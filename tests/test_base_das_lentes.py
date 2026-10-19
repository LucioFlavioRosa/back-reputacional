"""A Base de dados das lentes: as menções na fonte, para consulta."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.base_das_lentes import (
    EdicaoDoJornalista,
    editar_jornalista,
    listar_mencoes,
    opcoes_da_base,
)
from app.banco.tabelas_catalogo import BlocoTema
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor
from app.dominio.causa_da_lente import DIMENSOES_POR_LENTE, nomeia_o_diretorio
from app.dominio.erros import NaoAutorizado, NaoEncontrado, RegraViolada
from app.dominio.identidade import Papel
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


@dataclass
class _QuemOlha:
    ve_diretorio: bool = True
    #: Só usado por quem edita (`editar_jornalista`) — a leitura nem olha.
    papel: Papel | None = field(
        default_factory=lambda: Papel(
            codigo="score_edicao", nome="Score · edição", pode_editar_tudo=True
        )
    )


@pytest.fixture
def imprensa(sessao):
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    linhas = [
        (
            date(2026, 8, 3), "Folha de S.Paulo", "muito_relevante", "neg",
            "Água turva em São Gonçalo", "Ana Lima",
        ),
        (
            date(2026, 8, 10), "Valor Econômico", "relevante", "pos",
            "Aegea capta R$ 2 bi", "Bruno Reis",
        ),
        (
            date(2026, 8, 20), "G1", "muito_relevante", "neu",
            "Obras de esgoto avançam", "Carla Dias",
        ),
        (
            date(2026, 7, 15), "O Globo", "relevante", "neg",
            "Falta d'água no Rio", "Dani Souza",
        ),
    ]
    for data, veiculo, tier, sentimento, titulo, autor in linhas:
        sessao.add(
            Mencao(
                fonte_id=clipei.id,
                mes=data.replace(day=1),
                data=data,
                veiculo=veiculo,
                tier=tier,
                sentimento=sentimento,
                titulo_texto=titulo,
                autor=autor,
                link=f"https://exemplo.com/{veiculo}",
            )
        )
    sessao.flush()
    return linhas


def _listar(sessao, ve_diretorio=True, codigo="imprensa", **params):
    padrao = dict(
        de=date(2026, 7, 1), ate=date(2026, 8, 31), q=None, fonte=None, sentimento=None,
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        pagina=1, tamanho=50, ordenacao="-data",
    )
    padrao.update(params)
    return listar_mencoes(
        sessao=sessao, usuario=_QuemOlha(ve_diretorio), codigo=codigo, **padrao
    )


def _opcoes(sessao, ve_diretorio=True, codigo="imprensa"):
    return opcoes_da_base(
        sessao=sessao,
        usuario=_QuemOlha(ve_diretorio),
        codigo=codigo,
        de=date(2026, 7, 1),
        ate=date(2026, 8, 31),
    )


def test_lista_o_periodo_da_mais_recente_para_a_mais_antiga(sessao, imprensa):
    pagina = _listar(sessao)
    assert pagina.total == 4
    assert [m.veiculo for m in pagina.itens] == [
        "G1", "Valor Econômico", "Folha de S.Paulo", "O Globo",
    ]
    assert pagina.itens[0].link == "https://exemplo.com/G1"
    assert pagina.itens[0].fonte == "Clipei"


def test_filtra_por_campo_e_por_periodo(sessao, imprensa):
    assert _listar(sessao, sentimento="neg").total == 2
    assert _listar(sessao, tier="muito_relevante").total == 2
    assert _listar(sessao, veiculo="Valor Econômico").total == 1
    assert _listar(sessao, de=date(2026, 8, 1)).total == 3


def test_a_busca_livre_ignora_acento_e_maiuscula(sessao, imprensa):
    assert [m.veiculo for m in _listar(sessao, q="AGUA").itens] == ["Folha de S.Paulo", "O Globo"]
    assert _listar(sessao, q="economico").total == 1  # acha "Valor Econômico"
    assert _listar(sessao, q="sao goncalo").total == 1


def test_pagina_e_ordena(sessao, imprensa):
    primeira = _listar(sessao, tamanho=3)
    segunda = _listar(sessao, tamanho=3, pagina=2)
    assert len(primeira.itens) == 3 and len(segunda.itens) == 1
    assert [m.veiculo for m in _listar(sessao, ordenacao="veiculo").itens][0] == "Folha de S.Paulo"
    with pytest.raises(RegraViolada):
        _listar(sessao, ordenacao="senha")


def test_o_jornalista_so_para_quem_ve_o_diretorio(sessao, imprensa):
    assert _listar(sessao, ve_diretorio=True).itens[0].autor == "Carla Dias"
    sem = _listar(sessao, ve_diretorio=False)
    assert all(m.autor is None for m in sem.itens)
    # Nem filtrar por ele: senão a contagem revelaria o nome.
    assert _listar(sessao, ve_diretorio=False, autor="Carla Dias").total == 4
    opcoes = opcoes_da_base(
        sessao=sessao, usuario=_QuemOlha(False), codigo="imprensa", de=None, ate=None
    )
    assert opcoes.autores == []


def test_as_opcoes_do_periodo(sessao, imprensa):
    opcoes = opcoes_da_base(
        sessao=sessao,
        usuario=_QuemOlha(),
        codigo="imprensa",
        de=date(2026, 8, 1),
        ate=date(2026, 8, 31),
    )
    assert set(opcoes.veiculos) >= {"Folha de S.Paulo", "Valor Econômico", "G1"}
    assert "O Globo" not in opcoes.veiculos
    assert set(opcoes.sentimentos) >= {"neg", "pos", "neu"}


def test_institucional_nao_tem_base_de_mencoes(sessao):
    with pytest.raises(NaoEncontrado):
        listar_mencoes(sessao=sessao, usuario=_QuemOlha(), codigo="institucional")


# -- QUEM NOMEIA GENTE DE FORA, E QUEM NÃO ------------------------------------
#
# A regra do autor escondido vale POR ORIGEM DO DADO, e não por lente favorita:
# na Imprensa o `autor` é o jornalista do CADASTRO de terceiros, que
# `ve_diretorio` guarda; nas lentes de rede é o perfil que veio DENTRO da
# menção — o `Publicador` que a Approach manda na própria linha da planilha, o
# `Autor` que a Bites manda. Esse segundo é aberto, e já era: o cartão "Onde
# está a causa" da Sociedade digital declara `Dimensao("autor", "Autor",
# "autor")` sem `nomeia_o_diretorio`, e o indicador "Autor mais negativo" o
# mostra a todo mundo.
#
# A PERGUNTA MORAVA EM DOIS LUGARES: o cartão perguntava à declaração
# (`causa_da_lente`), e esta Base comparava `codigo == "imprensa"` em três
# pontos. Marcar uma lente nova como quem nomeia o diretório tiraria a aba do
# cartão e deixaria esta Base publicando a coluna e oferecendo o filtro — sem
# erro nenhum. Agora as duas leem a mesma declaração, e é isto que os dois
# testes abaixo prendem.


@pytest.fixture
def clientes(sessao):
    """Duas menções de Community Management, com o perfil que comentou cada uma.

    DUAS, E DE AUTORES DIFERENTES: com uma só, "o filtro de autor funcionou" e
    "o filtro foi ignorado porque o autor está escondido" devolvem o mesmo
    total, e a asserção não distingue os dois casos — que é exatamente o que
    estes testes existem para distinguir.
    """
    cm = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "approach_cm")).one()
    for dia, autor, texto in (
        (4, "branca_medeiros15", "Vocês deveriam ter vergonha"),
        (11, "fernandescaggy", "Terceiro dia sem água aqui"),
    ):
        sessao.add(
            Mencao(
                fonte_id=cm.id,
                mes=date(2026, 8, 1),
                data=date(2026, 8, dia),
                sentimento="neg",
                titulo_texto=texto,
                autor=autor,
                teor="Reclamação",
                engajamento=2,
            )
        )
    sessao.flush()


def test_o_perfil_que_comentou_aparece_sem_o_diretorio(sessao, clientes):
    """O `Publicador` da Approach é dado da menção, não cadastro de terceiros.

    SE ESTE TESTE QUEBRAR, houve uma decisão de produto, não um ajuste: alguém
    passou a tratar o perfil de quem comenta num post da Aegea como o cadastro
    de jornalistas. É a mesma pergunta de
    `test_o_jornalista_so_para_quem_ve_o_diretorio`, com a resposta oposta — e
    a diferença é a origem do dado.
    """
    pagina = _listar(sessao, ve_diretorio=False, codigo="clientes")

    assert [m.autor for m in pagina.itens] == ["fernandescaggy", "branca_medeiros15"]
    #: E O FILTRO FUNCIONA, porque não há nome a proteger aqui: uma das duas.
    assert _listar(
        sessao, ve_diretorio=False, codigo="clientes", autor="branca_medeiros15"
    ).total == 1
    assert "branca_medeiros15" in _opcoes(sessao, ve_diretorio=False, codigo="clientes").autores


def test_a_base_segue_a_declaracao_e_nao_o_nome_da_lente(sessao, clientes, monkeypatch):
    """A PROVA DA DERIVAÇÃO: marcar a lente na declaração esconde o autor aqui.

    Enquanto esta Base comparava `codigo == "imprensa"`, marcar uma lente nova
    com `nomeia_o_diretorio=True` tirava a aba do cartão "Onde está a causa" e
    deixava a coluna e o filtro de autor publicando o nome — sem erro nenhum,
    porque as duas regras eram cópias. Este teste é o que torna isso impossível:
    ele muda SÓ a declaração e exige que a Base obedeça.
    """
    from app.dominio import causa_da_lente

    monkeypatch.setitem(
        causa_da_lente.DIMENSOES_POR_LENTE,
        "clientes",
        (
            *causa_da_lente.DIMENSOES_POR_LENTE["clientes"],
            causa_da_lente.Dimensao("autor", "Autor", "autor", nomeia_o_diretorio=True),
        ),
    )

    pagina = _listar(sessao, ve_diretorio=False, codigo="clientes")
    assert all(m.autor is None for m in pagina.itens)
    #: E O FILTRO É IGNORADO — senão a contagem revelaria o nome escondido.
    assert _listar(
        sessao, ve_diretorio=False, codigo="clientes", autor="branca_medeiros15"
    ).total == 2
    assert _opcoes(sessao, ve_diretorio=False, codigo="clientes").autores == []
    #: Quem tem a permissão continua vendo os dois.
    assert _listar(sessao, ve_diretorio=True, codigo="clientes").itens[0].autor == "fernandescaggy"


def test_a_base_e_o_cartao_perguntam_a_mesma_coisa():
    """As duas regras do autor saem da MESMA declaração.

    `nomeia_o_diretorio` é a função que `base_das_lentes` passou a chamar nos
    três pontos onde havia `codigo == "imprensa"`. Este teste prende o estado
    de hoje — só a Imprensa — e, mais que isso, prende que a resposta vem da
    declaração por dimensão, que é onde a política está escrita.
    """
    nomeiam = sorted(
        codigo for codigo in DIMENSOES_POR_LENTE if nomeia_o_diretorio(codigo)
    )

    assert nomeiam == ["imprensa"], (
        f"mudou quem nomeia o diretório: hoje {nomeiam}. Se foi de propósito, a "
        "Base das Lentes já acompanha — confira se a lente nova tem mesmo autor "
        "de CADASTRO, e não o perfil que vem dentro da menção."
    )
    #: E A LENTE DE CLIENTES NÃO TEM ABA DE AUTOR NENHUMA: o cartão dela oferece
    #: tema, subtema, concessionária e UF. O perfil aparece na Base, não ali.
    assert all(
        dimensao.campo != "autor" for dimensao in DIMENSOES_POR_LENTE["clientes"]
    )


# =============================================================================
# `editar_jornalista` — vincular o autor da menção a um interlocutor cadastrado
# =============================================================================


@pytest.fixture
def materia_do_globo(sessao):
    """Uma menção da Imprensa já ligada ao veículo "O Globo" no cadastro, mais
    um interlocutor cadastrado nele e outro numa instituição diferente."""
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    globo = Instituicao(nome="O Globo", nome_normalizado=normalizar("O Globo"), tipo="veiculo")
    folha = Instituicao(
        nome="Folha de S.Paulo", nome_normalizado=normalizar("Folha de S.Paulo"), tipo="veiculo"
    )
    sessao.add_all([globo, folha])
    sessao.flush()

    jornalista_do_globo = Interlocutor(
        nome="Dani Souza", nome_normalizado=normalizar("Dani Souza"), instituicao_id=globo.id
    )
    jornalista_da_folha = Interlocutor(
        nome="Ana Lima", nome_normalizado=normalizar("Ana Lima"), instituicao_id=folha.id
    )
    sessao.add_all([jornalista_do_globo, jornalista_da_folha])

    materia = Mencao(
        fonte_id=clipei.id,
        mes=date(2026, 8, 1),
        data=date(2026, 8, 5),
        veiculo="O Globo",
        instituicao_id=globo.id,
        tier="relevante",
        sentimento="neg",
        titulo_texto="Falta d'água no Rio",
    )
    sessao.add(materia)
    sessao.flush()
    return materia, jornalista_do_globo, jornalista_da_folha


def _editar(sessao, mencao_id, interlocutor_id, *, usuario=None):
    return editar_jornalista(
        sessao=sessao,
        usuario=usuario or _QuemOlha(),
        id=mencao_id,
        edicao=EdicaoDoJornalista(interlocutor_id=interlocutor_id),
    )


def test_vincula_um_interlocutor_da_mesma_instituicao(sessao, materia_do_globo):
    materia, jornalista_do_globo, _ = materia_do_globo
    resultado = _editar(sessao, materia.id, jornalista_do_globo.id)
    assert resultado.autor == "Dani Souza"
    assert materia.autor == "Dani Souza"


def test_recusa_interlocutor_de_outra_instituicao(sessao, materia_do_globo):
    materia, _, jornalista_da_folha = materia_do_globo
    with pytest.raises(RegraViolada):
        _editar(sessao, materia.id, jornalista_da_folha.id)
    assert materia.autor is None


def test_recusa_vincular_sem_veiculo_no_cadastro(sessao, materia_do_globo):
    """Menção sem `instituicao_id`: não há instituição a conferir, então não
    há como a regra "mesmo veículo" valer — a edição é recusada, não ignorada."""
    materia, jornalista_do_globo, _ = materia_do_globo
    materia.instituicao_id = None
    sessao.flush()
    with pytest.raises(RegraViolada):
        _editar(sessao, materia.id, jornalista_do_globo.id)


def test_desvincula_passando_none(sessao, materia_do_globo):
    materia, jornalista_do_globo, _ = materia_do_globo
    _editar(sessao, materia.id, jornalista_do_globo.id)
    resultado = _editar(sessao, materia.id, None)
    assert resultado.autor is None
    assert materia.autor is None


def test_menção_e_interlocutor_inexistentes_sao_recusados(sessao, materia_do_globo):
    materia, jornalista_do_globo, _ = materia_do_globo
    with pytest.raises(NaoEncontrado):
        _editar(sessao, uuid.uuid4(), jornalista_do_globo.id)
    with pytest.raises(NaoEncontrado):
        _editar(sessao, materia.id, uuid.uuid4())


def test_so_quem_ve_o_diretorio_edita(sessao, materia_do_globo):
    materia, jornalista_do_globo, _ = materia_do_globo
    with pytest.raises(NaoAutorizado):
        _editar(sessao, materia.id, jornalista_do_globo.id, usuario=_QuemOlha(ve_diretorio=False))


def test_so_quem_pode_editar_tudo_edita(sessao, materia_do_globo):
    materia, jornalista_do_globo, _ = materia_do_globo
    leitor = _QuemOlha(
        papel=Papel(codigo="score_leitura", nome="Score · leitura", ve_diretorio=True)
    )
    with pytest.raises(NaoAutorizado):
        _editar(sessao, materia.id, jornalista_do_globo.id, usuario=leitor)
    sem_papel = _QuemOlha(papel=None)
    with pytest.raises(NaoAutorizado):
        _editar(sessao, materia.id, jornalista_do_globo.id, usuario=sem_papel)


def test_a_edicao_fica_na_trilha_de_auditoria(sessao, materia_do_globo):
    """O gatilho roda junto do UPDATE (`flush`), não precisa de commit — e o
    teste não pode commitar: quebraria o rollback de isolamento da fixture
    `sessao`."""
    materia, jornalista_do_globo, _ = materia_do_globo
    _editar(sessao, materia.id, jornalista_do_globo.id)

    linha = sessao.execute(
        text(
            "select campo, valor_anterior, valor_novo from mencao_auditoria "
            "where mencao_id = :id order by id desc limit 1"
        ),
        {"id": str(materia.id)},
    ).one()
    assert linha.campo == "autor"
    assert linha.valor_anterior is None
    assert linha.valor_novo == "Dani Souza"


# -- o rótulo do pilar depois da 0098 -----------------------------------------


def test_o_pilar_da_linha_vem_da_coluna_quando_nao_ha_tema_do_cadastro(sessao) -> None:
    """A coluna "Pilar (N1)" mostra o PILAR, e não a Subcategoria do fornecedor.

    O QUE ESTAVA ERRADO. O rótulo era `n1 or m.tema_texto`: sem tema do cadastro
    para derivar, caía no texto do fornecedor — que na Clipei é a `Subcategoria`,
    um ASSUNTO, exibido numa coluna chamada "Pilar (N1)". Eram 73.014 linhas
    (71% da base da Clipei) lendo "Falta de água" como se fosse um dos 7
    pilares.

    Com a `0098` a menção tem o pilar de verdade em `mencao.bloco_tema_id`, e é
    ele que aparece. O texto do fornecedor fica como último recurso, para a
    linha que não tem nível nenhum.
    """
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    pilar = sessao.execute(
        select(BlocoTema.id, BlocoTema.nome)
        .where(BlocoTema.ativo.is_(True))
        .order_by(BlocoTema.id)
        .limit(1)
    ).one()
    sessao.add(
        Mencao(
            fonte_id=clipei.id,
            mes=date(2026, 8, 1),
            data=date(2026, 8, 5),
            sentimento="neg",
            titulo_texto="Ligada só pelo pilar",
            #: O QUE A CLIPEI MANDA: um assunto, não o nome de um pilar.
            tema_texto="Falta de água",
            bloco_tema_id=pilar.id,
        )
    )
    sessao.flush()

    achada = next(
        item
        for item in _listar(sessao).itens
        if item.titulo == "Ligada só pelo pilar"
    )
    assert achada.tema_n1 == pilar.nome, (
        f"a coluna Pilar mostrou {achada.tema_n1!r}; devia mostrar o pilar "
        f"gravado ({pilar.nome!r}), e não a Subcategoria do fornecedor."
    )


def test_o_pilar_derivado_continua_vencendo(sessao, imprensa) -> None:
    """Onde o rótulo já tinha valor, ele NÃO muda — a mudança só preenche vazio.

    As menções do fixture não têm `tema_id` nem `bloco_tema_id`, então caem no
    último recurso e seguem mostrando o texto do fornecedor (nulo aqui). O que
    este teste prende é que a ordem das três tentativas não inverteu: nenhuma
    linha que mostrava um valor passou a mostrar outro.
    """
    for item in _listar(sessao).itens:
        assert item.tema_n1 == item.tema or item.tema_n1 is None, (
            f"o rótulo do pilar mudou para {item.tema_n1!r} numa linha sem "
            "nível nenhum; o último recurso tem de seguir sendo o tema do "
            "fornecedor."
        )

# -- a busca livre e o nome do cadastro ----------------------------------------
#
# ACHADO DA REVISÃO DO CODEX (18/10/2026). A `0099` fez a COLUNA da Base mostrar
# `CONCESSIONARIA` — o nome do cadastro, com o texto do fornecedor como reserva.
# A busca livre ficou procurando só `Mencao.unidade_texto`. Resultado: a pessoa
# lê "Holding / corporativo" na tela, digita exatamente isso no campo de busca,
# e recebe zero — porque o texto gravado é "Aegea Saneamento e Participações
# S/A". Procurar pelo que a tela NÃO mostra é o pior tipo de busca vazia: nada
# indica que a palavra certa era outra.
#
# `Corsan` NÃO SERVE DE EXEMPLO, e é por isso que este teste usa a holding: a
# razão social da Corsan contém a palavra "Corsan", então o defeito se esconde
# justamente no caso mais citado.

NOME_DA_HOLDING = "Holding / corporativo"
RAZAO_DA_HOLDING = "Aegea Saneamento e Participações S/A"


@pytest.fixture
def holding(sessao):
    """Uma menção que a tela rotula pelo cadastro e grava com a razão social."""
    from app.banco.tabelas_catalogo import UnidadeNegocio

    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    unidade = sessao.scalar(
        select(UnidadeNegocio.id).where(UnidadeNegocio.nome == NOME_DA_HOLDING)
    )
    assert unidade is not None, f"o cadastro não tem {NOME_DA_HOLDING!r}"
    sessao.add(
        Mencao(
            fonte_id=clipei.id,
            mes=date(2026, 8, 1),
            data=date(2026, 8, 5),
            sentimento="neu",
            titulo_texto="Resultado trimestral",
            unidade_texto=RAZAO_DA_HOLDING,
            unidade_negocio_id=unidade,
        )
    )
    sessao.flush()
    return unidade


def test_a_busca_acha_pelo_nome_que_a_TELA_MOSTRA(sessao, holding):
    pagina = _listar(sessao, q=NOME_DA_HOLDING)

    assert pagina.total == 1, (
        "buscar o nome que a coluna exibe devolveu nada — a busca procura o "
        f"texto do fornecedor e a tela mostra o do cadastro (total={pagina.total})"
    )
    assert pagina.itens[0].empresa == NOME_DA_HOLDING


def test_a_busca_CONTINUA_achando_pelo_texto_do_fornecedor(sessao, holding):
    """O controle negativo: o novo campo acrescenta, não substitui.

    Quem já procurava pela razão social — porque é o que está na planilha que
    tem na mão — não pode perder o resultado.
    """
    pagina = _listar(sessao, q="Participações")

    assert pagina.total == 1
    assert pagina.itens[0].empresa == NOME_DA_HOLDING


def test_a_CONTAGEM_e_a_lista_concordam_na_busca_pelo_cadastro(sessao, holding):
    """`total` sai de outra consulta, e ela também precisa da junção.

    Sem o `outerjoin` na consulta do `total`, a paginação diria um número e a
    lista mostraria outro — ou a consulta nem montaria.
    """
    pagina = _listar(sessao, q=NOME_DA_HOLDING)

    assert pagina.total == len(pagina.itens)
