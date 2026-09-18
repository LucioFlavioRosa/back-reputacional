-- =============================================================================
-- 0041 — `interacao_area` ganha o que todo vínculo da agenda tem: `delete`
--        para a aplicação e trilha de auditoria.
--
-- A 0032 criou a tabela no padrão de `interacao_tema` — e parou antes das duas
-- linhas que fazem esse padrão funcionar em produção:
--
-- 1. DELETE PARA `painel_app`. Trocar as áreas de uma agenda é apagar linhas
--    desta tabela (`delete-orphan` em `InteracaoRegistro.areas`), e as
--    `alter default privileges` da 0009 concedem só select/insert/update. Em
--    desenvolvimento ninguém nota, porque tudo roda como superusuário; com a
--    conta restrita, tirar uma área de uma agenda devolve "permission denied"
--    — e só na hora de salvar. É exatamente o aviso em negrito do README, e
--    o mesmo acerto que 0011 (`interacao_interlocutor`) e 0027
--    (`material_tema`) fizeram ao nascer.
--
-- 2. AUDITORIA. Tema, porta-voz e participante da outra parte registram quem
--    entrou e quem saiu da agenda (`registrar_vinculo`, 0005 e 0011). Área
--    interna é a mesma natureza de fato, influencia Painel e filtros, e
--    mudava em silêncio.
--
-- `registrar_vinculo()` é redefinida porque o valor gravado dependia do nome
-- da tabela e caía em `tema_id` para qualquer outra: `interacao_area` teria
-- trilha com valor nulo — e `interacao_interlocutor`, auditada desde 0011,
-- JÁ ESTAVA gravando nulo por esse mesmo caminho. A nova versão nomeia a
-- coluna de cada vínculo e mantém `tg_table_name` como último recurso.
--
-- NÃO ALTERA A 0032, já aplicada. Idempotente: `grant` repetido é inócuo,
-- `create or replace` substitui, `drop trigger if exists` antes do `create`.
-- =============================================================================

begin;

grant delete on interacao_area to painel_app;

create or replace function registrar_vinculo()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  linha  jsonb := to_jsonb(coalesce(new, old));
  rotulo text := case tg_table_name
                   when 'interacao_tema'         then 'tema'
                   when 'interacao_pessoa_aegea' then 'participacao'
                   when 'interacao_interlocutor' then 'interlocutor'
                   when 'interacao_area'         then 'area'
                   else tg_table_name
                 end;
  valor  text;
  autor  uuid;
begin
  valor := case tg_table_name
             when 'interacao_pessoa_aegea' then
               (linha ->> 'pessoa_aegea_id') || ' (' || coalesce(linha ->> 'papel', '?') || ')'
             when 'interacao_interlocutor' then linha ->> 'interlocutor_id'
             when 'interacao_area'         then linha ->> 'area_id'
             else                               linha ->> 'tema_id'
           end;

  begin
    autor := nullif(current_setting('painel.usuario_id', true), '')::uuid;
  exception when others then
    autor := null;
  end;

  insert into interacao_auditoria
    (interacao_id, usuario_id, campo, valor_anterior, valor_novo, origem)
  values (
    (linha ->> 'interacao_id')::uuid,
    autor,
    rotulo,
    case when tg_op = 'DELETE' then valor end,
    case when tg_op = 'INSERT' then valor end,
    session_user
  );

  return coalesce(new, old);
end;
$$;

-- `create or replace` preserva o dono; explícito mesmo assim, porque é a posse
-- que faz o `security definer` escrever na trilha que `painel_app` não alcança.
alter function registrar_vinculo() owner to painel_auditoria;

drop trigger if exists auditar_interacao_area on interacao_area;
create trigger auditar_interacao_area
  after insert or delete on interacao_area
  for each row execute function registrar_vinculo();

commit;
