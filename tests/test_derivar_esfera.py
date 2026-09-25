"""`derivar_esfera`: a esfera da interação é a da INSTITUIÇÃO com quem se falou.

O IRMÃO DE `derivar_frente`, e nasceu pelo mesmo motivo. O campo "Esfera" saiu
do formulário de cadastro e quatro telas continuaram lendo `interacao.esfera_id`
— o ranking "Esfera e abrangência", a coluna da Base, a linha da Ficha e o
filtro do recorte. Sem derivação, toda agenda criada a partir dali nascia com o
campo nulo, caía em "—" nas quatro, e não havia tela em lugar nenhum que
corrigisse.

DERIVAR EM VEZ DE DEVOLVER O CAMPO foi a escolha de quem cuida do produto, e é
a única das três saídas em que o dado não pode divergir da instituição: uma
agenda com o Ministério das Cidades é federal porque o Ministério é federal, e
não porque alguém marcou certo no formulário.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Esfera
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso.derivar_esfera import derivar_esfera
from app.dominio.erros import RegraViolada
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


def _esfera_id(sessao: Session, codigo: str) -> int:
    return sessao.scalar(select(Esfera.id).where(Esfera.codigo == codigo))


def _instituicao(sessao: Session, *, esfera_id: int | None) -> Instituicao:
    instituicao = Instituicao(
        nome="Instituição de teste",
        nome_normalizado="instituicao de teste",
        tipo="orgao",
        esfera_id=esfera_id,
    )
    sessao.add(instituicao)
    sessao.flush()
    return instituicao


def test_a_esfera_vem_da_instituicao(sessao):
    federal = _esfera_id(sessao, "federal")
    instituicao = _instituicao(sessao, esfera_id=federal)

    assert derivar_esfera(sessao, instituicao_id=instituicao.id) == federal


def test_instituicao_sem_esfera_cadastrada_devolve_nulo(sessao):
    """NULO É RESPOSTA, e não erro.

    A instituição que ninguém classificou existe, e recusar a agenda por causa
    dela seria bloquear o registro de quem não errou nada. O "—" nas telas é o
    retrato honesto de um cadastro incompleto — e o lugar de corrigir é o
    cadastro da instituição, que é justamente o ganho de derivar.
    """
    instituicao = _instituicao(sessao, esfera_id=None)

    assert derivar_esfera(sessao, instituicao_id=instituicao.id) is None


def test_instituicao_inexistente_recusa_com_regra_violada(sessao):
    """O mesmo contrato de `derivar_frente`: id que não existe é erro de domínio.

    Devolver `None` aqui confundiria "a instituição não tem esfera" com "a
    instituição não existe" — a primeira é um cadastro a completar, a segunda é
    um payload inválido.
    """
    with pytest.raises(RegraViolada):
        derivar_esfera(sessao, instituicao_id=uuid.uuid4())
