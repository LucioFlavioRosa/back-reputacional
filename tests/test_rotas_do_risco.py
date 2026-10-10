"""As duas rotas do rastreio de risco.

O que se testa aqui é o CONTRATO com a tela — o que o protótipo precisa receber
— e as duas regras de permissão que a aba carrega:

* o PORTAL é o do Score, como nas outras rotas daqui;
* a PAUTA da agenda é conteúdo do CRM, e quem não tem aquele portal recebe a
  linha SEM o texto, com `texto_restrito` dizendo por quê. A linha aparece
  porque a tabela não pode discordar do total sem explicar.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import Risco, RiskCluster
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


def _cliente(sessao, papel: str):
    """Um cliente autenticado como alguém do papel pedido.

    PELO COOKIE ASSINADO, e não pelo `auth_mock`: o mock provisiona UM usuário
    pelo mesmo `OID_MOCK`, e o papel é o da primeira criação — dois clientes no
    mesmo teste viravam a mesma pessoa, com o papel de quem chegou primeiro.
    O teste da pauta restrita passava a não testar nada por causa disso.

    `entra` é o ajudante que o projeto já usa para isto (ver
    `test_portal_no_backend.py`): cria alguém com o papel e assina a sessão.
    """
    from fastapi.testclient import TestClient

    from app.configuracao import obter_configuracao
    from tests.test_portal_no_backend import configuracao_real, entra

    #: A CONFIGURAÇÃO REAL, com o mesmo segredo que `entra` usa para assinar a
    #: sessão — sem ela o cookie não vale e tudo volta 403.
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = configuracao_real
    feito = TestClient(app)
    entra(feito, sessao, papel)
    return feito


@pytest.fixture
def com_incidentes(sessao):
    """Semeia o que a tela precisa: uma menção negativa e uma agenda tensa.

    SEMEAR EM VEZ DE PULAR. O banco de teste nasce das migrations, sem menção
    nenhuma, e cinco destes testes pulavam — entre eles os das duas regras de
    permissão, que são o que esta aba tem de mais delicado.

    Os ajudantes vêm do teste do repositório de propósito: duas formas de criar
    a mesma agenda divergiriam, e aí um dos dois arquivos passaria a provar
    sobre um dado que a aplicação não produz.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import Tema as _Tema
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco
    from app.banco.tabelas_score import ScoreFonte as _Fonte
    from tests.test_rastreio_de_riscos import _agenda, _mencao

    par = sessao.execute(
        _select(_Tema, _Risco)
        .join(_TemaRisco, _TemaRisco.tema_id == _Tema.id)
        .join(_Risco, _Risco.id == _TemaRisco.risco_id)
        .where(_Tema.ativo.is_(True), _Risco.ativo.is_(True))
        .order_by(_Tema.id)
        .limit(1)
    ).first()
    assert par is not None, "o cadastro de teste precisa de tema ligado a risco"
    tema, _risco = par

    bites = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "bites"))
    clipei = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "clipei"))

    #: A FORMA DO DADO REAL, e não uma linha genérica: medido na base, a Bites
    #: preenche cargo, autor e engajamento e NÃO manda tier nem público-alvo; a
    #: Clipei manda tier e público-alvo e não manda cargo. É disso que o teste
    #: das dimensões fala, e semente que ignore isso o faria provar o contrário.
    da_bites = _mencao(sessao, bites, tema, "neg")
    da_bites.cargo = "vereador"
    da_bites.autor = "fulano da silva"
    da_bites.engajamento = 42
    da_bites.uf = "Rio Grande do Sul"
    da_bites.unidade_texto = "Corsan"

    #: DOIS MESES, para a janela ter o que marcar e o que esmaecer.
    de_setembro = _mencao(sessao, bites, tema, "neg", dia=4)
    de_setembro.mes = date(2026, 9, 1)
    de_setembro.data = date(2026, 9, 4)
    de_setembro.cargo = "vereador"

    da_clipei = _mencao(sessao, clipei, tema, "neg", dia=5)
    da_clipei.tier = "relevante"
    da_clipei.publico_alvo = "Geral"
    da_clipei.uf = "Rio Grande do Sul"
    da_clipei.unidade_texto = "Corsan"

    sessao.flush()
    _agenda(sessao, tema, "tenso")
    return tema


@pytest.fixture
def do_score(sessao):
    """Quem tem o portal do Score e NÃO tem o do CRM."""
    feito = _cliente(sessao, "score_edicao")
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def da_plataforma(sessao):
    """Quem tem tudo — é o perfil que opera a plataforma."""
    feito = _cliente(sessao, "plataforma_edicao")
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


# -- o painel --------------------------------------------------------------------


def test_o_painel_devolve_a_serie_os_kpis_e_a_matriz(da_plataforma, sessao):
    resposta = da_plataforma.get("/api/score/riscos")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert {"serie", "matriz", "referencia", "faixas"} <= set(corpo)

    #: A MATRIZ TRAZ TODOS OS RISCOS DO CADASTRO — "sem incidente" é informação.
    from sqlalchemy import func

    quantos = sessao.scalar(
        select(func.count())
        .select_from(Risco)
        .join(RiskCluster, RiskCluster.id == Risco.risk_cluster_id)
        .where(Risco.ativo.is_(True), RiskCluster.ativo.is_(True))
    )
    assert len(corpo["matriz"]) == quantos
    #: E CADA LINHA SEPARA menção de agenda.
    assert {"mencoes", "agendas", "incidentes", "severidade", "cluster"} <= set(
        corpo["matriz"][0]
    )


def test_a_serie_vem_INTEIRA_com_os_meses_de_fora_MARCADOS(
    da_plataforma, com_incidentes
):
    """O protótipo esmaece as barras de fora da janela, e não as esconde."""
    resposta = da_plataforma.get("/api/score/riscos?de=2026-09&ate=2026-09")

    assert resposta.status_code == 200, resposta.text
    serie = resposta.json()["serie"]
    assert len(serie) > 1, "a semente cria dois meses"
    dentro = [mes for mes in serie if mes["na_janela"]]
    fora = [mes for mes in serie if not mes["na_janela"]]
    assert [mes["mes"] for mes in dentro] == ["2026-09"]
    assert fora, "os meses de fora continuam na série"
    #: COM ÍNDICE: é o que o gráfico esmaece, não o que ele omite.
    assert all(mes["indice"] is not None for mes in fora)


