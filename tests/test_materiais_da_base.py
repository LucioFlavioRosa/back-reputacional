"""A listagem dos documentos que sairam das reunioes.

Duas procedencias, duas telas: a biblioteca e o acervo do SharePoint que a
Aegea leva PARA a reuniao; isto aqui e o que VOLTA dela e mora no Blob.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    from app.banco.tabelas_stakeholders import Instituicao, PessoaAegea

    sufixo = uuid4().hex[:6]
    valor = Instituicao(
        nome=f"Veiculo {sufixo}",
        nome_normalizado=f"veiculo {sufixo}",
        tipo="veiculo",
        uf="SP",
    )
    a = PessoaAegea(nome=f"A {sufixo}", nome_normalizado=f"a {sufixo}", eh_porta_voz=True)
    b = PessoaAegea(nome=f"B {sufixo}", nome_normalizado=f"b {sufixo}", eh_porta_voz=True)
    sessao.add_all([valor, a, b])
    sessao.flush()
    return {"instituicao": valor, "radames": a, "andre": b}


def com_arquivo(cliente, sessao, semente, *, frente="imprensa", momento="produzido"):
    """Cria uma agenda e amarra um arquivo a ela. Devolve (agenda, arquivo).

    A LINHA DE `arquivo` E ESCRITA DIRETO, e nao pela rota de upload: o blob nao
    esta configurado no ambiente de teste — nenhum teste da suite sobe byte — e
    o alvo aqui e a LISTAGEM, nao o upload. Passar pela rota faria o teste
    depender de um servico que ele nao esta exercitando, e falhar por ele.
    """
    from app.banco.tabelas_acesso import Usuario
    from app.banco.tabelas_interacoes import Arquivo, Material

    criada = cliente.post("/api/interacoes", json=corpo(semente, frente=frente)).json()

    autor = sessao.scalar(select(Usuario.id).order_by(Usuario.email).limit(1))
    arquivo = Arquivo(
        caminho=f"agendas/{criada['id']}/ata.pdf",
        nome="ata.pdf",
        tipo_conteudo="application/pdf",
        tamanho=2048,
        criado_por=autor,
    )
    sessao.add(arquivo)
    sessao.flush()

    sessao.add(
        Material(
            interacao_id=criada["id"],
            momento=momento,
            titulo="Ata da reuniao",
            arquivo_id=arquivo.id,
            observacao="Assinada pelas duas partes.",
            criado_por=autor,
        )
    )
    sessao.flush()
    return criada, arquivo


def test_o_documento_com_arquivo_aparece_na_listagem(cliente, sessao, semente):
    agenda, _ = com_arquivo(cliente, sessao, semente)

    listados = cliente.get("/api/materiais").json()
    achado = next((m for m in listados if m["interacao_id"] == agenda["id"]), None)

    assert achado is not None, "o material com arquivo precisa aparecer"
    assert achado["titulo"] == "Ata da reuniao"
    assert achado["arquivo_nome"] == "ata.pdf"
    assert achado["arquivo_tipo"] == "application/pdf"
    assert achado["arquivo_tamanho"] > 0
    assert achado["resumo"] == "Assinada pelas duas partes."


def test_material_so_com_link_fica_de_fora(cliente, semente):
    """A tela existe para o acervo que SO existe dentro do painel.

    Material por link ja e alcancavel pelo link; listar os dois juntos faria a
    aba prometer arquivo e entregar atalho.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente)).json()
    cliente.patch(
        f"/api/interacoes/{criada['id']}",
        json={
            "materiais": [
                {
                    "momento": "apoio",
                    "titulo": "Briefing por link",
                    "url": "https://exemplo/briefing.docx",
                }
            ]
        },
    )

    listados = cliente.get("/api/materiais").json()
    assert not any(m["interacao_id"] == criada["id"] for m in listados)


