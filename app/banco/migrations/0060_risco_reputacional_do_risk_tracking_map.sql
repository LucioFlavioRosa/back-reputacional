-- 0060 — o eixo de risco do `Risk tracking map`, e o enquadramento de cada subtema
--
-- DE ONDE VEM. A planilha `20260917_Aegea_Taxonomia_Publicos_v2.xlsx` (set/2026)
-- tem três abas. Duas já estão neste banco: a `Taxonomia de temas` é a taxonomia
-- v4 que a `0058` carregou — os 7 pilares são `bloco_tema`, os 41 temas
-- estratégicos são `macro_tema` e os 104 subtemas são os 104 `tema` ATIVOS, nome
-- por nome, com casamento de 100% nos três níveis. A terceira aba, o
-- `Risk tracking map`, não existe aqui, e é ela que esta migration traz.
--
-- UMA TABELA SÓ, e não duas. O pedido foi "uma tabela para cada aba", escrito
-- antes de sabermos que a aba de taxonomia já estava carregada: criá-la agora
-- seria uma SEGUNDA VERDADE sobre pilar, tema e LSO, que envelheceria separada
-- das três tabelas que a API já consome. A única coluna daquela aba que faltava
-- aqui é o `Risk tracking` — o vínculo do subtema com o risco —, e ela entra como
-- `tema.risco_id`, onde pertence.
--
-- `Issue RepRisk correspondente` NÃO É GUARDADA: nas 100 linhas com risco ela é
-- sempre, sem uma exceção, o `Risk Cluster` do próprio risco. Guardá-la seria
-- dependência transitiva (3NF) e abriria a porta para as duas divergirem.
--
-- O CLUSTER É COLUNA, e não tabela própria. Ele não tem atributo nenhum além do
-- nome, nada o referencia, e as opções do formulário saem de um `distinct`. Uma
-- tabela de oito nomes cobraria um `join` em toda leitura para não responder
-- pergunta nenhuma. Se um dia o cluster ganhar dono, cor ou ordem, aí vira
-- tabela — e o `check` abaixo é o que impede que, até lá, entre um nome novo por
-- erro de digitação.
--
-- POR QUE `risco` É A CHAVE NATURAL: no mapa os 32 riscos são distintos e cada um
-- determina o seu cluster e a sua severidade, sem uma única ambiguidade. Então
-- escolher o risco preenche os outros dois campos, e é isso que a tela faz.

begin;

create table if not exists risco_reputacional (
  id          smallint generated always as identity primary key,
  -- O AGRUPAMENTO do RepRisk: 8 valores, 2 a 7 riscos cada.
  cluster     text     not null,
  -- O NOME DO RISCO. Único: é por ele que o subtema se liga, e é a chave natural
  -- da aba.
  nome        text     not null unique,
  severidade  text     not null,
  ativo       boolean  not null default true,
  criado_em   timestamptz not null default now(),

  -- Domínio fechado, porque severidade é escala e não texto livre: um
  -- "Médio" digitado ao lado de "Moderado" partiria qualquer contagem em duas.
  constraint risco_severidade_valida
    check (severidade in ('moderado', 'alto', 'critico')),
  -- Os 8 clusters da aba. Um `check` em vez de tabela: ver o cabeçalho.
  constraint risco_cluster_valido
    check (cluster in (
      'Riscos ESG',
      'Riscos Geopolíticos e Estratégicos',
      'Riscos Operacionais',
      'Riscos com Clientes',
      'Riscos com Finanças e Contabilidade',
      'Riscos com Stakeholders e novos negócios',
      'Riscos de Tecnologia',
      'Riscos em Investimentos de Capital'
    ))
);

comment on table risco_reputacional is
  'A aba `Risk tracking map` da planilha de taxonomia (set/2026): 32 riscos, '
  'cada um num cluster e com uma severidade. O subtema se liga a um risco por '
  '`tema.risco_id`. Ver 0060.';

