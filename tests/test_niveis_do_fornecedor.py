"""Qual coluna de cada fornecedor é o N3 — e por que o N2 e o N1 dele não entram.

A REGRA DE NEGÓCIO. Quem cadastra um tema (N3) cadastra em seguida o N2 e o N1
dele, então o tema já nasce com os três níveis. O N2 e o N1 de uma menção são
DERIVADOS pela árvore `tema -> macro_tema -> bloco_tema`
(`app/api/base_das_lentes.py`), e não lidos da planilha. Consequência prática,
e é ela que torna o formato dos fornecedores irrelevante: **a planilha vir sem
N1 e sem N2 não perde informação nenhuma.**

O QUE ESTES TESTES PROTEGEM:

* a correspondência coluna -> nível, que vinha escrita numa faixa de rótulos
  acima do cabeçalho da planilha da Clipei (`N2`, `N3`, `N1` sobre as colunas
  16, 17 e 18) e NÃO vem em toda entrega. Se alguém apontar `tema` para
  `Categoria` — que é o N2 do fornecedor —, as menções passam a ser agrupadas um
  nível acima, sem erro nenhum na subida: os números do índice mudam e nada
  acusa;
* a ausência de campo para o N2 do fornecedor, que é deliberada. Importá-lo
  criaria um segundo N2, capaz de DISCORDAR do derivado;
* o vocabulário fechado: um nome de campo fora de `CAMPOS` faz a subida ser
  recusada por "campo desconhecido", e o lugar de descobrir isso é aqui, não no
  upload do dono do produto.

Lê o cadastro COMO ELE ESTÁ NO BANCO, semeado pelas migrations, porque é lá que
esta convenção vive — não no código.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import ScoreFonte
from app.dominio.ingestao_score import CAMPOS
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: A COLUNA QUE É O N3 DE CADA FORNECEDOR, pelo código da fonte.
#:
#: Quatro nomes para o mesmo nível, que é exatamente o motivo de o mapeamento
#: ser cadastro e não código. O `crm` não é planilha de fornecedor — é a base
#: interna — e por isso não mapeia coluna nenhuma.
O_N3_DE_CADA_FONTE = {
    "approach_cm": "TAG (assunto 1)",
    "approach_sl": "Tags (tema)",
    "bites": "N3",
    "clipei": "Subcategoria",
    "clipei_investidores": "Subcategoria",
}

#: O N2 DO FORNECEDOR, que nenhum campo deve receber. Nome exato: `Subcategoria`
#: contém `Categoria` como pedaço, e comparar por `in` daria falso positivo.
COLUNAS_DE_OUTRO_NIVEL = {"Categoria"}


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


@pytest.fixture
def mapeamentos(sessao: Session) -> dict[str, dict]:
    fontes = sessao.scalars(select(ScoreFonte)).all()
    return {
        fonte.codigo: dict(fonte.mapeamento_colunas or {}) for fonte in fontes
    }


def test_o_tema_vem_do_N3_de_cada_fornecedor(mapeamentos: dict[str, dict]) -> None:
    """`tema` aponta para a coluna do nível mais fundo, em todas as fontes."""
    for codigo, esperada in O_N3_DE_CADA_FONTE.items():
        assert codigo in mapeamentos, f"a fonte {codigo} saiu do cadastro"
        colunas = mapeamentos[codigo].get("colunas") or {}
        assert colunas.get("tema") == esperada, (
            f"a fonte {codigo} deveria ler o tema da coluna {esperada!r} "
            f"(o N3 dela), e está lendo de {colunas.get('tema')!r}. "
            "Trocar de nível não quebra a subida: muda os números do índice."
        )


def test_nenhuma_fonte_le_o_N2_do_fornecedor(mapeamentos: dict[str, dict]) -> None:
    """O N2 do fornecedor não alimenta campo nenhum — nem mesmo `subtema`."""
    for codigo, mapeamento in mapeamentos.items():
        colunas = mapeamento.get("colunas") or {}
        lidas = set(colunas.values())
        intrusas = lidas & COLUNAS_DE_OUTRO_NIVEL
        assert not intrusas, (
            f"a fonte {codigo} passou a ler {sorted(intrusas)}, que é o N2 do "
            "fornecedor. O N2 da menção é derivado de `macro_tema`; um segundo "
            "N2 pode discordar dele, e a menção fica com dois."
        )


def test_o_painel_nao_tem_campo_para_o_N2_do_fornecedor() -> None:
    """A ausência é deliberada, e um campo novo aqui exigiria decisão de domínio."""
    assert not ({"categoria", "tema_n2", "macro_tema"} & CAMPOS), (
        "apareceu campo canônico para o nível intermediário do fornecedor. "
        "Se a decisão mudou, o comentário de `CAMPOS` em "
        "`app/dominio/ingestao_score.py` precisa mudar junto."
    )


def test_todo_campo_mapeado_existe_no_vocabulario(mapeamentos: dict[str, dict]) -> None:
    """Nome fora de `CAMPOS` é recusa na subida — descoberta aqui, não no upload."""
    for codigo, mapeamento in mapeamentos.items():
        colunas = mapeamento.get("colunas") or {}
        desconhecidos = sorted(set(colunas) - CAMPOS)
        assert not desconhecidos, (
            f"a fonte {codigo} mapeia {desconhecidos}, que não está em `CAMPOS`. "
            "A subida seria recusada por campo desconhecido."
        )


def test_o_N1_do_fornecedor_so_sobrevive_na_clipei(mapeamentos: dict[str, dict]) -> None:
    """O estado de hoje, registrado — não um estado desejado.

    A Bites parou de informar o N1 (migration 0079) porque ele pode discordar do
    derivado. A Clipei ainda mapeia `atributo` para a coluna `Atributo`, que é o
    N1 dela. Este teste existe para que, no dia em que essa pendência for
    decidida, a decisão passe por aqui — em vez de a divergência seguir invisível.
    """
    com_atributo = sorted(
        codigo
        for codigo, mapeamento in mapeamentos.items()
        if (mapeamento.get("colunas") or {}).get("atributo")
    )
    assert com_atributo == ["clipei", "clipei_investidores"], (
        "mudou quem lê o N1 do fornecedor: "
        f"hoje são {com_atributo}. Ver o comentário de `CAMPOS` em "
        "`app/dominio/ingestao_score.py`, seção 'a exceção que sobrou'."
    )
