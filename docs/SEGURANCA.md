# Arquitetura de segurança

> Faz parte de `back-reputacional`. O que descreve vive neste repositório;
> os artefatos de infraestrutura (`.bicep`) e as consultas de alerta ficam no
> repositório do painel.

O que a solução faz hoje, camada por camada, e o que ainda não existe.

O painel guarda relacionamento institucional: quem a Aegea procurou, o que foi
dito, o que ficou pendente. Parte disso é sensível por natureza — posicionamento
sobre tarifa antes de virar público, relato de conversa com parlamentar — e a
base é consultada por gente de fora (agência de comunicação, consultoria).

Essa mistura define o desenho: **autenticação é do Entra ID, autorização é do
banco, e o padrão é não ver nada.**

---

## 1. Autenticação

**Microsoft Entra ID, OIDC authorization code + PKCE.** Nunca existe senha neste
sistema — não há coluna, não há cadastro, não há redefinição.

O fluxo está em `app/api/acesso.py` e
`app/seguranca/oidc.py`:

| Etapa | O que protege |
|---|---|
| `state` em cookie próprio, conferido na volta | CSRF no próprio login |
| PKCE S256 (`code_verifier` nunca sai do servidor) | código interceptado sem valor |
| `nonce` conferido contra o `id_token` | replay de token |
| Assinatura RS256 validada contra JWKS, com cache | token forjado |
| `aud`, `iss` e `exp` conferidos | token de outro app ou tenant |

A identidade estável é o `oid` do token, e não o e-mail: e-mail corporativo muda
(casamento, transferência entre empresas do grupo) e o `oid` não. Identificar
pelo e-mail faria a pessoa perder o histórico ao trocar de endereço.

### A sessão

Cookie assinado com HMAC-SHA256, montado com a biblioteca padrão
(`app/seguranca/sessao_assinada.py`). Guarda o id do usuário,
o prazo e o token anti-CSRF — e **não** guarda papel nem escopo.

Isso é deliberado: papel e escopo são lidos do banco a cada requisição, então
uma revogação vale no próximo clique em vez de na próxima sessão. O custo é uma
consulta por requisição; o ganho é não ter janela entre revogar e deixar de
valer.

Atributos do cookie: `HttpOnly`, `Secure` em produção, `SameSite=Lax`,
`Path=/`. `Lax` e não `Strict` porque o retorno do provedor é uma navegação de
outro site — com `Strict` o cookie não voltaria e o login nunca fecharia.

### Desenvolvimento

`AUTH_MOCK=true` devolve um usuário fixo pelo mesmo caminho de provisionamento,
para desenvolver sem depender do tenant. A conferência de subida (§9) **recusa
iniciar em produção** com ele ligado.

---

## 2. Autorização

Três eixos independentes, e separá-los é o que permite responder "por que fulano
não vê isto?" sem ler código.

```
papel             O QUE pode fazer       criar, editar, exportar, administrar
usuario_escopo    SOBRE O QUE            quais frentes, quais unidades
acesso_expira_em  ATÉ QUANDO             obrigatório para quem é de fora
```

O schema está na migration `app/banco/migrations/0003_acesso.sql`.

### Por que tabela, e não claim de grupo do Entra ID

Escopo granular — esta frente, aquela unidade — não cabe em grupo de AD sem
multiplicar grupos (`externo_imprensa_rio`, `externo_imprensa_sp`, …). Além
disso, a lista de grupos do tenant é administrada por outra equipe, e cada
mudança de permissão viraria um chamado.

Com a tabela, a coordenação concede pela própria tela, e a trilha fica no mesmo
banco do resto.

### A regra de resolução, e ela falha FECHADA

1. `acesso_irrestrito = true` → nenhum filtro de escopo. É o caso do interno.
2. `acesso_irrestrito = false` → o registro precisa casar com pelo menos uma
   linha de **cada dimensão presente** em `usuario_escopo`.
