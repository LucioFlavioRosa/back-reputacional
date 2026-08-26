"""A sessão dentro da aplicação: cookie real, CSRF e redirecionamento.

Roda com `AUTH_MOCK=false`, que é o caminho de produção. O que não é exercitado
aqui é a ida ao Entra ID — essa vive em `test_oidc.py`, com chave RSA de
verdade. Daqui para a frente o que importa é o cookie que sobrou do login.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.acesso import destino_seguro
from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import (
    AcessoLog,
    Papel,
    Usuario,
)
from app.configuracao import Configuracao, obter_configuracao
from app.seguranca import sessao_assinada
from main import app
from tests.test_e2e_postgres import URL

SEGREDO = "segredo-de-teste-com-mais-de-trinta-e-dois-caracteres"

_engine = create_engine(URL, pool_pre_ping=True)


def configuracao_real() -> Configuracao:
    """`AUTH_MOCK=false`: o caminho de produção, sem ir ao Entra ID."""
    return Configuracao(
        auth_mock=False,
        sessao_secreta=SEGREDO,
        entra_tenant_id="t",
        entra_client_id="c",
        entra_client_secret="s",
        url_do_front="https://painel.aegea.com.br",
    )


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


@pytest.fixture
def usuario(sessao):
    """Alguém liberado, para o cookie apontar para uma pessoa real."""
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "coordenacao")).first()
    registro = Usuario(
        entra_object_id=f"oid-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@aegea.com.br",
        nome="Pessoa de Teste",
        papel_id=papel.id,
        acesso_irrestrito=True,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


@pytest.fixture
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = configuracao_real
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def cookie_de(usuario_id) -> str:
    return sessao_assinada.assinar(
        sessao_assinada.nova_sessao(usuario_id), SEGREDO
    )


# -- sem sessão não se entra ---------------------------------------------------


def test_sem_cookie_nao_le_nada(cliente):
    assert cliente.get("/api/interacoes").status_code == 403


def test_cookie_de_outro_segredo_nao_vale(cliente, usuario):
    forjado = sessao_assinada.assinar(
        sessao_assinada.nova_sessao(usuario.id), "outro-segredo-qualquer"
    )
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, forjado)
    assert cliente.get("/api/interacoes").status_code == 403


def test_cookie_de_usuario_inexistente_nao_vale(cliente):
    """Sessão bem assinada de alguém que não existe mais.

    O cookie continua válido; o que mudou foi o banco. Sem esta checagem, uma
    sessão emitida antes de a pessoa ser removida sobreviveria à remoção.
    """
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(uuid4()))
    assert cliente.get("/api/interacoes").status_code == 403


def test_com_cookie_valido_le(cliente, usuario):
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))
    assert cliente.get("/api/interacoes").status_code == 200


# -- CSRF ----------------------------------------------------------------------


def test_escrita_sem_token_anti_csrf_e_recusada(cliente, usuario):
    """`SameSite=Lax` não protege contra outro subdomínio de `aegea.com.br`.

    Para o navegador, `qualquercoisa.aegea.com.br` é o MESMO site — e a Aegea
    tem muitos. O cookie iria junto; o que falta ao atacante é o token.
    """
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))
    resposta = cliente.post("/api/interacoes", json={})
    assert resposta.status_code == 403
    assert "verificação" in resposta.json()["detalhe"].lower()


def test_token_anti_csrf_errado_e_recusado(cliente, usuario):
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))
    resposta = cliente.post(
        "/api/interacoes", json={}, headers={"X-CSRF-Token": "chute"}
    )
    assert resposta.status_code == 403


def test_token_anti_csrf_correto_passa_da_verificacao(cliente, usuario):
    """422 aqui é vitória: o corpo é que está vazio, o CSRF passou."""
    cookie = cookie_de(usuario.id)
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie)
    token = sessao_assinada.ler(cookie, SEGREDO).csrf

    resposta = cliente.post(
        "/api/interacoes", json={}, headers={"X-CSRF-Token": token}
    )
    assert resposta.status_code == 422


def test_leitura_nao_exige_token(cliente, usuario):
    """`GET` não altera estado; exigir cabeçalho nele quebraria a navegação."""
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))
    assert cliente.get("/api/interacoes").status_code == 200


# -- /api/eu -------------------------------------------------------------------


def test_eu_entrega_o_papel_e_o_token(cliente, usuario):
    """O token vive no cookie `httpOnly` e chega ao front por AQUI.

    É o que um site de outra origem não consegue: disparar a requisição ele
    consegue; ler a resposta, não — o CORS impede.
    """
    cookie = cookie_de(usuario.id)
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie)

    corpo = cliente.get("/api/eu").json()
    assert corpo["email"] == usuario.email
    assert corpo["papel"]["codigo"] == "coordenacao"
    assert corpo["csrf_token"] == sessao_assinada.ler(cookie, SEGREDO).csrf


def test_papel_revogado_vale_no_proximo_clique(cliente, usuario, sessao):
    """O motivo de o cookie NÃO carregar o papel.

    Se ele carregasse, tirar a permissão de alguém só surtiria efeito quando a
    sessão vencesse — até oito horas depois.
    """
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))
    assert cliente.get("/api/interacoes").status_code == 200

    usuario.papel_id = None
    sessao.flush()

    assert cliente.get("/api/interacoes").status_code == 403


# -- logout --------------------------------------------------------------------


def test_logout_apaga_o_cookie(cliente, usuario):
    cookie = cookie_de(usuario.id)
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie)
    token = sessao_assinada.ler(cookie, SEGREDO).csrf

    resposta = cliente.post("/api/auth/logout", headers={"X-CSRF-Token": token})
    assert resposta.status_code == 204
    assert "painel_sessao=" in resposta.headers.get("set-cookie", "")


def test_logout_sem_sessao_nao_e_erro(cliente):
    """Sair é idempotente: quem já está fora não precisa de erro para saber."""
    assert cliente.post("/api/auth/logout").status_code == 204


def test_logout_forjado_e_recusado(cliente, usuario):
    """Derrubar alguém no meio do trabalho é chateação real."""
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))
    assert cliente.post("/api/auth/logout").status_code == 403


# -- redirecionamento aberto ---------------------------------------------------


@pytest.mark.parametrize(
    "destino",
    [
        "https://sitedoatacante.com",
        "http://sitedoatacante.com/x",
        "//sitedoatacante.com",          # relativo de protocolo
        "https://painel.aegea.com.br.sitedoatacante.com",
        "javascript:alert(1)",
    ],
)
def test_redirecionamento_externo_e_recusado(destino):
    """O domínio do painel não pode virar trampolim.

    O link parece da Aegea, a pessoa faz o login de verdade, e é despejada em
    outro lugar — que ainda ganha o referrer. `//outro.site` é o caso que passa
    por quem só checa `startswith("/")`.
    """
    configuracao = configuracao_real()
    assert destino_seguro(destino, configuracao) == configuracao.url_do_front


@pytest.mark.parametrize(
    "pedido,esperado",
    [
        ("/painel", "https://painel.aegea.com.br/painel"),
        ("base", "https://painel.aegea.com.br/base"),
        (None, "https://painel.aegea.com.br"),
    ],
)
def test_redirecionamento_interno_e_preservado(pedido, esperado):
    assert destino_seguro(pedido, configuracao_real()) == esperado


# -- trilha de login -----------------------------------------------------------


def test_acesso_log_registra_recusa(cliente, sessao):
    """Toda tentativa vira uma linha em `acesso_log` (migration 0003).

    A tentativa NEGADA é a linha mais valiosa: login bem-sucedido é rotina;
    sequência de negados é sinal.
    """
    from app.casos_de_uso import registrar_acesso
    antes = sessao.scalar(text("select count(*) from acesso_log"))
    registrar_acesso.registrar(
        sessao,
        resultado=registrar_acesso.NEGADO_SEM_PAPEL,
        email_tentado="convidado@agencia.com.br",
        ip="203.0.113.9",
    )
    sessao.flush()

    depois = sessao.scalar(text("select count(*) from acesso_log"))
    assert depois == antes + 1

    linha = sessao.scalars(
        select(AcessoLog).order_by(AcessoLog.id.desc())
    ).first()
    assert linha.resultado == registrar_acesso.NEGADO_SEM_PAPEL
    assert linha.email_tentado == "convidado@agencia.com.br"


def test_recusa_sobrevive_ao_erro_que_a_rota_levanta(sessao):
    """A recusa fica gravada mesmo com a rota levantando erro.

    `obter_sessao` desfaz a transação em QUALQUER exceção, erro de domínio
    inclusive — e negar um login é exatamente levantar um erro de domínio. Sem
    cuidado, a linha seria escrita e desfeita milissegundos depois, deixando sem
    rastro justamente o evento que mais interessa.

    Por isso `registrar_e_confirmar` grava numa sessão própria, que não compartilha
    a sorte da transação do pedido.

    Este teste imita o ciclo da dependência: grava, levanta, desfaz. Se alguém
    trocar `registrar_e_confirmar` por `registrar`, ele cai.
    """
    from app.casos_de_uso import registrar_acesso
    from app.dominio.erros import NaoAutorizado

    engine = _engine
    marca = f"prova-{uuid4().hex[:8]}@agencia.com.br"

    propria = Session(bind=engine)
    try:
        registrar_acesso.registrar_e_confirmar(
            propria,
            resultado=registrar_acesso.NEGADO_SEM_PAPEL,
            email_tentado=marca,
        )
        raise NaoAutorizado("acesso não liberado")
    except NaoAutorizado:
        propria.rollback()   # o que a dependência faz em seguida
    finally:
        propria.close()

    with Session(bind=engine) as conferencia:
        quantas = conferencia.scalar(
            text("select count(*) from acesso_log where email_tentado = :e"),
            {"e": marca},
        )
        conferencia.execute(
            text("delete from acesso_log where email_tentado = :e"), {"e": marca}
        )
        conferencia.commit()

    assert quantas == 1, "a recusa sumiu no rollback"


def test_vocabulario_do_resultado_e_fechado_no_banco(sessao):
    """Texto livre viraria seis grafias da mesma coisa e nenhuma consulta confiável."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), sessao.begin_nested():
        sessao.execute(
            text("insert into acesso_log (resultado) values ('deu_ruim')")
        )


