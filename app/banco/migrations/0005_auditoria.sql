-- =============================================================================
-- 0005 — Auditoria por gatilho
--
-- Duas trilhas, uma para cada pergunta que aparece depois de um incidente:
--
--   interacao_auditoria  o que mudou neste registro, e quem mudou
--   usuario_auditoria    quem deu acesso a quem, e quando
--
-- POR QUE GATILHO, E NÃO CÓDIGO DA APLICAÇÃO
--
-- Trilha escrita pela aplicação registra o que a aplicação faz. Um `update`
-- rodado por SQL direto — manutenção, correção de emergência, alguém com a
-- credencial — não passaria por ela, e é justamente esse o caso que se precisa
-- enxergar. O gatilho registra venha de onde vier.
--
-- AS DUAS COLUNAS DE AUTORIA, E POR QUE SÃO DUAS
--
--   usuario_id / concedido_por   quem a APLICAÇÃO diz que agiu. Vem de
--                                `SET LOCAL painel.usuario_id`, carimbado no
--                                início da requisição. É informação boa, mas é
--                                declarada — quem tem a credencial do banco
--                                pode carimbar qualquer valor.
--
--   origem                       `session_user`, a conta com que a conexão se
--                                autenticou. Não é escolhida por quem escreve.
--
-- Nulo em `usuario_id` com `origem` preenchida é a assinatura de alteração
-- feita fora da aplicação. Não é dado faltando: é sinal.
--
-- `SECURITY DEFINER` E O DONO DAS FUNÇÕES
--
-- As funções rodam com os direitos do dono, para poder inserir na trilha mesmo
-- quando a conta da aplicação não tem esse direito — é o que impede a aplicação
-- de forjar ou apagar linhas de auditoria. O dono é `painel_auditoria`, um papel
-- que só pode inserir na trilha: com `postgres` como dono, uma falha na função
-- teria o servidor inteiro como raio de alcance.
-- =============================================================================

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'painel_auditoria') then
    create role painel_auditoria nologin;
  end if;

  -- Quem aplica precisa ser MEMBRO da role para transferir a posse das funções
  -- para ela. Superusuário é membro de tudo implicitamente; uma conta comum com
  -- `CREATEROLE` não é — e esse é o caso do Postgres gerenciado, onde a conta
  -- administrativa NÃO é superusuário.
  --
  -- Sem este bloco, o `alter function ... owner to` abaixo falha:
  --
  --   até o 15   ERROR: must be member of role "painel_auditoria"
  --   16+        ERROR: must be able to SET ROLE "painel_auditoria"
  --
  -- A diferença entre as versões é real: do 16 em diante quem cria a role já a
  -- recebe, mas com `SET FALSE` — administra sem poder assumir. Daí o
  -- `with set true`, sintaxe que não existe antes disso.
  if not (select rolsuper from pg_roles where rolname = current_user) then
    if current_setting('server_version_num')::int >= 160000 then
      execute format('grant %s to %I with set true', 'painel_auditoria', current_user);
    else
      execute format('grant %s to %I', 'painel_auditoria', current_user);
    end if;
  end if;
end $$;

grant usage on schema public to painel_auditoria;

-- O novo dono precisa de CREATE no schema para poder possuir objeto nele —
-- exigência do Postgres, conferida no momento da transferência.
--
-- Concedido só para isso e revogado no fim do arquivo: a posse permanece, e a
-- role volta a não poder criar nada. Superusuário passaria sem o grant, porque
-- ignora a checagem; o Postgres gerenciado, não.
grant create on schema public to painel_auditoria;


-- `security definer` com `search_path = public` só é seguro se ninguém puder
-- criar objeto em `public`. Sem isto, um papel qualquer planta uma função com
-- nome de built-in e a função privilegiada passa a chamá-la.
revoke create on schema public from public;


-- =============================================================================
-- Trilha das interações
-- =============================================================================

create table interacao_auditoria (
  id             bigserial   primary key,
  interacao_id   uuid        not null references interacao(id),
  usuario_id     uuid        references usuario(id),
  ocorrido_em    timestamptz not null default now(),
  -- Nome do campo, prefixado pela tabela quando vem de uma extensão:
  -- `imprensa.data_publicacao`. Sem o prefixo, `formato_id` de imprensa e de
  -- investidores seriam indistinguíveis na trilha.
  campo          text        not null,
  valor_anterior text,
  valor_novo     text,
  origem         text
);

