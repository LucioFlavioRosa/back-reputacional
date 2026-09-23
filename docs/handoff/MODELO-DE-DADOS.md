# Modelo de dados — CRM dos Stakeholders

## 1. Uma tabela-mãe, sete tipos

As 14 abas da planilha atual repetem os mesmos campos com nomes diferentes. Na web, todas viram **uma tabela de interações**, e cada aba passa a ser um `tipo` filtrado.

| Tipo (`area`) | Abas de origem |
|---|---|
| `Imprensa` | 2025 · Demandas de Imprensa 2026 · _Apoio (listas) |
| `Governo` | Agendas de governo · Apura |
| `Parceiros` | Agendas externas parceiros · ABCON-CE · ABCON-REPORT |
| `Eventos` | Acompanhamento de eventos |
| `Investidores` | novo (hoje disperso na Planilha Mãe e na plataforma de RI) |
| `Legislativo` | ABCON-ML (3.075 linhas: Data, Proposição, TAG, Relato, Encaminhamentos) |
| `Interna` | Demandas e entregas · Temas internos |

## 2. Entidade `interacao`

### Campos comuns a todos os tipos
| Campo | Tipo | Obrigatório | Observações |
|---|---|---|---|
| `id` | uuid | sim | |
| `area` | enum Frente | sim | ver tabela acima |
| `data` | date | sim | "Data da interação" / "Data recebida" |
| `unidade` | enum UnidadeNegocio | não | empresa da holding; default "Holding / corporativo" |
| `stakeholder` | enum Stakeholder | não | Imprensa, Gestor público, Financeiro/investidor, Entidade setorial, Parlamentar, Sociedade civil, Evento/entidade |
| `postura` | enum Postura | não | Propositiva, Reativa, Defensiva, Sem manifestação |
| `tier` | enum Tier | sim | Tier 1 / 2 / 3 (relevância) |
| `esfera` | enum Esfera | não | Municipal, Estadual, Regional, Nacional, Internacional, Federal |
| `uf` | enum UF + Nacional/Internacional | não | alimenta o mapa; "Nacional" fica fora das bolhas |
| `entidade_id` | fk instituicao | sim | veículo, órgão, instituição ou proposição |
| `pessoa_id` | fk interlocutor | não | **pessoa** (jornalista, gestor, parlamentar, analista) — nunca instituição |
| `portaVoz_id` | fk porta_voz | não | quem representou a Aegea |
| `status` | enum Status | sim | ver §4 |
| `resultado` | enum Resultado | não | Avançou, Mantido, Retrocedeu, Sem definição (default) |
| `clima` | enum Clima | não | Propositivo, Neutro, Tenso |
| `origem` | enum | não | Proativo / Reativo (ou Procurada / Provocada, na imprensa) |
| `pauta` | text | sim | "Resumo da pauta" / "Pauta" / "Demanda" |
| `posicionamento` | text | não | "Posicionamento da Companhia" |
| `relato` | text | não | "Relato" / "Relato/Encaminhamentos" |
| `encaminhamentos` | text | não | "Repercussão / Encaminhamentos" |
| `pendencias` | text | não | "Pendências/Encaminhamentos/Resultado" — alimenta a fila de pendências |
| `observacoes` | text | não | "OBS" |
| `registro` | text/url | não | "Registro / documentação" (SharePoint) |
| `fonte` | enum | não | Cadastro manual / Plataforma de RI |
| `tags` | array de fk tema | não | ver §5 |
| `criado_por`, `criado_em`, `atualizado_em` | | sim | log de alteração |

### Campos condicionais por tipo
**Imprensa**: `formato` (Entrevista online/presencial/por e-mail, Posicionamento, Podcast, Encontro de relacionamento) · `dataAtendida` · `dataPub` · `link` · `mensagens` (mensagens-chave, separadas por `;`)

**Governo / Parceiros / Eventos**: `tipoInter` (Executivo, Legislativo, Judiciário, Entidade, Associação, Escritório, Investidor) · `equipe` (equipe Aegea) · `cargo` do representante · **Eventos** adicionam `evento` (nome do evento — não confundir com a entidade promotora nem com o interlocutor)

**Investidores**: `subtipo` (Fundo de investimento, Banco/sell-side, Agência de rating, Analista/research, Roadshow/conferência) · `formato` (Videoconferência, Presencial, Roadshow, Conferência, Call de resultados, E-mail) · `equipe`

