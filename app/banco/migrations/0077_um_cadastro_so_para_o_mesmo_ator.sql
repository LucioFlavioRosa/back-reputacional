--: UM CADASTRO SÓ PARA O MESMO ATOR: o perfil de rede homônimo funde no veículo.
--:
--: O QUE O DONO DO PRODUTO PERGUNTOU, e que é a decisão de negócio desta
--: migration: "o Valor Econômico é uma empresa grande que está na base de
--: imprensa; caso tenhamos Valor Econômico no CRM, empresa e rede social, vamos
--: consultar o mesmo perfil?" — e a resposta foi "deveria ser um único cadastro
--: que vem de Cadastro compartilhado".
--:
--: HOJE NÃO É. Medido na base da pilha: 30 perfis de rede têm nome
--: EXATAMENTE igual a um veículo de imprensa já cadastrado — `Valor Econômico`
--: (2 menções de rede) e `Valor Econômico` (86 de clipping) são duas linhas,
--: dois dossiês, duas réguas de peso.
--:
--: A CAUSA É ESTRUTURAL, não um descuido de quem cadastrou: o índice único é
--: `(nome_normalizado, tipo)`. Nome igual com tipo diferente SEMPRE caberia
--: duas vezes, e a ingestão da Bites, que cria `perfil_rede`, não via o
--: `veiculo` de mesmo nome. A ingestão já foi corrigida — `reconhecer` procura
--: em qualquer tipo quando quem fala é perfil de rede, preferindo o mesmo tipo
--: — então a próxima subida não cria o par de novo. Esta migration limpa o que
--: a versão antiga já gravou.
--:
--: QUEM SOBREVIVE É O VEÍCULO, e não o perfil: ele é a linha curada, com
--: categoria, subcategoria, UF e frente (os 30 têm categoria; os perfis em
--: geral não), e concentra as menções — 86 contra 2, no caso do Valor. O nome
--: dele também é o escrito por gente ("UOL", "Exame"), contra o handle do
--: fornecedor ("Uol", "exame").
--:
--: O QUE SE PERDE, dito em voz alta: o `cargo` do perfil. Dos 30, 17 têm
--: "Imprensa" e 3 "Comunicador" — e o tipo `veiculo` já afirma isso. A coluna
--: não acompanha porque o CHECK `instituicao_cargo_so_de_perfil` existe de
--: propósito: um jornal não tem cargo.
--:
--: SÓ O HOMÔNIMO EXATO, por `nome_normalizado`. Há outros ~66 pares que só
--: casam depois de tirar pontuação e espaço (`valoreconomico` ↔ `Valor
--: Econômico`), e ali a semelhança NÃO prova identidade: `Diário SM` e
--: `Diários M` casam assim, `bmc.news` casa com DOIS veículos. Esses vão para
--: uma tela de confirmação, com gente decidindo. Fundir por semelhança
--: automaticamente juntaria dossiês de atores diferentes, e isso não tem volta.
--:
--: E O PERFIL LIGADO A UMA PESSOA FICA DE FORA: se alguém ligou o perfil a um
--: interlocutor do CRM, há julgamento humano gravado ali, e o veículo não pode
--: herdar a ligação (CHECK `instituicao_pessoa_so_de_perfil`). Na base de hoje
--: são zero; a guarda existe para a reaplicação.
--:
--: Idempotente: depois de rodar, não há mais par homônimo para fundir.

begin;

--: O `on commit drop` derruba a temporária no fim da transação. O `drop`
--: explícito é para quem rodar a migration DUAS VEZES NA MESMA transação, que é
--: o que o teste de idempotência faz.
drop table if exists par_a_fundir;

create temporary table par_a_fundir on commit drop as
select p.id as perfil, o.id as veiculo, p.cargo as cargo_perdido
  from instituicao p
  join instituicao o
    on o.nome_normalizado = p.nome_normalizado
   and o.tipo <> 'perfil_rede'
 where p.tipo = 'perfil_rede'
   --: VER O CABEÇALHO: julgamento humano gravado não se desfaz sozinho.
   and p.interlocutor_id is null;

--: SÓ O PAR 1:1. Um perfil que casasse com dois cadastros — ou um cadastro
--: disputado por dois perfis — é escolha de ator, não de SQL. Na base de hoje
--: os 30 são 1:1; a guarda é para a próxima base.
delete from par_a_fundir
 where perfil in (select perfil from par_a_fundir group by perfil having count(*) > 1)
    or veiculo in (select veiculo from par_a_fundir group by veiculo having count(*) > 1);

--: AS MENÇÕES PASSAM PARA O SOBREVIVENTE. É o dossiê inteiro do ator num só
--: lugar: 58 menções, no acerto de hoje.
update mencao m
   set instituicao_id = f.veiculo
  from par_a_fundir f
 where m.instituicao_id = f.perfil;

--: E O QUE MAIS APONTA PARA INSTITUIÇÃO. Zero nos dois, hoje; sem isto a
--: exclusão abaixo bateria na FK e a migration morreria no meio.
update interlocutor i
   set instituicao_id = f.veiculo
  from par_a_fundir f
 where i.instituicao_id = f.perfil;

update interacao i
   set instituicao_id = f.veiculo
  from par_a_fundir f
 where i.instituicao_id = f.perfil;

delete from instituicao where id in (select perfil from par_a_fundir);

do $$
declare
    fundidos int;
    cargos_perdidos int;
    sobrou int;
begin
    select count(*), count(cargo_perdido) into fundidos, cargos_perdidos
      from par_a_fundir;

    select count(*) into sobrou
      from instituicao p
      join instituicao o
        on o.nome_normalizado = p.nome_normalizado and o.tipo <> 'perfil_rede'
     where p.tipo = 'perfil_rede' and p.interlocutor_id is null;

    raise notice 'perfis fundidos no veiculo: % (cargos descartados: %)',
        fundidos, cargos_perdidos;
    raise notice 'pares homonimos restantes (devia ser 0 ou so os de 2+ lados): %',
        sobrou;
end $$;

commit;
