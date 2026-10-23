# Explorador de veículos — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir os três cartões de veículo da Síntese executiva por um bloco único de três painéis que se filtram entre si no navegador, alimentado por uma rota nova que devolve o mês agrupado por tier × veículo.

**Architecture:** O back ganha `grupos_de_veiculos` (quase cópia de `grupos_do_explorador`, com a chave `(tier, veiculo)`) e a rota `GET /{codigo}/explorador-de-veiculos`. O front faz **um** pedido por mês e recorte, guarda os grupos e cruza tudo somando no navegador — o clique não vai ao servidor e o dossiê não se move. A seleção tem **dois eixos** (`tier`, `veiculo`), e o eixo clicado continua inteiro.

**Tech Stack:** Back: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, pytest. Front: React 19, TypeScript, Vite, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-23-explorador-de-veiculos-design.md`

## Global Constraints

- **A suíte do back não roda no Python do Windows.** Roda num container da imagem da api, como root, com o repo montado — ver o comando exato no passo de teste de cada tarefa do back. Nunca duas execuções ao mesmo tempo (destroem o mesmo banco de teste).
- **No front, a checagem de tipo é `npx tsc -b`, nunca `tsc --noEmit`** — aqui o `--noEmit` não verifica nada e passa verde com erro de tipo.
- **Nunca cortar veículos em silêncio.** Se a rota ganhar teto, ele vem com uma linha de "outros" explícita; um corte silencioso faria as somas dos painéis não fecharem com a nota.
- **O dossiê não se move com o clique.** A seleção é local ao bloco; nada de `definirFiltro` nos três painéis.
- **O eixo clicado continua inteiro**, com o item em destaque. É a razão de ser do molde.
- **Rótulo do tier:** `ROTULO_DO_TIER` de `src/dominio/filtrosDasLentes.ts` (`muito_relevante` → "Tier 1"), na ordem fixa `['muito_relevante', 'relevante', 'menos_relevante']`.
- **O painel 2 chama-se "Top veículos"** — sem "Matérias por tier e".
- **O bloco aparece só para `LENTES_COM_BLOCOS_DE_VEICULO`** (`['imprensa', 'mercado']`).
- **`condicoes_do_filtro` casa por subconsulta, nunca por junção.** Não acrescentar `join` de `Tema`/`MacroTema` na consulta nova.
- **Codex revisa antes de qualquer coisa ir ao `main`** (instrução permanente do projeto).

## Review Focus

1. **O mesmo veículo em dois tiers** — a rota emite uma linha por `(tier, veiculo)`, então "Folha" com matéria de Tier 1 e de Tier 2 chega em duas linhas; o painel 2 tem de **somá-las** quando nenhum tier está escolhido, senão o mesmo veículo aparece duas vezes na lista. (Teste na Tarefa 4.)
2. **Menção sem tier ou sem veículo** — fica fora da barra do **próprio** eixo e continua valendo no outro, como no molde ("Menção sem o campo daquele nível fica fora DESTA barra, e continua valendo nas outras"). (Teste nas Tarefas 2 e 4.)
3. **Denominador zero** — mês sem menção que entre na régua faria o impacto virar `Infinity`/`NaN` na tela. (Teste na Tarefa 4.)
4. **Resposta atrasada** — trocar mês ou recorte duas vezes rápido e a resposta do primeiro pousar sobre o segundo. A guarda é a chave do pedido. (Teste na Tarefa 5.)
5. **Mês com 5 veículos ou menos** — o botão "Ver todos" não deve nascer, pela guarda `teto > inicial`. (Teste na Tarefa 5.)

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app/banco/repositorio_lentes.py` (modificar) | `grupos_de_veiculos`: a consulta e o colapso na chave `(tier, veiculo)` |
| `app/esquemas/lentes.py` (modificar) | `GrupoDeVeiculoSaida`, `ExploradorDeVeiculosSaida` |
| `app/api/lentes.py` (modificar) | a rota `GET /{codigo}/explorador-de-veiculos` |
| `tests/test_explorador_de_veiculos.py` (criar) | repositório e rota |
| `src/api/score.ts` (modificar) | `GrupoDeVeiculo`, `ExploradorDeVeiculos`, `obterExploradorDeVeiculos` |
| `src/dominio/exploradorDeVeiculos.ts` (criar) | a conta: `gruposNaSelecao`, `barrasDoTier`, `barrasDoVeiculo`, `termometroDosVeiculos` |
| `src/dominio/exploradorDeVeiculos.test.ts` (criar) | a conta, incluindo a regra dos dois eixos |
| `src/paginas/score/ExploradorDeVeiculos.tsx` (criar) | os três painéis, os chips e o Limpar |
| `src/paginas/score/ExploradorDeVeiculos.test.tsx` (criar) | o componente |
| `src/dominio/guiaDoDossie.ts` (modificar) | a ajuda do bloco novo |
| `src/paginas/score/DossieDaLente.tsx` (modificar) | os três cartões saem, o bloco entra |
| `src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx` (modificar) | os testes dos cartões que saíram |

---

### Task 1: Medir a cardinalidade de tier × veículo

Sem esta medida a rota não está fechada — é a condição que o desenho impõe. O número real nunca apareceu em tela nenhuma, porque os blocos de hoje sempre vêm cortados em 10.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-23-explorador-de-veiculos-design.md` (a seção "O tamanho da carga")

**Interfaces:**
- Consumes: nada.
- Produces: a decisão `com teto` ou `sem teto`, que a Tarefa 2 lê.

- [ ] **Step 1: Conferir que a pilha local está no ar**

```powershell
docker ps --format "{{.Names}}`t{{.Status}}"
```

Expected: `painel-reputacional-banco-1` aparece com `Up ... (healthy)`. Se não estiver:

```powershell
docker compose -p painel-reputacional -f back-reputacional/docker-compose.pilha.yml up -d
```

- [ ] **Step 2: Medir o pior mês**

```powershell
docker exec painel-reputacional-banco-1 psql -U postgres -d painel_reputacional -c "select m.mes, count(distinct m.veiculo) as veiculos, count(distinct (m.tier, m.veiculo)) as grupos, count(*) as mencoes from mencao m group by m.mes order by grupos desc limit 5;"
```

Expected: uma tabela com cinco linhas. A coluna `grupos` do primeiro mês é o tamanho da carga no pior caso.

- [ ] **Step 3: Decidir o teto e escrever a medida na especificação**

A régua, com a razão: cada linha tem nove campos e sai em ~120 bytes de JSON.

- `grupos` **≤ 2000** (≈ 240 KB): **sem teto**. É da ordem do que o `/explorador` de taxonomia já manda, e a rota segue como o desenho descreve.
- `grupos` **> 2000**: **com teto**. A rota passa a ordenar por volume decrescente, cortar nos 300 primeiros veículos e acrescentar **uma linha por tier** com `veiculo = null` somando todo o resto — a linha de "outros". Assim a soma dos pesos continua sendo o denominador do mês, e o painel 2 mostra "outros" como um item explícito em vez de perder matéria.

Substituir, na seção "O tamanho da carga: medir antes de fechar", o parágrafo que começa com "**O primeiro passo da implementação mede isso na base de dev**" por:

```markdown
**Medido em 23/10/2026** na base da pilha local: o pior mês tem `<N>` veículos
distintos e `<G>` grupos `(tier, veículo)` em `<M>` menções. Decisão:
`<sem teto | com teto de 300 veículos + linha de "outros" por tier>`.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-23-explorador-de-veiculos-design.md
git commit -m "docs: a carga do explorador de veiculos, medida na pilha local"
```

---

### Task 2: `grupos_de_veiculos` no repositório

**Files:**
- Modify: `app/banco/repositorio_lentes.py` (logo depois de `grupos_do_explorador`, que termina na linha 1017)
- Test: `tests/test_explorador_de_veiculos.py` (criar)

**Interfaces:**
- Consumes: a decisão de teto da Tarefa 1.
- Produces: `grupos_de_veiculos(sessao: Session, lente_id: int, mes: date, calibracao: Calibracao, regua: str, filtro: FiltroDeMencoes | None = None) -> list[dict]`, cada dict com as chaves `tier`, `veiculo`, `positivo`, `neutro`, `negativo`, `peso_positivo`, `peso_neutro`, `peso_negativo`.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_explorador_de_veiculos.py`. O cabeçalho das fixtures é o mesmo de `tests/test_consulta_da_lente.py:36-121` — copiar `MES`, `TEXTO_DO_MES`, a fixture `sessao`, `_QuemOlha`, `_gravar`, `_linhas_da_imprensa` e `_lente` de lá, com os mesmos imports.

