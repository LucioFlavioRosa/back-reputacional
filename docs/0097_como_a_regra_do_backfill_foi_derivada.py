"""Gera a 0097 a partir do Unicode, e PROVA a completude da guarda.

A regra do backfill tem de dar exatamente o mesmo resultado que
`app/dominio/texto.normalizar` (NFKD -> ascii -> colapsa -> trim -> lower).
Em SQL nao existe NFKD, entao a regra e montada em tres partes:

  1. `replace()` para o que o NFKD EXPANDE em mais de um ASCII  (½ -> 12)
  2. `translate()` para o que ele resolve em um ASCII so        (ç -> c)
  3. descartar todo nao-ASCII restante                          (— -> )

As tres juntas cobrem tudo que o NFKD produz DENTRO de U+00A0..U+017F, mais os
quatro coladores de web que um titulo de verdade recebe. Fora disso, a migration
RECUSA em vez de adivinhar — e este script prova que a lista de recusa e
completa, varrendo todos os 1.114.112 codepoints.
"""
from __future__ import annotations

import sys
import unicodedata

FAIXA = range(0x00A0, 0x0180)


def a_ascii(c: str) -> str:
    return unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()


um_para_um: list[tuple[str, str]] = []
expansoes: list[tuple[str, str]] = [(" ", " ")]
for cp in FAIXA:
    c = chr(cp)
    alvo = a_ascii(c)
    if c == " " or not alvo:
        continue
    (um_para_um if len(alvo) == 1 else expansoes).append((c, alvo))
expansoes += [("№", "No"), ("™", "TM"), ("ﬁ", "fi"), ("ﬂ", "fl")]

tratados = {c for c, _ in um_para_um} | {c for c, _ in expansoes}

# ------------------------------------------------- a guarda, e a prova dela
#: Quem ainda divergiria: nao-ASCII, fora do que tratamos, e cujo NFKD produz
#: ASCII. Expressos em FAIXAS, para o regex caber numa linha.
#: DERIVADAS, nao escolhidas: todo codepoint nao-ASCII que nao tratamos e cujo
#: NFKD produz ASCII. Agrupados em faixas contiguas so para o regex caber.
divergentes = [
    cp
    for cp in range(0x110000)
    if cp >= 128 and chr(cp) not in tratados and a_ascii(chr(cp))
]

FAIXAS_DE_RECUSA: list[tuple[int, int]] = []
for cp in divergentes:
    if FAIXAS_DE_RECUSA and cp == FAIXAS_DE_RECUSA[-1][1] + 1:
        FAIXAS_DE_RECUSA[-1] = (FAIXAS_DE_RECUSA[-1][0], cp)
    else:
        FAIXAS_DE_RECUSA.append((cp, cp))


def recusado(cp: int) -> bool:
    return any(a <= cp <= b for a, b in FAIXAS_DE_RECUSA)


faltando = [cp for cp in divergentes if not recusado(cp)]
if faltando:
    print(f"GUARDA INCOMPLETA: {len(faltando)} codepoints")
    sys.exit(1)

print("guarda COMPLETA: varridos 1.114.112 codepoints, "
      f"{len(divergentes)} divergiriam e todos sao recusados")
print(f"  {len(um_para_um)} pares no translate(), {len(expansoes)} replaces, "
      f"{len(FAIXAS_DE_RECUSA)} faixas recusadas")

DE = "".join(c for c, _ in um_para_um)
PARA = "".join(a for _, a in um_para_um)


def sql_de_replaces(coluna: str) -> str:
    saida = coluna
    for c, a in expansoes:
        saida = f"replace({saida}, chr({ord(c)}), '{a}')"
    return saida


def expressao(coluna: str) -> str:
    """A regra inteira, do jeito que vai para o SQL."""
    return (
        "lower(btrim(regexp_replace(regexp_replace(translate(\n"
        f"              {sql_de_replaces(coluna)},\n"
        f"              '{DE}',\n"
        f"              '{PARA}'\n"
        "            ), '[^[:ascii:]]', '', 'g'), '\\s+', ' ', 'g')))"
    )


def guarda_regex() -> str:
    partes = []
    for a, b in FAIXAS_DE_RECUSA:
        partes.append(f"\\u{a:04x}-\\u{b:04x}" if b <= 0xFFFF else f"\\U{a:08x}-\\U{b:08x}")
    return "[" + "".join(partes) + "]"


TRATADOS_SQL = "".join(sorted(tratados))

