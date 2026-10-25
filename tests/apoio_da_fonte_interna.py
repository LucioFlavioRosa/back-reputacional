"""Religar o CRM dentro de um teste, para o caminho da fonte interna seguir medido.

A `0112` tirou o CRM do índice e a `0114` o desligou de qualquer lente, mas o
mecanismo continua no código: `_somas_do_crm`, `_serie_do_crm`, os painéis de
órgão e clima, as agendas da matriz de risco.

Vários testes provam o MECANISMO, e não a configuração de hoje: que agenda
escondida não move a nota nem nomeia órgão em painel, que a série da lente
interna sai das interações, que a agenda de clima tenso é incidente. Apagá-los
junto com a decisão de produto jogaria fora garantias — a de privacidade,
principalmente — e deixaria o caminho da fonte interna sem cobertura nenhuma.

Religar são três pontas, e mudar uma e esquecer as outras produz sistema
incoerente:

  * a POLÍTICA (`dominio/fontes_do_score`) — é o que faz a matriz de risco
    voltar a contar agenda;
  * `ativo` — se ela entra na nota;
  * `lente_id` — de que lente ela é.

Tudo vale só para o teste: o banco termina em rollback e o `monkeypatch` se
desfaz sozinho.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Lente, ScoreFonte
from app.dominio import fontes_do_score


def ligar_o_crm(sessao: Session, monkeypatch: pytest.MonkeyPatch) -> ScoreFonte:
    """Põe o sistema no estado em que o CRM alimenta os KPIs, só neste teste."""
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "crm"))
    assert fonte is not None, "a fonte interna do CRM tem de existir no cadastro"

    institucional = sessao.scalar(select(Lente).where(Lente.codigo == "institucional"))
    assert institucional is not None, "a lente institucional tem de existir no cadastro"

    #: A política primeiro, e com `raising=True` (o padrão): se alguém
    #: renomear a constante, este auxiliar falha aqui em vez de ligar meia
    #: coisa e deixar vinte testes falhando longe daqui.
    monkeypatch.setattr(fontes_do_score, "FONTE_INTERNA_ALIMENTA_OS_KPIS", True)

    fonte.ativo = True
    fonte.lente_id = institucional.id
    sessao.flush()
    return fonte
