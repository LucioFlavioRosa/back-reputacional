"""Gravar traduzindo colisão de índice único em mensagem de gente.

ESTA FUNÇÃO EXISTE POR UMA ORDEM QUE É FÁCIL DE ERRAR: o `add` precisa ficar
DENTRO do savepoint. Um `flush` que falha marca a SESSÃO INTEIRA para
rollback, e o savepoint só a protege se a inserção inteira estiver dentro
dele. Com o `add` de fora, o comando seguinte estoura `PendingRollbackError`
— um erro sem relação aparente com o que a pessoa fez.

Nasceu privada em `app/api/stakeholders.py`, copiada em seis rotas; virou
módulo quando a administração de dicionários passou a precisar dela também.
Mora em `banco/` porque é sobre a sessão e o índice, não sobre HTTP.

`ao_colidir` é a mensagem que a pessoa lê. O banco diria "duplicate key
value violates unique constraint", que não ajuda ninguém a decidir o que
fazer.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dominio.erros import RegraViolada


def gravar[T](sessao: Session, registro: T, *, ao_colidir: str, novo: bool = False) -> T:
    try:
        with sessao.begin_nested():
            if novo:
                sessao.add(registro)
            sessao.flush()
    except IntegrityError as erro:
        raise RegraViolada(ao_colidir) from erro
    return registro
