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
from app.dominio.importacao_de_agendas import (
    ABA_DAS_DECLARACOES,
    CHAVE_DOS_CAMPOS_DECLARADOS,
    CHAVE_DOS_NOMES_DECLARADOS,
)


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


def gravar_proposta(sessao: Session, linha: ImportacaoLinha, proposta) -> None:
    """Regrava proposta e divergências de uma linha JÁ EXISTENTE.

    Usado quando a pessoa completa uma célula na conferência: a linha é reproposta
    e o resultado substitui o anterior. `gravar_linha` cria; esta atualiza.
    """
    linha.proposta = (
        para_json(proposta.entrada.model_dump(mode="json"))
        if proposta.entrada is not None
        else None
    )
    linha.divergencias = para_json(
        [
            {
                "campo": divergencia.campo,
                "valor": divergencia.valor,
                "mensagem": divergencia.mensagem,
                "trava": divergencia.trava,
                "coluna": divergencia.coluna,
                "sugestoes": list(divergencia.sugestoes),
                "acao": divergencia.acao,
                "alvo": divergencia.alvo,
                "declarado": divergencia.declarado,
            }
            for divergencia in proposta.divergencias
        ]
    )
    sessao.flush()


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
            .where(
                ImportacaoLinha.importacao_id == importacao_id,
                # A LINHA DAS DECLARAÇÕES FICA DE FORA, e o filtro é AQUI porque este é
                # o único lugar por onde as linhas saem do banco: oito chamadores as
                # pedem — a tela, o PATCH, a confirmação —, e nenhum deles quer uma
                # linha que não é agenda. Filtrar em cada um seria oito chances de
                # esquecer, e o esquecimento apareceria como linha vazia na conferência
                # ou como uma agenda a mais na contagem. Quem quer as declarações chama
                # `declaracoes_de`.
                ImportacaoLinha.aba != ABA_DAS_DECLARACOES,
            )
            .order_by(ImportacaoLinha.aba, ImportacaoLinha.linha_origem)
        ).all()
    )


def gravar_declaracoes(
    sessao: Session,
    *,
    importacao_id: uuid.UUID,
    nomes: Mapping[str, Any],
    campos: Mapping[str, Any],
) -> None:
    """Guarda o que a pessoa declarou nas abas de cadastro, para depois do upload.

    UMA LINHA RESERVADA e não uma coluna nova: a 0008 não tem coluna para isto, e
    acrescentá-la seria migration para um dado que é rastro do arquivo — a mesma decisão
    que a herança do `idem` já tomou ao viver dentro de `dados_brutos`.

    OS CONJUNTOS VIRAM LISTAS porque `frozenset` não é JSON. `declaracoes_de` os devolve
    como conjunto de novo, e é o único lugar que precisa saber disso.
    """
    sessao.add(
        ImportacaoLinha(
            importacao_id=importacao_id,
            aba=ABA_DAS_DECLARACOES,
            linha_origem=0,
            dados_brutos=para_json(
                {
                    CHAVE_DOS_NOMES_DECLARADOS: {
                        chave: sorted(valores) for chave, valores in nomes.items()
                    },
                    CHAVE_DOS_CAMPOS_DECLARADOS: campos,
                }
            ),
            proposta=None,
            divergencias=[],
        )
    )


def declaracoes_de(
    sessao: Session, importacao_id: uuid.UUID
) -> tuple[dict[str, frozenset[str]], dict[str, dict[str, dict[str, Any]]]]:
    """As declarações guardadas no upload: (nomes por vocabulário, campos por nome).

    VAZIO PARA IMPORTAÇÃO ANTIGA, e não erro: as que foram criadas antes desta linha
    existir continuam abertas para conferência, e quem chama já sabe se virar sem —
    reconstruindo o que puder das divergências. Vazio é a resposta honesta.
    """
    linha = sessao.scalars(
        select(ImportacaoLinha).where(
            ImportacaoLinha.importacao_id == importacao_id,
            ImportacaoLinha.aba == ABA_DAS_DECLARACOES,
        )
    ).first()
    if linha is None:
        return {}, {}
    guardado = linha.dados_brutos or {}
    nomes = guardado.get(CHAVE_DOS_NOMES_DECLARADOS) or {}
    campos = guardado.get(CHAVE_DOS_CAMPOS_DECLARADOS) or {}
    return (
        {chave: frozenset(valores) for chave, valores in nomes.items()},
        dict(campos),
    )