-- SÓ PARA O FORMULÁRIO: as opções de "Risk" aparecem agrupadas por cluster, e
-- escolher o cluster filtra a lista. É a mesma forma do Pilar -> Tema estratégico
-- que a tela já tem.
create index if not exists risco_por_cluster on risco_reputacional (cluster, nome);

-- OS 32 RISCOS DA ABA, na ordem em que ela os traz.
insert into risco_reputacional (cluster, nome, severidade) values
  ('Riscos Geopolíticos e Estratégicos', 'Instabilidade Política / Econômica', 'moderado'),
  ('Riscos Geopolíticos e Estratégicos', 'Relações Institucionais e Governamentais', 'moderado'),
  ('Riscos Geopolíticos e Estratégicos', 'Gestão de Portfólio e Estrutura de Capital', 'alto'),
  ('Riscos Geopolíticos e Estratégicos', 'Liquidez, Gestão da Dívida e Quebra de Covenants de financiamentos', 'alto'),
  ('Riscos Geopolíticos e Estratégicos', 'Legal e Regulatório', 'moderado'),
  ('Riscos Geopolíticos e Estratégicos', 'Práticas Ilegais ou Antiéticas', 'alto'),
  ('Riscos Geopolíticos e Estratégicos', 'Gestão do Capital Humano', 'moderado'),
  ('Riscos em Investimentos de Capital', 'Gestão de Contratos e Terceiros', 'moderado'),
  ('Riscos em Investimentos de Capital', 'Adoção e Efetividade de Novas Tecnologias', 'alto'),
  ('Riscos em Investimentos de Capital', 'Gestão Ambiental em Projetos e Obras', 'alto'),
  ('Riscos Operacionais', 'Gestão de Insumos', 'moderado'),
  ('Riscos Operacionais', 'Gestão de Licenças', 'alto'),
  ('Riscos Operacionais', 'Saúde e Segurança', 'alto'),
  ('Riscos Operacionais', 'Meio ambiente operacional', 'alto'),
  ('Riscos Operacionais', 'Integridade e Confiabilidade dos Ativos', 'alto'),
  ('Riscos Operacionais', 'Entrega de água e tratamento de esgoto', 'critico'),
  ('Riscos Operacionais', 'Tratamento de resíduos sólidos urbanos (RSU)', 'alto'),
  ('Riscos de Tecnologia', 'Cybersecurity e Continuidade Operacional', 'critico'),
  ('Riscos de Tecnologia', 'Proteção de Dados e informações', 'alto'),
  ('Riscos de Tecnologia', 'Proteção de Dados – LGPD', 'moderado'),
  ('Riscos ESG', 'Externalidades e Mudanças Climáticas', 'critico'),
  ('Riscos ESG', 'Gestão ESG e Sustentabilidade', 'alto'),
  ('Riscos ESG', 'Relações com as Comunidades', 'alto'),
  ('Riscos com Clientes', 'Regularidade, Atendimento e Satisfação', 'alto'),
  ('Riscos com Clientes', 'Gestão de Crédito e Inadimplência', 'moderado'),
  ('Riscos com Finanças e Contabilidade', 'Integridade das Demonstrações Financeiras', 'moderado'),
  ('Riscos com Finanças e Contabilidade', 'Cobertura de Seguros', 'moderado'),
  ('Riscos com Finanças e Contabilidade', 'Contingências e Provisões', 'moderado'),
  ('Riscos com Stakeholders e novos negócios', 'Integridade das Informações ao Mercado', 'moderado'),
  ('Riscos com Stakeholders e novos negócios', 'Gestão de Crises', 'critico'),
  ('Riscos com Stakeholders e novos negócios', 'Assunção de novos negócios', 'moderado'),
  ('Riscos com Stakeholders e novos negócios', 'Novas Tendências e Futuro', 'moderado')
on conflict (nome) do nothing;

