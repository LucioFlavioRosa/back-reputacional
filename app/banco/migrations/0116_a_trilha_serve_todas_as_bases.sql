--: A trilha da `0115` passa a servir TODAS as bases do painel, e não só as
--: fontes do Score: bonds e subtemas também perdem o "quem" hoje.
--:
--: POR QUE UMA TABELA E NÃO TRÊS. A pergunta é uma só — "quando esta base foi
--: atualizada, e por quem" — e a tela é uma só. Três tabelas com as mesmas sete
--: colunas seriam três lugares para a resposta divergir, e a aba teria de unir
--: as três a cada leitura.
--:
--: O QUE CADA BASE PERDIA ANTES DAQUI:
--:
--:   score      `planilha_recebida` é apagada na confirmação (0115 resolveu)
--:   bonds      `planilha_de_bonds.descartar` apaga a subida; `bond_cotacao`
--:              não tem importador nem hora de carga
--:   subtemas   `confirmar` não grava autor nem data em lugar nenhum
--:
--: AS AGENDAS DO CRM FICAM DE FORA, e de propósito: `importacao` já sobrevive à
--: confirmação com `criado_por`, `criado_em` e `confirmado_em`. Copiá-las para
--: cá criaria uma segunda verdade sobre o mesmo fato. A aba lê as duas.
--:
--: `fonte_id` SÓ FAZ SENTIDO NO SCORE: bonds e subtemas são base inteira, não
--: têm fonte. O `check` amarra as duas coisas em vez de confiar em convenção —
--: sem ele, uma carga de bonds com `fonte_id` apontaria para uma fonte de
--: menção e a aba mostraria "Bonds · Clipei".
--:
--: Idempotente.

begin;

do $$
begin
  if to_regclass('public.carga_de_fonte') is not null
     and to_regclass('public.carga_de_base') is null then
    --: `rename` PRESERVA OS GRANTS da 0115 (eles seguem o objeto, não o nome),
    --: então o `revoke update, delete` continua valendo. A conferência no fim
    --: cobra isso em vez de supor.
    alter table carga_de_fonte rename to carga_de_base;
    alter table carga_de_base rename column mencoes to linhas;
    alter index carga_de_fonte_fonte_concluida_idx
      rename to carga_de_base_fonte_concluida_idx;
    alter index carga_de_fonte_concluida_idx rename to carga_de_base_concluida_idx;
    alter index carga_de_fonte_lote_idx rename to carga_de_base_lote_idx;
  end if;
end $$;

--: Nasce com `default 'score'` para a coluna poder ser `not null` sem depender
--: de haver ou não linha; o default sai logo abaixo, porque base nova tem de se
--: declarar em vez de herdar o Score por omissão.
alter table carga_de_base
  add column if not exists base text not null default 'score';
alter table carga_de_base alter column base drop default;

alter table carga_de_base alter column fonte_id drop not null;

--: Vazio onde a base não é mensal: a planilha de subtemas não fala de mês.
alter table carga_de_base alter column meses set default '{}';

comment on column carga_de_base.base is
  'Qual base recebeu a carga. Ver `casos_de_uso/trilha_da_carga.BASES`. Lista '
  'FECHADA por check, ao contrario de `origem`: a aba ramifica nesta coluna, e '
  'um typo deixaria a carga invisivel para a tela.';

comment on column carga_de_base.fonte_id is
  'So o Score tem fonte. Bonds e subtemas sao base inteira, e o `check` '
  'carga_de_base_fonte_coerente impede os dois enganos simetricos.';

comment on column carga_de_base.linhas is
  'Quantas linhas a carga gravou: mencoes no Score, cotacoes em bonds, temas '
  'em subtemas. ZERO e valido e e o caso que torna esta tabela necessaria.';

--: `conrelid` TAMBÉM, e não só o nome: nome de constraint é único por tabela,
--: não por schema, então procurar só por `conname` acharia uma homônima de outra
--: tabela e a migration concluiria que já fez o que não fez.
do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'carga_de_base_fonte_coerente'
       and conrelid = 'public.carga_de_base'::regclass
  ) then
    alter table carga_de_base add constraint carga_de_base_fonte_coerente
      check ((base = 'score') = (fonte_id is not null));
  end if;
end $$;

--: `base` GANHA LISTA FECHADA, e `origem` não — a diferença é quem lê. `origem`
--: é rótulo que ninguém ramifica: um valor novo aparece na tela e pronto. `base`
--: é discriminador: o `check` acima ramifica nela, e a aba decide o que mostrar
--: por ela. Um typo aqui faria a carga ficar invisível para a tela, que é o
--: oposto do que a trilha existe para fazer. Base nova é migration, e tem de
--: ser: ela precisa de rótulo e de lugar na aba de qualquer jeito.
do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'carga_de_base_base_conhecida'
       and conrelid = 'public.carga_de_base'::regclass
  ) then
    alter table carga_de_base add constraint carga_de_base_base_conhecida
      check (base in ('score', 'bonds', 'subtemas'));
  end if;
end $$;

--: O comentário da `0115` falava de "(carga, fonte)", que o rename deixou
--: desatualizado.
comment on table carga_de_base is
  'Uma linha por (carga, base) — e por fonte, no Score. Append-only pela '
  'aplicacao: ver os revokes na 0115. A existencia da linha e o sucesso; carga '
  'que estourou faz rollback e nao deixa linha.';

--: A aba lista por base antes de por fonte.
create index if not exists carga_de_base_base_concluida_idx
  on carga_de_base (base, concluida_em desc);

do $$
declare
    indevidos text;
begin
    select string_agg(p, ', ' order by p) into indevidos
      from unnest(array['UPDATE', 'DELETE']) as p
     where has_table_privilege('painel_app', 'carga_de_base', p);

    if indevidos is not null then
        raise exception
            'painel_app pode % em carga_de_base: o rename perdeu o revoke da 0115',
            indevidos;
    end if;

    --: `SELECT` TAMBÉM: o rename preserva os privilégios, e esta conferência é o
    --: que prova em vez de supor. Sem a leitura a aba não tem o que mostrar, e o
    --: sintoma apareceria só no ambiente implantado.
    if not has_table_privilege('painel_app', 'carga_de_base', 'SELECT') then
        raise exception
            'painel_app nao pode ler carga_de_base: o rename perdeu o grant';
    end if;

    if not has_table_privilege('painel_app', 'carga_de_base', 'INSERT') then
        raise exception
            'painel_app nao pode inserir em carga_de_base: o rename perdeu o grant';
    end if;

    raise notice 'carga_de_base serve todas as bases, gravavel so por insert';
end $$;

commit;
