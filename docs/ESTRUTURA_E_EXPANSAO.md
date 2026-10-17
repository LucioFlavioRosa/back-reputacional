# A estrutura atual aguenta crescer?

**A pergunta.** O Painel Reputacional cresceu por fatias ao longo de meses, e vai
ganhar um módulo inteiro novo — a Inteligência de Mercado. A estrutura de hoje
facilita ou atrapalha manter o que existe e acrescentar o que vem?

**O método.** Tudo abaixo foi medido nos dois repositórios em 17/10/2026, não
inferido. Onde há opinião, ela está marcada como opinião.

---

## 1. O que existe hoje, medido

### O back tem camadas de verdade, e o domínio é puro — o resto se cruza

```
app/api/           23 módulos   rotas, esquemas de entrada e saída
app/casos_de_uso/  28 módulos   o que o sistema FAZ
app/dominio/       24 módulos   regra pura, sem banco e sem HTTP
app/banco/         33 módulos   tabelas, repositórios, consultas
app/seguranca/      8 módulos   identidade, sessão, limites
app/armazenamento/  2 módulos   blob
app/esquemas/       2 módulos
(raiz de app/)      3 módulos   configuração, observabilidade
```

**123 módulos**, e a varredura de inventário não achou **nenhum órfão**.

**O DOMÍNIO É PURO DE VERDADE, e isso é o ativo.** `app/dominio/` não importa
banco, FastAPI nem infraestrutura, e não há ciclo de import em lugar nenhum —
conferido estaticamente. É o que permite testar regra sem subir nada, e é de
onde vem a maior parte dos testes (2.276 numa execução registrada em 17/10/2026;
o número é de execução, não dedutível do disco).

**MAS AS OUTRAS TRÊS CAMADAS SE CRUZAM**, e a primeira versão deste documento
dizia que "as camadas são respeitadas", o que é falso:

```
banco/importar_cadastro_externo.py:71   from app.api.stakeholders import (...)
banco/importar_cadastro_externo.py:80   from app.casos_de_uso.derivar_tipo import ...
banco/carregar_pacote_das_lentes.py:28  from app.casos_de_uso.carga_do_pacote... import ...
api/lentes.py:34                        from app.api.score import _formula, _mes_de
api/consulta_profundidade.py:26         from app.api.score import _mes_de
```

A camada de baixo importa a de cima, e dois módulos de rota importam **funções
privadas** de um terceiro. Não há ciclo, mas há costura frouxa — e `_mes_de` com
dois consumidores externos não é mais privado, é uma função de domínio morando
no lugar errado.

### O front é meio organizado por domínio, e meio não

```
src/paginas/      25 arquivos na raiz + 7 subpastas por domínio
                  (score/ tem 55 arquivos, cadastro/ 11, importacao/ 7)
src/dominio/      37 arquivos, PLANO, sem subpasta
src/api/          1 arquivo: cliente.ts
src/graficos/     17 arquivos
src/componentes/  28 arquivos
```

`paginas/` já segue domínio. `dominio/` e `api/` não.

### Os arquivos grandes

| back | | front | |
|---|---|---|---|
| `casos_de_uso/importar_agendas.py` | 152 KB | `api/cliente.ts` | 100 KB |
| `banco/semear_enredos.py` | 141 KB | `paginas/Painel.tsx` | 82 KB |
| `api/lentes.py` | 103 KB | `paginas/Cadastro.tsx` | 69 KB |
| `api/score.py` | 74 KB | `dominio/derivacoes.ts` | 63 KB |

---

## 2. O que está funcionando, com evidência

### As entregas recentes tiveram superfície pequena — e isso prova menos do que parece

Arquivos por commit, últimos oito sem merge, medido em 17/10/2026:

| | em `origin/main` | em `HEAD` (inclui o não mesclado) |
|---|---|---|
| back | `3, 6, 7, 2, 5, 2, 4, 3` — mediana **3,5** | `1, 3, 10, 15, 3, 6, 7, 2` — mediana **4,5** |
| front | `1, 2, 2, 4, 10, 2, 2, 3` — mediana **2** | `4, 3, 8, 1, 2, 2, 4, 10` — mediana **3,5** |

