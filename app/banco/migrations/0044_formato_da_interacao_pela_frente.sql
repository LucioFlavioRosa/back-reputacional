-- =============================================================================
-- 0044 — A interação sem formato ganha o formato mais provável da frente.
--
-- A 0038 criou o formato "sem preenchimento retroativo": o acervo inteiro
-- ficou `null`, e "Tipo de Interação" — filtro e gráfico do Painel — saía
-- vazio para tudo que não fosse cadastrado depois. Coerência entre o que a
-- plataforma mostra e o que está cadastrado pede um valor; este é o palpite
-- por frente, o mesmo de `FORMATO_PADRAO_DA_FRENTE` em
-- `app/dominio/frentes.py` (o teste dos espelhos confere par a par):
--
--   imprensa → Mídia · eventos → Evento · investidores, bancos_credores →
--   Agenda de mercado · governo, legislativo → Agenda pública · parceiros,
--   interna → Reunião
--
-- Só onde está `null`; quem já escolheu o formato não é tocado, e quem
-- discordar corrige na edição da agenda. Idempotente.
-- =============================================================================

begin;

update interacao i
   set formato_interacao_id = fi.id
  from frente f, formato_interacao fi
 where f.id = i.frente_id
   and i.formato_interacao_id is null
   and fi.codigo = case f.codigo
                     when 'imprensa'        then 'midia'
                     when 'eventos'         then 'evento'
                     when 'investidores'    then 'agenda_de_mercado'
                     when 'bancos_credores' then 'agenda_de_mercado'
                     when 'governo'         then 'agenda_publica'
                     when 'legislativo'     then 'agenda_publica'
                     when 'parceiros'       then 'reuniao'
                     when 'interna'         then 'reuniao'
                   end;

commit;
