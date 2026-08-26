"""Tabelas dos dicionários administráveis.

Espelham `app/banco/migrations/0001_fundacao.sql`. São tabelas e não enums do
Postgres porque a coordenação precisa alterar os valores sem migration.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class _Dicionario:
    """Forma comum a quase todos os dicionários: código estável + rótulo."""

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Frente(_Dicionario, Tabela):
    __tablename__ = "frente"
    cor_hex: Mapped[str] = mapped_column(String(7))


class Status(_Dicionario, Tabela):
    __tablename__ = "status"
    #: resolvido | aberto | declinado — sustenta a taxa de resolutividade.
    grupo: Mapped[str] = mapped_column(Text)


class Esfera(_Dicionario, Tabela):
    __tablename__ = "esfera"


class Clima(_Dicionario, Tabela):
    __tablename__ = "clima"
    cor_hex: Mapped[str] = mapped_column(String(7))


class Resultado(_Dicionario, Tabela):
    __tablename__ = "resultado"
    cor_hex: Mapped[str] = mapped_column(String(7))


class Iniciativa(_Dicionario, Tabela):
    __tablename__ = "iniciativa"


class Formato(_Dicionario, Tabela):
    __tablename__ = "formato"
    #: imprensa | investidores | geral
    escopo: Mapped[str] = mapped_column(Text)


class NaturezaOrgao(_Dicionario, Tabela):
    __tablename__ = "natureza_orgao"


class Casa(_Dicionario, Tabela):
    __tablename__ = "casa"


class Tramitacao(_Dicionario, Tabela):
    __tablename__ = "tramitacao"


class TipoInvestidor(_Dicionario, Tabela):
    __tablename__ = "tipo_investidor"


class Stakeholder(_Dicionario, Tabela):
    __tablename__ = "stakeholder"


class UnidadeNegocio(Tabela):
    __tablename__ = "unidade_negocio"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(Text, unique=True)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Tema(Tabela):
    __tablename__ = "tema"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(Text, unique=True)
    #: estrategico (vocabulário fechado) | livre (criada pelo analista)
    nivel: Mapped[str] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Tag livre nasce datada — é o rastro de quando o vocabulário cresceu.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


#: Ordem em que os dicionários aparecem em `GET /api/dicionarios`.
DICIONARIOS: dict[str, type[Tabela]] = {
    "frentes": Frente,
    "status": Status,
    "esferas": Esfera,
    "climas": Clima,
    "resultados": Resultado,
    "iniciativas": Iniciativa,
    "formatos": Formato,
    "naturezas_orgao": NaturezaOrgao,
    "casas": Casa,
    "tramitacoes": Tramitacao,
    "tipos_investidor": TipoInvestidor,
    "stakeholders": Stakeholder,
    "unidades_negocio": UnidadeNegocio,
    "temas": Tema,
}
