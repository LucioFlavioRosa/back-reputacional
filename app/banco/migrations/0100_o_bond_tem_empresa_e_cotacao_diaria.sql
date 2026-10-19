-- O PAINEL DE INTELIGÊNCIA DE MERCADO GANHA SUA PRIMEIRA BASE: cotação diária
-- de bonds, por empresa.
--
-- O QUE ISTO SERVE. A primeira tela do portal `inteligencia_de_mercado` — que
-- hoje existe na capa com `view: null` — cruza o preço dos bonds da Aegea com o
-- índice reputacional da companhia. O dado vem de um export BDH do Bloomberg
-- que o dono do produto sobe semanalmente.
--
-- TRÊS TABELAS, E A DO MEIO É A QUE PEDIRAM. O pedido foi "uma tabela por
-- empresa (Sabesp, Eletrobras, Light…)". Catorze tabelas de schema idêntico
-- multiplicariam por catorze toda consulta, migration e permissão para entregar
-- o mesmo resultado na tela; o que a tela precisa é que a EMPRESA seja uma
-- entidade, e é isso que `emissor` é.
--
-- E O CADASTRO É NECESSÁRIO, não conveniência: a SABESP aparece com DOIS
-- prefixos de ticker — `SBSPAB31`, `SBSPAB36` e `SABESP30`. Não existe regra de
-- prefixo que resolva isso, então a correspondência ticker → empresa é dado, e
-- dado mora em tabela.
--
-- MEDIDO no arquivo `BASE DE DADOS_HISTORICO BONDS_Yieldv1.xlsx` (16/10/2026):
-- 31 tickers em 15 empresas, 1.750 datas de calendário de 01/01/2022 a
-- 16/10/2026, dois valores por ticker (preço e yield).
--
-- PREÇO E YIELD NA MESMA LINHA, e não duas linhas com uma coluna `tipo`: eles
-- sempre chegam juntos, do mesmo pregão, e o gráfico alterna entre os dois.
-- Duas linhas dobrariam a tabela e obrigariam todo `select` a pivotar.
--
-- A CHAVE PRIMÁRIA COMPOSTA É O QUE TORNA A SUBIDA SEMANAL SEGURA. O pedido
-- falou em "append", mas a planilha é CUMULATIVA: a de hoje traz as 1.750 datas
-- desde 2022, e a da semana que vem trará 1.755. Append cego duplicaria ~54 mil
-- linhas por semana, e o gráfico passaria a somar o mesmo pregão várias vezes.
-- Com `primary key (bond_ticker, data)` a ingestão é `on conflict do update`, e
-- subir o mesmo arquivo duas vezes é inofensivo.
--
-- `NUMERIC`, E NÃO `DOUBLE PRECISION`: preço de bond se lê em centésimos de
-- ponto, a variação diária que a tela mostra tem uma casa decimal, e somar
-- binário de ponto flutuante para depois arredondar é o tipo de erro que
-- aparece como "a conta não fecha com a planilha".
--
-- PERMISSÕES: as `alter default privileges` da 0009 concedem
-- `select/insert/update` a `painel_app` em tabela criada depois dela — que é
-- exatamente o que a ingestão por `upsert` e a leitura da tela usam. `DELETE`
-- NÃO É CONCEDIDO, e aqui a frase é precisa: nenhum caminho da aplicação apaga
-- cotação, e por isso o privilégio não entra. Não estou afirmando que a tabela
-- seja somente leitura por privilégio — ela não é.

create table emissor (
  id    smallserial primary key,
  nome  text        not null unique,
  --: A AEGEA É UMA LINHA COMO AS OUTRAS, marcada por uma coluna. A alternativa
  --: — a tela conhecer o nome "Aegea" — espalharia a identidade da companhia
  --: pelo front, e um dia alguém renomearia o cadastro e a legenda pararia de
  --: separar companhia de par sem ninguém entender por quê.
  e_aegea boolean   not null default false
);

