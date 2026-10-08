-- 0061 — os 100 enquadramentos que a planilha define, na matriz da 0059
--
-- O QUE FALTAVA. A `0059` criou `risk_cluster`, `risco` e `tema_risco` e
-- carregou os 8 clusters e os 32 riscos da matriz — mas inseriu UM vínculo de
-- exemplo ("Resultados financeiros e operacionais" → R27). Os enquadramentos
-- que a planilha de taxonomia define ficaram de fora, então a tela abre com a
-- matriz toda disponível e nenhum assunto classificado.
--
-- DE ONDE VEM: `20260917_Aegea_Taxonomia_Publicos_v2.xlsx`, aba
-- `Taxonomia de temas`, coluna `Risk tracking` — um risco por subtema. Dos 104
-- subtemas, 100 trazem um risco e 4 trazem "Sem enquadramento".
--
-- CASADO POR `codigo`, e não pelo nome: o `R01..R32` é a chave estável da
-- matriz, e renomear um risco não deve desfazer enquadramento. Conferido antes
-- de escrever: os 32 nomes da aba casam 1:1 com os 32 da `0059`, sem sobra de
-- nenhum lado.
--
-- O SUBTEMA casa por nome, que é o que a `0058` também fez — e ali o casamento
-- foi medido: os 104 subtemas da aba são os 104 `tema` ativos, nome por nome.
-- Sem `and ativo` de propósito: se um deles for desativado depois, o
-- enquadramento continua valendo para o histórico.
--
-- `on conflict do nothing` porque `tema_risco` tem chave primária composta.
--
-- O VÍNCULO DE EXEMPLO DA 0059 NÃO ESTÁ ENTRE ESTES 100, e isto é achado a
-- reportar em vez de corrigir aqui: ela liga "Resultados financeiros e
-- operacionais" ao R27 "Cobertura de Seguros", e a planilha diz que o
-- `Risk tracking` desse subtema é "Integridade das Informações ao Mercado".
-- Parece linha de teste de fumaça, não dado.
--
-- NÃO O APAGO: é dado de outro PR já mesclado, e se a ligação foi deliberada —
-- alguém na Aegea decidindo que resultado ao mercado toca cobertura de seguros
-- — apagá-la seria eu desfazendo decisão que não é minha. Como o schema é
-- muitos-para-muitos, os dois vínculos coexistem sem violar nada. Fica para o
-- dono do produto dizer se sai.
--
-- NULO É RESPOSTA para os 4 de fora: a Aegea olhou e decidiu que não há risco a
-- rastrear ali. Eles ficam sem linha em `tema_risco`, e é isso que a ausência
-- significa.

begin;

