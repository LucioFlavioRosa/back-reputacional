-- =============================================================================
-- 0004 — A interação: o registro que o painel inteiro conta
--
-- A FORMA: TABELA-MÃE + EXTENSÃO 1-1 POR FRENTE
--
-- `interacao` guarda o que TODA frente tem — data, instituição, status, pauta,
-- UF. O que só existe numa frente vai para uma tabela de extensão que
-- compartilha a chave primária: `data_publicacao` só faz sentido em imprensa,
-- `ementa` só em legislativo.
--
-- As duas alternativas foram descartadas:
--
--   uma tabela larga com tudo   sessenta colunas, das quais cinquenta nulas em
--                               cada linha, e nada impedindo preencher `ementa`
--                               numa interação de imprensa
--   uma tabela por frente       toda consulta do painel viraria sete `union`, e
--                               o KPI "total de interações" precisaria somar
--                               sete contagens que podem divergir
--
-- Com esta forma, contar é `select from interacao` e o campo específico só
-- existe onde faz sentido.
--
-- SOFT DELETE, SEMPRE
--
-- `arquivado_em` tira o registro das consultas e o mantém no banco. Interação
-- apagada de verdade levaria junto a trilha de auditoria e a atribuição de
-- histórico — e "some sem deixar rastro" é exatamente o que não se quer num
-- sistema cujo propósito é responder o que foi feito.
-- =============================================================================

create table interacao (
  id                 uuid        primary key default gen_random_uuid(),

  frente_id          smallint    not null references frente(id),
  data_interacao     date        not null,

  instituicao_id     uuid        not null references instituicao(id),
  interlocutor_id    uuid        references interlocutor(id),
  unidade_negocio_id smallint    references unidade_negocio(id),
  esfera_id          smallint    references esfera(id),

  -- Obrigatória: sem UF não há linha no mapa, e uma interação fora do mapa é
  -- uma interação que ninguém encontra.
  uf                 abrangencia not null,

  -- Quanto mais baixo, mais relevante a contraparte.
  --
  -- Guarda o NÚMERO do tier, e a chave estrangeira aponta para `relevancia`,
  -- onde os níveis são linhas. Era `check (tier between 1 and 3)`, escrito na
  -- coluna: acrescentar um nível exigia migration e deploy, e o filtro do
  -- painel tinha as opções fixas no código do front, em outro repositório.
  -- Duas fontes da verdade para a mesma lista, e nada as obrigava a concordar.
  tier               smallint    references relevancia(id),
  stakeholder_id     smallint    references stakeholder(id),

  status_id          smallint    not null references status(id),
  clima_id           smallint    references clima(id),
  resultado_id       smallint    references resultado(id),
  iniciativa_id      smallint    references iniciativa(id),

  pauta              text        not null,
  posicionamento     text,
  -- `relato` e `pendencias` são os campos sensíveis: saem do payload da API
  -- quando o papel não tem `ve_campos_sensiveis`.
  relato             text,
  encaminhamentos    text,
  pendencias         text,
  observacoes        text,
  registro_url       text,

  -- De onde o registro veio. Distingue o que foi digitado do que entrou em
  -- lote, e é o que permite refazer uma importação sem tocar no que foi
  -- cadastrado à mão.
  fonte              text        not null default 'cadastro_manual'
                       check (fonte in ('cadastro_manual','importacao_planilha','plataforma_ri')),

  visivel            boolean     not null default true,

  -- Rastro da planilha de origem, preenchido só quando `fonte` é importação.
  origem_aba         text,
  origem_linha       int,

  criado_por         uuid        not null references usuario(id),
  criado_em          timestamptz not null default now(),
  atualizado_em      timestamptz,
  arquivado_em       timestamptz
);

comment on column interacao.uf is
  'Obrigatória: o mapa do painel depende dela. Na importação é derivada da UF '
  'da instituição quando ausente.';

-- -- índices ------------------------------------------------------------------
--
-- Os quatro primeiros atendem os recortes que o painel faz o tempo todo. Os
-- índices de trigrama sustentam a busca livre (`q=`) sobre pauta, relato e
-- encaminhamentos; sem eles a busca vira varredura da tabela inteira.

create index interacao_data_interacao_idx on interacao (data_interacao desc);
create index interacao_frente_id_data_interacao_idx on interacao (frente_id, data_interacao desc);
create index interacao_instituicao_id_idx on interacao (instituicao_id);
create index interacao_interlocutor_id_idx on interacao (interlocutor_id);
create index interacao_unidade_negocio_id_idx on interacao (unidade_negocio_id);
create index interacao_criado_por_idx on interacao (criado_por);

-- Parciais: o painel nunca conta arquivado, e o índice fica menor por isso.
create index interacao_status_id_idx on interacao (status_id) where arquivado_em is null;
create index interacao_uf_idx on interacao (uf) where arquivado_em is null;

