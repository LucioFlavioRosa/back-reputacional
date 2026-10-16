"""A planilha do Score sobe uma vez: conferir guarda, confirmar reusa.

O QUE ESTES TESTES PROTEGEM, e é mais do que a economia de tráfego:

  * que a confirmação continue RELENDO a planilha e reconferindo contra o
    cadastro do instante — guardar o arquivo não pode virar guardar o que a
    conferência concluiu;
  * que o identificador não seja uma chave: ele vale para quem conferiu, e
    para a fonte em que foi conferido;
  * que o ambiente SEM armazenamento continue importando, exatamente como
    antes. A economia é uma economia, nunca um pré-requisito.

Medido em 15/10/2026, no clipping real da Clipei (10,53 MB, 75.369 linhas): sem
isto, a mesma pessoa manda 21 MB para fazer um trabalho que precisa de 10,53.
"""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_score import Mencao, PlanilhaRecebida, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

_TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: As colunas que o cadastro da Clipei espera.
_CABECALHO = [
    "Data",
    "Classificação",
    "Aegea Tier",
    "Veículo",
    "Público-alvo",
    "Subcategoria",
    "Atributo",
    "ID",
    "Arquivo/Link",
    "Título",
    "Estado do Veículo",
    "Empresa",
    "Abrangência",
]


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


def _cliente(sessao, perfil: str = "plataforma_edicao"):
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
    cliente = _cliente(sessao)
    try:
        yield cliente
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def outra_pessoa(sessao):
    """Outra gente de verdade: `criado_por` tem chave estrangeira para `usuario`,
    e um uuid inventado seria recusado pelo banco antes de a regra ser exercida."""
    papel = sessao.scalars(
        select(Papel).where(Papel.codigo == "plataforma_edicao")
    ).first()
    pessoa = Usuario(
        entra_object_id=f"oid-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@aegea.com.br",
        nome="Outra Pessoa da Coordenação",
        papel_id=papel.id,
        acesso_irrestrito=True,
    )
    sessao.add(pessoa)
    sessao.flush()
    return pessoa


@pytest.fixture
def armazenamento(monkeypatch):
    """Um Blob de mentira, em memória, que GUARDA de verdade.

    Os outros testes do projeto trocam `blob.guardar` por um `lambda: None` —
    basta a eles, que só precisam que não exploda. Aqui o byte é o assunto:
    estes testes afirmam que o que a confirmação lê é exatamente o que a
    conferência recebeu, e que o arquivo some quando deve.
    """
    guardados: dict[str, bytes] = {}

    def guardar(caminho, dados, tipo):
        assert caminho not in guardados, "gravou por cima de um caminho existente"
        guardados[caminho] = dados

    def ler(caminho):
        return guardados[caminho]

    def apagar(caminho):
        guardados.pop(caminho, None)

    monkeypatch.setattr(blob, "ligado", lambda: True)
    monkeypatch.setattr(blob, "guardar", guardar)
    monkeypatch.setattr(blob, "ler", ler)
    monkeypatch.setattr(blob, "apagar", apagar)
    return guardados


@pytest.fixture
def sem_armazenamento(monkeypatch):
    """O ambiente que não tem Blob — estado previsto, não defeito."""

    def explode(*_args, **_kwargs):
        raise AssertionError("não devia tocar no armazenamento com o Blob desligado")

    monkeypatch.setattr(blob, "ligado", lambda: False)
    monkeypatch.setattr(blob, "guardar", explode)
    monkeypatch.setattr(blob, "ler", explode)


def _planilha(veiculos: list[str] = ("Jornal de Teste",)) -> bytes:
    from openpyxl import Workbook

    pasta = Workbook()
    pasta.remove(pasta.active)
    aba = pasta.create_sheet("Clipping")
    aba.append(_CABECALHO)
    for indice, veiculo in enumerate(veiculos):
        aba.append(
            [
                "2026-08-10",
                "POSITIVA",
                "Relevante",
                veiculo,
                "Opinião Pública",
                "Tarifa",
                "1. Governança",
                f"id-{indice}",
                "https://exemplo/1",
                "Uma matéria",
                "Santa Catarina",
                "Águas de Teste",
                "Local",
            ]
        )
    arquivo = io.BytesIO()
    pasta.save(arquivo)
    return arquivo.getvalue()


def _conferir(cliente, conteudo: bytes, codigo: str = "clipei", nome: str = "export.xlsx"):
    return cliente.post(
        f"/api/score/fontes/{codigo}/conferencia",
        files={"arquivo": (nome, conteudo, _TIPO_XLSX)},
    )


def _importar_pelo_id(cliente, planilha_id, codigo: str = "clipei", **extra):
    return cliente.post(
        f"/api/score/fontes/{codigo}/planilha",
        data={"planilha_id": str(planilha_id), **extra},
    )


# -- o caminho normal ---------------------------------------------------------


