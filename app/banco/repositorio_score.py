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

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Date as ColunaDeData
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Clima, Tema
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_score import (
    Lente,
    Mencao,
    ScoreConfig,
    ScoreEstimativa,
    ScoreFato,
    ScoreFonte,
    ScoreMesFonte,
)
from app.dominio.assunto_do_mes import MencoesDoAssunto
from app.dominio.score import (
    Calibracao,
    Contagem,
    Indice,
    LenteMedida,
    SomasDaFonte,
    calcular_indice,
    medir_lente,
    ns,
    ponderar,
)

logger = logging.getLogger(__name__)

#: O código da fonte que se lê deste banco, e não de planilha.
FONTE_INTERNA_DO_CRM = "crm"

#: Como o clima de uma interação vira sentimento do índice (`SCORE.md` §2).
#:
#: PELO `codigo`, E NÃO PELO `nome`. O rótulo já mudou duas vezes — Proativo /
#: Reativo na 0030, Positivo / Negativo na 0047 — e nas duas o `codigo`
#: continuou o mesmo, exatamente para que mapeamentos como este não precisem
#: ser caçados a cada renomeação.
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
        limites=dict(registro.limites or {}),
        radial_por_peso=registro.radial_por_peso,
    )


def pesos_padrao(sessao: Session) -> dict[str, int]:
    return {
        codigo: peso
        for codigo, peso in sessao.execute(
            select(Lente.codigo, Lente.peso_padrao).where(Lente.ativo.is_(True))
        )
    }


def lentes_cadastradas(sessao: Session) -> list[Lente]:
    return list(sessao.scalars(select(Lente).where(Lente.ativo.is_(True)).order_by(Lente.ordem)))


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
        mes.replace(year=mes.year + 1, month=1)
        if mes.month == 12
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

    somas: list[SomasDaFonte] = []
    for codigo, total in sessao.execute(consulta):
        sentimento = SENTIMENTO_DO_CLIMA.get(codigo)
        if sentimento is None:
            # UM CLIMA NOVO NÃO PODE SUMIR EM SILÊNCIO. `clima` é dicionário
            # fechado, então chegar aqui significa que alguém o abriu — e a
            # lente institucional passaria a ignorar as interações desse clima
            # sem nenhum sinal, devolvendo um número menor e plausível.
            #
            # Não é erro fatal de propósito: derrubar o Score inteiro da
            # companhia porque uma linha de dicionário mudou seria pior que o
            # desvio. O sinal é o log — e o teste de mapeamento, que quebra no
            # CI no mesmo dia em que o clima for criado.
            logger.warning(
                "Clima %r sem mapeamento em SENTIMENTO_DO_CLIMA: "
                "%s interações ficaram fora da lente institucional de %s.",
                codigo,
                total,
                mes,
            )
            continue
        somas.append(
            SomasDaFonte(
                fonte=FONTE_INTERNA_DO_CRM,
                sentimento=sentimento,
                tier="",
                mencoes=float(total),
            )
        )
    return somas


def _estimativas(sessao: Session, mes: date) -> dict[str, float]:
    consulta = (
        select(Lente.codigo, ScoreEstimativa.ns)
        .join(Lente, Lente.id == ScoreEstimativa.lente_id)
        .where(ScoreEstimativa.mes == mes)
    )
    return {codigo: float(ns) for codigo, ns in sessao.execute(consulta)}


@dataclass(frozen=True, slots=True)
class LenteNoCadastro:
    """O que uma lente é, antes de qualquer mês. Não muda entre medições."""

    codigo: str
    nome: str
    peso_padrao: int
    fontes: tuple[str, ...]
    tem_fonte_interna: bool


