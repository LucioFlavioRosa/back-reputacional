# Especificação funcional — Painel Reputacional Aegea

Escopo: **comportamento**. O layout já existe no front de destino; este documento descreve o que cada tela faz, de onde vem cada número e como as telas se conectam. Critérios de aceite em `[ ]` no fim de cada seção.

Referência executável: os `.dc.html` deste pacote. A classe `Component` de cada arquivo contém as regras de derivação exatas — em caso de dúvida, o código do protótipo é a fonte.

---

## 0. Conceitos transversais

### 0.1 Registro de interação (entidade central)
Uma única tabela. Campo `area` define o tipo: `Imprensa | Governo | Parceiros | Legislativo | Eventos | Investidores | Interna`. Campos por tipo em `MODELO-DE-DADOS.md`.

Campos usados nos cálculos: `data`, `area`, `entidade` (veículo/órgão/instituição), `pessoa` (interlocutor), `portaVoz`, `unidade` (28 empresas da holding + "Holding / corporativo"), `uf`, `esfera`, `tier` (Tier 1/2/3), `status`, `clima` (Propositivo/Neutro/Tenso), `resultado` (Avançou/Mantido/Retrocedeu/Sem definição), `subtipo` (tipo de investidor), `tags[]`.

### 0.2 Estado global de filtros
Um único objeto de filtros, compartilhado por **todas** as abas do CRM (Painel, Frentes, Status, Resultado, Porta-vozes, Interlocutores, Base) e pelo Relatório.

| Filtro | Chave | Valor "sem filtro" | Regra |
|---|---|---|---|
| Período | `periodo` | `Ano 2026` | `Últimos 30/90/180 dias` relativo à data de referência |
| Frente | `area` | `Todas` | igualdade |
| Unidade de negócio | `unidade` | `Todas` | igualdade; vazio = "Holding / corporativo" |
| Esfera | `esfera` | `Todas` | igualdade |
| Relevância | `tier` | `Todos` | igualdade |
| Clima | `clima` | `Todos` | igualdade |
| Resultado | `resultado` | `Todos` | valor fora do enum conta como "Sem definição" |
| UF | `uf` | `Todas` | igualdade |
| Veículo / órgão | `entidade` | `Todas` | igualdade exata (não busca) |
| Tipo de investidor | `subtipo` | `Todos` | igualdade |
| Tag | `tags[]` | `[]` | **OU**: registro com qualquer tag selecionada |
| Busca livre | `busca` | `''` | contém, case-insensitive, em entidade + pessoa + pauta + uf + status + porta-voz + tags |

Regras:
- Filtros combinam em **E** entre si.
- **Persistir na URL** (query string) para permitir compartilhar recorte e voltar pelo navegador.
- Clicar em **Painel** no menu **limpa todos os filtros**.
- Barra superior mostra botão "Filtros (N)" com contagem de filtros ativos + resumo curto do recorte.
- Filtros abrem em **gaveta lateral esquerda** (overlay): busca, 11 selects empilhados, "Limpar tudo" e "Aplicar". Fecha por ×, Aplicar ou clique fora.
- Oculta a barra na tela Início e no Cadastro.

### 0.3 Clique vira filtro (drill-down)
Todo elemento de ranking ou gráfico é clicável e **seta um filtro global** (toggle: clicar de novo remove):

| Origem | Efeito |
|---|---|
| Bolha do mapa | `uf` = UF da bolha |
| Ranking Veículos e órgãos | `entidade` |
| Ranking Esfera e abrangência | `esfera` |
| Ranking Unidades de negócio | `unidade` |
| Agendas de investidores (tipo) | `area=Investidores` + `subtipo` |
| Composição por status | vai para Base com status na busca |
| Resultado (cada faixa) | `resultado` + vai para Base |
| Taxa de avanço por frente | `area` + `resultado=Avançou` + vai para Base |
| Resolutividade por frente | `area` + vai para Base |
| Card de porta-voz / interlocutor | vai para Base com o nome na busca |
| Card KPI do Painel | vai para Frentes (aba da frente) ou Base |

Elemento selecionado fica destacado; os demais perdem opacidade.

