-- =============================================================================
-- 0049 — LENTES v2: o dossiê por stakeholder.
--
-- Especificação: `docs/handoff/lentes/LENTES-ESPECIFICACAO.md` e o protótipo
-- `docs/handoff/lentes/Lentes v2 - Proposta.html`.
--
-- A aba Lentes deixa de ser um resumo do cálculo e vira um DOSSIÊ: cada uma das
-- cinco lentes com a mesma estrutura — destaque, evolução, dois painéis, o que
-- revela e encaminhamentos. O índice em si não muda; muda o que se lê em volta
-- dele.
--
-- POR QUE ISTO É TABELA, E NÃO TEXTO NO CÓDIGO
-- --------------------------------------------
-- Metade do que a tela mostra não sai de planilha nenhuma: a manchete de cada
-- lente, a leitura em dois parágrafos, os insights numerados, o plano de ação,
-- a matriz de jornalistas, a trajetória de rating, o estudo de percepção. É
-- trabalho editorial mensal, feito por gente — e escrito no código ficaria
-- congelado no mês em que alguém o escreveu, envelhecendo em silêncio numa tela
-- que a diretoria lê como se fosse deste mês.
--
-- A PROCEDÊNCIA É PARTE DO DADO
-- -----------------------------
-- Todas as tabelas de conteúdo abaixo têm `exemplo boolean`. Elas nascem semeadas com o
-- conteúdo do protótipo — a matriz de jornalistas montada à mão pela agência, a
-- linha de rating, o estudo da Brunswick — porque uma tela vazia não se avalia.
-- Mas dado de ilustração apresentado como medição é a forma mais barata de
-- destruir a confiança num painel: a marca faz a tela DIZER que aquilo é
-- exemplo, e some sozinha quando alguém cadastrar o real.
--
-- O QUE AS PLANILHAS AINDA NÃO TRAZEM (24/09/2026)
-- -----------------------------------------------
--   AUTOR DA MATÉRIA. A Clipei não manda quem assina. Por isso a matriz de
--   jornalistas é cadastro inteiro, e `exposicao_sugerida` fica nula: quando a
--   coluna vier, ela passa a ser calculada pelo volume do jornalista (quintis)
--   e o cadastro só confirma.
--
--   SE A MENSAGEM FOI RESPONDIDA. A aba CM da Approach diz o que chegou, não o
--   que foi respondido. Daí `cm_resposta_mes`, semeada com os números do
--   relatório e marcada como exemplo — sem tela de digitação: a falta é do
--   fornecedor, e criar trabalho manual mensal para tapá-la esconderia o
--   problema em vez de cobrá-lo.
--
-- Idempotente: `create table if not exists`, `on conflict do nothing`.
-- =============================================================================

begin;

-- -- 1. o que aconteceu no mercado ---------------------------------------------
--
-- Alimenta DUAS visualizações da lente Mercado: o eventograma (a linha do tempo
-- que mostra pressão e reforço alternando) e a tabela de trajetória de rating.
-- São a mesma coisa vista de dois jeitos — uma ação de rating é um evento com
-- nota anterior e nota nova —, e separá-las em duas tabelas faria a mesma
-- notícia ser digitada duas vezes.

create table if not exists evento_mercado (
  id uuid primary key default gen_random_uuid(),
  data date not null,
  --: `resultado` (divulgação), `rating`, `operacao` (captação, aumento de
  --: capital), `governanca` (saída de executivo, mudança de controle), `outro`.
  tipo text not null check (tipo in ('resultado', 'rating', 'operacao', 'governanca', 'outro')),
  --: Só nos eventos de rating. A agência é texto e não dicionário: são três, e
  --: um dicionário de três linhas custa mais do que resolve.
  agencia text,
  nota_anterior text,
  nota_nova text,
  --: `estavel`, `negativa`, `positiva`, `em observacao` — como a agência a
  --: escreve. Texto pelo mesmo motivo.
  perspectiva text,
  texto text not null,
  --: Como o evento age sobre a reputação. É o que pinta a borda do mês no
  --: eventograma, e o mesmo vocabulário de `score_fato`.
  efeito text not null check (efeito in ('sustenta', 'pressiona', 'misto')),
  exemplo boolean not null default false,
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now()
);

