# Score Executivo — Mudança: Visão geral com gráfico radial das lentes

**Escopo: só a aba Visão geral do Score Executivo.** As demais abas (Lentes, Drivers e riscos, Calibração, Metodologia) e todos os cálculos continuam como estão. Referência executável: `Score Executivo v2 - Visao geral radial.html` (arquivo único, abre sem internet). A lógica está no método `radialVals()` do script.

## 1. Resumo

| Antes | Agora |
|---|---|
| Card azul com o ISR em número grande + régua horizontal de faixas | ISR **no centro de um gráfico radial** |
| 5 cards de lente em grade | **Gráfico radial** (uma fatia por lente) + **lista lateral** das lentes |
| "Leitura do período" em card ao lado do ISR | Faixa horizontal abaixo: leitura + "o que sustenta" + "o que corrói" |

Sem mudança de dados, endpoints ou regras de cálculo. É mudança de front.

## 2. Nova estrutura da Visão geral (de cima para baixo)

1. **Bloco "Cinco lentes, um índice"** (card único, 2 colunas)
   - Cabeçalho: rótulo "Índice de Saúde Reputacional · {mês ano}" (uma linha, sem quebra), título, chip de calibração (padrão/ajustada) à direita.
   - Coluna esquerda: gráfico radial + chips de variação + legenda de faixas + nota de leitura.
   - Coluna direita: lista das 5 lentes.
2. **Faixa de leitura**: "Leitura do período" (texto) · "O que sustenta" · "O que corrói" lado a lado.
3. Evolução do índice e o restante da aba seguem **sem alteração**.

## 3. Gráfico radial — especificação

Gráfico polar de áreas (Nightingale), SVG.

| Elemento | Regra |
|---|---|
| Fatias | uma por lente, em sentido horário a partir das 12h, na ordem Imprensa → Mercado → Sociedade digital → Clientes → Institucional |
| **Ângulo da fatia** | proporcional ao **peso efetivo** da lente (default 30/20/20/15/15). Configuração `radialPorPeso` (default `true`); se `false`, fatias iguais |
| **Raio da fatia** | `r = R0 + (Rmax − R0) × nota/100` (nota 0–100). Anel interno R0 livre para o centro |
| Cor da fatia | cor da faixa da nota: Crítico <40 `#FF5C60` · Atenção 40–54 `#FE952B` · Estável 55–69 `#0027BD` · Sólido 70–84 `#17E3CB` · Referência ≥85 `#0A6B60` |
| Fundo | cada fatia tem um fundo até 100 (`#F4F6FC`, borda `#E2E5F0`): mostra quanto falta |
| Espaço entre fatias | pequeno recuo angular (~1°) de cada lado |
| Anéis de referência | círculos tracejados (`#C3CDF7`) nos limites 40, 55, 70, 85; contorno sólido em 100. Rótulos só em **40 e 70**, na vertical das 12h |
| Centro | círculo `#0027BD` com ISR (52px, bold, branco) e faixa (11px, caixa alta, `#9DEEE7`) |
| Rótulos externos | nome da lente (14px bold) + nota (15px bold na cor da faixa), no ângulo médio da fatia, a `Rmax + 30`. Alinhamento: centro quando próximo da vertical; à esquerda no lado direito; à direita no lado esquerdo |
| Lente fora do cálculo (todas as fontes desligadas) | fatia estreita fixa (~6% do círculo), só fundo, rótulo "fora"; as demais dividem o restante |

**Implementação:** não usar `<text>` dentro do SVG para valores dinâmicos se o framework envolver interpolação em elementos HTML. Os textos (centro, rótulos das lentes e dos anéis) ficam num **overlay HTML** com posição absoluta calculada a partir das coordenadas do SVG:
`left = (x − viewBoxX) / viewBoxW × 100%`, `top = (y − viewBoxY) / viewBoxH × 100%`, com `transform: translate(-50%|0|-100%, -50%)` conforme o alinhamento.

Abaixo do gráfico:
- Chips "{Δ} vs. mês anterior" e "{Δ} vs. janeiro" em **variante clara**: sobe `#DFFAF6/#0A6B60` · cai `#FFE7E8/#B32328` · igual `#F4F6FC/#44495C`.
- Legenda das 5 faixas com cor e limites.
- Nota: "largura de cada fatia = peso da lente · comprimento = nota · anéis tracejados = limites das faixas" (texto muda quando `radialPorPeso = false`).

## 4. Lista lateral das lentes

Uma linha clicável por lente:
`[quadrado na cor da faixa] · STAKEHOLDER (linha própria, caixa alta, sem quebra, reticências) · Nome da lente · fonte · peso {x}% · nota grande · chip de variação`

- Hover numa linha **destaca a fatia** correspondente (as outras ficam com opacidade 0,35 e a fatia focada ganha contorno escuro). Hover na fatia ou no rótulo destaca a linha. Estado compartilhado `hoverLente`.
- Clique (linha, fatia ou rótulo) abre a aba **Lentes** já na lente clicada.
- Lente fora do cálculo: linha com opacidade 0,55, nota "—", peso "fora do cálculo".
- Rodapé: "Passe o mouse para destacar a fatia; clique para abrir a lente."

## 5. Configuração nova

| Chave | Tipo | Default | Onde |
|---|---|---|---|
| `radialPorPeso` | boolean | `true` | `score_config` / aba Calibração (perfil `coordenacao`) |

## 6. Responsivo

- ≥ 960px: gráfico e lista lado a lado (gráfico ~55%).
- < 960px: lista abaixo do gráfico; gráfico com largura máxima de 560px, centralizado.
- Rótulos externos nunca podem ser cortados: reservar margem no viewBox (no protótipo: `-60 -20 580 500` para centro em 230,230 e Rmax 190).

## 7. Acessibilidade

- Cada fatia e cada linha da lista é focável por teclado (Tab) e ativável com Enter; foco equivale a hover.
- `aria-label` por fatia: "{Lente}: nota {n}, faixa {faixa}, peso {p}%".
- A informação nunca depende só da cor: a nota está escrita no rótulo e na lista.

## 8. Critérios de aceite

- [ ] Com a calibração padrão e dados de junho: ISR 58 (Estável) no centro; fatias Imprensa 70 · Mercado 67 · Sociedade 37 · Clientes 42 · Institucional 65 (conferir contra o protótipo)
- [ ] Ângulo das fatias segue o peso efetivo; mudar pesos na Calibração redesenha o gráfico
- [ ] `radialPorPeso = false` deixa as fatias iguais
- [ ] Desligar todas as fontes de uma lente: fatia "fora", demais redistribuídas
- [ ] Hover sincronizado entre fatia, rótulo e lista; clique abre a lente certa
- [ ] Nenhum texto sobreposto ou cortado em 1280, 1024 e 768px
- [ ] Chips de variação com contraste ≥ 4,5:1
- [ ] Trocar o mês no header atualiza gráfico, lista e chips

## 9. Removido da Visão geral
- Card azul do ISR com a régua horizontal de faixas (a legenda de faixas passa para baixo do gráfico).
- Grade de 5 cards de lente (substituída pela lista lateral).
