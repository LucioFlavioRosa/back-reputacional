# Importação de agendas por planilha — plano de implementação

> **Para quem executa:** SUB-SKILL OBRIGATÓRIO — use `superpowers:subagent-driven-development` (recomendado) ou `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam caixa (`- [ ]`) para acompanhamento.

**Objetivo:** permitir que a coordenação baixe um modelo `.xlsx`, preencha um dia inteiro de agendas fora da plataforma, suba o arquivo, confira as pendências agrupadas e crie todas as agendas de uma vez.

**Arquitetura:** uma descrição declarativa do formato da planilha mora no domínio e é lida por dois consumidores — o gerador do arquivo e o leitor dele. A importação nunca escreve em `interacao` diretamente: monta um `InteracaoEntrada` e segue pelo mesmo caminho do `POST /api/interacoes`. As tabelas `importacao` e `importacao_linha` já existem (migration `0008`) e não precisam de alteração.

**Tecnologias:** Python 3.12+, FastAPI, SQLAlchemy 2.x, Postgres, `openpyxl` (já declarado), pytest. Front em React 19 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-09-25-importacao-de-agendas-design.md` — leia antes da primeira tarefa. O plano argumenta a partir dela.

## Restrições globais

- **Comentários e identificadores em português.** É o estilo da casa, incluindo os comentários longos que explicam POR QUE uma regra existe. Não traduza o que já está escrito.
- **`dominio/` não toca banco nem arquivo.** Função pura, testável sem fixture. Se precisar de sessão ou de `openpyxl`, é `casos_de_uso/`.
- **Rotas são `def`, nunca `async def`** — o SQLAlchemy deste projeto é síncrono.
- **Dependências no router, não na rota**, via `dependencies=[Depends(...)]`.
- **Parâmetros com `Annotated`**, nunca `= Depends(...)` nem `...` como default.
- **Erros de domínio são `RegraViolada` / `NaoEncontrado`** (de `app/dominio/erros.py`), traduzidos centralmente. Nunca `HTTPException` crua num caso de uso.
- **Teto de 500 agendas por arquivo.**
- **As tabelas da `0008` são lei, não rascunho.** Elas já existem com colunas nomeadas: na `importacao_linha` a origem é `aba` e `linha_origem` (é na `interacao` que os campos se chamam `origem_aba` e `origem_linha` — os dois pares existem e são diferentes). `arquivo_nome` e `criado_por` são `not null`. `situacao` nasce `'processando'` e só então vai a `'aguardando_conferencia'`. `decisao` aceita `pendente|aceita|corrigida|descartada`. **Nenhuma migration nova.**
- **Consulta em `divergencias` e `dados_brutos` usa contenção (`@>`), nunca `->>`.** Os dois índices GIN da `0008` não entram com `->>`, e a consulta cai para varredura sequencial sem nada parecer errado. A própria migration deixa o exemplo: `where divergencias @> '[{"campo":"veiculo"}]'`.
- **Normalização de nome é `app/dominio/texto.py › normalizar`** — nunca uma segunda regra.
- **Vocabulários FECHADOS nunca recebem valor novo**, mesmo que a aba venha desprotegida. As chaves são as de `app/api/dicionarios.py`, que a spec nomeia como a fonte: `status`, `climas`, `resultados`, `iniciativas` — mais `modalidade`, `presenca`, `papel`, `momento`, que **não têm entrada no registro** porque são vocabulário de código, não tabela de dicionário. Os quatro primeiros se resolvem contra o banco; os quatro últimos, contra o código. A Tarefa 6 precisa dessa distinção.
- **Cada tarefa termina com a suíte inteira verde:** `BANCO_URL_TESTE="postgresql+psycopg2://postgres:postgres@localhost:5433/painel_reputacional" py -3 -m pytest -q` e `py -3 -m ruff check app/ tests/`.

## Foco da revisão

Cinco classes de entrada que a spec implica e que nenhuma tarefa do caminho feliz exercita. Cada uma tem seu teste na tarefa que possui o código.

1. **Planilha salva pelo Google Sheets ou LibreOffice** — perde a proteção de aba e a validação de lista. O leitor precisa aceitar o arquivo e recusar o conteúdo, nunca confiar na validação. *(Tarefa 5)*
2. **Data como texto** — "25/09/2026" digitado numa célula formatada como texto chega `str`, não `datetime`. Uma planilha exportada de outra ferramenta faz isso com frequência. *(Tarefa 4)*
3. **Espaço invisível colado da web** — espaço não separável (`\xa0`) e quebra de linha no fim do nome fazem o valor não casar com um cadastro que existe, e a pessoa não vê diferença nenhuma na tela. *(Tarefa 5)*
4. **O mesmo cadastro novo escrito de dois jeitos dentro do MESMO arquivo** — "Prefeitura de Campinas" na aba editável e "PREFEITURA DE CAMPINAS" na célula da agenda. Tem de criar **um**, não dois. *(Tarefa 5)*
5. **Linha filha apontando para um `Código` que não existe em Agendas** — a pessoa apagou a agenda e esqueceu os participantes dela. Recusa estrutural do arquivo, com o código citado. *(Tarefa 4)*

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app/dominio/importacao_de_agendas.py` | **Criar.** A descrição do formato (abas, colunas, vocabulário de cada coluna, quais são fechados) e a classificação de um valor lido. Puro. |
| `app/casos_de_uso/modelo_de_importacao.py` | **Criar.** Descrição + vocabulários atuais → bytes do `.xlsx`, com listas suspensas. |
| `app/casos_de_uso/ler_planilha_de_agendas.py` | **Criar.** Bytes → linhas brutas por aba, com as recusas estruturais. |
| `app/casos_de_uso/importar_agendas.py` | **Criar.** Propor, resolver, confirmar. |
| `app/banco/repositorio_importacao.py` | **Criar.** As duas tabelas da `0008`. |
| `app/banco/tabelas_importacao.py` | **Criar.** O mapeamento ORM de `importacao` e `importacao_linha`. |
| `app/api/importacoes.py` | **Criar.** As cinco rotas. |
| `main.py` | **Modificar.** `app.include_router(importacoes.rotas)`. |
| `tests/test_portal_no_backend.py` | **Modificar.** `/api/importacoes` na âncora estrutural. |
| `../front-reputacional/src/paginas/cadastro/impedimento.test.ts` | **Ler, não modificar.** É a lista canônica das seis recusas; a Tarefa 7 prende as duas listas a ela. |

---

### Tarefa 1: A descrição do formato

**Arquivos:**
- Criar: `app/dominio/importacao_de_agendas.py`
- Teste: `tests/test_importacao_de_agendas.py`

**Interfaces:**
- Consome: nada.
- Produz: `Coluna(nome, campo, vocabulario, obrigatoria)`, `Aba(nome, chave, colunas)`, `FORMATO: tuple[Aba, ...]`, `VOCABULARIOS_EDITAVEIS: frozenset[str]`, `VOCABULARIOS_FECHADOS: frozenset[str]`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
"""O formato da planilha de agendas — a descrição que o gerador e o leitor leem.

UMA DESCRIÇÃO, DOIS CONSUMIDORES. Se o formato morasse duas vezes, uma coluna
nova entraria no gerador e não no leitor, e a pessoa preencheria uma coluna que
ninguém lê — sem erro nenhum.
"""

from app.dominio.importacao_de_agendas import (
    FORMATO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
    aba_de,
)


def test_as_quatro_abas_de_preenchimento_existem():
    assert [aba.nome for aba in FORMATO] == [
        "Agendas",
        "Participantes",
        "Pessoas da Aegea",
        "Materiais",
    ]


def test_a_aba_de_agendas_comeca_pelo_codigo():
    """O `Código` é o que liga as abas filhas, e por isso é a primeira coluna:
    quem preenche precisa vê-lo antes de tudo."""
    assert aba_de("Agendas").colunas[0].nome == "Código"


def test_toda_aba_filha_tem_codigo():
    for aba in FORMATO[1:]:
        assert aba.colunas[0].nome == "Código", aba.nome


def test_nenhum_vocabulario_e_editavel_e_fechado_ao_mesmo_tempo():
    """São grupos exclusivos: `dicionarios.py` já garante isso do lado da
    Administração, e aqui a mesma regra precisa valer."""
    assert VOCABULARIOS_EDITAVEIS & VOCABULARIOS_FECHADOS == frozenset()


def test_toda_coluna_com_vocabulario_aponta_para_um_grupo_conhecido():
    """O QUE ISTO TRAVA: uma coluna nova com vocabulário escrito errado geraria
    lista suspensa vazia no modelo e divergência em toda linha na leitura."""
    conhecidos = VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS
    soltas = [
        (aba.nome, coluna.nome)
        for aba in FORMATO
        for coluna in aba.colunas
        if coluna.vocabulario and coluna.vocabulario not in conhecidos
    ]
    assert soltas == []


def test_o_clima_e_fechado_e_a_instituicao_e_editavel():
    """Os dois exemplos que o cliente deu, e eles caem em grupos diferentes:
    clima é FECHADO (os KPIs dependem dele), instituição é cadastro."""
    assert "clima" in VOCABULARIOS_FECHADOS
    assert "instituicoes" in VOCABULARIOS_EDITAVEIS
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q`
Esperado: FALHA com `ModuleNotFoundError: No module named 'app.dominio.importacao_de_agendas'`

