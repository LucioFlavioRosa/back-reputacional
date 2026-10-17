-- =============================================================================
-- 0095 — O jornalista da menção é auditado
--
-- A Base do Score é só leitura desde sempre: nenhuma linha de `mencao` jamais
-- foi alterada pela aplicação depois de ingerida. Esta migration prepara o
-- primeiro campo a mudar isso — `autor`, o jornalista vinculado ao cadastro —
-- com a mesma trilha que toda alteração do produto já tem (ver `0005`).
--
-- MESMO PADRÃO DA 0005, TRILHA PRÓPRIA: `registrar_alteracao()` (0005) é
-- amarrada a `interacao`/`interacao_id` e não serve aqui. `mencao_auditoria`
-- e `registrar_alteracao_de_mencao()` são o espelho, com `mencao_id` no lugar.
-- GENÉRICA campo a campo, como a 0005 — hoje só `autor` muda pela aplicação,
-- mas um campo novo que passe a ser editável já nasce coberto, sem migration.
-- =============================================================================

create table mencao_auditoria (
  id             bigserial   primary key,
  mencao_id      uuid        not null references mencao(id),
  usuario_id     uuid        references usuario(id),
  ocorrido_em    timestamptz not null default now(),
  campo          text        not null,
  valor_anterior text,
  valor_novo     text,
  origem         text
);

comment on column mencao_auditoria.usuario_id is
  'Nulo significa alteração fora da aplicação — SQL direto. É sinal de '
  'incidente, não de dado faltando.';

comment on column mencao_auditoria.origem is
  'A conta de banco usada (`session_user`). Diferente de `usuario_id`, não é '
  'escolhida por quem escreve — é com quem a conexão se autenticou.';

create index mencao_auditoria_mencao_id_ocorrido_em_idx
  on mencao_auditoria (mencao_id, ocorrido_em desc);
create index mencao_auditoria_usuario_idx on mencao_auditoria (usuario_id);

-- AO CONTRÁRIO DE `interacao_auditoria` (criada na 0005, ANTES do `alter
-- default privileges` da 0009), esta tabela nasce DEPOIS — e herdaria
-- `select, insert, update` para `painel_app` em silêncio se nada fosse feito.
-- `test_nenhuma_trilha_e_gravavel_pela_aplicacao` existe exatamente para
-- travar essa classe de descuido; o revoke abaixo é o que ele cobra.
revoke insert, update, delete on mencao_auditoria from painel_app;
grant select on mencao_auditoria to painel_app;

grant insert on mencao_auditoria to painel_auditoria;
grant usage, select on sequence mencao_auditoria_id_seq to painel_auditoria;


-- `painel_auditoria` precisa ser possível assumir de novo, pela mesma razão da
-- 0005: quem aplica pode não ser superusuário no Postgres gerenciado.
do $$
begin
  if not (select rolsuper from pg_roles where rolname = current_user) then
    if current_setting('server_version_num')::int >= 160000 then
      execute format('grant %s to %I with set true', 'painel_auditoria', current_user);
    else
      execute format('grant %s to %I', 'painel_auditoria', current_user);
    end if;
  end if;
end $$;

grant create on schema public to painel_auditoria;

do $$
begin
  if has_schema_privilege('public', 'public', 'CREATE') then
    raise exception
      'PUBLIC ainda pode criar objeto no schema public, e esta função '
      '`security definer` depende do contrário — ver o comentário equivalente '
      'na 0005.';
  end if;
end $$;

create or replace function registrar_alteracao_de_mencao()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  -- `criado_em` muda só na criação e `id` é a própria chave: nenhum dos dois
  -- diz nada de novo numa trilha de EDIÇÃO.
  ignoradas constant text[] := array['id', 'criado_em'];

  anterior jsonb := to_jsonb(old);
  novo     jsonb := to_jsonb(new);

  nome  text;
  de    text;
  para  text;
  autor uuid;
begin
  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;
  end;

  for nome in select jsonb_object_keys(anterior || novo) loop
    if nome = any (ignoradas) then
      continue;
    end if;

    de   := anterior ->> nome;
    para := novo ->> nome;

    if de is distinct from para then
      insert into mencao_auditoria
        (mencao_id, usuario_id, campo, valor_anterior, valor_novo, origem)
      values
        (new.id, autor, nome, de, para, session_user);
    end if;
  end loop;

  return new;
end;
$$;

alter function registrar_alteracao_de_mencao() owner to painel_auditoria;

create trigger auditar_mencao
  after update on mencao
  for each row execute function registrar_alteracao_de_mencao();

revoke create on schema public from painel_auditoria;


-- `painel_app` já tem `update` em `mencao` pelo `alter default privileges` da
-- 0009 (concedido depois da tabela existir, então a 0048 que a criou não
-- precisou pedir de novo) — nenhum grant novo é preciso para a aplicação
-- gravar o jornalista.
