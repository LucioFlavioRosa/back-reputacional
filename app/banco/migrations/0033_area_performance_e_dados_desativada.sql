-- =============================================================================
-- 0033 — "Performance e Dados" deixa de ser área selecionável.
--
-- `ativo = false`, e não delete: já existem interacao_area apontando para
-- ela (verificado antes desta migration), e apagar a linha quebraria a FK.
-- Mesmo padrão já usado para aposentar código de status/clima — a trilha
-- continua legível, só sai das listagens novas. `GET /api/dicionarios` já
-- filtra todo dicionário por `ativo`, então Cadastro, Termômetro por área e
-- o campo de área do porta-voz param de oferecê-la sozinhos, sem mudança de
-- código em lugar nenhum.
--
-- Idempotente: `and ativo` evita um UPDATE inútil se rodar de novo.
-- =============================================================================

begin;

update area_pessoa set ativo = false
 where codigo = 'performance_e_dados' and ativo;

commit;
