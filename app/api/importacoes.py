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


class ImportacaoSaida(BaseModel):
    id: str
    arquivo_nome: str
    situacao: str
    criado_em: str
    linhas: list[LinhaSaida]


def _saida(importacao, linhas) -> ImportacaoSaida:
    return ImportacaoSaida(
        id=str(importacao.id),
        arquivo_nome=importacao.arquivo_nome,
        situacao=importacao.situacao,
        criado_em=importacao.criado_em.isoformat(),
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
    repositorio_importacao.marcar_aguardando_conferencia(sessao, importacao)

    return _saida(importacao, repositorio_importacao.linhas_de(sessao, importacao.id))


@rotas.get("/{importacao_id}")
def retomar(sessao: Sessao, importacao_id: UUID) -> ImportacaoSaida:
    """A conferência de onde ela parou.

    É PARA ISTO QUE A 0008 CRIOU TABELA em vez de resolver em memória: 54 agendas
    não se conferem numa sentada, e fechar o navegador não pode custar o
    trabalho de subir e reconferir tudo.
    """
    importacao = repositorio_importacao.obter(sessao, importacao_id)
    return _saida(importacao, repositorio_importacao.linhas_de(sessao, importacao_id))
