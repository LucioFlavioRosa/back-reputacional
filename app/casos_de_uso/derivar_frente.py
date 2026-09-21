"""Deriva a Frente de uma interação a partir do TIPO da instituição — a tela
não pergunta mais a Frente diretamente.

A REGRA, EM ORDEM:

  1. O tipo da instituição já basta, sozinho, para todos os tipos menos
     "entidade" — ver `FRENTE_UNICA_DO_TIPO` em `app/dominio/frentes.py`.
     Área interna cai aqui: sempre Interna. Proposição e credor também:
     sempre Legislativo e Bancos/Credores, sem depender de mais nada — são
     justamente os dois casos que uma derivação por categoria de público não
     tinha como cobrir, porque nenhuma categoria da taxonomia de públicos
     descreve uma proposição ou um credor.
  2. "entidade" é o único tipo que duas frentes conversam — Parceiros e
     Eventos, porque quem promove um evento é a mesma classe de instituição
     com quem se faz parceria. Formato "Evento" decide Eventos; qualquer
     outro formato (ou nenhum) decide Parceiros.

Categoria de público NÃO entra na derivação: ela é informativa (o campo
"Público" da tela), não normativa. Bloquear a criação da interação por falta
dela seria recusar registros que a Frente já sabe resolver sozinha — e a base
de desenvolvimento tem instituição de sobra ainda não classificada.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import FormatoInteracao
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.erros import RegraViolada
from app.dominio.frentes import FRENTE_UNICA_DO_TIPO, Frente


def derivar_frente(
    sessao: Session,
    *,
    instituicao_id: UUID,
    formato_interacao_id: int | None,
) -> Frente:
    instituicao = sessao.get(Instituicao, instituicao_id)
    if instituicao is None:
        raise RegraViolada(f"Instituição {instituicao_id} não existe.")

    # `tipo` é restrito por check constraint aos valores de
    # `TIPOS_DE_INSTITUICAO` — todo tipo que não é "entidade" está em
    # `FRENTE_UNICA_DO_TIPO` por construção, então não há um terceiro caminho
    # aqui a não ser "entidade".
    frente_unica = FRENTE_UNICA_DO_TIPO.get(instituicao.tipo)
    if frente_unica is not None:
        return frente_unica

    if formato_interacao_id is not None:
        formato = sessao.get(FormatoInteracao, formato_interacao_id)
        if formato is not None and formato.codigo == "evento":
            return Frente.EVENTOS

    return Frente.PARCEIROS
