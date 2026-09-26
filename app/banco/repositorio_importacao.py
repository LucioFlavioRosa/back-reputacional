"""Grava e lê uma importação e as linhas dela.

O QUE VAI PARA O JSONB TEM DE SER JSON. As células de uma planilha chegam com
`date` do openpyxl, e a proposta carrega `UUID` e `date` do Pydantic — nenhum dos
dois sobrevive a `json.dumps`. `para_json` converte na fronteira, uma vez, em vez
de cada chamador lembrar: esquecer a conversão dá `TypeError` no commit, longe do
código que montou o dado, e com a transação já suja.

A CONSULTA EM `divergencias` USA CONTENÇÃO (`@>`), nunca `->>`. Os dois índices
GIN da 0008 não entram com `->>`, e a consulta cai para varredura sequencial sem
nada parecer errado. A própria migration deixa o exemplo.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_importacao import Importacao, ImportacaoLinha
from app.dominio.erros import NaoEncontrado


def para_json(valor: Any) -> Any:
    """O mesmo dado, com o que o JSON não aceita virado em texto.

    `time` E `Decimal` ESTÃO AQUI porque uma planilha os produz sem aviso: uma
    célula formatada como hora num campo livre (`Local`, `Observação`) chega
    `time`, e uma célula numérica chega `Decimal`. Sem a conversão, o erro só
    aparece no flush do JSONB — longe de quem montou o dado, com a transação já
    suja. Foi um achado de revisão, não hipótese.
    """
    if isinstance(valor, Mapping):
        return {str(chave): para_json(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [para_json(item) for item in valor]
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, Decimal):
        # Uma célula numérica do Excel pode chegar `Decimal`, e `json.dumps` não
        # sabe serializá-la. `float` perde precisão em teoria; aqui o valor é
        # texto livre que ninguém soma, e `str` preservaria as casas de um
        # número que a pessoa digitou — é o que ela reconhece de volta.
        return str(valor)
    return valor


def criar(sessao: Session, *, arquivo_nome: str, criado_por: uuid.UUID) -> Importacao:
    """A importação em `processando`, antes de qualquer linha.

    NASCE EM `processando` de propósito: se o processamento morrer no meio, a
    importação fica visivelmente incompleta em vez de aparecer como pronta para
    conferir, com metade das linhas.
    """
    importacao = Importacao(
        arquivo_nome=arquivo_nome, criado_por=criado_por, situacao="processando"
    )
    sessao.add(importacao)
    sessao.flush()
    return importacao


def gravar_linha(
    sessao: Session,
    *,
    importacao_id: uuid.UUID,
    aba: str,
    linha_origem: int,
    dados_brutos: Mapping[str, Any],
    proposta: Mapping[str, Any] | None,
    divergencias: Sequence[Any],
) -> ImportacaoLinha:
    linha = ImportacaoLinha(
        importacao_id=importacao_id,
        aba=aba,
        linha_origem=linha_origem,
        dados_brutos=para_json(dados_brutos),
        proposta=para_json(proposta) if proposta is not None else None,
        divergencias=para_json(divergencias),
    )
    sessao.add(linha)
    return linha


def marcar_aguardando_conferencia(sessao: Session, importacao: Importacao) -> None:
    """Só depois de as linhas estarem gravadas — ver `criar`."""
    importacao.situacao = "aguardando_conferencia"
    sessao.flush()


def linhas_com(
    sessao: Session, importacao_id: uuid.UUID, *, campo: str, valor: str
) -> list[ImportacaoLinha]:
    """As linhas cuja lista de divergências contém este `(campo, valor)`.

    SÓ AS NÃO RESOLVIDAS. Uma divergência já decidida continua na lista, com
    `acao` preenchido — e encontrá-la de novo faria um segundo clique sobrescrever
    a decisão da pessoa em silêncio, trocando "apontar para X" por "criar" sem
    nada avisar. A guarda de "zero linhas alcançadas" só protege se esta consulta
    não devolver o que já foi resolvido.

    USA CONTENÇÃO (`@>`) e não `->>`: os dois índices GIN da 0008 não entram com
    `->>`, e a consulta cairia para varredura sequencial sem nada parecer errado.
    A própria migration deixa este exemplo escrito. O filtro de `acao` é feito
    em Python porque "esta chave está ausente" não se expressa por contenção — e
    o `@>` já reduziu o conjunto a um punhado de linhas.
    """
    candidatas = sessao.scalars(
        select(ImportacaoLinha)
        .where(
            ImportacaoLinha.importacao_id == importacao_id,
            ImportacaoLinha.divergencias.contains([{"campo": campo, "valor": valor}]),
        )
        .order_by(ImportacaoLinha.aba, ImportacaoLinha.linha_origem)
    ).all()
    return [
        linha
        for linha in candidatas
        if any(
            bruta.get("campo") == campo
            and bruta.get("valor") == valor
            and not bruta.get("acao")
            for bruta in (linha.divergencias or [])
        )
    ]


def obter(sessao: Session, importacao_id: uuid.UUID) -> Importacao:
    importacao = sessao.get(Importacao, importacao_id)
    if importacao is None:
        raise NaoEncontrado(f"Importação {importacao_id} não encontrada.")
    return importacao


def linhas_de(sessao: Session, importacao_id: uuid.UUID) -> list[ImportacaoLinha]:
    """As linhas na ordem do arquivo — é a ordem em que a pessoa preencheu.

    Ordena por `(aba, linha_origem)` e não por `id`: o `bigserial` reflete a
    ordem de inserção, que hoje coincide, mas amarrar a apresentação à ordem de
    escrita faria a tela mudar se algum dia as linhas fossem gravadas em lote
    por aba.
    """
    return list(
        sessao.scalars(
            select(ImportacaoLinha)
            .where(ImportacaoLinha.importacao_id == importacao_id)
            .order_by(ImportacaoLinha.aba, ImportacaoLinha.linha_origem)
        ).all()
    )
