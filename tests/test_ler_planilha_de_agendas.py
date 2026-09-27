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
from app.dominio.importacao_de_agendas import (
    COLUNA_DE_REPETICAO,
    FORMATO,
    VALOR_DA_REPETICAO,
    aba_de,
)


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


def _completa(agendas: list[Mapping[str, object]] = ()) -> bytes:
    """Um arquivo estruturalmente válido: UMA aba, com o cabeçalho certo.

    As três abas filhas deixaram de existir — pessoas e materiais viraram colunas
    numeradas da própria linha da agenda.
    """
    return _livro(
        {
            "Agendas": [_cabecalho("Agendas")]
            + [_linha("Agendas", valores) for valores in agendas]
        }
    )


#: A agenda mais simples que o leitor aceita: as três colunas que identificam
#: uma reunião. O resto é assunto da Tarefa 5 (o que falta vira divergência).
def _agenda(quando=date(2026, 9, 25), onde: str = "Valor Econômico"):
    return {"Data": quando, "Instituição": onde}


def _repete(**valores):
    """Uma linha que repete a de cima, com o que ela sobrescreve."""
    return {COLUNA_DE_REPETICAO: VALOR_DA_REPETICAO, **valores}


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
    lido = ler(_completa(agendas=[_agenda(), _agenda()]))

    assert [linha.numero for linha in lido["Agendas"]] == [2, 3]



