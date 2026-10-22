"""Conferir e gravar o export BDH de bonds.

A DIVISÃO COM `dominio/leitura_de_bonds`: lá moram as REGRAS do formato (o zero
que é ausência, a coluna que se procura, o par que se reporta) e nada toca banco
nem `openpyxl`. Aqui mora a PLUMBING: abrir o arquivo, falar com o cadastro,
gravar. É a mesma divisão de `ingerir_mencoes` com `dominio/ingestao_score`.

CONFERIR ANTES DE GRAVAR, e a razão está escrita na importação de agendas:
"importação de planilha sem conferência humana cria duplicata de instituição em
massa, e desfazer isso depois é pior que digitar de novo". Aqui o risco é outro e
igualmente caro — uma planilha errada substitui a série que o gráfico desenha —,
e a resposta é a mesma: a conta aparece primeiro.

A SUBIDA SEMANAL É UM `upsert`, NÃO UM `append`. O pedido falou em append, mas o
arquivo é CUMULATIVO: o de hoje traz as 1.750 datas desde 2022, e o da semana que
vem trará 1.755. Append cego duplicaria ~33 mil cotações por semana e o gráfico
passaria a somar o mesmo pregão várias vezes. A chave `(bond_ticker, data)` da
`0100` é o que torna isto seguro, e `on conflict do update` é o que torna subir
o mesmo arquivo duas vezes inofensivo.

O TICKER DESCONHECIDO NÃO ENTRA, e aparece na conferência. É a doutrina do
cadastro de assuntos (`temas_da_mencao`): o cadastro é a autoridade, o upload
não inventa taxonomia. Bond novo emitido pede uma linha em `bond` — decisão de
quem acompanha o mercado, não efeito colateral de um arquivo.

NÃO HÁ SUBIDA EM PARTES AQUI, e é medição, não esquecimento: o arquivo tem 1,05
MB e o limite do front para fatiar é 1,2 MB, então ele já sobe de uma vez hoje.
Ele cresce ~3 KB por semana (cinco pregões × 31 tickers), o que põe a travessia
do limite a anos de distância. Generalizar a montagem por partes de
`planilha_do_score` — que é por fonte do Score — para outro domínio é bloco
próprio, e seria código sem usuário agora.
"""

from __future__ import annotations

import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from zipfile import BadZipFile

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.banco.tabelas_mercado import Bond, BondCotacao
from app.casos_de_uso.ingerir_mencoes import (
    ASSINATURA_ZIP,
    TAMANHO_MAXIMO,
    custo_da_leitura,
    orcamento_de_leitura,
)
from app.casos_de_uso.leitor_de_planilha import celulas_pelo_calamine, sem_erro_do_excel
from app.dominio.erros import RegraViolada
from app.dominio.leitura_de_bonds import Leitura, ler

#: Quantas cotações vão ao banco por vez. 33 mil numa instrução só monta um
#: `insert` gigante e segura a transação; lotes pequenos pagam ida e volta sem
#: necessidade. Mil é o mesmo tamanho que `ligar_mencoes_a_concessionaria` usa.
TAMANHO_DO_LOTE = 1_000


@dataclass
class Conferencia:
    """O que a subida FARIA, para a tela mostrar antes de gravar."""

    primeira_data: date | None = None
    ultima_data: date | None = None
    #: Quantas cotações o arquivo traz, e como elas caem no banco.
    cotacoes_no_arquivo: int = 0
    a_inserir: int = 0
    a_atualizar: int = 0
    #: Papéis do cadastro que o arquivo alimenta, com quantas cotações cada um.
    por_ticker: dict[str, int] = field(default_factory=dict)
    #: O QUE NÃO VAI ENTRAR, e por quê — cada lista é uma frase diferente na
    #: tela, e juntá-las numa só esconderia qual decisão cada caso pede.
    tickers_desconhecidos: list[str] = field(default_factory=list)
    tickers_sem_valor: list[str] = field(default_factory=list)
    rotulos_ignorados: list[tuple[str, str]] = field(default_factory=list)
    pares_repetidos: list[tuple[str, str]] = field(default_factory=list)
    linha_que_encerrou: int | None = None


@dataclass
class Resultado:
    """O que a subida FEZ."""

    inseridas: int = 0
    atualizadas: int = 0
    papeis_completados: int = 0


