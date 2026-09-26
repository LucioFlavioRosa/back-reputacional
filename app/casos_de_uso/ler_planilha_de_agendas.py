"""Bytes de um `.xlsx` viram linhas brutas, ou o arquivo é recusado inteiro.

O QUE ESTE MÓDULO NÃO FAZ. Ele não resolve nome contra cadastro, não decide o
que é divergência e não monta interação nenhuma — isso é da Tarefa 5 em diante.
Aqui só se responde "consigo entender a estrutura deste arquivo?", e o valor de
cada célula sai como a pessoa digitou.

A FRONTEIRA ENTRE RECUSAR O ARQUIVO E MARCAR A LINHA é a regra de desenho deste
módulo, e ela não é arbitrária:

  - recusa o ARQUIVO o que não tem conserto linha a linha — uma aba que não
    existe, um cabeçalho que não bate, dois códigos iguais, um participante
    apontando para agenda nenhuma. Nesses casos ninguém sabe o que a pessoa
    quis dizer, e propor 54 agendas a partir de um palpite seria pedir
    conferência de uma coisa que ela não preencheu.

  - deixa passar CRU o que é de uma linha só — uma data que não dá para ler,
    um nome que não existe no cadastro. Derrubar o arquivo por isso puniria as
    53 agendas certas pelo erro de uma, e é exatamente o que a tela de
    conferência existe para resolver.

É o `LinhaBruta` que carrega `numero`, e ele é o número da linha NO ARQUIVO,
contando o cabeçalho. É o que a `importacao_linha.linha_origem` grava e o que
deixa a pessoa voltar à planilha e conferir o que digitou.
"""

import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_agendas import FORMATO, Aba

#: Primeira barreira, antes de o parser de XML ver o arquivo: um `.xlsx` é um
#: zip, e todo zip começa assim. É a mesma guarda de `ingerir_mencoes`.
ASSINATURA_ZIP = b"PK\x03\x04"

#: Acima disto a tela de conferência deixa de ser conferível e a transação da
#: confirmação fica longa demais para uma requisição. Um dia de 54 agendas —
#: o caso que originou esta funcionalidade — cabe dez vezes.
TETO_DE_AGENDAS = 500

#: A aba que manda: é dela que saem os códigos que as outras três referenciam.
ABA_PRINCIPAL = "Agendas"

#: A coluna que liga as abas. Vive em todas as quatro.
COLUNA_DO_CODIGO = "Código"

