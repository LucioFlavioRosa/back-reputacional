"""Telemetria e log estruturado.

Duas coisas que o sistema não tinha e que impedem manutenção corretiva:

1. **Nada era registrado.** O tratador de erro devolvia JSON e engolia a
   exceção. Um 403, um 422 ou um 404 não deixavam rastro nenhum, e um 500
   deixava só o stderr do uvicorn — efêmero e não consultável.
2. **Nada correlacionava.** Sem `operation_Id` compartilhado, um erro visto
   pelo usuário no navegador e a falha no backend eram dois eventos soltos.

O log estruturado funciona **sempre**, com ou sem Azure: em desenvolvimento
sai no terminal, no App Service cai no log stream. O Application Insights é
uma camada por cima, ligada só quando a connection string existe — sem ela o
aplicativo sobe igual, sem erro e sem telemetria.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.configuracao import Configuracao

#: Namespace de todos os nossos loggers. O Azure Monitor é anexado a ele, então
#: `logging.getLogger("painel_reputacional.<qualquer coisa>")` já vai para o
#: App Insights sem configuração adicional.
#:
#: É o nome do SERVIÇO, e não o do pacote Python (que é `app`). Não são a mesma
#: coisa de propósito: o App Insights é compartilhado com o front, e um
#: namespace chamado "app" não distinguiria nada. Alinhado com
#: `nome_do_servico` em `configuracao.py`.
NAMESPACE = "painel_reputacional"

logger = logging.getLogger(NAMESPACE)

#: Requisição acima disso vira aviso, mesmo tendo dado certo. Com algumas
#: centenas de registros, qualquer coisa nessa faixa é sintoma.
LIMITE_DE_LENTIDAO_MS = 1500

#: Parâmetros cujo VALOR não vai para o log.
#:
#: `q` é a busca livre: texto digitado por uma pessoa da Aegea, que pode conter
#: nome de jornalista ou assunto sensível. O log registra que houve busca e o
#: tamanho do termo — o suficiente para reproduzir "busca longa derrubou a
#: tela" — sem guardar o que foi digitado.
PARAMETROS_SIGILOSOS = frozenset({"q"})


def _consulta_sanitizada(query: str) -> str:
    """Query string com os valores sigilosos substituídos."""
    if not query:
        return ""

    partes = []
    for chave, valor in parse_qsl(query, keep_blank_values=True):
        if chave in PARAMETROS_SIGILOSOS:
            partes.append(f"{chave}=<{len(valor)} caracteres>")
        else:
            partes.append(f"{chave}={valor}")
    return "&".join(partes)


def configurar_observabilidade(app: FastAPI, configuracao: Configuracao) -> None:
    """Liga o log estruturado e, se houver connection string, a telemetria."""
    _configurar_log(configuracao)
    _ligar_azure_monitor(configuracao)
    app.middleware("http")(_registrar_requisicao)


def _configurar_log(configuracao: Configuracao) -> None:
    """Log em stdout — é de lá que o App Service e o Docker coletam."""
    if logger.handlers:
        return

    # Só a política de erro muda; o encoding do terminal fica como está.
    #
    # Forçar UTF-8 aqui foi tentador e errado: o console do Windows abre em
    # cp1252, que ACEITA acento — trocar para UTF-8 fazia "não" virar "nÃ£o"
    # na saída. O que de fato estourava era um caractere fora do cp1252 (a
    # seta "→", já removida das mensagens). Com `backslashreplace`, qualquer
    # caractere futuro fora do encoding vira escape legível em vez de derrubar
    # a linha inteira de log.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="backslashreplace")
        except (ValueError, OSError):
            pass

    saida = logging.StreamHandler(sys.stdout)
    saida.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(saida)
    logger.setLevel(logging.DEBUG if not configuracao.producao else logging.INFO)
    # Sem isso, cada mensagem sairia duas vezes quando o uvicorn configura a raiz.
    logger.propagate = False


def _ligar_azure_monitor(configuracao: Configuracao) -> None:
    if not configuracao.applicationinsights_connection_string:
        logger.info(
            "Telemetria desligada: APPLICATIONINSIGHTS_CONNECTION_STRING não definida. "
            "O log continua saindo em stdout."
        )
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning(
            "azure-monitor-opentelemetry não está instalado; telemetria desligada."
        )
        return

    configure_azure_monitor(
        connection_string=configuracao.applicationinsights_connection_string,
        # `logger_name` anexa o exportador ao nosso namespace: tudo que passa por
        # `logging.getLogger("painel_reputacional...")` vira trace no App Insights.
        logger_name=NAMESPACE,
        # Vira `cloud_RoleName`. É o que separa este serviço do frontend no mesmo
        # recurso de App Insights e o que faz o Application Map desenhar a seta
        # de um para o outro.
        resource_attributes={
            "service.name": configuracao.nome_do_servico,
            "service.namespace": "painel-reputacional",
            "deployment.environment": configuracao.ambiente,
        },
    )
    logger.info(
        "Telemetria ligada como %s (%s).",
        configuracao.nome_do_servico,
        configuracao.ambiente,
    )


async def _registrar_requisicao(
    requisicao: Request, seguir: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Registra o desfecho de cada requisição, com o contexto que torna o erro
    reproduzível: método, rota, status, duração e a query string.

    A query string importa mais do que parece — nas rotas de leitura ela **é** o
    Recorte. "Falhou ao listar com frente=legislativo&uf=SP" é diagnosticável;
    um stack trace sozinho não é.
    """
    comeco = time.perf_counter()

    # Os atributos vão ACHATADOS, não como dicionário aninhado.
    #
    # `customDimensions` no Application Insights é um mapa plano de strings: um
    # dicionário aninhado chegaria lá como um JSON encapsulado, e toda consulta
    # KQL precisaria de `parse_json` para ler qualquer campo. Plano, vira
    # `customDimensions.rota` direto — filtrável e agrupável.
    contexto = {
        "metodo": requisicao.method,
        "rota": requisicao.url.path,
        "consulta": _consulta_sanitizada(str(requisicao.url.query)),
    }

    try:
        resposta = await seguir(requisicao)
    except Exception:
        duracao = round((time.perf_counter() - comeco) * 1000)
        # O código que o usuário vê na tela e cita ao suporte. Com mensagem
        # genérica, é a única coisa que liga a reclamação à linha do log.
        referencia = uuid4().hex[:8]
        # `exception` grava o stack completo. Este é o caminho do 500: sem ele,
        # a falha só existiria no stderr do processo.
        logger.exception(
            "Falha não tratada em %s %s",
            requisicao.method,
            requisicao.url.path,
            extra={
                **contexto,
                "duracao_ms": duracao,
                "desfecho": "excecao",
                "referencia": referencia,
            },
        )

        # A resposta é montada AQUI, e não relançada.
        #
        # O `ServerErrorMiddleware` do Starlette fica por fora de todo
        # middleware de usuário, inclusive do CORS: um 500 gerado por lá sai
        # SEM `access-control-allow-origin`. O navegador então enxerga erro
        # opaco de rede em vez do 5xx real — e o frontend registraria "falha
        # de rede", mascarando justamente o erro de servidor que esta
        # instrumentação existe para capturar.
        #
        # Devolvendo daqui, a resposta ainda atravessa o CORS na volta. Isso
        # exige que o CORS seja registrado DEPOIS deste middleware em
        # `main.py` — as duas coisas juntas, uma só não basta.
        #
        # A mensagem é genérica de propósito: o detalhe interno fica no log,
        # não na resposta.
        return JSONResponse(
            status_code=500,
            content={
                "detalhe": "Erro interno. A falha foi registrada.",
                # Sem isto, "erro interno" é indistinguível de qualquer outro
                # erro interno do dia, e quem reclama não tem como apontar qual.
                "referencia": referencia,
            },
        )

    duracao = round((time.perf_counter() - comeco) * 1000)

    if resposta.status_code >= 500:
        nivel = logging.ERROR
    elif resposta.status_code >= 400 or duracao > LIMITE_DE_LENTIDAO_MS:
        # 4xx em massa é sintoma de front mandando dado errado; lentidão em
        # requisição bem-sucedida é sintoma de consulta degradando.
        nivel = logging.WARNING
    else:
        nivel = logging.INFO

    logger.log(
        nivel,
        "%s %s -> %s em %dms",
        requisicao.method,
        requisicao.url.path,
        resposta.status_code,
        duracao,
        extra={
            **contexto,
            "status": resposta.status_code,
            "duracao_ms": duracao,
            "lenta": duracao > LIMITE_DE_LENTIDAO_MS,
            **_quem_pediu(requisicao),
        },
    )
    return resposta


