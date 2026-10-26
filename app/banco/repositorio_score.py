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
from sqlalchemy import case, func, null, or_, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import BlocoTema, Clima, MacroTema, Tema, UnidadeNegocio
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
from app.dominio.consulta_profundidade import GrupoDaConsulta, MencaoDaConsulta, MesDaLente
from app.dominio.ingestao_score import para_sigla, para_uf
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
    medida_da_mencao,
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

#: O ATRIBUTO SEM O PREFIXO NUMÉRICO da planilha real ("7. Prosperidade
#: Compartilhada" → "Prosperidade Compartilhada"). É por este rótulo que a aba
#: N1 agrupa, e por isso o filtro `atributo` aceita os dois: o valor cru (o mock
#: e links antigos) e o limpo (o que a aba mostra e o clique manda).
#:
#: O SEPARADOR É OBRIGATÓRIO. Com `[.)-]?`, o dígito inicial era comido sem
#: pontuação nenhuma e valor legítimo virava outro valor — "5G e cobertura" ->
#: "G e cobertura", "2024" -> "" —, e dois atributos diferentes caíam na MESMA
#: pílula da aba N1. Espaço também não serve de separador, pelo mesmo motivo:
#: `^[0-9]+(?:[.)-]\s*|\s+)` continua comendo "2024 " e "2 ".
ATRIBUTO_SEM_PREFIXO = func.regexp_replace(Mencao.atributo, r"^[0-9]+[.)-]\s*", "")

#: A CONCESSIONÁRIA COMO O CADASTRO A CHAMA, com o texto do fornecedor como
#: reserva. Exige `outerjoin(UnidadeNegocio, UnidadeNegocio.id ==
#: Mencao.unidade_negocio_id)` em quem a usa.
#:
#: É O QUE FAZ A NORMALIZAÇÃO APARECER: quem desenha a dimensão
#: "Concessionária" é o NOME, e a mesma operação chega em grafias diferentes —
#: "Corsan" e "Companhia Riograndense de Saneamento (Corsan)" eram duas barras e
#: dois valores de filtro para 16 mil menções da mesma empresa.
#:
#: `coalesce` E NÃO O NOME SECO: dezenas de milhares de menções nomeiam operação
#: que o cadastro não resolve, e elas continuam aparecendo com a palavra do
#: fornecedor — sumir do seletor é o oposto de normalizar.
#:
#: AQUI, E NÃO EM CADA LEITOR: quem agrupa por esta expressão e quem filtra por
#: `condicoes_do_filtro` têm de concordar, e duas cópias divergem.
CONCESSIONARIA = func.coalesce(UnidadeNegocio.nome, Mencao.unidade_texto)

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
            # UM CLIMA NOVO NÃO PODE SUMIR EM SILÊNCIO: `clima` é dicionário
            # fechado, e chegar aqui significa que alguém o abriu — a lente
            # institucional passaria a ignorar as interações desse clima,
            # devolvendo um número menor e plausível. Não é erro fatal porque
            # derrubar o Score inteiro da companhia por uma linha de dicionário
            # seria pior que o desvio; o sinal é o log, e o teste de mapeamento
            # quebra no CI no mesmo dia em que o clima for criado.
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

    `medir_lentes` perguntava, PARA CADA MÊS, quais lentes existem, quais fontes
    cada uma tem e qual delas é interna — respostas que não mudam entre um mês e
    outro. Numa série de dez meses, 110 das 147 consultas repetiam a mesma
    pergunta, e a conta piora a cada mês ingerido.

    O CADASTRO É LIDO UMA VEZ e atravessa a série inteira. Não é cache: é o mesmo
    pedido lendo uma vez só o que não varia dentro dele, o que também elimina a
    chance de dois meses da mesma resposta enxergarem cadastros diferentes.
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
            # A FONTE INTERNA É A EXCEÇÃO, e `ativo` conta nela. O histórico de
            # uma fonte de planilha está gravado em `score_mes_fonte` e continua
            # valendo depois de aposentada; o da interna não existe — ela é
            # recontada de `interacao_registro` a cada leitura, então aposentá-la
            # só pode significar "para de contar". `lente_e_interna` e
            # `_tem_fonte_interna` precisam dizer o mesmo: divergindo, partem a
            # lente ao meio (nota de um lado, série do outro).
            tem_fonte_interna=any(
                f.interna and f.ativo for f in por_lente.get(lente.id, ())
            ),
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
    """A TERCEIRA derivação da mesma pergunta, e ela também olha `ativo`.

    `catalogo_das_lentes` e `repositorio_lentes.lente_e_interna` exigem
    `interna AND ativo`. Sem o `ativo` aqui, a nota da lente vinha das matérias
    enquanto o dossiê e a composição ainda somavam o CRM aposentado — a lente
    partida ao meio, uma camada abaixo.
    """
    return (
        sessao.scalar(
            select(func.count())
            .select_from(ScoreFonte)
            .where(
                ScoreFonte.lente_id == lente_id,
                ScoreFonte.interna.is_(True),
                ScoreFonte.ativo.is_(True),
            )
        )
        > 0
    )


