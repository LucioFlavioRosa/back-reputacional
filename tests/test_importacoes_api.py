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
    interlocutor = Interlocutor(
        nome="Ana Prado",
        nome_normalizado=normalizar("Ana Prado"),
        instituicao_id=instituicao.id,
    )
    sessao.add_all(
        [
            interlocutor,
            PessoaAegea(nome="Radamés Casseb", nome_normalizado=normalizar("Radamés Casseb")),
        ]
    )
    sessao.flush()
    return {
        "instituicao": instituicao,
        "interlocutor": interlocutor,
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
            # DATAS DIFERENTES de propósito: com a mesma instituição e a mesma
            # data, as linhas 2, 3 e 4 seriam duplicatas uma da outra, e todo
            # teste que usa este helper passaria a carregar um aviso que não tem
            # nada a ver com o que ele quer provar.
            "Data": date(2026, 9, 21 + i),
            "Instituição": semente["instituicao"].nome,
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


def _agenda_ja_no_sistema(cliente, sessao, semente, quando, arquivada: bool = False):
    """Uma agenda que JÁ existe, para a detecção de duplicata ter o que achar.

    Monta com os ids que o banco de teste tem, e não com códigos escritos aqui:
    `interacao` exige `frente_id`, `status_id` e `criado_por`, e inventar
    qualquer um deles daria erro de chave estrangeira em vez de testar o aviso.

    O `cliente` NÃO É DECORAÇÃO: o banco de teste é recriado a cada execução com
    só o que as migrations inserem, e `usuario` nasce VAZIA. O usuário do
    `auth_mock` só passa a existir na primeira requisição autenticada — então
    esta chamada barata é o que dá a `criado_por` alguém a quem apontar.
    """
    from app.banco.tabelas_acesso import Usuario
    from app.banco.tabelas_catalogo import Frente, Status
    from app.banco.tabelas_interacoes import InteracaoRegistro

    cliente.get("/api/importacoes/modelo")

    registro = InteracaoRegistro(
        data_interacao=quando,
        instituicao_id=semente["instituicao"].id,
        uf="SP",
        frente_id=sessao.scalars(select(Frente).limit(1)).first().id,
        status_id=sessao.scalars(select(Status).limit(1)).first().id,
        criado_por=sessao.scalars(select(Usuario).limit(1)).first().id,
        arquivado_em=quando if arquivada else None,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


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


# =============================================================================
# a duplicata possível
# =============================================================================


def test_agenda_que_ja_existe_no_banco_AVISA_e_nao_trava(cliente_admin, sessao, semente):
    """Duas reuniões com o mesmo órgão no mesmo dia acontecem. Travar por isso
    ensinaria a pessoa a ignorar o aviso — e é o aviso que a protege do caso que
    importa: ela subiu o mesmo arquivo duas vezes."""
    from datetime import date

    _agenda_ja_no_sistema(cliente_admin, sessao, semente, date(2026, 9, 21))

    corpo = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente, quantas=1), TIPO_XLSX)},
    ).json()

    duplicatas = [grupo for grupo in corpo["grupos"] if grupo["campo"] == "duplicata"]
    assert duplicatas, corpo["grupos"]
    assert duplicatas[0]["trava"] is False
    assert corpo["pendencias"] == 0


