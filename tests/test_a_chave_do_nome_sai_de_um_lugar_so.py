"""Chave derivada de nome sai de `dominio/texto.py`, e de nenhum outro lugar.

POR QUE ISTO É TESTE. `dominio/texto.py` abre dizendo: "se a carga e a busca
normalizassem de formas diferentes, a busca deixaria de encontrar exatamente os
nomes que a carga uniu — por isso mora aqui, e não duplicada nos dois lados".

**E ESTAVA DUPLICADA ASSIM MESMO.** `api/stakeholders.py` tinha o seu próprio
`_normalizar`, e ele **não colapsava espaço interno**:

    dominio/texto.normalizar("Folha  de  S.Paulo")  ->  "folha de s.paulo"
    api/stakeholders._normalizar(o mesmo)           ->  "folha  de  s.paulo"

O índice único é `(nome_normalizado, tipo)`. Então a mesma instituição criada
pelo FORMULÁRIO com espaço duplo não colidia com a que a PLANILHA criou, e
entrava como segunda instituição — exatamente a duplicata que o comentário
daquela função dizia existir para impedir.

NINGUÉM TINHA DIGITADO ESPAÇO DUPLO AINDA. Medido no banco antes de consertar:
zero linhas divergentes e zero colisões em 4.419 cadastros (`instituicao` 3.953,
`interlocutor` 451, `pessoa_aegea` 15). O defeito era latente, e um defeito
latente é o que ninguém acha olhando a tela.

Uma regra que o código declara e que nada verifica é uma regra que já foi
violada uma vez. Agora é verificada.

NÃO PRECISA DE BANCO: é leitura de fonte com `ast`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.dominio.texto import achatar_para_comparar, codigo_estavel, normalizar

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app"
CANONICO = APP / "dominio" / "texto.py"

#: AS DUAS EXCEÇÕES, e cada uma tem propósito diferente de "chave de nome".
#:
#: Elas estão nomeadas uma a uma, com o motivo, e a lista é TETO: uma
#: normalização nova em qualquer outro lugar falha, e uma destas que deixe de
#: existir também falha — senão a lista vira cemitério.
EXCECOES = {
    "app/armazenamento/blob.py": (
        "Sanitiza CAMINHO DE ARQUIVO, não chave de nome: preserva caixa e ponto "
        "(`A-Za-z0-9._-`), troca o resto por `-` e corta em 80 caracteres. "
        "`normalizar` destruiria a extensão e a legibilidade do caminho."
    ),
    "app/dominio/ingestao_score.py": (
        "Achata VOCABULÁRIO DE FORNECEDOR (`POSITIVA`/`Positivo`/`positiva `), e "
        "faz NFD letra a letra filtrando categoria `Mn` em vez de NFKD + ascii. "
        "A diferença preserva letra não-ASCII em vez de descartá-la, e isso é "
        "escolha: aqui o texto vem de planilha de terceiro, não do cadastro."
    ),
}

IGNORAR = {"__pycache__", ".pytest_cache", ".ruff_cache"}

#: AS TRÊS FUNÇÕES CANÔNICAS. Um `re.sub` aplicado à saída de qualquer uma
#: delas está derivando uma QUARTA chave — foi assim que `consulta_profundidade`
#: ficou com uma cópia do corpo de `codigo_estavel` sem chamar `unicodedata`
#: nenhuma vez, e por isso invisível para a primeira versão desta guarda.
CANONICAS = {"normalizar", "achatar_para_comparar", "codigo_estavel"}


def _modulos() -> list[Path]:
    return sorted(
        p for p in APP.rglob("*.py") if not any(x in p.parts for x in IGNORAR)
    )


def _arvore(caminho: Path) -> ast.Module:
    return ast.parse(caminho.read_text(encoding="utf-8"))


def _apelidos_do_unicodedata(arvore: ast.Module) -> tuple[set[str], set[str]]:
    """Os nomes pelos quais ESTE arquivo alcança `unicodedata.normalize`.

    SÃO TRÊS FORMAS, e a primeira versão desta guarda só reconhecia uma —
    `import unicodedata` com o nome literal. `import unicodedata as ud` e
    `from unicodedata import normalize` passavam batido, e a guarda prometia
    mais do que entregava.
    """
    modulos: set[str] = set()
    diretos: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                if alias.name == "unicodedata":
                    modulos.add(alias.asname or alias.name)
        elif isinstance(no, ast.ImportFrom) and no.module == "unicodedata":
            for alias in no.names:
                if alias.name == "normalize":
                    diretos.add(alias.asname or alias.name)
    return modulos, diretos


def _normaliza_unicode(caminho: Path) -> list[int]:
    """As linhas em que este arquivo CHAMA `unicodedata.normalize`.

    POR AST, E NÃO POR TEXTO: `importacao_de_agendas.py` menciona "NFKD" numa
    docstring explicando por que `normalizar` resolve espaço não separável, e
    isso é documentação correta — não uma segunda implementação.
    """
    arvore = _arvore(caminho)
    modulos, diretos = _apelidos_do_unicodedata(arvore)
    achados = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        alvo = no.func
        if isinstance(alvo, ast.Attribute) and alvo.attr == "normalize":
            dono = alvo.value
            if isinstance(dono, ast.Name) and dono.id in modulos:
                achados.append(no.lineno)
        elif isinstance(alvo, ast.Name) and alvo.id in diretos:
            achados.append(no.lineno)
    return sorted(achados)


def _deriva_chave_de_nome(caminho: Path) -> list[int]:
    """As linhas que aplicam `.sub(...)` à saída de uma das canônicas.

    ESTA É A DETECÇÃO QUE FALTAVA. Chave de nome não se duplica só chamando
    `unicodedata`: `_FORA_DO_SLUG.sub("_", normalizar(nome)).strip("_")` é o
    corpo de `codigo_estavel` letra por letra, sem um `unicodedata` à vista.
    O resultado coincidia — e é justamente por coincidir que a cópia é
    perigosa: no dia em que a regra canônica mudar, ela não muda junto.
    """
    achados = []
    for no in ast.walk(_arvore(caminho)):
        if not isinstance(no, ast.Call):
            continue
        if not (isinstance(no.func, ast.Attribute) and no.func.attr in {"sub", "subn"}):
            continue
        for dentro in ast.walk(no):
            if (
                isinstance(dentro, ast.Call)
                and isinstance(dentro.func, ast.Name)
                and dentro.func.id in CANONICAS
            ):
                achados.append(no.lineno)
                break
    return sorted(achados)


def _relativo(caminho: Path) -> str:
    return caminho.relative_to(RAIZ).as_posix()


def test_nenhuma_normalizacao_nova_fora_do_dominio_do_texto():
    fora: list[str] = []
    for p in _modulos():
        if p == CANONICO:
            continue
        linhas = _normaliza_unicode(p)
        if linhas and _relativo(p) not in EXCECOES:
            fora.append(f"{_relativo(p)}:{','.join(str(x) for x in linhas)}")
    assert not fora, (
        "Normalização de texto fora de `dominio/texto.py`:\n  "
        + "\n  ".join(fora)
        + "\n\nUse `normalizar`, `achatar_para_comparar` ou `codigo_estavel`. Se o "
        "propósito for genuinamente outro, acrescente o arquivo em EXCECOES "
        "dizendo qual — foi uma regra duplicada em silêncio que criou duplicata "
        "de cadastro."
    )


@pytest.mark.parametrize("arquivo", sorted(EXCECOES))
def test_cada_excecao_ainda_normaliza(arquivo):
    """O outro lado do teto: exceção que deixou de normalizar sai da lista."""
    caminho = RAIZ / arquivo
    assert caminho.exists(), f"{arquivo} não existe mais — tire de EXCECOES."
    assert _normaliza_unicode(caminho), (
        f"{arquivo} já não chama `unicodedata.normalize`. Tire de EXCECOES — a "
        "exceção foi paga."
    )


def test_a_varredura_acha_a_implementacao_canonica():
    """SEM ESTE CASO o teste acima passa por vazio no dia em que a detecção
    parar de casar — e a garantia fica falsa sem ninguém notar."""
    assert _normaliza_unicode(CANONICO), "a detecção parou de reconhecer o canônico"


def test_a_varredura_reconhece_apelido_e_from_import(tmp_path):
    """AS TRÊS FORMAS DE ALCANÇAR `unicodedata.normalize`.

    A primeira versão desta guarda só reconhecia a primeira, então uma quarta
    regra entrava com `import unicodedata as ud` sem nada acusar. Estes são
    arquivos sintéticos: eles existem para provar que a DETECÇÃO vê o que
    promete ver, e não para afirmar algo sobre o `app/`.
    """
    formas = {
        "literal.py": "import unicodedata\nx = unicodedata.normalize('NFKD', 'a')\n",
        "apelido.py": "import unicodedata as ud\nx = ud.normalize('NFKD', 'a')\n",
        "direto.py": "from unicodedata import normalize\nx = normalize('NFKD', 'a')\n",
        "renomeado.py": "from unicodedata import normalize as nz\nx = nz('NFKD', 'a')\n",
    }
    for nome, fonte in formas.items():
        caminho = tmp_path / nome
        caminho.write_text(fonte, encoding="utf-8")
        assert _normaliza_unicode(caminho) == [2], f"a detecção não viu {nome}"
    #: E O OUTRO LADO: um `normalize` que não vem do `unicodedata` não é achado,
    #: senão a guarda viraria ruído e a próxima pessoa a desligaria.
    outro = tmp_path / "outro.py"
    outro.write_text("from numpy import normalize\nx = normalize('a')\n", encoding="utf-8")
    assert _normaliza_unicode(outro) == []


def test_nenhuma_quarta_chave_derivada_da_canonica():
    """A DUPLICAÇÃO QUE A PRIMEIRA VERSÃO DESTA GUARDA NÃO VIU.

    `consulta_profundidade.slug` era `_FORA_DO_SLUG.sub("_", normalizar(nome))
    .strip("_")` — o corpo de `codigo_estavel` letra por letra, sem chamar
    `unicodedata` uma vez. Mesmo resultado, e era o "mesmo resultado" que fazia
    a cópia valer a pena tirar: o endereço do N3 ficaria para trás sozinho no
    dia em que a regra canônica mudasse.
    """
    fora = [
        f"{_relativo(p)}:{','.join(str(x) for x in _deriva_chave_de_nome(p))}"
        for p in _modulos()
        if p != CANONICO and _deriva_chave_de_nome(p)
    ]
    assert not fora, (
        "Chave derivada da saída de uma função canônica, fora de "
        "`dominio/texto.py`:\n  "
        + "\n  ".join(fora)
        + "\n\nSe é uma quarta chave, ela mora em `dominio/texto.py` junto das "
        "outras três. Se é uma das três, chame-a pelo nome."
    )


def test_a_varredura_acha_as_derivacoes_do_canonico():
    """O canônico tem DUAS: `achatar_para_comparar` e `codigo_estavel` são
    `sub` sobre `normalizar`. Se a detecção parar de vê-las, o teste acima
    passa por vazio."""
    assert len(_deriva_chave_de_nome(CANONICO)) == 2


def test_a_chave_de_gravacao_colapsa_espaco_interno():
    """O DEFEITO, FIXADO. Era isto que `api/stakeholders._normalizar` não fazia,
    e é o que faz o formulário e a planilha chegarem à mesma chave."""
    assert normalizar("Folha  de  S.Paulo") == "folha de s.paulo"
    assert normalizar("  Águas   do    Rio  ") == "aguas do rio"
    #: Espaço NÃO SEPARÁVEL colado de página web: o NFKD o converte em espaço
    #: comum antes de o regex colapsar.
    assert normalizar("Valor\xa0Econômico") == "valor economico"


def test_as_tres_chaves_sao_diferentes_de_proposito():
    """Se duas delas passarem a coincidir em tudo, uma é redundante — e se
    alguém "unificar" sem ver isto, a unicidade do cadastro muda de regra."""
    nome = "Valor Econômico"
    assert normalizar(nome) == "valor economico"
    #: SEMELHANÇA tira espaço e pontuação: casa com o handle de rede.
    assert achatar_para_comparar(nome) == "valoreconomico"
    #: CÓDIGO troca o que não é alfanumérico por `_`, para caber em URL e SQL.
    assert codigo_estavel(nome) == "valor_economico"
    assert len({normalizar(nome), achatar_para_comparar(nome), codigo_estavel(nome)}) == 3


def test_o_codigo_estavel_faz_o_que_a_funcao_antiga_fazia():
    """Ele saiu de `api/dicionarios._codigo`. Estes casos vêm do que aquela
    função produzia, e não da saída da nova — senão o teste só afirma que nada
    mudou, sem provar que está certo."""
    assert codigo_estavel("Muito relevante") == "muito_relevante"
    assert codigo_estavel("Não identificado") == "nao_identificado"
    assert codigo_estavel("  Tier 1  ") == "tier_1"
    #: Pontuação e corrida de separadores viram UM `_`, e as pontas não ficam com
    #: `_` solto.
    assert codigo_estavel("Imprensa / Mídia") == "imprensa_midia"
    assert codigo_estavel("-- Atenção!! --") == "atencao"
    #: Nome que não deixa nada alfanumérico devolve vazio — quem chama decide o
    #: que fazer, e é o mesmo que a função antiga fazia.
    assert codigo_estavel("***") == ""


def test_onde_o_codigo_estavel_NAO_e_igual_a_funcao_antiga():
    """EU AFIRMEI QUE ERAM IDÊNTICAS EM TODA ENTRADA, E NÃO SÃO.

    A ordem mudou: a antiga fazia `lower()` ANTES de decompor, a nova decompõe
    e só então faz `lower()`. Para o caractere cuja decomposição NFKD produz
    LETRA ASCII MAIÚSCULA, a antiga via a maiúscula e a trocava por `_`:

        `№`        antiga `o`          nova `no`
        `₨`        antiga `s`          nova `rs`
        `™`        antiga ``           nova `tm`
        `㍱`        antiga `h_a`        nova `hpa`
        `Banco № 1`  antiga `banco_o_1`  nova `banco_no_1`

    A NOVA É MELHOR em todos os cinco — `™` virava string vazia —, então a
    mudança fica. O que não fica é a afirmação de que nada mudou.

    E O QUE ELA ALCANÇA, MEDIDO: nenhum dos 256 nomes de dicionário gravados
    diverge entre as duas regras, e `codigo_estavel` só roda na CRIAÇÃO de um
    item (`api/dicionarios.acrescentar`) — o código é gravado uma vez e nunca
    recalculado. Então isto não mexe em linha nenhuma: muda o código que um
    item FUTURO receberia se alguém nomeasse um dicionário com `№` ou `™`.
    """
    assert codigo_estavel("№") == "no"
    assert codigo_estavel("₨") == "rs"
    assert codigo_estavel("™") == "tm"
    assert codigo_estavel("㍱") == "hpa"
    assert codigo_estavel("Banco № 1") == "banco_no_1"
