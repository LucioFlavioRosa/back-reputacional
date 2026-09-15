"""Ler uma página de agendas custa o mesmo número de consultas com 3 ou com 30.

O QUE ISTO IMPEDE. A Base levava mais de um segundo para abrir: cada agenda da
página ia ao banco seis ou sete vezes só para traduzir `frente_id`, `status_id`,
`clima_id`… em código — mais de mil `SELECT` de uma linha por página de
duzentas. Nenhum teste via, porque cada um lia uma agenda só.

A GARANTIA É POR CONTAGEM, e não por tempo: tempo varia com a máquina; o número
de consultas de uma página só cresce com o número de linhas quando alguém
voltou a consultar por linha. O `selectin` do SQLAlchemy carrega cada coleção
numa consulta por página, e os dicionários, inteiros, uma vez por repositório —
então a contagem tem de ser a MESMA para páginas de tamanhos diferentes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
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
def cliente(sessao, monkeypatch):
    """Quem administra cadastros E agendas: cria a instituição, a pessoa e as
    agendas pela mesma porta que o front usa."""
    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como_admin = Configuracao(**{**padrao.model_dump(), "auth_mock_perfil": "plataforma_edicao"})
    monkeypatch.setattr("app.api.dependencias.obter_configuracao", lambda: como_admin)

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class _Com:
    def __init__(self, id_: str) -> None:
        self.id = id_


@pytest.fixture
def semente(cliente):
    """Instituição e pessoa da Aegea, no formato que `corpo()` espera."""
    instituicao = cliente.post(
        "/api/instituicoes", json={"nome": "Valor Econômico", "tipo": "veiculo", "uf": "SP"}
    )
    assert instituicao.status_code == 201, instituicao.text
    pessoa = cliente.post(
        "/api/pessoas-aegea", json={"nome": "Radamés Casseb", "eh_porta_voz": True}
    )
    assert pessoa.status_code == 201, pessoa.text
    return {"instituicao": _Com(instituicao.json()["id"]), "radames": _Com(pessoa.json()["id"])}


def _consultas_para_ler_uma_pagina(cliente, sessao) -> int:
    contagem = 0

    def contar(*_):
        nonlocal contagem
        contagem += 1

    conexao = sessao.connection()
    event.listen(conexao, "before_cursor_execute", contar)
    try:
        resposta = cliente.get("/api/interacoes?pagina=1&tamanho=200")
        assert resposta.status_code == 200, resposta.text
    finally:
        event.remove(conexao, "before_cursor_execute", contar)
    return contagem


def _cadastrar(cliente, semente, quantas: int) -> None:
    for i in range(quantas):
        criada = cliente.post(
            "/api/interacoes",
            json=corpo(
                semente,
                pauta=f"Pauta {i}",
                # Cada uma com participantes, temas e clima esperado: são as
                # coleções e os códigos que a leitura precisa traduzir.
                participacoes=[
                    {
                        "pessoa_aegea_id": str(semente["radames"].id),
                        "papel": "porta_voz",
                    }
                ],
                clima_esperado="neutro",
            ),
        )
        assert criada.status_code == 201, criada.text


def test_o_numero_de_consultas_nao_cresce_com_as_linhas(cliente, semente, sessao):
    _cadastrar(cliente, semente, 3)
    com_tres = _consultas_para_ler_uma_pagina(cliente, sessao)
    assert com_tres > 0, "o contador não está escutando a conexão da sessão"

    _cadastrar(cliente, semente, 27)
    com_trinta = _consultas_para_ler_uma_pagina(cliente, sessao)

    assert com_trinta == com_tres, (
        f"ler 30 agendas custou {com_trinta} consultas e ler 3 custou {com_tres}: "
        "alguma coisa voltou a consultar por linha"
    )
    # E o número absoluto é pequeno: a página, a contagem, uma consulta por
    # coleção e uma por dicionário. Trinta seria sinal de coleção nova sem
    # `selectin` — ou de dicionário lido linha a linha de novo.
    assert com_trinta <= 30, f"{com_trinta} consultas para uma página"
