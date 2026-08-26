"""Concessão de acesso: as regras da função e o rastro que ela deixa.

O ponto desta suíte não é a tela. É que a aplicação não alcança as colunas de
autorização sem passar por `conceder_acesso` (migration 0006), que toda
alteração aparece em `usuario_auditoria` venha de onde vier, e que duas pessoas
editando o mesmo acesso não se sobrescrevem.

A função NÃO é fronteira de autorização contra quem tem a credencial do banco —
`quem_concede` é parâmetro. Ver o cabeçalho da migration.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.casos_de_uso import administrar_acessos
from app.configuracao import obter_configuracao
from app.dominio.erros import NaoAutorizado, RegraViolada
from app.seguranca import sessao_assinada
from app.seguranca.cache_de_autorizacao import cache_para, limpar_todos
from main import app
from tests.test_acesso_http import SEGREDO, configuracao_real
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


def cria_usuario(sessao, papel_codigo: str | None = None, **ajustes) -> Usuario:
    papel_id = None
    if papel_codigo:
        papel_id = sessao.scalars(
            select(Papel.id).where(Papel.codigo == papel_codigo)
        ).first()

    sufixo = uuid4().hex[:8]
    registro = Usuario(
        entra_object_id=f"oid-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome=f"Pessoa {sufixo}",
        papel_id=papel_id,
        **ajustes,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def versao(sessao, alvo) -> object:
    """A versão corrente de quem vai receber a concessão.

    Conceder duas vezes seguidas exige reler a versão entre uma e outra — que é
    o que a tela faz ao recarregar a lista depois de salvar. `versao_vista` nunca
    é neutro: nulo AFIRMA que a pessoa nunca teve papel.
    """
    sessao.flush()
    identificador = getattr(alvo, "id", alvo)
    sessao.expire(sessao.get(Usuario, identificador))
    return sessao.get(Usuario, identificador).papel_concedido_em


def como(sessao, registro: Usuario):
    from app.casos_de_uso.provisionar_usuario import (
        carregar,
    )

    return carregar(sessao, registro.id)


# -- quem pode conceder --------------------------------------------------------


def test_sem_administra_acessos_nao_lista(sessao):
    analista = como(sessao, cria_usuario(sessao, "crm", acesso_irrestrito=True))
    with pytest.raises(NaoAutorizado):
        administrar_acessos.listar(sessao, solicitante=analista)


def test_sem_administra_acessos_nao_concede(sessao):
    analista = como(sessao, cria_usuario(sessao, "crm", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)
    with pytest.raises(NaoAutorizado):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(papel="plataforma", versao_vista=None),
            solicitante=analista,
        )


def test_ninguem_altera_o_proprio_acesso(sessao):
    """Não é paranoia.

    Quem se rebaixa por engano fica sem conseguir se consertar, e quem conserta
    é outra pessoa com o mesmo papel — que pode não existir. Pior seria alguém
    se conceder mais do que tem.
    """
    admin = cria_usuario(sessao, "plataforma", acesso_irrestrito=True)
    with pytest.raises(RegraViolada, match="próprio acesso"):
        administrar_acessos.conceder(
            sessao,
            alvo=admin.id,
            concessao=administrar_acessos.Concessao(papel="plataforma", versao_vista=None),
            solicitante=como(sessao, admin),
        )


# -- a concessão em si ---------------------------------------------------------


def test_concede_papel_e_escopo(sessao):
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    administrar_acessos.conceder(
        sessao,
        alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="score",
            externo=True,
            expira_em=date.today() + timedelta(days=90),
            frentes=("imprensa",),
            versao_vista=None,
        ),
        solicitante=admin,
    )
    sessao.flush()

    atual = como(sessao, alvo)
    assert atual.papel.codigo == "score"
    assert atual.externo
    assert atual.escopo.frentes == {"imprensa"}


def test_revogar_e_conceder_papel_nenhum(sessao):
    """A pessoa continua existindo e passa a não alcançar nada.

    É o oposto de apagar: o histórico dela permanece atribuído, e o registro de
    quem revogou fica na trilha.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao, "crm", acesso_irrestrito=True)

    # `versao_vista=None` mesmo com o alvo JÁ tendo papel, e isto é verdade
    # aqui: `cria_usuario` escreve `papel_id` direto pelo ORM, sem passar por
    # `conceder_acesso`, então `papel_concedido_em` continua nulo. É o mesmo
    # estado de quem teve o papel mexido por SQL direto no banco.
    #
    # Se um dia `cria_usuario` passar a carimbar a data, este teste falha com
    # "mudou enquanto" — e a correção será ler a versão, não voltar o nulo.
    administrar_acessos.conceder(
        sessao,
        alvo=alvo.id,
        concessao=administrar_acessos.Concessao(papel=None, versao_vista=None),
        solicitante=admin,
    )
    sessao.flush()

    atual = como(sessao, alvo)
    assert atual.sem_autorizacao
    assert atual.escopo.nao_alcanca_nada


