"""Faz a lista de veículos valer para os meses JÁ ingeridos. Idempotente.

    python -m app.comandos.reconciliar_lista_de_veiculos [--simular] [--lista imprensa_economica]

É O BACKFILL DA DECISÃO DE 19/10/2026 do dono do produto: "se eu dizer que uma
instituição pertence a categoria de público como imprensa e esfera econômica e
de negócios, todos seus registros devem ser movidos para a lente de mercado,
atualizando tudo" — e, no sentido inverso, tirar a classificação tira os
registros.

COMANDO E NÃO MIGRATION, pela mesma razão dos irmãos `ligar_mencoes_a_*`: a
regra de casamento é `normalizar` de `dominio/texto.py`, que é Python. A `0097`
reimplementou essa função em SQL e divergiu em 67 de 87 valores reais.

`--simular` É O PADRÃO DA CASA PARA ESTE TIPO DE GESTO, e aqui ele é mais do que
conveniência: aplicar reescreve `score_mes_fonte` de meses FECHADOS, e o índice
daqueles meses muda. O número que a diretoria cita muda com ele. Rodar a
simulação primeiro é o "mostre antes" que a conferência da subida de planilha
já segue.

O QUE ELE NÃO RECOMPÕE: `mencao_nao_classificada` — ver o cabeçalho de
`casos_de_uso/reconciliar_lista_de_veiculos`.
"""

from __future__ import annotations

import argparse
import sys

from app.banco.sessao import obter_fabrica_de_sessao
from app.casos_de_uso import reconciliar_lista_de_veiculos as motor


def _parsear(argv: list[str] | None) -> argparse.Namespace:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--lista",
        default=motor.LISTA_PADRAO,
        help="o nome da lista de veículos a reconciliar",
    )
    analisador.add_argument(
        "--simular",
        action="store_true",
        help="só mostra o que mudaria; não escreve",
    )
    return analisador.parse_args(argv)


def _relatar(medida: motor.Reconciliacao) -> None:
    print(f"\nfonte {medida.fonte} (espelho: {medida.espelho}, lista: {medida.lista})")
    if medida.entram:
        print("  passam a contar:")
        for veiculo in medida.entram:
            print(f"    + {veiculo.nome}: {veiculo.mencoes}")
    if medida.saem:
        print("  deixam de contar:")
        for veiculo in medida.saem:
            print(f"    - {veiculo.nome}: {veiculo.mencoes}")
    mudam = medida.meses_que_mudam
    if not mudam:
        print("  nenhum mês muda — a lente já é o espelho do cadastro.")
        return
    print(f"  {len(mudam)} mês(es) mudam:")
    for mes in mudam:
        sinal = "+" if mes.depois > mes.antes else "-"
        print(
            f"    {mes.mes:%Y-%m}: {mes.antes} -> {mes.depois} "
            f"({sinal}{abs(mes.depois - mes.antes)})"
        )


def executar(lista: str, simular: bool) -> int:
    fabrica = obter_fabrica_de_sessao()
    with fabrica() as sessao:
        fontes = motor.fontes_que_recortam(sessao, lista)
        if not fontes:
            print(f"nenhuma fonte recorta pela lista {lista!r}.")
            return 1
        for fonte in fontes:
            medida = (
                motor.previa(sessao, fonte)
                if simular
                else motor.aplicar(sessao, fonte)
            )
            _relatar(medida)
        if simular:
            print("\nsimulação: nada foi escrito.")
        else:
            sessao.commit()
            print("\naplicado.")
    return 0


def main(argv: list[str] | None = None) -> int:
    opcoes = _parsear(argv)
    return executar(lista=opcoes.lista, simular=opcoes.simular)


if __name__ == "__main__":
    sys.exit(main())
