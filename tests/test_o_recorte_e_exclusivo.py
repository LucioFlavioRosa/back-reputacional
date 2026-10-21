"""O recorte de uma lente é EXCLUSIVO, e simétrico.

O PEDIDO (20/10/2026): "se o Valor Econômico é um veículo de imprensa de
mercado, absolutamente todas as matérias dele vão para a lente de mercado...
isso deve ser simétrico: se voltar a ser imprensa, o histórico deve ser movido
também de volta".

COMO ERA, E ESTÁ MEDIDO: o espelho (`clipei`) ficava com o arquivo inteiro e a
recortada era uma CÓPIA do subconjunto. Uma subida com duas matérias deixava
`clipei` com 2 e `clipei_investidores` com 1 — a do Valor Econômico contava nas
DUAS lentes. Classificar movia o histórico para dentro do recorte e não o tirava
da Imprensa.

COMO FICA: o mês do arquivo é uma PARTIÇÃO entre as fontes irmãs. A que declara
a lista fica com os veículos dela; a que não declara fica com o resto. E a
reconciliação move nos dois sentidos.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes, reconciliar_lista_de_veiculos
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

DO_MERCADO = "Valor Econômico zz80"
QUALQUER = "Jornal Qualquer zz81"
MES = date(2026, 7, 1)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    s = Session(bind=conexao, expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        transacao.rollback()
        conexao.close()


def _planilha() -> bytes:
    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    aba.append(
        [
            "Data",
            "Classificação",
            "Veículo",
            "Título",
            "Atributo",
            "Aegea Tier",
            "Público-alvo",
            "Subcategoria",
        ]
    )
    for veiculo in (DO_MERCADO, QUALQUER):
        aba.append(
            [
                date(2026, 7, 3),
                "Positivo",
                veiculo,
                f"Matéria do {veiculo}",
                "Governança",
                "Muito relevante",
                "População em geral",
                "Tarifa",
            ]
        )
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _veiculos_por_lente(sessao) -> dict[str, list[str | None]]:
    """QUAL veículo está em qual lente, e não só quantos.

    LACUNA QUE A TERCEIRA REVISÃO APONTOU NUM TESTE MEU: conferir contagem por
    lente deixa passar a TROCA — as linhas têm pesos iguais, então "imprensa 1,
    mercado 1" vale tanto para o certo quanto para o avesso. Num
    reparticionamento, trocar duas linhas de lugar é exatamente o defeito
    plausível.
    """
    por_lente: dict[str, list[str | None]] = {}
    for codigo, veiculo in sessao.execute(
        select(Lente.codigo, Mencao.veiculo)
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
    ).all():
        por_lente.setdefault(codigo, []).append(veiculo)
    return {codigo: sorted(nomes, key=str) for codigo, nomes in por_lente.items()}


def _por_lente(sessao) -> dict[str, int]:
    return {
        codigo: total
        for codigo, total in sessao.execute(
            select(Lente.codigo, func.count(Mencao.id))
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .join(Lente, Lente.id == ScoreFonte.lente_id)
            .group_by(Lente.codigo)
        ).all()
    }


def _agregado(sessao) -> dict[str, float]:
    return {
        codigo: float(total or 0)
        for codigo, total in sessao.execute(
            select(Lente.codigo, func.sum(ScoreMesFonte.mencoes))
            .select_from(ScoreMesFonte)
            .join(ScoreFonte, ScoreFonte.id == ScoreMesFonte.fonte_id)
            .join(Lente, Lente.id == ScoreFonte.lente_id)
            .group_by(Lente.codigo)
        ).all()
    }


def _subcategoria(sessao, nome: str) -> int:
    return sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(CategoriaPublico, CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id)
        .where(CategoriaPublico.nome == "Imprensa", SubcategoriaPublico.nome == nome)
    )


def _classificar(sessao, nome: str, subcategoria: int | None) -> None:
    veiculo = sessao.scalar(
        select(Instituicao).where(Instituicao.nome_normalizado == normalizar(nome))
    )
    assert veiculo is not None, f"{nome} tinha de existir no cadastro"
    veiculo.subcategoria_publico_id = subcategoria
    sessao.flush()


def _reconciliar(sessao) -> None:
    for fonte in reconciliar_lista_de_veiculos.fontes_que_recortam(
        sessao, "imprensa_economica"
    ):
        reconciliar_lista_de_veiculos.aplicar(sessao, fonte)


def _subir(sessao) -> None:
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    ingerir_mencoes.ingerir(sessao, clipei, _planilha(), [DO_MERCADO, QUALQUER])


def test_a_SUBIDA_ja_particiona_entre_as_lentes(sessao):
    """Com o veículo já classificado, a matéria dele NASCE só no Mercado.

    Era aqui que a duplicação começava: o espelho lia o arquivo inteiro e a
    recortada relia o subconjunto, então a matéria do Valor Econômico virava
    linha nas duas lentes na mesma subida.
    """
    #: O veículo precisa existir ANTES, classificado — é o estado de quem já
    #: mantém a lista e sobe a planilha do mês.
    sessao.add(
        Instituicao(
            nome=DO_MERCADO,
            nome_normalizado=normalizar(DO_MERCADO),
            tipo="veiculo",
            subcategoria_publico_id=_subcategoria(sessao, "Econômica e de negócios"),
        )
    )
    sessao.flush()

    _subir(sessao)

    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}
    assert _agregado(sessao) == {"imprensa": 1.0, "mercado": 1.0}


def test_CLASSIFICAR_move_o_historico_e_TIRA_da_imprensa(sessao):
    """O cenário do dono do produto, medido de ponta a ponta."""
    _subir(sessao)
    assert _por_lente(sessao) == {"imprensa": 2}

    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)

    #: O MERCADO GANHOU, A IMPRENSA PERDEU. Era a segunda metade que não
    #: acontecia: a Imprensa continuava com 2.
    #:
    #: POR VEÍCULO: a contagem sozinha não distingue o certo da troca.
    assert _veiculos_por_lente(sessao) == {
        "imprensa": [QUALQUER],
        "mercado": [DO_MERCADO],
    }
    #: E O AGREGADO ACOMPANHA, que é quem carrega a NOTA. Mexer em `mencao` e
    #: esquecer `score_mes_fonte` deixaria a lista certa e a nota errada.
    assert _agregado(sessao) == {"imprensa": 1.0, "mercado": 1.0}


def test_DESCLASSIFICAR_traz_o_historico_de_VOLTA(sessao):
    """A simetria, que é o que ele pediu em voz alta.

    "se voltar a ser imprensa o histórico deve ser movido também de volta".
    Com a partição, a menção existe num lugar só — tirá-la do Mercado sem
    devolvê-la apagaria a matéria do sistema.
    """
    _subir(sessao)
    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)
    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}

    #: E AGORA ELE VOLTA A SER IMPRENSA COMUM.
    _classificar(sessao, DO_MERCADO, None)
    _reconciliar(sessao)

    assert _por_lente(sessao) == {"imprensa": 2}
    assert _agregado(sessao) == {"imprensa": 2.0}
    #: A MATÉRIA É A MESMA, e não uma linha nova vazia: o texto do veículo
    #: voltou junto.
    veiculos = sessao.scalars(
        select(Mencao.veiculo)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(ScoreFonte.codigo == "clipei")
    ).all()
    assert sorted(veiculos) == sorted([DO_MERCADO, QUALQUER])


def test_a_IDA_E_VOLTA_nao_duplica_nem_perde(sessao):
    """Duas voltas completas: o total do arquivo não pode mudar nunca."""
    _subir(sessao)
    total = sum(_por_lente(sessao).values())

    for _ in range(2):
        _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
        _reconciliar(sessao)
        assert sum(_por_lente(sessao).values()) == total
        _classificar(sessao, DO_MERCADO, None)
        _reconciliar(sessao)
        assert sum(_por_lente(sessao).values()) == total

    assert _por_lente(sessao) == {"imprensa": 2}


def _mencao_crua(sessao, fonte_codigo: str, veiculo: str | None) -> None:
    """Uma menção posta à mão numa fonte, para montar estados que a ingestão
    de hoje não produz mais — a duplicação antiga e a cópia parcial.

    E O AGREGADO VAI COM ELA, porque na vida real a ingestão escreve os dois. A
    primeira versão da fixture só punha a menção, e aí um teste cobrava do
    motor que ele CRIASSE o agregado de uma fonte cujas menções não mudaram —
    exigência que o código não tem e nem deveria ter: agregado de fonte intacta
    já está certo.
    """
    fonte = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == fonte_codigo)).one()
    sessao.add(
        Mencao(
            fonte_id=fonte.id,
            mes=MES,
            data=date(2026, 7, 3),
            sentimento="pos",
            veiculo=veiculo,
            titulo_texto=f"Posta à mão — {veiculo}",
        )
    )
    sessao.flush()

    quantas = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.fonte_id == fonte.id, Mencao.mes == MES)
    )
    sessao.execute(
        delete(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes == MES
        )
    )
    sessao.add(
        ScoreMesFonte(
            fonte_id=fonte.id,
            mes=MES,
            sentimento="pos",
            tier="",
            mencoes=quantas,
            soma_log=quantas,
            soma_engajamento=0,
            soma_cargo=0,
        )
    )
    sessao.flush()


def test_a_TRANSICAO_do_historico_duplicado_e_corrigida(sessao):
    """ACHADO ALTO DE REVISÃO, e o que fazia a mudança não servir para nada.

    O ESTADO DE HOJE em dev e em produção: o espelho tem o arquivo inteiro e a
    recortada tem a cópia do veículo listado — a mesma matéria nas duas lentes.
    A primeira versão media só o lado da recortada, que já estava certo, e
    concluía "nada mudou": o `aplicar` não fazia nada e a duplicação do
    histórico ficava intacta. Ou seja, a exclusividade só valia para dado
    ingerido DEPOIS da mudança, e o pedido era justamente o contrário.
    """
    sessao.add(
        Instituicao(
            nome=DO_MERCADO,
            nome_normalizado=normalizar(DO_MERCADO),
            tipo="veiculo",
            subcategoria_publico_id=_subcategoria(sessao, "Econômica e de negócios"),
        )
    )
    sessao.flush()
    #: O ESPELHO COM AS DUAS (como a Clipei sempre teve) e a recortada com a
    #: cópia da listada: exatamente o estado que o banco tem hoje.
    _mencao_crua(sessao, "clipei", DO_MERCADO)
    _mencao_crua(sessao, "clipei", QUALQUER)
    _mencao_crua(sessao, "clipei_investidores", DO_MERCADO)
    assert _por_lente(sessao) == {"imprensa": 2, "mercado": 1}

    _reconciliar(sessao)

    #: 1 E 1: a duplicação sumiu, e nada se perdeu.
    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}
    assert _agregado(sessao) == {"imprensa": 1.0, "mercado": 1.0}


def test_a_COPIA_PARCIAL_nao_perde_linha(sessao):
    """O outro achado: a devolução conferia PRESENÇA, e não contagem.

    Com a recortada tendo duas linhas de um veículo que saiu da lista e o
    espelho tendo uma, nada era devolvido — e o `delete` seguinte apagava as
    duas. Uma linha do sistema desaparecia.
    """
    _mencao_crua(sessao, "clipei_investidores", QUALQUER)
    _mencao_crua(sessao, "clipei_investidores", QUALQUER)
    _mencao_crua(sessao, "clipei", QUALQUER)
    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 2}

    _reconciliar(sessao)

    #: O QUALQUER NÃO ESTÁ NA LISTA: as duas linhas dele saem do Mercado, e a
    #: que o espelho ainda não tinha é devolvida. Nada desaparece.
    assert _por_lente(sessao) == {"imprensa": 2}


def test_a_mencao_SEM_VEICULO_na_recortada_volta_para_o_espelho(sessao):
    """O terceiro achado. A linha sem veículo não está na lista (nenhuma
    recortada a aceita), ficava fora da devolução por um `is_not(None)`, e o
    `delete` do mês a apagava. Pela regra da ingestão ela é do espelho.

    A `0067` registra que elas existem na recortada: foram gravadas pelo
    critério antigo, a coluna `Público-alvo`, que não exigia veículo.
    """
    _mencao_crua(sessao, "clipei_investidores", None)
    assert _por_lente(sessao) == {"mercado": 1}

    _reconciliar(sessao)

    assert _por_lente(sessao) == {"imprensa": 1}


def _reconciliar_lista(sessao, lista: str) -> None:
    for fonte in reconciliar_lista_de_veiculos.fontes_que_recortam(sessao, lista):
        reconciliar_lista_de_veiculos.aplicar(sessao, fonte)


@pytest.mark.parametrize(
    "ordem",
    [
        ("imprensa_economica", "imprensa_institucional"),
        ("imprensa_institucional", "imprensa_economica"),
    ],
)
def test_de_UMA_LISTA_PARA_A_OUTRA_nao_depende_da_ordem(sessao, ordem):
    """ACHADO ALTO DA SEGUNDA REVISÃO, e um caso que eu não tinha imaginado.

    Um veículo que vai do Mercado para a Institucional: aplicando a
    Institucional PRIMEIRO, ela não achava a linha (o universo era `fonte +
    espelho`, e a linha estava na recortada do Mercado); depois o Mercado a
    devolvia ao espelho, e ela terminava na IMPRENSA. Na ordem inversa
    funcionava — o resultado dependia de quem aplicasse primeiro, e as duas
    listas se aplicam por cliques separados na tela.

    AGORA O REPARTICIONAMENTO É DO ARQUIVO: cada linha tem um dono (a lista que
    contém o veículo dela), e a ordem deixa de importar.
    """
    _subir(sessao)
    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)
    assert _por_lente(sessao) == {"imprensa": 1, "mercado": 1}

    #: E AGORA ELE VIRA INSTITUCIONAL.
    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Institucional"))
    for lista in ordem:
        _reconciliar_lista(sessao, lista)

    #: POR VEÍCULO, E NÃO POR CONTAGEM — lacuna que a revisão apontou neste
    #: teste: "imprensa 1, institucional 1" vale tanto para o certo quanto para
    #: o avesso, porque as duas linhas pesam igual. Num reparticionamento,
    #: trocar duas linhas de lugar é justamente o defeito plausível.
    assert _veiculos_por_lente(sessao) == {
        "imprensa": [QUALQUER],
        "institucional": [DO_MERCADO],
    }
    assert _agregado(sessao) == {"imprensa": 1.0, "institucional": 1.0}


def test_DOIS_TEXTOS_que_normalizam_igual_vao_os_DOIS(sessao):
    """O caso mais sutil, e a revisão o verificou antes de eu testar.

    O DONO é decidido pelo texto NORMALIZADO ("VALOR ECONOMICO" e "Valor
    Econômico" são o mesmo veículo), mas o `delete` e a cópia são pelo texto
    CRU. Se os dois fossem tratados como um, um deles ficaria órfão na irmã
    errada — ou seria apagado sem ter sido copiado.
    """
    sessao.add(
        Instituicao(
            nome=DO_MERCADO,
            nome_normalizado=normalizar(DO_MERCADO),
            tipo="veiculo",
            subcategoria_publico_id=_subcategoria(sessao, "Econômica e de negócios"),
        )
    )
    sessao.flush()
    #: O MESMO VEÍCULO EM DUAS GRAFIAS, como o clipping manda ao longo dos
    #: meses — é o motivo de o sistema comparar normalizado em todo lugar.
    cru = DO_MERCADO.upper()
    _mencao_crua(sessao, "clipei", DO_MERCADO)
    _mencao_crua(sessao, "clipei", cru)

    _reconciliar(sessao)

    #: OS DOIS TEXTOS no Mercado, e NENHUM sobrando na Imprensa — e são DOIS,
    #: não um: tratá-los como uma linha só perderia uma matéria.
    assert _veiculos_por_lente(sessao) == {"mercado": sorted([DO_MERCADO, cru])}


def test_reconciliar_DUAS_VEZES_nao_muda_nada(sessao):
    #: A idempotência do gesto: a segunda aplicação não acha mês para mudar, e
    #: nada se move. Sem isto, cada clique no Salvar duplicaria ou apagaria.
    _subir(sessao)
    _classificar(sessao, DO_MERCADO, _subcategoria(sessao, "Econômica e de negócios"))
    _reconciliar(sessao)
    antes = _por_lente(sessao)

    _reconciliar(sessao)

    assert _por_lente(sessao) == antes
