# Prompt — Claude Code ou Codex

Cole na conversa do projeto, com esta pasta em `docs/handoff/jornada-indice/`.

---

Mudança de front no bloco de **evolução do índice** da aba Visão geral do Score Executivo. Leia `docs/handoff/jornada-indice/MUDANCA-JORNADA-DO-INDICE.md`. Referência visual e de comportamento: `Score Executivo v2 - Jornada do indice.html` (abra no navegador; a lógica está no método `evolVals()` do script).

O que muda: as barras mensais e a lista de fatos dão lugar a uma **jornada**: curva do ISR sobre faixas coloridas, colunas por mês com fato, variação e maior movimento, frase de resumo calculada e comparação com uma lente. Dados e endpoints **não mudam**.

Antes de codar, me mostre:
1. o componente atual que será substituído;
2. se vai usar a biblioteca de gráficos do projeto ou SVG próprio (curva suave, faixas recortadas no domínio e rótulos com regra de espaço precisam caber nela);
3. como vai alinhar as colunas de fatos com os pontos do gráfico (§7).

Depois implemente num PR, com teste de renderização para os critérios da §8. Atenção às três regras de layout que já quebraram no protótipo: variação do mês em linha própria (§4), nomes das faixas fora do gráfico (§5.2) e rótulo abaixo do ponto só se couber (§5.3).
