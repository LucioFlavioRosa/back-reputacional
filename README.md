# back-reputacional — API do Painel Reputacional Aegea

CRM dos Stakeholders: cadastro das interações institucionais da Aegea (imprensa,
governo, parceiros, eventos, investidores, legislativo e demandas internas) e os
painéis de análise sobre a mesma base.

Substitui a planilha `Demandas de Imprensa 2026.xlsx`, de 14 abas.

O frontend fica em repositório próprio e consome esta API.

## Rodando a pilha inteira, com Docker

Para **rodar o produto** — front, API, Postgres e o emulador de Blob — sem
instalar Python nem Node. Clone os dois repositórios lado a lado:

```bash
git clone https://github.com/LucioFlavioRosa/back-reputacional
git clone https://github.com/LucioFlavioRosa/front-reputacional
cd back-reputacional

docker compose -f docker-compose.pilha.yml up -d --build

docker compose -f docker-compose.pilha.yml exec api python -m app.banco.semear_desenvolvimento
docker compose -f docker-compose.pilha.yml exec api python -m app.banco.semear_referencias
docker compose -f docker-compose.pilha.yml exec api python -m app.banco.semear_enredos
```

Abra <http://localhost:8081>. O primeiro semeador imprime as oito contas e a
senha — uma por papel, todas com a mesma senha, que o código chama de
`SENHA_DE_DESENVOLVIMENTO` justamente porque **não é segredo e não pretende
ser**. Ela existe para o SSO ficar desligado enquanto ninguém tem o tenant.
Antes de qualquer ambiente compartilhado, ela morre.

**Não há dump do banco, e é de propósito.** As migrations e os semeadores são
versionados; um dump não é. Ele envelhece na primeira migration nova, e carrega
o lixo de quem o gerou — a base de quem desenvolve acumula teste de revisão,
upload repetido e conta descartável. Quem sobe daqui recebe a mesma base que
todo mundo: 99 instituições, 233 agendas e 67 referências com arquivo de
verdade no blob.

Se alguma porta estiver ocupada, troque no ambiente e reconstrua:

```bash
PORTA_WEB=8082 PORTA_API=8002 PORTA_BANCO=5434 PORTA_BLOB=10002   docker compose -p painel-outro -f docker-compose.pilha.yml up -d --build
```

O `--build` não é opcional aí: o endereço da API entra no bundle do front na
compilação, e também na CSP do nginx. Trocar a porta sem reconstruir deixa a
tela vazia sem erro nenhum no servidor.

Para derrubar tudo, inclusive o banco e os arquivos:

```bash
docker compose -f docker-compose.pilha.yml down -v
```

## Desenvolvendo a API sozinha, em 4 passos



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
│   ├── exportacoes.py      trilha de quem exportou a Base
│   ├── materiais.py        os documentos com arquivo, por recorte
│   ├── referencias.py      a biblioteca do SharePoint, por assunto
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

**O padrão é não ver nada.** Papel, escopo e prazo vêm do banco — nunca do
cookie — e são aplicados a toda requisição. Usuário sem papel não entra; usuário
sem escopo não vê nada. A leitura é cacheada por cinco minutos
(`AUTORIZACAO_CACHE_SEGUNDOS`), com duas exceções que o cache não cega: o prazo
de acesso vale na hora exata, e a revogação feita pela tela vale no ato. Ver
[`docs/SEGURANCA.md`](docs/SEGURANCA.md).

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
| 0007 | `relatorios` | registro de geração e exportação (a tabela virou `exportacao` na 0025) |
| 0008 | `importacao` | schema da importação (sem aplicação — ver abaixo) |
| 0009 | `papel_da_aplicacao` | os `grant` de `painel_app` |

> **A 0009 concede em massa, e só alcança o que já existia.** Uma migration
> posterior que crie tabela nasce SEM os `grant` de `painel_app` para `delete` —
> os de `select`, `insert` e `update` vêm do `alter default privileges`. Foi o
> que aconteceu com `referencia_tema` (0026) e `material_tema` (0027): as duas
> precisaram de `grant delete` explícito, e sem ele a edição falharia só na hora
> de salvar, com erro de permissão.
>
> A tabela acima para na 0009 e o diretório vai até a 0027; a lista não foi
> mantida. Quem precisar do histórico completo lê os arquivos, que são
> autoexplicativos por convenção.

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

**Antes de aplicar em Azure Flexible Server:** as três extensões (`pgcrypto`,
`citext`, `pg_trgm`) precisam estar liberadas no parâmetro de servidor
`azure.extensions`. `create extension` falha sem isso.

