"""A Consulta em profundidade, sem banco: a árvore, os arredondamentos e as frases.

O QUE ESTE ARQUIVO PROVA É O CONTRATO COM A TELA. O front confere com a
calculadora o que o drill mostra: os filhos somam o pai, os pilares somam
`nota − 50`, o sentimento soma 100, cada matéria vale `50 × peso ÷ D`. Um número
que não fecha numa reunião de diretoria custa a confiança no painel inteiro — e
é muito mais barato prová-lo aqui, com meia dúzia de menções na mão, do que
descobri-lo na tela com o dado real.

A TAXONOMIA DOS TESTES É UM RECORTE DA v4: dois pilares, três temas e três
subtemas, com os nomes de verdade onde o nome importa ("Tarifa" é tema N2 e não
subtema; "Prosperidade Compartilhada" chega como "7. Prosperidade
Compartilhada" no export real).
"""

from __future__ import annotations

import calendar
from datetime import date

import pytest

from app.dominio import frases_da_consulta as frases
from app.dominio.consulta_profundidade import (
    NEUTRAS_NA_AMOSTRA,
    SEM_PILAR,
    SEM_SUBTEMA,
    SEM_TEMA,
    TETO_DA_AMOSTRA,
    GrupoDaConsulta,
    LenteDaConsulta,
    MencaoDaConsulta,
    MesDaLente,
    PilarDaTaxonomia,
    SubtemaDaTaxonomia,
    Taxonomia,
    TemaDaTaxonomia,
    amostra,
    distribuicao,
    janela_de_sete_dias,
    maior_resto,
    montar_consulta,
    por_dia,
    sem_prefixo,
)
from app.dominio.score import Calibracao, ns, para_score, peso_da_mencao
from app.dominio.score import Contagem as ContagemDaNota

AGO = date(2026, 8, 1)
JUL = date(2026, 7, 1)
MESES = [date(2026, m, 1) for m in range(3, 9)]

T1, T2, T3 = "muito_relevante", "relevante", "menos_relevante"


def _taxonomia() -> Taxonomia:
    return Taxonomia(
        pilares=[
            PilarDaTaxonomia(id=5, codigo="eficiencia_operacional_e_qualidade",
                             nome="Eficiência Operacional e Qualidade"),
            PilarDaTaxonomia(id=6, codigo="crescimento_e_solidez_financeira",
                             nome="Crescimento e Solidez Financeira"),
            PilarDaTaxonomia(id=11, codigo="prosperidade_compartilhada",
                             nome="Prosperidade Compartilhada"),
        ],
        temas=[
            TemaDaTaxonomia(id=27, codigo="qualidade_da_agua", nome="Qualidade da água",
                            pilar_id=5),
            TemaDaTaxonomia(id=30, codigo="atendimento", nome="Atendimento", pilar_id=5),
            TemaDaTaxonomia(id=33, codigo="tarifa", nome="Tarifa", pilar_id=6),
            TemaDaTaxonomia(id=57, codigo="universalizacao", nome="Universalização",
                            pilar_id=11),
        ],
        subtemas=[
            SubtemaDaTaxonomia(id=93, nome="Atendimento ao cliente", tema_id=30),
            SubtemaDaTaxonomia(id=94, nome="Reclamações no Procon", tema_id=30),
            SubtemaDaTaxonomia(id=23, nome="Universalização e metas de cobertura",
                               tema_id=57),
        ],
    )


_contador = iter(range(10_000))


def _m(
    sentimento: str,
    tier: str | None = T2,
    *,
    mes: date = AGO,
    dia: int | None = 10,
    **campos,
) -> MencaoDaConsulta:
    """Uma menção mínima. O id é sequencial para a ordem dos testes ser estável."""
    return MencaoDaConsulta(
        id=f"m{next(_contador):04d}",
        mes=mes,
        sentimento=sentimento,
        tier=tier,
        data=date(mes.year, mes.month, dia) if dia else None,
        **campos,
    )


def _medidas(mencoes, calibracao=None) -> dict[date, MesDaLente]:
    """O D e a nota de cada mês COMO `score_mes_fonte` os daria: a soma dos
    mesmos pesos sobre as mesmas menções. É a condição de fechamento."""
    calibracao = calibracao or Calibracao()
    saida = {}
    for mes in MESES:
        do_mes = [m for m in mencoes if m.mes == mes]
        if not do_mes:
            continue
        p = n = u = 0.0
        for m in do_mes:
            w = peso_da_mencao(m.tier, m.cargo, m.engajamento, calibracao, "n")
            if m.sentimento == "pos":
                p += w
            elif m.sentimento == "neg":
                n += w
            else:
                u += w
        contagem = ContagemDaNota(positivo=p, neutro=u, negativo=n)
        valor = ns(contagem)
        saida[mes] = MesDaLente(
            mes=mes,
            regua="n",
            denominador=p + u + n,
            ns=valor,
            nota=para_score(valor) if valor is not None else None,
        )
    return saida


def _consulta(mencoes, *, codigo="imprensa", calibracao=None, ve_diretorio=True) -> dict:
    calibracao = calibracao or Calibracao()
    return montar_consulta(
        lente=LenteDaConsulta(codigo=codigo, nome=codigo.capitalize(), peso=0.3),
        mes=AGO,
        meses=MESES,
        mencoes=mencoes,
        medidas=_medidas(mencoes, calibracao),
        taxonomia=_taxonomia(),
        calibracao=calibracao,
        ve_diretorio=ve_diretorio,
    )


