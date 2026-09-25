"""Deriva a Esfera de uma interação a partir da INSTITUIÇÃO com quem se falou —
a tela não pergunta mais a Esfera diretamente.

O IRMÃO DE `derivar_frente`, e nasceu do mesmo buraco. O campo "Esfera" saiu do
formulário de cadastro e QUATRO telas continuaram lendo `interacao.esfera_id`: o
ranking "Esfera e abrangência" do Painel, a coluna e a exportação da Base, a
linha de metadados da Ficha e o filtro do recorte. Sem derivação, toda agenda
criada dali em diante nascia com o campo nulo, caía em "—" nas quatro, nunca
casava com o filtro — e não havia tela em lugar nenhum capaz de corrigir.

POR QUE DERIVAR, E NÃO DEVOLVER O CAMPO. É a única das saídas em que o dado não
pode divergir da instituição: uma agenda com o Ministério das Cidades é federal
porque o Ministério é federal, e não porque quem registrou marcou certo. Some um
campo do formulário e some a classe inteira de erro em que a esfera da agenda
contradiz o cadastro do órgão.

A REGRA É UMA LINHA, e é de propósito: `Instituicao.esfera_id`. Não há segundo
critério, não há desempate, não há caso "entidade" como na Frente. Se um dia
houver, ele nasce aqui e não espalhado pelos chamadores.

NULO É RESPOSTA, E NÃO ERRO. A instituição que ninguém classificou existe, e
recusar a agenda por causa dela bloquearia quem não errou nada. O "—" na tela é
o retrato honesto de um cadastro incompleto, e o lugar de consertar passa a ser
o cadastro da instituição — que é exatamente o ganho de derivar.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.erros import RegraViolada


def derivar_esfera(sessao: Session, *, instituicao_id: UUID) -> int | None:
    instituicao = sessao.get(Instituicao, instituicao_id)
    if instituicao is None:
        # MESMO CONTRATO DE `derivar_frente`: id que não existe é erro de
        # domínio, e não `None`. Devolver nulo aqui confundiria "a instituição
        # não tem esfera" — um cadastro a completar — com "a instituição não
        # existe", que é um payload inválido.
        raise RegraViolada(f"Instituição {instituicao_id} não existe.")
    return instituicao.esfera_id
