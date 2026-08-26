-- =============================================================================
-- 0006 — `conceder_acesso`: a escrita de autorização
--
-- A conta da aplicação (`painel_app`, ver 0009) NÃO pode escrever nas colunas de
-- autorização de `usuario` nem em `usuario_escopo`. Com `grant` direto ali,
-- quem tivesse a connection string faria `update usuario set acesso_irrestrito
-- = true` e passaria a enxergar a base inteira.
--
-- A tela de administração de acessos precisa alterar exatamente essas colunas.
-- Quem escreve é esta função, `security definer`, cujo dono tem os direitos que
-- a aplicação não tem.
--
-- O QUE ELA GARANTE
--
--   INTEGRIDADE   nenhum estado inválido é criável. Externo sem prazo, papel
--                 inexistente, frente que não existe, irrestrito combinado com
--                 externo — tudo recusado no banco, não só no Python.
--   CONTENÇÃO     um caminho futuro na aplicação não consegue esquecer as
--                 regras, porque não consegue escrever sem a função.
--   TRILHA        os gatilhos de 0005 gravam `usuario_auditoria` em qualquer
--                 caminho, inclusive por SQL direto.
--   VERSÃO        duas pessoas editando o mesmo acesso não se sobrescrevem.
--
-- O QUE ELA NÃO GARANTE — e é importante estar escrito
--
--   AUTORIZAÇÃO   contra quem detém a credencial da aplicação, não há barreira.
--                 O banco não distingue "a aplicação agindo por um
--                 administrador" de "alguém com a connection string": as duas
--                 chegam pela mesma conta. `quem_concede` é PARÂMETRO, e
--                 parâmetro é escolhido por quem chama.
--
-- A fronteira de autorização é a aplicação. As checagens aqui impedem estado
-- inválido e barram erro de programação; não barram quem já tem a credencial.
--
-- O que barraria: operações de concessão passarem por um serviço separado, com
-- credencial de banco que o processo do painel não possui. É mudança de
-- arquitetura, e está registrada como tal em `seguranca/ARQUITETURA.md`.
--
-- A VERSÃO OTIMISTA
--
-- `papel_concedido_em` é a versão. Quem salva declara o que viu em
-- `versao_vista`; se o banco tiver outra coisa, a função recusa e a tela
-- recarrega. Nulo não é curinga — afirma "vi esta pessoa sem concessão
-- nenhuma", e só passa se o banco também estiver sem.
-- =============================================================================

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'painel_concessao') then
    create role painel_concessao nologin;
  end if;

  -- Quem aplica precisa ser MEMBRO da role para transferir a posse das funções
  -- para ela. Superusuário é membro de tudo implicitamente; uma conta comum com
  -- `CREATEROLE` não é — e esse é o caso do Postgres gerenciado, onde a conta
  -- administrativa NÃO é superusuário.
  --
  -- Sem este bloco, o `alter function ... owner to` abaixo falha:
  --
  --   até o 15   ERROR: must be member of role "painel_concessao"
  --   16+        ERROR: must be able to SET ROLE "painel_concessao"
  --
  -- A diferença entre as versões é real: do 16 em diante quem cria a role já a
  -- recebe, mas com `SET FALSE` — administra sem poder assumir. Daí o
  -- `with set true`, sintaxe que não existe antes disso.
  if not (select rolsuper from pg_roles where rolname = current_user) then
    if current_setting('server_version_num')::int >= 160000 then
      execute format('grant %s to %I with set true', 'painel_concessao', current_user);
    else
      execute format('grant %s to %I', 'painel_concessao', current_user);
    end if;
  end if;
end $$;

grant usage on schema public to painel_concessao;

-- O novo dono precisa de CREATE no schema para poder possuir objeto nele —
-- exigência do Postgres, conferida no momento da transferência.
--
-- Concedido só para isso e revogado no fim do arquivo: a posse permanece, e a
-- role volta a não poder criar nada. Superusuário passaria sem o grant, porque
-- ignora a checagem; o Postgres gerenciado, não.
grant create on schema public to painel_concessao;

grant select on usuario, papel, frente, unidade_negocio to painel_concessao;
grant update (papel_id, acesso_irrestrito, externo, acesso_expira_em, ativo,
              papel_concedido_por, papel_concedido_em)
  on usuario to painel_concessao;
grant select, insert, delete on usuario_escopo to painel_concessao;


