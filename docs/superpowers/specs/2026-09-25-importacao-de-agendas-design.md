# Importação de agendas por planilha

**Data:** 25/09/2026
**Situação:** desenho aprovado, aguardando plano de implementação
**Alcance:** `back-reputacional` (domínio, casos de uso, rotas) e `front-reputacional` (botão de download e tela de conferência)

---

## Por que isto existe

O cliente relatou dias com **até 54 reuniões**. Registrá-las uma a uma pelo
formulário é trabalho que a ferramenta deveria poupar, e a saída que ele propôs
foi subir uma planilha.

O risco da planilha livre é a ausência de padrão: cada pessoa com um formato,
e o nome do mesmo órgão escrito de três jeitos. Por isso a plataforma **fornece
o modelo**: um `.xlsx` gerado com os vocabulários atuais e com as mesmas
restrições que a tela aplica, para preencher fora e subir depois.

O resultado que se busca: o dia inteiro de reuniões entra de uma vez, sem
digitar agenda por agenda, e sem que a base ganhe três grafias do mesmo órgão.

## O que já existia

A migration **`0008_importacao.sql`** criou `importacao` e `importacao_linha` e
nunca ganhou implementação. O cabeçalho dela diz "⚠ SCHEMA SEM APLICAÇÃO", e
`interacao.fonte`, `interacao.origem_aba` e `interacao.origem_linha` já apontam
para este fluxo.

Ela também registra uma decisão que este desenho respeita:

> importar não é escrever … uma pessoa confere linha a linha e decide … 
> importação de planilha sem conferência humana cria duplicata de instituição
> em massa, e desfazer isso depois é pior do que digitar de novo.

**As tabelas servem sem alteração.** Nenhuma migration nova é necessária para o
fluxo; se alguma surgir, é por detalhe de implementação, não por desenho.

Em particular, **o grupo de divergência não é uma tabela**: ele é uma VISTA
sobre as linhas que compartilham o mesmo valor não resolvido, montada ao ler
`importacao_linha.divergencias`. Resolver um grupo reescreve a `proposta` de
cada linha afetada e limpa aquela divergência — não há estado de grupo a
persistir, e criar uma terceira tabela para ele seria inventar uma entidade que
o desenho não tem.

Existe também precedente de leitura de `.xlsx` no repositório: a ingestão das
planilhas de fornecedores do Score, com `openpyxl` e mapeamento de colunas por
fonte. A leitura de arquivo não precisa ser inventada.

## Decisões de produto

Tomadas pelo dono do produto em 25/09/2026, registradas aqui porque **mudam o
risco** e não se derivam do código:

| Decisão | Escolha | Consequência aceita |
|---|---|---|
| O que acontece ao subir | **Propor e conferir** antes de criar | Uma tela a passar antes de as agendas existirem |
| Valor novo nas abas de cadastro | **É criado na importação** | Contraria o alerta da `0008`; mitigado pela distinção aba/célula e pela conferência |
| Listas dentro da agenda | **Abas filhas ligadas por código** | A pessoa aprende um conceito novo: o código da agenda |
| Quem importa | **Só quem administra cadastros** (`plataforma_edicao`) | Quem viveu as reuniões entrega a planilha à coordenação |

A segunda merece nota: ela foi tomada **depois** de o alerta da `0008` ser
apresentado. O que a torna defensável é a distinção da seção seguinte — escrever
na aba de cadastro é ato deliberado; digitar na célula da agenda não é.

## Invariantes do desenho

1. **A validação do Excel é conveniência, nunca controle.** O modelo leva listas
   suspensas porque ajudam a preencher certo. O servidor revalida tudo e não
   confia em nada do arquivo — mesma doutrina que o projeto aplica a botão
   escondido.
2. **A importação reusa o caminho do formulário.** Cada proposta é um
   `InteracaoEntrada` e segue por `para_dominio`, `derivar_frente`,
   `derivar_esfera`, `validar_consulta` e `registrar_interacao`. A importação
   **não escreve em `interacao` diretamente**. Uma agenda importada e uma
   digitada são indistinguíveis no banco, exceto por `fonte` e `origem_linha`.
