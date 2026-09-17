"""A biblioteca de referências. Espelha `migrations/0026` + `0028`.

O ARQUIVO MORA NO BLOB, numa árvore própria: `referencias/<assunto>/<tipo>/`.
Uma referência tem
VERSÕES: a tela mostra a mais recente, e as anteriores respondem "o que a gente
levou naquela reunião de março".

O ASSUNTO PRINCIPAL define a pasta no blob — ver `caminho_da_referencia`. A
referência cobre vários assuntos e `ReferenciaTema` guarda todos; o byte mora
num lugar só, porque copiá-lo criaria duas verdades que envelhecem separado.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.banco.sessao import Tabela
from app.banco.tabelas_interacoes import Arquivo


class ReferenciaTema(Tabela):
    """O vínculo referência ↔ assunto. É por ele que a agenda encontra material."""

    __tablename__ = "referencia_tema"

    referencia_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("referencia.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )


class Referencia(Tabela):
    __tablename__ = "referencia"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    titulo: Mapped[str] = mapped_column(Text)
    #: O assunto que define a PASTA no blob.
    #:
    #: Nulo no banco e obrigatório na API: a referência nasce em duas escritas
    #: — a linha e a primeira versão — e um `not null` aqui obrigaria a ordem
    #: inversa da que a rota usa.
    tema_principal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tema.id"), nullable=True
    )
    #: `posicionamento` | `qa` | `release` | `apresentacao` | `dados` |
    #: `nota_tecnica`. É por tipo que se procura material antes de uma reunião:
    #: "onde está o Q&A" vem antes de "qual era o nome do arquivo".
    tipo: Mapped[str] = mapped_column(Text)
    resumo: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=None, insert_default=func.now()
    )

    #: `selectin` porque a tela lista todas com seus tópicos: `lazy="select"`
    #: faria uma consulta por referência, e a biblioteca é lida inteira a cada
    #: abertura da aba.
    vinculos: Mapped[list[ReferenciaTema]] = relationship(
        primaryjoin="Referencia.id == ReferenciaTema.referencia_id",
        foreign_keys=lambda: [ReferenciaTema.referencia_id],
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    #: `selectin` pelo mesmo motivo: toda listagem precisa da versão mais
    #: recente de cada referência.
    versoes: Mapped[list[ReferenciaVersao]] = relationship(
        back_populates="referencia",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ReferenciaVersao.numero",
    )

    @property
    def temas(self) -> list[int]:
        return sorted(vinculo.tema_id for vinculo in self.vinculos)

    @property
    def versao_atual(self) -> ReferenciaVersao | None:
        """A de maior número — a que a tela mostra.

        `None` só existe entre a criação da linha e a primeira versão, dentro
        da mesma transação: uma referência sem versão não sai da rota.
        """
        return max(self.versoes, key=lambda v: v.numero, default=None)


class ReferenciaVersao(Tabela):
    """Uma versão de uma referência: o arquivo, a data dele e quem subiu."""

    __tablename__ = "referencia_versao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    referencia_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("referencia.id", ondelete="CASCADE")
    )
    #: 1, 2, 3… na ordem em que entraram. Ordena o histórico sem depender de
    #: data: duas versões subidas no mesmo dia continuam tendo ordem.
    numero: Mapped[int] = mapped_column(Integer)
    #: Nulo quando a versão vive só do Conteúdo, abaixo — desde que o arquivo
    #: virou opcional. Uma versão sempre tem UM dos dois, nunca nenhum; quem
    #: garante isso é a rota, não esta coluna, para não travar a leitura das
    #: versões de antes deste campo existir.
    arquivo_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("arquivo.id"), nullable=True
    )
    #: A data DO DOCUMENTO, e não a do upload: o arquivo pode ser de março e
    #: entrar aqui em agosto.
    atualizado_em: Mapped[date] = mapped_column(Date)
    #: O que mudou nesta versão. É o que responde "por que trocaram" quando
    #: alguém compara duas.
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O texto desta versão. Nulo nas versões de antes deste campo existir —
    #: não há valor real para inventar ali.
    conteudo: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=None, insert_default=func.now()
    )

    referencia: Mapped[Referencia] = relationship(back_populates="versoes")
    #: O nome, o tipo e o tamanho vêm junto: a tela mostra "v3 · ata.pdf ·
    #: 190 KB" sem uma segunda ida ao servidor. Nulo quando a versão não tem
    #: arquivo.
    arquivo: Mapped[Arquivo | None] = relationship(lazy="joined")
