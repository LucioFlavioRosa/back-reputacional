"""O Índice de Saúde Reputacional, conferido contra o protótipo.

O QUE ESTE ARQUIVO PROTEGE
--------------------------
Um número que a diretoria vai ler como "a reputação da companhia". Ele não
quebra quando está errado — só mente, e ninguém percebe. Por isso os casos
abaixo usam os DADOS REAIS DE JUNHO/2026 extraídos das planilhas dos
fornecedores (as mesmas constantes do protótipo `Score Executivo Aegea.dc.html`)
e comparam com os valores que o protótipo mostra na tela.

O critério de aceite do `SCORE.md` §7 é este: com os dados de junho e a
calibração padrão, Imprensa dá 70 e o ISR fica em torno de 58.
"""

from __future__ import annotations

import pytest

from app.dominio.erros import RegraViolada
from app.dominio.score import (
    Calibracao,
    Contagem,
    LenteMedida,
    SomasDaFonte,
    calcular_indice,
    faixa_de,
    medir_lente,
    ns,
    para_score,
    peso_do_cargo,
    peso_do_engajamento,
    ponderar,
)

# -- os dados de junho/2026, como as planilhas os entregaram -------------------
#
# Clipei: 1.506 matérias, por tier. Bites: 4.973 posts classificados. Approach
# Social Listening: 1.959 menções. Approach Community Management: 886
# mensagens. CRM: o clima das interações institucionais do mês.

CLIPEI_JUNHO = [
    SomasDaFonte("clipei", "pos", "muito_relevante", mencoes=65),
    SomasDaFonte("clipei", "neu", "muito_relevante", mencoes=64),
    SomasDaFonte("clipei", "neg", "muito_relevante", mencoes=16),
    SomasDaFonte("clipei", "pos", "relevante", mencoes=85),
    SomasDaFonte("clipei", "neu", "relevante", mencoes=43),
    SomasDaFonte("clipei", "neg", "relevante", mencoes=55),
    SomasDaFonte("clipei", "pos", "menos_relevante", mencoes=946),
    SomasDaFonte("clipei", "neu", "menos_relevante", mencoes=80),
    SomasDaFonte("clipei", "neg", "menos_relevante", mencoes=149),
]

#: A lente Mercado é proxy: os veículos Muito Relevante com público
#: investidores, sem ponderação de tier (já são todos do mesmo tier).
MERCADO_JUNHO = [
    SomasDaFonte("clipei_investidores", "pos", "", mencoes=65),
    SomasDaFonte("clipei_investidores", "neu", "", mencoes=64),
    SomasDaFonte("clipei_investidores", "neg", "", mencoes=16),
]

APPROACH_SL_JUNHO = [
    SomasDaFonte("approach_sl", "pos", "", mencoes=707, soma_log=1238, soma_engajamento=20544),
    SomasDaFonte("approach_sl", "neu", "", mencoes=142, soma_log=288, soma_engajamento=25994),
    SomasDaFonte("approach_sl", "neg", "", mencoes=1110, soma_log=1274, soma_engajamento=12716),
]

BITES_JUNHO = [
    SomasDaFonte(
        "bites", "pos", "", mencoes=888, soma_log=1417,
        soma_engajamento=25237, soma_cargo=888,
    ),
    SomasDaFonte(
        "bites", "neu", "", mencoes=1501, soma_log=2245,
        soma_engajamento=43689, soma_cargo=1501,
    ),
    SomasDaFonte(
        "bites", "neg", "", mencoes=2584, soma_log=3714,
        soma_engajamento=107886, soma_cargo=2591,
    ),
]

APPROACH_CM_JUNHO = [
    SomasDaFonte("approach_cm", "pos", "", mencoes=146),
    SomasDaFonte("approach_cm", "neu", "", mencoes=452),
    SomasDaFonte("approach_cm", "neg", "", mencoes=288),
]

