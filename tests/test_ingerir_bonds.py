"""A conferência e a gravação do export de bonds.

O QUE ESTE ARQUIVO PROTEGE, e é uma coisa só dita de três formas: que a subida
SEMANAL de um arquivo CUMULATIVO não duplique, não perca e não minta sobre o que
fez.

O pedido do dono do produto foi "a cada semana vou subir uma planilha como essa
com dados atualizados (que será um append)". A planilha de hoje traz as 1.750
datas desde 2022; a da semana que vem trará 1.755. Append cego duplicaria ~33
mil cotações por semana, e o gráfico passaria a somar o mesmo pregão várias
vezes. Então é `upsert` — e é isto que os testes abaixo afirmam, inclusive o caso
que importa de verdade: subir O MESMO arquivo duas vezes.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_mercado import Bond, BondCotacao
from app.casos_de_uso import ingerir_bonds
from app.dominio.erros import RegraViolada
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: Dois papéis que a `0100` cadastra, e um que ela não cadastra.
DO_CADASTRO = ("AEGEBZ31", "AEGEBZ36")
FORA_DO_CADASTRO = "NAOEXISTE9"


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


def _planilha(
    tickers: tuple[str, ...],
    dias: dict[date, tuple[object, ...]],
    catalogo: dict[str, tuple[str, str, object]] | None = None,
) -> bytes:
    """Um export BDH sintético, com a mesma forma do arquivo de verdade.

    `dias` mapeia a data para os valores das colunas de série, na ordem
    `(preço do 1º, yield do 1º, preço do 2º, yield do 2º, …)`. `catalogo` mapeia
    o ticker para `(descricao, id_bloomberg, amt_outstanding)`.
    """
    livro = Workbook()
    folha = livro.active
    #: L1: tickers repetidos; L2: Preço/Yield. Coluna G (7ª) é DATES.
    linha1 = ["Bond Description", None, None, "ID", "AMT_OUTSTANDING", None, None]
    linha2 = [None] * 7
    for ticker in tickers:
        linha1 += [ticker, ticker]
        linha2 += ["Preço", "Yield"]
    folha.append(linha1)
    folha.append(linha2)
    folha.append([None] * len(linha1))
    folha.append([None] * len(linha1))
    linha5 = [None] * 6 + ["DATES"] + ["px_last(", "yield("] * len(tickers)
    folha.append(linha5)

    for dia, valores in sorted(dias.items()):
        folha.append([None] * 6 + [dia] + list(valores))

    #: O catálogo mora em `A..E` a partir da linha 2 — por cima das linhas que
    #: já existem, como no arquivo real, onde as duas coisas se sobrepõem.
    if catalogo:
        for posicao, ticker in enumerate(tickers, start=2):
            if ticker not in catalogo:
                continue
            descricao, id_bb, amt = catalogo[ticker]
            folha.cell(row=posicao, column=1, value=descricao)
            folha.cell(row=posicao, column=2, value=id_bb)
            folha.cell(row=posicao, column=3, value=ticker)
            folha.cell(row=posicao, column=4, value=id_bb)
            folha.cell(row=posicao, column=5, value=amt)

    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _quantas(sessao: Session, ticker: str) -> int:
    return sessao.scalar(
        select(func.count()).select_from(BondCotacao).where(BondCotacao.bond_ticker == ticker)
    )


# -- as recusas estruturais ----------------------------------------------------


def test_arquivo_que_nao_e_xlsx_e_recusado_com_a_frase_certa(sessao):
    """`load_workbook` sobre bytes que não são ZIP levanta exceção de
    biblioteca — que vira 500 em vez de dizer à pessoa que ela escolheu o
    arquivo errado."""
    with pytest.raises(RegraViolada, match="não é um .xlsx"):
        ingerir_bonds.conferir(sessao, b"isto nao e um zip")


# -- a conferência -------------------------------------------------------------


def test_a_conferencia_separa_o_que_insere_do_que_atualiza(sessao):
    conteudo = _planilha(
        DO_CADASTRO,
        {
            date(2026, 1, 5): (95.5, 9.1, 80.0, 7.0),
            date(2026, 1, 6): (95.8, 9.0, 80.2, 6.9),
        },
    )

    antes = ingerir_bonds.conferir(sessao, conteudo)
    assert (antes.a_inserir, antes.a_atualizar) == (4, 0)

    ingerir_bonds.gravar(sessao, conteudo)
    depois = ingerir_bonds.conferir(sessao, conteudo)

    assert (depois.a_inserir, depois.a_atualizar) == (0, 4), (
        "o mesmo arquivo conferido de novo tem de aparecer inteiro como atualização"
    )


def test_a_conferencia_mostra_o_ticker_que_o_cadastro_nao_tem(sessao):
    """Papel novo emitido chega na planilha antes de alguém cadastrá-lo.

    `cotacoes_no_arquivo` conta TODAS as linhas lidas; `a_inserir` conta só as
    dos papéis cadastrados. A diferença é o que a tela precisa mostrar, e por
    isso os dois números vão separados em vez de um total.
    """
    conteudo = _planilha(
        (DO_CADASTRO[0], FORA_DO_CADASTRO),
        {date(2026, 1, 5): (95.5, 9.1, 50.0, 12.0)},
    )

    conferencia = ingerir_bonds.conferir(sessao, conteudo)

    assert conferencia.tickers_desconhecidos == [FORA_DO_CADASTRO]
    assert conferencia.cotacoes_no_arquivo == 2
    assert conferencia.a_inserir == 1
    assert conferencia.por_ticker == {DO_CADASTRO[0]: 1}


def test_a_conferencia_nao_escreve_nada(sessao):
    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 80.0, 7.0)})

    ingerir_bonds.conferir(sessao, conteudo)

    assert _quantas(sessao, DO_CADASTRO[0]) == 0


def test_a_conferencia_devolve_o_periodo(sessao):
    conteudo = _planilha(
        DO_CADASTRO,
        {
            date(2026, 1, 5): (95.5, 9.1, 0, 0),
            date(2026, 3, 2): (96.0, 9.0, 0, 0),
        },
    )

    conferencia = ingerir_bonds.conferir(sessao, conteudo)

    assert (conferencia.primeira_data, conferencia.ultima_data) == (
        date(2026, 1, 5),
        date(2026, 3, 2),
    )


# -- a gravação ----------------------------------------------------------------


def test_subir_o_MESMO_arquivo_duas_vezes_nao_duplica(sessao):
    """O teste que o pedido pede.

    A planilha é cumulativa, e quem sobe toda semana não lembra se já subiu.
    Sem a chave `(bond_ticker, data)` da `0100`, a segunda subida dobraria a
    série e o gráfico somaria o mesmo pregão duas vezes.
    """
    conteudo = _planilha(
        DO_CADASTRO,
        {
            date(2026, 1, 5): (95.5, 9.1, 80.0, 7.0),
            date(2026, 1, 6): (95.8, 9.0, 80.2, 6.9),
        },
    )

    primeira = ingerir_bonds.gravar(sessao, conteudo)
    segunda = ingerir_bonds.gravar(sessao, conteudo)

    assert (primeira.inseridas, primeira.atualizadas) == (4, 0)
    assert (segunda.inseridas, segunda.atualizadas) == (0, 4)
    assert _quantas(sessao, DO_CADASTRO[0]) == 2


def test_a_semana_seguinte_ACRESCENTA_sem_mexer_no_passado(sessao):
    """O que a rotina semanal faz de verdade: o arquivo cresce pela ponta."""
    semana1 = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    semana2 = _planilha(
        DO_CADASTRO,
        {
            date(2026, 1, 5): (95.5, 9.1, 0, 0),
            date(2026, 1, 12): (96.4, 8.8, 0, 0),
        },
    )

    ingerir_bonds.gravar(sessao, semana1)
    resultado = ingerir_bonds.gravar(sessao, semana2)

    assert (resultado.inseridas, resultado.atualizadas) == (1, 1)
    assert _quantas(sessao, DO_CADASTRO[0]) == 2


def test_o_valor_CORRIGIDO_na_origem_sobrescreve(sessao):
    """O outro lado do upsert: o Bloomberg revisa cotação.

    Se a subida apenas ignorasse a chave existente, uma correção na origem nunca
    chegaria ao gráfico — e a série ficaria errada para sempre, em silêncio.
    """
    original = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    corrigido = _planilha(DO_CADASTRO, {date(2026, 1, 5): (97.0, 8.5, 0, 0)})

    ingerir_bonds.gravar(sessao, original)
    ingerir_bonds.gravar(sessao, corrigido)

    linha = sessao.get(BondCotacao, (DO_CADASTRO[0], date(2026, 1, 5)))
    assert linha.preco_pct_par == Decimal("97.0000")
    assert linha.yield_pct == Decimal("8.5000")


def test_o_ticker_desconhecido_NAO_entra(sessao):
    """A doutrina do cadastro: o upload não inventa taxonomia."""
    conteudo = _planilha(
        (DO_CADASTRO[0], FORA_DO_CADASTRO),
        {date(2026, 1, 5): (95.5, 9.1, 50.0, 12.0)},
    )

    resultado = ingerir_bonds.gravar(sessao, conteudo)

    assert resultado.inseridas == 1
    assert _quantas(sessao, FORA_DO_CADASTRO) == 0
    assert sessao.get(Bond, FORA_DO_CADASTRO) is None


def test_o_ZERO_da_planilha_nao_vira_cotacao(sessao):
    """A regra do leitor, provada do outro lado: no banco."""
    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (0, 0, 80.0, 7.0)})

    ingerir_bonds.gravar(sessao, conteudo)

    assert _quantas(sessao, DO_CADASTRO[0]) == 0
    assert _quantas(sessao, DO_CADASTRO[1]) == 1


# -- o catálogo ----------------------------------------------------------------


def test_a_subida_completa_os_TRES_campos_do_catalogo(sessao):
    """A `0100` semeia a correspondência; a planilha traz o resto.

    OS TRÊS DE UMA VEZ, e este teste existe por um defeito que eu escrevi: a
    primeira versão tinha um `continue` depois de cada atribuição, e com
    descrição E montante alterados só a descrição entrava — a outra metade
    ficaria para a subida seguinte, e ninguém notaria a defasagem.
    """
    conteudo = _planilha(
        (DO_CADASTRO[0],),
        {date(2026, 1, 5): (95.5, 9.1)},
        catalogo={DO_CADASTRO[0]: ("AEGEBZ 9 01/20/31", "ZH164262 Corp", 800000000)},
    )

    resultado = ingerir_bonds.gravar(sessao, conteudo)
    sessao.flush()
    papel = sessao.get(Bond, DO_CADASTRO[0])

    assert resultado.papeis_completados == 1
    assert papel.descricao == "AEGEBZ 9 01/20/31"
    assert papel.id_bloomberg == "ZH164262 Corp"
    assert papel.amt_outstanding == Decimal("800000000.00")


def test_campo_vazio_na_planilha_NAO_apaga_o_que_ja_esta_no_cadastro(sessao):
    """A planilha é a fonte do que ela informa, não do que ela omite."""
    completo = _planilha(
        (DO_CADASTRO[0],),
        {date(2026, 1, 5): (95.5, 9.1)},
        catalogo={DO_CADASTRO[0]: ("AEGEBZ 9 01/20/31", "ZH164262 Corp", 800000000)},
    )
    ingerir_bonds.gravar(sessao, completo)
    sessao.flush()

    sem_catalogo = _planilha((DO_CADASTRO[0],), {date(2026, 1, 12): (96.0, 9.0)})
    ingerir_bonds.gravar(sessao, sem_catalogo)
    sessao.flush()

    papel = sessao.get(Bond, DO_CADASTRO[0])
    assert papel.descricao == "AEGEBZ 9 01/20/31"
    assert papel.amt_outstanding == Decimal("800000000.00")


def test_catalogo_igual_nao_conta_como_alteracao(sessao):
    """`numeric(18,2)` devolve `800000000.00` para o `800000000` da planilha.

    Comparar representação em vez de valor contaria essa ida e volta como
    mudança em TODA subida, para sempre — e o relatório da importação diria que
    31 papéis foram alterados toda semana, sem nada ter mudado.
    """
    conteudo = _planilha(
        (DO_CADASTRO[0],),
        {date(2026, 1, 5): (95.5, 9.1)},
        catalogo={DO_CADASTRO[0]: ("AEGEBZ 9 01/20/31", "ZH164262 Corp", 800000000)},
    )

    ingerir_bonds.gravar(sessao, conteudo)
    sessao.flush()
    segunda = ingerir_bonds.gravar(sessao, conteudo)

    assert segunda.papeis_completados == 0


# -- os achados da revisão do Codex --------------------------------------------


def test_zip_INVALIDO_que_comeca_com_a_assinatura_nao_vira_500():
    """`PK\\x03\\x04` seguido de lixo passa pela assinatura e explode no parser.

    Sem o tratamento, um `.xlsx` truncado — uma subida interrompida, por
    exemplo — vira 500 em vez de dizer à pessoa que o arquivo chegou incompleto.
    O teste antigo só cobria bytes que NÃO começam com a assinatura, então este
    caminho passava sem rede.
    """
    from app.casos_de_uso.ingerir_bonds import ler_arquivo

    with pytest.raises(RegraViolada, match="não abre"):
        ler_arquivo(b"PK\x03\x04" + b"\x00" * 200)


def test_a_planilha_grande_demais_para_a_MEMORIA_e_recusada(monkeypatch):
    """O limite de BYTES não protege a memória.

    `TAMANHO_MAXIMO` são 80 MB de ZIP COMPRIMIDO, e um `.xlsx` de poucos MB pode
    trazer milhões de células — `list(iter_rows())` materializa todas. Com o
    orçamento rebaixado a zero, qualquer planilha estimável tem de ser recusada
    com a frase certa, e não morrer sem frase nenhuma.
    """
    from app.casos_de_uso import ingerir_bonds as modulo

    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    monkeypatch.setattr(modulo, "orcamento_de_leitura", lambda: 1)

    with pytest.raises(RegraViolada, match="grande demais para a memória"):
        modulo.ler_arquivo(conteudo)


def test_a_planilha_normal_PASSA_pelo_orcamento():
    """O controle negativo do teste acima: o orçamento real não barra o arquivo
    de verdade. Sem isto, um coeficiente errado recusaria toda subida."""
    from app.casos_de_uso.ingerir_bonds import ler_arquivo

    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})

    assert ler_arquivo(conteudo).cotacoes


def test_o_ticker_desconhecido_com_TUDO_ZERO_ainda_e_reportado(sessao):
    """O achado: a lista vinha das cotações, e papel sem cotação desaparecia.

    O ticker que o arquivo menciona, o cadastro não conhece, e cujos valores são
    todos zero está sendo DESCARTADO — e a tela dizia "nada a reportar" sobre
    ele. É justamente esse papel que pede uma linha em `bond`.
    """
    conteudo = _planilha(
        (DO_CADASTRO[0], FORA_DO_CADASTRO),
        {date(2026, 1, 5): (95.5, 9.1, 0, 0)},
    )

    conferencia = ingerir_bonds.conferir(sessao, conteudo)

    assert FORA_DO_CADASTRO in conferencia.tickers_desconhecidos
    assert conferencia.por_ticker == {DO_CADASTRO[0]: 1}


def test_o_ticker_desconhecido_SO_NO_CATALOGO_tambem_e_reportado(sessao):
    """A outra metade: ele aparece em `A..E` e não tem coluna de série."""
    conteudo = _planilha(
        (DO_CADASTRO[0],),
        {date(2026, 1, 5): (95.5, 9.1)},
        catalogo={DO_CADASTRO[0]: ("AEGEBZ 9 01/20/31", "ZH164262 Corp", 800000000)},
    )
    #: Põe o desconhecido numa linha do catálogo, sem coluna de série.
    from openpyxl import load_workbook

    pasta = load_workbook(io.BytesIO(conteudo))
    folha = pasta[pasta.sheetnames[0]]
    folha.cell(row=3, column=3, value=FORA_DO_CADASTRO)
    folha.cell(row=3, column=1, value="Papel novo")
    memoria = io.BytesIO()
    pasta.save(memoria)

    conferencia = ingerir_bonds.conferir(sessao, memoria.getvalue())

    assert FORA_DO_CADASTRO in conferencia.tickers_desconhecidos


def test_ticker_REPETIDO_no_catalogo_conta_o_papel_uma_vez(sessao):
    """`papeis_completados` diria 32 num cadastro de 31.

    A primeira linha vence, como no par repetido do leitor — a escolha importa
    menos que o número do relatório não mentir.
    """
    conteudo = _planilha(
        (DO_CADASTRO[0],),
        {date(2026, 1, 5): (95.5, 9.1)},
        catalogo={DO_CADASTRO[0]: ("AEGEBZ 9 01/20/31", "ZH164262 Corp", 800000000)},
    )
    from openpyxl import load_workbook

    pasta = load_workbook(io.BytesIO(conteudo))
    folha = pasta[pasta.sheetnames[0]]
    #: A MESMA linha de catálogo, de novo, com outro valor.
    folha.cell(row=3, column=1, value="Outra descricao")
    folha.cell(row=3, column=2, value="OUTRO Corp")
    folha.cell(row=3, column=3, value=DO_CADASTRO[0])
    folha.cell(row=3, column=4, value="OUTRO Corp")
    folha.cell(row=3, column=5, value=999)
    memoria = io.BytesIO()
    pasta.save(memoria)

    resultado = ingerir_bonds.gravar(sessao, memoria.getvalue())
    sessao.flush()

    assert resultado.papeis_completados == 1
    #: E venceu a PRIMEIRA linha.
    assert sessao.get(Bond, DO_CADASTRO[0]).descricao == "AEGEBZ 9 01/20/31"