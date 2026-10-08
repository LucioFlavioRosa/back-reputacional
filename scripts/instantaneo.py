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
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

#: A raiz do repositório — este arquivo mora em `scripts/`.
RAIZ = Path(__file__).resolve().parent.parent

#: Onde os instantâneos ficam. Fora do Git: são megabytes de dado de trabalho,
#: e versioná-los faria todo clone baixar o lixo de quem gerou.
PASTA = RAIZ / ".instantaneos"

CONTAINER = "painel-reputacional-banco-1"
BANCO = "painel_reputacional"
USUARIO = "postgres"

#: As tabelas cuja contagem diz se a restauração trouxe o que se esperava.
#:
#: NÃO É TODA TABELA, de propósito: a lista existe para ser LIDA por quem
#: restaura. Trinta números ninguém confere; estes sete respondem "a base está
#: inteira?" — cadastro, agenda, taxonomia, risco e o volume das Lentes.
TABELAS_DE_CONFERENCIA = (
    "usuario",
    "instituicao",
    "interlocutor",
    "interacao",
    "tema",
    "tema_risco",
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


def _banco_no_ar() -> None:
    r = _docker("inspect", "-f", "{{.State.Running}}", CONTAINER)
    if r.returncode != 0 or r.stdout.decode().strip() != "true":
        raise SystemExit(
            f"O container {CONTAINER} não está no ar. Suba a pilha antes:\n"
            "  docker compose -f docker-compose.pilha.yml up -d"
        )


def _git(*args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8"
    )
    return r.stdout.strip() if r.returncode == 0 else "?"


def _migrations_no_disco() -> int:
    return len(list((RAIZ / "app" / "banco" / "migrations").glob("*.sql")))


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
        "contagens": _contagens(),
        "bytes_comprimidos": destino.stat().st_size,
    }
    (PASTA / f"{ident}.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"instantâneo {ident}")
    print(f"  {destino.stat().st_size / 1_048_576:.1f} MB  commit {manifesto['commit']}"
          f"  {manifesto['migrations_no_disco']} migrations")
    if manifesto["arvore_suja"]:
        print("  AVISO: árvore com mudança não commitada — este estado não é"
              " reproduzível a partir do commit.")
    for tabela, n in manifesto["contagens"].items():
        print(f"  {tabela:16s} {n}")


def _limpar(rotulo: str) -> str:
    """Rótulo vira parte de nome de arquivo: só o que é seguro em todo sistema."""
    seguro = "".join(c if c.isalnum() or c in "-_" else "-" for c in rotulo.lower())
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
              f"  {m.get('migrations_no_disco', '?')} migrations{sujo}")
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

    m = _manifesto(manifesto) if manifesto.exists() else {}
    agora = _migrations_no_disco()
    entao = m.get("migrations_no_disco")

    if entao is not None and entao != agora and not mesmo_assim:
        raise SystemExit(
            f"O instantâneo foi tirado com {entao} migrations no disco; hoje são"
            f" {agora}.\n"
            "Restaurar por cima traz de volta um schema que o código atual pode não\n"
            "entender — a falha apareceria como coluna inexistente numa tela, longe\n"
            "daqui. Se é isso mesmo que você quer (voltar o código também, por\n"
            "exemplo), repita com --mesmo-assim."
        )

    print(f"restaurando {ident} ({m.get('rotulo') or 'sem rótulo'})")
    print("  o banco atual será APAGADO.")

    # DROP E CREATE DO SCHEMA, e não `drop database`: o banco está com conexões
    # abertas (a API, o front, talvez um psql), e o Postgres recusa derrubar uma
    # base em uso. Trocar o conteúdo do schema `public` tem o mesmo efeito para
    # o que nos interessa e não exige derrubar a pilha.
    for sql in (
        "drop schema public cascade",
        "create schema public",
        f"grant all on schema public to {USUARIO}",
        "grant all on schema public to public",
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
