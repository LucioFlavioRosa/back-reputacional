--: ONDE A AGENDA ACONTECE.
--:
--: A agenda dizia COM QUEM, QUANDO e SOBRE O QUÊ, e não dizia ONDE. Quem vai à
--: reunião precisa do endereço, e quem lê a base depois precisa saber se foi
--: presencial ou por chamada — não é a mesma conversa, e a diferença muda a
--: leitura de quase tudo: presença, clima e quem de fato participou.
--:
--: DUAS COLUNAS, E NÃO UMA. "Presencial" e "o endereço" respondem perguntas
--: diferentes: a modalidade se agrega (quantas foram presenciais neste
--: trimestre?), e o endereço não. Guardar só o texto obrigaria a adivinhar a
--: modalidade lendo o campo — "Teams" é online, "Brasília" é presencial, e
--: "sala 4" não é nada.
--:
--: Idempotente, como as anteriores.

begin;

--: `presencial` | `online` | `hibrida`.
--:
--: Híbrida existe porque acontece: parte da mesa na sala e parte na chamada, e
--: forçá-la a escolher um dos dois faria a base afirmar algo falso. NULO é
--: NÃO INFORMADO — as agendas que vieram da planilha não responderam isto, e
--: tratá-las como presenciais inventaria história.
alter table interacao add column if not exists modalidade text;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'interacao_modalidade_valida'
  ) then
    alter table interacao
      add constraint interacao_modalidade_valida
      check (modalidade is null or modalidade in ('presencial', 'online', 'hibrida'));
  end if;
end $$;

comment on column interacao.modalidade is
  'presencial | online | hibrida. NULO e NAO INFORMADO — o que veio da '
  'planilha nao respondeu, e supor presencial inventaria historia.';

--: O ENDEREÇO, EM TEXTO LIVRE.
--:
--: Não é um campo estruturado de logradouro e número: uma agenda acontece em
--: "Ministério das Cidades, bloco A, 5º andar" tanto quanto em "Teams" ou "sala
--: do conselho". Estruturar exigiria decidir o que fazer com os dois últimos, e
--: a resposta seria um endereço vazio com a informação real perdida.
alter table interacao add column if not exists local text;

comment on column interacao.local is
  'Onde a agenda acontece, em palavras: endereco, sala, ou o link da chamada. '
  'Texto livre de proposito.';

commit;
