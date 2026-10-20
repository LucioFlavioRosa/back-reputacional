"""As rotas da reconciliação: a prévia que não escreve, e o aplicar.

A PRÉVIA EXISTE PORQUE A CONTA É A DA DIRETORIA: aplicar reescreve
`score_mes_fonte` de meses FECHADOS, e o índice daqueles meses muda. "Mostre
antes" é a mesma regra que a conferência da subida de planilha segue.

O QUE ESTES TESTES PROTEGEM:

* a prévia responde e NÃO escreve;
* o aplicar escreve, e o que ele diz bate com o que ficou no banco;
* as duas exigem a permissão de administrar cadastros — a MESMA de quem mantém
  a lista, porque é o mesmo gesto em dois tempos.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
from app.dominio.texto import normalizar
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

_CABECALHO = ["Data", "Classificação", "Veículo"]
_COLUNAS = {"data": "Data", "sentimento": "Classificação", "veiculo": "Veículo"}


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


def _cliente(sessao, perfil: str):
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": perfil}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    return TestClient(app)


@pytest.fixture
def cliente(sessao):
    feito = _cliente(sessao, "plataforma_edicao")
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


def _planilha(linhas: list[list[object]]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    aba.append(_CABECALHO)
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


@pytest.fixture
def mercado_com_desvio(sessao) -> ScoreFonte:
    """Um par espelho/recorte com um veículo classificado DEPOIS da subida.

    É o estado real que a tela precisa mostrar: a lista mudou e a lente ainda
    não sabe.
    """
    base = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    espelho = ScoreFonte(
        codigo="zz_rota_espelho",
        nome="Espelho da rota",
        fornecedor="Clipei",
        lente_id=base.lente_id,
        ordem=96,
        mapeamento_colunas={"aba": "Clipping", "arquivo": "zzrota", "colunas": _COLUNAS},
    )
    recorte = ScoreFonte(
        codigo="zz_rota_recorte",
        nome="Recorte da rota",
        fornecedor="Clipei",
        lente_id=base.lente_id,
        ordem=97,
        mapeamento_colunas={
            "aba": "Clipping",
            "arquivo": "zzrota",
            "colunas": _COLUNAS,
            "lista_de_veiculos": "imprensa_economica",
        },
    )
    sessao.add_all([espelho, recorte])
    sessao.flush()

    ingerir_mencoes.ingerir(
        sessao,
        espelho,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor da Rota zz95"],
                [date(2026, 9, 4), "Negativa", "Valor da Rota zz95"],
            ]
        ),
    )

    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            CategoriaPublico.nome == "Imprensa",
            SubcategoriaPublico.nome == "Econômica e de negócios",
        )
    )
    sessao.add(
        Instituicao(
            nome="Valor da Rota zz95",
            nome_normalizado=normalizar("Valor da Rota zz95"),
            tipo="veiculo",
            subcategoria_publico_id=alvo,
        )
    )
    sessao.flush()
    return recorte


def _quantas(sessao, fonte: ScoreFonte) -> int:
    return int(
        sessao.scalar(
            select(func.count()).select_from(Mencao).where(Mencao.fonte_id == fonte.id)
        )
        or 0
    )


def test_a_previa_diz_o_que_muda_e_NAO_escreve(cliente, sessao, mercado_com_desvio):
    resposta = cliente.get("/api/score/veiculos-de-investidores/reconciliacao")

    assert resposta.status_code == 200, resposta.text
    nosso = next(
        r for r in resposta.json() if r["fonte"] == mercado_com_desvio.codigo
    )
    assert nosso["espelho"] == "zz_rota_espelho"
    assert nosso["aplicada"] is False
    assert [(v["nome"], v["mencoes"]) for v in nosso["entram"]] == [
        ("Valor da Rota zz95", 2)
    ]
    assert nosso["saem"] == []
    mudam = [m for m in nosso["meses"] if m["mudou"]]
    assert [(m["mes"], m["antes"], m["depois"]) for m in mudam] == [
        ("2026-08-01", 0, 1),
        ("2026-09-01", 0, 1),
    ]
    #: E NADA FOI ESCRITO — é a razão de a prévia existir.
    assert _quantas(sessao, mercado_com_desvio) == 0


def test_o_aplicar_escreve_e_o_que_ele_diz_bate_com_o_banco(
    cliente, sessao, mercado_com_desvio
):
    resposta = cliente.post("/api/score/veiculos-de-investidores/reconciliacao")

    assert resposta.status_code == 200, resposta.text
    nosso = next(
        r for r in resposta.json() if r["fonte"] == mercado_com_desvio.codigo
    )
    assert nosso["aplicada"] is True
    #: O NÚMERO DA RESPOSTA É O NÚMERO DO BANCO. Uma tela que diga "2 menções
    #: entraram" com 0 no banco é pior que tela nenhuma.
    assert _quantas(sessao, mercado_com_desvio) == sum(
        m["depois"] for m in nosso["meses"]
    )
    assert _quantas(sessao, mercado_com_desvio) == 2


def test_a_segunda_chamada_nao_acha_mes_para_mudar(cliente, sessao, mercado_com_desvio):
    #: Repetir o POST é inofensivo, e é o que torna o botão seguro contra o
    #: clique duplo que toda tela leva.
    cliente.post("/api/score/veiculos-de-investidores/reconciliacao")

    resposta = cliente.post("/api/score/veiculos-de-investidores/reconciliacao")

    nosso = next(
        r for r in resposta.json() if r["fonte"] == mercado_com_desvio.codigo
    )
    assert [m for m in nosso["meses"] if m["mudou"]] == []
    assert _quantas(sessao, mercado_com_desvio) == 2


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_quem_nao_administra_cadastros_nao_reconcilia(sessao, metodo):
    """A MESMA permissão da lista: quem decide quais veículos a lente considera
    é quem decide que isso valha para trás. São o mesmo gesto em dois tempos."""
    cliente = _cliente(sessao, "plataforma_leitura")
    try:
        resposta = getattr(cliente, metodo)(
            "/api/score/veiculos-de-investidores/reconciliacao"
        )
        assert resposta.status_code == 403, resposta.text
    finally:
        app.dependency_overrides.clear()