create table bond (
  ticker      text    primary key,
  emissor_id  smallint not null references emissor (id),
  --: O QUE A PLANILHA TRAZ e a ingestão preenche: a descrição com cupom e
  --: vencimento ("AEGEBZ 9 01/20/31"), o identificador do Bloomberg e o
  --: montante em circulação. Nulos aqui porque a migration semeia a
  --: CORRESPONDÊNCIA (que ela sabe) e não o dado de mercado (que ela não tem).
  descricao        text,
  id_bloomberg     text,
  amt_outstanding  numeric(18, 2)
);

create table bond_cotacao (
  bond_ticker    text not null references bond (ticker),
  data           date not null,
  --: OS DOIS NULÁVEIS, e isto é regra de leitura, não frouxidão: a planilha
  --: escreve `0` para "sem cotação" — fim de semana, feriado, e todo dia
  --: anterior à emissão do papel. Gravar o zero desenharia um precipício de 0
  --: para 95 no gráfico, então o leitor converte `0` em nulo e a linha abre um
  --: vão, que é o que "não houve pregão" significa.
  preco_pct_par  numeric(10, 4),
  yield_pct      numeric(10, 4),
  primary key (bond_ticker, data)
);

-- -----------------------------------------------------------------------------
-- AS 15 EMPRESAS E OS 31 TICKERS
-- -----------------------------------------------------------------------------
-- A correspondência é ESCRITA, não derivada — ver a Sabesp acima. Ticker que a
-- planilha traga e não esteja aqui é RECUSADO pela ingestão e mostrado na
-- conferência: é a mesma doutrina do cadastro de assuntos (`temas_da_mencao`),
-- onde o cadastro é a autoridade e o upload não inventa taxonomia. Bond novo
-- emitido pede uma linha aqui, de propósito.

insert into emissor (nome, e_aegea) values
  ('Aegea',          true),
  ('Sabesp',         false),
  ('Eletrobras',     false),
  ('Light',          false),
  ('Simpar',         false),
  ('Movida',         false),
  ('Vamos',          false),
  ('Rumo',           false),
  ('Hidrovias',      false),
  ('Ultrapar',       false),
  ('Açu Petróleo',   false),
  ('Braskem',        false),
  ('Rede D''Or',     false),
  ('Minerva',        false),
  ('Petrobras',      false);

-- A LISTA MORA NUMA TABELA TEMPORÁRIA, e não num `values` dentro do `insert`,
-- por um motivo que a revisão encontrou: a conferência precisa comparar o PAR
-- (ticker, empresa) GRAVADO contra o par PEDIDO, e repetir a lista de 31 linhas
-- no `insert` e outra vez na conferência deixaria um erro de digitação passar
-- justamente por estar nos DOIS lugares. Uma fonte, lida duas vezes.
--
-- SEM `on commit drop`: o `migrar.py` roda a migration inteira numa transação só
-- (e aí o `drop` do fim é redundante, mas inofensivo), enquanto o CI aplica com
-- `psql -f` em autocommit — e ali `on commit drop` apagaria a tabela logo depois
-- do `insert`, antes de a conferência poder lê-la.

create temporary table par_pedido (ticker text, emissor text);

