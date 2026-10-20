--: PROATIVO / REATIVO, de novo no lugar de POSITIVO / NEGATIVO (por pedido,
--: 19/10/2026).
--:
--: Só o RÓTULO muda — `codigo` continua 'propositivo'/'tenso'/'neutro', que é
--: o que o código (cores, agregações, regras de exceção) usa para reconhecer
--: cada clima. Mudar o `codigo` também exigiria caçar toda referência a ele
--: em `app/` e no front; mudar só o `nome` é o mesmo padrão já usado em
--: `0030_clima_proativo_reativo.sql` e `0047_clima_positivo_negativo.sql` —
--: esta migration volta aos valores exatos da `0030`.
--:
--: Idempotente (um `update` que já fixa o mesmo valor não muda nada ao rodar
--: de novo).

begin;

update clima set nome = 'Proativo' where codigo = 'propositivo';
update clima set nome = 'Reativo'  where codigo = 'tenso';

commit;
