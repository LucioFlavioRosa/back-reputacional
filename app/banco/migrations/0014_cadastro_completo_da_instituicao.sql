--: O CADASTRO PASSA A DIZER QUEM É A INSTITUIÇÃO E COMO SE FALA COM ELA.
--:
--: O cadastro tinha nome, tipo e abrangência — o suficiente para a instituição
--: aparecer no lugar certo, e nada além. Faltavam duas coisas que quem prepara
--: uma agenda procura:
--:
--:   1. O NOME COMPLETO. A base guarda a forma curta, que é como se fala e como
--:      a lista fica legível: "ABCON", "ANA", "CNI". Quem não convive com a
--:      sigla não sabe o que escolheu, e a lista de 56 nomes vira adivinhação.
--:
--:   2. O E-MAIL DE QUEM REPRESENTA. `interlocutor` guardava nome e cargo, e
--:      não como chegar na pessoa. Marcar uma agenda começa por escrever para
--:      alguém, e esse endereço vivia fora do sistema — na caixa de quem já
--:      tinha falado com ela antes.
--:
--: Os dois são anuláveis e sem preenchimento retroativo. O que veio da planilha
--: não tem nem um nem outro, e deduzi-los do nome seria escrever texto que
--: ninguém conferiu num campo que parece conferido.
--:
--: Idempotente, como as anteriores.

begin;

--: CORREÇÃO DE ROTA, e fica registrada em vez de escondida.
--:
--: A primeira versão desta migration acrescentou `descricao`, por leitura
--: errada do pedido — "descrição" e "nome completo" não são a mesma coisa: uma
--: é texto livre sobre o que a instituição faz, o outro é o nome dela por
--: extenso, e é este que responde "que ABCON é essa?".
--:
--: A coluna é removida porque nasceu há minutos e está com ZERO linhas
--: preenchidas (conferido antes). Deixá-la seria um campo que a tela não
--: escreve e ninguém sabe para que serve.
alter table instituicao drop column if exists descricao;

alter table instituicao add column if not exists nome_completo text;

comment on column instituicao.nome_completo is
  'O nome por extenso. `nome` guarda a forma curta, que e como se fala e como '
  'a lista fica legivel. Nulo no que veio da planilha.';

alter table interlocutor add column if not exists email text;

comment on column interlocutor.email is
  'Como se chega na pessoa. Marcar agenda comeca por escrever para alguem, e '
  'este endereco vivia fora do sistema. Nulo no que veio da planilha.';

commit;