**A PRIMEIRA VERSÃO DESTE DOCUMENTO DAVA SÓ A COLUNA DA ESQUERDA, sem dizer que
era `origin/main`** — e a revisão, medindo em `HEAD`, achou outros números e
concluiu, com razão, que a amostra estava mal descrita. Os dois são
reprodutíveis; o que faltava era a referência.

**E O QUE ISTO SUSTENTA É MENOS DO QUE EU ESCREVI.** A primeira versão dizia que
"isso contradiz a hipótese de que a estrutura está emperrando". Não contradiz.
O que os números sustentam é:

> As entregas recentes, feitas por quem conhece bem o código, tiveram superfície
> de alteração pequena.

Três vieses impedem ir além disso:

1. **quem mexeu sabia onde mexer.** Isso encurta a navegação, não o acoplamento;
2. **quem mexeu também escolheu e dividiu as tarefas** — um autor experiente
   quebra mudança difícil em commits pequenos, ou evita a área ruim;
3. **contar arquivos mede superfície, não dificuldade.** Mudar duas funções
   dentro de `lentes.py` pode custar mais compreensão do que mudar dez arquivos
   coesos.

**A medida que responderia de verdade** é outra: tempo até a mudança certa,
idas e voltas de revisão, defeitos depois da mudança, e — a mais honesta —
alguém que não conhece o código executando uma tarefa e sendo cronometrado.

A mediana fica aqui como **observação histórica**, não como prova de
manutenibilidade.

### A camada de domínio paga

`ingerir_mencoes.custo_da_leitura`, `jornadaDoIndice`, `recorte`,
`filtros_sql.condicoes` — regras densas, puras, testadas linha a linha. O degrau
de 8 MB (leitura de 47,5 s para 3,11 s) foi escrito e provado sem subir banco
nenhum. Isso é a camada fazendo o trabalho dela.

---

## 3. O que vai doer ao acrescentar um módulo novo

### 3.1 Um domínio não mora em lugar nenhum — mora em quatro

O Score, hoje:

| pasta | arquivos do Score |
|---|---|
| `app/api/` | 5 (`score`, `lentes`, `riscos`, `base_das_lentes`, `consulta_profundidade`) |
| `app/casos_de_uso/` | 7 |
| `app/dominio/` | 8 |
| `app/banco/` | 9 |

**29 arquivos, espalhados por quatro pastas, misturados com os 26 do CRM.**

Quem chega para mexer no Score precisa saber quais 29 dos 123 são dele, e a única
coisa que diz isso é o nome do arquivo. Funciona enquanto os nomes forem bons —
e eles são, em geral —, mas já falha nas bordas: `ler_planilha_de_agendas` é do
CRM apesar de "planilha", e `temas_da_mencao` e `vocabulario_de_temas` moram em
camadas diferentes com nomes quase iguais.

**Acrescentar a Inteligência de Mercado na estrutura de hoje significa espalhar
mais cinco a oito arquivos pelas mesmas quatro pastas**, e `casos_de_uso/` passa
de 28 para ~35 módulos de três produtos diferentes.

Nada quebra. O custo é de navegação, e ele é cobrado toda vez que alguém novo
precisa entender uma parte.

### 3.2 `cliente.ts` é o gargalo diário do front

**90 funções, 2.481 linhas, um arquivo.** Toda chamada de API do produto inteiro
mora ali.

Evidência concreta e recente: neste mesmo dia eu editei `cliente.ts` em **três
PRs diferentes** — a subida em partes, o limiar de 1,2 MB e a remoção da senha.
São três funcionalidades sem nenhuma relação entre si disputando o mesmo arquivo.

É o ponto da estrutura onde duas pessoas trabalhando em paralelo colidem
primeiro, e onde o módulo novo vai entrar também.

### 3.3 A conta mora em dois lugares, e os dois discordam

