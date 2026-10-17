# A estrutura atual aguenta crescer?

**A pergunta.** O Painel Reputacional cresceu por fatias ao longo de meses, e vai
ganhar um módulo inteiro novo — a Inteligência de Mercado. A estrutura de hoje
facilita ou atrapalha manter o que existe e acrescentar o que vem?

**O método.** Tudo abaixo foi medido nos dois repositórios em 17/10/2026, não
inferido. Onde há opinião, ela está marcada como opinião.

> **O QUE JÁ FOI FEITO DEPOIS DESTE DOCUMENTO** — ver §6, no fim, para o que
> mudou, o que a medição derrubou de novo e o que virou teste em vez de
> afirmação. Duas recomendações daqui (§4.2 e a dívida da §1/§5) estão
> aplicadas; as outras duas continuam abertas.

---

## 1. O que existe hoje, medido

### O back tem camadas de verdade, e o domínio é puro — o resto se cruza

```
app/api/           23 módulos   rotas, esquemas de entrada e saída
app/casos_de_uso/  28 módulos   o que o sistema FAZ
app/dominio/       24 módulos   regra pura, sem banco e sem HTTP
app/banco/         33 módulos   tabelas, repositórios, consultas  ← HOJE SÃO 23
app/seguranca/      8 módulos   identidade, sessão, limites
app/armazenamento/  2 módulos   blob
app/esquemas/       2 módulos
(raiz de app/)      3 módulos   configuração, observabilidade
```

**123 módulos**, e a varredura de inventário não achou **nenhum órfão**.

