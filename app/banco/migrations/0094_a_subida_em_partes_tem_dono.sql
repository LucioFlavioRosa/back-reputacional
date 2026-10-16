-- =============================================================================
-- 0094 — a subida em partes passa a ter DONO, e a linha nasce antes do byte.
--
-- O QUE A REVISÃO DO CODEX ACHOU, em 16/10/2026, no caminho que a 0092 abriu e
-- que a subida em partes estendeu. O desenho em partes emitia um `planilha_id`
-- e NÃO o gravava em lugar nenhum até a conferência terminar — o estado da
-- subida era só o caminho no Blob. Disso saíram quatro defeitos:
--
--   1. O IDENTIFICADOR VALIA COMO SENHA AO PORTADOR. `receber_parte` não tinha
--      o que consultar para saber de quem era a subida, então aceitava partes
--      de qualquer sessão: quem conhecesse o uuid de outra pessoa registrava a
--      planilha dela no próprio nome. E `PUT` com uuid nunca aberto também
--      funcionava, gastando armazenamento sem criar estado algum.
--
--   2. O TETO DECLARADO NÃO LIMITAVA NADA. Declarar 1 MB e enviar oitenta
--      partes de 1 MB montava 80 MB. E a rota da parte é isenta do limite
--      genérico de corpo (tem de ser), então a parte podia vir com qualquer
--      tamanho e o processo a lia inteira na memória.
--
--   3. `partes` NÃO TINHA LIMITE. `partes=1_000_000_000` na conferência fazia
--      o processo construir a lista de blocos antes de falar com o Azure.
--
--   4. O BYTE FICAVA ÓRFÃO em três caminhos: a publicação acontecia antes do
--      `try` da rota, a leitura podia falhar, e o commit da sessão acontece
--      DEPOIS de a rota retornar (`banco/sessao.py`) — um commit que falhe
--      desfazia a linha e deixava o arquivo publicado.
--
-- A LINHA RESOLVE OS QUATRO, e é por isso que a correção é esta coluna e não
-- quatro verificações espalhadas:
--
--   * dono, fonte e tamanho declarado passam a estar GRAVADOS quando a primeira
--     parte chega — então há o que consultar, e a consulta é a verificação;
--   * o índice único de (fonte, criado_por) passa a significar "uma subida em
--     voo por fonte e por pessoa", que é o limite natural do abuso;
--   * a linha nasce ANTES do byte, como no caminho de uma vez só — e aí o byte
--     nunca é órfão: se a conferência falhar em qualquer ponto, inclusive no
--     commit, sobra uma linha INCOMPLETA apontando para o arquivo, que é
--     exatamente o que permite achá-lo e apagá-lo depois.
--
-- `completa_em` NULO É O ESTADO "SUBINDO", e a escolha por timestamp em vez de
-- booleano é deliberada: ela diz TAMBÉM quando terminou, e é o que uma varredura
-- por idade vai precisar para distinguir subida abandonada de planilha
-- conferida e esquecida. Um booleano exigiria outra coluna depois.
--
-- NÃO MUDA O CAMINHO DE UMA VEZ SÓ: ali a conferência grava a linha já
-- completa, no mesmo instante, e o valor nasce preenchido. O `default now()`
-- existe para isso — a inserção antiga continua válida sem citar a coluna.
--
-- NENHUM GRANT NOVO. Permissão no Postgres é por TABELA, não por coluna: a 0009
-- deu select/insert/update pelas tabelas futuras e a 0093 deu o delete. Coluna
-- nova herda. (Conferido antes de escrever isto, porque esquecer grant já
-- cobrou três vezes neste banco.)
-- =============================================================================

alter table planilha_recebida
    add column if not exists completa_em timestamptz not null default now();

--: AS LINHAS QUE JÁ EXISTEM ESTÃO COMPLETAS, e o `default` já as preencheu: toda
--: planilha em `planilha_recebida` hoje veio do caminho de uma vez só, que só
--: grava depois de conferir. Não há subida em voo para reconciliar.

--: E O ESTADO "SUBINDO" É A AUSÊNCIA, então a coluna precisa aceitar nulo para
--: quem nasce incompleta. O `not null` acima serve só para o `default` alcançar
--: as linhas existentes; o `drop not null` é o que abre o estado novo.
--:
--: NESTA ORDEM, E NÃO NULÁVEL DIRETO: criada nulável, as linhas existentes
--: ficariam com nulo — ou seja, seriam lidas como "subindo" — e a confirmação
--: passaria a recusar planilha que estava válida. Duas linhas em vez de uma, e
--: a diferença é não quebrar quem está no meio de uma importação agora.
alter table planilha_recebida
    alter column completa_em drop not null;

--: QUEM PROCURA SUBIDA EM VOO procura por isto. Índice parcial porque o estado
--: é raro e transitório: no regime normal a tabela tem zero ou poucas linhas
--: incompletas, e um índice sobre a coluna inteira pagaria por todas.
create index if not exists planilha_recebida_subindo
    on planilha_recebida (criado_por, fonte_id)
    where completa_em is null;
