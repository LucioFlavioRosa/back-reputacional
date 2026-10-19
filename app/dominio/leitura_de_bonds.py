"""Ler o export BDH do Bloomberg: catálogo de papéis e cotação diária.

DOMÍNIO PURO, como `importacao_de_agendas`: nada aqui toca banco nem
`openpyxl`. Entra uma sequência de linhas (tuplas de células, como
`iter_rows(values_only=True)` devolve) e sai o que foi lido. É isso que permite
testar as regras abaixo sem escrever um `.xlsx` de verdade — e as regras são a
parte que, errada, grava dado errado em silêncio.

O FORMATO NÃO É UMA TABELA, é um relatório. O arquivo
`BASE DE DADOS_HISTORICO BONDS_Yieldv1.xlsx` (medido em 16/10/2026) tem DUAS
coisas na mesma folha:

    A        B              C          D              E
    L1  Bond Description  <de>        <ate>      ID          AMT_OUTSTANDING
    L2  AEGEBZ 6 ¾ …      BW191153…   AEGEBZ29   BW191153…   250001000
    L3  AEGEBZ 9 01/20/31 ZH164262…   AEGEBZ31   ZH164262…   800000000
    …   (31 linhas de catálogo)

                                 G          H        I        J        K
    L1  (cabeçalho de cima)                 AEGEBZ29 AEGEBZ29 AEGEBZ31 AEGEBZ31
    L2                                      Preço    Yield    Preço    Yield
    L4                                      BW191…   BW191…   ZH164…   ZH164…
    L5                           DATES      px_last( yield(   px_last( yield(
    L6                           2022-01-01 0        0        0        0
    …                            (1.750 datas de CALENDÁRIO)

As duas se sobrepõem nas linhas: o catálogo ocupa `A..E` das linhas 2 a 32, e a
série ocupa `G..` das linhas 6 em diante. Ler os dois da mesma passada é o que
evita decodificar o arquivo duas vezes — a lição que `contagens_da_planilha`
pagou no leitor das menções.

TRÊS REGRAS QUE DECIDEM SE O DADO ENTRA CERTO:

1. **`0` NÃO É PREÇO ZERO, É "SEM COTAÇÃO".** As datas são de CALENDÁRIO, então
   todo sábado, domingo e feriado vem `0`; e todo dia anterior à emissão do
   papel também. Medido: o `AEGEBZ36` só passa a ter valor em 25/09/2025, e as
   1.363 datas antes disso são `0`. Gravar o zero desenharia um precipício de 0
   para 95 no gráfico — e pior, a média e a variação do período passariam a
   incluir dias que não existiram. Zero vira `None`, e a linha abre um vão.

2. **A COLUNA DAS DATAS SE PROCURA, não se conta.** A posição é a `G` hoje, e um
   índice fixo faria o leitor gravar yield na coluna de preço no dia em que
   alguém acrescentar uma coluna à esquerda. Ela é a célula da linha 5 que diz
   `DATES`, e os pares começam depois dela.

3. **PAR SEM VALOR NENHUM É REPORTADO, NÃO GRAVADO.** O `AEGEBZ29` — o papel que
   o mockup da tela mostra — tem ZERO valores no arquivo. Gravar 1.750 nulos
   para ele faria a tela oferecer uma série vazia na legenda, que se lê como
   defeito. Ele sai em `tickers_sem_valor`, para a conferência mostrar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.dominio.texto import normalizar

#: Onde o catálogo de papéis mora, em índices de coluna (base 0).
_CATALOGO_DESCRICAO = 0
_CATALOGO_ID_BLOOMBERG = 1
_CATALOGO_TICKER = 2
_CATALOGO_AMT = 4

#: A primeira linha do catálogo (a `L2`, logo abaixo do cabeçalho).
_PRIMEIRA_LINHA_DO_CATALOGO = 1

#: A linha onde mora a palavra `DATES` e as fórmulas BDH (a `L5`).
_LINHA_DAS_FORMULAS = 4

#: A primeira linha com data (a `L6`).
_PRIMEIRA_LINHA_DE_DADO = 5

_PRECO = "preco"
_YIELD = "yield"


@dataclass(frozen=True)
class PapelLido:
    """Uma linha do catálogo: o que o arquivo diz sobre o papel."""

    ticker: str
    descricao: str | None
    id_bloomberg: str | None
    amt_outstanding: Decimal | None


@dataclass(frozen=True)
class CotacaoLida:
    """O fechamento de um papel num dia. Nulo é "não houve pregão"."""

    ticker: str
    data: date
    preco_pct_par: Decimal | None
    yield_pct: Decimal | None


@dataclass
class Leitura:
    """O que a planilha trouxe, e o que ela deixou de trazer.

    `tickers_sem_valor` e `tickers_fora_do_catalogo` existem para a conferência
    poder mostrar ANTES de gravar. Um leitor que só devolvesse as cotações
    obrigaria a tela a inferir o que faltou pela ausência — e ausência não se vê.
    """

    papeis: list[PapelLido] = field(default_factory=list)
    cotacoes: list[CotacaoLida] = field(default_factory=list)
    #: Par ticker/tipo que o cabeçalho declara e que não tem UM valor sequer.
    tickers_sem_valor: list[str] = field(default_factory=list)
    #: Coluna de série cujo ticker não aparece no catálogo `A..E` do arquivo.
    tickers_fora_do_catalogo: list[str] = field(default_factory=list)
    primeira_data: date | None = None
    ultima_data: date | None = None


def _achatar(valor: object) -> str:
    """`Preço` → `preco`, para reconhecer o rótulo da coluna.

    DELEGA A `dominio/texto.normalizar`, e isto foi a guarda do projeto me
    pegando: eu havia escrito as três linhas de `unicodedata` aqui, e
    `test_nenhuma_normalizacao_nova_fora_do_dominio_do_texto` falhou com a frase
    certa — "foi uma regra duplicada em silêncio que criou duplicata de
    cadastro". É a mesma lição que a `0097` pagou reimplementando `normalizar`
    em SQL e divergindo em 67 de 87 valores.
    """
    if valor is None:
        return ""
    return normalizar(str(valor))


def _texto(valor: object) -> str | None:
    if valor is None:
        return None
    limpo = str(valor).strip()
    return limpo or None


def _data(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _numero(valor: object) -> Decimal | None:
    """O valor da célula, com `0` virando nulo — ver a regra 1 do módulo.

    `0` E NÃO "FALSY": `Decimal("0.0")` é zero e tem de virar nulo, e a string
    vazia já cai no `None` de cima. Comparar com zero depois de converter é o
    que torna as duas pontas iguais.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, str):
        limpo = valor.strip().replace(",", ".")
        if not limpo:
            return None
        try:
            numero = Decimal(limpo)
        except InvalidOperation:
            return None
    elif isinstance(valor, (int, float, Decimal)):
        try:
            numero = Decimal(str(valor))
        except InvalidOperation:
            return None
    else:
        return None
    return None if numero == 0 else numero