def _mes_misturado() -> list[MencaoDaConsulta]:
    """Um agosto com os quatro níveis e os três nós de fechamento."""
    return [
        # N3 pela Subcategoria (tema_texto == subtema): Atendimento ao cliente.
        _m("neg", T1, tema_texto="Atendimento ao cliente",
           atributo="Crescimento e Solidez Financeira", dia=3),
        _m("neg", T2, tema_texto="atendimento  AO cliente", dia=4),
        _m("pos", T3, tema_texto="Atendimento ao cliente", dia=12),
        _m("neu", T2, tema_texto="Atendimento ao cliente", dia=13),
        # Outro N3 do mesmo tema, pelo campo subtema.
        _m("pos", T1, subtema="Reclamações no Procon", dia=20),
        # N2 sem N3: "Tarifa" é tema, então o subtema fica em sem-subtema.
        _m("neg", T2, tema_texto="Tarifa", dia=21),
        _m("pos", T3, tema_texto="Qualidade da água", dia=22),
        # N1 só pelo atributo do export real, com o prefixo numérico.
        _m("neg", T3, tema_texto="Obras e investimentos",
           atributo="7. Prosperidade Compartilhada", dia=23),
        # Nada casa: sem-pilar.
        _m("neg", T1, tema_texto="Sustentabilidade", atributo="Outra coisa", dia=24),
        # Sem tier: conta no volume e no impacto, fica fora da amostra.
        _m("neu", None, tema_texto="Atendimento ao cliente", dia=25),
        # Julho, para o impactoMesAnterior.
        _m("neg", T1, mes=JUL, tema_texto="Atendimento ao cliente"),
        _m("pos", T2, mes=JUL, tema_texto="Tarifa"),
    ]


# -- arredondamento ------------------------------------------------------------------


def test_o_maior_resto_soma_o_alvo_e_nao_se_afasta_mais_de_uma_casa():
    exatos = [1.04, 1.04, 1.04, -0.12]
    arredondados = maior_resto(exatos, round(sum(exatos), 1))
    assert round(sum(arredondados), 1) == round(sum(exatos), 1)
    assert all(abs(a - e) < 0.1 + 1e-9 for a, e in zip(arredondados, exatos, strict=True))


def test_o_maior_resto_da_a_unidade_a_quem_perdeu_mais_no_corte():
    # 0,33 + 0,33 + 0,34 = 1,0; cada um por si daria 0,3 + 0,3 + 0,3 = 0,9.
    assert maior_resto([0.33, 0.33, 0.34], 1.0) == [0.3, 0.3, 0.4]


def test_o_maior_resto_aguenta_negativos_e_ruido_binario():
    exatos = [-2.25, -0.35, 0.1 + 0.2]
    arredondados = maior_resto(exatos, round(sum(exatos), 1))
    assert round(sum(arredondados), 1) == round(sum(exatos), 1)


def test_o_sentimento_soma_100_e_volume_zero_vale_zero():
    for pos, neu, neg in [(1, 1, 1), (2, 1, 0), (7, 0, 3), (1, 5, 13), (0, 0, 1)]:
        dist = distribuicao(pos, neu, neg)
        assert sum(dist.values()) == 100
    assert distribuicao(0, 0, 0) == {"pos": 0, "neu": 0, "neg": 0}


# -- resolução de cada menção --------------------------------------------------------


def test_a_cadeia_pelo_tema_id_vem_primeiro():
    v = _taxonomia().resolver(tema_id=93, tema_texto="Tarifa", atributo="Governança")
    assert (v.pilar, v.tema, v.subtema) == (
        "eficiencia_operacional_e_qualidade", "atendimento", "atendimento_ao_cliente"
    )


def test_a_subcategoria_casa_com_o_subtema_sem_acento_caixa_ou_espaco_extra():
    v = _taxonomia().resolver(tema_texto="  UNIVERSALIZACAO e metas   de cobertura ")
    assert (v.pilar, v.tema, v.subtema) == (
        "prosperidade_compartilhada", "universalizacao", "universalizacao_e_metas_de_cobertura"
    )


def test_o_campo_subtema_vale_quando_o_tema_texto_nao_casa():
    v = _taxonomia().resolver(tema_texto="Sustentabilidade", subtema="Reclamações no Procon")
    assert v.subtema == "reclamacoes_no_procon"


def test_tema_texto_igual_a_um_tema_estrategico_deixa_o_subtema_em_aberto():
    # "Tarifa" tem um homônimo LEGADO inativo no cadastro de subtemas (id 2); como
    # a taxonomia só carrega a cadeia ativa, ela cai no N2 33, e não num N3 órfão.
    v = _taxonomia().resolver(tema_texto="Tarifa")
    assert (v.pilar, v.tema, v.subtema) == ("crescimento_e_solidez_financeira", "tarifa",
                                            SEM_SUBTEMA)


def test_sem_n2_o_pilar_vem_do_atributo_sem_o_prefixo_numerico():
    v = _taxonomia().resolver(tema_texto="Obras", atributo="7. Prosperidade Compartilhada")
    assert (v.pilar, v.tema, v.subtema) == ("prosperidade_compartilhada", SEM_TEMA, "")
    assert sem_prefixo("7. Prosperidade Compartilhada") == "Prosperidade Compartilhada"
    assert sem_prefixo("12) Governança") == "Governança"


def test_sem_atributo_vale_a_regra_antiga_do_tema_texto_igual_ao_pilar():
    v = _taxonomia().resolver(tema_texto="crescimento e solidez financeira")
    assert (v.pilar, v.tema) == ("crescimento_e_solidez_financeira", SEM_TEMA)


def test_nada_casa_e_a_mencao_fica_sem_pilar():
    v = _taxonomia().resolver(tema_texto="Sustentabilidade", atributo="Outra coisa")
    assert v.caminho == (SEM_PILAR,)


