"""Nenhum registro aponta para valor de dicionário que a tela não resolve.

A ARMADILHA, em uma frase: `GET /api/dicionarios` filtra TODO vocabulário por
`ativo` — é o que faz um valor aposentado sair do filtro e do formulário, e isso
está certo. Mas o registro antigo continua apontando para o valor com que FOI
classificado, e o front resolve o nome por aquele mesmo dicionário. Quando as
duas coisas se cruzam, o campo aparece vazio e parece que o dado nunca existiu.

JÁ ACONTECEU, DUAS VEZES, e as duas custaram caro:

  a `0058` desativou 45 temas     313 agendas passaram a mostrar o campo de tema
  de uma vez                      em branco; a série mensal (que vem do servidor
                                  e NÃO filtra `ativo`) continuava mostrando
                                  "Regulação". O mesmo dado com três respostas no
                                  mesmo produto.

  a `0060` aposentou o formato    106 interações passaram a mostrar "—" no lugar
  `midia`                         de "Mídia", porque `nomeDoFormatoDeInteracao`
                                  devolve `'—'` quando o id não resolve.

O primeiro foi corrigido com a chave `temas_inativos`: as OPÇÕES seguem só com
os ativos, a RESOLUÇÃO olha as duas listas. O segundo não precisou de correção —
numa base recriada, os semeadores só atribuem formato ativo, e o problema tinha
vindo de dado acumulado antes da migration.

POR QUE UM TESTE E NÃO SEIS CHAVES NOVAS. Na base realinhada de 08/10/2026, seis
dicionários têm valor inativo (`tema` 45, `status` 8, `subcategoria_publico` 5,
`area_pessoa` 1, `categoria_publico` 1, `formato_interacao` 1) e SÓ `tema` tem
registro apontando para algum deles. Construir companheiro `*_inativos` para os
outros cinco seria encanamento para zero problema. O que falta é alguém ser
avisado na PRÓXIMA aposentadoria — e é isso que este arquivo faz: se uma
migration desativar um valor que registros usam, ele falha e quem desativou
decide (corrigir o dado, ou expor a lista de inativos como `tema` fez).

O TESTE DESCOBRE OS CAMINHOS, em vez de listá-los. Uma lista escrita à mão aqui
envelheceria na primeira FK nova — e o custo de envelhecer é exatamente o
silêncio que o teste existe para quebrar.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.test_e2e_postgres import URL

_engine = create_engine(URL)

#: Os dicionários cuja lista de INATIVOS a API já expõe, e que por isso a tela
#: resolve. Hoje só um; a chave em `/api/dicionarios` é `<nome>_inativos`.
#:
#: Pôr um dicionário aqui é dizer "a tela sabe mostrar o nome de um valor
#: aposentado deste". Se não souber, o nome aparece vazio e o teste tem razão em
#: reprovar.
COM_LISTA_DE_INATIVOS = {"tema"}


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    sessao = Session(bind=conexao)
    try:
        yield sessao
    finally:
        sessao.close()
        conexao.close()


#: Toda FK que aponta para uma tabela que tem coluna `ativo` — ou seja, todo
#: caminho pelo qual um registro pode ficar preso a vocabulário aposentado.
_CAMINHOS = text("""
    select
      filho.relname   as tabela,
      coluna.attname  as coluna,
      pai.relname     as dicionario
    from pg_constraint c
    join pg_class filho on filho.oid = c.conrelid
    join pg_class pai   on pai.oid   = c.confrelid
    join pg_namespace n on n.oid = filho.relnamespace
    join unnest(c.conkey) with ordinality as k(attnum, ord) on true
    join pg_attribute coluna
      on coluna.attrelid = c.conrelid and coluna.attnum = k.attnum
    where c.contype = 'f'
      and n.nspname = 'public'
      and array_length(c.conkey, 1) = 1
      -- só dicionário: tabela que tem `ativo`, logo pode aposentar valor
      and exists (
        select 1 from pg_attribute a
         where a.attrelid = pai.oid and a.attname = 'ativo' and not a.attisdropped
      )
    order by 1, 2
