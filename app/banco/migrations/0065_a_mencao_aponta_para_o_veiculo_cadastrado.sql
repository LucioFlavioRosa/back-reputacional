--: A MENÇÃO PASSA A APONTAR PARA O VEÍCULO CADASTRADO.
--:
--: A terceira ponte para o cadastro compartilhado, e a única que nem coluna
--: tinha. As outras duas existem e ninguém atravessa — medido em 4.392 menções:
--:
--:     mencao.tema_id           -> tema              0 preenchidas
--:     mencao.unidade_negocio_id -> unidade_negocio  0 preenchidas
--:     o veículo                 -> instituicao      não havia coluna
--:
--: POR QUE `instituicao` E NÃO UMA TABELA DE VEÍCULOS. O cadastro compartilhado
--: já modela isto inteiro, e foi o dono do produto quem apontou: `instituicao`
--: tem `tipo = 'veiculo'` (39 cadastrados hoje, todos como Imprensa),
--: `categoria_publico_id`, `subcategoria_publico_id` e `esfera_id`. Criar tabela
--: paralela seria um segundo vocabulário de veículo para a mesma empresa — e o
--: CRM e o Score passariam a discordar sobre quem é a Folha de S.Paulo.
--:
--: A SUBCATEGORIA É O CRITÉRIO DA LENTE MERCADO. "Econômica e de negócios" já
--: existe em `subcategoria_publico` sob Imprensa, cuja `padrao_de_quebra` é
--: literalmente `logica_editorial`. Hoje a lente `clipei_investidores` se
--: separa por `Público-alvo = Investidores`, o que captura 80 linhas quando
--: deveria capturar 323 — medido contra a lista de veículos do mercado
--: financeiro que o dono do produto mantém. Com esta coluna, o critério passa a
--: ser o cadastro, e a lista se mantém pela tela.
--:
--: `ON DELETE SET NULL`, E NÃO CASCADE. Apagar um veículo do cadastro não pode
--: apagar a menção: ela é fato do mês, aconteceu, e o vínculo é enriquecimento.
--: Cascade aqui faria uma limpeza de cadastro sumir com histórico de imprensa.
--:
--: O ÍNDICE É PARCIAL, como o de `tema_id`: a maioria das menções fica sem
--: vínculo por um bom tempo (a Clipei traz 2.648 veículos distintos e o cadastro
--: tem 39), e indexar nulo é indexar o que não se consulta.
--:
--: Idempotente.

begin;

alter table mencao
  add column if not exists instituicao_id uuid references instituicao(id) on delete set null;

create index if not exists mencao_por_veiculo_cadastrado
    on mencao (instituicao_id)
 where instituicao_id is not null;

do $$
begin
    if not exists (
        select 1 from information_schema.columns
         where table_name = 'mencao' and column_name = 'instituicao_id'
    ) then
        raise exception 'mencao.instituicao_id nao foi criada';
    end if;
end $$;

commit;
