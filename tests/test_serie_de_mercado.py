"""A leitura das duas séries que o gráfico cruza.

O QUE ESTE ARQUIVO PROTEGE, e o primeiro item é o que justifica o módulo existir:

1. QUE O ÍNDICE SAIA PELA ROTA DE MERCADO. `/api/score/serie` está atrás de
   `exigir_portal_score`; quem tem só `acessa_inteligencia_de_mercado` recebe
   403 dela. A linha do eixo direito sairia VAZIA por permissão, não por falta
   de dado — e na tela isso se lê como "o score não tem número neste período".
   O pior formato de erro de autorização é o que parece dado;

2. que o número seja O MESMO do painel de KPIs, porque sai das mesmas funções;

3. que o VÃO seja ausência de ponto, e não um ponto nulo — dia sem pregão não
   pode descer a linha até zero;

4. que a granularidade fique explícita no payload: o bond tem `data`, o índice
   tem `mes`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco import repositorio_score
from app.banco.tabelas_mercado import BondCotacao, Emissor
from app.banco.tabelas_score import ScoreFonte, ScoreMesFonte
from app.casos_de_uso import serie_de_mercado
from app.dominio.erros import RegraViolada
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

AEGEA_31 = "AEGEBZ31"
AEGEA_36 = "AEGEBZ36"
DE_PAR = "PETBRA30"


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
def mes_com_dado(sessao: Session) -> date:
    """UM mês com leitura, para o índice existir.

    SEMEADO EM VEZ DE PULADO, e isto é conserto: as duas asserções que mais
    importam deste arquivo — que o índice bate com o do painel de KPIs, e que o
    recorte pega o mês INTEIRO — dependiam de o banco de teste ter mês com dado,
    e ele não tem. Elas pulavam, e um teste que pula não protege nada.

    `score_mes_fonte` é uma das três origens que `meses_com_dado` olha, e é a
    mais simples de semear: não precisa de menção, de estimativa nem de agenda.
    """
    fonte = sessao.scalars(
        select(ScoreFonte).where(ScoreFonte.codigo == "clipei")
    ).one()
    mes = date(2026, 5, 1)
    sessao.add(
        ScoreMesFonte(
            fonte_id=fonte.id,
            mes=mes,
            sentimento="pos",
            tier="",
            mencoes=10,
            soma_log=10,
            soma_engajamento=0,
            soma_cargo=0,
        )
    )
    sessao.flush()
    return mes


def _cotacao(sessao: Session, ticker: str, dia: date, preco=None, rendimento=None):
    sessao.add(
        BondCotacao(
            bond_ticker=ticker,
            data=dia,
            preco_pct_par=None if preco is None else Decimal(str(preco)),
            yield_pct=None if rendimento is None else Decimal(str(rendimento)),
        )
    )
    sessao.flush()


# -- o catálogo ----------------------------------------------------------------


def test_o_catalogo_traz_os_31_papeis_com_a_empresa(sessao):
    papeis = serie_de_mercado.catalogo(sessao)

    assert len(papeis) == 31
    por_ticker = {p.ticker: p for p in papeis}
    assert por_ticker["SABESP30"].emissor == "Sabesp"
    assert por_ticker["SBSPAB31"].emissor == "Sabesp"


def test_a_aegea_vem_PRIMEIRO_no_catalogo(sessao):
    """A ordem é a da legenda, e decidi-la aqui a mantém num lugar só."""
    papeis = serie_de_mercado.catalogo(sessao)

    assert [p.ticker for p in papeis[:3]] == ["AEGEBZ29", AEGEA_31, AEGEA_36]
    assert all(p.e_aegea for p in papeis[:3])
    assert not papeis[3].e_aegea


# -- a série dos bonds ---------------------------------------------------------


def test_sem_tickers_devolve_os_DA_AEGEA(sessao):
    """31 linhas num gráfico não se lê; a tela abre na companhia."""
    _cotacao(sessao, AEGEA_31, date(2026, 1, 5), preco=95.5)
    _cotacao(sessao, DE_PAR, date(2026, 1, 5), preco=80.0)

    lida = serie_de_mercado.ler(sessao)

    assert {s.ticker for s in lida.bonds} == {"AEGEBZ29", AEGEA_31, AEGEA_36}
    assert DE_PAR not in {s.ticker for s in lida.bonds}


def test_o_par_pedido_vem(sessao):
    _cotacao(sessao, DE_PAR, date(2026, 1, 5), preco=80.0)

    lida = serie_de_mercado.ler(sessao, tickers=[DE_PAR])

    assert [s.ticker for s in lida.bonds] == [DE_PAR]
    assert lida.bonds[0].pontos[0].valor == Decimal("80.0000")


def test_ticker_inventado_e_ignorado_em_SILENCIO(sessao):
    """Não é erro do sistema: a série dele simplesmente não existe."""
    _cotacao(sessao, AEGEA_31, date(2026, 1, 5), preco=95.5)

    lida = serie_de_mercado.ler(sessao, tickers=[AEGEA_31, "NAOEXISTE9"])

    assert [s.ticker for s in lida.bonds] == [AEGEA_31]


def test_o_dia_SEM_a_metrica_pedida_nao_vira_ponto(sessao):
    """O vão é ausência de ponto, não ponto nulo.

    A linha de `bond_cotacao` existe quando QUALQUER das duas métricas tem
    valor. A série de preço precisa excluir o dia em que só o yield veio —
    senão o gráfico recebe um ponto sem valor e desce a linha até zero, que é
    exatamente o que a regra do leitor existe para evitar.
    """
    _cotacao(sessao, AEGEA_31, date(2026, 1, 5), preco=95.5, rendimento=9.1)
    _cotacao(sessao, AEGEA_31, date(2026, 1, 6), preco=None, rendimento=9.0)

    por_preco = serie_de_mercado.ler(sessao, tickers=[AEGEA_31], metrica="preco")
    por_yield = serie_de_mercado.ler(sessao, tickers=[AEGEA_31], metrica="yield")

    assert [p.data for p in por_preco.bonds[0].pontos] == [date(2026, 1, 5)]
    assert [p.data for p in por_yield.bonds[0].pontos] == [
        date(2026, 1, 5),
        date(2026, 1, 6),
    ]


def test_o_periodo_recorta_a_serie_do_bond(sessao):
    for dia in (date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)):
        _cotacao(sessao, AEGEA_31, dia, preco=95.5)

    lida = serie_de_mercado.ler(
        sessao, tickers=[AEGEA_31], de=date(2026, 2, 1), ate=date(2026, 2, 28)
    )

    assert [p.data for p in lida.bonds[0].pontos] == [date(2026, 2, 5)]


def test_metrica_que_nao_existe_e_recusada(sessao):
    with pytest.raises(RegraViolada, match="não existe"):
        serie_de_mercado.ler(sessao, metrica="spread")


def test_a_serie_sai_ordenada_por_data(sessao):
    """Um gráfico de linha desenhado fora de ordem vira um nó."""
    for dia in (date(2026, 3, 5), date(2026, 1, 5), date(2026, 2, 5)):
        _cotacao(sessao, AEGEA_31, dia, preco=95.5)

    lida = serie_de_mercado.ler(sessao, tickers=[AEGEA_31])

    datas = [p.data for p in lida.bonds[0].pontos]
    assert datas == sorted(datas)


# -- o índice ------------------------------------------------------------------


def test_o_indice_sai_com_MES_e_nao_com_data(sessao):
    """A granularidade no nome do campo.

    Chamar os dois de `data` faria a tela interpolar uma linha diária que não
    existe — o índice é mensal e se desenha em degraus.
    """
    lida = serie_de_mercado.ler(sessao)

    assert all(hasattr(p, "mes") for p in lida.indice)
    assert all(not hasattr(p, "data") for p in lida.indice)


def test_o_indice_e_o_MESMO_que_a_rota_do_score_calcularia(sessao, mes_com_dado):
    """A asserção que impede as duas telas de divergirem.

    Não se recalcula o índice aqui: são as mesmas `calibracao_vigente`,
    `catalogo_das_lentes` e `indice_do_mes`. Uma segunda implementação
    divergiria no dia em que a régua mudasse, e a divergência apareceria como
    "o Painel de Mercado discorda do de KPIs".
    """
    meses = repositorio_score.meses_com_dado(sessao)
    assert mes_com_dado in meses, "a fixture tinha de pôr o mês no índice"
    calibracao = repositorio_score.calibracao_vigente(sessao)
    catalogo = repositorio_score.catalogo_das_lentes(sessao)
    esperado = {
        mes: repositorio_score.indice_do_mes(sessao, mes, calibracao, catalogo).isr
        for mes in meses
    }

    lida = serie_de_mercado.ler(sessao)

    assert {p.mes: p.isr for p in lida.indice} == esperado


def test_o_periodo_recorta_o_indice_PELO_MES_que_contem_a_data(sessao, mes_com_dado):
    """Pedir de 15/03 a 20/08 inclui março e agosto INTEIROS.

    Recortar pela data perderia o degrau das duas pontas — justamente onde a
    pessoa está olhando quando escolhe o período.
    """
    lida = serie_de_mercado.ler(
        sessao,
        de=mes_com_dado.replace(day=15),
        ate=mes_com_dado.replace(day=20),
    )

    assert [p.mes for p in lida.indice] == [mes_com_dado], (
        "pedir 15 a 20 do mês tem de trazer o mês inteiro — recortar pela data "
        "perderia o degrau das duas pontas do gráfico"
    )


def test_periodo_sem_mes_nenhum_devolve_indice_vazio_sem_erro(sessao):
    lida = serie_de_mercado.ler(
        sessao, de=date(1990, 1, 1), ate=date(1990, 12, 31)
    )

    assert lida.indice == []


# -- o catálogo vem sempre -----------------------------------------------------


def test_o_catalogo_vem_mesmo_sem_cotacao_nenhuma(sessao):
    """O seletor tem de existir antes da primeira subida.

    É a mesma lição da aba Base do Score: a tela que CRIA o dado não pode
    exigir dado. Sem isto, o seletor de papéis nasceria vazio e ninguém saberia
    o que escolher.
    """
    sessao.execute(BondCotacao.__table__.delete())
    sessao.flush()

    lida = serie_de_mercado.ler(sessao)

    assert len(lida.papeis) == 31
    assert all(s.pontos == [] for s in lida.bonds)


def test_a_empresa_da_aegea_e_uma_so_no_catalogo(sessao):
    """`e_aegea` marcando duas empresas faria a legenda mostrar dois grupos."""
    quantas = sessao.scalars(select(Emissor.nome).where(Emissor.e_aegea.is_(True))).all()

    assert list(quantas) == ["Aegea"]
