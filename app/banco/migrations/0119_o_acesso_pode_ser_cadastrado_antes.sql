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
--: cujo e-mail verificado casar. A linha sem `oid` não é um beco, é um
--: pré-cadastro à espera.
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
  'primeiro login cujo e-mail verificado casar -- ver `provisionar_usuario`.';

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

    raise notice 'pre-cadastro liberado: entra_object_id aceita nulo';
end $$;

commit;
