"""Quais veículos a lente Mercado considera — definido pelo cadastro.

A LENTE MERCADO SE SEPARAVA POR UMA COLUNA DO FORNECEDOR
(`Público-alvo = Investidores`). Medido contra o export de 08–09/2026, isso
captura 80 linhas onde a lista de veículos que a Aegea mantém captura 323, e os
dois critérios discordam em 267 das 335 linhas envolvidas — o da coluna perde
Valor Econômico (49 menções), InfoMoney (25), Expert XP (20) e Times Brasil
(15). O critério passou a ser a SUBCATEGORIA DE PÚBLICO do cadastro, e esta
rota é como a lista se mantém: por tela, não por SQL.

O QUE ESTES TESTES PROTEGEM, e por que cada um importa:

* a gravação é DECLARATIVA — "estes são os veículos de mercado". Quem sai da
  lista perde a subcategoria DO MERCADO, e só ela.
* uma subcategoria escolhida à mão NÃO é sobrescrita nem apagada. Marcar um
  veículo como imprensa econômica não pode desfazer uma classificação que
  alguém fez, e desmarcá-lo não pode apagar outra.
* o par é (categoria, subcategoria): `subcategoria_publico` repete nome entre
  categorias de propósito, e casar só pelo nome pegaria a subcategoria de outro
  público.
* só quem administra cadastros muda isto — é cadastro compartilhado, e a lista
  muda um número que a diretoria lê.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao
from main import app
from tests.test_e2e_postgres import URL, corpo

_engine = create_engine(URL, pool_pre_ping=True)

ROTA = "/api/score/veiculos-de-investidores"


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
    """`plataforma_edicao`: administra os cadastros compartilhados."""
    feito = _cliente(sessao, "plataforma_edicao")
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_cadastro(sessao):
    """`crm_edicao`: escreve agenda e NÃO administra cadastro."""
    feito = _cliente(sessao, "crm_edicao")
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def mercado(sessao) -> int:
    """O id da subcategoria que define a lente Mercado, como o banco a tem."""
    achado = sessao.scalar(
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
    assert achado is not None, (
        "a subcategoria 'Econômica e de negócios' da Imprensa tem de existir — "
        "é a `0061` que a cria, e é dela que a lente Mercado depende"
    )
    return achado


@pytest.fixture
def outra_subcategoria(sessao, mercado: int) -> int:
    """Uma subcategoria da Imprensa que NÃO é a do mercado."""
    achada = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(CategoriaPublico.nome == "Imprensa", SubcategoriaPublico.id != mercado)
        .limit(1)
    )
    assert achada is not None
    return achada


def _veiculo(sessao, nome: str, subcategoria: int | None = None) -> Instituicao:
    from app.dominio.texto import normalizar

    feito = Instituicao(
        nome=nome,
        nome_normalizado=normalizar(nome),
        tipo="veiculo",
        subcategoria_publico_id=subcategoria,
    )
    sessao.add(feito)
    sessao.flush()
    return feito


def test_marca_os_veiculos_da_lista(cliente, sessao, mercado):
    valor = _veiculo(sessao, "Valor Econômico zz1")
    info = _veiculo(sessao, "InfoMoney zz1")

    resposta = cliente.put(ROTA, json={"ids": [str(valor.id), str(info.id)]})

    assert resposta.status_code == 200, corpo(resposta)
    assert resposta.json()["marcados"] == 2
    sessao.expire_all()
    assert sessao.get(Instituicao, valor.id).subcategoria_publico_id == mercado
    assert sessao.get(Instituicao, info.id).subcategoria_publico_id == mercado


def test_quem_sai_da_lista_perde_a_subcategoria_do_mercado(cliente, sessao, mercado):
    #: A GRAVAÇÃO É DECLARATIVA: mandar a lista sem um veículo é dizer que ele
    #: não é mais de mercado. É o gesto que a tela faz quando se desmarca.
    sai = _veiculo(sessao, "Jornal que saiu zz2", mercado)
    fica = _veiculo(sessao, "Jornal que ficou zz2", mercado)

    resposta = cliente.put(ROTA, json={"ids": [str(fica.id)]})

    assert resposta.status_code == 200, corpo(resposta)
    assert resposta.json()["desmarcados"] >= 1
    sessao.expire_all()
    assert sessao.get(Instituicao, sai.id).subcategoria_publico_id is None
    assert sessao.get(Instituicao, fica.id).subcategoria_publico_id == mercado


def test_nao_sobrescreve_subcategoria_que_alguem_escolheu(
    cliente, sessao, mercado, outra_subcategoria
):
    #: Tirar o veículo do Mercado não pode apagar uma classificação feita à
    #: mão, e marcá-lo não pode substituí-la: as duas coisas desfariam trabalho
    #: humano com uma lista. Fora da lista E dentro dela, ele fica como está.
    classificado = _veiculo(sessao, "Jornal do Bairro zz3", outra_subcategoria)

    fora = cliente.put(ROTA, json={"ids": []})
    assert fora.status_code == 200, corpo(fora)
    sessao.expire_all()
    assert (
        sessao.get(Instituicao, classificado.id).subcategoria_publico_id
        == outra_subcategoria
    )

    dentro = cliente.put(ROTA, json={"ids": [str(classificado.id)]})
    assert dentro.status_code == 200, corpo(dentro)
    sessao.expire_all()
    assert (
        sessao.get(Instituicao, classificado.id).subcategoria_publico_id
        == outra_subcategoria
    )


def test_ignora_quem_nao_e_veiculo(cliente, sessao, mercado):
    #: A lente lê `mencao`, que aponta para veículo. Marcar um órgão como
    #: imprensa econômica seria cadastro errado sem efeito nenhum — e a tela
    #: nem o oferece, então um id assim é erro de quem chamou a rota.
    from app.dominio.texto import normalizar

    orgao = Instituicao(
        nome="Ministério das Cidades zz4",
        nome_normalizado=normalizar("Ministério das Cidades zz4"),
        tipo="orgao",
    )
    sessao.add(orgao)
    sessao.flush()

    resposta = cliente.put(ROTA, json={"ids": [str(orgao.id)]})

    assert resposta.status_code == 200, corpo(resposta)
    assert resposta.json()["marcados"] == 0
    sessao.expire_all()
    assert sessao.get(Instituicao, orgao.id).subcategoria_publico_id is None


def test_id_que_nao_existe_nao_derruba_a_gravacao(cliente, sessao, mercado):
    #: Um id de instituição apagada noutra aba não pode impedir a pessoa de
    #: salvar os outros 80.
    from uuid import uuid4

    valor = _veiculo(sessao, "Valor Econômico zz5")

    resposta = cliente.put(ROTA, json={"ids": [str(valor.id), str(uuid4())]})

    assert resposta.status_code == 200, corpo(resposta)
    assert resposta.json()["marcados"] == 1


def test_regravar_a_mesma_lista_nao_muda_nada(cliente, sessao, mercado):
    valor = _veiculo(sessao, "Valor Econômico zz6", mercado)

    resposta = cliente.put(ROTA, json={"ids": [str(valor.id)]})

    assert resposta.status_code == 200, corpo(resposta)
    #: Os outros veículos de mercado do banco não entram nesta conta: o que se
    #: afirma aqui é que o que já estava certo não é tocado de novo.
    assert resposta.json()["marcados"] == 0


def test_lista_vazia_e_um_pedido_legitimo(cliente, sessao, mercado):
    #: "Nenhum veículo é de mercado" é uma decisão possível, e não um erro de
    #: preenchimento: recusá-la deixaria a pessoa sem como esvaziar a lista.
    unico = _veiculo(sessao, "Jornal único zz7", mercado)

    resposta = cliente.put(ROTA, json={"ids": []})

    assert resposta.status_code == 200, corpo(resposta)
    sessao.expire_all()
    assert sessao.get(Instituicao, unico.id).subcategoria_publico_id is None


def test_campo_desconhecido_e_recusado(cliente):
    #: `extra="forbid"`: um corpo com `veiculos` em vez de `ids` gravaria uma
    #: lista VAZIA em silêncio — e apagaria os 81.
    resposta = cliente.put(ROTA, json={"veiculos": []})

    assert resposta.status_code == 422, corpo(resposta)


def test_so_quem_administra_cadastros_muda_a_lista(cliente_sem_cadastro):
    resposta = cliente_sem_cadastro.put(ROTA, json={"ids": []})

    assert resposta.status_code == 403, corpo(resposta)
