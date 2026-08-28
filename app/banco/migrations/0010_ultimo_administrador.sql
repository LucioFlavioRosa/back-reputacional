-- A plataforma nunca fica sem quem administre acessos.
--
-- O PROBLEMA, E POR QUE ELE NÃO É ÓBVIO
-- =====================================
-- Sequencialmente a invariante já valia, e valia de graça: para mexer em acesso
-- é preciso ser administrador ATIVO, e `conceder_acesso` proíbe alterar o
-- próprio acesso. Logo quem pede sempre permanece.
--
-- Esse raciocínio está certo — e é inútil com duas transações ao mesmo tempo.
--
--     A desativa B          B desativa A
--     ------------          ------------
--     lê: A e B admins      lê: A e B admins
--     A vê 1 restante (A)   B vê 1 restante (B)
--     commit                commit
--                    → sobraram ZERO
--
-- Nenhuma das duas mente: cada uma olhou antes de a outra escrever. E não há
-- conflito de linha que as serialize, porque cada uma escreve numa linha
-- DIFERENTE. O `for update` de `conceder_acesso` trava o ALVO, que é
-- exatamente a linha errada para esta invariante.
--
-- Reproduzido contra este banco, nos dois caminhos: dois administradores se
-- desativando em paralelo terminaram com zero ativos; dois se rebaixando em
-- paralelo terminaram ambos sem `administra_acessos`.
--
-- POR QUE NÃO UM GATILHO
-- ======================
-- Um gatilho que contasse administradores ao fim de cada `update` tem o mesmo
-- furo: os dois rodariam antes de qualquer commit, cada um enxergando o outro
-- ainda ativo, e os dois passariam. Contar não resolve nada se as contagens
-- acontecem em paralelo.
--
-- A SOLUÇÃO
-- =========
-- Um cadeado consultivo por TRANSAÇÃO, tomado por toda operação capaz de
-- encolher o conjunto de administradores. Ele serializa apenas essas
-- operações — que são raras, administrativas, e nunca no caminho de leitura do
-- painel. Sob o cadeado, contar volta a valer.
--
-- `pg_advisory_xact_lock` e não `pg_advisory_lock`: solta sozinho no fim da
-- transação, inclusive em erro. A versão sem `xact` exigiria unlock explícito
-- e deixaria o cadeado preso na conexão do pool depois de qualquer exceção —
-- travando toda a administração de acessos até o processo reiniciar.
--
-- POR QUE `try`, E NÃO ESPERAR PELO CADEADO
-- =========================================
-- A primeira versão esperava, e criou um DEADLOCK de verdade — reproduzido.
--
-- Toda requisição autenticada passa por `carregar()`, que às vezes carimba
-- `ultimo_acesso_em` de quem está pedindo. Isso é um `update`, e um `update`
-- TRAVA A LINHA até o fim da transação. Então a ordem real é:
--
--     A trava a linha de A  →  pega o cadeado  →  quer a linha de B
--     B trava a linha de B  →  espera o cadeado
--
-- A espera pela linha de B; B espera pelo cadeado que A tem. Ciclo fechado, e
-- o Postgres mata uma das duas com `deadlock detected` — que chega na tela
-- como 500, sem explicação.
--
-- Inverter a ordem exigiria pegar o cadeado antes de `carregar()`, isto é,
-- antes da autenticação de TODA requisição. Seria pior do que a doença.
--
-- `pg_try_advisory_xact_lock` não espera: devolve falso na hora. Sem espera não
-- há ciclo, e portanto não há deadlock. Quem perdeu a corrida recebe uma
-- mensagem que diz o que fazer, e a transação dela solta as linhas que
-- segurava — deixando a vencedora seguir.
--
-- O custo é recusar uma operação concorrente legítima em vez de enfileirá-la.
-- Para uma tela administrativa de baixa frequência, falhar rápido e explicar é
-- melhor do que esperar sem dizer nada.

-- A chave mora numa função para os dois lados não divergirem: a aplicação
-- também a chama, e um número digitado em dois lugares vira dois números.
create or replace function chave_do_cadeado_de_administradores()
returns bigint
language sql
immutable
as $$
  --: Arbitrário e fixo. O que importa é ser o MESMO nas duas pontas.
  select 20260828000001::bigint;