def test_a_concessao_substitui_em_vez_de_somar(sessao):
    """`PUT`, não `PATCH`: a concessão é o estado completo.

    Aplicar diferença abriria a porta para "acrescentei uma frente e esqueci que
    ele já tinha acesso irrestrito" — e o erro só apareceria depois.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    for frentes in (("imprensa", "governo"), ("governo",)):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(papel="score", externo=True,
                                                    expira_em=date.today() + timedelta(days=30),
                                                    frentes=frentes,
                                                    versao_vista=versao(sessao, alvo)),
            solicitante=admin,
        )
        sessao.flush()

    assert como(sessao, alvo).escopo.frentes == {"governo"}


# -- as regras que o BANCO impõe ----------------------------------------------


def test_externo_sem_prazo_e_recusado(sessao):
    """A validação mora na função, e não só aqui.

    A função é a fronteira de confiança: quem a chama tem privilégio menor do
    que ela. Validar lá é o que impede que um caminho futuro esqueça a regra.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    with pytest.raises(RegraViolada, match="prazo"):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="score",
                externo=True,
                versao_vista=None,
            ),
            solicitante=admin,
        )


def test_irrestrito_com_externo_e_recusado(sessao):
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    with pytest.raises(RegraViolada):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="score", externo=True, acesso_irrestrito=True,
                expira_em=date.today() + timedelta(days=30),
                versao_vista=None,
            ),
            solicitante=admin,
        )


def test_papel_inexistente_e_recusado(sessao):
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    with pytest.raises(RegraViolada, match="[Pp]apel"):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(papel="chefao", versao_vista=None),
            solicitante=admin,
        )


