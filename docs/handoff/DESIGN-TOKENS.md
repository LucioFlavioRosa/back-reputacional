# Design tokens — arquivo de referência para o Claude Code

Copie estes valores para o sistema de tokens do codebase (CSS variables, Tailwind config, theme object).

## CSS variables

```css
:root {
  /* Paleta principal Aegea */
  --azul-mar: #0027BD;
  --azul-mar-sombra: #111799;
  --turquesa-rio: #17E3CB;
  --turquesa-sombra: #9DEEE7;

  /* Paleta secundária (apenas detalhes, ícones, gráficos) */
  --amarelo-pequi: #F8DC00;
  --laranja-baia: #FE952B;
  --vermelho-pitanga: #FF5C60;
  --magenta-pitaia: #E12379;
  --roxo-acai: #A11FFF;
  --rosa-goiaba: #FF8FE1;

  /* Neutros */
  --branco: #FFFFFF;
  --cinza-1: #E2E5F0;
  --cinza-2: #8C91A4;
  --cinza-3: #44495C;
  --cinza-4: #191B23;

  /* Aplicação */
  --bg-app: #F4F6FC;
  --bg-trilho: #EEF1F8;
  --bg-hover: #F8FAFF;
  --bg-rodape-card: #FAFBFE;
  --borda: #E2E5F0;
  --borda-input: #D5DAEA;
  --texto-placeholder: #A6ABBD;

  /* Semânticos */
  --ok-bg: #DFFAF6;      --ok-fg: #0A6B60;
  --atencao-bg: #FFF1DC; --atencao-fg: #8A4E00;
  --erro-bg: #FFE7E8;    --erro-fg: #B32328;
  --sobre-turquesa: #00312C;

  /* Frentes */
  --frente-imprensa: #0027BD;
  --frente-governo: #17E3CB;
  --frente-parceiros: #A11FFF;
  --frente-eventos: #FE952B;
  --frente-investidores: #E12379;
  --frente-legislativo: #F8DC00;
  --frente-interna: #8C91A4;

  /* Clima */
  --clima-propositivo: #17E3CB;
  --clima-neutro: #8C91A4;
  --clima-tenso: #FF5C60;

  /* Resultado */
  --res-avancou: #17E3CB;
  --res-mantido: #0027BD;
  --res-retrocedeu: #FF5C60;
  --res-sem-definicao: #D5DAEA;

  /* Status (grupo) */
  --grupo-resolvido: #17E3CB;
  --grupo-aberto: #FE952B;
  --grupo-declinado: #FF5C60;

  /* Tipografia */
  --font-sans: "DM Sans", Arial, sans-serif;
  --font-destaque: Georgia, "Times New Roman", serif; /* itálico */

  /* Raios */
  --r-chip: 5px;  --r-btn: 9px;  --r-card-int: 12px;
  --r-card: 14px; --r-destaque: 16px;

  /* Sombras */
  --sh-card-hover: 0 6px 18px rgba(0,39,189,0.10);
  --sh-tooltip: 0 8px 24px rgba(25,27,35,0.22);
  --sh-modal: 0 24px 64px rgba(25,27,35,0.28);
  --sh-drawer: 0 0 40px rgba(25,27,35,0.18);
}
```

## Escala tipográfica

| Uso | Tamanho | Peso | Letter-spacing |
|---|---|---|---|
| Hero da home | 44px | 700 | -0.03em |
| Número de hero / destaque | 38px | 700 | -0.03em |
| H1 de view | 26px | 700 | -0.02em |
| Número de KPI | 32-34px | 700 | -0.03em |
| Título de modal | 21px | 700 | -0.02em |
| H2 de card | 16-17px | 700 | — |
| Nome / item forte | 15px | 700 | — |
| Corpo | 14px | 400 | — |
| Tabela / label de campo | 13px | 400/500 | — |
| Auxiliar | 12px | 400 | — |
| Kicker (uppercase) | 11px | 700 | 0.06em |

Mínimos: nunca abaixo de 11px na interface; no relatório impresso, 8pt em rótulos e 9-10pt em corpo.

## Espaçamento

Escala: 4 · 5 · 6 · 8 · 10 · 12 · 14 · 16 · 18 · 20 · 22 · 26 · 32 · 64px

- Padding de card: 20px (padrão) / 22px (denso de conteúdo) / 26px (destaque)
- Gap de grid: 14px (KPIs) / 16px (seções) / 18-24px (interno de card)
- Padding de main: `28px 32px 64px`
- Max-width: 1440px (painéis) / 1180-1240px (leitura) / 820px (modal de ficha) / 680px (modal de seleção)
- Drawer de filtros: 312px

## Alturas de controle

Input/select 38-40px · botão secundário 34-36px · botão primário 40-44px · chip 28-30px · trilho de barra 7-9px (ranking) e 12-16px (empilhada).