def test_a_ordem_das_colunas_nao_importa():
    """O leitor casa por NOME. Uma pessoa que arrasta uma coluna no Excel não
    devia ver o arquivo inteiro recusado — e quem lê por posição recusaria, ou
    pior, leria o valor da coluna vizinha como se fosse o certo."""
    # INVERTE O CABEÇALHO INTEIRO, e não só as três primeiras: a versão antiga
    # trocava as três da frente, e quando a ordem das colunas mudou para seguir o
    # formulário essas três passaram a não carregar valor nenhum — o teste seguia
    # verde sem provar nada. Invertido, toda coluna preenchida muda de lugar.
    nomes = list(reversed(_cabecalho("Agendas")))
    trocado = nomes
    valores = _agenda()
    linha = [valores.get(nome) for nome in nomes]
    conteudo = _livro(
        {
            "Agendas": [trocado, linha],
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
    """Sem a aba Agendas não há nada a importar, e o nome dela está na mensagem:
    quem renomeou a aba precisa saber qual nome o servidor procura."""
    with pytest.raises(RegraViolada, match="Agendas"):
        ler(_livro({"Outra coisa": [["Código"]]}))


def test_coluna_faltando_recusa_e_diz_qual():
    """Dizer QUAL falta é a diferença entre a pessoa consertar em dez segundos
    e a pessoa comparar 27 colunas à mão."""
    nomes = _cabecalho("Agendas")
    sem_instituicao = [nome for nome in nomes if nome != "Instituição"]
    abas = {aba.nome: [_cabecalho(aba.nome)] for aba in FORMATO}
    abas["Agendas"] = [sem_instituicao]

    with pytest.raises(RegraViolada, match="Instituição"):
        ler(_livro(abas))



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






# =============================================================================
# `Repetir a linha de cima`: a coluna que substituiu o marcador `idem`
# =============================================================================


def test_repetir_traz_o_valor_da_linha_de_cima():
    """UM DIA DE 54 REUNIÕES tem a mesma instituição, a mesma UF e a mesma data em
    dezenas de linhas, e digitar tudo de novo é trabalho e é erro.

    A COLUNA É EXPLÍCITA, e não "vazio herda": vazio continua significando vazio.
    Sem isso, deixar um campo em branco de propósito passaria a copiar o de cima, e
    um esquecimento viraria dado errado em silêncio — o oposto do que esta
    funcionalidade inteira defende.

    ANTES ERA O MARCADOR `idem`, escolhido dentro de qualquer lista suspensa.
    Funcionava e era indescobrível: ninguém abre a suspensa de Clima esperando
    encontrar ali uma instrução sobre a linha inteira.
    """
    lido = ler(_completa(agendas=[_agenda(onde="Valor Econômico"), _repete()]))

    assert lido["Agendas"][1].celulas["Instituição"] == "Valor Econômico"


def test_sem_marcar_a_celula_vazia_continua_vazia():
    """O contrapeso, e o motivo de a coluna existir: a célula em branco continua em
    branco, mesmo com valor na linha de cima."""
    lido = ler(
        _completa(
            agendas=[
                _agenda(onde="Valor Econômico"),
                {"Data": date(2026, 9, 26), "UF": "SP"},
            ]
        )
    )

    assert lido["Agendas"][1].celulas["Instituição"] is None


def test_repetir_vale_para_TODAS_as_colunas_de_uma_vez():
    """É AQUI QUE ESTÁ A ECONOMIA. Marcar coluna por coluna trocaria digitar 22
    valores por digitar 22 marcas, e não pouparia nada — era a crítica do dono do
    produto ao desenho anterior."""
    lido = ler(
        _completa(agendas=[{**_agenda(), "UF": "RJ", "Local": "Sede"}, _repete()])
    )

    assert lido["Agendas"][1].celulas["UF"] == "RJ"
    assert lido["Agendas"][1].celulas["Local"] == "Sede"


def test_o_que_a_linha_ESCREVE_vence_a_heranca():
    """O caso do evento: marca, e troca só o órgão. Sem isto a coluna só serviria
    para clonar a linha de cima, que não é o que ninguém precisa."""
    lido = ler(_completa(agendas=[_agenda(onde="ABDIB"), _repete(**{"Instituição": "ABIQUIM"})]))

    assert lido["Agendas"][1].celulas["Instituição"] == "ABIQUIM"
    assert lido["Agendas"][1].celulas["Data"] == date(2026, 9, 25)
    assert "Instituição" not in lido["Agendas"][1].herdado


def test_repetir_em_cadeia_propaga_o_valor_original():
    """Cinco reuniões no mesmo evento: cada linha herda da de cima, e o valor que
    chega à quinta é o que a primeira tinha."""
    lido = ler(
        _completa(agendas=[_agenda(onde="Valor Econômico"), _repete(), _repete()])
    )

    assert [linha.celulas["Instituição"] for linha in lido["Agendas"]] == [
        "Valor Econômico",
        "Valor Econômico",
        "Valor Econômico",
    ]


def test_a_marca_ignora_caixa_e_acento():
    """A pessoa escolhe da suspensa, mas também digita "Sim" ou "SIM"."""
    lido = ler(
        _completa(
            agendas=[
                _agenda(onde="Valor Econômico"),
                {COLUNA_DE_REPETICAO: "SIM"},
            ]
        )
    )

    assert lido["Agendas"][1].celulas["Instituição"] == "Valor Econômico"


def test_repetir_traz_a_DATA_como_data_e_nao_como_texto():
    """A conversão de data roda DEPOIS da herança. Se rodasse antes, a linha
    herdaria texto e a data viraria divergência numa linha preenchida certo."""
    lido = ler(_completa(agendas=[_agenda(quando=date(2026, 9, 25)), _repete()]))

    assert lido["Agendas"][1].celulas["Data"] == date(2026, 9, 25)
    assert lido["Agendas"][1].herdado["Data"] == date(2026, 9, 25)


def test_a_propria_coluna_de_repeticao_NAO_herda():
    """Herdá-la faria uma linha marcada contaminar todas as de baixo, e a pessoa
    perderia o controle de onde a cadeia começa: uma marca no meio do arquivo
    transformaria o resto dele em cópias."""
    lido = ler(
        _completa(
            agendas=[
                _agenda(onde="ABDIB"),
                _repete(),
                {"Data": date(2026, 9, 27), "Instituição": "ABIQUIM"},
            ]
        )
    )

    terceira = lido["Agendas"][2].celulas
    assert terceira["Instituição"] == "ABIQUIM"
    assert lido["Agendas"][2].herdado == {}



def test_a_linha_em_branco_continua_sendo_ignorada():
    """A verificação de linha vazia roda ANTES da herança, senão o rastro de um
    Ctrl+V viraria uma cópia da agenda de cima — agendas que ninguém digitou."""
    conteudo = _livro(
        {
            "Agendas": [
                _cabecalho("Agendas"),
                _linha("Agendas", _agenda()),
                [None for _ in _cabecalho("Agendas")],
            ],
        }
    )

    lido = ler(conteudo)

    assert len(lido["Agendas"]) == 1





# =============================================================================
# o cabeçalho dos DOIS modelos, e a herança pela coluna
# =============================================================================


def _com_cabecalho(nomes, *linhas):
    """Um arquivo com exatamente essas colunas, nessa ordem."""
    return _livro({"Agendas": [list(nomes), *[list(linha) for linha in linhas]]})


def test_o_cabecalho_do_SIMPLIFICADO_e_aceito():
    """O modelo simplificado tem 22 das 59 colunas. Antes desta mudança o leitor
    exigia TODAS as colunas da descrição, então o arquivo do próprio modelo
    simplificado seria recusado inteiro."""
    from datetime import date

    from app.dominio.importacao_de_agendas import MODELOS

    nomes = list(MODELOS["simplificado"])
    valores = [None] * len(nomes)
    valores[nomes.index("Data")] = date(2026, 9, 25)
    valores[nomes.index("Instituição")] = "ABDIB"

    (linha,) = ler(_com_cabecalho(nomes, valores))["Agendas"]

    assert linha.celulas["Instituição"] == "ABDIB"
    # A coluna que o modelo não tem simplesmente não existe na linha — e quem a
    # consulta usa `.get`, então ela vale como vazia.
    assert "Pendências" not in linha.celulas


def test_faltar_coluna_OBRIGATORIA_recusa_e_diz_qual():
    """A tolerância tem limite: sem a Data não há agenda, e descobrir isso linha por
    linha daria 500 pendências idênticas sobre um arquivo que está errado no
    cabeçalho."""
    with pytest.raises(RegraViolada, match="Data"):
        ler(_com_cabecalho(["Instituição", "UF"], ["ABDIB", "SP"]))


def test_faltar_coluna_OPCIONAL_e_aceito():
    """É o que faz os dois modelos coexistirem — e também acolhe o arquivo de quem
    apagou as colunas que não ia usar, que é o que se faz numa planilha."""
    from datetime import date

    (linha,) = ler(
        _com_cabecalho(["Data", "Instituição"], [date(2026, 9, 25), "ABDIB"])
    )["Agendas"]

    assert linha.celulas["Data"] == date(2026, 9, 25)


def test_coluna_desconhecida_continua_sendo_ignorada():
    """Alguém acrescenta uma coluna de rascunho para se organizar. Recusar por causa
    dela seria proibir a pessoa de anotar na própria planilha."""
    from datetime import date

    (linha,) = ler(
        _com_cabecalho(
            ["Data", "Instituição", "meu rascunho"], [date(2026, 9, 25), "ABDIB", "ver depois"]
        )
    )["Agendas"]

    assert "meu rascunho" not in linha.celulas


def test_a_coluna_de_REPETIR_herda_a_linha_de_cima_inteira():
    """O CASO DO EVENTO: 54 agendas do mesmo dia, e a pessoa troca só o órgão.

    Marca `sim` e a linha repete tudo o que a de cima tinha. O que ela escreveu na
    PRÓPRIA linha vence a herança — senão a coluna serviria apenas para clonar."""
    from datetime import date

    from app.dominio.importacao_de_agendas import COLUNA_DE_REPETICAO, VALOR_DA_REPETICAO

    nomes = [COLUNA_DE_REPETICAO, "Data", "Instituição", "Local"]
    primeira, segunda = ler(
        _com_cabecalho(
            nomes,
            [None, date(2026, 9, 25), "ABDIB", "Brasília"],
            [VALOR_DA_REPETICAO, None, "ABIQUIM", None],
        )
    )["Agendas"]

    assert primeira.celulas["Instituição"] == "ABDIB"
    assert segunda.celulas["Data"] == date(2026, 9, 25)
    assert segunda.celulas["Local"] == "Brasília"
    # O que ela escreveu vence.
    assert segunda.celulas["Instituição"] == "ABIQUIM"
    # E a tela precisa saber o que foi herdado: a célula está vazia na planilha.
    assert segunda.herdado["Local"] == "Brasília"
    assert "Instituição" not in segunda.herdado


def test_SEM_marcar_a_coluna_o_vazio_continua_vazio():
    """A linha OPTA por herdar. "Vazio herda" tiraria a possibilidade de deixar um
    campo vazio de propósito, e transformaria todo esquecimento em dado inventado."""
    from datetime import date

    from app.dominio.importacao_de_agendas import COLUNA_DE_REPETICAO

    nomes = [COLUNA_DE_REPETICAO, "Data", "Instituição", "Local"]
    _, segunda = ler(
        _com_cabecalho(
            nomes,
            [None, date(2026, 9, 25), "ABDIB", "Brasília"],
            [None, date(2026, 9, 26), "ABIQUIM", None],
        )
    )["Agendas"]

    assert segunda.celulas["Local"] is None
    assert segunda.herdado == {}


def test_marcar_repetir_na_PRIMEIRA_linha_recusa_dizendo_o_que_fazer():
    from app.dominio.importacao_de_agendas import COLUNA_DE_REPETICAO, VALOR_DA_REPETICAO

    with pytest.raises(RegraViolada, match="linha 2"):
        ler(
            _com_cabecalho(
                [COLUNA_DE_REPETICAO, "Data", "Instituição"],
                [VALOR_DA_REPETICAO, None, None],
            )
        )


def test_a_palavra_idem_numa_celula_DEIXOU_de_ser_instrucao():
    """O `idem` saiu. Escrito numa célula, ele é só texto — e texto num campo de
    vocabulário vira divergência, que é o correto: a pessoa escreveu algo que não
    existe no cadastro.

    SE CONTINUASSE FUNCIONANDO EM SILÊNCIO teríamos duas instruções para a mesma
    coisa, e a planilha nova ensinando uma enquanto o servidor obedece a outra."""
    from datetime import date

    from app.dominio.importacao_de_agendas import COLUNA_DE_REPETICAO

    nomes = [COLUNA_DE_REPETICAO, "Data", "Instituição", "Local"]
    _, segunda = ler(
        _com_cabecalho(
            nomes,
            [None, date(2026, 9, 25), "ABDIB", "Brasília"],
            [None, date(2026, 9, 26), "idem", None],
        )
    )["Agendas"]

    assert segunda.celulas["Instituição"] == "idem"
    assert segunda.herdado == {}
