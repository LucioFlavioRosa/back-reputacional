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
--: lente nenhuma". Todas as leituras do código comparam `lente_id` por
--: igualdade (`where ScoreFonte.lente_id == lente_id`), e `null` não casa com
--: nada — então o isolamento passa a ser ESTRUTURAL, e não uma convenção que
--: se pode esquecer. `lentes_das_fontes` faz `join` com `lente` e a linha
--: simplesmente sai do mapa.
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

    --: E NENHUMA LENTE PODE FICAR SEM FONTE. O `update` acima é por `interna`,
    --: e não pelo código `crm`, justamente para não precisar de lista — mas
    --: isso significa que uma lente cuja ÚNICA fonte fosse interna ficaria sem
    --: nada de onde se medir. Hoje não é o caso (a Institucional tem a
    --: `clipei_institucional` desde a `0111`), e é melhor abortar do que
    --: descobrir pela tela vazia.
    select string_agg(l.codigo, ', ' order by l.codigo) into lentes_sem_fonte
      from lente l
     where not exists (select 1 from score_fonte f where f.lente_id = l.id);

    if lentes_sem_fonte is not null then
        raise exception
            'a 0114 deixaria sem fonte nenhuma a(s) lente(s): %', lentes_sem_fonte;
    end if;

    raise notice 'fonte interna desligada de lente; as agendas ficam no CRM';
end $$;

commit;
