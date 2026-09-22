"""`derivar_tipo`: a regra em três passos, testada pela interface — sem HTTP.

Espelha `test_derivar_frente`: os casos de API em `test_e2e_postgres` continuam
provando o contrato de fora; aqui é a regra em si, com o banco de teste só
para a categoria existir.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico
from app.casos_de_uso.derivar_tipo import derivar_tipo
from app.dominio.erros import RegraViolada

# Reaproveita o banco de teste que `test_e2e_postgres` cria e migra.
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


def _categoria(sessao, codigo: str) -> int:
    return sessao.scalar(select(CategoriaPublico.id).where(CategoriaPublico.codigo == codigo))


def test_tipo_informado_vale_mais_que_a_categoria(sessao):
    mercado = _categoria(sessao, "mercado_financeiro_capitais")
    assert derivar_tipo(sessao, tipo="credor", categoria_publico_id=mercado, atual=None) == "credor"


def test_tipo_informado_invalido_e_recusado(sessao):
    with pytest.raises(RegraViolada, match="Tipo invalido"):
        derivar_tipo(sessao, tipo="banco", categoria_publico_id=None, atual=None)


def test_sem_tipo_a_categoria_decide(sessao):
    imprensa = _categoria(sessao, "imprensa_formadores_opiniao")
    assert derivar_tipo(sessao, tipo=None, categoria_publico_id=imprensa, atual=None) == "veiculo"


def test_na_edicao_sem_tipo_nem_categoria_o_gravado_fica(sessao):
    derivado = derivar_tipo(sessao, tipo=None, categoria_publico_id=None, atual="proposicao")
    assert derivado == "proposicao"


def test_na_criacao_sem_tipo_nem_categoria_e_recusado(sessao):
    with pytest.raises(RegraViolada, match="categoria de publico"):
        derivar_tipo(sessao, tipo=None, categoria_publico_id=None, atual=None)
