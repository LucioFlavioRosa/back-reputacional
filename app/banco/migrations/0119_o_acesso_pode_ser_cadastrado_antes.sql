--: O acesso pode ser cadastrado ANTES de a pessoa entrar pela primeira vez.
--:
--: O DEFEITO QUE ISTO CONSERTA: hoje a pessoa só existe depois de ser RECUSADA.
--: O `provisionar` cria a linha a partir das claims do Entra com papel nulo, o
--: callback recusa o login, e só então ela aparece na tela de acessos para
--: receber papel. Numa estreia com diretores e C-levels, isso é um lote de
--: "Seu acesso ainda não foi liberado" antes de alguém poder agir.
--:
--: ISTO REVERTE PARTE DA `0096`, e a razão dela continua valendo. Lá o
--: `not null` entrou para impedir a CONTA FANTASMA: linha que existe, aparece
--: na tela, tem papel, e não entra por caminho nenhum — o que sobrava de quem
--: só tinha senha depois de a senha ser removida.
--:
--: O QUE MUDA, e é o que faz não ser a mesma coisa: ali não havia caminho de
--: entrada nenhum, e aqui há — `provisionar` vincula o `oid` no primeiro login
--: cujo e-mail casar. A linha sem `oid` não é um beco, é um pré-cadastro à
--: espera.
--:
--: O E-MAIL É O QUE O TOKEN DO TENANT AFIRMA, e não `email_verified` do OIDC: o
--: `oidc.validar` o tira de `preferred_username`, `email` ou `upn`, conferindo
--: assinatura, emissor, audiência, `nonce` e `tid`. Vale o que a administração
--: do Entra controla — forte dentro do tenant, e não mais que isso.
--:
--: O RISCO QUE SOBRA, dito: e-mail digitado errado NUNCA casa, e aí o
--: pré-cadastro É uma conta fantasma — com papel, na lista, inalcançável. Não
--: dá para o banco conferir isso (quem decide é o Entra), então quem o pega é a
--: tela: `ultimo_acesso_em` nulo distingue "nunca entrou" de "ativo", e é por
--: isso que o `check` abaixo existe em vez de ser dispensável.
--:
--: SÓ O PAPEL SE ADIANTA, E NUNCA A AUTENTICAÇÃO. Sem o grupo do SSO não há
--: token, não há login, e a linha fica parada: a `0096` segue sendo o único
--: caminho de entrada.
--:
--: Idempotente.

begin;

--: SEM `oid` PASSA A SER ESTADO VÁLIDO: pré-cadastro.
alter table usuario
    alter column entra_object_id drop not null;

--: E SEM VÍNCULO NÃO HOUVE ACESSO. É o que impede o estado sem sentido — nunca
--: vinculada e com último acesso carimbado —, e é o que a tela lê para dizer
--: "nunca entrou" em vez de mostrar um convite velho como usuário ativo.
alter table usuario
    drop constraint if exists usuario_sem_vinculo_nao_teve_acesso;

alter table usuario
    add constraint usuario_sem_vinculo_nao_teve_acesso
    check (entra_object_id is not null or ultimo_acesso_em is null);

comment on column usuario.entra_object_id is
  'O `oid` do Entra ID, e o unico caminho de entrada (0096). NULO desde a 0119 '
  'significa PRE-CADASTRO: o papel ja foi concedido e o vinculo acontece no '
  'primeiro login cujo e-mail o token do tenant afirmar (preferred_username, '
  'email ou upn) -- ver `provisionar_usuario`.';