# -- o caminho do navegador, de ponta a ponta ---------------------------------


def test_preflight_libera_o_cabecalho_do_csrf(cliente):
    """O teste que faltava, e que teria pegado o defeito.

    Apertar a allowlist do CORS e depois criar uma proteção que usa um cabeçalho
    fora dela quebra TODA escrita — no preflight, com `400 Disallowed CORS
    headers`, antes de a requisição chegar à rota. Do lado do servidor não
    aparece nada, porque nada chegou.

    O teste anterior mandava o cabeçalho direto pelo TestClient, que não faz
    preflight. Provava que o token era aceito; não que o navegador o deixaria
    sair.
    """
    resposta = cliente.options(
        "/api/interacoes",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert resposta.status_code == 200, resposta.text
    permitidos = resposta.headers["access-control-allow-headers"].lower()
    assert "x-csrf-token" in permitidos


def test_escrita_completa_com_o_token_de_api_eu(cliente, usuario, semente_minima):
    """O fluxo inteiro: `/api/eu` devolve o token, a escrita usa, e cria mesmo.

    Terminar em 422 provava só que não era 403. Terminar em 201 prova que a
    proteção deixa o trabalho acontecer — que é a metade que costuma ser
    esquecida numa medida de segurança.
    """
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie_de(usuario.id))

    token = cliente.get("/api/eu").json()["csrf_token"]
    assert token, "/api/eu não devolveu token"

    resposta = cliente.post(
        "/api/interacoes",
        headers={"X-CSRF-Token": token},
        json={
            "frente": "governo",
            "data_interacao": "2026-05-07",
            "instituicao_id": str(semente_minima),
            "uf": "SP",
            "status": "atendido",
            "pauta": "Escrita com token de verdade",
        },
    )
    assert resposta.status_code == 201, resposta.text