3. **O arquivo bruto fica guardado** em `importacao_linha.dados_brutos`, como a
   `0008` prevê — é o que permite reprocessar quando a regra de leitura mudar, e
   o que responde "de onde veio este registro" meses depois.
4. **Uma descrição do formato, dois consumidores.** Ver *Arquitetura*.

---

## O modelo `.xlsx`

### A aba de preenchimento

**UMA ABA SÓ — `Agendas` —, uma linha por agenda, 59 colunas.** Decisão do dono
do produto, tomada ao ver o primeiro modelo: *"quero preencher tudo em uma única
aba"*. O desenho anterior tinha quatro abas ligadas por um `Código` que quem
preenche inventava (A1, A2…) e repetia nas abas filhas.

A ordem das colunas segue a **sequência dos campos do formulário de nova
interação**, porque é o caminho que a coordenação já conhece:

| Grupo | Colunas |
|---|---|
| A agenda | `Código` · Tipo de interação · Área 1–2 · **Data** · Instituição · UF · Unidade de negócio · Tema 1–3 · Modalidade · Local · Iniciativa · Situação · Nota da situação · Declinado por · Motivo do declínio · Clima esperado · Expectativa · Prevê desdobramento · Clima · Resultado · Relato · Repercussão e encaminhamentos · Pendências · Observações |
| A outra parte | `Interlocutor 1–4` · `Presença 1–4` |
| A casa | `Pessoa da Aegea 1–4` · `Papel 1–4` · `Presença da Aegea 1–4` |
| Materiais | `Momento 1–3` · `Título 1–3` · `Link 1–3` · `Observação do material 1–3` |

**O preço do teto fixo**, dito na hora da decisão: uma agenda com cinco
interlocutores não cabe. Os tetos (4/4/3) vieram da medição do banco povoado —
máximo observado de 2 interlocutores, 3 pessoas da Aegea e 2 materiais por
agenda — com folga, e ampliá-los é acrescentar colunas, não mudar o desenho.

**O que o teto comprou:** o `Código` deixou de ligar coisa alguma, e com ele
desapareceu uma classe inteira de erro que só a conferência pegava — código
órfão, código repetido, participante colado na agenda errada. O `Código` continua
na planilha como referência da linha, porque é por ele que as mensagens de erro
chamam a agenda de que estão falando, e **pode ficar em branco**: o servidor
gera `linha N`.

**Temas e áreas também são colunas numeradas** (Tema 1–3, Área 1–2), pelo mesmo
motivo, e eram assim desde o primeiro desenho.

### A coluna Data é travada como data

Pedido do dono do produto, e o defeito mais silencioso da planilha: numa coluna
sem formato, `25/09/26`, `set/25`, `25.09.2026` e o texto `amanhã` são todos
aceitos sem reclamação, chegam ao servidor como texto, e a conferência acusa
"data ilegível" numa linha que a pessoa jurava ter preenchido — depois de ela já
ter feito as 54.

Duas metades, e cada uma resolve um problema diferente:

- **validação de data** (`greaterThanOrEqual DATE(2000,1,1)`, com
  `showErrorMessage`) recusa na célula o que não é data. O piso não julga a
  agenda: existe porque a validação de data do Excel exige um operador. **Sem
  teto** — agenda prevista é caso normal, e um teto recusaria dado legítimo;
- **formato `DD/MM/YYYY` na dimensão da coluna**, que é o que faz o Excel
  *interpretar* a digitação como data brasileira. Numa célula "Geral" a mesma
  digitação pode virar texto, e então a validação recusaria o que estava certo.

`allow_blank` continua verdadeiro: a linha em branco é normal no meio do arquivo,
e o `idem` herda a data da linha de cima.

### Abas de vocabulário

**Editáveis** — acrescentar linha cadastra: Instituições · Interlocutores ·
Pessoas da Aegea · Temas · Unidades de negócio · Tipos de interação · Áreas.

