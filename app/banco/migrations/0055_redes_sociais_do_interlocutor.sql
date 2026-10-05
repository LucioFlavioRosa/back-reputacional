-- 0055 — as redes sociais de um contato, se ele tiver
--
-- UMA LISTA, e não cinco colunas fixas (X/Instagram/Facebook/LinkedIn/
-- YouTube): o pedido foi por um cadastro onde se acrescenta quantos links
-- quiser, de qualquer rede, um de cada vez — não uma caixa por rede. Uma
-- pessoa pode ter dois Instagrams, ou só um X, ou nenhum.
--
-- TEXTO LIVRE DENTRO DA LISTA, sem validar formato nem identificar a rede:
-- mesmo molde de `cargo`/`area` na mesma tabela — é informação que ajuda a
-- localizar a pessoa (e, no futuro, cruzar com o que a lente de Imprensa/
-- Sociedade digital capturou), não um campo que o sistema precisa
-- interpretar hoje.
--
-- ARRAY, e não uma tabela à parte (como `interlocutor_tema`): cada valor
-- aqui não é uma entidade que outra coisa no sistema referencia — é só uma
-- lista de texto presa a UM contato. Uma tabela própria exigiria id, FK e
-- um CRUD de linha a mais para o mesmo resultado.

alter table interlocutor
  add column if not exists redes_sociais text[] not null default '{}';

comment on column interlocutor.redes_sociais is
  'Links ou handles de redes sociais do contato, texto livre, zero ou mais. '
  'Não identifica a rede nem valida formato. Ver 0055.';