### 0.4 Ficha do registro (modal)
Clique em qualquer linha (Base, Frentes, fila de pendências) abre modal com todos os campos. Blocos de texto longo em destaque: **Pauta, Posicionamento, Mensagens-chave, Relato / Encaminhamentos, Pendências, Observações/Documentação** (colunas "Relato", "Relato/Encaminhamentos", "Registro / documentação / observações" da planilha).
- Campos vazios: mostrar nota "N campos não preenchidos" listando **apenas campos aplicáveis ao tipo** do registro (os do formulário daquela `area`). Não listar campos de outras frentes.
- Fecha por ×, "Fechar" ou clique fora. Esc também.

### 0.5 Concordância
Toda contagem com singular/plural ("1 registro" / "N registros", "1 interação tensa").

- [ ] Um filtro aplicado numa aba vale em todas as outras
- [ ] URL reproduz o recorte ao recarregar
- [ ] Menu Painel limpa filtros
- [ ] Todos os drill-downs da tabela 0.3 funcionam como toggle

---

## 1. Login
- SSO Microsoft Entra ID (OIDC, authorization code + PKCE), tenant Aegea. Botão único "Entrar com a conta corporativa Microsoft".
- Perfil vem de **grupo** do Entra: `analista` (cadastra/edita o que criou), `coordenacao` (edita tudo, administra listas e calibração do Score), `diretoria` (somente leitura).
- Sem cadastro local de senha.

- [ ] Usuário fora dos grupos recebe tela de acesso negado
- [ ] Perfil diretoria não vê botões de cadastro/edição nem aba Calibração

---

## 2. Início
Central de módulos. Cards com estado: **Disponível** (navega) ou **Em desenvolvimento / Onda N** (não clicável).
- CRM dos Stakeholders → Painel
- Score Executivo → Score
- Demais (Síntese, Alertas, Relatórios, análise por frente) → estado "em ondas"
Conteúdo das ondas deve ser configurável (lista vinda do backend ou arquivo de config), não hard-coded.

---

## 3. Cadastro
- Seletor de **tipo de registro** (7 frentes). Trocar o tipo troca os campos do formulário (mapa completo em `MODELO-DE-DADOS.md` e em `camposDe()` do protótipo).
- Campos comuns: data*, esfera, relevância*, UF, unidade de negócio.
- Obrigatórios mínimos: data, entidade, status, pauta.
- **Tags**: input com Enter cria tag livre; chips sugeridos (vocabulário fechado) clicáveis; chip selecionado remove ao clicar.
- Salvar: grava **todos** os campos preenchidos (não só os usados em gráficos); `resultado` vazio grava "Sem definição". Registro aparece imediatamente em todas as abas.
- Lista "Últimos registros" ao lado.

- [ ] Cada tipo mostra exatamente seus campos
- [ ] Registro salvo aparece na Base e na ficha com todos os campos

---

## 4. Painel (visão consolidada)
Todos os números respeitam os filtros globais.

**KPIs (2 linhas, clicáveis)**: Agendas institucionais (Governo+Parceiros) · Demandas de imprensa (N atendidas · % aproveitamento = Atendido ÷ total imprensa) · Eventos · Agendas de investidores (internacionais × locais) · Proposições legislativas · Tier 1 (% do total).

**Volumetria mensal por frente**: barras empilhadas por mês × área. Hover mostra tooltip: mês, total, quebra por frente, nº Tier 1, tema principal. Tooltip alinhado à borda nas colunas das extremidades.

**Clima no tempo**: barras empilhadas Propositivo/Neutro/Tenso por mês.

**Temas no tempo**: top N tags (N≈6) empilhadas por mês. Total do mês = soma das ocorrências das tags exibidas (mesma unidade dos segmentos).

**Distribuição geográfica**: mapa do Brasil (geometria real, d3-geo + TopoJSON servido pelo backend), bolha por UF na capital, área ∝ volume (escala sqrt). Clique = filtro UF. Ranking por UF ao lado. Contagem "sem UF definida" (Nacional/Internacional). Altura igual ao card de investidores.

**Agendas de investidores**: total, quebra por tipo (clicável), últimas agendas.

**Rankings**: Veículos e órgãos · Esfera e abrangência · Unidades de negócio · (clicáveis, ver 0.3).

**Relatório**: botão "Gerar relatório" no header (ver §10).

---