def catalogo_das_lentes(sessao: Session) -> list[LenteNoCadastro]:
    """O cadastro inteiro em DUAS consultas, e não em onze.

    POR QUE ISTO EXISTE. `medir_lentes` perguntava, PARA CADA MÊS, quais lentes
    existem, quais fontes cada uma tem e qual delas é interna — respostas que
    não mudam entre um mês e outro. A série de dez meses saía em 147 consultas,
    das quais 110 repetiam a mesma pergunta; e a conta piora a cada mês
    ingerido, que é exatamente o que vai acontecer.

    O CADASTRO É LIDO UMA VEZ e atravessa a série inteira. Não é cache: é o
    mesmo pedido lendo o que não varia dentro dele uma vez só, o que também
    elimina a chance de dois meses da mesma resposta enxergarem cadastros
    diferentes.
    """
    lentes = lentes_cadastradas(sessao)
    por_lente: dict[int, list[ScoreFonte]] = {}
    for fonte in sessao.scalars(select(ScoreFonte).order_by(ScoreFonte.ordem)):
        por_lente.setdefault(fonte.lente_id, []).append(fonte)

    return [
        LenteNoCadastro(
            codigo=lente.codigo,
            nome=lente.nome,
            peso_padrao=lente.peso_padrao,
            # `ativo` não entra no filtro: um fornecedor descontinuado para de
            # receber importação, e o histórico dele continua valendo — ver o
            # comentário da 0048.
            fontes=tuple(f.codigo for f in por_lente.get(lente.id, ())),
            tem_fonte_interna=any(f.interna for f in por_lente.get(lente.id, ())),
        )
        for lente in lentes
    ]


def medir_lentes(
    sessao: Session,
    mes: date,
    calibracao: Calibracao,
    catalogo: list[LenteNoCadastro] | None = None,
) -> list[LenteMedida]:
    """As cinco lentes do mês, cada uma com a fonte que lhe cabe.

    `catalogo` é opcional para quem mede UM mês; quem mede uma série o lê uma
    vez e passa adiante — ver `catalogo_das_lentes`.
    """
    mes = primeiro_dia(mes)
    das_planilhas = _somas_das_planilhas(sessao, mes)
    estimativas = _estimativas(sessao, mes)
    do_crm = _somas_do_crm(sessao, mes)

    medidas: list[LenteMedida] = []
    for lente in catalogo if catalogo is not None else catalogo_das_lentes(sessao):
        somas = dict(das_planilhas.get(lente.codigo, {}))
        # A fonte interna entra depois: ela não passa por `score_mes_fonte`.
        if do_crm and lente.tem_fonte_interna:
            somas[FONTE_INTERNA_DO_CRM] = do_crm
        medidas.append(
            medir_lente(
                codigo=lente.codigo,
                nome=lente.nome,
                peso=calibracao.peso(lente.codigo, lente.peso_padrao),
                somas_por_fonte=somas,
                calibracao=calibracao,
                estimativa=estimativas.get(lente.codigo),
                fontes_cadastradas=lente.fontes,
            )
        )
    return medidas


def _codigos_das_fontes(sessao: Session, lente_id: int) -> tuple[str, ...]:
    """As fontes CADASTRADAS da lente, tenham dado no mês ou não.

    `ativo` não entra no filtro: um fornecedor descontinuado para de receber
    importação, e o histórico dele continua valendo — ver o comentário da 0048.
    """
    return tuple(
        sessao.scalars(
            select(ScoreFonte.codigo)
            .where(ScoreFonte.lente_id == lente_id)
            .order_by(ScoreFonte.ordem)
        )
    )


def _tem_fonte_interna(sessao: Session, lente_id: int) -> bool:
    return (
        sessao.scalar(
            select(func.count())
            .select_from(ScoreFonte)
            .where(ScoreFonte.lente_id == lente_id, ScoreFonte.interna.is_(True))
        )
        > 0
    )


def _somas_da_lente(sessao: Session, lente_id: int, mes: date) -> dict[str, list[SomasDaFonte]]:
    """As somas de uma lente, por fonte — incluindo a interna."""
    lente = sessao.get(Lente, lente_id)
    das_planilhas = _somas_das_planilhas(sessao, primeiro_dia(mes)).get(
        lente.codigo if lente else "", {}
    )
    somas = dict(das_planilhas)
    if _tem_fonte_interna(sessao, lente_id):
        do_crm = _somas_do_crm(sessao, primeiro_dia(mes))
        if do_crm:
            somas[FONTE_INTERNA_DO_CRM] = do_crm
    return somas


