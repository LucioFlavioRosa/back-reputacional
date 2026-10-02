"""O recorte da tela (tier/veículo/atributo/tema) no dossiê da lente.

POR QUE UM ARQUIVO À PARTE, e não dentro de `test_lentes_v2.py`: aquele banco
de teste nasce vazio de `mencao` — os testes existentes provam a FORMA do
dossiê (quatro KPIs, dois painéis, fichas) sem precisar de dado real. Provar
que o filtro realmente muda a nota exige inserir `mencao` de verdade, com
tier/veículo/atributo/tema variados, e isso merece seu próprio cenário.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.lentes import obter_dossie, obter_opcoes_de_filtro
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.score import peso_do_cargo, peso_do_engajamento
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

MES = date(2026, 6, 1)


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


@pytest.fixture
def imprensa_de_junho(sessao):
    """Seis matérias de Clipei em junho/2026: duas de cada tier, metade do
    veículo A (atributo "Qualidade") e metade do B (atributo "Preço"), com
    sentimento oposto entre os dois grupos — para o filtro ter o que separar.

    TAMBÉM grava `score_mes_fonte` com a MESMA soma — não é redundância, é o
    que faz o caminho SEM filtro (que só lê o agregado, nunca `mencao`) ter
    nota: sem isto, a nota viria `None` ("sem menção classificada") mesmo
    com seis menções no banco, porque é assim que a ingestão de verdade
    preenche aquela tabela, e este teste não roda ingestão nenhuma.
    """
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    linhas = [
        # tier, veiculo, atributo, tema_texto, sentimento
        ("muito_relevante", "Veículo A", "Qualidade", "Tarifa", "pos"),
        ("muito_relevante", "Veículo A", "Qualidade", "Tarifa", "pos"),
        ("relevante", "Veículo B", "Preço", "Obras", "neg"),
        ("relevante", "Veículo B", "Preço", "Obras", "neg"),
        ("menos_relevante", "Veículo A", "Qualidade", "Tarifa", "neu"),
        ("menos_relevante", "Veículo B", "Preço", "Obras", "neu"),
    ]
    for tier, veiculo, atributo, tema_texto, sentimento in linhas:
        sessao.add(
            Mencao(
                fonte_id=clipei.id,
                mes=MES,
                sentimento=sentimento,
                tier=tier,
                veiculo=veiculo,
                atributo=atributo,
                tema_texto=tema_texto,
            )
        )

    por_grupo: dict[tuple[str, str], int] = {}
    for tier, _veiculo, _atributo, _tema, sentimento in linhas:
        por_grupo[(sentimento, tier)] = por_grupo.get((sentimento, tier), 0) + 1
    for (sentimento, tier), mencoes in por_grupo.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=clipei.id,
                mes=MES,
                sentimento=sentimento,
                tier=tier,
                mencoes=mencoes,
                soma_log=mencoes * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=mencoes * peso_do_cargo(None),
            )
        )

    sessao.flush()
    return linhas


def _dossie(sessao, **filtro):
    return obter_dossie(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes="2026-06", **filtro
    )


def test_sem_filtro_usa_todas_as_mencoes_e_nao_se_marca_como_recorte(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    assert dossie.recorte_filtrado is False
    assert dossie.delta_versus == "mes_anterior"
    # Pesos do tier (régua "aegea"): 10/5/1. positivo=2*10=20, negativo=2*5=10,
    # neutro=2*1=2 -> NS = (20-10)/32 = 0,3125 -> score = round(65,625) = 66.
    assert dossie.nota == 66


def test_evolucao_fala_de_materia_e_nao_repete_a_manchete_da_nota(sessao, imprensa_de_junho):
    """A conclusão do gráfico de Evolução precisa bater com o que ele desenha
    (contagem de matéria) — e não repetir a manchete do Destaque, que fala da
    nota. 2 positivas, 2 neutras, 2 negativas: 33% cada."""
    dossie = _dossie(sessao)

    assert dossie.evolucao.titulo == "Evolução das matérias"
    assert dossie.evolucao.conclusao == (
        "6 matérias em junho: 33% positivas, 33% neutras, 33% negativas."
    )
    assert dossie.evolucao.conclusao != dossie.manchete


def test_filtrar_por_tier_muda_a_nota_e_marca_o_recorte(sessao, imprensa_de_junho):
    """Só o tier muito_relevante: as duas matérias positivas do Veículo A."""
    dossie = _dossie(sessao, tier="muito_relevante")

    assert dossie.recorte_filtrado is True
    assert dossie.delta_versus == "sem_filtro"
    # 2 positivas, 0 neutras, 0 negativas -> NS = 1 -> score = 100.
    assert dossie.nota == 100
    # vs. a nota sem filtro (66): delta = 100 - 66 = 34.
    assert dossie.delta == 34


def test_filtrar_por_veiculo_muda_a_nota_tambem(sessao, imprensa_de_junho):
    """Só o Veículo B: negativo=2*5=10 (tier relevante), neutro=1*1=1 (tier
    menos_relevante) -> NS = (0-10)/11 ≈ -0,909 -> score = round(4,545) = 5."""
    dossie = _dossie(sessao, veiculo="Veículo B")

    assert dossie.recorte_filtrado is True
    assert dossie.nota == 5


def test_filtrar_por_atributo_e_tema_restringe_igual_a_veiculo(sessao, imprensa_de_junho):
    """"Qualidade" e "Tarifa" são sinônimos de Veículo A neste cenário:
    positivo=2*10=20 (tier muito_relevante), neutro=1*1=1 (tier
    menos_relevante) -> NS = 20/21 ≈ 0,952 -> score = round(97,619) = 98."""
    por_atributo = _dossie(sessao, atributo="Qualidade")
    por_tema = _dossie(sessao, tema="Tarifa")

    assert por_atributo.nota == por_tema.nota == 98


def test_painel_a_so_mostra_o_tier_filtrado(sessao, imprensa_de_junho):
    dossie = _dossie(sessao, tier="relevante")

    (painel_a,) = (p for p in dossie.paineis if p.tipo == "barras_100")
    rotulos = {linha["rotulo"] for linha in painel_a.dados}
    assert rotulos == {"Tier 2"}


def test_filtro_de_veiculo_nao_afeta_tier_nem_atributo(sessao, imprensa_de_junho):
    """Os quatro filtros são independentes: pedir só `veiculo` não implica
    nenhuma restrição de tier/atributo/tema."""
    dossie = _dossie(sessao, veiculo="Veículo A")

    (painel_a,) = (p for p in dossie.paineis if p.tipo == "barras_100")
    rotulos = {linha["rotulo"] for linha in painel_a.dados}
    # Veículo A tem matérias em DOIS tiers (muito_relevante e menos_relevante).
    assert rotulos == {"Tier 1", "Tier 3"}


def test_opcoes_de_filtro_lista_so_o_que_existe_no_mes(sessao, imprensa_de_junho):
    opcoes = obter_opcoes_de_filtro(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes="2026-06"
    )

    assert set(opcoes.tiers) == {"muito_relevante", "relevante", "menos_relevante"}
    assert set(opcoes.veiculos) == {"Veículo A", "Veículo B"}
    assert set(opcoes.atributos) == {"Qualidade", "Preço"}
    assert set(opcoes.temas) == {"Tarifa", "Obras"}


def test_opcoes_de_filtro_vazias_fora_do_mes_semeado(sessao, imprensa_de_junho):
    opcoes = obter_opcoes_de_filtro(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes="2026-01"
    )

    assert opcoes.tiers == opcoes.veiculos == opcoes.atributos == opcoes.temas == []


# -- o drill-down: últimas matérias ----------------------------------------------


def test_materias_recentes_aparece_com_teto_de_cinco(sessao, imprensa_de_junho):
    """Seis menções semeadas, teto de cinco — o recorte pedido para o
    exercício não é "todas", é uma amostra pequena."""
    dossie = _dossie(sessao)

    bloco = dossie.materias_recentes
    assert bloco.tipo == "tabela"
    assert bloco.subtipo == "materias"
    assert len(bloco.dados) == 5
    # Nenhuma das seis menções do fixture tem `data` — a ordenação cai para
    # `criado_em`, mas o que este teste trava é só o teto, não a ordem exata.
    assert {linha["veiculo"] for linha in bloco.dados} <= {"Veículo A", "Veículo B"}


def test_materias_recentes_respeita_o_mesmo_filtro_da_tela(sessao, imprensa_de_junho):
    """Filtrar por tier muito_relevante deixa só as duas matérias daquele
    tier — o mesmo recorte que já muda a nota e o painel A."""
    dossie = _dossie(sessao, tier="muito_relevante")

    linhas = dossie.materias_recentes.dados
    assert len(linhas) == 2
    assert {linha["tier"] for linha in linhas} == {"Tier 1"}
    assert {linha["veiculo"] for linha in linhas} == {"Veículo A"}


def test_materias_recentes_vazia_na_institucional(sessao):
    """A lente Institucional lê o CRM, não `mencao` — não há matéria lá."""
    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="institucional", mes="2026-06")

    assert dossie.materias_recentes.dados == []
    assert dossie.materias_recentes.ficha.lacunas


# -- drivers e riscos, e temas mais falados --------------------------------------


def test_drivers_e_riscos_agrega_por_atributo(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    bloco = dossie.drivers_e_riscos
    assert bloco.tipo == "barras_100"
    por_rotulo = {linha["rotulo"]: linha for linha in bloco.dados}
    assert por_rotulo["Qualidade"] == {
        "rotulo": "Qualidade", "positivo": 2, "neutro": 1, "negativo": 0,
    }
    assert por_rotulo["Preço"] == {"rotulo": "Preço", "positivo": 0, "neutro": 1, "negativo": 2}


def test_drivers_e_riscos_mostra_os_SETE_pilares_mesmo_com_volume_desigual(sessao):
    """Atributo é vocabulário FECHADO — 7 pilares reputacionais, e não um
    ranking de cauda longa como tema ou veículo. Perder um pilar por ele ter
    menos matéria no mês (o `quantos=6` de antes) esconderia justamente o
    pilar menos falado, que é às vezes o próprio problema."""
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    pilares = [
        "Governança", "Eficiência Operacional e Qualidade", "Crescimento e Solidez Financeira",
        "Responsabilidade Social", "Responsabilidade Ambiental", "Prosperidade Compartilhada",
        "Inovação e Tecnologia",
    ]
    # O ÚLTIMO TEM UMA MATÉRIA SÓ — é o que um teto de 6 cortaria primeiro.
    for posicao, atributo in enumerate(pilares):
        for _ in range(len(pilares) - posicao):
            sessao.add(
                Mencao(
                    fonte_id=clipei.id, mes=MES, sentimento="neu",
                    tier="muito_relevante", atributo=atributo,
                )
            )
    sessao.flush()

    dossie = _dossie(sessao)

    assert {linha["rotulo"] for linha in dossie.drivers_e_riscos.dados} == set(pilares)


def test_temas_mais_falados_agrega_por_tema(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    por_rotulo = {linha["rotulo"]: linha for linha in dossie.temas_mais_falados.dados}
    assert por_rotulo["Tarifa"] == {"rotulo": "Tarifa", "positivo": 2, "neutro": 1, "negativo": 0}
    assert por_rotulo["Obras"] == {"rotulo": "Obras", "positivo": 0, "neutro": 1, "negativo": 2}


def test_drivers_e_temas_respeitam_o_filtro(sessao, imprensa_de_junho):
    """Filtrar por Veículo A deixa só "Qualidade"/"Tarifa" nos dois blocos."""
    dossie = _dossie(sessao, veiculo="Veículo A")

    assert [linha["rotulo"] for linha in dossie.drivers_e_riscos.dados] == ["Qualidade"]
    assert [linha["rotulo"] for linha in dossie.temas_mais_falados.dados] == ["Tarifa"]


def test_drivers_e_temas_vazios_na_institucional(sessao):
    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="institucional", mes="2026-06")

    assert dossie.drivers_e_riscos.dados == []
    assert dossie.drivers_e_riscos.ficha.lacunas
    assert dossie.temas_mais_falados.dados == []
    assert dossie.temas_mais_falados.ficha.lacunas


# -- volume por tier, e top/clima dos veículos ------------------------------------


def test_volume_por_tier_e_uma_rosca_com_os_tres_tiers(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    bloco = dossie.volume_por_tier
    assert bloco.tipo == "rosca"
    por_chave = {linha["chave"]: linha["total"] for linha in bloco.dados}
    assert por_chave == {"muito_relevante": 2, "relevante": 2, "menos_relevante": 2}


def test_top_veiculos_ordena_por_volume(sessao, imprensa_de_junho):
    """Os dois veículos têm 3 menções cada — empate desfeito por nome."""
    dossie = _dossie(sessao)

    assert dossie.top_veiculos.tipo == "barras_horizontais"
    assert [linha["rotulo"] for linha in dossie.top_veiculos.dados] == [
        "Veículo A", "Veículo B",
    ]
    assert {linha["valor"] for linha in dossie.top_veiculos.dados} == {3}


def test_veiculos_tier1_conta_so_quem_tem_materia_muito_relevante(sessao, imprensa_de_junho):
    """Veículo A tem duas matérias muito_relevante; Veículo B só tem relevante
    e menos_relevante — a conta de Tier 1 é dele só."""
    dossie = _dossie(sessao)
    kpi = next(k for k in dossie.kpis if k.rotulo == "Veículos Tier 1")
    assert kpi.valor == "1"


def test_veiculos_tier1_respeita_o_mesmo_filtro_da_tela(sessao, imprensa_de_junho):
    """Filtrar por Veículo B — que não tem matéria Tier 1 nenhuma — zera a
    conta: o KPI lê o MESMO recorte que o resto do dossiê, e não a base
    inteira por baixo dele."""
    dossie = _dossie(sessao, veiculo="Veículo B")
    kpi = next(k for k in dossie.kpis if k.rotulo == "Veículos Tier 1")
    assert kpi.valor == "0"


def test_clima_por_veiculos_e_o_saldo_simples_nao_o_ns_ponderado(sessao, imprensa_de_junho):
    """(positivas − negativas) ÷ total × 100 — SEM peso de tier, diferente da
    nota oficial da lente. Veículo A: 2 pos, 1 neu, 0 neg -> +67. Veículo B:
    0 pos, 1 neu, 2 neg -> -67."""
    dossie = _dossie(sessao)

    por_chave = {linha["chave"]: linha["score"] for linha in dossie.clima_por_veiculos.dados}
    assert por_chave == {"Veículo A": 67, "Veículo B": -67}


def test_volume_e_veiculos_vazios_na_institucional(sessao):
    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="institucional", mes="2026-06")

    assert dossie.volume_por_tier.dados == []
    assert dossie.volume_por_tier.ficha.lacunas
    assert dossie.top_veiculos.dados == []
    assert dossie.clima_por_veiculos.dados == []
    assert dossie.clima_por_veiculos.ficha.lacunas


def test_volume_e_veiculos_vazios_no_mercado_MESMO_com_tier_e_veiculo_no_dado(sessao):
    """Restrição de TELA, por hora (pedido do Jones, 2026-10-02) — e não por
    o Mercado não ter tier/veículo de verdade: a migration 0048 define
    `clipei_investidores` como o MESMO clipping da Clipei, recortado por
    público-alvo. Este teste planta `mencao` com tier/veículo reais nessa
    fonte e confere que os quatro blocos saem vazios assim mesmo — provando
    que a restrição é da tela, e não "faltou dado"."""
    clipei_investidores = sessao.scalars(
        select(ScoreFonte).where(ScoreFonte.codigo == "clipei_investidores")
    ).one()
    sessao.add(
        Mencao(
            fonte_id=clipei_investidores.id, mes=MES, sentimento="pos",
            tier="muito_relevante", veiculo="Valor Econômico",
        )
    )
    sessao.flush()

    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="mercado", mes="2026-06")

    assert dossie.volume_por_tier.dados == []
    assert dossie.top_veiculos.dados == []
    assert dossie.clima_por_veiculos.dados == []
    assert dossie.materias_recentes.dados == []


def test_materias_recentes_sobe_o_teto_quando_ha_recorte(sessao):
    """Clicar num veículo do placar de clima precisa mostrar TODAS as
    matérias por trás daquele saldo, não só uma amostra de 5 — ver
    `TETO_DE_MATERIAS_FILTRADO`."""
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    for _ in range(7):
        sessao.add(
            Mencao(fonte_id=clipei.id, mes=MES, sentimento="pos", veiculo="Veículo Único")
        )
    sessao.flush()

    sem_filtro = _dossie(sessao)
    assert len(sem_filtro.materias_recentes.dados) == 5

    com_filtro = _dossie(sessao, veiculo="Veículo Único")
    assert len(com_filtro.materias_recentes.dados) == 7
