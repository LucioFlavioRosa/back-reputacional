"""Normalização de nome — a mesma regra na carga, na busca e na comparação.

`nome_normalizado` existe para a importação deduplicar "Radamés" e "Radames"
antes de criar as chaves estrangeiras. Usar a mesma coluna na busca livre faz o
usuário encontrar o registro digitando sem acento, sem custo adicional: o
índice de trigrama já está sobre ela.

Se a carga e a busca normalizassem de formas diferentes, a busca deixaria de
encontrar exatamente os nomes que a carga uniu — por isso mora aqui, e não
duplicada nos dois lados.

E ESTAVA DUPLICADA ASSIM MESMO, com regra diferente, até 17/10/2026.
`api/stakeholders.py` tinha o seu próprio `_normalizar` e **não colapsava
espaço interno**: a mesma instituição criada pelo FORMULÁRIO com espaço duplo
gerava `nome_normalizado` diferente do que a PLANILHA geraria, e entrava como
segunda instituição — exatamente a duplicata que aquela função dizia existir
para impedir. Ninguém tinha digitado espaço duplo ainda (medido: zero linhas
divergentes em 4.419 cadastros), então o defeito era latente.

AS TRÊS CHAVES QUE SAEM DE UM NOME moram aqui, e as três são diferentes DE
PROPÓSITO. Quem precisar de uma quarta acrescenta nesta lista, e não no módulo
onde está trabalhando — é o que `test_a_chave_do_nome_sai_de_um_lugar_so.py`
exige:

    normalizar             a chave de GRAVAÇÃO (unicidade do cadastro)
    achatar_para_comparar  a chave de SEMELHANÇA (busca, fila de duplicados)
    codigo_estavel         o CÓDIGO de um item de dicionário (chave de API)
"""

from __future__ import annotations

import re
import unicodedata

_ESPACOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados. A chave de GRAVAÇÃO."""
    sem_acento = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return _ESPACOS.sub(" ", sem_acento).strip().lower()


_SO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def achatar_para_comparar(nome: str) -> str:
    """A chave de SEMELHANÇA: `Valor Econômico` e `valoreconomico` coincidem.

    NÃO É `normalizar`, E A DIFERENÇA É O PONTO. `normalizar` é a chave de
    GRAVAÇÃO, que carrega a unicidade do cadastro, e nela `valoreconomico` e
    `valor economico` são dois cadastros legítimos. Aqui o espaço e a pontuação
    saem, e os dois coincidem — porque o fornecedor de redes escreve o handle
    (`valoreconomico`, `bmc.news`, `gazeta_de_piracicaba`) e o clipping escreve o
    nome ("Valor Econômico").

    REGRA DE BUSCA, NUNCA DE GRAVAÇÃO: a semelhança não prova identidade. `Diário
    SM` e `Diários M` coincidem assim, e `bmc.news` coincide com DOIS veículos —
    então ela serve para PERGUNTAR, e quem responde é gente.

    MORA AQUI, E NÃO NO CASO DE USO, pelo mesmo motivo que `normalizar`: a
    ingestão precisa dela para não CRIAR o par, e a fila de duplicados para
    PERGUNTAR sobre ele. Medido antes de mover: a ingestão buscava por
    `normalizar` — que preserva o espaço — e criava `Neo Feed` ao lado de
    `Neofeed`; eram 5 pares `veiculo`+`veiculo` assim na base, mais 59
    `perfil_rede`+`veiculo`. Ela fabricava exatamente o que a fila perguntava.
    """
    return _SO_ALFANUMERICO.sub("", normalizar(nome))


_NAO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def codigo_estavel(nome: str) -> str:
    """O `codigo` de um item de dicionário: `Muito relevante` → `muito_relevante`.

    É A TERCEIRA CHAVE, e a diferença das outras duas é o que ela serve: este
    código vai para a URL, para o SQL e para o front, e por isso só pode ter
    `[a-z0-9_]` — um acento ou um espaço ali quebraria o caminho.

    NÃO É `achatar_para_comparar`, que REMOVE o que não é alfanumérico
    (`valor_economico` viraria `valoreconomico` e perderia a legibilidade do
    código); aqui o que não é alfanumérico vira `_`, um por corrida.

    MORAVA EM `api/dicionarios.py` como `_codigo`, repetindo a linha de NFKD de
    `normalizar`. Está aqui pelo mesmo motivo que as outras duas: chave derivada
    de nome é regra, e regra que mora em dois lugares divergente em um deles.
    """
    return _NAO_ALFANUMERICO.sub("_", normalizar(nome)).strip("_")


#: QUÃO PARECIDAS DUAS CHAVES PRECISAM SER PARA ALGUÉM SER PERGUNTADO.
#:
#: MEDIDO no cadastro de 3.785 nomes ativos, e não escolhido:
#:
#:     corte 0,95 ....  124 pares        corte 0,85 ....  494 pares
#:     corte 0,90 ....  231 pares        corte 0,80 .... 1512 pares
#:
#: Dos 231 em 0,90, 101 são de chave IGUAL e 130 só parecidos — fila de trabalho
#: finito, com uma decisão por par. Em 0,80 são 1.512 perguntas, e aí vale o
#: argumento da `0078`: "a fila deixa de ser fila e passa a ser ruído, e o ruído é
#: o que faz ninguém olhar".
SEMELHANCA_MINIMA = 0.90
