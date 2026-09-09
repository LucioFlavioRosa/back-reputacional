-- A COLUNA SITUAÇÃO PASSA A TER SÓ AS TRÊS DO FORMULÁRIO
--
-- A 0018 fez o formulário oferecer três — Solicitado, Aceito, Negado — e
-- deixou os outros oito códigos vivos nos 293 registros existentes. O efeito
-- era um vocabulário partido: a tela oferecia três e a Base mostrava onze.
--
-- O MAPEAMENTO, e por quê
-- -----------------------
--   Solicitado ← solicitado, em_analise, aguardando_aegea, aguardando_edelman
--                (38) — o pedido foi feito e ainda não teve resposta. As três
--                "aguardando" são exatamente isso, com o nome de quem espera.
--
--   Aceito     ← agendado, confirmada, atendido, realizado, elaborado
--                (231) — em todos, a agenda foi aceita. O que os separava era
--                se ela JÁ ACONTECEU, e isso deixa de morar aqui (ver abaixo).
--
--   Negado     ← declinado, cancelado (24) — a recusa, de qualquer lado.
--
-- ONDE FOI PARAR O "JÁ ACONTECEU"
-- -------------------------------
-- No `relato`. Medido nesta base: as 208 agendas concluídas — 90 atendidas,
-- 106 realizadas, 12 elaboradas — têm relato, todas; e nenhuma `solicitado`
-- ou `confirmada` tem. Não é coincidência: só se escreve o relato de uma
-- reunião que houve.
--
-- É um marcador melhor do que o status era, porque não depende de alguém
-- lembrar de mudar um campo depois da reunião — ele aparece quando a pessoa
-- escreve o que aconteceu, que é o gesto que ela já faz.
--
-- NADA SE PERDE. O gatilho de auditoria registra cada troca de `status_id`,
-- então o status anterior de cada registro fica em `interacao_auditoria`.
--
-- Os oito códigos ficam na tabela, INATIVOS: apagá-los quebraria a chave
-- estrangeira dos registros históricos em `interacao_auditoria`, e um código
-- inativo continua tendo rótulo para quem for ler a trilha.
--
-- Idempotente: roda quantas vezes for.

begin;

update interacao set status_id = (select id from status where codigo = 'solicitado')
 where status_id in (
   select id from status
    where codigo in ('em_analise', 'aguardando_aegea', 'aguardando_edelman')
 );

update interacao set status_id = (select id from status where codigo = 'confirmada')
 where status_id in (
   select id from status
    where codigo in ('agendado', 'atendido', 'realizado', 'elaborado')
 );

update interacao set status_id = (select id from status where codigo = 'declinado')
 where status_id in (select id from status where codigo = 'cancelado');

-- Fora da lista que a tela oferece — em filtro, em cadastro e em relatório.
-- `is distinct from` para não reescrever o que já está certo: sem ele estes
-- dois `update` marcavam 8 e 3 linhas a CADA rodada, e uma migration que grava
-- de novo o mesmo valor não é idempotente — é só inconsequente.
update status set ativo = false
 where codigo in (
   'agendado', 'em_analise', 'aguardando_aegea', 'aguardando_edelman',
   'atendido', 'realizado', 'elaborado', 'cancelado'
 )
   and ativo is distinct from false;

update status set ativo = true
 where codigo in ('solicitado', 'confirmada', 'declinado')
   and ativo is distinct from true;

commit;
