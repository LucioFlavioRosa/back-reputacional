--: A NOVA TAXONOMIA DE TEMAS — 4 blocos, 20 macro temas, 38 temas, proposta
--: pela Peers/Comms (planilha "Taxonomia de temas Aegea", v1.3, ainda em
--: validação por área — a coluna "Área concorda?" está vazia em todas as
--: linhas). Esta migration só constrói a ESTRUTURA e carrega o RASCUNHO;
--: nada disto fica visível na aplicação enquanto a validação não fechar.
--:
--: DOIS DICIONÁRIOS NOVOS, no molde de `categoria_publico`/`subcategoria_publico`
--: (0036), só que com um nível a mais: `bloco_tema` (4 linhas fixas) e
--: `macro_tema` (20 linhas, cada uma presa a um bloco). `tema` ganha
--: `macro_tema_id` para se encaixar nessa hierarquia — o terceiro nível já
--: existia, só não tinha pai.
--:
--: `camada_lso` (Legitimidade/Credibilidade/Confiança/Não se aplica) é
--: coluna nova, e não reaproveita `tipo` (`estruturante`/`operacional`,
--: 0048): embora as duas sejam "cadastro, não derivação" sobre o mesmo
--: `tema`, `tipo` nunca foi escrito por código nenhum e não é a mesma
--: pergunta que Camada de LSO responde — não convém forçar a taxonomia nova
--: dentro de um rótulo morto só porque ambos estão vagos hoje. `tipo`
--: continua existindo, sem uso, até alguém decidir o que fazer com ele.
--:
--: `area_dona_id` (`references area_pessoa`, mesmo dicionário que
--: `categoria_publico` já usa) FICA NULO EM TODOS OS 38 TEMAS NESTA
--: MIGRATION, de propósito: a planilha marca "Área dona sugerida" como
--: premissa, várias linhas sugerem MAIS DE UMA área ("Operações e
--: Jurídico", "Gente e Gestão e RI"...), e nenhuma delas ainda existe em
--: `area_pessoa` (que hoje só tem as cinco áreas de comunicação/RI/
--: financeiro — ver 0052). Popular esse campo agora seria inventar um
--: dono único para uma pergunta que a planilha propositalmente deixou
--: composta, ou criar áreas novas sem confirmação — decisão de negócio,
--: não técnica.
--:
--: OS 38 TEMAS NOVOS ENTRAM COM `ativo = false`: `GET /api/dicionarios` só
--: devolve dicionário com `ativo = true` (`app/api/catalogo.py`), então
--: nenhum cadastro ou filtro do painel muda de comportamento com esta
--: migration. Ativar em massa fica para quando a validação por área
--: fechar — até lá, os 38 existem no banco só para quem quiser consultar
--: ou construir a tela em cima deles.
--:
--: RECONCILIAÇÃO COM O CADASTRO ATUAL: dos 17 temas já em uso (0001), só
--: "Inclusão sanitária" tem nome IDÊNTICO na lista nova (17a) — por isso é
--: o único que esta migration liga à hierarquia nova (`update`, preservando
--: `id`, `ativo` e todo histórico de interações que já apontam para ele).
--: Os outros 16 (Tarifa, Universalização, IPO, Regulação, Leilões, Copasa,
--: Resíduos, Biometano, Reúso, Carbono, Clima, Modelo de negócio,
--: Disciplina financeira, Cenário político, Tributário, Reputação) NÃO TÊM
--: sucessor óbvio nos 38 novos — viraram temas mais granulares, foram
--: absorvidos em outro, ou não aparecem mais. Migrar as interações que os
--: usam é decisão editorial pendente, fora do escopo desta migration.
--:
--: Idempotente: `create table if not exists`, `on conflict do nothing`.

begin;

create table if not exists bloco_tema (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

create table if not exists macro_tema (
  id smallserial primary key,
  bloco_tema_id smallint not null references bloco_tema(id),
  codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

alter table tema add column if not exists macro_tema_id smallint references macro_tema(id);
alter table tema add column if not exists camada_lso text
  check (camada_lso in ('legitimidade', 'credibilidade', 'confianca', 'nao_se_aplica'));
alter table tema add column if not exists area_dona_id smallint references area_pessoa(id);

comment on column tema.macro_tema_id is
  'A hierarquia bloco > macro tema > tema da taxonomia v1.3 (Peers/Comms, ainda em validação). Nulo em quem não foi reconciliado com a taxonomia nova — ver 0053.';
comment on column tema.camada_lso is
  'Legitimidade / Credibilidade / Confiança / Não se aplica — dimensão da taxonomia v1.3, distinta de `tipo` (0048). Cadastro, não derivação. Ver 0053.';
comment on column tema.area_dona_id is
  'references area_pessoa(id), mesmo dicionário de `categoria_publico`. Nulo em toda a carga inicial da taxonomia v1.3: a planilha de origem sugere mais de uma área em várias linhas, e a decisão de qual prevalece ainda não foi tomada. Ver 0053.';


-- -- os 4 blocos -----------------------------------------------------------

insert into bloco_tema (codigo, nome, ordem) values
  ('entrega_do_servico',                'Entrega do serviço',                    1),
  ('economia_do_contrato',              'Economia do contrato',                  2),
  ('empresa_e_capital',                 'Empresa e capital',                     3),
  ('sustentabilidade_sociedade_marca',  'Sustentabilidade, sociedade e marca',   4)
on conflict (codigo) do nothing;


-- -- os 20 macro temas ------------------------------------------------------

insert into macro_tema (bloco_tema_id, codigo, nome, ordem) values
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'abastecimento', 'Abastecimento', 1),
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'qualidade_da_agua', 'Qualidade da água', 2),
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'coleta_e_tratamento_de_esgoto', 'Coleta e tratamento de esgoto', 3),
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'obras_e_universalizacao', 'Obras e universalização', 4),
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'transtornos_de_obra', 'Transtornos de obra', 5),
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'atendimento', 'Atendimento', 6),
  ((select id from bloco_tema where codigo = 'entrega_do_servico'), 'fatura_e_cobranca', 'Fatura e cobrança', 7),

  ((select id from bloco_tema where codigo = 'economia_do_contrato'), 'tarifa', 'Tarifa', 1),
  ((select id from bloco_tema where codigo = 'economia_do_contrato'), 'residuos_solidos_e_taxa_de_lixo', 'Resíduos sólidos e taxa de lixo', 2),
  ((select id from bloco_tema where codigo = 'economia_do_contrato'), 'contrato_e_regulacao', 'Contrato e regulação', 3),
  ((select id from bloco_tema where codigo = 'economia_do_contrato'), 'modelo_de_concessao', 'Modelo de concessão', 4),

  ((select id from bloco_tema where codigo = 'empresa_e_capital'), 'mercado_de_capitais_e_financas', 'Mercado de capitais e finanças', 1),
  ((select id from bloco_tema where codigo = 'empresa_e_capital'), 'crescimento_e_novos_negocios', 'Crescimento e novos negócios', 2),
  ((select id from bloco_tema where codigo = 'empresa_e_capital'), 'integridade_e_transparencia', 'Integridade e transparência', 3),
  ((select id from bloco_tema where codigo = 'empresa_e_capital'), 'relacoes_institucionais', 'Relações institucionais', 4),

  ((select id from bloco_tema where codigo = 'sustentabilidade_sociedade_marca'), 'meio_ambiente_e_clima', 'Meio ambiente e clima', 1),
  ((select id from bloco_tema where codigo = 'sustentabilidade_sociedade_marca'), 'impacto_social', 'Impacto social', 2),
  ((select id from bloco_tema where codigo = 'sustentabilidade_sociedade_marca'), 'pessoas', 'Pessoas', 3),
  ((select id from bloco_tema where codigo = 'sustentabilidade_sociedade_marca'), 'inovacao_e_tecnologia', 'Inovação e tecnologia', 4),
  ((select id from bloco_tema where codigo = 'sustentabilidade_sociedade_marca'), 'reconhecimento_e_premiacoes', 'Reconhecimento e premiações', 5)
on conflict (codigo) do nothing;


-- -- os 38 temas: 37 novos (rascunho, inativos) + 1 reconciliado -----------
--
-- `on conflict (nome) do nothing`: protege quem rodar esta migration de novo,
-- e também o único nome que já existe hoje ("Inclusão sanitária") — que
-- não é pra inserir de novo, é pra reconciliar no `update` logo abaixo.

insert into tema (nome, nivel, macro_tema_id, camada_lso, ativo) values
  ('Continuidade do abastecimento', 'sensivel',
    (select id from macro_tema where codigo = 'abastecimento'), 'legitimidade', false),
  ('Perdas, fraudes e furtos', 'gerais',
    (select id from macro_tema where codigo = 'abastecimento'), 'legitimidade', false),

  ('Gestão da qualidade da água', 'sensivel',
    (select id from macro_tema where codigo = 'qualidade_da_agua'), 'legitimidade', false),

  ('Falhas na coleta de esgoto', 'sensivel',
    (select id from macro_tema where codigo = 'coleta_e_tratamento_de_esgoto'), 'legitimidade', false),
  ('Lançamento e balneabilidade', 'sensivel',
    (select id from macro_tema where codigo = 'coleta_e_tratamento_de_esgoto'), 'legitimidade', false),

  ('Universalização e metas de cobertura', 'estrategico',
    (select id from macro_tema where codigo = 'obras_e_universalizacao'), 'legitimidade', false),
  ('Obras e expansão de rede', 'estrategico',
    (select id from macro_tema where codigo = 'obras_e_universalizacao'), 'legitimidade', false),

  ('Pavimentação e recomposição', 'gerais',
    (select id from macro_tema where codigo = 'transtornos_de_obra'), 'credibilidade', false),
  ('Acidentes e danos a terceiros', 'sensivel',
    (select id from macro_tema where codigo = 'transtornos_de_obra'), 'credibilidade', false),

  ('Canais e serviços ao cliente', 'gerais',
    (select id from macro_tema where codigo = 'atendimento'), 'credibilidade', false),
  ('Reclamações em órgãos de defesa', 'sensivel',
    (select id from macro_tema where codigo = 'atendimento'), 'credibilidade', false),

  ('Fatura e pagamento', 'gerais',
    (select id from macro_tema where codigo = 'fatura_e_cobranca'), 'credibilidade', false),
  ('Corte e inadimplência', 'sensivel',
    (select id from macro_tema where codigo = 'fatura_e_cobranca'), 'credibilidade', false),

  ('Reajuste e estrutura tarifária', 'sensivel',
    (select id from macro_tema where codigo = 'tarifa'), 'credibilidade', false),
  ('Tarifa social', 'estrategico',
    (select id from macro_tema where codigo = 'tarifa'), 'credibilidade', false),

  ('Taxa de lixo', 'sensivel',
    (select id from macro_tema where codigo = 'residuos_solidos_e_taxa_de_lixo'), 'credibilidade', false),
  ('Coleta e destinação', 'gerais',
    (select id from macro_tema where codigo = 'residuos_solidos_e_taxa_de_lixo'), 'credibilidade', false),

  ('Fiscalização e sanções', 'sensivel',
    (select id from macro_tema where codigo = 'contrato_e_regulacao'), 'legitimidade', false),
  ('Revisão e continuidade dos contratos', 'sensivel',
    (select id from macro_tema where codigo = 'contrato_e_regulacao'), 'legitimidade', false),

  ('Modelo de negócio e debate público', 'sensivel',
    (select id from macro_tema where codigo = 'modelo_de_concessao'), 'legitimidade', false),

  ('Governança, resultados e acionistas', 'sensivel',
    (select id from macro_tema where codigo = 'mercado_de_capitais_e_financas'), 'nao_se_aplica', false),
  ('Dívida, captação e solidez financeira', 'sensivel',
    (select id from macro_tema where codigo = 'mercado_de_capitais_e_financas'), 'nao_se_aplica', false),

  ('Leilões e novas operações', 'estrategico',
    (select id from macro_tema where codigo = 'crescimento_e_novos_negocios'), 'nao_se_aplica', false),

  ('Processos e investigações', 'sensivel',
    (select id from macro_tema where codigo = 'integridade_e_transparencia'), 'credibilidade', false),
  ('Conduta e compliance', 'sensivel',
    (select id from macro_tema where codigo = 'integridade_e_transparencia'), 'credibilidade', false),

  ('Agenda pública e setorial', 'estrategico',
    (select id from macro_tema where codigo = 'relacoes_institucionais'), 'confianca', false),

  ('Proteção de mananciais e oceanos', 'estrategico',
    (select id from macro_tema where codigo = 'meio_ambiente_e_clima'), 'confianca', false),
  ('Resiliência hídrica e novas fontes', 'estrategico',
    (select id from macro_tema where codigo = 'meio_ambiente_e_clima'), 'confianca', false),
  ('Licenciamento ambiental', 'sensivel',
    (select id from macro_tema where codigo = 'meio_ambiente_e_clima'), 'confianca', false),
  ('Energia, carbono e economia circular', 'estrategico',
    (select id from macro_tema where codigo = 'meio_ambiente_e_clima'), 'confianca', false),

  ('Programas sociais e comunidade', 'gerais',
    (select id from macro_tema where codigo = 'impacto_social'), 'confianca', false),

  ('Atração e desenvolvimento', 'gerais',
    (select id from macro_tema where codigo = 'pessoas'), 'nao_se_aplica', false),
  ('Diversidade e inclusão', 'sensivel',
    (select id from macro_tema where codigo = 'pessoas'), 'nao_se_aplica', false),
  ('Segurança e relações de trabalho', 'sensivel',
    (select id from macro_tema where codigo = 'pessoas'), 'nao_se_aplica', false),

  ('Tecnologia e inovação na operação', 'estrategico',
    (select id from macro_tema where codigo = 'inovacao_e_tecnologia'), 'nao_se_aplica', false),

  ('Prêmios, rankings e certificações', 'estrategico',
    (select id from macro_tema where codigo = 'reconhecimento_e_premiacoes'), 'confianca', false),
  ('Homenagens locais', 'gerais',
    (select id from macro_tema where codigo = 'reconhecimento_e_premiacoes'), 'confianca', false)
on conflict (nome) do nothing;

-- O único tema de fundação (0001) com nome idêntico na taxonomia nova (17a).
-- Reconciliado no lugar, preservando id/ativo/histórico — os outros 16 temas
-- de fundação ficam como estão, sem `macro_tema_id`, até a decisão editorial
-- de para onde cada um migra.
update tema set
  macro_tema_id = (select id from macro_tema where codigo = 'impacto_social'),
  camada_lso = 'confianca'
where nome = 'Inclusão sanitária';

commit;
