-- 0050 — os limites dos detectores de sinal entram na régua
--
-- POR QUE ISTO É CALIBRAÇÃO, E NÃO CONSTANTE NO CÓDIGO
-- ---------------------------------------------------
-- "O que conta como pico" não é decisão técnica. Depende do volume que cada
-- fonte costuma trazer, e quem sabe isso é quem lê o painel toda semana — não
-- quem escreveu o detector. Com os limites no código, ajustar o corte de um
-- pico exigiria deploy; com eles aqui, é a mesma tela que já ajusta pesos e
-- réguas, e a frase muda na próxima leitura.
--
-- POR QUE ENTRA EM `score_config`, E NÃO EM TABELA PRÓPRIA
-- -------------------------------------------------------
-- Porque é a mesma decisão, tomada pela mesma gente, no mesmo lugar: a régua
-- com que a companhia lê o próprio mês. Numa tabela separada, uma versão de
-- pesos e uma versão de limites poderiam divergir — e "com que critério este
-- número foi lido em junho?" passaria a ter duas respostas, cada uma com a sua
-- data.
--
-- VAZIO É O PADRÃO DO CÓDIGO, e não zero: uma linha antiga de `score_config`
-- não conhece limite nenhum, e o detector usa o padrão de fábrica. Zerar aqui
-- faria toda régua gravada antes desta migration produzir divisão por zero.

alter table score_config
  add column if not exists limites jsonb not null default '{}'::jsonb;

comment on column score_config.limites is
  'Cortes dos detectores de sinal: pico_desvios, virada_pontos, … (0050). '
  'Chave ausente = padrão do código.';