MODELO = """\
-- DUAS GRAFIAS DO MESMO NOME NAO PODEM COEXISTIR, e coexistiam em dois lugares.
--
-- `referencia` e `jornalista_matriz` tinham cada uma a SUA regra de chave de
-- nome, escrita em SQL dentro do indice unico:
--
--   0026  referencia         (lower(btrim(titulo)))
--   0049  jornalista_matriz  (lower(regexp_replace(nome,'\\s+',' ','g')),
--                             coalesce(veiculo,''))
--
-- Nenhuma das duas TIRA ACENTO. Entao "Relatorio Anual" com e sem acento
-- entravam como duas referencias -- o comeco de duas versoes circulando, que e
-- o problema que aquela tabela existe para acabar --, e "Tais Hirata" com e sem
-- acento como duas jornalistas, contra o que o comentario da propria 0049
-- promete. A 0026 ainda deixava passar espaco interno duplo, e a 0049 nao
-- normalizava `veiculo` de jeito nenhum.
--
-- POR QUE COLUNA, E NAO UM SQL MELHOR NO INDICE. Indice em Postgres exige
-- expressao IMMUTABLE, e `unaccent()` nao e a mesma coisa que o NFKD + ascii de
-- `dominio/texto.normalizar`. Vale o desenho que `instituicao` ja usava: a
-- COLUNA guarda a chave, a APLICACAO a escreve com a funcao canonica (por um
-- gancho no modelo, que nenhum ponto de escrita pode esquecer), e o indice e
-- sobre a coluna. Uma regra, num lugar so, em Python.
--
-- == O BACKFILL, E POR QUE ELE NAO PODE SER APROXIMADO ==
--
-- A PRIMEIRA VERSAO DESTA MIGRATION ERRAVA AQUI, e a revisao pegou: ela usava
-- `translate()` com os acentos do portugues, o que NAO descarta o nao-ASCII que
-- o NFKD descarta. Medido nos dados reais: 67 dos 87 valores divergiam, todos
-- pelo travessao (U+2014) em "Posicionamento -- Metas", que o `translate`
-- preservava e o `normalizar` descarta. Uma referencia migrada deixaria de
-- colidir com uma criada pela tela -- o defeito que esta migration existe para
-- consertar, reintroduzido por ela mesma.
--
-- (E o teste que eu escrevi para pegar isso percorria ZERO linhas, porque o
-- banco de teste nasce vazio. Ele agora monta o proprio corpus.)
--
-- A REGRA CORRETA TEM TRES PARTES, e este arquivo foi GERADO do Unicode em vez
-- de digitado -- um par de `translate` fora de posicao trocaria uma letra:
--
--   1. `replace()` para o que o NFKD EXPANDE em mais de um ASCII   (1/2 -> 12)
--   2. `translate()` para o que ele resolve em um ASCII so          (c -> c)
--   3. descartar todo nao-ASCII restante                            (-- -> )
--
-- == E A MIGRATION RECUSA EM VEZ DE ADIVINHAR ==
--
-- As tres partes cobrem tudo que o NFKD produz dentro de U+00A0..U+017F, mais
-- quatro coladores de web (No, TM, fi, fl). Para QUALQUER outro caractere cujo
-- NFKD produza ASCII, o SQL nao tem como acertar -- entao a migration PARA, com
-- a linha na mensagem, e alguem decide. A lista de faixas recusadas foi provada
-- completa varrendo os 1.114.112 codepoints: nenhum diverge sem ser recusado.
--
-- SE JA HOUVER PAR DIVERGENTE NO BANCO, o `create unique index` tambem FALHA, e
-- isso tambem e o certo: qual das duas linhas sobrevive e decisao de quem cuida
-- do cadastro. Medido na pilha local: `referencia` 67 linhas e 0 pares;
-- `jornalista_matriz` 10 linhas e 0 pares.
--
-- TUDO NUMA TRANSACAO: se o indice novo falhar, nada fica pela metade -- nem
-- coluna preenchida, nem tabela sem a protecao de unicidade que ela tinha.
--
-- NENHUM GRANT NOVO: permissao no Postgres e por tabela, nao por coluna.

begin;

-- ================================================================ a guarda
do $$
declare
  achado text;
begin
  select titulo into achado from referencia
   where titulo ~ '{GUARDA}' limit 1;
  if achado is not null then
    raise exception 'referencia.titulo contem caractere que o backfill nao sabe '
      'normalizar como `dominio/texto.normalizar` faria: %. Normalize a linha a '
      'mao (ou acrescente o caractere a esta migration) antes de aplicar.', achado;
  end if;

  select nome into achado from jornalista_matriz
   where nome ~ '{GUARDA}' or coalesce(veiculo,'') ~ '{GUARDA}' limit 1;
  if achado is not null then
    raise exception 'jornalista_matriz contem caractere que o backfill nao sabe '
      'normalizar: %. Mesma coisa.', achado;
  end if;
end $$;

-- ============================================================= referencia
alter table referencia add column if not exists titulo_normalizado text;

update referencia
   set titulo_normalizado = {EXPR_TITULO}
 where titulo_normalizado is null;

alter table referencia alter column titulo_normalizado set not null;

drop index if exists referencia_titulo_idx;
create unique index if not exists referencia_titulo_normalizado_idx
  on referencia (titulo_normalizado);

-- ====================================================== jornalista_matriz
alter table jornalista_matriz add column if not exists nome_normalizado text;
alter table jornalista_matriz add column if not exists veiculo_normalizado text;

update jornalista_matriz
   set nome_normalizado = {EXPR_NOME},
       veiculo_normalizado = case when veiculo is null then null
                                  else {EXPR_VEICULO} end
 where nome_normalizado is null;

alter table jornalista_matriz alter column nome_normalizado set not null;

-- O `where ativo` SE MANTEM: a matriz desativa em vez de apagar, e duas linhas
-- inativas da mesma pessoa sao historico, nao duplicata.
--
-- NOME NOVO, E NAO O MESMO `jornalista_matriz_unica`: um `create ... if not
-- exists` com nome ja usado e NO-OP SILENCIOSO, e foi assim que a 0052 pediu um
-- indice que nunca nasceu. `test_dois_indices_nao_disputam_o_mesmo_nome` me
-- parou quando eu reusei o nome.
drop index if exists jornalista_matriz_unica;
create unique index if not exists jornalista_matriz_unica_normalizada
  on jornalista_matriz (nome_normalizado, coalesce(veiculo_normalizado, ''))
  where ativo;

commit;
"""

destino = sys.argv[1]
conteudo = (
    MODELO.replace("{GUARDA}", guarda_regex())
    .replace("{EXPR_TITULO}", expressao("titulo"))
    .replace("{EXPR_NOME}", expressao("nome"))
    .replace("{EXPR_VEICULO}", expressao("veiculo"))
)
with open(destino, "w", encoding="utf-8", newline="\n") as f:
    f.write(conteudo)
print(f"\nescrito: {destino} ({len(conteudo.splitlines())} linhas)")
