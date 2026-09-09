"""Tabela de exportações. Espelha `migrations/0007_relatorios.sql` + `0025`.

Chamava-se `relatorio` e guardava duas coisas: o documento impresso pela tela
e a trilha de quem exportou a Base. A tela saiu do produto; a trilha ficou,
porque é controle de segurança e não relatório.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class ExportacaoRegistro(Tabela):
    __tablename__ = "exportacao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: O `Recorte` serializado. JSONB e não colunas: os filtros mudam com o
    #: produto, e uma coluna por filtro viraria migration a cada ajuste de tela.
    filtros: Mapped[dict[str, Any]] = mapped_column(JSONB)
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=None, insert_default=func.now()
    )
    #: Quantos registros o recorte alcançava no momento da exportação. Contado
    #: no servidor: receber do cliente seria aceitar que quem exporta declare
    #: quanto exportou.
    total_de_registros: Mapped[int] = mapped_column(Integer, default=0)
