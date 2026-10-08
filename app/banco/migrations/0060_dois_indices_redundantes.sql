-- 0060 — os dois índices que outro índice já cobre
--
-- ERA A 0059, E O NÚMERO FOI TOMADO: a `0059_matriz_de_risco_corporativo`
-- entrou no `main` enquanto esta estava em revisão. Renumerar aqui é seguro
-- porque esta migration nunca saiu deste branch — nenhum banco a registrou com
-- o nome antigo. Se já tivesse saído, renomear faria o `scripts/migrar.py`
-- rodá-la de novo, porque ele controla por NOME DE ARQUIVO.
--
-- (E é a segunda colisão de número no projeto: o `main` também tem duas 0055,
-- de dois branches paralelos. O custo é esse — a numeração sequencial não
-- sobrevive a dois branches abertos ao mesmo tempo.)
--
-- ACHADO DE REVISÃO de 08/10/2026, feita com as regras de Postgres do
-- `supabase-postgres-best-practices` e o checklist do `database-schema-designer`.
-- Nenhum dos dois é defeito de quem escreveu: os dois viraram redundantes por
-- ACÚMULO, quando um índice mais largo apareceu depois e passou a cobri-los.
--
-- POR QUE UM PREFIXO BASTA. Um índice btree de `(a, b, c)` serve qualquer
-- consulta que filtre por `(a)` ou por `(a, b)` — o Postgres lê as primeiras
-- colunas e ignora o resto. O caminho inverso não vale: `(a, b)` não serve uma
-- consulta por `(b)`. Então um índice de duas colunas cujo par é o começo de um
-- de três não acrescenta leitura nenhuma, e cobra escrita em toda inserção.
--
-- O QUE SE GANHA não é o espaço, é a escrita. A carga das Lentes insere 20.928
-- linhas em `mencao` de uma vez, e cada índice a mais é uma árvore a atualizar
-- linha por linha. O espaço (600 kB) é troco.
--
-- NÃO USEI `CONCURRENTLY`, de propósito: ele não roda dentro de transação, e
-- estas migrations rodam em bloco — tanto pelo `docker-entrypoint-initdb.d` na
-- pilha local quanto pelo `scripts/migrar.py` no Job do AKS. `DROP INDEX` pede
-- lock exclusivo na tabela, e aqui ele é de milissegundos: `mencao` tem 20 mil
-- linhas e o drop não reescreve a tabela. Numa tabela de milhões, a conta
-- mudaria e valeria sair da transação.
--
-- `IF EXISTS` porque banco criado do zero depois desta migration nunca terá
-- estes índices: a 0048 e a 0003 continuam criando-os (reescrever migration
-- publicada é pior que aceitar o drop logo depois), então em banco novo eles
-- nascem e morrem na mesma subida. Em banco existente, só morrem.

begin;

-- `mencao_por_fonte_e_mes (fonte_id, mes)`, nascido na 0048.
--
-- Virou prefixo de QUATRO índices: `mencao_por_perfil` e `mencao_por_uf`
-- (0055), `mencao_por_autor` e `mencao_por_subtema` (0056) — todos
-- `(fonte_id, mes, <dimensão>)`. Na pilha local ele estava com ZERO leituras
-- contra 12.257 dos quatro que o cobrem, o que confirma a leitura do plano.
drop index if exists mencao_por_fonte_e_mes;

-- `idx_usuario_escopo_usuario (usuario_id)`, nascido na 0003, no mesmo arquivo
-- que declara a PK `(usuario_id, dimensao, valor)` — que já começa por
-- `usuario_id`. Oito quilobytes; entra de carona porque é a mesma conversa, e
-- deixar um caso conhecido para trás é como a próxima revisão reencontra os
-- dois.
drop index if exists idx_usuario_escopo_usuario;

commit;

-- O QUE NÃO ENTROU NESTA MIGRATION, e fica dito para a próxima pessoa não
-- procurar:
--
--   as 43 FKs sem índice      estão em tabelas de 8 a 293 linhas apontando para
--                             dicionários de até 149. Nessa escala a varredura
--                             ganha do índice, e índice cobra escrita. A regra
--                             é CRÍTICA na skill e NÃO se aplica a este banco
--                             hoje; vale revisitar quando `interacao` crescer
--                             uma ordem de grandeza.
--
--   `mencao.tema_id` e        estão NULL nas 20.928 linhas — a carga preenche
--   `mencao.unidade_negocio_id`  `tema_texto` e `unidade_texto`. São duas
--                             chaves estrangeiras mortas, e é por isso que a
--                             0058 trocou a taxonomia sem tocar nas menções.
--                             Apagá-las é decisão do dono do produto: as outras
--                             lentes podem pretender preenchê-las.
--
--   os 40 índices nunca lidos a pilha estava no ar há 3 dias. Índice sem
--                             leitura ali quer dizer "a tela não foi aberta",
--                             não "o índice é inútil". `mencao_do_fornecedor_uma_vez`,
--                             por exemplo, é UNIQUE: é a constraint que torna a
--                             carga reexecutável.
