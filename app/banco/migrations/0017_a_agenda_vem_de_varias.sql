--: UMA AGENDA PODE VIR DE VÁRIAS.
--:
--: A 0011 criou `interacao.origem_interacao_id`: uma coluna, um pai só. Isso
--: descreve uma ÁRVORE, e a realidade que o painel precisa mostrar é um GRAFO.
--:
--: O caso que motivou: duas reuniões — uma com a agência reguladora e outra
--: com a bancada — levaram juntas a uma terceira, que abriu duas frentes com
--: bancos de fomento. Com um pai só, a terceira reunião aponta para UMA das
--: duas, e a outra some do encadeamento. O desenho ficaria bonito e mentiria
--: exatamente no caso que ele existe para mostrar.
--:
--: A COLUNA SAI, em vez de conviver com a tabela. Duas representações do mesmo
--: fato divergem — foi o que produziu, só nesta base, a pauta apagada num
--: PATCH, a extensão perdida ao trocar de frente, e a contagem dobrada de
--: agendas ao recusar apagar uma pessoa. A tabela passa a ser a verdade.
--:
--: E ESTE É O MOMENTO MAIS BARATO: a coluna existe há um dia e tem ZERO linhas
--: preenchidas (conferido antes). Não há dado a migrar. Daqui a três meses,
--: haveria.
--:
--: Idempotente, como as anteriores.

begin;

create table if not exists interacao_origem (
  --: A agenda que DESCENDE.
  interacao_id uuid not null references interacao(id) on delete cascade,

  --: A agenda que veio ANTES.
  --:
  --: `on delete cascade` também: se a agenda anterior for apagada, o elo some.
  --: `restrict` travaria a exclusão de uma agenda por causa de um vínculo
  --: informativo, e `set null` deixaria um elo apontando para o nada — pior que
  --: elo nenhum, porque o grafo desenharia uma seta partindo do vazio.
  origem_id    uuid not null references interacao(id) on delete cascade,

  criado_em    timestamptz not null default now(),

  primary key (interacao_id, origem_id),

  --: UMA AGENDA NÃO DESCENDE DE SI MESMA. O ciclo de comprimento maior —
  --: A → B → A — não cabe num `check` e é barrado no repositório, que consegue
  --: subir a cadeia inteira. Este pega o caso trivial, que é o mais provável
  --: num clique.
  constraint interacao_origem_sem_laco check (interacao_id <> origem_id)
);

comment on table interacao_origem is
  'De quais agendas esta agenda decorre. MUITOS para muitos: duas reunioes '
  'podem levar juntas a uma terceira, e uma reuniao pode abrir varias frentes.';

--: A CONSULTA DO GRAFO ANDA NOS DOIS SENTIDOS.
--:
--: "De onde esta agenda veio" usa a chave primária. "O que esta agenda gerou" —
--: que é a pergunta de quem vai à próxima reunião — parte de `origem_id`, e
--: sem este índice varre a tabela inteira a cada nó desenhado.
create index if not exists ix_interacao_origem_inverso
  on interacao_origem (origem_id);

--: MIGRA O QUE HOUVER, antes de derrubar a coluna.
--:
--: Hoje são zero linhas. O `insert` fica porque uma migration precisa valer em
--: qualquer banco que a receba — inclusive um que tenha rodado a 0011 e sido
--: usado por mais tempo que este.
--:
--: DENTRO DE UM BLOCO QUE CONFERE SE A COLUNA EXISTE, e isso não é zelo
--: excessivo: na primeira versão o `insert` ficava solto, e a SEGUNDA execução
--: falhava com "column origem_interacao_id does not exist" — a própria migration
--: a tinha removido. Idempotência não é `if not exists` em cada comando; é o
--: arquivo inteiro sobreviver a rodar de novo. Só rodar duas vezes mostra.
do $$
begin
  if exists (
    select 1 from information_schema.columns
     where table_name = 'interacao' and column_name = 'origem_interacao_id'
  ) then
    execute $migra$
      insert into interacao_origem (interacao_id, origem_id)
      select id, origem_interacao_id
        from interacao
       where origem_interacao_id is not null
         and origem_interacao_id <> id
      on conflict do nothing
    $migra$;
  end if;
end $$;

alter table interacao drop column if exists origem_interacao_id;

grant select, insert, update, delete on interacao_origem to painel_app;

commit;
