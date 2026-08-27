"""Quem pode mexer em quê.

As permissões são bandeiras de `papel`, concedidas no banco (migration 0003), e
não um `match` sobre perfis fixos. Este módulo NUNCA lê o código do papel — só
as bandeiras —, e é o que permite acrescentar um papel por `insert`.

Os OITO semeados são um LEITOR e um EDITOR para cada portal:

    plataforma_leitura / plataforma_edicao   os três portais
    crm_leitura        / crm_edicao          CRM dos Stakeholders
    sintese_leitura    / sintese_edicao      Síntese Executiva
    score_leitura      / score_edicao        Score Executivo

O prefixo diz ONDE entra; o sufixo diz o que FAZ lá dentro.

`pode_editar_tudo` — mexer no registro que OUTRA pessoa criou — fica só em
`plataforma_edicao`. Os editores de portal têm `pode_editar_proprio`, e a
distinção é o que separa "trabalha aqui" de "manda aqui".

QUAL portal um papel abre é outra dimensão, e mora em `Papel.acessa_*`. Aqui só
importa o que ele pode FAZER com o que alcança.

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
