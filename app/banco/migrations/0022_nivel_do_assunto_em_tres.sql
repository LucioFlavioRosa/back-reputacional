-- O NÍVEL DO ASSUNTO PASSA A TER TRÊS VALORES
--
-- Eram dois — `estrategico` e `livre` — e faltava o que a área de fato usa
-- para decidir quem fala: o assunto SENSÍVEL, o que exige alinhamento antes de
-- alguém abrir a boca. Sem ele, "reajuste tarifário" e "patrocínio de corrida"
-- moravam na mesma gaveta.
--
--   sensivel     exige alinhamento prévio sobre quem fala e o que se diz
--   estrategico  agenda da companhia — o que se planeja levar
--   gerais       o que aparece sem ter sido planejado
--
-- `livre` VIRA `gerais` no código, e não só no rótulo. Rótulo novo sobre
-- código velho cria duas escritas da mesma coisa — a tela dizendo "Gerais" e
-- o banco dizendo `livre` —, e é assim que uma consulta escrita daqui a seis
-- meses procura pela palavra errada.
--
-- Nenhum dos 17 assuntos de fundação usa `livre`: todos são `estrategico`. O
-- `update` abaixo existe para o que tenha sido cadastrado em uso.
--
-- Idempotente: roda quantas vezes for.

begin;

-- A restrição sai ANTES do update: com ela de pé, gravar 'gerais' seria
-- recusado pela própria regra que este arquivo veio trocar.
alter table tema drop constraint if exists tema_nivel_check;

update tema set nivel = 'gerais' where nivel = 'livre';

alter table tema
  add constraint tema_nivel_check
  check (nivel in ('sensivel', 'estrategico', 'gerais'));

alter table tema alter column nivel set default 'gerais';

commit;
