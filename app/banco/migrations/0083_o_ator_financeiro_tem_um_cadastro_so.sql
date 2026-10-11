--: O ATOR FINANCEIRO TEM UM CADASTRO SÓ: o veículo homônimo funde no investidor.
--:
--: A PERGUNTA QUE ORIGINOU ISTO, do dono do produto: "o fato de cadastrar alguma
--: instituição como investidor ou veículo não impede que ele seja visto em
--: qualquer uma das fontes cadastradas, como Clipei e Bites?"
--:
--: IMPEDIA, NUMA DIREÇÃO. A busca de `veiculos_da_imprensa.reconhecer` filtrava
--: pelo tipo da fonte, então para a Clipei só um cadastro `veiculo` contava — um
--: `investidor` de mesmo nome era invisível, o nome virava novo, e a ingestão
--: criava um SEGUNDO cadastro. A Bites nunca teve o problema: ela busca em
--: qualquer tipo, e 53 menções dela estão em cadastros `veiculo`.
--:
--: A INGESTÃO JÁ FOI CORRIGIDA (`TIPOS_DO_MESMO_ATOR`: `investidor` e `credor`
--: entram; `orgao`, `proposicao`, `entidade` e `area_interna` ficam fora, porque
--: ali o homônimo é real). Esta migration limpa o que a versão antiga gravou.
--:
--: MEDIDO NA BASE DA PILHA, e são dois pares:
--:
--:     BTG Pactual     investidor   12 agendas   0 menções   tier 3
--:     BTG Pactual     veiculo       0 agendas   4 menções   sem tier
--:     Fitch Ratings   investidor   11 agendas   0 menções   tier 1
--:     Fitch Ratings   veiculo       0 agendas   2 menções   sem tier
--:
--: A divisão é exata: o CRM num cadastro, a imprensa no outro, e nenhuma tela
--: junta. Quem abre o BTG vê 12 reuniões e nenhuma menção, ou 4 menções e nenhuma
--: reunião, dependendo de qual dos dois abriu.
--:
--: QUEM SOBREVIVE É O INVESTIDOR, e esta foi decisão do dono do produto com o
--: custo na mesa. É o oposto da `0077`, onde o veículo sobreviveu — e a razão é
--: outra: lá o perfil de rede era a linha crua da ingestão e o veículo a curada;
--: aqui as duas são curadas, e o investidor é a que carrega o trabalho humano:
--: 23 agendas, o tier, e a categoria "Mercado Financeiro e de Capitais".
--:
--: O QUE SE PERDE, DITO EM VOZ ALTA porque é real e foi aceito: BTG Pactual e
--: Fitch Ratings SAEM da lente Mercado. A lista dela é `tipo = 'veiculo'` mais o
--: par (categoria "Imprensa", subcategoria "Econômica e de negócios") — ver
--: `nomes_da_lista` e `api/score.py` —, e o cadastro sobrevivente não é veículo
--: nem está nessa subcategoria. A lista cai de 81 para 79 veículos, e as 6
--: menções deles deixam de contar nela.
--:
--: E A CAUSA DISSO NÃO É O CÓDIGO: a taxonomia não tem lugar para um ator que é
--: imprensa E investidor. Um cadastro guarda UM par (categoria, subcategoria), e
--: a lista da lente é definida por esse par. Tirar a lista da taxonomia — uma
--: marca própria no cadastro — é o que resolveria sem perda, e é mudança de
--: desenho que fica registrada aqui para quando alguém a quiser.
--:
--: FUNDE, E NÃO DESATIVA. Desativar o veículo deixaria as 6 menções apontando
--: para um cadastro fora de circulação: o dossiê do ator continuaria partido, com
--: metade invisível. Mover as menções é o que junta o ator.

begin;

drop table if exists par_financeiro;

--: SÓ OS PARES EM QUE O OUTRO LADO É ATOR FINANCEIRO. `TIPOS_DO_MESMO_ATOR`, no
--: código, é a mesma lista — e ela é curta de propósito: um nome de jornal igual
--: ao de uma prefeitura é HOMÔNIMO, e fundir os dois apontaria a matéria do jornal
--: para o órgão.
create temporary table par_financeiro on commit drop as
select v.id as veiculo, f.id as financeiro, f.tipo as tipo_que_fica
  from instituicao v
  join instituicao f
    on f.nome_normalizado = v.nome_normalizado
   and f.tipo in ('investidor', 'credor')
 where v.tipo = 'veiculo';

--: TRÊS LADOS OU MAIS NÃO SE FUNDE SOZINHO. Com dois investidores de mesmo nome,
--: ou dois veículos, não há como saber qual é o ator — e escolher errado espalha
--: as menções no cadastro errado. Fica para quem administra.
delete from par_financeiro
 where veiculo in (
         select veiculo from par_financeiro group by veiculo having count(*) > 1
       )
    or financeiro in (
         select financeiro from par_financeiro group by financeiro having count(*) > 1
       );

--: AS MENÇÕES PASSAM PARA O SOBREVIVENTE — é o que junta o dossiê do ator.
update mencao m
   set instituicao_id = p.financeiro
  from par_financeiro p
 where m.instituicao_id = p.veiculo;

--: E O QUE MAIS APONTA PARA INSTITUIÇÃO. As agendas já estão no investidor e os
--: interlocutores são zero hoje nos dois lados; sem estes dois `update` a exclusão
--: abaixo bateria na chave estrangeira e a migration morreria no meio.
update interlocutor i
   set instituicao_id = p.financeiro
  from par_financeiro p
 where i.instituicao_id = p.veiculo;

update interacao i
   set instituicao_id = p.financeiro
  from par_financeiro p
 where i.instituicao_id = p.veiculo;

--: O PAR JÁ DECIDIDO COMO "OUTRO ATOR" SAI DA FILA junto com o cadastro: a linha
--: de `ator_distinto` que aponta para o veículo que vai deixar de existir não diz
--: mais nada, e a chave estrangeira a seguraria.
delete from ator_distinto
 where esquerda in (select veiculo from par_financeiro)
    or direita in (select veiculo from par_financeiro);

delete from instituicao where id in (select veiculo from par_financeiro);

do $$
declare
    fundidos int;
    sobrou int;
begin
    select count(*) into fundidos from par_financeiro;

    --: O QUE DEVERIA SOBRAR É ZERO, e um número aqui diz "há par de três lados",
    --: que é o caso que esta migration deixa de propósito para quem administra.
    select count(*) into sobrou
      from instituicao v
      join instituicao f
        on f.nome_normalizado = v.nome_normalizado
       and f.tipo in ('investidor', 'credor')
     where v.tipo = 'veiculo';

    raise notice 'veiculos fundidos no ator financeiro: %', fundidos;
    raise notice 'pares restantes (devia ser 0, ou so os de 3+ lados): %', sobrou;
end $$;

commit;
