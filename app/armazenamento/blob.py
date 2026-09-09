"""Os arquivos dos materiais, no Blob Storage.

O mesmo SDK fala com o Azure e com o Azurite: o emulador é o serviço rodando
local, não uma imitação com API própria. Não existe caminho "só de teste" aqui
para divergir do que roda em produção.

A PASTA É A AGENDA
------------------
    interacoes/{interacao_id}/{momento}/{arquivo_id}-{nome}

Uma agenda, uma pasta; dentro dela, uma subpasta por momento. É isso que dá a
ligação única entre pasta e materiais: olhando o contêiner, dá para dizer a
qual agenda um arquivo pertence sem consultar o banco.

O `arquivo_id` no começo do nome é o que garante unicidade — dois arquivos com
o mesmo nome na mesma agenda não se sobrescrevem. O nome vem junto porque
quem abre o Storage Explorer para conferir precisa reconhecer o que está
vendo, e uma pasta de uuids não se lê.
"""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

from app.configuracao import obter_configuracao
from app.dominio.erros import NaoEncontrado, RegraViolada

#: O que se aceita subir. Lista de PERMITIDOS, e não de proibidos: uma lista de
#: proibidos precisa acertar todos os casos, e uma de permitidos só precisa
#: acertar os que existem.
#:
#: Sem antivírus por trás — ver o fim da migration 0012. A lista reduz a
#: superfície, não a elimina.
TIPOS_ACEITOS: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "text/csv": ".csv",
}


#: O que os primeiros bytes de cada formato dizem sobre ele.
#:
#: `.docx`, `.xlsx` e `.pptx` sao ZIP, e por isso caem todos na mesma
#: assinatura. Isso NAO distingue um `.docx` de um `.zip` qualquer: distinguir
#: exigiria abrir o pacote e conferir o `[Content_Types].xml`. O que esta
#: conferencia barra e o caso que importa aqui: um executavel renomeado.
#:
#: `.txt` e `.csv` NAO entram: texto simples nao tem assinatura, e inventar uma
#: recusaria arquivo legitimo. Para eles vale so a extensao.
ASSINATURAS: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
    #: Formato composto do Office antigo (OLE2).
    ".doc": (b"\xd0\xcf\x11\xe0",),
    ".xls": (b"\xd0\xcf\x11\xe0",),
    ".ppt": (b"\xd0\xcf\x11\xe0",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
}



def exigir_arquivo_coerente(nome: str, tipo_conteudo: str, dados: bytes) -> None:
    """O NOME E OS BYTES precisam concordar com o tipo declarado.

    O `Content-Type` do multipart e escrito por QUEM ENVIA. Medido pela API:
    `programa.exe` renomeado com `Content-Type: application/pdf` era aceito e
    guardado — a lista de tipos permitidos, sozinha, so barra quem nao tenta.

    Duas conferencias, porque nenhuma basta:

      1. A EXTENSAO precisa casar com o tipo declarado. Barra o renomeado
         simples, e barra tambem o oposto: um PDF de verdade chamado
         `relatorio.exe`, que o Windows abriria como programa.
      2. Os PRIMEIROS BYTES precisam ser os do formato. Barra quem troca a
         extensao junto com o `Content-Type`.

    Nao substitui antivirus — ver o fim da migration 0012. Um `.docx` legitimo
    com macro maliciosa passa por aqui inteiro.
    """
    esperada = TIPOS_ACEITOS[tipo_conteudo]
    #: `.jpg` e `.jpeg` sao o mesmo formato com dois nomes de uso corrente.
    aceitas = {esperada, ".jpeg"} if esperada == ".jpg" else {esperada}
    if not any(nome.lower().endswith(ext) for ext in aceitas):
        raise RegraViolada(
            f"O nome do arquivo termina em algo diferente de {esperada}, "
            f"mas ele foi enviado como {tipo_conteudo}. Renomeie o arquivo com "
            "a extensao certa e tente de novo."
        )

    assinaturas = ASSINATURAS.get(esperada)
    if assinaturas and not any(dados.startswith(a) for a in assinaturas):
        raise RegraViolada(
            "O conteudo do arquivo nao corresponde a um "
            f"{esperada.lstrip('.').upper()}. Confira se ele nao foi renomeado."
        )


def exigir_tipo_aceito(tipo_conteudo: str) -> None:
    """Recusa na porta o que não se guarda.

    A mensagem lista o que serve. "Tipo de arquivo não permitido" manda a
    pessoa adivinhar; dizer quais servem resolve a dúvida na primeira tentativa.
    """
    if tipo_conteudo not in TIPOS_ACEITOS:
        aceitos = ", ".join(sorted({e.lstrip(".") for e in TIPOS_ACEITOS.values()}))
        raise RegraViolada(
            f"Não guardamos arquivos do tipo {tipo_conteudo!r}. "
            f"Aceitos: {aceitos}."
        )


