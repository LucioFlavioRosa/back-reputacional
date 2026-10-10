--: O PÚBLICO DO PERFIL DE REDE SAI DO CARGO, E NÃO DE UM PADRÃO.
--:
--: O QUE O DONO DO PRODUTO VIU. A primeira carga da Bites criou os 1.108
--: perfis todos como "Formadores de Opinião", e no Cadastro compartilhado o
--: vereador Iriel Sachet aparecia classificado como formador de opinião. Está
--: errado, e o cadastro TEM o vocabulário certo: a taxonomia de públicos prevê
--: Poder Legislativo com Federal, Estadual e Municipal desde a `0036`.
--:
--: O CARGO ESTAVA SENDO JOGADO FORA no cadastro. A coluna `Cargo` da planilha
--: alimentava a régua de peso e o gráfico de quem fala, mas o perfil nascia
--: sem ela — e é ela que diz se o ator é poder público, imprensa ou sociedade.
--: A ingestão passou a usá-la (`CATEGORIA_POR_CARGO`); esta migration conserta
--: o que já está gravado.
--:
--: O CARGO DE CADA PERFIL É O MAIS FREQUENTE entre as menções dele. Quase
--: sempre há um só; havendo empate, o alfabético decide — determinístico, e
--: não "o que o banco devolver".
--:
--: SÓ MEXE EM QUEM ESTÁ NO PADRÃO: categoria "Formadores de Opinião" e
--: subcategoria nula.
--:
--: E ESSA GUARDA TEM UM LIMITE, que a revisão apontou e vale escrito:
--: "Formadores de Opinião" é `sem_quebra`, então NUNCA tem subcategoria — a
--: guarda não distingue "nasceu no padrão" de "um humano escolheu Formadores
--: de Opinião", que é a escolha certa para um influenciador. O segundo
--: UPDATE (o que zera) ficou restrito a quem NÃO TEM CARGO NENHUM nas
--: menções: um perfil com cargo registrado é preservado, mesmo que o cargo
--: não esteja mapeado. Um perfil sem cargo nenhum que alguém classificou à
--: mão ainda seria zerado numa reaplicação — é o resíduo conhecido, e a
--: ingestão nova já não cria esse estado.
--:
--: E O CARGO DESCONHECIDO ZERA A CATEGORIA, em vez de mantê-la. `político`
--: pode ser executivo ou legislativo; `partido`, `empresa` e `órgão público`
--: não têm par óbvio na taxonomia; e 2.249 das 2.886 linhas vêm SEM cargo.
--: Para todos esses, "ainda não classificado" é a verdade — e é um estado que
--: o cadastro já conhece. Deixá-los como formadores de opinião é exatamente a
--: afirmação falsa que esta migration existe para apagar.
--:
--: Idempotente.

begin;

create temporary table publico_por_cargo (
    cargo text primary key,
    categoria text not null,
    subcategoria text
) on commit drop;

--: AS GRAFIAS VARIANTES ENTRAM AQUI, e não só as canônicas.
--:
--: ACHADO DE REVISÃO: esta migration lê `mencao.cargo` do que JÁ está
--: gravado, e numa base que ingeriu antes de `CARGO_CANONICO` existir esse
--: valor pode ser `vereadora`, `verador` ou `deputada_estadual`. Sem as
--: variantes, a vereadora não casava, caía no segundo UPDATE e tinha a
--: categoria ZERADA — enquanto a vizinha gravada como `vereador` ganhava
--: Poder Legislativo / Municipal. Mesma régua, dois resultados.
insert into publico_por_cargo (cargo, categoria, subcategoria) values
    ('presidente',        'Poder Executivo',                      'Federal'),
    ('ministro',          'Poder Executivo',                      'Federal'),
    ('governador',        'Poder Executivo',                      'Estadual'),
    ('prefeito',          'Poder Executivo',                      'Municipal'),
    ('prefeitura',        'Poder Executivo',                      'Municipal'),
    ('senador',           'Poder Legislativo',                    'Federal'),
    ('deputado_federal',  'Poder Legislativo',                    'Federal'),
    ('deputado_estadual', 'Poder Legislativo',                    'Estadual'),
    ('vereador',          'Poder Legislativo',                    'Municipal'),
    --: IMPRENSA SEM SUBCATEGORIA: a lógica editorial é juízo humano, e é dela
    --: que a lente Mercado depende.
    ('imprensa',          'Imprensa',                             null),
    ('comunicador',       'Formadores de Opinião',                null),
    ('sindicato',         'Entidades Setoriais e Representativas', 'Institutos e Associações'),
    ('internauta',        'Sociedade Civil e Comunidade',         'Comunidade e lideranças locais'),
    --: AS VARIANTES, para a base que ingeriu antes da dobra.
    ('vereadora',         'Poder Legislativo',                    'Municipal'),
    ('verador',           'Poder Legislativo',                    'Municipal'),
    ('deputada_estadual', 'Poder Legislativo',                    'Estadual'),
    ('deputada_federal',  'Poder Legislativo',                    'Federal'),
    ('prefeita',          'Poder Executivo',                      'Municipal'),
    ('senadora',          'Poder Legislativo',                    'Federal'),
    ('governadora',       'Poder Executivo',                      'Estadual'),
    ('ministra',          'Poder Executivo',                      'Federal'),
    ('presidenta',        'Poder Executivo',                      'Federal');

