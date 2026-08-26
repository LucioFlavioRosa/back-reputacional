"""Ponto de entrada da API.

    uvicorn main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# -- as rotas ------------------------------------------------------------------
from app.api import (
    acesso,
    catalogo,
    interacoes,
    metricas,
    relatorios,
    stakeholders,
)

# -- plataforma ----------------------------------------------------------------
from app.api.erros import registrar_tratadores

# -- as tabelas ----------------------------------------------------------------
#
# Importadas aqui, e nunca usadas diretamente, porque o SQLAlchemy só resolve as
# chaves estrangeiras entre módulos depois que TODOS os mapeamentos existem. Sem
# estas linhas, a primeira consulta que atravessasse dois módulos falharia com
# "failed to locate a name" — e só em tempo de execução.
from app.banco import (  # noqa: F401
    tabelas_acesso,
    tabelas_catalogo,
    tabelas_interacoes,
    tabelas_relatorios,
    tabelas_stakeholders,
)
from app.configuracao import obter_configuracao
from app.observabilidade import configurar_observabilidade
from app.seguranca.limite_de_taxa import LimiteDeTaxaMiddleware, RegistroDeBaldes
from app.seguranca.protecao_http import (
    CabecalhosDeSegurancaMiddleware,
    LimiteDeCorpoMiddleware,
)
from app.seguranca.verificacao_de_producao import conferir


def criar_app() -> FastAPI:
    configuracao = obter_configuracao()

    # Recusa subir com configuração que torna um controle inexistente. É a
    # única checagem do sistema que impede a inicialização, e o motivo é que
    # variável de ambiente errada não aparece em lugar nenhum: o serviço sobe,
    # responde 200, e a proteção simplesmente não está lá.
    conferir(configuracao)

    # `/docs` e `/redoc` desenham a superfície inteira da API. Enquanto o
    # acesso era só interno isso era conveniência; com gente de fora, é entregar
    # o mapa. `None` remove as rotas — não basta esconder o link.
    docs = configuracao.docs_publicos and not configuracao.producao

    app = FastAPI(
        title="Painel Reputacional Aegea",
        description="CRM dos Stakeholders — cadastro e análise das interações institucionais.",
        version="0.1.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    # ORDEM IMPORTA. `add_middleware` insere no INÍCIO da pilha, então o
    # último registrado fica mais EXTERNO. A pilha final, de fora para dentro:
    #
    #     cabeçalhos  ->  CORS  ->  observabilidade
    #                 ->  limite de taxa  ->  limite de corpo  ->  rotas
    #
    # Os cabeçalhos de segurança por FORA de tudo: precisam sair em toda
    # resposta, inclusive no 429 do limite e no 500 da observabilidade. Por
    # dentro, a recusa escaparia justamente nas respostas de erro.
    #
    # O limite de corpo mais interno: só faz sentido depois de a requisição ter
    # passado pelo limite de taxa — recusar por tamanho antes de recusar por
    # frequência seria ler o corpo de quem já deveria ter sido barrado.
    #
    # O CORS por fora de tudo: sem isso, a resposta 500 que a observabilidade
    # devolve — e o 429 que o limite devolve — chegam sem os cabeçalhos, e o
    # navegador vê erro opaco de rede em vez do erro real. Verificado com teste.
    #
    # O limite por DENTRO da observabilidade, e não por fora: um 429 é sinal de
    # incidente, e fora dela a recusa não apareceria em log nenhum — o ataque
    # ficaria invisível justamente enquanto está sendo barrado.
    app.add_middleware(
        LimiteDeCorpoMiddleware, maximo=configuracao.tamanho_maximo_do_corpo
    )

    if configuracao.limite_de_taxa_ligado:
        app.add_middleware(
            LimiteDeTaxaMiddleware,
            registro=RegistroDeBaldes(
                capacidade=configuracao.limite_por_ip_capacidade,
                por_segundo=configuracao.limite_por_ip_por_segundo,
            ),
            proxies_confiaveis=configuracao.proxies_confiaveis,
        )

    configurar_observabilidade(app, configuracao)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=configuracao.origens_permitidas,
        allow_credentials=True,
        # Explícitos, e não `["*"]`: com `allow_credentials=True` o curinga
        # libera para a origem aceita qualquer verbo e qualquer cabeçalho,
        # inclusive os que esta API nunca usou.
        allow_methods=configuracao.metodos_permitidos,
        allow_headers=configuracao.cabecalhos_permitidos,
    )

    app.add_middleware(
        CabecalhosDeSegurancaMiddleware,
        hsts_ligado=configuracao.hsts_ligado,
        hsts_max_age=configuracao.hsts_max_age,
        hsts_incluir_subdominios=configuracao.hsts_incluir_subdominios,
    )

    registrar_tratadores(app)

    # Primeiro o de acesso: `/api/auth/*` precisa existir para alguém
    # conseguir entrar, e três das suas rotas são públicas.
    app.include_router(acesso.rotas)
    app.include_router(interacoes.rotas)
    app.include_router(metricas.rotas)
    app.include_router(relatorios.rotas)
    app.include_router(stakeholders.rotas)
    app.include_router(catalogo.rotas)

    @app.get("/api/saude", tags=["plataforma"])
    def saude() -> dict[str, str]:
        return {"situacao": "ok", "ambiente": configuracao.ambiente}

    return app


app = criar_app()
