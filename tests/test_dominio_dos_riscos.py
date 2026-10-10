"""O índice de exposição a risco, sem banco.

AS DUAS DECISÕES DO DONO DO PRODUTO que este módulo carrega:

* INCIDENTE é fato negativo sobre assunto que toca risco — menção de sentimento
  negativo, ou agenda de clima negativo no CRM;
* O ÍNDICE pesa a severidade e vai de 0 a 100, com 100 no pior mês da série.

O que se testa aqui é a aritmética e as bordas dela. O que vem do banco tem
teste próprio.
"""

from __future__ import annotations

from app.dominio.riscos import (
    MesDeRisco,
    com_o_indice,
    faixa_do_indice,
    peso_da_severidade,
    variacao,
)


def test_a_severidade_pesa_na_ordem_da_matriz():
    #: Um crítico vale três moderados — a proporção é convenção, a ORDEM não é:
    #: ela vem de `risco.severidade`, atribuído pela companhia.
    assert peso_da_severidade("critico") > peso_da_severidade("alto")
    assert peso_da_severidade("alto") > peso_da_severidade("moderado")
    assert peso_da_severidade("moderado") > 0


def test_a_severidade_DESCONHECIDA_pesa_ZERO_e_nao_um():
    """Severidade que o cadastro não conhece não inventa gravidade.

    Com peso 1, um valor novo em `risco.severidade` — um "baixo" que alguém
    cadastre — entraria no índice valendo o mesmo que "moderado", sem ninguém
    ter decidido isso. Com zero, o incidente aparece na matriz e não move o
    índice, que é o estado honesto de "não sei quanto isso pesa".
    """
    assert peso_da_severidade("baixo") == 0
    assert peso_da_severidade(None) == 0
    assert peso_da_severidade("") == 0


def test_a_severidade_vem_do_cadastro_com_qualquer_caixa():
    #: O cadastro é editável pela coordenação; `Crítico` com maiúscula não pode
    #: deixar de pesar.
    assert peso_da_severidade("CRITICO") == peso_da_severidade("critico")
    assert peso_da_severidade(" Alto ") == peso_da_severidade("alto")


def test_o_PICO_DA_SERIE_vale_cem():
    serie, referencia, mes_do_pico = com_o_indice(
        [
            MesDeRisco("2026-06", incidentes=4, pesado=8),
            MesDeRisco("2026-07", incidentes=10, pesado=20),
            MesDeRisco("2026-08", incidentes=5, pesado=10),
        ]
    )

    assert [mes.indice for mes in serie] == [40, 100, 50]
    #: A REFERÊNCIA VAI NA RESPOSTA porque a tela precisa dizer o que 100
    #: significa — sem ela, "índice 40" é número sem unidade.
    assert referencia == 20
    assert mes_do_pico == "2026-07"


def test_a_SERIE_SEM_INCIDENTE_da_zero_e_nao_estoura():
    """Mês sem incidente é informação, não falha.

    A divisão pelo pico com pico zero levantaria `ZeroDivisionError` no meio de
    um pedido — e o caso é comum: fonte recém-ligada, mês ainda sem carga, ou o
    recorte de um risco que nunca teve incidente.
    """
    serie, referencia, mes_do_pico = com_o_indice(
        [MesDeRisco("2026-06", 0, 0), MesDeRisco("2026-07", 0, 0)]
    )

    assert [mes.indice for mes in serie] == [0, 0]
    assert referencia == 0
    assert mes_do_pico is None


def test_a_SERIE_VAZIA_nao_estoura():
    serie, referencia, mes_do_pico = com_o_indice([])

    assert serie == []
    assert referencia == 0
    assert mes_do_pico is None


def test_as_FAIXAS_dividem_a_escala_em_tres():
    assert faixa_do_indice(100) == "critico"
    assert faixa_do_indice(67) == "critico"
    assert faixa_do_indice(66) == "alto"
    assert faixa_do_indice(34) == "alto"
    assert faixa_do_indice(33) == "moderado"
    assert faixa_do_indice(0) == "moderado"
    #: SEM ÍNDICE não é faixa nenhuma: mês sem medição não é "moderado".
    assert faixa_do_indice(None) is None


def test_a_VARIACAO_compara_com_o_mes_anterior():
    serie, _, _ = com_o_indice(
        [
            MesDeRisco("2026-07", 10, 20),
            MesDeRisco("2026-08", 5, 10),
        ]
    )

    #: 100 no pico de julho, 50 em agosto: caiu 50 pontos.
    assert variacao(serie) == -50


def test_a_PRIMEIRA_MEDICAO_nao_tem_variacao():
    """Zero diria "ficou estável", e não há com o que comparar."""
    serie, _, _ = com_o_indice([MesDeRisco("2026-08", 5, 10)])

    assert variacao(serie) is None
    assert variacao([]) is None


def test_o_INDICE_nao_apaga_o_que_o_MES_ja_sabia():
    """`com_o_indice` reconstruía o mês por POSIÇÃO, e isso calava.

    Campo novo no `MesDeRisco` voltava ao padrão ao passar pelo cálculo do
    índice — a série saía com `por_severidade` vazio e nada reclamava. A barra
    empilhada da tela ficaria lisa, e o gráfico pareceria não ter dado.
    """
    serie, _referencia, _pico = com_o_indice(
        [
            MesDeRisco(
                mes="2026-08",
                incidentes=3,
                pesado=7,
                na_janela=False,
                fontes=("bites", "clipei"),
                por_severidade=(("critico", 1), ("alto", 2)),
            )
        ]
    )

    assert serie[0].por_severidade == (("critico", 1), ("alto", 2))
    #: E O RESTO TAMBÉM SOBREVIVE.
    assert serie[0].fontes == ("bites", "clipei")
    assert serie[0].na_janela is False
    assert serie[0].indice == 100


def test_a_SERIE_SEM_INCIDENTE_tambem_preserva_o_mes():
    """O caminho do `referencia <= 0` reconstruía por posição do mesmo jeito."""
    serie, referencia, pico = com_o_indice(
        [MesDeRisco(mes="2026-01", incidentes=0, pesado=0, fontes=("bites",))]
    )

    assert (referencia, pico) == (0, None)
    assert serie[0].indice == 0
    assert serie[0].fontes == ("bites",)
