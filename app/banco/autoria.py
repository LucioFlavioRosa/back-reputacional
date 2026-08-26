"""Quem está alterando, do ponto de vista do banco.

O gatilho `auditar_interacao` (migration 0005) escreve a auditoria, mas não tem
como saber quem pediu a alteração: para o Postgres, toda requisição chega pela
mesma conta de aplicação. Esta é a ponte — a aplicação carimba o autor na
transação, e o gatilho lê de lá.

Se ninguém carimbar, a alteração ainda é auditada, com autor nulo. É assim que
uma alteração feita por SQL direto aparece: registrada, e explicitamente sem
dono conhecido.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

#: `painel.` porque o Postgres exige um prefixo com ponto em parâmetro
#: personalizado — sem ele, `set_config` recusa o nome.
PARAMETRO = "painel.usuario_id"


def marcar_autor_na_sessao(sessao: Session, usuario_id: UUID) -> None:
    """Carimba o autor na transação corrente.

    `set_config(..., true)` em vez de `SET LOCAL`: o terceiro argumento faz o
    valor durar só até o fim da transação, e a forma de função aceita parâmetro
    ligado. `SET LOCAL` não aceita — o valor teria de ser interpolado no texto
    do comando, que é como se escreve uma injeção de SQL sem querer.
    """
    sessao.execute(
        text("select set_config(:nome, :valor, true)"),
        {"nome": PARAMETRO, "valor": str(usuario_id)},
    )