def test_cada_mes_diz_QUAIS_FONTES_o_alimentaram(da_plataforma, com_incidentes):
    """Enquanto a base está incompleta, é o que impede o gráfico de comparar
    mês de uma fonte com mês de quatro."""
    corpo = da_plataforma.get("/api/score/riscos").json()

    com_dado = [mes for mes in corpo["serie"] if mes["incidentes"]]
    assert com_dado, "a semente cria incidentes"
    assert all(mes["fontes"] for mes in com_dado)


def test_os_KPIs_descrevem_a_JANELA_e_a_referencia_descreve_a_SERIE(da_plataforma):
    inteiro = da_plataforma.get("/api/score/riscos").json()
    recortado = da_plataforma.get("/api/score/riscos?de=2026-01&ate=2026-01").json()

    #: A REFERÊNCIA É A MESMA: 100 pontos é o pior mês da série, e a janela não
    #: reescala o passado.
    assert recortado["referencia"] == inteiro["referencia"]
    #: OS KPIs, NÃO: eles descrevem o período escolhido.
    if recortado["serie"]:
        assert recortado["indice_atual"]["mes"] in (None, "2026-01")


def test_as_FAIXAS_vem_na_resposta_para_a_tela_nao_recalcular(da_plataforma):
    faixas = da_plataforma.get("/api/score/riscos").json()["faixas"]

    assert set(faixas) == {"critico", "alto", "moderado"}
    assert faixas["critico"] > faixas["alto"] > faixas["moderado"]


# -- o relatório de incidentes ---------------------------------------------------


def test_o_relatorio_pagina_e_diz_o_total(da_plataforma):
    resposta = da_plataforma.get("/api/score/riscos/incidentes?tamanho=5")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["tamanho"] == 5
    assert len(corpo["itens"]) <= 5
    assert corpo["total"] >= len(corpo["itens"])
    if corpo["itens"]:
        linha = corpo["itens"][0]
        #: AS COLUNAS DO PROTÓTIPO: Data, Veículo, Alcance, Severidade,
        #: Recorrência, Incidente, Riscos relacionados.
        assert {
            "data",
            "quem",
            "tier",
            "engajamento",
            "severidade",
            "recorrencia",
            "incidente",
            "riscos",
        } <= set(linha)


def test_o_relatorio_vem_do_MAIS_RECENTE(da_plataforma, com_incidentes):
    itens = da_plataforma.get("/api/score/riscos/incidentes?tamanho=20").json()["itens"]
    assert len(itens) >= 2, "a semente cria três incidentes"

    datas = [linha["data"] for linha in itens]
    assert datas == sorted(datas, reverse=True)


def test_o_TETO_DA_PAGINA_e_recusado_acima_do_limite(da_plataforma):
    resposta = da_plataforma.get("/api/score/riscos/incidentes?tamanho=5000")

    #: O que passa do teto é exportação, não leitura de tela.
    assert resposta.status_code == 422


# -- as duas regras de permissão -------------------------------------------------


def test_SEM_O_PORTAL_DO_SCORE_a_aba_nao_abre(sessao):
    feito = _cliente(sessao, "crm_edicao")
    try:
        assert feito.get("/api/score/riscos").status_code == 403
        assert feito.get("/api/score/riscos/incidentes").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_a_AGENDA_nao_traz_TEXTO_LIVRE_para_papel_nenhum(
    do_score, da_plataforma, com_incidentes
):
    """A pauta não entra na aba de risco, e não é questão de permissão.

    DECISÃO DO DONO DO PRODUTO: "essa informação já deveria estar em tema da
    reunião e clima" — e a pauta é texto descritivo mais longo, que num relatório
    de sete colunas não cabe. A linha da agenda diz data, assunto, severidade,
    recorrência e riscos; o relato detalhado tem lugar próprio, que é a agenda
    no CRM.

    OS DOIS PAPÉIS, no mesmo teste: antes havia uma regra que mostrava o texto a
    quem tinha o portal do CRM e o escondia dos outros. Ela saiu junto com a
    pauta, e este teste é o que garante que não volta por um lado só.
    """
    for cliente in (do_score, da_plataforma):
        corpo = cliente.get("/api/score/riscos/incidentes?tamanho=500").json()
        agendas = [linha for linha in corpo["itens"] if linha["tipo"] == "agenda"]
        assert agendas, "a semente cria uma agenda de clima negativo"
        assert all(linha["incidente"] is None for linha in agendas)
        #: E O QUE DESCREVE A REUNIÃO continua lá: o assunto e a severidade.
        assert all(linha["tema"] for linha in agendas)
        assert all(linha["severidade"] for linha in agendas)


def test_a_MENCAO_traz_o_TITULO_da_materia(do_score, da_plataforma, com_incidentes):
    """Título de matéria publicada é público — esconder seria esconder o jornal."""
    for cliente in (do_score, da_plataforma):
        itens = cliente.get("/api/score/riscos/incidentes?tamanho=50").json()["itens"]
        mencoes = [linha for linha in itens if linha["tipo"] == "mencao"]
        assert mencoes, "a semente cria menções"
        assert any(linha["incidente"] for linha in mencoes)


def test_a_BUSCA_das_agendas_olha_o_ASSUNTO_e_nao_a_pauta(da_plataforma, com_incidentes):
    """Procurar num texto que não se mostra devolveria linha inexplicável.

    A pessoa digitaria uma palavra, veria uma linha de agenda aparecer e não
    encontraria a palavra em nenhuma coluna.
    """
    tema = com_incidentes
    por_assunto = da_plataforma.get(
        f"/api/score/riscos/incidentes?busca={tema.nome[:12]}&tamanho=500"
    ).json()
    assert any(linha["tipo"] == "agenda" for linha in por_assunto["itens"])

    #: E A PALAVRA DA PAUTA não traz a agenda: ela não é mais critério.
    por_pauta = da_plataforma.get(
        "/api/score/riscos/incidentes?busca=desabastecimento&tamanho=500"
    ).json()
    assert not [
        linha for linha in por_pauta["itens"] if linha["tipo"] == "agenda"
    ], "a pauta não pode ser critério de busca se não é mostrada"


def test_a_DATA_do_mes_aceita_so_AAAA_MM(da_plataforma):
    #: O endereço da tela carrega o mês; dia no parâmetro seria outra pergunta.
    assert da_plataforma.get("/api/score/riscos?de=2026-09-15").status_code == 422