`src/dominio/derivacoes.ts` (63 KB) calcula KPIs, séries e mapa **no navegador**,
sobre no máximo **5.000 registros** (`cliente.ts:533`). O back tem quatro rotas
que fazem a mesma conta sobre o recorte SQL inteiro — `/api/metricas/kpis`,
`/resolutividade`, `/serie-mensal`, `/mapa` — e **nenhuma é chamada**.

Acima de 5.000 interações o painel mostra número parcial. O front avisa
(`Painel.tsx:631`) e exibe assim mesmo.

**Este é o único achado desta revisão com efeito no que a pessoa lê.** E o
enquadramento certo é: acima de 5.000 o número é PARCIAL, e a tela avisa. Se o
produto exige o recorte inteiro, é defeito; se o teto é decisão, é limitação
declarada — e hoje não é nem uma coisa nem outra, é esquecimento. A decisão
ainda precisa ser tomada.

### 3.4 Os arquivos que passaram do ponto — e os piores não são os maiores

`casos_de_uso/importar_agendas.py` (152 KB, 3.258 linhas) e `paginas/Painel.tsx`
(82 KB) não cabem na cabeça de ninguém de uma vez. Não estão quebrados — a suíte
os cobre.

**MAS O PROBLEMA ESTRUTURAL MAIOR ESTÁ EM OUTROS DOIS, que a primeira versão
deste documento não citou:**

| | tamanho | o que acumula |
|---|---|---|
| `api/lentes.py` | 103 KB, 2.403 linhas | três rotas + montagem de resposta + KPIs + consulta + regra de CRM e de Score |
| `api/score.py` | 74 KB, 1.853 linhas | 17 funções de rota + modelos + auxiliares |

A diferença em relação ao `importar_agendas` é que estes dois **são a camada de
rota fazendo trabalho de três camadas** — e são eles que exportam as funções
privadas que `lentes.py` e `consulta_profundidade.py` importam de volta (§1).
Tamanho ali é sintoma; a causa é responsabilidade acumulada.

---

## 4. O que eu recomendo

Em ordem de retorno sobre esforço. **Nenhuma delas é reorganização geral**, e
isso é deliberado: a medição da seção 2 mostra que a estrutura atual não está
emperrando a manutenção. Reorganizar 123 módulos para resolver um problema de
navegação seria pagar caro por pouco, e com risco.

### 4.1 Nascer certo: o módulo novo organizado por domínio

**O que:** a Inteligência de Mercado nasce em `app/inteligencia_de_mercado/`,
com as suas próprias `api/`, `casos_de_uso/`, `dominio/` e `banco/` dentro.

**"CUSTA ZERO" ESTAVA ERRADO, e era o que a primeira versão dizia.** Criar a
pasta custa quase nada; **integrá-la não**. O que a revisão levantou, conferido:

| custo | onde |
|---|---|
| rota não é descoberta sozinha: precisa ser importada e registrada | `main.py:154` |
| o teste de segurança mantém lista de prefixos de rota | `protecao_http.py` |
| base declarativa é ÚNICA — a tabela nova entra no mesmo `Tabela.metadata` e precisa ser importada para mapear | `banco/sessao.py:16` |
| migrations são uma coleção PLANA, montada por Docker, pipeline e script | `app/banco/migrations/` |
| o pytest do back só procura em `tests/` | — |
| autorização é compartilhada: o portal novo passa pelas dependências globais | `dependencias.py` |

Estimativa da revisão: **1 a 3 dias de integração** antes de qualquer lógica do
módulo. E o repositório passa a ter duas convenções convivendo, o que tem custo
recorrente de navegação e de revisão.

**POR QUE EU AINDA RECOMENDO, com a condição abaixo:** o módulo é novo, e é o
único momento em que a escolha é livre. Mas só vale como laboratório **se tiver
critério de saída** — senão não é experimento, é uma segunda convenção
permanente, que é pior do que qualquer uma das duas sozinha.

**AS CONDIÇÕES, e elas não são opcionais:**

- base `Tabela` única, migrations na pasta plana de sempre, registro explícito
  de rota e autorização compartilhada — **a pasta agrupa código, não duplica
  infraestrutura**;
