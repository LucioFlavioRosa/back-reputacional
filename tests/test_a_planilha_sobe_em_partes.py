"""A planilha grande sobe em pedaços, porque uma requisição não a aguenta.

POR QUE ESTE CAMINHO EXISTE, com os números medidos em 16/10/2026 no ambiente
implantado — a telemetria do navegador, do mesmo arquivo e da mesma máquina:

     1,42 MB  ->    4,1 s  -> 200
     1,33 MB  ->   73,2 s  -> 200
    10,53 MB  ->  212,4 s  -> 403
    10,53 MB  ->  212,6 s  -> 403
    10,53 MB  ->  227,4 s  -> 403

Os três 403 param em 212 a 227 s porque o ingress do Container Apps encerra a
requisição por volta de 240 s, e isso NÃO é configurável. A banda de subida
variou de ~18 KB/s a ~350 KB/s na mesma hora; a 18 KB/s, 10,53 MB precisam de
390 s e nunca cabem.

O QUE SE AFIRMA AQUI é o contrato da montagem, não o tempo: que o arquivo
montado é idêntico ao que subiria de uma vez, que parte faltando recusa com
nome, que as recusas de cadastro chegam ANTES das onze requisições, e que uma
montagem recusada não deixa byte pago no contêiner.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.sessao import obter_sessao
from app.banco.tabelas_score import Mencao, PlanilhaRecebida
from app.casos_de_uso import ingerir_mencoes, planilha_do_score
from main import app
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

_TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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


@pytest.fixture
def armazenamento(monkeypatch):
    """Um Blob de mentira que MODELA BLOCO NÃO COMMITADO.

    É o ponto do caminho em partes, e um dicionário simples não o representaria:
    as partes ficam numa área separada e o caminho final NÃO EXISTE até a
    montagem. Um `ler` antes de `juntar_partes` tem de falhar — se ele
    funcionasse, o teste da montagem passaria sem a montagem.

    GUARDA POR ÍNDICE, e não por ordem de chegada: é o que permite afirmar que
    parte reenviada substitui e que ordem trocada monta igual.
    """
    publicados: dict[str, bytes] = {}
    estagiados: dict[str, dict[int, bytes]] = {}

    def guardar(caminho, dados, tipo):
        assert caminho not in publicados, "gravou por cima de um caminho existente"
        publicados[caminho] = dados

    def ler(caminho):
        return publicados[caminho]

    def apagar(caminho):
        publicados.pop(caminho, None)
        estagiados.pop(caminho, None)

    def guardar_parte(caminho, indice, dados):
        estagiados.setdefault(caminho, {})[indice] = dados

    def juntar_partes(caminho, quantas, tipo):
        partes = estagiados.get(caminho, {})
        faltando = [i for i in range(quantas) if i not in partes]
        if faltando:
            #: O serviço recusa a lista inteira quando um bloco falta. O fake
            #: precisa recusar também, senão o teste da parte faltando passaria
            #: por o fake ser tolerante.
            raise RuntimeError(f"blocos ausentes: {faltando}")
        publicados[caminho] = b"".join(partes[i] for i in range(quantas))

    monkeypatch.setattr(blob, "ligado", lambda: True)
    monkeypatch.setattr(blob, "guardar", guardar)
    monkeypatch.setattr(blob, "ler", ler)
    monkeypatch.setattr(blob, "apagar", apagar)
    monkeypatch.setattr(blob, "guardar_parte", guardar_parte)
    monkeypatch.setattr(blob, "juntar_partes", juntar_partes)
    return {"publicados": publicados, "estagiados": estagiados}


@pytest.fixture
def sem_armazenamento(monkeypatch):
    monkeypatch.setattr(blob, "ligado", lambda: False)


def _planilha(veiculos: list[str] = ("Jornal de Teste",)) -> bytes:
    from openpyxl import Workbook

    pasta = Workbook()
    pasta.remove(pasta.active)
    aba = pasta.create_sheet("Clipping")
    aba.append(_CABECALHO)
    for indice, veiculo in enumerate(veiculos):
        aba.append([
            "2026-08-10", "POSITIVA", "Relevante", veiculo, "Opinião Pública",
            "Tarifa", "1. Governança", f"id-{indice}", "https://exemplo/1",
            "Uma matéria", "Santa Catarina", "Águas de Teste", "Local",
        ])
    arquivo = io.BytesIO()
    pasta.save(arquivo)
    return arquivo.getvalue()


# -- os ajudantes do fluxo ----------------------------------------------------


def _comecar(cliente, tamanho: int, codigo: str = "clipei"):
    return cliente.post(
        f"/api/score/fontes/{codigo}/planilha/upload", data={"tamanho": tamanho}
    )


def _parte(cliente, planilha_id, indice: int, dados: bytes, codigo: str = "clipei"):
    return cliente.put(
        f"/api/score/fontes/{codigo}/planilha/{planilha_id}/parte/{indice}",
        files={"parte": (f"parte-{indice}", dados, "application/octet-stream")},
    )


def _conferir_montada(cliente, planilha_id, partes: int, nome="export.xlsx", codigo="clipei"):
    return cliente.post(
        f"/api/score/fontes/{codigo}/planilha/{planilha_id}/conferencia",
        data={"partes": partes, "nome": nome},
    )


def _em_pedacos(dados: bytes, tamanho: int) -> list[bytes]:
    return [dados[i : i + tamanho] for i in range(0, len(dados), tamanho)]


# -- o caminho inteiro --------------------------------------------------------


def test_a_planilha_sobe_em_partes_e_a_conferencia_responde_igual(
    cliente, sessao, armazenamento
):
    """O contrato: subir em partes dá a MESMA conferência de subir de uma vez.

    Não é "parecida": é a mesma resposta, porque é a mesma função montando a
    saída. Se divergirem, a tela do arquivo grande mostra menos do que a do
    pequeno, e ninguém repara até alguém decidir com informação a menos.
    """
    conteudo = _planilha(["Jornal A", "Jornal B"])
    pedacos = _em_pedacos(conteudo, 2048)
    assert len(pedacos) > 1, "o teste precisa de mais de uma parte"

    abertura = _comecar(cliente, len(conteudo))
    assert abertura.status_code == 200, abertura.text
    planilha_id = abertura.json()["planilha_id"]
    assert abertura.json()["tamanho_da_parte"] == planilha_do_score.TAMANHO_DA_PARTE

    for indice, pedaco in enumerate(pedacos):
        assert _parte(cliente, planilha_id, indice, pedaco).status_code == 204

    resposta = _conferir_montada(cliente, planilha_id, len(pedacos))

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["planilha_id"] == planilha_id
    assert corpo["previsao"], "a conferência não previu nada"
    assert {v["nome"] for v in corpo["veiculos_novos"]} == {"Jornal A", "Jornal B"}


def test_o_arquivo_montado_e_IDENTICO_ao_que_subiria_de_uma_vez(cliente, armazenamento):
    """A montagem não pode alterar um byte — é um `.xlsx`, e zip não perdoa."""
    conteudo = _planilha(["Jornal A", "Jornal B", "Jornal C"])
    pedacos = _em_pedacos(conteudo, 1500)

    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)
    _conferir_montada(cliente, planilha_id, len(pedacos))

    montado = next(iter(armazenamento["publicados"].values()))
    assert montado == conteudo


def test_as_partes_podem_CHEGAR_FORA_DE_ORDEM(cliente, armazenamento):
    """O cliente pode subir em paralelo, e a ordem é a da lista, não a da chegada.

    Sem isto, upload concorrente montaria um arquivo embaralhado — e o sintoma
    seria "não consegui abrir a planilha", que manda procurar defeito no
    arquivo da pessoa.
    """
    conteudo = _planilha(["Jornal A", "Jornal B"])
    pedacos = _em_pedacos(conteudo, 1024)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]

    for indice in reversed(range(len(pedacos))):
        _parte(cliente, planilha_id, indice, pedacos[indice])
    resposta = _conferir_montada(cliente, planilha_id, len(pedacos))

    assert resposta.status_code == 200, resposta.text
    assert next(iter(armazenamento["publicados"].values())) == conteudo


def test_a_parte_reenviada_SUBSTITUI_a_anterior(cliente, armazenamento):
    """É o que deixa o cliente repetir a que falhou sem recomeçar a subida.

    `PUT` promete isso, e o teste cobra: a primeira versão da parte 0 é lixo, a
    segunda é o pedaço certo, e o arquivo montado tem de ser o certo.
    """
    conteudo = _planilha(["Jornal A", "Jornal B"])
    pedacos = _em_pedacos(conteudo, 1024)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]

    _parte(cliente, planilha_id, 0, b"lixo que falhou no meio")
    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)

    _conferir_montada(cliente, planilha_id, len(pedacos))
    assert next(iter(armazenamento["publicados"].values())) == conteudo


def test_a_confirmacao_pelo_identificador_funciona_depois_da_montagem(
    cliente, sessao, armazenamento
):
    """A ponta solta: montar em partes tem de desaguar na confirmação que já
    existe, sem reenviar os bytes."""
    antes = sessao.scalar(select(func.count()).select_from(Mencao))
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, 2048)

    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)
    _conferir_montada(cliente, planilha_id, len(pedacos))

    importacao = cliente.post(
        "/api/score/fontes/clipei/planilha", data={"planilha_id": planilha_id}
    )

    assert importacao.status_code == 201, importacao.text
    assert sessao.scalar(select(func.count()).select_from(Mencao)) > antes
    #: E A LINHA SAIU, como no caminho de uma vez só.
    assert sessao.scalar(select(func.count()).select_from(PlanilhaRecebida)) == 0


# -- o que recusa, e QUANDO ---------------------------------------------------


def test_a_parte_que_FALTA_recusa_com_nome(cliente, sessao, armazenamento):
    """Montar sem um pedaço daria um `.xlsx` truncado.

    E o sintoma seria "não consegui abrir o arquivo como planilha" — que manda
    a pessoa procurar defeito no arquivo dela quando o problema é a subida.
    """
    conteudo = _planilha(["Jornal A", "Jornal B"])
    pedacos = _em_pedacos(conteudo, 1024)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]

    for indice, pedaco in enumerate(pedacos):
        if indice == 1:
            continue  # a parte 1 nunca sobe
        _parte(cliente, planilha_id, indice, pedaco)

    resposta = _conferir_montada(cliente, planilha_id, len(pedacos))

    assert resposta.status_code == 422, resposta.text
    assert "parte" in resposta.text.lower()
    assert sessao.scalar(select(func.count()).select_from(PlanilhaRecebida)) == 0


def test_o_TETO_e_conferido_na_ABERTURA_e_nao_depois_de_onze_partes(
    cliente, armazenamento
):
    """Descobrir o teto na décima primeira parte é fazer a pessoa pagar o
    upload inteiro para ouvir não.

    A FIXTURE DO ARMAZENAMENTO É NECESSÁRIA AQUI, e a primeira versão deste
    teste não a tinha: sem ela a recusa de "este ambiente não guarda arquivos"
    dispara primeiro, o teste passava pelo motivo errado, e eu só reparei porque
    afirmei a mensagem em vez de só o código 422.
    """
    resposta = _comecar(cliente, ingerir_mencoes.TAMANHO_MAXIMO + 1)

    assert resposta.status_code == 422, resposta.text
    assert "MB" in resposta.text


def test_a_FONTE_INTERNA_e_recusada_na_abertura(cliente, armazenamento):
    """Pelo mesmo motivo do teto: as recusas de cadastro vêm antes da subida.

    O CRM é interna — o dado já está neste banco e não vem de planilha.

    A FIXTURE E A MENSAGEM SÃO O TESTE. Sem `armazenamento` a recusa de "este
    ambiente não guarda arquivos" responde primeiro e o 422 vem pelo motivo
    errado — o harness de mutação provou isso: tirar `recusar_a_fonte` da rota
    não derrubava este teste. Afirmar a palavra "interna" é o que amarra.
    """
    resposta = _comecar(cliente, 1024, codigo="crm")

    assert resposta.status_code == 422, resposta.text
    assert "interna" in resposta.text


def test_SEM_ARMAZENAMENTO_a_abertura_recusa_dizendo_o_que_fazer(
    cliente, sem_armazenamento
):
    """Não há onde montar, e a tela tem de cair no envio de uma vez só.

    A recusa precisa DIZER isso: "não consegui" sem alternativa deixa a pessoa
    sem caminho, e o caminho existe.
    """
    resposta = _comecar(cliente, 5 * 1024 * 1024)

    assert resposta.status_code == 422, resposta.text
    assert "de uma vez" in resposta.text


def test_a_PARTE_VAZIA_e_recusada(cliente, armazenamento):
    """O Blob aceita bloco de zero byte, e um no meio da lista trunca o arquivo."""
    planilha_id = _comecar(cliente, 4096).json()["planilha_id"]

    resposta = _parte(cliente, planilha_id, 0, b"")

    assert resposta.status_code == 422, resposta.text


def test_o_que_NAO_E_PLANILHA_e_recusado_e_o_byte_montado_SAI(
    cliente, sessao, armazenamento
):
    """A recusa depois da montagem tem de apagar o arquivo publicado.

    AQUI A ORDEM É INVERTIDA em relação à subida de uma vez: o byte existe antes
    da conferência, porque é dele que se leu. Sem o descarte explícito, cada
    planilha recusada deixaria até 80 MB no contêiner — e recusar é caso normal.
    """
    conteudo = b"isto nao e um zip, e a assinatura prova"
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    _parte(cliente, planilha_id, 0, conteudo)

    resposta = _conferir_montada(cliente, planilha_id, 1)

    assert resposta.status_code == 422, resposta.text
    assert sessao.scalar(select(func.count()).select_from(PlanilhaRecebida)) == 0
    assert armazenamento["publicados"] == {}, "o arquivo montado ficou no contêiner"


def test_a_fonte_que_nao_existe_da_404_na_abertura(cliente):
    assert _comecar(cliente, 1024, codigo="fonte-que-nao-existe").status_code == 404


# -- a linha que a montagem grava --------------------------------------------


def test_a_linha_guarda_o_NOME_que_a_pessoa_enviou_e_o_tamanho_MONTADO(
    cliente, sessao, armazenamento
):
    """O nome não entra no caminho da montagem — vem no último passo e mora na
    linha, que é de onde a tela o lê.

    E O TAMANHO É O MONTADO, não o declarado na abertura: o declarado é
    afirmação do cliente e serve para poupar trabalho, não para virar dado.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, 2048)
    planilha_id = _comecar(cliente, 999_999).json()["planilha_id"]
    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)

    _conferir_montada(cliente, planilha_id, len(pedacos), nome="clipping de julho.xlsx")

    recebida = sessao.get(PlanilhaRecebida, planilha_id)
    assert recebida is not None
    assert recebida.nome == "clipping de julho.xlsx"
    assert recebida.tamanho == len(conteudo)
    assert recebida.tamanho != 999_999


