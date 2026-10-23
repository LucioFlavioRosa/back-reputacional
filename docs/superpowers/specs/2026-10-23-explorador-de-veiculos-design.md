# Explorador de veículos: tier e veículo que se filtram juntos

**Data:** 23/10/2026
**Situação:** desenho aprovado, aguardando plano de implementação
**Alcance:** `back-reputacional` (repositório de lentes, esquemas, rota) e `front-reputacional` (api, domínio, um bloco novo, três cartões que saem)

---

## Por que isto existe

Hoje a dimensão de veículo está partida em **três cartões independentes** na
Síntese executiva da Imprensa e do Mercado:

| Cartão | O que mostra |
|---|---|
| `Tier do veículo × sentimento` | distribuição de sentimento por tier |
| `% Matérias por tier e Top veículos` | rosca de volume por tier + os veículos que mais publicaram |
| `Termômetro por Veículos` | o placar de −100 a +100 de cada veículo |

Os três respondem ao **filtro da tela**: clicar num tier ou num veículo vai ao
servidor e move o dossiê inteiro — nota, KPIs, evolução, últimas matérias. Para
trocar de tier é preciso desfazer o clique antes, porque o painel clicado passa
a mostrar uma barra só.

O pedido (23/10/2026) é repetir nessa dimensão o molde do bloco **"Atributos,
temas estratégicos e subtemas"**, que resolve exatamente isso.

## O molde que se copia

`ExploradorDaLente.tsx` + `dominio/explorador.ts` + `GET /{codigo}/explorador`
fazem **um pedido por mês e recorte da tela**, recebem as menções já agrupadas
e cruzam tudo no navegador. Daí vêm as três propriedades que se quer:

1. **clique instantâneo** — não há ida ao servidor;
2. **o dossiê não se move** — a seleção é só do bloco;
3. **o gráfico do próprio item continua inteiro**, com ele em destaque — sem
   isto ninguém troca de seleção sem desfazer o clique antes.

A terceira é a razão de ser do molde, e está escrita no domínio:

> O FILTRO É CRUZADO: escolher um N1 refaz o N2, o N3 e o mapa; o gráfico do
> próprio N1 continua com todos (o escolhido em destaque), senão a pessoa não
> teria como trocar de N1 sem desfazer o clique antes.

## O fato que decidiu o desenho

**Nenhuma carga de hoje liga veículo a tier.** Foi conferido campo por campo:

| O que chega | tier | veículo |
|---|---|---|
| `volume_por_tier` | sim | não |
| painel `Tier do veículo × sentimento` | sim | não |
| `top_veiculos` | não | sim |
| `clima_por_veiculos` | não | sim |
| `GrupoDoExplorador` | não | não (`n1`, `n2`, `n3`, `uf`) |

Logo, "clicar num tier e ver os veículos daquele tier" **não é somável no
navegador** com o que existe. É por isso que esse cruzamento hoje só funciona
pelo filtro da tela, com o custo descrito acima.

A alternativa de fazer só no front, reaproveitando o filtro da tela, foi
avaliada e **recusada**: ela dá a aparência do molde e perde as três
propriedades que o definem.

## O que o back ganha

### `repositorio_lentes.grupos_de_veiculos`

Quase uma cópia de `grupos_do_explorador`, com uma chave menor:

```python
select(
    Mencao.tier,
    Mencao.veiculo,
    Mencao.sentimento,
    Mencao.cargo,
    Mencao.engajamento,
    func.count().label("quantas"),
)
.select_from(Mencao)
.join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
.where(
    ScoreFonte.lente_id == lente_id,
    Mencao.mes == primeiro_dia(mes),
    *so_fontes_ligadas(calibracao),
    *condicoes_do_filtro(filtro),
)
.group_by(Mencao.tier, Mencao.veiculo, Mencao.sentimento,
          Mencao.cargo, Mencao.engajamento)
```

Depois colapsa na chave `(tier, veiculo)` e emite, por linha:

```
{tier, veiculo, positivo, neutro, negativo,
 peso_positivo, peso_neutro, peso_negativo}
```

`cargo` e `engajamento` entram no `group_by` **só porque `peso_da_mencao`
precisa deles** — exatamente o motivo pelo qual já estão no `grupos_do_explorador`.
Eles não aparecem na saída.

**Sem `outerjoin` de `Tema`/`MacroTema`**, ao contrário do
`grupos_do_explorador` — esta consulta não lê taxonomia. E os filtros de
taxonomia da tela continuam funcionando sem o join, porque
`condicoes_do_filtro` casa por **subconsulta e nunca por junção**, decisão
registrada lá com a razão: *"entra em nove consultas diferentes, e acrescentar
uma junção aqui mudaria o `from` delas por baixo"*. Esta é a décima.

### `GET /api/score/lentes/{codigo}/explorador-de-veiculos`

Mesma forma de `obter_explorador`:

* os **mesmos parâmetros de consulta** (todo o filtro da tela vale aqui);
* `denominador_do_mes` para o impacto fechar com a nota;
* lente que lê o CRM responde **vazia, sem erro** (`lente_e_interna`);
* lente inexistente → `NaoEncontrado`.

### Esquemas

`GrupoDeVeiculoSaida` e `ExploradorDeVeiculosSaida` em `esquemas/lentes.py`,
no molde de `GrupoDoExploradorSaida`/`ExploradorSaida`.

### Por que rota nova, e não ampliar o `/explorador`

Acrescentar `tier` e `veiculo` àquela chave multiplicaria a cardinalidade:
`n1 × n2 × n3 × uf × tier × veículo`. Uma chave de só `tier × veículo` é a
carga mínima que responde aos três painéis, e deixa o Explorador de taxonomia
com o tamanho que ele já tem.

## O que o front ganha

* `api/score.ts` — `GrupoDeVeiculo`, `ExploradorDeVeiculos`, `obterExploradorDeVeiculos`;
* `dominio/exploradorDeVeiculos.ts` — a conta;
* `paginas/score/ExploradorDeVeiculos.tsx` — os três painéis, os chips e o Limpar;
* `dominio/guiaDoDossie.ts` — a entrada de ajuda do bloco novo.

Em `DossieDaLente.tsx` **saem** `VolumeETopVeiculos`, `ClimaPorVeiculos` e a
sublista "Top veículos Tier 1" de dentro do painel de tier. O bloco novo
aparece para `LENTES_COM_BLOCOS_DE_VEICULO` (`imprensa`, `mercado`) — a mesma
regra dos cartões que ele substitui.

## A mecânica: dois eixos, três painéis

No bloco de taxonomia, N1 › N2 › N3 é uma **hierarquia**: cada coluna é um
campo distinto. Aqui não. **Tier é um eixo e veículo é o outro**, e os painéis
2 e 3 são o *mesmo* eixo com medidas diferentes.

Então:

```ts
type Selecao = { tier?: string; veiculo?: string };
```

Duas chaves, três painéis. O `exceto` do molde passa a ser **o eixo do painel
que está sendo desenhado**, e não o painel:

| Clique | Painel 1 (Tier × sentimento) | Painel 2 (Top veículos) | Painel 3 (Termômetro) | Dossiê |
|---|---|---|---|---|
| num **tier** | **inteiro**, destacado | só os daquele tier | só os daquele tier | intocado |
| num **veículo** | só o tier dele | **inteiro**, destacado | **inteiro**, destacado | intocado |

Os dois painéis de veículo ficam inteiros **juntos**, porque compartilham o
eixo. Filtrar o painel 3 pelo veículo escolhido no painel 2 o deixaria com uma
barra só — que é o modo de falha que o molde existe para evitar.

Clicar de novo no mesmo valor desfaz, como no molde.

## UM cartão, três colunas

Decisão de 23/10/2026, depois de a primeira versão sair com **três cartões
empilhados**: o bloco é **um cartão com as três colunas lado a lado**
(`grade grade--3`), como o bloco de Atributos que serve de molde.

