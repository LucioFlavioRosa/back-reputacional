# Prompt para o Claude Code — mudança "Sinais do período"

Cole na conversa em que o Claude Code já está implementando as Lentes v2, com esta pasta em `docs/handoff/lentes/sinais/`.

---

Mudança de escopo nas Lentes v2. Leia `docs/handoff/lentes/sinais/LENTES-MUDANCA-SINAIS.md`. Ele **substitui** partes da `LENTES-ESPECIFICACAO.md`:

- **Sai**: curadoria editorial, "O que revela", encaminhamentos (tabelas, endpoints, telas e critérios de aceite).
- **Entra**: `SinaisService`, que gera manchete, títulos dos gráficos e o bloco "Sinais do período" a partir de detectores determinísticos (sem LLM), com limites configuráveis.

Referência executável: `Lentes v2 - Sinais.html` (o bloco `// Sinais do período` do script tem os detectores exatos).

Antes de codar, me mostre:
1. o que do que já foi feito precisa ser removido ou revertido;
2. onde o `SinaisService` vai morar e como ele recebe as séries já calculadas pelo endpoint da lente;
3. a lista de testes unitários por detector.

Depois implemente em PRs pequenos: remoção da curadoria → `SinaisService` + testes → integração no payload da lente → limites na Calibração. Critério de pronto: §7 do documento, incluindo as frases esperadas.
