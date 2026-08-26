"""Tabela de relatórios. Espelha `migrations/0007_relatorios.sql`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class RelatorioRegistro(Tabela):
    __tablename__ = "relatorio"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: `['resumo','volumetria',...]` — vocabulário fechado, validado no domínio.
    secoes: Mapped[list[str]] = mapped_column(JSONB)
    #: O `Recorte` serializado. JSONB e não colunas: os filtros mudam com o
    #: produto, e uma coluna por filtro viraria migration a cada ajuste de tela.
    filtros: Mapped[dict[str, Any]] = mapped_column(JSONB)
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=None, insert_default=func.now()
    )
    arquivo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Quantos registros o recorte alcançava no momento da geração.
    total_de_registros: Mapped[int] = mapped_column(Integer, default=0)
    #: `documento` (corta em `LINHAS_NO_DOCUMENTO`) | `csv` (não corta).
    formato: Mapped[str] = mapped_column(Text, default="documento")
