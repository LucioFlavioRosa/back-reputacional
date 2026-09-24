"""De onde o dossiê de cada lente tira os números.

TRÊS PROCEDÊNCIAS, e a tela precisa saber qual é qual:

    das planilhas   a série mensal, a composição por tier, os temas, as
                    concessionárias e o teor das mensagens — tudo de `mencao`
                    e `score_mes_fonte`, que a ingestão grava
    do CRM          a lente institucional, contada das interações na hora
    do cadastro     eventos de mercado, estudo de percepção, matriz de
                    jornalistas e respostas do CM

A CALIBRAÇÃO VALE EM TUDO O QUE VEM DE MENÇÃO. Explicar o número da lente com o
dado de uma fonte que a coordenação tirou do cálculo é pior do que não
explicar: quem lê o gráfico não tem como saber que aquela barra não entrou.

E NADA AQUI APLICA A RÉGUA DE TIER OU DE ENGAJAMENTO. O dossiê conta matéria e
post, um a um — a pergunta é "sobre o que falaram e com que tom", e não "quanto
isso pesou". A única exceção é a NOTA da lente, que vem pronta de
`repositorio_score` justamente para não existir em duas versões.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import Date as ColunaDeData
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.repositorio_score import (
    SENTIMENTO_DO_CLIMA,
    primeiro_dia,
    so_fontes_ligadas,
)
from app.banco.tabelas_catalogo import Clima, Tema
from app.banco.tabelas_interacoes import InteracaoRegistro, InteracaoTema
from app.banco.tabelas_lentes import (
    CmRespostaMes,
    EstudoAtributo,
    EstudoPercepcao,
    EventoMercado,
    JornalistaMatriz,
    MencaoNaoClassificada,
)
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.score import Calibracao


def meses_ate(mes: date, quantos: int) -> list[date]:
    """Os `quantos` meses que terminam em `mes`, do mais antigo ao mais novo.

    A JANELA É FIXA, e não "os meses com dado": a evolução precisa mostrar o
    buraco. Um gráfico que pula de março para junho porque abril e maio não
    tiveram export conta uma história de três meses seguidos que não aconteceu.
    """
    alvo = primeiro_dia(mes)
    saida = [alvo]
    for _ in range(quantos - 1):
        anterior = saida[0]
        saida.insert(
            0,
            anterior.replace(year=anterior.year - 1, month=12)
            if anterior.month == 1
            else anterior.replace(month=anterior.month - 1),
        )
    return saida


def fontes_da_lente(sessao: Session, lente_id: int) -> list[ScoreFonte]:
    return list(
        sessao.scalars(
            select(ScoreFonte)
            .where(ScoreFonte.lente_id == lente_id)
            .order_by(ScoreFonte.ordem)
        )
    )


def lente_e_interna(sessao: Session, lente_id: int) -> bool:
    return any(fonte.interna for fonte in fontes_da_lente(sessao, lente_id))


# -- a evolução mensal ----------------------------------------------------------


def serie_da_lente(
    sessao: Session, lente_id: int, meses: Sequence[date], calibracao: Calibracao
) -> list[dict]:
    """Positivo, neutro e negativo por mês, contados um a um.

    DOIS ESTADOS DE FALTA, e a tela desenha cada um do seu jeito (§2):

        sem base            o mês não tem menção nenhuma desta lente — barra
                            hachurada e "—" no topo
        sem sentimento      há volume, mas nenhuma menção classificada — barra
                            cinza única, com o total no tooltip

    Contar a segunda como zero seria dizer que o mês foi neutro, quando o que
    houve foi ausência de leitura.
    """
    if lente_e_interna(sessao, lente_id):
        return _serie_do_crm(sessao, meses)

    consulta = (
        select(
            Mencao.mes,
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            func.count().filter(Mencao.sentimento == "neg"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(list(meses)),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.mes)
    )
    medido = {
        mes: {"pos": pos, "neu": neu, "neg": neg}
        for mes, pos, neu, neg in sessao.execute(consulta)
    }
    nao_classificadas = _nao_classificadas(sessao, lente_id, meses, calibracao)
    vazio = {"pos": 0, "neu": 0, "neg": 0}
    return [
        {
            "mes": mes,
            # SEM BASE é não ter passado NADA por ali. Um mês em que só chegaram
            # menções que ninguém classificou tem base — tem volume —, e o que
            # falta é a leitura do fornecedor. São dois estados diferentes, e a
            # §2 desenha cada um do seu jeito.
            "sem_base": mes not in medido and mes not in nao_classificadas,
            "sem_classificacao": nao_classificadas.get(mes, 0),
            **medido.get(mes, vazio),
        }
        for mes in meses
    ]


def _nao_classificadas(
    sessao: Session, lente_id: int, meses: Sequence[date], calibracao: Calibracao
) -> dict[date, int]:
    """Quanto chegou em cada mês sem que o fornecedor lesse o sentimento."""
    consulta = (
        select(MencaoNaoClassificada.mes, func.sum(MencaoNaoClassificada.total))
        .join(ScoreFonte, ScoreFonte.id == MencaoNaoClassificada.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            MencaoNaoClassificada.mes.in_(list(meses)),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(MencaoNaoClassificada.mes)
    )
    return {mes: int(total or 0) for mes, total in sessao.execute(consulta)}


def _serie_do_crm(sessao: Session, meses: Sequence[date]) -> list[dict]:
    """A lente institucional: o clima das interações, mês a mês."""
    mes_da_interacao = func.date_trunc(
        "month", InteracaoRegistro.data_interacao
    ).cast(ColunaDeData)
    consulta = (
        select(mes_da_interacao, Clima.codigo, func.count())
        .select_from(InteracaoRegistro)
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .where(
            InteracaoRegistro.arquivado_em.is_(None),
            mes_da_interacao.in_(list(meses)),
        )
        .group_by(mes_da_interacao, Clima.codigo)
    )
    por_mes: dict[date, dict[str, int]] = {}
    for mes, codigo, total in sessao.execute(consulta):
        sentimento = SENTIMENTO_DO_CLIMA.get(codigo)
        if sentimento is None:
            continue
        por_mes.setdefault(mes, {"pos": 0, "neu": 0, "neg": 0})[sentimento] += total
    vazio = {"pos": 0, "neu": 0, "neg": 0}
    return [
        {"mes": mes, "sem_base": mes not in por_mes, **por_mes.get(mes, vazio)}
        for mes in meses
    ]


# -- os painéis que saem das menções --------------------------------------------


def composicao_por_tier(
    sessao: Session, lente_id: int, mes: date, calibracao: Calibracao
) -> list[dict]:
    """Tier do veículo × sentimento — o Painel A da Imprensa.

    É este cruzamento que o peso 10/5/1 do índice captura, e mostrá-lo em
    contagem crua é o que deixa a régua auditável: quem quiser conferir a nota
    multiplica na mão.
    """
    consulta = (
        select(
            Mencao.tier,
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            func.count().filter(Mencao.sentimento == "neg"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            Mencao.tier.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.tier)
    )
    ordem = {"muito_relevante": 0, "relevante": 1, "menos_relevante": 2}
    linhas = [
        {"tier": tier, "positivo": pos, "neutro": neu, "negativo": neg}
        for tier, pos, neu, neg in sessao.execute(consulta)
    ]
    return sorted(linhas, key=lambda linha: ordem.get(linha["tier"], 9))


def temas_por_sentimento(
    sessao: Session, lente_id: int, mes: date, calibracao: Calibracao, quantos: int = 6
) -> list[dict]:
    """Os temas mais falados do mês, com a composição de cada um."""
    rotulo = func.coalesce(Tema.nome, Mencao.tema_texto)
    consulta = (
        select(
            rotulo.label("tema"),
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            func.count().filter(Mencao.sentimento == "neg"),
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
        .order_by(func.count().desc(), rotulo.asc())
        .limit(quantos)
    )
    return [
        {"tema": tema, "positivo": pos, "neutro": neu, "negativo": neg}
        for tema, pos, neu, neg in sessao.execute(consulta)
    ]


def unidades_da_lente(
    sessao: Session, lente_id: int, meses: Sequence[date], calibracao: Calibracao,
    quantos: int = 6,
) -> list[dict]:
    """Volume por concessionária no período, com o mês de pico de cada uma.

    O PICO VAI JUNTO porque volume sem quando não orienta ação: 2.515 menções
    espalhadas por seis meses e 2.515 concentradas em março pedem respostas
    diferentes.
    """
    consulta = (
        select(Mencao.unidade_texto, Mencao.mes, func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(list(meses)),
            Mencao.unidade_texto.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.unidade_texto, Mencao.mes)
    )
    por_unidade: dict[str, dict] = {}
    # ORDENADO ANTES DE RESOLVER O EMPATE. Sem isto, duas altas iguais deixavam
    # o "mês de pico" à mercê da ordem física das linhas — a mesma tela podia
    # dizer março numa carga e maio na seguinte, sem nada ter mudado.
    for unidade, mes, total in sorted(
        sessao.execute(consulta), key=lambda linha: (linha[0], linha[1])
    ):
        atual = por_unidade.setdefault(
            unidade, {"unidade": unidade, "total": 0, "pico_mes": None, "pico": 0}
        )
        atual["total"] += total
        # `>` e não `>=`: empatado, fica o mês MAIS ANTIGO — é quando o
        # problema apareceu, que é o que orienta ação.
        if total > atual["pico"]:
            atual["pico"] = total
            atual["pico_mes"] = mes
    return sorted(
        por_unidade.values(), key=lambda linha: (-linha["total"], linha["unidade"])
    )[:quantos]


def teor_por_mes(
    sessao: Session, lente_id: int, meses: Sequence[date], calibracao: Calibracao
) -> list[dict]:
    """Reclamação, Dúvida, Elogio e o resto, mês a mês — o Painel B de Clientes.

    Devolve TODOS os teores, inclusive os não acionáveis: a tela decide o que
    mostrar em coluna e o que somar no rodapé, e esconder aqui tiraria dela a
    informação de que 18% do que chegou não era contato.
    """
    consulta = (
        select(Mencao.mes, Mencao.teor, Mencao.acionavel, func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(list(meses)),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.mes, Mencao.teor, Mencao.acionavel)
    )
    por_mes: dict[date, dict] = {
        mes: {
            "mes": mes,
            "teores": {},
            "acionaveis": 0,
            "sem_classificacao": 0,
            "total": 0,
        }
        for mes in meses
    }
    for mes, teor, acionavel, total in sessao.execute(consulta):
        if mes not in por_mes:
            continue
        linha = por_mes[mes]
        # A MENSAGEM SEM MOTIVO ENTRA NO TOTAL, e não some. Filtrá-la na
        # consulta fazia a soma da tabela não bater com o volume do mês, e a
        # célula que deveria dizer "—" simplesmente não existia.
        if teor is None:
            linha["sem_classificacao"] += total
        else:
            linha["teores"][teor] = linha["teores"].get(teor, 0) + total
        linha["total"] += total
        if acionavel:
            linha["acionaveis"] += total
    return list(por_mes.values())


def recebidas_por_mes(
    sessao: Session, lente_id: int, meses: Sequence[date], calibracao: Calibracao
) -> dict[date, int]:
    """Quantas mensagens chegaram em cada mês. Sai da própria base."""
    consulta = (
        select(Mencao.mes, func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(list(meses)),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(Mencao.mes)
    )
    return {mes: total for mes, total in sessao.execute(consulta)}


def respondidas_por_mes(sessao: Session, meses: Sequence[date]) -> dict[date, dict]:
    """Quantas foram respondidas — o que a planilha não traz.

    Mês sem linha fica FORA do dicionário, e não com zero: zero diria que
    ninguém respondeu nada, que é uma acusação, e não um dado que falta.
    """
    consulta = select(CmRespostaMes).where(CmRespostaMes.mes.in_(list(meses)))
    return {
        linha.mes: {"respondidas": linha.respondidas, "exemplo": linha.exemplo,
                    "origem": linha.origem}
        for linha in sessao.scalars(consulta)
    }


# -- os painéis da lente institucional, que saem do CRM -------------------------
#
# A institucional é a única lente cuja fonte é INTERNA: não há menção para
# agrupar, há agenda registrada. Reaproveitar as consultas de `mencao` aqui
# devolveria zero — e zero, numa tela, se lê como "não houve", não como "está
# noutro lugar".


def temas_do_crm(sessao: Session, meses: Sequence[date], quantos: int = 6) -> list[dict]:
    """Os assuntos das agendas do período, com o clima de cada um.

    O CLIMA É O SENTIMENTO DESTA LENTE: propositivo, neutro e tenso viram
    positivo, neutro e negativo pela mesma tabela que o índice usa — é o que
    faz o painel e a nota contarem a mesma história.
    """
    mes_da_interacao = func.date_trunc(
        "month", InteracaoRegistro.data_interacao
    ).cast(ColunaDeData)
    consulta = (
        select(Tema.nome, Clima.codigo, func.count())
        .select_from(InteracaoRegistro)
        .join(InteracaoTema, InteracaoTema.interacao_id == InteracaoRegistro.id)
        .join(Tema, Tema.id == InteracaoTema.tema_id)
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .where(
            InteracaoRegistro.arquivado_em.is_(None),
            mes_da_interacao.in_(list(meses)),
        )
        .group_by(Tema.nome, Clima.codigo)
    )
    por_tema: dict[str, dict] = {}
    for nome, codigo, total in sessao.execute(consulta):
        sentimento = SENTIMENTO_DO_CLIMA.get(codigo)
        if sentimento is None:
            continue
        linha = por_tema.setdefault(
            nome, {"tema": nome, "positivo": 0, "neutro": 0, "negativo": 0}
        )
        linha[{"pos": "positivo", "neu": "neutro", "neg": "negativo"}[sentimento]] += total
    return sorted(
        por_tema.values(),
        key=lambda linha: (
            -(linha["positivo"] + linha["neutro"] + linha["negativo"]),
            linha["tema"],
        ),
    )[:quantos]


def orgaos_do_crm(sessao: Session, meses: Sequence[date], quantos: int = 6) -> list[dict]:
    """Com quem a companhia mais se encontrou no período.

    SEM FILTRO DE CLIMA: aqui a pergunta é onde a agenda se concentra, e uma
    reunião sem clima registrado continua sendo uma reunião que aconteceu.
    """
    mes_da_interacao = func.date_trunc(
        "month", InteracaoRegistro.data_interacao
    ).cast(ColunaDeData)
    consulta = (
        select(Instituicao.nome, mes_da_interacao, func.count())
        .select_from(InteracaoRegistro)
        .join(Instituicao, Instituicao.id == InteracaoRegistro.instituicao_id)
        .where(
            InteracaoRegistro.arquivado_em.is_(None),
            mes_da_interacao.in_(list(meses)),
        )
        .group_by(Instituicao.nome, mes_da_interacao)
    )
    por_orgao: dict[str, dict] = {}
    for nome, mes, total in sorted(
        sessao.execute(consulta), key=lambda linha: (linha[0], linha[1])
    ):
        atual = por_orgao.setdefault(
            nome, {"unidade": nome, "total": 0, "pico_mes": None, "pico": 0}
        )
        atual["total"] += total
        if total > atual["pico"]:
            atual["pico"] = total
            atual["pico_mes"] = mes
    return sorted(
        por_orgao.values(), key=lambda linha: (-linha["total"], linha["unidade"])
    )[:quantos]


# -- o que vem do cadastro ------------------------------------------------------


def eventos_de_mercado(sessao: Session, meses: Sequence[date]) -> list[EventoMercado]:
    """Os fatos do período, do mais antigo ao mais novo."""
    inicio, fim = meses[0], meses[-1]
    proximo = (
        fim.replace(year=fim.year + 1, month=1)
        if fim.month == 12
        else fim.replace(month=fim.month + 1)
    )
    return list(
        sessao.scalars(
            select(EventoMercado)
            .where(EventoMercado.data >= inicio, EventoMercado.data < proximo)
            .order_by(EventoMercado.data)
        )
    )


def estudo_vigente(sessao: Session, mes: date) -> tuple[EstudoPercepcao | None, list]:
    """O estudo mais recente até o mês pedido, com seus atributos.

    ATÉ O MÊS, e não o mais recente de todos: abrir março e ver a percepção
    medida em julho seria mostrar o futuro como se fosse o retrato daquele mês.
    """
    estudo = sessao.scalars(
        select(EstudoPercepcao)
        .where(EstudoPercepcao.data < _inicio_do_mes_seguinte(mes))
        .order_by(EstudoPercepcao.data.desc())
        .limit(1)
    ).first()
    if estudo is None:
        return None, []
    atributos = list(
        sessao.scalars(
            select(EstudoAtributo)
            .where(EstudoAtributo.estudo_id == estudo.id)
            .order_by(EstudoAtributo.ordem, EstudoAtributo.atributo)
        )
    )
    return estudo, atributos


def _inicio_do_mes_seguinte(mes: date) -> date:
    """O primeiro dia do mês seguinte — o limite ABERTO de um mês.

    Chamava-se `_fim_do_mes` e era comparado com `<=`: um estudo datado no dia
    1º de julho aparecia ao abrir junho. O nome mentia, e o operador errado em
    cima do nome errado é o tipo de defeito que ninguém encontra lendo — só
    olhando o dado e estranhando.
    """
    primeiro = primeiro_dia(mes)
    return (
        primeiro.replace(year=primeiro.year + 1, month=1)
        if primeiro.month == 12
        else primeiro.replace(month=primeiro.month + 1)
    )


def matriz_de_jornalistas(sessao: Session) -> list[JornalistaMatriz]:
    return list(
        sessao.scalars(
            select(JornalistaMatriz)
            .where(JornalistaMatriz.ativo.is_(True))
            .order_by(
                (
                    JornalistaMatriz.relevancia
                    + JornalistaMatriz.exposicao
                    + JornalistaMatriz.proximidade
                ).desc(),
                JornalistaMatriz.nome,
            )
        )
    )


def lente_por_codigo(sessao: Session, codigo: str) -> Lente | None:
    return sessao.scalars(select(Lente).where(Lente.codigo == codigo)).first()
