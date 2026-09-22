-- =============================================================================
-- 0046 — A CONSULTA RECEBIDA e a ALEGAÇÃO que ela carrega.
--
-- O QUE ISTO RESOLVE
-- ------------------
-- Investidores, bancos e plataformas de rating mandam questionários por
-- e-mail perguntando sobre assuntos que a companhia não comunicou. A pergunta
-- costuma trazer o assunto JÁ COMO FATO — "como a Aegea lida com a
-- possibilidade de o Banco X não renegociar a dívida?" —, e é essa premissa,
-- não o e-mail, que interessa: quando ela chega de várias instituições que
-- não se falam, em poucos dias, há um movimento de mercado em curso, e ele
-- precede o efeito (juros, spread, rating) em semanas.
--
-- Hoje esses e-mails morrem na caixa de quem recebeu. Não há como responder
-- "isto já apareceu antes?" nem "quantos perguntaram a mesma coisa?".
--
-- DOIS NÍVEIS, E É O SEGUNDO QUE DÁ A LEITURA
-- -------------------------------------------
-- 1. A CONSULTA é uma interação como as outras — tem contraparte, data, tema,
--    área que recebeu, e o questionário vira `material`. Entra como um
--    `formato_interacao` novo ("Consulta recebida"), e não como frente: quem
--    manda continua sendo um credor, um investidor ou um veículo, e a frente
--    segue derivada do tipo da instituição.
--
-- 2. A ALEGAÇÃO é o que a pergunta dá como fato. Vive SOLTA da consulta, N:N,
--    porque é ela que se repete: a mesma alegação chega por cinco e-mails de
--    quatro instituições. Contar consultas responde "quanto nos perguntaram";
--    contar INSTITUIÇÕES DISTINTAS por alegação responde "o quanto isto está
--    circulando" — e essa é a pergunta do cliente.
--
-- POR QUE `interacao_consulta` NÃO É UMA EXTENSÃO DE FRENTE
-- ---------------------------------------------------------
-- As extensões 1-1 existentes (`interacao_imprensa`, `interacao_investidores`…)
-- são escolhidas pela FRENTE, e o domínio recusa a combinação errada
-- (`extensao_esperada`). A consulta é escolhida pelo TIPO DE INTERAÇÃO: uma
-- consulta de banco tem frente `bancos_credores` e já usa a extensão de
-- investidores. Por isso esta tabela é 1-1 com `interacao` e convive com a
-- extensão da frente, em vez de disputar o lugar dela.
--
-- Também é o que deixa a porta aberta para o mesmo fenômeno na imprensa — o
-- jornalista cuja pergunta já afirma — sem mudar nada aqui.
--
-- SOBRE NOMEAR "ALEGAÇÃO", E NÃO "BOATO"
-- --------------------------------------
-- Uma premissa pode proceder. E registrar no sistema que uma instituição
-- "espalha boatos" é uma afirmação com consequência jurídica, feita a partir
-- de um e-mail que pode ser diligência honesta. O vocabulário do produto
-- descreve o que se observou — alguém perguntou dando algo como certo — e
-- deixa a conclusão para quem lê. `apuracao` guarda o que a companhia apurou.
--
-- Idempotente: `create table if not exists`, `on conflict do nothing`,
-- `create or replace`, `drop trigger if exists` antes do `create`.
-- =============================================================================

begin;

-- -- 1. o tipo de interação ---------------------------------------------------
--
-- Oitavo valor de um dicionário ABERTO: a coordenação poderia tê-lo criado
-- pela tela. Entra por migration porque `interacao_consulta` abaixo só faz
-- sentido com ele, e os dois precisam chegar juntos a todo ambiente.

insert into formato_interacao (codigo, nome, ordem) values
  ('consulta_recebida', 'Consulta recebida', 8)
on conflict (codigo) do nothing;


-- -- 2. por onde a consulta chegou --------------------------------------------
--
-- Dicionário ABERTO: o canal muda com o mercado — hoje e-mail e formulário de
-- plataforma de rating, amanhã o que for. Nenhum cálculo depende destes
-- códigos, então acrescentar um é trabalho de coordenação, não de código.

