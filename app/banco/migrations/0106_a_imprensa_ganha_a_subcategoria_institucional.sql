--: "INSTITUCIONAL" ENTRA COMO SUBCATEGORIA DA IMPRENSA (por pedido,
--: 20/10/2026): "dentro da Categoria de público temos Imprensa e na
--: subcategoria temos que adicionar uma nova opção Institucional".
--:
--: ONDE ELA ENTRA. A categoria `imprensa` nasceu na `0061`, quando "Imprensa e
--: Formadores de Opinião" se separou em duas, e herdou quatro subcategorias:
--: Econômica e de negócios (1), Geral nacional (2), Regional das concessões
--: (3) e Municipal / local (4). "Institucional" vira a QUINTA, no fim da lista:
--: as quatro de hoje vieram da planilha de referência e a ordem delas é a
--: daquela planilha — acrescentar no fim é o que não mexe em nenhuma.
--:
--: A LENTE MERCADO NÃO MUDA, e esta é a conferência que importa. O recorte do
--: Mercado é o PAR (categoria "Imprensa", subcategoria "Econômica e de
--: negócios") — fixado pelo nome em `api/score.py` e em `veiculos_da_imprensa`,
--: e materializado pela `0066`. Uma subcategoria nova ao lado daquela não entra
--: no par, então nenhum veículo muda de lente por causa desta migration. Quem
--: for reclassificado para "Institucional" DEIXA o recorte do Mercado, e é esse
--: o efeito pretendido de reclassificar — não um efeito desta linha.
--:
--: HOMÔNIMO COM A LENTE "INSTITUCIONAL", de propósito e sem relação: a lente 5
--: (`lente.codigo = 'institucional'`, "Governo e entidades") é outra coisa, em
--: outra tabela. O nome aqui é o que a coordenação usa para a linha editorial
--: do veículo; nada no código liga um ao outro.
--:
--: O DICIONÁRIO SÓ MUDA POR MIGRATION, por desenho — é o que `api/dicionarios`
--: declara para esta tabela ("Subdivisão da taxonomia de públicos; mudar é
--: migration"). Por isso uma linha de SQL, e não um cadastro na tela.
--:
--: Idempotente. Se a categoria `imprensa` não existir, o `not null` da chave
--: estrangeira faz esta migration falhar alto, em vez de inserir órfã.

begin;

insert into subcategoria_publico (categoria_publico_id, codigo, nome, ordem) values
  ((select id from categoria_publico where codigo = 'imprensa'),
    'institucional', 'Institucional', 5)
on conflict (categoria_publico_id, codigo) do nothing;

commit;