def test_a_mesma_agenda_repetida_DENTRO_do_arquivo_tambem_avisa(cliente_admin, sessao, semente):
    """Colar a mesma agenda duas vezes na planilha é o mesmo erro visto de outro
    ângulo, e quem confere precisa vê-lo antes de criar as duas."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for codigo in ("A1", "A2"):
        valores = {
            "Código": codigo,
            "Data": date(2026, 9, 25),
            "Instituição": semente["instituicao"].nome,
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    duplicatas = [grupo for grupo in corpo["grupos"] if grupo["campo"] == "duplicata"]
    assert duplicatas, corpo["grupos"]
    # A PRIMEIRA não é duplicata de nada; a segunda é.
    assert duplicatas[0]["linhas"] == [3]


def test_a_agenda_arquivada_nao_conta_como_duplicata(cliente_admin, sessao, semente):
    """Uma agenda arquivada não é a mesma reunião acontecendo de novo, e avisar
    sobre ela ensinaria a ignorar o aviso."""
    from datetime import date

    _agenda_ja_no_sistema(cliente_admin, sessao, semente, date(2026, 9, 21), arquivada=True)

    corpo = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente, quantas=1), TIPO_XLSX)},
    ).json()

    assert [grupo for grupo in corpo["grupos"] if grupo["campo"] == "duplicata"] == []


# =============================================================================
# os grupos na resposta
# =============================================================================


def test_a_mesma_instituicao_desconhecida_vira_UM_grupo_com_as_linhas(
    cliente_admin, sessao, semente
):
    """A vista principal da conferência: uma decisão, várias linhas."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for i in range(4):
        valores = {
            "Código": f"A{i}",
            "Data": date(2026, 9, 25),
            "Instituição": "Prefeitura de Campinas",
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    (grupo,) = [g for g in corpo["grupos"] if g["campo"] == "instituicao_id"]
    assert grupo["valor"] == "Prefeitura de Campinas"
    assert grupo["linhas"] == [2, 3, 4, 5]
    assert grupo["trava"] is True
    # QUATRO pendências e UMA decisão. Este teste dizia `pendencias == 1`, e com
    # isso codificava o defeito que a revisão do Codex achou: o campo promete
    # "quantas linhas seguram a confirmação" e contava grupos, fazendo o cabeçalho
    # mentir sobre o tamanho do trabalho.
    assert corpo["pendencias"] == 4
    assert corpo["decisoes_pendentes"] == 1


def test_o_grupo_oferece_o_nome_parecido_que_JA_existe(cliente_admin, sessao, semente):
    """É o que transforma "não existe" em um clique: a pessoa reconhece
    "Prefeitura Municipal de Campinas" e aponta para ela."""
    from datetime import date

    from openpyxl import load_workbook

    from app.banco.tabelas_stakeholders import Instituicao as Inst

    sessao.add(
        Inst(
            nome="Prefeitura Municipal de Campinas",
            nome_normalizado=normalizar("Prefeitura Municipal de Campinas"),
            tipo="orgao",
            uf="SP",
        )
    )
    sessao.flush()

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": "Prefeitura de Campinas",
        "UF": "SP",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    (grupo,) = [g for g in corpo["grupos"] if g["campo"] == "instituicao_id"]
    assert "Prefeitura Municipal de Campinas" in grupo["sugestoes"]


def test_o_que_trava_vem_ANTES_do_que_so_avisa(cliente_admin, sessao, semente):
    """A tela lista em ordem de urgência: o que segura a confirmação primeiro."""
    from datetime import date

    from openpyxl import load_workbook

    _agenda_ja_no_sistema(cliente_admin, sessao, semente, date(2026, 9, 25))

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    # A primeira resolve inteira e é duplicata (avisa); a segunda tem
    # instituição desconhecida (trava).
    for codigo, instituicao in (
        ("A1", semente["instituicao"].nome),
        ("A2", "Prefeitura de Campinas"),
    ):
        valores = {
            "Código": codigo,
            "Data": date(2026, 9, 25),
            "Instituição": instituicao,
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    assert [g["trava"] for g in corpo["grupos"]] == sorted(
        [g["trava"] for g in corpo["grupos"]], reverse=True
    )
    assert corpo["grupos"][0]["trava"] is True


def test_a_linha_limpa_nao_gera_grupo_nenhum(cliente_admin, sessao, semente):
    corpo = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente), TIPO_XLSX)},
    ).json()

    assert corpo["grupos"] == []
    assert corpo["pendencias"] == 0


# =============================================================================
# os defeitos que a revisão do Codex achou
# =============================================================================

