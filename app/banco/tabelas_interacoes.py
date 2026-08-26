"""Tabelas do core domain. Espelham `migrations/0004_interacoes.sql`."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.banco.sessao import Tabela


class InteracaoRegistro(Tabela):
    __tablename__ = "interacao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # identidade e recorte
    frente_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("frente.id"))
    data_interacao: Mapped[date] = mapped_column(Date)
    instituicao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instituicao.id")
    )
    interlocutor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interlocutor.id"), nullable=True
    )
    unidade_negocio_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("unidade_negocio.id"), nullable=True
    )
    esfera_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("esfera.id"), nullable=True
    )
    #: Obrigatória: o mapa do painel depende dela.
    uf: Mapped[str] = mapped_column(String(2))
    #: O NÚMERO do tier, e a chave estrangeira aponta para `relevancia`, onde
    #: os níveis são linhas. Sem declarar a FK aqui, o banco continuaria
    #: barrando um nível inexistente, mas o metadata do SQLAlchemy diria que
    #: a coluna é um inteiro solto — e é o metadata que o teste de deriva do
    #: schema compara com as migrations.
    tier: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("relevancia.id"), nullable=True
    )
    stakeholder_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("stakeholder.id"), nullable=True
    )

    # classificação
    status_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("status.id"))
    clima_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("clima.id"), nullable=True
    )
    resultado_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("resultado.id"), nullable=True
    )
    iniciativa_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("iniciativa.id"), nullable=True
    )

    # conteúdo
    pauta: Mapped[str] = mapped_column(Text)
    posicionamento: Mapped[str | None] = mapped_column(Text, nullable=True)
    relato: Mapped[str | None] = mapped_column(Text, nullable=True)
    encaminhamentos: Mapped[str | None] = mapped_column(Text, nullable=True)
    pendencias: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    registro_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # procedência e ciclo de vida
    fonte: Mapped[str] = mapped_column(Text, default="cadastro_manual")
    visivel: Mapped[bool] = mapped_column(Boolean, default=True)
    origem_aba: Mapped[str | None] = mapped_column(Text, nullable=True)
    origem_linha: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    atualizado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    arquivado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # extensões: uma por frente, carregadas junto com o registro
    imprensa: Mapped[ImprensaRegistro | None] = relationship(
        back_populates="interacao", cascade="all, delete-orphan", lazy="joined"
    )
    institucional: Mapped[InstitucionalRegistro | None] = relationship(
        back_populates="interacao", cascade="all, delete-orphan", lazy="joined"
    )
    legislativo: Mapped[LegislativoRegistro | None] = relationship(
        back_populates="interacao", cascade="all, delete-orphan", lazy="joined"
    )
    investidores: Mapped[InvestidoresRegistro | None] = relationship(
        back_populates="interacao", cascade="all, delete-orphan", lazy="joined"
    )
    interna: Mapped[InternaRegistro | None] = relationship(
        back_populates="interacao", cascade="all, delete-orphan", lazy="joined"
    )

    temas: Mapped[list[InteracaoTema]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    participacoes: Mapped[list[InteracaoPessoaAegea]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class ImprensaRegistro(Tabela):
    __tablename__ = "interacao_imprensa"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    formato_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("formato.id"), nullable=True
    )
    data_atendida: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_publicacao: Mapped[date | None] = mapped_column(Date, nullable=True)
    link_materia: Mapped[str | None] = mapped_column(Text, nullable=True)
    mensagens_chave: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    interacao: Mapped[InteracaoRegistro] = relationship(back_populates="imprensa")


class InstitucionalRegistro(Tabela):
    """Governo, Parceiros e Eventos."""

    __tablename__ = "interacao_institucional"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    natureza_orgao_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("natureza_orgao.id"), nullable=True
    )
    cargo_interlocutor: Mapped[str | None] = mapped_column(Text, nullable=True)
    nome_evento: Mapped[str | None] = mapped_column(Text, nullable=True)

    interacao: Mapped[InteracaoRegistro] = relationship(back_populates="institucional")


class LegislativoRegistro(Tabela):
    __tablename__ = "interacao_legislativo"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    casa_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("casa.id"), nullable=True
    )
    tramitacao_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("tramitacao.id"), nullable=True
    )
    prioridade: Mapped[str | None] = mapped_column(Text, nullable=True)
    ementa: Mapped[str | None] = mapped_column(Text, nullable=True)

    interacao: Mapped[InteracaoRegistro] = relationship(back_populates="legislativo")


class InvestidoresRegistro(Tabela):
    __tablename__ = "interacao_investidores"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tipo_investidor_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("tipo_investidor.id"), nullable=True
    )
    formato_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("formato.id"), nullable=True
    )

    interacao: Mapped[InteracaoRegistro] = relationship(back_populates="investidores")


class InternaRegistro(Tabela):
    __tablename__ = "interacao_interna"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    natureza: Mapped[str | None] = mapped_column(Text, nullable=True)
    cumprimento: Mapped[str | None] = mapped_column(Text, nullable=True)
    complexidade: Mapped[str | None] = mapped_column(Text, nullable=True)
    prazo_dias: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    data_retorno: Mapped[date | None] = mapped_column(Date, nullable=True)

    interacao: Mapped[InteracaoRegistro] = relationship(back_populates="interna")


class InteracaoTema(Tabela):
    __tablename__ = "interacao_tema"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )


class InteracaoPessoaAegea(Tabela):
    """Vários porta-vozes por interação: o registro conta para cada um deles."""

    __tablename__ = "interacao_pessoa_aegea"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pessoa_aegea_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pessoa_aegea.id"), primary_key=True
    )
    papel: Mapped[str] = mapped_column(Text, primary_key=True)


class Comentario(Tabela):
    __tablename__ = "comentario"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE")
    )
    autor: Mapped[str] = mapped_column(Text)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    escrito_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    texto: Mapped[str] = mapped_column(Text)


class InteracaoAuditoria(Tabela):
    """Diff campo a campo. O `relato` é sensível — toda alteração fica registrada."""

    __tablename__ = "interacao_auditoria"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id")
    )
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    ocorrido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    campo: Mapped[str] = mapped_column(Text)
    valor_anterior: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor_novo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `session_user`: a conta de banco com que a conexão se autenticou.
    #:
    #: Diferente de `usuario_id`, não é escolhida por quem escreve. Quem tem a
    #: connection string pode carimbar o id de outra pessoa em
    #: `painel.usuario_id`; não pode mentir sobre com qual conta entrou.
    origem: Mapped[str | None] = mapped_column(Text, nullable=True)


#: A frente determina em qual relação a extensão é gravada.
RELACAO_DA_EXTENSAO: dict[str, str] = {
    "imprensa": "imprensa",
    "governo": "institucional",
    "parceiros": "institucional",
    "eventos": "institucional",
    "legislativo": "legislativo",
    "investidores": "investidores",
    "interna": "interna",
}
