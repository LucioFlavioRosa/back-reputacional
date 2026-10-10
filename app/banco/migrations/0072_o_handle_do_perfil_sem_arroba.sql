--: O HANDLE DO PERFIL DE REDE PERDE O @, E OS DUPLICADOS SE FUNDEM.
--:
--: O QUE ACONTECEU. A primeira carga da Bites criou 1.167 perfis de rede a
--: partir da coluna `Autor`, e o fornecedor escreve o mesmo perfil das duas
--: formas: `@casadevovodede` com 33 menções e `casadevovodede` com 32 são o
--: MESMO perfil. Medido nesta base: 568 dos 1.167 vieram com @, e 59 deles têm
--: o gêmeo sem @ já cadastrado. O dossiê somava os dois lados separados, e o
--: Cadastro compartilhado mostrava duas linhas para um perfil.
--:
--: O @ É PONTUAÇÃO DA PLATAFORMA, e não identidade — é a mesma natureza do
--: prefixo `2. ` que a Clipei carimba no atributo. A ingestão passou a tirá-lo
--: na leitura (`quem_falou`, em `dominio/ingestao_score`), e SÓ onde quem fala
--: é um perfil: no clipping, quem fala é veículo de imprensa e o nome não tem
--: @ — aplicar a regra lá mexeria em 25.457 vínculos que já funcionam.
--:
--: ESTA MIGRATION CONSERTA O QUE JÁ ESTÁ GRAVADO, em duas partes:
--:
--:   59 grupos FUNDEM     — a menção do lado com @ passa a apontar para o
--:                          canônico, e a linha com @ é removida
--:  509 linhas RENOMEIAM  — têm @ e não têm gêmeo: viram o próprio nome sem @
--:
--: Sobram 1.108 perfis, que é o número de perfis distintos no arquivo.
--:
--: O CANÔNICO É O SEM @, e não o de mais menções. Tem de ser: a ingestão agora
--: grava sem @, então escolher o lado com @ faria a próxima subida criar o
--: canônico de novo e o problema voltaria — com uma linha órfã a mais.
--:
--: PELO `nome_normalizado`, e não por `lower(nome)`. É a normalização que a
--: aplicação usa (`dominio/texto.normalizar`: sem acento, minúscula, espaço
--: colapsado) e que já está gravada na coluna — a lição da `0066`, que casou
--: 78 de 81 por usar `lower()`. Aqui só se tira o @ dela.
--:
--: SÓ `mencao` APONTA PARA PERFIL hoje (2.626 linhas); `interacao` e
--: `interlocutor` não têm nenhuma. Ainda assim o repontamento é feito antes da
--: remoção, e a remoção só alcança quem não tem mais nada apontando.
--:
--: Idempotente: rodar de novo não acha o que fundir.

begin;

--: OS GRUPOS, pela chave canônica (o normalizado sem @).
create temporary table fusao_de_perfis on commit drop as
with perfis as (
    select id, nome, nome_normalizado,
           --: `btrim` DEPOIS do `ltrim`, porque `quem_falou` faz
           --: `lstrip('@').strip()`: a célula `@ nome` (arroba e espaço)
           --: normalizaria para ` nome` aqui e para `nome` na ingestão —
           --: duas chaves, o gêmeo não funde, e a próxima subida cria
           --: outro perfil. Achado de revisão.
           btrim(ltrim(nome_normalizado, '@')) as canonico,
           (btrim(nome) <> btrim(ltrim(nome, '@'))) as tem_arroba
      from instituicao
     where tipo = 'perfil_rede'
),
escolhidos as (
    select canonico,
           --: O SEM @ VENCE. Havendo mais de um sem @ (não há nesta base), o
           --: menor id decide — determinístico, e não "o que o banco devolver".
           (array_agg(id order by tem_arroba, id))[1] as fica
      from perfis
     group by canonico
)
select p.id as sai, e.fica, p.canonico
  from perfis p
  join escolhidos e on e.canonico = p.canonico
 where p.id <> e.fica;

--: AS MENÇÕES DO LADO QUE SAI passam a apontar para o canônico.
update mencao m
   set instituicao_id = f.fica
  from fusao_de_perfis f
 where m.instituicao_id = f.sai;

delete from instituicao
 where id in (select sai from fusao_de_perfis);

--: E O QUE SOBROU COM @ perde o @ — no nome e no normalizado, que é a chave de
--: comparação e faz parte do índice único com o tipo.
update instituicao
   set nome = btrim(ltrim(nome, '@')),
       nome_normalizado = btrim(ltrim(nome_normalizado, '@'))
 where tipo = 'perfil_rede'
   --: PELO NORMALIZADO TAMBÉM: a verificação antiga olhava só `nome`, e um
   --: normalizado com arroba ou espaço residual passava batido — e é o
   --: normalizado que a ingestão compara.
   and (nome like '%@%' or nome_normalizado <> btrim(ltrim(nome_normalizado, '@')));

do $$
declare
    com_arroba int;
    duplicados int;
begin
    select count(*) into com_arroba
      from instituicao
     where tipo = 'perfil_rede'
       and (nome like '%@%'
            or nome_normalizado <> btrim(ltrim(nome_normalizado, '@')));

    select count(*) into duplicados
      from (
        select btrim(ltrim(nome_normalizado, '@'))
          from instituicao
         where tipo = 'perfil_rede'
         group by 1
        having count(*) > 1
      ) x;

    if com_arroba > 0 or duplicados > 0 then
        raise exception
            'a fusão não fechou: % com @, % chaves duplicadas',
            com_arroba, duplicados;
    end if;
    raise notice 'perfis de rede sem @ e sem duplicata';
end $$;

commit;
