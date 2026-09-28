"""Importação de agendas por planilha: baixar o modelo, subir, conferir.

QUEM IMPORTA É A COORDENAÇÃO — quem já administra os cadastros. A decisão é de
produto e tem razão prática: a importação pode CRIAR instituição e interlocutor,
e quem não pode criar um pela tela de Administração não deveria criar cinquenta
por planilha.

ESCONDER O BOTÃO É CONVENIÊNCIA, NUNCA CONTROLE. A tela só oferece a importação a
quem administra cadastros, e isso não protege nada — um `curl` basta. A guarda é
a dependência do router, e `tests/test_importacoes_api.py` tem a âncora
estrutural que garante que uma rota nova sob este prefixo nasça protegida em vez
de depender de alguém lembrar.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioLogado,
    exigir_administracao_de_cadastros,
    exigir_portal_crm,
)
from app.armazenamento import blob
from app.banco import repositorio_importacao
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import importar_agendas, modelo_de_importacao
from app.dominio.importacao_de_agendas import (
    ABA_PRINCIPAL,
    CHAVE_DO_CORRIGIDO,
    CHAVE_DO_HERDADO,
    CHAVES_RESERVADAS,
    Divergencia,
    aba_de,
    agrupar,
    coluna_do_campo,
    tipo_da_coluna,
)
from app.dominio.texto import normalizar

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: A chave sob a qual o herdado viaja dentro de `dados_brutos`. Começa e termina
#: com dois sublinhados para não colidir com nome de coluna da planilha.
# As chaves reservadas de `dados_brutos` vêm do domínio: quem grava é o caso de
# uso e quem lê é esta rota.

#: O nome que a pessoa vê na pasta de downloads.
NOME_DO_MODELO = "modelo-de-agendas.xlsx"

rotas = APIRouter(
    prefix="/api/importacoes",
    tags=["importacoes"],
    # DUAS dependências, e as duas precisam estar aqui.
    #
    # `exigir_portal_crm` porque estas rotas são do CRM dos Stakeholders, e quem
    # não abre esse portal não as alcança. `exigir_administracao_de_cadastros`
    # porque importar pode criar cadastro em massa — e o modelo que se baixa
    # lista o diretório inteiro, incluindo os interlocutores por nome.
    #
    # Ficam no APIRouter, e não em cada rota: uma rota nova nasce protegida em
    # vez de depender de alguém lembrar.
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_administracao_de_cadastros)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido

Arquivo = Annotated[UploadFile, File(description="A planilha preenchida, em .xlsx")]


class LinhaSaida(BaseModel):
    id: int
    aba: str
    #: A linha NO ARQUIVO, contando o cabeçalho — é por ela que a pessoa volta à
    #: planilha e confere o que digitou.
    linha_origem: int
    decisao: str
    #: A agenda que esta linha virou, depois da confirmação. É o que fecha o laço
    #: entre a planilha e o registro.
    interacao_id: str | None
    dados_brutos: dict
    #: O que a pessoa COMPLETOU na tela, coluna → valor. A tela marca a célula,
    #: porque a partir daí o registro difere da planilha que ela guardou.
    corrigido: dict = {}
    #: O que esta linha herdou da de cima por `idem`, coluna → valor.
    #:
    #: A TELA MOSTRA ISTO porque a herança é invisível na planilha: a célula fica
    #: vazia, e sem este campo a pessoa confirmaria 54 agendas confiando na memória
    #: do que havia acima.
    herdado: dict
    proposta: dict | None
    divergencias: list


class SugestaoSaida(BaseModel):
    """Um nome parecido, com o id que resolve a pendência num clique.

    O NOME SOZINHO NÃO SERVIA. A tela mandava o nome como `alvo`, e o servidor
    valida `alvo` como id ou código — então o atalho PRINCIPAL da conferência
    devolvia 422. A sugestão carrega os dois: o nome que a pessoa reconhece e o
    alvo que o servidor aceita.
    """

    nome: str
    alvo: str


class GrupoSaida(BaseModel):
    """Uma decisão que resolve várias linhas — o bloco "o que precisa de você"."""

    campo: str
    valor: str
    linhas: list[int]
    trava: bool
    sugestoes: list[SugestaoSaida]
    #: Se a importação sabe criar cadastro para este campo. A tela usa isto para
    #: não oferecer "Cadastrar como novo" onde o servidor vai recusar.
    pode_criar: bool


class ACriarSaida(BaseModel):
    """Um cadastro que a confirmação vai criar, ou um apontamento já decidido.

    É o bloco "o que vou criar" da spec, recolhido por padrão: não pede nada da
    pessoa, só presta contas do que vai acontecer quando ela confirmar.
    """

    campo: str
    valor: str
    #: `criar` ou `apontar`.
    acao: str
    #: O cadastro escolhido, quando `acao == "apontar"`.
    alvo: str | None
    linhas: list[int]


class ColunaSaida(BaseModel):
    """Uma coluna do arquivo, com o que a tela precisa para desenhá-la.

    O TIPO VEM DO FORMATO e não de uma lista no front: 59 nomes com o tipo de cada
    um, escritos do outro lado, envelheceriam na primeira coluna nova — e o erro
    seria silencioso, porque a coluna sem tipo receberia a largura padrão.
    """

    nome: str
    #: `marca`, `data`, `sigla`, `lista`, `prosa` ou `texto`. É dele que a grade tira
    #: largura e alinhamento.
    tipo: str


class ImportacaoSaida(BaseModel):
    id: str
    arquivo_nome: str
    situacao: str
    criado_em: str
    #: Quando a pessoa confirmou. Nulo enquanto não confirmou.
    confirmado_em: str | None
    #: As colunas daquele arquivo, NA ORDEM — o cabeçalho da grade de conferência.
    #: Quem subiu o modelo simplificado vê as 22 dele, não as 58 do completo.
    colunas: list[ColunaSaida] = []
    #: As divergências agrupadas por valor, ordenadas pelo que destrava mais.
    #: É a vista principal da conferência: uma decisão, doze linhas. SÓ AS NÃO
    #: RESOLVIDAS — uma decisão já tomada não é pendência, e deixá-la aqui fazia
    #: a tela mostrar um aviso brando no lugar da decisão da pessoa.
    grupos: list[GrupoSaida]
    #: O que já está decidido e vai acontecer na confirmação.
    a_criar: list[ACriarSaida]
    #: A segunda vista — as 54 linhas, para descartar uma específica.
    linhas: list[LinhaSaida]

    #: Quantas LINHAS ainda seguram a confirmação — não quantos grupos. Doze
    #: linhas travadas por um mesmo valor são doze pendências, e dizer "1" faria
    #: o cabeçalho mentir sobre o tamanho do trabalho. Foi um achado de revisão.
    pendencias: int
    #: Quantas DECISÕES resolvem essas linhas. É o número de cliques que a pessoa
    #: tem pela frente, e os dois juntos é que contam a história: "12 linhas
    #: presas por 2 decisões".
    decisoes_pendentes: int


def _nomes_conhecidos(sessao, campo: str) -> list[str]:
    """Os nomes cadastrados no vocabulário deste campo, para sugerir parecidos."""
    vocabulario = importar_agendas.vocabulario_do_campo(campo)
    if vocabulario is None:
        return []
    return importar_agendas.vocabularios(sessao).get(vocabulario, [])


def _alvo_de(sessao, campo: str, nome: str) -> str | None:
    """O id (ou código) do cadastro com este nome — o que `apontar` aceita.

    RESOLVE AQUI e não no domínio: `agrupar` compara TEXTO para achar o parecido,
    e não deve saber de tabela nenhuma. Quem conhece a ponte nome→id é este
    módulo, que já a usa para propor.
    """
    vocabulario = importar_agendas.vocabulario_do_campo(campo)
    if vocabulario is None:
        return None
    valor = importar_agendas.indice_do_vocabulario(sessao, vocabulario).get(normalizar(nome))
    return None if valor is None else str(valor)


def _decididas(linhas) -> list[ACriarSaida]:
    """As divergências que já têm decisão, agrupadas como os grupos são."""
    por_chave: dict[tuple[str, str, str, str | None], list[int]] = {}
    for linha in linhas:
        if linha.aba != "Agendas" or linha.decisao == "descartada":
            continue
        for bruta in linha.divergencias or []:
            if not bruta.get("acao"):
                continue
            chave = (
                bruta["campo"],
                bruta["valor"],
                bruta["acao"],
                bruta.get("alvo"),
            )
            por_chave.setdefault(chave, []).append(linha.linha_origem)
    return [
        ACriarSaida(campo=campo, valor=valor, acao=acao, alvo=alvo, linhas=numeros)
        for (campo, valor, acao, alvo), numeros in sorted(
            por_chave.items(), key=lambda par: (-len(par[1]), par[0][1])
        )
    ]


def _grupos(sessao, linhas) -> list[GrupoSaida]:
    """As divergências gravadas, viradas em decisões.

    LÊ O QUE ESTÁ NO BANCO e reconstrói `Divergencia` para agrupar: o
    agrupamento é regra de domínio, e deixar a API agrupar com dicionários
    soltos poria a mesma regra num segundo lugar — onde ela envelheceria em
    silêncio quando a severidade mudasse.
    """
    por_linha = [
        (
            linha.linha_origem,
            [
                Divergencia(
                    campo=bruta["campo"],
                    valor=bruta["valor"],
                    mensagem=bruta["mensagem"],
                    trava=bruta["trava"],
                    sugestoes=tuple(bruta.get("sugestoes") or ()),
                )
                for bruta in (linha.divergencias or [])
                # A DECIDIDA NÃO É PENDÊNCIA. Ela vai para `a_criar`.
                if not bruta.get("acao")
            ],
        )
        for linha in linhas
        # A DESCARTADA SAI DA CONTA: descartar é uma resolução, e a linha não
        # segura mais a confirmação. Mantê-la no agrupamento faria o botão de
        # confirmar continuar apagado depois de a pessoa já ter decidido.
        if linha.decisao != "descartada"
    ]

    # `vocabularios` uma vez por campo distinto, e não por grupo: uma tela com
    # doze grupos de instituição não pode custar doze leituras do diretório.
    campos = {
        divergencia.campo for _, divergencias in por_linha for divergencia in divergencias
    }
    conhecidos_por_campo = {campo: _nomes_conhecidos(sessao, campo) for campo in campos}

    saida: list[GrupoSaida] = []
    for campo in sorted(campos):
        so_deste_campo = [
            (numero, [d for d in divergencias if d.campo == campo])
            for numero, divergencias in por_linha
        ]
        for grupo in agrupar(so_deste_campo, conhecidos=conhecidos_por_campo[campo]):
            saida.append(
                GrupoSaida(
                    campo=grupo.campo,
                    valor=grupo.valor,
                    linhas=list(grupo.linhas),
                    trava=grupo.trava,
                    pode_criar=importar_agendas.pode_criar(grupo.campo),
                    sugestoes=[
                        SugestaoSaida(nome=nome, alvo=alvo)
                        for nome in grupo.sugestoes
                        # A sugestão sem alvo não entra: oferecer um atalho que o
                        # servidor recusa é pior que não oferecer atalho.
                        if (alvo := _alvo_de(sessao, grupo.campo, nome)) is not None
                    ],
                )
            )
    return sorted(saida, key=lambda grupo: (not grupo.trava, -len(grupo.linhas), grupo.valor))


def _com_a_coluna(divergencias) -> list[dict]:
    """As divergências gravadas, com `coluna` preenchida quando o dado antigo não a tem.

    IMPORTAÇÕES CRIADAS ANTES de as divergências ganharem `coluna` estão no banco sem
    essa chave, e a conferência delas continua aberta. A grade pinta pela coluna e o
    filtro inicial mostra só as linhas com pendência — então a linha DESAPARECIA da
    grade enquanto o cabeçalho anunciava a pendência, e não havia onde mexer.

    A COLUNA É DERIVÁVEL DO CAMPO para todo campo de valor único, e é isso que
    conserta o dado antigo sem migration. `coluna_do_campo` devolve vazio quando o
    campo tem várias colunas (os grupos numerados), e aí a divergência segue sem
    coluna — como as da linha inteira, que nunca tiveram.
    """
    return [
        {**bruta, "coluna": bruta.get("coluna") or coluna_do_campo(bruta.get("campo") or "")}
        for bruta in divergencias or []
    ]


def _colunas_do_arquivo(linhas) -> list[ColunaSaida]:
    """As colunas que AQUELE arquivo tinha, na ordem da descrição.

    A GRADE DA CONFERÊNCIA PRECISA DA ORDEM, e `dados_brutos` é um objeto JSON —
    depender da ordem de um objeto para montar o cabeçalho de uma tabela é
    depender de um detalhe que nenhum contrato promete.

    SÃO AS DAQUELE ARQUIVO e não as do formato inteiro: quem subiu o modelo
    simplificado não deve conferir 58 colunas, das quais 36 ele nunca viu. A ordem
    vem da descrição, que é a mesma nos dois recortes.
    """
    presentes: set[str] = set()
    for linha in linhas:
        presentes.update(
            chave
            for chave in (linha.dados_brutos or {})
            if chave not in CHAVES_RESERVADAS
        )
    return [
        ColunaSaida(nome=coluna.nome, tipo=tipo_da_coluna(coluna))
        for coluna in aba_de(ABA_PRINCIPAL).colunas
        if coluna.nome in presentes
    ]


def _saida(sessao, importacao, linhas) -> ImportacaoSaida:
    grupos = _grupos(sessao, linhas)
    # As linhas, e não os grupos: uma linha presa por duas decisões diferentes
    # conta UMA vez, e doze linhas presas pela mesma decisão contam doze.
    linhas_presas = {
        numero for grupo in grupos if grupo.trava for numero in grupo.linhas
    }
    return ImportacaoSaida(
        id=str(importacao.id),
        colunas=_colunas_do_arquivo(linhas),
        arquivo_nome=importacao.arquivo_nome,
        situacao=importacao.situacao,
        criado_em=importacao.criado_em.isoformat(),
        confirmado_em=(
            importacao.confirmado_em.isoformat() if importacao.confirmado_em else None
        ),
        grupos=grupos,
        a_criar=_decididas(linhas),
        pendencias=len(linhas_presas),
        decisoes_pendentes=sum(1 for grupo in grupos if grupo.trava),
        linhas=[
            LinhaSaida(
                id=linha.id,
                aba=linha.aba,
                linha_origem=linha.linha_origem,
                decisao=linha.decisao,
                interacao_id=str(linha.interacao_id) if linha.interacao_id else None,
                dados_brutos={
                    chave: valor
                    for chave, valor in (linha.dados_brutos or {}).items()
                    if chave not in CHAVES_RESERVADAS
                },
                herdado=(linha.dados_brutos or {}).get(CHAVE_DO_HERDADO) or {},
                corrigido=(linha.dados_brutos or {}).get(CHAVE_DO_CORRIGIDO) or {},
                proposta=linha.proposta,
                divergencias=_com_a_coluna(linha.divergencias),
            )
            for linha in linhas
        ],
    )


def _nome_do_arquivo(modelo: str) -> str:
    """O nome que o arquivo recebe na pasta de downloads, dizendo o recorte."""
    return NOME_DO_MODELO.replace(".xlsx", f"-{modelo}.xlsx")


@rotas.get("/modelo")
def baixar_o_modelo(sessao: Sessao, modelo: str = "completo") -> Response:
    """A planilha em branco, com o cadastro atual nas listas suspensas.

    É GERADA A CADA PEDIDO, e não guardada: um arquivo em cache teria a lista de
    instituições do dia em que foi gerado, e a pessoa preencheria com um
    vocabulário que já mudou — cada nome novo viraria divergência sem motivo.
    """
    # OS PARES (pessoa, instituição) VÃO JUNTO: é a relação que o formulário do
    # front tem — escolher o órgão reduz a lista de quem fala por ele — e é dela que
    # sai a lista suspensa dependente da coluna Interlocutor.
    conteudo = modelo_de_importacao.gerar(
        importar_agendas.vocabularios(sessao),
        importar_agendas.pares_de_vocabulario(sessao),
        modelo=modelo,
    )
    return Response(
        content=conteudo,
        media_type=TIPO_XLSX,
        headers={
            # `filename*=UTF-8''` com `quote()`, e não interpolação crua: o nome
            # é fixo hoje, mas a interpolação crua é o que quebra no dia em que
            # ele ganhar acento ou espaço.
            # O NOME DIZ QUAL MODELO É. Dois arquivos com o mesmo nome na pasta
            # de downloads viram "modelo (1).xlsx", e a pessoa abre o errado —
            # descobrindo só ao procurar uma coluna que aquele recorte não tem.
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(_nome_do_arquivo(modelo))}"
        },
    )


@rotas.post("", status_code=status.HTTP_201_CREATED)
def subir(sessao: Sessao, usuario: UsuarioLogado, arquivo: Arquivo) -> ImportacaoSaida:
    """Lê a planilha, propõe as agendas e guarda tudo para a conferência.

    NADA É CRIADO AQUI. Nem agenda, nem instituição: o que se grava é a proposta
    e o que não resolveu. Criar os cadastros no upload deixaria instituições
    órfãs se a pessoa cancelasse a conferência — e cancelar é um caminho normal,
    não uma falha.
    """
    conteudo = arquivo.file.read()
    # MESMO TETO DAS OUTRAS ROTAS DE UPLOAD (`blob.exigir_tamanho_aceito`) — e
    # a mesma isenção do limite global de 1 MB em `protecao_http.py`, sem a
    # qual esta chamada nunca seria alcançada: uma planilha de 500 agendas
    # preenchidas passa de 1 MiB (medido), e o middleware devolveria 413 antes
    # da rota rodar.
    blob.exigir_tamanho_aceito(len(conteudo))
    # As recusas estruturais levantam `RegraViolada` ANTES de qualquer escrita —
    # `app/api/erros.py` a traduz para 422. Sem isso, um `.xls` renomeado daria
    # 500 e a pessoa leria "erro interno" para um arquivo que ela pode trocar.
    propostas, nomes_declarados, campos_declarados = (
        importar_agendas.propor_com_as_declaracoes(sessao, conteudo)
    )

    importacao = repositorio_importacao.criar(
        sessao,
        arquivo_nome=arquivo.filename or "sem-nome.xlsx",
        criado_por=usuario.id,
    )
    for proposta in propostas:
        repositorio_importacao.gravar_linha(
            sessao,
            importacao_id=importacao.id,
            aba=proposta.linha.aba,
            linha_origem=proposta.linha.numero,
            # O herdado viaja DENTRO de `dados_brutos`, sob uma chave própria: a
            # 0008 não tem coluna para ele, e acrescentá-la seria migration para um
            # rastro de leitura. A saída o separa de novo.
            dados_brutos={
                **proposta.linha.celulas,
                CHAVE_DO_HERDADO: dict(proposta.linha.herdado),
            },
            proposta=(
                proposta.entrada.model_dump(mode="json") if proposta.entrada is not None else None
            ),
            divergencias=[
                {
                    "campo": divergencia.campo,
                    "valor": divergencia.valor,
                    "mensagem": divergencia.mensagem,
                    "trava": divergencia.trava,
                    # A COLUNA DA PLANILHA: é por ela que a tela sabe onde
                    # oferecer o campo para a pessoa completar o que falta.
                    "coluna": divergencia.coluna,
                    "sugestoes": list(divergencia.sugestoes),
                    # `acao` E `alvo` TAMBÉM. O `cria` do upload já nasce com
                    # `acao="criar"`, e perdê-los aqui fazia a declaração na aba
                    # editável reaparecer como pendência branda em vez de ir
                    # para o bloco "o que vou criar".
                    "acao": divergencia.acao,
                    "alvo": divergencia.alvo,
                    "declarado": divergencia.declarado,
                }
                for divergencia in proposta.divergencias
            ],
        )
    # AS DECLARAÇÕES VÃO PARA O BANCO JUNTO DAS LINHAS, porque o arquivo não é
    # guardado: sem isto, uma instituição declarada na aba e não usada em nenhuma linha
    # deixa de existir no instante em que o upload termina, e a pessoa que a usasse
    # depois — corrigindo uma célula na conferência — lia "escreva-a também na aba de
    # cadastro" tendo escrito.
    repositorio_importacao.gravar_declaracoes(
        sessao,
        importacao_id=importacao.id,
        nomes=nomes_declarados,
        campos=campos_declarados,
    )
    repositorio_importacao.marcar_aguardando_conferencia(sessao, importacao)

    return _saida(sessao, importacao, repositorio_importacao.linhas_de(sessao, importacao.id))


class ResolucaoEntrada(BaseModel):
    """Uma decisão sobre um grupo de divergência."""

    campo: str
    valor: str
    #: `apontar` para um cadastro existente, `criar` um novo, ou `descartar` as
    #: linhas. Validado no domínio e não por `Literal` aqui: a mensagem de recusa
    #: sai em português dizendo quais valem, em vez de erro de esquema.
    decisao: str
    #: O id do cadastro escolhido. Obrigatório quando `decisao == "apontar"`.
    alvo: str | None = None


@rotas.patch("/{importacao_id}/resolucoes")
def resolver_divergencia(
    sessao: Sessao, importacao_id: UUID, entrada: ResolucaoEntrada
) -> ImportacaoSaida:
    """Uma decisão, todas as linhas que aquele valor segurava.

    É O QUE FAZ A CONFERÊNCIA ESCALAR com o volume em vez de crescer junto com
    ele: "Instituição não encontrada em 12 linhas" vira um clique, e não doze
    cliques idênticos. Sem isto, um dia de 54 agendas com o mesmo órgão
    desconhecido faria a pessoa parar de conferir e passar a clicar.
    """
    importacao = repositorio_importacao.obter(sessao, importacao_id)
    importar_agendas.resolver(
        sessao,
        importacao_id,
        campo=entrada.campo,
        valor=entrada.valor,
        decisao=entrada.decisao,
        alvo=entrada.alvo,
    )
    return _saida(sessao, importacao, repositorio_importacao.linhas_de(sessao, importacao_id))


class ConfirmacaoSaida(BaseModel):
    """O que a confirmação fez."""

    criadas: int
    cadastros: int
    situacao: str


class CorrecaoEntrada(BaseModel):
    """O que mudou numa linha da conferência: as células, ou a exclusão dela.

    A LINHA É O RECURSO, e por isso uma rota só: "mude esta linha" é uma operação,
    e separá-la em duas faria a tela precisar saber qual chamar para cada gesto.
    """

    #: Coluna → valor, para o que a pessoa completou na grade.
    celulas: dict[str, object] = {}
    #: `True` exclui a linha da importação, `False` a restaura. Reversível até a
    #: confirmação: o arquivo não fica guardado, então a planilha não é o caminho de
    #: volta de uma exclusão por engano.
    descartada: bool | None = None


@rotas.patch("/{importacao_id}/linhas/{linha_id}")
def corrigir_linha(
    sessao: Sessao, importacao_id: UUID, linha_id: int, entrada: CorrecaoEntrada
) -> ImportacaoSaida:
    """Completa na tela o que faltou na planilha, e repropõe a linha.

    A CONFERÊNCIA SABIA RESOLVER O VALOR ERRADO e não o AUSENTE. "Este órgão não
    existe" vem com apontar e criar; a data em branco vinha com um grupo sem valor
    nenhum — nada para clicar. As saídas eram corrigir a planilha e subir tudo de
    novo, ou descartar a linha e perder a agenda.
    """
    importacao = repositorio_importacao.obter(sessao, importacao_id)
    importar_agendas.corrigir_linha(
        sessao, importacao_id, linha_id, entrada.celulas, entrada.descartada
    )
    return _saida(sessao, importacao, repositorio_importacao.linhas_de(sessao, importacao_id))


@rotas.post("/{importacao_id}/confirmacao", status_code=status.HTTP_201_CREATED)
def confirmar_importacao(
    sessao: Sessao, usuario: UsuarioLogado, importacao_id: UUID
) -> ConfirmacaoSaida:
    """Cria os cadastros e as agendas — tudo, ou nada.

    RECONFERE ANTES. Entre subir e confirmar, alguém pode ter cadastrado pela tela
    de Administração a mesma instituição que esta importação ia criar. Confirmar
    cego criaria a duplicata que a conferência existia para evitar, e duplicata de
    instituição contamina toda leitura que agrupa por órgão. Quando algo mudou, a
    resposta é 409 e não 422: o que a pessoa mandou estava certo quando ela olhou.
    """
    resumo = importar_agendas.confirmar(sessao, importacao_id, usuario)
    return ConfirmacaoSaida(
        criadas=resumo.criadas, cadastros=resumo.cadastros, situacao="confirmada"
    )


@rotas.post("/{importacao_id}/cancelamento")
def cancelar_importacao(sessao: Sessao, importacao_id: UUID) -> ImportacaoSaida:
    """Desiste da importação, sem apagar o que a pessoa preencheu.

    NADA A DESFAZER: nenhum cadastro foi criado no upload, exatamente para que
    cancelar não deixe instituições órfãs. O bruto fica porque é a única cópia
    daquele preenchimento no sistema.
    """
    importar_agendas.cancelar(sessao, importacao_id)
    importacao = repositorio_importacao.obter(sessao, importacao_id)
    return _saida(sessao, importacao, repositorio_importacao.linhas_de(sessao, importacao_id))


@rotas.get("/{importacao_id}")
def retomar(sessao: Sessao, importacao_id: UUID) -> ImportacaoSaida:
    """A conferência de onde ela parou.

    É PARA ISTO QUE A 0008 CRIOU TABELA em vez de resolver em memória: 54 agendas
    não se conferem numa sentada, e fechar o navegador não pode custar o
    trabalho de subir e reconferir tudo.
    """
    importacao = repositorio_importacao.obter(sessao, importacao_id)
    return _saida(sessao, importacao, repositorio_importacao.linhas_de(sessao, importacao_id))
