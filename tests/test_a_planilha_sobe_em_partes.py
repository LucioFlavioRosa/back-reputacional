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


#: A PARTE PEQUENA, para os testes terem MUITAS partes sem arquivos de
#: megabytes. O protocolo exige parte cheia menos a última, então cortar em
#: 1 KB com o tamanho real de 1 MB seria recusado — e corretamente.
_PARTE_DE_TESTE = 2048


@pytest.fixture(autouse=True)
def parte_pequena(monkeypatch):
    """Troca o tamanho da parte por um que cabe num teste rápido.

    AUTOUSE porque todo teste deste arquivo corta arquivo em partes, e esquecer
    a fixture num deles faria o teste passar com UMA parte — provando o caminho
    de uma vez só com o nome do outro.

    O TETO DE PARTES É FUNÇÃO e não constante por causa disto: calculado no
    import, ele ficaria com o valor de 1 MB e o limite deixaria de valer aqui.
    """
    monkeypatch.setattr(planilha_do_score, "TAMANHO_DA_PARTE", _PARTE_DE_TESTE)


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


def _comecar(cliente, tamanho: int, codigo: str = "clipei", nome: str = "export.xlsx"):
    #: O NOME VEM NA ABERTURA desde a `0094`: a linha nasce aqui, e `nome` é
    #: coluna `not null`. Pedi-lo no fim obrigaria um valor de mentira no meio.
    return cliente.post(
        f"/api/score/fontes/{codigo}/planilha/upload",
        data={"tamanho": tamanho, "nome": nome},
    )


def _parte(cliente, planilha_id, indice: int, dados: bytes, codigo: str = "clipei"):
    return cliente.put(
        f"/api/score/fontes/{codigo}/planilha/{planilha_id}/parte/{indice}",
        files={"parte": (f"parte-{indice}", dados, "application/octet-stream")},
    )


def _conferir_montada(cliente, planilha_id, partes: int, codigo="clipei"):
    return cliente.post(
        f"/api/score/fontes/{codigo}/planilha/{planilha_id}/conferencia",
        data={"partes": partes},
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
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
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
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)

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
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
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
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
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
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)

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
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]

    for indice, pedaco in enumerate(pedacos):
        if indice == 1:
            continue  # a parte 1 nunca sobe
        _parte(cliente, planilha_id, indice, pedaco)

    resposta = _conferir_montada(cliente, planilha_id, len(pedacos))

    assert resposta.status_code == 422, resposta.text
    assert "parte" in resposta.text.lower()
    #: A LINHA FICA, INCOMPLETA — e isso é o conserto do byte órfão, não um
    #: resto. Antes da `0094` a linha nascia depois do arquivo, e uma recusa
    #: aqui deixava um byte que nenhuma linha citava. Agora a subida continua
    #: registrada e rastreável pelo `criado_em`.
    subida = sessao.get(PlanilhaRecebida, planilha_id)
    assert subida is not None and subida.subindo is True


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
    assert armazenamento["publicados"] == {}, "o arquivo montado ficou no contêiner"
    #: A LINHA FICA INCOMPLETA: a subida existe, o byte saiu, e a pessoa pode
    #: começar de novo. Confirmar por este id é recusado por `recuperar`.
    subida = sessao.get(PlanilhaRecebida, planilha_id)
    assert subida is not None and subida.subindo is True


def test_a_fonte_que_nao_existe_da_404_na_abertura(cliente):
    assert _comecar(cliente, 1024, codigo="fonte-que-nao-existe").status_code == 404


# -- a linha que a montagem grava --------------------------------------------


