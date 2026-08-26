-- =============================================================================
-- 0003 — Quem entra, o que pode, sobre quais registros, e até quando
--
-- A autorização é composta por três coisas independentes, e separá-las é o que
-- torna possível responder "por que fulano não vê isto?" sem ler código:
--
--   papel           O QUE pode fazer      criar, editar, exportar, administrar
--   usuario_escopo  SOBRE O QUE           quais frentes, quais unidades
--   acesso_expira_em ATÉ QUANDO           obrigatório para quem é de fora
--
-- POR QUE O PAPEL VEM DE TABELA, E NÃO DO TOKEN DO ENTRA ID
--
-- Claim de grupo no token exigiria mexer no tenant a cada mudança de permissão,
-- e a lista de grupos do Entra ID é administrada por outra equipe. Com a tabela,
-- a coordenação concede acesso pela própria tela, e o registro de quem concedeu
-- fica no mesmo banco do resto — ver 0005.
--
-- O PADRÃO É NÃO VER NADA
--
-- Usuário provisionado no primeiro login nasce com `papel_id` nulo, e sem papel
-- não se entra. Um convidado B2B que consiga autenticar no tenant não ganha
-- acesso ao painel por isso: alguém da coordenação precisa conceder.
--
-- NUNCA EXISTE COLUNA DE SENHA. A autenticação é SSO, sempre.
-- =============================================================================

-- -- o que se pode fazer -------------------------------------------------------

create table papel (
  id                     smallserial primary key,
  codigo                 text        not null unique,
  nome                   text        not null,
  pode_criar             boolean     not null default false,
  pode_editar_proprio    boolean     not null default false,
  pode_editar_tudo       boolean     not null default false,
  administra_dicionarios boolean     not null default false,
  administra_acessos     boolean     not null default false,
  ve_campos_sensiveis    boolean     not null default false,
  ve_diretorio           boolean     not null default false,
  pode_exportar          boolean     not null default false,
  ativo                  boolean     not null default true,
  criado_em              timestamptz not null default now()
);

comment on table papel is
  'Conjunto nomeado de permissões. Não contém escopo: ver usuario_escopo.';

comment on column papel.ve_campos_sensiveis is
  'relato e pendencias saem do payload da API quando falso.';

-- Uma coluna por permissão, e não uma lista: assim a pergunta "quem pode
-- exportar?" é um `select`, e acrescentar uma permissão nova não exige
-- reinterpretar dado existente.
insert into papel (
  codigo, nome,
  pode_criar, pode_editar_proprio, pode_editar_tudo,
  administra_dicionarios, administra_acessos,
  ve_campos_sensiveis, ve_diretorio, pode_exportar
) values
  ('analista',    'Analista',    true,  true,  false, false, false, true,  true,  true ),
  ('coordenacao', 'Coordenação', true,  true,  true,  true,  true,  true,  true,  true ),
  ('diretoria',   'Diretoria',   false, false, false, false, false, true,  true,  true ),
  ('externo',     'Externo',     false, false, false, false, false, false, false, false)
on conflict (codigo) do nothing;


-- -- quem entra ----------------------------------------------------------------

-- `entra_object_id` é o `oid` do token, e é ele que identifica a pessoa — não o
-- e-mail. E-mail corporativo muda (casamento, transferência de empresa do
-- grupo) e o `oid` não; identificar pelo e-mail faria a pessoa perder o
-- histórico ao trocar de endereço.
--
-- `email` é `citext` porque o Entra ID não garante a caixa: o mesmo endereço
-- volta ora em minúsculas, ora capitalizado, e com `text` a restrição de
-- unicidade deixaria passar duplicata.
create table usuario (
  id                  uuid        primary key default gen_random_uuid(),
  entra_object_id     text        not null unique,
  email               citext      not null unique,
  nome                text        not null,
  ativo               boolean     not null default true,
  provisionado_em     timestamptz not null default now(),
  ultimo_acesso_em    timestamptz,

  papel_id            smallint    references papel(id),
  acesso_irrestrito   boolean     not null default false,
  externo             boolean     not null default false,
  acesso_expira_em    date,

  -- Quem concedeu e quando. `papel_concedido_em` também é a VERSÃO usada na
  -- detecção de alteração concorrente — ver `conceder_acesso` em 0006.
  papel_concedido_por uuid        references usuario(id),
  papel_concedido_em  timestamptz,

  -- Acesso de terceiro sem prazo é acesso que ninguém lembra de revogar. A
  -- restrição no banco é o que garante o prazo mesmo em escrita por SQL direto.
  constraint externo_tem_prazo
    check (not externo or acesso_expira_em is not null)
);

