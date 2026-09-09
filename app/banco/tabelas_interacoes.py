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
    pauta: Mapped[str | None] = mapped_column(Text, nullable=True)
    posicionamento: Mapped[str | None] = mapped_column(Text, nullable=True)
    relato: Mapped[str | None] = mapped_column(Text, nullable=True)
    encaminhamentos: Mapped[str | None] = mapped_column(Text, nullable=True)
    pendencias: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    registro_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- onde a agenda acontece (migration 0015) ------------------------------
    #
    #: `presencial` | `online` | `hibrida`. NULO e NAO INFORMADO: o que veio da
    #: planilha nao respondeu isto, e supor presencial inventaria historia.
    #:
    #: Coluna PROPRIA, e nao deduzida do texto do local: a modalidade se agrega
    #: ("quantas foram presenciais neste trimestre?") e o endereco nao.
    modalidade: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Endereco, sala, ou o link da chamada. Texto livre de proposito: uma
    #: agenda acontece em "Ministerio das Cidades, bloco A" tanto quanto em
    #: "Teams", e estruturar exigiria decidir o que fazer com o segundo.
    local: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- o ciclo da agenda (migration 0011) -----------------------------------
    #
    # Todas anuláveis, e nulo quer dizer NÃO INFORMADO. Os registros que vieram
    # da planilha não responderam nada disto, e tratá-los como "não" inventaria
    # história.
    #: O que se esperava, escrito ANTES da reunião. Compare com `relato`.
    expectativa: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `aegea` ou `outra_parte`. Declinar é decisão, e o lado muda a leitura.
    declinado_por: Mapped[str | None] = mapped_column(Text, nullable=True)
    motivo_declinio: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: EM QUE CONDICOES A AGENDA FOI ACEITA.
    #:
    #: "Aceitaram, mas so para marco" e "aceitaram com o diretor, nao com o
    #: presidente" sao o que decide o preparo da reuniao, e nao tinham onde ser
    #: escritos: o "por que foi negado" existia, o "em que termos foi aceito"
    #: nao.
    #:
    #: Campo PROPRIO, e nao o mesmo de `motivo_declinio`: sao fatos diferentes,
    #: e um campo so para os dois faria trocar de situacao sobrescrever o texto
    #: do outro caso.
    nota_situacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: DE QUAIS agendas esta decorre. Plural desde a 0017: duas reunioes podem
    #: levar juntas a uma terceira, e uma reuniao pode abrir varias frentes.
    #:
    #: Era `origem_interacao_id`, uma coluna — um pai so. Isso descrevia uma
    #: arvore, e a realidade que o painel precisa mostrar e um grafo.
    origens: Mapped[list[InteracaoOrigem]] = relationship(
        "InteracaoOrigem",
        foreign_keys="InteracaoOrigem.interacao_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    #: QUEM DECORRE DESTA. O lado inverso, e so leitura (`viewonly`): quem
    #: escreve o elo e a agenda que descende, e ter os dois lados gravaveis
    #: seria a mesma relacao com duas donas.
    #:
    #: `selectin` faz UMA consulta para a pagina inteira. Sem isto, a coluna da
    #: Base que diz "faz parte de uma cadeia" custaria uma consulta por linha.
    #: MEDIDO: uma pagina de 200 agendas faz DUAS consultas em
    #: `interacao_origem`, uma por lado.
    #:
    #: Sem `cascade`: apagar esta agenda nao pode apagar as que decorrem dela.
    #:
    #: -- POR QUE NAO PASSA PELA AGENDA DO OUTRO LADO ---------------------
    #:
    #: A versao anterior destas duas relacoes usava `secondary="interacao_origem"`
    #: para ja excluir as ARQUIVADAS no proprio join. Funcionou, e trouxe N+1:
    #: 400 consultas numa pagina de 200 registros, medidas com `log_statement`.
    #:
    #: A causa e que `selectin` NAO carrega em lote relacao AUTORREFERENTE — e
    #: com `secondary` os dois lados sao `InteracaoRegistro`. O SQLAlchemy cai
    #: para carregamento por objeto sem erro nenhum: a regra fica certa e o
    #: custo multiplica em silencio.
    #:
    #: Quem filtra as arquivadas agora e o repositorio, com UMA consulta por
    #: pagina — ver `_arquivadas_entre`.
    derivadas: Mapped[list[InteracaoOrigem]] = relationship(
        "InteracaoOrigem",
        foreign_keys="InteracaoOrigem.origem_id",
        viewonly=True,
        lazy="selectin",
    )
    #: So a INTENCAO de continuidade, e por isso nao e redundante com
    #: `origens`: ela existe ANTES de haver agenda filha, e responde "achamos
    #: que isto continua?" — enquanto `origens` responde "de onde isto veio".
    #: Uma agenda pode prever desdobramento e nunca ter um; e o inverso tambem
    #: acontece, e a distancia entre os dois e material para o painel.
    #:
    #: A proxima agenda, quando existir, aponta para esta em `interacao_origem`
    #: — nao mais por coluna, desde a 0017.
    preve_desdobramento: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    #: O clima PREVISTO, na mesma escala do real (`clima_id`). Sem ele, comparar
    #: esperado com realizado seria leitura humana de texto livre.
    clima_esperado_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("clima.id"), nullable=True
    )

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
    outra_parte: Mapped[list[InteracaoInterlocutor]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    materiais: Mapped[list[Material]] = relationship(
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


class MaterialTema(Tabela):
    """De que assuntos um material trata.

    Espelha `ReferenciaTema` de propósito: a busca por assunto precisa ser a
    mesma nas duas procedências — o oficial que se leva para a reunião e o
    produzido que voltou dela.
    """

    __tablename__ = "material_tema"

    material_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("material.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )


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

    #: Previsto, presente ou ausente — NULO é "não informado".
    #:
    #: Não entra na chave: a pessoa tem um papel e uma presença nesta agenda,
    #: não uma linha por combinação.
    presenca: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class InteracaoInterlocutor(Tabela):
    """Participantes da outra parte, além do principal.

    O interlocutor PRINCIPAL continua em `interacao.interlocutor_id` — 67 usos
    em filtros, relatórios e exportação dependem dele. Esta tabela guarda os
    demais, e a API devolve os dois numa lista só.
    """

    __tablename__ = "interacao_interlocutor"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    interlocutor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interlocutor.id"), primary_key=True
    )
    presenca: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Quem representa a outra parte. No maximo um por agenda — indice unico
    #: parcial no banco garante.
    principal: Mapped[bool] = mapped_column(Boolean, default=False)


class Arquivo(Tabela):
    """Um arquivo no Blob Storage.

    `caminho` e a chave dentro do contenedor, e e GRAVADO em vez de derivado:
    convencao derivada quebra em silencio no dia em que a convencao muda, e os
    arquivos antigos ficam onde estavam enquanto o codigo passa a procura-los
    onde nunca estiveram.
    """

    __tablename__ = "arquivo"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    caminho: Mapped[str] = mapped_column(Text)
    nome: Mapped[str] = mapped_column(Text)
    tipo_conteudo: Mapped[str] = mapped_column(Text)
    tamanho: Mapped[int] = mapped_column(BigInteger)
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    #: `server_default`, como as demais tabelas deste modulo: quem carimba a
    #: hora e o banco, e nao o relogio de quem chamou. Eu tinha escrito
    #: `default=lambda: datetime.now(UTC)` copiando outro arquivo — e `UTC` nao
    #: e importado aqui, entao a primeira insercao estourou `NameError` de
    #: dentro do driver, longe da linha errada.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InteracaoOrigem(Tabela):
    """De qual agenda esta agenda decorre.

    MUITOS para muitos. `interacao_id` e quem descende; `origem_id` e quem veio
    antes. As duas apontam para `interacao`, e por isso toda relacao daqui
    precisa dizer QUAL das duas chaves usa — sem `foreign_keys` explicito o
    SQLAlchemy nao tem como escolher.
    """

    __tablename__ = "interacao_origem"

    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    origem_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Material(Tabela):
    """Documentos de uma agenda: apoio (antes), obtido e produzido (depois)."""

    __tablename__ = "material"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    interacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id", ondelete="CASCADE")
    )
    momento: Mapped[str] = mapped_column(Text)
    titulo: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O arquivo no Blob, quando houver. Deixou de ser reservada: a 0012 criou
    #: `arquivo` e ligou as duas. Material por LINK segue com ela nula — o
    #: `check` do banco exige um dos dois, nao os dois.
    arquivo_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("arquivo.id"), nullable=True
    )
    arquivo: Mapped[Arquivo | None] = relationship(lazy="joined")
    #: De qual REFERÊNCIA da biblioteca este material veio.
    #:
    #: Nula no material escrito à mão, que é a maioria. Preenchida no que a
    #: tela trouxe sozinha ao marcar um assunto da agenda — e é ela que permite
    #: desmarcar o assunto tirar de volta o que ele trouxe, sem levar junto o
    #: que a pessoa acrescentou.
    referencia_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("referencia.id", ondelete="SET NULL"),
        nullable=True,
    )
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: DE QUE ASSUNTOS O DOCUMENTO TRATA.
    #:
    #: `selectin` porque a listagem da Base lê todos de uma vez; `select` faria
    #: uma consulta por material, e a tela mostra dezenas.
    temas: Mapped[list[MaterialTema]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# QUEM DECLARA A CHAVE ESTRANGEIRA TRAZ O ALVO JUNTO.
#
# `material.referencia_id` aponta para `referencia`, que é declarada em
# `tabelas_referencias`. Sem este import, qualquer processo que importe só este
# módulo — um semeador, um script avulso — quebra na PRIMEIRA consulta com
# `NoReferencedTableError: could not find table 'referencia'`, uma mensagem que
# não menciona import nenhum. Aconteceu com `semear_enredos` num banco novo.
#
# NO FIM DO ARQUIVO, e não no topo: `tabelas_referencias` importa `Arquivo`
# daqui. No topo, os dois módulos se esperariam.
from app.banco import tabelas_referencias  # noqa: E402,F401