def test_mensagem_de_erro_nao_traz_a_instrucao_sql(sessao):
    """`str(erro)` do SQLAlchemy traz o SQL inteiro e os parâmetros ligados.

    Isso inclui ids de usuário, e vai para o log — não para a tela.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    with pytest.raises(RegraViolada) as erro:
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="score",
                externo=True,
                versao_vista=None,
            ),
            solicitante=admin,
        )
    texto = str(erro.value)
    assert "select conceder_acesso" not in texto
    assert str(alvo.id) not in texto


# -- a trilha ------------------------------------------------------------------


def test_concessao_deixa_rastro_com_autor(sessao):
    """A pergunta que motivou a tabela: quem liberou este acesso?"""
    admin = cria_usuario(sessao, "plataforma", acesso_irrestrito=True)
    alvo = cria_usuario(sessao)

    administrar_acessos.conceder(
        sessao,
        alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="crm",
            acesso_irrestrito=True,
            versao_vista=None,
        ),
        solicitante=como(sessao, admin),
    )
    sessao.flush()

    linhas = sessao.execute(
        text(
            "select campo, valor_novo, concedido_por, origem "
            "from usuario_auditoria where usuario_id = :id"
        ),
        {"id": alvo.id},
    ).all()

    campos = {linha.campo for linha in linhas}
    assert "papel_id" in campos
    assert all(linha.concedido_por == admin.id for linha in linhas)
    assert all(linha.origem for linha in linhas), "session_user sempre é gravado"


def test_escopo_concedido_e_removido_aparecem_na_trilha(sessao):
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)
    prazo = date.today() + timedelta(days=30)

    for frentes in (("imprensa",), ("governo",)):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="score", externo=True, expira_em=prazo, frentes=frentes,
                versao_vista=versao(sessao, alvo),
            ),
            solicitante=admin,
        )
        sessao.flush()

    linhas = sessao.execute(
        text(
            "select valor_anterior, valor_novo from usuario_auditoria "
            "where usuario_id = :id and campo = 'escopo.frente'"
        ),
        {"id": alvo.id},
    ).all()

    entradas = {linha.valor_novo for linha in linhas if linha.valor_novo}
    saidas = {linha.valor_anterior for linha in linhas if linha.valor_anterior}
    assert entradas == {"imprensa", "governo"}
    assert saidas == {"imprensa"}


# -- pela HTTP -----------------------------------------------------------------


@pytest.fixture
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = configuracao_real
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def entra(cliente, registro: Usuario) -> str:
    cookie = sessao_assinada.assinar(
        sessao_assinada.nova_sessao(registro.id), SEGREDO
    )
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie)
    return sessao_assinada.ler(cookie, SEGREDO).csrf


def test_rota_de_listagem_exige_o_papel(cliente, sessao):
    analista = cria_usuario(sessao, "crm", acesso_irrestrito=True)
    entra(cliente, analista)
    assert cliente.get("/api/acessos").status_code == 403


def test_rota_concede_pela_http(cliente, sessao):
    admin = cria_usuario(sessao, "plataforma", acesso_irrestrito=True)
    alvo = cria_usuario(sessao)
    token = entra(cliente, admin)

    resposta = cliente.put(
        f"/api/acessos/{alvo.id}",
        headers={"X-CSRF-Token": token},
        json={
            "papel": "score",
            # `externo` é o BOOLEANO de convidado de fora, e não o código de um
            # papel. Os dois se chamavam parecido enquanto existia um papel
            # `externo`, e uma troca de nomes em massa confundiu os dois: a
            # chave virou `score` e o teste passou a mandar um campo que a rota
            # ignora — continuava verde sem exercitar a regra do prazo.
            "externo": True,
            "expira_em": (date.today() + timedelta(days=60)).isoformat(),
            "frentes": ["imprensa"],
            # Explícito porque o campo é obrigatório: nulo AFIRMA "vi esta
            # pessoa sem concessão nenhuma", e aqui é verdade.
            "versao_vista": None,
        },
    )
    assert resposta.status_code == 204, resposta.text
    assert como(sessao, alvo).escopo.frentes == {"imprensa"}


def test_rota_exige_a_versao_vista(cliente, sessao):
    """Omitir o campo é 422, e não uma sobrescrita silenciosa.

    Enquanto havia default, quem não conhecesse o campo apagava concessão
    alheia sem nunca ter decidido apagar. O erro é mais barato.
    """
    admin = cria_usuario(sessao, "plataforma", acesso_irrestrito=True)
    alvo = cria_usuario(sessao)
    token = entra(cliente, admin)

    resposta = cliente.put(
        f"/api/acessos/{alvo.id}",
        headers={"X-CSRF-Token": token},
        json={"papel": "crm", "acesso_irrestrito": True},
    )
    assert resposta.status_code == 422, resposta.text
    assert "versao_vista" in resposta.text


def test_concessao_pela_http_exige_token_anti_csrf(cliente, sessao):
    """Conceder acesso é o alvo mais valioso de um CSRF neste sistema."""
    admin = cria_usuario(sessao, "plataforma", acesso_irrestrito=True)
    alvo = cria_usuario(sessao)
    entra(cliente, admin)

    resposta = cliente.put(f"/api/acessos/{alvo.id}", json={"papel": "plataforma"})
    assert resposta.status_code == 403


def test_historico_pela_http(cliente, sessao):
    admin = cria_usuario(sessao, "plataforma", acesso_irrestrito=True)
    alvo = cria_usuario(sessao)
    token = entra(cliente, admin)

    cliente.put(
        f"/api/acessos/{alvo.id}",
        headers={"X-CSRF-Token": token},
        json={"papel": "sintese", "acesso_irrestrito": True, "versao_vista": None},
    )
    corpo = cliente.get(f"/api/acessos/{alvo.id}/historico").json()

    assert any(linha["campo"] == "papel_id" for linha in corpo)
    assert all(linha["origem"] for linha in corpo)


def test_erro_inesperado_nao_vaza_estrutura_do_banco(sessao):
    """Erro inesperado do banco não chega à tela.

    Devolver a primeira linha de qualquer erro parece seguro — evita o SQL e os
    parâmetros que `str(erro)` traz —, mas entrega a forma do schema:

        insert or update on table "usuario" violates foreign key constraint
        "usuario_papel_concedido_por_fkey"

    Filtrar por SQLSTATE separa "mensagem que escrevi para o usuário" do que o
    Postgres achou de dizer.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))

    with pytest.raises(RegraViolada) as erro:
        administrar_acessos.conceder(
            sessao,
            alvo=uuid4(),  # não existe: a função levanta antes, mas por outro caminho
            concessao=administrar_acessos.Concessao(
                papel="crm",
                acesso_irrestrito=True,
                versao_vista=None,
            ),
            solicitante=admin,
        )

    texto = str(erro.value)
    assert "constraint" not in texto.lower()
    assert "insert or update on table" not in texto.lower()