def test_o_bruto_das_abas_filhas_TAMBEM_e_gravado(cliente_admin, sessao, semente):
    """O DEFEITO 3: só as linhas de Agendas viravam `importacao_linha`, e o bruto
    das abas filhas não ficava em lugar nenhum — contra a invariante da 0008 de
    preservar o arquivo para poder reprocessar e responder de onde veio o dado."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    agendas = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(agendas.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": semente["instituicao"].nome,
        "UF": "SP",
    }
    agendas.append([valores.get(coluna) for coluna in cabecalho])

    participantes = pasta["Participantes"]
    cabecalho_p = [celula.value for celula in next(participantes.iter_rows())]
    linha_p = {"Código": "A1", "Pessoa": semente["interlocutor"].nome, "Presença": "presente"}
    participantes.append([linha_p.get(coluna) for coluna in cabecalho_p])

    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    das_filhas = [linha for linha in corpo["linhas"] if linha["aba"] == "Participantes"]
    assert das_filhas, [linha["aba"] for linha in corpo["linhas"]]
    assert das_filhas[0]["dados_brutos"]["Pessoa"] == semente["interlocutor"].nome

def test_pendencias_conta_LINHAS_e_nao_grupos(cliente_admin, sessao, semente):
    """O DEFEITO 5: o campo diz "quantas linhas seguram a confirmação" e contava
    grupos. Quatro linhas travadas por um grupo devolviam 1, e o cabeçalho da
    tela mentia sobre o tamanho do trabalho."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for i in range(4):
        valores = {
            "Código": f"A{i}",
            "Data": date(2026, 9, 21 + i),
            "Instituição": "Prefeitura de Campinas",
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    assert corpo["pendencias"] == 4
    assert corpo["decisoes_pendentes"] == 1

def test_celula_de_HORA_nao_estoura_no_commit(cliente_admin, sessao, semente):
    """O DEFEITO 6: `para_json` cobria date, datetime e UUID, e uma célula
    formatada como hora chega `time` — estourando no flush do JSONB, longe de
    quem montou o dado. É a classe de erro que a função existe para evitar."""
    from datetime import date, time

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": semente["instituicao"].nome,
        "UF": "SP",
        "Local": time(14, 30),
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    resposta = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["linhas"][0]["dados_brutos"]["Local"] == "14:30:00"


# =============================================================================
# resolver um grupo resolve todas as linhas dele
# =============================================================================


@pytest.fixture
def importacao_com_quatro(cliente_admin, sessao, semente):
    """Quatro agendas presas pela MESMA instituição desconhecida.

    É a forma do problema real: um dia inteiro com o mesmo órgão que ninguém
    cadastrou ainda. Uma decisão tem de destravar as quatro.
    """
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for i in range(4):
        valores = {
            "Código": f"A{i}",
            "Data": date(2026, 9, 21 + i),
            "Instituição": "Prefeitura de Campinas",
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    resposta = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_apontar_para_uma_existente_resolve_as_quatro_linhas(
    cliente_admin, sessao, semente, importacao_com_quatro
):
    """UMA DECISÃO, QUATRO LINHAS — é o que faz a conferência escalar."""
    parecida = Instituicao(
        nome="Prefeitura Municipal de Campinas",
        nome_normalizado=normalizar("Prefeitura Municipal de Campinas"),
        tipo="orgao",
        uf="SP",
    )
    sessao.add(parecida)
    sessao.flush()

    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
            "alvo": str(parecida.id),
        },
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["pendencias"] == 0
    assert corpo["decisoes_pendentes"] == 0


def test_apontar_registra_para_qual_cadastro(cliente_admin, sessao, semente, importacao_com_quatro):
    """Sem guardar o alvo, a confirmação não saberia para onde apontar — e a
    decisão da pessoa teria sido só um número que baixou na tela."""
    parecida = Instituicao(
        nome="Prefeitura Municipal de Campinas",
        nome_normalizado=normalizar("Prefeitura Municipal de Campinas"),
        tipo="orgao",
        uf="SP",
    )
    sessao.add(parecida)
    sessao.flush()

    cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
            "alvo": str(parecida.id),
        },
    )

    estado = cliente_admin.get(f"/api/importacoes/{importacao_com_quatro['id']}").json()
    resolvidas = [
        divergencia
        for linha in estado["linhas"]
        for divergencia in linha["divergencias"]
        if divergencia.get("acao") == "apontar"
    ]
    assert len(resolvidas) == 4
    assert all(d["alvo"] == str(parecida.id) for d in resolvidas)


def test_criar_transforma_o_que_travava_em_cadastro_a_criar(
    cliente_admin, importacao_com_quatro
):
    """A pessoa confirma que é cadastro novo mesmo — digitou na célula sem
    declarar na aba, e agora decide na tela. Deixa de travar."""
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "criar",
        },
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["pendencias"] == 0


