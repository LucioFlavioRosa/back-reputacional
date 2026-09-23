# Painel Reputacional Aegea — roteiro para apresentação

Material de apoio para montar os slides. Cada bloco tem: o que mostrar, o porquê, e o número que sustenta. Números são do protótipo (junho/2026 salvo indicação).

---

## 1. Ponto de partida

**Hoje**: 14 abas de uma planilha ("Demandas de Imprensa 2026"), preenchidas à mão por Comunicação e Institucional. Campos repetidos com nomes diferentes, texto livre onde deveria haver lista, "N/A" e "0" contando como valor. Nenhuma visão consolidada; nenhum indicador de reputação.

**Materiais dispersos**: Clipei (clipping), Bites e Approach (redes), Edelman (imprensa), ArtPlan (publicidade), relatórios internos de métricas. Cada fornecedor com sua taxonomia e seu relatório mensal em PPT.

**Pergunta da diretoria** (doc "O que precisamos responder"): qual é a reputação da Aegea, o que a sustenta, o que a corrói, e isso é operacional ou estruturante?

**Tese**: uma base única de relacionamento (CRM) + um índice único de reputação (Score), no padrão visual Aegea, com caminho para produção.

---

## 2. Arquitetura da solução — o que existe no protótipo

Fluxo de telas:

1. **Login** — SSO Microsoft/Azure com a conta corporativa (padrão Aegea).
2. **Início** — central de módulos: o que está pronto, o que vem em ondas.
3. **CRM dos Stakeholders** — cadastro + análise (Painel, Frentes, Status, Resultado, Porta-vozes, Interlocutores, Base).
4. **Score Executivo** — Índice de Saúde Reputacional em cinco lentes.
5. **Relatório PDF** — documento paginado, gerado do recorte de filtros com seções selecionáveis.

Ondas de desenvolvimento (alinhadas ao slide de roadmap):
- **Onda 1 (MVP)**: CRM, Score, Síntese executiva.
- **Ondas seguintes**: Painel de alertas, Relatórios automáticos, análise por frente (Mercado, Marca, Imprensa, Redes, Publicidade, Institucional, ESG).

---

## 3. CRM dos Stakeholders — o porquê de cada decisão

### 3.1 Uma tabela-mãe, sete frentes
As 14 abas viram **tipos de interação** de uma só base: Imprensa, Governo, Parceiros, Legislativo, Eventos, Investidores, Interna. O formulário de cadastro muda os campos conforme o tipo, mas tudo cai na mesma tabela — é isso que permite cruzar imprensa, governo e RI sob o mesmo tema.

### 3.2 Listas fechadas onde havia texto livre
Esfera, tier, status, clima, resultado, unidade de negócio (28 empresas da holding), tipo de investidor. Acaba com "Atendido " ≠ "Atendido".

### 3.3 Tags em dois níveis
Temas estratégicos (vocabulário fechado: Universalização, Tarifa, IPO, Regulação, Copasa, Carbono…) + tags livres. O fechado sustenta séries comparáveis no tempo; o livre absorve o novo.

### 3.4 Pessoas e instituições como cadastro
Porta-vozes (com cargo e **temas autorizados** → alerta de quem fala fora do escopo), interlocutores (jornalistas, gestores, parlamentares), veículos/órgãos. Sem isso, "Radamés Casseb" e "Radamés" contam separado.

### 3.5 Filtros globais, um caminho só
Barra lateral com 12 filtros (período, frente, unidade, esfera, tier, clima, resultado, UF, veículo/órgão, tipo de investidor, tag, busca). **Qualquer clique em gráfico vira filtro** — bolha no mapa, barra de ranking, status, resultado — e o filtro vale em todas as abas. Ao voltar ao Painel, limpa.

### 3.6 Indicadores do Painel
- **Volumetria mensal por frente** (barras empilhadas, tooltip com detalhe do mês).
- **Clima no tempo** (propositivo / neutro / tenso por mês) — substitui o campo livre "postura".
- **Temas no tempo** (top tags por mês).
- **Distribuição geográfica** — mapa do Brasil com geometria real, bolha por UF.
- **Agendas de investidores** — frente própria de RI, por tipo de investidor.
- Rankings: veículos/órgãos, unidades, esfera, porta-vozes.

