# Três fornecedores, uma tabela: o que a medição mostra

> ## ⚠️ CONCLUSÃO, 18/10/2026: NÃO SEPARAR AS TABELAS
>
> Este documento propõe, da seção 4 em diante, um núcleo conformado com uma
> tabela de extensão por fornecedor. **A recomendação foi retirada**, e por
> medição, não por mudança de ideia. A seção 8 tem os números.
>
> Em resumo: dos quatro ganhos que a seção 4 prometia, **o mais forte não
> existe** (a deduplicação por fornecedor não é implementável nem necessária), o
> segundo **já está resolvido** por outro mecanismo (`quem_fala` +
> `instituicao.tipo`), e os dois que restam são pequenos o bastante para não
> pagarem uma migration de 100 mil linhas em 10 arquivos.
>
> O que o dono do produto pediu — *"isolar os problemas de dados"* — **já está
> atendido pelo upload por fornecedor**, como a seção 1 já dizia e a seção 8
> confirma com número.
>
> O resto do documento fica como está, porque a medição dele continua válida e é
> ela que sustenta a retirada. Ler a seção 4 sem a 8 leva à conclusão errada.

> **Pedido do dono do produto (18/10/2026):** *"como são fornecedores diferentes
> o formato da tabela é diferente, mas as informações básicas devem ter em
> todas, e por isso gostaria que fossem salvas em tabelas distintas para
> eventuais mudanças não afetarem a todas e assim podermos isolar os problemas
> de dados."*
>
> Este documento **mede** antes de propor. Nada aqui foi implementado.

## 1. Como está hoje

Uma tabela `mencao` — **27 colunas** — para todos os fornecedores. O fornecedor
é uma coluna (`fonte_id` → `score_fonte`).

| id | código | fornecedor | linhas (pilha local) |
|---|---|---|---|
| 1 | `clipei` | Clipei | 100.151 |
| 2 | `clipei_investidores` | Clipei (recorte Mercado) | 1.677 |
| 3 | `approach_sl` | Approach · Social Listening | **0** |
| 4 | `bites` | Bites | 2.842 |
| 5 | `approach_cm` | Approach · Community Management | **0** |
| 6 | `crm` | Aegea (interna) | 0 |

**A adaptação de formato NÃO está no código** — está em
`score_fonte.mapeamento_colunas` (`jsonb`), uma declaração por fonte. Fornecedor
novo é uma linha e um JSON. Os desvios conhecidos têm cada um a sua chave:
`prefixo_a_remover` (a Approach carimba `2 - Aegea - Falta de Água`), `apelidos`
(a Bites chama a controladora de "Aegea", a Approach de "Holding"), `quem_fala`
(a Bites traz perfil de rede, a Clipei traz veículo), `lista_de_veiculos`,
`filtros`, `aba`, `arquivo`, `colunas_opcionais`.

### O que já está isolado

A subida **substitui por `(fonte_id, mês)`**:

```python
delete(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes.in_(meses))
```

Refazer a Clipei de setembro não toca numa linha da Bites, e o mapeamento é por
fonte — a Approach mudar o layout dela não passa perto da Clipei. **Metade do
pedido já está atendida: problema de dado de um fornecedor não contamina os
outros na carga nem na correção.**

O que **não** está isolado é o **schema**. É o resto deste documento.

## 2. A medição que decide o desenho

### 2.1 Os campos, lado a lado, como cada fornecedor os declara

Recortado de `score_fonte.mapeamento_colunas->'colunas'`, que é a verdade em
produção (e a única evidência disponível para a Approach, que não tem linha
carregada):

| campo | Clipei | Bites | Approach SL | Approach CM |
|---|---|---|---|---|
| `data` | Data | Data | Data | Data |
| `link` | Arquivo/Link | Link | Link | Link |
| `sentimento` | Classificação | Sentimento | Sentimento | Sentimento |
| `tema` | Subcategoria | N3 | Tags (tema) | TAG (assunto 1) |
| `titulo_texto` | Título | Texto | Conteúdo | Conteúdo |
| `unidade` | Empresa | Unidades/Empresas | Concessionárias | Concessionárias |
| `engajamento` | — | Engajamento | Engajamento | **Interações** |
| `uf` | **Estado do Veículo** | **Estado** | — | — |
| `veiculo` | Veículo | **Autor** | — | — |
| `atributo` | Atributo | — | — | — |
| `autor` | — | Autor | — | Publicador |
| `id_fonte` | ID | — | — | — |
| `publico_alvo` | Público-alvo | — | — | — |
| `tier` | Aegea Tier | — | — | — |
| `cargo` | — | **Cargo** | — | — |
| `perfil_autor` | — | **Cargo** | — | — |
| `subtema` | — | — | Tags (subtema) | — |
| `teor` | — | — | — | TAG (motivo) |

