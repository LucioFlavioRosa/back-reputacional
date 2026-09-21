"""`derivar_frente`: área interna → Interna; Evento → Eventos, direto;
senão, a categoria de público da instituição decide — via
`categoria_publico.frente_padrao_id` (0039).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, FormatoInteracao
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso.derivar_frente import derivar_frente
from app.dominio.erros import RegraViolada
from app.dominio.frentes import Frente
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


def _categoria_id(sessao: Session, codigo: str) -> int:
    return sessao.scalar(select(CategoriaPublico.id).where(CategoriaPublico.codigo == codigo))


def _formato_id(sessao: Session, codigo: str) -> int:
    return sessao.scalar(select(FormatoInteracao.id).where(FormatoInteracao.codigo == codigo))


def _instituicao(
    sessao: Session, *, tipo: str, categoria_publico_id: int | None = None
) -> Instituicao:
    instituicao = Instituicao(
        nome="Instituição de teste", nome_normalizado="instituicao de teste",
        tipo=tipo, categoria_publico_id=categoria_publico_id,
    )
    sessao.add(instituicao)
    sessao.flush()
    return instituicao


def test_area_interna_vira_sempre_interna_mesmo_sem_categoria(sessao):
    interna = _instituicao(sessao, tipo="area_interna")
    assert derivar_frente(
        sessao, instituicao_id=interna.id, formato_interacao_id=None
    ) == Frente.INTERNA


def test_formato_evento_vira_sempre_eventos_qualquer_categoria(sessao):
    categoria = _categoria_id(sessao, "imprensa_formadores_opiniao")
    instituicao = _instituicao(sessao, tipo="veiculo", categoria_publico_id=categoria)
    evento = _formato_id(sessao, "evento")
    assert derivar_frente(
        sessao, instituicao_id=instituicao.id, formato_interacao_id=evento
    ) == Frente.EVENTOS


@pytest.mark.parametrize(
    "codigo_categoria,frente_esperada",
    [
        ("poder_executivo", Frente.GOVERNO),
        ("poder_legislativo", Frente.GOVERNO),  # não vira `legislativo` — ver a migration
        ("poder_judiciario", Frente.GOVERNO),
        ("controle_fiscalizacao", Frente.GOVERNO),
        ("reguladores", Frente.GOVERNO),
        ("mercado_financeiro_capitais", Frente.INVESTIDORES),
        ("imprensa_formadores_opiniao", Frente.IMPRENSA),
        ("entidades_setoriais_representativas", Frente.PARCEIROS),
        ("sociedade_civil_comunidade", Frente.PARCEIROS),
        ("parceiros_cadeia_valor", Frente.PARCEIROS),
    ],
)
def test_categoria_publico_decide_a_frente(sessao, codigo_categoria, frente_esperada):
    categoria = _categoria_id(sessao, codigo_categoria)
    instituicao = _instituicao(sessao, tipo="orgao", categoria_publico_id=categoria)
    reuniao = _formato_id(sessao, "reuniao")
    assert (
        derivar_frente(sessao, instituicao_id=instituicao.id, formato_interacao_id=reuniao)
        == frente_esperada
    )


def test_instituicao_sem_categoria_recusa_com_regra_violada(sessao):
    instituicao = _instituicao(sessao, tipo="orgao", categoria_publico_id=None)
    with pytest.raises(RegraViolada, match="categoria de público"):
        derivar_frente(sessao, instituicao_id=instituicao.id, formato_interacao_id=None)


def test_instituicao_inexistente_recusa_com_regra_violada(sessao):
    import uuid

    with pytest.raises(RegraViolada):
        derivar_frente(sessao, instituicao_id=uuid.uuid4(), formato_interacao_id=None)