### Índices seguem a consulta, não a estrutura

A regra do repositório: **um índice existe porque uma consulta o usa** — do
painel ou operacional, mas escrita em algum lugar. Índice para consulta que
"algum dia pode aparecer" não entra; entra o comentário dizendo qual criar e com
que operador, no arquivo da tabela.

Existe índice onde o filtro é seletivo: `instituicao_id`, `interlocutor_id`,
`unidade_negocio_id` e `criado_por` em `interacao`; parciais em `status_id` e
`uf` (`where arquivado_em is null`, porque o painel nunca conta arquivado);
composto em `(frente_id, data_interacao desc)`; e trigrama (`pg_trgm`) em
`pauta`, `relato` e `encaminhamentos`, para a busca livre com `ILIKE '%termo%'`.

**Dezoito chaves estrangeiras NÃO têm índice, e é decisão.** O Postgres não cria
nenhum sozinho, então cada um seria escolha explícita. Dois motivos, e vale
saber qual se aplica antes de acrescentar o próximo:

1. **Seletividade baixa demais.** `esfera_id`, `clima_id` e `resultado_id`
   aparecem no `WHERE` de `app/banco/filtros_sql.py` — não é que ninguém
   consulte. É que os dicionários têm 6, 3 e 4 linhas: um índice sobre três
   valores distintos não ganha da varredura sequencial, e o planejador não o
   usaria. O mesmo vale para `iniciativa` (2), `casa` (5), `tema` (17) e
   `formato` (17).

2. **A verificação de integridade nunca roda.** O outro motivo clássico para
   indexar uma FK é o `DELETE` no lado referenciado, que sem índice varre a
   tabela filha. Aqui não acontece: os dicionários não são apagados, e
   `interacao` é arquivada (`arquivado_em`), nunca removida — ver a rota
   `DELETE /api/interacoes/{id}`, que é *soft delete*.

**Quatro dessas dezoito apontam para tabelas que CRESCEM, não para dicionário**,
e são as que merecem atenção quando o volume subir:

| Coluna | Aponta para | Por que ainda não tem índice |
|---|---|---|
| `interacao.stakeholder_id` | `stakeholder` | só é lida e gravada; nada filtra por ela |
| `importacao_linha.interacao_id` | `interacao` | idem |
| `exportacao.criado_por` | `usuario` | a trilha ordena por `criado_em`, não por autor |
| `importacao.criado_por` | `usuario` | idem |

No dia em que aparecer uma visão "por stakeholder" ou "o que fulano exportou",
esses são os primeiros índices a criar.

**Duas exceções à regra, e as duas estão comentadas no SQL.** A primeira é
`acesso_log.usuario_id`: nenhuma rota o consulta, e ele existe assim mesmo. O motivo está escrito em `0003_acesso.sql`, junto com
a consulta operacional que ele serve — `acesso_log` é a única tabela sem teto de
crescimento, e uma varredura sequencial nela durante uma investigação seria cara
justamente na hora errada.

A segunda são os dois GIN de `importacao_linha`, em `0008_importacao.sql`. Ali a
tabela inteira é rascunho — a importação da planilha não foi implementada, e o
arquivo diz isso no cabeçalho. Os índices fazem parte do desenho e caem junto se
o desenho cair.

Antes de acrescentar qualquer índice, meça: `explain (analyze, buffers)` sobre a
consulta real.

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
| `POST` | `/api/exportacoes` | registra uma exportação CSV da Base |
| `GET` | `/api/exportacoes/historico` | quem exportou o quê |
| `GET` | `/api/materiais` | os documentos com arquivo, no recorte |
| `GET` | `/api/referencias` | a biblioteca do SharePoint |
| `POST` | `/api/referencias` | cadastra uma referência |
| `PUT` | `/api/referencias/{id}` | edita uma referência |

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
- **Gerador de documento no servidor.** O CSV é montado no cliente, a partir da
  listagem já baixada. O que existe é o REGISTRO da exportação — trilha, não
  barreira. (A tela de relatório foi removida do produto na 0025; a trilha
  ficou, porque é controle de segurança e não relatório.)
- **Verificação de tipos.** Não há `mypy` nem `ty` configurados. Ver
  [`docs/SEGURANCA.md`](docs/SEGURANCA.md).
- **Rate limit distribuído.** O estado é por processo. Com mais de uma instância,
  o teto real é N vezes o configurado; quem dá o teto de verdade é a borda.
