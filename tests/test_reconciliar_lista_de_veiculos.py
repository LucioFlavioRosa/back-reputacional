"""A lista de veículos passa a valer para os meses JÁ ingeridos.

O PEDIDO: "se eu dizer que uma instituição pertence a categoria de público como
imprensa e esfera econômica e de negócios, todos seus registros devem ser movidos
para a lente de mercado, atualizando tudo".

COMO ERA: a `0067` escreveu que "nada muda nos meses já gravados — o novo
critério vale a partir da PRÓXIMA subida de cada mês". Classificar o Valor
Econômico hoje não o fazia entrar em agosto.

O QUE ESTES TESTES PROTEGEM:

* classificar faz o veículo entrar em TODOS os meses já ingeridos, e não só no
  último;
* DESclassificar o tira — os dois sentidos, por decisão do dono do produto;
* o agregado reconciliado é IGUAL ao que a ingestão escreveria com a mesma
  lista. É o teste que impede a segunda definição de "o que é um mês no banco";
* a prévia não escreve;
* o casamento é por nome NORMALIZADO, como o da ingestão — acento e caixa não
  tiram ninguém da lente;
* o mês que perde todos os veículos fica vazio DE VERDADE, agregado inclusive.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes, reconciliar_lista_de_veiculos
from app.dominio.erros import RegraViolada
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


_CABECALHO = ["Data", "Classificação", "Veículo", "Aegea Tier", "Engajamento", "Cargo"]

#: O MAPEAMENTO É O MESMO NAS DUAS FONTES, menos a lista — é o que a `0063` diz
#: do par real (`clipei`/`clipei_investidores`): "as duas fontes recebem o mesmo
#: mapeamento, porque leem o mesmo arquivo; a irmã conserva o filtro dela".
#:
#: TIER, ENGAJAMENTO E CARGO ENTRAM DE PROPÓSITO, e é conserto de um buraco que a
#: revisão apontou: sem eles, as quatro somas do agregado seriam `mencoes` e três
#: zeros, e o teste que compara a reconciliação com a resubida passaria mesmo se
#: `soma_log`, `soma_engajamento` ou `soma_cargo` divergissem. São justamente as
#: três que dependem de `somar` fazer a mesma conta nos dois caminhos.
_COLUNAS = {
    "data": "Data",
    "sentimento": "Classificação",
    "veiculo": "Veículo",
    "tier": "Aegea Tier",
    "engajamento": "Engajamento",
    "cargo": "Cargo",
}


def _planilha(linhas: list[list[object]]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    aba.append(_CABECALHO)
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


@pytest.fixture
def par(sessao) -> tuple[ScoreFonte, ScoreFonte]:
    """O espelho e o recorte, irmãos pelo mesmo `arquivo`.

    FONTES PRÓPRIAS, e não `clipei`/`clipei_investidores`: estas rodam dentro de
    uma transação que volta atrás, e mexer nas de produção faria o teste
    depender da ordem em que a suíte roda. O desenho é o mesmo — mesmo arquivo,
    mesma aba, mesmas colunas, e só uma delas recortando.
    """
    base = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert base is not None
    espelho = ScoreFonte(
        codigo="zz_espelho",
        nome="Espelho de teste",
        fornecedor="Clipei",
        lente_id=base.lente_id,
        ordem=98,
        mapeamento_colunas={"aba": "Clipping", "arquivo": "zz", "colunas": _COLUNAS},
    )
    recorte = ScoreFonte(
        codigo="zz_recorte",
        nome="Recorte de teste",
        fornecedor="Clipei",
        lente_id=base.lente_id,
        ordem=99,
        mapeamento_colunas={
            "aba": "Clipping",
            "arquivo": "zz",
            "colunas": _COLUNAS,
            "lista_de_veiculos": "imprensa_economica",
        },
    )
    sessao.add_all([espelho, recorte])
    sessao.flush()
    return espelho, recorte


def _marcar(sessao: Session, nome: str) -> Instituicao:
    """Cadastra o veículo já na lista do mercado."""
    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            CategoriaPublico.nome == "Imprensa",
            SubcategoriaPublico.nome == "Econômica e de negócios",
        )
    )
    assert alvo is not None
    feito = Instituicao(
        nome=nome,
        nome_normalizado=normalizar(nome),
        tipo="veiculo",
        subcategoria_publico_id=alvo,
    )
    sessao.add(feito)
    sessao.flush()
    return feito


def _quantas(sessao, fonte: ScoreFonte, mes: date | None = None) -> int:
    consulta = select(func.count()).select_from(Mencao).where(Mencao.fonte_id == fonte.id)
    if mes is not None:
        consulta = consulta.where(Mencao.mes == mes)
    return int(sessao.scalar(consulta) or 0)


def _agregado(sessao, fonte: ScoreFonte) -> dict[tuple, tuple]:
    linhas = sessao.execute(
        select(
            ScoreMesFonte.mes,
            ScoreMesFonte.sentimento,
            ScoreMesFonte.tier,
            ScoreMesFonte.mencoes,
            ScoreMesFonte.soma_log,
            ScoreMesFonte.soma_engajamento,
            ScoreMesFonte.soma_cargo,
        ).where(ScoreMesFonte.fonte_id == fonte.id)
    ).all()
    return {
        (linha.mes, linha.sentimento, linha.tier): (
            linha.mencoes,
            float(linha.soma_log),
            linha.soma_engajamento,
            float(linha.soma_cargo),
        )
        for linha in linhas
    }


#: TIERS, ENGAJAMENTOS E CARGOS DIFERENTES, para o agregado ter o que somar: o
#: grão de `score_mes_fonte` é (mês, sentimento, tier), e as três somas vêm de
#: engajamento e cargo. Com tudo nulo, a comparação entre a reconciliação e a
#: resubida seria entre duas linhas de zeros.
_DOIS_MESES = [
    [date(2026, 8, 3), "Positiva", "Valor Econômico zz90", "Muito relevante", 120, "Imprensa"],
    [date(2026, 8, 4), "Negativa", "Valor Econômico zz90", "Relevante", 7, "Jornalista"],
    [date(2026, 8, 5), "Positiva", "Valor Econômico zz90", "Relevante", 0, None],
    [date(2026, 9, 5), "Positiva", "Valor Econômico zz90", "Muito relevante", 45, "Imprensa"],
    [date(2026, 8, 6), "Positiva", "Jornal do Bairro zz90", "Relevante", 3, "Imprensa"],
]


def _subir(sessao, espelho: ScoreFonte) -> None:
    """A subida real, pelas duas fontes — é `ingerir` que grava as irmãs."""
    ingerir_mencoes.ingerir(sessao, espelho, _planilha(_DOIS_MESES))


# ============================================================ o sentido de ENTRAR
def test_classificar_faz_o_veiculo_entrar_em_TODOS_os_meses_ja_ingeridos(sessao, par):
    """O pedido, na letra: "todos seus registros devem ser movidos".

    DOIS MESES de propósito: a primeira versão que eu imaginei reconciliava só o
    mês mais recente, e isso parece certo em qualquer teste de um mês só.
    """
    espelho, recorte = par
    _subir(sessao, espelho)
    #: O veículo NÃO estava classificado quando a planilha subiu.
    assert _quantas(sessao, recorte) == 0
    assert _quantas(sessao, espelho) == 5

    _marcar(sessao, "Valor Econômico zz90")
    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    assert _quantas(sessao, recorte, date(2026, 8, 1)) == 3
    assert _quantas(sessao, recorte, date(2026, 9, 1)) == 1
    #: E o que NÃO está na lista continua fora.
    veiculos = set(
        sessao.scalars(select(Mencao.veiculo).where(Mencao.fonte_id == recorte.id))
    )
    assert veiculos == {"Valor Econômico zz90"}


def test_o_AGREGADO_reconciliado_e_igual_ao_que_a_subida_escreveria(sessao, par):
    """O teste que impede a SEGUNDA definição de "o que é um mês no banco".

    O agregado (`score_mes_fonte`) é de onde toda régua tira o número. A
    ingestão o escreve a partir das linhas da planilha, com `somar`; a
    reconciliação o escreve a partir das linhas do banco, com a MESMA `somar`.
    Se os dois caminhos divergirem, a lente passa a valer uma coisa depois da
    reconciliação e outra depois da próxima subida — e ninguém veria, porque os
    dois números são plausíveis.

    O TESTE COMPARA OS DOIS DE VERDADE: reconcilia, guarda o agregado, resobe a
    MESMA planilha com a MESMA lista (agora a ingestão recorta sozinha) e exige
    igualdade.
    """
    espelho, recorte = par
    _subir(sessao, espelho)
    _marcar(sessao, "Valor Econômico zz90")

    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)
    pela_reconciliacao = _agregado(sessao, recorte)
    assert pela_reconciliacao, "a reconciliação não escreveu agregado nenhum"
    #: E AS SOMAS NÃO SÃO TRIVIAIS: sem isto, um dia em que a planilha de teste
    #: perdesse o engajamento e o cargo, a igualdade abaixo passaria a comparar
    #: duas linhas de zeros — e o teste pararia de proteger as três somas sem
    #: ninguém notar.
    assert any(soma_log > 0 for _, soma_log, _, _ in pela_reconciliacao.values())
    assert any(cargo > 0 for *_, cargo in pela_reconciliacao.values())

    #: A MESMA planilha, de novo — agora a lista já existe, então a ingestão
    #: recorta por conta própria.
    _subir(sessao, espelho)
    pela_subida = _agregado(sessao, recorte)

    assert pela_reconciliacao == pela_subida


def test_a_RESPOSTA_do_aplicar_descreve_o_estado_DEPOIS(sessao, par):
    """Nenhum mês volta com `mudou=True` de uma aplicação bem-sucedida.

    ACHADO ALTO DE REVISÃO. A primeira versão devolvia a medida de ANTES, com
    `mudou=True` nos meses que ela acabara de reescrever. A tela pergunta "ainda
    há desvio?" para decidir se mostra o aviso — e continuava mostrando o aviso e
    o botão depois de aplicar com sucesso.

    O QUE FOI FEITO fica em `entram`/`saem`, que são a única coisa que só a
    medida de antes sabe dizer.
    """
    espelho, recorte = par
    _subir(sessao, espelho)
    _marcar(sessao, "Valor Econômico zz90")

    depois = reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    assert depois.aplicada is True
    assert depois.meses_que_mudam == ()
    assert [v.nome for v in depois.entram] == ["Valor Econômico zz90"]
    #: E OS NÚMEROS DOS MESES SÃO OS DE AGORA: `antes` e `depois` iguais, porque
    #: o mês já foi reescrito.
    assert all(mes.antes == mes.depois for mes in depois.meses)


def test_a_RECONCILIACAO_e_IDEMPOTENTE(sessao, par):
    #: Rodar duas vezes não muda nada — e a segunda não deve nem tocar nos meses,
    #: porque nenhum mudou.
    espelho, recorte = par
    _subir(sessao, espelho)
    _marcar(sessao, "Valor Econômico zz90")

    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)
    depois_da_primeira = _agregado(sessao, recorte)

    segunda = reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    assert segunda.meses_que_mudam == ()
    assert _agregado(sessao, recorte) == depois_da_primeira


def test_o_mes_em_que_UM_SAI_e_OUTRO_ENTRA_na_mesma_conta(sessao, par):
    """O defeito que a contagem por mês escondia.

    A primeira versão decidia quais meses reescrever comparando o TOTAL do mês.
    Aqui um veículo de 2 menções sai da lista e outro de 2 entra, no mesmo mês:
    antes = 2, depois = 2, e o mês ficava intacto — com as menções do veículo que
    já não pertence à lente. Nada daria sinal, e a nota do mês seguiria apoiada
    em matéria que o cadastro diz não ser de mercado.

    A comparação verdadeira é entre os CONJUNTOS de veículos do mês.
    """
    espelho, recorte = par
    sai = _marcar(sessao, "Sai da lista zz92")
    ingerir_mencoes.ingerir(
        sessao,
        espelho,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Sai da lista zz92"],
                [date(2026, 8, 4), "Positiva", "Sai da lista zz92"],
                [date(2026, 8, 5), "Negativa", "Entra na lista zz92"],
                [date(2026, 8, 6), "Negativa", "Entra na lista zz92"],
            ]
        ),
    )
    assert _quantas(sessao, recorte) == 2

    #: A troca: um sai do cadastro da lista, o outro entra.
    sai.subcategoria_publico_id = None
    _marcar(sessao, "Entra na lista zz92")
    sessao.flush()

    previa = reconciliar_lista_de_veiculos.previa(sessao, recorte)
    #: O TOTAL DO MÊS NÃO MUDA — e mesmo assim o mês tem de ser reescrito.
    mes = next(m for m in previa.meses if m.mes == date(2026, 8, 1))
    assert (mes.antes, mes.depois) == (2, 2)
    assert mes.mudou is True

    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    veiculos = set(
        sessao.scalars(select(Mencao.veiculo).where(Mencao.fonte_id == recorte.id))
    )
    assert veiculos == {"Entra na lista zz92"}


# ============================================================== o sentido de SAIR
def test_DESclassificar_tira_as_mencoes_da_lente(sessao, par):
    """O sentido inverso, por decisão do dono do produto (19/10/2026).

    "A lente é sempre o espelho do cadastro" é uma regra só, e explicável. O
    preço é que a nota de um mês pode CAIR por causa de uma correção de cadastro
    — e é por isso que a prévia existe.
    """
    espelho, recorte = par
    veiculo = _marcar(sessao, "Valor Econômico zz90")
    _subir(sessao, espelho)
    assert _quantas(sessao, recorte) == 4

    #: Tirar a classificação é exatamente o que a tela de cadastro faz.
    veiculo.subcategoria_publico_id = None
    sessao.flush()
    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    assert _quantas(sessao, recorte) == 0
    #: E O AGREGADO SOME JUNTO. Deixá-lo para trás faria a lente continuar com
    #: denominador de menções que não existem mais — a nota do mês seguiria de
    #: pé, apoiada em nada.
    assert _agregado(sessao, recorte) == {}


def test_o_veiculo_DESATIVADO_tambem_sai(sessao, par):
    #: `ativo=false` já tira o veículo de `nomes_da_lista`; a reconciliação herda
    #: essa regra de graça, e este teste é o que garante que ela não foi
    #: reimplementada aqui.
    espelho, recorte = par
    veiculo = _marcar(sessao, "Valor Econômico zz90")
    _subir(sessao, espelho)
    assert _quantas(sessao, recorte) == 4

    veiculo.ativo = False
    sessao.flush()
    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    assert _quantas(sessao, recorte) == 0


# ===================================================================== a prévia
def test_a_PREVIA_nao_escreve_e_diz_quem_entra(sessao, par):
    espelho, recorte = par
    _subir(sessao, espelho)
    _marcar(sessao, "Valor Econômico zz90")

    previa = reconciliar_lista_de_veiculos.previa(sessao, recorte)

    assert previa.aplicada is False
    assert [(v.nome, v.mencoes) for v in previa.entram] == [("Valor Econômico zz90", 4)]
    assert previa.saem == ()
    assert [(m.mes, m.antes, m.depois) for m in previa.meses_que_mudam] == [
        (date(2026, 8, 1), 0, 3),
        (date(2026, 9, 1), 0, 1),
    ]
    #: E NADA FOI ESCRITO: é a razão de a prévia existir.
    assert _quantas(sessao, recorte) == 0


def test_a_PREVIA_diz_quem_SAI(sessao, par):
    espelho, recorte = par
    veiculo = _marcar(sessao, "Valor Econômico zz90")
    _subir(sessao, espelho)

    veiculo.subcategoria_publico_id = None
    sessao.flush()
    previa = reconciliar_lista_de_veiculos.previa(sessao, recorte)

    assert [(v.nome, v.mencoes) for v in previa.saem] == [("Valor Econômico zz90", 4)]
    assert previa.entram == ()
    assert _quantas(sessao, recorte) == 4


# ================================================= o casamento, igual ao da subida
def test_o_casamento_e_NORMALIZADO_como_o_da_subida(sessao, par):
    """Acento e caixa não tiram ninguém da lente.

    A ingestão casa por `normalizar(veiculo) in nomes_da_lista`. Se a
    reconciliação comparasse texto cru, "VALOR ECONOMICO ZZ91" na planilha e
    "Valor Econômico zz91" no cadastro seriam veículos diferentes — foi o que
    aconteceu na primeira versão da `0066`, que casou 78 de 81 por usar
    `lower()`.
    """
    espelho, recorte = par
    ingerir_mencoes.ingerir(
        sessao,
        espelho,
        _planilha([[date(2026, 8, 3), "Positiva", "VALOR ECONOMICO ZZ91"]]),
    )
    _marcar(sessao, "Valor Econômico zz91")

    reconciliar_lista_de_veiculos.aplicar(sessao, recorte)

    assert _quantas(sessao, recorte) == 1


# ======================================================== as guardas de cadastro
def test_fonte_que_NAO_recorta_e_recusada(sessao, par):
    espelho, _ = par

    with pytest.raises(RegraViolada, match="não recorta"):
        reconciliar_lista_de_veiculos.previa(sessao, espelho)


def test_fonte_SEM_espelho_e_recusada(sessao):
    """Sem irmã não há de onde copiar, e isso é cadastro de fonte, não dado."""
    base = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    sozinha = ScoreFonte(
        codigo="zz_sozinha",
        nome="Recorte sem espelho",
        fornecedor="Clipei",
        lente_id=base.lente_id,
        ordem=97,
        mapeamento_colunas={
            "aba": "Clipping",
            "arquivo": "zz_sozinho",
            "colunas": _COLUNAS,
            "lista_de_veiculos": "imprensa_economica",
        },
    )
    sessao.add(sozinha)
    sessao.flush()

    with pytest.raises(RegraViolada, match="irmã"):
        reconciliar_lista_de_veiculos.previa(sessao, sozinha)


def test_a_fonte_do_mercado_de_PRODUCAO_e_encontrada_pela_lista(sessao):
    """A descoberta funciona na configuração real, e não só nas fontes de teste.

    Sem isto, tudo acima provaria que o motor funciona num par que eu mesmo
    montei — e o par que importa é `clipei`/`clipei_investidores`, que vem das
    migrations.
    """
    fontes = reconciliar_lista_de_veiculos.fontes_que_recortam(sessao)

    assert [f.codigo for f in fontes] == ["clipei_investidores"]
    assert (
        reconciliar_lista_de_veiculos.espelho_de(sessao, fontes[0]).codigo == "clipei"
    )