--: O VÍNCULO É POR FUNÇÃO, E NÃO POR `update` DA APLICAÇÃO — achado de revisão,
--: e era defeito que só apareceria em produção.
--:
--: A `0009` revoga `update` em `usuario` e devolve só quatro colunas: `nome`,
--: `email`, `ultimo_acesso_em` e `ativo`. `entra_object_id` não está lá, de
--: propósito. Escrevê-lo pela aplicação daria `permission denied for column
--: entra_object_id` no primeiro login de todo pré-cadastrado — e a suíte não
--: pegaria, porque o banco de teste roda como superusuário. É o mesmo ponto cego
--: que a `0041`, a `0068` e a `0092` já cobraram.
--:
--: CONCEDER A COLUNA SERIA A SAÍDA FÁCIL E A ERRADA. A `0009` diz por quê: "o
--: que não pode é mexer nas colunas que decidem o que a pessoa alcança", e `oid`
--: é a identidade — quem o escrevesse trocaria de dono uma conta. Função
--: `security definer`, como a `0006` fez com `conceder_acesso`, deixa a
--: aplicação pedir o vínculo sem poder escrever a coluna.
--:
--: E A CONDIÇÃO NO `where` É O QUE TORNA ATÔMICO, que foi o segundo achado da
--: mesma revisão: dois logins concorrentes contra o MESMO pré-cadastro liam
--: `oid is null` os dois e o segundo sobrescrevia o `oid` do primeiro — ou seja,
--: a conta ia para a última identidade a chegar. Aqui o `update` casa uma linha
--: só; o segundo não casa nada e recebe nulo, e o chamador trata como "já
--: vinculada".
create or replace function vincular_pre_cadastro(
  p_email citext,
  p_oid   text
) returns uuid
language plpgsql
security definer
--: `search_path` FIXO: função `security definer` sem ele é a receita conhecida
--: de sequestro por tabela homônima no caminho de quem chama.
set search_path = public
as $$
declare
    achado uuid;
begin
    update usuario
       set entra_object_id = p_oid
     where email = p_email
       and entra_object_id is null
    returning id into achado;

    --: NULO NÃO DISTINGUE "não existe" de "já vinculada", e não precisa: quem
    --: chama consulta em seguida para escolher entre criar e recusar, e é lá que
    --: a recusa tem a mensagem certa.
    return achado;
end;
$$;

--: E A DONA DA FUNÇÃO PRECISA DA COLUNA, por `grant` de coluna como a `0006`
--: fez com as dela e a `0087` com `acesso_sensivel`. `security definer` roda
--: como a dona: sem isto a função levanta `permission denied for table usuario`
--: — o privilégio sai da aplicação e tem de entrar em alguém.
grant update (entra_object_id) on usuario to painel_concessao;

--: A POSSE PEDE `create on schema public`, e sem isto o `alter owner` falha —
--: mesmo passo da `0006`, da `0087` e da `0101`.
grant create on schema public to painel_concessao;
alter function vincular_pre_cadastro(citext, text) owner to painel_concessao;
revoke create on schema public from painel_concessao;

revoke all on function vincular_pre_cadastro(citext, text) from public;
grant execute on function vincular_pre_cadastro(citext, text) to painel_app;

comment on function vincular_pre_cadastro(citext, text) is
  'Liga o pre-cadastro deste e-mail ao `oid` do Entra, e SO se ele ainda nao '
  'tiver vinculo. Devolve o id da linha vinculada, ou nulo. Existe porque a '
  '0009 nao da `update` em `entra_object_id` a aplicacao -- e porque a condicao '
  'no `where` torna o vinculo atomico entre logins concorrentes.';

do $$
begin
    if exists (
        select 1 from information_schema.columns
         where table_name = 'usuario'
           and column_name = 'entra_object_id'
           and is_nullable = 'NO'
    ) then
        raise exception 'a 0119 nao soltou o not null de usuario.entra_object_id';
    end if;

    --: A APLICAÇÃO PRECISA EXECUTAR A FUNÇÃO, e sem isto o primeiro login de
    --: todo pré-cadastrado falha — em produção, e só lá.
    if not has_function_privilege(
        'painel_app', 'vincular_pre_cadastro(citext, text)', 'EXECUTE'
    ) then
        raise exception 'painel_app nao pode executar vincular_pre_cadastro';
    end if;

    --: E NÃO PODE ESCREVER A COLUNA, que é o ponto de usar a função. Conferir só
    --: o `execute` deixaria passar uma 0009 futura que afrouxasse o `grant`.
    if has_column_privilege('painel_app', 'usuario', 'entra_object_id', 'UPDATE') then
        raise exception
            'painel_app pode escrever usuario.entra_object_id: a funcao perdeu o sentido';
    end if;

    --: A DONA PRECISA, e esta é a conferência que a primeira versão desta
    --: migration não tinha: sem o `grant` de coluna a função levanta
    --: `permission denied for table usuario` no primeiro login de todo
    --: pré-cadastrado. Peguei pelos testes; em produção seria 500 silencioso.
    if not has_column_privilege(
        'painel_concessao', 'usuario', 'entra_object_id', 'UPDATE'
    ) then
        raise exception
            'painel_concessao nao pode escrever usuario.entra_object_id: vincular_pre_cadastro vai falhar';
    end if;

    raise notice 'pre-cadastro liberado: vinculo por funcao, coluna fechada';
end $$;

commit;
