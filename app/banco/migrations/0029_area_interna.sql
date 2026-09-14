-- =============================================================================
-- 0029 — Área interna: de onde quem representa a Aegea fala
--
-- O CRM de stakeholders sempre soube QUEM fala pela Aegea (`pessoa_aegea`) e,
-- por `pessoa_aegea_tema`, SOBRE O QUE. Faltava DE ONDE — Comunicação,
-- Relações Institucionais, Jurídico — a área interna que a pessoa representa.
-- É outro vocabulário fechado, então é outro dicionário: mesma forma de
-- `tema`, e não um `check` na coluna, pelo motivo de sempre — acrescentar uma
-- área é um `insert`, não uma migration.
--
-- ESPELHA `tema` / `interacao_tema` DE PROPÓSITO: a interação também registra
-- quais áreas internas estiveram envolvidas — o filtro "Área" do painel
-- funciona como o de Temas, com OR entre as escolhidas.
-- =============================================================================

create table area (
  id        serial      primary key,
  nome      text        not null unique,
  ativo     boolean     not null default true,
  criado_em timestamptz not null default now()
);

insert into area (nome) values
  ('Comunicação'),
  ('Relações Institucionais'),
  ('Jurídico'),
  ('Regulatório'),
  ('Sustentabilidade');


-- -- de onde a pessoa da Aegea fala ---------------------------------------------
--
-- Nula: nem toda pessoa cadastrada tem área classificada, e quem é equipe
-- (não porta-voz) pode nunca precisar de uma.
alter table pessoa_aegea
  add column if not exists area_id integer references area(id);

comment on column pessoa_aegea.area_id is
  'De onde esta pessoa fala — Comunicação, Relações Institucionais etc. Nula '
  'em quem foi cadastrado antes da coluna existir, ou em quem é equipe.';


-- -- de quais áreas internas a interação trata -----------------------------------
--
-- Espelha `interacao_tema`: MUITOS para muitos, mesma chave composta.
create table interacao_area (
  interacao_id uuid not null references interacao(id) on delete cascade,
  area_id      int  not null references area(id),
  primary key (interacao_id, area_id)
);

-- Para "quais interações envolveram Jurídico": sem ele, filtrar por área varre
-- a tabela de vínculos inteira.
create index interacao_area_area_idx on interacao_area (area_id);

-- As `alter default privileges` da 0009 concedem select/insert/update; o
-- delete é dado tabela a tabela, a quem precisa dele. `interacao_area` é
-- vínculo puro sob `delete-orphan` do ORM — trocar as áreas de uma interação
-- emite `DELETE` de verdade nas linhas que saíram.
grant delete on interacao_area to painel_app;
