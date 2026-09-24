-- =============================================================================
-- 0048 — SCORE EXECUTIVO: o Índice de Saúde Reputacional (ISR).
--
-- Especificação: `docs/handoff/SCORE.md` e o protótipo executável
-- `docs/handoff/Score Executivo Aegea.dc.html` (a classe `Component` é a
-- fonte das fórmulas).
--
-- O QUE O ÍNDICE É
-- ----------------
-- Uma nota de 0 a 100 por mês, média ponderada de CINCO LENTES — imprensa,
-- mercado, sociedade, clientes e institucional. Cada lente lê o sentimento do
-- que se falou da companhia naquele mês, por uma ou mais fontes.
--
--     NS    = (positivo − negativo) / (positivo + neutro + negativo)
--     score = round((NS + 1) / 2 × 100)
--     ISR   = round(Σ score_lente × peso_lente / Σ peso_lente)
--
-- POR QUE O AGREGADO GUARDA COMPONENTES, E NÃO O SCORE
-- ----------------------------------------------------
-- A ponderação é CONFIGURÁVEL na tela de Calibração: o tier do veículo pode
-- valer 10/5/1 ou 1/1/1, e uma menção nas redes pode valer 1, o log do
-- engajamento, o engajamento bruto ou o cargo de quem postou. Guardar o score
-- pronto obrigaria a reprocessar tudo a cada ajuste de régua — e a régua é
-- justamente o que a coordenação mexe para entender o índice.
--
-- Por isso `score_mes_fonte` guarda as SOMAS QUE TODA PONDERAÇÃO PRECISA, no
-- grão (fonte, mês, sentimento, tier): quantas menções, a soma dos logs, a do
-- engajamento e a do peso por cargo. Qualquer uma das réguas do §3 sai dali
-- por multiplicação, na hora da leitura.
--
-- DUAS PROCEDÊNCIAS, E A DIFERENÇA IMPORTA
-- -----------------------------------------
-- Quatro lentes vêm de PLANILHA de fornecedor (Clipei, Bites, Approach) e
-- passam por `mencao` na ingestão. A quinta — institucional — já está neste
-- banco: é o clima das interações do CRM. Ela é marcada `interna` e é LIDA
-- das interações, sem cópia. Duplicar o clima em `mencao` criaria duas
-- verdades que envelhecem separado, e a primeira correção de um registro no
-- CRM deixaria o índice mentindo até alguém reprocessar.
--
-- ESTIMATIVA É DADO, E DECLARA QUE É
-- ----------------------------------
-- Há meses sem export (a Clipei só entregou junho). O §8 manda usar a
-- estimativa do resumo semestral e MARCAR como estimada: `score_estimativa`
-- guarda um NS direto, com a origem escrita, e a tela mostra o selo. Sem uma
-- tabela própria, a estimativa entraria como contagem inventada e ninguém
-- saberia mais o que foi medido e o que foi suposto.
--
-- Idempotente: `create table if not exists`, `on conflict do nothing`.
-- =============================================================================

begin;

-- -- 1. as cinco lentes -------------------------------------------------------
--
-- Dicionário FECHADO: as lentes são a estrutura do índice, e não vocabulário
-- que a coordenação administra. Uma sexta lente muda a fórmula, e isso é
-- mudança de código — o que a tela de Calibração ajusta é o PESO de cada uma,
-- que mora em `score_config`.

create table if not exists lente (
  id smallserial primary key, codigo text not null unique, nome text not null,
  --: De quem é a voz que a lente escuta. Vai para a tela: "Imprensa ·
  --: formadores de opinião".
  stakeholder text not null,
  --: O peso de fábrica, em pontos. A calibração vigente pode sobrepor.
  peso_padrao smallint not null,
  ordem smallint not null, ativo boolean not null default true
);

insert into lente (codigo, nome, stakeholder, peso_padrao, ordem) values
  ('imprensa',      'Imprensa',           'Formadores de opinião',   30, 1),
  ('mercado',       'Mercado',            'Investidores e rating',   20, 2),
  ('sociedade',     'Sociedade digital',  'Redes em mar aberto',     20, 3),
  ('clientes',      'Clientes',           'Canais próprios',         15, 4),
  ('institucional', 'Institucional',      'Governo e entidades',     15, 5)
