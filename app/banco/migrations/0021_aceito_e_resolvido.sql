-- ACEITO PASSA A SER DO GRUPO `resolvido`, E NÃO `aberto`
--
-- O QUE EU QUEBREI. A 0020 colapsou onze situações em três e deixou `Aceito`
-- no grupo `aberto`, herdado de quando `confirmada` significava "marcada, ainda
-- vai acontecer". Com isso NENHUM registro visível ficou em `resolvido` — e o
-- grupo é o que sustenta as métricas nos dois lados:
--
--   /api/metricas/kpis          imprensa.atendidas 0, taxa 0.0
--   /api/metricas/resolutividade taxa 0.0, grupo resolvido vazio
--   Painel                       "Demandas de imprensa 106 · 0% de aproveitamento"
--
-- Havia 62 demandas de imprensa aceitas e com relato. A tela dizia zero.
--
-- AS TRÊS SITUAÇÕES E OS TRÊS GRUPOS SÃO A MESMA PERGUNTA
-- ------------------------------------------------------
-- `grupo` responde "o pedido teve resposta, e qual?":
--
--   Solicitado → aberto      ainda não respondemos
--   Aceito     → resolvido   respondemos que sim
--   Negado     → declinado   respondemos que não
--
-- Um para um, o que torna a coluna previsível: quem lê `grupo` está lendo a
-- situação com outro nome, e não uma segunda classificação para manter em dia.
--
-- E NÃO É A PERGUNTA "A REUNIÃO ACONTECEU?"
-- -----------------------------------------
-- Essa mora no `relato`, e continua lá (ver `jaAconteceu` no front). São eixos
-- diferentes de propósito: uma agenda aceita para a semana que vem já é
-- resolvida — o pedido foi respondido — e ainda não aconteceu.
--
-- Idempotente: roda quantas vezes for, e só escreve o que está fora do lugar.

begin;

update status set grupo = 'resolvido'
 where codigo = 'confirmada' and grupo is distinct from 'resolvido';

-- Os oito códigos inativos ficam como estão: eles só existem para dar rótulo à
-- trilha em `interacao_auditoria`, e nenhuma métrica os alcança.

commit;
