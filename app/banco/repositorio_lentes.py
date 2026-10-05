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
    condicoes_do_filtro,
    primeiro_dia,
    so_fontes_ligadas,
    so_interacoes_visiveis,
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
from app.dominio.score import Calibracao, FiltroDeMencoes


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
    sessao: Session,
    lente_id: int,
    meses: Sequence[date],
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> list[dict]:
    """Positivo, neutro e negativo por mês, contados um a um.

    DOIS ESTADOS DE FALTA, e a tela desenha cada um do seu jeito (§2):

        sem base            o mês não tem menção nenhuma desta lente — barra
                            hachurada e "—" no topo
        sem sentimento      há volume, mas nenhuma menção classificada — barra
                            cinza única, com o total no tooltip

    Contar a segunda como zero seria dizer que o mês foi neutro, quando o que
    houve foi ausência de leitura.

    `filtro` NÃO VALE PARA A LENTE INTERNA: tier/veículo/atributo/tema são
    campos de `mencao`, e o clima das interações não passa por ela — ver
    `FiltroDeMencoes`.
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
            *condicoes_do_filtro(filtro),
        )
        .group_by(Mencao.mes)
    )
    medido = {
        mes: {"pos": pos, "neu": neu, "neg": neg}
        for mes, pos, neu, neg in sessao.execute(consulta)
    }
    # NÃO-CLASSIFICADAS NÃO TEM COMO SABER DE VEÍCULO/ATRIBUTO/TEMA — é uma
    # contagem agregada na ingestão, sem essas colunas. Com filtro ativo, as
    # não-classificadas somem da série em vez de aparecerem infladas (contando
    # linhas que o filtro teria excluído se tivesse como classificá-las).
    nao_classificadas = (
        {} if filtro and filtro.ativo else _nao_classificadas(sessao, lente_id, meses, calibracao)
    )
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


def climas_por_codigo(sessao: Session) -> dict[str, Clima]:
    """O dicionário de clima inteiro, por código.

    NOME E COR SEMPRE SAEM DAQUI, nunca de texto fixo no código: o rótulo já
    mudou duas vezes (Proativo/Reativo na 0030, Positivo/Negativo na 0047) e a
    cor é a mesma que pinta o Painel (`clima.cor_hex`) — ver `dicionarios.py`.
    Repetir qualquer um dos dois como string solta é como `SENTIMENTO_DO_CLIMA`
    já evita: o próximo rótulo trocado exigiria caçar mais um lugar.
    """
    return {c.codigo: c for c in sessao.scalars(select(Clima))}


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
            *so_interacoes_visiveis(),
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
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> list[dict]:
    """Tier do veículo × sentimento — o Painel A da Imprensa.

    É este cruzamento que o peso 10/5/1 do índice captura, e mostrá-lo em
    contagem crua é o que deixa a régua auditável: quem quiser conferir a nota
    multiplica na mão.

    COM O FILTRO DE TIER ATIVO, este painel vira uma única barra — é o
    esperado: "Tier × sentimento" filtrado por um tier só mostra ele mesmo.
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
            *condicoes_do_filtro(filtro),
        )
        .group_by(Mencao.tier)
    )
    ordem = {"muito_relevante": 0, "relevante": 1, "menos_relevante": 2}
    linhas = [
        {"tier": tier, "positivo": pos, "neutro": neu, "negativo": neg}
        for tier, pos, neu, neg in sessao.execute(consulta)
    ]
    return sorted(linhas, key=lambda linha: ordem.get(linha["tier"], 9))


