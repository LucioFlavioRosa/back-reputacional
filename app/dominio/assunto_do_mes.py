"""Quanto cada assunto pesou no índice do mês — e por que a conta fecha.

O FATO CADASTRADO DIZ O QUE ACONTECEU NO MUNDO: "saíram as demonstrações
financeiras". Este módulo responde a outra metade da pergunta: POR ONDE aquilo
entrou no número. São coisas diferentes e complementares, e por isso aparecem
lado a lado na coluna do mês — uma escrita por gente, outra derivada da base.

A CONTA É DECOMPOSIÇÃO EXATA, e não estimativa. O índice de um mês é

    ISR = Σ (score da lente × peso efetivo) / 100

e o score de uma lente é `(NS + 1) / 2 × 100`, com `NS = (pos − neg) / total`.
Um assunto dentro da lente contribui com `(pos_t − neg_t) / total_l` para o NS
dela; multiplicado por 50 e pelo peso efetivo, vira pontos do ÍNDICE.

    pontos do assunto = (pos_t − neg_t) / total_l × 50 × peso_l / 100

SOMANDO OS ASSUNTOS DE UMA LENTE recupera-se exatamente o que ela pôs no
índice, fora a parte constante dos 50 pontos de base. É isso que torna a frase
defensável: "Saneamento básico custou 6,9 pontos do índice em junho" é uma
afirmação que alguém pode conferir na mão, e não uma impressão.

DOIS ASSUNTOS, E NÃO UM. O que mais segurou e o que mais puxou, lado a lado:
um mês fechado com o maior negativo em destaque parece um mês perdido, e o
mesmo mês com os dois mostra a disputa que de fato houve. Em junho de 2026, o
que mais pesou foi "Universalização do saneamento", com +7,5 pontos — apontar
só a pressão teria escondido o que estava sustentando o índice.

O sinal vira o mesmo `efeito` que o fato cadastrado carrega — `sustenta` ou
`pressiona` —, e é o que permite os dois aparecerem na mesma coluna sem
explicação extra.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Meia escala: o score vai de 0 a 100 e o NS de −1 a 1.
PONTOS_POR_NS = 50


@dataclass(frozen=True, slots=True)
class MencoesDoAssunto:
    """As menções de um assunto dentro de uma lente, num mês."""

    lente: str
    assunto: str
    positivas: int
    negativas: int
    #: O total da LENTE no mês, e não o do assunto: é o denominador do NS.
    total_da_lente: int


@dataclass(frozen=True, slots=True)
class AssuntoDoMes:
    """O assunto que mais mexeu no índice, e quanto."""

    assunto: str
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


def pontos_no_indice(mencoes: MencoesDoAssunto, peso_efetivo: int) -> float:
    """Quantos pontos do índice este assunto vale, com sinal."""
    if not mencoes.total_da_lente:
        return 0.0
    saldo = (mencoes.positivas - mencoes.negativas) / mencoes.total_da_lente
    return saldo * PONTOS_POR_NS * peso_efetivo / 100


@dataclass(frozen=True, slots=True)
class AssuntosDoMes:
    """Os dois lados da disputa do mês. Qualquer um pode faltar."""

    sustentou: AssuntoDoMes | None = None
    pressionou: AssuntoDoMes | None = None


def _para_assunto(pontos: float, mencoes: MencoesDoAssunto) -> AssuntoDoMes:
    return AssuntoDoMes(
        assunto=mencoes.assunto,
        lente=mencoes.lente,
        pontos=round(pontos, 1),
        positivas=mencoes.positivas,
        negativas=mencoes.negativas,
    )


def assuntos_que_pesaram(
    mencoes: list[MencoesDoAssunto], pesos_efetivos: dict[str, int]
) -> AssuntosDoMes:
    """O assunto que mais segurou o índice, e o que mais puxou.

    OS DOIS, E NÃO O MAIOR EM MÓDULO. Um mês resumido pelo seu pior assunto
    parece um mês perdido; com os dois lados, a mesma coluna mostra a disputa
    que houve — e em junho de 2026 quem mais pesou foi o lado positivo.

    A LENTE FORA DO CÁLCULO NÃO ENTRA: ela tem peso efetivo zero, e um assunto
    que vale zero ponto não pesou — seria só o mais falado de uma lente que o
    índice ignorou.

    O EMPATE FICA COM O NOME, em ordem alfabética. Dois assuntos com o mesmo
    peso precisam devolver sempre a mesma resposta: a coluna do mês não pode
    mudar de texto entre duas leituras sem nada ter mudado.
    """
    pesados = [
        (pontos_no_indice(m, pesos_efetivos.get(m.lente, 0)), m)
        for m in mencoes
        if pesos_efetivos.get(m.lente)
    ]
    positivos = [(p, m) for p, m in pesados if p > 0]
    negativos = [(p, m) for p, m in pesados if p < 0]

    maior = (
        _para_assunto(*min(positivos, key=lambda par: (-par[0], par[1].assunto)))
        if positivos
        else None
    )
    menor = (
        _para_assunto(*min(negativos, key=lambda par: (par[0], par[1].assunto)))
        if negativos
        else None
    )
    return AssuntosDoMes(sustentou=maior, pressionou=menor)