**Somente leitura**, protegidas e visualmente distintas: Situação · Clima ·
Resultado · Iniciativa · Modalidade · Presença · Papel · Momento.

São os vocabulários **FECHADOS** de `api/dicionarios.py`, sobre os quais o
código já diz: "mudar um valor aqui é mudança de regra, então é código e
migration", porque os KPIs e a taxa de resolutividade dependem deles. **O
servidor recusa valor novo nesses vocabulários mesmo que alguém desproteja a
aba.**

### O que não entra na planilha

**Frente, Esfera e Tier são derivados** da instituição, não digitados. Pô-los na
planilha abriria a chance de a agenda contradizer o cadastro do órgão — que é
exatamente o que a derivação resolveu.

**O interlocutor principal não é coluna**: é o `Interlocutor 1`. Com abas filhas
havia uma coluna `Principal` para marcá-lo; em colunas numeradas, listar a pessoa
mais importante primeiro é mais fácil de preencher — e mais difícil de
contradizer — do que responder "qual número é o principal".

### Fora da primeira versão

**Os campos por frente** (link da matéria, casa, tramitação, tipo de
investidor). São um registro variante; numa planilha plana viram vinte colunas
com dezoito sempre vazias. A agenda importada sem eles é válida — `extensao` é
anulável — e quem precisar completa na ficha.

**A "Consulta recebida"**. É outro tipo de registro, com canal, remetente, teor
e prazo próprios, e `validar_consulta` recusa o bloco fora do tipo certo. A
planilha **recusa esse tipo** com mensagem dizendo para registrá-lo pela tela.

---

## Classificação: o que vira divergência

Quatro desfechos por célula.

**1. Resolve sozinho.** Casa com um existente depois de normalizar caixa,
acento e espaço — usando `app/dominio/texto.py › normalizar`, que já existe e
cujo docstring diz, em tantas palavras, que "`nome_normalizado` existe para a
importação deduplicar 'Radamés' e 'Radames'". A regra foi escrita para este
fluxo; não se inventa outra.

(Nota para quem implementar: `api/stakeholders.py:223` tem um `_normalizar`
próprio. Conferir se é a mesma regra e, se for, unificar — duas normalizações
fariam a importação deduplicar diferente do cadastro pela tela.)

**2. Confirmação — "vou criar isto".** O nome não existe **e está na aba
editável**. Aparece agrupado e contado antes de confirmar; criar três
instituições é ato consequente demais para acontecer calado.

**3. Divergência** — precisa de decisão, resolvida **uma vez por valor**.

**4. Recusa do arquivo inteiro** — aba faltando, coluna faltando ou `Código`
repetido. (O `Código` órfão saiu com as abas filhas: não há mais vínculo a
quebrar.) Nada é
proposto: não faz sentido oferecer 54 propostas quando o cabeçalho está errado.

### A distinção que sustenta a decisão de produto

**Escrever na aba editável é declaração de intenção. Digitar direto na célula da
agenda, não.**

Um nome que aparece na aba **Instituições** é a pessoa dizendo "esta é nova,
cadastre". O mesmo nome aparecendo só na coluna Instituição, sem casar com
nada, é muito mais provavelmente erro de grafia — e vira divergência com os
nomes parecidos ao lado.

É o que permite atender ao pedido do cliente sem o efeito que a `0008` alerta.

### Tabela

| Situação | Desfecho |
|---|---|
| Instituição/interlocutor/tema/unidade/área **na aba editável** | Confirmação — cria |
| O mesmo, digitado só na célula, sem casar | Divergência, com os parecidos e a opção de criar |
| Valor fora de vocabulário **fechado** | Divergência; só se resolve escolhendo um válido |
| Data ou Instituição em branco | Divergência — é o mínimo que identifica uma agenda |
| Data ilegível ou fora de faixa | Divergência na linha |
| Pessoa que não pertence à instituição da agenda | Divergência |
| Material com título e sem destino, ou o contrário | Divergência na linha |
| Linha inteiramente vazia | Ignorada, sem ruído |
| Mesma instituição e mesma data de agenda já existente | Divergência **informativa** — não trava |

