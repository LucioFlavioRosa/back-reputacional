"""Entrada por e-mail e senha.

O que estes testes protegem não é "o login funciona" — isso uma tentativa
manual mostra. É o que NÃO se vê olhando a tela:

  - que a recusa é a mesma para e-mail inexistente, senha errada e conta
    desativada, porque distinguir entregaria a lista de quem tem acesso ao
    painel;
  - que a senha nunca é guardada em claro;
  - que um usuário só de SSO não vira porta de entrada por senha vazia.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.casos_de_uso.autenticar_por_senha import (
    TAMANHO_MINIMO_DA_SENHA,
    autenticar,
    definir_senha,
    gerar_hash,
)
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: Custo mínimo do scrypt. Ver o comentário em `cria_usuario`.
N_DE_TESTE = 2**8

SENHA_BOA = "uma-senha-longa-o-bastante"


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def cria_usuario(sessao, *, com_senha=True, ativo=True, com_sso=False) -> str:
    email = f"{uuid.uuid4().hex[:10]}@aegea.com.br"
    sessao.execute(
        text("""
            insert into usuario (entra_object_id, email, nome, ativo, senha_hash)
            values (:oid, :email, 'Teste', :ativo, :hash)
        """),
        {
            # O `oid` só existe quando a pessoa vem do SSO. Sem ele e sem senha,
            # o `check` da migration recusaria a linha — que é o ponto dele.
            "oid": f"oid-{uuid.uuid4().hex[:8]}" if com_sso else None,
            "email": email,
            "ativo": ativo,
            # `n` pequeno nos testes: derivar dezenas de hashes com o custo de
            # produção faria a suíte levar minutos, e o que se exercita aqui é
            # a LÓGICA, que não muda com o custo.
            "hash": gerar_hash(SENHA_BOA, n=N_DE_TESTE) if com_senha else None,
        },
    )
    sessao.flush()
    return email


# -- o caminho feliz -----------------------------------------------------------


def test_email_e_senha_certos_autenticam(sessao):
    email = cria_usuario(sessao)
    quem = autenticar(sessao, email=email, senha=SENHA_BOA)
    assert quem is not None
    assert quem.email == email


def test_o_email_nao_diferencia_maiuscula(sessao):
    """A coluna é `citext`, e a tela não deve exigir que a pessoa lembre a caixa
    em que digitou o e-mail no dia do cadastro."""
    email = cria_usuario(sessao)
    assert autenticar(sessao, email=email.upper(), senha=SENHA_BOA) is not None


# -- as recusas, todas iguais --------------------------------------------------


def test_senha_errada_e_recusada(sessao):
    email = cria_usuario(sessao)
    assert autenticar(sessao, email=email, senha="senha-que-nao-e-a-dele") is None


def test_email_inexistente_e_recusado(sessao):
    assert autenticar(sessao, email="ninguem@aegea.com.br", senha=SENHA_BOA) is None


def test_conta_desativada_e_recusada_mesmo_com_a_senha_certa(sessao):
    """`ativo = false` é como se revoga alguém sem apagar o histórico.

    Se a senha certa ainda entrasse, desativar não desativaria nada.
    """
    email = cria_usuario(sessao, ativo=False)
    assert autenticar(sessao, email=email, senha=SENHA_BOA) is None


def test_usuario_so_de_sso_nao_entra_por_senha(sessao):
    """Quem vem do Entra ID tem `senha_hash` nulo.

    Sem este caso tratado, uma comparação contra nulo poderia devolver algo
    diferente de "não" — e a conta de todo mundo do diretório viraria porta
    aberta por senha vazia.
    """
    email = cria_usuario(sessao, com_senha=False, com_sso=True)
    assert autenticar(sessao, email=email, senha="") is None
    assert autenticar(sessao, email=email, senha=SENHA_BOA) is None


def test_senha_vazia_nunca_entra(sessao):
    email = cria_usuario(sessao)
    assert autenticar(sessao, email=email, senha="") is None


# -- como a senha é guardada ---------------------------------------------------


def test_a_senha_nunca_fica_em_claro_no_banco(sessao):
    email = cria_usuario(sessao, com_senha=False, com_sso=True)
    definir_senha(sessao, email=email, senha=SENHA_BOA, n=N_DE_TESTE)
    sessao.flush()

    guardado = sessao.scalar(
        text("select senha_hash from usuario where email = :email"), {"email": email}
    )
    assert guardado is not None
    assert SENHA_BOA not in guardado
    # O prefixo diz QUAL função derivou o hash. Sem ele, trocar de algoritmo
    # amanhã transformaria todo hash antigo em recusa silenciosa em vez de
    # "formato que não conheço".
    assert guardado.startswith("scrypt$")
    # E os parâmetros vão junto: é o que permite subir o custo sem invalidar as
    # senhas já cadastradas.
    assert guardado.split("$")[1] == str(N_DE_TESTE)


def test_a_mesma_senha_produz_hashes_diferentes(sessao):
    """Sal por linha.

    Sem sal, duas pessoas com a mesma senha teriam o mesmo hash — e quem
    vazasse o banco saberia quem repetiu senha de quem sem quebrar nada.
    """
    a = cria_usuario(sessao, com_senha=False, com_sso=True)
    b = cria_usuario(sessao, com_senha=False, com_sso=True)
    definir_senha(sessao, email=a, senha=SENHA_BOA, n=N_DE_TESTE)
    definir_senha(sessao, email=b, senha=SENHA_BOA, n=N_DE_TESTE)
    sessao.flush()

    hashes = sessao.execute(
        text("select senha_hash from usuario where email in (:a, :b)"), {"a": a, "b": b}
    ).scalars().all()
    assert len(set(hashes)) == 2


def test_definir_senha_recusa_senha_curta(sessao):
    email = cria_usuario(sessao, com_senha=False, com_sso=True)
    with pytest.raises(ValueError, match="curta"):
        definir_senha(sessao, email=email, senha="a" * (TAMANHO_MINIMO_DA_SENHA - 1), n=N_DE_TESTE)


def test_definir_senha_recusa_email_inexistente(sessao):
    """Falha alto, e não em silêncio.

    Um `update` que não acerta linha nenhuma é sucesso para o Postgres. Sem
    esta checagem, definir a senha de um e-mail digitado errado pareceria ter
    funcionado — e a pessoa descobriria no dia em que tentasse entrar.
    """
    with pytest.raises(ValueError, match="Não há usuário"):
        definir_senha(sessao, email="ninguem@aegea.com.br", senha=SENHA_BOA, n=N_DE_TESTE)


def test_definir_senha_troca_a_anterior(sessao):
    email = cria_usuario(sessao)
    nova = "outra-senha-bem-comprida"
    definir_senha(sessao, email=email, senha=nova, n=N_DE_TESTE)
    sessao.flush()

    assert autenticar(sessao, email=email, senha=nova) is not None
    assert autenticar(sessao, email=email, senha=SENHA_BOA) is None


# -- o schema sustenta as duas portas ------------------------------------------


def test_conta_sem_sso_e_sem_senha_e_recusada_pelo_banco(sessao):
    """O `check` da migration 0003.

    Sem ele, um `insert` que esquecesse os dois criaria uma conta que existe,
    recebe papel e escopo, aparece na tela de acessos — e não autentica por
    caminho nenhum.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        sessao.execute(
            text("""
                insert into usuario (entra_object_id, email, nome)
                values (null, 'fantasma@aegea.com.br', 'Fantasma')
            """)
        )
        sessao.flush()


