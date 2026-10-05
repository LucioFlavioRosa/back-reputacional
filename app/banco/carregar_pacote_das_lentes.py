"""Roda a carga inicial de uma lente, a partir da planilha do pacote.

    python -m app.banco.carregar_pacote_das_lentes sociedade "<caminho do .xlsx>"

A PLANILHA NÃO MORA NO REPOSITÓRIO. São 2 MB de dados de produção entregues uma
vez, e versioná-los faria todo clone do projeto baixar uma base que envelhece na
primeira carga mensal. O caminho vem no argumento; o pacote inteiro está na pasta
de handoff que a coordenação guarda.

POR QUE UM COMANDO, E NÃO UMA ROTA. Carga inicial é operação de quem opera o
banco, feita uma vez por lente, com o arquivo na mão. A rota de importação que o
padrão Aegea pede — com checklist de bloqueios e relatório de lote — é outra
coisa, e é a etapa 6 do pacote.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.banco.sessao import obter_fabrica_de_sessao

# `UnidadeNegocio` e `Tema` entram para o mapeamento resolver as chaves
# estrangeiras de `Mencao` — este comando roda sozinho, fora do `main`, que é
# quem normalmente importa todas as tabelas. É o mesmo cuidado de
# `semear_mencoes`, pela mesma razão.
from app.banco.tabelas_catalogo import Tema, UnidadeNegocio  # noqa: F401
from app.casos_de_uso.carga_do_pacote_das_lentes import PACOTE, carregar


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 2:
        lentes = ", ".join(sorted(PACOTE))
        print(__doc__)
        print(f"Lentes que a carga conhece: {lentes}")
        return 2

    lente, caminho = argumentos
    arquivo = Path(caminho)
    if not arquivo.is_file():
        print(f"Não achei a planilha em {arquivo}")
        return 2

    sessao = obter_fabrica_de_sessao()()
    try:
        resumo = carregar(sessao, arquivo.read_bytes(), lente)
        # O COMMIT É AQUI, e não dentro do caso de uso: quem decide gravar é
        # quem chamou. O caso de uso faz `flush` e deixa a transação aberta —
        # é o que permite o teste rodar a carga e desfazê-la.
        sessao.commit()
    finally:
        sessao.close()

    print(f"Lente {resumo.lente}: {resumo.gravadas} menções gravadas.")
    for fonte, quantas in sorted(resumo.por_fonte.items()):
        print(f"  {fonte}: {quantas}")
    print(f"  meses: {', '.join(mes.isoformat() for mes in resumo.meses)}")
    for motivo, quantas in sorted(resumo.descartes.items()):
        print(f"  descartadas por {motivo}: {quantas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
