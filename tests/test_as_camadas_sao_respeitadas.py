"""As camadas de `app/` são respeitadas — agora medido a cada execução.

POR QUE ESTE ARQUIVO EXISTE. `docs/ESTRUTURA_E_EXPANSAO.md` afirmou, na
primeira versão, que "as camadas são respeitadas". Era FALSO: havia quatro
imports de baixo para cima, e a revisão os encontrou. A segunda versão corrigiu
o texto — mas texto não impede o quinto. Uma afirmação de arquitetura que
ninguém executa envelhece sem avisar, e foi exatamente o que aconteceu.

Então a afirmação passou a ser esta suíte. As quatro violações foram resolvidas
de duas formas diferentes, e a diferença importa:

  * TRÊS NÃO ERAM DÍVIDA, eram diagnóstico errado meu. `importar_cadastro_externo`,
    `carregar_pacote_das_lentes` e `semear_referencias` são COMANDOS de linha
    (`python -m …`, com `__main__`), e um ponto de entrada pode importar
    qualquer camada — é o que `main.py` faz. O problema era morarem em
    `app/banco/`, fazendo aquela pasta significar duas coisas. Saíram para
    `app/comandos/`, e lá estão certos por construção;
  * DUAS ERAM. `_mes_de` e `_formula` eram privadas de `api/score.py` e duas
    outras rotas as importavam de volta. Viraram `dominio.periodo.mes_de` e
    `dominio.score.formula_aplicada`.

NÃO PRECISA DE BANCO: é leitura de fonte com `ast`.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app"

#: TRANSVERSAIS. Moram na raiz de `app/` e qualquer camada os lê por desenho:
#: configuração e log não estão acima nem abaixo de ninguém. Chamá-los de
#: violação faria o teste gritar treze vezes por nada, e um teste que grita por
#: nada é desligado na primeira semana.
TRANSVERSAIS = {"configuracao", "observabilidade"}

#: `seguranca.identidade_azure` é OBTER TOKEN para falar com o Azure, e não
#: regra de acesso: `banco/sessao` e `armazenamento/blob` precisam dele para se
#: autenticar no serviço gerenciado. É infraestrutura, e por isso é exceção
#: nomeada — não a pasta `seguranca` inteira liberada para todo mundo.
TRANSVERSAL_EXATO = {"app.seguranca.identidade_azure"}

#: DE QUE CADA CAMADA PODE DEPENDER. Ler de cima para baixo: `dominio` não
#: conhece ninguém (é o ativo da estrutura — testável sem subir nada), e cada
#: linha abaixo dele conhece só o que já está acima.
#:
#: `comandos` é ponto de entrada e pode tudo. Isso NÃO afrouxa nada: o que
#: impede a pasta de virar depósito é a regra inversa, em
#: `test_os_comandos_sao_pontos_de_entrada.py` — nenhuma camada importa um
#: comando.
PERMITIDO: dict[str, set[str]] = {
    "dominio": {"dominio"},
    "esquemas": {"esquemas", "dominio"},
    "armazenamento": {"armazenamento", "dominio"},
    "banco": {"banco", "dominio"},
    #: `banco` SAIU DAQUI, achado da revisão do Codex: nenhum módulo de
    #: `seguranca/` importa `banco`, e eu havia liberado por suposição. Uma
    #: permissão que não corresponde a nenhum import real é um furo esperando
    #: acontecer — ela deixaria passar o primeiro `seguranca -> banco` sem
    #: ninguém decidir que ele podia existir.
    "seguranca": {"seguranca", "dominio"},
    "casos_de_uso": {
        "casos_de_uso",
        "dominio",
        "banco",
        "armazenamento",
        "esquemas",
        "seguranca",
    },
    "api": {
        "api",
        "casos_de_uso",
        "dominio",
        "banco",
        "armazenamento",
        "esquemas",
        "seguranca",
    },
    "comandos": {
        "comandos",
        "api",
        "casos_de_uso",
        "dominio",
        "banco",
        "armazenamento",
        "esquemas",
        "seguranca",
    },
}

#: A DÍVIDA CONHECIDA, nomeada uma por uma: nome privado atravessando arquivo.
#: Não é violação de camada — as três são permitidas pela tabela acima. É outra
#: coisa: `_nome` diz "não me use de fora", e alguém usa.
#:
#: ESTA LISTA É TETO, NÃO PISO. O teste recusa qualquer cruzamento que não
#: esteja aqui, então a dívida não cresce em silêncio; e recusa também uma
#: entrada que deixou de acontecer, para a lista não virar cemitério.
#:
#: POR QUE AS TRÊS CONTINUAM. `api/acesso.py -> _exigir_csrf` é dentro da mesma
#: camada. As de `comandos` são deliberadas: `importar_cadastro_externo` grava
#: pelas MESMAS conferências que a API usa, de propósito — e aquelas três
#: `_conferir_*` recebem `Sessao` e consultam o catálogo, então não são domínio
#: puro como `mes_de` era; a casa certa delas (`banco` ou `casos_de_uso`) é
#: outra mudança, com os testes de erro na frente.
CRUZAMENTOS_CONHECIDOS: set[tuple[str, str, str]] = {
    ("app.api.acesso", "app.api.dependencias", "_exigir_csrf"),
    ("app.comandos.importar_cadastro_externo", "app.api.stakeholders", "_conferir_area"),
    (
        "app.comandos.importar_cadastro_externo",
        "app.api.stakeholders",
        "_conferir_categoria_publico",
    ),
    ("app.comandos.importar_cadastro_externo", "app.api.stakeholders", "_conferir_tier"),
    ("app.comandos.semear_taxonomia_de_temas", "app.comandos.semear_enredos", "_autor"),
    ("app.comandos.semear_taxonomia_de_temas", "app.comandos.semear_enredos", "_elenco"),
    ("app.comandos.semear_taxonomia_de_temas", "app.comandos.semear_enredos", "_uma_solta"),
}

#: O CICLO QUE EXISTE, e é de propósito. `ESTRUTURA_E_EXPANSAO.md` afirmava
#: "não há ciclo de import em lugar nenhum — conferido estaticamente", e este
#: teste provou que também era falso.
#:
#: POR QUE ELE FICA. `material.referencia_id` aponta para `referencia`, que é
#: declarada em `tabelas_referencias`; e `tabelas_referencias` precisa de
#: `Arquivo`, declarado em `tabelas_interacoes`. Quem declara a chave
#: estrangeira tem de trazer o alvo junto, senão um processo que importe só um
#: dos dois quebra na primeira consulta com `NoReferencedTableError` — uma
#: mensagem que não menciona import nenhum. Já aconteceu com `semear_enredos`
#: num banco novo. O import mora no FIM de `tabelas_interacoes.py`, com
#: `noqa: E402`, que é o que faz o ciclo se resolver em vez de travar.
#:
#: É dívida de mapeamento ORM, não de arquitetura — e está aqui nomeada para
#: que o SEGUNDO ciclo, que não terá este motivo, falhe.
CICLOS_CONHECIDOS: set[tuple[str, ...]] = {
    ("app.banco.tabelas_interacoes", "app.banco.tabelas_referencias"),
}

IGNORAR = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def _modulos() -> dict[str, Path]:
    saida = {}
    for p in APP.rglob("*.py"):
        if any(parte in IGNORAR for parte in p.parts):
            continue
        partes = p.relative_to(RAIZ).with_suffix("").parts
        saida[".".join(partes)] = p
        #: O PACOTE TAMBÉM, e não só o arquivo. Sem isto, `from app import banco`
        #: não resolveria: o nome `banco` está em `names`, e a conferência é
        #: `f"{alvo}.{nome}" in MODULOS` — `app.banco` precisa existir aqui.
        if partes[-1] == "__init__":
            saida[".".join(partes[:-1])] = p
    return saida


MODULOS = _modulos()


def _pacote_de(caminho: Path) -> str:
    """O pacote que contém o arquivo — `app.banco` para `app/banco/x.py`.

    É o que resolve import RELATIVO: `from ..dominio import erros` dentro de
    `app/banco/x.py` significa `app.dominio.erros`.
    """
    return ".".join(caminho.relative_to(RAIZ).parent.parts)


def _resolver_relativo(caminho: Path, modulo: str | None, nivel: int) -> str | None:
    """`from ..dominio import erros` → `app.dominio`.

    Nível 1 é o próprio pacote, 2 é o pai, e assim por diante.
    """
    partes = _pacote_de(caminho).split(".")
    subida = partes[: len(partes) - (nivel - 1)] if nivel > 1 else partes
    if not subida:
        return None
    return ".".join([*subida, modulo]) if modulo else ".".join(subida)


def _imports(caminho: Path) -> list[tuple[str, int, list[str]]]:
    """Os imports de `app.` deste arquivo, em TODAS as formas que o Python tem.

    AS QUATRO FORMAS, e cada uma já foi um furo:

    1. `from app.banco.x import y` — a óbvia;
    2. `from app.banco import derivados` — o submódulo está em `names`, não no
       nó. Ler só o nó faz um módulo usado parecer órfão, e esse ponto cego me
       enganou durante esta própria mudança: um módulo apareceu como "ninguém
       importa" e eu quase o movi;
    3. `import app.banco.x` / `import app.banco.x as y`;
    4. `from app import banco` e `from ..banco import x` — ACHADOS DA REVISÃO
       DO CODEX. O primeiro tem `module == "app"`, que não casa com o prefixo
       `"app."` por um caractere; o segundo tem `module == "banco"` e
       `level == 2`, e não parece `app.` nenhum. Nenhuma das duas existe no
       código hoje, e as duas passariam direto.
    """
    saida: list[tuple[str, int, list[str]]] = []

    def registrar(alvo: str, linha: int, nomes: list[str]) -> None:
        if not (alvo == "app" or alvo.startswith("app.")):
            return
        #: O PACOTE RAIZ `app` NÃO ENTRA sozinho: ele não diz camada nenhuma
        #: (`app/__init__.py` é só docstring), e registrá-lo faria
        #: `from app import dominio` aparecer como "o domínio importou `app`" —
        #: uma mensagem que não ajuda ninguém. O que entra é o submódulo
        #: resolvido, abaixo.
        if alvo != "app":
            saida.append((alvo, linha, nomes))
        #: O submódulo citado em `names` é um alvo por direito próprio.
        for nome in nomes:
            if f"{alvo}.{nome}" in MODULOS:
                saida.append((f"{alvo}.{nome}", linha, []))

    for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
        if isinstance(no, ast.ImportFrom):
            alvo = (
                _resolver_relativo(caminho, no.module, no.level)
                if no.level
                else no.module
            )
            if alvo:
                registrar(alvo, no.lineno, [a.name for a in no.names])
        elif isinstance(no, ast.Import):
            for a in no.names:
                registrar(a.name, no.lineno, [])
        #: IMPORT DINÂMICO com caminho literal — `importlib.import_module("app.x")`
        #: e `__import__("app.x")`. Também achado da revisão, e também inexistente
        #: hoje. Só o LITERAL é alcançável: um caminho montado em variável nenhuma
        #: varredura estática resolve, e prometer o contrário seria pior do que
        #: não cobrir.
        elif isinstance(no, ast.Call):
            nome = (
                no.func.attr
                if isinstance(no.func, ast.Attribute)
                else no.func.id
                if isinstance(no.func, ast.Name)
                else ""
            )
            if nome in ("import_module", "__import__") and no.args:
                primeiro = no.args[0]
                if isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str):
                    registrar(primeiro.value, no.lineno, [])
    return saida


def _camada(modulo: str) -> str | None:
    partes = modulo.split(".")
    return partes[1] if len(partes) >= 3 and partes[1] in PERMITIDO else None


def test_a_varredura_reconhece_as_SEIS_formas_de_importar(tmp_path, monkeypatch):
    """GUARDA QUE NUNCA VIU UM POSITIVO pode ter parado de casar.

    Quatro destas seis formas não existem no código hoje, e três delas eram
    FURO até a revisão do Codex apontar. Um teste que só roda contra o código
    atual nunca as exercita — então elas são exercitadas aqui, num arquivo
    temporário que finge estar em `app/banco/`, para o import relativo ter de
    onde subir.
    """
    pasta = tmp_path / "app" / "banco"
    pasta.mkdir(parents=True)
    alvo = pasta / "falso.py"
    alvo.write_text(
        "import importlib\n"
        "from app.dominio.erros import RegraViolada\n"  # 1: a óbvia
        "from app.banco import filtros_sql\n"  # 2: submódulo em `names`
        "import app.dominio.score\n"  # 3: import simples
        "from app import casos_de_uso\n"  # 4: pacote raiz + nome
        "from ..seguranca import oidc\n"  # 5: relativo
        "importlib.import_module('app.api.score')\n",  # 6: dinâmico literal
        encoding="utf-8",
    )

    #: `_imports` resolve o relativo contra a posição do ARQUIVO, então a raiz
    #: tem de ser a do temporário. `MODULOS` segue sendo a do repositório de
    #: verdade, que é o que faz a resolução de submódulo ter contra o que
    #: conferir — por isso os nomes usados acima são todos REAIS.
    monkeypatch.setattr(f"{__name__}.RAIZ", tmp_path)
    achados = {a for a, _, _ in _imports(alvo)}

    for esperado in (
        "app.dominio.erros",
        "app.banco",
        "app.banco.filtros_sql",
        "app.dominio.score",
        "app.casos_de_uso",
        "app.seguranca",
        "app.seguranca.oidc",
        "app.api.score",
    ):
        assert esperado in achados, (esperado, sorted(achados))

    #: E o pacote raiz sozinho NÃO entra — ele não diz camada nenhuma.
    assert "app" not in achados


def test_nenhuma_camada_importa_o_que_nao_pode():
    violacoes = []
    for nome, p in sorted(MODULOS.items()):
        minha = _camada(nome)
        if minha is None:
            continue
        for alvo, linha, _ in _imports(p):
            partes = alvo.split(".")
            if len(partes) < 2:
                continue
            outra = partes[1]
            if outra in TRANSVERSAIS or alvo in TRANSVERSAL_EXATO:
                continue
            if outra not in PERMITIDO[minha]:
                violacoes.append(f"{nome.replace('.', '/')}.py:{linha} ({minha}) -> {alvo}")
    assert not violacoes, "camada importando o que não pode:\n  " + "\n  ".join(violacoes)


def test_o_dominio_nao_conhece_ninguem():
    """O ATIVO DA ESTRUTURA, e o único item que a revisão de arquitetura mandou
    preservar acima de tudo. Regra pura se testa contra o valor esperado sem
    montar banco nem cliente HTTP — é de onde vem a maior parte desta suíte, e
    um único import de `banco` aqui começa a desmontar isso."""
    presos = []
    for nome, p in sorted(MODULOS.items()):
        if not nome.startswith("app.dominio."):
            continue
        for alvo, linha, _ in _imports(p):
            if not alvo.startswith("app.dominio"):
                presos.append(f"{nome.replace('.', '/')}.py:{linha} -> {alvo}")
    assert not presos, "o domínio deixou de ser puro:\n  " + "\n  ".join(presos)


def _ciclos() -> set[tuple[str, ...]]:
    """Cada ciclo como o conjunto ORDENADO dos módulos nele.

    Normalizado assim porque o mesmo ciclo é encontrado por caminhos
    diferentes dependendo de onde a busca começa — `a -> b -> a` e
    `b -> a -> b` são um ciclo, não dois.
    """
    grafo: dict[str, set[str]] = defaultdict(set)
    for nome, p in MODULOS.items():
        for alvo, _, _ in _imports(p):
            if alvo in MODULOS and alvo != nome:
                grafo[nome].add(alvo)

    #: Busca em profundidade com o caminho na mão, para o erro DIZER quais
    #: módulos formam o ciclo em vez de só afirmar que existe um.
    achados: set[tuple[str, ...]] = set()
    estado: dict[str, int] = {}

    def visitar(no: str, caminho: list[str]) -> None:
        estado[no] = 1
        for vizinho in sorted(grafo[no]):
            if estado.get(vizinho) == 1 and vizinho in caminho:
                achados.add(tuple(sorted(caminho[caminho.index(vizinho) :])))
            elif estado.get(vizinho) is None:
                visitar(vizinho, [*caminho, vizinho])
        estado[no] = 2

    for nome in sorted(MODULOS):
        if estado.get(nome) is None:
            visitar(nome, [nome])
    return achados


def test_nao_ha_ciclo_de_import_novo():
    """Zero ciclos novos. Um ciclo não quebra na hora: ele quebra no dia em que
    a ordem de import muda, com um `ImportError` que aponta para o arquivo
    errado. O único que existe hoje está em `CICLOS_CONHECIDOS`, com o motivo."""
    novos = sorted(_ciclos() - CICLOS_CONHECIDOS)
    assert not novos, "ciclo de import novo:\n  " + "\n  ".join(" <-> ".join(c) for c in novos)


@pytest.mark.parametrize("ciclo", sorted(CICLOS_CONHECIDOS), ids=lambda c: " <-> ".join(c))
def test_o_ciclo_conhecido_ainda_existe(ciclo):
    """Se ele foi desfeito, sai da lista — senão a lista deixa de dizer qual é
    a dívida de hoje."""
    assert ciclo in _ciclos(), (
        f"o ciclo {' <-> '.join(ciclo)} não existe mais. "
        "Tire a entrada de CICLOS_CONHECIDOS — a dívida foi paga."
    )


def _cruzamentos_privados() -> set[tuple[str, str, str]]:
    achados = set()
    for nome, p in MODULOS.items():
        for alvo, _, nomes in _imports(p):
            if alvo == nome:
                continue
            for n in nomes:
                if n.startswith("_") and not n.startswith("__"):
                    achados.add((nome, alvo, n))
    return achados


def test_nenhum_cruzamento_de_nome_privado_novo():
    """`_nome` significa "não me use de fora". Quando alguém usa, a função
    deixou de ser privada de fato e ninguém a renomeou — foi assim que
    `_mes_de` acabou com dois consumidores externos."""
    novos = sorted(_cruzamentos_privados() - CRUZAMENTOS_CONHECIDOS)
    assert not novos, (
        "cruzamento de nome privado que não está na lista de dívida conhecida:\n  "
        + "\n  ".join(f"{a} -> {b} [{c}]" for a, b, c in novos)
        + "\n\nOu promova o nome (tirando o `_` e pondo na camada certa), ou "
        "acrescente a entrada em CRUZAMENTOS_CONHECIDOS dizendo por quê."
    )


@pytest.mark.parametrize(("de", "para", "nome"), sorted(CRUZAMENTOS_CONHECIDOS))
def test_a_divida_conhecida_ainda_e_divida(de, para, nome):
    """O OUTRO LADO DO TETO: uma entrada que deixou de acontecer sai da lista.
    Sem isto, `CRUZAMENTOS_CONHECIDOS` vira cemitério e deixa de dizer qual é
    a dívida de hoje."""
    assert (de, para, nome) in _cruzamentos_privados(), (
        f"{de} já não importa {nome} de {para}. Tire a entrada de "
        "CRUZAMENTOS_CONHECIDOS — a dívida foi paga."
    )