def exigir_tamanho_aceito(tamanho: int) -> None:
    configuracao = obter_configuracao()
    if tamanho <= 0:
        raise RegraViolada("O arquivo está vazio.")
    if tamanho > configuracao.blob_tamanho_maximo:
        limite = configuracao.blob_tamanho_maximo // (1024 * 1024)
        atual = tamanho / (1024 * 1024)
        raise RegraViolada(
            f"O arquivo tem {atual:.1f} MB e o limite é {limite} MB. "
            "Para algo maior, registre o material por link."
        )


def _sem_acento_nem_surpresa(nome: str) -> str:
    """Um nome de arquivo que sobrevive a virar caminho.

    Nome do mundo real traz acento, espaço, barra, parêntese e emoji. Barra
    inventaria uma pasta que ninguém pediu; o resto vira escape na URL e
    transforma a leitura do contêiner num exercício de decodificação.
    """
    limpo = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "-", limpo).strip("-.")
    #: Caminho de blob tem limite, e nome longo não acrescenta informação
    #: depois de certo ponto — o `arquivo_id` já identifica.
    return (limpo or "arquivo")[:80]


def caminho_do_arquivo(
    *, interacao_id: UUID, momento: str, arquivo_id: UUID, nome: str
) -> str:
    """Onde o arquivo de uma AGENDA nasce. Ver o cabeçalho do módulo."""
    return f"interacoes/{interacao_id}/{momento}/{arquivo_id}-{_sem_acento_nem_surpresa(nome)}"


def caminho_da_referencia(
    *, assunto: str, tipo: str, titulo: str, numero: int, arquivo_id: UUID, nome: str
) -> str:
    """Onde uma versão da biblioteca nasce.

        referencias/<assunto principal>/<tipo>/<referência>/v<n>-<id>-<nome>

    A ÁRVORE É NAVEGÁVEL POR GENTE. Quem abrir o contêiner encontra o acervo
    organizado como a cabeça organiza — por assunto, depois por tipo de
    documento —, e as versões de uma referência ficam lado a lado, na ordem.

    O ASSUNTO É O PRINCIPAL, e um só. A referência pode cobrir vários, e
    `referencia_tema` guarda todos; o byte mora num lugar. Copiá-lo para cada
    assunto criaria duas verdades que envelhecem separado.

    O `arquivo_id` continua no nome porque `guardar` grava com
    `overwrite=False`: é ele que garante caminho novo a cada versão, mesmo que
    duas subam com o mesmo nome de arquivo.
    """
    return (
        f"referencias/{_sem_acento_nem_surpresa(assunto).lower()}"
        f"/{_sem_acento_nem_surpresa(tipo).lower()}"
        f"/{_sem_acento_nem_surpresa(titulo).lower()}"
        f"/v{numero}-{arquivo_id}-{_sem_acento_nem_surpresa(nome)}"
    )


def _contenedor():
    configuracao = obter_configuracao()
    if not configuracao.blob_ligado:
        #: 503, e não 500: o armazenamento não estar configurado é um estado
        #: previsto — o painel inteiro funciona sem ele, com material por link.
        raise ArmazenamentoDesligado(
            "O armazenamento de arquivos não está configurado neste ambiente. "
            "Registre o material por link, ou fale com quem administra."
        )
    servico = BlobServiceClient.from_connection_string(configuracao.blob_url)
    contenedor = servico.get_container_client(configuracao.blob_contenedor)
    try:
        #: PRIVADO por padrão (sem `public_access`). Um contêiner público
        #: exporia por URL adivinhável o material de agenda com governo e
        #: investidores — o conteúdo mais sensível deste painel.
        contenedor.create_container()
    except ResourceExistsError:
        pass
    return contenedor


class ArmazenamentoDesligado(RuntimeError):
    """O Blob não está configurado. Estado previsto, não defeito."""


def guardar(caminho: str, dados: bytes, tipo_conteudo: str) -> None:
    _contenedor().upload_blob(
        name=caminho,
        data=dados,
        #: `overwrite=False` de propósito. O caminho carrega um uuid novo a cada
        #: upload, então colisão aqui não é "salvar de novo" — é defeito, e
        #: falhar alto é melhor do que sobrescrever o arquivo de outra pessoa.
        overwrite=False,
        content_settings=ContentSettings(content_type=tipo_conteudo),
    )


def ler(caminho: str) -> bytes:
    try:
        return _contenedor().download_blob(caminho).readall()
    except ResourceNotFoundError as erro:
        #: A linha existe e o byte não. Acontece se alguém apagar pelo Storage
        #: Explorer. 404 com esta mensagem diz o que houve; 500 mandaria
        #: procurar defeito onde há dado faltando.
        raise NaoEncontrado(
            "O arquivo deste material não está mais no armazenamento."
        ) from erro


def apagar(caminho: str) -> None:
    """Apaga o byte. Some sem reclamar se ele já não estiver lá.

    Chamada DEPOIS do commit, nunca dentro dele: se a transação voltar atrás
    com o byte já apagado, a linha ressuscita apontando para o vazio. Na ordem
    certa, o pior caso é um byte órfão no contêiner — que não quebra nada e a
    política de retenção varrerá quando existir.
    """
    try:
        _contenedor().delete_blob(caminho)
    except ResourceNotFoundError:
        pass
