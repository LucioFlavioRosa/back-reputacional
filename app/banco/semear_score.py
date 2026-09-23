"""A carga de conferência do Score: o 1º semestre de 2026.

DE ONDE VEM ESTE DADO. Dos exports que os fornecedores entregaram — Clipei
(1.506 matérias), Bites (4.973 posts classificados), Approach Social Listening
(1.959 menções) e Community Management (886 mensagens) —, já somados por mês,
sentimento e tier. Os números são os mesmos do protótipo executável
(`docs/handoff/Score Executivo Aegea.dc.html`), que os extraiu das planilhas.

POR QUE SEMEAR O AGREGADO, E NÃO A MENÇÃO. O parser de planilha só pode ser
escrito contra os arquivos, e eles ainda não chegaram. O agregado é o que o
índice consome, então semeá-lo põe o Score de pé hoje e deixa o critério de
aceite verificável (§7: com junho e a régua padrão, Imprensa 70 e ISR ≈ 58).
Quando os arquivos chegarem, a ingestão preenche `mencao` e recalcula estas
mesmas linhas — o formato não muda.

O QUE É MEDIDO E O QUE É ESTIMADO. Junho tem export das quatro fontes. De
janeiro a maio, a Clipei não entregou base: o que existe é o resumo semestral
da Edelman, e dele se infere um NS. Esses meses entram em `score_estimativa`,
que é lida com selo na tela — ver o cabeçalho da 0047. A lente institucional
não é semeada nunca: ela é o clima das interações deste banco, contado na
hora.

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
from app.banco.tabelas_score import Lente, ScoreEstimativa, ScoreFonte, ScoreMesFonte

logger = logging.getLogger(__name__)

MESES = [date(2026, m, 1) for m in range(1, 7)]

#: Clipei, junho: matérias por tier e sentimento. É o único mês com base.
CLIPEI_JUNHO: dict[str, dict[str, int]] = {
    "muito_relevante": {"pos": 65, "neu": 64, "neg": 16},
    "relevante": {"pos": 85, "neu": 43, "neg": 55},
    "menos_relevante": {"pos": 946, "neu": 80, "neg": 149},
}

#: Mercado, junho: proxy pelos veículos Muito Relevante com público
#: investidores. Sem tier — já são todos do mesmo.
MERCADO_JUNHO = {"pos": 65, "neu": 64, "neg": 16}

#: Approach Social Listening, jan–jun. Três leituras do mesmo mês: contagem,
#: soma de 1+log10(1+engajamento) e engajamento bruto.
APPROACH_SL: list[dict[str, dict[str, int]]] = [
    {"n": {"pos": 1843, "neu": 39, "neg": 470},
     "log": {"pos": 2622, "neu": 74, "neg": 548},
     "eng": {"pos": 70783, "neu": 1490, "neg": 9894}},
    {"n": {"pos": 495, "neu": 136, "neg": 716},
     "log": {"pos": 863, "neu": 212, "neg": 808},
     "eng": {"pos": 18267, "neu": 3566, "neg": 3759}},
    {"n": {"pos": 518, "neu": 152, "neg": 1296},
     "log": {"pos": 959, "neu": 255, "neg": 1364},
     "eng": {"pos": 12557, "neu": 3571, "neg": 4256}},
    {"n": {"pos": 494, "neu": 129, "neg": 518},
     "log": {"pos": 727, "neu": 217, "neg": 826},
     "eng": {"pos": 5133, "neu": 3573, "neg": 8790}},
    {"n": {"pos": 513, "neu": 98, "neg": 506},
     "log": {"pos": 985, "neu": 159, "neg": 655},
     "eng": {"pos": 13039, "neu": 1581, "neg": 4785}},
    {"n": {"pos": 707, "neu": 142, "neg": 1110},
     "log": {"pos": 1238, "neu": 288, "neg": 1274},
     "eng": {"pos": 20544, "neu": 25994, "neg": 12716}},
]

#: Bites, só junho — a metodologia mudou no mês, e os anteriores não são
#: comparáveis. É a única fonte que traz o cargo de quem postou.
BITES_JUNHO = {
    "n": {"pos": 888, "neu": 1501, "neg": 2584},
    "log": {"pos": 1417, "neu": 2245, "neg": 3714},
    "eng": {"pos": 25237, "neu": 43689, "neg": 107886},
    "cargo": {"pos": 888, "neu": 1501, "neg": 2591},
}

#: Approach Community Management, jan–jun: os canais próprios.
APPROACH_CM: list[dict[str, int]] = [
    {"pos": 125, "neu": 119, "neg": 253},
    {"pos": 126, "neu": 81, "neg": 306},
    {"pos": 175, "neu": 212, "neg": 408},
    {"pos": 131, "neu": 293, "neg": 378},
    {"pos": 149, "neu": 340, "neg": 527},
    {"pos": 146, "neu": 452, "neg": 288},
]

#: O NS que o resumo semestral permite inferir, jan–mai. Junho não entra: tem
#: medição, e medido ganha de suposto.
ESTIMATIVAS: dict[str, list[float | None]] = {
    "imprensa": [0.45, 0.22, 0.18, 0.30, 0.38, None],
    "mercado": [0.35, 0.05, -0.15, 0.10, 0.30, None],
}

ORIGEM_DA_ESTIMATIVA = (
    "Resumo semestral Edelman (1S/2026): 83% positivo ou neutro; "
    "ajustado pelos eventos do mês"
)


def _fonte(sessao: Session, codigo: str) -> ScoreFonte:
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
    if fonte is None:  # pragma: no cover - a 0047 semeia as seis
        raise RuntimeError(f"Fonte {codigo!r} não cadastrada — rode as migrations.")
    return fonte


def _gravar(
    sessao: Session, fonte: ScoreFonte, mes: date, sentimento: str, tier: str,
    *, mencoes: float, log: float = 0, engajamento: float = 0, cargo: float = 0,
) -> None:
    sessao.add(
        ScoreMesFonte(
            fonte_id=fonte.id, mes=mes, sentimento=sentimento, tier=tier,
            mencoes=int(mencoes), soma_log=log,
            soma_engajamento=int(engajamento), soma_cargo=cargo,
        )
    )


def principal() -> None:
    sessao = obter_fabrica_de_sessao()()
    try:
        clipei = _fonte(sessao, "clipei")
        edelman = _fonte(sessao, "edelman")
        approach_sl = _fonte(sessao, "approach_sl")
        bites = _fonte(sessao, "bites")
        approach_cm = _fonte(sessao, "approach_cm")

        # REFAZ A CARGA INTEIRA. O semeador é idempotente por apagar antes:
        # rodar duas vezes não pode dobrar as contagens do índice.
        ids = [clipei.id, edelman.id, approach_sl.id, bites.id, approach_cm.id]
        sessao.execute(
            delete(ScoreMesFonte).where(
                ScoreMesFonte.fonte_id.in_(ids), ScoreMesFonte.mes.in_(MESES)
            )
        )
        sessao.execute(delete(ScoreEstimativa).where(ScoreEstimativa.mes.in_(MESES)))

        junho = MESES[5]
        for tier, contagens in CLIPEI_JUNHO.items():
            for sentimento, total in contagens.items():
                _gravar(sessao, clipei, junho, sentimento, tier, mencoes=total)

        for sentimento, total in MERCADO_JUNHO.items():
            _gravar(sessao, edelman, junho, sentimento, "", mencoes=total)

        for indice, mes in enumerate(MESES):
            leituras = APPROACH_SL[indice]
            for sentimento in ("pos", "neu", "neg"):
                _gravar(
                    sessao, approach_sl, mes, sentimento, "",
                    mencoes=leituras["n"][sentimento],
                    log=leituras["log"][sentimento],
                    engajamento=leituras["eng"][sentimento],
                    # Approach não traz cargo: a régua cai na contagem.
                    cargo=leituras["n"][sentimento],
                )
            for sentimento, total in APPROACH_CM[indice].items():
                _gravar(
                    sessao, approach_cm, mes, sentimento, "",
                    mencoes=total, log=total, engajamento=total, cargo=total,
                )

        for sentimento in ("pos", "neu", "neg"):
            _gravar(
                sessao, bites, junho, sentimento, "",
                mencoes=BITES_JUNHO["n"][sentimento],
                log=BITES_JUNHO["log"][sentimento],
                engajamento=BITES_JUNHO["eng"][sentimento],
                cargo=BITES_JUNHO["cargo"][sentimento],
            )

        lentes = {
            lente.codigo: lente.id for lente in sessao.scalars(select(Lente))
        }
        for codigo, valores in ESTIMATIVAS.items():
            for indice, ns in enumerate(valores):
                if ns is None:
                    continue
                sessao.add(
                    ScoreEstimativa(
                        lente_id=lentes[codigo], mes=MESES[indice], ns=ns,
                        origem=ORIGEM_DA_ESTIMATIVA,
                        nota="Sem export da Clipei neste mês.",
                    )
                )

        sessao.commit()
        logger.info(
            "Score semeado: junho com quatro fontes, jan–mai com estimativa."
        )
    finally:
        sessao.close()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    principal()
