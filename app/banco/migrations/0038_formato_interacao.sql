--: "FORMATO DA INTERAÇÃO" — Mídia, Agenda de mercado, Agenda pública,
--: Manifestação formal, Evento, Visita, Reunião. RESPONDE "que tipo de
--: encontro foi esse", uma pergunta DIFERENTE da que `frente` responde
--: ("quem é a contraparte") — não é substituto dela, é ortogonal: uma
--: "Reunião" ou "Visita" acontece com qualquer frente (imprensa, investidor,
--: agente público...), então as duas colunas convivem, cada uma na sua
--: pergunta. Ver a planilha de referência do usuário (coluna "Áreas que
--: mais usam" mostra "Visita"/"Reunião" batendo em todas as frentes).
--:
--: MORA EM `interacao`, não em `instituicao`: é atributo do ENCONTRO em si,
--: não da contraparte — a mesma instituição pode gerar uma "Mídia" hoje e
--: uma "Reunião" semana que vem.
--:
--: NULÁVEL, SEM PREENCHIMENTO RETROATIVO: é campo novo, opcional por
--: enquanto — mesmo raciocínio de `categoria_publico_id` na 0036. O
--: histórico de interações fica sem essa classificação até alguém editar.
--:
--: Idempotente.

begin;

create table if not exists formato_interacao (
  id smallserial primary key, codigo text not null unique, nome text not null,
  ordem smallint not null, ativo boolean not null default true
);

insert into formato_interacao (codigo, nome, ordem) values
  ('midia', 'Mídia', 1),
  ('agenda_de_mercado', 'Agenda de mercado', 2),
  ('agenda_publica', 'Agenda pública', 3),
  ('manifestacao_formal', 'Manifestação formal', 4),
  ('evento', 'Evento', 5),
  ('visita', 'Visita', 6),
  ('reuniao', 'Reunião', 7)
on conflict (codigo) do nothing;

alter table interacao add column if not exists formato_interacao_id smallint references formato_interacao(id);

comment on column interacao.formato_interacao_id is
  'Que tipo de encontro foi esse (Mídia, Agenda de mercado, Evento...) — ortogonal a frente, não substitui. Nula em quem foi cadastrado antes desta coluna existir.';

commit;