@pytest.fixture
def semente_minima(sessao):
    from app.banco.tabelas_stakeholders import (
        Instituicao,
    )

    sufixo = uuid4().hex[:8]
    instituicao = Instituicao(
        nome=f"Órgão {sufixo}",
        nome_normalizado=f"orgao {sufixo}",
        tipo="orgao",
        uf="SP",
    )
    sessao.add(instituicao)
    sessao.flush()
    return instituicao.id


def test_callback_sem_cookie_de_pedido_deixa_rastro(cliente, sessao):
    """Este caminho de recusa não registrava nada.

    Cookie de pedido ausente, vencido, adulterado ou de outro tipo é justamente
    o que uma rajada de callbacks forjados produz. Aparecia só no log da
    aplicação — não na trilha consultável, que é onde alguém procuraria depois
    de um incidente.
    """
    with Session(bind=_engine) as conferencia:
        antes = conferencia.scalar(
            text("select count(*) from acesso_log where resultado = 'negado_no_provedor'")
        )

    resposta = cliente.get(
        "/api/auth/callback?code=inventado&state=inventado", follow_redirects=False
    )
    assert resposta.status_code == 403

    with Session(bind=_engine) as conferencia:
        depois = conferencia.scalar(
            text("select count(*) from acesso_log where resultado = 'negado_no_provedor'")
        )
        conferencia.execute(
            text("delete from acesso_log where resultado = 'negado_no_provedor'")
        )
        conferencia.commit()

    assert depois == antes + 1, "a recusa no callback não foi registrada"


