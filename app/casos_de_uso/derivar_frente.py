"""Deriva a Frente de uma interação a partir do Formato e da categoria de
público da instituição — a tela não pergunta mais a Frente diretamente.

A REGRA, EM ORDEM (ver `0039_frente_padrao_por_categoria.sql` para o porquê
de cada passo):

  1. Instituição do tipo `area_interna` → sempre Interna. Área interna nunca
     tem categoria de público (não é público externo), então nem chega a
     olhar isso — checar primeiro evita um erro "sem categoria" sem sentido
     numa demanda que é, por definição, sem contraparte.
  2. Formato "Evento" → sempre Eventos, direto — bate 1 pra 1 com o que essa
     frente já significa hoje, não depende de quem é a contraparte.
  3. Senão, `categoria_publico.frente_padrao_id` da instituição decide.
     Instituição sem categoria classificada (e não interna) RECUSA com
     `RegraViolada`, em vez de adivinhar — pedir para classificar primeiro é
     mais barato do que uma Frente errada silenciosa.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, FormatoInteracao
from app.banco.tabelas_catalogo import Frente as FrenteTabela
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.erros import RegraViolada
from app.dominio.frentes import Frente


def derivar_frente(
    sessao: Session,
    *,
    instituicao_id: UUID,
    formato_interacao_id: int | None,
) -> Frente:
    instituicao = sessao.get(Instituicao, instituicao_id)
    if instituicao is None:
        raise RegraViolada(f"Instituição {instituicao_id} não existe.")

    if instituicao.tipo == "area_interna":
        return Frente.INTERNA

    if formato_interacao_id is not None:
        formato = sessao.get(FormatoInteracao, formato_interacao_id)
        if formato is not None and formato.codigo == "evento":
            return Frente.EVENTOS

    if instituicao.categoria_publico_id is None:
        raise RegraViolada(
            f"'{instituicao.nome}' ainda não tem uma categoria de público definida. "
            "Classifique a instituição em Administração > Instituições antes de "
            "registrar esta interação."
        )

    categoria = sessao.get(CategoriaPublico, instituicao.categoria_publico_id)
    if categoria is None or categoria.frente_padrao_id is None:
        raise RegraViolada(
            f"A categoria de público de '{instituicao.nome}' não tem uma frente "
            "padrão configurada — isso é um problema de dados, não algo que se "
            "resolva na tela."
        )

    frente_row = sessao.get(FrenteTabela, categoria.frente_padrao_id)
    if frente_row is None:
        raise RegraViolada("A frente padrão configurada para esta categoria não existe mais.")

    return Frente(frente_row.codigo)
