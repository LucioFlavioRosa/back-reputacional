-- =============================================================================
-- 0087 — a informação sensível passa a ser por PESSOA, e não só por papel
--
-- O QUE FALTAVA
--
-- `papel.ve_campos_sensiveis` existe desde 0003, e os OITO papéis semeados a
-- têm `true`. A bandeira nunca foi usada para NEGAR: não há, hoje, papel que
-- abra o CRM e esconda `relato` e `pendencias`. Quem recebe o CRM recebe junto
-- a transcrição do que foi conversado, e não havia como conceder um sem o
-- outro.
--
-- POR QUE NÃO MAIS PAPÉIS
--
-- Resolveria, e dobraria a tabela: `crm_leitura` e `crm_leitura_sem_sensivel`,
-- e o mesmo para cada um dos oito. É exatamente o argumento que separou ONDE a
-- pessoa entra do que ela FAZ lá dentro — ver o comentário de `acessa_crm` em
-- 0003. A informação sensível é a terceira dimensão da mesma decisão, e pede o
-- mesmo tratamento: dimensão própria, não produto cartesiano.
--
-- COMO AS DUAS SE COMBINAM
--
--     efetivo = papel.ve_campos_sensiveis AND usuario.acesso_sensivel
--
-- O papel diz o TETO que o cargo permite; a coluna nova diz se ESTA pessoa
-- recebeu. Conjunção, e não substituição: papel que não alcança o sensível
-- continua não alcançando, por mais que alguém marque a pessoa. A aplicação faz
-- essa conta num lugar só — a propriedade `UsuarioAtual.ve_campos_sensiveis`,
-- que é por onde TODAS as rotas passam (conferido: nenhuma lê
-- `papel.ve_campos_sensiveis` direto para decidir payload).
--
-- POR QUE O PADRÃO É `true`
--
-- Porque é o que já acontece. Com `false`, aplicar esta migration TIRARIA o
-- relato de todo mundo que tem acesso hoje, em silêncio, no deploy — uma
-- mudança de autorização que ninguém pediu e que apareceria como "a tela parou
-- de mostrar o campo". Com `true`, aplicar não muda nada, e restringir passa a
-- ser um ato explícito de quem administra.
--
-- Isso NÃO afasta a doutrina de falhar fechado. Quem nasce no provisionamento
-- nasce sem papel, e sem papel a conjunção já é falsa: o padrão desta coluna
-- não concede nada por si. E toda concessão de papel passa por
-- `conceder_acesso`, onde o valor é PARÂMETRO OBRIGATÓRIO — ver abaixo.
--
-- A CONTENÇÃO VEM DE GRAÇA, E ISSO MERECE REGISTRO
--
-- 0009 revoga `update` em `usuario` e devolve por COLUNA:
--
--     grant update (nome, email, ultimo_acesso_em, ativo) on usuario
--
-- Coluna nova não entra nessa lista, então `painel_app` já não consegue
-- escrevê-la. Quem escreve é `conceder_acesso`, como nas outras colunas de
-- autorização. `tests/test_papel_restrito.py` tem a guarda.
-- =============================================================================

alter table usuario
  add column if not exists acesso_sensivel boolean not null default true;

comment on column usuario.acesso_sensivel is
  'Se ESTA pessoa alcança os campos sensíveis. Combina com '
  'papel.ve_campos_sensiveis por E lógico: o papel é o teto, esta coluna é a '
  'concessão. Escrita só por conceder_acesso().';


-- A coluna entra no conjunto que só a função escreve.
grant update (acesso_sensivel) on usuario to painel_concessao;


