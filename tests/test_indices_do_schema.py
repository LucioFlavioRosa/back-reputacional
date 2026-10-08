"""Nenhum índice do schema é coberto por outro.

O QUE ISTO PEGA. Um índice btree de `(a, b, c)` já serve consulta por `(a)` e
por `(a, b)` — o Postgres lê as primeiras colunas e ignora o resto. Então um
índice de duas colunas cujo par é o começo de um de três não acrescenta leitura
nenhuma, e cobra escrita em toda inserção.

NINGUÉM ESCREVE ISSO DE PROPÓSITO: acontece por ACÚMULO. `mencao_por_fonte_e_mes
(fonte_id, mes)` nasceu certo na `0048`, e virou redundante quando a `0055` e a
`0056` acrescentaram quatro índices `(fonte_id, mes, <dimensão>)`. Entre uma
migration e outra ninguém olhou o conjunto — e não é razoável esperar que olhe.
A `0060` removeu os dois casos que existiam; este teste é o que evita o terceiro.

POR QUE ERA INVISÍVEL. A carga das Lentes insere 20.928 linhas de uma vez, e o
custo de um índice a mais aparece ali, não numa tela. Nenhum teste ficava
vermelho, nenhuma consulta ficava lenta: só a importação pagava, em silêncio.

DUAS ARMADILHAS NA CONSULTA, e as duas me pegaram ao escrevê-la:

  `indkey` é BASE ZERO    é `int2vector`, não `int2[]`. Fatiar de `[1:n]` compara
                          as colunas erradas e o teste passa achando que não há
                          redundância — foi o primeiro resultado que eu tive, e
                          era falso negativo.

  método e opclass        `interlocutor_nome_trgm_idx` é GIN com `gin_trgm_ops`
  contam                  sobre a MESMA coluna de um btree único. Comparar só a
                          posição das colunas o acusa, e ele não é redundante:
                          serve busca por semelhança, que btree não faz.

Índice PARCIAL também não entra: dois índices com `where` diferente respondem a
conjuntos de linhas diferentes, mesmo com as mesmas colunas.
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
    sessao = Session(bind=conexao)
    try:
        yield sessao
    finally:
        sessao.close()
        conexao.close()


#: Um índice é coberto por outro quando, no MESMO método de acesso e com a MESMA
#: classe de operador, as suas colunas são o começo das de um índice mais largo.
_COBERTOS = text("""
    select
      menor.indrelid::regclass::text as tabela,
      menor.indexrelid::regclass::text as coberto,
      maior.indexrelid::regclass::text as por
    from pg_index menor
    join pg_index maior
      on menor.indrelid = maior.indrelid
     and menor.indexrelid <> maior.indexrelid
     and menor.indnatts < maior.indnatts
     -- base zero, e aqui está a primeira armadilha
     and (maior.indkey::int2[])[0 : menor.indnatts - 1]
       = (menor.indkey::int2[])[0 : menor.indnatts - 1]
     -- a segunda: mesmo método e mesma classe de operador
     and (select relam from pg_class where oid = menor.indexrelid)
       = (select relam from pg_class where oid = maior.indexrelid)
     and (maior.indclass::oid[])[0 : menor.indnatts - 1]
       = (menor.indclass::oid[])[0 : menor.indnatts - 1]
    join pg_class t on t.oid = menor.indrelid
    join pg_namespace n on n.oid = t.relnamespace
    where n.nspname = 'public'
      -- o menor não pode ser constraint: a PK e o UNIQUE existem para PROIBIR
      -- linha repetida, não para acelerar leitura, e apagá-los mudaria o que o
      -- banco aceita.
      and not menor.indisprimary
      and not menor.indisunique
      -- parcial de nenhum dos dois lados: `where` diferente, linhas diferentes
      and menor.indpred is null
      and maior.indpred is null
    order by 1, 2
""")


def test_nenhum_indice_e_prefixo_de_outro(sessao):
    cobertos = sessao.execute(_COBERTOS).all()

    assert not cobertos, "índice(s) que outro já cobre:\n" + "\n".join(
        f"  {t}: {c} é prefixo de {p} — apague {c} numa migration nova" for t, c, p in cobertos
    )


def test_a_consulta_do_teste_acha_redundancia_quando_ela_existe(sessao):
    """A consulta acima é longa e cheia de detalhe; sem este teste, um erro nela
    viraria um teste que passa sempre — exatamente o que aconteceu comigo na
    primeira versão, pela fatia base um.

    Crio um índice redundante de propósito, confiro que ele é acusado, e desfaço.
    """
    sessao.execute(text("create index _redundante_de_proposito on mencao (fonte_id)"))
    try:
        acusados = {c for _, c, _ in sessao.execute(_COBERTOS).all()}
        assert "_redundante_de_proposito" in acusados
    finally:
        sessao.execute(text("drop index _redundante_de_proposito"))
        sessao.commit()


def test_o_indice_trigrama_nao_e_acusado(sessao):
    """GIN com `gin_trgm_ops` sobre a mesma coluna de um btree não é redundante:
    ele serve busca por semelhança, que btree não responde. A primeira versão
    desta consulta o acusava, e seguir aquele falso positivo teria quebrado a
    busca de instituição e de interlocutor por nome aproximado.
    """
    acusados = {c for _, c, _ in sessao.execute(_COBERTOS).all()}
    assert "interlocutor_nome_trgm_idx" not in acusados
    assert "instituicao_nome_trgm_idx" not in acusados


def test_os_quatro_indices_que_cobriam_o_removido_continuam_la(sessao):
    """A `0060` apagou `mencao_por_fonte_e_mes` porque estes quatro o cobrem.
    Se um deles for removido um dia, a consulta por `(fonte_id, mes)` volta a
    varrer a tabela — e aí o drop da `0060` passa a ser o problema.
    """
    existentes = {
        nome
        for (nome,) in sessao.execute(
            text("select indexname from pg_indexes where tablename = 'mencao'")
        )
    }
    cobertura = {
        "mencao_por_subtema",
        "mencao_por_autor",
        "mencao_por_uf",
        "mencao_por_perfil",
    }
    faltando = cobertura - existentes
    assert not faltando, (
        f"sem {faltando}, a consulta por (fonte_id, mes) perde o índice que a "
        "0059 assumiu que existiria"
    )
    assert "mencao_por_fonte_e_mes" not in existentes
