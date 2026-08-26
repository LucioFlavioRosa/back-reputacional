"""As agregações do backend batem com a tabela?

Esta é a suíte que sustenta a regra central do projeto: **o número do KPI bate
com o da tabela**. Enquanto tudo era derivado no navegador, a garantia era
trivial — o mesmo array alimentava os dois. Com a agregação em SQL, passam a
existir dois caminhos, e a garantia vira trabalho.

A forma do teste importa: em vez de conferir a agregação contra um valor
escrito à mão, ela é conferida contra a CONTAGEM DAS LINHAS QUE A LISTAGEM
DEVOLVE, sob o mesmo recorte. É a invariante de verdade, e não uma segunda
implementação do mesmo cálculo — que erraria junto.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco import consultas_metricas as consultas
from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import Status
from app.dominio.identidade import Escopo
from app.dominio.recorte import Periodo, Recorte
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def base(cliente, semente):
    """Um conjunto pequeno e conhecido, criado pela própria API.

    Criar pela API, e não por `insert` direto, é o que garante que os registros
    passam pelas mesmas invariantes que os de produção.
    """
    from tests.test_e2e_postgres import corpo

    registros = [
        dict(frente="imprensa", status="atendido", tier=1, uf="SP", data_interacao="2026-01-15"),
        dict(frente="imprensa", status="atendido", tier=2, uf="SP", data_interacao="2026-01-20"),
        dict(frente="imprensa", status="declinado", tier=1, uf="RJ", data_interacao="2026-02-10"),
        dict(frente="governo", status="atendido", tier=1, uf="DF", data_interacao="2026-02-11"),
        dict(frente="parceiros", status="em_analise", tier=3, uf="MG", data_interacao="2026-03-01"),
        dict(frente="investidores", status="atendido", tier=1, uf="IN",
             data_interacao="2026-03-05"),
        dict(frente="eventos", status="atendido", tier=2, uf="SP", data_interacao="2026-03-09"),
        dict(frente="legislativo", status="em_analise", tier=1, uf="DF",
             data_interacao="2026-04-02"),
    ]
    for registro in registros:
        resposta = cliente.post("/api/interacoes", json=corpo(semente, **registro))
        assert resposta.status_code == 201, resposta.text
    # Sem flush explícito: o TestClient usa a MESMA sessão do fixture, então os
    # registros já estão visíveis para as consultas seguintes.
    return registros


@pytest.fixture
def semente(sessao):
    from uuid import uuid4

    from app.banco.tabelas_stakeholders import (
        Instituicao,
        PessoaAegea,
    )

    sufixo = uuid4().hex[:6]
    valor = Instituicao(
        nome=f"Veículo {sufixo}", nome_normalizado=f"veiculo {sufixo}",
        tipo="veiculo", uf="SP",
    )
    a = PessoaAegea(nome=f"A {sufixo}", nome_normalizado=f"a {sufixo}", eh_porta_voz=True)
    b = PessoaAegea(nome=f"B {sufixo}", nome_normalizado=f"b {sufixo}", eh_porta_voz=True)
    sessao.add_all([valor, a, b])
    sessao.flush()
    return {"instituicao": valor, "radames": a, "andre": b}


def todas_as_linhas(cliente, consulta: str = "") -> list[dict]:
    """A listagem inteira do recorte, paginada como o front faz."""
    itens: list[dict] = []
    pagina = 1
    while True:
        resposta = cliente.get(f"/api/interacoes?tamanho=200&pagina={pagina}{consulta}")
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()
        itens.extend(corpo["itens"])
        if pagina >= corpo["paginas"] or not corpo["itens"]:
            return itens
        pagina += 1


# -- a invariante --------------------------------------------------------------


@pytest.mark.parametrize(
    "consulta",
    [
        "",
        "&frente=imprensa",
        "&uf=SP",
        "&tier=1",
        "&de=2026-02-01&ate=2026-03-31",
        "&frente=imprensa&tier=1",
        "&frente=investidores",
        # Recorte que não devolve nada: o caso em que uma divisão por zero
        # apareceria como 500 em vez de 0%.
        "&uf=AC",
    ],
)
def test_o_kpi_bate_com_a_tabela(cliente, base, consulta):
    """A regra central do projeto, verificada recorte a recorte.

    Não confere a agregação contra um número escrito à mão — confere contra a
    CONTAGEM DAS LINHAS que a listagem devolve. Uma segunda implementação do
    mesmo cálculo erraria junto; a listagem é o que o usuário vê.
    """
    kpis = cliente.get(f"/api/metricas/kpis?{consulta.lstrip('&')}").json()
    linhas = todas_as_linhas(cliente, consulta)

    por_frente = Counter(linha["frente"] for linha in linhas)

    assert kpis["total"] == len(linhas)
    assert kpis["institucionais"] == por_frente["governo"] + por_frente["parceiros"]
    assert kpis["imprensa"]["total"] == por_frente["imprensa"]
    assert kpis["eventos"] == por_frente["eventos"]
    assert kpis["legislativo"] == por_frente["legislativo"]
    assert kpis["investidores"]["total"] == por_frente["investidores"]
    assert kpis["tier1"]["total"] == sum(1 for i in linhas if i["tier"] == 1)


def test_a_serie_mensal_bate_com_a_tabela(cliente, base):
    serie = cliente.get("/api/metricas/serie-mensal").json()
    linhas = todas_as_linhas(cliente)

    esperado = Counter(linha["data_interacao"][:7] for linha in linhas)
    obtido = {coluna["mes"]: coluna["total"] for coluna in serie}
    assert obtido == dict(esperado)

    # O total de cada coluna é a soma dos segmentos dela: se divergir, a barra
    # empilhada não fecha com o rótulo em cima dela.
    for coluna in serie:
        assert coluna["total"] == sum(coluna["segmentos"].values())


def test_o_mapa_bate_com_a_tabela(cliente, base):
    """A rota do mapa INCLUI `NA` e `IN`.

    Eles não têm capital para virar bolha no mapa, e é o COMPONENTE do mapa que
    decide não desenhá-los. Filtrar no servidor quebraria o ranking que aparece
    ao lado, na mesma tela e sobre o mesmo recorte: os totais deixariam de
    fechar com a tabela.
    """
    mapa = cliente.get("/api/metricas/mapa").json()
    linhas = todas_as_linhas(cliente)

    esperado = Counter(linha["uf"] for linha in linhas)
    assert {ponto["uf"]: ponto["total"] for ponto in mapa} == dict(esperado)
    assert any(ponto["uf"] == "IN" for ponto in mapa), "internacional sumiu"


def test_a_resolutividade_bate_com_a_tabela(cliente, base, sessao):
    resolutividade = cliente.get("/api/metricas/resolutividade").json()
    linhas = todas_as_linhas(cliente)

    grupo_de = {s.codigo: s.grupo for s in sessao.scalars(select(Status))}
    por_grupo = Counter(grupo_de[linha["status"]] for linha in linhas)

    obtido = {g["grupo"]: g["total"] for g in resolutividade["grupos"]}
    # Os três sempre presentes; os ausentes da tabela valem zero.
    assert obtido == {
        grupo: por_grupo.get(grupo, 0)
        for grupo in ("resolvido", "aberto", "declinado")
    }

    # A taxa desconta os declinados do denominador — o mesmo critério da taxa
    # por frente. As duas aparecem lado a lado na tela, e já divergiram uma vez.
    resolvidos = por_grupo["resolvido"]
    denominador = len(linhas) - por_grupo["declinado"]
    assert resolutividade["taxa"] == pytest.approx(
        resolvidos / denominador if denominador else 0
    )


def test_o_denominador_por_frente_usa_o_mesmo_criterio(cliente, base, sessao):
    """O defeito que já aconteceu: KPI e detalhe com denominadores diferentes."""
    resolutividade = cliente.get("/api/metricas/resolutividade").json()
    linhas = todas_as_linhas(cliente)
    grupo_de = {s.codigo: s.grupo for s in sessao.scalars(select(Status))}

    for frente in resolutividade["por_frente"]:
        da_frente = [i for i in linhas if i["frente"] == frente["frente"]]
        declinados = sum(1 for i in da_frente if grupo_de[i["status"]] == "declinado")
        assert frente["total"] == len(da_frente)
        assert frente["denominador"] == len(da_frente) - declinados


# -- o recorte vazio -----------------------------------------------------------


def test_recorte_vazio_devolve_zero_e_nao_erro(cliente, base):
    """Divisão por zero é situação normal aqui.

    Basta filtrar por uma frente sem registros no período — e a tela mostra
    percentual, então um 500 apareceria como "o painel quebrou".
    """
    kpis = cliente.get("/api/metricas/kpis?uf=AC").json()
    assert kpis["total"] == 0
    assert kpis["imprensa"]["taxa"] == 0
    assert kpis["tier1"]["percentual"] == 0

    resolutividade = cliente.get("/api/metricas/resolutividade?uf=AC").json()
    assert resolutividade["taxa"] == 0
    # Os três grupos, zerados — e não lista vazia. Card que desaparece é lido
    # como "o sistema não calculou", não como "foi zero".
    assert [g["grupo"] for g in resolutividade["grupos"]] == [
        "resolvido",
        "aberto",
        "declinado",
    ]
    assert all(g["total"] == 0 for g in resolutividade["grupos"])


# -- o escopo vale nas agregações também ---------------------------------------


def test_a_agregacao_respeita_o_escopo(cliente, base, sessao):
    """O buraco mais fácil de abrir numa agregação nova.

    Um `where` escrito à mão aqui contaria a base inteira, e o KPI passaria a
    revelar o volume de frentes que a pessoa não pode ver — sem devolver um
    registro sequer, e sem ninguém notar.
    """
    so_imprensa = consultas.kpis(
        sessao,
        Recorte(),
        escopo=Escopo(frentes=frozenset({"imprensa"})),
        busca_em_campos_sensiveis=True,
    )
    tudo = consultas.kpis(
        sessao, Recorte(), escopo=Escopo.total(), busca_em_campos_sensiveis=True
    )

    assert so_imprensa.total < tudo.total
    assert so_imprensa.institucionais == 0
    assert so_imprensa.eventos == 0
    assert so_imprensa.imprensa.total == so_imprensa.total


def test_escopo_sem_concessao_agrega_zero(cliente, base, sessao):
    """Falha fechada também nos números."""
    nenhum = consultas.kpis(
        sessao,
        Recorte(),
        escopo=Escopo(irrestrito=False),
        busca_em_campos_sensiveis=True,
    )
    assert nenhum.total == 0


def test_periodo_do_recorte_vale_na_agregacao(cliente, base, sessao):
    dentro = consultas.kpis(
        sessao,
        Recorte(periodo=Periodo(de=date(2026, 3, 1), ate=date(2026, 3, 31))),
        escopo=Escopo.total(),
        busca_em_campos_sensiveis=True,
    )
    assert dentro.total == 3


# -- o que faltava cobrir ------------------------------------------------------


def test_investidores_internacionais_bate_com_a_tabela(cliente, base):
    """`IN` é abrangência, não estado. Estava sem teste."""
    kpis = cliente.get("/api/metricas/kpis").json()
    linhas = todas_as_linhas(cliente)

    esperado = sum(
        1 for i in linhas if i["frente"] == "investidores" and i["uf"] == "IN"
    )
    assert kpis["investidores"]["internacionais"] == esperado


def test_os_segmentos_da_serie_batem_com_a_tabela(cliente, base):
    """O total mensal estava coberto; a composição da pilha, não.

    Uma pilha cujo total fecha e cujos segmentos não é pior do que uma que não
    fecha: parece certa.
    """
    serie = cliente.get("/api/metricas/serie-mensal").json()
    linhas = todas_as_linhas(cliente)

    esperado: dict[str, Counter] = {}
    for linha in linhas:
        esperado.setdefault(linha["data_interacao"][:7], Counter())[linha["frente"]] += 1

    for coluna in serie:
        assert coluna["segmentos"] == dict(esperado[coluna["mes"]])


def test_serie_por_clima_segmenta_por_clima(cliente, base):
    """A série só sabia segmentar por frente.

    O painel empilha por frente, clima E tema na mesma tela. A série de clima
    teria vindo com "imprensa: 2" onde a tela espera "tenso: 1, neutro: 1".
    """
    serie = cliente.get("/api/metricas/serie-mensal?segmento=clima").json()
    linhas = todas_as_linhas(cliente)

    esperado: dict[str, Counter] = {}
    for linha in linhas:
        if linha["clima"]:
            esperado.setdefault(linha["data_interacao"][:7], Counter())[linha["clima"]] += 1

    obtido = {c["mes"]: c["segmentos"] for c in serie}
    assert obtido == {mes: dict(contagem) for mes, contagem in esperado.items()}


def test_interacao_sem_clima_nao_entra_na_serie_de_clima(cliente, semente):
    """O front faz `i.clima ? [i.clima] : []` — sem clima, sem segmento.

    Um `join` externo aqui criaria um segmento chamado `null` na pilha.
    """
    from tests.test_e2e_postgres import corpo

    cliente.post(
        "/api/interacoes",
        json={
            **corpo(semente, frente="governo", status="atendido", data_interacao="2026-06-01"),
            "clima": None,
        },
    )

    serie = cliente.get("/api/metricas/serie-mensal?segmento=clima").json()
    assert not any(c["mes"] == "2026-06" for c in serie)


def test_serie_por_tema_conta_cada_tema(cliente, semente, sessao):
    """Uma interação com três temas conta TRÊS vezes na pilha.

    Vem do front: a coluna é uma pilha, e a altura dela é a soma dos segmentos.
    Ler "total" aqui como "quantos registros houve no mês" daria número errado.
    """
    from app.banco.tabelas_catalogo import Tema
    from tests.test_e2e_postgres import corpo

    temas = sessao.scalars(select(Tema).limit(3)).all()
    assert len(temas) == 3

    cliente.post(
        "/api/interacoes",
        json=corpo(
            semente, frente="governo", status="atendido",
            data_interacao="2026-07-01", temas=[t.id for t in temas],
        ),
    )

    serie = cliente.get("/api/metricas/serie-mensal?segmento=tema").json()
    julho = next(c for c in serie if c["mes"] == "2026-07")

    assert julho["total"] == 3, "um registro, três temas, três ocorrências"
    assert len(julho["segmentos"]) == 3


def test_segmento_invalido_e_recusado(cliente, base):
    """Vocabulário fechado: `segmento=frentte` devolveria série vazia em silêncio."""
    resposta = cliente.get("/api/metricas/serie-mensal?segmento=frentte")
    assert resposta.status_code == 422
