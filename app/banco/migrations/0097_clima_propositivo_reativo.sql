--: PROPOSITIVO / REATIVO, no lugar de POSITIVO / NEGATIVO.
--:
--: Pedido do product owner: todo campo que dizia Positivo, Negativo e Neutro
--: passa a dizer Propositivo, Reativo e Neutro. Só o RÓTULO muda de novo —
--: `codigo` continua 'propositivo'/'tenso'/'neutro', pelo mesmo motivo da
--: 0030 e da 0047: é o que o código (cores, agregações, regras de exceção)
--: usa para reconhecer cada clima.
--:
--: A importação de agendas resolve o termômetro por `clima.nome`; os nomes
--: antigos ("Positivo", "Negativo", "Proativo") continuam aceitos por apelido
--: em `app/casos_de_uso/importar_agendas.py`.
--:
--: Idempotente (um `update` que já fixa o mesmo valor não muda nada ao rodar
--: de novo).

begin;

update clima set nome = 'Propositivo' where codigo = 'propositivo';
update clima set nome = 'Reativo' where codigo = 'tenso';

commit;