def test_a_cadeia_vence_o_atributo_e_a_divergencia_e_marcada():
    v = _taxonomia().resolver(tema_texto="Tarifa", atributo="1. Eficiência Operacional e Qualidade")
    assert v.pilar == "crescimento_e_solidez_financeira"
    assert v.divergente
    concorda = _taxonomia().resolver(tema_texto="Tarifa",
                                     atributo="Crescimento e Solidez Financeira")
    assert not concorda.divergente


def test_o_slug_do_subtema_que_colide_leva_o_id():
    tax = Taxonomia(
        pilares=[PilarDaTaxonomia(id=1, codigo="p", nome="P")],
        temas=[TemaDaTaxonomia(id=2, codigo="t", nome="T", pilar_id=1)],
        subtemas=[
            SubtemaDaTaxonomia(id=10, nome="Água e esgoto", tema_id=2),
            SubtemaDaTaxonomia(id=11, nome="Agua, esgoto", tema_id=2),
        ],
    )
    assert tax.slug_do_subtema == {10: "agua_e_esgoto", 11: "agua_esgoto"}
    colide = Taxonomia(
        pilares=tax.pilares,
        temas=tax.temas,
        subtemas=[
            SubtemaDaTaxonomia(id=10, nome="Água/esgoto", tema_id=2),
            SubtemaDaTaxonomia(id=11, nome="Agua esgoto", tema_id=2),
        ],
    )
    assert colide.slug_do_subtema == {10: "agua_esgoto", 11: "agua_esgoto_11"}


# -- a árvore -------------------------------------------------------------------------


def _soma(nos) -> float:
    return round(sum(n["impacto"] for n in nos), 1)


def test_os_pilares_somam_50_ns_e_os_filhos_somam_o_pai_em_toda_a_descida():
    mencoes = _mes_misturado()
    saida = _consulta(mencoes)
    lente = saida["lentes"][0]
    conferencia = saida["meta"]["conferencia"]

    assert conferencia["fecha"] is True
    assert conferencia["somaPilares"] == pytest.approx(conferencia["ns50"], abs=1e-4)
    assert _soma(lente["pilares"]) == round(conferencia["ns50"], 1)
    # A nota é arredondada; a soma exata fica a menos de meio ponto de nota − 50.
    assert abs(conferencia["somaPilares"] - (lente["nota"] - 50)) <= 0.5

    for pilar in lente["pilares"]:
        if "filhos" in pilar:
            assert _soma(pilar["filhos"]) == pilar["impacto"]
            assert sum(t["volume"] for t in pilar["filhos"]) == pilar["volume"]
            for tema in pilar["filhos"]:
                if "filhos" in tema:
                    assert _soma(tema["filhos"]) == tema["impacto"]
                    assert sum(s["volume"] for s in tema["filhos"]) == tema["volume"]
        for no in [pilar, *pilar.get("filhos", [])]:
            if no["volume"]:
                assert sum(no["sentimento"].values()) == 100


def test_os_nos_de_fechamento_aparecem_com_volume_e_nunca_abrem():
    lente = _consulta(_mes_misturado())["lentes"][0]
    pilares = {p["id"]: p for p in lente["pilares"]}

    assert pilares[SEM_PILAR]["nome"] == "Sem pilar identificado"
    assert pilares[SEM_PILAR]["volume"] == 1
    assert lente["pilares"][-1]["id"] == SEM_PILAR  # sempre por último

    prosperidade = pilares["prosperidade_compartilhada"]
    assert prosperidade["volume"] == 1
    # Só sem-tema abaixo: o pilar recebe volume e impacto, mas não abre.
    assert "filhos" not in prosperidade and "nivel2" not in prosperidade

    eficiencia = pilares["eficiencia_operacional_e_qualidade"]
    assert eficiencia["nivel2"]["destaque"]["temaId"] != SEM_TEMA
    financeira = pilares["crescimento_e_solidez_financeira"]
    tarifa = next(t for t in financeira["filhos"] if t["id"] == "tarifa")
    # Tarifa só tem sem-subtema: não abre o Nível 3.
    assert "filhos" not in tarifa and "nivel3" not in tarifa

    for pilar in lente["pilares"]:
        for no in [pilar, *pilar.get("filhos", [])]:
            for filho in no.get("filhos", []):
                if filho["id"].startswith("sem-"):
                    assert not {"filhos", "nivel2", "nivel3", "nivel4"} & set(filho)
    # NAS FRASES nunca; na linha numérica do "o que mudou" sim, como na tabela —
    # sem ela a variação dos pilares não fecharia com a da nota.
    textos = [lente["tabelaPilares"]["titulo"], lente["tabelaPilares"]["subtitulo"]]
    for cartao in lente["cartoesLaterais"]:
        textos += [cartao.get("titulo", ""), cartao.get("nota", ""), cartao.get("texto", "")]
    for pilar in lente["pilares"]:
        nivel2 = pilar.get("nivel2", {})
        textos += [nivel2.get("leitura", ""), nivel2.get("tituloTabela", "")]
    assert not any("Sem pilar" in t or "Sem tema" in t or "Sem subtema" in t for t in textos)


def test_sem_mencao_nao_ha_no_de_fechamento():
    so_identificadas = [_m("neg", T1, tema_texto="Atendimento ao cliente")]
    lente = _consulta(so_identificadas)["lentes"][0]
    ids = [p["id"] for p in lente["pilares"]]
    assert SEM_PILAR not in ids
    # Os 3 pilares ativos entram sempre, mesmo os de volume zero.
    assert ids == [
        "eficiencia_operacional_e_qualidade",
        "crescimento_e_solidez_financeira",
        "prosperidade_compartilhada",
    ]
    zerado = lente["pilares"][2]
    assert (zerado["volume"], zerado["impacto"]) == (0, 0.0)
    assert zerado["sentimento"] == {"pos": 0, "neu": 0, "neg": 0}