insert into par_pedido (ticker, emissor)
values
    ('AEGEBZ29', 'Aegea'),
    ('AEGEBZ31', 'Aegea'),
    ('AEGEBZ36', 'Aegea'),
    --: OS DOIS PREFIXOS DA SABESP, a razão de esta tabela existir.
    ('SBSPAB31', 'Sabesp'),
    ('SBSPAB36', 'Sabesp'),
    ('SABESP30', 'Sabesp'),
    ('ELEBRA30', 'Eletrobras'),
    ('ELEBRA35', 'Eletrobras'),
    ('LIGTBZ32', 'Light'),
    ('SIMHBZ31', 'Simpar'),
    ('MOVIBZ29', 'Movida'),
    ('MOVIBZ31', 'Movida'),
    ('MOVIBZ33', 'Movida'),
    ('VAMOBZ31', 'Vamos'),
    ('RAILBZ28', 'Rumo'),
    ('RAILBZ32', 'Rumo'),
    ('HIDRVS31', 'Hidrovias'),
    ('UGPABZ29', 'Ultrapar'),
    ('ACUPET32', 'Açu Petróleo'),
    ('BRASKM28', 'Braskem'),
    ('BRASKM30', 'Braskem'),
    ('BRASKM31', 'Braskem'),
    ('BRASKM50', 'Braskem'),
    ('RDEDOR30', 'Rede D''Or'),
    ('RDEDOR35', 'Rede D''Or'),
    ('RDEDOR36', 'Rede D''Or'),
    ('BEEFBZ31', 'Minerva'),
    ('BEEFBZ33', 'Minerva'),
    ('BEEFBZ36', 'Minerva'),
    ('PETBRA30', 'Petrobras'),
    ('PETBRA36', 'Petrobras');

insert into bond (ticker, emissor_id)
select p.ticker, e.id
  from par_pedido p
  join emissor e on e.nome = p.emissor;

-- -----------------------------------------------------------------------------
-- A CONFERÊNCIA DA PRÓPRIA MIGRATION
-- -----------------------------------------------------------------------------
-- `join` com `emissor` por NOME: se uma empresa acima estiver escrita de duas
-- formas, o `join` não casa e a linha do bond desaparece em SILÊNCIO — nenhum
-- erro, nenhum aviso, e o ticker simplesmente não existiria para a ingestão.
--
-- COMPARA O PAR, E NÃO A CONTAGEM — e esta frase é um conserto. A primeira
-- versão conferia três cardinalidades (15 empresas, 31 bonds, 3 da Aegea), e
-- uma revisão mostrou que isso não basta: trocar `BRASKM50` para Minerva e
-- `BEEFBZ36` para Braskem preserva os três números E a contagem de papéis de
-- cada empresa — Braskem continua com 4, Minerva com 3. O painel mostraria a
-- cotação de um bond sob a empresa errada, sem falha em lugar nenhum.
--
-- Comparar nos DOIS SENTIDOS: `pedido except gravado` pega o par que não entrou
-- (o `join` que não casou), e `gravado except pedido` pega o par que entrou
-- diferente do pedido. Um sentido só deixaria metade dos erros passar.

do $$
declare
  faltando text;
  sobrando text;
  aegea    integer;
begin
  select string_agg(ticker || '→' || emissor, ', ' order by ticker) into faltando
    from (
      select ticker, emissor from par_pedido
      except
      select b.ticker, e.nome from bond b join emissor e on e.id = b.emissor_id
    ) as q;

  select string_agg(ticker || '→' || emissor, ', ' order by ticker) into sobrando
    from (
      select b.ticker, e.nome as emissor from bond b join emissor e on e.id = b.emissor_id
      except
      select ticker, emissor from par_pedido
    ) as q;

  if faltando is not null then
    raise exception 'par pedido que não entrou: % — nome de empresa divergente?', faltando;
  end if;
  if sobrando is not null then
    raise exception 'par gravado que não foi pedido: %', sobrando;
  end if;

  --: A ÚNICA CARDINALIDADE QUE SOBRA, e ela afirma outra coisa: que a coluna
  --: `e_aegea` marca exatamente os três papéis da companhia. Isso não sai da
  --: comparação de pares acima, porque `par_pedido` não diz quem é a Aegea.
  select count(*) into aegea
    from bond b join emissor e on e.id = b.emissor_id
   where e.e_aegea;
  if aegea <> 3 then
    raise exception 'esperava 3 bonds marcados como Aegea, achou %', aegea;
  end if;
end
$$;

drop table par_pedido;