def _coluna_das_datas(linha_das_formulas: Sequence[object]) -> int | None:
    """Onde está `DATES` — ver a regra 2 do módulo."""
    for indice, celula in enumerate(linha_das_formulas):
        if _achatar(celula) == "dates":
            return indice
    return None


def _pares(
    tickers: Sequence[object], tipos: Sequence[object], primeira_coluna: int
) -> list[tuple[int, str, str]]:
    """As colunas de série, como `(índice, ticker, 'preco' | 'yield')`.

    IGNORA O QUE NÃO RECONHECE em vez de falhar: uma coluna de nota que alguém
    acrescente à direita não deve impedir a subida de 54 mil cotações. O que
    importa é que nenhuma coluna reconhecida seja lida como outra coisa, e isso
    o par (ticker, tipo) garante.
    """
    encontrados: list[tuple[int, str, str]] = []
    for indice in range(primeira_coluna, len(tickers)):
        ticker = _texto(tickers[indice])
        tipo = _achatar(tipos[indice]) if indice < len(tipos) else ""
        if not ticker:
            continue
        if tipo.startswith(_PRECO) or tipo.startswith("price"):
            encontrados.append((indice, ticker, _PRECO))
        elif tipo.startswith(_YIELD):
            encontrados.append((indice, ticker, _YIELD))
    return encontrados