def test_mes_sem_mencao_volta_vazio_e_sem_erro():
    saida = _consulta([_m("neg", T1, mes=JUL, tema_texto="Tarifa")])
    lente = saida["lentes"][0]
    assert saida["meta"]["vazio"] is True
    assert lente["pilares"] == [] and lente["cartoesLaterais"] == []
    assert lente["nota"] is None and lente["volumeTotal"] == 0
    assert lente["tabelaPilares"]["titulo"] == "Pilares da Imprensa em agosto"


def test_o_impacto_do_mes_anterior_usa_o_d_daquele_mes():
    lente = _consulta(_mes_misturado())["lentes"][0]
    eficiencia = next(p for p in lente["pilares"]
                      if p["id"] == "eficiencia_operacional_e_qualidade")
    # Julho: −10 (T1 neg) e +5 (T2 pos) com D = 15 → só o −10 é deste pilar.
    assert eficiencia["impactoMesAnterior"] == round(50 * -10 / 15, 1)
    atendimento = next(t for t in eficiencia["filhos"] if t["id"] == "atendimento")
    assert atendimento["impactoMesAnterior"] == round(50 * -10 / 15, 1)
    # Julho teve matéria, mas nenhuma de Qualidade da água: o anterior é 0,0 —
    # a mesma regra do pilar e a mesma da evolução, que mostra 0,0 naquele mês.
    qualidade = next(t for t in eficiencia["filhos"] if t["id"] == "qualidade_da_agua")
    assert qualidade["impactoMesAnterior"] == 0.0
    sub = next(s for s in atendimento["filhos"] if s["id"] == "reclamacoes_no_procon")
    assert sub["impactoMesAnterior"] == 0.0


def test_sem_base_no_mes_anterior_o_campo_some_nos_tres_niveis():
    so_agosto = [m for m in _mes_misturado() if m.mes == AGO]
    lente = _consulta(so_agosto)["lentes"][0]
    for pilar in lente["pilares"]:
        assert "impactoMesAnterior" not in pilar
        for tema in pilar.get("filhos", []):
            assert "impactoMesAnterior" not in tema
            for sub in tema.get("filhos", []):
                assert "impactoMesAnterior" not in sub


# -- o item e a amostra ---------------------------------------------------------------


def _subtema(lente: dict, subtema: str) -> dict:
    for pilar in lente["pilares"]:
        for tema in pilar.get("filhos", []):
            for sub in tema.get("filhos", []):
                if sub["id"] == subtema:
                    return sub
    raise AssertionError(subtema)


def test_o_impacto_da_materia_e_50_vezes_o_peso_sobre_d():
    mencoes = _mes_misturado()
    d = _medidas(mencoes)[AGO].denominador
    lente = _consulta(mencoes)["lentes"][0]
    sub = _subtema(lente, "atendimento_ao_cliente")
    por_tier = {(i["tier"], i["sentimento"]): i["impacto"] for i in sub["nivel4"]["itens"]}
    assert por_tier[("Tier 1", "negativo")] == round(-50 * 10 / d, 2)
    assert por_tier[("Tier 3", "positivo")] == round(50 * 1 / d, 2)
    assert por_tier[("Tier 2", "neutro")] == 0.0
    # A menção sem tier entrou no volume (5), mas não na amostra (4).
    assert sub["volume"] == 5 and len(sub["nivel4"]["itens"]) == 4
    assert sub["contagens"] == {"pos": 1, "neu": 2, "neg": 2}
    assert sub["tier1"] == 1
    item = sub["nivel4"]["itens"][0]
    assert item["titulo"] == "(sem título na planilha)"
    assert (item["trecho"], item["url"], item["jornalista"]) == ("", None, "")
    assert item["concessionaria"] == "Não informada" and item["uf"] == "Não informada"


def test_na_regua_so_tier1_a_materia_de_tier_2_vale_zero():
    calibracao = Calibracao(regua_tier="so_tier1")
    mencoes = [
        _m("neg", T1, tema_texto="Atendimento ao cliente"),
        _m("neg", T2, tema_texto="Atendimento ao cliente"),
    ]
    saida = _consulta(mencoes, calibracao=calibracao)
    itens = _subtema(saida["lentes"][0], "atendimento_ao_cliente")["nivel4"]["itens"]
    assert {i["tier"]: i["impacto"] for i in itens} == {"Tier 1": -50.0, "Tier 2": 0.0}
    assert saida["pesoTier"] == {"Tier 1": 1, "Tier 2": 0, "Tier 3": 0}


def _item(id_: str, sentimento: str, impacto: float, dia: int = 10) -> dict:
    return {"id": id_, "sentimento": sentimento, "impacto": impacto,
            "data": f"2026-08-{dia:02d}"}


def test_a_amostra_tem_no_maximo_20_e_as_tres_abas_quando_ha_o_que_mostrar():
    negativas = [_item(f"n{i:02d}", "negativo", -1.0 - i / 100) for i in range(30)]
    neutras = [_item(f"u{i:02d}", "neutro", 0.0, dia=1 + i) for i in range(10)]
    positiva = [_item("p00", "positivo", 0.01)]
    escolhidas = amostra([*negativas, *neutras, *positiva])
    assert len(escolhidas) == TETO_DA_AMOSTRA
    sentimentos = [i["sentimento"] for i in escolhidas]
    assert sentimentos.count("neutro") == NEUTRAS_NA_AMOSTRA
    assert "positivo" in sentimentos and "negativo" in sentimentos
    # As neutras são as mais recentes.
    assert {i["id"] for i in escolhidas if i["sentimento"] == "neutro"} == {
        "u09", "u08", "u07", "u06"
    }
    # E a ordem é por |impacto|.
    assert escolhidas[0]["id"] == "n29"


