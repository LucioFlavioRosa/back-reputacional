--: O ARQUIVO DO MATERIAL, GUARDADO NO BLOB.
--:
--: A 0011 criou `material.arquivo_id` inerte, com um comentário dizendo que
--: guardar arquivo no painel traz "armazenamento, limite de tamanho, antivírus
--: e política de retenção — uma frente inteira". Esta migration abre essa
--: frente pela metade de baixo: armazenamento e limite. Antivírus e retenção
--: seguem por fazer, e estão nomeados no fim deste arquivo para que a ausência
--: seja uma decisão registrada, e não um esquecimento.
--:
--: Idempotente, como as anteriores: `if not exists` em tudo, para poder rodar
--: duas vezes sem estragar o que já está no banco.

begin;

--: O ARQUIVO É UMA ENTIDADE, e não colunas soltas no material.
--:
--: Porque a mesma pergunta tem duas respostas diferentes: "que material é
--: este" (título, momento, observação — do material) e "onde está o byte"
--: (caminho, tamanho, tipo — do arquivo). Misturar as duas faria um material
--: por LINK carregar cinco colunas nulas explicando um arquivo que ele não
--: tem.
create table if not exists arquivo (
  id             uuid        primary key default gen_random_uuid(),

  --: O CAMINHO NO BLOB, GRAVADO — e não derivado por convenção.
  --:
  --: Dá para montar `interacoes/{id}/{momento}/{id}` a partir das outras
  --: colunas, e é assim que ele nasce. Mas convenção derivada quebra em
  --: silêncio no dia em que a convenção mudar: os arquivos antigos continuam
  --: onde estavam, e o código passa a procurá-los onde nunca estiveram.
  --:
  --: Gravado, o caminho é um FATO sobre este arquivo. A convenção decide
  --: apenas onde os PRÓXIMOS nascem.
  caminho        text        not null,

  --: O nome que a pessoa subiu. Não entra no caminho: nome de arquivo do
  --: mundo real traz acento, espaço, barra e emoji, e o caminho precisa ser
  --: estável. Mas é ele que volta no download — quem baixa espera reencontrar
  --: "Nota técnica ANA.pdf", não um uuid.
  nome           text        not null,

  --: O que o navegador precisa para decidir se abre ou baixa.
  tipo_conteudo  text        not null,

  --: Em bytes. Fica aqui, e não só no blob, para a tela poder mostrar o
  --: tamanho sem uma ida ao armazenamento por linha de lista.
  tamanho        bigint      not null check (tamanho > 0),

  criado_por     uuid        not null references usuario(id),
  criado_em      timestamptz not null default now(),

  --: DOIS ARQUIVOS NÃO OCUPAM O MESMO CAMINHO. É a garantia que faz "uma
  --: pasta, um conjunto de materiais" valer: sem ela, um upload poderia
  --: sobrescrever o byte de outro e as duas linhas continuariam apontando
  --: para o mesmo lugar, cada uma achando que é dona.
  constraint arquivo_caminho_unico unique (caminho)
);

comment on table arquivo is
  'Um arquivo no Blob Storage. `caminho` é a chave no contêiner; a linha aqui '
  'é o que a aplicação conhece sem ir ao armazenamento.';

--: A LIGAÇÃO QUE FALTAVA. A coluna nasceu na 0011 sem referência, porque a
--: tabela do outro lado ainda não existia.
--:
--: `on delete restrict` de propósito, e não `cascade`: apagar a linha do
--: arquivo com o material ainda apontando para ela deixaria um material órfão
--: prometendo um anexo que não volta. E `set null` seria pior — o material
--: passaria a não ter link NEM arquivo, violando
--: `material_precisa_apontar_para_algo` na próxima escrita, longe daqui.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'material_arquivo_fk'
  ) then
    alter table material
      add constraint material_arquivo_fk
      foreign key (arquivo_id) references arquivo(id) on delete restrict;
  end if;
end $$;

--: Buscar "os arquivos desta agenda" é a consulta da tela de materiais, e ela
--: roda a cada abertura de ficha que tenha anexo.
create index if not exists ix_material_arquivo on material (arquivo_id)
  where arquivo_id is not null;

grant select, insert, update, delete on arquivo to painel_app;

--: -------------------------------------------------------------------------
--: O QUE ESTA MIGRATION NÃO FAZ, e por que está escrito aqui.
--:
--: ANTIVÍRUS. Nada varre o que sobe. Num painel interno, com acesso por SSO
--: corporativo e uma lista de tipos permitidos na aplicação, o risco é menor
--: que o de uma pasta compartilhada — mas não é zero, e quem ler isto deve
--: saber que a checagem não existe.
--:
--: RETENÇÃO. Nada apaga arquivo velho. O blob cresce para sempre. A política
--: é decisão da companhia (quanto tempo se guarda material de agenda), e
--: implementá-la antes de alguém decidir seria escolher por eles.
--:
--: DEDUPLICAÇÃO. O mesmo PDF subido em duas agendas ocupa dois caminhos. É o
--: comportamento certo enquanto não houver retenção: apagar uma agenda não
--: pode levar embora o anexo de outra.

commit;