**SEIS CAMPOS SÃO DECLARADOS PELOS QUATRO FORNECEDORES**: `data`, `link`,
`sentimento`, `tema`, `titulo_texto`, `unidade`. É exatamente o "as informações
básicas devem ter em todas" do pedido, e não uma escolha de desenho — é o que a
medição devolveu.

### 2.2 Três coisas que a tabela única está escondendo

Estas não são hipóteses: saem da tabela acima.

**(a) `uf` tem DOIS significados.** Na Clipei é o *estado do veículo*; na Bites é
o *estado* (do autor do post). Hoje as duas gravam na mesma coluna, e qualquer
leitura que some `uf` entre fontes está somando duas perguntas diferentes.

**(b) `veiculo` da Bites é o AUTOR.** A Bites mapeia `veiculo` ← coluna `Autor`,
a mesma que alimenta `autor`. Então `mencao.veiculo` guarda nome de veículo de
imprensa para a Clipei e *handle de rede social* para a Bites. O cadastro
compartilhado já lida com isso por `quem_fala`, mas a coluna não distingue.

**(c) `cargo` e `perfil_autor` da Bites saem da MESMA coluna `Cargo`.** Dois
campos do mesmo dado bruto, com regras de leitura diferentes
(`normalizar_cargo` e `_perfil_de_quem_fala`).

**(d) `engajamento` não é a mesma métrica.** "Engajamento" (SL, Bites) e
"Interações" (CM) estão na mesma coluna, e a Clipei não tem nenhuma das duas.

### 2.3 O preenchimento real, por fonte

Percentual de linhas com valor, medido na pilha local:

| coluna | clipei | bites | clipei_inv |
|---|---|---|---|
| `data`, `sentimento`, `titulo_texto`, `link` | 100 | 100 | 100 |
| `unidade_texto` | 100 | 99 | 100 |
| `tema_texto` | 100 | 84 | 100 |
| `tema_id` | 27 | 84 | 20 |
| `instituicao_id` | 91 | 91 | 100 |
| `tier` | **100** | **0** | 100 |
| `atributo` | **99** | **0** | 99 |
| `id_fonte` | **100** | **0** | 100 |
| `publico_alvo` | 79 | **0** | 83 |
| `cargo` | **0** | **100** | 0 |
| `perfil_autor` | **0** | **100** | 0 |
| `autor` | **0** | 91 | 0 |
| `engajamento` | **0** | 57 | 0 |
| `uf` | 25 | 49 | 19 |
| `subtema` | 0 | 0 | 0 |
| `teor`, `acionavel` | 0 | 0 | 0 |

`subtema` e `teor` aparecem zerados **porque a Approach nunca foi carregada** —
são colunas da Approach, não colunas mortas. Com a Approach no ar, `subtema`
passa a valer para SL e `teor` para CM.

### 2.4 A consequência que já cobra conta: a Bites não tem deduplicação de linha

```sql
"mencao_do_fornecedor_uma_vez" UNIQUE (fonte_id, id_fonte, coalesce(unidade_texto,''))
  WHERE id_fonte IS NOT NULL
```

Só a Clipei declara `id_fonte` (coluna `ID`). **Bites e Approach caem fora do
índice.** A proteção delas é só a substituição do mês — que salva ao reenviar o
mês inteiro, e **não** salva de receber a mesma publicação duas vezes dentro do
mesmo arquivo. Numa tabela por fornecedor, cada um declara a chave que tem.

E `tier` não pode ser `not null` para a Clipei porque a Bites não tem a coluna.
**Nenhuma restrição de integridade consegue valer para um fornecedor só.** É
isso que a tabela compartilhada custa.

