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

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.dominio.erros import NaoEncontrado
from app.dominio.identidade import UsuarioAtual
from app.dominio.interacao import (
    Interacao,
    ParticipanteDaOutraParte,
)
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
    # `para_edicao=True` trava a linha: duas edições simultâneas da mesma
    # agenda liam o estado antigo e as duas gravavam, e a segunda estourava no
    # índice do participante principal. Agora a segunda espera e lê o novo.
    interacao = repositorio.obter(id, escopo=usuario.escopo, para_edicao=True)
    if interacao is None or interacao.arquivada:
        raise NaoEncontrado(f"Interação {id} não encontrada.")

    exigir_permissao_de_edicao(usuario, interacao)

    interacao.alterar(**_reconciliar_o_principal(interacao, alteracoes))
    return repositorio.atualizar(interacao)


def _reconciliar_o_principal(
    interacao: Interacao, alteracoes: dict[str, object]
) -> dict[str, object]:
    """Decide se manda a LISTA ou a COLUNA, pelo que o PATCH enviou.

    Quem representa a outra parte está escrito em dois lugares — a marca
    `principal` na lista de participantes e `interacao.interlocutor_id` — e os
    dois existem porque 67 usos dependem da coluna. Só que "qual dos dois
    manda" não é uma propriedade do agregado: depende do que a requisição
    QUIS mudar, e esse é um fato que só existe aqui.

    O repositório não pode decidir, e tentar fez o bug aparecer duas vezes:

      - a lista sempre mandando fez `PATCH {"interlocutor_id": X}` virar um
        no-op silencioso, com 200 na resposta e nada alterado — quebrando a
        edição de interlocutor da tela que já existe;
      - a coluna mandando quando a lista chegava vazia fez
        `PATCH {"outra_parte": []}` RESSUSCITAR o principal que a pessoa
        acabara de tirar.

    Os dois casos são indistinguíveis no agregado pronto: lista vazia é lista
    vazia, tenha ela sido enviada ou omitida. `exclude_unset` distingue, e o
    resultado disso chega aqui — e para aqui.
    """
    mandou_lista = "outra_parte" in alteracoes
    mandou_coluna = "interlocutor_id" in alteracoes

    if mandou_lista:
        # A LISTA MANDA. A coluna é projeção dela, mesmo que a requisição tenha
        # mandado as duas coisas: editar participantes é o gesto, e a coluna
        # acompanha. Lista sem principal — vazia inclusive — significa que
        # ninguém representa a outra parte.
        participantes = alteracoes["outra_parte"] or ()
        principal = next((p for p in participantes if p.principal), None)
        alteracoes = dict(alteracoes)
        alteracoes["interlocutor_id"] = (
            principal.interlocutor_id if principal else None
        )
        return alteracoes

    if mandou_coluna:
        # A COLUNA MANDA, e a lista acompanha. É o formato da tela de hoje, que
        # edita o interlocutor num campo só e não conhece a lista.
        novo_id = alteracoes["interlocutor_id"]
        atuais = [
            replace(p, principal=(p.interlocutor_id == novo_id))
            for p in interacao.outra_parte
        ]
        if novo_id is not None and not any(p.principal for p in atuais):
            # Trocar para alguém que ainda não estava na agenda: ele entra.
            atuais.append(
                ParticipanteDaOutraParte(interlocutor_id=novo_id, principal=True)
            )
        alteracoes = dict(alteracoes)
        alteracoes["outra_parte"] = tuple(atuais)
        return alteracoes

    # Nem uma nem outra: nada a reconciliar.
    return alteracoes


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
