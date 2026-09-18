""""Formato da interação" (Mídia, Agenda de mercado, Evento...): dicionário
novo, campo novo, ortogonal a `frente` — ver `0038_formato_interacao.sql`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import FormatoInteracao
from app.banco.tabelas_stakeholders import Instituicao
from main import app
from tests.test_e2e_postgres import URL, corpo

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
def cliente(sessao):
    from fastapi.testclient import TestClient

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    """Só a instituição — nenhum teste aqui precisa de pessoa da Aegea."""
    valor = Instituicao(
        nome="Valor Econômico", nome_normalizado="valor economico", tipo="veiculo", uf="SP"
    )
    sessao.add(valor)
    sessao.flush()
    return {"instituicao": valor}


def test_migration_criou_as_7_linhas_direto_no_banco(sessao):
    """Confere a migration sem passar pela API — não depende de sessão/CSRF,
    só do que `0038_formato_interacao.sql` de fato gravou."""
    formatos = sessao.scalars(
        select(FormatoInteracao).order_by(FormatoInteracao.ordem)
    ).all()
    assert [f.codigo for f in formatos] == [
        "midia", "agenda_de_mercado", "agenda_publica",
        "manifestacao_formal", "evento", "visita", "reuniao",
    ]
    assert [f.nome for f in formatos] == [
        "Mídia", "Agenda de mercado", "Agenda pública",
        "Manifestação formal", "Evento", "Visita", "Reunião",
    ]
    assert all(f.ativo for f in formatos)


def test_formatos_interacao_aparece_nos_dicionarios(cliente):
    resposta = cliente.get("/api/dicionarios")
    assert resposta.status_code == 200
    formatos = resposta.json()["formatos_interacao"]
    codigos = {f["codigo"] for f in formatos}
    assert codigos == {
        "midia", "agenda_de_mercado", "agenda_publica",
        "manifestacao_formal", "evento", "visita", "reuniao",
    }


def test_criar_sem_formato_continua_valendo(cliente, semente):
    # OPCIONAL, DE PROPÓSITO: uma interação não deixa de valer por não dizer
    # que tipo de encontro foi — ver o comentário da migration.
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    assert criada.status_code == 201, criada.text
    assert criada.json()["formato_interacao_id"] is None


def test_formato_interacao_id_e_aceito_na_criacao_e_editavel(cliente, semente):
    formatos = cliente.get("/api/dicionarios").json()["formatos_interacao"]
    reuniao = next(f for f in formatos if f["codigo"] == "reuniao")
    evento = next(f for f in formatos if f["codigo"] == "evento")

    criada = cliente.post(
        "/api/interacoes", json=corpo(semente, formato_interacao_id=reuniao["id"])
    )
    assert criada.status_code == 201, criada.text
    id_ = criada.json()["id"]
    assert criada.json()["formato_interacao_id"] == reuniao["id"]

    lida = cliente.get(f"/api/interacoes/{id_}")
    assert lida.json()["formato_interacao_id"] == reuniao["id"]

    editada = cliente.patch(
        f"/api/interacoes/{id_}", json={"formato_interacao_id": evento["id"]}
    )
    assert editada.status_code == 200, editada.text
    assert editada.json()["formato_interacao_id"] == evento["id"]