## 3. O impacto, arquivo por arquivo

`Mencao` aparece **498 vezes em 22 arquivos**. Mas o que importa é quem toca
coluna **de fornecedor** — essas são as que sairiam da tabela:

| coluna | arquivos que a acessam por `Mencao.<col>` |
|---|---|
| `uf` | `base_das_lentes`, `repositorio_lentes`, `repositorio_riscos`, `repositorio_score`, `carga_do_pacote_das_lentes`, `ingerir_mencoes`, `veiculos_da_imprensa`, `consulta_profundidade`, `ingestao_score` |
| `tier` | `base_das_lentes`, `repositorio_lentes`, `repositorio_riscos`, `repositorio_score`, `ingerir_mencoes`, `consulta_profundidade`, `ingestao_score` |
| `autor` | `base_das_lentes`, `repositorio_lentes`, `repositorio_riscos`, `repositorio_score`, `ingerir_mencoes`, `consulta_profundidade` |
| `engajamento` | `base_das_lentes`, `repositorio_lentes`, `repositorio_riscos`, `repositorio_score`, `ingerir_mencoes`, `ingestao_score` |
| `atributo` | `base_das_lentes`, `repositorio_lentes`, `repositorio_score`, `ingerir_mencoes`, `ingestao_score` |
| `perfil_autor` | `base_das_lentes`, `repositorio_lentes`, `repositorio_score`, `ingerir_mencoes`, `leitura_das_lentes` |
| `subtema` | `base_das_lentes`, `repositorio_lentes`, `repositorio_score`, `ingerir_mencoes` |
| `cargo` | `repositorio_riscos`, `repositorio_score`, `ingerir_mencoes`, `ingestao_score` |
| `teor`, `acionavel` | `repositorio_lentes`, `ingerir_mencoes` |
| `publico_alvo` | `repositorio_riscos`, `ingerir_mencoes` |
| `id_fonte` | `repositorio_score`, `ingerir_mencoes` |

**São 10 arquivos, não 22.** E as colunas de núcleo — `sentimento` (52
ocorrências), `mes` (63), `tema_id` (27), `tema_texto` (22), `unidade_texto`
(18) — **ficam onde estão**: a maioria das 498 referências não muda.

## 4. O desenho proposto: núcleo conformado + extensão por fornecedor

Três tabelas separadas e completas obrigariam **toda** leitura a virar `union` de
três — e as lentes somam fontes juntas (Imprensa soma Clipei, redes somam Bites,
os painéis comparam as duas). Isso paga caro por um isolamento que a carga já
tem.

O desenho que atende o pedido pelo texto dele — *"as informações básicas devem
ter em todas"* (núcleo) e *"mudanças não afetarem a todas"* (extensão):

```
mencao                    o NÚCLEO CONFORMADO, o que as quatro fontes têm
  id, fonte_id, mes, data, sentimento, link, titulo_texto,
  tema_texto, tema_id, unidade_texto, unidade_negocio_id,
  instituicao_id, criado_em

mencao_clipei             1:1, on delete cascade
  tier, peso_tier, atributo, publico_alvo, id_fonte,
  veiculo, uf_do_veiculo

mencao_bites              1:1, on delete cascade
  autor, cargo, perfil_autor, engajamento, uf_do_autor, handle

mencao_approach           1:1, on delete cascade
  autor, engajamento, subtema, teor, acionavel
```

### O que isso compra, item por item

1. **`not null` por fornecedor.** `mencao_clipei.tier not null` passa a ser
   possível. Hoje é impossível.
2. **Chave de deduplicação própria.** `mencao_clipei` deduplica por `id_fonte`;
   `mencao_bites` e `mencao_approach` declaram a que tiverem (link + data, por
   exemplo) — hoje elas simplesmente não têm.
3. **O `uf` ambíguo desaparece**: viram `uf_do_veiculo` e `uf_do_autor`, e
   qualquer leitura que somava os dois passa a ter de escolher — o que é o ponto.
4. **`veiculo` da Bites deixa de se disfarçar de veículo de imprensa.**
5. **Mudança de layout de um fornecedor é `alter table` na tabela dele.**
   Nenhuma migration volta a tocar a tabela de 100 mil linhas dos outros.
