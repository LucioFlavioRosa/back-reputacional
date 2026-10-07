-- 0058 — a taxonomia de temas v4 (Peers/Comms + RI), fechada e em uso
--
-- A v1.3 (0053) era rascunho: 4 blocos, 20 macro temas, 38 temas, tudo
-- carregado com `ativo = false` esperando a reunião de definição da taxonomia
-- terminar. Terminou. Esta migration troca a estrutura de verdade:
-- 7 pilares, 41 temas estratégicos, 104 subtemas — e os subtemas SÃO o que
-- a aplicação já chama de `tema` (mesma tabela, mesmo uso em interações).
--
-- A planilha de origem evoluiu três vezes (v2 → v3 → v4) até a Aegea decidir
-- abandonar a classificação externa do RepRisk (severidade, issue, contagem
-- de incidentes) em favor da própria matriz de risco corporativo. O que
-- sobrevive de tudo isso, nesta migration, é só o essencial já fechado:
-- hierarquia (pilar > tema estratégico > subtema), LSO (Legitimidade/
-- Credibilidade/Confiança) e uma classificação binária de risco — que é
-- NOVA (não existia em nenhuma migration anterior) e vem da classificação
-- Risco/Outros da v3, subtema por subtema, sem agregação.
--
-- `e_risco` É CADASTRO, NÃO DERIVAÇÃO — mesmo molde de `camada_lso`: um
-- booleano que alguém decidiu, não algo que o código calcula. Aceita nulo
-- porque os temas antigos (que ficam só desativados, nunca apagados) não
-- têm correspondência nessa classificação — não é "não é risco", é "não se
-- aplica mais perguntar".
--
-- NOVE NOMES NOVOS COLIDEM COM NOMES ANTIGOS (ex.: "Taxa de lixo", "Tarifa
-- social", "Gestão da qualidade da água" — a v1.3 já usava parte do mesmo
-- vocabulário). `nome` é UNIQUE em `tema`, então não dá para desativar o
-- antigo e inserir um novo com o mesmo nome. A carga usa
-- `on conflict (nome) do update`: quem colide é RECONCILIADO no lugar
-- (preserva `id` e todo o histórico de `interacao_tema`), exatamente como a
-- 0053 fez à mão para "Inclusão sanitária" — aqui o próprio `upsert` resolve
-- os nove de uma vez, sem precisar listar qual é qual.
--
-- DESATIVAR PRIMEIRO, CARREGAR DEPOIS: todo `tema` ativo vira inativo e
-- perde o vínculo com a hierarquia antiga ANTES de `bloco_tema`/`macro_tema`
-- serem recriados — sem isso, apagar as 20 macro temas antigas esbarraria
-- na FK de quem ainda apontava para elas. A carga dos 104 subtemas, logo
-- depois, reativa e reconcilia quem tem nome igual; o resto do vocabulário
-- antigo (45 temas, incluindo os 17 "de fundação" como Tarifa/IPO/Reputação)
-- fica desativado — mesmo destino que a 0053 já dava a 16 dos 17, só que
-- agora para todos.

begin;

alter table tema add column if not exists e_risco boolean;
comment on column tema.e_risco is
  'Se este tema representa exposição de risco, na classificação binária '
  'Risco/Outros da taxonomia v3 (Peers/Comms). Cadastro, não derivação — '
  'nulo em quem não foi reconciliado com a taxonomia v4. Ver 0058.';

-- -- desativa tudo e solta o vínculo com a hierarquia antiga (que vai ser
-- -- apagada e recriada logo abaixo) — SEM FILTRO POR `ativo`: os 37 temas-
-- -- rascunho da 0053 já nasceram com `ativo = false`, mas têm
-- -- `macro_tema_id` apontando para lá mesmo assim. Um `where ativo = true`
-- -- os deixaria de fora, e o `delete from macro_tema` logo abaixo quebraria
-- -- com FK pendurada — só não aparece num banco onde tudo já estava ativo
-- -- por algum motivo alheio a esta migration.

update tema set ativo = false, macro_tema_id = null;

-- -- a hierarquia antiga (v1.3, 0053) sai; nada mais referencia estas linhas
-- -- depois do update acima ---------------------------------------------------

delete from macro_tema;
delete from bloco_tema;

-- -- os 7 pilares --------------------------------------------------------------

