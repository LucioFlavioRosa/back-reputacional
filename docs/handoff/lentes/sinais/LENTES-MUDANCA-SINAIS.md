# Lentes v2 — Mudança: Sinais do período (analytics por regra)

**Este documento substitui partes da `LENTES-ESPECIFICACAO.md`.** Tudo o que não está aqui continua valendo como estava.

## 1. Resumo da mudança

| Antes | Agora |
|---|---|
| Curadoria mensal escrita à mão (manchete, títulos, leitura, "o que revela") | **Nada é escrito nem salvo como texto.** Frases geradas por detectores sobre os dados |
| Bloco "O que a lente revela" | **Removido** |
| Bloco "Encaminhamentos" (ação, dono, prazo) | **Removido** — ação é decisão de gestão, não sai do dado |
| — | **Novo bloco "Sinais do período"**: até 5 sinais por lente, ordenados por intensidade |

Sem LLM. Regras determinísticas, recalculadas sempre que os dados mudam.

## 2. O que é removido da especificação anterior

- §1, linhas **4. O que revela** e **5. Encaminhamentos** da tabela de estrutura.
- §4 **Conteúdo editorial (curadoria)** inteira.
- §5 tabelas `curadoria_lente` e `encaminhamento`.
- §6 endpoints `PUT/POST /score/curadoria/...` e `/score/encaminhamentos`.
- §7 critérios de aceite sobre curadoria, publicação, versionamento e encaminhamentos.
- O quadro lateral **"Leitura"** deixa de ter parágrafos editoriais: passa a mostrar os sinais da seção Evolução.

Continuam como cadastro, porque são **dado**, não análise: fatos do mês (`fato_mes`), eventos de mercado, estudos de percepção, matriz de jornalistas, respondidas do CM.

## 3. Onde os sinais aparecem

| Lugar na tela | Regra |
|---|---|
| **Manchete** (bloco Destaque) | 1º: sinal de **movimento recente** de Evolução ou Painel A, na ordem de tipo **Virada → Alta do negativo → Recuperação** (a nota da lente vem antes de indicadores operacionais); 2º: maior intensidade de Evolução/Painel A com tom positivo ou negativo; 3º: maior intensidade geral |
| **Título do gráfico de Evolução** | sinal de movimento recente com `secao = evo`; senão, o de maior intensidade da seção |
| **Quadro lateral "Sinais da evolução"** | até 3 sinais `evo` + lacunas de dado de `evo` |
| **Título do Painel A / Painel B** | mesma regra, por seção; sem sinal, usa o nome do painel |

**Regra de coerência:** a manchete nunca pode contradizer a variação do último mês mostrada no chip de nota. Por isso o movimento recente vem antes da intensidade.
| **Bloco "Sinais do período"** (fim da tela) | até `maxSinais` sinais reais por intensidade + todas as lacunas de dado no fim |

Sem nenhum sinal acima dos limites: "Sem variação relevante no período pelas regras atuais."

## 4. Estrutura de um sinal

```
{ tipo, frase, evidencia, secao: evo|pA|pB|geral, intensidade: number, tom: pos|neg|neu }
```
Na tela: chip do tipo (cor pelo tom) + "onde" (Evolução ou nome do painel) · frase · evidência em destaque.

## 5. Catálogo de detectores

Limites configuráveis (tabela `score_config`, aba Calibração, perfil `coordenacao`):

| Limite | Padrão |
|---|---|
| `picoDesvios` | 1,5 |
| `picoRazaoMin` | 1,3 |
| `viradaPontos` | 10 |
| `deslocamentoPP` | 10 |
| `tendenciaMeses` | 3 |
| `concentracaoRazao` | 3 |
| `concentracaoTop3` | 50% |
| `maxSinais` | 5 |

### 5.1 Série mensal de sentimento `{pos, neu, neg}` por mês
| Detector | Regra | Intensidade | Tom | Frase-modelo |
|---|---|---|---|---|
| **Pico** | z = (máx − média) ÷ desvio ≥ `picoDesvios` **e** máx ÷ média ≥ `picoRazaoMin` (volume) | z | neu | "{Mês} teve o maior volume do período ({n} {unidade}), {k}× a média mensal." |
| **Virada** | último vs. penúltimo mês com dado: \|Δ nota\| ≥ `viradaPontos` ou troca de sinal do NS | \|Δ\| ÷ limite | pos se subiu | "A nota {subiu/caiu} {Δ} pontos em {mês}: o negativo foi de {a}% para {b}%." |
| **Alta do negativo** | só se não houve Virada: Δ da fatia negativa ≥ `deslocamentoPP` | Δpp ÷ limite | neg | "O negativo subiu de {a}% em {mês1} para {b}% em {mês2}." |
| **Tendência** | fatia negativa estritamente monótona nos últimos `tendenciaMeses` | 1,2 | pos se cai | "O negativo {cai/sobe} há {n} meses seguidos: {a} → {b} → {c}." |
| **Deslocamento** | mês de maior fatia negativa ≠ último, queda ≥ `deslocamentoPP` **e** o último mês não piorou em relação ao anterior | Δpp ÷ limite | pos | "O negativo recuou de {a}% em {mês} para {b}% em {último}." |
| **Lacuna de dado** | meses só com total ou sem base | 0 (vai para o fim) | neu | "Sentimento de {meses} ainda não integrado. {Meses} sem base." |

