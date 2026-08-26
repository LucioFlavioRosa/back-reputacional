"""A aplicação funciona conectada como `painel_app`?

Esta suíte é o ÚNICO lugar que conecta como a conta restrita de produção. O
resto roda como superusuário, então um `grant` faltando não quebra nada aqui —
quebra em produção.

O caso que mais engana: revogar `delete` de tudo parece certo, porque o sistema
usa soft delete. Mas as relações do ORM usam `delete-orphan`, e tirar um tema,
tirar um porta-voz ou trocar a frente de um registro emite `DELETE` de verdade
nas tabelas filhas.

Ou seja: a aplicação pararia de funcionar em produção, e **o resto da suíte
continuaria verde**. Conceder permissão e testar
com outra conta é testar outra coisa.

`has_table_privilege` também não bastaria: ele responde o que o catálogo diz, não
o que acontece quando o SQLAlchemy monta a transação de verdade.
"""

from __future__ import annotations

from datetime import UTC, date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InternalError, ProgrammingError
from sqlalchemy.orm import Session

from app.banco.repositorio_interacoes import (
    RepositorioSQL,
)
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_stakeholders import (
    Instituicao,
    PessoaAegea,
)
from app.dominio.frentes import Frente
from app.dominio.interacao import (
    PAPEL_PORTA_VOZ,
    Interacao,
    ParticipacaoAegea,
)

# Reaproveita o banco de teste que `test_e2e_postgres` cria e migra.
from tests.test_e2e_postgres import URL  # noqa: F401

CONTA = "painel_teste_restrito"
SENHA = "somente-para-teste-local"


@pytest.fixture(scope="module")
def engine_restrito():
    """Cria uma conta de login com o papel da aplicação e conecta com ela.

    É o que a infraestrutura fará em produção: `painel_app` é recipiente de
    permissão, e a conta de login recebe o papel.
    """
    administrativo = create_engine(URL, isolation_level="AUTOCOMMIT")
    with administrativo.connect() as conexao:
        conexao.execute(text(f"drop role if exists {CONTA}"))
        conexao.execute(text(f"create role {CONTA} login password '{SENHA}'"))
        conexao.execute(text(f"grant painel_app to {CONTA}"))

    url = make_url(URL).set(username=CONTA, password=SENHA)
    engine = create_engine(url)

    yield engine

    engine.dispose()
    with administrativo.connect() as conexao:
        # `drop owned by` primeiro: um papel com privilégio pendente não é
        # removível, e o erro seria confundido com falha do teste.
        conexao.execute(text(f"drop owned by {CONTA}"))
        conexao.execute(text(f"drop role if exists {CONTA}"))
    administrativo.dispose()


@pytest.fixture
def sessao_restrita(engine_restrito):
    conexao = engine_restrito.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


@pytest.fixture
def semente(sessao_restrita):
    """Dado mínimo, criado PELA CONTA RESTRITA.

    Não reaproveita a fixture de `test_e2e_postgres`: aquela escreve pela sessão
    de superusuário, e o ponto desta suíte é justamente exercitar a outra conta.
    Se a conta restrita não conseguir semear, o teste falha aqui — que é a
    informação certa.
    """
    from uuid import uuid4

    from app.banco.tabelas_acesso import Usuario

    sufixo = uuid4().hex[:8]
    # `criado_por` é obrigatório em `interacao`, e provisionar usuário é
    # justamente uma das coisas que a conta restrita PRECISA conseguir fazer:
    # é o primeiro login de qualquer pessoa.
    autor = Usuario(
        entra_object_id=f"restrito-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome="Autor de teste",
        acesso_irrestrito=True,
    )
    sessao_restrita.add_all([
        autor,
        Instituicao(
            nome=f"Veículo {sufixo}",
            nome_normalizado=f"veiculo {sufixo}",
            tipo="veiculo",
            uf="SP",
        ),
        PessoaAegea(nome=f"A {sufixo}", nome_normalizado=f"a {sufixo}", eh_porta_voz=True),
        PessoaAegea(nome=f"B {sufixo}", nome_normalizado=f"b {sufixo}", eh_porta_voz=True),
    ])
    sessao_restrita.flush()
    return autor


