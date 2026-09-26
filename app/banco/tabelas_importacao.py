"""As duas tabelas da importação. Espelha `migrations/0008_importacao.sql`.

A 0008 EXISTE DESDE ANTES DESTE CÓDIGO, e o cabeçalho dela diz por quê: a forma
das tabelas foi decidida junto com o resto do modelo, e `interacao.fonte`,
`interacao.origem_aba` e `interacao.origem_linha` já apontavam para este fluxo.
Este módulo mapeia o que já está lá e NÃO altera nada — nenhuma migration nova.

O DESENHO QUE A 0008 DESCREVE, e que a spec desta funcionalidade repete:

  1. o arquivo é lido e cada linha vira uma `importacao_linha`, com os dados
     brutos preservados
  2. a aplicação propõe uma interação (`proposta`) e lista o que não conseguiu
     resolver (`divergencias`)
  3. uma pessoa confere e decide
  4. só na confirmação as interações são criadas

O passo 3 é o ponto: importação de planilha sem conferência humana cria
duplicata de instituição em massa, e desfazer isso depois é pior que digitar de
novo.

CUIDADO COM OS DOIS PARES DE NOMES. Aqui a origem é `aba` e `linha_origem`; em
`interacao` os campos equivalentes se chamam `origem_aba` e `origem_linha`. Os
dois pares existem e são diferentes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela

#: As situações que o `check` da 0008 aceita. Nasce em `processando` e só vai a
#: `aguardando_conferencia` depois de as linhas estarem gravadas — é o que
#: impede um arquivo cujo processamento morreu no meio de aparecer como pronto
#: para conferir.
SITUACOES = ("processando", "aguardando_conferencia", "confirmada", "cancelada")

#: O que uma pessoa decidiu sobre uma linha, conforme o `check` da 0008.
DECISOES = ("pendente", "aceita", "corrigida", "descartada")


class Importacao(Tabela):
    __tablename__ = "importacao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: O nome que a pessoa deu ao arquivo. É por ele que ela reconhece a
    #: importação na lista, e não pelo uuid.
    arquivo_nome: Mapped[str] = mapped_column(Text)
    situacao: Mapped[str] = mapped_column(Text, default="processando")
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    # `timezone=True` nas duas: o banco guarda `timestamptz`, e mapear sem
    # timezone faz o valor voltar ingênuo — o mesmo erro que os módulos novos do
    # Score cometeram.
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ImportacaoLinha(Tabela):
    __tablename__ = "importacao_linha"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    importacao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("importacao.id", ondelete="CASCADE")
    )

    #: De onde veio, para a pessoa conseguir voltar à planilha e conferir.
    aba: Mapped[str] = mapped_column(Text)
    linha_origem: Mapped[int] = mapped_column(Integer)

    #: O que estava na célula, sem interpretação. PRESERVADO mesmo depois de
    #: aceito: é o que permite reprocessar quando a regra de leitura mudar, e
    #: responder de onde veio um registro.
    dados_brutos: Mapped[dict[str, Any]] = mapped_column(JSONB)

    #: O que a aplicação entendeu, no formato de uma interação. Nulo quando
    #: alguma divergência trava — não há proposta válida a guardar.
    proposta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    #: O que ela não conseguiu resolver sozinha. Lista vazia significa linha
    #: limpa; a tela de conferência ordena por esta coluna.
    #:
    #: CONSULTA-SE POR CONTENÇÃO (`divergencias @> '[{"campo":"..."}]'`), nunca
    #: com `->>`: os dois índices GIN da 0008 não entram com `->>`, e a consulta
    #: cai para varredura sequencial sem nada parecer errado.
    divergencias: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    decisao: Mapped[str] = mapped_column(Text, default="pendente")

    #: Preenchido na confirmação, ligando a linha da planilha ao registro criado.
    interacao_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interacao.id"), nullable=True
    )
