# back-reputacional — API do Painel Reputacional Aegea

CRM dos Stakeholders: cadastro das interações institucionais da Aegea (imprensa,
governo, parceiros, eventos, investidores, legislativo e demandas internas) e os
painéis de análise sobre a mesma base.

Substitui a planilha `Demandas de Imprensa 2026.xlsx`, de 14 abas.

O frontend fica em repositório próprio e consome esta API.

## Subindo em 4 passos

```bash
# 1. banco
docker compose up -d                  # ou seu Postgres, aplicando app/banco/migrations em ordem

# 2. dependências
pip install -e ".[dev]"

# 3. configuração
cp .env.example .env                  # ajuste BANCO_URL

# 4. servidor
uvicorn main:app --reload             # ou `fastapi dev`
```

Documentação interativa em <http://localhost:8000/docs> — fora do ar em produção.

Com `AUTH_MOCK=true` (o padrão do `.env.example`) um usuário fixo é provisionado
pelo mesmo caminho do SSO real, para desenvolver sem depender do tenant.

```bash
python -m app.banco.semear_desenvolvimento   # 60 registros sintéticos
```

## Como o repositório é organizado

As pastas são **camadas**; os arquivos dentro delas levam o nome do **contexto de
negócio**. Quem procura "as rotas" abre `app/api/`; quem procura "interações"
acha `interacoes.py` em cada camada.

```
main.py                    o ponto de entrada — `uvicorn main:app`
app/
├── api/                   TODAS as rotas HTTP
│   ├── acesso.py            login, sessão, administração de acessos
│   ├── interacoes.py        CRUD do registro
│   ├── metricas.py          as agregações do painel
│   ├── relatorios.py        registro de geração e exportação
│   ├── stakeholders.py      diretórios
│   ├── catalogo.py          dicionários
│   ├── dependencias.py      quem está pedindo, e se pode
│   └── erros.py             exceção de domínio → resposta HTTP
├── esquemas/              o que entra e sai da API (Pydantic)
├── dominio/               entidades, regras e vocabulário. Sem SQL, sem FastAPI
├── casos_de_uso/          o que a aplicação faz, um arquivo por operação
├── banco/                 ORM, consultas, sessão e migrations
├── seguranca/             OIDC, cookie, CSRF, limite de taxa, cabeçalhos
├── configuracao.py        variáveis de ambiente, com os padrões
└── observabilidade.py     log estruturado e telemetria
tests/
```

A dependência corre em um sentido só: `api` conhece `casos_de_uso`, que conhece
`dominio`. **`dominio` não conhece ninguém** — é o que permite testá-lo sem
banco e sem HTTP.

Cada pacote tem um `__init__.py` com uma descrição do que mora ali. Comece por
`app/__init__.py`.

### Duas invariantes que sustentam o resto

**Os filtros são um objeto só.** `app/dominio/recorte.py` define `Recorte`, e
`app/banco/filtros_sql.condicoes()` é o **único** lugar que o traduz em SQL. É
isso que faz o número do KPI bater com o da tabela. Uma consulta nova que monte
`where` por conta própria quebra a garantia em silêncio.

**O padrão é não ver nada.** Papel, escopo e prazo vêm do banco e são aplicados
a cada requisição. Usuário sem papel não entra; usuário sem escopo não vê nada.
Ver [`docs/SEGURANCA.md`](docs/SEGURANCA.md).

## Banco

