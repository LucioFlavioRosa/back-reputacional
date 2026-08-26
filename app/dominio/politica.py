"""Quem pode mexer em quê.

As permissões deixaram de ser um `match` sobre três perfis fixos e passaram a
ser bandeiras de `papel`, concedidas no banco (migration 0003). Os papéis
semeados continuam se comportando como antes:

    analista      cria; edita os próprios registros
    coordenacao   edita tudo; administra dicionários e acessos
    diretoria     somente leitura
    externo       somente leitura, sem campos sensíveis nem diretório

A regra mora no domínio porque depende de um dado do agregado — `criado_por` —
e não apenas do papel de quem pede.
"""

from __future__ import annotations

from app.dominio.erros import NaoAutorizado
from app.dominio.identidade import UsuarioAtual
from app.dominio.interacao import Interacao


def pode_editar(usuario: UsuarioAtual, interacao: Interacao) -> bool:
    papel = usuario.papel
    if papel is None:
        return False
    if papel.pode_editar_tudo:
        return True
    if papel.pode_editar_proprio:
        return interacao.criado_por == usuario.id
    return False


def exigir_permissao_de_edicao(usuario: UsuarioAtual, interacao: Interacao) -> None:
    """Levanta se o usuário não pode alterar este registro."""
    if pode_editar(usuario, interacao):
        return

    if usuario.somente_leitura:
        raise NaoAutorizado(
            f"Perfil {usuario.papel.nome if usuario.papel else 'sem papel'} "
            "tem acesso somente de leitura."
        )

    raise NaoAutorizado(
        "Analista só edita os registros que criou. "
        "Peça à coordenação para alterar este."
    )