insert into bloco_tema (codigo, nome, ordem) values
  ('governanca',                            'Governança',                            1),
  ('eficiencia_operacional_e_qualidade',    'Eficiência Operacional e Qualidade',    2),
  ('crescimento_e_solidez_financeira',      'Crescimento e Solidez Financeira',      3),
  ('responsabilidade_social',               'Responsabilidade Social',               4),
  ('responsabilidade_ambiental',            'Responsabilidade Ambiental',            5),
  ('inovacao_e_tecnologia',                 'Inovação e Tecnologia',                 6),
  ('prosperidade_compartilhada',            'Prosperidade Compartilhada',            7);

-- -- os 41 temas estratégicos ---------------------------------------------------

insert into macro_tema (bloco_tema_id, codigo, nome, ordem) values
  ((select id from bloco_tema where codigo = 'governanca'), 'governanca_corporativa', 'Governança corporativa', 1),
  ((select id from bloco_tema where codigo = 'governanca'), 'contratos_e_regulacao', 'Contratos e Regulação', 2),
  ((select id from bloco_tema where codigo = 'governanca'), 'integridade', 'Integridade', 3),
  ((select id from bloco_tema where codigo = 'governanca'), 'modelo_de_negocio', 'Modelo de negócio', 4),
  ((select id from bloco_tema where codigo = 'governanca'), 'politico_institucional', 'Político-institucional', 5),

  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'abastecimento_de_agua', 'Abastecimento de água', 1),
  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'qualidade_da_agua', 'Qualidade da água', 2),
  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'esgoto', 'Esgoto', 3),
  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'obras_e_intervencoes', 'Obras e intervenções', 4),
  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'atendimento_ao_cliente', 'Atendimento ao cliente', 5),
  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'faturamento_e_cobranca', 'Faturamento e cobrança', 6),
  ((select id from bloco_tema where codigo = 'eficiencia_operacional_e_qualidade'), 'seguranca_operacional_e_patrimonial', 'Segurança operacional e patrimonial', 7),

  ((select id from bloco_tema where codigo = 'crescimento_e_solidez_financeira'), 'tarifa', 'Tarifa', 1),
  ((select id from bloco_tema where codigo = 'crescimento_e_solidez_financeira'), 'desempenho_financeiro', 'Desempenho financeiro', 2),
  ((select id from bloco_tema where codigo = 'crescimento_e_solidez_financeira'), 'estrutura_de_capital', 'Estrutura de capital', 3),
  ((select id from bloco_tema where codigo = 'crescimento_e_solidez_financeira'), 'credito_e_rating', 'Crédito e rating', 4),
  ((select id from bloco_tema where codigo = 'crescimento_e_solidez_financeira'), 'crescimento_e_portfolio', 'Crescimento e portfólio', 5),
  ((select id from bloco_tema where codigo = 'crescimento_e_solidez_financeira'), 'novos_negocios', 'Novos negócios', 6),

  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'acoes_sociais', 'Ações Sociais', 1),
  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'inclusao_sanitaria_e_acessibilidade_economica', 'Inclusão sanitária / Acessibilidade econômica', 2),
  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'relacionamento_comunitario', 'Relacionamento comunitário', 3),
  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'educacao_e_conscientizacao', 'Educação e conscientização', 4),
  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'pessoas', 'Pessoas', 5),
  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'saude_e_seguranca', 'Saúde e segurança', 6),
  ((select id from bloco_tema where codigo = 'responsabilidade_social'), 'relacoes_de_trabalho', 'Relações de trabalho', 7),

  ((select id from bloco_tema where codigo = 'responsabilidade_ambiental'), 'protecao_ambiental', 'Proteção ambiental', 1),
  ((select id from bloco_tema where codigo = 'responsabilidade_ambiental'), 'meio_ambiente_e_clima', 'Meio ambiente e clima', 2),
  ((select id from bloco_tema where codigo = 'responsabilidade_ambiental'), 'energia', 'Energia', 3),
  ((select id from bloco_tema where codigo = 'responsabilidade_ambiental'), 'mudancas_climaticas', 'Mudanças climáticas', 4),
  ((select id from bloco_tema where codigo = 'responsabilidade_ambiental'), 'licenciamento_ambiental', 'Licenciamento ambiental', 5),
  ((select id from bloco_tema where codigo = 'responsabilidade_ambiental'), 'economia_circular_e_reuso', 'Economia circular e reúso', 6),

  ((select id from bloco_tema where codigo = 'inovacao_e_tecnologia'), 'tecnologia_operacao', 'Tecnologia operação', 1),
  ((select id from bloco_tema where codigo = 'inovacao_e_tecnologia'), 'automacao_e_inteligencia_artificial', 'Automação e inteligência artificial', 2),
  ((select id from bloco_tema where codigo = 'inovacao_e_tecnologia'), 'experiencia_digital_do_cliente', 'Experiência digital do cliente', 3),
  ((select id from bloco_tema where codigo = 'inovacao_e_tecnologia'), 'pesquisa_e_desenvolvimento', 'Pesquisa e desenvolvimento', 4),
  ((select id from bloco_tema where codigo = 'inovacao_e_tecnologia'), 'seguranca_da_informacao', 'Segurança da informação', 5),

  ((select id from bloco_tema where codigo = 'prosperidade_compartilhada'), 'universalizacao', 'Universalização', 1),
  ((select id from bloco_tema where codigo = 'prosperidade_compartilhada'), 'investimento_em_infraestrutura', 'Investimento em infraestrutura', 2),
  ((select id from bloco_tema where codigo = 'prosperidade_compartilhada'), 'legado_e_impacto', 'Legado e impacto', 3),
  ((select id from bloco_tema where codigo = 'prosperidade_compartilhada'), 'emprego_e_renda', 'Emprego e renda', 4),
  ((select id from bloco_tema where codigo = 'prosperidade_compartilhada'), 'cadeia_de_valor', 'Cadeia de valor', 5);

