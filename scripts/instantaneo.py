"""Instantâneos do banco de desenvolvimento, para voltar no tempo.

PARA QUE SERVE. Recriar o banco do zero é a operação normal deste projeto — as
migrations e os semeadores são versionados, e o `README` do compose diz com
razão que não existe dump de distribuição. Mas voltar ao estado de ANTES de uma
carga manual, de uma migration aplicada à mão ou de um `delete` sem `where` é
outra coisa: é histórico local de trabalho, e sem ele a única saída é refazer o
caminho inteiro de memória.

NÃO É BACKUP, E A DIFERENÇA IMPORTA. Isto vive na máquina de quem desenvolve,
numa pasta ignorada pelo Git. Não substitui nada em produção, e não deve ser o
caminho para levar dado de uma máquina a outra — para isso existem as migrations
e os semeadores, que todo mundo roda igual.

O MANIFESTO É A PARTE QUE VALE. Um `.sql` solto numa pasta é uma armadilha:
restaurado sobre um código que já andou, ele traz de volta um schema que a
aplicação não entende mais, e a falha aparece como erro de coluna inexistente
numa tela qualquer. Cada instantâneo grava ao lado:

  o commit do back       para saber contra qual código aquele estado valia
  a contagem de migrations   o sinal mais direto de "o schema é o mesmo?"
  as contagens das tabelas   para conferir, depois de restaurar, que voltou o
  que importam            que se esperava — e não um banco pela metade
  se havia mudança não    um instantâneo tirado com a árvore suja não é
  commitada              reproduzível, e o manifesto diz isso em vez de deixar
                         a pessoa descobrir depois

E `restaurar` COMPARA antes de escrever. Se o instantâneo foi tirado com outra
contagem de migrations, ele avisa e exige `--mesmo-assim`: restaurar por cima e
descobrir o desencontro na tela é o modo de falha que este script existe para
evitar.

USO

    python -m scripts.instantaneo criar ["rótulo curto"]
    python -m scripts.instantaneo listar
    python -m scripts.instantaneo restaurar <id> [--mesmo-assim]
    python -m scripts.instantaneo apagar <id>

Roda de FORA do container, porque fala com o `docker` — o banco é um serviço do
compose, e o `pg_dump` usado é o da própria imagem do Postgres, que casa com a
versão do servidor por construção.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

#: A raiz do repositório — este arquivo mora em `scripts/`.
RAIZ = Path(__file__).resolve().parent.parent

#: Onde os instantâneos ficam. Fora do Git: são megabytes de dado de trabalho,
#: e versioná-los faria todo clone baixar o lixo de quem gerou.
PASTA = RAIZ / ".instantaneos"

#: O PROJETO DO COMPOSE, e por consequência o container.
#:
#: Vem do ambiente para o ENSAIO ser possível: antes de confiar nesta ferramenta
#: é preciso exercitar `criar -> down -v -> restaurar` de verdade, e fazer isso
#: contra a pilha de trabalho é apostar o dado que se quer proteger. Com
#: `INSTANTANEO_PROJETO=ensaio` sobe-se uma pilha paralela (portas próprias,
#: volume próprio) e o ciclo roda inteiro sem tocar no que importa.
#:
#: A SEGURANÇA NÃO VEM DO NOME FIXO, e é por isso que abrir isto não a enfraquece:
#: `_banco_no_ar` confere que o container é mesmo daquele projeto do Compose, que
#: o serviço é `banco`, e que `current_database()` é o esperado. Um nome
#: reaproveitado por outra coisa é recusado pelos rótulos, não pelo nome.
PROJETO = os.environ.get("INSTANTANEO_PROJETO", "painel-reputacional")
CONTAINER = f"{PROJETO}-banco-1"
BANCO = "painel_reputacional"
USUARIO = "postgres"

#: As tabelas cuja contagem diz se a restauração trouxe o que se esperava.
#:
#: NÃO É TODA TABELA, de propósito: a lista existe para ser LIDA por quem
#: restaura, e trinta números ninguém confere. Mas eram sete e passaram a ser
#: onze, por achado de revisão: faltavam sentinelas para "voltou, mas voltou
#: capado" — permissão (`usuario_escopo`), importação em andamento
#: (`importacao`, `importacao_linha`) e o catálogo de risco (`risk_cluster`,
#: `risco`). Um banco sem `usuario_escopo` abre e deixa todo mundo ver tudo.
TABELAS_DE_CONFERENCIA = (
    "usuario",
    "usuario_escopo",
    "instituicao",
    "interlocutor",
    "interacao",
    "tema",
    "risk_cluster",
    "risco",
    "tema_risco",
    "importacao",
    "importacao_linha",
    "mencao",
)


def _docker(*args: str, entrada: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        input=entrada,
        capture_output=True,
    )


def _psql(sql: str) -> str:
    r = _docker("exec", CONTAINER, "psql", "-U", USUARIO, "-d", BANCO, "-tAc", sql)
    if r.returncode != 0:
        raise SystemExit(f"psql falhou: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout.decode("utf-8", "replace").strip()


#: O que identifica O BANCO CERTO, e não um container que por acaso tem o nome.
#:
#: ACHADO DE REVISÃO: confiar só no nome é frágil para uma operação que roda
#: `drop schema public cascade`. Um container reaproveitado, ou outro compose com
#: o mesmo nome de projeto, receberia o drop. Então se confere o rótulo do
#: Compose (projeto e serviço) e o nome do banco de dentro da conexão.
SERVICO_ESPERADO = "banco"


def _banco_no_ar() -> None:
    r = _docker("inspect", "-f", "{{.State.Running}}", CONTAINER)
    if r.returncode != 0 or r.stdout.decode().strip() != "true":
        raise SystemExit(
            f"O container {CONTAINER} não está no ar. Suba a pilha antes:\n"
            "  docker compose -f docker-compose.pilha.yml up -d"
        )

    rotulos = _docker(
        "inspect", "-f",
        '{{index .Config.Labels "com.docker.compose.project"}}'
        "\t"
        '{{index .Config.Labels "com.docker.compose.service"}}'
        "\t"
        '{{index .Config.Labels "com.docker.compose.project.working_dir"}}',
        CONTAINER,
    )
    partes = rotulos.stdout.decode("utf-8", "replace").strip().split("\t")
    projeto, servico, pasta = (partes + ["", "", ""])[:3]

    if (projeto, servico) != (PROJETO, SERVICO_ESPERADO):
        raise SystemExit(
            f"O container {CONTAINER} existe, mas é do projeto {projeto!r}/"
            f"serviço {servico!r} — esperado {PROJETO!r}/{SERVICO_ESPERADO!r}.\n"
            "Isto apagaria o banco errado. Nada foi tocado."
        )

    # E DE QUAL CHECKOUT, que os rótulos de projeto e serviço NÃO provam.
    #
    # Achado de revisão: outro clone do repositório, noutra pasta, sobe um
    # container com o mesmo nome de projeto, o mesmo serviço e o mesmo nome de
    # banco. Os três rótulos acima batem, `current_database()` bate, e o
    # `drop schema public cascade` cairia no banco do clone errado — com as
    # migrations dele, que podem ser outras.
    if pasta and not _mesma_pasta(pasta, RAIZ):
        raise SystemExit(
            f"O container {CONTAINER} foi subido de outra pasta:\n"
            f"  dele:  {pasta}\n"
            f"  aqui:  {RAIZ}\n"
            "São dois checkouts do mesmo projeto, e as migrations podem diferir.\n"
            "Nada foi tocado. Rode de dentro da pasta que subiu a pilha."
        )

    # E O BANCO, de dentro da conexão: o `-d` acima podia estar apontando para
    # outro lugar por variável de ambiente do container.
    atual = _psql("select current_database()")
    if atual != BANCO:
        raise SystemExit(
            f"Conectei e o banco é {atual!r}, não {BANCO!r}. Nada foi tocado."
        )


def _mesma_pasta(a: str | Path, b: str | Path) -> bool:
    """Dois caminhos apontam para o mesmo lugar?

    `os.path.realpath` em vez de comparar texto: o rótulo do Compose vem do
    daemon, e no Windows chega com a caixa e os separadores que o Docker usou —
    `C:\\Users\\...` contra `C:/Users/...`, `Área` contra `A%CC%81rea`. Comparar
    string crua reprovaria o próprio checkout, que é o pior dos dois erros: a
    ferramenta de segurança recusando o caso legítimo ensina a desligá-la.
    """
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _git(*args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8"
    )
    return r.stdout.strip() if r.returncode == 0 else "?"


def _migrations_no_disco() -> int:
    return len(_arquivos_de_migration())


def _arquivos_de_migration() -> list[Path]:
    return sorted((RAIZ / "app" / "banco" / "migrations").glob("*.sql"))


def impressao_das_migrations(arquivos: list[Path] | None = None) -> str:
    """Um hash do NOME e do CONTEÚDO de cada migration, em ordem.

    A CONTAGEM NÃO SERVIA COMO GUARDA, e isto é correção de achado de revisão.
    Este repositório tem três colisões de número — duas `0055`, duas `0060`,
    duas `0061`, de branches paralelos —, então duas árvores podem ter a MESMA
    quantidade de arquivos e schemas diferentes. Um instantâneo de um branch
    restaurado no outro passaria pela guarda e quebraria na tela.

    O CONTEÚDO entra junto do nome porque editar migration publicada acontece
    neste projeto: a `0044` foi alterada depois de aplicada, trocando um
    mapeamento. Mesmo nome, schema diferente — e só o conteúdo denuncia.
    """
    # ORDENA AQUI, e não só em `_arquivos_de_migration`: um achado de revisão
    # notou que o teste de ordem não provava nada porque o ajudante dele já
    # entregava ordenado. Em vez de corrigir só o teste, a invariante passou a
    # valer para qualquer chamador — a impressão é da ÁRVORE, e árvore não tem
    # ordem de leitura.
    resumo = hashlib.sha256()
    for caminho in sorted(
        arquivos if arquivos is not None else _arquivos_de_migration(),
        key=lambda c: c.name,
    ):
        resumo.update(caminho.name.encode("utf-8"))
        resumo.update(hashlib.sha256(caminho.read_bytes()).digest())
    # O HASH INTEIRO, e não truncado: guardá-lo por extenso custa 48 bytes no
    # manifesto e dispensa defender o truncamento depois. Quem lê na tela vê os
    # 16 primeiros, que é o que `listar` imprime.
    return resumo.hexdigest()


def _contagens() -> dict[str, int]:
    """Conta só as tabelas que existem — um instantâneo antigo não tem as novas."""
    existentes = set(
        _psql(
            "select table_name from information_schema.tables "
            "where table_schema = 'public'"
        ).splitlines()
    )
    contagens: dict[str, int] = {}
    for tabela in TABELAS_DE_CONFERENCIA:
        if tabela in existentes:
            contagens[tabela] = int(_psql(f"select count(*) from {tabela}") or 0)
    return contagens


def _manifesto(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def _instantaneos() -> list[tuple[str, dict]]:
    if not PASTA.exists():
        return []
    achados = []
    for m in sorted(PASTA.glob("*.json")):
        try:
            achados.append((m.stem, _manifesto(m)))
        except (OSError, json.JSONDecodeError):
            print(f"  (ignorando manifesto ilegível: {m.name})", file=sys.stderr)
    return achados


# ============================================================ criar


def criar(rotulo: str | None) -> None:
    _banco_no_ar()
    PASTA.mkdir(exist_ok=True)

    agora = datetime.now(UTC).astimezone()
    pedaco = "-" + _limpar(rotulo) if rotulo else ""
    ident = agora.strftime("%Y%m%d-%H%M%S") + pedaco

    r = _docker("exec", CONTAINER, "pg_dump", "-U", USUARIO, "-d", BANCO)
    if r.returncode != 0:
        raise SystemExit(f"pg_dump falhou: {r.stderr.decode('utf-8', 'replace')[:400]}")

    # GZIP porque um dump deste banco passa de 5 MB em texto, e são vários por
    # dia de trabalho. O `.sql.gz` ainda abre com `zcat` quando alguém quiser ler.
    destino = PASTA / f"{ident}.sql.gz"
    destino.write_bytes(gzip.compress(r.stdout, compresslevel=6))

    sujo = _git("status", "--porcelain")
    manifesto = {
        "quando": agora.isoformat(timespec="seconds"),
        "rotulo": rotulo or "",
        "commit": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "arvore_suja": bool(sujo),
        "migrations_no_disco": _migrations_no_disco(),
        # A GUARDA DE VERDADE. A contagem fica por legibilidade; é esta que
        # `restaurar` compara — ver `impressao_das_migrations`.
        "impressao_das_migrations": impressao_das_migrations(),
        "contagens": _contagens(),
        "bytes_comprimidos": destino.stat().st_size,
    }
    (PASTA / f"{ident}.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"instantâneo {ident}")
    print(f"  {destino.stat().st_size / 1_048_576:.1f} MB  commit {manifesto['commit']}"
          f"  {manifesto['migrations_no_disco']} migrations"
          f"  impressão {manifesto['impressao_das_migrations'][:16]}")
    if manifesto["arvore_suja"]:
        print("  AVISO: árvore com mudança não commitada — este estado não é"
              " reproduzível a partir do commit.")
    for tabela, n in manifesto["contagens"].items():
        print(f"  {tabela:16s} {n}")


def _limpar(rotulo: str) -> str:
    """Rótulo vira parte de nome de arquivo: só ASCII, e só o que é seguro.

    O ACENTO SAI, e isto é conserto de defeito que um teste pegou: `isalnum()`
    é VERDADEIRO para letra acentuada em Python, então a versão anterior deixava
    `ç` e `á` passarem para o nome do arquivo. Num caminho que já mora sob
    "Área de Trabalho" no OneDrive, acrescentar acento ao nome do instantâneo é
    pedir para a ferramenta de recuperação falhar justamente na hora em que se
    precisa dela.
    """
    sem_acento = unicodedata.normalize("NFKD", rotulo.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    seguro = "".join(
        c if (c.isalnum() and c.isascii()) or c in "-_" else "-" for c in sem_acento
    )
    return "-".join(p for p in seguro.split("-") if p)[:40]


# =========================================================== listar


def listar() -> None:
    achados = _instantaneos()
    if not achados:
        print("nenhum instantâneo ainda. `python -m scripts.instantaneo criar`")
        return
    print(f"{len(achados)} instantâneo(s), do mais antigo ao mais novo:\n")
    for ident, m in achados:
        sujo = "  (árvore suja)" if m.get("arvore_suja") else ""
        print(f"  {ident}")
        print(f"     {m['quando']}  commit {m.get('commit', '?')}"
              f"  {m.get('migrations_no_disco', '?')} migrations"
              f"  impressão {str(m.get('impressao_das_migrations', '?'))[:16]}"
              f"{sujo}")
        if m.get("rotulo"):
            print(f"     {m['rotulo']}")
        contagens = m.get("contagens", {})
        if contagens:
            print("     " + "  ".join(f"{k}={v}" for k, v in contagens.items()))
        print()


# ========================================================= restaurar


def restaurar(ident: str, mesmo_assim: bool) -> None:
    _banco_no_ar()
    dump = PASTA / f"{ident}.sql.gz"
    manifesto = PASTA / f"{ident}.json"
    if not dump.exists():
        raise SystemExit(f"não achei {dump.name}. `listar` mostra o que existe.")

    # SEM MANIFESTO NÃO RESTAURA, e isto é correção de achado de revisão. Sem
    # ele, pulavam-se as DUAS proteções — a guarda do schema e a conferência das
    # contagens — e sobrava um `drop schema` destrutivo guiado por um arquivo
    # sobre o qual não se sabe nada. Um `.sql.gz` órfão existe: basta a escrita
    # do `.json` falhar entre o dump e o manifesto.
    if not manifesto.exists():
        if not mesmo_assim:
            raise SystemExit(
                f"{dump.name} não tem manifesto ({manifesto.name}).\n"
                "Sem ele não há como conferir se o schema daquele estado casa com o\n"
                "código de hoje, nem se a restauração trouxe tudo — e o caminho\n"
                "começa apagando o banco atual. Se você sabe de onde veio esse\n"
                "arquivo, repita com --mesmo-assim."
            )
        print(f"  AVISO: {ident} sem manifesto — restaurando às cegas.")

    m = _manifesto(manifesto) if manifesto.exists() else {}
    agora = impressao_das_migrations()
    entao = m.get("impressao_das_migrations")

    if entao is not None and entao != agora and not mesmo_assim:
        raise SystemExit(
            f"As migrations mudaram desde este instantâneo.\n"
            f"  instantâneo: {m.get('migrations_no_disco', '?')} arquivos,"
            f" impressão {str(entao)[:16]}\n"
            f"  hoje:        {_migrations_no_disco()} arquivos,"
            f" impressão {agora[:16]}\n\n"
            "A impressão é do NOME e do CONTEÚDO de cada migration, em ordem — ela\n"
            "muda tanto quando uma nasce quanto quando uma publicada é editada (o\n"
            "que acontece neste projeto: a `0044` foi alterada depois de aplicada).\n"
            "Restaurar por cima traz de volta um schema que o código atual pode não\n"
            "entender, e a falha apareceria como coluna inexistente numa tela, longe\n"
            "daqui. Se é isso mesmo que você quer (voltar o código também, por\n"
            "exemplo), repita com --mesmo-assim."
        )

    print(f"restaurando {ident} ({m.get('rotulo') or 'sem rótulo'})")
    print("  o banco atual será APAGADO.")

    # DROP E CREATE DO SCHEMA, e não `drop database`: o banco está com conexões
    # abertas (a API, o front, talvez um psql), e o Postgres recusa derrubar uma
    # base em uso. Trocar o conteúdo do schema `public` tem o mesmo efeito para
    # o que nos interessa e não exige derrubar a pilha.
    #
    # NÃO HÁ `grant all on schema public to public` AQUI, e a ausência é o
    # conserto de um achado de revisão — a versão anterior tinha essa linha e
    # ela REABRIA um buraco que a migration fecha. A `0005_auditoria` faz
    # `revoke create on schema public from public` porque as funções
    # `security definer` dela usam `search_path = public`: com CREATE liberado,
    # um papel qualquer planta uma função com nome de built-in e a função
    # privilegiada passa a chamá-la. O `pg_dump` NÃO grava esse `revoke` (ele
    # dumpa grants, não a ausência deles), então quem reconstrói o schema tem de
    # refazê-lo — e é o que a última linha abaixo faz.
    #
    # Os `grant usage` das roles `painel_*` vêm no dump; elas são objetos de
    # CLUSTER, criadas pelas migrations 0005/0006/0009, e o `drop schema` não as
    # toca.
    for sql in (
        "drop schema public cascade",
        # `authorization pg_database_owner` para o dono bater com o de um banco
        # recém-migrado: do Postgres 15 em diante o `public` nasce desse papel, e
        # um `create schema public` simples o deixaria com `postgres`. Não muda o
        # fluxo (as migrations rodam como `postgres`), mas a diferença seria uma
        # pegadinha para quem comparasse os dois bancos — e a graça do
        # instantâneo é justamente poder comparar.
        "create schema public authorization pg_database_owner",
        f"grant all on schema public to {USUARIO}",
        "grant usage on schema public to public",
        "revoke create on schema public from public",
    ):
        r = _docker("exec", CONTAINER, "psql", "-U", USUARIO, "-d", BANCO,
                    "-v", "ON_ERROR_STOP=1", "-q", "-c", sql)
        if r.returncode != 0:
            raise SystemExit(
                "falhou ao limpar o schema: "
                + r.stderr.decode("utf-8", "replace").strip()
            )

    r = _docker(
        "exec", "-i", CONTAINER, "psql", "-U", USUARIO, "-d", BANCO,
        "-v", "ON_ERROR_STOP=1", "-q",
        entrada=gzip.decompress(dump.read_bytes()),
    )
    if r.returncode != 0:
        raise SystemExit(
            "A RESTAURAÇÃO FALHOU NO MEIO, e o banco está pela metade: o schema foi\n"
            "apagado e o dump não entrou inteiro. Tente de novo, ou recrie com\n"
            "`down -v` e os semeadores.\n\n"
            + r.stderr.decode("utf-8", "replace")[:600]
        )

    print("\n  restaurado. conferência:")
    esperado = m.get("contagens", {})
    agora_contagens = _contagens()
    for tabela in sorted(set(esperado) | set(agora_contagens)):
        e, a = esperado.get(tabela), agora_contagens.get(tabela)
        marca = "" if e == a else "   <= NÃO BATE"
        print(f"    {tabela:16s} esperado {e}  agora {a}{marca}")
    if esperado and esperado != agora_contagens:
        raise SystemExit(
            "\nAs contagens não batem com o manifesto. O dump pode estar truncado."
        )

    # E A PERMISSÃO DE `public`, que é invariante de segurança e não contagem.
    #
    # Vira asserção aqui porque já falhou uma vez: a versão anterior deste script
    # restaurava com CREATE liberado para PUBLIC e ninguém notava — o banco
    # abria, as telas funcionavam, e só a garantia em que as funções
    # `security definer` se apoiam tinha ido embora. Um banco restaurado mais
    # permissivo que o migrado é defeito, não detalhe.
    if _psql("select has_schema_privilege('public', 'public', 'CREATE')") != "f":
        raise SystemExit(
            "\nO schema `public` ficou com CREATE para PUBLIC depois da"
            " restauração.\n"
            "A `0005_auditoria` revoga isso de propósito: as funções"
            " `security definer`\n"
            "dela usam `search_path = public`, e com CREATE liberado um papel"
            " qualquer\n"
            "planta uma função com nome de built-in. Rode à mão e confira:\n"
            "  revoke create on schema public from public"
        )
    print("    permissão de `public`  sem CREATE para PUBLIC (como a 0005 exige)")
    print("\n  Reinicie a API para ela soltar as conexões do schema antigo:")
    print("    docker compose -f docker-compose.pilha.yml restart api")


# ============================================================ apagar


def apagar(ident: str) -> None:
    achou = False
    for sufixo in (".sql.gz", ".json"):
        caminho = PASTA / f"{ident}{sufixo}"
        if caminho.exists():
            caminho.unlink()
            achou = True
    print(f"apagado {ident}" if achou else f"não achei {ident}")


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m scripts.instantaneo",
        description="Instantâneos do banco de desenvolvimento.",
    )
    sub = p.add_subparsers(dest="acao", required=True)

    c = sub.add_parser("criar", help="tira um instantâneo do estado atual")
    c.add_argument("rotulo", nargs="?", help='ex: "antes de recriar"')

    sub.add_parser("listar", help="mostra os instantâneos e o que cada um tinha")

    r = sub.add_parser("restaurar", help="volta o banco a um instantâneo")
    r.add_argument("id")
    r.add_argument(
        "--mesmo-assim", action="store_true",
        help="restaura mesmo com contagem de migrations diferente",
    )

    a = sub.add_parser("apagar", help="remove um instantâneo")
    a.add_argument("id")

    args = p.parse_args()
    if args.acao == "criar":
        criar(args.rotulo)
    elif args.acao == "listar":
        listar()
    elif args.acao == "restaurar":
        restaurar(args.id, args.mesmo_assim)
    elif args.acao == "apagar":
        apagar(args.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