```python
def test_os_grupos_saem_por_tier_e_veiculo_com_o_peso_no_lado_certo(sessao):
    """Uma linha por (tier, veículo), com a contagem e o peso no lado do
    sentimento. É o que a tela soma para desenhar os três painéis."""
    linhas = _linhas_da_imprensa(sessao)
    veiculos = ["Folha", "Folha", "Valor", "Valor", "Estadão", "Estadão"]
    for linha, veiculo in zip(linhas, veiculos, strict=True):
        linha["veiculo"] = veiculo
    _gravar(sessao, "clipei", linhas)
    lente = _lente(sessao, "imprensa")
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, denominador = repositorio_score.denominador_do_mes(
        sessao, lente.id, MES, calibracao
    )

    grupos = repositorio_lentes.grupos_de_veiculos(
        sessao, lente.id, MES, calibracao, regua
    )

    #: AS SEIS MENÇÕES INTEIRAS, sem perder nem duplicar nenhuma.
    assert sum(g["positivo"] + g["neutro"] + g["negativo"] for g in grupos) == 6
    #: A SOMA DOS PESOS É O DENOMINADOR DO MÊS — é isto que faz o impacto de
    #: cada barra fechar com a nota, a mesma invariante do explorador de
    #: taxonomia.
    assert sum(
        g["peso_positivo"] + g["peso_neutro"] + g["peso_negativo"] for g in grupos
    ) == pytest.approx(denominador)

    #: UMA LINHA POR PAR, e "Folha" chega em DOIS tiers: a soma por veículo é
    #: trabalho da tela, e a rota não a antecipa.
    pares = {(g["tier"], g["veiculo"]) for g in grupos}
    assert ("muito_relevante", "Folha") in pares
    assert ("relevante", "Folha") in pares

    #: O PESO CAI NO LADO DO SENTIMENTO: a primeira linha é negativa.
    folha_t1 = next(
        g for g in grupos if g["tier"] == "muito_relevante" and g["veiculo"] == "Folha"
    )
    assert folha_t1["negativo"] == 1 and folha_t1["positivo"] == 0
    assert folha_t1["peso_negativo"] > 0
    assert folha_t1["peso_positivo"] == 0

    #: CARGO E ENGAJAMENTO NÃO SAEM: entram no group_by só porque
    #: `peso_da_mencao` precisa deles.
    assert set(grupos[0]) == {
        "tier", "veiculo", "positivo", "neutro", "negativo",
        "peso_positivo", "peso_neutro", "peso_negativo",
    }


def test_mencao_sem_tier_ou_sem_veiculo_nao_derruba_a_consulta(sessao):
    """Nulo é dado, não erro: a menção entra com o campo vazio, e a tela a
    deixa fora da barra DAQUELE eixo sem a tirar do outro."""
    linhas = _linhas_da_imprensa(sessao)
    linhas[0]["tier"] = None
    linhas[1]["veiculo"] = None
    _gravar(sessao, "clipei", linhas)
    lente = _lente(sessao, "imprensa")
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, _ = repositorio_score.denominador_do_mes(sessao, lente.id, MES, calibracao)

    grupos = repositorio_lentes.grupos_de_veiculos(
        sessao, lente.id, MES, calibracao, regua
    )

    assert sum(g["positivo"] + g["neutro"] + g["negativo"] for g in grupos) == 6
    assert any(g["tier"] is None for g in grupos)
    assert any(g["veiculo"] is None for g in grupos)
```

- [ ] **Step 2: Rodar o teste e confirmar que ele falha**

```powershell
$b = "C:\Users\LúcioFláviodosSantos\OneDrive - Peers Consulting\Área de Trabalho\aegea\painel reputação\back-reputacional"
docker run --rm --user root --network painel-reputacional_default `
  -v "${b}:/src" -w /src `
  -e BANCO_URL_TESTE="postgresql+psycopg2://postgres:postgres@painel-reputacional-banco-1:5432/painel_reputacional" `
  painel-reputacional-api sh -c "pip install -q --no-cache-dir pytest httpx; python -m pytest tests/test_explorador_de_veiculos.py -q"
```

Expected: FAIL com `AttributeError: module 'app.banco.repositorio_lentes' has no attribute 'grupos_de_veiculos'`.

- [ ] **Step 3: Implementar a função**

Em `app/banco/repositorio_lentes.py`, depois de `grupos_do_explorador`:

```python
def grupos_de_veiculos(
    sessao: Session,
    lente_id: int,
    mes: date,
    calibracao: Calibracao,
    regua: str,
    filtro: FiltroDeMencoes | None = None,
) -> list[dict]:
    """As menções do mês agrupadas por tier e veículo — o que os três painéis
    do Explorador de veículos somam na tela.

    O MESMO MECANISMO DE `grupos_do_explorador`, com uma chave menor: agregado
    pronto para ser somado no navegador, e é isso que faz o clique ser
    instantâneo sem mover o dossiê. Cada linha traz a contagem (o que a barra
    desenha) e o peso por sentimento (o que a nota e o impacto usam).

    UMA LINHA POR PAR `(tier, veiculo)`, e não por veículo: o mesmo veículo
    pode ter matéria em mais de um tier, e somar aqui tiraria da tela a
    possibilidade de estreitar por tier. A soma por veículo é trabalho de quem
    desenha.

    `cargo` e `engajamento` ENTRAM NO `group_by` SÓ PORQUE `peso_da_mencao`
    PRECISA DELES, e não saem na resposta — o mesmo motivo pelo qual estão em
    `grupos_do_explorador`.

    SEM JUNÇÃO DE `Tema`/`MacroTema`: esta consulta não lê taxonomia, e os
    filtros de taxonomia da tela continuam valendo porque
    `condicoes_do_filtro` casa por subconsulta, nunca por junção.
    """
    consulta = (
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
        .group_by(
            Mencao.tier,
            Mencao.veiculo,
            Mencao.sentimento,
            Mencao.cargo,
            Mencao.engajamento,
        )
    )
    grupos: dict[tuple, dict] = {}
    for linha in sessao.execute(consulta):
        chave = (linha.tier or None, linha.veiculo or None)
        grupo = grupos.setdefault(
            chave,
            {
                "tier": chave[0],
                "veiculo": chave[1],
                "positivo": 0,
                "neutro": 0,
                "negativo": 0,
                "peso_positivo": 0.0,
                "peso_neutro": 0.0,
                "peso_negativo": 0.0,
            },
        )
        lado = {"pos": "positivo", "neg": "negativo"}.get(linha.sentimento, "neutro")
        peso = peso_da_mencao(linha.tier, linha.cargo, linha.engajamento, calibracao, regua)
        grupo[lado] += int(linha.quantas)
        grupo[f"peso_{lado}"] += peso * int(linha.quantas)
    return list(grupos.values())
