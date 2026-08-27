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


def test_os_oito_papeis_de_partida(sessao):
    """Um LEITOR e um EDITOR por portal, mais o par que alcança os três.

    O sufixo é obrigatório no nome, e não convenção: antes havia só `crm`, e
    ele ESCREVIA. Um papel cujo nome não revela o que concede é um papel que
    alguém atribui por engano.
    """
    papeis = sessao.scalars(select(PapelRegistro).order_by(PapelRegistro.id)).all()
    assert [p.codigo for p in papeis] == [
        "plataforma_leitura",
        "plataforma_edicao",
        "crm_leitura",
        "crm_edicao",
        "sintese_leitura",
        "sintese_edicao",
        "score_leitura",
        "score_edicao",
    ]


@pytest.mark.parametrize(
    ("leitor", "editor"),
    [
        ("plataforma_leitura", "plataforma_edicao"),
        ("crm_leitura", "crm_edicao"),
        ("sintese_leitura", "sintese_edicao"),
        ("score_leitura", "score_edicao"),
    ],
)
def test_o_par_de_cada_portal_alcanca_o_mesmo_e_faz_coisas_diferentes(
    sessao, leitor, editor
):
    """A prova de que as duas dimensões são independentes.

    O par abre exatamente os MESMOS portais — é a mesma pergunta "onde entra" —
    e difere só no que faz lá dentro. Se um dia os portais divergirem dentro de
    um par, alguém confundiu as dimensões.
    """
    a, b = (
        sessao.scalars(select(PapelRegistro).where(PapelRegistro.codigo == c)).one()
        for c in (leitor, editor)
    )
    portais = ("acessa_crm", "acessa_sintese", "acessa_score")
    assert [getattr(a, p) for p in portais] == [getattr(b, p) for p in portais]

    assert not (a.pode_criar or a.pode_editar_proprio or a.pode_editar_tudo)

    # O editor cria e edita O PRÓPRIO. `pode_editar_tudo` — mexer no registro
    # que outra pessoa criou — é permissão de coordenação, e só
    # `plataforma_edicao` a tem.
    assert b.pode_criar and b.pode_editar_proprio
    assert b.pode_editar_tudo == (b.codigo == "plataforma_edicao")


def test_plataforma_alcanca_os_tres(sessao):
    plataforma = sessao.scalars(
        select(PapelRegistro).where(PapelRegistro.codigo == "plataforma_edicao")
    ).one()
    assert (plataforma.acessa_crm, plataforma.acessa_sintese, plataforma.acessa_score) == (
        True,
        True,
        True,
    )


@pytest.mark.parametrize(
    ("codigo", "portal"),
    [
        ("crm_leitura", "acessa_crm"),
        ("crm_edicao", "acessa_crm"),
        ("sintese_leitura", "acessa_sintese"),
        ("sintese_edicao", "acessa_sintese"),
        ("score_leitura", "acessa_score"),
        ("score_edicao", "acessa_score"),
    ],
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
    # UMA linha. Nem `plataforma_leitura` tem: administrar acessos é editar
    # pessoas, e um papel de leitura que pudesse fazê-lo poderia se promover.
    assert list(com_permissao) == ["plataforma_edicao"]


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
        papel_inicial=Perfil.PLATAFORMA_EDICAO,
    )
    assert usuario.papel is not None
    assert usuario.papel.portais == set(Portal)
