"""O único lugar do sistema que traduz um Recorte para SQL.

Todo endpoint de leitura — a base, os KPIs, as séries mensais, os rankings, o
mapa — passa por aqui. É isso que garante que o número do KPI bate com o da
tabela: existe uma implementação de filtro, não oito.

Nenhum filtro usa `join` na consulta principal. Códigos de dicionário viram
subconsulta escalar e relações N-N viram `exists`, para que o total do recorte
nunca seja inflado por duplicação de linha.

O `escopo` e o `busca_em_campos_sensiveis` são argumentos **obrigatórios** de
propósito. Nenhum dos dois vem da query string — são o alcance que o usuário
não controla — e torná-los obrigatórios faz com que esquecê-los seja
`TypeError` na importação, e não uma leitura sem restrição descoberta em
produção.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, false, or_, select

from app.banco.tabelas_catalogo import (
    Clima,
    Esfera,
    Frente,
    Resultado,
    Status,
    Tema,
    TipoInvestidor,
    UnidadeNegocio,
)
from app.banco.tabelas_interacoes import (
    InteracaoPessoaAegea,
    InteracaoRegistro,
    InteracaoTema,
    InvestidoresRegistro,
)
from app.banco.tabelas_stakeholders import (
    Instituicao,
    Interlocutor,
)
from app.dominio.erros import RegraViolada
from app.dominio.identidade import Escopo
from app.dominio.interacao import PAPEL_PORTA_VOZ
from app.dominio.recorte import Recorte
from app.dominio.texto import normalizar


def _id_do_codigo(tabela: type, codigo: str) -> ColumnElement[int]:
    """Resolve `codigo` para `id` sem entrar como join na consulta principal."""
    return select(tabela.id).where(tabela.codigo == codigo).scalar_subquery()


def _condicoes_de_escopo(escopo: Escopo) -> list[ColumnElement[bool]]:
    """O alcance do usuário, que a query string não consegue afrouxar.

    Cada dimensão restringe apenas a si mesma; dimensões sem concessão não
    entram. O caso perigoso é o de quem é restrito e não recebeu concessão
    nenhuma: aqui isso vira `false`, não "sem filtro".
    """
    if escopo.irrestrito:
        return []

    if escopo.nao_alcanca_nada:
        return [false()]

    onde: list[ColumnElement[bool]] = []

    if escopo.frentes:
        onde.append(
            InteracaoRegistro.frente_id.in_(
                select(Frente.id).where(Frente.codigo.in_(sorted(escopo.frentes)))
            )
        )

    # `unidade_negocio` não tem coluna `codigo`: o nome é a chave natural, e é
    # por ele que o Recorte também filtra.
    if escopo.unidades:
        onde.append(
            InteracaoRegistro.unidade_negocio_id.in_(
                select(UnidadeNegocio.id).where(
                    UnidadeNegocio.nome.in_(sorted(escopo.unidades))
                )
            )
        )

    return onde


def condicoes(
    recorte: Recorte,
    *,
    escopo: Escopo,
    busca_em_campos_sensiveis: bool,
    incluir_arquivadas: bool = False,
) -> list[ColumnElement[bool]]:
    """Traduz o Recorte e o escopo do usuário para uma lista de condições `where`.

    A lista pode ser aplicada a qualquer consulta que tenha `interacao` como
    tabela principal — inclusive às agregações que ainda serão escritas.

    O escopo entra **depois** dos filtros pedidos e nunca no lugar deles: o
    usuário refina o que já lhe é permitido, jamais o amplia.

    `busca_em_campos_sensiveis` decide se `q=` varre `relato`. Esconder o campo
    do payload e mantê-lo pesquisável seria um oráculo: sem receber o texto, o
    usuário descobriria o conteúdo por tentativa e erro, uma palavra por vez.
    """
    onde: list[ColumnElement[bool]] = list(_condicoes_de_escopo(escopo))

    if not incluir_arquivadas:
        onde.append(InteracaoRegistro.arquivado_em.is_(None))
        onde.append(InteracaoRegistro.visivel.is_(True))

    # -- período -------------------------------------------------------------
    if recorte.periodo.de:
        onde.append(InteracaoRegistro.data_interacao >= recorte.periodo.de)
    if recorte.periodo.ate:
        onde.append(InteracaoRegistro.data_interacao <= recorte.periodo.ate)

    # -- dicionários ---------------------------------------------------------
    if recorte.frente:
        onde.append(InteracaoRegistro.frente_id == _id_do_codigo(Frente, recorte.frente))
    if recorte.esfera:
        onde.append(InteracaoRegistro.esfera_id == _id_do_codigo(Esfera, recorte.esfera))
    if recorte.clima:
        onde.append(InteracaoRegistro.clima_id == _id_do_codigo(Clima, recorte.clima))
    if recorte.resultado:
        onde.append(
            InteracaoRegistro.resultado_id == _id_do_codigo(Resultado, recorte.resultado)
        )

    # Status e grupo são filtros distintos: "declinado" é código de status *e*
    # nome de grupo. Os dois podem coexistir — a tela de Status filtra pelo
    # grupo e o chip dentro do card refina para um status específico.
    if recorte.status:
        onde.append(
            InteracaoRegistro.status_id.in_(
                select(Status.id).where(Status.codigo == recorte.status)
            )
        )
    if recorte.grupo_status:
        onde.append(
            InteracaoRegistro.status_id.in_(
                select(Status.id).where(Status.grupo == recorte.grupo_status)
            )
        )

    if recorte.unidade:
        onde.append(
            InteracaoRegistro.unidade_negocio_id
            == select(UnidadeNegocio.id)
            .where(UnidadeNegocio.nome == recorte.unidade)
            .scalar_subquery()
        )

    # -- campos diretos ------------------------------------------------------
    if recorte.uf:
        onde.append(InteracaoRegistro.uf == recorte.uf)
    if recorte.tier is not None:
        onde.append(InteracaoRegistro.tier == recorte.tier)
    if recorte.pessoa:
        onde.append(InteracaoRegistro.interlocutor_id == recorte.pessoa)

    # -- instituição: aceita id ou nome exato --------------------------------
    if recorte.entidade:
        try:
            onde.append(InteracaoRegistro.instituicao_id == UUID(recorte.entidade))
        except ValueError:
            onde.append(
                InteracaoRegistro.instituicao_id.in_(
                    select(Instituicao.id).where(Instituicao.nome == recorte.entidade)
                )
            )

    # -- relações: exists, para não duplicar linha ---------------------------
    if recorte.porta_voz:
        onde.append(
            exists(
                select(InteracaoPessoaAegea.interacao_id).where(
                    and_(
                        InteracaoPessoaAegea.interacao_id == InteracaoRegistro.id,
                        InteracaoPessoaAegea.pessoa_aegea_id == recorte.porta_voz,
                        InteracaoPessoaAegea.papel == PAPEL_PORTA_VOZ,
                    )
                )
            )
        )

    if recorte.tags:
        # OR entre as tags, como manda o contrato: o registro entra se tiver
        # qualquer uma delas.
        onde.append(
            exists(
                select(InteracaoTema.interacao_id).where(
                    and_(
                        InteracaoTema.interacao_id == InteracaoRegistro.id,
                        InteracaoTema.tema_id.in_(
                            select(Tema.id).where(Tema.nome.in_(recorte.tags))
                        ),
                    )
                )
            )
        )

    if recorte.subtipo:
        onde.append(
            exists(
                select(InvestidoresRegistro.interacao_id).where(
                    and_(
                        InvestidoresRegistro.interacao_id == InteracaoRegistro.id,
                        InvestidoresRegistro.tipo_investidor_id
                        == _id_do_codigo(TipoInvestidor, recorte.subtipo),
                    )
                )
            )
        )

    # -- busca livre ---------------------------------------------------------
    #
    # Os campos de texto usam ILIKE com curinga dos dois lados, servido pelos
    # índices de trigrama criados em `migrations/0004_interacoes.sql` — sem eles
    # isto seria varredura sequencial.
    #
    # Nome de instituição e de pessoa buscam pela coluna normalizada, a mesma
    # que a importação usa para deduplicar: assim "Radames" encontra
    # "Radamés", e quem digita sem acento não fica sem resultado.
    if recorte.busca:
        termo = f"%{recorte.busca.strip()}%"
        termo_normalizado = f"%{normalizar(recorte.busca)}%"

        # `relato` é o campo que `InteracaoSaida` anula para quem não tem
        # `ve_campos_sensiveis` — deixá-lo aqui devolveria por dedução o que a
        # serialização acabou de esconder.
        colunas = [
            InteracaoRegistro.pauta.ilike(termo),
            InteracaoRegistro.encaminhamentos.ilike(termo),
        ]
        if busca_em_campos_sensiveis:
            colunas.append(InteracaoRegistro.relato.ilike(termo))

        onde.append(
            or_(
                *colunas,
                InteracaoRegistro.uf.ilike(termo),
                exists(
                    select(Instituicao.id).where(
                        and_(
                            Instituicao.id == InteracaoRegistro.instituicao_id,
                            Instituicao.nome_normalizado.ilike(termo_normalizado),
                        )
                    )
                ),
                exists(
                    select(Interlocutor.id).where(
                        and_(
                            Interlocutor.id == InteracaoRegistro.interlocutor_id,
                            Interlocutor.nome_normalizado.ilike(termo_normalizado),
                        )
                    )
                ),
            )
        )

    return onde


#: Ordenações aceitas pela listagem. O prefixo "-" inverte.
ORDENACOES: dict[str, ColumnElement] = {
    "data_interacao": InteracaoRegistro.data_interacao,
    "criado_em": InteracaoRegistro.criado_em,
    "tier": InteracaoRegistro.tier,
    "uf": InteracaoRegistro.uf,
}


def ordenar_por(ordenacao: str) -> list[ColumnElement]:
    """Traduz "-data_interacao" para a cláusula `order by`.

    O desempate por `id` mantém a paginação estável quando várias interações
    caem no mesmo dia — o que é comum, já que a granularidade é diária.
    """
    descendente = ordenacao.startswith("-")
    campo = ordenacao.lstrip("-")

    coluna = ORDENACOES.get(campo)
    if coluna is None:
        validos = ", ".join(sorted(ORDENACOES))
        raise RegraViolada(f"Ordenação inválida: {campo!r}. Use {validos}.")

    principal = coluna.desc().nullslast() if descendente else coluna.asc().nullsfirst()
    return [principal, InteracaoRegistro.id.desc()]