def condicoes_do_filtro(filtro: FiltroDeMencoes | None) -> list:
    """As condições de um `FiltroDeMencoes`, prontas para um `.where(...)` em `Mencao`.

    Vazia quando não há filtro — mesma convenção de `so_fontes_ligadas`: lista,
    não sentinela, para não depender de um valor mágico "sem filtro".

    TRÊS REGRAS VALEM PARA TODAS AS DIMENSÕES ABAIXO:

    1. UMA CONDIÇÃO POR DIMENSÃO PREENCHIDA, todas no mesmo `where`. É o `and`
       que faz os recortes se EMPILHAREM (nível 3 do pacote), em vez de o último
       escolhido vencer os anteriores.
    2. QUEM TEM RÓTULO DERIVADO CASA PELAS DUAS FORMAS. A tela mostra
       `coalesce(cadastro, texto do fornecedor)` e soma as duas grafias na mesma
       barra; comparar só o texto cru manda ao servidor um valor que a coluna não
       tem, e o clique abre modal VAZIO sobre barra cheia. Acrescentar o disjunto
       só GANHA linha — o conjunto novo é superconjunto do antigo.
    3. SUBCONSULTA, E NÃO JUNÇÃO. Estas condições entram em nove consultas
       diferentes, algumas das quais já juntam `Tema` ou `UnidadeNegocio` por
       conta própria, e uma junção aqui mudaria o `from` delas por baixo.
    """
    if filtro is None:
        return []
    de_cada = (
        (Mencao.tier, filtro.tier),
        (Mencao.veiculo, filtro.veiculo),
        # -- as do padrão Aegea (0055) --
        (Mencao.perfil_autor, filtro.perfil_autor),
        (Mencao.subtema, filtro.subtema),
        (Mencao.autor, filtro.autor),
        (Mencao.sentimento, filtro.sentimento),
    )
    condicoes = [coluna == valor for coluna, valor in de_cada if valor]
    if filtro.uf:
        #: O ESTADO CASA PELAS TRÊS FORMAS, e aqui a assimetria é do nosso próprio
        #: modelo: `mencao.uf` guarda o NOME ("Santa Catarina" — ver `para_uf`), o
        #: mapa e a lista da Síntese executiva mostram a SIGLA, e linha gravada
        #: antes da canonização pode ter ficado com a sigla na coluna. O valor
        #: recebido entra no conjunto de todo jeito: é por ele que o que vem da
        #: barra de filtros continua casando, e que estado estrangeiro sem sigla
        #: ("Comunidade de Madrid") casa pelo texto do fornecedor.
        formas = {filtro.uf, para_uf(filtro.uf), para_sigla(filtro.uf)}
        condicoes.append(Mencao.uf.in_(sorted(forma for forma in formas if forma)))
    if filtro.empresa:
        #: A CONCESSIONÁRIA, pela regra 2 — e aqui o efeito é o maior: o rótulo
        #: passou a ser `coalesce(UnidadeNegocio.nome, Mencao.unidade_texto)`
        #: (`0099`), e a Corsan chega em duas grafias, de modo que clicar na barra
        #: devolvia 1.111 das 16.130 menções. A menção que o cadastro não resolve
        #: continua tendo o texto como único recorte, e é por isso que a primeira
        #: condição fica. Ver `tests/test_filtro_por_concessionaria.py`.
        condicoes.append(
            or_(
                Mencao.unidade_texto == filtro.empresa,
                Mencao.unidade_negocio_id.in_(
                    select(UnidadeNegocio.id)
                    .where(UnidadeNegocio.nome == filtro.empresa)
                    .scalar_subquery()
                ),
            )
        )
    if filtro.atributo:
        condicoes.append(
            or_(Mencao.atributo == filtro.atributo, ATRIBUTO_SEM_PREFIXO == filtro.atributo)
        )
    if filtro.tema_texto:
        #: O TEMA, pela regra 2: o rótulo é `coalesce(Tema.nome,
        #: Mencao.tema_texto)` — o nome do dicionário do CRM vence a grafia do
        #: fornecedor —, então "SAN BASICO" e "Saneamento básico" são a mesma
        #: barra, e comparar só o texto cru não achava nenhuma menção.
        condicoes.append(
            or_(
                Mencao.tema_texto == filtro.tema_texto,
                Mencao.tema_id.in_(
                    select(Tema.id).where(Tema.nome == filtro.tema_texto).scalar_subquery()
                ),
            )
        )
    #: OS TRÊS NÍVEIS DA TAXONOMIA, cada um um `and` a mais: escolher o pilar e,
    #: dentro dele, um tema estratégico estreita, como no CRM.
    if filtro.tema_n3:
        condicoes.append(
            Mencao.tema_id.in_(select(Tema.id).where(Tema.nome == filtro.tema_n3).scalar_subquery())
        )
    if filtro.tema_n2:
        condicoes.append(
            or_(
                #: A CHAVE DA `0098` PRIMEIRO, e a derivação por `tema_id` depois.
                Mencao.macro_tema_id.in_(
                    select(MacroTema.id)
                    .where(MacroTema.nome == filtro.tema_n2)
                    .scalar_subquery()
                ),
                Mencao.tema_id.in_(
                    select(Tema.id)
                    .join(MacroTema, MacroTema.id == Tema.macro_tema_id)
                    .where(MacroTema.nome == filtro.tema_n2)
                    .scalar_subquery()
                ),
            )
        )
    if filtro.tema_n1:
        #: O FORNECEDOR TRAZ UM NÍVEL E O CADASTRO DERIVA O RESTO (decisão do
        #: dono do produto), e a `0098` gravou o resultado em
        #: `mencao.bloco_tema_id`. É por ELE que o recorte por pilar entra, e era
        #: o que faltava para este filtro contar a verdade: medido na base local,
        #: o pilar alcançava 29.701 das 104.670 menções e passa a alcançar
        #: 102.715 — filtrar por "Eficiência Operacional e Qualidade" devolvia
        #: 12.386 de 60.114, escondendo quatro de cada cinco com a conta certa na
        #: tela.
        #:
        #: E A COLUNA NÃO DEPENDE DE REGRA DE PREFIXO. O `atributo` tem 15 grafias
        #: para 7 pilares porque metade do volume vem numerado, e há DUAS regras
        #: de recorte no repositório — a de `dominio/niveis_de_taxonomia`
        #: (separador opcional) e `ATRIBUTO_SEM_PREFIXO` (obrigatório). Comparar
        #: `bloco_tema_id` não passa por nenhuma das duas: a normalização
        #: aconteceu uma vez, na gravação.
        condicoes.append(
            or_(
                Mencao.bloco_tema_id.in_(
                    select(BlocoTema.id)
                    .where(BlocoTema.nome == filtro.tema_n1)
                    .scalar_subquery()
                ),
                Mencao.tema_texto == filtro.tema_n1,
                Mencao.tema_id.in_(
                    select(Tema.id)
                    .join(MacroTema, MacroTema.id == Tema.macro_tema_id)
                    .join(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
                    .where(BlocoTema.nome == filtro.tema_n1)
                    .scalar_subquery()
                ),
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


@dataclass(frozen=True, slots=True)
class GrupoNaJanela:
    """A identidade de um grupo da janela — um pilar (N1) ou um tema (N2).

    O `id` É A CHAVE e o `nome` é o rótulo: enquanto o nome era a chave, dois
    temas homônimos sob pilares diferentes viravam uma linha só.
    """

    id: int
    nome: str
    #: O nível de cima, como CONTEXTO: o pilar (N1) de um tema. `None` quando o
    #: grupo já é o pilar, ou quando o cadastro não resolve o pai.
    contexto: str | None


#: Os dois níveis em que a janela se agrupa.
#:
#: OS DOIS RESPONDEM PERGUNTAS DIFERENTES: o PILAR tem ~98% de cobertura na
#: Clipei e diz "a imprensa está amplamente positiva" sobre o TODO; o TEMA tem
#: sete vezes mais grupos e acha o bolsão negativo, mas só sobre o quarto que
#: está classificado. Escolher um perderia uma das perguntas, e a cobertura do
#: tema melhora conforme o fornecedor passa a mandar o N3 que o cadastro
#: reconhece.
NIVEL_DO_PILAR = "n1"
NIVEL_DO_TEMA = "n2"
#: O SUBTEMA (N3): a aba Bonds e reputação lê os quadros neste nível.
NIVEL_DO_SUBTEMA = "n3"
NIVEIS_DA_JANELA = (NIVEL_DO_PILAR, NIVEL_DO_TEMA, NIVEL_DO_SUBTEMA)


def coluna_da_mencao_no_nivel(nivel: str):
    """A coluna de `mencao` que diz o grupo no nível pedido.

    UM LUGAR SÓ para o quadro e o modal dos registros: se os dois escolhessem a
    coluna cada um do seu jeito, a lista do modal deixaria de ser a da linha.
    """
    if nivel == NIVEL_DO_SUBTEMA:
        return Mencao.tema_id
    if nivel == NIVEL_DO_TEMA:
        return Mencao.macro_tema_id
    return Mencao.bloco_tema_id


@dataclass(frozen=True, slots=True)
class SomasNaJanela:
    """As somas de uma janela de dias, quebradas pelo nível pedido.

    `sem_grupo` e `sem_data` NÃO SÃO DETALHE: são as duas formas de uma menção
    ficar fora desta conta, e as duas têm de chegar à tela. A menção sem o nível
    existe e pesa no índice, mas não pertence a grupo nenhum — somá-la a um seria
    inventar vínculo. A menção sem `data` (a coluna é opcional) pertence ao mês e
    não a um dia, então nenhuma janela a alcança.

    Omitir as duas faria a soma dos impactos não fechar com o impacto do período,
    e a tela mostraria pedaços que não compõem o que dizem compor — o mesmo
    defeito que `impacto_do_recorte` descreve sobre o denominador local.
    """

    #: Pelo `id` do cadastro, E NÃO POR NOME: `macro_tema.nome` não é único no
    #: schema (só `codigo` é), e agrupar por nome fundiria dois homônimos de
    #: pilares diferentes numa linha só, somando os impactos e exibindo o pai de
    #: um deles.
    por_grupo: dict[int, dict[str, list[SomasDaFonte]]]
    #: Quem é cada grupo — o nome é rótulo, não chave.
    grupos: dict[int, GrupoNaJanela]
    #: As menções da janela que não têm o nível pedido.
    sem_grupo: int
    #: As menções SEM DATA de TODOS os meses que a janela atravessa: numa janela
    #: que cruza a virada, as sem data do mês anterior também ficam fora dela.
    sem_data: int


def meses_da_janela(de: date, ate: date) -> list[date]:
    """Os primeiros dias de TODOS os meses que a janela atravessa.

    TODOS, E NÃO AS DUAS PONTAS: numa janela de 20/02 a 20/05 as pontas são
    fevereiro e maio, e março e abril inteiros ficariam fora — o impacto sairia
    menor sem nada dizer que faltou metade da janela. A rota aceita `dias` até 90.

    A COLUNA `mes` ENTRA NA CONSULTA PELO ÍNDICE, e é por isso que esta lista
    existe em vez de só comparar `data`: `mencao_por_mes` cobre `mes`, e `data`
    não tem índice nenhum.
    """
    meses = []
    atual = primeiro_dia(de)
    fim = primeiro_dia(ate)
    while atual <= fim:
        meses.append(atual)
        atual = date(atual.year + (atual.month == 12), (atual.month % 12) + 1, 1)
    return meses


def somas_por_nivel_na_janela(
    sessao: Session,
    lente_id: int,
    de: date,
    ate: date,
    nivel: str = NIVEL_DO_TEMA,
    tier: str | None = None,
) -> SomasNaJanela:
    """As somas da lente entre dois DIAS, agrupadas pelo nível pedido.

    OS TRÊS NÍVEIS RESPONDEM PERGUNTAS DIFERENTES — ver `NIVEIS_DA_JANELA`: o
    pilar dá cobertura, o tema dá profundidade.

    O NÍVEL DE CIMA VAI COMO CONTEXTO quando o grupo é o tema: quarenta e um
    nomes sem o pilar a que pertencem dão uma lista granular e menos legível. No
    pilar não há contexto, porque ele já é o topo da árvore.

    MESMO MOLDE DE `somas_da_lente_filtradas`: `score_mes_fonte` só tem grão de
    (fonte, mês, sentimento, tier) e não responde por dimensão nenhuma. Aqui há
    um motivo a mais — ele também não tem grão de DIA, então uma janela de quinze
    dias não sai dele.

    AS FÓRMULAS SÃO AS DA INGESTÃO (`peso_do_engajamento`, `peso_do_cargo`) e a
    ponderação é `ponderar`, do domínio. Reimplementar o peso aqui faria esta
    tela discordar da nota que a tela do Score mostra ao lado, e a divergência
    apareceria como "o impacto não fecha".

    O FILTRO POR `mes` ENTRA JUNTO COM O DE `data`, e não é redundância: os dois
    índices são `(mes, …)` e `data` não tem índice. Sem a coluna indexada na
    cláusula, a janela varre a tabela inteira.

    O GRUPO INATIVO ENTRA: nenhuma leitura do índice filtra `ativo`, porque a
    menção existe e pesou na nota, e esconder o tema desativado faria a soma dos
    pedaços não fechar com o período.

    A FONTE INTERNA (CRM) FICA DE FORA, como em `somas_da_lente_filtradas`: ela
    não vem de `mencao` e não tem dia nenhum.
    """
    if nivel not in NIVEIS_DA_JANELA:
        raise ValueError(f"nível desconhecido: {nivel!r}")

    meses = meses_da_janela(de, ate)
    no_tema = nivel == NIVEL_DO_TEMA
    no_subtema = nivel == NIVEL_DO_SUBTEMA
    #: O CONTEXTO É O PAI: o pilar do tema, o tema do subtema. No pilar não há
    #: contexto, porque ele já é o topo da árvore — e `null()` mantém a forma da
    #: linha igual nos três casos, em vez de consultas quase iguais que divergem
    #: na primeira mudança.
    coluna_do_grupo = Tema if no_subtema else MacroTema if no_tema else BlocoTema
    coluna_da_mencao = coluna_da_mencao_no_nivel(nivel)
    contexto = MacroTema.nome if no_subtema else BlocoTema.nome if no_tema else null()

    consulta = (
        select(
            coluna_do_grupo.id,
            coluna_do_grupo.nome,
            contexto,
            ScoreFonte.codigo,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.engajamento,
            Mencao.cargo,
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(coluna_do_grupo, coluna_do_grupo.id == coluna_da_mencao)
        .where(
            ScoreFonte.lente_id == lente_id,
            #: A MESMA CONDIÇÃO DO MODAL: o quadro e a lista que ele abre têm de
            #: contar o mesmo conjunto, e a fonte interna aposentada saiu do
            #: índice (`0112`). A DE PLANILHA APOSENTADA FICA, pelo mesmo motivo
            #: de ficar no modal: ali `ativo = false` é "parou de receber
            #: importação", e o histórico continua pesando na nota —
            #: `denominador_do_mes` filtra `calibracao.ligada`, não `ativo`.
            or_(ScoreFonte.interna.is_(False), ScoreFonte.ativo.is_(True)),
            Mencao.mes.in_(meses),
            Mencao.data.is_not(None),
            Mencao.data >= de,
            Mencao.data <= ate,
        )
    )
    if no_tema:
        #: O PAI VEM DO TEMA, e não de `Mencao.bloco_tema_id`: o pai do tema é o
        #: que dá contexto à linha, e a coluna da menção pode estar preenchida
        #: por uma resolução que parou no pilar — aí ela fala de outro nível.
        consulta = consulta.outerjoin(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
    if tier:
        #: O TIER DO QUADRO recorta o NUMERADOR; o denominador continua o do mês
        #: inteiro, e é o que faz o número seguir em pontos do índice — "quanto as
        #: matérias Tier 1 moveram a nota".
        consulta = consulta.where(Mencao.tier == tier)
    if no_subtema:
        #: O MESMO NO SUBTEMA: o tema estratégico vem do cadastro do subtema.
        consulta = consulta.outerjoin(MacroTema, MacroTema.id == Tema.macro_tema_id)

    sem_grupo = 0
    grupos: dict[int, GrupoNaJanela] = {}
    agrupadas: dict[int, dict[tuple[str, str, str], list[tuple[int | None, str | None]]]] = {}
    for (
        id_grupo,
        nome_grupo,
        nome_do_contexto,
        fonte_codigo,
        sentimento,
        tier,
        engajamento,
        cargo,
    ) in sessao.execute(consulta):
        if id_grupo is None:
            #: SEM O NÍVEL É CASO VOLUMOSO NO TEMA, e não exceção: o resolvedor
            #: da Clipei pelo `atributo` devolve só o pilar, e dezenas de milhares
            #: de menções ficam nesse estado. Elas pesam na nota e não pertencem a
            #: grupo nenhum — contar é o que impede o quadro de parecer o todo. No
            #: pilar o número é pequeno, e o contraste entre os dois é o que a
            #: chave serve para mostrar.
            sem_grupo += 1
            continue
        grupos.setdefault(
            id_grupo, GrupoNaJanela(id=id_grupo, nome=nome_grupo, contexto=nome_do_contexto)
        )
        chave = (fonte_codigo, sentimento, tier or "")
        agrupadas.setdefault(id_grupo, {}).setdefault(chave, []).append((engajamento, cargo))

    por_grupo: dict[int, dict[str, list[SomasDaFonte]]] = {}
    for id_do_grupo, por_chave in agrupadas.items():
        por_fonte: dict[str, list[SomasDaFonte]] = {}
        for (fonte_codigo, sentimento, tier), linhas in por_chave.items():
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
        por_grupo[id_do_grupo] = por_fonte

    #: AS MENÇÕES SEM DIA, em TODOS os meses da janela: elas pertencem ao mês e
    #: não a um dia, então janela nenhuma as alcança, e uma janela que atravessa
    #: a virada tem dois meses de onde elas podem vir.
    sem_data = (
        sessao.execute(
            select(func.count())
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .where(
                ScoreFonte.lente_id == lente_id,
                Mencao.mes.in_(meses),
                Mencao.data.is_(None),
                *([Mencao.tier == tier] if tier else []),
            )
        ).scalar()
        or 0
    )
    return SomasNaJanela(
        por_grupo=por_grupo, grupos=grupos, sem_grupo=sem_grupo, sem_data=sem_data
    )


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

    SOMA DAS FONTES LIGADAS, que é também como o SCORE sai (um denominador só,
    ver `medir_lente`): a barra mostra VOLUME, e volume se soma.

    A RÉGUA É A DA LENTE, e não a de cada fonte. Numa lente com duas fontes, uma
    com engajamento e outra sem, a régua por fonte mediria uma em curtidas e a
    outra em menções: a composição exibida no detalhe discordaria da nota exibida
    ao lado dela.
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

    AS DUAS COISAS SAEM DA MESMA LEITURA porque dependem do mesmo dado: a régua é
    o que todas as fontes ligadas cumprem, e o total é a soma delas sob essa
    régua. Separadas, eram duas leituras do mesmo agregado por mês — e o impacto
    é chamado uma vez por mês do período, o que levava o endpoint a 472 ms no mês
    mais cheio.
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

    O DENOMINADOR É O DO MÊS, e é o que faz a soma dos impactos de todos os
    valores de uma dimensão fechar em `nota − 50`, em qualquer nível. Um
    denominador local daria a cada pedaço o seu próprio 100%: cada barra
    pareceria enorme, nenhuma somaria o todo, e a tela mostraria pedaços que não
    compõem a coisa que dizem compor.

    A MESMA RÉGUA NOS DOIS LADOS, por `denominador_do_mes`: um recorte cujas
    fontes não mandam engajamento seria medido em menções e dividido por um mês
    medido em curtidas.

    ZERO QUANDO O MÊS NÃO TEM BASE, e não divisão por zero.
    """
    regua, total_do_mes = denominador or denominador_do_mes(sessao, lente_id, mes, calibracao)
    if not total_do_mes:
        return 0.0
    do_recorte = composicao_da_lente(sessao, lente_id, mes, calibracao, filtro, regua)
    return PONTOS_POR_NS * (do_recorte.positivo - do_recorte.negativo) / total_do_mes


def meses_da_lente(
    sessao: Session, lente: Lente, meses: Sequence[date], calibracao: Calibracao
) -> dict[date, MesDaLente]:
    """A nota oficial, o NS da contagem, a régua e o D de cada mês — de uma vez.

    É `denominador_do_mes` e `medir_lentes` juntos, para os seis meses da Consulta
    em profundidade em TRÊS leituras (fontes, `score_mes_fonte` e estimativas), e
    não dezoito. A conta é a mesma, pelas mesmas funções do domínio: a nota que
    sai daqui é a que a tela mostra, inclusive quando é estimada.

    SÓ PARA LENTE DE PLANILHA, e `ativo` conta na recusa — como em
    `_tem_fonte_interna` e em `lente_e_interna`. A fonte interna não passa por
    `score_mes_fonte`, então uma lente que a tenha ATIVA teria aqui a nota sem o
    CRM; mas uma fonte interna aposentada não alimenta mais nada, e recusar por
    causa dela deixava a Institucional sem consulta de profundidade.
    """
    fontes = list(sessao.scalars(select(ScoreFonte).where(ScoreFonte.lente_id == lente.id)))
    if any(fonte.interna and fonte.ativo for fonte in fontes):
        raise ValueError(f"A lente {lente.codigo!r} lê o CRM; meses_da_lente é só de planilha.")
    codigo_da_fonte = {fonte.id: fonte.codigo for fonte in fontes}
    meses = [primeiro_dia(m) for m in meses]

    por_mes: dict[date, dict[str, list[SomasDaFonte]]] = {m: {} for m in meses}
    consulta = select(
        ScoreMesFonte.mes,
        ScoreMesFonte.fonte_id,
        ScoreMesFonte.sentimento,
        ScoreMesFonte.tier,
        ScoreMesFonte.mencoes,
        ScoreMesFonte.soma_log,
        ScoreMesFonte.soma_engajamento,
        ScoreMesFonte.soma_cargo,
    ).where(ScoreMesFonte.fonte_id.in_(list(codigo_da_fonte)), ScoreMesFonte.mes.in_(meses))
    for mes, fonte_id, sentimento, tier, mencoes, log, engajamento, cargo in sessao.execute(
        consulta
    ):
        fonte = codigo_da_fonte[fonte_id]
        por_mes[mes].setdefault(fonte, []).append(
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
    estimativas = {
        mes: float(valor)
        for mes, valor in sessao.execute(
            select(ScoreEstimativa.mes, ScoreEstimativa.ns).where(
                ScoreEstimativa.lente_id == lente.id, ScoreEstimativa.mes.in_(meses)
            )
        )
    }

    saida: dict[date, MesDaLente] = {}
    for mes in meses:
        ligadas = {f: linhas for f, linhas in por_mes[mes].items() if calibracao.ligada(f)}
        regua = regua_da_lente(ligadas, calibracao.regua_engajamento)
        total = Contagem()
        for linhas in ligadas.values():
            total = total + ponderar(linhas, calibracao, regua)
        medida = medir_lente(
            codigo=lente.codigo,
            nome=lente.nome,
            peso=calibracao.peso(lente.codigo, lente.peso_padrao),
            somas_por_fonte=por_mes[mes],
            calibracao=calibracao,
            estimativa=estimativas.get(mes),
            fontes_cadastradas=tuple(codigo_da_fonte.values()),
        )
        saida[mes] = MesDaLente(
            mes=mes, regua=regua, denominador=total.total, ns=ns(total), nota=medida.score
        )
    return saida


def grupos_da_consulta(
    sessao: Session,
    lente_id: int,
    meses: Sequence[date],
    calibracao: Calibracao,
    reguas: dict[date, str],
) -> list[GrupoDaConsulta]:
    """As menções dos meses ANTERIORES ao da tela, já agrupadas no banco.

    Desses meses a Consulta só usa agregados (impacto de cada nó, volume), e ler
    as linhas cruas — 48 mil com o volume real, com título, link e autor — levava
    segundos. O GROUP BY é pelo que decide o vínculo (tema_id, tema_texto,
    subtema, atributo) e o peso (sentimento, tier, e o engajamento ou o cargo SÓ
    NO MÊS CUJA RÉGUA OS LÊ — `reguas`, de `meses_da_lente`): na régua de
    contagem eles não mudam o peso, e agrupar por eles só multiplicaria grupos.
    """
    meses = [primeiro_dia(m) for m in meses]
    if not meses:
        return []
    com_engajamento = [m for m in meses if reguas.get(m) in ("log", "bruto")]
    com_cargo = [m for m in meses if reguas.get(m) == "cargo"]
    # SEM RÓTULO NO GROUP BY: "engajamento" como alias colidiria com a coluna
    # de mesmo nome, e o Postgres resolveria o GROUP BY pela coluna crua.
    engajamento = (
        case((Mencao.mes.in_(com_engajamento), Mencao.engajamento), else_=null())
        if com_engajamento
        else null()
    )
    cargo = case((Mencao.mes.in_(com_cargo), Mencao.cargo), else_=null()) if com_cargo else null()
    chaves = (
        Mencao.mes,
        Mencao.sentimento,
        Mencao.tier,
        engajamento,
        cargo,
        Mencao.tema_id,
        Mencao.tema_texto,
        Mencao.subtema,
        Mencao.atributo,
    )
    consulta = (
        select(
            *chaves[:3],
            engajamento.label("engajamento_do_peso"),
            cargo.label("cargo_do_peso"),
            *chaves[5:],
            func.count().label("quantas"),
        )
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(meses),
            *so_fontes_ligadas(calibracao),
        )
        # O NULL constante fica fora do GROUP BY: o Postgres recusa constante
        # que não seja posição ("non-integer constant in GROUP BY").
        .group_by(
            *chaves[:3],
            *((engajamento,) if com_engajamento else ()),
            *((cargo,) if com_cargo else ()),
            *chaves[5:],
        )
    )
    return [
        GrupoDaConsulta(
            mes=linha.mes,
            sentimento=linha.sentimento,
            quantas=int(linha.quantas),
            tier=linha.tier,
            engajamento=linha.engajamento_do_peso,
            cargo=linha.cargo_do_peso,
            tema_id=linha.tema_id,
            tema_texto=linha.tema_texto,
            subtema=linha.subtema,
            atributo=linha.atributo,
        )
        for linha in sessao.execute(consulta)
    ]


def mencoes_da_consulta(
    sessao: Session, lente_id: int, mes: date, calibracao: Calibracao
) -> list[MencaoDaConsulta]:
    """As menções da lente NO MÊS DA TELA, linha a linha, numa leitura só.

    A CONSULTA EM PROFUNDIDADE NÃO CHAMA `impacto_do_recorte` POR NÓ: com 7
    pilares, dezenas de temas e subtemas, seriam centenas de idas ao banco para
    somar as mesmas linhas de jeitos diferentes. Lê-se a menção crua uma vez e a
    árvore inteira se agrega em Python (`dominio.consulta_profundidade`) —
    O(linhas), e as mesmas réguas. Só este mês precisa da linha inteira; os
    anteriores vêm de `grupos_da_consulta`.

    A CALIBRAÇÃO VALE AQUI COMO NA NOTA: fonte desligada não entra, senão a
    árvore explicaria um número do qual ela não participou.
    """
    consulta = (
        select(
            Mencao.id,
            Mencao.mes,
            Mencao.data,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.engajamento,
            Mencao.cargo,
            Mencao.tema_id,
            Mencao.tema_texto,
            Mencao.subtema,
            Mencao.atributo,
            Mencao.veiculo,
            Mencao.unidade_texto,
            #: O NOME DO CADASTRO, para o drill agrupar por ele (`0099`). O
            #: texto do fornecedor vai junto: quem agrupa é
            #: `MencaoDaConsulta.concessionaria`, que prefere este e cai
            #: naquele — o mesmo `coalesce` que as lentes fazem em SQL.
            UnidadeNegocio.nome.label("unidade_cadastrada"),
            Mencao.uf,
            Mencao.autor,
            Mencao.titulo_texto,
            Mencao.link,
            Mencao.id_fonte,
        )
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        #: `outerjoin`: a menção sem chave continua vindo, com o nome do
        #: fornecedor. Um `join` a tiraria do drill inteiro.
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *so_fontes_ligadas(calibracao),
        )
        # A ordem só estabiliza os empates (a amostra ordena em Python); com um
        # mês só, ela custa pouco.
        .order_by(Mencao.data, Mencao.id)
    )
    return [
        MencaoDaConsulta(
            id=str(linha.id),
            mes=linha.mes,
            data=linha.data,
            sentimento=linha.sentimento,
            tier=linha.tier,
            engajamento=linha.engajamento,
            cargo=linha.cargo,
            tema_id=linha.tema_id,
            tema_texto=linha.tema_texto,
            subtema=linha.subtema,
            atributo=linha.atributo,
            veiculo=linha.veiculo,
            unidade_texto=linha.unidade_texto,
            unidade_cadastrada=linha.unidade_cadastrada,
            uf=linha.uf,
            autor=linha.autor,
            titulo_texto=linha.titulo_texto,
            link=linha.link,
            id_fonte=linha.id_fonte,
        )
        for linha in sessao.execute(consulta)
    ]


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
    volta vazia, e a tela diz por quê.

    A CALIBRAÇÃO VALE AQUI TAMBÉM: desligar a Bites tira os posts dela do score
    da lente, e deixar os temas dela na aba de Drivers explicaria o número por um
    dado que não entrou nele.

    O NOME SAI DE DOIS LUGARES. `tema_id` aponta para o vocabulário do CRM, que é
    o bom — é por ele que um tema do Score e um tema de reunião são o mesmo tema.
    Mas o fornecedor manda o tema no vocabulário DELE, e enquanto ninguém casou
    as duas listas é o texto bruto que a tela tem para mostrar. Exigir a
    correspondência deixaria a aba de Drivers vazia com o banco cheio.
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
    # A fonte interna vem das interações, e não de `score_mes_fonte`, e `ativo`
    # ENTRA NA JUNÇÃO: com o CRM aposentado, um mês que só tivesse agenda
    # registrada continuava no seletor e podia virar o "mês mais completo" — a
    # tela abriria num mês em que nenhuma lente do Score foi medida. A fonte
    # interna não tem agregado gravado, então aposentá-la é apagá-la da conta.
    do_crm = (
        select(
            func.date_trunc("month", InteracaoRegistro.data_interacao)
            .cast(ColunaDeData)
            .label("mes"),
            ScoreFonte.lente_id.label("lente_id"),
        )
        .select_from(InteracaoRegistro)
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .join(
            ScoreFonte,
            (ScoreFonte.codigo == FONTE_INTERNA_DO_CRM) & ScoreFonte.ativo.is_(True),
        )
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

    É o que alimenta o seletor de mês: oferecer um mês vazio faria a tela abrir
    sem número e parecer quebrada. OFERECER UM MÊS QUE SÓ TEM AGENDA é o mesmo
    defeito ao contrário, agora que o CRM aposentado não alimenta lente nenhuma —
    com a diferença de que ninguém saberia por quê.
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

    consultas = [das_planilhas, das_estimativas]
    if _a_fonte_interna_conta(sessao):
        consultas.append(do_crm)

    meses = set()
    for consulta in consultas:
        meses.update(linha[0] for linha in sessao.execute(consulta) if linha[0])
    return sorted(meses)


def _a_fonte_interna_conta(sessao: Session) -> bool:
    """A fonte do CRM está ativa — ou seja, ainda alimenta alguma lente.

    A `0108` a aposentou. Enquanto ela estiver assim, interação registrada não
    entra em conta nenhuma do Score, e por isso também não põe mês no seletor.
    """
    return (
        sessao.scalar(
            select(func.count())
            .select_from(ScoreFonte)
            .where(
                ScoreFonte.codigo == FONTE_INTERNA_DO_CRM,
                ScoreFonte.ativo.is_(True),
            )
        )
        > 0
    )


# -- a aba de Drivers e riscos --------------------------------------------------
#
# As três leituras desta aba respondem "POR QUE o índice deu isso", e todas se
# fazem MENÇÃO A MENÇÃO: não saem de `score_mes_fonte`, que perdeu o atributo, o
# tema e a unidade ao somar.
#
# TODAS RESPEITAM A CALIBRAÇÃO. Explicar o número com o dado de uma fonte que a
# coordenação tirou do cálculo é pior do que não explicar, porque quem lê o
# gráfico não tem como saber que aquela barra não entrou na conta.
#
# E NENHUMA APLICA A RÉGUA DE TIER OU DE ENGAJAMENTO. Aqui se conta matéria e
# post, um a um: a pergunta é "sobre o que falaram e com que tom", e não "quanto
# isso pesou no índice". Ponderar faria uma matéria do Valor aparecer como dez, e
# a barra deixaria de ser contagem sem avisar.


def pesos_por_tema(
    sessao: Session, meses: Sequence[date], calibracao: Calibracao
) -> dict[date, list[PesosDoTema]]:
    """Os temas de cada mês, já ponderados pelas MESMAS réguas do índice.

    POR QUE NÃO BASTA CONTAR MENÇÕES: a decomposição errava por 4,3 pontos num
    mês real. A lente de imprensa pondera cada matéria pelo tier do veículo (10,
    5 ou 1 na régua da Aegea) e as de rede aplicam a régua de engajamento, então
    um tema de blog local contado como uma unidade parecia pesar o mesmo que uma
    capa do Valor.

    AS FÓRMULAS NÃO SE REPETEM EM SQL. O agrupamento desce até `tier`, `cargo` e
    `engajamento`, e quem multiplica é `peso_do_tier` e a medida de engajamento
    de `dominio/score` — as mesmas funções que `ponderar` usa. Escrever
    `1 + log10(1 + engajamento)` numa expressão SQL criaria um segundo lugar para
    a mesma regra.

    O GRÃO DESCE ATÉ A FONTE porque é por fonte que a RÉGUA se decide: basta uma
    sem o dado pedido para a lente inteira ser contada por menções (ver o
    comentário de `regua_de`, abaixo). O denominador, esse, é da lente inteira.
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
        """O que cada uma destas menções soma, pela régua dada — a regra mora em
        `medida_da_mencao`, a mesma que a consulta em profundidade usa."""
        return medida_da_mencao(regua, cargo, engajamento) * quantas

    linhas = list(sessao.execute(consulta))

    # A MESMA RÉGUA QUE A LENTE USA, E ELA É DA LENTE. `regua_da_lente` decide, no
    # domínio, que basta UMA fonte sem o dado pedido para a lente inteira ser
    # contada por menções — e esta conta TEM de decidir igual, ou ela para de
    # fechar com o número que explica. Não é a mesma chamada porque não é o mesmo
    # dado de entrada: a lente soma `score_mes_fonte`, já agregado, e aqui se lê a
    # menção crua, que é o que permite abrir por tema. A regra é uma; a
    # matéria-prima, duas. Por fonte, a fonte sem engajamento seria medida em
    # menções e a outra em curtidas, dentro da mesma razão.
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

    PELO NOME DO CADASTRO (`CONCESSIONARIA`), e não pela grafia do fornecedor:
    sem isso a Corsan aparece em duas barras, o que num painel chamado "onde a
    pressão se concentra" divide ao meio justamente a pressão que ele existe para
    mostrar.

    `outerjoin` E NÃO `join`: "Águas do Rio" são dois blocos e fica sem chave de
    propósito (ver `casos_de_uso/unidade_da_mencao`). Um `join` a sumiria do
    ranking, e sumir é pior que aparecer com a palavra do fornecedor.
    """
    negativas = func.count().filter(Mencao.sentimento == "neg")
    consulta = (
        select(CONCESSIONARIA, negativas, func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .where(
            Mencao.mes == primeiro_dia(mes),
            #: SOBRE A EXPRESSÃO, e não sobre `unidade_texto`: é o rótulo que a
            #: tela mostra que precisa existir. Hoje dá no mesmo — a chave só
            #: nasce de um texto —, mas amarrar a guarda ao que se exibe é o que
            #: impede a linha com chave e sem texto de sumir em silêncio.
            CONCESSIONARIA.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(CONCESSIONARIA)
        .having(negativas > 0)
        .order_by(negativas.desc(), CONCESSIONARIA.asc())
        .limit(quantos)
    )
    return [(nome, neg, total) for nome, neg, total in sessao.execute(consulta)]


def so_interacoes_visiveis() -> list:
    """As interações que o Score pode contar.

    UMA REGRA, SEIS CONSULTAS. O Score lê `interacao` em seis lugares — a lente
    institucional, o seletor de mês, o mês em que a tela abre e três painéis de
    dossiê — e cada um escrevia o próprio filtro: cinco pegavam o arquivamento,
    nenhum pegava `visivel`, e `meses_com_dado` não pegava nem o arquivamento.

    `visivel = false` É O REGISTRO QUE ALGUÉM TIROU DA VISTA, de propósito, e
    `filtros_sql.condicoes` o exclui de toda leitura do CRM. Por aqui ele
    continuava movendo o índice da companhia — e devolvendo o nome da instituição
    dele no painel da institucional, que é a informação que o CRM guarda com mais
    cuidado. NÃO É O MESMO QUE ARQUIVAR, e os dois entram juntos porque as duas
    respostas são "não leia".

    A AGENDA SENSÍVEL ENTRA NA MESMA REGRA (migration 0089), e esta é a decisão
    mais pesada do conjunto. O QUE ELA FECHA: `orgaos_do_crm` devolve NOME DE
    INSTITUIÇÃO com contagem por mês, e `temas_do_crm` nome de tema — com
    contagem 1 num mês, o par instituição-mês revela que o encontro existiu, que
    é exatamente o que a marca protege.

    SEM A BANDEIRA DE QUEM PEDE, de propósito, e aqui está a diferença de
    `filtros_sql.condicoes`: o Score é um índice DA COMPANHIA, não do leitor.
    Passá-lo por pessoa faria duas pessoas lerem notas diferentes para o mesmo
    mês e discutirem qual é a verdadeira.

    O CUSTO, E ELE É REAL: agenda restrita não move o índice nem aparece nos
    dossiês, para NINGUÉM — inclusive para quem a marcou. Uma reunião delicada é
    justamente o tipo de encontro que pesaria na reputação, e ela deixa de pesar.
    A alternativa era entregar o nome da instituição a quem não alcança a agenda.
    Se o dono do produto preferir o contrário, o lugar de mudar é este, e a
    mudança é por pessoa — com as duas notas que ela implica.
    """
    return [
        InteracaoRegistro.arquivado_em.is_(None),
        InteracaoRegistro.visivel.is_(True),
        InteracaoRegistro.sensivel.is_(False),
    ]


@dataclass(frozen=True, slots=True)
class RegistroDaJanela:
    """Uma menção do quadro da janela, como a tela a mostra."""

    id: str
    data: date
    veiculo: str | None
    titulo: str | None
    link: str | None
    sentimento: str
    tier: str | None
    #: DE QUAL LENTE VEM ESTE REGISTRO. É coluna na tela, e não enfeite: A LENTE
    #: DE UMA LINHA É DECIDIDA PELO VEÍCULO QUE PUBLICOU, então a mesma matéria
    #: publicada por dois veículos — um na lista do Mercado, outro não — aparece
    #: em duas lentes, com o mesmo título. Sem a coluna, isso parece erro.
    lente: str
    lente_nome: str


@dataclass(frozen=True, slots=True)
class RegistrosDaJanela:
    itens: tuple[RegistroDaJanela, ...]
    total: int
    pagina: int
    tamanho: int


def registros_do_grupo_na_janela(
    sessao: Session,
    lentes_id: Sequence[int],
    de: date,
    ate: date,
    grupo_id: int,
    calibracao: Calibracao,
    nivel: str = NIVEL_DO_TEMA,
    pagina: int = 1,
    tamanho: int = 50,
    tier: str | None = None,
) -> RegistrosDaJanela:
    """As menções que compõem UM grupo do quadro, paginadas.

    O RECORTE É O MESMO DE `somas_por_nivel_na_janela`, linha por linha, e isso é
    o ponto inteiro desta função. A rota da Base das lentes já lista menções por
    período e por tema, e não serve aqui, por três diferenças medidas:

    * ela casa a data por `coalesce(data, mes)`, de propósito, para a linha sem
      data continuar achável pelo mês. A janela faz o OPOSTO: exige `data` e
      conta as sem data à parte. Pela rota da Base, o modal traria de volta
      justamente as que o quadro excluiu;
    * ela não tira as fontes que a calibração desligou, e o impacto do quadro
      tira — contá-las faria o impacto de um pilar incluir o que a nota ignorou;
    * ela filtra o nível por NOME, e nome de N2 não é único no cadastro. O quadro
      agrupa por id, então clicar em "Tarifa" traria a "Tarifa" de outro pilar.

    Qualquer uma das três faz a lista discordar do número ao lado dela na mesma
    tela, e quem lê não tem como saber qual das duas está certa.

    PAGINADA, e com o total: um pilar de janela cheia passa de centena, e a tela
    precisa dizer "8 de 312" em vez de fingir que mostrou tudo.

    VÁRIAS LENTES, e cada linha diz de qual veio, pelo motivo de
    `RegistroDaJanela.lente`.

    O TOTAL É O NÚMERO DA LINHA DO QUADRO, porque o quadro soma as MESMAS lentes
    desta lista. ELES AINDA PODEM DIVERGIR num caso: a lente sem base de mês não
    entra no quadro, porque sem denominador ela não contribui em ponto do índice,
    e esta lista mostra as menções dela, que existem. O cabeçalho do modal nomeia
    os dois números quando isso acontece.
    """
    if nivel not in NIVEIS_DA_JANELA:
        raise ValueError(f"nível desconhecido: {nivel!r}")
    if not lentes_id:
        return RegistrosDaJanela(itens=(), total=0, pagina=pagina, tamanho=tamanho)

    coluna_da_mencao = coluna_da_mencao_no_nivel(nivel)
    onde = [
        ScoreFonte.lente_id.in_(list(lentes_id)),
        #: A FONTE INTERNA APOSENTADA SAI; a de planilha, NÃO. Para a INTERNA o
        #: score é recontado a cada leitura, e aposentá-la é tirá-la do índice
        #: (`0112`, as agendas fora da nota). Para fonte de PLANILHA `ativo =
        #: false` é "parou de receber importação", e o histórico continua valendo
        #: porque está gravado em `score_mes_fonte` — `denominador_do_mes`
        #: confirma, filtrando por `calibracao.ligada` e não por `ativo`. Um
        #: filtro genérico por `ativo` esconderia deste modal justamente a menção
        #: que compõe a nota.
        #:
        #: A MESMA CONDIÇÃO DE `leitura_das_lentes._nomes_das_fontes`
        #: (`fonte.ativo or not fonte.interna`), e não uma terceira forma de dizer
        #: a mesma regra.
        #:
        #: HOJE O CRM NÃO TEM LINHA EM `mencao`, porque a ingestão recusa fonte
        #: interna — mas isso é premissa operacional, não garantia do banco: um
        #: `insert` à mão ou um seed futuro a quebraria, e a consulta pode se
        #: garantir sozinha.
        or_(ScoreFonte.interna.is_(False), ScoreFonte.ativo.is_(True)),
        #: O MESMO PAR `mes`+`data` da janela: `mes` é quem tem índice, e sem
        #: ele a consulta varre a tabela inteira.
        Mencao.mes.in_(meses_da_janela(de, ate)),
        Mencao.data.is_not(None),
        Mencao.data >= de,
        Mencao.data <= ate,
        coluna_da_mencao == grupo_id,
        *so_fontes_ligadas(calibracao),
    ]
    if tier:
        #: O MESMO TIER DO QUADRO, senão a lista do modal deixaria de ser a da
        #: linha que a abriu.
        onde.append(Mencao.tier == tier)

    total = (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .where(*onde)
        )
        or 0
    )

    linhas = sessao.execute(
        select(
            Mencao.id,
            Mencao.data,
            Mencao.veiculo,
            Mencao.titulo_texto,
            Mencao.link,
            Mencao.sentimento,
            Mencao.tier,
            Lente.codigo.label("lente"),
            Lente.nome.label("lente_nome"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        #: A LENTE VEM NA MESMA CONSULTA, e não num dicionário montado depois:
        #: `mencao -> score_fonte -> lente` é o caminho que define a lente de
        #: uma menção em todo o sistema, e resolvê-lo noutro lugar abriria a
        #: chance de a coluna da tela discordar do filtro que trouxe a linha.
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .where(*onde)
        #: A MAIS NOVA PRIMEIRO, e o `id` fecha a ordem: várias matérias caem no
        #: mesmo dia, e sem o desempate a página 2 pode repetir uma linha da 1.
        .order_by(Mencao.data.desc(), Mencao.id)
        .offset((pagina - 1) * tamanho)
        .limit(tamanho)
    ).all()

    return RegistrosDaJanela(
        itens=tuple(
            RegistroDaJanela(
                id=str(linha.id),
                data=linha.data,
                veiculo=linha.veiculo,
                titulo=linha.titulo_texto,
                link=linha.link,
                sentimento=linha.sentimento,
                tier=linha.tier,
                lente=linha.lente,
                lente_nome=linha.lente_nome,
            )
            for linha in linhas
        ),
        total=total,
        pagina=pagina,
        tamanho=tamanho,
    )


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

    A DIFERENÇA ENTRE ISTO E "TEMAS DA LENTE" é o tempo: aquela lista responde "do
    que falaram neste mês", esta responde "o que já vinha e continua". Um tema que
    explode e some é ruído; o que reaparece cinco meses seguidos é posição
    consolidada.

    Conta MESES DISTINTOS, e não menções: um tema com 900 negativas num mês só é
    um episódio, e um com 40 por mês durante cinco é uma narrativa.

    A CONSULTA INTEIRA OLHA SÓ PARA A NEGATIVA, e não apenas a contagem final.
    Contar meses de qualquer sentimento deixava entrar um tema com UMA negativa em
    março e menções neutras de abril a junho: quatro meses de "perpetuação" de um
    tema que parou de incomodar no primeiro. Pelo mesmo motivo a lista de lentes
    sai daqui — dizer que o risco está na imprensa porque a imprensa falou BEM do
    tema seria o contrário do que a tela promete.
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
