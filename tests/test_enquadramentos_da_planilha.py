"""Os enquadramentos que a planilha de taxonomia define, na matriz da 0059.

O QUE FALTAVA. A `0059` criou `risk_cluster`, `risco` e `tema_risco` e carregou
os 8 clusters e os 32 riscos da matriz — mas inseriu UM vínculo de exemplo. Os
enquadramentos que a planilha define ficaram de fora, então a tela abria com a
matriz toda disponível e nenhum assunto classificado. A `0061` traz os 100.

DE ONDE VEM: `20260917_Aegea_Taxonomia_Publicos_v2.xlsx`, aba
`Taxonomia de temas`, coluna `Risk tracking` — um risco por subtema. Dos 104
subtemas, 100 trazem um risco e 4 trazem "Sem enquadramento".

O EXEMPLO DA 0059 FOI REMOVIDO (0062), por decisão do usuário: ele ligava
"Resultados financeiros e operacionais" ao R27 "Cobertura de Seguros", mas a
planilha diz que o `Risk tracking` desse subtema é "Integridade das Informações
ao Mercado" — a `0061` já trouxe o dado real; a `0062` tirou o que sobrava do
exemplo. 100 subtemas, 100 vínculos, nenhum duplicado.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.test_e2e_postgres import URL

_engine = create_engine(URL)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def test_cem_subtemas_enquadrados_e_quatro_sem(sessao):
    """O que a planilha diz: 100 com risco, 4 "Sem enquadramento"."""
    com = sessao.execute(
        text("""
            select count(*) from tema
             where ativo and id in (select tema_id from tema_risco)
        """)
    ).scalar_one()
    sem = sessao.execute(
        text("""
            select count(*) from tema
             where ativo and id not in (select tema_id from tema_risco)
        """)
    ).scalar_one()
    assert (com, sem) == (100, 4)


def test_os_quatro_sem_enquadramento_sao_os_da_planilha(sessao):
    """Nomeados, porque "quatro" sozinho passaria com os quatro errados."""
    nomes = {
        n
        for (n,) in sessao.execute(
            text("""
                select nome from tema
                 where ativo and id not in (select tema_id from tema_risco)
            """)
        )
    }
    assert nomes == {
        "Estrutura de governança / Conselho e comitês",
        "Modelo Operacional Aegea",
        "Benefícios do saneamento (saúde, educação, imóveis, socioeconômico)",
        "Drenagem urbana e águas pluviais",
    }


def test_cem_vinculos_exatos_depois_que_o_exemplo_saiu(sessao):
    """100 linhas, 100 subtemas — a 0062 tirou o que sobrava do exemplo.

    Nenhum tema aponta para mais de um risco: a divergência que existia entre a
    0059 (exemplo) e a 0061 (planilha) acabou com a remoção, não com um segundo
    vínculo convivendo com o primeiro.
    """
    linhas = sessao.execute(text("select count(*) from tema_risco")).scalar_one()
    assert linhas == 100

    com_mais_de_um = sessao.execute(
        text("""
            select count(*) from (
              select tema_id from tema_risco group by tema_id having count(*) > 1
            ) t
        """)
    ).scalar_one()
    assert com_mais_de_um == 0


def test_resultados_financeiros_enquadra_so_pela_planilha(sessao):
    """O que sobrou depois da 0062, dito por extenso.

    Antes da 0062, este subtema apontava para dois riscos — o exemplo da 0059
    ("Cobertura de Seguros") e o da planilha ("Integridade das Informações ao
    Mercado"). Só o segundo continua.
    """
    riscos = {
        n
        for (n,) in sessao.execute(
            text("""
                select r.nome from tema_risco tr
                  join tema t on t.id = tr.tema_id
                  join risco r on r.id = tr.risco_id
                 where t.nome = 'Resultados financeiros e operacionais'
            """)
        )
    }
    assert riscos == {"Integridade das Informações ao Mercado"}


def test_todo_enquadramento_aponta_para_risco_da_matriz(sessao):
    """Nenhum vínculo órfão — a FK garante, e isto prova que a carga a respeitou
    em vez de ter sido inserida com `on conflict` escondendo falha.
    """
    orfaos = sessao.execute(
        text("""
            select count(*) from tema_risco tr
             where not exists (select 1 from risco r where r.id = tr.risco_id)
                or not exists (select 1 from tema t where t.id = tr.tema_id)
        """)
    ).scalar_one()
    assert orfaos == 0


def test_a_severidade_vem_da_matriz_e_nao_do_enquadramento(sessao):
    """`tema_risco` não guarda severidade: ela mora no risco.

    É o que faz a tela preencher o campo sozinha, e o que impede o painel e a
    matriz de divergirem — não há onde gravar uma severidade diferente.
    """
    colunas = {
        c
        for (c,) in sessao.execute(
            text("""
                select column_name from information_schema.columns
                 where table_name = 'tema_risco'
            """)
        )
    }
    assert colunas == {"tema_id", "risco_id"}
