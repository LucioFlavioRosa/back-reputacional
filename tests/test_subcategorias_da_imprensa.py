"""As subcategorias de público da Imprensa — a linha editorial do veículo.

O PEDIDO: "dentro da Categoria de público temos Imprensa e na subcategoria
temos que adicionar uma nova opção Institucional" (20/10/2026, migration 0106).

O QUE ESTES TESTES PROTEGEM, e são três coisas diferentes:

1. que a opção EXISTA no banco, no fim da lista — este dicionário só muda por
   migration (é o que `api/dicionarios` declara para esta tabela);
2. que ela CHEGUE À TELA por `/api/dicionarios`, que é de onde todo seletor do
   front tira as opções ("o front NÃO deve ter lista fixa de nenhum deles").
   Achado de revisão: o primeiro teste olhava só o ORM, e passaria mesmo se a
   rota deixasse de expor a subcategoria — ele provava o `insert`, não o pedido;
3. que o PAR DA LENTE MERCADO continue um só. O recorte do Mercado é o par
   (Imprensa, "Econômica e de negócios"), casado PELO NOME em `api/score.py` e
   em `veiculos_da_imprensa` — então acrescentar irmã nesta categoria é
   exatamente o tipo de mudança que poderia tornar aquele casamento ambíguo. É
   a conferência que vale a migration, e não a de que a linha existe.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: A lista como a tela a mostra: só as ativas, na ordem do cadastro. As quatro
#: primeiras vêm da `0061`, na ordem da planilha de referência; "Institucional"
#: entra no fim justamente para não mexer em nenhuma delas.
ESPERADAS = [
    "Econômica e de negócios",
    "Geral nacional",
    "Regional das concessões",
    "Municipal / local",
    "Institucional",
]


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
def cliente(sessao):
    from fastapi.testclient import TestClient

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _da_imprensa():
    return (
        select(SubcategoriaPublico)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(CategoriaPublico.codigo == "imprensa")
    )


def test_INSTITUCIONAL_e_uma_opcao_da_imprensa(sessao):
    ativas = sessao.scalars(
        _da_imprensa()
        .where(SubcategoriaPublico.ativo.is_(True))
        .order_by(SubcategoriaPublico.ordem)
    ).all()

    assert [s.nome for s in ativas] == ESPERADAS
    #: PELO CÓDIGO TAMBÉM, que é a chave estável: o nome é rótulo de tela e já
    #: mudou duas vezes neste banco (ver o clima, 0030/0047/0105).
    institucional = next(s for s in ativas if s.codigo == "institucional")
    assert institucional.nome == "Institucional"
    assert institucional.ativo is True
    #: NO FIM, PELO NÚMERO e não só pela posição na lista: `ordem` é o que a
    #: rota usa para ordenar, e as quatro de antes não podem ter se mexido.
    assert institucional.ordem == 5
    #: E AS CINCO ORDENS SÃO DISTINTAS, que é a premissa silenciosa da asserção
    #: de cima — ACHADO DA SEGUNDA REVISÃO. Não há unicidade em
    #: (categoria_publico_id, ordem): só (categoria_publico_id, codigo). Com
    #: duas linhas na mesma `ordem`, a lista acima passaria ou não conforme a
    #: ordem FÍSICA do banco, e eu estaria afirmando uma posição que o esquema
    #: não garante. A rota agora desempata pelo `id`, mas empate em `ordem`
    #: continua sendo um erro de semeadura — e é aqui que ele aparece.
    assert len({s.ordem for s in ativas}) == len(ativas)


def test_INSTITUCIONAL_chega_na_TELA_pelos_dicionarios(cliente, sessao):
    """A opção não serve de nada no banco se o seletor não a recebe.

    ACHADO DE REVISÃO: o teste de cima olha o ORM, então passaria mesmo se a
    rota deixasse de expor esta tabela — e é a rota que alimenta o formulário do
    Cadastro de Instituições. `/api/dicionarios` devolve só os ativos, por
    `ordem`, e é de propósito que uma linha nova apareça na próxima carga da
    tela sem build nem deploy do front.
    """
    da_imprensa = sessao.scalar(
        select(CategoriaPublico.id).where(CategoriaPublico.codigo == "imprensa")
    )

    resposta = cliente.get("/api/dicionarios")
    assert resposta.status_code == 200
    todas = resposta.json()["subcategorias_publico"]

    desta = [s for s in todas if s["categoria_publico_id"] == da_imprensa]
    assert [s["nome"] for s in desta] == ESPERADAS
    assert next(s for s in desta if s["codigo"] == "institucional")["ordem"] == 5


def test_o_par_da_lente_MERCADO_continua_um_so(sessao):
    """A conferência que vale a migration.

    `api/score.py` e `veiculos_da_imprensa` acham a subcategoria do Mercado pelo
    PAR DE NOMES. Uma segunda linha que casasse com esse par faria a rota
    escolher pelo `order_by(id).limit(1)` — a menor id, que pode ser a errada —
    e faria `nomes_da_lista` unir os veículos das duas. Qual veículo entra na
    lente passaria a depender do banco, não do código.

    SEM FILTRAR `ativo`, E É ACHADO DE REVISÃO: a minha primeira versão contava
    só as ativas, e nenhum dos dois consumidores filtra `ativo` neste par. Uma
    aposentadoria futura que trocasse `economica_negocios` por outro código com
    o MESMO nome passaria pelo teste de antes e deixaria a rota escolhendo a
    linha aposentada — por ser a de menor id. O teste agora mede exatamente o
    que eles medem.

    HOJE ISSO DÁ 1, e a razão é a `0061`: a "Econômica e de negócios" antiga
    continua no banco, inativa, mas sob a categoria APOSENTADA — cujo nome é
    "Imprensa e Formadores de Opinião". É o nome da CATEGORIA que a separa
    deste par, não o `ativo` dela.
    """
    quantas = sessao.scalar(
        select(func.count())
        .select_from(SubcategoriaPublico)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            CategoriaPublico.nome == "Imprensa",
            SubcategoriaPublico.nome == "Econômica e de negócios",
        )
    )

    assert quantas == 1
