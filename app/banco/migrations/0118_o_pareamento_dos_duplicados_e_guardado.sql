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


--: O CÁLCULO É FATO PRÓPRIO, e não se deduz das linhas de `par_semelhante`.
--:
--: É O MESMO FURO QUE A `0115` EXISTE PARA FECHAR, e eu quase o repeti aqui:
--: deduzir "quando foi calculado" de `max(par_semelhante.calculado_em)` funciona
--: só enquanto houver par. Num cadastro LIMPO o recálculo roda, acha zero e não
--: insere nada — e aí o `max` é nulo, indistinguível de "nunca calculou". A tela
--: diria "nunca calculado" tendo calculado, que é a mentira simétrica à que a
--: trilha da carga conserta.
--:
--: APPEND-ONLY, e vira histórico de graça: "quando foi recalculado, e quantos
--: pares deu" é a pergunta seguinte de quem desconfia da fila. Uma linha por
--: subida-que-cria mais as execuções manuais — punhado por mês.
create table if not exists pareamento_da_fila (
  id           bigserial   primary key,
  calculado_em timestamptz not null default clock_timestamp(),
  --: ZERO É RESULTADO VÁLIDO, e é a razão desta tabela existir.
  pares        integer     not null,
  --: A IMPRESSÃO DO CADASTRO DE QUE ESTE PAREAMENTO SAIU, e é o que torna a
  --: defasagem VISÍVEL sem pendurar um gancho em cada escritor.
  --:
  --: O PROBLEMA QUE ELA RESOLVE: o pareamento depende dos nomes em
  --: `instituicao`, e o cadastro muda por muitos caminhos — a tela de cadastro,
  --: a confirmação de agendas, o comando de cadastro externo, e os que ainda não
  --: existem. Pendurar recálculo em cada um é a lista que o próximo esquece de
  --: atualizar; comparar a impressão pega todos, inclusive os futuros.
  --:
  --: CONTA E NOMES, não só a contagem: renomear não muda `count(*)` nem
  --: `max(criado_em)` — e renomear é exatamente o que faz dois cadastros
  --: passarem a se parecer.
  impressao    text        not null
);

comment on table pareamento_da_fila is
  'Quando o pareamento da fila de duplicados foi refeito, e quantos pares deu. '
  'ZERO par e resultado valido: e por isso que o fato nao se deduz de '
  '`par_semelhante`, que fica vazia nesse caso.';

create index if not exists pareamento_da_fila_calculado_idx
  on pareamento_da_fila (calculado_em desc);

--: `delete` NÃO é concedido aqui, ao contrário de `par_semelhante`: esta é
--: histórico e não é substituída. `update` sai pelo mesmo motivo — o `alter
--: default privileges` da `0009` o concederia em silêncio.
revoke update, delete on pareamento_da_fila from painel_app;
grant  select, insert  on pareamento_da_fila to painel_app;
grant usage, select on sequence pareamento_da_fila_id_seq to painel_app;

--: `DELETE` É O PONTO DESTA TABELA, e tabela nova NÃO o ganha: o bloco de
--: tabelas futuras da `0009` concede `select, insert, update` e mais nada,
--: porque o papel "apaga apenas linhas filhas de agregado". Esta é substituída
--: inteira a cada recálculo — sem o `grant` a suíte fica verde (local roda como
--: superusuário) e só o ambiente implantado quebra, que é o ponto cego que a
--: `0041`, a `0068` e a `0092` já cobraram.
--: E `UPDATE` SAI, porque o `alter default privileges` da `0009` já o concedeu e
--: um `grant` não o remove: a tabela é substituída por `delete` + `insert`, e
--: nada nela se altera no lugar. Sem este `revoke` a aplicação ganharia um
--: privilégio que nenhum caminho usa — e permissão sem uso é permissão que
--: ninguém revisa.
revoke update on par_semelhante from painel_app;
grant select, insert, delete on par_semelhante to painel_app;

do $$
declare
    faltando text;
    indevidos text;
begin
    select string_agg(p, ', ' order by p) into faltando
      from unnest(array['SELECT', 'INSERT', 'DELETE']) as p
     where not has_table_privilege('painel_app', 'par_semelhante', p);

    if faltando is not null then
        raise exception
            'painel_app nao pode % em par_semelhante, e o recalculo depende das tres',
            faltando;
    end if;

    --: E `UPDATE` NAO PODE SOBRAR. O `grant` acima nao remove o que o `alter
    --: default privileges` da 0009 concedeu, e conferir so as tres de cima
    --: deixaria passar exatamente esse caso.
    if has_table_privilege('painel_app', 'par_semelhante', 'UPDATE') then
        raise exception
            'painel_app ainda pode UPDATE em par_semelhante: o revoke nao pegou';
    end if;

    --: E O HISTORICO E O CONTRARIO: le e acrescenta, nunca altera nem apaga.
    select string_agg(p, ', ' order by p) into indevidos
      from unnest(array['UPDATE', 'DELETE']) as p
     where has_table_privilege('painel_app', 'pareamento_da_fila', p);

    if indevidos is not null then
        raise exception
            'painel_app pode % em pareamento_da_fila: o historico nao e append-only',
            indevidos;
    end if;

    raise notice 'par_semelhante substituivel, pareamento_da_fila append-only';
end $$;

commit;