on conflict (codigo) do nothing;


-- -- 2. o registro de fontes, extensível --------------------------------------
--
-- §4: "Novo fornecedor = nova linha + mapeamento de colunas, sem mudar
-- código." `mapeamento_colunas` diz qual coluna da planilha alimenta qual
-- campo de `mencao` — é o que permite um fornecedor novo entrar sem deploy.

create table if not exists score_fonte (
  id smallserial primary key,
  codigo text not null unique,
  nome text not null,
  fornecedor text not null,
  lente_id smallint not null references lente(id),
  --: `xlsx`, `csv`… ou nulo quando a fonte é interna.
  tipo_arquivo text,
  --: {"data": "Data", "sentimento": "Sentimento", "tier": "Aegea Tier", …}
  mapeamento_colunas jsonb not null default '{}'::jsonb,
  --: FONTE INTERNA não se ingere: o dado já está neste banco. Hoje só o CRM.
  interna boolean not null default false,
  --: SE A FONTE AINDA RECEBE IMPORTAÇÃO. Um fornecedor descontinuado entra
  --: aqui como `false`: não se importa mais nada para ele, e o histórico dele
  --: CONTINUA no índice. Tirar o passado junto reescreveria meses fechados —
  --: o ISR que a diretoria citou em julho mudaria porque o contrato acabou em
  --: outubro.
  --:
  --: NÃO É O TOGGLE DA CALIBRAÇÃO. Quem tira uma fonte do cálculo é
  --: `score_config.fontes_desligadas`, que age na LEITURA e vale para todos os
  --: meses de uma vez — ver `dominio/score.py::medir_lente`.
  ativo boolean not null default true,
  ordem smallint not null default 0,
  observacao text
);

-- O MAPEAMENTO É O CADASTRO DA FONTE, e foi conferido contra os quatro
-- exports de junho/2026: com estas colunas, a agregação reproduz número por
-- número os totais do protótipo. `aba` diz de qual planilha do arquivo ler —
-- o export da Approach traz Social Listening e Community Management no mesmo
-- arquivo, em abas diferentes, e são duas fontes de lentes diferentes.
-- `filtros` recorta antes de contar, e `arquivo` diz quais fontes leem o MESMO
-- export: subir o arquivo da Clipei alimenta Imprensa e Mercado na mesma
-- transação, e o da Approach alimenta Sociedade e Clientes. Sem isso, importar
-- por uma fonte deixaria a irmã com o mês anterior, e duas lentes leriam
-- versões diferentes do mesmo arquivo. `prefixo_a_remover` tira o cabeçalho de
-- taxonomia que a Approach carimba nos rótulos ("2 - Aegea - Falta de Água"):
-- sem isso, "Corsan" viraria quatro unidades e o gráfico de exposição não
-- fecharia. Ver `dominio/ingestao_score.py`.

