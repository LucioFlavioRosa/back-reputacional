"""Quanto cada tema pesou no índice do mês — e por que a conta fecha.

O FATO CADASTRADO DIZ O QUE ACONTECEU NO MUNDO: "saíram as demonstrações
financeiras". Este módulo responde a outra metade da pergunta: POR ONDE aquilo
entrou no número. São coisas diferentes e complementares, e por isso aparecem
lado a lado na coluna do mês — uma escrita por gente, outra derivada da base.

A CONTA É DECOMPOSIÇÃO EXATA, e refazer o caminho inteiro do índice é o que a
torna exata. A primeira versão deste módulo contava menções cruas, e errava por
4,3 pontos num mês real — porque ignorava as duas coisas que o índice faz antes
de somar:

    o tier pondera      uma capa do Valor vale 10 e um blog local vale 1, na
                        régua da Aegea. Contar as duas como uma menção cada faz
                        o tema do blog parecer pesar o mesmo
    a lente é MÉDIA     com duas fontes, o NS da lente é a média simples dos
                        dois NS, e não o NS do bolo junto. Juntar tudo num
                        denominador só dá outro número

Refazendo o caminho, a contribuição de um tema é:

    dentro da fonte     (ponderado_pos − ponderado_neg) / ponderado_total_f
    na lente            ÷ número de fontes com dado (a média)
    no índice           × 50 × peso_efetivo / 100

SOMANDO OS ASSUNTOS DE UMA LENTE recupera-se exatamente o NS dela — DESDE QUE
TODA MENÇÃO TENHA ASSUNTO. É isso que torna a frase defensável: "Saneamento
básico custou 6,9 pontos do índice em junho" é uma afirmação que alguém pode
conferir na mão, e não uma impressão.

E A RESSALVA NÃO É TEÓRICA. Hoje a Bites não classifica tema em nenhuma das
suas menções, e ela é metade da lente Sociedade digital: metade daquela lente
move o índice sem que nenhum tema possa ser responsabilizado. Por isso
`TemasDoMes` carrega `pontos_sem_tema` — mostrar dois temas e calar
sobre o pedaço que não se explica faria a coluna do mês afirmar mais do que
sabe. A LACUNA É DO DADO, e não da conta: ela some no dia em que a fonte
entregar o tema.

E UMA LENTE ESTIMADA CAI NO MESMO BALDE, por um motivo diferente e igualmente
honesto: quando o mês não tem medição e o NS vem do resumo semestral, não há
menção nenhuma para repartir entre temas. Ela moveu o índice e nenhum
tema pode ser responsabilizado — que é exatamente o que
`pontos_sem_tema` diz.

DOIS ASSUNTOS, E NÃO UM. O que mais segurou e o que mais puxou, lado a lado: um
mês fechado com o maior negativo em destaque parece um mês perdido, e o mesmo
mês com os dois mostra a disputa que de fato houve.

O sinal vira o mesmo `efeito` que o fato cadastrado carrega — `sustenta` ou
`pressiona` —, e é o que permite os dois aparecerem na mesma coluna sem
explicação extra.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Meia escala: o score vai de 0 a 100 e o NS de −1 a 1.
PONTOS_POR_NS = 50


@dataclass(frozen=True, slots=True)
class PesosDoTema:
    """Um tema dentro de uma FONTE, com as somas já ponderadas.

    O GRÃO É A FONTE, e não a lente, porque é nela que o NS se forma: a lente é
    a média dos NS das fontes dela.
    """

    lente: str
    fonte: str
    tema: str
    #: Já multiplicados pelo tier e pela medida de engajamento em vigor.
    positivas: float
    negativas: float
    #: O total ponderado da FONTE no mês — o denominador do NS dela.
    total_da_fonte: float
    #: Quantas fontes desta lente tiveram dado no mês. É o divisor da média.
    fontes_da_lente: int
    #: As contagens cruas, só para a tela dizer "755 positivas".
    mencoes_positivas: int
    mencoes_negativas: int


@dataclass(frozen=True, slots=True)
class TemaDoMes:
    """O tema e quanto ele mexeu no índice."""

    tema: str
    lente: str
    #: Pontos do ÍNDICE, com sinal. Negativo puxou para baixo.
    pontos: float
    positivas: int
    negativas: int

    @property
    def efeito(self) -> str:
        """O mesmo vocabulário do fato cadastrado, para a coluna não precisar
        explicar que um veio da base e o outro de alguém."""
        return "sustenta" if self.pontos > 0 else "pressiona"


@dataclass(frozen=True, slots=True)
class TemasDoMes:
    """Os dois lados da disputa do mês. Qualquer um pode faltar."""

    sustentou: TemaDoMes | None = None
    pressionou: TemaDoMes | None = None
    #: Pontos do índice que NENHUM tema explica — menções que moveram a nota
    #: sem tema classificado. Com a Bites hoje, é metade da Sociedade digital.
    pontos_sem_tema: float = 0.0


def contribuicao_no_ns(peso: PesosDoTema) -> float:
    """Quanto este tema pôs no NS da LENTE, com sinal.

    DIVIDIDO PELO NÚMERO DE FONTES porque a lente é a média delas: um tema
    que domina uma fonte de duas mexe metade do que mexeria se a fonte fosse
    única. Sem esse divisor, uma lente de duas fontes soma o dobro do que de
    fato tem.
    """
    if not peso.total_da_fonte or not peso.fontes_da_lente:
        return 0.0
    saldo = (peso.positivas - peso.negativas) / peso.total_da_fonte
    return saldo / peso.fontes_da_lente


def pontos_no_indice(peso: PesosDoTema, peso_efetivo: int) -> float:
    """A contribuição do tema convertida em pontos do índice."""
    return contribuicao_no_ns(peso) * PONTOS_POR_NS * peso_efetivo / 100


def _para_assunto(pontos: float, peso: PesosDoTema) -> TemaDoMes:
    return TemaDoMes(
        tema=peso.tema,
        lente=peso.lente,
        pontos=round(pontos, 1),
        positivas=peso.mencoes_positivas,
        negativas=peso.mencoes_negativas,
    )


def temas_que_pesaram(
    pesos: list[PesosDoTema],
    pesos_efetivos: dict[str, float],
    pontos_das_lentes: dict[str, float] | None = None,
) -> TemasDoMes:
    """O tema que mais segurou o índice, e o que mais puxou.

    O MESMO ASSUNTO EM DUAS FONTES CONTA JUNTO: "Privatização" na Approach e na
    Bites é um tema só para quem lê, e mostrá-lo duas vezes na mesma coluna
    faria a leitura parecer um erro de listagem.

    A LENTE FORA DO CÁLCULO NÃO ENTRA: ela tem peso efetivo zero, e um tema
    que vale zero ponto não pesou — seria só o mais falado de uma lente que o
    índice ignorou.

    O EMPATE FICA COM O NOME, em ordem alfabética. Dois temas com o mesmo
    peso precisam devolver sempre a mesma resposta: a coluna do mês não pode
    mudar de texto entre duas leituras sem nada ter mudado.
    """
    somados: dict[tuple[str, str], list[float | int]] = {}
    for peso in pesos:
        if not pesos_efetivos.get(peso.lente):
            continue
        chave = (peso.lente, peso.tema)
        atual = somados.setdefault(chave, [0.0, 0, 0])
        atual[0] = float(atual[0]) + pontos_no_indice(peso, pesos_efetivos[peso.lente])
        atual[1] = int(atual[1]) + peso.mencoes_positivas
        atual[2] = int(atual[2]) + peso.mencoes_negativas

    candidatos = [
        (
            float(valores[0]),
            PesosDoTema(
                lente=lente,
                fonte="",
                tema=tema,
                positivas=0,
                negativas=0,
                total_da_fonte=0,
                fontes_da_lente=0,
                mencoes_positivas=int(valores[1]),
                mencoes_negativas=int(valores[2]),
            ),
        )
        for (lente, tema), valores in somados.items()
        if valores[0]
    ]

    positivos = [(p, m) for p, m in candidatos if p > 0]
    negativos = [(p, m) for p, m in candidatos if p < 0]

    # O QUE SOBRA É O QUE NINGUÉM EXPLICA. `pontos_das_lentes` é o que cada
    # lente de fato pôs no índice; a diferença para a soma dos temas são as
    # menções sem tema — e dizê-la é o que impede a coluna de afirmar mais do
    # que sabe.
    explicado = sum(float(valores[0]) for valores in somados.values())
    total = sum(pontos_das_lentes.values()) if pontos_das_lentes else explicado

    return TemasDoMes(
        pontos_sem_tema=round(total - explicado, 1),
        sustentou=(
            _para_assunto(*min(positivos, key=lambda par: (-par[0], par[1].tema)))
            if positivos
            else None
        ),
        pressionou=(
            _para_assunto(*min(negativos, key=lambda par: (par[0], par[1].tema)))
            if negativos
            else None
        ),
    )