6. **Problema de dado fica contido por construção**, e não por disciplina de
   quem escreve a consulta.

### O que isso custa

- **Uma migration** com três tabelas, backfill por `fonte_id`, e as colunas
  saindo de `mencao` (ou ficando por um tempo, ver abaixo).
- **10 arquivos** com acesso a coluna de fornecedor, todos em `banco/` e
  `casos_de_uso/` — nenhum em `api/`, nenhum em `dominio/` além de
  `ingestao_score.py`.
- **Um join por leitura que use campo específico.** As leituras de núcleo não
  mudam.
- O front: as colunas chegam por `esquemas/`, então o contrato da API pode ficar
  idêntico. A decisão de expor `uf_do_veiculo`/`uf_do_autor` separados é de
  produto, e pode vir depois.

## 5. Ordem sugerida, cada passo verde e reversível

Nenhum passo exige o seguinte; se você parar no 2, o que foi feito já vale.

| # | passo | o que prova |
|---|---|---|
| 1 | Criar as três tabelas vazias e o backfill por `fonte_id`, **sem tirar nada de `mencao`**; um teste exige que as duas cópias concordem linha a linha | o backfill está certo e nada quebrou |
| 2 | As escritas passam a gravar nas duas (`mencao` + extensão), com o teste do passo 1 virando guarda permanente | a escrita nova está certa |
| 3 | As leituras dos 10 arquivos passam a ler da extensão, um arquivo por PR | cada arquivo isolado, com a suíte verde |
| 4 | Remover as colunas de `mencao` e ligar os `not null` e as chaves de deduplicação por fornecedor | o isolamento fica estrutural |

O passo 1 e o 2 juntos são o que de fato responde *"isolar problemas de dados"* —
do 3 em diante é limpeza.

## 6. O arquivo da Approach, lido

`Aegea - Approach Dados - Conteudo - SL - CM - V2.xlsx`, 3,4 MB, 7 abas. Lido em
18/10/2026 — é o **mesmo export** que a migration `0091` mediu (SL 10.955 + CM
6.084 = 17.039 linhas, exatamente os "17.039" citados lá).

| aba | cabeçalho | colunas | linhas | é menção? |
|---|---|---|---|---|
| `Conteúdo` | **linha 2** | 49 | 134 | não — post próprio, sem sentimento |
| `Stories` | linha 1 | 19 | 36 | não |
| `Seguidores` | **linha 2** | 16 | 13 | não — série mensal |
| `Mídia` | linha 1 | 32 (+41 vazias) | 50 | não — mídia paga |
| **`SL`** | **linha 2** | 20 | **10.955** | **sim** |
| **`CM`** | linha 1 | 28 | **6.084** | **sim** |
| `NÃO MEXER - Automação` | linha 1 | 3 | 4 | não — de-para Tema↔Editoria↔Atributo |

**O cabeçalho da `SL` e da `Conteúdo` está na linha 2**, com a linha 1 reservada
a anotações da agência (`Desconsiderar`, `Verificar`, `Buzzmonitor, verificar`,
`Unidade/empresa`, `o que é?`, `Quando linha = "", conteúdo orgânico`). Quem
ler assumindo linha 1 recebe cinco nomes de coluna que não existem.

### 6.1 A quebra do alcance, medida

**`alcance` não existe nas abas de menção.** Nem na `SL`, nem na `CM`. As 17.039
menções da Approach não têm alcance nenhum — elas têm `Engajamento` (SL) e
`Interações` (CM), que é o que o mapeamento já declara.

O alcance vive nas três abas de **conteúdo próprio**, que não são menção (não
têm sentimento, não entram neste caminho):

| aba | colunas `Alcance` | preenchimento | tipo |
|---|---|---|---|
| `Conteúdo` | **DUAS (col. 14 e 30)** | 82 e 37 de 134, **26 linhas com as duas** | **10 células com `-`** |
| `Stories` | uma | 36/36 | número |
| `Mídia` | uma | 48/50 | número |

**A quebra é a aba `Conteúdo` ter duas colunas com o nome `Alcance`** — e não só
ela: `Impressões`, `Reações`, `Comentários`, `Compartilham.`, `Salvar`,
`Cliques` e `Engajamentos` também aparecem **duas vezes cada**, oito nomes
repetidos no mesmo cabeçalho. O primeiro bloco é **orgânico**; o segundo, depois
da coluna `Investimento`, é **patrocinado**. Em 26 linhas os dois estão
preenchidos — é a mesma publicação com alcance orgânico *e* pago.

