-- 0055 — a menção ganha os campos do padrão Aegea que a Sociedade digital usa
--
-- DE ONDE VEM. O pacote de produção das Lentes (handoff de out/2026) define uma
-- planilha única de 40 colunas por item, igual para as cinco lentes, e a carga
-- inicial traz 29.414 itens reais nesse formato. A `mencao` nasceu com 14 campos
-- — o que a Clipei e a Approach mandavam em 2025 —, e os níveis que o pacote
-- pede (causa → recorte → item) precisam de dimensões que ela não tem.
--
-- SÓ O QUE A SOCIEDADE DIGITAL USA, e isto é decisão de escopo: o dono do
-- produto pediu uma lente por vez, começando por esta. Das 40 colunas do padrão,
-- a aba `item_sociedade_digital` preenche 16; onze já existem na `mencao` com o
-- nome que o índice usa, e as sete abaixo faltavam. As colunas das outras lentes
-- — clima, teor, respondida, frente, órgão, esfera, tier do veículo, pauta,
-- porta-voz — entram na migration da etapa daquela lente, com dado dentro. Uma
-- coluna vazia é uma pergunta sem resposta esperando quem for ler a tabela.
--
-- OS NOMES QUE JÁ EXISTEM FICAM, e não viram os do padrão: `sentimento` é
-- `classificacao` no padrão, `veiculo` é `veiculo_rede`, `tema_texto` é `tema`,
-- `unidade_texto` é `empresa_citada`, `cargo` é `cargo_autor`. Renomear cinco
-- colunas que a API inteira e os dois dossiês já consomem seria pagar hoje, em
-- risco, por uma simetria que o importador resolve com um mapa de uma linha por
-- coluna — que é exatamente o que `score_fonte.mapeamento_colunas` já é.

alter table mencao
  -- O ID NO SISTEMA DO FORNECEDOR. É ele que torna a carga REEXECUTÁVEL: sem
  -- ele, recarregar o mesmo mês duplica tudo, e a única saída é apagar por mês e
  -- rezar para que o arquivo novo cubra o mesmo período.
  add column if not exists id_fonte text,
  -- A UF do autor ou do assunto. Vem em 53% dos itens da Sociedade, e é um dos
  -- cortes que o pacote pede (`uf_mais_negativa` é KPI da lente).
  add column if not exists uf char(2),
  -- O segundo nível do assunto, abaixo de `tema_texto`. A Approach manda em
  -- 15% dos itens; é o corte que explica POR QUE um tema pesa.
  add column if not exists subtema text,
  -- QUEM FALA, em quatro valores: Cidadão, Figura pública, Imprensa, Perfil
  -- institucional. Vem em 100% dos itens da Sociedade e é o que separa "mil
  -- cidadãos reclamando" de "um deputado reclamando" — duas coisas com o mesmo
  -- sinal e consequências diferentes. É KPI da lente (`figuras_publicas`).
  add column if not exists perfil_autor text,
  -- O TEXTO DA MENÇÃO e o endereço dela. Vêm só numa amostra (14%: as negativas,
  -- as de tier alto e as mais engajadas), e o pacote diz que isso é esperado — o
  -- resto chega na primeira carga mensal completa. A tela tem de saber viver com
  -- a ausência, e é por isso que ambas são nulas.
  add column if not exists titulo_texto text,
  add column if not exists link text,
  -- O PESO QUE O PADRÃO DÁ AO ITEM, como DADO e não como régua. A planilha o
  -- traz pronto (1 na Sociedade; 10/5/1 pelo tier do veículo na Imprensa), e ele
  -- fica na linha para a ficha do item poder explicar o próprio peso e para a
  -- importação ser auditável contra o que o fornecedor afirmou.
  --
  -- A NOTA NÃO SAI DAQUI, e é importante não confundir: ela sai da régua da
  -- CALIBRAÇÃO vigente (`score_config.regua_tier` e `regua_engajamento`, ver
  -- `dominio/score.py`), que é o que a tela de Calibração deixa a coordenação
  -- mudar. Com a régua de hoje — contagem, cada menção vale 1 — as duas coisas
  -- coincidem na Sociedade; na Imprensa, a régua `aegea` reproduz o 10/5/1.
  -- Fazer a nota ler esta coluna tiraria a calibração do caminho sem ninguém
  -- pedir.
  add column if not exists peso_tier numeric(4,1) not null default 1;

comment on column mencao.id_fonte is
  'O id do item no sistema do fornecedor. É a chave natural da carga: '
  'com ela, reimportar o mesmo mês atualiza em vez de duplicar. Ver 0055.';
comment on column mencao.perfil_autor is
  'Quem fala: Cidadão, Figura pública, Imprensa, Perfil institucional. '
  'Derivado pelo fornecedor ou pelo importador a partir do cargo e do '
  'nome do autor (padrão Aegea, normalização 8). Ver 0055.';
comment on column mencao.peso_tier is
  'O peso que o padrão Aegea atribui ao item, como o fornecedor o enviou: '
  '1 na Sociedade e nos Clientes, 10/5/1 pelo tier do veículo na Imprensa. '
  'É dado, não régua — a nota usa a calibração vigente. Ver 0055.';

-- A MESMA MENÇÃO NÃO ENTRA DUAS VEZES, e o índice é o que garante. Parcial
-- porque as menções que já estão no banco não têm `id_fonte` — elas vieram antes
-- desta coluna existir, e um índice total recusaria todas elas de uma vez.
--
-- A TRINCA INCLUI A EMPRESA porque uma matéria que cita três concessionárias
-- chega como três linhas com o mesmo `id_fonte` (padrão Aegea, normalização 10):
-- é a empresa citada que as distingue, e sem ela o índice apagaria duas.
create unique index if not exists mencao_do_fornecedor_uma_vez
  on mencao (fonte_id, id_fonte, coalesce(unidade_texto, ''))
  where id_fonte is not null;

create index if not exists mencao_por_perfil on mencao (fonte_id, mes, perfil_autor);
create index if not exists mencao_por_uf on mencao (fonte_id, mes, uf);