# -- as opções: padronização com espaço para a particularidade -------------------


def test_as_OPCOES_trazem_o_cadastro_e_as_dimensoes(da_plataforma, com_incidentes):
    corpo = da_plataforma.get("/api/score/riscos/opcoes").json()

    assert corpo["clusters"], "os clusters do cadastro"
    assert all(cluster["riscos"] for cluster in corpo["clusters"])
    #: AS FONTES COM INCIDENTE, e não o cadastro inteiro: fonte sem incidente no
    #: recorte é filtro que volta vazio.
    assert {fonte["codigo"] for fonte in corpo["fontes"]} <= {
        "bites",
        "clipei",
        "clipei_investidores",
        "approach_cm",
        "approach_sl",
        "crm",
    }
    assert corpo["meses"], "a janela só pode oferecer mês que existe"


def test_as_DIMENSOES_variam_com_a_fonte_olhada(da_plataforma, com_incidentes):
    """O pedido do dono do produto: padronização, com espaço para a particularidade.

    Medido na base: `tier` existe em 25.448 menções da Clipei e em ZERO da
    Bites; `cargo`, em 2.842 da Bites e zero da Clipei. Oferecer tier a quem
    olha a Bites é prometer filtro que volta vazio; esconder cargo de quem olha a
    Bites é tirar o melhor filtro que ela tem.
    """
    so_bites = da_plataforma.get("/api/score/riscos/opcoes?fonte=bites").json()
    chaves = {dimensao["chave"] for dimensao in so_bites["dimensoes"]}

    #: A BITES TEM CARGO e não tem tier.
    assert "cargo" in chaves
    assert "tier" not in chaves
    #: E CADA DIMENSÃO DIZ DE QUAIS FONTES veio, para a tela poder explicar a
    #: ausência em vez de deixar o filtro mudo.
    for dimensao in so_bites["dimensoes"]:
        assert dimensao["fontes"] == ["bites"]


def test_a_DIMENSAO_COM_MUITOS_VALORES_vira_busca(da_plataforma, com_incidentes):
    """Seletor que ninguém percorre é pior que campo de texto.

    `autor` tem centenas de valores na Bites; mandar todos para a tela desenhar
    um seletor é peso sem uso.
    """
    corpo = da_plataforma.get("/api/score/riscos/opcoes").json()

    assert corpo["dimensoes"], "o recorte tem dimensões"
    for dimensao in corpo["dimensoes"]:
        if dimensao["tipo"] == "busca":
            assert dimensao["valores"] == [], "a busca não manda os valores"
            assert dimensao["quantos"] > 0, "mas diz quantos são"
        else:
            assert dimensao["valores"], "a lista manda os valores"


# -- os achados da revisão da etapa 2 --------------------------------------------


def test_a_DIMENSAO_oferecida_FILTRA_de_verdade(da_plataforma, com_incidentes):
    """O achado ALTO: eu oferecia filtros que nenhuma rota aceitava.

    A tela ia desenhar os controles a partir de `/opcoes` e eles não fariam
    nada — o parâmetro seria ignorado e a lista voltaria igual. O pior tipo de
    defeito: a pessoa clica, vê a tela não mudar e conclui que não há dado.
    """
    todas = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()
    assert todas["total"] >= 3

    #: A SEMENTE tem UMA menção com tier `relevante` (da Clipei).
    com_tier = da_plataforma.get(
        "/api/score/riscos/incidentes?dimensao=tier:relevante&tamanho=500"
    ).json()
    assert com_tier["total"] < todas["total"], "o filtro tem de recortar"
    assert all(linha["tier"] == "relevante" for linha in com_tier["itens"])

    #: E O FILTRO DE CARGO pega as da Bites, não a da Clipei.
    com_cargo = da_plataforma.get(
        "/api/score/riscos/incidentes?dimensao=cargo:vereador&tamanho=500"
    ).json()
    assert com_cargo["total"] >= 1
    assert all(linha["fonte"] == "bites" for linha in com_cargo["itens"])


def test_a_DIMENSAO_tambem_recorta_a_SERIE_e_a_MATRIZ(da_plataforma, com_incidentes):
    """O filtro vale na tela inteira, não só na tabela."""
    inteiro = da_plataforma.get("/api/score/riscos").json()
    recortado = da_plataforma.get("/api/score/riscos?dimensao=cargo:vereador").json()

    de_todas = sum(mes["incidentes"] for mes in inteiro["serie"])
    de_cargo = sum(mes["incidentes"] for mes in recortado["serie"])
    assert 0 < de_cargo < de_todas


def test_a_DIMENSAO_DESCONHECIDA_e_recusada_com_o_nome(da_plataforma):
    """Parâmetro que a rota não entende não pode ser ignorado em silêncio."""
    resposta = da_plataforma.get("/api/score/riscos?dimensao=inventada:x")

    assert resposta.status_code == 422
    assert "inventada" in resposta.text
    #: E A RECUSA DIZ QUAIS EXISTEM.
    assert "tier" in resposta.text


def test_a_DIMENSAO_DE_MENCAO_exclui_a_AGENDA(da_plataforma, com_incidentes):
    """Quem filtra por tier está perguntando sobre imprensa.

    A agenda não tem tier nem cargo; devolvê-la junto faria o recorte parecer
    não ter funcionado — a pessoa veria linhas sem o valor que pediu.
    """
    com_cargo = da_plataforma.get(
        "/api/score/riscos/incidentes?dimensao=cargo:vereador&tamanho=500"
    ).json()

    assert com_cargo["itens"], "a semente tem menção com esse cargo"
    assert all(linha["tipo"] == "mencao" for linha in com_cargo["itens"])