> **ESTE QUADRO É DA DATA DO DOCUMENTO, e uma linha dele já mudou no mesmo dia:**
> `app/banco/` tem **23** módulos, não 33 — os 10 scripts de linha de comando
> saíram para `app/comandos/` (§6.2). A revisão do Codex pegou o número
> desatualizado aqui, e pegou bem: quem lê a seção 1 de cima para baixo encontra
> "33" antes de chegar ao §6, e acredita. Pelo mesmo motivo a tabela de arquivos
> grandes mais abaixo ainda diz `banco/semear_enredos.py`, cujo caminho hoje é
> `comandos/semear_enredos.py`.
>
> Os números desta seção ficam como MEDIÇÃO DAQUELE DIA — reescrevê-los apagaria
> o antes de que o §6.4 depende para comparar. O que não pode é o leitor não
> saber disso, e é o que esta nota resolve.

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
banco/semear_referencias.py:29          from app.armazenamento import ...
api/lentes.py:34                        from app.api.score import _formula, _mes_de
api/consulta_profundidade.py:26         from app.api.score import _mes_de
```

A camada de baixo importa a de cima, e dois módulos de rota importam **funções
privadas** de um terceiro. Há costura frouxa — e `_mes_de` com dois consumidores
externos não é mais privado, é uma função de domínio morando no lugar errado.

> **ESTA LISTA FOI CORRIGIDA DEPOIS.** Ela tinha cinco linhas e a quarta acima
> (`semear_referencias`) faltava — a verificação que eu rodei à mão não a pegou.
> E o enquadramento das três primeiras estava errado: os três arquivos são
> COMANDOS de linha, não camada de banco. Ver §6.

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
| `casos_de_uso/importar_agendas.py` | 152 KB | `api/cliente.ts` (hoje dividido, §6.1) | 100 KB |
| `banco/semear_enredos.py` (hoje `comandos/`) | 141 KB | `paginas/Painel.tsx` | 82 KB |
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

> **ESTA RECOMENDAÇÃO ESTÁ RETIRADA, e o motivo é medição — ver §7.6.** O limiar
> foi alcançado (40 arquivos em 17/10/2026) e aí eu medi o GRAFO DE IMPORTS em
> vez da contagem: **27 dos 40 formam um único componente conexo**. Não há
> costura. A contagem de arquivos era a medida errada.

---

## 5. O que eu NÃO mudaria

**O domínio puro e a ausência de ciclos.** O domínio puro é o ativo real, e
qualquer reorganização tem de preservá-lo.

**"A AUSÊNCIA DE CICLOS" ERA FALSA TAMBÉM, e só se descobriu quando a
verificação virou teste (§6):** existe um ciclo, `tabelas_interacoes` ↔
`tabelas_referencias`, deliberado e documentado no próprio arquivo — quem
declara a chave estrangeira traz o alvo junto, senão um processo que importe só
um dos dois quebra na primeira consulta com `NoReferencedTableError`. O import
mora no fim do arquivo com `noqa: E402`, que é o que o resolve. É dívida de
mapeamento ORM, não de arquitetura — mas eu afirmei "nenhum ciclo em lugar
nenhum", e não era verdade.

E NÃO pelo motivo que a primeira versão deu ("as camadas são respeitadas") —
na data deste documento elas não eram, e os imports cruzados da §1 provam. Hoje
são, por mudança e por teste; ver §6.

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

---

## 6. O que foi feito, e o que a medição derrubou de novo

Tudo nesta seção é de 17/10/2026, depois do documento acima.

### 6.1 Feito: o `cliente.ts` se dividiu (§4.2)

`src/api/cliente.ts` — 90 funções, 2.481 linhas — virou cinco arquivos por
domínio (`nucleo`, `acesso`, `crm`, `score`, `importacao`), com `cliente.ts`
como barril de reexportação. Os 66 arquivos que importam de `@/api/cliente`
não mudaram. A revisão comparou AST contra AST: **162 declarações antes, 162
depois**, zero diferença de assinatura, corpo ou valor.

Ela também achou dois buracos que eu havia aberto, e os dois estão fechados: a
varredura aceitava `requisitar` renomeada no import (deixando chamadas sem
varredura nenhuma) e a lista de arquivos varridos era escrita à mão (um sexto
arquivo em `src/api/` escaparia em silêncio; agora é `import.meta.glob`).

### 6.2 Feito: os comandos saíram de `app/banco/`, e três "violações" eram diagnóstico errado meu

**O QUE A MEDIÇÃO MOSTROU.** `app/banco/` tinha 33 módulos, e **10 deles eram
script de linha de comando** (`python -m …`, com `__main__`). As outras seis
pastas de `app/` tinham **zero**. A pasta significava duas coisas: a camada que
fala SQL e os scripts que a operam.

**E ISSO DERRUBA TRÊS DAS QUATRO VIOLAÇÕES DA §1.** `importar_cadastro_externo`,
`carregar_pacote_das_lentes` e `semear_referencias` não eram dívida de camada:
um PONTO DE ENTRADA pode importar qualquer camada — é o que `main.py` faz. O
problema era a pasta, não o import. Eu os listei como costura frouxa porque
olhei o import e não o arquivo.

Nove saíram para `app/comandos/`, com o ajudante que só eles usam
(`temas_de_demonstracao.py`). Dois ficaram, cada um com motivo:

| fica em `app/banco/` | por quê |
|---|---|
| `sugerir_categoria_de_publico.py` | tem `__main__`, mas `derivados.py` usa as funções dele: é camada com CLI colado, não comando |
| `derivados.py` | é o espelho em Python das migrations 0043/0044, que moram em `app/banco/migrations/`, e `test_derivados` confere que os dois dizem a mesma coisa. Separar o par seria pior do que o cheiro de ser usado só por semeador |

**O risco real da mudança não era o import, era a string.** Caminho de módulo
escrito em prosa — um `python -m` apontando para a pasta antiga — não é
conferido por compilador nenhum: mover o arquivo deixa 26 instruções quebradas
em README, compose e docstrings, esperando a próxima pessoa que for semear um
banco. E duas delas tinham alcance pior. A primeira: `tests/test_semeadores.py`
usava `from app.banco import semear_desenvolvimento, …` — a forma em que o nome
do submódulo está em `names` e não no nó do import, que a minha varredura de
substituição não cobria. Ela passou, e **a suíte a pegou**. É o MESMO ponto cego
que já tinha me enganado meia hora antes, numa análise de dependência que
mostrou um módulo usado como se fosse órfão. A segunda, essa a suíte **não**
pegaria: `amostra_de_desenvolvimento.json` é carregado por
`Path(__file__).with_name(...)` e estava declarado como dado do pacote
`app.banco` no `pyproject.toml` — deixar a declaração para trás instalaria o
wheel sem o arquivo, e o semeador quebraria **só numa instalação real**, nunca
na suíte nem no container.

Por isso a mudança trouxe `test_os_comandos_sao_pontos_de_entrada.py`, que
confere que todo `python -m` documentado aponta para um módulo que existe.

**E ELE PEGOU DUAS COISAS NA PRIMEIRA EXECUÇÃO.** A primeira foi este próprio
documento: uma versão anterior deste parágrafo citava, como exemplo de caminho
morto, o `python -m` que `infra-reputacional/ajustes/back/AJUSTES.md` documenta
para o migrador — e que aponta para `app.banco.migrar`, um módulo que não
existe, porque `migrar.py` mora em `infra-reputacional/scripts/`. O exemplo
literal virou, ele mesmo, um caminho quebrado dentro do alcance da varredura.
Está descrito em prosa por isso. **No repositório de infra o teste não alcança,
e aquele caminho continua errado lá** — é a demonstração mais barata de por que
a verificação precisa ser executável.

A segunda foi `tests/test_informacao_sensivel_por_pessoa.py`, que mantém uma
lista de exceção **por caminho** dos módulos que leem `interacao` sem decidir
sobre a marca de restrição. Os três semeadores caíram fora dela ao mudar de
pasta, e a suíte falhou — o comportamento certo. Uma lista de exceção de
segurança que seguisse valendo depois de o arquivo mudar de lugar seria pior do
que não existir.

### 6.3 Feito: `_mes_de` e `_formula` saíram da rota (§1, §5)

As duas violações que eram violações de verdade. `_mes_de` virou
`dominio.periodo.mes_de`; `_formula` virou `dominio.score.formula_aplicada`, no
módulo onde `REGUAS_DE_TIER` e `Calibracao` já moravam — a mudança **tirou** um
import em vez de acrescentar.

E rendeu cobertura que não existia: `formula_aplicada` **não tinha teste nenhum**,
nem direto nem por HTTP, e é o texto que explica na tela como o número foi
feito — o risco dele é não quebrar quando erra, só descrever uma régua que não
rodou. Os casos de recusa de `mes_de` só eram exercitados por rota, em teste que
precisa de Postgres; agora se provam puros, e um deles mudou de lugar com
motivo: `99999-01` passa do ano máximo do próprio `date` (9999), morre no parse
e devolve a mensagem de FORMATO, não a de faixa. O teste por HTTP agrupava os
cinco casos e conferia só o 422, então não distinguia as duas mensagens.

### 6.4 Medido depois: antes e depois, no mesmo script

| | antes (`origin/main`) | depois |
|---|---|---|
| violações de camada | **4** | **0** |
| imports de nome privado entre arquivos | 5 | **3** |
| ciclos de import | **1** (eu afirmei 0) | 1, nomeado e explicado |
| módulos em `app/banco/` | 33 (10 eram script) | 23, só camada |

Os três cruzamentos privados que sobraram estão nomeados um por um em
`CRUZAMENTOS_CONHECIDOS`. O maior deles — `importar_cadastro_externo` usando
`_conferir_area`, `_conferir_categoria_publico` e `_conferir_tier` de
`api/stakeholders.py` — **não** é o caso do `_mes_de`: as três recebem `Sessao` e
consultam o catálogo, então não são domínio puro. A casa certa delas (`banco`
ou `casos_de_uso`) é outra mudança, com os testes de erro na frente.

### 6.5 O que mudou de método: a afirmação virou teste

**É o item mais importante desta seção.** Duas afirmações de arquitetura deste
documento eram falsas — "as camadas são respeitadas" e "não há ciclo em lugar
nenhum" —, e as duas foram escritas por mim depois de uma verificação à mão que
eu achei suficiente. A primeira foi corrigida por uma revisão; a segunda só
caiu quando a verificação virou código.

`tests/test_as_camadas_sao_respeitadas.py` agora mede a cada execução: a tabela
de quem pode importar quem, o domínio não conhecendo ninguém, nenhum ciclo
novo, nenhum nome privado novo atravessando arquivo. As exceções são nomeadas
uma a uma com o motivo, e são **teto, não piso** — a lista recusa uma entrada
nova e recusa também uma que deixou de acontecer, para não virar cemitério.

### 6.6 O que continua aberto

- **§4.1, o módulo novo por domínio**: continua sendo decisão da primeira fatia
  da Inteligência de Mercado, e a ressalva do documento segue valendo — se a aba
  de bonds depender muito do Score, agrupar rende pouco. `app/comandos/` não é
  precedente para isso: é pasta de pontos de entrada, não módulo de produto.
- **§4.3, onde a conta mora**: nada mudou. Acima de 5.000 interações o painel
  mostra número parcial e avisa; as quatro rotas `/api/metricas/*` continuam
  sem ser chamadas. **É o único achado desta revisão com efeito no que a pessoa
  lê**, e espera decisão de produto.
- **§4.4, agrupar `src/dominio/`**: ~~37 arquivos planos, limiar de 40 não
  alcançado.~~ **O limiar FOI alcançado no mesmo dia, e a recomendação está
  retirada** — contar arquivos era a medida errada: 27 dos 40 são um componente
  conexo só. Ver §7.6. (Achado da revisão: esta linha contradizia a retirada.)
- **`importar_agendas.py` (3.258 linhas) e `Painel.tsx`**: deliberadamente não
  tocados, pelos motivos da §5.

---

## 7. Crescer PARA ONDE — os três rumos, e o que cada um testa

Este documento abriu perguntando se a estrutura aguenta crescer, sem saber em
que direção. Em 17/10/2026 o dono do produto disse: **mais automações de leitura
de dados, IA para geração de insights, e WhatsApp para interagir com a
plataforma.** Pediu explicitamente para não construir nada disso ainda — só
estar preparado.

Isso muda o que vale medir, porque os três batem em lugares diferentes. Abaixo,
o que foi medido para cada um.

### 7.1 WhatsApp: uma SEGUNDA INTERFACE — e esta a estrutura já aguenta

É o rumo mais duro dos três, porque não acrescenta uma tela: acrescenta uma
porta. A pergunta é se a regra do produto é alcançável sem um pedido HTTP.

**Medido: das 94 funções públicas de `app/casos_de_uso/`, ZERO** pedem
`UploadFile`, `Request`, `Depends`, `BackgroundTasks` ou qualquer tipo que só
existe dentro de um pedido. E nem `casos_de_uso/` nem `dominio/` importam
`fastapi` ou `starlette` em linha nenhuma.

**Toda operação do produto já é chamável de um job, de um comando ou de um
webhook.** Os nove comandos da §6.2 são a prova viva: eles rodam a regra sem
FastAPI nenhum, todos os dias.

Isso não estava protegido por nada, e o jeito de perder é banal — um
`UploadFile` na assinatura do caso de uso é o atalho de quem está escrevendo
uma rota de upload. Virou teste
(`tests/test_a_regra_nao_depende_de_http.py`, PR à parte).

**MAS A SEGUNDA INTERFACE NÃO SAI DE GRAÇA, e aqui está o número que importa:**

| onde | linhas em função auxiliar de rota |
|---|---|
| `api/lentes.py` | **1.344** (30 auxiliares; a maior, `_paineis`, tem 271) |
| `api/dependencias.py` | 273 — legítimo, é autorização de pedido |
| `api/importacoes.py` | 238 |
| `api/score.py` | 230 |
| `api/interacoes.py` | 170 (a maior é `obter_recorte`, 128) |
| `api/referencias.py` | 165 |
| `api/stakeholders.py` | 141 |
| `api/erros.py` | 121 — legítimo, são tratadores HTTP |
| outras 14 | 501 |
| **total** | **3.183** |

Tirando os ~394 que são legitimamente HTTP, sobram **~2.800 linhas de montagem
de resposta e de regra dentro da camada de rota** — e mais da metade num
arquivo só. Uma pergunta de WhatsApp como "como está a Imprensa este mês?"
precisaria de `_paineis` (271 linhas), `_evolucao` (93) e `_onde_esta_a_causa`
(110), todas privadas, todas dentro de `api/lentes.py`.

**É a §3.4 deste documento com número e consequência.** Lá eu escrevi que
`lentes.py` é "a camada de rota fazendo trabalho de três camadas" e deixei como
observação. Com uma segunda interface no mapa, deixa de ser observação: é o
único trabalho estrutural que o WhatsApp exige, e ele tem tamanho —
**estimativa de 2 a 4 dias**, extraindo os 30 auxiliares para
`casos_de_uso/leitura_das_lentes.py` (ou um módulo por bloco), com a suíte de
`lentes` na frente. Não foi feito aqui de propósito: é mudança grande, e vale
abrir sozinha.

### 7.2 IA para insights: o lugar já existe, e o risco não é estrutural

O produto já gera texto a partir de dado medido, e em quatro lugares puros:
`dominio/frases_de_sinais.py`, `dominio/frases_da_consulta.py`,
`dominio/tema_do_mes.py` no back, e `dominio/sinteseIA.ts`,
`dominio/relatorioNarrativo.ts` no front. São funções puras, testadas, e já
recebem o recorte pronto.

**Um gerador por LLM entra como mais uma fonte de texto no mesmo lugar**, e a
estrutura não atrapalha: a chamada ao modelo é um caso de uso (que, pela §7.1,
já é chamável de qualquer porta), e o texto gerado é dado como qualquer outro.

O que a estrutura NÃO resolve, e precisa de decisão quando chegar a hora: de
onde o gerador lê o recorte inteiro. Hoje o front deriva KPI e série sobre no
máximo 5.000 registros (§4.3) e as quatro rotas `/api/metricas/*` que fazem a
conta sobre o recorte SQL inteiro não são chamadas. **Um insight gerado sobre
número parcial é pior do que nenhum insight**, porque ele afirma com frase o que
o número não sustenta. Isto é mais um motivo para a §4.3 sair do esquecimento.

### 7.3 Mais automações de leitura: o custo é por fonte, e já é baixo

A ingestão de hoje tem quatro caminhos (planilha de agendas, planilha do Score,
pacote das lentes, cadastro externo em CSV), e eles compartilham o que importa:
leitura por `openpyxl`/`csv`, conferência antes de gravar, sessão de upload em
partes, e `importacao`/`importacao_linha` para a tela de conferência.

**O teto de leitura é declarado e medido** — 80 MB de planilha, 1,2 MB por
pedaço na subida em partes, com o motivo de cada número no código. Uma fonte
nova entra por esse caminho; o que ela traz de próprio é o mapeamento de
colunas, que é específico por definição.

Nada estrutural a fazer. **O que vale lembrar é operacional:** fonte nova é
tabela nova ou coluna nova, e migration que cria tabela nasce sem `delete` para
`painel_app` — a suíte fica verde e só o ambiente implantado quebra.

### 7.4 Gráficos e elementos: o que dá para reaproveitar, medido

Pedido explícito: "estruturar para reaproveitar o máximo possível de gráficos e
outros elementos". Medido no front em 17/10/2026, por quantas TELAS distintas
consomem cada arquivo:

| | arquivos | 1 tela | 2 ou mais | 4 ou mais |
|---|---|---|---|---|
| `src/componentes/` | 28 | 10 | **18** | 11 |
| `src/graficos/` | 16 | **10** | 6 | 1 |

`componentes/` está saudável (`basicos` serve 32 telas). Nada a fazer.

`graficos/` parece ruim e o número engana. **Nenhum gráfico importa primitiva de
desenho de outro** — os únicos imports entre eles são um controle
(`SeletorDeJanela`) e um `.geo.json`. Mas **todos importam de `@/dominio/`**, e
`@/dominio/formato` aparece em nove.

**Então a CONTA já é compartilhada e o DESENHO é por gráfico — e isso está
certo.** Não há biblioteca de gráficos no projeto (só `d3-scale` e `d3-geo`, que
dão escala e projeção), e um gráfico específico servir uma tela só é normal.
Montar um kit genérico agora seria abstração por adivinhação.

**O que estava fora do padrão era uma exceção**, e foi corrigida em PR à parte:
`GraficoDeLinha.tsx` calculava a régua do eixo Y dentro do componente. A conta
foi para `dominio/eixoDaSerie`, ao lado da régua do índice, com o porquê de
serem DUAS (o NSS é saldo e cruza o zero; o índice não) e com as três perguntas
que a TERCEIRA — a aba de bonds, que plota preço e yield — terá de responder.

Esse é o formato de "preparado para expandir" que a medição sustenta: **coletar
as decisões onde a próxima pessoa as encontra, e não inventar a abstração antes
do terceiro caso.**

### 7.5 O que mudaria o veredito

Tudo acima vale enquanto a resposta a estas perguntas não mudar. Se mudar, a
§4.1 (módulo próprio por domínio) volta à mesa:

- **o WhatsApp vai ESCREVER no painel, ou só ler?** Se escrever (confirmar uma
  agenda, registrar uma interação), ele passa a precisar da autorização por
  portal e por camada, e isso não é adaptador: é produto;
- **a IA vai gerar texto SOB DEMANDA ou em lote?** Em lote é job, e job é
  comando — a §6.2 já tem a pasta. Sob demanda num pedido HTTP é latência de
  LLM dentro do teto de ~240 s do ingress, que não é configurável;
- **as automações de leitura vão ser EMPURRADAS por terceiro** (webhook do
  fornecedor) em vez de puxadas por planilha? Aí entra autenticação de máquina,
  idempotência e repetição — e nenhuma das três existe hoje.

### 7.6 A §4.4 está RETIRADA: contar arquivos era a medida errada

A §4.4 dizia para agrupar `src/dominio/` por domínio quando passasse de 40
arquivos. O limiar foi alcançado em 17/10/2026 — e então eu medi o que devia
ter medido antes: **o grafo de imports**, em vez da contagem.

```
40 arquivos em src/dominio/, 14 componentes conexos

  27 arquivos, 8.907 linhas  <- UM componente só
   1 arquivo cada             <- as outras 13 folhas (34 a 355 linhas)
```

**VINTE E SETE DOS QUARENTA SÃO UM BLOCO.** `tipos`, `recorte`, `formato`,
`derivacoes`, `frentes`, `score`, `dossie`, `riscos`, `jornadaDoIndice`,
`janelaDaJornada`, `sinais`, `sinteseIA`, `relatorioNarrativo`… todos se
importam. Não existe costura entre "o domínio do Score" e "o domínio do CRM" ali
— existe um núcleo coeso que as duas telas usam.

**O QUE ACONTECERIA SE EU AGRUPASSE.** Cortar um componente conexo em subpastas
produz subpastas que se importam constantemente. O resultado é a aparência de
estrutura sem a substância: mais caminho para escrever em cada import, nenhuma
fronteira nova, e a navegação PIORA porque o arquivo que você procura passa a
depender de adivinhar em que grupo alguém o pôs.

**E O CUSTO É MEDIDO:** 448 linhas de import em 185 arquivos citam
`@/dominio/…`. É um churn que colide com qualquer outro trabalho no front, que
só o `tsc` consegue atestar (ninguém revisa 448 renomeações lendo), e que
compraria navegação — não capacidade.

**AS 13 FOLHAS têm família**, e esta é a parte aproveitável da ideia original:
quatro delas são `guiaDaCalibracao`, `guiaDoCadastro`, `guiaDoDossie` e
`guiaDoRecorte` (671 linhas), que são texto de ajuda e não falam com o núcleo.
Um `dominio/guias/` seria honesto e custaria ~8 imports. **Não foi feito** por
ser cosmético: tira 4 de 40 e não muda o que alguém consegue fazer.

**O QUE REABRIRIA A DECISÃO:** a fatia de bonds, que vai acrescentar arquivos de
domínio. Se eles formarem um componente PRÓPRIO — sem importar o núcleo dos 27 —,
existe fronteira de verdade e aí vale uma pasta. Se importarem o núcleo, a
resposta é a mesma de agora, e a §4.1 (módulo próprio por domínio) também fica
respondida pela mesma medição.

**A lição de método, que vale além deste item:** eu escrevi um limiar de
contagem porque contar é fácil. Contagem de arquivo não mede acoplamento, e foi
preciso alcançar o limiar para descobrir que ele não respondia nada. O número que
decide agrupamento é o tamanho do maior componente conexo.
