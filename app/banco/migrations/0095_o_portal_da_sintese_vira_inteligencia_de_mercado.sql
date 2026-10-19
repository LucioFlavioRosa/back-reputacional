-- =============================================================================
-- 0095 — O PORTAL `sintese` PASSA A SE CHAMAR `inteligencia_de_mercado`.
--
-- POR QUE AGORA. O portal nasceu na 0003 chamado "Síntese", e a capa passou a
-- chamá-lo de "Painel de Inteligência de Mercado". O nome interno ficou para
-- trás, e `dependencias.py` registrou isso como nota de rodapé: "o rótulo da
-- capa mudou, o nome interno não". Agora ele vai ser construído — e começar a
-- escrever tabela, rota e tela com um nome que a tela não usa seria multiplicar
-- a divergência por tudo o que vem depois.
--
-- E TIRA UMA COLISÃO QUE QUASE CRIAMOS. A primeira proposta foi `acessa_mercado`,
-- por consistência com a variável `mercado_lancado`. Era pior: existe a LENTE
-- `mercado`, que é outra coisa e vive dentro do Score — ela recorta veículos de
-- mercado financeiro e está protegida por `acessa_score`. Chamar as duas de
-- "mercado" deixaria duas permissões diferentes com o mesmo nome, e
-- `dependencias.py` já avisava que trocá-las "custaria acesso em produção".
-- O nome mais longo não se confunde com nada.
--
-- O QUE **NÃO** É RENOMEADO, e a distinção é a parte perigosa desta entrega:
--
--   * a SÍNTESE EXECUTIVA PELA IA (`sinteseIA.ts`, `Painel.tsx`) é outro
--     produto, dentro do Score. Tem 34 ocorrências no front e nenhuma relação
--     com este portal. Um replace no atacado a quebraria;
--   * a palavra "síntese" em PROSA (`repositorio_interacoes.py`, onde significa
--     resumo mesmo);
--   * AS MIGRATIONS ANTERIORES. A 0003 cria a coluna com o nome antigo e a 0088
--     o cita; na ordem de aplicação, naquele instante o nome ERA aquele.
--     Reescrevê-las faria o banco novo divergir do banco que já rodou — e um
--     script meu fez exatamente isso aqui, por descuido, antes de ser revertido;
--   * `mercado_lancado`, que é VARIÁVEL DE AMBIENTE e não coluna: renomeá-la
--     exige trocar o env do Container App no mesmo instante do deploy, e ela já
--     diz "mercado", que é o lado certo da divergência. Fica para quando o env
--     for tocado de qualquer jeito.
--
-- NÃO HÁ PERDA DE ACESSO. `alter table ... rename column` preserva o dado, e os
-- dois `update` trocam só o `codigo` do papel — `usuario.papel_id` referencia
-- `papel(id)`, não o código, então ninguém é desligado do papel. Conferido na
-- 0003: `papel_id smallint references papel(id)`.
-- =============================================================================

begin;

alter table papel
    rename column acessa_sintese to acessa_inteligencia_de_mercado;

--: O CÓDIGO DO PAPEL É CHAVE NATURAL (`codigo text not null unique`) e aparece
--: em `identidade.py` como constante. Trocá-lo aqui e lá na mesma entrega é o
--: que mantém os dois lados dizendo a mesma coisa.
update papel set codigo = 'inteligencia_de_mercado_leitura'
 where codigo = 'sintese_leitura';

update papel set codigo = 'inteligencia_de_mercado_edicao'
 where codigo = 'sintese_edicao';

--: E O RÓTULO TAMBÉM, porque ele é o que a tela de perfis MOSTRA. Deixar
--: "Síntese · leitura" na lista seria a mesma divergência que esta migration
--: existe para fechar, só que na cara de quem concede acesso.
update papel set nome = 'Inteligência de Mercado · leitura'
 where codigo = 'inteligencia_de_mercado_leitura';

update papel set nome = 'Inteligência de Mercado · edição'
 where codigo = 'inteligencia_de_mercado_edicao';

comment on column papel.acessa_inteligencia_de_mercado is
  'Abre o Painel de Inteligência de Mercado (chamado `sintese` até a 0095). '
  'NÃO confundir com a lente `mercado`, que vive dentro do Score e responde a '
  'acessa_score.';

commit;
