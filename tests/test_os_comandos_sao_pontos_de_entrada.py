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

import re
from pathlib import Path

import pytest

from tests.varredura_de_imports import (
    ignorado as _ignorado,
)
from tests.varredura_de_imports import (
    imports_de,
    modulos_de,
    tem_porta_de_entrada,
)

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app"
COMANDOS = APP / "comandos"

#: A VARREDURA É A COMPARTILHADA, de `tests/varredura_de_imports.py`, e isso é
#: correção de um achado de revisão: este arquivo tinha a SUA PRÓPRIA, mais
#: fraca. Eu endureci a de `test_as_camadas_sao_respeitadas` e deixei esta como
#: estava — então a regra "nenhuma camada importa um comando" voltou a poder
#: ser burlada por import relativo e por `importlib`, enquanto a regra das
#: camadas já não podia.
MODULOS = modulos_de(RAIZ)


def _importa(caminho: Path) -> set[str]:
    return {a.modulo for a in imports_de(caminho, RAIZ, MODULOS)}


def _executaveis() -> set[str]:
    """Os módulos que `python -m` consegue DE FATO rodar.

    NÃO É A MESMA COISA QUE "EXISTE", e essa diferença era um falso positivo
    meu — achado na segunda rodada de revisão do Codex, no código que eu já
    havia empurrado. `python -m app.comandos` falha com
    `No module named app.comandos.__main__`, porque um PACOTE só é executável
    se tiver `__main__.py`, e `app/comandos/` não tem. A primeira versão deste
    teste conferia só se o nome estava no mapa de módulos, então **aprovava um
    caminho que não roda**.
    """
    saida: set[str] = set()
    for nome, caminho in MODULOS.items():
        if caminho.name != "__init__.py":
            #: Módulo em arquivo: `python -m` o executa.
            saida.add(nome)
        elif not nome.endswith(".__init__") and (caminho.parent / "__main__.py").exists():
            #: O pacote só se roda com `__main__.py`. (`...__init__` nunca se
            #: roda por nome próprio.)
            saida.add(nome)
    return saida


def test_nenhuma_camada_importa_um_comando():
    """A METADE QUE IMPORTA. Se uma rota, um caso de uso ou um repositório
    importar de `app.comandos`, a pasta deixou de ser ponto de entrada e virou
    biblioteca — e a separação que esta estrutura comprou foi perdida."""
    presos: list[str] = []
    for p in APP.rglob("*.py"):
        if _ignorado(p) or COMANDOS in p.parents:
            continue
        de_comando = sorted(m for m in _importa(p) if m.startswith("app.comandos"))
        if de_comando:
            presos.append(f"{p.relative_to(RAIZ)} importa {de_comando}")
    assert not presos, "camada importando comando:\n  " + "\n  ".join(presos)


def test_main_tambem_nao_importa_comando():
    """`main.py` mora na raiz e monta a aplicação. Ele é o outro ponto de
    entrada — e um comando subindo com o servidor seria carga rodando no
    processo que atende pedido."""
    assert not {m for m in _importa(RAIZ / "main.py") if m.startswith("app.comandos")}


def test_todo_arquivo_de_comandos_e_comando_ou_ajudante_so_dos_comandos():
    """O QUE IMPEDE A PASTA DE VIRAR DEPÓSITO. Cada `.py` aqui dentro é uma de
    duas coisas: tem `__main__` (é comando) ou é importado SÓ por esta pasta
    (é ajudante dela). Um terceiro caso é código de produção escondido num
    lugar que diz não ter nenhum."""
    fora: list[str] = []
    for p in sorted(COMANDOS.glob("*.py")):
        if p.name == "__init__.py":
            continue
        if tem_porta_de_entrada(p):
            continue
        nome = ".".join(p.relative_to(RAIZ).with_suffix("").parts)
        de_fora = sorted(
            str(q.relative_to(RAIZ))
            for q in APP.rglob("*.py")
            if not _ignorado(q) and COMANDOS not in q.parents and nome in _importa(q)
        )
        if de_fora:
            fora.append(f"{p.name} não tem __main__ e é importado de fora: {de_fora}")
    assert not fora, "\n  ".join(fora)


