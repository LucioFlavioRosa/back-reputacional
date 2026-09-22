"""O bloco da consulta só existe no tipo "Consulta recebida".

POR QUE ISTO NÃO MORA NO DOMÍNIO. `Interacao` guarda `formato_interacao_id`,
um número — e a regra é sobre o CÓDIGO do tipo, que só o banco sabe traduzir.
Mesma situação de `derivar_frente` e `derivar_tipo`: regra de negócio que
precisa de uma consulta, e por isso mora em `casos_de_uso`.

POR QUE NÃO BASTA A TELA. O formulário já manda `consulta: null` quando o
tipo deixa de ser esse. Mas a API aceita `PATCH` de um campo só: mudar o tipo
de "Consulta recebida" para "Reunião" sem tocar no bloco deixaria uma reunião
com prazo de resposta e alegações — e a aba de Sinais passaria a contar, como
premissa em circulação, uma pergunta que ninguém fez. Quem garante invariante
é o servidor.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import FormatoInteracao
from app.dominio.erros import RegraViolada
from app.dominio.interacao import Interacao

#: O código do tipo, o mesmo que a `0046` semeia e que o front conhece.
CODIGO_DA_CONSULTA = "consulta_recebida"


def validar_consulta(sessao: Session, interacao: Interacao) -> None:
    """Recusa o bloco fora do tipo, e o tipo sem o bloco que o explica."""
    codigo = (
        sessao.scalar(
            select(FormatoInteracao.codigo).where(
                FormatoInteracao.id == interacao.formato_interacao_id
            )
        )
        if interacao.formato_interacao_id is not None
        else None
    )
    e_consulta = codigo == CODIGO_DA_CONSULTA

    if interacao.consulta is not None and not e_consulta:
        raise RegraViolada(
            'Os dados da consulta só valem no tipo de interação "Consulta '
            "recebida\". Troque o tipo, ou remova o bloco."
        )

    # ALEGAÇÃO SEM CONSULTA NÃO EXISTE: ela é o que uma pergunta recebida deu
    # como fato. Pendurá-la numa reunião faria a aba contar, como premissa em
    # circulação, algo que ninguém perguntou.
    if interacao.alegacoes and not e_consulta:
        raise RegraViolada(
            'As alegações pertencem a uma consulta recebida — é o tipo de '
            "interação que registra o que perguntaram."
        )
