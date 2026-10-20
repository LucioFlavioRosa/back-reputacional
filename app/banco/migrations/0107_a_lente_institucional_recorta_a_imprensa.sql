--: A LENTE INSTITUCIONAL PASSA A LER A IMPRENSA, recortada pela subcategoria
--: "Institucional" (pedido de 20/10/2026: "na lente Institucional, o filtro que
--: deve ser utilizado será Imprensa > Institucional, assim como fizemos para a
--: lente mercado").
--:
--: O MESMO MECANISMO DA MERCADO, e não um parecido. A fonte nova lê o MESMO
--: arquivo e a MESMA aba da Clipei, e difere dela só pela lista: é isso que faz
--: `espelho_de` achar a `clipei` como espelho e a reconciliação retroativa
--: funcionar sem nenhuma linha nova de motor — exatamente como em
--: `clipei_investidores` (`0067`).
--:
--: O MAPEAMENTO É DERIVADO DA `clipei`, e não copiado. Duas cópias do mesmo
--: mapeamento divergem no dia em que o fornecedor renomear uma coluna e alguém
--: consertar só uma — e aí as duas fontes passam a ler versões diferentes do
--: mesmo arquivo. Aqui a cópia acontece UMA vez, no `insert`; o que se garante
--: é que ela nasce idêntica.
--:
--: O CRM CONTINUA NESTA LENTE, POR ENQUANTO. O dono do produto decidiu que ele
--: sai do índice, e isso é a PARTE SEGUINTE: ela mexe em como a lente é medida
--: e derruba os testes que afirmam a regra antiga. Esta migration é aditiva —
--: enquanto nenhum veículo estiver classificado como "Institucional", a lente
--: continua medindo exatamente o que media hoje.
--:
--: NADA MUDA NOS MESES JÁ GRAVADOS por esta migration: a ingestão é que
--: recorta, e o histórico se move pela reconciliação — que é gesto de quem
--: opera, com prévia antes, e não efeito colateral de um `insert`.
--:
--: Idempotente.

begin;

insert into score_fonte (codigo, nome, fornecedor, lente_id, tipo_arquivo, mapeamento_colunas, interna, ordem)
select
  'clipei_institucional',
  'Clipei · imprensa institucional',
  clipei.fornecedor,
  (select id from lente where codigo = 'institucional'),
  clipei.tipo_arquivo,
  clipei.mapeamento_colunas || jsonb_build_object('lista_de_veiculos', 'imprensa_institucional'),
  false,
  7
from score_fonte clipei
where clipei.codigo = 'clipei'
on conflict (codigo) do nothing;

do $$
declare
    nova record;
    espelho record;
begin
    select mapeamento_colunas ->> 'lista_de_veiculos' as lista,
           mapeamento_colunas ->> 'arquivo'           as arquivo,
           mapeamento_colunas ->> 'aba'               as aba,
           lente_id
      into nova
      from score_fonte where codigo = 'clipei_institucional';

    --: `found`, E NÃO `nova is null`: um RECORD sem linha tem todos os campos
    --: nulos, e `is null` sobre ele depende da semântica de ROW — `found` diz
    --: exatamente o que se quer perguntar.
    if not found then
        --: A `clipei` não existe nesta base (ou não foi semeada): não há de que
        --: derivar, e parar aqui impediria o banco de subir.
        raise notice 'clipei não encontrada — a fonte institucional não foi criada';
        return;
    end if;

    select mapeamento_colunas ->> 'arquivo' as arquivo,
           mapeamento_colunas ->> 'aba'     as aba
      into espelho
      from score_fonte where codigo = 'clipei';

    --: O ESPELHO É O QUE FAZ A RECONCILIAÇÃO EXISTIR: sem arquivo e aba iguais
    --: aos da `clipei`, `espelho_de` não acha par e a lista nunca vale para
    --: trás. Falhar aqui é melhor do que descobrir isso na tela, vazia.
    if nova.arquivo is distinct from espelho.arquivo or nova.aba is distinct from espelho.aba then
        raise exception
            'a fonte institucional não espelha a clipei: arquivo=%/% aba=%/%',
            nova.arquivo, espelho.arquivo, nova.aba, espelho.aba;
    end if;

    if nova.lista <> 'imprensa_institucional' then
        raise exception 'a fonte institucional não recorta pela lista certa: %', nova.lista;
    end if;

    if nova.lente_id is distinct from (select id from lente where codigo = 'institucional') then
        raise exception 'a fonte institucional nasceu na lente errada';
    end if;

    raise notice 'lente Institucional recortando a imprensa por lista de veiculos';
end $$;

commit;