- [ ] **Passo 3: Escrever a descrição**

Crie `app/dominio/importacao_de_agendas.py` com um `@dataclass(frozen=True, slots=True)` para `Coluna` (campos: `nome: str`, `campo: str`, `vocabulario: str | None = None`, `obrigatoria: bool = False`) e outro para `Aba` (`nome: str`, `colunas: tuple[Coluna, ...]`).

`FORMATO` é a tupla das quatro abas, com as colunas da spec (seção *O modelo `.xlsx`*). `campo` é o nome do campo em `Formulario`/`InteracaoEntrada` — `data_interacao`, `instituicao_id`, `formato_interacao_id`, `uf`, `unidade_negocio_id`, `modalidade`, `local`, `status`, `iniciativa`, `nota_situacao`, `declinado_por`, `motivo_declinio`, `clima_esperado`, `expectativa`, `preve_desdobramento`, `clima`, `resultado`, `relato`, `encaminhamentos`, `pendencias`, `observacoes`, e `temas`/`areas` para as colunas numeradas.

`aba_de(nome)` devolve a aba ou levanta `RegraViolada`.

Escreva no cabeçalho do módulo POR QUE a descrição é única, com o argumento do teste de colunas soltas.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q` → PASSA
Rode: `py -3 -m ruff check app/ tests/` → limpo

- [ ] **Passo 5: Commitar**

```bash
git add app/dominio/importacao_de_agendas.py tests/test_importacao_de_agendas.py
git commit -m "O formato da planilha de agendas vira descrição declarativa"
```

---

### Tarefa 2: Todo campo de `InteracaoEntrada` tem destino declarado

**Arquivos:**
- Modificar: `app/dominio/importacao_de_agendas.py`
- Teste: `tests/test_importacao_de_agendas.py`

**Interfaces:**
- Consome: `FORMATO` da Tarefa 1.
- Produz: `DESTINO_DO_CAMPO: dict[str, str]` com valores `"da planilha" | "das abas filhas" | "derivado" | "fora da v1"`. `das abas filhas` é para as coleções (`participacoes`, `outra_parte`, `materiais`): a pessoa as preenche na planilha, só que em aba própria e sem `Coluna.campo` correspondente. Chamá-las de `derivado` diria que o servidor as calcula, e o guarda existe justamente para não mentir sobre a procedência de um campo.

Esta tarefa existe porque é o guarda que pega o campo acrescentado depois — o mesmo padrão de `_DE_TEXTO` no `Recorte` e do `DESTINO` em `corpo.test.ts`. Sem ele, um campo novo em `InteracaoEntrada` simplesmente nunca chega pela importação, e ninguém descobre.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_todo_campo_da_interacao_tem_destino_declarado():
    """O GUARDA DO CAMPO NOVO.

    Sem isto, acrescentar um campo a `InteracaoEntrada` o deixa fora da
    importação em silêncio: a planilha não o traz, ninguém reclama, e meses
    depois alguém pergunta por que as agendas importadas não têm aquele dado.
    """
    from app.esquemas.interacoes import InteracaoEntrada
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO

    campos = set(InteracaoEntrada.model_fields)
    sem_destino = sorted(campos - set(DESTINO_DO_CAMPO))

    assert sem_destino == []


def test_todo_campo_declarado_como_da_planilha_tem_coluna():
    """O outro lado: declarar que vem da planilha e não ter coluna faria o
    campo chegar sempre vazio, e a declaração mentiria."""
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO, FORMATO

    com_coluna = {
        coluna.campo for aba in FORMATO for coluna in aba.colunas if coluna.campo
    }
    prometidos = {
        campo for campo, destino in DESTINO_DO_CAMPO.items() if destino == "da planilha"
    }

    assert prometidos - com_coluna == set()


def test_frente_esfera_e_tier_sao_derivados():
    """Pô-los na planilha abriria a chance de a agenda contradizer o cadastro
    do órgão — que é o que derivar resolveu, no item 3 de 24/09."""
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO

    assert DESTINO_DO_CAMPO["esfera_id"] == "derivado"
    assert DESTINO_DO_CAMPO["frente"] == "derivado"
    assert DESTINO_DO_CAMPO["tier"] == "derivado"
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q -k destino`
Esperado: FALHA com `ImportError: cannot import name 'DESTINO_DO_CAMPO'`

- [ ] **Passo 3: Escrever o dicionário**

