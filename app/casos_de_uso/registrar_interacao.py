"""Caso de uso: registrar uma nova interação."""

from __future__ import annotations

from app.dominio.identidade import UsuarioAtual
from app.dominio.interacao import Interacao
from app.dominio.repositorio import (
    RepositorioDeInteracoes,
)


def registrar(
    repositorio: RepositorioDeInteracoes,
    *,
    interacao: Interacao,
    usuario: UsuarioAtual,
) -> Interacao:
    """Grava a interação em nome de quem está logado.

    Qualquer perfil que chegue até aqui já passou por `exigir_escrita`; a
    autoria é definida aqui e não vem do cliente, para que ninguém registre em
    nome de outra pessoa.
    """
    interacao.criado_por = usuario.id
    interacao.revalidar()
    return repositorio.adicionar(interacao)