@pytest.mark.parametrize("bruto", ["desconhecido", "testclient", "", None, "nao-e-ip"])
def test_endereco_ilegivel_vira_nulo_em_vez_de_explodir(bruto, sessao):
    """A coluna é `inet`, e `ip_do_cliente` nem sempre devolve um endereço.

    `"desconhecido"` é o que ele responde quando a conexão não expõe o cliente
    — situação real atrás de certos proxies. Como a gravação virou transação
    própria e acontece no caminho de RECUSA, um insert que estoura transforma
    negativa de login em 500: a pessoa vê "erro interno" em vez de "seu acesso
    não foi liberado", e a trilha continua sem a linha.
    """
    from app.casos_de_uso import registrar_acesso
    marca = f"ip-{uuid4().hex[:8]}@teste.com"
    registrar_acesso.registrar(
        sessao,
        resultado=registrar_acesso.NEGADO_NO_PROVEDOR,
        email_tentado=marca,
        ip=bruto,
    )
    sessao.flush()

    linha = sessao.scalars(
        select(AcessoLog).where(AcessoLog.email_tentado == marca)
    ).first()
    assert linha is not None
    assert linha.ip is None


def test_endereco_valido_e_preservado(sessao):
    from app.casos_de_uso import registrar_acesso
    marca = f"ip-{uuid4().hex[:8]}@teste.com"
    registrar_acesso.registrar(
        sessao,
        resultado=registrar_acesso.NEGADO_NO_PROVEDOR,
        email_tentado=marca,
        ip="203.0.113.9",
    )
    sessao.flush()

    linha = sessao.scalars(
        select(AcessoLog).where(AcessoLog.email_tentado == marca)
    ).first()
    assert linha.ip == "203.0.113.9"