def test_mensagem_escrita_pela_funcao_chega_ao_usuario(sessao):
    """O outro lado: filtrar não pode engolir o texto útil.

    "Acesso externo exige prazo" é uma frase escrita para quem está na tela.
    Trocá-la por "não foi possível" tornaria a validação inútil na prática.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    with pytest.raises(RegraViolada, match="prazo"):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="score",
                externo=True,
                versao_vista=None,
            ),
            solicitante=admin,
        )


# -- alteração concorrente -----------------------------------------------------


def test_dois_administradores_nao_se_sobrescrevem(sessao):
    """O lost update, que é do tipo que ninguém percebe.

    A tela manda o estado completo e a função troca tudo. Se A abre o
    formulário, B acrescenta uma unidade, e A salva o que tinha na tela, a
    mudança de B some — sem conflito, sem aviso. O acesso simplesmente volta a
    ser o de antes, e ninguém liga uma coisa à outra.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    # A concessão inicial, que dá a versão que "A" vê na tela.
    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="crm",
            acesso_irrestrito=True,
            versao_vista=None,
        ),
        solicitante=admin,
    )
    sessao.flush()
    versao_que_A_viu = sessao.get(Usuario, alvo.id).papel_concedido_em

    # "B" altera enquanto o formulário de "A" está aberto. "B" acabou de
    # recarregar a lista, então manda a versão de agora — e passa.
    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="sintese", acesso_irrestrito=True,
            versao_vista=versao(sessao, alvo),
        ),
        solicitante=admin,
    )
    sessao.flush()

    # "A" salva o que tinha na tela.
    with pytest.raises(RegraViolada, match="mudou enquanto"):
        administrar_acessos.conceder(
            sessao, alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="crm", acesso_irrestrito=True, versao_vista=versao_que_A_viu
            ),
            solicitante=admin,
        )


