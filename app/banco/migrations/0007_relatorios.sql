-- =============================================================================
-- 0007 — Relatórios e exportações: o registro de que dados saíram
--
-- NÃO existe gerador de documento no servidor. O relatório impresso sai da
-- impressão do navegador sobre um layout que a tela já tem, e o CSV é montado
-- no navegador a partir da listagem já baixada.
--
-- O que esta tabela guarda é o EVENTO: quem gerou, sobre qual recorte, com
-- quais seções, e quantos registros o recorte alcançava. É o insumo da consulta
-- "alguém exportou a base inteira" em `observabilidade/seguranca.kql`.
--
-- É TRILHA, NÃO BARREIRA. Um cliente modificado baixa a listagem e monta o
-- arquivo sem chamar a API — nada aqui impede isso. Serve para
-- responsabilização entre pessoas da casa e como insumo de alerta.
-- =============================================================================

create table relatorio (
  id                 uuid        primary key default gen_random_uuid(),

  -- As seções pedidas. `base` é a que leva registros; as demais levam números
  -- agregados, e a diferença é o que decide se o evento vira alerta.
  secoes             jsonb       not null,

  -- O recorte serializado, no formato do value object `Recorte`. Guardar os
  -- filtros — e não só a contagem — é o que permite reproduzir depois o que a
  -- pessoa estava vendo.
  filtros            jsonb       not null,

  criado_por         uuid        not null references usuario(id),
  criado_em          timestamptz not null default now(),
  arquivo_url        text,

  total_de_registros int         not null default 0,

  -- `documento` corta em 80 linhas; `csv` não corta. O CSV é o caminho mais
  -- curto para tirar dados daqui, e por isso o que mais merece o alerta.
  formato            text        not null default 'documento'
                       check (formato in ('documento','csv'))
);

comment on column relatorio.total_de_registros is
  'Tamanho do recorte no momento da geração. É o insumo do alerta "alguém '
  'exportou a base inteira".';

comment on column relatorio.formato is
  'documento = relatório impresso pela tela; csv = exportação da Base.';

create index idx_relatorio_recente on relatorio (criado_em desc);

-- Para cruzar gerações pelo recorte: "quem mais exportou este mesmo filtro?".
create index relatorio_filtros_idx on relatorio using gin (filtros);
