"""Desativar e reativar — a remoção do produto.

POR QUE NÃO É `DELETE`
----------------------
Dez chaves estrangeiras apontam para `usuario`, e `interacao.criado_por` é
`not null`. O banco recusa apagar quem já registrou qualquer coisa, e deve:
apagar o autor apagaria a autoria. Medido antes de escrever isto — apagar uma
conta sem nenhuma interação já falha em `acesso_log_usuario_id_fkey`.

Então "remover" é desligar. E como é a única remoção que existe, ela precisa
funcionar de verdade: barrar o login (coberto em `test_recusa_de_login.py`),
deixar rastro, e não deixar a plataforma sem quem administre.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.casos_de_uso import administrar_acessos
from app.casos_de_uso.provisionar_usuario import carregar
from app.configuracao import obter_configuracao
from app.dominio.erros import NaoAutorizado, RegraViolada
from app.seguranca import sessao_assinada
from app.seguranca.cache_de_autorizacao import limpar_todos
from main import app
from tests.test_acesso_http import SEGREDO, configuracao_real
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def marca():
    return uuid4().hex[:8]


@pytest.fixture
def sessao(marca):
    """Transacional: nada do que o teste escrever sobrevive.

    Aqui dá para usar a sessão transacional — ao contrário de
    `test_recusa_de_login.py`, nenhum destes caminhos grava trilha de login por
    uma sessão separada.
    """
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


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


def _pessoa(sessao, marca, *, papel: str | None, ativo: bool = True) -> Usuario:
    registro = Usuario(
        entra_object_id=f"oid-{uuid4().hex}",
        email=f"{uuid4().hex[:6]}.{marca}@aegea.com.br",
        nome="Pessoa de Teste",
        ativo=ativo,
    )
    if papel is not None:
        registro.papel_id = sessao.scalars(
            select(Papel).where(Papel.codigo == papel)
        ).first().id
    sessao.add(registro)
    sessao.flush()
    return registro


def _como(sessao, registro: Usuario):
    """O `UsuarioAtual` de quem está pedindo."""
    return carregar(sessao, registro.id)


# -- o caminho feliz -----------------------------------------------------------


def test_desativar_desliga_e_reativar_religa(sessao, marca):
    admin = _pessoa(sessao, marca, papel="plataforma_edicao")
    alvo = _pessoa(sessao, marca, papel="crm_leitura")

    administrar_acessos.definir_situacao(
        sessao, alvo=alvo.id, ativa=False, solicitante=_como(sessao, admin)
    )
    assert alvo.ativo is False

    administrar_acessos.definir_situacao(
        sessao, alvo=alvo.id, ativa=True, solicitante=_como(sessao, admin)
    )
    assert alvo.ativo is True


def test_a_trilha_registra_quem_desativou(sessao, marca):
    """Sem autor, a trilha responde "quando" e não responde "quem".

    O gatilho `auditar_acesso_do_usuario` vigia `ativo`, e `concedido_por` vem
    do `SET LOCAL` que a aplicação carimba. Este teste prova que os dois se
    encontram — o gatilho existir não basta se ninguém marcar o autor.
    """
    from app.banco.autoria import marcar_autor_na_sessao

    admin = _pessoa(sessao, marca, papel="plataforma_edicao")
    alvo = _pessoa(sessao, marca, papel="crm_leitura")
    marcar_autor_na_sessao(sessao, admin.id)

    administrar_acessos.definir_situacao(
        sessao, alvo=alvo.id, ativa=False, solicitante=_como(sessao, admin)
    )
    sessao.flush()

    linha = sessao.execute(
        text(
            "select campo, valor_anterior, valor_novo, concedido_por "
            "from usuario_auditoria where usuario_id = :i and campo = 'ativo' "
            "order by ocorrido_em desc limit 1"
        ),
        {"i": alvo.id},
    ).first()
    assert linha is not None, "desativar não deixou rastro"
    assert linha.valor_anterior == "true"
    assert linha.valor_novo == "false"
    assert linha.concedido_por == admin.id, "a trilha não sabe quem desativou"


def test_repetir_a_mesma_situacao_nao_polui_a_trilha(sessao, marca):
    """Dois cliques no mesmo botão não são dois fatos.

    Sem a guarda, a segunda chamada gravaria uma linha dizendo que `ativo`
    mudou de `false` para `false` — e quem lê a trilha depois contaria duas
    remoções onde houve uma.
    """
    admin = _pessoa(sessao, marca, papel="plataforma_edicao")
    alvo = _pessoa(sessao, marca, papel="crm_leitura", ativo=False)

    administrar_acessos.definir_situacao(
        sessao, alvo=alvo.id, ativa=False, solicitante=_como(sessao, admin)
    )
    sessao.flush()

    quantas = sessao.scalar(
        text(
            "select count(*) from usuario_auditoria "
            "where usuario_id = :i and campo = 'ativo'"
        ),
        {"i": alvo.id},
    )
    assert quantas == 0


# -- as guardas ----------------------------------------------------------------


def test_ninguem_desativa_a_propria_conta(sessao, marca):
    """Quem se desliga não consegue se religar."""
    admin = _pessoa(sessao, marca, papel="plataforma_edicao")

    with pytest.raises(RegraViolada) as erro:
        administrar_acessos.definir_situacao(
            sessao, alvo=admin.id, ativa=False, solicitante=_como(sessao, admin)
        )
    assert "própria conta" in str(erro.value)
    assert admin.ativo is True


def test_quem_nao_administra_acessos_nao_desativa(sessao, marca):
    """A porta é `administra_acessos`, o mesmo que governa o resto da tela."""
    editor = _pessoa(sessao, marca, papel="crm_edicao")
    alvo = _pessoa(sessao, marca, papel="crm_leitura")

    with pytest.raises(NaoAutorizado):
        administrar_acessos.definir_situacao(
            sessao, alvo=alvo.id, ativa=False, solicitante=_como(sessao, editor)
        )
    assert alvo.ativo is True


def test_a_plataforma_nao_fica_sem_administrador(sessao, marca):
    """A invariante, provada pelo caminho real — e sem guarda dedicada.

    Escrevi uma contagem de "administradores restantes" e este teste a matou:
    ela nunca dispara. Para desativar é preciso ser administrador ATIVO, e
    ninguém desativa a própria conta; logo quem pede sempre sobra.

    O teste ficou porque a INVARIANTE importa, mesmo que a guarda não exista:
    se alguém amanhã afrouxar a regra do próprio acesso, é aqui que aparece.
    """
    sessao.execute(
        text(
            "update usuario set ativo = false "
            "where papel_id = (select id from papel where codigo = 'plataforma_edicao')"
        )
    )
    primeiro = _pessoa(sessao, marca, papel="plataforma_edicao")
    segundo = _pessoa(sessao, marca, papel="plataforma_edicao")

    # Um desliga o outro: sobra um.
    administrar_acessos.definir_situacao(
        sessao, alvo=segundo.id, ativa=False, solicitante=_como(sessao, primeiro)
    )
    assert segundo.ativo is False

    # O que sobrou não consegue se desligar...
    with pytest.raises(RegraViolada):
        administrar_acessos.definir_situacao(
            sessao, alvo=primeiro.id, ativa=False, solicitante=_como(sessao, primeiro)
        )

    # ...e quem foi desligado não consegue mais pedir nada: `carregar` devolve
    # `None` para conta inativa, então não há de onde partir o pedido.
    assert _como(sessao, segundo) is None

    sobraram = sessao.scalar(
        text(
            "select count(*) from usuario u join papel p on p.id = u.papel_id "
            "where u.ativo and p.ativo and p.administra_acessos"
        )
    )
    assert sobraram >= 1, "a plataforma ficou sem quem administre acessos"


# -- pela rota -----------------------------------------------------------------


def _entrar(cliente, registro: Usuario) -> str:
    """Grava o cookie e devolve o token anti-CSRF que ele carrega.

    Toda escrita exige o cabecalho; sem ele a rota responde 403 antes de olhar
    permissao, e o teste passaria a medir o CSRF em vez do que quer medir.
    """
    cookie = sessao_assinada.assinar(sessao_assinada.nova_sessao(registro.id), SEGREDO)
    cliente.cookies.set(sessao_assinada.NOME_DO_COOKIE, cookie)
    return sessao_assinada.ler(cookie, SEGREDO).csrf


def test_rota_desativa(cliente, sessao, marca):
    admin = _pessoa(sessao, marca, papel="plataforma_edicao")
    alvo = _pessoa(sessao, marca, papel="crm_leitura")
    token = _entrar(cliente, admin)

    resposta = cliente.patch(
        f"/api/acessos/{alvo.id}/situacao",
        json={"ativo": False},
        headers={"X-CSRF-Token": token},
    )

    assert resposta.status_code == 204
    sessao.refresh(alvo)
    assert alvo.ativo is False


def test_rota_recusa_quem_nao_administra(cliente, sessao, marca):
    editor = _pessoa(sessao, marca, papel="crm_edicao")
    alvo = _pessoa(sessao, marca, papel="crm_leitura")
    token = _entrar(cliente, editor)

    resposta = cliente.patch(
        f"/api/acessos/{alvo.id}/situacao",
        json={"ativo": False},
        headers={"X-CSRF-Token": token},
    )

    assert resposta.status_code == 403
    sessao.refresh(alvo)
    assert alvo.ativo is True


# -- a corrida ----------------------------------------------------------------
#
# O Codex barrou o commit anterior por aqui, e tinha razão. Eu havia concluído
# que nenhuma guarda era precisa: quem desativa é administrador ativo e não
# desativa a própria conta, logo sempre sobra. Certo sequencialmente, inútil em
# paralelo — as duas transações leem antes de qualquer uma escrever, e escrevem
# em linhas DIFERENTES, então nada as serializa.
#
# Reproduzido no Postgres: dois administradores se desativando ao mesmo tempo
# terminavam com ZERO ativos.


def _em_paralelo(alvos, *, com_cadeado: bool) -> tuple[int, list[str]]:
    """Duas transações desativando uma a outra, cada uma na sua conexão.

    `com_cadeado=False` existe para a PROVA NEGATIVA: sem o cadeado o mesmo
    roteiro tem de furar. Um teste de concorrência que passa nos dois estados
    não prova nada.

    A BARREIRA, no caminho SEM cadeado, é o que torna a prova determinística.
    Sem ela o teste era intermitente: se uma transação terminasse inteira antes
    de a outra começar, a segunda leria o mundo já atualizado, veria zero
    administradores e se recusaria sozinha — e o teste "passava" sem nunca ter
    havido corrida. Com a barreira, as duas escrevem antes de qualquer uma
    conferir, e cada uma enxerga a outra ainda ativa (a escrita alheia não está
    commitada). É exatamente a leitura enganosa que o cadeado existe para
    impedir.
    """
    import threading

    engine = create_engine(URL, pool_pre_ping=True)
    recusas: list[str] = []
    ambas_escreveram = None if com_cadeado else threading.Barrier(2, timeout=20)

    def desativar(alvo):
        try:
            with engine.begin() as conexao:
                if com_cadeado:
                    # `try`, como em produção: esperar aqui criaria o deadlock
                    # que a própria correção evita.
                    if not conexao.scalar(
                        text(
                            "select pg_try_advisory_xact_lock("
                            "chave_do_cadeado_de_administradores())"
                        )
                    ):
                        raise RuntimeError(
                            "Outra alteração de acesso está em andamento."
                        )
                conexao.execute(
                    text("update usuario set ativo = false where id = :i"), {"i": alvo}
                )
                if ambas_escreveram is not None:
                    ambas_escreveram.wait()
                conexao.execute(text("select exigir_administrador_restante()"))
        except Exception as erro:  # noqa: BLE001
            recusas.append(str(erro))

    fios = [threading.Thread(target=desativar, args=(a,)) for a in alvos]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=30)
        assert not f.is_alive(), "a transação travou — cadeado preso?"

    with engine.begin() as conexao:
        sobraram = conexao.execute(
            text(
                "select count(*) from usuario u join papel p on p.id = u.papel_id "
                "where u.ativo and p.ativo and p.administra_acessos"
            )
        ).scalar()
    engine.dispose()
    return sobraram, recusas


@pytest.fixture
def dois_administradores(marca):
    """Deixa exatamente DOIS administradores ativos no banco, e desfaz depois.

    Precisa comprometer de verdade: as transações concorrentes rodam em outras
    conexões e não enxergariam uma transação aberta.
    """
    engine = create_engine(URL, pool_pre_ping=True)
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "update usuario set ativo = false where papel_id = "
                "(select id from papel where codigo = 'plataforma_edicao')"
            )
        )
        ids = [
            conexao.execute(
                text(
                    "insert into usuario (entra_object_id, email, nome, papel_id, ativo) "
                    "values (:o, :e, :n, "
                    "(select id from papel where codigo = 'plataforma_edicao'), true) "
                    "returning id"
                ),
                {
                    "o": f"oid-{uuid4().hex}",
                    "e": f"{n}.{marca}@aegea.com.br",
                    "n": f"Admin {n.upper()}",
                },
            ).scalar()
            for n in ("a", "b")
        ]
    try:
        yield ids
    finally:
        with engine.begin() as conexao:
            alvo = {"m": f"%{marca}%"}
            conexao.execute(
                text(
                    "delete from usuario_auditoria where usuario_id in "
                    "(select id from usuario where email like :m)"
                ),
                alvo,
            )
            conexao.execute(
                text(
                    "delete from acesso_log where usuario_id in "
                    "(select id from usuario where email like :m)"
                ),
                alvo,
            )
            conexao.execute(text("delete from usuario where email like :m"), alvo)
            conexao.execute(
                text(
                    "update usuario set ativo = true where papel_id = "
                    "(select id from papel where codigo = 'plataforma_edicao')"
                )
            )
        engine.dispose()


def test_dois_administradores_simultaneos_nao_zeram_a_plataforma(dois_administradores):
    a, b = dois_administradores
    sobraram, recusas = _em_paralelo([b, a], com_cadeado=True)

    assert sobraram >= 1, "a plataforma ficou sem quem administre acessos"
    assert len(recusas) == 1, f"uma das duas tinha de ser recusada: {recusas}"
    # Duas recusas legítimas, conforme quem chegou primeiro: ou a segunda não
    # pegou o cadeado, ou pegou depois do commit da primeira e aí a contagem
    # deu zero. As duas preservam a invariante.
    assert (
        "sem ninguém que administre acessos" in recusas[0]
        or "Outra alteração de acesso" in recusas[0]
    ), recusas[0]


def test_sem_o_cadeado_a_corrida_fura(dois_administradores):
    """A PROVA NEGATIVA. Sem o cadeado, o mesmo roteiro chega a zero.

    Se este teste parar de falhar-por-furar, é porque a serialização passou a
    vir de outro lugar — e aí o teste acima deixou de provar o que diz provar.
    """
    a, b = dois_administradores
    sobraram, _ = _em_paralelo([b, a], com_cadeado=False)

    assert sobraram == 0, (
        "sem cadeado a corrida deveria zerar os administradores; se não zerou, "
        "algo mais está serializando e o teste de cima virou decorativo"
    )


def test_o_caso_de_uso_real_nao_da_deadlock(dois_administradores):
    """O deadlock que o `try` existe para evitar — pelo caminho de verdade.

    O teste acima usa SQL cru e por isso não reproduzia o problema: faltava o
    carimbo de `ultimo_acesso_em` que `carregar()` faz em quem está pedindo.
    Esse carimbo é um `update`, e trava a linha de quem pede ANTES do cadeado.

    Com a versão que esperava, este roteiro dava `deadlock detected` e virava
    500. Com `pg_try_advisory_xact_lock`, quem perde a corrida recebe uma
    recusa que diz o que fazer.
    """
    import threading

    a, b = dois_administradores
    resultados: list[str] = []
    # As DUAS precisam ter carimbado antes de qualquer uma escrever — é essa a
    # condição da inversão. Sem a barreira, a segunda `carregar()` acontece
    # depois do commit da primeira e devolve `None`, e o roteiro nunca chega
    # perto do deadlock.
    ambas_carregaram = threading.Barrier(2, timeout=20)

    def desativar(alvo, quem):
        engine = create_engine(URL, pool_pre_ping=True)
        try:
            with Session(bind=engine) as propria:
                # `carregar()` é o que carimba `ultimo_acesso_em` e trava a
                # linha de quem pede. É a peça que faltava no teste anterior.
                solicitante = carregar(propria, quem)
                assert solicitante is not None
                ambas_carregaram.wait()
                administrar_acessos.definir_situacao(
                    propria, alvo=alvo, ativa=False, solicitante=solicitante
                )
                propria.commit()
                resultados.append("aplicou")
        except RegraViolada as erro:
            resultados.append(f"recusou: {erro}")
        except Exception as erro:  # noqa: BLE001
            resultados.append(f"QUEBROU: {type(erro).__name__}: {erro}")
        finally:
            engine.dispose()

    fios = [
        threading.Thread(target=desativar, args=(b, a)),
        threading.Thread(target=desativar, args=(a, b)),
    ]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=30)
        assert not f.is_alive(), "travou"

    quebrou = [r for r in resultados if r.startswith("QUEBROU")]
    assert not quebrou, f"erro não tratado (deadlock vira 500): {quebrou}"

    engine = create_engine(URL, pool_pre_ping=True)
    with engine.begin() as conexao:
        sobraram = conexao.execute(
            text(
                "select count(*) from usuario u join papel p on p.id = u.papel_id "
                "where u.ativo and p.ativo and p.administra_acessos"
            )
        ).scalar()
    engine.dispose()
    assert sobraram >= 1, f"ficou sem administrador; resultados: {resultados}"


def _dois_em_paralelo(acoes) -> list[str]:
    """Duas operações administrativas de verdade, uma contra a outra.

    Cada `acao` é `(quem, o_que)` e roda na sua conexão. A barreira garante que
    as DUAS passem por `carregar()` — que carimba `ultimo_acesso_em` e trava a
    linha de quem pede — antes de qualquer uma escrever. É essa ordem que cria
    a inversão; sem ela o roteiro nunca chega perto do deadlock.
    """
    import threading

    resultados: list[str] = []
    ambas_carregaram = threading.Barrier(len(acoes), timeout=20)

    def rodar(quem, o_que):
        engine = create_engine(URL, pool_pre_ping=True)
        try:
            with Session(bind=engine) as propria:
                solicitante = carregar(propria, quem)
                assert solicitante is not None
                # `flush` explícito: o carimbo de `ultimo_acesso_em` precisa ter
                # CHEGADO ao banco antes da barreira, senão a linha de quem pede
                # não está travada e o roteiro não reproduz a inversão. Sem
                # isto o teste passava até com a ordem errada — e um teste que
                # não distingue não vale nada.
                propria.flush()
                ambas_carregaram.wait()
                o_que(propria, solicitante)
                propria.commit()
                resultados.append("aplicou")
        except RegraViolada as erro:
            resultados.append(f"recusou: {erro}")
        except Exception as erro:  # noqa: BLE001
            resultados.append(f"QUEBROU: {type(erro).__name__}: {erro}")
        finally:
            engine.dispose()

    fios = [threading.Thread(target=rodar, args=a) for a in acoes]
    for f in fios:
        f.start()
    for f in fios:
        f.join(timeout=30)
        assert not f.is_alive(), "travou"
    return resultados


def _rebaixar(alvo):
    """Troca o papel do alvo para um que NÃO administra acessos."""

    def acao(sessao, solicitante):
        administrar_acessos.conceder(
            sessao,
            alvo=alvo,
            concessao=administrar_acessos.Concessao(
                papel="crm_leitura",
                acesso_irrestrito=True,
                externo=False,
                expira_em=None,
                frentes=(),
                unidades=(),
                versao_vista=None,
            ),
            solicitante=solicitante,
        )

    return acao


def _desativar(alvo):
    def acao(sessao, solicitante):
        administrar_acessos.definir_situacao(
            sessao, alvo=alvo, ativa=False, solicitante=solicitante
        )

    return acao


def _sobraram_administradores() -> int:
    engine = create_engine(URL, pool_pre_ping=True)
    with engine.begin() as conexao:
        n = conexao.execute(
            text(
                "select count(*) from usuario u join papel p on p.id = u.papel_id "
                "where u.ativo and p.ativo and p.administra_acessos"
            )
        ).scalar()
    engine.dispose()
    return n


def test_rebaixar_rebaixar_nao_da_deadlock(dois_administradores):
    """O roteiro que o Codex achou e os meus testes não cobriam.

    O deadlock aqui é ANTERIOR a este trabalho: `conceder_acesso` faz
    `for update` no alvo desde 0006, e `carregar()` já travou a linha de quem
    pede. Dois administradores se rebaixando fecham o ciclo sem o cadeado
    participar — foi por isso que ele precisou vir ANTES do `for update`.

    O QUE ESTE TESTE PROVA, E O QUE NÃO PROVA
    -----------------------------------------
    Ele prova o DESFECHO: nenhum erro sem tratamento chega a quem usa, e sobra
    administrador. É um guarda de regressão útil.

    Ele NÃO é prova negativa do deadlock. Verificado: com a ordem antiga
    instalada no banco — cadeado depois do `for update` —, este mesmo teste
    passa. O entrelaçamento que produz o ciclo não acontece de forma confiável
    neste arranjo de threads, ainda que as duas transações comprovadamente
    segurem as próprias linhas na barreira (medido com `for update nowait` de
    uma terceira conexão).

    Quem reproduziu o deadlock foi a revisão externa, com um arranjo próprio.
    Registrar isso importa: um teste que se acredita discriminante e não é vale
    menos que teste nenhum, porque compra confiança que não existe.
    """
    a, b = dois_administradores
    resultados = _dois_em_paralelo([(a, _rebaixar(b)), (b, _rebaixar(a))])

    quebrou = [r for r in resultados if r.startswith("QUEBROU")]
    assert not quebrou, f"deadlock ou erro não tratado: {quebrou}"
    assert _sobraram_administradores() >= 1, resultados


def test_misto_desativar_contra_rebaixar_nao_zera(dois_administradores):
    """Códigos DIFERENTES disputando o mesmo cadeado.

    Um caminho é Python (`definir_situacao`), o outro é a função do banco
    (`conceder_acesso`). Se cada um pegasse um cadeado diferente — ou um deles
    não pegasse nenhum — a invariante cairia justamente aqui.
    """
    a, b = dois_administradores
    resultados = _dois_em_paralelo([(a, _desativar(b)), (b, _rebaixar(a))])

    quebrou = [r for r in resultados if r.startswith("QUEBROU")]
    assert not quebrou, f"deadlock ou erro não tratado: {quebrou}"
    assert _sobraram_administradores() >= 1, resultados
