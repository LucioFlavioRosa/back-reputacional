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
* que NUNCA se adivinhe bloco: um nome que cobre duas ou mais unidades do
  cadastro (a família) não pode resolver sozinho para nenhuma delas. Até
  19/10/2026 o exemplo real era "Águas do Pará" (quatro linhas); a
  consolidação daquele dia por pedido apagou o único caso real que existia,
  e os testes da família passaram a montar o próprio par de irmãs fictícias
  em vez de depender do cadastro de produção ter uma;
* que a semelhança não resolva: "Águas de São Francisco" e "Águas de São
  Francisco do Sul" são operações diferentes, em estados diferentes, e
  continuam resolvendo para IDS diferentes mesmo depois de a 0104 (por
  pedido) cadastrar a primeira — antes disso o teste prendia a primeira NÃO
  resolvendo nada;
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


@pytest.fixture
def duas_irmas(sessao) -> tuple[str, str]:
    """Um par FICTÍCIO que forma família, só para este teste.

    Até 19/10/2026 havia família de verdade no cadastro semeado ("Águas do
    Rio", "Águas do Pará", "Ambiental Ceará"); a consolidação daquele dia
    (por pedido) apagou as três — o cadastro real não tem mais nenhuma.
    Os testes que exercitam "nome de família não resolve sozinho" criam o
    próprio par aqui, na transação que o `rollback` da fixture `sessao`
    desfaz, em vez de depender de o cadastro de produção ter uma — ESTE é o
    acoplamento que fez `test_a_subida_NAO_adivinha_o_bloco` e companhia
    quebrarem na consolidação, e não deveria quebrar de novo na próxima."""
    sessao.add_all([
        UnidadeNegocio(nome="Irmã Testável 1", ordem=9000),
        UnidadeNegocio(nome="Irmã Testável 2", ordem=9001),
    ])
    sessao.flush()
    return "Irmã Testável 1", "Irmã Testável 2"


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
    "corsan" caberiam as duas, e `cadastro()` guardaria só a última. O número
    de nomes é o que o cadastro tiver no momento — a consolidação e as
    unidades novas de 19/10/2026 (migration `0104`) mudaram a contagem, e vão
    mudar de novo; o teste não fixa um número, só que nomes e chaves
    continuam 1 para 1.
    """
    nomes = [nome for (nome,) in sessao.execute(select(UnidadeNegocio.nome))]
    chaves = {normalizar(nome) for nome in nomes}
    assert len(chaves) == len(nomes), (
        "duas unidades do cadastro normalizam para a mesma chave: "
        f"{len(nomes)} nomes, {len(chaves)} chaves"
    )


def test_familia_tira_sufixo_numerico_ou_de_bloco():
    """A heurística em si, pura — sem tocar o banco.

    ELA SÓ EXISTE PARA A MENSAGEM, nunca para resolver — ver
    `unidade_da_mencao`. `familia()` é só a função: a chave que agrupa
    "Águas do Pará — Bloco C" e "Águas do Rio 4" com as irmãs delas.
    """
    assert unidade_da_mencao.familia("Águas do Pará — Bloco C") == unidade_da_mencao.familia(
        "Águas do Pará — Bloco A"
    )
    assert unidade_da_mencao.familia("Águas do Rio 1") == unidade_da_mencao.familia(
        "Águas do Rio 4"
    )
    #: NOME SEM SUFIXO não casa com nada — senão toda unidade seria irmã de
    #: toda unidade.
    assert unidade_da_mencao.familia("Corsan") != unidade_da_mencao.familia("Prolagos")


def test_a_familia_agrupa_as_irmas_e_deixa_as_outras_sozinhas(sessao, duas_irmas):
    """A heurística do sufixo, contra um par fictício (ver `duas_irmas`).

    Hoje, depois da consolidação de 19/10/2026, o cadastro de produção não
    tem mais nenhuma família real — por isso o par é fabricado aqui, e não
    lido do cadastro semeado."""
    cadastro = unidade_da_mencao.cadastro(sessao)
    chave = unidade_da_mencao.familia(duas_irmas[0])
    assert chave in cadastro.familias
    assert cadastro.familias[chave] == duas_irmas
    #: E "CORSAN" CONTINUA SOZINHA: unidade sem irmã não entra no mapa — só a
    #: pluralidade é opção a escolher (ver o comentário de `cadastro()`).
    assert unidade_da_mencao.familia("Corsan") not in cadastro.familias


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


def test_o_nome_de_familia_NAO_resolve(sessao, duas_irmas):
    """NUNCA SE ADIVINHA BLOCO, e é a regra que define o desenho.

    Até 19/10/2026 o exemplo real eram as 14.703 menções de "Águas do Rio",
    "Águas do Pará" e "Ambiental Ceará" — três nomes que cobriam várias
    linhas do cadastro e por isso nenhum deles resolvia sozinho. A
    consolidação daquele dia (por pedido) uniu cada trio/quarteto numa linha
    só, e os três passaram a resolver que nem qualquer outro nome exato —
    ver `test_o_nome_exato_do_cadastro_resolve`. O par fictício de
    `duas_irmas` mantém este teste exercitando a MESMA regra sem depender de
    o cadastro real ter uma ambiguidade disponível.

    Escolher um bloco por ordem, por volume ou por qualquer critério
    inventaria um dado que a planilha não tem — e ele sairia depois num
    relatório por concessionária como se fosse informação.
    """
    #: O NOME GENÉRICO, sem o número que distingue as duas — o mesmo gesto de
    #: quem escrevia "Águas do Pará" sem dizer qual bloco.
    assert unidade_da_mencao.cadastro(sessao).resolver("Irmã Testável") is None


@pytest.mark.parametrize(
    "nome", ["Águas do Rio", "Águas do Pará", "Ambiental Ceará"]
)
def test_os_antigos_nomes_de_familia_agora_resolvem(sessao, nome):
    """O outro lado da consolidação de 19/10/2026: o que não resolvia passou
    a resolver, porque virou o nome exato de uma linha só do cadastro."""
    assert unidade_da_mencao.cadastro(sessao).resolver(nome) is not None


def test_sao_francisco_nao_vira_sao_francisco_do_sul(sessao):
    """A SEMELHANÇA NÃO RESOLVE, e este é o par que prova por que.

    "Águas de São Francisco" e "Águas de São Francisco do Sul" são operações
    diferentes, em estados diferentes. Um passo por prefixo ou por
    similaridade juntaria as duas e o erro sairia num relatório por
    concessionária sem nada acusar.

    ATÉ 19/10/2026 só a segunda estava no cadastro (132 menções da primeira
    ficavam sem concessionária, de propósito — a 0104 cadastrou "Águas de São
    Francisco" por pedido). Agora as duas resolvem, e o que este teste
    protege virou "resolvem para IDS DIFERENTES", não "uma delas não resolve
    nada" — a semelhança continua não bastando para juntar as duas.
    """
    cadastro = unidade_da_mencao.cadastro(sessao)
    do_sul = cadastro.resolver("Águas de São Francisco do Sul")
    sem_sul = cadastro.resolver("Águas de São Francisco")
    assert do_sul is not None, "o cadastro tem São Francisco do Sul"
    assert sem_sul is not None, "a 0104 cadastrou Águas de São Francisco"
    assert do_sul != sem_sul, "as duas operações, de estados diferentes, colapsaram numa só"


def test_o_que_o_cadastro_nao_tem_nao_resolve(sessao):
    #: "ÁGUAS DE TREVO" NÃO É UMA CONCESSÃO DE VERDADE — escolhida assim de
    #: propósito depois de 19/10/2026, quando "Águas de Sinop" (o exemplo
    #: antigo deste teste) virou nome real do cadastro pela 0104.
    cadastro = unidade_da_mencao.cadastro(sessao)
    assert cadastro.resolver("Águas de Trevo") is None
    assert cadastro.resolver("") is None
    assert cadastro.resolver(None) is None


# -- reconhecer: o que a conferência diz antes de gravar -----------------------


def test_reconhecer_separa_o_AMBIGUO_do_DESCONHECIDO(sessao, duas_irmas):
    """DOIS PROBLEMAS, DOIS CONSERTOS, e é por isso que `opcoes` existe.

    "Irmã Testável" (ver `duas_irmas`) está escrito CERTO e mesmo assim não
    liga: o conserto é o fornecedor informar qual das duas. "Águas de Trevo"
    o cadastro não tem: o conserto é cadastrar a unidade. Um booleano "não
    reconhecido" mandaria as duas pessoas para o mesmo lugar errado.
    """
    reco = unidade_da_mencao.reconhecer(
        sessao,
        {"Corsan": 10, "Irmã Testável": 7, "Águas de Trevo": 3},
    )
    assert reco.ligadas == 10
    por_nome = {item.nome: item for item in reco.nao_ligados}
    assert set(por_nome) == {"Irmã Testável", "Águas de Trevo"}
    assert len(por_nome["Irmã Testável"].opcoes) == 2
    assert por_nome["Águas de Trevo"].opcoes == ()
    assert reco.nao_ligadas == 10


def test_reconhecer_conta_quem_veio_sem_concessionaria(sessao):
    reco = unidade_da_mencao.reconhecer(sessao, {"": 5, "Corsan": 1})
    assert reco.sem_unidade == 5
    assert reco.ligadas == 1
    #: VAZIO NÃO É "NÃO RECONHECIDO": ele não vira linha da lista, senão a
    #: pessoa procuraria na planilha um nome que não existe.
    assert reco.nao_ligados == ()


def test_reconhecer_ordena_por_volume(sessao):
    #: TRÊS NOMES SEM CONCESSÃO DE VERDADE — "Águas de Sinop"/"Sorriso"/"Jaru",
    #: os exemplos originais deste teste, viraram cadastro real pela 0104
    #: (19/10/2026), por pedido.
    reco = unidade_da_mencao.reconhecer(
        sessao, {"Águas de Trevo": 3, "Águas de Lontra": 50, "Águas de Bromélia": 9}
    )
    assert [item.nome for item in reco.nao_ligados] == [
        "Águas de Lontra",
        "Águas de Bromélia",
        "Águas de Trevo",
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


def test_a_subida_NAO_adivinha_o_bloco(sessao, bites, um_tema, duas_irmas):
    """A linha ambígua entra, conta e fica SEM chave. Ela não é descartada: a
    menção é fato do mês, e o vínculo é enriquecimento."""
    ingerir_mencoes.ingerir(
        sessao, bites, _planilha(bites, [_linha("Irmã Testável", um_tema.nome)])
    )

    gravada = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    ).one()
    assert gravada.unidade_negocio_id is None
    assert gravada.unidade_texto == "Irmã Testável"


def test_a_conferencia_mostra_a_concessionaria_que_nao_liga_ANTES_de_gravar(
    sessao, bites, um_tema, duas_irmas
):
    conteudo = _planilha(
        bites,
        [
            _linha("Corsan", um_tema.nome, 3),
            _linha("Irmã Testável", um_tema.nome, 4),
            _linha("Águas de Trevo", um_tema.nome, 5),
        ],
    )

    _previsao, _veiculos, _assuntos, unidades = ingerir_mencoes.conferir(
        sessao, bites, conteudo
    )

    assert unidades.ligadas == 1
    por_nome = {item.nome: item for item in unidades.nao_ligados}
    assert set(por_nome) == {"Irmã Testável", "Águas de Trevo"}
    assert len(por_nome["Irmã Testável"].opcoes) == 2
    assert por_nome["Águas de Trevo"].opcoes == ()

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
