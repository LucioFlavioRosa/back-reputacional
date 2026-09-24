-- 0051 — a Visão geral desenha as fatias pelo peso, ou todas iguais
--
-- POR QUE ISTO É RÉGUA, E NÃO PREFERÊNCIA DE QUEM OLHA
-- ---------------------------------------------------
-- O gráfico radial diz duas coisas ao mesmo tempo: o comprimento da fatia é a
-- nota da lente, e a largura é o peso dela no índice. Desligar a largura por
-- peso muda o que a diretoria LÊ do mesmo número — com fatias iguais, uma
-- lente de peso 15 parece pesar tanto quanto a de 30.
--
-- Isso é decisão da coordenação sobre como a companhia se apresenta, e não
-- ajuste de quem abriu a tela: por isso mora em `score_config`, versionada com
-- autor e data, ao lado dos pesos que ela desenha.
--
-- VERDADEIRO É O PADRÃO porque é o que o índice de fato faz: a média é
-- ponderada, e um gráfico de fatias iguais esconde a ponderação que o número
-- ao lado aplicou.

alter table score_config
  add column if not exists radial_por_peso boolean not null default true;

comment on column score_config.radial_por_peso is
  'Largura da fatia de cada lente no gráfico radial da Visão geral: o peso '
  'efetivo (padrão) ou fatias iguais (0051).';