def test_a_linha_guarda_o_NOME_da_abertura_e_o_tamanho_MONTADO(
    cliente, sessao, armazenamento
):
    """O nome vem na abertura, porque a linha nasce lá. O tamanho é corrigido
    no fim.

    O DECLARADO É AFIRMAÇÃO DO CLIENTE e serve para dimensionar os tetos; o que
    fica gravado é o que o arquivo tem. Guardar o declarado faria a tela dizer
    um número que ninguém mediu.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
    #: DECLARA UM POUCO MAIS do que o arquivo tem, dentro da mesma contagem de
    #: partes: é o suficiente para provar que o gravado é o MEDIDO, sem violar a
    #: regra de parte cheia.
    declarado = len(conteudo) + 7
    planilha_id = _comecar(
        cliente, declarado, nome="clipping de julho.xlsx"
    ).json()["planilha_id"]

    #: ENQUANTO SOBE, a linha já existe e já guarda o declarado.
    subindo = sessao.get(PlanilhaRecebida, planilha_id)
    assert subindo is not None, "a linha não nasceu na abertura"
    assert subindo.subindo is True
    assert subindo.tamanho == declarado

    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)
    _conferir_montada(cliente, planilha_id, len(pedacos))

    #: `flush` E NÃO `expire_all`: a rota alterou o objeto e quem grava é o
    #: `commit` de `obter_sessao`, que não roda no teste (a sessão é injetada).
    #: `expire_all` DESCARTARIA a alteração pendente e o teste leria o estado
    #: anterior — passando a afirmar que a subida não fechou quando ela fechou.
    sessao.flush()
    recebida = sessao.get(PlanilhaRecebida, planilha_id)
    assert recebida is not None
    assert recebida.nome == "clipping de julho.xlsx"
    assert recebida.subindo is False, "a subida não foi fechada"
    assert recebida.tamanho == len(conteudo)
    assert recebida.tamanho != declarado


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


def test_a_subida_PERTENCE_A_UMA_FONTE(cliente, armazenamento):
    """O mesmo id pela fonte irmã é recusado.

    ANTES DA `0094` ISTO SE PROVAVA PELO CAMINHO: a fonte entrava nele, então
    a parte ia para outro lugar e as duas montagens não se misturavam. Agora a
    garantia é mais forte e mais barata — a subida é uma LINHA que pertence a
    uma fonte, e pela irmã ela simplesmente não existe.

    O caminho continua levando a fonte, para o contêiner ser legível quando um
    byte sobra; mas não é mais ele que separa.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
    pid = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    assert _parte(cliente, pid, 0, pedacos[0]).status_code == 204

    resposta = _parte(cliente, pid, 0, pedacos[0], codigo="clipei_investidores")

    assert resposta.status_code == 404, resposta.text
    assert len(set(armazenamento["estagiados"])) == 1


# -- a subida tem DONO (0094) -------------------------------------------------


@pytest.fixture
def outra_pessoa(sessao):
    """Alguém de verdade no banco, porque `criado_por` tem chave estrangeira."""
    from uuid import uuid4 as _uuid4

    from app.banco.tabelas_acesso import Papel, Usuario

    papel = sessao.scalars(select(Papel).limit(1)).first()
    sufixo = _uuid4().hex[:8]
    pessoa = Usuario(
        entra_object_id=f"partes-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome="Outra pessoa",
        papel_id=papel.id if papel else None,
        acesso_irrestrito=True,
    )
    sessao.add(pessoa)
    sessao.flush()
    return pessoa


def test_a_PARTE_DE_OUTRA_PESSOA_e_recusada(cliente, sessao, armazenamento, outra_pessoa):
    """O ACHADO CENTRAL da revisão do Codex em 16/10/2026.

    Antes da `0094` não havia linha até a conferência, então `receber_parte` não
    tinha o que consultar para saber de quem era a subida — e aceitava parte de
    qualquer sessão. O `planilha_id` valia como SENHA AO PORTADOR:

        1. A abre a subida e recebe o uuid
        2. B obtém o uuid (log, proxy, extensão, inspeção da requisição)
        3. B manda partes para o mesmo caminho
        4. B chama a conferência
        5. a planilha é registrada no nome de B

    A SUBIDA TROCA DE DONO no teste em vez de o cliente trocar de perfil: o
    perfil mockado é um só por processo, e o que se quer provar é a dona da
    LINHA, não o papel de quem pede.
    """
    conteudo = _planilha(["Jornal A"])
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    subida = sessao.get(PlanilhaRecebida, planilha_id)
    subida.criado_por = outra_pessoa.id
    sessao.flush()

    resposta = _parte(cliente, planilha_id, 0, conteudo)

    assert resposta.status_code == 404, resposta.text
    assert armazenamento["estagiados"] == {}, "escreveu na subida de outra pessoa"