def test_a_amostra_pequena_vai_inteira():
    itens = [_item("a", "negativo", -1.0), _item("b", "neutro", 0.0)]
    assert {i["id"] for i in amostra(itens)} == {"a", "b"}


# -- por dia --------------------------------------------------------------------------


def test_por_dia_tem_os_dias_do_mes_e_negativas_nunca_passam_do_total():
    fev = date(2026, 2, 1)
    mencoes = [
        _m("neg", mes=fev, dia=27),
        _m("pos", mes=fev, dia=28),
        _m("neg", mes=fev, dia=None),  # sem data: cai no dia 1
    ]
    dias = por_dia(mencoes, fev)
    assert len(dias["total"]) == calendar.monthrange(2026, 2)[1] == 28
    assert dias["total"][0] == 1 and dias["total"][26] == 1 and dias["total"][27] == 1
    assert all(n <= t for n, t in zip(dias["negativas"], dias["total"], strict=True))
    assert len(por_dia([], AGO)["total"]) == 31


def test_a_janela_de_sete_dias_e_a_de_mais_materias_em_base_1():
    total = [0] * 31
    for dia in range(12, 19):
        total[dia - 1] = 5
    total[0] = 3
    assert janela_de_sete_dias(total) == (12, 18)
    assert janela_de_sete_dias([0] * 31) == (1, 7)


# -- cartões e cabeçalho ---------------------------------------------------------------


def test_imprensa_tem_drill_e_historia_mercado_nao_tem_drill_e_tem_divergentes():
    imprensa = _consulta(_mes_misturado())["lentes"][0]
    assert imprensa["drill"] is True
    assert [c["tipo"] for c in imprensa["cartoesLaterais"]] == ["oQueMudou", "historia"]
    historia = imprensa["cartoesLaterais"][1]
    assert historia["destino"]["subtema"] == "atendimento_ao_cliente"
    assert historia["itemId"] in {
        i["id"] for i in _subtema(imprensa, "atendimento_ao_cliente")["nivel4"]["itens"]
    }

    mercado = _consulta(_mes_misturado(), codigo="mercado")["lentes"][0]
    assert mercado["drill"] is False
    assert mercado["publico"] == "Investidores e rating"
    assert [c["tipo"] for c in mercado["cartoesLaterais"]] == ["oQueMudou", "divergentes"]
    assert mercado["cartoesLaterais"][1]["rotulo"] == "Temas do Mercado"


def test_o_que_mudou_vai_da_nota_anterior_para_a_atual():
    mencoes = _mes_misturado()
    medidas = _medidas(mencoes)
    cartao = _consulta(mencoes)["lentes"][0]["cartoesLaterais"][0]
    assert (cartao["de"], cartao["para"]) == (medidas[JUL].nota, medidas[AGO].nota)
    valores = [linha["valor"] for linha in cartao["linhas"]]
    assert valores == sorted(valores)


def test_o_cabecalho_e_os_meses():
    saida = _consulta(_mes_misturado())
    meta = saida["meta"]
    assert meta["versao"] == "api-1"
    assert (meta["mesReferencia"], meta["rotuloMes"], meta["mesAnterior"]) == (
        "2026-08", "Agosto de 2026", "julho"
    )
    assert meta["meses"] == ["mar/26", "abr/26", "mai/26", "jun/26", "jul/26", "ago/26"]
    assert meta["aviso"] == "" and meta["dataCorte"] == "2026-08-25"
    assert meta["conferencia"]["semVinculo"] == {"pilar": 1, "tema": 1, "subtema": 2}
    assert meta["conferencia"]["divergenciasDePilar"] == 1
    assert [f["id"] for f in saida["faixas"]] == [
        "referencia", "solido", "estavel", "atencao", "critico"
    ]
    assert saida["pesoTier"] == {"Tier 1": 10, "Tier 2": 5, "Tier 3": 1}
    lente = saida["lentes"][0]
    assert len(lente["serie"]) == 6 and lente["serie"][-1] == lente["nota"]
    assert lente["kpis"] == [] and lente["leitura"] == ""


def test_sem_acesso_ao_diretorio_o_jornalista_nao_sai():
    mencoes = [_m("neg", T1, tema_texto="Atendimento ao cliente", autor="Fulana")]
    aberto = _consulta(mencoes)["lentes"][0]
    fechado = _consulta(mencoes, ve_diretorio=False)["lentes"][0]

    def jornalistas(lente):
        tema = lente["pilares"][0]["filhos"][0]
        return tema["nivel3"]["destaque"]["jornalistas"]["linhas"]

    assert [j["nome"] for j in jornalistas(aberto)] == ["Fulana"]
    assert jornalistas(fechado) == []
    item = _subtema(fechado, "atendimento_ao_cliente")["nivel4"]["itens"][0]
    assert item["jornalista"] == ""


# -- frases ---------------------------------------------------------------------------


def test_numeros_em_pt_br_com_o_menos_tipografico():
    assert frases.numero(-7.44) == "−7,4"
    assert frases.numero(-0.04) == "0,0"
    assert frases.com_sinal(2.0) == "+2,0"
    assert frases.numero(4.069, 2) == "4,07"


