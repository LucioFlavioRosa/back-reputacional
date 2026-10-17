"""Os comandos de linha: o que uma pessoa RODA, e não o que o servidor serve.

    semear_*.py                   povoam um banco vazio para desenvolver e demonstrar
    importar_cadastro_externo.py  carga única do cadastro consolidado (CSV)
    carregar_pacote_das_lentes.py carga inicial de uma lente, da planilha do pacote

Cada um se roda por `python -m app.comandos.<nome>`, e cada um tem o seu próprio
`--help` no docstring do módulo.

POR QUE ESTA PASTA EXISTE. Eles moravam em `app/banco/`, e isso fazia aquela
pasta significar duas coisas: a camada que fala SQL e os scripts que a operam.
Media-se: 10 dos 33 módulos de `app/banco/` eram script, e nenhuma das outras
seis pastas de `app/` tinha um só. A medição está em
`docs/ESTRUTURA_E_EXPANSAO.md`.

E RESOLVEU UM DIAGNÓSTICO ERRADO MEU. Aquele documento listava três imports
"de baixo para cima" como dívida de camada — `banco/importar_cadastro_externo`
puxando `api/stakeholders` e `casos_de_uso/derivar_tipo`,
`banco/carregar_pacote_das_lentes` puxando `casos_de_uso`. Não era dívida: um
PONTO DE ENTRADA pode importar qualquer camada, que é o que `main.py` faz. O
problema era a pasta, não o import. Aqui dentro eles estão certos por
construção.

A REGRA, E ELA É TESTADA (`tests/test_os_comandos_sao_pontos_de_entrada.py`):

    um comando importa qualquer camada;
    NENHUMA camada importa um comando.

A segunda metade é o que impede a pasta de virar um segundo lugar onde mora
regra de negócio. `sugerir_categoria_de_publico.py` FICOU em `app/banco/` por
causa dela: tem `__main__`, mas `banco/derivados.py` usa as funções dele, então
é camada com um CLI colado — e não comando.
"""