def _interacao(sessao: Session, autor, **ajustes) -> Interacao:
    instituicao = sessao.scalars(select(Instituicao).limit(1)).first()
    padrao = dict(
        frente=Frente.GOVERNO,
        data_interacao=date(2026, 5, 7),
        instituicao_id=instituicao.id,
        uf="SP",
        status="atendido",
        pauta="Sondagem do papel restrito",
        criado_por=autor.id,
    )
    return Interacao(**{**padrao, **ajustes})


# -- o caminho de escrita inteiro ----------------------------------------------


def test_cria_interacao_como_painel_app(sessao_restrita, semente):
    repositorio = RepositorioSQL(sessao_restrita)
    criada = repositorio.adicionar(_interacao(sessao_restrita, semente))
    sessao_restrita.flush()
    assert criada.id is not None


def test_remover_tema_funciona_com_o_papel_restrito(sessao_restrita, semente):
    """O caso que quebrava: `delete-orphan` em `interacao_tema`.

    Revogar `delete` de tudo — sob o argumento de que o sistema usa soft
    delete — faria este fluxo levantar `permission denied` em produção: as
    relações do ORM usam `delete-orphan`, e tirar um tema emite `DELETE`.
    """
    temas = sessao_restrita.scalars(select(Tema).limit(2)).all()
    assert len(temas) == 2, "a semente precisa de ao menos dois temas"

    repositorio = RepositorioSQL(sessao_restrita)
    criada = repositorio.adicionar(
        _interacao(sessao_restrita, semente, temas=[t.id for t in temas])
    )
    sessao_restrita.flush()

    criada.temas = [temas[0].id]
    repositorio.atualizar(criada)
    sessao_restrita.flush()

    restantes = sessao_restrita.execute(
        text("select tema_id from interacao_tema where interacao_id = :id"),
        {"id": criada.id},
    ).scalars().all()
    assert restantes == [temas[0].id]


def test_remover_porta_voz_funciona_com_o_papel_restrito(sessao_restrita, semente):
    pessoas = sessao_restrita.scalars(select(PessoaAegea).limit(2)).all()
    repositorio = RepositorioSQL(sessao_restrita)

    criada = repositorio.adicionar(
        _interacao(
            sessao_restrita,
            semente,
            participacoes=[
                ParticipacaoAegea(pessoa_aegea_id=p.id, papel=PAPEL_PORTA_VOZ) for p in pessoas
            ],
        )
    )
    sessao_restrita.flush()

    criada.participacoes = (
        ParticipacaoAegea(pessoa_aegea_id=pessoas[0].id, papel=PAPEL_PORTA_VOZ),
    )
    repositorio.atualizar(criada)
    sessao_restrita.flush()

    quantos = sessao_restrita.execute(
        text("select count(*) from interacao_pessoa_aegea where interacao_id = :id"),
        {"id": criada.id},
    ).scalar()
    assert quantos == 1


def test_arquivar_funciona_com_o_papel_restrito(sessao_restrita, semente):
    """Soft delete é `update`, não `delete`: precisa passar."""
    from datetime import datetime

    repositorio = RepositorioSQL(sessao_restrita)
    criada = repositorio.adicionar(_interacao(sessao_restrita, semente))
    sessao_restrita.flush()

    criada.arquivado_em = datetime.now(UTC)
    repositorio.atualizar(criada)
    sessao_restrita.flush()


# -- o que o papel NÃO pode ----------------------------------------------------


def _isolado(sessao: Session):
    """Savepoint em volta de uma operação que se espera falhar.

    Erro de permissão aborta a transação corrente. Sem isolar, o `rollback` do
    fixture reclamaria de operar sobre transação já encerrada, e o teste
    seguinte herdaria o estropício.
    """
    return sessao.begin_nested()