```

- [ ] **Step 3b: O teto, SÓ se a Tarefa 1 decidiu "com teto"**

Se a Tarefa 1 decidiu **sem teto**, pular para o Step 4.

Primeiro o teste, em `tests/test_explorador_de_veiculos.py`:

```python
def test_o_teto_soma_o_resto_numa_linha_de_outros_por_tier(sessao, monkeypatch):
    """Cortar em silêncio faria a soma dos painéis não fechar com a nota: o
    que passa do teto vira UMA linha por tier, com `veiculo` nulo."""
    monkeypatch.setattr(repositorio_lentes, "TETO_DE_VEICULOS", 2)
    linhas = _linhas_da_imprensa(sessao)
    veiculos = ["Folha", "Folha", "Folha", "Valor", "Estadão", "Metrópoles"]
    for linha, veiculo in zip(linhas, veiculos, strict=True):
        linha["veiculo"] = veiculo
    _gravar(sessao, "clipei", linhas)
    lente = _lente(sessao, "imprensa")
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, denominador = repositorio_score.denominador_do_mes(
        sessao, lente.id, MES, calibracao
    )

    grupos = repositorio_lentes.grupos_de_veiculos(
        sessao, lente.id, MES, calibracao, regua
    )

    #: NADA SE PERDE: as seis menções e o denominador continuam inteiros.
    assert sum(g["positivo"] + g["neutro"] + g["negativo"] for g in grupos) == 6
    assert sum(
        g["peso_positivo"] + g["peso_neutro"] + g["peso_negativo"] for g in grupos
    ) == pytest.approx(denominador)
    #: OS DOIS MAIORES PELO NOME, o resto em "outros" (`veiculo` nulo).
    nomes = {g["veiculo"] for g in grupos}
    assert "Folha" in nomes and "Valor" in nomes
    assert "Estadão" not in nomes and "Metrópoles" not in nomes
    assert None in nomes
```

Rodar e confirmar que falha (`AttributeError: ... has no attribute 'TETO_DE_VEICULOS'`), e então implementar. Em `app/banco/repositorio_lentes.py`, acima de `grupos_de_veiculos` — se `Counter` não estiver nos imports do arquivo, acrescentar `from collections import Counter`:

```python
#: Quantos veículos a rota manda nome por nome antes de somar o resto em
#: "outros" — ver a medição na especificação do Explorador de veículos.
TETO_DE_VEICULOS = 300


def _com_teto_de_veiculos(grupos: list[dict], teto: int) -> list[dict]:
    """Os `teto` veículos de maior volume nome por nome; o resto somado por
    tier numa linha de `veiculo` nulo — a linha de "outros".

    O CORTE NÃO PODE PERDER MATÉRIA: a soma dos pesos continua sendo o
    denominador do mês, senão o impacto das barras deixaria de fechar com a
    nota — e um corte silencioso é exatamente o que o desenho proíbe.
    """
    volume: Counter[str | None] = Counter()
    for grupo in grupos:
        volume[grupo["veiculo"]] += grupo["positivo"] + grupo["neutro"] + grupo["negativo"]
    maiores = {veiculo for veiculo, _ in volume.most_common(teto)}
    saida: dict[tuple, dict] = {}
    for grupo in grupos:
        veiculo = grupo["veiculo"] if grupo["veiculo"] in maiores else None
        chave = (grupo["tier"], veiculo)
        alvo = saida.get(chave)
        if alvo is None:
            saida[chave] = {**grupo, "veiculo": veiculo}
            continue
        for campo in (
            "positivo", "neutro", "negativo",
            "peso_positivo", "peso_neutro", "peso_negativo",
        ):
            alvo[campo] += grupo[campo]
    return list(saida.values())
```

E, em `grupos_de_veiculos`, trocar o `return list(grupos.values())` por:

```python
    return _com_teto_de_veiculos(list(grupos.values()), TETO_DE_VEICULOS)
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Mesmo comando do Step 2.
Expected: PASS, 2 passed.

- [ ] **Step 5: Rodar a suíte inteira do back**

```powershell
$b = "C:\Users\LúcioFláviodosSantos\OneDrive - Peers Consulting\Área de Trabalho\aegea\painel reputação\back-reputacional"
docker run --rm --user root --network painel-reputacional_default `
  -v "${b}:/src" -w /src `
  -e BANCO_URL_TESTE="postgresql+psycopg2://postgres:postgres@painel-reputacional-banco-1:5432/painel_reputacional" `
  painel-reputacional-api sh -c "pip install -q --no-cache-dir pytest httpx ruff; python -m pytest -q; ruff check ."
```

Expected: a suíte passa (a contagem do dia, sem falha) e o `ruff` limpo.

- [ ] **Step 6: Commit**

```bash
git add app/banco/repositorio_lentes.py tests/test_explorador_de_veiculos.py
git commit -m "feat(veiculos): o mes agrupado por tier e veiculo, para a tela somar"
```

---

### Task 3: Os esquemas e a rota

**Files:**
- Modify: `app/esquemas/lentes.py` (depois de `ExploradorSaida`, que termina na linha 312)
- Modify: `app/api/lentes.py` (depois de `obter_explorador`, que termina na linha 648; e os imports no topo, linhas 81-83)
- Test: `tests/test_explorador_de_veiculos.py` (acrescentar)

**Interfaces:**
- Consumes: `repositorio_lentes.grupos_de_veiculos(...) -> list[dict]` da Tarefa 2.
- Produces: `GET /api/score/lentes/{codigo}/explorador-de-veiculos` devolvendo `{lente: str, mes: str, denominador: float, grupos: [{tier, veiculo, positivo, neutro, negativo, peso_positivo, peso_neutro, peso_negativo}]}`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_explorador_de_veiculos.py`:

```python
def _explorador_de_veiculos(sessao, **filtro):
    from app.api.lentes import obter_explorador_de_veiculos

    parametros = dict(
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        sentimento=None,
    )
    parametros.update(filtro)
    return obter_explorador_de_veiculos(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes=TEXTO_DO_MES, **parametros
    )


def test_a_rota_devolve_os_grupos_e_o_denominador(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))

    saida = _explorador_de_veiculos(sessao)

    assert saida.lente == "imprensa"
    assert saida.mes == TEXTO_DO_MES
    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == 6
    #: A INVARIANTE DO MOLDE: a soma dos pesos é o denominador do mês.
    pesos = sum(g.peso_positivo + g.peso_neutro + g.peso_negativo for g in saida.grupos)
    assert pesos == pytest.approx(saida.denominador)
    assert {g.veiculo for g in saida.grupos} == {"Folha"}


def test_a_rota_segue_o_filtro_da_tela(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))

    saida = _explorador_de_veiculos(sessao, sentimento="neg")

    assert sum(g.negativo for g in saida.grupos) == 3
    assert all(g.positivo == 0 and g.neutro == 0 for g in saida.grupos)


def test_a_lente_que_le_o_crm_responde_vazia_sem_erro(sessao):
    from app.api.lentes import obter_explorador_de_veiculos

    parametros = dict(
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        sentimento=None,
    )
    saida = obter_explorador_de_veiculos(
        sessao=sessao, usuario=_QuemOlha(), codigo="institucional",
        mes=TEXTO_DO_MES, **parametros
    )

    assert saida.grupos == [] and saida.denominador == 0


def test_a_lente_que_nao_existe_da_404(sessao):
    from app.api.lentes import obter_explorador_de_veiculos
    from app.dominio.erros import NaoEncontrado

    parametros = dict(
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        sentimento=None,
    )
    with pytest.raises(NaoEncontrado):
        obter_explorador_de_veiculos(
            sessao=sessao, usuario=_QuemOlha(), codigo="nao-existe",
            mes=TEXTO_DO_MES, **parametros
        )
```

- [ ] **Step 2: Rodar e confirmar que falha**

```powershell
$b = "C:\Users\LúcioFláviodosSantos\OneDrive - Peers Consulting\Área de Trabalho\aegea\painel reputação\back-reputacional"
docker run --rm --user root --network painel-reputacional_default `
  -v "${b}:/src" -w /src `
  -e BANCO_URL_TESTE="postgresql+psycopg2://postgres:postgres@painel-reputacional-banco-1:5432/painel_reputacional" `
  painel-reputacional-api sh -c "pip install -q --no-cache-dir pytest httpx; python -m pytest tests/test_explorador_de_veiculos.py -q"
