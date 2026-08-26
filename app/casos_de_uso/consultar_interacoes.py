"""Casos de uso de leitura: a listagem filtrada e a ficha do registro."""

from __future__ import annotations

from uuid import UUID

from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.identidade import Escopo
from app.dominio.interacao import Interacao
from app.dominio.recorte import Recorte
from app.dominio.repositorio import (
    Pagina,
    RepositorioDeInteracoes,
)

TAMANHO_MAXIMO_DE_PAGINA = 200


def listar(
    repositorio: RepositorioDeInteracoes,
    *,
    recorte: Recorte,
    escopo: Escopo,
    busca_em_campos_sensiveis: bool,
    pagina: int = 1,
    tamanho: int = 50,
    ordenacao: str = "-data_interacao",
) -> Pagina:
    """A base de registros e o contador do recorte saem daqui."""
    if pagina < 1:
        raise RegraViolada("A página começa em 1.")
    if not 1 <= tamanho <= TAMANHO_MAXIMO_DE_PAGINA:
        raise RegraViolada(
            f"O tamanho da página vai de 1 a {TAMANHO_MAXIMO_DE_PAGINA}."
        )

    return repositorio.listar(
        recorte,
        escopo=escopo,
        busca_em_campos_sensiveis=busca_em_campos_sensiveis,
        pagina=pagina,
        tamanho=tamanho,
        ordenacao=ordenacao,
    )


def obter(repositorio: RepositorioDeInteracoes, *, id: UUID, escopo: Escopo) -> Interacao:
    """A ficha do registro.

    Precisa recusar exatamente o que a listagem esconde — arquivado, invisível
    e fora do escopo do usuário. Hoje o repositório aplica as três em SQL, mas
    a checagem em Python fica: ela é barata e um repositório em memória escrito
    para teste não teria como reproduzir o `where`.

    Fora do escopo devolve "não encontrada", e não "não autorizada", de
    propósito: a segunda mensagem confirmaria a existência do registro para
    quem não deveria saber sequer disso.
    """
    interacao = repositorio.obter(id, escopo=escopo)
    if interacao is None or interacao.arquivada or not interacao.visivel:
        raise NaoEncontrado(f"Interação {id} não encontrada.")
    return interacao