def test_ponto_no_singular_abaixo_de_2_e_plural_a_partir_de_2():
    assert frases.pontos(1.94) == "ponto"
    assert frases.pontos(-1.96) == "pontos"
    assert frases.pontos(2.0) == "pontos"
    leitura = frases.leitura_do_pilar(
        pilar="Governança", impacto=-1.4, lente_contraida="da Imprensa", mes="agosto",
        mes_anterior="julho", impacto_anterior=None, destaque=None, concentracao=None,
        unico_oposto=None,
    )
    assert leitura == "Governança tirou 1,4 ponto da nota da Imprensa em agosto."
    positiva = frases.leitura_do_pilar(
        pilar="Governança", impacto=2.0, lente_contraida="do Mercado", mes="agosto",
        mes_anterior="julho", impacto_anterior=None, destaque=None, concentracao=None,
        unico_oposto=None,
    )
    assert positiva == "Governança pôs 2,0 pontos na nota do Mercado em agosto."


def test_a_fatia_so_e_dita_com_o_mesmo_sinal_todo_relevante_e_ate_100():
    assert frases.pct(-1.0, -2.0) == 50
    assert frases.pct(-1.0, 0.2) is None
    assert frases.pct(0.01, 0.05) is None
    assert frases.pct(-5.7, -3.7) is None


def test_o_titulo_dos_pilares_cobre_os_casos_e_cai_no_neutro():
    lente, mes = "da Imprensa", "agosto"
    misto = frases.titulo_da_tabela_de_pilares([("A", -3.0), ("B", 1.2)], lente, mes)
    assert misto == "A é o que mais pressiona (−3,0); B é o que mais sustenta (+1,2)"
    concentrado = frases.titulo_da_tabela_de_pilares(
        [("A", -3.0), ("B", -2.0), ("C", -0.5), ("D", 1.0)], lente, mes
    )
    assert concentrado.startswith("A e B tiram 5,0 pontos")
    so_negativos = frases.titulo_da_tabela_de_pilares([("A", -3.0), ("B", -1.0)], lente, mes)
    assert so_negativos.endswith("A responde por 75% da perda")
    so_positivos = frases.titulo_da_tabela_de_pilares([("A", 1.0), ("B", 1.0)], lente, mes)
    assert so_positivos.endswith("A responde por 50% do ganho")
    assert frases.titulo_da_tabela_de_pilares([("A", 0.0)], lente, mes) == (
        "Pilares da Imprensa em agosto"
    )


def test_as_frases_dos_niveis_tem_fallback_neutro():
    assert frases.titulo_da_tabela_de_filhos(
        destaque="X", impacto_do_destaque=0.0, impacto_do_pai=-1.0, demais=[-1.0],
        filho="tema", pai="pilar", nome_do_pai="Governança",
    ) == "Temas de Governança"
    assert frases.titulo_da_evolucao("X", [0, 0, 0, 0, 0, -1.0], [0, 0, 0, 0, 0, 1], "julho") == (
        "Evolução de X nos últimos 6 meses"
    )
    assert frases.titulo_da_lista(
        subtema="X", mes="agosto", volume=2, negativas=0, tier1_no_topo=0,
        negativa_de_maior_impacto=None,
    ) == "Matérias de X em agosto"
    assert frases.titulo_dos_veiculos([("V", -0.3)], -0.3) == "Veículos de maior impacto no subtema"
    assert frases.titulo_dos_jornalistas([], 3, ha_autor=False) == (
        "A fonte não informa o jornalista destas matérias"
    )
    assert frases.titulo_da_concentracao([("Não informada", 3, -1.0)], 3, -1.0,
                                         "Não informada") == (
        "A fonte não informou a concessionária destas matérias"
    )
    assert frases.nota_do_que_mudou(mes_anterior="julho", pilar=None, tema=None) == (
        "Sem base em julho para comparar."
    )
    assert frases.titulo_dos_divergentes([("A", 1.0)], 1.0) == "Temas de maior impacto no Mercado"


def test_as_frases_com_plural_de_materia_e_de_negativa():
    assert frases.subtitulo_do_destaque_do_subtema(1, 1, "da Imprensa").startswith(
        "1 matéria, 1 negativa."
    )
    assert frases.subtitulo_do_destaque_do_subtema(3, 0, "da Imprensa").startswith(
        "3 matérias, 0 negativas."
    )
    assert frases.titulo_da_lista(
        subtema="X", mes="agosto", volume=3, negativas=1, tier1_no_topo=0,
        negativa_de_maior_impacto=date(2026, 8, 4),
    ) == "1 de 3 matérias é negativa; a de maior impacto saiu em 04/08"
    assert frases.titulo_dos_tiers(10, 1) == "Cada matéria de Tier 1 pesa 10 vezes uma de Tier 3"
    assert frases.titulo_dos_tiers(1, 0) == "Nesta calibração só o Tier 1 conta na nota"
    assert frases.subtitulo_da_lista(
        lente_contraida="da Imprensa", valor_tier1=4.0650, mostradas=20, volume=31
    ).endswith("Tier 1 vale −4,07 quando negativa e +4,07 quando positiva. "
               "A lista mostra as 20 de maior impacto de 31.")


# -- frases: os casos achados no dado real --------------------------------------------


def test_um_pilar_so_com_impacto_nao_e_todos():
    lente, mes = "da Imprensa", "agosto"
    assert frases.titulo_da_tabela_de_pilares([("A", -3.0), ("B", 0.0)], lente, mes) == (
        "A é o único pilar que pressiona a nota (−3,0)"
    )
    assert frases.titulo_da_tabela_de_pilares([("A", 1.2)], lente, mes) == (
        "A é o único pilar que sustenta a nota (+1,2)"
    )


