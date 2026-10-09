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

O QUE ESTE TESTE **NÃO** PEGA, e é limitação de desenho, não descuido: ele roda
contra o banco de teste, que nasce das migrations e não tem histórico. Uma
migration que aposente valor em uso passa aqui se os semeadores não reproduzirem
aquele uso — foi exatamente o caso do formato `midia`, que tinha 106 interações
na base acumulada e zero na recriada. Achado de revisão.

Então o CI é a primeira barreira, não a única. Antes de aplicar migration que
aposente vocabulário numa base com histórico, rode esta consulta CONTRA AQUELA
BASE (ou contra um instantâneo restaurado dela — ver `scripts/instantaneo.py`):

    select filho.relname as tabela, coluna.attname as coluna,
           pai.relname as dicionario
      from pg_constraint c
      join pg_class filho on filho.oid = c.conrelid
      join pg_class pai   on pai.oid   = c.confrelid
      join pg_namespace n on n.oid = filho.relnamespace
      join unnest(c.conkey) with ordinality as k(attnum, ord) on true
      join pg_attribute coluna
        on coluna.attrelid = c.conrelid and coluna.attnum = k.attnum
     where c.contype = 'f' and n.nspname = 'public'
       and array_length(c.conkey, 1) = 1
       and exists (select 1 from pg_attribute a
                    where a.attrelid = pai.oid and a.attname = 'ativo'
                      and not a.attisdropped);

e, para cada caminho, conte os registros presos:

    select count(*) from <tabela> r
      join <dicionario> d on d.id = r.<coluna>
     where not d.ativo;

É a mesma conferência que o teste faz. A diferença é a base onde ela roda, e é
essa diferença que decide se o campo vai aparecer vazio para alguém.
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
COM_LISTA_DE_INATIVOS = {"tema", "formato_interacao"}

#: As tabelas que a aplicação EXIBE mesmo quando a linha está inativa.
#:
#: ACHADO DE REVISÃO, e ele derrubou meu recorte anterior. Eu havia escrito
#: "registro inativo não chega à tela, então o pai irresolvível dele não mostra
#: campo vazio" — verdade para `subcategoria_publico`, falso para `tema`:
#: `/api/stakeholders/temas` devolve a lista COMPLETA de propósito ("quem
#: administra precisa ver o que desativou"), e o Cadastro de Assuntos resolve o
#: `macro_tema_id` no catálogo de ATIVOS. No dia em que um macro tema for
#: aposentado, abrir um tema inativo que aponta para ele mostraria o eixo em
#: branco — e o recorte por `r.ativo` deixaria isso passar calado.
#:
#: Então a pergunta certa não é "esta tabela tem `ativo`?", é "esta tabela é
#: EXIBIDA mesmo inativa?". Para as de baixo, a conferência ignora o `ativo` do
#: próprio registro e cobra a resolução do que ele aponta.
#:
#: Pôr uma tabela aqui é dizer "existe tela que mostra isto aposentado". Hoje é
#: uma; `subcategoria_publico` não entra porque só aparece pelo dicionário de
#: ativos, e o teste de baixo prova que ela seria falso positivo se entrasse.
EXIBIDOS_MESMO_INATIVOS = {"tema"}


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
        exibe_inativo = tabela in EXIBIDOS_MESMO_INATIVOS
        vivo = (
            " and r.ativo"
            if _tem_ativo(sessao, tabela) and not exibe_inativo
            else ""
        )
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

    dicionarios = listar_dicionarios(sessao)
    assert "temas_inativos" in dicionarios
    # E o conserto preventivo do bloco 3: a `0060` aposentou `midia`, e a carga
    # real traz de volta as agendas classificadas com ele.
    assert "formatos_interacao_inativos" in dicionarios


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


def test_tema_inativo_tambem_e_cobrado_porque_a_tela_o_mostra(sessao):
    """O buraco que o recorte por `r.ativo` abria, agora fechado.

    `tema` está em `EXIBIDOS_MESMO_INATIVOS`, então a conferência cobra a
    resolução do `macro_tema_id` dele mesmo quando o tema está inativo. Aqui o
    cenário é criado: aposenta um macro tema que um tema INATIVO usa, e exige
    que o guarda acuse.

    Sem a lista, isto passaria — e no Cadastro de Assuntos, que lista os
    aposentados de propósito, o eixo apareceria em branco.
    """
    alvo = sessao.execute(
        text(
            "select t.id, t.macro_tema_id from tema t"
            " join macro_tema m on m.id = t.macro_tema_id"
            " where m.ativo limit 1"
        )
    ).first()
    assert alvo is not None, "o banco de teste está sem tema ligado a macro tema"
    tema_id, macro_id = alvo

    sessao.execute(text("update tema set ativo = false where id = :i"), {"i": tema_id})
    sessao.execute(
        text("update macro_tema set ativo = false where id = :i"), {"i": macro_id}
    )
    sessao.flush()

    with pytest.raises(AssertionError, match="macro_tema"):
        test_nenhum_registro_preso_a_vocabulario_aposentado(sessao)

    sessao.rollback()


def test_nenhuma_fk_composta_aponta_para_dicionario(sessao):
    """A descoberta ignora FK composta — e o silêncio não pode virar contrato.

    `_CAMINHOS` filtra `array_length(conkey, 1) = 1` porque todo dicionário deste
    schema é referenciado por uma coluna só. Isso é verdade hoje, não é lei: uma
    FK composta para tabela com `ativo` sairia do radar do guarda principal sem
    ninguém perceber.

    Achado de revisão. Se este teste falhar, ou a FK nova não é para dicionário,
    ou `_CAMINHOS` precisa aprender a tratá-la.
    """
    compostas = sessao.execute(
        text("""
            select filho.relname, pai.relname, array_length(c.conkey, 1)
              from pg_constraint c
              join pg_class filho on filho.oid = c.conrelid
              join pg_class pai   on pai.oid   = c.confrelid
              join pg_namespace n on n.oid = filho.relnamespace
             where c.contype = 'f'
               and n.nspname = 'public'
               and array_length(c.conkey, 1) > 1
               and exists (
                 select 1 from pg_attribute a
                  where a.attrelid = pai.oid and a.attname = 'ativo'
                    and not a.attisdropped
               )
        """)
    ).all()

    assert not compostas, (
        "FK composta para tabela com `ativo`, que o guarda principal não vê:\n  "
        + "\n  ".join(f"{f} -> {p} ({n} colunas)" for f, p, n in compostas)
    )


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