def ler_arquivo(conteudo: bytes) -> Leitura:
    """Os bytes viram `Leitura`. As duas recusas estruturais moram aqui.

    TAMANHO E ASSINATURA ANTES DE ABRIR, com as mesmas constantes do leitor de
    menções: um `.xlsx` é um ZIP, e `load_workbook` sobre bytes que não são ZIP
    levanta exceção de biblioteca — que vira 500 em vez de dizer à pessoa que
    ela escolheu o arquivo errado.

    MATERIALIZA AS LINHAS numa lista de propósito. `ler` recebe `Sequence` (usa
    `len`), e passar o gerador de `iter_rows` falharia — uma revisão apontou
    essa armadilha. A lista é o formato que o domínio puro aceita, e é também o
    que permite ao leitor olhar as cinco primeiras linhas de cabeçalho antes de
    percorrer a série.

    O MESMO MECANISMO DAS LENTES desde 22/10/2026: calamine primeiro, openpyxl
    de reserva, pelo `leitor_de_planilha`. Antes esta tela abria o arquivo pelo
    openpyxl direto — a plataforma tinha cinco leitores e três comportamentos, e
    o mesmo arquivo era lido de um jeito aqui e de outro na tela ao lado.
    """
    if len(conteudo) > TAMANHO_MAXIMO:
        raise RegraViolada("A planilha de bonds passa do tamanho que se aceita ler.")
    if not conteudo.startswith(ASSINATURA_ZIP):
        raise RegraViolada("O arquivo não é um .xlsx — os primeiros bytes não são de ZIP.")

    #: A MEMÓRIA É MEDIDA ANTES DE QUALQUER LEITOR, e isto voltou atrás numa
    #: decisão minha. Eu havia movido esta guarda para dentro do leitor de
    #: reserva, com o argumento de que o calamine "não produz preenchimento" —
    #: e esse argumento é falso: ele ignora a dimensão DECLARADA, mas
    #: materializa o retângulo da área usada. Um `.xlsx` de 4,7 KB com `A1=1` e
    #: `BR54254=2` custa 63,8 MB pelo caminho rápido, medido. Deixar o caminho
    #: rápido sem guarda era trocar uma recusa indevida por um processo morto.
    #:
    #: O QUE CONSERTOU O DEFEITO DO Q&A NÃO FOI TIRAR A GUARDA, foi corrigir o
    #: PREÇO da célula vazia (`MEMORIA_POR_CELULA_VAZIA`): com ele, o arquivo
    #: dele estima 104 MB contra 204 de orçamento e passa. A guarda podia ter
    #: ficado onde estava desde o começo.
    custo = custo_da_leitura(conteudo)
    orcamento = orcamento_de_leitura()
    if custo is not None and custo > orcamento:
        raise RegraViolada(
            "A planilha de bonds é grande demais para a memória deste ambiente: "
            f"a leitura pediria ~{custo // (1024 * 1024)} MB e o orçamento é de "
            f"~{orcamento // (1024 * 1024)} MB."
        )

    try:
        linhas = celulas_pelo_calamine(conteudo)
    except RegraViolada:
        #: RECUSA DE CADASTRO passa direto: arquivo vazio é recado à pessoa, não
        #: falha de leitor, e tentar o outro daria a mesma resposta.
        raise
    except Exception:
        #: QUALQUER OUTRA FALHA DO CALAMINE cai no openpyxl, que leu estes
        #: arquivos desde que a tela existe. Um leitor novo pode recusar um
        #: `.xlsx` estranho que o antigo aceitava, e a subida não pode morrer
        #: por causa de uma otimização.
        linhas = _pelo_leitor_de_reserva(conteudo)

    return ler(linhas)