3. `acesso_irrestrito = false` **e nenhuma linha de escopo** → **não vê nada**.
4. `acesso_expira_em < hoje` → **não vê nada**, seja qual for o papel.
5. `papel_id` nulo → **não entra**.

O item 3 é o que importa. A alternativa natural — "sem linha significa sem
restrição" — falharia ABERTA: um convidado recém-provisionado enxergaria tudo.

O item 4 é conferido a cada requisição porque a dependência monta o usuário do
banco toda vez. **Se um dia a sessão passar a guardar papel e escopo, a
revalidação por requisição precisa entrar junto** — senão um acesso que vence no
meio do expediente continua valendo até o próximo login.

### Por que o prazo é obrigatório para quem é de fora

A autorização em tabela tem uma fraqueza que a claim de grupo não tem: ela nunca
fica sabendo que a pessoa mudou de função. O Entra ID sabe, porque é o sistema
de registro da organização; a tabela não.

Para o interno isso é incômodo. Para o externo é risco: contrato de agência
acaba e dependem-se de duas limpezas que ninguém faz — remover o convidado do
tenant **e** apagar a linha daqui.

A restrição `externo_tem_prazo` transforma o esquecimento em expiração: sem
renovar, o acesso morre sozinho. É a única parte deste desenho que funciona
quando ninguém está prestando atenção — que é exatamente quando incidente
acontece.

A tela de administração mostra "expira em N dias" com destaque quando está
perto, e a renovação é evento auditável.

### Onde o escopo é aplicado

| Frente | Onde | O que faz |
|---|---|---|
| Listagem e agregações | `app/banco/filtros_sql.condicoes()` | junta as condições de escopo depois dos filtros pedidos |
| Ficha por id | `casos_de_uso/consultar_interacoes.obter()` | usa `condicoes()`, e não `sessao.get()` direto |
| Diretórios | `app/api/stakeholders.py` | exige `papel.ve_diretorio` |
| Campos sensíveis | `esquemas/interacoes.py :: InteracaoSaida` | `relato` e `pendencias` só com `papel.ve_campos_sensiveis` |

**`filtros_sql.condicoes()` é o único ponto que traduz `Recorte` em SQL**, e
isso é invariante do sistema: é o que faz o KPI do painel contar exatamente o
que a tabela lista. Uma consulta nova que monte `where` por conta própria quebra
a garantia em silêncio.

Os parâmetros `escopo` e `busca_em_campos_sensiveis` são **obrigatórios e
nomeados** justamente por isso: esquecer é `TypeError` na hora, e não um buraco
silencioso.

### A ficha por id, e o IDOR

`obter()` aplica escopo. Sem isso, quem soubesse um UUID leria qualquer
interação — a listagem filtraria, e a ficha não. É o caso clássico de IDOR, e a
diferença entre `sessao.get(id)` e "buscar com as mesmas condições da listagem".

---

## 3. A escrita de autorização

A conta da aplicação **não pode** escrever nas colunas de autorização. Quem
escreve é a função `conceder_acesso` (migration `app/banco/migrations/0006_concessao_de_acesso.sql`),
`security definer`, com dono próprio.

**O que ela garante:** integridade (nenhum estado inválido é criável),
contenção (um caminho novo na aplicação não consegue esquecer as regras),
trilha (os gatilhos gravam venha de onde vier) e versão otimista com trava de
linha (duas pessoas editando o mesmo acesso não se sobrescrevem).

**O que ela NÃO garante, e é importante estar escrito:** contra quem detém a
credencial da aplicação, não há barreira. O banco não distingue "a aplicação
agindo por um administrador" de "alguém com a connection string" — as duas
chegam pela mesma conta, e `quem_concede` é parâmetro.

A fronteira de autorização é a aplicação. O que barraria de verdade seria a
concessão passar por um serviço separado, com credencial de banco que o processo
do painel não possui. É mudança de arquitetura, e está registrada em §10.

### A versão otimista

