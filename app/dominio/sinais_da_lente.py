"""O que está acontecendo numa lente, dito por regra — sem LLM.

A tela do dossiê precisa de frases: a manchete, o título de cada gráfico, a
lista do que mudou no período. A primeira versão pedia que alguém as
escrevesse todo mês. Este módulo as CALCULA dos próprios dados, com detectores
determinísticos — e é por isso que a frase nunca desencontra do número que está
ao lado dela.

POR QUE NÃO SE GUARDA NADA. Texto salvo envelhece em silêncio: a tela que a
diretoria abre em setembro mostraria a leitura de junho com a mesma cara de
atual, e ninguém perceberia. Recalcular a cada leitura custa microssegundos e
elimina a classe inteira desse erro.

POR QUE NÃO É LLM. Um detector com limite configurável é auditável: dá para
perguntar "por que esta frase apareceu" e receber "porque o negativo subiu 13
pontos percentuais, e o limite é 10". A mesma pergunta a um modelo devolve uma
explicação plausível, que não é a mesma coisa.

O QUE ENTRA AQUI SÃO AS SÉRIES JÁ CALCULADAS pelo endpoint — este módulo não
conhece banco, não faz consulta e não sabe o que é uma lente. Ele recebe
números e devolve frases, e é essa fronteira que o torna testável linha a linha.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

from app.dominio import frases_de_sinais as frases
from app.dominio.lentes import prioridade_do_jornalista


class Secao(StrEnum):
    """Onde o sinal aparece. É o que liga a frase ao gráfico que a prova."""

    EVOLUCAO = "evo"
    PAINEL_A = "pA"
    PAINEL_B = "pB"
    #: Vale para a lente inteira — não tem gráfico próprio.
    GERAL = "geral"


class Tom(StrEnum):
    POSITIVO = "pos"
    NEGATIVO = "neg"
    NEUTRO = "neu"


#: Os tipos que descrevem MOVIMENTO RECENTE, na ordem de precedência da §3.
#:
#: A manchete tem de respeitar esta ordem antes da intensidade, e o motivo é a
#: regra de coerência: ao lado da manchete há um chip dizendo "+11" ou "−10". Um
#: sinal antigo e intenso na manchete, com o chip mostrando o mês, faz a tela
#: se contradizer na mesma linha.
TIPOS_DE_MOVIMENTO_RECENTE: tuple[str, ...] = ("Virada", "Alta do negativo", "Recuperação")

TIPO_DE_LACUNA = "Lacuna de dado"


@dataclass(frozen=True, slots=True)
class Limites:
    """Os cortes de cada detector. Configuráveis pela Calibração (§5).

    SÃO DECISÃO DE LEITURA, e não constante técnica: "o que conta como pico"
    muda com o volume que cada fonte costuma trazer, e quem sabe isso é quem lê
    o painel toda semana — não quem escreveu o detector.
    """

    pico_desvios: float = 1.5
    pico_razao_minima: float = 1.3
    virada_pontos: int = 10
    deslocamento_pp: float = 10
    tendencia_meses: int = 3
    concentracao_razao: float = 3
    concentracao_top3: float = 50
    max_sinais: int = 5


@dataclass(frozen=True, slots=True)
class Sinal:
    tipo: str
    frase: str
    #: O número que a frase prova, em destaque ao lado dela.
    evidencia: str
    secao: Secao
    intensidade: float
    tom: Tom
    #: A ordem em que o detector o produziu — desempata intensidade igual, e é
    #: o que faz duas leituras seguidas darem a mesma lista.
    ordem: int = 0


@dataclass(frozen=True, slots=True)
class Ponto:
    """Um mês da série de sentimento.

    TRÊS ESTADOS, e os detectores tratam cada um do seu jeito (§2):

        com leitura         `pos`, `neu` e `neg` somam mais que zero
        sem classificação   só `sem_classificacao` — houve volume, ninguém leu
        sem base            nada passou por ali
    """

    mes: date
    pos: int = 0
    neu: int = 0
    neg: int = 0
    sem_classificacao: int = 0
    sem_base: bool = False

    @property
    def classificadas(self) -> int:
        return self.pos + self.neu + self.neg

    @property
    def volume(self) -> int:
        return self.classificadas + self.sem_classificacao

    @property
    def tem_leitura(self) -> bool:
        return not self.sem_base and self.classificadas > 0

    @property
    def fatia_negativa(self) -> float:
        return self.neg / self.classificadas if self.classificadas else 0.0

    @property
    def ns(self) -> float:
        return (self.pos - self.neg) / self.classificadas if self.classificadas else 0.0

    @property
    def nota(self) -> int:
        return round((self.ns + 1) / 2 * 100)


@dataclass(frozen=True, slots=True)
class Item:
    """Uma linha de composição: tier, tema, clima."""

    rotulo: str
    pos: float
    neu: float
    neg: float

    @property
    def total(self) -> float:
        return self.pos + self.neu + self.neg

    @property
    def fatia_negativa(self) -> float:
        return self.neg / self.total if self.total else 0.0

    @property
    def fatia_positiva(self) -> float:
        return self.pos / self.total if self.total else 0.0


def primeiro_do_mes(quando: date) -> date:
    return quando.replace(day=1)


def _media(valores: Sequence[float]) -> float:
    return sum(valores) / len(valores) if valores else 0.0


def _desvio(valores: Sequence[float]) -> float:
    if not valores:
        return 0.0
    media = _media(valores)
    return math.sqrt(_media([(valor - media) ** 2 for valor in valores]))


# -- 5.1 · a série mensal de sentimento -----------------------------------------


def detectar_na_serie(
    serie: Sequence[Ponto],
    *,
    unidade: str,
    secao: Secao,
    limites: Limites,
    com_pico: bool = True,
) -> list[Sinal]:
    """Pico, virada, alta do negativo, tendência, deslocamento e lacuna."""
    achados: list[Sinal] = []
    # ORDENAR AQUI, E NÃO CONFIAR NO CHAMADOR: "último vs. penúltimo" é uma
    # afirmação sobre o calendário, e lê-la da ordem do argumento faria a mesma
    # série devolver leituras diferentes conforme quem a montou.
    serie = sorted(serie, key=lambda ponto: ponto.mes)
    com_base = [ponto for ponto in serie if not ponto.sem_base]
    com_leitura = [ponto for ponto in serie if ponto.tem_leitura]

    if com_pico and len(com_base) >= 3:
        achados += _pico(com_base, unidade=unidade, secao=secao, limites=limites)

    if len(com_leitura) >= 2:
        antes, depois = com_leitura[-2], com_leitura[-1]
        virada = _virada(antes, depois, secao=secao, limites=limites)
        if virada:
            achados.append(virada)
        else:
            alta = _alta_do_negativo(antes, depois, secao=secao, limites=limites)
            if alta:
                achados.append(alta)

    if len(com_leitura) >= limites.tendencia_meses:
        tendencia = _tendencia(com_leitura, secao=secao, limites=limites)
        if tendencia:
            achados.append(tendencia)

    if len(com_leitura) >= 3:
        deslocamento = _deslocamento(com_leitura, secao=secao, limites=limites)
        if deslocamento:
            achados.append(deslocamento)

    lacuna = _lacuna(serie, secao=secao)
    if lacuna:
        achados.append(lacuna)
    return achados


def _pico(
    com_base: Sequence[Ponto], *, unidade: str, secao: Secao, limites: Limites
) -> list[Sinal]:
    volumes = [ponto.volume for ponto in com_base]
    media, desvio = _media(volumes), _desvio(volumes)
    maior = max(volumes)
    if not media or not desvio:
        return []
    z = (maior - media) / desvio
    if z < limites.pico_desvios or maior / media < limites.pico_razao_minima:
        return []
    ponto = com_base[volumes.index(maior)]
    return [
        Sinal(
            tipo="Pico",
            frase=frases.pico(ponto.mes, maior, unidade, maior / media),
            evidencia=frases.inteiro(maior),
            secao=secao,
            intensidade=z,
            tom=Tom.NEUTRO,
        )
    ]


def _virada(antes: Ponto, depois: Ponto, *, secao: Secao, limites: Limites) -> Sinal | None:
    delta = depois.nota - antes.nota
    # A TROCA DE SINAL CONTA MESMO PEQUENA: sair de saldo positivo para negativo
    # é uma mudança de natureza, não de grau — e um mês que cruza o zero por
    # dois pontos diz mais que um que melhora dez sem mudar de lado.
    trocou_de_lado = antes.ns != 0 and (antes.ns > 0) != (depois.ns > 0)
    if abs(delta) < limites.virada_pontos and not trocou_de_lado:
        return None
    return Sinal(
        tipo="Virada",
        frase=frases.virada(delta, depois.mes, antes.fatia_negativa, depois.fatia_negativa),
        evidencia=f"{'+' if delta > 0 else ''}{delta} pts",
        secao=secao,
        intensidade=abs(delta) / limites.virada_pontos,
        tom=Tom.POSITIVO if delta > 0 else Tom.NEGATIVO,
    )


def _alta_do_negativo(
    antes: Ponto, depois: Ponto, *, secao: Secao, limites: Limites
) -> Sinal | None:
    """SÓ QUANDO NÃO HOUVE VIRADA. Os dois descrevem o mesmo movimento com
    palavras diferentes, e mostrar os dois juntos faz a lista repetir a notícia
    — gastando uma das cinco vagas com o que já foi dito."""
    delta_pp = (depois.fatia_negativa - antes.fatia_negativa) * 100
    if delta_pp < limites.deslocamento_pp:
        return None
    return Sinal(
        tipo="Alta do negativo",
        frase=frases.alta_do_negativo(
            antes.fatia_negativa, antes.mes, depois.fatia_negativa, depois.mes
        ),
        evidencia=f"+{round(delta_pp)} p.p.",
        secao=secao,
        intensidade=delta_pp / limites.deslocamento_pp,
        tom=Tom.NEGATIVO,
    )


def _tendencia(com_leitura: Sequence[Ponto], *, secao: Secao, limites: Limites) -> Sinal | None:
    ultimos = com_leitura[-limites.tendencia_meses :]
    fatias = [ponto.fatia_negativa for ponto in ultimos]
    cai = all(b < a for a, b in zip(fatias, fatias[1:], strict=False))
    sobe = all(b > a for a, b in zip(fatias, fatias[1:], strict=False))
    if not cai and not sobe:
        return None
    return Sinal(
        tipo="Tendência",
        frase=frases.tendencia(cai, fatias),
        evidencia=f"{len(fatias)} meses",
        secao=secao,
        # Fixa, e não proporcional: três meses seguidos na mesma direção valem
        # pelo padrão, não pelo tamanho do passo.
        intensidade=1.2,
        tom=Tom.POSITIVO if cai else Tom.NEGATIVO,
    )


def _deslocamento(com_leitura: Sequence[Ponto], *, secao: Secao, limites: Limites) -> Sinal | None:
    """O negativo recuou do pico — mas só se o último mês não piorou.

    A CONDIÇÃO DO FINAL É O QUE IMPEDE A CONTRADIÇÃO. Sem ela, um mês que
    piorou em relação ao anterior ainda geraria "o negativo recuou", porque o
    pico foi há quatro meses — e a frase apareceria ao lado de um chip dizendo
    que a nota caiu.
    """
    pico = max(com_leitura, key=lambda ponto: ponto.fatia_negativa)
    ultimo = com_leitura[-1]
    anterior = com_leitura[-2] if len(com_leitura) >= 2 else ultimo
    queda_pp = (pico.fatia_negativa - ultimo.fatia_negativa) * 100
    if pico.mes == ultimo.mes:
        return None
    if queda_pp < limites.deslocamento_pp:
        return None
    if ultimo.fatia_negativa > anterior.fatia_negativa:
        return None
    return Sinal(
        tipo="Deslocamento",
        frase=frases.deslocamento(pico.fatia_negativa, pico.mes, ultimo.fatia_negativa, ultimo.mes),
        evidencia=f"−{round(queda_pp)} p.p.",
        secao=secao,
        intensidade=queda_pp / limites.deslocamento_pp,
        tom=Tom.POSITIVO,
    )


def _lacuna(serie: Sequence[Ponto], *, secao: Secao) -> Sinal | None:
    sem_sentimento = [
        ponto.mes for ponto in serie if not ponto.sem_base and not ponto.classificadas
    ]
    sem_base = [ponto.mes for ponto in serie if ponto.sem_base]
    if not sem_sentimento and not sem_base:
        return None
    quantos = len(sem_sentimento) + len(sem_base)
    return Sinal(
        tipo=TIPO_DE_LACUNA,
        frase=frases.lacuna_de_dado(sem_sentimento, sem_base),
        evidencia=f"{quantos} {frases.plural(quantos, 'mês', 'meses')}",
        secao=secao,
        # Zero de propósito: lacuna não compete por vaga, vai para o fim.
        intensidade=0,
        tom=Tom.NEUTRO,
    )


# -- 5.2 · composição por item ---------------------------------------------------


def detectar_nos_itens(
    itens: Sequence[Item],
    *,
    secao: Secao,
    rotulo_do_negativo: str = "Tema dominante",
    percentual: bool = False,
) -> list[Sinal]:
    """Quem concentra o negativo, e quem sustenta.

    `percentual` diz que cada item já vem normalizado (as fatias somam 100 por
    linha) — aí não existe "geral" com que comparar, porque somar percentuais de
    linhas diferentes não produz número nenhum.
    """
    # ITEM SEM VOLUME NÃO TEM FATIA. `fatia_negativa` devolve 0 para não
    # estourar, e esse 0 viraria "concentra o maior negativo: 0%" — uma leitura
    # analítica sobre um item por onde não passou nada.
    itens = [item for item in itens if item.total]
    if not itens:
        return []

    pior = max(itens, key=lambda item: item.fatia_negativa)
    melhor = max(itens, key=lambda item: item.fatia_positiva)
    total = sum(item.total for item in itens)
    geral = None if percentual or not total else sum(item.neg for item in itens) / total

    achados = [
        Sinal(
            tipo=rotulo_do_negativo,
            frase=frases.tema_dominante(pior.rotulo, pior.fatia_negativa, geral),
            evidencia=frases.porcento(pior.fatia_negativa),
            secao=secao,
            intensidade=pior.fatia_negativa / geral if geral else pior.fatia_negativa * 2,
            tom=Tom.NEGATIVO,
        )
    ]
    if melhor.rotulo != pior.rotulo:
        achados.append(
            Sinal(
                tipo="Sustenta",
                frase=frases.sustenta(melhor.rotulo, melhor.fatia_positiva),
                evidencia=frases.porcento(melhor.fatia_positiva),
                secao=secao,
                intensidade=melhor.fatia_positiva,
                tom=Tom.POSITIVO,
            )
        )
    return achados


# -- 5.3 · ranking ---------------------------------------------------------------


def detectar_no_ranking(
    itens: Sequence[tuple[str, float]],
    *,
    secao: Secao,
    ordinal_do_segundo: str,
    unidade: str,
    limites: Limites,
) -> list[Sinal]:
    """Concentração: pela razão entre o primeiro e o segundo, ou pelo topo.

    DUAS FORMAS PORQUE SÃO DOIS FORMATOS DE PROBLEMA. Uma unidade que sozinha
    vale três vezes a segunda é um caso; três unidades que somam metade do
    volume é outro. Mostrar as duas ao mesmo tempo diria a mesma coisa duas
    vezes, e por isso a segunda só vale quando a primeira não dispara.
    """
    ordenados = sorted(itens, key=lambda item: (-item[1], item[0]))
    if len(ordenados) >= 2 and ordenados[1][1]:
        razao = ordenados[0][1] / ordenados[1][1]
        if razao >= limites.concentracao_razao:
            return [
                Sinal(
                    tipo="Concentração",
                    frase=frases.concentracao_por_razao(
                        ordenados[0][0], razao, ordenados[1][0], ordinal_do_segundo
                    ),
                    evidencia=f"{frases.decimal(razao)}×",
                    secao=secao,
                    intensidade=razao / limites.concentracao_razao,
                    tom=Tom.NEGATIVO,
                )
            ]

    total = sum(valor for _, valor in ordenados)
    if not total:
        return []
    topo = ordenados[:3]
    fatia = sum(valor for _, valor in topo) / total
    if fatia * 100 < limites.concentracao_top3:
        return []
    return [
        Sinal(
            tipo="Concentração",
            frase=frases.concentracao_do_topo([rotulo for rotulo, _ in topo], fatia, unidade),
            evidencia=frases.porcento(fatia),
            secao=secao,
            intensidade=fatia * 100 / limites.concentracao_top3,
            tom=Tom.NEUTRO,
        )
    ]


# -- 5.4 · série de percentual ---------------------------------------------------


def detectar_no_percentual(
    serie: Sequence[tuple[date, float | None]],
    *,
    nome: str,
    secao: Secao,
    limites: Limites,
) -> list[Sinal]:
    """O recuo de uma fatia — o teor de reclamação, por exemplo."""
    com_valor = [(quando, valor) for quando, valor in serie if valor is not None]
    if len(com_valor) < 2:
        return []
    maior = max(com_valor, key=lambda par: par[1])
    ultimo = com_valor[-1]
    queda = maior[1] - ultimo[1]
    if maior[0] == ultimo[0] or queda < limites.deslocamento_pp:
        return []
    minimo = min(valor for _, valor in com_valor)
    return [
        Sinal(
            tipo="Deslocamento",
            frase=frases.deslocamento_percentual(
                nome,
                maior[1] / 100,
                maior[0],
                ultimo[1] / 100,
                ultimo[0],
                e_minimo=ultimo[1] == minimo,
            ),
            evidencia=f"−{round(queda)} p.p.",
            secao=secao,
            intensidade=queda / limites.deslocamento_pp,
            tom=Tom.POSITIVO,
        )
    ]


# -- 5.5 · o que só existe em uma lente ------------------------------------------
#
# Os detectores acima leem FORMATOS: uma série mensal, uma composição, um
# ranking. Os de baixo leem ASSUNTOS: a matriz de jornalistas, o eventograma, o
# estudo de percepção, a trajetória de rating. Não dá para generalizá-los sem
# inventar um formato que teria um usuário só cada — e a regra de cada um é
# específica o bastante para que o nome do detector seja a própria regra.


@dataclass(frozen=True, slots=True)
class Jornalista:
    """Uma linha da matriz — as três notas de 1 a 5."""

    nome: str
    veiculo: str | None
    relevancia: int
    exposicao: int
    proximidade: int


def detectar_na_matriz(jornalistas: Sequence[Jornalista], *, secao: Secao) -> list[Sinal]:
    """Quem está longe demais, e quantos exigem cadência contínua.

    A DISTÂNCIA É `média(relevância, exposição) − proximidade`, e é o que a
    matriz existe para mostrar: um jornalista que pauta muito e de quem estamos
    longe é um problema de relacionamento; um de quem estamos longe e que não
    pauta, não é. Olhar só a proximidade confundiria os dois.
    """
    if not jornalistas:
        return []

    def distancia(pessoa: Jornalista) -> float:
        return (pessoa.relevancia + pessoa.exposicao) / 2 - pessoa.proximidade

    achados: list[Sinal] = []
    mais_longe = max(jornalistas, key=lambda pessoa: (distancia(pessoa), pessoa.nome))
    if distancia(mais_longe) > 0:
        achados.append(
            Sinal(
                tipo="Lacuna de relacionamento",
                frase=frases.lacuna_de_relacionamento(
                    mais_longe.nome,
                    mais_longe.veiculo,
                    mais_longe.relevancia,
                    mais_longe.exposicao,
                    mais_longe.proximidade,
                ),
                evidencia=f"proximidade {mais_longe.proximidade}",
                secao=secao,
                # Dois pontos de distância numa escala de 1 a 5 é o bastante
                # para competir de igual com um sinal no limite — daí o divisor.
                intensidade=distancia(mais_longe) / 2,
                tom=Tom.NEGATIVO,
            )
        )

    p1 = [
        pessoa
        for pessoa in jornalistas
        if prioridade_do_jornalista(pessoa.relevancia, pessoa.exposicao, pessoa.proximidade).nivel
        == 1
    ]
    if p1:
        achados.append(
            Sinal(
                tipo="Prioridade",
                frase=frases.prioridade_um(len(p1)),
                evidencia=f"P1 · {len(p1)}",
                secao=secao,
                # FIXA, E ABAIXO DE 1: quantos exigem cadência contínua é pano
                # de fundo, não notícia do mês — e uma contagem crua no lugar
                # faria uma matriz grande empurrar todo o resto da lista para
                # fora só por ser grande.
                intensidade=0.8,
                tom=Tom.NEUTRO,
            )
        )
    return achados


@dataclass(frozen=True, slots=True)
class Evento:
    """Um fato do eventograma. `efeito` é `pressiona`, `sustenta` ou `misto`."""

    quando: date
    texto: str
    efeito: str


PRESSIONA = "pressiona"
SUSTENTA = "sustenta"


def detectar_nos_eventos(eventos: Sequence[Evento], *, secao: Secao) -> list[Sinal]:
    """Em quantos meses a pressão predominou, e onde ela se acumulou.

    O DENOMINADOR SÃO OS MESES COM EVENTO, e não os meses do período: um mês
    sem nenhum fato cadastrado não é um mês calmo, é um mês sem cadastro — e
    contá-lo como calmo diluiria a pressão com ausência de informação.
    """
    if not eventos:
        return []

    por_mes: dict[date, list[Evento]] = {}
    for evento in eventos:
        por_mes.setdefault(evento.quando.replace(day=1), []).append(evento)

    sob_pressao = sorted(
        mes
        for mes, doacoes in por_mes.items()
        if sum(1 for evento in doacoes if evento.efeito == PRESSIONA)
        > sum(1 for evento in doacoes if evento.efeito == SUSTENTA)
    )
    achados: list[Sinal] = []
    # SÓ QUANDO HOUVE ALGUM MÊS ASSIM. "A pressão predominou em 0 de 7 meses"
    # é uma frase sobre o que não aconteceu, e ocuparia uma das cinco vagas da
    # lista para dizer que não há notícia.
    if sob_pressao:
        achados.append(
            Sinal(
                tipo="Pressão",
                frase=frases.pressao(sob_pressao, len(por_mes)),
                evidencia=f"{len(sob_pressao)}/{len(por_mes)}",
                secao=secao,
                # VEZES DOIS: sem isso uma fração nunca passa de 1, e a pressão
                # — que é o sinal central da lente de mercado — jamais chegaria
                # ao título do eventograma.
                intensidade=len(sob_pressao) / len(por_mes) * 2,
                tom=Tom.NEGATIVO,
            )
        )

    # EMPATE FICA COM O MAIS RECENTE (§5.5): dois meses com o mesmo acúmulo, o
    # que importa é o de agora — o outro já foi lido no mês em que aconteceu.
    acumulos = [
        (mes, [evento.texto for evento in doacoes if evento.efeito == PRESSIONA])
        for mes, doacoes in sorted(por_mes.items())
    ]
    acumulos = [(mes, textos) for mes, textos in acumulos if len(textos) >= 2]
    if acumulos:
        mes, textos = max(acumulos, key=lambda par: (len(par[1]), par[0]))
        achados.append(
            Sinal(
                # O PROTÓTIPO CHAMA DE "Concentração", como o de ranking. São
                # dois detectores diferentes, e o chip é o que a pessoa lê para
                # saber qual regra produziu a frase — a §5.5 os separa, e o
                # nome aqui segue a §5.5.
                tipo="Concentração de eventos",
                frase=frases.concentracao_de_eventos(mes, textos),
                evidencia=f"{len(textos)} eventos",
                secao=secao,
                # Divisor 1,5 e não 2: dois eventos de pressão no mesmo mês já
                # são o caso que o detector existe para mostrar, e dividir pelo
                # próprio limite os deixaria empatados com qualquer sinal no
                # corte.
                intensidade=len(textos) / 1.5,
                tom=Tom.NEGATIVO,
            )
        )
    return achados


def detectar_no_estudo(atributos: Sequence[tuple[str, float]], *, secao: Secao) -> list[Sinal]:
    """A maior distância entre dois atributos do estudo de percepção.

    UM ESTUDO COM UM ATRIBUTO SÓ NÃO TEM CONTRASTE — e é por isso que o
    detector se cala em vez de comparar o atributo consigo mesmo, o que daria
    "0,0 pontos abaixo" e passaria por leitura.
    """
    if len(atributos) < 2:
        return []
    pior = min(atributos, key=lambda par: (par[1], par[0]))
    melhor = max(atributos, key=lambda par: (par[1], par[0]))
    diferenca = melhor[1] - pior[1]
    if not diferenca:
        return []
    return [
        Sinal(
            tipo="Contraste",
            frase=frases.contraste(pior[0], pior[1], melhor[0], melhor[1]),
            evidencia=f"−{frases.decimal(diferenca)}",
            secao=secao,
            # A PRÓPRIA DIFERENÇA, em pontos da escala de 1 a 5: dois pontos
            # separam "bem avaliado" de "mal avaliado", e é essa distância que
            # mede o tamanho do problema.
            intensidade=diferenca,
            tom=Tom.NEGATIVO,
        )
    ]


@dataclass(frozen=True, slots=True)
class AcaoDeRating:
    """Uma linha da trajetória. `efeito` `pressiona` é rebaixamento."""

    agencia: str
    quando: date
    efeito: str
    perspectiva: str | None = None


def detectar_no_rating(acoes: Sequence[AcaoDeRating], *, secao: Secao) -> list[Sinal]:
    """Quem voltou a rebaixar depois do primeiro rebaixamento.

    A CONTA É "DEPOIS DO PRIMEIRO", e não "quantos rebaixamentos houve": um
    rebaixamento isolado é um evento; outro rebaixamento depois dele é um
    movimento de mercado, e é o movimento que a lente precisa mostrar.
    """
    rebaixamentos = sorted(
        (acao for acao in acoes if acao.efeito == PRESSIONA),
        key=lambda acao: (acao.quando, acao.agencia),
    )
    if not rebaixamentos:
        return []
    # DEPOIS DO MÊS DO PRIMEIRO, e não depois da primeira linha: as três
    # agências que rebaixaram na mesma semana de maio são UM movimento. Contar
    # as duas seguintes como "voltaram a rebaixar" diria que cinco agências se
    # mexeram depois de maio, quando foram duas.
    desde = primeiro_do_mes(rebaixamentos[0].quando)
    depois = {acao.agencia for acao in rebaixamentos if primeiro_do_mes(acao.quando) > desde}
    if not depois:
        return []
    negativas = sorted(
        {
            acao.agencia
            for acao in acoes
            if acao.perspectiva and acao.perspectiva.lower().startswith("negativ")
        }
    )
    return [
        Sinal(
            tipo="Rating",
            frase=frases.rating(len(depois), desde, negativas),
            evidencia=f"{len(depois)} rebaixamentos",
            secao=secao,
            # Fixa e alta: uma segunda rodada de rebaixamento é notícia de
            # mercado independentemente de quantas agências a fizeram — o
            # número está na frase, e não precisa reger a ordem da lista.
            intensidade=1.6,
            tom=Tom.NEGATIVO,
        )
    ]


def sinal_de_proxy() -> Sinal:
    """A lente de mercado não tem série de sentimento — e precisa dizer isso.

    É UMA LACUNA, e por isso vai para o fim da lista com intensidade zero: a
    nota existe e é defensável, mas quem a lê tem de saber que ela mede os
    veículos econômicos de Tier 1, e não o que o mercado disse.
    """
    return Sinal(
        tipo=TIPO_DE_LACUNA,
        frase=frases.proxy_sem_serie(),
        evidencia="proxy",
        secao=Secao.GERAL,
        intensidade=0,
        tom=Tom.NEUTRO,
    )


def detectar_no_volume(
    serie: Sequence[tuple[date, int | None]],
    *,
    unidade: str,
    secao: Secao,
    limites: Limites,
) -> list[Sinal]:
    """Só o pico, sobre uma contagem que não tem sentimento.

    A LENTE DE CLIENTES PRECISA DISSO porque o que chega ao atendimento se conta
    em mensagens recebidas, e mensagem recebida não é positiva nem negativa — é
    demanda. Passar essa série pelos detectores de sentimento produziria
    "a nota caiu" a partir de números que não medem nota nenhuma.
    """
    pontos = [
        Ponto(mes=quando, sem_classificacao=valor) for quando, valor in serie if valor is not None
    ]
    if len(pontos) < 3:
        return []
    return _pico(pontos, unidade=unidade, secao=secao, limites=limites)


def detectar_na_recuperacao(
    serie: Sequence[tuple[date, float | None]], *, secao: Secao, limites: Limites
) -> list[Sinal]:
    """A taxa de resposta voltou a subir depois de um fundo.

    A MÍNIMA É PROCURADA ANTES DO ÚLTIMO MÊS, e não na série inteira: se o
    último mês for o pior de todos, ele não se recuperou de nada — e comparar o
    mês consigo mesmo devolveria zero, que não dispara, mas por acidente.
    """
    com_valor = [(quando, valor) for quando, valor in serie if valor is not None]
    if len(com_valor) < 2:
        return []
    quando, taxa = com_valor[-1]
    quando_minima, minima = min(com_valor[:-1], key=lambda par: (par[1], par[0]))
    ganho_pp = (taxa - minima) * 100
    if ganho_pp < limites.deslocamento_pp:
        return []
    return [
        Sinal(
            tipo="Recuperação",
            frase=frases.recuperacao(taxa, quando, minima, quando_minima),
            evidencia=f"+{round(ganho_pp)} p.p.",
            secao=secao,
            intensidade=ganho_pp / limites.deslocamento_pp,
            tom=Tom.POSITIVO,
        )
    ]


# -- a escolha: manchete, títulos e lista ----------------------------------------


@dataclass(frozen=True, slots=True)
class Leitura:
    """O que a tela mostra, já escolhido."""

    manchete: str
    titulo_da_evolucao: str
    sinais_da_evolucao: list[str] = field(default_factory=list)
    titulo_do_painel_a: str | None = None
    titulo_do_painel_b: str | None = None
    lista: list[Sinal] = field(default_factory=list)


def escolher(
    sinais: Sequence[Sinal],
    *,
    limites: Limites,
    nome_do_painel_a: str,
    nome_do_painel_b: str,
) -> Leitura:
    """Qual sinal vai para cada lugar da tela (§3).

    A MANCHETE OBEDECE À ORDEM DE MOVIMENTO ANTES DA INTENSIDADE, e essa é a
    regra que impede a tela de se contradizer: ao lado da manchete há um chip
    com a variação do último mês. Um sinal antigo e intenso ali — "a Corsan
    concentra o negativo" — ao lado de "+11" faz o leitor procurar a relação
    entre os dois e não achar.
    """
    numerados = [replace(sinal, ordem=i) for i, sinal in enumerate(sinais)]
    reais = sorted(
        (sinal for sinal in numerados if sinal.tipo != TIPO_DE_LACUNA),
        key=lambda sinal: (-sinal.intensidade, sinal.ordem),
    )
    lacunas = [sinal for sinal in numerados if sinal.tipo == TIPO_DE_LACUNA]

    def do_topo(secao: Secao) -> Sinal | None:
        """A MESMA REGRA DA MANCHETE, por seção (§3) — inclusive a ORDEM.

        Procurar "qualquer movimento recente" sobre a lista já ordenada por
        intensidade deixaria uma Recuperação forte passar na frente de uma
        Virada: o título diria que a taxa se recuperou enquanto o gráfico
        embaixo mostra a nota virando.
        """
        recente = next(
            (
                sinal
                for tipo in TIPOS_DE_MOVIMENTO_RECENTE
                for sinal in reais
                if sinal.secao == secao and sinal.tipo == tipo
            ),
            None,
        )
        return recente or next((sinal for sinal in reais if sinal.secao == secao), None)

    de_frente = {Secao.EVOLUCAO, Secao.PAINEL_A}
    manchete = (
        next(
            (
                sinal
                for tipo in TIPOS_DE_MOVIMENTO_RECENTE
                for sinal in reais
                if sinal.secao in de_frente and sinal.tipo == tipo
            ),
            None,
        )
        or next(
            (sinal for sinal in reais if sinal.secao in de_frente and sinal.tom != Tom.NEUTRO),
            None,
        )
        or (reais[0] if reais else None)
    )

    da_evolucao = [sinal.frase for sinal in reais if sinal.secao == Secao.EVOLUCAO][:3]
    da_evolucao += [sinal.frase for sinal in lacunas if sinal.secao == Secao.EVOLUCAO]

    topo_evo = do_topo(Secao.EVOLUCAO)
    topo_a, topo_b = do_topo(Secao.PAINEL_A), do_topo(Secao.PAINEL_B)
    return Leitura(
        manchete=manchete.frase if manchete else frases.SEM_SINAL,
        titulo_da_evolucao=topo_evo.frase if topo_evo else frases.SEM_SINAL_NA_SERIE,
        sinais_da_evolucao=da_evolucao or [frases.SEM_SINAL_NA_LISTA],
        titulo_do_painel_a=topo_a.frase if topo_a else nome_do_painel_a,
        titulo_do_painel_b=topo_b.frase if topo_b else nome_do_painel_b,
        # As lacunas VÃO PARA O FIM, sempre, e não disputam as vagas: elas
        # dizem o que falta, e o que falta não compete com o que aconteceu.
        lista=reais[: limites.max_sinais] + lacunas,
    )
