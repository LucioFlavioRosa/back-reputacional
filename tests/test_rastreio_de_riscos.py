"""O rastreio de risco, do banco: a série, a matriz e o que NÃO conta.

O QUE O DONO DO PRODUTO PEDIU: uma aba que mostre os riscos dos temas citados no
CRM, na Clipei (nos dois recortes), na Bites e na Approach quando ela subir.

O CAMINHO É UM SÓ — `tema_risco` liga o tema (N3) aos riscos da matriz
corporativa —, e é por isso que não há lógica por fornecedor: a fonte é uma
dimensão de filtro. O que estes testes protegem são as decisões que não se leem
no SQL:

* INCIDENTE é fato NEGATIVO: menção `neg`, ou agenda de clima `tenso`;
* o CRM entra pelo CLIMA, porque `interacao` não tem sentimento;
* agenda invisível ou arquivada NÃO é incidente;
* a matriz traz os 32 riscos, inclusive os SEM incidente;
* um tema que toca dois riscos conta o incidente nos dois, e a série conta a
  menção UMA vez;
* e a janela da tela não mexe na referência de 100 pontos.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.repositorio_riscos import (
    FiltroDeRisco,
    matriz_de_risco,
    serie_do_indice,
)
from app.banco.tabelas_catalogo import (
    Clima,
    Frente,
    Risco,
    RiskCluster,
    Tema,
    TemaRisco,
)
from app.banco.tabelas_interacoes import InteracaoRegistro, InteracaoTema
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.dominio.identidade import Escopo
from app.dominio.riscos import PESO_DA_SEVERIDADE
from tests.apoio_da_fonte_interna import ligar_o_crm
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: O ESCOPO IRRESTRITO, que é o da maioria dos papéis. O restrito tem teste
#: próprio: `test_o_ESCOPO_DO_USUARIO_esconde_a_agenda`.
TUDO = Escopo(irrestrito=True)


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
def bites(sessao) -> ScoreFonte:
    return sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))


@pytest.fixture
def com_risco(sessao) -> tuple[Tema, Risco]:
    """Um tema ativo ligado a um risco ativo, como o cadastro os tem."""
    par = sessao.execute(
        select(Tema, Risco)
        .join(TemaRisco, TemaRisco.tema_id == Tema.id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        .where(Tema.ativo.is_(True), Risco.ativo.is_(True))
        .order_by(Tema.id)
        .limit(1)
    ).first()
    assert par is not None, "o cadastro de teste precisa de um tema ligado a risco"
    return par


def _mencao(sessao, fonte: ScoreFonte, tema: Tema, sentimento: str, dia: int = 3) -> Mencao:
    registro = Mencao(
        fonte_id=fonte.id,
        mes=date(2026, 8, 1),
        data=date(2026, 8, dia),
        sentimento=sentimento,
        veiculo="Jornal do Risco",
        titulo_texto="Falta de água no bairro",
        tema_id=tema.id,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _agenda(sessao, tema: Tema, clima: str, **extra) -> InteracaoRegistro:
    """Uma agenda do CRM com o que o banco exige, e nada além.

    `interacao` tem `not null` em frente, data, instituição, uf, status, fonte,
    visível e criado_por — conferido em `information_schema`, e não descoberto
    um por um a cada falha.
    """
    from app.banco.tabelas_acesso import Usuario
    from app.banco.tabelas_catalogo import Frente, Status
    from app.banco.tabelas_stakeholders import Instituicao
    from app.dominio.texto import normalizar

    do_clima = sessao.scalar(select(Clima).where(Clima.codigo == clima))
    assert do_clima is not None, clima
    frente = sessao.scalar(select(Frente).order_by(Frente.id).limit(1))
    status = sessao.scalar(select(Status).order_by(Status.id).limit(1))
    assert frente is not None and status is not None, (
        "o cadastro de teste precisa de frente e status"
    )
    #: O BANCO DE TESTE NASCE SEM USUÁRIO — ele vem do provisionamento, não das
    #: migrations —, e `criado_por` é obrigatório. Um por sessão basta.
    quem = sessao.scalar(select(Usuario).order_by(Usuario.email).limit(1))
    if quem is None:
        #: `entra_object_id` É `not null` DESDE A 0096: usuário que não
        #: autentica não existe na plataforma. O check
        #: `usuario_autentica_de_algum_jeito`, que aceitava "senha OU Entra ID",
        #: saiu junto com a senha — agora há um caminho só, e ele é obrigatório.
        quem = Usuario(
            email="risco.teste@aegea.com.br",
            nome="Teste do Risco",
            entra_object_id="mock-risco-teste",
        )
        sessao.add(quem)
        sessao.flush()

    #: NOME ÚNICO POR AGENDA: o índice de `instituicao` é
    #: `(nome_normalizado, tipo)`, e o mesmo teste cria duas agendas.
    import uuid as _uuid

    nome = f"Entidade do Risco zz60 {_uuid.uuid4().hex[:8]}"
    com_quem = Instituicao(
        nome=nome, nome_normalizado=normalizar(nome), tipo="entidade"
    )
    sessao.add(com_quem)
    sessao.flush()

    registro = InteracaoRegistro(
        frente_id=frente.id,
        instituicao_id=com_quem.id,
        data_interacao=date(2026, 8, 12),
        uf="RS",
        status_id=status.id,
        fonte="cadastro_manual",
        clima_id=do_clima.id,
        pauta="Reunião sobre o desabastecimento",
        criado_por=quem.id,
        **extra,
    )
    sessao.add(registro)
    sessao.flush()
    sessao.add(InteracaoTema(interacao_id=registro.id, tema_id=tema.id))
    sessao.flush()
    return registro


def _de_agosto(serie) -> object | None:
    return next((mes for mes in serie if mes.mes == "2026-08"), None)


# -- o que conta como incidente --------------------------------------------------


def test_a_mencao_NEGATIVA_de_tema_com_risco_e_incidente(sessao, bites, com_risco):
    tema, _risco = com_risco
    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    quantos_antes = antes.incidentes if antes else 0

    _mencao(sessao, bites, tema, "neg")

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert agora.incidentes == quantos_antes + 1


def test_a_mencao_POSITIVA_nao_e_incidente(sessao, bites, com_risco):
    """"Sem incidente" é a informação mais útil da matriz.

    Contando toda menção, um risco muito falado de forma positiva apareceria
    como o mais quente da tela.
    """
    tema, _risco = com_risco
    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    quantos_antes = antes.incidentes if antes else 0

    _mencao(sessao, bites, tema, "pos")
    _mencao(sessao, bites, tema, "neu", dia=4)

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    quantos_agora = agora.incidentes if agora else 0
    assert quantos_agora == quantos_antes


def test_a_AGENDA_NAO_conta_como_incidente_por_padrao(sessao, bites, com_risco):
    """A regra de hoje: a agenda do CRM não é incidente.

    Sem `ligar_o_crm`, de propósito — a diferença entre este teste e o de baixo
    é a política em `dominio/fontes_do_score`.

    A agenda é semeada mesmo assim, senão "não contou" poderia ser "não havia".
    E a menção vai junto para o mês EXISTIR na série: sem ela o mês não produz
    linha, e a asserção passaria com `agora is None` — o que também passaria se
    a série inteira tivesse quebrado.
    """
    tema, _risco = com_risco
    _mencao(sessao, bites, tema, "neg", dia=4)
    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert antes is not None, "a menção semeada tinha de produzir a linha de agosto"
    quantos_antes = antes.incidentes

    _agenda(sessao, tema, "tenso")

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert agora is not None
    assert agora.incidentes == quantos_antes
    #: E o CRM não aparece entre as fontes do mês: a tela não nomeia uma
    #: procedência que não trouxe nada. A Bites aparece, porque trouxe.
    assert "crm" not in agora.fontes
    assert "bites" in agora.fontes
def test_a_FONTE_INTERNA_nao_e_de_lente_nenhuma(sessao):
    """O cadastro depois da `0114`: nenhuma lente se relaciona com o CRM.

    A POLÍTICA É METADE DA TRANCA; esta é a outra. Enquanto a fonte interna
    apontava `lente_id = institucional`, religá-la (`ativo = true`, um `update`
    de uma coluna) devolvia as agendas ao índice daquela lente, e o Risk
    Tracking as atribuía a ela. Sem lente, não há a que devolver.
    """
    internas_com_lente = sessao.execute(
        select(ScoreFonte.codigo, ScoreFonte.lente_id)
        .where(ScoreFonte.interna.is_(True), ScoreFonte.lente_id.is_not(None))
    ).all()

    assert internas_com_lente == [], (
        f"fonte interna voltou a ter lente: {internas_com_lente}. "
        "As agendas do CRM ficam no CRM."
    )


def test_a_AGENDA_de_clima_negativo_e_incidente(sessao, com_risco, monkeypatch):
    """O CRM entra pelo clima: `interacao` não tem coluna de sentimento.

    Com o CRM ligado só aqui. O mecanismo segue medido porque é ele que precisa
    estar correto no dia em que o CRM voltar; o comportamento padrão tem teste
    próprio.
    """
    ligar_o_crm(sessao, monkeypatch)
    tema, _risco = com_risco
    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    quantos_antes = antes.incidentes if antes else 0

    _agenda(sessao, tema, "tenso")

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert agora.incidentes == quantos_antes + 1
    assert "crm" in agora.fontes
def test_a_AGENDA_de_clima_positivo_ou_neutro_nao_e_incidente(
    sessao, bites, com_risco, monkeypatch
):
    """O clima separa a agenda-incidente da agenda comum.

    Com o CRM ligado, senão nenhuma agenda contaria e "positivo não conta"
    seria indistinguível de "negativo também não".

    A agenda tensa é o CONTROLE: ela precisa somar 1, senão a asserção de baixo
    volta a ser vácuo — um mecanismo quebrado por inteiro também faria "não
    contou" passar.
    """
    ligar_o_crm(sessao, monkeypatch)
    tema, _risco = com_risco
    _mencao(sessao, bites, tema, "neg", dia=4)
    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert antes is not None, "a menção semeada tinha de produzir a linha de agosto"

    _agenda(sessao, tema, "tenso")
    com_tenso = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert com_tenso.incidentes == antes.incidentes + 1, "o clima tenso é incidente"

    _agenda(sessao, tema, "propositivo")
    _agenda(sessao, tema, "neutro")

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert agora.incidentes == com_tenso.incidentes
def test_a_AGENDA_INVISIVEL_ou_ARQUIVADA_nao_e_incidente(
    sessao, bites, com_risco, monkeypatch
):
    """A mesma regra de visibilidade do resto da plataforma.

    Uma tela de risco que conte agenda arquivada mostra como incidente o que
    alguém retirou do registro.

    Com o CRM ligado, e a agenda visível é o controle: ela soma 1, as duas
    escondidas não somam mais nada.
    """
    from datetime import datetime

    tema, _risco = com_risco
    ligar_o_crm(sessao, monkeypatch)
    _mencao(sessao, bites, tema, "neg", dia=4)
    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert antes is not None, "a menção semeada tinha de produzir a linha de agosto"

    _agenda(sessao, tema, "tenso")
    _agenda(sessao, tema, "tenso", visivel=False)
    _agenda(sessao, tema, "tenso", arquivado_em=datetime(2026, 9, 1))

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    #: Três agendas semeadas, um incidente: só a visível e não arquivada conta.
    assert agora.incidentes == antes.incidentes + 1
# -- a matriz --------------------------------------------------------------------


def test_a_matriz_traz_TODOS_os_riscos_inclusive_os_SEM_incidente(sessao):
    matriz = matriz_de_risco(sessao, FiltroDeRisco(), TUDO)

    #: TODOS, e o número vem do CADASTRO: achado de revisão — a versão anterior
    #: conferia que UM risco estava lá, e uma implementação que devolvesse um
    #: subconjunto passaria.
    from sqlalchemy import func as _func

    quantos_no_cadastro = sessao.scalar(
        select(_func.count())
        .select_from(Risco)
        .join(RiskCluster, RiskCluster.id == Risco.risk_cluster_id)
        .where(Risco.ativo.is_(True), RiskCluster.ativo.is_(True))
    )
    assert len(matriz) == quantos_no_cadastro
    #: E O SILÊNCIO APARECE: há risco com zero incidente na matriz.
    assert any(linha.incidentes == 0 for linha in matriz)


def test_a_matriz_separa_MENCAO_de_AGENDA(sessao, bites, com_risco, monkeypatch):
    """Uma menção e uma reunião não são a mesma coisa, e a tela diz qual é qual.

    COM O CRM LIGADO SÓ AQUI — ver o teste acima: o que se prova é que a matriz
    SABE separar as duas, e isso tem de continuar verdade.
    """
    ligar_o_crm(sessao, monkeypatch)
    tema, risco = com_risco
    _mencao(sessao, bites, tema, "neg")
    _agenda(sessao, tema, "tenso")

    matriz = matriz_de_risco(sessao, FiltroDeRisco(), TUDO)
    linha = next(celula for celula in matriz if celula.codigo == risco.codigo)

    assert linha.mencoes >= 1
    assert linha.agendas >= 1
    assert linha.incidentes == linha.mencoes + linha.agendas


def test_o_TEMA_QUE_TOCA_DOIS_RISCOS_conta_nos_dois_e_a_serie_conta_UMA_vez(
    sessao, bites, com_risco
):
    """A diferença entre a matriz e a série, que é fácil de errar.

    A MATRIZ conta pares (incidente, risco): o incidente de um tema que toca
    dois riscos aparece nos dois, e é isso que "este incidente toca estes
    riscos" quer dizer. A SÉRIE conta incidentes: a mesma menção não pode valer
    dois, senão o índice dobra para quem tem tema mais conectado.

    O SEGUNDO VÍNCULO É CRIADO AQUI. O banco de teste nasce das migrations, e os
    104 temas da taxonomia entraram por importação — `tema_risco` ali é esparso.
    Este teste pulava por isso, e teste pulado não protege nada.
    """
    tema, primeiro = com_risco
    segundo = sessao.scalar(
        select(Risco)
        .where(Risco.ativo.is_(True), Risco.id != primeiro.id)
        .order_by(Risco.id)
        .limit(1)
    )
    assert segundo is not None, "o cadastro de teste precisa de dois riscos"
    ja_ligados = set(
        sessao.scalars(select(TemaRisco.risco_id).where(TemaRisco.tema_id == tema.id))
    )
    if segundo.id not in ja_ligados:
        sessao.add(TemaRisco(tema_id=tema.id, risco_id=segundo.id))
        sessao.flush()

    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    quantos_antes = antes.incidentes if antes else 0
    de_antes = {
        linha.codigo: linha.mencoes for linha in matriz_de_risco(sessao, FiltroDeRisco(), TUDO)
    }

    _mencao(sessao, bites, tema, "neg")

    #: A SÉRIE CONTA UMA.
    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert agora.incidentes == quantos_antes + 1

    #: A MATRIZ CONTA NOS DOIS.
    de_agora = {
        linha.codigo: linha.mencoes for linha in matriz_de_risco(sessao, FiltroDeRisco(), TUDO)
    }
    assert de_agora[primeiro.codigo] == de_antes.get(primeiro.codigo, 0) + 1
    assert de_agora[segundo.codigo] == de_antes.get(segundo.codigo, 0) + 1


# -- a janela e a referência -----------------------------------------------------


def test_a_JANELA_nao_mexe_na_referencia_de_cem_pontos(sessao, bites, com_risco):
    """O índice de um mês não pode mudar com o período que a pessoa escolhe.

    Se a janela entrasse no cálculo da referência, agosto valeria 100 numa
    janela que termina em agosto e 40 numa que vai até dezembro — e o número
    deixaria de dizer algo sobre o mês.
    """
    tema, _risco = com_risco
    _mencao(sessao, bites, tema, "neg")

    _serie_inteira, referencia_inteira, _pico = serie_do_indice(sessao, FiltroDeRisco(), TUDO)
    _serie_curta, referencia_curta, _pico_curto = serie_do_indice(
        sessao, FiltroDeRisco(de=date(2026, 8, 1), ate=date(2026, 8, 1)), TUDO
    )

    assert referencia_curta == referencia_inteira


def test_o_FILTRO_DE_FONTE_tira_o_CRM_quando_pede_so_uma_fonte(
    sessao, bites, com_risco, monkeypatch
):
    """O filtro por fonte vale para a fonte interna também.

    Com o CRM ligado: sem filtro ele entra (o controle), e é removido quando o
    filtro seleciona apenas a Bites (a regra). Com a política de hoje o CRM
    sai de qualquer jeito, e o filtro não seria exercido.
    """
    ligar_o_crm(sessao, monkeypatch)
    tema, _risco = com_risco
    _agenda(sessao, tema, "tenso")
    #: A menção da Bites garante que agosto existe na série.
    _mencao(sessao, bites, tema, "neg")

    tudo = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    assert tudo is not None
    assert "crm" in tudo.fontes, "sem filtro, a agenda do CRM ligado é incidente"

    so_bites = serie_do_indice(sessao, FiltroDeRisco(fontes=("bites",)), TUDO)[0]
    de_agosto = _de_agosto(so_bites)
    assert de_agosto is not None, "agosto tem menção da Bites e devia estar na série"
    assert "crm" not in de_agosto.fontes
    assert de_agosto.fontes == ("bites",)
    assert de_agosto.incidentes < tudo.incidentes, "o filtro tinha de tirar a agenda"
# -- os achados da revisão -------------------------------------------------------


def test_o_ESCOPO_DO_USUARIO_esconde_a_agenda(sessao, com_risco, monkeypatch):
    """A tela de risco não pode contar o que o CRM esconde.

    O CRM restringe por frente e por unidade de negócio (`usuario_escopo`), e a
    primeira versão desta tela não aplicava isso: a mesma agenda ficava
    invisível na listagem do CRM e contava como incidente aqui. É a razão de o
    escopo ser parâmetro obrigatório, e não campo opcional do filtro.

    Com o CRM ligado só aqui. É garantia de privacidade, e precisa continuar
    valendo no dia em que as agendas voltarem.
    """
    ligar_o_crm(sessao, monkeypatch)
    tema, _risco = com_risco
    agenda = _agenda(sessao, tema, "tenso")
    da_agenda = sessao.scalar(
        select(Frente.codigo).where(Frente.id == agenda.frente_id)
    )

    #: QUEM ALCANÇA A FRENTE DA AGENDA conta o incidente.
    de_dentro = _de_agosto(
        serie_do_indice(sessao, FiltroDeRisco(), Escopo(frentes=frozenset({da_agenda})))[0]
    )
    com_a_frente = de_dentro.incidentes if de_dentro else 0

    #: QUEM NÃO ALCANÇA não conta — e é o mesmo banco, no mesmo instante.
    outras = set(sessao.scalars(select(Frente.codigo))) - {da_agenda}
    if not outras:
        #: Só há uma frente cadastrada: o escopo que não alcança nada serve
        #: igual, e é o caso mais severo.
        sem_alcance = Escopo(frentes=frozenset())
    else:
        sem_alcance = Escopo(frentes=frozenset({next(iter(outras))}))

    de_fora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), sem_alcance)[0])
    sem_a_frente = de_fora.incidentes if de_fora else 0

    assert com_a_frente > sem_a_frente, (
        "a agenda devia contar para quem alcança a frente dela, e não para quem não alcança"
    )


def test_o_PESO_e_o_da_PIOR_severidade_tocada(sessao, bites, com_risco):
    """O achado BAIXO: o teste anterior não provava a escolha do peso.

    Um incidente cujo tema toca um risco CRÍTICO e um MODERADO conta uma vez
    (isso já estava provado) — mas com que peso? O do crítico. Pesá-lo pelo
    menor esconderia a gravidade; somar os dois contaria o mesmo fato duas
    vezes.
    """
    tema, _primeiro = com_risco
    critico = sessao.scalar(
        select(Risco).where(Risco.ativo.is_(True), Risco.severidade == "critico").limit(1)
    )
    moderado = sessao.scalar(
        select(Risco).where(Risco.ativo.is_(True), Risco.severidade == "moderado").limit(1)
    )
    assert critico is not None and moderado is not None

    #: UM TEMA SÓ MEU, ligado aos dois, para o peso ser inequívoco.
    meu = Tema(
        nome="Assunto de dois riscos zz61",
        macro_tema_id=tema.macro_tema_id,
        nivel=tema.nivel,
    )
    sessao.add(meu)
    sessao.flush()
    sessao.add_all(
        [
            TemaRisco(tema_id=meu.id, risco_id=critico.id),
            TemaRisco(tema_id=meu.id, risco_id=moderado.id),
        ]
    )
    sessao.flush()

    antes = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    pesado_antes = antes.pesado if antes else 0

    _mencao(sessao, bites, meu, "neg")

    agora = _de_agosto(serie_do_indice(sessao, FiltroDeRisco(), TUDO)[0])
    #: O PESO DO CRÍTICO, e não a soma dos dois nem o do moderado.
    assert agora.pesado == pesado_antes + PESO_DA_SEVERIDADE["critico"]


def test_a_JANELA_marca_os_meses_em_vez_de_corta_los(sessao, bites, com_risco):
    """O achado MÉDIO: a série vem inteira, e a janela marca.

    O protótipo esmaece as barras de fora ("barras esmaecidas ficam fora da
    janela selecionada"), então cortar deixaria o gráfico sem o contexto de onde
    o período escolhido cai na história. A versão anterior nem cortava nem
    marcava: devolvia tudo como se tudo tivesse sido pedido.
    """
    tema, _risco = com_risco
    _mencao(sessao, bites, tema, "neg")

    serie, _referencia, _pico = serie_do_indice(
        sessao, FiltroDeRisco(de=date(2026, 8, 1), ate=date(2026, 8, 1)), TUDO
    )

    de_agosto = next(mes for mes in serie if mes.mes == "2026-08")
    assert de_agosto.na_janela is True
    fora = [mes for mes in serie if mes.mes != "2026-08"]
    assert all(mes.na_janela is False for mes in fora)
    #: E OS MESES DE FORA CONTINUAM NA SÉRIE, com índice: é o que o gráfico
    #: esmaece, não o que ele esconde.
    assert all(mes.indice is not None for mes in fora)
