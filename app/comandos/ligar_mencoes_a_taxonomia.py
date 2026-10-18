"""Liga as menções já gravadas aos três níveis da taxonomia. Idempotente.

    python -m app.comandos.ligar_mencoes_a_taxonomia [--lote 5000] [--simular]

É O BACKFILL DA `0098`, e ele é um comando em vez de um `update` dentro da
migration por uma razão medida, não por gosto: fazê-lo em SQL exigiria
reimplementar ali DUAS regras que já existem em Python — o `normalizar` de
`dominio/texto.py` e a precedência de seis passos entre os níveis. A `0097`
tentou exatamente isso com a primeira, e o preço está no cabeçalho dela: a
versão SQL divergia da Python em 67 de 87 valores reais, todos pelo travessão,
reintroduzindo o defeito que a migration existia para consertar.

Aqui não há segunda regra: este comando chama `temas_da_mencao.arvore(...)` e
`Arvore.resolver(...)`, exatamente o que a ingestão mensal chama. Se a regra
mudar, ele muda junto, sem ninguém lembrar de atualizar um SQL.

IDEMPOTENTE, E O CRITÉRIO É "OS TRÊS NULOS": a linha que já tem qualquer nível
não é tocada. Rodar duas vezes não muda nada na segunda, e rodar depois de uma
ingestão não desfaz o que ela ligou.

O CRITÉRIO É `bloco_tema_id is null`, E NÃO "OS TRÊS NULOS". O "três nulos" foi
a primeira versão e estava ERRADO: a intenção era não reprocessar, e o efeito
foi pular as 29.701 menções que já tinham `tema_id` — justamente as que têm o N3
e cujo N2 e N1 são leitura direta da árvore. Rodei, medi, e `n3_sem_n1` deu
29.701 de 29.701: toda menção com subtema ficou sem pilar, o oposto do que a
`0098` existe para fazer.

O MEDO QUE JUSTIFICAVA O CRITÉRIO ERRADO era laço infinito: a linha que não
resolve continua casando o `where` e voltaria no lote seguinte. Quem resolve isso
é o CURSOR (`id > ultimo`), e não o filtro — cada linha é vista uma vez por
execução, resolva ou não. São 1.955 linhas assim hoje; relê-las a cada execução
custa um `index scan` e nada mais.

EM LOTES, com `commit` por lote: são 104.670 menções na base local e o volume
cresce todo mês. Um `update` só manteria a tabela inteira travada para a escrita
durante a subida do mês seguinte.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter

from sqlalchemy import select, update

from app.banco.sessao import obter_fabrica_de_sessao
from app.banco.tabelas_score import Mencao
from app.casos_de_uso import temas_da_mencao

#: Quantas menções por transação. 5.000 é ~1s de `update` e um lote que cabe
#: folgado na memória com três colunas por linha.
LOTE_PADRAO = 5_000


def _parsear(argv: list[str] | None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        prog="ligar_mencoes_a_taxonomia",
        description="Backfill dos três níveis da taxonomia em `mencao` (0098).",
    )
    analisador.add_argument(
        "--lote", type=int, default=LOTE_PADRAO, help=f"padrão: {LOTE_PADRAO}"
    )
    analisador.add_argument(
        "--simular",
        action="store_true",
        help="conta o que ligaria e NÃO grava nada — para conferir antes.",
    )
    return analisador.parse_args(argv)


def executar(*, lote: int = LOTE_PADRAO, simular: bool = False) -> Counter[str]:
    """Liga o que estiver por ligar. Devolve a contagem por nível mais fundo."""
    fabrica = obter_fabrica_de_sessao()
    contagem: Counter[str] = Counter()

    with fabrica() as sessao:
        arvore = temas_da_mencao.arvore(sessao)
        #: A ÁRVORE UMA VEZ, FORA DO LAÇO: são 7 + 41 + 104 nomes e eles não
        #: mudam no meio de um backfill. Recarregar por lote faria o resultado
        #: depender de alguém mexer no cadastro durante a execução.

    #: O CURSOR, E NÃO SÓ `limit`. A linha que não resolve NÃO é atualizada,
    #: então ela continua casando o `where` do próximo lote. Com `limit` puro, um
    #: lote formado só de irresolúveis devolveria sempre as mesmas linhas: ou
    #: lacinho infinito, ou — se a saída fosse "parar quando nada mudou" — parada
    #: ANTES de alcançar as resolvíveis que estavam atrás delas. Paginar pelo
    #: `id` sempre avança, e cada linha é vista uma vez só.
    #:
    #: `order by id` é estável aqui porque `mencao.id` é uuid4 gerado na
    #: gravação e imutável: nada reordena a página sob o cursor.
    ultimo: uuid.UUID | None = None

    while True:
        with fabrica() as sessao:
            #: AS COLUNAS, NÃO O OBJETO: `select(Mencao)` traria 36 colunas de
            #: 5.000 linhas para decidir sobre quatro.
            consulta = (
                select(
                    Mencao.id,
                    Mencao.tema_id,
                    Mencao.tema_texto,
                    Mencao.subtema,
                    Mencao.atributo,
                )
                .where(Mencao.bloco_tema_id.is_(None))
                .order_by(Mencao.id)
                .limit(lote)
            )
            if ultimo is not None:
                consulta = consulta.where(Mencao.id > ultimo)
            linhas = sessao.execute(consulta).all()
            if not linhas:
                break
            ultimo = linhas[-1][0]

            ligadas = 0
            for ident, tema_id, tema_texto, subtema, atributo in linhas:
                niveis = arvore.resolver(
                    #: O `tema_id` QUE A LINHA JÁ TEM ENTRA NA RESOLUÇÃO, e foi
                    #: o defeito da primeira versão deste comando: sem ele, as
                    #: 29.701 menções que já tinham N3 saíam daqui com N3 e sem
                    #: N2 e sem N1 — exatamente as linhas cujo pilar é o mais
                    #: confiável de derivar. Medido depois de rodar: `n3_sem_n1`
                    #: dava 29.701 de 29.701.
                    tema_id=tema_id,
                    tema_texto=tema_texto,
                    subtema=subtema,
                    atributo=atributo,
                )
                contagem[niveis.nivel_mais_fundo or "sem_nivel"] += 1
                if niveis.nivel_mais_fundo is None:
                    #: São 914 linhas assim hoje (`Marca empregadora` 733,
                    #: `Outros` 181): o fornecedor fala um N1 que o cadastro não
                    #: tem. Ficam nulas de propósito.
                    continue
                ligadas += 1
                if not simular:
                    sessao.execute(
                        update(Mencao)
                        .where(Mencao.id == ident)
                        .values(
                            bloco_tema_id=niveis.n1_id,
                            macro_tema_id=niveis.n2_id,
                            tema_id=niveis.n3_id,
                        )
                    )

            if simular:
                print(
                    f"simulação: {len(linhas)} menções lidas, {ligadas} ligariam."
                )
            else:
                sessao.commit()

    return contagem


def main(argv: list[str] | None = None) -> int:
    opcoes = _parsear(argv)
    contagem = executar(lote=opcoes.lote, simular=opcoes.simular)
    total = sum(contagem.values())
    print(f"menções avaliadas: {total}")
    for nivel in ("n3", "n2", "n1", "sem_nivel"):
        if contagem[nivel]:
            print(f"  {nivel:>9}: {contagem[nivel]}")
    if contagem["sem_nivel"]:
        print(
            "\nas `sem_nivel` falam um vocabulário que o cadastro não tem — é "
            "cobrança ao fornecedor ou cadastro a completar, não defeito daqui."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
