--: A fonte interna deixa de estar vinculada a uma lente: as agendas do CRM
--: ficam no CRM. A `0112` já a havia aposentado (`ativo = false`), mas o vínculo com a
--: lente sobrevivia no cadastro, e dele saíam duas coisas visíveis: a linha
--: "CRM dos Stakeholders · Institucional" na aba Calibração, e as agendas
--: atribuídas àquela lente no Risk Tracking.
--:
--: `lente_id` nula significa "fonte que não alimenta lente nenhuma". As
--: leituras alcançam a coluna por igualdade, `in_` e `join`, e nulo fica de
--: fora das três: o isolamento é estrutural, não convenção.
--:
--: A linha não é apagada porque o Risk Tracking lê o nome dela para rotular, a
--: subida de planilha precisa conhecê-la para recusar upload em fonte interna,
--: e `score_fonte.id` é referenciado por quatro tabelas.
--:
--: Efeito ao subir: nenhuma nota muda, porque a fonte já não contava. No Risk
--: Tracking, "incidentes por mês" cai nos meses que tinham reunião de clima
--: tenso.
--:
--: Para reverter o comportamento, faça os dois passos juntos:
--:
--:   update score_fonte set lente_id = (select id from lente where codigo =
--:     'institucional'), ativo = true where codigo = 'crm';
--:
--: e `FONTE_INTERNA_ALIMENTA_OS_KPIS = True` em `app/dominio/fontes_do_score.py`.
--:
--: Idempotente.

begin;

alter table score_fonte alter column lente_id drop not null;

--: De que lentes as fontes internas eram ANTES do `update`: é o escopo da
--: segunda conferência lá embaixo. Numa segunda execução vem vazia, e aí não
--: há nada a conferir — é o que torna a conferência idempotente.
create temporary table fontes_internas_antes on commit drop as
select distinct lente_id
  from score_fonte
 where interna and lente_id is not null;

update score_fonte set lente_id = null where interna;

do $$
declare
    internas_com_lente int;
    lentes_sem_fonte text;
begin
    --: Sobrou fonte interna ligada a alguma lente? Se sim, esta migration não
    --: fez o que diz e o Risk Tracking volta a atribuir agenda a lente.
    select count(*) into internas_com_lente
      from score_fonte
     where interna and lente_id is not null;

    if internas_com_lente > 0 then
        raise exception
            'ainda ha % fonte(s) interna(s) ligada(s) a uma lente depois da 0114',
            internas_com_lente;
    end if;

    --: E nenhuma lente pode ficar sem fonte por causa desta migration. O
    --: `update` é por `interna` e não pelo código `crm`, para não precisar de
    --: lista — mas isso significa que uma lente cuja única fonte fosse interna
    --: ficaria sem nada de onde se medir. Melhor abortar do que descobrir pela
    --: tela vazia.
    --:
    --: Só as lentes que esta migration tocou: sobre TODAS, um estado antigo e
    --: inválido abortaria a migration reclamando de algo que ela não causou.
    select string_agg(l.codigo, ', ' order by l.codigo) into lentes_sem_fonte
      from lente l
     where l.id in (select lente_id from fontes_internas_antes)
       and not exists (select 1 from score_fonte f where f.lente_id = l.id);

    if lentes_sem_fonte is not null then
        raise exception
            'a 0114 deixaria sem fonte nenhuma a(s) lente(s): %', lentes_sem_fonte;
    end if;

    raise notice 'fonte interna desligada de lente; as agendas ficam no CRM';
end $$;

commit;
