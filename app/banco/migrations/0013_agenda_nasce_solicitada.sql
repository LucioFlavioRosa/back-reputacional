--: A AGENDA NASCE COM O QUE IDENTIFICA, E O RESTO VEM DEPOIS.
--:
--: Criar uma agenda exigia preencher cinco campos espalhados por três seções —
--: data, veículo/órgão e abrangência na identificação, mais status e pauta em
--: seções que só fazem sentido depois. Quem pede uma agenda de manhã sabe com
--: quem e quando; não sabe ainda o que vai sair dela.
--:
--: Duas mudanças, e as duas tiram obrigatoriedade de onde ela não pertencia.
--:
--: Idempotente, como as anteriores.

begin;

--: =============================================================================
--: 1. O ESTADO EM QUE UMA AGENDA COMEÇA
--: =============================================================================
--: O dicionário tinha `agendado`, `em_analise`, `aguardando_*`, `confirmada`,
--: `realizado` e `declinado`. Faltava o primeiro de todos.
--:
--: `agendado` afirma que existe data marcada com a outra parte — coisa que
--: ninguém confirmou no instante em que a agenda é criada. Usá-lo como padrão
--: encheria a base de reuniões dizendo que estão marcadas quando só foram
--: pedidas, e é justamente essa distinção que o ciclo existe para medir.
--:
--: Mesmo motivo pelo qual a 0011 acrescentou `confirmada`: a diferença entre
--: "pedimos e estamos esperando" e "as duas partes confirmaram".
--:
--: `ordem = 0` porque `agendado` e 1, e nao 10: escrevi 5 primeiro, achando que
--: havia folga entre eles, e o estado inicial caiu DEPOIS do agendado na lista.
--: Zero e o unico valor livre antes do primeiro — renumerar os existentes
--: mexeria em linhas que ninguem pediu para mexer.
insert into status (codigo, nome, grupo, ordem)
values ('solicitado', 'Solicitado', 'aberto', 0)
on conflict (codigo) do nothing;

--: Corrige quem ja rodou a primeira versao desta migration, com ordem 5.
update status set ordem = 0 where codigo = 'solicitado' and ordem <> 0;

comment on table status is
  'Os estados de uma agenda. A ordem e a do CICLO — solicitado, agendado, '
  'confirmada, realizado — e nao a de cadastro.';

--: =============================================================================
--: 2. A PAUTA DEIXA DE SER OBRIGATÓRIA
--: =============================================================================
--: Ela saiu da tela: `Temas` diz o assunto de forma classificada — que é o que
--: o painel consegue somar — e `Expectativa` diz o que se quer dele. Pauta era
--: a terceira forma de dizer a mesma coisa, e a única que ninguém consegue
--: agregar.
--:
--: A COLUNA FICA, e os 60 registros que vieram da planilha mantêm a delas. Ela
--: continua sendo o título do registro na Base quando existe; quando não
--: existe, a tela mostra os temas no lugar. Dropar a coluna apagaria o texto
--: que a planilha trouxe, que é a única descrição em palavras que esses
--: registros têm.
--:
--: `drop not null` é reversível: voltar exige preencher as linhas nulas antes,
--: e é por isso que o caminho de volta não é automático.
alter table interacao alter column pauta drop not null;

comment on column interacao.pauta is
  'O assunto em palavras. NULO no que foi criado pela tela depois da 0013 — '
  'ali quem diz o assunto sao `interacao_tema` e `expectativa`. Preenchida no '
  'que veio da planilha.';

commit;