Acrescente `DESTINO_DO_CAMPO` ao módulo, classificando **todos** os campos de `InteracaoEntrada`. Consulte o modelo real antes de escrever — não adivinhe a lista. `interlocutor_id` é `"derivado"` (vem de quem está marcado `Principal`); `canal_id`, `remetente`, `teor`, `motivo`, `prazo_resposta`, `respondida_em`, `alegacoes` e `extensao` são `"fora da v1"`.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q` → PASSA

- [ ] **Passo 5: Commitar**

```bash
git add app/dominio/importacao_de_agendas.py tests/test_importacao_de_agendas.py
git commit -m "Todo campo da interação declara se vem da planilha, é derivado ou fica fora"
```

---

### Tarefa 3: O gerador do `.xlsx`

**Arquivos:**
- Criar: `app/casos_de_uso/modelo_de_importacao.py`
- Teste: `tests/test_modelo_de_importacao.py`

**Interfaces:**
- Consome: `FORMATO`, `VOCABULARIOS_EDITAVEIS`, `VOCABULARIOS_FECHADOS`.
- Produz: `gerar(vocabularios: Mapping[str, list[str]]) -> bytes`.

`vocabularios` chega pronto — o caso de uso não consulta banco, quem consulta é a rota. Isso mantém o gerador testável sem fixture de Postgres.

- [ ] **Passo 1: Escrever o teste que falha**

```python
"""O modelo que a pessoa baixa."""

import io

import pytest

from app.casos_de_uso.modelo_de_importacao import gerar
from app.dominio.importacao_de_agendas import FORMATO

VOCABULARIOS = {
    "instituicoes": ["Prefeitura de Campos", "Valor Econômico"],
    "interlocutores": ["Ana Prado"],
    "pessoas_aegea": ["Radamés Casseb"],
    "temas": ["Tarifa"],
    "unidades_negocio": ["Corsan"],
    "formatos_interacao": ["Reunião"],
    "areas": ["Regulatório"],
    "situacao": ["Confirmada", "Realizada"],
    "clima": ["Propositivo", "Neutro", "Tenso"],
    "resultado": ["Avançou"],
    "iniciativa": ["Aegea"],
    "modalidade": ["Presencial"],
    "presenca": ["Presente"],
    "papel": ["Porta-voz"],
    "momento": ["Apoio"],
}


def _abrir(conteudo: bytes):
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(conteudo))


def test_o_arquivo_tem_as_abas_de_preenchimento_e_as_de_vocabulario():
    planilha = _abrir(gerar(VOCABULARIOS))

    for aba in FORMATO:
        assert aba.nome in planilha.sheetnames


def test_o_cabecalho_de_cada_aba_e_o_da_descricao():
    """SE ISTO DIVERGIR, a pessoa preenche uma coluna que o leitor ignora."""
    planilha = _abrir(gerar(VOCABULARIOS))

    for aba in FORMATO:
        lidas = [celula.value for celula in next(planilha[aba.nome].iter_rows())]
        assert lidas[: len(aba.colunas)] == [c.nome for c in aba.colunas], aba.nome


def test_a_coluna_de_vocabulario_ganha_lista_suspensa():
    planilha = _abrir(gerar(VOCABULARIOS))
    agendas = planilha["Agendas"]

    assert len(agendas.data_validations.dataValidation) > 0


def test_a_aba_fechada_e_protegida_e_a_editavel_nao():
    """A diferença precisa ser visível E mecânica: a pessoa não deve conseguir
    digitar um clima novo sem esforço deliberado."""
    planilha = _abrir(gerar(VOCABULARIOS))

    assert planilha["Clima"].protection.sheet is True
    assert planilha["Instituições"].protection.sheet is False


def test_o_vocabulario_vazio_nao_quebra_o_arquivo():
    """Uma base nova não tem interlocutor nenhum, e o modelo tem de abrir."""
    vazio = {chave: [] for chave in VOCABULARIOS}

    planilha = _abrir(gerar(vazio))

    assert "Agendas" in planilha.sheetnames
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `py -3 -m pytest tests/test_modelo_de_importacao.py -q`
Esperado: FALHA com `ModuleNotFoundError`

- [ ] **Passo 3: Escrever o gerador**

Use `openpyxl.Workbook`. Para cada `Aba` de `FORMATO`, escreva o cabeçalho. Para cada vocabulário, crie uma aba com os valores em coluna e um `DefinedName` apontando para o intervalo. Para cada coluna com `vocabulario`, crie um `DataValidation(type="list", formula1="=NomeDefinido")` e adicione à faixa daquela coluna (ex.: `B2:B501`).

Proteja com `ws.protection.sheet = True` as abas dos vocabulários fechados. Nas editáveis, deixe uma linha em branco depois do último valor.

Importe `openpyxl` **dentro da função**, com o mesmo `except ModuleNotFoundError` que `ingerir_mencoes._linhas_da_aba` usa — é o padrão do repositório e a mensagem já está escrita lá.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `py -3 -m pytest tests/test_modelo_de_importacao.py -q` → PASSA

- [ ] **Passo 5: Abrir o arquivo de verdade**

```bash
py -3 -c "
from app.casos_de_uso.modelo_de_importacao import gerar
from tests.test_modelo_de_importacao import VOCABULARIOS
open('modelo.xlsx','wb').write(gerar(VOCABULARIOS))
"
```
Abra `modelo.xlsx` no Excel. Confira que a lista suspensa de Instituição funciona e que a aba Clima está protegida. **Apague o arquivo depois** — ele não vai para o repositório.

- [ ] **Passo 6: Commitar**

```bash
git add app/casos_de_uso/modelo_de_importacao.py tests/test_modelo_de_importacao.py
git commit -m "O modelo .xlsx é gerado da descrição, com lista suspensa e abas protegidas"
```

---

### Tarefa 4: O leitor e as recusas estruturais

**Arquivos:**
- Criar: `app/casos_de_uso/ler_planilha_de_agendas.py`
- Teste: `tests/test_ler_planilha_de_agendas.py`

**Interfaces:**
- Consome: `FORMATO`, `aba_de`.
- Produz: `LinhaBruta(aba, numero, celulas: Mapping[str, object])`, `ler(conteudo: bytes) -> dict[str, list[LinhaBruta]]`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
"""Bytes viram linhas, ou o arquivo é recusado inteiro."""

import io
from datetime import date

import pytest

from app.casos_de_uso.ler_planilha_de_agendas import ler
from app.dominio.erros import RegraViolada


