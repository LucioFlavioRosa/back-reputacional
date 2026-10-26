"""Escrever os vínculos de risco de um tema, num lugar só.

A FUNÇÃO MORAVA EM `app/api/stakeholders.py`, com dois chamadores. A importação
de subtemas é o terceiro, e um caso de uso não pode importar da camada de API
sem inverter a dependência: o `app/__init__.py` deste projeto diz que `api/` são
as rotas e `casos_de_uso/` o que elas orquestram, e a flecha aponta num sentido
só.

A alternativa era copiar as dez linhas para cá, e o preço disso já apareceu:
`TabelaDeInteracoes` tinha uma CÓPIA do resolvedor de nome de formato, e quando
o original aprendeu a enxergar formato aposentado a cópia seguiu devolvendo
travessão — na tela que mais gente abre.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import TemaRisco


def aplicar_riscos_do_tema(sessao: Session, tema_id: int, riscos: list[int]) -> None:
    """Substitui a lista inteira, casando por (tema, risco).

    NÃO APAGA E RECRIA TUDO, mesmo raciocínio de `_aplicar_temas_da_pessoa`:
    `delete` seguido de `insert` troca o vínculo que não mudou por um vínculo
    novo igual, e quem lê o log de auditoria vê mudança onde não houve.
    """
    atuais = {
        v.risco_id: v
        for v in sessao.scalars(select(TemaRisco).where(TemaRisco.tema_id == tema_id))
    }
    desejados = set(riscos)

    for risco_id, vinculo in atuais.items():
        if risco_id not in desejados:
            sessao.delete(vinculo)
    for risco_id in desejados - set(atuais):
        sessao.add(TemaRisco(tema_id=tema_id, risco_id=risco_id))
    sessao.flush()