def test_nao_apaga_o_agregado(sessao_restrita, semente):
    """`interacao` só sai de cena por `arquivado_em`."""
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text("delete from interacao"))


def test_nao_adultera_a_trilha_de_auditoria(sessao_restrita, semente):
    """Quem escreve a auditoria é o gatilho, que roda como `security definer`.

    Sem esta revogação, quem tivesse a connection string inseria linha falsa e
    reescrevia linha verdadeira — e a trilha deixaria de ser evidência de coisa
    nenhuma.
    """
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(
            text("update interacao_auditoria set valor_novo = 'adulterado'")
        )

    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(
            text(
                "insert into interacao_auditoria (interacao_id, campo) "
                "select id, 'inventado' from interacao limit 1"
            )
        )


def test_nao_escala_o_proprio_privilegio(sessao_restrita, semente):
    """A conta da aplicação não se promove dentro do banco.

    Sem esta revogação, `update usuario set acesso_irrestrito = true` daria
    alcance total a quem tivesse a connection string — sem tocar em papel
    nenhum e sem deixar rastro na aplicação.

    Quem escreve autorização é `conceder_acesso` (migration 0006), com
    validação e trilha.
    """
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text("update usuario set acesso_irrestrito = true"))

    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text("update usuario set papel_id = 2"))

    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(
            text("insert into usuario_escopo (usuario_id, dimensao, valor) "
                 "select id, 'frente', 'imprensa' from usuario limit 1")
        )


def test_ainda_atualiza_o_que_precisa_em_usuario(sessao_restrita, semente):
    """A revogação é por COLUNA: o provisionamento JIT continua funcionando."""
    sessao_restrita.execute(
        text("insert into usuario (entra_object_id, email, nome) "
             "values ('teste-restrito', 'r@aegea.com.br', 'R')")
    )
    sessao_restrita.execute(
        text("update usuario set ultimo_acesso_em = now() "
             "where entra_object_id = 'teste-restrito'")
    )


def test_nao_cria_nem_derruba_estrutura(sessao_restrita, semente):
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text("create table intruso (id int)"))

    with pytest.raises(ProgrammingError), _isolado(sessao_restrita):
        sessao_restrita.execute(text("drop table interacao"))


# -- a concessão de acesso só existe pela função (migration 0006) --------------


def test_papel_da_aplicacao_nao_altera_autorizacao_direto(sessao_restrita, semente):
    """A tela de administração escreve pela FUNÇÃO, e não por `update` direto.

    Devolver o `grant` nestas colunas para a tela funcionar reabriria a
    escalada: quem tivesse a connection string se promoveria dentro do banco.
    """
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text("update usuario set acesso_irrestrito = true"))


@pytest.mark.parametrize("tabela", ["importacao", "importacao_linha"])
def test_nao_escreve_no_schema_sem_aplicacao(sessao_restrita, semente, tabela):
    """Permissão sem caso de uso é permissão que ninguém revisa.

    A importação da planilha não foi implementada. As tabelas existem, e o
    `grant insert, update on all tables` da 0009 as alcançaria — a aplicação
    ganharia escrita numa área que nenhum código toca.

    Quem for implementar a importação vai ver este teste falhar, e é o
    comportamento desejado: a concessão passa a ser uma decisão explícita na
    migration, e não um efeito colateral do `grant on all tables`.
    """
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(
            text(f"insert into {tabela} default values")  # noqa: S608 - nome vem do parametrize
        )


