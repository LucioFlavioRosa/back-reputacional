--: QUEM FALA NA BITES É UM PERFIL DE REDE, E ELE PASSA A TER CADASTRO.
--:
--: O QUE ESTA MIGRATION RESOLVE. A menção guarda QUEM FALOU em `veiculo`, e na
--: Clipei isso é um veículo de imprensa — 25.457 das 25.573 menções dela estão
--: ligadas a uma instituição do Cadastro compartilhado. A Bites não tinha
--: vínculo nenhum: o `Autor` da planilha (`deolhoemesteio`, `@casadevovodede`,
--: "Stela Farias") não era lido, e as 2.886 menções entraram sem apontar para
--: ninguém.
--:
--: O GRÃO É O PERFIL, e isto foi medido antes de decidir: dos 1.173 autores
--: distintos do arquivo de 01–09/2026, só 54 aparecem em mais de uma rede e
--: só 2 em mais de um estado. Uma entidade "rede + estado" colapsaria os 1.173
--: em ~30 baldes e perderia o que interessa — `deolhoemesteio` com 135
--: menções, "Stela Farias" com 121. Rede e UF são ATRIBUTOS do perfil.
--:
--: E ELE NÃO É VEÍCULO DE IMPRENSA. Nasce com `tipo='perfil_rede'` e na
--: categoria de público "Formadores de Opinião" — que já existia no cadastro
--: desde a `0036` e estava VAZIA. Pôr perfil de rede na Imprensa o deixaria
--: candidato à lista de imprensa econômica da lente Mercado, e
--: `deolhoemesteio` não é veículo de investidor. A lista de investidores
--: filtra `tipo='veiculo'`, então o perfil fica fora dela por construção.
--:
--: POR QUE NÃO UMA TABELA NOVA. `instituicao` já abriga `proposicao` e
--: `area_interna`, que também não são instituições no sentido estrito: ela é o
--: cadastro de QUEM e O QUE existe lá fora. Tabela própria custaria coluna
--: nova na menção, tela nova, filtro novo e um segundo vínculo a manter — para
--: o mesmo resultado. Com o `tipo`, a tela de Cadastro compartilhado já filtra
--: e já lista.
--:
--: A PESSOA POR TRÁS DO PERFIL É O PASSO SEGUINTE, e não é esta migration:
--: `interlocutor` já tem `redes_sociais` (array de texto), hoje vazio nos 129
--: cadastrados. Ligar "Stela Farias" do Bites à deputada do CRM é curadoria
--: sobre os ~56 perfis com mais de cinco menções, e não código.
--:
--: `quem_fala` NO MAPEAMENTO é o que faz a ingestão procurar e criar no tipo
--: certo. Ausente, vale `veiculo` — as quatro fontes antigas ficam idênticas.
--:
--: NADA MUDA NO QUE JÁ ESTÁ GRAVADO. O mapeamento vale da próxima subida; os
--: perfis nascem quando alguém AUTORIZAR na conferência, um por um, como os
--: 2.631 veículos da Clipei.
--:
--: Idempotente.

begin;

--: O TIPO NOVO ENTRA NO CHECK. Sem isto, o `insert` do perfil é recusado pelo
--: Postgres — e a mensagem falaria de constraint, não de cadastro.
alter table instituicao drop constraint if exists instituicao_tipo_check;
alter table instituicao add constraint instituicao_tipo_check check (
  tipo in (
    'veiculo', 'orgao', 'entidade', 'escritorio', 'investidor',
    'proposicao', 'area_interna', 'credor', 'perfil_rede'
  )
);

update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas || jsonb_build_object('quem_fala', 'perfil_rede'),
         '{colunas}',
         (mapeamento_colunas -> 'colunas') || jsonb_build_object('veiculo', 'Autor')
       )
 where codigo = 'bites';

--: `veiculo` OPCIONAL pelo mesmo motivo das outras: a planilha pode vir sem a
--: coluna `Autor` num mês, e isso não pode derrubar a subida.
update score_fonte
   set mapeamento_colunas = jsonb_set(
         mapeamento_colunas,
         '{colunas_opcionais}',
         '["tema", "link", "titulo_texto", "autor", "uf", "veiculo"]'::jsonb
       )
 where codigo = 'bites';

do $$
declare
    colunas jsonb;
    quem text;
    tem_categoria boolean;
begin
    select mapeamento_colunas -> 'colunas', mapeamento_colunas ->> 'quem_fala'
      into colunas, quem
      from score_fonte
     where codigo = 'bites';

    select exists (
        select 1 from categoria_publico
         where nome = 'Formadores de Opinião' and ativo
    ) into tem_categoria;

    if colunas is null then
        raise notice 'fonte bites não encontrada — nada a converter';
    elsif colunas ->> 'veiculo' <> 'Autor' or quem <> 'perfil_rede' then
        raise exception
            'conversão da bites não fechou: veiculo=%, quem_fala=%',
            colunas ->> 'veiculo', quem;
    elsif not tem_categoria then
        --: A categoria é onde o perfil nasce: sem ela, a criação viria com
        --: categoria nula e o Cadastro compartilhado recusaria editar o
        --: registro depois.
        raise exception
            'a categoria de público "Formadores de Opinião" não está cadastrada e ativa';
    else
        raise notice 'a Bites cadastra quem fala como perfil_rede, pelo Autor';
    end if;
end $$;

commit;
