"""As rotas da importação: baixar o modelo, subir o arquivo, retomar a conferência.

ESCONDER O BOTÃO É CONVENIÊNCIA, NUNCA CONTROLE. A tela só oferece a importação a
quem administra cadastros, e isso não protege nada: um `curl` basta. A guarda é a
dependência do router, e a âncora estrutural deste arquivo é o que garante que
uma rota nova sob este prefixo nasça protegida em vez de depender de alguém
lembrar.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import Clima, FormatoInteracao
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso import importar_agendas, modelo_de_importacao
from app.dominio.texto import normalizar
from main import app
from tests.test_e2e_postgres import URL

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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


def _cliente(sessao, perfil: str) -> TestClient:
    """Um cliente logado com o perfil pedido.

    SOBRESCREVE `obter_configuracao()` VIA `app.dependency_overrides`, e não
    `monkeypatch.setattr`: o `Depends(obter_configuracao)` já foi resolvido, na
    importação do módulo, com uma referência direta à função original — trocar o
    nome no módulo depois não alcança quem já guardou o objeto.
    """
    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(**{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": perfil})
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    return TestClient(app)


@pytest.fixture
def cliente_admin(sessao):
    """`plataforma_edicao` é o ÚNICO perfil com `administra_dicionarios` — ver
    `app/api/dependencias.py`, `exigir_administracao_de_cadastros`."""
    try:
        yield _cliente(sessao, "plataforma_edicao")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_admin(sessao):
    """`crm_edicao` abre o portal do CRM e NÃO administra cadastros: é o
    contrapeso exato da guarda, e não um perfil sem acesso a nada — que passaria
    o teste de 403 pelo motivo errado."""
    try:
        yield _cliente(sessao, "crm_edicao")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    instituicao = Instituicao(
        nome="Valor Econômico",
        nome_normalizado=normalizar("Valor Econômico"),
        tipo="veiculo",
        uf="SP",
    )
    sessao.add(instituicao)
    sessao.flush()
    sessao.add_all(
        [
            Interlocutor(
                nome="Ana Prado",
                nome_normalizado=normalizar("Ana Prado"),
                instituicao_id=instituicao.id,
            ),
            PessoaAegea(nome="Radamés Casseb", nome_normalizado=normalizar("Radamés Casseb")),
        ]
    )
    sessao.flush()
    return {
        "instituicao": instituicao,
        "formato": sessao.scalars(select(FormatoInteracao).limit(1)).first(),
        "clima": sessao.scalars(select(Clima).limit(1)).first(),
    }


def _planilha_de_um_dia(sessao, semente, quantas: int = 3) -> bytes:
    """O modelo de verdade com algumas agendas preenchidas."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for i in range(quantas):
        valores = {
            "Código": f"A{i}",
            "Data": date(2026, 9, 25),
            "Instituição": semente["instituicao"].nome,
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


# =============================================================================
# a guarda
# =============================================================================


def test_quem_nao_administra_cadastros_nao_importa(cliente_sem_admin):
    """A decisão de produto: só a coordenação importa. E esconder o botão é
    conveniência — o servidor recusa por conta própria."""
    resposta = cliente_sem_admin.post(
        "/api/importacoes", files={"arquivo": ("a.xlsx", b"PK\x03\x04", TIPO_XLSX)}
    )

    assert resposta.status_code == 403


def test_quem_nao_administra_cadastros_nao_baixa_o_modelo(cliente_sem_admin):
    """O modelo lista o cadastro inteiro — instituições, interlocutores, pessoas
    da Aegea. Deixá-lo aberto entregaria o diretório a quem não o vê na tela."""
    assert cliente_sem_admin.get("/api/importacoes/modelo").status_code == 403


def test_toda_rota_sob_importacoes_exige_administrar_cadastros():
    """A ÂNCORA ESTRUTURAL, no mesmo molde da do portal: uma rota nova sob este
    prefixo nasce protegida, ou este teste quebra.

    Vale mais que os dois testes de 403 acima: eles provam duas rotas, este
    prova TODAS — inclusive as que a Tarefa 10 e a 11 ainda vão acrescentar.
    """
    from fastapi.routing import APIRoute

    from app.api.dependencias import exigir_administracao_de_cadastros
    from tests.test_portal_no_backend import _rotas_montadas

    desprotegidas = [
        f"{sorted(rota.methods)} {rota.path}"
        for rota in _rotas_montadas(app)
        if isinstance(rota, APIRoute)
        and rota.path.startswith("/api/importacoes")
        and exigir_administracao_de_cadastros not in {d.call for d in rota.dependant.dependencies}
    ]

    assert desprotegidas == []


def test_a_varredura_enxerga_as_rotas_de_importacao():
    """Contrapeso da âncora: uma varredura que não encontra nada passaria sem
    provar nada."""
    from fastapi.routing import APIRoute

    from tests.test_portal_no_backend import _rotas_montadas

    achadas = [
        rota.path
        for rota in _rotas_montadas(app)
        if isinstance(rota, APIRoute) and rota.path.startswith("/api/importacoes")
    ]

    assert len(achadas) >= 3, achadas


# =============================================================================
# o modelo
# =============================================================================


def test_o_modelo_baixa_um_xlsx_que_abre(cliente_admin):
    from openpyxl import load_workbook

    resposta = cliente_admin.get("/api/importacoes/modelo")

    assert resposta.status_code == 200
    assert resposta.content[:4] == b"PK\x03\x04"
    assert "Agendas" in load_workbook(io.BytesIO(resposta.content)).sheetnames


def test_o_modelo_vem_como_anexo_com_nome(cliente_admin):
    resposta = cliente_admin.get("/api/importacoes/modelo")

    assert "attachment" in resposta.headers["content-disposition"]
    assert "modelo-de-agendas.xlsx" in resposta.headers["content-disposition"]


# =============================================================================
# subir
# =============================================================================


def test_subir_grava_a_importacao_e_devolve_as_propostas(cliente_admin, sessao, semente):
    resposta = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente), TIPO_XLSX)},
    )

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["situacao"] == "aguardando_conferencia"
    assert len(corpo["linhas"]) == 3


