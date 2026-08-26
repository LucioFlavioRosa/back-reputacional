"""A instrumentação precisa sobreviver a quem mexer nela depois.

Nenhum destes testes precisa de banco: são sobre a pilha HTTP e o formato do
que é registrado.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.configuracao import obter_configuracao
from app.observabilidade import (
    PARAMETROS_SIGILOSOS,
    _consulta_sanitizada,
)
from main import app

# -- ordem da pilha de middleware --------------------------------------------
#
# Esta é a parte frágil: `add_middleware` insere no INÍCIO, então o último
# registrado fica mais externo. Trocar duas linhas em `main.py` desfaz tudo, e
# o sintoma em produção seria indireto — o navegador veria erro opaco de rede
# em vez do 5xx, e o frontend registraria a falha errada.


def test_cors_fica_por_fora_da_observabilidade():
    pilha = [m.cls.__name__ for m in app.user_middleware]

    assert pilha.index("CORSMiddleware") < pilha.index("BaseHTTPMiddleware"), (
        "O CORS precisa ficar mais externo que o middleware de observabilidade, "
        "senão a resposta 500 sai sem cabeçalho CORS. Em `main.py`, "
        "`configurar_observabilidade` vem ANTES de `add_middleware(CORSMiddleware)`."
    )


def test_erro_500_devolve_cabecalho_cors():
    """Sem isto o navegador vê erro opaco e o front reporta 'falha de rede'."""
    origem = obter_configuracao().origens_permitidas[0]

    @app.get("/api/_erro_de_teste")
    def _erro_de_teste() -> dict:
        raise RuntimeError("defeito interno")

    try:
        cliente = TestClient(app, raise_server_exceptions=False)
        resposta = cliente.get("/api/_erro_de_teste", headers={"Origin": origem})

        assert resposta.status_code == 500
        assert resposta.headers.get("access-control-allow-origin") == origem
    finally:
        app.router.routes = [
            rota
            for rota in app.router.routes
            if getattr(rota, "path", None) != "/api/_erro_de_teste"
        ]


def test_erro_500_nao_vaza_detalhe_interno():
    """A mensagem interna fica no log, não na resposta."""

    @app.get("/api/_erro_sigiloso")
    def _erro_sigiloso() -> dict:
        raise RuntimeError("senha=abc123 no meio do stack")

    try:
        cliente = TestClient(app, raise_server_exceptions=False)
        resposta = cliente.get("/api/_erro_sigiloso")

        assert resposta.status_code == 500
        assert "senha" not in resposta.text
        corpo = resposta.json()
        assert corpo["detalhe"] == "Erro interno. A falha foi registrada."
        # A referência liga a reclamação ("deu erro, código 4f2a1c") à linha do
        # log. Sem ela, "erro interno" é indistinguível de qualquer outro do dia.
        assert len(corpo["referencia"]) == 8
    finally:
        app.router.routes = [
            rota
            for rota in app.router.routes
            if getattr(rota, "path", None) != "/api/_erro_sigiloso"
        ]


# -- sigilo na query string ---------------------------------------------------


def test_busca_livre_nao_vai_para_o_log():
    """`q` é texto digitado por uma pessoa — pode conter nome ou assunto sensível."""
    sanitizada = _consulta_sanitizada("q=jornalista do Valor&frente=imprensa")

    assert "jornalista" not in sanitizada
    assert "q=<19 caracteres>" in sanitizada
    # O resto continua legível: é o que permite reproduzir a falha.
    assert "frente=imprensa" in sanitizada


def test_demais_filtros_permanecem_legiveis():
    sanitizada = _consulta_sanitizada("frente=governo&tier=1&uf=SP&grupo=aberto")
    assert sanitizada == "frente=governo&tier=1&uf=SP&grupo=aberto"


def test_query_vazia_nao_quebra():
    assert _consulta_sanitizada("") == ""


def test_a_lista_de_sigilosos_cobre_a_busca():
    assert "q" in PARAMETROS_SIGILOSOS


def test_atributo_registrado_ja_vem_sanitizado():
    """O que chega ao Application Insights é o valor sanitizado, não o original."""
    capturados: list[logging.LogRecord] = []

    class Espiao(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            capturados.append(registro)

    espiao = Espiao()
    logger = logging.getLogger("painel_reputacional")
    logger.addHandler(espiao)

    try:
        TestClient(app).get("/api/saude?q=texto%20sigiloso")
    finally:
        logger.removeHandler(espiao)

    consultas = [r.consulta for r in capturados if hasattr(r, "consulta")]
    assert consultas, "nenhuma requisição foi registrada"
    assert all("sigiloso" not in c for c in consultas)


# -- atributos achatados ------------------------------------------------------


def test_atributos_vao_achatados_e_nao_aninhados():
    """`customDimensions` é um mapa plano: dicionário aninhado viraria JSON
    encapsulado, e toda consulta KQL precisaria de `parse_json`."""
    capturados: list[logging.LogRecord] = []

    class Espiao(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            capturados.append(registro)

    espiao = Espiao()
    logger = logging.getLogger("painel_reputacional")
    logger.addHandler(espiao)

    try:
        TestClient(app).get("/api/saude")
    finally:
        logger.removeHandler(espiao)

    registro = next(r for r in capturados if hasattr(r, "rota"))

    for atributo in ("metodo", "rota", "status", "duracao_ms"):
        assert hasattr(registro, atributo), f"faltou o atributo {atributo}"
        valor = getattr(registro, atributo)
        assert isinstance(valor, (str, int, float, bool)), (
            f"{atributo} precisa ser escalar para virar customDimensions, "
            f"veio {type(valor).__name__}"
        )

    assert not hasattr(registro, "contexto"), (
        "atributo aninhado voltou; o KQL depende dos campos achatados"
    )


@pytest.mark.parametrize("rota", ["/api/saude"])
def test_requisicao_bem_sucedida_e_registrada(rota):
    capturados: list[logging.LogRecord] = []

    class Espiao(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            capturados.append(registro)

    espiao = Espiao()
    logger = logging.getLogger("painel_reputacional")
    logger.addHandler(espiao)

    try:
        TestClient(app).get(rota)
    finally:
        logger.removeHandler(espiao)

    registro = next(r for r in capturados if getattr(r, "rota", None) == rota)
    assert registro.status == 200
    assert registro.levelno == logging.INFO
