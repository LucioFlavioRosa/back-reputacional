"""O cookie de sessão e o token anti-CSRF.

Duas peças pequenas de que tudo o mais depende: se o cookie for forjável, o
escopo, o papel e a auditoria protegem contra ninguém — basta assinar a sessão
da pessoa certa.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from app.seguranca import sessao_assinada
from app.seguranca.sessao_assinada import (
    Sessao,
    SessaoInvalida,
    assinar,
    ler,
    nova_sessao,
)

SEGREDO = "segredo-de-teste-com-tamanho-suficiente-para-nao-parecer-real"


def test_ida_e_volta():
    quem = uuid4()
    lida = ler(assinar(nova_sessao(quem), SEGREDO), SEGREDO)
    assert lida.usuario_id == quem


def test_cookie_adulterado_e_recusado():
    """O ataque óbvio: trocar o UUID por outro.

    Sem assinatura, o cookie é um JSON em base64 — qualquer um o reescreve com
    o id de quem quiser e vira aquela pessoa.
    """
    import base64
    import json

    original = assinar(nova_sessao(uuid4()), SEGREDO)
    corpo, _, assinatura = original.partition(".")

    dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
    dados["u"] = str(uuid4())  # vira outra pessoa
    forjado = base64.urlsafe_b64encode(
        json.dumps(dados, separators=(",", ":")).encode()
    ).decode().rstrip("=")

    with pytest.raises(SessaoInvalida):
        ler(f"{forjado}.{assinatura}", SEGREDO)


def test_segredo_diferente_nao_abre():
    """Trocar o segredo derruba todas as sessões — é o botão de emergência."""
    cookie = assinar(nova_sessao(uuid4()), SEGREDO)
    with pytest.raises(SessaoInvalida):
        ler(cookie, "outro-segredo-qualquer")


def test_prazo_esticado_e_recusado():
    """A assinatura cobre o prazo, não só a identidade.

    Sem isso, quem tivesse um cookie vencido só precisaria empurrar a data.
    """
    import base64
    import json

    vencida = Sessao(usuario_id=uuid4(), expira_em=int(time.time()) - 10, csrf="x")
    cookie = assinar(vencida, SEGREDO)
    corpo, _, assinatura = cookie.partition(".")

    dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
    dados["e"] = int(time.time()) + 86400
    esticado = base64.urlsafe_b64encode(
        json.dumps(dados, separators=(",", ":")).encode()
    ).decode().rstrip("=")

    with pytest.raises(SessaoInvalida):
        ler(f"{esticado}.{assinatura}", SEGREDO)


def test_sessao_vencida_e_recusada():
    vencida = Sessao(usuario_id=uuid4(), expira_em=int(time.time()) - 1, csrf="x")
    with pytest.raises(SessaoInvalida):
        ler(assinar(vencida, SEGREDO), SEGREDO)


@pytest.mark.parametrize("valor", [None, "", "sem-ponto", ".", "a.b", "a."])
def test_lixo_nao_derruba(valor):
    """Entrada malformada precisa virar recusa, não exceção inesperada.

    Um `IndexError` aqui viraria 500 — e 500 num caminho de autenticação é
    convite para explorar.
    """
    with pytest.raises(SessaoInvalida):
        ler(valor, SEGREDO)


def test_token_anti_csrf_e_imprevisivel():
    """Token previsível é token nenhum: o atacante o inclui no pedido forjado."""
    tokens = {nova_sessao(uuid4()).csrf for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 40 for t in tokens)


def test_o_cookie_nao_carrega_papel_nem_escopo():
    """Deliberado, e é o que faz revogação valer no próximo clique.

    Se o papel viajasse no cookie, tirar a permissão de alguém só surtiria
    efeito quando a sessão dele vencesse — até oito horas depois.
    """
    cookie = assinar(nova_sessao(uuid4()), SEGREDO)
    import base64
    import json

    corpo = cookie.partition(".")[0]
    dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
    # `t` separa cookie de sessão de cookie de pedido; nenhum dos quatro é
    # permissão.
    assert set(dados) == {"u", "e", "c", "t"}


def test_duracao_padrao_cobre_um_expediente():
    """Oito horas: não obriga a reentrar no meio da tarde, e não passa a noite."""
    assert sessao_assinada.DURACAO_PADRAO == 8 * 3600


def test_cookie_de_pedido_nao_serve_de_sessao():
    """Os dois usam o mesmo segredo e o mesmo formato.

    Sem um rótulo dentro da assinatura, copiar `painel_pedido` para
    `painel_sessao` seria aceito — com o UUID que o pedido carrega. Hoje isso
    pararia adiante, porque aquele UUID não existe no banco; mas "não é
    explorável porque outra coisa segura" descreve um defeito latente, não um
    desenho.
    """
    pedido = Sessao(
        usuario_id=uuid4(),
        expira_em=int(time.time()) + 600,
        csrf="estado|nonce|verificador|",
        tipo=sessao_assinada.TIPO_PEDIDO,
    )
    cookie = assinar(pedido, SEGREDO)

    # Lido como pedido: passa.
    assert ler(cookie, SEGREDO, tipo=sessao_assinada.TIPO_PEDIDO).tipo == "p"

    # Lido como sessão: recusa, mesmo com a assinatura correta.
    with pytest.raises(SessaoInvalida):
        ler(cookie, SEGREDO)


def test_barra_vertical_no_redirect_nao_embaralha_o_pedido():
    """`redirect` vem da query string do usuário e vai no último campo.

    `split("|", 3)` para de dividir depois do terceiro separador, então um `|`
    no redirect fica dentro dele em vez de virar outro campo. Os três primeiros
    são `token_urlsafe`, que nunca contém `|`.
    """
    campos = "estado|nonce|verificador|/base?q=a|b|c"
    estado, nonce, verificador, redirect = campos.split("|", 3)
    assert estado == "estado"
    assert nonce == "nonce"
    assert verificador == "verificador"
    assert redirect == "/base?q=a|b|c"