def test_subir_guarda_de_que_linha_do_arquivo_cada_uma_veio(cliente_admin, sessao, semente):
    """`linha_origem` é o que deixa a pessoa voltar à planilha e conferir."""
    corpo = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente), TIPO_XLSX)},
    ).json()

    assert [linha["linha_origem"] for linha in corpo["linhas"]] == [2, 3, 4]


def test_subir_preserva_os_dados_brutos(cliente_admin, sessao, semente):
    """O bruto fica mesmo depois de aceito: é o que permite reprocessar quando a
    regra de leitura mudar, e responder de onde veio o registro."""
    corpo = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente), TIPO_XLSX)},
    ).json()

    assert corpo["linhas"][0]["dados_brutos"]["Instituição"] == semente["instituicao"].nome


def test_subir_grava_o_nome_do_arquivo(cliente_admin, sessao, semente):
    corpo = cliente_admin.post(
        "/api/importacoes",
        files={
            "arquivo": (
                "agendas de quinta.xlsx",
                _planilha_de_um_dia(sessao, semente),
                TIPO_XLSX,
            )
        },
    ).json()

    assert corpo["arquivo_nome"] == "agendas de quinta.xlsx"


def test_subir_um_arquivo_que_nao_e_planilha_devolve_422_e_nao_500(cliente_admin):
    """`RegraViolada` é traduzida centralmente. Sem isso a pessoa leria "erro
    interno" para um arquivo que ela mesma pode trocar."""
    resposta = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("a.xlsx", b"isto nao e planilha", TIPO_XLSX)}
    )

    assert resposta.status_code == 422
    assert "xlsx" in resposta.text


def test_subir_uma_planilha_sem_as_abas_devolve_422(cliente_admin):
    from openpyxl import Workbook

    livro = Workbook()
    saida = io.BytesIO()
    livro.save(saida)

    resposta = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("a.xlsx", saida.getvalue(), TIPO_XLSX)}
    )

    assert resposta.status_code == 422


# =============================================================================
# retomar
# =============================================================================


def test_a_importacao_sobrevive_a_fechar_o_navegador(cliente_admin, sessao, semente):
    """É para isto que a 0008 criou tabela em vez de resolver em memória."""
    criada = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente), TIPO_XLSX)},
    ).json()

    retomada = cliente_admin.get(f"/api/importacoes/{criada['id']}")

    assert retomada.status_code == 200
    assert retomada.json()["linhas"] == criada["linhas"]


def test_uma_importacao_que_nao_existe_devolve_404(cliente_admin):
    resposta = cliente_admin.get("/api/importacoes/00000000-0000-0000-0000-000000000000")

    assert resposta.status_code == 404