```

Expected: FAIL com `ImportError: cannot import name 'obter_explorador_de_veiculos' from 'app.api.lentes'`.

- [ ] **Step 3: Os esquemas**

Em `app/esquemas/lentes.py`, depois de `ExploradorSaida`:

```python
class GrupoDeVeiculoSaida(BaseModel):
    """Um pedaço do mês: tier e veículo, com contagem e peso por sentimento.

    Nulo onde a menção não traz o campo — a tela deixa de fora da barra
    daquele eixo, e a menção continua valendo no outro.

    UMA LINHA POR PAR, e não por veículo: o mesmo veículo pode ter matéria em
    mais de um tier, e somar aqui tiraria da tela a possibilidade de estreitar
    por tier.
    """

    tier: str | None
    veiculo: str | None
    positivo: int
    neutro: int
    negativo: int
    peso_positivo: float
    peso_neutro: float
    peso_negativo: float


class ExploradorDeVeiculosSaida(BaseModel):
    """Os grupos do mês e o denominador da nota — a tela soma o resto.

    Mesma regra de impacto de `ExploradorSaida`:
    `impacto(S) = 50 × (Σ peso_positivo − Σ peso_negativo) ÷ denominador`.
    """

    lente: str
    mes: str
    denominador: float
    grupos: list[GrupoDeVeiculoSaida]
```

- [ ] **Step 4: A rota**

Em `app/api/lentes.py`, acrescentar aos imports do bloco das linhas 81-83:

```python
    ExploradorDeVeiculosSaida,
    GrupoDeVeiculoSaida,
```

E depois de `obter_explorador`:

```python
@rotas.get("/{codigo}/explorador-de-veiculos")
def obter_explorador_de_veiculos(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
    tema_n1: Annotated[str | None, Query(description="pilar (N1) da taxonomia, pelo nome")] = None,
    tema_n2: Annotated[str | None, Query(description="tema estratégico (N2), pelo nome")] = None,
    tema_n3: Annotated[str | None, Query(description="tema (N3) do cadastro, pelo nome")] = None,
    sentimento: Annotated[str | None, Query(description="pos, neu ou neg")] = None,
) -> ExploradorDeVeiculosSaida:
    """Os três painéis do Explorador de veículos: tier × sentimento, Top
    veículos e o Termômetro por veículo.

    UM PEDIDO POR MÊS E RECORTE DA TELA, e o filtro cruzado (clicar num tier
    estreita os dois painéis de veículo) acontece no navegador, somando os
    grupos — ver `grupos_de_veiculos`. Os mesmos parâmetros do dossiê.

    A LENTE QUE LÊ O CRM NÃO TEM MENÇÃO, e volta vazia (sem erro).
    """
    alvo = mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")
    if repositorio_lentes.lente_e_interna(sessao, lente.id):
        return ExploradorDeVeiculosSaida(
            lente=lente.codigo, mes=f"{alvo:%Y-%m}", denominador=0, grupos=[]
        )

    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        autor=autor,
        empresa=empresa,
        tema_n1=tema_n1,
        tema_n2=tema_n2,
        tema_n3=tema_n3,
        sentimento=sentimento,
    )
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, denominador = repositorio_score.denominador_do_mes(sessao, lente.id, alvo, calibracao)
    grupos = repositorio_lentes.grupos_de_veiculos(
        sessao, lente.id, alvo, calibracao, regua, filtro
    )
    return ExploradorDeVeiculosSaida(
        lente=lente.codigo,
        mes=f"{alvo:%Y-%m}",
        denominador=denominador,
        grupos=[GrupoDeVeiculoSaida(**grupo) for grupo in grupos],
    )
```

- [ ] **Step 5: Rodar o arquivo de teste e confirmar que passa**

Mesmo comando do Step 2.
Expected: PASS, 6 passed.

- [ ] **Step 6: Rodar a suíte inteira e o ruff**

Mesmo comando do Step 5 da Tarefa 2.
Expected: a suíte passa e o `ruff` limpo (as regras FastAPI pegam rota mal anotada).

- [ ] **Step 7: Commit**

```bash
git add app/esquemas/lentes.py app/api/lentes.py tests/test_explorador_de_veiculos.py
git commit -m "feat(veiculos): a rota do explorador de veiculos, no molde do de taxonomia"
```

---

### Task 4: O front — cliente e a conta

**Files:**
- Modify: `src/api/score.ts` (depois de `obterExploradorDaLente`, linha 560)
- Create: `src/dominio/exploradorDeVeiculos.ts`
- Test: `src/dominio/exploradorDeVeiculos.test.ts` (criar)

**Interfaces:**
- Consumes: a rota da Tarefa 3.
- Produces:
  - `GrupoDeVeiculo` = `{ tier: string | null; veiculo: string | null; positivo: number; neutro: number; negativo: number; peso_positivo: number; peso_neutro: number; peso_negativo: number }`
  - `ExploradorDeVeiculos` = `{ lente: string; mes: string; denominador: number; grupos: GrupoDeVeiculo[] }`
  - `obterExploradorDeVeiculos(codigo: string, mes: string, filtro?: FiltroDaLente): Promise<ExploradorDeVeiculos>`
  - `Eixo = 'tier' | 'veiculo'`; `SelecaoDeVeiculos = Partial<Record<Eixo, string>>`
  - `barrasDoTier(grupos, selecao, denominador): BarraDoExplorador[]`
  - `barrasDoVeiculo(grupos, selecao, denominador): BarraDoExplorador[]`
  - `termometroDosVeiculos(grupos, selecao): VeiculoNoTermometro[]`, com `VeiculoNoTermometro = { veiculo: string; total: number; nss: number; score: number }`

- [ ] **Step 1: Escrever o teste que falha**

Criar `src/dominio/exploradorDeVeiculos.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import type { GrupoDeVeiculo } from '@/api/cliente';
import {
  barrasDoTier,
  barrasDoVeiculo,
  termometroDosVeiculos,
} from '@/dominio/exploradorDeVeiculos';

function grupo(parcial: Partial<GrupoDeVeiculo>): GrupoDeVeiculo {
  return {
    tier: 'muito_relevante',
    veiculo: 'Folha',
    positivo: 0,
    neutro: 0,
    negativo: 0,
    peso_positivo: 0,
    peso_neutro: 0,
    peso_negativo: 0,
    ...parcial,
  };
}

//: "FOLHA" EM DOIS TIERS, que é o caso que a rota produz e a tela tem de somar.
const GRUPOS: GrupoDeVeiculo[] = [
  grupo({ tier: 'muito_relevante', veiculo: 'Folha', positivo: 3, peso_positivo: 30 }),
  grupo({ tier: 'relevante', veiculo: 'Folha', negativo: 1, peso_negativo: 5 }),
  grupo({ tier: 'muito_relevante', veiculo: 'Valor', negativo: 2, peso_negativo: 20 }),
  grupo({ tier: 'menos_relevante', veiculo: 'Estadão', neutro: 4, peso_neutro: 4 }),
];