def _pelo_leitor_de_reserva(conteudo: bytes) -> list[tuple]:
    """O openpyxl, para quando o calamine recusa o arquivo.

    A MEMÓRIA JÁ FOI MEDIDA em `ler_arquivo`, antes dos dois leitores — ver a
    nota lá sobre por que ela não pode valer só aqui.

    NORMALIZA AS CÉLULAS como o leitor rápido normaliza, e isto é achado de
    revisão: sem isso, um `#N/A` no catálogo some pelo caminho rápido (o
    calamine entrega vazio) e vira um papel de ticker "#N/A" pelo de reserva.
    Dois caminhos que discordam sobre o mesmo arquivo é pior que qualquer um
    dos dois sozinho.
    """
    try:
        pasta = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except (BadZipFile, KeyError, ValueError) as erro:
        #: `PK\x03\x04` SEGUIDO DE LIXO passa pela assinatura e explode no
        #: parser — outro achado de revisão. Sem isto, um `.xlsx` truncado (uma
        #: subida interrompida, por exemplo) vira 500 em vez de dizer à pessoa
        #: que o arquivo chegou corrompido.
        raise RegraViolada(
            "O arquivo começa como um .xlsx mas não abre — pode ter chegado "
            "incompleto. Tente subir de novo."
        ) from erro
    try:
        if not pasta.sheetnames:
            raise RegraViolada("A planilha não tem nenhuma aba.")
        #: A PRIMEIRA ABA, sem exigir nome: o export vem com o nome que o
        #: analista deu à folha ("Planilha2 (2)" no arquivo medido), e exigir um
        #: nome recusaria o arquivo certo por um detalhe que ninguém controla.
        folha = pasta[pasta.sheetnames[0]]
        return [sem_erro_do_excel(linha) for linha in folha.iter_rows(values_only=True)]
    finally:
        pasta.close()


def conferir(sessao: Session, conteudo: bytes) -> Conferencia:
    """Lê o arquivo e diz o que a subida faria. NÃO escreve nada."""
    leitura = ler_arquivo(conteudo)
    cadastrados = set(sessao.scalars(select(Bond.ticker)))

    conhecidas = [c for c in leitura.cotacoes if c.ticker in cadastrados]
    #: DOS DECLARADOS E DO CATÁLOGO DO ARQUIVO, e não das cotações — achado de
    #: revisão. Derivando das cotações, o ticker desconhecido cujos valores são
    #: todos zero (ou cujos dois rótulos foram ignorados) não produzia cotação
    #: nenhuma e DESAPARECIA desta lista, embora esteja sendo descartado. A tela
    #: diria "nada a reportar" sobre um papel que o arquivo menciona e o
    #: cadastro não conhece — e é esse papel que pede uma linha em `bond`.
    mencionados = set(leitura.tickers_declarados) | {p.ticker for p in leitura.papeis}
    desconhecidos = sorted(mencionados - cadastrados)

    #: AS QUE JÁ EXISTEM, em UMA consulta. Perguntar por cotação seriam 33 mil
    #: idas ao banco numa tela de conferência; o conjunto de chaves do período
    #: cabe em memória e responde a mesma pergunta.
    ja_no_banco = set(
        sessao.execute(
            select(BondCotacao.bond_ticker, BondCotacao.data).where(
                BondCotacao.bond_ticker.in_({c.ticker for c in conhecidas} or {""})
            )
        ).all()
    )
    atualizar = sum(1 for c in conhecidas if (c.ticker, c.data) in ja_no_banco)

    return Conferencia(
        primeira_data=leitura.primeira_data,
        ultima_data=leitura.ultima_data,
        cotacoes_no_arquivo=len(leitura.cotacoes),
        a_inserir=len(conhecidas) - atualizar,
        a_atualizar=atualizar,
        por_ticker=dict(sorted(Counter(c.ticker for c in conhecidas).items())),
        tickers_desconhecidos=desconhecidos,
        tickers_sem_valor=list(leitura.tickers_sem_valor),
        rotulos_ignorados=list(leitura.rotulos_ignorados),
        pares_repetidos=list(leitura.pares_repetidos),
        linha_que_encerrou=leitura.linha_que_encerrou,
    )


