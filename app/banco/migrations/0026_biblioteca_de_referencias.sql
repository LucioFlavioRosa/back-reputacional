-- A BIBLIOTECA DE REFERÊNCIAS
--
-- A Aegea mantém no SharePoint um acervo por assunto — posicionamentos, Q&A,
-- releases, notas técnicas — e é dele que os porta-vozes tiram o que dizem. O
-- acervo existe; o que não existia era o painel saber que ele existe.
--
-- O PROBLEMA QUE ISTO RESOLVE não é guardar arquivo: é o porta-voz entrar numa
-- reunião de tarifa sem o Q&A de tarifa, ou com a versão de março. Por isso a
-- referência é ligada a ASSUNTO, e não a agenda: assunto é o que se escolhe ao
-- marcar uma reunião, e é por ele que o material certo se encontra sozinho.
--
-- NÃO GUARDAMOS O ARQUIVO. Guardamos o link, o resumo e a data — o arquivo
-- continua no SharePoint, com a governança que ele já tem. Duplicar o byte aqui
-- criaria uma segunda verdade que envelhece em silêncio.

begin;

create table if not exists referencia (
  id        uuid        primary key default gen_random_uuid(),

  titulo    text        not null,

  --: O QUE O DOCUMENTO É, e não do que ele trata — isso são os tópicos.
  --:
  --: Quem procura material antes de uma reunião procura por tipo: "onde está o
  --: Q&A", "qual é o posicionamento oficial". Procurar por título exige já
  --: saber o nome do arquivo, que é justamente o que quem chega não sabe.
  tipo      text        not null
              check (tipo in ('posicionamento', 'qa', 'release',
                              'apresentacao', 'dados', 'nota_tecnica')),

  --: Para quem está decidindo se abre o arquivo. Uma linha do que ele diz vale
  --: mais que o título, e é o que evita abrir cinco para achar um.
  resumo    text,

  --: O link no SharePoint. É por onde o material chega hoje, e é o mesmo
  --: formato que `material.url` já recebe.
  url       text        not null,

  --: A ÚLTIMA ATUALIZAÇÃO DO ARQUIVO — a data que diz se a referência ainda
  --: vale. É o campo que faz a biblioteca servir ao propósito de "todo mundo
  --: falando a mesma coisa, e a coisa atual".
  atualizado_em date    not null,

  --: QUEM ESCREVEU A DATA ACIMA.
  --:
  --: Hoje é sempre `manual`: não há integração com o Microsoft Graph, e montar
  --: uma exige registro de app no Entra, consentimento de administrador e um
  --: segredo em cofre. A coluna nasce agora para que, quando o sync vier, ele
  --: preencha `atualizado_em` e marque `sharepoint` aqui — sem migrar dado e
  --: sem a tela ter de adivinhar de onde veio o que mostra.
  fonte_da_data text     not null default 'manual'
                  check (fonte_da_data in ('manual', 'sharepoint')),

  --: Quando o sync leu o SharePoint. Nulo enquanto a data for manual: dizer
  --: "lido em" sobre um dado que ninguém leu seria mentira com carimbo.
  lido_em   timestamptz,

  ativo     boolean     not null default true,
  criado_por uuid       not null references usuario(id),
  criado_em timestamptz not null default now()
);

comment on table referencia is
  'Biblioteca de referências do SharePoint, por assunto. Guarda o link e os '
  'metadados; o arquivo continua lá.';

-- O MESMO NOME NÃO ENTRA DUAS VEZES. Duas linhas "Q&A Tarifa 2026" apontando
-- para arquivos diferentes é o começo de duas versões circulando — que é o
-- problema que esta tabela existe para acabar.
create unique index if not exists referencia_titulo_idx
  on referencia (lower(btrim(titulo)));

-- Para "o que existe sobre tarifa": é a consulta que a tela de agenda faz a
-- cada assunto marcado.
create table if not exists referencia_tema (
  referencia_id uuid not null references referencia(id) on delete cascade,
  tema_id       int  not null references tema(id),
  primary key (referencia_id, tema_id)
);

create index if not exists referencia_tema_tema_idx on referencia_tema (tema_id);

-- DELETE SÓ NO VÍNCULO, e não na referência.
--
-- As `alter default privileges` da 0009 concedem select/insert/update; o delete
-- é dado tabela a tabela, a quem precisa dele. Trocar os tópicos de uma
-- referência é apagar linhas daqui — sem isto, editar os tópicos falharia com
-- erro de permissão, e só na hora de salvar.
--
-- A REFERÊNCIA FICA SEM DELETE, como instituição e assunto: sai de circulação
-- por `ativo = false`. Uma referência apagada de vez levaria consigo a
-- explicação de por que certa reunião recebeu certo material.
grant delete on referencia_tema to painel_app;

-- =============================================================================
-- O MATERIAL DA AGENDA SABE DE QUAL REFERÊNCIA VEIO
-- =============================================================================
-- Ao marcar os assuntos de uma agenda, as referências daqueles assuntos viram
-- material de apoio. A coluna é o que permite três coisas que um título solto
-- não permitiria: a tela marcar a linha como vinda da biblioteca; desmarcar o
-- assunto tirar de volta o que ele trouxe; e, depois, saber quantas reuniões
-- levaram determinado posicionamento.
--
-- NULA no material que a pessoa escreveu à mão — que continua sendo a maioria.
--
-- `on delete set null`, e não `cascade`: apagar uma referência da biblioteca
-- não pode apagar o material de uma reunião que aconteceu. O registro do que
-- circulou naquele dia é da agenda, não da biblioteca.
alter table material
  add column if not exists referencia_id uuid references referencia(id)
    on delete set null;

comment on column material.referencia_id is
  'De qual referência da biblioteca este material veio. Nulo quando alguém o '
  'escreveu à mão.';

create index if not exists material_por_referencia_idx
  on material (referencia_id) where referencia_id is not null;

commit;
