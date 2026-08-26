"""Leitura dos dicionários. O cadastro carrega tudo numa chamada só."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencias import obter_usuario_atual
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import DICIONARIOS

rotas = APIRouter(
    prefix="/api",
    tags=["catalogo"],
    # Só autenticação. Os dicionários são vocabulário fechado — frentes,
    # status, climas — e sem eles nenhuma tela renderiza rótulo. Não revelam
    # nada sobre com quem a Aegea fala nem sobre o que foi conversado, então
    # ficam fora do escopo de propósito, e não por esquecimento.
    dependencies=[Depends(obter_usuario_atual)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido


@rotas.get("/dicionarios")
def listar_dicionarios(sessao: Sessao) -> dict[str, list[dict[str, Any]]]:
    """Todos os enums administráveis, só os ativos, na ordem de exibição."""
    resposta: dict[str, list[dict[str, Any]]] = {}
    for chave, tabela in DICIONARIOS.items():
        consulta = select(tabela).where(tabela.ativo.is_(True))  # type: ignore[attr-defined]
        if hasattr(tabela, "ordem"):
            consulta = consulta.order_by(tabela.ordem)  # type: ignore[attr-defined]
        else:
            consulta = consulta.order_by(tabela.nome)  # type: ignore[attr-defined]

        resposta[chave] = [
            {
                coluna.name: getattr(linha, coluna.name)
                for coluna in tabela.__table__.columns
                if coluna.name != "ativo"
            }
            for linha in sessao.scalars(consulta)
        ]
    return resposta