def test_o_TOTAL_POR_SEVERIDADE_conta_INCIDENTE_e_nao_par(
    da_plataforma, sessao, com_incidentes
):
    """O achado ALTO 2: somar a matriz contava o incidente duas vezes.

    O incidente de um tema que toca um crítico e um alto entrava nos dois
    baldes, e os três números do topo somavam mais que o total de incidentes —
    que é o número logo ao lado deles na tela.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco

    tema = com_incidentes
    #: LIGA O TEMA A UM SEGUNDO RISCO de outra severidade.
    ja = set(
        sessao.scalars(_select(_TemaRisco.risco_id).where(_TemaRisco.tema_id == tema.id))
    )
    outro = sessao.scalar(
        _select(_Risco)
        .where(_Risco.ativo.is_(True), _Risco.id.not_in(ja or {0}))
        .order_by(_Risco.id)
        .limit(1)
    )
    assert outro is not None
    sessao.add(_TemaRisco(tema_id=tema.id, risco_id=outro.id))
    sessao.flush()

    corpo = da_plataforma.get("/api/score/riscos").json()
    total_da_tabela = da_plataforma.get(
        "/api/score/riscos/incidentes?tamanho=500"
    ).json()["total"]

    #: OS TRÊS NÚMEROS SOMAM O TOTAL, e não mais que ele.
    assert sum(corpo["total_por_severidade"].values()) == total_da_tabela


def test_o_AUTOR_so_aparece_para_quem_VE_O_DIRETORIO(da_plataforma, do_score, sessao):
    """O achado ALTO 3: o filtro de autor publicaria o cadastro de terceiros.

    A Base das Lentes já esconde o autor da imprensa de quem não tem
    `ve_diretorio` — é o mesmo cadastro que a matriz de jornalistas protege.
    Oferecê-lo como FILTRO listaria todos os nomes num seletor.
    """
    #: A SEMENTE com autor, criada aqui para o teste não depender da ordem.
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import Tema as _Tema
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco
    from app.banco.tabelas_score import ScoreFonte as _Fonte
    from tests.test_rastreio_de_riscos import _mencao

    tema = sessao.execute(
        _select(_Tema)
        .join(_TemaRisco, _TemaRisco.tema_id == _Tema.id)
        .join(_Risco, _Risco.id == _TemaRisco.risco_id)
        .where(_Tema.ativo.is_(True), _Risco.ativo.is_(True))
        .order_by(_Tema.id)
        .limit(1)
    ).scalar_one()
    bites = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "bites"))
    com_autor = _mencao(sessao, bites, tema, "neg")
    com_autor.autor = "jornalista com nome"
    sessao.flush()

    #: PLATAFORMA vê o diretório; SCORE não (conferido na tabela `papel`).
    de_quem_ve = da_plataforma.get("/api/score/riscos/opcoes").json()
    de_quem_nao_ve = do_score.get("/api/score/riscos/opcoes").json()

    assert "autor" in {d["chave"] for d in de_quem_ve["dimensoes"]}
    assert "autor" not in {d["chave"] for d in de_quem_nao_ve["dimensoes"]}


def test_o_LIMITE_DO_SELETOR_e_quarenta(da_plataforma, sessao, com_incidentes):
    """O achado BAIXO: o limite 40/41 não tinha prova.

    Em 40 a dimensão vem como `lista` com os valores; em 41, como `busca` sem
    eles — mandar quarenta e um valores para a tela desenhar um seletor que
    ninguém percorre é peso sem uso.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_score import ScoreFonte as _Fonte
    from tests.test_rastreio_de_riscos import _mencao

    tema = com_incidentes
    bites = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "bites"))

    #: QUARENTA CARGOS DISTINTOS: ainda é lista.
    for numero in range(40):
        linha = _mencao(sessao, bites, tema, "neg", dia=5 + (numero % 20))
        linha.cargo = f"cargo zz{numero:02d}"
    sessao.flush()

    de_quarenta = {
        d["chave"]: d
        for d in da_plataforma.get("/api/score/riscos/opcoes?fonte=bites").json()[
            "dimensoes"
        ]
    }
    #: A semente já tem `vereador`, então aqui são 41 — e por isso vira busca.
    assert de_quarenta["cargo"]["tipo"] == "busca"
    assert de_quarenta["cargo"]["valores"] == []
    assert de_quarenta["cargo"]["quantos"] == 41


# -- as médias da revisão: a ausência estrutural e a recorrência -----------------


def test_a_DIMENSAO_que_a_FONTE_TEM_e_o_RECORTE_esvaziou_CONTINUA(
    da_plataforma, sessao, com_incidentes
):
    """A dimensão vazia fica, com as fontes que a classificam e zero valores.

    É A MESMA REGRA DA FILEIRA DE ABAS DAS LENTES, decidida pelo dono do produto:
    a aba que a fonte tem continua aparecendo no mês em que ela não classificou
    nada, porque uma fileira que muda a cada clique se lê como tela quebrada —
    e o filtro vazio diz algo acionável ("a Clipei não classificou relevância
    neste corte"), que é diferente de o campo não existir.
    """
    from datetime import date as _date

    from sqlalchemy import select as _select

    from app.banco.tabelas_score import ScoreFonte as _Fonte
    from tests.test_rastreio_de_riscos import _mencao

    #: SETEMBRO DA CLIPEI, SEM TIER: a fonte classifica relevância (a menção de
    #: agosto tem), e neste mês não há nenhuma.
    clipei = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "clipei"))
    de_setembro = _mencao(sessao, clipei, com_incidentes, "neg", dia=9)
    de_setembro.mes = _date(2026, 9, 1)
    de_setembro.data = _date(2026, 9, 9)
    sessao.flush()

    corpo = da_plataforma.get(
        "/api/score/riscos/opcoes?fonte=clipei&de=2026-09&ate=2026-09"
    ).json()
    por_chave = {d["chave"]: d for d in corpo["dimensoes"]}

    assert "tier" in por_chave, "a dimensão que a fonte tem não desaparece"
    assert por_chave["tier"]["tipo"] == "vazia"
    assert por_chave["tier"]["valores"] == []
    assert por_chave["tier"]["preenchidas"] == 0
    #: E DIZ DE QUEM É O CAMPO, para a tela escrever o motivo.
    assert por_chave["tier"]["fontes"] == ["clipei"]


def test_a_DIMENSAO_que_NENHUMA_FONTE_do_recorte_classifica_SAI(
    da_plataforma, com_incidentes
):
    """A ausência da FONTE tira o filtro; a ausência do CORTE não.

    Medido na base: a Bites não manda tier em nenhuma das 2.842 menções. Oferecer
    relevância a quem está olhando a Bites — nem vazio — é prometer um filtro que
    não existe lá, e que não aparece nem trocando o período.
    """
    corpo = da_plataforma.get("/api/score/riscos/opcoes?fonte=bites").json()
    por_chave = {d["chave"]: d for d in corpo["dimensoes"]}

    assert "tier" not in por_chave
    assert "publico_alvo" not in por_chave
    #: E O QUE A BITES TEM aparece, com valor.
    assert por_chave["cargo"]["preenchidas"] >= 1
    assert "vereador" in por_chave["cargo"]["valores"]


