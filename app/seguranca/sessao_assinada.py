"""Sessão em cookie assinado.

O cookie carrega quem é a pessoa e até quando vale — nada mais. Nem o
`id_token`, nem claims, nem papel: papel e escopo vêm do banco, e é isso que
impede uma sessão emitida ontem de carregar as permissões de ontem.

A leitura do banco é cacheada por alguns minutos
(`app/seguranca/cache_de_autorizacao.py`), mas a diferença permanece: o que está
em memória o servidor descarta quando quiser, e de fato descarta quando a
permissão muda pela tela. O que estivesse no cookie estaria com o cliente, e só
venceria no prazo dele.

POR QUE ASSINADO E NÃO CIFRADO

O conteúdo não é segredo: é um UUID que a própria pessoa já conhece. O que
precisa ser impossível é **alterá-lo** — trocar o id por outro, ou empurrar a
data de expiração. Assinatura resolve isso; cifra resolveria outro problema, que
não temos.

POR QUE HMAC DA BIBLIOTECA PADRÃO

Nenhuma dependência nova para algo com esta superfície. `hmac.compare_digest`
faz a comparação em tempo constante, que é a única parte sutil: comparar
assinatura com `==` vaza, byte a byte, quanto do palpite estava certo.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

#: Nome do cookie. Prefixo `__Host-` seria melhor — o navegador passa a exigir
#: `Secure`, caminho `/` e proibir `Domain` —, mas ele quebra em http, e o
#: desenvolvimento local roda sem TLS. Fica como item de quando houver HTTPS
#: em todos os ambientes.
NOME_DO_COOKIE = "painel_sessao"

#: Duração da sessão. Oito horas cobre um expediente sem obrigar a reentrar no
#: meio da tarde, e não deixa sessão viva pela noite numa máquina destrancada.
DURACAO_PADRAO = 8 * 3600


class SessaoInvalida(Exception):
    """Cookie ausente, adulterado ou vencido. Vira 401."""


#: Rótulos que separam os dois usos do mesmo mecanismo.
#:
#: O cookie de PEDIDO (que atravessa a ida ao Entra ID) e o de SESSÃO usam o
#: mesmo segredo e o mesmo formato. Sem um rótulo dentro da assinatura, um vale
#: como o outro: bastaria copiar o `painel_pedido` para `painel_sessao` e a
#: leitura aceitaria — com o UUID que o pedido carrega.
#:
#: Hoje isso pararia adiante, porque aquele UUID não existe no banco. Mas
#: "não é explorável porque outra coisa segura" é como se descreve um defeito
#: latente, não um desenho.
TIPO_SESSAO = "s"
TIPO_PEDIDO = "p"


@dataclass(frozen=True, slots=True)
class Sessao:
    usuario_id: UUID
    expira_em: int
    #: Token anti-CSRF. Vive DENTRO do cookie, que é `httpOnly`, então nenhum
    #: script o lê. O front o recebe pelo corpo de `/api/eu` — e é isso que um
    #: site de outra origem não consegue fazer, porque o CORS impede a leitura
    #: da resposta.
    csrf: str
    tipo: str = TIPO_SESSAO

    @property
    def vencida(self) -> bool:
        return time.time() >= self.expira_em


def nova_sessao(usuario_id: UUID, *, duracao: int = DURACAO_PADRAO) -> Sessao:
    return Sessao(
        usuario_id=usuario_id,
        expira_em=int(time.time()) + duracao,
        # 32 bytes de urandom. Token de CSRF previsível é token nenhum.
        csrf=secrets.token_urlsafe(32),
    )


def assinar(sessao: Sessao, segredo: str) -> str:
    corpo = _codificar(
        {
            "u": str(sessao.usuario_id),
            "e": sessao.expira_em,
            "c": sessao.csrf,
            "t": sessao.tipo,
        }
    )
    return f"{corpo}.{_assinatura(corpo, segredo)}"


def ler(valor: str | None, segredo: str, *, tipo: str = TIPO_SESSAO) -> Sessao:
    """Devolve a sessão ou levanta `SessaoInvalida`.

    Toda falha vira a mesma exceção, sem distinguir "assinatura errada" de
    "vencida", "de outro tipo" ou "mal formada": a diferença só interessa a quem
    está tentando forjar.
    """
    if not valor:
        raise SessaoInvalida("Sem sessão.")

    corpo, _, assinatura = valor.partition(".")
    if not corpo or not assinatura:
        raise SessaoInvalida("Sessão mal formada.")

    if not hmac.compare_digest(assinatura, _assinatura(corpo, segredo)):
        raise SessaoInvalida("Assinatura inválida.")

    try:
        dados = json.loads(_decodificar(corpo))
        sessao = Sessao(
            usuario_id=UUID(dados["u"]),
            expira_em=int(dados["e"]),
            csrf=str(dados["c"]),
            tipo=str(dados["t"]),
        )
    except (ValueError, KeyError, TypeError) as erro:
        raise SessaoInvalida("Sessão ilegível.") from erro

    if sessao.tipo != tipo:
        raise SessaoInvalida("Cookie de outro tipo.")

    if sessao.vencida:
        raise SessaoInvalida("Sessão expirada.")

    return sessao


def _assinatura(corpo: str, segredo: str) -> str:
    bruto = hmac.new(segredo.encode(), corpo.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(bruto).decode().rstrip("=")


def _codificar(dados: dict) -> str:
    # `separators` sem espaço: o JSON entra na assinatura, e um byte a mais é
    # um byte a mais em todo cookie de toda requisição.
    bruto = json.dumps(dados, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(bruto).decode().rstrip("=")


def _decodificar(corpo: str) -> bytes:
    # O `=` do padding é removido na codificação porque atrapalha em cookie;
    # aqui ele volta, porque o decodificador exige comprimento múltiplo de 4.
    return base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4))
