--: A LENTE MERCADO PASSA A RECORTAR PELA LISTA DE VEÍCULOS DO CADASTRO.
--:
--: COMO ERA. `clipei_investidores` lia o export da Clipei e guardava as linhas
--: com `Público-alvo = Investidores` — uma coluna que o FORNECEDOR preenche,
--: pelo critério dele.
--:
--: O QUE ISSO CUSTAVA, medido contra o export de 08–09/2026: a coluna captura
--: **80 linhas** onde a lista de veículos do mercado financeiro que a Aegea
--: mantém captura **323**. Os dois critérios discordam em 267 das 335 linhas
--: envolvidas, e o da coluna perde Valor Econômico (49 menções), InfoMoney
--: (25), Expert XP (20) e Times Brasil (15) — que entravam só na Imprensa.
--: Como a lente Mercado vale 20% do índice, isso é um quinto do ISR alimentado
--: por um recorte que ninguém daqui decide.
--:
--: COMO FICA. O recorte é a subcategoria de público do veículo no cadastro
--: compartilhado — "Econômica e de negócios" da Imprensa —, mantida na aba
--: Base dos KPIs. Quem decide quem é veículo de investidor passa a ser a
--: Aegea, por tela, e não a planilha que chega.
--:
--: `lista_de_veiculos` É UM NOME, e não o par (categoria, subcategoria): o
--: motor só sabe que a lista existe, e a tradução para o cadastro mora em
--: `casos_de_uso/veiculos_da_imprensa.LISTAS_DE_VEICULOS`. Um nome que o motor
--: não conheça faz o cadastro da fonte FALHAR na leitura, em vez de produzir um
--: recorte vazio que ninguém sabe explicar.
--:
--: A COLUNA `Público-alvo` CONTINUA MAPEADA, e é de propósito: o dado é bom
--: (`mencao.publico_alvo` alimenta filtro do dossiê), e o que se aposentou foi
--: o papel dela de DECIDIR a lente. Ela sai de `filtros`, não de `colunas`.
--:
--: NADA MUDA NOS MESES JÁ GRAVADOS. A ingestão é que recorta, então o novo
--: critério vale a partir da PRÓXIMA subida de cada mês — resubir o arquivo de
--: um mês é o que o aplica àquele mês, e isso é decisão de quem opera, não
--: efeito colateral de uma migration.
--:
--: Idempotente.

begin;

update score_fonte
   set mapeamento_colunas =
         (mapeamento_colunas - 'filtros')
         || jsonb_build_object('lista_de_veiculos', 'imprensa_economica')
 where codigo = 'clipei_investidores';

do $$
declare
    recorte text;
    tem_filtro boolean;
begin
    select mapeamento_colunas ->> 'lista_de_veiculos',
           mapeamento_colunas ? 'filtros'
      into recorte, tem_filtro
      from score_fonte
     where codigo = 'clipei_investidores';

    if recorte is null then
        --: A fonte não existe nesta base (ou não foi semeada): não há o que
        --: converter, e parar aqui impediria o banco de subir.
        raise notice 'clipei_investidores não encontrada — nada a converter';
    elsif recorte <> 'imprensa_economica' or tem_filtro then
        raise exception
            'conversão da lente Mercado não fechou: lista=%, ainda tem filtros=%',
            recorte, tem_filtro;
    else
        raise notice 'lente Mercado recortando por lista de veiculos';
    end if;
end $$;

commit;