#: Formatos de data que uma planilha de verdade entrega quando a célula é
#: TEXTO em vez de data: o brasileiro que a pessoa digita e o ISO que todo
#: export de sistema produz. A ordem importa — "03/04/2026" é 3 de abril aqui.
FORMATOS_DE_DATA = ("%d/%m/%Y", "%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class LinhaBruta:
    """Uma linha da planilha, sem interpretação além de aparar espaço e data."""

    aba: str
    #: O número da linha NO ARQUIVO. A primeira linha de dados é a 2.
    numero: int
    celulas: Mapping[str, object]


def _texto(valor: object) -> object:
    """Apara o espaço invisível antes de qualquer comparação.

    `str.strip()` sem argumento tira também o espaço não separável (`\xa0`) que
    vem de copiar de uma página web — e é preciso tirá-lo AQUI, porque ele faz
    um nome que existe no cadastro não casar, e a pessoa não vê diferença
    nenhuma na tela para entender por quê.
    """
    if not isinstance(valor, str):
        return valor
    aparado = valor.strip()
    return aparado or None


def _data(valor: object) -> object:
    """Devolve `date` quando consegue; o valor cru quando não.

    Deixar passar cru é deliberado: data ilegível é divergência de UMA linha,
    e quem decide isso é a Tarefa 5.
    """
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if not isinstance(valor, str):
        return valor
    for formato in FORMATOS_DE_DATA:
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            continue
    return valor


def _abrir(conteudo: bytes):
    """O arquivo aberto, ou `RegraViolada` com mensagem que a pessoa resolve."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
        raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

    nao_e_xlsx = RegraViolada(
        "O arquivo não é uma planilha .xlsx. "
        "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
    )
    if not conteudo.startswith(ASSINATURA_ZIP):
        raise nao_e_xlsx
    try:
        # `data_only` traz o VALOR de uma célula com fórmula: sem ele, uma data
        # montada com `=HOJE()` chegaria como a string "=HOJE()".
        return load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as erro:
        # Um `.docx`, um zip renomeado ou um upload truncado passam a assinatura
        # e morrem aqui. Sem a tradução, a pessoa leria "erro interno" para um
        # arquivo que ela mesma pode trocar.
        raise nao_e_xlsx from erro


def _indices(aba: Aba, cabecalho: tuple) -> dict[str, int]:
    """Coluna → posição, casando por NOME.

    POR NOME E NÃO POR POSIÇÃO. Quem lê por posição recusa o arquivo de quem
    arrastou uma coluna no Excel — ou pior, lê o valor da coluna vizinha como
    se fosse o certo, e a agenda entra com o dado trocado e sem erro nenhum.
    """
    lidos = {
        _texto(valor): posicao
        for posicao, valor in enumerate(cabecalho)
        if isinstance(valor, str) and _texto(valor)
    }
    faltando = [coluna.nome for coluna in aba.colunas if coluna.nome not in lidos]
    if faltando:
        raise RegraViolada(
            f"A aba {aba.nome!r} está sem a coluna {', '.join(repr(n) for n in faltando)}. "
            "Baixe o modelo de novo e transfira o que já preencheu — o cabeçalho "
            "precisa ser o mesmo."
        )
    # Colunas que não conhecemos ficam de fora, e é de propósito: alguém
    # acrescenta uma coluna de rascunho para se organizar, e recusar por causa
    # dela seria proibir a pessoa de anotar na própria planilha.
    return {coluna.nome: lidos[coluna.nome] for coluna in aba.colunas}


def _linhas_da_aba(aba: Aba, folha) -> list[LinhaBruta]:
    linhas = folha.iter_rows(values_only=True)
    try:
        cabecalho = next(linhas)
    except StopIteration:
        raise RegraViolada(f"A aba {aba.nome!r} está vazia, sem nem o cabeçalho.") from None

    indices = _indices(aba, cabecalho)
    e_data = {coluna.nome for coluna in aba.colunas if coluna.campo == "data_interacao"}

    lidas: list[LinhaBruta] = []
    for numero, valores in enumerate(linhas, start=2):
        celulas = {
            nome: _texto(valores[posicao]) if posicao < len(valores) else None
            for nome, posicao in indices.items()
        }
        # A linha inteiramente vazia é o rastro de um preenchimento abandonado
        # ou de um Ctrl+V. Propô-la daria uma divergência por coluna.
        if all(valor is None for valor in celulas.values()):
            continue
        for nome in e_data:
            celulas[nome] = _data(celulas[nome])
        lidas.append(LinhaBruta(aba=aba.nome, numero=numero, celulas=celulas))
    return lidas


def _codigos_das_agendas(linhas: list[LinhaBruta]) -> set[str]:
    """Os códigos da aba Agendas, recusando o que não dá para referenciar."""
    if len(linhas) > TETO_DE_AGENDAS:
        raise RegraViolada(
            f"A planilha tem {len(linhas)} agendas e o limite é {TETO_DE_AGENDAS} "
            "por arquivo. Divida em dois envios."
        )

    vistos: set[str] = set()
    for linha in linhas:
        codigo = linha.celulas.get(COLUNA_DO_CODIGO)
        if codigo is None:
            raise RegraViolada(
                f"A agenda da linha {linha.numero} está sem Código. "
                "É ele que liga a agenda aos participantes e materiais dela."
            )
        codigo = str(codigo)
        if codigo in vistos:
            raise RegraViolada(
                f"O Código {codigo!r} aparece em duas agendas. Com o código "
                "repetido não há como saber a qual delas cada participante "
                "pertence."
            )
        vistos.add(codigo)
    return vistos


def _conferir_vinculo(aba: Aba, linhas: list[LinhaBruta], codigos: set[str]) -> None:
    """Toda linha filha aponta para uma agenda que existe.

    Uma linha órfã é a agenda que a pessoa apagou e cujos participantes ela
    esqueceu. Importá-los é impossível; ignorá-los em silêncio perderia gente
    da reunião, e ninguém saberia que faltou alguém.
    """
    for linha in linhas:
        codigo = linha.celulas.get(COLUNA_DO_CODIGO)
        if codigo is None:
            raise RegraViolada(
                f"A linha {linha.numero} da aba {aba.nome!r} está sem Código, "
                "então não há como saber de que agenda ela é."
            )
        if str(codigo) not in codigos:
            raise RegraViolada(
                f"A linha {linha.numero} da aba {aba.nome!r} aponta para o "
                f"Código {str(codigo)!r}, que não existe na aba Agendas."
            )


def ler(conteudo: bytes) -> dict[str, list[LinhaBruta]]:
    """As linhas de cada aba, ou `RegraViolada` se a estrutura não se sustenta."""
    pasta = _abrir(conteudo)

    faltando = [aba.nome for aba in FORMATO if aba.nome not in pasta.sheetnames]
    if faltando:
        raise RegraViolada(
            f"A planilha está sem a aba {', '.join(repr(n) for n in faltando)}. "
            f"Abas encontradas: {', '.join(pasta.sheetnames)}. "
            "Baixe o modelo de novo — as quatro abas precisam estar lá."
        )

    por_aba = {aba.nome: _linhas_da_aba(aba, pasta[aba.nome]) for aba in FORMATO}

    codigos = _codigos_das_agendas(por_aba[ABA_PRINCIPAL])
    for aba in FORMATO:
        if aba.nome != ABA_PRINCIPAL:
            _conferir_vinculo(aba, por_aba[aba.nome], codigos)

    return por_aba
