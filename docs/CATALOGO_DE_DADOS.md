# Catálogo de dados — Painel Reputacional Aegea

> Gerado a partir das migrations em [`app/banco/migrations/`](../app/banco/migrations/), lidas em ordem alfabética — a mesma ordem em que o Postgres as aplica. Cada tabela aparece na migration que a **criou**; alterações posteriores de schema (`alter table ... add column`) estão marcadas onde ocorrem, na tabela original.
>
> "Obrigatória" significa `not null` no banco — inclui colunas de chave primária, que são implicitamente `not null` mesmo quando a migration não escreve a palavra (o Postgres impõe isso pela própria natureza da chave).
>
> O catálogo descreve o **estado atual** do schema: coluna criada e depois removida não aparece (fica registrada em nota de rodapé), e `check` alterado aparece só na versão que vale hoje.
>
> 57 tabelas ao todo, em 45 arquivos de migration (`0001` a `0046`, sem o número `0019`, que nunca existiu). As migrations que só alteram schema existente, só populam dicionário ou só criam função/grant/trigger (sem `create table` novo) não aparecem como seções próprias — aparecem como nota na tabela que alteraram. São elas: **0006** (`conceder_acesso`), **0009** (papel `painel_app`), **0010** (cadeado do último administrador), **0013**, **0014**, **0015**, **0016**, **0018**, **0020**, **0021**, **0022**, **0023**, **0024**, **0025**, **0030**, **0031**, **0033**, **0034**, **0035**, **0037**, **0039**, **0040**, **0041**, **0042**, **0043**, **0044** e **0045**.

## Sumário