def opcoes_de_filtro(sessao: Session, lente_id: int, mes: date) -> dict[str, list[str]]:
    """Os valores de veículo/atributo/tema que REALMENTE aparecem no mês desta
    lente — e não um dicionário fechado, porque nenhum dos três é um: são
    texto livre que cada fornecedor manda do seu jeito.

    SÓ DO MÊS, de propósito: oferecer um veículo que só existiu em março
    deixaria o filtro aceitar uma escolha que não muda nada no mês vigente, e
    quem escolheu não teria como saber que o resultado vazio era disso.
    """

    def _distintos(coluna) -> list[str]:
        consulta = (
            select(coluna)
            .distinct()
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .where(
                ScoreFonte.lente_id == lente_id,
                Mencao.mes == primeiro_dia(mes),
                coluna.is_not(None),
            )
            .order_by(coluna)
        )
        return [valor for (valor,) in sessao.execute(consulta) if valor]

    def _mais_presentes(coluna, quantos: int) -> list[str]:
        """Os valores com mais menções no mês, e só eles.

        UM SELETOR DE MIL E SETECENTAS OPÇÕES NÃO É UM SELETOR — e é isso que o
        autor dá em junho de 2026, com perfis que a fonte nem soube nomear
        ("1000000000"). Quem aparece uma vez no mês não é um recorte: é uma linha
        da lista de itens, que a tela já mostra.

        POR VOLUME, E NÃO ALFABÉTICO, porque a pergunta de quem abre o seletor é
        "quem está falando deste mês", e a resposta começa por quem fala mais.
        """
        consulta = (
            select(coluna, func.count().label("total"))
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .where(
                ScoreFonte.lente_id == lente_id,
                Mencao.mes == primeiro_dia(mes),
                coluna.is_not(None),
            )
            .group_by(coluna)
            .order_by(func.count().desc(), coluna.asc())
            .limit(quantos)
        )
        return [valor for valor, _ in sessao.execute(consulta) if valor]

    return {
        "tiers": _distintos(Mencao.tier),
        "veiculos": _distintos(Mencao.veiculo),
        "atributos": _distintos(Mencao.atributo),
        "temas": _distintos(Mencao.tema_texto),
        # -- os cortes que o padrão Aegea trouxe (0055) ----------------------
        #
        # O PACOTE DE PRODUÇÃO LISTA AS DIMENSÕES ÚTEIS DE CADA LENTE, e as da
        # Sociedade digital são tema, subtema, empresa citada, rede, perfil do
        # autor, autor, fonte e UF. Quatro delas chegaram com a carga do padrão e
        # não tinham por onde ser escolhidas na tela.
        #
        # AQUI, E NÃO EM PAINEL NOVO, porque os dois painéis do dossiê são
        # estrutura fixa — é o que faz as cinco lentes se lerem igual. O filtro é
        # o lugar onde a tela já aceita recortar por mais dimensões do que
        # desenha, e é dele que o recorte do pacote (nível 3) nasce.
        #
        # VAZIO NAS LENTES QUE NÃO TÊM O CAMPO, e isso é o próprio contrato de
        # `_distintos`: ele só devolve o que aparece no mês daquela lente. A
        # Imprensa não manda perfil do autor, então a chave vem vazia e a tela
        # não oferece o filtro.
        "perfis": _distintos(Mencao.perfil_autor),
        "ufs": _distintos(Mencao.uf),
        "subtemas": _distintos(Mencao.subtema),
        #: O AUTOR É O ÚNICO CORTADO: os outros cabem numa lista (25 UFs, 40
        #: subtemas, 4 perfis), e o autor são 1.745 no mês real.
        "autores": _mais_presentes(Mencao.autor, 20),
    }


def materias_recentes(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantas: int = 5,
) -> list[dict]:
    """As `quantas` matérias mais recentes do mês — o drill-down até a linha.

    NÃO É A MATÉRIA, É O METADADO DELA: `mencao` não guarda título nem link
    hoje — o pipeline de importação atual não tem como ler isso (ver
    `ingestao_score.CAMPOS`), independente do que a planilha de origem traga.

    A CALIBRAÇÃO VALE AQUI TAMBÉM, pela mesma razão do resto do dossiê: uma
    matéria de fonte desligada não entrou na nota lá em cima, e listá-la aqui
    embaixo contaria uma história que o número não sustenta.

    SEM DADO É LISTA VAZIA, igual ao resto do dossiê — nunca uma linha
    inventada para preencher a tabela.
    """
    rotulo = func.coalesce(Tema.nome, Mencao.tema_texto)
    consulta = (
        select(
            Mencao.data,
            Mencao.veiculo,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.atributo,
            rotulo,
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        # MAIS RECENTE PRIMEIRO; SEM DATA POR ÚLTIMO — `data` é opcional no
        # schema (algumas fontes não trazem a data exata da matéria), e uma
        # linha sem data não é "a mais antiga", é "não se sabe quando".
        .order_by(Mencao.data.desc().nulls_last(), Mencao.criado_em.desc())
        .limit(quantas)
    )
    return [
        {
            "data": data,
            "veiculo": veiculo,
            "sentimento": sentimento,
            "tier": tier,
            "atributo": atributo,
            "tema": tema,
        }
        for data, veiculo, sentimento, tier, atributo, tema in sessao.execute(consulta)
    ]


def temas_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
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
            *condicoes_do_filtro(filtro),
        )
        .group_by(rotulo)
        .order_by(func.count().desc(), rotulo.asc())
        .limit(quantos)
    )
    return [
        {"tema": tema, "positivo": pos, "neutro": neu, "negativo": neg}
        for tema, pos, neu, neg in sessao.execute(consulta)
    ]


