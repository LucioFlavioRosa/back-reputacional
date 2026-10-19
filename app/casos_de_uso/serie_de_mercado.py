"""As duas séries que o gráfico cruza: cotação de bond e índice reputacional.

POR QUE AS DUAS SAEM DA MESMA ROTA, e esta é a decisão central deste módulo.

`GET /api/score/serie` já devolve o índice mensal — e está atrás de
`exigir_portal_score`. Quem tiver só `acessa_inteligencia_de_mercado` recebe 403
dela: a linha do eixo direito sairia VAZIA por permissão, não por falta de dado,
e isso se lê na tela como "o score não tem número neste período". O pior formato
de erro de autorização é o que parece dado.

Então o portal de mercado serve as duas séries, com o guarda dele. O que NÃO se
faz é conceder o portal do Score a quem precisa do gráfico: isso abriria o painel
inteiro de KPIs para quem pediu uma linha.

E NÃO SE RECALCULA O ÍNDICE AQUI. `calibracao_vigente`, `catalogo_das_lentes`,
`meses_com_dado` e `indice_do_mes` são as mesmas funções que a rota do Score usa.
É isso que garante que os dois painéis mostrem o MESMO número para o mesmo mês —
uma segunda implementação divergiria no dia em que a régua mudasse, e a
divergência apareceria como "o Painel de Mercado discorda do de KPIs".

A GRANULARIDADE FICA EXPLÍCITA NO PAYLOAD. O bond tem data e o índice tem mês;
devolver os dois como "pontos" obrigaria a tela a adivinhar qual é qual. O índice
sai com `mes`, e é a tela que o desenha em degraus — um valor por mês repetido
nos dias, que é o desenho que mostra na própria forma que a medida é outra.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco import repositorio_score
from app.banco.tabelas_mercado import Bond, BondCotacao, Emissor

#: As duas métricas que a planilha traz, e o que cada uma significa na tela.
#: `yield` SUBINDO É PIORA — o inverso do preço —, e é a tela que pinta a
#: variação; aqui só se diz qual coluna sai.
PRECO = "preco"
YIELD = "yield"
METRICAS = (PRECO, YIELD)


@dataclass(frozen=True)
class PapelNoCatalogo:
    """Um papel, com a empresa dele — o que a legenda e o seletor precisam."""

    ticker: str
    descricao: str | None
    emissor: str
    e_aegea: bool


@dataclass(frozen=True)
class PontoDoBond:
    data: date
    valor: Decimal


@dataclass(frozen=True)
class SerieDoBond:
    ticker: str
    pontos: list[PontoDoBond]


@dataclass(frozen=True)
class PontoDoIndice:
    #: `mes`, e não `data`: o nome do campo é o que diz à tela que a medida é
    #: mensal. Ver o docstring do módulo.
    mes: date
    isr: int | None


@dataclass
class SerieDeMercado:
    papeis: list[PapelNoCatalogo] = field(default_factory=list)
    bonds: list[SerieDoBond] = field(default_factory=list)
    indice: list[PontoDoIndice] = field(default_factory=list)
    metrica: str = PRECO


def catalogo(sessao: Session) -> list[PapelNoCatalogo]:
    """Os 31 papéis com a empresa de cada um, para o seletor.

    DEVOLVE TODOS, e não só os pedidos na consulta: é o que a tela oferece para
    escolher. Ordenado com a AEGEA PRIMEIRO e os pares em seguida, porque é a
    ordem em que a legenda os mostra — e ordenar na tela faria a decisão de
    "quem é a companhia" viver em dois lugares.
    """
    linhas = sessao.execute(
        select(Bond.ticker, Bond.descricao, Emissor.nome, Emissor.e_aegea)
        .join(Emissor, Emissor.id == Bond.emissor_id)
        .order_by(Emissor.e_aegea.desc(), Emissor.nome, Bond.ticker)
    ).all()
    return [
        PapelNoCatalogo(ticker=t, descricao=d, emissor=e, e_aegea=a)
        for t, d, e, a in linhas
    ]


def ler(
    sessao: Session,
    *,
    tickers: list[str] | None = None,
    de: date | None = None,
    ate: date | None = None,
    metrica: str = PRECO,
) -> SerieDeMercado:
    """As duas séries no período, mais o catálogo.

    `tickers` VAZIO SIGNIFICA "OS DA AEGEA", e não "todos": trinta e uma linhas
    num gráfico não se lê, e a tela abre na companhia. Quem quer par pede par.

    O VÃO É AUSÊNCIA DE PONTO, não um ponto nulo. Dia sem pregão não tem linha
    em `bond_cotacao` (o leitor converteu o `0` da planilha em nulo e a chave só
    nasce quando há valor), e um dia cujo preço é nulo mas o yield não entra na
    série de yield e fica fora da de preço. É o que faz a linha abrir vão em vez
    de descer a zero.
    """
    if metrica not in METRICAS:
        from app.dominio.erros import RegraViolada

        raise RegraViolada(
            f"Métrica {metrica!r} não existe. Use {' ou '.join(METRICAS)}."
        )

    papeis = catalogo(sessao)
    escolhidos = tickers or [p.ticker for p in papeis if p.e_aegea]
    #: SÓ OS CADASTRADOS, e em silêncio: um ticker inventado na URL não é erro
    #: do sistema nem merece 422 — a série dele simplesmente não existe, e a
    #: legenda mostra o que voltou.
    conhecidos = {p.ticker for p in papeis}
    escolhidos = [t for t in escolhidos if t in conhecidos]

    coluna = (
        BondCotacao.preco_pct_par if metrica == PRECO else BondCotacao.yield_pct
    )
    condicoes = [
        BondCotacao.bond_ticker.in_(escolhidos),
        #: O NULO NÃO ENTRA. A linha existe quando QUALQUER das duas métricas
        #: tem valor, então a série de preço precisa excluir o dia em que só o
        #: yield veio — senão o gráfico recebe um ponto sem valor.
        coluna.is_not(None),
    ]
    if de is not None:
        condicoes.append(BondCotacao.data >= de)
    if ate is not None:
        condicoes.append(BondCotacao.data <= ate)

    por_ticker: dict[str, list[PontoDoBond]] = {t: [] for t in escolhidos}
    for ticker, dia, valor in sessao.execute(
        select(BondCotacao.bond_ticker, BondCotacao.data, coluna)
        .where(*condicoes)
        .order_by(BondCotacao.bond_ticker, BondCotacao.data)
    ):
        por_ticker[ticker].append(PontoDoBond(data=dia, valor=valor))

    return SerieDeMercado(
        papeis=papeis,
        #: NA ORDEM DO CATÁLOGO, e não na dos `tickers` pedidos: a legenda segue
        #: a mesma ordem do seletor, e a cor de cada série vem da posição.
        bonds=[
            SerieDoBond(ticker=p.ticker, pontos=por_ticker[p.ticker])
            for p in papeis
            if p.ticker in por_ticker
        ],
        indice=_indice(sessao, de=de, ate=ate),
        metrica=metrica,
    )


def _indice(
    sessao: Session, *, de: date | None, ate: date | None
) -> list[PontoDoIndice]:
    """O índice mensal da companhia, pelas MESMAS funções da rota do Score.

    RECORTA PELO MÊS QUE CONTÉM a data, e não pela data: pedir de 15/03 a 20/08
    tem de incluir março e agosto inteiros, senão o gráfico perde o degrau das
    duas pontas — justamente onde a pessoa está olhando.
    """
    meses = repositorio_score.meses_com_dado(sessao)
    if de is not None:
        meses = [m for m in meses if m >= de.replace(day=1)]
    if ate is not None:
        meses = [m for m in meses if m <= ate.replace(day=1)]
    if not meses:
        return []

    calibracao = repositorio_score.calibracao_vigente(sessao)
    catalogo_das_lentes = repositorio_score.catalogo_das_lentes(sessao)
    return [
        PontoDoIndice(
            mes=mes,
            isr=repositorio_score.indice_do_mes(
                sessao, mes, calibracao, catalogo_das_lentes
            ).isr,
        )
        for mes in meses
    ]
