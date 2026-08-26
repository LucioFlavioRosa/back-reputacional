"""Quem está do outro lado, e quem representa a Aegea."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class Instituicao(Tabela):
    __tablename__ = "instituicao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    #: unaccent(lower(nome)) — junta "Radamés" e "Radames" na importação.
    nome_normalizado: Mapped[str] = mapped_column(Text)
    #: veiculo | orgao | entidade | escritorio | investidor | proposicao | area_interna
    tipo: Mapped[str] = mapped_column(Text)
    esfera_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("esfera.id"), nullable=True
    )
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
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
    #: Aparece no diretório de porta-vozes e no painel de exposição.
    eh_porta_voz: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
