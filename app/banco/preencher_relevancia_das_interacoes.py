"""Preenche a Relevância da interação a partir da instituição, quando falta.

    python -m app.banco.preencher_relevancia_das_interacoes
    python -m app.banco.preencher_relevancia_das_interacoes --aplicar

O QUE ESTAVA ACONTECENDO. `interacao.tier` é um campo PRÓPRIO da interação,
independente de `instituicao.tier` — pensado para o raro caso em que a
relevância vale só para aquele encontro. Mas a importação de agenda só grava
`interacao.tier` quando a planilha traz a coluna preenchida NAQUELA linha: se
vier vazia, a interação nasce sem relevância — mesmo quando a instituição já
tem uma havia tempos (veículo de imprensa conhecido, classificado pela
Clipei). O efeito: veículos como "Valor Econômico" aparecem com Relevância
"—" na Base, apesar do cadastro da instituição já ter Tier certo.

SEM `--aplicar`, SÓ CONTA — nenhum `update`/`commit`. COM `--aplicar`, copia
o tier da instituição para a interação, só onde a interação está sem E a
instituição tem. NUNCA sobrescreve uma relevância que a própria interação já
tinha — essa pode ter sido uma correção deliberada de alguém, e sobrescrever
jogaria fora um dado mais específico com um mais genérico.

IDEMPOTENTE: depois de rodar uma vez, não sobra nenhuma linha para a segunda
execução corrigir — rodar de novo conta e aplica zero.

NÃO CORRIGE A CAUSA, só o PASSADO: a importação de agenda continua, sem outra
mudança, nascendo sem relevância quando a planilha não a traz. Esse é o
segundo passo (ajuste em `importar_agendas.py`), separado deste.
"""

from __future__ import annotations

import sys

from sqlalchemy import func, select, update

from app.banco.sessao import obter_fabrica_de_sessao
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao


def contar_pendentes(sessao) -> int:
    """Quantas interações estão sem relevância, com a instituição já tendo."""
    return sessao.scalar(
        select(func.count())
        .select_from(InteracaoRegistro)
        .join(Instituicao, Instituicao.id == InteracaoRegistro.instituicao_id)
        .where(InteracaoRegistro.tier.is_(None), Instituicao.tier.is_not(None))
    )


def aplicar(sessao) -> int:
    """Copia o tier da instituição para a interação, nos casos pendentes.

    UM `UPDATE` SÓ, e não uma linha de cada vez em Python: são, no pior caso,
    dezenas de milhares de interações, e ir e voltar do banco por linha seria
    minutos onde uma instrução é milissegundos. `scalar_subquery` correlacionada
    é o que faz cada linha copiar o tier DA SUA PRÓPRIA instituição, e não de
    uma só escolhida para todas.
    """
    resultado = sessao.execute(
        update(InteracaoRegistro)
        .where(
            InteracaoRegistro.tier.is_(None),
            InteracaoRegistro.instituicao_id.in_(
                select(Instituicao.id).where(Instituicao.tier.is_not(None))
            ),
        )
        .values(
            tier=select(Instituicao.tier)
            .where(Instituicao.id == InteracaoRegistro.instituicao_id)
            .scalar_subquery()
        )
    )
    sessao.commit()
    return resultado.rowcount


def main() -> int:
    aplicar_de_verdade = "--aplicar" in sys.argv

    with obter_fabrica_de_sessao()() as sessao:
        pendentes = contar_pendentes(sessao)
        print(
            f"{pendentes} interações sem Relevância, com a instituição já tendo Relevância."
        )
        if not aplicar_de_verdade:
            print("É só a prévia — nada foi gravado. Rode de novo com --aplicar para corrigir.")
            return 0

        corrigidas = aplicar(sessao)
        print(f"Corrigidas: {corrigidas}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