def test_a_CONFERENCIA_DE_OUTRA_PESSOA_e_recusada(
    cliente, sessao, armazenamento, outra_pessoa
):
    """A outra metade do mesmo defeito: sem a verificação, B fechava a subida de
    A e a planilha ficava registrada no nome de B."""
    conteudo = _planilha(["Jornal A"])
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    _parte(cliente, planilha_id, 0, conteudo)
    subida = sessao.get(PlanilhaRecebida, planilha_id)
    subida.criado_por = outra_pessoa.id
    sessao.flush()

    resposta = _conferir_montada(cliente, planilha_id, 1)

    assert resposta.status_code == 404, resposta.text


def test_a_parte_de_um_UUID_NUNCA_ABERTO_e_recusada(cliente, armazenamento):
    """`PUT` com uuid inventado gastava armazenamento sem criar estado nenhum.

    Não é só desperdício: era a porta pela qual qualquer sessão escrevia em
    qualquer caminho de `planilhas/`.
    """
    from uuid import uuid4

    resposta = _parte(cliente, uuid4(), 0, b"bytes de qualquer coisa")

    assert resposta.status_code == 404, resposta.text
    assert armazenamento["estagiados"] == {}


def test_a_parte_de_uma_subida_JA_CONFERIDA_e_recusada(cliente, armazenamento):
    """`commit_block_list` SOBRESCREVE o blob existente — não há equivalente do
    `overwrite=False`.

    Sem a condição "ainda subindo", mandar parte para uma planilha já conferida
    e chamar a montagem de novo substituiria um arquivo que alguém está prestes
    a confirmar.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)
    assert _conferir_montada(cliente, planilha_id, len(pedacos)).status_code == 200

    resposta = _parte(cliente, planilha_id, 0, pedacos[0])

    assert resposta.status_code == 404, resposta.text


def test_CONFIRMAR_uma_planilha_que_AINDA_SOBE_e_recusado(cliente, sessao, armazenamento):
    """Confirmar antes da conferência leria um arquivo que não existe.

    `commit_block_list` não rodou, então o caminho está vazio. Sem a condição em
    `recuperar`, a importação quebraria em leitura de blob — longe da causa.
    """
    conteudo = _planilha(["Jornal A"])
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    _parte(cliente, planilha_id, 0, conteudo)

    resposta = cliente.post(
        "/api/score/fontes/clipei/planilha", data={"planilha_id": planilha_id}
    )

    assert resposta.status_code == 404, resposta.text


# -- os tetos que faltavam (0094) ---------------------------------------------


def test_a_PARTE_MAIOR_QUE_O_TETO_e_recusada(cliente, armazenamento):
    """A rota da parte é ISENTA do limite genérico de corpo — tem de ser.

    Então sem este teto uma sessão autorizada mandava partes de qualquer
    tamanho, e o servidor as lia inteiras na memória. Achado da revisão.
    """
    planilha_id = _comecar(cliente, 10 * 1024 * 1024).json()["planilha_id"]
    grande = b"x" * (planilha_do_score.TAMANHO_DA_PARTE + 1)

    resposta = _parte(cliente, planilha_id, 0, grande)

    assert resposta.status_code == 422, resposta.text
    assert "parte" in resposta.text.lower()


def test_o_INDICE_ALEM_DO_DECLARADO_e_recusado(cliente, armazenamento):
    """Declarar 1 MB e enviar oitenta partes de 1 MB montava 80 MB.

    O teto da abertura só olhava o DECLARADO, e nada depois o fazia valer. O
    índice preso ao declarado é o que fecha: o arquivo montado não passa de
    pouco mais do que a pessoa disse que ele tem.
    """
    planilha_id = _comecar(cliente, 1024).json()["planilha_id"]  # cabe em 1 parte

    assert _parte(cliente, planilha_id, 0, b"ok").status_code == 204
    #: PARTE CHEIA no índice fora de faixa, e a mensagem afirmada: com uma parte
    #: curta, a regra de "parte cheia menos a última" recusaria primeiro e o
    #: teste passaria sem provar ESTE teto. O harness de mutação mostrou isso —
    #: tirar o teto do índice não derrubava a versão anterior deste teste.
    cheia = b"x" * _PARTE_DE_TESTE
    resposta = _parte(cliente, planilha_id, 1, cheia)

    assert resposta.status_code == 422, resposta.text
    assert "fora do tamanho que a subida declarou" in resposta.text


def test_uma_CONTAGEM_DE_PARTES_ABSURDA_e_recusada(cliente, armazenamento):
    """`partes=1_000_000_000` fazia o processo construir a lista de blocos ANTES
    de falar com o Azure — uma requisição derrubava a réplica.

    A MENSAGEM É O TESTE, e não o 422. O harness de mutação mostrou que tirar o
    teto não derrubava a versão anterior: sem ele a montagem é tentada, falha
    por bloco ausente, e devolve 422 também — por outro motivo. Afirmar só o
    código deixava o teto sem guarda nenhuma.

    E A PROVA DESTA GUARDA NÃO É UM TESTE VERMELHO. Medido em 16/10/2026: com o
    teto removido, o processo é MORTO por falta de memória em 16,8 s — exit -9,
    nenhuma saída. É o sintoma exato que o teto impede, e nenhum harness de
    mutação consegue expressá-lo como falha de asserção: não há resultado de
    teste porque não há mais processo.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]
    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)

    resposta = _conferir_montada(cliente, planilha_id, 1_000_000_000)

    assert resposta.status_code == 422, resposta.text
    assert "contagem de partes" in resposta.text