| Migration | Domínio | Tabelas criadas |
|---|---|---|
| [0001](#0001--fundação) | Fundação: extensões, domínio geográfico, dicionários | 15 |
| [0002](#0002--stakeholders) | Diretório de contrapartes | 5 |
| [0003](#0003--acesso) | Autorização | 4 |
| [0004](#0004--interações) | O núcleo: interações e extensões por frente | 9 |
| [0005](#0005--auditoria) | Trilha de auditoria | 2 |
| [0007](#0007--exportações) | Registro de quem levou dados daqui | 1 |
| [0008](#0008--importação-schema-sem-aplicação) | Importação da planilha (schema sem aplicação) | 2 |
| [0011](#0011--ciclo-da-agenda) | Participantes reais e materiais da agenda | 2 |
| [0012](#0012--arquivo-do-material) | O arquivo no Blob Storage | 1 |
| [0017](#0017--a-agenda-vem-de-várias) | Encadeamento N-N entre agendas | 1 |
| [0026](#0026--biblioteca-de-referências) | Acervo de referências por assunto | 2 |
| [0027](#0027--assunto-do-material) | Assunto do material da agenda | 1 |
| [0028](#0028--referência-com-versões) | Versões de uma referência | 1 |
| [0029](#0029--área-do-representante) | Dicionário de áreas da Aegea | 1 |
| [0032](#0032--área-da-interação) | Quais áreas participam de uma interação | 1 |
| [0036](#0036--categoria-de-público) | Taxonomia de públicos | 2 |
| [0038](#0038--formato-da-interação) | Que tipo de encontro foi | 1 |
| [0046](#0046--consulta-recebida-e-alegação) | Consultas recebidas e o que elas dão como fato | 6 |

---

## Domínios (não são tabelas, mas sustentam colunas abaixo)

### `abrangencia` — criado em 0001

Domínio de texto com `check` embutido. Usado nas colunas `instituicao.uf` e `interacao.uf`.

Valores aceitos: as 27 siglas de UF (`AC`, `AL`, `AP`, `AM`, `BA`, `CE`, `DF`, `ES`, `GO`, `MA`, `MT`, `MS`, `MG`, `PA`, `PB`, `PR`, `PE`, `PI`, `RJ`, `RN`, `RS`, `RO`, `RR`, `SC`, `SP`, `SE`, `TO`) mais `NA` (nacional) e `IN` (internacional). Nenhuma migration posterior alterou o domínio — a lista é a mesma desde a fundação.

---

## 0001 — Fundação

Primeiro arquivo do schema; cria o que todo o resto referencia. Instala `pgcrypto`, `citext` e `pg_trgm` (deliberadamente **sem** `unaccent`: a normalização de nome roda em Python, em `app/dominio/texto.py`, e a mesma regra precisa valer na carga e na busca).

Os dicionários são tabelas, e não `enum`: acrescentar um valor é um `insert`, e não uma migration com deploy. Todos seguem a mesma forma — `id`, `codigo` (chave natural estável, usada pela API), `nome` (o que a pessoa lê), `ordem` e `ativo`. Desativar preserva os registros históricos que apontam para o valor.

### `frente`

As frentes de relacionamento — a dimensão que divide o painel inteiro.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único; é o que o front e `app/dominio/frentes.py` usam para reconhecer a frente |
| `nome` | `text` | Sim | o rótulo da tela (alterado em 0031: `governo` passa a "Entidades" e `legislativo` a "Agentes Públicos" — só o nome, o código fica) |
| `cor_hex` | `char(7)` | Sim | mora aqui e não no CSS porque é a mesma cor no painel, no gráfico e no chip da lista — trocá-la é decisão de marca |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> São oito frentes: `imprensa`, `governo`, `parceiros`, `eventos`, `investidores`, `legislativo`, `interna` (0001) e `bancos_credores` (**acrescentada em 0031**, para a relação de crédito/dívida, que não é mercado de capitais). A 0045 atualizou `cor_hex` de `investidores`, `interna` e `bancos_credores` para o padrão Aegea do front — o front é a fonte da verdade das cores, e o dicionário guardava valores antigos.

### `status`

A situação da agenda. `grupo` é o que sustenta a taxa de resolutividade do painel — sem ele, cada tela decidiria por conta própria o que conta como resolvido.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | (alterado em 0018: `confirmada` passa a "Aceito" e `declinado` a "Negado") |
| `grupo` | `text` | Sim | `check (grupo in ('resolvido','aberto','declinado'))` (alterado em 0021: `confirmada` passa de `aberto` para `resolvido` — sem isso nenhum registro visível ficava em `resolvido` e as métricas davam zero) |
| `ordem` | `smallint` | Sim | a ordem do CICLO, e não a de cadastro |
| `ativo` | `boolean` | Sim | `default true` |

> A 0011 acrescentou `confirmada` e a 0013 acrescentou `solicitado` (com `ordem` 0, o único valor livre antes do primeiro). A 0020 colapsou os onze códigos em três — Solicitado, Aceito, Negado — remapeando os registros e marcando os outros oito como `ativo = false`: apagá-los quebraria a chave estrangeira dos registros históricos em `interacao_auditoria`, e um código inativo continua tendo rótulo para quem for ler a trilha.

### `esfera`

Esfera geográfica/administrativa da contraparte.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `clima`

O clima da conversa.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | (alterado em 0030: `propositivo` passa a "Proativo" e `tenso` a "Reativo" — só o rótulo; o código é o que as cores, agregações e regras de exceção usam) |
| `cor_hex` | `char(7)` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `resultado`

O que a interação produziu: avançou, manteve, recuou, sem definição.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `cor_hex` | `char(7)` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `relevancia`

Relevância da contraparte, o que o painel chama de "tier".

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallint` | Sim | chave primária, `check (id > 0)`; é o PRÓPRIO número do tier, e não uma sequência — `interacao.tier` guarda 1, 2, 3… e é esse número que aparece na tela |
| `nome` | `text` | Sim | editável por `update`: trocar "Tier 4" por "Regional" muda a tela sem tocar em código |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> Não tem `codigo`: a chave natural é o próprio `id`.

### `iniciativa`

Quem pediu a agenda.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único; `provocada` = a Aegea pediu, `procurada` = a Aegea foi procurada |
| `nome` | `text` | Sim | (alterado em 0011: rótulos passam a "Pedida pela Aegea" e "Pedida por terceiro" — o nome anterior era ambíguo, e é deste campo que sai o indicador "a Aegea está sendo ativa?") |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `formato`

Formato da interação nas frentes de imprensa e investidores.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `escopo` | `text` | Sim | `check (escopo in ('imprensa','investidores','geral'))`; limita quais formatos aparecem em cada frente — "Roadshow" não faz sentido numa interação de imprensa |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> Não confundir com `formato_interacao` (0038), que responde outra pergunta: "que tipo de encontro foi esse".

### `natureza_orgao`

Natureza do órgão da contraparte institucional.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `casa`

Casa legislativa.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `tramitacao`

Fase da proposição legislativa.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `tipo_investidor`

Tipo da contraparte financeira.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `stakeholder`

Natureza da contraparte, independente da frente.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `unidade_negocio`

As empresas da holding.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `nome` | `text` | Sim | único; é a chave natural — não há código curto, e inventar um só para uniformizar criaria um vocabulário que ninguém usa |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> É por `nome` que `usuario_escopo.valor` referencia esta tabela, justamente porque não há `codigo`.

### `tema`

Os assuntos, com nível de classificação.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `serial` | Sim | chave primária |
| `nome` | `text` | Sim | único |
| `nivel` | `text` | Sim | `check (nivel in ('sensivel','estrategico','gerais'))`, `default 'gerais'` (alterado em 0022: eram dois valores — `estrategico` e `livre` —, e `livre` virou `gerais` no código, não só no rótulo; `sensivel` é o assunto que exige alinhamento prévio sobre quem fala) |
| `ativo` | `boolean` | Sim | `default true` |
| `criado_em` | `timestamptz` | Sim | `default now()` |

---

## 0002 — Stakeholders

Quem está do outro lado, e quem está do nosso. Há um diretório com chave própria, e não texto livre na interação, porque é ele que permite responder "quantas vezes falamos com a Folha este ano" — a pergunta que o painel existe para responder.

`nome_normalizado` guarda o nome sem acento e em minúsculas; é ele que carrega a restrição de unicidade e o índice de semelhança (`pg_trgm`). O `nome` original fica intacto para exibição, e quem preenche os dois é a aplicação.

### `instituicao`

O veículo, o órgão, a entidade, o fundo, a proposição.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `nome` | `text` | Sim | a forma curta, que é como se fala |
| `nome_normalizado` | `text` | Sim | único junto com `tipo`: "Águas do Rio" existe como `area_interna` e pode existir como `orgao` numa proposição |
| `tipo` | `text` | Sim | `check (tipo in ('veiculo','orgao','entidade','escritorio','investidor','proposicao','area_interna','credor'))`; decide em quais frentes a instituição aparece na busca (alterado em 0031: acrescenta `credor`, para bancos e credores — a relação é de crédito/dívida, não de mercado de capitais) |
| `esfera_id` | `smallint` | Não | `references esfera(id)` |
| `uf` | `abrangencia` | Não | |
| `ativo` | `boolean` | Sim | `default true` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `nome_completo` | `text` | Não | **adicionada em 0014** — o nome por extenso; sem ele uma lista de siglas vira adivinhação. Nulo no que veio da planilha |
| `tier` | `smallint` | Não | **adicionada em 0023** — `references relevancia(id)`; a relevância é atributo de quem está do outro lado, e não do encontro. Não confundir com `interacao.tier` |
| `categoria_publico_id` | `smallint` | Não | **adicionada em 0036** — `references categoria_publico(id)`; a taxonomia de públicos |
| `subcategoria_publico_id` | `smallint` | Não | **adicionada em 0036** — `references subcategoria_publico(id)`; nula sempre que a categoria for `sem_quebra` |

> A 0014 removeu uma coluna `descricao` criada minutos antes, por leitura errada do pedido: "descrição" e "nome completo" não são a mesma coisa. A 0024 e a 0043 preencheram `tier` onde estava nulo, pela moda dos tiers das agendas de cada instituição (empate resolvido pelo tier mais alto) — só onde estava nulo, porque decisão de gente vence estatística. A 0042 concedeu `delete` desta tabela a `painel_app`, para o que entrou por engano.

### `interlocutor`

A pessoa daquela instituição.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `nome` | `text` | Sim | |
| `nome_normalizado` | `text` | Sim | único junto com `instituicao_id`: mesmo nome em instituições diferentes são pessoas diferentes |
| `instituicao_id` | `uuid` | Não | `references instituicao(id)`; nulo porque existe interlocutor sem vínculo estável — um freelancer, um consultor. Forçar o vínculo obrigaria a inventar uma instituição falsa |
| `cargo` | `text` | Não | |
| `tipo` | `text` | Não | `check (tipo in ('jornalista','gestor_publico','parlamentar','analista_investidor','executivo_entidade','representante_entidade','outro'))` |
| `ativo` | `boolean` | Sim | `default true` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `email` | `text` | Não | **adicionada em 0014** — marcar uma agenda começa por escrever para alguém, e esse endereço vivia fora do sistema. Nulo no que veio da planilha |

> A 0042 concedeu `delete` desta tabela a `painel_app`: a rota existia e devolvia "permission denied" em produção, porque as `alter default privileges` da 0009 dão select/insert/update, nunca delete.

### `pessoa_aegea`

Quem da Aegea participou.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `nome` | `text` | Sim | |
| `nome_normalizado` | `text` | Sim | único |
| `cargo` | `text` | Não | |
| `eh_porta_voz` | `boolean` | Sim | `default false`; separa quem FALA em nome da companhia de quem só estava na sala — sem esta marca a tela de porta-vozes contaria os dois |
| `ativo` | `boolean` | Sim | `default true` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `email` | `text` | Não | **adicionada em 0016** — como se aciona a pessoa da casa. Nulo no que veio da planilha |
| `area_id` | `smallint` | Não | **adicionada em 0029** — `references area_pessoa(id)`; de onde essa pessoa fala. Nula em quem foi cadastrado antes da coluna existir |

### `interlocutor_tema`

Sobre o que esta pessoa costuma falar — usado ao preparar uma conversa. Independente dos temas de cada interação: alguém pode ser referência em tarifa e nunca ter tratado do assunto conosco.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interlocutor_id` | `uuid` | Sim | `references interlocutor(id) on delete cascade`; parte da chave primária |
| `tema_id` | `int` | Sim | `references tema(id)`; parte da chave primária |

### `pessoa_aegea_tema`

O mesmo, do lado da Aegea.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `pessoa_aegea_id` | `uuid` | Sim | `references pessoa_aegea(id) on delete cascade`; parte da chave primária |
| `tema_id` | `int` | Sim | `references tema(id)`; parte da chave primária |

---

## 0003 — Acesso

Quem entra, o que pode, sobre quais registros, e até quando. A autorização é composta por três coisas independentes, e separá-las é o que torna possível responder "por que fulano não vê isto?" sem ler código: `papel` (o que pode fazer), `usuario_escopo` (sobre o que) e `acesso_expira_em` (até quando).

O padrão é não ver nada: usuário provisionado no primeiro login nasce com `papel_id` nulo, e sem papel não se entra.

### `papel`

Conjunto nomeado de permissões e de portais. Uma coluna por permissão, e não uma lista: assim "quem pode exportar?" é um `select`.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único; o sufixo `_leitura`/`_edicao` é explícito porque um papel cujo nome não revela o que concede é um papel que alguém atribui por engano |
| `nome` | `text` | Sim | |
| `pode_criar` | `boolean` | Sim | `default false` |
| `pode_editar_proprio` | `boolean` | Sim | `default false`; edita o que ELE criou |
| `pode_editar_tudo` | `boolean` | Sim | `default false`; mexer no registro de outra pessoa é permissão de coordenação, e fica só em `plataforma_edicao` |
| `administra_dicionarios` | `boolean` | Sim | `default false`; a tela de administração de dicionários ainda não existe — a coluna espera o caso de uso |
| `administra_acessos` | `boolean` | Sim | `default false`; é a permissão que concede todas as outras, e fica só em `plataforma_edicao` |
| `ve_campos_sensiveis` | `boolean` | Sim | `default false`; `relato` e `pendencias` saem do payload da API quando falso |
| `ve_diretorio` | `boolean` | Sim | `default false` |
| `pode_exportar` | `boolean` | Sim | `default false` |
| `acessa_crm` | `boolean` | Sim | `default false`; abre o CRM dos Stakeholders |
| `acessa_sintese` | `boolean` | Sim | `default false`; abre a Síntese Executiva |
| `acessa_score` | `boolean` | Sim | `default false`; abre o Score Executivo |
| `ativo` | `boolean` | Sim | `default true` |
| `criado_em` | `timestamptz` | Sim | `default now()` |

> As três colunas de portal são dimensão SEPARADA das bandeiras de permissão, e a separação é o que impede a lista de papéis de multiplicar: sem ela, cada portal novo dobraria a tabela. Todas fecham por padrão. A carga inicial traz oito papéis — um leitor e um editor por portal, mais os dois de plataforma. A 0009 revoga `insert`/`update`/`delete` desta tabela de `painel_app`.

### `usuario`

Quem entra. Nunca existe coluna de senha em claro — a autenticação é SSO, e o caminho local guarda só hash bcrypt.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `entra_object_id` | `text` | Não | único; é o `oid` do token, e é ele que identifica a pessoa — não o e-mail, que muda. Nulo = usuário só de senha local |
| `senha_hash` | `text` | Não | bcrypt do `pgcrypto`; a comparação acontece no Postgres, para a senha em claro não passar por variável da aplicação nem entrar em log. Nulo = não entra por senha |
| `email` | `citext` | Sim | único; `citext` porque o Entra ID não garante a caixa, e com `text` a unicidade deixaria passar duplicata |
| `nome` | `text` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |
| `provisionado_em` | `timestamptz` | Sim | `default now()` |
| `ultimo_acesso_em` | `timestamptz` | Não | |
| `papel_id` | `smallint` | Não | `references papel(id)`; nulo é o padrão de quem acabou de ser provisionado — e sem papel não se entra |
| `acesso_irrestrito` | `boolean` | Sim | `default false`; verdadeiro dispensa o filtro de escopo. Falso SEM linha em `usuario_escopo` significa não ver nada — a alternativa falharia aberta para todo convidado recém-provisionado |
| `externo` | `boolean` | Sim | `default false` |
| `acesso_expira_em` | `date` | Não | `check (not externo or acesso_expira_em is not null)`: acesso de terceiro sem prazo é acesso que ninguém lembra de revogar |
| `papel_concedido_por` | `uuid` | Não | `references usuario(id)` |
| `papel_concedido_em` | `timestamptz` | Não | também é a VERSÃO usada na detecção de alteração concorrente por `conceder_acesso` |

> `check (entra_object_id is not null or senha_hash is not null)`: toda pessoa precisa poder entrar de algum jeito — sem isso, um `insert` que esquecesse os dois criaria uma conta fantasma que aparece na tela e não autentica por caminho nenhum. A escrita das colunas de autorização não passa por `update` direto: a 0006 criou a função `security definer` `conceder_acesso`, a 0010 acrescentou a ela um cadeado consultivo por transação (`pg_try_advisory_xact_lock`) que impede duas operações simultâneas de deixarem a plataforma sem nenhum administrador ativo, e a 0009 revogou `update` da tabela para `painel_app`, devolvendo só `nome`, `email`, `ultimo_acesso_em` e `ativo`.

### `usuario_escopo`

Restrição de leitura por dimensão.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `usuario_id` | `uuid` | Sim | `references usuario(id) on delete cascade`; parte da chave primária |
| `dimensao` | `text` | Sim | `check (dimensao in ('frente','unidade_negocio'))`; parte da chave primária |
| `valor` | `text` | Sim | parte da chave primária. Sem chave estrangeira porque a dimensão é polimórfica: referencia `frente.codigo` ou `unidade_negocio.nome` conforme o caso |
| `concedido_em` | `timestamptz` | Sim | `default now()` |

> Quem confere que o valor existe é `conceder_acesso` (0006): sem isso, conceder "frente: NAO_EXISTE" grava, a tela informa sucesso, e a pessoa não vê nada sem ninguém entender por quê.

### `acesso_log`

Toda tentativa de login, com ou sem sucesso. É a base das consultas de segurança em `observabilidade/seguranca.kql`.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `bigserial` | Sim | chave primária |
| `usuario_id` | `uuid` | Não | `references usuario(id)` |
| `email_tentado` | `text` | Não | preenchido quando a recusa acontece antes de haver usuário: é a única identificação disponível nesses casos |
| `ocorrido_em` | `timestamptz` | Sim | `default now()` |
| `ip` | `inet` | Não | |
| `resultado` | `text` | Sim | `check (resultado in ('sucesso','negado_sem_papel','negado_vencido','negado_no_provedor','negado_inativo'))` |

> Append-only: a 0009 revoga `update` e `delete` de `painel_app` — poder alterá-los depois de gravados é exatamente o que faria quem quisesse apagar o próprio rastro. É a única tabela que cresce sem teto, e por isso carrega um índice por usuário que nenhuma rota da API consulta, escrito para a investigação de incidente.

---

## 0004 — Interações

O registro que o painel inteiro conta. A forma é tabela-mãe + extensão 1-1 por frente: `interacao` guarda o que TODA frente tem, e o que só existe numa frente vai para uma tabela de extensão que compartilha a chave primária. As duas alternativas foram descartadas — uma tabela larga teria sessenta colunas, cinquenta nulas em cada linha; uma tabela por frente faria toda consulta do painel virar sete `union`.

Soft delete, sempre: `arquivado_em` tira o registro das consultas e o mantém no banco.

### `interacao`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `frente_id` | `smallint` | Sim | `references frente(id)` |
| `data_interacao` | `date` | Sim | |
| `instituicao_id` | `uuid` | Sim | `references instituicao(id)` |
| `interlocutor_id` | `uuid` | Não | `references interlocutor(id)`; aponta para a linha marcada como `principal` em `interacao_interlocutor` — 67 usos em filtros, relatórios e exportação dependem desta coluna, e quem mantém as duas em acordo é o repositório |
| `unidade_negocio_id` | `smallint` | Não | `references unidade_negocio(id)` |
| `esfera_id` | `smallint` | Não | `references esfera(id)` |
| `uf` | `abrangencia` | Sim | obrigatória porque o mapa do painel depende dela; na importação é derivada da UF da instituição quando ausente |
| `tier` | `smallint` | Não | `references relevancia(id)`; quanto mais baixo, mais relevante. Era `check (tier between 1 and 3)` na coluna, o que exigia migration para acrescentar um nível |
| `stakeholder_id` | `smallint` | Não | `references stakeholder(id)` |
| `status_id` | `smallint` | Sim | `references status(id)` |
| `clima_id` | `smallint` | Não | `references clima(id)`; o clima real |
| `resultado_id` | `smallint` | Não | `references resultado(id)` |
| `iniciativa_id` | `smallint` | Não | `references iniciativa(id)` |
| `pauta` | `text` | Não | era obrigatória; o `not null` caiu em 0013, porque `Temas` diz o assunto de forma classificada e `Expectativa` diz o que se quer dele. A coluna fica, e os registros da planilha mantêm a delas |
| `posicionamento` | `text` | Não | |
| `relato` | `text` | Não | campo sensível: sai do payload da API quando o papel não tem `ve_campos_sensiveis`. Também é o marcador de "a reunião já aconteceu" (ver 0020) |
| `encaminhamentos` | `text` | Não | |
| `pendencias` | `text` | Não | campo sensível, como `relato` |
| `observacoes` | `text` | Não | |
| `registro_url` | `text` | Não | o link do registro da interação — a matéria publicada, a ata. Não confundir com `material` |
| `fonte` | `text` | Sim | `default 'cadastro_manual'`, `check (fonte in ('cadastro_manual','importacao_planilha','plataforma_ri'))`; permite refazer uma importação sem tocar no que foi cadastrado à mão |
| `visivel` | `boolean` | Sim | `default true` |
| `origem_aba` | `text` | Não | rastro da planilha de origem, preenchido só quando `fonte` é importação |
| `origem_linha` | `int` | Não | idem |
| `criado_por` | `uuid` | Sim | `references usuario(id)`; indexado porque `pode_editar_proprio` filtra por ele a cada edição |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `atualizado_em` | `timestamptz` | Não | ignorada pela auditoria: muda em toda escrita e não diz nada |
| `arquivado_em` | `timestamptz` | Não | o soft delete; o painel nunca conta arquivado |
| `expectativa` | `text` | Não | **adicionada em 0011** — o que se espera da agenda, escrito ANTES dela. Fica ao lado de `relato` de propósito: lado a lado, a distância entre o que se esperava e o que houve é legível sem consulta |
| `declinado_por` | `text` | Não | **adicionada em 0011** — `check (declinado_por in ('aegea','outra_parte'))`; agenda declinada PELA Aegea é escolha, declinada pela outra parte é porta que se fechou, e somar as duas apaga a diferença |
| `motivo_declinio` | `text` | Não | **adicionada em 0011** |
| `preve_desdobramento` | `boolean` | Não | **adicionada em 0011** — só a INTENÇÃO de continuidade. Nulo = não informado, e não "não" |
| `clima_esperado_id` | `smallint` | Não | **adicionada em 0011** — `references clima(id)`, o mesmo dicionário de `clima_id`; é o que permite dizer "em 8 de 10 agendas o clima veio pior do que se esperava" |
| `modalidade` | `text` | Não | **adicionada em 0015** — `check (modalidade is null or modalidade in ('presencial','online','hibrida'))`. Híbrida existe porque acontece. Nulo = não informado |
| `local` | `text` | Não | **adicionada em 0015** — onde a agenda acontece, em palavras. Texto livre de propósito: uma agenda acontece em "Ministério das Cidades, bloco A" tanto quanto em "Teams" |
| `nota_situacao` | `text` | Não | **adicionada em 0018** — em que condições a agenda foi aceita. O motivo da recusa mora em `motivo_declinio`: são fatos diferentes |
| `formato_interacao_id` | `smallint` | Não | **adicionada em 0038** — `references formato_interacao(id)`; que tipo de encontro foi esse, ortogonal a `frente_id`. Nula em quem foi cadastrado antes da coluna existir |

> A 0011 criou também `origem_interacao_id` (auto-referência, um pai só) e a 0017 a removeu antes de ela ter qualquer linha preenchida: uma coluna descreve uma ÁRVORE, e o encadeamento real é um GRAFO — duas reuniões podem levar juntas a uma terceira. A verdade passou a ser a tabela `interacao_origem`. A 0044 preencheu `formato_interacao_id` onde estava nulo, com o formato mais provável de cada frente (o mesmo mapa de `FORMATO_PADRAO_DA_FRENTE` em `app/dominio/frentes.py`). A 0005 instala o gatilho `auditar_interacao`, que registra campo a campo todo `update` — inclusive os feitos por SQL direto.

### `interacao_imprensa`

Extensão 1-1 da frente de imprensa.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | chave primária, `references interacao(id) on delete cascade` — a extensão não existe sem a mãe |
| `formato_id` | `smallint` | Não | `references formato(id)` |
| `data_atendida` | `date` | Não | |
| `data_publicacao` | `date` | Não | |
| `link_materia` | `text` | Não | |
| `mensagens_chave` | `text[]` | Não | array, e não tabela: são frases livres sem identidade própria, sempre lidas junto com a interação e nunca consultadas isoladamente |

### `interacao_institucional`

Serve governo, parceiros e eventos: as três registram órgão, cargo de quem recebeu e, quando é evento, o nome dele.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | chave primária, `references interacao(id) on delete cascade` |
| `natureza_orgao_id` | `smallint` | Não | `references natureza_orgao(id)` |
| `cargo_interlocutor` | `text` | Não | |
| `nome_evento` | `text` | Não | |

### `interacao_legislativo`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | chave primária, `references interacao(id) on delete cascade` |
| `casa_id` | `smallint` | Não | `references casa(id)` |
| `tramitacao_id` | `smallint` | Não | `references tramitacao(id)` |
| `prioridade` | `text` | Não | `check (prioridade in ('alta','media','baixa','monitoramento'))` |
| `ementa` | `text` | Não | |

### `interacao_investidores`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | chave primária, `references interacao(id) on delete cascade` |
| `tipo_investidor_id` | `smallint` | Não | `references tipo_investidor(id)` |
| `formato_id` | `smallint` | Não | `references formato(id)` |

### `interacao_interna`

A frente interna registra demanda e entrega entre áreas da companhia, com prazo — é a única que tem SLA.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | chave primária, `references interacao(id) on delete cascade` |
| `natureza` | `text` | Não | `check (natureza in ('demanda','entrega'))` |
| `cumprimento` | `text` | Não | `check (cumprimento in ('interno','externo','misto'))` |
| `complexidade` | `text` | Não | `check (complexidade in ('baixa','media','alta'))` |
| `prazo_dias` | `smallint` | Não | |
| `data_retorno` | `date` | Não | |

### `interacao_tema`

Os assuntos de uma agenda.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; parte da chave primária |
| `tema_id` | `int` | Sim | `references tema(id)`; parte da chave primária |

> Auditada por `registrar_vinculo` desde 0005: a linha inteira aparece ou some, e auditar coluna a coluna aqui seria ruído.

### `interacao_pessoa_aegea`

Quem da Aegea participou, e em que papel.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; parte da chave primária |
| `pessoa_aegea_id` | `uuid` | Sim | `references pessoa_aegea(id)`; parte da chave primária |
| `papel` | `text` | Sim | `check (papel in ('porta_voz','equipe'))`; entra na chave primária porque a mesma pessoa pode ser porta-voz de uma interação e equipe de outra, e ambos os fatos importam |
| `presenca` | `text` | Não | **adicionada em 0011** — `check (presenca in ('previsto','presente','ausente'))`. Nulo = não informado (registros anteriores à coluna) |

### `comentario`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade` |
| `autor` | `text` | Sim | texto, e não só a FK: comentário importado da planilha tem o nome de quem escreveu, mas não uma conta correspondente |
| `usuario_id` | `uuid` | Não | `references usuario(id)` |
| `escrito_em` | `timestamptz` | Sim | |
| `texto` | `text` | Sim | |

---

## 0005 — Auditoria

Duas trilhas, uma para cada pergunta que aparece depois de um incidente. Escritas por GATILHO, e não por código da aplicação: um `update` rodado por SQL direto não passaria pela aplicação, e é justamente esse o caso que se precisa enxergar.

As funções são `security definer` e pertencem a `painel_auditoria`, um papel que só pode inserir na trilha — é o que impede a aplicação de forjar ou apagar linhas de auditoria.

### `interacao_auditoria`

O que mudou neste registro, e quem mudou.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `bigserial` | Sim | chave primária; é a única ordem confiável para reconstruir uma edição |
| `interacao_id` | `uuid` | Sim | `references interacao(id)` |
| `usuario_id` | `uuid` | Não | `references usuario(id)`; nulo significa alteração fora da aplicação — é sinal de incidente, não de dado faltando |
| `ocorrido_em` | `timestamptz` | Sim | `default now()`, e não `clock_timestamp()`: identifica a TRANSAÇÃO, não o evento, e as linhas de uma mesma edição compartilham o instante |
| `campo` | `text` | Sim | nome do campo, prefixado pela tabela quando vem de uma extensão (`imprensa.data_publicacao`); sem o prefixo, `formato_id` de imprensa e de investidores seriam indistinguíveis |
| `valor_anterior` | `text` | Não | |
| `valor_novo` | `text` | Não | |
| `origem` | `text` | Não | `session_user`, a conta com que a conexão se autenticou — diferente de `usuario_id`, não é escolhida por quem escreve |

> `registrar_vinculo()`, a função que audita os vínculos N-N, foi redefinida duas vezes depois: a **0041** nomeou a coluna de cada vínculo (a versão de 0005 caía em `tema_id` para qualquer tabela que não fosse `interacao_pessoa_aegea`, e `interacao_interlocutor` vinha gravando valor nulo desde a 0011) e acrescentou `interacao_area`; a **0046** acrescentou `interacao_alegacao`, como superconjunto da anterior para não desfazê-la.

### `usuario_auditoria`

Quem deu acesso a quem, e quando.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `bigserial` | Sim | chave primária |
| `usuario_id` | `uuid` | Sim | `references usuario(id)`; de quem é o acesso que mudou |
| `concedido_por` | `uuid` | Não | `references usuario(id)`; informado pela aplicação, e portanto forjável por quem tem a credencial |
| `ocorrido_em` | `timestamptz` | Sim | `default now()`; identifica a TRANSAÇÃO, como na outra trilha |
| `campo` | `text` | Sim | só o que decide o que a pessoa alcança — `papel_id`, `acesso_irrestrito`, `externo`, `acesso_expira_em`, `ativo` — mais `escopo.<dimensao>` |
| `valor_anterior` | `text` | Não | |
| `valor_novo` | `text` | Não | |
| `origem` | `text` | Não | a conta de banco, que não é escolhida |

> A 0009 revoga `insert`, `update` e `delete` das duas trilhas (e das sequences) de `painel_app`, deixando só `select`. Sem isso, quem tivesse a connection string inseria linha falsa e a auditoria deixaria de ser evidência de coisa nenhuma.

---

## 0007 — Exportações

Não existe gerador de documento no servidor: o CSV é montado no navegador a partir da listagem já baixada. O que esta tabela guarda é o EVENTO — quem gerou, sobre qual recorte, e quantos registros o recorte alcançava. É trilha, não barreira.

### `exportacao`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `filtros` | `jsonb` | Sim | o recorte serializado, no formato do value object `Recorte`. Guardar os filtros — e não só a contagem — é o que permite reproduzir depois o que a pessoa estava vendo |
| `criado_por` | `uuid` | Sim | `references usuario(id)` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `total_de_registros` | `int` | Sim | `default 0`; tamanho do recorte no momento da exportação, contado no servidor. É o insumo do alerta "alguém levou a base inteira" |

> A tabela nasceu como `relatorio` e foi **renomeada para `exportacao` em 0025**, quando a tela de relatório saiu do produto: a mesma tabela guardava o relatório impresso (que saiu) e a trilha de quem exportou a Base (que é controle de segurança e ficou). Na mesma migration saíram as colunas `secoes`, `formato` e `arquivo_url`, que só o relatório usava — sem perda de dado, porque a tabela tinha zero linhas. Append-only: `painel_app` não tem `update` nem `delete` aqui. Não há índice sobre `filtros`, e a ausência é deliberada — a coluna é gravada e lida inteira.

---

## 0008 — Importação (schema sem aplicação)

⚠ Estas duas tabelas existem; o código que as usa NÃO foi implementado. Não há rota, caso de uso nem tela de importação. Estão aqui porque a forma delas foi decidida junto com o resto do modelo, e porque `interacao.fonte`, `interacao.origem_aba` e `interacao.origem_linha` já apontam para este fluxo.

O desenho previsto: cada linha do arquivo vira uma `importacao_linha` com os dados brutos preservados, a aplicação propõe uma interação e lista o que não conseguiu resolver, uma pessoa confere linha a linha, e só na confirmação as interações são criadas.

### `importacao`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `arquivo_nome` | `text` | Sim | |
| `situacao` | `text` | Sim | `default 'processando'`, `check (situacao in ('processando','aguardando_conferencia','confirmada','cancelada'))` |
| `criado_por` | `uuid` | Sim | `references usuario(id)` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `confirmado_em` | `timestamptz` | Não | |

### `importacao_linha`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `bigserial` | Sim | chave primária |
| `importacao_id` | `uuid` | Sim | `references importacao(id) on delete cascade` |
| `aba` | `text` | Sim | de onde veio, para a pessoa conseguir voltar à planilha e conferir |
| `linha_origem` | `int` | Sim | idem |
| `dados_brutos` | `jsonb` | Sim | o que estava na célula, sem interpretação; preservado mesmo depois de aceito, para permitir reprocessar quando a regra de leitura mudar |
| `proposta` | `jsonb` | Não | o que a aplicação entendeu, no formato de uma interação |
| `divergencias` | `jsonb` | Sim | `default '[]'::jsonb`; o que ela não conseguiu resolver sozinha. Lista vazia significa linha limpa |
| `decisao` | `text` | Sim | `default 'pendente'`, `check (decisao in ('pendente','aceita','corrigida','descartada'))` |
| `interacao_id` | `uuid` | Não | `references interacao(id)`; preenchido na confirmação, ligando a linha da planilha ao registro criado |

> A 0009 revoga `insert`, `update` e `delete` destas duas tabelas de `painel_app`: permissão sem uso é permissão que ninguém revisa, e quem for implementar a importação precisa concedê-la explicitamente ali.

---

## 0011 — Ciclo da agenda

A interação deixa de ser um fato consumado e passa a ser uma AGENDA com ciclo de vida — pedida, planejada, confirmada ou declinada, realizada, desdobrada. Responder "estamos sendo ativos o bastante, e o que prometemos aconteceu?" exige separar o PREVISTO do REAL.

Tudo anulável, sem exceção: uma coluna `not null` com valor padrão inventaria história sobre os registros que vieram da planilha. Nulo aqui quer dizer NÃO INFORMADO.

### `interacao_interlocutor`

Participantes da outra parte — o principal inclusive.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; parte da chave primária |
| `interlocutor_id` | `uuid` | Sim | `references interlocutor(id)`; parte da chave primária |
| `presenca` | `text` | Não | `check (presenca in ('previsto','presente','ausente'))`. `ausente` é a mais valiosa das três: uma reunião em que o decisor não apareceu não é a reunião que se pediu. Nulo = não informado |
| `principal` | `boolean` | Sim | `default false`; no máximo um por interação, garantido por índice único PARCIAL (`where principal`) e não por convenção |

> A primeira versão guardava só os DEMAIS participantes, e o principal ficava apenas em `interacao.interlocutor_id` — não havia onde dizer se ele compareceu. `interacao.interlocutor_id` permanece e aponta para a linha marcada como `principal`. Auditada por `registrar_vinculo` desde esta migration; até a 0041 a trilha gravava valor nulo, porque a função caía em `tema_id`.

### `material`

Documentos de uma agenda. Três momentos, uma tabela: apoio existe antes da reunião; obtido e produzido existem depois.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade` |
| `momento` | `text` | Sim | `check (momento in ('apoio','obtido','produzido'))` |
| `titulo` | `text` | Sim | |
| `url` | `text` | Não | o link para SharePoint/Drive |
| `arquivo_id` | `uuid` | Não | nasceu inerte, sem referência, porque a tabela do outro lado ainda não existia; **ganhou `references arquivo(id) on delete restrict` em 0012** — `cascade` deixaria um material órfão prometendo um anexo que não volta, e `set null` violaria a restrição abaixo na escrita seguinte |
| `observacao` | `text` | Não | |
| `criado_por` | `uuid` | Sim | `references usuario(id)`; deliberadamente SEM índice — ninguém pergunta "quais materiais fulano cadastrou" |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `referencia_id` | `uuid` | Não | **adicionada em 0026** — `references referencia(id) on delete set null`; de qual referência da biblioteca este material veio. Nula no que alguém escreveu à mão. `set null` e não `cascade`: apagar uma referência não pode apagar o material de uma reunião que aconteceu |

> `check (url is not null or arquivo_id is not null)`: ao menos um dos dois, senão o material não é nada além de um título. `interacao.registro_url` continua existindo e é outra coisa — o link do registro da interação, não um documento que circula em torno dela.

---

## 0012 — Arquivo do material

A 0011 criou `material.arquivo_id` inerte, com um comentário dizendo que guardar arquivo no painel traz "armazenamento, limite de tamanho, antivírus e política de retenção — uma frente inteira". Esta migration abre a metade de baixo dessa frente: armazenamento e limite.

### `arquivo`

Um arquivo no Blob Storage. É uma ENTIDADE, e não colunas soltas no material: "que material é este" e "onde está o byte" são perguntas diferentes, e misturá-las faria um material por link carregar cinco colunas nulas.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `caminho` | `text` | Sim | único (`arquivo_caminho_unico`); GRAVADO e não derivado por convenção — convenção derivada quebra em silêncio no dia em que mudar, e os arquivos antigos continuam onde estavam |
| `nome` | `text` | Sim | o nome que a pessoa subiu; não entra no caminho, que precisa ser estável, mas é ele que volta no download |
| `tipo_conteudo` | `text` | Sim | o que o navegador precisa para decidir se abre ou baixa |
| `tamanho` | `bigint` | Sim | `check (tamanho > 0)`; em bytes, aqui e não só no blob, para a tela mostrar o tamanho sem uma ida ao armazenamento por linha de lista |
| `criado_por` | `uuid` | Sim | `references usuario(id)` |
| `criado_em` | `timestamptz` | Sim | `default now()` |

> A própria migration registra o que ela NÃO faz, para que a ausência seja decisão e não esquecimento: não há antivírus, não há política de retenção (o blob cresce para sempre) e não há deduplicação — o mesmo PDF subido em duas agendas ocupa dois caminhos, que é o comportamento certo enquanto não houver retenção.

---

## 0017 — A agenda vem de várias

A 0011 criou `interacao.origem_interacao_id`: uma coluna, um pai só. Isso descreve uma árvore, e a realidade que o painel precisa mostrar é um grafo — duas reuniões podem levar juntas a uma terceira, e uma reunião pode abrir várias frentes. A coluna saiu em vez de conviver com a tabela, porque duas representações do mesmo fato divergem.

### `interacao_origem`

De quais agendas esta agenda decorre.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; a agenda que DESCENDE. Parte da chave primária |
| `origem_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; a agenda que veio ANTES. Parte da chave primária. `cascade` e não `restrict`, que travaria a exclusão por causa de um vínculo informativo, nem `set null`, que desenharia uma seta partindo do vazio |
| `criado_em` | `timestamptz` | Sim | `default now()` |

> `check (interacao_id <> origem_id)`: uma agenda não descende de si mesma. O ciclo mais longo — A → B → A — não cabe num `check` e é barrado no repositório, que consegue subir a cadeia inteira.

---

## 0026 — Biblioteca de referências

A Aegea mantém um acervo por assunto — posicionamentos, Q&A, releases, notas técnicas — e é dele que os porta-vozes tiram o que dizem. A referência é ligada a ASSUNTO, e não a agenda: assunto é o que se escolhe ao marcar uma reunião, e é por ele que o material certo se encontra sozinho.

### `referencia`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `titulo` | `text` | Sim | único por `lower(btrim(titulo))`: duas linhas "Q&A Tarifa 2026" apontando para arquivos diferentes é o começo de duas versões circulando |
| `tipo` | `text` | Sim | `check (tipo in ('posicionamento','qa','release','apresentacao','dados','nota_tecnica'))`; quem procura material antes de uma reunião procura por tipo, e não por título |
| `resumo` | `text` | Não | para quem está decidindo se abre o arquivo; obrigatório na API, não no banco |
| `ativo` | `boolean` | Sim | `default true`; a referência não se apaga — uma referência apagada levaria consigo a explicação de por que certa reunião recebeu certo material |
| `criado_por` | `uuid` | Sim | `references usuario(id)` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `tema_principal_id` | `int` | Não | **adicionada em 0028** — `references tema(id)`; o assunto que define a PASTA no blob. Nulo no banco e obrigatório na API, porque uma referência nasce em duas escritas — a linha e a primeira versão |

> A 0028 removeu `url`, `atualizado_em`, `fonte_da_data` e `lido_em`, que eram da época em que o arquivo morava no SharePoint: a data passou a ser da VERSÃO, a fonte dela é sempre quem subiu, e o link deu lugar ao arquivo no Blob. Os 69 registros de demonstração (links fictícios que não abriam) saíram na mesma migration.

### `referencia_tema`

Os assuntos de uma referência — é a consulta que a tela de agenda faz a cada assunto marcado.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `referencia_id` | `uuid` | Sim | `references referencia(id) on delete cascade`; parte da chave primária |
| `tema_id` | `int` | Sim | `references tema(id)`; parte da chave primária |

> `delete` é concedido a `painel_app` aqui: trocar os tópicos de uma referência é apagar linhas desta tabela, e as `alter default privileges` da 0009 só dão select/insert/update.

---

## 0027 — Assunto do material

A biblioteca do SharePoint é organizada por assunto desde que nasceu; o que a equipe sobe para o armazenamento próprio não tinha nada disso — a ata de uma reunião só era alcançável por quem soubesse de qual reunião ela saiu.

### `material_tema`

De que assuntos um material trata. Espelha `referencia_tema`, para que a busca por assunto seja a mesma nas duas procedências.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `material_id` | `uuid` | Sim | `references material(id) on delete cascade`; parte da chave primária |
| `tema_id` | `int` | Sim | `references tema(id)`; parte da chave primária |

> Os materiais que já existiam herdaram os assuntos da agenda — é um palpite, e por isso só valeu para o acervo anterior à migration. `delete` concedido a `painel_app` pelo mesmo motivo de `referencia_tema`.

---

## 0028 — Referência com versões

Uma referência tem VERSÕES, e não um arquivo: o Q&A de tarifa de agosto substitui o de março, e o de março continua existindo — foi ele que circulou naquela reunião.

### `referencia_versao`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `referencia_id` | `uuid` | Sim | `references referencia(id) on delete cascade` |
| `numero` | `int` | Sim | 1, 2, 3… na ordem em que entraram; é o que a tela mostra como "v3" e o que ordena o histórico sem depender de data. Único por referência (`referencia_versao_unica`) |
| `arquivo_id` | `uuid` | Não | `references arquivo(id) on delete restrict`; `restrict` porque apagar um arquivo por engano não pode levar embora o registro de que a versão existiu. Era `not null` — o **`not null` caiu em 0034**, quando o conteúdo em texto passou a ser forma válida de versão |
| `atualizado_em` | `date` | Sim | a data DO DOCUMENTO, informada por quem sobe; não é `criado_em` — o arquivo pode ser de março e entrar aqui em agosto |
| `nota` | `text` | Não | o que mudou nesta versão; é ela que responde "por que trocaram" |
| `criado_por` | `uuid` | Sim | `references usuario(id)` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `conteudo` | `text` | Não | **adicionada em 0034** — texto livre por versão. Obrigatório para versões NOVAS pela API (`Form()` sem default), e não por `not null` aqui: as versões já cadastradas ficam sem ele para sempre, sem backfill |

---

## 0029 — Área do representante

`pessoa_aegea` já distinguia porta-voz de equipe; faltava dizer DE ONDE essa pessoa fala. Um dicionário, e não uma coluna de texto livre — o mesmo padrão de `esfera`/`relevancia`: a coordenação muda os valores por `insert`/`update`, sem migration, e o front não precisa de lista fixa nenhuma.

### `area_pessoa`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> Cinco áreas na carga: Comunicação, Relações Institucionais, Operações Financeiras, Performance e Dados, Relações com Investidores. A **0033** marcou `performance_e_dados` como `ativo = false` — e não `delete`, porque já havia `interacao_area` apontando para ela. `GET /api/dicionarios` filtra todo dicionário por `ativo`, então ela some das listagens novas sem mudança de código. A **0035** removeu uma tabela `area` órfã, criada por uma migration paralela e abortada (`0029_area_interna.sql`) que um merge anterior trouxe por engano; `area_pessoa` é o modelo correto, e a remoção confere antes se `interacao_area` tem FK apontando para a órfã em vez de apagar às cegas.

---

## 0032 — Área da interação

Mesmo padrão de `interacao_tema`: vínculo N:N puro, sem atributo próprio. Reaproveita `area_pessoa` — é o mesmo vocabulário, aplicado a um registro diferente. Nenhum dicionário novo.

### `interacao_area`

Quais áreas internas participam de uma interação.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; parte da chave primária |
| `area_id` | `smallint` | Sim | `references area_pessoa(id)`; parte da chave primária |

> A **0041** completou o padrão que esta migration deixou pela metade: concedeu `delete` a `painel_app` (sem ele, tirar uma área de uma agenda devolvia "permission denied" só na hora de salvar, e só em produção, porque desenvolvimento roda como superusuário) e instalou o gatilho de auditoria — área interna é a mesma natureza de fato que tema e porta-voz, influencia Painel e filtros, e mudava em silêncio.

---

## 0036 — Categoria de público

Uma taxonomia de 10 categorias, cada uma com sua própria subdivisão e uma área da Aegea dona daquele público. Mora em `instituicao`, e não em `interacao`: categoria de público é atributo do órgão em si — "Ministério da Fazenda" é Poder Executivo Federal em qualquer reunião.

### `categoria_publico`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `padrao_de_quebra` | `text` | Sim | `check (padrao_de_quebra in ('esfera','logica_de_relacao','posicao_de_capital','logica_editorial','sem_quebra'))`; é texto com check, e não tabela, porque é metadado descritivo de COMO a categoria se subdivide — mesmo raciocínio de `formato.escopo` (alterado em 0037: "Entidades Setoriais e Representativas" deixa de ser `sem_quebra` e passa a `logica_de_relacao`) |
| `area_dona_id` | `smallint` | Não | `references area_pessoa(id)`; nulo só na categoria "Parceiros e Cadeia de Valor", onde a área responsável é quem demandou a interação — variável, e já capturada por `interacao_area` |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> A **0039** acrescentou aqui uma coluna `frente_padrao_id` (`references frente(id)`), para a tela deixar de perguntar a Frente e o backend derivá-la da categoria de público da instituição. A **0040** a removeu sem que ela chegasse a servir: `derivar_frente` passou a derivar do TIPO da instituição, que basta sozinho e cobre inclusive os dois casos que a categoria não tinha como cobrir — `proposicao` (Legislativo) e `credor` (Bancos/Credores), que não têm categoria de público nenhuma. Categoria de público continua existindo como o campo informativo "Público" da tela.

### `subcategoria_publico`

A subdivisão dentro da categoria. Existe só para quem tem subdivisão de verdade — as categorias `sem_quebra` não geram linha nenhuma aqui e ficam representadas por `instituicao.subcategoria_publico_id` nulo.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `categoria_publico_id` | `smallint` | Sim | `references categoria_publico(id)` |
| `codigo` | `text` | Sim | único por categoria (`unique (categoria_publico_id, codigo)`), e não globalmente: "federal" se repete em Poder Executivo, Poder Legislativo e Reguladores |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> A **0037** ajustou a taxonomia a partir da planilha de referência, que chegou depois: acrescentou "Municipal / local" em Imprensa e Formadores de Opinião (empurrando "Setorial" da ordem 4 para a 5) e criou "Institutos e Associações" e "Academias" em Entidades Setoriais.

---

## 0038 — Formato da interação

Responde "que tipo de encontro foi esse", uma pergunta DIFERENTE da que `frente` responde ("quem é a contraparte"). Não é substituto: uma "Reunião" ou "Visita" acontece com qualquer frente, e as duas colunas convivem.

### `formato_interacao`

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

> Sete valores na carga: Mídia, Agenda de mercado, Agenda pública, Manifestação formal, Evento, Visita, Reunião. A **0046** acrescentou o oitavo, "Consulta recebida" — dicionário aberto, que a coordenação poderia ter criado pela tela, mas que entrou por migration porque `interacao_consulta` só faz sentido com ele. A **0044** preencheu `interacao.formato_interacao_id` no acervo que nasceu sem ele, pelo formato mais provável de cada frente.

---

## 0046 — Consulta recebida e alegação

Investidores, bancos e plataformas de rating mandam questionários perguntando sobre assuntos que a companhia não comunicou. A pergunta costuma trazer o assunto JÁ COMO FATO, e é essa premissa — não o e-mail — que interessa: quando ela chega de várias instituições que não se falam, em poucos dias, há um movimento de mercado em curso.

Dois níveis: a CONSULTA é uma interação como as outras; a ALEGAÇÃO vive solta dela, N:N, porque é ela que se repete. Contar consultas responde "quanto nos perguntaram"; contar INSTITUIÇÕES DISTINTAS por alegação responde "o quanto isto está circulando".

O vocabulário é "alegação", e não "boato": uma premissa pode proceder, e registrar que uma instituição espalha boatos é afirmação com consequência jurídica feita a partir de um e-mail que pode ser diligência honesta.

### `canal_consulta`

Por onde a consulta chegou. Dicionário aberto: o canal muda com o mercado, e nenhum cálculo depende destes códigos.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `apuracao`

Em que pé está a apuração da alegação.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `smallserial` | Sim | chave primária |
| `codigo` | `text` | Sim | único |
| `nome` | `text` | Sim | |
| `cor_hex` | `char(7)` | Sim | a tela pinta a alegação por ele, como faz com clima. As cores dizem RISCO, e não aprovação: "procede" é o caso de maior consequência |
| `ordem` | `smallint` | Sim | |
| `ativo` | `boolean` | Sim | `default true` |

### `alegacao`

O que uma pergunta recebida dá como fato, sem que a companhia tenha comunicado.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `id` | `uuid` | Sim | chave primária, `default gen_random_uuid()` |
| `texto` | `text` | Sim | a premissa em uma frase, na voz de quem alega — não a pergunta transcrita nem o resumo do e-mail. É o que se repete de um remetente para outro |
| `texto_normalizado` | `text` | Sim | único (`alegacao_texto_unico`); minúsculas, sem acento, espaços colapsados. Sem ele, duas pessoas registrariam a mesma alegação com maiúsculas diferentes e o produto perderia a contagem que existe para fazer |
| `apuracao_id` | `smallint` | Sim | `references apuracao(id)` |
| `referencia_id` | `uuid` | Não | `references referencia(id)`; o posicionamento que responde a esta alegação, na biblioteca. É o elo que faz a tela dizer "isto está circulando e não temos resposta publicada" |
| `nota` | `text` | Não | o que a companhia apurou. Nulo enquanto ninguém apurou |
| `ativo` | `boolean` | Sim | `default true`; a alegação NÃO se apaga — é o histórico do que circulou, e apagá-la reescreveria a leitura de um período que já foi lido. Sai de circulação por aqui |
| `criado_por` | `uuid` | Não | `references usuario(id)` |
| `criado_em` | `timestamptz` | Sim | `default now()` |
| `atualizado_em` | `timestamptz` | Sim | `default now()` |

### `alegacao_tema`

De que assuntos uma alegação trata.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `alegacao_id` | `uuid` | Sim | `references alegacao(id) on delete cascade`; parte da chave primária |
| `tema_id` | `integer` | Sim | `references tema(id)`; parte da chave primária |

### `interacao_consulta`

Os dados próprios de uma interação do tipo "Consulta recebida". É 1-1 com `interacao` e CONVIVE com a extensão da frente, em vez de disputar o lugar dela: as extensões de 0004 são escolhidas pela FRENTE, e a consulta é escolhida pelo TIPO DE INTERAÇÃO — uma consulta de banco tem frente `bancos_credores` e já usa a extensão de investidores.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | chave primária, `references interacao(id) on delete cascade` |
| `canal_id` | `smallint` | Não | `references canal_consulta(id)` |
| `remetente` | `text` | Não | quem assina o e-mail, em texto; para o caso comum de quem escreve não estar (nem precisar estar) no cadastro. O contato cadastrado é `interacao_interlocutor` |
| `teor` | `text` | Não | as perguntas, coladas do e-mail. Guardar o que basta para reconhecer a pergunta — e não o corpo integral, que tem dado pessoal de quem enviou — é escolha deliberada; o anexo continua em `material` |
| `motivo` | `text` | Não | por que acham que perguntaram: a hipótese de quem leu sobre a INTENÇÃO de quem perguntou. NÃO é a alegação — a alegação é o que a pergunta DIZ, observável e contável; misturá-los faria a tela apresentar suposição com autoridade de fato |
| `prazo_resposta` | `date` | Não | até quando responder, se o remetente deu prazo |
| `respondida_em` | `date` | Não | nulo com `prazo_resposta` vencido é o que a tela cobra |

### `interacao_alegacao`

Quais alegações uma consulta trouxe.

| Coluna | Tipo | Obrigatória | Observações |
|---|---|---|---|
| `interacao_id` | `uuid` | Sim | `references interacao(id) on delete cascade`; parte da chave primária |
| `alegacao_id` | `uuid` | Sim | `references alegacao(id)`; parte da chave primária. Indexado à parte, porque a busca da aba é pela alegação e a chave primária só serve à direção contrária |

> Auditada por gatilho: dizer que uma consulta trouxe (ou deixou de trazer) uma alegação muda a contagem que a tela usa para afirmar que algo está circulando, e mudar isso em silêncio não é opção. `delete` concedido a `painel_app` em `interacao_consulta`, `interacao_alegacao` e `alegacao_tema`, porque trocar as alegações de uma consulta e os temas de uma alegação apagam linhas de verdade.
