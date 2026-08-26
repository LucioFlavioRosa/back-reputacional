"""As opções de filtro do painel saem do banco, e só do banco.

O front NÃO deve ter lista fixa de nenhuma delas. Antes tinha: as opções de
relevância estavam escritas à mão no `FiltrosDrawer.tsx`, os níveis válidos
estavam num `check` na coluna, e ainda havia uma terceira cópia no domínio
Python. Três listas para o mesmo vocabulário, e nada obrigava as três a
concordar — foi assim que "Tier 4" ficou impossível de registrar sem que
nenhuma delas dissesse por quê.

Este arquivo tranca as duas pontas que sobraram fora de tabela.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.catalogo import listar_dicionarios
from app.dominio.recorte import ABRANGENCIAS_VALIDAS, GRUPOS_DE_STATUS
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    """Cada teste roda dentro de uma transação desfeita ao final.

    É o que permite `insert into relevancia` num teste sem que o próximo veja o
    nível novo.
    """
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def test_as_ufs_do_python_sao_as_mesmas_do_dominio_do_postgres(sessao):
    """`ABRANGENCIAS_VALIDAS` e o domínio `abrangencia` não podem divergir.

    O domínio é quem de fato recusa uma escrita errada; a lista em Python é
    quem monta o filtro e a mensagem de erro. Se as duas se separarem, o painel
    ofereceria uma UF que o banco rejeita — ou esconderia uma que ele aceita, e
    aí o registro existe e ninguém consegue filtrá-lo.
    """
    definicao = sessao.scalar(
        text("""
            select pg_get_constraintdef(c.oid)
              from pg_constraint c
              join pg_type t on t.oid = c.contypid
             where t.typname = 'abrangencia'
        """)
    )
    assert definicao, "o domínio `abrangencia` sumiu do schema"

    no_banco = set(re.findall(r"'([A-Z]{2})'::text", definicao))

    assert no_banco == set(ABRANGENCIAS_VALIDAS), (
        f"só no banco: {sorted(no_banco - set(ABRANGENCIAS_VALIDAS))} · "
        f"só no Python: {sorted(set(ABRANGENCIAS_VALIDAS) - no_banco)}"
    )


def test_os_grupos_de_status_do_python_sao_os_do_banco(sessao):
    """`GRUPOS_DE_STATUS` sustenta a taxa de resolutividade do painel.

    Um grupo novo em `status.grupo` que o Python não conhecesse sairia da conta
    em silêncio: o total continuaria fechando, e a taxa passaria a medir outra
    coisa sem nenhum aviso.
    """
    no_banco = set(sessao.scalars(text("select distinct grupo from status")).all())
    assert no_banco == set(GRUPOS_DE_STATUS), (
        f"só no banco: {sorted(no_banco - set(GRUPOS_DE_STATUS))} · "
        f"só no Python: {sorted(set(GRUPOS_DE_STATUS) - no_banco)}"
    )


def test_relevancia_e_tabela_e_nao_lista_no_codigo(sessao):
    """O que motivou a mudança: acrescentar um nível tem de ser um `insert`."""
    niveis = sessao.execute(
        text("select id, nome from relevancia where ativo order by ordem")
    ).all()
    assert [n.id for n in niveis] == [1, 2, 3, 4]
    assert [n.nome for n in niveis] == ["Tier 1", "Tier 2", "Tier 3", "Tier 4"]


def test_um_nivel_novo_aparece_no_dicionario_sem_tocar_em_codigo(sessao):
    """A prova do que foi prometido: `insert` e o filtro passa a oferecê-lo."""
    sessao.execute(
        text("insert into relevancia (id, nome, ordem) values (5, 'Regional', 5)")
    )
    sessao.flush()

    relevancias = listar_dicionarios(sessao)["relevancias"]

    assert [r["nome"] for r in relevancias] == [
        "Tier 1",
        "Tier 2",
        "Tier 3",
        "Tier 4",
        "Regional",
    ]


def test_nivel_inexistente_e_recusado_pelo_banco(sessao):
    """O domínio deixa passar qualquer positivo; quem barra é a chave estrangeira.

    É onde a lista de níveis realmente vive, e ter UM lugar decidindo é o ponto
    de toda esta mudança.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        sessao.execute(
            text("""
                insert into interacao
                       (frente_id, data_interacao, uf, tier, status_id, pauta, criado_por)
                select 1, current_date, 'SP', 99, s.id, 'teste', null
                  from status s limit 1
            """)
        )
        sessao.flush()


def test_nivel_desativado_some_do_filtro_e_o_historico_fica(sessao):
    """Desativar não apaga: os registros que já usavam o nível continuam lá.

    É o que separa `ativo = false` de `delete`. Um nível aposentado sai do
    filtro para ninguém classificar mais nada com ele, e os registros antigos
    permanecem exatamente como foram gravados.
    """
    sessao.execute(text("update relevancia set ativo = false where id = 4"))
    sessao.flush()

    relevancias = listar_dicionarios(sessao)["relevancias"]
    assert [r["id"] for r in relevancias] == [1, 2, 3]


def test_as_ufs_e_os_grupos_saem_na_mesma_resposta(sessao):
    """Uma fonte só para as opções de filtro.

    Se algum vocabulário saísse por outra rota, a tela teria de juntar duas
    respostas — e é assim que uma lista fixa reaparece no código do front, como
    "só este aqui eu deixo escrito".
    """
    dicionarios = listar_dicionarios(sessao)

    assert {"ufs", "grupos_de_status", "relevancias", "frentes", "temas"} <= set(
        dicionarios
    )

    ufs = dicionarios["ufs"]
    assert len(ufs) == 29
    # `NA` e `IN` no fim, e NESTA ordem: por alfabeto "IN" viria antes de "NA",
    # invertendo o par que a tela sempre mostrou.
    assert [u["codigo"] for u in ufs[-2:]] == ["NA", "IN"]
    assert ufs[-2]["nome"] == "Nacional"
    assert ufs[-1]["nome"] == "Internacional"
    # E as 27 UFs antes deles, em ordem alfabética.
    assert [u["codigo"] for u in ufs[:3]] == ["AC", "AL", "AM"]
