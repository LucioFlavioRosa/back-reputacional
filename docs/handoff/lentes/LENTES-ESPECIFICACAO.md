# Lentes v2 — Especificação para produção

Módulo: **Score Executivo › Lentes**. Dossiê por stakeholder em que as cinco lentes do Índice de Saúde Reputacional (ISR) seguem a mesma estrutura. Referência visual e executável: `Lentes v2 - Proposta.html` (arquivo único, abre sem internet). As regras de cálculo estão no objeto `LENTES` do script.

Pressupõe o que já foi especificado no pacote anterior (`SCORE.md`, `MODELO-DE-DADOS.md`, `API.md`): tabela `mencao` normalizada, `score_fonte`, `score_config` e a fórmula NS → 0–100.

---

## 1. Estrutura fixa da tela (igual nas 5 lentes)

Navegação: 5 abas no header — Imprensa · Mercado · Sociedade digital · Clientes · Institucional. Seletor de mês de referência (herdado do Score).

| Bloco | Conteúdo | Origem |
|---|---|---|
| **1. Destaque** | nota da lente (0–100), variação vs. mês anterior, mês de referência, fontes, **manchete** (1 frase), 4 KPIs | cálculo + texto editorial |
| **2. Evolução** | rótulo + **título-conclusão** + gráfico mensal (jan–dez) + marcadores de fato por mês + lista de fatos + quadro "Leitura" (2–4 parágrafos) | série mensal + fatos + texto |
| **3. Dois painéis** | cada painel: rótulo, título-conclusão, visualização, legenda, nota de fonte | agregados específicos da lente |
| **4. O que revela** | 3–4 insights numerados (título + texto) | texto editorial |
| **5. Encaminhamentos** | ação, responsável, prazo | cadastro (plano de ação) |

Regra de design: **todo gráfico abre com a frase que ele prova.** O título nunca pode contradizer o dado (validar na revisão editorial).

## 2. Tipos de visualização (componentes reutilizáveis)

Implementar como componentes genéricos que recebem dados por props; cada lente só escolhe o tipo.

| Tipo | Uso | Dados |
|---|---|---|
| `barras_empilhadas` | evolução de sentimento/clima | `[{mes, pos, neu, neg}]`, total no topo |
| `barras_pareadas` | recebidas × respondidas | `[{mes, a, b}]`, % b/a no topo |
| `linha_do_tempo` | eventograma (Mercado) | `[{mes, eventos:[{texto, efeito}]}]`; borda do mês colorida pelo efeito predominante |
| `barras_100` | composição por item (tier, tema, mês) | `[{label, pos, neu, neg, nota}]` |
| `barras_horizontais` | rankings | `[{label, valor, nota}]` |
| `escala_1a5` | percepção (estudo) | `[{label, nota, hint}]` |
| `tabela` | rating, teor | `head[]`, `rows[][]`, célula com destaque condicional |
| `matriz_prioridade` | jornalistas | `[{nome, veiculo, relevancia, exposicao, proximidade}]` → pontos e prioridade |

Estados obrigatórios:
- **Mês sem base**: barra hachurada tracejada e "—" no topo.
- **Total sem sentimento**: barra cinza única com tooltip "sentimento a integrar".
- **Célula sem dado**: "—" em cinza claro.
- Tooltip com valor absoluto em todo segmento.

Cores: positivo `#17E3CB` · neutro `#D5DAEA` · negativo `#FF5C60` · recebidas `#C3CDF7` · respondidas `#0027BD`. Efeito dos fatos: pressiona `#FF5C60` · sustenta `#17E3CB` · misto `#9DA6C9`.

## 3. Especificação por lente

### 3.1 Imprensa — fonte Clipei (peso por tier 10/5/1)
- **Nota**: NS ponderado por tier do mês de referência.
- **KPIs**: matérias no ano (e média/mês) · % positivas + neutras · pico negativo (mês e volume) · nº de jornalistas prioridade 1.
- **Evolução**: `barras_empilhadas` pos/neu/neg por mês + fatos.
- **Painel A — Tier × sentimento**: `barras_100` por `Aegea Tier` (Muito Relevante, Relevante, Menos Relevante); nota = total e % negativo.
- **Painel B — Matriz de jornalistas**: `matriz_prioridade`. Pontos = relevância + exposição + proximidade (1–5 cada). Prioridade: P1 13–15 (contínuo) · P2 10–12 (semestral) · P3 7–9 (tático) · P4 <7 (monitoramento). **Exposição pode ser sugerida automaticamente** pelo volume do jornalista na Clipei (quintis); relevância e proximidade são cadastro.

### 3.2 Mercado — fontes Clipei Tier 1 econômico, agências de rating, estudos de percepção
- **Nota**: proxy atual (veículos Muito Relevantes com público-alvo Investidores). Exibir "proxy" no mês de referência e "sem série" na variação até existir série.
- **KPIs**: notas do estudo de percepção (solidez financeira, eficiência operacional) · nº de rebaixamentos no ano · nº de entrevistas do estudo.
- **Evolução**: `linha_do_tempo` a partir de `evento_mercado` (divulgações, ações de rating, operações, saída de executivos).
- **Painel A — Percepção**: `escala_1a5` com os atributos do estudo (hoje: eficiência operacional 4,0; solidez financeira 1,8).
- **Painel B — Rating**: `tabela` agência × nota por data × perspectiva; rebaixamento em vermelho.

