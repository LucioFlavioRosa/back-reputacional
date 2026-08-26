"""O vocabulário das agregações.

Espelha, campo a campo, o que `derivacoes.ts, no repositório do frontend`
calcula hoje no navegador. A duplicação é deliberada e temporária: enquanto as
duas existirem, a de lá é a referência, e há teste garantindo que a de cá dá o
mesmo número.

POR QUE MOVER PARA O BACKEND

O painel baixa até 5.000 registros para derivar tudo no cliente. Funcionava
enquanto todo mundo era da casa. Com acesso externo, entregar o conjunto
completo ao navegador é o argumento mais forte contra a arquitetura atual: o
externo receberia números, não registros — e isso é a única coisa que limita
exfiltração de verdade, porque limite de taxa não limita quem simplesmente usa
o produto.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ImprensaKpi:
    total: int
    atendidas: int
    taxa: float


@dataclass(frozen=True, slots=True)
class InvestidoresKpi:
    total: int
    internacionais: int


@dataclass(frozen=True, slots=True)
class Tier1Kpi:
    total: int
    percentual: float


@dataclass(frozen=True, slots=True)
class Kpis:
    """Os números do cabeçalho do painel."""

    #: Governo e Parceiros somados: as duas compartilham a mesma extensão e o
    #: painel as apresenta como uma linha só.
    institucionais: int
    imprensa: ImprensaKpi
    eventos: int
    investidores: InvestidoresKpi
    legislativo: int
    tier1: Tier1Kpi
    #: O total do recorte. Não está em `derivacoes.ts` — de lá sai do tamanho da
    #: lista. Aqui precisa vir explícito, porque a lista não é baixada.
    total: int


@dataclass(frozen=True, slots=True)
class StatusDoGrupo:
    codigo: str
    nome: str
    total: int


@dataclass(frozen=True, slots=True)
class GrupoDeResolucao:
    grupo: str
    total: int
    percentual: float
    status_que_compoem: list[StatusDoGrupo] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResolutividadeDaFrente:
    frente: str
    total: int
    #: Total da frente MENOS os declinados — o mesmo critério da taxa geral.
    #:
    #: Explícito no payload porque a taxa por frente e a taxa geral aparecem
    #: lado a lado na mesma tela: com o denominador visível, quem lê confere que
    #: as duas usam o mesmo critério em vez de precisar confiar.
    denominador: int
    resolvidos: int
    taxa: float


@dataclass(frozen=True, slots=True)
class Resolutividade:
    taxa: float
    grupos: list[GrupoDeResolucao]
    por_frente: list[ResolutividadeDaFrente]


@dataclass(frozen=True, slots=True)
class ColunaMensal:
    """Um mês, com a contagem de cada segmento."""

    mes: str
    total: int
    segmentos: dict[str, int]


@dataclass(frozen=True, slots=True)
class PontoNoMapa:
    uf: str
    total: int


@dataclass(frozen=True, slots=True)
class ItemContado:
    chave: str
    rotulo: str
    total: int