def _quem_pediu(requisicao: Request) -> dict[str, object]:
    """Identidade da requisição, para as consultas de segurança.

    Sai o ID, NÃO o e-mail. A distinção é deliberada:

    Toda requisição gera uma linha, e são milhares por dia. E-mail em todas elas
    encheria a telemetria de dado pessoal — que passa a ter prazo de retenção,
    regra de acesso e obrigação de apagar. UUID é pseudônimo: serve para
    agrupar ("esta conta fez 400 requisições às 3h") sem carregar identidade.

    O e-mail aparece só nos eventos de SEGURANÇA — 403 em rajada, login negado,
    relatório com registros — que são raros e nos quais alguém precisa agir
    rápido, e ir ao banco traduzir o UUID no meio de um incidente é atrito onde
    ele custa mais caro.

    Lido DEPOIS de a resposta voltar: a dependência que resolve a identidade já
    rodou. Antes disso, `state.usuario` não existe.
    """
    usuario = getattr(requisicao.state, "usuario", None)
    if usuario is None:
        return {"usuario_id": "", "externo": False}
    return {
        "usuario_id": str(getattr(usuario, "id", "") or ""),
        "externo": bool(getattr(usuario, "externo", False)),
    }


def obter_logger(sufixo: str) -> logging.Logger:
    """Logger dentro do namespace instrumentado.

        logger = obter_logger("importacao")   →  painel_reputacional.importacao
    """
    return logging.getLogger(f"{NAMESPACE}.{sufixo}")
