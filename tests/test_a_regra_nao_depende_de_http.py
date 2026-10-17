"""A regra do produto é chamável sem um pedido HTTP. Medido a cada execução.

POR QUE ISTO IMPORTA AGORA. O painel vai ganhar uma SEGUNDA INTERFACE — um bot
de WhatsApp foi nomeado pelo dono do produto —, além de mais automações de
leitura e de geração de texto por IA. Nenhuma das três entra por um navegador.

E A BOA NOTÍCIA É QUE A ESTRUTURA JÁ AGUENTA: medido em 17/10/2026, das **94
funções públicas de `app/casos_de_uso/`, ZERO** pedem `UploadFile`, `Request`,
`Depends`, `BackgroundTasks` ou qualquer outro tipo que só existe dentro de um
pedido. Toda operação do produto é chamável de um job, de um comando de linha
ou de um webhook.

ISSO NÃO ESTAVA PROTEGIDO POR NADA. Um `UploadFile` numa assinatura de caso de
uso é o atalho natural de quem está escrevendo uma rota de upload — é mais
curto, funciona, e passa em toda revisão que não esteja olhando para isto. No
dia seguinte a segunda interface não alcança mais aquela operação, e ninguém
liga uma coisa à outra. Então virou teste.

O QUE ESTE ARQUIVO **NÃO** AFIRMA. Ele não diz que a segunda interface sai de
graça. Medido no mesmo dia: `app/api/` guarda **3.183 linhas em funções
auxiliares de rota**, e **1.344 delas num módulo só** (`lentes.py`, 30
auxiliares, a maior com 271 linhas, todas privadas). Tudo o que mora ali uma
segunda interface tem de duplicar ou importar de um módulo de rota — uma
pergunta como "como está a Imprensa este mês?" precisaria de `_paineis` (271
linhas), `_evolucao` (93) e `_onde_esta_a_causa` (110).

Esse é o trabalho que falta, e é mudança à parte. Este teste protege o que já
está certo, e não finge que o resto está.

NÃO PRECISA DE BANCO: é leitura de fonte com `ast`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app"

#: AS CAMADAS QUE TÊM DE FICAR CHAMÁVEIS DE QUALQUER LUGAR.
#:
#: `api/` fica de fora por definição (é a interface HTTP), e `seguranca/`
#: também: cookie, CSRF e limite de taxa SÃO sobre o pedido. Uma segunda
#: interface traz a própria autenticação — não reusa a sessão do navegador.
LIVRES_DE_HTTP = ("casos_de_uso", "dominio")

#: Tipos que só existem dentro de um pedido HTTP. Uma função que pede qualquer
#: um destes na assinatura só pode ser chamada pelo FastAPI.
#:
#: `SessaoDoPedido` entra na lista e é o caso menos óbvio: ele parece só uma
#: `Session`, mas é `Annotated[Session, Depends(...)]` — uma sessão amarrada ao
#: ciclo de vida do pedido. Um caso de uso tem de receber `Session` crua, que é
#: o que `obter_fabrica_de_sessao()` entrega fora do HTTP.
TIPOS_DE_PEDIDO = frozenset(
    {
        "UploadFile",
        "Request",
        "Response",
        "BackgroundTasks",
        "Depends",
        "File",
        "Form",
        "Query",
        "Header",
        "Cookie",
        "Body",
        "HTTPException",
        "APIRouter",
        "UsuarioLogado",
        "SessaoDoPedido",
        "UsuarioQueAdministraCadastros",
    }
)

#: Pacotes que não podem ser importados pelas camadas livres. Uma função pode
#: ter assinatura limpa e ainda levantar `HTTPException` no meio do corpo, e aí
#: a segunda interface recebe um erro que ela não sabe traduzir.
PACOTES_DE_PEDIDO = ("fastapi", "starlette")

IGNORAR = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def _modulos(camada: str) -> list[Path]:
    pasta = APP / camada
    return sorted(p for p in pasta.rglob("*.py") if not any(x in p.parts for x in IGNORAR))


def _anotacao(no: ast.AST | None) -> str:
    return ast.unparse(no) if no is not None else ""


def _funcoes_publicas(caminho: Path) -> list[tuple[str, int, list[str]]]:
    """(nome, linha, anotações dos parâmetros) de cada função pública de topo.

    SÓ AS DE TOPO E SÓ AS PÚBLICAS: método de dataclass e `_auxiliar` não são
    a superfície que uma segunda interface chama.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    saida = []
    for no in arvore.body:
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if no.name.startswith("_"):
            continue
        argumentos = [*no.args.posonlyargs, *no.args.args, *no.args.kwonlyargs]
        saida.append((no.name, no.lineno, [_anotacao(a.annotation) for a in argumentos]))
    return saida