def test_sem_versao_a_primeira_concessao_passa(sessao):
    """Nulo é "vi esta pessoa sem concessão nenhuma", e aqui é verdade.

    Exigir versão sempre impediria a primeira concessão — que é justamente a
    mais comum na tela. `is distinct from` compara nulo com nulo como
    igualdade, então o caso passa sem precisar de exceção no código.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="crm",
            acesso_irrestrito=True,
            versao_vista=None,
        ),
        solicitante=admin,
    )
    sessao.flush()
    assert como(sessao, alvo).papel.codigo == "crm"


def test_versao_nula_nao_e_curinga(sessao):
    """Nulo NÃO passa por cima de uma concessão que já existe.

    É o caso mais comum de todos, e por isso tem teste próprio: toda pessoa nova
    aparece na lista com `concedido_em` nulo, e é isso que a tela manda de volta.
    Se nulo fosse curinga, bastaria uma tela aberta antes da concessão de outra
    pessoa para apagá-la — sem conflito e sem aviso.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    outro = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    # "B" concede, e o alvo passa a ter versão.
    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="crm",
            acesso_irrestrito=True,
            versao_vista=None,
        ),
        solicitante=outro,
    )
    sessao.flush()

    # "A", com a tela aberta desde antes, ainda acha que o alvo não tem nada —
    # e é exatamente por isso que manda nulo.
    # `begin_nested` porque a exceção vem de `raise` DENTRO da função do
    # banco, e isso aborta a transação inteira: sem o savepoint, a leitura
    # seguinte falharia com "transaction is aborted" e o teste passaria pelo
    # motivo errado. Na API não aparece — lá cada requisição é uma transação,
    # e ela é descartada inteira.
    ponto = sessao.begin_nested()
    with pytest.raises(RegraViolada, match="mudou enquanto"):
        administrar_acessos.conceder(
            sessao, alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel="plataforma", acesso_irrestrito=True, versao_vista=None
            ),
            solicitante=admin,
        )
    # `rollback`, e nao sair do `with`: sair TENTA liberar o savepoint, e a
    # transacao ja esta abortada -- o proprio RELEASE falha. Desfazer e a unica
    # saida.
    ponto.rollback()

    sessao.expire_all()
    assert como(sessao, alvo).papel.codigo == "crm", (
        "a concessão de quem chegou primeiro tem de continuar de pé"
    )


# -- concorrência de verdade, e não formulário desatualizado ------------------
#
# Os testes acima simulam "A abriu a tela antes de B salvar": as escritas
# acontecem uma DEPOIS da outra. É o caso comum, e não é este.
#
# Aqui as duas transações estão abertas AO MESMO TEMPO, em conexões diferentes.
# Sem o `for update` da função (migration 0006) as duas leriam a mesma
# `versao_atual` antes de qualquer uma escrever, as duas passariam na
# comparação, e a segunda apagaria a primeira. Mesmo sintoma do formulário
# desatualizado, causa diferente — e o teste sequencial passa nos dois casos.


@pytest.fixture
def dois_usuarios_comitados():
    """Admin e alvo que EXISTEM para outras conexões.

    A fixture `sessao` faz rollback no fim, então nada que ela escreve é visível
    de fora. Um teste de concorrência precisa de duas conexões enxergando as
    mesmas linhas, e para isso os dados precisam estar comitados — a limpeza
    passa a ser manual.
    """
    sufixo = uuid4().hex[:8]
    with _engine.begin() as conexao:
        admin = conexao.execute(
            text(
                "insert into usuario (entra_object_id, email, nome, acesso_irrestrito, papel_id) "
                "values (:o, :e, 'Admin', true, (select id from papel where codigo='plataforma')) "
                "returning id"
            ),
            {"o": f"conc-admin-{sufixo}", "e": f"admin-{sufixo}@aegea.com.br"},
        ).scalar()
        alvo = conexao.execute(
            text(
                "insert into usuario (entra_object_id, email, nome) "
                "values (:o, :e, 'Alvo') returning id"
            ),
            {"o": f"conc-alvo-{sufixo}", "e": f"alvo-{sufixo}@aegea.com.br"},
        ).scalar()
        # Uma concessão inicial, para o alvo passar a ter versão.
        conexao.execute(
            text(
                "select conceder_acesso(:alvo, :quem, 'crm', true, false, "
                "null, '{}'::text[], '{}'::text[], null)"
            ),
            {"alvo": alvo, "quem": admin},
        )
        versao = conexao.execute(
            text("select papel_concedido_em from usuario where id = :id"), {"id": alvo}
        ).scalar()

    yield admin, alvo, versao

    with _engine.begin() as conexao:
        for id_ in (alvo, admin):
            conexao.execute(
                text("delete from usuario_auditoria where usuario_id = :id or concedido_por = :id"),
                {"id": id_},
            )
            conexao.execute(text("delete from usuario_escopo where usuario_id = :id"), {"id": id_})
        conexao.execute(
            text("update usuario set papel_concedido_por = null where id in (:a, :b)"),
            {"a": alvo, "b": admin},
        )
        conexao.execute(text("delete from usuario where id in (:a, :b)"), {"a": alvo, "b": admin})


