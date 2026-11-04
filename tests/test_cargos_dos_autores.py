"""O "Tracking dos cargos dos autores" contra o Postgres: o agrupamento e a rota.

O MOLDE É O EXPLORADOR DE VEÍCULOS (`test_explorador_de_veiculos.py`), e a
invariante é a mesma: a soma dos pesos de todas as linhas tem de ser o
denominador do mês — é isso que faz o impacto de cada cargo e de cada autor
fechar com a nota.

O QUE SÓ O BANCO PROVA é o agrupamento por `(perfil_autor, autor)`, que a
menção sem cargo volta (com cargo nulo) em vez de sumir, e que, numa lente
cujo autor é do diretório, quem não o vê recebe os cargos sem nome nenhum.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco import repositorio_score
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.erros import NaoEncontrado
from app.dominio.score import peso_da_mencao, peso_do_cargo, peso_do_engajamento
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: UM MÊS LONGE DE TUDO, para nenhuma semente do banco de teste entrar na conta.
MES = date(2031, 6, 1)
TEXTO_DO_MES = "2031-06"

SEM_FILTRO = dict(
    tier=None,
    veiculo=None,
    atributo=None,
    tema=None,
    perfil_autor=None,
    uf=None,
    subtema=None,
    autor=None,
    empresa=None,
    tema_n1=None,
    tema_n2=None,
    tema_n3=None,
    sentimento=None,
)


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
    administra_dicionarios: bool = False
    ve_diretorio: bool = True


def _gravar(sessao, linhas: list[dict]) -> None:
    """Grava as menções da Bites E o agregado do mês, como a ingestão faria —
    o denominador sai do agregado, e a invariante precisa dele."""
    fonte = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    grao: Counter[tuple[str, str | None]] = Counter()
    for linha in linhas:
        sessao.add(Mencao(fonte_id=fonte.id, mes=MES, **linha))
        grao[(linha["sentimento"], linha.get("cargo"))] += 1
    por_sentimento: Counter[str] = Counter()
    soma_cargo: Counter[str] = Counter()
    for (sentimento, cargo), quantas in grao.items():
        por_sentimento[sentimento] += quantas
        soma_cargo[sentimento] += quantas * peso_do_cargo(cargo)
    for sentimento, quantas in por_sentimento.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=fonte.id,
                mes=MES,
                sentimento=sentimento,
                tier="",
                mencoes=quantas,
                soma_log=quantas * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=soma_cargo[sentimento],
            )
        )
    sessao.flush()


def _linhas() -> list[dict]:
    """Sete menções: dois vereadores, um deputado e duas sem cargo."""
    vereador = {"perfil_autor": "Vereador", "cargo": "vereador"}
    deputado = {"perfil_autor": "Deputado estadual", "cargo": "deputado_estadual"}
    return [
        {**vereador, "autor": "@iriel", "sentimento": "neg", "link": "https://x.com/iriel/1"},
        {**vereador, "autor": "@iriel", "sentimento": "neg", "link": "https://x.com/iriel/2"},
        {**vereador, "autor": "@ana", "sentimento": "pos"},
        {**deputado, "autor": "@joao", "sentimento": "neu"},
        {**deputado, "autor": "@joao", "sentimento": "pos", "uf": "Rio de Janeiro"},
        {"autor": "@cidadao", "sentimento": "neg"},
        {"autor": None, "sentimento": "pos"},
    ]


def _cargos(sessao, codigo: str = "sociedade", quem: _QuemOlha | None = None, **filtro):
    from app.api.lentes import obter_cargos_dos_autores

    parametros = dict(SEM_FILTRO)
    parametros.update(filtro)
    return obter_cargos_dos_autores(
        sessao=sessao, usuario=quem or _QuemOlha(), codigo=codigo, mes=TEXTO_DO_MES, **parametros
    )


def test_os_grupos_saem_por_cargo_e_autor_e_fecham_com_o_denominador(sessao):
    _gravar(sessao, _linhas())

    saida = _cargos(sessao)

    assert saida.lente == "sociedade" and saida.mes == TEXTO_DO_MES
    assert saida.ve_autores is True
    #: AS SETE MENÇÕES INTEIRAS, inclusive as duas sem cargo.
    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == 7
    #: A INVARIANTE DO MOLDE: a soma dos pesos é o denominador do mês.
    pesos = sum(g.peso_positivo + g.peso_neutro + g.peso_negativo for g in saida.grupos)
    assert pesos == pytest.approx(saida.denominador)

    pares = {(g.cargo, g.autor) for g in saida.grupos}
    assert pares == {
        ("Vereador", "@iriel"),
        ("Vereador", "@ana"),
        ("Deputado estadual", "@joao"),
        (None, "@cidadao"),
        (None, None),
    }
    #: UMA LINHA POR PAR DE VERDADE — um `set` não conta repetição.
    assert len(saida.grupos) == len(pares)

    iriel = next(g for g in saida.grupos if g.autor == "@iriel")
    assert iriel.negativo == 2 and iriel.positivo == 0
    assert iriel.peso_negativo > 0 and iriel.peso_positivo == 0


def test_o_peso_de_cada_grupo_e_o_da_regua_vigente(sessao):
    """O impacto de um autor é o peso das menções dele na régua do mês — a
    mesma `peso_da_mencao` que fecha a nota. Comparar contra a função, e não só
    a soma, é o que pega um `cargo` que não chegasse ao cálculo."""
    _gravar(sessao, _linhas())

    saida = _cargos(sessao)
    lente = sessao.scalars(select(Lente).where(Lente.codigo == "sociedade")).one()
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, _ = repositorio_score.denominador_do_mes(sessao, lente.id, MES, calibracao)

    cargo_por_rotulo = {"Vereador": "vereador", "Deputado estadual": "deputado_estadual"}
    for grupo in saida.grupos:
        esperado = peso_da_mencao(
            None, cargo_por_rotulo.get(grupo.cargo), None, calibracao, regua
        ) * (grupo.positivo + grupo.neutro + grupo.negativo)
        soma = grupo.peso_positivo + grupo.peso_neutro + grupo.peso_negativo
        assert soma == pytest.approx(esperado), f"peso errado em {grupo.cargo}/{grupo.autor}"


def test_na_sociedade_o_autor_e_aberto_a_todos(sessao):
    """O @ da Sociedade é o perfil que veio DENTRO da menção, não o cadastro de
    terceiros — `nomeia_o_diretorio("sociedade")` é falso, e o KPI "Autor mais
    negativo" já o mostra a todos. Quem não vê o diretório vê os @ aqui também."""
    _gravar(sessao, _linhas())

    saida = _cargos(sessao, quem=_QuemOlha(ve_diretorio=False))

    assert saida.ve_autores is True
    assert any(g.autor == "@iriel" for g in saida.grupos)


