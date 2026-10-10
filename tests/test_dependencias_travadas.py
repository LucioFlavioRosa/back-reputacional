"""As dependências declaradas estão nos DOIS arquivos de lock.

O QUE ESTE TESTE TRAVA, e é uma falha que já aconteceu: `python-calamine` entrou
em `pyproject.toml` e em `requirements.txt`, e NÃO em `requirements-dev.txt`. Tudo
passou localmente — o ambiente de desenvolvimento já tinha o pacote — e o CI caiu
em três testes com `ModuleNotFoundError`, porque o job de testes instala
`--require-hashes -r requirements-dev.txt` e depois `pip install --no-deps -e .`:
o `--no-deps` não traz dependência nenhuma, então o que falta no lock não chega.

POR QUE SÃO DOIS LOCKS: `requirements.txt` é o que a imagem de produção instala;
`requirements-dev.txt` é o mesmo mais as ferramentas de teste. Os dois saem do
mesmo `pyproject.toml`, por dois comandos de `pip-compile` — e manter os dois em
dia é exatamente o tipo de passo que ninguém lembra. Este teste lembra.

NÃO CONFERE VERSÃO, de propósito: o lock é gerado, e comparar versão entre os
dois arquivos brigaria com a resolução legítima do pip-compile. O que ele cobra é
a PRESENÇA, que é o que faltou.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

#: `python-calamine`, `python_calamine`, `PyJWT` — o pip normaliza tudo para
#: minúsculas com hífen (PEP 503).
#:
#: E O EXTRA SAI DO NOME, nos dois lados: o lock escreve `pyjwt[crypto]==2.13.0`
#: e `uvicorn[standard]==0.52.4`. Comparar com o extra dava falso positivo
#: exatamente nos dois pacotes que o projeto declara com extra — e um teste que
#: acusa o que está certo é pior que nenhum, porque ensina a ignorá-lo.
def _normaliza(nome: str) -> str:
    sem_extra = nome.split("[", 1)[0]
    return re.sub(r"[-_.]+", "-", sem_extra).lower().strip()


def _declaradas() -> set[str]:
    """Os nomes das dependências de execução, sem extras nem faixa de versão."""
    com = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    nomes = set()
    for bruta in com["project"]["dependencies"]:
        #: `uvicorn[standard]>=0.30` -> `uvicorn`
        nome = re.split(r"[<>=!;~ ]", bruta, maxsplit=1)[0]
        if nome:
            nomes.add(_normaliza(nome))
    return nomes


def _travadas(arquivo: str) -> set[str]:
    """Os nomes que o lock fixa — as linhas que começam com o pacote."""
    nomes = set()
    for linha in (RAIZ / arquivo).read_text(encoding="utf-8").splitlines():
        if not linha or linha.startswith((" ", "#", "-")):
            continue
        nome = linha.split("==")[0].strip()
        if nome:
            nomes.add(_normaliza(nome))
    return nomes


def test_toda_dependencia_declarada_esta_nos_DOIS_locks():
    declaradas = _declaradas()
    assert declaradas, "o pyproject tem dependências"

    for arquivo in ("requirements.txt", "requirements-dev.txt"):
        faltando = sorted(declaradas - _travadas(arquivo))
        assert not faltando, (
            f"{arquivo} não trava: {', '.join(faltando)}. "
            "Rode o pip-compile dos DOIS arquivos, ou acrescente o bloco do "
            "pacote (nome, hashes e `# via`) à mão, em ordem alfabética — ver o "
            "cabeçalho deste teste."
        )


def test_os_DOIS_locks_travam_o_MESMO_conjunto_de_execucao():
    """O dev é o de produção MAIS as ferramentas, nunca menos.

    Um pacote que só está no de produção é o defeito que derrubou o CI; um que
    só está no dev é um pacote que o deploy não terá — e aí o erro aparece em
    produção, não aqui.
    """
    de_producao = _travadas("requirements.txt")
    de_dev = _travadas("requirements-dev.txt")

    so_na_producao = sorted(de_producao - de_dev)
    assert not so_na_producao, (
        "estão no requirements.txt e não no requirements-dev.txt — o CI instala "
        f"do segundo: {', '.join(so_na_producao)}"
    )


def test_o_LEITOR_DE_PLANILHA_esta_travado():
    """O pacote exato da falha, nomeado.

    O teste acima cobre a regra; este nomeia o caso, para quem ler a falha num
    CI vermelho entender em um segundo do que se trata. `python-calamine` é o
    leitor em Rust que a subida de planilha usa, e três testes o chamam direto.
    """
    for arquivo in ("requirements.txt", "requirements-dev.txt"):
        assert "python-calamine" in _travadas(arquivo), arquivo
