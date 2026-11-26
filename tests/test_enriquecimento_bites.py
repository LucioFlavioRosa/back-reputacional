"""A Bites ganha Cargo/N3 que ela não manda, só onde vier em branco.

Ver o cabeçalho de `app/casos_de_uso/enriquecimento_bites.py` para a decisão
de produto (26/11/2026): o que dá pra resolver com confiança, só com o que a
própria Bites manda, entra direto — sem aprovação manual no meio. O que não
dá fica em branco até a Bites mandar mais dado ou alguém complementar o
catálogo (`cargo_de_conta`, `migrations/0122`).

O QUE ESTES TESTES PROTEGEM, além do comportamento novo: que NADA do que já
funciona pra Bites quebra — célula que a Bites já manda preenchida nunca é
sobrescrita, e uma fonte que não seja a Bites nunca passa por aqui.
"""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import CargoDeConta, Mencao, ScoreFonte
from app.casos_de_uso import enriquecimento_bites, ingerir_mencoes
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


def _planilha(cabecalho: list[str], linhas: list[list]) -> bytes:
    livro = openpyxl.Workbook()
    aba = livro.active
    aba.title = "Planilha1"
    aba.append(cabecalho)
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _ler(conteudo: bytes) -> tuple[list[str], list[list]]:
    aba = openpyxl.load_workbook(io.BytesIO(conteudo)).active
    linhas = list(aba.iter_rows(values_only=True))
    return list(linhas[0]), [list(linha) for linha in linhas[1:]]


# =============================================================================
# `classificar_linha` — puro, sem banco.
# =============================================================================


def test_sem_atributo_nao_classifica():
    assert enriquecimento_bites.classificar_linha(None, "abastecimento", "falta de agua") == (
        "",
        "",
        "",
    )


def test_resolve_por_categoria():
    #: "fatura" só tem candidatos sob um N2 só (Faturamento e cobrança) — sem
    #: texto pra desempatar entre os três N3 dela, o método fica no nível do
    #: meio, que é o resultado honesto: sabe-se o tema, não o subtema exato.
    n2, n3, metodo = enriquecimento_bites.classificar_linha(
        "Eficiência Operacional e Qualidade", "fatura", None
    )
    assert metodo == "ambiguo_entre_subtemas_do_mesmo_n2"
    assert n2 == "Faturamento e cobrança"
    assert n3 == ""


def test_resolve_por_categoria_e_texto_juntos():
    n2, n3, metodo = enriquecimento_bites.classificar_linha(
        "Eficiência Operacional e Qualidade", "fatura", "cobranca abusiva na conta"
    )
    assert metodo == "categoria+texto"
    assert n3 == "Conta errada, Tarifa abusiva"
    assert n2 == "Faturamento e cobrança"


def test_resolve_por_texto():
    n2, n3, metodo = enriquecimento_bites.classificar_linha(
        "Eficiência Operacional e Qualidade", None, "estamos sem agua ha dois dias"
    )
    assert metodo == "texto"
    assert n3 == "Frequência, Continuidade"


def test_sem_match_fica_em_branco():
    n2, n3, metodo = enriquecimento_bites.classificar_linha(
        "Eficiência Operacional e Qualidade", None, "bom dia pessoal, tudo bem?"
    )
    assert metodo == "sem_match"
    assert n3 == ""


def test_categoria_fora_do_pilar_nao_conta():
    #: "fatura" não é candidato nenhum sob o pilar Governança — o filtro de
    #: pilar é rígido, e a categoria de outro pilar não pode vazar pra cá.
    n2, n3, metodo = enriquecimento_bites.classificar_linha(
        "Governança", "fatura", "conta errada, cobranca abusiva"
    )
    assert n3 != "Conta errada, Tarifa abusiva"


# =============================================================================
# `enriquecer_planilha_bites` — com banco, mas só a tabela nova.
# =============================================================================

_CABECALHO = [
    "Data",
    "Autor",
    "Cargo",
    "Rede social",
    "Estado",
    "Atributo",
    "Sentimento",
    "Unidades/Empresas",
    "Categoria",
    "Texto",
    "Engajamento",
]


def _linha(autor="", cargo="", atributo="", categoria="", texto="") -> list:
    return [
        date(2026, 11, 3),
        autor,
        cargo,
        "Twitter",
        "",
        atributo,
        "Positivo",
        "Corsan",
        categoria,
        texto,
        10,
    ]