### As regras do formulário precisam de casa no servidor

As seis recusas de `front/src/paginas/cadastro/impedimento.ts` são TypeScript, e
a importação é Python. Duplicá-las criaria duas versões da mesma verdade.

**Decisão:** a importação implementa em Python **só as que uma planilha pode de
fato produzir** — participante fora da instituição, material pela metade — e um
teste prende as duas listas, no mesmo padrão de `_DE_TEXTO` e do `DESTINO` de
`corpo.test.ts`. As outras quatro são artefatos de formulário meio preenchido,
que planilha não gera.

---

## A tela de conferência

Cabeçalho que responde "quanto falta": **54 agendas · 6 pendências · 3 cadastros
novos**. Três blocos em ordem de urgência.

**O que precisa de você** — divergências agrupadas por valor, ordenadas por
quantas linhas cada uma segura:

> **Instituição não encontrada: "Prefeitura de Campinas"** — em 12 linhas
> Parecidas: *Prefeitura Municipal de Campinas* · *Prefeitura de Campos*
> → [apontar para uma existente] · [cadastrar como nova] · [descartar as 12 linhas]

Uma decisão, doze linhas. É o que faz a conferência escalar com o volume em vez
de crescer junto com ele.

**O que vou criar** — as confirmações, recolhidas por padrão.

**As 54 linhas** — segunda vista, com filtro "só as que têm pendência", e onde
se descarta uma linha específica.

### Duas severidades

**Trava**: instituição não encontrada, valor fora de vocabulário fechado, data
ausente.

**Avisa**: possível duplicata. Mostra a agenda existente e **não impede
confirmar** — duas reuniões com o mesmo órgão no mesmo dia acontecem, e travar
por isso ensinaria a ignorar o aviso.

O botão de confirmar acende quando não resta nenhuma das que travam.

### O banco muda entre subir e confirmar

A proposta é calculada no upload. Entre ele e a confirmação, alguém pode
cadastrar aquela instituição pela tela de Administração, ou desativar uma que a
planilha usava. Confirmar cegamente criaria a duplicata que a conferência
existia para evitar.

**A resolução é refeita na confirmação**, contra o estado atual. Se algo mudou
— o que ia ser criado já existe, o que estava resolvido sumiu — a confirmação
**para** e mostra o que mudou. É um passo a mais no caminho feliz e é o que
impede a janela entre as duas ações de virar defeito silencioso.

### A confirmação é uma transação só

Cadastros novos e agendas nascem no mesmo commit. Ou tudo entra, ou nada entra
— não existe estado em que as instituições foram criadas e as agendas não. É
também o que faz cancelar não deixar resíduo.

### Três detalhes de uso real

- **A importação sobrevive a fechar o navegador**: está gravada. É para isso que
  a `0008` criou tabela em vez de resolver em memória.
- **Teto de 500 agendas por arquivo.** Acima disso a tela deixa de ser
  conferível e a transação fica longa demais para uma requisição. Um dia de 54
  cabe dez vezes.
- **A procedência fica gravada**: `fonte`, `origem_aba` e `origem_linha` em cada
  agenda criada, e o arquivo bruto em `importacao_linha.dados_brutos`.

---

## Arquitetura

### Uma descrição, dois consumidores

O formato da planilha é **uma descrição declarativa** em
`app/dominio/importacao_de_agendas.py`: quais abas existem, quais colunas cada
uma tem, contra qual vocabulário cada coluna valida, quais vocabulários são
fechados. Pura — sem banco e sem `openpyxl`.

Dois consumidores a leem: **o gerador**, que a transforma no `.xlsx` com as
listas suspensas; e **o leitor**, que interpreta o arquivo preenchido.

Se o formato morasse duas vezes, modelo e leitor divergiriam no dia em que
alguém acrescentasse uma coluna — e a pessoa preencheria uma coluna que o leitor
ignora, sem erro nenhum. Mesmo princípio de `materiaisDoTema`, onde a construção
e a comparação são a mesma função.

