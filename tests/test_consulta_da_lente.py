"""A Consulta em profundidade contra o Postgres: a rota, o banco e a nota da tela.

O DOMÍNIO JÁ PROVA A ÁRVORE com menções na mão (`test_consulta_profundidade`).
O que só o banco prova é a COSTURA: que a leitura das menções, a do agregado
(`score_mes_fonte`) e a da taxonomia chegam ao mesmo número que o resto do
produto já mostra. Se a Consulta disser −7,7 e o recorte do dossiê disser −7,6
para o mesmo mês, a diretoria vê dois números para a mesma pergunta — e deixa de
acreditar nos dois.

POR ISSO CADA TESTE COMPARA COM UMA FUNÇÃO QUE JÁ EXISTE, e não com um número
escrito aqui: a soma dos pilares com `impacto_do_recorte` sem filtro, o pilar
com o recorte pelo atributo, a nota com `medir_lentes` (a do dossiê).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.consulta_profundidade import obter_consulta
from app.banco import repositorio_score
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.erros import NaoEncontrado
from app.dominio.score import FiltroDeMencoes, peso_do_cargo, peso_do_engajamento
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: UM MÊS LONGE DE TUDO, para nenhuma semente do banco de teste entrar na conta.
MES = date(2031, 5, 1)
TEXTO_DO_MES = "2031-05"


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


def _gravar(sessao, fonte_codigo: str, linhas: list[dict], mes: date = MES) -> None:
    """Grava as menções E o agregado do mês, como `ingerir_mencoes` faria.

    O AGREGADO É REFEITO DAS MESMAS LINHAS, no grão (sentimento, tier) de
    `score_mes_fonte`. É a condição de fechamento da Consulta: D vem dali, e os
    numeradores vêm da menção.
    """
    fonte = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == fonte_codigo)).one()
    grao: Counter[tuple[str, str]] = Counter()
    for linha in linhas:
        sessao.add(Mencao(fonte_id=fonte.id, mes=mes, **linha))
        grao[(linha["sentimento"], linha.get("tier") or "")] += 1
    for (sentimento, tier), quantas in grao.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=fonte.id,
                mes=mes,
                sentimento=sentimento,
                tier=tier,
                mencoes=quantas,
                soma_log=quantas * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=quantas * peso_do_cargo(None),
            )
        )
    sessao.flush()


def _linhas_da_imprensa(sessao) -> list[dict]:
    """Os três jeitos de uma menção chegar à taxonomia, e um que não chega.

    - `tema_id` gravado (a ingestão nova faz isso pela Subcategoria);
    - só a Subcategoria em `tema_texto`, de uma carga antiga;
    - só o pilar no atributo, com o prefixo do export real;
    - nada que case: o nó "Sem pilar identificado".
    """
    atendimento = sessao.scalars(
        select(Tema).where(Tema.nome == "Atendimento ao cliente", Tema.ativo.is_(True))
    ).one()
    base = {"veiculo": "Folha", "unidade_texto": "Águas do Rio", "data": date(2031, 5, 12)}
    return [
        {**base, "sentimento": "neg", "tier": "muito_relevante", "tema_id": atendimento.id,
         "tema_texto": "Atendimento ao cliente",
         "atributo": "2. Eficiência Operacional e Qualidade"},
        {**base, "sentimento": "pos", "tier": "relevante", "tema_texto": "atendimento ao cliente"},
        {**base, "sentimento": "neu", "tier": "menos_relevante",
         "tema_texto": "Atendimento ao cliente"},
        {**base, "sentimento": "neg", "tier": "relevante", "tema_texto": "Obras",
         "atributo": "1. Governança"},
        {**base, "sentimento": "pos", "tier": "menos_relevante", "tema_texto": "Obras",
         "atributo": "Governança"},
        {**base, "sentimento": "neg", "tier": "menos_relevante", "tema_texto": "Qualquer",
         "atributo": "Nada que case", "data": date(2031, 5, 20)},
    ]


def _consulta(sessao, codigo: str = "imprensa", mes: str = TEXTO_DO_MES) -> dict:
    return obter_consulta(sessao=sessao, usuario=_QuemOlha(), codigo=codigo, mes=mes)


def _lente(sessao, codigo: str) -> Lente:
    return sessao.scalars(select(Lente).where(Lente.codigo == codigo)).one()


def test_os_pilares_somam_o_impacto_do_mes_inteiro_e_50_ns(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    saida = _consulta(sessao)
    conferencia = saida["meta"]["conferencia"]

    calibracao = repositorio_score.calibracao_vigente(sessao)
    lente = _lente(sessao, "imprensa")
    do_recorte = repositorio_score.impacto_do_recorte(sessao, lente.id, MES, calibracao)
    medida = repositorio_score.medir_uma_lente(sessao, lente, MES, calibracao)

    assert conferencia["fecha"] is True
    assert conferencia["somaPilares"] == pytest.approx(do_recorte, abs=1e-4)
    assert conferencia["somaPilares"] == pytest.approx(50 * medida.ns, abs=1e-4)
    pilares = saida["lentes"][0]["pilares"]
    assert round(sum(p["impacto"] for p in pilares), 1) == round(do_recorte, 1)
    assert conferencia["semVinculo"]["pilar"] == 1
    assert pilares[-1]["id"] == "sem-pilar"


def test_o_pilar_sem_divergencia_e_o_recorte_pelo_atributo(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    pilares = {p["id"]: p for p in _consulta(sessao)["lentes"][0]["pilares"]}

    calibracao = repositorio_score.calibracao_vigente(sessao)
    lente = _lente(sessao, "imprensa")
    # As duas menções de Governança vêm SÓ pelo atributo, uma com o prefixo do
    # export real e outra sem — o recorte do dossiê precisa das duas grafias.
    governanca = sum(
        repositorio_score.impacto_do_recorte(
            sessao, lente.id, MES, calibracao, FiltroDeMencoes(atributo=valor)
        )
        for valor in ("1. Governança", "Governança")
    )
    assert pilares["governanca"]["impacto"] == round(governanca, 1)
    assert pilares["governanca"]["volume"] == 2
    assert "filhos" not in pilares["governanca"]  # só "sem tema": não abre


def test_os_quatro_niveis_abrem_pela_cadeia_do_cadastro(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    lente = _consulta(sessao)["lentes"][0]
    pilar = next(p for p in lente["pilares"] if p["id"] == "eficiencia_operacional_e_qualidade")
    assert pilar["volume"] == 3
    tema = pilar["filhos"][0]
    assert tema["nome"] != "Sem tema identificado" and "nivel3" in tema
    subtema = tema["filhos"][0]
    assert subtema["id"] == "atendimento_ao_cliente"
    assert len(subtema["nivel4"]["porDia"]["total"]) == 31
    assert {i["sentimento"] for i in subtema["nivel4"]["itens"]} == {
        "positivo", "neutro", "negativo"
    }
    assert lente["drill"] is True
    assert [c["tipo"] for c in lente["cartoesLaterais"]] == ["oQueMudou", "historia"]


def test_a_nota_e_a_do_dossie(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    lente = _consulta(sessao)["lentes"][0]
    calibracao = repositorio_score.calibracao_vigente(sessao)
    do_dossie = next(
        m for m in repositorio_score.medir_lentes(sessao, MES, calibracao)
        if m.codigo == "imprensa"
    )
    assert lente["nota"] == do_dossie.score
    assert lente["serie"][-1] == do_dossie.score
    assert lente["totalPonderado"] == pytest.approx(10 + 5 + 1 + 5 + 1 + 1)


def test_o_mercado_responde_sem_drill(sessao):
    _gravar(
        sessao,
        "clipei_investidores",
        [
            {"sentimento": "pos", "tier": "muito_relevante", "veiculo": "Valor",
             "tema_texto": "Tarifa"},
            {"sentimento": "neg", "tier": "relevante", "veiculo": "Valor",
             "atributo": "3. Crescimento e Solidez Financeira"},
        ],
    )
    saida = _consulta(sessao, "mercado")
    lente = saida["lentes"][0]
    assert lente["id"] == "mercado" and lente["drill"] is False
    assert saida["meta"]["conferencia"]["fecha"] is True
    assert round(sum(p["impacto"] for p in lente["pilares"]), 1) == round(50 * (10 - 5) / 15, 1)
    assert [c["tipo"] for c in lente["cartoesLaterais"]] == ["oQueMudou", "divergentes"]


def test_lente_fora_da_consulta_e_404(sessao):
    with pytest.raises(NaoEncontrado):
        _consulta(sessao, "sociedade")
    with pytest.raises(NaoEncontrado):
        _consulta(sessao, "nao-existe")


def test_mes_sem_dado_volta_vazio_sem_erro(sessao):
    saida = _consulta(sessao, "imprensa", "2031-02")
    lente = saida["lentes"][0]
    assert saida["meta"]["vazio"] is True
    assert lente["pilares"] == [] and lente["cartoesLaterais"] == []
    assert lente["volumeTotal"] == 0 and lente["nota"] is None


def test_o_mes_anterior_agrupado_no_banco_da_o_mesmo_impacto_do_recorte(sessao):
    """Os cinco meses antes do da tela vêm de um GROUP BY, e não linha a linha:
    o pilar de abril tem de ser o mesmo que o recorte de abril pelo atributo."""
    abril = date(2031, 4, 1)
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao), mes=abril)
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    pilares = {p["id"]: p for p in _consulta(sessao)["lentes"][0]["pilares"]}

    calibracao = repositorio_score.calibracao_vigente(sessao)
    lente = _lente(sessao, "imprensa")
    governanca_em_abril = sum(
        repositorio_score.impacto_do_recorte(
            sessao, lente.id, abril, calibracao, FiltroDeMencoes(atributo=valor)
        )
        for valor in ("1. Governança", "Governança")
    )
    assert pilares["governanca"]["impactoMesAnterior"] == round(governanca_em_abril, 1)
    tema = next(
        t for t in pilares["eficiencia_operacional_e_qualidade"]["filhos"]
        if not t["id"].startswith("sem-")
    )
    evolucao = pilares["eficiencia_operacional_e_qualidade"]["nivel2"]["destaque"]["evolucao"]
    assert evolucao["volumes"][-2] == tema["volume"]  # o mesmo mês, agrupado
    assert evolucao["impactos"][-2] == tema["impactoMesAnterior"]


# -- pelo HTTP: a rota registrada, a permissão do portal e o 422 ----------------------


@pytest.fixture
def cliente(sessao):
    from main import app
    from tests.test_score_api import _cliente

    try:
        yield lambda perfil: _cliente(sessao, perfil)
    finally:
        app.dependency_overrides.clear()


def test_pelo_http_a_consulta_responde_comprimida_a_quem_tem_o_score(sessao, cliente):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    resposta = cliente("plataforma_edicao").get(
        f"/api/score/lentes/imprensa/consulta?mes={TEXTO_DO_MES}",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["meta"]["versao"] == "api-1"
    assert resposta.headers.get("content-encoding") == "gzip"


def test_pelo_http_quem_nao_tem_o_portal_do_score_nao_le_a_consulta(cliente):
    resposta = cliente("crm_edicao").get(
        f"/api/score/lentes/imprensa/consulta?mes={TEXTO_DO_MES}"
    )
    assert resposta.status_code == 403


@pytest.mark.parametrize("mes", ["2026-13", "abc", "0001-02", "1-1", "99999-01"])
def test_pelo_http_mes_invalido_e_422_e_nunca_500(cliente, mes):
    resposta = cliente("plataforma_edicao").get(f"/api/score/lentes/imprensa/consulta?mes={mes}")
    assert resposta.status_code == 422


def test_pelo_http_lente_fora_da_consulta_e_404(cliente):
    resposta = cliente("plataforma_edicao").get(
        f"/api/score/lentes/sociedade/consulta?mes={TEXTO_DO_MES}"
    )
    assert resposta.status_code == 404
