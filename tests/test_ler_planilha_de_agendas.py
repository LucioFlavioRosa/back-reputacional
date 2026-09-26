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


def test_codigo_repetido_recusa_o_arquivo():
    """Dois códigos iguais tornam impossível saber a qual agenda o participante
    pertence — e adivinhar seria pior que recusar."""
    with pytest.raises(RegraViolada, match="A1"):
        ler(_completa(agendas=[_agenda("A1"), _agenda("A1", date(2026, 9, 26), "Outro")]))




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
# o Código é opcional quando a agenda não tem filhas
# =============================================================================


def test_agenda_sem_codigo_e_sem_filhas_e_aceita():
    """O CÓDIGO NÃO É IDENTIDADE DA AGENDA, é só o vínculo com as abas filhas.

    Quem tem 54 reuniões para registrar não deve preencher uma coluna que não
    serve para nada nas linhas que não têm participante nem material. A linha já
    se identifica por `linha_origem`, que o servidor grava sozinho.
    """
    lido = ler(_completa(agendas=[_agenda(codigo=None)]))

    assert len(lido["Agendas"]) == 1


def test_a_agenda_sem_codigo_ganha_um_do_servidor():
    """Ela precisa de UM código internamente, para o agrupamento das filhas
    funcionar sem um caso especial em cada passo — mas é o servidor que o põe."""
    lido = ler(_completa(agendas=[_agenda(codigo=None)]))

    assert lido["Agendas"][0].celulas["Código"]


def test_o_codigo_gerado_cita_a_linha_de_onde_veio():
    """Para a pessoa reconhecer de qual linha ele fala, se ele aparecer numa
    mensagem de erro."""
    lido = ler(_completa(agendas=[_agenda(codigo=None)]))

    assert "2" in str(lido["Agendas"][0].celulas["Código"])


def test_duas_agendas_sem_codigo_nao_colidem():
    """Sem isto, o servidor geraria o mesmo código duas vezes e a própria recusa
    de código repetido derrubaria um arquivo perfeitamente válido."""
    lido = ler(_completa(agendas=[_agenda(codigo=None), _agenda(codigo=None)]))

    codigos = {linha.celulas["Código"] for linha in lido["Agendas"]}
    assert len(codigos) == 2





def test_um_codigo_escrito_que_imita_o_gerado_e_recusado():
    """Se alguém escrever exatamente o que o servidor geraria, o código deixaria
    de ser único e a filha ligaria na agenda errada. Recusar é a saída honesta:
    só quem escreveu sabe o que quis dizer."""
    from app.casos_de_uso.ler_planilha_de_agendas import codigo_da_linha

    with pytest.raises(RegraViolada, match="reservado"):
        ler(_completa(agendas=[_agenda(codigo=codigo_da_linha(3)), _agenda(codigo=None)]))


# =============================================================================
# `idem`: repetir o valor da linha de cima, dizendo que repete
# =============================================================================


def test_idem_repete_o_valor_da_linha_de_cima():
    """UM DIA DE 54 REUNIÕES tem a mesma instituição, a mesma UF e a mesma data em
    dezenas de linhas, e digitar tudo de novo é trabalho e é erro.

    O MARCADOR É EXPLÍCITO, e não "vazio herda": vazio continua significando
    vazio. Sem isso, deixar um campo em branco de propósito passaria a copiar o de
    cima, e um esquecimento viraria dado errado em silêncio — o oposto do que esta
    funcionalidade inteira defende.
    """
    lido = ler(
        _completa(
            agendas=[
                _agenda("A1", onde="Valor Econômico"),
                _agenda("A2", onde="idem"),
            ]
        )
    )

    assert lido["Agendas"][1].celulas["Instituição"] == "Valor Econômico"


