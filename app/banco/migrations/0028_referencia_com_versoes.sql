-- A BIBLIOTECA SAI DO SHAREPOINT E PASSA A TER VERSÕES
--
-- Duas mudanças que andam juntas.
--
-- 1. O ARQUIVO PASSA A MORAR AQUI. A 0026 guardava só o link do SharePoint, e
--    a plataforma deixou de usá-lo: todo arquivo vem do Blob. Uma referência
--    sem arquivo no painel é um título que não leva a lugar nenhum.
--
-- 2. UMA REFERÊNCIA TEM VERSÕES, e não um arquivo. É a natureza do acervo: o
--    Q&A de tarifa de agosto substitui o de março, e o de março continua
--    existindo — foi ele que circulou naquela reunião. A tela mostra a mais
--    recente; o histórico responde "o que a gente levou em março".
--
-- O ASSUNTO PRINCIPAL define a PASTA no blob:
--
--     referencias/<assunto principal>/<tipo>/<referência>/<arquivo>
--
-- Uma referência cobre vários assuntos — o Q&A de tarifa social cobre Tarifa e
-- Inclusão sanitária — e `referencia_tema` continua guardando todos, para a
-- busca e para o preparo de agenda. Mas o BYTE mora num lugar só: copiá-lo
-- para cada assunto criaria duas verdades que envelhecem separado, e trocar a
-- versão exigiria lembrar de trocar nas duas.
--
-- OS 69 REGISTROS DE DEMONSTRAÇÃO SAEM. Eram links fictícios de SharePoint,
-- semeados para mostrar o produto; nenhum abre. Mantê-los seria carregar 69
-- links quebrados e uma coluna `url` que ninguém mais preenche. O semeador
-- refaz o acervo com arquivos de verdade no blob.

begin;

-- -----------------------------------------------------------------------------
-- 1. O ACERVO DE DEMONSTRAÇÃO SAI
-- -----------------------------------------------------------------------------
-- Os materiais de agenda que vieram dele saem junto: sem isso, 22 linhas
-- ficariam com título de referência e link de SharePoint que não abre — e o
-- `on delete set null` de `material.referencia_id` esconderia a origem delas.
--
-- Só o que veio da BIBLIOTECA. O material que alguém escreveu à mão continua,
-- inclusive o que aponta para SharePoint: aquilo é o registro do que circulou
-- numa reunião, e não é nosso para reescrever.
delete from material_tema
 where material_id in (select id from material where referencia_id is not null);
delete from material where referencia_id is not null;
delete from referencia_tema;
delete from referencia;

-- -----------------------------------------------------------------------------
-- 2. O ASSUNTO PRINCIPAL
-- -----------------------------------------------------------------------------
-- Nulo no banco e OBRIGATÓRIO na API. A coluna aceita nulo porque uma
-- referência nasce em duas escritas — a linha e a primeira versão — e um
-- `not null` aqui obrigaria a ordem inversa da que a rota usa. Quem garante o
-- preenchimento é `/api/referencias`, que recusa sem ele.
alter table referencia
  add column if not exists tema_principal_id int references tema(id);

comment on column referencia.tema_principal_id is
  'O assunto que define a PASTA no blob. Os demais ficam em referencia_tema.';

-- -----------------------------------------------------------------------------
-- 3. AS VERSÕES
-- -----------------------------------------------------------------------------
create table if not exists referencia_versao (
  id            uuid        primary key default gen_random_uuid(),
  referencia_id uuid        not null references referencia(id) on delete cascade,

  --: 1, 2, 3… na ordem em que entraram. É o que a tela mostra como "v3", e o
  --: que ordena o histórico sem depender de data — duas versões subidas no
  --: mesmo dia continuam tendo ordem.
  numero        int         not null,

  --: O arquivo no Blob. `restrict`, e não `cascade`: apagar um arquivo por
  --: engano não pode levar embora o registro de que a versão existiu.
  arquivo_id    uuid        not null references arquivo(id) on delete restrict,

  --: A data DO DOCUMENTO, informada por quem sobe. Não é `criado_em`: o
  --: arquivo pode ser de março e entrar aqui em agosto.
  atualizado_em date        not null,

  --: O que mudou nesta versão. Uma linha, opcional — mas é ela que responde
  --: "por que trocaram" quando alguém compara duas.
  nota          text,

  criado_por    uuid        not null references usuario(id),
  criado_em     timestamptz not null default now(),

  constraint referencia_versao_unica unique (referencia_id, numero)
);

comment on table referencia_versao is
  'As versões de uma referência. A tela mostra a de maior `numero`; as '
  'anteriores respondem o que circulou numa reunião passada.';

-- Para "a versão mais recente desta referência", que é a consulta de toda
-- listagem: sem ele, cada linha da biblioteca varre as versões dela.
create index if not exists referencia_versao_recente_idx
  on referencia_versao (referencia_id, numero desc);

grant delete on referencia_versao to painel_app;

-- -----------------------------------------------------------------------------
-- 4. O QUE O SHAREPOINT DEIXOU
-- -----------------------------------------------------------------------------
-- `url`, `atualizado_em`, `fonte_da_data` e `lido_em` eram da época em que o
-- arquivo morava fora. A data agora é da VERSÃO; a fonte dela é sempre quem
-- subiu; e o link deu lugar ao arquivo.
alter table referencia drop column if exists url;
alter table referencia drop column if exists atualizado_em;
alter table referencia drop column if exists fonte_da_data;
alter table referencia drop column if exists lido_em;

commit;
