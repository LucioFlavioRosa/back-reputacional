"""Tabelas de acesso. Nunca existe coluna de senha: a identidade vem do Entra ID.

A autorização, essa sim, mora aqui — `papel` diz o que a pessoa pode fazer e
`usuario_escopo` sobre quais registros. Espelham `migrations/0003_acesso.sql`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class Papel(Tabela):
    """Conjunto nomeado de permissões. Não contém escopo — ver `UsuarioEscopo`."""

    __tablename__ = "papel"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)

    pode_criar: Mapped[bool] = mapped_column(Boolean, default=False)
    pode_editar_proprio: Mapped[bool] = mapped_column(Boolean, default=False)
    pode_editar_tudo: Mapped[bool] = mapped_column(Boolean, default=False)
    administra_dicionarios: Mapped[bool] = mapped_column(Boolean, default=False)
    administra_acessos: Mapped[bool] = mapped_column(Boolean, default=False)

    ve_campos_sensiveis: Mapped[bool] = mapped_column(Boolean, default=False)
    ve_diretorio: Mapped[bool] = mapped_column(Boolean, default=False)
    pode_exportar: Mapped[bool] = mapped_column(Boolean, default=False)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UsuarioEscopo(Tabela):
    """Restrição de leitura por dimensão.

    Sem chave estrangeira porque a dimensão é polimórfica: `valor` referencia
    `frente.codigo` ou `unidade_negocio.codigo` conforme o caso.
    """

    __tablename__ = "usuario_escopo"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
    )
    dimensao: Mapped[str] = mapped_column(Text, primary_key=True)
    valor: Mapped[str] = mapped_column(Text, primary_key=True)
    concedido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Usuario(Tabela):
    __tablename__ = "usuario"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: `oid` do token do Entra ID — a identidade estável da pessoa no diretório.
    entra_object_id: Mapped[str] = mapped_column(Text, unique=True)
    #: CITEXT: o Entra ID pode devolver a claim com outra caixa, e sem isso a
    #: mesma pessoa ganharia uma segunda conta no provisionamento JIT.
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    provisionado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ultimo_acesso_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Anulável de propósito: é assim que o convidado B2B nasce — autenticado
    #: pelo diretório e autorizado a nada, até alguém conceder.
    papel_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("papel.id"), nullable=True
    )
    #: Verdadeiro dispensa o filtro de escopo. Falso *sem* linha em
    #: `usuario_escopo` significa não ver nada — falha fechada.
    acesso_irrestrito: Mapped[bool] = mapped_column(Boolean, default=False)
    externo: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Obrigatório para externo, por `check` no banco. O esquecimento de
    #: revogar vira expiração.
    acesso_expira_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    papel_concedido_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    papel_concedido_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AcessoLog(Tabela):
    __tablename__ = "acesso_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    email_tentado: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocorrido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    resultado: Mapped[str] = mapped_column(Text)