def test_o_recorte_vale_aqui_como_vale_na_base(cliente, sessao, semente):
    """Uma aba que ignorasse os filtros mostraria documentos de agendas que a
    tela ao lado nao lista — e os dois numeros nao se reconciliariam."""
    de_imprensa, _ = com_arquivo(cliente, sessao, semente, frente="imprensa")

    so_governo = cliente.get("/api/materiais?frente=governo").json()
    assert not any(m["interacao_id"] == de_imprensa["id"] for m in so_governo)

    so_imprensa = cliente.get("/api/materiais?frente=imprensa").json()
    assert any(m["interacao_id"] == de_imprensa["id"] for m in so_imprensa)


def test_a_listagem_diz_de_qual_agenda_o_documento_saiu(cliente, sessao, semente):
    """Sem isto, o arquivo aparece solto: para saber o contexto seria preciso
    abrir a agenda que o gerou — e e preciso saber qual foi."""
    agenda, _ = com_arquivo(cliente, sessao, semente)

    achado = next(
        m
        for m in cliente.get("/api/materiais").json()
        if m["interacao_id"] == agenda["id"]
    )
    assert achado["frente"] == "imprensa"
    assert achado["data_interacao"] == agenda["data_interacao"]
    assert achado["instituicao"]


# -- o assunto, a ponte entre as duas abas -------------------------------------


def test_o_assunto_do_material_vai_e_volta(cliente, semente, sessao):
    """A ida e a VOLTA, provadas por HTTP.

    Um campo declarado no esquema e nao preenchido no construtor sai vazio para
    sempre, com 200 na resposta — ja aconteceu tres vezes neste projeto. Por
    isso o teste grava por POST e le por GET, em vez de conferir a camada.
    """
    from app.banco.tabelas_catalogo import Tema

    temas = sessao.scalars(select(Tema.id).where(Tema.ativo.is_(True)).limit(2)).all()

    criada = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            materiais=[
                {
                    "momento": "produzido",
                    "titulo": "Nota de encaminhamento",
                    "url": "https://exemplo/nota.docx",
                    "temas": list(temas),
                }
            ],
        ),
    )
    assert criada.status_code == 201, criada.text

    lida = cliente.get(f"/api/interacoes/{criada.json()['id']}").json()
    assert sorted(lida["materiais"][0]["temas"]) == sorted(temas)


def test_trocar_o_assunto_do_material_troca_so_o_que_mudou(cliente, semente, sessao):
    from app.banco.tabelas_catalogo import Tema

    temas = sessao.scalars(select(Tema.id).where(Tema.ativo.is_(True)).limit(2)).all()

    criada = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            materiais=[
                {
                    "momento": "produzido",
                    "titulo": "Ata",
                    "url": "https://exemplo/ata.docx",
                    "temas": [temas[0]],
                }
            ],
        ),
    ).json()

    material = cliente.get(f"/api/interacoes/{criada['id']}").json()["materiais"][0]
    editada = cliente.patch(
        f"/api/interacoes/{criada['id']}",
        json={
            "materiais": [
                {
                    "id": material["id"],
                    "momento": material["momento"],
                    "titulo": material["titulo"],
                    "url": material["url"],
                    "temas": [temas[1]],
                }
            ]
        },
    )
    assert editada.status_code == 200, editada.text
    assert editada.json()["materiais"][0]["temas"] == [temas[1]]


def test_a_listagem_da_base_traz_os_assuntos(cliente, sessao, semente):
    """Sem eles na listagem, a aba de documentos nao teria por onde filtrar — e
    a busca deixaria de ser a mesma nas duas procedencias."""
    from app.banco.tabelas_catalogo import Tema
    from app.banco.tabelas_interacoes import MaterialTema

    agenda, _ = com_arquivo(cliente, sessao, semente)
    tema = sessao.scalars(select(Tema.id).where(Tema.ativo.is_(True)).limit(1)).first()

    from app.banco.tabelas_interacoes import Material

    material = sessao.scalars(
        select(Material).where(Material.interacao_id == agenda["id"])
    ).first()
    material.temas.append(MaterialTema(tema_id=tema))
    sessao.flush()

    achado = next(
        m
        for m in cliente.get("/api/materiais").json()
        if m["interacao_id"] == agenda["id"]
    )
    assert achado["temas"] == [tema]
