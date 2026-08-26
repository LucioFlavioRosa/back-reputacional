"""Endurecimento da superfície HTTP: cabeçalhos de segurança e tamanho de corpo.

Nenhuma das duas coisas aqui impede um ataque sozinha. As duas fecham categorias
inteiras de erro barato — do tipo que aparece em varredura automática e em
relatório de auditoria, e que custa uma linha para não existir.

SOBRE CSP NUMA API QUE SÓ DEVOLVE JSON

Parece inútil, e quase é. O valor está no "quase": se algum dia uma rota devolver
HTML por engano — página de erro de um proxy, retorno de biblioteca, um `/docs`
esquecido ligado —, `default-src 'none'` faz esse HTML não conseguir executar
nem carregar nada. É seguro de graça, porque JSON não é afetado.

`frame-ancestors 'none'` é o que de fato importa: impede que a resposta seja
embutida em `iframe` de outro site.

SOBRE HSTS

Só faz sentido sobre HTTPS, e é uma decisão com efeito duradouro: o navegador
guarda a instrução por `max-age` inteiro e passa a recusar http naquele domínio.

Ligado em produção, desligado fora. Mas `includeSubDomains` é opção à parte e
vem desligada, porque é a metade perigosa: num domínio compartilhado como
`aegea.com.br` ela obriga HTTPS em TODO subdomínio da companhia — inclusive nos
que este time não conhece. `preload` nunca é enviado: entrar naquela lista é
praticamente irreversível e é decisão da companhia, não deste serviço.
"""

from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Um megabyte. O maior corpo legítimo é o formulário de interação — campos de
#: texto. Nada aqui recebe arquivo: não existe `UploadFile` em rota nenhuma.
TAMANHO_MAXIMO_DO_CORPO = 1_048_576

#: `default-src 'none'`: nada carrega, nada executa. Uma API JSON não precisa de
#: origem nenhuma, então a política mais restritiva possível é também a correta.
CSP_DE_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


class CabecalhosDeSegurancaMiddleware:
    """ASGI puro, e não `BaseHTTPMiddleware`, de propósito.

    `BaseHTTPMiddleware` materializa a resposta inteira para poder mexer nela.
    Para acrescentar quatro cabeçalhos, isso é caro sem motivo — aqui basta
    interceptar a mensagem `http.response.start`, que carrega os cabeçalhos e
    nada mais.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        hsts_ligado: bool = False,
        hsts_max_age: int = 31_536_000,
        hsts_incluir_subdominios: bool = False,
    ) -> None:
        self.app = app
        self.hsts_ligado = hsts_ligado
        self.hsts_max_age = hsts_max_age
        self.hsts_incluir_subdominios = hsts_incluir_subdominios

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(mensagem: Message) -> None:
            if mensagem["type"] == "http.response.start":
                cabecalhos = MutableHeaders(scope=mensagem)

                # Impede o navegador de adivinhar o tipo do conteúdo. Sem isto,
                # um JSON com texto controlado pelo usuário pode ser
                # interpretado como HTML e executar.
                cabecalhos.setdefault("X-Content-Type-Options", "nosniff")

                # `X-Frame-Options` além do `frame-ancestors` do CSP: navegador
                # antigo não entende o segundo, e o custo de mandar os dois é um
                # cabeçalho.
                cabecalhos.setdefault("X-Frame-Options", "DENY")

                # A URL desta API não deve viajar como `Referer` para terceiros:
                # a query string carrega o recorte — e `q=` carrega termo de
                # busca, que pode ser o nome de uma pessoa.
                cabecalhos.setdefault("Referrer-Policy", "no-referrer")

                cabecalhos.setdefault("Content-Security-Policy", CSP_DE_API)

                # Desliga recursos que uma API jamais usa. Se o navegador chegar
                # a interpretar uma resposta como documento, nada disso abre.
                cabecalhos.setdefault(
                    "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
                )

                if self.hsts_ligado:
                    # `includeSubDomains` NÃO entra por padrão: num domínio
                    # compartilhado ele obriga HTTPS em todo subdomínio da
                    # companhia, inclusive nos de outros times. `preload` nunca
                    # entra: é praticamente irreversível.
                    valor = f"max-age={self.hsts_max_age}"
                    if self.hsts_incluir_subdominios:
                        valor += "; includeSubDomains"
                    cabecalhos.setdefault("Strict-Transport-Security", valor)

            await send(mensagem)

        await self.app(scope, receive, enviar)


class LimiteDeCorpoMiddleware:
    """Recusa corpo acima do teto, com 413.

    Duas verificações, porque uma só não basta:

      1. `Content-Length`, quando existe — recusa antes de ler um byte.
      2. A contagem do que realmente chega — porque o cabeçalho pode mentir, e
         em `Transfer-Encoding: chunked` ele nem existe.

    Uma correção de premissa: a segunda verificação NÃO é sobre memória. Em
    HTTP/1.1 o servidor lê exatamente os bytes declarados em `Content-Length`, e
    o excedente nem chega à aplicação. Quem realmente depende da contagem é
    `Transfer-Encoding: chunked`, onde não há tamanho declarado — aí o corpo
    chega inteiro se ninguém contar.
    """

    def __init__(self, app: ASGIApp, *, maximo: int = TAMANHO_MAXIMO_DO_CORPO) -> None:
        self.app = app
        self.maximo = maximo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declarado = Headers(scope=scope).get("content-length")
        if declarado is not None:
            try:
                if int(declarado) > self.maximo:
                    await _responder_grande_demais(send)
                    return
            except ValueError:
                # Cabeçalho ilegível: a contagem real abaixo resolve.
                pass

        recebidos = 0
        estourou = False

        async def receber() -> Message:
            nonlocal recebidos, estourou
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                recebidos += len(mensagem.get("body", b""))
                if recebidos > self.maximo:
                    estourou = True
                    # Interrompe a leitura: sem isto o corpo continuaria
                    # entrando. A exceção NÃO chega a nenhum tratador — o
                    # FastAPI embrulha qualquer falha na leitura do corpo num
                    # `HTTPException(400, "There was an error parsing the
                    # body")`. Por isso o status é corrigido no envio, abaixo.
                    raise CorpoGrandeDemais(self.maximo)
            return mensagem

        async def enviar(mensagem: Message) -> None:
            if estourou and mensagem["type"] == "http.response.start":
                # A recusa já aconteceu; o que sai daqui é o 400 genérico do
                # FastAPI. Trocar por 413 é o que faz a resposta dizer o motivo
                # certo — e é o que permite alertar sobre corpo grande sem
                # confundir com erro de JSON malformado do front.
                mensagem = {**mensagem, "status": 413}
            await send(mensagem)

        await self.app(scope, receber, enviar)


class CorpoGrandeDemais(Exception):
    """O corpo passou do teto durante a leitura. Vira 413."""

    def __init__(self, maximo: int) -> None:
        self.maximo = maximo
        super().__init__(f"Corpo da requisição acima do limite de {maximo} bytes.")


async def _responder_grande_demais(send: Send) -> None:
    corpo = b'{"detalhe":"Corpo da requisicao grande demais."}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(corpo)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corpo})
