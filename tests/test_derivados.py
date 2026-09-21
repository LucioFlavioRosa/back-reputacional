"""As derivações de `app/banco/derivados.py`, e os espelhos em SQL.

Roda contra o banco de teste, dentro de uma transação desfeita ao final.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.derivados import (
    SQL_PARES_DA_0044,
    derivar_o_que_falta,
    formato_das_interacoes_pela_frente,
    tier_das_instituicoes_pelas_agendas,
)
from app.banco.repositorio_interacoes import RepositorioSQL
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_catalogo import FormatoInteracao
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.frentes import FORMATO_PADRAO_DA_FRENTE, Frente
from app.dominio.interacao import Interacao

# Reaproveita o banco de teste que `test_e2e_postgres` cria e migra.
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)
MIGRATIONS = Path(__file__).resolve().parents[1] / "app/banco/migrations"


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
def autor(sessao):
    sufixo = uuid4().hex[:8]
    usuario = Usuario(
        entra_object_id=f"derivados-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome="Autor de teste",
        acesso_irrestrito=True,
    )
    sessao.add(usuario)
    sessao.flush()
    return usuario


def _instituicao(sessao, nome: str, tipo: str, tier: int | None = None) -> Instituicao:
    registro = Instituicao(nome=nome, nome_normalizado=nome.lower(), tipo=tipo, tier=tier)
    sessao.add(registro)
    sessao.flush()
    return registro


def _agenda(sessao, autor, instituicao, frente: Frente, **ajustes) -> Interacao:
    criada = RepositorioSQL(sessao).adicionar(
        Interacao(
            frente=frente,
            data_interacao=date(2026, 5, 7),
            instituicao_id=instituicao.id,
            uf="SP",
            status="confirmada",
            pauta="derivados",
            criado_por=autor.id,
            **ajustes,
        )
    )
    sessao.flush()
    return criada


def test_tier_da_instituicao_e_a_moda_das_agendas_e_nao_toca_quem_ja_tem(sessao, autor):
    sem_tier = _instituicao(sessao, "Sem Tier", "orgao")
    com_tier = _instituicao(sessao, "Com Tier", "orgao", tier=4)
    for t in (2, 1, 2):
        _agenda(sessao, autor, sem_tier, Frente.GOVERNO, tier=t)
    for t in (1, 1, 1):
        _agenda(sessao, autor, com_tier, Frente.GOVERNO, tier=t)

    assert tier_das_instituicoes_pelas_agendas(sessao) >= 1
    sessao.expire_all()
    assert sessao.get(Instituicao, sem_tier.id).tier == 2, "a moda das agendas"
    assert sessao.get(Instituicao, com_tier.id).tier == 4, "quem ja tinha nao e tocado"
    assert tier_das_instituicoes_pelas_agendas(sessao) == 0, "idempotente"


def test_empate_de_tier_desempata_pelo_mais_relevante(sessao, autor):
    empate = _instituicao(sessao, "Empate", "orgao")
    for t in (3, 1):
        _agenda(sessao, autor, empate, Frente.GOVERNO, tier=t)
    tier_das_instituicoes_pelas_agendas(sessao)
    sessao.expire_all()
    assert sessao.get(Instituicao, empate.id).tier == 1


def test_formato_da_interacao_segue_a_frente_so_onde_falta(sessao, autor):
    veiculo = _instituicao(sessao, "Veiculo X", "veiculo")
    reuniao = sessao.scalar(
        select(FormatoInteracao.id).where(FormatoInteracao.codigo == "reuniao")
    )
    sem_formato = _agenda(sessao, autor, veiculo, Frente.IMPRENSA, tier=1)
    com_formato = _agenda(
        sessao, autor, veiculo, Frente.IMPRENSA, tier=1, formato_interacao_id=reuniao
    )

    assert formato_das_interacoes_pela_frente(sessao) >= 1
    sessao.expire_all()
    midia = sessao.scalar(select(FormatoInteracao.id).where(FormatoInteracao.codigo == "midia"))
    assert sessao.get(InteracaoRegistro, sem_formato.id).formato_interacao_id == midia
    assert sessao.get(InteracaoRegistro, com_formato.id).formato_interacao_id == reuniao
    assert formato_das_interacoes_pela_frente(sessao) == 0, "idempotente"


def test_derivar_o_que_falta_devolve_as_tres_contagens(sessao):
    resultado = derivar_o_que_falta(sessao)
    assert set(resultado) == {
        "tier_de_instituicao",
        "categoria_de_instituicao",
        "formato_de_interacao",
    }


def test_a_0044_espelha_o_mapa_do_dominio():
    """Os dois espelhos — SQL para o banco existente, Python para a base
    semeada — precisam dizer a mesma coisa, par a par, e cobrir toda frente."""
    sql = (MIGRATIONS / "0044_formato_da_interacao_pela_frente.sql").read_text(encoding="utf-8")
    pares = dict(re.findall(r"when '([a-z_]+)'\s+then '([a-z_]+)'", sql))
    assert pares == dict(SQL_PARES_DA_0044)
    assert set(FORMATO_PADRAO_DA_FRENTE) == set(Frente), "toda frente tem formato padrao"