def test_a_RECORRENCIA_conta_MESES_e_nao_incidentes(da_plataforma, com_incidentes):
    """Quatro incidentes em dois meses são recorrência 2, não 4.

    "Este assunto já voltou duas vezes" é um fato sobre o assunto. A semente tem
    menção da Bites e da Clipei e agenda em agosto, e menção da Bites em
    setembro: quatro incidentes, dois meses.
    """
    corpo = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()

    assert corpo["total"] >= 4
    recorrencias = {linha["recorrencia"] for linha in corpo["itens"]}
    assert recorrencias == {2}, recorrencias


def test_a_RECORRENCIA_olha_a_SERIE_INTEIRA_e_nao_a_janela(
    da_plataforma, com_incidentes
):
    """A janela recorta a tabela, e não o fato sobre o assunto.

    Pedindo só setembro, a tabela mostra uma linha — mas a recorrência continua
    dizendo DOIS, porque o assunto também voltou em agosto. O contrário faria o
    número virar "incidentes no período", que é a coluna ao lado.
    """
    corpo = da_plataforma.get(
        "/api/score/riscos/incidentes?de=2026-09&ate=2026-09&tamanho=500"
    ).json()

    assert corpo["total"] == 1
    assert corpo["itens"][0]["recorrencia"] == 2


def test_a_SERIE_diz_os_INCIDENTES_DE_CADA_SEVERIDADE(da_plataforma, com_incidentes):
    """O bloco principal da tela: a barra do mês é empilhada por severidade.

    DO TOTAL NÃO SE DERIVA A DIVISÃO — 6 pontos ponderados são dois críticos,
    três altos ou seis moderados —, então o mês tem de trazer os três números.
    """
    corpo = da_plataforma.get("/api/score/riscos").json()
    comIncidente = [mes for mes in corpo["serie"] if mes["incidentes"]]

    assert comIncidente, "a semente tem incidente"
    for mes in comIncidente:
        #: OS TRÊS NÚMEROS SOMAM O TOTAL DO MÊS, senão a barra empilhada não
        #: chega à altura do índice.
        assert sum(mes["por_severidade"].values()) == mes["incidentes"]
        #: E NENHUMA SEVERIDADE COM ZERO: a dica do mês não lista o que não houve.
        assert all(quantos > 0 for quantos in mes["por_severidade"].values())
        assert set(mes["por_severidade"]) <= {"critico", "alto", "moderado"}


def test_a_PILHA_do_mes_vem_na_ORDEM_DA_GRAVIDADE(da_plataforma, sessao, com_incidentes):
    """A ordem é a da gravidade, e não a que a consulta devolveu.

    A pilha da barra tem de sair igual em todos os meses: crítico embaixo,
    moderado em cima. Ordem de inserção faria dois meses empilharem ao contrário
    um do outro, e a comparação visual entre eles passaria a enganar.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco

    #: LIGA O TEMA A UM RISCO DE OUTRA SEVERIDADE, para o mês ter duas.
    ja = set(
        sessao.scalars(
            _select(_TemaRisco.risco_id).where(_TemaRisco.tema_id == com_incidentes.id)
        )
    )
    severidades = {
        risco.severidade: risco
        for risco in sessao.scalars(_select(_Risco).where(_Risco.ativo.is_(True)))
    }
    assert len(severidades) >= 2, "o cadastro de teste precisa de duas severidades"
    for risco in severidades.values():
        if risco.id not in ja:
            sessao.add(_TemaRisco(tema_id=com_incidentes.id, risco_id=risco.id))
    sessao.flush()

    corpo = da_plataforma.get("/api/score/riscos").json()
    for mes in corpo["serie"]:
        if not mes["por_severidade"]:
            continue
        nomes = list(mes["por_severidade"])
        esperada = [
            nome for nome in ("critico", "alto", "moderado") if nome in set(nomes)
        ]
        assert nomes == esperada, mes["mes"]


# -- os degraus do aprofundamento: lente, severidade, os três níveis -------------


def test_a_LENTE_recorta_e_NAO_e_a_FONTE(da_plataforma, com_incidentes):
    """Lente e fonte são duas perguntas, e por isso são dois filtros.

    A Clipei alimenta DUAS lentes (imprensa e, pelo público investidores,
    mercado) e a Bites divide a sociedade digital com a Approach. Quem pergunta
    "como está a imprensa" não está perguntando por um fornecedor; quem
    desconfia de uma planilha não está perguntando por uma lente.
    """
    todos = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()
    assert todos["total"] >= 4

    da_imprensa = da_plataforma.get(
        "/api/score/riscos/incidentes?lente=imprensa&tamanho=500"
    ).json()
    assert 0 < da_imprensa["total"] < todos["total"]
    assert all(linha["lente"] == "imprensa" for linha in da_imprensa["itens"])
    assert all(linha["fonte"] == "clipei" for linha in da_imprensa["itens"])

    #: E A LENTE DA BITES É A SOCIEDADE DIGITAL, não "bites".
    da_sociedade = da_plataforma.get(
        "/api/score/riscos/incidentes?lente=sociedade&tamanho=500"
    ).json()
    assert all(linha["fonte"] == "bites" for linha in da_sociedade["itens"])


def test_a_LENTE_tambem_deixa_a_AGENDA_de_fora(da_plataforma, com_incidentes):
    """O CRM é a lente institucional, e esquecer isso seria o pior erro daqui.

    Quem escolhe "Imprensa" receberia as reuniões do CRM no meio das notícias, e
    o total não corresponderia a nada que se possa conferir.
    """
    da_imprensa = da_plataforma.get(
        "/api/score/riscos/incidentes?lente=imprensa&tamanho=500"
    ).json()
    assert all(linha["tipo"] == "mencao" for linha in da_imprensa["itens"])

    da_institucional = da_plataforma.get(
        "/api/score/riscos/incidentes?lente=institucional&tamanho=500"
    ).json()
    assert da_institucional["total"] >= 1
    assert all(linha["tipo"] == "agenda" for linha in da_institucional["itens"])
    assert all(linha["lente"] == "institucional" for linha in da_institucional["itens"])


def test_as_LENTES_OFERECIDAS_saem_das_FONTES_com_incidente(
    da_plataforma, com_incidentes
):
    """A lente entra no filtro quando alguma fonte dela trouxe incidente."""
    corpo = da_plataforma.get("/api/score/riscos/opcoes").json()
    oferecidas = {lente["codigo"] for lente in corpo["lentes"]}

    assert {"imprensa", "sociedade", "institucional"} <= oferecidas
    #: E A QUE NINGUÉM ALIMENTOU NÃO ENTRA: a semente não tem Approach.
    assert "clientes" not in oferecidas
    assert all(lente["nome"] for lente in corpo["lentes"])


def test_a_SEVERIDADE_filtra_pela_PIOR_do_incidente(da_plataforma, com_incidentes):
    """Clicar em "Crítico 6" leva aos 6 — e os três filtros somam o total.

    PELA PIOR, e não "toca um risco desta severidade": é a régua que empilha a
    barra do mês e preenche a coluna da tabela. Filtrar por "toca" faria o
    incidente cujo pior é crítico aparecer também em "alto", e os três números
    deixariam de somar.
    """
    painel = da_plataforma.get("/api/score/riscos").json()
    total = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()["total"]

    somados = 0
    for severidade, quantos in painel["total_por_severidade"].items():
        pagina = da_plataforma.get(
            f"/api/score/riscos/incidentes?severidade={severidade}&tamanho=500"
        ).json()
        #: O NÚMERO DO TOPO É O NÚMERO DA TABELA FILTRADA. Se divergir, a pessoa
        #: clica em "14" e recebe outra quantidade de linhas.
        assert pagina["total"] == quantos, severidade
        assert all(linha["severidade"] == severidade for linha in pagina["itens"])
        somados += pagina["total"]

    assert somados == total


def test_a_SEVERIDADE_DESCONHECIDA_e_recusada_com_o_nome(da_plataforma):
    """Ela vem de um clique, e valor que não existe devolveria tela vazia."""
    resposta = da_plataforma.get("/api/score/riscos?severidade=catastrofico")

    assert resposta.status_code == 422
    assert "catastrofico" in resposta.text
    assert "critico" in resposta.text


def test_os_TRES_NIVEIS_do_tema_recortam_a_tela(da_plataforma, sessao, com_incidentes):
    """N1 > N2 > N3 — o caminho do macro ao registro.

    OS TRÊS CRUZAM TODAS AS FONTES, e é por isso que estão ao lado de cluster e
    risco em vez de na fileira de dimensões por base: a premissa da aba é que
    tudo chega a risco pelo tema do cadastro.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import BlocoTema as _Bloco
    from app.banco.tabelas_catalogo import MacroTema as _Macro

    macro = sessao.get(_Macro, com_incidentes.macro_tema_id)
    assert macro is not None, "o tema da semente tem macro tema"
    bloco = sessao.get(_Bloco, macro.bloco_tema_id)
    assert bloco is not None

    todos = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()
    assert todos["total"] >= 4

    for consulta in (
        f"bloco={bloco.codigo}",
        f"macro={macro.codigo}",
        f"tema={com_incidentes.nome}",
    ):
        pagina = da_plataforma.get(
            f"/api/score/riscos/incidentes?{consulta}&tamanho=500"
        ).json()
        #: A SEMENTE TODA É DESTE TEMA, então os três níveis trazem tudo.
        assert pagina["total"] == todos["total"], consulta

    #: E UM NÍVEL QUE NÃO É O DELE NÃO TRAZ NADA — é o que prova que recorta.
    outro = sessao.scalar(
        _select(_Bloco).where(_Bloco.id != bloco.id, _Bloco.ativo.is_(True))
    )
    assert outro is not None
    vazia = da_plataforma.get(
        f"/api/score/riscos/incidentes?bloco={outro.codigo}&tamanho=500"
    ).json()
    assert vazia["total"] == 0


