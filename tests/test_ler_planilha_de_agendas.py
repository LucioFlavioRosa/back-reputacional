"""Bytes viram linhas, ou o arquivo é recusado inteiro.

AS RECUSAS SÃO ESTRUTURAIS, e por isso derrubam o arquivo todo em vez de
marcarem a linha. Uma aba que não existe, um cabeçalho que não bate, dois
códigos iguais: nenhum desses tem conserto linha a linha, e propor 54 agendas
a partir de um arquivo cuja estrutura ninguém entendeu seria pedir conferência
de uma coisa que não é o que a pessoa preencheu.

O CABEÇALHO DOS TESTES VEM DE `FORMATO`, nunca de uma lista escrita aqui. Uma
lista escrita aqui envelheceria: a coluna nova entraria na descrição, o teste
continuaria verde contra o cabeçalho antigo, e o leitor passaria a recusar todo
arquivo que o gerador produz — sem nenhum teste vermelho para avisar.
"""

import io
from collections.abc import Mapping
from datetime import date

import pytest

from app.casos_de_uso.ler_planilha_de_agendas import ler
from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_agendas import FORMATO, aba_de


def _cabecalho(aba: str) -> list[str]:
    return [coluna.nome for coluna in aba_de(aba).colunas]


def _linha(aba: str, valores: Mapping[str, object]) -> list:
    """Uma linha posicional montada por NOME de coluna.

    Montar por nome e não por posição é o que deixa o teste sobreviver a uma
    coluna nova no meio da aba — e o que faz um nome errado falhar aqui, no
    teste, em vez de virar um valor silenciosamente na coluna vizinha.
    """
    nomes = _cabecalho(aba)
    desconhecidas = set(valores) - set(nomes)
    assert not desconhecidas, f"coluna que não existe em {aba!r}: {sorted(desconhecidas)}"
    return [valores.get(nome) for nome in nomes]


def _livro(abas: Mapping[str, list[list]]) -> bytes:
    """Escreve exatamente o que recebe — inclusive cabeçalho torto ou aba a menos."""
    from openpyxl import Workbook

    livro = Workbook()
    livro.remove(livro.active)
    for nome, linhas in abas.items():
        folha = livro.create_sheet(nome)
        for linha in linhas:
            folha.append(linha)
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


def _completa(
    agendas: list[Mapping[str, object]] = (),
    participantes: list[Mapping[str, object]] = (),
    pessoas_aegea: list[Mapping[str, object]] = (),
    materiais: list[Mapping[str, object]] = (),
) -> bytes:
    """Um arquivo estruturalmente válido, com as quatro abas e o cabeçalho certo."""
    por_aba = {
        "Agendas": agendas,
        "Participantes": participantes,
        "Pessoas da Aegea": pessoas_aegea,
        "Materiais": materiais,
    }
    return _livro(
        {
            aba.nome: [_cabecalho(aba.nome)]
            + [_linha(aba.nome, valores) for valores in por_aba[aba.nome]]
            for aba in FORMATO
        }
    )


#: A agenda mais simples que o leitor aceita: as três colunas que identificam
#: uma reunião. O resto é assunto da Tarefa 5 (o que falta vira divergência).
def _agenda(codigo: str = "A1", quando: object = date(2026, 9, 25), onde: str = "Valor Econômico"):
    return {"Código": codigo, "Data": quando, "Instituição": onde}


# =============================================================================
# o caminho que funciona
# =============================================================================


def test_le_uma_agenda():
    lido = ler(_completa(agendas=[_agenda()]))

    assert lido["Agendas"][0].celulas["Instituição"] == "Valor Econômico"


def test_guarda_de_que_linha_do_arquivo_a_agenda_veio():
    """`linha_origem` é o que deixa a pessoa voltar à planilha e conferir, e o
    que a `importacao_linha` grava. A primeira agenda está na linha 2, porque a
    1 é o cabeçalho — off-by-one aqui manda a pessoa olhar a linha errada."""
    lido = ler(_completa(agendas=[_agenda("A1"), _agenda("A2")]))

    assert [linha.numero for linha in lido["Agendas"]] == [2, 3]


def test_le_as_abas_filhas_ligadas_pelo_codigo():
    lido = ler(
        _completa(
            agendas=[_agenda("A1")],
            participantes=[{"Código": "A1", "Pessoa": "Ana Prado", "Principal": "sim"}],
        )
    )

    assert lido["Participantes"][0].celulas["Pessoa"] == "Ana Prado"


