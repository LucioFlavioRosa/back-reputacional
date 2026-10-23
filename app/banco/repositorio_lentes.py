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
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Date as ColunaDeData
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.repositorio_score import (
    ATRIBUTO_SEM_PREFIXO,
    CONCESSIONARIA,
    SENTIMENTO_DO_CLIMA,
    condicoes_do_filtro,
    primeiro_dia,
    so_fontes_ligadas,
    so_interacoes_visiveis,
)
from app.banco.tabelas_catalogo import (
    BlocoTema,
    Clima,
    MacroTema,
    Tema,
    UnidadeNegocio,
)
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
from app.dominio.causa_da_lente import (
    Dimensao,
    Presenca,
    dimensoes_do_recorte,
)
from app.dominio.consulta_profundidade import (
    PilarDaTaxonomia,
    SubtemaDaTaxonomia,
    Taxonomia,
    TemaDaTaxonomia,
)
from app.dominio.ingestao_score import para_sigla
from app.dominio.score import Calibracao, FiltroDeMencoes, peso_da_mencao


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
    """A lente se lê deste banco (o CRM), e não de menção ingerida.

    `ativo` CONTA AQUI, e só aqui ele significa isto. Para uma fonte de planilha,
    `ativo=false` é "parou de receber importação" e o histórico dela continua
    valendo, porque está gravado em `score_mes_fonte` — é o que
    `catalogo_das_lentes` documenta. A fonte interna não tem histórico gravado:
    ela é recontada de `interacao_registro` a cada leitura. Aposentá-la só pode
    significar "para de contar", e é o que a `0108` fez com o CRM.

    SEM ISTO, A INSTITUCIONAL FICARIA PARTIDA AO MEIO — achado de revisão. Ela
    tem as duas fontes cadastradas (o CRM aposentado e a Clipei recortada), e com
    `any(interna)` a nota viria das menções enquanto série, explorador, recorte e
    painéis continuariam no CRM: dois números para a mesma lente, cada um certo
    no seu mundo, lado a lado se contradizendo.
    """
    return any(
        fonte.interna and fonte.ativo for fonte in fontes_da_lente(sessao, lente_id)
    )


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


