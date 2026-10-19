"""A regra do produto é chamável sem um pedido HTTP. Medido a cada execução.

POR QUE ISTO IMPORTA AGORA. O painel vai ganhar uma SEGUNDA INTERFACE — um bot
de WhatsApp foi nomeado pelo dono do produto —, além de mais automações de
leitura e de geração de texto por IA. Nenhuma das três entra por um navegador.

E A BOA NOTÍCIA É QUE A ESTRUTURA JÁ AGUENTA: medido em 17/10/2026, das **94
funções públicas de `app/casos_de_uso/`, ZERO** pedem `UploadFile`, `Request`,
`Depends`, `BackgroundTasks` ou qualquer outro tipo que só existe dentro de um
pedido. Toda operação do produto é chamável de um job, de um comando de linha
ou de um webhook.

E A CONFERÊNCIA É MAIS LARGA DO QUE AQUELE NÚMERO: ela passa por **492
funções** (209 em `casos_de_uso/`, 283 em `dominio/`) — toda função, em
qualquer profundidade, pública ou privada, com parâmetro de qualquer espécie e
anotação de retorno. Ver `_funcoes`.

ISSO NÃO ESTAVA PROTEGIDO POR NADA. Um `UploadFile` numa assinatura de caso de
uso é o atalho natural de quem está escrevendo uma rota de upload — é mais
curto, funciona, e passa em toda revisão que não esteja olhando para isto. No
dia seguinte a segunda interface não alcança mais aquela operação, e ninguém
liga uma coisa à outra. Então virou teste.

O QUE ESTE ARQUIVO **NÃO** AFIRMA. Ele não diz que a segunda interface sai de
graça. Quando este teste foi escrito, `app/api/` guardava **3.183 linhas em
funções auxiliares de rota**, e **1.344 delas num módulo só** (`lentes.py`, 30
auxiliares privadas) — e tudo o que mora ali uma segunda interface tem de
duplicar ou importar de um módulo de rota.

**AQUELE MÓDULO FOI EXTRAÍDO no mesmo dia** (para
`casos_de_uso/leitura_das_lentes.py` e `esquemas/lentes.py`), e o total caiu
para **1.839 linhas**. Metade do que sobra é legitimamente HTTP
(`dependencias.py`, `erros.py`); o resto está espalhado, sem concentração, e
nenhum pedaço é exigido pelos rumos de hoje.

Este teste protege o que já está certo, e não finge que o resto está. Ver
`docs/ESTRUTURA_E_EXPANSAO.md` §7.1.

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
        #: No singular, de `starlette.background`.
        "BackgroundTask",
        "Depends",
        "File",
        "Form",
        "Query",
        "Header",
        "Cookie",
        "Body",
        "HTTPException",
        "APIRouter",
        #: Os quatro abaixo entraram por achado de revisão. Nenhum aparece no
        #: código hoje, e nenhum colide com nome de biblioteca padrão.
        "Security",
        "SecurityScopes",
        "WebSocket",
        "HTTPConnection",
        "UsuarioLogado",
        "SessaoDoPedido",
        "UsuarioQueAdministraCadastros",
    }
)

#: `Path` FICOU DE FORA DE PROPÓSITO, contra a sugestão da revisão.
#:
#: `fastapi.Path` e `pathlib.Path` são indistinguíveis dentro de uma anotação —
#: a varredura vê o nome, não a origem. E `pathlib.Path` é usado em código
#: legítimo destas camadas (`casos_de_uso/ingerir_mencoes.py` o importa), então
#: incluí-lo faria o teste ACUSAR código correto. Um guarda que acusa o certo é
#: desligado na primeira semana, e aí ele deixa de pegar o errado também.
#:
#: Quem protege contra `fastapi.Path` é o outro teste do par, que proíbe
#: importar `fastapi` nestas camadas — e é por isso que os dois existem juntos.
FORA_POR_COLISAO_DE_NOME = frozenset({"Path"})

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


def _funcoes(caminho: Path) -> list[tuple[str, int, list[str]]]:
    """(nome, linha, todas as anotações) de CADA função do arquivo.

    A REGRA FORTE SUBSTITUIU QUATRO EXCEÇÕES. A primeira versão olhava só
    funções PÚBLICAS de TOPO e só anotações de PARÂMETRO POSICIONAL, e a
    revisão listou o que escapava: método de classe, função aninhada, `*args`/
    `**kwargs`, anotação de RETORNO (`-> Response`) e alias de módulo
    (`processar = _fazer`, que torna pública uma privada).

    Enumerar os cinco seria a mesma lista que envelhece. A regra larga cobre
    todos de uma vez: TODA função, em qualquer profundidade, pública ou
    privada, e TODA anotação — parâmetros de qualquer espécie e o retorno.

    E ELA NÃO CUSTA FALSO POSITIVO: medido antes de adotar, são 494 funções em
    `casos_de_uso/` + `dominio/` (contra 236 públicas de topo), e nenhuma delas
    menciona um tipo de pedido. Afinal, não existe motivo legítimo para uma
    função DESTAS camadas pedir um `UploadFile`, nem em auxiliar privado.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    saida = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = no.args
        argumentos = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        if a.vararg:
            argumentos.append(a.vararg)
        if a.kwarg:
            argumentos.append(a.kwarg)
        anotacoes = [_anotacao(x.annotation) for x in argumentos]
        anotacoes.append(_anotacao(no.returns))
        saida.append((no.name, no.lineno, anotacoes))
    return saida


