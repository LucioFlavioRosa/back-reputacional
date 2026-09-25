# Handoff: Painel Reputacional Aegea — CRM dos Stakeholders

## Visão geral

Solução web para substituir a planilha `Demandas de Imprensa 2026.xlsx` (14 abas) que hoje concentra o registro das interações institucionais da Aegea. O produto tem duas naturezas:

1. **Cadastro** — um formulário único, com campos condicionais por tipo de interação, que alimenta uma tabela-mãe.
2. **Análise** — painéis que leem essa tabela e respondem perguntas de reputação: volume por frente, resolutividade, desfecho, exposição de porta-vozes, relacionamento com interlocutores, distribuição geográfica e temas estratégicos no tempo.

Escopo do MVP (Onda 1 do roadmap): **CRM dos Stakeholders** (este protótipo), **Síntese Executiva** e **Score Executivo** (ainda não construídos).

## Sobre os arquivos de design

Os arquivos deste pacote são **referências de design feitas em HTML** — protótipos que mostram aparência e comportamento pretendidos, **não código de produção para copiar**. A tarefa é **recriar esses designs no ambiente do codebase de destino** (React/Next, Vue, etc.), usando os padrões e bibliotecas já estabelecidos ali. Se ainda não existe ambiente, escolha a stack mais adequada e implemente os designs nela.

Os dados embutidos nos protótipos são **amostra sintética derivada da planilha real** (60 registros). Não são dados de produção e não devem ser migrados como estão — a carga real vem da planilha (ver `MODELO-DE-DADOS.md`, seção "Importação").

## Fidelidade

**Alta fidelidade (hifi).** Cores, tipografia, espaçamentos, estados de hover e interações estão definidos e seguem o guia visual oficial da Aegea (`PPT_Padrao_Aegea_V4.pdf`, incluído). Recriar com fidelidade visual, usando os componentes do codebase.

## Telas / views

O protótipo é uma SPA com sete views na navegação principal + duas modais + uma view de cadastro.

### 0. Login (`Login Reputacional Aegea.dc.html`) — entrada com SSO Microsoft
- **Propósito**: autenticar pelo diretório corporativo; o perfil de permissão vem do Entra ID.
- **Layout**: grid de duas colunas `1.05fr / 1fr`, altura mínima 100vh.
  - **Coluna de arte** (esquerda): imagem `assets/hero-agua.png` com `background-position: center bottom` e `background-size: auto 140%` (ancorada na crista da água, mantendo o wordmark do arquivo fora do corte), sobre gradiente `linear-gradient(155deg, rgba(0,39,189,0.72) 0%, rgba(0,39,189,0.44) 52%, rgba(23,227,203,0.14) 100%)`. Conteúdo em coluna com `justify-content: space-between`, padding 44px 48px: marca (círculo turquesa 36px + kicker "AEGEA · REPUTAÇÃO"), h1 40px/700/-0.03em com destaque em Georgia itálico turquesa e `text-shadow: 0 2px 18px rgba(0,25,120,0.4)`, parágrafo 15px `#EAEEFC`, e três números (7 frentes / 11 fontes / 28 unidades).
  - **Coluna de formulário** (direita): bloco centralizado de 392px, padding 40px 32px.
- **Componentes**:
  - **Botão SSO** (primário na hierarquia visual, altura 50px, borda `#D5DAEA`, raio 10px): logo Microsoft de quatro quadrantes 18px (`#F25022`, `#7FBA00`, `#00A4EF`, `#FFB900` em grid 2×2, gap 2px), rótulo "Entrar com a conta Microsoft Aegea". Em carregamento, borda passa a `#0027BD`, rótulo muda para "Redirecionando para a Microsoft…" e aparece spinner 15px (`@keyframes girar`, .7s linear infinite).
  - Nota abaixo: "Entra pelo Microsoft Entra ID (Azure AD) do tenant **aegea.com.br**, com MFA quando exigido pela política."
  - **Divisor** "ou" (linhas `#E2E5F0` + label 11px uppercase).
  - **Fallback e-mail/senha** recolhido atrás de um botão secundário "Entrar com e-mail e senha"; ao abrir, mostra e-mail, senha (Enter submete), checkbox "Manter conectado", link "Esqueci a senha", faixa de erro (`#FFE7E8` / `#B32328` com losango) e botão primário 46px.
  - **Perfis de acesso** listados com marcadores coloridos: Analista (`#0027BD`), Coordenação (`#17E3CB`), Diretoria (`#8C91A4`).
  - Aviso legal 11px `#A6ABBD` sobre Termos de Uso, Política de Privacidade e registro de acesso para auditoria.
