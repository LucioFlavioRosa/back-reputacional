"""Tabelas dos dicionários administráveis.

Espelham `app/banco/migrations/0001_fundacao.sql`. São tabelas e não enums do
Postgres porque a coordenação precisa alterar os valores sem migration.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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


class Relevancia(Tabela):
    """Os níveis de relevância — o que o painel chama de "tier".

    NÃO herda `_Dicionario`: aqui a chave primária é o PRÓPRIO número do tier,
    e não uma sequência. `interacao.tier` guarda 1, 2, 3… e é esse número que
    aparece na tela, nos KPIs e na exportação, então uma segunda numeração
    interna só criaria tradução sem serventia.

    Também não tem `codigo`: o número já é o código estável.
    """

    __tablename__ = "relevancia"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Status(_Dicionario, Tabela):
    __tablename__ = "status"
    #: resolvido | aberto | declinado — sustenta a taxa de resolutividade.
    grupo: Mapped[str] = mapped_column(Text)


class FormatoInteracao(_Dicionario, Tabela):
    """Mídia, Agenda de mercado, Agenda pública, Manifestação formal, Evento,
    Visita, Reunião — que TIPO DE ENCONTRO foi, não quem é a contraparte
    (isso é `Frente`). Ver `0038_formato_interacao.sql`."""

    __tablename__ = "formato_interacao"


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
    #: estrategico (vocabulário fechado) | livre (criada por quem registra)
    nivel: Mapped[str] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Tag livre nasce datada — é o rastro de quando o vocabulário cresceu.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AreaPessoa(_Dicionario, Tabela):
    """A área de quem representa a Aegea — Comunicação, Relações
    Institucionais etc. Ver `0029_area_do_representante.sql`."""

    __tablename__ = "area_pessoa"


class CategoriaPublico(_Dicionario, Tabela):
    """A taxonomia de públicos — 10 categorias (Poder Executivo, Imprensa e
    Formadores de Opinião...). Vive em `instituicao`, não em `interacao`: ver
    `0036_categoria_de_publico.sql`."""

    __tablename__ = "categoria_publico"
    #: esfera | logica_de_relacao | posicao_de_capital | logica_editorial | sem_quebra
    #: — como esta categoria se subdivide, não uma entidade que se cadastra.
    padrao_de_quebra: Mapped[str] = mapped_column(Text)
    #: Nula só em "Parceiros e Cadeia de Valor": ali a área responsável é quem
    #: demandou a interação, variável por instituição — não fixa por categoria
    #: como nas outras nove.
    area_dona_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("area_pessoa.id"), nullable=True
    )


class SubcategoriaPublico(Tabela):
    """A subdivisão dentro de uma `CategoriaPublico` — Federal/Estadual/
    Municipal, por exemplo. Só existe para quem tem `padrao_de_quebra` !=
    `sem_quebra`.

    NÃO HERDA `_Dicionario`: lá `codigo` é `unique` sozinho, mas aqui "federal"
    se repete de propósito em Poder Executivo, Poder Legislativo e Reguladores
    — a unicidade real é `(categoria_publico_id, codigo)`, ver a migration.
    Herdar a mixin faria o ORM declarar uma constraint que a migration não tem.
    """

    __tablename__ = "subcategoria_publico"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    categoria_publico_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("categoria_publico.id")
    )
    codigo: Mapped[str] = mapped_column(Text)
    nome: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


#: Ordem em que os dicionários aparecem em `GET /api/dicionarios`.
DICIONARIOS: dict[str, type[Tabela]] = {
    "frentes": Frente,
    "relevancias": Relevancia,
    "status": Status,
    "formatos_interacao": FormatoInteracao,
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
    "areas_pessoa": AreaPessoa,
    "categorias_publico": CategoriaPublico,
    "subcategorias_publico": SubcategoriaPublico,
}