-- O VÍNCULO DO SUBTEMA COM O RISCO.
--
-- NULO é resposta, e não falta de dado: 4 dos 104 subtemas vêm da planilha com
-- "Sem enquadramento" — a Aegea olhou e decidiu que não há risco a rastrear
-- ali. `on delete restrict` porque apagar um risco usado por subtema deixaria
-- o enquadramento sem sentido; aposentar um risco é `ativo = false`.
alter table tema
  add column if not exists risco_id smallint references risco_reputacional (id)
    on delete restrict;

comment on column tema.risco_id is
  'O risco do `Risk tracking map` que enquadra este subtema. Nulo = a planilha '
  'diz "Sem enquadramento", ou o subtema não vem dela. NÃO confundir com '
  '`e_risco`, que é a binária Risco/Outros da taxonomia v3 — são dois eixos, de '
  'fontes diferentes, e divergem em 21 dos 104. Ver 0060.';

create index if not exists tema_por_risco on tema (risco_id)
  where risco_id is not null;

-- O ENQUADRAMENTO DOS 100 SUBTEMAS QUE A PLANILHA ENQUADRA.
--
-- Casado por NOME, que é o que a `0058` também fez — e aqui o casamento foi
-- conferido antes: os 104 subtemas da aba são os 104 `tema` ativos, sem sobra de
-- nenhum lado. `where tema.nome = ...` sem `ativo` de propósito: se um deles for
-- desativado depois, o enquadramento continua valendo para o histórico.
--
-- `e_risco` NÃO É TOCADO. Ele vem da taxonomia v3 (Peers/Comms) e diverge deste
-- eixo em 21 dos 104 — 18 que a planilha enquadra e ele diz que não é risco, 3 o
-- contrário. Sobrescrevê-lo aqui apagaria a classificação v3 para alinhar duas
-- coisas que nunca foram a mesma. A reconciliação é decisão do dono do produto, e
-- está anotada no README.
update tema set risco_id = r.id
  from (values
  ('Acionistas', 'Gestão de Portfólio e Estrutura de Capital'),
  ('Cumprimento contratual', 'Legal e Regulatório'),
  ('Revisão e renovação de contratos', 'Legal e Regulatório'),
  ('Reequilíbrio econômico-financeiro', 'Legal e Regulatório'),
  ('Segurança jurídica', 'Legal e Regulatório'),
  ('Fiscalização regulatória', 'Legal e Regulatório'),
  ('Multa e processos', 'Contingências e Provisões'),
  ('Ética e conduta', 'Práticas Ilegais ou Antiéticas'),
  ('Investigações e Acordo', 'Práticas Ilegais ou Antiéticas'),
  ('Controles internos / Prevenção à fraude e corrupção', 'Práticas Ilegais ou Antiéticas'),
  ('Demonstrações de resultados e auditoria', 'Integridade das Demonstrações Financeiras'),
  ('Políticas públicas e setoriais', 'Instabilidade Política / Econômica'),
  ('Patrocínios institucionais', 'Relações Institucionais e Governamentais'),
  ('Debate público versus privado', 'Instabilidade Política / Econômica'),
  ('Judicialização e CPIs', 'Legal e Regulatório'),
  ('Marco Legal do Saneamento', 'Instabilidade Política / Econômica'),
  ('Agências reguladoras', 'Relações Institucionais e Governamentais'),
  ('Agenda Associações (Políticas setoriais)', 'Relações Institucionais e Governamentais'),
  ('Frequência, Continuidade', 'Entrega de água e tratamento de esgoto'),
  ('Perdas, fraudes, furtos e ligações irregulares', 'Integridade e Confiabilidade dos Ativos'),
  ('Rompimento de adutora', 'Integridade e Confiabilidade dos Ativos'),
  ('Plano de contingência e redundância', 'Gestão de Crises'),
  ('Gestão da qualidade da água', 'Entrega de água e tratamento de esgoto'),
  ('Monitoramento e controle de qualidade da água', 'Entrega de água e tratamento de esgoto'),
  ('Potabilidade', 'Entrega de água e tratamento de esgoto'),
  ('Rede e Coleta de esgoto', 'Entrega de água e tratamento de esgoto'),
  ('Tratamento de esgoto', 'Entrega de água e tratamento de esgoto'),
  ('Lançamento irregular e extravasamento', 'Meio ambiente operacional'),
  ('Balneabilidade', 'Meio ambiente operacional'),
  ('Odor e incômodo', 'Relações com as Comunidades'),
  ('Custos e eficiência', 'Gestão de Contratos e Terceiros'),
  ('Acidentes e danos a terceiros', 'Saúde e Segurança'),
  ('Expansão da rede', 'Gestão de Contratos e Terceiros'),
  ('Pavimentação e recomposição', 'Gestão de Contratos e Terceiros'),
  ('Manutenção, interdições e transtornos urbanos', 'Relações com as Comunidades'),
  ('Canais de atendimento', 'Regularidade, Atendimento e Satisfação'),
  ('Atendimento ao cliente', 'Regularidade, Atendimento e Satisfação'),
  ('Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)', 'Regularidade, Atendimento e Satisfação'),
  ('Medição e leitura', 'Regularidade, Atendimento e Satisfação'),
  ('Conta errada, Tarifa abusiva', 'Regularidade, Atendimento e Satisfação'),
  ('Inadimplência, Corte e religação', 'Gestão de Crédito e Inadimplência'),
  ('Segurança, ameaças e invasões', 'Integridade e Confiabilidade dos Ativos'),
  ('Reajuste/ Revisão tarifária', 'Legal e Regulatório'),
  ('Estrutura e composição tarifária', 'Legal e Regulatório'),
  ('Resultados financeiros e operacionais', 'Integridade das Informações ao Mercado'),
  ('Projeções e guidance', 'Integridade das Informações ao Mercado'),
  ('Endividamento e alavancagem', 'Liquidez, Gestão da Dívida e Quebra de Covenants de financiamentos'),
  ('Aportes dos acionistas', 'Gestão de Portfólio e Estrutura de Capital'),
  ('Dividendos e distribuição de capital', 'Gestão de Portfólio e Estrutura de Capital'),
  ('Emissão de dívida / Debêntures e bonds', 'Liquidez, Gestão da Dívida e Quebra de Covenants de financiamentos'),
  ('IPO e acesso ao mercado de ações', 'Gestão de Portfólio e Estrutura de Capital'),
  ('Percepção de risco de crédito / Rating corporativo', 'Liquidez, Gestão da Dívida e Quebra de Covenants de financiamentos'),
  ('Covenants', 'Liquidez, Gestão da Dívida e Quebra de Covenants de financiamentos'),
  ('Novos Negócios e Leilões', 'Assunção de novos negócios'),
  ('M&A e parcerias', 'Assunção de novos negócios'),
  ('Venda de ativo', 'Gestão de Portfólio e Estrutura de Capital'),
  ('Entrada em novos mercados', 'Assunção de novos negócios'),
  ('Coleta de resíduos / Tratamento e Destinação', 'Tratamento de resíduos sólidos urbanos (RSU)'),
  ('Taxa de lixo', 'Tratamento de resíduos sólidos urbanos (RSU)'),
  ('Reúso de água', 'Novas Tendências e Futuro'),
  ('Programas sociais e comunidade', 'Relações com as Comunidades'),
  ('Tarifa social', 'Relações com as Comunidades'),
  ('Cadastro e elegibilidade', 'Regularidade, Atendimento e Satisfação'),
  ('Renegociação e apoio ao cliente', 'Gestão de Crédito e Inadimplência'),
  ('Prêmios, Projetos e incentivos à comunidade', 'Relações com as Comunidades'),
  ('Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água', 'Relações com as Comunidades'),
  ('Contratação', 'Gestão do Capital Humano'),
  ('Atração e desenvolvimento', 'Gestão do Capital Humano'),
  ('Equidade, Diversidade e inclusão', 'Gestão do Capital Humano'),
  ('Segurança, condições e relações de trabalho', 'Saúde e Segurança'),
  ('Cultura organizacional', 'Gestão do Capital Humano'),
  ('Segurança dos trabalhadores / Acidentes de trabalho', 'Saúde e Segurança'),
  ('Relações sindicais', 'Gestão do Capital Humano'),
  ('Relacionamento com terceiros', 'Gestão de Contratos e Terceiros'),
  ('Proteção de mananciais / Recuperação ambiental', 'Meio ambiente operacional'),
  ('Oceanos', 'Meio ambiente operacional'),
  ('Resiliência hídrica e novas fontes', 'Externalidades e Mudanças Climáticas'),
  ('Eficiência energética / Energia renovável / Autoprodução e geração distribuída', 'Gestão de Insumos'),
  ('Emissão gases efeito estufa', 'Gestão ESG e Sustentabilidade'),
  ('Eventos Climáticos', 'Externalidades e Mudanças Climáticas'),
  ('Adaptação e resiliência', 'Externalidades e Mudanças Climáticas'),
  ('Biodiversidade', 'Gestão Ambiental em Projetos e Obras'),
  ('Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações', 'Gestão de Licenças'),
  ('Aproveitamento de subprodutos', 'Novas Tendências e Futuro'),
  ('Gestão de lodo', 'Meio ambiente operacional'),
  ('Redução e valorização de resíduos', 'Gestão ESG e Sustentabilidade'),
  ('Monitoramento em tempo real', 'Adoção e Efetividade de Novas Tecnologias'),
  ('Gestão de ativos', 'Integridade e Confiabilidade dos Ativos'),
  ('Sensoriamento e telemetria', 'Adoção e Efetividade de Novas Tecnologias'),
  ('Automação de processos', 'Adoção e Efetividade de Novas Tecnologias'),
  ('Inteligência artificial / Eficiência baseada em dados / Análise preditiva', 'Adoção e Efetividade de Novas Tecnologias'),
  ('Canais digitais / Autoatendimento', 'Regularidade, Atendimento e Satisfação'),
  ('Medição e fatura digital', 'Adoção e Efetividade de Novas Tecnologias'),
  ('Novas tecnologias', 'Novas Tendências e Futuro'),
  ('Parcerias com universidades e startups', 'Novas Tendências e Futuro'),
  ('Proteção de dados / Privacidade / Cybersegurança / Continuidade', 'Cybersecurity e Continuidade Operacional'),
  ('Universalização e metas de cobertura', 'Legal e Regulatório'),
  ('Volume de investimentos', 'Gestão de Portfólio e Estrutura de Capital'),
  ('Geração de empregos / Contratação local / Capacitação profissional', 'Relações com as Comunidades'),
  ('Desenvolvimento de fornecedores / Fornecedores locais / Compras responsáveis', 'Gestão de Contratos e Terceiros')
  ) as v(subtema, risco)
  join risco_reputacional r on r.nome = v.risco
 where tema.nome = v.subtema;

-- A GUARDA DO CASAMENTO POR NOME.
--
-- Achado de revisão: o `update` acima não falha se casar MENOS do que deveria.
-- Aqui o casamento foi conferido antes de escrever (os 104 subtemas da aba são
-- os 104 `tema` ativos, sem sobra), mas num banco onde alguém renomeou um tema
-- antes desta migration ele aplicaria em silêncio com buraco — e o buraco só
-- apareceria meses depois, como um assunto sem enquadramento que deveria ter um.
--
-- 100 é o número da planilha: 104 subtemas menos os 4 com "Sem enquadramento".
-- Se este número mudar, é porque a planilha mudou, e aí a migration nova é que
-- deve dizer o novo número — não esta.
do $$
declare
  enquadrados int;
begin
  select count(*) into enquadrados from tema where risco_id is not null;
  if enquadrados <> 100 then
    raise exception
      'A 0060 enquadrou % subtemas, e a planilha enquadra 100. O casamento e por '
      'NOME: confira se algum tema foi renomeado antes desta migration. Nenhuma '
      'linha foi gravada.', enquadrados;
  end if;
end $$;

commit;
