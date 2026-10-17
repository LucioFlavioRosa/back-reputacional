"""Quem importa quem, em `app/` — a varredura ÚNICA que os testes de estrutura
usam.

POR QUE ELA MORA AQUI, E NÃO DENTRO DE CADA TESTE. Havia DUAS varreduras:
`test_as_camadas_sao_respeitadas.py` tinha uma e
`test_os_comandos_sao_pontos_de_entrada.py` tinha outra, mais fraca. Eu
endureci a primeira depois de uma revisão e **deixei a segunda como estava** —
então a regra "nenhuma camada importa um comando" voltou a poder ser burlada
por import relativo, enquanto a regra das camadas já não podia. Achado da
segunda rodada de revisão do Codex, e é o modo de apodrecer mais previsível que
existe: duas cópias da mesma pergunta, uma delas corrigida.

AS SEIS FORMAS DE IMPORTAR QUE ISTO RECONHECE, e cada uma já foi um furo:

    1. from app.banco.x import y          a óbvia
    2. from app.banco import derivados    o submódulo está em `names`, não no nó
    3. import app.banco.x                 e `import app.banco.x as y`
    4. from app import banco              `module == "app"`, que não casa "app."
    5. from ..banco import x              relativo: `module == "banco"`, level=2
    6. importlib.import_module("app.x")   dinâmico, SÓ com caminho literal

A 2 me enganou durante a mudança que criou `app/comandos/`: um módulo apareceu
como "ninguém importa" e eu quase o movi. A 4, a 5 e a 6 passaram pela primeira
versão e foram achadas por revisão.

O QUE ISTO NÃO ALCANÇA, declarado: caminho de módulo montado em variável
(`import_module(f"app.{nome}")`). Nenhuma varredura estática resolve isso, e
prometer o contrário seria pior do que não cobrir.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

#: Pastas que nunca entram na varredura.
#:
#: É A UNIÃO DO QUE OS DOIS TESTES PRECISAM, e não a interseção. Ao juntar as
#: duas varreduras eu quase deixei de fora `node_modules` e `.venv`, que só a
#: de comandos precisa — ela varre a RAIZ do repositório procurando `python -m`
#: em documentação, e não só `app/`. Um `.venv` no disco faria aquele teste
#: percorrer dezenas de milhares de arquivos e acusar invocação de dependência
#: de terceiro.
IGNORAR = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".git", "node_modules", ".venv", "dist"}
)


class Alvo(NamedTuple):
    """Um import de `app.` encontrado num arquivo."""

    modulo: str
    linha: int
    #: Os nomes citados em `from X import a, b` — vazio nas outras formas.
    nomes: tuple[str, ...]


def ignorado(caminho: Path) -> bool:
    return any(parte in IGNORAR or parte.endswith(".egg-info") for parte in caminho.parts)


def modulos_de(raiz: Path, pacote: str = "app") -> dict[str, Path]:
    """Todo módulo importável sob `raiz/pacote`, pelo nome pontilhado.

    O PACOTE TAMBÉM ENTRA, e não só o arquivo: sem `app.banco` aqui,
    `from app import banco` não teria contra o que resolver — a forma 4 passava.
    """
    saida: dict[str, Path] = {}
    for p in (raiz / pacote).rglob("*.py"):
        if ignorado(p):
            continue
        partes = p.relative_to(raiz).with_suffix("").parts
        saida[".".join(partes)] = p
        if partes[-1] == "__init__":
            saida[".".join(partes[:-1])] = p
    return saida


def pacote_do_arquivo(caminho: Path, raiz: Path) -> str:
    """`app.banco` para `app/banco/x.py` — a base dos imports relativos."""
    return ".".join(caminho.relative_to(raiz).parent.parts)


def resolver_relativo(caminho: Path, modulo: str | None, nivel: int, raiz: Path) -> str | None:
    """`from ..dominio import erros` em `app/banco/x.py` → `app.dominio`.

    Nível 1 é o próprio pacote, 2 é o pai, e assim por diante. Subir acima da
    raiz devolve `None` — e isso corresponde a um import relativo que o próprio
    Python recusaria.
    """
    partes = pacote_do_arquivo(caminho, raiz).split(".")
    subida = partes[: len(partes) - (nivel - 1)] if nivel > 1 else partes
    if not subida or subida == [""]:
        return None
    return ".".join([*subida, modulo]) if modulo else ".".join(subida)


def _nome_chamado(no: ast.Call) -> str:
    if isinstance(no.func, ast.Attribute):
        return no.func.attr
    if isinstance(no.func, ast.Name):
        return no.func.id
    return ""


def imports_de(
    caminho: Path,
    raiz: Path,
    modulos: dict[str, Path],
    pacote: str = "app",
) -> list[Alvo]:
    """Os imports de `pacote` que este arquivo faz, nas seis formas."""
    saida: list[Alvo] = []

    def registrar(alvo: str, linha: int, nomes: tuple[str, ...]) -> None:
        if not (alvo == pacote or alvo.startswith(f"{pacote}.")):
            return
        #: O PACOTE RAIZ SOZINHO NÃO ENTRA: ele não diz camada nenhuma
        #: (`app/__init__.py` é só docstring), e registrá-lo faria
        #: `from app import dominio` virar "o domínio importou `app`" — mensagem
        #: que não ajuda ninguém. O que entra é o submódulo resolvido, abaixo.
        if alvo != pacote:
            saida.append(Alvo(alvo, linha, nomes))
        for nome in nomes:
            if f"{alvo}.{nome}" in modulos:
                saida.append(Alvo(f"{alvo}.{nome}", linha, ()))

    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.ImportFrom):
            alvo = (
                resolver_relativo(caminho, no.module, no.level, raiz)
                if no.level
                else no.module
            )
            if alvo:
                registrar(alvo, no.lineno, tuple(a.name for a in no.names))
        elif isinstance(no, ast.Import):
            for a in no.names:
                registrar(a.name, no.lineno, ())
        elif isinstance(no, ast.Call):
            if _nome_chamado(no) in ("import_module", "__import__") and no.args:
                primeiro = no.args[0]
                if isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str):
                    registrar(primeiro.value, no.lineno, ())
    return saida


def tem_porta_de_entrada(caminho: Path) -> bool:
    """O arquivo tem um guard `__main__`?

    POR AST, E NÃO POR TEXTO: a busca por texto contava a mesma frase escrita
    numa docstring, num comentário ou num bloco comentado — um arquivo que só
    FALA de `__main__` passaria por comando.

    A REGRA É LARGA DE PROPÓSITO: qualquer `if`/`elif` cujo teste mencione
    `__name__` e a string `"__main__"`, em qualquer profundidade. A primeira
    versão enumerava formas (`==` nas duas ordens) e perdia
    `if __name__ in ("__main__",)`, guard dentro de `try`, `elif` e comparação
    combinada com `and` — achados da revisão. Procurar os dois símbolos na
    subárvore do teste cobre todas de uma vez, sem lista de formas para
    envelhecer.

    `match __name__:` NÃO é coberto, e é escolha: ninguém escreve isso, e a
    consequência de errar aqui é fraca — o arquivo seria classificado como
    AJUDANTE, o que só torna a classificação pior, não a garantia falsa.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if not isinstance(no, ast.If):
            continue
        dentro = list(ast.walk(no.test))
        tem_nome = any(isinstance(x, ast.Name) and x.id == "__name__" for x in dentro)
        tem_main = any(
            isinstance(x, ast.Constant) and x.value == "__main__" for x in dentro
        )
        if tem_nome and tem_main:
            return True
    return False
