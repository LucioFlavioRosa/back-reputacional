-- =============================================================================
-- 0001 — Extensões, domínio de abrangência e dicionários
--
-- Primeiro arquivo do schema. Cria o que todo o resto referencia.
--
-- CONVENÇÕES DO BANCO INTEIRO
--   português, snake_case, sem acento em identificador
--   chave técnica sempre `id`; a chave natural fica em `codigo` ou `nome`
--   `timestamptz` para instante, `date` para dia de calendário
--
-- OS DICIONÁRIOS SÃO TABELAS, E NÃO ENUMS
--   Enum do Postgres exigiria migration e deploy para acrescentar um formato de
--   entrevista — o que na prática significa que ninguém acrescentaria. Sendo
--   tabela, o valor entra com um `INSERT`.
--
--   ⚠ A TELA DE ADMINISTRAÇÃO NÃO EXISTE. A API só lê (`GET /api/dicionarios`),
--   e hoje mudar um valor é SQL direto. O papel `administra_dicionarios` está
--   na tabela `papel` esperando o caso de uso.
--
--   Todos seguem a mesma forma: `id`, `codigo` (chave natural, estável, usada
--   pela API), `nome` (o que a pessoa lê), `ordem` (como aparece na lista) e
--   `ativo`. Desativar preserva os registros históricos que apontam para o
--   valor; apagar quebraria a chave estrangeira.
-- =============================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists citext;     -- e-mail sem diferenciar maiúscula
create extension if not exists pg_trgm;    -- busca por semelhança em nome

-- NÃO há `unaccent` aqui, e a ausência é deliberada.
--
-- A normalização de nome acontece em Python, em `app/dominio/texto.py`, e o
-- resultado é gravado em `nome_normalizado`. Precisa ser assim: a MESMA regra
-- roda na carga e na busca, e uma diferença entre as duas faria a busca deixar
-- de encontrar exatamente os nomes que a carga uniu.
--
-- Declarar a extensão sem usá-la não seria inócuo: no Postgres gerenciado do
-- Azure cada extensão exige uma entrada em `azure.extensions`, e uma entrada a
-- mais é uma exigência de implantação em troca de nada.


-- -- abrangência geográfica ----------------------------------------------------
--
-- Domínio, e não `char(2)` solto: o mapa do painel agrupa por este valor, e um
-- "SÃO PAULO" digitado à mão viraria uma região fantasma no mapa.
--
-- `NA` e `IN` não são UF. São o que a operação de fato registra: assunto
-- nacional (uma nota da holding) e internacional (um investidor estrangeiro).

create domain abrangencia as text
  check (value in (
    'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB',
    'PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO',
    'NA','IN'
  ));

comment on domain abrangencia is
  'As 27 UFs mais NA (nacional) e IN (internacional). O mapa do painel lê daqui.';


-- =============================================================================
-- Dicionários da interação
-- =============================================================================

-- As sete frentes de relacionamento. `cor_hex` mora aqui, e não no CSS, porque
-- é a mesma cor no painel, no gráfico e no chip da lista — e trocá-la é decisão
-- de marca, não de front-end.
create table frente (
  id      smallserial primary key,
  codigo  text        not null unique,
  nome    text        not null,
  cor_hex char(7)     not null,
  ordem   smallint    not null,
  ativo   boolean     not null default true
);

-- `grupo` é o que sustenta a taxa de resolutividade do painel. Sem ele, cada
-- tela decidiria por conta própria o que conta como resolvido, e dois números
-- da mesma base discordariam.
create table status (
  id     smallserial primary key,
  codigo text        not null unique,
  nome   text        not null,
  grupo  text        not null check (grupo in ('resolvido','aberto','declinado')),
  ordem  smallint    not null,
  ativo  boolean     not null default true
);

