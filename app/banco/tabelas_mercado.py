"""Tabelas do Painel de Inteligência de Mercado: empresas e cotação de bonds.

Espelham `app/banco/migrations/0100_o_bond_tem_empresa_e_cotacao_diaria.sql`.

ARQUIVO PRÓPRIO, e não uma seção de `tabelas_score.py`: o portal
`inteligencia_de_mercado` é outro domínio — ele lê o índice do Score, mas o
preço de um bond não é menção, não tem lente e não entra em nenhuma régua de
calibração. Misturar os dois faria o módulo do Score crescer com um assunto que
não é dele, e é justamente a organização por domínio que o dono do produto pediu.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.banco.sessao import Tabela


class Emissor(Tabela):
    """A empresa dona dos papéis — a Aegea e os 14 pares acompanhados.

    POR QUE UMA TABELA, e não um texto na linha do bond: a SABESP aparece com
    DOIS prefixos de ticker (`SBSPAB31`, `SBSPAB36` e `SABESP30`). Não existe
    regra de prefixo que resolva isso, então a correspondência ticker → empresa
    é dado — e dado mora em tabela, não em `if` no front.
    """

    __tablename__ = "emissor"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(Text, unique=True)
    #: A Aegea é uma linha como as outras, marcada por esta coluna. A tela
    #: separa companhia de par por aqui, e não por conhecer o nome "Aegea".
    e_aegea: Mapped[bool] = mapped_column(Boolean, default=False)


class Bond(Tabela):
    """Um papel. `descricao`, `id_bloomberg` e `amt_outstanding` vêm da planilha.

    A LINHA NASCE NA MIGRATION e a ingestão só a completa: ticker que a planilha
    traga e não esteja cadastrado é RECUSADO e mostrado na conferência. É a mesma
    doutrina do cadastro de assuntos (`casos_de_uso/temas_da_mencao`) — o
    cadastro é a autoridade, o upload não inventa taxonomia. Bond novo emitido
    pede uma linha, de propósito: é uma decisão de quem acompanha o mercado.
    """

    __tablename__ = "bond"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    emissor_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("emissor.id"))
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_bloomberg: Mapped[str | None] = mapped_column(Text, nullable=True)
    amt_outstanding: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )

    emissor: Mapped[Emissor] = relationship(lazy="joined")


class BondCotacao(Tabela):
    """O fechamento de um papel num dia. Preço e yield na MESMA linha.

    OS DOIS JUNTOS porque chegam juntos, do mesmo pregão, e a tela alterna entre
    eles. Duas linhas com uma coluna `tipo` dobrariam a tabela e obrigariam todo
    `select` a pivotar.

    NULO SIGNIFICA "SEM PREGÃO". A planilha escreve `0` para fim de semana,
    feriado e todo dia anterior à emissão do papel; o leitor converte em nulo, e
    a linha do gráfico abre um vão em vez de desenhar um precipício até zero.

    `numeric`, E NÃO FLOAT: preço de bond se lê em centésimos de ponto e a
    variação que a tela mostra tem uma casa decimal. Somar binário de ponto
    flutuante para depois arredondar é o erro que aparece como "a conta não
    fecha com a planilha".
    """

    __tablename__ = "bond_cotacao"

    bond_ticker: Mapped[str] = mapped_column(
        Text, ForeignKey("bond.ticker"), primary_key=True
    )
    data: Mapped[date] = mapped_column(Date, primary_key=True)
    preco_pct_par: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    yield_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