comment on column interacao_auditoria.usuario_id is
  'Nulo significa alteração fora da aplicação — SQL direto. É sinal de '
  'incidente, não de dado faltando.';

comment on column interacao_auditoria.origem is
  'A conta de banco usada (`session_user`). Diferente de `usuario_id`, não é '
  'escolhida por quem escreve — é com quem a conexão se autenticou.';

create index interacao_auditoria_interacao_id_ocorrido_em_idx
  on interacao_auditoria (interacao_id, ocorrido_em desc);
create index interacao_auditoria_usuario_idx on interacao_auditoria (usuario_id);

grant insert on interacao_auditoria to painel_auditoria;
grant usage, select on sequence interacao_auditoria_id_seq to painel_auditoria;


-- -- a função genérica de campo a campo -----------------------------------------

create or replace function registrar_alteracao()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  -- `atualizado_em` muda em toda escrita e não diz nada; `interacao_id` é a
  -- chave, e registrá-la seria repetir o que a linha de trilha já traz.
  ignoradas constant text[] := array['atualizado_em', 'interacao_id'];

  anterior jsonb := case when tg_op = 'INSERT' then '{}'::jsonb else to_jsonb(old) end;
  novo     jsonb := case when tg_op = 'DELETE' then '{}'::jsonb else to_jsonb(new) end;

  alvo     uuid;
  prefixo  text := case when tg_table_name = 'interacao' then '' else tg_table_name || '.' end;
  nome     text;
  de       text;
  para     text;
  autor    uuid;
begin
  if tg_table_name = 'interacao' then
    alvo := coalesce((novo ->> 'id')::uuid, (anterior ->> 'id')::uuid);
  else
    alvo := coalesce((novo ->> 'interacao_id')::uuid, (anterior ->> 'interacao_id')::uuid);
  end if;

  -- `true` devolve nulo em vez de erro quando a variável não foi definida — o
  -- caso de toda alteração feita por SQL direto.
  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;   -- valor mal formado não pode derrubar o UPDATE
  end;

  for nome in select jsonb_object_keys(anterior || novo) loop
    if nome = any (ignoradas) then
      continue;
    end if;

    de   := anterior ->> nome;
    para := novo ->> nome;

    -- `is distinct from` e não `<>`: com `<>`, mudar de nulo para valor não
    -- conta como mudança, e o campo mais interessante da auditoria — o que
    -- estava vazio e passou a ter conteúdo — nunca seria registrado.
    if de is distinct from para then
      insert into interacao_auditoria
        (interacao_id, usuario_id, campo, valor_anterior, valor_novo, origem)
      values
        (alvo, autor, prefixo || nome, de, para, session_user);
    end if;
  end loop;

  return coalesce(new, old);
end;
$$;

alter function registrar_alteracao() owner to painel_auditoria;


-- -- os vínculos N-N ------------------------------------------------------------
--
-- Auditar coluna a coluna aqui seria ruído: a linha inteira aparece ou some.
-- Uma linha de auditoria por vínculo diz o que aconteceu sem repetir a chave.

create or replace function registrar_vinculo()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  linha  jsonb := to_jsonb(coalesce(new, old));
  rotulo text := case tg_table_name
                   when 'interacao_tema' then 'tema'
                   when 'interacao_pessoa_aegea' then 'participacao'
                   else tg_table_name
                 end;
  valor  text;
  autor  uuid;
begin
  if tg_table_name = 'interacao_pessoa_aegea' then
    valor := (linha ->> 'pessoa_aegea_id') || ' (' || coalesce(linha ->> 'papel', '?') || ')';
  else
    valor := linha ->> 'tema_id';
  end if;

  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;
  end;

  insert into interacao_auditoria
    (interacao_id, usuario_id, campo, valor_anterior, valor_novo, origem)
  values (
    (linha ->> 'interacao_id')::uuid,
    autor,
    rotulo,
    case when tg_op = 'DELETE' then valor end,
    case when tg_op = 'INSERT' then valor end,
    session_user
  );

  return coalesce(new, old);
end;
$$;

alter function registrar_vinculo() owner to painel_auditoria;


-- -- os gatilhos das interações -------------------------------------------------

-- Só `update` na mãe: a criação já está registrada pela própria linha, com
-- `criado_por` e `criado_em`.
create trigger auditar_interacao
  after update on interacao
  for each row execute function registrar_alteracao();

do $$
declare
  filha text;