describe('o explorador de veículos soma por dois eixos', () => {
  it('soma o mesmo veículo que aparece em mais de um tier', () => {
    const barras = barrasDoVeiculo(GRUPOS, {}, 100);
    const folha = barras.find((barra) => barra.rotulo === 'Folha');
    //: SEM A SOMA, "Folha" apareceria DUAS vezes na lista — uma por tier.
    expect(barras.filter((barra) => barra.rotulo === 'Folha')).toHaveLength(1);
    expect(folha?.positivo).toBe(3);
    expect(folha?.negativo).toBe(1);
  });

  it('escolher um TIER estreita os veículos e deixa o painel de tier inteiro', () => {
    const selecao = { tier: 'muito_relevante' };
    //: O EIXO CLICADO CONTINUA INTEIRO: os três tiers seguem na barra, senão
    //: ninguém troca de tier sem desfazer o clique antes.
    expect(barrasDoTier(GRUPOS, selecao, 100).map((b) => b.rotulo)).toEqual([
      'Tier 1',
      'Tier 2',
      'Tier 3',
    ]);
    //: E OS DOIS PAINÉIS DE VEÍCULO ESTREITAM.
    expect(barrasDoVeiculo(GRUPOS, selecao, 100).map((b) => b.rotulo)).toEqual([
      'Folha',
      'Valor',
    ]);
    expect(termometroDosVeiculos(GRUPOS, selecao).map((v) => v.veiculo)).toEqual([
      'Folha',
      'Valor',
    ]);
  });

  it('escolher um VEÍCULO deixa os DOIS painéis de veículo inteiros', () => {
    const selecao = { veiculo: 'Folha' };
    //: OS DOIS SÃO O MESMO EIXO: estreitar o termômetro pelo veículo escolhido
    //: no Top o deixaria com uma barra só, que é o que o molde evita.
    //: A ORDEM É VOLUME DECRESCENTE e, no empate, o nome em pt-BR: Estadão e
    //: Folha têm 4 matérias cada, e "Estadão" vem antes.
    expect(barrasDoVeiculo(GRUPOS, selecao, 100).map((b) => b.rotulo)).toEqual([
      'Estadão',
      'Folha',
      'Valor',
    ]);
    expect(termometroDosVeiculos(GRUPOS, selecao).map((v) => v.veiculo).sort()).toEqual([
      'Estadão',
      'Folha',
      'Valor',
    ]);
    //: E O PAINEL DE TIER ESTREITA para os tiers em que a Folha publicou.
    const tiers = barrasDoTier(GRUPOS, selecao, 100).filter(
      (barra) => barra.positivo + barra.neutro + barra.negativo > 0,
    );
    expect(tiers.map((barra) => barra.rotulo)).toEqual(['Tier 1', 'Tier 2']);
  });

  it('deixa de fora a menção sem o campo do próprio eixo, e a mantém no outro', () => {
    const grupos = [
      ...GRUPOS,
      grupo({ tier: null, veiculo: 'Metrópoles', positivo: 5, peso_positivo: 50 }),
      grupo({ tier: 'relevante', veiculo: null, positivo: 7, peso_positivo: 70 }),
    ];
    //: SEM TIER sai da barra de tier, mas o veículo continua na lista.
    expect(barrasDoTier(grupos, {}, 100).map((b) => b.rotulo)).not.toContain('');
    expect(barrasDoVeiculo(grupos, {}, 100).map((b) => b.rotulo)).toContain('Metrópoles');
    //: SEM VEÍCULO sai da lista de veículos, mas continua contando no tier.
    expect(barrasDoVeiculo(grupos, {}, 100).map((b) => b.rotulo)).not.toContain('');
    const tier2 = barrasDoTier(grupos, {}, 100).find((b) => b.rotulo === 'Tier 2');
    expect(tier2?.positivo).toBe(7);
  });

  it('com denominador zero o impacto é zero, e não Infinity', () => {
    const barras = barrasDoVeiculo(GRUPOS, {}, 0);
    expect(barras.every((barra) => Number.isFinite(barra.impacto))).toBe(true);
    expect(barras.every((barra) => barra.impacto === 0)).toBe(true);
  });

  it('o termômetro e a nota saem pela conta do produto', () => {
    //: 3 positivas e 1 negativa: nss = (3 − 1) ÷ 4 × 100 = 50.
    //: NS ponderado = (30 − 5) ÷ 35; score = (NS + 1) ÷ 2 × 100 = 86.
    const folha = termometroDosVeiculos(GRUPOS, {}).find((v) => v.veiculo === 'Folha');
    expect(folha?.total).toBe(4);
    expect(folha?.nss).toBe(50);
    expect(folha?.score).toBe(86);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

```powershell
cd "C:\Users\LúcioFláviodosSantos\OneDrive - Peers Consulting\Área de Trabalho\aegea\painel reputação\front-reputacional"
npx vitest run src/dominio/exploradorDeVeiculos.test.ts
```

Expected: FAIL — `Failed to resolve import "@/dominio/exploradorDeVeiculos"`.

- [ ] **Step 3: O cliente**

Em `src/api/score.ts`, depois de `obterExploradorDaLente`:

```ts
export interface GrupoDeVeiculo {
  tier: string | null;
  veiculo: string | null;
  positivo: number;
  neutro: number;
  negativo: number;
  peso_positivo: number;
  peso_neutro: number;
  peso_negativo: number;
}

export interface ExploradorDeVeiculos {
  lente: string;
  mes: string;
  /** O denominador da nota do mês: impacto = 50 × (P − N) ÷ denominador. */
  denominador: number;
  grupos: GrupoDeVeiculo[];
}

/** Os grupos que os três painéis do Explorador de veículos somam na tela. UM
 *  PEDIDO POR MÊS E FILTRO DA TELA: o filtro cruzado (clicar num tier) é soma
 *  no navegador, sem nova ida ao servidor. */
export function obterExploradorDeVeiculos(
  codigo: string,
  mes: string,
  filtro?: FiltroDaLente,
): Promise<ExploradorDeVeiculos> {
  return requisitar<ExploradorDeVeiculos>(
    `/api/score/lentes/${codigo}/explorador-de-veiculos?${paraConsultaDoFiltro(mes, filtro)}`,
  );
}
```

- [ ] **Step 4: A conta**

Criar `src/dominio/exploradorDeVeiculos.ts`:

```ts
/** A conta dos três painéis do Explorador de veículos.
 *
 *  O SERVIDOR MANDA O MÊS EM GRUPOS `(tier, veículo)` com contagem e peso por
 *  sentimento (`/explorador-de-veiculos`), e tudo o mais é soma aqui — é o que
 *  deixa o clique ser instantâneo sem mover o dossiê.
 *
 *  SÃO DOIS EIXOS, E TRÊS PAINÉIS. No Explorador de taxonomia, N1 › N2 › N3 é
 *  uma hierarquia: cada coluna é um campo distinto. Aqui, tier é um eixo e
 *  veículo é o outro, e os painéis "Top veículos" e "Termômetro" são o MESMO
 *  eixo com medidas diferentes. Por isso o `exceto` é o EIXO do painel que se
 *  desenha, e não o painel: escolher um veículo deixa os DOIS painéis de
 *  veículo inteiros. Estreitar o termômetro pelo veículo escolhido no Top o
 *  deixaria com uma barra só — o modo de falha que o molde existe para evitar.
 */

import type { GrupoDeVeiculo } from '@/api/cliente';
import type { BarraDoExplorador } from '@/dominio/explorador';
import { ROTULO_DO_TIER } from '@/dominio/filtrosDasLentes';

export type Eixo = 'tier' | 'veiculo';
export const EIXOS: Eixo[] = ['tier', 'veiculo'];
export type SelecaoDeVeiculos = Partial<Record<Eixo, string>>;

//: A ORDEM DO PRODUTO, e não a do volume: Tier 1, 2, 3. O painel de tier é uma
//: régua de relevância, e reordená-la por volume faria "Tier 3" aparecer em
//: cima num mês ruim.
const ORDEM_DO_TIER = ['muito_relevante', 'relevante', 'menos_relevante'];

export interface VeiculoNoTermometro {
  veiculo: string;
  /** Matérias do veículo no recorte. */
  total: number;
  /** O termômetro do CRM: (positivas − negativas) ÷ total × 100, de −100 a 100. */
  nss: number;
  /** A nota do veículo na régua da lente, de 0 a 100. */
  score: number;
}

/** Os grupos que passam pelas escolhas — menos a do eixo `exceto`. */
export function gruposNaSelecao(
  grupos: GrupoDeVeiculo[],
  selecao: SelecaoDeVeiculos,
  exceto?: Eixo,
): GrupoDeVeiculo[] {
  return grupos.filter((grupo) =>
    EIXOS.every((eixo) => eixo === exceto || !selecao[eixo] || grupo[eixo] === selecao[eixo]),
  );
}

function impacto(pesoPositivo: number, pesoNegativo: number, denominador: number): number {
  return denominador ? (50 * (pesoPositivo - pesoNegativo)) / denominador : 0;
}

interface Soma {
  pos: number;
  neu: number;
  neg: number;
  wPos: number;
  wNeu: number;
  wNeg: number;
}

function vazia(): Soma {
  return { pos: 0, neu: 0, neg: 0, wPos: 0, wNeu: 0, wNeg: 0 };
}

function somar(alvo: Soma, grupo: GrupoDeVeiculo): void {
  alvo.pos += grupo.positivo;
  alvo.neu += grupo.neutro;
  alvo.neg += grupo.negativo;
  alvo.wPos += grupo.peso_positivo;
  alvo.wNeu += grupo.peso_neutro;
  alvo.wNeg += grupo.peso_negativo;
}

/** Somas por valor de um eixo, já dentro das escolhas dos OUTROS eixos.
 *  Grupo sem o campo deste eixo fica de fora — e continua valendo no outro. */
function somasDoEixo(
  grupos: GrupoDeVeiculo[],
  eixo: Eixo,
  selecao: SelecaoDeVeiculos,
): Map<string, Soma> {
  const somas = new Map<string, Soma>();
  for (const grupo of gruposNaSelecao(grupos, selecao, eixo)) {
    const chave = grupo[eixo];
    if (!chave) continue;
    const atual = somas.get(chave) ?? vazia();
    somar(atual, grupo);
    somas.set(chave, atual);
  }
  return somas;
}

/** As três barras de tier, na ordem do produto. O tier sem matéria no recorte
 *  continua desenhado, em zero: a régua tem três degraus sempre, e um degrau
 *  que desaparece faz a lista pular de tamanho a cada clique. */
export function barrasDoTier(
  grupos: GrupoDeVeiculo[],
  selecao: SelecaoDeVeiculos,
  denominador: number,
): BarraDoExplorador[] {
  const somas = somasDoEixo(grupos, 'tier', selecao);
  return ORDEM_DO_TIER.map((tier) => {
    const s = somas.get(tier) ?? vazia();
    return {
      rotulo: ROTULO_DO_TIER[tier] ?? tier,
      positivo: s.pos,
      neutro: s.neu,
      negativo: s.neg,
      impacto: impacto(s.wPos, s.wNeg, denominador),
    };
  });
}

/** Os veículos do recorte, do maior volume para o menor. */
export function barrasDoVeiculo(
  grupos: GrupoDeVeiculo[],
  selecao: SelecaoDeVeiculos,
  denominador: number,
): BarraDoExplorador[] {
  const somas = somasDoEixo(grupos, 'veiculo', selecao);
  return [...somas.entries()]
    .map(([rotulo, s]) => ({
      rotulo,
      positivo: s.pos,
      neutro: s.neu,
      negativo: s.neg,
      impacto: impacto(s.wPos, s.wNeg, denominador),
    }))
    .sort(
      (a, b) =>
        b.positivo + b.neutro + b.negativo - (a.positivo + a.neutro + a.negativo) ||
        a.rotulo.localeCompare(b.rotulo, 'pt-BR'),
    );
}

/** Cada veículo com o termômetro (NSS) e a nota, dentro das escolhas. */
export function termometroDosVeiculos(
  grupos: GrupoDeVeiculo[],
  selecao: SelecaoDeVeiculos,
): VeiculoNoTermometro[] {
  const somas = somasDoEixo(grupos, 'veiculo', selecao);
  return [...somas.entries()]
    .map(([veiculo, s]) => {
      const total = s.pos + s.neu + s.neg;
      const peso = s.wPos + s.wNeu + s.wNeg;
      const ns = peso ? (s.wPos - s.wNeg) / peso : 0;
      return {
        veiculo,
        total,
        nss: total ? Math.round(((s.pos - s.neg) / total) * 100) : 0,
        score: Math.round(((ns + 1) / 2) * 100),
      };
    })
    .sort((a, b) => b.total - a.total || a.veiculo.localeCompare(b.veiculo, 'pt-BR'));
}
```

- [ ] **Step 5: Rodar e confirmar que passa**

```powershell
npx vitest run src/dominio/exploradorDeVeiculos.test.ts
```

Expected: PASS, 6 passed.

- [ ] **Step 6: Tipo e suíte**

```powershell
npx tsc -b
npx vitest run
```

Expected: `tsc -b` exit 0; a suíte inteira passa.

- [ ] **Step 7: Commit**

```bash
git add src/api/score.ts src/dominio/exploradorDeVeiculos.ts src/dominio/exploradorDeVeiculos.test.ts
git commit -m "feat(veiculos): a conta dos dois eixos, e o cliente da rota nova"
```

---

### Task 5: O front — o bloco dos três painéis

**Files:**
- Create: `src/paginas/score/ExploradorDeVeiculos.tsx`
- Modify: `src/dominio/guiaDoDossie.ts` (o mapa `GUIA_DO_BLOCO`, linha 38)
- Test: `src/paginas/score/ExploradorDeVeiculos.test.tsx` (criar)

**Interfaces:**
- Consumes: `obterExploradorDeVeiculos`, `barrasDoTier`, `barrasDoVeiculo`, `termometroDosVeiculos`, `SelecaoDeVeiculos` da Tarefa 4; `useListaDeVeiculos` e `RevelarVeiculos`, hoje privados em `DossieDaLente.tsx:956-1100`.
- Produces: `<ExploradorDeVeiculos codigo={string} mes={string} filtro={FiltroDaLente} />`.

- [ ] **Step 1: Mover `useListaDeVeiculos` e `RevelarVeiculos` para um módulo próprio**

Eles são privados de `DossieDaLente.tsx` e passam a ser usados por dois arquivos. Criar `src/paginas/score/revelarVeiculos.tsx` com os dois **sem mudar uma linha do corpo**, exportando ambos, e trocar em `DossieDaLente.tsx` as definições por um import. O `teto` deixa de ser limitado a 10: trocar

```ts
const QUANTIDADE_MAXIMA_DE_VEICULOS = 10;
```

por

```ts
//: SEM TETO DE 10 (23/10/2026): o Explorador de veículos recebe TODOS os
//: veículos do recorte, e quem corta é o botão — "Ver todos os N" com o N de
//: verdade. O 10 era o corte que o servidor fazia nos blocos antigos.
```

e, em `useListaDeVeiculos`, trocar `const teto = Math.min(QUANTIDADE_MAXIMA_DE_VEICULOS, total);` por `const teto = total;`.

- [ ] **Step 2: Rodar a suíte do dossiê e confirmar que nada quebrou com a mudança de lugar**

```powershell
npx vitest run src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx
```

Expected: PASS — os testes de hoje usam listas de 7 veículos, e com `teto = total` o rótulo continua "Ver todos os 7 veículos".

- [ ] **Step 3: Commit da mudança de lugar, antes de somar comportamento**

```bash
git add src/paginas/score/revelarVeiculos.tsx src/paginas/score/DossieDaLente.tsx
git commit -m "refactor(veiculos): o botao de revelar sai de dentro da tela, e perde o teto de 10"
```

- [ ] **Step 4: Escrever o teste que falha**

Criar `src/paginas/score/ExploradorDeVeiculos.test.tsx`:

```tsx
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ExploradorDeVeiculos as Dados } from '@/api/cliente';
import { ExploradorDeVeiculos } from '@/paginas/score/ExploradorDeVeiculos';

vi.mock('@/api/cliente', async (importarOriginal) => ({
  ...(await importarOriginal<typeof import('@/api/cliente')>()),
  obterExploradorDeVeiculos: vi.fn(),
}));

const { obterExploradorDeVeiculos } = await import('@/api/cliente');

function dados(quantosVeiculos: number): Dados {
  return {
    lente: 'imprensa',
    mes: '2026-09',
    denominador: 100,
    grupos: Array.from({ length: quantosVeiculos }, (_, indice) => ({
      tier: 'muito_relevante',
      veiculo: `Veículo ${indice + 1}`,
      positivo: quantosVeiculos - indice,
      neutro: 0,
      negativo: 0,
      peso_positivo: quantosVeiculos - indice,
      peso_neutro: 0,
      peso_negativo: 0,
    })),
  };
}

function montar() {
  return render(
    <ExploradorDeVeiculos codigo="imprensa" mes="2026-09" filtro={{}} />,
  );
}

describe('o Explorador de veículos', () => {
  beforeEach(() => {
    vi.mocked(obterExploradorDeVeiculos).mockReset();
  });

  it('desenha os três painéis', async () => {
    vi.mocked(obterExploradorDeVeiculos).mockResolvedValue(dados(3));
    montar();
    await waitFor(() => expect(screen.getByText('Tier do veículo × sentimento')).toBeInTheDocument());
    expect(screen.getByText('Top veículos')).toBeInTheDocument();
    expect(screen.getByText('Termômetro por Veículos')).toBeInTheDocument();
  });

  it('o chip aparece ao escolher, e o Limpar zera os dois eixos', async () => {
    vi.mocked(obterExploradorDeVeiculos).mockResolvedValue(dados(3));
    montar();
    await waitFor(() => expect(screen.getByText('Tier 1')).toBeInTheDocument());

    await userEvent.click(screen.getByText('Tier 1'));
    expect(screen.getByText('Filtrando por')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Tirar o filtro Tier/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Limpar' }));
    expect(screen.queryByText('Filtrando por')).toBeNull();
  });

  it('abre em 5 veículos, e o botão diz quantos há de verdade', async () => {
    //: O N É O TOTAL DO RECORTE, e não o teto de 10 dos blocos antigos: o
    //: servidor passou a mandar todos.
    vi.mocked(obterExploradorDeVeiculos).mockResolvedValue(dados(13));
    montar();
    await waitFor(() => expect(screen.getByText('Top veículos')).toBeInTheDocument());

    const topo = screen.getByText('Top veículos').closest('.cartao') as HTMLElement;
    expect(within(topo).getByText('Veículo 5')).toBeInTheDocument();
    expect(within(topo).queryByText('Veículo 6')).toBeNull();
    await userEvent.click(
      within(topo).getByRole('button', { name: 'Ver todos os 13 veículos' }),
    );
    expect(within(topo).getByText('Veículo 13')).toBeInTheDocument();
  });

  it('com 5 veículos ou menos não existe botão de revelar', async () => {
    vi.mocked(obterExploradorDeVeiculos).mockResolvedValue(dados(4));
    montar();
    await waitFor(() => expect(screen.getByText('Top veículos')).toBeInTheDocument());

    const topo = screen.getByText('Top veículos').closest('.cartao') as HTMLElement;
    expect(within(topo).queryByRole('button', { name: /Ver todos/ })).toBeNull();
  });

  it('a falha vira recado na tela, e não tela vazia', async () => {
    vi.mocked(obterExploradorDeVeiculos).mockRejectedValue(
      new Error('Não foi possível ler os veículos.'),
    );
    montar();
    await waitFor(() =>
      expect(screen.getByText('Não foi possível ler os veículos.')).toBeInTheDocument(),
    );
  });

  it('a resposta atrasada de um recorte não pousa sobre o atual', async () => {
    //: A GUARDA É A CHAVE DO PEDIDO (`codigo|mes|filtro`): sem ela, trocar de
    //: mês duas vezes rápido deixaria a tela mostrando o mês errado.
    let liberar: ((dado: Dados) => void) | undefined;
    vi.mocked(obterExploradorDeVeiculos).mockImplementationOnce(
      () => new Promise<Dados>((resolve) => (liberar = resolve)),
    );
    const { rerender } = montar();
    vi.mocked(obterExploradorDeVeiculos).mockResolvedValue(dados(2));
    rerender(<ExploradorDeVeiculos codigo="imprensa" mes="2026-10" filtro={{}} />);
    await waitFor(() => expect(screen.getByText('Top veículos')).toBeInTheDocument());

    //: A resposta do mês velho chega DEPOIS, com 7 veículos.
    liberar?.(dados(7));
    await waitFor(() => expect(screen.getByText('Top veículos')).toBeInTheDocument());
    const topo = screen.getByText('Top veículos').closest('.cartao') as HTMLElement;
    //: Continua o recorte novo (2 veículos), e não o velho (7).
    expect(within(topo).queryByText('Veículo 3')).toBeNull();
  });
});
```

- [ ] **Step 5: Rodar e confirmar que falha**

```powershell
npx vitest run src/paginas/score/ExploradorDeVeiculos.test.tsx
```

Expected: FAIL — `Failed to resolve import "@/paginas/score/ExploradorDeVeiculos"`.

- [ ] **Step 6: Implementar o componente**

Criar `src/paginas/score/ExploradorDeVeiculos.tsx`. O arquivo segue `src/paginas/score/ExploradorDaLente.tsx` passo a passo — **ler aquele arquivo inteiro antes de escrever este**, porque dele vêm, sem alteração: a guarda da chave do pedido (`:74-101`), a barra de chips "Filtrando por" com o Limpar (`:106-150`), a `<Legenda />` (`:231-251`) e o uso de `ComFaixaDoTopo` + `Secao`.

O que muda em relação ao modelo:

```tsx
const NOMES: Record<Eixo, string> = { tier: 'Tier', veiculo: 'Veículo' };

const [selecao, definirSelecao] = useState<SelecaoDeVeiculos>({});
const alternar = (eixo: Eixo, valor: string) =>
  definirSelecao((atual) => ({ ...atual, [eixo]: atual[eixo] === valor ? undefined : valor }));
```

Os chips iteram `EIXOS` em vez de `Object.keys(NOMES) as Nivel[]`, e o `aria-label` fica `Tirar o filtro ${NOMES[eixo]}: ${selecao[eixo]}`.

Três `<Secao>` em `<ComFaixaDoTopo>`, uma por painel:

```tsx
// 1 — Tier do veículo × sentimento
<ColunasEmpilhadas
  semLegenda
  rotuloEmCima
  espessura={8}
  alturaMaxima={360}
  cores={CORES_DO_SENTIMENTO}
  vazio="Nenhuma matéria com tier do veículo neste recorte."
  ativo={selecao.tier ? ROTULO_DO_TIER[selecao.tier] : undefined}
  aoClicar={(rotulo) => {
    const tier = Object.keys(ROTULO_DO_TIER).find((chave) => ROTULO_DO_TIER[chave] === rotulo);
    if (tier) alternar('tier', tier);
  }}
  itens={barrasDoTier(atuais.dados.grupos, selecao, atuais.dados.denominador).map((barra) => ({
    ...barra,
    detalhe: `${textoDoImpacto(barra.impacto)} pts`,
  }))}
/>
```

**O `ColunasEmpilhadas` fala por RÓTULO, não por chave** — `aoClicar` recebe `barra.rotulo`. Como o painel 1 mostra "Tier 1" e a seleção guarda `muito_relevante`, a tradução acontece nas duas pontas, como no trecho acima. O painel 1 **não leva** `RevelarVeiculos`.

```tsx
// 2 — Top veículos: a lista cortada em `quantidade`, com o botão
const lista = useListaDeVeiculos(veiculos.length);
...
<div id={lista.idDaLista}>
  <ColunasEmpilhadas
    semLegenda rotuloEmCima espessura={8} alturaMaxima={360}
    cores={CORES_DO_SENTIMENTO}
    vazio="Nenhuma matéria com veículo neste recorte."
    ativo={selecao.veiculo}
    aoClicar={(valor) => alternar('veiculo', valor)}
    itens={veiculos.slice(0, lista.quantidade).map((barra) => ({
      ...barra,
      detalhe: `${textoDoImpacto(barra.impacto)} pts`,
    }))}
  />
</div>
<RevelarVeiculos
  teto={lista.teto} podeAbrir={lista.podeAbrir} aberta={lista.aberta}
  aoAlternar={lista.alternar} controla={lista.idDaLista}
/>

// 3 — Termômetro por Veículos: o mesmo par, com a lista própria
<BarraDivergentePorItem
  itens={termometro.slice(0, listaDoTermometro.quantidade).map((item) => ({
    chave: item.veiculo,
    rotulo: item.veiculo,
    total: item.total,
    score: item.score,
  }))}
  ativo={selecao.veiculo}
  aoClicar={(veiculo) => alternar('veiculo', veiculo)}
  unidade={{ singular: 'matéria', plural: 'matérias' }}
  variante="termometro"
/>
```

**Dois `useListaDeVeiculos` independentes**, um por painel de veículo: cada um abre e fecha sozinho, como os cartões de hoje fazem.

- [ ] **Step 7: A ajuda do bloco**

Em `src/dominio/guiaDoDossie.ts`, dentro de `GUIA_DO_BLOCO`, acrescentar as duas entradas que faltam (a de `'Tier do veículo × sentimento'` já existe na linha 47):

```ts
  'Top veículos':
    'Os veículos com mais matérias no recorte, com o volume positivo, neutro e negativo de cada um e o impacto na nota da lente em pontos. Clique num veículo para filtrar os outros dois painéis. Essa visão mostra quem está pautando a cobertura do mês.',
  'Termômetro por Veículos':
    'Para cada veículo do recorte, o saldo (positivas − negativas) ÷ total × 100, de −100 a 100 — o mesmo cálculo do termômetro por instituição do Painel. Essa visão mostra quais veículos estão favoráveis ou desfavoráveis à companhia, sem o peso de tier que a nota oficial usa.',
```

- [ ] **Step 8: Rodar e confirmar que passa**

```powershell
npx vitest run src/paginas/score/ExploradorDeVeiculos.test.tsx
npx tsc -b
```

Expected: 6 passed; `tsc -b` exit 0.

- [ ] **Step 9: Commit**

```bash
git add src/paginas/score/ExploradorDeVeiculos.tsx src/paginas/score/ExploradorDeVeiculos.test.tsx src/dominio/guiaDoDossie.ts
git commit -m "feat(veiculos): o bloco dos tres paineis que se filtram por dois eixos"
```

---

### Task 6: Trocar no dossiê — os três cartões saem

**Files:**
- Modify: `src/paginas/score/DossieDaLente.tsx`
- Modify: `src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx`

**Interfaces:**
- Consumes: `<ExploradorDeVeiculos />` da Tarefa 5.
- Produces: nada — é a última tarefa.

- [ ] **Step 1: Escrever o teste que falha**

Em `src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx`, **substituir** o teste `'o Top veículos e o Termômetro abrem em 5 e um botão só revela todos'`, o `'e sem segunda tela para revelar não existe botão nenhum'` e o `'e o ranking de Tier 1 abre pelo mesmo botão'` por um só:

```tsx
  it('os três cartões de veículo deram lugar ao Explorador de veículos', async () => {
    //: OS TRÊS CARTÕES SAÍRAM (23/10/2026): a dimensão de veículo virou um
    //: bloco de três painéis que se filtram entre si no navegador, e os
    //: cartões independentes que respondiam ao filtro da TELA não existem
    //: mais. Os testes do contador, do botão de revelar e da sublista de Tier
    //: 1 moraram aqui e foram para `ExploradorDeVeiculos.test.tsx`.
    obterDossieDaLente.mockResolvedValue(dossieCom('imprensa'));
    await montarEAbrir('imprensa');

    await waitFor(() => expect(screen.getAllByText('Últimas matérias').length).toBeGreaterThan(0));
    expect(screen.queryByText('% Matérias por tier e Top veículos')).toBeNull();
    expect(screen.queryAllByText(/veículos Tier 1/)).toEqual([]);
  });
```

E, na lista `OS_BLOCOS` do arquivo, tirar `'% Matérias por tier e Top veículos'` e `'Termômetro por Veículos'` se estiverem lá.

- [ ] **Step 2: Rodar e confirmar que falha**

```powershell
npx vitest run src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx
```

Expected: FAIL — `expected null not to be null` no `queryByText('% Matérias por tier e Top veículos')`, porque o cartão ainda está desenhado.

- [ ] **Step 3: Tirar os três cartões e pôr o bloco**

Em `src/paginas/score/DossieDaLente.tsx`:

1. apagar as funções `VolumeETopVeiculos` e `ClimaPorVeiculos` inteiras;
2. apagar o trecho da sublista de Tier 1 dentro de `CartaoDoPainel` (o `{painel.titulo === 'Tier do veículo × sentimento' && dossie.veiculos_tier1 ? (...) : null}`), a prop `veiculosDoTier1` de `CartaoDoPainel` e de todas as suas chamadas, e a linha `const veiculosDoTier1 = useListaDeVeiculos(...)`;
3. no lugar onde os dois cartões eram desenhados, pôr:

```tsx
{/* A DIMENSÃO DE VEÍCULO EM UM BLOCO SÓ (23/10/2026, por pedido), no molde do
    Explorador de taxonomia: três painéis que se filtram entre si somando no
    navegador. Os três cartões independentes de antes respondiam ao filtro da
    TELA — cada clique ia ao servidor e movia o dossiê inteiro, e o painel
    clicado ficava com uma barra só. */}
{LENTES_COM_BLOCOS_DE_VEICULO.includes(dossie.codigo) ? (
  <ExploradorDeVeiculos
    key={`veiculos-${dossie.codigo}-${dossie.mes}`}
    codigo={dossie.codigo}
    mes={dossie.mes}
    filtro={filtro}
  />
) : null}
```

4. acrescentar o import `import { ExploradorDeVeiculos } from '@/paginas/score/ExploradorDeVeiculos';`;
5. tirar os imports que ficaram sem uso (`Rosca`, `BarraDivergentePorItem`, e `useListaDeVeiculos`/`RevelarVeiculos` se nada mais os usar no arquivo) — o `tsc -b` e o `ruff`/lint apontam.

- [ ] **Step 4: Rodar e confirmar que passa**

```powershell
npx vitest run src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx
npx tsc -b
```

Expected: PASS; `tsc -b` exit 0.

- [ ] **Step 5: A suíte inteira do front**

```powershell
npx vitest run
```

Expected: tudo passa. Os testes de `DossieDaLente.opcoes-do-mes.test.tsx` montam o dossiê com os quatro blocos no fixture — eles continuam válidos, porque o tipo `Dossie` não mudou (os blocos seguem chegando do servidor, só não são mais lidos).

- [ ] **Step 6: Commit**

```bash
git add src/paginas/score/DossieDaLente.tsx src/paginas/score/DossieDaLente.blocos-de-veiculo.test.tsx
git commit -m "feat(veiculos): os tres cartoes dao lugar ao Explorador de veiculos"
```

---

## Depois do plano

1. **O Codex revisa** os dois repositórios (instrução permanente), com atenção a: a invariante do denominador na rota nova; a regra dos dois eixos no domínio do front; e se algum teste passa por motivo errado.
2. **Dois PRs**, um por repositório, e o do back entra primeiro — o front depende da rota.
3. **Pendência registrada:** remover `volume_por_tier`, `top_veiculos`, `clima_por_veiculos` e `veiculos_tier1` do dossiê no back, depois de conferir relatório, PNG e a lente Mercado.