CRM_JUNHO = [
    SomasDaFonte("crm", "pos", "", mencoes=6),
    SomasDaFonte("crm", "neu", "", mencoes=4),
    SomasDaFonte("crm", "neg", "", mencoes=2),
]

PADRAO = Calibracao(
    pesos={"imprensa": 30, "mercado": 20, "sociedade": 20, "clientes": 15, "institucional": 15}
)


def _lentes(calibracao: Calibracao) -> list[LenteMedida]:
    """As cinco lentes de junho, com a calibração pedida."""
    return [
        medir_lente(
            codigo="imprensa", nome="Imprensa", peso=calibracao.peso("imprensa", 30),
            somas_por_fonte={"clipei": CLIPEI_JUNHO}, calibracao=calibracao,
        ),
        medir_lente(
            codigo="mercado", nome="Mercado", peso=calibracao.peso("mercado", 20),
            somas_por_fonte={"clipei_investidores": MERCADO_JUNHO}, calibracao=calibracao,
        ),
        medir_lente(
            codigo="sociedade", nome="Sociedade digital", peso=calibracao.peso("sociedade", 20),
            somas_por_fonte={"approach_sl": APPROACH_SL_JUNHO, "bites": BITES_JUNHO},
            calibracao=calibracao,
        ),
        medir_lente(
            codigo="clientes", nome="Clientes", peso=calibracao.peso("clientes", 15),
            somas_por_fonte={"approach_cm": APPROACH_CM_JUNHO}, calibracao=calibracao,
        ),
        medir_lente(
            codigo="institucional", nome="Institucional", peso=calibracao.peso("institucional", 15),
            somas_por_fonte={"crm": CRM_JUNHO}, calibracao=calibracao,
        ),
    ]


# -- a fórmula, nos seus três passos -------------------------------------------


def test_o_saldo_de_sentimento_vai_de_menos_um_a_um():
    assert ns(Contagem(positivo=10, neutro=0, negativo=0)) == 1
    assert ns(Contagem(positivo=0, neutro=0, negativo=10)) == -1
    assert ns(Contagem(positivo=5, neutro=0, negativo=5)) == 0
    assert ns(Contagem(positivo=1, neutro=8, negativo=1)) == 0


def test_lente_sem_mencao_e_SEM_DADO_e_nao_zero():
    """Uma lente que ninguém mediu não é uma lente neutra.

    Entrar como 50 no índice inventaria equilíbrio onde há silêncio — e o ISR
    diria "estável" sobre um mês em que não se olhou.
    """
    assert ns(Contagem()) is None


def test_o_score_e_o_ns_na_escala_de_cem():
    assert para_score(-1) == 0
    assert para_score(0) == 50
    assert para_score(1) == 100


@pytest.mark.parametrize(
    ("score", "faixa"),
    [(92, "Referência"), (70, "Sólido"), (58, "Estável"), (41, "Atenção"), (12, "Crítico")],
)
def test_as_faixas_cobrem_a_escala(score, faixa):
    assert faixa_de(score)[0] == faixa


# -- o critério de aceite do §7 -------------------------------------------------


def test_com_junho_e_a_calibracao_padrao_a_imprensa_da_70():
    """O número que o protótipo mostra, conferido contra a régua 10/5/1.

    A conta: (65·10 + 85·5 + 946·1) positivas contra (16·10 + 55·5 + 149·1)
    negativas, sobre o total ponderado.
    """
    imprensa = _lentes(PADRAO)[0]

    assert imprensa.score == 70
    assert imprensa.fontes == ("clipei",)
    assert not imprensa.estimado


def test_com_junho_e_a_calibracao_padrao_o_isr_fica_em_58():
    """O critério de aceite inteiro: ISR ≈ 58 com os dados de junho."""
    indice = calcular_indice("2026-06", _lentes(PADRAO))

    assert indice.isr == 58
    assert indice.faixa == "Estável"
    assert len(indice.lentes_no_calculo) == 5
    assert indice.lentes_de_fora == ()


