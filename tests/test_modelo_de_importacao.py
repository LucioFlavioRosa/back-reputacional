"""O modelo que a pessoa baixa."""

import io

from app.casos_de_uso.modelo_de_importacao import gerar
from app.dominio.importacao_de_agendas import (
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
    colunas_do_cadastro,
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

    # SEM O `=`: o conteúdo de `<formula1>` é a fórmula, e o elemento já diz isso.
    assert por_formula["status"].showErrorMessage is True
    assert por_formula["instituicoes"].showErrorMessage is False


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
    """O QUE ISTO TRAVA: um `DefinedName` mal apontado não dá erro nenhum — o arquivo
    abre normalmente, a lista suspensa existe, e só se mostra errada quando alguém abre
    a aba de destino e vê que os valores não batem. Foi assim que a colisão entre o
    rótulo de `pessoas_aegea` e a aba de preenchimento "Pessoas da Aegea" quase passou
    despercebida: nenhum outro teste deste arquivo teria acusado o intervalo apontando
    para a aba errada.

    LÊ A FÓRMULA E NÃO UM INTERVALO, desde que o nome definido virou dinâmico
    (`INDEX` na última linha preenchida, para a lista crescer com o que a pessoa
    acrescenta). O que ele guarda é o mesmo: a aba citada é a do rótulo, e os valores
    que moram nela são os que `gerar` recebeu — não o cabeçalho de uma aba de
    preenchimento que por acaso tem o mesmo nome.
    """
    # COM OS PARES, como a rota sempre passa: sem eles as abas em pares listariam o
    # vocabulário, e o teste conferiria uma situação que a produção não tem.
    planilha = _abrir(gerar(VOCABULARIOS, PARES))

    for chave, valores in VOCABULARIOS.items():
        rotulo = ROTULO_DO_VOCABULARIO[chave]
        formula = planilha.defined_names[chave].attr_text

        # A ABA CITADA, e só ela: um `'Pessoas da Aegea'` no lugar de
        # `'Pessoas da Aegea (lista)'` é exatamente a colisão que este teste pegou.
        assert f"'{rotulo}'!" in formula, (chave, formula)
        abas_citadas = {
            pedaco.split("'!")[0].lstrip("(,").lstrip("'")
            for pedaco in formula.split("'")[1::2]
        }
        assert abas_citadas == {rotulo}, (chave, formula)

        # E os valores que moram naquela aba são os que `gerar` recebeu.
        # A aba com mais de uma coluna tem CABEÇALHO, então os valores começam na 2.
        primeira = 2 if len(colunas_do_cadastro(chave)) > 1 else 1
        lidos = [
            celula.value
            for (celula,) in planilha[rotulo].iter_rows(
                min_row=primeira, min_col=1, max_col=1
            )
            if celula.value is not None
        ]
        # A ABA DE INTERLOCUTORES NÃO LISTA `vocabularios`: ela lista os PARES
        # (pessoa, instituição), que é a relação que o front tem. O nome definido segue
        # cobrindo a coluna A — é a lista inteira, e é a rede da suspensa dependente
        # quando o órgão da linha não é reconhecido.
        # A ABA EM PARES lista o valor na coluna A, ordenada por dono e depois por
        # valor — é a contiguidade que a suspensa dependente exige.
        esperados = (
            [valor for valor, _ in sorted(PARES[chave], key=lambda par: (par[1], par[0]))]
            if chave in PARES
            else valores
        )
        assert lidos == esperados, chave


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

#: Os vocabulários que saem em PARES — valor na coluna A, dono na B. Um dicionário
#: porque são dois hoje, e o mecanismo é o mesmo para os dois.
PARES = {
    "interlocutores": [
        ("Ana Prado", "Valor Econômico"),
        ("Assessoria da liderança", "Câmara Municipal"),
        ("Assessoria da liderança", "Valor Econômico"),
        ("Bruno Lima", "Câmara Municipal"),
    ],
    "subcategorias_publico": [
        ("Federal", "Poder Executivo"),
        ("Estadual", "Poder Executivo"),
    ],
}


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

    assert "instituicoes" in formulas


def test_a_suspensa_de_interlocutor_DEPENDE_da_instituicao_da_linha():
    """O CORAÇÃO DO PEDIDO: escolher a instituição já reduz a lista de pessoas.

    A fórmula cita a coluna da instituição DA MESMA LINHA, a aba de
    interlocutores, e cai na lista inteira quando o órgão não é reconhecido —
    porque o órgão novo, digitado, é caminho normal, e uma suspensa vazia ali
    pareceria defeito."""
    from app.casos_de_uso.modelo_de_importacao import _letra_de_coluna
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL, colunas_do_modelo

    agendas = _com_pares()[ABA_PRINCIPAL]
    letra_da_instituicao = _letra_de_coluna(colunas_do_modelo("completo"), "Instituição")
    dependentes = [
        dv
        for dv in agendas.data_validations.dataValidation
        if dv.formula1 and "OFFSET" in dv.formula1
    ]

    assert len(dependentes) == 4, "uma por coluna Interlocutor 1..4"
    formula = dependentes[0].formula1
    assert f"${letra_da_instituicao}2" in formula
    assert "Interlocutores" in formula
    # SEM ÓRGÃO OU SEM NINGUÉM, A LISTA FICA VAZIA — ver
    # `test_a_suspensa_dependente_fica_VAZIA_e_nao_cai_na_lista_inteira`. Antes ela caía
    # na lista inteira, e isso convidava a escolher alguém de outro órgão: exatamente o
    # que o servidor recusa.
    assert ",interlocutores," not in formula
    assert "COUNTIF" in formula
    # E não trava, pelo mesmo motivo de sempre: digitar nome novo é como se
    # cadastra alguém.
    assert dependentes[0].showErrorMessage is False


# =============================================================================
# os dois modelos, e a coluna que substituiu o `idem`
# =============================================================================


def _cabecalho_de(conteudo: bytes) -> list[str]:
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL

    folha = _abrir(conteudo)[ABA_PRINCIPAL]
    return [celula.value for celula in next(folha.iter_rows())]


def test_o_gerador_faz_o_COMPLETO_por_padrao():
    """Quem não escolhe recebe o formato inteiro: perder colunas por omissão seria
    perder dado sem ninguém ter decidido isso."""
    from app.dominio.importacao_de_agendas import MODELOS

    assert _cabecalho_de(gerar(VOCABULARIOS)) == list(MODELOS["completo"])


def test_o_gerador_faz_o_SIMPLIFICADO_quando_pedido():
    """O modelo do evento: 37 colunas, na ordem do formulário."""
    from app.dominio.importacao_de_agendas import MODELOS

    conteudo = gerar(VOCABULARIOS, modelo="simplificado")

    assert _cabecalho_de(conteudo) == list(MODELOS["simplificado"])


def test_os_dois_modelos_tem_a_coluna_de_repetir_na_frente():
    from app.dominio.importacao_de_agendas import COLUNA_DE_REPETICAO

    for modelo in ("completo", "simplificado"):
        assert _cabecalho_de(gerar(VOCABULARIOS, modelo=modelo))[0] == COLUNA_DE_REPETICAO


def test_a_coluna_de_repetir_tem_suspensa_de_UM_valor():
    """Uma suspensa de um valor só é mais rápida de preencher do que um sim/não, e
    não deixa dúvida sobre o que significa a célula vazia."""
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL, VALOR_DA_REPETICAO

    agendas = _abrir(gerar(VOCABULARIOS))[ABA_PRINCIPAL]
    daquela_coluna = [
        dv
        for dv in agendas.data_validations.dataValidation
        if any(str(faixa).startswith("A2:") for faixa in dv.sqref.ranges)
    ]

    assert len(daquela_coluna) == 1
    assert daquela_coluna[0].formula1 == f'"{VALOR_DA_REPETICAO}"'
    # NÃO TRAVA: a coluna é conveniência, e travar o que a pessoa digita nela
    # transformaria um engano de digitação em arquivo recusado.
    assert daquela_coluna[0].showErrorMessage is False


def test_NENHUMA_aba_de_vocabulario_oferece_idem():
    """O marcador saiu junto com a própria ideia dele. Deixá-lo nas listas seria
    oferecer uma instrução que o servidor já não obedece."""
    planilha = _abrir(gerar(VOCABULARIOS))

    for aba in planilha.worksheets:
        valores = [
            str(celula.value).lower()
            for linha in aba.iter_rows()
            for celula in linha
            if celula.value is not None
        ]
        assert "idem" not in valores, aba.title


def test_no_simplificado_a_suspensa_de_data_segue_na_coluna_certa():
    """AS VALIDAÇÕES SEGUEM A COLUNA PELO NOME, e não pela letra: no simplificado a
    Data é a quinta coluna e no completo também, mas a Instituição muda de lugar
    entre eles — e a suspensa dependente do interlocutor cita a coluna dela.

    Se alguma validação usasse posição fixa, o simplificado validaria a coluna
    errada em silêncio, que é o pior defeito possível numa planilha."""
    from openpyxl.utils import get_column_letter

    from app.casos_de_uso.modelo_de_importacao import COLUNA_DA_DATA
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL, colunas_do_modelo

    for modelo in ("completo", "simplificado"):
        colunas = [coluna.nome for coluna in colunas_do_modelo(modelo)]
        letra = get_column_letter(colunas.index(COLUNA_DA_DATA) + 1)
        agendas = _abrir(gerar(VOCABULARIOS, modelo=modelo))[ABA_PRINCIPAL]
        datas = [
            dv for dv in agendas.data_validations.dataValidation if dv.type == "date"
        ]
        assert len(datas) == 1, modelo
        assert any(str(faixa).startswith(f"{letra}2:") for faixa in datas[0].sqref.ranges), (
            modelo,
            [str(f) for f in datas[0].sqref.ranges],
        )


def test_cada_coluna_do_arquivo_tem_a_LARGURA_do_tipo_dela():
    """A MESMA NECESSIDADE, NO OUTRO LUGAR. A tela já dimensiona cada coluna pelo tipo
    do dado; o arquivo que a pessoa PREENCHE saía com todas do mesmo tamanho — o
    Relato tão estreito quanto a UF, e é nele que ela digita um parágrafo.

    O TIPO É O MESMO da grade, vindo da mesma descrição: uma tabela de larguras
    escrita à parte aqui divergiria da tela no dia em que uma delas mudasse.
    """
    from openpyxl.utils import get_column_letter

    from app.casos_de_uso.modelo_de_importacao import LARGURA_NO_EXCEL
    from app.dominio.importacao_de_agendas import (
        ABA_PRINCIPAL,
        colunas_do_modelo,
        tipo_da_coluna,
    )

    agendas = _abrir(gerar(VOCABULARIOS))[ABA_PRINCIPAL]

    for indice, coluna in enumerate(colunas_do_modelo("completo"), start=1):
        letra = get_column_letter(indice)
        esperada = LARGURA_NO_EXCEL[tipo_da_coluna(coluna)]
        assert agendas.column_dimensions[letra].width == esperada, coluna.nome


def test_a_coluna_de_PROSA_e_a_mais_larga_do_arquivo():
    """O contrapeso que prova que a tabela de larguras não é decorativa: se todas
    fossem iguais, o teste acima passaria e a planilha continuaria ruim."""
    from app.casos_de_uso.modelo_de_importacao import LARGURA_NO_EXCEL

    for outro in ("marca", "data", "sigla", "lista", "texto"):
        assert LARGURA_NO_EXCEL["prosa"] > LARGURA_NO_EXCEL[outro], outro


def test_o_simplificado_tambem_recebe_as_larguras():
    """As larguras seguem o RECORTE, como as validações: no simplificado a coluna 17 é
    o Clima e no completo é o Relato, e uma largura por posição fixa daria o tamanho
    do parágrafo para a lista suspensa."""
    from openpyxl.utils import get_column_letter

    from app.casos_de_uso.modelo_de_importacao import LARGURA_NO_EXCEL
    from app.dominio.importacao_de_agendas import (
        ABA_PRINCIPAL,
        colunas_do_modelo,
        tipo_da_coluna,
    )

    agendas = _abrir(gerar(VOCABULARIOS, modelo="simplificado"))[ABA_PRINCIPAL]

    for indice, coluna in enumerate(colunas_do_modelo("simplificado"), start=1):
        letra = get_column_letter(indice)
        assert agendas.column_dimensions[letra].width == LARGURA_NO_EXCEL[
            tipo_da_coluna(coluna)
        ], coluna.nome


# =============================================================================
# a lista suspensa acompanha o que a pessoa acrescenta
# =============================================================================


def test_o_intervalo_do_vocabulario_CRESCE_com_o_conteudo():
    """O DEFEITO QUE O DONO DO PRODUTO ACHOU AO USAR: ele acrescentou instituições na
    aba e elas não apareceram na suspensa da agenda.

    A CAUSA: o nome definido era um intervalo FIXO — as 99 instituições do banco mais
    UMA linha em branco, o "convite a cadastrar". Quem acrescentava duas via a primeira
    na lista e a segunda não, sem nenhum aviso. E o pior caso é o silencioso: ela digita
    o nome na agenda, a suspensa não o tem, e a linha vira pendência de um cadastro que
    ela acabou de declarar.

    A CORREÇÃO é o intervalo DINÂMICO: o fim dele é `INDEX` na ÚLTIMA LINHA PREENCHIDA,
    calculada pelo Excel na hora de abrir a lista — e não a última que existia quando o
    arquivo foi gerado.

    O FIM NÃO É MAIS `COUNTA`, e a troca tem motivo (ver
    `test_o_intervalo_sobrevive_a_uma_linha_em_BRANCO_no_meio`): contagem de linhas
    preenchidas não é o mesmo que número da última linha preenchida, e a diferença entre
    as duas é uma linha vazia no meio da coluna.

    `INDEX` E NÃO `OFFSET`: `OFFSET` é volátil, e função volátil em validação de dados é
    onde o Excel se recusa a resolver em algumas versões. `INDEX` faz o mesmo sem ser
    volátil, e a expressão fica sendo um intervalo — `$A$2:INDEX(...)` —, que é a forma
    que a validação lê com menos ressalvas.
    """
    pasta = _abrir(gerar(VOCABULARIOS))

    definido = pasta.defined_names["instituicoes"].attr_text

    assert "INDEX" in definido, definido
    assert "$A:$A" in definido, definido
    assert "OFFSET" not in definido, definido


def test_o_intervalo_COMECA_depois_do_cabecalho():
    """As abas de duas colunas têm cabeçalho, e a lista não pode oferecer a palavra
    "Instituição" como se fosse uma instituição.

    O FIM É O MESMO NAS DUAS — a última linha preenchida da coluna. É a primeira linha
    que muda: com cabeçalho os valores começam na 2, sem cabeçalho na 1."""
    pasta = _abrir(gerar(VOCABULARIOS))

    assert "$A$2:" in pasta.defined_names["instituicoes"].attr_text
    assert "$A$1:" in pasta.defined_names["climas"].attr_text


def test_o_vocabulario_VAZIO_ainda_da_um_intervalo_valido():
    """Uma base nova não tem instituição nenhuma. Um intervalo de altura ZERO é inválido
    e o Excel recusa o arquivo inteiro ao abrir — que é o pior defeito possível, porque
    acontece antes de a pessoa conseguir fazer qualquer coisa."""
    vazio = {chave: [] for chave in VOCABULARIOS}

    pasta = _abrir(gerar(vazio))

    assert "MAX(" in pasta.defined_names["instituicoes"].attr_text


def test_a_suspensa_dependente_olha_MUITO_alem_das_linhas_de_hoje():
    """A mesma armadilha na fórmula do interlocutor: ela procurava a instituição num
    intervalo que terminava na última linha EXISTENTE quando o arquivo foi gerado. Quem
    acrescentasse um interlocutor abaixo disso não o veria na suspensa da agenda."""
    from app.casos_de_uso.modelo_de_importacao import _LINHAS_DE_ABAS_FILHAS
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL

    agendas = _abrir(gerar(VOCABULARIOS, PARES))[ABA_PRINCIPAL]
    dependentes = [
        dv
        for dv in agendas.data_validations.dataValidation
        if dv.formula1 and "OFFSET" in dv.formula1
    ]

    assert dependentes
    assert f"$B${_LINHAS_DE_ABAS_FILHAS}" in dependentes[0].formula1, dependentes[0].formula1


def test_a_fonte_da_suspensa_NAO_LEVA_o_sinal_de_igual():
    """O DEFEITO QUE FEZ A LISTA NÃO CRESCER, e ele é de formato.

    O conteúdo de `<formula1>` no OOXML é a fórmula SEM o `=` — o elemento já diz que
    aquilo é uma fórmula. Nós gravávamos `=instituicoes`, e o Excel tolera isso quando o
    nome é um INTERVALO estático (foi por isso que as suspensas sempre pareceram
    funcionar). Quando o nome passou a ser uma FÓRMULA — `OFFSET` com altura de `COUNTA`,
    para a lista crescer —, essa tolerância acabou: a lista parava no que existia quando
    o arquivo foi gerado, e o que a pessoa acrescentava na aba não aparecia em lugar
    nenhum.

    O TESTE OLHA O XML porque é lá que o defeito vive. Ler o objeto do openpyxl não
    pegaria: ele devolve exatamente a string que recebeu.
    """
    import re
    import zipfile

    conteudo = gerar(VOCABULARIOS, PARES)

    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        folhas = [nome for nome in arquivo.namelist() if nome.startswith("xl/worksheets/")]
        formulas = []
        for nome in folhas:
            xml = arquivo.read(nome).decode("utf-8")
            formulas.extend(re.findall(r"<formula1>(.*?)</formula1>", xml, re.S))

    assert formulas, "nenhuma validação de lista no arquivo"
    com_igual = [formula for formula in formulas if formula.startswith("=")]
    assert com_igual == [], com_igual


def test_a_suspensa_de_lista_literal_continua_entre_aspas():
    """O contrapeso: a coluna de repetição não aponta para nada, ela TEM a lista dentro
    da fórmula. `"sim"` entre aspas é a forma de uma lista literal, e tirar as aspas a
    transformaria num nome que não existe."""
    import re
    import zipfile

    with zipfile.ZipFile(io.BytesIO(gerar(VOCABULARIOS))) as arquivo:
        xml = arquivo.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert '<formula1>"sim"</formula1>' in re.sub(r"\s+", " ", xml)


# =============================================================================
# o pente fino: as abas de cadastro reproduzem o formulário da plataforma
# =============================================================================


def test_a_aba_de_cadastro_tem_os_campos_do_FORMULARIO():
    """O PEDIDO DO DONO DO PRODUTO: "garanta que todas as abas reproduzam os campos de
    cadastro que temos na plataforma, na parte de CRM".

    Os campos foram conferidos um por um em `CadastroDeInstituicoes.tsx` e
    `CadastroDePortaVozes.tsx`. Uma aba com menos campos que o formulário cria cadastro
    pela metade, e quem completa depois é alguém que não estava na reunião."""
    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    planilha = _abrir(gerar(VOCABULARIOS, PARES))

    def cabecalho(chave):
        folha = planilha[ROTULO_DO_VOCABULARIO[chave]]
        return [celula.value for celula in next(folha.iter_rows())]

    assert cabecalho("instituicoes") == [
        "Instituição",
        "Nome completo",
        "Abrangência",
        "Relevância",
        "Categoria de público",
        "Subcategoria",
    ]
    assert cabecalho("interlocutores") == ["Interlocutor", "Instituição", "Cargo", "E-mail"]
    assert cabecalho("pessoas_aegea") == [
        "Pessoa da Aegea",
        "Cargo",
        "E-mail",
        "Área",
        "É porta-voz?",
    ]


def test_TODA_coluna_de_cadastro_com_vocabulario_TEM_lista_suspensa():
    """A GUARDA DO PENTE. "Deve ter os mesmos mecanismos de preenchimento restrito" —
    uma coluna de vocabulário sem suspensa é texto livre, e aí o erro de grafia vira
    cadastro errado em vez de pendência."""
    from openpyxl.utils import get_column_letter

    from app.dominio.importacao_de_agendas import (
        ROTULO_DO_VOCABULARIO,
        VOCABULARIOS_EDITAVEIS,
        VOCABULARIOS_FECHADOS,
        colunas_do_cadastro,
    )

    planilha = _abrir(gerar(VOCABULARIOS, PARES))

    sem_suspensa = []
    for chave in VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS:
        folha = planilha[ROTULO_DO_VOCABULARIO[chave]]
        faixas = {
            str(faixa)
            for dv in folha.data_validations.dataValidation
            for faixa in dv.sqref.ranges
        }
        for posicao, coluna in enumerate(colunas_do_cadastro(chave), start=1):
            if not coluna.vocabulario:
                continue
            letra = get_column_letter(posicao)
            if not any(faixa.startswith(f"{letra}2:") for faixa in faixas):
                sem_suspensa.append((chave, coluna.nome))

    assert sem_suspensa == []


def test_a_SUBCATEGORIA_se_reduz_pela_categoria_da_linha():
    """O MESMO MECANISMO DO INTERLOCUTOR, pedido explicitamente: "deve ter os mesmos
    mecanismos assim como temos em interlocutores quando selecionamos a instituição".

    No formulário da plataforma, trocar a categoria LIMPA a subcategoria escolhida —
    porque uma subcategoria pertence a uma categoria só. Aqui o equivalente é a lista se
    reduzir às da categoria daquela linha."""
    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    folha = _abrir(gerar(VOCABULARIOS, PARES))[ROTULO_DO_VOCABULARIO["instituicoes"]]
    dependentes = [
        dv
        for dv in folha.data_validations.dataValidation
        if dv.formula1 and "OFFSET" in dv.formula1
    ]

    assert len(dependentes) == 1, [dv.formula1 for dv in dependentes]
    formula = dependentes[0].formula1
    # Aponta para a COLUNA DA CATEGORIA da mesma linha — a quinta da aba.
    assert "$E2" in formula, formula
    assert "Subcategorias de público" in formula
    # E fica VAZIA enquanto a categoria estiver vazia, em vez de oferecer todas.
    assert ",subcategorias_publico," not in formula


def test_a_aba_de_subcategorias_sai_com_a_CATEGORIA_dona_ao_lado():
    """É o que permite o `MATCH` da suspensa dependente — a mesma forma da aba de
    interlocutores, pelo mesmo motivo."""
    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    folha = _abrir(gerar(VOCABULARIOS, PARES))[
        ROTULO_DO_VOCABULARIO["subcategorias_publico"]
    ]
    linhas = [(a, b) for a, b, *_ in folha.iter_rows(min_col=1, max_col=2, values_only=True)]

    assert linhas[0] == ("Subcategoria", "Categoria de público")
    assert ("Federal", "Poder Executivo") in linhas


def test_a_suspensa_dependente_fica_VAZIA_e_nao_cai_na_lista_inteira():
    """O DEFEITO QUE O DONO DO PRODUTO ACHOU AO USAR, e era uma decisão minha errada.

    Ele criou uma instituição, não atrelou interlocutor nenhum a ela, foi lançar a agenda
    — e a suspensa mostrou TODOS os interlocutores da base.

    EU TINHA POSTO ESSA REDE de propósito, com o argumento de que uma suspensa vazia
    pareceria defeito. O argumento estava errado, e por uma razão que o próprio servidor
    prova: escolher alguém de outro órgão é justamente o que ele RECUSA (um interlocutor
    fala por uma instituição só). A rede convidava ao erro que o passo seguinte rejeita —
    e fazia isso na hora em que a pessoa está com 54 linhas para preencher.

    VAZIA É A RESPOSTA CERTA, e é o que o front já faz: `interlocutoresDaInstituicao`
    devolve lista vazia sem instituição escolhida e sem ninguém daquele órgão. A suspensa
    vazia diz a verdade — "este órgão ainda não tem ninguém cadastrado" — e digitar
    continua permitido, porque a coluna não trava: é assim que se declara alguém novo.
    """
    from app.dominio.importacao_de_agendas import ABA_PRINCIPAL

    agendas = _abrir(gerar(VOCABULARIOS, PARES))[ABA_PRINCIPAL]
    dependentes = [
        dv
        for dv in agendas.data_validations.dataValidation
        if dv.formula1 and "OFFSET" in dv.formula1
    ]

    assert dependentes
    for dv in dependentes:
        # A LISTA INTEIRA NÃO É MAIS A SAÍDA: o nome do vocabulário não pode aparecer
        # como alternativa do `IF`.
        assert ",interlocutores," not in dv.formula1, dv.formula1
        # E a condição passou a ser "quantos são", que também cobre o dono vazio.
        assert "COUNTIF" in dv.formula1, dv.formula1


def test_a_suspensa_da_SUBCATEGORIA_tambem_fica_vazia():
    """O mesmo mecanismo, a mesma regra: sem categoria escolhida, nenhuma subcategoria —
    e não todas elas."""
    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    folha = _abrir(gerar(VOCABULARIOS, PARES))[ROTULO_DO_VOCABULARIO["instituicoes"]]
    (dependente,) = [
        dv
        for dv in folha.data_validations.dataValidation
        if dv.formula1 and "OFFSET" in dv.formula1
    ]

    assert ",subcategorias_publico," not in dependente.formula1, dependente.formula1


def test_a_celula_de_reserva_da_suspensa_vazia_esta_SEMPRE_em_branco():
    """A GUARDA DO TRUQUE. Uma lista suspensa não aceita intervalo de altura zero, então
    "vazia" se faz apontando para uma célula em branco. Essa célula fica numa coluna que
    o gerador reserva e nunca escreve — e se algum dia escrever, a suspensa passaria a
    oferecer aquele valor em toda linha sem órgão."""
    from app.casos_de_uso.modelo_de_importacao import COLUNA_DE_RESERVA
    from app.dominio.importacao_de_agendas import (
        ROTULO_DO_VOCABULARIO,
        VOCABULARIOS_EM_PARES,
    )

    planilha = _abrir(gerar(VOCABULARIOS, PARES))

    for chave in VOCABULARIOS_EM_PARES:
        folha = planilha[ROTULO_DO_VOCABULARIO[chave]]
        for linha in range(1, 6):
            celula = folha[f"{COLUNA_DE_RESERVA}{linha}"]
            assert celula.value is None, (chave, celula.coordinate, celula.value)


# =============================================================================
# a largura também nas abas de cadastro
# =============================================================================


def test_TODAS_as_abas_tem_a_largura_de_cada_coluna():
    """O DONO DO PRODUTO PEDIU O MESMO AJUSTE FORA DA ABA DE AGENDAS: as larguras
    valiam só para `Agendas`, e as dezenove abas de cadastro continuavam com a
    coluna padrão do Excel — "Nome completo" do mesmo tamanho de "Relevância",
    com o nome do órgão cortado ao meio na aba onde ele é declarado.

    O TIPO VEM DA DESCRIÇÃO, como na aba de agendas: é o que impede uma tabela de
    larguras por nome de coluna, que envelheceria na primeira coluna nova."""
    from openpyxl.utils import get_column_letter

    from app.casos_de_uso.modelo_de_importacao import LARGURA_NO_EXCEL
    from app.dominio.importacao_de_agendas import tipo_da_coluna_de_cadastro

    pasta = _abrir(gerar(VOCABULARIOS))

    for chave in VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS:
        planilha = pasta[ROTULO_DO_VOCABULARIO[chave]]
        for indice, coluna in enumerate(colunas_do_cadastro(chave), start=1):
            letra = get_column_letter(indice)
            esperada = LARGURA_NO_EXCEL[tipo_da_coluna_de_cadastro(coluna)]
            assert planilha.column_dimensions[letra].width == esperada, (
                f"{ROTULO_DO_VOCABULARIO[chave]} › {coluna.nome}"
            )


def test_o_NOME_COMPLETO_do_orgao_e_mais_largo_que_a_relevancia():
    """O contrapeso: se todas as colunas de cadastro recebessem a mesma largura, o
    teste acima passaria e a aba continuaria ilegível. O nome completo do órgão é o
    texto mais longo que se escreve ali; a relevância é um número."""
    from app.casos_de_uso.modelo_de_importacao import LARGURA_NO_EXCEL
    from app.dominio.importacao_de_agendas import (
        colunas_do_cadastro,
        tipo_da_coluna_de_cadastro,
    )

    por_nome = {
        coluna.nome: LARGURA_NO_EXCEL[tipo_da_coluna_de_cadastro(coluna)]
        for coluna in colunas_do_cadastro("instituicoes")
    }

    assert por_nome["Nome completo"] > por_nome["Relevância"]
    assert por_nome["Nome completo"] > por_nome["Subcategoria"]


def test_o_intervalo_sobrevive_a_uma_linha_em_BRANCO_no_meio():
    """ACHADO DA REVISÃO, e é o mesmo defeito de antes por outro caminho: a pessoa
    acrescenta instituições deixando uma linha vazia entre elas, e as que estão abaixo
    do buraco desaparecem da suspensa.

    A CAUSA É `COUNTA`: ele conta as linhas COM conteúdo, não diz qual é a última. Com
    um buraco, a conta fica menor que o número da última linha preenchida, e o intervalo
    termina antes dela — silenciosamente, como o defeito original.

    A CORREÇÃO É PERGUNTAR PELA ÚLTIMA LINHA, e não pela quantidade: `MATCH` procurando
    um valor maior que qualquer texto devolve a posição da última célula de texto, e o
    mesmo com um número maior que qualquer número cobre os vocabulários numéricos (a
    Relevância é `1`, `2`, `3`). Buraco no meio deixa de importar.

    `COUNTA` FICA COMO PISO DENTRO DO `MAX`, e não como o fim do intervalo — a revisão
    lembrou que o modo aproximado do `MATCH` é documentado para intervalo ordenado, e
    esta aba é editada à mão. Os dois juntos num `MAX` não pioram nada: nenhum dos
    braços pode passar da última linha preenchida, e o pior caso de um é o
    comportamento do outro."""
    pasta = _abrir(gerar(VOCABULARIOS))

    definido = pasta.defined_names["instituicoes"].attr_text

    assert "MATCH(" in definido, definido
    assert "MAX(COUNTA(" in definido, definido


def test_o_intervalo_acha_a_ultima_linha_tambem_num_vocabulario_de_NUMEROS():
    """A Relevância sai como número, e o truque do texto (`REPT("z",255)`) não acha
    célula numérica nenhuma. Sem o segundo braço, a suspensa da Relevância cairia para
    a primeira linha — uma lista de um item só."""
    pasta = _abrir(gerar(VOCABULARIOS))

    definido = pasta.defined_names["relevancias"].attr_text

    assert 'REPT("z"' in definido, definido
    assert "E+307" in definido, definido


def test_o_modelo_marca_o_tema_repetido_nas_duas_versoes():
    """A FORMATAÇÃO CONDICIONAL É O QUE DÁ, e o pedido era outro.

    O pedido foi "ao escolher um tema, tirá-lo das outras colunas". O Excel não
    permite: uma célula aceita UMA validação, e uma lista não sabe excluir o que
    as vizinhas usaram. Trocar a lista por uma fórmula `COUNTIF` perderia a
    suspensa com os assuntos — e digitá-los à mão é o erro que a suspensa existe
    para impedir.

    O que entrou resolve o mesmo problema por outro caminho: a célula repetida
    fica vermelha na hora, a suspensa continua inteira, e a trava de verdade é a
    conferência. Este teste existe porque uma formatação condicional é
    invisível em revisão de código e some sem ninguém notar.
    """
    from openpyxl.utils import get_column_letter

    from app.dominio.importacao_de_agendas import CAMPO_DOS_TEMAS, colunas_do_modelo

    for modelo in ("completo", "simplificado"):
        pasta = _abrir(gerar(VOCABULARIOS, modelo=modelo))
        aba = pasta["Agendas"]

        regras = [
            (faixa.sqref, regra)
            for faixa in aba.conditional_formatting
            for regra in faixa.rules
        ]
        assert len(regras) == 1, (modelo, regras)
        faixa, regra = regras[0]

        # A FAIXA COBRE AS COLUNAS DE TEMA, e as 500 linhas do teto.
        colunas = colunas_do_modelo(modelo)
        de_tema = [
            indice
            for indice, coluna in enumerate(colunas, start=1)
            if coluna.campo == CAMPO_DOS_TEMAS
        ]
        assert len(de_tema) == 18, modelo
        primeira = get_column_letter(min(de_tema))
        ultima = get_column_letter(max(de_tema))
        assert str(faixa) == f"{primeira}2:{ultima}501", (modelo, str(faixa))

        # A FÓRMULA CONTA NA LINHA, não na coluna: `$` nas letras e não no
        # número. Fixar a linha compararia toda a planilha com a linha 2.
        (formula,) = regra.formula
        assert f"COUNTIF(${primeira}2:${ultima}2,{primeira}2)>1" in formula, modelo
        # EM BRANCO NÃO É REPETIÇÃO: dezoito células vazias contariam como
        # dezoito iguais, e a linha inteira nasceria vermelha.
        assert f'{primeira}2<>""' in formula, modelo
