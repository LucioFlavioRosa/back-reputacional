"""Deriva o TIPO de uma instituição — a tela de cadastro não o pergunta mais.

A REGRA, EM ORDEM:
  1. `tipo` informado vale: quem manda está dizendo o que quer, e a categoria
     não passa por cima — é o que permite corrigir, na edição, um banco
     credor que a taxonomia não distingue de um investidor.
  2. Sem `tipo`, a categoria de público decide (`TIPO_DA_CATEGORIA_DE_PUBLICO`,
     em `app/dominio/frentes.py`).
  3. Sem os dois: na edição, o tipo gravado fica; na criação não há de onde
     tirar um — recusar é melhor do que gravar uma instituição que nunca
     aparece em formulário nenhum.

É o irmão de `derivar_frente`: aquele deriva a frente da INTERAÇÃO a partir do
tipo da instituição; este deriva o tipo da INSTITUIÇÃO a partir do público.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico
from app.dominio.erros import RegraViolada
from app.dominio.frentes import TIPO_DA_CATEGORIA_DE_PUBLICO, TIPOS_DE_INSTITUICAO


def derivar_tipo(
    sessao: Session,
    *,
    tipo: str | None,
    categoria_publico_id: int | None,
    atual: str | None,
) -> str:
    if tipo is not None:
        if tipo not in TIPOS_DE_INSTITUICAO:
            raise RegraViolada(
                f"Tipo invalido: {tipo!r}. Use {', '.join(sorted(TIPOS_DE_INSTITUICAO))}."
            )
        return tipo
    if categoria_publico_id is not None:
        # Quem chama já conferiu que a categoria existe e está ativa.
        categoria = sessao.get(CategoriaPublico, categoria_publico_id)
        derivado = TIPO_DA_CATEGORIA_DE_PUBLICO.get(categoria.codigo) if categoria else None
        if derivado is not None:
            return derivado
    if atual is not None:
        return atual
    raise RegraViolada(
        "Informe a categoria de publico: e dela que sai o tipo da instituicao, "
        "e sem tipo ela nao apareceria em formulario nenhum."
    )