def test_ABRIR_SUBIDA_NOVA_substitui_a_pendente(cliente, sessao, armazenamento):
    """O índice único de (fonte, dono) passa a significar "uma subida em voo".

    É o que limita o abuso sem contador: quem abre subida atrás de subida
    substitui a própria, e o byte da anterior sai.
    """
    primeiro = _comecar(cliente, 4096).json()["planilha_id"]
    _parte(cliente, primeiro, 0, b"bytes da primeira subida")

    segundo = _comecar(cliente, 4096).json()["planilha_id"]

    assert segundo != primeiro
    assert sessao.get(PlanilhaRecebida, primeiro) is None
    assert sessao.scalar(select(func.count()).select_from(PlanilhaRecebida)) == 1


def test_a_montagem_nao_publica_nada_antes_de_juntar(cliente, armazenamento):
    """Bloco não commitado não existe para ninguém.

    É o que faz subida interrompida não deixar arquivo pela metade para alguém
    ler — e o que torna desnecessário limpar as partes de uma subida abandonada.
    """
    conteudo = _planilha(["Jornal A"])
    pedacos = _em_pedacos(conteudo, _PARTE_DE_TESTE)
    planilha_id = _comecar(cliente, len(conteudo)).json()["planilha_id"]

    for indice, pedaco in enumerate(pedacos):
        _parte(cliente, planilha_id, indice, pedaco)

    assert armazenamento["publicados"] == {}, "publicou antes de montar"
    assert armazenamento["estagiados"], "não guardou as partes"
