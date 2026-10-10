-- =============================================================================
-- 0068 — `painel_app` ganha escrita em `importacao` e `importacao_linha`
--
-- A 0009 revogou `insert, update, delete` destas duas tabelas de propósito,
-- porque na época (migration 0008) a importação de planilha só existia como
-- schema — nenhum caso de uso a usava ainda. O comentário da 0009 já avisava:
-- "Quem for implementar a importação precisa conceder explicitamente aqui."
--
-- A importação foi implementada depois (upload, conferência, confirmação —
-- ver `app/api/importacoes.py` e `app/casos_de_uso/importar_agendas.py`), e
-- esta migration nunca veio: `POST /api/importacoes` falha com "permission
-- denied for table importacao" em qualquer ambiente que rode como `painel_app`
-- — sandbox e produção, nunca em teste local, que roda como superusuário. É
-- o mesmo ponto cego que a 0041 descreve para `interacao_area`.
--
-- SÓ `insert, update` — NUNCA `delete`. Nenhum caso de uso apaga linha de
-- `importacao` nem de `importacao_linha`; cancelar marca `situacao =
-- 'cancelada'` (`importar_agendas.cancelar`), não remove a linha. Conceder
-- `delete` sem uso seria repetir o erro que a 0009 queria evitar.
--
-- O teste que documentava a ausência proposital deste grant
-- (`tests/test_papel_restrito.py::test_nao_escreve_no_schema_sem_aplicacao`)
-- precisa sair junto com esta migration — ele afirma, no próprio docstring,
-- que vai falhar no dia em que a importação for implementada, e esse dia é
-- hoje.
--
-- Idempotente: `grant` repetido é inócuo.
-- =============================================================================

begin;

grant insert, update on importacao, importacao_linha to painel_app;

commit;
