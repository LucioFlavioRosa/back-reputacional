"""Períodos e janelas de comparação.

O painel oferece atalhos de período ("últimos 90 dias") e janelas de comparação
entre recortes de tempo (semestre, trimestre, 90 dias). Ambos resolvem para um
par de datas — quem consulta o banco nunca vê o atalho, só o intervalo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from app.dominio.erros import RegraViolada


class AtalhoDePeriodo(StrEnum):
    """Atalhos que a barra de filtros oferece.

    PASSADO E FUTURO NA MESMA ESCALA, de propósito: 30/60/90/180/360 dias dos
    dois lados do calendário. "Ano corrente" saiu daqui — não tinha um espelho
    para a frente, e a barra de filtros passou a tratar as duas direções de
    forma simétrica.
    """

    ULTIMOS_30 = "ultimos-30"
    ULTIMOS_60 = "ultimos-60"
    ULTIMOS_90 = "ultimos-90"
    ULTIMOS_180 = "ultimos-180"
    ULTIMOS_360 = "ultimos-360"
    #: PARA A FRENTE: agendas ainda por vir, não as que já aconteceram — a
    #: mesma janela dos "últimos", olhando para o outro lado do calendário.
    PROXIMOS_30 = "proximos-30"
    PROXIMOS_60 = "proximos-60"
    PROXIMOS_90 = "proximos-90"
    PROXIMOS_180 = "proximos-180"
    PROXIMOS_360 = "proximos-360"


@dataclass(frozen=True, slots=True)
class Periodo:
    """Intervalo fechado de datas. Ambos os extremos são opcionais."""

    de: date | None = None
    ate: date | None = None

    def __post_init__(self) -> None:
        if self.de and self.ate and self.de > self.ate:
            raise RegraViolada("O início do período é posterior ao fim.")

    @property
    def aberto(self) -> bool:
        return self.de is None and self.ate is None

    @classmethod
    def do_atalho(cls, atalho: AtalhoDePeriodo, hoje: date | None = None) -> Periodo:
        referencia = hoje or date.today()
        match atalho:
            case AtalhoDePeriodo.ULTIMOS_30:
                return cls(de=referencia - timedelta(days=30), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_60:
                return cls(de=referencia - timedelta(days=60), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_90:
                return cls(de=referencia - timedelta(days=90), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_180:
                return cls(de=referencia - timedelta(days=180), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_360:
                return cls(de=referencia - timedelta(days=360), ate=referencia)
            case AtalhoDePeriodo.PROXIMOS_30:
                return cls(de=referencia, ate=referencia + timedelta(days=30))
            case AtalhoDePeriodo.PROXIMOS_60:
                return cls(de=referencia, ate=referencia + timedelta(days=60))
            case AtalhoDePeriodo.PROXIMOS_90:
                return cls(de=referencia, ate=referencia + timedelta(days=90))
            case AtalhoDePeriodo.PROXIMOS_180:
                return cls(de=referencia, ate=referencia + timedelta(days=180))
            case AtalhoDePeriodo.PROXIMOS_360:
                return cls(de=referencia, ate=referencia + timedelta(days=360))
        raise RegraViolada(f"Atalho de período desconhecido: {atalho}")


class Janela(StrEnum):
    """Janelas de comparação das telas de porta-vozes e interlocutores."""

    SEMESTRE = "semestre"
    TRIMESTRE = "trimestre"
    NOVENTA_DIAS = "90d"
