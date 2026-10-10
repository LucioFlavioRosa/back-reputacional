"""A lente Mercado recortada pela LISTA DE VEÍCULOS do cadastro.

O QUE MUDOU DE LUGAR. `clipei_investidores` recortava o export da Clipei por
`Público-alvo = Investidores`, coluna que o fornecedor preenche pelo critério
dele. Medido contra o export de 08–09/2026: a coluna captura 80 linhas onde a
lista de veículos que a Aegea mantém captura 323, e as duas discordam em 267
das 335 linhas envolvidas — a coluna perde Valor Econômico (49 menções),
InfoMoney (25), Expert XP (20) e Times Brasil (15). Como o Mercado vale 20% do
índice, era um quinto do ISR decidido por quem não é a Aegea.

O QUE ESTES TESTES PROTEGEM:

* o recorte segue a lista, e não a coluna;
* nome casa NORMALIZADO (acento, caixa, espaço) — foi por não normalizar que a
  primeira versão da `0066` marcou 78 de 81;
* linha sem veículo não entra: não há como afirmar que é de mercado;
* a fonte que declara recortar por lista e é lida SEM o predicado falha alto.
  Sem isso, um erro de ligação faria a lente Mercado contar as 25.457 menções
  de Imprensa — o índice subiria sem nenhum sinal de que algo quebrou;
* a CONFERÊNCIA recorta igual à subida: a tela existe para prometer o que vai
  acontecer.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_lentes import MencaoNaoClassificada
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import (
    Descarte,
    Leitura,
    Mapeamento,
    MencaoLida,
    ler_planilha,
)
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


MAPEAMENTO_COM_LISTA = {
    "colunas": {
        "data": "Data",
        "sentimento": "Classificação",
        "veiculo": "Veículo",
    },
    "lista_de_veiculos": "imprensa_economica",
}


def _linha(veiculo: str, sentimento: str = "Positiva") -> dict[str, object]:
    return {"Data": date(2026, 8, 3), "Classificação": sentimento, "Veículo": veiculo}


# -- o motor, sem banco ---------------------------------------------------------


def test_o_recorte_guarda_quem_esta_na_lista():
    mapeamento = Mapeamento.de_json(MAPEAMENTO_COM_LISTA)
    na_lista = {"valor economico"}

    leitura = ler_planilha(
        [_linha("Valor Econômico"), _linha("Jornal do Bairro")],
        mapeamento,
        lambda veiculo: normalizar(veiculo or "") in na_lista,
    )

    assert len(leitura.mencoes) == 1
    assert leitura.mencoes[0].veiculo == "Valor Econômico"
    assert leitura.descartes[Descarte.FORA_DA_LISTA_DE_VEICULOS.value] == 1


def test_o_descarte_tem_motivo_PROPRIO():
    #: E não `fora_do_filtro`: a tela mostra os descartes por motivo, e as duas
    #: causas se consertam em lugares diferentes — filtro de coluna é cadastro
    #: da fonte, lista de veículos é cadastro compartilhado.
    leitura = ler_planilha(
        [_linha("Jornal do Bairro")],
        Mapeamento.de_json(MAPEAMENTO_COM_LISTA),
        lambda _veiculo: False,
    )

    assert leitura.descartes[Descarte.FORA_DA_LISTA_DE_VEICULOS.value] == 1
    assert leitura.descartes[Descarte.FORA_DO_FILTRO.value] == 0


def test_o_motor_pergunta_ao_predicado_tambem_pela_linha_sem_veiculo():
    #: O MOTOR NÃO DECIDE SOZINHO sobre a linha sem veículo: ele pergunta, e
    #: quem responde é `_recorte_por_lista` — testado em
    #: `test_a_linha_SEM_VEICULO_nao_entra_pelo_codigo_de_producao`, que exercita
    #: a guarda de verdade. Aqui só se afirma que a pergunta é feita.
    perguntados: list[str | None] = []

    def anotar(veiculo: str | None) -> bool:
        perguntados.append(veiculo)
        return False

    leitura = ler_planilha(
        [{"Data": date(2026, 8, 3), "Classificação": "Positiva", "Veículo": None}],
        Mapeamento.de_json(MAPEAMENTO_COM_LISTA),
        anotar,
    )

    assert perguntados == [None]
    assert leitura.mencoes == ()
    assert leitura.descartes[Descarte.FORA_DA_LISTA_DE_VEICULOS.value] == 1


def test_ler_sem_o_predicado_FALHA_ALTO():
    #: O contrapeso que importa: sem esta recusa, uma fonte que declara
    #: recortar por lista e é lida sem o predicado traz o arquivo INTEIRO — a
    #: lente Mercado passaria a contar as menções de Imprensa, e o índice
    #: subiria por um erro de ligação sem nenhum sinal.
    with pytest.raises(ValueError, match="veiculo_na_lista"):
        ler_planilha([_linha("Valor Econômico")], Mapeamento.de_json(MAPEAMENTO_COM_LISTA))


def test_fonte_sem_lista_continua_lendo_tudo():
    sem_lista = Mapeamento.de_json(
        {"colunas": MAPEAMENTO_COM_LISTA["colunas"]},
    )

    leitura = ler_planilha([_linha("Valor Econômico"), _linha("Jornal do Bairro")], sem_lista)

    assert len(leitura.mencoes) == 2


def test_lista_que_o_motor_nao_conhece_e_recusada_no_cadastro_da_fonte():
    #: A mensagem tem de falar do CADASTRO, e não da planilha: quem lê "a
    #: planilha não tem a coluna X" vai procurar na planilha um problema que
    #: está no cadastro da fonte.
    with pytest.raises(ValueError, match="lista de veículos que não existe"):
        Mapeamento.de_json(
            {**MAPEAMENTO_COM_LISTA, "lista_de_veiculos": "investidores"},
        )


# -- a lista, lida do cadastro --------------------------------------------------


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


def test_a_lista_sai_do_cadastro_normalizada(sessao):
    _marcar(sessao, "Valor Econômico zz1")

    nomes = nomes_da_lista(sessao, "imprensa_economica")

    #: NORMALIZADO: é assim que nome de veículo se compara em todo o sistema, e
    #: é o que faz "VALOR ECONOMICO" do export casar com o cadastro.
    assert "valor economico zz1" in nomes


def test_veiculo_sem_subcategoria_nao_esta_na_lista(sessao):
    solto = Instituicao(
        nome="Jornal do Bairro zz2",
        nome_normalizado=normalizar("Jornal do Bairro zz2"),
        tipo="veiculo",
    )
    sessao.add(solto)
    sessao.flush()

    assert "jornal do bairro zz2" not in nomes_da_lista(sessao, "imprensa_economica")


def test_VEICULO_DESATIVADO_sai_da_lista(sessao):
    """O achado Médio: desativar no cadastro tinha de tirar da lente.

    `ativo=false` é o gesto de quem administra o cadastro dizendo "este não é um
    veículo corrente". Sem este filtro, a próxima subida continuava contando as
    menções dele no Mercado — e a aba o exibia como membro vivo, sem marca
    nenhuma. Três lugares precisavam concordar e não concordavam.
    """
    desativado = _marcar(sessao, "Jornal aposentado zz30")
    assert normalizar("Jornal aposentado zz30") in nomes_da_lista(
        sessao, "imprensa_economica"
    )

    desativado.ativo = False
    sessao.flush()

    assert normalizar("Jornal aposentado zz30") not in nomes_da_lista(
        sessao, "imprensa_economica"
    )


def test_lista_sem_traducao_para_o_cadastro_e_recusada(sessao):
    with pytest.raises(RegraViolada, match="não tem tradução"):
        nomes_da_lista(sessao, "mercado_de_capitais")


# -- a subida inteira ------------------------------------------------------------


_CABECALHO = ["Data", "Classificação", "Veículo", "Público-alvo"]


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
def fonte_de_mercado(sessao) -> ScoreFonte:
    """Uma fonte que recorta pela lista, no grão em que o banco a guarda."""
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert fonte is not None
    nova = ScoreFonte(
        codigo="zz_mercado",
        nome="Mercado de teste",
        fornecedor="Clipei",
        lente_id=fonte.lente_id,
        ordem=99,
        mapeamento_colunas={
            "aba": "Clipping",
            "colunas": {
                "data": "Data",
                "sentimento": "Classificação",
                "veiculo": "Veículo",
            },
            "lista_de_veiculos": "imprensa_economica",
        },
    )
    sessao.add(nova)
    sessao.flush()
    return nova


def test_a_subida_grava_SO_quem_esta_na_lista(sessao, fonte_de_mercado):
    _marcar(sessao, "Valor Econômico zz3")

    resumo = ingerir_mencoes.ingerir(
        sessao,
        fonte_de_mercado,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz3", "Geral"],
                [date(2026, 8, 4), "Negativa", "Jornal do Bairro zz3", "Investidores"],
            ]
        ),
    )

    assert resumo[0].ingeridas == 1
    #: A SEGUNDA LINHA DIZ `Público-alvo = Investidores` e NÃO entra: é a prova
    #: de que o critério trocou de dono — quem decide é o cadastro, não a
    #: coluna do fornecedor.
    assert resumo[0].descartes[Descarte.FORA_DA_LISTA_DE_VEICULOS.value] == 1
    gravadas = sessao.scalars(
        select(Mencao.veiculo).where(Mencao.fonte_id == fonte_de_mercado.id)
    ).all()
    assert list(gravadas) == ["Valor Econômico zz3"]


def test_a_CONFERENCIA_recorta_igual_a_subida(sessao, fonte_de_mercado):
    #: Se a previsão lesse o arquivo sem a lista, a tela prometeria duas
    #: menções e o banco gravaria uma — e a conferência existe justamente para
    #: prometer o que vai acontecer.
    _marcar(sessao, "Valor Econômico zz4")
    conteudo = _planilha(
        [
            [date(2026, 8, 3), "Positiva", "Valor Econômico zz4", "Geral"],
            [date(2026, 8, 4), "Negativa", "Jornal do Bairro zz4", "Investidores"],
        ]
    )

    previsoes, _veiculos, _assuntos = ingerir_mencoes.conferir(
        sessao, fonte_de_mercado, conteudo
    )
    previsao = next(p for p in previsoes if p.fonte == "zz_mercado")

    assert previsao.ingeridas == 1
    assert previsao.descartes[Descarte.FORA_DA_LISTA_DE_VEICULOS.value] == 1


def test_lista_vazia_recorta_para_zero_sem_derrubar_a_subida(sessao, fonte_de_mercado):
    #: É O ESTADO DA PRIMEIRA SUBIDA numa base onde ninguém classificou veículo
    #: nenhum: o recorte nasce vazio por construção. Derrubar aqui faria a
    #: carga da Clipei inteira falhar — as menções de Imprensa não entrariam
    #: porque o Mercado ficou vazio.
    resumo = ingerir_mencoes.ingerir(
        sessao,
        fonte_de_mercado,
        _planilha([[date(2026, 8, 3), "Positiva", "Veículo sem lista zz5", "Geral"]]),
        veiculos_a_criar=(),
    )

    assert resumo[0].ingeridas == 0


# -- os achados da revisão -------------------------------------------------------


def test_a_linha_SEM_VEICULO_nao_entra_pelo_codigo_de_producao(sessao, fonte_de_mercado):
    """A guarda real, e não a lambda de um teste.

    O QUE A REVISÃO PEGOU: o teste do motor passava um predicado próprio, então
    `if not veiculo: return False` em `_recorte_por_lista` nunca era exercida —
    apagá-la deixava a suíte verde. Aqui a linha sobe de verdade, pelo caminho
    inteiro.
    """
    _marcar(sessao, "Valor Econômico zz10")

    resumo = ingerir_mencoes.ingerir(
        sessao,
        fonte_de_mercado,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz10", "Geral"],
                [date(2026, 8, 4), "Negativa", None, "Investidores"],
            ]
        ),
    )

    assert resumo[0].ingeridas == 1
    assert resumo[0].descartes[Descarte.FORA_DA_LISTA_DE_VEICULOS.value] == 1


def _mencao_antiga(sessao, fonte: ScoreFonte, mes: date) -> None:
    """Uma menção gravada pela régua ANTERIOR, como o banco a tem hoje."""
    sessao.add(
        Mencao(
            fonte_id=fonte.id,
            mes=mes,
            data=mes,
            sentimento="pos",
            veiculo="Veículo do critério antigo",
        )
    )
    sessao.flush()


def test_RESUBIR_ZERA_O_MES_em_que_nenhum_veiculo_da_lista_aparece(
    sessao, fonte_de_mercado
):
    """O achado Alto: o mês não pode ficar com o que a régua antiga gravou.

    CENÁRIO. A lente Mercado tinha agosto gravado pelo critério velho
    (`Público-alvo = Investidores`). Quem opera resobe o arquivo justamente para
    aplicar o critério novo, e naquele mês nenhum veículo da lista é mencionado.
    Antes do conserto, `regravar` apagava por `leitura.meses` — que nasce das
    menções e vinha vazio —, então NADA era apagado: a lente seguia valendo 20%
    do ISR com as linhas do critério aposentado, e nenhuma tela mostrava isso.
    """
    _mencao_antiga(sessao, fonte_de_mercado, date(2026, 8, 1))

    resumo = ingerir_mencoes.ingerir(
        sessao,
        fonte_de_mercado,
        _planilha([[date(2026, 8, 3), "Positiva", "Fora da lista zz11", "Geral"]]),
    )

    assert resumo[0].ingeridas == 0
    #: O MÊS APARECE NO RESUMO, para a tela poder dizer o que substituiu.
    assert resumo[0].meses == (date(2026, 8, 1),)
    #: E A TELA PODE DIZER QUE ENCOLHEU: `antes` é o que havia no mês.
    assert resumo[0].antes == 1
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.fonte_id == fonte_de_mercado.id)
        )
        == 0
    )


def test_RESUBIR_PARCIAL_nao_deixa_um_mes_em_cada_criterio(sessao, fonte_de_mercado):
    """O caso pior do mesmo achado: a série misturando dois critérios.

    Arquivo com agosto E setembro, lista casando só em agosto. Antes do
    conserto, agosto era regravado pelo critério novo e setembro ficava no
    antigo — e a série do Mercado passava a misturar os dois, mês a mês.
    """
    _marcar(sessao, "Valor Econômico zz12")
    _mencao_antiga(sessao, fonte_de_mercado, date(2026, 8, 1))
    _mencao_antiga(sessao, fonte_de_mercado, date(2026, 9, 1))

    ingerir_mencoes.ingerir(
        sessao,
        fonte_de_mercado,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz12", "Geral"],
                [date(2026, 9, 4), "Negativa", "Fora da lista zz12", "Investidores"],
            ]
        ),
    )

    gravadas = sessao.execute(
        select(Mencao.mes, Mencao.veiculo).where(Mencao.fonte_id == fonte_de_mercado.id)
    ).all()
    assert [(m, v) for m, v in gravadas] == [
        (date(2026, 8, 1), "Valor Econômico zz12")
    ]


def test_ARQUIVO_ILEGIVEL_continua_sendo_recusado(sessao, fonte_de_mercado):
    """A outra metade do achado Médio sobre o vazio.

    O recorte explica um vazio; arquivo ilegível não. Aba e cabeçalho certos,
    vocabulário de sentimento que o mapeamento não conhece: nenhuma linha chegou
    a ser candidata, e aceitar com 201 é a falha para a qual a guarda foi
    escrita. Antes do conserto, `pode_vir_vazia` a desligava para toda fonte que
    recorta por lista.
    """
    with pytest.raises(RegraViolada, match="Nenhuma linha da planilha virou menção"):
        ingerir_mencoes.ingerir(
            sessao,
            fonte_de_mercado,
            _planilha([[date(2026, 8, 3), "Mais ou menos", "Valor Econômico zz13", ""]]),
        )


def test_as_NAO_CLASSIFICADAS_sao_as_desta_fonte(sessao, fonte_de_mercado):
    """O achado Médio sobre "houve volume e ninguém classificou".

    O recorte acontece depois de `ler_linha`, então a linha sem sentimento era
    contada para a fonte do Mercado seja de que veículo fosse: a lente passava a
    exibir como sua a não-classificação do clipping INTEIRO.
    """
    _marcar(sessao, "Valor Econômico zz14")

    ingerir_mencoes.ingerir(
        sessao,
        fonte_de_mercado,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz14", "Geral"],
                #: SEM SENTIMENTO e de veículo DA lista: conta.
                [date(2026, 8, 4), "Não informado", "Valor Econômico zz14", "Geral"],
                #: SEM SENTIMENTO e de veículo FORA da lista: não é desta fonte.
                [date(2026, 8, 5), "Não informado", "Jornal do Bairro zz14", "Geral"],
                [date(2026, 8, 6), "Não informado", "Outro jornal zz14", "Geral"],
            ]
        ),
    )

    quantas = sessao.scalar(
        select(MencaoNaoClassificada.total).where(
            MencaoNaoClassificada.fonte_id == fonte_de_mercado.id,
            MencaoNaoClassificada.mes == date(2026, 8, 1),
        )
    )
    assert quantas == 1


def test_REGRAVAR_recusa_leitura_que_nao_foi_recortada(sessao, fonte_de_mercado):
    """O achado Médio do segundo caminho de escrita.

    `carga_do_pacote_das_lentes` monta a `Leitura` à mão e chama `regravar`
    direto, por fora de `ler_planilha` — então a guarda do motor não cobre esse
    caminho. No dia em que a imprensa entrar naquele pacote, a fonte do Mercado
    seria gravada com o clipping inteiro, sem sinal nenhum. A guarda passou a
    morar onde a escrita acontece.
    """
    sem_recorte = Leitura(
        mencoes=(
            MencaoLida(
                mes=date(2026, 8, 1),
                data=date(2026, 8, 3),
                sentimento="pos",
                veiculo="Qualquer um",
            ),
        ),
        descartes={},
        linhas=1,
    )

    with pytest.raises(RegraViolada, match="não foi recortada"):
        ingerir_mencoes.regravar(sessao, fonte_de_mercado, sem_recorte)