`papel_concedido_em` é a versão. Quem salva declara o que viu em `versao_vista`;
se o banco tiver outra coisa, a função recusa e a tela recarrega.

Dois detalhes que decidem se isso funciona:

- **Nulo não é curinga.** Afirma "vi esta pessoa sem concessão nenhuma", e só
  passa se o banco também estiver sem. Toda pessoa nova aparece na lista com
  `concedido_em` nulo, então tratar nulo como "aplique de qualquer jeito"
  esvaziaria a trava no caso mais comum de todos.
- **`select ... for update`** antes de comparar. Sem a trava, duas transações
  simultâneas leem a mesma versão, as duas passam, e a segunda vence.

O campo é **obrigatório** na rota HTTP e no serviço Python. Omitir seria afirmar
algo sobre o estado do banco sem ter olhado.

---

## 4. Auditoria

Duas trilhas, escritas por **gatilho** e não pela aplicação (migration
`app/banco/migrations/0005_auditoria.sql`):

| Tabela | Responde |
|---|---|
| `interacao_auditoria` | o que mudou neste registro, e quem mudou |
| `usuario_auditoria` | quem deu acesso a quem, e quando |
| `acesso_log` | quem entrou, quando, de onde — e quem tentou e não entrou |

Trilha escrita pela aplicação registra o que a aplicação faz. Um `update` rodado
por SQL direto — manutenção, correção de emergência, alguém com a credencial —
não passaria por ela, e é justamente esse o caso que se precisa enxergar.

### As duas colunas de autoria

```
usuario_id / concedido_por   quem a APLICAÇÃO diz que agiu. Vem de
                             `SET LOCAL painel.usuario_id`. É declarado, e
                             portanto forjável por quem tem a credencial.

origem                       `session_user`, a conta com que a conexão se
                             autenticou. Não é escolhida por quem escreve.
```

Nulo em `usuario_id` com `origem` preenchida é a assinatura de alteração feita
fora da aplicação. **Não é dado faltando: é sinal.**

### A recusa de login sobrevive ao rollback

`obter_sessao` desfaz a transação em qualquer exceção, erro de domínio inclusive
— e negar um login é levantar um erro de domínio. Por isso
`registrar_e_confirmar` grava numa sessão própria: sem isso, a linha seria
escrita e desfeita milissegundos depois, deixando sem rastro o evento que mais
interessa.

---

## 5. Superfície HTTP

Tudo em `app/seguranca/protecao_http.py` e `main.py`.

| Proteção | Como |
|---|---|
| CORS | origens explícitas, métodos e cabeçalhos listados. Nunca `["*"]` — com `allow_credentials=True` o curinga transforma qualquer origem aceita numa origem confiável |
| CSRF | duplo envio: token no cookie de sessão e em `X-CSRF-Token`, conferidos em toda escrita |
| Cabeçalhos | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP restritiva, `Permissions-Policy` |
| HSTS | ligado por configuração, desligado onde o certificado não é confiável |
| Tamanho de corpo | limite conferido no `Content-Length` E durante o envio, para cobrir `Transfer-Encoding: chunked` |
| Documentação | `/docs` e `/openapi.json` fora do ar em produção |

### O CSRF e o CORS interagem

O cabeçalho `X-CSRF-Token` precisa estar na allowlist do CORS. Fora dela, o
preflight de toda escrita é recusado e nada funciona — e um teste que só
verifique "não é 403" passa sem provar nada. A suíte tem preflight de verdade e
um 201 depois dele.

### A CSP da página

Quem carrega o `<script>` é o documento, servido pelo nginx do front — e não a
API. Conferir só a API dá falsa segurança.

`connect-src` é substituído no build a partir de `VITE_API_URL` e da connection
string do Application Insights: são o mesmo fato do bundle, e endereço fixo no
arquivo se desencontraria dele. A CSP é do frontend, e vive no repositório
dele.

`style-src 'unsafe-inline'` está declarado como **dívida**: o painel usa estilo
inline em quase todo componente, e tirar exigiria reescrever a estilização.