begin
  foreach filha in array array[
    'interacao_imprensa', 'interacao_institucional', 'interacao_legislativo',
    'interacao_investidores', 'interacao_interna'
  ] loop
    -- INSERT e DELETE também: trocar a frente de um registro apaga a extensão
    -- antiga e cria a nova, e as duas coisas são alteração de conteúdo.
    execute format(
      'create trigger auditar_%1$s after insert or update or delete on %1$I '
      'for each row execute function registrar_alteracao()', filha
    );
  end loop;

  foreach filha in array array['interacao_tema', 'interacao_pessoa_aegea'] loop
    execute format(
      'create trigger auditar_%1$s after insert or delete on %1$I '
      'for each row execute function registrar_vinculo()', filha
    );
  end loop;
end $$;


-- =============================================================================
-- Trilha da autorização
-- =============================================================================

create table usuario_auditoria (
  id             bigserial   primary key,
  usuario_id     uuid        not null references usuario(id),
  concedido_por  uuid        references usuario(id),
  ocorrido_em    timestamptz not null default now(),
  campo          text        not null,
  valor_anterior text,
  valor_novo     text,
  origem         text
);

comment on table usuario_auditoria is
  'Quem mudou a autorização de quem, e quando. Escrita por gatilho. A autoria '
  '(`concedido_por`) é informada pela aplicação e portanto forjável por quem '
  'tem a credencial; `origem` é a conta de banco, que não é escolhida.';

create index idx_usuario_auditoria_alvo on usuario_auditoria (usuario_id, ocorrido_em desc);

-- Consulta de incidente: "quem concedeu acesso na última semana?".
create index idx_usuario_auditoria_autor on usuario_auditoria (concedido_por, ocorrido_em desc);

grant insert on usuario_auditoria to painel_auditoria;
grant usage, select on sequence usuario_auditoria_id_seq to painel_auditoria;


create or replace function registrar_mudanca_de_acesso()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  -- Só o que decide o que a pessoa alcança. `nome`, `email` e
  -- `ultimo_acesso_em` mudam a cada login e não dizem nada sobre permissão.
  vigiadas constant text[] := array[
    'papel_id', 'acesso_irrestrito', 'externo', 'acesso_expira_em', 'ativo'
  ];
  anterior jsonb := to_jsonb(old);
  novo     jsonb := to_jsonb(new);
  nome     text;
  de       text;
  para     text;
  autor    uuid;
begin
  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;
  end;

  foreach nome in array vigiadas loop
    de   := anterior ->> nome;
    para := novo ->> nome;
    if de is distinct from para then
      insert into usuario_auditoria
        (usuario_id, concedido_por, campo, valor_anterior, valor_novo, origem)
      values (new.id, autor, nome, de, para, session_user);
    end if;
  end loop;

  return new;
end;
$$;

alter function registrar_mudanca_de_acesso() owner to painel_auditoria;

create trigger auditar_acesso_do_usuario
  after update on usuario
  for each row execute function registrar_mudanca_de_acesso();


-- Escopo é linha que aparece e some; auditar coluna a coluna seria ruído.
create or replace function registrar_mudanca_de_escopo()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  linha jsonb := to_jsonb(coalesce(new, old));
  autor uuid;
begin
  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;
  end;

  insert into usuario_auditoria
    (usuario_id, concedido_por, campo, valor_anterior, valor_novo, origem)
  values (
    (linha ->> 'usuario_id')::uuid,
    autor,
    'escopo.' || (linha ->> 'dimensao'),
    case when tg_op in ('DELETE', 'UPDATE') then to_jsonb(old) ->> 'valor' end,
    case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) ->> 'valor' end,
    session_user
  );

  return coalesce(new, old);
end;
$$;

alter function registrar_mudanca_de_escopo() owner to painel_auditoria;

-- `update` incluído: `conceder_acesso` só faz `delete` + `insert`, mas um papel
-- de manutenção faria `update usuario_escopo set valor = ...` e mudaria o
-- alcance de alguém sem deixar rastro. A trilha diz "venha de onde vier".
create trigger auditar_escopo
  after insert or update or delete on usuario_escopo
  for each row execute function registrar_mudanca_de_escopo();


-- -- devolve o schema ao estado fechado -----------------------------------------
--
-- A posse das funções já foi transferida; o CREATE não é mais necessário. Sem
-- esta revogação, `painel_auditoria` continuaria podendo criar objeto em
-- `public` — e é justamente sobre isso que o `revoke create ... from public` do
-- topo deste arquivo se apoia.
revoke create on schema public from painel_auditoria;