create or replace function conceder_acesso(
  alvo            uuid,
  quem_concede    uuid,
  codigo_do_papel text,
  irrestrito      boolean,
  eh_externo      boolean,
  expira_em       date,
  frentes         text[],
  unidades        text[],
  --: O que a tela viu quando abriu, e que precisa continuar valendo.
  --:
  --: Nulo NÃO é curinga: é a declaração "vi esta pessoa sem concessão nenhuma".
  --: Só passa se o banco também estiver sem — ver o `is distinct from` abaixo.
  --:
  --: O `default null` existe para a chamada da primeira concessão; omitir o
  --: argumento AFIRMA que o alvo nunca teve papel, e a chamada falha se ele teve.
  versao_vista    timestamptz default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  id_do_papel  smallint;
  desconhecida text;
  versao_atual timestamptz;
begin
  if quem_concede is null then
    raise exception 'Concessão exige um autor.';
  end if;

  -- Administrador que se rebaixa por engano fica sem conseguir se consertar, e
  -- quem conserta é quem tem o mesmo papel — que pode não existir. Pior ainda
  -- seria alguém se conceder mais do que tem.
  if alvo = quem_concede then
    raise exception 'Ninguém altera o próprio acesso.';
  end if;

  if not exists (
    select 1 from usuario u join papel p on p.id = u.papel_id
     where u.id = quem_concede and u.ativo and p.administra_acessos
  ) then
    raise exception 'Quem concede precisa administrar acessos.';
  end if;

  -- `for update` TRAVA a linha, e sem ele a conferência de versão logo abaixo
  -- não vale sob concorrência: duas transações simultâneas leriam a MESMA
  -- `versao_atual` antes de qualquer uma escrever, as duas passariam na
  -- comparação, e a segunda sobrescreveria a primeira.
  --
  -- Com a trava, a segunda espera a primeira terminar e então lê o carimbo
  -- novo — que já não bate com o que ela viu.
  --
  -- Custo: concessões para a MESMA pessoa são serializadas. É o que se quer.
  select papel_concedido_em into versao_atual from usuario where id = alvo
    for update;
  if not found then
    raise exception 'Usuário não encontrado.';
  end if;

  -- `is distinct from` porque os dois lados podem ser nulos, e nulo é um estado
  -- legítimo: é o de quem nunca teve papel. O operador compara nulo com nulo
  -- como igualdade — que é exatamente o caso da primeira concessão.
  if versao_atual is distinct from versao_vista then
    raise exception
      'O acesso desta pessoa mudou enquanto o formulário estava aberto. Recarregue e refaça.';
  end if;

  if codigo_do_papel is null then
    id_do_papel := null;
    -- Revogar é estado limpo. Guardar o alcance de alguém sem papel é guardar
    -- uma surpresa para quem conceder papel depois: um contrato encerrado
    -- ressuscitaria com o escopo intacto.
    irrestrito  := false;
    eh_externo  := false;
    expira_em   := null;
    frentes     := '{}';
    unidades    := '{}';
  else
    select id into id_do_papel from papel
     where codigo = codigo_do_papel and ativo;
    if id_do_papel is null then
      raise exception 'Papel desconhecido ou inativo: %', codigo_do_papel;
    end if;

    if eh_externo and expira_em is null then
      raise exception 'Acesso externo exige prazo.';
    end if;

    if irrestrito and eh_externo then
      raise exception 'Acesso irrestrito não se combina com acesso externo.';
    end if;

    -- `usuario_escopo` não tem chave estrangeira, porque a dimensão é
    -- polimórfica. Sem esta conferência, conceder "frente: NAO_EXISTE" grava e a
    -- tela informa sucesso — e a pessoa não vê nada, sem ninguém entender por quê.
    if not irrestrito then
      select f into desconhecida
        from unnest(coalesce(frentes, '{}')) f
       where not exists (select 1 from frente where codigo = f)
       limit 1;
      if desconhecida is not null then
        raise exception 'Frente desconhecida: %', desconhecida;
      end if;

      select u into desconhecida
        from unnest(coalesce(unidades, '{}')) u
       where not exists (select 1 from unidade_negocio where nome = u)
       limit 1;
      if desconhecida is not null then
        raise exception 'Unidade desconhecida: %', desconhecida;
      end if;
    end if;
  end if;

  -- Carimba o autor para os gatilhos de auditoria lerem. `true` = local à
  -- transação: não vaza para a próxima requisição da mesma conexão.
  perform set_config('painel.usuario_id', quem_concede::text, true);

  update usuario
     set papel_id            = id_do_papel,
         acesso_irrestrito   = irrestrito,
         externo             = eh_externo,
         acesso_expira_em    = expira_em,
         papel_concedido_por = quem_concede,
         -- `clock_timestamp()`, e não `now()`: `now()` devolve o horário de
         -- INÍCIO DA TRANSAÇÃO, então duas concessões dentro da mesma transação
         -- receberiam o mesmo carimbo e a versão não mudaria — a detecção de
         -- alteração concorrente deixaria de detectar. Em produção cada
         -- requisição é uma transação, então isso só apareceria na primeira
         -- rotina que concedesse em lote.
         papel_concedido_em  = clock_timestamp()
   where id = alvo;

  -- Substituição, e não diferença: o gatilho registra cada linha que sai e cada
  -- uma que entra, então o histórico fica completo de qualquer jeito, e o código
  -- fica sem um caso de borda para errar.
  delete from usuario_escopo where usuario_id = alvo;

  if id_do_papel is not null and not irrestrito then
    insert into usuario_escopo (usuario_id, dimensao, valor)
    select alvo, 'frente', unnest(coalesce(frentes, '{}'))
    union all
    select alvo, 'unidade_negocio', unnest(coalesce(unidades, '{}'));
  end if;
end;
$$;

alter function conceder_acesso(uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz)
  owner to painel_concessao;

-- O `grant execute` para `painel_app` fica em 0009, junto do resto do que a
-- aplicação pode: um lugar só para responder "o que a conta da aplicação faz?".
revoke all on function conceder_acesso(uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz)
  from public;

comment on function conceder_acesso(uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz) is
  'Escreve autorização com validação, versão e trilha. NÃO é fronteira de '
  'autorização: `quem_concede` é parâmetro, e quem tem a credencial o escolhe.';


-- A posse já foi transferida; o CREATE não é mais necessário. Ver a nota no
-- topo, junto do `grant create`.
revoke create on schema public from painel_concessao;