@pytest.fixture
def lente_que_nomeia_o_diretorio(monkeypatch):
    """Uma lente cujo autor É do diretório, como a Imprensa — para provar a
    guarda sem depender de qual lente a declara hoje."""
    monkeypatch.setattr("app.api.lentes.a_lente_nomeia_o_diretorio", lambda codigo: True)


@pytest.mark.usefixtures("lente_que_nomeia_o_diretorio")
def test_quem_nao_ve_o_diretorio_recebe_os_cargos_sem_autor(sessao):
    _gravar(sessao, _linhas())

    saida = _cargos(sessao, quem=_QuemOlha(ve_diretorio=False))

    assert saida.ve_autores is False
    assert all(g.autor is None for g in saida.grupos)
    #: OS DOIS VEREADORES VIRAM UMA LINHA: nem o nome, nem quantos autores
    #: distintos há por trás da barra.
    assert [g.cargo for g in saida.grupos].count("Vereador") == 1
    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == 7


@pytest.mark.usefixtures("lente_que_nomeia_o_diretorio")
def test_quem_nao_ve_o_diretorio_nao_filtra_por_autor(sessao):
    """Filtrar por autor e ler a contagem revelaria se ele existe."""
    _gravar(sessao, _linhas())

    saida = _cargos(sessao, quem=_QuemOlha(ve_diretorio=False), autor="@iriel")

    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == 7


def test_a_rota_segue_o_filtro_da_tela(sessao):
    _gravar(sessao, _linhas())

    saida = _cargos(sessao, uf="Rio de Janeiro")

    assert [(g.cargo, g.autor, g.positivo) for g in saida.grupos] == [
        ("Deputado estadual", "@joao", 1)
    ]


def test_a_lente_que_le_o_crm_responde_vazia_sem_erro(sessao):
    saida = _cargos(sessao, codigo="institucional")

    assert saida.grupos == [] and saida.denominador == 0


def test_a_lente_que_nao_existe_da_404(sessao):
    with pytest.raises(NaoEncontrado):
        _cargos(sessao, codigo="nao-existe")
