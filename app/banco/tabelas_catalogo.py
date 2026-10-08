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
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class CanalConsulta(_Dicionario, Tabela):
    """Por onde uma consulta recebida chegou — e-mail, formulário, rating."""

    __tablename__ = "canal_consulta"


class Apuracao(_Dicionario, Tabela):
    """Em que pé está a apuração de uma alegação. Tem cor: a tela pinta a
    alegação por ela, como faz com clima."""

    __tablename__ = "apuracao"
    cor_hex: Mapped[str] = mapped_column(String(7))


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
    #: `estruturante` (afeta a tese da companhia) | `operacional` (afeta o dia
    #: a dia). CADASTRO, e não derivação — nada no dado diz qual é qual. Nulo
    #: até alguém classificar. Ver `migrations/0048`.
    tipo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A hierarquia bloco > macro tema > tema da taxonomia v1.3 (Peers/Comms,
    #: ainda em validação por área). Nulo em quem não foi reconciliado com a
    #: taxonomia nova. Ver `migrations/0053`.
    macro_tema_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("macro_tema.id"), nullable=True
    )
    #: legitimidade | credibilidade | confianca | nao_se_aplica — dimensão da
    #: taxonomia v1.3, distinta de `tipo`. Cadastro, não derivação. Ver `migrations/0053`.
    camada_lso: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Se este tema representa exposição de risco (taxonomia v3, Risco/Outros).
    #: Cadastro, não derivação. Nulo em quem não foi reconciliado com a
    #: taxonomia v4. Ver `migrations/0058`.
    e_risco: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Nulo em toda a carga inicial da taxonomia v1.3: a planilha de origem
    #: sugere mais de uma área em várias linhas, e a decisão de qual
    #: prevalece ainda não foi tomada. Ver `migrations/0053`.
    area_dona_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("area_pessoa.id"), nullable=True
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Tag livre nasce datada — é o rastro de quando o vocabulário cresceu.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    #: QUAIS RISCOS DA MATRIZ CORPORATIVA ESTE TEMA TOCA. `selectin` carrega os
    #: vínculos de toda a lista numa consulta a mais, não uma por tema — mesmo
    #: raciocínio de `PessoaAegea.vinculos_de_tema`. Só leitura: quem escreve é
    #: `_aplicar_riscos_do_tema`, na API. Ver `migrations/0059`.
    vinculos_de_risco: Mapped[list[TemaRisco]] = relationship(
        "TemaRisco", viewonly=True, lazy="selectin"
    )

    @property
    def riscos(self) -> list[int]:
        """Os ids dos riscos associados, como a tela os quer."""
        return sorted(vinculo.risco_id for vinculo in self.vinculos_de_risco)


class BlocoTema(_Dicionario, Tabela):
    """O nível mais alto da taxonomia de temas v1.3 (Peers/Comms) — 4 blocos.
    Ainda em validação por área; não exposto em `GET /api/dicionarios`
    enquanto a hierarquia não estiver pronta para uso. Ver `migrations/0053`."""

    __tablename__ = "bloco_tema"


class MacroTema(Tabela):
    """O nível intermediário entre `BlocoTema` e `Tema` — 20 macro temas.
    Mesmo raciocínio de `SubcategoriaPublico`: existe só para agrupar `Tema`
    dentro de um `BlocoTema`. Ver `migrations/0053`."""

    __tablename__ = "macro_tema"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    bloco_tema_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("bloco_tema.id"))
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class RiskCluster(_Dicionario, Tabela):
    """O agrupador dos 32 riscos da matriz corporativa da Aegea — 8 clusters.
    Ver `migrations/0059`."""

    __tablename__ = "risk_cluster"


class Risco(Tabela):
    """Um dos 32 riscos da matriz corporativa — severidade já atribuída pela
    Aegea (não é derivada). Mesmo raciocínio de `MacroTema`: existe para
    agrupar, aqui sob um `RiskCluster`. Ver `migrations/0059`."""

    __tablename__ = "risco"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    risk_cluster_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("risk_cluster.id"))
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    #: critico | alto | moderado.
    severidade: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class TemaRisco(Tabela):
    """Quais riscos da matriz um tema (subtema da taxonomia v5) toca. N:N de
    propósito — um tema pode tocar mais de um risco. Ver `migrations/0059`."""

    __tablename__ = "tema_risco"

    tema_id: Mapped[int] = mapped_column(Integer, ForeignKey("tema.id"), primary_key=True)
    risco_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("risco.id"), primary_key=True
    )


class AreaPessoa(_Dicionario, Tabela):
    """A área de quem representa a Aegea — Comunicação, Relações
    Institucionais etc. Ver `0029_area_do_representante.sql`."""

    __tablename__ = "area_pessoa"


class CategoriaPublico(_Dicionario, Tabela):
    """A taxonomia de públicos — 11 categorias (Poder Executivo, Imprensa,
    Formadores de Opinião...; a 0061 separou Imprensa de Formadores de
    Opinião, antes uma categoria só). Vive em `instituicao`, não em
    `interacao`: ver `0036_categoria_de_publico.sql` e `0061`."""

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
    "blocos_tema": BlocoTema,
    "macro_temas": MacroTema,
    "risk_clusters": RiskCluster,
    "riscos": Risco,
    "areas_pessoa": AreaPessoa,
    "categorias_publico": CategoriaPublico,
    "subcategorias_publico": SubcategoriaPublico,
    "canais_consulta": CanalConsulta,
    "apuracoes": Apuracao,
}
