"""De onde o Score tira os números.

DUAS PROCEDÊNCIAS, E A JUNÇÃO ACONTECE AQUI. Quatro lentes vêm das planilhas
dos fornecedores, já somadas em `score_mes_fonte` pela ingestão. A quinta — a
institucional — é o CLIMA DAS INTERAÇÕES deste banco, contado na hora: o dado
já existe, e copiá-lo criaria duas verdades que envelhecem separado. A
primeira correção de um registro no CRM deixaria o índice mentindo até alguém
reprocessar.

A CALIBRAÇÃO É APLICADA NA LEITURA, e não gravada no agregado: o que se guarda
são as somas cruas (quantas menções, soma dos logs, do engajamento, do peso de
cargo), e a régua escolhida multiplica na hora. É o que permite a coordenação
mexer na régua e ver o índice inteiro mudar sem reprocessar nada.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date as ColunaDeData
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Clima
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_score import (
    Lente,
    ScoreConfig,
    ScoreEstimativa,
    ScoreFonte,
    ScoreMesFonte,
)
from app.dominio.score import (
    Calibracao,
    Indice,
    LenteMedida,
    SomasDaFonte,
    calcular_indice,
    medir_lente,
)

#: O código da fonte que se lê deste banco, e não de planilha.
FONTE_INTERNA_DO_CRM = "crm"

#: Como o clima de uma interação vira sentimento do índice (`SCORE.md` §2).
SENTIMENTO_DO_CLIMA: dict[str, str] = {
    "propositivo": "pos",
    "neutro": "neu",
    "tenso": "neg",
}


def primeiro_dia(mes: date) -> date:
    return mes.replace(day=1)


def calibracao_vigente(sessao: Session) -> Calibracao:
    """A última linha de `score_config`, ou o padrão das lentes.

    SEM LINHA NENHUMA É O PADRÃO, e não erro: o índice tem de funcionar antes
    de alguém abrir a Calibração pela primeira vez.
    """
    registro = sessao.scalars(
        select(ScoreConfig).order_by(ScoreConfig.versao.desc()).limit(1)
    ).first()
    if registro is None:
        return Calibracao(pesos=pesos_padrao(sessao))
    return Calibracao(
        pesos={**pesos_padrao(sessao), **(registro.pesos or {})},
        regua_tier=registro.regua_tier,
        regua_engajamento=registro.regua_engajamento,
        fontes_desligadas=frozenset(registro.fontes_desligadas or []),
    )


def pesos_padrao(sessao: Session) -> dict[str, int]:
    return {
        codigo: peso
        for codigo, peso in sessao.execute(
            select(Lente.codigo, Lente.peso_padrao).where(Lente.ativo.is_(True))
        )
    }


def lentes_cadastradas(sessao: Session) -> list[Lente]:
    return list(
        sessao.scalars(
            select(Lente).where(Lente.ativo.is_(True)).order_by(Lente.ordem)
        )
    )


def fontes_cadastradas(sessao: Session) -> list[ScoreFonte]:
    return list(sessao.scalars(select(ScoreFonte).order_by(ScoreFonte.ordem)))


def _somas_das_planilhas(sessao: Session, mes: date) -> dict[str, dict[str, list[SomasDaFonte]]]:
    """As somas que a ingestão gravou, agrupadas por lente e por fonte."""
    consulta = (
        select(
            Lente.codigo,
            ScoreFonte.codigo,
            ScoreMesFonte.sentimento,
            ScoreMesFonte.tier,
            ScoreMesFonte.mencoes,
            ScoreMesFonte.soma_log,
            ScoreMesFonte.soma_engajamento,
            ScoreMesFonte.soma_cargo,
        )
        .join(ScoreFonte, ScoreFonte.id == ScoreMesFonte.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .where(ScoreMesFonte.mes == mes)
    )

    por_lente: dict[str, dict[str, list[SomasDaFonte]]] = {}
    for linha in sessao.execute(consulta):
        lente, fonte, sentimento, tier, mencoes, log, engajamento, cargo = linha
        por_lente.setdefault(lente, {}).setdefault(fonte, []).append(
            SomasDaFonte(
                fonte=fonte,
                sentimento=sentimento,
                tier=tier or "",
                mencoes=float(mencoes),
                soma_log=float(log),
                soma_engajamento=float(engajamento),
                soma_cargo=float(cargo),
            )
        )
    return por_lente


def _somas_do_crm(sessao: Session, mes: date) -> list[SomasDaFonte]:
    """A lente institucional, contada das interações do próprio painel.

    Só o que tem clima registrado: uma interação sem clima não é neutra — ela
    não foi avaliada, e contá-la como neutra diluiria o saldo com silêncio.
    """
    proximo = (
        mes.replace(year=mes.year + 1, month=1) if mes.month == 12
        else mes.replace(month=mes.month + 1)
    )
    consulta = (
        select(Clima.codigo, func.count())
        .select_from(InteracaoRegistro)
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .where(
            InteracaoRegistro.data_interacao >= mes,
            InteracaoRegistro.data_interacao < proximo,
            InteracaoRegistro.arquivado_em.is_(None),
        )
        .group_by(Clima.codigo)
    )

    return [
        SomasDaFonte(
            fonte=FONTE_INTERNA_DO_CRM,
            sentimento=SENTIMENTO_DO_CLIMA[codigo],
            tier="",
            mencoes=float(total),
        )
        for codigo, total in sessao.execute(consulta)
        if codigo in SENTIMENTO_DO_CLIMA
    ]


def _estimativas(sessao: Session, mes: date) -> dict[str, float]:
    consulta = (
        select(Lente.codigo, ScoreEstimativa.ns)
        .join(Lente, Lente.id == ScoreEstimativa.lente_id)
        .where(ScoreEstimativa.mes == mes)
    )
    return {codigo: float(ns) for codigo, ns in sessao.execute(consulta)}


def medir_lentes(sessao: Session, mes: date, calibracao: Calibracao) -> list[LenteMedida]:
    """As cinco lentes do mês, cada uma com a fonte que lhe cabe."""
    mes = primeiro_dia(mes)
    das_planilhas = _somas_das_planilhas(sessao, mes)
    estimativas = _estimativas(sessao, mes)
    do_crm = _somas_do_crm(sessao, mes)

    medidas: list[LenteMedida] = []
    for lente in lentes_cadastradas(sessao):
        somas = dict(das_planilhas.get(lente.codigo, {}))
        # A fonte interna entra depois: ela não passa por `score_mes_fonte`.
        if do_crm and _tem_fonte_interna(sessao, lente.id):
            somas[FONTE_INTERNA_DO_CRM] = do_crm
        medidas.append(
            medir_lente(
                codigo=lente.codigo,
                nome=lente.nome,
                peso=calibracao.peso(lente.codigo, lente.peso_padrao),
                somas_por_fonte=somas,
                calibracao=calibracao,
                estimativa=estimativas.get(lente.codigo),
            )
        )
    return medidas


def _tem_fonte_interna(sessao: Session, lente_id: int) -> bool:
    return sessao.scalar(
        select(func.count())
        .select_from(ScoreFonte)
        .where(ScoreFonte.lente_id == lente_id, ScoreFonte.interna.is_(True))
    ) > 0


def indice_do_mes(sessao: Session, mes: date, calibracao: Calibracao) -> Indice:
    return calcular_indice(
        f"{primeiro_dia(mes):%Y-%m}", medir_lentes(sessao, mes, calibracao)
    )


def meses_com_dado(sessao: Session) -> list[date]:
    """Os meses que têm alguma leitura — de planilha, de estimativa ou do CRM.

    É o que alimenta o seletor de mês: oferecer um mês vazio faria a tela
    abrir sem número e parecer quebrada.
    """
    das_planilhas = select(ScoreMesFonte.mes.label("mes")).distinct()
    das_estimativas = select(ScoreEstimativa.mes.label("mes")).distinct()
    # `ColunaDeData` é o `Date` do SQLAlchemy: `date` do `datetime` já ocupa o
    # nome neste arquivo, e o `cast` precisa do tipo da coluna.
    do_crm = (
        select(
            func.date_trunc("month", InteracaoRegistro.data_interacao)
            .cast(ColunaDeData)
            .label("mes")
        )
        .where(InteracaoRegistro.clima_id.is_not(None))
        .distinct()
    )

    meses = set()
    for consulta in (das_planilhas, das_estimativas, do_crm):
        meses.update(linha[0] for linha in sessao.execute(consulta) if linha[0])
    return sorted(meses)
