"""O modelo que a pessoa baixa."""

import io

from app.casos_de_uso.modelo_de_importacao import gerar
from app.dominio.importacao_de_agendas import (
    FORMATO,
    MARCADOR_DE_REPETICAO,
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
    """SE ISTO DIVERGIR, a pessoa preenche uma coluna que o leitor ignora.

    A comparação é EXATA, não por prefixo. Uma versão por prefixo (`lidas[:
    len(aba.colunas)] == [...]`) já passou por cima de uma 26ª célula na
    linha 1 de Agendas — uma nota escrita direto na linha do cabeçalho, que
    `FORMATO` descreve com 25 nomes. A Tarefa 4 lê essa MESMA linha contra
    `FORMATO` para casar cabeçalho com coluna, e uma célula sobrando ali é
    exatamente a divergência que o docstring do domínio existe para evitar —
    por prefixo, este teste nunca a veria. A igualdade fecha essa classe
    inteira: nenhuma célula a mais pode se esconder depois do fim descrito."""
    planilha = _abrir(gerar(VOCABULARIOS))

    for aba in FORMATO:
        lidas = [celula.value for celula in next(planilha[aba.nome].iter_rows())]
        assert lidas == [c.nome for c in aba.colunas], aba.nome


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


def test_o_vocabulario_fechado_trava_e_o_editavel_nao():
    """A ASSIMETRIA É DE PROPÓSITO, e as duas metades quebram coisas
    diferentes se alguém as igualar por engano.

    Sem `showErrorMessage=True`, o Excel desenha a seta mas
    `DataValidation.showErrorMessage` nasce `False` no openpyxl — a "lista
    suspensa" aceita QUALQUER valor digitado por cima, e vira decoração, não
    restrição. `test_a_coluna_de_vocabulario_ganha_lista_suspensa`, que só
    confere que o objeto existe, não pegaria essa falha: reabrir o arquivo
    prova que a validação foi criada, não que ela trava alguma coisa.

    Vocabulário fechado (aqui, `status`, a coluna Situação) precisa travar —
    é a restrição que o cliente pediu, e um valor novo é mudança de regra.
    Vocabulário editável (aqui, `instituicoes`, a coluna Instituição) precisa
    CONTINUAR sem travar — digitar um nome novo e cadastrá-lo na aba editável
    é o caminho desenhado para a importação em massa; "consertar" esta
    metade pelo mesmo padrão da outra mataria essa funcionalidade."""
    planilha = _abrir(gerar(VOCABULARIOS))
    agendas = planilha["Agendas"]

    por_formula = {dv.formula1: dv for dv in agendas.data_validations.dataValidation}

    assert por_formula["=status"].showErrorMessage is True
    assert por_formula["=instituicoes"].showErrorMessage is False


def test_a_aba_de_agendas_nao_convida_mais_que_o_teto_de_500():
    """O QUE ISTO TRAVA: a lista suspensa cobrindo mais linhas que o servidor
    aceita convida a pessoa a preencher além do teto e só descobrir na
    recusa do upload inteiro. O intervalo da validação vai até a linha 501
    (cabeçalho + 500 agendas), nunca mais."""
    planilha = _abrir(gerar(VOCABULARIOS))
    agendas = planilha["Agendas"]

    for dv in agendas.data_validations.dataValidation:
        for intervalo in dv.sqref.ranges:
            assert intervalo.max_row == 501, str(dv.sqref)


def test_o_teto_de_agendas_esta_num_comentario_na_celula_codigo():
    """O QUE ISTO TRAVA: a nota do teto de 500 já foi uma célula extra na
    linha do cabeçalho — removida por quebrar `test_o_cabecalho_de_cada_
    aba_e_o_da_descricao` quando esse teste passou a comparar por igualdade.
    Virou comentário na célula "Código" (A1 de Agendas) precisamente para
    ficar visível a quem preenche sem tocar o valor de nenhuma célula — e sem
    este teste, alguém poderia mover ou apagar o comentário sem que nada
    percebesse, porque nenhum outro teste deste arquivo olha para ele."""
    planilha = _abrir(gerar(VOCABULARIOS))
    comentario = planilha["Agendas"]["A1"].comment

    assert comentario is not None
    assert "500" in comentario.text


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
        # O MARCADOR DE REPETIÇÃO FECHA A LISTA, e está dentro do intervalo de
        # propósito: a validação de vocabulário fechado bloqueia valor fora da
        # lista, então `idem` precisa estar nela para poder ser escrito — e
        # ficando na lista, é escolhido em vez de digitado.
        assert lidos == [*valores, MARCADOR_DE_REPETICAO], chave


def test_o_vocabulario_vazio_nao_quebra_o_arquivo():
    """Uma base nova não tem interlocutor nenhum, e o modelo tem de abrir."""
    vazio = {chave: [] for chave in VOCABULARIOS}

    planilha = _abrir(gerar(vazio))

    assert "Agendas" in planilha.sheetnames


def test_a_coluna_do_codigo_explica_quando_preencher():
    """O CÓDIGO CONFUNDE SE NÃO SE EXPLICAR.

    Ele é a primeira coluna da planilha e fica em branco na maioria das linhas —
    quem abre o arquivo pela primeira vez não tem como saber se esqueceu de
    preencher algo. O comentário na célula do cabeçalho diz as duas metades da
    regra: em branco quando a agenda não tem participante nem material, escrito
    quando tem, porque é ele que liga as linhas.

    Vai como COMENTÁRIO e não como célula: a Tarefa 4 lê a linha 1 contra
    `FORMATO`, e uma célula a mais ali é a divergência entre gerador e leitor que
    o domínio existe para impedir.
    """
    planilha = _abrir(gerar(VOCABULARIOS))["Agendas"]

    comentario = planilha["A1"].comment
    assert comentario is not None, "a célula do Código precisa explicar quando preencher"
    assert "participante" in comentario.text.lower()