def test_descartar_tira_as_linhas_sem_apagar_o_bruto(cliente_admin, importacao_com_quatro):
    """`dados_brutos` fica: é o que permite reprocessar quando a regra de leitura
    mudar, e responder de onde veio o registro."""
    cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "descartar",
        },
    )

    estado = cliente_admin.get(f"/api/importacoes/{importacao_com_quatro['id']}").json()
    descartadas = [linha for linha in estado["linhas"] if linha["decisao"] == "descartada"]
    assert len(descartadas) == 4
    assert all(linha["dados_brutos"] for linha in descartadas)


def test_a_linha_descartada_nao_conta_mais_como_pendencia(cliente_admin, importacao_com_quatro):
    """Descartar é uma resolução: a linha sai do caminho da confirmação."""
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "descartar",
        },
    )

    assert resposta.json()["pendencias"] == 0


def test_resolver_um_valor_que_nao_esta_pendente_recusa(cliente_admin, importacao_com_quatro):
    """Recusar em vez de não fazer nada: um 200 silencioso faria a tela mostrar
    "resolvido" para uma decisão que não alcançou linha nenhuma."""
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={"campo": "instituicao_id", "valor": "Não existe", "decisao": "criar"},
    )

    assert resposta.status_code == 422


def test_apontar_sem_alvo_recusa(cliente_admin, importacao_com_quatro):
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
        },
    )

    assert resposta.status_code == 422


def test_apontar_para_um_cadastro_que_nao_existe_recusa(cliente_admin, importacao_com_quatro):
    """Sem esta guarda, a decisão gravaria um id que a confirmação não encontra —
    e o erro apareceria lá, longe de quem escolheu."""
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
            "alvo": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert resposta.status_code == 422


def test_decisao_desconhecida_recusa(cliente_admin, importacao_com_quatro):
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "inventada",
        },
    )

    assert resposta.status_code == 422


