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
