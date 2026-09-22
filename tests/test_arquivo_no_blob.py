"""O caminho no blob, e o que se recusa na porta.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
Nada aqui toca no banco nem no armazenamento: são as decisões que o upload toma
ANTES de gravar qualquer coisa. Justamente por serem baratas, elas são as que
ninguém testa — e são as que, erradas, deixam dois arquivos ocupando o mesmo
caminho ou um vídeo de 800 MB atravessando a rede antes de ser recusado.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.armazenamento import blob
from app.dominio.erros import RegraViolada

# -- a pasta da consulta: por mês, por quem mandou -----------------------------


def test_a_consulta_agrupa_por_mes_e_por_instituicao():
    """A vistoria do contêiner é por PERÍODO: um movimento de mercado acontece
    numa janela de semanas, e é assim que alguém procura — "o que o mercado
    mandou em setembro", e não "o que tem na agenda 8f3c…"."""
    consulta = uuid4()
    caminho = blob.caminho_da_consulta(
        data=date(2026, 9, 13),
        instituicao="Banco Interamericano S.A.",
        consulta_id=consulta,
        arquivo_id=uuid4(),
        nome="Questionário anual.pdf",
    )

    # O ponto final some: `_sem_acento_nem_surpresa` apara pontos e hifens das
    # pontas, e pasta terminada em ponto é armadilha no Windows.
    assert caminho.startswith("consultas/2026-09/banco-interamericano-s.a/")
    assert f"/2026-09-13-{consulta}/" in caminho
    assert caminho.endswith("-Questionario-anual.pdf")


def test_duas_consultas_do_mesmo_banco_no_mesmo_dia_ficam_em_pastas_diferentes():
    """Uma pasta por CONSULTA: juntá-las faria parecer que o anexo da segunda
    é da primeira. O id inteiro no nome é o que garante — um prefixo dele
    deixaria de ser garantia e viraria probabilidade."""
    argumentos = dict(
        data=date(2026, 9, 13),
        instituicao="Banco X",
        arquivo_id=uuid4(),
        nome="anexo.pdf",
    )
    um = blob.caminho_da_consulta(consulta_id=uuid4(), **argumentos)
    outro = blob.caminho_da_consulta(consulta_id=uuid4(), **argumentos)

    assert um.rsplit("/", 1)[0] != outro.rsplit("/", 1)[0]


def test_a_data_comeca_o_nome_da_pasta_para_a_ordem_ser_cronologica():
    """Ordenação alfabética do Storage Explorer = ordem do tempo."""
    pastas = [
        blob.caminho_da_consulta(
            data=data,
            instituicao="Banco X",
            consulta_id=uuid4(),
            arquivo_id=uuid4(),
            nome="anexo.pdf",
        ).rsplit("/", 2)[1]
        for data in (date(2026, 9, 2), date(2026, 9, 13), date(2026, 9, 9))
    ]

    assert sorted(pastas) == [pastas[0], pastas[2], pastas[1]]


def test_instituicao_sem_nome_usavel_ainda_produz_caminho():
    """O byte não pode ficar sem casa porque um cadastro tem nome estranho."""
    caminho = blob.caminho_da_consulta(
        data=date(2026, 9, 13),
        instituicao="???",
        consulta_id=uuid4(),
        arquivo_id=uuid4(),
        nome="anexo.pdf",
    )
    assert caminho.startswith("consultas/2026-09/arquivo/")


# -- a pasta é a agenda --------------------------------------------------------


def test_o_caminho_agrupa_por_agenda_e_por_momento():
    """É isto que dá a ligação única entre pasta e materiais.

    Olhando o contêiner, dá para dizer a qual agenda um arquivo pertence sem
    consultar o banco.
    """
    agenda = uuid4()
    caminho = blob.caminho_do_arquivo(
        interacao_id=agenda, momento="apoio", arquivo_id=uuid4(), nome="Nota.pdf"
    )

    assert caminho.startswith(f"interacoes/{agenda}/apoio/")


