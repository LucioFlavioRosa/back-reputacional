"""O portal barra no BACKEND, e não só esconde o cartão da capa.

O furo que motivou este arquivo era exatamente o inverso do que a tela sugeria:
`sintese@aegea.com.br` não abre o CRM, a capa escondia o cartão — e um `curl`
em `/api/interacoes` devolvia os 60 registros.

Pior: a ESCRITA já era barrada, porque aquele papel é somente-leitura. Quem
conferisse só os POSTs concluiria que a separação estava protegida.

Três perguntas diferentes, que coexistem e não se substituem:

    portal   em qual MÓDULO se entra        `papel.acessa_*`
    papel    o que se FAZ lá dentro         `papel.pode_*`
    escopo   QUAIS registros se alcança     `usuario_escopo`
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.configuracao import Configuracao, obter_configuracao
from app.seguranca import sessao_assinada
from main import app
from tests.test_e2e_postgres import URL

SEGREDO = "segredo-de-teste-com-mais-de-trinta-e-dois-caracteres"
_engine = create_engine(URL, pool_pre_ping=True)

#: As rotas do CRM. A lista é explícita para uma rota nova não escapar em
#: silêncio: quem acrescentar um router de CRM sem a dependência vê este teste
#: reprovar se lembrar de incluí-la aqui — e o `test_todo_router_do_crm_exige`
#: abaixo cobre o caso de esquecer.
ROTAS_DO_CRM = [
    "/api/interacoes",
    "/api/metricas/kpis",
    "/api/metricas/mapa",
    "/api/metricas/resolutividade",
    "/api/metricas/serie-mensal",
    "/api/instituicoes",
    "/api/interlocutores",
    "/api/pessoas-aegea",
]

#: O que TODO mundo alcança, independentemente de portal.
#:
#: Sem vocabulário nenhuma tela renderiza rótulo, e sem `/api/eu` a aplicação
#: não sabe quem entrou — barrar estas por portal deixaria a Síntese sem como
#: desenhar a própria tela no dia em que ela existir.
ROTAS_DE_TODOS = ["/api/dicionarios", "/api/eu"]


def configuracao_real() -> Configuracao:
    return Configuracao(
        auth_mock=False,
        sessao_secreta=SEGREDO,
        sso_ligado=True,
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
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = configuracao_real
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def entra(cliente, sessao, codigo_do_papel: str):
    """Cria alguém com o papel pedido e põe o cookie de sessão no cliente."""
    papel = sessao.scalars(select(Papel).where(Papel.codigo == codigo_do_papel)).one()
    usuario = Usuario(
        entra_object_id=f"oid-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@aegea.com.br",
        nome=f"Teste {codigo_do_papel}",
        papel_id=papel.id,
        # Escopo total de propósito: o que se testa aqui é o PORTAL. Com escopo
        # restrito, uma listagem vazia teria duas causas possíveis.
        acesso_irrestrito=True,
    )
    sessao.add(usuario)
    sessao.flush()
    cliente.cookies.set(
        sessao_assinada.NOME_DO_COOKIE,
        sessao_assinada.assinar(sessao_assinada.nova_sessao(usuario.id), SEGREDO),
    )
    return usuario


# -- quem abre o CRM entra -----------------------------------------------------


@pytest.mark.parametrize("rota", ROTAS_DO_CRM)
def test_o_papel_crm_alcanca_as_rotas_do_crm(cliente, sessao, rota):
    entra(cliente, sessao, "crm")
    assert cliente.get(rota).status_code == 200


@pytest.mark.parametrize("rota", ROTAS_DO_CRM)
def test_a_plataforma_alcanca_as_rotas_do_crm(cliente, sessao, rota):
    entra(cliente, sessao, "plataforma")
    assert cliente.get(rota).status_code == 200


# -- quem NÃO abre o CRM é barrado --------------------------------------------


@pytest.mark.parametrize("papel", ["sintese", "score"])
@pytest.mark.parametrize("rota", ROTAS_DO_CRM)
def test_quem_nao_abre_o_crm_nao_le_o_crm(cliente, sessao, papel, rota):
    """O furo, em uma linha.

    Antes desta dependência, todas estas combinações devolviam 200 — com os 60
    registros no corpo.
    """
    entra(cliente, sessao, papel)
    resposta = cliente.get(rota)
    assert resposta.status_code == 403, f"{papel} alcançou {rota}"


def test_o_historico_de_relatorios_e_barrado_por_DOIS_motivos(cliente, sessao):
    """A prova de que as camadas são independentes.

    `/api/relatorios/historico` está sob o prefixo do CRM E exige permissão
    própria dentro dele. Então:

        sintese  403 porque não abre o MÓDULO
        crm      403 porque, dentro do módulo, não tem a PERMISSÃO

    Duas recusas com o mesmo código e motivos diferentes. Se um dia alguém
    remover a permissão interna achando que o portal já basta, `sintese`
    continuaria barrado — mas `crm` passaria a ler o histórico de todo mundo.
    """
    entra(cliente, sessao, "sintese")
    por_portal = cliente.get("/api/relatorios/historico")
    assert por_portal.status_code == 403
    assert "CRM dos Stakeholders" in por_portal.json()["detalhe"]

    entra(cliente, sessao, "crm")
    por_permissao = cliente.get("/api/relatorios/historico")
    assert por_permissao.status_code == 403
    assert "CRM dos Stakeholders" not in por_permissao.json()["detalhe"]

    entra(cliente, sessao, "plataforma")
    assert cliente.get("/api/relatorios/historico").status_code == 200


def test_a_recusa_diz_qual_modulo(cliente, sessao):
    """Quem chega aqui já provou identidade e conhece o próprio perfil.

    Nomear o módulo não conta nada que a pessoa não saiba sobre si mesma, e é
    acionável — diferente de "não autorizado", que manda adivinhar.
    """
    entra(cliente, sessao, "sintese")
    resposta = cliente.get("/api/interacoes")
    assert "CRM dos Stakeholders" in resposta.json()["detalhe"]


@pytest.mark.parametrize("papel", ["sintese", "score"])
def test_quem_nao_abre_o_crm_tambem_nao_escreve(cliente, sessao, papel):
    """Já era barrado por `exigir_escrita`, e continua.

    O teste existe para a proteção não depender de UMA camada: se alguém der
    permissão de escrita ao papel `sintese` amanhã, o portal ainda barra.
    """
    entra(cliente, sessao, papel)
    assert cliente.post("/api/interacoes", json={}).status_code == 403


# -- o que não é do CRM continua aberto ---------------------------------------


@pytest.mark.parametrize("papel", ["plataforma", "crm", "sintese", "score"])
@pytest.mark.parametrize("rota", ROTAS_DE_TODOS)
def test_o_vocabulario_e_a_identidade_valem_para_todos(cliente, sessao, papel, rota):
    """Barrar estas por portal quebraria a Síntese antes de ela existir.

    Sem `/api/dicionarios` nenhuma tela renderiza rótulo; sem `/api/eu` a
    aplicação não sabe quem entrou nem o que oferecer na capa.
    """
    entra(cliente, sessao, papel)
    assert cliente.get(rota).status_code == 200


# -- a rede contra rota nova desprotegida --------------------------------------


#: Os prefixos cujo conteúdo é do CRM dos Stakeholders.
#:
#: Toda rota registrada sob eles precisa exigir o portal — venha do router que
#: vier, e mesmo que alguém a declare direto no `main.py`.
PREFIXOS_DO_CRM = (
    "/api/interacoes",
    "/api/metricas",
    "/api/relatorios",
    "/api/instituicoes",
    "/api/interlocutores",
    "/api/pessoas-aegea",
)


def test_toda_rota_sob_prefixo_do_crm_exige_o_portal():
    """Âncora estrutural, varrendo a APLICAÇÃO MONTADA.

    A primeira versão deste teste olhava os quatro objetos `rotas` dos módulos
    conhecidos, e por isso não provaria nada sobre uma rota registrada em outro
    lugar — direto no `main.py`, ou num router novo que ninguém lembrou de
    incluir na lista. Era uma âncora que só cobria o que já se sabia.

    Olhar `app.routes` cobre o que EXISTE, e não o que se lembrou de listar.
    """
    from fastapi.routing import APIRoute

    from app.api.dependencias import exigir_portal_crm

    desprotegidas = []
    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue
        if not rota.path.startswith(PREFIXOS_DO_CRM):
            continue
        # `dependant.dependencies` traz a árvore resolvida — as do router e as
        # da própria rota, que é onde uma exceção se esconderia.
        chamadas = {d.call for d in rota.dependant.dependencies}
        if exigir_portal_crm not in chamadas:
            desprotegidas.append(f"{sorted(rota.methods)} {rota.path}")

    assert not desprotegidas, (
        "Rotas sob prefixo do CRM que não exigem o portal: " + ", ".join(desprotegidas)
    )


def test_a_varredura_enxerga_as_rotas_de_verdade():
    """Contrapeso do teste acima.

    Sem ele, um erro no filtro de prefixo faria a varredura encontrar ZERO
    rotas e concluir que está tudo protegido — o modo de falha mais silencioso
    que uma âncora estrutural tem.
    """
    from fastapi.routing import APIRoute

    sob_crm = [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith(PREFIXOS_DO_CRM)
    ]
    assert len(sob_crm) >= 12, f"só {len(sob_crm)} rotas sob prefixo do CRM"


def test_o_papel_sem_portal_nenhum_nao_alcanca_o_crm(cliente, sessao):
    """Fecha por padrão.

    Um papel criado por `insert` sem decidir os portais não abre nada — e o
    CRM, que é o único módulo com dado hoje, é o que mais importa que fique
    fechado.
    """
    sessao.execute(
        text("""
            insert into papel (codigo, nome, ve_campos_sensiveis)
            values ('sem_portal', 'Sem portal', true)
        """)
    )
    sessao.flush()
    entra(cliente, sessao, "sem_portal")
    assert cliente.get("/api/interacoes").status_code == 403