def _nomes_na_anotacao(texto: str) -> set[str]:
    """Os identificadores de uma anotação, sem casar por substring.

    `"Annotated[Session, ...]"` tem de dar {Annotated, Session}, e um tipo
    chamado `RequestoDeAlgo` NÃO pode casar com `Request` — por isso é tokenização
    por `ast`, e não `in`.
    """
    try:
        arvore = ast.parse(texto, mode="eval")
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(arvore) if isinstance(n, ast.Attribute)
    }


@pytest.mark.parametrize("camada", LIVRES_DE_HTTP)
def test_nenhuma_funcao_publica_pede_um_tipo_de_pedido_http(camada):
    presas: list[str] = []
    for p in _modulos(camada):
        for nome, linha, anotacoes in _funcoes_publicas(p):
            achados = sorted(
                {
                    t
                    for a in anotacoes
                    for t in _nomes_na_anotacao(a) & TIPOS_DE_PEDIDO
                }
            )
            if achados:
                presas.append(f"{p.relative_to(RAIZ)}:{linha} {nome}(...) pede {achados}")
    assert not presas, (
        f"Estas funções de app/{camada}/ só podem ser chamadas pelo FastAPI, e a "
        "segunda interface (WhatsApp, job, comando) não as alcança:\n  "
        + "\n  ".join(presas)
        + "\n\nReceba o dado já lido (`bytes`, `str`, um tipo do domínio) e deixe a "
        "rota fazer a leitura do pedido."
    )


@pytest.mark.parametrize("camada", LIVRES_DE_HTTP)
def test_as_camadas_livres_nao_importam_fastapi_nem_starlette(camada):
    """Assinatura limpa não basta: `raise HTTPException(...)` no meio do corpo
    devolve, para quem chamou de fora, um erro que ele não sabe traduzir. A
    regra levanta `ErroDeDominio`, e cada interface decide como apresentá-lo."""
    presos: list[str] = []
    for p in _modulos(camada):
        arvore = ast.parse(p.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            alvos: list[str] = []
            if isinstance(no, ast.ImportFrom) and no.module:
                alvos = [no.module]
            elif isinstance(no, ast.Import):
                alvos = [a.name for a in no.names]
            for alvo in alvos:
                raiz = alvo.split(".")[0]
                if raiz in PACOTES_DE_PEDIDO:
                    presos.append(f"{p.relative_to(RAIZ)}:{no.lineno} importa {alvo}")
    assert not presos, (
        f"app/{camada}/ passou a depender da camada HTTP:\n  " + "\n  ".join(presos)
    )


def test_a_varredura_esta_olhando_para_funcoes_de_verdade():
    """SEM ESTE CASO os dois acima passam por vazio no dia em que uma pasta for
    renomeada — e a garantia fica falsa sem ninguém notar."""
    quantas = sum(
        len(_funcoes_publicas(p)) for camada in LIVRES_DE_HTTP for p in _modulos(camada)
    )
    #: Eram 94 em `casos_de_uso/` em 17/10/2026, mais as de `dominio/`. O piso é
    #: folgado de propósito: ele existe para pegar varredura vazia, não para
    #: travar o número.
    assert quantas > 80, quantas


def test_a_varredura_reconhece_o_que_ela_existe_para_pegar():
    """Guarda de fonte que nunca viu um positivo pode ter parado de casar.

    Os quatro casos abaixo são as formas em que o tipo aparece de verdade no
    código — e o último é o que separa tokenização de `in`: um tipo chamado
    `RequestoDeConsulta` não é `Request`.
    """
    assert _nomes_na_anotacao("UploadFile") & TIPOS_DE_PEDIDO == {"UploadFile"}
    assert _nomes_na_anotacao("UploadFile | None") & TIPOS_DE_PEDIDO == {"UploadFile"}
    assert _nomes_na_anotacao("Annotated[Session, Depends(obter)]") & TIPOS_DE_PEDIDO == {
        "Depends"
    }
    assert _nomes_na_anotacao("list[UploadFile]") & TIPOS_DE_PEDIDO == {"UploadFile"}
    assert not _nomes_na_anotacao("RequestoDeConsulta") & TIPOS_DE_PEDIDO
    assert not _nomes_na_anotacao("Session") & TIPOS_DE_PEDIDO