- **Validações do protótipo**: campos obrigatórios; e-mail precisa terminar em `@aegea.com.br` (caso contrário: "Use um e-mail do domínio aegea.com.br ou entre pelo SSO.").
- **Responsivo**: `@media (max-width: 880px)` colapsa para uma coluna (arte vira cabeçalho de 240px, h1 28px); `@media (max-width: 520px)` esconde os números e reduz o h1 para 24px.
- **Em produção**: o botão dispara o fluxo OAuth 2.0 / OIDC do Microsoft Entra ID (authorization code + PKCE), com `tenant` restrito ao diretório da Aegea. O perfil (analista / coordenação / diretoria) vem de **claim de grupo** ou app role, não de cadastro local. O fallback e-mail/senha só deve existir se houver contas fora do diretório — se não houver, remover e deixar apenas o SSO.

### 1. Início (`view: 'home'`) — hub de módulos
- **Propósito**: ponto de entrada; mostra o roadmap em ondas e quais módulos estão disponíveis.
- **Layout**: hero full-bleed (imagem de água + gradiente Azul Mar → Turquesa, faixa ondulada dupla no rodapé do hero), depois seções: "MVP · Onda 1 — os três painéis executivos" (grid 1.35fr/1fr/1fr), "Squad evolutiva · ferramentas" (auto-fit, min 240px), "Análise por frente" (auto-fit, min 190px), "Jornada via ondas de evolução" (grid de 7 colunas, min 168px, com scroll horizontal), "As cinco camadas" (card escuro #191B23).
- **Componentes**: cards com ícone geométrico (composto só de círculos, quadrados e barras — sem SVG desenhado), selo de onda (MVP = #F8DC00 com texto #332727; ondas 2-6 = outline #D5DAEA).
- **Destaque tipográfico**: palavra em Georgia itálico (classe `.destaque`), assinatura do site oficial.

### 2. Painel (`view: 'painel'`) — visão consolidada
- **KPIs**: 6 cards em 2 linhas de 3 (grid `repeat(3,1fr)`, gap 14px). Cada card: barra superior turquesa 3px, label 11px uppercase #8C91A4, número 34px/700 letter-spacing -0.03em, hint 12px, seta → quando navega. Clique abre a visão executiva da frente correspondente.
  - Agendas institucionais (Governo + Parceiros) · Demandas de imprensa (com taxa de aproveitamento) · Eventos/participações · Agendas de investidores (split internacional/local) · Proposições legislativas · Tier 1 (com % da amostra).
- **Volumetria mensal por frente**: barras empilhadas por frente (8 meses), rótulo do total em linha de altura fixa (16px) acima e mês em linha de 14px abaixo — nunca dentro do trilho, senão meses zerados desalinham. Tooltip no hover da coluna: mês, total, quebra por frente com cores, Tier 1 e tema principal. Tooltip alinha pela borda nas colunas das pontas (índices 0-1 à esquerda, dois últimos à direita).
- **Clima da interação no tempo**: barras empilhadas Propositivo/Neutro/Tenso.
- **Temas no tempo**: 5 temas mais recorrentes, empilhados; unidade = ocorrências de tag (o número no topo é a soma dos segmentos). Clique na legenda filtra o painel.
- **Distribuição geográfica**: mapa do Brasil com bolha por UF, posicionada na capital, área proporcional ao volume (escala sqrt, raio máx ~5.5% da largura). Clique na bolha aplica o filtro de UF no app inteiro; clique novamente remove. Ranking por UF ao lado, também clicável.
- **Agendas de investidores**: total, quebra por tipo de investidor (clicável → filtra), últimas 4 agendas (clicável → abre a ficha).
- **Rankings**: Veículos e órgãos, Esfera e abrangência, Unidades de negócio — todos os itens clicáveis, aplicando o filtro correspondente.

### 3. Frentes (`view: 'detalhe'`) — visão executiva por frente
Abas: Institucionais · Imprensa · Eventos · Investidores · Legislativo · Tier 1.
- **Hero azul (#0027BD)**: número grande (64px) + frase de leitura gerada dos dados ("No período filtrado são N registros, com X como veículo mais frequente (n) e tema dominante Y. Agosto está Z acima de julho.").
- 4 mini-KPIs (Tier 1, em aberto, clima tenso, variação mês vs. anterior), curva mensal da frente, **Pontos de atenção** (card escuro, regras aplicadas sobre os dados, com concordância singular/plural correta), 3 rankings (interlocutores, porta-vozes, temas) e os 8 registros mais recentes (clique abre a ficha).

### 4. Status (`view: 'status'`)
- Taxa de resolutividade em destaque; 3 cards de grupo (Resolvidos = atendido/realizado/elaborado; Em aberto = agendado/em análise; Declinados) com número, %, barra e os status que compõem cada grupo como chips clicáveis.
- **Resolutividade por frente**: barra empilhada por frente (clique filtra), com legenda do agrupamento.
- **Fila de pendências**: cards com dias parados em destaque (78px à esquerda), chip da frente, entidade, data/status/tier e a pauta completa em texto corrido. Selo de risco: No prazo / Atenção (>30d) / Crítico (>60d).

### 5. Resultado (`view: 'resultado'`)
Taxa de avanço com denominador explícito, barra empilhada dos 4 desfechos (Avançou/Mantido/Retrocedeu/Sem definição) como cards clicáveis, taxa de avanço por frente, e dois indicadores: Retrocederam e Sem resultado informado (com % da base).

### 6. Porta-vozes (`view: 'portavozes'`) — 3 sub-abas
- **Exposição**: 4 KPIs (porta-vozes acionados, concentração no primeiro, média por porta-voz, exposição em Tier 1), alerta de concentração (>35% num único nome), e um card por porta-voz com cargo, total, barra relativa, faixa de aderência ao escopo (verde/âmbar/cinza), quebra por frente, temas e última aparição.
- **Comparativo de períodos**: janela selecionável (semestres / trimestres / últimos 90 dias), totais e variação, tabela por pessoa com barra dupla e delta colorido.
- **Cadastro de porta-vozes**: diretório editável — cargo (texto), temas autorizados (chips add/remove), toggle ativo/inativo, contagem de registros e alerta de "fora do escopo".

### 7. Interlocutores (`view: 'interlocutores'`) — 3 sub-abas
- **Panorama**: total, top 4 em cards, cards "Por frente" e "Contato único" (quem só apareceu uma vez), e a tabela completa com busca e cabeçalho fixo (colunas: Interlocutor / Veículo-órgão / Frente / Última / Registros).
- **Comparativo de períodos**: mesma janela, com dois indicadores próprios: **novos contatos** e **sem contato no período**.
- **Cadastro de interlocutores**: cargo, tipo (jornalista, gestor público, parlamentar, analista/investidor, executivo/representante de entidade — sugerido pela frente e pelo prefixo Sen./Dep.), temas de interesse, ativo/inativo.

### 8. Base (`view: 'base'`)
Tabela completa com 10 colunas (Data, Frente, Veículo/órgão, Unidade, Interlocutor, Pauta, UF, Relevância, Status, Tags), cabeçalho sticky, rolagem interna `calc(100vh - 340px)`, contagem do filtro e **Exportar CSV** (gera Blob com BOM, separador `;`, do recorte atual).

### 9. Cadastro (`view: 'cadastro'`)
Formulário único. O seletor de **tipo de registro** define os campos: Demanda de imprensa · Agenda de governo · Agenda externa/parceiros · Evento/participação · Agenda de investidores · Proposição legislativa · Demanda interna. Tags em dois níveis (vocabulário sugerido + criação livre por Enter). Ver campos completos em `MODELO-DE-DADOS.md`.

### Modais
- **Ficha do registro** (max-width 820px): cabeçalho azul com entidade + frente/data/tier; bloco **Conteúdo do registro** (cartões de leitura, só os campos preenchidos: pauta, posicionamento, relato, repercussão/encaminhamentos, pendências, observações, mensagens-chave, link, documentação); bloco **Classificação** (metadados preenchidos, 2 colunas); nota discreta listando os campos vazios **aplicáveis àquela frente**; **Comentários** (autor, data, avatar com inicial, campo para novo comentário); **Tags**.
- **Gerar relatório**: seletor de 8 seções com Todas/Nenhuma, resumo dos filtros no cabeçalho, e prévia em modal com Salvar PDF / Mudar seções / Fechar.

## Interações e comportamento

- **Filtros globais** em barra lateral esquerda (drawer 312px, overlay scrim, fecha por ×/Aplicar/clique fora). Campos: busca livre, Período, Frente, Esfera, Relevância, Clima, Resultado, Unidade de negócio, Veículo/órgão, Tipo de investidor, Tag, UF. A barra no topo mostra o botão "Filtros" com contagem de ativos + resumo textual do recorte.
- **Clicar em "Painel" na nav zera todos os filtros.** As outras abas preservam o recorte.
- **Todo item de ranking, chip, bolha do mapa e legenda de tema aplica filtro**; clicar no mesmo item remove.
- **Toggle, não navegação**: nenhuma ação de filtro deve trocar de aba sem o usuário pedir (regressão já corrigida uma vez: export CSV navegava para outra aba).
- **Um caminho por tarefa**: a nav é o único caminho para cada view; ações (novo registro, gerar relatório) são botões no header; a marca volta para o Início.
- Hover em cards/linhas: `background: #F8FAFF`; em cards de destaque: `border-color: #0027BD; box-shadow: 0 6px 18px rgba(0,39,189,0.10)`.
- Transições curtas (.12s) em border-color e box-shadow. Sem animação de entrada.

## Estado necessário

```
view                  'home' | 'painel' | 'detalhe' | 'status' | 'resultado' | 'portavozes' | 'interlocutores' | 'base' | 'cadastro'
drill                 frente da visão executiva
filtros               fPeriodo, fArea, fEsfera, fTier, fClima, fResultado, fUnidade, fEntidade, fSubtipo, fUf, fTags[], busca
filtrosAbertos        drawer lateral
recAberto             id do registro na ficha
relAberto / relUrl    seletor de seções / prévia do relatório
pvTab / pvJanela      sub-aba e janela de comparação (porta-vozes)
ilTab / ilJanela      idem (interlocutores)
pvDir / ilDir         diretórios editáveis (persistir no backend)
form / tags           cadastro em andamento
hoverMes              tooltip do gráfico
```

Todos os agregados (KPIs, séries mensais, rankings, filas) são **derivados** do conjunto filtrado — nada é armazenado pré-agregado no protótipo. Em produção, avaliar agregação no backend para as views de análise.

## Design tokens

**Cores (guia oficial Aegea)**
| Token | Hex | Uso |
|---|---|---|
| Azul Mar | `#0027BD` | primária, headers, barras |
| Azul Mar sombra | `#111799` | hover da primária |
| Turquesa Rio | `#17E3CB` | acento, positivo |
| Turquesa sombra | `#9DEEE7` | texto sobre azul |
| Amarelo Pequi | `#F8DC00` | selo MVP, frente Legislativo |
| Laranja-da-Baía | `#FE952B` | em aberto, atenção |
| Vermelho Pitanga | `#FF5C60` | tenso, declinado, crítico |
| Magenta Pitaia | `#E12379` | frente Investidores |
| Roxo Açaí | `#A11FFF` | frente Parceiros |
| Cinza 1 | `#E2E5F0` | bordas |
| Cinza 2 | `#8C91A4` | texto secundário |
| Cinza 3 | `#44495C` | texto de corpo |
| Cinza 4 | `#191B23` | texto principal, cards escuros |
| Fundo app | `#F4F6FC` | — |
| Fundo trilho | `#EEF1F8` | barras vazias |
| Hover | `#F8FAFF` | linhas e cards |
| Verde escuro | `#0A6B60` / `#00312C` | texto sobre turquesa |
| Âmbar texto | `#8A4E00` sobre `#FFF1DC` | atenção |
| Vermelho texto | `#B32328` sobre `#FFE7E8` | crítico |
| Verde texto | `#0A6B60` sobre `#DFFAF6` | ok |

**Cores por frente**: Imprensa `#0027BD` · Governo `#17E3CB` · Parceiros `#A11FFF` · Eventos `#FE952B` · Investidores `#E12379` · Legislativo `#F8DC00` · Interna `#8C91A4`. Chips de Governo e Legislativo usam texto `#00312C` (contraste).

**Tipografia**: DM Sans (Google Fonts, 400/500/700) — é a fonte alternativa oficial da Aegea para materiais digitais; fallback Arial. Destaque em **Georgia itálico** (equivalente ao Aegea Move do guia). Escala: 44px hero home · 38px número hero · 26px h1 de view · 21px título de modal · 16-17px h2 de card · 15px nome · 14px corpo · 13px tabela/label · 12px auxiliar · 11px kicker uppercase (letter-spacing .06em). Letter-spacing negativo (-0.02 a -0.03em) em números e títulos grandes.

**Espaçamento**: 4 / 5 / 6 / 8 / 10 / 12 / 14 / 16 / 18 / 20 / 22 / 26 / 32px. Padding de card 20-22px; gap de grid 14-16px; padding de main 28px 32px 64px; max-width 1440px (1180-1240px nas views de leitura).

**Raio**: 5px (chip pequeno) · 7-9px (botão, chip) · 11-12px (card interno) · 14px (card) · 16-18px (card de destaque, modal) · 50% (avatar).

**Sombras**: card em hover `0 6px 18px rgba(0,39,189,0.10)`; tooltip `0 8px 24px rgba(25,27,35,0.22)`; modal `0 24px 64px rgba(25,27,35,0.28)`; drawer `0 0 40px rgba(25,27,35,0.18)`.

**Barras/trilhos**: altura 7-9px (rankings), 12-16px (empilhadas), raio metade da altura, fundo `#EEF1F8`.

## Assets

- `assets/hero-agua.png` — imagem de água enviada pelo cliente, usada no hero e na faixa da home (`background-position: center 82%` para cortar o logo do topo).
- `brazil-map.js` — web component `<uf-bubble-map>`: contorno do Brasil a partir de **geometria real** (Natural Earth via world-atlas 2.0.2 + d3-geo/topojson-client, versões pinadas com integrity). Bolhas nas capitais (lat/lon reais). **Nunca desenhar geografia à mão.** Em produção, servir o TopoJSON do próprio backend/CDN interno.
- `doc-page.js`, `image-slot.js` — componentes de apoio do protótipo (documento paginado e slot de imagem). Não precisam ir para produção.
- `PPT_Padrao_Aegea_V4.pdf` — guia visual oficial (paleta, tipografia, faixas onduladas, elementos orgânicos).
- `Demandas de Imprensa 2026.xlsx` — planilha de origem, com as 14 abas e os comentários de célula.

## Arquivos deste pacote

| Arquivo | O que é |
|---|---|
| `Login Reputacional Aegea.dc.html` | tela de login com SSO Microsoft (Entra ID) + fallback e-mail/senha |
| `Painel Reputacional Aegea.dc.html` | protótipo principal (todas as views, cadastro, modais) |
| `Relatorio Reputacional Aegea.dc.html` | documento paginado do relatório executivo (export PDF) |
| `Home Reputacional Aegea.dc.html` | versão standalone da home/hub |
| `dados-crm.js` | amostra de dados + derivações (referência de shape) |
| `brazil-map.js` | componente do mapa de bolhas por UF |
| `MODELO-DE-DADOS.md` | entidades, campos, enums, importação da planilha |
| `API.md` | contrato sugerido de endpoints |
| `assets/hero-agua.png` | imagem do hero |

> Os `.dc.html` abrem direto no navegador. São documentos de referência: leia o markup para medidas exatas e a lógica para as regras de derivação.

## Backend — o que precisa existir

Ver `API.md` para o contrato sugerido e `MODELO-DE-DADOS.md` para o schema. Em resumo:

1. **CRUD de interações** com filtros server-side (os mesmos 12 filtros do painel), paginação e ordenação por data.
2. **Dicionários administráveis**: frentes, esferas, tiers, status, climas, resultados, formatos, tipos de investidor, fases de tramitação, unidades de negócio, temas/tags.
3. **Cadastros próprios**: porta-vozes (cargo, temas autorizados, ativo), interlocutores (cargo, tipo, temas de interesse, ativo), instituições/veículos.
4. **Comentários** por registro (autor, data, texto) — a planilha já tem comentários de célula que devem ser migrados.
5. **Agregações** para as views de análise (séries mensais, rankings, distribuição por UF, resolutividade, resultado, exposição por porta-voz, comparativo entre períodos).
6. **Importador da planilha** com tela de conferência (datas em número de série do Excel, células com múltiplos nomes, valores "N/A" e "0" que hoje entram como dado válido).
7. **Export**: CSV do recorte e PDF do relatório com seções selecionáveis.
8. **Permissões**: analista cadastra e edita o que criou; coordenação edita tudo e administra dicionários; diretoria só lê. Log de alteração por registro (o campo de relato é sensível).
9. **Autenticação via Microsoft Entra ID (Azure AD)**: OIDC / OAuth 2.0 com authorization code + PKCE, tenant da Aegea, MFA conforme política da companhia. O backend valida o `id_token`, mapeia grupo/app role → perfil de permissão, e mantém sessão própria (cookie httpOnly + refresh). Registrar cada acesso (usuário, timestamp, IP) para auditoria. Provisionamento de usuário no primeiro login (JIT), sem cadastro manual de senha.

## Pendências de produto (decidir antes de fechar escopo)

1. **O que é "reputacional" no indicador** — se a diretoria quer um índice único (Score Executivo), definir pesos por tier, clima e alcance, ou integrar clipping/análise externa.
2. **Fonte do Community Management** — "mensagens recebidas/respondidas" é métrica pedida e não existe na base atual.
3. **Agendas de investidores** — a plataforma de RI (Mz Group) integra ou o time de RI cadastra no sistema? Já existe campo "origem do registro" para marcar isso.
4. **Granularidade geográfica** — bolha por UF resolve hoje; município exige campo cidade obrigatório; choropleth exige malha do IBGE.
5. **Histórico a migrar** — só 2026, ou também 2025 (422 linhas) e ABCON-ML (3.075 linhas)?
6. **Onde roda** — app próprio, Power BI sobre base nova, ou SharePoint List + painel. Muda mais o cadastro que o painel.
7. **Unidade de negócio** — campo novo, inexistente na planilha; definir se será preenchido retroativamente.
8. **Login local** — manter o fallback de e-mail/senha ou exigir SSO para todos? Se houver acesso de terceiros (agência, consultoria), definir se entram como convidados no tenant (B2B) ou por conta local.
9. **Grupos do Entra ID** — quais grupos existentes mapeiam para analista, coordenação e diretoria, e quem administra essa associação.
