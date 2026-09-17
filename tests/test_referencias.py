"""A biblioteca de referências: pasta no blob, versões, e o caminho até a agenda.

O que esta feature promete é uma frase só: quem marca uma reunião de tarifa não
entra nela sem o Q&A de tarifa — e sem a versão de março quando a de agosto já
existe.

O BLOB É SUBSTITUÍDO POR UM ESPIÃO. Nenhum teste desta suíte sobe byte, e o que
se prova aqui é o CAMINHO que a aplicação escolhe e a numeração das versões.
Passar pelo Azure de verdade faria o teste depender de um serviço que ele não
está exercitando — e falhar por ele.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_referencias import Referencia
from main import app
from tests.test_e2e_postgres import URL, corpo

_engine = create_engine(URL, pool_pre_ping=True)

PDF = b"%PDF-1.7\nconteudo de teste\n%%EOF\n"


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
def guardados(monkeypatch):
    """Os caminhos que a aplicação mandou para o blob, na ordem."""
    caminhos: list[str] = []
    monkeypatch.setattr(
        blob, "guardar", lambda caminho, dados, tipo: caminhos.append(caminho)
    )
    return caminhos


@pytest.fixture
def cliente(sessao):
    """Roda como quem ADMINISTRA cadastros.

    O perfil padrão do cliente de teste é `crm_edicao`, que edita agenda e não
    mexe nos cadastros — e escrever na biblioteca é cadastro.

    SOBRESCREVE `obter_configuracao()` VIA `app.dependency_overrides`, e não
    via `monkeypatch.setattr("app.api.dependencias.obter_configuracao", ...)`.
    O `Depends(obter_configuracao)` de `_usuario_provisionado` foi montado, na
    importação do módulo, com uma referência direta à função original — trocar
    o nome no módulo depois não alcança quem já guardou o objeto. E o padrão
    real do ambiente é `auth_mock=False` (a postura segura por padrão), então
    sem isto o cliente de teste caía no caminho de cookie de produção e via
    "Sessão ausente" em toda escrita.
    """
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
def cliente_sem_cadastros(sessao):
    """O perfil padrão — `crm_edicao`. Lê a biblioteca, não escreve nela.

    Mesma correção de `cliente`: só liga `auth_mock`, sem elevar o perfil.
    """
    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como_mock = Configuracao(**{**padrao.model_dump(), "auth_mock": True})
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como_mock
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    from app.banco.tabelas_stakeholders import Instituicao, PessoaAegea

    sufixo = uuid4().hex[:6]
    valor = Instituicao(
        nome=f"Veiculo {sufixo}",
        nome_normalizado=f"veiculo {sufixo}",
        tipo="veiculo",
        uf="SP",
    )
    a = PessoaAegea(nome=f"A {sufixo}", nome_normalizado=f"a {sufixo}", eh_porta_voz=True)
    b = PessoaAegea(nome=f"B {sufixo}", nome_normalizado=f"b {sufixo}", eh_porta_voz=True)
    sessao.add_all([valor, a, b])
    sessao.flush()
    return {"instituicao": valor, "radames": a, "andre": b}


@pytest.fixture
def assuntos(sessao):
    """Dois assuntos ATIVOS, com os nomes — a pasta usa o nome, não o id."""
    return sessao.execute(
        select(Tema.id, Tema.nome).where(Tema.ativo.is_(True)).order_by(Tema.id).limit(2)
    ).all()


def criar(cliente, assuntos, **campos):
    """Cria uma referência com a primeira versão. Devolve a resposta."""
    dados = {
        "titulo": f"Q&A {uuid4().hex[:8]}",
        "tipo": "qa",
        "tema_principal_id": str(assuntos[0].id),
        "atualizado_em": "2026-08-12",
        "resumo": "O que responder sobre o reajuste.",
        "conteudo": "O texto desta versao, por extenso.",
    }
    dados.update({k: str(v) for k, v in campos.items()})
    return cliente.post(
        "/api/referencias",
        data=dados,
        files={"arquivo": ("qa-tarifa.pdf", PDF, "application/pdf")},
    )


# -- a pasta no blob -----------------------------------------------------------


def test_a_pasta_e_assunto_barra_tipo_barra_referencia(cliente, assuntos, guardados):
    """A árvore é navegável por gente.

    Quem abrir o contêiner precisa encontrar o acervo organizado como a cabeça
    organiza — por assunto, depois por tipo —, e não uma pasta plana de uuids.
    """
    resposta = criar(cliente, assuntos, titulo="Q&A — Tarifa social")
    assert resposta.status_code == 201, resposta.text

    assert len(guardados) == 1
    caminho = guardados[0]
    partes = caminho.split("/")
    assert partes[0] == "referencias", caminho
    assert partes[2] == "qa", f"o tipo e a segunda pasta: {caminho}"
    assert partes[3] == "q-a-tarifa-social", f"a referencia da nome a pasta: {caminho}"
    assert partes[4].startswith("v1-"), f"a versao abre o nome do arquivo: {caminho}"


def test_o_assunto_principal_e_quem_define_a_pasta(cliente, assuntos, guardados):
    """A referência cobre vários assuntos e o byte mora num lugar só.

    Copiá-lo para cada assunto criaria duas verdades que envelhecem separado, e
    trocar a versão exigiria lembrar de trocar nas duas.
    """
    principal, outro = assuntos[0], assuntos[1]
    resposta = criar(cliente, assuntos, tema_principal_id=principal.id, temas=outro.id)
    assert resposta.status_code == 201, resposta.text

    # UM arquivo só — e não um por assunto.
    assert len(guardados) == 1
    # A pasta é a do principal: o nome dele, sem acento, em minúsculas.
    assert guardados[0].split("/")[1] == blob._sem_acento_nem_surpresa(
        principal.nome
    ).lower()

    # E os DOIS assuntos ficam na busca.
    assert sorted(resposta.json()["temas"]) == sorted([principal.id, outro.id])


# -- as versões ----------------------------------------------------------------


def test_a_segunda_versao_nao_apaga_a_primeira(cliente, assuntos, guardados):
    """Foi a de março que circulou naquela reunião.

    É esta a razão de o acervo ter histórico: uma agenda de março continua
    respondendo o que a companhia dizia em março.
    """
    criada = criar(cliente, assuntos).json()
    assert criada["versao"]["numero"] == 1
    assert criada["quantas_versoes"] == 1

    nova = cliente.post(
        f"/api/referencias/{criada['id']}/versoes",
        data={
            "atualizado_em": "2026-09-01",
            "nota": "Atualizado apos o reajuste.",
            "conteudo": "O texto da versao 2.",
        },
        files={"arquivo": ("qa-tarifa-v2.pdf", PDF, "application/pdf")},
    )
    assert nova.status_code == 201, nova.text

    corpo_novo = nova.json()
    assert corpo_novo["versao"]["numero"] == 2, "a tela mostra a mais recente"
    assert corpo_novo["versao"]["atualizado_em"] == "2026-09-01"
    assert corpo_novo["versao"]["nota"] == "Atualizado apos o reajuste."
    assert corpo_novo["quantas_versoes"] == 2, "a primeira continua existindo"

    assert len(guardados) == 2
    assert "/v1-" in guardados[0] and "/v2-" in guardados[1]
    assert guardados[0] != guardados[1], "cada versao tem caminho proprio"


def test_a_numeracao_da_versao_trava_a_referencia(cliente, assuntos, guardados, sessao):
    """Duas subidas ao mesmo tempo não podem receber o mesmo número.

    MEDIDO, e não imaginado: doze POSTs simultâneos na mesma referência
    devolviam dois 201 e dez 500 de `unique (referencia_id, numero)` — e, pior,
    os dez bytes já estavam no blob, órfãos, porque o arquivo subia antes de a
    linha existir.

    Os dois consertos deixam rastro diferente. Este teste cobre o primeiro: a
    contagem só acontece com a LINHA DA REFERÊNCIA TRAVADA, e num teste de uma
    conexão só isso se prova pelo SQL que sai — o `FOR UPDATE`.
    """
    from sqlalchemy import event

    comandos: list[str] = []

    def anotar(conexao, cursor, sql, parametros, contexto, muitos):
        comandos.append(" ".join(sql.split()).upper())

    criada = criar(cliente, assuntos).json()
    event.listen(sessao.get_bind(), "before_cursor_execute", anotar)
    try:
        nova = cliente.post(
            f"/api/referencias/{criada['id']}/versoes",
            data={"atualizado_em": "2026-09-01", "conteudo": "O texto da versao 2."},
            files={"arquivo": ("v2.pdf", PDF, "application/pdf")},
        )
    finally:
        event.remove(sessao.get_bind(), "before_cursor_execute", anotar)

    assert nova.status_code == 201, nova.text
    travas = [c for c in comandos if "FOR UPDATE" in c and "REFERENCIA" in c]
    assert travas, f"a numeracao contou versoes sem travar a referencia: {comandos}"


def test_o_byte_so_sobe_depois_de_a_linha_ser_aceita(
    cliente, assuntos, sessao, monkeypatch
):
    """O segundo conserto da corrida: a ordem da escrita.

    A falha que ACONTECE é a do banco — a linha recusada pela unicidade quando
    outro escritor chegou primeiro. Com o byte subindo antes, cada recusa
    deixava um arquivo sem dono no contêiner; foi assim que dez POSTs perdidos
    viraram dez blobs órfãos.

    Aqui se prova a ordem, e não a exceção: o INSERT da versão tem de sair
    ANTES da chamada ao blob.
    """
    from sqlalchemy import event

    from app.armazenamento import blob as modulo_blob

    passos: list[str] = []
    monkeypatch.setattr(
        modulo_blob, "guardar", lambda caminho, dados, tipo: passos.append("blob")
    )

    criada = criar(cliente, assuntos).json()
    passos.clear()  # a criação já foi; o que se observa é a SEGUNDA versão

    def anotar(conexao, cursor, sql, parametros, contexto, muitos):
        if "INSERT INTO referencia_versao" in " ".join(sql.split()):
            passos.append("linha")

    event.listen(sessao.get_bind(), "before_cursor_execute", anotar)
    try:
        nova = cliente.post(
            f"/api/referencias/{criada['id']}/versoes",
            data={"atualizado_em": "2026-09-01", "conteudo": "O texto da versao 2."},
            files={"arquivo": ("v2.pdf", PDF, "application/pdf")},
        )
    finally:
        event.remove(sessao.get_bind(), "before_cursor_execute", anotar)

    assert nova.status_code == 201, nova.text
    assert passos == ["linha", "blob"], f"o byte subiu fora de ordem: {passos}"


def test_o_historico_vem_da_mais_recente_para_a_mais_antiga(cliente, assuntos, guardados):
    criada = criar(cliente, assuntos).json()
    for dia in ("2026-09-01", "2026-09-05"):
        cliente.post(
            f"/api/referencias/{criada['id']}/versoes",
            data={"atualizado_em": dia, "conteudo": f"O texto de {dia}."},
            files={"arquivo": ("v.pdf", PDF, "application/pdf")},
        )

    versoes = cliente.get(f"/api/referencias/{criada['id']}/versoes").json()
    assert [v["numero"] for v in versoes] == [3, 2, 1]
    assert versoes[0]["criado_por"], "a trilha diz quem subiu"


def test_a_listagem_traz_a_versao_atual_e_quantas_existem(cliente, assuntos, guardados):
    """Sem isso, a tela precisaria de uma ida por linha só para dizer "v3"."""
    criada = criar(cliente, assuntos).json()
    cliente.post(
        f"/api/referencias/{criada['id']}/versoes",
        data={"atualizado_em": "2026-09-01", "conteudo": "O texto da versao 2."},
        files={"arquivo": ("v2.pdf", PDF, "application/pdf")},
    )

    achada = next(
        r for r in cliente.get("/api/referencias").json() if r["id"] == criada["id"]
    )
    assert achada["versao"]["numero"] == 2
    assert achada["quantas_versoes"] == 2
    assert achada["versao"]["arquivo_nome"] == "v2.pdf"
    assert achada["versao"]["arquivo_tamanho"] == len(PDF)


# -- o que a rota recusa -------------------------------------------------------


def test_referencia_sem_arquivo_mas_com_conteudo_e_aceita(cliente, assuntos, guardados):
    """O arquivo virou opcional: a versão pode viver só do texto."""
    resposta = cliente.post(
        "/api/referencias",
        data={
            "titulo": "So conteudo, sem arquivo",
            "tipo": "qa",
            "tema_principal_id": str(assuntos[0].id),
            "atualizado_em": "2026-08-12",
            "resumo": "Um resumo qualquer.",
            "conteudo": "O texto completo, sem arquivo nenhum.",
        },
    )
    assert resposta.status_code == 201, resposta.text
    assert not guardados, "sem arquivo, nada sobe ao blob"

    versao = resposta.json()["versao"]
    assert versao["conteudo"] == "O texto completo, sem arquivo nenhum."
    assert versao["arquivo_id"] is None
    assert versao["arquivo_nome"] is None
    assert versao["arquivo_tamanho"] is None


def test_referencia_sem_arquivo_e_sem_conteudo_e_recusada(cliente, assuntos):
    """Uma versão sem arquivo E sem conteúdo não leva a lugar nenhum."""
    resposta = cliente.post(
        "/api/referencias",
        data={
            "titulo": "Sem arquivo nem conteudo",
            "tipo": "qa",
            "tema_principal_id": str(assuntos[0].id),
            "atualizado_em": "2026-08-12",
            "resumo": "Um resumo qualquer.",
        },
    )
    assert resposta.status_code == 422


def test_referencia_com_arquivo_mas_sem_conteudo_e_recusada(cliente, assuntos):
    """O conteúdo é obrigatório mesmo quando o arquivo vem junto."""
    resposta = cliente.post(
        "/api/referencias",
        data={
            "titulo": "Com arquivo, sem conteudo",
            "tipo": "qa",
            "tema_principal_id": str(assuntos[0].id),
            "atualizado_em": "2026-08-12",
            "resumo": "Um resumo qualquer.",
        },
        files={"arquivo": ("qa.pdf", PDF, "application/pdf")},
    )
    assert resposta.status_code == 422


def test_referencia_sem_resumo_e_recusada(cliente, assuntos):
    """O resumo é obrigatório daqui para a frente."""
    resposta = cliente.post(
        "/api/referencias",
        data={
            "titulo": "Sem resumo",
            "tipo": "qa",
            "tema_principal_id": str(assuntos[0].id),
            "atualizado_em": "2026-08-12",
            "conteudo": "Texto qualquer.",
        },
        files={"arquivo": ("qa.pdf", PDF, "application/pdf")},
    )
    assert resposta.status_code == 422


def test_editar_sem_resumo_continua_aceito(cliente, assuntos, guardados):
    """O resumo obrigatório é regra de TELA (formulário), não do schema de edição.

    Uma referência de antes desta feature pode não ter resumo nenhum — e a
    ação rápida de Desativar/Reativar reenvia os metadados como estão, sem
    passar pelo formulário. Travar isso aqui quebraria essa ação para toda
    referência antiga sem resumo, que é exatamente o cenário que a
    retrocompatibilidade promete não quebrar.
    """
    criada = criar(cliente, assuntos).json()
    resposta = cliente.put(
        f"/api/referencias/{criada['id']}",
        json={
            "titulo": criada["titulo"],
            "tipo": criada["tipo"],
            # `None` explícito — simula a referência antiga sem resumo, cujo
            # valor a tela reenvia como está.
            "resumo": None,
            "tema_principal_id": criada["tema_principal_id"],
            "temas": criada["temas"],
            "ativo": False,
        },
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["resumo"] is None
    assert resposta.json()["ativo"] is False


def test_nova_versao_sem_arquivo_mas_com_conteudo_e_aceita(cliente, assuntos, guardados):
    """Mesma regra de `criar()`: uma versão seguinte também pode viver só do texto."""
    criada = criar(cliente, assuntos).json()

    nova = cliente.post(
        f"/api/referencias/{criada['id']}/versoes",
        data={"atualizado_em": "2026-09-01", "conteudo": "Texto da versao 2, sem arquivo."},
    )
    assert nova.status_code == 201, nova.text
    assert len(guardados) == 1, "so a v1 (com arquivo) subiu ao blob"

    versao = nova.json()["versao"]
    assert versao["numero"] == 2
    assert versao["arquivo_id"] is None
    assert versao["conteudo"] == "Texto da versao 2, sem arquivo."


def test_baixar_versao_sem_arquivo_devolve_404_e_nao_quebra(cliente, assuntos, guardados):
    """Sem a guarda, `versao.arquivo.caminho` estouraria em `AttributeError`."""
    criada = criar(cliente, assuntos).json()
    cliente.post(
        f"/api/referencias/{criada['id']}/versoes",
        data={"atualizado_em": "2026-09-01", "conteudo": "So texto, sem arquivo."},
    )
    versoes = cliente.get(f"/api/referencias/{criada['id']}/versoes").json()
    sem_arquivo = next(v for v in versoes if v["numero"] == 2)

    resposta = cliente.get(
        f"/api/referencias/{criada['id']}/versoes/{sem_arquivo['id']}/arquivo"
    )
    assert resposta.status_code == 404


def test_o_mesmo_titulo_nao_entra_duas_vezes(cliente, assuntos, guardados):
    """Duas linhas com o mesmo nome apontando para arquivos diferentes é o
    começo de duas versões circulando — o problema que a biblioteca resolve."""
    assert criar(cliente, assuntos, titulo="Posicionamento — Tarifa").status_code == 201
    repetida = criar(cliente, assuntos, titulo="  POSICIONAMENTO — TARIFA  ")
    assert repetida.status_code == 422
    assert "Ja existe" in repetida.json()["detalhe"]


def test_tipo_fora_do_vocabulario_e_recusado(cliente, assuntos, guardados):
    resposta = criar(cliente, assuntos, tipo="inventado")
    assert resposta.status_code == 422
    assert "Tipo invalido" in resposta.json()["detalhe"]


def test_assunto_inexistente_e_recusado_com_mensagem(cliente, assuntos, guardados):
    """A chave estrangeira recusaria com um 500, que não diz o que fazer."""
    resposta = criar(cliente, assuntos, tema_principal_id=999999)
    assert resposta.status_code == 422
    assert "999999" in resposta.json()["detalhe"]


def test_quem_nao_administra_cadastros_nao_escreve_na_biblioteca(
    cliente_sem_cadastros, assuntos
):
    """Ler a biblioteca é de todo mundo do CRM; escrever nela, não.

    Uma referência errada circula por todas as reuniões daquele assunto — o
    alcance do erro é o que justifica a permissão mais estreita.
    """
    assert cliente_sem_cadastros.get("/api/referencias").status_code == 200
    assert criar(cliente_sem_cadastros, assuntos).status_code == 403


# -- o caminho até a agenda ----------------------------------------------------


def test_o_material_guarda_de_qual_referencia_veio(cliente, semente, assuntos, guardados):
    """O degrau que liga a biblioteca à reunião.

    Sem `referencia_id`, a agenda teria um título solto e a tela não saberia
    distinguir o que a biblioteca trouxe do que a pessoa escreveu.
    """
    referencia = criar(cliente, assuntos).json()

    criada = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            materiais=[
                {
                    "momento": "apoio",
                    "titulo": referencia["titulo"],
                    "url": "https://exemplo/apoio.pdf",
                    "referencia_id": referencia["id"],
                }
            ],
        ),
    )
    assert criada.status_code == 201, criada.text

    lida = cliente.get(f"/api/interacoes/{criada.json()['id']}").json()
    assert lida["materiais"][0]["referencia_id"] == referencia["id"]


def test_apagar_a_referencia_nao_apaga_o_material_da_reuniao(
    cliente, semente, assuntos, sessao, guardados
):
    """`on delete set null`, e não `cascade`.

    O registro do que circulou naquele dia é da agenda, não da biblioteca: uma
    limpeza no acervo não pode reescrever o histórico de uma reunião que houve.
    """
    referencia = criar(cliente, assuntos).json()
    criada = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            materiais=[
                {
                    "momento": "apoio",
                    "titulo": referencia["titulo"],
                    "url": "https://exemplo/apoio.pdf",
                    "referencia_id": referencia["id"],
                }
            ],
        ),
    ).json()

    sessao.delete(sessao.get(Referencia, referencia["id"]))
    sessao.flush()

    lida = cliente.get(f"/api/interacoes/{criada['id']}").json()
    assert len(lida["materiais"]) == 1, "o material sobreviveu à referência"
    assert lida["materiais"][0]["referencia_id"] is None
