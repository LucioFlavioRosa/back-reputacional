"""Rotas HTTP das interações.

A camada mais fina do contexto: monta o Recorte, chama o caso de uso, serializa
a resposta. Nenhuma regra de negócio mora aqui.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencias import (
    UsuarioLogado,
    UsuarioQueEscreve,
    obter_usuario_atual,
)
from app.banco.repositorio_interacoes import (
    RepositorioSQL,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import consultar_interacoes, editar_interacao, registrar_interacao
from app.dominio.recorte import Recorte
from app.esquemas.interacoes import (
    InteracaoEdicao,
    InteracaoEntrada,
    InteracaoSaida,
    PaginaDeInteracoes,
)

# A autenticação é dependência do router inteiro: nenhuma rota daqui é pública.
# As rotas de leitura também recebem `UsuarioLogado` — não por redundância, mas
# porque precisam do escopo e da permissão de ver campos sensíveis. O FastAPI
# resolve a dependência uma vez por requisição e reaproveita.
rotas = APIRouter(
    prefix="/api/interacoes",
    tags=["interacoes"],
    # `obter_usuario_atual` já encadeia provisionamento, limite de taxa e
    # autorização, nessa ordem. Uma dependência só, resolvida uma vez por
    # requisição.
    dependencies=[Depends(obter_usuario_atual)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido


def obter_recorte(
    periodo: Annotated[
        str | None,
        Query(description="ano-corrente | ultimos-30 | ultimos-90 | ultimos-180"),
    ] = None,
    de: Annotated[date | None, Query()] = None,
    ate: Annotated[date | None, Query()] = None,
    frente: Annotated[str | None, Query()] = None,
    area: Annotated[
        str | None,
        Query(deprecated=True, description="apelido de `frente`"),
    ] = None,
    unidade: Annotated[str | None, Query()] = None,
    uf: Annotated[
        str | None,
        Query(description="sigla, NA (nacional) ou IN (internacional)"),
    ] = None,
    esfera: Annotated[str | None, Query()] = None,
    # Sem `le`: quantos níveis existem é o que estiver em `relevancia`, e
    # um teto aqui voltaria a ser uma cópia que envelhece sozinha.
    tier: Annotated[int | None, Query(ge=1)] = None,
    clima: Annotated[str | None, Query()] = None,
    resultado: Annotated[str | None, Query()] = None,
    status_: Annotated[
        str | None,
        Query(alias="status", description="código de um status específico"),
    ] = None,
    grupo: Annotated[str | None, Query(description="resolvido | aberto | declinado")] = None,
    entidade: Annotated[str | None, Query(description="id ou nome exato da instituição")] = None,
    subtipo: Annotated[str | None, Query(description="tipo de investidor")] = None,
    porta_voz: Annotated[UUID | None, Query(alias="portaVoz")] = None,
    pessoa: Annotated[UUID | None, Query()] = None,
    tags: Annotated[str | None, Query(description="separadas por vírgula; OR entre elas")] = None,
    q: Annotated[str | None, Query(description="busca livre")] = None,
) -> Recorte:
    """Monta o Recorte a partir da query string.

    É a única porta de entrada dos filtros: qualquer rota que precise deles
    declara esta dependência, e todas passam a aceitar exatamente o mesmo
    conjunto — que é o requisito do contrato da API.
    """
    return Recorte.construir(
        periodo=periodo,
        de=de,
        ate=ate,
        frente=frente or area,
        unidade=unidade,
        uf=uf.upper() if uf else None,
        esfera=esfera,
        tier=tier,
        clima=clima,
        resultado=resultado,
        status=status_,
        grupo_status=grupo,
        entidade=entidade,
        subtipo=subtipo,
        porta_voz=porta_voz,
        pessoa=pessoa,
        tags=tags,
        busca=q,
    )


RecorteAtual = Annotated[Recorte, Depends(obter_recorte)]


@rotas.get("")
def listar(
    sessao: Sessao,
    usuario: UsuarioLogado,
    recorte: RecorteAtual,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=200)] = 50,
    ordenacao: Annotated[
        str, Query(description="campo, com '-' para descendente")
    ] = "-data_interacao",
) -> PaginaDeInteracoes:
    """A base de registros do recorte corrente."""
    resultado = consultar_interacoes.listar(
        RepositorioSQL(sessao),
        recorte=recorte,
        escopo=usuario.escopo,
        busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
        pagina=pagina,
        tamanho=tamanho,
        ordenacao=ordenacao,
    )
    return PaginaDeInteracoes(
        itens=[
            InteracaoSaida.de_dominio(i, ve_campos_sensiveis=usuario.ve_campos_sensiveis)
            for i in resultado.itens
        ],
        total=resultado.total,
        pagina=resultado.pagina,
        tamanho=resultado.tamanho,
        paginas=resultado.paginas,
        filtros_ativos=recorte.quantidade_de_filtros,
    )


@rotas.post("", status_code=status.HTTP_201_CREATED)
def criar(
    sessao: Sessao, usuario: UsuarioQueEscreve, entrada: InteracaoEntrada
) -> InteracaoSaida:
    criada = registrar_interacao.registrar(
        RepositorioSQL(sessao), interacao=entrada.para_dominio(), usuario=usuario
    )
    return InteracaoSaida.de_dominio(criada, ve_campos_sensiveis=usuario.ve_campos_sensiveis)


@rotas.get("/{id}")
def obter(sessao: Sessao, usuario: UsuarioLogado, id: UUID) -> InteracaoSaida:
    """A ficha do registro."""
    interacao = consultar_interacoes.obter(
        RepositorioSQL(sessao), id=id, escopo=usuario.escopo
    )
    return InteracaoSaida.de_dominio(interacao, ve_campos_sensiveis=usuario.ve_campos_sensiveis)


@rotas.patch("/{id}")
def editar(
    sessao: Sessao, usuario: UsuarioQueEscreve, id: UUID, edicao: InteracaoEdicao
) -> InteracaoSaida:
    repositorio = RepositorioSQL(sessao)

    atual = consultar_interacoes.obter(repositorio, id=id, escopo=usuario.escopo)
    alteracoes = edicao.alteracoes(frente_atual=atual.frente)

    atualizada = editar_interacao.editar(
        repositorio, sessao, id=id, alteracoes=alteracoes, usuario=usuario
    )
    return InteracaoSaida.de_dominio(atualizada, ve_campos_sensiveis=usuario.ve_campos_sensiveis)


@rotas.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def arquivar(sessao: Sessao, usuario: UsuarioQueEscreve, id: UUID) -> None:
    """Soft delete: sai das consultas, permanece no banco."""
    editar_interacao.arquivar(RepositorioSQL(sessao), sessao, id=id, usuario=usuario)
