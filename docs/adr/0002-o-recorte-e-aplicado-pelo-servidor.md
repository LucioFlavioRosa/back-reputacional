# Todo filtro do recorte é aplicado pelo servidor

Tipo de interação e categoria de público nasceram como filtros só do
navegador, e KPIs/tabela (filtrados no cliente) passaram a contar agendas
diferentes de métricas, materiais e exportação (filtrados no servidor) para
o mesmo recorte. Decidimos que TODO campo do `Recorte` é lido por
`obter_recorte` e traduzido em SQL por `condicoes()` — um filtro que só o
cliente conhece não entra no recorte. O front pode continuar a derivar
agregados no navegador, mas nunca a filtrar por conta própria.
