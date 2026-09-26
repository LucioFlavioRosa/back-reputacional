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
from app.banco import repositorio_importacao
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import importar_agendas, modelo_de_importacao
from app.dominio.importacao_de_agendas import Divergencia, agrupar

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
    dados_brutos: dict
    proposta: dict | None
    divergencias: list


class GrupoSaida(BaseModel):
    """Uma decisão que resolve várias linhas — o bloco "o que precisa de você"."""

    campo: str
    valor: str
    linhas: list[int]
    trava: bool
    sugestoes: list[str]


class ImportacaoSaida(BaseModel):
    id: str
    arquivo_nome: str
    situacao: str
    criado_em: str
    #: As divergências agrupadas por valor, ordenadas pelo que destrava mais.
    #: É a vista principal da conferência: uma decisão, doze linhas.
    grupos: list[GrupoSaida]
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
            ],
        )
        for linha in linhas
        # A DESCARTADA SAI DA CONTA: descartar é uma resolução, e a linha não
        # segura mais a confirmação. Mantê-la no agrupamento faria o botão de
        # confirmar continuar apagado depois de a pessoa já ter decidido.
        if linha.aba == "Agendas" and linha.decisao != "descartada"
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
                    sugestoes=list(grupo.sugestoes),
                )
            )
    return sorted(saida, key=lambda grupo: (not grupo.trava, -len(grupo.linhas), grupo.valor))


def _saida(sessao, importacao, linhas) -> ImportacaoSaida:
    grupos = _grupos(sessao, linhas)
    # As linhas, e não os grupos: uma linha presa por duas decisões diferentes
    # conta UMA vez, e doze linhas presas pela mesma decisão contam doze.
    linhas_presas = {
        numero for grupo in grupos if grupo.trava for numero in grupo.linhas
    }
    return ImportacaoSaida(
        id=str(importacao.id),
        arquivo_nome=importacao.arquivo_nome,
        situacao=importacao.situacao,
        criado_em=importacao.criado_em.isoformat(),
        grupos=grupos,
        pendencias=len(linhas_presas),
        decisoes_pendentes=sum(1 for grupo in grupos if grupo.trava),
        linhas=[
            LinhaSaida(
                id=linha.id,
                aba=linha.aba,
                linha_origem=linha.linha_origem,
                decisao=linha.decisao,
                dados_brutos=linha.dados_brutos,
                proposta=linha.proposta,
                divergencias=linha.divergencias,
            )
            for linha in linhas
        ],
    )


@rotas.get("/modelo")
def baixar_o_modelo(sessao: Sessao) -> Response:
    """A planilha em branco, com o cadastro atual nas listas suspensas.

    É GERADA A CADA PEDIDO, e não guardada: um arquivo em cache teria a lista de
    instituições do dia em que foi gerado, e a pessoa preencheria com um
    vocabulário que já mudou — cada nome novo viraria divergência sem motivo.
    """
    conteudo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    return Response(
        content=conteudo,
        media_type=TIPO_XLSX,
        headers={
            # `filename*=UTF-8''` com `quote()`, e não interpolação crua: o nome
            # é fixo hoje, mas a interpolação crua é o que quebra no dia em que
            # ele ganhar acento ou espaço.
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(NOME_DO_MODELO)}"
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
    # As recusas estruturais levantam `RegraViolada` ANTES de qualquer escrita —
    # `app/api/erros.py` a traduz para 422. Sem isso, um `.xls` renomeado daria
    # 500 e a pessoa leria "erro interno" para um arquivo que ela pode trocar.
    propostas = importar_agendas.propor(sessao, conteudo)

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
            dados_brutos=proposta.linha.celulas,
            proposta=(
                proposta.entrada.model_dump(mode="json") if proposta.entrada is not None else None
            ),
            divergencias=[
                {
                    "campo": divergencia.campo,
                    "valor": divergencia.valor,
                    "mensagem": divergencia.mensagem,
                    "trava": divergencia.trava,
                    "sugestoes": list(divergencia.sugestoes),
                }
                for divergencia in proposta.divergencias
            ],
        )
        # O BRUTO DAS ABAS FILHAS TAMBÉM, uma `importacao_linha` por linha delas.
        #
        # Antes só as linhas de Agendas eram gravadas, e o arquivo original de
        # Participantes, Pessoas da Aegea e Materiais não ficava em lugar nenhum —
        # contra a invariante da 0008 de preservar o bruto para reprocessar e para
        # responder de onde veio um registro. Pior no caso de uma linha filha que
        # espera cadastro: o que a pessoa preencheu não estaria em parte alguma.
        for filha in proposta.linhas_filhas:
            repositorio_importacao.gravar_linha(
                sessao,
                importacao_id=importacao.id,
                aba=filha.aba,
                linha_origem=filha.numero,
                dados_brutos=filha.celulas,
                proposta=None,
                divergencias=[],
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


@rotas.get("/{importacao_id}")
def retomar(sessao: Sessao, importacao_id: UUID) -> ImportacaoSaida:
    """A conferência de onde ela parou.

    É PARA ISTO QUE A 0008 CRIOU TABELA em vez de resolver em memória: 54 agendas
    não se conferem numa sentada, e fechar o navegador não pode custar o
    trabalho de subir e reconferir tudo.
    """
    importacao = repositorio_importacao.obter(sessao, importacao_id)
    return _saida(sessao, importacao, repositorio_importacao.linhas_de(sessao, importacao_id))