def test_preenche_cargo_de_conta_conhecida(sessao):
    sessao.add(
        CargoDeConta(autor_normalizado="contaconhecida", autor="ContaConhecida", cargo="Imprensa")
    )
    sessao.flush()

    conteudo = _planilha(_CABECALHO, [_linha(autor="@ContaConhecida")])
    saida = enriquecimento_bites.enriquecer_planilha_bites(sessao, conteudo)

    cabecalho, linhas = _ler(saida)
    assert linhas[0][cabecalho.index("Cargo")] == "Imprensa"


def test_conta_desconhecida_fica_em_branco(sessao):
    conteudo = _planilha(_CABECALHO, [_linha(autor="@NuncaFoiJulgada")])
    saida = enriquecimento_bites.enriquecer_planilha_bites(sessao, conteudo)

    cabecalho, linhas = _ler(saida)
    assert not linhas[0][cabecalho.index("Cargo")]


def test_nunca_sobrescreve_cargo_que_a_bites_ja_mandou(sessao):
    sessao.add(
        CargoDeConta(autor_normalizado="contaconhecida", autor="ContaConhecida", cargo="Imprensa")
    )
    sessao.flush()

    conteudo = _planilha(_CABECALHO, [_linha(autor="@ContaConhecida", cargo="Vereador")])
    saida = enriquecimento_bites.enriquecer_planilha_bites(sessao, conteudo)

    cabecalho, linhas = _ler(saida)
    assert linhas[0][cabecalho.index("Cargo")] == "Vereador"


def test_cria_a_coluna_n3_quando_nao_existe_e_preenche_por_texto(sessao):
    cabecalho_sem_n3 = _CABECALHO  # nenhuma linha "N3" aqui, de propósito
    conteudo = _planilha(
        cabecalho_sem_n3,
        [
            _linha(
                atributo="Eficiência Operacional e Qualidade",
                texto="moradores reclamam de falta de agua na regiao",
            )
        ],
    )
    saida = enriquecimento_bites.enriquecer_planilha_bites(sessao, conteudo)

    cabecalho, linhas = _ler(saida)
    assert "N3" in cabecalho
    assert linhas[0][cabecalho.index("N3")] == "Frequência, Continuidade"


def test_nunca_sobrescreve_n3_que_a_bites_ja_mandou(sessao):
    cabecalho = _CABECALHO + ["N3"]
    linha = _linha(atributo="Eficiência Operacional e Qualidade", texto="falta de agua")
    conteudo = _planilha(cabecalho, [linha + ["Potabilidade"]])
    saida = enriquecimento_bites.enriquecer_planilha_bites(sessao, conteudo)

    cabecalho_saida, linhas = _ler(saida)
    assert linhas[0][cabecalho_saida.index("N3")] == "Potabilidade"


def test_n3_sem_match_fica_em_branco(sessao):
    conteudo = _planilha(
        _CABECALHO,
        [_linha(atributo="Eficiência Operacional e Qualidade", texto="bom dia a todos")],
    )
    saida = enriquecimento_bites.enriquecer_planilha_bites(sessao, conteudo)

    cabecalho, linhas = _ler(saida)
    assert not linhas[0][cabecalho.index("N3")]


# =============================================================================
# Fim a fim: `ingerir_mencoes.ingerir` já enriquecido, pra fonte bites.
# =============================================================================


def test_subida_da_bites_grava_cargo_e_tema_resolvidos_sozinhos(sessao, bites):
    sessao.add(
        CargoDeConta(autor_normalizado="contaconhecida", autor="ContaConhecida", cargo="Imprensa")
    )
    sessao.flush()

    conteudo = _planilha(
        _CABECALHO,
        [
            _linha(
                autor="@ContaConhecida",
                atributo="Eficiência Operacional e Qualidade",
                texto="moradores reclamam de falta de agua na regiao",
            )
        ],
    )
    resumos = ingerir_mencoes.ingerir(sessao, bites, conteudo)

    assert resumos[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 11, 1))
    )
    assert gravada.perfil_autor == "Imprensa"
    assert gravada.tema_id is not None


def test_subida_da_bites_sem_match_sobe_em_branco_igual_antes(sessao, bites):
    linha = _linha(
        autor="@ContaNuncaVista",
        atributo="Eficiência Operacional e Qualidade",
        texto="bom dia",
    )
    conteudo = _planilha(_CABECALHO, [linha])
    resumos = ingerir_mencoes.ingerir(sessao, bites, conteudo)

    assert resumos[0].ingeridas == 1
    gravada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 11, 1))
    )
    assert gravada.perfil_autor is None
    assert gravada.tema_id is None
