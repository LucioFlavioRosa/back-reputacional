"""O tema que mais pesou — a conta que precisa fechar.

O QUE ESTES TESTES PROVAM é que a frase é defensável. "Saneamento básico custou
1,9 ponto do índice em junho" é uma afirmação que alguém pode conferir na mão, e
se a decomposição não fechar com o próprio índice ela vira impressão — o tipo de
número que destrói a confiança no painel quando alguém confere.

A PRIMEIRA VERSÃO NÃO FECHAVA, e o teste da época não pegava: ele montava um
caso sem ponderação de tier e com uma fonte só, que é justamente onde a conta
errada acerta. Medida contra o índice real, ela errava por 4,3 pontos. Os testes
abaixo montam os dois casos que faltavam.
"""

from __future__ import annotations

import pytest

from app.dominio.tema_do_mes import (
    PesosDoTema,
    contribuicao_no_ns,
    pontos_no_indice,
    temas_que_pesaram,
)


def peso(
    tema: str,
    *,
    lente: str = "sociedade",
    fonte: str = "approach_sl",
    pos: float = 0,
    neg: float = 0,
    total: float = 1000,
    fontes: int = 1,
    cruas_pos: int = 0,
    cruas_neg: int = 0,
) -> PesosDoTema:
    return PesosDoTema(
        lente=lente,
        fonte=fonte,
        tema=tema,
        positivas=pos,
        negativas=neg,
        total_da_fonte=total,
        fontes_da_lente=fontes,
        mencoes_positivas=cruas_pos or int(pos),
        mencoes_negativas=cruas_neg or int(neg),
    )


PESOS = {"imprensa": 30, "mercado": 20, "sociedade": 20, "clientes": 15, "institucional": 15}


class TestContribuicaoNoNs:
    def test_um_assunto_só_negativo_puxa_o_ns(self):
        # Metade do peso da fonte, todo negativo, numa fonte única: −0,5 de NS.
        assert contribuicao_no_ns(peso("Privatização", neg=500)) == pytest.approx(-0.5)

    def test_a_LENTE_É_MÉDIA_das_fontes(self):
        # O mesmo tema, na mesma proporção, numa lente de DUAS fontes: ele
        # mexe metade, porque a outra fonte entra com o mesmo direito de voto.
        # Ignorar isto era metade do erro de 4,3 pontos.
        de_uma = contribuicao_no_ns(peso("X", neg=500, fontes=1))
        de_duas = contribuicao_no_ns(peso("X", neg=500, fontes=2))
        assert de_duas == pytest.approx(de_uma / 2)

    def test_um_assunto_equilibrado_não_pesa(self):
        # Quinhentas menções não movem nada quando metade sustenta e metade
        # pressiona — e é por isso que VOLUME não é peso.
        assert contribuicao_no_ns(peso("Obra", pos=250, neg=250)) == 0

    def test_a_fonte_sem_peso_não_estoura(self):
        assert contribuicao_no_ns(peso("Nada", neg=5, total=0)) == 0
        assert contribuicao_no_ns(peso("Nada", neg=5, fontes=0)) == 0

    def test_A_CONTA_FECHA_com_o_ns_da_fonte(self):
        """A soma dos temas recupera o NS da fonte.

        É a propriedade que torna a frase auditável. Uma fonte com 300 de peso
        positivo e 700 de negativo, sobre 1000, tem NS de −0,4 — e os temas
        dela têm de somar exatamente isso.
        """
        partes = [
            peso("A", pos=300, neg=100),
            peso("B", neg=400),
            peso("C", neg=200),
        ]
        assert sum(contribuicao_no_ns(parte) for parte in partes) == pytest.approx(-0.4)

    def test_A_CONTA_FECHA_com_DUAS_fontes(self):
        """O caso que o teste antigo não montava — e onde a conta errada errava.

        Duas fontes, cada uma com o seu NS; a lente é a média. A soma das
        contribuições precisa dar essa média, e não o NS do bolo junto.
        """
        # Fonte A: NS = −0,4. Fonte B: NS = +0,2. Média = −0,1.
        de_a = [peso("X", pos=300, neg=700, fontes=2, fonte="a")]
        de_b = [peso("Y", pos=600, neg=400, fontes=2, fonte="b")]
        soma = sum(contribuicao_no_ns(p) for p in de_a + de_b)
        assert soma == pytest.approx((-0.4 + 0.2) / 2)

    def test_O_TIER_JÁ_VEM_APLICADO_nas_somas(self):
        """A ponderação não mora aqui: chega pronta do repositório.

        Uma matéria Muito Relevante entra valendo 10 na régua da Aegea, e é a
        consulta que multiplica. O que este módulo recebe já é peso, e não
        contagem — era a outra metade do erro de 4,3 pontos.
        """
        # Uma única matéria negativa de peso 10, numa fonte de peso total 100.
        uma_capa = peso("Acusações", lente="imprensa", neg=10, total=100, cruas_neg=1)
        assert contribuicao_no_ns(uma_capa) == pytest.approx(-0.1)
        # E a tela continua podendo dizer "1 menção".
        assert uma_capa.mencoes_negativas == 1