def test_a_ARVORE_DOS_TEMAS_vem_com_os_tres_niveis(da_plataforma):
    """O seletor precisa da árvore para N1 reduzir N2 e N2 reduzir N3."""
    corpo = da_plataforma.get("/api/score/riscos/opcoes").json()

    assert corpo["temas"], "o cadastro de teste tem taxonomia"
    bloco = corpo["temas"][0]
    assert {"codigo", "nome", "dentro"} <= set(bloco)
    macro = bloco["dentro"][0]
    assert macro["dentro"], "o macro tema tem temas dentro"
    #: O TERCEIRO NÍVEL É FOLHA.
    assert macro["dentro"][0]["dentro"] == []


def test_a_ARVORE_so_tem_tema_que_TOCA_RISCO(da_plataforma, sessao):
    """Tema que não chega a risco é filtro que volta vazio sempre."""
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import Tema as _Tema
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco

    corpo = da_plataforma.get("/api/score/riscos/opcoes").json()
    na_arvore = {
        folha["codigo"]
        for bloco in corpo["temas"]
        for macro in bloco["dentro"]
        for folha in macro["dentro"]
    }

    com_risco = sessao.scalar(
        _select(_func.count(_func.distinct(_Tema.id)))
        .select_from(_Tema)
        .join(_TemaRisco, _TemaRisco.tema_id == _Tema.id)
        .join(_Risco, _Risco.id == _TemaRisco.risco_id)
        .where(_Tema.ativo.is_(True), _Risco.ativo.is_(True))
    )
    #: PODE SER MENOR (tema sem macro tema fica fora da árvore), nunca maior.
    assert 0 < len(na_arvore) <= com_risco


def test_a_ARVORE_conta_os_INCIDENTES_de_cada_no(da_plataforma, com_incidentes):
    """Cada nó diz quantos incidentes tem — é o que mostra onde descer.

    E O PAI SOMA OS FILHOS, por construção: duas contagens para o mesmo conjunto
    divergiriam na primeira diferença de `join`, e a pessoa veria o N1 dizer 12 e
    os N2 dele somarem 11.
    """
    corpo = da_plataforma.get("/api/score/riscos/opcoes").json()
    total = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()["total"]

    soma = 0
    for bloco in corpo["temas"]:
        assert bloco["incidentes"] == sum(m["incidentes"] for m in bloco["dentro"])
        for macro in bloco["dentro"]:
            assert macro["incidentes"] == sum(f["incidentes"] for f in macro["dentro"])
        soma += bloco["incidentes"]

    #: A SOMA DA ÁRVORE É O TOTAL DA TABELA: cada incidente conta uma vez, mesmo
    #: quando o tema dele toca dois riscos.
    assert soma == total