def test_dois_arquivos_de_mesmo_nome_nao_se_sobrescrevem():
    """O `arquivo_id` no caminho é o que separa um do outro.

    Sem ele, subir "Ata.pdf" duas vezes na mesma agenda faria o segundo ocupar
    o caminho do primeiro — e as duas linhas do banco apontariam para o mesmo
    byte, cada uma achando que é dona.
    """
    comuns = {"interacao_id": uuid4(), "momento": "apoio", "nome": "Ata.pdf"}

    primeiro = blob.caminho_do_arquivo(arquivo_id=uuid4(), **comuns)
    segundo = blob.caminho_do_arquivo(arquivo_id=uuid4(), **comuns)

    assert primeiro != segundo


def test_o_nome_perde_acento_espaco_e_parentese():
    """Nome do mundo real não vira caminho sem tradução.

    Barra inventaria uma pasta que ninguém pediu; acento e espaço viram escape
    na URL e transformam a leitura do contêiner em decodificação.
    """
    caminho = blob.caminho_do_arquivo(
        interacao_id=uuid4(),
        momento="apoio",
        arquivo_id=uuid4(),
        nome="Nota técnica ANA (v2) — final.pdf",
    )

    final = caminho.rsplit("/", 1)[-1]
    assert "técnica" not in final
    assert " " not in final
    assert final.endswith(".pdf")


def test_nome_que_vira_nada_ainda_produz_um_caminho():
    """Um nome só de caracteres impróprios não pode gerar caminho vazio.

    Caminho terminado em `/` é uma pasta, não um arquivo, e o armazenamento
    aceitaria — com o byte alcançável por um caminho que ninguém consegue
    escrever de volta.
    """
    caminho = blob.caminho_do_arquivo(
        interacao_id=uuid4(), momento="apoio", arquivo_id=uuid4(), nome="中文.pdf"
    )

    assert not caminho.endswith("/")
    assert caminho.rsplit("/", 1)[-1].strip()


# -- o que se recusa antes de gastar rede --------------------------------------


def test_tipo_fora_da_lista_e_recusado_dizendo_o_que_serve():
    """A mensagem lista os aceitos.

    "Tipo não permitido" manda a pessoa adivinhar; dizer quais servem resolve
    na primeira tentativa.
    """
    with pytest.raises(RegraViolada) as erro:
        blob.exigir_tipo_aceito("application/x-msdownload")

    assert "pdf" in str(erro.value)


def test_o_pdf_passa():
    blob.exigir_tipo_aceito("application/pdf")


def test_arquivo_vazio_e_recusado():
    with pytest.raises(RegraViolada, match="vazio"):
        blob.exigir_tamanho_aceito(0)


def test_acima_do_limite_e_recusado_com_o_tamanho_na_mensagem():
    """Saber que passou não basta: a pessoa precisa saber por quanto."""
    with pytest.raises(RegraViolada) as erro:
        blob.exigir_tamanho_aceito(80 * 1024 * 1024)

    mensagem = str(erro.value)
    assert "80" in mensagem and "25" in mensagem
    #: E o que fazer a respeito, que é a parte que a pessoa consegue agir.
    assert "link" in mensagem


def test_no_limite_exato_passa():
    """O limite é o maior aceito, e não o menor recusado.

    Um `>=` no lugar do `>` recusaria o arquivo de exatamente 25 MB dizendo que
    o limite é 25 MB — a mensagem contradiria a regra.
    """
    blob.exigir_tamanho_aceito(25 * 1024 * 1024)


# -- o tipo declarado nao vale por si -------------------------------------------
#
# Medido pela API antes de existir esta secao: `programa.exe` enviado com
# `Content-Type: application/pdf` voltou 201 e foi guardado. O `Content-Type` do
# multipart e escrito por QUEM ENVIA, e a lista de permitidos, sozinha, so barra
# quem nao tenta.


def test_exe_com_content_type_de_pdf_e_recusado():
    """O caso exato que a API aceitou. Duas conferencias o barram.

    A extensao nao casa com o tipo declarado — e mesmo que casasse, os
    primeiros bytes nao sao os de um PDF.
    """
    with pytest.raises(RegraViolada):
        blob.exigir_arquivo_coerente(
            "programa.exe", "application/pdf", b"MZ\x90\x00\x03"
        )


