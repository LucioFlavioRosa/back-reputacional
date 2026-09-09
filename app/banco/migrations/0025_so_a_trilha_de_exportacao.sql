-- O RELATÓRIO SAI; A TRILHA DO EXPORT FICA
--
-- A tela de relatório foi removida do produto. A tabela `relatorio`, porém,
-- guardava DUAS coisas com o mesmo nome:
--
--   formato = 'documento'  o relatório impresso pela tela  → sai
--   formato = 'csv'        quem exportou a Base, e quanto  → FICA
--
-- A segunda é controle de segurança, e não relatório: é o que responde "quem
-- levou a base embora, quando, com que recorte". Ela só dividia o encanamento
-- com a tela que saiu — apagá-la junto abriria um buraco que ninguém pediu
-- para abrir.
--
-- A tabela passa a se chamar pelo que restou. Manter o nome `relatorio` para
-- guardar exportações criaria duas palavras para uma coisa e uma palavra para
-- nenhuma — que é como se perde uma consulta escrita daqui a seis meses.
--
-- AS COLUNAS QUE SÓ O RELATÓRIO USAVA SAEM:
--   `secoes`  eram as seções do documento; a exportação leva sempre a Base.
--   `formato` só teria o valor 'csv' daqui em diante.
--   `arquivo_url` apontava para o PDF no blob; não há mais PDF.
--
-- SEM PERDA DE DADO: a tabela tem zero linhas — medido antes de escrever isto.
-- Se tivesse, este arquivo teria de filtrar as de formato 'documento' antes,
-- e não simplesmente derrubar as colunas.
--
-- Idempotente: roda quantas vezes for.

begin;

alter table if exists relatorio rename to exportacao;
alter index if exists idx_relatorio_recente rename to idx_exportacao_recente;

alter table exportacao drop column if exists secoes;
alter table exportacao drop column if exists formato;
alter table exportacao drop column if exists arquivo_url;

comment on table exportacao is
  'Quem exportou a Base, quando e sobre qual recorte. Append-only: o painel_app '
  'não tem update nem delete aqui.';

comment on column exportacao.total_de_registros is
  'Tamanho do recorte no momento da exportação, contado no servidor. É o insumo '
  'do alerta "alguém levou a base inteira".';

-- Os grants seguem a tabela no rename; reafirmados aqui para quem ler só este
-- arquivo saber que a regra continua valendo.
revoke update, delete on exportacao from painel_app;

commit;