def test_a_ordem_das_colunas_nao_importa():
    """O leitor casa por NOME. Uma pessoa que arrasta uma coluna no Excel não
    devia ver o arquivo inteiro recusado — e quem lê por posição recusaria, ou
    pior, leria o valor da coluna vizinha como se fosse o certo."""
    nomes = _cabecalho("Agendas")
    trocado = [nomes[2], nomes[1], nomes[0], *nomes[3:]]
    valores = _agenda()
    linha = [valores.get(nomes[2]), valores.get(nomes[1]), valores.get(nomes[0])] + [
        None for _ in nomes[3:]
    ]
    conteudo = _livro(
        {
            "Agendas": [trocado, linha],
            "Participantes": [_cabecalho("Participantes")],
            "Pessoas da Aegea": [_cabecalho("Pessoas da Aegea")],
            "Materiais": [_cabecalho("Materiais")],
        }
    )

    lido = ler(conteudo)

    assert lido["Agendas"][0].celulas["Instituição"] == "Valor Econômico"


def test_coluna_extra_desconhecida_e_ignorada():
    """Alguém acrescenta uma coluna de rascunho para se organizar. Recusar o
    arquivo por causa dela seria proibir a pessoa de anotar na própria planilha,
    e nada se perde em ignorá-la: as colunas que o servidor usa estão todas lá."""
    conteudo = _livro(
        {
            "Agendas": [
                [*_cabecalho("Agendas"), "minhas anotações"],
                [*_linha("Agendas", _agenda()), "confirmar com o Radamés"],
            ],
            "Participantes": [_cabecalho("Participantes")],
            "Pessoas da Aegea": [_cabecalho("Pessoas da Aegea")],
            "Materiais": [_cabecalho("Materiais")],
        }
    )

    lido = ler(conteudo)

    assert lido["Agendas"][0].celulas["Instituição"] == "Valor Econômico"
    assert "minhas anotações" not in lido["Agendas"][0].celulas


def test_a_linha_inteiramente_vazia_e_ignorada():
    """É a linha que sobrou de um preenchimento abandonado, ou o rastro de um
    Ctrl+V. Propor uma agenda vazia daria uma divergência por coluna."""
    conteudo = _livro(
        {
            "Agendas": [
                _cabecalho("Agendas"),
                [None for _ in _cabecalho("Agendas")],
                _linha("Agendas", _agenda()),
            ],
            "Participantes": [_cabecalho("Participantes")],
            "Pessoas da Aegea": [_cabecalho("Pessoas da Aegea")],
            "Materiais": [_cabecalho("Materiais")],
        }
    )

    lido = ler(conteudo)

    assert len(lido["Agendas"]) == 1


def test_a_celula_so_com_espaco_conta_como_vazia():
    """Uma célula com um espaço parece vazia na tela e não é. Sem isto, a linha
    "vazia" que a pessoa acha que apagou viraria uma agenda a propor."""
    vazia = [" " for _ in _cabecalho("Agendas")]
    conteudo = _livro(
        {
            "Agendas": [_cabecalho("Agendas"), vazia, _linha("Agendas", _agenda())],
            "Participantes": [_cabecalho("Participantes")],
            "Pessoas da Aegea": [_cabecalho("Pessoas da Aegea")],
            "Materiais": [_cabecalho("Materiais")],
        }
    )

    lido = ler(conteudo)

    assert len(lido["Agendas"]) == 1


# =============================================================================
# a data, que chega de todas as formas
# =============================================================================


def test_a_data_digitada_como_TEXTO_e_lida():
    """UMA PLANILHA EXPORTADA DE OUTRA FERRAMENTA faz isso o tempo todo: a
    célula é texto e chega `str`, não `datetime`. Recusar seria recusar o
    arquivo que a pessoa de fato tem."""
    lido = ler(_completa(agendas=[_agenda(quando="25/09/2026")]))

    assert lido["Agendas"][0].celulas["Data"] == date(2026, 9, 25)


def test_a_data_em_iso_tambem_e_lida():
    """O formato que o Google Sheets e todo export de sistema produzem."""
    lido = ler(_completa(agendas=[_agenda(quando="2026-09-25")]))

    assert lido["Agendas"][0].celulas["Data"] == date(2026, 9, 25)


