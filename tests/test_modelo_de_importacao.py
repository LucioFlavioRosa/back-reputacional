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
        # A ABA DE INTERLOCUTORES NÃO LISTA `vocabularios`: ela lista os PARES
        # (pessoa, instituição), que é a relação que o front tem. O nome definido
        # segue cobrindo a coluna A — é a lista inteira, e é a rede da suspensa
        # dependente quando o órgão da linha não é reconhecido.
        esperados = [] if chave == "interlocutores" else valores
        assert lidos == [*esperados, MARCADOR_DE_REPETICAO], chave


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


# =============================================================================
# a coluna Data: travada como data, não como texto
# =============================================================================


def _validacao_da_data(planilha):
    """A validação que cobre a coluna Data da aba Agendas."""
    from app.casos_de_uso.modelo_de_importacao import COLUNA_DA_DATA
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL, aba_de

    agendas = planilha[ABA_PRINCIPAL]
    letra = _letra_da_coluna(aba_de(ABA_PRINCIPAL), COLUNA_DA_DATA)
    for validacao in agendas.data_validations.dataValidation:
        if validacao.type == "date" and any(
            str(faixa).startswith(f"{letra}2:") for faixa in validacao.sqref.ranges
        ):
            return validacao
    return None


def _letra_da_coluna(aba, nome: str) -> str:
    from openpyxl.utils import get_column_letter

    for indice, coluna in enumerate(aba.colunas, start=1):
        if coluna.nome == nome:
            return get_column_letter(indice)
    raise AssertionError(f"a aba não tem a coluna {nome!r}")


def test_a_coluna_de_data_TRAVA_o_que_nao_e_data():
    """O PEDIDO DO DONO DO PRODUTO, e o defeito mais silencioso da planilha.

    Sem isto o Excel aceita `25/09/26`, `set/25`, `25.09.2026` ou o texto
    `amanhã` na coluna Data. Nenhum deles é recusado na hora; todos chegam ao
    servidor como texto, e a conferência acusa "data ilegível" numa linha que a
    pessoa jurava ter preenchido — depois de ela já ter feito as 54.

    Travar na célula é o único momento em que o erro custa uma tecla. O
    `showErrorMessage` é o que separa a restrição de verdade da decoração: sem
    ele o Excel desenha a validação e aceita tudo por cima."""
    validacao = _validacao_da_data(_abrir(gerar(VOCABULARIOS)))

    assert validacao is not None, "a coluna Data não tem validação de data"
    assert validacao.showErrorMessage is True
    assert validacao.allow_blank is True


def test_a_mensagem_de_erro_da_data_DIZ_O_FORMATO():
    """"Valor inválido" não ensina nada. A mensagem tem de dizer o formato, com
    um exemplo: quem digitou `25/9/26` precisa saber o que o arquivo espera."""
    from app.casos_de_uso.modelo_de_importacao import FORMATO_DA_DATA_NA_TELA

    validacao = _validacao_da_data(_abrir(gerar(VOCABULARIOS)))

    assert "dd/mm/aaaa" in validacao.error.lower()
    assert FORMATO_DA_DATA_NA_TELA == "DD/MM/YYYY"


def test_a_COLUNA_de_data_vem_com_o_formato_brasileiro():
    """O formato é a outra metade da trava: sem ele, quem digita `25/09/2026` numa
    célula Geral pode ver o Excel guardar o dia errado, ou guardar TEXTO — e então
    a validação recusaria o que estava certo, que é o pior dos mundos.

    NA COLUNA e não nas células: ver
    `test_o_formato_da_data_nao_materializa_as_500_linhas`."""
    from app.casos_de_uso.modelo_de_importacao import (
        COLUNA_DA_DATA,
        FORMATO_DA_DATA_NA_TELA,
    )
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL, aba_de

    agendas = _abrir(gerar(VOCABULARIOS))[ABA_PRINCIPAL]
    letra = _letra_da_coluna(aba_de(ABA_PRINCIPAL), COLUNA_DA_DATA)

    assert agendas.column_dimensions[letra].number_format == FORMATO_DA_DATA_NA_TELA


def test_o_formato_da_data_nao_materializa_as_500_linhas():
    """O DEFEITO QUE A SUÍTE INTEIRA PEGOU, e nenhum teste da planilha sozinho.

    Formatar `A2:A501` célula por célula CRIA as 500 células. O modelo passa a ter
    501 linhas usadas: quem abre vê o `Ctrl+End` cair no fim do nada, e toda linha
    acrescentada por código vai para a 502 em vez da 2 — foi assim que seis testes
    de outro arquivo quebraram de uma vez.

    O modelo sai com UMA linha usada: o cabeçalho."""
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL

    agendas = _abrir(gerar(VOCABULARIOS))[ABA_PRINCIPAL]

    assert agendas.max_row == 1


