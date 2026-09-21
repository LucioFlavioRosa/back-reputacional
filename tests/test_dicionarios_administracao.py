"""A administração dos dicionários: o que se edita pela tela, e o que não.

Reaproveita o banco de teste de `test_e2e_postgres`, com fixtures próprias da
mesma forma (importar fixture pelo nome é redefinição para o linter). A rota
exige `administra_dicionarios`, que `cliente_admin` tem e `cliente` não.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.dicionarios import ABERTOS, APOSENTADOS, FECHADOS, OUTRA_ABA, ROTULOS
from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import DICIONARIOS
from main import app

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


@pytest.fixture
def cliente(sessao):
    """`crm_edicao`: edita agenda, não administra cadastros."""
    from fastapi.testclient import TestClient

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_admin(sessao):
    """`plataforma_edicao`: administra cadastros — ver `test_e2e_postgres`."""
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como_admin = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": "plataforma_edicao"}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como_admin
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    """Nada a semear: os dicionários já vêm das migrations."""
    return None


def test_todo_dicionario_do_registro_aparece_na_administracao(cliente_admin, semente):
    """Aberto, fechado ou aposentado — nenhum vocabulário fica invisível.
    Um dicionário novo no registro sem classificação aqui é erro, e este
    teste é o que o acusa."""
    classificados = set(ABERTOS) | set(FECHADOS) | set(APOSENTADOS)
    assert classificados | set(OUTRA_ABA) == set(DICIONARIOS), (
        "todo dicionário do registro precisa estar em ABERTOS, FECHADOS, APOSENTADOS "
        "ou OUTRA_ABA"
    )
    assert classificados <= set(ROTULOS)

    resposta = cliente_admin.get("/api/dicionarios/administracao")
    assert resposta.status_code == 200, resposta.text
    por_nome = {d["nome"]: d for d in resposta.json()}
    # `temas` tem aba própria: não repete aqui.
    assert set(por_nome) == classificados
    for nome in ABERTOS:
        assert por_nome[nome]["editavel"] is True
    for nome in list(FECHADOS) + list(APOSENTADOS):
        assert por_nome[nome]["editavel"] is False
        assert por_nome[nome]["motivo"]


def test_a_administracao_mostra_os_inativos_e_a_tela_nao(cliente_admin, semente):
    criado = cliente_admin.post("/api/dicionarios/unidades_negocio", json={"nome": "Unidade Z"})
    assert criado.status_code == 201, criado.text
    id_ = criado.json()["id"]

    desativado = cliente_admin.put(
        f"/api/dicionarios/unidades_negocio/{id_}", json={"nome": "Unidade Z", "ativo": False}
    )
    assert desativado.status_code == 200, desativado.text

    telas = {u["id"] for u in cliente_admin.get("/api/dicionarios").json()["unidades_negocio"]}
    assert id_ not in telas, "a tela só vê ativos"
    administracao = next(
        d for d in cliente_admin.get("/api/dicionarios/administracao").json()
        if d["nome"] == "unidades_negocio"
    )
    achado = next(i for i in administracao["itens"] if i["id"] == id_)
    assert achado["ativo"] is False


def test_acrescentar_gera_codigo_estavel_e_recusa_duplicata(cliente_admin, semente):
    criado = cliente_admin.post(
        "/api/dicionarios/tipos_investidor", json={"nome": "Família & Office"}
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["codigo"] == "familia_office"
    assert criado.json()["ordem"] >= 1

    repetido = cliente_admin.post(
        "/api/dicionarios/tipos_investidor", json={"nome": "família & office"}
    )
    assert repetido.status_code == 422
    assert "Já existe" in repetido.json()["detalhe"]


def test_renomear_nao_muda_o_codigo(cliente_admin, semente):
    criado = cliente_admin.post("/api/dicionarios/esferas", json={"nome": "Distrital"}).json()
    editado = cliente_admin.put(
        f"/api/dicionarios/esferas/{criado['id']}", json={"nome": "Distrito Federal"}
    )
    assert editado.status_code == 200, editado.text
    assert editado.json()["nome"] == "Distrito Federal"
    assert editado.json()["codigo"] == criado["codigo"] == "distrital"


def test_formato_acrescentado_pela_tela_vale_para_imprensa_e_investidores(
    cliente_admin, semente
):
    criado = cliente_admin.post("/api/dicionarios/formatos", json={"nome": "Mesa-redonda"})
    assert criado.status_code == 201, criado.text
    formatos = cliente_admin.get("/api/dicionarios").json()["formatos"]
    achado = next(f for f in formatos if f["id"] == criado.json()["id"])
    assert achado["escopo"] == "geral"


def test_dicionario_fechado_nao_se_edita_e_diz_por_que(cliente_admin, semente):
    resposta = cliente_admin.post("/api/dicionarios/frentes", json={"nome": "Nova frente"})
    assert resposta.status_code == 422
    assert "não se edita pela tela" in resposta.json()["detalhe"]
    assert "derivada" in resposta.json()["detalhe"]

    resposta = cliente_admin.put("/api/dicionarios/status/1", json={"nome": "X"})
    assert resposta.status_code == 422


def test_dicionario_inexistente_e_404(cliente_admin, semente):
    resposta = cliente_admin.post("/api/dicionarios/nao_existe", json={"nome": "X"})
    assert resposta.status_code == 404


def test_quem_nao_administra_cadastros_nao_ve_nem_edita(cliente, semente):
    assert cliente.get("/api/dicionarios/administracao").status_code == 403
    assert (
        cliente.post("/api/dicionarios/unidades_negocio", json={"nome": "X"}).status_code == 403
    )