O que isso ganha: a comparação de relance entre as três leituras, e os chips de
"Filtrando por" aparecendo **uma** vez — empilhado, eram três linhas de chips e
três botões "Limpar", todos com o mesmo nome acessível.

O que isso custa: a `BarraDivergentePorItem` do termômetro passa de largura
cheia para um terço, e o cartão fica mais largo que alto. **Pede conferência
visual.**

Cada coluna é um `role="group"` com `aria-labelledby` no próprio `h3`. Sem o
grupo, o leitor de tela leria uma fila de barras sem dizer de qual coluna cada
uma é — "Folha, 12 matérias" aparece nas DUAS colunas de veículo, e nada as
distinguiria.

O título do cartão é **"Tier do veículo, top veículos e termômetro"**, no molde
da lista que "Atributos, temas estratégicos e subtemas" usa. Os nomes das três
colunas continuam sendo os que o pedido nomeou.

## As medidas de cada painel

1. **Tier do veículo × sentimento** — `ColunasEmpilhadas` com as três barras de
   tier. Rótulo de `ROTULO_DO_TIER` (`muito_relevante` → "Tier 1"), que já
   existe em `dominio/filtrosDasLentes.ts`, na ordem fixa
   `muito_relevante, relevante, menos_relevante`. Impacto em pontos na ponta.
   **Somente a distribuição de sentimento por tier** — a rosca de volume não
   volta, por ser a mesma leitura em outra forma.
2. **Top veículos** — `ColunasEmpilhadas` por volume decrescente, sentimento
   dentro da barra, impacto na ponta. O título perdeu o "Matérias por tier e"
   (decisão de 23/10/2026): a rosca de volume saiu e a distribuição por tier é
   o painel 1, então o nome antigo prometia duas leituras e entrega uma.
3. **Termômetro por Veículos** — `BarraDivergentePorItem` na variante
   `termometro`, com NSS e score pela conta de `ufsDoExplorador`:
   `nss = (pos − neg) ÷ total × 100` e `score = (NS ponderado + 1) ÷ 2 × 100`.

### Quantos veículos aparecem

Hoje o servidor corta no **top 10**. Com o agrupamento local o front recebe
**todos** os veículos do recorte, e a decisão passa a ser da tela.

Decisão (23/10/2026): os painéis 2 e 3 **abrem em 5** e têm o botão
**"Ver todos os N veículos"** que já está no ar desde o PR #160 — `N` passa a
ser *todos* os do recorte, não mais o teto de 10. A altura fica com a rolagem
interna da `ColunasEmpilhadas`, como as colunas do Explorador de taxonomia
fazem. O `useListaDeVeiculos` e o `RevelarVeiculos` são reaproveitados; o que
muda é a origem do `teto`.

O painel 1 tem três barras e **não leva botão** — a guarda `teto > inicial` já
o faz não nascer.

## O tamanho da carga: medir antes de fechar

**Não se sabe quantos veículos distintos um mês tem.** Os blocos de hoje sempre
vêm cortados em 10, então o número real nunca apareceu em tela nenhuma.

O limite superior de linhas é `tiers × veículos`, mas um veículo tende a ter um
tier só, então o esperado é da ordem do número de veículos.

**O primeiro passo da implementação mede isso na base de dev** —
`count(distinct veiculo)` e a contagem de grupos por mês — e o resultado entra
neste documento. Se a carga se mostrar grande, a rota ganha um teto com uma
linha de **"outros" explícita** (nunca um corte silencioso, que faria as somas
dos painéis não fecharem com a nota). Enquanto a medição não existir, a rota
não é considerada fechada.

### Estado da medição em 23/10/2026: NÃO FEITA

Tentada na pilha local e **impossível ali**: os três bancos do Postgres local
(`painel_reputacional`, `painel_reputacional_limpo`,
`painel_reputacional_teste`) têm `count(*) from mencao` = **0**. A pilha local
nunca recebeu a base importada.

