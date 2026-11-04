--: O pareamento da fila de duplicados passa a ser GUARDADO, em vez de refeito a
--: cada abertura da tela.
--:
--: O DEFEITO QUE ISTO CONSERTA: 504. `atores_duplicados.listar` comparava o
--: cadastro ativo inteiro par a par com `difflib`, dentro da requisição. Medido:
--: 3.800 cadastros levam 9,6 s; 7.300 levam 43,7 s; 11.000 levam 102,7 s — e o
--: ingress do Container Apps corta a requisição por volta de 240 s. O cadastro
--: cresce em LOTE (`veiculos_da_imprensa.criar` registra 2.631 criações numa tela
--: só), então não é questão de se vai estourar, é de quando.
--:
--: POR QUE NÃO UM PRÉ-FILTRO POR `pg_trgm`, que foi a primeira ideia: medido no
--: mesmo corpus, um pré-filtro com limiar 0,35 devolve 2,36% dos pares e dá 4x
--: (102,7 s → 25,6 s em 11.000). Mas 2,36% de n² ainda é n², e a curva volta a
--: bater nos 240 s por volta de 30.000 cadastros. E não é sem perda: o par de
--: menor semelhança trigram entre os que a fila encontra mede 0,294 — abaixo do
--: próprio limiar padrão de 0,3 —, então qualquer limiar usável perde duplicado.
--: Tempo emprestado em troca de recall; não vale.
--:
--: SÓ O PAREAMENTO É GUARDADO, e o resto da fila continua ao vivo: as decisões de
--: `ator_distinto`, a contagem de menções, as origens e o filtro de quem pergunta
--: são lidos a cada abertura. É o que faz a fila andar na hora em que alguém
--: responde — materializar a fila PRONTA deixaria o par respondido na tela até o
--: próximo recálculo.
--:
--: O PAR É GUARDADO UMA VEZ, ordenado por `ordenar_o_par` como a `0078` já faz
--: com `ator_distinto`: dizer que A parece B é dizer que B parece A, e a chave
--: primária recusa a repetição. Quem lê monta as duas direções.
--:
--: Idempotente.

begin;

create table if not exists par_semelhante (
  --: ORDENADOS: `um_id < outro_id` por texto, via `ordenar_o_par`. A `0078`
  --: escolheu o mesmo caminho para `ator_distinto`, e manter as duas iguais é o
  --: que permite comparar as chaves direto.
  um_id        uuid        not null references instituicao(id) on delete cascade,
  outro_id     uuid        not null references instituicao(id) on delete cascade,
  calculado_em timestamptz not null default clock_timestamp(),
  primary key (um_id, outro_id)
);

comment on table par_semelhante is
  'O pareamento da fila de duplicados, guardado para a tela nao recalcular '
  'n^2 por requisicao. SUBSTITUIDO inteiro a cada recalculo -- ver '
  '`atores_duplicados.recalcular`. Nao e trilha: nao tem historia a preservar.';

--: `on delete cascade` NAS DUAS: fundir apaga uma linha do catálogo, e um par
--: apontando para cadastro que já não existe seria linha que a leitura tem de
--: filtrar para sempre. Deixar o banco limpar é mais barato e não esquece.

--: A LEITURA É PELOS DOIS LADOS, e a chave primária só indexa `um_id`: sem este
--: índice, montar as duas direções varre a tabela.
create index if not exists par_semelhante_outro_idx on par_semelhante (outro_id);

--: `DELETE` É O PONTO DESTA TABELA, e tabela nova NÃO o ganha: o bloco de
--: tabelas futuras da `0009` concede `select, insert, update` e mais nada,
--: porque o papel "apaga apenas linhas filhas de agregado". Esta é substituída
--: inteira a cada recálculo — sem o `grant` a suíte fica verde (local roda como
--: superusuário) e só o ambiente implantado quebra, que é o ponto cego que a
--: `0041`, a `0068` e a `0092` já cobraram.
grant select, insert, delete on par_semelhante to painel_app;

do $$
declare
    faltando text;
begin
    select string_agg(p, ', ' order by p) into faltando
      from unnest(array['SELECT', 'INSERT', 'DELETE']) as p
     where not has_table_privilege('painel_app', 'par_semelhante', p);

    if faltando is not null then
        raise exception
            'painel_app nao pode % em par_semelhante, e o recalculo depende das tres',
            faltando;
    end if;

    raise notice 'par_semelhante criada, substituivel pela aplicacao';
end $$;

commit;
