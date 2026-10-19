"""O cadastro de empresas e bonds da `0100`.

O QUE ESTE ARQUIVO PROTEGE. O pedido do dono do produto foi "uma tabela por
empresa (Sabesp, Eletrobras, Light, Simpar, Movida, Vamos, Rumo, Hidrovias,
Ultrapar, Açu, Braskem, Rede D'Or, Minerva, Petrobras) ou outras se tiver". A
entrega é um CADASTRO de empresas, e o que ele promete é:

1. que as 14 empresas pedidas existam, cada uma com os papéis certos;
2. que a Aegea seja distinguível por coluna, e não pelo nome;
3. que a SABESP — a razão de o cadastro existir — una os DOIS prefixos de
   ticker num só emissor.

O PONTO 3 É O CARO. `SBSPAB31`, `SBSPAB36` e `SABESP30` são a mesma empresa com
prefixos diferentes. Qualquer tentação futura de derivar a empresa dos quatro
primeiros caracteres do ticker quebra aqui, e é para isso que o teste existe.

A `0100` JÁ SE CONFERE, com um `do $$` que levanta exceção se o `join` por nome
não casar. Este arquivo é a outra metade: a migration garante que não gravou
LIXO, estes testes garantem que gravou o que foi PEDIDO. Uma migration que
semeasse 31 bonds em 15 empresas erradas passaria na conferência dela.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_mercado import Bond, Emissor
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: AS CATORZE QUE O DONO DO PRODUTO LISTOU, na ordem em que ele as escreveu.
PARES_PEDIDOS = (
    "Sabesp",
    "Eletrobras",
    "Light",
    "Simpar",
    "Movida",
    "Vamos",
    "Rumo",
    "Hidrovias",
    "Ultrapar",
    "Açu Petróleo",
    "Braskem",
    "Rede D'Or",
    "Minerva",
    "Petrobras",
)

#: O PAR, E NÃO A CONTAGEM — e esta lista existe por um achado de revisão.
#:
#: A primeira versão deste arquivo afirmava quantos papéis cada empresa tem, e
#: isso não basta: trocar `BRASKM50` para Minerva e `BEEFBZ36` para Braskem
#: preserva TODAS as contagens (Braskem 4, Minerva 3), preserva as 15 empresas,
#: os 31 bonds e os 3 da Aegea — e faz o painel mostrar a cotação de um bond sob
#: a empresa errada, sem falha em lugar nenhum.
#:
#: A LISTA SE REPETE AQUI DE PROPÓSITO. A migration confere a si mesma contra a
#: própria fonte (uma tabela temporária lida duas vezes), o que pega o `join`
#: que não casou. O que ela NÃO pode pegar é ter semeado a correspondência
#: errada — para isso é preciso uma segunda declaração, escrita por fora, e é
#: esta. Repetir a lista é o teste; não repetir seria confiar na mesma fonte
#: duas vezes.
TICKER_DA_EMPRESA = {
    "AEGEBZ29": "Aegea",
    "AEGEBZ31": "Aegea",
    "AEGEBZ36": "Aegea",
    "SBSPAB31": "Sabesp",
    "SBSPAB36": "Sabesp",
    "SABESP30": "Sabesp",
    "ELEBRA30": "Eletrobras",
    "ELEBRA35": "Eletrobras",
    "LIGTBZ32": "Light",
    "SIMHBZ31": "Simpar",
    "MOVIBZ29": "Movida",
    "MOVIBZ31": "Movida",
    "MOVIBZ33": "Movida",
    "VAMOBZ31": "Vamos",
    "RAILBZ28": "Rumo",
    "RAILBZ32": "Rumo",
    "HIDRVS31": "Hidrovias",
    "UGPABZ29": "Ultrapar",
    "ACUPET32": "Açu Petróleo",
    "BRASKM28": "Braskem",
    "BRASKM30": "Braskem",
    "BRASKM31": "Braskem",
    "BRASKM50": "Braskem",
    "RDEDOR30": "Rede D'Or",
    "RDEDOR35": "Rede D'Or",
    "RDEDOR36": "Rede D'Or",
    "BEEFBZ31": "Minerva",
    "BEEFBZ33": "Minerva",
    "BEEFBZ36": "Minerva",
    "PETBRA30": "Petrobras",
    "PETBRA36": "Petrobras",
}


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


def test_as_catorze_empresas_pedidas_estao_cadastradas(sessao):
    nomes = set(sessao.scalars(select(Emissor.nome)))

    faltam = [nome for nome in PARES_PEDIDOS if nome not in nomes]
    assert not faltam, f"empresas pedidas que não entraram: {faltam}"


def test_a_aegea_se_distingue_por_coluna_e_e_a_unica(sessao):
    """`e_aegea` é como a tela separa companhia de par.

    E É UMA SÓ: duas linhas marcadas fariam a legenda mostrar dois grupos
    "companhia", e o seletor de pares perderia uma empresa sem avisar.
    """
    da_casa = list(sessao.scalars(select(Emissor.nome).where(Emissor.e_aegea.is_(True))))

    assert da_casa == ["Aegea"]


def test_a_SABESP_une_os_dois_prefixos_de_ticker(sessao):
    """A razão de o cadastro existir.

    `SBSPAB31`, `SBSPAB36` e `SABESP30` são a MESMA empresa. Derivar o emissor
    do prefixo do ticker — a simplificação que este teste existe para impedir —
    criaria duas Sabesp, e a tela ofereceria a mesma companhia duas vezes com
    metade dos papéis em cada.
    """
    tickers = set(
        sessao.scalars(
            select(Bond.ticker).join(Emissor).where(Emissor.nome == "Sabesp")
        )
    )

    assert tickers == {"SBSPAB31", "SBSPAB36", "SABESP30"}
    #: E o controle: os prefixos são de fato dois, senão o teste acima passaria
    #: por motivo errado no dia em que alguém renomeasse os tickers.
    assert len({t[:4] for t in tickers}) == 2


def test_cada_TICKER_esta_sob_a_empresa_certa(sessao):
    """A asserção que a contagem não faz.

    Compara o conjunto inteiro de pares, nos dois sentidos: o que falta diz que
    algum ticker não entrou ou entrou sob outra empresa; o que sobra diz que
    entrou um par que ninguém pediu. Uma troca entre duas empresas aparece nas
    duas listas ao mesmo tempo, e é o caso que a cardinalidade não vê.
    """
    gravado = {
        ticker: nome
        for ticker, nome in sessao.execute(
            select(Bond.ticker, Emissor.nome).join(Emissor)
        )
    }

    errados = {
        ticker: (gravado.get(ticker), empresa)
        for ticker, empresa in TICKER_DA_EMPRESA.items()
        if gravado.get(ticker) != empresa
    }
    assert not errados, f"ticker sob a empresa errada (gravado, pedido): {errados}"

    sobrando = set(gravado) - set(TICKER_DA_EMPRESA)
    assert not sobrando, f"ticker gravado que ninguém pediu: {sorted(sobrando)}"


@pytest.mark.parametrize("empresa", sorted(set(TICKER_DA_EMPRESA.values())))
def test_cada_empresa_tem_os_papeis_medidos(sessao, empresa):
    """A contagem CONTINUA, ao lado da comparação de pares.

    Ela não é redundante: a comparação acima prova a correspondência dos 31
    tickers que esta suíte conhece; a contagem prova que não há um 32º papel
    pendurado numa dessas empresas. São perguntas diferentes.
    """
    esperados = sum(1 for e in TICKER_DA_EMPRESA.values() if e == empresa)
    total = sessao.scalar(
        select(func.count())
        .select_from(Bond)
        .join(Emissor)
        .where(Emissor.nome == empresa)
    )

    assert total == esperados


def test_nenhum_bond_fica_sem_empresa(sessao):
    """O `join` por nome da `0100` falha em SILÊNCIO quando não casa.

    A conferência dentro da migration pega o total errado; isto pega o caso em
    que o total está certo e uma linha ficou órfã — impossível hoje, porque a
    coluna é `not null` com chave estrangeira, e é exatamente o que se quer
    afirmar: que a garantia está no schema e não na boa vontade do `insert`.
    """
    orfaos = sessao.scalar(
        select(func.count())
        .select_from(Bond)
        .outerjoin(Emissor, Emissor.id == Bond.emissor_id)
        .where(Emissor.id.is_(None))
    )

    assert orfaos == 0


def test_os_trinta_e_um_tickers_sao_distintos(sessao):
    """31 tickers, 31 linhas — um ticker repetido sumiria pela chave primária.

    Medido no arquivo de 16/10/2026: 31 pares ticker/empresa. Se a planilha de
    uma semana trouxer um papel novo, este número muda de propósito, e o teste
    é onde a mudança fica registrada.
    """
    total = sessao.scalar(select(func.count()).select_from(Bond))

    assert total == 31