create index if not exists evento_mercado_por_data on evento_mercado (data desc);


-- -- 2. o que o mercado responde quando perguntam ------------------------------
--
-- Estudo de percepção: um instituto entrevista investidores e analistas e
-- devolve notas de 1 a 5 por atributo. Duas tabelas porque um estudo tem vários
-- atributos e a tela compara ATRIBUTOS entre si — "eficiência operacional 4,0 ×
-- solidez financeira 1,8" é a leitura inteira da lente Mercado hoje.

create table if not exists estudo_percepcao (
  id uuid primary key default gen_random_uuid(),
  instituto text not null,
  data date not null,
  --: Quantas entrevistas. Vai para a tela: uma nota de 20 entrevistas não se
  --: lê como uma de 200.
  amostra integer,
  publico text,
  observacao text,
  exemplo boolean not null default false,
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now()
);

create table if not exists estudo_atributo (
  estudo_id uuid not null references estudo_percepcao(id) on delete cascade,
  atributo text not null,
  --: De 1 a 5, com uma casa: o estudo devolve 1,8 e arredondar para 2 apagaria
  --: justamente a distância que a tela existe para mostrar.
  nota numeric(2,1) not null check (nota >= 1 and nota <= 5),
  comentario text,
  ordem smallint not null default 0,
  primary key (estudo_id, atributo)
);


-- -- 3. com quem a imprensa fala ------------------------------------------------
--
-- A matriz de relacionamento: relevância, exposição e proximidade, de 1 a 5
-- cada. A soma dá a prioridade — P1 13–15 (relacionamento contínuo), P2 10–12
-- (semestral), P3 7–9 (tático), P4 abaixo de 7 (monitoramento).
--
-- CADASTRO INTEIRO, POR ORA. A pontuação de hoje foi montada à mão pela
-- agência, e não sai da clipagem — a Clipei não manda quem assina a matéria.
-- `exposicao_sugerida` fica reservada para quando a coluna de autor chegar: aí
-- o volume do jornalista na base dá o quintil, e a pessoa confirma ou corrige
-- em vez de estimar do zero.

create table if not exists jornalista_matriz (
  id uuid primary key default gen_random_uuid(),
  --: O contato no CRM, quando existe. Nulo é comum e não é falha: a matriz
  --: nasce de um relatório da agência, e nem todo jornalista citado nele já
  --: está no diretório de contrapartes.
  interlocutor_id uuid references interlocutor(id),
  nome text not null,
  veiculo text,
  relevancia smallint not null check (relevancia between 1 and 5),
  exposicao smallint not null check (exposicao between 1 and 5),
  proximidade smallint not null check (proximidade between 1 and 5),
  --: O que a base sugeriria, quando souber o autor. Nulo hoje, sempre.
  exposicao_sugerida smallint check (exposicao_sugerida between 1 and 5),
  exemplo boolean not null default false,
  ativo boolean not null default true,
  atualizado_em timestamptz not null default now()
);

--: Dois cadastros da mesma pessoa no mesmo veículo são erro de digitação, e não
--: duas relações. O índice é sobre o nome normalizado porque "Taís Hirata" e
--: "Tais  Hirata" são a mesma jornalista.
create unique index if not exists jornalista_matriz_unica
  on jornalista_matriz (lower(regexp_replace(nome, '\s+', ' ', 'g')), coalesce(veiculo, ''))
  where ativo;