-- -- os 104 subtemas (nossa tabela `tema`) --------------------------------------
--
-- `on conflict (nome) do update`: os nove nomes que já existiam (ex. "Taxa de
-- lixo") são reconciliados no lugar — reativados, com a hierarquia e o risco
-- novos — em vez de duplicados. Os outros 95 são inserção simples.

insert into tema (nome, nivel, macro_tema_id, camada_lso, e_risco, ativo) values
  ('Estrutura de governança / Conselho e comitês', 'estrategico', (select id from macro_tema where codigo = 'governanca_corporativa'), 'credibilidade', true, true),
  ('Acionistas', 'estrategico', (select id from macro_tema where codigo = 'governanca_corporativa'), 'credibilidade', true, true),

  ('Cumprimento contratual', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), 'legitimidade', true, true),
  ('Revisão e renovação de contratos', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), 'legitimidade', true, true),
  ('Reequilíbrio econômico-financeiro', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), 'legitimidade', true, true),
  ('Segurança jurídica', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), 'legitimidade', true, true),
  ('Fiscalização regulatória', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), 'legitimidade', true, true),
  ('Multa e processos', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), 'credibilidade', true, true),
  ('Agências reguladoras', 'estrategico', (select id from macro_tema where codigo = 'contratos_e_regulacao'), null, true, true),

  ('Ética e conduta', 'estrategico', (select id from macro_tema where codigo = 'integridade'), 'credibilidade', true, true),
  ('Investigações e Acordo', 'estrategico', (select id from macro_tema where codigo = 'integridade'), 'credibilidade', true, true),
  ('Controles internos / Prevenção à fraude e corrupção', 'estrategico', (select id from macro_tema where codigo = 'integridade'), 'credibilidade', true, true),
  ('Demonstrações de resultados e auditoria', 'estrategico', (select id from macro_tema where codigo = 'integridade'), 'credibilidade', true, true),

  ('Modelo Operacional Aegea', 'estrategico', (select id from macro_tema where codigo = 'modelo_de_negocio'), 'credibilidade', true, true),

  ('Políticas públicas e setoriais', 'estrategico', (select id from macro_tema where codigo = 'politico_institucional'), 'credibilidade', false, true),
  ('Patrocínios institucionais', 'estrategico', (select id from macro_tema where codigo = 'politico_institucional'), 'credibilidade', true, true),
  ('Debate público versus privado', 'estrategico', (select id from macro_tema where codigo = 'politico_institucional'), 'credibilidade', true, true),
  ('Judicialização e CPIs', 'estrategico', (select id from macro_tema where codigo = 'politico_institucional'), 'credibilidade', true, true),
  ('Marco Legal do Saneamento', 'estrategico', (select id from macro_tema where codigo = 'politico_institucional'), null, false, true),
  ('Agenda Associações (Políticas setoriais)', 'estrategico', (select id from macro_tema where codigo = 'politico_institucional'), 'credibilidade', false, true),

  ('Frequência, Continuidade', 'estrategico', (select id from macro_tema where codigo = 'abastecimento_de_agua'), 'legitimidade', true, true),
  ('Perdas, fraudes, furtos e ligações irregulares', 'estrategico', (select id from macro_tema where codigo = 'abastecimento_de_agua'), 'legitimidade', true, true),
  ('Rompimento de adutora', 'estrategico', (select id from macro_tema where codigo = 'abastecimento_de_agua'), 'legitimidade', true, true),
  ('Plano de contingência e redundância', 'estrategico', (select id from macro_tema where codigo = 'abastecimento_de_agua'), 'legitimidade', true, true),

  ('Gestão da qualidade da água', 'estrategico', (select id from macro_tema where codigo = 'qualidade_da_agua'), 'legitimidade', true, true),
  ('Monitoramento e controle de qualidade da água', 'estrategico', (select id from macro_tema where codigo = 'qualidade_da_agua'), 'legitimidade', true, true),
  ('Potabilidade', 'estrategico', (select id from macro_tema where codigo = 'qualidade_da_agua'), 'legitimidade', true, true),

  ('Rede e Coleta de esgoto', 'estrategico', (select id from macro_tema where codigo = 'esgoto'), 'legitimidade', true, true),
  ('Tratamento de esgoto', 'estrategico', (select id from macro_tema where codigo = 'esgoto'), 'legitimidade', true, true),
  ('Lançamento irregular e extravasamento', 'estrategico', (select id from macro_tema where codigo = 'esgoto'), 'legitimidade', true, true),
  ('Balneabilidade', 'estrategico', (select id from macro_tema where codigo = 'esgoto'), 'legitimidade', true, true),
  ('Odor e incômodo', 'estrategico', (select id from macro_tema where codigo = 'esgoto'), null, true, true),

  ('Custos e eficiência', 'estrategico', (select id from macro_tema where codigo = 'obras_e_intervencoes'), 'credibilidade', true, true),
  ('Acidentes e danos a terceiros', 'estrategico', (select id from macro_tema where codigo = 'obras_e_intervencoes'), 'credibilidade', true, true),
  ('Expansão da rede', 'estrategico', (select id from macro_tema where codigo = 'obras_e_intervencoes'), 'credibilidade', true, true),
  ('Pavimentação e recomposição', 'estrategico', (select id from macro_tema where codigo = 'obras_e_intervencoes'), 'credibilidade', true, true),
  ('Manutenção, interdições e transtornos urbanos', 'estrategico', (select id from macro_tema where codigo = 'obras_e_intervencoes'), 'credibilidade', true, true),

  ('Canais de atendimento', 'estrategico', (select id from macro_tema where codigo = 'atendimento_ao_cliente'), 'credibilidade', true, true),
  ('Atendimento ao cliente', 'estrategico', (select id from macro_tema where codigo = 'atendimento_ao_cliente'), 'credibilidade', true, true),
  ('Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)', 'estrategico', (select id from macro_tema where codigo = 'atendimento_ao_cliente'), 'credibilidade', true, true),

  ('Medição e leitura', 'estrategico', (select id from macro_tema where codigo = 'faturamento_e_cobranca'), null, true, true),
  ('Conta errada, Tarifa abusiva', 'estrategico', (select id from macro_tema where codigo = 'faturamento_e_cobranca'), null, true, true),
  ('Inadimplência, Corte e religação', 'estrategico', (select id from macro_tema where codigo = 'faturamento_e_cobranca'), null, true, true),

  ('Segurança, ameaças e invasões', 'estrategico', (select id from macro_tema where codigo = 'seguranca_operacional_e_patrimonial'), null, true, true),

  ('Reajuste/ Revisão tarifária', 'estrategico', (select id from macro_tema where codigo = 'tarifa'), null, true, true),
  ('Estrutura e composição tarifária', 'estrategico', (select id from macro_tema where codigo = 'tarifa'), null, true, true),

  ('Resultados financeiros e operacionais', 'estrategico', (select id from macro_tema where codigo = 'desempenho_financeiro'), null, true, true),
  ('Projeções e guidance', 'estrategico', (select id from macro_tema where codigo = 'desempenho_financeiro'), null, true, true),

  ('Endividamento e alavancagem', 'estrategico', (select id from macro_tema where codigo = 'estrutura_de_capital'), null, true, true),
  ('Aportes dos acionistas', 'estrategico', (select id from macro_tema where codigo = 'estrutura_de_capital'), null, false, true),
  ('Dividendos e distribuição de capital', 'estrategico', (select id from macro_tema where codigo = 'estrutura_de_capital'), null, true, true),
  ('Emissão de dívida / Debêntures e bonds', 'estrategico', (select id from macro_tema where codigo = 'estrutura_de_capital'), null, false, true),
  ('IPO e acesso ao mercado de ações', 'estrategico', (select id from macro_tema where codigo = 'estrutura_de_capital'), null, true, true),

  ('Percepção de risco de crédito / Rating corporativo', 'estrategico', (select id from macro_tema where codigo = 'credito_e_rating'), null, true, true),
  ('Covenants', 'estrategico', (select id from macro_tema where codigo = 'credito_e_rating'), null, true, true),

  ('Novos Negócios e Leilões', 'estrategico', (select id from macro_tema where codigo = 'crescimento_e_portfolio'), null, true, true),
  ('M&A e parcerias', 'estrategico', (select id from macro_tema where codigo = 'crescimento_e_portfolio'), null, true, true),
  ('Venda de ativo', 'estrategico', (select id from macro_tema where codigo = 'crescimento_e_portfolio'), null, true, true),
  ('Entrada em novos mercados', 'estrategico', (select id from macro_tema where codigo = 'crescimento_e_portfolio'), null, true, true),

  ('Coleta de resíduos / Tratamento e Destinação', 'estrategico', (select id from macro_tema where codigo = 'novos_negocios'), null, true, true),
  ('Taxa de lixo', 'estrategico', (select id from macro_tema where codigo = 'novos_negocios'), null, true, true),
  ('Reúso de água', 'estrategico', (select id from macro_tema where codigo = 'novos_negocios'), null, false, true),

  ('Programas sociais e comunidade', 'estrategico', (select id from macro_tema where codigo = 'acoes_sociais'), 'confianca', false, true),

  ('Tarifa social', 'estrategico', (select id from macro_tema where codigo = 'inclusao_sanitaria_e_acessibilidade_economica'), null, true, true),
  ('Cadastro e elegibilidade', 'estrategico', (select id from macro_tema where codigo = 'inclusao_sanitaria_e_acessibilidade_economica'), null, true, true),
  ('Renegociação e apoio ao cliente', 'estrategico', (select id from macro_tema where codigo = 'inclusao_sanitaria_e_acessibilidade_economica'), null, true, true),

  ('Prêmios, Projetos e incentivos à comunidade', 'estrategico', (select id from macro_tema where codigo = 'relacionamento_comunitario'), null, false, true),

  ('Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água', 'estrategico', (select id from macro_tema where codigo = 'educacao_e_conscientizacao'), null, false, true),

  ('Contratação', 'estrategico', (select id from macro_tema where codigo = 'pessoas'), 'confianca', true, true),
  ('Atração e desenvolvimento', 'estrategico', (select id from macro_tema where codigo = 'pessoas'), 'confianca', false, true),
  ('Equidade, Diversidade e inclusão', 'estrategico', (select id from macro_tema where codigo = 'pessoas'), 'confianca', true, true),
  ('Segurança, condições e relações de trabalho', 'estrategico', (select id from macro_tema where codigo = 'pessoas'), 'confianca', true, true),
  ('Cultura organizacional', 'estrategico', (select id from macro_tema where codigo = 'pessoas'), null, true, true),

  ('Segurança dos trabalhadores / Acidentes de trabalho', 'estrategico', (select id from macro_tema where codigo = 'saude_e_seguranca'), null, true, true),

  ('Relações sindicais', 'estrategico', (select id from macro_tema where codigo = 'relacoes_de_trabalho'), null, true, true),
  ('Relacionamento com terceiros', 'estrategico', (select id from macro_tema where codigo = 'relacoes_de_trabalho'), null, true, true),

  ('Proteção de mananciais / Recuperação ambiental', 'estrategico', (select id from macro_tema where codigo = 'protecao_ambiental'), 'confianca', true, true),
  ('Oceanos', 'estrategico', (select id from macro_tema where codigo = 'protecao_ambiental'), 'confianca', true, true),
  ('Biodiversidade', 'estrategico', (select id from macro_tema where codigo = 'protecao_ambiental'), null, true, true),

  ('Resiliência hídrica e novas fontes', 'estrategico', (select id from macro_tema where codigo = 'meio_ambiente_e_clima'), 'confianca', true, true),

  ('Eficiência energética / Energia renovável / Autoprodução e geração distribuída', 'estrategico', (select id from macro_tema where codigo = 'energia'), 'confianca', false, true),

  ('Emissão gases efeito estufa', 'estrategico', (select id from macro_tema where codigo = 'mudancas_climaticas'), 'confianca', true, true),
  ('Eventos Climáticos', 'estrategico', (select id from macro_tema where codigo = 'mudancas_climaticas'), null, true, true),
  ('Adaptação e resiliência', 'estrategico', (select id from macro_tema where codigo = 'mudancas_climaticas'), null, true, true),

  ('Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações', 'estrategico', (select id from macro_tema where codigo = 'licenciamento_ambiental'), null, true, true),

  ('Aproveitamento de subprodutos', 'estrategico', (select id from macro_tema where codigo = 'economia_circular_e_reuso'), null, false, true),
  ('Gestão de lodo', 'estrategico', (select id from macro_tema where codigo = 'economia_circular_e_reuso'), null, true, true),
  ('Redução e valorização de resíduos', 'estrategico', (select id from macro_tema where codigo = 'economia_circular_e_reuso'), null, true, true),

  ('Monitoramento em tempo real', 'estrategico', (select id from macro_tema where codigo = 'tecnologia_operacao'), 'credibilidade', false, true),
  ('Gestão de ativos', 'estrategico', (select id from macro_tema where codigo = 'tecnologia_operacao'), 'credibilidade', false, true),
  ('Sensoriamento e telemetria', 'estrategico', (select id from macro_tema where codigo = 'tecnologia_operacao'), 'credibilidade', false, true),

  ('Automação de processos', 'estrategico', (select id from macro_tema where codigo = 'automacao_e_inteligencia_artificial'), 'credibilidade', true, true),
  ('Inteligência artificial / Eficiência baseada em dados / Análise preditiva', 'estrategico', (select id from macro_tema where codigo = 'automacao_e_inteligencia_artificial'), 'credibilidade', true, true),

  ('Canais digitais / Autoatendimento', 'estrategico', (select id from macro_tema where codigo = 'experiencia_digital_do_cliente'), 'credibilidade', true, true),
  ('Medição e fatura digital', 'estrategico', (select id from macro_tema where codigo = 'experiencia_digital_do_cliente'), 'credibilidade', true, true),

  ('Novas tecnologias', 'estrategico', (select id from macro_tema where codigo = 'pesquisa_e_desenvolvimento'), 'credibilidade', false, true),
  ('Parcerias com universidades e startups', 'estrategico', (select id from macro_tema where codigo = 'pesquisa_e_desenvolvimento'), 'credibilidade', false, true),

  ('Proteção de dados / Privacidade / Cybersegurança / Continuidade', 'estrategico', (select id from macro_tema where codigo = 'seguranca_da_informacao'), 'credibilidade', true, true),

  ('Universalização e metas de cobertura', 'estrategico', (select id from macro_tema where codigo = 'universalizacao'), null, true, true),

  ('Volume de investimentos', 'estrategico', (select id from macro_tema where codigo = 'investimento_em_infraestrutura'), null, true, true),

  ('Benefícios do saneamento (saúde, educação, imóveis, socioeconômico)', 'estrategico', (select id from macro_tema where codigo = 'legado_e_impacto'), null, false, true),

  ('Geração de empregos / Contratação local / Capacitação profissional', 'estrategico', (select id from macro_tema where codigo = 'emprego_e_renda'), null, false, true),

  ('Desenvolvimento de fornecedores / Fornecedores locais / Compras responsáveis', 'estrategico', (select id from macro_tema where codigo = 'cadeia_de_valor'), null, true, true),
  ('Drenagem urbana e águas pluviais', 'estrategico', (select id from macro_tema where codigo = 'cadeia_de_valor'), null, true, true)
on conflict (nome) do update set
  nivel = excluded.nivel,
  macro_tema_id = excluded.macro_tema_id,
  camada_lso = excluded.camada_lso,
  e_risco = excluded.e_risco,
  ativo = true;

commit;
