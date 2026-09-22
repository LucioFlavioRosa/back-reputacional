-- =============================================================================
-- 0043 — A instituição sem relevância herda a das agendas dela.
--
-- A Relevância da agenda passou a vir da INSTITUIÇÃO (a tela não pergunta
-- mais) — e nenhuma das ~99 instituições importadas tinha tier: toda agenda
-- nova nascia sem relevância, e o KPI "Tier 1", o filtro e a rosca por tier
-- só enxergavam o acervo importado, que tinha o tier na própria agenda.
--
-- A REGRA: a MODA dos tiers das agendas da instituição; empate desempata pelo
-- tier mais alto (número menor). É um palpite, e por isso só vale onde está
-- `null` — quem já classificou à mão não é tocado, e quem discordar corrige
-- na Administração. O mesmo cálculo, em Python, está em
-- `app/banco/derivados.py` (para a base semeada, que nasce depois disto).
--
-- Idempotente: a segunda rodada não encontra `null` para preencher.
-- =============================================================================

begin;

with moda as (
  select instituicao_id, tier, count(*) as n
    from interacao
   where tier is not null
   group by instituicao_id, tier
), melhor as (
  select distinct on (instituicao_id) instituicao_id, tier
    from moda
   order by instituicao_id, n desc, tier asc
)
update instituicao i
   set tier = melhor.tier
  from melhor
 where i.id = melhor.instituicao_id
   and i.tier is null;

commit;
