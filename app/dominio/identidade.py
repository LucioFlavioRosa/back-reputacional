"""Quem está usando o sistema, o que pode fazer e sobre quais registros.

A autorização mora no banco, e não em claim de grupo do Entra ID. O diretório
responde "quem é você"; `papel` e `usuario_escopo` respondem "o que você pode".

A razão é prática: escopo granular — esta frente, aquela unidade — não cabe em
grupo de AD sem multiplicar grupos, e a lista de grupos do tenant é administrada
por outra equipe. Ver `seguranca/ARQUITETURA.md`.

Três conceitos que valem manter separados:

    Papel    o que a pessoa pode FAZER      (criar, editar, exportar…)
    Escopo   sobre QUAIS registros
    Prazo    até QUANDO
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID


class Portal(StrEnum):
    """As três divisões da plataforma, como a capa as oferece."""

    CRM = "crm"
    SINTESE = "sintese"
    SCORE = "score"


class Perfil(StrEnum):
    """Os papéis semeados pela migration 0003.

    NÃO é a fonte da autorização — quem decide são as bandeiras de `Papel`.
    Isto é o vocabulário para semear e para escolher o usuário do provedor mock
    de desenvolvimento.

    A lista pode crescer sem passar por aqui: `papel` é tabela, e um papel novo
    é um `insert`. O que está neste enum são os quatro de partida, que são a
    divisão por PORTAL — a fronteira mais grossa da plataforma.
    """

    PLATAFORMA = "plataforma"
    CRM = "crm"
    SINTESE = "sintese"
    SCORE = "score"


@dataclass(frozen=True, slots=True)
class Papel:
    """O que a pessoa pode fazer, e ONDE. Espelha uma linha de `papel`."""

    codigo: str
    nome: str

    pode_criar: bool = False
    pode_editar_proprio: bool = False
    pode_editar_tudo: bool = False
    administra_dicionarios: bool = False
    administra_acessos: bool = False

    ve_campos_sensiveis: bool = False
    ve_diretorio: bool = False
    pode_exportar: bool = False

    #: ONDE a pessoa entra — dimensão separada do que ela faz lá dentro.
    #:
    #: Sem essa separação a lista de papéis multiplicaria: "lê a Síntese" e "lê
    #: a Síntese e o Score" seriam papéis diferentes, e cada portal novo
    #: dobraria a tabela.
    #:
    #: Fecham por padrão, como todas as outras bandeiras. Papel novo que não
    #: decida nada não abre porta nenhuma.
    acessa_crm: bool = False
    acessa_sintese: bool = False
    acessa_score: bool = False

    @property
    def somente_leitura(self) -> bool:
        return not (self.pode_criar or self.pode_editar_proprio or self.pode_editar_tudo)

    def alcanca(self, portal: Portal) -> bool:
        """Se este papel abre o portal.

        Um `match` e não três `if`: acrescentar um portal ao enum passa a
        quebrar aqui em vez de devolver `False` calado, que seria uma porta
        fechada sem ninguém saber por quê.
        """
        match portal:
            case Portal.CRM:
                return self.acessa_crm
            case Portal.SINTESE:
                return self.acessa_sintese
            case Portal.SCORE:
                return self.acessa_score

    @property
    def portais(self) -> frozenset[Portal]:
        """Os portais que este papel abre. É o que a tela usa para decidir o
        que mostrar na capa."""
        return frozenset(p for p in Portal if self.alcanca(p))


@dataclass(frozen=True, slots=True)
class Escopo:
    """Sobre quais registros. Espelha as linhas de `usuario_escopo`.

    Uma dimensão sem valores não restringe *aquela* dimensão — mas ninguém
    chega aqui com as duas vazias e `irrestrito` falso e enxerga tudo: isso é
    `nao_alcanca_nada`, e o tradutor de SQL devolve uma condição falsa.
    """

    irrestrito: bool = False
    #: códigos de `frente`
    frentes: frozenset[str] = frozenset()
    #: nomes de `unidade_negocio` — a tabela não tem coluna `codigo`
    unidades: frozenset[str] = frozenset()

    @property
    def nao_alcanca_nada(self) -> bool:
        """Restrito e sem nenhuma concessão: não vê registro nenhum.

        A alternativa — "sem linha significa sem restrição" — falharia aberta
        para todo convidado B2B recém-provisionado, que é exatamente o caso
        que este plano existe para cobrir.
        """
        return not self.irrestrito and not self.frentes and not self.unidades

    @classmethod
    def total(cls) -> Escopo:
        return cls(irrestrito=True)


def _hoje_utc() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True, slots=True)
class UsuarioAtual:
    """Quem está fazendo a requisição."""

    id: UUID
    nome: str
    email: str
    #: Nulo é o estado normal do convidado B2B no primeiro login: autenticado
    #: pelo Entra ID e autorizado a nada, até alguém conceder.
    papel: Papel | None
    escopo: Escopo = Escopo()
    externo: bool = False
    acesso_expira_em: date | None = None

    @property
    def sem_autorizacao(self) -> bool:
        return self.papel is None

    def acesso_vencido(self, hoje: date | None = None) -> bool:
        """Concessão com prazo, obrigatória para quem é de fora.

        A comparação usa a data UTC. Para o Brasil isso estende a validade em
        até três horas além da virada local — folga deliberada: é preferível
        conceder um fim de tarde a mais do que derrubar alguém no meio do
        expediente por causa de fuso.
        """
        if self.acesso_expira_em is None:
            return False
        return (hoje or _hoje_utc()) > self.acesso_expira_em

    @property
    def somente_leitura(self) -> bool:
        return self.papel is None or self.papel.somente_leitura

    @property
    def administra_dicionarios(self) -> bool:
        return self.papel is not None and self.papel.administra_dicionarios

    @property
    def ve_campos_sensiveis(self) -> bool:
        """`relato` e `pendencias` saem do payload quando falso."""
        return self.papel is not None and self.papel.ve_campos_sensiveis