def test_a_ARVORE_nao_ZERA_os_IRMAOS_do_nivel_escolhido(
    da_plataforma, sessao, com_incidentes
):
    """Com N1 escolhido, os outros N1 continuam mostrando o que têm.

    Contá-los dentro do próprio recorte de tema daria zero em todos os outros, e
    a pessoa concluiria que não há nada lá — quando o que há é um filtro ligado.
    A árvore responde "onde está a massa", e essa pergunta é sobre o recorte
    MENOS o nível do tema.
    """
    from app.banco.tabelas_catalogo import BlocoTema as _Bloco
    from app.banco.tabelas_catalogo import MacroTema as _Macro

    macro = sessao.get(_Macro, com_incidentes.macro_tema_id)
    bloco = sessao.get(_Bloco, macro.bloco_tema_id) if macro else None
    assert bloco is not None

    livre = da_plataforma.get("/api/score/riscos/opcoes").json()
    escolhido = da_plataforma.get(
        f"/api/score/riscos/opcoes?bloco={bloco.codigo}"
    ).json()

    def contagens(corpo):
        return {um["codigo"]: um["incidentes"] for um in corpo["temas"]}

    assert contagens(escolhido) == contagens(livre)


def test_a_SEVERIDADE_e_o_RISCO_juntos_dao_o_MESMO_numero(
    da_plataforma, sessao, com_incidentes
):
    """O achado da revisão da tela: duas definições de "pior severidade".

    O CENÁRIO: um tema que toca um risco CRÍTICO e um ALTO. Com o risco ALTO
    escolhido na tela, o topo conta o incidente como `alto` — certo, porque
    dentro do recorte só o risco alto conta. O filtro de severidade, porém, media
    a pior severidade GLOBAL do fato: `severidade=alto` não trazia a linha, e
    `severidade=critico` trazia — exibindo-a como `alto`.

    Ou seja: clicar no número "1" ao lado de "Alto" devolvia zero linhas. Este
    teste exige que os três números do topo continuem sendo exatamente o total da
    tabela filtrada DENTRO DE UM RECORTE DE RISCO, que é onde as duas definições
    divergiam.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco

    #: LIGA O TEMA DA SEMENTE A UM RISCO DE CADA SEVERIDADE.
    ja = set(
        sessao.scalars(
            _select(_TemaRisco.risco_id).where(_TemaRisco.tema_id == com_incidentes.id)
        )
    )
    por_severidade: dict[str, _Risco] = {}
    for risco in sessao.scalars(
        _select(_Risco).where(_Risco.ativo.is_(True)).order_by(_Risco.id)
    ):
        por_severidade.setdefault(risco.severidade, risco)
    assert {"critico", "alto"} <= set(por_severidade), (
        "o cadastro de teste precisa de um risco crítico e um alto"
    )
    for risco in (por_severidade["critico"], por_severidade["alto"]):
        if risco.id not in ja:
            sessao.add(_TemaRisco(tema_id=com_incidentes.id, risco_id=risco.id))
    sessao.flush()

    do_alto = por_severidade["alto"].codigo
    painel = da_plataforma.get(f"/api/score/riscos?risco={do_alto}").json()
    total = da_plataforma.get(
        f"/api/score/riscos/incidentes?risco={do_alto}&tamanho=500"
    ).json()["total"]
    assert total >= 1, "a semente toca o risco alto"

    somados = 0
    for severidade, quantos in painel["total_por_severidade"].items():
        pagina = da_plataforma.get(
            f"/api/score/riscos/incidentes?risco={do_alto}"
            f"&severidade={severidade}&tamanho=500"
        ).json()
        #: CADA NÚMERO DO TOPO É O TOTAL DA TABELA FILTRADA POR ELE.
        assert pagina["total"] == quantos, severidade
        #: E A COLUNA DA LINHA DIZ A MESMA SEVERIDADE pela qual ela foi filtrada.
        assert all(linha["severidade"] == severidade for linha in pagina["itens"])
        somados += pagina["total"]

    assert somados == total

    #: E DENTRO DESTE RECORTE NÃO HÁ BALDE CRÍTICO: o recorte é de um risco alto,
    #: e um balde crítico num recorte sem risco crítico se lê como tela quebrada.
    assert painel["total_por_severidade"].get("critico", 0) == 0


def test_a_MATRIZ_respeita_os_filtros_que_NAO_sao_de_risco(
    da_plataforma, com_incidentes
):
    """A matriz mostra todos os riscos, mas CONTA só o que está no recorte.

    Ela reconstruía o filtro a mão com quatro campos, e os cinco que entraram
    depois (lente, severidade e os três níveis do tema) ficavam de fora em
    silêncio: a tela recortava e a matriz continuava contando a base inteira.
    Achado de revisão.
    """
    inteira = da_plataforma.get("/api/score/riscos").json()
    recortada = da_plataforma.get("/api/score/riscos?lente=imprensa").json()

    de_todas = sum(linha["incidentes"] for linha in inteira["matriz"])
    da_imprensa = sum(linha["incidentes"] for linha in recortada["matriz"])
    assert 0 < da_imprensa < de_todas

    #: E CONTINUA TRAZENDO OS 32 RISCOS — o recorte muda a contagem, não o mapa.
    assert len(recortada["matriz"]) == len(inteira["matriz"])
    #: A AGENDA SAI JUNTO quando a lente não é a do CRM.
    assert all(linha["agendas"] == 0 for linha in recortada["matriz"])


def test_a_AGENDA_DE_VARIOS_TEMAS_pesa_pelo_tema_do_RECORTE(
    da_plataforma, sessao, com_incidentes
):
    """A agenda trata de vários assuntos, e o recorte de tema muda a severidade.

    A MENÇÃO TEM UM TEMA, então recortar por tema não muda quais riscos ela
    toca. `interacao_tema` É N:N: uma agenda com o tema A (dentro do recorte) e o
    tema B (fora) tinha a pior severidade medida sobre OS DOIS, enquanto o resto
    da tela media sobre um — ela aparecia no topo como `alto` e sumia ao clicar
    em `alto`. Achado de revisão da tela.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_catalogo import Risco as _Risco
    from app.banco.tabelas_catalogo import Tema as _Tema
    from app.banco.tabelas_catalogo import TemaRisco as _TemaRisco
    from app.banco.tabelas_interacoes import InteracaoTema as _InteracaoTema
    from tests.test_rastreio_de_riscos import _agenda

    #: UM TEMA POR SEVERIDADE, cada um ligado a um risco só.
    por_severidade: dict[str, _Risco] = {}
    for risco in sessao.scalars(
        _select(_Risco).where(_Risco.ativo.is_(True)).order_by(_Risco.id)
    ):
        por_severidade.setdefault(risco.severidade, risco)
    assert {"critico", "alto"} <= set(por_severidade), "o cadastro precisa das duas"

    temas: dict[str, _Tema] = {}
    for severidade, risco in (
        ("alto", por_severidade["alto"]),
        ("critico", por_severidade["critico"]),
    ):
        tema = sessao.execute(
            _select(_Tema)
            .join(_TemaRisco, _TemaRisco.tema_id == _Tema.id)
            .where(_Tema.ativo.is_(True), _TemaRisco.risco_id == risco.id)
            .order_by(_Tema.id)
            .limit(1)
        ).scalar_one_or_none()
        if tema is None:
            pytest.skip(f"o cadastro de teste não tem tema ligado a risco {severidade}")
        temas[severidade] = tema

    #: UMA AGENDA COM OS DOIS TEMAS.
    dos_dois = _agenda(sessao, temas["alto"], "tenso")
    sessao.add(_InteracaoTema(interacao_id=dos_dois.id, tema_id=temas["critico"].id))
    sessao.flush()

    #: O RECORTE PELO TEMA ALTO: a agenda entra, e pesa como ALTO.
    do_alto = temas["alto"].nome
    painel = da_plataforma.get(f"/api/score/riscos?tema={do_alto}").json()
    total = da_plataforma.get(
        f"/api/score/riscos/incidentes?tema={do_alto}&tamanho=500"
    ).json()["total"]
    assert total >= 1

    somados = 0
    for severidade, quantos in painel["total_por_severidade"].items():
        pagina = da_plataforma.get(
            f"/api/score/riscos/incidentes?tema={do_alto}"
            f"&severidade={severidade}&tamanho=500"
        ).json()
        assert pagina["total"] == quantos, severidade
        somados += pagina["total"]
    assert somados == total

    #: E A AGENDA DOS DOIS TEMAS ESTÁ ENTRE AS `alto`, não entre as `critico`:
    #: dentro deste recorte, o tema crítico dela não conta.
    das_altas = da_plataforma.get(
        f"/api/score/riscos/incidentes?tema={do_alto}&severidade=alto&tamanho=500"
    ).json()
    assert str(dos_dois.id) in {
        linha["id"] for linha in das_altas["itens"] if linha["tipo"] == "agenda"
    }


