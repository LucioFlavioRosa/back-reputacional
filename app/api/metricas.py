"""As agregações, em HTTP.

`asdict` e nunca `vars`: as dataclasses de `dominio/metricas.py` usam
`slots=True`, e objeto com slots não tem `__dict__`. `vars` levantaria
`TypeError` em tempo de EXECUÇÃO — o teste de importação não pega, e o erro
aparece na resposta da API.

Um endpoint por número da tela, todos sobre o MESMO `Recorte` que a listagem
usa — é a dependência `obter_recorte`, reaproveitada do contexto de interações,
que garante isso. Recortar de forma diferente aqui faria o KPI contar um
conjunto e a tabela outro.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioLogado,
    obter_usuario_atual,
)
from app.api.interacoes import obter_recorte
from app.banco import consultas_metricas as consultas
from app.banco.sessao import SessaoDoPedido
from app.dominio.recorte import Recorte

rotas = APIRouter(
    prefix="/api/metricas",
    tags=["analise"],
    # `obter_usuario_atual` encadeia provisionamento, limite de taxa e
    # autorização. Uma dependência só, resolvida uma vez por requisição.
    dependencies=[Depends(obter_usuario_atual)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido
RecorteAtual = Annotated[Recorte, Depends(obter_recorte)]


class ImprensaSaida(BaseModel):
    total: int
    atendidas: int
    taxa: float


class InvestidoresSaida(BaseModel):
    total: int
    internacionais: int


class Tier1Saida(BaseModel):
    total: int
    percentual: float


class KpisSaida(BaseModel):
    total: int
    institucionais: int
    imprensa: ImprensaSaida
    eventos: int
    investidores: InvestidoresSaida
    legislativo: int
    tier1: Tier1Saida


class StatusSaida(BaseModel):
    codigo: str
    nome: str
    total: int


class GrupoSaida(BaseModel):
    grupo: str
    total: int
    percentual: float
    status_que_compoem: list[StatusSaida]


class FrenteSaida(BaseModel):
    frente: str
    total: int
    denominador: int
    resolvidos: int
    taxa: float


class ResolutividadeSaida(BaseModel):
    taxa: float
    grupos: list[GrupoSaida]
    por_frente: list[FrenteSaida]


class ColunaSaida(BaseModel):
    mes: str
    total: int
    segmentos: dict[str, int]


class PontoSaida(BaseModel):
    uf: str
    total: int


@rotas.get("/kpis")
def kpis(sessao: Sessao, usuario: UsuarioLogado, recorte: RecorteAtual) -> KpisSaida:
    """Os números do cabeçalho do painel."""
    calculado = consultas.kpis(
        sessao,
        recorte,
        escopo=usuario.escopo,
        busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
    )
    return KpisSaida(
        total=calculado.total,
        institucionais=calculado.institucionais,
        imprensa=ImprensaSaida(**asdict(calculado.imprensa)),
        eventos=calculado.eventos,
        investidores=InvestidoresSaida(**asdict(calculado.investidores)),
        legislativo=calculado.legislativo,
        tier1=Tier1Saida(**asdict(calculado.tier1)),
    )


@rotas.get("/resolutividade")
def resolutividade(
    sessao: Sessao, usuario: UsuarioLogado, recorte: RecorteAtual
) -> ResolutividadeSaida:
    calculado = consultas.resolutividade(
        sessao,
        recorte,
        escopo=usuario.escopo,
        busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
    )
    return ResolutividadeSaida(
        taxa=calculado.taxa,
        grupos=[
            GrupoSaida(
                grupo=g.grupo,
                total=g.total,
                percentual=g.percentual,
                status_que_compoem=[StatusSaida(**asdict(s)) for s in g.status_que_compoem],
            )
            for g in calculado.grupos
        ],
        por_frente=[FrenteSaida(**asdict(f)) for f in calculado.por_frente],
    )


@rotas.get("/serie-mensal")
def serie_mensal(
    sessao: Sessao,
    usuario: UsuarioLogado,
    recorte: RecorteAtual,
    segmento: Annotated[str, Query(description="frente | clima | tema")] = "frente",
) -> list[ColunaSaida]:
    """A série empilhada. O painel usa as três dimensões na mesma tela.

    Em `tema`, o total da coluna é a soma das ocorrências, não de registros:
    uma interação com três temas conta três vezes na pilha. Vem do front, e é o
    que faz a altura da barra bater com os segmentos dela.
    """
    return [
        ColunaSaida(**asdict(coluna))
        for coluna in consultas.serie_mensal(
            sessao,
            recorte,
            escopo=usuario.escopo,
            busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
            segmento=segmento,
        )
    ]


@rotas.get("/mapa")
def mapa(sessao: Sessao, usuario: UsuarioLogado, recorte: RecorteAtual) -> list[PontoSaida]:
    return [
        PontoSaida(**asdict(ponto))
        for ponto in consultas.distribuicao_por_uf(
            sessao,
            recorte,
            escopo=usuario.escopo,
            busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
        )
    ]
