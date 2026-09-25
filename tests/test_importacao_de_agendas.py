"""O formato da planilha de agendas — a descrição que o gerador e o leitor leem.

UMA DESCRIÇÃO, DOIS CONSUMIDORES. Se o formato morasse duas vezes, uma coluna
nova entraria no gerador e não no leitor, e a pessoa preencheria uma coluna que
ninguém lê — sem erro nenhum.
"""

from app.dominio.importacao_de_agendas import (
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
    aba_de,
)


def test_as_quatro_abas_de_preenchimento_existem():
    assert [aba.nome for aba in FORMATO] == [
        "Agendas",
        "Participantes",
        "Pessoas da Aegea",
        "Materiais",
    ]


def test_a_aba_de_agendas_comeca_pelo_codigo():
    """O `Código` é o que liga as abas filhas, e por isso é a primeira coluna:
    quem preenche precisa vê-lo antes de tudo."""
    assert aba_de("Agendas").colunas[0].nome == "Código"


def test_toda_aba_filha_tem_codigo():
    for aba in FORMATO[1:]:
        assert aba.colunas[0].nome == "Código", aba.nome


def test_nenhum_vocabulario_e_editavel_e_fechado_ao_mesmo_tempo():
    """São grupos exclusivos: `dicionarios.py` já garante isso do lado da
    Administração, e aqui a mesma regra precisa valer."""
    assert VOCABULARIOS_EDITAVEIS & VOCABULARIOS_FECHADOS == frozenset()


def test_toda_coluna_com_vocabulario_aponta_para_um_grupo_conhecido():
    """O QUE ISTO TRAVA: uma coluna nova com vocabulário escrito errado geraria
    lista suspensa vazia no modelo e divergência em toda linha na leitura."""
    conhecidos = VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS
    soltas = [
        (aba.nome, coluna.nome)
        for aba in FORMATO
        for coluna in aba.colunas
        if coluna.vocabulario and coluna.vocabulario not in conhecidos
    ]
    assert soltas == []


def test_o_clima_e_fechado_e_a_instituicao_e_editavel():
    """Os dois exemplos que o cliente deu, e eles caem em grupos diferentes:
    clima é FECHADO (os KPIs dependem dele), instituição é cadastro."""
    assert "clima" in VOCABULARIOS_FECHADOS
    assert "instituicoes" in VOCABULARIOS_EDITAVEIS


def test_todo_vocabulario_tem_rotulo_de_aba():
    """O GUARDA DO NOME SOLTO. `ROTULO_DO_VOCABULARIO` fecha a lacuna entre a
    chave do vocabulário e a aba que uma pessoa vê: sem ele, a Tarefa 3
    nomearia a aba de um jeito e a Tarefa 4 procuraria por outro, e os dois
    lados só descobririam a divergência com um arquivo de verdade na mão."""
    conhecidos = VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS
    assert set(ROTULO_DO_VOCABULARIO) == conhecidos
