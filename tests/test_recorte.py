"""O Recorte é o value object que sustenta a coerência entre as views."""

from __future__ import annotations

from datetime import date

import pytest

from app.dominio.erros import RegraViolada
from app.dominio.periodo import AtalhoDePeriodo, Periodo
from app.dominio.recorte import Recorte


def test_recorte_vazio_significa_base_inteira():
    recorte = Recorte()
    assert recorte.vazio
    assert recorte.quantidade_de_filtros == 0


def test_conta_filtros_ativos_para_o_contador_do_botao():
    recorte = Recorte.construir(
        periodo="ultimos-90", frente="imprensa", uf="SP", tags="Tarifa,IPO"
    )
    # período + frente + uf + tags = 4
    assert recorte.quantidade_de_filtros == 4


def test_datas_explicitas_vencem_o_atalho_de_periodo():
    recorte = Recorte.construir(
        periodo="ultimos-30", de=date(2026, 1, 1), ate=date(2026, 3, 31)
    )
    assert recorte.periodo == Periodo(de=date(2026, 1, 1), ate=date(2026, 3, 31))


def test_atalho_resolve_para_intervalo_de_datas():
    periodo = Periodo.do_atalho(AtalhoDePeriodo.ANO_CORRENTE, hoje=date(2026, 8, 24))
    assert periodo.de == date(2026, 1, 1)
    assert periodo.ate == date(2026, 8, 24)


def test_tags_chegam_como_texto_separado_por_virgula():
    recorte = Recorte.construir(tags="Tarifa, IPO ,Copasa")
    assert recorte.tags == ("Copasa", "IPO", "Tarifa")


def test_alternar_tag_liga_e_desliga():
    recorte = Recorte(tags=("Tarifa",))
    assert recorte.alternar_tag("IPO").tags == ("IPO", "Tarifa")
    assert recorte.alternar_tag("Tarifa").tags == ()


def test_uf_aceita_nacional_e_internacional():
    assert Recorte(uf="NA").uf == "NA"
    assert Recorte(uf="IN").uf == "IN"
    assert Recorte(uf="SP").uf == "SP"


def test_uf_invalida_e_recusada():
    with pytest.raises(RegraViolada, match="UF inválida"):
        Recorte(uf="XX")


def test_tier_fora_da_faixa_e_recusado():
    with pytest.raises(RegraViolada, match="Tier inválido"):
        Recorte(tier=4)


def test_periodo_invertido_e_recusado():
    with pytest.raises(RegraViolada, match="posterior"):
        Periodo(de=date(2026, 5, 1), ate=date(2026, 1, 1))


def test_status_e_grupo_sao_filtros_distintos():
    # "declinado" é código de status *e* nome de grupo. Em campos separados,
    # nunca há dúvida sobre qual dos dois o usuário pediu.
    recorte = Recorte(status="declinado", grupo_status="declinado")
    assert recorte.status == "declinado"
    assert recorte.grupo_status == "declinado"
    assert recorte.quantidade_de_filtros == 2


def test_grupo_de_status_invalido_e_recusado():
    with pytest.raises(RegraViolada, match="Grupo de status inválido"):
        Recorte(grupo_status="pendente")


def test_recorte_e_imutavel():
    recorte = Recorte(frente="imprensa")
    novo = recorte.com(uf="RJ")
    assert recorte.uf is None
    assert novo.uf == "RJ"
    assert novo.frente == "imprensa"


def test_periodo_desconhecido_diz_o_que_e_valido():
    with pytest.raises(RegraViolada, match="ano-corrente"):
        Recorte.construir(periodo="semana-passada")