def test_papel_da_aplicacao_executa_a_funcao_de_concessao(sessao_restrita, semente):
    """O outro lado: a barreira não pode impedir o trabalho.

    Uma proteção que quebra a tela de administração é uma proteção que alguém
    desliga na próxima terça-feira.
    """
    concedente = sessao_restrita.execute(
        text(
            "insert into usuario (entra_object_id, email, nome, acesso_irrestrito, papel_id) "
            "values (:o, :e, 'Quem concede', true, "
            "        (select id from papel where codigo = 'coordenacao')) returning id"
        ),
        {"o": f"concede-{uuid4().hex[:8]}", "e": f"{uuid4().hex[:8]}@aegea.com.br"},
    ).scalar()
    alvo = sessao_restrita.execute(
        text(
            "insert into usuario (entra_object_id, email, nome) "
            "values (:o, :e, 'Alvo') returning id"
        ),
        {"o": f"alvo-{uuid4().hex[:8]}", "e": f"{uuid4().hex[:8]}@aegea.com.br"},
    ).scalar()

    sessao_restrita.execute(
        text(
            "select conceder_acesso(:alvo, :quem, 'analista', true, false, null, "
            "'{}'::text[], '{}'::text[])"
        ),
        {"alvo": alvo, "quem": concedente},
    )

    irrestrito = sessao_restrita.execute(
        text("select acesso_irrestrito from usuario where id = :id"), {"id": alvo}
    ).scalar()
    assert irrestrito is True


@pytest.mark.parametrize(
    "comando",
    [
        "update usuario_auditoria set concedido_por = null",
        "delete from usuario_auditoria",
        "insert into usuario_auditoria (usuario_id, campo) "
        "select id, 'inventado' from usuario limit 1",
    ],
)
def test_papel_da_aplicacao_nao_adultera_a_trilha_de_acesso(comando, sessao_restrita, semente):
    """Quem escreve `usuario_auditoria` e o gatilho, nao a aplicacao.

    Os tres verbos, e nao so `update`: inserir linha falsa e tao eficaz para
    confundir uma investigacao quanto reescrever uma verdadeira.
    """
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text(comando))


def test_papel_da_aplicacao_nao_consome_a_sequence_da_trilha(sessao_restrita, semente):
    """`nextval` permitido deixa abrir buracos artificiais na numeracao.

    Baixo impacto isolado; numa trilha de auditoria, numeracao com buraco e
    exatamente o que se olha para decidir se alguem apagou alguma coisa.
    """
    with pytest.raises(ProgrammingError, match="permission denied"), _isolado(sessao_restrita):
        sessao_restrita.execute(text("select nextval('usuario_auditoria_id_seq')"))


# -- os limites da funcao de concessao, testados NO BANCO ---------------------
#
# Os testes de `test_administrar_acessos.py` exercitam a camada Python. Estes
# chamam a funcao direto, como faria quem tem a connection string — que e
# justamente o caminho em que a checagem do Python nao existe.


def _dois_usuarios(sessao, admin=True):
    concedente = sessao.execute(
        text(
            "insert into usuario (entra_object_id, email, nome, acesso_irrestrito, papel_id) "
            "values (:o, :e, 'Concedente', true, "
            "        (select id from papel where codigo = :papel)) returning id"
        ),
        {
            "o": f"c-{uuid4().hex[:8]}",
            "e": f"{uuid4().hex[:8]}@aegea.com.br",
            "papel": "coordenacao" if admin else "analista",
        },
    ).scalar()
    alvo = sessao.execute(
        text(
            "insert into usuario (entra_object_id, email, nome) "
            "values (:o, :e, 'Alvo') returning id"
        ),
        {"o": f"a-{uuid4().hex[:8]}", "e": f"{uuid4().hex[:8]}@aegea.com.br"},
    ).scalar()
    return concedente, alvo


def _conceder(sessao, alvo, quem, papel="coordenacao"):
    sessao.execute(
        text(
            "select conceder_acesso(:alvo, :quem, :papel, true, false, null, "
            "'{}'::text[], '{}'::text[])"
        ),
        {"alvo": alvo, "quem": quem, "papel": papel},
    )


def test_funcao_recusa_autoconcessao(sessao_restrita, semente):
    """O caminho mais curto da escalada, e o mais provavel por engano.

    A checagem equivalente existe no Python, mas some quando alguem chama a
    funcao pela connection string. Barrar aqui NAO torna a funcao uma fronteira
    de autorizacao — quem tem a credencial passa o id de outra pessoa —, mas
    fecha o atalho.
    """
    _, alvo = _dois_usuarios(sessao_restrita)
    with pytest.raises(InternalError), _isolado(sessao_restrita):
        _conceder(sessao_restrita, alvo, alvo)


