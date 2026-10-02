"""Dados fake para exercitar a taxonomia de temas v1.3 (`migrations/0053`).

POR QUE UM QUARTO SEMEADOR, E NÃO ENREDOS NOVOS
------------------------------------------------
`semear_enredos.py` é claro sobre seu padrão: "forma não basta; o conteúdo
também é a demonstração" — cada tema ali foi escrito à mão, lido de uma
planilha real. Escrever 38 enredos novos no mesmo padrão seria autoria, não
geração, e a taxonomia v1.3 ainda está em validação por área (a coluna "Área
concorda?" da planilha de origem está vazia em todas as linhas) — não vale o
investimento narrativo antes disso fechar.

Este semeador é deliberadamente MECÂNICO: cobre cada um dos temas novos (os
que têm `macro_tema_id`, ou seja, vieram da 0053) com um volume pequeno — o
bastante para o front ter o que mostrar em cada macro tema e bloco, sem
pretender ser uma base de demonstração narrativa. REAPROVEITA toda a
infraestrutura de conteúdo plausível de `semear_enredos` (elenco de
instituições/pessoas, textos por frente, formato de `extensao`) em vez de
duplicá-la: só o sorteio do TEMA é diferente — aqui é determinístico, um a
um pelos 38 temas, não um sorteio livre do dicionário inteiro.

Idempotente: para por `origem_aba`, como os demais semeadores.
"""

from __future__ import annotations

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.repositorio_interacoes import RepositorioSQL
from app.banco.semear_enredos import _autor, _elenco, _uma_solta
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.dominio.frentes import Frente

ORIGEM = "demonstracao-taxonomia-v1.3"

#: Semente própria: uma base fixa e repetível, independente da de
#: `semear_enredos` (que usa 20260907) — as duas convivem sem se influenciar.
SEMENTE = 20261001

#: Quantas interações por tema novo. Pequeno de propósito: o objetivo é ter
#: ALGO em cada macro tema e bloco para o front exercitar, não replicar o
#: volume de uma base real — ver `migrations/0053` sobre por que a taxonomia
#: ainda não tem o peso editorial para isso.
POR_TEMA = (2, 2, 3)

#: As frentes entre as quais se alterna para dar variedade de instituição e
#: texto — todas as que `semear_enredos.SOLTAS_POR_FRENTE`/`QUANTAS_SOLTAS`
#: já cobrem, exceto `INTERNA` (poucas instituições no elenco, e tema de
#: reputação institucional não é o que esta taxonomia classifica).
FRENTES = (
    Frente.IMPRENSA,
    Frente.GOVERNO,
    Frente.PARCEIROS,
    Frente.EVENTOS,
    Frente.INVESTIDORES,
    Frente.LEGISLATIVO,
)


def semear(sessao: Session) -> int:
    """Cria as interações de demonstração da taxonomia nova. Devolve quantas criou."""
    if sessao.scalar(
        select(InteracaoRegistro.id).where(InteracaoRegistro.origem_aba == ORIGEM).limit(1)
    ):
        return 0

    sorte = random.Random(SEMENTE)
    elenco = _elenco(sessao)
    autor = _autor(sessao)
    repositorio = RepositorioSQL(sessao)

    # OS TEMAS DA TAXONOMIA NOVA, e só eles: `macro_tema_id is not null` é
    # exatamente o que a 0053 marca em quem reconciliou com a hierarquia nova
    # (os 37 rascunhos + "Inclusão sanitária") — os outros 16 temas de
    # fundação ficam de fora deste semeador de propósito.
    temas_novos = list(
        sessao.scalars(
            select(Tema).where(Tema.macro_tema_id.is_not(None)).order_by(Tema.id)
        )
    )

    criadas = 0
    indice = 0
    for tema in temas_novos:
        for _ in range(sorte.choice(POR_TEMA)):
            frente = FRENTES[indice % len(FRENTES)]
            agenda = _uma_solta(
                frente,
                indice,
                elenco,
                autor,
                sorte,
                temas_forcados=(tema.id,),
                origem_aba=ORIGEM,
            )
            repositorio.adicionar(agenda)
            criadas += 1
            indice += 1
        if indice % 20 == 0:
            sessao.flush()

    sessao.flush()
    return criadas


def principal() -> None:
    from app.banco.derivados import derivar_o_que_falta
    from app.banco.semear_enredos import vincular_areas
    from app.banco.sessao import obter_fabrica_de_sessao

    sessao = obter_fabrica_de_sessao()()
    try:
        criadas = semear(sessao)
        ligadas = vincular_areas(sessao)
        derivados = derivar_o_que_falta(sessao)
        sessao.commit()
        print(f"Agendas da taxonomia v1.3 criadas: {criadas}")
        if criadas == 0:
            print("Já tinha rodado antes. Nada a fazer.")
        print(f"Áreas vinculadas: {ligadas}")
        for nome, quantos in derivados.items():
            print(f"{nome.replace('_', ' ').capitalize()}: {quantos}")
    finally:
        sessao.close()


if __name__ == "__main__":
    principal()