def _planilha(abas: dict[str, list[list]]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    livro.remove(livro.active)
    for nome, linhas in abas.items():
        folha = livro.create_sheet(nome)
        for linha in linhas:
            folha.append(linha)
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


CABECALHO_AGENDAS = ["Código", "Data", "Instituição"]


def _minima(linhas_de_agenda: list[list], **outras) -> bytes:
    return _planilha({"Agendas": [CABECALHO_AGENDAS, *linhas_de_agenda], **outras})


def test_le_uma_agenda():
    lido = ler(_minima([["A1", date(2026, 9, 25), "Valor Econômico"]]))

    assert lido["Agendas"][0].celulas["Instituição"] == "Valor Econômico"


def test_a_data_digitada_como_TEXTO_e_lida(recorte=None):
    """UMA PLANILHA EXPORTADA DE OUTRA FERRAMENTA faz isso o tempo todo: a
    célula é texto e chega `str`, não `datetime`. Recusar seria recusar o
    arquivo que a pessoa de fato tem."""
    lido = ler(_minima([["A1", "25/09/2026", "Valor Econômico"]]))

    assert lido["Agendas"][0].celulas["Data"] == date(2026, 9, 25)


def test_a_linha_inteiramente_vazia_e_ignorada():
    lido = ler(_minima([[None, None, None], ["A1", date(2026, 9, 25), "X"]]))

    assert len(lido["Agendas"]) == 1


def test_aba_faltando_recusa_o_arquivo_inteiro():
    """Não faz sentido propor 54 agendas quando a planilha nem tem a aba."""
    with pytest.raises(RegraViolada, match="Participantes"):
        ler(_planilha({"Agendas": [CABECALHO_AGENDAS]}))


def test_coluna_faltando_recusa_e_diz_qual():
    with pytest.raises(RegraViolada, match="Instituição"):
        ler(_minima([], **{"Agendas": [["Código", "Data"]]}))


def test_codigo_repetido_recusa_o_arquivo():
    """Dois códigos iguais tornam impossível saber a qual agenda o participante
    pertence — e adivinhar seria pior que recusar."""
    with pytest.raises(RegraViolada, match="A1"):
        ler(
            _minima(
                [
                    ["A1", date(2026, 9, 25), "X"],
                    ["A1", date(2026, 9, 26), "Y"],
                ]
            )
        )


def test_linha_filha_com_codigo_orfao_recusa_e_cita_o_codigo():
    """A pessoa apagou a agenda e esqueceu os participantes dela. Importar os
    participantes de uma agenda que não existe é impossível, e ignorá-los em
    silêncio perderia gente da reunião."""
    conteudo = _planilha(
        {
            "Agendas": [CABECALHO_AGENDAS, ["A1", date(2026, 9, 25), "X"]],
            "Participantes": [["Código", "Pessoa"], ["A9", "Ana Prado"]],
        }
    )

    with pytest.raises(RegraViolada, match="A9"):
        ler(conteudo)


def test_arquivo_que_nao_e_xlsx_recusa_com_mensagem_util():
    with pytest.raises(RegraViolada, match="xlsx"):
        ler(b"isto nao e uma planilha")


def test_acima_do_teto_recusa():
    linhas = [["A%d" % i, date(2026, 9, 25), "X"] for i in range(501)]

    with pytest.raises(RegraViolada, match="500"):
        ler(_minima(linhas))
```

Ajuste os testes de aba/coluna faltando para o conjunto real de `FORMATO` — os exemplos acima usam um cabeçalho reduzido para caber no teste; o leitor exige o cabeçalho completo.

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `py -3 -m pytest tests/test_ler_planilha_de_agendas.py -q`
Esperado: FALHA com `ModuleNotFoundError`

- [ ] **Passo 3: Escrever o leitor**

Reuse a abertura de `ingerir_mencoes._linhas_da_aba`: `load_workbook(BytesIO, read_only=True, data_only=True)` dentro de `try/except` traduzindo para `RegraViolada` com a mensagem sobre `.xls`/`.csv`. Confira a assinatura `PK\x03\x04` antes, como `ASSINATURA_ZIP` já faz.

A data em texto: tente `datetime`/`date` direto; se vier `str`, tente `%d/%m/%Y` e `%Y-%m-%d`, nessa ordem. Falhando, deixe o valor cru — a divergência de data é da Tarefa 5, não daqui.

As quatro recusas estruturais (aba, coluna, código repetido, código órfão) levantam `RegraViolada` citando o que falta.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `py -3 -m pytest tests/test_ler_planilha_de_agendas.py -q` → PASSA

- [ ] **Passo 5: Commitar**

```bash
git add app/casos_de_uso/ler_planilha_de_agendas.py tests/test_ler_planilha_de_agendas.py
git commit -m "O leitor da planilha, com as quatro recusas estruturais"
```

---

### Tarefa 5: A classificação — resolve, cria ou diverge

**Arquivos:**
- Modificar: `app/dominio/importacao_de_agendas.py`
- Teste: `tests/test_importacao_de_agendas.py`

**Interfaces:**
- Consome: `LinhaBruta` da Tarefa 4, `normalizar` de `app/dominio/texto.py`.
- Produz: `Divergencia(campo, valor, mensagem, trava, sugestoes=())` — um `@dataclass(frozen=True, slots=True)`; `mensagem` é o texto que a pessoa lê e `trava` separa as duas severidades. `classificar(valor, vocabulario, conhecidos, declarados) -> Literal["resolve","cria","diverge"]`.

`conhecidos` é o que está no banco; `declarados` é o que a pessoa escreveu nas abas editáveis. **A distinção entre os dois é a regra central desta tarefa** e é o que torna defensável a decisão de produto de criar cadastro pela planilha.

- [ ] **Passo 1: Escrever o teste que falha**

```python
from app.dominio.importacao_de_agendas import classificar

CONHECIDOS = {"valor economico": "Valor Econômico"}


def test_casa_depois_de_normalizar_caixa_e_acento():
    assert classificar("VALOR ECONOMICO", "instituicoes", CONHECIDOS, set()) == "resolve"


def test_espaco_invisivel_colado_da_web_ainda_casa():
    """`\\xa0` é o espaço não separável que vem de copiar de uma página. A
    pessoa não vê diferença nenhuma na tela, e o valor não casaria."""
    assert classificar("Valor\\xa0Econômico ", "instituicoes", CONHECIDOS, set()) == "resolve"


def test_nome_novo_DECLARADO_na_aba_editavel_e_criado():
    declarados = {"prefeitura de campinas"}

    assert classificar(
        "Prefeitura de Campinas", "instituicoes", CONHECIDOS, declarados
    ) == "cria"


def test_nome_novo_digitado_SO_NA_CELULA_vira_divergencia():
    """A REGRA CENTRAL. Escrever na aba de cadastro é declaração de intenção;
    digitar na célula da agenda é, muito mais provavelmente, erro de grafia."""
    assert classificar(
        "Prefeitura de Campinas", "instituicoes", CONHECIDOS, set()
    ) == "diverge"


def test_o_mesmo_nome_em_duas_grafias_no_MESMO_arquivo_cria_um_so():
    """Declarado como "Prefeitura de Campinas" e usado como "PREFEITURA DE
    CAMPINAS": é o mesmo cadastro, e criar dois seria a duplicata que a
    conferência existe para evitar — agora vinda de dentro do arquivo."""
    declarados = {"prefeitura de campinas"}

    assert classificar(
        "PREFEITURA DE CAMPINAS", "instituicoes", CONHECIDOS, declarados
    ) == "cria"


def test_vocabulario_FECHADO_nunca_cria_mesmo_declarado():
    """A aba vem protegida, mas o Google Sheets tira a proteção ao converter.
    O servidor recusa de qualquer jeito: mudar clima é mudança de regra."""
    assert classificar("Eufórico", "clima", {}, {"euforico"}) == "diverge"
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q -k classificar`
Esperado: FALHA com `ImportError: cannot import name 'classificar'`

- [ ] **Passo 3: Escrever a classificação**

```python
def classificar(
    valor: str,
    vocabulario: str,
    conhecidos: Mapping[str, str],
    declarados: AbstractSet[str],
) -> str:
    chave = normalizar(valor)
    if chave in conhecidos:
        return "resolve"
    if vocabulario in VOCABULARIOS_FECHADOS:
        return "diverge"
    return "cria" if chave in declarados else "diverge"
```

`normalizar` já colapsa espaços — confira que `\xa0` cai no `\s+` do regex; se não cair, troque-o por espaço antes de normalizar e escreva o porquê no comentário.

Escreva acima da função o comentário que explica a distinção `conhecidos`/`declarados`: é a regra que sustenta a decisão de produto, e quem a ler daqui a um ano precisa saber que ela não é detalhe.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q` → PASSA

- [ ] **Passo 5: Commitar**

```bash
git add app/dominio/importacao_de_agendas.py tests/test_importacao_de_agendas.py
git commit -m "A classificação distingue o cadastro declarado do nome digitado na célula"
```

---

### Tarefa 6: A proposta — linha bruta vira `InteracaoEntrada`

**Arquivos:**
- Criar: `app/casos_de_uso/importar_agendas.py`
- Teste: `tests/test_importar_agendas.py` (usa Postgres)

**Interfaces:**
- Consome: `ler` (T4), `classificar` (T5), `DESTINO_DO_CAMPO` (T2).
- Produz: `Proposta(linha, entrada: InteracaoEntrada | None, divergencias: list[Divergencia])`, `propor(sessao, conteudo: bytes) -> list[Proposta]`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_a_agenda_limpa_vira_uma_entrada_valida(sessao, semente):
    conteudo = _planilha_com([[
        "A1", date(2026, 9, 25), semente["instituicao"].nome, "Reunião", "SP",
    ]])

    propostas = importar_agendas.propor(sessao, conteudo)

    assert propostas[0].divergencias == []
    assert propostas[0].entrada.instituicao_id == semente["instituicao"].id


def test_a_data_ausente_e_divergencia_que_trava(sessao, semente):
    conteudo = _planilha_com([["A1", None, semente["instituicao"].nome, "Reunião", "SP"]])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(d.trava for d in proposta.divergencias)


def test_a_mesma_instituicao_desconhecida_em_doze_linhas_e_UMA_divergencia(sessao, semente):
    """É o que faz a conferência escalar: uma decisão, doze linhas."""
    linhas = [
        ["A%d" % i, date(2026, 9, 25), "Prefeitura de Campinas", "Reunião", "SP"]
        for i in range(12)
    ]

    propostas = importar_agendas.propor(sessao, _planilha_com(linhas))
    valores = {
        d.valor for p in propostas for d in p.divergencias if d.campo == "instituicao_id"
    }

    assert valores == {"Prefeitura de Campinas"}


def _consultas_para_propor(sessao, conteudo: bytes) -> int:
    """Conta as consultas de um `propor`, no mesmo molde de
    `tests/test_leitura_sem_consulta_por_linha.py`. Aquele arquivo tem a mesma
    contagem presa a um helper privado (`_consultas_para_ler_uma_pagina`), e
    duplicar seis linhas é melhor que exportar o interno de outro teste."""
    from sqlalchemy import event

    contagem = 0

    def contar(*_):
        nonlocal contagem
        contagem += 1

    conexao = sessao.connection()
    event.listen(conexao, "before_cursor_execute", contar)
    try:
        importar_agendas.propor(sessao, conteudo)
    finally:
        event.remove(conexao, "before_cursor_execute", contar)
    return contagem


def test_o_custo_nao_cresce_com_o_numero_de_agendas(sessao, semente):
    """500 agendas não podem virar 500 buscas de instituição.

    A GARANTIA É POR INVARIÂNCIA, e não por um teto absoluto: um teto passa a
    ser escolhido para caber no que o código faz hoje, e sobe calado quando
    alguém acrescenta uma consulta. Comparar 3 com 30 não tem como subir
    calado — a única forma de o número mudar entre os dois é alguém ter
    voltado a consultar por linha. É o mesmo argumento, e o mesmo formato, de
    `test_o_numero_de_consultas_nao_cresce_com_as_linhas`.
    """
    def arquivo(quantas: int) -> bytes:
        return _planilha_com(
            [
                ["A%d" % i, date(2026, 9, 25), semente["instituicao"].nome, "Reunião", "SP"]
                for i in range(quantas)
            ]
        )

    com_tres = _consultas_para_propor(sessao, arquivo(3))
    assert com_tres > 0, "o contador não está escutando a conexão da sessão"

    com_trinta = _consultas_para_propor(sessao, arquivo(30))

    assert com_trinta == com_tres, (
        f"propor 30 agendas custou {com_trinta} consultas e propor 3 custou "
        f"{com_tres}: alguma coisa voltou a consultar por linha"
    )
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `BANCO_URL_TESTE=... py -3 -m pytest tests/test_importar_agendas.py -q`
Esperado: FALHA com `ModuleNotFoundError`

- [ ] **Passo 3: Escrever `propor`**

Leia os vocabulários **uma vez** para dicionários `normalizado → id`, no padrão de `catalogo_das_lentes`. Leia as abas editáveis para os conjuntos `declarados`. Depois percorra as linhas.

Monte `InteracaoEntrada(**campos)` só quando não houver divergência que trave. `frente`, `esfera_id` e `tier` **não** são preenchidos: quem os deriva é a rota de criação, na confirmação.

- [ ] **Passo 4: Rodar e ver passar** → PASSA

- [ ] **Passo 5: Commitar**

```bash
git add app/casos_de_uso/importar_agendas.py tests/test_importar_agendas.py
git commit -m "A linha da planilha vira proposta de interação, com as divergências agrupadas"
```

---

### Tarefa 7: As duas recusas do formulário que uma planilha consegue produzir

**Arquivos:**
- Modificar: `app/dominio/importacao_de_agendas.py`, `app/casos_de_uso/importar_agendas.py`
- Teste: `tests/test_importacao_de_agendas.py`

**Interfaces:**
- Consome: `Proposta` (T6).
- Produz: `IMPEDIMENTOS_DA_PLANILHA: frozenset[str]`, `impedimentos(proposta) -> list[Divergencia]`.

As seis recusas vivem em TypeScript, em `front/src/paginas/cadastro/impedimento.ts`, e a importação é Python. Duplicar as seis criaria duas versões da mesma verdade, das quais uma envelheceria. A spec decidiu implementar **só as duas que uma planilha pode de fato produzir** — e a parte que faz a decisão sobreviver é o teste que prende as duas listas uma à outra.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_participante_que_nao_pertence_a_instituicao_e_recusado():
    """A planilha produz isto com facilidade: a pessoa copia a linha de uma
    agenda e troca só a instituição, deixando os participantes da anterior."""
    proposta = _proposta(instituicao="inst-1", participantes=["p-de-outra"])

    (impedimento,) = impedimentos(proposta, podem_representar=frozenset())

    assert "não pertence" in impedimento.mensagem


def test_material_com_titulo_e_sem_destino_e_recusado():
    proposta = _proposta(materiais=[{"titulo": "Nota técnica", "url": "", "arquivo_id": None}])

    (impedimento,) = impedimentos(proposta, podem_representar=frozenset())

    assert "não leva a lugar nenhum" in impedimento.mensagem


def test_material_com_arquivo_e_sem_link_passa():
    # O contrapeso: destino é arquivo OU link. É a mesma regra do
    # `impedimento.ts`, e inverter o OU aqui recusaria todo material que veio
    # por upload.
    proposta = _proposta(materiais=[{"titulo": "Nota", "url": "", "arquivo_id": "arq-1"}])

    assert impedimentos(proposta, podem_representar=frozenset()) == []


def test_as_duas_listas_de_impedimento_nao_se_perdem_de_vista():
    """O GUARDA DA DECISÃO, e o motivo de esta tarefa existir.

    A spec escolheu implementar em Python 2 das 6 recusas do formulário. Essa
    escolha só é defensável enquanto alguém souber que as outras 4 existem e
    POR QUE ficaram de fora. Sem este teste, a sétima recusa nasce no
    TypeScript e ninguém nunca pergunta se a planilha a produz.

    É o mesmo mecanismo de `_DE_TEXTO` no `Recorte` e do `DESTINO` de
    `corpo.test.ts`: uma lista que obriga a classificar o que for novo.
    """
    import re, pathlib

    ts = pathlib.Path("../front-reputacional/src/paginas/cadastro/impedimento.test.ts")
    if not ts.exists():
        pytest.skip("o repositório do front não está ao lado deste")

    # Os `describe` numerados do teste do front são a lista canônica das seis.
    no_front = set(re.findall(r"describe\('(\d)\. ", ts.read_text(encoding="utf-8")))

    assert no_front == {"1", "2", "3", "4", "5", "6"}, (
        f"o front agora tem as recusas {sorted(no_front)}: uma mudou de número "
        "ou nasceu uma nova. Decida se a planilha a produz e classifique-a em "
        "IMPEDIMENTOS_DA_PLANILHA ou em FORA_DA_PLANILHA."
    )
    assert IMPEDIMENTOS_DA_PLANILHA | FORA_DA_PLANILHA == no_front
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `py -3 -m pytest tests/test_importacao_de_agendas.py -q -k impedimento`
Esperado: FALHA com `ImportError: cannot import name 'impedimentos'`

- [ ] **Passo 3: Escrever os impedimentos**

`IMPEDIMENTOS_DA_PLANILHA = frozenset({"1", "2"})` (material sem destino, material sem título — os dois que uma planilha produz ao ter título numa coluna e nada nas outras) e `FORA_DA_PLANILHA = frozenset({"3", "5", "6"})`, com a regra 4 entrando em `IMPEDIMENTOS_DA_PLANILHA`. Escreva ao lado de cada um dos `FORA_DA_PLANILHA` a frase que diz por quê: são artefatos de formulário meio preenchido — uma linha sem pessoa escolhida existe porque alguém clicou "acrescentar" e parou, e a planilha não tem esse estado.

Confira a numeração real abrindo `impedimento.test.ts` antes de escrever: os números vêm de lá, não deste plano.

`impedimentos()` devolve `Divergencia` com `trava=True`.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `BANCO_URL_TESTE=... py -3 -m pytest -q` → tudo verde

- [ ] **Passo 5: Commitar**

```bash
git add app/dominio/importacao_de_agendas.py app/casos_de_uso/importar_agendas.py tests/test_importacao_de_agendas.py
git commit -m "A importação recusa o que a planilha consegue produzir, e prende as duas listas"
```

---

### Tarefa 8: As tabelas, o repositório e `POST /api/importacoes`

**Arquivos:**
- Criar: `app/banco/tabelas_importacao.py`, `app/banco/repositorio_importacao.py`, `app/api/importacoes.py`
- Modificar: `main.py`, `tests/test_portal_no_backend.py`
- Teste: `tests/test_importacoes_api.py`

**Interfaces:**
- Consome: `propor` (T6).
- Produz: rotas `GET /modelo`, `POST /`, `GET /{id}`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_quem_nao_administra_cadastros_nao_importa(cliente_sem_admin, semente):
    """A decisão de produto: só a coordenação importa. E esconder o botão é
    conveniência — o servidor recusa."""
    resposta = cliente_sem_admin.post(
        "/api/importacoes", files={"arquivo": ("a.xlsx", b"PK\x03\x04", TIPO_XLSX)}
    )

    assert resposta.status_code == 403


def test_toda_rota_sob_importacoes_exige_administrar_cadastros():
    """A âncora estrutural, no mesmo molde da do Score: rota nova sob este
    prefixo nasce protegida, ou este teste quebra."""
    from app.api.dependencias import exigir_administracao_de_cadastros
    from tests.test_portal_no_backend import _rotas_montadas
    from main import app

    desprotegidas = [
        rota.path
        for rota in _rotas_montadas(app)
        if rota.path.startswith("/api/importacoes")
        and exigir_administracao_de_cadastros
        not in {d.call for d in rota.dependant.dependencies}
    ]

    assert desprotegidas == []


def test_o_modelo_baixa_um_xlsx_que_abre(cliente_admin):
    resposta = cliente_admin.get("/api/importacoes/modelo")

    assert resposta.status_code == 200
    assert resposta.content[:4] == b"PK\x03\x04"


def test_subir_grava_a_importacao_e_devolve_as_propostas(cliente_admin, semente):
    resposta = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(semente), TIPO_XLSX)},
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["situacao"] == "aguardando_conferencia"
    assert len(corpo["linhas"]) == 3


