--: A UF DA MENÇÃO PASSA A SER O NOME DO ESTADO, E CINCO COLUNAS VIRAM OPCIONAIS.
--:
--: Duas decisões do dono do produto (09/10/2026), e as duas corrigem escolhas
--: que eu havia feito na `0063`.
--:
--: ## 1. `mencao.uf` de `char(2)` para `text`
--:
--: "Pode subir a uf sem ser sigla, pode ser o nome completo do estado."
--:
--: A `0063` traduzia "Santa Catarina" para `SC` porque a coluna não aceitava
--: mais que duas letras. Agora aceita, e o nome é a forma canônica — quem manda
--: sigla converge para o nome (ver `para_uf`), para `SC` e `Santa Catarina` não
--: virarem duas opções de filtro do mesmo estado.
--:
--: ISSO NÃO QUEBRA FILTRO, e foi verificado antes: as opções de UF da lente saem
--: do PRÓPRIO DADO (`_distintos(Mencao.uf)`) e o recorte compara por igualdade.
--: A validação contra as 27 siglas (`ABRANGENCIAS_VALIDAS`) é de `Recorte`, o
--: filtro do CRM sobre `interacao.uf` — outra coluna, outra dimensão, mesmo
--: nome. `interacao.uf` e `instituicao.uf` NÃO mudam.
--:
--: GANHO COLATERAL: o que não é estado brasileiro deixa de ser achatado em `IN`.
--: A Clipei trouxe uma linha de "Comunidade de Madrid" nestes dois meses, e o
--: nome diz mais do que "internacional".
--:
--: As 4.392 menções existentes têm `uf` nulo (medido), então não há dado a
--: converter — `char(2)` para `text` é alargamento, e o Postgres o faz sem
--: reescrever a tabela.
--:
--: ## 2. Cinco colunas da Clipei viram opcionais
--:
--: "Pode ter casos sem link."
--:
--: Mapear uma coluna a tornava EXIGIDA: faltando no arquivo, a subida inteira
--: para com o nome dela na mensagem. Isso é certo para `Data` e `Classificação`
--: — sem elas não há menção — e duro demais para enriquecimento: 25 mil menções
--: paradas porque o fornecedor renomeou a coluna do link.
--:
--: `colunas_opcionais` é declarado NO CADASTRO, como o resto do mapeamento, e o
--: padrão continua sendo "mapeada é exigida". `data` e `sentimento` nunca entram
--: aqui, mesmo se alguém os declarar — `colunas_necessarias` os reexige.
--:
--: CÉLULA VAZIA JÁ FUNCIONAVA: uma linha sem link grava nulo e entra igual. O
--: que esta migration resolve é a COLUNA ausente, não a célula.
--:
--: Idempotente nas duas partes.

begin;

-- 1. a coluna aceita o nome do estado
alter table mencao
  alter column uf type text using nullif(trim(uf), '');

-- 2. as cinco de enriquecimento podem faltar no arquivo
update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas::jsonb,
         '{colunas_opcionais}',
         '["id_fonte", "link", "titulo_texto", "uf", "unidade"]'::jsonb
       )
 where codigo in ('clipei', 'clipei_investidores');

do $$
declare
    tipo text;
    sem_opcionais int;
begin
    select data_type into tipo
      from information_schema.columns
     where table_name = 'mencao' and column_name = 'uf';
    if tipo <> 'text' then
        raise exception 'mencao.uf ficou como % em vez de text', tipo;
    end if;

    select count(*) into sem_opcionais
      from score_fonte
     where codigo in ('clipei', 'clipei_investidores')
       and not (mapeamento_colunas::jsonb ? 'colunas_opcionais');
    if sem_opcionais > 0 then
        raise exception
            '% fontes da Clipei ficaram sem colunas_opcionais', sem_opcionais;
    end if;
end $$;

commit;
