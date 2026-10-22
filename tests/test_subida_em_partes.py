"""As regras da subida em partes, sem banco, sem armazenamento e sem rota.

POR QUE ESTE ARQUIVO EXISTE. Estas recusas são a segurança do caminho de
subida — e cada uma delas saiu de uma revisão, nenhuma de projeto. Até
22/10/2026 só dava para exercitá-las subindo a pilha inteira: Postgres, Blob,
sessão autenticada e uma fonte do Score cadastrada. Isso custa segundos por
caso e, pior, faz a falha chegar misturada com a de outra coisa.

`subida_em_partes` é função pura. Este arquivo roda em milissegundos e falha
apontando para a regra, não para o ambiente.

O ARQUIVO IRMÃO CONTINUA NECESSÁRIO: `test_a_planilha_sobe_em_partes` prova que
as rotas CHAMAM estas regras, com dono, fonte e armazenamento de verdade. Regra
certa que ninguém chama é defeito igual.
"""

from __future__ import annotations

import pytest

from app.casos_de_uso import subida_em_partes
from app.dominio.erros import RegraViolada

#: Um teto de arquivo pequeno, para não depender do valor real de nenhum
#: domínio: o que se afirma aqui é a aritmética, não o número do Score.
TETO = 10 * subida_em_partes.TAMANHO_DA_PARTE


def _parte_cheia() -> bytes:
    return b"x" * subida_em_partes.TAMANHO_DA_PARTE


def test_as_partes_esperadas_arredondam_PARA_CIMA():
    """Um byte a mais que um pedaço já são duas partes — e é desse número que
    saem os dois tetos do índice e da contagem."""
    parte = subida_em_partes.TAMANHO_DA_PARTE

    assert subida_em_partes.partes_esperadas(parte) == 1
    assert subida_em_partes.partes_esperadas(parte + 1) == 2
    assert subida_em_partes.partes_esperadas(3 * parte) == 3


def test_a_parte_VAZIA_e_recusada():
    """O Blob ACEITA bloco de zero byte, e um deles no meio da lista produz um
    `.xlsx` truncado que só falha na leitura — longe da causa."""
    with pytest.raises(RegraViolada, match="chegou vazia"):
        subida_em_partes.conferir_a_parte(
            indice=0, dados=b"", tamanho_declarado=subida_em_partes.TAMANHO_DA_PARTE
        )


def test_o_indice_ALEM_do_declarado_e_recusado():
    """Declarar um pedaço e mandar a parte 80 era como o teto era furado: sem
    esta recusa, o arquivo montado não tinha tamanho máximo nenhum."""
    with pytest.raises(RegraViolada, match="fora do tamanho que a subida declarou"):
        subida_em_partes.conferir_a_parte(
            indice=1,
            dados=_parte_cheia(),
            tamanho_declarado=subida_em_partes.TAMANHO_DA_PARTE,
        )


def test_o_indice_NEGATIVO_e_recusado():
    """`-1` entra no `range` de ninguém, mas chega pela URL como qualquer outro
    número — e `indice < 0` é a única linha que o separa do caminho feliz."""
    with pytest.raises(RegraViolada, match="fora do tamanho"):
        subida_em_partes.conferir_a_parte(
            indice=-1,
            dados=_parte_cheia(),
            tamanho_declarado=subida_em_partes.TAMANHO_DA_PARTE,
        )


def test_a_parte_DO_MEIO_tem_de_vir_cheia():
    """É esta regra que faz a aritmética do teto fechar.

    Com ela, o montado não passa de `partes_esperadas × TAMANHO_DA_PARTE`. Sem
    ela, partes pequenas permitiriam MAIS partes que o esperado e o total
    voltaria a ser ilimitado.
    """
    declarado = 3 * subida_em_partes.TAMANHO_DA_PARTE

    with pytest.raises(RegraViolada, match="menos a última"):
        subida_em_partes.conferir_a_parte(
            indice=0, dados=b"meio byte", tamanho_declarado=declarado
        )


def test_a_ULTIMA_parte_pode_vir_menor():
    """O controle do teste acima: a última é justamente a que não enche."""
    declarado = 2 * subida_em_partes.TAMANHO_DA_PARTE + 10

    #: A terceira (índice 2) é a última deste declarado, e traz os 10 bytes.
    subida_em_partes.conferir_a_parte(
        indice=2, dados=b"x" * 10, tamanho_declarado=declarado
    )


def test_a_parte_MAIOR_que_o_pedaco_e_recusada():
    """A rota da parte é isenta do limite genérico de corpo — tem de ser, senão
    a primeira parte seria recusada. Então o teto é este aqui, e só este."""
    declarado = 2 * subida_em_partes.TAMANHO_DA_PARTE

    with pytest.raises(RegraViolada, match="menos a última"):
        subida_em_partes.conferir_a_parte(
            indice=0,
            dados=b"x" * (subida_em_partes.TAMANHO_DA_PARTE + 1),
            tamanho_declarado=declarado,
        )


def test_a_contagem_ZERO_e_recusada():
    with pytest.raises(RegraViolada, match="quantas partes"):
        subida_em_partes.conferir_a_contagem(
            partes=0, tamanho_declarado=TETO, teto_do_arquivo=TETO
        )


def test_a_contagem_ABSURDA_nao_chega_a_montar_lista():
    """O defeito que a revisão achou em 16/10/2026: `partes=1_000_000_000` fazia
    o processo construir a lista de blocos ANTES de falar com o Azure, e uma
    requisição derrubava a réplica."""
    with pytest.raises(RegraViolada, match="contagem de partes"):
        subida_em_partes.conferir_a_contagem(
            partes=1_000_000_000, tamanho_declarado=TETO, teto_do_arquivo=TETO
        )


def test_a_contagem_acima_do_DECLARADO_e_recusada():
    """O outro teto, e o que de fato aperta: declarar um pedaço e mandar juntar
    dez montaria dez vezes o que a pessoa disse que ia subir."""
    declarado = subida_em_partes.TAMANHO_DA_PARTE

    with pytest.raises(RegraViolada, match="contagem de partes"):
        subida_em_partes.conferir_a_contagem(
            partes=10, tamanho_declarado=declarado, teto_do_arquivo=TETO
        )


def test_a_contagem_que_CORRESPONDE_passa():
    """O controle negativo: sem ele, um teto errado recusaria toda montagem e
    estes testes continuariam verdes."""
    declarado = 3 * subida_em_partes.TAMANHO_DA_PARTE

    subida_em_partes.conferir_a_contagem(
        partes=3, tamanho_declarado=declarado, teto_do_arquivo=TETO
    )


def test_o_TETO_DO_ARQUIVO_vem_de_quem_sobe():
    """A planilha do Score tem o teto dela, a de bonds terá o dela, e este
    módulo não deve conhecer nenhum dos dois — é a razão de `teto_do_arquivo`
    ser parâmetro e não constante importada."""
    assert subida_em_partes.partes_maximas(TETO) == 11
    assert subida_em_partes.partes_maximas(TETO * 2) == 21