def test_a_data_aceita_o_passado_e_o_futuro():
    """A agenda PREVISTA é caso normal — `status` tem "previsto" —, e a
    importação também serve para registrar o histórico. Uma faixa apertada
    recusaria dado legítimo, que é pior que não travar: o piso existe só para
    que o Excel tenha um critério de data, não para julgar a agenda."""
    from datetime import date

    validacao = _validacao_da_data(_abrir(gerar(VOCABULARIOS)))

    assert validacao.operator == "greaterThanOrEqual"
    assert str(date(2000, 1, 1).year) in str(validacao.formula1)


# =============================================================================
# a relação instituição -> interlocutores
# =============================================================================
#
# O QUE O FRONT FAZ e a planilha não fazia. `interlocutoresDaInstituicao`, em
# `src/dominio/frentes.ts`, filtra a lista pelo `instituicao_id` da instituição
# escolhida: ao escolher o órgão, a pessoa já vê só quem fala por ele. Na planilha
# as duas abas eram listas soltas — nome de instituição de um lado, nome de pessoa
# do outro, sem nada dizendo quem é de quem. Quem preenche 54 agendas escolhia
# entre TODOS os interlocutores da base, e o erro só aparecia na conferência.

PARES = [
    ("Ana Prado", "Valor Econômico"),
    ("Assessoria da liderança", "Câmara Municipal"),
    ("Assessoria da liderança", "Valor Econômico"),
    ("Bruno Lima", "Câmara Municipal"),
]


def _com_pares(conteudo=None):
    return _abrir(gerar(VOCABULARIOS, PARES))


def test_a_aba_de_interlocutores_DIZ_de_quem_cada_um_e():
    """A relação tem de estar VISÍVEL na planilha, e não só na validação: é o que
    responde "quem fala por este órgão?" para quem está preenchendo, e é o que
    permite ao servidor desfazer homônimo sem perguntar."""
    from app.dominio.importacao_de_agendas import (
        COLUNA_DA_INSTITUICAO_DO_INTERLOCUTOR,
        ROTULO_DO_VOCABULARIO,
    )

    aba = _com_pares()[ROTULO_DO_VOCABULARIO["interlocutores"]]
    linhas = [(a, b) for a, b, *_ in aba.iter_rows(min_col=1, max_col=2, values_only=True)]

    assert linhas[0] == ("Interlocutor", COLUNA_DA_INSTITUICAO_DO_INTERLOCUTOR)
    assert ("Ana Prado", "Valor Econômico") in linhas


def test_os_interlocutores_vem_AGRUPADOS_por_instituicao():
    """AGRUPADOS E CONTÍGUOS, e não é estética: a lista suspensa dependente é um
    `OFFSET` a partir da primeira linha da instituição, com altura igual à
    contagem dela. Se as linhas de um mesmo órgão ficarem separadas, a suspensa
    daquele órgão mostra as pessoas do vizinho."""
    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    aba = _com_pares()[ROTULO_DO_VOCABULARIO["interlocutores"]]
    instituicoes = [
        linha[1]
        for linha in aba.iter_rows(min_row=2, min_col=1, max_col=2, values_only=True)
        if linha[1]
    ]

    # Cada instituição aparece num bloco só: o número de blocos é o número de
    # instituições distintas.
    blocos = [nome for i, nome in enumerate(instituicoes) if i == 0 or instituicoes[i - 1] != nome]
    assert len(blocos) == len(set(blocos)), instituicoes


def test_a_coluna_de_instituicao_do_interlocutor_TEM_a_suspensa_de_instituicoes():
    """Quem cadastra alguém novo escreve o nome na coluna A e escolhe o órgão na B.
    Digitar o órgão à mão aqui erraria a grafia e criaria a pessoa solta."""
    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    aba = _com_pares()[ROTULO_DO_VOCABULARIO["interlocutores"]]
    formulas = {dv.formula1 for dv in aba.data_validations.dataValidation}

    assert "=instituicoes" in formulas


def test_a_suspensa_de_interlocutor_DEPENDE_da_instituicao_da_linha():
    """O CORAÇÃO DO PEDIDO: escolher a instituição já reduz a lista de pessoas.

    A fórmula cita a coluna da instituição DA MESMA LINHA, a aba de
    interlocutores, e cai na lista inteira quando o órgão não é reconhecido —
    porque o órgão novo, digitado, é caminho normal, e uma suspensa vazia ali
    pareceria defeito."""
    from app.casos_de_uso.modelo_de_importacao import _letra_de_coluna
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL, aba_de

    agendas = _com_pares()[ABA_PRINCIPAL]
    letra_da_instituicao = _letra_de_coluna(aba_de(ABA_PRINCIPAL), "Instituição")
    dependentes = [
        dv
        for dv in agendas.data_validations.dataValidation
        if dv.formula1 and "OFFSET" in dv.formula1
    ]

    assert len(dependentes) == 4, "uma por coluna Interlocutor 1..4"
    formula = dependentes[0].formula1
    assert f"${letra_da_instituicao}2" in formula
    assert "Interlocutores" in formula
    # A rede: órgão não reconhecido cai na lista inteira, que é o nome definido.
    assert ",interlocutores," in formula
    # E não trava, pelo mesmo motivo de sempre: digitar nome novo é como se
    # cadastra alguém.
    assert dependentes[0].showErrorMessage is False