def test_conferir_de_novo_em_partes_substitui_a_anterior(cliente, sessao, armazenamento):
    """A invariante do índice único da `0092` vale nos dois caminhos: uma
    planilha pendente por fonte e por pessoa."""
    primeiro = _planilha(["Jornal A"])
    pid1 = _comecar(cliente, len(primeiro)).json()["planilha_id"]
    _parte(cliente, pid1, 0, primeiro)
    _conferir_montada(cliente, pid1, 1)

    segundo = _planilha(["Jornal B"])
    pid2 = _comecar(cliente, len(segundo)).json()["planilha_id"]
    _parte(cliente, pid2, 0, segundo)
    _conferir_montada(cliente, pid2, 1)

    assert pid1 != pid2
    assert sessao.get(PlanilhaRecebida, pid1) is None
    assert sessao.get(PlanilhaRecebida, pid2) is not None
    assert sessao.scalar(select(func.count()).select_from(PlanilhaRecebida)) == 1


def test_a_fonte_do_caminho_separa_as_montagens(cliente, armazenamento):
    """Duas fontes, dois caminhos: a montagem de uma não vê a parte da outra.

    O caminho leva a fonte, e é isso que o garante — não a sorte do uuid.
    """
    irma = "clipei_investidores"
    conteudo = _planilha(["Jornal A"])
    pid = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    _parte(cliente, pid, 0, conteudo)

    #: A MESMA parte, o MESMO id, pela fonte irmã: o caminho é outro.
    _parte(cliente, pid, 0, conteudo, codigo=irma)

    caminhos = set(armazenamento["estagiados"])
    assert len(caminhos) == 2, caminhos
    assert any("clipei_investidores" in c for c in caminhos)


def test_a_montagem_nao_publica_nada_antes_de_juntar(cliente, armazenamento):
    """Bloco não commitado não existe para ninguém.

    É o que faz subida interrompida não deixar arquivo pela metade para alguém
    ler — e o que torna desnecessário limpar as partes de uma subida abandonada.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, 1024)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]

    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)

    assert armazenamento["publicados"] == {}, "publicou antes de montar"
    assert armazenamento["estagiados"], "não guardou as partes"
