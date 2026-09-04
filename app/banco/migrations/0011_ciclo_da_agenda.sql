-- A interação deixa de ser um fato consumado e passa a ser uma AGENDA com
-- ciclo de vida.
--
-- O QUE MUDA, E POR QUE
-- =====================
-- O modelo de 0004 descreve o que ACONTECEU: pauta, relato, clima, resultado.
-- Serve para registrar. Não serve para a pergunta que move esta plataforma —
-- "estamos sendo ativos o bastante, e o que prometemos aconteceu?".
--
-- Responder isso exige separar o PREVISTO do REAL:
--
--     pedida por quem  →  planejada  →  confirmada ou declinada  →  realizada
--                                                                      ↓
--                                                              desdobra em outra
--
-- Antes da reunião existem expectativa, participantes previstos e materiais de
-- apoio. Depois existem resumo, clima real, quem de fato foi, e o que saiu de
-- lá. Guardar os dois lados é o que permite comparar o que se esperava com o
-- que houve — que é a medida de eficiência, e não o número de reuniões.
--
-- TUDO ANULÁVEL, SEM EXCEÇÃO
-- ==========================
-- Os 60 registros existentes vieram de planilha e estão incompletos. Uma coluna
-- `not null` com valor padrão inventaria história: diria que uma reunião de
-- 2024 "não previa desdobramento" quando na verdade ninguém foi perguntado.
--
-- Nulo aqui quer dizer NÃO INFORMADO, e a tela precisa mostrar isso como tal —
-- nunca como "não". A diferença entre "não sabemos" e "não" é justamente o que
-- esta plataforma existe para reduzir.

-- =============================================================================
-- 1. QUEM PEDIU A AGENDA
-- =============================================================================
-- A coluna já existia (`iniciativa`), com os valores `procurada` e `provocada`
-- e o comentário "Quem procurou quem" — que não diz quem procurou quem.
--
-- Ambiguidade cara: é deste campo que sai o indicador "a Aegea está sendo
-- ativa?". Lido ao contrário, o painel afirmaria exatamente o oposto da
-- realidade, e ninguém desconfiaria.
--
-- Confirmada a direção com quem conhece o dado. Os CÓDIGOS ficam — são a chave
-- estrangeira de 60 registros e de todo o front. O que muda é o rótulo, que é o
-- que as pessoas leem.
update iniciativa set nome = 'Pedida pela Aegea'    where codigo = 'provocada';
update iniciativa set nome = 'Pedida por terceiro'  where codigo = 'procurada';

comment on table iniciativa is
  'Quem pediu a agenda. `provocada` = a Aegea pediu; `procurada` = a Aegea foi procurada.';


-- =============================================================================
-- 1b. O ESTADO QUE FALTAVA: CONFIRMADA
-- =============================================================================
-- O dicionario tinha `agendado`, `em_analise`, `aguardando_*`, `realizado` e
-- `declinado`. Faltava a diferenca entre "pedimos e estamos esperando" e "as
-- duas partes confirmaram" — e essa diferenca e metade do que o ciclo existe
-- para registrar: uma agenda pedida ha tres semanas e ainda nao confirmada e
-- exatamente o caso que ninguem ve hoje.
--
-- `ordem` entre `aguardando_edelman` (4) e `atendido` (5). Os codigos
-- existentes nao se movem: `ordem` e o que a tela usa para listar, e reordenar
-- os outros mudaria telas que ninguem pediu para mudar.
insert into status (codigo, nome, grupo, ordem)
select 'confirmada', 'Confirmada', 'aberto', 45
 where not exists (select 1 from status where codigo = 'confirmada');


-- =============================================================================
-- 2. O CICLO: EXPECTATIVA, DECLÍNIO, DESDOBRAMENTO
-- =============================================================================
alter table interacao
  --: O que se espera desta agenda, escrito ANTES dela.
  --:
  --: Fica ao lado de `relato` de propósito: lado a lado, a distância entre o
  --: que se esperava e o que houve é legível sem consulta nenhuma. É a única
  --: forma de a base responder "o que prometemos costuma acontecer?".
  add column if not exists expectativa text,

  --: Quem declinou, quando alguém declinou. `status = 'declinado'` diz que
  --: houve recusa; esta coluna diz de qual lado veio, e a de baixo diz por quê.
  --:
  --: Separado do status porque a leitura estratégica é oposta nos dois casos:
  --: agenda declinada PELA Aegea é escolha; declinada pela outra parte é porta
  --: que se fechou. Somar as duas num número só apaga a diferença.
  add column if not exists declinado_por text
    check (declinado_por in ('aegea','outra_parte')),
  add column if not exists motivo_declinio text,

  --: Esta agenda nasceu de outra?
  --:
  --: Auto-referência: o encadeamento é o histórico da relação, e é isso que
  --: transforma reuniões soltas numa AGENDA ESTRATÉGICA com evolução. Sem ele,
  --: a terceira conversa com o mesmo órgão parece a primeira.
  --:
  --: `on delete set null` e não `cascade`: apagar uma agenda antiga não pode
  --: levar junto as que vieram depois — elas aconteceram.
  add column if not exists origem_interacao_id uuid
    references interacao(id) on delete set null,

  --: Prevê continuidade? Nulo = não informado, e não "não".
  --:
  --: É só a INTENÇÃO. A próxima agenda, quando existir de verdade, aponta para
  --: esta por `origem_interacao_id`. Criar a agenda seguinte em rascunho aqui
  --: povoaria a base de reuniões que ninguém marcou.
  add column if not exists preve_desdobramento boolean,

  --: O clima que se ESPERAVA, na mesma escala do que se mediu.
  --:
  --: Aponta para `clima`, o mesmo dicionario de `clima_id`, e e o que permite o
  --: painel dizer "em 8 de 10 agendas o clima veio pior do que se esperava".
  --: Texto livre em `expectativa` nao responde isso: nao se soma, nao se
  --: compara, nao vira serie.
  --:
  --: Duas colunas para o mesmo dicionario, e nao uma coluna com "momento": a
  --: interacao tem UM clima esperado e UM real, e uma tabela de ligacao para
  --: guardar dois valores conhecidos seria estrutura demais para o problema.
  add column if not exists clima_esperado_id smallint references clima(id);

comment on column interacao.clima_esperado_id is
  'Clima previsto, na mesma escala de `clima_id` (o real). Nulo = nao informado.';

comment on column interacao.expectativa is
  'O que se esperava desta agenda, registrado antes dela. Compare com `relato`.';
comment on column interacao.origem_interacao_id is
  'Agenda que deu origem a esta. Encadeia a evolução da relação.';
comment on column interacao.preve_desdobramento is
  'Intenção de continuidade. Nulo = não informado.';

-- A busca natural é "o que veio depois desta agenda?", e sem índice ela varre a
-- tabela inteira a cada abertura de ficha.
create index if not exists interacao_origem_idx
  on interacao (origem_interacao_id)
  where origem_interacao_id is not null;

-- Um ciclo (A origina B, B origina A) tornaria o histórico infinito e travaria
-- qualquer leitura recursiva. O caso trivial dá para barrar sem custo; ciclos
-- longos ficam para a aplicação, que é onde há contexto para explicar o erro.
-- `add constraint` NAO aceita `if not exists` — o Postgres nao tem essa
-- forma, e escrever assim e erro de sintaxe. O bloco confere antes.
--
-- Vale o mesmo motivo do resto do arquivo: durante o desenvolvimento esta
-- migration e aplicada a mao num banco que ja subiu, e uma segunda aplicacao
-- que estoura no meio deixa o schema pela metade — com as colunas criadas e a
-- restricao faltando, que e o pior dos dois estados.
do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'interacao_nao_origina_a_si_mesma'
       and conrelid = 'interacao'::regclass
  ) then
    alter table interacao
      add constraint interacao_nao_origina_a_si_mesma
      check (origem_interacao_id is null or origem_interacao_id <> id);
  end if;
end $$;


-- =============================================================================
-- 3. PARTICIPANTES: O PREVISTO E O REAL
-- =============================================================================
-- TODOS os participantes da outra parte moram aqui, o principal inclusive.
--
-- A primeira versao guardava so os DEMAIS, e o principal ficava apenas em
-- `interacao.interlocutor_id`. Parecia economico e tinha um buraco: nao havia
-- onde dizer se o principal compareceu. Justamente a pessoa mais importante da
-- reuniao era a unica sem presenca — e "participantes reais" e metade do que
-- esta onda existe para registrar.
--
-- `interacao.interlocutor_id` PERMANECE, e aponta para a linha marcada como
-- principal. Nao e duplicacao a toa: 67 usos em filtros, relatorios, exportacao
-- e diretorio dependem daquela coluna, e reescreve-los junto com esta mudanca
-- seria empilhar dois riscos. Quem mantem os dois em acordo e o repositorio, e
-- ha teste para isso.
create table if not exists interacao_interlocutor (
  interacao_id    uuid not null references interacao(id) on delete cascade,
  interlocutor_id uuid not null references interlocutor(id),

  --: NULO É NÃO INFORMADO, e é o estado dos registros que vieram da planilha.
  --:
  --: `previsto` é quem se esperava; `presente` é quem de fato foi; `ausente` é
  --: quem foi esperado e não veio — e essa terceira é a mais valiosa das três,
  --: porque uma reunião em que o decisor não apareceu não é a reunião que se
  --: pediu, ainda que conste como realizada.
  presenca text check (presenca in ('previsto','presente','ausente')),

  --: Quem representa a outra parte nesta agenda. No maximo um por interacao —
  --: garantido pelo indice unico parcial abaixo, e nao por convencao.
  principal boolean not null default false,

  primary key (interacao_id, interlocutor_id)
);

-- `create table if not exists` acima PULA A TABELA INTEIRA quando ela ja existe
-- — e nao acrescenta coluna nenhuma. Num banco onde uma versao anterior desta
-- migration ja rodou, `principal` simplesmente nao nasceria, e o indice abaixo
-- estouraria com "column does not exist".
--
-- Por isso as duas formas: a coluna esta no `create table` para banco novo, e
-- aqui para banco que ja tem a tabela. As duas idempotentes.
alter table interacao_interlocutor
  add column if not exists principal boolean not null default false;


-- UM principal por agenda, no maximo. Indice unico PARCIAL: sem o `where`, ele
-- exigiria unicidade tambem entre os `false`, e nenhuma agenda poderia ter dois
-- participantes comuns.
create unique index if not exists interacao_interlocutor_um_principal_idx
  on interacao_interlocutor (interacao_id)
  where principal;

comment on table interacao_interlocutor is
  'Participantes da outra parte, além do interlocutor principal em interacao.interlocutor_id.';

create index if not exists interacao_interlocutor_por_pessoa_idx
  on interacao_interlocutor (interlocutor_id);


-- OS REGISTROS QUE JA EXISTEM ENTRAM NA TABELA NOVA.
--
-- Agora que ela guarda TODOS os participantes, deixar os 60 registros de fora
-- faria a ficha deles mostrar "nenhum participante" para agendas que tem
-- interlocutor havia meses.
--
-- `presenca` fica NULA de proposito: ninguem perguntou a essas pessoas se
-- compareceram, e inventar `presente` seria afirmar presenca que ninguem
-- registrou. Nulo diz "nao informado", que e a verdade.
insert into interacao_interlocutor (interacao_id, interlocutor_id, presenca, principal)
select id, interlocutor_id, null, true
  from interacao
 where interlocutor_id is not null
on conflict (interacao_id, interlocutor_id) do nothing;


-- Do lado da Aegea a tabela já existia, com `papel` (porta-voz ou equipe). Só
-- faltava a mesma distinção entre quem foi previsto e quem foi.
alter table interacao_pessoa_aegea
  add column if not exists presenca text check (presenca in ('previsto','presente','ausente'));

comment on column interacao_pessoa_aegea.presenca is
  'Previsto, presente ou ausente. Nulo = não informado (registros anteriores a esta coluna).';


-- =============================================================================
-- 4. MATERIAIS
-- =============================================================================
-- Três momentos, uma tabela: material de APOIO existe antes da reunião;
-- OBTIDO e PRODUZIDO existem depois. Separar em três tabelas repetiria a mesma
-- estrutura três vezes para distinguir o que uma coluna distingue.
--
-- `interacao.registro_url` continua existindo e é outra coisa: o link do
-- registro da interação (a matéria publicada, a ata). Materiais são os
-- documentos que circulam em torno da agenda.
create table if not exists material (
  id           uuid        primary key default gen_random_uuid(),
  interacao_id uuid        not null references interacao(id) on delete cascade,

  momento      text        not null
                 check (momento in ('apoio','obtido','produzido')),

  titulo       text        not null,

  --: O link para SharePoint/Drive. É assim que o material chega hoje.
  url          text,

  --: PREVISTO PARA O FUTURO, e propositalmente inerte agora.
  --:
  --: Guardar arquivo no painel traz armazenamento, limite de tamanho,
  --: antivírus e política de retenção — uma frente inteira. A coluna nasce aqui
  --: para que, quando essa frente vier, ela não exija migrar dados existentes:
  --: material vira "tem arquivo" sem deixar de ser material.
  --:
  --: Nenhuma rota escreve nela hoje.
  arquivo_id   uuid,

  --: Ao menos um dos dois, senão o material não é nada além de um título.
  constraint material_precisa_apontar_para_algo
    check (url is not null or arquivo_id is not null),

  observacao   text,
  criado_por   uuid        not null references usuario(id),
  criado_em    timestamptz not null default now()
);

comment on table material is
  'Documentos de uma agenda: apoio (antes), obtido e produzido (depois).';

create index if not exists material_por_interacao_idx on material (interacao_id, momento);

-- SEM INDICE EM `criado_por`, E E DELIBERADO.
--
-- A regra geral manda indexar coluna de chave estrangeira: o Postgres nao o faz
-- sozinho, e sem indice tanto o JOIN quanto a checagem de `on delete` varrem a
-- tabela. `interacao.criado_por` TEM indice, e por um motivo concreto — o papel
-- `pode_editar_proprio` filtra por ele a cada edicao.
--
-- Aqui nao existe esse motivo. Ninguem pergunta "quais materiais fulano
-- cadastrou", e apagar um usuario e impossivel por construcao: dez chaves
-- estrangeiras barram, e a remocao do produto e `ativo = false`. O indice nunca
-- seria lido, e custaria escrita em toda insercao de material.
--
-- Se um dia houver tela de "meus materiais", este e o comentario a apagar.


-- =============================================================================
-- 5. PERMISSÕES E TRILHA PARA O QUE ACABOU DE NASCER
-- =============================================================================
-- `0009` concedeu sobre `all tables in schema public` — as que existiam NAQUELE
-- momento. Tabela criada depois nasce sem permissão nenhuma, e a aplicação
-- receberia "permission denied" só quando alguém tentasse salvar. Explícito
-- aqui, junto de quem cria, para não virar uma caçada depois.
grant select, insert, update on interacao_interlocutor to painel_app;
grant select, insert, update on material               to painel_app;

-- Apagar, pelo mesmo critério de 0009: só linhas que pertencem a um agregado e
-- são substituídas junto com ele. A interação em si continua sem `delete` — ela
-- se arquiva.
grant delete on interacao_interlocutor to painel_app;
grant delete on material               to painel_app;


-- A trilha dos VÍNCULOS. `interacao_tema` e `interacao_pessoa_aegea` já a têm
-- desde 0005; participante da outra parte é a mesma natureza de fato — quem
-- entrou e quem saiu da agenda — e a ausência aqui abriria um buraco calado
-- justamente no dado que esta onda existe para registrar.
drop trigger if exists auditar_interacao_interlocutor on interacao_interlocutor;
create trigger auditar_interacao_interlocutor
  after insert or delete on interacao_interlocutor
  for each row execute function registrar_vinculo();
