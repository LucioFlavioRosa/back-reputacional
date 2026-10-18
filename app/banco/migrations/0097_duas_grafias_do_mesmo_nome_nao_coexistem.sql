-- DUAS GRAFIAS DO MESMO NOME NÃO PODEM COEXISTIR, e coexistiam em dois lugares.
--
-- `referencia` e `jornalista_matriz` tinham cada uma a SUA regra de chave de
-- nome, escrita em SQL dentro do índice único:
--
--   0026  referencia         (lower(btrim(titulo)))
--   0049  jornalista_matriz  (lower(regexp_replace(nome,'\s+',' ','g')),
--                             coalesce(veiculo,''))
--
-- Nenhuma das duas TIRA ACENTO. Então "Relatório Anual" e "Relatorio Anual"
-- entravam como duas referências, e "Taís Hirata" e "Tais Hirata" como duas
-- jornalistas -- contra o que o comentário da própria 0049 promete ("o índice é
-- sobre o nome normalizado PORQUE são a mesma jornalista"). A 0026 ainda deixa
-- passar espaço interno duplo, que a 0049 pelo menos colapsa, e a 0049 não
-- normaliza `veiculo` de jeito nenhum: "Valor Econômico" e "Valor Economico"
-- como veículo também abriam duas linhas para a mesma pessoa.
--
-- POR QUE COLUNA, E NÃO UM SQL MELHOR NO ÍNDICE. Traduzir a regra para SQL
-- seria a QUINTA cópia dela (eram três no Python até 17/10/2026, mais estas
-- duas no banco), e uma cópia que ninguém vê divergir: `unaccent()` não é a
-- mesma coisa que o NFKD + ascii do `dominio/texto.normalizar`, e índice em
-- Postgres exige expressão IMMUTABLE, o que empurra para gambiarra. Então vale
-- aqui o mesmo desenho que `instituicao`, `interlocutor` e `pessoa_aegea` já
-- usam: a COLUNA guarda a chave, a APLICAÇÃO a escreve com a função canônica, e
-- o índice é sobre a coluna. Uma regra, num lugar só, em Python.
--
-- O BACKFILL ABAIXO É A ÚNICA VEZ que a regra aparece em SQL, e é de uso único:
-- `translate()` em vez de `unaccent()` de propósito, porque `unaccent` é
-- extensão (confiável no PG 13+, mas ainda exige CREATE no banco, e o CI roda
-- com conta comum). Ele cobre o acento que o português usa, que é o que existe
-- nestas duas tabelas. E NÃO FICA NO ESCURO: um teste recalcula TODA linha das
-- duas tabelas com `dominio/texto.normalizar` e falha se o backfill divergir em
-- qualquer caractere -- inclusive os que o `translate` não cobre (`ß`, `œ`, `ﬁ`).
--
-- SE JÁ HOUVER PAR DIVERGENTE NO BANCO, O `create unique index` FALHA e a
-- migration para. Isso é o comportamento certo: a decisão de qual das duas
-- linhas sobrevive é de quem cuida do cadastro, não de uma migration. Medido
-- antes de escrever (pilha local): `referencia` 67 linhas e 0 pares,
-- `jornalista_matriz` 10 linhas e 0 pares -- pela regra antiga e pela nova.
--
-- NENHUM GRANT NOVO. Permissão no Postgres é por TABELA, não por coluna: as
-- duas tabelas já têm o que `painel_app` precisa, e coluna nova herda.

-- ============================================================== referencia
alter table referencia add column if not exists titulo_normalizado text;

update referencia
   set titulo_normalizado = lower(
         btrim(
           regexp_replace(
             translate(
               titulo,
               'áàâãäéèêëíìîïóòôõöúùûüçñýÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑÝ',
               'aaaaaeeeeiiiiooooouuuucnyAAAAAEEEEIIIIOOOOOUUUUCNY'
             ),
             '\s+', ' ', 'g'
           )
         )
       )
 where titulo_normalizado is null;

alter table referencia alter column titulo_normalizado set not null;

drop index if exists referencia_titulo_idx;
create unique index if not exists referencia_titulo_normalizado_idx
  on referencia (titulo_normalizado);

-- ======================================================= jornalista_matriz
alter table jornalista_matriz add column if not exists nome_normalizado text;
alter table jornalista_matriz add column if not exists veiculo_normalizado text;

update jornalista_matriz
   set nome_normalizado = lower(
         btrim(
           regexp_replace(
             translate(
               nome,
               'áàâãäéèêëíìîïóòôõöúùûüçñýÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑÝ',
               'aaaaaeeeeiiiiooooouuuucnyAAAAAEEEEIIIIOOOOOUUUUCNY'
             ),
             '\s+', ' ', 'g'
           )
         )
       ),
       veiculo_normalizado = case
         when veiculo is null then null
         else lower(
           btrim(
             regexp_replace(
               translate(
                 veiculo,
                 'áàâãäéèêëíìîïóòôõöúùûüçñýÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑÝ',
                 'aaaaaeeeeiiiiooooouuuucnyAAAAAEEEEIIIIOOOOOUUUUCNY'
               ),
               '\s+', ' ', 'g'
             )
           )
         )
       end
 where nome_normalizado is null;

alter table jornalista_matriz alter column nome_normalizado set not null;

-- O `where ativo` SE MANTÉM: a matriz desativa em vez de apagar, e duas linhas
-- inativas da mesma pessoa são histórico, não duplicata.
--
-- NOME NOVO, E NÃO O MESMO `jornalista_matriz_unica`. Eu escrevi o mesmo nome
-- primeiro, e `test_dois_indices_nao_disputam_o_mesmo_nome` me parou: um
-- `create ... if not exists` com nome já usado é NO-OP SILENCIOSO, e foi assim
-- que a `0052` pediu um índice que nunca nasceu. O `drop` logo acima faria o
-- caminho funcionar hoje, mas o dia em que ele falhar ou alguém reordenar, o
-- índice ANTIGO continua valendo com o nome do novo — e a regra errada volta
-- sem ninguém ver.
drop index if exists jornalista_matriz_unica;
create unique index if not exists jornalista_matriz_unica_normalizada
  on jornalista_matriz (nome_normalizado, coalesce(veiculo_normalizado, ''))
  where ativo;