create index interacao_pauta_trgm_idx on interacao using gin (pauta gin_trgm_ops);
create index interacao_relato_trgm_idx on interacao using gin (relato gin_trgm_ops);
create index interacao_encaminhamentos_trgm_idx on interacao using gin (encaminhamentos gin_trgm_ops);


-- =============================================================================
-- Extensões por frente
--
-- `on delete cascade` na chave: a extensão não existe sem a mãe. Trocar a
-- frente de um registro apaga a extensão antiga e cria a nova — e as duas
-- coisas aparecem na auditoria (ver 0005).
-- =============================================================================

create table interacao_imprensa (
  interacao_id    uuid primary key references interacao(id) on delete cascade,
  formato_id      smallint references formato(id),
  data_atendida   date,
  data_publicacao date,
  link_materia    text,
  -- Array, e não tabela: são frases livres sem identidade própria, sempre lidas
  -- junto com a interação e nunca consultadas isoladamente.
  mensagens_chave text[]
);

-- NÃO há índice sobre `mensagens_chave`, e a ausência é deliberada: nada no
-- código filtra por essa coluna — ela é lida e escrita inteira, junto com a
-- interação.
--
-- Quando existir a consulta que se imagina ("quais atendimentos levaram a
-- mensagem X?"), o índice a criar é
--
--   create index interacao_imprensa_mensagens_idx
--     on interacao_imprensa using gin (mensagens_chave);
--
-- e a consulta precisa usar o operador de contenção (`@>`) para alcançá-lo:
-- `where mensagens_chave @> array['tarifa']`. Com `= any(...)` o GIN não é
-- usado, e o índice fica pago sem servir.

-- Serve governo, parceiros e eventos: as três registram órgão, cargo de quem
-- recebeu e, quando é evento, o nome dele.
create table interacao_institucional (
  interacao_id      uuid primary key references interacao(id) on delete cascade,
  natureza_orgao_id smallint references natureza_orgao(id),
  cargo_interlocutor text,
  nome_evento       text
);

create table interacao_legislativo (
  interacao_id  uuid primary key references interacao(id) on delete cascade,
  casa_id       smallint references casa(id),
  tramitacao_id smallint references tramitacao(id),
  prioridade    text check (prioridade in ('alta','media','baixa','monitoramento')),
  ementa        text
);

create table interacao_investidores (
  interacao_id      uuid primary key references interacao(id) on delete cascade,
  tipo_investidor_id smallint references tipo_investidor(id),
  formato_id        smallint references formato(id)
);

-- A frente interna registra demanda e entrega entre áreas da companhia, com
-- prazo — é a única que tem SLA.
create table interacao_interna (
  interacao_id uuid primary key references interacao(id) on delete cascade,
  natureza     text check (natureza in ('demanda','entrega')),
  cumprimento  text check (cumprimento in ('interno','externo','misto')),
  complexidade text check (complexidade in ('baixa','media','alta')),
  prazo_dias   smallint,
  data_retorno date
);


-- =============================================================================
-- Vínculos N-N
-- =============================================================================

create table interacao_tema (
  interacao_id uuid not null references interacao(id) on delete cascade,
  tema_id      int  not null references tema(id),
  primary key (interacao_id, tema_id)
);

-- Para "quais interações trataram de tarifa": sem ele, filtrar por tema varre
-- a tabela de vínculos inteira.
create index interacao_tema_tema_idx on interacao_tema (tema_id);

-- `papel` na chave primária: a mesma pessoa pode ser porta-voz de uma interação
-- e equipe de outra, e ambos os fatos importam.
create table interacao_pessoa_aegea (
  interacao_id    uuid not null references interacao(id) on delete cascade,
  pessoa_aegea_id uuid not null references pessoa_aegea(id),
  papel           text not null check (papel in ('porta_voz','equipe')),
  primary key (interacao_id, pessoa_aegea_id, papel)
);

-- A tela de porta-vozes conta aparições por pessoa e papel.
create index interacao_pessoa_aegea_pessoa_idx
  on interacao_pessoa_aegea (pessoa_aegea_id, papel);


-- -- comentários ---------------------------------------------------------------
--
-- `autor` é texto, e não só a FK: comentário importado da planilha tem o nome de
-- quem escreveu, mas não uma conta correspondente. Guardar o nome preserva a
-- atribuição sem inventar usuário.

create table comentario (
  id           uuid        primary key default gen_random_uuid(),
  interacao_id uuid        not null references interacao(id) on delete cascade,
  autor        text        not null,
  usuario_id   uuid        references usuario(id),
  escrito_em   timestamptz not null,
  texto        text        not null
);

create index comentario_interacao_id_escrito_em_idx on comentario (interacao_id, escrito_em);
create index comentario_usuario_idx on comentario (usuario_id);
