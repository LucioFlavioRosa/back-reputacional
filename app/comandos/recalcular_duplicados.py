"""Refaz o pareamento guardado da fila de duplicados. Idempotente.

    python -m app.comandos.recalcular_duplicados

É O BACKFILL DA `0118`, e é obrigatório UMA VEZ depois de aplicá-la: a tabela
nasce vazia, e fila vazia na tela não se distingue de "nenhum duplicado". A rota
`/api/instituicoes/duplicados/estado` existe para a tela nunca cair nessa
confusão, mas quem some com o problema é este comando.

É COMANDO E NÃO `update` DENTRO DA MIGRATION pela mesma razão medida dos seus
irmãos `ligar_mencoes_a_*`: a chave de semelhança é `achatar_para_comparar`, de
`dominio/texto.py`, e reescrevê-la em `regexp_replace` seria a terceira cópia da
mesma regra. A `0097` já pagou esse preço — a versão SQL divergia da Python em 67
de 87 valores reais.

NO DIA A DIA ELE NÃO É NECESSÁRIO: a subida de planilha recalcula sozinha quando
cria cadastro (ver `ingerir_mencoes.ingerir`). Este comando serve para o backfill,
e para quando alguém criou cadastro por fora da subida — pelo CRM, ou por SQL.

CUSTO MEDIDO: 9,6 s em 3.800 cadastros ativos, 43,7 s em 11.000. Roda fora de
requisição, então o teto de 240 s do ingress não se aplica.
"""

from __future__ import annotations

import time

from app.banco.sessao import obter_fabrica_de_sessao
from app.casos_de_uso import atores_duplicados


def main() -> None:
    inicio = time.perf_counter()
    fabrica = obter_fabrica_de_sessao()
    with fabrica() as sessao:
        pares = atores_duplicados.recalcular(sessao)
        sessao.commit()
    print(f"pareamento refeito: {pares} pares em {time.perf_counter() - inicio:.1f} s")


if __name__ == "__main__":
    main()