### 3.3 Sociedade digital — fontes Approach SL + Bites
- **Nota**: média dos NS das fontes ativas (regras e ponderação por engajamento/cargo em `SCORE.md`).
- **KPIs**: menções no período e variação vs. semestre anterior · % positivo · % negativo (ambos com o valor do semestre anterior) · unidade com mais menções.
- **Evolução**: `barras_empilhadas` + fatos.
- **Painel A — Temas × sentimento**: `barras_100` top 6 temas; nota = % do sentimento dominante.
- **Painel B — Concessionárias**: `barras_horizontais` volume por unidade + mês de pico.

### 3.4 Clientes — fonte Approach CM
- **Nota**: NS das mensagens recebidas.
- **KPIs**: recebidas no ano (pico) · taxa bruta de resposta (mês e mínima) · % negativo (vs. pico) · % elogio.
- **Evolução**: `barras_pareadas` recebidas × respondidas, % no topo.
- **Painel A — Sentimento**: `barras_100` por mês.
- **Painel B — Teor**: `tabela` mês × Reclamação/Dúvida/Elogio (% e volume). Destacar Reclamação ≥ 50%.
- **Taxa operacional**: calcular também com mensagens **acionáveis** (excluir marcações, spam, stories vencidos) — exige flag `acionavel` na ingestão do CM. Exibir as duas taxas quando existir.

### 3.5 Institucional — fonte CRM dos Stakeholders
- **Nota**: NS do clima (Propositivo/Neutro/Tenso) das agendas de governo, parceiros e legislativo.
- **KPIs**: agendas no período · % propositivo · % tenso (com tema principal) · % "Avançou" entre as agendas com resultado.
- **Evolução**: `barras_empilhadas` de clima por mês.
- **Painel A — Temas × clima**: `barras_100` por tag.
- **Painel B — Órgãos**: `barras_horizontais` por entidade.

Todos os números da lente Institucional respeitam os filtros globais do CRM quando a tela é aberta a partir dele.

## 4. Conteúdo editorial (cadastro)

Nova área **Curadoria mensal** (perfil `coordenacao`), por lente e mês:
- `manchete` (até 280 caracteres)
- `evo_titulo` e `painel_a_titulo` / `painel_b_titulo` (títulos-conclusão)
- `leitura[]` (2–4 parágrafos)
- `revela[]` (3–4 itens: título + texto)
- `fato_mes[]` (mês, texto, efeito: sustenta/pressiona/misto) — também alimenta a Visão geral do Score
- `encaminhamento[]` (ação, responsável, prazo, status: aberto/em andamento/concluído)

Comportamento:
- Sem curadoria no mês → gerar **rascunho automático** a partir dos dados (maior variação, tema dominante, unidade com mais negativo) com selo "rascunho automático".
- Histórico versionado; publicar torna visível para a diretoria.
- Encaminhamentos pendentes de meses anteriores continuam visíveis até concluídos.

## 5. Dados novos

| Tabela | Campos | Observação |
|---|---|---|
| `evento_mercado` | data, tipo (resultado, rating, operação, governança, outro), agência, nota_anterior, nota_nova, perspectiva, texto, efeito | alimenta linha do tempo e tabela de rating |
| `estudo_percepcao` | id, instituto, data, amostra, publico | ex.: Brunswick, 20 entrevistas |
| `estudo_atributo` | estudo_id, atributo, nota (1–5), comentario | |
| `jornalista_matriz` | pessoa_id, veiculo, relevancia, exposicao, proximidade, atualizado_em | exposição com valor sugerido |
| `curadoria_lente` | lente, mes, campos da §4, status, autor, versao | |
| `encaminhamento` | lente, mes_origem, acao, responsavel, prazo, status | |
| `mencao` (existente) | + `teor` (Reclamação/Dúvida/Elogio/Informação/Sugestão), + `acionavel` (bool) | CM |

## 6. API (sugestão)

- `GET /score/lentes/{lente}?mes=AAAA-MM` → payload completo da tela: `{nota, delta, kpis[], evolucao{tipo, serie[], fatos[]}, paineis[2]{tipo, dados}, curadoria{...}, encaminhamentos[]}`. Um endpoint por tela; o front não calcula.
- `PUT /score/curadoria/{lente}/{mes}` · `POST /score/curadoria/{lente}/{mes}/publicar`
- CRUD: `/score/eventos-mercado`, `/score/estudos`, `/score/jornalistas-matriz`, `/score/encaminhamentos`

## 7. Critérios de aceite

- [ ] As 5 lentes renderizam a mesma estrutura de blocos com os tipos de gráfico da §3
- [ ] Com os dados de referência (junho/agosto 2026) os números batem com o protótipo
- [ ] Mês sem base, total sem sentimento e célula vazia aparecem como na §2
- [ ] Trocar o mês de referência recalcula nota, delta, KPIs e destaca o mês nos gráficos
- [ ] Curadoria salva como rascunho, publica e versiona; sem curadoria aparece o rascunho automático
- [ ] Diretoria só vê conteúdo publicado; não vê a Curadoria
- [ ] Encaminhamentos abertos de meses anteriores permanecem visíveis
- [ ] Matriz de jornalistas recalcula pontos e prioridade ao editar

## 8. Fora de escopo agora
Share of voice de pares, spread de bonds na lente Mercado e série mensal de Mercado seguem para a próxima onda.
