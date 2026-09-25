"""O portal barra no BACKEND, e não só esconde o cartão da capa.

Esconder o cartão na capa não separa nada: `sintese@aegea.com.br` não abre o
CRM, e sem esta barreira um `curl` em `/api/interacoes` devolve a Base inteira.

A ESCRITA já é barrada, porque aquele papel é somente-leitura — e é justamente
por isso que conferir só os POSTs faz concluir que a separação está protegida.

Três perguntas diferentes, que coexistem e não se substituem:

    portal   em qual MÓDULO se entra        `papel.acessa_*`
    papel    o que se FAZ lá dentro         `papel.pode_*`
    escopo   QUAIS registros se alcança     `usuario_escopo`
"""

from __future__ import annotations

import uuid
from datetime import date

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
    entra(cliente, sessao, "crm_edicao")
    assert cliente.get(rota).status_code == 200


@pytest.mark.parametrize("rota", ROTAS_DO_CRM)
def test_a_plataforma_alcanca_as_rotas_do_crm(cliente, sessao, rota):
    entra(cliente, sessao, "plataforma_edicao")
    assert cliente.get(rota).status_code == 200


# -- quem NÃO abre o CRM é barrado --------------------------------------------


@pytest.mark.parametrize("papel", ["sintese_leitura", "score_leitura"])
@pytest.mark.parametrize("rota", ROTAS_DO_CRM)
def test_quem_nao_abre_o_crm_nao_le_o_crm(cliente, sessao, papel, rota):
    """O furo, em uma linha.

    Antes desta dependência, todas estas combinações devolviam 200 — com os 60
    registros no corpo.
    """
    entra(cliente, sessao, papel)
    resposta = cliente.get(rota)
    assert resposta.status_code == 403, f"{papel} alcançou {rota}"


def test_a_trilha_de_exportacoes_e_barrada_por_DOIS_motivos(cliente, sessao):
    """A prova de que as camadas são independentes.

    `/api/exportacoes/historico` está sob o prefixo do CRM E exige permissão
    própria dentro dele. Então:

        sintese  403 porque não abre o MÓDULO
        crm      403 porque, dentro do módulo, não tem a PERMISSÃO

    Duas recusas com o mesmo código e motivos diferentes. Se um dia alguém
    remover a permissão interna achando que o portal já basta, `sintese`
    continuaria barrado — mas `crm` passaria a ler o que todo mundo exportou.
    """
    entra(cliente, sessao, "sintese_leitura")
    por_portal = cliente.get("/api/exportacoes/historico")
    assert por_portal.status_code == 403
    assert "CRM dos Stakeholders" in por_portal.json()["detalhe"]

    entra(cliente, sessao, "crm_edicao")
    por_permissao = cliente.get("/api/exportacoes/historico")
    assert por_permissao.status_code == 403
    assert "CRM dos Stakeholders" not in por_permissao.json()["detalhe"]

    entra(cliente, sessao, "plataforma_edicao")
    assert cliente.get("/api/exportacoes/historico").status_code == 200


def test_a_recusa_diz_qual_modulo(cliente, sessao):
    """Quem chega aqui já provou identidade e conhece o próprio perfil.

    Nomear o módulo não conta nada que a pessoa não saiba sobre si mesma, e é
    acionável — diferente de "não autorizado", que manda adivinhar.
    """
    entra(cliente, sessao, "sintese_leitura")
    resposta = cliente.get("/api/interacoes")
    assert "CRM dos Stakeholders" in resposta.json()["detalhe"]


@pytest.mark.parametrize("papel", ["sintese_leitura", "score_leitura"])
def test_quem_nao_abre_o_crm_tambem_nao_escreve(cliente, sessao, papel):
    """Barrado por `exigir_escrita` E pelo portal.

    O teste existe para a proteção não depender de UMA camada: se alguém der
    permissão de escrita ao papel `sintese` amanhã, o portal ainda barra.
    """
    entra(cliente, sessao, papel)
    assert cliente.post("/api/interacoes", json={}).status_code == 403


# -- o que não é do CRM continua aberto ---------------------------------------