### 3.7 Status × Resultado (abas separadas — decisão de UX)
- **Status** = operacional: resolvido / em aberto / declinado, taxa de resolutividade por frente, fila de pendências com dias parados (No prazo · Atenção >30d · Crítico >60d).
- **Resultado** = desfecho: Avançou / Mantido / Retrocedeu / Sem definição. Responde "serviu para algo?" — e expõe a maior lacuna da base: quantos registros não têm resultado informado.

### 3.8 Porta-vozes e Interlocutores (mesma estrutura)
Exposição por pessoa, concentração (alerta acima de 35% num nome), comparativo entre períodos (semestre / trimestre / 90 dias), cadastro com temas autorizados e aderência ao escopo.

### 3.9 Ficha completa do registro
Clique em qualquer linha abre tudo: pauta, posicionamento, mensagens-chave, relato/encaminhamentos, pendências, documentação — os campos de "Relato" e "Registro/observações" da planilha original. Campos vazios aparecem como "não informado", só os aplicáveis àquele tipo.

### 3.10 Relatório PDF
Botão "Gerar relatório" → modal escolhe seções (resumo, volumetria, status, resultado, rankings, interlocutores, pendências, base) → documento paginado com cabeçalho/rodapé Aegea, respeitando o recorte de filtros e registrando-o na capa.

---

## 4. Score Executivo — Índice de Saúde Reputacional (ISR)

### 4.1 Por que um índice, e por que assim
- A Aegea tinha um rascunho de score (pesos 10/5/1 por tier, régua de indicadores) mas "solto" — sem stakeholders além da mídia, sem série, sem ligação com o relacionamento.
- Gartner (Market Guide for Reputation Health Tracking, jun/2026): saúde reputacional exige **múltiplos stakeholders**, agregação multifonte, benchmark histórico e contra pares, drivers do sentimento e ligação com resultado de negócio. Monitorar mídia não basta.
- Gartner (Painel Social com IA): separar **operacional × estruturante** e detectar **perpetuação** de temas negativos ("caça de ameaça narrativa").

### 4.2 Cinco lentes, um índice
| Lente | Stakeholder | Fonte | Peso padrão | Junho |
|---|---|---|---|---|
| Imprensa | formadores de opinião | Clipei, ponderado por tier 10/5/1 | 30% | 70 |
| Mercado | investidores e rating | Clipei Tier 1 econômico (proxy) | 20% | 67 |
| Sociedade digital | redes em mar aberto | Approach SL + Bites | 20% | 37 |
| Clientes | canais próprios | Approach CM | 15% | 42 |
| Institucional | governo e entidades | CRM (clima das interações) | 15% | 65 |

**ISR junho = 58 — Estável (faixa baixa).** Imprensa sustenta; redes corroem.

### 4.3 Cálculo (igual para todas as lentes)
1. Contar positivo / neutro / negativo no mês.
2. Sentimento líquido **NS = (pos − neg) ÷ total** (neutro dilui).
3. Escala **Score = (NS + 1) ÷ 2 × 100** → 0 tudo negativo, 50 equilíbrio, 100 tudo positivo.
4. **ISR = média ponderada** das lentes. Faixas: Crítico <40 · Atenção 40–54 · Estável 55–69 · Sólido 70–84 · Referência ≥85.

Exemplo Imprensa junho: 65×10 + 85×5 + 946×1 = 2.021 pos; 935 neu; 584 neg → NS 0,41 → **70**.

### 4.4 Ponderações (aba Calibração)
- **Tier de veículo**: 10·5·1 (Aegea, padrão) · 5·3·1 · 20·5·1 · 1·1·1 · só Tier 1. Um blog local não pode pesar como o Valor.
- **Engajamento nas redes**: contagem · 1+log₁₀(engajamento) (recomendado) · engajamento bruto · cargo do autor (Bites: ministro/governador 5 → vereador 2).
- **Fontes**: liga/desliga por fornecedor; se a única fonte de uma lente sai, a lente sai e os pesos redistribuem com aviso.
- **Pesos das lentes**: −/+ na tela, com "restaurar padrão". A Visão geral avisa quando a calibração não é a padrão.