def test_a_importacao_sobrevive_a_fechar_o_navegador(cliente_admin, semente):
    """É para isto que a 0008 criou tabela em vez de resolver em memória."""
    criada = cliente_admin.post(
        "/api/importacoes",
        files={"arquivo": ("dia.xlsx", _planilha_de_um_dia(semente), TIPO_XLSX)},
    ).json()

    retomada = cliente_admin.get(f"/api/importacoes/{criada['id']}")

    assert retomada.json()["linhas"] == criada["linhas"]
```

- [ ] **Passo 2: Rodar e ver falhar** → FALHA com 404 nas rotas

- [ ] **Passo 3: Escrever as tabelas, o repositório e as rotas**

`tabelas_importacao.py` mapeia as duas tabelas da `0008` **sem alterá-las**. Use `DateTime(timezone=True)` em `criado_em` e `confirmado_em` — os módulos novos do Score erraram isso e a spec não vai repetir. Leia a `0008` inteira antes de escrever o mapeamento: o cabeçalho dela descreve o fluxo em quatro passos, e é o mesmo desta spec.

O `POST` grava `arquivo_nome` (do `UploadFile`) e `criado_por` (o usuário logado), cria a importação em `'processando'`, e só a move para `'aguardando_conferencia'` depois de gravar as linhas — a situação inicial existe justamente para que um arquivo cujo processamento morreu no meio não apareça como pronto para conferir.

O router:

```python
rotas = APIRouter(
    prefix="/api/importacoes",
    tags=["importacoes"],
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_administracao_de_cadastros)],
)
```

`GET /modelo` lê os vocabulários do banco e chama `modelo_de_importacao.gerar`. Devolva `Response(content=..., media_type=TIPO_XLSX)` com `Content-Disposition: attachment; filename*=UTF-8''modelo-de-agendas.xlsx` — use `quote()` como `api/interacoes.py:374` faz, e não a interpolação crua de `referencias.py:452`.

Acrescente `/api/importacoes` a `PREFIXOS_DO_CRM` em `tests/test_portal_no_backend.py`.

- [ ] **Passo 4: Rodar e ver passar**

Rode a suíte inteira: `BANCO_URL_TESTE=... py -3 -m pytest -q` → tudo verde

- [ ] **Passo 5: Commitar**

```bash
git add app/banco/tabelas_importacao.py app/banco/repositorio_importacao.py \
        app/api/importacoes.py main.py tests/test_importacoes_api.py \
        tests/test_portal_no_backend.py
git commit -m "A importação ganha rotas, persistência e a âncora estrutural"
```

---

### Tarefa 9: O agrupamento por valor — a vista da conferência

**Arquivos:**
- Modificar: `app/dominio/importacao_de_agendas.py`, `app/api/importacoes.py`
- Teste: `tests/test_importacao_de_agendas.py`

**Interfaces:**
- Produz: `agrupar(propostas) -> list[GrupoDeDivergencia]` com `valor`, `campo`, `linhas: list[int]`, `sugestoes: list[str]`, `trava: bool`.

O grupo **não é tabela**: é uma vista montada ao ler `importacao_linha.divergencias`. Não crie migration.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_agrupa_por_valor_e_conta_as_linhas():
    grupos = agrupar(_propostas_com_instituicao_desconhecida(quantas=12))

    assert grupos[0].valor == "Prefeitura de Campinas"
    assert len(grupos[0].linhas) == 12


def test_ordena_pelo_que_segura_mais_linhas():
    """A pessoa resolve primeiro o que destrava mais."""
    grupos = agrupar(_propostas(instituicoes={"A": 12, "B": 3}))

    assert [g.valor for g in grupos] == ["A", "B"]


def test_a_sugestao_traz_os_nomes_parecidos():
    grupos = agrupar(_propostas(instituicoes={"Prefeitura de Campinas": 1}),
                     conhecidos=["Prefeitura Municipal de Campinas", "Valor Econômico"])

    assert "Prefeitura Municipal de Campinas" in grupos[0].sugestoes
    assert "Valor Econômico" not in grupos[0].sugestoes


def test_a_duplicata_possivel_NAO_trava():
    """Duas reuniões com o mesmo órgão no mesmo dia acontecem. Travar por isso
    ensinaria a ignorar o aviso."""
    (grupo,) = agrupar(_propostas_com_duplicata())

    assert grupo.trava is False
```

