"""O mapeamento SQLAlchemy e o DDL precisam contar a mesma história.

Enquanto não há Alembic, a migration em SQL é a fonte da verdade do banco e o
ORM é a fonte da verdade do código. Divergência entre os dois só apareceria em
produção, no primeiro `select` de uma coluna que não existe — este teste puxa
esse erro para o momento da edição.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy.orm import configure_mappers

# Importar todos os contextos registra as tabelas no metadata.
import main  # noqa: F401
from app.banco.sessao import Tabela

MIGRATIONS = (
    Path(__file__).resolve().parents[1]
    / "app/banco/migrations"
)

#: O `if not exists` e opcional: sem ele no padrao, o parser leria `if` como
#: nome da tabela e a migration inteira sumiria do retrato — em silencio.
BLOCO_CREATE_TABLE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?(\w+)\s*\((.*?)\n\);",
    re.IGNORECASE | re.DOTALL,
)
#: `add constraint` nao casa aqui porque a palavra `column` e obrigatoria.
REMOVE_TABELA = re.compile(
    r"drop\s+table\s+(?:if\s+exists\s+)?(\w+)", re.IGNORECASE
)
#: Um `alter table` inteiro, ate o `;`. O corpo e varrido depois.
#:
#: Casar `alter table X add column Y` de uma vez veria so a PRIMEIRA coluna de
#: um `alter table` com varias clausulas — que e a forma idiomatica de
#: acrescentar cinco colunas a uma tabela. O ponto cego seria silencioso na
#: direcao que importa: colunas no DDL e ausentes no ORM, que e exatamente o
#: que este arquivo existe para pegar.
#: `if exists` entra no padrao: sem ele, `alter table if exists x ...` faria o
#: parser ler `if` como nome da tabela — e a alteracao inteira seria aplicada a
#: uma tabela fantasma, em silencio.
ALTERA_TABELA = re.compile(
    r"alter\s+table\s+(?:if\s+exists\s+)?(\w+)([^;]*);", re.IGNORECASE
)

#: `alter table X rename to Y`.
#:
#: A 0025 renomeou `relatorio` para `exportacao` ao remover a tela de relatorio,
#: e o parser cego para renomeacao acusou a tabela nova como "no ORM e ausente
#: no DDL" — uma divergencia inventada, num schema correto. E o caso que o
#: comentario de `_colunas_do_sql` previa: a proxima migration usa o que o
#: baseline nao usava.
RENOMEIA_TABELA = re.compile(
    r"alter\s+table\s+(?:if\s+exists\s+)?(\w+)\s+rename\s+to\s+(\w+)",
    re.IGNORECASE,
)

#: Cada clausula `add column` / `drop column` dentro daquele corpo.
#: `add constraint` e `owner to` nao casam, e e o que se quer.
CLAUSULA_DE_COLUNA = re.compile(
    r"\b(add|drop)\s+column\s+(?:if\s+(?:not\s+)?exists\s+)?(\w+)",
    re.IGNORECASE,
)


def _definicoes_por_tabela(sql: str) -> list[tuple[str, list[str]]]:
    """Quebra o corpo de cada `create table` nas suas definições.

    Separado para servir a dois leitores — colunas e chaves estrangeiras — sem
    que a contagem de parênteses exista em duas cópias. Uma delas envelheceria,
    e as duas leituras passariam a discordar sobre o mesmo SQL.

    A contagem de profundidade é o ponto: `check (tier between 1 and 3)` tem
    vírgulas nenhuma, mas `numeric(10, 2)` tem, e quebrar em toda vírgula
    partiria a definição no meio.
    """
    saida: list[tuple[str, list[str]]] = []
    for nome, corpo in BLOCO_CREATE_TABLE.findall(sql):
        definicoes: list[str] = []
        profundidade = 0
        atual = ""
        for caractere in corpo:
            if caractere == "(":
                profundidade += 1
            elif caractere == ")":
                profundidade -= 1
            if caractere == "," and profundidade == 0:
                definicoes.append(atual)
                atual = ""
                continue
            atual += caractere
        definicoes.append(atual)
        saida.append((nome.lower(), definicoes))
    return saida


#: `coluna tipo references outra_tabela(id)` — a forma usada em todo o schema.
REFERENCIA = re.compile(r"^\s*(\w+).*?references\s+(\w+)\s*\(", re.I | re.S)


def chaves_estrangeiras_do_ddl(sql: str | None = None) -> dict[str, set[tuple[str, str]]]:
    """Cada tabela e os pares (coluna, tabela apontada) declarados no DDL.

    Existe porque um retrato só de COLUNAS deixa passar FK que o DDL tem e o
    ORM não: o banco continua barrando, mas o metadata do SQLAlchemy descreve
    a coluna como um inteiro solto — e é o metadata que gera schema em qualquer
    ferramenta que o leia.
    """
    if sql is None:
        sql = "\n".join(
            arquivo.read_text(encoding="utf-8") for arquivo in sorted(MIGRATIONS.glob("*.sql"))
        )
    sql = re.sub(r"--[^\n]*", "", sql)

    chaves: dict[str, set[tuple[str, str]]] = {}
    for tabela, definicoes in _definicoes_por_tabela(sql):
        encontradas = set()
        for definicao in definicoes:
            achado = REFERENCIA.match(definicao)
            if achado and achado.group(1).lower() not in {
                "primary", "foreign", "unique", "check", "constraint",
            }:
                encontradas.add((achado.group(1).lower(), achado.group(2).lower()))
        if encontradas:
            chaves[tabela] = encontradas
    return chaves


def colunas_do_ddl() -> dict[str, set[str]]:
    """O retrato do schema, lido de TODAS as migrations em ordem."""
    return _colunas_do_sql(
        "\n".join(
            arquivo.read_text(encoding="utf-8")
            for arquivo in sorted(MIGRATIONS.glob("*.sql"))
        )
    )


def _colunas_do_sql(sql: str) -> dict[str, set[str]]:
    """Extrai tabela -> colunas, APLICANDO as operações em ordem.

    O baseline define cada objeto uma vez, com `create table`; a partir da 0050
    há `alter table add column`, e o parser tem de aplicá-lo — sem isso ele
    acusaria divergência num schema correto, porque o ORM conhece a coluna e o
    retrato não.

    `drop table` e `drop column` continuam sem uso nas migrations reais. Quem
    os exercita é `test_o_parser_aplica_alter_e_drop`, com SQL próprio.
    """
    # Tira os comentários de linha para não confundir o parser.
    sql = re.sub(r"--[^\n]*", "", sql)

    tabelas: dict[str, set[str]] = {}
    for nome, definicoes in _definicoes_por_tabela(sql):
        nomes = set()
        for definicao in definicoes:
            primeira = definicao.strip().split()
            if not primeira:
                continue
            candidato = primeira[0].lower()
            # "primary key (a, b)" e afins não são colunas.
            if candidato in {"primary", "foreign", "unique", "check", "constraint"}:
                continue
            nomes.add(candidato)
        tabelas[nome.lower()] = nomes

    # A RENOMEAÇÃO VEM ANTES das cláusulas de coluna: quem renomeia costuma
    # ajustar colunas em seguida, já pelo nome NOVO, e aplicar na ordem inversa
    # criaria uma tabela fantasma com o nome novo e deixaria a antiga intacta.
    for antiga, nova in RENOMEIA_TABELA.findall(sql):
        if antiga.lower() in tabelas:
            tabelas[nova.lower()] = tabelas.pop(antiga.lower())

    # A ordem importa: uma coluna acrescentada por uma migration e removida por
    # outra não deve sobrar no retrato. Como a varredura é sobre o texto
    # concatenado em ordem de arquivo, basta aplicar cada operação onde aparece.
    for tabela, corpo in ALTERA_TABELA.findall(sql):
        for operacao, coluna in CLAUSULA_DE_COLUNA.findall(corpo):
            if operacao.lower() == "add":
                tabelas.setdefault(tabela.lower(), set()).add(coluna.lower())
            else:
                tabelas.get(tabela.lower(), set()).discard(coluna.lower())

    # Sem tratar `drop table`, o retrato guardaria uma tabela que uma migration
    # posterior removeu — e o teste que confere "tabela do DDL existe no ORM" a
    # ignoraria em silêncio, porque tabela sem mapeamento é caso esperado.
    for tabela in REMOVE_TABELA.findall(sql):
        tabelas.pop(tabela.lower(), None)

    return tabelas


@pytest.fixture(scope="module")
def ddl() -> dict[str, set[str]]:
    configure_mappers()
    return colunas_do_ddl()


def test_a_migration_foi_lida():
    assert MIGRATIONS.is_dir(), f"Migrations não encontradas em {MIGRATIONS}"
    assert len(colunas_do_ddl()) >= 25


def test_o_parser_aplica_alter_e_drop():
    """Guarda o PARSER, com SQL próprio — e a distinção importa.

    As migrations atuais definem cada objeto uma vez e não usam `alter table`
    nem `drop table`. Um teste que exercitasse esse caminho pelas migrations
    reais passaria por vacuidade: confirmaria a ausência de coisas que nunca
    existiram, e não que o parser sabe aplicá-las.

    A capacidade precisa continuar coberta porque a próxima migration a ser
    escrita provavelmente vai usá-la — e um parser cego para `alter table`
    acusaria divergência num schema correto, ou deixaria de acusar uma real.
    """
    # O corpo precisa terminar com `\n);`, como nas migrations reais: é o que o
    # padrão de `BLOCO_CREATE_TABLE` reconhece. `create table x (a int);` numa
    # linha só NÃO é lido — e escrever assim numa migration futura tiraria a
    # tabela do retrato em silêncio.
    tabelas = _colunas_do_sql(
        """
