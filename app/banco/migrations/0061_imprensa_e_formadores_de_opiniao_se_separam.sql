--: "IMPRENSA E FORMADORES DE OPINIÃO" SE DIVIDE EM DUAS CATEGORIAS.
--:
--: A Aegea pediu a separação: "Imprensa" (veículo de imprensa propriamente
--: dito) e "Formadores de Opinião" (quem opina sem ser veículo) deixam de
--: ser uma coisa só.
--:
--: "FORMADORES DE OPINIÃO" NASCE `sem_quebra`: a única subcategoria que a
--: categoria combinada tinha para essa linha editorial ("Setorial e
--: formadores de opinião") deixa de fazer sentido como subcategoria de si
--: mesma — mesmo raciocínio de "Parceiros e Cadeia de Valor" em `0037`
--: (uma subcategoria sem alternativa não dá opção real a quem cadastra).
--: "Imprensa" herda as outras 4 subcategorias e o `padrao_de_quebra`
--: `logica_editorial` de antes.
--:
--: A CATEGORIA ANTIGA É APOSENTADA, NÃO APAGADA: `ativo = false` nela e nas
--: 5 subcategorias que tinha, mesmo padrão de `0058` — preserva a FK de
--: quem já estava classificado lá.
--:
--: INSTITUIÇÕES JÁ CLASSIFICADAS NA CATEGORIA ANTIGA FICAM SEM CATEGORIA:
--: confirmado com o usuário — hoje são só dados de desenvolvimento (fake),
--: sem reclassificação real a perder; quem precisar reclassifica pela tela,
--: igual ao padrão de LSO/e_risco.
--:
--: Idempotente.

begin;

insert into categoria_publico (codigo, nome, padrao_de_quebra, area_dona_id, ordem) values
  ('imprensa', 'Imprensa', 'logica_editorial',
    (select id from area_pessoa where codigo = 'comunicacao'), 7),
  ('formadores_opiniao', 'Formadores de Opinião', 'sem_quebra',
    (select id from area_pessoa where codigo = 'comunicacao'), 8)
on conflict (codigo) do nothing;

update categoria_publico set ordem = 9  where codigo = 'entidades_setoriais_representativas';
update categoria_publico set ordem = 10 where codigo = 'sociedade_civil_comunidade';
update categoria_publico set ordem = 11 where codigo = 'parceiros_cadeia_valor';

insert into subcategoria_publico (categoria_publico_id, codigo, nome, ordem) values
  ((select id from categoria_publico where codigo = 'imprensa'),
    'economica_negocios', 'Econômica e de negócios', 1),
  ((select id from categoria_publico where codigo = 'imprensa'),
    'geral_nacional', 'Geral nacional', 2),
  ((select id from categoria_publico where codigo = 'imprensa'),
    'regional_concessoes', 'Regional das concessões', 3),
  ((select id from categoria_publico where codigo = 'imprensa'),
    'municipal_local', 'Municipal / local', 4)
on conflict (categoria_publico_id, codigo) do nothing;

update categoria_publico set frente_padrao_id = (select id from frente where codigo = 'imprensa')
  where codigo in ('imprensa', 'formadores_opiniao');

update subcategoria_publico set ativo = false
  where categoria_publico_id = (select id from categoria_publico where codigo = 'imprensa_formadores_opiniao');

update categoria_publico set ativo = false where codigo = 'imprensa_formadores_opiniao';

update instituicao set categoria_publico_id = null, subcategoria_publico_id = null
  where categoria_publico_id = (select id from categoria_publico where codigo = 'imprensa_formadores_opiniao');

commit;
