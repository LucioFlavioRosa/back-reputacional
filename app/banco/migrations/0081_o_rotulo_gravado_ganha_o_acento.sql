--: O RÓTULO JÁ GRAVADO GANHA O ACENTO.
--:
--: O QUE A TELA MOSTRAVA. "Unidade aegea" e "Nao identificado" — o nome da
--: companhia com minúscula e a palavra "não" sem o til. Os dois aparecem no
--: gráfico "Perfil de quem fala" e na fileira de filtros da aba de risco, na
--: tela do cliente.
--:
--: A CAUSA. `ROTULO_DO_CARGO` (Python) e `rotulo_do_cargo` (a tabela da `0076`)
--: não tinham entrada para `aegea`, `unidade_aegea` e `nao_identificado`. Sem
--: entrada, o rótulo é DERIVADO: `capitalize()` de um lado, `initcap` do outro.
--: Nenhum dos dois põe maiúscula na segunda palavra, e nenhum devolve acento.
--:
--: E POR QUE ISTO PRECISA DE MIGRATION, que foi achado de revisão: o rótulo não
--: é só exibido, ele é GRAVADO — em `mencao.perfil_autor` na ingestão e em
--: `instituicao.cargo` quando um perfil de rede nasce. Corrigir só o dicionário
--: faria a carga NOVA escrever "Unidade Aegea" e o histórico ficar com "Unidade
--: aegea", e o gráfico que agrupa por esse texto mostraria os dois como se
--: fossem perfis diferentes. Dividir uma série em duas em silêncio é pior que o
--: erro de grafia.
--:
--: MEDIDO NA BASE LOCAL, antes:
--:
--:     mencao.perfil_autor = 'Unidade aegea' ........  85
--:     mencao.perfil_autor = 'Nao identificado' ..... 288
--:     instituicao.cargo   = 'Unidade aegea' ........  11
--:     instituicao.cargo   = 'Nao identificado' .....  23
--:
--: PELO VALOR EXATO, e não por `initcap` ou `unaccent`: o conjunto é de três
--: rótulos conhecidos, e uma regra genérica mexeria em texto que alguém pode ter
--: escrito à mão. Trocar exatamente o que a derivação errada produziu é o que
--: deixa esta migration inócua na segunda passagem — e inócua numa base que
--: nunca teve o valor errado.
--:
--: `aegea` NÃO ENTRA NA TROCA: a derivação já produzia "Aegea", que é o rótulo
--: certo. A entrada foi para o dicionário por completude, e aqui não há o que
--: corrigir.

begin;

create temporary table rotulo_corrigido (errado text primary key, certo text not null)
    on commit drop;

insert into rotulo_corrigido (errado, certo) values
    ('Unidade aegea',    'Unidade Aegea'),
    ('Nao identificado', 'Não identificado');

update mencao m
   set perfil_autor = c.certo
  from rotulo_corrigido c
 where m.perfil_autor = c.errado;

update instituicao i
   set cargo = c.certo
  from rotulo_corrigido c
 where i.cargo = c.errado;

--: A VERIFICAÇÃO AVISA, E NÃO FALHA. Uma base que nunca ingeriu Bites não tem
--: nenhuma dessas linhas, e isso não é erro — é um ambiente que não passou por
--: aqui. Falhar deixaria o banco sem subir por causa de um acento.
do $$
declare
    restantes integer;
begin
    select count(*) into restantes
      from mencao
     where perfil_autor in ('Unidade aegea', 'Nao identificado');
    if restantes > 0 then
        raise notice 'ainda restam % menções com o rótulo sem acento', restantes;
    end if;
end
$$;

commit;