-- -- 4. quantas mensagens foram respondidas ------------------------------------
--
-- A aba CM da Approach diz o que CHEGOU: uma linha por mensagem recebida. Ela
-- não diz o que foi respondido — e "recebidas × respondidas" é o gráfico
-- principal da lente Clientes.
--
-- NÃO HÁ TELA DE DIGITAÇÃO, e é decisão do dono do produto: abrir um formulário
-- para alguém teclar doze números por mês cria uma obrigação recorrente para
-- resolver uma falta que é do fornecedor. O que entra agora são os números do
-- relatório Jan-Ago, semeados e MARCADOS COMO EXEMPLO — a tela desenha o
-- gráfico, o "?" diz que o dado não vem da base, e a cobrança fica onde deve:
-- na coluna que a Approach ainda não manda.
--
-- Um mês sem linha aqui NÃO vira zero: vira "—" no topo da barra, com só as
-- recebidas desenhadas. Zero diria que ninguém respondeu nada, que é uma
-- acusação, e não um dado que falta.

create table if not exists cm_resposta_mes (
  --: O primeiro dia do mês, como em `mencao`.
  mes date primary key,
  respondidas integer not null check (respondidas >= 0),
  --: De onde veio o número — hoje, o relatório do cliente.
  origem text,
  --: Enquanto for o número do relatório, e não a coluna do fornecedor.
  exemplo boolean not null default false,
  atualizado_por uuid references usuario(id),
  atualizado_em timestamptz not null default now()
);


-- -- 5. o texto que a lente carrega --------------------------------------------
--
-- A curadoria mensal: manchete, títulos-conclusão, leitura e insights. Um
-- registro por (lente, mês, versão) — a tabela SÓ CRESCE, e a linha vigente é a
-- de maior versão. Publicar é gravar uma versão com `status = 'publicado'`.
--
-- POR QUE VERSIONAR. O texto é o que a diretoria cita; saber o que estava
-- escrito quando ela leu é a mesma necessidade que fez `score_config` ser
-- versionada. Editar no lugar apagaria a frase que alguém repetiu numa reunião.

create table if not exists curadoria_lente (
  id uuid primary key default gen_random_uuid(),
  lente_id smallint not null references lente(id),
  mes date not null,
  versao bigint generated always as identity,
  status text not null default 'rascunho' check (status in ('rascunho', 'publicado')),

  --: Uma frase. O limite existe porque manchete que não cabe numa linha deixa
  --: de ser manchete.
  manchete text check (manchete is null or length(manchete) <= 280),
  --: Os títulos-conclusão: a frase que cada gráfico prova. Regra de design da
  --: §1 — o título nunca pode contradizer o dado.
  evolucao_titulo text,
  painel_a_titulo text,
  painel_b_titulo text,
  --: 2 a 4 parágrafos, como lista de textos.
  leitura jsonb not null default '[]'::jsonb,
  --: 3 a 4 itens `{titulo, texto}`.
  revela jsonb not null default '[]'::jsonb,
  --: Enquanto o texto for o do relatório Jan-Ago, transcrito, e não escrito
  --: pela curadoria naquele mês. O "?" de cada bloco lê esta marca.
  exemplo boolean not null default false,

  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now()
);

create index if not exists curadoria_por_lente_e_mes
  on curadoria_lente (lente_id, mes, versao desc);


-- -- 6. o que se decidiu fazer -------------------------------------------------
--
-- O plano de ação de cada lente. `mes_origem` é o mês em que a decisão foi
-- tomada, e não o prazo: encaminhamento aberto CONTINUA VISÍVEL nos meses
-- seguintes até alguém concluí-lo — some da tela por conclusão, nunca por
-- passagem do tempo. Uma ação que desaparece no virar do mês é uma ação que
-- ninguém cobrou.

