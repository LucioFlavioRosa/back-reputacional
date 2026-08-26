"""Leitura dos cadastros de stakeholders.

A listagem de interações devolve chaves estrangeiras, não nomes. Quem monta a
tela resolve os nomes com estes três diretórios, carregados uma vez — são
poucas centenas de linhas e mudam raramente.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencias import exigir_diretorio
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_stakeholders import (
    Instituicao,
    Interlocutor,
    PessoaAegea,
)

rotas = APIRouter(
    prefix="/api",
    tags=["stakeholders"],
    # `exigir_diretorio`, e não só autenticação: estas três rotas devolvem o
    # mapa de relacionamento inteiro da Aegea — todo jornalista, gestor público
    # e entidade com quem a companhia fala. Para um terceiro isso pode valer
    # mais do que os registros. Não passam por `condicoes()`, então a barreira
    # é o papel.
    dependencies=[Depends(exigir_diretorio)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido


class InstituicaoSaida(BaseModel):
    id: UUID
    nome: str
    tipo: str
    esfera_id: int | None
    uf: str | None
    ativo: bool


class InterlocutorSaida(BaseModel):
    id: UUID
    nome: str
    instituicao_id: UUID | None
    cargo: str | None
    tipo: str | None
    ativo: bool


class PessoaAegeaSaida(BaseModel):
    id: UUID
    nome: str
    cargo: str | None
    eh_porta_voz: bool
    ativo: bool


@rotas.get("/instituicoes", response_model=list[InstituicaoSaida])
def listar_instituicoes(
    sessao: Sessao,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[Instituicao]:
    consulta = select(Instituicao).order_by(Instituicao.nome)
    if not incluir_inativos:
        consulta = consulta.where(Instituicao.ativo.is_(True))
    return list(sessao.scalars(consulta))


@rotas.get("/interlocutores", response_model=list[InterlocutorSaida])
def listar_interlocutores(
    sessao: Sessao,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[Interlocutor]:
    consulta = select(Interlocutor).order_by(Interlocutor.nome)
    if not incluir_inativos:
        consulta = consulta.where(Interlocutor.ativo.is_(True))
    return list(sessao.scalars(consulta))


@rotas.get("/pessoas-aegea", response_model=list[PessoaAegeaSaida])
def listar_pessoas_aegea(
    sessao: Sessao,
    somente_porta_vozes: Annotated[bool, Query()] = False,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[PessoaAegea]:
    """Porta-vozes e equipe. O diretório de porta-vozes filtra por
    `somente_porta_vozes`; o cadastro de interação precisa dos dois."""
    consulta = select(PessoaAegea).order_by(PessoaAegea.nome)
    if somente_porta_vozes:
        consulta = consulta.where(PessoaAegea.eh_porta_voz.is_(True))
    if not incluir_inativos:
        consulta = consulta.where(PessoaAegea.ativo.is_(True))
    return list(sessao.scalars(consulta))
