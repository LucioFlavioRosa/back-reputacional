"""O perfil guarda o cargo que o fornecedor informou.

O QUE O DONO DO PRODUTO VIU. No Cadastro compartilhado, a deputada Stela Farias
aparecia como "Poder Legislativo" — o público está certo desde a `0075`, mas o
CARGO não aparecia em lugar nenhum. E é ele que diz quem é o ator: "Deputado
estadual · RS" responde a pergunta; "Poder Legislativo" diz só a que poder ele
pertence.

O cargo estava apenas em `mencao.cargo`, onde serve à régua de peso e ao
gráfico de quem fala. O Cadastro compartilhado lê o CATÁLOGO, não a base de
menções — então a tela não tinha de onde tirá-lo.

O QUE ESTES TESTES PROTEGEM:

* o rótulo vai para o cadastro ("Deputado estadual", não `deputado_estadual`);
* só perfil de rede tem cargo — um jornal não tem —, e a recusa fala de
  cadastro, não de constraint;
* quem edita à mão não é sobrescrito: o fornecedor erra (`stelafariasrs` veio
  com UF TO e sem cargo), e quem conhece o ator conserta na tela;
* e o rótulo da migration não divergiu do rótulo do domínio.
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
from app.casos_de_uso.veiculos_da_imprensa import CATEGORIA_POR_CARGO
from app.dominio.ingestao_score import CARGO_CANONICO, ROTULO_DO_CARGO
from app.dominio.texto import normalizar
from main import app
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
def cliente(sessao):
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": "plataforma_edicao"}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    feito = TestClient(app)
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


CABECALHO = [
    "Data",
    "Autor",
    "Cargo",
    "Sentimento",
    "Unidades/Empresas",
    "Engajamento",
]


def _planilha(autor: str, cargo: str) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(CABECALHO)
    aba.append([date(2026, 8, 3), autor, cargo, "Negativo", "Corsan", 1])
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _planilha_de_duas_linhas(autor: str, cargo_da_segunda: str) -> bytes:
    """O mesmo autor em duas linhas: a PRIMEIRA sem cargo, a segunda com.

    É a forma exata do defeito que `veiculos_da_planilha` tinha: `setdefault` só
    age quando a chave falta, ou seja na primeira linha daquele autor — e o que
    ele guardava era o valor DAQUELA linha, vazio incluído. O cargo da segunda ia
    para o lixo, e o perfil nascia sem público.
    """
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(CABECALHO)
    aba.append([date(2026, 8, 3), autor, None, "Negativo", "Corsan", 1])
    aba.append([date(2026, 8, 4), autor, cargo_da_segunda, "Negativo", "Corsan", 1])
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _bites(sessao):
    from app.banco.tabelas_score import ScoreFonte

    return sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))


def test_o_perfil_nasce_com_o_ROTULO_do_cargo(sessao):
    ingerir_mencoes.ingerir(
        sessao,
        _bites(sessao),
        _planilha("Stela Farias zz1", "Deputada Estadual"),
        veiculos_a_criar=("Stela Farias zz1",),
    )

    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("Stela Farias zz1")
        )
    )
    #: O RÓTULO, e não o código: a coluna é lida por gente, como
    #: `interlocutor.cargo`. O código continua em `mencao.cargo`, para a régua.
    assert criado.cargo == "Deputado estadual"


def test_o_veiculo_NAO_ganha_cargo(sessao):
    #: Um jornal não tem cargo, e o CHECK do banco recusaria.
    from app.banco.tabelas_score import ScoreFonte

    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert clipei is not None
    #: A Clipei não mapeia `cargo`, e `quem_fala` dela é `veiculo`: o caminho
    #: nem oferece cargo. O que se afirma aqui é a trava do banco.
    veiculo = Instituicao(
        nome="Jornal Qualquer zz2",
        nome_normalizado=normalizar("Jornal Qualquer zz2"),
        tipo="veiculo",
    )
    sessao.add(veiculo)
    sessao.flush()

    with pytest.raises(Exception, match="instituicao_cargo_so_de_perfil"):
        sessao.execute(
            text("update instituicao set cargo = :c where id = :i"),
            {"c": "Editor", "i": veiculo.id},
        )
        sessao.flush()


def test_a_tela_pode_CORRIGIR_o_cargo(cliente, sessao):
    """O fornecedor erra, e quem conhece o ator conserta.

    Medido no arquivo real: `stelafariasrs` veio com UF `TO` e sem cargo, quando
    é a mesma deputada do RS. O cargo tem de ser editável.
    """
    perfil = Instituicao(
        nome="stelafariasrs zz3",
        nome_normalizado=normalizar("stelafariasrs zz3"),
        tipo="perfil_rede",
    )
    sessao.add(perfil)
    sessao.flush()

    resposta = cliente.put(
        f"/api/instituicoes/{perfil.id}",
        json={
            "nome": perfil.nome,
            "tipo": "perfil_rede",
            "cargo": "Deputado estadual",
            "uf": "RS",
            "ativo": True,
        },
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["cargo"] == "Deputado estadual"
    sessao.expire_all()
    assert sessao.get(Instituicao, perfil.id).cargo == "Deputado estadual"


def test_a_api_recusa_cargo_em_quem_nao_e_perfil(cliente, sessao):
    veiculo = Instituicao(
        nome="Jornal Qualquer zz4",
        nome_normalizado=normalizar("Jornal Qualquer zz4"),
        tipo="veiculo",
    )
    sessao.add(veiculo)
    sessao.flush()

    resposta = cliente.put(
        f"/api/instituicoes/{veiculo.id}",
        json={
            "nome": veiculo.nome,
            "tipo": "veiculo",
            "cargo": "Editor",
            "ativo": True,
        },
    )

    assert resposta.status_code == 422, resposta.text
    assert "perfil de rede" in resposta.text


def test_o_rotulo_da_migration_bate_com_o_dominio():
    """A `0076` escreve os rótulos em SQL, porque migration não importa a app.

    DUAS CÓPIAS DA MESMA TABELA é a receita conhecida de divergir em silêncio:
    alguém acrescenta um cargo no domínio, a migration antiga fica para trás, e
    o backfill de uma base nova grava um rótulo diferente do que a ingestão
    grava. Este teste é a costura entre as duas.
    """
    sql = (
        Path(__file__).resolve().parents[1]
        / "app/banco/migrations/0076_o_perfil_guarda_o_cargo_informado.sql"
    ).read_text(encoding="utf-8")
    pares = dict(re.findall(r"\('([a-z_]+)',\s*'([^']+)'\)", sql))

    for codigo, rotulo in ROTULO_DO_CARGO.items():
        assert pares.get(codigo) == rotulo, codigo
    #: AS VARIANTES TAMBÉM, e com o rótulo do CANÔNICO: a migration lê
    #: `mencao.cargo` do que já está gravado, e numa base que ingeriu antes de
    #: `CARGO_CANONICO` existir esse valor pode ser `vereadora` ou `verador`.
    #: Sem elas, o backfill gravava "Verador" — o typo do fornecedor — como se
    #: fosse um cargo. Achado de revisão.
    for variante, canonico in CARGO_CANONICO.items():
        esperado = ROTULO_DO_CARGO.get(canonico)
        if esperado is None:
            continue
        assert pares.get(variante) == esperado, variante
    assert len(pares) == len(ROTULO_DO_CARGO) + len(CARGO_CANONICO)


def test_a_categoria_da_migration_bate_com_o_dominio():
    """A TERCEIRA cópia manual da mesma tabela, costurada.

    `CATEGORIA_POR_CARGO` (Python, usada na ingestão) e `publico_por_cargo`
    (SQL, usada no backfill da `0075`) dizem a mesma coisa em dois lugares.
    Divergindo, o perfil criado pela ingestão cai numa categoria e o backfill
    de uma base nova cai em outra — e a falha é MUDA dos dois lados: um
    `.get()` que não casa deixa o perfil sem público, indistinguível de "cargo
    desconhecido"; um `join` que não casa simplesmente não atualiza.

    A migration tem a mais as GRAFIAS VARIANTES, que a ingestão já dobra antes
    de chegar ao mapa — por isso a conferência é de inclusão, com a dobra
    aplicada.
    """
    sql = (
        Path(__file__).resolve().parents[1]
        / "app/banco/migrations/0075_o_publico_do_perfil_sai_do_cargo.sql"
    ).read_text(encoding="utf-8")
    trincas = re.findall(
        r"\('([a-z_]+)',\s*'([^']+)',\s*(?:'([^']+)'|null)\)", sql
    )
    da_migration = {cargo: (categoria, sub or None) for cargo, categoria, sub in trincas}

    for cargo, par in CATEGORIA_POR_CARGO.items():
        assert da_migration.get(cargo) == par, cargo

    #: E O QUE A MIGRATION TEM A MAIS tem de ser variante de algo mapeado, com
    #: o MESMO par do canônico — nada de público inventado só no SQL.
    for cargo, par in da_migration.items():
        if cargo in CATEGORIA_POR_CARGO:
            continue
        canonico = CARGO_CANONICO.get(cargo)
        assert canonico is not None, cargo
        assert CATEGORIA_POR_CARGO.get(canonico) == par, cargo


def test_o_cargo_da_SEGUNDA_linha_vale_quando_a_primeira_vem_vazia(sessao):
    """O "primeiro não vazio" passou a ser verdade. Achado MÉDIA de revisão.

    O COMENTÁRIO JÁ PROMETIA O CERTO e o código fazia outra coisa: "o primeiro
    cargo NÃO VAZIO, como a praça e a abrangência". `setdefault` só age quando a
    CHAVE falta — na primeira linha daquele autor —, e o que ele guardava era o
    valor daquela linha, VAZIO INCLUÍDO.

    O CARGO É O MAIS CARO DOS QUATRO CAMPOS que sofriam disso (praça, abrangência,
    cargo, tier), porque é ele que decide o PÚBLICO do perfil
    (`CATEGORIA_POR_CARGO`): primeira linha sem cargo fazia o vereador nascer sem
    público — o mesmo defeito que `CATEGORIA_DE_QUEM_FALA` registra como já
    consertado uma vez, voltando por outro caminho.

    E O RISCO É MEDIDO: 2.851 das 28.626 menções têm tier nulo, 10%. Coluna vazia
    na primeira linha de um ator não é caso raro.
    """
    from app.banco.tabelas_catalogo import CategoriaPublico

    ingerir_mencoes.ingerir(
        sessao,
        _bites(sessao),
        _planilha_de_duas_linhas("Iriel Sachet zz9", "Vereador"),
        veiculos_a_criar=("Iriel Sachet zz9",),
    )

    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("Iriel Sachet zz9")
        )
    )
    assert criado is not None, "o perfil não foi criado"
    #: O CARGO VEIO DA SEGUNDA LINHA.
    assert criado.cargo == "Vereador"
    #: E COM ELE O PÚBLICO, que é a consequência que importa: sem o cargo o perfil
    #: nasce em "Formadores de Opinião" ou sem categoria nenhuma, e um vereador
    #: classificado como formador de opinião foi exatamente a queixa que
    #: `CATEGORIA_POR_CARGO` existe para resolver.
    categoria, subcategoria = CATEGORIA_POR_CARGO["vereador"]
    esperada = sessao.scalar(
        select(CategoriaPublico.id).where(CategoriaPublico.nome == categoria)
    )
    assert criado.categoria_publico_id == esperada, (
        f"esperava o público de vereador ({categoria} / {subcategoria})"
    )