def test_resolver_nao_mexe_em_linha_de_outro_valor(cliente_admin, sessao, semente):
    """Duas divergências diferentes, uma decisão: só as linhas daquele valor."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for codigo, instituicao in (("A1", "Prefeitura de Campinas"), ("A2", "Prefeitura de Campos")):
        valores = {
            "Código": codigo,
            "Data": date(2026, 9, 25),
            "Instituição": instituicao,
            "UF": "SP",
        }
        folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()
    assert criada["pendencias"] == 2

    resposta = cliente_admin.patch(
        f"/api/importacoes/{criada['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "descartar",
        },
    )

    assert resposta.json()["pendencias"] == 1


def test_resolver_uma_importacao_que_nao_existe_devolve_404(cliente_admin):
    resposta = cliente_admin.patch(
        "/api/importacoes/00000000-0000-0000-0000-000000000000/resolucoes",
        json={"campo": "instituicao_id", "valor": "X", "decisao": "criar"},
    )

    assert resposta.status_code == 404


# =============================================================================
# a confirmação: uma transação só, reconferida contra o banco
# =============================================================================


def _quantas(sessao, tabela) -> int:
    from sqlalchemy import func
    from sqlalchemy import select as sel

    return sessao.scalar(sel(func.count()).select_from(tabela))


@pytest.fixture
def limpa(cliente_admin, sessao, semente):
    """Três agendas que resolvem inteiras — nada a decidir."""
    corpo = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(sessao, semente), TIPO_XLSX)},
    ).json()
    assert corpo["pendencias"] == 0, corpo["grupos"]
    return corpo


@pytest.fixture
def com_cadastro_novo(cliente_admin, sessao, semente):
    """Uma agenda cuja instituição foi DECLARADA na aba editável — a criar."""
    from datetime import date

    from openpyxl import load_workbook

    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": "Prefeitura de Campinas",
        "UF": "SP",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    pasta[ROTULO_DO_VOCABULARIO["instituicoes"]].append(["Prefeitura de Campinas"])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()
    assert corpo["pendencias"] == 0, corpo["grupos"]
    return corpo


def test_confirmar_cria_as_agendas(cliente_admin, sessao, limpa):
    from app.banco.tabelas_interacoes import InteracaoRegistro

    antes = _quantas(sessao, InteracaoRegistro)

    resposta = cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")

    assert resposta.status_code == 201, resposta.text
    assert _quantas(sessao, InteracaoRegistro) == antes + 3
    assert resposta.json()["criadas"] == 3


def test_confirmar_cria_o_cadastro_declarado_junto(cliente_admin, sessao, com_cadastro_novo):
    """Os cadastros novos e as agendas nascem no MESMO commit."""
    from app.banco.tabelas_interacoes import InteracaoRegistro

    antes_inst = _quantas(sessao, Instituicao)
    antes_ag = _quantas(sessao, InteracaoRegistro)

    resposta = cliente_admin.post(f"/api/importacoes/{com_cadastro_novo['id']}/confirmacao")

    assert resposta.status_code == 201, resposta.text
    assert _quantas(sessao, Instituicao) == antes_inst + 1
    assert _quantas(sessao, InteracaoRegistro) == antes_ag + 1
    assert resposta.json()["cadastros"] == 1


def test_a_agenda_criada_guarda_de_onde_veio(cliente_admin, sessao, limpa):
    """A procedência é o que permite responder "de onde veio este registro" e
    reprocessar quando a regra de leitura mudar."""
    from sqlalchemy import select as sel

    from app.banco.tabelas_interacoes import InteracaoRegistro

    cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")

    criadas = sessao.scalars(
        sel(InteracaoRegistro).where(InteracaoRegistro.fonte == "importacao_planilha")
    ).all()
    assert len(criadas) == 3
    assert {linha.origem_aba for linha in criadas} == {"Agendas"}
    assert sorted(linha.origem_linha for linha in criadas) == [2, 3, 4]


def test_confirmar_liga_cada_linha_a_sua_agenda(cliente_admin, limpa):
    """`interacao_id` é o que fecha o laço entre a planilha e o registro."""
    cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")

    estado = cliente_admin.get(f"/api/importacoes/{limpa['id']}").json()
    das_agendas = [linha for linha in estado["linhas"] if linha["aba"] == "Agendas"]
    assert all(linha["interacao_id"] for linha in das_agendas)


def test_confirmar_marca_a_importacao_como_confirmada(cliente_admin, limpa):
    cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")

    estado = cliente_admin.get(f"/api/importacoes/{limpa['id']}").json()
    assert estado["situacao"] == "confirmada"
    assert estado["confirmado_em"]


def test_o_cadastro_que_NASCEU_entre_subir_e_confirmar_para_a_confirmacao(
    cliente_admin, sessao, com_cadastro_novo
):
    """O PONTO MAIS DELICADO DA FUNCIONALIDADE.

    Entre subir e confirmar, alguém cadastrou a mesma instituição pela tela de
    Administração. Confirmar cego criaria a duplicata que a conferência existia
    para evitar — e duplicata de instituição é o defeito mais caro aqui, porque
    espalha por toda leitura que agrupa por órgão.
    """
    sessao.add(
        Instituicao(
            nome="Prefeitura de Campinas",
            nome_normalizado=normalizar("Prefeitura de Campinas"),
            tipo="orgao",
            uf="SP",
        )
    )
    sessao.flush()

    resposta = cliente_admin.post(f"/api/importacoes/{com_cadastro_novo['id']}/confirmacao")

    assert resposta.status_code == 409, resposta.text
    assert "Prefeitura de Campinas" in resposta.text


def test_confirmar_com_pendencia_que_trava_recusa(cliente_admin, sessao, semente):
    """O botão fica apagado na tela, e o servidor recusa por conta própria."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": "Orgao Que Ninguem Cadastrou",
        "UF": "SP",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()
    assert criada["pendencias"] == 1

    resposta = cliente_admin.post(f"/api/importacoes/{criada['id']}/confirmacao")

    assert resposta.status_code == 422


def test_confirmar_duas_vezes_recusa(cliente_admin, limpa):
    """Sem esta guarda, dois cliques no botão criariam as agendas duas vezes."""
    primeira = cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")
    assert primeira.status_code == 201

    segunda = cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")

    assert segunda.status_code == 422


def test_a_linha_descartada_nao_vira_agenda(cliente_admin, sessao, importacao_com_quatro):
    """Descartar é decisão, e ela tem de valer na confirmação."""
    from app.banco.tabelas_interacoes import InteracaoRegistro

    cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "descartar",
        },
    )
    antes = _quantas(sessao, InteracaoRegistro)

    resposta = cliente_admin.post(f"/api/importacoes/{importacao_com_quatro['id']}/confirmacao")

    assert resposta.status_code == 201, resposta.text
    assert _quantas(sessao, InteracaoRegistro) == antes
    assert resposta.json()["criadas"] == 0