def test_funcao_recusa_concedente_sem_permissao(sessao_restrita, semente):
    concedente, alvo = _dois_usuarios(sessao_restrita, admin=False)
    with pytest.raises(InternalError), _isolado(sessao_restrita):
        _conceder(sessao_restrita, alvo, concedente)


def test_funcao_recusa_frente_inexistente(sessao_restrita, semente):
    """`usuario_escopo` nao tem chave estrangeira: a dimensao e polimorfica.

    Sem esta conferencia, a tela informa sucesso e a pessoa nao ve nada — e
    ninguem entende por que, porque a linha esta la, com o valor pedido.
    """
    concedente, alvo = _dois_usuarios(sessao_restrita)
    with pytest.raises(InternalError), _isolado(sessao_restrita):
        sessao_restrita.execute(
            text(
                "select conceder_acesso(:alvo, :quem, 'externo', false, true, "
                "'2026-12-31'::date, array['NAO_EXISTE'], '{}'::text[])"
            ),
            {"alvo": alvo, "quem": concedente},
        )


def test_funcao_nao_e_executavel_por_public(sessao_restrita):
    """Funcao nasce executavel por `PUBLIC` no PostgreSQL.

    Sem a revogacao, a concessao explicita a `painel_app` seria decorativa:
    qualquer papel com conexao chamaria a funcao privilegiada.

    A assinatura precisa estar COMPLETA aqui, com o `timestamptz` final da
    versao otimista: `has_function_privilege` sobre uma assinatura que nao
    existe devolve erro ou `false`, e o teste passaria em falso.
    """
    pode = sessao_restrita.execute(
        text(
            "select has_function_privilege('public', "
            "'conceder_acesso(uuid,uuid,text,boolean,boolean,date,"
            "text[],text[],timestamptz)', 'EXECUTE')"
        )
    ).scalar()
    assert pode is False


def test_ninguem_cria_objeto_no_schema_public(sessao_restrita):
    """`security definer` com `search_path = public` depende disto.

    Se um papel qualquer pudesse criar em `public`, plantaria uma funcao com
    nome de built-in e a funcao privilegiada passaria a chama-la.
    """
    pode = sessao_restrita.execute(
        text("select has_schema_privilege('public', 'public', 'CREATE')")
    ).scalar()
    assert pode is False


#: Toda tabela cujo nome termina em `_auditoria` é trilha, e trilha não se
#: reescreve pela aplicação.
SUFIXO_DE_TRILHA = "_auditoria"


def test_nenhuma_trilha_e_gravavel_pela_aplicacao(sessao_restrita):
    """Uma invariante, e não uma revogação lembrada caso a caso.

    O `alter default privileges` da 0009 concede `select, insert, update` em
    TODA tabela nova criada pelo mesmo papel. `usuario_auditoria` nasceu
    gravável por causa disso, e só não ficou porque um teste apanhou — a
    revogação em `interacao_auditoria` não se estende sozinha.

    Este teste falha na PRÓXIMA tabela de trilha que alguém criar sem revogar,
    em vez de esperar a próxima revisão.
    """
    trilhas = sessao_restrita.execute(
        text(
            "select table_name from information_schema.tables "
            " where table_schema = 'public' and table_name like :padrao"
        ),
        {"padrao": f"%{SUFIXO_DE_TRILHA}"},
    ).scalars().all()

    assert trilhas, "nenhuma tabela de trilha encontrada — o padrão de nome mudou?"

    graváveis = {
        nome: [
            privilegio
            for privilegio in ("INSERT", "UPDATE", "DELETE")
            if sessao_restrita.execute(
                text("select has_table_privilege('painel_app', :t, :p)"),
                {"t": nome, "p": privilegio},
            ).scalar()
        ]
        for nome in trilhas
    }
    graváveis = {nome: p for nome, p in graváveis.items() if p}

    assert not graváveis, f"trilha gravável pela aplicação: {graváveis}"