$$;

comment on function chave_do_cadeado_de_administradores() is
  'Chave do cadeado consultivo que serializa operações capazes de remover o último administrador.';


create or replace function exigir_administrador_restante()
returns void
language plpgsql
as $$
begin
  if not exists (
    select 1
      from usuario u
      join papel p on p.id = u.papel_id
     where u.ativo
       and p.ativo
       and p.administra_acessos
  ) then
    -- Mensagem escrita para quem administra ler na tela, e não para log.
    raise exception
      'Esta operação deixaria a plataforma sem ninguém que administre acessos. Conceda o papel a outra pessoa antes.';
  end if;
end;
$$;

comment on function exigir_administrador_restante() is
  'Levanta se não restar administrador ativo. Chamar sempre DEPOIS da escrita e SOB o cadeado.';


-- `conceder_acesso` ganha o cadeado e a conferência.
--
-- O CORPO É O DE 0006, VERBATIM, mais duas linhas — e isso não é preciosismo.
-- Reescrevi a função de memória primeiro, e um diff contra o original mostrou
-- que eu tinha perdido a limpeza de `irrestrito`/`externo`/escopo ao remover o
-- papel, perdido a regra "irrestrito não se combina com externo", trocado
-- `unidade_negocio.nome` por `codigo` e inventado uma checagem de prazo.
-- `create or replace` exige o corpo inteiro, e o corpo inteiro é onde se
-- perdem validações sem ninguém ver.
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

  -- `for update` TRAVA a linha, e sem ele a conferência de versão logo abaixo
  -- não vale sob concorrência: duas transações simultâneas leriam a MESMA
  -- `versao_atual` antes de qualquer uma escrever, as duas passariam na
  -- comparação, e a segunda sobrescreveria a primeira.
  --
  -- Com a trava, a segunda espera a primeira terminar e então lê o carimbo
  -- novo — que já não bate com o que ela viu.
  --
  -- Custo: concessões para a MESMA pessoa são serializadas. É o que se quer.
  -- O CADEADO VEM ANTES DO `for update`, e a ordem é o ponto.
  --
  -- Depois dele seria tarde: `carregar()` já travou a linha de QUEM PEDE ao
  -- carimbar `ultimo_acesso_em`, e o `for update` abaixo quer a linha do ALVO.
  -- Com dois administradores se rebaixando ao mesmo tempo, cada transação
  -- segura a própria linha e espera a do outro — deadlock, e o cadeado nem
  -- chega a ser consultado. Medido: `deadlock detected ... while locking tuple
  -- in relation "usuario"`.
  --
  -- Este deadlock é ANTERIOR a esta migration: nasce do `for update` de 0006
  -- somado ao carimbo de último acesso. Pegar o cadeado antes o elimina, porque
  -- o perdedor desiste na hora e solta a linha que segurava.
  --
  -- SÓ quando o alvo administra hoje: uma concessão a um leitor não pode
  -- afetar a invariante, e serializá-la só criaria recusas sem motivo — foi o
  -- que quebrou `test_duas_concessoes_simultaneas_nao_se_atropelam` na versão
  -- anterior desta migration.
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
  -- Tira administrador se ele administrava e o papel novo não administra.
  -- `id_do_papel` nulo é revogação: tira também.
  pode_tirar_admin := alvo_administra_hoje and not coalesce(
    (select p.administra_acessos from papel p where p.id = id_do_papel), false
  );

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

  -- DEPOIS da escrita: vale para qualquer campo que a concessão mexeu, sem o
  -- código precisar adivinhar qual deles importa.
  if pode_tirar_admin then
    perform exigir_administrador_restante();
  end if;
end;
$$;

alter function conceder_acesso(uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz)
  owner to painel_concessao;


-- Explícito, e não confiando no `execute` que o Postgres dá a `public` por
-- padrão: a aplicação chama as duas diretamente, e uma política futura que
-- revogue o padrão não deve derrubar a administração de acessos em silêncio.
grant execute on function chave_do_cadeado_de_administradores() to painel_app;
grant execute on function exigir_administrador_restante() to painel_app;
