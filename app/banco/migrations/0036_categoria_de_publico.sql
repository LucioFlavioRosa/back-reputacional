--: A NOVA TAXONOMIA DE PÚBLICOS — 10 categorias, cada uma com sua própria
--: subdivisão (esfera, lógica de relação, posição de capital, lógica
--: editorial, ou nenhuma) e uma área da Aegea dona daquele público.
--:
--: MORA EM `instituicao`, NÃO EM `interacao`. Categoria de público é atributo
--: do órgão/veículo/entidade em si — "Ministério da Fazenda" é Poder
--: Executivo Federal em qualquer reunião, não algo que se redigite a cada
--: agenda. `instituicao` é diretório curado e pequeno (poucas centenas de
--: linhas — ver comentário em `app/api/stakeholders.py`), então reclassificar
--: é um backfill de uma vez só, não uma reescrita de todo o histórico de
--: interações.
--:
--: DOIS DICIONÁRIOS, NÃO UM. `categoria_publico` tem as 10 linhas fixas;
--: `subcategoria_publico` referencia a categoria e existe só pra quem tem
--: subdivisão de verdade (1,2,4,5,6,7,9 — as categorias 3, 8 e 10 não geram
--: linha nenhuma ali, ficam representadas por `subcategoria_publico_id null`
--: na instituição).
--:
--: `padrao_de_quebra` é TEXTO COM CHECK, não uma tabela: é metadado
--: descritivo de COMO aquela categoria se subdivide (por esfera, por lógica
--: de relação...), não uma entidade que a coordenação cadastra por conta
--: própria — mesmo raciocínio de `formato.escopo` (`0001_fundacao.sql`).
--:
--: `area_dona_id` fica NULO só na categoria 10 (Parceiros e Cadeia de Valor):
--: ali a área responsável é "quem demandou" a interação, variável por
--: instituição/agenda — já capturado hoje por `interacao_area` — e não uma
--: área fixa por categoria como nas outras nove.
--:
--: `subcategoria_publico_id` não é globalmente único por código: "federal"
--: se repete em Poder Executivo, Poder Legislativo e Reguladores — a
--: unicidade é por categoria.
--:
--: NULÁVEIS NA INSTITUIÇÃO, SEM PREENCHIMENTO RETROATIVO: as ~99 instituições
--: já cadastradas ficam sem classificação até o backfill (planilha revisada
--: à parte, fora desta migration — ver o plano combinado).
--:
--: Idempotente.

begin;

create table if not exists categoria_publico (
  id smallserial primary key, codigo text not null unique, nome text not null,
  padrao_de_quebra text not null
    check (padrao_de_quebra in
      ('esfera', 'logica_de_relacao', 'posicao_de_capital', 'logica_editorial', 'sem_quebra')),
  area_dona_id smallint references area_pessoa(id),
  ordem smallint not null, ativo boolean not null default true
);

create table if not exists subcategoria_publico (
  id smallserial primary key,
  categoria_publico_id smallint not null references categoria_publico(id),
  codigo text not null, nome text not null,
  ordem smallint not null, ativo boolean not null default true,
  unique (categoria_publico_id, codigo)
);

insert into categoria_publico (codigo, nome, padrao_de_quebra, area_dona_id, ordem) values
  ('poder_executivo', 'Poder Executivo', 'esfera',
    (select id from area_pessoa where codigo = 'relacoes_institucionais'), 1),
  ('poder_legislativo', 'Poder Legislativo', 'esfera',
    (select id from area_pessoa where codigo = 'relacoes_institucionais'), 2),
  ('poder_judiciario', 'Poder Judiciário', 'sem_quebra',
    (select id from area_pessoa where codigo = 'relacoes_institucionais'), 3),
  ('controle_fiscalizacao', 'Controle e Fiscalização', 'logica_de_relacao',
    (select id from area_pessoa where codigo = 'relacoes_institucionais'), 4),
  ('reguladores', 'Reguladores', 'esfera',
    (select id from area_pessoa where codigo = 'relacoes_institucionais'), 5),
  ('mercado_financeiro_capitais', 'Mercado Financeiro e de Capitais', 'posicao_de_capital',
    (select id from area_pessoa where codigo = 'operacoes_financeiras'), 6),
  ('imprensa_formadores_opiniao', 'Imprensa e Formadores de Opinião', 'logica_editorial',
    (select id from area_pessoa where codigo = 'comunicacao'), 7),
  ('entidades_setoriais_representativas', 'Entidades Setoriais e Representativas', 'sem_quebra',
    (select id from area_pessoa where codigo = 'relacoes_institucionais'), 8),
  ('sociedade_civil_comunidade', 'Sociedade Civil e Comunidade', 'logica_de_relacao',
    (select id from area_pessoa where codigo = 'comunicacao'), 9),
  ('parceiros_cadeia_valor', 'Parceiros e Cadeia de Valor', 'sem_quebra', null, 10)