@pytest.mark.parametrize(
    "papel",
    [
        "plataforma_leitura",
        "plataforma_edicao",
        "crm_leitura",
        "crm_edicao",
        "sintese_leitura",
        "sintese_edicao",
        "score_leitura",
        "score_edicao",
    ],
)
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
    "/api/materiais",
    "/api/referencias",
    "/api/exportacoes",
    "/api/instituicoes",
    "/api/interlocutores",
    "/api/pessoas-aegea",
)


def _rotas_montadas(aplicacao) -> list:
    """Toda `APIRoute` da aplicacao, em qualquer profundidade.

    NAO BASTA OLHAR `app.routes`. Ate o FastAPI 0.140, `include_router` COPIAVA
    cada rota para a lista da aplicacao; da 0.141 em diante ele insere um
    objeto que guarda o router dentro de si, em `original_router`, e a lista de
    primeiro nivel passa a ter oito entradas opacas no lugar de 45 rotas.

    Uma varredura que so olha o primeiro nivel encontra ZERO rotas de negocio —
    e uma ancora que nao encontra nada passa sem provar nada. Foi exatamente
    isso que uma atualizacao de dependencia produziu aqui.

    Descer por `original_router` funciona nas duas geracoes: onde a rota ja
    esta no primeiro nivel, ela e colhida direto.
    """
    from fastapi.routing import APIRoute

    encontradas: list = []
    pilha = list(aplicacao.routes)
    while pilha:
        item = pilha.pop()
        if isinstance(item, APIRoute):
            encontradas.append(item)
            continue
        interno = getattr(item, "original_router", None) or item
        pilha.extend(getattr(interno, "routes", ()))
    return encontradas


def test_toda_rota_sob_prefixo_do_crm_exige_o_portal():
    """Âncora estrutural, varrendo a APLICAÇÃO MONTADA.

    Olhar `app.routes` cobre o que EXISTE, e não o que alguém lembrou de
    listar. Percorrer os objetos `rotas` dos módulos conhecidos não provaria
    nada sobre uma rota registrada em outro lugar — direto no `main.py`, ou num
    router novo que ninguém acrescentou à lista.
    """
    from fastapi.routing import APIRoute

    from app.api.dependencias import exigir_portal_crm

    desprotegidas = []
    for rota in _rotas_montadas(app):
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
        for r in _rotas_montadas(app)
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


# -- editar o proprio nao e editar o de todos ---------------------------------


def test_o_editor_do_crm_nao_mexe_em_registro_alheio(cliente, sessao):
    """A distinção que separa "trabalha aqui" de "manda aqui".

    Este teste existe porque o defeito passou: `crm_edicao` nasceu com
    `pode_editar_tudo`, e por um momento o editor do CRM podia alterar e
    arquivar registro criado por qualquer pessoa.

    A suíte não pegou, e o motivo vale registrar: um teste montava `crm_edicao`
    SEM aquela bandeira, e outro exigia que todo editor a tivesse. Os dois
    passavam, discordando sobre o que o papel é — e nenhum falava com o banco,
    que é onde a permissão de verdade estava gravada.
    """

    # Alguém do CRM cria um registro.
    autor = entra(cliente, sessao, "crm_edicao")
    registro = _registro_de(sessao, autor)

    # OUTRA pessoa, com o mesmo papel de edição do CRM.
    entra(cliente, sessao, "crm_edicao")

    recusado = cliente.patch(
        f"/api/interacoes/{registro.id}",
        headers={"X-CSRF-Token": _csrf(cliente)},
        json={"pauta": "mexi no que não é meu"},
    )
    assert recusado.status_code == 403, recusado.text

    arquivar = cliente.delete(
        f"/api/interacoes/{registro.id}", headers={"X-CSRF-Token": _csrf(cliente)}
    )
    assert arquivar.status_code == 403


