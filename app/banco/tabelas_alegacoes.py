"""O que está circulando no mercado. Espelha `migrations/0046`.

Uma ALEGAÇÃO é o que uma pergunta recebida dá como fato sem que a companhia
tenha comunicado — "o Banco X não renegociaria a dívida". Ela vive solta da
consulta que a trouxe (`InteracaoAlegacao`, N:N) porque é ela que se REPETE:
a mesma alegação chega por cinco e-mails de quatro instituições, e é contar
instituições distintas que responde "o quanto isto está circulando".

`texto_normalizado` tem índice único pela mesma razão de `nome_normalizado`
nos cadastros: duas pessoas registram a mesma alegação com acentuação
diferente e a contagem que o produto existe para fazer se parte em duas.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class Alegacao(Tabela):
    __tablename__ = "alegacao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    texto: Mapped[str] = mapped_column(Text)
    texto_normalizado: Mapped[str] = mapped_column(Text)
    apuracao_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("apuracao.id"))
    #: O posicionamento da biblioteca que responde a esta alegação. Nulo é o
    #: que a aba cobra: está circulando e não temos resposta publicada.
    referencia_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("referencia.id"), nullable=True
    )
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: NÃO SE APAGA uma alegação: ela é o histórico do que circulou, e apagá-la
    #: reescreveria a leitura de um período que já foi lido. Sai de circulação
    #: por aqui, como instituição e contato.
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class AlegacaoTema(Tabela):
    """De que assuntos a alegação trata. Espelha `InteracaoTema`."""

    __tablename__ = "alegacao_tema"

    alegacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("alegacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )
