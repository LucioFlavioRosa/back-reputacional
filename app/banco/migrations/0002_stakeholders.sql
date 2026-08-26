-- =============================================================================
-- 0002 — Quem está do outro lado, e quem está do nosso
--
--   instituicao    o veículo, o órgão, a entidade, o fundo, a proposição
--   interlocutor   a pessoa daquela instituição
--   pessoa_aegea   quem da Aegea participou
--
-- POR QUE HÁ UM DIRETÓRIO, E NÃO TEXTO LIVRE NA INTERAÇÃO
--
-- Na planilha o nome do veículo é digitado a cada linha, e "Folha de S.Paulo",
-- "Folha de Sao Paulo" e "folha" viram três veículos diferentes na hora de
-- contar. Um diretório com chave própria é o que permite responder "quantas
-- vezes falamos com a Folha este ano" — que é a pergunta que o painel existe
-- para responder.
--
-- A NORMALIZAÇÃO DO NOME
--
-- `nome_normalizado` guarda o nome sem acento e em minúsculas; é ele que carrega
-- a restrição de unicidade e o índice de semelhança. O `nome` original fica
-- intacto para exibição. Quem preenche os dois é a aplicação, no mesmo caso de
-- uso — ver `contextos/stakeholders`.
-- =============================================================================

-- `tipo` decide em quais frentes a instituição aparece na busca do cadastro, e
-- é o que impede oferecer um fundo de investimento como veículo de imprensa.
create table instituicao (
  id               uuid        primary key default gen_random_uuid(),
  nome             text        not null,
  nome_normalizado text        not null,
  tipo             text        not null check (tipo in (
                     'veiculo','orgao','entidade','escritorio',
                     'investidor','proposicao','area_interna')),
  esfera_id        smallint    references esfera(id),
  uf               abrangencia,
  ativo            boolean     not null default true,
  criado_em        timestamptz not null default now()
);

-- Unicidade por (nome, TIPO), e não só por nome: "Águas do Rio" existe como
-- `area_interna` e pode existir como `orgao` numa proposição legislativa. Sem o
-- tipo na chave, cadastrar o segundo seria impossível.
create unique index instituicao_nome_normalizado_tipo_idx
  on instituicao (nome_normalizado, tipo);

-- Índice de trigrama para a busca com erro de digitação do cadastro. Sem ele, a
-- pessoa não acha "Estadão" digitando "estadao" e cadastra um veículo novo.
create index instituicao_nome_trgm_idx
  on instituicao using gin (nome_normalizado gin_trgm_ops);


-- `instituicao_id` é nulo porque existe interlocutor sem vínculo estável — um
-- jornalista freelancer, um consultor. Forçar o vínculo obrigaria a inventar uma
-- instituição falsa, que é pior do que a ausência.
create table interlocutor (
  id               uuid        primary key default gen_random_uuid(),
  nome             text        not null,
  nome_normalizado text        not null,
  instituicao_id   uuid        references instituicao(id),
  cargo            text,
  tipo             text        check (tipo in (
                     'jornalista','gestor_publico','parlamentar',
                     'analista_investidor','executivo_entidade',
                     'representante_entidade','outro')),
  ativo            boolean     not null default true,
  criado_em        timestamptz not null default now()
);

-- Mesmo nome em instituições diferentes são pessoas diferentes.
create unique index interlocutor_nome_normalizado_instituicao_id_idx
  on interlocutor (nome_normalizado, instituicao_id);

create index interlocutor_instituicao_idx on interlocutor (instituicao_id);
create index interlocutor_nome_trgm_idx
  on interlocutor using gin (nome_normalizado gin_trgm_ops);


-- `eh_porta_voz` separa quem FALA em nome da companhia de quem participou da
-- interação. A tela de porta-vozes conta aparições por pessoa, e sem esta marca
-- ela contaria também quem só estava na sala.
create table pessoa_aegea (
  id               uuid        primary key default gen_random_uuid(),
  nome             text        not null,
  nome_normalizado text        not null unique,
  cargo            text,
  eh_porta_voz     boolean     not null default false,
  ativo            boolean     not null default true,
  criado_em        timestamptz not null default now()
);


-- -- temas de quem, e não só da interação ---------------------------------------
--
-- Os temas de um interlocutor são a resposta para "sobre o que esta pessoa
-- costuma falar" — usado ao preparar uma conversa. São independentes dos temas
-- de cada interação: alguém pode ser referência em tarifa e nunca ter tratado
-- do assunto conosco.

create table interlocutor_tema (
  interlocutor_id uuid not null references interlocutor(id) on delete cascade,
  tema_id         int  not null references tema(id),
  primary key (interlocutor_id, tema_id)
);

create table pessoa_aegea_tema (
  pessoa_aegea_id uuid not null references pessoa_aegea(id) on delete cascade,
  tema_id         int  not null references tema(id),
  primary key (pessoa_aegea_id, tema_id)
);
