"""A Bites informa o subtema (N3), e a coluna de atributo deixa de ser lida.

A DECISÃO DE NEGÓCIO. O cadastro de assuntos guarda a árvore e os riscos, então
a planilha só precisa informar o N3: 104 temas ativos, nenhum sem macro_tema
(N2), nenhum macro_tema sem bloco_tema (N1), e 100 das 104 ligações para risco
já cadastradas. O N1 que o fornecedor carimba passa a ser redundante — e pior,
porque pode DISCORDAR do N1 derivado, deixando a mesma menção com dois.

O QUE ESTES TESTES PROTEGEM:

* a coluna `Atributo` é ignorada, esteja ela no arquivo ou não — o fornecedor
  vai parar de mandá-la, e nenhuma das duas formas pode exigir aviso;
* `Categoria` ausente não derruba a subida: a primeira planilha sobe com ela
  VAZIA de propósito, e no dia em que o fornecedor remover a coluna em vez de
  limpá-la a subida continua passando;
* a aba não é mais exigida pelo nome. O cadastro pedia `Posts`, o arquivo real
  chama `Planilha1`, e a subida era recusada antes de ler uma linha.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte
from app.casos_de_uso import ingerir_mencoes
from app.dominio.ingestao_score import Mapeamento
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


def _planilha(nome_da_aba: str, cabecalho: list[str], linhas: list[list]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = nome_da_aba
    #: UMA LINHA DE TÍTULO ANTES DO CABEÇALHO, como o arquivo real: o cabeçalho
    #: da Bites vem na linha 2.
    aba.append(["Relatório mensal", None])
    aba.append(cabecalho)
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


#: O FORMATO ANTIGO, como o fornecedor mandava: com `Atributo` e com
#: `Categoria`. Nenhuma das duas é lida hoje — `Atributo` por decisão, e
#: `Categoria` desde que o tema passou a vir de `N3` (`0079`).
COMPLETO = [
    "Data",
    "Cargo",
    "Atributo",
    "Sentimento",
    "Unidades/Empresas",
    "Categoria",
    "Engajamento",
]
#: O CABEÇALHO REAL do arquivo de 01–09/2026, com as colunas que a `0070`
#: passou a ler.
COM_AS_NOVAS = [
    "Data",
    "Autor",
    "Cargo",
    "Rede Social",
    "Estado",
    "Sentimento",
    "Unidades/Empresas",
    "Categoria",
    "Link",
    "Texto",
    "Engajamento",
]
#: O CABEÇALHO DA PLANILHA CONSOLIDADA (Jan–Set/2026), em que a Bites passou a
#: entregar os três níveis explícitos. Conferido contra o cadastro: N1 7/7,
#: N2 40/40 e N3 92/92 casam, e as três colunas concordam entre si.
CONSOLIDADA = [
    "Data",
    "Autor",
    "Cargo",
    "Rede Social",
    "Cidade",
    "Estado",
    "Abrangência",
    "Atributo",
    "Sentimento",
    "Unidades/Empresas",
    "Categoria",
    "Link",
    "Texto",
    "Engajamento",
    "Holding",
    "Seguidores",
    "N1",
    "N2",
    "N3",
]
#: A PLANILHA MENOS O ATRIBUTO, e com a coluna de tema que o cadastro lê hoje
#: (`N3`, desde a `0079`). Trazia `Categoria` — que deixou de ser coluna de
#: tema —, e aí o cenário dizia "menos o Atributo" enquanto era "menos o
#: Atributo E menos o tema". Duas ausências num teste que fala de uma.
SEM_ATRIBUTO = ["Data", "Cargo", "Sentimento", "Unidades/Empresas", "N3", "Engajamento"]
#: E A PLANILHA SEM COLUNA DE TEMA NENHUMA: `tema` é opcional de propósito, e o
#: fornecedor pode parar de mandá-la.
SEM_TEMA = ["Data", "Cargo", "Sentimento", "Unidades/Empresas", "Engajamento"]


def test_o_cadastro_da_bites_nao_le_mais_o_atributo(bites):
    mapeamento = Mapeamento.de_json(bites.mapeamento_colunas)

    assert "atributo" not in mapeamento.colunas
    #: E A ABA NÃO É MAIS EXIGIDA PELO NOME.
    assert mapeamento.aba is None
    assert "Atributo" not in mapeamento.colunas_necessarias
    assert "Categoria" not in mapeamento.colunas_necessarias


def test_a_planilha_COM_a_coluna_atributo_sobe_e_ignora_a_coluna(sessao, bites):
    #: O fornecedor ainda vai mandar a coluna por um tempo. Ela não pode
    #: quebrar a subida nem virar dado.
    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Planilha1",
            COMPLETO,
            [[date(2026, 8, 3), "Vereador", "Governança", "Positivo", "Corsan", "", 10]],
        ),
    )

    assert resumo[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    )
    #: IGNORADA, e não gravada: o N1 passa a vir do cadastro, pelo N3.
    assert gravada.atributo is None


def test_a_planilha_SEM_a_coluna_atributo_sobe_igual(sessao, bites):
    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Planilha1",
            SEM_ATRIBUTO,
            [[date(2026, 8, 3), "Vereador", "Positivo", "Corsan", "", 10]],
        ),
    )

    assert resumo[0].ingeridas == 1


def test_a_planilha_SEM_A_COLUNA_DE_TEMA_sobe(sessao, bites):
    #: A primeira sobe com ela vazia; depois o fornecedor pode removê-la. Nem
    #: uma nem outra forma pode exigir mudança no cadastro da fonte — e a
    #: menção fica SEM ASSUNTO, que é o retrato honesto do arquivo.
    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Planilha1",
            SEM_TEMA,
            [[date(2026, 8, 3), "Vereador", "Positivo", "Corsan", 10]],
        ),
    )

    assert resumo[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    )
    assert gravada.tema_texto is None


def test_a_aba_pode_ter_QUALQUER_NOME(sessao, bites):
    #: O arquivo real chama a aba de `Planilha1`, o nome que o Excel dá por
    #: padrão. O cadastro pedia `Posts` e a subida era recusada antes de ler uma
    #: linha — a mensagem certa para um arquivo errado, e a errada para um
    #: arquivo CERTO.
    for nome in ("Planilha1", "Posts", "Sheet1", "Dados de setembro"):
        resumo = ingerir_mencoes.ingerir(
            sessao,
            bites,
            _planilha(
                nome,
                SEM_ATRIBUTO,
                [[date(2026, 8, 3), "Vereador", "Positivo", "Corsan", "", 10]],
            ),
        )
        assert resumo[0].ingeridas == 1, nome


def test_a_coluna_que_FALTA_DE_VERDADE_ainda_e_recusada(sessao, bites):
    #: O que a decisão NÃO pode custar: um arquivo sem a coluna de sentimento
    #: continua sendo recusado com o nome da coluna. Tornar tudo opcional
    #: transformaria arquivo errado em mês vazio.
    from app.dominio.erros import RegraViolada

    with pytest.raises(RegraViolada, match="Sentimento"):
        ingerir_mencoes.ingerir(
            sessao,
            bites,
            _planilha(
                "Planilha1",
                ["Data", "Cargo", "Unidades/Empresas", "Engajamento"],
                [[date(2026, 8, 3), "Vereador", "Corsan", 10]],
            ),
        )


# -- a 0070: link, texto, autor e uf ----------------------------------------------


def test_a_bites_grava_LINK_TEXTO_AUTOR_E_UF(sessao, bites):
    """O que a lente de redes sociais precisa para ter o que mostrar.

    O BLOCO "MENÇÕES DO MÊS" da lente Sociedade digital lista as linhas com
    Texto, Link, Autor, Perfil e Engajamento — e só mostra linha QUE TEM TEXTO.
    Sem estas colunas mapeadas, as 2.886 menções entraram com tudo nulo e a
    tabela ficava vazia: a nota aparecia, e nenhuma menção para clicar.
    """
    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Planilha1",
            COM_AS_NOVAS,
            [
                [
                    date(2026, 8, 3),
                    "Alô Gravataí",
                    "Comunicador",
                    "Instagram",
                    "RS",
                    "Negativo",
                    "Corsan",
                    "",
                    "https://www.instagram.com/p/ABC123/",
                    "SEM ÁGUA | Moradores de Gravataí relatam falta",
                    42,
                ]
            ],
        ),
    )

    assert resumo[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    )
    assert gravada.link == "https://www.instagram.com/p/ABC123/"
    assert gravada.titulo_texto == "SEM ÁGUA | Moradores de Gravataí relatam falta"
    assert gravada.autor == "Alô Gravataí"
    #: A UF ENTRA POR EXTENSO. A planilha manda a sigla, e `mencao.uf` guarda o
    #: nome — decisão de 09/10/2026, porque é o que o filtro mostra.
    assert gravada.uf == "Rio Grande do Sul"


def test_as_colunas_novas_sao_TODAS_OPCIONAIS(sessao, bites):
    """A lição da `0064`: coluna que o fornecedor pode parar de mandar não pode
    derrubar a subida inteira."""
    mapeamento = Mapeamento.de_json(bites.mapeamento_colunas)
    for coluna in ("Link", "Texto", "Autor", "Estado"):
        assert coluna not in mapeamento.colunas_necessarias

    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Planilha1",
            SEM_ATRIBUTO,
            [[date(2026, 8, 3), "Vereador", "Positivo", "Corsan", "", 10]],
        ),
    )

    assert resumo[0].ingeridas == 1


def test_quem_fala_na_bites_e_o_AUTOR_e_nasce_como_PERFIL_DE_REDE(bites):
    """`mencao.veiculo` guarda QUEM FALOU, e na Bites quem fala é o autor.

    A POSIÇÃO MUDOU, e vale registrar por quê. A objeção original era mapear
    `Rede Social`: "Instagram" como instituição seria errado, e viraria
    candidato à lista de imprensa econômica da lente Mercado. `Autor` é outra
    coisa — é quem postou, que é exatamente o que a coluna significa no
    clipping da Clipei (lá, o veículo que publicou).

    E ELE NÃO NASCE COMO VEÍCULO: `quem_fala='perfil_rede'` faz a ingestão
    procurar e criar em `tipo='perfil_rede'`, na categoria "Formadores de
    Opinião". A lista de investidores filtra `tipo='veiculo'`, então o perfil
    fica fora dela por construção.
    """
    mapeamento = Mapeamento.de_json(bites.mapeamento_colunas)

    assert mapeamento.colunas["veiculo"] == "Autor"
    assert mapeamento.quem_fala == "perfil_rede"
    #: OPCIONAL como as outras: um mês sem a coluna `Autor` não derruba a
    #: subida inteira.
    assert "Autor" not in mapeamento.colunas_necessarias


def test_a_REDE_SOCIAL_continua_fora_do_veiculo(bites):
    """O que a decisão NÃO pode custar: "Instagram" no Cadastro compartilhado.

    A coluna `Rede Social` vem preenchida em 100% das 2.886 linhas, e é
    tentador usá-la — mas ela é a plataforma, não quem falou. Se um dia alguém
    a mapear para `veiculo`, oito nomes de rede entram no cadastro como se
    fossem quem fala.
    """
    colunas = Mapeamento.de_json(bites.mapeamento_colunas).colunas

    assert "Rede Social" not in colunas.values()


def test_a_CLIPEI_continua_cadastrando_veiculo(sessao):
    """O padrão protege as fontes antigas.

    `quem_fala` ausente vale `veiculo`, e é o que mantém a Clipei, as duas da
    Approach e a interna exatamente como estavam — 25.457 menções já ligadas a
    veículos do cadastro não podem mudar de significado por causa da Bites.
    """
    for codigo in ("clipei", "clipei_investidores", "approach_sl", "approach_cm"):
        fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
        assert Mapeamento.de_json(fonte.mapeamento_colunas).quem_fala == "veiculo", codigo


def test_o_subtema_vem_da_coluna_N3(bites):
    """A `0079`, e o defeito que ela conserta.

    A `Categoria` da planilha antiga era o que havia; na consolidada existe uma
    coluna `N3` que é a taxonomia do cadastro. E `Categoria` não serve mais como
    chave: 52 dos seus valores trazem VÁRIOS assuntos numa célula
    ("Abastecimento, Agência de Regulação, Proteção ambiental"), e a ingestão
    procuraria no cadastro um assunto com esse nome inteiro.
    """
    mapeamento = Mapeamento.de_json(bites.mapeamento_colunas)

    assert mapeamento.colunas["tema"] == "N3"
    #: E A COLUNA ANTIGA NÃO É MAIS LIDA por campo nenhum.
    assert "Categoria" not in mapeamento.colunas.values()
    #: (`Categoria` também não está nas necessárias — mas isso vale desde a
    #: `0069`, que pôs `tema` em `colunas_opcionais`, e passaria com esta
    #: migration revertida. Fica como registro, não como guarda. Achado de
    #: revisão: a asserção parecia provar a troca e não provava.)
    assert "Categoria" not in mapeamento.colunas_necessarias


def test_a_planilha_CONSOLIDADA_liga_o_assunto_no_cadastro(sessao, bites):
    """O caminho inteiro: célula N3 -> `tema_id` do cadastro.

    Na planilha real são 92 valores de N3, e os 92 casam com temas ativos. Sem a
    `0079` cada uma dessas linhas subiria com `tema_id` nulo — e nenhum recorte
    por N1, N2 ou N3 a encontraria.

    O TEMA VEM DO BANCO, e não por nome fixo: o banco de teste nasce das
    migrations, e os 104 temas da taxonomia entraram por importação de planilha.
    """
    from app.banco.tabelas_catalogo import Tema

    #: `order_by` junto do `limit`: sem ele a linha devolvida é indeterminada no
    #: Postgres, e o teste fica intermitente no dia em que o semeador mudar.
    esperado = sessao.scalar(
        select(Tema)
        .where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None))
        .order_by(Tema.id)
        .limit(1)
    )
    assert esperado is not None, "o cadastro de teste precisa de um tema ativo"

    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Consolidado 2026",
            CONSOLIDADA,
            [
                [
                    date(2026, 8, 4), "fulano zz90", "Vereador", "Facebook", "Canoas",
                    "RS", "Municipal", "Governança", "Negativo", "Corsan",
                    "Abastecimento, Agência de Regulação", "https://x/1", "texto",
                    3, 1, 10, "Eficiência Operacional e Qualidade",
                    "Abastecimento de água", esperado.nome,
                ]
            ],
        ),
    )

    assert resumo[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    )
    assert gravada.tema_id == esperado.id
    #: O RÓTULO GRAVADO É O DO N3, e não a célula de `Categoria` com dois
    #: assuntos — que é justamente o que a ingestão lia antes.
    assert gravada.tema_texto == esperado.nome
    #: E O `Atributo` SEGUE IGNORADO: nesta planilha ele contradiz o N1 em 1.418
    #: das 2.842 linhas, e o N1 vem do cadastro pelo N3.
    assert gravada.atributo is None


def test_a_CATEGORIA_PREENCHIDA_nao_liga_mais_assunto(sessao, bites):
    """O contrapeso da `0079`: a coluna antiga, cheia, não vale mais nada.

    ACHADO DE REVISÃO. Os testes provavam que o mapeamento diz `N3`; nenhum
    provava o caminho inteiro com `Categoria` PREENCHIDA com nome de tema de
    verdade. Sem isto, reapontar o cadastro para `Categoria` por engano não faz
    teste fim-a-fim nenhum reclamar — e o engano é silencioso: as menções entram,
    a nota sai, e o recorte por assunto fica vazio.
    """
    from app.banco.tabelas_catalogo import Tema

    tema = sessao.scalar(
        select(Tema)
        .where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None))
        .order_by(Tema.id)
        .limit(1)
    )
    assert tema is not None

    #: `SEM_TEMA` + `Categoria` no fim: a planilha NÃO tem `N3`, e a `Categoria`
    #: traz o nome de um tema ativo — o cenário em que a leitura antiga ligaria.
    resumo = ingerir_mencoes.ingerir(
        sessao,
        bites,
        _planilha(
            "Planilha1",
            [*SEM_TEMA, "Categoria"],
            [[date(2026, 8, 3), "Vereador", "Positivo", "Corsan", 10, tema.nome]],
        ),
    )

    assert resumo[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 8, 1))
    )
    #: A MENÇÃO ENTRA E FICA SEM ASSUNTO. É o que a `0079` muda: só `N3` liga.
    assert gravada.tema_texto is None
    assert gravada.tema_id is None
