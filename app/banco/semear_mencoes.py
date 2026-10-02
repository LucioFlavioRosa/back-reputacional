"""Menções de mentira para as quatro lentes que hoje não têm nenhum dado
medido — Imprensa, Mercado, Sociedade digital e Clientes.

DIFERENTE DE `semear_lentes.py`. Aquele transcreve o Balanço Reputacional de
verdade do cliente; este aqui é inventado do zero, só para o ambiente de
demonstração não abrir com quatro lentes vazias e um ISR que é o score de uma
lente só. Nada disto é medição, nem é relatório de ninguém — é enredo.

POR QUE NÃO HÁ SELO "EXEMPLO" NA TELA PARA ISTO. `mencao` não tem a coluna
`exemplo` que `jornalista_matriz`/`evento_mercado`/`estudo_percepcao` têm —
ela é preenchida do mesmo jeito por uma planilha de fornecedor de verdade ou
por este semeador, e a tela não tem como distinguir os dois casos. Por isso
este script só deve rodar num ambiente que todo mundo já sabe ser de
demonstração (hoje, o `dev`) — nunca contra uma base com carga real.

MESMO GRÃO DA INGESTÃO DE VERDADE. Usa `MencaoLida` e `somar()` de
`dominio/ingestao_score.py` — as mesmas funções que `ingerir_mencoes.py` usa
ao ler uma planilha de fornecedor — para o `score_mes_fonte` (de onde a nota
da lente sai) bater com o que os gráficos de `mencao` mostram, em vez de
serem dois números inventados em paralelo.

IDEMPOTENTE. Apaga e regrava por (fonte, mês) antes de inserir — rodar de
novo não duplica.

Rodar:
    python -m app.banco.semear_mencoes
"""

from __future__ import annotations

import logging
import random
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.banco.sessao import obter_fabrica_de_sessao

# `UnidadeNegocio` e `Tema` entram para o mapeamento resolver as chaves
# estrangeiras de `Mencao` — este semeador roda sozinho, fora do `main`, que é
# quem normalmente importa todas as tabelas.
from app.banco.tabelas_catalogo import Tema, UnidadeNegocio  # noqa: F401
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.ingestao_score import MencaoLida, somar

logger = logging.getLogger(__name__)

#: Mesma janela da lente institucional, que já tem dado de verdade — para o
#: mês mais completo (`repositorio_score.mes_mais_completo`) juntar as cinco.
MESES = [date(2026, mes, 1) for mes in range(1, 9)]

TEMAS = [
    "Tarifa", "Universalização", "Regulação", "Qualidade da água",
    "Obras e investimentos", "Atendimento ao cliente", "Disciplina financeira",
    "Sustentabilidade",
]
VEICULOS_IMPRENSA = ["Valor Econômico", "Folha de S.Paulo", "O Globo", "InfoMoney", "Estadão"]
TIERS = ["muito_relevante", "relevante", "menos_relevante"]
CONCESSIONARIAS = ["Aegea Norte", "Aegea Sul", "Aegea Centro-Oeste", "Prolagos", "Saneágua"]
#: OS 7 PILARES REPUTACIONAIS (slide Peers/Comms, 29/09/2026) — "Transversal
#: aos pilares" não entra: é regra de classificação ("conta no pilar que o
#: prêmio reconhece"), não um pilar que uma matéria possa pertencer. ESTE
#: AINDA É UM CHUTE: a Clipei nunca mandou pilar nenhum pra gente — os 4
#: valores que estavam aqui antes (Governança, Qualidade do serviço,
#: Responsabilidade ambiental, Solidez financeira) também eram inventados,
#: só que sem ligação com taxonomia nenhuma. Trocar para os 7 é só para o
#: ambiente de demonstração já nascer coerente com a estrutura nova — vale
#: confirmar com quem administra a conta da Clipei se ela classifica por
#: pilar de verdade, e qual o vocabulário real, antes disto significar algo.
ATRIBUTOS = [
    "Governança",
    "Eficiência Operacional e Qualidade",
    "Crescimento e Solidez Financeira",
    "Responsabilidade Social",
    "Responsabilidade Ambiental",
    "Inovação e Tecnologia",
    "Prosperidade Compartilhada",
]
TEORES_CLIENTES = ["Reclamação", "Dúvida", "Elogio", "Informação"]


