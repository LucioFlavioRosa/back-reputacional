-- =============================================================================
-- 0113 — a planilha de bonds ganha subida em partes, com dono.
--
-- POR QUE AGORA. O ingress do Container Apps encerra a requisição por volta de
-- 240 s e isso NÃO é configurável. Medido em 16/10/2026, na mesma máquina e na
-- mesma hora, com banda de subida variando de ~18 KB/s a ~350 KB/s:
--
--     1,42 MB  ->    4,1 s  -> 200
--    10,53 MB  ->  212,4 s  -> 403   (o ingress desistindo)
--
-- A planilha do Score ganhou a subida em partes por causa disso (0092/0094). A
-- de bonds ficou sem, e manda o arquivo inteiro numa requisição — DUAS VEZES,
-- porque a tela confere e depois importa. O export é CUMULATIVO e cresce toda
-- semana: hoje tem 1,05 MB e passa; é questão de tempo até cair no mesmo 403,
-- e quem subir não vai entender por quê.
--
-- A TABELA É A MESMA IDEIA DA `planilha_recebida`, e o que ela resolve são os
-- quatro defeitos que a revisão de 16/10 achou no desenho sem linha (ver a
-- 0094). Repetidos aqui porque valem igual:
--
--   * sem linha, o identificador vale como SENHA AO PORTADOR: não há o que
--     consultar para saber de quem é a subida, e quem conhecer o uuid de outra
--     pessoa manda parte na subida dela;
--   * sem o tamanho GRAVADO, declarar 1 MB e mandar oitenta partes monta 80 MB;
--   * a linha nasce ANTES do byte, então uma falha em qualquer ponto — inclusive
--     no commit, que roda depois de a rota retornar — deixa linha incompleta
--     apontando para o arquivo, em vez de arquivo que ninguém sabe que existe.
--
-- SEM `fonte_id`, e é a única diferença estrutural para a tabela do Score: a
-- importação de bonds não tem fonte, é uma só. O índice único de `criado_por`
-- passa a significar "uma subida em voo por pessoa", que é o limite natural do
-- abuso — e abrir subida nova descarta a pendente daquela pessoa, como a
-- planilha do Score já faz.
--
-- `completa_em` NULO É O ESTADO "SUBINDO". Timestamp e não booleano pela mesma
-- razão da 0094: diz também QUANDO terminou, que é o que uma varredura por
-- idade precisa para separar subida abandonada de planilha conferida e
-- esquecida.
--
-- O `grant delete` É OBRIGATÓRIO E ESTÁ ABAIXO. A `0009` concede
-- `select, insert, update` por `alter default privileges` — e só. `delete` é
-- por tabela, explícito, porque `painel_app` "apaga apenas linhas filhas de
-- agregado". Tabela nova que precisa apagar precisa do grant na mesma
-- migration: sem ele a suíte fica VERDE (roda como superusuário) e só o
-- ambiente implantado quebra, na hora em que alguém abre a segunda subida.
-- Este banco já pagou isso três vezes.
-- =============================================================================

create table if not exists planilha_de_bonds_recebida (
    id           uuid primary key,
    caminho      text        not null,
    nome         text        not null,
    tamanho      integer     not null,
    --: CONTROLE DE ACESSO, não auditoria: só quem conferiu importa. Por isso
    --: `not null` — uma linha sem dono não teria como ser recusada.
    criado_por   uuid        not null references usuario (id),
    criado_em    timestamptz not null default now(),
    completa_em  timestamptz
);

--: UMA SUBIDA EM VOO POR PESSOA. Índice parcial porque o estado é raro e
--: transitório: no regime normal a tabela tem zero ou poucas linhas
--: incompletas, e um índice sobre a coluna inteira pagaria por todas.
create unique index if not exists planilha_de_bonds_recebida_subindo
    on planilha_de_bonds_recebida (criado_por)
    where completa_em is null;

--: VER O CABEÇALHO. Idempotente: `grant` repetido é inócuo.
grant delete on planilha_de_bonds_recebida to painel_app;
