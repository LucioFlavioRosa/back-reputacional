"""Quem está do outro lado, e quem representa a Aegea."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.banco.sessao import Tabela


class Instituicao(Tabela):
    __tablename__ = "instituicao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    #: Sem acento e em minúsculas, normalizado por `app/dominio/texto.py` —
    #: junta "Radamés" e "Radames". É esta coluna que carrega a unicidade e o
    #: índice de trigrama; `nome` fica intacto para exibição.
    nome_normalizado: Mapped[str] = mapped_column(Text)
    #: veiculo | orgao | entidade | investidor | proposicao | area_interna
    #:
    #: A lista vale como `TIPOS_DE_INSTITUICAO` no dominio, derivada do mapa
    #: frente -> tipo — e nao escrita a mao aqui.
    tipo: Mapped[str] = mapped_column(Text)
    #: O nome POR EXTENSO. `nome` guarda a forma curta — "ABCON", "ANA" —, que
    #: e como se fala e como a lista fica legivel; quem nao convive com a sigla
    #: nao sabe o que escolheu. Nulo no que veio da planilha.
    nome_completo: Mapped[str | None] = mapped_column(Text, nullable=True)
    esfera_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("esfera.id"), nullable=True
    )
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: Relevância da INSTITUIÇÃO — Tier 1 a 4, do mesmo dicionário `relevancia`
    #: que a agenda usa. Não confundir com `interacao.tier`, que é a relevância
    #: daquele encontro: a Folha é Tier 1 sempre, e uma nota de rodapé com a
    #: Folha pode ser Tier 3.
    #:
    #: Nulo nas cadastradas antes da coluna existir (0023). O formulário exige
    #: o campo nas novas.
    tier: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("relevancia.id"), nullable=True
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Interlocutor(Tabela):
    __tablename__ = "interlocutor"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text)
    instituicao_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instituicao.id"), nullable=True
    )
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Como se chega na pessoa. Marcar agenda comeca por escrever para alguem, e
    #: este endereco vivia fora do sistema.
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InterlocutorTema(Tabela):
    __tablename__ = "interlocutor_tema"

    interlocutor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interlocutor.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )


class PessoaAegea(Tabela):
    """Uma pessoa da Aegea é a mesma pessoa quer apareça como porta-voz numa
    demanda de imprensa, quer apareça na equipe de uma agenda de governo. O
    papel fica na relação com a interação, não na pessoa."""

    __tablename__ = "pessoa_aegea"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text, unique=True)
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Como se aciona a pessoa da casa para articular a agenda. Antes disto o
    #: endereco vivia no catalogo corporativo, fora daqui, e sem garantia de
    #: ser o certo.
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Aparece no diretório de porta-vozes e no painel de exposição.
    eh_porta_voz: Mapped[bool] = mapped_column(Boolean, default=False)
    #: De onde esta pessoa fala — Comunicação, Relações Institucionais etc.
    #: Nula em quem foi cadastrado antes de a coluna existir (0029).
    area_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("area_pessoa.id"), nullable=True
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    #: SOBRE O QUE ESTA PESSOA PODE FALAR.
    #:
    #: `selectin` carrega os vinculos de TODA a lista em uma consulta a mais —
    #: nao uma por pessoa. A objecao a N+1 registrada em `temas_do_porta_voz`
    #: vale para carregamento preguicoso, nao para carregamento em lote.
    #:
    #: So leitura: quem escreve e `_aplicar_temas_da_pessoa`, na API. Ter os
    #: dois lados gravaveis seria a mesma relacao com duas donas.
    vinculos_de_tema: Mapped[list[PessoaAegeaTema]] = relationship(
        "PessoaAegeaTema", viewonly=True, lazy="selectin"
    )

    @property
    def temas(self) -> list[int]:
        """Os ids dos assuntos autorizados, como a tela os quer.

        Propriedade e nao relacao: quem le quer o id do assunto, e nao a linha
        de ligacao. O esquema de saida mapeia por nome, entao le daqui.
        """
        return sorted(vinculo.tema_id for vinculo in self.vinculos_de_tema)


class PessoaAegeaTema(Tabela):
    """Temas autorizados. Sustenta a regra de "fora do escopo": registro cujo
    tema não está na lista do porta-voz que o conduziu."""

    __tablename__ = "pessoa_aegea_tema"

    pessoa_aegea_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pessoa_aegea.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )
