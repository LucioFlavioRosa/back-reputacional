"""A relevância da instituição some para a interação que não trouxe a dela.

CENÁRIO MEDIDO DE VERDADE (18/11/2026): "Valor Econômico" tem Tier 1 no
cadastro (veio da Clipei), mas as agendas de imprensa importadas pelo CRM
ficaram com Relevância em branco — a planilha de agenda não repetia o Tier
linha a linha. Os testes abaixo usam exatamente esse nome, de propósito: é o
caso real que motivou o script.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.preencher_relevancia_das_interacoes import aplicar, contar_pendentes
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_catalogo import Frente, Relevancia, Status
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    """Uma sessão que se desfaz no fim — nada deste arquivo sobra no banco de
    teste, e o banco de teste em si não é o de desenvolvimento nem o real."""
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def _primeiro_ativo(sessao, tabela):
    return sessao.scalars(select(tabela).where(tabela.ativo.is_(True)).limit(1)).first()


def _usuario_de_teste(sessao):
    sufixo = uuid.uuid4().hex[:8]
    autor = Usuario(
        entra_object_id=f"teste-relevancia-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome="Analista de teste",
        acesso_irrestrito=True,
    )
    sessao.add(autor)
    sessao.flush()
    return autor


def _nova_interacao(sessao, instituicao_id, autor_id, *, tier=None):
    frente = _primeiro_ativo(sessao, Frente)
    status = _primeiro_ativo(sessao, Status)
    interacao = InteracaoRegistro(
        frente_id=frente.id,
        data_interacao=date(2026, 5, 20),
        instituicao_id=instituicao_id,
        uf="SP",
        status_id=status.id,
        tier=tier,
        criado_por=autor_id,
    )
    sessao.add(interacao)
    sessao.flush()
    return interacao


def test_conta_so_quem_esta_sem_relevancia_e_a_instituicao_tem(sessao):
    autor = _usuario_de_teste(sessao)
    tier_1 = sessao.scalars(select(Relevancia.id)).first()

    com_tier = Instituicao(
        nome="Valor Econômico", nome_normalizado=normalizar("Valor Econômico"),
        tipo="veiculo", uf="SP", tier=tier_1,
    )
    sem_tier = Instituicao(
        nome="Veículo Sem Tier", nome_normalizado=normalizar("Veículo Sem Tier"),
        tipo="veiculo", uf="SP",
    )
    sessao.add_all([com_tier, sem_tier])
    sessao.flush()

    # PENDENTE: instituição com tier, interação sem.
    _nova_interacao(sessao, com_tier.id, autor.id, tier=None)
    # JÁ CERTA: as duas já têm — não deveria entrar na conta.
    _nova_interacao(sessao, com_tier.id, autor.id, tier=tier_1)
    # NÃO DÁ PARA CORRIGIR: a instituição também não tem tier.
    _nova_interacao(sessao, sem_tier.id, autor.id, tier=None)

    assert contar_pendentes(sessao) == 1


def test_aplicar_copia_o_tier_da_instituicao_e_nunca_sobrescreve(sessao):
    autor = _usuario_de_teste(sessao)
    tier_1 = sessao.scalars(select(Relevancia.id)).first()
    tier_2 = sessao.scalars(select(Relevancia.id).where(Relevancia.id != tier_1)).first()

    instituicao = Instituicao(
        nome="Valor Econômico", nome_normalizado=normalizar("Valor Econômico"),
        tipo="veiculo", uf="SP", tier=tier_1,
    )
    sessao.add(instituicao)
    sessao.flush()

    pendente = _nova_interacao(sessao, instituicao.id, autor.id, tier=None)
    # JÁ TINHA UMA RELEVÂNCIA PRÓPRIA, diferente da instituição — não pode virar a da instituição.
    tinha_a_propria = _nova_interacao(sessao, instituicao.id, autor.id, tier=tier_2)

    corrigidas = aplicar(sessao)
    assert corrigidas == 1

    sessao.refresh(pendente)
    sessao.refresh(tinha_a_propria)
    assert pendente.tier == tier_1
    assert tinha_a_propria.tier == tier_2  # intocada


def test_idempotente_a_segunda_execucao_nao_corrige_nada(sessao):
    autor = _usuario_de_teste(sessao)
    tier_1 = sessao.scalars(select(Relevancia.id)).first()
    instituicao = Instituicao(
        nome="Valor Econômico", nome_normalizado=normalizar("Valor Econômico"),
        tipo="veiculo", uf="SP", tier=tier_1,
    )
    sessao.add(instituicao)
    sessao.flush()
    _nova_interacao(sessao, instituicao.id, autor.id, tier=None)

    primeira = aplicar(sessao)
    segunda = aplicar(sessao)

    assert primeira == 1
    assert segunda == 0
    assert contar_pendentes(sessao) == 0
