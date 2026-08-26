-- =============================================================================
-- 0009 — `painel_app`: o que a conta da aplicação pode fazer
--
-- ESTE ARQUIVO RODA POR ÚLTIMO, e isso é requisito, não acaso: os `grant on all
-- tables` abaixo só alcançam o que já existe. Toda migration que criar tabela
-- precisa vir ANTES desta.
--
-- POR QUE UM PAPEL RESTRITO
--
-- Conectar como superusuário significa que uma injeção de SQL bem-sucedida — ou
-- uma connection string vazada — não entrega os dados: entrega o servidor.
-- `drop table`, `copy ... to program`, leitura de arquivo do sistema.
--
-- Nada aqui impede a injeção. O que muda é o TETO do estrago quando ela
-- acontece.
--
-- SEM SENHA AQUI, DE PROPÓSITO
--
-- `painel_app` nasce `nologin`: é recipiente de permissão, não conta. A conta de
-- login é criada pela infraestrutura, com a senha vinda do Key Vault:
--
--     create role painel_api login password '<do Key Vault>';
--     grant painel_app to painel_api;
--
-- Senha em arquivo de migration entra no histórico do Git e não sai mais.
--
-- DOIS PONTOS QUE PARECEM DETALHE E NÃO SÃO
--
--   `delete` nas linhas FILHAS é obrigatório. As relações do ORM usam
--   `delete-orphan`: tirar um tema, tirar um porta-voz ou trocar a frente de um
--   registro emite `DELETE` de verdade. Revogar `delete` de tudo — "o sistema
--   usa soft delete" — pararia a aplicação. A suíte de testes NÃO pega isso,
--   porque roda como superusuário; quem cobre este caminho é
--   `tests/test_papel_restrito.py`, que conecta como `painel_app`.
--
--   `alter default privileges` alcança tabelas FUTURAS. Isso é o que evita
--   "permission denied for table" em produção depois de uma migration nova — e
--   é também por que as revogações de auditoria abaixo precisam ser explícitas:
--   sem elas, uma trilha nova nasceria gravável pela aplicação.
-- =============================================================================

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'painel_app') then
    create role painel_app nologin;
  end if;
end $$;

-- `current_database()` porque o nome muda entre desenvolvimento, teste e
-- produção, e a migration é a mesma nos três.
do $$
begin
  execute format('grant connect on database %I to painel_app', current_database());
end $$;

grant usage on schema public to painel_app;

-- Zera antes de conceder. Sem isto, reexecutar a migration depois de mudar as
-- regras acumularia as permissões antigas com as novas — e os `revoke` abaixo
-- deixariam de significar o que dizem.
revoke all on all tables in schema public from painel_app;
revoke all on all sequences in schema public from painel_app;


-- -- a linha de base -----------------------------------------------------------

grant select on all tables in schema public to painel_app;
grant insert, update on all tables in schema public to painel_app;
grant usage, select on all sequences in schema public to painel_app;


-- -- o que a aplicação PODE apagar ---------------------------------------------
--
-- Só linhas que pertencem a um agregado e são substituídas junto com ele. O
-- agregado em si nunca é removido: `interacao` usa `arquivado_em`.

grant delete on
  interacao_imprensa,
  interacao_institucional,
  interacao_legislativo,
  interacao_investidores,
  interacao_interna,
  interacao_tema,
  interacao_pessoa_aegea,
  interlocutor_tema,
  pessoa_aegea_tema
to painel_app;


-- -- a trilha de auditoria é só de leitura --------------------------------------
--
-- Quem escreve são os gatilhos de 0005, que rodam como `security definer` e não
-- dependem destes `grant`. Sem as revogações, quem tivesse a connection string
-- inseria linha falsa e reescrevia linha verdadeira — e a auditoria deixaria de
-- ser evidência de coisa nenhuma.
--
-- As sequences entram junto: `nextval` permitido deixa consumir números e abrir
-- buracos artificiais na numeração da trilha.

revoke insert, update, delete on interacao_auditoria from painel_app;
revoke all on sequence interacao_auditoria_id_seq from painel_app;
grant select on interacao_auditoria to painel_app;

revoke insert, update, delete on usuario_auditoria from painel_app;
revoke all on sequence usuario_auditoria_id_seq from painel_app;
grant select on usuario_auditoria to painel_app;


-- -- autorização não se altera pela aplicação -----------------------------------
--
-- A tela de administração de acessos escreve pela função `conceder_acesso`
-- (0006), e não por `update` direto. Com `grant` nestas colunas, quem tivesse a
-- connection string se promoveria dentro do banco.

revoke insert, update, delete on papel from painel_app;
revoke insert, update, delete on usuario_escopo from painel_app;

-- `usuario` é caso à parte: o provisionamento no primeiro login precisa CRIAR a
-- linha e atualizar `ultimo_acesso_em`. O que não pode é mexer nas colunas que
-- decidem o que a pessoa alcança.
revoke update on usuario from painel_app;
grant update (nome, email, ultimo_acesso_em, ativo) on usuario to painel_app;

grant execute on function conceder_acesso(
  uuid, uuid, text, boolean, boolean, date, text[], text[], timestamptz
) to painel_app;

-- -- schema sem aplicação -------------------------------------------------------
--
-- A importação da planilha não foi implementada (migration 0008). As tabelas
-- existem, e o `grant insert, update on all tables` acima as alcançaria — a
-- aplicação ganharia escrita numa área sem nenhum caso de uso que a justifique.
--
-- Permissão sem uso é permissão que ninguém revisa. Quem for implementar a
-- importação precisa conceder explicitamente aqui, e essa exigência é
-- deliberada: obriga a decisão a passar por este arquivo.
revoke insert, update, delete on importacao, importacao_linha from painel_app;


-- -- os registros que só crescem ------------------------------------------------
--
-- `acesso_log` e `relatorio` são append-only por natureza. Os dois respondem
-- "quem entrou" e "quem levou dados daqui"; poder alterá-los depois de gravados
-- é exatamente o que faria quem quisesse apagar o próprio rastro.

revoke update, delete on acesso_log from painel_app;
revoke update, delete on relatorio from painel_app;


-- -- tabelas futuras ------------------------------------------------------------
--
-- Sem isto, a próxima migration cria tabela invisível para a aplicação e o
-- sistema quebra em produção com "permission denied for table" — num caminho que
-- nenhum teste local percorreria, porque local roda como superusuário.
--
-- ATENÇÃO: vale apenas para objetos criados pelo MESMO papel que executou esta
-- migration. Se um dia as migrations passarem a rodar por outra conta, este
-- bloco precisa ser reexecutado por ela.
--
-- ATENÇÃO 2: uma trilha de auditoria nova nasce gravável por causa daqui, e
-- precisa de `revoke` explícito como os de cima. `tests/test_papel_restrito.py`
-- tem um teste que varre todas as tabelas `*_auditoria` e falha se alguma for
-- gravável — é o que impede o esquecimento.
alter default privileges in schema public
  grant select, insert, update on tables to painel_app;
alter default privileges in schema public
  grant usage, select on sequences to painel_app;

comment on role painel_app is
  'Papel da aplicação. Lê tudo; escreve nos dados de negócio; apaga apenas '
  'linhas filhas de agregado. Não altera auditoria nem autorização.';
