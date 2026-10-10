--: O PERFIL DE QUEM FALA PASSA A VIR DO CARGO, NA BITES.
--:
--: O QUE ESTAVA ACONTECENDO. `mencao.perfil_autor` estava VAZIO nas 32.784
--: menções de TODAS as cinco fontes — e é a coluna que alimenta o gráfico
--: "Perfil de quem fala × sentimento" da lente e o KPI de figuras públicas.
--: Mais um campo que existia na tabela e nunca era escrito, como `tema_id`
--: (zero em 29.898) e `unidade_negocio_id` (zero em 32.784).
--:
--: E O DADO ESTAVA NA PLANILHA, na coluna `Cargo`, que a Bites já mandava e o
--: motor já lia para a régua de engajamento. Medido no arquivo de 01–09/2026:
--:
--:     379  deputado_estadual     47  comunicador      11  prefeitura
--:      78  imprensa              19  politico          6  empresa
--:      55  vereador              18  deputado_federal  5  perfil_de_twitter
--:
--: Ou seja: dá para ver quem fala — político, comunicador, imprensa — e a tela
--: mostrava nada.
--:
--: `perfil_autor` E `cargo` APONTAM PARA A MESMA COLUNA, de propósito, e é
--: isso que o motor lê como "nesta fonte, o perfil de quem fala é o cargo":
--: `cargo` vira CÓDIGO para a régua de peso (`deputado_estadual`), e
--: `perfil_autor` vira RÓTULO para a tela ("Deputado estadual"). Duas
--: leituras da mesma célula, cada uma no formato de quem a consome.
--:
--: E O RÓTULO DOBRA AS GRAFIAS: o fornecedor manda `Vereador` (55) e
--: `Vereadora` (4), `Deputado Estadual` (379) e `Deputada Estadual` (1), e
--: ainda `Verador` (1) — erro de digitação. Sem dobrar, o gráfico mostrava o
--: mesmo cargo em duas barras e a régua dava peso 1 à vereadora e 2 ao
--: vereador. A dobra mora em `CARGO_CANONICO`, no domínio.
--:
--: OPCIONAL, como as demais colunas desta fonte: um mês sem `Cargo` não pode
--: derrubar a subida.
--:
--: NÃO MEXE NO QUE JÁ ESTÁ GRAVADO: o mapeamento vale da próxima subida. As
--: 2.886 menções de hoje continuam com `perfil_autor` nulo até resubir — e
--: resubir substitui os nove meses.
--:
--: Idempotente.

begin;

update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas,
         '{colunas}',
         (mapeamento_colunas -> 'colunas')
           || jsonb_build_object('perfil_autor', 'Cargo')
       )
 where codigo = 'bites';

update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas,
         '{colunas_opcionais}',
         '["tema", "link", "titulo_texto", "autor", "uf", "veiculo", "perfil_autor"]'::jsonb
       )
 where codigo = 'bites';

do $$
declare
    colunas jsonb;
    opcionais jsonb;
begin
    select mapeamento_colunas -> 'colunas', mapeamento_colunas -> 'colunas_opcionais'
      into colunas, opcionais
      from score_fonte
     where codigo = 'bites';

    if colunas is null then
        raise notice 'fonte bites não encontrada — nada a converter';
    elsif colunas ->> 'perfil_autor' <> 'Cargo'
       or colunas ->> 'cargo' <> 'Cargo'
       or not (opcionais ? 'perfil_autor') then
        raise exception
            'conversão da bites não fechou: perfil_autor=%, cargo=%, opcionais=%',
            colunas ->> 'perfil_autor', colunas ->> 'cargo', opcionais;
    else
        raise notice 'a Bites diz o perfil de quem fala pelo cargo';
    end if;
end $$;

commit;