class TestPontosNoIndice:
    def test_converte_o_ns_em_pontos_do_índice(self):
        # −0,5 de NS numa lente de peso 20: −0,5 × 50 × 0,20 = −5 pontos.
        assert pontos_no_indice(peso("Privatização", neg=500), 20) == pytest.approx(-5)

    def test_o_peso_da_lente_escala_o_resultado(self):
        na_imprensa = pontos_no_indice(peso("X", lente="imprensa", neg=500), 30)
        na_sociedade = pontos_no_indice(peso("X", neg=500), 20)
        assert na_imprensa == pytest.approx(na_sociedade * 30 / 20)


class TestAssuntosQuePesaram:
    def test_devolve_os_DOIS_lados_do_mês(self):
        # Um mês resumido pelo pior tema parece um mês perdido; com os dois,
        # a mesma coluna mostra a disputa que houve.
        dos_lados = temas_que_pesaram(
            [
                peso("Universalização", lente="imprensa", fonte="clipei", pos=755, total=1500),
                peso("Saneamento básico", pos=125, neg=759),
                peso("Privatização", pos=5, neg=110),
            ],
            PESOS,
        )
        assert dos_lados.sustentou is not None
        assert dos_lados.sustentou.tema == "Universalização"
        assert dos_lados.sustentou.efeito == "sustenta"
        assert dos_lados.pressionou is not None
        assert dos_lados.pressionou.tema == "Saneamento básico"
        assert dos_lados.pressionou.efeito == "pressiona"

    def test_o_mesmo_assunto_em_duas_fontes_conta_JUNTO(self):
        """ "Privatização" na Approach e na Bites é um tema só para quem lê;
        mostrá-lo duas vezes faria a coluna parecer erro de listagem."""
        dos_lados = temas_que_pesaram(
            [
                peso("Privatização", fonte="approach_sl", neg=300, fontes=2, cruas_neg=300),
                peso("Privatização", fonte="bites", neg=200, fontes=2, cruas_neg=200),
            ],
            PESOS,
        )
        assert dos_lados.pressionou is not None
        assert dos_lados.pressionou.tema == "Privatização"
        assert dos_lados.pressionou.negativas == 500

    def test_um_mês_só_de_pressão_não_inventa_quem_sustentou(self):
        so_ruim = temas_que_pesaram([peso("Privatização", neg=300)], PESOS)
        assert so_ruim.sustentou is None
        assert so_ruim.pressionou is not None

    def test_um_mês_só_de_reforço_não_inventa_quem_pressionou(self):
        so_bom = temas_que_pesaram([peso("Patrocínio", pos=300)], PESOS)
        assert so_bom.pressionou is None
        assert so_bom.sustentou is not None

    def test_a_lente_fora_do_cálculo_não_concorre(self):
        """Peso efetivo zero significa que o índice ignorou a lente. O tema
        mais falado dela não pesou nada."""
        dos_lados = temas_que_pesaram(
            [
                peso("Enorme", lente="mercado", fonte="clipei_investidores", neg=900),
                peso("Menor", neg=100),
            ],
            {"sociedade": 20, "mercado": 0},
        )
        assert dos_lados.pressionou is not None
        assert dos_lados.pressionou.tema == "Menor"

    def test_o_empate_devolve_sempre_a_mesma_resposta(self):
        """A coluna do mês não pode mudar de texto entre duas leituras sem nada
        ter mudado."""
        empatados = [peso("Zebra", neg=100), peso("Abelha", neg=100)]
        primeiro = temas_que_pesaram(empatados, PESOS)
        segundo = temas_que_pesaram(list(reversed(empatados)), PESOS)
        assert primeiro.pressionou is not None and segundo.pressionou is not None
        assert primeiro.pressionou.tema == segundo.pressionou.tema == "Abelha"

    def test_mês_sem_assunto_que_pese_não_inventa_nenhum(self):
        vazio = temas_que_pesaram([], PESOS)
        assert vazio.sustentou is None and vazio.pressionou is None

        neutro = temas_que_pesaram([peso("Neutro", pos=50, neg=50)], PESOS)
        assert neutro.sustentou is None and neutro.pressionou is None


class TestPontosSemAssunto:
    """O pedaço que nenhum tema explica.

    NÃO É ERRO DE CONTA, É LACUNA DE DADO. Hoje a Bites não classifica tema
    em nenhuma menção, e ela é metade da Sociedade digital: metade daquela
    lente move o índice sem que nada possa ser responsabilizado. Mostrar dois
    temas e calar sobre o resto faria a coluna afirmar mais do que sabe.
    """

    def test_diz_quanto_ficou_sem_explicação(self):
        # A lente pôs −5 pontos; o tema conhecido explica −2.
        dos_lados = temas_que_pesaram(
            [peso("Conhecido", neg=200, total=1000)],
            {"sociedade": 20},
            {"sociedade": -5.0},
        )
        assert dos_lados.pressionou is not None
        assert dos_lados.pressionou.pontos == pytest.approx(-2)
        assert dos_lados.pontos_sem_tema == pytest.approx(-3)

    def test_sem_lacuna_quando_todo_assunto_é_conhecido(self):
        dos_lados = temas_que_pesaram(
            [peso("Tudo", neg=1000, total=1000)],
            {"sociedade": 20},
            {"sociedade": -10.0},
        )
        assert dos_lados.pontos_sem_tema == pytest.approx(0)

    def test_sem_os_pontos_das_lentes_não_inventa_lacuna(self):
        """Quem não passa o total não recebe uma lacuna calculada do nada."""
        dos_lados = temas_que_pesaram([peso("X", neg=200)], {"sociedade": 20})
        assert dos_lados.pontos_sem_tema == 0
