"""Quais portais cada papel abre.

A plataforma tem três divisões, e os nomes internos não batem com os rótulos:

    CRM      "CRM dos Stakeholders"
    SCORE    "KPIs Reputacionais"
    SINTESE  "Painel de Inteligência de Mercado" — em construção

QUAL delas um papel abre é dimensão separada do que ele pode FAZER lá dentro, e
a separação é o ponto: sem ela, "lê a Síntese" e "lê a Síntese e o Score" seriam
papéis diferentes, e cada portal novo dobraria a tabela.

AS COLUNAS SAEM DO ENUM, e não de listas escritas à mão em cada teste. Três
deles enumeravam `acessa_crm`, `acessa_sintese`, `acessa_score` por extenso, e
uma lista escrita à mão não cobre o portal que ainda não existia quando ela foi
escrita — comparava os papéis nas três dimensões conhecidas e ignoraria a
quarta. Derivar do enum faz `Portal` ser a única lista.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import Papel as PapelRegistro
from app.dominio.identidade import Papel, Portal
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: As colunas de portal de `papel`, derivadas do enum.
#:
#: Derivadas, e não escritas: acrescentar um membro a `Portal` passa a alargar
#: estes testes sozinho. A convenção de nome (`acessa_<valor do enum>`) vem de
#: 0003, e `test_alcanca_cobre_todo_portal_do_enum` é quem garante que o domínio
#: não tem portal sem bandeira.
COLUNAS_DE_PORTAL = tuple(f"acessa_{p.value}" for p in Portal)


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
    #: A contagem escrita é de propósito: `portais == set(Portal)` sozinho
    #: passaria num enum vazio. Três, e não quatro — o "Painel de Inteligência
    #: de Mercado" é o portal `sintese`, não um quarto.
    assert len(Portal) == 3


# -- o que está semeado no banco ----------------------------------------------


def test_os_papeis_de_partida(sessao):
    """Um LEITOR e um EDITOR por portal, mais os que alcançam todos.

    O sufixo é obrigatório no nome, e não convenção: antes havia só `crm`, e
    ele ESCREVIA. Um papel cujo nome não revela o que concede é um papel que
    alguém atribui por engano.

    ERA "OS OITO" até 0088, que acrescentou o nono. A lista é escrita por
    extenso, e na ordem de `id`, porque é ela que responde "o que existe para
    conceder?" — e porque um papel que aparece aqui sem ninguém ter decidido
    acrescentá-lo é um papel que alguém semeou de passagem.
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
        # -- 0088: o Executivo que edita os painéis e não administra acessos ---
        #: O nome é feio e o motivo está em 0088: `plataforma_edicao` já é o
        #: papel de administrador, e tomar-lhe o nome significaria tirar
        #: `administra_acessos` de quem o tem hoje em produção.
        "plataforma_edicao_sem_acessos",
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
    assert [getattr(a, p) for p in COLUNAS_DE_PORTAL] == [
        getattr(b, p) for p in COLUNAS_DE_PORTAL
    ]

    assert not (a.pode_criar or a.pode_editar_proprio or a.pode_editar_tudo)

    # O editor cria e edita O PRÓPRIO. `pode_editar_tudo` — mexer no registro
    # que outra pessoa criou — é permissão de coordenação, e só
    # `plataforma_edicao` a tem.
    assert b.pode_criar and b.pode_editar_proprio
    assert b.pode_editar_tudo == (b.codigo == "plataforma_edicao")


@pytest.mark.parametrize(
    "codigo",
    ["plataforma_leitura", "plataforma_edicao", "plataforma_edicao_sem_acessos"],
)
def test_a_plataforma_alcanca_todos_os_portais(sessao, codigo):
    """"Plataforma" no nome é promessa: alcança TODOS os portais.

    Era só `plataforma_edicao`, e comparava os portais por extenso. Derivando de
    `COLUNAS_DE_PORTAL`, um portal novo entra na conferência sozinho — sem isso,
    um papel chamado "plataforma" passaria deixando um painel de fora.

    `plataforma_edicao_sem_acessos` entra na lista porque é o Executivo Editor
    de 0088, e "alcança os painéis" é metade do que ele promete.
    """
    papel = sessao.scalars(
        select(PapelRegistro).where(PapelRegistro.codigo == codigo)
    ).one()
    fechados = [p for p in COLUNAS_DE_PORTAL if not getattr(papel, p)]
    assert fechados == [], f"{codigo} não abre: {fechados}"


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
    abertos = [nome for nome in COLUNAS_DE_PORTAL if getattr(papel, nome)]
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
