# Prompt para o Claude Code — Lentes v2

Cole na primeira mensagem, dentro do repositório, com esta pasta em `docs/handoff/lentes/`.

---

Preciso implementar a tela **Lentes v2** do Score Executivo na nossa aplicação (front, back e banco se necessário). Ela substitui a aba Lentes atual.

Arquivos em `docs/handoff/lentes/`:
- `LENTES-ESPECIFICACAO.md` — **documento principal**: estrutura fixa da tela, 8 tipos de visualização, regras de cada uma das 5 lentes, curadoria editorial mensal, tabelas novas, API e critérios de aceite.
- `Lentes v2 - Proposta.html` — protótipo executável (abre no navegador). É a referência visual e de comportamento. O objeto `LENTES` do script mostra de onde sai cada número; use como fonte das regras, não como código a copiar. Os dados dele são de referência (relatório Jan-Ago 2026), não seed de produção.

Contexto: o Score Executivo, a ingestão de fontes (`mencao`, `score_fonte`, `score_config`) e o CRM já foram especificados no pacote anterior (`docs/handoff/SCORE.md`, `MODELO-DE-DADOS.md`, `API.md`). Reaproveite o que já existe.

Regras:
1. **Antes de codar**, me mostre: (a) o que já existe no repo que atende a esta tela, (b) as tabelas e endpoints novos que você vai criar, (c) como vai organizar os 8 tipos de gráfico como componentes reutilizáveis, alinhados ao layout e à biblioteca de gráficos que o front já usa.
2. Cálculo no backend; um endpoint devolve o payload completo da lente (§6). O front só renderiza.
3. Os 8 tipos de visualização são componentes genéricos; as lentes só configuram.
4. Implemente os estados de dado ausente da §2 desde o início.
5. Curadoria editorial (§4) com rascunho, publicação e versionamento; rascunho automático quando não houver curadoria.
6. Perfis: `coordenacao` edita curadoria, matriz, eventos e encaminhamentos; `diretoria` só lê conteúdo publicado.
7. Um PR por etapa, com testes. Ordem: tabelas novas + migrations → endpoint da lente (Imprensa primeiro) → componentes de gráfico → tela com as 5 lentes → curadoria → CRUDs de apoio (eventos de mercado, estudos, matriz, encaminhamentos).
8. Critério de pronto de cada etapa = os `[ ]` da §7.
9. Onde a especificação não decide, **pergunte**.

Comece pelo item 1, sem escrever código.
