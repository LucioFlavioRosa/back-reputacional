-- 0057 — Conferência entra como tipo de interação
--
-- Mesmo molde dos 7 formatos da 0038: só dado, a tabela e a FK já existem.

insert into formato_interacao (codigo, nome, ordem) values
  ('conferencia', 'Conferência', 9)
on conflict (codigo) do nothing;
