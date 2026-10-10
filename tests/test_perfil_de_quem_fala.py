"""O perfil de quem fala, que vinha vazio — e o cargo que o alimenta.

O QUE ESTAVA QUEBRADO. `mencao.perfil_autor` estava vazio nas 32.784 menções de
TODAS as cinco fontes, e é a coluna do gráfico "Perfil de quem fala ×
sentimento" e do KPI de figuras públicas da lente. Mais um campo que existia na
tabela e nunca era escrito — como `tema_id` (zero em 29.898) e
`unidade_negocio_id` (zero em 32.784).

E O DADO ESTAVA NA PLANILHA. A coluna `Cargo` da Bites traz 637 valores em
2.886 linhas: deputado estadual (379), imprensa (78), vereador (55),
comunicador (47), político (19), deputado federal (18). Dava para ver quem fala
— e a tela mostrava nada.

O QUE ESTES TESTES PROTEGEM:

* o cargo tem DUAS leituras da mesma célula: código para a régua de peso,
  rótulo para a tela — e as duas saem do mesmo caminho, para não divergirem;
* as grafias do mesmo cargo dobram: `Vereador`/`Vereadora`/`Verador` é um
  cargo, e sem dobrar a régua dava peso 1 à vereadora e 2 ao vereador;
* a dobra é por tabela, e NÃO por regra de sufixo: trocar "a" final por "o"
  quebraria `imprensa`, `empresa` e `prefeitura`;
* cargo que o fornecedor inventar aparece na tela mesmo assim;
* e a transformação SÓ vale quando a fonte diz que o perfil é o cargo —
  "Figura pública" numa coluna própria não pode voltar sem acento.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte
from app.casos_de_uso import ingerir_mencoes
from app.dominio.ingestao_score import (
    CARGO_CANONICO,
    Mapeamento,
    ler_linha,
    normalizar_cargo,
    rotulo_do_cargo,
)
from app.dominio.score import PESO_DO_CARGO, peso_do_cargo
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


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
def bites(sessao) -> ScoreFonte:
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))
    assert fonte is not None
    return fonte


# -- o cargo, sem banco ----------------------------------------------------------


@pytest.mark.parametrize(
    ("escrito", "codigo", "rotulo"),
    [
        ("Deputado Estadual", "deputado_estadual", "Deputado estadual"),
        ("Deputada Estadual", "deputado_estadual", "Deputado estadual"),
        ("Vereador", "vereador", "Vereador"),
        ("Vereadora", "vereador", "Vereador"),
        #: ERRO DE DIGITAÇÃO DO FORNECEDOR, uma menção no arquivo real.
        ("Verador", "vereador", "Vereador"),
        ("Comunicador", "comunicador", "Comunicador"),
        ("Imprensa", "imprensa", "Imprensa"),
    ],
)
def test_as_grafias_do_mesmo_cargo_dobram(escrito, codigo, rotulo):
    assert normalizar_cargo(escrito) == codigo
    assert rotulo_do_cargo(escrito) == rotulo


def test_a_dobra_NAO_e_regra_de_sufixo():
    #: Trocar "a" final por "o" quebraria estes três, que não são femininos de
    #: nada. É por isso que a dobra é tabela declarada, e não regra.
    for palavra in ("Imprensa", "Empresa", "Prefeitura"):
        codigo = normalizar_cargo(palavra)
        assert codigo not in CARGO_CANONICO
        assert codigo == palavra.lower()


def test_a_regua_de_peso_passou_a_valer_para_a_forma_feminina():
    #: ERA O DEFEITO MEDÍVEL: `PESO_DO_CARGO` só tem a forma masculina, então
    #: uma vereadora pesava 1 e um vereador 2. A dobra na normalização conserta
    #: os dois lados de uma vez, porque o peso lê o cargo já canonizado.
    assert peso_do_cargo(normalizar_cargo("Vereadora")) == PESO_DO_CARGO["vereador"]
    assert (
        peso_do_cargo(normalizar_cargo("Deputada Estadual"))
        == PESO_DO_CARGO["deputado_estadual"]
    )


def test_cargo_que_o_fornecedor_INVENTAR_aparece_na_tela():
    #: Esconder até alguém cadastrar faria o gráfico mentir por omissão.
    assert rotulo_do_cargo("Chefe de Gabinete") == "Chefe de gabinete"


def test_sem_cargo_nao_ha_perfil():
    assert normalizar_cargo("") is None
    assert rotulo_do_cargo(None) is None


def test_a_COLUNA_PROPRIA_de_perfil_passa_CRU(bites):
    """A proteção que a transformação não pode custar.

    A lente Sociedade conta `perfil_autor = 'Figura pública'` num KPI. Se o
    rótulo do cargo fosse aplicado a qualquer coluna de perfil, aquele valor
    voltaria "Figura publica" — sem acento, porque `achatar` tira acento para
    comparar — e o KPI nunca mais acharia nada.
    """
    #: Uma fonte com coluna PRÓPRIA de perfil, diferente da de cargo.
    mapeamento = Mapeamento.de_json(
        {
            "colunas": {
                "data": "Data",
                "sentimento": "Sentimento",
                "cargo": "Cargo",
                "perfil_autor": "Tipo de autor",
            }
        }
    )

    lido = ler_linha(
        {
            "Data": date(2026, 8, 3),
            "Sentimento": "Positivo",
            "Cargo": "Vereadora",
            "Tipo de autor": "Figura pública",
        },
        mapeamento,
    )

    assert lido.perfil_autor == "Figura pública"
    #: E o cargo continua dobrando, no campo dele.
    assert lido.cargo == "vereador"


# -- a subida inteira ------------------------------------------------------------


CABECALHO = [
    "Data",
    "Autor",
    "Cargo",
    "Sentimento",
    "Unidades/Empresas",
    "Engajamento",
]


def _planilha(cargos: list[str]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(CABECALHO)
    for indice, cargo in enumerate(cargos):
        aba.append(
            [date(2026, 8, 3 + indice), f"autor {indice}", cargo, "Negativo", "Corsan", 1]
        )
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def test_a_subida_preenche_o_perfil_de_quem_fala(sessao, bites):
    ingerir_mencoes.ingerir(
        sessao, bites, _planilha(["Deputado Estadual", "Comunicador", "Vereadora"])
    )

    perfis = sorted(
        p
        for (p,) in sessao.execute(
            select(Mencao.perfil_autor).where(Mencao.fonte_id == bites.id)
        )
    )
    assert perfis == ["Comunicador", "Deputado estadual", "Vereador"]


def test_a_linha_SEM_CARGO_entra_sem_perfil(sessao, bites):
    #: 2.249 das 2.886 linhas do arquivo real vêm sem cargo. Elas contam na
    #: nota e nos cortes; o que não fazem é inventar um perfil.
    resumo = ingerir_mencoes.ingerir(sessao, bites, _planilha([""]))

    assert resumo[0].ingeridas == 1
    gravada = sessao.scalar(select(Mencao).where(Mencao.fonte_id == bites.id))
    assert gravada.perfil_autor is None
    assert gravada.cargo is None


def test_o_ROTULO_da_propria_companhia_e_do_desconhecido_tem_ACENTO():
    """A derivação automática não devolve acento, e a tela mostrava o erro.

    Sem entrada em `ROTULO_DO_CARGO`, o rótulo sai de
    `codigo.replace("_", " ").capitalize()` — que põe maiúscula só na primeira
    letra e não tem como saber do acento. A tela do cliente mostrava "Unidade
    aegea" e "Nao identificado": é o tipo de erro que se lê como desleixo antes
    de se ler como defeito, e o nome da companhia é o pior lugar para ele.
    """
    from app.dominio.ingestao_score import rotulo_do_cargo

    assert rotulo_do_cargo("unidade_aegea") == "Unidade Aegea"
    assert rotulo_do_cargo("nao_identificado") == "Não identificado"
    assert rotulo_do_cargo("aegea") == "Aegea"
    #: E O CARGO QUE NINGUÉM CADASTROU continua aparecendo, derivado: esconder
    #: até alguém mapear faria o gráfico mentir por omissão.
    assert rotulo_do_cargo("coisa_nova") == "Coisa nova"
