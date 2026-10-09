"""As três rotas da revisão da taxonomia de subtemas pela planilha.

    GET  /api/taxonomia/subtemas/modelo       baixa a taxonomia atual
    POST /api/taxonomia/subtemas/conferencia  sobe a planilha e vê o que muda
    POST /api/taxonomia/subtemas/confirmacao  aplica o que foi conferido

NÃO FICAM SOB `/api/importacoes`, e a primeira versão ficava. O teste de rota
pegou o erro: a importação de agendas tem
`POST /api/importacoes/{importacao_id}/confirmacao`, e o parâmetro casa com o
literal `subtemas` — a chamada caía na rota de agendas e voltava 422 de "uuid
inválido" em vez de confirmar. Qualquer segmento literal sob
`/api/importacoes/` é mina pelo mesmo motivo, e registrar este roteador antes
do outro só esconderia a armadilha atrás de uma ordem de registro que ninguém
lembraria de preservar. `/api/taxonomia` não tem rota com parâmetro no
primeiro nível.

SÃO TRÊS, E NÃO SETE. A importação de agendas tem subir, resolver divergência,
corrigir linha, confirmar, cancelar e retomar — porque lá o rascunho vive em
`importacao_linha` e a pessoa trabalha nele dentro do sistema por vários dias.
Aqui não há rascunho: a pessoa corrige a PLANILHA e sobe de novo, então não há
o que cancelar (fechar a tela já é o cancelamento) nem o que retomar. O
docstring de `importar_subtemas.aplicar` explica a escolha e o seu custo.

O CUSTO É A RECONFERÊNCIA, e está pago por `impressao_das_propostas`: a
confirmação recebe a planilha outra vez, reconfere contra o banco daquele
instante e recusa se o resultado diferir do que a pessoa aprovou.

NÃO ENTROU NO `_CAMINHOS_DE_UPLOAD` de `protecao_http.py`, e isso é
deliberado — aquela lista isenta rotas do teto global de 1 MB. Uma planilha de
subtemas no teto do leitor (400 linhas de 6 colunas) tem dezenas de KB: a de
150 linhas gerada hoje tem 24 KB, medidos. Isentar do limite global uma rota
que cabe nele com folga só alargaria a superfície de upload sem motivo.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencias import exigir_administracao_de_cadastros, exigir_portal_crm
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Risco, Tema
from app.casos_de_uso import importar_subtemas, modelo_de_subtemas
from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_subtemas import NAO, SIM, Decisao, Proposta
from app.dominio.vocabulario_de_temas import CAMADAS_DE_LSO

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

rotas = APIRouter(
    prefix="/api/taxonomia/subtemas",
    tags=["taxonomia"],
    # AS MESMAS DUAS DE `importacoes.py`, e pelo mesmo motivo: a taxonomia é
    # cadastro do CRM dos Stakeholders, e revisá-la em massa é administração de
    # cadastro. Ficam no APIRouter para uma rota nova nascer protegida.
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_administracao_de_cadastros)],
)

Sessao = SessaoDoPedido
Arquivo = Annotated[UploadFile, File(description="A planilha de subtemas, em .xlsx")]


# ------------------------------------------------------------------ as saídas
class DivergenciaSaida(BaseModel):
    coluna: str
    valor: str
    motivo: str


class PropostaSaida(BaseModel):
    """Uma linha da planilha e o que a importação faria com ela."""

    linha: int
    nome: str
    decisao: str
    #: Nulo fora de `ALTERA`. Os dois juntos são o que permite a tela mostrar o
    #: que muda em vez de pedir confiança.
    antes: dict | None = None
    depois: dict | None = None
    divergencias: list[DivergenciaSaida] = Field(default_factory=list)


class ConferenciaSaida(BaseModel):
    """O que a tela de conferência recebe."""

    #: A conta por decisão, para o cabeçalho dizer "4 mudam, 145 iguais".
    totais: dict[str, int]
    propostas: list[PropostaSaida]
    #: O que a confirmação tem de devolver para provar que confere o mesmo.
    impressao: str


class ConfirmacaoSaida(BaseModel):
    criados: int
    alterados: int
    iguais: int
    recusadas: int


def _saida_da_proposta(proposta: Proposta) -> PropostaSaida:
    return PropostaSaida(
        linha=proposta.lido.linha,
        nome=proposta.lido.nome,
        decisao=str(proposta.decisao),
        antes=proposta.antes,
        depois=proposta.depois,
        divergencias=[
            DivergenciaSaida(coluna=d.coluna, valor=d.valor, motivo=d.motivo)
            for d in proposta.divergencias
        ],
    )


def _totais(propostas: list[Proposta]) -> dict[str, int]:
    """Uma chave por decisão, SEMPRE as quatro.

    Omitir a decisão de contagem zero obrigaria a tela a tratar chave ausente
    como zero — e a primeira que esquecer mostra o cabeçalho vazio.
    """
    contagem = {str(decisao): 0 for decisao in Decisao}
    for proposta in propostas:
        contagem[str(proposta.decisao)] += 1
    return contagem


# ------------------------------------------------------- o que o banco oferece
def _vocabularios(sessao: Session) -> dict[str, list[str]]:
    """As listas suspensas do modelo, com o cadastro de agora.

    SÓ OS ATIVOS. O modelo é para ESCOLHER, e oferecer um pilar aposentado
    convidaria a pessoa a classificar um subtema sob ele. É o oposto da leitura:
    lá os inativos entram, porque um subtema pode já estar ligado a um.
    """
    pilares = sessao.scalars(
        select(BlocoTema.nome).where(BlocoTema.ativo).order_by(BlocoTema.nome)
    )
    macros = sessao.scalars(
        select(MacroTema.nome).where(MacroTema.ativo).order_by(MacroTema.nome)
    )
    codigos = sessao.execute(
        select(Risco.codigo, Risco.nome).where(Risco.ativo).order_by(Risco.codigo)
    )
    return {
        "blocos_tema": list(pilares),
        "macro_temas": list(macros),
        "camadas_lso": list(CAMADAS_DE_LSO),
        "sim_nao": [SIM, NAO],
        # O CÓDIGO NA COLUNA A E O NOME NA B, em par: "R17" não diz a ninguém
        # qual risco é, e a aba é onde a pessoa descobre — mas a lista suspensa
        # tem de oferecer só o código, que é o que a coluna aceita.
        "riscos": [(codigo, nome) for codigo, nome in codigos],
    }


def _linhas_atuais(sessao: Session) -> list[dict[str, str]]:
    """A taxonomia de hoje, já no formato das colunas do modelo.

    É O QUE FAZ O MODELO SER ÚTIL: a pessoa baixa a taxonomia inteira, muda as
    três linhas que mudaram e sobe. Ver o docstring de `modelo_de_subtemas`.

    OS INATIVOS SAEM TAMBÉM, com Pilar e N2 em branco quando não têm — é o
    estado "ainda não reconciliado" dos 45 subtemas que a 0058 deixou, e a
    planilha é o instrumento de reconciliá-los. Omiti-los esconderia a fila.
    """
    pilar_do_macro = {
        macro_id: nome
        for macro_id, nome in sessao.execute(
            select(MacroTema.id, BlocoTema.nome).join(
                BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id
            )
        ).all()
    }
    # `.all()` ANTES do `dict`: um `Result` do SQLAlchemy 2 não é iterável
    # de pares — `dict(result)` estoura com 'object is not subscriptable'.
    nome_do_macro = dict(sessao.execute(select(MacroTema.id, MacroTema.nome)).all())
    codigo_do_risco = dict(sessao.execute(select(Risco.id, Risco.codigo)).all())

    linhas: list[dict[str, str]] = []
    for tema in sessao.scalars(select(Tema).order_by(Tema.nome)):
        if tema.e_risco is None:
            e_risco = ""  # em branco é resposta: "não reconciliado com a v4"
        else:
            e_risco = SIM if tema.e_risco else NAO
        linhas.append(
            {
                "Subtema (N3)": tema.nome,
                "Pilar (N1)": pilar_do_macro.get(tema.macro_tema_id, ""),
                "Tema estratégico (N2)": nome_do_macro.get(tema.macro_tema_id, ""),
                "LSO": tema.camada_lso or "",
                "É tema de risco?": e_risco,
                "Riscos (códigos)": ", ".join(
                    sorted(
                        codigo_do_risco[risco_id]
                        for risco_id in tema.riscos
                        if risco_id in codigo_do_risco
                    )
                ),
            }
        )
    return linhas


# ------------------------------------------------------------------- as rotas
@rotas.get("/modelo")
def baixar_o_modelo(sessao: Sessao) -> Response:
    """A taxonomia atual num `.xlsx`, com as listas suspensas do cadastro de hoje.

    GERADA A CADA PEDIDO, nunca guardada: um arquivo em cache traria a
    taxonomia do dia em que foi gerado, e a pessoa subiria de volta uma versão
    antiga — o que a conferência leria, corretamente, como um monte de
    alterações que ninguém pediu.
    """
    conteudo = modelo_de_subtemas.gerar(_vocabularios(sessao), _linhas_atuais(sessao))
    return Response(
        content=conteudo,
        media_type=TIPO_XLSX,
        headers={
            # `filename*=UTF-8''` com `quote()`, e não interpolação crua — o
            # mesmo cuidado de `importacoes.py`.
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(modelo_de_subtemas.NOME_DO_MODELO)
        },
    )


@rotas.post("/conferencia")
def conferir(sessao: Sessao, arquivo: Arquivo) -> ConferenciaSaida:
    """Lê a planilha e diz o que faria com cada linha. NADA É GRAVADO.

    As recusas estruturais (arquivo que não abre, aba que falta, cabeçalho que
    não é o do modelo) levantam `RegraViolada` antes de qualquer confronto, e
    `app/api/erros.py` as traduz para 422 — sem isso um `.xls` renomeado daria
    500, e a pessoa leria "erro interno" para um arquivo que ela pode trocar.
    """
    propostas = importar_subtemas.propor(
        sessao, importar_subtemas.ler(arquivo.file.read())
    )
    return ConferenciaSaida(
        totais=_totais(propostas),
        propostas=[_saida_da_proposta(p) for p in propostas],
        impressao=importar_subtemas.impressao_das_propostas(propostas),
    )


@rotas.post("/confirmacao")
def confirmar(
    sessao: Sessao,
    arquivo: Arquivo,
    impressao: Annotated[str, Form(description="A impressão devolvida na conferência")],
) -> ConfirmacaoSaida:
    """Reconfere a planilha e aplica o que foi aprovado.

    A RECONFERÊNCIA NÃO É CERIMÔNIA. Entre conferir e confirmar o banco pode
    mudar — alguém edita um subtema pelo Cadastro de Assuntos com a planilha
    aberta —, e aplicar o `ALTERA` conferido naquele momento gravaria sobre um
    "antes" que já não é o antes: a pessoa teria aprovado uma mudança e aplicado
    outra. Recalcular aqui e comparar a impressão é o que impede isso sem
    guardar rascunho.

    A TRANSAÇÃO É A DA REQUISIÇÃO. `SessaoDoPedido` só faz commit no fim, então
    uma `RegraViolada` no meio desfaz as escritas anteriores — meia taxonomia
    aplicada é pior que nenhuma, porque ninguém sabe onde parou.
    """
    propostas = importar_subtemas.propor(
        sessao, importar_subtemas.ler(arquivo.file.read())
    )
    agora = importar_subtemas.impressao_das_propostas(propostas)
    if agora != impressao:
        raise RegraViolada(
            "O cadastro mudou depois que você conferiu esta planilha. "
            "Confira de novo antes de aplicar."
        )
    resumo = importar_subtemas.aplicar(sessao, propostas)
    return ConfirmacaoSaida(
        criados=resumo.criados,
        alterados=resumo.alterados,
        iguais=resumo.iguais,
        recusadas=resumo.recusadas,
    )
