--: REMOVE O VÍNCULO DE EXEMPLO DA 0059.
--:
--: A `0059_matriz_de_risco_corporativo` inseriu um único vínculo de
--: demonstração — "Resultados financeiros e operacionais" → R27 "Cobertura de
--: Seguros" — antes de existir o dado real da planilha. A `0061` trouxe os 100
--: enquadramentos de verdade e achou que esse subtema, pela planilha, enquadra
--: em R29 ("Integridade das Informações ao Mercado"), não em R27. Os dois
--: vínculos conviviam (schema N:N), mas o de exemplo nunca foi decisão de
--: ninguém — era só para a tela não abrir vazia.
--:
--: Decisão do usuário (2026-10-08): remover o exemplo agora que o dado real
--: chegou.
--:
--: Idempotente.

begin;

delete from tema_risco
 where tema_id = (select id from tema where nome = 'Resultados financeiros e operacionais')
   and risco_id = (select id from risco where codigo = 'R27');

commit;