def _esperou_por_lock(prazo_segundos: float = 10.0) -> bool:
    """Houve um backend bloqueado esperando lock dentro de `conceder_acesso`?

    O teste de concorrência precisa saber que a segunda transação de fato
    PAROU, e não apenas que o tempo passou. Sem esta conferência, uma máquina
    lenta transforma o teste em tautologia.
    """
    import time

    limite = time.monotonic() + prazo_segundos
    while time.monotonic() < limite:
        with _engine.connect() as conexao:
            bloqueados = conexao.execute(
                text(
                    "select count(*) from pg_stat_activity "
                    " where datname = current_database() "
                    "   and wait_event_type = 'Lock' "
                    "   and query ilike '%conceder_acesso%'"
                )
            ).scalar()
        if bloqueados:
            return True
        time.sleep(0.05)
    return False


def _conceder(conexao, *, alvo, quem, papel, versao):
    conexao.execute(
        text(
            "select conceder_acesso(:alvo, :quem, :papel, true, false, null, "
            "'{}'::text[], '{}'::text[], :versao)"
        ),
        {"alvo": alvo, "quem": quem, "papel": papel, "versao": versao},
    )


def test_duas_concessoes_simultaneas_nao_se_atropelam(dois_usuarios_comitados):
    """Concorrência de verdade: a segunda espera e acorda vendo a versão nova.

    Os testes acima simulam formulário desatualizado — as escritas acontecem uma
    DEPOIS da outra. Aqui as duas transações estão abertas ao mesmo tempo, em
    conexões diferentes, que é o caso que o `for update` da função existe para
    cobrir: sem ele, as duas leriam a mesma versão antes de qualquer uma
    escrever, as duas passariam na comparação, e a segunda venceria.

    COMO NÃO ESCREVER ESTE TESTE, porque a armadilha é sutil: usar
    `lock_timeout` e afirmar "a segunda estourou o prazo, logo a linha estava
    travada" não distingue nada. Ela estoura de qualquer jeito — mesmo sem
    `for update`, a segunda transação chega ao PRÓPRIO `update` e trava ali.

    O que distingue é deixar a segunda esperar e olhar o DESFECHO: travada antes
    de comparar, ela acorda lendo o carimbo novo e é recusada; travada só no
    `update`, ela já comparou com o carimbo velho e escreve por cima.

    Por isso a segunda roda numa thread: precisa ficar bloqueada de verdade
    enquanto a primeira decide.
    """
    import threading

    admin, alvo, versao = dois_usuarios_comitados
    desfecho: dict[str, object] = {}

    primeira = _engine.connect()
    primeira.begin()
    _conceder(primeira, alvo=alvo, quem=admin, papel="sintese", versao=versao)
    ja_comitou = False

    def segunda_concessao() -> None:
        with _engine.connect() as conexao:
            conexao.begin()
            try:
                # MESMA versão que a primeira usou: as duas telas foram abertas
                # antes de qualquer uma salvar.
                _conceder(conexao, alvo=alvo, quem=admin, papel="score", versao=versao)
                conexao.commit()
                desfecho["resultado"] = "escreveu"
            except Exception as erro:  # noqa: BLE001 - o teste julga a mensagem
                conexao.rollback()
                desfecho["resultado"] = "recusou"
                desfecho["mensagem"] = str(erro)

    thread = threading.Thread(target=segunda_concessao, daemon=True)
    thread.start()

    # Espera VERIFICADA, e não um `join(timeout=...)` na esperança de que dois
    # segundos bastem.
    #
    # Dormir um tempo fixo aqui deixaria o teste passar pelo motivo errado numa
    # máquina lenta: se a segunda transação ainda não tivesse chegado ao ponto
    # de bloqueio quando a primeira comitasse, ela leria o carimbo NOVO e seria
    # recusada — o desfecho que o teste espera — sem que `for update` tivesse
    # participado de nada. Verde, e provando o contrário do que diz.
    #
    # `pg_stat_activity` responde a pergunta certa: existe um backend PARADO
    # esperando um lock, executando a nossa função? Enquanto não existir, a
    # primeira não comita.
    try:
        assert _esperou_por_lock(), (
            "a segunda concessão não chegou a bloquear — sem isso o teste não "
            "distingue a correção da ausência dela"
        )
    finally:
        # `finally`, e não depois do assert.
        #
        # Se a conferência acima falhar, esta transação fica ABERTA segurando o
        # lock da linha — e o teardown da fixture, que apaga as mesmas linhas
        # comitadas, trava atrás dela. Um teste que falha derrubaria a suíte
        # inteira por travamento, e a mensagem que apareceria seria a do
        # travamento, não a do defeito.
        #
        # O `commit` é o que a segunda thread está esperando: solta ela também.
        primeira.commit()
        primeira.close()
        ja_comitou = True

    assert ja_comitou

    thread.join(timeout=10)
    assert not thread.is_alive(), "a segunda concessão ficou presa"

    assert desfecho.get("resultado") == "recusou", (
        "a segunda transação escreveu por cima: ela comparou a versão antes de "
        "travar, que é justamente o que o `for update` da função impede"
    )
    assert "mudou enquanto" in str(desfecho.get("mensagem", ""))

    with _engine.connect() as conferencia:
        papel = conferencia.execute(
            text(
                "select p.codigo from usuario u join papel p on p.id = u.papel_id "
                " where u.id = :id"
            ),
            {"id": alvo},
        ).scalar()
    assert papel == "sintese", "quem chegou primeiro tem de continuar de pé"


