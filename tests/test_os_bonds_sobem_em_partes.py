"""O export de bonds sobe em pedaços, como a planilha do Score já sobe.

POR QUE ESTE CAMINHO EXISTE. O ingress do Container Apps encerra a requisição
por volta de 240 s e isso NÃO é configurável. Medido em 16/10/2026, na mesma
máquina e na mesma hora, com a banda variando de ~18 KB/s a ~350 KB/s:

    1,42 MB  ->    4,1 s  -> 200
   10,53 MB  ->  212,4 s  -> 403   (o ingress desistindo)

O export de bonds é CUMULATIVO e cresce toda semana. Hoje tem 1,05 MB e passa;
e a tela ainda o mandava DUAS VEZES, porque confere e depois importa.

O QUE ESTE ARQUIVO PROTEGE, além do caminho feliz: o DONO da subida. As
condições de segurança deste desenho saíram todas da revisão de 16/10/2026
contra a planilha do Score, nenhuma de projeto — e a versão de bonds nasceu
depois delas justamente para não repetir os quatro defeitos.

AS REGRAS DO PEDAÇO (tamanho, índice, contagem) estão em
`test_subida_em_partes`, sem banco. Aqui se prova que as rotas as CHAMAM, com
dono e armazenamento de verdade.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_mercado import BondCotacao, PlanilhaDeBondsRecebida
from app.casos_de_uso import subida_em_partes
from main import app
from tests.test_e2e_postgres import URL
from tests.test_ingerir_bonds import DO_CADASTRO, _planilha

_engine = create_engine(URL, pool_pre_ping=True)

#: A PARTE PEQUENA, para o teste ter MUITAS partes sem arquivos de megabytes. O
#: protocolo exige parte cheia menos a última, então cortar em 1 KB com o
#: tamanho real de 1 MB seria recusado — e corretamente.
_PARTE_DE_TESTE = 2048


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

    #: `mercado_lancado` E A BANDEIRA DO PAPEL: o roteiro inteiro de
    #: `/api/mercado` está atrás das duas. Sem elas, todo teste deste arquivo
    #: levaria 403 antes de chegar na subida — e falharia dizendo que o portal
    #: não foi lançado, que não é o que se quer medir aqui.
    padrao = obter_configuracao()
    como = Configuracao(
        **{
            **padrao.model_dump(),
            "auth_mock": True,
            "auth_mock_perfil": "plataforma_edicao",
            "mercado_lancado": True,
        }
    )
    papel = sessao.scalars(
        select(Papel).where(Papel.codigo == "plataforma_edicao")
    ).one()
    papel.acessa_inteligencia_de_mercado = True
    sessao.flush()
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def armazenamento(monkeypatch):
    """Um Blob de mentira que MODELA BLOCO NÃO COMMITADO.

    É o ponto do caminho em partes: as partes ficam numa área separada e o
    caminho final NÃO EXISTE até a montagem. Um `ler` antes de `juntar_partes`
    tem de falhar — se ele funcionasse, o teste da montagem passaria sem a
    montagem.
    """
    publicados: dict[str, bytes] = {}
    estagiados: dict[str, dict[int, bytes]] = {}

    def juntar_partes(caminho, quantas, tipo):
        partes = estagiados.get(caminho, {})
        faltando = [i for i in range(quantas) if i not in partes]
        if faltando:
            #: O serviço recusa a lista inteira quando um bloco falta. O fake
            #: recusa também, senão o teste da parte faltando passaria por o
            #: fake ser tolerante.
            raise RuntimeError(f"blocos ausentes: {faltando}")
        publicados[caminho] = b"".join(partes[i] for i in range(quantas))

    monkeypatch.setattr(blob, "ligado", lambda: True)
    monkeypatch.setattr(blob, "ler", lambda caminho: publicados[caminho])
    monkeypatch.setattr(blob, "apagar", lambda caminho: publicados.pop(caminho, None))
    monkeypatch.setattr(
        blob,
        "guardar_parte",
        lambda caminho, indice, dados: estagiados.setdefault(caminho, {}).__setitem__(
            indice, dados
        ),
    )
    monkeypatch.setattr(blob, "juntar_partes", juntar_partes)
    return {"publicados": publicados, "estagiados": estagiados}


@pytest.fixture(autouse=True)
def parte_pequena(monkeypatch):
    """Troca o tamanho da parte por um que cabe num teste rápido.

    AUTOUSE porque todo teste deste arquivo corta arquivo em partes, e esquecer
    a fixture num deles faria o teste passar com UMA parte — provando o caminho
    de uma vez só com o nome do outro.

    A TROCA É EM `subida_em_partes`, que é onde a constante mora e onde as
    recusas a leem. Trocá-la em `planilha_de_bonds` não alcançaria quem decide.
    """
    monkeypatch.setattr(subida_em_partes, "TAMANHO_DA_PARTE", _PARTE_DE_TESTE)


def _em_partes(conteudo: bytes) -> list[bytes]:
    return [
        conteudo[i : i + _PARTE_DE_TESTE]
        for i in range(0, len(conteudo), _PARTE_DE_TESTE)
    ]


def _subir(cliente, conteudo: bytes, *, nome: str = "bonds.xlsx"):
    """Abre a subida e manda todas as partes. Devolve (subida_id, partes)."""
    abertura = cliente.post(
        "/api/mercado/bonds/upload", data={"tamanho": len(conteudo), "nome": nome}
    )
    assert abertura.status_code == 200, abertura.text
    subida_id = abertura.json()["subida_id"]
    pedacos = _em_partes(conteudo)
    for indice, pedaco in enumerate(pedacos):
        resposta = cliente.put(
            f"/api/mercado/bonds/upload/{subida_id}/parte/{indice}",
            files={"parte": ("parte", pedaco, "application/octet-stream")},
        )
        assert resposta.status_code == 204, resposta.text
    return subida_id, len(pedacos)


def test_o_caminho_inteiro_abre_sobe_confere_e_importa(cliente, sessao, armazenamento):
    """O que a tela faz, de ponta a ponta — e a prova de que o arquivo montado
    é o mesmo que entrou: as cotações chegam ao banco."""
    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    assert len(conteudo) > _PARTE_DE_TESTE, "a fixture coube numa parte só"

    subida_id, partes = _subir(cliente, conteudo)

    #: NADA FOI PUBLICADO ATÉ AQUI: as partes são blocos não commitados.
    assert armazenamento["publicados"] == {}

    conferencia = cliente.post(
        f"/api/mercado/bonds/upload/{subida_id}/conferencia", data={"partes": partes}
    )
    assert conferencia.status_code == 200, conferencia.text
    assert conferencia.json()["cotacoes_no_arquivo"] == 1

    importacao = cliente.post(f"/api/mercado/bonds/upload/{subida_id}/importar")
    assert importacao.status_code == 200, importacao.text

    assert sessao.scalar(select(BondCotacao).where(BondCotacao.data == date(2026, 1, 5)))


def test_SEM_armazenamento_a_rota_manda_a_tela_subir_de_uma_vez(cliente, monkeypatch):
    """`subida_id` NULO, e não 422.

    Era 422 na planilha do Score, e o cliente não tinha como distinguir essa
    recusa das outras desta rota: mostrava a mensagem crua em vez de cair no
    caminho de sempre. O campo nulo é o que permite à tela decidir.
    """
    monkeypatch.setattr(blob, "ligado", lambda: False)

    resposta = cliente.post(
        "/api/mercado/bonds/upload", data={"tamanho": 10_000, "nome": "bonds.xlsx"}
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["subida_id"] is None
    #: E O TAMANHO DA PARTE VAI MESMO ASSIM: um campo que às vezes falta
    #: obrigaria o cliente a tratar duas formas de resposta.
    assert resposta.json()["tamanho_da_parte"] == _PARTE_DE_TESTE


def test_a_parte_de_uma_subida_que_NAO_e_sua_e_recusada(cliente, sessao, armazenamento):
    """O defeito que a revisão achou no desenho sem linha: o identificador
    valia como SENHA AO PORTADOR.

    Aqui a linha existe e é de outra pessoa — a rota tem o que consultar, e a
    consulta é a verificação.
    """
    from uuid import uuid4

    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    subida_id, _ = _subir(cliente, conteudo)

    #: OUTRA PESSOA DE VERDADE, e não um uuid inventado: `criado_por` tem chave
    #: estrangeira para `usuario`, e um id solto seria recusado pelo banco antes
    #: de a rota decidir coisa alguma — o teste passaria por motivo errado.
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "plataforma_edicao")).one()
    outra = Usuario(
        entra_object_id=f"oid-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@aegea.com.br",
        nome="Outra Pessoa",
        papel_id=papel.id,
        acesso_irrestrito=True,
    )
    sessao.add(outra)
    sessao.flush()

    #: TROCA O DONO da linha, sem mexer em mais nada.
    subida = sessao.scalar(
        select(PlanilhaDeBondsRecebida).where(PlanilhaDeBondsRecebida.id == subida_id)
    )
    subida.criado_por = outra.id
    sessao.flush()

    caminho = next(iter(armazenamento["estagiados"]))
    antes = armazenamento["estagiados"][caminho][0]

    resposta = cliente.put(
        f"/api/mercado/bonds/upload/{subida_id}/parte/0",
        files={"parte": ("parte", b"x" * _PARTE_DE_TESTE, "application/octet-stream")},
    )

    assert resposta.status_code == 404, resposta.text
    #: E NADA FOI ESCRITO, que é a propriedade que importa — o status sozinho
    #: não a prova. Era exatamente isto que o desenho sem linha permitia: a
    #: parte de outra pessoa entrava no armazenamento dela.
    assert armazenamento["estagiados"][caminho][0] == antes, (
        "a parte de outra pessoa foi gravada por cima"
    )
    #: A MENSAGEM NO CORPO É GENÉRICA ("Registro não encontrado"), e isso é
    #: `api/erros.py` fazendo o certo: a frase específica fica no log, porque
    #: distinguir "não é sua" de "não existe" conta a quem tem o id se ele
    #: acertou o número de outra pessoa.
    assert "não está em andamento" not in resposta.text


def test_IMPORTAR_sem_ter_montado_e_recusado(cliente, sessao, armazenamento):
    """A subida ainda está em voo: o arquivo NÃO EXISTE no armazenamento.

    Sem esta recusa, a importação leria um caminho que não foi publicado e a
    pessoa veria "não consegui abrir a planilha" — procurando defeito num
    arquivo que está correto.
    """
    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    subida_id, _ = _subir(cliente, conteudo)

    resposta = cliente.post(f"/api/mercado/bonds/upload/{subida_id}/importar")

    assert resposta.status_code == 404, resposta.text


def test_abrir_SUBIDA_NOVA_descarta_a_pendente_da_mesma_pessoa(
    cliente, sessao, armazenamento
):
    """É o que o índice único de `criado_por` exige — uma subida em voo por
    pessoa — e é o que a tela já espera: recomeçar substitui."""
    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    primeira, _ = _subir(cliente, conteudo)
    segunda, _ = _subir(cliente, conteudo, nome="outro.xlsx")

    assert primeira != segunda
    em_voo = sessao.scalars(select(PlanilhaDeBondsRecebida)).all()
    assert [str(linha.id) for linha in em_voo] == [segunda]


def test_a_parte_FALTANDO_vira_recusa_com_nome(cliente, sessao, armazenamento):
    """O serviço recusa a lista inteira quando um bloco não está lá. Sem a
    tradução, a pessoa leria "não consegui abrir o arquivo como planilha" — que
    manda procurar defeito no arquivo dela."""
    conteudo = _planilha(DO_CADASTRO, {date(2026, 1, 5): (95.5, 9.1, 0, 0)})
    subida_id, partes = _subir(cliente, conteudo)

    #: APAGA UMA PARTE DO MEIO, como um bloco expirado faria.
    caminho = next(iter(armazenamento["estagiados"]))
    del armazenamento["estagiados"][caminho][0]

    resposta = cliente.post(
        f"/api/mercado/bonds/upload/{subida_id}/conferencia", data={"partes": partes}
    )

    assert resposta.status_code == 422, resposta.text
    assert "Faltou alguma parte" in resposta.text