## 5. Frentes (visão executiva por frente)
Abas: Institucionais · Imprensa · Eventos · Investidores · Legislativo · Tier 1.
- Manchete com total + **frase de leitura gerada**: interlocutor mais frequente, tema dominante, variação do mês corrente vs. anterior.
- 4 mini-KPIs: Tier 1 · Em aberto (Agendado/Em análise) · Clima tenso · Mês vs. anterior.
- Curva mensal da frente.
- **Pontos de atenção** por regra: pendências abertas; clima tenso concentrado num tema; volume de declinadas.
- Rankings: interlocutores, porta-vozes, temas. 8 registros recentes (abrem ficha).

---

## 6. Status (operacional)
Agrupamento: **Resolvido** = Atendido/Realizado/Elaborado · **Em aberto** = Agendado/Em análise · **Declinado** = demais.
- KPIs: taxa de resolutividade (resolvidos ÷ total) · em aberto · declinados · pendência mais antiga (dias) · acima de 30 dias.
- Composição por status (clicável → Base).
- Resolutividade por frente: barra empilhada 3 grupos + % resolvido (clicável).
- **Fila de pendências**: em aberto ordenados por dias desde `data`. Selo: No prazo ≤30 · Atenção 31–60 · Crítico >60. Linha abre ficha.

## 7. Resultado (desfecho)
- Taxa de avanço = Avançou ÷ registros com resultado definido.
- Barra empilhada das 4 faixas + contagem/percentual (clicável).
- Taxa de avanço por frente (clicável).
- Destacar volume "Sem definição" como lacuna de qualidade da base.

---

## 8. Porta-vozes
Sub-abas:
1. **Exposição** — KPIs: acionados, concentração no 1º (%), média por pessoa, exposição Tier 1. Alerta se o 1º concentra ≥35%. Card por pessoa: cargo, total, barra relativa, quebra por frente, temas top 3, interações tensas, última aparição, **aderência ao escopo** (verde = tudo dentro dos temas autorizados; âmbar = N fora, com os temas; cinza = sem temas cadastrados).
2. **Comparativo de períodos** — janelas: semestres · trimestres · últimos 90 vs. 90 anteriores. Totais A, B, variação; tabela por pessoa com barra dupla e delta colorido.
3. **Cadastro** — cargo editável, temas autorizados (adicionar/remover chips), ativo/inativo. Recalcula aderência ao salvar. Só coordenação edita.

Regra de "fora do escopo": registro do porta-voz com ao menos uma tag que não está nos temas autorizados dele.

## 9. Interlocutores
Mesma estrutura de Porta-vozes, aplicada a `pessoa`. Excluir da lista nomes coletivos (Câmara…, Comissão…, Equipe…, Time…, Analistas…, Investidores…, Representantes…) e nomes iguais ao nome do evento. Card mostra veículo/órgão (casa legislativa quando Legislativo), frente, total, último contato.

---

## 10. Base e Relatório
**Base**: tabela com rolagem interna, todos os registros do recorte, ordenados por data desc. Linha abre ficha. Exportar CSV (separador `;`, BOM UTF-8, colunas: data, área, entidade, pessoa, porta-voz, esfera, uf, unidade, tier, clima, status, resultado, pauta, tags).

**Gerar relatório** (modal):
1. Mostra o recorte atual (resumo dos filtros + nº de registros).
2. Checklist de 8 seções: Resumo executivo · Volumetria mensal · Status e resolutividade · Resultado · Rankings · Interlocutores · Pendências · Base de registros. Atalhos Todas/Nenhuma.
3. "Gerar" → PDF paginado (A4/Letter), cabeçalho e rodapé Aegea em toda página, tabelas repetem cabeçalho, cards não quebram. Capa registra o recorte de filtros.
4. **Gerar no backend** (HTML → PDF headless) e devolver arquivo para **download**, não diálogo de impressão do navegador.

- [ ] PDF contém apenas as seções marcadas
- [ ] PDF respeita todos os filtros e os imprime na capa

---

## 11. Score Executivo
Especificação completa em `SCORE.md`.

---

## 12. Fora de escopo agora
Share of Voice / benchmark de pares, Síntese Executiva, Painel de Alertas — seguem nas ondas seguintes (ver roteiro em `referencias/`).
