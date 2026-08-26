"""Quais portais cada papel abre.

A plataforma tem três divisões — CRM dos Stakeholders, Síntese Executiva e
Score Executivo — e a capa oferece as três. QUAL delas um papel abre é dimensão
separada do que ele pode FAZER lá dentro, e a separação é o ponto: sem ela,
"lê a Síntese" e "lê a Síntese e o Score" seriam papéis diferentes, e cada
portal novo dobraria a tabela.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import Papel as PapelRegistro
from app.dominio.identidade import Papel, Portal
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


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


# -- o objeto de domínio -------------------------------------------------------


def test_papel_sem_decidir_nada_nao_abre_porta_nenhuma():
    """Fecha por padrão, como todas as outras bandeiras.

    Um papel criado por `insert` sem mexer nas colunas de portal não alcança
    nada. É o comportamento certo para quem esqueceu de decidir: a falha é
    "ninguém entra", e não "todo mundo entra".
    """
    vazio = Papel(codigo="novo", nome="Novo")
    assert vazio.portais == frozenset()
    assert not vazio.alcanca(Portal.CRM)


def test_alcanca_responde_por_portal():
    so_crm = Papel(codigo="x", nome="X", acessa_crm=True)
    assert so_crm.alcanca(Portal.CRM)
    assert not so_crm.alcanca(Portal.SINTESE)
    assert not so_crm.alcanca(Portal.SCORE)
    assert so_crm.portais == {Portal.CRM}


def test_portais_devolve_todos_os_abertos():
    dois = Papel(codigo="x", nome="X", acessa_sintese=True, acessa_score=True)
    assert dois.portais == {Portal.SINTESE, Portal.SCORE}


def test_alcanca_cobre_todo_portal_do_enum():
    """Âncora contra portal novo esquecido.

    `alcanca` usa `match` sem ramo padrão: acrescentar um valor a `Portal` sem
    a coluna correspondente quebra AQUI, e não em produção devolvendo `False`
    calado — uma porta fechada sem ninguém saber por quê.
    """
    tudo = Papel(
        codigo="x",
        nome="X",
        acessa_crm=True,
        acessa_sintese=True,
        acessa_score=True,
    )
    assert tudo.portais == set(Portal)
    assert len(Portal) == 3


# -- o que está semeado no banco ----------------------------------------------


def test_os_quatro_papeis_de_partida(sessao):
    papeis = sessao.scalars(select(PapelRegistro).order_by(PapelRegistro.id)).all()
    assert [p.codigo for p in papeis] == ["plataforma", "crm", "sintese", "score"]


def test_plataforma_alcanca_os_tres(sessao):
    plataforma = sessao.scalars(
        select(PapelRegistro).where(PapelRegistro.codigo == "plataforma")
    ).one()
    assert (plataforma.acessa_crm, plataforma.acessa_sintese, plataforma.acessa_score) == (
        True,
        True,
        True,
    )


@pytest.mark.parametrize(
    ("codigo", "portal"),
    [("crm", "acessa_crm"), ("sintese", "acessa_sintese"), ("score", "acessa_score")],
)
def test_cada_papel_de_portal_abre_so_o_seu(sessao, codigo, portal):
    papel = sessao.scalars(select(PapelRegistro).where(PapelRegistro.codigo == codigo)).one()
    abertos = [
        nome
        for nome in ("acessa_crm", "acessa_sintese", "acessa_score")
        if getattr(papel, nome)
    ]
    assert abertos == [portal]


def test_so_a_plataforma_administra_acessos(sessao):
    """A permissão que concede todas as outras fica em UM papel só.

    Espalhá-la faria cada portal poder ampliar o próprio alcance — quem
    administra acessos pode se dar qualquer papel, inclusive um que abra os
    três portais.
    """
    com_permissao = sessao.scalars(
        select(PapelRegistro.codigo).where(PapelRegistro.administra_acessos.is_(True))
    ).all()
    assert list(com_permissao) == ["plataforma"]


def test_alguem_administra_acessos(sessao):
    """O contrapeso do teste acima, e não é redundante.

    `conceder_acesso` proíbe alterar o PRÓPRIO acesso (migration 0006). Com
    zero pessoas podendo administrar, a administração fica trancada e sair
    disso exige SQL direto no banco. Este teste falha antes de o banco ser
    semeado errado.
    """
    quantos = sessao.scalar(
        text("select count(*) from papel where administra_acessos and ativo")
    )
    assert quantos >= 1


def test_o_papel_do_banco_vira_dominio_com_os_portais(sessao):
    """As colunas novas atravessam o ORM até o objeto de domínio.

    Sem isto, `Papel.acessa_*` ficaria sempre no padrão `False` e a capa não
    ofereceria portal nenhum — com o banco dizendo o contrário, e nada
    acusando.
    """
    from app.casos_de_uso.provisionar_usuario import provisionar
    from app.dominio.identidade import Perfil

    usuario = provisionar(
        sessao,
        entra_object_id="oid-teste-portais",
        email="portais@aegea.com.br",
        nome="Teste de Portais",
        # `Perfil`, e não a string: `provisionar` chama `.value` no que recebe.
        papel_inicial=Perfil.PLATAFORMA,
    )
    assert usuario.papel is not None
    assert usuario.papel.portais == set(Portal)
