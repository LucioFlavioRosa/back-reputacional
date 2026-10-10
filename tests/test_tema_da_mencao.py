"""A menção aponta para o tema do cadastro, e a conferência diz o que não casou.

O QUE ESTAVA QUEBRADO. `mencao.tema_id` existia na tabela e NUNCA era escrito —
zero em 29.898 menções. E isso deixava uma feature inteira inerte: o filtro do
dossiê por Pilar (N1), Tema estratégico (N2) e Subtema (N3) casa justamente por
`Mencao.tema_id`, então as opções voltavam vazias e o recorte nunca batia em
nada.

A DECISÃO DE NEGÓCIO QUE ISTO SERVE. A planilha informa só o N3; o N2, o N1 e os
riscos saem do cadastro — 104 temas ativos, nenhum sem N2, nenhum N2 sem N1, e
100 das 104 ligações para risco. Por isso a coluna de atributo da Bites saiu do
mapeamento: o N1 derivado é o mesmo dado, e manter os dois deixava a mesma
menção com dois N1 livres para discordar.

O QUE ESTES TESTES PROTEGEM:

* a menção liga por nome NORMALIZADO, como o veículo — acento, caixa e espaço
  da planilha não podem decidir se o filtro acha a menção;
* NÃO SE PARTE A CÉLULA EM VÍRGULAS: cinco temas do cadastro têm vírgula no
  nome ("Perdas, fraudes e furtos"), e partir destruiria os nomes certos;
* tema DESATIVADO não é ligado, e a conferência o separa do nome errado: um se
  conserta no cadastro, o outro na planilha;
* a conferência mostra o que não casou ANTES de gravar, com volume — é a
  diferença entre corrigir a planilha e descobrir o buraco no gráfico vazio;
* o vínculo vale para os DOIS caminhos de escrita, porque mora em `regravar`.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.casos_de_uso import ingerir_mencoes, temas_da_mencao
from app.dominio.ingestao_score import Mapeamento
from app.dominio.texto import normalizar
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
def bites(sessao) -> ScoreFonte:
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))
    assert fonte is not None
    return fonte


def _cabecalho(coluna_do_tema: str) -> list[str]:
    """O cabeçalho da Bites, com a coluna de tema QUE O CADASTRO MANDA LER.

    Escrita à mão, essa coluna já quebrou doze testes de uma vez: a `0079`
    apontou o tema para `N3` e o arquivo que estes testes geram deixou de ter
    coluna de assunto nenhuma — eles passaram a provar o contrário do que dizem.
    É a mesma regra de `_planilha_da_approach`, aqui também.
    """
    return ["Data", "Cargo", "Sentimento", "Unidades/Empresas", coluna_do_tema, "Engajamento"]


def _planilha(fonte: ScoreFonte, linhas: list[list]) -> bytes:
    from openpyxl import Workbook

    coluna = Mapeamento.de_json(fonte.mapeamento_colunas).colunas["tema"]
    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(_cabecalho(coluna))
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _planilha_da_approach(mapeamento: Mapeamento, assunto: str) -> bytes:
    """Uma planilha no formato da fonte, pelo próprio mapeamento dela.

    PELO MAPEAMENTO, e não com o cabeçalho escrito à mão: assim o teste não
    mente sobre o formato no dia em que o cadastro da fonte mudar.
    """
    from openpyxl import Workbook

    colunas = mapeamento.colunas
    cabecalho = [
        colunas["data"],
        colunas["sentimento"],
        colunas["tema"],
        colunas.get("unidade", "Unidades"),
        colunas.get("engajamento", "Engajamento"),
    ]
    livro = Workbook()
    aba = livro.active
    aba.title = mapeamento.aba or "Planilha1"
    aba.append(cabecalho)
    aba.append([date(2026, 8, 3), "Positivo", assunto, "Corsan", 1])
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _linha(assunto: str, dia: int = 3) -> list:
    return [date(2026, 8, dia), "Vereador", "Positivo", "Corsan", assunto, 10]


@pytest.fixture
def um_tema(sessao) -> Tema:
    """Um tema ATIVO do cadastro, com o N2 e o N1 que ele resolve."""
    tema = sessao.scalar(
        select(Tema).where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None)).limit(1)
    )
    assert tema is not None
    return tema


def test_a_mencao_aponta_para_o_tema_do_cadastro(sessao, bites, um_tema):
    ingerir_mencoes.ingerir(sessao, bites, _planilha(bites, [_linha(um_tema.nome)]))

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.tema_id == um_tema.id
    #: E O TEXTO CRU FICA, porque é o que o fornecedor disse: o vínculo não
    #: apaga a evidência de como o assunto chegou.
    assert gravada.tema_texto == um_tema.nome


def test_liga_pelo_nome_NORMALIZADO(sessao, bites, um_tema):
    #: Acento, caixa e espaço da planilha não podem decidir se o filtro acha a
    #: menção. É a mesma régua do vínculo do veículo.
    bagunçado = f"  {um_tema.nome.upper()}  "

    ingerir_mencoes.ingerir(sessao, bites, _planilha(bites, [_linha(bagunçado)]))

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.tema_id == um_tema.id


def test_o_assunto_que_o_cadastro_NAO_TEM_fica_sem_vinculo(sessao, bites):
    ingerir_mencoes.ingerir(sessao, bites, _planilha(bites, [_linha("Assunto inventado zz1")]))

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.tema_id is None
    assert gravada.tema_texto == "Assunto inventado zz1"


def test_a_CELULA_NAO_E_PARTIDA_em_virgulas(sessao, bites):
    """Cinco temas do cadastro têm vírgula no próprio nome.

    "Perdas, fraudes e furtos" e "Dívida, captação e solidez financeira" são UM
    assunto cada. Partir a célula em vírgulas para tratar "Fatura, Serviços"
    destruiria justamente os nomes certos — e a planilha multivalorada é
    conteúdo a corrigir, não formato a adivinhar.
    """
    com_virgula = sessao.scalar(
        select(Tema).where(Tema.ativo.is_(True), Tema.nome.like("%, %")).limit(1)
    )
    assert com_virgula is not None, "o cadastro tem de ter tema com vírgula no nome"

    ingerir_mencoes.ingerir(sessao, bites, _planilha(bites, [_linha(com_virgula.nome)]))

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.tema_id == com_virgula.id


def test_o_tema_DESATIVADO_nao_e_ligado(sessao, bites):
    """A taxonomia v4 desativou 45 temas.

    Ligar a menção a um deles a faria aparecer num filtro que a tela não
    oferece mais — o dossiê lista o que as menções alcançam, e o front descarta
    o tema desativado. Os números discordariam entre duas telas.
    """
    desativado = sessao.scalar(select(Tema).where(Tema.ativo.is_(False)).limit(1))
    assert desativado is not None

    ingerir_mencoes.ingerir(sessao, bites, _planilha(bites, [_linha(desativado.nome)]))

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.tema_id is None


def test_o_resumo_conta_quantas_ligaram(sessao, bites, um_tema):
    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            bites,
            [_linha(um_tema.nome, 3), _linha("Assunto inventado zz2", 4), _linha("", 5)],
        ),
    )

    assert resumo[0].ingeridas == 3
    assert resumo[0].mencoes_com_tema == 1


# -- a conferência ---------------------------------------------------------------


def test_a_conferencia_mostra_o_que_NAO_CASOU_antes_de_gravar(sessao, bites, um_tema):
    conteudo = _planilha(
        bites,
        [
            _linha(um_tema.nome, 3),
            _linha("Assunto inventado zz3", 4),
            _linha("Assunto inventado zz3", 5),
            _linha("", 6),
        ]
    )

    _previsao, _veiculos, assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    assert assuntos.ligadas == 1
    assert assuntos.sem_assunto == 1
    assert [(i.nome, i.mencoes) for i in assuntos.nao_ligados] == [
        ("Assunto inventado zz3", 2)
    ]
    #: E NÃO GRAVOU NADA.
    assert sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id)) is None


def test_a_conferencia_separa_o_tema_DESATIVADO_do_nome_errado(sessao, bites):
    #: São dois problemas com dois consertos: nome errado se arruma na
    #: planilha, tema desativado se arruma no cadastro.
    desativado = sessao.scalar(select(Tema).where(Tema.ativo.is_(False)).limit(1))
    conteudo = _planilha(bites, [_linha(desativado.nome, 3), _linha("Nome errado zz4", 4)])

    _previsao, _veiculos, assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    por_nome = {i.nome: i for i in assuntos.nao_ligados}
    assert por_nome[desativado.nome].desativado is True
    assert por_nome["Nome errado zz4"].desativado is False


def test_a_lista_do_que_nao_casou_vem_ORDENADA_POR_VOLUME(sessao, bites):
    conteudo = _planilha(
        bites,
        [_linha("Pouco zz5", 3)] + [_linha("Muito zz5", 4) for _ in range(3)]
    )

    _previsao, _veiculos, assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    #: O nome errado que aparece 300 vezes importa mais que o que aparece uma.
    assert [i.nome for i in assuntos.nao_ligados] == ["Muito zz5", "Pouco zz5"]


def test_a_conferencia_NAO_CONTA_a_linha_que_a_subida_descarta(sessao, bites, um_tema):
    """O achado Alto da revisão: a conferência contava linhas que não entram.

    A primeira versão lia as linhas da aba direto, sem filtros e sem descartes.
    A Bites traz 2.886 linhas e 1.426 caem por sentimento ilegível: a tela
    dizia "N acham o assunto" sobre 2.886, e o resumo depois de gravar contava
    sobre ~1.460 — o mesmo rótulo com dois números, quase o dobro de diferença,
    antes e depois de confirmar.
    """
    conteudo = _planilha(
        bites,
        [
            _linha(um_tema.nome, 3),
            #: SENTIMENTO ILEGÍVEL: a linha não vira menção, e por isso não
            #: pode ser contada como assunto reconhecido.
            [date(2026, 8, 4), "Vereador", "Mais ou menos", "Corsan", um_tema.nome, 10],
        ]
    )

    _previsao, _veiculos, assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    assert assuntos.ligadas == 1


def test_a_conferencia_aplica_o_PREFIXO_do_fornecedor(sessao):
    """A outra metade do mesmo achado.

    As duas fontes da Approach mandam `2 - Aegea - Falta de Água`, e o
    mapeamento declara o prefixo a remover. Lendo a célula crua, a conferência
    listava TODOS os assuntos como desconhecidos e a subida ligava todos — a
    pessoa era mandada cobrar do fornecedor um problema que não existe.
    """
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "approach_sl"))
    assert fonte is not None
    mapeamento = Mapeamento.de_json(fonte.mapeamento_colunas)
    assert mapeamento.prefixo_a_remover, "a fonte precisa declarar o prefixo"

    tema = sessao.scalar(select(Tema).where(Tema.ativo.is_(True)).limit(1))
    conteudo = _planilha_da_approach(mapeamento, f"2 - Aegea - {tema.nome}")

    #: PELA FUNÇÃO QUE O DEFEITO MORAVA, e não por `conferir`: a Approach tem
    #: duas fontes no MESMO arquivo (abas SL e CM), e `conferir` prevê as duas
    #: — montar as duas abas aqui provaria o agrupamento, não o prefixo.
    assuntos = temas_da_mencao.reconhecer(
        sessao, ingerir_mencoes.assuntos_da_planilha(sessao, fonte, conteudo)
    )

    #: O PREFIXO SAIU e o assunto casou — como a gravação faz.
    assert assuntos.ligadas == 1
    assert assuntos.nao_ligados == ()


def test_fonte_sem_coluna_de_assunto_nao_reclama(sessao):
    #: As duas fontes da Approach mapeiam `tema`; uma fonte que não mapeasse
    #: nada precisa conferir sem estourar.
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "approach_sl"))
    assert fonte is not None
    mapeamento = dict(fonte.mapeamento_colunas)
    colunas = dict(mapeamento["colunas"])
    colunas.pop("tema", None)
    fonte.mapeamento_colunas = {**mapeamento, "colunas": colunas}
    sessao.flush()

    assert ingerir_mencoes.assuntos_da_planilha(sessao, fonte, b"") == {}


def test_o_mapa_do_cadastro_SO_TRAZ_ATIVOS(sessao):
    por_nome = temas_da_mencao.por_nome(sessao)

    ativos = sessao.scalars(select(Tema.nome).where(Tema.ativo.is_(True))).all()
    desativados = sessao.scalars(select(Tema.nome).where(Tema.ativo.is_(False))).all()
    assert len(por_nome) == len(ativos)
    for nome in desativados:
        assert normalizar(nome) not in por_nome