### 4.5 Achados de junho para contar
- Redes por contagem: 40. Por log de engajamento: ~44. Por engajamento bruto: positivo da Approach (20,5 mil interações) supera o negativo (12,7 mil). **A negatividade é numerosa mas pouco amplificada** — muda a leitura de risco.
- Governança é o atributo mais fraco (score 35 na clipagem: 181 negativas vs 95 positivas). Prosperidade Compartilhada é o mais forte (976 positivas).
- Temas em perpetuação: Termo de Acordo/leniência (fev→jun, 5 meses), DFs e rating (mar→jun), Privatização/Copasa (6 meses), Corsan e boleto (operacionais, persistentes), CPI (novo em junho).
- Exposição por unidade: Corsan concentra 1.463 menções negativas em mar aberto (Bites); Águas do Rio 369; Manaus 181.

### 4.6 Fatos que explicam a curva (jan–jun)
- FEV: UOL TAB sobre o Termo de Acordo no STJ → pressiona.
- MAR: atraso/revisão das DFs; rebaixamentos S&P, Moody's, Fitch → pressiona.
- ABR: lucro R$ 856 mi em 2025; encontros com Valor e Bloomberg → sustenta.
- MAI: aporte US$ 1 bi Itaúsa e GIC (Brazil Week) → sustenta.
- JUN: CEO fala em IPO 2027 na CNN; disputa da Copasa; acordo no MT → misto.

### 4.7 Honestidades a declarar
- Clipping em base só para junho; jan–mai estimados do resumo semestral Edelman (4.324 matérias, 83% pos/neutro).
- Mercado é proxy até entrar rating e spread de bonds/debêntures (RI tem).
- Falta share of voice dos pares (Sabesp, Iguá, BRK, Copasa), economias por unidade (para o Score2 da Aegea), Reclame Aqui / Consumidor.gov / Google.

---

## 5. Como levar para o dia a dia

**Rotina semanal (analista)**
- Cadastra interações no CRM ao acontecerem (formulário por tipo, 2 min).
- Revisa a fila de pendências (>30d) e atualiza status/resultado.
- Confere aderência de porta-vozes ao escopo autorizado.

**Rotina mensal (coordenação)**
- Importa exports da Clipei, Bites e Approach → o Score recalcula.
- Lê "Drivers e riscos": o que se perpetua, o que é operacional × estruturante.
- Gera o Relatório PDF do mês com as seções relevantes.
- Ajusta calibração se a diretoria pedir (e registra o porquê).

**Rotina executiva (diretoria)**
- Uma tela: ISR, variação vs. mês anterior, o que sustenta, o que corrói.
- Cinco lentes em um olhar — clica na que preocupa.
- Alertas (próxima onda): Tier 1 com clima tenso, órgão estratégico sem contato há 90 dias, tema negativo ativo há 3+ meses.

**Governança do índice**
- Pesos e ponderações são decisão da diretoria, registrada; não mudam mês a mês.
- Cada fornecedor novo entra declarando: lente que alimenta, método de combinação com quem já está lá, cobertura.
- Metodologia publicada na própria ferramenta (aba Metodologia) — auditável.

---

## 6. Caminho para produção

- Pacote de handoff pronto (`design_handoff_painel_reputacional/`): modelo de dados, telas, regras, armadilhas de importação da planilha.
- Ordem sugerida: schema + seed → CRUD com filtros → importador da planilha (revela se o schema aguenta o dado real) → login SSO → cadastro → Base/ficha → Painel → demais abas → Score.
- Decisões em aberto: onde roda (app próprio, Power BI sobre base nova, SharePoint List); fonte do Community Management; papel da plataforma de RI; quanto histórico migrar (2025 + 3.075 linhas ABCON-ML).

---

## 7. Sugestão de sequência de slides (14)

1. Capa
2. O problema: planilha de 14 abas + materiais dispersos + pergunta sem resposta
3. A tese: CRM + Score, uma base, um índice
4. Arquitetura e fluxo de telas
5. CRM — uma tabela-mãe, sete frentes (mostrar cadastro)
6. CRM — Painel: qualquer clique vira filtro (mostrar mapa + rankings)
7. CRM — Status × Resultado: tratado ≠ resolvido
8. CRM — Porta-vozes: exposição, concentração, escopo autorizado
9. Score — por que cinco lentes (Gartner + rascunho Aegea)
10. Score — como calcula (fórmula + exemplo da Imprensa)
11. Score — junho: 58, o que sustenta, o que corrói
12. Score — achados: engajamento muda a leitura; governança é o driver fraco; perpetuação
13. Dia a dia: rotinas semanal / mensal / executiva
14. Próximos passos: ondas, dados a integrar, produção