### Módulos

| Onde | O que faz |
|---|---|
| `dominio/importacao_de_agendas.py` | a descrição do formato, a classificação, o agrupamento por valor. Puro |
| `casos_de_uso/modelo_de_importacao.py` | descrição + vocabulários atuais → bytes do `.xlsx` |
| `casos_de_uso/importar_agendas.py` | ler → propor → gravar; resolver; confirmar |
| `banco/repositorio_importacao.py` | as duas tabelas da `0008` |
| `api/importacoes.py` | as rotas |

### Rotas

Sob `/api/importacoes`, em router com `exigir_portal_crm` **e** a dependência de
quem administra cadastros — no router, não em cada rota, como o resto do
projeto.

| Rota | O que faz |
|---|---|
| `GET /modelo` | gera e baixa o `.xlsx` com os vocabulários do momento |
| `POST /` | sobe o arquivo, propõe, grava, devolve o estado |
| `GET /{id}` | retoma uma conferência em andamento |
| `PATCH /{id}/resolucoes` | registra a decisão de um grupo de divergência |
| `POST /{id}/confirmacao` | reconfere, cria tudo numa transação |

---

## Como isso se prova

**Ida e volta do arquivo.** Gera o modelo, preenche programaticamente, lê de
volta, confere que **cada coluna sobreviveu**. É o `corpo.test.ts` desta
funcionalidade, e é o que pega a coluna acrescentada à descrição que o leitor
não trata.

**Todo campo classificado.** Um dicionário dizendo, para cada campo de
`InteracaoEntrada`, se ele vem da planilha, é derivado ou está fora da v1 — com
teste comparando contra os campos reais do modelo. Acrescentar um campo obriga a
decidir, em vez de descobrir depois que ele nunca chegou.

**Uma consulta por vocabulário, não por linha.** 500 agendas não podem virar 500
buscas de instituição; os vocabulários são lidos uma vez, como
`catalogo_das_lentes` já faz. Entra em `test_leitura_sem_consulta_por_linha`.

**A transação.** Cancelar não deixa cadastro; confirmar cria tudo ou nada; a
reconferência pega o vocabulário que mudou entre subir e confirmar.

**A recusa.** `crm_edicao` leva 403 em todas as rotas, e `/api/importacoes`
entra na âncora estrutural que varre a aplicação montada — a mesma que cobre
`/api/score`. Rota nova sob esse prefixo nasce protegida ou o teste quebra.

**A distinção aba/célula.** Nome na aba editável cria; o mesmo nome só na célula
vira divergência. É a regra que sustenta a decisão de produto e precisa de teste
próprio nos dois sentidos.

---

## Sobre o tamanho disto

É uma funcionalidade só, mas grande. Ela **não se decompõe em entregas
independentes** — modelo sem leitor não serve, e leitor sem conferência não
pode criar nada. O plano de implementação deve, porém, ordená-la em fases que
se provam sozinhas:

1. a descrição do formato e o gerador do `.xlsx` (prova: o arquivo abre no Excel
   com as listas funcionando);
2. o leitor e a classificação, sem gravar nada (prova: planilha entra, lista de
   propostas e divergências sai);
3. a persistência e a tela de conferência;
4. a confirmação transacional, com a reconferência.

Cada fase é verificável ao fim de si mesma, e é essa a ordem em que o risco cai.

## Fora de alcance

- Campos por frente e "Consulta recebida" (ver *O modelo*).
- Edição de agendas existentes por planilha — este fluxo só **cria**.
- Importação por outro papel que não a coordenação.
- Histórico de importações como tela. As tabelas guardam; a listagem pode vir
  depois.

## Pendente de resposta

**O perfil real das 54 reuniões.** Se a maioria for de frentes com campos
próprios (Imprensa, Legislativo, Investidores) ou consultas recebidas, o recorte
de "fora da primeira versão" precisa ser revisto antes da implementação.

---

## Emenda de 26/09: dois modelos, e o fim do `Código` e do `idem`

