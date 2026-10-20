"""As subcategorias de público da Imprensa — a linha editorial do veículo.

O PEDIDO: "dentro da Categoria de público temos Imprensa e na subcategoria
temos que adicionar uma nova opção Institucional" (20/10/2026, migration 0106).

O QUE ESTES TESTES PROTEGEM, e são duas coisas diferentes:

1. que a opção EXISTA e apareça na lista, no fim dela — este dicionário só muda
   por migration (é o que `api/dicionarios` declara para esta tabela), então a
   lista da tela é exatamente o que o banco semeou;
2. que o PAR DA LENTE MERCADO continue um só. O recorte do Mercado é o par
   (Imprensa, "Econômica e de negócios"), casado PELO NOME em `api/score.py` e
   em `veiculos_da_imprensa` — então acrescentar irmã nesta categoria é
   exatamente o tipo de mudança que poderia tornar aquele casamento ambíguo. É
   a conferência que vale a migration, e não a de que a linha existe.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
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


def test_o_par_da_lente_MERCADO_continua_um_so(sessao):
    """A conferência que vale a migration.

    `api/score.py` e `veiculos_da_imprensa` acham a subcategoria do Mercado pelo
    PAR de NOMES. Uma segunda linha que casasse com esse par faria o `scalar()`
    deles devolver uma das duas — e qual delas depende do banco, não do código.
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
            SubcategoriaPublico.ativo.is_(True),
        )
    )

    assert quantas == 1