insert into score_fonte (codigo, nome, fornecedor, lente_id, tipo_arquivo, mapeamento_colunas, interna, ordem, observacao) values
  ('clipei', 'Clipei', 'Clipei', (select id from lente where codigo='imprensa'),
   'xlsx',
   '{"aba": "Clipping", "arquivo": "clipei",
     "colunas": {"data": "Data", "sentimento": "Classificação", "tier": "Aegea Tier",
                 "atributo": "Atributo", "veiculo": "Veículo",
                 "publico_alvo": "Público-alvo", "tema": "Subcategoria"}}'::jsonb,
   false, 1, 'Clipping de imprensa, ponderado pelo Aegea Tier'),

  -- A MESMA PLANILHA DA CLIPEI, recortada. O §2 define a lente Mercado como
  -- "veículos com público-alvo Investidores" — é um recorte do clipping, e
  -- não um fornecedor à parte. Separar em duas fontes é o que permite ligar e
  -- desligar Imprensa e Mercado de forma independente na Calibração, lendo o
  -- mesmo arquivo. (A Edelman entra como ESTIMATIVA, em `score_estimativa`:
  -- o resumo semestral dela é um NS suposto, e não menção medida.)
  ('clipei_investidores', 'Clipei · público investidores', 'Clipei',
   (select id from lente where codigo='mercado'),
   'xlsx',
   '{"aba": "Clipping", "arquivo": "clipei",
     "filtros": {"Público-alvo": ["Investidores"]},
     "colunas": {"data": "Data", "sentimento": "Classificação", "tier": "Aegea Tier",
                 "atributo": "Atributo", "veiculo": "Veículo",
                 "publico_alvo": "Público-alvo", "tema": "Subcategoria"}}'::jsonb,
   false, 2, 'Recorte do clipping: matérias dirigidas a investidores'),

  ('approach_sl', 'Approach · Social Listening', 'Approach', (select id from lente where codigo='sociedade'),
   'xlsx',
   '{"aba": "SL", "arquivo": "approach",
     "prefixo_a_remover": "^(\\d+\\s*-\\s*)?(Aegea\\s*-\\s*)?",
     "colunas": {"data": "Data", "sentimento": "Sentimento",
                 "engajamento": "Engajamento", "tema": "Tags (tema)",
                 "unidade": "Concessionárias"}}'::jsonb,
   false, 3, 'Redes em mar aberto'),

  ('bites', 'Bites', 'Bites', (select id from lente where codigo='sociedade'),
   'xlsx',
   '{"aba": "Posts", "arquivo": "bites",
     "apelidos": {"Aegea": "Holding"},
     "colunas": {"data": "Data", "sentimento": "Sentimento", "engajamento": "Engajamento",
                 "cargo": "Cargo", "atributo": "Atributo", "tema": "Categoria",
                 "unidade": "Unidades/Empresas"}}'::jsonb,
   false, 4, 'Redes em mar aberto; única fonte que traz o cargo do autor'),

  -- `Interações`, e não `Engajamento`: é o mesmo fato com o nome que a aba de
  -- Community Management usa. Trocar o nome no código serviria a esta aba e
  -- quebraria a outra — por isso o nome mora no cadastro.
  ('approach_cm', 'Approach · Community Management', 'Approach', (select id from lente where codigo='clientes'),
   'xlsx',
   '{"aba": "CM", "arquivo": "approach",
     "prefixo_a_remover": "^(\\d+\\s*-\\s*)?(Aegea\\s*-\\s*)?",
     "colunas": {"data": "Data", "sentimento": "Sentimento",
                 "engajamento": "Interações", "tema": "TAG (assunto 1)",
                 "unidade": "Concessionárias"}}'::jsonb,
   false, 5, 'Canais próprios'),

  ('crm', 'CRM dos Stakeholders', 'Aegea', (select id from lente where codigo='institucional'),
   null, '{}'::jsonb, true, 6, 'O clima das interações deste painel — lido, não importado')
on conflict (codigo) do nothing;


-- -- 3. a menção normalizada --------------------------------------------------
--
-- Uma linha por matéria, post ou mensagem que a planilha do fornecedor trouxe,
-- já traduzida para o vocabulário do índice. É o grão mais fino, e o que
-- permite refazer qualquer agregado quando a régua muda.

