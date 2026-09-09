"""Trilha de exportação da Base: quem levou o quê, e quanto.

ERA `api/relatorios.py`, com a geração do documento impresso ao lado. A tela de
relatório saiu do produto; sobrou o controle de segurança que o plano listava
desde o começo — "Export CSV: quem exportou, qual recorte, quantas linhas".

O CSV é montado no navegador a partir da listagem já baixada, e saía sem evento
nenhum: um botão, um arquivo, o recorte inteiro.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.api.dependencias import UsuarioLogado, exigir_portal_crm
from app.api.interacoes import obter_recorte
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import registrar_exportacao
from app.dominio.recorte import Recorte

rotas = APIRouter(
    prefix="/api/exportacoes",
    tags=["exportacoes"],
    # `exigir_portal_crm`, e não `obter_usuario_atual`: estas rotas são do CRM
    # dos Stakeholders, e quem não abre esse portal não as alcança.
    #
    # Fica no APIRouter, e não em cada rota: uma rota nova nasce protegida em
    # vez de depender de alguém lembrar. `exigir_portal_crm` já resolve o
    # usuário, então nada se perde.
    dependencies=[Depends(exigir_portal_crm)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido
RecorteAtual = Annotated[Recorte, Depends(obter_recorte)]


class ExportacaoSaida(BaseModel):
    id: str
    criado_em: str
    total_de_registros: int


class HistoricoSaida(BaseModel):
    id: str
    criado_em: str
    criado_por: str
    total_de_registros: int
    resumo_do_recorte: str


@rotas.post("", status_code=status.HTTP_201_CREATED)
def registrar(
    sessao: Sessao, usuario: UsuarioLogado, recorte: RecorteAtual
) -> ExportacaoSaida:
    """Registra uma exportação CSV da tela Base.

    O recorte vem da query string, pela MESMA dependência que a listagem usa —
    recebê-lo no corpo abriria a porta para a exportação registrar um recorte e
    levar outro.

    Vale a ressalva de sempre: é trilha, não barreira. Um cliente modificado
    baixa a listagem e monta o arquivo sem chamar isto.
    """
    exportacao = registrar_exportacao.registrar(
        sessao, recorte=recorte, usuario=usuario
    )
    return ExportacaoSaida(
        id=str(exportacao.id),
        criado_em=exportacao.criado_em.isoformat(),
        total_de_registros=exportacao.total_de_registros,
    )


@rotas.get("/historico")
def historico(
    sessao: Sessao,
    usuario: UsuarioLogado,
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[HistoricoSaida]:
    """Quem exportou o quê. Exige `administra_acessos`."""
    return [
        HistoricoSaida(
            id=str(linha.id),
            criado_em=linha.criado_em.isoformat(),
            criado_por=linha.criado_por,
            total_de_registros=linha.total_de_registros,
            resumo_do_recorte=linha.resumo_do_recorte,
        )
        for linha in registrar_exportacao.historico(
            sessao, solicitante=usuario, limite=limite
        )
    ]