create index idx_usuario_papel on usuario (papel_id);

comment on column usuario.acesso_irrestrito is
  'Verdadeiro dispensa o filtro de escopo. Falso SEM linha em usuario_escopo '
  'significa não ver nada — a alternativa (sem linha = sem restrição) falharia '
  'aberta para todo convidado recém-provisionado.';


-- -- sobre quais registros -----------------------------------------------------

create table usuario_escopo (
  usuario_id   uuid        not null references usuario(id) on delete cascade,
  dimensao     text        not null check (dimensao in ('frente','unidade_negocio')),
  valor        text        not null,
  concedido_em timestamptz not null default now(),
  primary key (usuario_id, dimensao, valor)
);

create index idx_usuario_escopo_usuario on usuario_escopo (usuario_id);

comment on table usuario_escopo is
  'Restrição de leitura por dimensão. Sem FK porque a dimensão é polimórfica: '
  'valor referencia frente.codigo ou unidade_negocio.nome conforme o caso — '
  'unidade_negocio nao tem coluna codigo, o nome e a chave natural.';


-- -- a trilha de entrada -------------------------------------------------------
--
-- Toda tentativa de login, com ou sem sucesso. É a base das consultas de
-- segurança em `observabilidade/seguranca.kql` — em especial "cinco negativas
-- da mesma conta em dez minutos".

create table acesso_log (
  id            bigserial   primary key,
  usuario_id    uuid        references usuario(id),
  -- Preenchido quando a recusa acontece antes de haver usuário: é a única
  -- identificação disponível nesses casos.
  email_tentado text,
  ocorrido_em   timestamptz not null default now(),
  ip            inet,
  resultado     text        not null check (resultado in (
                  'sucesso',
                  'negado_sem_papel',     -- autenticou, mas ninguém concedeu papel
                  'negado_vencido',       -- o prazo de acesso passou
                  'negado_no_provedor',   -- falhou antes de chegar aqui
                  'negado_inativo'        -- conta desativada
                ))
);

comment on column acesso_log.resultado is
  'sucesso | negado_sem_papel | negado_vencido | negado_no_provedor | negado_inativo';

create index acesso_log_ocorrido_em_idx on acesso_log (ocorrido_em desc);

-- A recusa é o que se procura numa investigação, e ela é minoria das linhas.
create index idx_acesso_log_resultado on acesso_log (resultado, ocorrido_em desc);

-- Este índice é a ÚNICA exceção à regra "índice segue a consulta", porque
-- nenhuma rota da API consulta `acesso_log` por usuário. Ele serve a uma
-- consulta OPERACIONAL, que fica escrita aqui para não ser hipotética:
--
--   select ocorrido_em, resultado, ip
--     from acesso_log
--    where usuario_id = $1
--      and ocorrido_em >= now() - interval '30 days'
--    order by ocorrido_em desc;
--
-- É a segunda pergunta de todo incidente — "o que esta pessoa fez?" — e vem
-- logo depois de "quem entrou?". Vale o índice porque `acesso_log` é a única
-- tabela que cresce sem teto: uma linha por TENTATIVA de login, para sempre. As
-- outras têm volume limitado pelo negócio, e nelas uma varredura sequencial
-- durante uma investigação é aceitável. Aqui não seria.
create index idx_acesso_log_usuario on acesso_log (usuario_id, ocorrido_em desc);
