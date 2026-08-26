"""Superfície HTTP: cabeçalhos, CORS explícito, tamanho de corpo e `/docs`.

Nada aqui impede um ataque sozinho. São categorias inteiras de erro barato
fechadas por uma linha cada — e o valor de testá-las é que somem em silêncio.
Um cabeçalho que deixa de sair não quebra nada, não aparece em log, e ninguém
percebe até a auditoria.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.configuracao import Configuracao
from app.observabilidade import configurar_observabilidade
from app.seguranca.protecao_http import (
    CabecalhosDeSegurancaMiddleware,
    LimiteDeCorpoMiddleware,
)
from main import criar_app

# -- cabeçalhos ----------------------------------------------------------------


def _app(hsts_ligado: bool = False) -> FastAPI:
    """Espelha a pilha de `main.py`, inclusive a observabilidade.

    A observabilidade nao esta aqui por completude: e ela que TRANSFORMA a
    excecao em resposta. Sem ela, o 500 vem do `ServerErrorMiddleware` do
    Starlette, que fica por FORA de todo middleware de usuario — e a resposta
    sai sem cabecalho nenhum. Foi o que este teste descobriu.
    """
    app = FastAPI()
    app.add_middleware(LimiteDeCorpoMiddleware, maximo=100)
    configurar_observabilidade(app, Configuracao())
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(CabecalhosDeSegurancaMiddleware, hsts_ligado=hsts_ligado)

    @app.get("/api/coisa")
    def coisa() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/coisa")
    def criar(corpo: dict) -> dict:
        return corpo

    @app.get("/api/explode")
    def explode() -> None:
        raise RuntimeError("falha interna")

    return app


@pytest.mark.parametrize(
    "cabecalho,valor",
    [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
    ],
)
def test_cabecalhos_de_seguranca_saem_na_resposta(cabecalho, valor):
    resposta = TestClient(_app()).get("/api/coisa")
    assert resposta.headers[cabecalho] == valor


def test_csp_fecha_tudo():
    """`default-src 'none'` numa API JSON é seguro de graça.

    Serve para o dia em que alguma rota devolver HTML por engano — página de
    erro de proxy, retorno de biblioteca, um `/docs` esquecido ligado.
    """
    csp = TestClient(_app()).get("/api/coisa").headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_referrer_policy_protege_a_query_string():
    """A URL carrega o recorte — e `q=` carrega termo de busca.

    Sem `no-referrer`, o termo pesquisado viaja no `Referer` para qualquer
    destino que a resposta acabe alcançando. Um termo de busca aqui pode ser o
    nome de uma pessoa.
    """
    resposta = TestClient(_app()).get("/api/coisa?q=nome%20de%20alguem")
    assert resposta.headers["Referrer-Policy"] == "no-referrer"


def test_cabecalhos_saem_tambem_no_erro():
    """O caso que uma pilha mal montada perde.

    O 500 é a resposta em que o conteúdo é menos previsível, e é justamente a
    que escapa com facilidade: o `ServerErrorMiddleware` do Starlette fica por
    FORA de todo middleware de usuário. Se ninguém transformar a exceção em
    resposta antes dele, ela sai sem cabeçalho de segurança e sem CORS.

    Quem faz essa transformação aqui é a observabilidade — mesma razão pela
    qual o CORS funciona no 500. Este teste amarra as duas coisas: se alguém
    fizer o middleware de observabilidade relançar em vez de responder, cai
    aqui.
    """
    cliente = TestClient(_app(), raise_server_exceptions=False)
    resposta = cliente.get("/api/explode")
    assert resposta.status_code == 500
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in resposta.headers["Content-Security-Policy"]


def test_hsts_so_sai_quando_ligado():
    """Desligado por padrão porque o efeito é duradouro e difícil de desfazer.

    O navegador guarda a instrução por `max-age` inteiro e passa a recusar http
    no domínio e nos subdomínios.
    """
    assert "Strict-Transport-Security" not in TestClient(_app()).get("/api/coisa").headers

    ligado = TestClient(_app(hsts_ligado=True)).get("/api/coisa")
    valor = ligado.headers["Strict-Transport-Security"]
    assert "max-age=" in valor

    # A metade perigosa fica de fora até alguém pedir: num domínio compartilhado
    # como `aegea.com.br`, `includeSubDomains` obriga HTTPS em TODO subdomínio
    # da companhia, inclusive nos de outros times.
    assert "includeSubDomains" not in valor
    # `preload` nunca sai: entrar naquela lista é praticamente irreversível.
    assert "preload" not in valor


def test_include_subdomains_sai_quando_pedido():
    app = FastAPI()
    app.add_middleware(
        CabecalhosDeSegurancaMiddleware,
        hsts_ligado=True,
        hsts_incluir_subdominios=True,
    )

    @app.get("/api/coisa")
    def coisa() -> dict[str, bool]:
        return {"ok": True}

    valor = TestClient(app).get("/api/coisa").headers["Strict-Transport-Security"]
    assert "includeSubDomains" in valor


# -- CORS explícito ------------------------------------------------------------


def test_preflight_recusa_metodo_fora_da_lista():
    """`allow_methods=["*"]` com `allow_credentials=True` libera todo verbo.

    Não é hipótese: o curinga responde afirmativamente a qualquer método que a
    origem aceita perguntar, inclusive os que esta API nunca implementou.
    """
    cliente = TestClient(_app())
    cabecalhos = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "DELETE",
    }
    resposta = cliente.options("/api/coisa", headers=cabecalhos)
    permitidos = resposta.headers.get("access-control-allow-methods", "")
    assert "DELETE" not in permitidos


def test_preflight_aceita_o_que_o_front_usa():
    cliente = TestClient(_app())
    resposta = cliente.options(
        "/api/coisa",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resposta.status_code == 200
    assert "POST" in resposta.headers["access-control-allow-methods"]


def test_configuracao_padrao_cobre_os_verbos_do_front():
    """Amarra a lista ao que `cliente.ts` de fato dispara.

    Se alguém acrescentar um verbo no front sem tocar aqui, o navegador recusa o
    preflight e a chamada falha — melhor descobrir neste teste.
    """
    padrao = Configuracao()
    for verbo in ("GET", "POST", "PATCH", "DELETE"):
        assert verbo in padrao.metodos_permitidos
    assert "Content-Type" in padrao.cabecalhos_permitidos


# -- tamanho de corpo ----------------------------------------------------------


def test_corpo_dentro_do_limite_passa():
    cliente = TestClient(_app())
    assert cliente.post("/api/coisa", json={"a": "b"}).status_code == 200


def test_corpo_acima_do_limite_e_recusado_com_413():
    cliente = TestClient(_app())
    resposta = cliente.post("/api/coisa", json={"a": "x" * 500})
    assert resposta.status_code == 413


def test_corpo_sem_tamanho_declarado_e_barrado_com_413():
    """`Transfer-Encoding: chunked` é o caso em que a contagem importa.

    Sem `Content-Length` não há o que conferir de antemão, e o corpo chega
    inteiro se ninguém contar enquanto ele passa.

    O status precisa ser 413, e não o 400 genérico do FastAPI ("There was an
    error parsing the body"): 400 se confunde com JSON malformado do próprio
    front, e alerta sobre corpo grande fica impossível de escrever.
    """

    def pedacos():
        yield b'{"a":"'
        for _ in range(50):
            yield b"x" * 200
        yield b'"}'

    cliente = TestClient(_app(), raise_server_exceptions=False)
    resposta = cliente.post(
        "/api/coisa", content=pedacos(), headers={"Content-Type": "application/json"}
    )
    assert resposta.status_code == 413


def test_content_length_mentiroso_nao_e_aceito():
    """O cabeçalho é declaração do cliente, não fato.

    Em HTTP/1.1 quem mente para MENOS não consegue muita coisa: o servidor lê
    exatamente os bytes declarados e o excedente nem chega. A requisição é
    recusada de qualquer forma — o que este teste garante é que ela nunca é
    aceita como válida.
    """
    cliente = TestClient(_app(), raise_server_exceptions=False)
    corpo = json.dumps({"a": "x" * 5000}).encode()
    resposta = cliente.post(
        "/api/coisa",
        content=corpo,
        headers={"Content-Type": "application/json", "Content-Length": "10"},
    )
    assert resposta.status_code in (400, 413)
    assert resposta.status_code != 200


# -- /docs ---------------------------------------------------------------------


def producao_valida(**ajustes) -> Configuracao:
    """Uma produção que a conferência de subida aceita."""
    padrao = dict(
        ambiente="producao",
        auth_mock=False,
        origens_permitidas=["https://painel.aegea.com.br"],
        proxies_confiaveis=1,
        # Telemetria vazia de propósito: uma connection string faria o
        # exportador do Azure tentar conectar de verdade durante o teste. A
        # conferência de subida só AVISA sobre isso — não recusa —, então o
        # `criar_app` sobe normalmente.
        applicationinsights_connection_string=None,
        docs_publicos=False,
        # Segredo próprio: o padrão do código está no Git, e a conferência
        # de subida recusa produção com ele.
        sessao_secreta="x" * 48,
        # SSO ligado exige as três: sem elas ninguém entra, e o erro só
        # apareceria quando a primeira pessoa tentasse.
        entra_tenant_id="tenant",
        entra_client_id="cliente",
        entra_client_secret="segredo",
        # Explícito: o padrão do código aponta para localhost, e a conferência
        # de subida recusa isso em produção.
        banco_url=(
            "postgresql+psycopg2://app:x@servidor.postgres.database.azure.com"
            "/painel?sslmode=require"
        ),
    )
    return Configuracao(**{**padrao, **ajustes})


def test_docs_somem_em_producao(monkeypatch):
    """`/docs` desenha cada rota, cada campo e cada formato.

    Enquanto o acesso era interno isso era conveniência. Com gente de fora, é
    entregar o mapa da superfície de ataque — e esconder o link não basta: a
    rota precisa deixar de existir.
    """
    # Produção CONFIGURADA, e não apenas `ambiente="producao"`: a conferência
    # de subida recusa uma produção com os padrões de desenvolvimento, e o
    # teste passaria a medir a recusa em vez do que se quer medir aqui.
    monkeypatch.setattr(
        "main.obter_configuracao", lambda: producao_valida()
    )

    cliente = TestClient(criar_app())
    assert cliente.get("/docs").status_code == 404
    assert cliente.get("/openapi.json").status_code == 404


def test_docs_continuam_em_desenvolvimento():
    cliente = TestClient(criar_app())
    assert cliente.get("/docs").status_code == 200
