"""`aplicar_sugestoes`: só confiança alta vira gravação; confiança baixa
fica `null`, do jeito que já estava.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sugerir_categoria_de_publico import aplicar_sugestoes, gerar_sugestoes
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao
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


def _criar_instituicao(sessao: Session, *, nome: str, tipo: str) -> Instituicao:
    instituicao = Instituicao(nome=nome, nome_normalizado=nome.lower(), tipo=tipo)
    sessao.add(instituicao)
    sessao.flush()
    return instituicao


def test_confianca_alta_nas_duas_grava_categoria_e_subcategoria(sessao):
    # "Instituto" bate a palavra-chave de Entidades Setoriais — as duas
    # confianças (categoria e subcategoria) saem altas da mesma regra.
    instituto = _criar_instituicao(
        sessao, nome="Instituto Brasileiro de Governança", tipo="entidade"
    )

    resultado = aplicar_sugestoes(sessao, gerar_sugestoes(sessao))

    categoria = sessao.scalars(
        select(CategoriaPublico).where(
            CategoriaPublico.codigo == "entidades_setoriais_representativas"
        )
    ).one()
    subcategoria = sessao.scalars(
        select(SubcategoriaPublico).where(
            SubcategoriaPublico.categoria_publico_id == categoria.id,
            SubcategoriaPublico.codigo == "institutos_e_associacoes",
        )
    ).one()

    sessao.refresh(instituto)
    assert instituto.categoria_publico_id == categoria.id
    assert instituto.subcategoria_publico_id == subcategoria.id
    assert resultado["categoria"] >= 1
    assert resultado["subcategoria"] >= 1


def test_confianca_baixa_nao_grava_nada(sessao):
    # `tipo="area_interna"` sempre devolve (None, "baixa", None, "baixa") —
    # não é público externo, não há o que sugerir.
    area = _criar_instituicao(sessao, nome="Comunicação Interna", tipo="area_interna")

    aplicar_sugestoes(sessao, gerar_sugestoes(sessao))

    sessao.refresh(area)
    assert area.categoria_publico_id is None
    assert area.subcategoria_publico_id is None


def test_categoria_alta_com_subcategoria_baixa_grava_so_a_categoria(sessao):
    # `tipo="veiculo"` acerta a categoria (alta) sem dizer qual linha
    # editorial é (subcategoria baixa) — só a categoria deve ser gravada.
    veiculo = _criar_instituicao(sessao, nome="Um Jornal Qualquer", tipo="veiculo")

    aplicar_sugestoes(sessao, gerar_sugestoes(sessao))

    categoria = sessao.scalars(
        select(CategoriaPublico).where(CategoriaPublico.codigo == "imprensa_formadores_opiniao")
    ).one()

    sessao.refresh(veiculo)
    assert veiculo.categoria_publico_id == categoria.id
    assert veiculo.subcategoria_publico_id is None


def test_instituicao_ja_classificada_nao_entra_na_planilha_nem_e_regravada(sessao):
    veiculo = _criar_instituicao(sessao, nome="Outro Jornal", tipo="veiculo")
    categoria_diferente = sessao.scalars(
        select(CategoriaPublico).where(CategoriaPublico.codigo == "poder_executivo")
    ).one()
    veiculo.categoria_publico_id = categoria_diferente.id
    sessao.flush()

    aplicar_sugestoes(sessao, gerar_sugestoes(sessao))

    sessao.refresh(veiculo)
    # `gerar_sugestoes` já filtra quem tem categoria — a classificação manual
    # (ainda que "errada" pela heurística) não é sobrescrita.
    assert veiculo.categoria_publico_id == categoria_diferente.id
