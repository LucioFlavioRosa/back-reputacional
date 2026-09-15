"""Um cadastro na Administração aparece, na leitura seguinte, onde quer que se leia.

O QUE ISTO GARANTE. A Administração cadastra temas, instituições e seus
interlocutores, pessoas da Aegea e referências da biblioteca — e esses
cadastros são as OPÇÕES de todo formulário, filtro e ficha da plataforma. O
front recarrega o catálogo a cada escrita bem-sucedida (ver
`dominio/sincronizacao.ts`); esta suíte prova a metade do servidor: a escrita
está visível na leitura imediatamente seguinte, PELA MESMA API que o front lê,
e nenhuma resposta carrega permissão para ser guardada no caminho.

POR HTTP, e não pelo repositório: é a porta por onde o front entra, e é nela
que um cache, um cabeçalho errado ou um esquema que descarta um campo se
esconderia.

DUAS COISAS QUE ESTA GARANTIA PRESSUPÕE, e que não estão no código:

  1. O commit acontece ANTES de a resposta sair. É o que `obter_sessao` faz
     no caminho feliz, e o que `test_sessao_do_pedido` prova — sem isso, o
     front recarregaria o catálogo antes de a escrita estar visível.

  2. NÃO HÁ RÉPLICA DE LEITURA. Um Postgres só, e toda leitura vê o último
     commit. Uma réplica no Terraform — que ninguém precisa mexer em código
     para acrescentar — traria atraso de replicação, e esta suíte passaria a
     falhar de forma intermitente. É o sinal certo: a garantia teria de ser
     redesenhada, e não o teste afrouxado.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.sessao import obter_sessao
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

PDF = b"%PDF-1.7\nconteudo de teste\n%%EOF\n"


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
def admin(sessao, monkeypatch):
    """Quem administra cadastros — o papel que a Administração exige."""
    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como_admin = Configuracao(
        **{**padrao.model_dump(), "auth_mock_perfil": "plataforma_edicao"}
    )
    monkeypatch.setattr("app.api.dependencias.obter_configuracao", lambda: como_admin)
    monkeypatch.setattr(blob, "guardar", lambda caminho, dados, tipo: None)

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _sufixo() -> str:
    return uuid4().hex[:8]


# -- cada cadastro, e a leitura que o front faz logo depois --------------------


def test_tema_novo_esta_no_dicionario_na_leitura_seguinte(admin):
    """`/api/dicionarios` é o que alimenta o formulário de agenda e os filtros."""
    nome = f"Tema {_sufixo()}"
    criado = admin.post("/api/temas", json={"nome": nome, "nivel": "sensivel"})
    assert criado.status_code == 201, criado.text

    temas = admin.get("/api/dicionarios").json()["temas"]
    achado = next((t for t in temas if t["id"] == criado.json()["id"]), None)
    assert achado is not None, "o tema criado não chegou ao dicionário"
    assert achado["nome"] == nome


def test_tema_renomeado_e_desativado_muda_o_dicionario(admin):
    """Editar é tão cadastro quanto criar — e desativar tem de SUMIR das opções.

    Um tema desativado que continua sendo oferecido é pior do que um tema que
    nunca existiu: alguém o escolhe, e a agenda aponta para o que a
    administração tirou de circulação.
    """
    criado = admin.post(
        "/api/temas", json={"nome": f"Tema {_sufixo()}", "nivel": "gerais"}
    ).json()

    renomeado = admin.put(
        f"/api/temas/{criado['id']}",
        json={"nome": f"Renomeado {_sufixo()}", "nivel": "estrategico", "ativo": True},
    )
    assert renomeado.status_code == 200, renomeado.text
    no_dicionario = {t["id"]: t for t in admin.get("/api/dicionarios").json()["temas"]}
    assert no_dicionario[criado["id"]]["nome"] == renomeado.json()["nome"]

    admin.put(
        f"/api/temas/{criado['id']}",
        json={"nome": renomeado.json()["nome"], "nivel": "estrategico", "ativo": False},
    )
    ativos = {t["id"] for t in admin.get("/api/dicionarios").json()["temas"]}
    assert criado["id"] not in ativos, "tema desativado continua sendo oferecido"


def test_instituicao_nova_e_renomeada_no_diretorio(admin):
    """`/api/instituicoes` é a lista do campo "Instituição" da agenda."""
    criada = admin.post(
        "/api/instituicoes",
        json={"nome": f"Instituição {_sufixo()}", "tipo": "veiculo", "uf": "SP"},
    )
    assert criada.status_code == 201, criada.text
    id_ = criada.json()["id"]

    assert any(i["id"] == id_ for i in admin.get("/api/instituicoes").json())

    novo_nome = f"Renomeada {_sufixo()}"
    editada = admin.put(
        f"/api/instituicoes/{id_}", json={"nome": novo_nome, "tipo": "veiculo", "uf": "SP"}
    )
    assert editada.status_code == 200, editada.text
    no_diretorio = next(i for i in admin.get("/api/instituicoes").json() if i["id"] == id_)
    assert no_diretorio["nome"] == novo_nome


def test_interlocutor_novo_aparece_e_removido_some(admin):
    """`/api/interlocutores` alimenta "Pela outra parte".

    Remover é a escrita que mais custa quando não sincroniza: a pessoa some do
    cadastro e continua sendo oferecida na agenda — e escolhê-la grava um id
    que não existe mais.
    """
    instituicao = admin.post(
        "/api/instituicoes",
        json={"nome": f"Casa {_sufixo()}", "tipo": "orgao", "uf": "DF"},
    ).json()
    criado = admin.post(
        "/api/interlocutores",
        json={"nome": f"Pessoa {_sufixo()}", "instituicao_id": instituicao["id"]},
    )
    assert criado.status_code == 201, criado.text
    id_ = criado.json()["id"]
    assert any(p["id"] == id_ for p in admin.get("/api/interlocutores").json())

    removido = admin.delete(f"/api/interlocutores/{id_}")
    assert removido.status_code == 204, removido.text
    assert not any(p["id"] == id_ for p in admin.get("/api/interlocutores").json())


def test_pessoa_da_aegea_nova_com_seus_temas(admin):
    """`/api/pessoas-aegea` alimenta "Quem participa"; os temas alimentam a
    regra de "fora do escopo" da Situação."""
    tema = admin.post(
        "/api/temas", json={"nome": f"Tema {_sufixo()}", "nivel": "gerais"}
    ).json()
    criada = admin.post(
        "/api/pessoas-aegea",
        json={"nome": f"Porta-voz {_sufixo()}", "eh_porta_voz": True, "temas": [tema["id"]]},
    )
    assert criada.status_code == 201, criada.text
    id_ = criada.json()["id"]

    assert any(p["id"] == id_ for p in admin.get("/api/pessoas-aegea").json())
    assert admin.get(f"/api/pessoas-aegea/{id_}/temas").json() == [tema["id"]]


def test_referencia_nova_esta_na_biblioteca_e_desativada_continua_listada(admin):
    """`/api/referencias` alimenta os materiais de preparação da agenda e a Base.

    A listagem traz TAMBÉM as desativadas — a Administração precisa reativá-las
    —, e cabe a quem oferece filtrar `ativo`. O teste prova as duas metades:
    a nova aparece, e a desativada aparece COM `ativo=false`.
    """
    tema = admin.get("/api/dicionarios").json()["temas"][0]
    criada = admin.post(
        "/api/referencias",
        data={
            "titulo": f"Q&A {_sufixo()}",
            "tipo": "qa",
            "tema_principal_id": str(tema["id"]),
            "atualizado_em": "2026-09-01",
            "resumo": "O que responder.",
        },
        files={"arquivo": ("qa.pdf", PDF, "application/pdf")},
    )
    assert criada.status_code == 201, criada.text
    id_ = criada.json()["id"]

    na_biblioteca = {r["id"]: r for r in admin.get("/api/referencias").json()}
    assert id_ in na_biblioteca and na_biblioteca[id_]["ativo"] is True

    # O PUT é a ficha INTEIRA, e não um remendo: quem desativa manda o resto
    # igual. Foi assim que a rota foi desenhada, e o teste fala a língua dela.
    desativada = admin.put(
        f"/api/referencias/{id_}",
        json={
            "titulo": criada.json()["titulo"],
            "tipo": "qa",
            "tema_principal_id": tema["id"],
            "temas": [],
            "resumo": "O que responder.",
            "ativo": False,
        },
    )
    assert desativada.status_code == 200, desativada.text
    na_biblioteca = {r["id"]: r for r in admin.get("/api/referencias").json()}
    assert na_biblioteca[id_]["ativo"] is False


# -- nada no caminho pode guardar uma resposta -----------------------------------


@pytest.mark.parametrize(
    "caminho",
    [
        "/api/dicionarios",
        "/api/instituicoes",
        "/api/interlocutores",
        "/api/pessoas-aegea",
        "/api/referencias",
    ],
)
def test_as_leituras_do_catalogo_proibem_cache(admin, caminho):
    """`Cache-Control: no-store` em toda leitura que alimenta o catálogo.

    Sem isto, um proxy, uma CDN ou o próprio navegador poderia guardar a lista e
    servi-la de novo — e um cadastro feito na Administração não apareceria
    para NINGUÉM até a cópia vencer. `no-store` é o único valor que proíbe
    guardar; `no-cache` só obriga a revalidar.
    """
    resposta = admin.get(caminho)
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers.get("cache-control") == "no-store"


def test_ate_a_recusa_e_o_vazio_proibem_cache(admin):
    """O cabeçalho vem do middleware, e vale para TODA resposta — inclusive o
    204 de uma remoção e o 404 de um id que não existe. Uma recusa guardada
    esconderia o cadastro que veio logo depois."""
    instituicao = admin.post(
        "/api/instituicoes",
        json={"nome": f"Casa {_sufixo()}", "tipo": "orgao", "uf": "DF"},
    ).json()
    pessoa = admin.post(
        "/api/interlocutores",
        json={"nome": f"Pessoa {_sufixo()}", "instituicao_id": instituicao["id"]},
    ).json()

    sem_corpo = admin.delete(f"/api/interlocutores/{pessoa['id']}")
    assert sem_corpo.status_code == 204
    assert sem_corpo.headers.get("cache-control") == "no-store"

    nao_existe = admin.get(f"/api/instituicoes/{uuid4()}")
    assert nao_existe.status_code in (404, 405)
    assert nao_existe.headers.get("cache-control") == "no-store"
