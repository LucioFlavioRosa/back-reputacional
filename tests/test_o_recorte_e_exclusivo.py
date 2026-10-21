"""O recorte de uma lente é EXCLUSIVO, e simétrico.

O PEDIDO (20/10/2026): "se o Valor Econômico é um veículo de imprensa de
mercado, absolutamente todas as matérias dele vão para a lente de mercado...
isso deve ser simétrico: se voltar a ser imprensa, o histórico deve ser movido
também de volta".

COMO ERA, E ESTÁ MEDIDO: o espelho (`clipei`) ficava com o arquivo inteiro e a
recortada era uma CÓPIA do subconjunto. Uma subida com duas matérias deixava
`clipei` com 2 e `clipei_investidores` com 1 — a do Valor Econômico contava nas
DUAS lentes. Classificar movia o histórico para dentro do recorte e não o tirava
da Imprensa.

COMO FICA: o mês do arquivo é uma PARTIÇÃO entre as fontes irmãs. A que declara
a lista fica com os veículos dela; a que não declara fica com o resto. E a
reconciliação move nos dois sentidos.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes, reconciliar_lista_de_veiculos
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

DO_MERCADO = "Valor Econômico zz80"
QUALQUER = "Jornal Qualquer zz81"
MES = date(2026, 7, 1)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    s = Session(bind=conexao, expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        transacao.rollback()
        conexao.close()


def _planilha() -> bytes:
    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    aba.append(
        [
            "Data",
            "Classificação",
            "Veículo",
            "Título",
            "Atributo",
            "Aegea Tier",
            "Público-alvo",
            "Subcategoria",
        ]
    )
    for veiculo in (DO_MERCADO, QUALQUER):
        aba.append(
            [
                date(2026, 7, 3),
                "Positivo",
                veiculo,
                f"Matéria do {veiculo}",
                "Governança",
                "Muito relevante",
                "População em geral",
                "Tarifa",
            ]
        )
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _por_lente(sessao) -> dict[str, int]:
    return {
        codigo: total
        for codigo, total in sessao.execute(
            select(Lente.codigo, func.count(Mencao.id))
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .join(Lente, Lente.id == ScoreFonte.lente_id)
            .group_by(Lente.codigo)
        ).all()
    }


def _agregado(sessao) -> dict[str, float]:
    return {
        codigo: float(total or 0)
        for codigo, total in sessao.execute(
            select(Lente.codigo, func.sum(ScoreMesFonte.mencoes))
            .select_from(ScoreMesFonte)
            .join(ScoreFonte, ScoreFonte.id == ScoreMesFonte.fonte_id)
            .join(Lente, Lente.id == ScoreFonte.lente_id)
            .group_by(Lente.codigo)
        ).all()
    }


def _subcategoria(sessao, nome: str) -> int:
    return sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(CategoriaPublico, CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id)
        .where(CategoriaPublico.nome == "Imprensa", SubcategoriaPublico.nome == nome)
    )


def _classificar(sessao, nome: str, subcategoria: int | None) -> None:
    veiculo = sessao.scalar(
        select(Instituicao).where(Instituicao.nome_normalizado == normalizar(nome))
    )
    assert veiculo is not None, f"{nome} tinha de existir no cadastro"
    veiculo.subcategoria_publico_id = subcategoria
    sessao.flush()


def _reconciliar(sessao) -> None:
    for fonte in reconciliar_lista_de_veiculos.fontes_que_recortam(
        sessao, "imprensa_economica"
    ):
        reconciliar_lista_de_veiculos.aplicar(sessao, fonte)


def _subir(sessao) -> None:
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    ingerir_mencoes.ingerir(sessao, clipei, _planilha(), [DO_MERCADO, QUALQUER])


def test_a_SUBIDA_ja_particiona_entre_as_lentes(sessao):
    """Com o veículo já classificado, a matéria dele NASCE só no Mercado.

    Era aqui que a duplicação começava: o espelho lia o arquivo inteiro e a
    recortada relia o subconjunto, então a matéria do Valor Econômico virava
    linha nas duas lentes na mesma subida.
    """
    #: O veículo precisa existir ANTES, classificado — é o estado de quem já
    #: mantém a lista e sobe a planilha do mês.
    sessao.add(
        Instituicao(
            nome=DO_MERCADO,
            nome_normalizado=normalizar(DO_MERCADO),
            tipo="veiculo",
            subcategoria_publico_id=_subcategoria(sessao, "Econômica e de negócios"),
        )
    )
    sessao.flush()

    _subir(sessao)

    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}
    assert _agregado(sessao) == {"imprensa": 1.0, "mercado": 1.0}


def test_CLASSIFICAR_move_o_historico_e_TIRA_da_imprensa(sessao):
    """O cenário do dono do produto, medido de ponta a ponta."""
    _subir(sessao)
    assert _por_lente(sessao) == {"imprensa": 2}

    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)

    #: O MERCADO GANHOU, A IMPRENSA PERDEU. Era a segunda metade que não
    #: acontecia: a Imprensa continuava com 2.
    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}
    #: E O AGREGADO ACOMPANHA, que é quem carrega a NOTA. Mexer em `mencao` e
    #: esquecer `score_mes_fonte` deixaria a lista certa e a nota errada.
    assert _agregado(sessao) == {"imprensa": 1.0, "mercado": 1.0}


def test_DESCLASSIFICAR_traz_o_historico_de_VOLTA(sessao):
    """A simetria, que é o que ele pediu em voz alta.

    "se voltar a ser imprensa o histórico deve ser movido também de volta".
    Com a partição, a menção existe num lugar só — tirá-la do Mercado sem
    devolvê-la apagaria a matéria do sistema.
    """
    _subir(sessao)
    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)
    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}

    #: E AGORA ELE VOLTA A SER IMPRENSA COMUM.
    _classificar(sessao, DO_MERCADO, None)
    _reconciliar(sessao)

    assert _por_lente(sessao) == {"imprensa": 2}
    assert _agregado(sessao) == {"imprensa": 2.0}
    #: A MATÉRIA É A MESMA, e não uma linha nova vazia: o texto do veículo
    #: voltou junto.
    veiculos = sessao.scalars(
        select(Mencao.veiculo)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(ScoreFonte.codigo == "clipei")
    ).all()
    assert sorted(veiculos) == sorted([DO_MERCADO, QUALQUER])


def test_a_IDA_E_VOLTA_nao_duplica_nem_perde(sessao):
    """Duas voltas completas: o total do arquivo não pode mudar nunca."""
    _subir(sessao)
    total = sum(_por_lente(sessao).values())

    for _ in range(2):
        _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
        _reconciliar(sessao)
        assert sum(_por_lente(sessao).values()) == total
        _classificar(sessao, DO_MERCADO, None)
        _reconciliar(sessao)
        assert sum(_por_lente(sessao).values()) == total

    assert _por_lente(sessao) == {"imprensa": 2}


def test_reconciliar_DUAS_VEZES_nao_muda_nada(sessao):
    #: A idempotência do gesto: a segunda aplicação não acha mês para mudar, e
    #: nada se move. Sem isto, cada clique no Salvar duplicaria ou apagaria.
    _subir(sessao)
    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)
    antes = _por_lente(sessao)

    _reconciliar(sessao)

    assert _por_lente(sessao) == antes