""")


def _tem_ativo(sessao, tabela: str) -> bool:
    """A tabela tem a própria coluna `ativo`?

    Se tem, ela também é vocabulário — e um valor dela que esteja aposentado não
    chega à tela, então o que ele aponta não pode mostrar campo vazio.
    """
    return bool(
        sessao.execute(
            text(
                "select 1 from information_schema.columns"
                " where table_schema = 'public' and table_name = :t"
                " and column_name = 'ativo'"
            ),
            {"t": tabela},
        ).first()
    )


def test_nenhum_registro_preso_a_vocabulario_aposentado(sessao):
    """O teste que avisa na próxima aposentadoria.

    SE ESTE TESTE FALHAR, não "conserte o teste". Ele está dizendo que uma
    migration desativou um valor que registros ainda usam, e que a tela vai
    mostrar aquele campo vazio. Há dois caminhos honestos:

      reclassificar o dado    se o valor aposentado foi substituído por outro,
                              a migration que o aposentou deveria mover os
                              registros — é o que falta.

      expor os inativos       se o dado antigo deve continuar dizendo o que
                              dizia, o dicionário precisa de uma lista de
                              inativos em `/api/dicionarios`, como `temas_inativos`,
                              e o nome entra em `COM_LISTA_DE_INATIVOS`.

    O que NÃO é caminho: deixar passar. O campo em branco não é "sem dado" — é o
    painel escondendo o que ele sabe.
    """
    presos = []
    for tabela, coluna, dicionario in sessao.execute(_CAMINHOS):
        if dicionario in COM_LISTA_DE_INATIVOS:
            continue
        # SÓ REGISTRO VIVO CONTA, e este recorte foi o próprio teste que pediu:
        # na primeira execução ele acusou `subcategoria_publico ->
        # categoria_publico` com 5 linhas, que são as subcategorias de "Imprensa
        # e Formadores de Opinião" desativadas pela `0061` JUNTO com a
        # categoria-mãe. Aposentar pai e filho na mesma migration é coerente, e
        # um filho inativo não aparece na tela — então o pai irresolvível dele
        # não mostra campo vazio para ninguém.
        #
        # A regra é "registro que a tela MOSTRA apontando para valor que a tela
        # NÃO resolve", e não "qualquer FK para valor inativo".
        vivo = " and r.ativo" if _tem_ativo(sessao, tabela) else ""
        quantos = sessao.execute(
            text(
                f"select count(*) from {tabela} r"  # noqa: S608 — nomes vêm do catálogo
                f" join {dicionario} d on d.id = r.{coluna}"
                f" where not d.ativo{vivo}"
            )
        ).scalar_one()
        if quantos:
            presos.append(f"{tabela}.{coluna} -> {dicionario}: {quantos} registro(s)")

    assert not presos, (
        "registros presos a vocabulário aposentado que a tela não resolve:\n  "
        + "\n  ".join(presos)
        + "\n\nVer o docstring deste teste: ou a migration reclassifica o dado, ou "
        "o dicionário ganha lista de inativos em `/api/dicionarios`."
    )


def test_o_tema_esta_na_lista_de_isentos_porque_a_api_o_resolve(sessao):
    """A isenção de `tema` não é conveniência: ela é verificável.

    `temas_inativos` existe em `/api/dicionarios` e o front resolve por ela. Se
    alguém remover a chave, este teste reprova a isenção — e o teste de cima
    volta a cobrar `tema` junto com os outros.
    """
    from app.api.catalogo import listar_dicionarios

    assert "temas_inativos" in listar_dicionarios(sessao)


def test_o_guarda_dispara_quando_a_condicao_acontece(sessao):
    """Aposenta um formato EM USO e exige que o teste principal acuse.

    SEM ISTO O GUARDA SERIA CARIMBO: ele passa hoje porque a base está limpa, e
    passaria igual se a consulta de descoberta estivesse quebrada ou se o
    recorte de "registro vivo" tivesse comido o caso de verdade. Aqui a condição
    é criada de propósito — exatamente o que a `0060` fez com o formato `midia`,
    que deixou 106 interações mostrando "—" — e desfeita no fim.
    """
    # PELO CAMINHO `macro_tema -> bloco_tema`, e não por um formato de interação:
    # o banco de TESTE nasce só das migrations, sem semeadores, então não há
    # interação nenhuma para prender a um formato. A hierarquia da taxonomia, ao
    # contrário, vem carregada pela `0058` — 7 pilares e 41 temas estratégicos,
    # todos ativos — e é dado que as migrations garantem existir.
    #
    # A forma do defeito é a mesma: um registro VIVO (o tema estratégico)
    # apontando para vocabulário que a tela não resolve (o pilar aposentado).
    pilar = sessao.execute(
        text(
            "select b.id from bloco_tema b"
            " join macro_tema m on m.bloco_tema_id = b.id and m.ativo"
            " where b.ativo limit 1"
        )
    ).scalar_one()
    sessao.execute(
        text("update bloco_tema set ativo = false where id = :i"), {"i": pilar}
    )
    sessao.flush()

    with pytest.raises(AssertionError, match="bloco_tema"):
        test_nenhum_registro_preso_a_vocabulario_aposentado(sessao)

    sessao.rollback()


def test_a_descoberta_de_caminhos_acha_algo(sessao):
    """A consulta que descobre os caminhos é longa; se ela devolvesse vazio por
    um erro de junção, o teste principal passaria sempre.

    Este é o guarda do guarda — e `interacao_tema -> tema` tem de estar entre os
    caminhos, porque é o que já quebrou em produção.
    """
    caminhos = {(t, c, d) for t, c, d in sessao.execute(_CAMINHOS)}

    assert len(caminhos) > 20, f"só {len(caminhos)} caminhos; a consulta quebrou?"
    assert ("interacao_tema", "tema_id", "tema") in caminhos
    assert ("interacao", "formato_interacao_id", "formato_interacao") in caminhos