def test_apontar_e_confirmar_usa_o_cadastro_escolhido(
    cliente_admin, sessao, semente, importacao_com_quatro
):
    """O caminho completo da conferência: a pessoa aponta e a agenda nasce no
    cadastro que ela escolheu, não num criado às pressas."""
    from sqlalchemy import select as sel

    from app.banco.tabelas_interacoes import InteracaoRegistro

    escolhida = Instituicao(
        nome="Prefeitura Municipal de Campinas",
        nome_normalizado=normalizar("Prefeitura Municipal de Campinas"),
        tipo="orgao",
        uf="SP",
    )
    sessao.add(escolhida)
    sessao.flush()

    cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
            "alvo": str(escolhida.id),
        },
    )

    resposta = cliente_admin.post(f"/api/importacoes/{importacao_com_quatro['id']}/confirmacao")

    assert resposta.status_code == 201, resposta.text
    criadas = sessao.scalars(
        sel(InteracaoRegistro).where(InteracaoRegistro.instituicao_id == escolhida.id)
    ).all()
    assert len(criadas) == 4


def test_cancelar_nao_deixa_cadastro_orfao(cliente_admin, sessao, com_cadastro_novo):
    """Se os cadastros nascessem no upload, cancelar deixaria instituições
    criadas sem nenhuma agenda a que servissem. É por isso que nada nasce lá."""
    antes = _quantas(sessao, Instituicao)

    resposta = cliente_admin.post(f"/api/importacoes/{com_cadastro_novo['id']}/cancelamento")

    assert resposta.status_code == 200, resposta.text
    assert _quantas(sessao, Instituicao) == antes
    assert resposta.json()["situacao"] == "cancelada"


def test_cancelar_preserva_o_bruto(cliente_admin, com_cadastro_novo):
    """Cancelar não apaga o que a pessoa preencheu: ela pode querer entender o
    que deu errado, e o bruto é a única cópia daquilo no sistema."""
    cliente_admin.post(f"/api/importacoes/{com_cadastro_novo['id']}/cancelamento")

    estado = cliente_admin.get(f"/api/importacoes/{com_cadastro_novo['id']}").json()
    assert all(linha["dados_brutos"] for linha in estado["linhas"])


def test_confirmar_uma_cancelada_recusa(cliente_admin, limpa):
    cliente_admin.post(f"/api/importacoes/{limpa['id']}/cancelamento")

    resposta = cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")

    assert resposta.status_code == 422


def test_confirmar_uma_importacao_que_nao_existe_devolve_404(cliente_admin):
    resposta = cliente_admin.post(
        "/api/importacoes/00000000-0000-0000-0000-000000000000/confirmacao"
    )

    assert resposta.status_code == 404


# =============================================================================
# os defeitos que a revisão do Codex achou na Tarefa 10
# =============================================================================


def test_a_divergencia_resolvida_SAI_das_pendencias_e_vira_a_criar(
    cliente_admin, importacao_com_quatro
):
    """DEFEITO 1. A divergência resolvida ficava na lista com `trava=False`, e o
    agrupamento a devolvia como se fosse aviso comum — escondendo a decisão que a
    pessoa tomou e fazendo a tela parecer ter uma pendência branda que não existe.
    Resolvido é resolvido: sai dos grupos e entra no bloco "o que vou criar"."""
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "criar",
        },
    )

    corpo = resposta.json()
    assert corpo["grupos"] == [], corpo["grupos"]
    assert ["Prefeitura de Campinas"] == [item["valor"] for item in corpo["a_criar"]]


def test_reaplicar_a_mesma_decisao_recusa(cliente_admin, importacao_com_quatro):
    """DEFEITO 1, a outra metade. `linhas_com` continuava encontrando a
    divergência já resolvida, então a guarda de "zero linhas alcançadas" não
    protegia contra sobrescrever uma decisão tomada — um segundo clique podia
    trocar "apontar para X" por "criar" sem ninguém perceber."""
    primeira = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "criar",
        },
    )
    assert primeira.status_code == 200

    segunda = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "criar",
        },
    )

    assert segunda.status_code == 422


