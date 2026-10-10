--: A BITES INFORMA O SUBTEMA (N3), E A COLUNA DE ATRIBUTO DEIXA DE SER LIDA.
--:
--: A DECISÃO DE NEGÓCIO. O cadastro de assuntos guarda a árvore inteira e os
--: riscos, então uma planilha só precisa informar o N3 — o resto é consequência,
--: não escolha. Medido neste banco:
--:
--:     104 temas (N3) ativos, ZERO sem macro_tema (N2)
--:      41 macro_temas,       ZERO sem bloco_tema (N1)
--:     100 das 104 ligações tema -> risco já cadastradas
--:     `tema_nome_key`: o nome do N3 é ÚNICO, então casar por nome identifica
--:                      uma linha só — é o que torna "mande só o N3" seguro
--:
--: POR QUE A COLUNA `Atributo` SAI. Ela traz o N1 (os 7 blocos casam 100% nas
--: 2.886 linhas do arquivo de 01–09/2026), e o N1 derivado do N3 é o MESMO
--: dado por outro caminho. Manter os dois não é redundância inofensiva: eles
--: podem DISCORDAR, e aí a mesma menção tem dois N1 — o que o fornecedor
--: carimbou e o que o cadastro deriva —, sem ninguém saber qual a tela mostra.
--:
--: O FORNECEDOR VAI PARAR DE MANDAR a coluna, e até lá ela é IGNORADA: tirar
--: `atributo` do mapeamento faz exatamente isso, porque `colunas_necessarias`
--: nasce do que está mapeado. Com a coluna no arquivo ou sem ela, a subida
--: passa igual — nenhuma das duas formas precisa de aviso.
--:
--: `tema` FICA OPCIONAL pelo mesmo motivo. O conteúdo de `Categoria` vai ser
--: refeito no vocabulário do N3, e a primeira planilha sobe com a coluna VAZIA
--: por decisão de quem opera. Vazia o cabeçalho ainda existe; mas no dia em que
--: o fornecedor remover a coluna em vez de limpá-la, a subida não pode quebrar
--: por falta de um dado que já se sabe que não vem.
--:
--: E A ABA DEIXA DE SER EXIGIDA PELO NOME. O cadastro pedia `Posts`; o arquivo
--: de hoje chama a aba de `Planilha1` — o nome que o Excel dá por padrão — e a
--: subida era recusada antes de ler uma linha. Sem `aba` no mapeamento, o leitor
--: usa a PRIMEIRA aba, que é o que se quer num arquivo de aba única. Fixar
--: `Planilha1` seria pendurar a ingestão no nome padrão de um programa.
--:
--: NÃO MEXE EM MENÇÃO JÁ GRAVADA. As 81 menções da Bites que estão no banco
--: mantêm o atributo que tinham; o mapeamento vale da próxima subida em diante.
--:
--: Idempotente.

begin;

update score_fonte
   set mapeamento_colunas =
         (mapeamento_colunas - 'aba')
         || jsonb_build_object(
              'colunas', (mapeamento_colunas -> 'colunas') - 'atributo',
              'colunas_opcionais', '["tema"]'::jsonb
            )
 where codigo = 'bites';

do $$
declare
    tem_aba boolean;
    tem_atributo boolean;
    opcionais jsonb;
begin
    select mapeamento_colunas ? 'aba',
           (mapeamento_colunas -> 'colunas') ? 'atributo',
           mapeamento_colunas -> 'colunas_opcionais'
      into tem_aba, tem_atributo, opcionais
      from score_fonte
     where codigo = 'bites';

    if tem_aba is null then
        raise notice 'fonte bites não encontrada — nada a converter';
    elsif tem_aba or tem_atributo or opcionais <> '["tema"]'::jsonb then
        raise exception
            'conversão da bites não fechou: aba=%, atributo=%, opcionais=%',
            tem_aba, tem_atributo, opcionais;
    else
        raise notice 'bites lê a primeira aba, ignora Atributo e aceita Categoria ausente';
    end if;
end $$;

commit;
