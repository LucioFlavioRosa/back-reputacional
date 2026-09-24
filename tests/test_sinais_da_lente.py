"""Os detectores de sinal, um a um — e as frases do protótipo, inteiras.

DOIS NÍVEIS DE PROVA, e são diferentes de propósito.

O primeiro é por detector: dispara, não dispara, e se cala quando falta dado.
É o que garante que um limite mexido na Calibração muda o que se espera que
mude, e só isso.

O segundo é de ponta a ponta, com os NÚMEROS DO PROTÓTIPO — a série de imprensa
de janeiro a agosto, os tiers de junho, o eventograma de mercado, o teor de
reclamação. A §7 do pacote lista as frases que esses números têm de produzir, e
elas estão aqui literais. É o único teste que pega o erro que mais importa: o
detector certo produzindo a frase errada, ou a frase certa aparecendo no lugar
errado da tela.

POR QUE OS DADOS DE REFERÊNCIA NÃO SÃO OS DA BASE. A base local tem junho, e o
protótipo tem oito meses. Um golden test escrito sobre a base provaria que o
código concorda consigo mesmo; escrito sobre o protótipo, prova que concorda
com quem desenhou a leitura.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.dominio.erros import RegraViolada
from app.dominio.sinais_da_lente import (
    TIPO_DE_LACUNA,
    AcaoDeRating,
    Evento,
    Item,
    Jornalista,
    Limites,
    Ponto,
    Secao,
    Tom,
    detectar_na_matriz,
    detectar_na_recuperacao,
    detectar_na_serie,
    detectar_no_estudo,
    detectar_no_percentual,
    detectar_no_ranking,
    detectar_no_rating,
    detectar_no_volume,
    detectar_nos_eventos,
    detectar_nos_itens,
    escolher,
    sinal_de_proxy,
)

LIMITES = Limites()


def mes(numero: int) -> date:
    """O 1º dia do mês `numero` de 2026 — o período inteiro do protótipo."""
    return date(2026, numero, 1)


def serie(*meses: tuple[int, int, int] | None) -> list[Ponto]:
    """`(pos, neu, neg)` por mês, a partir de janeiro. `None` é mês sem base."""
    return [
        Ponto(mes=mes(i), sem_base=True)
        if valores is None
        else Ponto(mes=mes(i), pos=valores[0], neu=valores[1], neg=valores[2])
        for i, valores in enumerate(meses, start=1)
    ]


def frases_de(sinais) -> list[str]:
    return [sinal.frase for sinal in sinais]


def tipos_de(sinais) -> list[str]:
    return [sinal.tipo for sinal in sinais]


def na_serie(pontos, **extra):
    return detectar_na_serie(
        pontos, unidade="matérias", secao=Secao.EVOLUCAO, limites=LIMITES, **extra
    )


# =============================================================================
# 5.1 · a série mensal de sentimento
# =============================================================================


class TestPico:
    def test_dispara_no_mes_de_maior_volume(self):
        sinais = na_serie(serie((10, 10, 10), (10, 10, 10), (10, 10, 10), (300, 100, 100)))
        pico = next(sinal for sinal in sinais if sinal.tipo == "Pico")
        assert "Abril teve o maior volume do período (500 matérias)" in pico.frase
        assert pico.evidencia == "500"
        assert pico.tom is Tom.NEUTRO

    def test_nao_dispara_quando_o_volume_e_parelho(self):
        """Um mês 9% acima da média passa nos desvios e cai na razão.

        SÃO DUAS CONDIÇÕES PORQUE UMA SÓ ERRA NOS DOIS SENTIDOS: numa série
        muito regular, qualquer solavanco vira 1,5 desvio — como aqui, onde o
        z chega a 1,7 sobre uma diferença de nove matérias.
        """
        sinais = na_serie(serie((100, 0, 0), (100, 0, 0), (100, 0, 0), (113, 0, 0)))
        assert "Pico" not in tipos_de(sinais)

    def test_se_cala_com_menos_de_tres_meses(self):
        assert "Pico" not in tipos_de(na_serie(serie((10, 0, 0), (900, 0, 0))))

    def test_o_mes_sem_base_nao_entra_na_media(self):
        """Contá-lo como zero rebaixaria a média e inventaria um pico."""
        com_buraco = na_serie(serie((100, 0, 0), None, (100, 0, 0), (140, 0, 0)))
        assert "Pico" not in tipos_de(com_buraco)


class TestVirada:
    def test_dispara_quando_a_nota_anda_dez_pontos(self):
        sinais = na_serie(serie((60, 0, 40), (40, 0, 60)))
        virada = next(sinal for sinal in sinais if sinal.tipo == "Virada")
        assert virada.frase == (
            "A nota caiu 20 pontos em fevereiro: o negativo foi de 40% para 60%."
        )
        assert virada.evidencia == "-20 pts"
        assert virada.tom is Tom.NEGATIVO

    def test_dispara_na_troca_de_lado_mesmo_pequena(self):
        """Sair de saldo positivo para negativo é mudança de natureza."""
        sinais = na_serie(serie((52, 0, 48), (48, 0, 52)))
        assert "Virada" in tipos_de(sinais)

    def test_a_troca_de_lado_sem_variacao_de_nota_nao_diz_zero_ponto(self):
        """A nota é o saldo reescalado E ARREDONDADO: um saldo que cruza o zero
        por pouco cai no mesmo inteiro dos dois lados, e "A nota caiu 0 ponto"
        seria a frase."""
        sinais = na_serie(serie((501, 0, 499), (499, 0, 501)))
        virada = next(sinal for sinal in sinais if sinal.tipo == "Virada")
        assert virada.frase == (
            "O saldo virou para o negativo em fevereiro: o negativo foi de 50% para 50%."
        )

    def test_a_troca_para_o_positivo_diz_isso(self):
        sinais = na_serie(serie((499, 0, 501), (501, 0, 499)))
        virada = next(sinal for sinal in sinais if sinal.tipo == "Virada")
        assert virada.frase.startswith("O saldo virou para o positivo")

    def test_nao_dispara_abaixo_do_limite_sem_trocar_de_lado(self):
        sinais = na_serie(serie((70, 0, 30), (66, 0, 34)))
        assert "Virada" not in tipos_de(sinais)

    def test_se_cala_com_um_mes_so(self):
        assert "Virada" not in tipos_de(na_serie(serie((60, 0, 40))))

    def test_compara_os_dois_ultimos_meses_COM_leitura(self):
        """O mês sem base entre eles não interrompe a comparação: ele não tem
        leitura para comparar, e tratá-lo como corte esconderia a virada."""
        sinais = na_serie(serie((60, 0, 40), None, (40, 0, 60)))
        virada = next(sinal for sinal in sinais if sinal.tipo == "Virada")
        assert "em março" in virada.frase


class TestOrdemDaSerie:
    def test_a_leitura_nao_depende_da_ordem_em_que_a_serie_chegou(self):
        """ "Último vs. penúltimo" é uma afirmação sobre o calendário. Lê-la da
        ordem do argumento faria a mesma série devolver leituras diferentes
        conforme quem a montou."""
        em_ordem = serie((60, 0, 40), (50, 0, 50), (40, 0, 60))
        embaralhada = [em_ordem[2], em_ordem[0], em_ordem[1]]
        assert frases_de(na_serie(embaralhada)) == frases_de(na_serie(em_ordem))


class TestAltaDoNegativo:
    def test_dispara_quando_nao_houve_virada(self):
        """A nota anda 8 pontos (abaixo do limite), a fatia negativa anda 16."""
        sinais = na_serie(serie((20, 60, 20), (20, 44, 36)))
        alta = next(sinal for sinal in sinais if sinal.tipo == "Alta do negativo")
        assert alta.frase == ("O negativo subiu de 20% em janeiro para 36% em fevereiro.")
        assert alta.evidencia == "+16 p.p."

    def test_se_cala_quando_a_virada_ja_contou_a_mesma_noticia(self):
        sinais = na_serie(serie((60, 0, 40), (40, 0, 60)))
        assert "Virada" in tipos_de(sinais)
        assert "Alta do negativo" not in tipos_de(sinais)

    def test_nao_dispara_abaixo_do_limite(self):
        sinais = na_serie(serie((20, 60, 20), (20, 55, 25)))
        assert "Alta do negativo" not in tipos_de(sinais)

    def test_pula_o_mes_sem_leitura_no_meio(self):
        """O mês sem base não é um mês parado: é um mês sem dado, e tratá-lo
        como leitura faria a comparação sair contra zero."""
        sinais = na_serie(serie((20, 60, 20), None, (20, 44, 36)))
        alta = next(sinal for sinal in sinais if sinal.tipo == "Alta do negativo")
        assert alta.frase == ("O negativo subiu de 20% em janeiro para 36% em março.")

    def test_se_cala_quando_so_um_mes_tem_leitura(self):
        pontos = [
            Ponto(mes=mes(1), pos=20, neu=60, neg=20),
            Ponto(mes=mes(2), sem_classificacao=900),
        ]
        assert "Alta do negativo" not in tipos_de(na_serie(pontos))


class TestTendencia:
    def test_dispara_em_tres_meses_na_mesma_direcao(self):
        sinais = na_serie(serie((70, 0, 30), (75, 0, 25), (80, 0, 20)))
        tendencia = next(sinal for sinal in sinais if sinal.tipo == "Tendência")
        assert tendencia.frase == ("O negativo cai há 3 meses seguidos: 30% → 25% → 20%.")
        assert tendencia.tom is Tom.POSITIVO

    def test_nao_dispara_com_um_mes_fora_da_direcao(self):
        sinais = na_serie(serie((70, 0, 30), (60, 0, 40), (80, 0, 20)))
        assert "Tendência" not in tipos_de(sinais)

    def test_se_cala_com_menos_meses_que_o_limite(self):
        sinais = na_serie(serie((70, 0, 30), (75, 0, 25)))
        assert "Tendência" not in tipos_de(sinais)

    def test_os_meses_sem_leitura_nao_contam_para_a_sequencia(self):
        """TRÊS MESES SEGUIDOS É SOBRE A LEITURA, não sobre o calendário: um
        buraco no meio não interrompe a tendência, mas também não a preenche."""
        sinais = na_serie(serie((70, 0, 30), None, (75, 0, 25), (80, 0, 20)))
        tendencia = next(sinal for sinal in sinais if sinal.tipo == "Tendência")
        assert tendencia.evidencia == "3 meses"

    def test_se_cala_quando_o_buraco_deixa_menos_de_tres(self):
        sinais = na_serie(serie((70, 0, 30), None, (75, 0, 25)))
        assert "Tendência" not in tipos_de(sinais)

    def test_o_limite_de_meses_e_configuravel(self):
        pontos = serie((70, 0, 30), (75, 0, 25), (78, 0, 22), (80, 0, 20))
        com_quatro = detectar_na_serie(
            pontos,
            unidade="matérias",
            secao=Secao.EVOLUCAO,
            limites=Limites(tendencia_meses=4),
        )
        tendencia = next(sinal for sinal in com_quatro if sinal.tipo == "Tendência")
        assert tendencia.evidencia == "4 meses"


class TestDeslocamento:
    def test_dispara_quando_o_negativo_recuou_do_pico(self):
        sinais = na_serie(serie((40, 0, 60), (60, 0, 40), (70, 0, 30)))
        deslocamento = next(sinal for sinal in sinais if sinal.tipo == "Deslocamento")
        assert deslocamento.frase == ("O negativo recuou de 60% em janeiro para 30% em março.")
        assert deslocamento.evidencia == "−30 p.p."

    def test_nao_dispara_quando_o_ultimo_mes_piorou(self):
        """É A REGRA QUE IMPEDE A CONTRADIÇÃO na própria linha: o chip ao lado
        mostraria a queda da nota, e a frase diria que o negativo recuou."""
        sinais = na_serie(serie((40, 0, 60), (75, 0, 25), (65, 0, 35)))
        assert "Deslocamento" not in tipos_de(sinais)

    def test_nao_dispara_quando_o_pico_e_o_ultimo_mes(self):
        sinais = na_serie(serie((70, 0, 30), (60, 0, 40), (40, 0, 60)))
        assert "Deslocamento" not in tipos_de(sinais)

    def test_se_cala_com_menos_de_tres_meses(self):
        sinais = na_serie(serie((40, 0, 60), (80, 0, 20)))
        assert "Deslocamento" not in tipos_de(sinais)

    def test_se_cala_quando_o_buraco_deixa_menos_de_tres_meses_com_leitura(self):
        sinais = na_serie(serie((40, 0, 60), None, (70, 0, 30)))
        assert "Deslocamento" not in tipos_de(sinais)

    def test_o_mes_sem_base_nao_conta_como_recuo(self):
        """Sem leitura não há fatia negativa, e tratá-la como zero faria o
        detector anunciar um recuo que ninguém mediu."""
        sinais = na_serie(serie((40, 0, 60), (60, 0, 40), (70, 0, 30), None))
        deslocamento = next(sinal for sinal in sinais if sinal.tipo == "Deslocamento")
        assert "para 30% em março" in deslocamento.frase


class TestLacunaDeDado:
    def test_separa_o_mes_sem_sentimento_do_mes_sem_base(self):
        """SÃO DOIS PROBLEMAS DIFERENTES (§2): um é fornecedor que não leu, o
        outro é fornecedor que não mandou — e quem cobra não é o mesmo."""
        pontos = [
            Ponto(mes=mes(1), pos=10, neu=0, neg=5),
            Ponto(mes=mes(2), sem_classificacao=800),
            Ponto(mes=mes(3), sem_base=True),
        ]
        lacuna = next(sinal for sinal in na_serie(pontos) if sinal.tipo == TIPO_DE_LACUNA)
        assert lacuna.frase == ("Sentimento de fevereiro ainda não integrado. Março sem base.")
        assert lacuna.evidencia == "2 meses"

    def test_nao_dispara_quando_todo_mes_tem_leitura(self):
        assert TIPO_DE_LACUNA not in tipos_de(na_serie(serie((10, 0, 5), (10, 0, 5))))

    def test_nao_compete_por_vaga(self):
        pontos = [Ponto(mes=mes(1), pos=10, neu=0, neg=5), Ponto(mes=mes(2), sem_base=True)]
        lacuna = next(sinal for sinal in na_serie(pontos) if sinal.tipo == TIPO_DE_LACUNA)
        assert lacuna.intensidade == 0

    def test_o_singular_do_mes(self):
        pontos = [Ponto(mes=mes(1), pos=10, neu=0, neg=5), Ponto(mes=mes(2), sem_base=True)]
        lacuna = next(sinal for sinal in na_serie(pontos) if sinal.tipo == TIPO_DE_LACUNA)
        assert lacuna.evidencia == "1 mês"


# =============================================================================
# 5.2 · composição por item
# =============================================================================


class TestItens:
    def test_compara_o_item_com_o_geral_quando_sao_contagens(self):
        sinais = detectar_nos_itens(
            [
                Item("Muito Relevante", 65, 64, 16),
                Item("Relevante", 85, 43, 55),
                Item("Menos Relevante", 946, 80, 149),
            ],
            secao=Secao.PAINEL_A,
            rotulo_do_negativo="Tier",
        )
        assert frases_de(sinais)[0] == ("Relevante concentra o maior negativo: 30% (geral 15%).")
        assert tipos_de(sinais)[0] == "Tier"

    def test_sem_geral_quando_cada_linha_ja_e_percentual(self):
        """SOMAR PERCENTUAIS DE LINHAS DIFERENTES NÃO PRODUZ NÚMERO NENHUM — e
        um "geral" calculado assim pareceria uma média e não seria."""
        sinais = detectar_nos_itens(
            [Item("Privatização", 9.4, 11, 79.6), Item("Patrocínio", 97.1, 0.9, 2)],
            secao=Secao.PAINEL_A,
            percentual=True,
        )
        assert frases_de(sinais)[0] == "Privatização concentra o maior negativo: 80%."

    def test_sustenta_sai_quando_o_melhor_e_o_pior_sao_o_mesmo_item(self):
        sinais = detectar_nos_itens([Item("Único", 50, 0, 50)], secao=Secao.PAINEL_A)
        assert tipos_de(sinais) == ["Tema dominante"]

    def test_se_cala_sem_itens(self):
        assert detectar_nos_itens([], secao=Secao.PAINEL_A) == []

    def test_o_item_sem_volume_nao_vira_leitura(self):
        """Sem denominador não há fatia. `fatia_negativa` devolve 0 para não
        estourar, e esse 0 viraria "concentra o maior negativo: 0%" sobre um
        item por onde não passou nada."""
        assert detectar_nos_itens([Item("Vazio", 0, 0, 0)], secao=Secao.PAINEL_A) == []

    def test_ignora_o_item_vazio_e_le_os_outros(self):
        sinais = detectar_nos_itens(
            [Item("Vazio", 0, 0, 0), Item("Privatização", 5, 5, 90)],
            secao=Secao.PAINEL_A,
        )
        assert frases_de(sinais) == ["Privatização concentra o maior negativo: 90% (geral 90%)."]


# =============================================================================
# 5.3 · ranking
# =============================================================================


class TestRanking:
    def test_dispara_pela_razao_entre_o_primeiro_e_o_segundo(self):
        sinais = detectar_no_ranking(
            [("Corsan", 2515), ("Águas do Rio", 318)],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="a segunda unidade",
            unidade="menções",
            limites=LIMITES,
        )
        assert frases_de(sinais) == ["Corsan tem 7,9× o volume de Águas do Rio, a segunda unidade."]

    def test_cai_para_o_topo_quando_a_razao_nao_dispara(self):
        sinais = detectar_no_ranking(
            [("ANA", 9), ("BNDES", 7), ("ABCON", 6), ("Câmara", 5), ("ALMG", 4)],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="o segundo órgão",
            unidade="agendas",
            limites=LIMITES,
        )
        assert frases_de(sinais) == ["ANA, BNDES e ABCON concentram 71% das agendas."]

    def test_nao_dispara_quando_o_volume_e_distribuido(self):
        sinais = detectar_no_ranking(
            [(f"Órgão {i}", 10) for i in range(10)],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="o segundo órgão",
            unidade="agendas",
            limites=LIMITES,
        )
        assert sinais == []

    def test_o_singular_quando_o_topo_tem_um_item_so(self):
        """ "ANA concentram 100%" denuncia que ninguém leu a tela."""
        sinais = detectar_no_ranking(
            [("ANA", 9)],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="o segundo órgão",
            unidade="agendas",
            limites=LIMITES,
        )
        assert frases_de(sinais) == ["ANA concentra 100% das agendas."]

    def test_o_ordinal_do_segundo_chega_pronto(self):
        """ADIVINHAR O GÊNERO PELA ÚLTIMA LETRA acerta "unidade" e erra
        "empresa" — quem chama sabe o gênero, o modelo de frase não."""
        sinais = detectar_no_ranking(
            [("Aegea", 900), ("Outra", 100)],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="a segunda empresa",
            unidade="menções",
            limites=LIMITES,
        )
        assert frases_de(sinais) == ["Aegea tem 9,0× o volume de Outra, a segunda empresa."]

    def test_se_cala_sem_volume(self):
        assert (
            detectar_no_ranking(
                [("ANA", 0), ("BNDES", 0)],
                secao=Secao.PAINEL_B,
                ordinal_do_segundo="o segundo órgão",
                unidade="agendas",
                limites=LIMITES,
            )
            == []
        )


# =============================================================================
# 5.4 · série de percentual
# =============================================================================


class TestPercentual:
    def test_dispara_e_diz_quando_o_ultimo_e_o_menor(self):
        sinais = detectar_no_percentual(
            [(mes(5), 59.0), (mes(6), 46.0), (mes(7), 47.0), (mes(8), 34.0)],
            nome="Reclamação",
            secao=Secao.PAINEL_B,
            limites=LIMITES,
        )
        assert frases_de(sinais) == [
            "Reclamação caiu de 59% em maio para 34% em agosto, o menor peso do período."
        ]

    def test_sem_o_fecho_quando_ja_esteve_mais_baixo(self):
        sinais = detectar_no_percentual(
            [(mes(5), 59.0), (mes(6), 20.0), (mes(8), 34.0)],
            nome="Reclamação",
            secao=Secao.PAINEL_B,
            limites=LIMITES,
        )
        assert frases_de(sinais) == ["Reclamação caiu de 59% em maio para 34% em agosto."]

    def test_nao_dispara_quando_o_maximo_e_o_ultimo(self):
        assert (
            detectar_no_percentual(
                [(mes(5), 20.0), (mes(6), 59.0)],
                nome="Reclamação",
                secao=Secao.PAINEL_B,
                limites=LIMITES,
            )
            == []
        )

    def test_se_cala_com_um_mes_medido_so(self):
        assert (
            detectar_no_percentual(
                [(mes(5), None), (mes(6), None), (mes(7), 34.0)],
                nome="Reclamação",
                secao=Secao.PAINEL_B,
                limites=LIMITES,
            )
            == []
        )


# =============================================================================
# 5.5 · o que só existe em uma lente
# =============================================================================

MATRIZ = [
    Jornalista("Ana Paula", "Valor", relevancia=5, exposicao=5, proximidade=2),
    Jornalista("Bruno", "Folha", relevancia=5, exposicao=4, proximidade=4),
    Jornalista("Carla", "Estadão", relevancia=5, exposicao=5, proximidade=5),
]


class TestMatrizDeJornalistas:
    def test_aponta_quem_pauta_muito_e_esta_longe(self):
        sinais = detectar_na_matriz(MATRIZ, secao=Secao.PAINEL_B)
        lacuna = next(sinal for sinal in sinais if sinal.tipo == "Lacuna de relacionamento")
        assert lacuna.frase == (
            "Ana Paula (Valor) tem relevância 5 e exposição 5, mas proximidade 2 "
            "— a maior distância da matriz."
        )
        assert lacuna.evidencia == "proximidade 2"

    def test_se_cala_quando_ninguem_esta_longe(self):
        perto = [Jornalista("Carla", "Estadão", 5, 5, 5)]
        assert "Lacuna de relacionamento" not in tipos_de(
            detectar_na_matriz(perto, secao=Secao.PAINEL_B)
        )

    def test_conta_os_de_prioridade_um(self):
        sinais = detectar_na_matriz(MATRIZ, secao=Secao.PAINEL_B)
        prioridade = next(sinal for sinal in sinais if sinal.tipo == "Prioridade")
        assert prioridade.frase == (
            "2 jornalistas estão em prioridade 1 (relacionamento contínuo)."
        )

    def test_o_singular_de_um_jornalista_so(self):
        sinais = detectar_na_matriz([Jornalista("Carla", "Estadão", 5, 5, 5)], secao=Secao.PAINEL_B)
        prioridade = next(sinal for sinal in sinais if sinal.tipo == "Prioridade")
        assert prioridade.frase == ("1 jornalista está em prioridade 1 (relacionamento contínuo).")

    def test_se_cala_sem_matriz(self):
        assert detectar_na_matriz([], secao=Secao.PAINEL_B) == []


EVENTOS = [
    Evento(mes(2), "Vazamento do acordo", "pressiona"),
    Evento(mes(3), "Atraso das DFs", "pressiona"),
    Evento(mes(4), "DFs 2025", "misto"),
    Evento(mes(5), "1T26", "misto"),
    Evento(mes(5), "Brazil Week NY", "sustenta"),
    Evento(mes(5), "S&P B · Fitch BB- · Moody's Ba3", "pressiona"),
    Evento(mes(6), "Edital e proposta Copasa", "misto"),
    Evento(mes(7), "Aumento de capital R$ 2,1 bi", "sustenta"),
    Evento(mes(7), "Fitch B+", "pressiona"),
    Evento(mes(7), "Estudo de percepção", "misto"),
    Evento(mes(8), "2T26", "misto"),
    Evento(mes(8), "Saída do CFO", "pressiona"),
    Evento(mes(8), "Moody's B2 negativa", "pressiona"),
]


class TestEventos:
    def test_conta_os_meses_em_que_a_pressao_predominou(self):
        sinais = detectar_nos_eventos(EVENTOS, secao=Secao.EVOLUCAO)
        pressao = next(sinal for sinal in sinais if sinal.tipo == "Pressão")
        assert pressao.frase == (
            "A pressão predominou em 3 de 7 meses com eventos (fevereiro, março e agosto)."
        )
        assert pressao.evidencia == "3/7"

    def test_o_denominador_sao_os_meses_com_evento(self):
        """Um mês sem fato cadastrado não é um mês calmo — é um mês sem
        cadastro, e contá-lo como calmo diluiria a pressão com ausência."""
        sinais = detectar_nos_eventos(
            [Evento(mes(2), "Vazamento", "pressiona")], secao=Secao.EVOLUCAO
        )
        pressao = next(sinal for sinal in sinais if sinal.tipo == "Pressão")
        assert pressao.evidencia == "1/1"

    def test_nao_dispara_pressao_quando_o_periodo_sustenta(self):
        sinais = detectar_nos_eventos(
            [Evento(mes(7), "Aumento de capital", "sustenta")], secao=Secao.EVOLUCAO
        )
        assert "Pressão" not in tipos_de(sinais)

    def test_aponta_o_mes_que_acumulou_pressao(self):
        sinais = detectar_nos_eventos(EVENTOS, secao=Secao.EVOLUCAO)
        concentracao = next(sinal for sinal in sinais if sinal.tipo == "Concentração de eventos")
        assert concentracao.frase == (
            "Agosto concentra 2 eventos de pressão: Saída do CFO e Moody's B2 negativa."
        )

    def test_o_empate_fica_com_o_mes_mais_recente(self):
        empatados = [
            Evento(mes(3), "A", "pressiona"),
            Evento(mes(3), "B", "pressiona"),
            Evento(mes(7), "C", "pressiona"),
            Evento(mes(7), "D", "pressiona"),
        ]
        sinais = detectar_nos_eventos(empatados, secao=Secao.EVOLUCAO)
        concentracao = next(sinal for sinal in sinais if sinal.tipo == "Concentração de eventos")
        assert concentracao.frase.startswith("Julho concentra")

    def test_nao_dispara_concentracao_com_um_evento_por_mes(self):
        sinais = detectar_nos_eventos(
            [Evento(mes(2), "A", "pressiona"), Evento(mes(3), "B", "pressiona")],
            secao=Secao.EVOLUCAO,
        )
        assert "Concentração de eventos" not in tipos_de(sinais)

    def test_se_cala_sem_eventos(self):
        assert detectar_nos_eventos([], secao=Secao.EVOLUCAO) == []


class TestEstudoDePercepcao:
    def test_aponta_o_maior_contraste(self):
        sinais = detectar_no_estudo(
            [("Eficiência operacional", 4.0), ("Solidez financeira", 1.8)],
            secao=Secao.PAINEL_A,
        )
        assert frases_de(sinais) == [
            "Solidez financeira (1,8) fica 2,2 pontos abaixo de eficiência "
            "operacional (4,0) — o maior contraste do estudo."
        ]
        assert sinais[0].evidencia == "−2,2"

    def test_se_cala_com_um_atributo_so(self):
        assert detectar_no_estudo([("Solidez financeira", 1.8)], secao=Secao.PAINEL_A) == []

    def test_se_cala_quando_todos_tem_a_mesma_nota(self):
        """ "0,0 pontos abaixo" passaria por leitura e não é leitura nenhuma."""
        assert detectar_no_estudo([("A", 3.0), ("B", 3.0)], secao=Secao.PAINEL_A) == []

    def test_se_cala_sem_estudo(self):
        assert detectar_no_estudo([], secao=Secao.PAINEL_A) == []


RATING = [
    AcaoDeRating("S&P", mes(5), "pressiona"),
    AcaoDeRating("Fitch", mes(5), "pressiona"),
    AcaoDeRating("Moody's", mes(5), "pressiona"),
    AcaoDeRating("Fitch", mes(7), "pressiona"),
    AcaoDeRating("Moody's", mes(8), "pressiona", perspectiva="negativa"),
]


class TestRating:
    def test_conta_quem_voltou_a_rebaixar_depois_do_primeiro_mes(self):
        sinais = detectar_no_rating(RATING, secao=Secao.PAINEL_B)
        assert frases_de(sinais) == [
            "2 agências voltaram a rebaixar depois de maio; Moody's com perspectiva negativa."
        ]

    def test_as_tres_do_mesmo_mes_sao_um_movimento_so(self):
        """CONTAR AS LINHAS, E NÃO OS MESES, diria que cinco agências se
        mexeram depois de maio — quando foram duas, e as outras três são a
        própria maio."""
        so_maio = RATING[:3]
        assert detectar_no_rating(so_maio, secao=Secao.PAINEL_B) == []

    def test_sem_perspectiva_negativa_a_frase_fecha_no_ponto(self):
        sem_perspectiva = [acao for acao in RATING[:4]]
        sinais = detectar_no_rating(sem_perspectiva, secao=Secao.PAINEL_B)
        assert frases_de(sinais) == ["1 agência voltou a rebaixar depois de maio."]

    def test_ignora_as_acoes_que_nao_pressionam(self):
        elevacoes = [
            AcaoDeRating("S&P", mes(5), "sustenta"),
            AcaoDeRating("Fitch", mes(7), "sustenta"),
        ]
        assert detectar_no_rating(elevacoes, secao=Secao.PAINEL_B) == []

    def test_se_cala_sem_acoes(self):
        assert detectar_no_rating([], secao=Secao.PAINEL_B) == []


class TestProxy:
    def test_e_uma_lacuna_da_lente_inteira(self):
        sinal = sinal_de_proxy()
        assert sinal.tipo == TIPO_DE_LACUNA
        assert sinal.secao is Secao.GERAL
        assert sinal.intensidade == 0
        assert "proxy dos veículos Tier 1" in sinal.frase


RECEBIDAS = [497, 513, 799, 802, 1016, 886, 799, 776]
RESPONDIDAS = [383, 325, 504, 492, 607, 465, 398, 561]
TAXA = [
    (mes(i), respondidas / recebidas)
    for i, (recebidas, respondidas) in enumerate(zip(RECEBIDAS, RESPONDIDAS, strict=True), start=1)
]


class TestVolume:
    def test_aponta_o_pico_de_mensagens_recebidas(self):
        sinais = detectar_no_volume(
            [(mes(i), valor) for i, valor in enumerate(RECEBIDAS, start=1)],
            unidade="mensagens",
            secao=Secao.EVOLUCAO,
            limites=LIMITES,
        )
        assert frases_de(sinais) == [
            "Maio teve o maior volume do período (1.016 mensagens), 1,3× a média mensal."
        ]

    def test_so_produz_pico(self):
        """Mensagem recebida não é positiva nem negativa — é demanda, e passá-la
        pelos detectores de sentimento produziria "a nota caiu" de números que
        não medem nota nenhuma."""
        sinais = detectar_no_volume(
            [(mes(i), valor) for i, valor in enumerate(RECEBIDAS, start=1)],
            unidade="mensagens",
            secao=Secao.EVOLUCAO,
            limites=LIMITES,
        )
        assert tipos_de(sinais) == ["Pico"]

    def test_se_cala_com_menos_de_tres_meses(self):
        assert (
            detectar_no_volume(
                [(mes(1), 100), (mes(2), 900)],
                unidade="mensagens",
                secao=Secao.EVOLUCAO,
                limites=LIMITES,
            )
            == []
        )

    def test_ignora_os_meses_sem_contagem(self):
        assert (
            detectar_no_volume(
                [(mes(1), 100), (mes(2), None), (mes(3), 120)],
                unidade="mensagens",
                secao=Secao.EVOLUCAO,
                limites=LIMITES,
            )
            == []
        )


class TestRecuperacao:
    def test_dispara_depois_de_um_fundo(self):
        sinais = detectar_na_recuperacao(TAXA, secao=Secao.EVOLUCAO, limites=LIMITES)
        assert frases_de(sinais) == [
            "A taxa bruta de resposta voltou a 72% em agosto, após mínima de 50% em julho."
        ]
        assert sinais[0].evidencia == "+22 p.p."

    def test_nao_dispara_quando_o_ultimo_mes_e_o_pior(self):
        """COMPARAR O MÊS CONSIGO MESMO devolveria zero — não dispararia, mas
        por acidente, e o acidente some quando alguém mexe no limite."""
        caindo = [(mes(1), 0.72), (mes(2), 0.60), (mes(3), 0.45)]
        assert detectar_na_recuperacao(caindo, secao=Secao.EVOLUCAO, limites=LIMITES) == []

    def test_nao_dispara_abaixo_do_limite(self):
        parelho = [(mes(1), 0.70), (mes(2), 0.66), (mes(3), 0.72)]
        assert detectar_na_recuperacao(parelho, secao=Secao.EVOLUCAO, limites=LIMITES) == []

    def test_se_cala_com_um_mes_medido_so(self):
        assert (
            detectar_na_recuperacao(
                [(mes(1), None), (mes(2), 0.72)], secao=Secao.EVOLUCAO, limites=LIMITES
            )
            == []
        )


# =============================================================================
# a escolha: manchete, títulos e lista (§3)
# =============================================================================


class TestEscolha:
    def _escolher(self, sinais):
        return escolher(
            sinais, limites=LIMITES, nome_do_painel_a="Painel A", nome_do_painel_b="Painel B"
        )

    def test_o_movimento_recente_vem_antes_da_intensidade(self):
        """A REGRA DE COERÊNCIA DA §3: ao lado da manchete há um chip com a
        variação do último mês. Um sinal antigo e intenso ali faz o leitor
        procurar a relação entre os dois e não achar."""
        sinais = [
            *detectar_nos_itens(
                [Item("Privatização", 5, 5, 90), Item("Patrocínio", 90, 5, 5)],
                secao=Secao.PAINEL_A,
            ),
            *na_serie(serie((60, 0, 40), (40, 0, 60))),
        ]
        leitura = self._escolher(sinais)
        assert leitura.manchete.startswith("A nota caiu")

    def test_cai_para_a_maior_intensidade_com_tom(self):
        sinais = detectar_nos_itens(
            [Item("Privatização", 5, 5, 90), Item("Patrocínio", 90, 5, 5)],
            secao=Secao.PAINEL_A,
        )
        leitura = self._escolher(sinais)
        assert leitura.manchete == ("Privatização concentra o maior negativo: 90% (geral 48%).")

    def test_o_titulo_da_secao_tambem_poe_movimento_antes_de_intensidade(self):
        """Uma Recuperação forte não passa na frente de uma Virada: o título
        diria que a taxa se recuperou enquanto o gráfico embaixo mostra a nota
        virando."""
        recuperacao = detectar_na_recuperacao(
            [(mes(1), 0.20), (mes(2), 0.95)], secao=Secao.EVOLUCAO, limites=LIMITES
        )
        virada = [
            sinal for sinal in na_serie(serie((60, 0, 40), (45, 0, 55))) if sinal.tipo == "Virada"
        ]
        assert recuperacao[0].intensidade > virada[0].intensidade
        leitura = self._escolher([*recuperacao, *virada])
        assert leitura.titulo_da_evolucao.startswith("A nota caiu")

    def test_sem_sinal_nenhum_a_tela_diz_isso(self):
        leitura = self._escolher([])
        assert leitura.manchete == ("Sem variação relevante no período pelas regras atuais.")
        assert leitura.titulo_da_evolucao == (
            "Série mensal sem variação relevante pelas regras atuais."
        )
        assert leitura.sinais_da_evolucao == ["Nenhum sinal acima dos limites configurados."]

    def test_o_painel_sem_sinal_fica_com_o_proprio_nome(self):
        leitura = self._escolher(na_serie(serie((60, 0, 40), (40, 0, 60))))
        assert leitura.titulo_do_painel_a == "Painel A"
        assert leitura.titulo_do_painel_b == "Painel B"

    def test_as_lacunas_vao_para_o_fim_e_nao_ocupam_vaga(self):
        pontos = serie((60, 0, 40), (40, 0, 60), (30, 0, 70), (20, 0, 80), None)
        leitura = escolher(
            na_serie(pontos),
            limites=Limites(max_sinais=1),
            nome_do_painel_a="A",
            nome_do_painel_b="B",
        )
        assert tipos_de(leitura.lista)[-1] == TIPO_DE_LACUNA
        assert len([s for s in leitura.lista if s.tipo != TIPO_DE_LACUNA]) == 1

    def test_o_quadro_da_evolucao_mostra_no_maximo_tres_mais_as_lacunas(self):
        pontos = serie((600, 0, 400), (40, 0, 60), (30, 0, 70), (20, 0, 80), None)
        leitura = self._escolher(na_serie(pontos))
        assert len(leitura.sinais_da_evolucao) == 4
        assert leitura.sinais_da_evolucao[-1].endswith("sem base.")

    def test_a_ordem_desempata_e_a_leitura_e_estavel(self):
        """DUAS LEITURAS SEGUIDAS DÃO A MESMA LISTA. Sem o desempate por ordem,
        dois sinais de mesma intensidade trocariam de lugar entre um F5 e
        outro, e a tela pareceria mudar sem que nada tivesse mudado."""
        empatados = [
            *detectar_nos_itens([Item("A", 5, 0, 5), Item("B", 5, 0, 5)], secao=Secao.PAINEL_A),
            *detectar_nos_itens([Item("C", 5, 0, 5), Item("D", 5, 0, 5)], secao=Secao.PAINEL_B),
        ]
        assert len({sinal.intensidade for sinal in empatados}) == 1, empatados
        primeira = self._escolher(empatados)
        segunda = self._escolher(list(empatados))
        assert frases_de(primeira.lista) == frases_de(segunda.lista)
        assert len(primeira.lista) == 2


# =============================================================================
# §7 · as frases esperadas com os dados de referência
# =============================================================================

IMPRENSA = serie(
    (177, 28, 5),
    (220, 36, 201),
    (484, 76, 51),
    (311, 197, 98),
    (504, 293, 114),
    (1116, 190, 223),
    (461, 113, 61),
    (500, 61, 164),
)

SOCIEDADE = [
    Ponto(mes=mes(1), pos=1843, neu=39, neg=470),
    Ponto(mes=mes(2), pos=495, neu=136, neg=716),
    Ponto(mes=mes(3), pos=518, neu=152, neg=1296),
    Ponto(mes=mes(4), pos=494, neu=129, neg=518),
    Ponto(mes=mes(5), pos=513, neu=98, neg=506),
    Ponto(mes=mes(6), pos=707, neu=142, neg=1110),
    Ponto(mes=mes(7), sem_classificacao=1078),
    Ponto(mes=mes(8), sem_base=True),
]

CLIENTES = serie(
    (125, 119, 253),
    (126, 81, 306),
    (175, 212, 408),
    (131, 293, 378),
    (149, 340, 527),
    (146, 452, 288),
    (88, 435, 276),
    (215, 363, 233),
)

INSTITUCIONAL = [
    *serie((5, 4, 1), (6, 5, 2), (6, 4, 2), (6, 5, 3), (5, 4, 2), (6, 4, 2)),
    Ponto(mes=mes(7), sem_base=True),
    Ponto(mes=mes(8), sem_base=True),
]


def escolha(sinais):
    return escolher(
        sinais, limites=LIMITES, nome_do_painel_a="Painel A", nome_do_painel_b="Painel B"
    )


class TestFrasesDaImprensa:
    SINAIS = [
        *detectar_na_serie(IMPRENSA, unidade="matérias", secao=Secao.EVOLUCAO, limites=LIMITES),
        *detectar_nos_itens(
            [
                Item("Muito Relevante", 65, 64, 16),
                Item("Relevante", 85, 43, 55),
                Item("Menos Relevante", 946, 80, 149),
            ],
            secao=Secao.PAINEL_A,
            rotulo_do_negativo="Tier",
        ),
        *detectar_na_matriz(MATRIZ, secao=Secao.PAINEL_B),
    ]

    def test_a_manchete(self):
        assert escolha(self.SINAIS).manchete == (
            "O negativo subiu de 10% em julho para 23% em agosto."
        )

    def test_o_pico_de_junho(self):
        assert (
            "Junho teve o maior volume do período (1.529 matérias), 2,2× a média mensal."
            in frases_de(self.SINAIS)
        )

    def test_o_tier_que_concentra_o_negativo(self):
        assert "Relevante concentra o maior negativo: 30% (geral 15%)." in frases_de(self.SINAIS)

    def test_nao_gera_deslocamento_porque_agosto_piorou(self):
        assert "Deslocamento" not in tipos_de(self.SINAIS)


class TestFrasesDoMercado:
    SINAIS = [
        *detectar_nos_eventos(EVENTOS, secao=Secao.EVOLUCAO),
        *detectar_no_estudo(
            [("Eficiência operacional", 4.0), ("Solidez financeira", 1.8)],
            secao=Secao.PAINEL_A,
        ),
        *detectar_no_rating(RATING, secao=Secao.PAINEL_B),
        sinal_de_proxy(),
    ]

    def test_o_contraste_do_estudo(self):
        assert (
            "Solidez financeira (1,8) fica 2,2 pontos abaixo de eficiência "
            "operacional (4,0) — o maior contraste do estudo." in frases_de(self.SINAIS)
        )

    def test_a_trajetoria_de_rating(self):
        assert (
            "2 agências voltaram a rebaixar depois de maio; "
            "Moody's com perspectiva negativa." in frases_de(self.SINAIS)
        )

    def test_a_lente_avisa_que_a_nota_e_proxy(self):
        leitura = escolha(self.SINAIS)
        assert frases_de(leitura.lista)[-1].startswith("Mercado sem série mensal")


class TestFrasesDaSociedade:
    SINAIS = [
        *detectar_na_serie(SOCIEDADE, unidade="menções", secao=Secao.EVOLUCAO, limites=LIMITES),
        *detectar_nos_itens(
            [
                Item("Patrocínio", 97.1, 0.9, 2),
                Item("Marca Empregadora", 94, 4.9, 1.1),
                Item("Saneamento básico", 18.5, 5.5, 76),
                Item("Atendimento", 23.5, 29.4, 47.1),
                Item("Obra", 20.7, 12.2, 67.1),
                Item("Privatização", 9.4, 11, 79.6),
            ],
            secao=Secao.PAINEL_A,
            percentual=True,
        ),
        *detectar_no_ranking(
            [("Corsan", 2515), ("Águas do Rio", 318)],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="a segunda unidade",
            unidade="menções",
            limites=LIMITES,
        ),
    ]

    def test_a_manchete(self):
        assert escolha(self.SINAIS).manchete == (
            "A nota caiu 10 pontos em junho: o negativo foi de 45% para 57%."
        )

    def test_a_concentracao_por_unidade(self):
        assert "Corsan tem 7,9× o volume de Águas do Rio, a segunda unidade." in frases_de(
            self.SINAIS
        )

    def test_o_tema_que_concentra_o_negativo(self):
        assert "Privatização concentra o maior negativo: 80%." in frases_de(self.SINAIS)

    def test_a_lacuna_separa_julho_de_agosto(self):
        assert "Sentimento de julho ainda não integrado. Agosto sem base." in frases_de(self.SINAIS)


class TestFrasesDosClientes:
    SINAIS = [
        *detectar_no_volume(
            [(mes(i), valor) for i, valor in enumerate(RECEBIDAS, start=1)],
            unidade="mensagens",
            secao=Secao.EVOLUCAO,
            limites=LIMITES,
        ),
        *detectar_na_recuperacao(TAXA, secao=Secao.EVOLUCAO, limites=LIMITES),
        *detectar_na_serie(
            CLIENTES,
            unidade="mensagens",
            secao=Secao.PAINEL_A,
            limites=LIMITES,
            com_pico=False,
        ),
        *detectar_no_percentual(
            [(mes(5), 59.0), (mes(6), 46.0), (mes(7), 47.0), (mes(8), 34.0)],
            nome="Reclamação",
            secao=Secao.PAINEL_B,
            limites=LIMITES,
        ),
    ]

    def test_a_manchete(self):
        assert escolha(self.SINAIS).manchete == (
            "A nota subiu 11 pontos em agosto: o negativo foi de 35% para 29%."
        )

    def test_o_deslocamento_desde_fevereiro(self):
        assert "O negativo recuou de 60% em fevereiro para 29% em agosto." in frases_de(self.SINAIS)

    def test_o_teor_de_reclamacao(self):
        assert (
            "Reclamação caiu de 59% em maio para 34% em agosto, o menor peso do período."
            in frases_de(self.SINAIS)
        )

    def test_a_taxa_de_resposta_se_recuperou(self):
        assert (
            "A taxa bruta de resposta voltou a 72% em agosto, após mínima de 50% em julho."
            in frases_de(self.SINAIS)
        )


class TestFrasesDoInstitucional:
    SINAIS = [
        *detectar_na_serie(INSTITUCIONAL, unidade="agendas", secao=Secao.EVOLUCAO, limites=LIMITES),
        *detectar_nos_itens(
            [
                Item("Regulação e marco legal", 8, 3, 1),
                Item("Inclusão sanitária", 6, 2, 0),
                Item("Resíduos e biometano", 4, 2, 0),
                Item("Tarifa e reequilíbrio", 2, 2, 4),
                Item("Copasa / ALMG", 1, 1, 3),
            ],
            secao=Secao.PAINEL_A,
        ),
        *detectar_no_ranking(
            [
                ("ANA", 9),
                ("BNDES", 7),
                ("ABCON", 6),
                ("Câmara dos Deputados", 5),
                ("ALMG", 4),
                ("Senado Federal", 3),
            ],
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="o segundo órgão",
            unidade="agendas",
            limites=LIMITES,
        ),
    ]

    def test_o_tema_que_concentra_o_negativo(self):
        assert "Copasa / ALMG concentra o maior negativo: 60% (geral 21%)." in frases_de(
            self.SINAIS
        )

    def test_a_tendencia_de_tres_meses(self):
        assert "O negativo cai há 3 meses seguidos: 21% → 18% → 17%." in frases_de(self.SINAIS)


# =============================================================================
# o idioma das frases (§6)
# =============================================================================


class TestIdioma:
    @pytest.mark.parametrize(
        "sinais",
        [
            TestFrasesDaImprensa.SINAIS,
            TestFrasesDoMercado.SINAIS,
            TestFrasesDaSociedade.SINAIS,
            TestFrasesDosClientes.SINAIS,
            TestFrasesDoInstitucional.SINAIS,
        ],
        ids=["imprensa", "mercado", "sociedade", "clientes", "institucional"],
    )
    def test_toda_frase_e_uma_oracao_terminada(self, sinais):
        for frase in frases_de(sinais):
            assert frase[0].isupper() or frase[0].isdigit(), frase
            assert frase.endswith("."), frase

    @pytest.mark.parametrize(
        "sinais",
        [
            TestFrasesDaImprensa.SINAIS,
            TestFrasesDaSociedade.SINAIS,
            TestFrasesDosClientes.SINAIS,
        ],
        ids=["imprensa", "sociedade", "clientes"],
    )
    def test_nenhum_mes_aparece_abreviado_ou_em_numero(self, sinais):
        """ "jan" e "2026-01" são ruído numa frase de diretoria."""
        for frase in frases_de(sinais):
            assert "2026" not in frase, frase
            for abreviado in ("jan", "fev", "mar", "abr", "jun", "jul", "ago"):
                assert f" {abreviado} " not in frase, frase

    def test_o_milhar_usa_ponto(self):
        frase = frases_de(TestFrasesDaImprensa.SINAIS)
        assert any("1.529" in linha for linha in frase)

    def test_a_escala_de_um_a_cinco_sempre_com_uma_casa(self):
        frase = frases_de(TestFrasesDoMercado.SINAIS)
        assert any("(4,0)" in linha for linha in frase)


# =============================================================================
# os limites vêm da Calibração (§5)
# =============================================================================


class TestLimites:
    def test_o_que_nao_foi_mexido_fica_no_padrao_de_fabrica(self):
        limites = Limites.a_partir_de({"virada_pontos": 6})
        assert limites.virada_pontos == 6
        assert limites.pico_desvios == Limites().pico_desvios

    def test_sem_ajuste_nenhum_e_a_regua_de_fabrica(self):
        assert Limites.a_partir_de({}) == Limites()

    def test_recusa_uma_chave_que_nao_existe(self):
        """UM `picoDesvios` EM CAMELCASE SERIA ACEITO EM SILÊNCIO: a pessoa
        veria "salvo", o limite continuaria o de fábrica, e ela passaria a
        semana achando que o detector está errado."""
        with pytest.raises(RegraViolada, match="picoDesvios"):
            Limites.a_partir_de({"picoDesvios": 2})

    @pytest.mark.parametrize(
        "chave",
        [
            "pico_desvios",
            "pico_razao_minima",
            "virada_pontos",
            "deslocamento_pp",
            "concentracao_razao",
        ],
    )
    def test_recusa_o_zero_em_todo_corte_que_e_divisor(self, chave):
        """Um zero gravado não daria erro na tela da Calibração: estouraria
        horas depois, na tela de outra pessoa abrindo uma lente."""
        with pytest.raises(RegraViolada, match="maior que zero"):
            Limites.a_partir_de({chave: 0})

    def test_recusa_uma_tendencia_de_um_mes(self):
        with pytest.raises(RegraViolada, match="dois meses"):
            Limites.a_partir_de({"tendencia_meses": 1})

    def test_recusa_uma_concentracao_fora_da_porcentagem(self):
        with pytest.raises(RegraViolada, match="entre 1 e 100"):
            Limites.a_partir_de({"concentracao_top3": 140})

    def test_recusa_uma_lista_sem_vaga_nenhuma(self):
        with pytest.raises(RegraViolada, match="ao menos um sinal"):
            Limites.a_partir_de({"max_sinais": 0})

    def test_os_meses_chegam_inteiros_mesmo_escritos_com_virgula(self):
        """ "3,0 meses seguidos" não significa nada, e o JSON pode trazer float
        de qualquer jeito — o campo da tela não é a única defesa."""
        assert Limites.a_partir_de({"tendencia_meses": 3.0}).tendencia_meses == 3

    def test_baixar_o_limite_faz_o_sinal_aparecer(self):
        """O critério da §7: mudar um limite na Calibração altera os sinais sem
        deploy."""
        pontos = serie((70, 0, 30), (66, 0, 34))
        de_fabrica = detectar_na_serie(
            pontos, unidade="matérias", secao=Secao.EVOLUCAO, limites=Limites()
        )
        assert "Virada" not in tipos_de(de_fabrica)

        calibrado = detectar_na_serie(
            pontos,
            unidade="matérias",
            secao=Secao.EVOLUCAO,
            limites=Limites.a_partir_de({"virada_pontos": 3}),
        )
        assert "Virada" in tipos_de(calibrado)

    def test_encurtar_a_lista_corta_os_sinais_mais_fracos(self):
        sinais = detectar_nos_itens(
            [Item("Privatização", 5, 5, 90), Item("Patrocínio", 90, 5, 5)],
            secao=Secao.PAINEL_A,
        )
        assert len(sinais) == 2
        leitura = escolher(
            sinais,
            limites=Limites.a_partir_de({"max_sinais": 1}),
            nome_do_painel_a="A",
            nome_do_painel_b="B",
        )
        assert len(leitura.lista) == 1