def taxonomia_n1_n2(
    sessao: Session, do_fornecedor: list[str] | None = None
) -> dict[str, list[str]]:
    """Os pilares (N1) e os temas estratégicos (N2), na ordem da taxonomia.

    `do_fornecedor`: os temas que os fornecedores escreveram no período. O TEMA
    DO FORNECEDOR É O PILAR (N1), e por isso entra na lista de N1 — depois dos 7
    da taxonomia, sem repetir o que já está lá."""
    pilares = list(sessao.scalars(select(BlocoTema.nome).order_by(BlocoTema.ordem)))
    vistos = {p.casefold() for p in pilares}
    extras = [t for t in (do_fornecedor or []) if t.casefold() not in vistos]
    return {
        "temas_n1": pilares + sorted(set(extras), key=str.casefold),
        "temas_n2": list(
            sessao.scalars(
                select(MacroTema.nome)
                .join(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
                .order_by(BlocoTema.ordem, MacroTema.ordem)
            )
        ),
    }


def taxonomia_ativa(sessao: Session) -> Taxonomia:
    """Os três níveis ATIVOS da taxonomia v4, para a Consulta em profundidade.

    TRÊS LEITURAS PEQUENAS (7 + 41 + 104 linhas) e a resolução em Python: a
    comparação é sem acento, e o `unaccent` não está instalado no banco — fazê-la
    em SQL pediria uma extensão nova só para isto.

    O SUBTEMA SEM MACRO FICA DE FORA aqui mesmo: são os 45 legados que a 0058
    desativou ("Tarifa", "Universalização"), e casar uma menção com eles a
    deixaria num N3 sem N2 e sem pilar.

    SÓ AS COLUNAS, E NÃO A ENTIDADE: `Tema.vinculos_de_risco` é `selectin`, e
    carregar o ORM inteiro disparava uma quarta leitura (tema_risco) que a
    Consulta não usa.
    """
    pilares = [
        PilarDaTaxonomia(id=id_, codigo=codigo, nome=nome)
        for id_, codigo, nome in sessao.execute(
            select(BlocoTema.id, BlocoTema.codigo, BlocoTema.nome)
            .where(BlocoTema.ativo.is_(True))
            .order_by(BlocoTema.ordem)
        )
    ]
    temas = [
        TemaDaTaxonomia(id=id_, codigo=codigo, nome=nome, pilar_id=pilar_id)
        for id_, codigo, nome, pilar_id in sessao.execute(
            select(MacroTema.id, MacroTema.codigo, MacroTema.nome, MacroTema.bloco_tema_id)
            .join(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
            .where(MacroTema.ativo.is_(True))
            .order_by(BlocoTema.ordem, MacroTema.ordem)
        )
    ]
    subtemas = [
        SubtemaDaTaxonomia(id=id_, nome=nome, tema_id=tema_id)
        for id_, nome, tema_id in sessao.execute(
            select(Tema.id, Tema.nome, Tema.macro_tema_id)
            .where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None))
            .order_by(Tema.id)
        )
    ]
    return Taxonomia(pilares, temas, subtemas)


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

    def _da_taxonomia(coluna) -> list[str]:
        """Os nomes de um nível da taxonomia que as menções do mês alcançam."""
        consulta = (
            select(coluna)
            .distinct()
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .join(Tema, Tema.id == Mencao.tema_id)
            .join(MacroTema, MacroTema.id == Tema.macro_tema_id)
            .join(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
            .where(ScoreFonte.lente_id == lente_id, Mencao.mes == primeiro_dia(mes))
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

    def _concessionarias(quantos: int) -> list[str]:
        """As concessionárias do mês, PELO NOME DO CADASTRO quando ele resolve.

        É `_mais_presentes` com uma junção a mais, e a junção é a razão de esta
        função existir em vez de um parâmetro: sem ela, a Corsan aparece DUAS
        vezes na lista — "Corsan" (1.111 menções) e "Companhia Riograndense de
        Saneamento (Corsan)" (15.019) —, e escolher uma perde a outra. A
        holding aparecia três vezes.

        `coalesce` E `outerjoin`, e não um `join`: a menção que o cadastro não
        resolve — "Águas do Rio" (9.411), que são dois blocos — continua na
        lista com a palavra do fornecedor. Um `join` a sumiria do seletor, que
        é o oposto de normalizar.

        AGRUPA PELA MESMA EXPRESSÃO QUE O FILTRO RECORTA (`condicoes_do_filtro`
        casa o nome do cadastro OU o texto cru). Agrupar por um caminho e
        filtrar por outro faria a opção escolhida devolver menos linhas do que
        a lista prometia — foi exatamente o que aconteceu com a barra do N2 na
        `0098`, e o conserto está no `_por_taxonomia`.
        """
        consulta = (
            select(CONCESSIONARIA, func.count().label("total"))
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .outerjoin(
                UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id
            )
            .where(
                ScoreFonte.lente_id == lente_id,
                Mencao.mes == primeiro_dia(mes),
                CONCESSIONARIA.is_not(None),
            )
            .group_by(CONCESSIONARIA)
            .order_by(func.count().desc(), CONCESSIONARIA.asc())
            .limit(quantos)
        )
        return [valor for valor, _ in sessao.execute(consulta) if valor]

    return {
        "tiers": _distintos(Mencao.tier),
        "veiculos": _distintos(Mencao.veiculo),
        "atributos": _distintos(Mencao.atributo),
        "temas": _distintos(Mencao.tema_texto),
        #: O sentimento da menção, filtro rápido da Imprensa (pos/neu/neg).
        "sentimentos": _distintos(Mencao.sentimento),
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
        #: A concessionária citada. Cortada como o autor, pelo mesmo motivo: numa
        #: base nacional são dezenas, e a lista por volume responde "quem está
        #: aparecendo este mês".
        "empresas": _concessionarias(20),
        # -- a taxonomia de temas do CRM, pelas menções ligadas a ela ----------
        #
        # SÓ O QUE APARECE NO MÊS, como as outras: os nomes dos pilares, temas
        # estratégicos e temas das menções que têm `tema_id`. Sem menção ligada
        # (a base que só traz o texto do fornecedor), as três vêm vazias e a
        # tela não oferece o filtro.
        # PILAR E TEMA ESTRATÉGICO: A TAXONOMIA INTEIRA, sempre — e é a única
        # exceção ao "só o que aparece no mês". São filtros rápidos fixos em
        # toda lente, por pedido, e precisam estar lá mesmo quando o mês ainda
        # não tem menção ligada a tema do cadastro; escolher um sem menção
        # devolve a lista vazia, que é a resposta verdadeira.
        **taxonomia_n1_n2(sessao, _distintos(Mencao.tema_texto)),
        "temas_n3": _da_taxonomia(Tema.nome),
    }


def materias_recentes(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantas: int = 5,
) -> list[dict]:
    """As `quantas` menções do mês que têm o que mostrar — o drill-down até a linha.

    JÁ FOI SÓ METADADO, e o docstring dizia que `mencao` não guardava título nem
    link porque o importador não tinha como lê-los. Deixou de ser verdade na
    0055: o padrão Aegea traz o texto e o endereço da menção, e a carga da
    Sociedade digital pôs 2.208 deles no banco — as negativas, as de tier alto e
    as mais engajadas, que é a amostra que o pacote avisa que vem na primeira
    carga.

    QUEM TEM TEXTO VEM PRIMEIRO, e isto é o que faz a lista servir: 86% dos itens
    chegam sem texto, então ordenar só por data devolveria cinco linhas de
    metadado, sem nada a ler. Dentro dos que têm, o maior engajamento antes — a
    ordem que o pacote pede para esta lente.

    A DATA CONTINUA SENDO O ÚLTIMO CRITÉRIO, e o nulo dela fica por último: uma
    linha sem data não é "a mais antiga", é "não se sabe quando".

    A CALIBRAÇÃO VALE AQUI TAMBÉM, pela mesma razão do resto do dossiê: uma
    menção de fonte desligada não entrou na nota lá em cima, e listá-la aqui
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
            # -- o que a 0055 trouxe: a menção em si, e quem a escreveu -----
            Mencao.titulo_texto,
            Mencao.link,
            Mencao.autor,
            Mencao.perfil_autor,
            Mencao.engajamento,
            Mencao.uf,
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
        # QUEM TEM TEXTO PRIMEIRO, depois o maior engajamento, e só então a
        # data. Ordenar só por data devolveria cinco linhas de metadado numa
        # lente em que 86% dos itens chegam sem texto — uma lista sem nada a ler.
        #
        # SEM DATA POR ÚLTIMO, como antes: `data` é opcional no schema, e uma
        # linha sem data não é "a mais antiga", é "não se sabe quando".
        .order_by(
            Mencao.titulo_texto.is_(None),
            Mencao.engajamento.desc().nulls_last(),
            Mencao.data.desc().nulls_last(),
            Mencao.criado_em.desc(),
        )
        .limit(quantas)
    )
    return [
        {
            "data": data,
            "veiculo": veiculo,
            "sentimento": sentimento,
            "tier": tier,
            "atributo": atributo,
            "titulo_texto": titulo_texto,
            "link": link,
            "autor": autor,
            "perfil_autor": perfil_autor,
            "engajamento": engajamento,
            "uf": uf,
            "tema": tema,
        }
        for (
            data,
            veiculo,
            sentimento,
            tier,
            atributo,
            tema,
            titulo_texto,
            link,
            autor,
            perfil_autor,
            engajamento,
            uf,
        ) in sessao.execute(consulta)
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
    quantos: int | None = 6,
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
        #: PARA `CONCESSIONARIA` PODER SER A COLUNA. Sai barato (29 linhas,
        #: chave indexada) e vale para toda dimensão: o que importa é a aba
        #: agrupar pelo mesmo nome que o seletor oferece e o filtro recorta.
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
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


#: AS DUAS DIMENSÕES QUE SAEM DO CADASTRO, e não de uma coluna da menção. Num
#: lugar só porque três decisões dependem da mesma lista — o corte, a presença e
#: a saída da consulta única —, e três literais `("tema_n2", "tema_n3")` divergem
#: na primeira dimensão nova.
_DIMENSOES_DA_TAXONOMIA = frozenset({"tema_n2", "tema_n3"})


def coluna_da_dimensao(campo: str):
    """A coluna por que uma dimensão da aba "Onde está a causa" agrupa e conta.

    QUASE SEMPRE É O ATRIBUTO DE `Mencao` DE MESMO NOME — `causa_da_lente.
    Dimensao.campo` guarda o nome e diz que "o repositório resolve". A exceção é
    a CONCESSIONÁRIA, e a razão é a mesma que o caso do `tema` logo acima
    registra como achado de revisão: a aba agrupava pelo texto cru enquanto o
    painel ao lado agrupava pelo nome do cadastro, e aí os dois ficam na mesma
    tela com rótulos diferentes para o mesmo mês — e o clique no rótulo manda ao
    servidor uma grafia que o dado não tem.

    Para a concessionária isso é visível: a Corsan seria duas fatias de 1.111 e
    15.019 aqui, e uma de 16.130 no seletor. Quem usa a função tem de ter
    `outerjoin(UnidadeNegocio, ...)` na consulta.
    """
    if campo == "unidade_texto":
        return CONCESSIONARIA
    return getattr(Mencao, campo)


def _por_taxonomia(
    sessao: Session,
    nivel: str,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int | None = None,
) -> list[dict]:
    """O corte do mês pelo N2 (tema estratégico) ou pelo N3 (subtema) do
    cadastro, contado por sentimento.

    PELO MESMO CAMINHO DO FILTRO, sempre — é esta a regra, e ela é mais forte
    que "pelo `tema_id`". Agrupar por um caminho e recortar por outro faria a
    coluna contar menções que o clique nela não recorta. Menção que o caminho
    não alcança fica fora, como o nulo das outras abas; quanto falta vai na
    ficha.

    E O CAMINHO DO N2 MUDOU NA `0098`: `condicoes_do_filtro` passou a aceitar
    `Mencao.macro_tema_id` (a chave gravada) ALÉM da derivação por `tema_id`,
    porque o fornecedor que fala N2 não tem N3 para derivar. Então o
    agrupamento tem de aceitar as duas também — senão o filtro alcança 30.932
    menções e a barra conta 29.701, e as 1.231 de diferença são exatamente as
    que só têm N2.

    `coalesce(Mencao.macro_tema_id, Tema.macro_tema_id)`: a chave gravada
    primeiro, a derivada depois. Elas concordam onde as duas existem — a
    gravação deriva uma da outra (ver `temas_da_mencao.Arvore`) —, então a ordem
    só decide quem responde quando a outra é nula.

    E O `Tema` VIRA `outerjoin` NO N2, por consequência: a menção com N2 e sem
    N3 não tem linha em `Tema`, e o join interno a descartaria antes do
    `coalesce` ter chance. O N3 segue com join INTERNO, porque lá não há o que
    aceitar além do `tema_id` — o filtro `tema_n3` também só usa ele.
    """
    nome = MacroTema.nome if nivel == "tema_n2" else Tema.nome
    consulta = (
        select(
            nome,
            func.count().filter(Mencao.sentimento == "pos"),
            func.count().filter(Mencao.sentimento == "neu"),
            func.count().filter(Mencao.sentimento == "neg"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
    )
    if nivel == "tema_n2":
        consulta = consulta.outerjoin(Tema, Tema.id == Mencao.tema_id).join(
            MacroTema,
            MacroTema.id == func.coalesce(Mencao.macro_tema_id, Tema.macro_tema_id),
        )
    else:
        consulta = consulta.join(Tema, Tema.id == Mencao.tema_id)
    consulta = (
        consulta.where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        .group_by(nome)
        .order_by(func.count().desc(), nome.asc())
        .limit(quantos)
    )
    return [
        {"rotulo": valor, "positivo": pos, "neutro": neu, "negativo": neg}
        for valor, pos, neu, neg in sessao.execute(consulta)
    ]


def _presenca_da_taxonomia(
    sessao: Session,
    nivel: str,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> Presenca:
    """Quanto a aba de taxonomia PODE mostrar — pelo mesmo caminho que ela usa.

    POR QUE NÃO SERVE A PRESENÇA DE `tema_id`, que é o `campo` destas duas
    dimensões. `presenca_das_dimensoes` conta `count(tema_id)`: toda menção com
    vínculo. Mas `_por_taxonomia` chega ao N2 ATRAVESSANDO `MacroTema`, e
    `Tema.macro_tema_id` É NULÁVEL — há 45 temas órfãos em 149 no cadastro, que
    a reconciliação da `0058` deixou para trás por casar só pelo nome exato.

    Uma menção presa a um tema órfão seria CONTADA no "vem em X menções do mês"
    e EXCLUÍDA das barras pelo join. Isto é exatamente o que a ficha existe para
    impedir — "quanto falta vai escrito, e é o que impede a aba de mentir por
    omissão" —, e seria ela mesma mentindo.

    Hoje são 0 menções nessa situação na Imprensa (os 45 órfãos são os temas que
    a taxonomia v4 desativou, e nada novo se liga a eles). Então isto não
    conserta um número errado na tela: impede que ele apareça no dia em que um
    tema nascer sem pilar — e aí ninguém estaria olhando.

    O `count()` SEM COLUNA depois de joins internos já é "quantas menções a aba
    alcança": o join é o filtro. E `distintas` conta o nível certo — macro tema
    no N2, tema no N3 —, não `tema_id` nos dois.

    OS JOINS SÃO OS MESMOS DE `_por_taxonomia`, E TÊM DE SER: esta função existe
    para dizer quanto AQUELA aba alcança. Depois da `0098` o N2 entra também por
    `Mencao.macro_tema_id`, então aqui entra igual — senão a ficha diria "vem em
    29.701 menções" sobre barras que somam 30.932, e seria ela mentindo, que é
    exatamente o que este docstring diz que ela existe para impedir.
    """
    alvo = MacroTema.id if nivel == "tema_n2" else Tema.id
    consulta = (
        select(func.count(), func.count(alvo.distinct()))
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
    )
    if nivel == "tema_n2":
        consulta = consulta.outerjoin(Tema, Tema.id == Mencao.tema_id).join(
            MacroTema,
            MacroTema.id == func.coalesce(Mencao.macro_tema_id, Tema.macro_tema_id),
        )
    else:
        consulta = consulta.join(Tema, Tema.id == Mencao.tema_id)
    consulta = consulta.where(
        ScoreFonte.lente_id == lente_id,
        Mencao.mes == primeiro_dia(mes),
        *so_fontes_ligadas(calibracao),
        *condicoes_do_filtro(filtro),
    )
    preenchidas, distintas = sessao.execute(consulta).one()
    return Presenca(preenchidas=int(preenchidas or 0), distintas=int(distintas or 0))


def grupos_do_explorador(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    regua: str,
    filtro: FiltroDeMencoes | None = None,
) -> list[dict]:
    """As menções do mês agrupadas por N1 (atributo), N2, N3 e UF — o que os
    gráficos N1 › N2 › N3 e o mapa da Síntese executiva somam.

    AGREGADO PRONTO PARA SER SOMADO NA TELA, e é o que faz o clique ser
    instantâneo: escolher um N1 refaz o N2, o N3 e o mapa somando estas linhas
    no navegador, sem nova ida ao servidor. Cada linha traz a contagem (o que a
    barra desenha) e o peso por sentimento (o que a nota e o impacto usam) —
    peso se soma, e o denominador do mês é um só.

    O PESO É O DA NOTA (`peso_da_mencao`, régua do mês): a soma dos pesos de
    todas as linhas é o denominador do mês, e é por isso que o impacto de cada
    barra fecha com a nota.
    """
    consulta = (
        select(
            ATRIBUTO_SEM_PREFIXO.label("n1"),
            MacroTema.nome.label("n2"),
            Tema.nome.label("n3"),
            Mencao.uf,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.cargo,
            Mencao.engajamento,
            func.count().label("quantas"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .outerjoin(MacroTema, MacroTema.id == Tema.macro_tema_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        .group_by(
            ATRIBUTO_SEM_PREFIXO,
            MacroTema.nome,
            Tema.nome,
            Mencao.uf,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.cargo,
            Mencao.engajamento,
        )
    )
    grupos: dict[tuple, dict] = {}
    for linha in sessao.execute(consulta):
        #: A UF SAI EM SIGLA, que é o que o mapa e a lista da tela procuram.
        #: Desde 09/10/2026 `mencao.uf` guarda o NOME ("Santa Catarina", ver
        #: `para_uf`), e a tela não achava estado nenhum: o Termômetro por UF
        #: ficava vazio com a base reimportada. Estado estrangeiro não tem
        #: sigla e continua com o nome que o fornecedor deu.
        uf = para_sigla(linha.uf) or linha.uf
        chave = (linha.n1 or None, linha.n2, linha.n3, uf)
        grupo = grupos.setdefault(
            chave,
            {
                "n1": chave[0],
                "n2": chave[1],
                "n3": chave[2],
                "uf": chave[3],
                "positivo": 0,
                "neutro": 0,
                "negativo": 0,
                "peso_positivo": 0.0,
                "peso_neutro": 0.0,
                "peso_negativo": 0.0,
            },
        )
        lado = {"pos": "positivo", "neg": "negativo"}.get(linha.sentimento, "neutro")
        peso = peso_da_mencao(linha.tier, linha.cargo, linha.engajamento, calibracao, regua)
        grupo[lado] += int(linha.quantas)
        grupo[f"peso_{lado}"] += peso * int(linha.quantas)
    return list(grupos.values())


def grupos_de_veiculos(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    regua: str,
    filtro: FiltroDeMencoes | None = None,
) -> list[dict]:
    """As menções do mês agrupadas por tier e veículo — o que os três painéis
    do Explorador de veículos somam na tela.

    O MESMO MECANISMO DE `grupos_do_explorador`, com uma chave menor: agregado
    pronto para ser somado no navegador, e é isso que faz o clique ser
    instantâneo sem mover o dossiê. Cada linha traz a contagem (o que a barra
    desenha) e o peso por sentimento (o que a nota e o impacto usam) — peso se
    soma, e o denominador do mês é um só.

    UMA LINHA POR PAR `(tier, veiculo)`, E NÃO POR VEÍCULO: o mesmo veículo
    pode ter matéria em mais de um tier, e somar aqui tiraria da tela a
    possibilidade de estreitar por tier. A soma por veículo é trabalho de quem
    desenha.

    POR QUE UMA ROTA PRÓPRIA, e não `tier`/`veiculo` dentro de
    `grupos_do_explorador`: acrescentá-los àquela chave multiplicaria a
    cardinalidade (`n1 × n2 × n3 × uf × tier × veículo`). Uma chave de só
    `tier × veículo` é a carga mínima que responde aos três painéis.

    `cargo` E `engajamento` ENTRAM NO `group_by` SÓ PORQUE `peso_da_mencao`
    PRECISA DELES, e não saem na resposta — o mesmo motivo pelo qual estão em
    `grupos_do_explorador`.

    SEM JUNÇÃO DE `Tema`/`MacroTema`, ao contrário do explorador de taxonomia:
    esta consulta não lê taxonomia, e os filtros de taxonomia da tela continuam
    valendo sem o join porque `condicoes_do_filtro` casa por SUBCONSULTA, nunca
    por junção — decisão registrada lá com a razão ("entra em nove consultas
    diferentes, e acrescentar uma junção aqui mudaria o `from` delas por
    baixo"). Esta é a décima.
    """
    consulta = (
        select(
            Mencao.tier,
            Mencao.veiculo,
            Mencao.sentimento,
            Mencao.cargo,
            Mencao.engajamento,
            func.count().label("quantas"),
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
        .group_by(
            Mencao.tier,
            Mencao.veiculo,
            Mencao.sentimento,
            Mencao.cargo,
            Mencao.engajamento,
        )
    )
    grupos: dict[tuple, dict] = {}
    for linha in sessao.execute(consulta):
        chave = (linha.tier or None, linha.veiculo or None)
        grupo = grupos.setdefault(
            chave,
            {
                "tier": chave[0],
                "veiculo": chave[1],
                "positivo": 0,
                "neutro": 0,
                "negativo": 0,
                "peso_positivo": 0.0,
                "peso_neutro": 0.0,
                "peso_negativo": 0.0,
            },
        )
        lado = {"pos": "positivo", "neg": "negativo"}.get(linha.sentimento, "neutro")
        peso = peso_da_mencao(linha.tier, linha.cargo, linha.engajamento, calibracao, regua)
        grupo[lado] += int(linha.quantas)
        grupo[f"peso_{lado}"] += peso * int(linha.quantas)
    return list(grupos.values())


def presenca_das_dimensoes(
    sessao: Session,
    campos: Sequence[str],
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> tuple[dict[str, Presenca], int]:
    """Quanto cada dimensão aparece no mês, e quantas menções o mês tem.

    UMA CONSULTA PARA TODAS, e isto é o que torna as abas viáveis: decidir quais
    cortes merecem aba exige saber, de cada um, quantas menções o trazem e em
    quantos valores — sete perguntas. Sete consultas seriam sete idas ao banco
    para NÃO desenhar nada; `count` e `count(distinct)` lado a lado na mesma
    varredura custam uma.

    `COUNT(COLUNA)` IGNORA NULO e `COUNT(*)` não — é nessa diferença que mora o
    "quanto falta", que a ficha de cada aba publica.
    """
    medidas: list = [func.count()]
    for campo in campos:
        #: PELA MESMA COLUNA QUE O CORTE AGRUPA (`coluna_da_dimensao`), e não
        #: por `getattr` direto: a ficha da aba publica "vem em N menções, em M
        #: valores", e M tem de ser o número de rótulos que a aba desenha. Com
        #: o texto cru, a concessionária diria 65 valores e a aba mostraria 62.
        coluna = coluna_da_dimensao(campo)
        medidas.append(func.count(coluna))
        medidas.append(func.count(coluna.distinct()))
    consulta = (
        select(*medidas)
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
    )
    linha = sessao.execute(consulta).one()
    total = int(linha[0] or 0)
    presencas = {
        campo: Presenca(
            preenchidas=int(linha[1 + i * 2] or 0),
            distintas=int(linha[2 + i * 2] or 0),
        )
        for i, campo in enumerate(campos)
    }
    return presencas, total


@dataclass(frozen=True)
class CorteDaCausa:
    """Um corte do mês por uma dimensão — ou a falta dele.

    COM NOME, e não uma tupla de quatro: a tupla era desempacotada por índice em
    dois lugares (`corte[0].chave`), e o terceiro lugar erraria a ordem.
    """

    dimensao: Dimensao
    #: Vazio no corte que NÃO explica o mês: ele existe no resultado para a tela
    #: poder dizer por que a aba esperada não está lá.
    linhas: list[dict]
    presenca: Presenca
    total: int

    @property
    def explica(self) -> bool:
        return bool(self.linhas)


def cortes_da_causa(
    sessao: Session,
    codigo_da_lente: str,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    quantos: int = 6,
    ve_diretorio: bool = True,
    dimensoes: list[Dimensao] | None = None,
) -> list[CorteDaCausa]:
    """Os cortes que explicam o mês desta lente — um por aba de "onde está a
    causa", cada um com as suas linhas e com quanto da dimensão o mês tem.

    TUDO NO MESMO PEDIDO, e isto foi medido antes de decidir: os seis cortes do
    mês mais cheio (6.932 menções) somam 109 ms. Um endpoint por aba custaria um
    estado de carregamento a cada clique e um segundo caminho de dados para a
    mesma conta — por um ganho que o relógio não vê.

    A MEDIDA VEM PRIMEIRO, de propósito: só se consulta o corte da dimensão que
    passou no critério. Num mês em que a fonte não mandou UF nem subtema, isto é
    uma consulta em vez de três.

    DENTRO DO RECORTE ATIVO, e é o que faz o terceiro nível existir: com uma UF
    escolhida, as abas passam a explicar AQUELA UF. Descer um nível é refazer a
    mesma pergunta num pedaço menor, e não olhar o mês inteiro de outro jeito.
    """
    #: `dimensoes` VEM DE QUEM CHAMA quando o painel de aprofundamento tem abas
    #: próprias (ver `dimensoes_do_aprofundamento`); sem ela, as do cartão.
    if dimensoes is None:
        dimensoes = dimensoes_do_recorte(codigo_da_lente, ve_diretorio)
    if not dimensoes:
        return []
    #: A TAXONOMIA FICA FORA DA CONSULTA ÚNICA, e tem presença própria: o `campo`
    #: das duas é `tema_id`, que não é o que as abas delas alcançam — ver
    #: `_presenca_da_taxonomia`. Deixá-las aqui também punha `tema_id` DUAS vezes
    #: em `campos`, e o dicionário de presenças descartava uma em silêncio.
    presencas_por_campo, total = presenca_das_dimensoes(
        sessao,
        [d.campo for d in dimensoes if d.chave not in _DIMENSOES_DA_TAXONOMIA],
        lente_id,
        mes,
        calibracao,
        filtro,
    )
    presencas = presencas_por_campo
    #: UM CORTE POR DIMENSÃO, SEMPRE — e a que não tem dado volta com `linhas`
    #: vazio, para a aba existir e dizer que a fonte não classificou. Ver
    #: `dimensoes_do_recorte`: a fileira de abas é a mesma em todo mês.
    cortes: list[CorteDaCausa] = []
    for dimensao in dimensoes:
        if dimensao.chave in _DIMENSOES_DA_TAXONOMIA:
            presenca = _presenca_da_taxonomia(
                sessao, dimensao.chave, lente_id, mes, calibracao, filtro
            )
        else:
            presenca = presencas[dimensao.campo]
        limite = None if dimensao.todos else quantos
        if not presenca.preenchidas:
            #: SEM UM VALOR SEQUER, nem se consulta: a aba sai vazia, e a medida
            #: que já está na mão é o que explica por quê.
            cortes.append(CorteDaCausa(dimensao, [], presenca, total))
            continue
        if dimensao.chave == "tema":
            #: O TEMA PELA MESMA CONSULTA DO PAINEL, e isto foi achado de revisão:
            #: o painel "Temas × sentimento" agrupa por
            #: `coalesce(Tema.nome, Mencao.tema_texto)` — o nome do dicionário do
            #: CRM vence a grafia do fornecedor —, e a aba agrupava pelo texto cru.
            #: Os dois ficam lado a lado na mesma tela: rótulos diferentes para o
            #: mesmo mês, e um clique no rótulo do painel mandando ao servidor uma
            #: grafia que o dado não tem.
            linhas = [
                {"rotulo": linha.pop("tema"), **linha}
                for linha in temas_por_sentimento(
                    sessao, lente_id, mes, calibracao, filtro, quantos
                )
            ]
        elif dimensao.chave in _DIMENSOES_DA_TAXONOMIA:
            linhas = _por_taxonomia(
                sessao, dimensao.chave, lente_id, mes, calibracao, filtro, limite
            )
        else:
            linhas = _por_coluna_de_texto(
                sessao,
                #: O ATRIBUTO SEM O PREFIXO "7. ": a mesma pílula para o mock e
                #: para a planilha real, e o clique filtra pelo mesmo rótulo.
                ATRIBUTO_SEM_PREFIXO
                if dimensao.chave == "atributo"
                #: E A CONCESSIONÁRIA PELO NOME DO CADASTRO — ver
                #: `coluna_da_dimensao`, que registra por que.
                else coluna_da_dimensao(dimensao.campo),
                "rotulo",
                lente_id,
                mes,
                calibracao,
                filtro,
                limite,
            )
        cortes.append(CorteDaCausa(dimensao, linhas, presenca, total))
    return cortes


def quantas_com(
    sessao: Session,
    coluna,
    valor: str,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
) -> int:
    """Quantas menções do mês têm aquele valor naquela coluna.

    ACHADO DE REVISÃO, e a lição é sobre reusar a resposta errada: o indicador
    "Figuras públicas" somava as linhas do CORTE por perfil, que devolve os seis
    valores de MAIOR VOLUME. Com sete grafias de perfil na frente, "Figura
    pública" cairia fora da lista e o indicador mostraria zero — um zero que não
    significa "não houve", e ninguém teria como saber disso olhando a tela.

    CORTE E CONTAGEM RESPONDEM PERGUNTAS DIFERENTES: o corte serve a um painel e
    por isso é limitado; a contagem de um valor específico não pode ser.
    """
    total = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes == primeiro_dia(mes),
            coluna == valor,
            *so_fontes_ligadas(calibracao),
            *condicoes_do_filtro(filtro),
        )
    )
    return int(total or 0)


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
    ordenar_pelo_negativo: bool = False,
) -> list[dict]:
    """Onde o mês pesou, por estado.

    `ordenar_pelo_negativo` É PARA O INDICADOR `UF mais negativa`, e existe por
    um achado de revisão: lê-lo da lista ordenada por VOLUME fazia a resposta sair
    de dentre as seis UFs maiores, e a mais negativa do mês pode ser a sétima —
    uma UF pequena com tudo negativo é exatamente o caso que interessa.
    """
    return _por_coluna_de_texto(
        sessao,
        Mencao.uf,
        "uf",
        lente_id,
        mes,
        calibracao,
        filtro,
        quantos,
        ordenar_pelo_negativo=ordenar_pelo_negativo,
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
    so_do_tier: str | None = None,
) -> list[dict]:
    """Os veículos com mais matérias no mês — "quem é a cobertura" desta
    lente, e o saldo de sentimento de cada um.

    `so_do_tier` restringe a um tier (`muito_relevante` para o Top 10 Tier 1 do
    painel "Tier do veículo × sentimento"), somado ao filtro da tela.

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
            *((Mencao.tier == so_do_tier,) if so_do_tier else ()),
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

    PELO NOME DO CADASTRO (`CONCESSIONARIA`), como `_concessionarias` e o
    seletor ao lado. Esta leitura ficou de fora da `0099` e a revisão do Codex a
    encontrou: a Corsan ocupava DUAS posições do ranking com metade do volume
    cada, e o "mês de pico" era calculado sobre cada metade — então a tela podia
    apontar março numa linha e maio na outra para a mesma operação.

    `outerjoin` E NÃO `join`, pela razão de sempre: "Águas do Rio" são dois
    blocos, fica sem chave de propósito, e precisa continuar no ranking.
    """
    consulta = (
        select(CONCESSIONARIA, Mencao.mes, func.count())
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .where(
            ScoreFonte.lente_id == lente_id,
            Mencao.mes.in_(list(meses)),
            CONCESSIONARIA.is_not(None),
            *so_fontes_ligadas(calibracao),
        )
        .group_by(CONCESSIONARIA, Mencao.mes)
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
