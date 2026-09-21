-- =============================================================================
-- 0042 — `painel_app` pode apagar instituicao e interlocutor.
--
-- `DELETE /api/interlocutores/{id}` existe desde a onda de cadastros e
-- `DELETE /api/instituicoes/{id}` nasce agora — os dois para o que entrou por
-- engano, e os dois recusam o que ja esteve numa agenda (a chave estrangeira
-- de `interacao` recusaria de qualquer jeito; a API so troca a mensagem).
--
-- O QUE FALTAVA: as `alter default privileges` da 0009 dao select/insert/
-- update, nunca delete. `interlocutor_tema` entrou na lista de vinculos com
-- delete da propria 0009; `interlocutor` e `instituicao` nao — em desenvolvimento
-- ninguem nota, porque tudo roda como superusuario, e em producao o botao
-- "Remover" de uma pessoa devolvia "permission denied" na hora de confirmar.
-- Mesma classe de falha da 0041 (`interacao_area`), conferida do mesmo jeito:
-- `has_table_privilege('painel_app', 'interlocutor', 'DELETE')` era falso.
--
-- Idempotente: `grant` repetido e inocuo.
-- =============================================================================

begin;

grant delete on interlocutor to painel_app;
grant delete on instituicao  to painel_app;

commit;
