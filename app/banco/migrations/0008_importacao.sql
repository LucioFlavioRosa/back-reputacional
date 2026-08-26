-- =============================================================================
-- 0008 — Importação da planilha
--
-- ⚠ SCHEMA SEM APLICAÇÃO. Estas duas tabelas existem; o código que as usa NÃO
-- foi implementado. Não há rota, caso de uso nem tela de importação.
--
-- Estão aqui porque a forma delas foi decidida junto com o resto do modelo, e
-- porque `interacao.fonte`, `interacao.origem_aba` e `interacao.origem_linha`
-- já apontam para este fluxo. Quem for implementar encontra o desenho pronto;
-- quem for auditar o banco precisa saber que estão vazias por não terem dono.
--
-- O DESENHO PREVISTO: importar não é escrever
--
--   1. o arquivo é lido e cada linha vira uma `importacao_linha`, com os dados
--      brutos preservados
--   2. a aplicação propõe uma interação (`proposta`) e lista o que não
--      conseguiu resolver (`divergencias`) — veículo que não existe no
--      diretório, status fora do vocabulário, data ilegível
--   3. uma pessoa confere linha a linha e decide
--   4. só na confirmação as interações são criadas
--
-- O passo 3 é o ponto: importação de planilha sem conferência humana cria
-- duplicata de instituição em massa, e desfazer isso depois é pior do que
-- digitar de novo.
-- =============================================================================

create table importacao (
  id            uuid        primary key default gen_random_uuid(),
  arquivo_nome  text        not null,
  situacao      text        not null default 'processando'
                  check (situacao in ('processando','aguardando_conferencia','confirmada','cancelada')),
  criado_por    uuid        not null references usuario(id),
  criado_em     timestamptz not null default now(),
  confirmado_em timestamptz
);

create table importacao_linha (
  id            bigserial primary key,
  importacao_id uuid      not null references importacao(id) on delete cascade,

  -- De onde veio, para a pessoa conseguir voltar à planilha e conferir.
  aba           text      not null,
  linha_origem  int       not null,

  -- O que estava na célula, sem interpretação. Preservado mesmo depois de
  -- aceito: é o que permite reprocessar quando a regra de leitura mudar.
  dados_brutos  jsonb     not null,

  -- O que a aplicação entendeu, no formato de uma interação.
  proposta      jsonb,

  -- O que ela não conseguiu resolver sozinha. Lista vazia significa linha
  -- limpa; a tela de conferência ordena por esta coluna.
  divergencias  jsonb     not null default '[]'::jsonb,

  decisao       text      not null default 'pendente'
                  check (decisao in ('pendente','aceita','corrigida','descartada')),

  -- Preenchido na confirmação, ligando a linha da planilha ao registro criado.
  interacao_id  uuid      references interacao(id)
);

create index importacao_linha_importacao_id_decisao_idx
  on importacao_linha (importacao_id, decisao);

create index importacao_linha_dados_brutos_idx
  on importacao_linha using gin (dados_brutos);
create index importacao_linha_divergencias_idx
  on importacao_linha using gin (divergencias);