def test_exe_renomeado_para_pdf_tambem_e_recusado():
    """Trocar a extensao junto com o tipo nao basta.

    A extensao passa a casar, e e a ASSINATURA que barra: `MZ` e um executavel
    do Windows, nao um PDF.
    """
    with pytest.raises(RegraViolada, match="nao corresponde"):
        blob.exigir_arquivo_coerente(
            "programa.pdf", "application/pdf", b"MZ\x90\x00\x03"
        )


def test_pdf_de_verdade_passa():
    blob.exigir_arquivo_coerente("nota.pdf", "application/pdf", b"%PDF-1.7\n")


def test_pdf_verdadeiro_com_nome_de_executavel_e_recusado():
    """O oposto do disfarce, e igualmente perigoso.

    Um PDF legitimo chamado `relatorio.exe` sai do download com esse nome, e o
    Windows o trata como programa. A conferencia de extensao pega os dois lados.
    """
    with pytest.raises(RegraViolada, match="extensao"):
        blob.exigir_arquivo_coerente("relatorio.exe", "application/pdf", b"%PDF-1.7\n")


def test_jpeg_aceita_as_duas_extensoes_de_uso_corrente():
    """`.jpg` e `.jpeg` sao o mesmo formato. Recusar uma seria armadilha."""
    for nome in ("foto.jpg", "foto.jpeg"):
        blob.exigir_arquivo_coerente(nome, "image/jpeg", b"\xff\xd8\xff\xe0")


def test_texto_simples_nao_tem_assinatura_e_passa_pela_extensao():
    """Inventar assinatura para `.txt` recusaria arquivo legitimo.

    Texto nao tem numero magico. A conferencia que resta e a extensao, e esta
    ausencia esta escrita em `ASSINATURAS` de proposito.
    """
    blob.exigir_arquivo_coerente("notas.txt", "text/plain", b"qualquer coisa")

    with pytest.raises(RegraViolada, match="extensao"):
        blob.exigir_arquivo_coerente("notas.exe", "text/plain", b"qualquer coisa")


# -- a rota do arquivo escapa do teto global de corpo ---------------------------


def test_a_rota_do_arquivo_fica_fora_do_limite_de_corpo():
    """O teto global e 1 MB, e o limite do upload e 25 MB.

    Sem a isencao, um PDF de 2 MB leva `413` do middleware, com mensagem
    generica, antes de a rota rodar — e o limite de 25 MB fica inalcancavel.

    O conserto NAO foi subir o teto global: isso abriria todas as rotas a
    corpos de 25 MB para consertar uma.
    """
    from app.seguranca.protecao_http import _fora_do_limite_de_corpo

    assert _fora_do_limite_de_corpo(
        "/api/interacoes/af190c19-b11d-4711-88a8-741bbf8f9816/materiais/arquivo"
    )


def test_as_demais_rotas_continuam_sob_o_teto():
    """A prova negativa: uma isencao ampla demais desprotegeria o resto.

    Casar por prefixo `/api/interacoes` deixaria o `PATCH` da agenda de fora do
    limite tambem — e ele aceita JSON de qualquer tamanho.
    """
    from app.seguranca.protecao_http import _fora_do_limite_de_corpo

    assert not _fora_do_limite_de_corpo("/api/interacoes")
    assert not _fora_do_limite_de_corpo(
        "/api/interacoes/af190c19-b11d-4711-88a8-741bbf8f9816"
    )
    assert not _fora_do_limite_de_corpo("/api/acessos")


