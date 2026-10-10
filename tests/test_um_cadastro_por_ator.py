"""Um cadastro só para o mesmo ator.

O QUE O DONO DO PRODUTO DECIDIU. "O Valor Econômico é uma empresa grande que
está na base de imprensa; caso tenhamos Valor Econômico no CRM, empresa e rede
social, vamos consultar o mesmo perfil?" — "deveria ser um único cadastro que
vem de Cadastro compartilhado".

A ingestão já respeita isso (`reconhecer` procura em qualquer tipo quando quem
fala é perfil de rede). O que estes testes protegem é a limpeza do que a versão
antiga gravou — e, principalmente, O QUE A MIGRATION NÃO FAZ:

* o homônimo EXATO funde, e as menções dos dois lados ficam no sobrevivente;
* quem sobrevive é o VEÍCULO, a linha curada, com categoria e nome escrito por
  gente — não o handle do fornecedor;
* a semelhança NÃO funde: `valoreconomico` e `Valor Econômico` só casam depois
  de tirar pontuação, e `Diário SM`/`Diários M` prova que isso erra. Esses
  pares vão para a tela de confirmação;
* perfil ligado a uma pessoa fica de fora: há julgamento humano gravado ali;
* e rodar duas vezes não quebra nem funde a mais.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

SQL = (
    Path(__file__).resolve().parents[1]
    / "app/banco/migrations/0077_um_cadastro_so_para_o_mesmo_ator.sql"
).read_text(encoding="utf-8")


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


def _rodar(sessao) -> None:
    """A migration de verdade, sem o `begin`/`commit` que o fixture já dá."""
    sessao.execute(text(SQL.replace("begin;", "").replace("commit;", "")))
    sessao.expire_all()


def _quantas(sessao, qual) -> int:
    #: POR CONTAGEM: `sessao.get` de uma linha apagada pelo SQL levanta
    #: `ObjectDeletedError` em vez de devolver None.
    return sessao.scalar(
        select(func.count()).select_from(Instituicao).where(Instituicao.id == qual)
    )


def _par(sessao, nome: str, *, nome_do_veiculo: str | None = None):
    perfil = Instituicao(
        nome=nome, nome_normalizado=normalizar(nome), tipo="perfil_rede", cargo="Imprensa"
    )
    veiculo = Instituicao(
        nome=nome_do_veiculo or nome,
        nome_normalizado=normalizar(nome_do_veiculo or nome),
        tipo="veiculo",
    )
    sessao.add_all([perfil, veiculo])
    sessao.flush()
    return perfil, veiculo


def _mencao(sessao, dono: Instituicao, fonte: ScoreFonte) -> None:
    sessao.add(
        Mencao(
            fonte_id=fonte.id,
            mes=date(2026, 8, 1),
            data=date(2026, 8, 3),
            sentimento="neg",
            veiculo=dono.nome,
            instituicao_id=dono.id,
        )
    )
    sessao.flush()


@pytest.fixture
def bites(sessao) -> ScoreFonte:
    return sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))


def test_o_homonimo_EXATO_funde_no_veiculo(sessao, bites):
    perfil, veiculo = _par(sessao, "Valor Zz50")
    _mencao(sessao, perfil, bites)
    _mencao(sessao, veiculo, bites)
    id_do_perfil, id_do_veiculo = perfil.id, veiculo.id

    _rodar(sessao)

    assert _quantas(sessao, id_do_perfil) == 0
    assert _quantas(sessao, id_do_veiculo) == 1
    #: O DOSSIÊ INTEIRO DO ATOR NUM SÓ LUGAR.
    juntas = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.instituicao_id == id_do_veiculo)
    )
    assert juntas == 2


def test_quem_sobrevive_e_o_VEICULO_com_o_nome_dele(sessao):
    #: O fornecedor escreve `exame`; quem cadastrou escreveu `Exame`. O nome que
    #: fica é o da linha curada.
    perfil = Instituicao(
        nome="exame zz51", nome_normalizado=normalizar("exame zz51"), tipo="perfil_rede"
    )
    veiculo = Instituicao(
        nome="Exame Zz51", nome_normalizado=normalizar("exame zz51"), tipo="veiculo"
    )
    sessao.add_all([perfil, veiculo])
    sessao.flush()
    id_do_veiculo = veiculo.id

    _rodar(sessao)

    sobreviveu = sessao.scalar(select(Instituicao).where(Instituicao.id == id_do_veiculo))
    assert sobreviveu.nome == "Exame Zz51"
    assert sobreviveu.tipo == "veiculo"


def test_a_SEMELHANCA_nao_funde(sessao):
    """`Diário SM` e `Diários M` casam sem pontuação, e não são o mesmo ator.

    Fundir por semelhança juntaria dossiês de atores diferentes, e isso não tem
    volta. Esses pares vão para a tela de confirmação.
    """
    perfil, veiculo = _par(sessao, "valorzz52", nome_do_veiculo="Valor Zz52")
    id_do_perfil = perfil.id

    _rodar(sessao)

    assert _quantas(sessao, id_do_perfil) == 1
    assert _quantas(sessao, veiculo.id) == 1


def test_o_perfil_LIGADO_A_PESSOA_fica_de_fora(sessao):
    pessoa = Interlocutor(nome="Fulano Zz53", nome_normalizado=normalizar("Fulano Zz53"))
    sessao.add(pessoa)
    sessao.flush()
    perfil, _veiculo = _par(sessao, "Jornal Zz53")
    perfil.interlocutor_id = pessoa.id
    sessao.flush()
    id_do_perfil = perfil.id

    _rodar(sessao)

    #: HÁ JULGAMENTO HUMANO GRAVADO ALI, e o veículo não pode herdar a ligação
    #: (CHECK `instituicao_pessoa_so_de_perfil`).
    assert _quantas(sessao, id_do_perfil) == 1


def test_rodar_DUAS_VEZES_nao_quebra(sessao, bites):
    perfil, veiculo = _par(sessao, "Diario Zz54")
    _mencao(sessao, perfil, bites)
    id_do_perfil, id_do_veiculo = perfil.id, veiculo.id

    _rodar(sessao)
    _rodar(sessao)

    assert _quantas(sessao, id_do_perfil) == 0
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.instituicao_id == id_do_veiculo)
        )
        == 1
    )
