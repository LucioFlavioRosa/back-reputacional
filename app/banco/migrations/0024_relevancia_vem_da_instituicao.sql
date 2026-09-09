-- A RELEVÂNCIA DAS 99 INSTITUIÇÕES, RECUPERADA DAS AGENDAS
--
-- A 0023 criou `instituicao.tier` e deixou as 99 existentes sem valor. Agora
-- que a agenda TIRA a relevância da instituição em vez de perguntar, deixá-las
-- nulas faria toda agenda nova nascer sem tier — e o painel conta Tier 1.
--
-- O VALOR NÃO É INVENTADO: vem do que essas mesmas pessoas escreveram. Cada
-- instituição recebe o tier MAIS FREQUENTE entre as agendas dela.
--
-- E É JUSTAMENTE POR ISSO QUE O CAMPO MUDOU DE LUGAR: medido nesta base, 54
-- das 98 instituições com histórico foram classificadas de formas DIFERENTES
-- em agendas diferentes. A pergunta era refeita a cada reunião e respondida
-- conforme o dia. A moda é a resposta que a área mais deu.
--
-- Empate resolvido pelo tier MAIS ALTO (menor número): entre classificar de
-- menos e de mais uma instituição que a própria área não decidiu, errar para o
-- lado do cuidado custa uma revisão; o contrário custa uma ausência no radar.
--
-- SÓ ONDE ESTÁ NULO. Quem já foi classificado à mão no cadastro fica como
-- está — é decisão de gente, e ela vence a estatística.
--
-- As agendas MANTÊM o tier que têm: são registro do que foi, e reescrevê-las
-- apagaria a informação que este próprio `update` acabou de usar.
--
-- Idempotente: na segunda rodada não há mais nulo para preencher.

begin;

with mais_frequente as (
  select distinct on (instituicao_id)
         instituicao_id,
         tier
    from (
      select instituicao_id, tier, count(*) as vezes
        from interacao
       where tier is not null
         and instituicao_id is not null
       group by instituicao_id, tier
    ) contagem
   order by instituicao_id, vezes desc, tier asc
)
update instituicao
   set tier = mais_frequente.tier
  from mais_frequente
 where instituicao.id = mais_frequente.instituicao_id
   and instituicao.tier is null;

commit;
