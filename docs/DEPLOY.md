# Publicar o Painel Reputacional no Azure

O que a aplicação espera do ambiente, o que ainda precisa ser decidido, e em que
ordem as coisas acontecem. Vale para os dois repositórios.

**A infraestrutura é Terraform e mora fora destes repositórios.** Ela cria o
Postgres Flexible Server, a conta de Storage, o Container Apps Environment com
três aplicações — front, back e o job de migrations —, o registro de imagens, o
App Registration e as identidades gerenciadas.

---

## O princípio: não há segredo para guardar

Nenhuma senha, chave ou segredo de cliente viaja em variável de ambiente. As
três coisas que exigiriam um segredo se resolvem pela **identidade gerenciada**
do contêiner:

| O que | Como se autentica |
|---|---|
| Postgres | token do Entra ID **no lugar da senha**, renovado a cada conexão |
| Blob Storage | credencial da identidade; a chave da conta está **desligada** |
| SSO (troca do `code`) | `client_assertion` assinada para a identidade |

É o que permite que a conta de Storage tenha `shared_access_key_enabled = false`
e que o `BANCO_URL` chegue sem senha. Um segredo a menos é um segredo que não
vaza, não vence e não precisa ser rotacionado.

A porta de entrada disso tudo é `AZURE_CLIENT_ID`, que o Terraform injeta com o
client id da identidade do back: ela diz QUAL identidade usar. Sem ela, o SDK
procuraria a identidade do sistema, que não existe neste desenho.

A variável, sozinha, **não** quer dizer identidade gerenciada — ela também
nomeia o cliente de um service principal, ao lado de `AZURE_TENANT_ID` e de um
segredo. Por isso o código olha o conjunto: com tenant e segredo ao lado, o
ambiente é um CI, e vale a cadeia de credenciais.

---

## O que o código já faz

Estas cinco mudanças estão aplicadas. Nenhuma delas muda o ambiente local: a
pilha do `docker-compose.pilha.yml` continua com senha no Postgres, cadeia de
conexão no Azurite e SSO desligado.

**1. `app/seguranca/identidade_azure.py`** — a credencial, num lugar só, com um
token por escopo renovado cinco minutos antes de vencer.

Neste deploy a credencial é `ManagedIdentityCredential`, **determinística**, e
não `DefaultAzureCredential`: a cadeia do segundo custa latência a cada elo que
falha antes do certo, esconde a causa no fim da cadeia e pode autenticar como
outra identidade se sobrar variável de ambiente. Num CI com service principal,
ou na máquina de quem desenvolve com `az login`, vale a cadeia. E quando o
token é recusado, a mensagem diz o que conferir — em ordem —, em vez de chegar
como "autenticação falhou" do Postgres.

**2. `app/banco/sessao.py`** — URL com usuário, **sem** senha e num servidor
`*.postgres.database.azure.com` significa autenticação por Entra ID: um ouvinte
`do_connect` põe o token como senha ao abrir cada conexão. Fora disso nada
acontece e o `azure-identity` nem é importado — inclusive num Postgres local sem
senha, que é legítimo (`trust`, autenticação por par, `.pgpass`).
`pool_pre_ping=True` é o que faz o resto funcionar: o token só é conferido no
login, então conexão velha no pool continua válida.

**3. `app/armazenamento/blob.py`** — `_servico()` escolhe pelo formato do
endereço: `https://` é conta do Azure com credencial; qualquer outra coisa é
cadeia de conexão do Azurite.

**4. `app/seguranca/oidc.py`** — sem segredo, a troca do `code` manda
`client_assertion`. Com segredo, manda o segredo. Nunca os dois.

**5. Front (`nginx.conf` e `Dockerfile`)** — o nginx serve `/api/` da **mesma
origem**, encaminhando para o ingress interno do back. Sem CORS, com cookie de
primeira parte. O arquivo mora em `/etc/nginx/templates/` porque
`${API_UPSTREAM}` só existe quando o contêiner sobe, e só essa variável é
substituída (`NGINX_ENVSUBST_FILTER`) — as do nginx, como `$host`, ficam de
fora. Sem a variável, vale o padrão da pilha local; com ela **vazia**, o
contêiner recusa subir dizendo o que falta, em vez de morrer num "invalid
number of arguments" do nginx.

A conferência de subida acompanhou: falta de segredo **não** bloqueia mais, mas
falta de segredo **e** de identidade bloqueia — sem uma das duas não há como
provar ao tenant que somos o cliente registrado.

---

## O que ainda precisa ser resolvido na infraestrutura

**Use a cópia mais nova do Terraform.** A que estiver com
`pgaadauth_create_principal(nome, …)` no `scripts/migrar.py` resolve o principal
pelo NOME via Microsoft Graph, e essa consulta é bloqueada por acesso
condicional no tenant. A versão correta usa
`pgaadauth_create_principal_with_oid(...)` e recebe `PRINCIPAL_DA_APLICACAO_OID`
no job. Sem isso, o job falha exatamente no passo que dá acesso ao back.

**`PROXIES_CONFIAVEIS` precisa ser medido, não adivinhado.** O back lê
`X-Forwarded-For` da direita e devolve a N-ésima entrada. Com a cadeia que a
infraestrutura descreve — `cliente, ingress-do-front, nginx` — o valor é **3**;
com `2`, a chave do limite de taxa vira o IP do ingress e **todos os usuários
compartilham o mesmo balde**: um cliente barulhento devolve 429 para os outros.
Erra para o mesmo lado se o valor for alto demais. Registre o cabeçalho cru numa
requisição depois do primeiro deploy e fixe o número pelo que aparecer.

