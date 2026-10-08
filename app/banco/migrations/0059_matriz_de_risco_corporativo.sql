-- 0059 — a matriz de risco corporativo da Aegea, e tema pode ter mais de um
--
-- 32 riscos em 8 "Risk Clusters", cada um com uma severidade já atribuída
-- (Crítico/Alto/Moderado) — dado estável da companhia, igual nas versões
-- v3/v4/v5 da planilha de taxonomia. Os códigos R01–R32 NÃO vêm da planilha
-- (ela não tem coluna de código nenhuma); são gerados aqui, na ordem das
-- linhas do documento de análise. Se a Aegea um dia publicar um código
-- oficial, é so trocar o valor de `codigo` — nada mais depende dele.
--
-- LIGAÇÃO COM TEMA: N:N, de propósito (`tema_risco`), mesmo sem nenhum caso
-- real de um tema com mais de um risco ainda — o pedido foi deixar pronto
-- para quando acontecer, não forçar 1-para-1 e ter que migrar depois.
--
-- NENHUM TEMA SAI CLASSIFICADO POR ESTA MIGRATION, com uma exceção: a
-- planilha nunca preencheu a coluna "Risk tracking" (0/104 linhas) — o
-- de-para tema↔risco sugerido no documento de análise é proposta do
-- analista, não dado da Aegea, e aplicá-lo aqui seria inventar classificação
-- de negócio sem validação, o mesmo erro que já vimos acontecer com
-- `atributo`. Fica em branco, classificável pela tela, igual `camada_lso`.
--
-- A EXCEÇÃO É R27 (Cobertura de Seguros): é o único risco da matriz sem
-- NENHUM tema candidato no documento de análise — um risco "orfão" tornaria
-- a lista de risco incompleta para quem for olhar o cadastro. Associado a
-- "Desempenho financeiro" (mesma área de gestão financeira onde R26,
-- Integridade das Demonstrações Financeiras, já aparece). Decisão de
-- escopo, não da Aegea — revisitar se/quando a validação oficial chegar.
--
-- R30 (Gestão de Crises) TAMBÉM fica sem tema, mas por um motivo diferente:
-- o documento o descreve como "transversal" — pode se aplicar a qualquer
-- subtema numa situação de crise, não é fixo a um. Não é omissão, é a
-- natureza do risco; não força um tema só para preencher.

begin;

create table if not exists risk_cluster (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

create table if not exists risco (
  id smallserial primary key,
  risk_cluster_id smallint not null references risk_cluster(id),
  codigo text not null unique,
  nome text not null,
  severidade text not null check (severidade in ('critico', 'alto', 'moderado')),
  ordem smallint not null,
  ativo boolean not null default true
);

comment on column risco.severidade is
  'critico | alto | moderado — já vem atribuída pela matriz da Aegea, não é derivada. Ver 0059.';

-- N:N DE PROPÓSITO: um tema pode apontar para mais de um risco (a planilha já
-- sugere "principal" + "secundário" em vários casos), e um risco pode valer
-- para mais de um tema. Sem coluna de papel (principal/secundário): essa
-- distinção também não está na planilha, fica para quando for validada.
create table if not exists tema_risco (
  tema_id integer not null references tema(id),
  risco_id smallint not null references risco(id),
  primary key (tema_id, risco_id)
);


-- -- os 8 risk clusters ---------------------------------------------------------

insert into risk_cluster (codigo, nome, ordem) values
  ('geopoliticos_e_estrategicos',       'Riscos Geopolíticos e Estratégicos',       1),
  ('investimentos_de_capital',          'Riscos em Investimentos de Capital',       2),
  ('operacionais',                      'Riscos Operacionais',                      3),
  ('tecnologia',                        'Riscos de Tecnologia',                     4),
  ('esg',                               'Riscos ESG',                               5),
  ('clientes',                          'Riscos com Clientes',                      6),
  ('financas_e_contabilidade',          'Riscos com Finanças e Contabilidade',      7),
  ('stakeholders_e_novos_negocios',     'Riscos com Stakeholders e novos negócios', 8)
on conflict (codigo) do nothing;


-- -- os 32 riscos ---------------------------------------------------------------

insert into risco (risk_cluster_id, codigo, nome, severidade, ordem) values
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R01', 'Instabilidade Política / Econômica', 'moderado', 1),
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R02', 'Relações Institucionais e Governamentais', 'moderado', 2),
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R03', 'Gestão de Portfólio e Estrutura de Capital', 'alto', 3),
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R04', 'Liquidez, Gestão da Dívida e Quebra de Covenants de financiamentos', 'alto', 4),
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R05', 'Legal e Regulatório', 'moderado', 5),
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R06', 'Práticas Ilegais ou Antiéticas', 'alto', 6),
  ((select id from risk_cluster where codigo = 'geopoliticos_e_estrategicos'), 'R07', 'Gestão do Capital Humano', 'moderado', 7),

  ((select id from risk_cluster where codigo = 'investimentos_de_capital'), 'R08', 'Gestão de Contratos e Terceiros', 'moderado', 1),
  ((select id from risk_cluster where codigo = 'investimentos_de_capital'), 'R09', 'Adoção e Efetividade de Novas Tecnologias', 'alto', 2),
  ((select id from risk_cluster where codigo = 'investimentos_de_capital'), 'R10', 'Gestão Ambiental em Projetos e Obras', 'alto', 3),

  ((select id from risk_cluster where codigo = 'operacionais'), 'R11', 'Gestão de Insumos', 'moderado', 1),
  ((select id from risk_cluster where codigo = 'operacionais'), 'R12', 'Gestão de Licenças', 'alto', 2),
  ((select id from risk_cluster where codigo = 'operacionais'), 'R13', 'Saúde e Segurança', 'alto', 3),
  ((select id from risk_cluster where codigo = 'operacionais'), 'R14', 'Meio ambiente operacional', 'alto', 4),
  ((select id from risk_cluster where codigo = 'operacionais'), 'R15', 'Integridade e Confiabilidade dos Ativos', 'alto', 5),
  ((select id from risk_cluster where codigo = 'operacionais'), 'R16', 'Entrega de água e tratamento de esgoto', 'critico', 6),
  ((select id from risk_cluster where codigo = 'operacionais'), 'R17', 'Tratamento de resíduos sólidos urbanos (RSU)', 'alto', 7),

  ((select id from risk_cluster where codigo = 'tecnologia'), 'R18', 'Cybersecurity e Continuidade Operacional', 'critico', 1),
  ((select id from risk_cluster where codigo = 'tecnologia'), 'R19', 'Proteção de Dados e informações', 'alto', 2),
  ((select id from risk_cluster where codigo = 'tecnologia'), 'R20', 'Proteção de Dados – LGPD', 'moderado', 3),

  ((select id from risk_cluster where codigo = 'esg'), 'R21', 'Externalidades e Mudanças Climáticas', 'critico', 1),
  ((select id from risk_cluster where codigo = 'esg'), 'R22', 'Gestão ESG e Sustentabilidade', 'alto', 2),
  ((select id from risk_cluster where codigo = 'esg'), 'R23', 'Relações com as Comunidades', 'alto', 3),

  ((select id from risk_cluster where codigo = 'clientes'), 'R24', 'Regularidade, Atendimento e Satisfação', 'alto', 1),
  ((select id from risk_cluster where codigo = 'clientes'), 'R25', 'Gestão de Crédito e Inadimplência', 'moderado', 2),

  ((select id from risk_cluster where codigo = 'financas_e_contabilidade'), 'R26', 'Integridade das Demonstrações Financeiras', 'moderado', 1),
  ((select id from risk_cluster where codigo = 'financas_e_contabilidade'), 'R27', 'Cobertura de Seguros', 'moderado', 2),
  ((select id from risk_cluster where codigo = 'financas_e_contabilidade'), 'R28', 'Contingências e Provisões', 'moderado', 3),

  ((select id from risk_cluster where codigo = 'stakeholders_e_novos_negocios'), 'R29', 'Integridade das Informações ao Mercado', 'moderado', 1),
  ((select id from risk_cluster where codigo = 'stakeholders_e_novos_negocios'), 'R30', 'Gestão de Crises', 'critico', 2),
  ((select id from risk_cluster where codigo = 'stakeholders_e_novos_negocios'), 'R31', 'Assunção de novos negócios', 'moderado', 3),
  ((select id from risk_cluster where codigo = 'stakeholders_e_novos_negocios'), 'R32', 'Novas Tendências e Futuro', 'moderado', 4)
on conflict (codigo) do nothing;


-- -- a única ligação tema↔risco carregada por esta migration --------------------
--
-- R27 (Cobertura de Seguros) não tem tema candidato no documento de análise.
-- Ver o comentário do topo do arquivo.

insert into tema_risco (tema_id, risco_id)
select
  (select id from tema where nome = 'Resultados financeiros e operacionais'),
  (select id from risco where codigo = 'R27')
where not exists (
  select 1 from tema_risco
  where tema_id = (select id from tema where nome = 'Resultados financeiros e operacionais')
    and risco_id = (select id from risco where codigo = 'R27')
);

commit;