def composicao_da_lente(
    sessao: Session, lente_id: int, mes: date, calibracao: Calibracao
) -> Contagem:
    """Os três números da fórmula, já ponderados — o que a barra desenha.

    SOMA DAS FONTES LIGADAS, e não a média de NS: a média é como o SCORE da
    lente sai (§2.4), mas a barra mostra volume, e volume se soma.
    """
    total = Contagem()
    for fonte, linhas in _somas_da_lente(sessao, lente_id, mes).items():
        if calibracao.ligada(fonte):
            total = total + ponderar(linhas, calibracao)
    return total


def fontes_da_lente(
    sessao: Session, lente_id: int, mes: date, calibracao: Calibracao
) -> list[tuple[ScoreFonte, float | None, int]]:
    """Cada fonte da lente com o seu próprio NS e o volume do mês.

    É o que deixa a tela responder "qual das duas está puxando a lente para
    baixo" — com a média de NS, uma fonte pode esconder a outra.

    O NS DE UMA FONTE DESLIGADA É CALCULADO ASSIM MESMO, de propósito: é a
    resposta para "o que aconteceria se eu religasse esta". Quem diz que ela
    não entrou no score é o campo `ligada`, que a API devolve ao lado — e a
    tela precisa mostrar os dois juntos, senão o número vira explicação de um
    score do qual não participou.
    """
    somas = _somas_da_lente(sessao, lente_id, mes)
    saida = []
    for fonte in sessao.scalars(
        select(ScoreFonte).where(ScoreFonte.lente_id == lente_id).order_by(ScoreFonte.ordem)
    ):
        linhas = somas.get(fonte.codigo, [])
        saida.append(
            (
                fonte,
                ns(ponderar(linhas, calibracao)) if linhas else None,
                int(sum(linha.mencoes for linha in linhas)),
            )
        )
    return saida


