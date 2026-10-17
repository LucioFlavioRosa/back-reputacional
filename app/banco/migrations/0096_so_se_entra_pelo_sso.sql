-- =============================================================================
-- 0096 — A ENTRADA POR SENHA SAI. Só se entra pelo SSO.
--
-- A 0003 já dizia, no cabeçalho: "NUNCA EXISTE COLUNA DE SENHA. A autenticação
-- é SSO, sempre." E a MESMA migration criava `usuario.senha_hash` 158 linhas
-- abaixo. Não foi divergência que envelheceu: o arquivo se contradizia desde o
-- primeiro dia, e a varredura de 16/10/2026 foi quem reparou.
--
-- Esta migration faz a frase virar verdade.
--
-- O QUE SAI:
--   * `usuario.senha_hash`;
--   * a restrição `usuario_autentica_de_algum_jeito`, que aceitava "ou Entra ou
--     senha" — agora o Entra é o único caminho, e isso se diz com `not null`,
--     que é mais forte do que um check e dispensa-o;
--   * no código: `casos_de_uso/autenticar_por_senha.py` e a rota
--     `POST /api/auth/senha`.
--
-- ELA SE RECUSA A RODAR se trancar alguém. Em desenvolvimento, medido em
-- 16/10/2026: 4 usuários ativos, os 4 com `entra_object_id`, nenhum preso à
-- senha. Em produção eu NÃO consigo consultar, e é por isso que a guarda
-- existe: sem ela, uma conta que só tinha senha viraria uma conta que existe,
-- aparece na tela de acessos, tem papel — e não entra por caminho nenhum. É
-- exatamente a "conta fantasma" que o comentário da 0003 dizia estar evitando.
--
-- FALHAR É O COMPORTAMENTO CERTO AQUI. O pipeline interrompe o deploy quando as
-- migrations falham (`azure-pipelines.yml`: "As migrations falharam. O app NÃO
-- foi atualizado"), então o pior caso é um deploy que não sai — e não um
-- usuário que não entra. Quem vir esta exceção resolve dando `entra_object_id`
-- às contas listadas, ou desativando-as, e roda de novo.
--
-- `pgcrypto` FICA. Ela servia ao `crypt()` da senha, mas também é de onde vem
-- `gen_random_uuid()`, usado como default em meia dúzia de tabelas desde a
-- 0001. Removê-la quebraria inserção em todas elas.
--
-- O QUE ISTO CUSTA NA PILHA LOCAL, e está escrito aqui porque é a consequência
-- que ninguém lembra: a pilha de desenvolvimento sobe com o SSO desligado
-- (`ENTRA_TENANT_ID: nao-usado-o-sso-esta-desligado`) e entrava por senha, com
-- oito usuários semeados — um por papel. Sem senha, ela passa a usar
-- `AUTH_MOCK`, que provisiona UM usuário fixo pelo mesmo caminho do SSO real.
-- Trocar de papel deixa de ser "sair e entrar como outro" e passa a ser mudar
-- `AUTH_MOCK_PERFIL` e subir de novo.
-- =============================================================================

begin;

--: A GUARDA, antes de qualquer destruição. Dentro da transação: se ela
--: levantar, nada abaixo aconteceu.
do $$
declare
    presos int;
    quem   text;
begin
    select count(*), coalesce(string_agg(email, ', ' order by email), '')
      into presos, quem
      from usuario
     where entra_object_id is null;

    if presos > 0 then
        raise exception
            'A 0096 foi interrompida: % conta(s) entram SO por senha e ficariam '
            'sem caminho de entrada. Dê entra_object_id a elas, ou desative-as, '
            'e rode de novo. Contas: %', presos, quem;
    end if;
end $$;

--: O CHECK SAI ANTES DA COLUNA. Ele cita `senha_hash`; deixá-lo para depois
--: faria o `drop column` ter de derrubá-lo em cascata, e cascata é onde some o
--: que ninguém queria perder.
alter table usuario
    drop constraint if exists usuario_autentica_de_algum_jeito;

--: AGORA O ENTRA É OBRIGATÓRIO, e isto é o que a 0003 queria dizer. Mais forte
--: que um check com `or`: não há segundo caminho para existir.
alter table usuario
    alter column entra_object_id set not null;

alter table usuario
    drop column if exists senha_hash;

comment on column usuario.entra_object_id is
  'O `oid` do Entra ID. Obrigatório desde a 0096: é o ÚNICO caminho de entrada. '
  'A coluna `senha_hash` existiu da 0003 à 0096.';

commit;
