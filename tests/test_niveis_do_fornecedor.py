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
  criaria um segundo N2, capaz de DISCORDAR do derivado — e isso está medido: na
  consolidada da Bites o `Atributo` contradizia o `N1` em 1.418 das 2.842 linhas
  (migration 0079). Quem tirou o `atributo` do mapeamento da Bites foi a
  migration **0069**; a 0079 trocou o `tema` de `Categoria` para `N3`;
* os dois campos que carregam taxonomia, `tema` e `subtema`. O segundo passou
  a ser mapeado pela **0091**, na `approach_sl` (`Tags (subtema)`, o nível
  abaixo de `Tags (tema)`) — foi a primeira fonte a usá-lo, e as duas colunas
  daquele fornecedor são de níveis vizinhos de propósito. Ver
  `tests/test_mapeamento_da_approach.py`;
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
O_N2_DO_FORNECEDOR = {"Categoria", "N2"}

#: TODA COLUNA QUE É OUTRO NÍVEL, pelos nomes que os fornecedores usam hoje.
#:
#: Achado de revisão (MÉDIA): a primeira versão deste arquivo barrava só
#: `Categoria`, e `subtema` — que ESTÁ em `CAMPOS` e É lido por `ler_linha`
#: (`app/dominio/ingestao_score.py`, `subtema=_rotulo(opcional("subtema"), …)`)
#: — podia receber `Atributo` ou `N1` sem nada acusar.
COLUNAS_DE_OUTRO_NIVEL = {"Categoria", "Atributo", "N1", "N2"}

#: OS CAMPOS QUE LIGAM A MENÇÃO À ÁRVORE. São os dois que passam por `_rotulo` e
#: são procurados no cadastro de assuntos; é neles que o nível importa.
#:
#: `atributo` NÃO está aqui de propósito: ele guarda texto solto, e a Clipei
#: aponta-o para `Atributo` — a pendência registrada no fim deste arquivo.
CAMPOS_DE_TAXONOMIA = {"tema", "subtema"}


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
        intrusas = lidas & O_N2_DO_FORNECEDOR
        assert not intrusas, (
            f"a fonte {codigo} passou a ler {sorted(intrusas)}, que é o N2 do "
            "fornecedor. O N2 da menção é derivado de `macro_tema`; um segundo "
            "N2 pode discordar dele — na consolidada da Bites o `Atributo` "
            "contradizia o `N1` em 1.418 de 2.842 linhas (migration 0079)."
        )


def test_campo_de_taxonomia_nao_recebe_coluna_de_outro_nivel(
    mapeamentos: dict[str, dict],
) -> None:
    """`tema` e `subtema` só podem vir do nível mais fundo.

    Achado de revisão (MÉDIA): barrar só `Categoria` deixava passar
    `subtema -> "Atributo"` e `subtema -> "N1"`. `subtema` está em `CAMPOS` e é
    lido, então é caminho aberto — e nenhum fornecedor o mapeia hoje, o que faz
    deste o momento certo de prendê-lo.
    """
    for codigo, mapeamento in mapeamentos.items():
        colunas = mapeamento.get("colunas") or {}
        for campo in CAMPOS_DE_TAXONOMIA:
            coluna = colunas.get(campo)
            assert coluna not in COLUNAS_DE_OUTRO_NIVEL, (
                f"a fonte {codigo} aponta `{campo}` para a coluna {coluna!r}, "
                "que é outro nível da árvore do fornecedor. A subida não quebra: "
                "as menções passam a ser agrupadas no nível errado, os números "
                "do índice mudam e nada acusa."
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
    """Quem informa o N1 — e agora é DECISÃO, não pendência.

    A Bites parou de informar o N1 na migration **0069**, e a 0079 mediu por quê:
    naquela planilha o `Atributo` contradizia o `N1` em 1.418 das 2.842 linhas.
    A Clipei continuou mapeando `atributo` para a coluna `Atributo`, que é o N1
    dela, e este teste dizia: "ninguém mediu a divergência lá".

    A MEDIÇÃO FOI FEITA (18/10/2026, base local, 104.670 menções) e a decisão
    tomada pelo dono do produto: **o fornecedor traz o N1 ou o N2 ou o N3, e os
    de cima são derivados do cadastro.** O N1 da Clipei VALE.

    Por que não é "conviver com dois", que era o medo certo da 0079:

        onde a menção tem os dois N1    27.315 concordam, 2 discordam (99,993%)
        onde tem só o do fornecedor     73.928 menções — 71% da base

    O `Atributo` da Clipei não é um segundo N1 que contradiz o derivado; é o
    ÚNICO N1 de 71% da base, porque a Clipei não fala o vocabulário do N3 (71
    dos 326 assuntos dela casam no cadastro) enquanto a Bites fala (92 de 92).
    E onde os dois se encontram, o derivado ganha — ver `Arvore.resolver`.

    O TESTE CONTINUA VALENDO COMO REGISTRO: se um fornecedor NOVO passar a
    informar o N1, ainda há o que decidir — se ele fala N3 como a Bites, o N1
    dele é redundância com chance de divergir; se não fala, é o piso dele. A
    lista muda depois da medição daquele fornecedor, não antes.
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