### 5.2 Itens com composição `[label, pos, neu, neg]` (tier, tema, clima)
| Detector | Regra | Intensidade | Frase-modelo |
|---|---|---|---|
| **Tema dominante / Tier** | item de maior fatia negativa; compara com o geral quando os valores são contagens | fatia ÷ geral (ou fatia × 2 se %) | "{Item} concentra o maior negativo: {x}% (geral {g}%)." |
| **Sustenta** | item de maior fatia positiva, se diferente | fatia | "{Item} é o mais favorável: {x}% positivo." |

### 5.3 Ranking `[label, valor]` (unidades, órgãos)
| Detector | Regra | Frase-modelo |
|---|---|---|
| **Concentração** (razão) | 1º ÷ 2º ≥ `concentracaoRazao` | "{1º} tem {k}× o volume de {2º}, a segunda {unidade}." |
| **Concentração** (top 3) | senão, top 3 ≥ `concentracaoTop3` do total | "{A}, {B} e {C} concentram {x}% das {unidade}." |

### 5.4 Série de percentual (ex.: teor Reclamação)
| **Deslocamento** | máximo ≠ último e queda ≥ `deslocamentoPP` | "{Série} caiu de {a}% em {mês} para {b}% em {último}[, o menor peso do período]." |

### 5.5 Específicos por lente
| Lente | Detector | Regra | Seção |
|---|---|---|---|
| Imprensa | **Lacuna de relacionamento** | jornalista com maior (média de relevância e exposição) − proximidade | pB |
| Imprensa | **Prioridade** | contagem de P1 na matriz | pB |
| Mercado | **Pressão** | meses em que eventos "pressiona" > "sustenta", sobre meses com evento | evo |
| Mercado | **Concentração de eventos** | mês com ≥ 2 eventos de pressão (empate: o mais recente) | evo |
| Mercado | **Contraste** | maior − menor nota do estudo de percepção | pA |
| Mercado | **Rating** | agências com nova ação após o primeiro rebaixamento + perspectivas negativas | pB |
| Mercado | **Lacuna** | sem série mensal de sentimento → "a nota é um proxy" | geral |
| Clientes | **Pico** | sobre recebidas | evo |
| Clientes | **Recuperação** | taxa de resposta do último mês − mínima anterior ≥ `deslocamentoPP` | evo |

### 5.6 Mapeamento por lente
| Lente | Evolução (evo) | Painel A | Painel B |
|---|---|---|---|
| Imprensa | 5.1 sobre notícias × sentimento | 5.2 sobre tier × sentimento | 5.5 matriz |
| Mercado | 5.5 eventos | 5.5 contraste | 5.5 rating |
| Sociedade digital | 5.1 sobre menções | 5.2 sobre temas (%) | 5.3 sobre unidades |
| Clientes | 5.5 pico + recuperação | 5.1 sobre sentimento (sem pico) | 5.4 teor Reclamação |
| Institucional | 5.1 sobre clima | 5.2 sobre temas × clima | 5.3 sobre órgãos |

## 6. Backend

- Serviço `SinaisService.calcular(lente, mes, filtros)` → `sinais[]`, puro e sem estado, com um teste por detector.
- O payload de `GET /score/lentes/{lente}` passa a trazer: `manchete`, `evolucao.titulo`, `evolucao.sinais[]`, `paineis[i].titulo`, `sinais[]`. Nenhum desses campos vem de texto salvo.
- Frases-modelo em arquivo de templates (i18n), não espalhadas no código.
- Meses por extenso em minúsculas; números no padrão pt-BR; notas de 1 a 5 sempre com uma casa ("4,0").
- Plural/singular em todas as frases.

## 7. Critérios de aceite

- [ ] Nenhum texto analítico é salvo em banco; mudar um dado muda as frases na próxima leitura
- [ ] Com os dados de referência, as frases batem com o protótipo (lista abaixo)
- [ ] Mudar um limite na Calibração altera os sinais sem deploy
- [ ] Lacunas de dado aparecem sempre, no fim da lista
- [ ] Um teste unitário por detector, cobrindo: dispara, não dispara, dado ausente
- [ ] Removidos: curadoria, "O que revela", encaminhamentos

### Frases esperadas com os dados de referência
- **Imprensa**: manchete "O negativo subiu de 10% em julho para 23% em agosto." · "Junho teve o maior volume do período (1.529 matérias), 2,2× a média mensal." · "Relevante concentra o maior negativo: 30% (geral 15%)." · *não* gera Deslocamento (agosto piorou vs. julho)
- **Mercado**: "Solidez financeira (1,8) fica 2,2 pontos abaixo de eficiência operacional (4,0) — o maior contraste do estudo." · "2 agências voltaram a rebaixar depois de maio; Moody's com perspectiva negativa."
- **Sociedade digital**: manchete "A nota caiu 10 pontos em junho: o negativo foi de 45% para 57%." · "Corsan tem 7,9× o volume de Águas do Rio, a segunda unidade." · "Privatização concentra o maior negativo: 80%."
- **Clientes**: manchete "A nota subiu 11 pontos em agosto: o negativo foi de 35% para 29%." · "O negativo recuou de 60% em fevereiro para 29% em agosto." · "Reclamação caiu de 59% em maio para 34% em agosto, o menor peso do período." · "A taxa bruta de resposta voltou a 72% em agosto, após mínima de 50% em julho."
- **Institucional** (amostra): "Copasa / ALMG concentra o maior negativo: 60% (geral 21%)." · "O negativo cai há 3 meses seguidos: 21% → 18% → 17%."

## 8. Referência executável
`Lentes v2 - Sinais.html`: o bloco `// Sinais do período` do script contém `LIMITES`, os detectores (`detSerie`, `detItens`, `detRanking`, `detPct`), o mapeamento `SINAIS` por lente e `sinaisDe()`, que escolhe manchete, títulos e lista.
