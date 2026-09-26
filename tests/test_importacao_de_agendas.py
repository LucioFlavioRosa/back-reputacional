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


def test_o_formato_tem_uma_aba_de_preenchimento_so():
    """UMA ABA SÓ, por decisão do dono: quem preenche 54 reuniões não quer pular
    entre abas, e o vínculo por `Código` entre elas era a parte que mais
    confundia. As pessoas e os materiais viraram colunas numeradas."""
    assert [aba.nome for aba in FORMATO] == ["Agendas"]


def test_a_aba_de_agendas_comeca_pelo_codigo():
    """Primeira coluna porque é a referência da linha: é por ele que a conferência
    e as mensagens de erro chamam a agenda de que estão falando."""
    assert aba_de("Agendas").colunas[0].nome == "Código"


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
    clima é FECHADO (os KPIs dependem dele), instituição é cadastro.

    A chave é `"climas"`, não `"clima"`: é a mesma de `api/dicionarios.py ›
    FECHADOS`, e a Tarefa 6 resolve este vocabulário contra o banco por ela."""
    assert "climas" in VOCABULARIOS_FECHADOS
    assert "instituicoes" in VOCABULARIOS_EDITAVEIS


def test_todo_vocabulario_tem_rotulo_de_aba():
    """O GUARDA DO NOME SOLTO. `ROTULO_DO_VOCABULARIO` fecha a lacuna entre a
    chave do vocabulário e a aba que uma pessoa vê: sem ele, a Tarefa 3
    nomearia a aba de um jeito e a Tarefa 4 procuraria por outro, e os dois
    lados só descobririam a divergência com um arquivo de verdade na mão."""
    conhecidos = VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS
    assert set(ROTULO_DO_VOCABULARIO) == conhecidos


def test_nenhum_rotulo_de_vocabulario_repete_nome_de_aba_de_preenchimento():
    """O QUE ISTO TRAVA: o Excel não aceita duas abas com o mesmo nome, e o
    openpyxl resolve a colisão RENOMEANDO A SEGUNDA CALADAMENTE — sem erro,
    sem aviso. Se um rótulo de vocabulário repetir o nome de uma aba de
    `FORMATO`, a lista suspensa daquele vocabulário aponta, na prática, para
    a aba de preenchimento (cuja primeira linha é cabeçalho, não um valor
    válido) em vez da aba de vocabulário — e o arquivo abre normalmente, sem
    denunciar nada. Foi exatamente o que aconteceu com `"pessoas_aegea"`
    antes deste teste existir. Ele prende o dicionário INTEIRO contra as
    QUATRO abas de preenchimento, não só o par que já colidiu, porque o
    próximo rótulo a colidir pode ser outro."""
    nomes_de_preenchimento = {aba.nome for aba in FORMATO}
    colisoes = sorted(set(ROTULO_DO_VOCABULARIO.values()) & nomes_de_preenchimento)
    assert colisoes == []


def test_todo_campo_da_interacao_tem_destino_declarado():
    """O GUARDA DO CAMPO NOVO.

    Sem isto, acrescentar um campo a `InteracaoEntrada` o deixa fora da
    importação em silêncio: a planilha não o traz, ninguém reclama, e meses
    depois alguém pergunta por que as agendas importadas não têm aquele dado.
    """
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO
    from app.esquemas.interacoes import InteracaoEntrada

    campos = set(InteracaoEntrada.model_fields)
    sem_destino = sorted(campos - set(DESTINO_DO_CAMPO))

    assert sem_destino == []


def test_todo_campo_declarado_como_da_planilha_tem_coluna():
    """O outro lado: declarar que vem da planilha e não ter coluna faria o
    campo chegar sempre vazio, e a declaração mentiria."""
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO, FORMATO

    com_coluna = {
        coluna.campo for aba in FORMATO for coluna in aba.colunas if coluna.campo
    }
    prometidos = {
        campo for campo, destino in DESTINO_DO_CAMPO.items() if destino == "da planilha"
    }

    assert prometidos - com_coluna == set()


def test_frente_esfera_e_tier_sao_derivados():
    """Pô-los na planilha abriria a chance de a agenda contradizer o cadastro
    do órgão — que é o que derivar resolveu, no item 3 de 24/09."""
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO

    assert DESTINO_DO_CAMPO["esfera_id"] == "derivado"
    assert DESTINO_DO_CAMPO["frente"] == "derivado"
    assert DESTINO_DO_CAMPO["tier"] == "derivado"


# =============================================================================
# a classificação: resolve, cria ou diverge
# =============================================================================

#: O que já está no banco: chave normalizada → nome como está cadastrado.
CONHECIDOS = {"valor economico": "Valor Econômico"}


def test_casa_depois_de_normalizar_caixa_e_acento():
    from app.dominio.importacao_de_agendas import classificar

    assert classificar("VALOR ECONOMICO", "instituicoes", CONHECIDOS, set()) == "resolve"


def test_espaco_invisivel_colado_da_web_ainda_casa():
    """`\xa0` é o espaço não separável que vem de copiar de uma página. A pessoa
    não vê diferença nenhuma na tela, e o valor não casaria."""
    from app.dominio.importacao_de_agendas import classificar

    assert classificar("Valor\xa0Econômico ", "instituicoes", CONHECIDOS, set()) == "resolve"


def test_nome_novo_DECLARADO_na_aba_editavel_e_criado():
    from app.dominio.importacao_de_agendas import classificar

    declarados = {"prefeitura de campinas"}

    assert classificar("Prefeitura de Campinas", "instituicoes", CONHECIDOS, declarados) == "cria"


def test_nome_novo_digitado_SO_NA_CELULA_vira_divergencia():
    """A REGRA CENTRAL. Escrever na aba de cadastro é declaração de intenção;
    digitar na célula da agenda é, muito mais provavelmente, erro de grafia."""
    from app.dominio.importacao_de_agendas import classificar

    assert classificar("Prefeitura de Campinas", "instituicoes", CONHECIDOS, set()) == "diverge"


def test_o_mesmo_nome_em_duas_grafias_no_MESMO_arquivo_cria_um_so():
    """Declarado como "Prefeitura de Campinas" e usado como "PREFEITURA DE
    CAMPINAS": é o mesmo cadastro, e criar dois seria a duplicata que a
    conferência existe para evitar — agora vinda de dentro do arquivo."""
    from app.dominio.importacao_de_agendas import classificar

    declarados = {"prefeitura de campinas"}

    assert classificar("PREFEITURA DE CAMPINAS", "instituicoes", CONHECIDOS, declarados) == "cria"


def test_vocabulario_FECHADO_nunca_cria_mesmo_declarado():
    """A aba vem protegida, mas o Google Sheets tira a proteção ao converter.
    O servidor recusa de qualquer jeito: mudar clima é mudança de regra."""
    from app.dominio.importacao_de_agendas import classificar

    assert classificar("Eufórico", "climas", {}, {"euforico"}) == "diverge"


def test_vocabulario_fechado_com_valor_que_EXISTE_resolve():
    """O contrapeso: fechado não quer dizer intransponível, quer dizer que a
    lista é a lista. Sem isto, "fechado sempre diverge" passaria."""
    from app.dominio.importacao_de_agendas import classificar

    assert classificar("Propositivo", "climas", {"propositivo": "Propositivo"}, set()) == "resolve"


def test_valor_vazio_diverge_em_vez_de_casar_com_nada():
    """Uma célula vazia não é um nome. Sem esta guarda, `normalizar("")` daria
    `""`, e um `conhecidos` que por acidente tivesse a chave vazia casaria."""
    from app.dominio.importacao_de_agendas import classificar

    assert classificar("", "instituicoes", CONHECIDOS, set()) == "diverge"
    assert classificar("   ", "instituicoes", CONHECIDOS, set()) == "diverge"


# =============================================================================
# a divergência que a tela mostra
# =============================================================================


def test_a_divergencia_nasce_sem_sugestao():
    """`sugestoes` é opcional porque a maioria das divergências não tem nenhuma
    parecida a oferecer — e um default mutável aqui seria compartilhado entre
    todas elas."""
    from app.dominio.importacao_de_agendas import Divergencia

    divergencia = Divergencia(
        campo="instituicao_id",
        valor="Prefeitura de Campinas",
        mensagem="Instituição não encontrada",
        trava=True,
    )

    assert divergencia.sugestoes == ()


def test_a_divergencia_e_imutavel():
    """Ela é reescrita na resolução (Tarefa 10) trocando o objeto, não mutando:
    a lista de divergências de uma linha é comparada por valor, e mutar uma
    delas mudaria em silêncio o agrupamento que a tela já mostrou."""
    import dataclasses

    import pytest

    from app.dominio.importacao_de_agendas import Divergencia

    divergencia = Divergencia(campo="c", valor="v", mensagem="m", trava=False)

    with pytest.raises(dataclasses.FrozenInstanceError):
        divergencia.trava = True


# =============================================================================
# o agrupamento: a vista que a conferência mostra
# =============================================================================


def _divergencia(valor: str, campo: str = "instituicao_id", trava: bool = True):
    from app.dominio.importacao_de_agendas import Divergencia

    return Divergencia(
        campo=campo, valor=valor, mensagem=f"{valor} não existe no cadastro.", trava=trava
    )


def _linhas(*grupos: tuple[str, int]) -> list[tuple[int, list]]:
    """(valor, quantas) → [(numero_da_linha, [divergencias])], numerando do 2."""
    linhas: list[tuple[int, list]] = []
    numero = 2
    for valor, quantas in grupos:
        for _ in range(quantas):
            linhas.append((numero, [_divergencia(valor)]))
            numero += 1
    return linhas


def test_agrupa_por_valor_e_conta_as_linhas():
    """Uma decisão, doze linhas — é o que faz a conferência escalar com o volume
    em vez de crescer junto com ele."""
    from app.dominio.importacao_de_agendas import agrupar

    grupos = agrupar(_linhas(("Prefeitura de Campinas", 12)))

    assert grupos[0].valor == "Prefeitura de Campinas"
    assert len(grupos[0].linhas) == 12


def test_o_grupo_diz_QUAIS_linhas_ele_segura():
    """Contar não basta: a pessoa precisa poder ir olhar as linhas."""
    from app.dominio.importacao_de_agendas import agrupar

    (grupo,) = agrupar(_linhas(("A", 3)))

    # TUPLA e não lista: o grupo é congelado, e um membro mutável dentro de um
    # dataclass congelado é armadilha — quem recebe o grupo poderia alterar as
    # linhas dele sem que nada impedisse. A saída JSON é lista de qualquer jeito.
    assert grupo.linhas == (2, 3, 4)


def test_ordena_pelo_que_segura_mais_linhas():
    """A pessoa resolve primeiro o que destrava mais."""
    from app.dominio.importacao_de_agendas import agrupar

    grupos = agrupar(_linhas(("B", 3), ("A", 12)))

    assert [g.valor for g in grupos] == ["A", "B"]


def test_empate_ordena_pelo_valor_para_a_ordem_ser_ESTAVEL():
    """Duas leituras da mesma importação têm de dar a mesma tela. Sem desempate,
    a ordem sairia da iteração de um dicionário e a lista se remexeria entre dois
    F5 — e a pessoa perderia o lugar onde estava."""
    from app.dominio.importacao_de_agendas import agrupar

    grupos = agrupar(_linhas(("Zeta", 2), ("Alfa", 2)))

    assert [g.valor for g in grupos] == ["Alfa", "Zeta"]


def test_o_mesmo_valor_em_CAMPOS_diferentes_sao_grupos_diferentes():
    """"Ana Prado" não encontrada como interlocutora e como pessoa da Aegea são
    dois problemas, com duas resoluções diferentes."""
    from app.dominio.importacao_de_agendas import agrupar

    grupos = agrupar(
        [
            (2, [_divergencia("Ana Prado", campo="outra_parte.interlocutor_id")]),
            (3, [_divergencia("Ana Prado", campo="participacoes.pessoa_aegea_id")]),
        ]
    )

    assert len(grupos) == 2


def test_a_sugestao_traz_os_nomes_parecidos():
    from app.dominio.importacao_de_agendas import agrupar

    (grupo,) = agrupar(
        _linhas(("Prefeitura de Campinas", 1)),
        conhecidos=["Prefeitura Municipal de Campinas", "Valor Econômico"],
    )

    assert "Prefeitura Municipal de Campinas" in grupo.sugestoes
    assert "Valor Econômico" not in grupo.sugestoes


def test_sem_nome_parecido_a_sugestao_fica_vazia():
    """Oferecer o menos-ruim de uma lista sem nada parecido é pior que não
    oferecer: a pessoa aponta para o errado por confiar na sugestão."""
    from app.dominio.importacao_de_agendas import agrupar

    (grupo,) = agrupar(_linhas(("Prefeitura de Campinas", 1)), conhecidos=["Valor Econômico"])

    assert grupo.sugestoes == ()


def test_a_duplicata_possivel_NAO_trava():
    """Duas reuniões com o mesmo órgão no mesmo dia acontecem. Travar por isso
    ensinaria a pessoa a ignorar o aviso — e é o aviso que a protege do caso em
    que ela de fato subiu o arquivo duas vezes."""
    from app.dominio.importacao_de_agendas import agrupar

    (grupo,) = agrupar([(2, [_divergencia("25/09/2026", campo="data_interacao", trava=False)])])

    assert grupo.trava is False


def test_o_grupo_trava_se_QUALQUER_linha_dele_travar():
    """Um grupo é uma decisão só; se ela destrava algumas linhas e não todas, a
    tela não pode dizer que está tudo resolvido."""
    from app.dominio.importacao_de_agendas import agrupar

    grupos = agrupar(
        [
            (2, [_divergencia("A", trava=False)]),
            (3, [_divergencia("A", trava=True)]),
        ]
    )

    assert grupos[0].trava is True


def test_linha_sem_divergencia_nao_vira_grupo():
    from app.dominio.importacao_de_agendas import agrupar

    assert agrupar([(2, []), (3, [])]) == []


def test_a_ordem_das_colunas_segue_o_FORMULARIO():
    """QUEM PREENCHE A PLANILHA JÁ CONHECE O FORMULÁRIO.

    A ordem não é estética: quem registra 54 reuniões conhece a sequência da tela
    de nova interação, e uma planilha com os campos em outra ordem a obriga a
    procurar cada um. `Área` era a última coluna e é a SEGUNDA seção do
    formulário — o dono procurou e não achou.

    As colunas de PESSOA e MATERIAL vêm depois das da agenda, e não na posição das
    seções 4, 7 e 10 do formulário: elas são quatro grupos numerados, e intercalá-
    los no meio dos campos da agenda faria a pessoa rolar para os lados no meio do
    preenchimento de uma coisa só.
    """
    # Filtra pelo CAMPO e não pelo dígito no nome: `Tema 1` e `Área 1` são
    # numeradas e são campos da agenda, não grupos de pessoa ou material.
    DOS_GRUPOS = {"outra_parte", "participacoes", "materiais"}
    da_agenda = [
        coluna.nome
        for coluna in aba_de("Agendas").colunas
        if coluna.campo not in DOS_GRUPOS
    ]

    assert da_agenda == [
        "Código",
        # 1. Tipo de interação
        "Tipo de interação",
        # 2. Área(s)
        "Área 1",
        "Área 2",
        # 3. Identificação
        "Data",
        "Instituição",
        "UF",
        "Unidade de negócio",
        "Tema 1",
        "Tema 2",
        "Tema 3",
        # 5. Onde será ou foi realizada
        "Modalidade",
        "Local",
        # 6. Situação e expectativa
        "Iniciativa",
        "Situação",
        "Nota sobre o aceite",
        "Quem negou",
        "Por que foi negado",
        "Clima esperado",
        "Expectativa",
        # 8. Outputs da interação
        "Relato",
        "Repercussão e encaminhamentos",
        "Pendências",
        "Observações",
        # 9. Desfecho da interação
        "Clima",
        "Desfecho",
        "Desdobra em outra interação?",
    ]


def test_os_grupos_numerados_vem_no_fim_e_em_ordem():
    """Interlocutores, pessoas da Aegea e materiais, cada grupo inteiro antes do
    seguinte — e não `Interlocutor 1, Pessoa 1, Interlocutor 2`, que faria quem
    preenche saltar de assunto a cada duas colunas."""
    DOS_GRUPOS = {"outra_parte", "participacoes", "materiais"}
    numeradas = [
        coluna.nome for coluna in aba_de("Agendas").colunas if coluna.campo in DOS_GRUPOS
    ]

    assert numeradas[:4] == [
        "Interlocutor 1",
        "Presença 1",
        "Interlocutor 2",
        "Presença 2",
    ]
    assert numeradas[8:11] == [
        "Pessoa da Aegea 1",
        "Papel 1",
        "Presença da Aegea 1",
    ]
    assert numeradas[-4:] == [
        "Momento 3",
        "Título 3",
        "Link 3",
        "Observação do material 3",
    ]


def test_o_que_o_formulario_deriva_nao_e_coluna():
    """"Público" e "Relevância" aparecem no formulário e NÃO na planilha: os dois
    saem do cadastro da instituição. Uma coluna para eles permitiria que a agenda
    contradissesse o órgão — que é o que derivar resolveu."""
    nomes = {coluna.nome for coluna in aba_de("Agendas").colunas}

    assert "Público" not in nomes
    assert "Relevância" not in nomes
