"""As Lentes v2, no banco. Espelha `migrations/0049`.

O dossiê de cada lente tem duas metades. Uma é CALCULADA das menções que a
ingestão já grava — evolução, composição, rankings. A outra não sai de planilha
nenhuma:

    evento_mercado      o que aconteceu: resultados, rating, operações
    estudo_percepcao    o que o mercado responde quando perguntam
    estudo_atributo     nota de 1 a 5 por atributo do estudo
    jornalista_matriz   com quem a imprensa fala, e quão perto estamos
    cm_resposta_mes     quantas mensagens foram respondidas no mês

TRÊS DELAS NASCEM COM DADO DE EXEMPLO, e dizem isso. `exemplo` não é um detalhe
de semeadura: é o que a tela lê para avisar, no "?" de cada bloco, que aquele
número veio do relatório do cliente e não da base — ver o cabeçalho da 0049.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class EventoMercado(Tabela):
    """Um fato de mercado: divulgação, ação de rating, operação, governança."""

    __tablename__ = "evento_mercado"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    data: Mapped[date] = mapped_column(Date)
    tipo: Mapped[str] = mapped_column(Text)
    agencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    nota_anterior: Mapped[str | None] = mapped_column(Text, nullable=True)
    nota_nova: Mapped[str | None] = mapped_column(Text, nullable=True)
    perspectiva: Mapped[str | None] = mapped_column(Text, nullable=True)
    texto: Mapped[str] = mapped_column(Text)
    #: `sustenta` | `pressiona` | `misto` — pinta a borda do mês no eventograma.
    efeito: Mapped[str] = mapped_column(Text)
    exemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class EstudoPercepcao(Tabela):
    """Um estudo de percepção — instituto, data, amostra."""

    __tablename__ = "estudo_percepcao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instituto: Mapped[str] = mapped_column(Text)
    data: Mapped[date] = mapped_column(Date)
    amostra: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publico: Mapped[str | None] = mapped_column(Text, nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    exemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class EstudoAtributo(Tabela):
    """A nota de um atributo dentro de um estudo, de 1 a 5."""

    __tablename__ = "estudo_atributo"

    estudo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("estudo_percepcao.id"), primary_key=True
    )
    atributo: Mapped[str] = mapped_column(Text, primary_key=True)
    nota: Mapped[float] = mapped_column(Numeric(2, 1))
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordem: Mapped[int] = mapped_column(SmallInteger, default=0)


class JornalistaMatriz(Tabela):
    """Relevância, exposição e proximidade de um jornalista, de 1 a 5."""

    __tablename__ = "jornalista_matriz"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    interlocutor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interlocutor.id"), nullable=True
    )
    nome: Mapped[str] = mapped_column(Text)
    veiculo: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevancia: Mapped[int] = mapped_column(SmallInteger)
    exposicao: Mapped[int] = mapped_column(SmallInteger)
    proximidade: Mapped[int] = mapped_column(SmallInteger)
    #: O que a base sugeriria, quando a Clipei mandar o autor. Nula hoje.
    exposicao_sugerida: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    exemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    atualizado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class CmRespostaMes(Tabela):
    """Quantas mensagens foram respondidas no mês.

    Não vem da planilha: a aba CM diz o que chegou, não o que foi respondido.
    """

    __tablename__ = "cm_resposta_mes"

    mes: Mapped[date] = mapped_column(Date, primary_key=True)
    respondidas: Mapped[int] = mapped_column(Integer)
    origem: Mapped[str | None] = mapped_column(Text, nullable=True)
    exemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    atualizado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    atualizado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class MencaoNaoClassificada(Tabela):
    """Quantas menções chegaram sem sentimento — o segundo estado da §2.

    São publicações reais que o fornecedor não leu. Não viram `mencao` porque
    `sentimento` é obrigatório e "neutro" seria inventar leitura; e não podem
    sumir, porque um mês com mil menções sem classificação desenhado como mês
    vazio mente sobre o volume da conversa.
    """

    __tablename__ = "mencao_nao_classificada"

    fonte_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("score_fonte.id"), primary_key=True
    )
    mes: Mapped[date] = mapped_column(Date, primary_key=True)
    total: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(server_default=func.now())