def gravar(sessao: Session, conteudo: bytes) -> Resultado:
    """Grava as cotações dos papéis cadastrados, por `upsert`.

    DEVOLVE INSERIDAS E ATUALIZADAS SEPARADAS, e isso custa uma leitura a mais
    das chaves existentes. Vale: "33.294 cotações gravadas" não distingue a
    primeira carga de uma recarga do mesmo arquivo, e é justamente essa
    diferença que diz se a subida da semana trouxe dado novo.
    """
    leitura = ler_arquivo(conteudo)
    cadastrados = set(sessao.scalars(select(Bond.ticker)))
    conhecidas = [c for c in leitura.cotacoes if c.ticker in cadastrados]

    ja_no_banco = set(
        sessao.execute(
            select(BondCotacao.bond_ticker, BondCotacao.data).where(
                BondCotacao.bond_ticker.in_({c.ticker for c in conhecidas} or {""})
            )
        ).all()
    )
    atualizadas = sum(1 for c in conhecidas if (c.ticker, c.data) in ja_no_banco)

    for comeco in range(0, len(conhecidas), TAMANHO_DO_LOTE):
        lote = conhecidas[comeco : comeco + TAMANHO_DO_LOTE]
        comando = insert(BondCotacao).values(
            [
                {
                    "bond_ticker": c.ticker,
                    "data": c.data,
                    "preco_pct_par": c.preco_pct_par,
                    "yield_pct": c.yield_pct,
                }
                for c in lote
            ]
        )
        sessao.execute(
            comando.on_conflict_do_update(
                index_elements=["bond_ticker", "data"],
                set_={
                    "preco_pct_par": comando.excluded.preco_pct_par,
                    "yield_pct": comando.excluded.yield_pct,
                },
            )
        )

    completados = _completar_catalogo(sessao, leitura, cadastrados)
    return Resultado(
        inseridas=len(conhecidas) - atualizadas,
        atualizadas=atualizadas,
        papeis_completados=completados,
    )


def _completar_catalogo(
    sessao: Session, leitura: Leitura, cadastrados: set[str]
) -> int:
    """Preenche `descricao`, `id_bloomberg` e `amt_outstanding` dos papéis.

    A `0100` semeia a CORRESPONDÊNCIA ticker → empresa, que ela sabe, e deixa
    estes três campos nulos, que ela não tem. Eles vêm do catálogo `A..E` do
    arquivo e mudam: o montante em circulação cai quando a companhia recompra
    papel. Então a subida os ATUALIZA, não só os preenche.

    NÃO CRIA PAPEL, pela mesma razão de `gravar` não gravar ticker desconhecido.
    """
    alterados = 0
    #: UMA VEZ POR TICKER, e isto é achado de revisão: um catálogo com o mesmo
    #: ticker em duas linhas e valores diferentes contaria o papel duas vezes em
    #: `papeis_completados`, e o relatório da importação diria 32 papéis num
    #: cadastro de 31. A primeira linha vence, como no par repetido do leitor.
    ja_visto: set[str] = set()
    for papel in leitura.papeis:
        if papel.ticker not in cadastrados or papel.ticker in ja_visto:
            continue
        ja_visto.add(papel.ticker)
        linha = sessao.get(Bond, papel.ticker)
        if linha is None:
            continue
        #: SÓ O QUE O ARQUIVO TRAZ sobrescreve: um campo vazio na planilha não
        #: apaga o que já está no cadastro. A planilha é a fonte do que ela
        #: informa, não do que ela omite.
        #:
        #: OS TRÊS CAMPOS, E NÃO O PRIMEIRO QUE MUDOU. A primeira versão disto
        #: tinha um `continue` depois de cada atribuição, e com descrição E
        #: montante alterados só a descrição entrava — a outra metade ficaria
        #: para a subida seguinte, e ninguém notaria a defasagem de uma semana.
        mudou = False
        if papel.descricao is not None and papel.descricao != linha.descricao:
            linha.descricao = papel.descricao
            mudou = True
        if papel.id_bloomberg is not None and papel.id_bloomberg != linha.id_bloomberg:
            linha.id_bloomberg = papel.id_bloomberg
            mudou = True
        if papel.amt_outstanding is not None and _difere(
            papel.amt_outstanding, linha.amt_outstanding
        ):
            linha.amt_outstanding = papel.amt_outstanding
            mudou = True
        if mudou:
            alterados += 1
    return alterados


def _difere(novo: Decimal, atual: Decimal | None) -> bool:
    """`Decimal('100') == Decimal('100.00')` é VERDADEIRO em valor e falso em
    representação — comparar como número evita contar alteração que não houve.

    O `numeric(18,2)` do banco devolve `100.00` para um `100` que a planilha
    trouxe como inteiro, e um `!=` de string contaria essa ida e volta como
    mudança em toda subida, para sempre.
    """
    return atual is None or novo != atual
