-- 0054 — a área do contato DENTRO da instituição dele
--
-- NÃO É `area_pessoa`. Aquele dicionário (0022-ish) é a área da PRÓPRIA
-- Aegea — Comunicação, Relações Institucionais... — dona de um tema ou de
-- uma categoria de público. Esta coluna é outra pergunta: em que área de
-- UMA INSTITUIÇÃO EXTERNA o contato trabalha (ex.: "Research" num banco,
-- "Jurídico" num órgão regulador). Ligar as duas coisas na mesma tabela
-- misturaria "quem é dono disto na Aegea" com "onde a pessoa de fora
-- senta" — por isso é coluna nova, livre, sem FK para `area_pessoa`.
--
-- TEXTO LIVRE, mesmo molde de `cargo` e `tipo` na mesma tabela: a área de
-- um contato externo não é um vocabulário fechado que a Aegea controla, e
-- um dicionário aqui exigiria cadastrar "Research" antes de alguém poder
-- escrever "Research".

alter table interlocutor
  add column if not exists area text;

comment on column interlocutor.area is
  'A área do contato DENTRO da instituição dele (ex.: "Research", '
  '"Jurídico") — texto livre, nula quando não informada. NÃO é '
  '`area_pessoa` (a área da própria Aegea). Ver 0054.';
