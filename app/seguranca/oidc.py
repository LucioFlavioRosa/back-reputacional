"""Cliente OIDC do Microsoft Entra ID — authorization code + PKCE.

O que este módulo faz e o que deliberadamente não faz:

    FAZ    monta a URL de autorização, troca o `code` por tokens, e VALIDA o
           `id_token` contra as chaves públicas do tenant
    NÃO    guarda o `id_token`, nem o `access_token`, nem o refresh

Depois de validado, o `id_token` já cumpriu o papel: dele saem `oid`, e-mail e
nome, e a sessão passa a ser nossa. Guardar o token do provedor seria carregar
um segredo com prazo de validade sem ter o que fazer com ele — este sistema não
chama nenhuma API da Microsoft em nome do usuário.

PKCE MESMO COM CLIENT SECRET

O app é confidencial e tem segredo, então PKCE não é obrigatório. Entra assim
mesmo porque protege contra interceptação do `code` no redirecionamento — e
porque custa uma linha.

VALIDAR ASSINATURA É O PONTO INTEIRO

Um `id_token` sem verificação de assinatura é um JSON que qualquer um escreve.
`jwt.decode` só é chamado com a chave pública correspondente ao `kid` do
cabeçalho, e com `issuer`, `audience` e expiração conferidos.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient

#: Quanto tempo a descoberta e as chaves ficam em memória.
#:
#: O Entra ID gira as chaves de assinatura, então cache eterno faz o login
#: quebrar num dia qualquer, sem mudança nenhuma do nosso lado. Uma hora é
#: curto o bastante para acompanhar a rotação e longo o bastante para não
#: transformar cada login numa ida à Microsoft.
VALIDADE_DA_DESCOBERTA = 3600

#: `openid` para receber `id_token`; `profile` e `email` para nome e e-mail.
#: Nada além disso: escopo pedido é escopo que aparece na tela de consentimento,
#: e pedir mais do que se usa é o caminho para alguém negar o consentimento
#: inteiro.
ESCOPOS = "openid profile email"

#: A nuvem pública da Microsoft.
#:
#: Configurável, e não fixo no código, por dois motivos que se somam:
#:
#:   - nuvem soberana usa outro endereço (`login.microsoftonline.us` no Azure
#:     Government, `login.partner.microsoftonline.cn` na China). Fixo, o
#:     sistema não funcionaria lá — e a descoberta só falharia no deploy.
#:   - sem isso, NÃO HÁ COMO testar o fluxo de login localmente. Um provedor
#:     OIDC falso em contêiner é a única forma de exercitar redirecionamento,
#:     troca de código e validação de assinatura de ponta a ponta; com a URL
#:     fixa, o teste para na fronteira do `httpx`.
AUTORIDADE_PADRAO = "https://login.microsoftonline.com"


#: O tenant pode ser configurado como GUID ou como domínio
#: (`aegea.onmicrosoft.com`). `tid` no token é sempre GUID, então só dá para
#: comparar quando a configuração também é um.
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _parece_guid(valor: str) -> bool:
    return bool(_GUID.match(valor))


class FalhaNoLogin(Exception):
    """Qualquer problema no fluxo OIDC. Vira 401, sem detalhar ao cliente."""


@dataclass(frozen=True, slots=True)
class Identidade:
    """O que sobra do `id_token` depois de validado."""

    entra_object_id: str
    email: str
    nome: str


@dataclass(frozen=True, slots=True)
class DesafioPkce:
    verificador: str
    desafio: str


def novo_desafio() -> DesafioPkce:
    """Gera o par verificador/desafio do PKCE (método S256)."""
    verificador = secrets.token_urlsafe(64)
    resumo = hashlib.sha256(verificador.encode("ascii")).digest()
    desafio = base64.urlsafe_b64encode(resumo).decode("ascii").rstrip("=")
    return DesafioPkce(verificador=verificador, desafio=desafio)


class ClienteEntraId:
    """Conversa com o tenant. Uma instância por processo, para reaproveitar cache."""

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        autoridade: str = AUTORIDADE_PADRAO,
        tempo_limite: float = 10.0,
    ) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.autoridade = autoridade.rstrip("/")
        self.tempo_limite = tempo_limite
        self._descoberta: dict | None = None
        self._descoberta_em: float = 0.0
        self._chaves: PyJWKClient | None = None

    # -- descoberta ----------------------------------------------------------

    @property
    def url_de_descoberta(self) -> str:
        return (
            f"{self.autoridade}/{self.tenant_id}"
            "/v2.0/.well-known/openid-configuration"
        )

    def descoberta(self) -> dict:
        """Os endpoints do tenant, em cache com prazo."""
        agora = time.monotonic()
        if self._descoberta and agora - self._descoberta_em < VALIDADE_DA_DESCOBERTA:
            return self._descoberta

        try:
            resposta = httpx.get(self.url_de_descoberta, timeout=self.tempo_limite)
            resposta.raise_for_status()
        except httpx.HTTPError as erro:
            raise FalhaNoLogin(f"Descoberta OIDC indisponível: {erro}") from erro

        self._descoberta = resposta.json()
        self._descoberta_em = agora
        self._chaves = None  # chaves novas vêm junto com a descoberta nova
        return self._descoberta

    def _cliente_de_chaves(self) -> PyJWKClient:
        if self._chaves is None:
            self._chaves = PyJWKClient(
                self.descoberta()["jwks_uri"], cache_keys=True, lifespan=VALIDADE_DA_DESCOBERTA
            )
        return self._chaves

    # -- o fluxo -------------------------------------------------------------

    def url_de_autorizacao(
        self, *, redirect_uri: str, estado: str, desafio: str, nonce: str
    ) -> str:
        from urllib.parse import urlencode

        parametros = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": ESCOPOS,
            "state": estado,
            "nonce": nonce,
            "code_challenge": desafio,
            "code_challenge_method": "S256",
        }
        return f"{self.descoberta()['authorization_endpoint']}?{urlencode(parametros)}"

    def trocar_codigo(self, *, codigo: str, redirect_uri: str, verificador: str) -> str:
        """Troca o `code` pelo `id_token`. Devolve o token cru, ainda não validado."""
        try:
            resposta = httpx.post(
                self.descoberta()["token_endpoint"],
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": codigo,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verificador,
                    "scope": ESCOPOS,
                },
                timeout=self.tempo_limite,
            )
        except httpx.HTTPError as erro:
            raise FalhaNoLogin(f"Endpoint de token indisponível: {erro}") from erro

        if resposta.status_code != 200:
            # O corpo traz `error_description`, útil no log e perigoso na tela:
            # ele às vezes ecoa o que foi enviado.
            raise FalhaNoLogin(f"Troca de código recusada: {resposta.status_code}")

        token = resposta.json().get("id_token")
        if not token:
            raise FalhaNoLogin("Resposta de token sem `id_token`.")
        return token

    def validar(self, id_token: str, *, nonce: str) -> Identidade:
        """Confere assinatura, emissor, destinatário, prazo e `nonce`."""
        try:
            chave = self._cliente_de_chaves().get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                chave.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.descoberta()["issuer"],
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except Exception as erro:  # noqa: BLE001 — qualquer falha aqui é recusa
            raise FalhaNoLogin(f"id_token inválido: {type(erro).__name__}") from erro

        # O `nonce` amarra este token ao pedido que ESTE navegador fez. Sem
        # conferir, um `id_token` válido capturado de outro login seria aceito.
        #
        # `compare_digest` por consistência com o resto: não vi como explorar o
        # tempo aqui, mas comparar segredo com `!=` é o hábito que se quer não
        # ter em lugar nenhum.
        if not secrets.compare_digest(str(claims.get("nonce") or ""), nonce):
            raise FalhaNoLogin("Nonce divergente.")

        # `tid` é o tenant que emitiu. O `issuer` já é específico do tenant, e
        # `aud` já é conferido — então isto é cinto além do suspensório. Custa
        # uma comparação e fecha a hipótese de um emissor `common`/`organizations`
        # aceitar token de outro diretório.
        if _parece_guid(self.tenant_id) and claims.get("tid") != self.tenant_id:
            raise FalhaNoLogin("Token de outro tenant.")

        # `oid` é o identificador estável da pessoa no diretório. `sub` também é
        # estável, mas muda por aplicação — usá-lo faria a mesma pessoa virar
        # dois usuários se o app for registrado de novo.
        oid = claims.get("oid")
        if not oid:
            raise FalhaNoLogin("Token sem `oid`.")

        email = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("upn")
        )
        if not email:
            raise FalhaNoLogin("Token sem e-mail.")

        return Identidade(
            entra_object_id=str(oid),
            email=str(email),
            nome=str(claims.get("name") or email),
        )
