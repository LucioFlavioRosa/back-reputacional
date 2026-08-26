"""Normalização de nome — a mesma regra na carga e na busca.

`nome_normalizado` existe para a importação deduplicar "Radamés" e "Radames"
antes de criar as chaves estrangeiras. Usar a mesma coluna na busca livre faz o
usuário encontrar o registro digitando sem acento, sem custo adicional: o
índice de trigrama já está sobre ela.

Se a carga e a busca normalizassem de formas diferentes, a busca deixaria de
encontrar exatamente os nomes que a carga uniu — por isso mora aqui, e não
duplicada nos dois lados.
"""

from __future__ import annotations

import re
import unicodedata

_ESPACOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados."""
    sem_acento = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return _ESPACOS.sub(" ", sem_acento).strip().lower()