Pedido do dono do produto depois de usar o modelo de aba única. Três mudanças,
todas com a mesma origem: **o caso real é um evento**, onde 54 agendas do mesmo
dia repetem quase tudo.

### Dois modelos, um formato

A planilha de 59 colunas descreve a agenda inteira — os campos de antes e os de
depois da reunião, os quatro interlocutores, os três materiais. Num evento, isso
é uma tela de rolagem horizontal para preencher quatro coisas por linha.

Passam a existir **dois modelos do MESMO formato**, e a escolha é no download:

| Modelo | Para quê | Colunas |
|---|---|---|
| **Completo** | a agenda que merece registro inteiro | as 59 (menos o `Código`) |
| **Simplificado** | o evento com muitas conversas curtas | 22 |

O simplificado tem: `Repetir a linha de cima` · Tipo de interação · Área 1–2 ·
Data · Instituição · UF · Unidade de negócio · Tema 1–3 · Modalidade · Local ·
Relato · Repercussão e encaminhamentos · Observações · Clima · Desfecho ·
Interlocutor 1–2 · Pessoa da Aegea 1–2.

**UMA descrição, dois recortes.** O modelo simplificado é um SUBCONJUNTO ORDENADO
da descrição única, nomeado por colunas — não uma segunda descrição. Duas
descrições divergiriam na primeira coluna nova, e o leitor passaria a aceitar de
um modelo o que recusa do outro.

**O leitor aceita os dois sem perguntar qual é.** Ele não recebe o nome do modelo:
confere que (a) nenhuma coluna é desconhecida e (b) as obrigatórias estão todas
lá. Isso também acolhe o arquivo de quem apagou colunas que não ia usar, que é
comportamento normal de quem trabalha em planilha. Exigir o cabeçalho exato de um
dos dois recusaria o arquivo inteiro por uma coluna apagada — o pior erro possível
num arquivo de 500 linhas.

**Sem Presença e sem Papel, o simplificado não perde nada que o domínio exija:**
`papel` nasce `porta_voz` por padrão e `presenca` é anulável ("não informado").

### O `Código` sai

Ele existia para ligar a aba de agendas às três abas filhas. As abas filhas
morreram na mudança para aba única, e ele ficou sendo uma coluna que a pessoa
preenchia para nada — quando não a deixava em branco e recebia `linha 3` gerado
pelo servidor.

O que ele ainda fazia, e para onde foi: identificar a agenda nas mensagens e no
descarte de linha passou a ser o **número da linha no arquivo**, que é o que a
pessoa usa para voltar à planilha e conferir.

### O `idem` sai, e no lugar dele entra uma coluna

O marcador `idem` era escolhido DENTRO de qualquer lista suspensa, e a linha toda
herdava. Funcionava, e era difícil de descobrir: ninguém abre a suspensa de Clima
esperando encontrar ali uma instrução sobre a linha.

Entra, na primeira coluna — o lugar que era do `Código` —, **`Repetir a linha de
cima`**, com uma suspensa de um valor só: `sim`. Marcar significa que a linha
repete tudo o que a de cima tinha, e **o que a pessoa escrever na própria linha
vence a herança**. É o caso do evento: marca `sim`, troca só a instituição.

O `idem` deixa de existir nas duas planilhas, e sai de todas as listas de
vocabulário — onde ele nunca foi um valor daquele vocabulário.

### A conferência vira a planilha

Depois de subir, a conferência passa a mostrar **a planilha como a pessoa a
preencheu**, em grade, com a cor dizendo o que falta:

- **vermelho** na célula que TRAVA a confirmação;
- **amarelo** na que só avisa;
- a célula vermelha é **editável ali mesmo**, e a linha é reproposta ao salvar.

A grade SUBSTITUI a tabela de linhas anterior, que mostrava "linha 3 · falta a
Data" sem mostrar a linha. Duas vistas das mesmas linhas — uma em grade e uma em
lista — obrigariam a pessoa a cruzar as duas para entender uma pendência.