**Legislativo**: `entidade` = proposição (ex. "PL 260/2024") · `casa` (Câmara, Senado, Congresso, Assembleia estadual, Câmara municipal) · `pessoa` = relator/autor · `tramitacao` (Apresentada, Em comissão, Pronta para pauta, Aprovada, Arquivada, Sancionada, Vetada) · `prioridade` (Alta, Média, Baixa, Monitoramento)

**Interna**: `entidade` = área demandante · `cumprimento` (Interno, Externo, Misto) · `complexidade` (Baixa, Média, Alta) · `prazo` · `dataRetorno`

## 3. Entidades de apoio

```
instituicao        id, nome, tipo (veículo | órgão | entidade | escritório | investidor | proposição), esfera, uf
interlocutor       id, nome, instituicao_id, cargo, tipo (Jornalista | Gestor público | Parlamentar |
                   Analista/investidor | Executivo de entidade | Representante de entidade | Outro),
                   temas_interesse[], ativo
porta_voz          id, nome, cargo, area, temas_autorizados[], ativo
tema (tag)         id, nome, nivel ('estrategico' | 'livre'), ativo
unidade_negocio    id, nome  → 28 valores + "Holding / corporativo" (ver §6)
comentario         id, interacao_id, autor, data, texto
```

Regra de negócio usada no painel: **fora do escopo** = registro cujo tema não está na lista de `temas_autorizados` do porta-voz que o conduziu.

## 4. Enums de status e agrupamento

```
Status  Agendado | Atendido | Declinado | Em análise | Realizado | Elaborado | Cancelado
Grupo   Resolvido  = Atendido, Realizado, Elaborado
        Em aberto  = Agendado, Em análise
        Declinado  = Declinado, Cancelado
```

Faixas de risco da fila de pendências (dias desde `data`): ≤30 **No prazo** · 31-60 **Atenção** · >60 **Crítico**.

## 5. Tags em dois níveis

- **Tema estratégico** (vocabulário fechado, administrável): Universalização, Tarifa, IPO, Regulação, Leilões, Copasa, Resíduos, Biometano, Reúso, Carbono, Clima, Inclusão sanitária, Modelo de negócio, Disciplina financeira, Cenário político, Tributário, Reputação.
- **Tag livre**, criada pelo analista, para o que é novo e não pode esperar governança.

Na planilha, o equivalente são as colunas `flag_*` da Planilha Mãe (Biometano, Carbono, Reuso, Universaliza, IPO, Tarifa, Residuos) e a coluna TAG da ABCON-ML.

## 6. Unidades de negócio (holding)

Holding / corporativo · Águas do Rio 1 · Águas do Rio 4 · Corsan · Águas de Manaus · Águas Guariroba · Prolagos · Águas de Teresina · Ambiental Ceará 1 · Ambiental Ceará 2 · Ambiental MS Pantanal · Ambiental Metrosul · Nascentes do Xingu · Águas de Governador Valadares · Águas de Palhoça · Águas de São Francisco do Sul · Águas de Camboriú · Águas de Penha · Águas de Bombinhas · Águas do Piauí · Águas do Pará (Blocos A, B, C, D) · Parsan · Padova · Regenera Rio · Reuso Itaboraí · Rio Investimentos

## 7. Importação da planilha

Mapeamento coluna a coluna por aba, com tela de conferência. Armadilhas reais encontradas no arquivo:

1. **Datas como número de série do Excel** (ex. `46127` = data; `2100` em coluna de data é lixo).
2. **Valores sentinela** que hoje entram como dado válido: `"N/A"`, `"0"`, `""`, e IDs numéricos soltos em colunas de texto (ex. coluna de porta-voz com `26`, `42`, `63`).
3. **Variações do mesmo valor**: `"Atendido "` vs `"Atendido"`; `"Radamés"` vs `"Radamés Casseb"` — normalizar antes de criar as FKs.
4. **Múltiplos nomes numa célula**, separados por quebra de linha (representantes, equipe interna) — quebrar em N registros de pessoa.
5. **Instituição no campo de pessoa**: em várias linhas o "representante" é "Câmara dos Deputados", "Comissão de…", "Mesa…", "Equipe…" — não são pessoas; devem ir para instituição ou ficar vazias.
6. **Nome do evento no campo de pessoa**, nas abas de eventos — vai para o campo `evento`.
7. **Comentários de célula** (4 no arquivo, incluindo um encadeado) → migrar para `comentario`, preservando autor e data.
8. **Colunas com o mesmo significado e nomes diferentes** entre abas — consolidar conforme §2.
9. **Linhas de fórmula** na Planilha Mãe (coluna "Linha origem" aponta para a aba de origem) — não importar em duplicidade.
