"""A planilha é decodificada UMA VEZ por subida.

O QUE O DONO DO PRODUTO VIU: "está tendo uma demora grande para ver a
importação". Medido com 25.000 linhas, o tamanho do export real da Clipei:

    decodificar o .xlsx uma vez ........ 5,1s
    a conferência fazia isso 4 vezes .. 14,3s
    o banco, nas mesmas 4 etapas ....... 0,02s
    as 4 passadas reusando as células .. 0,10s

Quatro leituras porque cada etapa abria o arquivo do zero: duas na previsão (uma
por fonte irmã), uma nos veículos e uma nos assuntos. Não era banco: era o mesmo
XML sendo decodificado de novo.

POR QUE ESTES TESTES EXISTEM. O ganho é invisível no resultado — a conferência
devolve exatamente a mesma coisa lendo uma ou quatro vezes. Ninguém nota a volta
da releitura olhando a tela, e nenhum outro teste quebraria: o único sinal seria
a demora voltar, que é o que a pessoa relatou. Então o que se prende aqui é a
CONTAGEM de decodificações, não o resultado.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte
from app.casos_de_uso import ingerir_mencoes
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


@pytest.fixture
def clipei(sessao) -> ScoreFonte:
    #: A CLIPEI DE PROPÓSITO: ela tem fonte irmã (`clipei_investidores`) lendo o
    #: mesmo arquivo, que é o caso em que a releitura dobrava.
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert fonte is not None
    return fonte


@pytest.fixture
def contador(monkeypatch) -> list[str]:
    """Registra cada DECODIFICAÇÃO do arquivo, pelo leitor que for.

    `_linhas_da_aba` continua sendo chamada quatro vezes, e é isso que se quer:
    cada etapa pede as linhas de que precisa. O que não pode repetir é a
    decodificação — e ela acontece em dois lugares: `_pelo_calamine`, o caminho
    normal, e `_abrir`, o do openpyxl (reserva, e o caminho dos arquivos grandes,
    que não guardam leitura).

    CONTAR SÓ UM DELES já me enganou: com o calamine na frente, o contador que
    olhava apenas `_abrir` passou a ver zero e os testes acusaram falsamente.
    """
    decodificadas: list[str] = []

    def contando(nome_do_metodo):
        original = getattr(ingerir_mencoes.ArquivoLido, nome_do_metodo)

        def embrulhado(eu, mapeamento):
            decodificadas.append(mapeamento.aba or "(primeira)")
            return original(eu, mapeamento)

        monkeypatch.setattr(ingerir_mencoes.ArquivoLido, nome_do_metodo, embrulhado)

    contando("_pelo_calamine")
    contando("_abrir")
    return decodificadas


CABECALHO = [
    "ID", "Data", "Veículo", "Atributo", "Subcategoria", "Classificação",
    "Empresa", "Aegea Tier", "Arquivo/Link", "Título", "Estado do Veículo",
    "Público-alvo",
]


def _planilha(quantas: int = 3) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    #: A ABA QUE O CADASTRO DA CLIPEI PEDE.
    aba.title = "Clipping"
    #: A linha de marcadores de nível que o export real traz acima do cabeçalho.
    aba.append(["N1", "N2", "N3"])
    aba.append(CABECALHO)
    for indice in range(quantas):
        aba.append([
            f"zz{indice}", date(2026, 8, 3 + indice), f"Jornal zz{indice}",
            "Governança", "Abastecimento", "Positivo", "Corsan", "2",
            f"https://exemplo/{indice}", f"Título {indice}", "RS", "Geral",
        ])
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def test_a_CONFERENCIA_decodifica_o_arquivo_uma_vez(sessao, clipei, contador):
    """Eram quatro: previsão da Clipei, previsão da irmã, veículos, assuntos."""
    ingerir_mencoes.conferir(sessao, clipei, _planilha())

    assert contador == ["Clipping"], (
        "a conferência decodificou o arquivo mais de uma vez: " + str(contador)
    )


def test_a_SUBIDA_decodifica_o_arquivo_uma_vez(sessao, clipei, contador):
    """Eram três: os veículos, e uma gravação por fonte irmã."""
    ingerir_mencoes.ingerir(sessao, clipei, _planilha())

    assert contador == ["Clipping"], (
        "a subida decodificou o arquivo mais de uma vez: " + str(contador)
    )


def test_cada_etapa_ainda_recebe_TODAS_as_linhas(sessao, clipei, contador):
    """O contrapeso: ler uma vez não pode servir meia planilha.

    `linhas()` é um gerador, e a armadilha óbvia de guardar a leitura é alguém
    consumir o iterador na primeira etapa e as seguintes receberem vazio. Aqui a
    subida inteira roda e as três menções têm de estar gravadas.
    """
    ingerir_mencoes.ingerir(sessao, clipei, _planilha(3))

    gravadas = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == clipei.id, Mencao.mes == date(2026, 8, 1))
    ).all()
    assert len(gravadas) == 3
    #: E COM CONTEÚDO, não linhas vazias: se o cabeçalho fosse perdido entre as
    #: passadas, os campos viriam nulos e o teste acima ainda passaria.
    assert sorted(m.veiculo for m in gravadas) == [
        "Jornal zz0", "Jornal zz1", "Jornal zz2"
    ]


def test_a_ABA_DE_OUTRA_FONTE_nao_vem_do_cache(sessao, clipei):
    """O cache é por nome de aba, e isso tem de ser verdade.

    Duas fontes da Approach leem abas DIFERENTES do mesmo arquivo (`CM` e `SL`).
    Um cache por arquivo, e não por aba, serviria à segunda as linhas da
    primeira — e a fonte inteira passaria a contar o dado da irmã, sem erro
    nenhum na tela.
    """
    from openpyxl import Workbook

    from app.dominio.ingestao_score import Mapeamento

    livro = Workbook()
    primeira = livro.active
    primeira.title = "CM"
    primeira.append(["Data", "Sentimento", "Concorrente"])
    primeira.append([date(2026, 8, 3), "Positivo", "da aba CM"])
    segunda = livro.create_sheet("SL")
    segunda.append(["Data", "Sentimento", "Concorrente"])
    segunda.append([date(2026, 8, 4), "Negativo", "da aba SL"])
    memoria = io.BytesIO()
    livro.save(memoria)

    arquivo = ingerir_mencoes.ArquivoLido(memoria.getvalue())
    de_cm = Mapeamento.de_json(
        {"aba": "CM", "colunas": {"data": "Data", "sentimento": "Sentimento"}}
    )
    de_sl = Mapeamento.de_json(
        {"aba": "SL", "colunas": {"data": "Data", "sentimento": "Sentimento"}}
    )

    linhas_cm = [linha["Concorrente"] for linha in arquivo.linhas(de_cm)]
    linhas_sl = [linha["Concorrente"] for linha in arquivo.linhas(de_sl)]

    assert linhas_cm == ["da aba CM"]
    assert linhas_sl == ["da aba SL"]


def test_a_COLUNA_QUE_FALTA_na_irma_ainda_e_recusada(sessao, clipei):
    """A validação de coluna continua POR FONTE, e não uma vez para todas.

    Guardar a leitura junta o que o arquivo tem; não junta o que cada cadastro
    exige. Uma irmã que peça coluna ausente tem de ser recusada pelo nome da
    coluna, mesmo que a primeira fonte tenha lido bem o mesmo arquivo.
    """
    from app.dominio.erros import RegraViolada
    from app.dominio.ingestao_score import Mapeamento

    arquivo = ingerir_mencoes.ArquivoLido(_planilha())
    exigente = Mapeamento.de_json(
        {
            "aba": "Clipping",
            "colunas": {
                "data": "Data",
                "sentimento": "Classificação",
                "unidade": "Coluna Que Não Existe",
            },
        }
    )

    with pytest.raises(RegraViolada, match="Coluna Que Não Existe"):
        list(arquivo.linhas(exigente))


# -- os achados da revisão do Codex ----------------------------------------------


def test_o_CABECALHO_e_procurado_POR_FONTE_e_nao_herdado():
    """O achado que era de CORREÇÃO, e não de desempenho.

    `_achar_o_cabecalho` procura a primeira linha que traz as
    `colunas_necessarias` DAQUELA fonte. Guardar o cabeçalho junto com as
    células faria a irmã herdar o da primeira — e recusar uma coluna que existe
    numa linha mais abaixo.

    O cenário: a linha 1 serve a uma fonte modesta (`Data`/`Classificação`); a
    linha 2 é o cabeçalho completo, com `Empresa`. A fonte exigente tem de achar
    a linha 2, mesmo que a modesta já tenha lido a aba antes dela.
    """
    from openpyxl import Workbook

    from app.dominio.ingestao_score import Mapeamento

    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    #: A LINHA 1 JÁ CASA com o que a fonte modesta exige.
    aba.append(["Data", "Classificação"])
    #: A LINHA 2 é o cabeçalho de verdade, com a coluna que a irmã exige.
    aba.append(["Data", "Classificação", "Empresa"])
    aba.append([date(2026, 8, 3), "Positivo", "Corsan"])
    memoria = io.BytesIO()
    livro.save(memoria)

    arquivo = ingerir_mencoes.ArquivoLido(memoria.getvalue())
    modesta = Mapeamento.de_json(
        {"aba": "Clipping", "colunas": {"data": "Data", "sentimento": "Classificação"}}
    )
    exigente = Mapeamento.de_json(
        {
            "aba": "Clipping",
            "colunas": {
                "data": "Data",
                "sentimento": "Classificação",
                "unidade": "Empresa",
            },
        }
    )

    #: A MODESTA LÊ PRIMEIRO, e é ela que põe as células no cache.
    linhas_da_modesta = list(arquivo.linhas(modesta))
    assert len(linhas_da_modesta) == 2  # para ela, o cabeçalho completo é dado

    #: E A EXIGENTE AINDA ACHA O SEU CABEÇALHO.
    linhas_da_exigente = list(arquivo.linhas(exigente))
    assert [linha["Empresa"] for linha in linhas_da_exigente] == ["Corsan"]


def test_ARQUIVO_GRANDE_nao_fica_guardado(sessao, clipei, contador, monkeypatch):
    """O teto de memória, e o preço que ele cobra.

    Guardar as células de um arquivo de 40 MB comprimido — o limite de upload —
    chegaria a centenas de MB. Acima do teto a subida volta a decodificar por
    etapa: fica lenta como era antes, em vez de arriscar a memória do servidor.

    O TETO É BAIXADO no teste em vez de se gerar um arquivo de 8 MB: o que se
    afirma é a DECISÃO, e gerar oito megabytes de planilha para prová-la custaria
    minutos de suíte.
    """
    monkeypatch.setattr(ingerir_mencoes, "TAMANHO_PARA_GUARDAR_A_LEITURA", 1)

    ingerir_mencoes.conferir(sessao, clipei, _planilha())

    #: QUATRO DECODIFICAÇÕES, de novo — e aqui é o comportamento desejado.
    assert len(contador) == 4, contador
    #: E NADA FICA RETIDO, que é o ponto do teto.
    arquivo = ingerir_mencoes.ArquivoLido(b"xx")
    assert arquivo._guardar is False
    assert arquivo._lido == {}


def test_arquivo_grande_ainda_entrega_as_linhas_certas(sessao, clipei, monkeypatch):
    """O contrapeso: o caminho sem cache não pode servir meia planilha."""
    monkeypatch.setattr(ingerir_mencoes, "TAMANHO_PARA_GUARDAR_A_LEITURA", 1)

    ingerir_mencoes.ingerir(sessao, clipei, _planilha(3))

    gravadas = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == clipei.id, Mencao.mes == date(2026, 8, 1))
    ).all()
    assert sorted(m.veiculo for m in gravadas) == [
        "Jornal zz0",
        "Jornal zz1",
        "Jornal zz2",
    ]


# -- a troca do parser -----------------------------------------------------------


def test_as_CELULAS_do_calamine_saem_como_as_do_openpyxl():
    """Os dois leitores, no MESMO arquivo, célula por célula.

    O calamine lê o `.xlsx` 9,5x mais rápido (2,55s contra 0,27s, no export de
    25.000 linhas), e é por isso que ele entrou. O preço é que ele difere do
    openpyxl em três coisas, e todas as três mudariam o dado em silêncio:

    * vazio vem como `""`, não `None`;
    * inteiro vem como `float` — e a coluna `ID` da Clipei é numérica, então
      `id_fonte` gravaria `"12345.0"` no lugar de `"12345"`, que é o campo pelo
      qual se compara matéria com matéria;
    * `to_python()` pula as linhas vazias do topo, o que deslocaria a busca do
      cabeçalho.

    Este teste compara os dois leitores sobre o mesmo arquivo. Ele é a única
    coisa que acusaria a volta de qualquer uma das três — nenhuma produz erro.
    """
    import io as _io

    from openpyxl import Workbook, load_workbook

    from app.dominio.ingestao_score import Mapeamento

    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    #: UMA LINHA VAZIA NO TOPO: é o que o calamine pularia.
    aba.append([None, None, None, None])
    aba.append(["ID", "Data", "Classificação", "Engajamento"])
    #: ID INTEIRO, que é o caso do arquivo real; engajamento com decimal; e uma
    #: célula vazia no meio.
    aba.append([12345, date(2026, 8, 3), "Positivo", 1.5])
    aba.append([67890, date(2026, 8, 4), None, 7])
    memoria = _io.BytesIO()
    livro.save(memoria)
    conteudo = memoria.getvalue()

    pelo_openpyxl = list(
        load_workbook(_io.BytesIO(conteudo), read_only=True, data_only=True)[
            "Clipping"
        ].iter_rows(values_only=True)
    )
    de_json = {"aba": "Clipping", "colunas": {"data": "Data", "sentimento": "Classificação"}}
    pelo_calamine = ingerir_mencoes.ArquivoLido(conteudo)._pelo_calamine(
        Mapeamento.de_json(de_json)
    )

    #: AS DATAS SÃO O ÚNICO DESVIO ACEITO: `datetime` contra `date`, e
    #: `para_data` trata os dois desde antes desta troca. O resto tem de bater.
    def sem_a_hora(linha):
        return tuple(
            celula.date() if isinstance(celula, datetime) else celula for celula in linha
        )

    assert [sem_a_hora(linha) for linha in pelo_openpyxl] == [
        sem_a_hora(linha) for linha in pelo_calamine
    ]
    #: E EXPLICITAMENTE: a linha vazia do topo ficou, o id é inteiro, o vazio é
    #: nulo e o decimal continua decimal.
    assert pelo_calamine[0] == (None, None, None, None)
    assert pelo_calamine[2][0] == 12345
    assert pelo_calamine[3][2] is None
    assert pelo_calamine[2][3] == 1.5


def test_o_ID_NUMERICO_e_gravado_sem_o_PONTO_ZERO(sessao, clipei):
    """A diferença que mais machucaria, pelo caminho inteiro.

    `id_fonte` é como a plataforma compara matéria com matéria entre subidas. Um
    `12345.0` no lugar de `12345` não dá erro nenhum: só faz a mesma matéria
    parecer outra, e a conta de "repetida no mesmo mês" deixar de funcionar.
    """
    import io as _io

    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    aba.append(["N1", "N2", "N3"])
    aba.append(CABECALHO)
    linha = [
        99887766, date(2026, 8, 3), "Jornal zz50", "Governança", "Abastecimento",
        "Positivo", "Corsan", "2", "https://exemplo/1", "Título", "RS", "Geral",
    ]
    aba.append(linha)
    memoria = _io.BytesIO()
    livro.save(memoria)

    ingerir_mencoes.ingerir(sessao, clipei, memoria.getvalue())

    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == clipei.id, Mencao.mes == date(2026, 8, 1))
    )
    assert gravada.id_fonte == "99887766"


def test_o_OPENPYXL_e_a_RESERVA_quando_o_calamine_recusa(sessao, clipei, monkeypatch):
    """Leitor novo pode recusar arquivo que o antigo lia, e a subida não morre.

    O calamine leu esses arquivos por minutos; o openpyxl, por meses. Trocar sem
    rede faria uma planilha estranha — que o antigo aceitava — virar falha de
    subida por causa de uma otimização.
    """
    def recusando(eu, mapeamento):
        raise RuntimeError("o calamine não quis este arquivo")

    monkeypatch.setattr(ingerir_mencoes.ArquivoLido, "_pelo_calamine", recusando)

    resumo = ingerir_mencoes.ingerir(sessao, clipei, _planilha(2))

    assert resumo[0].ingeridas == 2


def test_a_ABA_QUE_FALTA_nao_cai_na_reserva_em_silencio(sessao, clipei):
    """Recusa de cadastro é mensagem para a pessoa, não falha de leitor.

    Se a aba ausente caísse no openpyxl, o arquivo seria lido duas vezes para
    chegar à mesma recusa — e a mensagem é a mesma. Ela sobe direto.
    """
    import io as _io

    from openpyxl import Workbook

    from app.dominio.erros import RegraViolada
    from app.dominio.ingestao_score import Mapeamento

    livro = Workbook()
    livro.active.title = "OutraAba"
    livro.active.append(["Data", "Classificação"])
    memoria = _io.BytesIO()
    livro.save(memoria)

    arquivo = ingerir_mencoes.ArquivoLido(memoria.getvalue())
    pedindo_clipping = Mapeamento.de_json(
        {"aba": "Clipping", "colunas": {"data": "Data", "sentimento": "Classificação"}}
    )

    with pytest.raises(RegraViolada, match="não tem a aba"):
        list(arquivo.linhas(pedindo_clipping))
