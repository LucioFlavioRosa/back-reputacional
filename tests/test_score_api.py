"""O Score servido pela API — o contrato, e quem alcança o quê.

As fórmulas se provam em `test_score.py`, sem banco. Aqui é o resto: o índice
sai com as lentes que o formaram, a calibração é versionada e só quem
administra cadastros a muda, a lente institucional vem DAS INTERAÇÕES deste
banco, e quem não tem o portal Score não lê nada disso.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_score import Lente, ScoreConfig, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao
from main import app
from tests.test_e2e_postgres import URL, corpo

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


def _cliente(sessao, perfil: str):
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": perfil}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    return TestClient(app)


@pytest.fixture
def cliente_do_score(sessao):
    """`plataforma_edicao`: alcança o Score E administra cadastros."""
    cliente = _cliente(sessao, "plataforma_edicao")
    try:
        yield cliente
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_score(sessao):
    """`crm_edicao`: escreve agenda e NÃO alcança o portal Score."""
    cliente = _cliente(sessao, "crm_edicao")
    try:
        yield cliente
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    valor = Instituicao(
        nome="Valor Econômico", nome_normalizado="valor economico",
        tipo="veiculo", uf="SP",
    )
    sessao.add(valor)
    sessao.flush()
    return {"instituicao": valor}


@pytest.fixture
def junho(sessao):
    """Junho com uma fonte de imprensa, no grão que o índice lê."""
    mes = date(2026, 6, 1)
    sessao.execute(delete(ScoreMesFonte).where(ScoreMesFonte.mes == mes))
    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    for tier, contagens in {
        "muito_relevante": {"pos": 65, "neu": 64, "neg": 16},
        "relevante": {"pos": 85, "neu": 43, "neg": 55},
        "menos_relevante": {"pos": 946, "neu": 80, "neg": 149},
    }.items():
        for sentimento, total in contagens.items():
            sessao.add(
                ScoreMesFonte(
                    fonte_id=clipei.id, mes=mes, sentimento=sentimento,
                    tier=tier, mencoes=total,
                )
            )
    sessao.flush()
    return mes


# -- as cinco lentes e o índice -------------------------------------------------


def test_a_migration_cadastrou_as_cinco_lentes_e_as_seis_fontes(sessao):
    lentes = sessao.scalars(select(Lente).order_by(Lente.ordem)).all()
    assert [lente.codigo for lente in lentes] == [
        "imprensa", "mercado", "sociedade", "clientes", "institucional"
    ]
    assert sum(lente.peso_padrao for lente in lentes) == 100

    fontes = sessao.scalars(select(ScoreFonte)).all()
    assert {fonte.codigo for fonte in fontes} >= {
        "clipei", "edelman", "approach_sl", "bites", "approach_cm", "crm"
    }
    # O CRM é a única fonte interna: ela se lê deste banco, não de planilha.
    assert [fonte.codigo for fonte in fontes if fonte.interna] == ["crm"]


def test_o_indice_traz_a_imprensa_em_70_com_a_regua_padrao(cliente_do_score, junho):
    """O critério de aceite do §7, pela API."""
    resposta = cliente_do_score.get("/api/score?mes=2026-06")
    assert resposta.status_code == 200, resposta.text

    corpo_ = resposta.json()
    imprensa = next(lente for lente in corpo_["lentes"] if lente["codigo"] == "imprensa")
    assert imprensa["score"] == 70
    assert imprensa["fontes"] == ["clipei"]
    assert corpo_["calibracao"]["padrao"] is True


def test_a_lente_institucional_vem_das_interacoes_deste_banco(
    cliente_do_score, sessao, semente, junho
):
    """Sem cópia: o clima das interações É a lente.

    É o que garante que corrigir um registro no CRM corrige o índice — com o
    clima duplicado numa tabela de menções, o índice mentiria até alguém
    reprocessar.
    """
    antes = cliente_do_score.get("/api/score?mes=2026-06").json()
    institucional_antes = next(
        lente for lente in antes["lentes"] if lente["codigo"] == "institucional"
    )

    for clima in ("propositivo", "propositivo", "tenso"):
        criada = cliente_do_score.post(
            "/api/interacoes",
            json={**corpo(semente), "data_interacao": "2026-06-15", "clima": clima},
        )
        assert criada.status_code == 201, criada.text

    depois = cliente_do_score.get("/api/score?mes=2026-06").json()
    institucional_depois = next(
        lente for lente in depois["lentes"] if lente["codigo"] == "institucional"
    )

    assert institucional_depois["fontes"] == ["crm"]
    assert institucional_depois["score"] != institucional_antes["score"] or (
        institucional_antes["score"] is None
    )


def test_a_leitura_diz_o_que_sustenta_e_o_que_corroi(cliente_do_score, junho):
    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    assert "sustenta o índice" in corpo_["leitura"]
    assert "pressiona" in corpo_["leitura"]


def test_a_serie_diz_quantas_lentes_formaram_cada_ponto(cliente_do_score, junho):
    """Um mês com uma lente só produz um ISR legítimo pela fórmula e enganoso
    na curva — a tela precisa poder marcar o ponto como parcial."""
    serie = cliente_do_score.get("/api/score/serie").json()
    assert serie, "junho tem dado; a série não pode vir vazia"
    assert all("lentes" in ponto for ponto in serie)
    assert all(0 <= ponto["lentes"] <= 5 for ponto in serie)


def test_mes_invalido_e_recusado_dizendo_o_formato(cliente_do_score):
    resposta = cliente_do_score.get("/api/score?mes=junho")
    assert resposta.status_code == 422
    assert "AAAA-MM" in resposta.json()["detalhe"]


# -- a calibração ---------------------------------------------------------------


def test_desligar_as_fontes_da_sociedade_tira_a_lente_e_redistribui(
    cliente_do_score, junho
):
    """§7: "Desligar Approach SL e Bites remove Sociedade e redistribui pesos"."""
    gravou = cliente_do_score.put(
        "/api/score/calibracao",
        json={"fontes_desligadas": ["approach_sl", "bites"]},
    )
    assert gravou.status_code == 201, gravou.text
    assert gravou.json()["padrao"] is False

    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    sociedade = next(lente for lente in corpo_["lentes"] if lente["codigo"] == "sociedade")
    assert sociedade["score"] is None
    assert "desligadas" in sociedade["ausencia"]
    assert "Fora do cálculo" in corpo_["leitura"]


def test_a_regua_de_tier_muda_o_indice_sem_tocar_no_dado(cliente_do_score, junho):
    """O agregado é o mesmo; o que muda é quanto cada tier vale."""
    com_padrao = cliente_do_score.get("/api/score?mes=2026-06").json()
    imprensa_padrao = next(
        lente for lente in com_padrao["lentes"] if lente["codigo"] == "imprensa"
    )["score"]

    cliente_do_score.put("/api/score/calibracao", json={"regua_tier": "igual"})

    sem_ponderacao = cliente_do_score.get("/api/score?mes=2026-06").json()
    imprensa_sem = next(
        lente for lente in sem_ponderacao["lentes"] if lente["codigo"] == "imprensa"
    )["score"]

    assert imprensa_sem != imprensa_padrao


def test_a_calibracao_e_versionada_e_nao_sobrescrita(cliente_do_score, sessao, junho):
    """Saber com que régua um número foi lido é o que explica por que ele
    mudou — por isso a tabela só cresce."""
    antes = len(sessao.scalars(select(ScoreConfig)).all())

    cliente_do_score.put("/api/score/calibracao", json={"regua_engajamento": "log"})
    cliente_do_score.put("/api/score/calibracao", json={"regua_engajamento": "bruto"})

    depois = len(sessao.scalars(select(ScoreConfig)).all())
    assert depois == antes + 2


def test_restaurar_o_padrao_grava_uma_versao_em_vez_de_apagar(cliente_do_score, junho):
    cliente_do_score.put("/api/score/calibracao", json={"regua_tier": "forte"})
    restaurou = cliente_do_score.delete("/api/score/calibracao")

    assert restaurou.status_code == 201, restaurou.text
    assert restaurou.json()["padrao"] is True
    assert restaurou.json()["regua_tier"] == "aegea"


def test_regua_invalida_e_recusada(cliente_do_score):
    recusa = cliente_do_score.put("/api/score/calibracao", json={"regua_tier": "chute"})
    assert recusa.status_code == 422
    assert "Régua de tier inválida" in recusa.json()["detalhe"]


def test_peso_fora_da_faixa_e_recusado(cliente_do_score):
    recusa = cliente_do_score.put(
        "/api/score/calibracao", json={"pesos": {"imprensa": 90}}
    )
    assert recusa.status_code == 422
    assert "fora da faixa" in recusa.json()["detalhe"]


def test_lente_ou_fonte_desconhecida_e_recusada(cliente_do_score):
    assert cliente_do_score.put(
        "/api/score/calibracao", json={"pesos": {"astrologia": 10}}
    ).status_code == 422
    assert cliente_do_score.put(
        "/api/score/calibracao", json={"fontes_desligadas": ["inventada"]}
    ).status_code == 422


# -- quem alcança o quê ---------------------------------------------------------


def test_quem_nao_tem_o_portal_score_nao_le_o_indice(cliente_sem_score):
    """O cartão escondido na capa não protege a rota: um `curl` basta."""
    recusa = cliente_sem_score.get("/api/score?mes=2026-06")
    assert recusa.status_code == 403
    assert "Score Executivo" in recusa.json()["detalhe"]


def test_a_calibracao_exige_administrar_cadastros(sessao, junho):
    """Ler o índice é de quem tem o portal; MEXER NA RÉGUA é da coordenação —
    ela muda o número que todo mundo lê."""
    leitura = _cliente(sessao, "score_leitura")
    try:
        assert leitura.get("/api/score?mes=2026-06").status_code == 200
        assert leitura.put(
            "/api/score/calibracao", json={"regua_tier": "forte"}
        ).status_code == 403
    finally:
        app.dependency_overrides.clear()


# -- os fatos do mês ------------------------------------------------------------


def test_o_fato_do_mes_aparece_no_indice(cliente_do_score, junho):
    """É o que transforma uma curva em explicação."""
    criado = cliente_do_score.post(
        "/api/score/fatos",
        json={"mes": "2026-06", "texto": "Atraso na divulgação das DFs", "efeito": "pressiona"},
    )
    assert criado.status_code == 201, criado.text

    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    assert [f["texto"] for f in corpo_["fatos"]] == ["Atraso na divulgação das DFs"]

    apagou = cliente_do_score.delete(f"/api/score/fatos/{criado.json()['id']}")
    assert apagou.status_code == 204


def test_efeito_invalido_e_recusado(cliente_do_score):
    recusa = cliente_do_score.post(
        "/api/score/fatos",
        json={"mes": "2026-06", "texto": "Alguma coisa", "efeito": "chute"},
    )
    assert recusa.status_code == 422
    assert "Efeito inválido" in recusa.json()["detalhe"]


# -- o registro de fontes -------------------------------------------------------


def test_as_fontes_trazem_cobertura_e_volume_do_mes(cliente_do_score, junho):
    """A aba Calibração lista: fonte, lente, cobertura de meses, volume."""
    fontes = cliente_do_score.get("/api/score/fontes?mes=2026-06").json()
    clipei = next(f for f in fontes if f["codigo"] == "clipei")

    assert clipei["lente"] == "Imprensa"
    assert clipei["meses_com_dado"] >= 1
    assert clipei["mencoes_no_mes"] == 1503
    assert clipei["ligada"] is True


def test_as_opcoes_da_calibracao_vem_do_servidor(cliente_do_score):
    """A tela não tem lista fixa de régua nem de lente: uma régua nova passa a
    ser oferecida sem build do front."""
    opcoes = cliente_do_score.get("/api/score/opcoes").json()

    assert {r["codigo"] for r in opcoes["reguas_de_tier"]} == {
        "aegea", "suave", "forte", "igual", "so_tier1"
    }
    assert set(opcoes["reguas_de_engajamento"]) == {"n", "log", "bruto", "cargo"}
    assert len(opcoes["lentes"]) == 5
