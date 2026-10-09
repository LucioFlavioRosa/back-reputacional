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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import BlocoTema, Clima, MacroTema, Tema
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
from app.dominio.score import (
    REGUA_DE_CONTAGEM,
    REGUAS_DE_TIER,
    Calibracao,
    Contagem,
    FiltroDeMencoes,
    Indice,
    LenteMedida,
    SomasDaFonte,
    calcular_indice,
    medir_lente,
    ns,
    peso_do_cargo,
    peso_do_engajamento,
    ponderar,
    regua_da_lente,
)
from app.dominio.tema_do_mes import PONTOS_POR_NS, PesosDoTema

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
            *so_interacoes_visiveis(),
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


def medir_uma_lente(
    sessao: Session,
    lente: Lente,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> LenteMedida:
    """O score de uma lente sozinha — para o dossiê com filtro ativo.

    `medir_lentes` mede as cinco de uma vez por cima de `score_mes_fonte`, e é
    o caminho certo sem filtro. Mas um filtro de veículo/atributo/tema só
    existe por `somas_da_lente_filtradas`, que já é por lente — reaproveitar o
    lote das cinco aqui custaria ler as outras quatro à toa. A ESTIMATIVA FICA
    DE FORA DE PROPÓSITO: `score_estimativa` é um NS do resumo semestral, sem
    nenhuma das quatro dimensões do filtro — cair nela com um filtro ativo
    responderia a pergunta errada com a aparência de ter respondido a certa.
    """
    fontes_cadastradas = tuple(
        sessao.scalars(select(ScoreFonte.codigo).where(ScoreFonte.lente_id == lente.id))
    )
    somas = _somas_da_lente(sessao, lente.id, mes, filtro)
    return medir_lente(
        codigo=lente.codigo,
        nome=lente.nome,
        peso=calibracao.peso(lente.codigo, lente.peso_padrao),
        somas_por_fonte=somas,
        calibracao=calibracao,
        estimativa=None,
        fontes_cadastradas=fontes_cadastradas,
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


def condicoes_do_filtro(filtro: FiltroDeMencoes | None) -> list:
    """As condições de um `FiltroDeMencoes`, prontas para um `.where(...)` em `Mencao`.

    Vazia quando não há filtro — mesma convenção de `so_fontes_ligadas`: lista,
    não sentinela, para não depender de um valor mágico "sem filtro".
    """
    if filtro is None:
        return []
    #: UMA CONDIÇÃO POR DIMENSÃO PREENCHIDA, e todas no mesmo `where`: é o `and`
    #: que faz os recortes se EMPILHAREM (nível 3 do pacote), em vez de o último
    #: escolhido vencer os anteriores.
    de_cada = (
        (Mencao.tier, filtro.tier),
        (Mencao.veiculo, filtro.veiculo),
        (Mencao.atributo, filtro.atributo),
        # -- as do padrão Aegea (0055) --
        (Mencao.perfil_autor, filtro.perfil_autor),
        (Mencao.uf, filtro.uf),
        (Mencao.subtema, filtro.subtema),
        (Mencao.autor, filtro.autor),
        (Mencao.unidade_texto, filtro.empresa),
    )
    condicoes = [coluna == valor for coluna, valor in de_cada if valor]
    if filtro.tema_texto:
        #: O TEMA CASA POR DUAS COLUNAS, e isto foi achado de revisão. O rótulo
        #: que a tela mostra é `coalesce(Tema.nome, Mencao.tema_texto)` — o nome
        #: do dicionário do CRM vence a grafia do fornecedor —, e o filtro
        #: comparava só o texto cru. Com `tema_id` preenchido e grafia diferente
        #: ("SAN BASICO" para o tema "Saneamento básico"), clicar no rótulo
        #: mandava ao servidor um valor que o dado não tem: nenhuma menção
        #: encontrada, numa barra que acabou de mostrar três.
        #:
        #: SUBCONSULTA, E NÃO JUNÇÃO: `condicoes_do_filtro` entra em nove
        #: consultas diferentes, e algumas já juntam `Tema` por conta própria —
        #: acrescentar uma junção aqui mudaria o `from` delas por baixo.
        condicoes.append(
            or_(
                Mencao.tema_texto == filtro.tema_texto,
                Mencao.tema_id.in_(
                    select(Tema.id).where(Tema.nome == filtro.tema_texto).scalar_subquery()
                ),
            )
        )
    #: OS TRÊS NÍVEIS DA TAXONOMIA, cada um um `and` a mais — escolher o pilar e,
    #: dentro dele, um tema estratégico estreita, como no CRM. SUBCONSULTA pelo
    #: mesmo motivo do tema acima: este recorte entra em nove consultas.
    if filtro.tema_n3:
        condicoes.append(
            Mencao.tema_id.in_(select(Tema.id).where(Tema.nome == filtro.tema_n3).scalar_subquery())
        )
    if filtro.tema_n2:
        condicoes.append(
            Mencao.tema_id.in_(
                select(Tema.id)
                .join(MacroTema, MacroTema.id == Tema.macro_tema_id)
                .where(MacroTema.nome == filtro.tema_n2)
                .scalar_subquery()
            )
        )
    if filtro.tema_n1:
        condicoes.append(
            Mencao.tema_id.in_(
                select(Tema.id)
                .join(MacroTema, MacroTema.id == Tema.macro_tema_id)
                .join(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
                .where(BlocoTema.nome == filtro.tema_n1)
                .scalar_subquery()
            )
        )
    return condicoes


def somas_da_lente_filtradas(
    sessao: Session, lente_id: int, mes: date, filtro: FiltroDeMencoes
) -> dict[str, list[SomasDaFonte]]:
    """Como `_somas_da_lente`, mas agregando `mencao` ao vivo.

    `score_mes_fonte` (o que a ingestão grava) só tem grão de (fonte, mês,
    sentimento, tier) — sem dimensão de veículo, atributo ou tema, não tem
    como responder a um filtro desses. Este caminho lê `mencao` linha a linha
    e soma na mão, com as MESMAS fórmulas da ingestão (`peso_do_engajamento`,
    `peso_do_cargo`) — para a nota filtrada nunca divergir da fórmula de
    sempre, só do CONJUNTO de menções que entra nela.

    Só a fonte interna (CRM) fica de fora: ela não vem de `mencao`, e nenhum
    dos quatro campos do filtro existe numa interação — ver `_somas_do_crm`.
    """
    consulta = (
        select(
            ScoreFonte.codigo,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.engajamento,
            Mencao.cargo,
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *condicoes_do_filtro(filtro),
        )
    )
    linhas_por_grupo: dict[tuple[str, str, str], list[tuple[int | None, str | None]]] = {}
    for fonte_codigo, sentimento, tier, engajamento, cargo in sessao.execute(consulta):
        chave = (fonte_codigo, sentimento, tier or "")
        linhas_por_grupo.setdefault(chave, []).append((engajamento, cargo))

    por_fonte: dict[str, list[SomasDaFonte]] = {}
    for (fonte_codigo, sentimento, tier), linhas in linhas_por_grupo.items():
        por_fonte.setdefault(fonte_codigo, []).append(
            SomasDaFonte(
                fonte=fonte_codigo,
                sentimento=sentimento,
                tier=tier,
                mencoes=len(linhas),
                soma_log=sum(peso_do_engajamento(engajamento) for engajamento, _ in linhas),
                soma_engajamento=sum(engajamento or 0 for engajamento, _ in linhas),
                soma_cargo=sum(peso_do_cargo(cargo) for _, cargo in linhas),
            )
        )
    return por_fonte


def _somas_da_lente(
    sessao: Session, lente_id: int, mes: date, filtro: FiltroDeMencoes | None = None
) -> dict[str, list[SomasDaFonte]]:
    """As somas de uma lente, por fonte — incluindo a interna.

    `filtro` ativo desvia para `somas_da_lente_filtradas`, que não passa pela
    fonte interna (sem filtro, o comportamento de sempre continua idêntico).
    """
    if filtro is not None and filtro.ativo:
        return somas_da_lente_filtradas(sessao, lente_id, mes, filtro)
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
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    regua: str | None = None,
) -> Contagem:
    """Os três números da fórmula, já ponderados — o que a barra desenha.

    SOMA DAS FONTES LIGADAS. Hoje é também como o SCORE sai (um denominador só,
    ver `medir_lente`); antes a nota era a média dos NS das fontes e esta soma
    existia porque a barra mostra VOLUME, e volume se soma. As duas contas
    convergiram, e é bom que tenham: a barra e o número agora dizem a mesma coisa.

    A RÉGUA É A DA LENTE, e este era um achado de revisão — eu havia passado a
    nota para a régua do conjunto e deixado esta chamada com a régua por fonte.
    Numa lente com duas fontes, uma com engajamento e outra sem, a barra mediria
    uma em curtidas e a outra em menções: a composição exibida no detalhe
    discordaria da nota exibida ao lado dela, sem nada explicando a diferença.
    """
    ligadas = {
        fonte: linhas
        for fonte, linhas in _somas_da_lente(sessao, lente_id, mes, filtro).items()
        if calibracao.ligada(fonte)
    }
    #: A RÉGUA DE FORA VENCE, e existe por causa do impacto de um recorte: lá o
    #: numerador é do recorte e o denominador é do MÊS, e os dois têm de estar na
    #: mesma unidade. Deixar cada chamada achar a sua régua faria um recorte
    #: pequeno (sem engajamento no dado) ser dividido por um mês medido em
    #: curtidas — curtida sobre menção, um número sem significado nenhum.
    regua = regua or regua_da_lente(ligadas, calibracao.regua_engajamento)
    total = Contagem()
    for linhas in ligadas.values():
        total = total + ponderar(linhas, calibracao, regua)
    return total


def denominador_do_mes(
    sessao: Session, lente_id: int, mes: date, calibracao: Calibracao
) -> tuple[str, float]:
    """A régua e o total ponderado do mês — o denominador do impacto, de uma
    leitura só.

    ACHADO DE REVISÃO (desempenho). Antes eram duas funções: uma lia as somas do
    mês para decidir a régua, a outra as lia DE NOVO para somar o total. E o
    impacto é chamado uma vez por mês do período no histórico — oito meses,
    dezesseis leituras do mesmo agregado, metade delas para redescobrir a mesma
    régua. O endpoint levava 472 ms no mês mais cheio.

    AS DUAS COISAS SAEM DA MESMA LEITURA porque dependem do mesmo dado: a régua é
    o que todas as fontes ligadas cumprem, e o total é a soma delas sob essa
    régua.
    """
    ligadas = {
        fonte: linhas
        for fonte, linhas in _somas_da_lente(sessao, lente_id, mes, None).items()
        if calibracao.ligada(fonte)
    }
    regua = regua_da_lente(ligadas, calibracao.regua_engajamento)
    total = Contagem()
    for linhas in ligadas.values():
        total = total + ponderar(linhas, calibracao, regua)
    return regua, total.total


def impacto_do_recorte(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    denominador: tuple[str, float] | None = None,
) -> float:
    """Quantos pontos este pedaço do mês tira (ou põe) na nota da lente.

    `denominador` PRONTO evita medir o mês duas vezes quando quem chama já o tem —
    é o caso do dossiê, que pede o impacto do mês alvo e depois o histórico.

    A REGRA CENTRAL DO PACOTE, na letra:

        impacto(S) = 50 × Σ(sinal × peso de S) ÷ Σ(peso de TODOS os itens do mês)

    O DENOMINADOR É O DO MÊS, e é tudo o que importa aqui: é o que faz a soma dos
    impactos de todos os valores de uma dimensão fechar em `nota − 50`, em
    qualquer nível. Um denominador local daria a cada pedaço o seu próprio 100%
    — cada barra pareceria enorme, nenhuma somaria o todo, e a tela estaria
    mostrando pedaços que não compõem a coisa que dizem compor.

    A MESMA RÉGUA NOS DOIS LADOS, por `denominador_do_mes`: um recorte cujas fontes não
    mandam engajamento seria medido em menções e dividido por um mês medido em
    curtidas.

    ZERO QUANDO O MÊS NÃO TEM BASE, e não divisão por zero: sem denominador não
    há pergunta a responder.
    """
    regua, total_do_mes = denominador or denominador_do_mes(sessao, lente_id, mes, calibracao)
    if not total_do_mes:
        return 0.0
    do_recorte = composicao_da_lente(sessao, lente_id, mes, calibracao, filtro, regua)
    return PONTOS_POR_NS * (do_recorte.positivo - do_recorte.negativo) / total_do_mes


def fontes_da_lente(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
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
    somas = _somas_da_lente(sessao, lente_id, mes, filtro)
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
    mesmo tema. Mas o fornecedor manda o tema no vocabulário DELE, e enquanto
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
        # ORDENADO PELO QUE TOMA PARTIDO, e não pelo volume. Os temas mais
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
            *so_interacoes_visiveis(),
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
        .where(
            InteracaoRegistro.clima_id.is_not(None),
            *so_interacoes_visiveis(),
        )
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


def pesos_por_tema(
    sessao: Session, meses: Sequence[date], calibracao: Calibracao
) -> dict[date, list[PesosDoTema]]:
    """Os temas de cada mês, já ponderados pelas MESMAS réguas do índice.

    POR QUE NÃO BASTA CONTAR MENÇÕES. A primeira versão desta consulta contava
    positivas e negativas por tema, e a decomposição errava por 4,3 pontos
    num mês real: a lente de imprensa pondera cada matéria pelo tier do veículo
    (10, 5 ou 1 na régua da Aegea) e as de rede aplicam a régua de engajamento.
    Um tema de blog local contado como uma unidade parecia pesar o mesmo que
    uma capa do Valor.

    AS FÓRMULAS NÃO SE REPETEM EM SQL. O agrupamento desce até `tier`, `cargo` e
    `engajamento`, e quem multiplica é `peso_do_tier` e a medida de engajamento
    de `dominio/score` — as mesmas funções que `ponderar` usa. Escrever
    `1 + log10(1 + engajamento)` numa expressão SQL criaria um segundo lugar
    para a mesma regra, e dois lugares para uma regra é como eles divergem.

    O GRÃO DESCE ATÉ A FONTE porque é nela que o NS se forma: a lente é a média
    simples dos NS das fontes dela, e juntar tudo num denominador só dá outro
    número.
    """
    rotulo = func.coalesce(Tema.nome, Mencao.tema_texto)
    consulta = (
        select(
            Mencao.mes,
            Lente.codigo,
            ScoreFonte.codigo,
            rotulo.label("tema"),
            Mencao.sentimento,
            Mencao.tier,
            Mencao.cargo,
            Mencao.engajamento,
            func.count(),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .where(Mencao.mes.in_(list(meses)), *so_fontes_ligadas(calibracao))
        .group_by(
            Mencao.mes,
            Lente.codigo,
            ScoreFonte.codigo,
            rotulo,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.cargo,
            Mencao.engajamento,
        )
    )

    pesos_de_tier = REGUAS_DE_TIER[calibracao.regua_tier]

    def medida(regua: str, cargo: str | None, engajamento: int | None, quantas: int) -> float:
        """O que cada uma destas menções soma, pela régua dada."""
        if regua == "log":
            return peso_do_engajamento(engajamento) * quantas
        if regua == "bruto":
            return (engajamento or 0) * quantas
        if regua == "cargo":
            return peso_do_cargo(cargo) * quantas
        return float(quantas)

    linhas = list(sessao.execute(consulta))

    # A MESMA RÉGUA QUE A LENTE USA, E ELA É DA LENTE. `regua_da_lente` decide,
    # lá no domínio, que basta UMA fonte sem o dado pedido para a lente inteira
    # ser contada por menções — e esta conta TEM de decidir igual, ou ela para de
    # fechar com o número que explica. Não é a mesma chamada porque não é o mesmo
    # dado de entrada: a lente soma `score_mes_fonte`, já agregado, e aqui se lê a
    # menção crua, que é o que permite abrir por tema. A regra é uma; a
    # matéria-prima, duas.
    #
    # ERA POR FONTE, e deixou de ser quando a nota passou a ter um denominador
    # só: a fonte sem engajamento seria medida em menções e a outra em curtidas,
    # dentro da mesma razão.
    medido_por_fonte: dict[tuple[date, str], float] = {}
    fontes_da_lente: dict[tuple[date, str], set[str]] = {}
    for mes, lente, fonte, _tema, _sent, tier, cargo, engajamento, quantas in linhas:
        peso = pesos_de_tier.get(tier, 1.0) if tier else 1.0
        medido_por_fonte[(mes, fonte)] = medido_por_fonte.get((mes, fonte), 0.0) + (
            peso * medida(calibracao.regua_engajamento, cargo, engajamento, quantas)
        )
        fontes_da_lente.setdefault((mes, lente), set()).add(fonte)

    regua_de: dict[tuple[date, str], str] = {}
    for (mes, lente), fontes in fontes_da_lente.items():
        cumprem = all(medido_por_fonte.get((mes, fonte)) for fonte in fontes)
        regua_de[(mes, lente)] = (
            calibracao.regua_engajamento if cumprem else REGUA_DE_CONTAGEM
        )

    # O DENOMINADOR É A LENTE INTEIRA — todas as fontes, inclusive as menções sem
    # tema: elas entraram no NS, e tirá-las faria as contribuições somarem mais do
    # que a lente de fato pôs.
    total_da_lente: dict[tuple[date, str], float] = {}
    for mes, lente, _fonte, _tema, _sent, tier, cargo, engajamento, quantas in linhas:
        peso = pesos_de_tier.get(tier, 1.0) if tier else 1.0
        total_da_lente[(mes, lente)] = total_da_lente.get((mes, lente), 0.0) + (
            peso * medida(regua_de[(mes, lente)], cargo, engajamento, quantas)
        )

    # (mês, lente, fonte, tema) -> [pos ponderado, neg ponderado, pos, neg]
    por_tema: dict[tuple[date, str, str, str], list[float]] = {}
    for mes, lente, fonte, tema, sentimento, tier, cargo, engajamento, quantas in linhas:
        if tema is None or sentimento not in ("pos", "neg"):
            continue
        peso = pesos_de_tier.get(tier, 1.0) if tier else 1.0
        valor = peso * medida(regua_de[(mes, lente)], cargo, engajamento, quantas)
        atual = por_tema.setdefault((mes, lente, fonte, tema), [0.0, 0.0, 0.0, 0.0])
        if sentimento == "pos":
            atual[0] += valor
            atual[2] += quantas
        else:
            atual[1] += valor
            atual[3] += quantas

    por_mes: dict[date, list[PesosDoTema]] = {}
    for (mes, lente, fonte, tema), (pos, neg, cruas_pos, cruas_neg) in por_tema.items():
        por_mes.setdefault(mes, []).append(
            PesosDoTema(
                lente=lente,
                fonte=fonte,
                tema=tema,
                positivas=pos,
                negativas=neg,
                total_da_lente=total_da_lente.get((mes, lente), 0.0),
                mencoes_positivas=int(cruas_pos),
                mencoes_negativas=int(cruas_neg),
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


def so_interacoes_visiveis() -> list:
    """As interações que o Score pode contar.

    UMA REGRA, SEIS CONSULTAS. O Score lê `interacao` em seis lugares — a lente
    institucional, o seletor de mês, o mês em que a tela abre e três painéis de
    dossiê — e cada um escrevia o próprio filtro. Cinco pegavam o arquivamento,
    nenhum pegava `visivel`, e o sexto (`meses_com_dado`) não pegava nem o
    arquivamento: um mês cujas agendas foram todas arquivadas continuava no
    seletor e chegava à tela como ponto sem número, que é exatamente o que o
    docstring dele diz existir para evitar.

    `visivel = false` É O REGISTRO QUE ALGUÉM TIROU DA VISTA, de propósito, e
    `filtros_sql.condicoes` o exclui de toda leitura do CRM desde sempre. Por
    aqui ele continuava movendo o índice da companhia — e devolvendo o nome da
    instituição dele no painel da institucional, que é a informação que o CRM
    guarda com mais cuidado.

    NÃO É O MESMO QUE ARQUIVAR, e os dois entram juntos porque as duas respostas
    são "não leia": o arquivado saiu do ciclo de vida, o não visível continua nele
    e foi retirado da vista. Uma leitura que aplica um e não o outro está errada
    das duas formas.
    """
    return [
        InteracaoRegistro.arquivado_em.is_(None),
        InteracaoRegistro.visivel.is_(True),
    ]


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
#: qualquer tema de duas semanas entraria; a lista é sobre o que NÃO passa.
MESES_PARA_PERPETUAR = 3


def temas_em_perpetuacao(
    sessao: Session, mes: date, calibracao: Calibracao, quantos: int = 6
) -> list[tuple[str, int, date, date, int, list[str]]]:
    """Os temas negativos que atravessam meses — o risco que não passa.

    A DIFERENÇA ENTRE ISTO E "TEMAS DA LENTE" é o tempo. Aquela lista responde
    "do que falaram neste mês"; esta responde "o que já vinha e continua". Um
    tema que explode e some é ruído; o que reaparece cinco meses seguidos é
    posição consolidada, e é com esse que a comunicação precisa lidar.

    Conta MESES DISTINTOS, e não menções: um tema com 900 negativas num mês só
    é um episódio, e um com 40 por mês durante cinco é uma narrativa.

    A CONSULTA INTEIRA OLHA SÓ PARA A NEGATIVA, e não apenas a contagem final.
    Contar meses de qualquer sentimento deixava entrar um tema com UMA negativa
    em março e menções neutras de abril a junho: quatro meses de "perpetuação"
    de um tema que parou de incomodar no primeiro. Pelo mesmo motivo a lista
    de lentes sai daqui — dizer que o risco está na imprensa porque a imprensa
    falou bem do tema seria o contrário do que a tela promete.
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
