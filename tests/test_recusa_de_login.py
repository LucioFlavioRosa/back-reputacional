"""Quem NÃO entra — e que a regra é a mesma nas duas portas.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
A plataforma vai passar a ter só SSO. A pergunta que o dono do produto fez foi
exatamente a certa: "hoje quem não tem cadastro não consegue entrar; quando
mudarmos para o SSO isso continua acontecendo?"

A resposta estava no código e não estava em teste nenhum. `test_oidc.py` cobre
a validação do token — assinatura, emissor, `nonce`, prazo — e para aí, antes
da decisão de autorizar. As referências a `NEGADO_SEM_PAPEL` no resto da suíte
chamam a função de auditoria DIRETAMENTE, sem passar por rota.

Ou seja: a garantia era verdadeira por acidente de leitura, e quebraria em
silêncio no dia da virada — que é o pior dia possível para descobrir.

O QUE MUDOU JUNTO
-----------------
`ativo` não era consultado na decisão. A porta da senha o conferia por conta
própria, dentro de `autenticar()`, na própria consulta SQL. O SSO nunca
conferiu. Enquanto as duas portas existiam, desativar alguém PARECIA funcionar
— e a senha é justamente o que vai embora.

Como não existe apagar pessoa (`interacao.criado_por` e mais nove chaves
apontam para `usuario`), desativar é a ÚNICA forma de remover alguém. Ela
pararia de surtir efeito no login exatamente quando virasse a única forma.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from fastapi.testclient import TestClient

from app.api import acesso
from app.api.acesso import _motivo_da_recusa, _texto_da_recusa
from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.casos_de_uso import registrar_acesso
from app.casos_de_uso.provisionar_usuario import _papel_de
from app.configuracao import obter_configuracao
from app.dominio.identidade import UsuarioAtual
from app.seguranca import sessao_assinada
from app.seguranca.cache_de_autorizacao import limpar_todos
from app.seguranca.oidc import Identidade
from main import app
from tests.test_acesso_http import SEGREDO, configuracao_real
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


# As fixtures moram em `test_acesso_http.py` e o pytest nao as compartilha
# entre modulos. Repetidas aqui de proposito, e nao movidas para um
# `conftest.py`: mexer no que 494 testes usam para acrescentar um arquivo e
# trocar um risco pequeno por um grande.


@pytest.fixture
def marca():
    """Um sufixo por teste, para a limpeza saber o que e dela."""
    return uuid4().hex[:8]


@pytest.fixture
def sessao(marca):
    """Compromete DE VERDADE, e limpa depois — e a razao importa.

    A sessao transacional que o resto da suite usa nao serve aqui.
    `registrar_e_confirmar()` grava a trilha de recusa numa sessao SEPARADA,
    de proposito, para a recusa sobreviver ao rollback do pedido. Essa segunda
    sessao nao enxerga um usuario que so existe dentro de uma transacao
    aberta, e o `insert` em `acesso_log` morre em
    `acesso_log_usuario_id_fkey`.

    Tentar contornar escrevendo o usuario por uma terceira conexao trava: ela
    espera o lock que a transacao do teste segura.

    Entao aqui e o caminho honesto — commit real, limpeza por marca no fim.
    """
    sessao = Session(bind=_engine, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.rollback()
        sessao.close()
        with Session(bind=_engine) as limpeza:
            alvo = {"m": f"%{marca}%"}
            limpeza.execute(
                text(
                    "delete from acesso_log where email_tentado like :m "
                    "or usuario_id in (select id from usuario where email like :m)"
                ),
                alvo,
            )
            limpeza.execute(
                text(
                    "delete from usuario_auditoria where usuario_id in "
                    "(select id from usuario where email like :m)"
                ),
                alvo,
            )
            limpeza.execute(text("delete from usuario where email like :m"), alvo)
            limpeza.commit()


@pytest.fixture(autouse=True)
def _cache_limpo():
    limpar_todos()
    yield
    limpar_todos()


@pytest.fixture
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = configuracao_real
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# -- a política, nua -----------------------------------------------------------
#
# `_motivo_da_recusa` é o ÚNICO lugar onde se decide quem entra, e as duas
# portas passam por ele. Testá-lo é testar as duas.


def _pessoa(**ajustes) -> UsuarioAtual:
    base = UsuarioAtual(
        id=uuid4(),
        nome="Pessoa da Aegea",
        email="pessoa@aegea.com.br",
        papel=None,
    )
    return replace(base, **ajustes)


def test_sem_papel_nao_entra():
    """O caso do dono do produto: e-mail corporativo, ninguém concedeu nada."""
    assert _motivo_da_recusa(_pessoa()) == registrar_acesso.NEGADO_SEM_PAPEL


def test_desativado_nao_entra_mesmo_com_papel(sessao):
    """A regressão que este arquivo existe para impedir.

    Antes: `ativo` só era conferido dentro de `autenticar()`, na porta da
    senha. Uma conta desativada COM papel passava por `_motivo_da_recusa` sem
    ser notada — e o SSO usa só essa função.
    """
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    desativada = _pessoa(papel=_papel_de(sessao, papel.id), ativo=False)
    assert desativada.papel is not None, "o caso só vale com papel concedido"
    assert _motivo_da_recusa(desativada) == registrar_acesso.NEGADO_INATIVO


def test_desativado_vence_sem_papel_na_trilha(sessao):
    """A ORDEM importa, e não é estética.

    Desativado E sem papel deve registrar `negado_inativo`. Dissesse
    `negado_sem_papel`, a trilha afirmaria que ninguém nunca concedeu acesso a
    essa pessoa — quando na verdade alguém a removeu. É a trilha que se lê
    depois de um incidente, e ela precisa dizer o que houve.
    """
    assert (
        _motivo_da_recusa(_pessoa(ativo=False)) == registrar_acesso.NEGADO_INATIVO
    )


def test_prazo_vencido_nao_entra(sessao):
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    vencida = _pessoa(
        papel=_papel_de(sessao, papel.id),
        acesso_expira_em=date(2020, 1, 1),
    )
    assert _motivo_da_recusa(vencida) == registrar_acesso.NEGADO_VENCIDO


def test_quem_esta_em_ordem_entra(sessao):
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    liberada = _pessoa(papel=_papel_de(sessao, papel.id))
    assert _motivo_da_recusa(liberada) is None


@pytest.mark.parametrize(
    ("estado", "trecho"),
    [
        ({"ativo": False}, "desativada"),
        ({}, "ainda não foi liberado"),
    ],
)
def test_a_mensagem_diz_o_que_fazer(estado, trecho):
    """Específica de propósito: quem chega aqui já provou quem é.

    Uma recusa vaga produz um chamado; esta diz a quem pedir.
    """
    texto = _texto_da_recusa(_pessoa(**estado))
    assert trecho in texto
    assert "coordenação do painel" in texto


# -- a porta do SSO, de ponta a ponta -----------------------------------------
#
# Aqui está o valor real do arquivo. O `provisionar()` roda de verdade, a rota
# decide de verdade; o que é falso é só o servidor da Microsoft.


class _EntraFalso:
    """Devolve a identidade combinada, sem sair da máquina."""

    def __init__(self, identidade: Identidade) -> None:
        self._identidade = identidade

    def trocar_codigo(self, **_):  # noqa: ANN003
        return "id-token-que-nao-sera-lido"

    def validar(self, _token, *, nonce):  # noqa: ANN001
        return self._identidade


def _cookie_de_pedido(estado: str) -> str:
    """O mesmo que `/auth/login` grava, montado à mão.

    O `csrf` carrega `estado|nonce|verificador|redirect` — quatro campos, e o
    `split("|", 3)` da rota exige exatamente esta forma.
    """
    return sessao_assinada.assinar(
        sessao_assinada.Sessao(
            usuario_id=uuid4(),
            expira_em=int(datetime.now(UTC).timestamp()) + 600,
            csrf=f"{estado}|nonce-de-teste|verificador-de-teste|",
            tipo=sessao_assinada.TIPO_PEDIDO,
        ),
        SEGREDO,
    )


def _chamar_callback(cliente, monkeypatch, identidade: Identidade):
    monkeypatch.setattr(
        acesso, "cliente_entra", lambda _configuracao: _EntraFalso(identidade)
    )
    estado = secrets.token_urlsafe(16)
    cliente.cookies.set(acesso.COOKIE_DO_PEDIDO, _cookie_de_pedido(estado))
    return cliente.get(
        f"/api/auth/callback?code=qualquer&state={estado}", follow_redirects=False
    )


def test_sso_recusa_quem_nunca_recebeu_papel(cliente, sessao, marca, monkeypatch):
    """A pergunta do dono do produto, respondida pela porta que vai sobrar.

    Pessoa com e-mail da Aegea, autenticada pelo Entra ID, sem concessao
    nenhuma: entra no BANCO e nao entra na PLATAFORMA.
    """
    email = f"{uuid4().hex[:6]}.{marca}@aegea.com.br"
    identidade = Identidade(
        entra_object_id=f"oid-{uuid4().hex}", email=email, nome="Recem-chegada"
    )

    resposta = _chamar_callback(cliente, monkeypatch, identidade)

    assert resposta.status_code == 403
    assert "nao foi liberado" in _sem_acento(resposta.json()["detalhe"])

    # O OUTRO LADO DA MOEDA, e o que faz o fluxo do produto funcionar: a
    # pessoa recusada PRECISA existir depois, senao quem administra acessos
    # nao teria a quem conceder — teria de pedir que ela tentasse de novo, e a
    # tentativa seria negada de novo. E o `commit()` antes da decisao.
    registro = sessao.scalars(select(Usuario).where(Usuario.email == email)).first()
    assert registro is not None, (
        "a pessoa recusada sumiu do banco; o admin nao tem a quem conceder"
    )
    assert registro.papel_id is None


def test_sso_recusa_conta_desativada(cliente, sessao, marca, monkeypatch):
    """O buraco que a virada abriria.

    Antes da correcao esta rota devolvia 303 e gravava o cookie: nada no
    caminho do SSO olhava `ativo`. A pessoa removida entrava e ainda tinha o
    `ultimo_acesso_em` carimbado — aparecendo na tela de acessos como quem
    acabou de entrar.
    """
    oid = f"oid-{uuid4().hex}"
    email = f"{uuid4().hex[:6]}.{marca}@aegea.com.br"
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    sessao.add(
        Usuario(
            entra_object_id=oid,
            email=email,
            nome="Pessoa Removida",
            papel_id=papel.id,
            ativo=False,
        )
    )
    sessao.commit()

    resposta = _chamar_callback(
        cliente,
        monkeypatch,
        Identidade(entra_object_id=oid, email=email, nome="Pessoa Removida"),
    )

    assert resposta.status_code == 403, (
        "conta desativada entrou pelo SSO — desativar deixou de remover"
    )
    assert "desativada" in resposta.json()["detalhe"]

    registro = sessao.scalars(
        select(Usuario).where(Usuario.entra_object_id == oid)
    ).first()
    assert registro.ultimo_acesso_em is None, (
        "o login recusado carimbou ultimo acesso: a pessoa removida aparece "
        "na tela de acessos como quem acabou de entrar"
    )


# -- a porta da senha ----------------------------------------------------------


def test_senha_recusa_quem_nao_recebeu_papel(cliente, sessao, marca):
    """A mesma regra, pela porta que existe hoje.

    Existe para provar que as duas concordam. No dia em que a rota de senha
    sair, este teste sai com ela — e o do SSO, acima, continua.
    """
    from app.casos_de_uso.autenticar_por_senha import gerar_hash

    email = f"{uuid4().hex[:6]}.{marca}@aegea.com.br"
    sessao.add(
        Usuario(
            email=email,
            nome="Sem Papel",
            # `n` minusculo de proposito: o scrypt de producao custa ~100ms, e
            # o custo existe para quem ataca, nao para a suite.
            senha_hash=gerar_hash("uma-senha-bem-longa", n=2**4),
            papel_id=None,
        )
    )
    sessao.commit()

    resposta = cliente.post(
        "/api/auth/senha", json={"email": email, "senha": "uma-senha-bem-longa"}
    )
    assert resposta.status_code == 403
    assert "nao foi liberado" in _sem_acento(resposta.json()["detalhe"])


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(
        c
        for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


# -- a recusa precisa dizer o que fazer ---------------------------------------
#
# Achado do Codex nesta revisão: as outras quatro recusas do callback também
# viravam "Você não tem permissão para esta operação". Num login isso é beco
# sem saída — a pessoa conclui que o problema é o acesso dela e abre chamado,
# quando bastava tentar de novo.


def test_pedido_de_login_expirado_diz_o_que_fazer(cliente):
    """Sem o cookie de pedido, a instrução tem de chegar.

    É o caso mais comum de todos: a aba ficou aberta tempo demais entre clicar
    em "entrar" e voltar do Entra ID.
    """
    resposta = cliente.get(
        "/api/auth/callback?code=qualquer&state=qualquer", follow_redirects=False
    )
    assert resposta.status_code == 403
    detalhe = resposta.json()["detalhe"]
    assert "Tente entrar de novo" in detalhe, (
        f"a instrução não chegou; a pessoa leu {detalhe!r}"
    )


def test_a_guarda_de_cada_requisicao_tambem_barra_desativado(sessao, marca):
    """A MESMA política, no outro lugar onde ela mora.

    `_exigir_autorizacao_valida()` protege toda requisição autenticada, e
    conferia só "sem papel" e "vencido". Duas cópias da mesma política
    discordando foi exatamente o que produziu o buraco original — `ativo`
    valendo numa porta e não na outra.
    """
    from app.api.dependencias import _exigir_autorizacao_valida
    from app.dominio.erros import NaoAutorizado

    papel = sessao.scalars(select(Papel).where(Papel.codigo == "crm_leitura")).first()
    removida = _pessoa(papel=_papel_de(sessao, papel.id), ativo=False)

    with pytest.raises(NaoAutorizado) as erro:
        _exigir_autorizacao_valida(removida)

    assert "desativada" in str(erro.value)
    assert erro.value.sobre_o_pedido, (
        "a mensagem seria trocada pela genérica e viraria beco sem saída"
    )
