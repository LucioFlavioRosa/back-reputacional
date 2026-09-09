-- O MATERIAL DO BLOB PASSA A TER ASSUNTO
--
-- A biblioteca do SharePoint é organizada por assunto desde que nasceu (0026),
-- e é por assunto que se acha o que se procura. O que a equipe sobe para o
-- nosso armazenamento não tinha nada disso: a ata de uma reunião só era
-- alcançável por quem soubesse de qual reunião ela saiu.
--
-- DUAS ABAS, UMA MANEIRA DE PROCURAR. Com esta tabela, "o que existe sobre
-- tarifa" tem a mesma resposta nas duas — o oficial que se leva e o produzido
-- que voltou.
--
-- TABELA DE VÍNCULO, e não uma coluna: um documento trata de mais de um
-- assunto com a mesma naturalidade com que uma agenda trata. É a mesma forma de
-- `interacao_tema` e de `referencia_tema`, de propósito — três vínculos com a
-- mesma pergunta ("do que isto trata?") escritos de três jeitos diferentes
-- seriam três consultas diferentes para a mesma coisa.

begin;

create table if not exists material_tema (
  material_id uuid not null references material(id) on delete cascade,
  tema_id     int  not null references tema(id),
  primary key (material_id, tema_id)
);

comment on table material_tema is
  'De que assuntos um material trata. Espelha `referencia_tema`, para que a '
  'busca por assunto seja a mesma nas duas procedências.';

-- Para "quais documentos falam de tarifa": sem ele, filtrar por assunto varre a
-- tabela de vínculos inteira.
create index if not exists material_tema_tema_idx on material_tema (tema_id);

-- DELETE É NECESSÁRIO AQUI. Trocar os assuntos de um material é apagar linhas
-- desta tabela; as `alter default privileges` da 0009 concedem apenas
-- select/insert/update, e sem isto a edição falharia com erro de permissão — e
-- só na hora de salvar.
grant delete on material_tema to painel_app;

-- OS MATERIAIS QUE JÁ EXISTIAM HERDAM OS ASSUNTOS DA AGENDA
--
-- É a mesma regra que o formulário aplica a uma linha nova: um documento
-- produzido numa reunião sobre tarifa trata de tarifa. Deixá-los sem assunto
-- os tornaria invisíveis na busca que esta migration existe para permitir — e
-- ninguém voltaria para classificar um a um.
--
-- É UM PALPITE, e é por isso que só vale para o que já estava aqui: daqui em
-- diante quem sobe o arquivo vê os assuntos na tela e pode corrigi-los. O
-- palpite erra quando a ata traz um trecho de outro assunto, e acertar isso
-- exigiria ler os documentos.
--
-- `on conflict do nothing` deixa a rodada seguinte sem efeito, e preserva quem
-- já foi classificado à mão.
insert into material_tema (material_id, tema_id)
select m.id, it.tema_id
  from material m
  join interacao_tema it on it.interacao_id = m.interacao_id
 where not exists (
   select 1 from material_tema mt where mt.material_id = m.id
 )
on conflict do nothing;

commit;