PostgreSQL **15 ou superior** — a razão do piso está em [Versão e
privilégio](#versão-e-privilégio). 37 tabelas: uma tabela-mãe `interacao` com os
campos comuns, mais cinco extensões 1-para-1 por frente.

As migrations ficam em `app/banco/migrations/` e rodam **em ordem alfabética**:

| # | Arquivo | O que cria |
|---|---|---|
| 0001 | `fundacao` | extensões, domínio `abrangencia`, 14 dicionários + carga |
| 0002 | `stakeholders` | instituição, interlocutor, pessoa da Aegea |
| 0003 | `acesso` | papel, usuário, escopo, trilha de login |
| 0004 | `interacoes` | a tabela-mãe, as extensões, os vínculos |
| 0005 | `auditoria` | trilhas e gatilhos |
| 0006 | `concessao_de_acesso` | a função `conceder_acesso` |
| 0007 | `relatorios` | registro de geração e exportação |
| 0008 | `importacao` | schema da importação (sem aplicação — ver abaixo) |
| 0009 | `papel_da_aplicacao` | os `grant` de `painel_app` |

> **0009 tem de rodar por último.** Os `grant on all tables` só alcançam o que já
> existe; migration nova que crie tabela precisa vir antes dela.

Cada objeto é criado **uma vez**, no estado final. Não há migration que corrija
outra.

### Versão e privilégio

Conferido no CI, aplicando as 9 migrations num banco limpo:

| | 15 | 16 | 17 | 18 |
|---|---|---|---|---|
| superusuário | ok | ok | ok | ok |
| conta comum com `CREATEROLE` | ok | ok | ok | ok |

**O piso é o Postgres 15, e a razão é de segurança.** Até o 14, o schema
`public` pertence a `postgres` e concede `CREATE` a `PUBLIC` por padrão. Uma
conta comum não consegue revogar isso — o Postgres emite *warning*, não erro —,
e as funções `security definer`, que usam `set search_path = public`, ficariam
sem a garantia de que dependem: qualquer role poderia plantar ali uma função com
nome de built-in.

A migration 0005 **recusa aplicar** nesse estado, com mensagem dizendo o que
fazer. Sem essa recusa, o banco terminava mais fraco do que a documentação
afirmava, em silêncio. O Postgres 13 está fora de suporte desde novembro de
2025.

A segunda linha é a que importa para o deploy: **no Postgres gerenciado do Azure
a conta administrativa não é superusuário**. As migrations criam três roles e
transferem posse de funções `security definer` para elas — o que exige ser
membro da role. 0005 e 0006 tratam isso, com sintaxe diferente até o 15 e do 16
em diante.

**Antes de aplicar em Azure Flexible Server:** as quatro extensões (`pgcrypto`,
`citext`, `unaccent`, `pg_trgm`) precisam estar liberadas no parâmetro de
servidor `azure.extensions`. `create extension` falha sem isso.

## API

A listagem de interações e as rotas de métricas recebem **os mesmos filtros**,
porque vêm da mesma dependência `obter_recorte`. As demais têm parâmetros
próprios.

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/api/saude` | healthcheck |
| `GET` | `/api/auth/login` | começa o fluxo OIDC |
| `GET` | `/api/auth/callback` | volta do provedor e cria a sessão |
| `POST` | `/api/auth/logout` | encerra a sessão |
| `GET` | `/api/eu` | quem sou, o que posso, e o token anti-CSRF |
| `GET` | `/api/interacoes` | lista paginada do recorte |
| `POST` | `/api/interacoes` | cria |
| `GET` | `/api/interacoes/{id}` | ficha do registro |
| `PATCH` | `/api/interacoes/{id}` | edita, revalidando o agregado |
| `DELETE` | `/api/interacoes/{id}` | arquiva (soft delete) |
| `GET` | `/api/metricas/kpis` | os números do topo do painel |
| `GET` | `/api/metricas/resolutividade` | taxa e composição por grupo de status |
| `GET` | `/api/metricas/serie-mensal` | volume por mês, segmentado |
| `GET` | `/api/metricas/mapa` | total por UF |
| `GET` | `/api/instituicoes` | diretório, com busca por semelhança |
| `GET` | `/api/interlocutores` | diretório |
| `GET` | `/api/pessoas-aegea` | diretório |
| `GET` | `/api/dicionarios` | todos os vocabulários numa chamada |
| `GET` | `/api/acessos` | administração de acessos |
| `GET` | `/api/acessos/papeis` | papéis disponíveis |
| `PUT` | `/api/acessos/{id}` | concede ou revoga |
| `GET` | `/api/acessos/{id}/historico` | trilha de concessão |
| `POST` | `/api/relatorios` | registra a geração de um relatório |
| `POST` | `/api/relatorios/exportacoes` | registra uma exportação CSV |
| `GET` | `/api/relatorios/historico` | o que já foi gerado |

`status` e `grupo` são parâmetros **separados**: `declinado` é ao mesmo tempo o
código de um status e o nome de um grupo — que também contém `cancelado`.

## Testes e qualidade

```bash
python -m pytest        # 366 testes; precisa do Postgres no ar
ruff check .            # linter, com as regras FastAPI (FAST); passa limpo
```

Os testes de banco usam uma base **própria** (`painel_reputacional_teste`),
criada e migrada pelo próprio módulo a cada execução.

### CI

`.github/workflows/ci.yml`, em push para `main` e em todo pull request:

| Etapa | O que faz |
|---|---|
| Lint | `ruff check` com as regras do `pyproject.toml`, FastAPI incluídas |
| Testes | a suíte em Python 3.12 **e** 3.13, contra Postgres 18 |
| Migrations | aplica as 9 num banco limpo, em **4 versões × 2 níveis de privilégio** |
| Imagem Docker | constrói, sobe contra um Postgres migrado e confere 7 rotas |

A matriz de migrations é a etapa que mais paga, e já provou isso duas vezes:
pegou a transferência de posse das funções `security definer` falhando sem
superusuário, e depois pegou o schema `public` ficando gravável por qualquer
role até o Postgres 14 — uma garantia que a documentação afirmava e o banco não
tinha. Cada combinação roda num contêiner próprio, porque roles no Postgres são
de cluster.

Para proteger o branch, aponte a regra para o check **`CI`** — ele agrega os
demais, então acrescentar uma versão de Postgres não exige mexer na
configuração do repositório.

| Arquivo | O que garante |
|---|---|
| `test_e2e_postgres.py` | ciclo completo contra o Postgres real |
| `test_papel_restrito.py` | conecta como `painel_app` — o único que exercita os `grant` de produção |
| `test_administrar_acessos.py` | concessão, versão otimista e concorrência real |
| `test_sessao_do_pedido.py` | commit que falha não vira resposta de sucesso |
| `test_verificacao_de_producao.py` | a API recusa subir com configuração insegura |
| `test_protecao_http.py` | CORS, CSRF, cabeçalhos, limite de corpo |
| `test_schema_bate_com_migration.py` | compara o ORM com o DDL, coluna por coluna |

## Configuração

Tudo em `app/configuracao.py`, lido de variável de ambiente. Ver `.env.example`,
que lista o que **bloqueia** a subida em produção e o que apenas **avisa**.

Se a API sobe com `AMBIENTE=producao`, nenhum bloqueio foi violado — mas vale ler
os avisos no log da subida.

## Docker

```bash
docker build -t back-reputacional .
```

A imagem roda como usuário não-root, com um worker (o limite de taxa guarda
estado em memória por processo) e **sem `--proxy-headers`** — quem decide o
endereço do cliente é `app/seguranca/limite_de_taxa.py`, lendo o
`X-Forwarded-For` da direita.

## O que não existe

Escrito explicitamente para quem for continuar.

- **Importação da planilha.** As tabelas existem (migration `0008`) e o desenho
  está documentado lá; não há rota nem caso de uso.
- **Administração de dicionários.** A API só lê (`GET /api/dicionarios`). O papel
  `administra_dicionarios` existe e não é exigido em lugar nenhum, porque não há
  escrita para exigir.
- **Gerador de documento no servidor.** O relatório sai da impressão do navegador
  e o CSV é montado no cliente. O que existe é o REGISTRO da geração — trilha,
  não barreira.
- **Verificação de tipos.** Não há `mypy` nem `ty` configurados. Ver
  [`docs/SEGURANCA.md`](docs/SEGURANCA.md).
- **Rate limit distribuído.** O estado é por processo. Com mais de uma instância,
  o teto real é N vezes o configurado; quem dá o teto de verdade é a borda.
