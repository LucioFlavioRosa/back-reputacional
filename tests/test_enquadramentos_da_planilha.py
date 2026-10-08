"""Os enquadramentos que a planilha de taxonomia define, na matriz da 0059.

O QUE FALTAVA. A `0059` criou `risk_cluster`, `risco` e `tema_risco` e carregou
os 8 clusters e os 32 riscos da matriz — mas inseriu UM vínculo de exemplo. Os
enquadramentos que a planilha define ficaram de fora, então a tela abria com a
matriz toda disponível e nenhum assunto classificado. A `0061` traz os 100.

DE ONDE VEM: `20260917_Aegea_Taxonomia_Publicos_v2.xlsx`, aba
`Taxonomia de temas`, coluna `Risk tracking` — um risco por subtema. Dos 104
subtemas, 100 trazem um risco e 4 trazem "Sem enquadramento".

A DIVERGÊNCIA DO EXEMPLO, que é achado a reportar e não a corrigir: a `0059`
liga "Resultados financeiros e operacionais" ao R27 "Cobertura de Seguros", e a
planilha diz que o `Risk tracking` desse subtema é "Integridade das Informações
ao Mercado". Parece linha de teste de fumaça, não dado — mas é dado de outro PR
já mesclado, e se a ligação foi deliberada, apagá-la seria desfazer decisão que
não é nossa. Como o schema é muitos-para-muitos, os dois coexistem. Estes testes
travam esse estado exato, para que mudá-lo seja uma escolha e não um acidente.
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


def test_um_vinculo_a_mais_que_os_cem_e_o_exemplo_da_0059(sessao):
    """101 linhas, 100 subtemas — a diferença é o exemplo, e está nomeada.

    Este teste é o lugar onde a divergência fica registrada em código, e não só
    em comentário: se alguém decidir tirar o exemplo, é aqui que o número muda, e
    quem mudar tem de ler por quê.
    """
    linhas = sessao.execute(text("select count(*) from tema_risco")).scalar_one()
    assert linhas == 101

    com_dois = {
        n
        for (n,) in sessao.execute(
            text("""
                select t.nome from tema t
                 where t.id in (
                   select tema_id from tema_risco group by tema_id having count(*) > 1
                 )
            """)
        )
    }
    assert com_dois == {"Resultados financeiros e operacionais"}


def test_o_exemplo_da_0059_contradiz_a_planilha(sessao):
    """A contradição, dita por extenso.

    A planilha enquadra esse subtema em "Integridade das Informações ao Mercado";
    o exemplo da `0059` o liga a "Cobertura de Seguros". Os dois estão no banco.
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
    assert riscos == {
        "Integridade das Informações ao Mercado",  # o que a planilha diz
        "Cobertura de Seguros",  # o exemplo da 0059
    }


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