def test_a_data_ilegivel_chega_CRUA_e_nao_derruba_o_arquivo():
    """Isto é de propósito e é a fronteira entre esta tarefa e a Tarefa 5: data
    ilegível é divergência DE UMA LINHA, com as outras 53 seguindo em frente.
    Derrubar o arquivo aqui puniria as agendas certas pelo erro de uma."""
    lido = ler(_completa(agendas=[_agenda(quando="25 de setembro")]))

    assert lido["Agendas"][0].celulas["Data"] == "25 de setembro"


# =============================================================================
# as recusas estruturais
# =============================================================================


def test_aba_faltando_recusa_o_arquivo_inteiro():
    """Não faz sentido propor 54 agendas quando a planilha nem tem a aba."""
    sem_participantes = {
        aba.nome: [_cabecalho(aba.nome)] for aba in FORMATO if aba.nome != "Participantes"
    }

    with pytest.raises(RegraViolada, match="Participantes"):
        ler(_livro(sem_participantes))


def test_coluna_faltando_recusa_e_diz_qual():
    """Dizer QUAL falta é a diferença entre a pessoa consertar em dez segundos
    e a pessoa comparar 27 colunas à mão."""
    nomes = _cabecalho("Agendas")
    sem_instituicao = [nome for nome in nomes if nome != "Instituição"]
    abas = {aba.nome: [_cabecalho(aba.nome)] for aba in FORMATO}
    abas["Agendas"] = [sem_instituicao]

    with pytest.raises(RegraViolada, match="Instituição"):
        ler(_livro(abas))


def test_codigo_repetido_recusa_o_arquivo():
    """Dois códigos iguais tornam impossível saber a qual agenda o participante
    pertence — e adivinhar seria pior que recusar."""
    with pytest.raises(RegraViolada, match="A1"):
        ler(_completa(agendas=[_agenda("A1"), _agenda("A1", date(2026, 9, 26), "Outro")]))


def test_agenda_sem_codigo_recusa():
    """O código é o que liga as abas. Uma agenda sem ele não pode receber
    participante nenhum, e a pessoa não teria como descobrir por quê."""
    with pytest.raises(RegraViolada, match="[Cc]ódigo"):
        ler(_completa(agendas=[_agenda(codigo=None)]))


def test_linha_filha_com_codigo_orfao_recusa_e_cita_o_codigo():
    """A pessoa apagou a agenda e esqueceu os participantes dela. Importar os
    participantes de uma agenda que não existe é impossível, e ignorá-los em
    silêncio perderia gente da reunião."""
    with pytest.raises(RegraViolada, match="A9"):
        ler(
            _completa(
                agendas=[_agenda("A1")],
                participantes=[{"Código": "A9", "Pessoa": "Ana Prado"}],
            )
        )


def test_o_codigo_orfao_e_apontado_em_QUALQUER_aba_filha():
    """As três abas filhas têm o mesmo vínculo, e uma guarda que só olha
    Participantes deixaria Materiais e Pessoas da Aegea sem rede."""
    with pytest.raises(RegraViolada, match="A9"):
        ler(
            _completa(
                agendas=[_agenda("A1")],
                materiais=[{"Código": "A9", "Título": "Nota técnica"}],
            )
        )


def test_arquivo_que_nao_e_xlsx_recusa_com_mensagem_util():
    with pytest.raises(RegraViolada, match="xlsx"):
        ler(b"isto nao e uma planilha")


def test_arquivo_vazio_recusa_sem_estourar():
    with pytest.raises(RegraViolada, match="xlsx"):
        ler(b"")


def test_zip_que_nao_e_planilha_recusa_com_a_mesma_mensagem():
    """A assinatura `PK` passa a primeira barreira — um `.docx`, um `.zip`
    renomeado. É o openpyxl que recusa, e a tradução tem de valer aqui também,
    senão a pessoa lê "erro interno" para um arquivo que ela pode trocar."""
    with pytest.raises(RegraViolada, match="xlsx"):
        ler(b"PK\x03\x04" + b"lixo que nao e um zip valido")


def test_acima_do_teto_recusa():
    """Acima de 500 a tela de conferência deixa de ser conferível e a transação
    fica longa demais para uma requisição. Um dia de 54 cabe dez vezes."""
    with pytest.raises(RegraViolada, match="500"):
        ler(_completa(agendas=[_agenda(f"A{i}") for i in range(501)]))


def test_exatamente_no_teto_passa():
    """O contrapeso do teste acima: 500 é o limite, não o primeiro recusado."""
    lido = ler(_completa(agendas=[_agenda(f"A{i}") for i in range(500)]))

    assert len(lido["Agendas"]) == 500