def temas_da_lente(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    quantos: int = 5,
) -> list[tuple[str, int, int, str | None]]:
    """Os temas mais falados da lente no mês, com positivo × negativo.

    Vem de `mencao`, que só a INGESTÃO preenche: sem planilha importada a lista
    volta vazia, e a tela diz por quê. Preferir uma lista vazia a números
    inventados é o que mantém a leitura honesta.

    A CALIBRAÇÃO VALE AQUI TAMBÉM. Desligar a Bites tira os posts dela do
    score da lente; deixar os temas dela na aba de Drivers explicaria o número
    por um dado que não entrou nele. Quem lê o gráfico não tem como saber.

    O NOME SAI DE DOIS LUGARES. `tema_id` aponta para o vocabulário do CRM,
    que é o bom: é por ele que um tema do Score e um tema de reunião são o
    mesmo tema. Mas o fornecedor manda o assunto no vocabulário DELE, e enquanto
    ninguém casou as duas listas é o texto bruto que a tela tem para mostrar.
    Exigir a correspondência deixaria a aba de Drivers vazia com o banco cheio.
    """
    rotulo = func.coalesce(Tema.nome, Mencao.tema_texto)
    consulta = (
        select(
            rotulo.label("tema"),
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neg"),
            # Só o tema do CRM tem tipo; agrupado pelo rótulo, `max` devolve o
            # único valor não nulo do grupo — ou nulo, quando veio só do texto.
            func.max(Tema.tipo),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            rotulo.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(rotulo)
        # ORDENADO PELO QUE TOMA PARTIDO, e não pelo volume. Os assuntos mais
        # numerosos da Approach são etiquetas de operação — "spam", "Stories -
        # marcado" —, com centenas de menções neutras e nenhuma positiva ou
        # negativa. Ordenar por volume encheria "Drivers e riscos" com cinco
        # barras vazias e esconderia Falta de Água.
        .having(func.count().filter(Mencao.sentimento.in_(("pos", "neg"))) > 0)
        .order_by(func.count().filter(Mencao.sentimento.in_(("pos", "neg"))).desc())
        .limit(quantos)
    )
    return [(nome, pos, neg, tipo) for nome, pos, neg, tipo in sessao.execute(consulta)]


def indice_do_mes(
    sessao: Session,
    mes: date,
    calibracao: Calibracao,
    catalogo: list[LenteNoCadastro] | None = None,
) -> Indice:
    return calcular_indice(
        f"{primeiro_dia(mes):%Y-%m}", medir_lentes(sessao, mes, calibracao, catalogo)
    )


def mes_mais_completo(sessao: Session, calibracao: Calibracao) -> date | None:
    """O mês que a tela deve abrir: o de MAIS LENTES medidas, e não o último.

    O CRM é a única fonte que se alimenta sozinha — cada interação registrada
    põe um mês novo na lista, mesmo sem nenhuma planilha de fornecedor. Abrir
    no mês mais recente levava, por isso, a uma tela com quatro lentes vazias e
    um ISR que era o score de uma lente só: o pior primeiro contato possível
    com um índice, porque parece que o dado sumiu.

    Empate resolve pelo mais recente — entre dois meses igualmente completos,
    quem chega quer ver o último.
    """
    das_planilhas = (
        select(ScoreMesFonte.mes.label("mes"), ScoreFonte.lente_id.label("lente_id"))
        .join(ScoreFonte, ScoreFonte.id == ScoreMesFonte.fonte_id)
        .where(*so_fontes_ligadas(calibracao))
        .distinct()
    )
    das_estimativas = select(
        ScoreEstimativa.mes.label("mes"), ScoreEstimativa.lente_id.label("lente_id")
    ).distinct()
    # A institucional vem das interações, e não de `score_mes_fonte`.
    do_crm = (
        select(
            func.date_trunc("month", InteracaoRegistro.data_interacao)
            .cast(ColunaDeData)
            .label("mes"),
            ScoreFonte.lente_id.label("lente_id"),
        )
        .select_from(InteracaoRegistro)
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .join(ScoreFonte, ScoreFonte.codigo == FONTE_INTERNA_DO_CRM)
        .where(
            InteracaoRegistro.arquivado_em.is_(None),
            *so_fontes_ligadas(calibracao),
        )
        .distinct()
    )

    tudo = das_planilhas.union(das_estimativas, do_crm).subquery()
    consulta = (
        select(tudo.c.mes)
        .group_by(tudo.c.mes)
        .order_by(func.count(func.distinct(tudo.c.lente_id)).desc(), tudo.c.mes.desc())
        .limit(1)
    )
    return sessao.scalar(consulta)


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


# -- a aba de Drivers e riscos --------------------------------------------------
#
# As três leituras desta aba respondem "POR QUE o índice deu isso", e todas as
# três se fazem MENÇÃO A MENÇÃO — não saem de `score_mes_fonte`, que já perdeu o
# atributo, o tema e a unidade ao somar. É por isso que elas só acenderam quando
# a ingestão passou a gravar `mencao`.
#
# TODAS RESPEITAM A CALIBRAÇÃO. Explicar o número com o dado de uma fonte que a
# coordenação tirou do cálculo é pior do que não explicar: quem lê o gráfico não
# tem como saber que aquela barra não entrou na conta.
#
# E NENHUMA APLICA A RÉGUA DE TIER OU DE ENGAJAMENTO. Aqui se conta matéria e
# post, um a um: a pergunta é "sobre o que falaram e com que tom", e não "quanto
# isso pesou no índice". Ponderar aqui faria uma matéria do Valor aparecer como
# dez, e a barra deixaria de ser contagem sem avisar.


def mencoes_por_assunto(
    sessao: Session, meses: Sequence[date], calibracao: Calibracao
) -> dict[date, list[MencoesDoAssunto]]:
    """Os assuntos de cada mês, com o total da lente ao lado.

    UMA CONSULTA PARA O PERÍODO INTEIRO. A série já mede mês a mês; somar a
    isso uma ida ao banco por coluna faria a tela mais cara a cada mês
    ingerido, que é o que acontece todo mês.

    O TOTAL DA LENTE VEM JUNTO porque é o denominador do NS: sem ele, o peso de
    um assunto teria de ser recalculado a partir de outra consulta, e as duas
    poderiam discordar.
    """
    rotulo = func.coalesce(Tema.nome, Mencao.tema_texto)
    consulta = (
        select(
            Mencao.mes,
            Lente.codigo,
            rotulo.label("assunto"),
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neg"),
            func.count(),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .where(Mencao.mes.in_(list(meses)), *so_fontes_ligadas(calibracao))
        .group_by(Mencao.mes, Lente.codigo, rotulo)
    )

    linhas = list(sessao.execute(consulta))
    # O DENOMINADOR É A LENTE INTEIRA, inclusive as menções sem assunto: elas
    # entraram no NS e tirá-las do total faria as contribuições somarem mais do
    # que a lente de fato pôs no índice.
    total_da_lente: dict[tuple[date, str], int] = {}
    for mes, lente, _assunto, _pos, _neg, total in linhas:
        chave = (mes, lente)
        total_da_lente[chave] = total_da_lente.get(chave, 0) + total

    por_mes: dict[date, list[MencoesDoAssunto]] = {}
    for mes, lente, assunto, pos, neg, _total in linhas:
        if assunto is None:
            continue
        por_mes.setdefault(mes, []).append(
            MencoesDoAssunto(
                lente=lente,
                assunto=assunto,
                positivas=pos,
                negativas=neg,
                total_da_lente=total_da_lente[(mes, lente)],
            )
        )
    return por_mes


def fatos_do_periodo(sessao: Session, meses: list[date]) -> list[ScoreFato]:
    """O que explica a curva, nos meses que a evolução mostra.

    O DOSSIÊ MOSTRA A JANELA INTEIRA, e não só o mês escolhido: um fato de
    fevereiro é o que explica o degrau de fevereiro no gráfico — lê-lo só ao
    trocar o seletor para fevereiro obrigaria a pessoa a caçar a explicação mês
    a mês.
    """
    return list(
        sessao.scalars(
            select(ScoreFato)
            .where(ScoreFato.mes.in_(meses))
            .order_by(ScoreFato.mes, ScoreFato.criado_em)
        )
    )


def mencoes_do_mes(sessao: Session, mes: date, calibracao: Calibracao) -> int:
    """Quantas menções individuais o mês tem, de fonte que está no cálculo.

    É o que distingue "não houve nada a dizer" de "a planilha ainda não foi
    importada" — duas situações que produzem a mesma tela vazia.
    """
    total = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(Mencao.mes == primeiro_dia(mes), *so_fontes_ligadas(calibracao))
    )
    return int(total or 0)


def atributos_do_mes(
    sessao: Session, mes: date, calibracao: Calibracao
) -> list[tuple[str, int, int, int]]:
    """O atributo reputacional da clipagem, com positivo, neutro e negativo.

    É a taxonomia do fornecedor — Governança, Eficiência Operacional,
    Prosperidade Compartilhada — e responde o que a companhia é ACUSADA ou
    CREDITADA de ser. Só Clipei e Bites classificam atributo; as outras fontes
    simplesmente não entram, e é isso que a tela diz.
    """
    consulta = (
        select(
            Mencao.atributo,
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            func.count().filter(Mencao.sentimento == "neg"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            Mencao.mes == primeiro_dia(mes),
            Mencao.atributo.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.atributo)
        # O DESEMPATE PELO NOME é o que faz a lista não trocar de ordem entre
        # dois carregamentos do mesmo mês — dois atributos com o mesmo volume
        # não têm ordem natural, e o Postgres não promete nenhuma.
        .order_by(func.count().desc(), Mencao.atributo.asc())
    )
    return [(nome, pos, neu, neg) for nome, pos, neu, neg in sessao.execute(consulta)]


def negativas_do_mes(sessao: Session, mes: date, calibracao: Calibracao) -> int:
    """Todas as menções negativas do mês, de fonte ligada.

    É O DENOMINADOR da participação de cada unidade — e precisa ser o total de
    verdade, e não a soma das que couberam no ranking. Com as oito primeiras
    como base, a nona unidade negativa some da conta e as oito passam a somar
    100% de um todo que não existe.
    """
    total = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            Mencao.mes == primeiro_dia(mes),
            Mencao.sentimento == "neg",
            Mencao.unidade_texto.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
    )
    return int(total or 0)


def unidades_do_mes(
    sessao: Session, mes: date, calibracao: Calibracao, quantos: int = 8
) -> list[tuple[str, int, int]]:
    """Onde a pressão se concentra: negativas por concessionária.

    ORDENADO PELO NEGATIVO, e não pelo volume: a pergunta é onde está o
    problema. O total vai junto porque 300 negativas em 400 menções é uma
    situação, e 300 em 3.000 é outra.
    """
    consulta = (
        select(
            Mencao.unidade_texto,
            func.count().filter(Mencao.sentimento == "neg"),
            func.count(),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            Mencao.mes == primeiro_dia(mes),
            Mencao.unidade_texto.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.unidade_texto)
        .having(func.count().filter(Mencao.sentimento == "neg") > 0)
        .order_by(
            func.count().filter(Mencao.sentimento == "neg").desc(),
            Mencao.unidade_texto.asc(),
        )
        .limit(quantos)
    )
    return [(nome, neg, total) for nome, neg, total in sessao.execute(consulta)]


def so_fontes_ligadas(calibracao: Calibracao) -> list:
    """As condições que tiram do resultado as fontes que a calibração desligou.

    DEVOLVE UMA LISTA, vazia quando não há nada desligado — e não um `not_in`
    com sentinela. O `not_in({""})` que existia aqui funcionava por acidente:
    bastava alguém cadastrar uma fonte de código vazio para ela sumir de todas
    as leituras sem que ninguém a tivesse desligado.
    """
    if not calibracao.fontes_desligadas:
        return []
    return [ScoreFonte.codigo.not_in(calibracao.fontes_desligadas)]


#: Quantos meses a janela de perpetuação olha para trás, o mês pedido incluso.
MESES_DA_PERPETUACAO = 6

#: Em quantos meses o tema precisa aparecer para ser "em perpetuação". Com dois,
#: qualquer assunto de duas semanas entraria; a lista é sobre o que NÃO passa.
MESES_PARA_PERPETUAR = 3


def temas_em_perpetuacao(
    sessao: Session, mes: date, calibracao: Calibracao, quantos: int = 6
) -> list[tuple[str, int, date, date, int, list[str]]]:
    """Os temas negativos que atravessam meses — o risco que não passa.

    A DIFERENÇA ENTRE ISTO E "TEMAS DA LENTE" é o tempo. Aquela lista responde
    "do que falaram neste mês"; esta responde "o que já vinha e continua". Um
    assunto que explode e some é ruído; o que reaparece cinco meses seguidos é
    posição consolidada, e é com esse que a comunicação precisa lidar.

    Conta MESES DISTINTOS, e não menções: um tema com 900 negativas num mês só
    é um episódio, e um com 40 por mês durante cinco é uma narrativa.

    A CONSULTA INTEIRA OLHA SÓ PARA A NEGATIVA, e não apenas a contagem final.
    Contar meses de qualquer sentimento deixava entrar um tema com UMA negativa
    em março e menções neutras de abril a junho: quatro meses de "perpetuação"
    de um assunto que parou de incomodar no primeiro. Pelo mesmo motivo a lista
    de lentes sai daqui — dizer que o risco está na imprensa porque a imprensa
    falou bem do assunto seria o contrário do que a tela promete.
    """
    alvo = primeiro_dia(mes)
    inicio = alvo
    for _ in range(MESES_DA_PERPETUACAO - 1):
        inicio = (
            inicio.replace(year=inicio.year - 1, month=12)
            if inicio.month == 1
            else inicio.replace(month=inicio.month - 1)
        )

    rotulo = func.coalesce(Tema.nome, Mencao.tema_texto)
    negativas = func.count()
    meses_distintos = func.count(func.distinct(Mencao.mes))
    consulta = (
        select(
            rotulo.label("tema"),
            meses_distintos,
            func.min(Mencao.mes),
            func.max(Mencao.mes),
            negativas,
            func.array_agg(func.distinct(Lente.nome)),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .where(
            Mencao.sentimento == "neg",
            Mencao.mes <= alvo,
            Mencao.mes >= inicio,
            rotulo.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(rotulo)
        # SÓ O QUE ALCANÇA O MÊS PEDIDO: um tema que morreu em março não está
        # "em perpetuação" em junho — está encerrado, e listá-lo como risco
        # vivo mandaria a comunicação apagar um incêndio que já acabou.
        .having(func.max(Mencao.mes) == alvo)
        .having(meses_distintos >= MESES_PARA_PERPETUAR)
        .order_by(meses_distintos.desc(), negativas.desc(), rotulo.asc())
        .limit(quantos)
    )
    return [
        (tema, meses, primeiro, ultimo, neg, sorted(lentes))
        for tema, meses, primeiro, ultimo, neg, lentes in sessao.execute(consulta)
    ]
