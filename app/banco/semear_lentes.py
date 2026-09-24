"""O conteúdo das Lentes v2 que ainda não vem de lugar nenhum.

DE ONDE SAI CADA COISA (e é isto que o "?" de cada bloco mostra na tela):

    das planilhas       evolução, composição por tier, temas, concessionárias,
                        teor das mensagens — a ingestão já grava
    do CRM              a lente institucional inteira, contada na hora
    DESTE ARQUIVO       a matriz de jornalistas, a trajetória de rating, o
                        estudo de percepção e quantas mensagens foram
                        respondidas

O que este semeador grava veio do **Balanço Reputacional Jan-Ago 2026** do
cliente, transcrito — não é invenção, mas também não é medição desta
ferramenta. Por isso toda linha entra com `exemplo = true`, e a tela diz isso
no "?" de cada bloco em vez de apresentar o número como se tivesse saído da
base.

DUAS LACUNAS QUE ESTE ARQUIVO TAPA, E QUE PRECISAM SER COBRADAS:

    A Clipei não manda o AUTOR da matéria. Sem isso a exposição de cada
    jornalista não pode ser calculada pelo volume, e a matriz inteira é a que a
    agência montou à mão.

    A Approach não manda se a mensagem foi RESPONDIDA. Sem isso metade do
    gráfico principal da lente Clientes não existe, e os números aqui são os do
    relatório.

IDEMPOTENTE, E SÓ SOBRE O QUE É EXEMPLO. O `delete` de cada tabela filtra por
`exemplo = true`: rodar este arquivo de novo nunca apaga cadastro de verdade —
que é o cenário em que um semeador destrói trabalho de gente.

GERADO por `scripts/gerar_semeador_de_lentes.py`? NÃO: este arquivo é editado à
mão como qualquer outro. A formatação abaixo é longa porque o conteúdo é texto
de relatório, e quebrá-lo em constantes menores só afastaria a frase do lugar
onde ela é usada.

Rodar:
    python -m app.banco.semear_lentes
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.banco.sessao import obter_fabrica_de_sessao

# `Usuario` e `Interlocutor` entram para o mapeamento resolver as chaves
# estrangeiras — este semeador roda sozinho, fora do `main`.
from app.banco.tabelas_acesso import Usuario  # noqa: F401
from app.banco.tabelas_lentes import (
    CmRespostaMes,
    EstudoAtributo,
    EstudoPercepcao,
    EventoMercado,
    JornalistaMatriz,
)
from app.banco.tabelas_stakeholders import Interlocutor  # noqa: F401

logger = logging.getLogger(__name__)

#: O mês em que a curadoria de exemplo é gravada. É o mês que a base cobre
#: inteiro — as quatro planilhas têm junho.
MES = date(2026, 6, 1)

ORIGEM = "Balanço Reputacional Jan-Ago 2026 (relatório do cliente), transcrito"


# -- a matriz de jornalistas ---------------------------------------------------
#
# Relevância, exposição e proximidade, de 1 a 5. A soma dá a prioridade:
# P1 13–15 · P2 10–12 · P3 7–9 · P4 abaixo de 7.

JORNALISTAS: list[tuple[str, str, int, int, int]] = [
    ("Taís Hirata e Felipe Laurence", "Valor Econômico", 5, 5, 5),
    ("Elisa Calmon", "Neofeed", 5, 5, 5),
    ("Thiago Bethônico", "Folha de S.Paulo", 5, 5, 4),
    ("Juliana Estigarribia", "Bloomberg Línea", 5, 4, 5),
    ("Thierry Ogier", "LatinFinance", 5, 4, 3),
    ("Maria Fernanda Blaser", "REDD Intelligence", 5, 5, 2),
    ("Luciano Pádua", "Exame Infra", 4, 3, 5),
    ("João Sorima", "O Globo", 4, 3, 4),
    ("Márcio Juliboni", "Veja", 4, 2, 5),
    ("Beatriz Kawai", "Agência Infra", 3, 3, 1),
]


# -- o que aconteceu no mercado ------------------------------------------------
#
# O dia só é exato onde o próprio relatório o dá (as divulgações de resultado);
# nos demais vale o mês, que é o grão do eventograma.

EVENTOS: list[tuple[str, str, str, str, str | None, str | None, str | None]] = [
    ("2026-02-15", "governanca", "Vazamento do Termo de Acordo", "pressiona", None, None, None),
    (
        "2026-03-15",
        "resultado",
        "Atraso na divulgação das demonstrações financeiras",
        "pressiona",
        None,
        None,
        None,
    ),
    ("2026-04-10", "resultado", "Demonstrações financeiras de 2025", "misto", None, None, None),
    ("2026-05-07", "resultado", "Resultado do 1T26", "misto", None, None, None),
    ("2026-05-20", "operacao", "Brazil Week, em Nova York", "sustenta", None, None, None),
    ("2026-05-25", "rating", "S&P rebaixa para B", "pressiona", "S&P", None, "B · brAA-"),
    ("2026-05-25", "rating", "Fitch rebaixa para BB-", "pressiona", "Fitch", None, "BB- · brA+"),
    ("2026-05-25", "rating", "Moody's rebaixa para Ba3", "pressiona", "Moody's", None, "Ba3"),
    ("2026-06-15", "operacao", "Edital e proposta da Copasa", "misto", None, None, None),
    ("2026-07-15", "operacao", "Aumento de capital de até R$ 2,1 bi", "sustenta", None, None, None),
    ("2026-07-20", "rating", "Fitch move para B+", "pressiona", "Fitch", "BB- · brA+", "B+ · A"),
    (
        "2026-07-25",
        "outro",
        "Estudo de percepção com investidores e analistas",
        "misto",
        None,
        None,
        None,
    ),
    ("2026-08-05", "resultado", "Resultado do 2T26", "misto", None, None, None),
    ("2026-08-12", "governanca", "Saída do CFO", "pressiona", None, None, None),
    (
        "2026-08-20",
        "rating",
        "Moody's move para B2, perspectiva negativa",
        "pressiona",
        "Moody's",
        "Ba3",
        "B2",
    ),
]

#: A perspectiva só aparece onde a agência a declarou.
PERSPECTIVA_POR_NOTA = {"B2": "negativa"}


# -- o estudo de percepção -----------------------------------------------------

ESTUDO = {
    "instituto": "Brunswick",
    "data": date(2026, 6, 30),
    "amostra": 20,
    "publico": "Investidores e analistas, entrevistas em profundidade",
    "observacao": (
        "Junho e julho de 2026. Os demais atributos entram quando o estudo completo for "
        "liberado."
    ),
}

ATRIBUTOS: list[tuple[str, float, str]] = [
    (
        "Eficiência operacional",
        4.0,
        "Capacidade de executar projetos complexos e melhorar ativos.",
    ),
    (
        "Solidez financeira",
        1.8,
        (
            "A crítica não é ao crescimento, e sim a como foi financiado e à impossibilidade "
            "de auditá-lo."
        ),
    ),
]


# -- quantas mensagens foram respondidas ---------------------------------------
#
# Janeiro a agosto. As RECEBIDAS a ingestão conta sozinha, da própria base; o que
# o banco guarda aqui é só o que a planilha não traz.

RESPOSTAS: list[int] = [383, 325, 504, 492, 607, 465, 398, 561]



def _apagar_exemplos(sessao: Session) -> None:
    """Tira só o que este arquivo pôs. Cadastro de gente fica."""
    for tabela in (EventoMercado, JornalistaMatriz, CmRespostaMes):
        sessao.execute(delete(tabela).where(tabela.exemplo.is_(True)))
    # O atributo cai junto com o estudo, por `on delete cascade`.
    sessao.execute(delete(EstudoPercepcao).where(EstudoPercepcao.exemplo.is_(True)))


def principal() -> None:
    sessao = obter_fabrica_de_sessao()()
    try:
        _apagar_exemplos(sessao)

        for nome, veiculo, relevancia, exposicao, proximidade in JORNALISTAS:
            sessao.add(
                JornalistaMatriz(
                    nome=nome,
                    veiculo=veiculo,
                    relevancia=relevancia,
                    exposicao=exposicao,
                    proximidade=proximidade,
                    exemplo=True,
                )
            )

        for dia, tipo, texto, efeito, agencia, anterior, nova in EVENTOS:
            sessao.add(
                EventoMercado(
                    data=date.fromisoformat(dia),
                    tipo=tipo,
                    texto=texto,
                    efeito=efeito,
                    agencia=agencia,
                    nota_anterior=anterior,
                    nota_nova=nova,
                    perspectiva=PERSPECTIVA_POR_NOTA.get(nova or ""),
                    exemplo=True,
                )
            )

        estudo = EstudoPercepcao(**ESTUDO, exemplo=True)
        sessao.add(estudo)
        sessao.flush()
        for ordem, (atributo, nota, comentario) in enumerate(ATRIBUTOS):
            sessao.add(
                EstudoAtributo(
                    estudo_id=estudo.id,
                    atributo=atributo,
                    nota=nota,
                    comentario=comentario,
                    ordem=ordem,
                )
            )

        for indice, respondidas in enumerate(RESPOSTAS):
            sessao.add(
                CmRespostaMes(
                    mes=date(2026, indice + 1, 1),
                    respondidas=respondidas,
                    origem=ORIGEM,
                    exemplo=True,
                )
            )

        sessao.commit()
        quantos = len(JORNALISTAS) + len(EVENTOS) + len(ATRIBUTOS) + len(RESPOSTAS)
        logger.info("Lentes: %s linhas de exemplo gravadas.", quantos)
        print(f"Lentes: {quantos} linhas de exemplo gravadas (todas com exemplo=true).")
    finally:
        sessao.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    principal()