create table if not exists canal_consulta (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

insert into canal_consulta (codigo, nome, ordem) values
  ('email', 'E-mail', 1),
  ('formulario', 'Formulário', 2),
  ('plataforma', 'Plataforma de rating ou ESG', 3),
  ('telefone', 'Telefone', 4),
  ('outro', 'Outro', 5)
on conflict (codigo) do nothing;


-- -- 3. em que pé está a apuração da alegação ----------------------------------
--
-- Dicionário ABERTO, com cor — a tela pinta a alegação por ele, como faz com
-- clima. As cores dizem RISCO, e não aprovação: "procede" é o caso em que o
-- que estava circulando é verdade, e portanto o de maior consequência.

create table if not exists apuracao (
  id smallserial primary key, codigo text not null unique, nome text not null,
  cor_hex char(7) not null, ordem smallint not null, ativo boolean not null default true
);

insert into apuracao (codigo, nome, cor_hex, ordem) values
  ('em_apuracao',      'Em apuração',      '#FE952B', 1),
  ('sem_fundamento',   'Sem fundamento',   '#17E3CB', 2),
  ('procede_em_parte', 'Procede em parte', '#F8DC00', 3),
  ('procede',          'Procede',          '#FF5C60', 4)
on conflict (codigo) do nothing;


-- -- 4. a alegação --------------------------------------------------------------

create table if not exists alegacao (
  id uuid primary key default gen_random_uuid(),

  --: O QUE A PERGUNTA DÁ COMO FATO, em uma frase, na voz de quem alega —
  --: "o Banco X não renegociaria a dívida da Aegea". Não é a pergunta
  --: transcrita nem o resumo do e-mail: é a premissa, que é o que se repete
  --: de um remetente para outro e o que permite reconhecer a mesma alegação
  --: chegando por dois caminhos.
  texto text not null,

  --: O texto normalizado (minúsculas, sem acento, espaços colapsados) —
  --: índice único sobre ele. Duas pessoas registram a mesma alegação com
  --: maiúsculas diferentes e o produto perderia exatamente a contagem que
  --: existe para fazer.
  texto_normalizado text not null,

  apuracao_id smallint not null references apuracao(id),

  --: O POSICIONAMENTO QUE RESPONDE A ESTA ALEGAÇÃO, na biblioteca. É o elo
  --: que faz a tela dizer "isto está circulando e não temos resposta
  --: publicada" — a fila de trabalho da área.
  referencia_id uuid references referencia(id),

  --: O que a companhia apurou, para quem for responder. Nulo enquanto
  --: ninguém apurou.
  nota text,

  ativo boolean not null default true,
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create unique index if not exists alegacao_texto_unico
  on alegacao (texto_normalizado);

create index if not exists alegacao_por_apuracao on alegacao (apuracao_id);

create table if not exists alegacao_tema (
  alegacao_id uuid not null references alegacao(id) on delete cascade,
  tema_id integer not null references tema(id),
  primary key (alegacao_id, tema_id)
);


-- -- 5. a consulta recebida ------------------------------------------------------

create table if not exists interacao_consulta (
  interacao_id uuid primary key references interacao(id) on delete cascade,

  canal_id smallint references canal_consulta(id),

  --: QUEM ASSINA O E-MAIL, em texto. O contato cadastrado é
  --: `interacao_interlocutor`, como em toda interação; este campo é para o
  --: caso comum de quem escreve não estar (nem precisar estar) no cadastro —
  --: um analista de uma plataforma de rating que manda o questionário anual.
  remetente text,

  --: O TEOR: as perguntas, coladas do e-mail. O corpo integral tem dado
  --: pessoal de quem enviou; guardar o que basta para reconhecer a pergunta
  --: é escolha deliberada, e o anexo continua em `material`.
  teor text,

  --: POR QUE ACHAM QUE PERGUNTARAM — a leitura de quem recebeu, em texto
  --: livre: "quer justificar revisão de spread", "está montando relatório
  --: setorial", "ouviu da concorrência".
  --:
  --: NÃO É A ALEGAÇÃO, e a diferença é o que mantém a leitura honesta: a
  --: alegação é o que a pergunta DIZ (observável, e é o que a aba conta); o
  --: motivo é a hipótese de quem leu sobre a INTENÇÃO de quem perguntou. Um
  --: se conta, o outro se lê — misturá-los faria a tela apresentar suposição
  --: com a mesma autoridade de um fato registrado.
  motivo text,

  --: Até quando responder, se o remetente deu prazo.
  prazo_resposta date,

  --: Quando respondemos. Nulo com `prazo_resposta` vencido é o que a tela
  --: cobra.
  respondida_em date
);

create table if not exists interacao_alegacao (
  interacao_id uuid not null references interacao(id) on delete cascade,
  alegacao_id uuid not null references alegacao(id),
  primary key (interacao_id, alegacao_id)
);

--: A BUSCA DA ABA É PELA ALEGAÇÃO ("quais consultas trouxeram esta?"), e a
--: chave primária só serve à direção contrária.
create index if not exists interacao_alegacao_por_alegacao
  on interacao_alegacao (alegacao_id);


-- -- 6. permissões ---------------------------------------------------------------
--
-- `alter default privileges` (0009) já dá select/insert/update em tabela
-- nova. `delete` é explícito, e é obrigatório aqui: trocar as alegações de
-- uma consulta e trocar os temas de uma alegação apagam linhas de verdade
-- (`delete-orphan` no ORM). Sem isto, passa em desenvolvimento (superusuário)
-- e devolve "permission denied" em produção, na hora de salvar — a falha que
-- 0041 e 0042 corrigiram depois do fato.

grant delete on interacao_consulta, interacao_alegacao, alegacao_tema to painel_app;

--: A alegação em si NÃO se apaga: ela é o histórico do que circulou, e
--: apagá-la reescreveria a leitura de um período que já foi lido. Sai de
--: circulação por `ativo`, como instituição e contato.


-- -- 7. auditoria do vínculo -------------------------------------------------------
--
-- Tema, área, porta-voz e participante da outra parte registram quem entrou e
-- quem saiu da agenda. Alegação é a mesma natureza de fato — e a de maior
-- consequência das cinco, porque dizer que uma consulta trouxe (ou deixou de
-- trazer) uma alegação muda a contagem que a tela usa para afirmar que algo
-- está circulando. Mudar isso em silêncio não é opção.
--
-- `registrar_vinculo()` é redefinida para nomear a coluna de cada vínculo: a
-- versão de 0005 caía em `tema_id` para qualquer tabela que não fosse
-- `interacao_pessoa_aegea`, e gravaria valor nulo para este. `interacao_area`
-- está na lista de propósito — é a correção que a 0041 faz, e esta versão
-- precisa ser um superconjunto dela para não desfazê-la quando as duas
-- migrations conviverem (0041 roda antes, por ordem alfabética).

create or replace function registrar_vinculo()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  linha  jsonb := to_jsonb(coalesce(new, old));
  rotulo text := case tg_table_name
                   when 'interacao_tema'         then 'tema'
                   when 'interacao_pessoa_aegea' then 'participacao'
                   when 'interacao_interlocutor' then 'interlocutor'
                   when 'interacao_area'         then 'area'
                   when 'interacao_alegacao'     then 'alegacao'
                   else tg_table_name
                 end;
  valor  text;
  autor  uuid;
begin
  valor := case tg_table_name
             when 'interacao_pessoa_aegea' then
               (linha ->> 'pessoa_aegea_id') || ' (' || coalesce(linha ->> 'papel', '?') || ')'
             when 'interacao_interlocutor' then linha ->> 'interlocutor_id'
             when 'interacao_area'         then linha ->> 'area_id'
             when 'interacao_alegacao'     then linha ->> 'alegacao_id'
             else                               linha ->> 'tema_id'
           end;

  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;
  end;

  insert into interacao_auditoria
    (interacao_id, usuario_id, campo, valor_anterior, valor_novo, origem)
  values (
    (linha ->> 'interacao_id')::uuid,
    autor,
    rotulo,
    case when tg_op = 'DELETE' then valor end,
    case when tg_op = 'INSERT' then valor end,
    session_user
  );

  return coalesce(new, old);
end;
$$;

-- `create or replace` preserva o dono; explícito mesmo assim, porque é a posse
-- que faz o `security definer` escrever na trilha que `painel_app` não alcança.
alter function registrar_vinculo() owner to painel_auditoria;

drop trigger if exists auditar_interacao_alegacao on interacao_alegacao;
create trigger auditar_interacao_alegacao
  after insert or delete on interacao_alegacao
  for each row execute function registrar_vinculo();

comment on table alegacao is
  'O que uma pergunta recebida dá como fato, sem que a companhia tenha comunicado.';
comment on table interacao_consulta is
  'Os dados próprios de uma interação do tipo "Consulta recebida" (0046).';

commit;
