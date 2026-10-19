"""O guarda do Painel de Inteligência de Mercado: o ALCANCE e a PORTA.

POR QUE SÃO DUAS CONDIÇÕES. O campo `configuracao.mercado_lancado` existe com
uma razão escrita nele próprio: "fechar o painel por uma tarde exigiria revogar
o acesso de dezenas de pessoas — e, na tela de acessos, isso é indistinguível de
alguém ter perdido o acesso. Com a bandeira, o alcance fica intacto e a porta
fecha". E a frase seguinte é a que este arquivo prende: "precisa existir no
BACKEND, e não só na navegação da tela: esconder o cartão não fecha a rota".

ATÉ ESTE BLOCO NÃO HAVIA GUARDA, e a ausência estava documentada em
`dependencias.py`: "o painel está EM CONSTRUÇÃO, não existe rota dele para
proteger". A primeira rota chegou, então a ausência deixou de ser deliberada — e
o estado em que as rotas NASCEM é recusando para todo mundo, porque
`mercado_lancado` é `False` por padrão. É o que permite mesclar o back antes de
a tela existir sem abrir nada.

AS DUAS RECUSAS TÊM MENSAGENS DIFERENTES de propósito, e isso também é afirmado
aqui: "ainda não foi lançado" é estado do produto e não tem o que pedir à
coordenação; "seu perfil não tem acesso" é concessão. A mesma frase para as duas
mandaria alguém pedir permissão para uma porta fechada para todos.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.configuracao import Configuracao, obter_configuracao
from app.seguranca import sessao_assinada
from app.seguranca.cache_de_autorizacao import limpar_todos
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

SEGREDO = "segredo-de-teste-do-portal-de-mercado"

ROTAS = (
    "/api/mercado/bonds/conferencia",
    "/api/mercado/bonds/importar",
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


@pytest.fixture(autouse=True)
def _cache_limpo():
    #: O cache de autorização vive no processo e sobrevive entre testes — sem
    #: isto a ordem da suíte passaria a importar.
    limpar_todos()
    yield
    limpar_todos()


def _configuracao(*, lancado: bool) -> Configuracao:
    return Configuracao(
        auth_mock=False,
        sessao_secreta=SEGREDO,
        sso_ligado=True,
        entra_tenant_id="t",
        entra_client_id="c",
        entra_client_secret="s",
        url_do_front="https://painel.aegea.com.br",
        autorizacao_cache_segundos=0,
        mercado_lancado=lancado,
    )


def _usuario(sessao: Session, *, alcanca_mercado: bool) -> Usuario:
    """Alguém com um papel que alcança — ou não — o portal de mercado.

    MEXE NO PAPEL EM VEZ DE ESCOLHER UM, e a transação desfaz: amarrar o teste a
    qual papel de fábrica tem a bandeira faria ele falhar quando a coordenação
    reorganizasse perfis, por um motivo que não é o do teste.
    """
    papel = sessao.scalars(
        select(Papel).where(Papel.codigo == "plataforma_edicao")
    ).one()
    papel.acessa_inteligencia_de_mercado = alcanca_mercado
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


def _cliente(
    sessao: Session, usuario: Usuario, *, lancado: bool
) -> tuple[TestClient, dict[str, str]]:
    """O cliente E o cabeçalho anti-CSRF.

    DEVOLVE OS DOIS, e isto foi um teste meu passando por motivo errado: sem o
    `X-CSRF-Token` todo POST é recusado com 403 — o MESMO código do guarda do
    portal. As duas primeiras asserções passavam sem a rota nunca ter sido
    alcançada, e só a mensagem no corpo mostrou a diferença.
    """
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: _configuracao(
        lancado=lancado
    )
    cliente = TestClient(app)
    cookie = sessao_assinada.assinar(sessao_assinada.nova_sessao(usuario.id), SEGREDO)
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie)
    return cliente, {"X-CSRF-Token": sessao_assinada.ler(cookie, SEGREDO).csrf}


@pytest.fixture(autouse=True)
def _sem_sobrescritas():
    yield
    app.dependency_overrides.clear()


@pytest.mark.parametrize("rota", ROTAS)
def test_com_a_bandeira_DESLIGADA_recusa_ate_quem_tem_o_papel(sessao, rota):
    """O estado em que as rotas nascem.

    `mercado_lancado` é `False` por padrão, então mesclar o back antes de a tela
    existir não abre nada — nem para quem já tem a concessão.
    """
    usuario = _usuario(sessao, alcanca_mercado=True)
    cliente, cabecalho = _cliente(sessao, usuario, lancado=False)

    resposta = cliente.post(
        rota, headers=cabecalho, files={"arquivo": ("x.xlsx", b"PK\x03\x04", "x")}
    )

    assert resposta.status_code == 403
    assert "ainda não foi lançado" in resposta.json()["detalhe"]


@pytest.mark.parametrize("rota", ROTAS)
def test_lancado_mas_SEM_o_papel_recusa_com_a_outra_frase(sessao, rota):
    """Recusa diferente, porque a decisão de quem lê é diferente.

    "Não foi lançado" não tem o que pedir; "seu perfil não tem acesso" tem.
    """
    usuario = _usuario(sessao, alcanca_mercado=False)
    cliente, cabecalho = _cliente(sessao, usuario, lancado=True)

    resposta = cliente.post(
        rota, headers=cabecalho, files={"arquivo": ("x.xlsx", b"PK\x03\x04", "x")}
    )

    assert resposta.status_code == 403
    corpo = resposta.json()["detalhe"]
    assert "não tem acesso ao Painel de Inteligência de Mercado" in corpo
    assert "ainda não foi lançado" not in corpo


@pytest.mark.parametrize("rota", ROTAS)
def test_com_as_DUAS_a_rota_atende(sessao, rota):
    """O controle positivo: passou o guarda e chegou à regra do arquivo.

    422 é a resposta CERTA aqui — os bytes não são um `.xlsx` válido, e é
    `RegraViolada` que `app/api/erros.py` traduz. O que este teste prova é que a
    recusa deixou de ser de autorização: o 403 virou 422.
    """
    usuario = _usuario(sessao, alcanca_mercado=True)
    cliente, cabecalho = _cliente(sessao, usuario, lancado=True)

    resposta = cliente.post(
        rota, headers=cabecalho, files={"arquivo": ("x.xlsx", b"nao e zip", "x")}
    )

    assert resposta.status_code == 422, resposta.text
    assert "não é um .xlsx" in resposta.json()["detalhe"]


def test_sem_cookie_nenhum_nao_entra(sessao):
    """A porta de fora continua valendo, antes do guarda do portal."""
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: _configuracao(lancado=True)

    resposta = TestClient(app).post(
        ROTAS[0], files={"arquivo": ("x.xlsx", b"PK\x03\x04", "x")}
    )

    assert resposta.status_code == 403


# -- a rota de LEITURA também está atrás da bandeira ---------------------------
#
# O POST é o que muda dado, mas é o GET que SERVE dado — e o painel inteiro
# existe para mostrar número. Uma rota de leitura aberta enquanto o módulo está
# "em construção" entrega a série de cotações a quem o cartão da capa ainda diz
# que não pode entrar. Esconder o cartão não fecha a rota: é a frase escrita na
# própria `configuracao.mercado_lancado`.


def test_a_serie_NAO_sai_com_a_bandeira_desligada(sessao):
    usuario = _usuario(sessao, alcanca_mercado=True)
    cliente, _ = _cliente(sessao, usuario, lancado=False)

    resposta = cliente.get("/api/mercado/bonds/serie")

    assert resposta.status_code == 403
    assert "ainda não foi lançado" in resposta.json()["detalhe"]


def test_a_serie_NAO_sai_para_quem_nao_tem_o_papel(sessao):
    usuario = _usuario(sessao, alcanca_mercado=False)
    cliente, _ = _cliente(sessao, usuario, lancado=True)

    resposta = cliente.get("/api/mercado/bonds/serie")

    assert resposta.status_code == 403
    assert "não tem acesso ao Painel" in resposta.json()["detalhe"]


def test_a_serie_sai_com_as_duas_condicoes_e_traz_o_catalogo(sessao):
    """O controle positivo, e ele afirma mais que o status.

    O CATÁLOGO VEM MESMO SEM COTAÇÃO: é a mesma lição da aba Base do Score — a
    tela que cria o dado não pode exigir dado. Sem isto o seletor de papéis
    nasceria vazio e ninguém saberia o que escolher.

    E O `indice` VEM DAQUI, não de `/api/score/serie` — aquela rota exige o
    portal do Score, e quem tem só o de mercado receberia 403 dela. A linha do
    eixo direito sairia vazia por permissão e se leria como falta de dado.
    """
    usuario = _usuario(sessao, alcanca_mercado=True)
    cliente, _ = _cliente(sessao, usuario, lancado=True)

    resposta = cliente.get("/api/mercado/bonds/serie")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert len(corpo["papeis"]) == 31
    assert corpo["metrica"] == "preco"
    #: As três séries da Aegea aparecem, mesmo vazias — é o que a legenda lista.
    assert {s["ticker"] for s in corpo["bonds"]} == {
        "AEGEBZ29",
        "AEGEBZ31",
        "AEGEBZ36",
    }
    assert "indice" in corpo


def test_a_metrica_invalida_na_url_da_422_e_nao_403(sessao):
    """Passou o guarda e chegou à regra — a recusa deixou de ser de acesso."""
    usuario = _usuario(sessao, alcanca_mercado=True)
    cliente, _ = _cliente(sessao, usuario, lancado=True)

    resposta = cliente.get("/api/mercado/bonds/serie?metrica=spread")

    assert resposta.status_code == 422, resposta.text
    assert "não existe" in resposta.json()["detalhe"]