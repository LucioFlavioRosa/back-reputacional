"""O fluxo OIDC contra um Entra ID falso — com criptografia de verdade.

O `id_token` é assinado aqui com uma chave RSA gerada no teste, e validado pelo
código de produção sem nenhum atalho: mesma verificação de assinatura, emissor,
destinatário, prazo e `nonce`. O que é falso é só o servidor da Microsoft.

Isso importa porque a única coisa que separa "identidade provada" de "JSON que
qualquer um escreve" é a verificação da assinatura. Um teste que a contornasse
provaria exatamente nada.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.seguranca.oidc import (
    ClienteEntraId,
    FalhaNoLogin,
    novo_desafio,
)

TENANT = "tenant-de-teste"
CLIENTE = "client-id-de-teste"
EMISSOR = f"https://login.microsoftonline.com/{TENANT}/v2.0"


@pytest.fixture(scope="module")
def chave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def entra(chave, monkeypatch):
    """Um `ClienteEntraId` cujo tenant é este teste."""
    cliente = ClienteEntraId(
        tenant_id=TENANT, client_id=CLIENTE, client_secret="segredo"
    )
    monkeypatch.setattr(
        cliente,
        "descoberta",
        lambda: {
            "issuer": EMISSOR,
            "authorization_endpoint": f"{EMISSOR}/authorize",
            "token_endpoint": f"{EMISSOR}/token",
            "jwks_uri": f"{EMISSOR}/keys",
        },
    )

    class ChaveFalsa:
        key = chave.public_key()

    class ClienteDeChaves:
        def get_signing_key_from_jwt(self, token):  # noqa: ANN001
            return ChaveFalsa()

    monkeypatch.setattr(cliente, "_cliente_de_chaves", lambda: ClienteDeChaves())
    return cliente


def token(chave, **ajustes) -> str:
    agora = int(time.time())
    claims = {
        "iss": EMISSOR,
        "aud": CLIENTE,
        "sub": "sub-estavel",
        "oid": "11111111-2222-3333-4444-555555555555",
        "preferred_username": "pessoa@aegea.com.br",
        "name": "Pessoa da Aegea",
        "nonce": "nonce-correto",
        "iat": agora,
        "exp": agora + 300,
    }
    claims.update(ajustes)
    return jwt.encode(claims, chave, algorithm="RS256")


# -- PKCE ----------------------------------------------------------------------


def test_desafio_pkce_e_o_sha256_do_verificador():
    """Se o desafio não derivar do verificador, o PKCE é decoração."""
    import base64
    import hashlib

    desafio = novo_desafio()
    esperado = (
        base64.urlsafe_b64encode(hashlib.sha256(desafio.verificador.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert desafio.desafio == esperado


def test_cada_desafio_e_novo():
    assert len({novo_desafio().verificador for _ in range(50)}) == 50


# -- a URL de autorização ------------------------------------------------------


def test_url_de_autorizacao_leva_o_que_precisa(entra):
    from urllib.parse import parse_qs, urlsplit

    url = entra.url_de_autorizacao(
        redirect_uri="https://painel.aegea.com.br/api/auth/callback",
        estado="estado-1",
        desafio="desafio-1",
        nonce="nonce-1",
    )
    parametros = parse_qs(urlsplit(url).query)

    assert parametros["response_type"] == ["code"]
    assert parametros["code_challenge_method"] == ["S256"]
    assert parametros["state"] == ["estado-1"]
    assert parametros["nonce"] == ["nonce-1"]
    # Escopo pedido é escopo que aparece na tela de consentimento.
    assert set(parametros["scope"][0].split()) == {"openid", "profile", "email"}


# -- validação do id_token -----------------------------------------------------


def test_token_valido_vira_identidade(entra, chave):
    identidade = entra.validar(token(chave), nonce="nonce-correto")
    assert identidade.entra_object_id == "11111111-2222-3333-4444-555555555555"
    assert identidade.email == "pessoa@aegea.com.br"
    assert identidade.nome == "Pessoa da Aegea"


def test_assinatura_de_outra_chave_e_recusada(entra):
    """O ataque que a validação existe para impedir.

    Sem conferir a assinatura, o `id_token` é um JSON em base64: qualquer um
    escreve o `oid` de quem quiser e entra como essa pessoa.
    """
    intrusa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(FalhaNoLogin):
        entra.validar(token(intrusa), nonce="nonce-correto")


def test_token_sem_assinatura_e_recusado(entra, chave):
    """`alg: none` é o clássico. Só RS256 é aceito."""
    cru = jwt.encode({"iss": EMISSOR, "aud": CLIENTE, "oid": "x"}, key="", algorithm="none")
    with pytest.raises(FalhaNoLogin):
        entra.validar(cru, nonce="nonce-correto")


def test_destinatario_errado_e_recusado(entra, chave):
    """Um token emitido para OUTRA aplicação do mesmo tenant não vale aqui.

    Sem conferir `aud`, qualquer app do tenant da Aegea viraria porta de entrada
    para este: bastaria pegar o token que ele emite e apresentá-lo aqui.
    """
    with pytest.raises(FalhaNoLogin):
        entra.validar(token(chave, aud="outro-app"), nonce="nonce-correto")


def test_emissor_errado_e_recusado(entra, chave):
    with pytest.raises(FalhaNoLogin):
        entra.validar(
            token(chave, iss="https://login.microsoftonline.com/outro/v2.0"),
            nonce="nonce-correto",
        )


def test_token_vencido_e_recusado(entra, chave):
    agora = int(time.time())
    with pytest.raises(FalhaNoLogin):
        entra.validar(
            token(chave, exp=agora - 10, iat=agora - 600), nonce="nonce-correto"
        )


def test_nonce_divergente_e_recusado(entra, chave):
    """O `nonce` amarra o token ao pedido que ESTE navegador fez.

    Sem conferir, um `id_token` válido capturado de outro login seria aceito —
    é o replay.
    """
    with pytest.raises(FalhaNoLogin):
        entra.validar(token(chave), nonce="nonce-de-outro-pedido")


def test_token_sem_oid_e_recusado(entra, chave):
    """`oid` é a identidade estável; sem ele não há como saber quem entrou."""
    sem_oid = token(chave)
    claims = jwt.decode(sem_oid, options={"verify_signature": False})
    del claims["oid"]
    with pytest.raises(FalhaNoLogin):
        entra.validar(jwt.encode(claims, chave, algorithm="RS256"), nonce="nonce-correto")


def test_email_cai_para_os_outros_claims(entra, chave):
    """Nem todo tenant devolve `preferred_username`."""
    claims = jwt.decode(token(chave), options={"verify_signature": False})
    del claims["preferred_username"]
    claims["email"] = "outro@aegea.com.br"
    identidade = entra.validar(
        jwt.encode(claims, chave, algorithm="RS256"), nonce="nonce-correto"
    )
    assert identidade.email == "outro@aegea.com.br"


# -- troca do código -----------------------------------------------------------


def test_troca_de_codigo_manda_o_verificador(entra, monkeypatch):
    """Sem o `code_verifier`, o PKCE não é verificado do outro lado."""
    enviado = {}

    class RespostaFalsa:
        status_code = 200

        def json(self):
            return {"id_token": "token-cru"}

    def post_falso(url, data=None, timeout=None):  # noqa: ANN001
        enviado.update(data)
        return RespostaFalsa()

    monkeypatch.setattr(
        "app.seguranca.oidc.httpx.post",
        post_falso,
    )

    assert entra.trocar_codigo(
        codigo="abc", redirect_uri="https://x/callback", verificador="verificador-1"
    ) == "token-cru"
    assert enviado["code_verifier"] == "verificador-1"
    assert enviado["grant_type"] == "authorization_code"


def test_recusa_do_provedor_nao_vaza_o_corpo(entra, monkeypatch):
    """`error_description` às vezes ecoa o que foi enviado.

    Útil no log, perigoso na tela — e esta exceção chega ao usuário.
    """
    class RespostaFalsa:
        status_code = 400

        def json(self):
            return {"error_description": "AADSTS9002313: segredo-que-nao-deve-vazar"}

    monkeypatch.setattr(
        "app.seguranca.oidc.httpx.post",
        lambda *a, **k: RespostaFalsa(),
    )

    with pytest.raises(FalhaNoLogin) as erro:
        entra.trocar_codigo(codigo="x", redirect_uri="y", verificador="z")
    assert "segredo-que-nao-deve-vazar" not in str(erro.value)
