-- A planilha do Score sobe UMA vez: a conferência guarda o arquivo, e a
-- confirmação o reusa em vez de pedir os mesmos bytes de novo.
--
-- O QUE MOTIVOU, com os números medidos em 15/10/2026. Hoje quem importa manda
-- o arquivo DUAS vezes — `POST /fontes/{codigo}/conferencia` e depois
-- `POST /fontes/{codigo}/planilha`, cada uma com um `UploadFile`. Com o
-- clipping real da Clipei (10,53 MB, 75.369 linhas) isso são 21 MB de tráfego
-- e duas travessias completas de ingress, nginx e API.
--
-- E a segunda travessia é a que mais dói, porque é a que grava: ela sobe o
-- arquivo DE NOVO antes de começar a trabalhar, dentro do mesmo relógio de
-- gateway que já estourou uma vez — o 504 de 15/10/2026 no ambiente do cliente
-- (`conferencia`, 113 s de processamento contra um teto de 60 s).
--
-- GUARDA OS BYTES, NUNCA AS CONCLUSÕES. Esta é a linha que separa este desenho
-- de uma tabela de rascunho, e ela foi escrita de propósito: a importação de
-- subtemas documenta que "o arquivo vai de novo, e não é desperdício: o
-- servidor relê e reconfere contra o banco daquele instante". O argumento está
-- certo e continua valendo — a confirmação segue relendo a planilha inteira e
-- reconferindo veículo por veículo e tema por tema contra o cadastro do
-- instante em que ela roda. O que esta tabela dispensa é o UPLOAD, não a
-- reconferência. Nenhuma previsão, nenhum veículo novo e nenhuma contagem da
-- conferência é persistida aqui.
--
-- UMA POR FONTE E POR PESSOA, e é isso que a unicidade abaixo declara. Conferir
-- de novo a mesma fonte substitui a anterior, inclusive o byte no armazenamento
-- — senão cada conferência abandonada deixaria um arquivo de dezenas de MB para
-- sempre. Com a restrição, o lixo máximo é um arquivo por fonte por pessoa, em
-- vez de um por clique.
--
-- `criado_por` É CONTROLE DE ACESSO, não auditoria. Só quem conferiu pode
-- confirmar aquela planilha: sem isso, um id vazado deixaria outra pessoa com
-- a mesma permissão gravar um arquivo que ela nunca viu. A coluna é NOT NULL
-- por essa razão — uma linha sem dono não teria como ser recusada.
--
-- O ARMAZENAMENTO PODE ESTAR DESLIGADO, e aí nada disto acontece: a conferência
-- devolve `planilha_id` nulo e a tela manda o arquivo de novo, exatamente como
-- antes. O painel inteiro funciona sem Blob (ver `blob.ArmazenamentoDesligado`),
-- e esta tabela não pode ser a primeira coisa a quebrar essa promessa.
--
-- `on delete cascade` NO USUÁRIO: apagar uma pessoa não pode ser barrado por
-- uma planilha que ela conferiu e não confirmou. O byte correspondente vira
-- órfão no contêiner.
--
-- NÃO HÁ VARREDURA DE ABANDONADAS, e isto é limitação conhecida, não descuido.
-- Achado da revisão do Codex em 16/10/2026: uma versão anterior deste
-- comentário dizia que "a retenção varre", e isso era falso — a
-- `delete_retention_policy` da conta guarda o que JÁ foi apagado por 7 dias, e
-- não apaga o que ninguém apagou.
--
-- O QUE DE FATO LIMITA O ESTRAGO é o índice único abaixo: no pior caso existe
-- uma planilha pendente por fonte e por pessoa — hoje 5 fontes, e o teto por
-- arquivo são 80 MB. Não é zero, e uma expiração por idade é o próximo passo
-- honesto; ela não entrou aqui porque é outro desenho (quem varre? com que
-- gatilho?) e misturá-lo faria um PR que ninguém consegue revisar.

create table if not exists planilha_recebida (
    id         uuid primary key,
    fonte_id   smallint not null references score_fonte (id) on delete cascade,
    --: O caminho NO ARMAZENAMENTO. Texto, e não um identificador estruturado:
    --: quem resolve a árvore é `blob.caminho_da_planilha`, e o banco só precisa
    --: saber onde devolver o byte.
    caminho    text     not null,
    --: O nome que a pessoa escolheu, para a tela poder dizer qual arquivo ela
    --: está prestes a confirmar. Não participa do caminho sozinho.
    nome       text     not null,
    tamanho    integer  not null,
    criado_por uuid     not null references usuario (id) on delete cascade,
    criado_em  timestamptz not null default now()
);

--: A INVARIANTE, declarada em vez de esperada: uma planilha pendente por fonte
--: e por pessoa. O caso de uso apaga a anterior antes de inserir, e esta
--: restrição é o que garante que ele não possa esquecer.
create unique index if not exists planilha_recebida_por_fonte_e_pessoa
    on planilha_recebida (fonte_id, criado_por);