on conflict (codigo) do nothing;

insert into subcategoria_publico (categoria_publico_id, codigo, nome, ordem) values
  ((select id from categoria_publico where codigo = 'poder_executivo'), 'federal', 'Federal', 1),
  ((select id from categoria_publico where codigo = 'poder_executivo'), 'estadual', 'Estadual', 2),
  ((select id from categoria_publico where codigo = 'poder_executivo'), 'municipal', 'Municipal', 3),

  ((select id from categoria_publico where codigo = 'poder_legislativo'), 'federal', 'Federal', 1),
  ((select id from categoria_publico where codigo = 'poder_legislativo'), 'estadual', 'Estadual', 2),
  ((select id from categoria_publico where codigo = 'poder_legislativo'), 'municipal', 'Municipal', 3),

  ((select id from categoria_publico where codigo = 'controle_fiscalizacao'),
    'controle_auditoria', 'Controle e auditoria', 1),
  ((select id from categoria_publico where codigo = 'controle_fiscalizacao'),
    'ministerio_publico', 'Ministério Público', 2),
  ((select id from categoria_publico where codigo = 'controle_fiscalizacao'),
    'defesa_consumidor', 'Defesa do consumidor', 3),

  ((select id from categoria_publico where codigo = 'reguladores'), 'federal', 'Federal', 1),
  ((select id from categoria_publico where codigo = 'reguladores'), 'estadual', 'Estadual', 2),
  ((select id from categoria_publico where codigo = 'reguladores'),
    'municipal_ou_consorcio', 'Municipal ou consórcio', 3),

  ((select id from categoria_publico where codigo = 'mercado_financeiro_capitais'),
    'divida_credito_equity_acionistas', 'Dívida, crédito, equity e acionistas', 1),
  ((select id from categoria_publico where codigo = 'mercado_financeiro_capitais'),
    'rating', 'Rating', 2),

  ((select id from categoria_publico where codigo = 'imprensa_formadores_opiniao'),
    'economica_negocios', 'Econômica e de negócios', 1),
  ((select id from categoria_publico where codigo = 'imprensa_formadores_opiniao'),
    'geral_nacional', 'Geral nacional', 2),
  ((select id from categoria_publico where codigo = 'imprensa_formadores_opiniao'),
    'regional_concessoes', 'Regional das concessões', 3),
  ((select id from categoria_publico where codigo = 'imprensa_formadores_opiniao'),
    'setorial_formadores_opiniao', 'Setorial e formadores de opinião', 4),

  ((select id from categoria_publico where codigo = 'sociedade_civil_comunidade'),
    'organizacoes_sociedade_civil', 'Organizações da sociedade civil', 1),
  ((select id from categoria_publico where codigo = 'sociedade_civil_comunidade'),
    'comunidade_liderancas_locais', 'Comunidade e lideranças locais', 2)
on conflict (categoria_publico_id, codigo) do nothing;

alter table instituicao add column if not exists categoria_publico_id smallint references categoria_publico(id);
alter table instituicao add column if not exists subcategoria_publico_id smallint references subcategoria_publico(id);

comment on column instituicao.categoria_publico_id is
  'A nova taxonomia de públicos (10 categorias). Nula em quem foi cadastrado antes desta coluna existir — ver backfill sugerido em separado.';
comment on column instituicao.subcategoria_publico_id is
  'A subdivisão dentro da categoria (esfera, lógica de relação...). Nula sempre que a categoria for "sem_quebra", e nula também em quem ainda não foi reclassificado.';

commit;
