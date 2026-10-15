-- =============================================================================
-- 0090 — a agenda de destaque, e como se acha ela depois
--
-- O QUE É
--
-- Uma marca EDITORIAL feita por quem registra: "esta agenda merece ser
-- destacada". Não é cálculo, não é derivada de nada e não quer dizer que a
-- agenda seja importante por algum critério do sistema — quer dizer que uma
-- pessoa decidiu apontá-la.
--
--     destaque = true   → a agenda aparece marcada na Base e na ficha, e o
--                         filtro "Só agendas de destaque" a encontra.
--     destaque = false  → agenda comum. É o padrão.
--
-- NÃO É CONTROLE DE ACESSO, e esta é a diferença que importa em relação a
-- `sensivel` (0089), que é a outra bandeira booleana desta tabela:
--
--     sensivel  restringe QUEM alcança a linha. É segurança: entra em
--               `filtros_sql.condicoes()` SEMPRE, sem ninguém pedir, e tira a
--               agenda da Base, do KPI e da busca de quem não tem a camada.
--
--     destaque  não restringe nada. É um filtro OPCIONAL como frente, UF ou
--               clima: só estreita quando a pessoa pede. Quem pode ver a
--               agenda vê a marca; quem pode editar pode marcar.
--
-- Confundir as duas seria o jeito de transformar uma marca editorial em
-- permissão por acidente, e é por isso que está escrito aqui.
--
-- POR QUE `not null default false`
--
-- Mesmo motivo de `sensivel`: três estados num campo de duas respostas
-- (sim/não/não respondeu) só adiariam a pergunta "e o nulo, conta?" para cada
-- consulta que filtrar por ele — e cada uma responderia à sua maneira. As 300+
-- agendas existentes nascem comuns, que é a leitura certa: ninguém as apontou.
--
-- O QUE ISSO FAZ COM O KPI
--
-- Enquanto ninguém filtrar, nada. O filtro entra em `condicoes()` como
-- qualquer outro recorte, então quando alguém pedir "só destaque" os KPIs
-- respondem ao MESMO subconjunto que a tabela lista — que é a invariante do
-- sistema. Não há divergência por pessoa aqui, porque não há camada.
--
-- CUIDADO COM A PALAVRA: no Painel de Inteligência de Mercado "Destaque" já
-- nomeia o bloco-manchete de uma lente (`FICHA_DO_DESTAQUE`, em `api/lentes`),
-- que é CALCULADO a partir de menções. São coisas diferentes em domínios
-- diferentes — aquilo é derivado, isto é declarado — e nenhuma lê a outra.
-- =============================================================================

alter table interacao
  add column if not exists destaque boolean not null default false;

comment on column interacao.destaque is
  'Marca editorial de quem registra: esta agenda merece ser destacada. '
  'NÃO é controle de acesso — diferente de `sensivel`, não restringe quem '
  'alcança a linha; é um filtro opcional como frente ou UF.';


-- SEM ÍNDICE, e por uma razão diferente da de 0089.
--
-- Lá o argumento era a baixa seletividade: `sensivel = false` casa com quase
-- tudo e o planejador não escolheria o índice. Aqui é o contrário —
-- `destaque = true` é seletivo, e um índice PARCIAL (`where destaque`) é
-- exatamente a forma certa para este predicado.
--
-- O que falta é tamanho: a tabela tem algumas centenas de linhas, e nessa
-- escala a varredura sequencial ganha do índice. Criá-lo agora seria custo de
-- escrita em toda gravação de agenda em troca de nada.
--
-- QUANDO CRIAR: quando a Base passar da ordem de dezenas de milhares de
-- agendas e o filtro de destaque aparecer no plano como varredura. É
--     create index concurrently interacao_destaque_idx on interacao (destaque)
--       where destaque;
-- e cabe numa migration própria, medida antes.