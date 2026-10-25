"""Religar o CRM dentro de um teste, para o caminho da fonte interna continuar medido.

A `0112` tirou o CRM do índice (`score_fonte.ativo = false`) e a `0114` o
desligou de qualquer lente, por decisão do dono do produto: as agendas ficam no
CRM, e os KPIs Reputacionais se medem de Clipei, Bites e Approach. O MECANISMO
da fonte interna continua no código — `_somas_do_crm`, `_serie_do_crm`, os
painéis de órgão e clima, as agendas da matriz de risco — e continua inteiro.

O QUE ESTE AUXILIAR PRESERVA, e é a razão de ele existir. Vários testes provam
coisas que NÃO são sobre a configuração de hoje e sim sobre o mecanismo: que
agenda escondida (`visivel = false`) não move a nota e não nomeia órgão em
painel, que a série da lente interna sai das interações, que a agenda de clima
tenso é incidente, que o recorte por lente deixa a agenda de fora. Apagá-los
junto com a decisão de produto jogaria fora garantias — a de privacidade,
principalmente — que precisam continuar valendo no dia em que o CRM voltar.

E É ELE QUE IMPEDE A MÁQUINA DE VIRAR CÓDIGO MORTO: sem estes testes, o caminho
da fonte interna ficaria sem cobertura nenhuma, apodrecendo em silêncio até
alguém religar e descobrir que não funciona mais.

AS TRÊS PONTAS JUNTAS, de propósito. Religar o CRM é mais do que um `update`
desde a `0114`:

  * a POLÍTICA (`dominio/fontes_do_score`) decide se fonte interna alimenta os
    KPIs — é o que faz a matriz de risco voltar a contar agenda;
  * `ativo` decide se ela entra na nota;
  * `lente_id` decide de que lente ela é.

Mudar uma e esquecer as outras produz um sistema incoerente, e é exatamente o
que este auxiliar existe para não deixar acontecer dentro de um teste. É também
a lista do "como se desfaz" escrita na migration e no módulo da política.

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

    #: A POLÍTICA PRIMEIRO, e com `raising=True` (o padrão): se alguém renomear
    #: a constante, este auxiliar falha em vez de ligar meia coisa e deixar
    #: vinte testes falhando longe daqui, por um motivo que não é o deles.
    monkeypatch.setattr(fontes_do_score, "FONTE_INTERNA_ALIMENTA_OS_KPIS", True)

    fonte.ativo = True
    fonte.lente_id = institucional.id
    sessao.flush()
    return fonte