A medição precisa da base de **dev**, e rodar SQL ali é ação em ambiente
compartilhado — fica como item aberto para o dono do produto. **A rota foi
implementada sem teto**, que é o caso comum; o teto, se a medição o exigir,
entra depois sem tocar o front.

### E se o teto vier, o nulo não serve de rótulo

Achado ao implementar: a linha de "outros" com `veiculo = null` seria
**silenciosamente descartada** pela tela. `somasDoEixo`, no domínio do front,
faz `if (!chave) continue` — que é a regra **certa** para "menção sem veículo",
e que o próprio molde do Explorador de taxonomia tem ("Menção sem o campo
daquele nível fica fora DESTA barra"). As duas coisas colidiriam no mesmo
valor: o "outros" do teto e o "sem veículo" do dado.

Então o teto, quando vier, precisa de **rótulo próprio** em vez de nulo — e de
uma decisão sobre o que o clique nele faz, porque filtrar por "Outros" não
casaria com nenhuma menção. Duas decisões de produto que este desenho
deliberadamente **não** resolve, para não inventar comportamento antes de
existir o número que o justifique.

## Os blocos antigos do servidor

`volume_por_tier`, `top_veiculos`, `clima_por_veiculos` e `veiculos_tier1`
deixam de ser lidos pelo front. **Eles ficam no back nesta mudança.**

A informação que eles carregam continua aparecendo, de uma forma ou de outra,
nos painéis novos — então o que sobra é carga morta, não perda de informação.
Removê-los agora alargaria o estrago numa mudança que já é de dois
repositórios: é preciso antes conferir o relatório, o PNG e a lente Mercado.
**Vai num PR separado**, e está registrado como pendência.

## Erro e carregamento

Idênticos ao molde: `<Carregando />` enquanto não há resposta, parágrafo em
`var(--erro-fg)` com a mensagem quando falha, e lente interna devolvendo vazio
sem erro. Os dados guardam a **chave do pedido** (`codigo|mes|filtro`) e a tela
só usa os que batem com o estado atual — é o que evita a resposta atrasada de
um recorte pousar sobre outro.

## Testes

**Back**

* `grupos_de_veiculos`: o agrupamento colapsa na chave certa; a contagem e o
  peso caem no lado certo do sentimento; `cargo`/`engajamento` não aparecem na
  saída; menção sem tier e menção sem veículo não derrubam a consulta.
* a rota: parâmetros do filtro chegando, lente interna vazia, lente
  inexistente em 404, e a permissão igual às outras rotas de lente.
* o impacto fecha com a nota: a soma dos pesos das linhas é o denominador do
  mês — a mesma invariante que o Explorador de taxonomia tem.

**Front**

* domínio: a regra do `exceto` por **eixo** — clicar num tier deixa o painel de
  tier inteiro e estreita os dois de veículo; clicar num veículo deixa **os
  dois** de veículo inteiros e estreita o de tier. Este é o teste que prende a
  diferença em relação ao molde de três níveis.
* domínio: NSS e score conferidos contra valores escritos à mão.
* componente: os três painéis desenhados, os chips com o rótulo do eixo, o
  Limpar zerando os dois, e o botão "Ver todos" abrindo em 5.

**O que morre**

Os testes dos três cartões em `DossieDaLente.blocos-de-veiculo.test.tsx` saem,
**inclusive o do Tier 1 escrito em 23/10/2026**: a sublista deixa de existir, e
um teste de guarda para código removido é ruído.

## Fora de alcance

* remover os quatro blocos do dossiê no back (PR separado, acima);
* estender o bloco à lente `institucional` — ela está em
  `LENTES_COM_EXPLORADOR` mas não em `LENTES_COM_BLOCOS_DE_VEICULO`, e incluí-la
  é decisão de produto, de uma linha;
* o `azure-pipelines.yml` do front, que publica num repositório de imagem
  inexistente (pendência anotada em 23/10/2026, sem relação com este desenho).