def _sentimento(positivo: float, neutro: float) -> str:
    r = random.random()
    if r < positivo:
        return "pos"
    if r < positivo + neutro:
        return "neu"
    return "neg"


def _imprensa_ou_mercado(por_mes: int) -> list[MencaoLida]:
    return [
        MencaoLida(
            mes=mes,
            data=date(mes.year, mes.month, random.randint(1, 28)),
            sentimento=_sentimento(0.45, 0.35),
            tier=random.choices(TIERS, weights=[2, 5, 3])[0],
            veiculo=random.choice(VEICULOS_IMPRENSA),
            publico_alvo="geral",
            atributo=random.choice(ATRIBUTOS),
            tema_texto=random.choice(TEMAS),
        )
        for mes in MESES
        for _ in range(random.randint(por_mes - 4, por_mes + 4))
    ]


def _sociedade(por_mes: int) -> list[MencaoLida]:
    return [
        MencaoLida(
            mes=mes,
            data=date(mes.year, mes.month, random.randint(1, 28)),
            sentimento=_sentimento(0.35, 0.30),
            engajamento=random.randint(0, 500),
            unidade_texto=random.choice(CONCESSIONARIAS),
            tema_texto=random.choice(TEMAS),
        )
        for mes in MESES
        for _ in range(random.randint(por_mes - 6, por_mes + 6))
    ]


def _clientes(por_mes: int) -> list[MencaoLida]:
    mencoes = []
    for mes in MESES:
        for _ in range(random.randint(por_mes - 6, por_mes + 6)):
            teor = random.choices(TEORES_CLIENTES, weights=[3, 3, 2, 2])[0]
            mencoes.append(
                MencaoLida(
                    mes=mes,
                    data=date(mes.year, mes.month, random.randint(1, 28)),
                    sentimento=_sentimento(0.30, 0.30),
                    engajamento=random.randint(0, 50),
                    teor=teor,
                    acionavel=teor in ("Reclamação", "Dúvida", "Elogio"),
                )
            )
    return mencoes


def _gravar(sessao: Session, codigo_fonte: str, mencoes: list[MencaoLida]) -> int:
    fonte = sessao.query(ScoreFonte).filter_by(codigo=codigo_fonte).one()
    meses = {m.mes for m in mencoes}
    sessao.execute(delete(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes.in_(meses)))
    sessao.execute(
        delete(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes.in_(meses)
        )
    )
    sessao.add_all(
        Mencao(
            fonte_id=fonte.id, mes=m.mes, data=m.data, sentimento=m.sentimento, tier=m.tier,
            engajamento=m.engajamento, cargo=m.cargo, atributo=m.atributo, veiculo=m.veiculo,
            publico_alvo=m.publico_alvo, tema_texto=m.tema_texto, unidade_texto=m.unidade_texto,
            teor=m.teor, acionavel=m.acionavel, autor=m.autor,
        )
        for m in mencoes
    )
    sessao.add_all(
        ScoreMesFonte(
            fonte_id=fonte.id, mes=s.mes, sentimento=s.sentimento, tier=s.tier,
            mencoes=s.mencoes, soma_log=s.soma_log, soma_engajamento=s.soma_engajamento,
            soma_cargo=s.soma_cargo,
        )
        for s in somar(mencoes)
    )
    return len(mencoes)


def principal() -> None:
    random.seed(42)
    sessao = obter_fabrica_de_sessao()()
    try:
        total = 0
        total += _gravar(sessao, "clipei", _imprensa_ou_mercado(18))
        total += _gravar(sessao, "clipei_investidores", _imprensa_ou_mercado(8))
        total += _gravar(sessao, "approach_sl", _sociedade(15))
        total += _gravar(sessao, "bites", _sociedade(12))
        # 500, e não os 30 das outras fontes: "respondidas" vem do relatório de
        # verdade (semear_lentes.py, 383-607/mês) e "recebidas" precisa ficar
        # na mesma ordem de grandeza, ou a taxa de resposta estoura para mais
        # de 1000% — mock demais para até parecer erro de conta.
        total += _gravar(sessao, "approach_cm", _clientes(500))
        sessao.commit()
        logger.info("Menções de mentira: %s linhas gravadas.", total)
        print(f"Menções de mentira: {total} linhas gravadas (Jan-Ago 2026, 4 lentes).")
    finally:
        sessao.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    principal()
