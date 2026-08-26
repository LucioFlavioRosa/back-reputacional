"""As invariantes do agregado. Nenhum caminho grava um registro inválido."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    Frente,
    Imprensa,
    Institucional,
    Interna,
    Legislativo,
)
from app.dominio.identidade import Escopo, Papel, Perfil, UsuarioAtual
from app.dominio.interacao import (
    PAPEL_EQUIPE,
    PAPEL_PORTA_VOZ,
    Interacao,
    ParticipacaoAegea,
)
from app.dominio.politica import pode_editar


def nova(**ajustes) -> Interacao:
    padroes = dict(
        frente=Frente.IMPRENSA,
        data_interacao=date(2026, 5, 7),
        instituicao_id=uuid4(),
        uf="SP",
        status="atendido",
        pauta="Reajuste tarifário em concessões",
    )
    return Interacao(**{**padroes, **ajustes})


# -- invariantes -------------------------------------------------------------


def test_pauta_vazia_e_recusada():
    with pytest.raises(RegraViolada, match="pauta é obrigatória"):
        nova(pauta="   ")


def test_uf_e_obrigatoria_e_validada():
    with pytest.raises(RegraViolada, match="Abrangência inválida"):
        nova(uf="ZZ")


def test_uf_aceita_nacional_e_internacional():
    assert nova(uf="NA").uf == "NA"
    assert nova(uf="IN").uf == "IN"


def test_tier_fora_da_faixa_e_recusado():
    with pytest.raises(RegraViolada, match="Tier inválido"):
        nova(tier=9)


def test_extensao_precisa_corresponder_a_frente():
    with pytest.raises(RegraViolada, match="espera dados de"):
        nova(frente=Frente.GOVERNO, extensao=Imprensa(formato="entrevista_online"))


def test_governo_parceiros_e_eventos_compartilham_a_mesma_extensao():
    for frente in (Frente.GOVERNO, Frente.PARCEIROS, Frente.EVENTOS):
        interacao = nova(frente=frente, extensao=Institucional(natureza_orgao="executivo"))
        assert isinstance(interacao.extensao, Institucional)


def test_data_de_publicacao_anterior_ao_atendimento_e_recusada():
    with pytest.raises(RegraViolada, match="anterior à data"):
        Imprensa(data_atendida=date(2026, 5, 10), data_publicacao=date(2026, 5, 1))


def test_prioridade_legislativa_invalida_e_recusada():
    with pytest.raises(RegraViolada, match="Prioridade inválida"):
        Legislativo(prioridade="urgentissima")


def test_complexidade_interna_invalida_e_recusada():
    with pytest.raises(RegraViolada, match="Complexidade inválido"):
        Interna(complexidade="altissima")


def test_prazo_negativo_e_recusado():
    with pytest.raises(RegraViolada, match="não pode ser negativo"):
        Interna(prazo_dias=-3)


# -- porta-vozes -------------------------------------------------------------


def test_uma_interacao_pode_ter_varios_porta_vozes():
    radames, andre = uuid4(), uuid4()
    interacao = nova(
        participacoes=(
            ParticipacaoAegea(radames, PAPEL_PORTA_VOZ),
            ParticipacaoAegea(andre, PAPEL_PORTA_VOZ),
        )
    )
    assert interacao.porta_vozes == (radames, andre)


def test_equipe_nao_entra_na_lista_de_porta_vozes():
    porta_voz, apoio = uuid4(), uuid4()
    interacao = nova(
        participacoes=(
            ParticipacaoAegea(porta_voz, PAPEL_PORTA_VOZ),
            ParticipacaoAegea(apoio, PAPEL_EQUIPE),
        )
    )
    assert interacao.porta_vozes == (porta_voz,)


def test_mesma_pessoa_duas_vezes_no_mesmo_papel_e_recusada():
    pessoa = uuid4()
    with pytest.raises(RegraViolada, match="duas vezes no mesmo papel"):
        nova(
            participacoes=(
                ParticipacaoAegea(pessoa, PAPEL_PORTA_VOZ),
                ParticipacaoAegea(pessoa, PAPEL_PORTA_VOZ),
            )
        )


def test_mesma_pessoa_em_papeis_diferentes_e_permitida():
    pessoa = uuid4()
    interacao = nova(
        participacoes=(
            ParticipacaoAegea(pessoa, PAPEL_PORTA_VOZ),
            ParticipacaoAegea(pessoa, PAPEL_EQUIPE),
        )
    )
    assert len(interacao.participacoes) == 2


def test_papel_desconhecido_e_recusado():
    with pytest.raises(RegraViolada, match="Papel inválido"):
        ParticipacaoAegea(uuid4(), "assessor")


# -- edição ------------------------------------------------------------------


def test_alterar_revalida_o_agregado():
    interacao = nova()
    with pytest.raises(RegraViolada, match="Abrangência inválida"):
        interacao.alterar(uf="ZZ")


def test_alterar_campo_inexistente_e_recusado():
    interacao = nova()
    with pytest.raises(RegraViolada, match="não editável"):
        interacao.alterar(inventado="x")


def test_campos_de_auditoria_nao_sao_editaveis():
    interacao = nova()
    with pytest.raises(RegraViolada, match="não editável"):
        interacao.alterar(criado_por=uuid4())


def test_trocar_de_frente_exige_extensao_compativel():
    interacao = nova(extensao=Imprensa(formato="entrevista_online"))
    with pytest.raises(RegraViolada, match="espera dados de"):
        interacao.alterar(frente=Frente.LEGISLATIVO)


def test_dias_parada_alimenta_a_fila_de_pendencias():
    interacao = nova(data_interacao=date(2026, 6, 1))
    assert interacao.dias_parada(hoje=date(2026, 8, 24)) == 84


# -- permissões --------------------------------------------------------------


#: Espelham as linhas semeadas pela migration 0003. Ficam aqui, e nao numa
#: fixture de banco, porque estes testes sao de dominio puro: a politica so
#: precisa das bandeiras, nao de onde elas foram lidas.
PAPEIS = {
    Perfil.ANALISTA: Papel(
        codigo="analista", nome="Analista",
        pode_criar=True, pode_editar_proprio=True,
        ve_campos_sensiveis=True, ve_diretorio=True, pode_exportar=True,
    ),
    Perfil.COORDENACAO: Papel(
        codigo="coordenacao", nome="Coordenacao",
        pode_criar=True, pode_editar_proprio=True, pode_editar_tudo=True,
        administra_dicionarios=True, administra_acessos=True,
        ve_campos_sensiveis=True, ve_diretorio=True, pode_exportar=True,
    ),
    Perfil.DIRETORIA: Papel(
        codigo="diretoria", nome="Diretoria",
        ve_campos_sensiveis=True, ve_diretorio=True, pode_exportar=True,
    ),
    Perfil.EXTERNO: Papel(codigo="externo", nome="Externo"),
}


def usuario(perfil: Perfil, id_=None, escopo: Escopo | None = None) -> UsuarioAtual:
    return UsuarioAtual(
        id=id_ or uuid4(),
        nome="Fulano",
        email="f@aegea.com.br",
        papel=PAPEIS[perfil],
        escopo=escopo or Escopo.total(),
    )


def test_analista_edita_o_que_criou():
    autor = usuario(Perfil.ANALISTA)
    interacao = nova(criado_por=autor.id)
    assert pode_editar(autor, interacao)


def test_analista_nao_edita_registro_alheio():
    autor = usuario(Perfil.ANALISTA)
    outro = usuario(Perfil.ANALISTA)
    interacao = nova(criado_por=autor.id)
    assert not pode_editar(outro, interacao)


def test_coordenacao_edita_tudo():
    interacao = nova(criado_por=uuid4())
    assert pode_editar(usuario(Perfil.COORDENACAO), interacao)


def test_diretoria_nao_edita_nada():
    diretoria = usuario(Perfil.DIRETORIA)
    interacao = nova(criado_por=diretoria.id)
    assert not pode_editar(diretoria, interacao)
    assert diretoria.somente_leitura