def test_o_declarado_na_aba_ja_aparece_como_a_criar(cliente_admin, sessao, semente):
    """A declaração na aba editável e a decisão "criar" na tela passam a ter a
    MESMA forma, e as duas aparecem no mesmo bloco — que é o que a spec descreve."""
    from datetime import date

    from openpyxl import load_workbook

    from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": "Prefeitura de Campinas",
        "UF": "SP",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    pasta[ROTULO_DO_VOCABULARIO["instituicoes"]].append(["Prefeitura de Campinas"])
    saida = io.BytesIO()
    pasta.save(saida)

    corpo = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    assert corpo["grupos"] == []
    assert [item["valor"] for item in corpo["a_criar"]] == ["Prefeitura de Campinas"]


def test_apontar_para_um_vocabulario_DE_CODIGO_funciona(cliente_admin, sessao, semente):
    """DEFEITO 2. `_cadastro_existe` só olhava `NO_BANCO`, então uma Modalidade
    escrita errada não podia ser resolvida apontando para um código válido — a
    pessoa ficava sem saída numa pendência que travava."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": semente["instituicao"].nome,
        "UF": "SP",
        "Modalidade": "pessoalmente",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()
    assert criada["pendencias"] == 1

    resposta = cliente_admin.patch(
        f"/api/importacoes/{criada['id']}/resolucoes",
        json={
            "campo": "modalidade",
            "valor": "pessoalmente",
            "decisao": "apontar",
            "alvo": "presencial",
        },
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["pendencias"] == 0


def test_criar_num_vocabulario_FECHADO_recusa(cliente_admin, sessao, semente):
    """DEFEITO 2, a metade pior. `criar` não era validado contra vocabulário
    fechado, então a resolução contornava a regra que `classificar` enforça no
    upload: mudar a lista de modalidades é mudança de regra, não de cadastro."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": semente["instituicao"].nome,
        "UF": "SP",
        "Modalidade": "pessoalmente",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    resposta = cliente_admin.patch(
        f"/api/importacoes/{criada['id']}/resolucoes",
        json={"campo": "modalidade", "valor": "pessoalmente", "decisao": "criar"},
    )

    assert resposta.status_code == 422
    assert "fechad" in resposta.text.lower()


def test_alvo_malformado_recusa_com_422_e_nao_estoura(cliente_admin, importacao_com_quatro):
    """DEFEITO 3. `alvo` chega como texto e ia direto comparar com uma coluna
    UUID. "abc" viraria erro de banco — 500 e "erro interno" para quem só digitou
    algo inesperado num campo da API."""
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_quatro['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
            "alvo": "abc",
        },
    )

    assert resposta.status_code == 422, resposta.text


def test_alvo_nao_numerico_num_campo_de_id_inteiro_recusa(cliente_admin, sessao, semente):
    """O mesmo, do lado dos dicionários com id inteiro."""
    from datetime import date

    from openpyxl import load_workbook

    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    valores = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": semente["instituicao"].nome,
        "UF": "SP",
        "Unidade de negócio": "Unidade Que Nao Existe",
    }
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()

    resposta = cliente_admin.patch(
        f"/api/importacoes/{criada['id']}/resolucoes",
        json={
            "campo": "unidade_negocio_id",
            "valor": "Unidade Que Nao Existe",
            "decisao": "apontar",
            "alvo": "nao-e-numero",
        },
    )

    assert resposta.status_code == 422, resposta.text


def test_a_confirmacao_nao_faz_commit_por_conta_propria(cliente_admin, sessao, limpa):
    """OU TUDO ENTRA, OU NADA ENTRA — e é o que garante isso.

    A atomicidade não vem de um `try/except` dentro do caso de uso: vem de a
    transação ser a da requisição, comitada no teardown da dependência (ver
    `app/banco/sessao.py`). Um `sessao.commit()` no meio de `confirmar` criaria
    exatamente o estado que ela existe para impedir — instituições criadas e
    agendas não —, e nenhum teste de caminho feliz notaria.

    Este teste vigia a ausência de um commit. É a única forma de prender a
    invariante sem simular a falha, porque dentro da transação do próprio teste
    um rollback parcial não se distingue de um total.
    """
    chamadas = []
    original = sessao.commit
    sessao.commit = lambda *a, **k: chamadas.append(1) or original(*a, **k)
    try:
        resposta = cliente_admin.post(f"/api/importacoes/{limpa['id']}/confirmacao")
    finally:
        sessao.commit = original

    assert resposta.status_code == 201, resposta.text
    assert chamadas == [], "confirmar comitou por conta própria"
