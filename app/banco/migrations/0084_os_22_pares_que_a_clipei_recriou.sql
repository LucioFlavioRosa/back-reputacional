--: OS 22 PARES QUE A CLIPEI RECRIOU depois da `0077`.
--:
--: A `0077` FUNDIU 30 HOMÔNIMOS `perfil_rede` + `veiculo` e escreveu, com todas as
--: letras, por que não voltariam: "a ingestão já foi corrigida — `reconhecer`
--: procura em qualquer tipo quando quem fala é perfil de rede — então a próxima
--: subida não cria o par de novo".
--:
--: ERA VERDADE PELA METADE. A Bites, que cria `perfil_rede`, de fato passou a
--: achar o veículo. A CLIPEI, que cria `veiculo`, continuou filtrando
--: `tipo = 'veiculo'`: ela não via o perfil que a Bites havia criado, e criava um
--: veículo ao lado. A correção de 2026-10 era assimétrica, e a assimetria era o
--: defeito.
--:
--: MEDIDO AGORA: 22 pares, 310 menções no lado veículo e 37 no lado perfil, e
--: NENHUM deles ligado a pessoa do CRM. São 22 atores com o dossiê partido —
--: "GZH", "Brasil 247", "BM&C News" entre eles.
--:
--: A INGESTÃO JÁ FOI CORRIGIDA DE VERDADE, e agora nas duas direções: a busca não
--: filtra tipo nenhum, para fonte nenhuma. É o princípio que o dono do produto
--: deu em 11/10/2026 — "qualquer fonte de dados tem acesso à mesma base de
--: instituições e interlocutores; o BTG podemos ter acesso em rede social, em
--: reunião de investimento ou imprensa, mas ele continua sendo um só". Esta
--: migration limpa o que a versão assimétrica gravou.
--:
--: QUEM SOBREVIVE É O VEÍCULO, pela mesma razão da `0077` e não por repetição: o
--: perfil é a linha crua do social listening e o veículo é a curada, com
--: categoria, subcategoria, UF e frente — e concentra as menções, 310 contra 37.
--: O nome dele também é o escrito por gente ("GZH") contra o handle.
--:
--: E O ENQUADRAMENTO NÃO É DECIDIDO AQUI: "quem decide como enquadrar é o time
--: que está registrando a primeira vez ou editando posteriormente". Esta migration
--: não muda tipo, categoria nem subcategoria de ninguém — ela escolhe qual das
--: DUAS linhas existentes fica, e move o que apontava para a outra.
--:
--: O CANAL NÃO SE PERDE AO UNIFICAR, e vale repetir porque é a objeção natural:
--: quem diz "foi em rede social" é a FONTE da menção — `bites` alimenta a lente
--: Sociedade digital, `clipei` a Imprensa. A instituição responde QUEM falou; a
--: fonte responde ONDE. É exatamente o "relacionando em diferentes níveis".

begin;

drop table if exists par_recriado;

create temporary table par_recriado on commit drop as
select p.id as perfil, v.id as veiculo
  from instituicao p
  join instituicao v
    on v.nome_normalizado = p.nome_normalizado
   and v.tipo = 'veiculo'
 where p.tipo = 'perfil_rede'
   --: VER A `0077`: julgamento humano gravado não se desfaz sozinho. Um perfil
   --: ligado a uma pessoa do CRM é decisão de alguém, e fundi-lo levaria o
   --: vínculo embora. Zero deles hoje, e a guarda fica.
   and p.interlocutor_id is null;

--: TRÊS LADOS OU MAIS NÃO SE FUNDE SOZINHO: com dois veículos de mesmo nome não
--: há como saber qual é o ator, e escolher errado espalha as menções no cadastro
--: errado. Fica para quem administra.
delete from par_recriado
 where perfil in (select perfil from par_recriado group by perfil having count(*) > 1)
    or veiculo in (select veiculo from par_recriado group by veiculo having count(*) > 1);

--: AS MENÇÕES PASSAM PARA O SOBREVIVENTE: é o dossiê inteiro do ator num só lugar.
update mencao m
   set instituicao_id = r.veiculo
  from par_recriado r
 where m.instituicao_id = r.perfil;

--: E O QUE MAIS APONTA PARA INSTITUIÇÃO; sem isto a exclusão bate na chave
--: estrangeira e a migration morre no meio.
update interlocutor i
   set instituicao_id = r.veiculo
  from par_recriado r
 where i.instituicao_id = r.perfil;

update interacao i
   set instituicao_id = r.veiculo
  from par_recriado r
 where i.instituicao_id = r.perfil;

delete from ator_distinto
 where esquerda in (select perfil from par_recriado)
    or direita in (select perfil from par_recriado);

delete from instituicao where id in (select perfil from par_recriado);

do $$
declare
    fundidos int;
    sobrou int;
begin
    select count(*) into fundidos from par_recriado;

    select count(*) into sobrou
      from instituicao p
      join instituicao v
        on v.nome_normalizado = p.nome_normalizado and v.tipo = 'veiculo'
     where p.tipo = 'perfil_rede' and p.interlocutor_id is null;

    raise notice 'perfis recriados pela Clipei, fundidos no veiculo: %', fundidos;
    raise notice 'pares restantes (devia ser 0, ou so os de 3+ lados): %', sobrou;
end $$;

commit;
