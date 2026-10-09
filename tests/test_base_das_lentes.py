"""A Base de dados das lentes: as menções na fonte, para consulta."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.base_das_lentes import listar_mencoes, opcoes_da_base
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.dominio.erros import NaoEncontrado, RegraViolada
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


def _listar(sessao, ve_diretorio=True, **params):
    padrao = dict(
        de=date(2026, 7, 1), ate=date(2026, 8, 31), q=None, fonte=None, sentimento=None,
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        pagina=1, tamanho=50, ordenacao="-data",
    )
    padrao.update(params)
    return listar_mencoes(
        sessao=sessao, usuario=_QuemOlha(ve_diretorio), codigo="imprensa", **padrao
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
