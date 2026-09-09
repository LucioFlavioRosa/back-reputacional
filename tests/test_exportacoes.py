"""A trilha de exportação da Base: quem levou o quê, e quanto.

Não há geração de documento no servidor: o que existe é o EVENTO que
`seguranca/ARQUITETURA.md` lista como necessário para responder "o que saiu
daqui?" depois de um incidente.

Os testes são sobre a
única coisa que a trilha promete — dizer a verdade sobre o que saiu.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_exportacoes import ExportacaoRegistro
from app.casos_de_uso import registrar_exportacao
from app.dominio.erros import NaoAutorizado
from app.dominio.recorte import Recorte
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
    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    from app.banco.tabelas_stakeholders import (
        Instituicao,
        PessoaAegea,
    )

    sufixo = uuid4().hex[:6]
    valor = Instituicao(
        nome=f"Veículo {sufixo}",
        nome_normalizado=f"veiculo {sufixo}",
        tipo="veiculo",
        uf="SP",
    )
    a = PessoaAegea(nome=f"A {sufixo}", nome_normalizado=f"a {sufixo}", eh_porta_voz=True)
    b = PessoaAegea(nome=f"B {sufixo}", nome_normalizado=f"b {sufixo}", eh_porta_voz=True)
    sessao.add_all([valor, a, b])
    sessao.flush()
    return {"instituicao": valor, "radames": a, "andre": b}


# -- o total é contado aqui, não recebido --------------------------------------


def test_o_total_e_contado_pelo_servidor(cliente, semente, sessao):
    """Receber o total do cliente seria aceitar que quem exporta declare quanto.

    O número existe exatamente para o caso em que essa declaração não é
    confiável.
    """
    for _ in range(3):
        assert cliente.post("/api/interacoes", json=corpo(semente)).status_code == 201

    resposta = cliente.post("/api/exportacoes?frente=imprensa")
    assert resposta.status_code == 201

    linhas = cliente.get("/api/interacoes?frente=imprensa").json()["total"]
    assert resposta.json()["total_de_registros"] == linhas


def test_o_total_respeita_o_recorte(cliente, semente):
    """A trilha registra o tamanho DO RECORTE exportado, não o da base."""
    cliente.post("/api/interacoes", json=corpo(semente, frente="imprensa"))
    cliente.post("/api/interacoes", json=corpo(semente, frente="governo"))

    tudo = cliente.post("/api/exportacoes").json()
    so_governo = cliente.post("/api/exportacoes?frente=governo").json()

    assert so_governo["total_de_registros"] < tudo["total_de_registros"]


def test_o_recorte_registrado_e_o_da_query_string(cliente, semente, sessao):
    """Receber os filtros no corpo abriria a porta para a exportação registrar
    um recorte e levar outro — e a trilha passaria a mentir sobre o que saiu."""
    cliente.post("/api/interacoes", json=corpo(semente))
    cliente.post("/api/exportacoes?frente=imprensa&uf=SP")
    sessao.flush()

    registro = sessao.scalars(
        select(ExportacaoRegistro).order_by(ExportacaoRegistro.criado_em.desc())
    ).first()
    assert registro.filtros == {"frente": "imprensa", "uf": "SP"}


def test_filtros_vazios_nao_enchem_a_coluna(cliente, semente, sessao):
    """Guardar `{"frente": null, "uf": null, ...}` tornaria ilegível o que de
    fato foi filtrado."""
    cliente.post("/api/exportacoes")
    sessao.flush()

    registro = sessao.scalars(
        select(ExportacaoRegistro).order_by(ExportacaoRegistro.criado_em.desc())
    ).first()
    assert registro.filtros == {}


# -- o histórico ---------------------------------------------------------------


def cria_usuario(sessao, papel_codigo: str) -> Usuario:
    papel_id = sessao.scalars(select(Papel.id).where(Papel.codigo == papel_codigo)).first()
    sufixo = uuid4().hex[:8]
    registro = Usuario(
        entra_object_id=f"oid-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome=f"Pessoa {sufixo}",
        papel_id=papel_id,
        acesso_irrestrito=True,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def como(sessao, registro: Usuario):
    from app.casos_de_uso.provisionar_usuario import (
        carregar,
    )

    return carregar(sessao, registro.id)


def test_historico_exige_administrar_acessos(cliente, semente, sessao):
    """A trilha diz o que cada pessoa levou embora.

    Isso é informação sobre as PESSOAS, não sobre as interações — quem lê
    precisa ter o papel de quem responde por isso.
    """
    analista = como(sessao, cria_usuario(sessao, "crm_edicao"))
    with pytest.raises(NaoAutorizado):
        registrar_exportacao.historico(sessao, solicitante=analista)


def test_historico_mostra_quem_exportou_e_quanto(cliente, semente, sessao):
    admin = cria_usuario(sessao, "plataforma_edicao")
    cliente.post("/api/interacoes", json=corpo(semente))

    registrar_exportacao.registrar(
        sessao,
        recorte=Recorte(frente="imprensa"),
        usuario=como(sessao, admin),
    )
    sessao.flush()

    linhas = registrar_exportacao.historico(sessao, solicitante=como(sessao, admin))
    primeira = linhas[0]

    assert primeira.criado_por == admin.nome
    assert primeira.total_de_registros >= 1
    assert "frente=imprensa" in primeira.resumo_do_recorte


def test_recorte_sem_filtro_aparece_legivel_no_historico(cliente, semente, sessao):
    admin = cria_usuario(sessao, "plataforma_edicao")
    registrar_exportacao.registrar(
        sessao, recorte=Recorte(), usuario=como(sessao, admin)
    )
    sessao.flush()

    linhas = registrar_exportacao.historico(sessao, solicitante=como(sessao, admin))
    assert linhas[0].resumo_do_recorte == "todo o histórico"


# -- o escopo vale aqui também -------------------------------------------------


def test_o_total_respeita_o_escopo_de_quem_exporta(cliente, semente, sessao):
    """Sem isso, a exportação de um externo contaria a base inteira.

    A trilha registraria "5.000 linhas" para quem alcança 40 — e o alerta de
    volume dispararia no alvo errado, todo dia, até alguém desligá-lo.
    """
    from app.dominio.identidade import Escopo

    cliente.post("/api/interacoes", json=corpo(semente, frente="imprensa"))
    cliente.post("/api/interacoes", json=corpo(semente, frente="governo"))
    sessao.flush()

    admin = cria_usuario(sessao, "plataforma_edicao")
    irrestrito = como(sessao, admin)

    # `replace`, e não reconstruir campo a campo: se `UsuarioAtual` ganhar um
    # campo obrigatório, o teste quebraria por forma e não por comportamento.
    restrito = replace(irrestrito, escopo=Escopo(frentes=frozenset({"governo"})))

    completo = registrar_exportacao.registrar(
        sessao, recorte=Recorte(), usuario=irrestrito
    )
    parcial = registrar_exportacao.registrar(
        sessao, recorte=Recorte(), usuario=restrito
    )

    assert parcial.total_de_registros < completo.total_de_registros


# -- a trilha não se reescreve -------------------------------------------------


def test_a_aplicacao_nao_altera_exportacao_gravada(sessao):
    """A migration 0009 revoga `update` e `delete`; a 0025 reafirma no nome novo.

    O `alter default privileges` da 0009 concede em massa; sem a revogação,
    quem tivesse a connection string reescreveria a trilha de exportações —
    exatamente a que diz o que saiu daqui.
    """
    concedido = sessao.execute(
        text(
            "select has_table_privilege('painel_app', 'exportacao', 'INSERT') as inserir, "
            "       has_table_privilege('painel_app', 'exportacao', 'UPDATE') as alterar, "
            "       has_table_privilege('painel_app', 'exportacao', 'DELETE') as remover"
        )
    ).one()
    assert concedido.inserir, "a aplicação precisa registrar"
    assert not concedido.alterar
    assert not concedido.remover


# -- o CSV leva tudo -----------------------------------------------------------


def test_a_exportacao_leva_o_recorte_inteiro(cliente, semente, sessao):
    """O CSV NÃO corta.

    O documento impresso cortava em 80 linhas, e por isso a trilha distinguia
    "o que saiu" de "o que a pessoa estava olhando". Sem ele, os dois números
    são o mesmo — e é justamente por levar tudo que a exportação é o caminho
    mais curto para tirar dados daqui.
    """
    for _ in range(3):
        cliente.post("/api/interacoes", json=corpo(semente))

    resposta = cliente.post("/api/exportacoes?frente=imprensa").json()
    alcance = cliente.get("/api/interacoes?frente=imprensa").json()["total"]

    assert resposta["total_de_registros"] == alcance
