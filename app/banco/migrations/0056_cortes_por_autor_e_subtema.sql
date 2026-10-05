-- 0056 — os dois índices que faltaram aos cortes novos da Sociedade digital
--
-- ACHADO DE REVISÃO, severidade baixa e com cenário dito: a 0055 criou índice
-- para `perfil_autor` e `uf`, e deixou de fora `autor` e `subtema` — que também
-- viraram corte do dossiê e opção de filtro. O índice `(fonte_id, mes)` já
-- reduz bem o universo, então hoje, com 6.932 menções no maior mês, a diferença
-- não aparece. Ela aparece quando o volume crescer ou quando várias pessoas
-- abrirem o dossiê ao mesmo tempo: o agrupamento por autor passa a varrer todas
-- as linhas do mês para devolver os seis maiores.
--
-- A MESMA FORMA DOS OUTROS DOIS, de propósito: `(fonte_id, mes, coluna)` serve
-- tanto ao corte do mês quanto ao filtro, porque os dois sempre entram com fonte
-- e mês antes da dimensão. Um índice só na coluna não serviria a nenhum dos dois.
--
-- POR QUE NÃO ESPERAR O VOLUME: criar índice numa tabela de 20 mil linhas é
-- instantâneo, e o custo de descobrir isso em produção é um dossiê lento numa
-- reunião de diretoria.

create index if not exists mencao_por_autor on mencao (fonte_id, mes, autor);
create index if not exists mencao_por_subtema on mencao (fonte_id, mes, subtema);
