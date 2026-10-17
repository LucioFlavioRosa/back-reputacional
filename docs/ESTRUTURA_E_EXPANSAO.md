# A estrutura atual aguenta crescer?

**A pergunta.** O Painel Reputacional cresceu por fatias ao longo de meses, e vai
ganhar um módulo inteiro novo — a Inteligência de Mercado. A estrutura de hoje
facilita ou atrapalha manter o que existe e acrescentar o que vem?

**O método.** Tudo abaixo foi medido nos dois repositórios em 17/10/2026, não
inferido. Onde há opinião, ela está marcada como opinião.

---

## 1. O que existe hoje, medido

### O back tem camadas de verdade, e elas são respeitadas

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

Isso não é pouco. A separação `dominio/` sem banco e sem HTTP é o que permite
testar regra sem subir nada, e é de onde vem a maior parte dos 2.276 testes.

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

### Mudança incremental é barata

Arquivos tocados pelas últimas oito entregas de cada repositório:

```
back:   3, 6, 7, 2, 5, 2, 4, 3      mediana 3,5
front:  1, 2, 2, 4, 10, 2, 2, 3     mediana 2
```

**Isso contradiz a hipótese de que a estrutura está emperrando.** Para mexer no
que existe, o acoplamento é baixo e o caminho é curto. Uma correção de
comportamento custa dois ou três arquivos.

A única entrega de dez arquivos foi a que atravessou três níveis de taxonomia na
tela — e dez para isso é razoável.

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

**Este é o único achado desta revisão que entrega número errado a quem usa.** E
é decisão de arquitetura, não sujeira: onde a conta deve morar.

### 3.4 Dois arquivos passaram do ponto

`casos_de_uso/importar_agendas.py` com 152 KB e `paginas/Painel.tsx` com 82 KB
não cabem na cabeça de ninguém de uma vez. Não estão quebrados — a suíte os
cobre —, mas são onde uma mudança leva mais tempo para ser entendida do que para
ser feita.

---

## 4. O que eu recomendo

Em ordem de retorno sobre esforço. **Nenhuma delas é reorganização geral**, e
isso é deliberado: a medição da seção 2 mostra que a estrutura atual não está
emperrando a manutenção. Reorganizar 123 módulos para resolver um problema de
navegação seria pagar caro por pouco, e com risco.

### 4.1 Nascer certo: o módulo novo organizado por domínio

**O que:** a Inteligência de Mercado nasce em `app/inteligencia_de_mercado/`,
com as suas próprias `api/`, `casos_de_uso/`, `dominio/` e `banco/` dentro.

**Por quê:** é o único momento em que isso custa zero. O módulo não existe; pôr
os arquivos dele numa pasta própria em vez de espalhá-los não dá trabalho nenhum
a mais — e dá, de graça, a resposta para "onde mora a Inteligência de Mercado".

**E vira o laboratório.** Se depois de um ou dois meses a navegação por domínio
se mostrar melhor, há um exemplo funcionando no mesmo repositório para migrar o
Score e o CRM — e, se não se mostrar, o custo de desfazer é uma pasta.

**O que NÃO muda:** as camadas. `api → casos_de_uso → dominio → banco` continua
valendo dentro da pasta do módulo. A mudança é de agrupamento, não de desenho.

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

**As camadas do back.** Elas funcionam, são respeitadas, e são de onde vem a
testabilidade. A crítica da seção 3.1 é de agrupamento, não de camada.

**Os comentários longos.** Eles são densos e explicam o porquê, não o quê — e
nesta sessão eles pagaram três vezes: o comentário de `acesso.py` previu a
remoção da senha e pôs a conferência no lugar certo; o de `test_recusa_de_login`
disse qual teste sairia junto; o de `GraficoDeLinha` já tinha decidido que
ausência não é zero, que é exatamente a regra que a base de bonds vai precisar.
O custo deles é real, e o retorno também.

**Quebrar `importar_agendas.py` agora.** Ele é grande e incomoda, mas está
coberto e estável. Quebrá-lo sem uma mudança de produto que justifique é mexer
em código que funciona.

**Fazer tudo de uma vez.** A medição diz que a manutenção está barata. Uma
reorganização geral trocaria um custo pequeno e conhecido por um risco grande e
desconhecido.
