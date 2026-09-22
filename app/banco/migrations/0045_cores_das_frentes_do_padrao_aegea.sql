-- =============================================================================
-- 0045 — As cores das frentes no dicionário acompanham o padrão Aegea do front.
--
-- O front passou a conferir suas listas fixas contra o dicionário a cada
-- carga (`divergenciasDoCatalogo`), e a primeira conferência acusou três
-- cores diferentes: `investidores`, `interna` e `bancos_credores`. Dos dois
-- lados, o que vale é o FRONT — as cores dele são o padrão visual Aegea
-- (`CORES_DE_FRENTE`, 14/09) e passaram por auditoria de contraste (26/08);
-- o dicionário guardava os valores de antes.
--
-- Por código, não por id: é o código que os dois lados compartilham.
-- Idempotente — a segunda rodada grava o mesmo valor.
-- =============================================================================

begin;

update frente set cor_hex = '#DF2378' where codigo = 'investidores';
update frente set cor_hex = '#B0B9C8' where codigo = 'interna';
update frente set cor_hex = '#A85E40' where codigo = 'bancos_credores';

commit;
