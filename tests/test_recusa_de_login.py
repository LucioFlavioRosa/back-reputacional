"""Quem NÃO entra — e que a regra é a mesma nas duas portas.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
A plataforma vai passar a ter só SSO. A pergunta que o dono do produto fez foi
exatamente a certa: "hoje quem não tem cadastro não consegue entrar; quando
mudarmos para o SSO isso continua acontecendo?"

A resposta estava no código e não estava em teste nenhum. `test_oidc.py` cobre
a validação do token — assinatura, emissor, `nonce`, prazo — e para aí, antes
da decisão de autorizar. As referências a `NEGADO_SEM_PAPEL` no resto da suíte
chamam a função de auditoria DIRETAMENTE, sem passar por rota.

Ou seja: sem este arquivo, a garantia seria verdadeira por acidente de
leitura, e quebraria em silêncio no dia da virada para só-SSO — que é o pior
dia possível para descobrir.

`ativo` NA DECISÃO
------------------
A conferência é em `_motivo_da_recusa`, e não só dentro de `autenticar()`: o
caminho do SSO não passa por lá. Confiar na porta da senha faz desativar
alguém PARECER que funciona — e a senha é justamente o que vai embora.

Como não existe apagar pessoa (`interacao.criado_por` e mais nove chaves
apontam para `usuario`), desativar é a ÚNICA forma de remover alguém. Ela
pararia de surtir efeito no login exatamente quando virasse a única forma.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api import acesso
from app.api.acesso import _motivo_da_recusa, _texto_da_recusa
from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.casos_de_uso import registrar_acesso
from app.casos_de_uso.provisionar_usuario import _papel_de
from app.configuracao import obter_configuracao
from app.dominio.identidade import UsuarioAtual
from app.seguranca import sessao_assinada
from app.seguranca.cache_de_autorizacao import limpar_todos
from app.seguranca.oidc import Identidade
from main import app
from tests.test_acesso_http import SEGREDO, configuracao_real
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


# As fixtures moram em `test_acesso_http.py` e o pytest nao as compartilha
# entre modulos. Repetidas aqui de proposito, e nao movidas para um
# `conftest.py`: mexer no que 494 testes usam para acrescentar um arquivo e
# trocar um risco pequeno por um grande.


@pytest.fixture
def marca():
    """Um sufixo por teste, para a limpeza saber o que e dela."""
    return uuid4().hex[:8]


@pytest.fixture
def sessao(marca):
    """Compromete DE VERDADE, e limpa depois — e a razao importa.

    A sessao transacional que o resto da suite usa nao serve aqui.
    `registrar_e_confirmar()` grava a trilha de recusa numa sessao SEPARADA,
    de proposito, para a recusa sobreviver ao rollback do pedido. Essa segunda
    sessao nao enxerga um usuario que so existe dentro de uma transacao
    aberta, e o `insert` em `acesso_log` morre em
    `acesso_log_usuario_id_fkey`.

    Tentar contornar escrevendo o usuario por uma terceira conexao trava: ela
    espera o lock que a transacao do teste segura.

    Entao aqui e o caminho honesto — commit real, limpeza por marca no fim.
    """
    sessao = Session(bind=_engine, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.rollback()
        sessao.close()
        with Session(bind=_engine) as limpeza:
            alvo = {"m": f"%{marca}%"}
            limpeza.execute(
                text(
                    "delete from acesso_log where email_tentado like :m "
                    "or usuario_id in (select id from usuario where email like :m)"
                ),
                alvo,
            )
            limpeza.execute(
                text(
                    "delete from usuario_auditoria where usuario_id in "
                    "(select id from usuario where email like :m)"
                ),
                alvo,
            )
            limpeza.execute(text("delete from usuario where email like :m"), alvo)
            limpeza.commit()


@pytest.fixture(autouse=True)
def _cache_limpo():
    limpar_todos()
    yield
    limpar_todos()


@pytest.fixture
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = configuracao_real
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# -- a política, nua -----------------------------------------------------------
#
# `_motivo_da_recusa` é o ÚNICO lugar onde se decide quem entra, e as duas
# portas passam por ele. Testá-lo é testar as duas.


def _pessoa(**ajustes) -> UsuarioAtual:
    base = UsuarioAtual(
        id=uuid4(),
        nome="Pessoa da Aegea",
        email="pessoa@aegea.com.br",
        papel=None,
    )
    return replace(base, **ajustes)


def test_sem_papel_nao_entra():
    """O caso do dono do produto: e-mail corporativo, ninguém concedeu nada."""
    assert _motivo_da_recusa(_pessoa()) == registrar_acesso.NEGADO_SEM_PAPEL


def test_desativado_nao_entra_mesmo_com_papel(sessao):
    """A regressão que este arquivo existe para impedir.

    Conferido `ativo` só dentro de `autenticar()`, na porta da senha, uma conta
    desativada COM papel passa por `_motivo_da_recusa` sem ser notada — e o SSO
    usa só essa função.
    """
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    desativada = _pessoa(papel=_papel_de(sessao, papel.id), ativo=False)
    assert desativada.papel is not None, "o caso só vale com papel concedido"
    assert _motivo_da_recusa(desativada) == registrar_acesso.NEGADO_INATIVO


def test_desativado_vence_sem_papel_na_trilha(sessao):
    """A ORDEM importa, e não é estética.

    Desativado E sem papel deve registrar `negado_inativo`. Dissesse
    `negado_sem_papel`, a trilha afirmaria que ninguém nunca concedeu acesso a
    essa pessoa — quando na verdade alguém a removeu. É a trilha que se lê
    depois de um incidente, e ela precisa dizer o que houve.
    """
    assert (
        _motivo_da_recusa(_pessoa(ativo=False)) == registrar_acesso.NEGADO_INATIVO
    )


def test_prazo_vencido_nao_entra(sessao):
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    vencida = _pessoa(
        papel=_papel_de(sessao, papel.id),
        acesso_expira_em=date(2020, 1, 1),
    )
    assert _motivo_da_recusa(vencida) == registrar_acesso.NEGADO_VENCIDO


def test_quem_esta_em_ordem_entra(sessao):
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    liberada = _pessoa(papel=_papel_de(sessao, papel.id))
    assert _motivo_da_recusa(liberada) is None


@pytest.mark.parametrize(
    ("estado", "trecho"),
    [
        ({"ativo": False}, "desativada"),
        ({}, "ainda não foi liberado"),
    ],
)
def test_a_mensagem_diz_o_que_fazer(estado, trecho):
    """Específica de propósito: quem chega aqui já provou quem é.

    Uma recusa vaga produz um chamado; esta diz a quem pedir.
    """
    texto = _texto_da_recusa(_pessoa(**estado))
    assert trecho in texto
    assert "coordenação do painel" in texto


# -- a porta do SSO, de ponta a ponta -----------------------------------------
#
# Aqui está o valor real do arquivo. O `provisionar()` roda de verdade, a rota
# decide de verdade; o que é falso é só o servidor da Microsoft.


class _EntraFalso:
    """Devolve a identidade combinada, sem sair da máquina."""

    def __init__(self, identidade: Identidade) -> None:
        self._identidade = identidade

    def trocar_codigo(self, **_):  # noqa: ANN003
        return "id-token-que-nao-sera-lido"

    def validar(self, _token, *, nonce):  # noqa: ANN001
        return self._identidade


def _cookie_de_pedido(estado: str) -> str:
    """O mesmo que `/auth/login` grava, montado à mão.

    O `csrf` carrega `estado|nonce|verificador|redirect` — quatro campos, e o
    `split("|", 3)` da rota exige exatamente esta forma.
    """
    return sessao_assinada.assinar(
        sessao_assinada.Sessao(
            usuario_id=uuid4(),
            expira_em=int(datetime.now(UTC).timestamp()) + 600,
            csrf=f"{estado}|nonce-de-teste|verificador-de-teste|",
            tipo=sessao_assinada.TIPO_PEDIDO,
        ),
        SEGREDO,
    )


def _chamar_callback(cliente, monkeypatch, identidade: Identidade):
    monkeypatch.setattr(
        acesso, "cliente_entra", lambda _configuracao: _EntraFalso(identidade)
    )
    estado = secrets.token_urlsafe(16)
    cliente.cookies.set(acesso.COOKIE_DO_PEDIDO, _cookie_de_pedido(estado))
    return cliente.get(
        f"/api/auth/callback?code=qualquer&state={estado}", follow_redirects=False
    )


def test_sso_recusa_quem_nunca_recebeu_papel(cliente, sessao, marca, monkeypatch):
    """A pergunta do dono do produto, respondida pela porta que vai sobrar.

    Pessoa com e-mail da Aegea, autenticada pelo Entra ID, sem concessao
    nenhuma: entra no BANCO e nao entra na PLATAFORMA.
    """
    email = f"{uuid4().hex[:6]}.{marca}@aegea.com.br"
    identidade = Identidade(
        entra_object_id=f"oid-{uuid4().hex}", email=email, nome="Recem-chegada"
    )

    resposta = _chamar_callback(cliente, monkeypatch, identidade)

    # 303, e não 403: o navegador chega aqui por navegação de topo, vinda do
    # Entra ID — um 403 cru apareceria como PÁGINA, no lugar do site. A recusa
    # vira redirecionamento de volta ao front com a mensagem, para a tela de
    # login mostrar na caixa de aviso que já tem pronta.
    assert resposta.status_code == 303
    assert "nao foi liberado" in _sem_acento(_mensagem_do_redirecionamento(resposta))

    # O OUTRO LADO DA MOEDA, e o que faz o fluxo do produto funcionar: a
    # pessoa recusada PRECISA existir depois, senao quem administra acessos
    # nao teria a quem conceder — teria de pedir que ela tentasse de novo, e a
    # tentativa seria negada de novo. E o `commit()` antes da decisao.
    registro = sessao.scalars(select(Usuario).where(Usuario.email == email)).first()
    assert registro is not None, (
        "a pessoa recusada sumiu do banco; o admin nao tem a quem conceder"
    )
    assert registro.papel_id is None


def test_sso_recusa_conta_desativada(cliente, sessao, marca, monkeypatch):
    """O buraco que a virada abriria.

    Antes da correcao esta rota devolvia 303 e gravava o cookie: nada no
    caminho do SSO olhava `ativo`. A pessoa removida entrava e ainda tinha o
    `ultimo_acesso_em` carimbado — aparecendo na tela de acessos como quem
    acabou de entrar.
    """
    oid = f"oid-{uuid4().hex}"
    email = f"{uuid4().hex[:6]}.{marca}@aegea.com.br"
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    sessao.add(
        Usuario(
            entra_object_id=oid,
            email=email,
            nome="Pessoa Removida",
            papel_id=papel.id,
            ativo=False,
        )
    )
    sessao.commit()

    resposta = _chamar_callback(
        cliente,
        monkeypatch,
        Identidade(entra_object_id=oid, email=email, nome="Pessoa Removida"),
    )

    # 303 é a resposta correta agora (ver `app/api/acesso.py` — recusa vira
    # redirecionamento com mensagem, não mais 403 cru). O que este teste
    # protege continua intacto: SEM o cookie de sessão, a conta desativada não
    # entra nem com o código mudando de 403 para 303.
    assert resposta.status_code == 303, (
        "conta desativada entrou pelo SSO — desativar deixou de remover"
    )
    assert sessao_assinada.NOME_DO_COOKIE not in resposta.cookies, (
        "conta desativada recebeu cookie de sessão pelo SSO"
    )
    assert "desativada" in _mensagem_do_redirecionamento(resposta)

    registro = sessao.scalars(
        select(Usuario).where(Usuario.entra_object_id == oid)
    ).first()
    assert registro.ultimo_acesso_em is None, (
        "o login recusado carimbou ultimo acesso: a pessoa removida aparece "
        "na tela de acessos como quem acabou de entrar"
    )


# -- a porta da senha ----------------------------------------------------------


def test_senha_recusa_quem_nao_recebeu_papel(cliente, sessao, marca):
    """A mesma regra, pela porta que existe hoje.

    Existe para provar que as duas concordam. No dia em que a rota de senha
    sair, este teste sai com ela — e o do SSO, acima, continua.
    """
    from app.casos_de_uso.autenticar_por_senha import gerar_hash

    email = f"{uuid4().hex[:6]}.{marca}@aegea.com.br"
    sessao.add(
        Usuario(
            email=email,
            nome="Sem Papel",
            # `n` minusculo de proposito: o scrypt de producao custa ~100ms, e
            # o custo existe para quem ataca, nao para a suite.
            senha_hash=gerar_hash("uma-senha-bem-longa", n=2**4),
            papel_id=None,
        )
    )
    sessao.commit()

    resposta = cliente.post(
        "/api/auth/senha", json={"email": email, "senha": "uma-senha-bem-longa"}
    )
    assert resposta.status_code == 403
    assert "nao foi liberado" in _sem_acento(resposta.json()["detalhe"])


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def _mensagem_do_redirecionamento(resposta) -> str:
    """A mensagem de recusa que o `/auth/callback` devolve no `?erro=` do
    redirecionamento — e não mais num corpo JSON cru. Ver `app/api/acesso.py`."""
    from urllib.parse import parse_qs, urlsplit

    query = parse_qs(urlsplit(resposta.headers["location"]).query)
    return query["erro"][0]


# -- a recusa precisa dizer o que fazer ---------------------------------------
#
# Sem mensagem própria, as recusas do callback saem todas como "Você não tem
# permissão para esta operação". Num login isso é beco sem saída — a pessoa
# conclui que o problema é o acesso dela e abre chamado, quando bastava tentar
# de novo.


def test_pedido_de_login_expirado_diz_o_que_fazer(cliente):
    """Sem o cookie de pedido, a instrução tem de chegar.

    É o caso mais comum de todos: a aba ficou aberta tempo demais entre clicar
    em "entrar" e voltar do Entra ID.
    """
    resposta = cliente.get(
        "/api/auth/callback?code=qualquer&state=qualquer", follow_redirects=False
    )
    assert resposta.status_code == 303
    detalhe = _mensagem_do_redirecionamento(resposta)
    assert "Tente entrar de novo" in detalhe, (
        f"a instrução não chegou; a pessoa leu {detalhe!r}"
    )


def test_a_guarda_de_cada_requisicao_tambem_barra_desativado(sessao, marca):
    """A MESMA política, no outro lugar onde ela mora.

    `_exigir_autorizacao_valida()` protege toda requisição autenticada, e
    conferia só "sem papel" e "vencido". Duas cópias da mesma política
    discordando foi exatamente o que produziu o buraco original — `ativo`
    valendo numa porta e não na outra.
    """
    from app.api.dependencias import _exigir_autorizacao_valida
    from app.dominio.erros import NaoAutorizado

    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    removida = _pessoa(papel=_papel_de(sessao, papel.id), ativo=False)

    with pytest.raises(NaoAutorizado) as erro:
        _exigir_autorizacao_valida(removida)

    assert "desativada" in str(erro.value)
    assert erro.value.sobre_o_pedido, (
        "a mensagem seria trocada pela genérica e viraria beco sem saída"
    )

# == AS RECUSAS QUE FALTAVAM, E O QUE A PESSOA LÊ EM CADA UMA ==================
#
# ACHADO DE REVISÃO. Os testes acima cobrem as três recusas de AUTORIZAÇÃO (sem
# papel, desativado, prazo vencido) e uma de pedido (cookie ausente). Ficaram de
# fora as recusas de AUTENTICAÇÃO — as que acontecem antes de saber quem é a
# pessoa — e é nelas que o risco de vazar está, porque são as que têm um motivo
# técnico por trás.
#
# O QUE CADA UMA PRECISA PROVAR, e são duas coisas diferentes: que a pessoa
# recebe uma instrução (303 com mensagem, nunca JSON cru no lugar do site), e
# que a mensagem NÃO carrega o motivo técnico — que é o que ajudaria quem está
# tentando forjar um token a descobrir o que falhou.


#: SENTINELAS LONGAS, e a razão é que a configuração de teste normal tem tenant
#: `"t"`, client id `"c"` e secret `"s"` — uma letra cada. Procurar uma letra
#: dentro de uma frase em português reprova sempre; procurar por palavra inteira
#: não pega `tenant=t` nem JSON nem URL, que são as formas de um vazamento real.
#: Com um valor improvável, a conferência volta a ser `valor not in mensagem`,
#: crua, e passa a pegar qualquer forma. Achado de revisão.
TENANT_SENTINELA = "tenant-que-nao-pode-vazar-9f3a1c"
CLIENT_SENTINELA = "client-id-que-nao-pode-vazar-7b2e4d"
SECRETO_SENTINELA = "client-secret-que-nao-pode-vazar-1a5c8f"


@pytest.fixture
def cliente_com_sentinelas(sessao):
    """O mesmo cliente, com tenant/client/secret improváveis de achar por acaso."""
    app.dependency_overrides[obter_sessao] = lambda: sessao
    #: `model_copy`, e não `dataclasses.replace`: `Configuracao` é um
    #: `BaseSettings` do pydantic, não uma dataclass.
    app.dependency_overrides[obter_configuracao] = lambda: configuracao_real().model_copy(
        update={
            "entra_tenant_id": TENANT_SENTINELA,
            "entra_client_id": CLIENT_SENTINELA,
            "entra_client_secret": SECRETO_SENTINELA,
        }
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _destino_do_redirecionamento(resposta) -> str:
    """O endereço, sem a query. É o que diz se o redirect é aberto."""
    from urllib.parse import urlsplit

    partes = urlsplit(resposta.headers["location"])
    return f"{partes.scheme}://{partes.netloc}{partes.path}"


class _EntraQueFalha:
    """O provedor responde, e a validação do token recusa.

    A mensagem da exceção é deliberadamente reveladora — é o que o código real
    produz, e é exatamente o que não pode chegar à tela.
    """

    MOTIVO = "assinatura inválida: kid=abc123 não está no JWKS de t"

    def trocar_codigo(self, **_):  # noqa: ANN003
        return "id-token-forjado"

    def validar(self, _token, *, nonce):  # noqa: ANN001
        from app.seguranca.oidc import FalhaNoLogin

        raise FalhaNoLogin(_EntraQueFalha.MOTIVO)


def _chamar_callback_cru(cliente, consulta: str, *, redirect: str = "") -> object:
    """Chama o callback com um cookie de pedido válido e a query que se quiser.

    O `redirect` vai para o quarto campo do `csrf`, que é de onde o SUCESSO tira
    o destino. Numa recusa ele tem de ser ignorado — ver o teste do destino.
    """
    estado = secrets.token_urlsafe(16)
    cookie = sessao_assinada.assinar(
        sessao_assinada.Sessao(
            usuario_id=uuid4(),
            expira_em=int(datetime.now(UTC).timestamp()) + 600,
            csrf=f"{estado}|nonce-de-teste|verificador-de-teste|{redirect}",
            tipo=sessao_assinada.TIPO_PEDIDO,
        ),
        SEGREDO,
    )
    cliente.cookies.set(acesso.COOKIE_DO_PEDIDO, cookie)
    return cliente.get(
        f"/api/auth/callback?{consulta.format(estado=estado)}",
        follow_redirects=False,
    )


def test_o_entra_recusando_nao_devolve_json_no_lugar_do_site(cliente):
    """O provedor manda `error=`, e a pessoa tem de voltar à tela de login.

    É o caso de quem clica em "cancelar" na tela da Microsoft, ou de quem o
    Entra barra por política do tenant. Sem o redirecionamento, o navegador
    mostraria o JSON da exceção COMO PÁGINA.
    """
    resposta = _chamar_callback_cru(cliente, "error=access_denied&state={estado}")

    assert resposta.status_code == 303
    assert "Entra ID recusou" in _mensagem_do_redirecionamento(resposta)
    #: E o código do provedor não é repassado: `access_denied` é vocabulário
    #: dele, não da pessoa, e ela não tem o que fazer com isso.
    assert "access_denied" not in _mensagem_do_redirecionamento(resposta)


def test_state_divergente_e_csrf_no_login_e_a_mensagem_nao_explica(cliente):
    """`state` que não bate é alguém tentando fazer a vítima entrar em OUTRA conta.

    O ataque é este: o atacante inicia o login na conta dele, guarda o `code`, e
    faz a vítima abrir o callback com esse código. Se passasse, a vítima estaria
    dentro da conta do atacante, vendo o painel como se fosse o dela.

    A mensagem é vaga de propósito, e aqui o vago PROTEGE: dizer "o state não
    bate" ensina quem está tentando onde a conferência está.
    """
    resposta = _chamar_callback_cru(cliente, "code=qualquer&state=outro-estado")

    assert resposta.status_code == 303
    mensagem = _mensagem_do_redirecionamento(resposta)
    assert "Pedido de login inválido" in mensagem
    for termo in ("state", "csrf", "nonce", "verificador", "cookie"):
        assert termo not in mensagem.lower(), (
            f"a mensagem contou qual conferência falhou: {mensagem!r}"
        )


def test_sem_code_nenhum_tambem_e_recusado(cliente):
    """O callback aberto na mão, sem código: não é erro de servidor, é recusa.

    Vale testar separado do `state` divergente porque é a MESMA guarda com outra
    perna (`not code or not state or ...`), e alguém que mexa nela pode derrubar
    só uma das duas.
    """
    resposta = _chamar_callback_cru(cliente, "state={estado}")

    assert resposta.status_code == 303
    assert "Pedido de login inválido" in _mensagem_do_redirecionamento(resposta)


def test_a_validacao_do_token_falhando_nao_conta_o_que_falhou(cliente, monkeypatch):
    """O MOTIVO VAI PARA O LOG, NÃO PARA A TELA — e este é o teste de vazamento.

    Quando a validação do token recusa, o motivo é preciso: "assinatura inválida:
    kid=abc123 não está no JWKS de t". Isso é ouro para quem está tentando forjar
    um token — diz exatamente qual conferência falhou e com que dado.

    Então o teste exige as duas metades: a pessoa lê uma frase sem conteúdo
    técnico, e quem opera encontra o motivo no log.
    """
    import logging

    #: NÃO USA `caplog`, e a razão está escrita em `test_politica_de_erro.py`:
    #: ele depende de o logger propagar para a raiz, e
    #: `configurar_observabilidade` põe `propagate = False`. Um handler no
    #: logger de fato usado não depende de configuração nenhuma.
    capturadas: list[str] = []

    class Capturador(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            #: `getMessage()` aplica os argumentos; `msg` cru devolveria o
            #: gabarito com `%s` e o teste passaria sem provar nada.
            capturadas.append(registro.getMessage())

    monkeypatch.setattr(
        acesso, "cliente_entra", lambda _configuracao: _EntraQueFalha()
    )
    registro = logging.getLogger("painel_reputacional.acesso")
    capturador = Capturador()
    registro.addHandler(capturador)
    try:
        resposta = _chamar_callback_cru(cliente, "code=qualquer&state={estado}")
    finally:
        registro.removeHandler(capturador)

    assert resposta.status_code == 303
    mensagem = _mensagem_do_redirecionamento(resposta)
    assert "Não foi possível concluir o login" in mensagem
    #: nada do motivo técnico na tela
    for termo in ("kid", "abc123", "JWKS", "assinatura"):
        assert termo not in mensagem, (
            f"o motivo técnico chegou à tela: {mensagem!r}"
        )
    #: e o motivo no log, senão ninguém diagnostica
    assert any(_EntraQueFalha.MOTIVO in linha for linha in capturadas), (
        f"o motivo não foi registrado; a recusa ficou sem diagnóstico: {capturadas}"
    )


@pytest.mark.parametrize(
    ("consulta", "sem_cookie"),
    [
        ("error=access_denied&state={estado}", False),
        ("code=qualquer&state=outro-estado", False),
        ("state={estado}", False),
        #: O COOKIE DE PEDIDO AUSENTE também cai no mesmo `except NaoAutorizado`,
        #: e sem ele a frase "todas as recusas do callback" não seria literal.
        #: Achado de revisão.
        ("code=qualquer&state=qualquer", True),
    ],
)
def test_nenhuma_recusa_leva_segredo_na_mensagem(
    cliente_com_sentinelas, consulta, sem_cookie
):
    """A regra, varrida sobre TODAS as recusas do callback de uma vez.

    Cada teste acima prova o seu caso; este prova a CLASSE. Um caminho de recusa
    novo que alguém acrescente com a mensagem errada cai aqui, mesmo que ninguém
    se lembre de escrever o teste dele.

    A lista é do que existe nesta rota e não pode sair: o segredo da sessão, o
    segredo do cliente, o tenant, o client id, e o código do provedor. Os três
    do meio vêm como SENTINELA — ver o comentário em `TENANT_SENTINELA`.
    """
    if sem_cookie:
        cliente_com_sentinelas.cookies.clear()
        resposta = cliente_com_sentinelas.get(
            f"/api/auth/callback?{consulta}", follow_redirects=False
        )
    else:
        resposta = _chamar_callback_cru(cliente_com_sentinelas, consulta)

    assert resposta.status_code == 303
    mensagem = _mensagem_do_redirecionamento(resposta)
    proibidos = {
        "segredo da sessão": SEGREDO,
        "tenant": TENANT_SENTINELA,
        "client id": CLIENT_SENTINELA,
        "client secret": SECRETO_SENTINELA,
    }
    for nome, valor in proibidos.items():
        assert valor not in mensagem, f"a mensagem vazou o {nome}"
    assert "access_denied" not in mensagem, "a mensagem repetiu o erro do provedor"
    assert "Traceback" not in mensagem

    #: E AS OUTRAS TRÊS GARANTIAS, na mesma varredura: destino fixo, sem sessão,
    #: e o cookie de pedido apagado. Elas valiam uma recusa cada; agora valem a
    #: classe toda, que é o que o nome do teste promete.
    assert _destino_do_redirecionamento(resposta) == "https://painel.aegea.com.br/"
    gravados = resposta.headers.get_list("set-cookie")
    assert not any(
        sessao_assinada.NOME_DO_COOKIE in c and "Max-Age=0" not in c for c in gravados
    ), f"a recusa gravou sessão: {gravados}"
    assert any(
        acesso.COOKIE_DO_PEDIDO in c and "max-age=0" in c.lower() for c in gravados
    ), f"o cookie de pedido não foi apagado: {gravados}"


# == O DESTINO DO REDIRECIONAMENTO ============================================


def test_a_recusa_volta_sempre_para_o_front_e_nao_para_onde_pedirem(cliente):
    """O redirecionamento da recusa NÃO se deixa levar pela requisição.

    POR QUE ISTO MERECE TESTE: a mudança que introduziu o redirect é
    exatamente a forma de mudança que cria redirect aberto. O destino do
    SUCESSO passa por `destino_seguro()`, que recusa `scheme`, `netloc` e
    `//outro.site` — e tem teste. O da RECUSA é montado direto, com
    `url_do_front` fixo, e não tinha teste nenhum.

    Aqui o cookie de pedido carrega um destino externo no campo que o sucesso
    usa. A recusa tem de ignorá-lo: se um dia alguém "unificar" os dois
    caminhos passando o `redirect` para a recusa também, este teste cai — e é
    o único lugar que veria.
    """
    resposta = _chamar_callback_cru(
        cliente,
        "code=qualquer&state=outro-estado",
        redirect="https://sitedoatacante.example/colhe",
    )

    assert resposta.status_code == 303
    assert _destino_do_redirecionamento(resposta) == "https://painel.aegea.com.br/"
    assert "sitedoatacante" not in resposta.headers["location"]


def test_a_recusa_nao_concede_sessao(cliente):
    """Óbvio, e justamente por isso sem teste até agora.

    Um redirecionamento 303 PARECE um login que deu certo — mesmo status, mesmo
    destino. O que separa os dois é o cookie de sessão, e é só isso.
    """
    resposta = _chamar_callback_cru(cliente, "code=qualquer&state=outro-estado")

    gravados = resposta.headers.get_list("set-cookie")
    assert not any(
        sessao_assinada.NOME_DO_COOKIE in c and "Max-Age=0" not in c
        for c in gravados
    ), f"a recusa gravou sessão: {gravados}"


def test_a_recusa_apaga_o_cookie_do_pedido(cliente):
    """ACHADO DE REVISÃO: ele só era apagado no sucesso.

    O cookie de pedido vale dez minutos e carrega `estado|nonce|verificador`.
    Depois de uma recusa ele não serve para mais nada — mas sobrevivia, e com
    ele o mesmo pedido podia ser reapresentado ao callback por todo o prazo.

    Não concede sessão nenhuma (o teste acima prova), então o risco é de ruído e
    de replay, não de entrada indevida. Mas o sucesso já apaga, e a recusa não
    tinha motivo para não apagar — a assimetria era o defeito.
    """
    resposta = _chamar_callback_cru(cliente, "code=qualquer&state=outro-estado")

    apagados = [
        c
        for c in resposta.headers.get_list("set-cookie")
        if acesso.COOKIE_DO_PEDIDO in c
    ]
    assert apagados, "o cookie de pedido sobreviveu à recusa"
    assert any('Max-Age=0' in c or 'max-age=0' in c.lower() for c in apagados), (
        f"o cookie de pedido não foi apagado: {apagados}"
    )
