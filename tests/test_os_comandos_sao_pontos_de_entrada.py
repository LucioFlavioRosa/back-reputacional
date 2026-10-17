"""`app/comandos/` só vale enquanto a regra dela for verdade — então é teste.

A PASTA DIZ UMA COISA: ali mora o que uma PESSOA RODA, e não o que o servidor
serve. Isso compra duas coisas, e as duas somem em silêncio se ninguém olhar:

  1. um comando pode importar QUALQUER camada — é ponto de entrada, igual a
     `main.py` — e nenhuma camada pode importar um comando. Sem a segunda
     metade, a pasta vira um segundo lugar onde mora regra de negócio, e aí ter
     separado não serviu para nada;

  2. todo `python -m app.<algo>` que o projeto documenta aponta para um módulo
     que EXISTE. Caminho de módulo em prosa é string: nenhum compilador o
     confere, e mover um arquivo deixa a instrução quebrada esperando a próxima
     pessoa que for semear um banco. Esta mudança moveu dez arquivos; o motivo
     deste teste nascer junto é exatamente esse. (O repositório de infra já
     tinha uma dessas: documentava `python -m app.banco.migrar`, e `migrar.py`
     mora em `infra-reputacional/scripts/`. Lá este teste não alcança.)

NÃO PRECISA DE BANCO: é tudo leitura de fonte.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app"
COMANDOS = APP / "comandos"

#: Onde não se procura: artefato de build, ambiente virtual, cache.
IGNORAR = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


def _ignorado(caminho: Path) -> bool:
    return any(p in IGNORAR or p.endswith(".egg-info") for p in caminho.parts)


def _modulos_de_app() -> set[str]:
    nomes = set()
    for p in APP.rglob("*.py"):
        if _ignorado(p):
            continue
        partes = p.relative_to(RAIZ).with_suffix("").parts
        nomes.add(".".join(partes))
        #: `app.comandos` (o pacote) também é importável, e `python -m` num
        #: pacote com `__main__.py` é legítimo — nenhum existe hoje, mas o
        #: teste não deve passar a acusar o dia em que existir.
        if partes[-1] == "__init__":
            nomes.add(".".join(partes[:-1]))
    return nomes


def _importa(caminho: Path, modulos: set[str]) -> set[str]:
    """Os módulos de `app.` que este arquivo importa, nas DUAS formas.

    `from app.banco import derivados` tem `app.banco` no nó e `derivados` em
    `names` — ler só o nó do import é o ponto cego que faz um módulo usado
    parecer órfão. Já me enganou uma vez nesta mesma mudança.
    """
    saida: set[str] = set()
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("app."):
            saida.add(no.module)
            for a in no.names:
                if f"{no.module}.{a.name}" in modulos:
                    saida.add(f"{no.module}.{a.name}")
        elif isinstance(no, ast.Import):
            saida.update(a.name for a in no.names if a.name.startswith("app."))
    return saida


def test_nenhuma_camada_importa_um_comando():
    """A METADE QUE IMPORTA. Se uma rota, um caso de uso ou um repositório
    importar de `app.comandos`, a pasta deixou de ser ponto de entrada e virou
    biblioteca — e a separação que esta estrutura comprou foi perdida."""
    modulos = _modulos_de_app()
    presos: list[str] = []
    for p in APP.rglob("*.py"):
        if _ignorado(p) or COMANDOS in p.parents:
            continue
        de_comando = sorted(m for m in _importa(p, modulos) if m.startswith("app.comandos"))
        if de_comando:
            presos.append(f"{p.relative_to(RAIZ)} importa {de_comando}")
    assert not presos, "camada importando comando:\n  " + "\n  ".join(presos)


def test_main_tambem_nao_importa_comando():
    """`main.py` mora na raiz e monta a aplicação. Ele é o outro ponto de
    entrada — e um comando subindo com o servidor seria carga rodando no
    processo que atende pedido."""
    modulos = _modulos_de_app()
    assert not {m for m in _importa(RAIZ / "main.py", modulos) if m.startswith("app.comandos")}


def test_todo_arquivo_de_comandos_e_comando_ou_ajudante_so_dos_comandos():
    """O QUE IMPEDE A PASTA DE VIRAR DEPÓSITO. Cada `.py` aqui dentro é uma de
    duas coisas: tem `__main__` (é comando) ou é importado SÓ por esta pasta
    (é ajudante dela). Um terceiro caso é código de produção escondido num
    lugar que diz não ter nenhum."""
    modulos = _modulos_de_app()
    fora: list[str] = []
    for p in sorted(COMANDOS.glob("*.py")):
        if p.name == "__init__.py":
            continue
        texto = p.read_text(encoding="utf-8")
        if '__name__ == "__main__"' in texto:
            continue
        nome = ".".join(p.relative_to(RAIZ).with_suffix("").parts)
        de_fora = sorted(
            str(q.relative_to(RAIZ))
            for q in APP.rglob("*.py")
            if not _ignorado(q) and COMANDOS not in q.parents and nome in _importa(q, modulos)
        )
        if de_fora:
            fora.append(f"{p.name} não tem __main__ e é importado de fora: {de_fora}")
    assert not fora, "\n  ".join(fora)


#: `python -m app.alguma.coisa`, em qualquer arquivo de texto do projeto.
#: `[\w.]+` para parar na primeira coisa que não é nome de módulo — o
#: argumento que vem depois (`sociedade`, `--aplicar`, um caminho) fica fora.
INVOCACAO = re.compile(r"python -m (app[\w.]*)")

TEXTO = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".sh", ".cfg", ".ini"}


#: ESTE ARQUIVO FICA DE FORA DA VARREDURA, e é o único: ele fala SOBRE
#: invocações — cita `python -m app.banco.migrar` como exemplo de caminho
#: quebrado, e `python -m app.alguma.coisa` para explicar a regex. Sem a
#: exclusão, a varredura se acusava a si mesma. Qualquer OUTRO arquivo de teste
#: que cite um `python -m app.…` continua sendo conferido.
ESTE_ARQUIVO = Path(__file__).name


def _invocacoes() -> list[tuple[str, str]]:
    achadas = []
    for p in sorted(RAIZ.rglob("*")):
        if not p.is_file() or p.suffix not in TEXTO or _ignorado(p):
            continue
        if p.name == ESTE_ARQUIVO:
            continue
        try:
            texto = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - nenhum hoje
            continue
        for achado in INVOCACAO.finditer(texto):
            achadas.append((str(p.relative_to(RAIZ)), achado.group(1).rstrip(".")))
    return achadas


def test_o_projeto_documenta_pelo_menos_um_comando():
    """SE A VARREDURA NÃO ACHAR NADA, o teste seguinte passa por vazio e a
    garantia é falsa sem ninguém notar. Este é o fio de alarme dela."""
    assert len(_invocacoes()) >= 9, _invocacoes()


@pytest.mark.parametrize(("onde", "modulo"), _invocacoes(), ids=lambda v: str(v))
def test_todo_python_m_documentado_aponta_para_modulo_que_existe(onde, modulo):
    modulos = _modulos_de_app()
    assert modulo in modulos, (
        f"{onde} manda rodar `python -m {modulo}`, e esse módulo não existe. "
        "Um arquivo mudou de lugar e a instrução ficou para trás."
    )
