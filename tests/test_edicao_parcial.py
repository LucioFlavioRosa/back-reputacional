"""O PATCH: o que ele altera, o que preserva e o que se recusa a fazer.

A regressão que estes testes travam: trocar entre Governo, Parceiros e Eventos
apagava a extensão `Institucional`, mesmo com os dados continuando válidos —
as três frentes compartilham exatamente os mesmos campos extras.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    Frente,
    Institucional,
)
from app.dominio.interacao import Interacao
from app.esquemas.interacoes import InteracaoEdicao


def institucional(frente: Frente) -> Interacao:
    return Interacao(
        frente=frente,
        data_interacao=date(2026, 4, 8),
        instituicao_id=uuid4(),
        uf="DF",
        status="atendido",
        pauta="Impacto de insumos e reequilíbrio contratual",
        extensao=Institucional(
            natureza_orgao="executivo", cargo_interlocutor="Secretário"
        ),
    )


# -- o que o PATCH preserva --------------------------------------------------


@pytest.mark.parametrize(
    ("de", "para"),
    [
        (Frente.GOVERNO, Frente.PARCEIROS),
        (Frente.PARCEIROS, Frente.EVENTOS),
        (Frente.EVENTOS, Frente.GOVERNO),
    ],
)
def test_trocar_entre_frentes_da_mesma_extensao_preserva_os_dados(de, para):
    interacao = institucional(de)
    alteracoes = InteracaoEdicao(frente=para).alteracoes(frente_atual=de)

    # A extensão nem entra nas alterações: o que já estava lá continua válido.
    assert "extensao" not in alteracoes

    interacao.alterar(**alteracoes)
    assert interacao.frente is para
    assert interacao.extensao == Institucional(
        natureza_orgao="executivo", cargo_interlocutor="Secretário"
    )


def test_editar_sem_tocar_na_frente_nao_mexe_na_extensao():
    interacao = institucional(Frente.GOVERNO)
    alteracoes = InteracaoEdicao(relato="Reunião remarcada").alteracoes(
        frente_atual=Frente.GOVERNO
    )

    assert alteracoes == {"relato": "Reunião remarcada"}
    interacao.alterar(**alteracoes)
    assert interacao.extensao is not None


# -- o que o PATCH recusa ----------------------------------------------------


def test_trocar_para_frente_de_outra_extensao_exige_decisao_explicita():
    with pytest.raises(RegraViolada, match="Envie `extensao`"):
        InteracaoEdicao(frente=Frente.LEGISLATIVO).alteracoes(
            frente_atual=Frente.GOVERNO
        )


def test_descartar_a_extensao_antiga_e_permitido_quando_explicito():
    interacao = institucional(Frente.GOVERNO)
    alteracoes = InteracaoEdicao(
        frente=Frente.LEGISLATIVO, extensao=None
    ).alteracoes(frente_atual=Frente.GOVERNO)

    assert alteracoes["extensao"] is None
    interacao.alterar(**alteracoes)
    assert interacao.frente is Frente.LEGISLATIVO
    assert interacao.extensao is None


def test_trocar_de_frente_com_extensao_nova_e_aceito():
    interacao = institucional(Frente.GOVERNO)
    edicao = InteracaoEdicao.model_validate(
        {"frente": "legislativo", "extensao": {"casa": "senado_federal", "prioridade": "alta"}}
    )
    alteracoes = edicao.alteracoes(frente_atual=Frente.GOVERNO)

    interacao.alterar(**alteracoes)
    assert interacao.frente is Frente.LEGISLATIVO
    assert interacao.extensao.casa == "senado_federal"


# -- campos parciais ---------------------------------------------------------


def test_apenas_o_que_foi_enviado_entra_nas_alteracoes():
    edicao = InteracaoEdicao.model_validate({"tier": 1})
    assert edicao.alteracoes(frente_atual=Frente.IMPRENSA) == {"tier": 1}


def test_null_explicito_limpa_o_campo():
    edicao = InteracaoEdicao.model_validate({"relato": None})
    assert edicao.alteracoes(frente_atual=Frente.IMPRENSA) == {"relato": None}


def test_uf_e_normalizada_para_maiuscula():
    edicao = InteracaoEdicao.model_validate({"uf": "sp"})
    assert edicao.alteracoes(frente_atual=Frente.IMPRENSA) == {"uf": "SP"}


def test_campo_desconhecido_e_recusado_na_fronteira():
    with pytest.raises(ValueError):
        InteracaoEdicao.model_validate({"campo_inventado": 1})
