"""O Score Executivo, no banco. Espelha `migrations/0047`.

O índice mensal tem quatro coisas guardadas e uma calculada:

    lente               as cinco famílias de stakeholder — fechado
    score_fonte         de onde vem o sentimento de cada lente — extensível
    mencao              o grão fino: uma linha por matéria, post ou mensagem
    score_mes_fonte     as somas mensais, no grão que toda régua consome
    score_estimativa    o NS suposto, onde não houve medição
    score_config        a régua em vigor, versionada
    score_fato          o que explica a curva, escrito por gente

O score em si não mora aqui: é calculado na leitura, por `app/dominio/score.py`,
porque a régua que o produz é configurável — ver o cabeçalho da 0047.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class Lente(Tabela):
    """Uma das cinco famílias de stakeholder que o ISR pondera."""

    __tablename__ = "lente"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    stakeholder: Mapped[str] = mapped_column(Text)
    #: O peso de fábrica; a calibração vigente pode sobrepor.
    peso_padrao: Mapped[int] = mapped_column(SmallInteger)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class ScoreFonte(Tabela):
    """Um fornecedor de sentimento. Novo fornecedor é linha, não deploy."""

    __tablename__ = "score_fonte"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    fornecedor: Mapped[str] = mapped_column(Text)
    lente_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("lente.id"))
    tipo_arquivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Qual coluna da planilha alimenta qual campo de `mencao`.
    mapeamento_colunas: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Fonte interna não se ingere — o dado já está neste banco (hoje, o CRM).
    interna: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ordem: Mapped[int] = mapped_column(SmallInteger, default=0)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)


class Mencao(Tabela):
    """Uma matéria, post ou mensagem, já no vocabulário do índice."""

    __tablename__ = "mencao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fonte_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("score_fonte.id"))
    #: O primeiro dia do mês, sempre.
    mes: Mapped[date] = mapped_column(Date)
    data: Mapped[date | None] = mapped_column(Date, nullable=True)
    sentimento: Mapped[str] = mapped_column(Text)
    tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    engajamento: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    unidade_negocio_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("unidade_negocio.id"), nullable=True
    )
    tema_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tema.id"), nullable=True
    )
    #: O assunto no vocabulário do FORNECEDOR, que não é o do CRM.
    tema_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    atributo: Mapped[str | None] = mapped_column(Text, nullable=True)
    veiculo: Mapped[str | None] = mapped_column(Text, nullable=True)
    publico_alvo: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreMesFonte(Tabela):
    """As somas de um mês, no grão (fonte, sentimento, tier).

    É daqui que toda régua de ponderação tira o número — ver
    `dominio/score.py::ponderar`.
    """

    __tablename__ = "score_mes_fonte"

    fonte_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("score_fonte.id"), primary_key=True
    )
    mes: Mapped[date] = mapped_column(Date, primary_key=True)
    sentimento: Mapped[str] = mapped_column(Text, primary_key=True)
    #: Vazio, e não nulo, quando a fonte não tem tier: é chave primária.
    tier: Mapped[str] = mapped_column(Text, primary_key=True, default="")

    mencoes: Mapped[int] = mapped_column(Integer, default=0)
    soma_log: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    soma_engajamento: Mapped[int] = mapped_column(BigInteger, default=0)
    soma_cargo: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    atualizado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreEstimativa(Tabela):
    """O NS suposto de uma lente num mês sem export, com a origem escrita."""

    __tablename__ = "score_estimativa"

    lente_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("lente.id"), primary_key=True
    )
    mes: Mapped[date] = mapped_column(Date, primary_key=True)
    ns: Mapped[float] = mapped_column(Numeric(4, 3))
    #: De onde veio o número — uma estimativa sem procedência é um palpite.
    origem: Mapped[str] = mapped_column(Text)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreConfig(Tabela):
    """A calibração. Versionada: a linha mais recente é a vigente."""

    __tablename__ = "score_config"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Cresce sozinho e não empata — `criado_em` é o instante da transação, e
    #: duas versões gravadas juntas teriam o mesmo carimbo.
    versao: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    pesos: Mapped[dict] = mapped_column(JSONB, default=dict)
    regua_tier: Mapped[str] = mapped_column(Text, default="aegea")
    regua_engajamento: Mapped[str] = mapped_column(Text, default="n")
    fontes_desligadas: Mapped[list] = mapped_column(JSONB, default=list)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreFato(Tabela):
    """O que explica a curva do mês — texto de gente, não derivação."""

    __tablename__ = "score_fato"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mes: Mapped[date] = mapped_column(Date)
    texto: Mapped[str] = mapped_column(Text)
    #: `sustenta` | `pressiona` | `misto`
    efeito: Mapped[str] = mapped_column(Text)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())
