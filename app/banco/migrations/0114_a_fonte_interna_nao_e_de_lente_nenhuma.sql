--: AS AGENDAS DO CRM FICAM NO CRM, e nenhuma lente se relaciona com elas
--: (decisão do dono do produto, 24/10/2026, nestas palavras: "os dados de
--: agendas do crm devem ficar somente no crm; os KPIs Reputacionais são
--: focados nesse momento em bases da Clipei, Bites e Approach. Esse isolamento
--: nesse momento deve ser claro").
--:
--: O QUE AINDA LIGAVA OS DOIS, depois de a `0112` aposentar a fonte. A linha
--: `crm` de `score_fonte` continuava apontando `lente_id = institucional`. Ela
--: não entrava mais na NOTA (`ativo = false`), mas a relação sobrevivia no
--: cadastro, e dela saíam duas coisas visíveis:
--:
--:   a aba Calibração do Score listava "CRM dos Stakeholders · Institucional",
--:   esmaecido e com selo "interna";
--:
--:   o Risk Tracking tratava as agendas como sendo DAQUELA lente — escolher
--:   "Institucional" naquela tela trazia reuniões no meio das matérias.
--:
--: POR QUE DESLIGAR DA LENTE, E NÃO APAGAR A LINHA. A fonte continua existindo
--: por três razões concretas: o Risk Tracking lê o NOME dela do cadastro para
--: rotular; a subida de planilha precisa conhecê-la para RECUSAR upload numa
--: fonte interna com a mensagem certa; e `score_fonte.id` é referenciado por
--: quatro tabelas. Apagar seria uma refatoração grande para ganhar o mesmo que
--: um `null` ganha aqui.
--:
--: `lente_id` VIRA OPCIONAL, e o significado é esse: "fonte que não alimenta
--: lente nenhuma". As leituras do código alcançam a coluna de três formas, e
--: `null` fica de fora das três: igualdade (`where ScoreFonte.lente_id ==
--: lente_id`), `in_(...)` e `join` com `lente`. Então o isolamento passa a ser
--: ESTRUTURAL, e não uma convenção que se pode esquecer.
--:
--: (ESTA NOTA DIZIA "todas as leituras comparam por igualdade", e era
--: imprecisa — achado da revisão do Codex. O comportamento é o mesmo nas três,
--: mas quem for conferir precisa saber que há `in_` e `join` também.)
--:
--: E É ISSO QUE FECHA A PORTA que uma revisão abriu: enquanto a relação
--: existia, religar a fonte (`ativo = true`, um `update` de uma coluna) devolvia
--: as agendas ao índice daquela lente. Agora religar não basta — e a política
--: em `dominio/fontes_do_score` é a outra metade da mesma tranca.
--:
--: O QUE ACONTECE NO DIA EM QUE ISTO SUBIR: a nota de nenhuma lente muda (a
--: fonte já não contava desde a `0112`), e o ÍNDICE não se move. O que muda na
--: tela é o Risk Tracking: as agendas deixam de ser incidente, então
--: "incidentes por mês" CAI nos meses que tinham reunião de clima tenso. Isso é
--: o pedido, não efeito colateral.
--:
--: COMO SE DESFAZ, e são os dois passos juntos — um só deixa o sistema
--: incoerente:
--:
--:   update score_fonte set lente_id = (select id from lente where codigo =
--:     'institucional'), ativo = true where codigo = 'crm';
--:
--: e `FONTE_INTERNA_ALIMENTA_OS_KPIS = True` em `app/dominio/fontes_do_score.py`.
--:
--: Idempotente.

begin;

alter table score_fonte alter column lente_id drop not null;

--: DE QUE LENTES AS FONTES INTERNAS ERAM, ANTES do `update` — é o escopo da
--: segunda conferência lá embaixo. Guardar antes é o que permite conferir só o
--: que ESTA migration mexeu.
--:
--: NUMA SEGUNDA EXECUÇÃO ela vem vazia, e isso é o correto: não há mais nada a
--: desligar, então não há nada a conferir. É assim que a conferência fica
--: idempotente junto com o `update`.
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
    --: A CONFERÊNCIA É PELA PERGUNTA QUE O CÓDIGO FAZ: "existe fonte interna
    --: ligada a alguma lente?". Se sobrar uma, esta migration não fez o que diz
    --: e o Risk Tracking volta a atribuir agenda a lente.
    select count(*) into internas_com_lente
      from score_fonte
     where interna and lente_id is not null;

    if internas_com_lente > 0 then
        raise exception
            'ainda ha % fonte(s) interna(s) ligada(s) a uma lente depois da 0114',
            internas_com_lente;
    end if;

    --: E NENHUMA LENTE PODE FICAR SEM FONTE *POR CAUSA DESTA MIGRATION*. O
    --: `update` acima é por `interna`, e não pelo código `crm`, justamente para
    --: não precisar de lista — mas isso significa que uma lente cuja ÚNICA
    --: fonte fosse interna ficaria sem nada de onde se medir. Hoje não é o caso
    --: (a Institucional tem a `clipei_institucional` desde a `0111`), e é
    --: melhor abortar do que descobrir pela tela vazia.
    --:
    --: SÓ AS LENTES QUE ESTA MIGRATION TOCOU, e é correção da revisão do Codex:
    --: a conferência era sobre TODAS as lentes, então um estado antigo e
    --: inválido — uma lente cadastrada sem fonte nenhuma, por qualquer outro
    --: motivo — abortaria esta migration reclamando de algo que ela não causou.
    --: É o mesmo erro que a `0112` já tinha cometido e corrigido na revisão
    --: dela, com estas palavras: "eu contava as fontes internas do sistema
    --: INTEIRO, então o dia em que alguém criasse uma fonte interna legítima em
    --: outra lente esta migration abortaria".
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