def test_a_plataforma_mexe_em_registro_alheio(cliente, sessao):
    """O contrapeso: alguém precisa poder corrigir o registro de quem saiu.

    Sem este teste, restringir demais passaria despercebido — e a coordenação
    ficaria sem como consertar um erro de digitação de quem já não está na
    empresa.
    """

    autor = entra(cliente, sessao, "crm_edicao")
    registro = _registro_de(sessao, autor)

    entra(cliente, sessao, "plataforma_edicao")
    aceito = cliente.patch(
        f"/api/interacoes/{registro.id}",
        headers={"X-CSRF-Token": _csrf(cliente)},
        json={"pauta": "corrigido pela coordenação"},
    )
    assert aceito.status_code == 200, aceito.text


def _registro_de(sessao, autor):
    """Uma interação de `autor`, com o mínimo que o schema exige.

    A instituição é CRIADA aqui, e não buscada: o banco de teste tem as
    migrations mas não a amostra sintética, então `select ... limit 1` voltava
    vazio e o `insert` falhava por `not null` — um erro que aponta para a
    coluna, e não para a causa.
    """
    from app.banco.tabelas_interacoes import InteracaoRegistro
    from app.banco.tabelas_stakeholders import Instituicao

    instituicao = Instituicao(
        nome=f"Instituição {uuid.uuid4().hex[:6]}",
        nome_normalizado=uuid.uuid4().hex[:12],
        tipo="veiculo",
    )
    sessao.add(instituicao)
    sessao.flush()

    registro = InteracaoRegistro(
        frente_id=sessao.scalar(text("select id from frente where codigo='imprensa'")),
        data_interacao=date.today(),
        uf="SP",
        status_id=sessao.scalar(text("select id from status limit 1")),
        instituicao_id=instituicao.id,
        pauta="registro de outra pessoa",
        criado_por=autor.id,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _csrf(cliente) -> str:
    return cliente.get("/api/eu").json()["csrf_token"]


#: Os prefixos cujo conteúdo é do Score Executivo.
#:
#: Dois módulos servem sob o mesmo prefixo — `api/score.py` (índice, série,
#: calibração, fontes, importação, fatos) e `api/lentes.py` (os dossiês) —, e é
#: por isso que a âncora olha o CAMINHO e não o módulo: um terceiro módulo sob
#: `/api/score` nasceria fora de qualquer lista que se mantenha à mão.
PREFIXOS_DO_SCORE = ("/api/score",)


def test_toda_rota_sob_prefixo_do_score_exige_o_portal():
    """A mesma âncora do CRM, para o módulo mais novo — que é onde ela faltava.

    O CRM tinha esta prova desde o começo; o Score chegou depois e não ganhou a
    dele. A consequência não é hipotética: uma revisão encontrou, nesta mesma
    área, o dossiê servindo o diretório a quem não o alcança — o tipo de falha
    que uma dependência esquecida produz e que nenhum teste de contrato pega,
    porque o payload continua perfeito.
    """
    from fastapi.routing import APIRoute

    from app.api.dependencias import exigir_portal_score

    desprotegidas = []
    for rota in _rotas_montadas(app):
        if not isinstance(rota, APIRoute):
            continue
        if not rota.path.startswith(PREFIXOS_DO_SCORE):
            continue
        chamadas = {d.call for d in rota.dependant.dependencies}
        if exigir_portal_score not in chamadas:
            desprotegidas.append(f"{sorted(rota.methods)} {rota.path}")

    assert not desprotegidas, (
        "Rotas sob prefixo do Score que não exigem o portal: " + ", ".join(desprotegidas)
    )


def test_a_varredura_enxerga_as_rotas_do_score():
    """Contrapeso, pelo mesmo motivo do contrapeso do CRM.

    Um prefixo escrito errado faria a varredura achar zero rotas e declarar
    tudo protegido. O piso é deliberadamente folgado: ele existe para detectar
    "achei nada", não para congelar a contagem a cada rota nova.
    """
    from fastapi.routing import APIRoute

    do_score = [
        rota
        for rota in _rotas_montadas(app)
        if isinstance(rota, APIRoute) and rota.path.startswith(PREFIXOS_DO_SCORE)
    ]

    assert len(do_score) >= 10, f"a varredura achou só {len(do_score)} rotas do Score"
