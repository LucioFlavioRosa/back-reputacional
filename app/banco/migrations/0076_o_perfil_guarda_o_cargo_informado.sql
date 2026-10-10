--: O PERFIL DE REDE GUARDA O CARGO QUE O FORNECEDOR INFORMOU.
--:
--: O QUE O DONO DO PRODUTO VIU. No Cadastro compartilhado, a deputada Stela
--: Farias aparecia como "Poder Legislativo" — o público está certo desde a
--: `0075`, mas o CARGO não aparecia em lugar nenhum. E ele é o que a pessoa
--: reconhece: "Deputado estadual · RS" diz quem é o ator; "Poder Legislativo"
--: diz a que poder ele pertence.
--:
--: O CARGO ESTAVA SÓ NA MENÇÃO (`mencao.cargo`), onde serve à régua de peso e
--: ao gráfico de quem fala. O cadastro do perfil não o guardava, então a tela
--: teria de ir buscá-lo nas menções para mostrar — e o Cadastro compartilhado
--: lê o catálogo, não a base de menções.
--:
--: GUARDA O RÓTULO, e não o código: `Deputado estadual`, e não
--: `deputado_estadual`. A coluna é lida por gente, como `interlocutor.cargo`,
--: que também é texto livre. O código continua em `mencao.cargo`, que é onde a
--: régua de peso o consome.
--:
--: SÓ PERFIL DE REDE TEM CARGO, e o CHECK garante: um jornal não tem cargo.
--: Mesma disciplina de `interlocutor_id` na `0073`.
--:
--: E A PESSOA, QUANDO VIER, TEM O CARGO DELA. `interlocutor.cargo` é a verdade
--: do CRM sobre a pessoa; este aqui é a evidência do fornecedor sobre o
--: perfil. Não é a mesma afirmação em dois lugares: um perfil pode existir sem
--: pessoa nenhuma, e é esse o estado dos 1.108.
--:
--: O BACKFILL USA O CARGO MAIS FREQUENTE das menções do perfil, como a `0075`:
--: quase sempre há um só; havendo empate, o alfabético decide.
--:
--: Idempotente.

begin;

alter table instituicao add column if not exists cargo text;

alter table instituicao drop constraint if exists instituicao_cargo_so_de_perfil;
alter table instituicao add constraint instituicao_cargo_so_de_perfil check (
  cargo is null or tipo = 'perfil_rede'
);

--: O RÓTULO DE CADA CÓDIGO, espelhando `ROTULO_DO_CARGO` do domínio. Escrito
--: aqui porque uma migration não importa a aplicação — e o teste
--: `test_o_rotulo_da_migration_bate_com_o_dominio` prova que os dois não
--: divergiram.
create temporary table rotulo_do_cargo (
    cargo text primary key,
    rotulo text not null
) on commit drop;

--: AS VARIANTES TAMBÉM, pelo mesmo motivo da `0075`: numa base que ingeriu
--: antes de `CARGO_CANONICO`, `mencao.cargo` tem `vereadora` e `verador`, e o
--: `coalesce` com `initcap` gravaria "Verador" — o erro de digitação do
--: fornecedor — como se fosse um cargo. Achado de revisão.
insert into rotulo_do_cargo (cargo, rotulo) values
    ('presidente',        'Presidente'),
    ('ministro',          'Ministro'),
    ('governador',        'Governador'),
    ('senador',           'Senador'),
    ('deputado_federal',  'Deputado federal'),
    ('deputado_estadual', 'Deputado estadual'),
    ('prefeito',          'Prefeito'),
    ('vereador',          'Vereador'),
    ('politico',          'Político'),
    ('comunicador',       'Comunicador'),
    ('imprensa',          'Imprensa'),
    ('internauta',        'Internauta'),
    ('empresa',           'Empresa'),
    ('sindicato',         'Sindicato'),
    ('partido',           'Partido'),
    ('prefeitura',        'Prefeitura'),
    ('orgao_publico',     'Órgão público'),
    ('outros',            'Outros'),
    ('vereadora',         'Vereador'),
    ('verador',           'Vereador'),
    ('deputada_estadual', 'Deputado estadual'),
    ('deputada_federal',  'Deputado federal'),
    ('prefeita',          'Prefeito'),
    ('senadora',          'Senador'),
    ('governadora',       'Governador'),
    ('ministra',          'Ministro'),
    ('presidenta',        'Presidente');

create temporary table cargo_do_perfil on commit drop as
with contagem as (
    select m.instituicao_id as perfil, m.cargo,
           row_number() over (
               partition by m.instituicao_id
               order by count(*) desc, m.cargo
           ) as ordem
      from mencao m
      join instituicao i on i.id = m.instituicao_id
     where i.tipo = 'perfil_rede' and m.cargo is not null
     group by m.instituicao_id, m.cargo
)
select perfil, cargo from contagem where ordem = 1;

update instituicao i
   set cargo = coalesce(
         r.rotulo,
         --: CARGO QUE O FORNECEDOR INVENTAR aparece mesmo assim, do código:
         --: esconder até alguém cadastrar faria a tela mentir por omissão.
         initcap(replace(cp.cargo, '_', ' '))
       )
  from cargo_do_perfil cp
  left join rotulo_do_cargo r on r.cargo = cp.cargo
 where i.id = cp.perfil
   and i.tipo = 'perfil_rede'
   --: NÃO SOBRESCREVE o que alguém já tenha escrito à mão.
   and i.cargo is null;

do $$
declare
    com_cargo int;
    total int;
begin
    select count(*) , count(cargo) into total, com_cargo
      from instituicao where tipo = 'perfil_rede';
    raise notice 'perfis com cargo: % de %', com_cargo, total;
end $$;

commit;
