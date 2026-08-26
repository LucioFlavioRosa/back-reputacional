"""O que a mensagem de erro conta, e para quem.

A tensão que estes testes fixam: `"Analista só edita os registros que criou"` é
AJUDA para quem é da casa e MAPA DO MODELO DE PERMISSÃO para quem é de fora. E
tornar tudo genérico quebraria o produto — `"UF inválida: 'XX'"` é o que faz o
formulário ser usável.

O corte não é por público, é pelo que a mensagem descreve.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.erros import registrar_tratadores
from app.dominio.erros import (
    NaoAutorizado,
    NaoEncontrado,
    RegraViolada,
)

# -- a política, no domínio ----------------------------------------------------


def test_erro_de_validacao_e_especifico_para_todos():
    """Descreve o PEDIDO, e quem enviou já sabe o que enviou.

    Trocar por "requisição inválida" transformaria cada erro de digitação num
    chamado de suporte.
    """
    erro = RegraViolada("UF inválida: 'XX'. Use uma das 27 siglas.")
    assert erro.publica(externo=True) == str(erro)
    assert erro.publica(externo=False) == str(erro)


def test_nao_encontrado_e_generico_para_todos():
    """As três causas — não existe, arquivado, fora do alcance — dão a MESMA
    resposta.

    Distinguir "não existe" de "existe e você não pode ver" entrega a segunda
    informação de graça, e transforma o 404 num oráculo de existência.
    """
    erro = NaoEncontrado("Interação 3f2a-... não encontrada.")
    assert erro.publica(externo=True) == "Registro não encontrado."
    assert erro.publica(externo=False) == "Registro não encontrado."


def test_id_nao_volta_na_resposta():
    """Ecoar entrada do usuário numa resposta é hábito que se paga caro."""
    erro = NaoEncontrado("Interação 11111111-2222-3333-4444-555555555555 não encontrada.")
    assert "11111111" not in erro.publica(externo=False)


def test_regra_de_permissao_e_generica_so_para_quem_e_de_fora():
    erro = NaoAutorizado("Analista só edita os registros que criou.")
    assert erro.publica(externo=False) == "Analista só edita os registros que criou."
    assert erro.publica(externo=True) == "Você não tem permissão para esta operação."


def test_mensagem_sobre_o_proprio_pedido_e_especifica_para_todos():
    """A distinção que nasceu de um teste quebrado.

    A política inicial engolia a mensagem do CSRF. "Você não tem permissão"
    faria alguém com a sessão vencida ficar clicando sem nunca pensar em
    recarregar — a instrução vira beco sem saída.
    """
    erro = NaoAutorizado(
        "Token de verificação ausente. Recarregue a página.", sobre_o_pedido=True
    )
    assert erro.publica(externo=True) == str(erro)
    assert erro.publica(externo=False) == str(erro)


# -- a política, na resposta HTTP ---------------------------------------------


def app_com(erro: Exception, externo: bool | None) -> TestClient:
    """Uma aplicação mínima que levanta o erro pedido.

    `externo=None` simula o caso em que a identidade ainda NÃO foi resolvida —
    falha no meio da própria autenticação, por exemplo.
    """
    aplicacao = FastAPI()
    registrar_tratadores(aplicacao)

    @aplicacao.middleware("http")
    async def carimbar(requisicao, seguir):  # noqa: ANN001
        if externo is not None:
            # A forma REAL de `UsuarioAtual`, e não só `externo`: um falso
            # parcial escondeu, uma vez, que o tratador estourava ao ler campos
            # que ele não tinha.
            requisicao.state.usuario = type(
                "U", (), {"externo": externo, "id": uuid4(), "email": "x@aegea.com.br"}
            )()
        return await seguir(requisicao)

    @aplicacao.get("/x")
    def rota() -> None:
        raise erro

    return TestClient(aplicacao, raise_server_exceptions=False)


def test_resposta_para_quem_e_da_casa_traz_o_detalhe():
    resposta = app_com(NaoAutorizado("Analista só edita o que criou."), externo=False).get("/x")
    assert resposta.status_code == 403
    assert resposta.json()["detalhe"] == "Analista só edita o que criou."


def test_resposta_para_quem_e_de_fora_e_generica():
    resposta = app_com(NaoAutorizado("Analista só edita o que criou."), externo=True).get("/x")
    assert resposta.status_code == 403
    assert resposta.json()["detalhe"] == "Você não tem permissão para esta operação."
    assert "Analista" not in resposta.text


def test_identidade_desconhecida_recebe_a_versao_generica():
    """Na dúvida, o lado seguro.

    Uma mensagem específica a mais para alguém de fora custa mais do que uma
    genérica a mais para alguém da casa.
    """
    resposta = app_com(NaoAutorizado("Analista só edita o que criou."), externo=None).get("/x")
    assert resposta.json()["detalhe"] == "Você não tem permissão para esta operação."


def test_toda_resposta_de_erro_leva_referencia():
    """Com mensagem genérica, é o único fio entre a reclamação e o log.

    Sem ela, "você não tem permissão" é indistinguível de todos os outros do
    dia, e o suporte não tem por onde começar.
    """
    resposta = app_com(NaoAutorizado("qualquer"), externo=True).get("/x")
    referencia = resposta.json()["referencia"]
    assert len(referencia) == 8


def test_referencias_sao_diferentes_entre_requisicoes():
    cliente = app_com(NaoAutorizado("qualquer"), externo=True)
    primeira = cliente.get("/x").json()["referencia"]
    segunda = cliente.get("/x").json()["referencia"]
    assert primeira != segunda


def test_o_log_guarda_a_mensagem_completa():
    """O que o usuário não vê precisa continuar existindo em algum lugar.

    Uma política que apaga a informação em vez de esconder tornaria impossível
    investigar a reclamação que ela mesma provoca.

    Não usa `caplog`: ele depende de o logger propagar para a raiz, e
    `configurar_observabilidade` mexe nisso. O teste passava sozinho e falhava
    na suíte completa — que é o pior tipo de teste. Um handler anexado ao logger
    de fato usado não depende de configuração nenhuma.
    """
    import logging

    capturadas: list[str] = []

    class Capturador(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            # `getMessage()` aplica os argumentos; ler `msg` cru devolveria o
            # gabarito com `%s` e o teste passaria sem provar nada.
            capturadas.append(registro.getMessage())

    logger = logging.getLogger("painel_reputacional.erros")
    capturador = Capturador()
    logger.addHandler(capturador)
    try:
        app_com(NaoAutorizado("Analista só edita o que criou."), externo=True).get("/x")
    finally:
        logger.removeHandler(capturador)

    assert any("Analista só edita o que criou." in linha for linha in capturadas)


def test_validacao_chega_inteira_mesmo_para_quem_e_de_fora():
    """O formulário precisa funcionar para todo mundo."""
    resposta = app_com(RegraViolada("UF inválida: 'XX'."), externo=True).get("/x")
    assert resposta.status_code == 422
    assert "UF inválida" in resposta.json()["detalhe"]


def test_o_tratador_nunca_estoura(caplog):
    """Um tratador de erro que lança transforma todo 403 num 500.

    E a falha aparece longe da causa: quem investiga vê "erro interno" numa
    rota que só deveria recusar acesso. É o único lugar do sistema onde vale ser
    paranoico com a FORMA do que chega — qualquer coisa colocada em
    `request.state.usuario` passa por aqui.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    aplicacao = FastAPI()
    registrar_tratadores(aplicacao)

    @aplicacao.middleware("http")
    async def carimbar(requisicao, seguir):  # noqa: ANN001
        # Um objeto incompleto — foi assim que o defeito apareceu.
        requisicao.state.usuario = object()
        return await seguir(requisicao)

    @aplicacao.get("/x")
    def rota() -> None:
        raise NaoAutorizado("qualquer")

    resposta = TestClient(aplicacao, raise_server_exceptions=False).get("/x")
    assert resposta.status_code == 403, "o tratador estourou e virou 500"


