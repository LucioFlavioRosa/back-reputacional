# Score Executivo — Índice de Saúde Reputacional (ISR)

Referência executável: `Score Executivo Aegea.dc.html` (classe `Component`). Base conceitual: Gartner Market Guide for Reputation Health Tracking (2026) + rascunho de score Aegea (pesos 10/5/1 por tier).

---

## 1. Modelo

**ISR (0–100) = média ponderada de 5 lentes.** Cada lente = um stakeholder, com suas fontes.

| Lente | Stakeholder | Fontes | Peso padrão |
|---|---|---|---|
| `imprensa` | formadores de opinião | Clipei (+ Edelman para meses sem base) | 30 |
| `mercado` | investidores e rating | Clipei: veículos Tier 1 com público-alvo Investidores | 20 |
| `sociedade` | redes em mar aberto | Approach SL, Bites | 20 |
| `clientes` | canais próprios | Approach CM | 15 |
| `institucional` | governo e entidades | CRM (campo `clima`) | 15 |

Se a soma dos pesos ≠ 100, normalizar pela soma.

## 2. Cálculo por lente
1. Para o mês, somar positivo / neutro / negativo (com as ponderações do §3).
2. `NS = (pos − neg) / (pos + neu + neg)`; total zero → lente sem dado.
3. `score = round((NS + 1) / 2 × 100)`.
4. Fontes múltiplas numa lente: **média simples dos NS** das fontes ativas (ex.: sociedade = média de Approach SL e Bites).
5. `ISR = round(Σ score_l × peso_l / Σ peso_l)` sobre as lentes com dado.

Mapeamento de sentimento: Clipei `POSITIVA/NEUTRA/NEGATIVA`; Bites/Approach `Positivo/Neutro/Negativo`; CRM `Propositivo→pos, Neutro→neu, Tenso→neg`. Menções sem sentimento ficam fora.

**Faixas**: Crítico <40 · Atenção 40–54 · Estável 55–69 · Sólido 70–84 · Referência ≥85.

## 3. Ponderações (configuráveis — aba Calibração)

**Tier de veículo** (Imprensa e Mercado), por matéria conforme `Aegea Tier` da Clipei:

| Opção | Muito Relevante | Relevante | Menos Relevante |
|---|---|---|---|
| `aegea` (padrão) | 10 | 5 | 1 |
| suave | 5 | 3 | 1 |
| forte | 20 | 5 | 1 |
| sem ponderação | 1 | 1 | 1 |
| só Tier 1 | 1 | 0 | 0 |

**Engajamento** (Sociedade e Clientes), por post/menção:
- `n` contagem (padrão): peso 1
- `log` recomendado: `1 + log10(1 + engajamento)`
- `bruto`: engajamento
- `cargo` (Bites, coluna Cargo): Presidente/Ministro/Governador 5 · Senador/Dep. Federal 4 · Dep. Estadual/Prefeito 3 · Vereador 2 · demais 1

**Fontes**: liga/desliga por fornecedor. Se todas as fontes de uma lente estão off, a lente sai do ISR e os pesos redistribuem; exibir aviso "lente X fora do cálculo".

**Pesos das lentes**: −/+ de 5 em 5, faixa 0–60. "Restaurar padrão" reseta pesos, tier, engajamento e fontes.

Persistência: calibração é **configuração da organização** (tabela `score_config`, versionada com autor e data), editável só por `coordenacao`. A Visão geral mostra chip "calibração ajustada" quando difere do padrão.

## 4. Registro de fontes (extensível)
Cada fornecedor é uma linha em `score_fonte`:
`id, nome, fornecedor, lente, tipo_arquivo, mapeamento_colunas (json: data, sentimento, tier, engajamento, cargo, unidade, tema, atributo), ativo, cobertura (meses com dado)`.

Novo fornecedor = nova linha + mapeamento de colunas, sem mudar código. A aba Calibração lista: fonte, lente, cobertura de meses, volume do mês, toggle.

## 5. Ingestão mensal
Upload dos exports (xlsx) por fonte e mês → parser pelo mapeamento → tabela `mencao` normalizada:
`fonte_id, mes, data, sentimento(pos|neu|neg), tier, engajamento, cargo, unidade, tema, atributo, veiculo, publico_alvo`.
Agregados mensais por lente calculados na ingestão (`score_mes_lente`) e recalculados quando a calibração mudar.

Exports de referência (junho/2026) estão em `referencias/` do projeto de origem: Clipei (1.506 matérias), Bites (7.869 posts), Approach (SL 10.418 menções, CM, Conteúdo).

## 6. Telas (5 abas)

1. **Visão geral** — ISR grande + faixa + régua com marcador; deltas vs. mês anterior e vs. janeiro; **leitura gerada** (qual lente sustenta, qual corrói, variação); cards "o que sustenta / o que corrói" (lente de maior e menor score); 5 cards de lente (score, delta, peso, fonte) → clique abre aba Lentes na lente; evolução mensal com lista de fatos do mês (cadastrável: mês, texto, efeito sustenta/pressiona/misto).
2. **Lentes** — abas das 5 lentes: barra pos/neu/neg, fórmula aplicada em texto, top 5 temas com barra pos×neg e selo **Estruturante / Operacional** (classificação do tema é cadastro: `tema.tipo`).
3. **Drivers e riscos** — Temas em perpetuação (tema negativo presente em ≥2 meses consecutivos: meses ativos, tipo, onde aparece; "novo" se só no mês corrente) · Atributos reputacionais (NS por atributo da Clipei, barra divergente centrada em zero) · Exposição por unidade (menções negativas por unidade nas redes + % negativo nos canais próprios).
4. **Calibração** — §3 e §4. Só `coordenacao`.
5. **Metodologia** — texto dos passos, aderência aos critérios Gartner (Coberto/Parcial/A integrar), lista de dados a integrar.

Seletor de mês no header vale para todas as abas.

## 7. Critérios de aceite
- [ ] Com os exports de junho e calibração padrão: Imprensa 70, ISR ≈ 58 (conferir contra o protótipo)
- [ ] Mudar tier/engajamento/fontes/pesos recalcula ISR e lentes sem reload
- [ ] Desligar Approach SL e Bites remove Sociedade e redistribui pesos com aviso
- [ ] Nova fonte cadastrada entra no cálculo sem deploy
- [ ] Diretoria vê Visão geral, Lentes, Drivers e Metodologia; não vê Calibração

## 8. Limitações conhecidas (declarar na tela Metodologia)
- Meses sem export da Clipei usam estimativa do resumo semestral (marcar como estimado).
- Mercado é proxy até integrar rating e spread de debêntures.
- Pendentes: share of voice de pares, economias por unidade (Score2), Reclame Aqui / Consumidor.gov / Google.