**O estado do Terraform está local.** O `backend "azurerm"` vem comentado, e é
dentro desse estado que nasce o `SESSAO_SECRETA`. Perder o arquivo é perder o
controle da stack e o segredo junto.

**Não há alerta nenhum.** Existe Log Analytics e Application Insights, e nenhum
`diagnostic_setting`, alerta ou action group: crash loop, enxurrada de 5xx e
falha do job de migrations dependem de alguém abrir o log.

**Três decisões de dado**, hoje herdadas do padrão: retenção de backup de 7
dias, geo-redundância desligada, e `max_replicas = 2` no back — que dobra o teto
do limite de taxa, porque o balde é por processo.

**Antes de ligar HSTS no front, decida sobre os subdomínios.** O `Dockerfile`
acrescenta `includeSubDomains` sempre que `HSTS` não é `off`; o backend trata as
duas coisas separadamente (`HSTS_INCLUIR_SUBDOMINIOS`) porque num domínio
compartilhado a diretiva alcança irmãos que talvez não estejam prontos para
HTTPS obrigatório. Em `*.azurecontainerapps.io` a questão não aparece, porque
HSTS fica desligado; num domínio próprio da Aegea, aparece.

---

## A ordem das coisas

```bash
cp terraform.tfvars.example terraform.tfvars   # subscription_id e tenant_id
terraform init
terraform validate                             # antes do plan, sempre
terraform plan
terraform apply                                # ~15 min; o Postgres é o lento
```

Os Container Apps sobem com a imagem de exemplo da Microsoft: o front mostra
uma página de placeholder e a API responde 504 até o passo seguinte.

```bash
# 1. publicar as imagens  (`terraform output comandos` imprime com os nomes reais)
az acr build -r <acr> -t back-reputacional:dev .          # no back-reputacional
az acr build -r <acr> -t front-reputacional:dev \         # no front-reputacional
  --build-arg VITE_API_URL= \
  --build-arg VITE_APPINSIGHTS_CONNECTION_STRING="$(terraform output -raw appinsights_connection_string)" .

az containerapp update     -g <rg> -n ca-back-…       --image <acr>.azurecr.io/back-reputacional:dev
az containerapp update     -g <rg> -n ca-front-…      --image <acr>.azurecr.io/front-reputacional:dev
az containerapp job update -g <rg> -n caj-migracoes-… --image <acr>.azurecr.io/back-reputacional:dev

# 2. migrations, e o acesso do back ao banco
az containerapp job start          -g <rg> -n caj-migracoes-…
az containerapp job execution list -g <rg> -n caj-migracoes-… -o table
```

**`VITE_API_URL` vazio não é descuido**: é o que faz o painel chamar a API na
mesma origem, e o que deixa a CSP fechar em `connect-src 'self'`. Um valor aqui
aponta o bundle para outro host e a CSP passa a permitir esse host.

**Os dois `Dockerfile` não podem usar sintaxe de BuildKit** — `# syntax=`,
`RUN --mount`, `COPY --link`, heredoc. O `az acr build` não a entende, e hoje
nenhum dos dois usa. Quem acrescentar quebra a publicação da imagem, e o erro
aparece no build remoto, não na máquina de quem escreveu.

O job de migrations entra no Postgres como administrador Entra, aplica os `.sql`
em ordem, registra em `migracao_aplicada`, cria o principal do back no banco e o
põe em `painel_app`. Pode rodar quantas vezes quiser.

**3. O App Registration passa pela administração do tenant.** O back só sobe
depois que `entra_client_id` estiver preenchido — sem ele a conferência de
subida bloqueia, e com razão: sem client id ninguém entra.

**4. O primeiro administrador é manual, e é um passo consciente.** Com SSO, a
pessoa é provisionada no primeiro login e nasce **sem papel**. Alguém precisa
dar o primeiro `UPDATE` por `psql`. A auditoria vai registrar `concedido_por =
null` e `origem = postgres` — o banco dizendo "isto não veio por uma tela". Daí
em diante tudo passa pela tela de Acessos, que registra o autor. O porquê de não
semear isso numa migration está em [`SEGURANCA.md`](SEGURANCA.md), seção 10.

---

## O que conferir depois de subir

| O quê | Como |
|---|---|
| a API subiu | `GET /api/saude` pela URL do front |
| o token do Postgres funciona | qualquer tela que liste dados; falha aqui aparece como "autenticação falhou" para um usuário sem senha |
| o blob responde | subir um material numa agenda |
| o SSO fecha o ciclo | entrar pela tela; a falha do `client_assertion` aparece só na volta do `code` |
| o limite de taxa mede o cliente certo | ver `PROXIES_CONFIAVEIS` acima |
| o log da subida | os avisos que não bloqueiam saem ali, inclusive "SSO por credencial federada" |

---

## O que continua não existindo

Está no [README](../README.md), em "O que não existe", e nada disto muda com o
deploy: importação da planilha, geração de documento no servidor, verificação de
tipos, e limite de taxa distribuído.

E uma coisa que **precisa deixar de existir** antes de qualquer ambiente
compartilhado: a entrada por e-mail e senha. Ela é temporária, existe porque o
SSO depende do tenant, e a lista do que remover está em
[`SEGURANCA.md`](SEGURANCA.md), seção 10.
