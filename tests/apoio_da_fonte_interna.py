"""Religar o CRM dentro de um teste, para o caminho da fonte interna continuar medido.

A `0108` tirou o CRM do índice (`score_fonte.ativo = false`), por decisão do dono
do produto: a lente Institucional passou a ser imprensa recortada. O MECANISMO da
fonte interna continua no código — `_somas_do_crm`, `_serie_do_crm`, os painéis de
órgão e clima — e continua ligável por um `update` de uma coluna.

O QUE ESTE AUXILIAR PRESERVA. Vários testes provavam coisas que NÃO são sobre a
configuração de hoje e sim sobre o mecanismo: que agenda escondida (`visivel =
false`) não move a nota e não nomeia órgão em painel, que a série da lente interna
sai das interações, que lente interna recusa recorte de menção. Apagá-los junto
com a decisão de produto jogaria fora garantias — a de privacidade, principalmente
— que precisam continuar valendo no dia em que alguém religar o CRM.

Religar vale só para a transação do teste, que termina em rollback.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import ScoreFonte


def ligar_o_crm(sessao: Session) -> ScoreFonte:
    """Devolve a fonte interna ao índice, só nesta transação."""
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "crm"))
    assert fonte is not None, "a fonte interna do CRM tem de existir no cadastro"
    fonte.ativo = True
    sessao.flush()
    return fonte
