"""O vocabulário do ciclo está escrito duas vezes. Aqui elas se encontram.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
`presenca`, `momento` de material e `declinado_por` não são dicionários em
tabela: são `text` com `check`, como `fonte` e `natureza`. A escolha é
deliberada — não são opções que o negócio configura, são vocabulário estrutural,
e não aparecem como filtro no painel.

O preço é uma SEGUNDA cópia da lista, em Python, para o domínio poder recusar
valor inválido com mensagem em português em vez de deixar o banco estourar.

Duas cópias que nada obriga a concordar é como um valor novo se torna
impossível de registrar sem que nenhuma mensagem diga por quê.

Este arquivo lê o `check` DO BANCO e compara com as constantes. Acrescentar um
valor num lado sem o outro falha aqui, e não no dia em que alguém tentar
salvar.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.dominio.interacao import (
    LADOS,
    MOMENTOS_DE_MATERIAL,
    PRESENCAS,
)
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    with Session(bind=_engine) as sessao:
        yield sessao


def _valores_do_check(sessao: Session, tabela: str, coluna: str) -> set[str]:
    """Os literais aceitos pelo `check` daquela coluna, lidos do catálogo.

    `cast(:tabela as regclass)` e nao `:tabela::regclass`: o `::` logo depois
    de um parametro faz o SQLAlchemy ler `:tabela:` como o nome do bind, e o
    Postgres recebe SQL quebrado.

    `pg_get_constraintdef` devolve algo como
    `CHECK ((presenca = ANY (ARRAY['previsto'::text, ...])))`. A expressão
    normalizada pelo Postgres não é a que escrevemos, e é justamente por isso
    que a leitura tem de vir DAQUI: o que vale é o que o banco vai aplicar.
    """
    definicoes = sessao.execute(
        text(
            """
            select pg_get_constraintdef(c.oid)
              from pg_constraint c
              join pg_attribute a
                on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
             where c.conrelid = cast(:tabela as regclass)
               and c.contype = 'c'
               and a.attname = :coluna
            """
        ),
        {"tabela": tabela, "coluna": coluna},
    ).scalars().all()

    assert definicoes, f"{tabela}.{coluna} não tem `check` — o vocabulário sumiu"
    return {
        literal
        for definicao in definicoes
        for literal in re.findall(r"'([^']+)'::text", definicao)
    }


def test_presenca_bate_nas_duas_pontas(sessao):
    """`previsto`, `presente`, `ausente` — nos dois lados da mesa e no domínio."""
    assert _valores_do_check(sessao, "interacao_interlocutor", "presenca") == set(
        PRESENCAS
    )
    assert _valores_do_check(sessao, "interacao_pessoa_aegea", "presenca") == set(
        PRESENCAS
    )


def test_as_duas_tabelas_de_participante_usam_o_MESMO_vocabulario(sessao):
    """Aegea e outra parte não podem divergir.

    São duas tabelas com a mesma coluna e o mesmo significado. Se uma ganhar
    `justificou` e a outra não, a ficha passa a mostrar presenças que a outra
    metade da reunião não sabe representar.
    """
    assert _valores_do_check(
        sessao, "interacao_interlocutor", "presenca"
    ) == _valores_do_check(sessao, "interacao_pessoa_aegea", "presenca")


def test_momento_do_material_bate(sessao):
    """`apoio` é antes da reunião; `obtido` e `produzido`, depois."""
    assert _valores_do_check(sessao, "material", "momento") == set(
        MOMENTOS_DE_MATERIAL
    )


def test_lado_do_declinio_bate(sessao):
    """Declinar é escolha; ser declinado é porta fechada. São dois lados, só."""
    assert _valores_do_check(sessao, "interacao", "declinado_por") == set(LADOS)


def test_o_leitor_do_check_realmente_le(sessao):
    """Guarda o próprio leitor.

    Se `_valores_do_check` passasse a devolver conjunto vazio — por uma mudança
    no formato de `pg_get_constraintdef`, ou por um erro no `regex` —, todos os
    testes acima virariam comparações de vazio com vazio e passariam sem provar
    nada. Este fixa um valor que tem de estar lá.
    """
    valores = _valores_do_check(sessao, "material", "momento")
    assert "apoio" in valores, "o leitor do `check` parou de ler"
    assert len(valores) >= 3
