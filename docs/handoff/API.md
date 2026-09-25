# Contrato sugerido de API

REST/JSON. Todos os endpoints de leitura aceitam o **mesmo conjunto de filtros** do painel, para que qualquer view possa ser reproduzida server-side.

## Query params de filtro (comuns)

```
periodo      ano-2026 | ultimos-30 | ultimos-90 | ultimos-180   (ou de/ate explícitos)
de, ate      ISO date
area         Imprensa | Governo | Parceiros | Eventos | Investidores | Legislativo | Interna
unidade      nome da unidade de negócio
uf           sigla | Nacional | Internacional
esfera       Municipal | Estadual | Regional | Nacional | Internacional | Federal
tier         Tier 1 | Tier 2 | Tier 3
clima        Propositivo | Neutro | Tenso
resultado    Avançou | Mantido | Retrocedeu | Sem definição
status       valor único ou grupo (resolvido | aberto | declinado)
entidade     id ou nome exato da instituição
subtipo      tipo de investidor
tags         lista separada por vírgula (OR entre elas)
portaVoz     id
pessoa       id
q            busca livre (entidade, pessoa, pauta, uf, status, porta-voz, tags)
page, size, sort
```

## Interações

```
GET    /api/interacoes                 lista paginada + total do recorte
POST   /api/interacoes                 cria
GET    /api/interacoes/{id}            ficha completa (inclui comentários e campos narrativos)
PATCH  /api/interacoes/{id}            edita (com log)
DELETE /api/interacoes/{id}            arquiva (soft delete)
GET    /api/interacoes/export.csv      CSV do recorte (BOM, separador ";")
POST   /api/interacoes/{id}/comentarios
```

## Agregações (uma por bloco do painel)

```
GET /api/metricas/kpis                 { institucionais, imprensa: {total, atendidas, taxa},
                                         eventos, investidores: {total, internacionais},
                                         legislativo: {total, emTramitacao}, tier1: {total, pct} }
GET /api/metricas/serie-mensal?por=area|clima|tema&topN=5
GET /api/metricas/ranking?por=entidade|esfera|unidade|portaVoz|pessoa|uf|tag|status|subtipo&limit=8
GET /api/metricas/geo                  [{ uf, count }]
GET /api/metricas/status               { grupos: [...], porFrente: [...], fila: [...] }
GET /api/metricas/resultado            { itens: [...], taxaAvanco, porFrente: [...], semResultado }
GET /api/metricas/porta-vozes          exposição, concentração, aderência ao escopo
GET /api/metricas/interlocutores       lista + novos/sem-contato por janela
GET /api/metricas/comparativo?janela=semestre|trimestre|90d&entidade=portaVoz|pessoa
```

## Cadastros e dicionários

```
GET/POST/PATCH /api/porta-vozes         (cargo, temas autorizados, ativo)
GET/POST/PATCH /api/interlocutores      (cargo, tipo, temas de interesse, ativo)
GET/POST/PATCH /api/instituicoes
GET/POST/PATCH /api/temas               (nível estratégico | livre)
GET            /api/dicionarios         enums administráveis em uma chamada
GET/POST/PATCH /api/unidades-negocio
```

## Relatório

```
POST /api/relatorios                   { secoes: [...], filtros: {...} } → id
GET  /api/relatorios/{id}.pdf          PDF paginado (cabeçalho/rodapé Aegea, filtros impressos)
```

Seções disponíveis: `resumo`, `volumetria`, `status`, `resultado`, `rankings`, `interlocutores`, `pendencias`, `base`.

## Importação

```
POST /api/importacoes                  upload do .xlsx → job
GET  /api/importacoes/{id}             status + linhas com divergência para conferência
POST /api/importacoes/{id}/confirmar   aplica após revisão
```

## Autenticação (Microsoft Entra ID)

```
GET  /api/auth/login                inicia OIDC (authorization code + PKCE); ?redirect=/painel
GET  /api/auth/callback             troca o code, valida id_token, cria sessão, provisiona no 1º login (JIT)
POST /api/auth/logout               encerra sessão local + logout do IdP
GET  /api/auth/me                   { id, nome, email, perfil, unidadesPermitidas[], grupos[] }
POST /api/auth/refresh              renova a sessão
```

- Tenant restrito ao diretório da Aegea; MFA conforme política da companhia.
- `perfil` derivado de **claim de grupo / app role**, nunca de cadastro local.
- Sessão em cookie `httpOnly`, `Secure`, `SameSite=Lax`.
- Registrar todo login (usuário, timestamp, IP, resultado) para auditoria.
- Fallback e-mail/senha só se houver contas fora do diretório — decisão de produto pendente.

## Permissões

```
analista      cria; edita os próprios registros; lê tudo
coordenacao   edita tudo; administra dicionários e cadastros
diretoria     somente leitura das views de análise e do relatório
```

Auditoria: toda alteração em `interacao` registra autor, timestamp e diff dos campos (o campo de relato é sensível).
