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
        periodo="ultimos-90", frente="imprensa", uf="SP", tags=["Tarifa", "IPO"]
    )
    # período + frente + uf + tags = 4
    assert recorte.quantidade_de_filtros == 4


def test_datas_explicitas_vencem_o_atalho_de_periodo():
    recorte = Recorte.construir(
        periodo="ultimos-30", de=date(2026, 1, 1), ate=date(2026, 3, 31)
    )
    assert recorte.periodo == Periodo(de=date(2026, 1, 1), ate=date(2026, 3, 31))


def test_atalho_resolve_para_intervalo_de_datas():
    periodo = Periodo.do_atalho(AtalhoDePeriodo.ULTIMOS_360, hoje=date(2026, 8, 24))
    assert periodo.de == date(2025, 8, 29)
    assert periodo.ate == date(2026, 8, 24)


def test_atalho_futuro_resolve_para_intervalo_de_datas():
    periodo = Periodo.do_atalho(AtalhoDePeriodo.PROXIMOS_360, hoje=date(2026, 8, 24))
    assert periodo.de == date(2026, 8, 24)
    assert periodo.ate == date(2027, 8, 19)


def test_tags_chegam_como_lista_e_a_virgula_faz_parte_do_nome():
    """Repetido na query (`tags=a&tags=b`), lista aqui — e nunca partido na
    vírgula, porque um nome de tema pode tê-la."""
    recorte = Recorte.construir(tags=["Tarifa", " IPO ", "", "Saneamento, drenagem"])
    assert recorte.tags == ("IPO", "Saneamento, drenagem", "Tarifa")

    # Um texto só é UM tema, vírgula inclusa.
    assert Recorte.construir(tags="Saneamento, drenagem").tags == ("Saneamento, drenagem",)


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


def test_tier_nao_positivo_e_recusado():
    """O `Recorte` só barra o que é absurdo em qualquer configuração.

    Filtrar por um nível que não existe devolve zero registros, e está certo: é
    a mesma resposta de filtrar por um que existe e ninguém usou. Recusar
    exigiria consultar o banco daqui, e o `Recorte` é objeto de valor puro.
    """
    with pytest.raises(RegraViolada, match="Tier inválido"):
        Recorte(tier=0)
    with pytest.raises(RegraViolada, match="Tier inválido"):
        Recorte(tier=-2)


def test_tier_4_e_aceito_pelo_recorte():
    """Este teste afirmava o contrário até hoje, e por isso `Recorte(tier=4)`
    devolvia 400 mesmo com o Tier 4 já existindo no banco."""
    assert Recorte(tier=4).tier == 4


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
    with pytest.raises(RegraViolada, match="ultimos-30"):
        Recorte.construir(periodo="semana-passada")


def test_a_busca_acha_agenda_nova_pelo_tema_e_pela_expectativa():
    """A pauta saiu da tela, e a busca procurava o assunto nela.

    Agenda criada pelo formulario nao tem mais pauta: o assunto dela mora em
    `temas` (o classificado) e em `expectativa` (o que se quer da reuniao).
    Sem estes dois, procurar por "reajuste" acharia so os 60 registros vindos
    da planilha — e a busca PARECERIA funcionar, o que e pior do que quebrar.
    """
    from app.banco.filtros_sql import condicoes
    from app.dominio.identidade import Escopo
    from app.dominio.recorte import Recorte

    sql = " ".join(
        str(c.compile(compile_kwargs={"literal_binds": True}))
        for c in condicoes(
            Recorte(busca="reajuste"),
            escopo=Escopo(irrestrito=True),
            busca_em_campos_sensiveis=False,
        )
    )

    assert "expectativa" in sql, "a busca ignora a expectativa"
    assert "interacao_tema" in sql, "a busca ignora o assunto classificado"
    #: E continua achando o que a planilha trouxe.
    assert "pauta" in sql


def test_o_filtro_por_pessoa_nao_estoura():
    """O filtro por pessoa e montado, e nao so escrito.

    `InteracaoInterlocutor` usada sem import da `NameError` em tempo de
    execucao, dentro da montagem da consulta — 500 na API. Sem um teste que
    exercite `pessoa=`, o unico sinal e um `F821`
    que ninguem estava lendo.

    O teste MONTA a condicao, que e onde o nome e resolvido. Um teste que so
    chamasse a rota com outro filtro passaria sem tocar nesta linha.
    """
    from uuid import uuid4

    from app.banco.filtros_sql import condicoes
    from app.dominio.identidade import Escopo
    from app.dominio.recorte import Recorte

    condicoes(
        Recorte(pessoa=uuid4()),
        escopo=Escopo(irrestrito=True),
        busca_em_campos_sensiveis=False,
    )
