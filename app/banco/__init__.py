"""Tudo que fala SQL: mapeamento, consultas, sessão e migrations.

    sessao.py       a sessão por requisição, e o alias que as rotas usam
    tabelas_*.py    o mapeamento ORM, um arquivo por contexto
    repositorio_*   a escrita e a leitura do agregado
    filtros_sql.py  o ÚNICO lugar que traduz `Recorte` em SQL
    migrations/     o schema, em SQL, aplicado em ordem alfabética

`filtros_sql.condicoes()` é invariante do sistema: uma consulta que monte
`where` por conta própria quebra a garantia de que o KPI conta o que a tabela
lista — e quebra em silêncio.

OS SEMEADORES NÃO MORAM MAIS AQUI. `semear_*`, `importar_cadastro_externo` e
`carregar_pacote_das_lentes` foram para `app/comandos/`: eram 10 dos 33
arquivos desta pasta, e faziam "banco" significar duas coisas — a camada que
fala SQL e os scripts que a operam. O que ficou é só camada, com uma exceção
nomeada: `sugerir_categoria_de_publico.py` tem `__main__`, mas `derivados.py`
usa as funções dele, então é camada com um CLI colado.
"""
