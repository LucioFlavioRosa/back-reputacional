"""A aba da plataforma: quando cada base foi carregada, e por quem.

O QUE ESTES TESTES PROTEGEM:

* a aba une DUAS fontes de verdade — `carga_de_base` (0115/0116) e `importacao`,
  que as agendas do CRM já tinham. Copiar as agendas para a tabela nova criaria
  uma segunda verdade sobre o mesmo fato;
* só as importações CONFIRMADAS entram: uma em conferência não carregou nada
  ainda, e uma cancelada não carregou nada nunca;
* a permissão é a do portal da plataforma, a mesma do Gerenciamento de perfis;
* `FonteSaida` ganha a última carga por fonte, e ela é NULA antes da primeira —
  a trilha começa na `0115` e não se reconstrói para trás.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_importacao import Importacao, ImportacaoLinha
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_score import CargaDeBase, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from main import app
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


def _cliente(sessao, perfil: str) -> TestClient:
    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": perfil}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    return TestClient(app)


@pytest.fixture
def cliente_admin(sessao):
    try:
        yield _cliente(sessao, "plataforma_edicao")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_admin(sessao):
    """`crm_edicao` entra na plataforma e NÃO administra acessos.

    É o contrapeso exato da guarda — um perfil sem acesso a nada passaria o
    teste de 403 pelo motivo errado.
    """
    try:
        yield _cliente(sessao, "crm_edicao")
    finally:
        app.dependency_overrides.clear()


def _pessoa(sessao, nome: str) -> Usuario:
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "plataforma_edicao")).first()
    registro = Usuario(
        entra_object_id=f"oid-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@aegea.com.br",
        nome=nome,
        papel_id=papel.id,
        acesso_irrestrito=True,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _carga(sessao, **campos) -> CargaDeBase:
    """Uma linha da trilha, gravada direto: aqui o assunto é a LEITURA."""
    padrao = {
        "base": "score",
        "origem": "api:planilha",
        "lote_id": uuid.uuid4(),
        "linhas": 10,
        "meses": [date(2026, 8, 1)],
    }
    carga = CargaDeBase(**{**padrao, **campos})
    sessao.add(carga)
    sessao.flush()
    return carga


def _uma_fonte(sessao) -> ScoreFonte:
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert fonte is not None
    return fonte


def _cargas(cliente, **parametros):
    resposta = cliente.get("/api/plataforma/cargas", params=parametros)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


# -- a permissão ----------------------------------------------------------------


def test_quem_nao_administra_acessos_nao_ve_a_aba(cliente_sem_admin):
    """A mesma guarda do Gerenciamento de perfis, que é a aba vizinha."""
    assert cliente_sem_admin.get("/api/plataforma/cargas").status_code == 403


# -- a união das quatro bases ---------------------------------------------------


def test_a_aba_une_as_quatro_bases(sessao, cliente_admin):
    quem = _pessoa(sessao, "Quem Carregou")
    fonte = _uma_fonte(sessao)
    _carga(
        sessao,
        base="score",
        fonte_id=fonte.id,
        usuario_id=quem.id,
        arquivo="clipping.xlsx",
    )
    _carga(sessao, base="bonds", origem="api:bonds", usuario_id=quem.id, meses=[])
    _carga(sessao, base="subtemas", origem="api:subtemas", linhas=3, meses=[])
    _agenda_confirmada(sessao, quem, quantas_linhas=2)

    bases = {carga["base"] for carga in _cargas(cliente_admin)}

    assert bases == {"score", "bonds", "subtemas", "agendas"}


def test_a_carga_do_score_traz_a_fonte_e_as_outras_nao(sessao, cliente_admin):
    """`fonte` só existe no Score — é a única base que tem fonte."""
    fonte = _uma_fonte(sessao)
    _carga(sessao, base="score", fonte_id=fonte.id)
    _carga(sessao, base="bonds", origem="api:bonds", meses=[])

    por_base = {carga["base"]: carga for carga in _cargas(cliente_admin)}

    assert por_base["score"]["fonte"] == fonte.nome
    assert por_base["bonds"]["fonte"] is None


def test_a_mais_recente_vem_primeiro(sessao, cliente_admin):
    """A pergunta da tela é "está velha?", e a resposta é a primeira linha."""
    fonte = _uma_fonte(sessao)
    agora = datetime.now(UTC)
    _carga(
        sessao,
        base="score",
        fonte_id=fonte.id,
        arquivo="antiga.xlsx",
        concluida_em=agora - timedelta(days=30),
    )
    _carga(
        sessao,
        base="bonds",
        origem="api:bonds",
        meses=[],
        arquivo="recente.xlsx",
        concluida_em=agora,
    )

    assert [c["arquivo"] for c in _cargas(cliente_admin)] == [
        "recente.xlsx",
        "antiga.xlsx",
    ]


def test_o_filtro_por_base(sessao, cliente_admin):
    fonte = _uma_fonte(sessao)
    _carga(sessao, base="score", fonte_id=fonte.id)
    _carga(sessao, base="bonds", origem="api:bonds", meses=[])

    assert {c["base"] for c in _cargas(cliente_admin, base="bonds")} == {"bonds"}
    assert {c["base"] for c in _cargas(cliente_admin, base="score")} == {"score"}


def test_a_carga_de_zero_linha_aparece(sessao, cliente_admin):
    """É o caso que torna a trilha necessária, e a aba tem de mostrá-lo.

    Recorte que não achou veículo nenhum apaga o mês e não insere nada: sem esta
    linha, a tela diria que a base está velha depois de uma carga de hoje.
    """
    fonte = _uma_fonte(sessao)
    _carga(sessao, base="score", fonte_id=fonte.id, linhas=0)

    (carga,) = _cargas(cliente_admin)

    assert carga["linhas"] == 0


def test_carga_sem_usuario_e_informacao_e_nao_dado_faltando(sessao, cliente_admin):
    """Nulo com `origem` preenchida é carga feita fora da tela."""
    fonte = _uma_fonte(sessao)
    _carga(sessao, base="score", fonte_id=fonte.id, origem="carga_do_pacote")

    (carga,) = _cargas(cliente_admin)

    assert carga["quem"] is None
    assert carga["origem"] == "carga_do_pacote"


# -- as agendas, da trilha que elas já tinham -----------------------------------


def _uma_interacao(sessao, quem: Usuario) -> InteracaoRegistro:
    """Uma interação mínima, só para `ImportacaoLinha.interacao_id` ter alvo.

    AS CHAVES SAEM DO CATÁLOGO que as migrations semeiam (`frente`, `status`);
    a instituição nasce aqui. Nada disto é o assunto do teste — o assunto é a
    contagem —, mas a chave estrangeira é real e um uuid inventado seria
    recusado pelo banco antes de a regra ser exercida.
    """
    frente_id = sessao.execute(text("select id from frente order by id limit 1")).scalar()
    status_id = sessao.execute(text("select id from status order by id limit 1")).scalar()
    assert frente_id is not None and status_id is not None
    instituicao = Instituicao(
        nome=f"Órgão zzaba {uuid4().hex[:6]}",
        nome_normalizado=f"orgao zzaba {uuid4().hex[:6]}",
        tipo="orgao",
    )
    sessao.add(instituicao)
    sessao.flush()
    registro = InteracaoRegistro(
        frente_id=frente_id,
        data_interacao=date(2026, 9, 10),
        instituicao_id=instituicao.id,
        uf="SP",
        status_id=status_id,
        criado_por=quem.id,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _agenda_confirmada(sessao, quem: Usuario, *, quantas_linhas: int) -> Importacao:
    """Uma importação de agendas CONFIRMADA, com linhas que viraram interação."""
    importacao = Importacao(
        arquivo_nome="agendas-setembro.xlsx",
        situacao="confirmada",
        criado_por=quem.id,
        confirmado_em=datetime.now(UTC),
    )
    sessao.add(importacao)
    sessao.flush()
    for indice in range(quantas_linhas):
        sessao.add(
            ImportacaoLinha(
                importacao_id=importacao.id,
                aba="Agendas",
                linha_origem=indice + 2,
                dados_brutos={},
                decisao="aceita",
                interacao_id=_uma_interacao(sessao, quem).id,
            )
        )
    sessao.flush()
    return importacao


def test_a_agenda_conta_as_linhas_que_viraram_interacao(sessao, cliente_admin):
    """E não todas as linhas: planilha majoritariamente recusada não é carga grande."""
    quem = _pessoa(sessao, "Quem Importou Agenda")
    importacao = _agenda_confirmada(sessao, quem, quantas_linhas=2)
    #: Uma linha DESCARTADA, que não virou interação: não conta.
    sessao.add(
        ImportacaoLinha(
            importacao_id=importacao.id,
            aba="Agendas",
            linha_origem=99,
            dados_brutos={},
            decisao="descartada",
        )
    )
    sessao.flush()

    (carga,) = _cargas(cliente_admin, base="agendas")

    assert carga["linhas"] == 2
    assert carga["quem"] == "Quem Importou Agenda"
    assert carga["arquivo"] == "agendas-setembro.xlsx"
    assert carga["fonte"] is None
    assert carga["meses"] == []


@pytest.mark.parametrize("situacao", ["processando", "aguardando_conferencia", "cancelada"])
def test_a_importacao_que_nao_confirmou_nao_aparece(sessao, cliente_admin, situacao):
    """Conferência em curso não carregou nada; cancelada não carregou nunca."""
    quem = _pessoa(sessao, "Quem Comecou")
    sessao.add(
        Importacao(
            arquivo_nome="pendente.xlsx",
            situacao=situacao,
            criado_por=quem.id,
        )
    )
    sessao.flush()

    assert _cargas(cliente_admin, base="agendas") == []


# -- a última carga por fonte, na Calibração ------------------------------------


def _fontes(cliente, mes: str = "2026-08"):
    resposta = cliente.get("/api/score/fontes", params={"mes": mes})
    assert resposta.status_code == 200, resposta.text
    return {fonte["codigo"]: fonte for fonte in resposta.json()}


def test_a_fonte_sem_carga_registrada_diz_nulo(sessao, cliente_admin):
    """A trilha começa na `0115` e não se reconstrói: o autor histórico foi
    apagado junto com `planilha_recebida`. Inventar seria pior que admitir."""
    fontes = _fontes(cliente_admin)

    assert fontes["clipei"]["ultima_carga_em"] is None
    assert fontes["clipei"]["ultima_carga_por"] is None


def test_a_fonte_mostra_a_ultima_carga_e_quem_fez(sessao, cliente_admin):
    quem = _pessoa(sessao, "Quem Subiu A Planilha")
    fonte = _uma_fonte(sessao)
    agora = datetime.now(UTC)
    #: DUAS CARGAS, e a tela mostra a mais recente: é a pergunta "está velha?".
    _carga(
        sessao,
        fonte_id=fonte.id,
        usuario_id=_pessoa(sessao, "Quem Subiu Antes").id,
        concluida_em=agora - timedelta(days=10),
    )
    _carga(sessao, fonte_id=fonte.id, usuario_id=quem.id, concluida_em=agora)

    fontes = _fontes(cliente_admin)

    assert fontes["clipei"]["ultima_carga_por"] == "Quem Subiu A Planilha"
    assert fontes["clipei"]["ultima_carga_em"] is not None


def test_a_carga_de_OUTRA_BASE_nao_vira_carga_de_fonte(sessao, cliente_admin):
    """`fonte_id` é nulo em bonds e subtemas, e a Calibração não pode confundir."""
    _carga(sessao, base="bonds", origem="api:bonds", meses=[])

    fontes = _fontes(cliente_admin)

    assert all(f["ultima_carga_em"] is None for f in fontes.values())