def test_idem_nao_se_confunde_com_vazio():
    """O contrapeso, e o motivo de o marcador existir: a célula em branco continua
    em branco, mesmo com valor na linha de cima."""
    lido = ler(
        _completa(
            agendas=[
                _agenda("A1", onde="Valor Econômico"),
                {"Código": "A2", "Data": date(2026, 9, 26), "UF": "SP"},
            ]
        )
    )

    assert lido["Agendas"][1].celulas["Instituição"] is None


def test_idem_vale_para_qualquer_coluna():
    lido = ler(
        _completa(
            agendas=[
                {**_agenda("A1"), "UF": "RJ", "Local": "Sede"},
                {**_agenda("A2"), "UF": "idem", "Local": "idem"},
            ]
        )
    )

    assert lido["Agendas"][1].celulas["UF"] == "RJ"
    assert lido["Agendas"][1].celulas["Local"] == "Sede"


def test_idem_em_cadeia_repete_o_ULTIMO_valor_de_verdade():
    """Três linhas com `idem` seguem repetindo o valor original, e não o marcador."""
    lido = ler(
        _completa(
            agendas=[
                _agenda("A1", onde="Valor Econômico"),
                _agenda("A2", onde="idem"),
                _agenda("A3", onde="idem"),
            ]
        )
    )

    assert [linha.celulas["Instituição"] for linha in lido["Agendas"]] == [
        "Valor Econômico",
        "Valor Econômico",
        "Valor Econômico",
    ]


def test_idem_ignora_caixa_e_acento():
    """A pessoa digita "Idem", "IDEM" ou escolhe da lista suspensa."""
    lido = ler(
        _completa(
            agendas=[_agenda("A1", onde="Valor Econômico"), _agenda("A2", onde="IDEM")]
        )
    )

    assert lido["Agendas"][1].celulas["Instituição"] == "Valor Econômico"


def test_idem_repete_a_DATA_como_data_e_nao_como_texto():
    """A conversão de data roda DEPOIS da herança, senão a linha herdaria o texto
    "idem" e a data viraria divergência numa linha que a pessoa preencheu certo."""
    lido = ler(
        _completa(
            agendas=[
                _agenda("A1", quando=date(2026, 9, 25)),
                _agenda("A2", quando="idem"),
            ]
        )
    )

    assert lido["Agendas"][1].celulas["Data"] == date(2026, 9, 25)


def test_idem_sem_nada_acima_recusa_e_diz_onde():
    """`idem` é uma instrução ao leitor, e uma instrução que ele não pode cumprir é
    problema de estrutura — como um cabeçalho que não bate. A mensagem cita a
    linha e a coluna porque a correção é de uma célula."""
    with pytest.raises(RegraViolada, match="[Ii]dem"):
        ler(_completa(agendas=[_agenda("A1", onde="idem")]))


def test_a_linha_em_branco_continua_sendo_ignorada():
    """A verificação de linha vazia roda ANTES da herança, senão o rastro de um
    Ctrl+V viraria uma cópia da agenda de cima — agendas que ninguém digitou."""
    conteudo = _livro(
        {
            "Agendas": [
                _cabecalho("Agendas"),
                _linha("Agendas", _agenda("A1")),
                [None for _ in _cabecalho("Agendas")],
            ],
        }
    )

    lido = ler(conteudo)

    assert len(lido["Agendas"]) == 1



def test_o_marcador_esta_na_lista_suspensa_de_um_vocabulario_fechado():
    """SEM ISSO O MARCADOR NÃO SERVE nas colunas que mais se repetem: a validação
    de vocabulário fechado BLOQUEIA valor fora da lista, então `idem` digitado em
    Clima seria recusado pelo próprio Excel antes de chegar ao servidor."""
    import io as _io

    from openpyxl import load_workbook

    from app.casos_de_uso.modelo_de_importacao import gerar
    from app.dominio.importacao_de_agendas import MARCADOR_DE_REPETICAO, ROTULO_DO_VOCABULARIO

    vocabularios = {
        chave: ["Um", "Outro"]
        for chave in ROTULO_DO_VOCABULARIO
    }
    pasta = load_workbook(_io.BytesIO(gerar(vocabularios)))
    folha = pasta[ROTULO_DO_VOCABULARIO["climas"]]
    valores = [celula.value for (celula,) in folha.iter_rows(min_col=1, max_col=1)]

    assert MARCADOR_DE_REPETICAO in valores


