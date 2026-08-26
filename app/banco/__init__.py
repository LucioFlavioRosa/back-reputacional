"""Tudo que fala SQL: mapeamento, consultas, sessão e migrations.

    sessao.py       a sessão por requisição, e o alias que as rotas usam
    tabelas_*.py    o mapeamento ORM, um arquivo por contexto
    repositorio_*   a escrita e a leitura do agregado
    filtros_sql.py  o ÚNICO lugar que traduz `Recorte` em SQL
    migrations/     o schema, em SQL, aplicado em ordem alfabética

`filtros_sql.condicoes()` é invariante do sistema: uma consulta que monte
`where` por conta própria quebra a garantia de que o KPI conta o que a tabela
lista — e quebra em silêncio.
"""
