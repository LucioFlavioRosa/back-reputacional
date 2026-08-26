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
    """Atalhos que a barra de filtros oferece."""

    ANO_CORRENTE = "ano-corrente"
    ULTIMOS_30 = "ultimos-30"
    ULTIMOS_90 = "ultimos-90"
    ULTIMOS_180 = "ultimos-180"


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
            case AtalhoDePeriodo.ANO_CORRENTE:
                return cls(de=date(referencia.year, 1, 1), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_30:
                return cls(de=referencia - timedelta(days=30), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_90:
                return cls(de=referencia - timedelta(days=90), ate=referencia)
            case AtalhoDePeriodo.ULTIMOS_180:
                return cls(de=referencia - timedelta(days=180), ate=referencia)
        raise RegraViolada(f"Atalho de período desconhecido: {atalho}")


class Janela(StrEnum):
    """Janelas de comparação das telas de porta-vozes e interlocutores."""

    SEMESTRE = "semestre"
    TRIMESTRE = "trimestre"
    NOVENTA_DIAS = "90d"
