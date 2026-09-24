"""O assunto que mais pesou — a conta que precisa fechar.

O QUE ESTES TESTES PROVAM é que a frase é defensável. "Saneamento básico custou
6,9 pontos do índice em junho" é uma afirmação que alguém pode conferir na mão,
e se a decomposição não fechar com o próprio índice ela vira impressão — o tipo
de número que destrói a confiança no painel quando alguém confere.
"""

from __future__ import annotations

import pytest

from app.dominio.assunto_do_mes import (
    MencoesDoAssunto,
    assuntos_que_pesaram,
    pontos_no_indice,
)


def mencoes(
    assunto: str,
    *,
    lente: str = "sociedade",
    pos: int = 0,
    neg: int = 0,
    total: int = 1000,
) -> MencoesDoAssunto:
    return MencoesDoAssunto(
        lente=lente, assunto=assunto, positivas=pos, negativas=neg, total_da_lente=total
    )


PESOS = {"imprensa": 30, "mercado": 20, "sociedade": 20, "clientes": 15, "institucional": 15}


class TestPontosNoIndice:
    def test_um_assunto_só_negativo_custa_pontos(self):
        # Metade das menções da lente, todas negativas, numa lente de peso 20:
        # −0,5 de NS × 50 × 0,20 = −5 pontos do índice.
        assert pontos_no_indice(mencoes("Privatização", neg=500), 20) == pytest.approx(-5)

    def test_o_mesmo_assunto_positivo_dá_pontos(self):
        assert pontos_no_indice(mencoes("Patrocínio", pos=500), 20) == pytest.approx(5)

    def test_um_assunto_equilibrado_não_pesa(self):
        # Quinhentas menções não movem nada quando metade sustenta e metade
        # pressiona — e é por isso que VOLUME não é peso.
        assert pontos_no_indice(mencoes("Obra", pos=250, neg=250), 20) == 0

    def test_a_lente_sem_menção_não_estoura(self):
        assert pontos_no_indice(mencoes("Nada", neg=5, total=0), 20) == 0

    def test_o_peso_da_lente_escala_o_resultado(self):
        # O mesmo assunto, a mesma proporção, em duas lentes: quem pesa mais no
        # índice leva mais pontos.
        na_imprensa = pontos_no_indice(mencoes("X", lente="imprensa", neg=500), 30)
        na_sociedade = pontos_no_indice(mencoes("X", neg=500), 20)
        assert na_imprensa == pytest.approx(na_sociedade * 30 / 20)

    def test_A_CONTA_FECHA_com_o_score_da_lente(self):
        """A soma dos assuntos recupera o que a lente pôs no índice.

        É a propriedade que torna a frase auditável. Uma lente com NS de −0,4 e
        peso 20 contribui com `(−0,4) × 50 × 0,20 = −4` pontos além da base de
        50 — e os assuntos dela têm de somar exatamente isso.
        """
        # 300 positivas, 700 negativas, total 1000 → NS = −0,4.
        partes = [
            mencoes("A", pos=300, neg=100),
            mencoes("B", neg=400),
            mencoes("C", neg=200),
        ]
        soma = sum(pontos_no_indice(parte, 20) for parte in partes)
        assert soma == pytest.approx(-0.4 * 50 * 0.20)


class TestAssuntosQuePesaram:
    def test_devolve_os_DOIS_lados_do_mês(self):
        # Um mês resumido pelo pior assunto parece um mês perdido; com os dois,
        # a mesma coluna mostra a disputa que houve.
        dos_lados = assuntos_que_pesaram(
            [
                mencoes("Universalização", lente="imprensa", pos=755, total=1500),
                mencoes("Saneamento básico", pos=125, neg=759),
                mencoes("Privatização", pos=5, neg=110),
            ],
            PESOS,
        )
        assert dos_lados.sustentou is not None
        assert dos_lados.sustentou.assunto == "Universalização"
        assert dos_lados.sustentou.efeito == "sustenta"
        assert dos_lados.pressionou is not None
        assert dos_lados.pressionou.assunto == "Saneamento básico"
        assert dos_lados.pressionou.efeito == "pressiona"

    def test_um_mês_só_de_pressão_não_inventa_quem_sustentou(self):
        so_ruim = assuntos_que_pesaram([mencoes("Privatização", neg=300)], PESOS)
        assert so_ruim.sustentou is None
        assert so_ruim.pressionou is not None

    def test_um_mês_só_de_reforço_não_inventa_quem_pressionou(self):
        so_bom = assuntos_que_pesaram([mencoes("Patrocínio", pos=300)], PESOS)
        assert so_bom.pressionou is None
        assert so_bom.sustentou is not None

    def test_a_lente_fora_do_cálculo_não_concorre(self):
        """Peso efetivo zero significa que o índice ignorou a lente. O assunto
        mais falado dela não pesou nada."""
        dos_lados = assuntos_que_pesaram(
            [
                mencoes("Enorme", lente="mercado", neg=900),
                mencoes("Menor", neg=100),
            ],
            {"sociedade": 20, "mercado": 0},
        )
        assert dos_lados.pressionou is not None
        assert dos_lados.pressionou.assunto == "Menor"

    def test_o_empate_devolve_sempre_a_mesma_resposta(self):
        """A coluna do mês não pode mudar de texto entre duas leituras sem nada
        ter mudado."""
        empatados = [mencoes("Zebra", neg=100), mencoes("Abelha", neg=100)]
        primeiro = assuntos_que_pesaram(empatados, PESOS)
        segundo = assuntos_que_pesaram(list(reversed(empatados)), PESOS)
        assert primeiro.pressionou is not None and segundo.pressionou is not None
        assert primeiro.pressionou.assunto == segundo.pressionou.assunto == "Abelha"

    def test_mês_sem_assunto_que_pese_não_inventa_nenhum(self):
        vazio = assuntos_que_pesaram([], PESOS)
        assert vazio.sustentou is None and vazio.pressionou is None

        neutro = assuntos_que_pesaram([mencoes("Neutro", pos=50, neg=50)], PESOS)
        assert neutro.sustentou is None and neutro.pressionou is None

    def test_sem_peso_nenhum_não_há_assunto(self):
        nada = assuntos_que_pesaram([mencoes("X", neg=100)], {})
        assert nada.sustentou is None and nada.pressionou is None