#: `python -m app.alguma.coisa`, em qualquer arquivo de texto do projeto.
#:
#: `[\w.]+` para parar na primeira coisa que não é nome de módulo — o argumento
#: que vem depois (`sociedade`, `--aplicar`, um caminho) fica fora.
#:
#: AS VARIAÇÕES DO INTERPRETADOR SÃO ACHADO DA REVISÃO DO CODEX: a primeira
#: versão exigia exatamente `python -m `, com um espaço. `python3 -m`,
#: `py -m` (o lançador do Windows, que é o que esta máquina usa) e espaço duplo
#: passavam direto — e uma instrução escrita com qualquer um dos três apontando
#: para módulo inexistente não seria acusada.
INVOCACAO = re.compile(r"\b(?:python3?|py)[ \t]+-m[ \t]+(app[\w.]*)")

TEXTO = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".sh", ".cfg", ".ini"}

#: ARQUIVOS SEM EXTENSÃO que também carregam comando, e que a varredura por
#: extensão perdia — `Dockerfile` é o caso real, e também achado da revisão.
#: Hoje ele usa `uvicorn main:app` e não `python -m`, então não há nada para
#: pegar; fechar o buraco custa uma linha e vale pelo dia em que houver.
SEM_EXTENSAO = {"Dockerfile", "Makefile", "Procfile"}


#: ESTE ARQUIVO FICA DE FORA DA VARREDURA, e é o único: ele fala SOBRE
#: invocações — cita `python -m app.banco.migrar` como exemplo de caminho
#: quebrado, e `python -m app.alguma.coisa` para explicar a regex. Sem a
#: exclusão, a varredura se acusava a si mesma. Qualquer OUTRO arquivo de teste
#: que cite um `python -m app.…` continua sendo conferido.
ESTE_ARQUIVO = Path(__file__).name


def _e_placeholder(texto: str, achado: re.Match[str]) -> bool:
    """`python -m app.comandos.<nome>` é PROSA, não instrução.

    O SEGUNDO FALSO POSITIVO ACHADO PELA REVISÃO, e também no meu próprio
    código: `README.md` e `app/comandos/__init__.py` escrevem a forma genérica
    com `<nome>`. A regex captura `app.comandos.`, o `rstrip(".")` devolve
    `app.comandos`, e aí o teste cobrava que um PACOTE fosse executável —
    reprovando uma frase que está certa.

    O sinal é o `<` imediatamente depois do nome capturado. Só ele: um ponto
    solto no fim (`python -m app.comandos.`) continua sendo erro de verdade e
    segue sendo acusado.
    """
    seguinte = texto[achado.end() : achado.end() + 1]
    return achado.group(1).endswith(".") and seguinte == "<"


def _invocacoes() -> list[tuple[str, str]]:
    achadas = []
    for p in sorted(RAIZ.rglob("*")):
        if not p.is_file() or _ignorado(p):
            continue
        if p.suffix not in TEXTO and p.name.split(".")[0] not in SEM_EXTENSAO:
            continue
        if p.name == ESTE_ARQUIVO:
            continue
        try:
            texto = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - nenhum hoje
            continue
        for achado in INVOCACAO.finditer(texto):
            if _e_placeholder(texto, achado):
                continue
            achadas.append((str(p.relative_to(RAIZ)), achado.group(1).rstrip(".")))
    return achadas


@pytest.mark.parametrize(
    ("linha", "esperado"),
    [
        ("python -m app.comandos.semear_score", "app.comandos.semear_score"),
        ("python3 -m app.comandos.semear_score", "app.comandos.semear_score"),
        #: `py` é o lançador do Windows, e é com ele que estes comandos de fato
        #: são rodados na máquina de quem desenvolve aqui.
        ("py -m app.comandos.semear_score", "app.comandos.semear_score"),
        ("python  -m  app.comandos.semear_score", "app.comandos.semear_score"),
        ("python\t-m\tapp.comandos.semear_score", "app.comandos.semear_score"),
        ("exec api python -m app.comandos.semear_score", "app.comandos.semear_score"),
        #: O ARGUMENTO FICA FORA do nome do módulo.
        ("python -m app.comandos.carregar_pacote_das_lentes sociedade",
         "app.comandos.carregar_pacote_das_lentes"),
    ],
)
def test_a_regex_reconhece_as_formas_de_invocar(linha, esperado):
    """As quatro primeiras variações eram FURO até a revisão do Codex: a regex
    exigia exatamente `python -m ` com um espaço."""
    achado = INVOCACAO.search(linha)
    assert achado is not None, linha
    assert achado.group(1) == esperado