#: QUANTOS PILARES REPUTACIONAIS EXISTEM — 7, pelo slide que substituiu os 4
#: blocos de tema (ver a conversa que abriu essa mudança). NÃO É UM TETO DE
#: "TOP N" como em `temas_por_sentimento`: atributo é vocabulário FECHADO, e
#: um teto menor que o total corta um pilar inteiro da tela sem avisar — foi
#: o que aconteceu com `quantos=6`: "Inovação e Tecnologia" desaparecia de
#: "Drivers e riscos" sempre que os outros seis tivessem mais matérias no mês.
QUANTOS_PILARES_REPUTACIONAIS = 7


def atributos_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = QUANTOS_PILARES_REPUTACIONAIS,
) -> list[dict]:
    """Os atributos reputacionais mais falados do mês — "Drivers e riscos":
    o que está puxando a lente para cima ou para baixo, e não só o saldo
    final. Mesmo molde de `temas_por_sentimento`, sem o `coalesce` com `Tema`
    porque atributo não tem dicionário do CRM para casar — é só da Clipei.

    `quantos` É O TOTAL DE PILARES, e não um corte de "top N": ao contrário de
    tema ou veículo, atributo é um vocabulário fechado — perder um pilar da
    tela por volume baixo no mês esconderia justamente o que mais precisa de
    atenção (pouco falado é, às vezes, o próprio problema).
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
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            Mencao.atributo.is_not(None),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        .group_by(Mencao.atributo)
        .order_by(func.count().desc(), Mencao.atributo.asc())
        .limit(quantos)
    )
    return [
        {"atributo": atributo, "positivo": pos, "neutro": neu, "negativo": neg}
        for atributo, pos, neu, neg in sessao.execute(consulta)
    ]


def _por_coluna_de_texto(
    sessao: Session,
    coluna,
    rotulo: str,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
    ordenar_pelo_negativo: bool = False,
) -> list[dict]:
    """O corte do mês por uma coluna de texto da própria menção.

    UMA FUNÇÃO PARA OS QUATRO CORTES NOVOS — perfil do autor, UF, subtema e
    autor —, porque é literalmente a mesma consulta: agrupar por uma coluna de
    `mencao`, contar por sentimento, ignorar nulo. As irmãs mais velhas
    (`temas_por_sentimento`, `veiculos_por_sentimento`) são separadas porque cada
    uma tem a sua particularidade: tema casa com o dicionário do CRM por
    `coalesce`, veículo tem grafia a normalizar. Estas quatro não têm nenhuma, e
    quatro cópias da mesma consulta divergiriam na primeira correção.

    NULO FICA FORA, e isto é decisão de leitura: a UF vem em pouco mais da metade
    dos itens e o subtema em 15%. Uma linha "sem classificação" seria a maior de
    todas em quase todo mês, dizendo nada sobre a reputação — e empurrando para
    baixo as que dizem algo. Quanto falta de cada campo é assunto da ficha de
    procedência do bloco, que a tela já mostra.

    `ordenar_pelo_negativo` É PARA O AUTOR, e a diferença importa: o corte por
    perfil responde "como se divide o mês" e se ordena por volume; o de autor
    responde "quem pesou contra", e aí quem falou muito e elogiou não é a
    resposta.
    """
    negativas = func.count().filter(Mencao.sentimento == "neg")
    consulta = (
        select(
            coluna,
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            negativas,
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            coluna.is_not(None),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        .group_by(coluna)
        .order_by(
            negativas.desc() if ordenar_pelo_negativo else func.count().desc(),
            coluna.asc(),
        )
        .limit(quantos)
    )
    return [
        {rotulo: valor, "positivo": pos, "neutro": neu, "negativo": neg}
        for valor, pos, neu, neg in sessao.execute(consulta)
    ]


def perfis_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
) -> list[dict]:
    """Quem fala, e com que sinal: Cidadão, Figura pública, Imprensa, Perfil
    institucional.

    É O CORTE QUE MAIS MUDA A LEITURA DA LENTE. Mil cidadãos reclamando e um
    deputado reclamando têm o mesmo sinal e consequências diferentes — um é
    clima, o outro é agenda. Sem este corte a lente diz que o negativo subiu e
    não diz de quem é a voz.
    """
    return _por_coluna_de_texto(
        sessao,
        Mencao.perfil_autor,
        "perfil",
        lente_id,
        mes,
        calibracao,
        filtro,
        quantos,
    )


def ufs_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
) -> list[dict]:
    """Onde o mês pesou, por estado. É a base do indicador `UF mais negativa`."""
    return _por_coluna_de_texto(
        sessao, Mencao.uf, "uf", lente_id, mes, calibracao, filtro, quantos
    )


def subtemas_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
) -> list[dict]:
    """O assunto um nível abaixo do tema — é ele que explica POR QUE um tema pesa.

    "Saneamento básico" é o tema de metade das menções de um mês ruim, e isso não
    diz nada que se possa resolver; "Falta de água" e "Obra atrasada", dentro
    dele, dizem.
    """
    return _por_coluna_de_texto(
        sessao, Mencao.subtema, "subtema", lente_id, mes, calibracao, filtro, quantos
    )


def autores_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
) -> list[dict]:
    """Quem pesou contra, do mais negativo para o menos.

    ORDENADO PELO NEGATIVO, e não por volume: o indicador pergunta quem pesou
    contra, e quem falou muito elogiando não é essa resposta.
    """
    return _por_coluna_de_texto(
        sessao,
        Mencao.autor,
        "autor",
        lente_id,
        mes,
        calibracao,
        filtro,
        quantos,
        ordenar_pelo_negativo=True,
    )


def veiculos_por_sentimento(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 5,
) -> list[dict]:
    """Os veículos com mais matérias no mês — "quem é a cobertura" desta
    lente, e o saldo de sentimento de cada um.

    POR VOLUME, E NÃO POR SALDO — mesmo critério de `unidades_da_lente` e do
    placar de clima do Painel (CRM): o veículo que mais falou da companhia
    entra primeiro, com o saldo que ele tiver, bom ou ruim. Ordenar pelo
    saldo esconderia o volume: um veículo com 2 matérias e 100% negativo
    pesaria mais que um com 40 matérias e 60% negativo, que é o que de fato
    está formando a opinião do mês.
    """
    consulta = (
        select(
            Mencao.veiculo,
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            func.count().filter(Mencao.sentimento == "neg"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            Mencao.veiculo.is_not(None),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        .group_by(Mencao.veiculo)
        .order_by((func.count()).desc(), Mencao.veiculo.asc())
        .limit(quantos)
    )
    return [
        {
            "veiculo": veiculo,
            "positivo": pos,
            "neutro": neu,
            "negativo": neg,
            "total": pos + neu + neg,
        }
        for veiculo, pos, neu, neg in sessao.execute(consulta)
    ]


def veiculos_tier1_do_periodo(
    sessao: Session,
    lente_id: int,
    meses: Sequence[date],
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> int:
    """Quantos veículos DIFERENTES, Tier 1 (muito relevante), cobriram a Aegea
    no período.

    O SUBSTITUTO HONESTO DE "Jornalistas P1": aquele KPI vinha da matriz de
    jornalistas, que promete uma relação jornalista-a-jornalista que ainda não
    existe — hoje é dado de exemplo (ver `JornalistaMatriz`). O tier do
    veículo, ao contrário, é o mesmo dado real que já forma o Top 5 veículos e
    a régua do índice: vem de cada matéria ingerida, não de cadastro à parte.
    """
    consulta = (
        select(func.count(func.distinct(Mencao.veiculo)))
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(list(meses)),
            Mencao.tier == "muito_relevante",
            Mencao.veiculo.is_not(None),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
    )
    return sessao.scalar(consulta) or 0


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
            *so_interacoes_visiveis(),
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
            *so_interacoes_visiveis(),
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


def matriz_de_jornalistas(
    sessao: Session, veiculo: str | None = None
) -> list[JornalistaMatriz]:
    """A matriz é cadastro à mão, não vem de `mencao` — só `veiculo` filtra
    aqui: tier/atributo/tema não são atributo de jornalista nenhum."""
    condicoes = [JornalistaMatriz.ativo.is_(True)]
    if veiculo:
        condicoes.append(JornalistaMatriz.veiculo == veiculo)
    return list(
        sessao.scalars(
            select(JornalistaMatriz)
            .where(*condicoes)
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