def _nomes_na_anotacao(texto: str) -> set[str]:
    """Os identificadores de uma anotação, sem casar por substring.

    `"Annotated[Session, ...]"` tem de dar {Annotated, Session}, e um tipo
    chamado `RequestoDeAlgo` NÃO pode casar com `Request` — por isso é
    tokenização por `ast`, e não `in`.

    FORWARD-REF ENTRE ASPAS É REPARSEADO, e isso era um furo: `anexo:
    "UploadFile"` chega como `ast.Constant` de string, e a primeira versão
    devolvia conjunto VAZIO em silêncio — o lugar exato em que um guarda para
    de pegar sem avisar. Achado da revisão.
    """
    try:
        arvore = ast.parse(texto, mode="eval")
    except SyntaxError:
        #: `_anotacao_ilegivel` conta estes, e um teste exige que sejam ZERO —
        #: senão este `except` viraria o buraco silencioso de novo.
        return set()
    saida: set[str] = set()
    for n in ast.walk(arvore):
        if isinstance(n, ast.Name):
            saida.add(n.id)
        elif isinstance(n, ast.Attribute):
            saida.add(n.attr)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            saida |= _nomes_na_anotacao(n.value)
    return saida


def _ilegivel(texto: str) -> bool:
    """A anotação não parseia como expressão?

    Existe para que o `except SyntaxError` acima seja CONTADO, e não apenas
    engolido: se alguma anotação real do projeto cair ali, o guarda deixou de
    olhar para ela, e isso tem de aparecer como falha e não como silêncio.
    """
    if not texto:
        return False
    try:
        ast.parse(texto, mode="eval")
    except SyntaxError:
        return True
    return False


@pytest.mark.parametrize("camada", LIVRES_DE_HTTP)
def test_nenhuma_funcao_pede_um_tipo_de_pedido_http(camada):
    presas: list[str] = []
    for p in _modulos(camada):
        for nome, linha, anotacoes in _funcoes(p):
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


#: O PISO É POR CAMADA, E NÃO NA SOMA — achado da revisão, e a aritmética dele
#: estava certa: `casos_de_uso/` tem 94 funções públicas de topo e `dominio/`
#: tem 142. Com um piso único de 80 na SOMA, apagar `casos_de_uso/` inteira
#: ainda deixava 142 e o fio de alarme passava — justamente no caso que ele
#: existe para pegar.
#:
#: Os valores são folgados de propósito: servem para pegar varredura VAZIA ou
#: pasta desaparecida, não para travar o número. Medidos em 17/10/2026 com a
#: regra larga (toda função, qualquer profundidade): 209 e 283.
PISO_POR_CAMADA = {"casos_de_uso": 120, "dominio": 200}


@pytest.mark.parametrize("camada", LIVRES_DE_HTTP)
def test_a_varredura_esta_olhando_para_funcoes_de_verdade(camada):
    """SEM ESTE CASO os dois acima passam por vazio no dia em que uma pasta for
    renomeada — e a garantia fica falsa sem ninguém notar."""
    modulos = _modulos(camada)
    assert modulos, f"app/{camada}/ não tem módulo nenhum — a pasta mudou de nome?"
    quantas = sum(len(_funcoes(p)) for p in modulos)
    assert quantas > PISO_POR_CAMADA[camada], (camada, quantas)


@pytest.mark.parametrize("camada", LIVRES_DE_HTTP)
def test_nenhuma_anotacao_destas_camadas_e_ilegivel_para_a_varredura(camada):
    """O `except SyntaxError` de `_nomes_na_anotacao` é o lugar onde o guarda
    pararia de pegar EM SILÊNCIO. Este caso exige que ele nunca seja usado em
    anotação de verdade do projeto — se alguma cair ali, isto falha dizendo
    qual, em vez de a anotação passar sem ser olhada."""
    ilegiveis = [
        f"{p.relative_to(RAIZ)}:{linha} {nome} → {a!r}"
        for p in _modulos(camada)
        for nome, linha, anotacoes in _funcoes(p)
        for a in anotacoes
        if _ilegivel(a)
    ]
    assert not ilegiveis, "\n  ".join(ilegiveis)


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
    assert _nomes_na_anotacao("fastapi.UploadFile") & TIPOS_DE_PEDIDO == {"UploadFile"}
    #: FORWARD-REF ENTRE ASPAS, nas três formas em que aparece. Era conjunto
    #: vazio em silêncio.
    assert _nomes_na_anotacao('"UploadFile"') & TIPOS_DE_PEDIDO == {"UploadFile"}
    assert _nomes_na_anotacao('"UploadFile | None"') & TIPOS_DE_PEDIDO == {"UploadFile"}
    assert _nomes_na_anotacao('list["UploadFile"]') & TIPOS_DE_PEDIDO == {"UploadFile"}
    assert not _nomes_na_anotacao("RequestoDeConsulta") & TIPOS_DE_PEDIDO
    assert not _nomes_na_anotacao("Session") & TIPOS_DE_PEDIDO
    #: `Path` NÃO É ACUSADO, e é decisão: `pathlib.Path` é legítimo nestas
    #: camadas e indistinguível de `fastapi.Path` dentro de uma anotação.
    assert not _nomes_na_anotacao("Path") & TIPOS_DE_PEDIDO
    assert FORA_POR_COLISAO_DE_NOME.isdisjoint(TIPOS_DE_PEDIDO)
    #: E `_ilegivel` reconhece o que não parseia, para o `except` ser contado.
    assert _ilegivel("list[")
    assert not _ilegivel("list[int]")
    assert not _ilegivel("")
