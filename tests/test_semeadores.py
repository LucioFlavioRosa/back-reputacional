"""Os três semeadores do README, na ordem em que o README manda rodar.

Eles são o caminho de quem clona o repositório e sobe a pilha: se um deles
quebra, a base fica pela metade e o README mente. Nenhum teste os exercitava —
foi assim que `vincular_areas` passou 3 dias quebrado em `main` (o `scalars` de
uma coluna devolve o valor, não um objeto com `.interacao_id`).

Roda dentro da transação da fixture `sessao`, desfeita no fim: o banco de teste
continua vazio para os demais arquivos. O blob é substituído por um no-op, como
em `test_sincronizacao_do_catalogo` — o que está em prova é o banco.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco import semear_desenvolvimento, semear_enredos, semear_referencias
from app.banco.tabelas_interacoes import InteracaoRegistro

# Reaproveita o banco de teste que `test_e2e_postgres` cria e migra.
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    """Uma transação por teste, desfeita ao final — a mesma forma da fixture
    de `test_e2e_postgres`, reescrita aqui porque importar uma fixture pelo
    nome é redefinição para o linter."""
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def test_os_tres_semeadores_rodam_em_sequencia_e_sao_idempotentes(sessao, monkeypatch):
    monkeypatch.setattr(blob, "guardar", lambda caminho, dados, tipo: None)

    amostra = semear_desenvolvimento.semear(sessao)
    assert amostra["interacoes"] == 60

    biblioteca = semear_referencias.semear(sessao)
    assert biblioteca["criadas"] == 67

    criadas = semear_enredos.semear(sessao)
    assert criadas == 233

    # A base inteira é 60 + 233, e é essa soma que o README promete.
    assert sessao.scalar(select(func.count()).select_from(InteracaoRegistro)) == 293

    ligadas = semear_enredos.vincular_areas(sessao)
    sessao.flush()
    assert ligadas > 0

    # Nenhuma agenda de frente mapeada ficou sem área.
    sem_area = sessao.execute(
        text(
            "select count(*) from interacao i join frente f on f.id = i.frente_id "
            "where f.codigo in ('imprensa', 'eventos', 'governo', 'parceiros', 'legislativo') "
            "and not exists (select 1 from interacao_area ia where ia.interacao_id = i.id)"
        )
    ).scalar_one()
    assert sem_area == 0

    # Rodar de novo não duplica nem toca em quem já tem área.
    assert semear_enredos.semear(sessao) == 0
    assert semear_enredos.vincular_areas(sessao) == 0
