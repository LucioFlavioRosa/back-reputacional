# Dois modelos de planilha, sem `Código` e sem `idem` — Plano

**Spec:** `docs/superpowers/specs/2026-09-25-importacao-de-agendas-design.md`,
emenda de 26/09.

**Objetivo:** dois modelos do mesmo formato (completo e simplificado), a primeira
coluna virando `Repetir a linha de cima`, o `Código` e o `idem` fora, e a
conferência mostrando a planilha em grade colorida e editável.

## Restrições globais

- UMA descrição do formato. O simplificado é um subconjunto ORDENADO por nomes de
  coluna, nunca uma segunda descrição.
- O leitor NÃO recebe o nome do modelo: aceita qualquer cabeçalho sem coluna
  desconhecida e com as obrigatórias presentes.
- Nenhuma migration nova. O que precisa viajar vai dentro do JSONB, como
  `__herdado__` e `__corrigido__` já fazem.
- TDD em cada tarefa: teste que eu vi falhar, depois o código.

## Tarefa 1 — Domínio: os dois modelos e a coluna de repetição

- `COLUNA_DE_REPETICAO = "Repetir a linha de cima"`, primeira coluna, sem campo.
- `VALOR_DA_REPETICAO = "sim"`.
- `MARCADOR_DE_REPETICAO` e `Código` removidos (`COLUNA_DO_CODIGO` também).
- `MODELOS: dict[str, tuple[str, ...]]` — `completo` (todas) e `simplificado` (as
  22 nomeadas na spec); `colunas_do_modelo(nome)` devolve os `Coluna` na ordem.
- Guarda: todo nome em `MODELOS["simplificado"]` existe na descrição.
- Guarda: as obrigatórias estão em TODOS os modelos — um modelo que omitisse a
  Data geraria arquivo que o servidor recusa inteiro.

## Tarefa 2 — Leitor: cabeçalho tolerante e herança pela coluna

- o cabeçalho passa a ser validado por (a) nada desconhecido, (b) obrigatórias
  presentes; as mensagens nomeiam o que sobrou e o que falta.
- a herança lê `Repetir a linha de cima`, e não mais qualquer célula com `idem`.
- `codigo_da_linha`/`PREFIXO_DO_CODIGO_GERADO`/a unicidade do código: fora.

## Tarefa 3 — Gerador: `modelo` como parâmetro

- `gerar(vocabularios, interlocutores, modelo="completo")`.
- a coluna de repetição ganha suspensa literal `"sim"`, sem travar.
- `idem` sai de todas as listas de vocabulário.
- a validação dependente do interlocutor e a trava da data seguem a coluna pelo
  NOME, então funcionam nos dois modelos sem saber qual é.

## Tarefa 4 — API: escolher o modelo e dizer as colunas

- `GET /modelo?modelo=completo|simplificado`, com recusa nomeando os válidos.
- `ImportacaoSaida.colunas`: as colunas daquele arquivo, NA ORDEM — é o que a
  grade usa como cabeçalho.
- `_linhas_para_reler`: o descarte passa a ser por `linha_origem`.

## Tarefa 5 — Front: o modal de escolha do modelo

- "Importar planilha" abre um modal com os dois modelos, cada um com uma linha
  dizendo para quem serve e quantas colunas tem.

## Tarefa 6 — Front: a conferência em grade colorida

- `corDaCelula(linha, coluna)`: vermelho onde trava, amarelo onde avisa, nada no
  resto — módulo testável, fora do JSX.
- a grade substitui a tabela de linhas, com rolagem horizontal, cabeçalho fixo e
  a célula vermelha editável.

## Tarefa 7 — Revisão do Codex e pilha reconstruída
