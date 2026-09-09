-- A INSTITUIÇÃO PASSA A TER RELEVÂNCIA
--
-- O tier existia só na AGENDA (`interacao.tier`), e é a mesma pergunta feita
-- toda vez: quem cadastra uma reunião com a Folha reclassifica a Folha, e quem
-- cadastra a próxima reclassifica de novo — às vezes diferente. A relevância é
-- um atributo de quem está do outro lado, e não do encontro.
--
-- APONTA PARA `relevancia`, o mesmo dicionário da agenda, cujo `id` é o
-- próprio número do tier. Uma segunda lista de tiers divergiria da primeira no
-- dia em que alguém acrescentasse o Tier 5 em um só lugar.
--
-- NULO NAS QUE JÁ EXISTEM, e não um tier chutado. São 98 instituições
-- cadastradas antes desta coluna existir; preenchê-las com "Tier 3" inventaria
-- uma classificação que ninguém fez e que ninguém saberia distinguir da
-- classificação de verdade. O formulário EXIGE o campo nas novas; as antigas
-- aparecem sem relevância até alguém dizer qual é.
--
-- Idempotente: roda quantas vezes for.

begin;

alter table instituicao
  add column if not exists tier smallint references relevancia(id);

comment on column instituicao.tier is
  'Relevância da instituição — Tier 1 a 4, do dicionário `relevancia`. Nulo '
  'nas cadastradas antes da coluna existir. Não confundir com `interacao.tier`, '
  'que é a relevância DAQUELA agenda.';

commit;