-- -- `conceder_acesso` ganha a terceira camada -----------------------------------
--
-- A FUNÇÃO ANTIGA SAI DE CIRCULAÇÃO, e não fica como sobrecarga.
--
-- `create or replace` com um argumento a mais não substitui: cria uma SEGUNDA
-- função. Com `default` no argumento novo, as duas aceitariam 9 argumentos e o
-- Postgres recusaria a chamada por ambiguidade ("function conceder_acesso(...)
-- is not unique"). Sem `default`, as duas conviveriam — e a de 9 argumentos
-- continuaria gravando concessão SEM decidir a camada sensível, que é
-- justamente o esquecimento que esta migration existe para impedir.
--
-- Por isso `drop`: quem chamar com a assinatura velha passa a receber erro na
-- hora, em vez de gravar meia concessão.
--
-- `sensivel` ENTRA NO FIM, COM `default false`, e as duas coisas têm razão.
--
-- No fim porque o Postgres exige: parâmetro com padrão não pode ser seguido de
-- parâmetro sem padrão, e `versao_vista` tem o seu desde 0006. Pôr `sensivel`
-- antes dela seria reordenar a assinatura, e aí uma chamada antiga de nove
-- argumentos passaria o `timestamptz` da versão no lugar do booleano.
--
-- `default false` porque é bandeira de PERMISSÃO, e para bandeira de permissão
-- este projeto já decidiu: "fecham por padrão, como todas as outras bandeiras.
-- Papel novo que não decida nada não abre porta nenhuma" (0003, `acessa_crm`).
-- Quem esquecer o argumento não concede o relato — deixa de conceder, que é o
-- lado seguro de errar.
--
-- É diferente de `versao_vista`, que não tem padrão SEGURO: qualquer valor ali
-- AFIRMA algo sobre o estado do banco, e por isso o padrão dela é um nulo que
-- significa "vi esta pessoa sem concessão nenhuma", conferido de verdade.
drop function if exists conceder_acesso(
  uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz
);

-- O CORPO É O DE 0010, VERBATIM, mais a coluna nova — e a repetição é
-- deliberada, pela mesma razão que 0010 registra: `create or replace` exige o
-- corpo inteiro, e o corpo inteiro é onde se perdem validações sem ninguém ver.
-- Conferido contra 0010 linha a linha: cadeado, `for update`, versão otimista,
-- limpeza na revogação, as duas recusas de combinação, as duas conferências de
-- dimensão e a invariante do último administrador.
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
  versao_vista    timestamptz default null,
  --: A terceira camada. Fecha por padrão — ver a nota do `drop` acima.
  sensivel        boolean     default false
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
  --: O alvo administra acessos HOJE? Decide se esta transação paga o cadeado.
  alvo_administra_hoje boolean := false;
  --: E vai DEIXAR de administrar? Decide se a invariante é conferida no fim.
  pode_tirar_admin boolean := false;
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

  -- O CADEADO VEM ANTES DO `for update`, e a ordem é o ponto. Ver 0010: depois
  -- dele seria tarde, porque `carregar()` já travou a linha de QUEM PEDE ao
  -- carimbar `ultimo_acesso_em`, e o `for update` abaixo quer a linha do ALVO —
  -- dois administradores se rebaixando ao mesmo tempo fecham o ciclo.
  --
  -- SÓ quando o alvo administra hoje: uma concessão a um leitor não pode afetar
  -- a invariante, e serializá-la só criaria recusas sem motivo.
  select coalesce((
    select p.administra_acessos
      from usuario u join papel p on p.id = u.papel_id
     where u.id = alvo and u.ativo and p.ativo
  ), false) into alvo_administra_hoje;

  if alvo_administra_hoje then
    -- `try`, e não esperar: esperar é o que fecha o ciclo.
    if not pg_try_advisory_xact_lock(chave_do_cadeado_de_administradores()) then
      raise exception
        'Outra alteração de acesso está em andamento. Tente de novo em instantes.';
    end if;
  end if;

  -- `for update` TRAVA a linha, e sem ele a conferência de versão não vale sob
  -- concorrência: duas transações leriam a MESMA `versao_atual` antes de
  -- qualquer uma escrever, as duas passariam, e a segunda sobrescreveria a
  -- primeira.
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
    --
    -- `sensivel` ENTRA NESSA LIMPEZA, e é o único lugar onde o padrão da coluna
    -- não vale: quem for reativado começa sem a camada, e concedê-la de novo é
    -- um ato. Falha fechada, que é o que se quer de uma ressurreição.
    irrestrito  := false;
    eh_externo  := false;
    expira_em   := null;
    frentes     := '{}';
    unidades    := '{}';
    sensivel    := false;
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

    if sensivel is null then
      -- A coluna é `not null`, e um nulo aqui viraria erro de constraint com
      -- mensagem do Postgres sobre nome de coluna. Recusa explícita diz o que
      -- fazer.
      raise exception 'A camada de informação sensível precisa ser decidida.';
    end if;

    -- NÃO SE CONCEDE SENSÍVEL ACIMA DO TETO DO PAPEL.
    --
    -- A conjunção na aplicação já faria o acesso ser falso, então isto não
    -- protege dado nenhum — protege a TELA de dizer uma coisa e o sistema fazer
    -- outra. Sem a recusa, a pessoa apareceria marcada "com acesso sensível" e
    -- não veria o campo, e quem administra procuraria o defeito no lugar
    -- errado.
    if sensivel and not exists (
      select 1 from papel where id = id_do_papel and ve_campos_sensiveis
    ) then
      raise exception
        'O papel % não alcança informação sensível.', codigo_do_papel;
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

  -- Tira administrador se ele administrava e o papel novo não administra.
  -- `id_do_papel` nulo é revogação: tira também.
  pode_tirar_admin := alvo_administra_hoje and not coalesce(
    (select p.administra_acessos from papel p where p.id = id_do_papel), false
  );

  -- Carimba o autor para os gatilhos de auditoria lerem. `true` = local à
  -- transação: não vaza para a próxima requisição da mesma conexão.
  perform set_config('painel.usuario_id', quem_concede::text, true);

  update usuario
     set papel_id            = id_do_papel,
         acesso_irrestrito   = irrestrito,
         externo             = eh_externo,
         acesso_expira_em    = expira_em,
         acesso_sensivel     = sensivel,
         papel_concedido_por = quem_concede,
         -- `clock_timestamp()`, e não `now()`: `now()` devolve o horário de
         -- INÍCIO DA TRANSAÇÃO, então duas concessões dentro da mesma transação
         -- receberiam o mesmo carimbo e a versão não mudaria — a detecção de
         -- alteração concorrente deixaria de detectar.
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

  -- DEPOIS da escrita: vale para qualquer campo que a concessão mexeu, sem o
  -- código precisar adivinhar qual deles importa.
  if pode_tirar_admin then
    perform exigir_administrador_restante();
  end if;
end;
$$;

-- O DONO PRECISA DE `create` NO SCHEMA PARA POSSUIR OBJETO NELE, e é exigência
-- conferida no momento da transferência.
--
-- 0006 concedeu e REVOGOU esse direito no mesmo arquivo — a posse permanece, a
-- role volta a não poder criar nada. Então aqui ele não existe mais, e a
-- transferência falha com `permission denied for schema public`.
--
-- SUPERUSUÁRIO PASSA SEM ISSO, porque ignora a checagem. Conta comum não — e é
-- conta comum que aplica as migrations no Postgres gerenciado. Esta migration
-- passou localmente (superusuário) e quebrou nos quatro jobs
-- `Migrations · conta-comum` do CI, nas quatro versões do Postgres. É
-- exatamente o cenário que aquela matriz existe para pegar, e a razão de ela
-- existir.
--
-- Concedido só para a transferência e revogado logo depois, como em 0006.
grant create on schema public to painel_concessao;

alter function conceder_acesso(
  uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz, boolean
) owner to painel_concessao;

revoke create on schema public from painel_concessao;

-- O `drop` acima levou embora os `grant` da assinatura antiga. Sem estas duas
-- linhas a função nasce chamável por `public` e NÃO chamável pela aplicação —
-- exatamente o contrário do que se quer, e a tela de acessos pararia com
-- "permission denied for function".
revoke all on function conceder_acesso(
  uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz, boolean
) from public;

grant execute on function conceder_acesso(
  uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz, boolean
) to painel_app;

comment on function conceder_acesso(
  uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz, boolean
) is
  'Escreve autorização com validação, versão e trilha. NÃO é fronteira de '
  'autorização: `quem_concede` é parâmetro, e quem tem a credencial o escolhe.';


-- -- a trilha vigia a coluna nova ----------------------------------------------
--
-- `registrar_mudanca_de_acesso` ENUMERA as colunas que audita (0005, `vigiadas`).
-- Uma coluna de autorização fora dessa lista é mudança de acesso sem rastro — e
-- "quem liberou isto?" é a pergunta que a tabela existe para responder. O
-- esquecimento seria invisível: a concessão funcionaria, a tela confirmaria, e a
-- trilha simplesmente não teria a linha.
--
-- Recriada em bloco porque `create or replace` exige o corpo inteiro. É o de
-- 0005 verbatim, mais um item no array.
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
    'papel_id', 'acesso_irrestrito', 'externo', 'acesso_expira_em', 'ativo',
    'acesso_sensivel'
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

-- `create or replace` PRESERVA o dono, então esta transferência é redundante
-- hoje. Fica porque o dia em que não for — uma função recriada por outra conta —
-- o gatilho perde o direito de inserir na trilha e para de gravar em silêncio.
--
-- O `grant create` em volta é pela mesma razão do bloco de `conceder_acesso`
-- acima: 0005 concedeu e revogou esse direito a `painel_auditoria` no próprio
-- arquivo, e sem reconceder a transferência falharia em conta comum. Aqui ela
-- passaria por ser no-op (o dono já é esse), mas depender disso é depender de
-- um detalhe do Postgres que não está escrito em lugar nenhum.
grant create on schema public to painel_auditoria;

alter function registrar_mudanca_de_acesso() owner to painel_auditoria;

revoke create on schema public from painel_auditoria;
