"""A menção aponta para a concessionária do cadastro, e a subida é quem liga.

O QUE ESTAVA QUEBRADO. `mencao.unidade_negocio_id` existe desde a `0048` e
estava preenchido em ZERO das 104.670 menções. A dimensão "Concessionária" das
lentes agrupava pelo TEXTO do fornecedor, e a mesma operação chega em grafias
diferentes: a Corsan como "Corsan" (1.111) e como "Companhia Riograndense de
Saneamento (Corsan)" (15.019) — duas barras no gráfico, dois valores no filtro,
e recortar por uma perdia a outra.

O QUE ESTES TESTES PROTEGEM:

* que a CHAVE SEMEADA na `0099` seja a que `normalizar` calcula. É o teste mais
  importante do arquivo: as cinco chaves foram escritas à mão em SQL, e um
  acento a mais ali viraria um apelido que nunca casa — o sintoma seria 15.019
  menções sem concessionária, e não um erro;
* que NUNCA se adivinhe bloco: "Águas do Pará" são quatro linhas do cadastro, e
  nenhuma delas é a resposta;
* que a semelhança não resolva: "Águas de São Francisco" (132 menções) NÃO é
  "Águas de São Francisco do Sul" (7.528) — é outra operação, em outro estado;
* que a conferência separe o nome AMBÍGUO do DESCONHECIDO, porque os consertos
  são diferentes e feitos por pessoas diferentes;
* que o vínculo valha para os dois caminhos de escrita, porque mora em
  `regravar` — a subida de uma vez e a subida em partes convergem nele.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Tema, UnidadeNegocio, UnidadeNegocioApelido
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.casos_de_uso import ingerir_mencoes, unidade_da_mencao
from app.dominio.ingestao_score import Mapeamento
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


@pytest.fixture
def bites(sessao) -> ScoreFonte:
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))
    assert fonte is not None
    return fonte


@pytest.fixture
def um_tema(sessao) -> Tema:
    tema = sessao.scalar(
        select(Tema).where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None)).limit(1)
    )
    assert tema is not None
    return tema


def _planilha(fonte: ScoreFonte, linhas: list[list]) -> bytes:
    """Uma planilha da Bites, com o cabeçalho que o cadastro dela manda ler."""
    from openpyxl import Workbook

    coluna_do_tema = Mapeamento.de_json(fonte.mapeamento_colunas).colunas["tema"]
    livro = Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(["Relatório mensal", None])
    aba.append(
        ["Data", "Cargo", "Sentimento", "Unidades/Empresas", coluna_do_tema, "Engajamento"]
    )
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _linha(unidade: str, assunto: str, dia: int = 3) -> list:
    return [date(2026, 8, dia), "Vereador", "Positivo", unidade, assunto, 10]


# -- o cadastro e os apelidos semeados -----------------------------------------


def test_a_chave_semeada_e_a_que_o_codigo_calcula(sessao):
    """O TESTE QUE PAGA A ESCOLHA DE SEMEAR EM SQL.

    A `0099` escreveu as cinco chaves à mão (`'aegea saneamento e participacoes
    s/a'`), porque `normalizar` é Python e a migration é SQL. A `0097` já mostrou
    o preço de reimplementar essa função em SQL: divergiu em 67 de 87 valores
    reais. Aqui a chave é escrita à mão UMA vez e conferida contra a função de
    verdade — o que torna o erro de digitação impossível de passar.

    E o sintoma que ele teria é o pior tipo: nenhuma exceção, nenhum log. Só
    15.019 menções da Corsan continuando sem concessionária.
    """
    apelidos = sessao.execute(
        select(UnidadeNegocioApelido.nome_normalizado, UnidadeNegocioApelido.nome)
    ).all()
    assert apelidos, "a 0099 semeia cinco apelidos; nenhum chegou"
    errados = [
        (chave, nome, normalizar(nome))
        for chave, nome in apelidos
        if chave != normalizar(nome)
    ]
    assert not errados, f"chave semeada ≠ normalizar(nome): {errados}"


def test_nenhum_apelido_repete_um_nome_do_cadastro(sessao):
    """Apelido que repete um nome do cadastro é dado contraditório.

    `cadastro()` resolve o nome PRIMEIRO (`setdefault`), então o apelido nunca
    venceria — mas o conflito ficaria calado, e um dia alguém o leria como "o
    apelido manda". Os dois não podem coexistir.
    """
    nomes = {
        normalizar(nome)
        for (nome,) in sessao.execute(select(UnidadeNegocio.nome))
    }
    apelidos = {
        chave for (chave,) in sessao.execute(select(UnidadeNegocioApelido.nome_normalizado))
    }
    assert not (nomes & apelidos), f"apelido que já é nome do cadastro: {nomes & apelidos}"


def test_os_nomes_do_cadastro_dao_chaves_distintas(sessao):
    """Duas unidades que normalizassem igual fariam uma sumir do mapa em silêncio.

    `unidade_negocio.nome` tem índice único, mas sobre o texto CRU: "Corsan" e
    "corsan" caberiam as duas, e `cadastro()` guardaria só a última. Medido hoje:
    29 nomes, 29 chaves. É o cadastro que pode mudar, não este código.
    """
    nomes = [nome for (nome,) in sessao.execute(select(UnidadeNegocio.nome))]
    chaves = {normalizar(nome) for nome in nomes}
    assert len(chaves) == len(nomes), (
        "duas unidades do cadastro normalizam para a mesma chave: "
        f"{len(nomes)} nomes, {len(chaves)} chaves"
    )


def test_a_familia_agrupa_as_irmas_e_deixa_as_outras_sozinhas(sessao):
    """A heurística do sufixo, contra o cadastro de verdade.

    ELA SÓ EXISTE PARA A MENSAGEM, nunca para resolver — ver
    `unidade_da_mencao`. Este teste prende o que ela agrupa HOJE, para que
    alargá-la (ou o cadastro ganhar um nome terminado em dígito) seja uma
    mudança visível e não um efeito colateral.
    """
    cadastro = unidade_da_mencao.cadastro(sessao)
    assert set(cadastro.familias) == {
        unidade_da_mencao.familia("Águas do Rio 1"),
        unidade_da_mencao.familia("Ambiental Ceará 1"),
        unidade_da_mencao.familia("Águas do Pará — Bloco A"),
    }
    assert cadastro.familias[unidade_da_mencao.familia("Águas do Pará")] == (
        "Águas do Pará — Bloco A",
        "Águas do Pará — Bloco B",
        "Águas do Pará — Bloco C",
        "Águas do Pará — Bloco D",
    )


# -- resolver: o que liga e o que NÃO liga -------------------------------------


def test_o_nome_exato_do_cadastro_resolve(sessao):
    cadastro = unidade_da_mencao.cadastro(sessao)
    esperado = sessao.scalar(select(UnidadeNegocio.id).where(UnidadeNegocio.nome == "Corsan"))
    assert cadastro.resolver("Corsan") == esperado
    #: CAIXA E ACENTO NÃO DECIDEM: a chave é `normalizar`, como no veículo e no
    #: tema. Uma planilha que escreva "CORSAN" liga igual.
    assert cadastro.resolver("  CORSAN ") == esperado


def test_o_apelido_resolve_para_a_mesma_unidade_do_nome(sessao):
    """O ponto da `0099`: as duas grafias da Corsan viram UMA chave.

    São 16.130 menções da mesma empresa que estavam em dois baldes.
    """
    cadastro = unidade_da_mencao.cadastro(sessao)
    pelo_nome = cadastro.resolver("Corsan")
    pelo_apelido = cadastro.resolver("Companhia Riograndense de Saneamento (Corsan)")
    assert pelo_nome is not None
    assert pelo_apelido == pelo_nome


def test_a_holding_resolve_pelas_duas_grafias_do_fornecedor(sessao):
    cadastro = unidade_da_mencao.cadastro(sessao)
    esperado = sessao.scalar(
        select(UnidadeNegocio.id).where(UnidadeNegocio.nome == "Holding / corporativo")
    )
    assert cadastro.resolver("Holding") == esperado
    assert cadastro.resolver("Aegea Saneamento e Participações S/A") == esperado


@pytest.mark.parametrize(
    "nome", ["Águas do Rio", "Águas do Pará", "Ambiental Ceará"]
)
def test_o_nome_de_familia_NAO_resolve(sessao, nome):
    """NUNCA SE ADIVINHA BLOCO, e é a regra que define o desenho.

    São 14.703 menções. Escolher um bloco por ordem, por volume ou por qualquer
    critério inventaria um dado que a planilha não tem — e ele sairia depois num
    relatório por concessionária como se fosse informação.
    """
    assert unidade_da_mencao.cadastro(sessao).resolver(nome) is None


def test_sao_francisco_nao_vira_sao_francisco_do_sul(sessao):
    """A SEMELHANÇA NÃO RESOLVE, e este é o par que prova por que.

    "Águas de São Francisco" (132 menções) e "Águas de São Francisco do Sul"
    (7.528, e no cadastro) são operações diferentes, em estados diferentes. Um
    passo por prefixo ou por similaridade juntaria as duas e o erro sairia num
    relatório por concessionária sem nada acusar.
    """
    cadastro = unidade_da_mencao.cadastro(sessao)
    do_sul = cadastro.resolver("Águas de São Francisco do Sul")
    assert do_sul is not None, "o cadastro tem São Francisco do Sul"
    assert cadastro.resolver("Águas de São Francisco") is None


def test_o_que_o_cadastro_nao_tem_nao_resolve(sessao):
    cadastro = unidade_da_mencao.cadastro(sessao)
    assert cadastro.resolver("Águas de Sinop") is None
    assert cadastro.resolver("") is None
    assert cadastro.resolver(None) is None


# -- reconhecer: o que a conferência diz antes de gravar -----------------------


def test_reconhecer_separa_o_AMBIGUO_do_DESCONHECIDO(sessao):
    """DOIS PROBLEMAS, DOIS CONSERTOS, e é por isso que `opcoes` existe.

    "Águas do Pará" está escrito CERTO e mesmo assim não liga: o conserto é o
    fornecedor informar o bloco. "Águas de Sinop" o cadastro não tem: o conserto
    é cadastrar a unidade. Um booleano "não reconhecido" mandaria as duas pessoas
    para o mesmo lugar errado.
    """
    reco = unidade_da_mencao.reconhecer(
        sessao,
        {"Corsan": 10, "Águas do Pará": 7, "Águas de Sinop": 3},
    )
    assert reco.ligadas == 10
    por_nome = {item.nome: item for item in reco.nao_ligados}
    assert set(por_nome) == {"Águas do Pará", "Águas de Sinop"}
    assert len(por_nome["Águas do Pará"].opcoes) == 4
    assert por_nome["Águas de Sinop"].opcoes == ()
    assert reco.nao_ligadas == 10


def test_reconhecer_conta_quem_veio_sem_concessionaria(sessao):
    reco = unidade_da_mencao.reconhecer(sessao, {"": 5, "Corsan": 1})
    assert reco.sem_unidade == 5
    assert reco.ligadas == 1
    #: VAZIO NÃO É "NÃO RECONHECIDO": ele não vira linha da lista, senão a
    #: pessoa procuraria na planilha um nome que não existe.
    assert reco.nao_ligados == ()


def test_reconhecer_ordena_por_volume(sessao):
    reco = unidade_da_mencao.reconhecer(
        sessao, {"Águas de Sinop": 3, "Águas de Sorriso": 50, "Águas de Jaru": 9}
    )
    assert [item.nome for item in reco.nao_ligados] == [
        "Águas de Sorriso",
        "Águas de Jaru",
        "Águas de Sinop",
    ]


def test_o_apelido_conta_como_LIGADA_na_conferencia(sessao):
    """A conferência tem de prometer o que a subida faz. Se ela listasse o
    apelido como não reconhecido, a pessoa cobraria do fornecedor uma correção
    que o sistema já faz."""
    reco = unidade_da_mencao.reconhecer(
        sessao, {"Companhia Riograndense de Saneamento (Corsan)": 42}
    )
    assert reco.ligadas == 42
    assert reco.nao_ligados == ()


# -- a subida grava a chave ----------------------------------------------------


def test_a_subida_liga_a_mencao_pelo_nome_do_cadastro(sessao, bites, um_tema):
    ingerir_mencoes.ingerir(sessao, bites, _planilha(bites, [_linha("Corsan", um_tema.nome)]))

    gravada = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    ).one()
    esperado = sessao.scalar(select(UnidadeNegocio.id).where(UnidadeNegocio.nome == "Corsan"))
    assert gravada.unidade_negocio_id == esperado
    #: E O TEXTO DO FORNECEDOR FICA. É contra ele que a carga é auditável, e é
    #: dele que a chave foi derivada.
    assert gravada.unidade_texto == "Corsan"


def test_a_subida_liga_pelo_APELIDO(sessao, bites, um_tema):
    """As 15.019 menções da Corsan que chegam pela razão social."""
    ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            bites,
            [_linha("Companhia Riograndense de Saneamento (Corsan)", um_tema.nome)],
        ),
    )

    gravada = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    ).one()
    esperado = sessao.scalar(select(UnidadeNegocio.id).where(UnidadeNegocio.nome == "Corsan"))
    assert gravada.unidade_negocio_id == esperado
    assert gravada.unidade_texto == "Companhia Riograndense de Saneamento (Corsan)"


def test_a_subida_NAO_adivinha_o_bloco(sessao, bites, um_tema):
    """A linha ambígua entra, conta e fica SEM chave. Ela não é descartada: a
    menção é fato do mês, e o vínculo é enriquecimento."""
    ingerir_mencoes.ingerir(
        sessao, bites, _planilha(bites, [_linha("Águas do Pará", um_tema.nome)])
    )

    gravada = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    ).one()
    assert gravada.unidade_negocio_id is None
    assert gravada.unidade_texto == "Águas do Pará"


def test_a_conferencia_mostra_a_concessionaria_que_nao_liga_ANTES_de_gravar(
    sessao, bites, um_tema
):
    conteudo = _planilha(
        bites,
        [
            _linha("Corsan", um_tema.nome, 3),
            _linha("Águas do Pará", um_tema.nome, 4),
            _linha("Águas de Sinop", um_tema.nome, 5),
        ],
    )

    _previsao, _veiculos, _assuntos, unidades = ingerir_mencoes.conferir(
        sessao, bites, conteudo
    )

    assert unidades.ligadas == 1
    por_nome = {item.nome: item for item in unidades.nao_ligados}
    assert set(por_nome) == {"Águas do Pará", "Águas de Sinop"}
    assert len(por_nome["Águas do Pará"].opcoes) == 4
    assert por_nome["Águas de Sinop"].opcoes == ()

    #: E NÃO GRAVOU NADA — a conferência só lê.
    assert (
        sessao.scalars(
            select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
        ).all()
        == []
    )


def test_a_fonte_sem_coluna_de_concessionaria_nao_reclama(sessao, bites):
    """A `crm` não mapeia `unidade`, e a conferência dela não pode estourar.

    O `b""` é o ponto: se a função lesse o arquivo, ele seria recusado como
    planilha inválida. Foi assim que a primeira versão de `contagens_da_planilha`
    quebrou o teste equivalente dos assuntos — a saída antecipada passou a
    depender das DUAS colunas.
    """
    mapeamento = dict(bites.mapeamento_colunas)
    colunas = dict(mapeamento["colunas"])
    colunas.pop("unidade", None)
    bites.mapeamento_colunas = {**mapeamento, "colunas": colunas}
    sessao.flush()

    assert ingerir_mencoes.unidades_da_planilha(sessao, bites, b"") == {}
