--: A CLIPEI PASSA A TRAZER CINCO COLUNAS QUE ELA SEMPRE MANDOU.
--:
--: O export da Clipei tem 25 colunas e o cadastro da fonte aproveitava 7. Cinco
--: das 18 restantes vêm preenchidas em 100% das linhas e têm campo esperando em
--: `mencao` desde a `0055` — e estavam sendo jogadas fora:
--:
--:     ID                 -> id_fonte      a CHAVE DE DEDUPLICAÇÃO
--:     Arquivo/Link       -> link          o endereço da matéria
--:     Título             -> titulo_texto  a manchete
--:     Estado do Veículo  -> uf            a praça do veículo
--:     Empresa            -> unidade_texto a concessionária
--:
--: O `id_fonte` É O MAIS IMPORTANTE. O índice `mencao_do_fornecedor_uma_vez`
--: existe desde a `0055` para impedir que a mesma menção entre duas vezes, e sem
--: `id_fonte` ele nunca protegeu nada: o `where id_fonte is not null` o desligava
--: em toda linha. Medido no arquivo de 08–09/2026: 25.597 IDs distintos em 25.597
--: linhas, zero repetição — a chave é confiável.
--:
--: O `link` tem consumidor esperando: `app/api/lentes.py` já pede
--: `coluna_do_link="link"` para o dossiê da lente, e recebia nulo sempre.
--:
--: POR QUE O CADASTRO E NÃO SÓ O CÓDIGO. Mapear coluna é cadastro da fonte, e
--: mora em `score_fonte.mapeamento_colunas`. Mas isto SÓ FUNCIONA junto com a
--: mudança em `app/dominio/ingestao_score.py::ler_linha`, que até agora ignorava
--: os seis campos do "padrão Aegea" mesmo quando mapeados — eram declarados em
--: `CAMPOS`, tinham campo em `MencaoLida`, coluna na tabela, e ninguém os lia.
--: Medido antes: `link`, `id_fonte`, `titulo_texto` e `uf` zerados nas cinco
--: fontes, em 4.392 menções.
--:
--: `Estado do Veículo` VEM POR EXTENSO ("Santa Catarina") e `mencao.uf` é
--: `char(2)`. Quem traduz é `para_uf`, no domínio — mapear sem ele trocaria um
--: campo vazio por erro de banco.
--:
--: AS DUAS FONTES RECEBEM O MESMO MAPEAMENTO, porque leem o mesmo arquivo. A
--: irmã `clipei_investidores` conserva o filtro dela.
--:
--: O QUE DELIBERADAMENTE NÃO ENTROU:
--:   - `Tipo` -> `teor`: tem um valor só na planilha inteira
--:     ("Notícias/Publicações"), e `teor` alimenta `acionavel`. Um valor
--:     constante classificaria 25 mil linhas sem distinguir nada.
--:   - `Subcategoria` -> `subtema`: já está mapeada em `tema`. Mapear nos dois
--:     gravaria o mesmo texto em duas colunas.
--:   - `Categoria` (o N2 da Clipei): o nosso N2 se deriva do subtema, e o dele
--:     casa com o nosso em 7% — é corte editorial do fornecedor, não taxonomia.
--:
--: Idempotente: reescreve as chaves de `colunas` sem tocar no resto do JSON.

begin;

update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas::jsonb,
         '{colunas}',
         (mapeamento_colunas::jsonb -> 'colunas') || jsonb_build_object(
             'id_fonte',     'ID',
             'link',         'Arquivo/Link',
             'titulo_texto', 'Título',
             'uf',           'Estado do Veículo',
             'unidade',      'Empresa'
         )
       )
 where codigo in ('clipei', 'clipei_investidores');

do $$
declare
    faltando int;
begin
    select count(*) into faltando
      from score_fonte
     where codigo in ('clipei', 'clipei_investidores')
       and not (mapeamento_colunas::jsonb -> 'colunas') ? 'link';
    if faltando > 0 then
        raise exception
            'as % fontes da Clipei ficaram sem o mapeamento de link', faltando;
    end if;
end $$;

commit;
