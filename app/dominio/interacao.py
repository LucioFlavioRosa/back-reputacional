"""O agregado raiz: uma interação com um stakeholder.

Uma tabela-mãe, sete frentes. Os campos comuns — os que os filtros do Recorte e as
agregações usam — moram aqui; o que é exclusivo de uma frente vive na extensão
correspondente, em `frentes/`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from uuid import UUID

from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    Extensao,
    Frente,
    extensao_esperada,
)
from app.dominio.recorte import ABRANGENCIAS_VALIDAS

#: Como o registro entrou no sistema.
FONTES = ("cadastro_manual", "importacao_planilha", "plataforma_ri")

#: Papéis que uma pessoa da Aegea pode ter numa interação.
PAPEL_PORTA_VOZ = "porta_voz"
PAPEL_EQUIPE = "equipe"
PAPEIS = (PAPEL_PORTA_VOZ, PAPEL_EQUIPE)


@dataclass(frozen=True, slots=True)
class ParticipacaoAegea:
    """Quem representou a Aegea, e em que papel.

    Uma interação pode ter mais de um porta-voz: "Radamés Casseb e André Pires"
    conta para os dois no painel de exposição.
    """

    pessoa_aegea_id: UUID
    papel: str = PAPEL_PORTA_VOZ

    def __post_init__(self) -> None:
        if self.papel not in PAPEIS:
            raise RegraViolada(
                f"Papel inválido: {self.papel!r}. Use {' ou '.join(PAPEIS)}."
            )


@dataclass
class Interacao:
    """Uma interação institucional registrada.

    O construtor valida as invariantes; a edição volta a validá-las por
    `revalidar()`. Nenhum caminho grava um registro que o domínio recusaria.
    """

    # identidade e recorte
    frente: Frente
    data_interacao: date
    instituicao_id: UUID
    uf: str
    status: str
    pauta: str

    id: UUID | None = None
    interlocutor_id: UUID | None = None
    unidade_negocio_id: int | None = None
    esfera_id: int | None = None
    tier: int | None = None
    stakeholder_id: int | None = None

    # classificação
    clima: str | None = None
    resultado: str | None = None
    iniciativa: str | None = None

    # conteúdo
    posicionamento: str | None = None
    relato: str | None = None
    encaminhamentos: str | None = None
    pendencias: str | None = None
    observacoes: str | None = None
    registro_url: str | None = None

    # relações
    extensao: Extensao | None = None
    temas: tuple[int, ...] = ()
    participacoes: tuple[ParticipacaoAegea, ...] = ()

    # procedência e ciclo de vida
    fonte: str = "cadastro_manual"
    visivel: bool = True
    origem_aba: str | None = None
    origem_linha: int | None = None
    criado_por: UUID | None = None
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None
    arquivado_em: datetime | None = None

    def __post_init__(self) -> None:
        self.frente = Frente(self.frente)
        self.revalidar()

    # -- invariantes ---------------------------------------------------------

    def revalidar(self) -> None:
        """Garante que o agregado está íntegro. Chamado na criação e na edição."""
        if not self.pauta or not self.pauta.strip():
            raise RegraViolada("A pauta é obrigatória: é o que identifica o registro.")

        if self.uf not in ABRANGENCIAS_VALIDAS:
            raise RegraViolada(
                f"Abrangência inválida: {self.uf!r}. Use uma das 27 UFs, "
                "'NA' (nacional) ou 'IN' (internacional). O mapa do painel depende dela."
            )

        if self.tier is not None and self.tier < 1:
            raise RegraViolada(f"Tier inválido: {self.tier!r}. Use um número positivo.")
        # QUAIS números existem é decisão do BANCO, não daqui: os níveis são
        # linhas em `relevancia`, e `interacao.tier` tem chave estrangeira para
        # lá. Repetir a lista neste ponto criaria uma segunda fonte da verdade
        # que nada obriga a concordar com a primeira — foi exatamente o que
        # havia antes: QUATRO cópias da mesma lista — esta, uma em
        # `dominio/recorte.py`, um `check between 1 and 3` no schema e as opções
        # escritas à mão no filtro do front, em outro repositório.
        #
        # Um número inexistente vira violação de chave estrangeira, traduzida
        # para `RegraViolada` na borda do banco.

        if self.fonte not in FONTES:
            raise RegraViolada(
                f"Fonte inválida: {self.fonte!r}. Use {', '.join(FONTES)}."
            )

        self._validar_extensao()
        self._validar_participacoes()

    def _validar_extensao(self) -> None:
        if self.extensao is None:
            return
        esperada = extensao_esperada(self.frente)
        if not isinstance(self.extensao, esperada):
            raise RegraViolada(
                f"A frente {self.frente.value!r} espera dados de "
                f"{esperada.__name__}, e recebeu {type(self.extensao).__name__}."
            )

    def _validar_participacoes(self) -> None:
        vistos: set[tuple[UUID, str]] = set()
        for participacao in self.participacoes:
            chave = (participacao.pessoa_aegea_id, participacao.papel)
            if chave in vistos:
                raise RegraViolada(
                    "A mesma pessoa aparece duas vezes no mesmo papel nesta interação."
                )
            vistos.add(chave)

    # -- comportamento -------------------------------------------------------

    @property
    def arquivada(self) -> bool:
        return self.arquivado_em is not None

    @property
    def porta_vozes(self) -> tuple[UUID, ...]:
        """Todos os porta-vozes do registro — a base do painel de exposição."""
        return tuple(
            p.pessoa_aegea_id for p in self.participacoes if p.papel == PAPEL_PORTA_VOZ
        )

    def dias_parada(self, hoje: date | None = None) -> int:
        """Dias desde a interação. Alimenta a fila de pendências."""
        return ((hoje or date.today()) - self.data_interacao).days

    def alterar(self, **campos: object) -> None:
        """Aplica alterações e revalida o agregado inteiro.

        Um `alterar` que quebre uma invariante levanta antes de qualquer coisa
        chegar ao banco.
        """
        desconhecidos = set(campos) - {f.name for f in _campos_editaveis()}
        if desconhecidos:
            raise RegraViolada(
                f"Campo inexistente ou não editável: {', '.join(sorted(desconhecidos))}."
            )

        for nome, valor in campos.items():
            setattr(self, nome, valor)

        if "frente" in campos:
            self.frente = Frente(self.frente)

        self.revalidar()


def _campos_editaveis() -> tuple[object, ...]:
    """Tudo, menos identidade e trilha de auditoria."""
    imutaveis = {
        "id", "criado_por", "criado_em", "atualizado_em",
        "arquivado_em", "origem_aba", "origem_linha",
    }
    return tuple(f for f in fields(Interacao) if f.name not in imutaveis)
