--: A BITES PASSA A TRAZER LINK, TEXTO, AUTOR E UF.
--:
--: O QUE ESTAVA ACONTECENDO. A lente Sociedade digital tem um bloco "Menções
--: do mês" que lista as linhas uma a uma com Texto, Link, Autor, Perfil do
--: autor e Engajamento — e ele só mostra linha QUE TEM TEXTO
--: (`app/api/lentes.py`, `_mencoes_de_rede`). O mapeamento da fonte não lia
--: nenhuma dessas colunas, então as 2.886 menções entraram com todos esses
--: campos nulos e a tabela ficava VAZIA. Quem abria a lente via a nota e os
--: gráficos, e nenhuma menção para clicar.
--:
--: E A PLANILHA JÁ TRAZ TUDO, medido no arquivo de 01–09/2026:
--:
--:     Link      2886/2886   o endereço do post
--:     Texto     2877/2886   o conteúdo, que é o que a tabela exibe
--:     Autor     2626/2886   quem postou
--:     Estado    1422/2886   a UF, em sigla
--:
--: `uf` ENTRA PELO `para_uf`, que converte a sigla para o nome por extenso —
--: a decisão de 09/10/2026 é que `mencao.uf` guarda "Santa Catarina", e não
--: "SC", porque é o que o filtro mostra. A conversão é do motor, não desta
--: migration.
--:
--: TODAS OPCIONAIS, de propósito. A mesma lição da `0064`: coluna que o
--: fornecedor pode deixar de mandar não pode derrubar a subida inteira. Se um
--: mês vier sem `Autor`, as menções entram sem autor — e não se perde o mês.
--:
--: NÃO MEXE NO QUE JÁ ESTÁ GRAVADO. O mapeamento é lido na INGESTÃO: as 2.886
--: menções que subiram antes desta migration continuam sem link até alguém
--: resubir o arquivo. Resubir substitui os nove meses e preenche tudo.
--:
--: O QUE NÃO ENTROU, e por que:
--:
--: `Rede Social` (Instagram, Facebook...) e `Cargo` disputam o campo
--: `perfil_autor`, que alimenta o gráfico "Perfil de quem fala × sentimento".
--: Pelo nome do gráfico, o perfil é o CARGO (Deputado Estadual, Imprensa,
--: Comunicador) — mas o cargo vem vazio em 78% das linhas, e a rede social em
--: nenhuma. São duas respostas defensáveis, e a escolha é do dono do produto.
--:
--: `veiculo` NÃO é mapeado. Seria tentador apontá-lo para `Rede Social`, mas
--: `mencao.veiculo` é o que liga a menção ao veículo do Cadastro compartilhado
--: e o que define a lente Mercado: "Instagram" apareceria na conferência como
--: veículo a cadastrar, e um dia entraria na lista de imprensa econômica.
--:
--: Idempotente.

begin;

update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas,
         '{colunas}',
         (mapeamento_colunas -> 'colunas')
           || jsonb_build_object(
                'link', 'Link',
                'titulo_texto', 'Texto',
                'autor', 'Autor',
                'uf', 'Estado'
              )
       )
 where codigo = 'bites';

--: AS NOVAS ENTRAM COMO OPCIONAIS, somando-se ao `tema` que a `0069` já pôs.
update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas,
         '{colunas_opcionais}',
         '["tema", "link", "titulo_texto", "autor", "uf"]'::jsonb
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
    elsif colunas ->> 'link' <> 'Link'
       or colunas ->> 'titulo_texto' <> 'Texto'
       or colunas ->> 'autor' <> 'Autor'
       or colunas ->> 'uf' <> 'Estado'
       or not (opcionais ? 'link' and opcionais ? 'tema') then
        raise exception
            'conversão da bites não fechou: colunas=%, opcionais=%', colunas, opcionais;
    else
        raise notice 'bites lê link, texto, autor e uf — todas opcionais';
    end if;
end $$;

commit;