def test_a_conferencia_guarda_a_planilha_e_devolve_o_identificador(
    cliente, sessao, armazenamento
):
    resposta = _conferir(cliente, _planilha())

    assert resposta.status_code == 200
    planilha_id = resposta.json()["planilha_id"]
    assert planilha_id is not None

    guardada = sessao.get(PlanilhaRecebida, planilha_id)
    assert guardada is not None
    assert guardada.nome == "export.xlsx"
    assert guardada.caminho in armazenamento
    assert guardada.tamanho == len(armazenamento[guardada.caminho])


def test_a_confirmacao_aceita_o_identificador_em_vez_do_arquivo(
    cliente, sessao, armazenamento
):
    """O ponto da funcionalidade: os bytes não sobem de novo."""
    planilha_id = _conferir(cliente, _planilha()).json()["planilha_id"]
    antes = sessao.scalar(select(func.count()).select_from(Mencao))

    resposta = _importar_pelo_id(cliente, planilha_id)

    assert resposta.status_code == 201, resposta.text
    assert sessao.scalar(select(func.count()).select_from(Mencao)) > antes


def test_o_byte_e_a_linha_somem_quando_a_importacao_grava(
    cliente, sessao, armazenamento
):
    """Cumprido o papel, a planilha guardada não tem por que ocupar o contêiner."""
    planilha_id = _conferir(cliente, _planilha()).json()["planilha_id"]
    caminho = sessao.get(PlanilhaRecebida, planilha_id).caminho

    _importar_pelo_id(cliente, planilha_id)

    assert sessao.get(PlanilhaRecebida, planilha_id) is None
    assert caminho not in armazenamento


def test_a_confirmacao_le_exatamente_os_bytes_que_a_conferencia_recebeu(
    cliente, sessao, armazenamento
):
    conteudo = _planilha(["Jornal de Teste", "Outro Jornal"])

    _conferir(cliente, conteudo)

    assert list(armazenamento.values()) == [conteudo]


# -- o identificador não é uma chave -----------------------------------------


def test_a_planilha_de_outra_pessoa_nao_pode_ser_confirmada(
    cliente, sessao, armazenamento, outra_pessoa
):
    """Conhecer o uuid não pode bastar: senão outra pessoa da coordenação grava
    no mês de todo mundo um arquivo que ela nunca viu.

    A planilha troca de dono em vez de o cliente trocar de perfil porque o
    perfil mockado é um só por processo — e o que se quer provar é a dona da
    LINHA, não o papel de quem pede.
    """
    planilha_id = _conferir(cliente, _planilha()).json()["planilha_id"]
    recebida = sessao.get(PlanilhaRecebida, planilha_id)
    recebida.criado_por = outra_pessoa.id
    sessao.flush()

    resposta = _importar_pelo_id(cliente, planilha_id)

    assert resposta.status_code == 404


def test_a_planilha_de_outra_fonte_nao_pode_ser_confirmada(
    cliente, sessao, armazenamento
):
    """O mapeamento é por fonte. O arquivo errado não daria erro: daria recusa
    de coluna — ou, pior, leitura torta.

    AS OUTRAS DUAS ASSERÇÕES não são zelo, são o que torna este teste capaz de
    falhar. Uma primeira versão só exigia 404 e passava com o filtro de fonte
    REMOVIDO — o 404 podia vir de "Fonte não encontrada". Então:

      * a fonte irmã precisa EXISTIR, o que elimina essa outra origem de 404;
      * a planilha precisa CONTINUAR guardada. Recusa não consome: se o filtro
        sumisse, a importação teria rodado e descartado a linha. A mensagem não
        serve para isto — o handler da plataforma mascara todo `NaoEncontrado`
        com o mesmo "Registro não encontrado.", e é assim que deve ser.
    """
    irma = sessao.scalar(
        select(ScoreFonte).where(ScoreFonte.codigo == "clipei_investidores")
    )
    assert irma is not None, "sem a fonte irmã, o 404 viria de outro lugar"

    planilha_id = _conferir(cliente, _planilha()).json()["planilha_id"]

    resposta = _importar_pelo_id(cliente, planilha_id, codigo="clipei_investidores")

    assert resposta.status_code == 404
    assert sessao.get(PlanilhaRecebida, planilha_id) is not None


def test_um_identificador_que_nao_existe_e_recusado(cliente, armazenamento):
    resposta = _importar_pelo_id(cliente, uuid4())

    assert resposta.status_code == 404


# -- um jeito por pedido ------------------------------------------------------


def test_o_arquivo_e_o_identificador_juntos_sao_recusados(cliente, armazenamento):
    """Escolher um em silêncio gravaria o que a pessoa não quis, e a resposta
    pareceria certa."""
    planilha_id = _conferir(cliente, _planilha()).json()["planilha_id"]

    resposta = cliente.post(
        "/api/score/fontes/clipei/planilha",
        files={"arquivo": ("export.xlsx", _planilha(), _TIPO_XLSX)},
        data={"planilha_id": str(planilha_id)},
    )

    assert resposta.status_code == 422
    assert "não os dois" in resposta.text