create table exemplo (
  id     int,
  antiga text
);

create table if not exists opcional (
  codigo text
);

create table descartavel (
  id int
);

create table batizada (
  id     int,
  sobra  text
);

alter table exemplo add column nova text;
alter table exemplo drop column antiga;
alter table if exists batizada rename to rebatizada;
alter table rebatizada drop column if exists sobra;
drop table descartavel;
"""
    )

    assert tabelas["exemplo"] == {"id", "nova"}, "add/drop column não foi aplicado"
    # Sem o `if not exists` opcional no padrão, o parser leria `if` como nome da
    # tabela e a tabela inteira sumiria do retrato — em silêncio.
    assert tabelas["opcional"] == {"codigo"}, "create table if not exists não foi lido"
    assert "descartavel" not in tabelas, "drop table não foi aplicado"
    # A renomeação leva as colunas junto, e o nome antigo não sobra: um retrato
    # com os dois acusaria a tabela velha como "existe no DDL e não no ORM".
    assert "batizada" not in tabelas, "rename to deixou o nome antigo no retrato"
    assert tabelas["rebatizada"] == {"id"}, (
        "rename to não levou as colunas, ou o drop column pelo nome NOVO não foi aplicado"
    )


def test_o_retrato_das_migrations_reais_e_utilizavel():
    """O parser funciona NESTES arquivos, e não só em teoria.

    Confere colunas que o ORM usa e que só aparecem se as migrations certas
    tiverem sido lidas — é o que separa "o parser funciona" de "o parser
    funciona sobre as migrations que existem".
    """
    tabelas = colunas_do_ddl()
    assert {"papel_id", "acesso_expira_em", "papel_concedido_em"} <= tabelas["usuario"]
    assert "codigo" in tabelas["papel"]
    assert {"dimensao", "valor"} <= tabelas["usuario_escopo"]


def test_toda_tabela_do_orm_existe_na_migration(ddl):
    faltando = set(Tabela.metadata.tables) - set(ddl)
    assert not faltando, f"Tabelas mapeadas no ORM e ausentes no DDL: {sorted(faltando)}"


def test_toda_coluna_do_orm_existe_na_migration(ddl):
    divergencias: dict[str, list[str]] = {}
    for nome, tabela in Tabela.metadata.tables.items():
        do_orm = {coluna.name for coluna in tabela.columns}
        sobrando = do_orm - ddl.get(nome, set())
        if sobrando:
            divergencias[nome] = sorted(sobrando)

    assert not divergencias, f"Colunas no ORM e ausentes no DDL: {divergencias}"


def test_toda_chave_estrangeira_do_ddl_esta_declarada_no_orm():
    """O retrato de COLUNAS não basta.

    Uma coluna como `interacao.tier`, com `references relevancia(id)` no DDL e
    sem `ForeignKey` no ORM, não quebra teste nenhum: o banco continua
    recusando um nível inexistente. Quem mente é o metadata do SQLAlchemy — e é
    dele que sai qualquer schema gerado por ferramenta, incluindo o que uma
    migração automática escreveria.

    Confere só o sentido perigoso: FK no DDL e ausente no ORM. O contrário —
    FK no ORM sem estar no DDL — quebraria na aplicação da migration, que é
    barulho suficiente.
    """
    configure_mappers()
    no_ddl = chaves_estrangeiras_do_ddl()

    faltando: dict[str, list[str]] = {}
    for tabela, esperadas in no_ddl.items():
        mapeada = Tabela.metadata.tables.get(tabela)
        if mapeada is None:
            continue  # tabela ainda sem ORM: o teste de tabelas cobre
        do_orm = {
            (coluna.name.lower(), fk.column.table.name.lower())
            for coluna in mapeada.columns
            for fk in coluna.foreign_keys
        }
        ausentes = esperadas - do_orm
        if ausentes:
            faltando[tabela] = sorted(f"{c} -> {t}" for c, t in ausentes)

    assert not faltando, f"Chaves estrangeiras no DDL e ausentes no ORM: {faltando}"


def test_o_leitor_de_chaves_encontra_o_que_deve():
    """Âncora do próprio leitor.

    Sem ela, uma regex que parasse de casar faria o teste acima aprovar
    qualquer ORM — encontraria zero chaves no DDL e concluiria que nenhuma
    falta.
    """
    chaves = chaves_estrangeiras_do_ddl()
    assert ("tier", "relevancia") in chaves["interacao"]
    assert ("frente_id", "frente") in chaves["interacao"]
    assert len(chaves) >= 10


def test_toda_coluna_da_migration_existe_no_orm(ddl):
    divergencias: dict[str, list[str]] = {}
    for nome, colunas in ddl.items():
        tabela = Tabela.metadata.tables.get(nome)
        if tabela is None:
            # Tabelas ainda sem ORM (importacao, relatorio) são esperadas nesta
            # fase; o teste inverso cobre o caso perigoso.
            continue
        faltando = colunas - {coluna.name for coluna in tabela.columns}
        if faltando:
            divergencias[nome] = sorted(faltando)

    assert not divergencias, f"Colunas no DDL e ausentes no ORM: {divergencias}"
