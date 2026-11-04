--: `importacao` guardava QUEM SUBIU (`criado_por`) e QUANDO CONFIRMOU
--: (`confirmado_em`), e mais ninguém. Falta a terceira: quem confirmou.
--:
--: POR QUE ISSO IMPORTA AGORA. A aba da plataforma mostra uma linha por carga
--: com "quando" e "quem". Para as agendas, o "quando" é `confirmado_em` e o
--: "quem" só podia ser `criado_por` — e `importar_agendas.confirmar` NÃO exige
--: que quem confirma seja quem subiu. Então A sobe, B confirma, e a tela mostra
--: a hora de B com o nome de A. A linha parecia certa e não era.
--:
--: `confirmar` JÁ RECEBE O USUÁRIO (`confirmar(sessao, importacao_id, usuario)`)
--: e já escreve `confirmado_em` na mesma linha. A coluna só grava o que a função
--: tem na mão.
--:
--: NULÁVEL, e nulo tem dois significados que a tela distingue pela situação:
--: importação ainda não confirmada, ou confirmada ANTES desta migration. Para o
--: segundo caso a aba cai em `criado_por` e diz que é quem enviou o arquivo —
--: retroagir seria inventar.
--:
--: Idempotente.

begin;

alter table importacao
  add column if not exists confirmado_por uuid references usuario(id);

comment on column importacao.confirmado_por is
  'Quem apertou confirmar. Nulo em importacao nao confirmada, e tambem nas '
  'confirmadas antes da 0117 -- ai a trilha cai em `criado_por` e diz que e '
  'quem enviou o arquivo, porque e tudo o que a tabela guardou.';

--: `painel_app` já tem `select, insert, update` em `importacao` pelo `alter
--: default privileges` da `0009`, e coluna nova herda o privilégio da tabela.
--: Nada a conceder.

do $$
begin
    if not exists (
        select 1 from information_schema.columns
         where table_schema = 'public'
           and table_name = 'importacao'
           and column_name = 'confirmado_por'
    ) then
        raise exception 'importacao.confirmado_por nao foi criada';
    end if;

    raise notice 'importacao guarda quem confirmou';
end $$;

commit;
