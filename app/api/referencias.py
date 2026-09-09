"""A biblioteca de referências: o acervo oficial, por assunto e por versão.

Existe para o porta-voz não entrar numa reunião de tarifa sem o Q&A de tarifa —
ou com a versão de março. A referência é ligada a ASSUNTO porque assunto é o
que se escolhe ao marcar uma agenda, e é por ele que o material certo se
encontra sozinho.

O ARQUIVO MORA NO BLOB, numa árvore navegável por gente:

    referencias/<assunto principal>/<tipo>/<referência>/v<n>-<id>-<nome>

E UMA REFERÊNCIA TEM VERSÕES. Subir a de agosto não apaga a de março: foi a de
março que circulou naquela reunião, e é ela que responde quando alguém pergunta
o que a gente levou.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencias import (
    UsuarioLogado,
    UsuarioQueAdministraCadastros,
    exigir_portal_crm,
)
from app.armazenamento import blob
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_interacoes import Arquivo
from app.banco.tabelas_referencias import Referencia, ReferenciaTema, ReferenciaVersao
from app.dominio.erros import NaoEncontrado, RegraViolada

rotas = APIRouter(
    prefix="/api/referencias",
    tags=["referencias"],
    dependencies=[Depends(exigir_portal_crm)],
)

Sessao = SessaoDoPedido

#: O que o documento É — e não do que ele trata, que são os tópicos.
#:
#: Fechado, e não texto livre, pelo mesmo motivo do resto dos dicionários: seis
#: grafias de "Q&A" não se somam e não filtram.
TIPOS = ("posicionamento", "qa", "release", "apresentacao", "dados", "nota_tecnica")


class VersaoSaida(BaseModel):
    id: UUID
    numero: int
    atualizado_em: date
    nota: str | None
    arquivo_id: UUID
    arquivo_nome: str
    arquivo_tipo: str
    arquivo_tamanho: int
    criado_em: str
    criado_por: str | None


class ReferenciaSaida(BaseModel):
    id: UUID
    titulo: str
    tipo: str
    resumo: str | None
    #: O assunto que define a pasta no blob.
    tema_principal_id: int | None
    #: Todos os assuntos, o principal incluído.
    temas: list[int]
    ativo: bool
    #: A versão que a tela mostra. Nula só num registro em estado impossível —
    #: a rota de criação grava a linha e a v1 na mesma transação.
    versao: VersaoSaida | None
    #: Quantas versões existem, para a tela oferecer o histórico sem pedi-lo.
    quantas_versoes: int


class ReferenciaEdicao(BaseModel):
    """Os METADADOS. O arquivo entra pelas rotas de versão."""

    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1)
    tipo: str
    resumo: str | None = None
    tema_principal_id: int
    #: Os demais assuntos que esta referência cobre. O principal entra sozinho.
    temas: list[int] = Field(default_factory=list)
    ativo: bool = True


def _conferir_tipo(tipo: str) -> None:
    if tipo not in TIPOS:
        raise RegraViolada(f"Tipo invalido: {tipo!r}. Use {', '.join(TIPOS)}.")


def _conferir_temas(sessao: Session, ids: set[int]) -> None:
    """Os assuntos precisam existir e estar ATIVOS.

    A chave estrangeira recusaria o inexistente com um 500; e ela não recusa o
    desativado — a linha continua na tabela. Conferir aqui faz a API responder
    o mesmo que a tela oferece.
    """
    achados = set(
        sessao.scalars(select(Tema.id).where(Tema.id.in_(ids), Tema.ativo.is_(True))).all()
    )
    if ids - achados:
        faltando = ", ".join(str(i) for i in sorted(ids - achados))
        raise RegraViolada(
            f"Assunto inexistente ou desativado: {faltando}. "
            "Veja os assuntos em uso em /api/dicionarios."
        )


def _aplicar_temas(registro: Referencia, temas: set[int]) -> None:
    """Deixa os vínculos iguais ao pedido, mexendo só no que mudou.

    Apagar todos e reinserir seria mais curto e trocaria a identidade de linhas
    que não mudaram — um `delete`/`insert` por salvamento mesmo quando ninguém
    tocou nos tópicos.
    """
    atuais = {vinculo.tema_id for vinculo in registro.vinculos}
    for vinculo in list(registro.vinculos):
        if vinculo.tema_id not in temas:
            registro.vinculos.remove(vinculo)
    for tema_id in sorted(temas - atuais):
        registro.vinculos.append(ReferenciaTema(tema_id=tema_id))


def _versao_para_saida(versao: ReferenciaVersao, autor: str | None) -> VersaoSaida:
    return VersaoSaida(
        id=versao.id,
        numero=versao.numero,
        atualizado_em=versao.atualizado_em,
        nota=versao.nota,
        arquivo_id=versao.arquivo.id,
        arquivo_nome=versao.arquivo.nome,
        arquivo_tipo=versao.arquivo.tipo_conteudo,
        arquivo_tamanho=versao.arquivo.tamanho,
        criado_em=versao.criado_em.isoformat(),
        criado_por=autor,
    )


def _nomes_de_quem_subiu(sessao: Session, versoes: list[ReferenciaVersao]) -> dict:
    """Os nomes numa consulta só.

    Uma por versão faria a listagem da biblioteca disparar uma dezena de idas
    ao banco para escrever "Ana Lima" ao lado de cada linha.
    """
    from app.banco.tabelas_acesso import Usuario

    ids = {v.criado_por for v in versoes}
    if not ids:
        return {}
    return dict(
        sessao.execute(select(Usuario.id, Usuario.nome).where(Usuario.id.in_(ids))).all()
    )


def _para_saida(registro: Referencia, nomes: dict) -> ReferenciaSaida:
    atual = registro.versao_atual
    return ReferenciaSaida(
        id=registro.id,
        titulo=registro.titulo,
        tipo=registro.tipo,
        resumo=registro.resumo,
        tema_principal_id=registro.tema_principal_id,
        temas=registro.temas,
        ativo=registro.ativo,
        versao=(
            _versao_para_saida(atual, nomes.get(atual.criado_por)) if atual else None
        ),
        quantas_versoes=len(registro.versoes),
    )


def _guardar_versao(
    sessao: Session,
    registro: Referencia,
    *,
    arquivo: UploadFile,
    atualizado_em: date,
    nota: str | None,
    usuario,
) -> ReferenciaVersao:
    """Grava a versão no banco e o byte no blob, nessa ordem.

    AS MESMAS GUARDAS DO UPLOAD DE AGENDA: tipo aceito, coerência entre nome e
    conteúdo, tamanho. O `Content-Type` do multipart é escrito por quem envia —
    sem a conferência de coerência, um `programa.exe` com `Content-Type` de PDF
    entrava e ficava guardado.
    """
    dados = arquivo.file.read()
    blob.exigir_tipo_aceito(arquivo.content_type or "")
    blob.exigir_arquivo_coerente(arquivo.filename or "", arquivo.content_type or "", dados)
    blob.exigir_tamanho_aceito(len(dados))

    assunto = sessao.scalar(
        select(Tema.nome).where(Tema.id == registro.tema_principal_id)
    )

    # A TRAVA NA LINHA DA REFERÊNCIA, ANTES DE CONTAR.
    #
    # Sem o bloqueio, uploads simultâneos na mesma referência leem a mesma
    # versão atual, pedem todos o mesmo número, e o
    # `unique (referencia_id, numero)` derruba todos menos um — com 500
    # genérico na tela e, pior, o byte já gravado no blob.
    #
    # `with_for_update` serializa quem escreve NESTA referência e libera no
    # commit. Duas pessoas subindo versões de referências diferentes não se
    # esperam; duas na mesma entram em fila e recebem números distintos.
    sessao.execute(
        select(Referencia.id).where(Referencia.id == registro.id).with_for_update()
    )
    sessao.refresh(registro, ["versoes"])
    numero = (registro.versao_atual.numero + 1) if registro.versao_atual else 1

    linha = Arquivo(
        caminho="",
        nome=arquivo.filename or "arquivo",
        tipo_conteudo=arquivo.content_type or "application/octet-stream",
        tamanho=len(dados),
        criado_por=usuario.id,
    )
    sessao.add(linha)
    sessao.flush()

    linha.caminho = blob.caminho_da_referencia(
        assunto=assunto or "sem-assunto",
        tipo=registro.tipo,
        titulo=registro.titulo,
        numero=numero,
        arquivo_id=linha.id,
        nome=linha.nome,
    )
    versao = ReferenciaVersao(
        numero=numero,
        arquivo_id=linha.id,
        atualizado_em=atualizado_em,
        nota=nota,
        criado_por=usuario.id,
    )
    registro.versoes.append(versao)

    # A LINHA PRIMEIRO, O BYTE DEPOIS.
    #
    # A ordem inversa parece defensável: se o blob falhasse, a transação não
    # commitaria e não sobraria linha apontando para arquivo inexistente. Mas a
    # falha que acontece na prática é a do BANCO — a numeração recusada por
    # outro escritor —, e nessa ordem o byte já teria ido, órfão, para o
    # contêiner. Com o `flush` antes, o banco recusa antes de escrevermos
    # coisa no armazenamento.
    sessao.flush()
    blob.guardar(linha.caminho, dados, linha.tipo_conteudo)
    return versao


@rotas.get("", response_model=list[ReferenciaSaida])
def listar(sessao: Sessao, usuario: UsuarioLogado) -> list[ReferenciaSaida]:
    """A biblioteca inteira, ativas e inativas.

    AS INATIVAS TAMBÉM, ao contrário do catálogo que alimenta o formulário. Sem
    elas a referência desativada some da tela de administração e reaparece como
    "já existe" na próxima tentativa de cadastrar o mesmo título.
    """
    registros = sessao.scalars(select(Referencia).order_by(Referencia.titulo)).all()
    nomes = _nomes_de_quem_subiu(
        sessao, [v for r in registros for v in r.versoes]
    )
    return [_para_saida(registro, nomes) for registro in registros]


@rotas.post("", response_model=ReferenciaSaida, status_code=status.HTTP_201_CREATED)
def criar(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    titulo: Annotated[str, Form()],
    tipo: Annotated[str, Form()],
    tema_principal_id: Annotated[int, Form()],
    atualizado_em: Annotated[date, Form()],
    arquivo: Annotated[UploadFile, File()],
    resumo: Annotated[str | None, Form()] = None,
    #: Os demais assuntos, separados por vírgula — o multipart não carrega
    #: lista, e um campo repetido complicaria o cliente mais do que resolve.
    temas: Annotated[str, Form()] = "",
    nota: Annotated[str | None, Form()] = None,
) -> ReferenciaSaida:
    """Cadastra a referência COM a primeira versão, numa transação só.

    O ARQUIVO É OBRIGATÓRIO. Uma referência sem ele é um título que não leva a
    lugar nenhum.
    """
    _conferir_tipo(tipo)
    outros = {int(t) for t in temas.split(",") if t.strip()}
    _conferir_temas(sessao, outros | {tema_principal_id})

    registro = Referencia(
        titulo=titulo.strip(),
        tipo=tipo,
        resumo=resumo,
        tema_principal_id=tema_principal_id,
        criado_por=usuario.id,
    )
    _aplicar_temas(registro, outros | {tema_principal_id})
    sessao.add(registro)

    try:
        with sessao.begin_nested():
            sessao.flush()
    except IntegrityError as erro:
        raise RegraViolada(f"Ja existe uma referencia chamada {titulo!r}.") from erro

    _guardar_versao(
        sessao,
        registro,
        arquivo=arquivo,
        atualizado_em=atualizado_em,
        nota=nota,
        usuario=usuario,
    )
    return _para_saida(registro, _nomes_de_quem_subiu(sessao, registro.versoes))


@rotas.put("/{id}", response_model=ReferenciaSaida)
def editar(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    entrada: ReferenciaEdicao,
) -> ReferenciaSaida:
    """Só os metadados. Arquivo novo é VERSÃO nova, e entra pela outra rota."""
    registro = sessao.get(Referencia, id)
    if registro is None:
        raise NaoEncontrado("Referencia nao encontrada.")

    _conferir_tipo(entrada.tipo)
    desejados = set(entrada.temas) | {entrada.tema_principal_id}
    _conferir_temas(sessao, desejados)

    registro.titulo = entrada.titulo.strip()
    registro.tipo = entrada.tipo
    registro.resumo = entrada.resumo
    registro.tema_principal_id = entrada.tema_principal_id
    registro.ativo = entrada.ativo
    _aplicar_temas(registro, desejados)

    try:
        with sessao.begin_nested():
            sessao.flush()
    except IntegrityError as erro:
        raise RegraViolada(
            f"Ja existe uma referencia chamada {entrada.titulo!r}."
        ) from erro

    return _para_saida(registro, _nomes_de_quem_subiu(sessao, registro.versoes))


@rotas.get("/{id}/versoes", response_model=list[VersaoSaida])
def historico(sessao: Sessao, usuario: UsuarioLogado, id: UUID) -> list[VersaoSaida]:
    """Todas as versões, da mais recente para a mais antiga."""
    registro = sessao.get(Referencia, id)
    if registro is None:
        raise NaoEncontrado("Referencia nao encontrada.")
    nomes = _nomes_de_quem_subiu(sessao, registro.versoes)
    return [
        _versao_para_saida(v, nomes.get(v.criado_por))
        for v in sorted(registro.versoes, key=lambda v: v.numero, reverse=True)
    ]


@rotas.post(
    "/{id}/versoes", response_model=ReferenciaSaida, status_code=status.HTTP_201_CREATED
)
def nova_versao(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    atualizado_em: Annotated[date, Form()],
    arquivo: Annotated[UploadFile, File()],
    nota: Annotated[str | None, Form()] = None,
) -> ReferenciaSaida:
    """Acrescenta uma versão. A anterior CONTINUA — é o histórico."""
    registro = sessao.get(Referencia, id)
    if registro is None:
        raise NaoEncontrado("Referencia nao encontrada.")

    _guardar_versao(
        sessao,
        registro,
        arquivo=arquivo,
        atualizado_em=atualizado_em,
        nota=nota,
        usuario=usuario,
    )
    return _para_saida(registro, _nomes_de_quem_subiu(sessao, registro.versoes))


@rotas.get("/{id}/versoes/{versao_id}/arquivo")
def baixar(
    sessao: Sessao, usuario: UsuarioLogado, id: UUID, versao_id: UUID
) -> Response:
    """Entrega o byte, pela API e não por link direto ao blob.

    Um SAS seria mais rápido e tiraria a API do caminho. Mas o acervo diz o que
    a companhia fala publicamente, e um link de blob que vaza continua valendo
    depois de a pessoa perder o acesso. Passando por aqui, a autorização é
    verificada a cada download.
    """
    versao = sessao.get(ReferenciaVersao, versao_id)
    if versao is None or versao.referencia_id != id:
        raise NaoEncontrado("Versao nao encontrada.")

    dados = blob.ler(versao.arquivo.caminho)
    return Response(
        content=dados,
        media_type=versao.arquivo.tipo_conteudo,
        headers={
            # `inline` para o PDF abrir na aba, e `filename` para o download
            # manual sair com o nome que a pessoa reconhece.
            "Content-Disposition": f'inline; filename="{versao.arquivo.nome}"'
        },
    )