create table if not exists mencao (
  id uuid primary key default gen_random_uuid(),
  fonte_id smallint not null references score_fonte(id),
  --: O PRIMEIRO DIA DO MÊS, sempre: o índice é mensal, e guardar o mês
  --: como data evita `to_char` em toda consulta.
  mes date not null,
  data date,
  sentimento text not null check (sentimento in ('pos', 'neu', 'neg')),
  --: A relevância do veículo, na escala da Clipei. Nulo nas fontes que não a
  --: têm — redes não têm tier.
  tier text check (tier in ('muito_relevante', 'relevante', 'menos_relevante')),
  --: Reações + compartilhamentos + comentários. Nulo em imprensa.
  engajamento integer,
  --: O cargo de quem postou (só Bites): alimenta a régua `cargo`.
  cargo text,
  unidade_negocio_id smallint references unidade_negocio(id),
  tema_id integer references tema(id),
  --: O tema COMO O FORNECEDOR ESCREVEU. A Clipei manda "Obras", a Approach
  --: manda "2 - Aegea - Obra": é o mesmo assunto com dois nomes, e nenhum dos
  --: dois é o vocabulário de `tema`, que é o do CRM. Guardar o texto bruto faz
  --: a tela de Drivers acender no primeiro import; `tema_id` fica para quando
  --: alguém sentar e casar as duas listas, que é decisão editorial e não
  --: conversão automática.
  tema_texto text,
  --: A concessionária COMO O FORNECEDOR A NOMEIA. Mesma história de
  --: `tema_texto`: a Bites escreve "Corsan", a Approach escreve
  --: "1 - Aegea - Corsan", e `unidade_negocio` tem o nome do CRM. É este
  --: rótulo que a aba de Drivers usa para medir exposição por unidade.
  unidade_texto text,
  --: O atributo reputacional da Clipei — alimenta a barra divergente de
  --: "Drivers e riscos".
  atributo text,
  veiculo text,
  publico_alvo text,
  criado_em timestamptz not null default now()
);

create index if not exists mencao_por_fonte_e_mes on mencao (fonte_id, mes);
create index if not exists mencao_por_mes on mencao (mes);
--: A tela de Drivers pergunta "quais temas negativos se repetem", e essa
--: consulta varre mês e tema.
create index if not exists mencao_por_tema on mencao (tema_id) where tema_id is not null;

-- OS TRÊS AGRUPAMENTOS DA ABA DE DRIVERS. Cada um varre um mês (ou seis, na
-- perpetuação) e agrupa por um rótulo que a maioria das linhas NÃO tem: só
-- Clipei e Bites classificam atributo, e só as redes trazem a concessionária.
-- Índice parcial serve exatamente a esse formato — ele indexa a minoria que
-- interessa, e não as centenas de milhares de linhas com o campo nulo.
--
-- Hoje, com 19 mil menções, uma varredura sequencial resolveria. O histórico é
-- que cresce: são ~10 mil menções por mês, e o índice é mensal para sempre.
create index if not exists mencao_por_atributo on mencao (mes, atributo)
  where atributo is not null;
create index if not exists mencao_por_unidade on mencao (mes, unidade_texto)
  where unidade_texto is not null;
--: A perpetuação olha SÓ o negativo, numa janela de seis meses.
create index if not exists mencao_negativa_por_tema on mencao (mes, tema_texto)
  where tema_texto is not null and sentimento = 'neg';


-- -- 4. o agregado mensal, com as somas de toda régua --------------------------
--
-- Grão: fonte × mês × sentimento × tier. Guarda as quatro somas que as réguas
-- do §3 consomem — ver o cabeçalho deste arquivo. Recalculado na ingestão, e
-- NÃO quando a calibração muda: a calibração é aplicada na leitura, sobre
-- estas somas.

create table if not exists score_mes_fonte (
  fonte_id smallint not null references score_fonte(id),
  mes date not null,
  sentimento text not null check (sentimento in ('pos', 'neu', 'neg')),
  --: Vazio (não nulo) quando a fonte não tem tier — é chave primária.
  tier text not null default '' check (tier in ('', 'muito_relevante', 'relevante', 'menos_relevante')),

  --: Quantas menções. É a régua `n` (contagem), e o denominador de tudo.
  mencoes integer not null default 0,
  --: Σ (1 + log10(1 + engajamento)) — a régua `log`, recomendada: um post com
  --: 3.000 interações vale ~4,5, e um com 1 vale 1,3.
  soma_log numeric(14, 4) not null default 0,
  --: Σ engajamento — a régua `bruto`, em que um viral domina o mês.
  soma_engajamento bigint not null default 0,
  --: Σ peso do cargo — a régua `cargo`, só onde a fonte traz o dado.
  soma_cargo numeric(14, 4) not null default 0,

  atualizado_em timestamptz not null default now(),
  primary key (fonte_id, mes, sentimento, tier)
);


