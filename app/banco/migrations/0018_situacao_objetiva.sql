-- A SITUAÇÃO DA AGENDA, EM TRÊS PALAVRAS
--
-- O formulário oferecia onze status no mesmo campo — agendado, em análise,
-- aguardando Aegea, aguardando Edelman, atendido, realizado, elaborado,
-- declinado, cancelado, confirmada, solicitado. Onze opções num momento em que
-- só há três coisas a saber: o pedido foi feito, foi aceito, ou foi negado.
--
-- O que a agenda VIROU depois disso mora na seção "Desfecho da agenda", que é
-- de onde clima e resultado saem. Misturar as duas leituras no mesmo campo era
-- o que produzia a lista de onze.
--
-- NÃO SE APAGA CÓDIGO NENHUM. Os oito restantes seguem em 259 dos 293
-- registros e continuam válidos: o que muda é o que o formulário OFERECE para
-- registro novo. Apagá-los deixaria a Base, os filtros e o painel sem rótulo
-- para o que já está gravado.
--
-- Idempotente: roda quantas vezes for.

begin;

-- Os rótulos que o produto passa a usar. Os códigos ficam — `confirmada` e
-- `declinado` já eram exatamente estas duas ideias, com outro nome na tela.
update status set nome = 'Aceito' where codigo = 'confirmada';
update status set nome = 'Negado' where codigo = 'declinado';

-- A ordem em que as três aparecem no formulário. `confirmada` tinha `ordem`
-- 45, herdada de quando entrou solta no fim da lista.
update status set ordem = 0 where codigo = 'solicitado';
update status set ordem = 1 where codigo = 'confirmada';
update status set ordem = 2 where codigo = 'declinado';

-- A JUSTIFICATIVA DO ACEITE.
--
-- O "por que foi negado" já existia (`motivo_declinio`), e o aceite não tinha
-- onde ser explicado — "aceitaram, mas só para março" e "aceitaram com o
-- diretor, não com o presidente" são a informação que decide o preparo da
-- reunião, e sumiam.
alter table interacao add column if not exists nota_situacao text;

comment on column interacao.nota_situacao is
  'Em que condições a agenda foi aceita. O motivo da recusa mora em '
  '`motivo_declinio` — são fatos diferentes, e um campo só para os dois faria '
  'a troca de situação sobrescrever o texto do outro caso.';

commit;