Isso é decisivo para o desenho: **um `Mapeamento` que aponta campo → *nome* de
coluna não consegue ler essa aba.** `{"alcance": "Alcance"}` pega a primeira
ocorrência e perde a paga, calado. Ler alcance exige ou posição de coluna, ou um
nome qualificado (`Alcance (orgânico)` / `Alcance (pago)`) negociado com a
agência. E `-` em 10 células significa que a coluna não é numérica.

A `Stories` repete `Mês`, `Ano`, `Data` e `Editoria` (colunas 1-4 e 5-8, o
primeiro bloco 80% preenchido e o segundo 100%); a `Seguidores` repete os quatro
nomes dela **três vezes**, um bloco por rede.

### 6.2 O que isso muda no plano

1. **`mencao_approach` NÃO ganha coluna de alcance.** A Approach não traz alcance
   para menção, e inventar a coluna seria antecipar um dado que não existe neste
   caminho. A composição proposta na seção 4 fica como está.
2. **Alcance é outro grão, não outra coluna.** Desempenho de post próprio
   (orgânico × pago, com investimento, CPM, CTR, frequência) não é menção: não
   tem sentimento, não tem veículo, não tem autor. Se o painel for medir isso, é
   uma tabela nova com a sua própria chave, não um campo em `mencao`.
3. **As seis colunas da `SL` que o `0091` deixou de fora continuam vazias**, e a
   medição confirma: `Autor`, `Cidade`, `Estado`, `Publicador`, `Atributo` e
   `Holding` estão a **0%** nas 10.955 linhas. A decisão de não mapeá-las segue
   certa, e segue sendo cobrança à agência.
4. **A `CM` tem lixo na área de dados.** A coluna 22 (`TAGS`) e as 19-21 e 23-28,
   sem nome, carregam uma legenda colada ao lado (`2 - Aegea - Vagas`,
   `replied`) e **referências de célula** (`V2:V777`, `C5310:C6085`). O leitor
   atual sobrevive porque lê por nome de coluna; qualquer leitura posicional
   quebraria.

## 7. O pré-requisito que já foi feito

Antes de separar as colunas por fornecedor, o **núcleo** precisava conseguir
juntá-los — e não conseguia. A medição mostrou que `mencao` tinha **um** nível de
taxonomia (`tema_id`, o N3) e que 71% da base não alcançava nível nenhum.

