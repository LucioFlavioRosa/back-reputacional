--: O SUBTEMA DA BITES VEM DA COLUNA `N3`, e não mais de `Categoria`.
--:
--: O QUE MUDOU DO LADO DO FORNECEDOR. A Bites refez a engenharia da planilha e
--: entregou `Bites-Planilha-Consolidada-Aegea-Jan-a-Set-2026.xlsx` com TRÊS
--: colunas explícitas — `N1`, `N2` e `N3` —, que é exatamente a taxonomia do
--: cadastro de assuntos.
--:
--: CONFERIDO CONTRA O CADASTRO, linha por linha, com a mesma função
--: `normalizar` que a ingestão usa:
--:
--:   * N1: 7 valores distintos, os 7 casam com os 7 blocos — 2.413 linhas;
--:   * N2: 40 valores distintos, os 40 casam com os macro temas — 2.413 linhas;
--:   * N3: 92 valores distintos, os 92 casam com temas ATIVOS — 2.384 linhas;
--:   * e as três colunas CONCORDAM ENTRE SI segundo o cadastro: nas 2.384
--:     linhas com N3, zero divergência de N2 e zero de N1.
--:
--: POR QUE `N3` E SÓ ELE. O N3 determina N2, N1 e os riscos pelo cadastro —
--: decisão do dono do produto. Ler as três colunas seria guardar a mesma
--: afirmação três vezes, com três chances de divergir. E a divergência não é
--: hipótese: nesta planilha a coluna `Atributo` CONTRADIZ a `N1` em 1.418 das
--: 2.842 linhas (metade), com casos como `Atributo = Eficiência Operacional e
--: Qualidade` sobre `N1 = Governança`. É a razão de `Atributo` seguir ignorada.
--:
--: `Categoria` SAI DE CENA, e é o que esta migration conserta: ela continua no
--: arquivo, preenchida em 442 linhas, e 52 dos seus valores trazem VÁRIOS
--: assuntos numa célula ("Abastecimento, Agência de Regulação, Proteção
--: ambiental"). Como chave de tema isso não serve: a ingestão procuraria no
--: cadastro um assunto chamado "Abastecimento, Agência de Regulação, ..." e não
--: acharia nenhum. Apontada para `N3`, a mesma ingestão liga 2.384 das 2.842
--: linhas — 84%.
--:
--: E ESSES NÚMEROS SÃO DA TELA, não da planilha crua — a revisão duvidou, com
--: razão, porque o código ainda dizia que a Bites perde 1.426 linhas por
--: sentimento ilegível. Perdia, NO ARQUIVO ANTERIOR. A conferência do arquivo
--: consolidado, rodada na pilha pela rota real, devolveu: 2.842 linhas, 2.842
--: ingeridas, descartes zero, `mencoes_com_tema` 2.384, `mencoes_sem_assunto`
--: 458 e `assuntos_nao_reconhecidos` vazio. O consolidado trouxe sentimento em
--: todas as linhas.
--:
--: AS 458 LINHAS SEM N3 ficam sem assunto, e isso é o retrato honesto do
--: arquivo: 429 não têm nível nenhum e 29 têm só o N1. Menção sem assunto conta
--: para a nota e não aparece em recorte por tema — e a conferência diz o número
--: antes de confirmar.
--:
--: O QUE ESTA MIGRATION NÃO FAZ, de propósito: não mapeia `Rede Social`,
--: `Cidade` nem `Seguidores`, que são colunas novas sem campo correspondente na
--: menção; não mexe no vocabulário de cargo; e não liga a unidade de negócio,
--: que é outra conversa — o fornecedor manda a MARCA ("Águas do Rio") e o
--: cadastro guarda o CONTRATO ("Águas do Rio 1", "Águas do Rio 4"), então 20
--: dos 29 valores não casam por nome.
--:
--: E UM AVISO QUE A REVISÃO ARRANCOU DAQUI: `Abrangência` NÃO é mapeamento de
--: cadastro, mas É LIDA, por nome fixo (`COLUNA_DA_ABRANGENCIA`, em
--: `ingerir_mencoes.py`), e define a `esfera` de todo perfil que nascer nesta
--: subida — "Regional" na deputada Stela Farias, conferido na conferência do
--: arquivo real. O formato anterior não trazia a coluna; o consolidado traz, em
--: 442 linhas. Não é efeito desta migration, e sim do arquivo novo encontrando
--: código que já existia — mas quem ler este cabeçalho tem de saber.
--:
--: Idempotente: escreve o valor final, não um incremento.

begin;

update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas,
         '{colunas,tema}',
         '"N3"'::jsonb
       )
 where codigo = 'bites';

do $$
declare
    existe boolean;
    de_onde text;
begin
    select true, mapeamento_colunas #>> '{colunas,tema}' into existe, de_onde
      from score_fonte where codigo = 'bites';

    --: SEM A FONTE, NÃO HÁ O QUE CONVERTER, e a migration não pode derrubar a
    --: aplicação: o CI aplica todas em sequência com `ON_ERROR_STOP=1`, e um
    --: banco novo que ainda não semeou `score_fonte` morreria aqui. Mesma
    --: disciplina da `0069`, `0070`, `0071` e `0075`. Achado de revisão: a
    --: versão anterior comparava o nulo com 'N3', dava verdadeiro e levantava
    --: exceção dizendo "veio de <NULL>" — mandando procurar defeito na coluna.
    if existe is null then
        raise notice 'fonte bites não encontrada — nada a converter';
    elsif de_onde is distinct from 'N3' then
        raise exception 'o tema da bites deveria vir de N3, e veio de %', de_onde;
    else
        raise notice 'bites: o subtema passa a vir da coluna %', de_onde;
    end if;
end $$;

commit;
