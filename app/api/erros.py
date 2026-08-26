"""Tradução de erro de domínio para resposta HTTP.

O domínio não importa FastAPI. Este módulo é a única ponte entre os dois.

O QUE SAI NA RESPOSTA, E O QUE FICA SÓ NO LOG

A mensagem COMPLETA vai sempre para o log. O que muda é o que o cliente recebe,
e quem decide é o próprio erro (`publica`, em `app/dominio/erros.py`): mensagem sobre
o PEDIDO é específica para todos; sobre o SISTEMA, específica só para quem é da
casa; sobre a EXISTÊNCIA de um registro, genérica sempre.

Toda resposta de erro leva uma `referencia`. Com mensagem genérica, ela é o que
permite a alguém dizer ao suporte "deu erro, código 4f2a1c" e o suporte achar a
linha exata — sem a referência, "acesso negado" é indistinguível de qualquer
outro "acesso negado" do dia.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.dominio.erros import (
    ErroDeDominio,
    NaoAutorizado,
    NaoEncontrado,
    RegraViolada,
)
from app.observabilidade import obter_logger
from app.seguranca.limite_de_taxa import (
    ExcessoDeRequisicoes,
    resposta_de_excesso,
)

logger = obter_logger("erros")

_STATUS_POR_ERRO: list[tuple[type[ErroDeDominio], int]] = [
    (NaoEncontrado, 404),
    (NaoAutorizado, 403),
    (RegraViolada, 422),
]


def _referencia() -> str:
    """Um código curto para o usuário citar ao suporte.

    Oito caracteres: suficiente para achar a linha no log de um dia, curto o
    bastante para alguém ditar por telefone sem errar.
    """
    return uuid4().hex[:8]


def _e_externo(requisicao: Request) -> bool:
    """Quem está pedindo é de fora?

    Na dúvida, SIM. Se a identidade ainda não foi resolvida — erro no meio da
    própria autenticação, por exemplo —, o lado seguro é o genérico: uma
    mensagem específica a mais para alguém de fora custa mais do que uma
    mensagem genérica a mais para alguém da casa.
    """
    usuario = getattr(requisicao.state, "usuario", None)
    if usuario is None:
        return True

    # `getattr` com padrão `True`, pelos dois motivos ao mesmo tempo: não
    # estourar dentro do tratador de erro, e cair no lado seguro quando não dá
    # para saber. Ler o atributo direto fazia um `request.state.usuario`
    # incompleto virar 500 em cima de um 403.
    return bool(getattr(usuario, "externo", True))


def _quem(requisicao: Request) -> dict[str, object]:
    """Identificação de quem pediu, para o log.

    Sem isto, "403 em rajada de um mesmo usuário" — a consulta que detecta
    alguém sondando permissões — é impossível de escrever: o log dizia que
    houve quarenta 403 e não dizia se foram quarenta pessoas ou uma.

    Ausente quando a falha acontece antes de a identidade ser resolvida. Isso
    também é informação: 403 sem usuário é tentativa de entrar, não de escalar.
    """
    usuario = getattr(requisicao.state, "usuario", None)
    if usuario is None:
        return {"usuario_id": "", "usuario_email": "", "externo": False}

    # `getattr` com padrão, e não acesso direto.
    #
    # Um tratador de erro que ESTOURA transforma todo erro de domínio em 500 —
    # e a falha aparece longe da causa, sem relação óbvia com quem a provocou.
    # É o único lugar do sistema onde vale ser paranoico com forma: qualquer
    # coisa colocada em `request.state.usuario` chega aqui.
    return {
        "usuario_id": str(getattr(usuario, "id", "") or ""),
        "usuario_email": str(getattr(usuario, "email", "") or ""),
        "externo": bool(getattr(usuario, "externo", False)),
    }


def registrar_tratadores(app: FastAPI) -> None:
    async def tratar(requisicao: Request, erro: Exception) -> JSONResponse:
        status = 400
        for tipo, codigo in _STATUS_POR_ERRO:
            if isinstance(erro, tipo):
                status = codigo
                break

        referencia = _referencia()
        externo = _e_externo(requisicao)
        publica = erro.publica(externo=externo) if isinstance(erro, ErroDeDominio) else str(erro)

        # Antes daqui o erro de domínio era devolvido em JSON e desaparecia.
        # Um 403 repetido é tentativa de acesso indevido; uma enxurrada de 422
        # é o front mandando dado inválido. Nenhum dos dois se enxerga sem log.
        logger.warning(
            "%s em %s %s: %s",
            type(erro).__name__,
            requisicao.method,
            requisicao.url.path,
            # A mensagem COMPLETA, mesmo quando a resposta for genérica: é aqui
            # que ela serve, e é aqui que ninguém de fora lê.
            erro,
            extra={
                "erro": type(erro).__name__,
                "status": status,
                "metodo": requisicao.method,
                "rota": requisicao.url.path,
                "consulta": str(requisicao.url.query) or "",
                "referencia": referencia,
                # `true` marca as respostas em que o usuário viu menos do que o
                # log registra — é o filtro para investigar reclamação de
                # "erro sem explicação".
                "resposta_generica": publica != str(erro),
                **_quem(requisicao),
            },
        )
        return JSONResponse(
            status_code=status,
            content={"detalhe": publica, "referencia": referencia},
        )

    app.add_exception_handler(ErroDeDominio, tratar)

    async def tratar_excesso(requisicao: Request, erro: Exception) -> JSONResponse:
        """429 com `Retry-After`, e o registro de quem bateu no teto.

        Precisa de tratador próprio porque `tratar` não devolve cabeçalho, e sem
        `Retry-After` o cliente tenta de novo na hora — o que transforma o limite
        em amplificador em vez de freio.
        """
        assert isinstance(erro, ExcessoDeRequisicoes)
        logger.warning(
            "Limite de taxa atingido em %s %s",
            requisicao.method,
            requisicao.url.path,
            extra={
                "erro": "ExcessoDeRequisicoes",
                # `evento` e `camada` espelham o que o middleware por IP emite,
                # para uma consulta só enxergar as duas camadas.
                "evento": "limite_por_usuario",
                "camada": "usuario",
                "status": 429,
                "metodo": requisicao.method,
                "rota": requisicao.url.path,
                "espera_segundos": round(erro.espera_segundos, 2),
                **_quem(requisicao),
            },
        )
        return resposta_de_excesso(erro.espera_segundos)

    app.add_exception_handler(ExcessoDeRequisicoes, tratar_excesso)

    # NÃO existe tratador para `CorpoGrandeDemais`, e a ausência é deliberada.
    #
    # A exceção nasce dentro de `receive()`, e o FastAPI embrulha toda falha na
    # leitura do corpo num `HTTPException(400)` antes que qualquer tratador
    # registrado aqui a veja. Um tratador para ela seria código morto que
    # parece cobertura — e alguém leria o 413 no código e concluiria que a
    # resposta sai com esse status.
    #
    # Quem corrige o status é o próprio `LimiteDeCorpoMiddleware`, no envio.

    # Não existe tratador global de `ValueError` de propósito.
    #
    # Um deles converteria QUALQUER ValueError do processo em 422 — inclusive
    # os que nascem de bug interno, que devem ser 500. O cliente receberia
    # "seu pedido está errado" quando o errado é o servidor, e a mensagem
    # interna vazaria junto. Entrada inválida levanta `RegraViolada`, que é
    # explícita e some daqui pelo tratador acima.
