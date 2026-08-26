"""Casos de uso de edição e arquivamento.

A trilha de auditoria é escrita por gatilho (migration 0005). O gatilho
`auditar_interacao` passou a ser o único escritor de `interacao_auditoria`, e
este módulo apenas altera o agregado.

O motivo: enquanto a aplicação escrevia a auditoria, ela só registrava o que
passasse por ela. Um `update` no cliente SQL — "corrigir uma linha rapidinho" —
alterava o dado e sumia do histórico. No banco, o gatilho vê as duas coisas.

Quem informa o autor é `marcar_autor_na_sessao`, chamada quando a identidade é
resolvida. Sem ela, a alteração ainda é registrada, com autor nulo — que é
justamente como uma alteração por SQL direto aparece.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.dominio.erros import NaoEncontrado
from app.dominio.identidade import UsuarioAtual
from app.dominio.interacao import Interacao
from app.dominio.politica import (
    exigir_permissao_de_edicao,
)
from app.dominio.repositorio import (
    RepositorioDeInteracoes,
)


def editar(
    repositorio: RepositorioDeInteracoes,
    sessao: Session,
    *,
    id: UUID,
    alteracoes: dict[str, Any],
    usuario: UsuarioAtual,
) -> Interacao:
    """Aplica alterações parciais e revalida o agregado.

    `sessao` continua no argumento porque o repositório trabalha dentro dela e
    a transação precisa ser a mesma — é nela que a variável `painel.usuario_id`
    está definida, e é dela que o gatilho lê o autor.
    """
    # O escopo do usuário entra também na escrita: não se edita o que não se
    # enxerga. Sem isso, quem não pode ler um registro poderia alterá-lo às
    # cegas conhecendo só o id.
    interacao = repositorio.obter(id, escopo=usuario.escopo)
    if interacao is None or interacao.arquivada:
        raise NaoEncontrado(f"Interação {id} não encontrada.")

    exigir_permissao_de_edicao(usuario, interacao)

    interacao.alterar(**alteracoes)
    return repositorio.atualizar(interacao)


def arquivar(
    repositorio: RepositorioDeInteracoes,
    sessao: Session,
    *,
    id: UUID,
    usuario: UsuarioAtual,
) -> None:
    """Soft delete. Nada some do banco — o registro sai das consultas.

    O gatilho registra isto como qualquer outra alteração: `arquivado_em` mudou
    de nulo para uma data. Não é preciso caso especial.
    """
    interacao = repositorio.obter(id, escopo=usuario.escopo)
    if interacao is None or interacao.arquivada:
        raise NaoEncontrado(f"Interação {id} não encontrada.")

    exigir_permissao_de_edicao(usuario, interacao)

    interacao.arquivado_em = datetime.now(UTC)
    repositorio.atualizar(interacao)