def test_a_sociedade_e_a_media_dos_ns_das_duas_fontes():
    """MÉDIA DE NS, e não soma das contagens (§2.4).

    A Bites classifica 4.973 posts e a Approach 1.959: somar as contagens
    faria a Bites decidir a lente sozinha. Média de NS dá voz igual às duas
    leituras da mesma realidade.
    """
    sociedade = _lentes(PADRAO)[2]

    ns_sl = ns(ponderar(APPROACH_SL_JUNHO, PADRAO))
    ns_bites = ns(ponderar(BITES_JUNHO, PADRAO))
    assert sociedade.ns == pytest.approx((ns_sl + ns_bites) / 2)
    assert sociedade.fontes == ("approach_sl", "bites")


# -- a calibração muda o número, e é para isso que ela existe -------------------


def test_a_regua_de_tier_muda_a_imprensa():
    """Sem ponderação, as 946 positivas de veículo local pesam igual às 65 de
    Muito Relevante — e a imprensa sobe. É a régua que traduz "relevância"."""
    sem_ponderacao = Calibracao(pesos=PADRAO.pesos, regua_tier="igual")

    assert _lentes(PADRAO)[0].score == 70
    assert _lentes(sem_ponderacao)[0].score > 70


def test_so_tier_1_ignora_o_resto_da_imprensa():
    """`so_tier1` zera o peso dos outros dois tiers: sobram 65/64/16."""
    so_tier1 = Calibracao(pesos=PADRAO.pesos, regua_tier="so_tier1")

    esperado = para_score(ns(Contagem(positivo=65, neutro=64, negativo=16)))
    assert _lentes(so_tier1)[0].score == esperado


def test_a_regua_de_engajamento_muda_a_sociedade():
    """Pelo engajamento bruto, um viral decide o mês — e o número muda."""
    por_contagem = _lentes(PADRAO)[2].score
    por_engajamento = _lentes(
        Calibracao(pesos=PADRAO.pesos, regua_engajamento="bruto")
    )[2].score

    assert por_contagem != por_engajamento


def test_desligar_as_duas_fontes_tira_a_sociedade_e_redistribui_os_pesos():
    """§7: "Desligar Approach SL e Bites remove Sociedade e redistribui pesos".

    O ISR NÃO PODE CAIR POR FALTA DE DADO. Se o peso 20 da Sociedade
    continuasse no denominador, o índice desabaria e pareceria queda de
    reputação, quando foi só uma fonte desligada.
    """
    sem_sociedade = Calibracao(
        pesos=PADRAO.pesos, fontes_desligadas=frozenset({"approach_sl", "bites"})
    )
    indice = calcular_indice("2026-06", _lentes(sem_sociedade))

    sociedade = next(lente for lente in indice.lentes if lente.codigo == "sociedade")
    assert sociedade.score is None
    assert sociedade.ausencia == "todas as fontes desta lente estão desligadas"
    assert len(indice.lentes_no_calculo) == 4
    # A sociedade é a pior lente de junho; sem ela, o índice sobe.
    assert indice.isr is not None and indice.isr > 58


def test_desligar_uma_das_duas_deixa_a_lente_com_a_outra():
    so_approach = Calibracao(pesos=PADRAO.pesos, fontes_desligadas=frozenset({"bites"}))
    sociedade = _lentes(so_approach)[2]

    assert sociedade.fontes == ("approach_sl",)
    assert sociedade.ns == pytest.approx(ns(ponderar(APPROACH_SL_JUNHO, PADRAO)))


def test_peso_zero_numa_lente_a_tira_do_denominador():
    """Peso 0 é "não quero esta lente no índice", e não "vale zero"."""
    sem_clientes = Calibracao(pesos={**PADRAO.pesos, "clientes": 0})
    indice = calcular_indice("2026-06", _lentes(sem_clientes))

    assert indice.isr != 58


def test_regua_invalida_e_recusada_dizendo_quais_valem():
    with pytest.raises(RegraViolada, match="Régua de tier inválida"):
        Calibracao(regua_tier="chute")
    with pytest.raises(RegraViolada, match="Régua de engajamento inválida"):
        Calibracao(regua_engajamento="chute")