# -- a trilha de acesso --------------------------------------------------------


def test_a_recusa_fica_gravada_mesmo_com_a_transacao_desfeita(sessao):
    """O achado que quase passou: a recusa sumia da trilha.

    A rota gravava com `registrar()` e levantava em seguida — e `obter_sessao`
    desfaz a transação em qualquer exceção. A linha era gravada e descartada
    milissegundos depois, então `acesso_log` só tinha SUCESSOS. Numa
    investigação, "ninguém tentou entrar" e "todas as tentativas foram
    apagadas" são indistinguíveis.

    `registrar_e_confirmar` usa transação própria, que sobrevive ao rollback da
    principal. Este teste imita a sequência: grava, desfaz, e confere que a
    linha ficou.
    """
    from app.casos_de_uso import registrar_acesso

    email = f"recusa-{uuid.uuid4().hex[:8]}@aegea.com.br"
    registrar_acesso.registrar_e_confirmar(
        sessao,
        resultado=registrar_acesso.NEGADO_NO_PROVEDOR,
        usuario_id=None,
        email_tentado=email,
        ip="203.0.113.7",
    )

    # A transação da requisição é desfeita — é o que a exceção provoca.
    sessao.rollback()

    # E a linha continua lá, porque foi gravada por outra transação.
    quantas = sessao.scalar(
        text("select count(*) from acesso_log where email_tentado = :email"),
        {"email": email},
    )
    assert quantas == 1