create table esfera (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

create table clima (
  id smallserial primary key, codigo text not null unique, nome text not null,
  cor_hex char(7) not null, ordem smallint not null, ativo boolean not null default true
);

create table resultado (
  id smallserial primary key, codigo text not null unique, nome text not null,
  cor_hex char(7) not null, ordem smallint not null, ativo boolean not null default true
);

-- Relevância da contraparte, o que o painel chama de "tier".
--
-- É TABELA, e não `check (tier between 1 and 3)` na coluna, pelo mesmo motivo
-- que todos os outros vocabulários daqui: acrescentar um nível é um `insert`, e
-- não uma migration com deploy. O filtro do painel lista o que estiver aqui.
--
-- O `id` é o PRÓPRIO número do tier, e não uma sequência: a coluna
-- `interacao.tier` guarda 1, 2, 3… e é esse número que aparece na tela, nos
-- KPIs e na exportação. Deixar a chave ser o número evita uma tradução entre
-- "o id 4" e "o Tier 4" que não serviria a ninguém.
create table relevancia (
  id smallint primary key check (id > 0), nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

-- Quem procurou quem.
create table iniciativa (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

-- `escopo` limita quais formatos aparecem em cada frente: "Roadshow" não faz
-- sentido numa interação de imprensa, e uma lista única obrigaria quem cadastra
-- a procurar o valor certo no meio dos errados.
create table formato (
  id smallserial primary key, codigo text not null unique, nome text not null,
  escopo text not null check (escopo in ('imprensa','investidores','geral')),
  ordem smallint not null, ativo boolean not null default true
);

create table natureza_orgao (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

-- Casa legislativa.
create table casa (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

-- Fase da proposição legislativa.
create table tramitacao (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

create table tipo_investidor (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

-- Natureza da contraparte, independente da frente.
create table stakeholder (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

-- As empresas da holding. `nome` é a chave natural — não há código curto, e
-- inventar um só para uniformizar criaria um vocabulário que ninguém usa.
create table unidade_negocio (
  id smallserial primary key, nome text not null unique,
  ordem smallint not null, ativo boolean not null default true
);

-- Temas, com dois níveis. `estrategico` é o vocabulário fechado que a
-- coordenação acompanha e que aparece nos painéis; `livre` permite marcar um
-- assunto pontual sem poluir a lista estratégica.
create table tema (
  id        serial      primary key,
  nome      text        not null unique,
  nivel     text        not null check (nivel in ('estrategico','livre')),
  ativo     boolean     not null default true,
  criado_em timestamptz not null default now()
);


-- =============================================================================
-- Carga inicial
--
-- Os valores vêm de três fontes, nesta ordem de precedência:
--   1. a aba `_Apoio` da planilha (listas de validação que o time já usa)
--   2. os valores realmente encontrados nas abas de dado
--   3. o protótipo, para o que ainda não existe na planilha
-- =============================================================================

insert into frente (codigo, nome, cor_hex, ordem) values
  ('imprensa',     'Imprensa',     '#0027BD', 1),
  ('governo',      'Governo',      '#17E3CB', 2),
  ('parceiros',    'Parceiros',    '#A11FFF', 3),
  ('eventos',      'Eventos',      '#FE952B', 4),
  ('investidores', 'Investidores', '#E12379', 5),
  ('legislativo',  'Legislativo',  '#F8DC00', 6),
  ('interna',      'Interna',      '#8C91A4', 7);

-- `aguardando_aegea` e `aguardando_edelman` guardam quem está travando a
-- demanda — a informação que o time usa para cobrar.
insert into status (codigo, nome, grupo, ordem) values
  ('agendado',           'Agendado',           'aberto',    1),
  ('em_analise',         'Em análise',         'aberto',    2),
  ('aguardando_aegea',   'Aguardando Aegea',   'aberto',    3),
  ('aguardando_edelman', 'Aguardando Edelman', 'aberto',    4),
  ('atendido',           'Atendido',           'resolvido', 5),
  ('realizado',          'Realizado',          'resolvido', 6),
  ('elaborado',          'Elaborado',          'resolvido', 7),
  ('declinado',          'Declinado',          'declinado', 8),
  ('cancelado',          'Cancelado',          'declinado', 9);

insert into esfera (codigo, nome, ordem) values
  ('municipal',     'Municipal',     1),
  ('estadual',      'Estadual',      2),
  ('regional',      'Regional',      3),
  ('federal',       'Federal',       4),
  ('nacional',      'Nacional',      5),
  ('internacional', 'Internacional', 6);

-- Quatro níveis. O quinto, se vier, é um `insert` — sem deploy, e o filtro do
-- painel passa a mostrá-lo na carga seguinte da tela.
--
-- Os nomes são editáveis por `update`: trocar 'Tier 4' por 'Regional' muda a
-- tela sem tocar em código.
insert into relevancia (id, nome, ordem) values
  (1, 'Tier 1', 1),
  (2, 'Tier 2', 2),
  (3, 'Tier 3', 3),
  (4, 'Tier 4', 4);

insert into clima (codigo, nome, cor_hex, ordem) values
  ('propositivo', 'Propositivo', '#17E3CB', 1),
  ('neutro',      'Neutro',      '#8C91A4', 2),
  ('tenso',       'Tenso',       '#FF5C60', 3);

insert into resultado (codigo, nome, cor_hex, ordem) values
  ('avancou',       'Avançou',       '#17E3CB', 1),
  ('mantido',       'Mantido',       '#0027BD', 2),
  ('recuou',        'Recuou',        '#FF5C60', 3),
  ('sem_definicao', 'Sem definição', '#D5DAEA', 4);

insert into iniciativa (codigo, nome, ordem) values
  ('procurada', 'Procurada', 1),
  ('provocada', 'Provocada', 2);

insert into formato (codigo, nome, escopo, ordem) values
  ('posicionamento',           'Posicionamento',           'imprensa',      1),
  ('entrevista_online',        'Entrevista online',        'imprensa',      2),
  ('entrevista_presencial',    'Entrevista presencial',    'imprensa',      3),
  ('entrevista_email',         'Entrevista por e-mail',    'imprensa',      4),
  ('entrevista_telefone',      'Entrevista por telefone',  'imprensa',      5),
  ('informacoes_email',        'Informações por e-mail',   'imprensa',      6),
  ('encontro_relacionamento',  'Encontro de relacionamento','imprensa',     7),
  ('depoimento',               'Depoimento',               'imprensa',      8),
  ('envio_release',            'Envio de release',         'imprensa',      9),
  ('press_trip',               'Press trip',               'imprensa',     10),
  ('podcast',                  'Podcast',                  'imprensa',     11),
  ('videoconferencia',         'Videoconferência',         'investidores', 12),
  ('presencial',               'Presencial',               'investidores', 13),
  ('roadshow',                 'Roadshow',                 'investidores', 14),
  ('conferencia',              'Conferência',              'investidores', 15),
  ('call_resultados',          'Call de resultados',       'investidores', 16),
  ('email',                    'E-mail',                   'investidores', 17);

insert into natureza_orgao (codigo, nome, ordem) values
  ('executivo',   'Executivo',   1),
  ('legislativo', 'Legislativo', 2),
  ('judiciario',  'Judiciário',  3),
  ('entidade',    'Entidade',    4),
  ('associacao',  'Associação',  5),
  ('escritorio',  'Escritório',  6),
  ('empresa',     'Empresa',     7),
  ('investidor',  'Investidor',  8);

insert into casa (codigo, nome, ordem) values
  ('camara_deputados',   'Câmara dos Deputados',  1),
  ('senado_federal',     'Senado Federal',        2),
  ('congresso_nacional', 'Congresso Nacional',    3),
  ('assembleia_estadual','Assembleia estadual',   4),
  ('camara_municipal',   'Câmara municipal',      5);

insert into tramitacao (codigo, nome, ordem) values
  ('apresentada',       'Apresentada',       1),
  ('em_comissao',       'Em comissão',       2),
  ('pronta_para_pauta', 'Pronta para pauta', 3),
  ('aprovada',          'Aprovada',          4),
  ('arquivada',         'Arquivada',         5),
  ('sancionada',        'Sancionada',        6),
  ('vetada',            'Vetada',            7);

insert into tipo_investidor (codigo, nome, ordem) values
  ('fundo',      'Fundo de investimento',   1),
  ('sell_side',  'Banco / sell-side',       2),
  ('rating',     'Agência de rating',       3),
  ('research',   'Analista / research',     4),
  ('conferencia','Roadshow / conferência',  5);

insert into stakeholder (codigo, nome, ordem) values
  ('imprensa',        'Imprensa',              1),
  ('gestor_publico',  'Gestor público',        2),
  ('investidor',      'Financeiro/investidor', 3),
  ('entidade_setorial','Entidade setorial',    4),
  ('parlamentar',     'Parlamentar',           5),
  ('sociedade_civil', 'Sociedade civil',       6),
  ('evento_entidade', 'Evento/entidade',       7);

insert into unidade_negocio (nome, ordem) values
  ('Holding / corporativo',            1),
  ('Águas do Rio 1',                   2),
  ('Águas do Rio 4',                   3),
  ('Corsan',                           4),
  ('Águas de Manaus',                  5),
  ('Águas Guariroba',                  6),
  ('Prolagos',                         7),
  ('Águas de Teresina',                8),
  ('Ambiental Ceará 1',                9),
  ('Ambiental Ceará 2',               10),
  ('Ambiental MS Pantanal',           11),
  ('Ambiental Metrosul',              12),
  ('Nascentes do Xingu',              13),
  ('Águas de Governador Valadares',   14),
  ('Águas de Palhoça',                15),
  ('Águas de São Francisco do Sul',   16),
  ('Águas de Camboriú',               17),
  ('Águas de Penha',                  18),
  ('Águas de Bombinhas',              19),
  ('Águas do Piauí',                  20),
  ('Águas do Pará — Bloco A',         21),
  ('Águas do Pará — Bloco B',         22),
  ('Águas do Pará — Bloco C',         23),
  ('Águas do Pará — Bloco D',         24),
  ('Parsan',                          25),
  ('Padova',                          26),
  ('Regenera Rio',                    27),
  ('Reuso Itaboraí',                  28),
  ('Rio Investimentos',               29);

insert into tema (nome, nivel) values
  ('Universalização',      'estrategico'),
  ('Tarifa',               'estrategico'),
  ('IPO',                  'estrategico'),
  ('Regulação',            'estrategico'),
  ('Leilões',              'estrategico'),
  ('Copasa',               'estrategico'),
  ('Resíduos',             'estrategico'),
  ('Biometano',            'estrategico'),
  ('Reúso',                'estrategico'),
  ('Carbono',              'estrategico'),
  ('Clima',                'estrategico'),
  ('Inclusão sanitária',   'estrategico'),
  ('Modelo de negócio',    'estrategico'),
  ('Disciplina financeira','estrategico'),
  ('Cenário político',     'estrategico'),
  ('Tributário',           'estrategico'),
  ('Reputação',            'estrategico');
