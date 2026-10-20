--: O CRM SAI DO ÍNDICE, e a lente Institucional passa a ser só imprensa
--: (decisão do dono do produto, 20/10/2026, tomada depois de eu medir e
--: apresentar o preço: "CRM sai do índice").
--:
--: O QUE ISSO É, EXATAMENTE. A fonte `crm` é a ÚNICA interna do sistema: ela
--: não lê planilha e não grava `score_mes_fonte` — o score dela é recontado de
--: `interacao_registro` + `clima` a cada leitura. Aposentá-la tira as agendas
--: do índice inteiro; nenhuma outra lente as lê.
--:
--: APOSENTADA, NÃO APAGADA (`ativo = false`), como a `0061` fez com a categoria
--: antiga: as telas do CRM continuam iguais, as interações continuam sendo
--: registradas, a aba de riscos continua lendo agendas. O que para é a
--: contribuição delas para a NOTA.
--:
--: E `ativo` SIGNIFICA ALGO DIFERENTE AQUI, de propósito. Numa fonte de
--: planilha, `ativo = false` é "parou de receber importação" e o histórico
--: continua valendo, porque está gravado em `score_mes_fonte` — é o que
--: `catalogo_das_lentes` documenta e continua verdade. A fonte interna não tem
--: histórico gravado: ela é recontada toda vez. Para ela, aposentar só pode
--: significar "para de contar" — em todos os meses, inclusive os fechados.
--: `catalogo_das_lentes` e `repositorio_lentes.lente_e_interna` passaram a
--: respeitar `ativo` por isso, e as DUAS juntas: divergindo, a lente ficaria
--: partida (nota das menções, série do CRM).
--:
--: O QUE ACONTECE NO DIA EM QUE ISTO SUBIR, dito antes de alguém perguntar: a
--: lente Institucional fica SEM DADO enquanto nenhum veículo estiver
--: classificado como "Imprensa > Institucional". Lente sem dado sai do índice —
--: e sai TAMBÉM do denominador dos pesos (`calcular_indice`), então as outras
--: quatro passam a dividir 85 em vez de 100. O ISR de todos os meses muda: não
--: por queda de reputação, mas porque as agendas deixaram de contar.
--:
--: COMO SE DESFAZ: `update score_fonte set ativo = true where codigo = 'crm'`.
--: Nenhum dado foi apagado.
--:
--: Idempotente.

begin;

update score_fonte set ativo = false where codigo = 'crm';

do $$
declare
    ainda_interna int;
begin
    --: A CONFERÊNCIA É PELA PERGUNTA QUE O CÓDIGO FAZ: "esta lente tem fonte
    --: interna ATIVA?". Se sobrar uma, o índice continua somando agendas e esta
    --: migration não fez o que diz.
    --:
    --: SÓ NESTA LENTE, e é correção de revisão: eu contava as fontes internas
    --: do sistema INTEIRO, então o dia em que alguém criasse uma fonte interna
    --: legítima em outra lente esta migration abortaria — reclamando de algo
    --: que não tem nada a ver com o CRM, que ela acabou de aposentar
    --: corretamente.
    select count(*) into ainda_interna
      from score_fonte f
      join lente l on l.id = f.lente_id
     where l.codigo = 'institucional' and f.interna and f.ativo;

    if ainda_interna > 0 then
        raise exception
            'a lente institucional ainda tem % fonte(s) interna(s) ativa(s) depois da 0108',
            ainda_interna;
    end if;

    --: E A LENTE PRECISA TER COM QUE SE MEDIR DEPOIS: sem a fonte da `0107`,
    --: esta migration deixaria a Institucional sem fonte nenhuma — não vazia à
    --: espera de classificação, mas impossível de preencher.
    if not exists (
        select 1 from score_fonte f
          join lente l on l.id = f.lente_id
         where l.codigo = 'institucional' and f.ativo
           and f.mapeamento_colunas ->> 'lista_de_veiculos' = 'imprensa_institucional'
    ) then
        raise exception
            'a lente institucional ficaria sem fonte: a 0107 não criou clipei_institucional';
    end if;

    raise notice 'CRM fora do indice; a lente Institucional agora e imprensa recortada';
end $$;

commit;
