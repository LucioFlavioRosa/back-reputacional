"""Mover um contato para outra instituição — a mudança de casa.

PEDIDO DO DONO DO PRODUTO (11/10/2026): "siga com mover contato", depois de eu
relatar que o modal da fila não oferece o campo e que um contato nascido na casa
errada só se consertava apagando e recriando.

POR QUE ISTO NÃO É EDITAR UM CAMPO. A `0002` cria
`unique (nome_normalizado, instituicao_id)` com o comentário "mesmo nome em
instituições diferentes são pessoas diferentes": a instituição não é um atributo
do contato, é parte da IDENTIDADE dele neste modelo. Trocá-la num `<select>` ao
lado do cargo ofereceria, com o mesmo peso de corrigir um e-mail, uma afirmação
de outra natureza.

E O CASO É REAL: Nikolau Muller apareceu em JGP Gestão e Leto Capital na mesma
planilha de RI, e a leitura mais provável é que ele mudou de casa.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.banco.tabelas_stakeholders import Instituicao, Interlocutor
from app.dominio.texto import normalizar
from main import app
from tests.test_e2e_postgres import URL
from tests.test_importacoes_api import _cliente

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


@pytest.fixture
def cliente_admin(sessao):
    try:
        yield _cliente(sessao, "plataforma_edicao")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_admin(sessao):
    """`crm_edicao` abre o portal do CRM e NÃO administra cadastros — o
    contrapeso exato da guarda, e não um perfil sem acesso a nada."""
    try:
        yield _cliente(sessao, "crm_edicao")
    finally:
        app.dependency_overrides.clear()


def _casa(sessao, nome: str, ativo: bool = True) -> Instituicao:
    registro = Instituicao(
        nome=nome,
        nome_normalizado=normalizar(nome),
        tipo="investidor",
        uf="SP",
        ativo=ativo,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _contato(sessao, nome: str, casa: Instituicao | None) -> Interlocutor:
    registro = Interlocutor(
        nome=nome,
        nome_normalizado=normalizar(nome),
        instituicao_id=casa.id if casa else None,
        cargo="Diretor de RI",
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def test_o_contato_MUDA_de_casa(cliente_admin, sessao):
    """O gesto inteiro, e o caso real: Nikolau Muller mudou da JGP para a Leto."""
    jgp = _casa(sessao, "JGP Gestao Zz01")
    leto = _casa(sessao, "Leto Capital Zz01")
    nikolau = _contato(sessao, "Nikolau Muller Zz01", jgp)

    resposta = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["de"] == "JGP Gestao Zz01"
    assert corpo["para"] == "Leto Capital Zz01"

    sessao.refresh(nikolau)
    assert nikolau.instituicao_id == leto.id
    #: E O CARGO NÃO SE PERDE: a mudança mexe numa coisa só.
    assert nikolau.cargo == "Diretor de RI"


def test_as_AGENDAS_ficam_na_casa_antiga(cliente_admin, sessao):
    """O HISTÓRICO NÃO SE MEXE, e é o que eu fui conferir antes de escrever.

    `interacao.instituicao_id` é coluna PRÓPRIA da agenda, separada de
    `interacao.interlocutor_id`. Mover o contato NÃO reescreve a casa de nenhuma
    agenda passada: a reunião continua registrada como tendo sido com a JGP,
    porque era.

    E ISSO É O CERTO. Quem trocou de emprego participou daquelas reuniões pela
    casa antiga; reescrever isso apagaria o fato. A mudança diz "de hoje em
    diante ela fala pela Leto", e as agendas antigas são a prova de que a mudança
    aconteceu.

    A CONTAGEM VOLTA NA RESPOSTA por isso: com zero agendas, a leitura provável é
    "eu errei a instituição no cadastro"; com trinta, é "mudou de casa". Quem
    confirma precisa dessa frase.
    """
    from datetime import date

    jgp = _casa(sessao, "JGP Gestao Zz02")
    leto = _casa(sessao, "Leto Capital Zz02")
    nikolau = _contato(sessao, "Nikolau Muller Zz02", jgp)

    criada = cliente_admin.post(
        "/api/interacoes",
        json={
            "data_interacao": str(date(2026, 9, 25)),
            "instituicao_id": str(jgp.id),
            "interlocutor_id": str(nikolau.id),
            "uf": "SP",
        },
    )
    assert criada.status_code == 201, criada.text

    corpo = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    ).json()

    #: A RESPOSTA CONTA O QUE FICOU ATRÁS.
    assert corpo["agendas_que_ficam"] == 1

    #: E A AGENDA CONTINUA NA JGP.
    da_agenda = cliente_admin.get(f"/api/interacoes/{criada.json()['id']}").json()
    assert da_agenda["instituicao_id"] == str(jgp.id)


def test_o_nome_JA_NA_CASA_DE_DESTINO_e_recusado(cliente_admin, sessao):
    """Mover um para cima do outro não é mudança de casa, é FUSÃO.

    O índice único da `0002` é `(nome_normalizado, instituicao_id)` e NÃO é
    parcial em `ativo`: um contato desativado continua ocupando o par. Sem a
    conferência o `flush` estoura em `IntegrityError` — 500 para quem clicou, e
    sem dizer que já existe alguém com aquele nome lá.

    E A RECUSA APONTA PARA A FILA DE DUPLICADOS, porque é a pergunta certa: se há
    um "Nikolau" na Leto e outro na JGP, fundir é decisão de quem conhece as duas
    linhas — e o lote de enquadramento já recusa pelo mesmo motivo.
    """
    jgp = _casa(sessao, "JGP Gestao Zz03")
    leto = _casa(sessao, "Leto Capital Zz03")
    daqui = _contato(sessao, "Nikolau Muller Zz03", jgp)
    _contato(sessao, "Nikolau Muller Zz03", leto)

    resposta = cliente_admin.post(
        f"/api/interlocutores/{daqui.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    )
    assert resposta.status_code == 422, resposta.text
    assert "Possíveis duplicados" in resposta.text

    #: NADA MUDOU.
    sessao.refresh(daqui)
    assert daqui.instituicao_id == jgp.id


def test_a_casa_DESATIVADA_e_recusada(cliente_admin, sessao):
    """A FK aceitaria, e o contato ficaria invisível.

    A listagem padrão de contatos aplica os DOIS níveis — a pessoa ativa E a
    instituição ativa —, então mover alguém para uma casa desativada é esconder a
    pessoa sem dizer isso.
    """
    jgp = _casa(sessao, "JGP Gestao Zz04")
    fechada = _casa(sessao, "Casa Fechada Zz04", ativo=False)
    nikolau = _contato(sessao, "Nikolau Muller Zz04", jgp)

    resposta = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(fechada.id)},
    )
    assert resposta.status_code == 422, resposta.text
    assert "desativada" in resposta.text
    sessao.refresh(nikolau)
    assert nikolau.instituicao_id == jgp.id


def test_mover_para_a_MESMA_casa_e_recusado(cliente_admin, sessao):
    """Não é erro de dado, é a pessoa não ter percebido que já estava lá — e
    responder 200 a isso faria a tela anunciar uma mudança que não houve."""
    jgp = _casa(sessao, "JGP Gestao Zz05")
    nikolau = _contato(sessao, "Nikolau Muller Zz05", jgp)

    resposta = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(jgp.id)},
    )
    assert resposta.status_code == 422, resposta.text
    assert "já fala por" in resposta.text


def test_o_contato_SEM_CASA_pode_ganhar_uma(cliente_admin, sessao):
    """`de` nulo é o estado de quem a planilha criou sem instituição na linha —
    e para esse a "mudança" é a primeira casa, não uma troca."""
    leto = _casa(sessao, "Leto Capital Zz06")
    solto = _contato(sessao, "Contato Solto Zz06", None)

    corpo = cliente_admin.post(
        f"/api/interlocutores/{solto.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    ).json()

    assert corpo["de"] is None
    assert corpo["para"] == "Leto Capital Zz06"
    assert corpo["agendas_que_ficam"] == 0


def test_a_casa_que_NAO_EXISTE_da_404(cliente_admin, sessao):
    jgp = _casa(sessao, "JGP Gestao Zz07")
    nikolau = _contato(sessao, "Nikolau Muller Zz07", jgp)

    assert (
        cliente_admin.post(
            f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
            json={"instituicao_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )


def test_quem_NAO_administra_cadastros_nao_move(cliente_sem_admin, sessao):
    """Mover um contato muda a quem ele pertence, e nesse modelo a instituição é
    parte da identidade dele — é escrita de administração, não de registro."""
    assert (
        cliente_sem_admin.post(
            f"/api/interlocutores/{uuid.uuid4()}/mudanca-de-casa",
            json={"instituicao_id": str(uuid.uuid4())},
        ).status_code
        == 403
    )


def test_a_mudanca_TRAVA_a_linha_que_vai_mexer():
    """Duas pessoas movendo o mesmo contato para casas diferentes.

    Lendo antes de qualquer commit, as duas responderiam 200 e a última gravação
    venceria em silêncio — o mesmo lost update que o lote de enquadramento teve.
    A âncora é a fonte, pela mesma razão de lá: a fixture roda tudo numa
    transação que termina em rollback, e duas sessões não se veem.
    """
    import inspect

    from app.casos_de_uso import mudar_a_casa

    fonte = inspect.getsource(mudar_a_casa.mudar)
    assert "with_for_update()" in fonte, (
        "a leitura do contato precisa travar a linha: sem isso, duas mudanças "
        "simultâneas se sobrescrevem"
    )


# -- os quatro achados da revisão ---------------------------------------------


def test_a_contagem_e_SO_das_agendas_da_CASA_ANTIGA(cliente_admin, sessao):
    """ACHADO DE REVISÃO COM SEVERIDADE MÉDIA: o nome não entregava o que promete.

    `agendas_que_ficam` contava TODAS as agendas do contato — inclusive as de uma
    terceira instituição e as da própria casa de DESTINO. O número inflava a
    frase da confirmação, que é a única razão de ele existir.

    E UMA TELA QUE CONTA ERRADO NUMA CONFIRMAÇÃO é pior que uma que não conta:
    "7 agendas continuam registradas em XP Asset" é o que distingue "mudou de
    casa" de "errei a instituição", e quem lê decide com base nela.

    O ARRANJO DESTE TESTE: uma agenda na casa antiga, uma na de destino, e uma
    numa terceira. Só a primeira conta.
    """
    from datetime import date

    jgp = _casa(sessao, "JGP Gestao Zz10")
    leto = _casa(sessao, "Leto Capital Zz10")
    terceira = _casa(sessao, "Outra Casa Zz10")
    nikolau = _contato(sessao, "Nikolau Muller Zz10", jgp)

    for casa in (jgp, leto, terceira):
        criada = cliente_admin.post(
            "/api/interacoes",
            json={
                "data_interacao": str(date(2026, 9, 25)),
                "instituicao_id": str(casa.id),
                "interlocutor_id": str(nikolau.id),
                "uf": "SP",
            },
        )
        assert criada.status_code == 201, criada.text

    corpo = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    ).json()

    #: UMA, e não três: só a da JGP fica atrás.
    assert corpo["agendas_que_ficam"] == 1, corpo


def test_a_contagem_pega_quem_participou_como_ACOMPANHANTE(cliente_admin, sessao):
    """Os DOIS lugares onde um contato participa.

    `interacao.interlocutor_id` guarda o principal — 67 usos em filtros e
    relatórios dependem dele — e `interacao_interlocutor` guarda os demais.
    Contar só o primeiro diria "zero agendas" para quem participou de trinta como
    acompanhante, e a frase da confirmação mandaria a pessoa concluir que foi
    erro de cadastro.
    """
    from datetime import date

    jgp = _casa(sessao, "JGP Gestao Zz11")
    leto = _casa(sessao, "Leto Capital Zz11")
    principal = _contato(sessao, "Quem Conduz Zz11", jgp)
    acompanhante = _contato(sessao, "Quem Acompanha Zz11", jgp)

    criada = cliente_admin.post(
        "/api/interacoes",
        json={
            "data_interacao": str(date(2026, 9, 25)),
            "instituicao_id": str(jgp.id),
            "interlocutor_id": str(principal.id),
            #: `outra_parte`, e não uma lista de ids: cada participante leva a
            #: `presenca` e a marca de `principal` — o esquema é
            #: `ParticipanteDaOutraParteEntrada`.
            "outra_parte": [{"interlocutor_id": str(acompanhante.id)}],
            "uf": "SP",
        },
    )
    assert criada.status_code == 201, criada.text

    corpo = cliente_admin.post(
        f"/api/interlocutores/{acompanhante.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    ).json()

    assert corpo["agendas_que_ficam"] == 1, corpo


def test_mover_ENCERRA_a_pendencia_da_fila(cliente_admin, sessao):
    """ACHADO DE REVISÃO, e é um erro de raciocínio meu.

    Eu havia decidido não mexer na pendência porque "uma mudança deliberada é uma
    decisão, não uma dúvida". O outro lado é o que importa: "não precisa marcar
    dúvida nova; precisa ENCERRAR a dúvida antiga".

    O motivo que a fila mostrava diz literalmente "confirme se são a mesma
    pessoa, SE ELA MUDOU DE CASA, ou se são homônimas". Mover É a resposta — e
    deixar na fila faria a pergunta voltar amanhã, com a resposta já dada no
    dado.
    """
    jgp = _casa(sessao, "JGP Gestao Zz12")
    leto = _casa(sessao, "Leto Capital Zz12")
    nikolau = _contato(sessao, "Nikolau Muller Zz12", jgp)
    nikolau.pendente_de_revisao = True
    nikolau.motivo_da_revisao = (
        "Apareceu em 2 instituições na mesma planilha — confirme se são a mesma "
        "pessoa, se ela mudou de casa, ou se são homônimas."
    )
    sessao.flush()

    corpo = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    ).json()

    assert corpo["consolidou"] is True
    sessao.refresh(nikolau)
    assert nikolau.pendente_de_revisao is False
    #: O MOTIVO SAI COM A PENDÊNCIA: ele era a pergunta, e ela foi respondida.
    assert nikolau.motivo_da_revisao is None


def test_mover_quem_NAO_estava_na_fila_diz_que_nao_consolidou(cliente_admin, sessao):
    """O outro lado do booleano: a tela não deve anunciar o que não houve."""
    jgp = _casa(sessao, "JGP Gestao Zz13")
    leto = _casa(sessao, "Leto Capital Zz13")
    nikolau = _contato(sessao, "Nikolau Muller Zz13", jgp)
    assert nikolau.pendente_de_revisao is False

    corpo = cliente_admin.post(
        f"/api/interlocutores/{nikolau.id}/mudanca-de-casa",
        json={"instituicao_id": str(leto.id)},
    ).json()

    assert corpo["consolidou"] is False


def test_a_mutacao_acontece_DENTRO_do_savepoint():
    """ACHADO DE REVISÃO COM SEVERIDADE MÉDIA, sobre o meu conserto anterior.

    Eu havia posto as três atribuições ANTES de chamar `gravar`, e
    `Session.begin_nested()` FAZ FLUSH DO QUE ESTÁ PENDENTE AO ENTRAR no bloco: o
    `UPDATE` saía antes de o SAVEPOINT existir. A colisão continuava virando
    `RegraViolada` — o `try` do `gravar` envolve a entrada —, mas a sessão ficava
    marcada para rollback, e qualquer leitura depois dali estouraria
    `PendingRollbackError`. O savepoint não isolava nada; só parecia.

    E EU HAVIA LIDO A LIÇÃO: `app/banco/gravar.py` diz em voz alta que "o `add`
    precisa ficar DENTRO do savepoint". Citei a frase no comentário e não a
    apliquei — `gravar` só cumpre a promessa para objeto NOVO, porque aí o `add`
    é dele; num `UPDATE` de objeto já sujo ele não tem como pegar a mutação.

    == POR QUE ESTA ÂNCORA É POR `ast`, E NÃO POR TEXTO ==

    A primeira versão cobrava a string `gravar(` e a AUSÊNCIA de
    `sessao.flush()`. A revisão apontou que ela "prova menos do que diz": não
    enxerga o flush IMPLÍCITO do `begin_nested`, e barraria um flush legítimo
    acrescentado depois por outra razão.

    A propriedade que importa é ESTRUTURAL — "as atribuições a `contato` estão
    dentro do `with begin_nested`" —, e `ast` afirma exatamente isso. Provar pelo
    comportamento exigiria a corrida: duas conexões e um commit no meio, e a
    fixture roda tudo numa transação que termina em rollback.
    """
    import ast
    import inspect
    import textwrap

    from app.casos_de_uso import mudar_a_casa

    arvore = ast.parse(textwrap.dedent(inspect.getsource(mudar_a_casa.mudar)))

    #: O `with` cujo contexto é `sessao.begin_nested()`.
    blocos = [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin_nested"
            for item in no.items
        )
    ]
    assert len(blocos) == 1, f"esperava um savepoint, achei {len(blocos)}"

    #: AS TRÊS ATRIBUIÇÕES QUE GRAVAM, todas dentro dele.
    dentro = {
        alvo.attr
        for no in ast.walk(blocos[0])
        if isinstance(no, ast.Assign)
        for alvo in no.targets
        if isinstance(alvo, ast.Attribute)
    }
    assert {"instituicao_id", "pendente_de_revisao", "motivo_da_revisao"} <= dentro, (
        "a mutação precisa estar DENTRO do savepoint: fora dele, o "
        f"`begin_nested` a descarrega antes de o SAVEPOINT existir. Achei {dentro}"
    )

    #: E NENHUMA DELAS FORA. `ast.walk` da função inteira menos as de dentro.
    todas = {
        alvo.attr
        for no in ast.walk(arvore)
        if isinstance(no, ast.Assign)
        for alvo in no.targets
        if isinstance(alvo, ast.Attribute)
    }
    assert todas == dentro, f"gravação fora do savepoint: {todas - dentro}"


def test_o_destino_e_TRAVADO_junto_com_o_contato():
    """ACHADO DE REVISÃO (BAIXA): o destino era validado ativo SEM lock.

    Uma edição concorrente podia DESATIVAR a casa depois da conferência e antes
    do commit, deixando o contato numa instituição inativa — exatamente o que a
    recusa por casa desativada existe para impedir.

    E A ORDEM É FIXA: contato primeiro, casa depois, em todo caminho deste caso
    de uso. Duas chamadas simultâneas esperam uma à outra, nunca se cruzam.
    """
    import inspect

    from app.casos_de_uso import mudar_a_casa

    fonte = inspect.getsource(mudar_a_casa.mudar)
    assert fonte.count("with_for_update()") == 2, (
        "o contato E o destino precisam ser travados: "
        f"achei {fonte.count('with_for_update()')} travas"
    )
    #: E O CONTATO VEM PRIMEIRO, que é a ordem que evita deadlock.
    assert fonte.index("Interlocutor.id == interlocutor_id") < fonte.index(
        "Instituicao.id == instituicao_id"
    )
