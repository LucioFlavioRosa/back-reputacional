"""O Índice de Saúde Reputacional — as fórmulas, sem banco e sem HTTP.

Especificação: `docs/handoff/SCORE.md` §1 a §3. A referência executável é a
classe `Component` de `docs/handoff/Score Executivo Aegea.dc.html`; o que está
aqui reproduz as mesmas contas.

O ÍNDICE EM TRÊS LINHAS
-----------------------
    NS    = (positivo − negativo) / (positivo + neutro + negativo)
    score = round((NS + 1) / 2 × 100)
    ISR   = round(Σ score_lente × peso_lente / Σ peso_lente)

O QUE MUDA ENTRE UMA LEITURA E OUTRA É O PESO DE CADA MENÇÃO, e é isso que a
Calibração ajusta: uma matéria em veículo Muito Relevante pode valer 10 ou 1;
um post pode valer 1, o log do seu engajamento, o engajamento cru ou o cargo
de quem o escreveu. Nada disso muda a fórmula — muda o que se soma antes dela.

POR QUE ESTE MÓDULO NÃO TOCA NO BANCO. O índice é a única coisa do produto que
alguém vai querer conferir na mão, número por número, contra uma planilha. Uma
função pura se testa contra o valor esperado sem montar nada — e é assim que o
critério de aceite do §7 ("com os dados de junho, ISR ≈ 58") vira teste.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from app.dominio.erros import RegraViolada


class Sentimento(StrEnum):
    POSITIVO = "pos"
    NEUTRO = "neu"
    NEGATIVO = "neg"


class Tier(StrEnum):
    """A relevância do veículo, na escala da Clipei."""

    MUITO_RELEVANTE = "muito_relevante"
    RELEVANTE = "relevante"
    MENOS_RELEVANTE = "menos_relevante"
    #: A fonte não tem tier — redes sociais, canais próprios, CRM.
    SEM = ""


#: As réguas de tier do §3. A `aegea` é o rascunho de score da companhia: uma
#: negativa no Valor pesa dez vezes uma de blog local.
REGUAS_DE_TIER: dict[str, dict[str, float]] = {
    "aegea": {Tier.MUITO_RELEVANTE: 10, Tier.RELEVANTE: 5, Tier.MENOS_RELEVANTE: 1},
    "suave": {Tier.MUITO_RELEVANTE: 5, Tier.RELEVANTE: 3, Tier.MENOS_RELEVANTE: 1},
    "forte": {Tier.MUITO_RELEVANTE: 20, Tier.RELEVANTE: 5, Tier.MENOS_RELEVANTE: 1},
    "igual": {Tier.MUITO_RELEVANTE: 1, Tier.RELEVANTE: 1, Tier.MENOS_RELEVANTE: 1},
    "so_tier1": {Tier.MUITO_RELEVANTE: 1, Tier.RELEVANTE: 0, Tier.MENOS_RELEVANTE: 0},
}

#: As réguas de engajamento do §3, e qual soma de `score_mes_fonte` cada uma
#: consome. O nome da coluna mora aqui porque é a régua que decide qual somar.
REGUAS_DE_ENGAJAMENTO: dict[str, str] = {
    "n": "mencoes",
    "log": "soma_log",
    "bruto": "soma_engajamento",
    "cargo": "soma_cargo",
}

#: As faixas do §2, da melhor para a pior — `faixa_de` devolve a primeira que
#: o score alcança.
FAIXAS: tuple[tuple[int, str, str], ...] = (
    (85, "Referência", "reputação é ativo de valor"),
    (70, "Sólido", "margem para absorver ruído"),
    (55, "Estável", "equilíbrio frágil entre lentes"),
    (40, "Atenção", "exige plano de recuperação"),
    (0, "Crítico", "risco ao valor da companhia"),
)

#: O peso do cargo de quem postou (§3, régua `cargo`). Aplicado na INGESTÃO,
#: e não aqui: o que chega em `score_mes_fonte` já é a soma.
PESO_DO_CARGO: dict[str, float] = {
    "presidente": 5, "ministro": 5, "governador": 5,
    "senador": 4, "deputado_federal": 4,
    "deputado_estadual": 3, "prefeito": 3,
    "vereador": 2,
}
PESO_DE_CARGO_PADRAO = 1.0


def peso_do_cargo(cargo: str | None) -> float:
    """Quanto vale a voz de quem postou. Sem cargo conhecido, vale 1."""
    if not cargo:
        return PESO_DE_CARGO_PADRAO
    return PESO_DO_CARGO.get(cargo.strip().lower(), PESO_DE_CARGO_PADRAO)


def peso_do_engajamento(engajamento: int | None) -> float:
    """`1 + log10(1 + engajamento)` — a régua recomendada do §3.

    Comprime a cauda: um post com 3.000 interações vale ~4,5, e um com 1
    interação vale ~1,3. Sem a compressão, um viral sozinho decide o mês.
    """
    return 1 + math.log10(1 + max(0, engajamento or 0))


@dataclass(frozen=True, slots=True)
class Contagem:
    """O que se soma de um lado da fórmula, já ponderado."""

    positivo: float = 0
    neutro: float = 0
    negativo: float = 0

    @property
    def total(self) -> float:
        return self.positivo + self.neutro + self.negativo

    def __add__(self, outra: Contagem) -> Contagem:
        return Contagem(
            self.positivo + outra.positivo,
            self.neutro + outra.neutro,
            self.negativo + outra.negativo,
        )


def ns(contagem: Contagem) -> float | None:
    """O saldo de sentimento, de −1 a 1.

    TOTAL ZERO É "SEM DADO", e não zero: uma lente sem menção nenhuma no mês
    não é uma lente neutra — ela não foi medida, e entrar como 50 no índice
    inventaria equilíbrio onde há silêncio. Por isso devolve `None`, e quem
    chama tira a lente do cálculo (§2.2).
    """
    if contagem.total == 0:
        return None
    return (contagem.positivo - contagem.negativo) / contagem.total


def para_score(valor_ns: float) -> int:
    """O NS na escala de 0 a 100 (§2.3)."""
    return round((valor_ns + 1) / 2 * 100)


def faixa_de(score: int) -> tuple[str, str]:
    """O rótulo e a leitura da faixa em que o score caiu."""
    for minimo, rotulo, leitura in FAIXAS:
        if score >= minimo:
            return rotulo, leitura
    return FAIXAS[-1][1], FAIXAS[-1][2]  # pragma: no cover - 0 já cai na última


@dataclass(frozen=True, slots=True)
class Calibracao:
    """A régua em vigor. Espelha uma linha de `score_config`."""

    pesos: dict[str, int] = field(default_factory=dict)
    regua_tier: str = "aegea"
    regua_engajamento: str = "n"
    fontes_desligadas: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.regua_tier not in REGUAS_DE_TIER:
            validas = ", ".join(sorted(REGUAS_DE_TIER))
            raise RegraViolada(
                f"Régua de tier inválida: {self.regua_tier!r}. Use {validas}."
            )
        if self.regua_engajamento not in REGUAS_DE_ENGAJAMENTO:
            validas = ", ".join(sorted(REGUAS_DE_ENGAJAMENTO))
            raise RegraViolada(
                f"Régua de engajamento inválida: {self.regua_engajamento!r}. Use {validas}."
            )
        for lente, peso in self.pesos.items():
            if not 0 <= peso <= 60:
                raise RegraViolada(
                    f"Peso da lente {lente!r} fora da faixa: {peso}. Use de 0 a 60."
                )

    def ligada(self, fonte: str) -> bool:
        return fonte not in self.fontes_desligadas

    def peso(self, lente: str, padrao: int) -> int:
        return self.pesos.get(lente, padrao)


@dataclass(frozen=True, slots=True)
class SomasDaFonte:
    """As somas de uma fonte num mês, no grão em que o banco as guarda.

    Uma instância por (fonte, sentimento, tier) — é a linha de
    `score_mes_fonte`. `ponderar` escolhe qual soma usar e quanto ela vale.
    """

    fonte: str
    sentimento: str
    tier: str
    mencoes: float = 0
    soma_log: float = 0
    soma_engajamento: float = 0
    soma_cargo: float = 0

    def medida(self, regua_engajamento: str) -> float:
        return float(getattr(self, REGUAS_DE_ENGAJAMENTO[regua_engajamento]))


def ponderar(somas: list[SomasDaFonte], calibracao: Calibracao) -> Contagem:
    """As somas de uma fonte viram os três números da fórmula.

    DUAS RÉGUAS, UMA MULTIPLICAÇÃO. O tier diz quanto vale a matéria pelo
    veículo; a régua de engajamento diz o que se soma de cada menção. Onde não
    há tier (redes, canais próprios, CRM), o peso é 1 — a linha entra com a
    sua medida e nada mais.
    """
    pesos_de_tier = REGUAS_DE_TIER[calibracao.regua_tier]
    total = Contagem()
    for linha in somas:
        peso = pesos_de_tier.get(linha.tier, 1.0) if linha.tier else 1.0
        if peso == 0:
            continue
        valor = linha.medida(calibracao.regua_engajamento) * peso
        if linha.sentimento == Sentimento.POSITIVO:
            total = total + Contagem(positivo=valor)
        elif linha.sentimento == Sentimento.NEUTRO:
            total = total + Contagem(neutro=valor)
        else:
            total = total + Contagem(negativo=valor)
    return total


@dataclass(frozen=True, slots=True)
class LenteMedida:
    """Uma lente depois da conta: o score, e de onde ele veio."""

    codigo: str
    nome: str
    peso: int
    ns: float | None
    score: int | None
    #: As fontes ligadas que trouxeram dado neste mês.
    fontes: tuple[str, ...] = ()
    #: Verdadeiro quando o número veio de `score_estimativa`, e não de contagem.
    estimado: bool = False
    #: Por que a lente ficou de fora, quando ficou.
    ausencia: str | None = None


def medir_lente(
    *,
    codigo: str,
    nome: str,
    peso: int,
    somas_por_fonte: dict[str, list[SomasDaFonte]],
    calibracao: Calibracao,
    estimativa: float | None = None,
) -> LenteMedida:
    """O score de uma lente no mês.

    MÉDIA SIMPLES DOS NS DAS FONTES, e não soma das contagens (§2.4). A
    diferença é grande: a Bites classifica 4.973 posts e a Approach 1.959, e
    somar as contagens faria a Bites decidir a lente sozinha. Média de NS dá
    voz igual a cada fornecedor — que é o que se quer de duas leituras da
    mesma realidade.

    A ESTIMATIVA SÓ ENTRA ONDE NÃO HÁ MEDIÇÃO. Havendo contagem, ela é
    ignorada: medido ganha de suposto, sempre.
    """
    ligadas = {
        fonte: somas
        for fonte, somas in somas_por_fonte.items()
        if calibracao.ligada(fonte)
    }
    if not ligadas:
        return LenteMedida(
            codigo=codigo, nome=nome, peso=peso, ns=None, score=None,
            ausencia="todas as fontes desta lente estão desligadas",
        )

    valores: list[float] = []
    com_dado: list[str] = []
    for fonte, somas in sorted(ligadas.items()):
        valor = ns(ponderar(somas, calibracao))
        if valor is not None:
            valores.append(valor)
            com_dado.append(fonte)

    if valores:
        media = sum(valores) / len(valores)
        return LenteMedida(
            codigo=codigo, nome=nome, peso=peso, ns=media,
            score=para_score(media), fontes=tuple(com_dado),
        )

    if estimativa is not None:
        return LenteMedida(
            codigo=codigo, nome=nome, peso=peso, ns=estimativa,
            score=para_score(estimativa), estimado=True,
        )

    return LenteMedida(
        codigo=codigo, nome=nome, peso=peso, ns=None, score=None,
        ausencia="sem menção classificada neste mês",
    )


@dataclass(frozen=True, slots=True)
class Indice:
    """O ISR de um mês, com as lentes que o formaram."""

    mes: str
    isr: int | None
    faixa: str
    leitura_da_faixa: str
    lentes: tuple[LenteMedida, ...]

    @property
    def lentes_no_calculo(self) -> tuple[LenteMedida, ...]:
        return tuple(lente for lente in self.lentes if lente.score is not None)

    @property
    def lentes_de_fora(self) -> tuple[LenteMedida, ...]:
        return tuple(lente for lente in self.lentes if lente.score is None)


def calcular_indice(mes: str, lentes: list[LenteMedida]) -> Indice:
    """A média ponderada das lentes que têm dado (§2.5).

    OS PESOS REDISTRIBUEM SOZINHOS. Uma lente sem dado sai da soma do
    denominador também — se a Sociedade (peso 20) fica de fora, as outras
    quatro passam a dividir 80, e não 100. Sem isso, o índice cairia por
    falta de dado e pareceria queda de reputação.
    """
    com_dado = [lente for lente in lentes if lente.score is not None]
    soma_dos_pesos = sum(lente.peso for lente in com_dado)

    if not com_dado or soma_dos_pesos == 0:
        return Indice(
            mes=mes, isr=None, faixa="Sem dado",
            leitura_da_faixa="nenhuma lente foi medida neste mês",
            lentes=tuple(lentes),
        )

    isr = round(
        sum(lente.score * lente.peso for lente in com_dado) / soma_dos_pesos  # type: ignore[operator]
    )
    rotulo, leitura = faixa_de(isr)
    return Indice(
        mes=mes, isr=isr, faixa=rotulo, leitura_da_faixa=leitura, lentes=tuple(lentes)
    )