def test_o_titulo_dos_filhos_so_conta_os_identificados_e_o_mesmo_sentido():
    comum = {"filho": "tema", "pai": "pilar", "nome_do_pai": "Eficiência"}
    # Um só identificado (o resto era sem-tema): título neutro, nada de "100%".
    assert frases.titulo_da_tabela_de_filhos(
        destaque="Universalização", impacto_do_destaque=9.5, impacto_do_pai=11.4,
        demais=[], **comum,
    ) == "Temas de Eficiência"
    # Os demais devolvem pontos: "custa mais que os demais" não é dito.
    oposto = frases.titulo_da_tabela_de_filhos(
        destaque="Qualidade da água", impacto_do_destaque=-5.7, impacto_do_pai=-3.7,
        demais=[2.0], **comum,
    )
    assert "Sozinho" not in oposto and "mais que" not in oposto
    # Mesmo sentido e maior que a soma deles: a frase vale, sem gênero no nome.
    assert frases.titulo_da_tabela_de_filhos(
        destaque="Qualidade da água", impacto_do_destaque=-5.0, impacto_do_pai=-6.0,
        demais=[-1.0], **comum,
    ) == ("Sozinho, o tema Qualidade da água custa 5,0 pontos, mais que os demais temas "
          "do pilar somados")


def test_a_leitura_nao_da_a_fatia_de_um_filho_unico():
    leitura = frases.leitura_do_pilar(
        pilar="P", impacto=-2.0, lente_contraida="da Imprensa", mes="agosto",
        mes_anterior="julho", impacto_anterior=None, destaque=("T", -2.0),
        concentracao=None, unico_oposto=None, temas_identificados=1,
    )
    assert "responde por" not in leitura
    tema = frases.leitura_do_tema(
        subtema="S", impacto_do_subtema=-2.0, impacto_do_tema=-2.0, volume_do_subtema=1,
        mes="agosto", tier1_volume_pct=None, tier1_impacto_pct=None, veiculos=[],
        unico=None, subtemas_identificados=1,
    )
    assert tema == "S teve 1 matéria em agosto."


def test_a_evolucao_plana_e_estavel_e_nao_o_pior_nivel():
    assert frases.titulo_da_evolucao("T", [-1.0] * 6, [1] * 6, "julho") == (
        "T ficou estável em relação a julho"
    )
    assert frases.titulo_da_evolucao("T", [-1.0] * 5 + [-2.0], [1] * 6, "julho") == (
        "T chegou ao pior nível dos últimos 6 meses (−2,0)"
    )


def test_a_historia_de_uma_materia_vai_no_singular():
    um = frases.texto_da_historia(
        volume=1, mes="julho", pct_na_janela=100, dia_inicial=13, dia_final=19,
        impacto=-3.0, publicada_em=date(2026, 7, 15),
    )
    assert um == "1 matéria em julho, publicada em 15/07, tirou 3,0 pontos da nota."
    neutra = frases.texto_da_historia(
        volume=1, mes="março", pct_na_janela=100, dia_inicial=17, dia_final=23,
        impacto=0.0, publicada_em=date(2026, 3, 20),
    )
    assert neutra == "1 matéria em março, publicada em 20/03, não mexeu na nota."
    varias = frases.texto_da_historia(
        volume=3, mes="agosto", pct_na_janela=33, dia_inicial=1, dia_final=7, impacto=2.0,
    )
    assert varias == "3 matérias em agosto, 33% delas entre 1 e 7, puseram 2,0 pontos na nota."


def test_os_divergentes_falam_dos_temas_identificados_e_concordam_ponto():
    assert frases.titulo_dos_divergentes([("A", 1.0), ("B", 0.5)], 1.6) == (
        "A e B somam 1,5 dos 1,6 ponto de ganho dos temas identificados"
    )


def test_o_prefixo_do_atributo_aceita_os_separadores_de_um_export_a_mao():
    tax = _taxonomia()
    for atributo in ("7 - Prosperidade Compartilhada", "7) Prosperidade Compartilhada",
                     "7 – Prosperidade Compartilhada", " 7.Prosperidade Compartilhada"):
        assert tax.resolver(atributo=atributo).pilar == "prosperidade_compartilhada", atributo


def test_fora_da_regua_de_contagem_o_tier_1_nao_tem_valor_unico():
    assert frases.subtitulo_da_lista(
        lente_contraida="da Imprensa", valor_tier1=None, mostradas=2, volume=2
    ) == ("Impacto de cada matéria na nota da Imprensa, em pontos, ponderado pelo tier do "
          "veículo e pelo engajamento.")


# -- a montagem: os mesmos casos no payload ------------------------------------------


def _medidas_na_regua(mencoes, regua: str, calibracao: Calibracao, casas: int | None = None):
    """Como `_medidas`, numa régua dada; `casas` arredonda as somas como o
    numeric(14,4) de `score_mes_fonte`."""
    saida = {}
    for mes in MESES:
        do_mes = [m for m in mencoes if m.mes == mes]
        if not do_mes:
            continue
        soma = {"pos": 0.0, "neu": 0.0, "neg": 0.0}
        for m in do_mes:
            soma[m.sentimento] += peso_da_mencao(m.tier, m.cargo, m.engajamento, calibracao, regua)
        if casas is not None:
            soma = {k: round(v, casas) for k, v in soma.items()}
        contagem = ContagemDaNota(positivo=soma["pos"], neutro=soma["neu"], negativo=soma["neg"])
        valor = ns(contagem)
        saida[mes] = MesDaLente(
            mes=mes, regua=regua, denominador=sum(soma.values()), ns=valor,
            nota=para_score(valor) if valor is not None else None,
        )
    return saida


