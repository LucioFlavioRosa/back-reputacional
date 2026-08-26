"""As agregações, em SQL.

A REGRA QUE SUSTENTA TUDO AQUI

Toda consulta deste módulo aplica `condicoes()` — o mesmo tradutor de `Recorte`
que a listagem usa. É isso, e só isso, que faz o número do KPI bater com o da
tabela: existe uma implementação de filtro, não oito.

Escrever um `where` à mão em qualquer função abaixo quebraria a garantia em
silêncio — o KPI passaria a contar um conjunto e a tabela outro, e a divergência
apareceria como "o sistema está com número errado", sem ninguém saber onde.

SOBRE `join` E DUPLICAÇÃO

`frente` e `status` são 1-para-N a partir da interação: cada registro tem
exatamente um de cada, então juntá-los não infla contagem. Tema e porta-voz são
N-N e NÃO podem entrar por `join` numa contagem — quando forem necessários,
entram por subconsulta, como `filtros_sql` já faz.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.banco.filtros_sql import condicoes
from app.banco.tabelas_catalogo import (
    Clima,
    Frente,
    Status,
    Tema,
)
from app.banco.tabelas_interacoes import (
    InteracaoRegistro,
    InteracaoTema,
)
from app.dominio.erros import RegraViolada
from app.dominio.identidade import Escopo
from app.dominio.metricas import (
    ColunaMensal,
    GrupoDeResolucao,
    ImprensaKpi,
    InvestidoresKpi,
    Kpis,
    PontoNoMapa,
    Resolutividade,
    ResolutividadeDaFrente,
    StatusDoGrupo,
    Tier1Kpi,
)
from app.dominio.recorte import Recorte

#: Governo e Parceiros são apresentados juntos: compartilham a mesma extensão e
#: o painel os trata como uma linha só.
FRENTES_INSTITUCIONAIS = ("governo", "parceiros")

#: `IN` é o código de abrangência internacional, no domínio `abrangencia`.
INTERNACIONAL = "IN"

#: Declinado sai do denominador da resolutividade: não foi resolvido nem está
#: aberto — foi recusado, e contar como não-resolvido puniria a equipe por uma
#: decisão que foi dela.
GRUPO_DECLINADO = "declinado"


def _base(recorte: Recorte, escopo: Escopo, busca_em_campos_sensiveis: bool):
    """O `from` + `where` compartilhado por todas as agregações."""
    return (
        select(InteracaoRegistro)
        .join(Frente, Frente.id == InteracaoRegistro.frente_id)
        .join(Status, Status.id == InteracaoRegistro.status_id)
        .where(
            *condicoes(
                recorte,
                escopo=escopo,
                busca_em_campos_sensiveis=busca_em_campos_sensiveis,
            )
        )
    )


def _quantos(condicao: ColumnElement[bool] | None = None):
    """`count(*) filter (where ...)` — uma varredura para todos os números."""
    if condicao is None:
        return func.count()
    return func.count().filter(condicao)


def kpis(
    sessao: Session,
    recorte: Recorte,
    *,
    escopo: Escopo,
    busca_em_campos_sensiveis: bool,
) -> Kpis:
    """Os números do cabeçalho, em UMA consulta.

    Um `select` por KPI seria mais legível e sete vezes mais caro — e, pior,
    daria sete fotografias de momentos diferentes: entre a primeira e a última,
    alguém pode ter cadastrado. Contar tudo de uma vez torna o conjunto
    coerente por construção.
    """
    linha = sessao.execute(
        _base(recorte, escopo, busca_em_campos_sensiveis).with_only_columns(
            _quantos().label("total"),
            _quantos(Frente.codigo.in_(FRENTES_INSTITUCIONAIS)).label("institucionais"),
            _quantos(Frente.codigo == "imprensa").label("imprensa_total"),
            _quantos(
                (Frente.codigo == "imprensa") & (Status.grupo == "resolvido")
            ).label("imprensa_atendidas"),
            _quantos(Frente.codigo == "eventos").label("eventos"),
            _quantos(Frente.codigo == "investidores").label("investidores_total"),
            _quantos(
                (Frente.codigo == "investidores")
                & (InteracaoRegistro.uf == INTERNACIONAL)
            ).label("investidores_internacionais"),
            _quantos(Frente.codigo == "legislativo").label("legislativo"),
            _quantos(InteracaoRegistro.tier == 1).label("tier1"),
        )
    ).one()

    return Kpis(
        total=linha.total,
        institucionais=linha.institucionais,
        imprensa=ImprensaKpi(
            total=linha.imprensa_total,
            atendidas=linha.imprensa_atendidas,
            taxa=_divisao(linha.imprensa_atendidas, linha.imprensa_total),
        ),
        eventos=linha.eventos,
        investidores=InvestidoresKpi(
            total=linha.investidores_total,
            internacionais=linha.investidores_internacionais,
        ),
        legislativo=linha.legislativo,
        tier1=Tier1Kpi(
            total=linha.tier1,
            percentual=_divisao(linha.tier1, linha.total),
        ),
    )


def resolutividade(
    sessao: Session,
    recorte: Recorte,
    *,
    escopo: Escopo,
    busca_em_campos_sensiveis: bool,
) -> Resolutividade:
    """Taxa de resolução, por grupo de status e por frente."""
    por_status = sessao.execute(
        _base(recorte, escopo, busca_em_campos_sensiveis)
        .with_only_columns(
            Status.grupo, Status.codigo, Status.nome, _quantos().label("total")
        )
        .group_by(Status.grupo, Status.codigo, Status.nome)
    ).all()

    grupos: dict[str, list[StatusDoGrupo]] = {}
    for linha in por_status:
        grupos.setdefault(linha.grupo, []).append(
            StatusDoGrupo(codigo=linha.codigo, nome=linha.nome, total=linha.total)
        )

    total = sum(linha.total for linha in por_status)

    # Os TRÊS grupos, sempre, mesmo zerados.
    #
    # Omitir os vazios parecia econômico e diverge do front, que sempre monta os
    # três. A tela os mostra lado a lado: um recorte em que ninguém declinou
    # faria o card de declinados desaparecer, e a pessoa leria isso como "o
    # sistema não calculou" em vez de "foi zero". Ordem fixa pelo mesmo motivo —
    # trocar de lugar entre um recorte e outro confunde a leitura.
    montados = [
        GrupoDeResolucao(
            grupo=grupo,
            total=sum(s.total for s in grupos.get(grupo, [])),
            percentual=_divisao(sum(s.total for s in grupos.get(grupo, [])), total),
            status_que_compoem=sorted(grupos.get(grupo, []), key=lambda s: -s.total),
        )
        for grupo in ("resolvido", "aberto", GRUPO_DECLINADO)
    ]

    resolvidos = next((g.total for g in montados if g.grupo == "resolvido"), 0)
    declinados = next((g.total for g in montados if g.grupo == GRUPO_DECLINADO), 0)

    por_frente = sessao.execute(
        _base(recorte, escopo, busca_em_campos_sensiveis)
        .with_only_columns(
            Frente.codigo,
            _quantos().label("total"),
            _quantos(Status.grupo == "resolvido").label("resolvidos"),
            _quantos(Status.grupo == GRUPO_DECLINADO).label("declinados"),
        )
        .group_by(Frente.codigo)
    ).all()

    return Resolutividade(
        # O denominador desconta os declinados aqui E na taxa por frente. Já
        # divergiu uma vez, com as duas aparecendo lado a lado sem fechar.
        taxa=_divisao(resolvidos, total - declinados),
        grupos=montados,
        por_frente=sorted(
            (
                ResolutividadeDaFrente(
                    frente=linha.codigo,
                    total=linha.total,
                    denominador=linha.total - linha.declinados,
                    resolvidos=linha.resolvidos,
                    taxa=_divisao(linha.resolvidos, linha.total - linha.declinados),
                )
                for linha in por_frente
            ),
            key=lambda f: -f.total,
        ),
    )


#: As três dimensões que o painel empilha hoje.
#:
#: `frente` e `clima` são 1-para-1 com a interação; `tema` é N-N, e é isso que
#: torna a função genérica em vez de três consultas parecidas.
SEGMENTOS = ("frente", "clima", "tema")


def serie_mensal(
    sessao: Session,
    recorte: Recorte,
    *,
    escopo: Escopo,
    busca_em_campos_sensiveis: bool,
    segmento: str = "frente",
) -> list[ColunaMensal]:
    """Contagem por mês, empilhada pela dimensão pedida.

    O painel empilha por frente, clima E tema, e por isso o segmento é
    parâmetro: fixá-lo em frente faria a série de clima vir com "imprensa: 2"
    onde a tela espera "positivo: 1, negativo: 1".

    SOBRE O TOTAL, que não é o número de registros:

    Em tema, uma interação com três temas conta TRÊS vezes. É deliberado e vem
    do front: a coluna é uma pilha, e a altura dela é a soma dos segmentos. Ler
    "total" aqui como "quantos registros houve no mês" daria número errado.

    Os meses vazios NÃO são preenchidos aqui. O front tem `completarMeses`, e
    preencher nos dois lugares daria buracos preenchidos duas vezes ou nenhuma,
    dependendo de qual caminho a tela usasse.
    """
    if segmento not in SEGMENTOS:
        raise RegraViolada(
            f"Segmento inválido: {segmento!r}. Use um de {', '.join(SEGMENTOS)}."
        )

    mes = func.to_char(InteracaoRegistro.data_interacao, "YYYY-MM").label("mes")
    consulta = _base(recorte, escopo, busca_em_campos_sensiveis)

    if segmento == "frente":
        rotulo = Frente.codigo
    elif segmento == "clima":
        # `join` interno: interação sem clima não entra em segmento nenhum, que
        # é exatamente o que o front faz (`i.clima ? [i.clima] : []`).
        consulta = consulta.join(Clima, Clima.id == InteracaoRegistro.clima_id)
        rotulo = Clima.codigo
    else:
        # Tema DUPLICA linha de propósito: é o que faz uma interação com três
        # temas contar três vezes na pilha.
        consulta = consulta.join(
            InteracaoTema, InteracaoTema.interacao_id == InteracaoRegistro.id
        ).join(Tema, Tema.id == InteracaoTema.tema_id)
        rotulo = Tema.nome

    linhas = sessao.execute(
        consulta.with_only_columns(mes, rotulo.label("rotulo"), _quantos().label("total"))
        .group_by(mes, rotulo)
        .order_by(mes)
    ).all()

    colunas: dict[str, dict[str, int]] = {}
    for linha in linhas:
        colunas.setdefault(linha.mes, {})[linha.rotulo] = linha.total

    return [
        ColunaMensal(mes=chave, total=sum(segmentos.values()), segmentos=segmentos)
        for chave, segmentos in sorted(colunas.items())
    ]


def distribuicao_por_uf(
    sessao: Session,
    recorte: Recorte,
    *,
    escopo: Escopo,
    busca_em_campos_sensiveis: bool,
) -> list[PontoNoMapa]:
    """Contagem por abrangência, INCLUINDO `NA` e `IN`.

    Não têm capital para virar bolha no mapa, e é o COMPONENTE do mapa que
    decide não desenhá-los. Filtrar aqui apagaria um número que a tela mostra: o
    ranking ao lado, na mesma tela e sobre o mesmo recorte, precisa deles.
    """
    linhas = sessao.execute(
        _base(recorte, escopo, busca_em_campos_sensiveis)
        .with_only_columns(InteracaoRegistro.uf, _quantos().label("total"))
        .group_by(InteracaoRegistro.uf)
        .order_by(_quantos().desc())
    ).all()

    return [PontoNoMapa(uf=linha.uf, total=linha.total) for linha in linhas]


def _divisao(parte: int, todo: int) -> float:
    """Divisão que não estoura, e devolve 0 quando não há base.

    Não é detalhe: `taxa` aparece na tela como percentual, e um recorte vazio é
    situação normal — basta filtrar por uma frente sem registros no período.
    """
    return parte / todo if todo else 0.0
