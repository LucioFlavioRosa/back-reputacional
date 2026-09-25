"""Rotas HTTP das interações.

A camada mais fina do contexto: monta o Recorte, chama o caso de uso, serializa
a resposta. Nenhuma regra de negócio mora aqui.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.dependencias import (
    UsuarioLogado,
    UsuarioQueEscreve,
    exigir_portal_crm,
)
from app.armazenamento import blob
from app.banco.repositorio_interacoes import (
    RepositorioSQL,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import consultar_interacoes, editar_interacao, registrar_interacao
from app.casos_de_uso.consulta_recebida import validar_consulta
from app.casos_de_uso.derivar_esfera import derivar_esfera
from app.casos_de_uso.derivar_frente import derivar_frente
from app.dominio.erros import RegraViolada
from app.dominio.interacao import MOMENTOS_DE_MATERIAL
from app.dominio.recorte import Recorte
from app.esquemas.interacoes import (
    ArquivoSaida,
    InteracaoEdicao,
    InteracaoEntrada,
    InteracaoSaida,
    PaginaDeInteracoes,
)

# A autenticação é dependência do router inteiro: nenhuma rota daqui é pública.
# As rotas de leitura também recebem `UsuarioLogado` — não por redundância, mas
# porque precisam do escopo e da permissão de ver campos sensíveis. O FastAPI
# resolve a dependência uma vez por requisição e reaproveita.
rotas = APIRouter(
    prefix="/api/interacoes",
    tags=["interacoes"],
    # `obter_usuario_atual` já encadeia provisionamento, limite de taxa e
    # autorização, nessa ordem. Uma dependência só, resolvida uma vez por
    # requisição.
    # `exigir_portal_crm`, e não `obter_usuario_atual`: estas rotas são do CRM
    # dos Stakeholders, e quem não abre esse portal não as alcança.
    #
    # Fica no APIRouter, e não em cada rota: uma rota nova nasce protegida em
    # vez de depender de alguém lembrar. `exigir_portal_crm` já resolve o
    # usuário, então nada se perde.
    dependencies=[Depends(exigir_portal_crm)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido


def obter_recorte(
    periodo: Annotated[
        str | None,
        Query(
            description=(
                "ultimos-30 | ultimos-60 | ultimos-90 | ultimos-180 | ultimos-360 | "
                "proximos-30 | proximos-60 | proximos-90 | proximos-180 | proximos-360"
            )
        ),
    ] = None,
    de: Annotated[date | None, Query()] = None,
    ate: Annotated[date | None, Query()] = None,
    frente: Annotated[str | None, Query()] = None,
    area: Annotated[
        str | None,
        Query(deprecated=True, description="apelido de `frente`"),
    ] = None,
    unidade: Annotated[str | None, Query()] = None,
    uf: Annotated[
        str | None,
        Query(description="sigla, NA (nacional) ou IN (internacional)"),
    ] = None,
    esfera: Annotated[str | None, Query()] = None,
    # Sem `le`: quantos níveis existem é o que estiver em `relevancia`, e
    # um teto aqui voltaria a ser uma cópia que envelhece sozinha.
    tier: Annotated[int | None, Query(ge=1)] = None,
    clima: Annotated[str | None, Query(description="clima registrado depois da interação")] = None,
    clima_esperado: Annotated[
        str | None,
        Query(alias="climaEsperado", description="clima esperado ao marcar a interação"),
    ] = None,
    resultado: Annotated[str | None, Query()] = None,
    status_: Annotated[
        str | None,
        Query(alias="status", description="código de um status específico"),
    ] = None,
    grupo: Annotated[str | None, Query(description="resolvido | aberto | declinado")] = None,
    entidade: Annotated[str | None, Query(description="id ou nome exato da instituição")] = None,
    subtipo: Annotated[str | None, Query(description="tipo de investidor")] = None,
    porta_voz: Annotated[UUID | None, Query(alias="portaVoz")] = None,
    pessoa: Annotated[UUID | None, Query()] = None,
    alegacao: Annotated[
        UUID | None,
        Query(description="id de uma alegação; traz as consultas que a trouxeram"),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Query(
            description="repetido — tags=a&tags=b; OR entre elas. Um nome de tema pode ter vírgula."
        ),
    ] = None,
    areas: Annotated[
        str | None,
        Query(description="ids de área interna, separados por vírgula; OR entre elas"),
    ] = None,
    formatos_interacao: Annotated[
        str | None,
        Query(
            alias="formatoInteracao",
            description="ids de formato de interação, separados por vírgula; OR entre eles",
        ),
    ] = None,
    categorias_publico: Annotated[
        str | None,
        Query(
            alias="categoriaPublico",
            description="ids de categoria de público da instituição, separados por vírgula",
        ),
    ] = None,
    q: Annotated[str | None, Query(description="busca livre")] = None,
) -> Recorte:
    """Monta o Recorte a partir da query string.

    É a única porta de entrada dos filtros: qualquer rota que precise deles
    declara esta dependência, e todas passam a aceitar exatamente o mesmo
    conjunto — que é o requisito do contrato da API.
    """
    return Recorte.construir(
        periodo=periodo,
        de=de,
        ate=ate,
        frente=frente or area,
        unidade=unidade,
        uf=uf.upper() if uf else None,
        esfera=esfera,
        tier=tier,
        clima=clima,
        clima_esperado=clima_esperado,
        resultado=resultado,
        status=status_,
        grupo_status=grupo,
        entidade=entidade,
        subtipo=subtipo,
        porta_voz=porta_voz,
        pessoa=pessoa,
        alegacao=alegacao,
        tags=tags,
        areas=areas,
        formatos_interacao=formatos_interacao,
        categorias_publico=categorias_publico,
        busca=q,
    )


RecorteAtual = Annotated[Recorte, Depends(obter_recorte)]


@rotas.get("")
def listar(
    sessao: Sessao,
    usuario: UsuarioLogado,
    recorte: RecorteAtual,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=200)] = 50,
    ordenacao: Annotated[
        str, Query(description="campo, com '-' para descendente")
    ] = "-data_interacao",
) -> PaginaDeInteracoes:
    """A base de registros do recorte corrente."""
    resultado = consultar_interacoes.listar(
        RepositorioSQL(sessao),
        recorte=recorte,
        escopo=usuario.escopo,
        busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
        pagina=pagina,
        tamanho=tamanho,
        ordenacao=ordenacao,
    )
    return PaginaDeInteracoes(
        itens=[
            InteracaoSaida.de_dominio(i, ve_campos_sensiveis=usuario.ve_campos_sensiveis)
            for i in resultado.itens
        ],
        total=resultado.total,
        pagina=resultado.pagina,
        tamanho=resultado.tamanho,
        paginas=resultado.paginas,
        filtros_ativos=recorte.quantidade_de_filtros,
    )


@rotas.post("", status_code=status.HTTP_201_CREATED)
def criar(
    sessao: Sessao, usuario: UsuarioQueEscreve, entrada: InteracaoEntrada
) -> InteracaoSaida:
    # QUEM MANDOU `frente` EXPLÍCITO É RESPEITADO — retrocompatível com o
    # cliente antigo (que ainda escolhe a Frente na tela) e com quem sabe
    # exatamente o que quer. Só deriva quando o campo vem ausente.
    frente = entrada.frente or derivar_frente(
        sessao,
        instituicao_id=entrada.instituicao_id,
        formato_interacao_id=entrada.formato_interacao_id,
    )
    # A ESFERA SEGUE A MESMA REGRA, e pelo mesmo motivo: a tela deixou de
    # perguntá-la, e quatro leituras continuaram dependendo dela. Derivar é o
    # único caminho em que a esfera da agenda não pode contradizer o cadastro do
    # órgão — ver `casos_de_uso/derivar_esfera.py`.
    esfera_id = entrada.esfera_id or derivar_esfera(
        sessao, instituicao_id=entrada.instituicao_id
    )
    interacao = entrada.para_dominio(frente=frente, esfera_id=esfera_id)
    # O BLOCO DA CONSULTA SÓ VALE NO TIPO CERTO, e quem garante é o servidor:
    # a tela já manda coerente, mas a API aceita um cliente direto.
    validar_consulta(sessao, interacao)
    criada = registrar_interacao.registrar(
        RepositorioSQL(sessao), interacao=interacao, usuario=usuario
    )
    return InteracaoSaida.de_dominio(criada, ve_campos_sensiveis=usuario.ve_campos_sensiveis)


@rotas.get("/{id}")
def obter(sessao: Sessao, usuario: UsuarioLogado, id: UUID) -> InteracaoSaida:
    """A ficha do registro."""
    interacao = consultar_interacoes.obter(
        RepositorioSQL(sessao), id=id, escopo=usuario.escopo
    )
    return InteracaoSaida.de_dominio(interacao, ve_campos_sensiveis=usuario.ve_campos_sensiveis)


@rotas.patch("/{id}")
def editar(
    sessao: Sessao,
    usuario: UsuarioQueEscreve,
    id: UUID,
    edicao: InteracaoEdicao,
    tarefas: BackgroundTasks,
) -> InteracaoSaida:
    repositorio = RepositorioSQL(sessao)

    atual = consultar_interacoes.obter(repositorio, id=id, escopo=usuario.escopo)
    alteracoes = edicao.alteracoes(frente_atual=atual.frente)

    # A ESFERA SEGUE A INSTITUIÇÃO TAMBÉM NA TROCA, e não só no dia em que a
    # agenda nasce. Derivar apenas na criação deixava o registro com a esfera do
    # órgão ANTERIOR depois de uma correção — federal numa agenda que passou a
    # ser com uma secretaria estadual —, e o erro seria invisível justamente
    # porque ninguém digita a esfera: não há campo na tela para conferir.
    #
    # SÓ QUANDO O CAMPO NÃO VEIO, o mesmo contrato da criação: quem manda a
    # esfera de propósito é respeitado.
    if "instituicao_id" in alteracoes and "esfera_id" not in alteracoes:
        alteracoes["esfera_id"] = derivar_esfera(
            sessao, instituicao_id=alteracoes["instituicao_id"]
        )

    atualizada = editar_interacao.editar(
        repositorio, sessao, id=id, alteracoes=alteracoes, usuario=usuario
    )
    # DEPOIS DE APLICAR, e não antes: o `PATCH` altera um campo de cada vez, e
    # a invariante é sobre o ESTADO FINAL. Trocar só o tipo, sem tocar no
    # bloco, é exatamente o caso que precisa ser recusado — e a recusa desfaz
    # a transação inteira, como qualquer `RegraViolada`.
    validar_consulta(sessao, atualizada)

    # O BYTE SO SOME DEPOIS DO COMMIT, e por isso vai como tarefa de fundo.
    #
    # O commit desta requisicao roda no teardown da dependencia da sessao,
    # quando esta funcao ja retornou — apagar aqui seria apagar ANTES, e um
    # rollback depois devolveria a linha apontando para o vazio. Tarefa de
    # fundo corre depois da resposta, que e depois do commit.
    #
    # `caminhos_orfaos()` so le uma lista em memoria: nao toca na sessao, que
    # a essa altura ja esta fechada.
    tarefas.add_task(registrar_interacao.apagar_bytes_orfaos, repositorio)
    return InteracaoSaida.de_dominio(atualizada, ve_campos_sensiveis=usuario.ve_campos_sensiveis)


@rotas.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def arquivar(sessao: Sessao, usuario: UsuarioQueEscreve, id: UUID) -> None:
    """Soft delete: sai das consultas, permanece no banco."""
    editar_interacao.arquivar(RepositorioSQL(sessao), sessao, id=id, usuario=usuario)


# -- os arquivos dos materiais ------------------------------------------------
#
# O UPLOAD VEM ANTES DO MATERIAL EXISTIR, e é por isso que ele tem rota própria
# em vez de entrar no corpo do `PATCH`.
#
# Quem preenche o formulário acrescenta a linha do material, escolhe o arquivo e
# só depois salva a agenda. Nesse instante o material ainda não tem `id` — não
# existe no servidor. A rota guarda o byte, devolve um `arquivo_id`, e o `PATCH`
# seguinte amarra os dois.
#
# O preço disso é um arquivo órfão quando alguém sobe e desiste de salvar. É o
# lado certo do erro: o contrário — exigir salvar antes de subir — obrigaria a
# gravar uma agenda pela metade só para poder anexar.


@rotas.post("/{id}/materiais/arquivo", status_code=status.HTTP_201_CREATED)
def subir_arquivo_de_material(
    sessao: Sessao,
    usuario: UsuarioQueEscreve,
    id: UUID,
    momento: Annotated[str, Form()],
    arquivo: Annotated[UploadFile, File()],
) -> ArquivoSaida:
    """Guarda o byte e devolve o `arquivo_id` que o material vai citar."""
    repositorio = RepositorioSQL(sessao)
    # O ESCOPO ENTRA AQUI TAMBÉM. Sem isto, quem não enxerga uma agenda poderia
    # escrever no armazenamento dela conhecendo só o id — e a pasta é o que dá
    # a ligação entre arquivo e agenda.
    interacao = consultar_interacoes.obter(repositorio, id=id, escopo=usuario.escopo)

    if momento not in MOMENTOS_DE_MATERIAL:
        raise RegraViolada(
            f"Momento inválido: {momento!r}. Use {', '.join(MOMENTOS_DE_MATERIAL)}."
        )

    dados = arquivo.file.read()
    blob.exigir_tipo_aceito(arquivo.content_type or "")
    # O `Content-Type` do multipart e escrito por quem envia, e a lista de
    # permitidos sozinha so barra quem nao tenta: sem a conferencia abaixo, um
    # `programa.exe` com `Content-Type: application/pdf` entra e fica guardado.
    blob.exigir_arquivo_coerente(
        arquivo.filename or "", arquivo.content_type or "", dados
    )
    blob.exigir_tamanho_aceito(len(dados))

    salvo = registrar_interacao.guardar_arquivo(
        repositorio,
        sessao,
        interacao=interacao,
        momento=momento,
        nome=arquivo.filename or "arquivo",
        tipo_conteudo=arquivo.content_type or "application/octet-stream",
        dados=dados,
        usuario=usuario,
    )
    return ArquivoSaida(
        id=salvo.id,
        nome=salvo.nome,
        tipo_conteudo=salvo.tipo_conteudo,
        tamanho=salvo.tamanho,
    )


@rotas.get("/{id}/materiais/arquivo/{arquivo_id}")
def baixar_arquivo_de_material(
    sessao: Sessao, usuario: UsuarioLogado, id: UUID, arquivo_id: UUID
) -> Response:
    """Entrega o byte, pela API e não por link direto ao blob.

    Um SAS seria mais rápido e tiraria a API do caminho do download. Mas o
    material de agenda com governo e investidores é o conteúdo mais sensível
    deste painel, e um link de blob que vaza continua valendo depois de a
    pessoa perder o acesso. Passando por aqui, a autorização é verificada a
    cada download.
    """
    repositorio = RepositorioSQL(sessao)
    consultar_interacoes.obter(repositorio, id=id, escopo=usuario.escopo)

    registro = registrar_interacao.arquivo_da_interacao(
        repositorio, interacao_id=id, arquivo_id=arquivo_id
    )
    return Response(
        content=blob.ler(registro.caminho),
        media_type=registro.tipo_conteudo,
        headers={
            # `attachment` com o nome ORIGINAL: quem baixa espera reencontrar
            # "Nota técnica ANA.pdf", e não o uuid que serve ao armazenamento.
            "Content-Disposition": (
                f'attachment; filename*=UTF-8\'\'{quote(registro.nome)}'
            )
        },
    )