def test_uma_rota_qualquer_terminada_no_mesmo_sufixo_nao_herda_a_isencao():
    """A divida que a versao por sufixo deixava.

    A isencao descreve a rota INTEIRA. Um `endswith("/materiais/arquivo")`
    funcionaria hoje e abriria mao do teto para qualquer rota futura terminada
    assim, sem ninguem decidir isso.
    """
    from app.seguranca.protecao_http import _fora_do_limite_de_corpo

    assert not _fora_do_limite_de_corpo("/api/exportacoes/materiais/arquivo")
    assert not _fora_do_limite_de_corpo("/api/interacoes/nao-e-uuid/materiais/arquivo")
    #: E a rota de DOWNLOAD tambem nao: ela nao recebe corpo.
    assert not _fora_do_limite_de_corpo(
        "/api/interacoes/af190c19-b11d-4711-88a8-741bbf8f9816/materiais/arquivo/"
        "67c10771-4715-4a58-bc1a-5afa26342bf5"
    )


def test_a_biblioteca_tambem_recebe_arquivo_e_tambem_escapa_do_teto():
    """Sao TRES rotas de upload, e nao uma.

    A referencia nasce COM a primeira versao, e cada versao seguinte sobe outro
    arquivo. Faltando a isencao, o middleware recusa com 413 generico ANTES de
    a rota rodar — e a mensagem que diz o tamanho aceito nunca chega a quem
    subiu. O teto delas e o mesmo dos materiais, aplicado por
    `blob.exigir_tamanho_aceito` dentro da rota.
    """
    from app.seguranca.protecao_http import _fora_do_limite_de_corpo

    assert _fora_do_limite_de_corpo("/api/referencias")
    assert _fora_do_limite_de_corpo(
        "/api/referencias/52193002-103b-4a87-8a1d-2a95059ccfc1/versoes"
    )
    #: A LISTAGEM de versoes e a mesma rota no metodo GET, e nao ha como o
    #: middleware distinguir — mas GET sem corpo nao chega perto do teto.
    #:
    #: O DOWNLOAD de uma versao, sim, e outro caminho, e nao escapa:
    assert not _fora_do_limite_de_corpo(
        "/api/referencias/52193002-103b-4a87-8a1d-2a95059ccfc1/versoes/"
        "67c10771-4715-4a58-bc1a-5afa26342bf5/arquivo"
    )
    #: E editar os metadados continua sob o teto de formulario:
    assert not _fora_do_limite_de_corpo(
        "/api/referencias/52193002-103b-4a87-8a1d-2a95059ccfc1"
    )


# -- de onde vem a credencial do Storage ---------------------------------------


def test_endereco_https_autentica_pela_identidade(monkeypatch):
    """No Azure a conta tem a chave de acesso DESLIGADA.

    Não existe cadeia de conexão para montar: quem prova quem somos é a
    identidade do contêiner. Montar `from_connection_string` com um endereço
    `https://` falharia dizendo que a cadeia é inválida — erro que não tem
    relação nenhuma com a causa.
    """
    from app.armazenamento import blob

    chamadas = {}

    class ServicoFalso:
        def __init__(self, account_url=None, credential=None):
            chamadas["account_url"] = account_url
            chamadas["credential"] = credential

        @classmethod
        def from_connection_string(cls, cadeia):
            chamadas["cadeia"] = cadeia
            return cls()

    monkeypatch.setattr(blob, "BlobServiceClient", ServicoFalso)
    monkeypatch.setattr(
        "app.seguranca.identidade_azure.credencial", lambda: "a-identidade"
    )

    blob._servico("https://stpainel.blob.core.windows.net/")

    assert chamadas["account_url"] == "https://stpainel.blob.core.windows.net/"
    assert chamadas["credential"] == "a-identidade"
    assert "cadeia" not in chamadas


def test_cadeia_de_conexao_continua_valendo(monkeypatch):
    """O Azurite só entende cadeia de conexão, e é o que o compose oferece."""
    from app.armazenamento import blob

    chamadas = {}

    class ServicoFalso:
        @classmethod
        def from_connection_string(cls, cadeia):
            chamadas["cadeia"] = cadeia
            return cls()

    monkeypatch.setattr(blob, "BlobServiceClient", ServicoFalso)

    blob._servico("DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;")

    assert chamadas["cadeia"].startswith("DefaultEndpointsProtocol=")
