"""As rotas que mantêm uma lista de veículos — QUALQUER uma, não só a do Mercado.

O PEDIDO (20/10/2026) foi a lente Institucional recortar a imprensa "assim como
fizemos para a lente mercado", com a mesma reescrita do histórico. O motor já
era por lista e por fonte; estas rotas é que assumiam a do Mercado.

O QUE ESTES TESTES PROTEGEM:

1. que a lista venha do ENDEREÇO e chegue até o cadastro — gravar na
   subcategoria da outra lente seria mover veículo de lente sem ninguém pedir;
2. que as duas listas não se misturem: marcar um veículo como institucional não
   pode tirar (nem pôr) ninguém no Mercado;
3. que uma lista que não existe seja recusada, em vez de responder lista vazia —
   um nome errado na tela viraria "nenhum veículo" sem explicação;
4. que os CAMINHOS ANTIGOS continuem respondendo a lista do Mercado. O back sobe
   antes do front, e a tela que está no ar ainda os chama.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.texto import normalizar
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

DA_LISTA = "/api/score/veiculos-da-lista"
ANTIGA = "/api/score/veiculos-de-investidores"


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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


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


def _veiculo(sessao, nome: str) -> Instituicao:
    feito = Instituicao(nome=nome, nome_normalizado=normalizar(nome), tipo="veiculo")
    sessao.add(feito)
    sessao.flush()
    return feito


def test_a_lista_do_ENDERECO_e_a_que_recebe_o_veiculo(cliente, sessao):
    alvo = _veiculo(sessao, "Agência Institucional zz31")

    resposta = cliente.put(
        f"{DA_LISTA}/imprensa_institucional",
        json={"ids": [str(alvo.id)], "conhecidos": []},
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["marcados"] == 1
    sessao.refresh(alvo)
    assert alvo.subcategoria_publico_id == _subcategoria(sessao, "Institucional")


def test_as_duas_listas_NAO_se_misturam(cliente, sessao):
    """Marcar institucional não mexe em quem é do Mercado, e vice-versa.

    É a conferência que a tela gêmea exige: as duas gravam na MESMA coluna
    (`instituicao.subcategoria_publico_id`), cada uma com o seu alvo. Se a
    gravação de uma lista enxergasse a outra, salvar a tela do Institucional
    esvaziaria o Mercado — e o Mercado é 20% do índice.
    """
    do_mercado = _veiculo(sessao, "Jornal do Mercado zz32")
    do_mercado.subcategoria_publico_id = _subcategoria(sessao, "Econômica e de negócios")
    institucional = _veiculo(sessao, "Agência Institucional zz33")
    sessao.flush()

    resposta = cliente.put(
        f"{DA_LISTA}/imprensa_institucional",
        json={"ids": [str(institucional.id)], "conhecidos": []},
    )
    assert resposta.status_code == 200, resposta.text

    sessao.refresh(do_mercado)
    #: O DO MERCADO CONTINUA ONDE ESTAVA — nem desmarcado, nem recusado.
    assert do_mercado.subcategoria_publico_id == _subcategoria(
        sessao, "Econômica e de negócios"
    )
    assert resposta.json()["desmarcados"] == 0


def test_salvar_a_lista_VAZIA_com_ids_vazios_nao_toca_na_outra(cliente, sessao):
    """O caso destrutivo do declarativo: "a lista é NENHUM".

    `ids=[]` afirma que a lista pedida está vazia, e é a forma mais curta de
    pedir uma remoção em massa. Ela tem de alcançar SÓ a lista do endereço.
    """
    do_mercado = _veiculo(sessao, "Jornal do Mercado zz34")
    do_mercado.subcategoria_publico_id = _subcategoria(sessao, "Econômica e de negócios")
    sessao.flush()

    resposta = cliente.put(
        f"{DA_LISTA}/imprensa_institucional", json={"ids": [], "conhecidos": []}
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["desmarcados"] == 0
    sessao.refresh(do_mercado)
    assert do_mercado.subcategoria_publico_id is not None


def test_duas_gravacoes_na_LISTA_VAZIA_nao_se_atropelam(cliente, sessao):
    """ACHADO ALTO DE REVISÃO, e ele é ANTERIOR a esta rota.

    A guarda de concorrência trava as linhas que a gravação MENCIONA
    (`pedidos ∪ conhecidos`). Com a lista vazia, duas pessoas acrescentando
    veículos DIFERENTES não mencionam nenhuma linha em comum: as duas travam
    coisas distintas, as duas leem a lista vazia, as duas passam pela
    conferência de `conhecidos` — e o resultado é {A, B}, quando cada uma
    afirmou que a lista inteira era só o seu veículo.

    ESTAVA DORMENTE porque a lista do Mercado nunca esteve vazia (a `0066`
    semeou 81). A Institucional NASCE vazia: é o estado em que ele acorda.

    O QUE ESTE TESTE MEDE é a trava, e não a corrida: reproduzir duas sessões
    simultâneas aqui exigiria duas conexões e um `commit` no meio — e o teste
    inteiro vive numa transação que termina em rollback. O que se afirma é que
    a gravação PEDE a trava da lista; sem ela, as duas gravações nem se veem.
    """
    executadas: list[str] = []
    original = sessao.execute

    def espiando(consulta, *resto, **nomeados):
        executadas.append(str(consulta))
        return original(consulta, *resto, **nomeados)

    sessao.execute = espiando  # type: ignore[method-assign]
    try:
        alvo = _veiculo(sessao, "Agência Institucional zz35")
        resposta = cliente.put(
            f"{DA_LISTA}/imprensa_institucional",
            json={"ids": [str(alvo.id)], "conhecidos": []},
        )
    finally:
        sessao.execute = original  # type: ignore[method-assign]

    assert resposta.status_code == 200, resposta.text
    assert any("pg_advisory_xact_lock" in consulta for consulta in executadas), (
        "a gravação da lista tem de pedir a trava da lista — sem ela, duas "
        "pessoas partindo da lista vazia não se enxergam"
    )


def test_a_lista_QUE_NAO_EXISTE_e_recusada(cliente):
    #: 404, e não lista vazia: um nome errado na tela tem de doer aqui, e não
    #: virar "nenhum veículo" que ninguém sabe explicar. É a mesma escolha que
    #: `nomes_da_lista` faz no motor.
    assert cliente.get(f"{DA_LISTA}/imprensa_que_nao_existe/reconciliacao").status_code == 404
    assert cliente.put(
        f"{DA_LISTA}/imprensa_que_nao_existe", json={"ids": [], "conhecidos": []}
    ).status_code == 404


def test_a_previa_por_lista_responde_a_fonte_daquela_lente(cliente):
    institucional = cliente.get(f"{DA_LISTA}/imprensa_institucional/reconciliacao")
    assert institucional.status_code == 200, institucional.text
    assert [linha["fonte"] for linha in institucional.json()] == ["clipei_institucional"]

    mercado = cliente.get(f"{DA_LISTA}/imprensa_economica/reconciliacao")
    assert mercado.status_code == 200, mercado.text
    assert [linha["fonte"] for linha in mercado.json()] == ["clipei_investidores"]


def test_o_caminho_ANTIGO_continua_sendo_o_do_mercado(cliente):
    """O back sobe antes do front: a tela no ar ainda chama este endereço.

    Removê-lo junto faria "Veículos de investidores" responder 404 por alguns
    minutos, num deploy que não tem nada a ver com ela.
    """
    antiga = cliente.get(f"{ANTIGA}/reconciliacao")
    nova = cliente.get(f"{DA_LISTA}/imprensa_economica/reconciliacao")

    assert antiga.status_code == 200, antiga.text
    assert antiga.json() == nova.json()