# -- revogar é estado limpo ----------------------------------------------------


def test_revogar_apaga_escopo_e_prazo(sessao):
    """Revogar é estado limpo: sem papel, sem alcance, sem prazo.

    Guardar o escopo de quem não tem papel é guardar uma surpresa para quem
    conceder papel depois: o alcance de um contrato encerrado ressuscitaria
    intacto, sem ninguém pedir.
    """
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="score", externo=True,
            expira_em=date.today() + timedelta(days=30), frentes=("imprensa",),
            versao_vista=None,
        ),
        solicitante=admin,
    )
    sessao.flush()

    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel=None, versao_vista=versao(sessao, alvo)
        ),
        solicitante=admin,
    )
    sessao.flush()

    registro = sessao.get(Usuario, alvo.id)
    assert registro.papel_id is None
    assert registro.externo is False
    assert registro.acesso_expira_em is None
    assert como(sessao, alvo).escopo.frentes == frozenset()


def test_escopo_antigo_nao_ressuscita(sessao):
    """O cenário completo: revogar e conceder de novo."""
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao)

    administrar_acessos.conceder(
        sessao, alvo=alvo.id,
        concessao=administrar_acessos.Concessao(
            papel="score", externo=True,
            expira_em=date.today() + timedelta(days=30), frentes=("imprensa",),
            versao_vista=None,
        ),
        solicitante=admin,
    )
    sessao.flush()

    for papel in (None, "sintese"):
        administrar_acessos.conceder(
            sessao, alvo=alvo.id,
            concessao=administrar_acessos.Concessao(
                papel=papel, acesso_irrestrito=False,
                versao_vista=versao(sessao, alvo),
            ),
            solicitante=admin,
        )
        sessao.flush()

    # Papel novo, alcance nenhum: quem concedeu precisa dizer o escopo de novo.
    assert como(sessao, alvo).escopo.frentes == frozenset()