---

## 6. Limite de taxa

Duas camadas, em `app/seguranca/limite_de_taxa.py`. Token bucket em memória.

| Camada | Chave | Padrão | Para quê |
|---|---|---|---|
| Middleware | endereço IP | 600 fichas, 40/s | rajada anônima, antes de haver identidade |
| Dependência | usuário | 120 fichas, 8/s | é o que de fato distingue pessoas |

Por IP é frouxo de propósito: atrás do NAT corporativo o escritório inteiro
compartilha um endereço, e apertar puniria todos pelo excesso de um.

Os números saem do uso real: um recorte do painel custa ~25 requisições, e quem
explora filtros faz vários recortes por minuto. Um teto de "60 por minuto"
quebraria a terceira mudança de filtro.

**Busca livre custa 5 fichas** em vez de 1: `ilike` com curinga à esquerda varre
trigrama, e é a consulta mais cara da API.

### O endereço do cliente

`ip_do_cliente` lê o `X-Forwarded-For` **da direita para a esquerda**, contando
`PROXIES_CONFIAVEIS`. Com zero, ignora o cabeçalho por completo e usa o endereço
da conexão — o padrão seguro, porque o cabeçalho é forjável.

Por isso o `Dockerfile` **não** usa `--proxy-headers`: o uvicorn
reescreveria `request.client.host` pela primeira entrada do XFF, que é a que o
cliente controla.

**Estado em memória, por processo.** Com mais de um worker o teto passa a valer
N vezes o configurado. Em produção quem dá o teto de verdade é a borda; um
worker mantém o comportamento local igual ao que os testes descrevem.

---

## 7. Papel restrito de banco

`painel_app` (migration `app/banco/migrations/0009_papel_da_aplicacao.sql`) — lê tudo, escreve nos
dados de negócio, apaga apenas linhas filhas de agregado, e **não** altera
auditoria nem autorização.

Nada disso impede injeção de SQL. O que muda é o TETO do estrago: com
superusuário, uma connection string vazada entrega o servidor (`copy ... to
program`, leitura de arquivo, `drop table`).

Dois pontos que parecem detalhe e não são:

- **`delete` nas linhas FILHAS é obrigatório.** As relações do ORM usam
  `delete-orphan`: tirar um tema ou trocar a frente emite `DELETE` de verdade.
  A suíte não pega isso porque roda como superusuário — quem cobre é
  `tests/test_papel_restrito.py`, que conecta como `painel_app`.
- **`alter default privileges` alcança tabelas futuras.** Evita "permission
  denied" em produção depois de uma migration nova, e é também por que as
  revogações de auditoria precisam ser explícitas: uma trilha nova nasceria
  gravável.

A conta de login é criada pela infraestrutura, com senha do Key Vault:

```sql
create role painel_api login password '<do Key Vault>';
grant painel_app to painel_api;
```

### Aplicar as migrations sem superusuário

No Postgres gerenciado do Azure a conta administrativa **não é superusuário**, e
isso muda duas coisas nas migrations:

- **Posse das funções.** 0005 e 0006 transferem a posse de funções
  `security definer` para roles próprias, e isso exige ser MEMBRO da role.
  Superusuário é membro de tudo implicitamente; uma conta comum com `CREATEROLE`
  não é. Os dois arquivos concedem a membria antes de transferir, com sintaxe
  diferente até o 15 (`grant X to Y`) e do 16 em diante (`... with set true`,
  porque a partir dali quem cria a role a recebe sem poder assumi-la).
- **CREATE no schema.** O novo dono precisa de `CREATE` em `public` no momento
  da transferência. É concedido para isso e revogado logo depois, no mesmo
  arquivo — a posse permanece e a role volta a não poder criar nada.

Conferido aplicando as 9 migrations num banco limpo nas versões 13, 14, 15, 16 e
18, como superusuário e como conta comum.

As quatro extensões precisam estar liberadas em `azure.extensions` antes da
primeira migration.

---

