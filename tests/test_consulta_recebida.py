"""A consulta recebida e a alegação que ela carrega — o contrato de ponta a ponta.

O QUE ESTE ARQUIVO PROTEGE
--------------------------
A leitura que a aba de Sinais faz: "esta premissa chegou de N instituições
distintas em X dias". Ela depende de três coisas que só se provam com o banco
de verdade:

1. a consulta gravar e voltar inteira (o bloco 1-1 convive com a extensão da
   frente, em vez de substituí-la);
2. a mesma alegação não entrar duas vezes por causa de acento ou maiúscula —
   senão a contagem se parte em duas;
3. o filtro por alegação ser aplicado PELO SERVIDOR (ADR 0002), para a tela,
   a exportação e as métricas contarem o mesmo.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_alegacoes import Alegacao
from app.banco.tabelas_catalogo import Apuracao
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.texto import normalizar
from main import app
from tests.test_e2e_postgres import URL, corpo

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
def cliente_admin(sessao):
    """`plataforma_edicao`: escreve agenda E administra cadastros — os dois
    papéis que esta funcionalidade usa (registrar a consulta, apurar a
    alegação)."""
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como_admin = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": "plataforma_edicao"}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como_admin
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente(sessao):
    """`crm_edicao`: escreve agenda e NÃO vê campos sensíveis nem administra
    cadastros — o perfil mais comum, e o que este arquivo usa para provar o
    que NÃO sai."""
    from fastapi.testclient import TestClient

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    """Só a instituição de imprensa que `corpo` usa como padrão."""
    valor = Instituicao(
        nome="Valor Econômico", nome_normalizado="valor economico", tipo="veiculo", uf="SP"
    )
    sessao.add(valor)
    sessao.flush()
    return {"instituicao": valor}


@pytest.fixture
def credor(cliente_admin, semente):
    """Um banco: tipo `credor`, e portanto frente `bancos_credores`."""
    dicionarios = cliente_admin.get("/api/dicionarios").json()
    mercado = next(
        c for c in dicionarios["categorias_publico"]
        if c["codigo"] == "mercado_financeiro_capitais"
    )
    resposta = cliente_admin.post(
        "/api/instituicoes",
        json={
            "nome": "Banco da Sondagem",
            "tipo": "credor",
            "categoria_publico_id": mercado["id"],
        },
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _alegacao(cliente_admin, texto: str, **ajustes):
    resposta = cliente_admin.post(
        "/api/alegacoes", json={"texto": texto, **ajustes}
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _tipo_de_consulta(cliente_admin) -> int:
    formatos = cliente_admin.get("/api/dicionarios").json()["formatos_interacao"]
    return next(f["id"] for f in formatos if f["codigo"] == "consulta_recebida")


def _consulta(cliente_admin, semente, instituicao_id, **ajustes):
    corpo_ = corpo(semente)
    corpo_["instituicao_id"] = instituicao_id
    # SEM `frente` NO CORPO, de propósito: é ela que o servidor deriva do tipo
    # da instituição, e é isso que se está provando aqui.
    corpo_.pop("frente", None)
    corpo_["formato_interacao_id"] = _tipo_de_consulta(cliente_admin)
    # O BLOCO SEMPRE VIAJA no tipo de consulta, como a tela faz: ele é o
    # marcador de consulta para quem lê, e alegação sem ele é recusada.
    corpo_["consulta"] = {}
    corpo_.update(ajustes)
    resposta = cliente_admin.post("/api/interacoes", json=corpo_)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_o_tipo_consulta_recebida_existe_no_dicionario(cliente_admin):
    formatos = cliente_admin.get("/api/dicionarios").json()["formatos_interacao"]
    assert any(f["codigo"] == "consulta_recebida" for f in formatos)


def test_canais_e_apuracoes_chegam_ao_catalogo(cliente_admin):
    dicionarios = cliente_admin.get("/api/dicionarios").json()
    assert {c["codigo"] for c in dicionarios["canais_consulta"]} >= {"email", "plataforma"}
    apuracoes = {a["codigo"]: a for a in dicionarios["apuracoes"]}
    assert set(apuracoes) == {
        "em_apuracao", "sem_fundamento", "procede_em_parte", "procede"
    }
    # A tela pinta a alegação por este código, como faz com clima.
    assert all(a["cor_hex"].startswith("#") for a in apuracoes.values())


def test_a_consulta_grava_e_volta_inteira(cliente_admin, semente, credor):
    canal = next(
        c for c in cliente_admin.get("/api/dicionarios").json()["canais_consulta"]
        if c["codigo"] == "email"
    )
    alegacao = _alegacao(
        cliente_admin, "O Banco da Sondagem não renegociaria a dívida da Aegea"
    )

    criada = _consulta(
        cliente_admin,
        semente,
        credor["id"],
        consulta={
            "canal_id": canal["id"],
            "remetente": "analista@bancodasondagem.com",
            "teor": "Como a companhia trata a hipótese de não renegociação?",
            "prazo_resposta": "2026-06-30",
        },
        alegacoes=[alegacao["id"]],
    )

    assert criada["consulta"]["remetente"] == "analista@bancodasondagem.com"
    assert criada["consulta"]["prazo_resposta"] == "2026-06-30"
    assert criada["consulta"]["respondida_em"] is None
    assert criada["alegacoes"] == [alegacao["id"]]

    # E volta igual na leitura, que é outro caminho de código.
    lida = cliente_admin.get(f"/api/interacoes/{criada['id']}").json()
    assert lida["consulta"]["teor"].startswith("Como a companhia")
    assert lida["alegacoes"] == [alegacao["id"]]


def test_a_consulta_convive_com_a_extensao_da_frente(cliente_admin, semente, credor):
    """O bloco da consulta é escolhido pelo TIPO; a extensão, pela FRENTE.

    Uma consulta de banco é frente `bancos_credores` — que compartilha a
    extensão institucional com Governo, Parceiros e Eventos. Se a consulta
    ocupasse o lugar da extensão, um dos dois se perderia ao salvar.
    """
    criada = _consulta(
        cliente_admin,
        semente,
        credor["id"],
        consulta={"remetente": "mesa@banco.com"},
        extensao={"cargo_interlocutor": "Mesa de crédito"},
    )
    assert criada["frente"] == "bancos_credores"
    assert criada["consulta"]["remetente"] == "mesa@banco.com"
    assert criada["extensao"]["cargo_interlocutor"] == "Mesa de crédito"


def test_deixar_de_ser_consulta_larga_o_bloco(cliente_admin, semente, credor):
    """Senão sobra prazo de resposta numa reunião."""
    criada = _consulta(
        cliente_admin, semente, credor["id"], consulta={"remetente": "mesa@banco.com"}
    )
    atualizada = cliente_admin.patch(
        f"/api/interacoes/{criada['id']}", json={"consulta": None}
    )
    assert atualizada.status_code == 200, atualizada.text
    assert atualizada.json()["consulta"] is None


def test_a_mesma_alegacao_nao_entra_duas_vezes(cliente_admin):
    """O índice único é sobre o texto NORMALIZADO: acento e maiúscula não
    criam uma segunda alegação, senão a contagem da aba se parte em duas."""
    _alegacao(cliente_admin, "O rating da companhia cairia em junho")

    repetida = cliente_admin.post(
        "/api/alegacoes", json={"texto": "  o RATING da companhia cairia em junho  "}
    )
    assert repetida.status_code == 422
    assert "já está cadastrada" in repetida.json()["detalhe"]


def test_a_alegacao_nasce_em_apuracao(cliente_admin):
    """Dizer "sem fundamento" por omissão seria afirmar o que ninguém
    verificou."""
    apuracoes = {
        a["id"]: a["codigo"]
        for a in cliente_admin.get("/api/dicionarios").json()["apuracoes"]
    }
    nova = _alegacao(cliente_admin, "A companhia teria perdido uma concessão")
    assert apuracoes[nova["apuracao_id"]] == "em_apuracao"
    assert nova["referencia_id"] is None


def test_apurar_amarra_o_posicionamento_que_responde(cliente_admin):
    apuracoes = {
        a["codigo"]: a["id"]
        for a in cliente_admin.get("/api/dicionarios").json()["apuracoes"]
    }
    nova = _alegacao(cliente_admin, "A tarifa subiria acima do contrato")

    editada = cliente_admin.put(
        f"/api/alegacoes/{nova['id']}",
        json={
            "texto": nova["texto"],
            "temas": nova["temas"],
            "apuracao_id": apuracoes["sem_fundamento"],
            "nota": "O reajuste segue o contrato de concessão.",
        },
    )
    assert editada.status_code == 200, editada.text
    assert editada.json()["apuracao_id"] == apuracoes["sem_fundamento"]
    assert editada.json()["nota"].startswith("O reajuste")


def test_a_alegacao_sai_de_circulacao_sem_ser_apagada(cliente_admin):
    """Apagá-la reescreveria a leitura de um período que já foi lido."""
    nova = _alegacao(cliente_admin, "Haveria atraso no pagamento de debêntures")

    assert cliente_admin.delete(f"/api/alegacoes/{nova['id']}").status_code == 405

    desativada = cliente_admin.put(
        f"/api/alegacoes/{nova['id']}",
        json={"texto": nova["texto"], "temas": [], "ativo": False},
    )
    assert desativada.status_code == 200, desativada.text

    ativas = {a["id"] for a in cliente_admin.get("/api/alegacoes").json()}
    assert nova["id"] not in ativas
    todas = {a["id"] for a in cliente_admin.get("/api/alegacoes?incluir_inativas=1").json()}
    assert nova["id"] in todas


def test_a_contagem_de_consultas_e_a_convergencia(cliente_admin, semente, credor):
    """A leitura que a aba faz: a mesma alegação chegando de instituições
    diferentes. O número que importa não é o de e-mails — é o de quem
    perguntou."""
    dicionarios = cliente_admin.get("/api/dicionarios").json()
    mercado = next(
        c for c in dicionarios["categorias_publico"]
        if c["codigo"] == "mercado_financeiro_capitais"
    )
    outro = cliente_admin.post(
        "/api/instituicoes",
        json={"nome": "Fundo Curioso", "tipo": "investidor",
              "categoria_publico_id": mercado["id"]},
    ).json()

    alegacao = _alegacao(cliente_admin, "A dívida de curto prazo não seria rolada")
    _consulta(cliente_admin, semente, credor["id"], alegacoes=[alegacao["id"]])
    _consulta(cliente_admin, semente, credor["id"], alegacoes=[alegacao["id"]])
    _consulta(cliente_admin, semente, outro["id"], alegacoes=[alegacao["id"]])

    listada = next(
        a for a in cliente_admin.get("/api/alegacoes").json() if a["id"] == alegacao["id"]
    )
    assert listada["consultas"] == 3


def test_o_filtro_por_alegacao_e_aplicado_pelo_servidor(cliente_admin, semente, credor):
    """ADR 0002: clicar numa alegação na aba filtra a página inteira, e quem
    aplica é o servidor — senão a tela, a exportação e as métricas contariam
    coisas diferentes para o mesmo recorte."""
    uma = _alegacao(cliente_admin, "O spread subiria já no próximo trimestre")
    outra = _alegacao(cliente_admin, "Haveria revisão do plano de investimentos")

    com_uma = _consulta(cliente_admin, semente, credor["id"], alegacoes=[uma["id"]])
    com_as_duas = _consulta(
        cliente_admin, semente, credor["id"], alegacoes=[uma["id"], outra["id"]]
    )
    sem_nenhuma = _consulta(cliente_admin, semente, credor["id"])

    def ids(consulta: str) -> set[str]:
        resposta = cliente_admin.get(f"/api/interacoes?{consulta}&tamanho=200")
        assert resposta.status_code == 200, resposta.text
        return {i["id"] for i in resposta.json()["itens"]} & {
            com_uma["id"], com_as_duas["id"], sem_nenhuma["id"]
        }

    assert ids(f"alegacao={uma['id']}") == {com_uma["id"], com_as_duas["id"]}
    assert ids(f"alegacao={outra['id']}") == {com_as_duas["id"]}


def test_tirar_a_alegacao_de_uma_consulta_fica_na_trilha(
    cliente_admin, sessao, semente, credor
):
    """Mudar isto muda a contagem que a tela usa para afirmar que algo está
    circulando — não pode mudar em silêncio."""
    alegacao = _alegacao(cliente_admin, "A agência rebaixaria a nota da companhia")
    criada = _consulta(
        cliente_admin, semente, credor["id"], alegacoes=[alegacao["id"]]
    )

    atualizada = cliente_admin.patch(
        f"/api/interacoes/{criada['id']}", json={"alegacoes": []}
    )
    assert atualizada.status_code == 200, atualizada.text
    assert atualizada.json()["alegacoes"] == []

    trilha = sessao.execute(
        text(
            "select campo, valor_anterior, valor_novo from interacao_auditoria "
            "where interacao_id = :id and campo = 'alegacao' order by id"
        ),
        {"id": criada["id"]},
    ).all()
    assert ("alegacao", None, alegacao["id"]) in trilha, "a entrada não foi auditada"
    assert ("alegacao", alegacao["id"], None) in trilha, "a saída não foi auditada"


# -- a invariante: o bloco pertence ao tipo -----------------------------------


def test_o_bloco_da_consulta_fora_do_tipo_e_recusado(cliente_admin, semente, credor):
    """A tela manda coerente; a API aceita um cliente direto, e é ela que
    garante a invariante."""
    resposta = cliente_admin.post(
        "/api/interacoes",
        json={
            **corpo(semente),
            "instituicao_id": credor["id"],
            "formato_interacao_id": None,
            "consulta": {"remetente": "mesa@banco.com"},
        },
    )
    assert resposta.status_code == 422
    assert "Consulta recebida" in resposta.json()["detalhe"]


def test_alegacao_sem_consulta_e_recusada(cliente_admin, semente, credor):
    """Pendurar uma alegação numa reunião faria a aba contar, como premissa em
    circulação, algo que ninguém perguntou."""
    alegacao = _alegacao(cliente_admin, "O plano de investimentos seria revisto")
    resposta = cliente_admin.post(
        "/api/interacoes",
        json={
            **corpo(semente),
            "instituicao_id": credor["id"],
            "formato_interacao_id": None,
            "alegacoes": [alegacao["id"]],
        },
    )
    assert resposta.status_code == 422
    assert "consulta recebida" in resposta.json()["detalhe"]


def test_alegacao_com_o_tipo_certo_mas_sem_o_bloco_e_recusada(
    cliente_admin, semente, credor
):
    """O BLOCO é o marcador de consulta para quem lê: sem ele, a interação
    ficaria fora da aba levando a premissa consigo — registrada, e nunca
    contada."""
    alegacao = _alegacao(cliente_admin, "O covenant seria renegociado em agosto")
    resposta = cliente_admin.post(
        "/api/interacoes",
        json={
            **corpo(semente),
            "instituicao_id": credor["id"],
            "formato_interacao_id": _tipo_de_consulta(cliente_admin),
            "alegacoes": [alegacao["id"]],
        },
    )
    assert resposta.status_code == 422
    assert "consulta recebida" in resposta.json()["detalhe"]


def test_trocar_o_tipo_sem_limpar_o_bloco_e_recusado(cliente_admin, semente, credor):
    """O `PATCH` altera um campo de cada vez, e a invariante é sobre o ESTADO
    FINAL: sem isto, uma reunião ficaria com prazo de resposta e alegações."""
    criada = _consulta(
        cliente_admin, semente, credor["id"], consulta={"remetente": "mesa@banco.com"}
    )
    formatos = cliente_admin.get("/api/dicionarios").json()["formatos_interacao"]
    reuniao = next(f["id"] for f in formatos if f["codigo"] == "reuniao")

    resposta = cliente_admin.patch(
        f"/api/interacoes/{criada['id']}", json={"formato_interacao_id": reuniao}
    )
    assert resposta.status_code == 422

    # QUE A EDIÇÃO PARCIAL É DESFEITA se prova em
    # `test_sessao_do_pedido::test_erro_de_dominio_desfaz_a_transacao`, e não
    # aqui: esta suíte injeta a sessão por `dependency_overrides`, então o
    # código de saída de `obter_sessao` — o `rollback` — não roda. Afirmá-lo
    # neste arquivo seria testar o harness, e não o servidor.

    # E com o bloco limpo na MESMA edição, passa.
    ok = cliente_admin.patch(
        f"/api/interacoes/{criada['id']}",
        json={"formato_interacao_id": reuniao, "consulta": None, "alegacoes": []},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["consulta"] is None


# -- quem vê o quê na lista de alegações ---------------------------------------
#
# UM CLIENTE POR TESTE, de propósito: `cliente` e `cliente_admin` escrevem no
# mesmo `app.dependency_overrides`, então montar os dois no mesmo teste faria
# ambos rodarem com o último perfil — e o contraste que se quer provar
# desapareceria sem falhar.


def _alegacao_com_nota(sessao, texto: str, nota: str) -> Alegacao:
    """Direto no banco: escrever a nota pela API exige o papel que o teste
    justamente NÃO quer usar."""
    registro = Alegacao(
        id=uuid4(),
        texto=texto,
        texto_normalizado=normalizar(texto),
        apuracao_id=sessao.scalar(select(Apuracao.id).order_by(Apuracao.ordem)),
        nota=nota,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def test_a_nota_de_apuracao_nao_sai_para_quem_so_escreve(cliente, sessao):
    """A premissa que circula é o que a tela precisa mostrar; a investigação
    sobre ela, não."""
    registro = _alegacao_com_nota(
        sessao, "A agência rebaixaria a nota em dezembro", "Apurado: sem base."
    )
    listada = next(
        a for a in cliente.get("/api/alegacoes").json() if a["id"] == str(registro.id)
    )
    assert listada["texto"] == registro.texto
    assert listada["nota"] is None


def test_a_nota_de_apuracao_sai_para_quem_administra(cliente_admin, sessao):
    registro = _alegacao_com_nota(
        sessao, "O rating cairia antes do balanço", "Apurado: sem base."
    )
    listada = next(
        a for a in cliente_admin.get("/api/alegacoes").json() if a["id"] == str(registro.id)
    )
    assert listada["nota"] == "Apurado: sem base."


def test_as_inativas_sao_recusadas_a_quem_so_escreve(cliente):
    """Recusado, e não silenciosamente ignorado: quem pediu precisa saber que
    não recebeu tudo."""
    assert cliente.get("/api/alegacoes?incluir_inativas=1").status_code == 403


def test_as_inativas_saem_para_quem_administra(cliente_admin):
    assert cliente_admin.get("/api/alegacoes?incluir_inativas=1").status_code == 200
