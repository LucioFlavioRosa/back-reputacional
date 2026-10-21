"""A Árvore da taxonomia contra o Postgres: a rota lê o Cadastro de Temas.

A FIXTURE É A PLANILHA QUE FECHOU A TAXONOMIA (`tests/fixtures/...Depara.xlsx`,
aba "De-para Risk tracking"): os nomes e as contagens da rota têm de bater com
ela. E CADA MUDANÇA NO CADASTRO tem de aparecer na rota sem mudar código —
renomear, mover subtema, criar pilar, desativar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.arvore_da_taxonomia import obter_arvore
from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)
PLANILHA = (
    Path(__file__).parent / "fixtures" / "20261008_Aegea_Taxonomia_Temas_RiskTracking_Depara.xlsx"
)


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


@dataclass
class _QuemOlha:
    administra_dicionarios: bool = False
    ve_diretorio: bool = True


def _arvore(sessao):
    return obter_arvore(sessao=sessao, usuario=_QuemOlha())


@pytest.fixture(scope="module")
def planilha():
    livro = openpyxl.load_workbook(PLANILHA, read_only=True, data_only=True)
    depara = [
        linha
        for linha in livro["De-para Risk tracking"].iter_rows(min_row=2, values_only=True)
        if linha[3]
    ]
    riscos = [
        linha
        for linha in livro["Risk tracking map"].iter_rows(min_row=2, values_only=True)
        if linha[1]
    ]
    return depara, riscos


def _sem_numero(pilar: str) -> str:
    """'1. Governança' na planilha; no cadastro o pilar não guarda o número."""
    return re.sub(r"^\d+\.\s*", "", pilar)


def test_com_a_fixture_sao_7_pilares_41_temas_104_subtemas_e_32_riscos_em_8_clusters(
    sessao, planilha
):
    depara, riscos = planilha
    arvore = _arvore(sessao)

    assert len(arvore.pilares) == 7 == len({_sem_numero(linha[1]) for linha in depara})
    assert len(arvore.temas) == 41 == len({(linha[1], linha[2]) for linha in depara})
    assert len(arvore.subtemas) == 104 == len(depara)
    assert len(arvore.riscos) == 32 == len(riscos)
    assert len(arvore.clusters) == 8 == len({linha[0] for linha in riscos})

    # OS MESMOS NOMES, e o subtema no mesmo tema e no mesmo risco primário.
    assert {p.nome for p in arvore.pilares} == {_sem_numero(linha[1]) for linha in depara}
    tema = {t.id: t for t in arvore.temas}
    risco = {r.id: r for r in arvore.riscos}
    no_cadastro = {
        s.nome: (tema[s.tema_id].nome, risco[s.risco_id].nome if s.risco_id else None)
        for s in arvore.subtemas
    }
    for linha in depara:
        primario = None if str(linha[6]).startswith("Sem enquadramento") else linha[6]
        assert no_cadastro[linha[3]] == (linha[2], primario), linha[3]


def test_renomear_e_mover_um_subtema_aparece_sem_mudar_codigo(sessao):
    antes = _arvore(sessao)
    subtema = antes.subtemas[0]
    outro_tema = next(t for t in antes.temas if t.id != subtema.tema_id)

    registro = sessao.get(Tema, subtema.id)
    registro.nome = "Nome novo de teste"
    registro.macro_tema_id = outro_tema.id
    sessao.flush()

    depois = {s.id: s for s in _arvore(sessao).subtemas}
    assert depois[subtema.id].nome == "Nome novo de teste"
    assert depois[subtema.id].tema_id == outro_tema.id


def test_criar_um_pilar_aparece_com_o_tema_e_o_subtema_dele(sessao):
    ultima = max(p.ordem for p in _arvore(sessao).pilares)
    pilar = BlocoTema(codigo="pilar_de_teste", nome="Pilar de teste", ordem=ultima + 1, ativo=True)
    sessao.add(pilar)
    sessao.flush()
    tema = MacroTema(
        bloco_tema_id=pilar.id, codigo="tema_de_teste", nome="Tema de teste", ordem=1, ativo=True
    )
    sessao.add(tema)
    sessao.flush()
    sessao.add(Tema(nome="Subtema de teste", nivel="estrategico", macro_tema_id=tema.id))
    sessao.flush()

    arvore = _arvore(sessao)
    assert arvore.pilares[-1].nome == "Pilar de teste"
    assert any(t.nome == "Tema de teste" and t.pilar_id == pilar.id for t in arvore.temas)
    novo = next(s for s in arvore.subtemas if s.nome == "Subtema de teste")
    assert novo.risco_id is None and novo.lso is None


def test_inativo_nao_aparece(sessao):
    subtema = _arvore(sessao).subtemas[0]
    sessao.get(Tema, subtema.id).ativo = False
    sessao.flush()
    assert subtema.id not in {s.id for s in _arvore(sessao).subtemas}


def test_as_cores_vem_prontas_com_o_balde_do_vazio(sessao):
    cores = {d.chave: d for d in _arvore(sessao).cores}
    assert list(cores) == ["sev", "lso"]
    assert cores["sev"].alvo == "risco" and cores["lso"].alvo == "subtema"
    severidades = {r.severidade for r in _arvore(sessao).riscos}
    assert severidades <= {v.codigo for v in cores["sev"].valores}
    assert cores["lso"].vazio.hachurado


def test_a_rota_esta_registrada(sessao):
    from main import app

    assert "/api/taxonomia/arvore" in app.openapi()["paths"]


def test_a_rota_nao_exige_portal_score(sessao):
    """SÓ LOGIN (20/10/2026, por pedido): a árvore saiu da Metodologia do
    Score e ganhou cartão próprio na Início, aberto a qualquer pessoa logada.

    `cliente`, aqui, roda como `crm_edicao` — que NÃO acessa Score
    (`acessa_score=False`, ver `tests/test_e2e_postgres.py::cliente`). Antes
    desta mudança a rota exigia `exigir_portal_score` e este papel recebia
    403; a regressão que este teste existe para travar é alguém devolver
    `exigir_portal_score` ao router por achar que "é do Score" só porque
    o arquivo um dia morou lá.
    """
    from fastapi.testclient import TestClient

    from main import app as aplicacao

    aplicacao.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        cliente = TestClient(aplicacao)
        resposta = cliente.get("/api/taxonomia/arvore")
    finally:
        aplicacao.dependency_overrides.clear()

    assert resposta.status_code == 200