def test_peso_fora_da_faixa_e_recusado():
    """§3: de 0 a 60, de 5 em 5. A faixa é o que impede uma lente de valer
    mais que todas as outras somadas por engano de digitação."""
    with pytest.raises(RegraViolada, match="fora da faixa"):
        Calibracao(pesos={"imprensa": 90})


# -- a estimativa -------------------------------------------------------------


def test_a_estimativa_entra_so_onde_nao_ha_medicao():
    """Meses sem export usam o resumo semestral, MARCADO como estimado (§8)."""
    lente = medir_lente(
        codigo="imprensa", nome="Imprensa", peso=30,
        somas_por_fonte={"clipei": []}, calibracao=PADRAO, estimativa=0.45,
    )

    assert lente.estimado
    assert lente.score == para_score(0.45)


def test_a_estimativa_vale_para_o_mes_que_nao_teve_export_nenhum():
    """Sem export, a lente não chega com fonte alguma — e não com uma fonte
    vazia. É o caso real da Imprensa de janeiro a maio, que não tem base da
    Clipei: sem isto, o mês inteiro ficaria sem Imprensa com a estimativa
    gravada e ignorada."""
    lente = medir_lente(
        codigo="imprensa", nome="Imprensa", peso=30,
        somas_por_fonte={}, calibracao=PADRAO, estimativa=0.45,
    )

    assert lente.estimado
    assert lente.score == para_score(0.45)


def test_desligar_toda_fonte_nao_faz_a_lente_cair_na_estimativa():
    """Desligar é ato deliberado: voltar pela estimativa devolveria justamente
    o número que a coordenação tirou do cálculo."""
    calibracao = Calibracao(pesos=PADRAO.pesos, fontes_desligadas=frozenset({"clipei"}))
    lente = medir_lente(
        codigo="imprensa", nome="Imprensa", peso=30,
        somas_por_fonte={"clipei": CLIPEI_JUNHO}, calibracao=calibracao,
        estimativa=0.45,
    )

    assert lente.score is None
    assert not lente.estimado
    assert lente.ausencia == "todas as fontes desta lente estão desligadas"


def test_havendo_medicao_a_estimativa_e_ignorada():
    """Medido ganha de suposto, sempre."""
    lente = medir_lente(
        codigo="imprensa", nome="Imprensa", peso=30,
        somas_por_fonte={"clipei": CLIPEI_JUNHO}, calibracao=PADRAO, estimativa=-0.9,
    )

    assert not lente.estimado
    assert lente.score == 70


def test_mes_sem_nenhuma_lente_medida_nao_inventa_indice():
    indice = calcular_indice("2026-01", [
        LenteMedida(codigo="imprensa", nome="Imprensa", peso=30, ns=None, score=None),
    ])

    assert indice.isr is None
    assert indice.faixa == "Sem dado"


# -- as réguas de ponderação em si ---------------------------------------------


def test_o_log_comprime_a_cauda_do_engajamento():
    """Um post com 3.000 interações vale ~4,5, e um com 1 vale ~1,3 — sem
    isso, um viral sozinho decide o mês."""
    assert peso_do_engajamento(0) == 1
    assert peso_do_engajamento(3000) == pytest.approx(4.477, abs=0.001)
    assert peso_do_engajamento(1) == pytest.approx(1.301, abs=0.001)


def test_engajamento_ausente_ou_negativo_vale_o_piso():
    assert peso_do_engajamento(None) == 1
    assert peso_do_engajamento(-5) == 1


def test_o_cargo_pesa_a_voz_de_quem_postou():
    assert peso_do_cargo("Ministro") == 5
    assert peso_do_cargo("deputado_federal") == 4
    assert peso_do_cargo("Vereador") == 2
    assert peso_do_cargo("cidadão") == 1
    assert peso_do_cargo(None) == 1