def test_o_log_diz_quem_recebeu_o_403():
    """Sem isto, "403 em rajada de um mesmo usuário" é impossível de consultar.

    O log dizia que houve quarenta 403 e não dizia se foram quarenta pessoas ou
    uma tentando quarenta portas.
    """
    import logging
    from uuid import uuid4

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    quem = uuid4()
    capturados: list[logging.LogRecord] = []

    class Capturador(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            capturados.append(registro)

    aplicacao = FastAPI()
    registrar_tratadores(aplicacao)

    @aplicacao.middleware("http")
    async def carimbar(requisicao, seguir):  # noqa: ANN001
        requisicao.state.usuario = type(
            "U", (), {"id": quem, "email": "externo@agencia.com.br", "externo": True}
        )()
        return await seguir(requisicao)

    @aplicacao.get("/x")
    def rota() -> None:
        raise NaoAutorizado("sonda de permissão")

    logger = logging.getLogger("painel_reputacional.erros")
    capturador = Capturador()
    logger.addHandler(capturador)
    try:
        TestClient(aplicacao, raise_server_exceptions=False).get("/x")
    finally:
        logger.removeHandler(capturador)

    registro = capturados[-1]
    assert registro.usuario_id == str(quem)
    assert registro.usuario_email == "externo@agencia.com.br"
    assert registro.externo is True
