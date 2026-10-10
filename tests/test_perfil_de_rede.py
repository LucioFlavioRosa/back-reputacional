"""O perfil de rede entra no Cadastro compartilhado, e não como veículo.

O QUE ISTO RESOLVE. A menção guarda QUEM FALOU em `veiculo`. Na Clipei isso é
um veículo de imprensa, e 25.457 das 25.573 menções dela apontam para uma
instituição do cadastro. A Bites não tinha vínculo nenhum: o `Autor` da
planilha não era lido, e as 2.886 menções entraram sem apontar para ninguém.

O GRÃO É O PERFIL, medido antes de decidir: dos 1.173 autores distintos do
arquivo de 01–09/2026, só 54 aparecem em mais de uma rede e só 2 em mais de um
estado. Uma entidade "rede + estado" colapsaria 1.173 perfis em ~30 baldes e
perderia `deolhoemesteio` com 135 menções e "Stela Farias" com 121.

O QUE ESTES TESTES PROTEGEM:

* o perfil nasce como `perfil_rede` em "Formadores de Opinião" — nunca como
  veículo de imprensa, porque veículo de imprensa é candidato à lista de
  imprensa econômica da lente Mercado, e `deolhoemesteio` não é isso;
* a lista de investidores NÃO alcança perfil de rede, por construção;
* o perfil já cadastrado é RECONHECIDO na subida seguinte, e não recriado — o
  índice único é `(nome_normalizado, tipo)`, e procurar no tipo errado faria a
  segunda subida estourar;
* as quatro fontes antigas continuam cadastrando veículo, porque o padrão de
  `quem_fala` é `veiculo`;
* nada nasce sem autorização: o padrão de `ingerir` é não criar nada.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
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


CABECALHO = [
    "Data",
    "Autor",
    #: `Cargo` CONTINUA OBRIGATORIA na fonte, e por isso esta aqui: so `tema`,
    #: `link`, `titulo_texto`, `autor`, `uf` e `veiculo` sao opcionais.
    "Cargo",
    "Rede Social",
    "Estado",
    "Sentimento",
    "Unidades/Empresas",
    "Engajamento",
]


def _planilha_com_cargo(pares: list[tuple[str, str]]) -> bytes:
    """Uma planilha com o cargo de cada autor — e o cargo decide o público."""
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(CABECALHO)
    for indice, (autor, cargo) in enumerate(pares):
        aba.append(
            [
                date(2026, 8, 3 + indice),
                autor,
                cargo,
                "Instagram",
                "RS",
                "Negativo",
                "Corsan",
                10,
            ]
        )
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _planilha(autores: list[str]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(CABECALHO)
    for indice, autor in enumerate(autores):
        aba.append(
            [
                date(2026, 8, 3 + indice),
                autor,
                "Comunicador",
                "Instagram",
                "RS",
                "Negativo",
                "Corsan",
                10,
            ]
        )
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def test_o_perfil_NASCE_como_perfil_de_rede_e_nao_como_veiculo(sessao, bites):
    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(["deolhoemesteio zz1"]),
        veiculos_a_criar=("deolhoemesteio zz1",),
    )

    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("deolhoemesteio zz1")
        )
    )
    assert criado is not None
    assert criado.tipo == "perfil_rede"
    #: NA CATEGORIA QUE JÁ EXISTIA E ESTAVA VAZIA: "Formadores de Opinião".
    categoria = sessao.get(CategoriaPublico, criado.categoria_publico_id)
    assert categoria.nome == "Formadores de Opinião"
    #: E SEM SUBCATEGORIA: a lógica editorial é juízo humano, como nos veículos.
    assert criado.subcategoria_publico_id is None


def test_O_PUBLICO_DO_PERFIL_SAI_DO_CARGO(sessao, bites):
    """O que o dono do produto viu e reclamou.

    A primeira carga criou os 1.108 perfis todos como "Formadores de Opinião", e
    o vereador Iriel Sachet apareceu no cadastro classificado como formador de
    opinião. O cadastro TEM o vocabulário certo: a taxonomia de públicos prevê
    Poder Legislativo com Federal, Estadual e Municipal desde a `0036` — e a
    coluna `Cargo` da planilha diz qual é.
    """
    from app.banco.tabelas_catalogo import SubcategoriaPublico

    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha_com_cargo([("Iriel Sachet zz10", "Vereador")]),
        veiculos_a_criar=("Iriel Sachet zz10",),
    )

    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("Iriel Sachet zz10")
        )
    )
    categoria = sessao.get(CategoriaPublico, criado.categoria_publico_id)
    subcategoria = sessao.get(SubcategoriaPublico, criado.subcategoria_publico_id)
    assert categoria.nome == "Poder Legislativo"
    assert subcategoria.nome == "Municipal"


def test_a_grafia_FEMININA_do_cargo_cai_no_mesmo_publico(sessao, bites):
    #: "Vereadora" é o mesmo cargo que "Vereador" — a dobra de `CARGO_CANONICO`
    #: vale também para o público, porque o mapa é indexado pelo cargo
    #: canonizado.
    from app.banco.tabelas_catalogo import SubcategoriaPublico

    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha_com_cargo([("Alguma Vereadora zz13", "Vereadora")]),
        veiculos_a_criar=("Alguma Vereadora zz13",),
    )

    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("Alguma Vereadora zz13")
        )
    )
    assert sessao.get(SubcategoriaPublico, criado.subcategoria_publico_id).nome == "Municipal"


def test_o_cargo_DESCONHECIDO_deixa_o_perfil_sem_publico(sessao, bites):
    #: 2.249 das 2.886 linhas vêm sem cargo, e `político`, `partido` e `perfil
    #: de twitter` não têm par defensável na taxonomia. Chutar classificaria
    #: 2.249 anônimos como formadores de opinião — que é o defeito que isto
    #: conserta. Sem categoria é a verdade: "ainda não classificado".
    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha_com_cargo([("anonimo zz11", "")]),
        veiculos_a_criar=("anonimo zz11",),
    )

    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("anonimo zz11")
        )
    )
    assert criado.categoria_publico_id is None
    assert criado.subcategoria_publico_id is None


def test_a_conferencia_MOSTRA_O_CARGO_antes_de_criar(sessao, bites):
    #: Quem autoriza a criação de 1.108 perfis precisa ver "Iriel Sachet —
    #: Vereador", e não só o nome: é o cargo que decide onde ele entra.
    conteudo = _planilha_com_cargo([("Iriel Sachet zz12", "Vereadora")])

    _previsao, veiculos, _assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    assert veiculos.novos[0].cargo == "vereador"


def test_UM_CADASTRO_SO_o_perfil_reaproveita_o_veiculo(sessao, bites):
    """A decisão do dono do produto: um cadastro só, do Cadastro compartilhado.

    MEDIDO antes de decidir: "Valor Econômico" existia TRÊS vezes nesta base —
    como veículo (86 menções, na lista do Mercado) e como dois perfis de rede
    (2 e 11 menções, sem classificação). Treze menções do Valor não somavam com
    as 86, e nenhuma tela juntava. São 94 atores nessa situação.

    O CANAL NÃO SE PERDE: quem diz "foi em rede social" é a FONTE — `bites`
    alimenta a lente Sociedade digital, `clipei` a Imprensa. A instituição
    responde QUEM falou; a fonte responde ONDE.
    """
    from app.dominio.texto import normalizar as _n

    veiculo = Instituicao(
        nome="Valor Econômico zz20",
        nome_normalizado=_n("Valor Econômico zz20"),
        tipo="veiculo",
    )
    sessao.add(veiculo)
    sessao.flush()

    resumo = ingerir_mencoes.ingerir(
        sessao, bites, _planilha(["Valor Econômico zz20"])
    )

    assert resumo[0].veiculos_criados == 0
    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    #: A MENÇÃO DA REDE APONTA PARA O VEÍCULO — um cadastro só.
    assert gravada.instituicao_id == veiculo.id


def test_a_conferencia_nao_oferece_criar_quem_JA_EXISTE_em_outro_tipo(sessao, bites):
    from app.dominio.texto import normalizar as _n

    sessao.add(
        Instituicao(
            nome="InfoMoney zz21",
            nome_normalizado=_n("InfoMoney zz21"),
            tipo="veiculo",
        )
    )
    sessao.flush()

    _previsao, veiculos, _assuntos = ingerir_mencoes.conferir(
        sessao, bites, _planilha(["InfoMoney zz21"])
    )

    assert [novo.nome for novo in veiculos.novos] == []
    assert _n("InfoMoney zz21") in veiculos.cadastrados


def test_o_CLIPPING_nao_reaproveita_outro_tipo(sessao):
    """A direção em que a unificação NÃO vale.

    O `Veículo` do clipping é SEMPRE um meio de imprensa. Um nome igual ao de
    um órgão ali é HOMÔNIMO, não o mesmo ator — apontar a matéria do jornal
    para a prefeitura seria atribuição errada. A reutilização entre tipos vale
    na direção do perfil de rede, onde o Instagram do Valor É o Valor.
    """
    from app.casos_de_uso.veiculos_da_imprensa import reconhecer
    from app.dominio.texto import normalizar as _n

    sessao.add(
        Instituicao(
            nome="Homônimo zz22",
            nome_normalizado=_n("Homônimo zz22"),
            tipo="orgao",
        )
    )
    sessao.flush()

    reco = reconhecer(sessao, {"Homônimo zz22": {"mencoes": 1}}, "veiculo")

    assert [v.nome for v in reco.novos] == ["Homônimo zz22"]


def test_a_mencao_aponta_para_o_perfil(sessao, bites):
    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(["deolhoemesteio zz2"]),
        veiculos_a_criar=("deolhoemesteio zz2",),
    )

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("deolhoemesteio zz2")
        )
    )
    assert gravada.instituicao_id == criado.id
    assert gravada.veiculo == "deolhoemesteio zz2"


def test_a_LISTA_DE_INVESTIDORES_nao_alcanca_perfil_de_rede(sessao, bites):
    """A proteção que justifica o tipo separado.

    A lente Mercado se recorta pela lista de veículos de investidores, e a rota
    que mantém a lista filtra `tipo='veiculo'`. Se o perfil nascesse como
    veículo da Imprensa, `deolhoemesteio` seria candidato a veículo de
    investidor — e um dia alguém o marcaria por engano.
    """
    from app.casos_de_uso.veiculos_da_imprensa import LISTAS_DE_VEICULOS, nomes_da_lista

    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(["perfil de investidor zz3"]),
        veiculos_a_criar=("perfil de investidor zz3",),
    )
    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("perfil de investidor zz3")
        )
    )
    #: Mesmo marcado à mão com a subcategoria do mercado, ele não entra: a
    #: lista é de veículo.
    from app.banco.tabelas_catalogo import SubcategoriaPublico

    categoria, subcategoria = LISTAS_DE_VEICULOS["imprensa_economica"]
    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(CategoriaPublico.nome == categoria, SubcategoriaPublico.nome == subcategoria)
    )
    criado.subcategoria_publico_id = alvo
    sessao.flush()

    assert normalizar("perfil de investidor zz3") not in nomes_da_lista(
        sessao, "imprensa_economica"
    )


def test_o_perfil_JA_CADASTRADO_e_reconhecido_e_nao_recriado(sessao, bites):
    #: O índice único é `(nome_normalizado, tipo)`. Procurar no tipo errado
    #: faria a segunda subida tentar criar de novo e estourar.
    conteudo = _planilha(["deolhoemesteio zz4"])
    ingerir_mencoes.ingerir(
        sessao, bites, conteudo, veiculos_a_criar=("deolhoemesteio zz4",)
    )

    previsao, veiculos, _assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    assert [novo.nome for novo in veiculos.novos] == []
    assert normalizar("deolhoemesteio zz4") in veiculos.cadastrados


def test_sem_autorizacao_nada_nasce(sessao, bites):
    resumo = ingerir_mencoes.ingerir(sessao, bites, _planilha(["ninguem zz5"]))

    assert resumo[0].ingeridas == 1
    assert resumo[0].veiculos_criados == 0
    assert (
        sessao.scalar(
            select(Instituicao).where(
                Instituicao.nome_normalizado == normalizar("ninguem zz5")
            )
        )
        is None
    )


def test_a_conferencia_lista_os_perfis_que_nasceriam(sessao, bites):
    conteudo = _planilha(["um zz6", "outro zz6", "um zz6"])

    _previsao, veiculos, _assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    por_nome = {novo.nome: novo for novo in veiculos.novos}
    assert por_nome["um zz6"].mencoes == 2
    assert por_nome["outro zz6"].mencoes == 1
    #: A PRAÇA COMO O FORNECEDOR A MANDA, e a Bites manda sigla. A Clipei
    #: manda nome por extenso na mesma posição — a conferência mostra o texto
    #: dele, sem traduzir, porque é o que a pessoa vai reconhecer ao conferir
    #: contra a planilha aberta ao lado.
    assert por_nome["um zz6"].uf == "RS"
