"""Liga as menções já gravadas à concessionária do cadastro. Idempotente.

    python -m app.comandos.ligar_mencoes_a_concessionaria [--lote 5000] [--simular]

É O BACKFILL DA `0099`, e é comando e não `update` dentro da migration pela
mesma razão medida do seu irmão `ligar_mencoes_a_taxonomia`: fazê-lo em SQL
exigiria reimplementar ali o `normalizar` de `dominio/texto.py`, e a `0097` já
pagou esse preço — a versão SQL divergia da Python em 67 de 87 valores reais.

Aqui não há segunda regra: este comando chama `unidade_da_mencao.cadastro(...)`
e `Cadastro.resolver(...)`, exatamente o que a ingestão mensal chama.

IDEMPOTENTE, E O CRITÉRIO É `unidade_negocio_id is null`: a linha já ligada não
é tocada, e rodar depois de uma subida não desfaz o que ela ligou.

QUEM GARANTE O FIM DO LAÇO É O CURSOR (`id > ultimo`), e não o `where`. A linha
que não resolve continua casando o filtro e voltaria no lote seguinte para
sempre; paginando pelo `id`, cada linha é vista uma vez por execução. São ~28
mil linhas irresolúveis hoje, e relê-las custa um `index scan`.

O QUE ELE NÃO FAZ, E É O PONTO: não adivinha bloco. "Águas do Rio" (9.411
menções) são duas linhas do cadastro e "Águas do Pará" (4.267) são quatro.
Elas saem daqui nulas, e saem nulas de propósito — ver `unidade_da_mencao`.
O relatório final as separa das que o cadastro simplesmente não tem, porque os
dois casos têm consertos diferentes.

E NÃO TOCA `unidade_texto`. A palavra do fornecedor fica onde está: é contra
ela que a carga é auditável, e é dela que este comando deriva a chave. Um
backfill que reescrevesse o texto apagaria a evidência de como a linha entrou.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter

from sqlalchemy import select, update

from app.banco.sessao import obter_fabrica_de_sessao

#: AS TABELAS QUE `mencao` REFERENCIA, importadas só para existirem no metadata.
#:
#: Mesmo idioma de `ligar_mencoes_a_taxonomia` e de `semear_score`: o `update`
#: em lote passa pelo caminho de ORM do SQLAlchemy, que configura o mapper
#: inteiro e exige resolver TODA chave estrangeira de `Mencao`. Sem estes
#: imports o comando morre na primeira gravação com `NoReferencedTableError`.
from app.banco.tabelas_acesso import Usuario  # noqa: F401
from app.banco.tabelas_catalogo import UnidadeNegocio  # noqa: F401
from app.banco.tabelas_score import Mencao
from app.banco.tabelas_stakeholders import Instituicao  # noqa: F401
from app.casos_de_uso import unidade_da_mencao

LOTE_PADRAO = 5_000


def _parsear(argv: list[str] | None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(
        prog="ligar_mencoes_a_concessionaria",
        description="Backfill de `mencao.unidade_negocio_id` (0099).",
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
    """Liga o que estiver por ligar.

    Devolve a contagem em quatro baldes — `ligadas`, `ambiguas` (o cadastro tem
    mais de uma candidata), `desconhecidas` e `sem_texto` —, porque cada um pede
    uma ação diferente, de uma pessoa diferente, e um relatório que os somasse
    mandaria todo mundo para o mesmo lugar errado.
    """
    fabrica = obter_fabrica_de_sessao()
    contagem: Counter[str] = Counter()

    with fabrica() as sessao:
        #: O CADASTRO UMA VEZ, FORA DO LAÇO: são 29 unidades e 5 apelidos, e
        #: recarregá-los por lote faria o resultado depender de alguém mexer no
        #: cadastro durante a execução.
        cadastro = unidade_da_mencao.cadastro(sessao)

    ultimo: uuid.UUID | None = None

    while True:
        with fabrica() as sessao:
            consulta = (
                select(Mencao.id, Mencao.unidade_texto)
                .where(Mencao.unidade_negocio_id.is_(None))
                .order_by(Mencao.id)
                .limit(lote)
            )
            if ultimo is not None:
                consulta = consulta.where(Mencao.id > ultimo)
            linhas = sessao.execute(consulta).all()
            if not linhas:
                break
            ultimo = linhas[-1][0]

            alteracoes: list[dict[str, object]] = []
            for ident, unidade_texto in linhas:
                achada = cadastro.resolver(unidade_texto)
                if achada is None:
                    #: TRÊS BALDES E NÃO DOIS. A primeira versão somava a linha
                    #: SEM texto às `desconhecidas`, e aí o relatório dizia
                    #: "nomeiam operação que o cadastro não tem" sobre 37 linhas
                    #: que não nomeiam nada — a frase mandaria alguém cadastrar
                    #: uma unidade para resolver um campo em branco.
                    if not (unidade_texto or "").strip():
                        contagem["sem_texto"] += 1
                        continue
                    chave = unidade_da_mencao.familia(str(unidade_texto))
                    contagem[
                        "ambiguas" if chave in cadastro.familias else "desconhecidas"
                    ] += 1
                    continue
                contagem["ligadas"] += 1
                #: A CHAVE PRIMÁRIA NO DICIONÁRIO, e não num `where` explícito:
                #: é o que o "ORM Bulk UPDATE by Primary Key" espera. Ver o
                #: comentário equivalente em `ligar_mencoes_a_taxonomia`, que
                #: registra as duas recusas que eu levei por brigar com ele.
                alteracoes.append({"id": ident, "unidade_negocio_id": achada})

            if alteracoes and not simular:
                sessao.execute(update(Mencao), alteracoes)

            if simular:
                print(
                    f"simulação: {len(linhas)} menções lidas, "
                    f"{len(alteracoes)} ligariam."
                )
            else:
                sessao.commit()

    return contagem


def main(argv: list[str] | None = None) -> int:
    opcoes = _parsear(argv)
    contagem = executar(lote=opcoes.lote, simular=opcoes.simular)
    total = sum(contagem.values())
    print(f"menções avaliadas: {total}")
    for balde in ("ligadas", "ambiguas", "desconhecidas", "sem_texto"):
        if contagem[balde]:
            print(f"  {balde:>14}: {contagem[balde]}")
    if contagem["ambiguas"]:
        print(
            "\nas `ambiguas` têm o nome CERTO e mesmo assim não ligam: o cadastro "
            "tem mais de uma unidade com aquele nome-base (os blocos). O conserto "
            "é o fornecedor informar o bloco, ou um apelido declarado."
        )
    if contagem["desconhecidas"]:
        print(
            "as `desconhecidas` nomeiam operação que o cadastro não tem. O "
            "conserto é cadastrá-la — ou aceitar que ela não é da Aegea."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
