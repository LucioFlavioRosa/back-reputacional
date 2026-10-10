"""O handle do perfil perde o @, e os duplicados se fundem.

O QUE ACONTECEU. A primeira carga da Bites criou 1.167 perfis a partir da
coluna `Autor`, e o fornecedor escreve o mesmo perfil das duas formas:
`@casadevovodede` com 33 menções e `casadevovodede` com 32 são o MESMO perfil.
Medido no arquivo de 01–09/2026: 568 dos 1.173 autores vêm com @, e 59 deles
têm o gêmeo sem @ na mesma planilha. O dossiê somava os dois lados separados, e
o Cadastro compartilhado mostrava duas linhas para um perfil.

O QUE ESTES TESTES PROTEGEM:

* o @ sai na leitura, e o nome gravado é o que o cadastro usa;
* a mesma canonização vale na CONFERÊNCIA: se a tela listasse pela célula crua,
  prometeria dois perfis e o banco gravaria um;
* SÓ onde quem fala é perfil. No clipping, quem fala é veículo de imprensa e o
  nome não tem @ — aplicar a regra lá mexeria em 25.457 vínculos que funcionam;
* célula que é só "@" não cria instituição de nome vazio.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
from app.dominio.ingestao_score import Mapeamento, quem_falou
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


@pytest.fixture
def clipei(sessao) -> ScoreFonte:
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert fonte is not None
    return fonte


#: O MAPEAMENTO DA BITES, para comparar o que a ingestão procuraria.
MAPEAMENTO_DA_BITES = Mapeamento.de_json(
    {"colunas": {"data": "Data", "sentimento": "Sentimento"}, "quem_fala": "perfil_rede"}
)

CABECALHO = [
    "Data",
    "Autor",
    "Cargo",
    "Sentimento",
    "Unidades/Empresas",
    "Engajamento",
]


def _planilha(autores: list[str]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(CABECALHO)
    for indice, autor in enumerate(autores):
        aba.append([date(2026, 8, 3 + indice), autor, "Comunicador", "Negativo", "Corsan", 1])
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


# -- o motor ---------------------------------------------------------------------


def test_o_arroba_sai_quando_quem_fala_e_perfil(bites):
    mapeamento = Mapeamento.de_json(bites.mapeamento_colunas)

    assert quem_falou("@casadevovodede", mapeamento) == "casadevovodede"
    assert quem_falou("casadevovodede", mapeamento) == "casadevovodede"
    #: A CAIXA NÃO É TOCADA: quem resolve caixa é `normalizar`, na comparação.
    #: O que se grava é o nome como o fornecedor escreveu, menos o @.
    assert quem_falou("@Stela Farias", mapeamento) == "Stela Farias"


def test_o_arroba_NAO_sai_no_clipping(clipei):
    #: No clipping, quem fala é veículo de imprensa. Aplicar a regra lá mexeria
    #: em 25.457 vínculos que já funcionam por uma regra que não é deles.
    mapeamento = Mapeamento.de_json(clipei.mapeamento_colunas)

    assert quem_falou("@algum veiculo", mapeamento) == "@algum veiculo"


def test_celula_que_e_SO_ARROBA_nao_vira_nome_vazio(bites):
    mapeamento = Mapeamento.de_json(bites.mapeamento_colunas)

    assert quem_falou("@", mapeamento) is None


# -- a subida e a conferência ----------------------------------------------------


def test_os_DOIS_JEITOS_viram_UM_perfil_na_subida(sessao, bites):
    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(["@casadevovodede zz1", "casadevovodede zz1"]),
        veiculos_a_criar=("casadevovodede zz1",),
    )

    quantos = sessao.scalar(
        select(func.count())
        .select_from(Instituicao)
        .where(Instituicao.nome_normalizado == normalizar("casadevovodede zz1"))
    )
    assert quantos == 1
    #: E AS DUAS MENÇÕES APONTAM PARA ELE.
    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("casadevovodede zz1")
        )
    )
    ligadas = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.instituicao_id == criado.id)
    )
    assert ligadas == 2


def test_a_conferencia_lista_UM_perfil_para_os_dois_jeitos(sessao, bites):
    #: Se a tela listasse pela célula crua, prometeria dois perfis a cadastrar e
    #: o banco gravaria um — a conferência existe para prometer o que acontece.
    conteudo = _planilha(["@casadevovodede zz2", "casadevovodede zz2"])

    _previsao, veiculos, _assuntos = ingerir_mencoes.conferir(sessao, bites, conteudo)

    nomes = [novo.nome for novo in veiculos.novos]
    assert nomes == ["casadevovodede zz2"]
    assert veiculos.novos[0].mencoes == 2


def test_a_mencao_guarda_o_nome_SEM_o_arroba(sessao, bites):
    ingerir_mencoes.ingerir(sessao, bites, _planilha(["@deolhoemesteio zz3"]))

    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.veiculo == "deolhoemesteio zz3"


# -- a migration que consertou o que já estava gravado ---------------------------


def test_a_0071_FUNDE_o_par_e_preserva_as_mencoes(sessao, bites):
    """A migration rodada de verdade, sobre duas linhas criadas aqui.

    ACHADO DE REVISÃO: os dois testes que havia aqui liam o banco de teste —
    que é criado do zero pelas migrations e NÃO tem perfil de rede nenhum. As
    asserções eram `0 == 0` e `[] == []`: afirmavam provar a fusão de 59 grupos
    e o rename de 509 linhas, e passariam com a `0072` apagada do repositório.

    Aqui o par `@x`/`x` é criado na sessão, com uma menção em cada lado, e o
    SQL da migration é executado. O que se afirma é o que ela faz: o lado com
    arroba sai, as menções dele passam para o canônico, e nada se perde.
    """
    from pathlib import Path

    canonico = Instituicao(
        nome="casadevovodede zz40",
        nome_normalizado=normalizar("casadevovodede zz40"),
        tipo="perfil_rede",
    )
    com_arroba = Instituicao(
        nome="@casadevovodede zz40",
        nome_normalizado=normalizar("@casadevovodede zz40"),
        tipo="perfil_rede",
    )
    sessao.add_all([canonico, com_arroba])
    sessao.flush()
    for dono in (canonico, com_arroba):
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=date(2026, 8, 1),
                data=date(2026, 8, 3),
                sentimento="neg",
                veiculo=dono.nome,
                instituicao_id=dono.id,
            )
        )
    sessao.flush()

    sql = (
        Path(__file__).resolve().parents[1]
        / "app/banco/migrations/0072_o_handle_do_perfil_sem_arroba.sql"
    ).read_text(encoding="utf-8")
    #: SEM O `begin`/`commit` da migration: o teste já roda dentro de uma
    #: transação que o fixture desfaz no fim.
    id_do_canonico, id_com_arroba = canonico.id, com_arroba.id
    sessao.execute(text(sql.replace("begin;", "").replace("commit;", "")))
    sessao.expire_all()

    #: POR CONTAGEM, e não por `sessao.get`: o objeto está no identity map, e
    #: `get` de uma linha que o SQL apagou levanta `ObjectDeletedError` em vez
    #: de devolver None — o teste falharia afirmando exatamente o que provou.
    def quantas(qual):
        return sessao.scalar(
            select(func.count()).select_from(Instituicao).where(Instituicao.id == qual)
        )

    assert quantas(id_com_arroba) == 0
    assert quantas(id_do_canonico) == 1
    ligadas = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.instituicao_id == id_do_canonico)
    )
    assert ligadas == 2


def test_a_0071_RENOMEIA_quem_tem_arroba_e_nao_tem_gemeo(sessao):
    from pathlib import Path

    sozinho = Instituicao(
        nome="@rjempregos2 zz41",
        nome_normalizado=normalizar("@rjempregos2 zz41"),
        tipo="perfil_rede",
    )
    sessao.add(sozinho)
    sessao.flush()

    sql = (
        Path(__file__).resolve().parents[1]
        / "app/banco/migrations/0072_o_handle_do_perfil_sem_arroba.sql"
    ).read_text(encoding="utf-8")
    sessao.execute(text(sql.replace("begin;", "").replace("commit;", "")))
    sessao.expire_all()

    renomeado = sessao.get(Instituicao, sozinho.id)
    assert renomeado.nome == "rjempregos2 zz41"
    assert renomeado.nome_normalizado == normalizar("rjempregos2 zz41")


def test_a_0071_trata_ARROBA_COM_ESPACO(sessao):
    """O achado de revisão sobre o `btrim`.

    `quem_falou` faz `lstrip('@').strip()`. A migration fazia só
    `ltrim(nome,'@')`: a célula `@ nome` ficava com um espaço à frente no
    normalizado — uma forma que `normalizar()` nunca produz —, o gêmeo não
    fundia, a verificação final não notava, e a próxima subida criava outro
    perfil. Era o defeito que a migration existe para eliminar, voltando pela
    porta de trás.
    """
    from pathlib import Path

    torto = Instituicao(
        nome="@ comespaco zz42",
        nome_normalizado="@ comespaco zz42",
        tipo="perfil_rede",
    )
    sessao.add(torto)
    sessao.flush()

    sql = (
        Path(__file__).resolve().parents[1]
        / "app/banco/migrations/0072_o_handle_do_perfil_sem_arroba.sql"
    ).read_text(encoding="utf-8")
    sessao.execute(text(sql.replace("begin;", "").replace("commit;", "")))
    sessao.expire_all()

    arrumado = sessao.get(Instituicao, torto.id)
    assert arrumado.nome_normalizado == "comespaco zz42"
    #: E O QUE A INGESTÃO VAI PROCURAR na próxima subida casa com isto.
    assert normalizar(quem_falou("@ comespaco zz42", MAPEAMENTO_DA_BITES)) == (
        arrumado.nome_normalizado
    )
