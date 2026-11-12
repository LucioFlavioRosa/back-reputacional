-- =============================================================================
-- 0120 — o Fornecedor de Dados SÓ SOBE PLANILHA, e nada mais
--
-- Bites, Clipei, Approach e futuros fornecedores de fonte do Score precisam de
-- uma conta que alcance só a tela de Importação do Score (baixar/conferir/subir
-- a planilha mensal) — nunca o portal inteiro, que também mostra Lentes, KPIs,
-- o Radar e a calibração do índice.
--
-- POR QUE NÃO REAPROVEITAR `administra_dicionarios`
--
-- É a permissão que hoje guarda a subida de planilha (`exigir_administracao_de_
-- cadastros`), mas ela é larga demais: a mesma flag abre o Cadastro
-- compartilhado (editar Instituição, Interlocutor, Tema) e a calibração/
-- reconciliação do Score. Dar essa flag a uma empresa de fora concederia tudo
-- isso em troca de só querer o upload.
--
-- POR QUE NÃO REAPROVEITAR `acessa_score`
--
-- Abriria o portal inteiro — Lentes, KPIs, Radar — que não é o que um
-- fornecedor de dados deve ver. A tela de Importação do Score passou a viver
-- fora do prefixo protegido por `exigir_portal_score` desde este commit (ver
-- `rotas_de_fontes` em `app/api/score.py`), exatamente para permitir este novo
-- papel sem abrir o resto do portal para ele.
--
-- A GUARDA NOVA (`exigir_upload_de_fontes`, em `app/api/dependencias.py`) passa
-- quem tem `administra_dicionarios` OU `sobe_planilha_do_score` — quem já
-- administra continua subindo, e o fornecedor entra só por esta flag nova.
-- =============================================================================

alter table papel
  add column if not exists sobe_planilha_do_score boolean not null default false;

insert into papel (
  codigo, nome,
  pode_criar, pode_editar_proprio, pode_editar_tudo,
  administra_dicionarios, administra_acessos,
  ve_campos_sensiveis, ve_diretorio, pode_exportar,
  acessa_crm, acessa_inteligencia_de_mercado, acessa_score,
  sobe_planilha_do_score
) values
  -- NENHUM PORTAL, NENHUMA AÇÃO ALÉM DA PLANILHA: é de propósito. Um
  -- fornecedor de dados não cadastra agenda, não vê o diretório de
  -- stakeholders, não exporta — só sobe o arquivo dele.
  ('fornecedor_de_dados', 'Fornecedor de dados (só sobe planilha)',
   false, false, false, false, false, false, false, false,
   false, false, false,
   true)
on conflict (codigo) do nothing;
