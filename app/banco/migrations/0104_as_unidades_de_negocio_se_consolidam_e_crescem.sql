-- =============================================================================
-- 0104 — Algumas unidades de negócio se consolidam, outras entram novas
--
-- CONSOLIDAÇÃO, por pedido (2026-10-19): as unidades que tinham subdivisão
-- numérica ou por bloco no nome passam a ser UMA só, sem o sufixo — a
-- subdivisão interna da concessão não é o corte que o produto usa:
--
--   Águas do Rio 1 + Águas do Rio 4              -> Águas do Rio
--   Ambiental Ceará 1 + Ambiental Ceará 2         -> Ambiental Ceará
--   Águas do Pará — Bloco A/B/C/D (quatro linhas) -> Águas do Pará
--
-- UMA DAS LINHAS SOBREVIVE (renomeada, com o `id` e o `ordem` que já tinha);
-- as outras são apagadas DEPOIS de repontar quem as referenciava
-- (`interacao`, `mencao`, `unidade_negocio_apelido`) para a sobrevivente —
-- nunca o contrário, porque apagar antes de repontar derrubaria a FK.
--
-- Nenhum apelido da `0099` aponta para as linhas que saem (conferido): a
-- tabela de apelidos não precisa de ajuste além do laço genérico abaixo.
-- =============================================================================

do $$
declare
  sobrevivente smallint;
  apagada      smallint;
begin
  -- Águas do Rio 1 + 4 -> Águas do Rio
  select id into sobrevivente from unidade_negocio where nome = 'Águas do Rio 1';
  if sobrevivente is not null then
    update unidade_negocio set nome = 'Águas do Rio' where id = sobrevivente;
    for apagada in select id from unidade_negocio where nome = 'Águas do Rio 4' loop
      update interacao set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      update mencao set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      update unidade_negocio_apelido set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      delete from unidade_negocio where id = apagada;
    end loop;
  end if;

  -- Ambiental Ceará 1 + 2 -> Ambiental Ceará
  select id into sobrevivente from unidade_negocio where nome = 'Ambiental Ceará 1';
  if sobrevivente is not null then
    update unidade_negocio set nome = 'Ambiental Ceará' where id = sobrevivente;
    for apagada in select id from unidade_negocio where nome = 'Ambiental Ceará 2' loop
      update interacao set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      update mencao set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      update unidade_negocio_apelido set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      delete from unidade_negocio where id = apagada;
    end loop;
  end if;

  -- Águas do Pará — Bloco A/B/C/D -> Águas do Pará
  select id into sobrevivente from unidade_negocio where nome = 'Águas do Pará — Bloco A';
  if sobrevivente is not null then
    update unidade_negocio set nome = 'Águas do Pará' where id = sobrevivente;
    for apagada in select id from unidade_negocio where nome like 'Águas do Pará — Bloco %' loop
      update interacao set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      update mencao set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      update unidade_negocio_apelido set unidade_negocio_id = sobrevivente where unidade_negocio_id = apagada;
      delete from unidade_negocio where id = apagada;
    end loop;
  end if;
end $$;


-- NOVAS UNIDADES, por pedido (2026-10-19) — lista trazida pelo dono do
-- produto. `Holding / corporativo` continua em primeiro, intocado.
insert into unidade_negocio (nome, ordem) values
  ('Águas de Sinop',                  30),
  ('Águas de Sorriso',                31),
  ('Águas de Matão',                  32),
  ('Águas de Timon',                  33),
  ('Ambiental Brusque',               34),
  ('Ambiental Crato',                 35),
  ('Águas de Primavera',              36),
  ('Águas de Ariquemes',              37),
  ('Águas de Barra do Garças',        38),
  ('Águas de Jaru',                   39),
  ('Águas de Pimenta Bueno',          40),
  ('Ambiental Serra',                 41),
  ('Mirante',                         42),
  ('Águas de Rolim de Moura',         43),
  ('Ambiental Vila Velha',            44),
  ('Águas de Buritis',                45),
  ('Águas de Holambra',               46),
  ('Ambiental Cariacica',             47),
  ('Ambiental Paraná',                48),
  ('Águas de Paranatinga',            49),
  ('Águas de São Francisco',          50),
  ('Águas de Diamantino',             51),
  ('Águas de Novo Progresso',         52),
  ('Águas de Pedra Preta',            53),
  ('Águas de Vera',                   54),
  ('Águas de Campo Verde',            55),
  ('Águas de Confresa',               56),
  ('Águas de Nortelândia',            57),
  ('Águas de Guarantã',               58),
  ('Águas de Matupá',                 59),
  ('Águas de Peixoto de Azevedo',     60),
  ('Águas de São José',               61)
on conflict (nome) do nothing;
