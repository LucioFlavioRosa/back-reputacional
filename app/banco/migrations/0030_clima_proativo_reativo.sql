--: PROATIVO / REATIVO, no lugar de PROPOSITIVO / TENSO.
--:
--: Só o RÓTULO muda — `codigo` continua 'propositivo'/'tenso'/'neutro', que é
--: o que o código (cores, agregações, regras de exceção) usa para reconhecer
--: cada clima. Mudar o `codigo` também exigiria caçar toda referência a ele
--: em `app/` e no front; mudar só o `nome` é o mesmo padrão já usado para
--: renomear rótulo de dicionário (ver `0011_ciclo_da_agenda.sql` e
--: `0018_situacao_objetiva.sql`).
--:
--: Idempotente (um `update` que já fixa o mesmo valor não muda nada ao rodar
--: de novo).

begin;

update clima set nome = 'Proativo' where codigo = 'propositivo';
update clima set nome = 'Reativo'  where codigo = 'tenso';

commit;