create table if not exists encaminhamento (
  id uuid primary key default gen_random_uuid(),
  lente_id smallint not null references lente(id),
  mes_origem date not null,
  acao text not null,
  --: Quem toca. Texto, e não pessoa cadastrada: aqui se escreve "RI +
  --: Financeiro", que é uma dupla de áreas, e não um nome do diretório.
  responsavel text,
  --: Também texto: o relatório fala em "imediato", "curto prazo", "3T26" —
  --: prazos que uma data transformaria em falsa precisão.
  prazo text,
  status text not null default 'aberto'
    check (status in ('aberto', 'em_andamento', 'concluido')),
  concluido_em date,
  --: Idem: veio do relatório, não de uma decisão tomada nesta ferramenta.
  exemplo boolean not null default false,
  criado_por uuid references usuario(id),
  criado_em timestamptz not null default now()
);

create index if not exists encaminhamento_aberto
  on encaminhamento (lente_id, status) where status <> 'concluido';


-- -- 7. o que a menção passa a guardar ------------------------------------------

--: O TEOR da mensagem, no vocabulário do fornecedor: Reclamação, Dúvida,
--: Elogio, Informação, Marcação, NPR. É o Painel B da lente Clientes.
alter table mencao add column if not exists teor text;

--: SE A MENSAGEM É UM CONTATO DE VERDADE. Marcação (alguém citou a Aegea num
--: post) e NPR (não pertinente) chegam pelo mesmo canal e não são gente
--: procurando a companhia: 18% da base de janeiro a junho.
--:
--: NÃO É PARA ESCONDÊ-LAS. Elas continuam contadas e aparecem na tela, com o
--: motivo escrito. O que a marca faz é permitir a SEGUNDA taxa de resposta, a
--: operacional — a mesma quantidade de respostas sobre 3.701 mensagens em vez
--: de 4.509 é um percentual 22% maior, e é esse que diz como o atendimento
--: está indo.
alter table mencao add column if not exists acionavel boolean;

--: Quem assina a matéria. Nulo em tudo hoje: a Clipei não manda a coluna. Fica
--: pronta para o dia em que mandar — é ela que liga a clipagem à matriz de
--: jornalistas e faz a exposição deixar de ser estimada.
alter table mencao add column if not exists autor text;

create index if not exists mencao_por_teor on mencao (mes, teor)
  where teor is not null;


-- -- 8. permissão ---------------------------------------------------------------
--
-- A regra do projeto: migration nova concede `delete` a `painel_app`. A 0009
-- concedeu em massa e só alcança o que já existia; `select`, `insert` e
-- `update` vêm depois pelo `alter default privileges` — `delete` não vem.

grant select, insert, update, delete on
  evento_mercado, estudo_percepcao, estudo_atributo, jornalista_matriz,
  cm_resposta_mes, curadoria_lente, encaminhamento
to painel_app;

-- NADA DE `grant ... on all sequences`. Foi a primeira versão desta migration, e
-- um teste a derrubou: a trilha de auditoria tem sequence PRÓPRIA, e o papel da
-- aplicação não pode consumi-la — numeração com buraco é exatamente o que se
-- olha para decidir se alguém apagou alguma coisa. O grant também era inútil:
-- `curadoria_lente.versao` é `generated always as identity`, e o Postgres
-- resolve a sequence dela por dentro, com o `insert` na tabela.


comment on table evento_mercado is 'Eventograma e trajetória de rating da lente Mercado (0049).';
comment on table estudo_percepcao is 'Estudo de percepção do mercado financeiro (0049).';
comment on table jornalista_matriz is 'Matriz de relacionamento com jornalistas: cadastro, porque a Clipei não manda o autor (0049).';
comment on table cm_resposta_mes is 'Quantas mensagens foram respondidas no mês — do relatório, marcado como exemplo, até a Approach mandar a coluna (0049).';
comment on table curadoria_lente is 'O texto editorial de cada lente, versionado (0049).';
comment on table encaminhamento is 'Plano de ação por lente; some por conclusão, nunca por passagem do mês (0049).';

commit;
