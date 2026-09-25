"""O modelo que a pessoa baixa."""

import io

from app.casos_de_uso.modelo_de_importacao import gerar
from app.dominio.importacao_de_agendas import (
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
)

# Montado a partir dos dois conjuntos VIVOS do domínio, não retiptado à mão:
# se um deles ganhar ou perder uma chave, este fixture acompanha sozinho, sem
# precisar de outra edição neste arquivo. Um valor de exemplo por chave basta
# — o teste não verifica o CONTEÚDO da lista, só que ela vira aba e validação.
VOCABULARIOS = {
    chave: [f"{chave} exemplo"] for chave in VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS
}


def _abrir(conteudo: bytes):
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(conteudo))


def test_o_arquivo_tem_as_abas_de_preenchimento_e_as_de_vocabulario():
    planilha = _abrir(gerar(VOCABULARIOS))

    for aba in FORMATO:
        assert aba.nome in planilha.sheetnames


def test_o_cabecalho_de_cada_aba_e_o_da_descricao():
    """SE ISTO DIVERGIR, a pessoa preenche uma coluna que o leitor ignora."""
    planilha = _abrir(gerar(VOCABULARIOS))

    for aba in FORMATO:
        lidas = [celula.value for celula in next(planilha[aba.nome].iter_rows())]
        assert lidas[: len(aba.colunas)] == [c.nome for c in aba.colunas], aba.nome


def test_a_coluna_de_vocabulario_ganha_lista_suspensa():
    planilha = _abrir(gerar(VOCABULARIOS))
    agendas = planilha["Agendas"]

    assert len(agendas.data_validations.dataValidation) > 0


def test_a_aba_fechada_e_protegida_e_a_editavel_nao():
    """A diferença precisa ser visível E mecânica: a pessoa não deve conseguir
    digitar um clima novo sem esforço deliberado."""
    planilha = _abrir(gerar(VOCABULARIOS))

    assert planilha["Clima"].protection.sheet is True
    assert planilha["Instituições"].protection.sheet is False


def test_o_definedname_de_cada_vocabulario_resolve_para_a_aba_certa():
    """O QUE ISTO TRAVA: um `DefinedName` mal apontado não dá erro nenhum — o
    arquivo abre normalmente, a lista suspensa existe, e só se mostra errada
    quando alguém abre a aba de destino e vê que os valores não batem. Foi
    assim que a colisão entre o rótulo de `pessoas_aegea` e a aba de
    preenchimento "Pessoas da Aegea" quase passou despercebida: nenhum outro
    teste deste arquivo teria acusado o intervalo apontando para a aba
    errada. Este confere, por vocabulário, que o nome de aba do `DefinedName`
    é o rótulo esperado e que os valores lidos daquele intervalo são
    exatamente os que `gerar` recebeu — não o cabeçalho de uma aba de
    preenchimento que por acaso tem o mesmo nome."""
    planilha = _abrir(gerar(VOCABULARIOS))

    for chave, valores in VOCABULARIOS.items():
        (nome_da_aba, intervalo), = planilha.defined_names[chave].destinations
        assert nome_da_aba == ROTULO_DO_VOCABULARIO[chave], chave

        lidos = [
            celula.value
            for (celula,) in planilha[nome_da_aba][intervalo]
            if celula.value is not None
        ]
        assert lidos == valores, chave


def test_o_vocabulario_vazio_nao_quebra_o_arquivo():
    """Uma base nova não tem interlocutor nenhum, e o modelo tem de abrir."""
    vazio = {chave: [] for chave in VOCABULARIOS}

    planilha = _abrir(gerar(vazio))

    assert "Agendas" in planilha.sheetnames
