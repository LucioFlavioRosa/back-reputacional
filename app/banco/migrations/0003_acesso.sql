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

  -- ONDE a pessoa entra, e não o que ela faz lá dentro.
  --
  -- A plataforma tem três portais — CRM dos Stakeholders, Síntese Executiva e
  -- Score Executivo —, e a capa oferece os três. Estas colunas dizem quais
  -- deles um papel abre.
  --
  -- É dimensão SEPARADA das bandeiras acima, e a separação é o que impede a
  -- lista de papéis de multiplicar: sem ela, "quem lê a Síntese" e "quem lê a
  -- Síntese e o Score" seriam papéis diferentes, e cada portal novo dobraria a
  -- tabela.
  --
  -- Fecham por padrão. Papel novo criado sem mexer nelas não abre porta
  -- nenhuma, que é o comportamento certo para quem esqueceu de decidir.
  acessa_crm             boolean     not null default false,
  acessa_sintese         boolean     not null default false,
  acessa_score           boolean     not null default false,

  ativo                  boolean     not null default true,
  criado_em              timestamptz not null default now()
);

comment on table papel is
  'Conjunto nomeado de permissões e de portais. Não contém escopo: ver '
  'usuario_escopo.';

comment on column papel.acessa_crm is
  'Abre o CRM dos Stakeholders. Ver acessa_sintese e acessa_score.';

comment on column papel.ve_campos_sensiveis is
  'relato e pendencias saem do payload da API quando falso.';

-- Uma coluna por permissão, e não uma lista: assim a pergunta "quem pode
-- exportar?" é um `select`, e acrescentar uma permissão nova não exige
-- reinterpretar dado existente.
-- OS QUATRO PAPÉIS DE PARTIDA.
--
-- São a divisão por PORTAL, que é a fronteira mais grossa da plataforma:
-- `plataforma` alcança os três, e os outros três alcançam um cada.
--
-- As bandeiras de permissão abaixo são ponto de partida, e mudá-las é um
-- `update` — não uma migration. Um papel intermediário ("lê a Síntese e o
-- Score, não exporta") é um `insert`.
--
-- `administra_acessos` fica SÓ em `plataforma`, e a exclusividade é
-- deliberada: é a permissão que concede todas as outras. Espalhá-la faria
-- cada portal poder ampliar o próprio alcance.
--
-- ATENÇÃO ao mexer: `conceder_acesso` proíbe alterar o próprio acesso
-- (migration 0006). Deixar zero pessoas com `administra_acessos` tranca a
-- administração, e sair disso exige SQL direto no banco.
insert into papel (
  codigo, nome,
  pode_criar, pode_editar_proprio, pode_editar_tudo,
  administra_dicionarios, administra_acessos,
  ve_campos_sensiveis, ve_diretorio, pode_exportar,
  acessa_crm, acessa_sintese, acessa_score
) values
  -- Alcança os três portais e administra a plataforma.
  ('plataforma', 'Plataforma',        true,  true,  true,  true,  true,  true,  true,  true,  true,  true,  true ),

  -- O CRM é o único portal com dado hoje, e é onde se registra: este papel
  -- trabalha lá dentro, mas não edita o que é dos outros nem administra nada.
  ('crm',        'CRM',               true,  true,  false, false, false, true,  true,  true,  true,  false, false),

  -- Síntese e Score são leitura executiva: consultam e exportam.
  ('sintese',    'Síntese Executiva', false, false, false, false, false, true,  false, true,  false, true,  false),
  ('score',      'Score Executivo',   false, false, false, false, false, true,  false, true,  false, false, true )
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

  -- NULO é permitido, e é o que abre a porta para senha local.
  --
  -- Era `not null`: quem entra é sempre do Entra ID. Passou a aceitar nulo
  -- porque a plataforma ganhou uma segunda forma de autenticar, e um usuário de
  -- senha não tem `oid` nenhum para guardar aqui. `unique` continua valendo, e
  -- no Postgres vários nulos convivem sob `unique` — é exatamente o que se
  -- quer: muitos usuários locais, nenhum deles colidindo.
  entra_object_id     text        unique,

  -- Hash bcrypt, produzido por `crypt(senha, gen_salt('bf', 12))` do pgcrypto.
  --
  -- Nulo quer dizer "esta pessoa não entra por senha", e é o normal: quem vem
  -- do Entra ID nunca tem senha aqui. Guardar a senha em claro, ou um hash
  -- rápido como SHA, transformaria um vazamento de banco em vazamento de
  -- credencial — bcrypt custa de propósito.
  --
  -- A COMPARAÇÃO acontece no Postgres (`senha_hash = crypt($1, senha_hash)`),
  -- e não em Python: assim a senha em claro não passa por variável da
  -- aplicação além do necessário, nem entra em log de exceção.
  senha_hash          text,

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
  -- Toda pessoa precisa poder entrar de ALGUM jeito.
  --
  -- Sem isto, um `insert` que esquecesse os dois criaria uma conta que existe,
  -- aparece na tela de acessos, pode receber papel e escopo — e não autentica
  -- por caminho nenhum. Uma conta fantasma que ninguém entende por que não
  -- funciona.
  constraint usuario_autentica_de_algum_jeito
    check (entra_object_id is not null or senha_hash is not null),

  papel_concedido_por uuid        references usuario(id),
  papel_concedido_em  timestamptz,

  -- Acesso de terceiro sem prazo é acesso que ninguém lembra de revogar. A
  -- restrição no banco é o que garante o prazo mesmo em escrita por SQL direto.
  constraint externo_tem_prazo
    check (not externo or acesso_expira_em is not null)
);

comment on column usuario.senha_hash is
  'bcrypt do pgcrypto. Nulo = não entra por senha, só por SSO.';

comment on column usuario.entra_object_id is
  'oid do token do Entra ID. Nulo = usuário só de senha local.';

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
