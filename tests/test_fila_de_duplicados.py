"""A fila do mesmo ator cadastrado duas vezes, e as duas respostas.

A `0077` fundiu os homônimos exatos sozinha. O que sobra é o par que só casa
depois de tirar pontuação — `valoreconomico` ↔ `Valor Econômico` —, e ali
semelhança não é identidade: `Diário SM` e `Diários M` casam assim, `bmc.news`
casa com DOIS veículos.

O QUE ESTES TESTES PROTEGEM:

* a fila mostra o par parecido, com as menções de cada lado (é o número que diz
  qual é a linha com história);
* e NÃO mostra: o homônimo exato (é da `0077`), o par que alguém já declarou
  distinto, o perfil ligado a uma pessoa do CRM;
* a fusão move as menções para o sobrevivente e apaga o perfil;
* a fusão RECUSA o caminho inverso — apagar o veículo curado dentro do handle
  do fornecedor;
* "são atores diferentes" tira o par da fila, nas duas ordens, e clicar duas
  vezes não é erro.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import AtorDistinto, Instituicao, Interlocutor
from app.casos_de_uso import atores_duplicados
from app.dominio.erros import RegraViolada
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
def bites(sessao) -> ScoreFonte:
    return sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))


def _cadastrar(sessao, nome: str, tipo: str, **extra) -> Instituicao:
    registro = Instituicao(
        nome=nome, nome_normalizado=normalizar(nome), tipo=tipo, **extra
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _mencao(sessao, dono: Instituicao, fonte: ScoreFonte) -> None:
    sessao.add(
        Mencao(
            fonte_id=fonte.id,
            mes=date(2026, 8, 1),
            data=date(2026, 8, 3),
            sentimento="neg",
            veiculo=dono.nome,
            instituicao_id=dono.id,
        )
    )
    sessao.flush()


def _na_fila(sessao, qual) -> atores_duplicados.Duplicado | None:
    return next((d for d in atores_duplicados.listar(sessao) if d.id == qual), None)


# -- a chave da semelhança -------------------------------------------------------


def test_a_chave_junta_o_handle_e_o_nome():
    achatar = atores_duplicados.achatar_para_comparar

    assert achatar("valoreconomico") == achatar("Valor Econômico")
    assert achatar("gazeta_de_piracicaba") == achatar("Gazeta de Piracicaba")
    assert achatar("bmc.news") == achatar("BM&C News")
    #: E NÃO JUNTA O QUE É SÓ PARECIDO NO OLHO.
    assert achatar("Diário SM") != achatar("Diário de Santa Maria")


def test_a_chave_NAO_substitui_a_de_gravacao():
    #: `normalizar` carrega a unicidade do cadastro, e nela `valoreconomico` e
    #: `valor economico` são dois cadastros legítimos. Confundir as duas faria
    #: a gravação fundir sozinha o que esta fila existe para perguntar.
    assert normalizar("Valor Econômico") != atores_duplicados.achatar_para_comparar(
        "Valor Econômico"
    )


# -- a fila ----------------------------------------------------------------------


def test_a_fila_mostra_o_par_parecido_com_as_mencoes(sessao, bites):
    perfil = _cadastrar(sessao, "valorzz60", "perfil_rede", cargo="Imprensa")
    veiculo = _cadastrar(sessao, "Valor Zz60", "veiculo")
    _mencao(sessao, perfil, bites)
    for _ in range(3):
        _mencao(sessao, veiculo, bites)

    achado = _na_fila(sessao, perfil.id)

    assert achado is not None
    assert achado.mencoes == 1
    assert [(c.nome, c.mencoes) for c in achado.candidatos] == [("Valor Zz60", 3)]


def test_a_fila_NAO_mostra_o_homonimo_exato(sessao):
    #: Nome igual por `nome_normalizado` é da `0077`, que funde sem perguntar.
    #: Se aparecesse aqui, a tela pediria decisão sobre o que já foi decidido.
    perfil = _cadastrar(sessao, "Exame Zz61", "perfil_rede")
    _cadastrar(sessao, "exame zz61", "veiculo")

    assert _na_fila(sessao, perfil.id) is None


def test_a_fila_NAO_mostra_o_perfil_ligado_a_uma_pessoa(sessao):
    pessoa = Interlocutor(nome="Fulano Zz62", nome_normalizado=normalizar("Fulano Zz62"))
    sessao.add(pessoa)
    sessao.flush()
    perfil = _cadastrar(sessao, "fulanozz62", "perfil_rede", interlocutor_id=pessoa.id)
    _cadastrar(sessao, "Fulano Zz62 ", "veiculo")

    #: O sobrevivente não pode herdar a ligação (CHECK
    #: `instituicao_pessoa_so_de_perfil`), e desfazer escolha de gente não é
    #: fusão, é perda.
    assert _na_fila(sessao, perfil.id) is None

    #: CONTRAPESO: sem a ligação, o par É pergunta — o teste acima não está
    #: passando porque nada apareceria de todo jeito.
    perfil.interlocutor_id = None
    sessao.flush()
    assert _na_fila(sessao, perfil.id) is not None


def test_a_fila_NAO_repete_o_que_alguem_ja_decidiu(sessao):
    perfil = _cadastrar(sessao, "diariosmzz63", "perfil_rede")
    outro = _cadastrar(sessao, "Diários M Zz63", "veiculo")
    #: mesma chave achatada? não — este par é só para o fluxo de decisão.
    outro.nome = "Diario Sm Zz63"
    outro.nome_normalizado = normalizar("Diario Sm Zz63")
    sessao.flush()
    assert _na_fila(sessao, perfil.id) is not None

    atores_duplicados.declarar_distintos(sessao, um=perfil.id, outro=outro.id)

    assert _na_fila(sessao, perfil.id) is None


def test_o_veiculo_NAO_entra_na_fila_como_pergunta(sessao):
    #: Dois veículos de nome parecido são outra conversa: essa base é curada à
    #: mão, e o par nasce da ingestão de redes sociais. A fila pergunta sobre o
    #: perfil.
    um = _cadastrar(sessao, "jornalzz64", "veiculo")
    _cadastrar(sessao, "Jornal Zz64", "veiculo")

    assert _na_fila(sessao, um.id) is None

    #: CONTRAPESO: é o TIPO que o tira da fila, e não a semelhança fraca.
    um.tipo = "perfil_rede"
    sessao.flush()
    assert _na_fila(sessao, um.id) is not None


def test_a_mesma_pergunta_aparece_UMA_VEZ(sessao, bites):
    """Dois perfis parecidos davam DUAS linhas na fila.

    Medido na pilha: 144 linhas para ~100 perguntas, porque `AC 24 Horas →
    ac24horas` e `ac24horas → AC 24 Horas` são a mesma dúvida em dois pontos da
    lista alfabética. Responder uma resolvia as duas — mas quem abre a tela lê
    o dobro do trabalho que existe, e o contador mente.
    """
    magro = _cadastrar(sessao, "ac24horaszz72", "perfil_rede")
    gordo = _cadastrar(sessao, "AC 24 Horas Zz72", "perfil_rede")
    _mencao(sessao, gordo, bites)
    _mencao(sessao, gordo, bites)
    _mencao(sessao, magro, bites)

    fila = atores_duplicados.listar(sessao)
    deste_par = [
        d for d in fila if d.id in {magro.id, gordo.id}
    ]

    assert len(deste_par) == 1
    #: E ANCORADA EM QUEM VAI SUMIR: o lado com menos menções pergunta, a linha
    #: com história sobrevive — a mesma orientação que `fundir` exige.
    assert deste_par[0].id == magro.id
    assert [c.id for c in deste_par[0].candidatos] == [gordo.id]


def test_com_VEICULO_do_outro_lado_a_pergunta_nasce_do_perfil(sessao, bites):
    #: Aqui não há escolha de lado: só o perfil de rede entra em outro
    #: cadastro. Mesmo com MAIS menções que o veículo, é ele que pergunta.
    perfil = _cadastrar(sessao, "valorzz73", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz73", "veiculo")
    for _ in range(5):
        _mencao(sessao, perfil, bites)

    achado = _na_fila(sessao, perfil.id)

    assert achado is not None
    assert [c.id for c in achado.candidatos] == [veiculo.id]


# -- a fusão ---------------------------------------------------------------------


def test_a_fusao_leva_as_mencoes_e_apaga_o_perfil(sessao, bites):
    perfil = _cadastrar(sessao, "valorzz65", "perfil_rede", cargo="Imprensa")
    veiculo = _cadastrar(sessao, "Valor Zz65", "veiculo")
    _mencao(sessao, perfil, bites)
    _mencao(sessao, veiculo, bites)
    id_do_perfil, id_do_veiculo = perfil.id, veiculo.id

    atores_duplicados.fundir(
        sessao, perfil_id=id_do_perfil, sobrevivente_id=id_do_veiculo
    )

    sobrou = sessao.scalar(
        select(func.count()).select_from(Instituicao).where(Instituicao.id == id_do_perfil)
    )
    assert sobrou == 0
    juntas = sessao.scalar(
        select(func.count()).select_from(Mencao).where(Mencao.instituicao_id == id_do_veiculo)
    )
    assert juntas == 2


def test_a_fusao_RECUSA_apagar_o_veiculo_curado(sessao):
    """O caminho inverso não é oferecido.

    O veículo é a linha com categoria, subcategoria, UF e frente, e com o nome
    escrito por gente. Fundir ele dentro do handle do fornecedor perderia a
    curadoria — e quem clica numa tela de duplicados não está pedindo isso.
    """
    perfil = _cadastrar(sessao, "valorzz66", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz66", "veiculo")

    with pytest.raises(RegraViolada, match="perfil de rede"):
        atores_duplicados.fundir(
            sessao, perfil_id=veiculo.id, sobrevivente_id=perfil.id
        )


def test_a_fusao_recusa_o_perfil_ligado_a_uma_pessoa(sessao):
    pessoa = Interlocutor(nome="Fulano Zz67", nome_normalizado=normalizar("Fulano Zz67"))
    sessao.add(pessoa)
    sessao.flush()
    perfil = _cadastrar(sessao, "fulanozz67", "perfil_rede", interlocutor_id=pessoa.id)
    veiculo = _cadastrar(sessao, "Fulano Zz67", "veiculo")

    with pytest.raises(RegraViolada, match="pessoa"):
        atores_duplicados.fundir(
            sessao, perfil_id=perfil.id, sobrevivente_id=veiculo.id
        )


def test_a_fusao_recusa_o_cadastro_com_ele_mesmo(sessao):
    perfil = _cadastrar(sessao, "valorzz68", "perfil_rede")

    with pytest.raises(RegraViolada, match="ele mesmo"):
        atores_duplicados.fundir(
            sessao, perfil_id=perfil.id, sobrevivente_id=perfil.id
        )


def test_a_fusao_LEVA_AS_PESSOAS_do_perfil(sessao):
    #: Sem isto a exclusão bate na chave estrangeira e a fusão morre no meio,
    #: com a menção já movida.
    perfil = _cadastrar(sessao, "grupozz69", "perfil_rede")
    veiculo = _cadastrar(sessao, "Grupo Zz69", "veiculo")
    pessoa = Interlocutor(
        nome="Fulana Zz69",
        nome_normalizado=normalizar("Fulana Zz69"),
        instituicao_id=perfil.id,
    )
    sessao.add(pessoa)
    sessao.flush()

    atores_duplicados.fundir(sessao, perfil_id=perfil.id, sobrevivente_id=veiculo.id)

    sessao.expire_all()
    assert sessao.scalar(
        select(Interlocutor.instituicao_id).where(Interlocutor.id == pessoa.id)
    ) == veiculo.id


# -- "são atores diferentes" -----------------------------------------------------


def test_o_par_distinto_e_guardado_SEM_LADO(sessao):
    um = _cadastrar(sessao, "diariozz70", "perfil_rede")
    outro = _cadastrar(sessao, "Diário Zz70", "veiculo")

    atores_duplicados.declarar_distintos(sessao, um=outro.id, outro=um.id)

    #: Gravado na ordem canônica, e a chave primária recusa a repetição.
    esquerda, direita = atores_duplicados.ordenar_o_par(um.id, outro.id)
    assert sessao.get(AtorDistinto, (esquerda, direita)) is not None


def test_declarar_DUAS_VEZES_nao_e_erro(sessao):
    um = _cadastrar(sessao, "diariozz71", "perfil_rede")
    outro = _cadastrar(sessao, "Diário Zz71", "veiculo")

    atores_duplicados.declarar_distintos(sessao, um=um.id, outro=outro.id)
    atores_duplicados.declarar_distintos(
        sessao, um=outro.id, outro=um.id, motivo="jornais diferentes"
    )

    quantos = sessao.scalar(select(func.count()).select_from(AtorDistinto))
    assert quantos == 1
    esquerda, direita = atores_duplicados.ordenar_o_par(um.id, outro.id)
    assert sessao.get(AtorDistinto, (esquerda, direita)).motivo == "jornais diferentes"


# -- as rotas --------------------------------------------------------------------


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


def test_a_rota_lista_a_fila(cliente, sessao, bites):
    perfil = _cadastrar(sessao, "valorzz80", "perfil_rede", cargo="Imprensa")
    veiculo = _cadastrar(sessao, "Valor Zz80", "veiculo")
    _mencao(sessao, veiculo, bites)

    resposta = cliente.get("/api/instituicoes/duplicados")

    assert resposta.status_code == 200, resposta.text
    achado = next(d for d in resposta.json() if d["id"] == str(perfil.id))
    assert achado["cargo"] == "Imprensa"
    assert achado["candidatos"][0]["nome"] == "Valor Zz80"
    assert achado["candidatos"][0]["mencoes"] == 1


def test_a_rota_funde(cliente, sessao, bites):
    perfil = _cadastrar(sessao, "valorzz81", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz81", "veiculo")
    _mencao(sessao, perfil, bites)

    resposta = cliente.post(
        f"/api/instituicoes/{perfil.id}/fundir",
        json={"sobrevivente_id": str(veiculo.id)},
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["nome"] == "Valor Zz81"
    sessao.expire_all()
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.instituicao_id == veiculo.id)
        )
        == 1
    )


def test_a_rota_RECUSA_o_caminho_inverso(cliente, sessao):
    perfil = _cadastrar(sessao, "valorzz82", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz82", "veiculo")

    resposta = cliente.post(
        f"/api/instituicoes/{veiculo.id}/fundir",
        json={"sobrevivente_id": str(perfil.id)},
    )

    #: A recusa fala de cadastro, e diz o gesto certo.
    assert resposta.status_code == 422, resposta.text
    assert "perfil de rede" in resposta.text


def test_a_rota_guarda_o_par_distinto(cliente, sessao):
    perfil = _cadastrar(sessao, "diariozz83", "perfil_rede")
    outro = _cadastrar(sessao, "Diário Zz83", "veiculo")

    resposta = cliente.post(
        "/api/atores-distintos",
        json={
            "um_id": str(perfil.id),
            "outro_id": str(outro.id),
            "motivo": "jornais diferentes",
        },
    )

    assert resposta.status_code == 200, resposta.text
    esquerda, direita = atores_duplicados.ordenar_o_par(perfil.id, outro.id)
    sessao.expire_all()
    guardado = sessao.get(AtorDistinto, (esquerda, direita))
    assert guardado.motivo == "jornais diferentes"
    #: E QUEM DECIDIU fica registrado: a fusão não tem volta, e o par recusado
    #: barra fusão automática futura.
    assert guardado.decidido_por is not None