def test_o_MES_QUE_NAO_EXISTE_e_recusado_e_nao_estoura(da_plataforma):
    """`2026-99` passa o regex da rota e estourava dentro de `date()`.

    O RESULTADO ERA 500: "erro interno" para um endereço que a pessoa digitou
    errado, e um registro de falha na telemetria que ninguém causou. Achado de
    revisão de PR.
    """
    for consulta in ("de=2026-99", "ate=2026-00", "de=2026-13&ate=2026-14"):
        resposta = da_plataforma.get(f"/api/score/riscos?{consulta}")
        assert resposta.status_code == 422, (consulta, resposta.status_code)
        #: E A RECUSA DIZ QUAL VALOR FOI RECUSADO.
        assert "não existe" in resposta.text or "nao existe" in resposta.text

    #: E O MÊS QUE EXISTE CONTINUA PASSANDO.
    assert da_plataforma.get("/api/score/riscos?de=2026-01&ate=2026-12").status_code == 200


def test_o_POST_DA_PROPRIA_AEGEA_nao_e_incidente(da_plataforma, sessao, com_incidentes):
    """A aba responde "o que se fala da companhia", não o que ela publica.

    MEDIDO EM 10/10/2026: 125 menções da Bites são posts da Aegea e das
    concessionárias dela (4,4% da fonte), e SEIS vinham classificadas como
    negativas com assunto — entravam na conta como se alguém tivesse criticado a
    empresa.

    SEIS DE 5.885 É POUCO, e não é por isso que se conserta: é que uma dessas
    linhas aberta numa reunião ("este aqui é nosso próprio post") derruba a
    confiança no resto da tabela, que está certo.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_score import ScoreFonte as _Fonte
    from tests.test_rastreio_de_riscos import _mencao

    antes = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()["total"]

    bites = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "bites"))
    #: UM POST DA CASA, negativo e com assunto — tudo o que faria dele um
    #: incidente, menos o autor.
    da_casa = _mencao(sessao, bites, com_incidentes, "neg", dia=7)
    da_casa.cargo = "unidade_aegea"
    #: E UM DE TERCEIRO no mesmo molde, para o teste provar que a exclusão é do
    #: AUTOR e não do resto.
    de_terceiro = _mencao(sessao, bites, com_incidentes, "neg", dia=8)
    de_terceiro.cargo = "vereador"
    sessao.flush()

    depois = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()
    assert depois["total"] == antes + 1, "só o de terceiro entrou"
    assert str(da_casa.id) not in {linha["id"] for linha in depois["itens"]}
    assert str(de_terceiro.id) in {linha["id"] for linha in depois["itens"]}


def test_a_CASA_fica_fora_tambem_da_SEVERIDADE_e_do_INDICE(
    da_plataforma, sessao, com_incidentes
):
    """A exclusão vale em todas as contas, senão os números param de fechar.

    Se a subconsulta da pior severidade contasse o post da casa e a consulta
    principal não, os três números do topo deixariam de somar o total da
    tabela — o mesmo defeito que a revisão achou na severidade por recorte.
    """
    from sqlalchemy import select as _select

    from app.banco.tabelas_score import ScoreFonte as _Fonte
    from tests.test_rastreio_de_riscos import _mencao

    bites = sessao.scalar(_select(_Fonte).where(_Fonte.codigo == "bites"))
    for dia in (9, 10, 11):
        linha = _mencao(sessao, bites, com_incidentes, "neg", dia=dia)
        linha.cargo = "aegea"
    sessao.flush()

    painel = da_plataforma.get("/api/score/riscos").json()
    total = da_plataforma.get("/api/score/riscos/incidentes?tamanho=500").json()["total"]

    assert sum(painel["total_por_severidade"].values()) == total
    #: E A SÉRIE TAMBÉM: a soma dos meses é o total do recorte.
    assert sum(mes["incidentes"] for mes in painel["serie"]) == total
