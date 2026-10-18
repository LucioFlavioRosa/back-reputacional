-- =============================================================================
-- A CONCESSIONÁRIA DA MENÇÃO PASSA A VIR DO CADASTRO CENTRAL
-- =============================================================================
--
-- O QUE ESTAVA ACONTECENDO. `mencao.unidade_negocio_id` existe desde a `0048` e
-- estava preenchido em ZERO das 104.670 menções. A dimensão "Concessionária"
-- das lentes agrupa pelo TEXTO do fornecedor (`unidade_texto`), e o mesmo
-- operação chega em grafias diferentes:
--
--     Corsan .......... "Corsan" (1.111) + "Companhia Riograndense de
--                       Saneamento (Corsan)" (15.019)   -> DUAS barras
--     Holding ......... "Holding" (1.411) + "Aegea Saneamento e Participações
--                       S/A" (7.258)                     -> DUAS barras
--     Gov. Valadares .. "Águas de Valadares" (905) + "Água de Valadares" (1)
--
-- Recortar por uma grafia perde a outra. Do outro lado, a agenda do CRM
-- (`interacao.unidade_negocio_id`) usa o cadastro em todas as linhas, e o
-- alcance de cada pessoa é concedido POR NOME DE UNIDADE
-- (`filtros_sql.condicoes_de_escopo`): são as duas metades da mesma companhia
-- sem uma chave em comum.
--
-- A MEDIÇÃO, 18/10/2026, sobre as 104.670 menções:
--
--     104.633 trazem `unidade_texto` (99,96%), em 65 grafias, contra 29
--     unidades no cadastro.
--
--         bate exato com o cadastro ....  12 grafias   51.490   49,2%
--         apelido inequívoco ..........    5 grafias   24.594   23,5%
--         família com mais de um membro    3 grafias   14.703   14,1%
--         não existe no cadastro ......   45 grafias   13.846   13,2%
--
-- POR QUE UMA TABELA DE APELIDO, E NÃO MAIS UMA UNIDADE. "Companhia
-- Riograndense de Saneamento (Corsan)" não pode ser a 30ª linha de
-- `unidade_negocio`: ela duplicaria a Corsan no cadastro que o CRM usa e pelo
-- qual o alcance é concedido. E não pode ir para o `apelidos` do
-- `mapeamento_colunas` por duas razões: ele é POR FONTE (o mesmo nome chega
-- pela `clipei` e pela `clipei_investidores`) e ele REESCREVE `unidade_texto`,
-- apagando a palavra do fornecedor — que é contra o que a carga é auditável.
--
-- O QUE ESTA MIGRATION NÃO FAZ
-- ----------------------------
--
-- NÃO LIGA AS MENÇÕES QUE JÁ ESTÃO NA BASE. Isso é o comando
-- `app/comandos/ligar_mencoes_a_concessionaria.py`, e é comando e não SQL pela
-- mesma razão da `0098`: resolver aqui exigiria reimplementar `normalizar` em
-- SQL, e a `0097` já pagou esse preço (divergiu em 67 de 87 valores reais).
--
-- NÃO ADIVINHA BLOCO. "Águas do Rio" (9.411 menções) corresponde a DUAS linhas
-- do cadastro e "Águas do Pará" (4.267) a QUATRO. Nenhuma liga, e é de
-- propósito: escolher um bloco por ordem ou por volume inventaria um dado que a
-- planilha não tem, e ele sairia depois num relatório por concessionária como
-- se fosse informação. A conferência da subida passa a mostrar os três nomes
-- com as opções do cadastro ao lado.
--
-- NÃO CONCEDE `delete` A `painel_app`, e isto é decisão e não esquecimento — a
-- `0092` esqueceu e a `0093` existiu só para consertar. O aplicativo LÊ os
-- apelidos; quem os declara hoje é esta migration. No dia em que houver tela
-- para administrá-los, o `grant` entra com ela. O `insert/select/update` vem do
-- default ACL do schema, como em toda tabela nova.
-- =============================================================================

begin;

create table if not exists unidade_negocio_apelido (
    --: A CHAVE É O NOME JÁ NORMALIZADO (`dominio/texto.normalizar`: minúscula,
    --: sem acento, espaço colapsado) — a mesma com que `unidade_da_mencao`
    --: procura. Guardá-la pronta torna a busca um `dict.get` em vez de uma
    --: função sobre cada linha, e sendo PRIMÁRIA ela declara a invariante: duas
    --: grafias que normalizam igual são uma entrada, não duas.
    --:
    --: `tests/test_unidade_da_mencao.py::test_a_chave_semeada_e_a_que_o_codigo_calcula`
    --: confere cada linha abaixo contra a função de verdade. Sem ele, um acento
    --: digitado errado aqui viraria um apelido que nunca casa — e o sintoma
    --: seria 15.019 menções sem concessionária, não um erro.
    nome_normalizado  text     primary key,
    --: A grafia como o fornecedor escreve, para a tela mostrar o que foi
    --: declarado em vez da chave achatada.
    nome              text     not null,
    unidade_negocio_id smallint not null references unidade_negocio (id)
);

--: OS CINCO APELIDOS INEQUÍVOCOS, com o volume medido em 18/10/2026.
--:
--: INEQUÍVOCO QUER DIZER "uma linha do cadastro e nenhuma dúvida sobre qual":
--: a razão social da Corsan é a Corsan, e a Aegea Saneamento e Participações
--: S/A é a holding. Os três nomes AMBÍGUOS (Águas do Rio, Águas do Pará,
--: Ambiental Ceará) NÃO estão aqui de propósito — ver acima.
--:
--: `on conflict do nothing`: a migration roda em ambiente que já pode ter a
--: linha, e repetir não é erro.
insert into unidade_negocio_apelido (nome_normalizado, nome, unidade_negocio_id)
select v.chave, v.nome, u.id
  from (values
    -- 15.019 menções (clipei + clipei_investidores)
    ('companhia riograndense de saneamento (corsan)',
     'Companhia Riograndense de Saneamento (Corsan)', 'Corsan'),
    -- 7.258 menções (clipei + clipei_investidores)
    ('aegea saneamento e participacoes s/a',
     'Aegea Saneamento e Participações S/A',          'Holding / corporativo'),
    -- 1.411 menções (bites; o `mapeamento_colunas` dela já dobra "Aegea" aqui)
    ('holding',             'Holding',               'Holding / corporativo'),
    -- 905 menções (clipei + clipei_investidores)
    ('aguas de valadares',  'Águas de Valadares',    'Águas de Governador Valadares'),
    -- 1 menção (bites) — entra porque custa uma linha e some do relatório
    ('agua de valadares',   'Água de Valadares',     'Águas de Governador Valadares')
  ) as v (chave, nome, unidade)
  join unidade_negocio u on u.nome = v.unidade
    on conflict (nome_normalizado) do nothing;

--: O RECORTE POR CONCESSIONÁRIA, pelo mesmo desenho dos índices da `0098`:
--: parcial, porque a coluna nasce nula na maioria das linhas até o comando
--: rodar, e por `(mes, ...)` porque toda leitura das lentes recorta o mês
--: primeiro.
create index if not exists mencao_por_concessionaria
  on mencao (mes, unidade_negocio_id) where unidade_negocio_id is not null;

commit;
