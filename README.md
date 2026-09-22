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

O terceiro semeador termina derivando o que o acervo não trouxe — relevância
da instituição (moda das agendas dela), categoria de público (o sugeridor,
só em confiança alta) e formato da interação (pela frente) — as mesmas
regras das migrations `0043`/`0044`, em `app/banco/derivados.py`. Num banco
que já existe, as migrations fazem isso sozinhas; a categoria continua
sendo `python -m app.banco.sugerir_categoria_de_publico --aplicar`.

Abra <http://localhost:8081>. O primeiro semeador imprime as oito contas e a
senha — uma por papel, todas com a mesma senha, que o código chama de
`SENHA_DE_DESENVOLVIMENTO` justamente porque **não é segredo e não pretende
ser**. Ela existe para o SSO ficar desligado enquanto ninguém tem o tenant.
Antes de qualquer ambiente compartilhado, ela morre.

**Não há dump do banco, e é de propósito.** As migrations e os semeadores são
versionados; um dump não é. Ele envelhece na primeira migration nova, e carrega
o lixo de quem o gerou — a base de quem desenvolve acumula teste de revisão,
upload repetido e conta descartável. Quem sobe daqui recebe a mesma base que
todo mundo: 99 instituições, 293 agendas — 233 dos enredos de demonstração e
60 da amostra de handoff — e 67 referências com arquivo de verdade no blob.

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
│   ├── referencias.py      a biblioteca de referências, com versões
│   ├── stakeholders.py      diretórios
│   ├── catalogo.py          dicionários
│   ├── dependencias.py      quem está pedindo, e se pode
│   └── erros.py             exceção de domínio → resposta HTTP
├── esquemas/              o que entra e sai da API (Pydantic)
├── dominio/               entidades, regras e vocabulário. Sem SQL, sem FastAPI
├── casos_de_uso/          o que a aplicação faz, um arquivo por operação
├── banco/                 ORM, consultas, sessão e migrations
├── armazenamento/         o Blob: caminho, upload e download dos arquivos
│                          três árvores, e cada uma responde a uma pergunta:
│                          `interacoes/<id>/<momento>/` — o material da agenda,
│                          achado pelo registro; `referencias/<assunto>/<tipo>/`
│                          — a biblioteca, achada pelo assunto; e
│                          `consultas/<aaaa-mm>/<instituicao>/<dia>-<id>/` — o
│                          anexo do e-mail recebido, achado pelo contêiner
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
privilégio](#versão-e-privilégio). 57 tabelas, organizadas em sete assuntos:

| Assunto | Tabelas principais |
|---|---|
| dicionários | `frente`, `status`, `tema`, `esfera`, `clima`, `resultado`, `formato`, `formato_interacao`, `area_pessoa`, `categoria_publico`, `subcategoria_publico`, … |
| stakeholders | `instituicao`, `interlocutor`, `pessoa_aegea` |
| acesso | `papel`, `usuario`, `escopo`, `acesso_log`, trilha de concessão |
| agendas | `interacao` (tabela-mãe) + cinco extensões 1-para-1 por frente, `interacao_consulta` (1-para-1 pelo TIPO), `interacao_interlocutor`, `interacao_origem`, `interacao_area`, `participacao_aegea`, `material` |
| biblioteca | `referencia`, `referencia_versao`, `referencia_tema`, `arquivo` |
| sinais | `alegacao`, `alegacao_tema`, `interacao_alegacao`, `apuracao`, `canal_consulta` |
| trilhas | `auditoria`, `exportacao`, `importacao` (schema sem aplicação) |

As 45 migrations (`0001` a `0046`; a `0019` não existe) ficam em
`app/banco/migrations/` e rodam **em ordem alfabética**, uma vez, na primeira
subida do banco. Cada arquivo abre com um
cabeçalho dizendo o que muda e por quê — é lá que está o histórico, e não aqui.

Cada objeto é criado **uma vez**, no estado final. Não há migration que corrija
outra.

> **Migration nova precisa conceder `delete` a `painel_app`.** A 0009 concede em
> massa e só alcança o que já existia; `select`, `insert` e `update` vêm depois
> pelo `alter default privileges`, mas `delete` não. Sem o `grant` explícito, a
> edição falha só na hora de salvar, com erro de permissão.

### O que o vocabulário ganhou em setembro de 2026

- **Oito frentes.** `bancos_credores` (Bancos/Credores) entrou pela `0031` e
  usa a extensão `interacao_institucional`, a mesma de Governo, Parceiros e
  Eventos — o mapa é `EXTENSAO_POR_FRENTE`, em `app/dominio/frentes.py`.
- **Clima é Proativo / Reativo** (`0030`). Os códigos `propositivo` e `tenso`
  continuam no banco; só o nome exibido mudou.
- **Área interna da agenda.** `area_pessoa` é a área da Aegea (Comunicação,
  Relações Institucionais, Operações Financeiras, Relações com Investidores;
  "Performance e Dados" está com `ativo = false` desde a `0033`), e
  `interacao_area` liga cada agenda a uma ou mais áreas (`0032`; o `delete`
  para `painel_app` e o gatilho de auditoria vieram só na `0041`). O filtro é
  `areas=1,2` — ids separados por vírgula, OR entre eles.
- **Taxonomia de públicos** (`0036`). Dez categorias, cada uma com seu
  `padrao_de_quebra` (esfera, lógica de relação, posição de capital, lógica
  editorial ou nenhuma) e a área dona daquele público; vinte subcategorias.
  **Mora em `instituicao`** (`categoria_publico_id`, `subcategoria_publico_id`),
  não em `interacao`: é atributo do órgão, não da reunião. `natureza_orgao`
  segue no banco e na API enquanto o backfill não termina —
  `python -m app.banco.sugerir_categoria_de_publico` sugere, sem gravar, a
  categoria de cada instituição já cadastrada.
- **Conteúdo por versão** na biblioteca (`0034`): o resumo acompanha a versão
  da referência e é obrigatório na criação; o arquivo passou a ser opcional.
- **Formato da interação** (`0038`): Mídia, Evento, Reunião, Visita,
  Manifestação formal… — responde "que tipo de encontro foi", uma pergunta
  ortogonal à da frente ("quem é a contraparte"). `formato_interacao_id` em
  `interacao`; o filtro "Tipo de Interação" do Painel usa ele, não a frente.
- **A Frente deixou de ser perguntada.** Quem registra escolhe o formato e a
  instituição, e `derivar_frente` (`app/casos_de_uso/derivar_frente.py`) deduz
  a frente do tipo da instituição. A tentativa de guardar uma frente padrão
  por categoria de público (`0039`) foi desfeita na `0040`: o tipo da
  instituição já bastava.

### Versão e privilégio

Conferido no CI, aplicando as migrations num banco limpo:

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

O período aceita duas formas: `de`/`ate` (datas ISO) ou um atalho em `periodo`
— `ultimos-30|60|90|180|360` e `proximos-30|60|90|180|360`, a mesma escala para
trás e para a frente (`app/dominio/periodo.py`). O front resolve os atalhos do
lado dele e manda só `de`/`ate`, o que permite combinar passado e futuro num
intervalo único. Os demais filtros: `frente`, `unidade`, `uf`, `esfera`,
`tier`, `clima`, `resultado`, `status`, `grupo`, `entidade`, `subtipo`,
`portaVoz`, `pessoa`, `tags`, `areas` e `q` (busca livre).

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/api/saude` | healthcheck |
| `GET` | `/api/auth/login` | começa o fluxo OIDC |
| `GET` | `/api/auth/callback` | volta do provedor e cria a sessão |
| `POST` | `/api/auth/senha` | entra por e-mail e senha (só com o SSO desligado) |
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
| `GET`, `POST` | `/api/instituicoes` | diretório, com busca por semelhança |
| `PUT` | `/api/instituicoes/{id}` | edita, inclusive a relevância |
| `GET`, `POST` | `/api/interlocutores` | diretório |
| `PUT`, `DELETE` | `/api/interlocutores/{id}` | edita e remove |
| `GET`, `POST` | `/api/pessoas-aegea` | diretório |
| `PUT` | `/api/pessoas-aegea/{id}` | edita |
| `GET` | `/api/pessoas-aegea/{id}/temas` | de que assuntos a pessoa fala |
| `GET`, `POST` | `/api/temas` | os assuntos, com nível |
| `PUT` | `/api/temas/{id}` | edita |
| `GET` | `/api/dicionarios` | todos os vocabulários numa chamada |
| `GET` | `/api/acessos` | administração de acessos |
| `GET` | `/api/acessos/papeis` | papéis disponíveis |
| `PUT` | `/api/acessos/{id}` | concede ou revoga |
| `PATCH` | `/api/acessos/{id}/situacao` | ativa ou desativa a conta |
| `GET` | `/api/acessos/{id}/historico` | trilha de concessão |
| `POST` | `/api/exportacoes` | registra uma exportação CSV da Base |
| `GET` | `/api/exportacoes/historico` | quem exportou o quê |
| `GET` | `/api/materiais` | os documentos que saíram das reuniões, no recorte |
| `POST` | `/api/interacoes/{id}/materiais/arquivo` | sobe um arquivo para a agenda |
| `GET` | `/api/interacoes/{id}/materiais/arquivo/{arquivo_id}` | baixa (pela API, nunca por link direto) |
| `GET`, `POST` | `/api/referencias` | a biblioteca de referências |
| `PUT` | `/api/referencias/{id}` | edita os metadados |
| `GET`, `POST` | `/api/referencias/{id}/versoes` | histórico e nova versão |
| `GET` | `/api/referencias/{id}/versoes/{versao_id}/arquivo` | baixa aquela versão |

`status` e `grupo` são parâmetros **separados**: `declinado` é ao mesmo tempo o
código de um status e o nome de um grupo.

**Três situações ativas** — `solicitado`, `confirmada` (Aceito) e `declinado`
(Negado). O dicionário guarda outros oito códigos com `ativo = false`, porque
registros antigos apontam para eles; a coluna `ativo` é o que separa o que se
oferece do que só se lê.

## Testes e qualidade

```bash
python -m pytest        # 709 testes; precisa do Postgres no ar
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
| Migrations | aplica todas num banco limpo, em **4 versões × 2 níveis de privilégio** |
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
| `test_semeadores.py` | os três semeadores do README, na ordem, contra o banco de teste — o caminho de quem clona |

## As versões são travadas

`pyproject.toml` declara **faixas** — o que a aplicação aceita.
`requirements.txt` declara **versões exatas com hash** — o que ela roda. **A
imagem e o CI instalam do segundo**, e é por isso que o que se testa é o que se
publica.

O LOCK É DE LINUX, e do par de Pythons que a aplicação suporta (3.12 e 3.13).
Ele traz `uvloop`, que não existe para Windows, e rodas que não existem para
3.14. Quem desenvolve fora disso instala pelas faixas — `pip install -e
".[dev]"`, como nos 4 passos acima — sabendo que as versões da sua máquina
podem não ser as de produção. Quem decide é o CI, que roda nas duas versões
travadas.

Os dois arquivos são gerados, e o comando é este:

```bash
docker run --rm -v "$PWD:/repo" -w /repo python:3.12-slim bash -c "
  pip install -q pip-tools
  pip-compile --generate-hashes -o requirements.txt pyproject.toml
  pip-compile --generate-hashes --extra dev -o requirements-dev.txt pyproject.toml"
```

**No 3.12, que é o piso** — e não no 3.13 da imagem: resolver na versão mais
baixa produz um lock que serve às duas, e o contrário quebra no piso
declarado. Em contêiner Linux, que é onde a imagem roda.

Atualizar dependência é rodar isso, ler o diff e commitar — que é justamente o
ponto: a atualização vira uma mudança revisada, e não um efeito colateral do
dia em que alguém reconstruiu a imagem.

## Publicar no Azure

O caminho inteiro — o que a aplicação espera do ambiente, o que ainda precisa
ser decidido na infraestrutura, a ordem dos comandos e os dois passos manuais —
está em [`docs/DEPLOY.md`](docs/DEPLOY.md).

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
- **Ingestão automática de e-mail.** A consulta recebida (`0046`) é
  REGISTRADA À MÃO: quem recebe o questionário cadastra a interação e a
  alegação que ela traz. Encaminhar para uma caixa e o sistema se registrar
  sozinho — com a alegação sugerida — é a fase seguinte, e exige e-mail de
  entrada no Azure.
- **Administração dos dicionários fechados.** Frente, status, clima, resultado e
  formato só se leem (`GET /api/dicionarios`); mudar um valor é SQL. O que TEM
  tela e rota é o cadastro de assuntos, instituições, interlocutores e pessoas
  da Aegea — e escrever neles exige o papel `administra_dicionarios`.
- **Gerador de documento no servidor.** O CSV é montado no cliente, a partir da
  listagem já baixada. O que existe é o REGISTRO da exportação — trilha, não
  barreira: não há tela de relatório, e a exportação é um controle de
  segurança.
- **Verificação de tipos.** Não há `mypy` nem `ty` configurados. Ver
  [`docs/SEGURANCA.md`](docs/SEGURANCA.md).
- **Rate limit distribuído.** O estado é por processo. Com mais de uma instância,
  o teto real é N vezes o configurado; quem dá o teto de verdade é a borda.
