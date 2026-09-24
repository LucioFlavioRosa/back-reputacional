--: POSITIVO / NEGATIVO, no lugar de PROATIVO / REATIVO.
--:
--: Só o RÓTULO muda de novo — `codigo` continua 'propositivo'/'tenso'/
--: 'neutro', pelo mesmo motivo da 0030: é o que o código (cores, agregações,
--: regras de exceção) usa para reconhecer cada clima, e trocar o `codigo`
--: exigiria caçar toda referência a ele em `app/` e no front.
--:
--: Idempotente (um `update` que já fixa o mesmo valor não muda nada ao rodar
--: de novo).

begin;

update clima set nome = 'Positivo' where codigo = 'propositivo';
update clima set nome = 'Negativo' where codigo = 'tenso';

commit;