def test_na_regua_log_o_d_arredondado_do_agregado_ainda_fecha():
    calibracao = Calibracao(regua_engajamento="log")
    mencoes = [
        _m(s, t, tema_texto="Atendimento ao cliente", engajamento=e)
        for s, t, e in [("pos", T1, 17), ("neg", T2, 3), ("neg", T1, 1234), ("neu", T3, 0),
                        ("pos", T3, 99), ("neg", T3, 7)]
    ]
    saida = montar_consulta(
        lente=LenteDaConsulta(codigo="imprensa", nome="Imprensa", peso=0.3),
        mes=AGO, meses=MESES, mencoes=mencoes,
        medidas=_medidas_na_regua(mencoes, "log", calibracao, casas=4),
        taxonomia=_taxonomia(), calibracao=calibracao,
    )
    assert saida["meta"]["conferencia"]["fecha"] is True
    sub = _subtema(saida["lentes"][0], "atendimento_ao_cliente")
    # Cada matéria de Tier 1 vale diferente na régua log: nada de valor único.
    assert "Tier 1 vale" not in sub["nivel4"]["subtituloLista"]


def test_a_positiva_sem_impacto_nao_e_citada_como_a_de_maior_impacto():
    calibracao = Calibracao(regua_tier="so_tier1")
    mencoes = [
        _m("neg", T1, tema_texto="Atendimento ao cliente", dia=2),
        _m("pos", T2, tema_texto="Atendimento ao cliente", dia=3),
    ]
    sub = _subtema(_consulta(mencoes, calibracao=calibracao)["lentes"][0],
                   "atendimento_ao_cliente")
    assert "positiva de maior impacto" not in sub["nivel4"]["leitura"]
    assert sub["nivel4"]["tituloLista"].endswith("saiu em 02/08")


def test_veiculo_sem_tier_nao_ganha_tier_inventado():
    mencoes = [_m("neg", None, tema_texto="Atendimento ao cliente", veiculo="Blog"),
               _m("neg", T1, tema_texto="Atendimento ao cliente", veiculo="Folha")]
    tema = _consulta(mencoes)["lentes"][0]["pilares"][0]["filhos"][0]
    veiculos = {v["nome"]: v for v in tema["nivel3"]["destaque"]["veiculos"]["linhas"]}
    assert "tier" not in veiculos["Blog"]
    assert veiculos["Folha"]["tier"] == "Tier 1"


def test_a_historia_de_um_subtema_com_uma_materia_vai_no_singular():
    mencoes = [_m("neg", T1, tema_texto="Atendimento ao cliente", dia=15)]
    historia = _consulta(mencoes)["lentes"][0]["cartoesLaterais"][1]
    assert historia["texto"].startswith("1 matéria em agosto, publicada em 15/08, tirou ")


def test_o_mercado_sem_drill_manda_os_temas_e_nao_os_niveis_abertos():
    mercado = _consulta(_mes_misturado(), codigo="mercado")["lentes"][0]
    for pilar in mercado["pilares"]:
        assert "nivel2" not in pilar
        for tema in pilar.get("filhos", []):
            assert not {"filhos", "nivel3"} & set(tema)
    assert any("filhos" in p for p in mercado["pilares"])


def test_o_total_dos_divergentes_e_o_dos_temas_identificados():
    # Um pilar sem tema nenhum (Prosperidade, só pelo atributo) e um sem-tema de
    # impacto alto: nenhum dos dois entra no total que a frase cita.
    mencoes = [
        _m("pos", T1, tema_texto="Atendimento ao cliente"),
        _m("pos", T2, tema_texto="Tarifa"),
        _m("pos", T1, tema_texto="Obras", atributo="7. Prosperidade Compartilhada"),
        _m("pos", T1, tema_texto="Obras", atributo="Crescimento e Solidez Financeira"),
        _m("neu", T3, tema_texto="Atendimento ao cliente"),
    ]
    lente = _consulta(mencoes, codigo="mercado")["lentes"][0]
    cartao = lente["cartoesLaterais"][1]
    temas = [t["impacto"] for p in lente["pilares"] for t in p.get("filhos", [])
             if not t["id"].startswith("sem-") and t["impacto"] > 0]
    total = sum(temas)
    assert cartao["titulo"].endswith(
        f"dos {frases.numero(total)} {frases.pontos(total)} de ganho dos temas identificados"
    )


def test_os_meses_anteriores_agrupados_somam_igual_as_linhas():
    mencoes = _mes_misturado()
    linha_a_linha = _consulta(mencoes)
    agosto = [m for m in mencoes if m.mes == AGO]
    contagem: dict[tuple, int] = {}
    for m in mencoes:
        if m.mes != AGO:
            chave = (m.mes, m.sentimento, m.tier, m.tema_id, m.tema_texto, m.subtema, m.atributo)
            contagem[chave] = contagem.get(chave, 0) + 1
    grupos = [
        GrupoDaConsulta(mes=k[0], sentimento=k[1], tier=k[2], tema_id=k[3], tema_texto=k[4],
                        subtema=k[5], atributo=k[6], quantas=n)
        for k, n in contagem.items()
    ]
    calibracao = Calibracao()
    agrupado = montar_consulta(
        lente=LenteDaConsulta(codigo="imprensa", nome="Imprensa", peso=0.3),
        mes=AGO, meses=MESES, mencoes=agosto, grupos=grupos,
        medidas=_medidas(mencoes, calibracao), taxonomia=_taxonomia(), calibracao=calibracao,
    )
    assert agrupado == linha_a_linha
