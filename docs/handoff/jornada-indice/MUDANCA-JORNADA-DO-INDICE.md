# Score Executivo — Mudança: Jornada do índice (evolução mensal)

**Escopo: só o bloco de evolução da aba Visão geral.** O gráfico radial (pacote anterior), as demais abas e todos os cálculos continuam como estão. Referência executável: `Score Executivo v2 - Jornada do indice.html`, arquivo único que abre sem internet. A lógica está no método `evolVals()` do script.

## 1. Resumo

| Antes | Agora |
|---|---|
| Barras verticais do ISR por mês | **Curva suave do ISR** sobre **faixas coloridas ao fundo** |
| Lista de fatos embaixo do gráfico | **Colunas por mês acima do gráfico**, alinhadas a cada ponto |
| Título fixo "Evolução do índice" | **Frase de resumo calculada** a partir da série |
| — | **"Comparar com"**: curva tracejada de uma lente sobre a do índice |
| — | Clique no ponto ou na coluna muda o mês de referência da página |

Sem mudança de dados nem de endpoints. Os fatos do mês já existem (`fato_mes`); a série mensal do ISR e das lentes já é calculada.

## 2. Estrutura do bloco (de cima para baixo)

1. **Cabeçalho**
   - Rótulo "Jornada do índice · {período}".
   - Frase de resumo em título (18px).
   - Linha própria abaixo: "Comparar com" + chips (Só o índice · uma por lente ativa).
2. **Colunas por mês**: grade com uma coluna por mês, cada uma alinhada ao ponto do mês.
3. **Gráfico**: faixas ao fundo, curva do ISR, pontos, rótulos, eixo de meses.
4. **Legenda**: cores do filete (pressiona / sustenta / misto) + "clique num mês…".

## 3. Frase de resumo (calculada, sem texto salvo)

`O índice fecha o semestre {n} ponto(s) {acima|abaixo} de {primeiro mês}. O vale foi {mês} ({nota}) e o pico, {mês} ({nota}).`

- Singular/plural em "ponto(s)".
- A segunda parte ("e o pico…") some se vale e pico caem no mesmo mês.
- Meses por extenso, em minúsculas.

## 4. Colunas por mês

Uma coluna por mês, com botão clicável. Largura = largura do gráfico ÷ nº de meses, e **as mesmas margens laterais do gráfico** para alinhar com os pontos.

| Elemento | Regra |
|---|---|
| Filete no topo (3px) | cor do efeito do fato do mês: pressiona `#FF5C60` · sustenta `#17E3CB` · misto `#9DA6C9` · sem fato `#E2E5F0` |
| Linha 1 | nome do mês (11px, caixa alta, `#8C91A4`) |
| Linha 2 (própria, sem quebra) | variação do ISR no mês: "+3 no mês" / "−15 no mês" / "0 no mês"; primeiro mês: "ponto de partida" (12px bold) |
| Texto | fato do mês (`fato_mes.texto`); sem fato: "Sem fato de destaque registrado." |
| Rodapé | "Maior movimento: {lente} {±Δ}": a lente com maior \|Δ\| no mês; omitido no primeiro mês ou se nenhuma lente se mexeu |
| Mês selecionado | fundo `#F8FAFF` |

**A variação fica em linha própria, nunca ao lado do nome do mês.** Com seis colunas não há largura para os dois lado a lado.

## 5. Gráfico

Dimensões de referência: viewBox `1000 × 330`, `PADT = 14`, `PADB = 34` (faixa dos meses).

### 5.1 Eixo Y (domínio adaptativo)
- `lo = floor((min − 8) / 5) × 5`, `hi = ceil((max + 8) / 5) × 5`, limitados a 0–100. Min e max consideram o ISR **e** a lente comparada, se houver.
- Amplitude mínima de 30 pontos (centraliza se for menor).
- Marcas a cada 10, **fora do gráfico, à esquerda** (margem reservada ~34px).

### 5.2 Faixas ao fundo
Só as faixas que cruzam o domínio, recortadas nele:

| Faixa | Intervalo | Fundo | Rótulo |
|---|---|---|---|
| Crítico | <40 | `#FFE7E8` | `#B32328` |
| Atenção | 40–55 | `#FFF1DC` | `#8A4E00` |
| Estável | 55–70 | `#EEF1F8` | `#0027BD` |
| Sólido | 70–85 | `#DFFAF6` | `#0A6B60` |
| Referência | ≥85 | `#C8F2EA` | `#0A6B60` |

**Os nomes das faixas ficam fora do gráfico, à direita** (margem reservada ~92px), centralizados verticalmente na faixa. Dentro do gráfico eles colidem com o primeiro ou o último ponto, que ficam a 1/(2n) da borda.

### 5.3 Curva e pontos
- X de cada mês: `(i + 0,5) / n × W`, o centro da coluna correspondente.
- Curva suave (Catmull-Rom → Bézier cúbica), traço `#0027BD` 3,5px sobre um halo de 14px com opacidade 0,22.
- Ponto do mês: raio 8 (selecionado: 11, com contorno `#191B23`), preenchido com a cor da faixa da nota e contorno branco.
- **Rótulo do ponto**: nota (16px bold) e, embaixo, tag do fato ("pressão" / "reforço" / "misto").
  - Cor da nota: a cor escura da faixa (`#17E3CB` → `#0A6B60`, `#FE952B` → `#8A4E00`, `#FF5C60` → `#B32328`) para manter contraste ≥ 4,5:1.
  - Posição: **acima** se o ponto é pico local (≥ média dos vizinhos), senão **abaixo**. **Só vai para baixo se couber antes do eixo**: `y + LAB ≤ H − PADB` (LAB ≈ 72 unidades do viewBox). Se não couber, vai para cima.

### 5.4 Comparar com uma lente
- Chips: "Só o índice" e uma por lente ativa. Seleção única.
- Lente selecionada: curva tracejada `#9DA6C9` 2,5px (`dasharray 6 6`), pontos brancos com contorno, e rótulo no fim da curva ("{Lente} {nota}") fora do último ponto.
- O domínio do eixo Y se recalcula para incluir a lente.

### 5.5 Eixo de meses
Abreviaturas em caixa alta sob cada ponto; o mês selecionado fica em `#0027BD` bold.

## 6. Interação
- Clique no ponto ou na coluna: muda o mês de referência da página inteira (mesmo estado do seletor Abr/Mai/Jun do header).
- Colunas e pontos focáveis por teclado; Enter seleciona.
- `aria-label` por ponto: "{Mês}: índice {n}, faixa {faixa}, {fato}".

## 7. Implementação
- Textos (rótulos dos pontos, nomes das faixas, marcas do eixo, meses) num **overlay HTML** com posição percentual calculada das coordenadas do viewBox. Não usar `<text>` interpolado dentro do SVG (mesma orientação do pacote do gráfico radial).
- Duas camadas SVG com o mesmo viewBox: faixas (`preserveAspectRatio="none"`) e curva/pontos (proporção preservada, sobreposta com `position:absolute; inset:0`).
- Colunas, gráfico e legenda com as mesmas margens laterais (`34px` à esquerda, `92px` à direita) para alinhar.

## 8. Critérios de aceite
- [ ] Com os dados de referência, a frase de resumo e as notas batem com o protótipo
- [ ] Nenhuma sobreposição entre rótulos de ponto, nomes das faixas, marcas do eixo e meses em 1280 e 1024px
- [ ] Variação do mês em linha própria, sem quebra, em todas as colunas
- [ ] Contraste do texto ≥ 4,5:1 em todas as faixas
- [ ] Selecionar uma lente adiciona a curva tracejada e recalcula o eixo
- [ ] Clique no ponto ou na coluna atualiza o radial, a lista e os chips de variação
- [ ] Mês sem fato: filete cinza, texto padrão e sem tag no ponto

## 9. Removido
- Barras verticais do ISR por mês.
- Lista de fatos abaixo do gráfico (agora nas colunas).