@pytest.mark.parametrize(
    ("fonte", "esperado"),
    [
        ('if __name__ == "__main__":\n    raise SystemExit(0)\n', True),
        ("if __name__ == '__main__':\n    raise SystemExit(0)\n", True),
        ('if "__main__" == __name__:\n    raise SystemExit(0)\n', True),
        #: AS QUATRO FORMAS QUE A PRIMEIRA VERSÃO PERDIA, por enumerar `==`:
        ('if __name__ in ("__main__",):\n    raise SystemExit(0)\n', True),
        ('if True:\n    pass\nelif __name__ == "__main__":\n    raise SystemExit(0)\n', True),
        (
            'try:\n    if __name__ == "__main__":\n        raise SystemExit(0)\n'
            "except Exception:\n    pass\n",
            True,
        ),
        ('if __name__ == "__main__" and True:\n    raise SystemExit(0)\n', True),
        #: O QUE A BUSCA POR TEXTO CONTAVA E NÃO DEVIA:
        ('"""Rode com: if __name__ == "__main__" no fim."""\n', False),
        ('# if __name__ == "__main__":\n', False),
        ("def f():\n    pass\n", False),
        #: E o que menciona só um dos dois símbolos não conta.
        ('if __name__:\n    pass\n', False),
        ('if "__main__" in x:\n    pass\n', False),
    ],
)
def test_a_porta_de_entrada_e_reconhecida_por_ast_e_nao_por_texto(fonte, esperado, tmp_path):
    alvo = tmp_path / "x.py"
    alvo.write_text(fonte, encoding="utf-8")
    assert tem_porta_de_entrada(alvo) is esperado


def test_o_pacote_app_comandos_NAO_e_executavel_e_o_teste_sabe():
    """O falso positivo, fixado nas duas pontas.

    `app.comandos` EXISTE como pacote e NÃO roda com `python -m` (não tem
    `__main__.py`). O mapa de módulos conhece os dois; só o de executáveis
    distingue. Se alguém acrescentar `app/comandos/__main__.py`, este caso
    falha e pede que a distinção seja revista — que é o comportamento certo."""
    assert "app.comandos" in MODULOS
    assert not (COMANDOS / "__main__.py").exists()
    assert "app.comandos" not in _executaveis()
    assert "app.comandos.semear_score" in _executaveis()


@pytest.mark.parametrize(
    ("texto", "quantas"),
    [
        #: PROSA: a forma genérica, que o README e o `__init__` usam.
        ("roda com `python -m app.comandos.<nome>`", 0),
        ("python -m app.comandos.<comando>", 0),
        #: INSTRUÇÃO DE VERDADE: continua sendo conferida.
        ("python -m app.comandos.semear_score", 1),
        #: PONTO SOLTO no fim NÃO é placeholder — é erro, e segue acusado.
        ("python -m app.comandos.", 1),
    ],
)
def test_o_placeholder_generico_nao_e_confundido_com_instrucao(texto, quantas, tmp_path):
    alvo = tmp_path / "x.md"
    alvo.write_text(texto, encoding="utf-8")
    achados = [
        a for a in INVOCACAO.finditer(texto) if not _e_placeholder(texto, a)
    ]
    assert len(achados) == quantas, [a.group(1) for a in achados]


def test_o_projeto_documenta_pelo_menos_um_comando():
    """SE A VARREDURA NÃO ACHAR NADA, o teste seguinte passa por vazio e a
    garantia é falsa sem ninguém notar. Este é o fio de alarme dela."""
    assert len(_invocacoes()) >= 9, _invocacoes()


@pytest.mark.parametrize(("onde", "modulo"), _invocacoes(), ids=lambda v: str(v))
def test_todo_python_m_documentado_aponta_para_modulo_que_RODA(onde, modulo):
    assert modulo in _executaveis(), (
        f"{onde} manda rodar `python -m {modulo}`, e isso não roda. Ou o módulo "
        "não existe (um arquivo mudou de lugar e a instrução ficou para trás), "
        "ou é um PACOTE sem `__main__.py` — que falha com "
        "`No module named …__main__`."
    )