Isso virou a **migration `0098`** (PR #93), com a regra do dono do produto: *o
fornecedor traz o N1, o N2 ou o N3, e os de cima são derivados do cadastro*.
Resultado medido: **de 29.701 para 102.715 menções com N1 (98,1%)**, com
`tema_id` inalterado.

**Por que isso vinha antes:** separar as colunas de fornecedor sem isso copiaria
para três tabelas um núcleo que não junta. O pedido diz *"o core que vai
permitir juntar elas, fazer filtro e tudo que for necessário para uma análise
unificada"* — as três chaves de taxonomia são esse core.

**O que ainda falta para o core cumprir o pedido inteiro**, e está medido:

| buraco | medida | onde resolver |
|---|---|---|
| nenhuma leitura usa `bloco_tema_id`/`macro_tema_id` | filtros derivam de `tema_id`; menção só-N1 não entra no recorte por pilar | PR próprio, muda números em tela |
| `unidade_negocio_id` | **0 de 104.670** | o fornecedor diz `Águas do Pará`, o cadastro tem 4 blocos — decisão de produto |
| `subtema` | 0 de 104.670 | só a Approach mapeia, e nunca subiu |

## 8. Por que a separação foi retirada

> **Esclarecimento do dono do produto (18/10/2026):** *"não é para ter tela por
> fornecedor, apenas o upload que será específico — e hoje já temos."*

Com isso, a pergunta deixou de ser "como separar" e passou a ser "o que a
separação ainda compra". Medi os quatro ganhos que a seção 4 prometia.

### 8.1 Chave de deduplicação por fornecedor — **o ganho não existe**

Era o argumento mais forte da seção 4: *"Bites e Approach caem fora do índice
único, e a proteção delas é só a substituição do mês"*. A medição derruba por
dois lados.

**Não há o que deduplicar.** Duplicatas por `(fonte, mes, link)`:

| fonte | grupos | linhas a mais | e com `titulo_texto` junto |
|---|---|---|---|
| bites | 32 | 46 | **0 — some** |
| clipei | 3.468 | 6.858 | 3.273 / 6.580 |
| clipei_investidores | 133 | 183 | 110 / 152 |

As 46 linhas da Bites que compartilham link **têm texto diferente**: são
comentários distintos no mesmo post, que é exatamente o que social listening
coleta. Deduplicar por link as apagaria. Não sobra nenhuma duplicata de verdade.

**E não há chave para declarar.** A Bites manda `id_fonte` em **0 de 2.842**
linhas. Qualquer chave derivada do conteúdo erra para um dos dois lados — e a
Clipei prova: mesmo COM o índice único em `id_fonte`, ela tem 6.858 linhas
compartilhando `(fonte, mes, link)`, porque são itens diferentes no sistema do
fornecedor. **Link nunca foi chave.**

A proteção que existe — apagar e regravar o mês inteiro — cobre o reenvio, que
é como o arquivo chega. O risco residual (a mesma publicação duas vezes DENTRO
de um arquivo) não se materializou em 104.670 linhas.

### 8.2 `veiculo` da Bites se disfarçando de veículo — **já resolvido**

A seção 2.2(b) está certa sobre a coluna, e errada sobre a consequência: o
cadastro **já** distingue, por `quem_fala` no mapeamento e `instituicao.tipo` no
destino.

| o que a Bites criou no cadastro | quantas |
|---|---|
| `perfil_rede` | **1.050** |
| `veiculo` | 36 |

Nenhum perfil de rede virou veículo de imprensa. Uma tabela separada não
melhoraria isto — `tipo` já faz o trabalho.

### 8.3 `uf` com dois significados — **real, e pequeno**

| | Clipei (estado do veículo) | Bites (estado do autor) |
|---|---|---|
| linhas com `uf` | 25.784 | **1.396** |

A Bites é **5%** do `uf` preenchido. No maior estado, Rio Grande do Sul: 5.034
do veículo contra 966 do autor. A conflação existe e é mensurável, mas separar
tabelas é caro demais para ela — se incomodar, o conserto é **uma coluna**
(`uf_do_autor`), não três tabelas.

### 8.4 `not null` por fornecedor — **real, e cosmético**

`mencao_clipei.tier not null` passaria a ser possível (a Bites tem 0 de 2.842).
O ganho é pegar um arquivo torto na subida em vez de na tela. É verdadeiro, e
sozinho não paga a mudança.

### 8.5 O que o upload por fornecedor já isola, com número

```python
delete(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes.in_(meses))
```

* **o dado**: refazer a Clipei de setembro não toca uma linha da Bites;
* **o formato**: `mapeamento_colunas` é por fonte — a Approach mudar o layout
  dela não passa perto da Clipei. É onde moram `prefixo_a_remover`, `apelidos`,
  `quem_fala`, `aba`, `arquivo`, `filtros`, `colunas_opcionais`;
* **o momento**: cada fonte sobe quando o fornecedor entrega.

Era isto o pedido — *"eventuais mudanças não afetarem a todas, e assim podermos
isolar os problemas de dados"*. Está atendido.

### 8.6 O que vale fazer no lugar

O que de fato faltava ao núcleo não eram tabelas, eram **chaves** — e essa parte
foi feita (seção 7, migration `0098` + o filtro):

| | antes | depois |
|---|---|---|
| menções com N1 | 29.701 | **102.715** |
| o recorte por pilar alcançava | 29.701 | **102.715** |

O que continua aberto é **decisão de produto, não schema**:

| pendência | medida |
|---|---|
| `unidade_negocio_id` | **0 de 104.670** — o fornecedor diz `Águas do Pará`, o cadastro tem 4 blocos |
| gráfico de N1 agrupa por texto | 15 grafias para 7 pilares |
| `uf` do autor x do veículo | 5% de contaminação, uma coluna resolve |