def _catalogo(linhas: Sequence[Sequence[object]]) -> list[PapelLido]:
    """O catálogo `A..E`, que acaba na primeira linha sem ticker."""
    papeis: list[PapelLido] = []
    for linha in linhas[_PRIMEIRA_LINHA_DO_CATALOGO:]:
        ticker = _texto(linha[_CATALOGO_TICKER]) if len(linha) > _CATALOGO_TICKER else None
        if not ticker:
            break
        papeis.append(
            PapelLido(
                ticker=ticker,
                descricao=_texto(linha[_CATALOGO_DESCRICAO]),
                id_bloomberg=_texto(linha[_CATALOGO_ID_BLOOMBERG]),
                #: O montante NÃO passa pelo `_numero`: zero aqui seria um
                #: montante de zero, não "sem cotação", e a regra do zero é da
                #: série — não do catálogo.
                amt_outstanding=_montante(
                    linha[_CATALOGO_AMT] if len(linha) > _CATALOGO_AMT else None
                ),
            )
        )
    return papeis


def _montante(valor: object) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def ler(linhas: Sequence[Sequence[object]]) -> Leitura:
    """A planilha inteira, numa passada.

    DEVOLVE VAZIO em vez de levantar quando o arquivo não tem a forma esperada:
    quem chama (a conferência) transforma isso em mensagem para a pessoa, e uma
    exceção aqui viraria 500 numa tela de upload — que é o oposto de dizer o que
    está errado com o arquivo.
    """
    if len(linhas) <= _PRIMEIRA_LINHA_DO_CATALOGO:
        return Leitura()

    #: O CATÁLOGO VEM PRIMEIRO E SEMPRE, e isto foi um teste me pegando: a saída
    #: antecipada por "arquivo curto" devolvia `Leitura()` vazia e perdia o
    #: catálogo, enquanto o ramo sem `DATES` logo abaixo o devolvia. Duas saídas
    #: discordando sobre a mesma pergunta — e a conferência de um arquivo com
    #: cabeçalho e sem série diria "nenhum papel", que é falso. O catálogo
    #: precisa de DUAS linhas; a série precisa de seis.
    papeis = _catalogo(linhas)
    if len(linhas) <= _PRIMEIRA_LINHA_DE_DADO:
        return Leitura(papeis=papeis)

    coluna_das_datas = _coluna_das_datas(linhas[_LINHA_DAS_FORMULAS])
    if coluna_das_datas is None:
        return Leitura(papeis=papeis)

    pares = _pares(linhas[0], linhas[1], coluna_das_datas + 1)
    no_catalogo = {papel.ticker for papel in papeis}

    #: ACUMULA POR (ticker, data) porque preço e yield são DUAS colunas e viram
    #: UMA linha. Um `dict` em vez de duas listas para juntar: a alternativa
    #: — gravar preço e depois atualizar com o yield — faria a ingestão escrever
    #: duas vezes cada dia de cada papel.
    por_chave: dict[tuple[str, date], dict[str, Decimal | None]] = {}
    com_valor: set[str] = set()
    primeira: date | None = None
    ultima: date | None = None

    for linha in linhas[_PRIMEIRA_LINHA_DE_DADO:]:
        if len(linha) <= coluna_das_datas:
            continue
        dia = _data(linha[coluna_das_datas])
        #: LINHA SEM DATA ENCERRA A LEITURA. O arquivo medido declara 54.254
        #: linhas e só 1.750 têm data: o resto é rodapé fantasma do Excel.
        #: Continuar varrendo custaria 52 mil iterações para nada — e, pior,
        #: uma data perdida no fim seria lida como série válida.
        if dia is None:
            break
        primeira = dia if primeira is None or dia < primeira else primeira
        ultima = dia if ultima is None or dia > ultima else ultima
        for indice, ticker, tipo in pares:
            if indice >= len(linha):
                continue
            valor = _numero(linha[indice])
            if valor is None:
                continue
            com_valor.add(ticker)
            por_chave.setdefault((ticker, dia), {})[tipo] = valor

    cotacoes = [
        CotacaoLida(
            ticker=ticker,
            data=dia,
            preco_pct_par=valores.get(_PRECO),
            yield_pct=valores.get(_YIELD),
        )
        for (ticker, dia), valores in sorted(por_chave.items())
    ]

    declarados = sorted({ticker for _, ticker, _ in pares})
    return Leitura(
        papeis=papeis,
        cotacoes=cotacoes,
        tickers_sem_valor=[t for t in declarados if t not in com_valor],
        tickers_fora_do_catalogo=[t for t in declarados if t not in no_catalogo],
        primeira_data=primeira,
        ultima_data=ultima,
    )
