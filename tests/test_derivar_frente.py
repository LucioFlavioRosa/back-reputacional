"""`derivar_frente`: o TIPO da instituição decide sozinho, em todos os casos
menos "entidade" — ali quem decide entre Parceiros e Eventos é o Formato.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import FormatoInteracao
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


def _formato_id(sessao: Session, codigo: str) -> int:
    return sessao.scalar(select(FormatoInteracao.id).where(FormatoInteracao.codigo == codigo))


def _instituicao(sessao: Session, *, tipo: str) -> Instituicao:
    instituicao = Instituicao(
        nome="Instituição de teste",
        nome_normalizado="instituicao de teste",
        tipo=tipo,
    )
    sessao.add(instituicao)
    sessao.flush()
    return instituicao


@pytest.mark.parametrize(
    "tipo,frente_esperada",
    [
        ("area_interna", Frente.INTERNA),
        ("veiculo", Frente.IMPRENSA),
        ("orgao", Frente.GOVERNO),
        ("investidor", Frente.INVESTIDORES),
        ("proposicao", Frente.LEGISLATIVO),
        ("credor", Frente.BANCOS_CREDORES),
    ],
)
def test_tipo_da_instituicao_decide_sozinho(sessao, tipo, frente_esperada):
    instituicao = _instituicao(sessao, tipo=tipo)
    assert (
        derivar_frente(sessao, instituicao_id=instituicao.id, formato_interacao_id=None)
        == frente_esperada
    )


def test_entidade_com_formato_evento_vira_eventos(sessao):
    instituicao = _instituicao(sessao, tipo="entidade")
    evento = _formato_id(sessao, "evento")
    assert (
        derivar_frente(sessao, instituicao_id=instituicao.id, formato_interacao_id=evento)
        == Frente.EVENTOS
    )


def test_entidade_com_outro_formato_vira_parceiros(sessao):
    instituicao = _instituicao(sessao, tipo="entidade")
    reuniao = _formato_id(sessao, "reuniao")
    assert (
        derivar_frente(sessao, instituicao_id=instituicao.id, formato_interacao_id=reuniao)
        == Frente.PARCEIROS
    )


def test_entidade_sem_formato_vira_parceiros(sessao):
    instituicao = _instituicao(sessao, tipo="entidade")
    assert (
        derivar_frente(sessao, instituicao_id=instituicao.id, formato_interacao_id=None)
        == Frente.PARCEIROS
    )


def test_instituicao_inexistente_recusa_com_regra_violada(sessao):
    with pytest.raises(RegraViolada):
        derivar_frente(sessao, instituicao_id=uuid.uuid4(), formato_interacao_id=None)
