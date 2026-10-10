"""O perfil de rede aponta para a pessoa do CRM — o que cruza as fontes.

O QUE ISTO HABILITA. A lente de redes sabe que `stelafariasrs` falou 27 vezes, e
o CRM sabe que a deputada Stela Farias tem agendas. Sem o vínculo, as duas
metades não se falam, e "o que este ator disse e fez em todos os canais" não é
uma pergunta respondível.

A CARDINALIDADE DECIDIU ONDE A CHAVE MORA: um perfil é de no máximo UMA pessoa,
e uma pessoa tem VÁRIOS perfis — 54 dos 1.173 autores da Bites aparecem em mais
de uma rede. Então a chave fica no perfil, apontando para a pessoa.

E NÃO PELO `interlocutor.redes_sociais`, que era o plano. Ligar por casamento de
string repetiria o que esta base já mostrou duas vezes: `mencao.tema_texto` com
25.909 textos e ZERO vínculos, `unidade_texto` com 58% dos nomes fora do
cadastro. Texto como ligação apodrece.

O QUE ESTES TESTES PROTEGEM:

* só perfil de rede tem pessoa — um jornal não é "de" alguém, e a recusa fala
  de cadastro, não de constraint;
* uma pessoa pode ter vários perfis, que é o caso real das duas redes;
* apagar a pessoa do CRM não apaga o perfil nem as menções dele.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor
from app.dominio.texto import normalizar
from main import app
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
def cliente(sessao):
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": "plataforma_edicao"}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    feito = TestClient(app)
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


def _perfil(sessao, nome: str) -> Instituicao:
    feito = Instituicao(
        nome=nome, nome_normalizado=normalizar(nome), tipo="perfil_rede"
    )
    sessao.add(feito)
    sessao.flush()
    return feito


def _pessoa(sessao, nome: str) -> Interlocutor:
    feita = Interlocutor(nome=nome, nome_normalizado=normalizar(nome))
    sessao.add(feita)
    sessao.flush()
    return feita


def test_o_perfil_aponta_para_a_pessoa(cliente, sessao):
    perfil = _perfil(sessao, "stelafariasrs zz1")
    pessoa = _pessoa(sessao, "Stela Farias zz1")

    resposta = cliente.put(
        f"/api/instituicoes/{perfil.id}",
        json={
            "nome": perfil.nome,
            "tipo": "perfil_rede",
            "interlocutor_id": str(pessoa.id),
            "ativo": True,
        },
    )

    assert resposta.status_code == 200, resposta.text
    sessao.expire_all()
    assert sessao.get(Instituicao, perfil.id).interlocutor_id == pessoa.id
    #: E A SAÍDA DA API DIZ, para a tela poder mostrar de quem é cada perfil.
    assert resposta.json()["interlocutor_id"] == str(pessoa.id)


def test_UMA_PESSOA_tem_VARIOS_perfis(cliente, sessao):
    #: O caso real: 54 dos 1.173 autores aparecem em mais de uma rede, e
    #: "Pompeu de Mattos" tem perfil no Instagram E no Facebook.
    pessoa = _pessoa(sessao, "Pompeu de Mattos zz2")
    for nome in ("pompeu.insta zz2", "pompeu.face zz2"):
        perfil = _perfil(sessao, nome)
        resposta = cliente.put(
            f"/api/instituicoes/{perfil.id}",
            json={
                "nome": nome,
                "tipo": "perfil_rede",
                "interlocutor_id": str(pessoa.id),
                "ativo": True,
            },
        )
        assert resposta.status_code == 200, resposta.text

    quantos = sessao.scalars(
        select(Instituicao.nome).where(Instituicao.interlocutor_id == pessoa.id)
    ).all()
    assert sorted(quantos) == ["pompeu.face zz2", "pompeu.insta zz2"]


def test_SO_PERFIL_DE_REDE_tem_pessoa(cliente, sessao):
    #: Um jornal não é "de" uma pessoa. Sem esta recusa, alguém poria o editor
    #: da Folha como dono da Folha — e a pergunta "o que esta pessoa disse"
    #: passaria a trazer a redação inteira.
    veiculo = Instituicao(
        nome="Jornal Qualquer zz3",
        nome_normalizado=normalizar("Jornal Qualquer zz3"),
        tipo="veiculo",
    )
    sessao.add(veiculo)
    pessoa = _pessoa(sessao, "Editor zz3")
    sessao.flush()

    resposta = cliente.put(
        f"/api/instituicoes/{veiculo.id}",
        json={
            "nome": veiculo.nome,
            "tipo": "veiculo",
            "interlocutor_id": str(pessoa.id),
            "ativo": True,
        },
    )

    assert resposta.status_code == 422, resposta.text
    assert "perfil de rede" in resposta.text


def test_o_BANCO_tambem_recusa_pessoa_em_quem_nao_e_perfil(sessao):
    #: A trava da aplicação é a mensagem; a do banco é a garantia. Um script
    #: que escreva direto na tabela não passa pelo `if` da rota.
    veiculo = Instituicao(
        nome="Jornal Qualquer zz4",
        nome_normalizado=normalizar("Jornal Qualquer zz4"),
        tipo="veiculo",
    )
    pessoa = _pessoa(sessao, "Editor zz4")
    sessao.add(veiculo)
    sessao.flush()

    with pytest.raises(Exception, match="instituicao_pessoa_so_de_perfil"):
        sessao.execute(
            text(
                "update instituicao set interlocutor_id = :p where id = :i"
            ),
            {"p": pessoa.id, "i": veiculo.id},
        )
        sessao.flush()


def test_apagar_a_pessoa_NAO_apaga_o_perfil(sessao):
    #: `on delete set null`: o perfil volta a ser anônimo, que é o estado dele
    #: hoje — e as 2.626 menções que apontam para ele continuam de pé.
    perfil = _perfil(sessao, "orfao zz5")
    pessoa = _pessoa(sessao, "Alguem zz5")
    perfil.interlocutor_id = pessoa.id
    sessao.flush()

    sessao.delete(pessoa)
    sessao.flush()
    sessao.expire_all()

    sobrou = sessao.get(Instituicao, perfil.id)
    assert sobrou is not None
    assert sobrou.interlocutor_id is None
