"""O recorte e o rótulo de concessionária usam a chave da `0099`.

O QUE ESTAVA ERRADO. A dimensão "Concessionária" saía do TEXTO do fornecedor
(`mencao.unidade_texto`), e a mesma operação chega em grafias diferentes:

    Corsan .......... "Corsan" (1.111) + "Companhia Riograndense de
                      Saneamento (Corsan)" (15.019)
    Holding ......... "Holding" (1.411) + "Aegea Saneamento e
                      Participações S/A" (7.258)
    Gov. Valadares .. "Águas de Valadares" (905) + "Água de Valadares" (1)

Eram DUAS barras no gráfico e DOIS valores no seletor para a mesma empresa, e
clicar numa delas recortava só a metade dela. 16.130 menções da Corsan em dois
baldes.

O QUE ESTE ARQUIVO PROTEGE:

1. que o recorte pelo nome do cadastro alcance TODAS as grafias — é o que o
   dono do produto pediu ao dizer "para fazer essa deduplicação, depois da
   normalização os nomes devem ser iguais";
2. que o conjunto novo seja SUPERCONJUNTO do antigo: a menção que o cadastro
   não resolve continua sendo achada pelo texto cru. Acrescentar disjunção só
   ganha linha;
3. que O SELETOR E O RECORTE CONTEM O MESMO. É a lição da `0098`: lá a barra do
   N2 mostrava 29.701 e o clique nela alcançava 30.932, porque a leitura
   agrupava por um caminho e o filtro recortava por outro;
4. que a COLUNA DA TABELA mostre o mesmo nome por que a lista ordena e o
   seletor agrupa.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco import repositorio_lentes, repositorio_score
from app.banco.repositorio_score import CONCESSIONARIA, condicoes_do_filtro
from app.banco.tabelas_catalogo import UnidadeNegocio
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.dominio.score import Calibracao, FiltroDeMencoes
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

MES = date(2026, 1, 1)

#: AS DUAS GRAFIAS QUE A `0099` UNE, e a unidade do cadastro que elas são.
NOME_DO_CADASTRO = "Corsan"
RAZAO_SOCIAL = "Companhia Riograndense de Saneamento (Corsan)"
#: UM NOME QUE O CADASTRO NÃO TEM, sem chave de propósito — "Águas de Trevo"
#: não é concessão de verdade. Até 19/10/2026 este constante era "Águas do
#: Rio", um nome ambíguo de verdade (duas linhas do cadastro, "1" e "4"); a
#: migration `0104` (por pedido) consolidou as duas numa só, e "Águas do Rio"
#: passou a RESOLVER — deixou de servir de exemplo de "sem chave" aqui.
SEM_CHAVE = "Águas de Trevo"


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
def fonte(sessao: Session) -> int:
    ident = sessao.scalar(select(ScoreFonte.id).order_by(ScoreFonte.id).limit(1))
    assert ident is not None, "nenhuma fonte cadastrada"
    return ident


@pytest.fixture
def corsan(sessao: Session) -> int:
    ident = sessao.scalar(
        select(UnidadeNegocio.id).where(UnidadeNegocio.nome == NOME_DO_CADASTRO)
    )
    assert ident is not None, f"o cadastro não tem {NOME_DO_CADASTRO!r}"
    return ident


def _mencao(sessao: Session, fonte_id: int, **campos) -> uuid.UUID:
    ident = uuid.uuid4()
    sessao.add(
        Mencao(
            id=ident, fonte_id=fonte_id, mes=MES, data=MES, sentimento="neg", **campos
        )
    )
    sessao.flush()
    return ident


def _acha(sessao: Session, filtro: FiltroDeMencoes, ident: uuid.UUID) -> bool:
    """A menção `ident` passa pelo recorte?"""
    return (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.id == ident, *condicoes_do_filtro(filtro))
        )
        == 1
    )


# -- 1. a deduplicação: um nome alcança as duas grafias ------------------------


def test_o_recorte_pelo_nome_do_cadastro_acha_AS_DUAS_GRAFIAS(sessao, fonte, corsan):
    """O pedido, verificado: depois de normalizar, os nomes são iguais.

    As duas menções abaixo têm `unidade_texto` DIFERENTE e a mesma chave. Antes
    da `0099`, recortar por "Corsan" achava só a primeira.
    """
    pelo_nome = _mencao(
        sessao, fonte, unidade_texto=NOME_DO_CADASTRO, unidade_negocio_id=corsan
    )
    pela_razao_social = _mencao(
        sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan
    )

    filtro = FiltroDeMencoes(empresa=NOME_DO_CADASTRO)
    assert _acha(sessao, filtro, pelo_nome)
    assert _acha(sessao, filtro, pela_razao_social)


def test_o_recorte_pela_razao_social_tambem_acha_as_duas(sessao, fonte, corsan):
    """O seletor passou a oferecer só "Corsan", mas um link antigo — ou alguém
    digitando na URL — pode mandar a razão social. Ela entra pelo texto cru e
    acha a linha que o tem; o que não pode é estourar."""
    pela_razao_social = _mencao(
        sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan
    )
    assert _acha(sessao, FiltroDeMencoes(empresa=RAZAO_SOCIAL), pela_razao_social)


# -- 2. superconjunto: nada que achava hoje deixa de ser achado ---------------


def test_o_recorte_ainda_acha_PELO_TEXTO_CRU(sessao, fonte):
    """A menção SEM chave continua sendo achada pelo nome do fornecedor.

    É a verificação de superconjunto na forma que importa: a menção cuja
    grafia o cadastro não resolve continua achável pelo texto cru. Se alguém
    "simplificar" a condição trocando o `or` pela coluna nova, estas somem do
    filtro que as acha hoje.
    """
    ident = _mencao(sessao, fonte, unidade_texto=SEM_CHAVE)
    assert sessao.scalar(
        select(Mencao.unidade_negocio_id).where(Mencao.id == ident)
    ) is None, "o caso precisa ter a chave NULA para provar o que prova"
    assert _acha(sessao, FiltroDeMencoes(empresa=SEM_CHAVE), ident)


def test_a_concessionaria_errada_nao_acha(sessao, fonte, corsan):
    """A condição nova não é um `or` frouxo que deixa tudo passar."""
    outra = sessao.scalar(
        select(UnidadeNegocio.nome)
        .where(UnidadeNegocio.ativo.is_(True), UnidadeNegocio.id != corsan)
        .order_by(UnidadeNegocio.id)
        .limit(1)
    )
    assert outra, "o cadastro só tem uma unidade; o teste não provaria nada"
    ident = _mencao(
        sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan
    )
    assert not _acha(sessao, FiltroDeMencoes(empresa=outra), ident)


def test_o_recorte_por_concessionaria_e_superconjunto_do_antigo(sessao, fonte, corsan):
    """A PROPRIEDADE, enumerada em vez de prometida.

    A regra antiga era `unidade_texto == valor`. A nova acrescenta um disjunto.
    Para cada combinação de (texto, chave) que o banco admite, o que a antiga
    achava a nova tem de achar — e a nova pode achar mais.
    """
    combinacoes = [
        (NOME_DO_CADASTRO, corsan),
        (NOME_DO_CADASTRO, None),
        (RAZAO_SOCIAL, corsan),
        (RAZAO_SOCIAL, None),
        (SEM_CHAVE, None),
        (None, corsan),
    ]
    for texto, chave in combinacoes:
        ident = _mencao(
            sessao, fonte, unidade_texto=texto, unidade_negocio_id=chave
        )
        for valor in (NOME_DO_CADASTRO, RAZAO_SOCIAL, SEM_CHAVE):
            achava = texto == valor
            acha = _acha(sessao, FiltroDeMencoes(empresa=valor), ident)
            assert acha or not achava, (
                f"a regra nova PERDEU uma linha: texto={texto!r} chave={chave!r} "
                f"recorte={valor!r}"
            )


# -- 3. o seletor e o recorte contam o mesmo -----------------------------------


def test_o_rotulo_do_cadastro_VENCE_o_texto_do_fornecedor(sessao, fonte, corsan):
    """A expressão que a tela mostra: `coalesce(nome do cadastro, texto)`.

    É ela que faz as duas grafias virarem UMA entrada no seletor e UMA barra no
    gráfico — e é por ela que a coluna da Base e a ordenação passam.
    """
    _mencao(sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan)
    _mencao(sessao, fonte, unidade_texto=NOME_DO_CADASTRO, unidade_negocio_id=corsan)
    #: E A SEM CHAVE MANTÉM O TEXTO DO FORNECEDOR: sumir do seletor seria o
    #: oposto de normalizar.
    _mencao(sessao, fonte, unidade_texto=SEM_CHAVE)

    rotulos = sessao.execute(
        select(CONCESSIONARIA, func.count())
        .select_from(Mencao)
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .where(Mencao.mes == MES, Mencao.fonte_id == fonte)
        .group_by(CONCESSIONARIA)
    ).all()
    por_rotulo = dict(rotulos)

    assert por_rotulo.get(NOME_DO_CADASTRO) == 2, (
        f"as duas grafias tinham de virar uma entrada só: {por_rotulo}"
    )
    assert RAZAO_SOCIAL not in por_rotulo
    assert por_rotulo.get(SEM_CHAVE) == 1


def test_o_rotulo_e_o_recorte_contam_O_MESMO(sessao, fonte, corsan):
    """A LIÇÃO DA `0098`, aplicada antes de doer.

    Lá a barra do N2 mostrava 29.701 e o clique nela alcançava 30.932: a leitura
    agrupava por `Tema.macro_tema_id` e o filtro recortava por
    `Mencao.macro_tema_id`. Aqui a conta tem de fechar nos dois sentidos, para
    cada rótulo que o seletor oferece.
    """
    _mencao(sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan)
    _mencao(sessao, fonte, unidade_texto=NOME_DO_CADASTRO, unidade_negocio_id=corsan)
    _mencao(sessao, fonte, unidade_texto=SEM_CHAVE)

    do_rotulo = dict(
        sessao.execute(
            select(CONCESSIONARIA, func.count())
            .select_from(Mencao)
            .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
            .where(Mencao.mes == MES, Mencao.fonte_id == fonte)
            .group_by(CONCESSIONARIA)
        ).all()
    )

    for rotulo, quantas in do_rotulo.items():
        do_recorte = sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(
                Mencao.mes == MES,
                Mencao.fonte_id == fonte,
                *condicoes_do_filtro(FiltroDeMencoes(empresa=rotulo)),
            )
        )
        assert do_recorte == quantas, (
            f"o rótulo {rotulo!r} conta {quantas} e o clique nele alcança "
            f"{do_recorte}"
        )


# -- 4. as outras duas telas que mostram concessionária ------------------------


def test_o_drill_agrupa_pelo_NOME_DO_CADASTRO():
    """A tela de aprofundamento agrupa em Python, e tem de concordar com as
    lentes sobre quantas empresas existem.

    SEM ISTO a Corsan vira duas fatias aqui e uma no seletor das lentes — duas
    telas discordando, que é pior que as duas erradas do mesmo jeito.
    """
    from app.dominio.consulta_profundidade import MencaoDaConsulta

    def mencao(**campos) -> MencaoDaConsulta:
        return MencaoDaConsulta(id="x", mes=MES, sentimento="neg", **campos)

    pela_razao_social = mencao(
        unidade_texto=RAZAO_SOCIAL, unidade_cadastrada=NOME_DO_CADASTRO
    )
    pelo_nome = mencao(unidade_texto=NOME_DO_CADASTRO, unidade_cadastrada=NOME_DO_CADASTRO)
    assert pela_razao_social.concessionaria == pelo_nome.concessionaria == NOME_DO_CADASTRO

    #: E A SEM CHAVE CAI NO TEXTO DO FORNECEDOR, em vez de virar "Não
    #: informada": o nome que ela tem é melhor que nenhum.
    sem_chave = mencao(unidade_texto=SEM_CHAVE)
    assert sem_chave.concessionaria == SEM_CHAVE
    #: E O TEXTO CRU CONTINUA ALCANÇÁVEL, que é o motivo de ser propriedade e
    #: não renomear o campo.
    assert pela_razao_social.unidade_texto == RAZAO_SOCIAL


def test_a_dimensao_de_risco_oferece_UM_nome_e_o_recorte_acha_as_duas(
    sessao, fonte, corsan
):
    """A aba de riscos: a opção que ela oferece e o recorte que ela aplica.

    O RECORTE DELA É OUTRA FUNÇÃO (`repositorio_riscos.condicao_da_dimensao`), e
    por isso tem teste próprio: ela recortava por `getattr(Mencao,
    'unidade_texto')`, então ofereceria "Corsan" (as duas grafias somadas) e
    recortaria só a grafia curta. É a mesma dessincronia da barra do N2 na
    `0098`.
    """
    from app.banco.repositorio_riscos import condicao_da_dimensao

    pela_razao_social = _mencao(
        sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan
    )
    pelo_nome = _mencao(
        sessao, fonte, unidade_texto=NOME_DO_CADASTRO, unidade_negocio_id=corsan
    )

    condicao = condicao_da_dimensao("unidade", NOME_DO_CADASTRO)
    assert condicao is not None
    achadas = set(
        sessao.scalars(
            select(Mencao.id).where(
                Mencao.id.in_([pela_razao_social, pelo_nome]), condicao
            )
        )
    )
    assert achadas == {pela_razao_social, pelo_nome}

    #: E A DIMENSÃO DESCONHECIDA CONTINUA DEVOLVENDO `None`, que é como o laço
    #: do filtro sabe ignorá-la.
    assert condicao_da_dimensao("nao_existe", "x") is None


def test_a_aba_DA_CAUSA_agrupa_a_concessionaria_pelo_cadastro():
    """A quinta leitura, e a que eu tinha esquecido.

    A aba "Onde está a causa" declara as dimensões em `causa_da_lente` por NOME
    DE CAMPO, e o repositório resolvia com `getattr(Mencao, campo)` — texto cru.
    O painel ao lado já mostrava o nome do cadastro, e o comentário do caso
    `tema`, logo acima no mesmo arquivo, descreve exatamente o estrago: "os dois
    ficam lado a lado na mesma tela: rótulos diferentes para o mesmo mês, e um
    clique no rótulo do painel mandando ao servidor uma grafia que o dado não
    tem".

    ESTE TESTE PRENDE A FIAÇÃO, e não o `if`: ele parte da dimensão DECLARADA,
    então renomear o campo em `causa_da_lente` sem atualizar o mapa falha aqui.
    """
    from app.banco.repositorio_lentes import coluna_da_dimensao
    from app.dominio.causa_da_lente import DIMENSOES_POR_LENTE

    declaradas = [
        dim for dim in DIMENSOES_POR_LENTE["sociedade"] if dim.chave == "empresa"
    ]
    assert declaradas, "a lente Sociedade declara a dimensão 'empresa'"
    assert coluna_da_dimensao(declaradas[0].campo) is CONCESSIONARIA

    #: E AS OUTRAS NÃO MUDAM: é uma exceção nomeada, não um desvio geral.
    assert coluna_da_dimensao("uf") is Mencao.uf
    assert coluna_da_dimensao("perfil_autor") is Mencao.perfil_autor


# -- 5. os dois RANKINGS que ficaram para trás ---------------------------------
#
# A REVISÃO DO CODEX (18/10/2026) ACHOU O QUE EU PROCUREI E NÃO ENCONTREI. Eu
# tinha levado `CONCESSIONARIA` a cinco leituras e escrito, no cabeçalho deste
# arquivo, que o rótulo e o recorte contam o mesmo. Duas ficaram de fora, e são
# justamente as que respondem "onde está o problema":
#
#   `repositorio_score.unidades_do_mes`   — "onde a pressão se concentra"
#   `repositorio_lentes.unidades_da_lente` — o ranking do dossiê, com o mês de pico
#
# Nas duas, a Corsan voltava a aparecer em DUAS barras. É o mesmo defeito que a
# `0098` cobrou na barra do N2 — agrupar por um caminho e recortar por outro —,
# só que aqui nem recortar chegava a acontecer: elas agrupavam pela grafia crua
# enquanto o seletor ao lado já oferecia o nome do cadastro.


def test_o_ranking_do_MES_agrupa_as_duas_grafias_numa_barra(sessao, fonte, corsan):
    """`unidades_do_mes`: uma linha "Corsan", com as duas grafias somadas."""
    _mencao(sessao, fonte, unidade_texto=NOME_DO_CADASTRO, unidade_negocio_id=corsan)
    _mencao(sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan)

    linhas = repositorio_score.unidades_do_mes(sessao, MES, Calibracao())
    por_nome = {nome: (neg, total) for nome, neg, total in linhas}

    assert RAZAO_SOCIAL not in por_nome, (
        "a razão social virou uma barra própria — a mesma empresa em dois lugares"
    )
    assert por_nome.get(NOME_DO_CADASTRO) == (2, 2), (
        f"esperava Corsan somando as duas grafias; veio {por_nome!r}"
    )


def test_o_ranking_do_MES_ainda_mostra_quem_o_cadastro_nao_resolve(sessao, fonte):
    """O `outerjoin` não pode sumir com a menção sem chave.

    `SEM_CHAVE` fica sem chave DE PROPÓSITO, de novo. Um `join` em vez de
    `outerjoin` a tiraria do ranking — e sumir do painel "onde está o
    problema" é pior que aparecer com a palavra do fornecedor.
    """
    _mencao(sessao, fonte, unidade_texto=SEM_CHAVE)

    linhas = repositorio_score.unidades_do_mes(sessao, MES, Calibracao())

    assert SEM_CHAVE in {nome for nome, _, _ in linhas}


def test_o_ranking_do_DOSSIE_agrupa_as_duas_grafias(sessao, fonte, corsan):
    """`unidades_da_lente`: idem, e o `total` soma as duas."""
    lente_id = sessao.scalar(select(ScoreFonte.lente_id).where(ScoreFonte.id == fonte))
    _mencao(sessao, fonte, unidade_texto=NOME_DO_CADASTRO, unidade_negocio_id=corsan)
    _mencao(sessao, fonte, unidade_texto=RAZAO_SOCIAL, unidade_negocio_id=corsan)

    linhas = repositorio_lentes.unidades_da_lente(sessao, lente_id, [MES], Calibracao())
    por_nome = {linha["unidade"]: linha["total"] for linha in linhas}

    assert RAZAO_SOCIAL not in por_nome, (
        "a razão social virou uma entrada própria no ranking do dossiê"
    )
    assert por_nome.get(NOME_DO_CADASTRO) == 2, (
        f"esperava Corsan com as duas grafias somadas; veio {por_nome!r}"
    )


def test_o_ranking_do_DOSSIE_ainda_mostra_quem_o_cadastro_nao_resolve(sessao, fonte):
    """O mesmo controle negativo do `outerjoin`, no dossiê."""
    lente_id = sessao.scalar(select(ScoreFonte.lente_id).where(ScoreFonte.id == fonte))
    _mencao(sessao, fonte, unidade_texto=SEM_CHAVE)

    linhas = repositorio_lentes.unidades_da_lente(sessao, lente_id, [MES], Calibracao())

    assert SEM_CHAVE in {linha["unidade"] for linha in linhas}