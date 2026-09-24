-- 0052 — o agrupamento por tema ganha índice
--
-- A COLUNA DO MÊS PERGUNTA, PARA O PERÍODO INTEIRO: quanto cada tema pesou
-- em cada fonte. É um `group by` sobre (mês, fonte, tema, sentimento, tier,
-- cargo, engajamento), e os índices que existiam cobriam `mencao(mes)` e
-- `mencao(fonte_id, mes)` — bons para "as menções deste mês", e não para
-- agrupar o histórico inteiro.
--
-- HOJE ELE VARRE POUCO E NINGUÉM SENTE. O ponto é que a Jornada lê TODOS os
-- meses de uma vez, e a série cresce um mês por mês: o custo dobra sozinho a
-- cada ano, sem nenhuma mudança de código para culpar.
--
-- POR QUE (fonte_id, mes, tema_id) E NÃO A CHAVE INTEIRA. As três primeiras
-- colunas são as que restringem e agrupam; tier, cargo e engajamento têm
-- cardinalidade alta e entrariam só para engordar o índice. O Postgres lê o
-- resto da linha na heap, que é o que ele faz bem.

create index if not exists mencao_por_tema
  on mencao (fonte_id, mes, tema_id);

comment on index mencao_por_tema is
  'Agrupamento por tema do período inteiro — a coluna do mês da Jornada (0052).';
