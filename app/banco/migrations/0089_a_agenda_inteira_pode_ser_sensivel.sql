-- =============================================================================
-- 0089 — a AGENDA inteira pode ser sensível, e não só alguns campos dela
--
-- O QUE MUDA, E É UMA TROCA DE SEMÂNTICA
--
-- Até aqui a informação sensível era uma lista FIXA de campos
-- (`InteracaoSaida.CAMPOS_SENSIVEIS`): `relato`, `encaminhamentos`,
-- `pendencias`, `observacoes`, `posicionamento`. O registro aparecia para todo
-- mundo e esses campos vinham nulos para quem não tinha a camada.
--
-- Agora quem classifica é quem REGISTRA, uma agenda por vez, e o efeito é
-- sobre a LINHA:
--
--     sensivel = true   → só quem tem `usuario.acesso_sensivel` alcança.
--                         Para os outros, a linha NÃO EXISTE: não aparece na
--                         Base, não entra em KPI, não é achada pela busca, não
--                         abre pela URL.
--     sensivel = false  → todo mundo que tem o CRM vê a agenda INTEIRA,
--                         relato incluído.
--
-- POR QUE A TROCA
--
-- A lista fixa não respondia à pergunta de quem usa. "Esta reunião é
-- delicada" é uma propriedade do ENCONTRO, não do campo: há agenda cujo relato
-- é banal e agenda em que a simples existência do encontro é a informação
-- sensível — e a lista de campos não tinha como esconder a segunda. Além disso
-- ninguém entendia por que um campo vinha vazio num registro comum.
--
-- O QUE ISSO ALARGA, e precisa estar escrito
--
-- Toda interação existente nasce `sensivel = false`, e com isso o `relato`
-- delas passa a ser visível a quem tem o CRM e NÃO tem a camada sensível —
-- antes vinha nulo. É ampliação de acesso sobre o acervo, decidida com essa
-- consequência à vista, e é o preço de a classificação passar a ser explícita.
--
-- O padrão NÃO podia ser o contrário: `true` em tudo esconderia o acervo
-- inteiro de quem não tem a camada, e aí ninguém sem ela teria painel nenhum.
--
-- E O QUE ISSO FAZ COM O KPI
--
-- O filtro mora em `filtros_sql.condicoes()`, o mesmo tradutor que a listagem
-- e TODAS as agregações usam — é o que faz o número do KPI bater com o da
-- tabela. Logo, quem não alcança o sensível verá KPI MENOR: índice, série
-- mensal, resolutividade. Duas pessoas na mesma tela veem números diferentes.
--
-- É inerente a segurança por linha, e é o único arranjo que mantém a
-- invariante: contar no KPI o que a tabela não lista (ou o contrário) a
-- quebraria para um dos dois lados, e a divergência apareceria como "o sistema
-- está com número errado", sem ninguém saber onde.
--
-- QUEM PODE MARCAR
--
-- Só quem tem `usuario.acesso_sensivel`. Não se classifica algo dentro de um
-- cofre que não se abre: quem marcasse sem a camada perderia o próprio
-- registro de vista no mesmo instante, sem entender por quê. A recusa é na
-- aplicação (`api/interacoes.py`), com 422 e motivo.
--
-- NÃO CONFUNDIR COM `visivel`
--
-- `visivel` já existe e é outra coisa: esconder um registro de todo mundo
-- (importação que deu errado, duplicata). `sensivel` restringe POR PESSOA. As
-- duas entram em `condicoes()` e convivem.
-- =============================================================================

alter table interacao
  add column if not exists sensivel boolean not null default false;

comment on column interacao.sensivel is
  'A agenda inteira é restrita: só quem tem usuario.acesso_sensivel a alcança. '
  'Para os outros a LINHA não existe — nem na Base, nem no KPI, nem na busca. '
  'Diferente de `visivel`, que esconde de todo mundo.';


-- SEM ÍNDICE, e é decisão e não esquecimento.
--
-- O filtro acrescenta `sensivel = false` a consultas que JÁ filtram por
-- `arquivado_em is null`, `visivel` e período — e que o planejador resolve
-- pelos índices que existem. Um índice sobre booleano de baixa seletividade
-- não seria escolhido, e custaria escrita em toda gravação de agenda.
--
-- Se um dia a maioria das agendas for sensível, o caso vira o inverso e um
-- índice PARCIAL (`where sensivel`) passa a valer. Medir antes.
