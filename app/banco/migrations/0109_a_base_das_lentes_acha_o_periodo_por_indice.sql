--: A BASE DE DADOS DAS LENTES VARRIA A TABELA INTEIRA A CADA ABERTURA.
--:
--: DEFEITO RELATADO PELO DONO DO PRODUTO: "quando vou na base de dados das
--: lentes está demorando muito para carregar, mesmo a busca também tem demorado
--: para retomar quando digito algo".
--:
--: MEDIDO NO AMBIENTE, pelos logs de duração da própria API:
--:   GET /api/score/base/imprensa/mencoes -> 200 em 48507ms
--:   (e 47869, 47450, 42011, 41949, 33542 na mesma janela; 16477ms hoje)
--: A linha de base é ~500ms, e há um agrupamento de 1,2s a 2,5s em que VÁRIAS
--: lentes são pedidas quase ao mesmo tempo — trocar de aba dispara uma consulta
--: nova sem cancelar a anterior, e elas disputam a mesma CPU.
--:
--: A CAUSA: o período da tela recorta por `coalesce(data, mes)` — a data da
--: menção, com o mês como reserva para a linha que veio sem data. É uma FUNÇÃO
--: SOBRE DUAS COLUNAS, e nenhum dos 17 índices de `mencao` a atende: o
--: planejador não tem escolha senão `Seq Scan` nas 104 mil linhas. E são DOIS
--: scans por requisição, porque o `total` do rodapé é montado à parte da lista.
--: Num Postgres `Standard_B1ms` (1 vCPU, burstable), duas varreduras completas
--: por requisição e várias requisições concorrentes esgotam o crédito de CPU —
--: é daí que saem os 48 segundos.
--:
--: MEDIDO COM 104 MIL MENÇÕES NUM BANCO LOCAL, antes e depois deste índice:
--:   o total   26ms -> 6,9ms   (Seq Scan -> Bitmap Index Scan)
--:   a lista   25ms -> 10,7ms
--:   a busca  274ms -> 102ms   (ela passa a filtrar as 10 mil do período, e
--:                              não as 104 mil da tabela)
--:
--: SÓ A EXPRESSÃO, e não `(fonte_id, coalesce(...))`: eu criei os dois e medi.
--: O planejador escolheu este, e o composto ficou com zero uso — a lente entra
--: por `score_fonte`, numa junção, então o `fonte_id` não chega ao índice como
--: constante. Um índice que ninguém usa custa escrita em toda ingestão.
--:
--: `CREATE INDEX` COMUM, e não `CONCURRENTLY`: o job de migrações roda cada
--: arquivo dentro de uma transação, e `concurrently` não pode. Em 104 mil linhas
--: leva bem menos de um segundo; a trava de escrita é só isso, e não há
--: ingestão rodando no momento da implantação.
--:
--: A BUSCA LIVRE CONTINUA CUSTANDO, e o caminho óbvio foi TENTADO E MEDIDO
--: antes de eu deixá-lo de fora. Ela compara `lower(translate(coluna))` com
--: `like '%termo%'` em dez colunas, que nenhum btree atende; `pg_trgm` está
--: instalado e a busca do CRM usa GIN trigrama (`interacao_pauta_trgm_idx` e as
--: duas irmãs), então parecia ser só repetir a receita. Criei os GIN sobre as
--: expressões normalizadas no banco com as 104 mil linhas e medi:
--:   a busca 102ms -> 88ms, e NENHUM dos índices foi usado pelo planejador.
--: Ele prefere o índice de data: o período já corta 104 mil para 10 mil, e um
--: `BitmapOr` de dez GIN custaria mais do que filtrar essas 10 mil. Custo que
--: NÃO se paga: 21 MB de índice sobre 27 MB de tabela, mantidos em toda
--: ingestão, por 14%.
--: O que resta ali é CPU de `translate` em dez colunas sobre as linhas do
--: período — isso só cai mudando a forma (menos colunas, ou uma coluna de texto
--: de busca já normalizada), e é decisão de produto.
--: A tela também não cancela a consulta superada ao trocar de aba ou digitar.
--:
--: Idempotente.

begin;

create index if not exists mencao_por_data_efetiva
  on mencao ((coalesce(data, mes)));

commit;
