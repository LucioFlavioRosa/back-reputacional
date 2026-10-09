"""O recorte das lentes pela taxonomia de temas do CRM: Pilar (N1), Tema
estratégico (N2) e Subtema (N3).

A menção entra pelo tema do cadastro a que está ligada (`tema_id`); a que só
traz o texto do fornecedor não entra em nenhum dos três — e as opções do mês
não os oferecem enquanto não houver menção ligada.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.banco.repositorio_lentes import opcoes_de_filtro
from app.banco.repositorio_score import condicoes_do_filtro
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte
from app.dominio.score import FiltroDeMencoes
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)
MES = date(2026, 6, 1)


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
def ligadas(sessao):
    """Três menções da Sociedade: duas ligadas a temas de PILARES diferentes, e uma
    só com o texto do fornecedor."""
    (a, n2_a, n1_a), (b, n2_b, n1_b) = sessao.execute(
        text(
            """
            select distinct on (b.id) t.id, m.nome, b.nome
            from tema t
            join macro_tema m on m.id = t.macro_tema_id
            join bloco_tema b on b.id = m.bloco_tema_id
            where t.ativo
            order by b.id, t.id
            limit 2
            """
        )
    ).all()
    nome = lambda id_: sessao.scalar(text("select nome from tema where id = :i"), {"i": id_})  # noqa: E731
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    for tema_id in (a, b, None):
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=MES,
                sentimento="neg",
                tema_id=tema_id,
                tema_texto="Texto do fornecedor",
            )
        )
    sessao.flush()
    return {
        "lente_id": bites.lente_id,
        "n3": (nome(a), nome(b)),
        "n2": (n2_a, n2_b),
        "n1": (n1_a, n1_b),
    }


def _quantas(sessao, lente_id: int, **filtro) -> int:
    consulta = (
        select(func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(ScoreFonte.lente_id == lente_id, Mencao.mes == MES)
        .where(*condicoes_do_filtro(FiltroDeMencoes(**filtro)))
    )
    return sessao.scalar(consulta)


def test_cada_nivel_filtra_pelas_mencoes_ligadas(sessao, ligadas):
    lente = ligadas["lente_id"]
    assert _quantas(sessao, lente) == 3
    assert _quantas(sessao, lente, tema_n1=ligadas["n1"][0]) == 1
    assert _quantas(sessao, lente, tema_n2=ligadas["n2"][1]) == 1
    assert _quantas(sessao, lente, tema_n3=ligadas["n3"][0]) == 1


def test_niveis_juntos_estreitam(sessao, ligadas):
    lente = ligadas["lente_id"]
    # Pilar de uma menção e tema estratégico da outra: nenhuma tem os dois.
    assert _quantas(sessao, lente, tema_n1=ligadas["n1"][0], tema_n2=ligadas["n2"][1]) == 0
    assert _quantas(sessao, lente, tema_n1=ligadas["n1"][1], tema_n2=ligadas["n2"][1]) == 1


def test_as_opcoes_n3_sao_as_que_as_mencoes_alcancam_e_n1_n2_a_taxonomia_inteira(sessao, ligadas):
    opcoes = opcoes_de_filtro(sessao, ligadas["lente_id"], MES)
    # Pilar e tema estratégico são filtros rápidos fixos: a taxonomia inteira.
    # Os 7 pilares e, depois deles, o tema que o fornecedor escreveu (que é N1).
    assert set(opcoes["temas_n1"]) >= set(ligadas["n1"]) | {"Texto do fornecedor"}
    assert len(opcoes["temas_n1"]) == 8 and opcoes["temas_n1"][-1] == "Texto do fornecedor"
    assert set(opcoes["temas_n2"]) >= set(ligadas["n2"]) and len(opcoes["temas_n2"]) == 41
    assert set(opcoes["temas_n3"]) == set(ligadas["n3"])


def test_sem_mencao_ligada_so_o_n3_vem_vazio(sessao):
    lente_id = sessao.scalar(select(Lente.id).where(Lente.codigo == "sociedade"))
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    sessao.add(Mencao(fonte_id=bites.id, mes=MES, sentimento="pos", tema_texto="Só texto"))
    sessao.flush()
    opcoes = opcoes_de_filtro(sessao, lente_id, MES)
    assert opcoes["temas_n3"] == []
    # Pilar e tema estratégico continuam oferecidos — são filtros fixos.
    assert len(opcoes["temas_n2"]) == 41
    assert opcoes["temas_n1"][-1] == "Só texto" and len(opcoes["temas_n1"]) == 8


def test_o_tema_do_fornecedor_e_o_pilar(sessao, ligadas):
    """O tema que o fornecedor escreve É o Pilar (N1): filtrar por ele acha a
    menção mesmo sem vínculo com o cadastro."""
    lente = ligadas["lente_id"]
    # As três menções da fixture trazem "Texto do fornecedor" como tema.
    assert _quantas(sessao, lente, tema_n1="Texto do fornecedor") == 3
