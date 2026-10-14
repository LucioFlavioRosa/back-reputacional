"""A porta de persistência do contexto.

Interface, não implementação: o domínio e os casos de uso dependem deste
protocolo, e a `infraestrutura` fornece o adaptador SQL. Trocar o Postgres por
um repositório em memória nos testes não exige mudar uma linha de caso de uso.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.dominio.identidade import Escopo
from app.dominio.interacao import Interacao
from app.dominio.recorte import Recorte


@dataclass(frozen=True, slots=True)
class Pagina:
    """Um pedaço do recorte, com o total para o contador do painel."""

    itens: tuple[Interacao, ...]
    total: int
    pagina: int
    tamanho: int

    @property
    def paginas(self) -> int:
        if self.tamanho <= 0:
            return 0
        return -(-self.total // self.tamanho)  # teto da divisão


class RepositorioDeInteracoes(Protocol):
    def adicionar(self, interacao: Interacao) -> Interacao: ...

    def obter(
        self,
        id: UUID,
        *,
        escopo: Escopo,
        alcanca_sensivel: bool,
        para_edicao: bool = False,
    ) -> Interacao | None:
        """Devolve o registro se o escopo do usuário o alcança.

        O escopo é obrigatório aqui pelo mesmo motivo que em `listar`: sem ele,
        a leitura por id é o caminho que escapa do filtro, e quem conhecer o
        identificador lê qualquer registro.

        `alcanca_sensivel` é obrigatório pela MESMA razão, uma camada adiante:
        uma agenda marcada como sensível (0089) não pode se abrir por URL
        direta para quem não tem a camada. Sem padrão, de propósito — esquecer
        é `TypeError`, e não um vazamento numa rota só.
        """
        ...

    def atualizar(self, interacao: Interacao) -> Interacao: ...

    def listar(
        self,
        recorte: Recorte,
        *,
        escopo: Escopo,
        alcanca_sensivel: bool,
        pagina: int = 1,
        tamanho: int = 50,
        ordenacao: str = "-data_interacao",
    ) -> Pagina: ...

    def contar(
        self, recorte: Recorte, *, escopo: Escopo, alcanca_sensivel: bool
    ) -> int: ...