# =============================================================================
# um `idem` vale para a linha toda
# =============================================================================


def test_um_idem_faz_a_linha_INTEIRA_herdar():
    """O PONTO QUE FAZ O MARCADOR VALER A PENA.

    Escrever `idem` em cada uma das 27 colunas não economiza nada — troca digitar
    27 valores por digitar 27 marcadores. Um `idem` em qualquer célula declara
    "esta linha repete a de cima", e o resto vem de graça.
    """
    lido = ler(
        _completa(
            agendas=[
                {**_agenda("A1"), "UF": "RJ", "Local": "Sede", "Expectativa": "Destravar"},
                {"Código": "A2", "Data": "idem"},
            ]
        )
    )

    segunda = lido["Agendas"][1].celulas
    assert segunda["Data"] == date(2026, 9, 25)
    assert segunda["Instituição"] == "Valor Econômico"
    assert segunda["UF"] == "RJ"
    assert segunda["Local"] == "Sede"
    assert segunda["Expectativa"] == "Destravar"


def test_o_que_a_pessoa_PREENCHEU_prevalece_sobre_a_heranca():
    """É o caso de uso real: o dia é o mesmo, a instituição é outra. Ela escreve
    `idem` uma vez e só o que muda."""
    lido = ler(
        _completa(
            agendas=[
                {**_agenda("A1"), "UF": "RJ"},
                {"Código": "A2", "Data": "idem", "Instituição": "Outro Órgão"},
            ]
        )
    )

    segunda = lido["Agendas"][1].celulas
    assert segunda["Instituição"] == "Outro Órgão"
    assert segunda["UF"] == "RJ"


def test_a_linha_SEM_idem_nao_herda_nada():
    """A GARANTIA QUE NÃO SE PERDE: quem não pediu herança não recebe. Vazio
    continua vazio, e um esquecimento continua virando pendência em vez de dado
    inventado — a linha opta por herdar, uma linha de cada vez."""
    lido = ler(
        _completa(
            agendas=[
                {**_agenda("A1"), "UF": "RJ", "Local": "Sede"},
                {"Código": "A2", "Data": date(2026, 9, 26), "Instituição": "Outro"},
            ]
        )
    )

    segunda = lido["Agendas"][1].celulas
    assert segunda["UF"] is None
    assert segunda["Local"] is None


def test_o_CODIGO_da_agenda_nunca_herda():
    """Herdar o código faria duas agendas terem o mesmo, e o arquivo seria
    recusado por código repetido — a herança derrubaria o arquivo que ela deveria
    facilitar. Na aba Agendas o código IDENTIFICA a linha; nas filhas ele
    REFERENCIA outra, e é por isso que lá ele herda."""
    lido = ler(
        _completa(
            agendas=[
                _agenda("A1"),
                {"Data": "idem"},
            ]
        )
    )

    codigos = [linha.celulas["Código"] for linha in lido["Agendas"]]
    assert codigos[0] == "A1"
    assert codigos[1] != "A1"



def test_a_heranca_de_linha_segue_valendo_em_cadeia():
    """Cinco reuniões no mesmo dia: `idem` em cada linha, e todas herdam o
    original — não o marcador."""
    lido = ler(
        _completa(
            agendas=[
                {**_agenda("A1"), "UF": "RJ"},
                {"Código": "A2", "Data": "idem", "Instituição": "B"},
                {"Código": "A3", "Data": "idem", "Instituição": "C"},
            ]
        )
    )

    assert [linha.celulas["UF"] for linha in lido["Agendas"]] == ["RJ", "RJ", "RJ"]
    assert [linha.celulas["Data"] for linha in lido["Agendas"]] == [date(2026, 9, 25)] * 3
