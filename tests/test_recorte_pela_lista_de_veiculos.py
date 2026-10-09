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
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import Descarte, Mapeamento, ler_planilha
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


def test_linha_sem_veiculo_nao_entra():
    #: Não há como afirmar que ela é de um veículo de mercado, e supor que é
    #: inventaria menção na lente.
    leitura = ler_planilha(
        [{"Data": date(2026, 8, 3), "Classificação": "Positiva", "Veículo": None}],
        Mapeamento.de_json(MAPEAMENTO_COM_LISTA),
        lambda veiculo: bool(veiculo) and normalizar(veiculo) in {"valor economico"},
    )

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

    previsoes, _reconhecimento = ingerir_mencoes.conferir(
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