insert into tema_risco (tema_id, risco_id)
select t.id, r.id
  from (values
  ('Acionistas', 'R03'),
  ('Cumprimento contratual', 'R05'),
  ('Revisão e renovação de contratos', 'R05'),
  ('Reequilíbrio econômico-financeiro', 'R05'),
  ('Segurança jurídica', 'R05'),
  ('Fiscalização regulatória', 'R05'),
  ('Multa e processos', 'R28'),
  ('Ética e conduta', 'R06'),
  ('Investigações e Acordo', 'R06'),
  ('Controles internos / Prevenção à fraude e corrupção', 'R06'),
  ('Demonstrações de resultados e auditoria', 'R26'),
  ('Políticas públicas e setoriais', 'R01'),
  ('Patrocínios institucionais', 'R02'),
  ('Debate público versus privado', 'R01'),
  ('Judicialização e CPIs', 'R05'),
  ('Marco Legal do Saneamento', 'R01'),
  ('Agências reguladoras', 'R02'),
  ('Agenda Associações (Políticas setoriais)', 'R02'),
  ('Frequência, Continuidade', 'R16'),
  ('Perdas, fraudes, furtos e ligações irregulares', 'R15'),
  ('Rompimento de adutora', 'R15'),
  ('Plano de contingência e redundância', 'R30'),
  ('Gestão da qualidade da água', 'R16'),
  ('Monitoramento e controle de qualidade da água', 'R16'),
  ('Potabilidade', 'R16'),
  ('Rede e Coleta de esgoto', 'R16'),
  ('Tratamento de esgoto', 'R16'),
  ('Lançamento irregular e extravasamento', 'R14'),
  ('Balneabilidade', 'R14'),
  ('Odor e incômodo', 'R23'),
  ('Custos e eficiência', 'R08'),
  ('Acidentes e danos a terceiros', 'R13'),
  ('Expansão da rede', 'R08'),
  ('Pavimentação e recomposição', 'R08'),
  ('Manutenção, interdições e transtornos urbanos', 'R23'),
  ('Canais de atendimento', 'R24'),
  ('Atendimento ao cliente', 'R24'),
  ('Órgãos de defesa ao cliente (Ouvidoria, Procon, Reclame Aqui)', 'R24'),
  ('Medição e leitura', 'R24'),
  ('Conta errada, Tarifa abusiva', 'R24'),
  ('Inadimplência, Corte e religação', 'R25'),
  ('Segurança, ameaças e invasões', 'R15'),
  ('Reajuste/ Revisão tarifária', 'R05'),
  ('Estrutura e composição tarifária', 'R05'),
  ('Resultados financeiros e operacionais', 'R29'),
  ('Projeções e guidance', 'R29'),
  ('Endividamento e alavancagem', 'R04'),
  ('Aportes dos acionistas', 'R03'),
  ('Dividendos e distribuição de capital', 'R03'),
  ('Emissão de dívida / Debêntures e bonds', 'R04'),
  ('IPO e acesso ao mercado de ações', 'R03'),
  ('Percepção de risco de crédito / Rating corporativo', 'R04'),
  ('Covenants', 'R04'),
  ('Novos Negócios e Leilões', 'R31'),
  ('M&A e parcerias', 'R31'),
  ('Venda de ativo', 'R03'),
  ('Entrada em novos mercados', 'R31'),
  ('Coleta de resíduos / Tratamento e Destinação', 'R17'),
  ('Taxa de lixo', 'R17'),
  ('Reúso de água', 'R32'),
  ('Programas sociais e comunidade', 'R23'),
  ('Tarifa social', 'R23'),
  ('Cadastro e elegibilidade', 'R24'),
  ('Renegociação e apoio ao cliente', 'R25'),
  ('Prêmios, Projetos e incentivos à comunidade', 'R23'),
  ('Educação ambiental / Engajamento em saneamento e saúde / Uso consciente da água', 'R23'),
  ('Contratação', 'R07'),
  ('Atração e desenvolvimento', 'R07'),
  ('Equidade, Diversidade e inclusão', 'R07'),
  ('Segurança, condições e relações de trabalho', 'R13'),
  ('Cultura organizacional', 'R07'),
  ('Segurança dos trabalhadores / Acidentes de trabalho', 'R13'),
  ('Relações sindicais', 'R07'),
  ('Relacionamento com terceiros', 'R08'),
  ('Proteção de mananciais / Recuperação ambiental', 'R14'),
  ('Oceanos', 'R14'),
  ('Resiliência hídrica e novas fontes', 'R21'),
  ('Eficiência energética / Energia renovável / Autoprodução e geração distribuída', 'R11'),
  ('Emissão gases efeito estufa', 'R22'),
  ('Eventos Climáticos', 'R21'),
  ('Adaptação e resiliência', 'R21'),
  ('Biodiversidade', 'R10'),
  ('Licenças e autorizações / Condicionantes ambientais / Fiscalização e autuações', 'R12'),
  ('Aproveitamento de subprodutos', 'R32'),
  ('Gestão de lodo', 'R14'),
  ('Redução e valorização de resíduos', 'R22'),
  ('Monitoramento em tempo real', 'R09'),
  ('Gestão de ativos', 'R15'),
  ('Sensoriamento e telemetria', 'R09'),
  ('Automação de processos', 'R09'),
  ('Inteligência artificial / Eficiência baseada em dados / Análise preditiva', 'R09'),
  ('Canais digitais / Autoatendimento', 'R24'),
  ('Medição e fatura digital', 'R09'),
  ('Novas tecnologias', 'R32'),
  ('Parcerias com universidades e startups', 'R32'),
  ('Proteção de dados / Privacidade / Cybersegurança / Continuidade', 'R18'),
  ('Universalização e metas de cobertura', 'R05'),
  ('Volume de investimentos', 'R03'),
  ('Geração de empregos / Contratação local / Capacitação profissional', 'R23'),
  ('Desenvolvimento de fornecedores / Fornecedores locais / Compras responsáveis', 'R08')
  ) as v(subtema, codigo)
  join tema t on t.nome = v.subtema
  join risco r on r.codigo = v.codigo
on conflict (tema_id, risco_id) do nothing;

-- A GUARDA DO CASAMENTO POR NOME.
--
-- O `insert` acima não falha se casar menos do que deveria: num banco onde
-- alguém renomeou um tema antes desta migration, ele aplicaria em silêncio com
-- buraco — e o buraco só apareceria meses depois, como um assunto sem
-- enquadramento que deveria ter um.
--
-- 101 = os 100 da planilha (104 subtemas menos os 4 "Sem enquadramento") MAIS o
-- vínculo de exemplo da `0059`, que não está entre eles. Se o total mudar, é
-- porque a planilha mudou, ou porque aquele exemplo saiu — e aí é a migration
-- nova que diz o novo número.
do $$
declare
  enquadrados int;
begin
  select count(*) into enquadrados from tema_risco;
  if enquadrados <> 101 then
    raise exception
      'A 0061 deixou % vinculos em tema_risco; o esperado e 101 (os 100 da '
      'planilha mais o vinculo de exemplo da 0059). O casamento do subtema e '
      'por NOME: confira se algum tema foi renomeado antes desta migration. '
      'Nenhuma linha foi gravada.', enquadrados;
  end if;
end $$;

commit;
