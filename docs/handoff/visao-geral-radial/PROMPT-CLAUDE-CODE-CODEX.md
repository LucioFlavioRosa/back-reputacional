# Prompt — Claude Code ou Codex

Cole na conversa do projeto, com esta pasta em `docs/handoff/visao-geral-radial/`.

---

Mudança de front na aba **Visão geral** do Score Executivo. Leia `docs/handoff/visao-geral-radial/MUDANCA-VISAO-GERAL-RADIAL.md`. Referência visual e de comportamento: `Score Executivo v2 - Visao geral radial.html` (abra no navegador; a lógica do gráfico está no método `radialVals()` do script).

O que muda: o card do ISR e a grade de cards das lentes dão lugar a um **gráfico radial** (ISR no centro; uma fatia por lente, ângulo = peso, raio = nota, cor = faixa) com uma **lista lateral sincronizada**. A leitura do período vira uma faixa abaixo. Dados, endpoints e cálculos **não mudam**; a única configuração nova é `radialPorPeso`.

Antes de codar, me mostre:
1. quais componentes da Visão geral atual serão substituídos ou removidos;
2. se o gráfico vai ser SVG próprio ou usar a biblioteca de gráficos que o projeto já tem (explique a escolha: ângulo variável por fatia e raio por nota precisam caber nela);
3. como vai posicionar os textos sobre o SVG (§3, "Implementação").

Depois implemente num PR, com teste de renderização para os critérios da §8.