- [ ] **Passo 2: Rodar e ver falhar** → `ImportError: cannot import name 'agrupar'`

- [ ] **Passo 3: Escrever `agrupar`**

Agrupe por `(campo, valor)`. Ordene por `len(linhas)` decrescente, desempatando pelo valor para a ordem ser estável entre duas leituras. As sugestões usam `difflib.get_close_matches` sobre os nomes normalizados conhecidos.

- [ ] **Passo 4: Rodar e ver passar** → PASSA

- [ ] **Passo 5: Commitar**

```bash
git add app/dominio/importacao_de_agendas.py app/api/importacoes.py tests/test_importacao_de_agendas.py
git commit -m "As divergências se agrupam por valor, ordenadas pelo que destrava mais"
```

---

### Tarefa 10: `PATCH /{id}/resolucoes`

**Arquivos:**
- Modificar: `app/casos_de_uso/importar_agendas.py`, `app/api/importacoes.py`
- Teste: `tests/test_importacoes_api.py`

**Interfaces:**
- Produz: `resolver(sessao, importacao_id, campo, valor, decisao, alvo) -> None`, com `decisao in {"apontar", "criar", "descartar"}`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_apontar_para_uma_existente_resolve_as_doze_linhas(cliente_admin, importacao_com_12):
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_12['id']}/resolucoes",
        json={
            "campo": "instituicao_id",
            "valor": "Prefeitura de Campinas",
            "decisao": "apontar",
            "alvo": str(ID_DA_PREFEITURA_EXISTENTE),
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["pendencias"] == 0


def test_descartar_tira_as_linhas_sem_apagar_o_bruto(cliente_admin, importacao_com_12):
    """`dados_brutos` fica: é o que permite reprocessar e responder de onde
    veio o registro."""
    cliente_admin.patch(
        f"/api/importacoes/{importacao_com_12['id']}/resolucoes",
        json={"campo": "instituicao_id", "valor": "Prefeitura de Campinas",
              "decisao": "descartar"},
    )

    estado = cliente_admin.get(f"/api/importacoes/{importacao_com_12['id']}").json()
    descartadas = [l for l in estado["linhas"] if l["decisao"] == "descartada"]
    assert len(descartadas) == 12
    assert all(l["dados_brutos"] for l in descartadas)


def test_resolver_um_valor_que_nao_esta_pendente_recusa(cliente_admin, importacao_com_12):
    resposta = cliente_admin.patch(
        f"/api/importacoes/{importacao_com_12['id']}/resolucoes",
        json={"campo": "instituicao_id", "valor": "Não existe", "decisao": "criar"},
    )

    assert resposta.status_code == 422
```

- [ ] **Passo 2: Rodar e ver falhar** → 404/405

- [ ] **Passo 3: Escrever `resolver`**

Reescreva a `proposta` de cada linha afetada e remova aquela divergência de `divergencias`. `decisao="descartar"` marca `decisao='descartada'` nas linhas e **não** apaga `dados_brutos`.

- [ ] **Passo 4: Rodar e ver passar** → PASSA

- [ ] **Passo 5: Commitar**

```bash
git add app/casos_de_uso/importar_agendas.py app/api/importacoes.py tests/test_importacoes_api.py
git commit -m "Resolver um grupo de divergência resolve todas as linhas dele"
```

---

### Tarefa 11: `POST /{id}/confirmacao` — reconferência e transação

**Arquivos:**
- Modificar: `app/casos_de_uso/importar_agendas.py`, `app/api/importacoes.py`
- Teste: `tests/test_importacoes_api.py`

**Interfaces:**
- Produz: `confirmar(sessao, importacao_id, usuario) -> Resumo(criadas: int, cadastros: int)`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
def test_confirmar_cria_as_agendas_e_os_cadastros_juntos(cliente_admin, importacao_limpa):
    antes = _quantas_interacoes(sessao)

    resposta = cliente_admin.post(f"/api/importacoes/{importacao_limpa['id']}/confirmacao")

    assert resposta.status_code == 201
    assert _quantas_interacoes(sessao) == antes + 3


def test_cancelar_nao_deixa_cadastro_orfao(cliente_admin, sessao, importacao_com_cadastro_novo):
    """Se os cadastros nascessem no upload, cancelar deixaria instituições
    criadas sem nenhuma agenda a que servissem."""
    instituicoes_antes = _quantas_instituicoes(sessao)

    cliente_admin.post(f"/api/importacoes/{importacao_com_cadastro_novo['id']}/cancelamento")

    assert _quantas_instituicoes(sessao) == instituicoes_antes


def test_a_agenda_criada_guarda_de_onde_veio(cliente_admin, sessao, importacao_limpa):
    cliente_admin.post(f"/api/importacoes/{importacao_limpa['id']}/confirmacao")

    criada = _ultima_interacao(sessao)
    assert criada.fonte == "planilha"
    assert criada.origem_aba == "Agendas"
    assert criada.origem_linha == 2


def test_o_vocabulario_que_mudou_entre_subir_e_confirmar_PARA_a_confirmacao(
    cliente_admin, sessao, importacao_com_cadastro_novo
):
    """O PONTO MAIS DELICADO. Entre subir e confirmar, alguém cadastrou a mesma
    instituição pela tela de Administração. Confirmar cego criaria a duplicata
    que a conferência existia para evitar."""
    _cadastrar_pela_tela(sessao, "Prefeitura de Campinas")

    resposta = cliente_admin.post(
        f"/api/importacoes/{importacao_com_cadastro_novo['id']}/confirmacao"
    )

    assert resposta.status_code == 409
    assert "Prefeitura de Campinas" in resposta.json()["detalhe"]


def test_a_falha_no_meio_nao_deixa_metade_criada(cliente_admin, sessao, importacao_limpa, monkeypatch):
    """Ou tudo entra, ou nada entra."""
    antes = _quantas_interacoes(sessao)
    monkeypatch.setattr(registrar_interacao, "registrar", _explode_na_terceira)

    with pytest.raises(Exception):
        cliente_admin.post(f"/api/importacoes/{importacao_limpa['id']}/confirmacao")

    assert _quantas_interacoes(sessao) == antes
```

- [ ] **Passo 2: Rodar e ver falhar** → 404

- [ ] **Passo 3: Escrever `confirmar`**

1. Releia os vocabulários do banco **agora**.
2. Reclassifique cada proposta. Se alguma resolução deixou de valer — o que ia ser criado já existe, o que estava apontado sumiu —, levante `RegraViolada` citando o valor. O tradutor central devolve 409 se você usar um erro próprio; se preferir 422, ajuste o teste, mas **decida e seja consistente**.
3. Crie os cadastros novos.
4. Para cada linha aceita, chame `registrar_interacao.registrar` com a entrada montada, passando `fonte="planilha"`, `origem_aba` e `origem_linha`.
5. Marque `importacao.situacao='confirmada'`, `confirmado_em=now()`, e grave `interacao_id` em cada linha.

Tudo na sessão da requisição — o commit acontece no teardown da dependência, como `app/banco/sessao.py:108` descreve. **Não** chame `sessao.commit()` no caso de uso.

- [ ] **Passo 4: Rodar e ver passar** → PASSA

- [ ] **Passo 5: Rodar a suíte inteira**

Rode: `BANCO_URL_TESTE=... py -3 -m pytest -q` e `py -3 -m ruff check app/ tests/`

- [ ] **Passo 6: Commitar**

```bash
git add app/casos_de_uso/importar_agendas.py app/api/importacoes.py tests/test_importacoes_api.py
git commit -m "A confirmação reconfere o vocabulário e cria tudo numa transação só"
```

---

### Tarefa 12: A tela de conferência (front)

**Arquivos:**
- Criar: `src/paginas/importacao/ConferirImportacao.tsx`, `src/paginas/importacao/grupos.ts`, `src/paginas/importacao/grupos.test.ts`
- Modificar: `src/api/cliente.ts`, `src/navegacao/rota.ts`, `src/navegacao/areas.ts`, `src/paginas/Base.tsx` (o botão de importar)

**Interfaces:**
- Consome: as cinco rotas das Tarefas 8–11.
- Produz: destino `'importacao'` na rota, com `?id=`.

- [ ] **Passo 1: Escrever o teste que falha**

`grupos.ts` é a lógica pura da tela — o que está pendente, o que trava, se dá para confirmar. Ela sai do componente pelo critério que o `README` agora declara: se você quer escrever o teste e não consegue, está no lugar errado.

```typescript
import { describe, expect, it } from 'vitest';
import { contagens, podeConfirmar, pendencias } from '@/paginas/importacao/grupos';

const TRAVA = { valor: 'Prefeitura de Campinas', campo: 'instituicao_id', linhas: [1, 2], trava: true };
const AVISA = { valor: 'duplicata', campo: 'data_interacao', linhas: [3], trava: false };

describe('podeConfirmar', () => {
  it('não confirma com divergência que trava', () => {
    expect(podeConfirmar([TRAVA, AVISA])).toBe(false);
  });

  it('confirma com apenas avisos', () => {
    // A duplicata possível avisa e não impede: duas reuniões com o mesmo órgão
    // no mesmo dia acontecem.
    expect(podeConfirmar([AVISA])).toBe(true);
  });

  it('confirma sem divergência nenhuma', () => {
    expect(podeConfirmar([])).toBe(true);
  });
});

describe('pendencias', () => {
  it('conta só o que trava', () => {
    expect(pendencias([TRAVA, AVISA])).toBe(1);
  });
});

describe('o cabeçalho', () => {
  it('conta agendas, pendências e cadastros novos', () => {
    // As três contagens do cabeçalho saem daqui e não do JSX: são a primeira
    // coisa que a pessoa lê para decidir se tem tempo de conferir agora.
    expect(contagens({ linhas: 54, grupos: [TRAVA, AVISA], aCriar: ['A', 'B', 'C'] })).toEqual({
      agendas: 54,
      pendencias: 1,
      cadastrosNovos: 3,
    });
  });
});
```

- [ ] **Passo 2: Rodar e ver falhar**

Rode: `npx vitest run src/paginas/importacao/grupos.test.ts`
Esperado: FALHA com `Cannot find package '@/paginas/importacao/grupos'`

- [ ] **Passo 3: Escrever `grupos.ts` e o componente**

O cabeçalho responde "quanto falta" numa linha — **54 agendas · 6 pendências · 3 cadastros novos** — e as três contagens saem de `grupos.ts`, não do JSX, pelo mesmo motivo que `podeConfirmar` saiu.

O componente tem três blocos, na ordem da spec: *o que precisa de você* (grupos que travam, depois os que avisam), *o que vou criar* (recolhido), e *as 54 linhas* (com filtro "só as que têm pendência").

Grades em classes de `index.css`, nunca em estilo inline — a regra está escrita no próprio arquivo e já quebrou o responsivo uma vez.

- [ ] **Passo 4: Rodar e ver passar**

Rode: `npx tsc -b && npm run test && npm run lint && npm run build`

- [ ] **Passo 5: Conferir no navegador**

Suba a pilha, entre como `plataforma.edicao@aegea.com.br`, baixe o modelo, preencha três agendas sendo uma com instituição inexistente, suba, e confira que o grupo aparece com a contagem certa.

- [ ] **Passo 6: Commitar**

```bash
git add src/paginas/importacao src/api/cliente.ts src/navegacao src/paginas/Base.tsx src/index.css
git commit -m "A tela de conferência da importação, agrupando por valor"
```

---

## Ao terminar

Rode a suíte inteira dos dois repositórios, suba a pilha local e faça o caminho completo uma vez: baixar o modelo, preencher um dia, subir, resolver uma divergência, confirmar, e abrir uma das agendas criadas na Base para conferir que ela está igual a uma digitada — exceto por `fonte`.
