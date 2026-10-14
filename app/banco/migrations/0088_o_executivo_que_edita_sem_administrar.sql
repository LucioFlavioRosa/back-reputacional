-- =============================================================================
-- 0088 — o Executivo que EDITA os painéis e NÃO administra acessos
--
-- O descritivo de perfis separa "Administrador" de "Executivo": o primeiro tem
-- os painéis mais o gerenciamento de usuários, o segundo tem os painéis e
-- explicitamente NÃO tem o gerenciamento. Cada nível ainda se divide em Editor
-- e Usuário.
--
-- "Executivo · Usuário" já existia: é `plataforma_leitura`. "Executivo ·
-- Editor" não existia, e não havia como montá-lo: o único papel que edita os
-- três portais é `plataforma_edicao`, que tem `administra_acessos` e
-- `administra_dicionarios`. Escolher "Executivo + Editor" na tela acabaria
-- concedendo gerenciamento de usuários a quem o descritivo diz que não deve
-- ter — e concederia EM SILÊNCIO, porque a tela mostraria "Executivo".
--
-- POR QUE O NOME É FEIO
--
-- O nome bom (`plataforma_edicao`) está tomado, e tomá-lo de volta significaria
-- tirar `administra_acessos` de quem o tem HOJE em produção — de quem
-- administra a plataforma. Uma migration que pode deixar a casa sem
-- administrador para melhorar um nome não vale o nome.
--
-- O QUE ESTA MIGRATION NÃO FAZ, E A PRIMEIRA VERSÃO DELA FAZIA
--
-- Ela criava um quarto portal, `papel.acessa_mercado`, para o "Painel de
-- Inteligência de Mercado" do descritivo. ESSE PAINEL JÁ TEM PORTAL: é
-- `acessa_sintese`.
--
-- O rótulo mudou e o nome interno não. `score` passou a se chamar "KPIs
-- Reputacionais" na capa, e "Painel de Inteligência de Mercado" foi para o
-- cartão de `sintese`, que está `pronto: false` — em construção. Está escrito
-- em `front-reputacional/src/paginas/Inicio.tsx`, junto do porquê.
--
-- Um quarto portal teria sido pior do que inútil: o nível "Mercado" concederia
-- `acessa_mercado`, que não guarda rota nenhuma, enquanto o painel de verdade
-- continuaria atrás de `acessa_sintese`, não concedido. A tela pareceria certa.
--
-- Fica como lição de leitura de código: o descritivo fala a língua do produto,
-- o banco fala a do sistema, e os nomes não se correspondem um a um.
-- =============================================================================

insert into papel (
  codigo, nome,
  pode_criar, pode_editar_proprio, pode_editar_tudo,
  administra_dicionarios, administra_acessos,
  ve_campos_sensiveis, ve_diretorio, pode_exportar,
  acessa_crm, acessa_sintese, acessa_score
) values
  -- `pode_editar_tudo` FALSO: mexer no registro que outra pessoa criou é
  -- permissão de coordenação, e segue morando só em `plataforma_edicao`. É a
  -- mesma distinção que 0003 faz entre `crm_edicao` e `plataforma_edicao` — e é
  -- a razão de este papel não ser apenas "plataforma_edicao sem admin".
  ('plataforma_edicao_sem_acessos', 'Plataforma · edição (não administra acessos)',
   true,  true,  false, false, false, true,  true,  true,  true,  true,  true )
on conflict (codigo) do nothing;