-- -- 5. a estimativa, que declara ser estimativa -------------------------------

create table if not exists score_estimativa (
  lente_id smallint not null references lente(id),
  mes date not null,
  --: O NS direto, de −1 a 1. Não são contagens: é a leitura que o resumo
  --: semestral permitiu inferir.
  ns numeric(4, 3) not null check (ns between -1 and 1),
  --: De onde veio o número. Vai para a tela junto com o selo "estimado" — uma
  --: estimativa sem procedência é um palpite.
  origem text not null,
  nota text,
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now(),
  primary key (lente_id, mes)
);


-- -- 6. a calibração, versionada ----------------------------------------------
--
-- §3: "configuração da organização, versionada com autor e data, editável só
-- por coordenação". Nova linha a cada mudança; a mais recente é a vigente.
-- Não se apaga: saber com que régua um número foi lido no mês passado é o que
-- permite explicar por que ele mudou.

create table if not exists score_config (
  id uuid primary key default gen_random_uuid(),
  --: A ORDEM É POR CONTADOR, E NÃO POR RELÓGIO. `now()` é o instante da
  --: TRANSAÇÃO: duas versões gravadas na mesma transação nascem com o mesmo
  --: carimbo, e "a mais recente" viraria sorteio. O número cresce sozinho e
  --: não empata.
  versao bigint generated always as identity,
  --: {"imprensa": 30, "mercado": 20, …} — pontos por lente.
  pesos jsonb not null default '{}'::jsonb,
  --: `aegea` | `suave` | `forte` | `igual` | `so_tier1`
  regua_tier text not null default 'aegea',
  --: `n` | `log` | `bruto` | `cargo`
  regua_engajamento text not null default 'n',
  --: Códigos de fonte desligadas: ["bites"].
  fontes_desligadas jsonb not null default '[]'::jsonb,
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now()
);

create index if not exists score_config_recente on score_config (versao desc);


-- -- 7. os fatos do mês --------------------------------------------------------
--
-- §6.1: a evolução mensal traz "a lista de fatos do mês (cadastrável)". É o
-- que transforma uma curva em explicação — "caiu em março porque saíram as
-- DFs" —, e por isso é texto de gente, e não derivação.

create table if not exists score_fato (
  id uuid primary key default gen_random_uuid(),
  mes date not null,
  texto text not null,
  efeito text not null check (efeito in ('sustenta', 'pressiona', 'misto')),
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now()
);

create index if not exists score_fato_por_mes on score_fato (mes);


-- -- 8. o tipo do tema ---------------------------------------------------------
--
-- §6.2: o selo Estruturante / Operacional ao lado de cada tema. É CADASTRO, e
-- não derivação: "Boleto e cobrança" é operacional e "Privatização" é
-- estruturante por decisão de quem lê o setor, não por nada que esteja no
-- dado. Nulo = ainda não classificado.

alter table tema add column if not exists tipo text
  check (tipo in ('estruturante', 'operacional'));

comment on column tema.tipo is
  'Estruturante (afeta a tese da companhia) ou operacional (afeta o dia a dia). Cadastro, não derivação — ver 0048.';


-- -- 9. permissões --------------------------------------------------------------
--
-- `alter default privileges` (0009) já dá select/insert/update ao `painel_app`
-- em tabela nova. `delete` é explícito, e aqui vale para o que se SUBSTITUI:
-- reingerir um mês apaga as menções e o agregado daquele mês antes de gravar
-- os novos, e a coordenação corrige um fato ou uma estimativa que errou.
--
-- `score_config` fica de fora de propósito: é versionada, e apagar uma versão
-- apagaria a explicação de um número que alguém já leu.

grant delete on mencao, score_mes_fonte, score_fato, score_estimativa to painel_app;

comment on table lente is 'As cinco lentes do ISR. Fechado: uma sexta muda a fórmula (0048).';
comment on table score_fonte is 'De onde vem o sentimento de cada lente. Extensível sem deploy (0048).';
comment on table score_mes_fonte is 'Somas mensais por fonte, no grão que toda régua de ponderação consome (0048).';

commit;