def test_nem_arquivo_nem_identificador_e_recusado(cliente, armazenamento):
    resposta = cliente.post("/api/score/fontes/clipei/planilha", data={})

    assert resposta.status_code == 422


# -- uma por fonte e por pessoa ----------------------------------------------


def test_conferir_de_novo_substitui_a_anterior_byte_inclusive(
    cliente, sessao, armazenamento
):
    """Abandonar conferência é o caso NORMAL — é o que acontece toda vez que
    alguém olha a previsão e decide não subir. Sem substituir, cada abandono
    deixaria dezenas de MB para sempre."""
    primeiro = _conferir(cliente, _planilha()).json()["planilha_id"]
    caminho_antigo = sessao.get(PlanilhaRecebida, primeiro).caminho

    segundo = _conferir(cliente, _planilha(["Jornal Dois"])).json()["planilha_id"]

    assert segundo != primeiro
    assert sessao.get(PlanilhaRecebida, primeiro) is None
    assert caminho_antigo not in armazenamento
    assert (
        sessao.scalar(select(func.count()).select_from(PlanilhaRecebida)) == 1
    ), "sobrou mais de uma planilha pendente para a mesma pessoa e fonte"


# -- sem armazenamento, tudo segue como antes --------------------------------


def test_sem_armazenamento_a_conferencia_nao_guarda_e_nao_quebra(
    cliente, sem_armazenamento
):
    resposta = _conferir(cliente, _planilha())

    assert resposta.status_code == 200
    assert resposta.json()["planilha_id"] is None


def test_sem_armazenamento_a_importacao_pelo_arquivo_continua_funcionando(
    cliente, sessao, sem_armazenamento
):
    """A economia é uma economia, nunca um pré-requisito. O dia em que o Blob
    mal configurado impedir a importação é o dia em que isto virou dependência
    sem ninguém decidir."""
    antes = sessao.scalar(select(func.count()).select_from(Mencao))

    resposta = cliente.post(
        "/api/score/fontes/clipei/planilha",
        files={"arquivo": ("export.xlsx", _planilha(), _TIPO_XLSX)},
    )

    assert resposta.status_code == 201, resposta.text
    assert sessao.scalar(select(func.count()).select_from(Mencao)) > antes


# -- guarda o byte, nunca a conclusão ----------------------------------------


def test_a_planilha_guardada_nao_carrega_nenhuma_conclusao_da_conferencia():
    """DERIVADO DA TABELA, e é esta a guarda que importa mais.

    A importação de subtemas registra por que o arquivo vai de novo: "o servidor
    relê e reconfere contra o banco daquele instante", e guardar as propostas
    exigiria uma tabela de rascunho que aquele desenho dispensa. O argumento
    continua valendo — o que esta tabela dispensa é o UPLOAD.

    Uma coluna nova aqui (`previsao`, `veiculos_novos`, qualquer contagem) seria
    a tabela de rascunho nascendo sem ninguém decidir, e este teste existe para
    que isso não passe calado.
    """
    assert {coluna.name for coluna in PlanilhaRecebida.__table__.columns} == {
        "id",
        "fonte_id",
        "caminho",
        "nome",
        "tamanho",
        "criado_por",
        "criado_em",
    }


def test_a_confirmacao_reconfere_contra_o_cadastro_deste_instante(
    cliente, sessao, armazenamento
):
    """O cadastro pode mudar entre conferir e confirmar — e a confirmação tem
    de ver o cadastro NOVO, não o que a conferência viu.

    Aqui o veículo nasce DEPOIS da conferência. Se a confirmação reaproveitasse
    a conclusão de que ele era novo, criaria um segundo com o mesmo nome.
    """
    conferencia = _conferir(cliente, _planilha(["Jornal Recem Cadastrado"])).json()
    assert any(
        v["nome"] == "Jornal Recem Cadastrado" for v in conferencia["veiculos_novos"]
    ), "a conferência precisa tê-lo visto como novo, senão o teste não prova nada"

    sessao.add(
        Instituicao(
            nome="Jornal Recem Cadastrado",
            nome_normalizado="jornal recem cadastrado",
            tipo="veiculo",
            uf="SC",
        )
    )
    sessao.flush()

    resposta = _importar_pelo_id(
        cliente, conferencia["planilha_id"], veiculos_a_criar='["Jornal Recem Cadastrado"]'
    )

    assert resposta.status_code == 201, resposta.text
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Instituicao)
            .where(Instituicao.nome_normalizado == "jornal recem cadastrado")
        )
        == 1
    ), "criou um segundo veículo com o mesmo nome: reaproveitou a conclusão antiga"


def test_a_fonte_guardada_e_a_fonte_que_conferiu(cliente, sessao, armazenamento):
    planilha_id = _conferir(cliente, _planilha()).json()["planilha_id"]

    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert sessao.get(PlanilhaRecebida, planilha_id).fonte_id == clipei.id