## 8. Mensagem de erro

`app/dominio/erros.py` e `app/api/erros.py`.

Quem é de **fora** recebe mensagem genérica; quem é da casa recebe a específica.
O log guarda a mensagem inteira nos dois casos, com uma `referencia` curta que
também vai na resposta — é o que liga a reclamação do usuário à linha do log.

Na dúvida sobre quem está pedindo (erro antes de a identidade ser resolvida), o
lado seguro é o genérico.

A exceção é o erro **sobre o pedido** (`sobre_o_pedido=True`): "Acesso externo
exige prazo" é sobre o que a pessoa mandou, e escondê-lo só a impediria de
corrigir.

Erro inesperado do banco nunca chega à tela: o filtro é por SQLSTATE, e não pela
primeira linha da mensagem — devolver a primeira linha entregaria nome de tabela
e de constraint.

---

## 9. Conferência de subida

`app/seguranca/verificacao_de_producao.py` **recusa iniciar** com configuração
insegura quando `AMBIENTE=producao`:

- `AUTH_MOCK` ligado
- origem sem `https`, ou apontando para loopback / rede privada (analisada, não
  procurada por substring)
- limite de taxa desligado, ou com número ≤ 0
- `BANCO_ECHO` ligado (o log vaporizaria os parâmetros das consultas)
- banco local, ou sem `sslmode`
- `SESSAO_SECRETA` ausente ou no valor padrão
- `ENTRA_*` incompletos

É o teste mais barato da pilha local: se a API sobe, a configuração passou.

---

## 10. O que NÃO existe

Escrito explicitamente para quem for continuar.

### Definido mas nunca aplicado

Os dois arquivos `.bicep` **não estão neste repositório** — ficam no repositório
do painel, em `seguranca/borda/` e `seguranca/dados/`. São definição de
infraestrutura que **não foi aplicada em nenhum ambiente**:

| Arquivo | O que define |
|---|---|
| `waf-limite-de-taxa.bicep` | Front Door + WAF: rate limit de borda, conjunto gerenciado |
| `postgres-e-segredos.bicep` | Postgres gerenciado com TLS obrigatório, Key Vault, PITR |

Enquanto não forem aplicados: não há WAF, não há rate limit de borda, e os
segredos são variável de ambiente.

### Não implementado

- **Administração de dicionários.** `papel.administra_dicionarios` existe e é
  devolvido em `/api/eu`, mas **nada o exige**: a API de catálogo só lê. É uma
  permissão sem barreira correspondente, e quem for implementar a escrita precisa
  passar a exigi-la.
- **Importação da planilha.** As tabelas existem (migration
  `app/banco/migrations/0008_importacao.sql`) e o desenho está documentado lá; não há rota, caso de
  uso nem tela.
- **Gerador de documento no servidor.** O relatório sai da impressão do
  navegador e o CSV é montado no cliente. O que existe é o REGISTRO da geração —
  trilha, não barreira: um cliente modificado baixa a listagem e monta o arquivo
  sem chamar a API.
- **Alertas ligados.** As consultas KQL vivem no repositório do painel, em
  `observabilidade/seguranca.kql`. Estão
  escritas e **os limiares não foram calibrados** contra volume real. Ligar
  notificação antes de calibrar produz alarme falso, e alarme falso é o que faz
  alguém desligar o alerta.

### Decisões de arquitetura em aberto

- **Serviço separado para concessão de acesso.** Hoje quem tem a credencial do
  banco concede o que quiser (§3). Separar exigiria um processo com credencial
  própria, e é a única mudança que fecharia isso de verdade.
- **Rate limit distribuído.** O estado é por processo (§6). Com mais de uma
  instância, o teto real é N vezes o configurado.

### Decisão de negócio em aberto

- **O externo enxerga `relato` e `pendencias`?** O mecanismo existe
  (`papel.ve_campos_sensiveis`, hoje `false` para o papel `externo`), mas qual
  parceiro recebe o quê é decisão de quem contrata.
