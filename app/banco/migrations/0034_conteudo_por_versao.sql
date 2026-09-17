-- =============================================================================
-- 0034 — Conteúdo entra na versão; arquivo deixa de ser a única forma dela.
--
-- Até aqui toda versão de referência exigia um arquivo no Blob. Agora o
-- Resumo (fixo na referência, inalterado nesta migration — já era nullable)
-- passa a ser sempre preenchido nas escritas novas, e o Conteúdo (texto
-- livre, por versão) passa a acompanhar cada versão nova — o arquivo vira
-- opcional.
--
-- NADA SE APAGA E NADA VIRA OBRIGATÓRIO NO BANCO: as versões já cadastradas
-- não têm `conteudo` (fica null para sempre ali, sem backfill) e continuam
-- com `arquivo_id` preenchido, como sempre estiveram. A obrigatoriedade de
-- `conteudo` para versões NOVAS é imposta pela API (Form() sem default), não
-- por um `not null` aqui — mesmo padrão que `resumo` já seguia.
--
-- Idempotente: `add column if not exists` e soltar uma constraint que já não
-- existe não falham se a migration rodar de novo.
-- =============================================================================

begin;

alter table referencia_versao add column if not exists conteudo text;
alter table referencia_versao alter column arquivo_id drop not null;

commit;
