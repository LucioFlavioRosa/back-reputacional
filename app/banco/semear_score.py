"""As estimativas do Score: os meses que nenhuma planilha cobre.

O QUE ESTE SCRIPT NÃO FAZ MAIS. Ele nasceu semeando também os agregados de
junho, copiados do protótipo, porque as planilhas dos fornecedores ainda não
tinham chegado. Chegaram — e a ingestão (`casos_de_uso/ingerir_mencoes.py`) lê
os quatro exports e escreve `mencao` e `score_mes_fonte` a partir do arquivo.
Manter aqui uma segunda cópia dos mesmos números seria pior que redundante:
rodar o semeador depois de um import APAGARIA o dado medido e o trocaria por
uma constante — o dado real perdendo para o rascunho, em silêncio.

O QUE SOBRA É O QUE NÃO TEM ARQUIVO. De janeiro a maio a Clipei não entregou
base: o que existe é o resumo semestral da Edelman, e dele se infere um NS
para Imprensa e Mercado. É suposição, e por isso mora em `score_estimativa`,
que a tela mostra com selo — ver o cabeçalho da 0048. Junho não entra: tem
medição, e medido ganha de suposto.

A lente institucional não é semeada nunca: ela é o clima das interações deste
banco, contado na hora.

Rodar:
    python -m app.banco.semear_score
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_fabrica_de_sessao

# `Usuario` entra para o mapeamento resolver a chave estrangeira de
# `criado_por` — o SQLAlchemy precisa da tabela registrada, e este
# semeador roda sozinho, fora do `main`.
from app.banco.tabelas_acesso import Usuario  # noqa: F401
from app.banco.tabelas_score import Lente, ScoreEstimativa

logger = logging.getLogger(__name__)

MESES = [date(2026, m, 1) for m in range(1, 6)]

#: O NS que o resumo semestral permite inferir, jan–mai.
ESTIMATIVAS: dict[str, list[float]] = {
    "imprensa": [0.45, 0.22, 0.18, 0.30, 0.38],
    "mercado": [0.35, 0.05, -0.15, 0.10, 0.30],
}

ORIGEM_DA_ESTIMATIVA = (
    "Resumo semestral Edelman (1S/2026): 83% positivo ou neutro; "
    "ajustado pelos eventos do mês"
)


def _lente(sessao: Session, codigo: str) -> Lente:
    lente = sessao.scalar(select(Lente).where(Lente.codigo == codigo))
    if lente is None:  # pragma: no cover - a 0048 semeia as cinco
        raise RuntimeError(f"Lente {codigo!r} não cadastrada — rode as migrations.")
    return lente


def principal() -> None:
    sessao = obter_fabrica_de_sessao()()
    try:
        gravadas = 0
        for codigo, serie in ESTIMATIVAS.items():
            lente = _lente(sessao, codigo)
            # APAGA ANTES: rodar duas vezes não pode dobrar nada, e a chave
            # primária é (lente, mês) — um segundo `insert` estouraria.
            sessao.execute(
                delete(ScoreEstimativa).where(
                    ScoreEstimativa.lente_id == lente.id,
                    ScoreEstimativa.mes.in_(MESES),
                )
            )
            for mes, ns in zip(MESES, serie, strict=True):
                sessao.add(
                    ScoreEstimativa(
                        lente_id=lente.id,
                        mes=mes,
                        ns=ns,
                        origem=ORIGEM_DA_ESTIMATIVA,
                    )
                )
                gravadas += 1
        sessao.commit()
        logger.info("Score: %s estimativas gravadas (jan–mai/2026).", gravadas)
        print(f"Score: {gravadas} estimativas gravadas (jan–mai/2026).")
    finally:
        sessao.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    principal()
