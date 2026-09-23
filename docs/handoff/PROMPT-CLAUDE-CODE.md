# Prompt para o Claude Code

Cole na primeira mensagem, dentro do repositório da sua aplicação, com esta pasta copiada para `docs/handoff/`.

---

Preciso implementar as **funcionalidades** do Painel Reputacional Aegea na nossa aplicação. **O front já tem o layout pronto** — não recrie telas nem estilos; conecte comportamento, dados e regras aos componentes existentes.

Pacote em `docs/handoff/`:
- `FUNCIONALIDADES.md` — comportamento tela a tela, filtros globais, drill-downs, ficha, relatório, com critérios de aceite. **Documento principal.**
- `SCORE.md` — Índice de Saúde Reputacional: fórmulas, ponderações, registro extensível de fontes, ingestão mensal.
- `MODELO-DE-DADOS.md` — entidades, campos por tipo de registro, enums, armadilhas da importação da planilha (§7).
- `API.md` — contrato sugerido de endpoints e autenticação.
- `*.dc.html` — protótipos executáveis. A classe `Component` de cada arquivo tem as regras exatas de cálculo; use como fonte de verdade das fórmulas, não como código a copiar.
- `dados-crm.js` — amostra **sintética**, só para referência de shape. Não use como seed de produção.

Regras:
1. **Antes de codar**, mapeie o front existente: liste as telas/componentes que já existem e aponte, para cada seção de `FUNCIONALIDADES.md`, qual componente recebe qual comportamento e o que falta. Me mostre esse mapa.
2. Reaproveite os componentes, rotas, gerenciamento de estado e cliente HTTP que já existem. Não introduza biblioteca nova sem me perguntar.
3. Filtros globais: um único estado compartilhado, sincronizado com a URL (§0.2). Todas as agregações do backend aceitam os mesmos filtros.
4. Cálculos de agregação e do Score ficam no **backend**; o front só exibe.
5. Relatório PDF gerado no backend e entregue como download.
6. Mapa com geometria real (d3-geo + TopoJSON servido pelo backend).
7. Auth: SSO Microsoft Entra ID, perfis por grupo (`analista`, `coordenacao`, `diretoria`).
8. Um PR por etapa, com testes. Ordem: schema + seeds → CRUD + filtros → importador da planilha → auth → cadastro → Base + ficha → Painel → Frentes → Status/Resultado → Porta-vozes/Interlocutores → Relatório → Score (ingestão → cálculo → telas → calibração).
9. Critério de pronto de cada etapa = os `[ ]` da seção correspondente.
10. Onde a especificação não decide, **pergunte**.

Comece pelo item 1: o mapa entre o front existente e a especificação, sem escrever código.
