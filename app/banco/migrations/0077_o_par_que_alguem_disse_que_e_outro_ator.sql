--: O PAR QUE ALGUÉM OLHOU E DISSE: são atores diferentes.
--:
--: POR QUE ESTA TABELA EXISTE. A `0076` fundiu os 30 homônimos exatos, que não
--: pedem julgamento. Sobraram ~66 pares que só casam depois de tirar pontuação
--: e espaço — `valoreconomico` ↔ `Valor Econômico` é o mesmo ator; `Diário SM`
--: ↔ `Diários M` pode não ser; `bmc.news` casa com DOIS veículos. Esses vão
--: para uma tela, e quem conhece o ator decide.
--:
--: UMA TELA SEM ISTO NUNCA CHEGA A ZERO: o par que a pessoa olhou e recusou
--: volta na próxima abertura, idêntico, para sempre. A fila deixa de ser fila e
--: passa a ser ruído — e o ruído é o que faz ninguém olhar.
--:
--: E A DECISÃO VALE MAIS QUE A TELA: "estes dois são atores diferentes" é
--: conhecimento sobre o mundo, não estado de interface. Guardado, ele também
--: protege de uma fusão automática futura: qualquer regra nova que resolva
--: casar por semelhança tem de consultar isto primeiro.
--:
--: O PAR NÃO TEM LADO: dizer que A é diferente de B é dizer que B é diferente
--: de A. Guardado sempre na mesma ordem (`esquerda < direita`, pelo uuid), o
--: que faz a chave primária recusar a repetição sozinha, sem a aplicação ter
--: de procurar nas duas direções.
--:
--: `on delete cascade` porque, apagada a instituição, o par deixou de existir —
--: não é histórico de nada, é a ausência de uma pergunta.
--:
--: Idempotente.

begin;

create table if not exists ator_distinto (
  esquerda uuid not null references instituicao(id) on delete cascade,
  direita uuid not null references instituicao(id) on delete cascade,
  --: POR QUE, quando quem decidiu quis escrever. A tela não obriga.
  motivo text,
  decidido_por uuid references usuario(id),
  decidido_em timestamptz not null default now(),
  primary key (esquerda, direita),
  constraint ator_distinto_em_ordem check (esquerda < direita)
);

comment on table ator_distinto is
  'Pares de cadastro que alguem olhou e declarou atores diferentes. Tira o par '
  'da fila de duplicados e barra fusao automatica futura.';

commit;