# -- provisionamento: colisão de e-mail ----------------------------------------


def test_email_ja_provisionado_com_outro_oid_recusa_com_mensagem(sessao):
    """Recusa clara em vez de 500 opaco — e sem reatribuir identidade.

    `provisionar` busca por `entra_object_id`, mas o e-mail também é único. Dois
    identificadores do provedor para o mesmo e-mail acontecem de verdade em
    desenvolvimento, alternando entre `AUTH_MOCK` e o SSO real: sem tratamento,
    o `flush` levanta `UniqueViolation` e a API devolve 500 sem pista nenhuma.

    A saída NÃO é trocar o `oid` da linha existente. Ele é a identidade estável,
    e trocá-lo em silêncio entregaria a conta de uma pessoa a outra que apenas
    tenha o mesmo e-mail. A resolução é humana, e a mensagem diz isso.
    """
    from app.casos_de_uso.provisionar_usuario import provisionar

    sufixo = uuid4().hex[:8]
    email = f"{sufixo}@aegea.com.br"
    sessao.add(
        Usuario(entra_object_id=f"oid-sso-{sufixo}", email=email, nome="Pessoa")
    )
    sessao.flush()

    with pytest.raises(NaoAutorizado, match="outro identificador"):
        provisionar(
            sessao,
            entra_object_id=f"oid-mock-{sufixo}",
            email=email,
            nome="Pessoa",
        )


# -- a revogação pela tela vale no ato, apesar do cache -------------------------


def test_conceder_descarta_o_que_o_cache_sabia_do_alvo(sessao):
    """A garantia que sustenta a janela do cache.

    Papel e escopo valem por `autorizacao_cache_segundos` em memória, então uma
    revogação escrita por FORA da aplicação demora a valer. Pela aplicação, não:
    `conceder()` descarta a entrada do alvo.

    Isso importa porque é exatamente aí que alguém confere se a revogação pegou
    — administrador revoga e vai olhar. Se o cache respondesse a permissão
    antiga nesse momento, a conclusão seria "não funcionou", e a próxima ação
    seria revogar de novo, ou pior, ir mexer no banco.
    """
    limpar_todos()
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao, "crm", acesso_irrestrito=True)

    cache = cache_para(300.0)
    cache.guardar(como(sessao, alvo))
    assert cache.obter(alvo.id) is not None

    administrar_acessos.conceder(
        sessao,
        alvo=alvo.id,
        concessao=administrar_acessos.Concessao(papel=None, versao_vista=None),
        solicitante=admin,
    )

    assert cache.obter(alvo.id) is None


def test_conceder_nao_derruba_o_cache_de_quem_nao_foi_alterado(sessao):
    """Descartar demais custa o que o cache economiza.

    Se uma concessão esvaziasse o cache inteiro, num painel com dezenas de
    pessoas conectadas cada mexida de permissão faria todas voltarem a reler o
    banco — e revogação em lote viraria uma rajada de consultas.
    """
    limpar_todos()
    admin = como(sessao, cria_usuario(sessao, "plataforma", acesso_irrestrito=True))
    alvo = cria_usuario(sessao, "crm", acesso_irrestrito=True)
    terceiro = cria_usuario(sessao, "crm", acesso_irrestrito=True)

    cache = cache_para(300.0)
    cache.guardar(como(sessao, terceiro))

    administrar_acessos.conceder(
        sessao,
        alvo=alvo.id,
        concessao=administrar_acessos.Concessao(papel=None, versao_vista=None),
        solicitante=admin,
    )

    assert cache.obter(terceiro.id) is not None
