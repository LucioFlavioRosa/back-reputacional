-- =============================================================================
-- 0032 — Quais áreas internas participam de uma interação.
--
-- MESMO PADRÃO DE `interacao_tema`: vínculo N:N puro, sem atributo próprio.
-- `area_pessoa` já existe (0029_area_do_representante.sql) para dizer DE ONDE
-- a PESSOA fala; esta tabela reaproveita o mesmo dicionário para dizer quais
-- áreas participaram de UMA INTERAÇÃO — é o mesmo vocabulário, aplicado a um
-- registro diferente. Nenhum dicionário novo.
--
-- Idempotente: `create table if not exists`.
-- =============================================================================

begin;

create table if not exists interacao_area (
  interacao_id uuid     not null references interacao(id) on delete cascade,
  area_id      smallint not null references area_pessoa(id),
  primary key (interacao_id, area_id)
);

create index if not exists interacao_area_area_idx on interacao_area (area_id);

commit;
