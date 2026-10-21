"""A lente Institucional recorta a Clipei pela subcategoria "Institucional".

O PEDIDO (20/10/2026): "na lente Institucional, o filtro que deve ser utilizado
será Imprensa > Institucional, assim como fizemos para a lente mercado... caso um
veículo seja classificado como institucional, todo histórico dele deve ser movido
para institucional e tudo deve ser atualizado".

ESTA É A PARTE QUE ACRESCENTA. O CRM continua medindo a lente até a parte
seguinte, e por isso nada que já funcionava muda aqui: enquanto nenhum veículo
estiver classificado como "Institucional", a fonte nova recorta para zero.

O QUE ESTES TESTES PROTEGEM:

1. que o par (Imprensa, Institucional) seja mesmo o critério — pelo CADASTRO, e
   não por coluna que o fornecedor preencha;
2. que a fonte nova ESPELHE a Clipei (mesmo arquivo, mesma aba). É o espelho que
   faz a lista valer para trás: sem ele, `espelho_de` não acha par e a
   reconciliação retroativa nunca acontece — a metade do pedido que fala do
   histórico;
3. QUE A TERCEIRA FONTE NO MESMO ARQUIVO NÃO QUEBRE A SEGUNDA. `espelho_de`
   exige EXATAMENTE uma irmã sem recorte: três fontes lendo o export da Clipei é
   configuração nova neste sistema, e se a conta de irmãs falhasse, a
   reconciliação do MERCADO morreria junto — um recurso que já está no ar.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Lente, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import reconciliar_lista_de_veiculos
from app.casos_de_uso.veiculos_da_imprensa import LISTAS_DE_VEICULOS, nomes_da_lista
from app.dominio.ingestao_score import LISTAS_DE_VEICULOS as LISTAS_DO_MOTOR
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

LISTA = "imprensa_institucional"
FONTE = "clipei_institucional"


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


def _subcategoria(sessao, nome: str) -> int:
    achada = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(CategoriaPublico.nome == "Imprensa", SubcategoriaPublico.nome == nome)
    )
    assert achada is not None, f"a subcategoria {nome!r} da Imprensa tem de existir"
    return achada


def _veiculo(sessao, nome: str, subcategoria_id: int) -> Instituicao:
    feito = Instituicao(
        nome=nome,
        nome_normalizado=normalizar(nome),
        tipo="veiculo",
        subcategoria_publico_id=subcategoria_id,
    )
    sessao.add(feito)
    sessao.flush()
    return feito


def test_o_MOTOR_conhece_a_lista_e_a_camada_de_banco_a_traduz():
    """As duas pontas do nome, e é por isso que ele é declarado duas vezes.

    O motor só sabe que a lista existe; a tradução para o par do cadastro mora na
    camada que tem banco. Um nome declarado só de um lado faz o cadastro da fonte
    falhar na leitura — ou, pior, produzir recorte vazio sem explicação.
    """
    assert LISTA in LISTAS_DO_MOTOR
    assert LISTAS_DE_VEICULOS[LISTA] == ("Imprensa", "Institucional")
    #: E AS DUAS DECLARAÇÕES BATEM INTEIRAS, não só nesta linha.
    assert set(LISTAS_DE_VEICULOS) == set(LISTAS_DO_MOTOR)


def test_a_fonte_institucional_ESPELHA_a_clipei(sessao):
    """Mesmo arquivo e mesma aba — é o que faz a reconciliação ter de onde copiar."""
    nova = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == FONTE))
    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert nova is not None, "a 0111 cria a fonte"

    assert nova.mapeamento_colunas["arquivo"] == clipei.mapeamento_colunas["arquivo"]
    assert nova.mapeamento_colunas["aba"] == clipei.mapeamento_colunas["aba"]
    assert nova.mapeamento_colunas["lista_de_veiculos"] == LISTA
    #: AS COLUNAS NASCERAM IGUAIS ÀS DA CLIPEI: é o mesmo anexo, lido duas vezes.
    assert nova.mapeamento_colunas["colunas"] == clipei.mapeamento_colunas["colunas"]
    #: NA LENTE CERTA, e não na Imprensa.
    institucional = sessao.scalar(select(Lente).where(Lente.codigo == "institucional"))
    assert nova.lente_id == institucional.id
    #: NÃO É FONTE INTERNA: ela lê planilha, ao contrário do CRM.
    assert nova.interna is False


def test_cada_recortadora_continua_com_UM_espelho(sessao):
    """A terceira fonte no mesmo arquivo não pode quebrar a segunda.

    `espelho_de` exige EXATAMENTE uma irmã que leia o mesmo arquivo SEM recortar,
    e levanta se achar zero ou duas. Três fontes sobre o export da Clipei é
    configuração que não existia: se a conta de irmãs contasse as recortadoras
    entre si, a reconciliação do MERCADO — que já está no ar — morreria junto com
    a estreia desta.
    """
    for codigo in (FONTE, "clipei_investidores"):
        fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
        assert reconciliar_lista_de_veiculos.espelho_de(sessao, fonte).codigo == "clipei"


def test_a_lista_institucional_sai_do_CADASTRO_e_nao_se_mistura_com_a_do_mercado(sessao):
    """O recorte é a subcategoria do veículo, e as duas listas são disjuntas.

    Uma subcategoria só por instituição: classificar como "Institucional" é o
    mesmo gesto que TIRAR de "Econômica e de negócios". É por isso que o pedido
    de mover o histórico vale nos dois sentidos — e é o que a reconciliação faz.
    """
    institucional = _veiculo(
        sessao, "Agência Institucional zz21", _subcategoria(sessao, "Institucional")
    )
    economico = _veiculo(
        sessao, "Jornal do Mercado zz22", _subcategoria(sessao, "Econômica e de negócios")
    )

    da_institucional = nomes_da_lista(sessao, LISTA)
    do_mercado = nomes_da_lista(sessao, "imprensa_economica")

    assert institucional.nome_normalizado in da_institucional
    assert institucional.nome_normalizado not in do_mercado
    assert economico.nome_normalizado in do_mercado
    assert economico.nome_normalizado not in da_institucional


def test_o_veiculo_DESATIVADO_nao_entra_na_lista_institucional(sessao):
    #: A mesma regra da lista do Mercado: `ativo=false` é quem administra o
    #: cadastro dizendo "este não é um veículo corrente", e contá-lo numa lente
    #: faria a desativação significar duas coisas diferentes em dois lugares.
    fora = _veiculo(
        sessao, "Boletim Extinto zz23", _subcategoria(sessao, "Institucional")
    )
    fora.ativo = False
    sessao.flush()

    assert fora.nome_normalizado not in nomes_da_lista(sessao, LISTA)