--: O CARGO DE CADA PERFIL, o mais frequente entre as menções dele.
create temporary table cargo_do_perfil on commit drop as
with contagem as (
    select m.instituicao_id as perfil, m.cargo, count(*) as quantas,
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

--: QUEM TEM CARGO CONHECIDO vai para o público dele.
update instituicao i
   set categoria_publico_id = c.id,
       subcategoria_publico_id = s.id
  from cargo_do_perfil cp
  join publico_por_cargo p on p.cargo = cp.cargo
  join categoria_publico c on c.nome = p.categoria
  left join subcategoria_publico s
    on s.categoria_publico_id = c.id and s.nome = p.subcategoria
 where i.id = cp.perfil
   and i.tipo = 'perfil_rede'
   --: SÓ O QUE ESTÁ NO PADRÃO — ver o cabeçalho.
   and i.subcategoria_publico_id is null
   and i.categoria_publico_id = (
         select id from categoria_publico where nome = 'Formadores de Opinião'
       );

--: QUEM NÃO TEM CARGO CONHECIDO perde a categoria: "ainda não classificado" é
--: a verdade, e dizer "formador de opinião" não é.
update instituicao i
   set categoria_publico_id = null
 where i.tipo = 'perfil_rede'
   and i.subcategoria_publico_id is null
   and i.categoria_publico_id = (
         select id from categoria_publico where nome = 'Formadores de Opinião'
       )
   --: SÓ QUEM NÃO TEM CARGO NENHUM nas menções. A versão anterior zerava
   --: também quem tinha cargo NÃO MAPEADO (`político`, `empresa`, `partido`),
   --: e aí não havia como distinguir isso de uma escolha humana — agora o
   --: perfil fica com o que tem, aparece na tela com o cargo, e quem conhece o
   --: ator decide. Achado de revisão.
   --:
   --: (`i.cargo` seria a guarda óbvia e NÃO serve: a coluna só nasce na
   --: `0076`, e uma base criada do zero aplica as migrations em ordem — a
   --: suíte inteira foi pulada em silêncio por causa disso.)
   and not exists (
         select 1 from cargo_do_perfil cp where cp.perfil = i.id
       );

do $$
declare
    por_cargo int;
    sem_classificacao int;
    sobrou_formador int;
begin
    select count(*) into por_cargo
      from instituicao i
      join categoria_publico c on c.id = i.categoria_publico_id
     where i.tipo = 'perfil_rede' and c.nome <> 'Formadores de Opinião';

    select count(*) into sem_classificacao
      from instituicao
     where tipo = 'perfil_rede' and categoria_publico_id is null;

    select count(*) into sobrou_formador
      from instituicao i
      join categoria_publico c on c.id = i.categoria_publico_id
     where i.tipo = 'perfil_rede' and c.nome = 'Formadores de Opinião';

    raise notice
        'perfis por cargo: %, sem classificacao: %, formadores de opiniao: %',
        por_cargo, sem_classificacao, sobrou_formador;
end $$;

commit;