- declarar de quê o módulo pode depender para fora dele;
- **medir em um ou dois meses**: tempo para localizar, pastas tocadas por
  entrega, quantas vezes foi preciso sair da pasta.

**E UMA RESSALVA QUE MUDA A DECISÃO:** se a Inteligência de Mercado depender
muito do Score (e a aba de bonds depende — menção, taxonomia, lente, impacto no
score), ela **não é um módulo de fronteira independente**. Nesse caso o
agrupamento rende pouco e o certo é pôr o código específico nas camadas
existentes, com nome claro. Isso se decide ao escrever a primeira fatia, não
agora.

### 4.2 Quebrar o `cliente.ts` por domínio

**O que:** `api/cliente.ts` vira `api/crm.ts`, `api/score.ts`, `api/acesso.ts`,
`api/importacao.ts`, `api/mercado.ts` — e um `api/requisitar.ts` com o que todos
usam (`requisitar`, `comTentativas`, o tratamento de erro).

**Por quê:** é mecânico, de risco baixo (o `tsc` prova), e paga todo dia. Acaba
com a colisão de três PRs no mesmo arquivo.

**Opinião:** esta é a que eu faria primeiro se só pudesse fazer uma.

### 4.3 Decidir onde a conta mora

**O que:** ou o front passa a chamar `/api/metricas/*` e `derivacoes.ts` encolhe,
ou as quatro rotas saem e o limite de 5.000 vira limite declarado do produto.

**Por quê:** hoje não é escolha, é esquecimento — e custa número errado acima de
5.000 registros.

**Opinião:** o back está certo. A conta sobre o recorte inteiro é dele, e o
front devia desenhar o que recebe. Mas isso é mudança de comportamento, não
refatoração, e precisa de decisão do produto antes.

### 4.4 Agrupar `src/dominio/` quando passar de 40

**O que:** 37 arquivos planos ainda se acham. Quando o módulo novo entrar, vale
a mesma divisão por domínio que `paginas/` já tem.

**Por quê:** não é urgente. Está aqui para não ser esquecido.

---

## 5. O que eu NÃO mudaria

**O domínio puro e a ausência de ciclos.** São o ativo real, e qualquer
reorganização tem de preservá-los.

Mas NÃO pelo motivo que a primeira versão deu ("as camadas são respeitadas") —
elas não são, e os cinco imports cruzados da §1 provam. Os crossings entre api,
casos de uso e banco são dívida localizada, a tratar quando se tocar na área, e
não justificativa para deixar tudo como está.

**Os comentários que registram DECISÃO.** Nesta sessão eles pagaram três vezes:
o de `acesso.py` previu a remoção da senha e pôs a conferência no lugar certo; o
de `test_recusa_de_login` disse qual teste sairia junto; o de `GraficoDeLinha` já
tinha decidido que ausência não é zero — a regra exata que a base de bonds vai
precisar.

MANTER NÃO É ABSOLUTO, e a primeira versão deixou soar assim. Vale manter o que
registra invariante, motivo de decisão, consequência de mudar, limite de
segurança ou de desempenho. Não vale manter o que narra o código, repete
histórico ou descreve implementação que já mudou — comentário longo também
envelhece e vira uma segunda arquitetura falsa. Esta sessão achou quatro desses
(a senha na 0003, a importação na 0008, as rotas no handoff, os números do
README).

**Quebrar `importar_agendas.py` agora.** Ele é grande e incomoda, mas está
coberto e estável, e não é necessário para a Inteligência de Mercado. Quebrá-lo
sem uma mudança de produto que justifique é mexer em código que funciona.

Isso não quer dizer que esteja saudável: são 3.258 linhas concentrando leitura,
mapeamento, validação, resolução de conflito, criação e confirmação. Quando uma
mudança tocar esse fluxo, vale dividir pelos seams que já existem conceitualmente
— estimativa de 1 a 3 dias, com teste.

**Fazer tudo de uma vez.** A medição diz que a manutenção está barata. Uma
reorganização geral trocaria um custo pequeno e conhecido por um risco grande e
desconhecido.
