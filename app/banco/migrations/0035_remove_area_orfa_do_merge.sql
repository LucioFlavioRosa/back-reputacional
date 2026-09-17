-- =============================================================================
-- 0035 — Remove a tabela `area`, órfã de uma tentativa de migration abortada.
--
-- CONTEXTO: a integração de hoje descobriu que um merge anterior (`ca5d13c`)
-- descartou por engano as migrations originais de `area_pessoa` +
-- `interacao_area` (0029_area_do_representante.sql, 0032_interacao_area.sql,
-- 0033_area_performance_e_dados_desativada.sql — já aplicadas em produção há
-- dias, com dados reais de demonstração já validados) em favor de uma
-- implementação paralela e independente (`0029_area_interna.sql`, tabela
-- `area`, outras categorias) que outra pessoa construiu sem saber da
-- primeira. Decisão tomada: `area_pessoa` é o modelo correto, e os três
-- arquivos originais voltaram com o nome e o conteúdo exatos de quando
-- rodaram pela primeira vez — o rastreamento de migration por nome de
-- arquivo os reconhece como já aplicados e não tenta rodá-los de novo.
--
-- `0029_area_interna.sql` NÃO era transacional, e quebrou no meio: o
-- `create table interacao_area` dela bateu de frente com a tabela homônima
-- do modelo antigo, que já existia. Isso deixa, em qualquer ambiente onde
-- ela rodou e falhou assim, uma tabela `area` órfã — criada, com cinco
-- linhas de semente, mas nunca chegou a ligar nada a ela, porque a criação
-- de `interacao_area` falhou ANTES disso. `pessoa_aegea.area_id` também não
-- foi afetado: a coluna já existia (do 0029 antigo), e o
-- `add column if not exists` dela foi um no-op.
--
-- SEGURANÇA — não apaga às cegas: antes de derrubar `area`, confere se
-- `interacao_area` tem alguma FK apontando para ela. Se tiver, é sinal de
-- que ESTE ambiente completou a migration abortada por inteiro, com
-- `interacao_area` já no modelo novo — nesse caso pode haver vínculo de
-- verdade lá dentro, e a migration PARA com um erro em vez de decidir
-- sozinha o que fazer com esse dado.
--
-- Idempotente: se `area` não existir (ambiente que nunca rodou a migration
-- abortada, ou que já foi limpo por esta mesma migration antes), não faz
-- nada.
-- =============================================================================

begin;

do $$
begin
  if not exists (select 1 from pg_tables where tablename = 'area') then
    return;
  end if;

  if exists (
    select 1 from pg_constraint
    where conrelid = 'interacao_area'::regclass
      and contype = 'f'
      and confrelid = 'area'::regclass
  ) then
    raise exception
      'interacao_area tem uma FK apontando para "area" -- este ambiente pode '
      'ter completado a migration abortada (0029_area_interna.sql) por '
      'inteiro, com vinculos de verdade no modelo novo. Nao apagando "area" '
      'as cegas -- reconcilie manualmente antes de rodar esta migration.';
  end if;

  drop table area;
end $$;

-- Cosmético: `0029_area_interna.sql` sobrescreveu o comentário desta coluna
-- antes de quebrar (COMMENT ON COLUMN não depende de `interacao_area`).
-- Devolve o texto original — não afeta nenhum comportamento, só a leitura de
-- quem inspeciona o schema.
comment on column pessoa_aegea.area_id is
  'A área de quem representa a Aegea. Nula em quem foi cadastrado antes desta coluna existir.';

commit;
