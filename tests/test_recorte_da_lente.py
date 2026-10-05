"""O nível 3 do pacote: o recorte que o drawer abre quando alguém clica num dado.

O DONO DO PRODUTO FOI DIRETO AO PONTO: "ao clicar em um dado temos que abrir um
modal com o deep diving, e não como é feito hoje". Hoje o clique aplica o recorte
na TELA INTEIRA — a nota muda, os painéis se refazem, e quem clicou perde de
vista o mês de onde saiu. É recortar, não aprofundar.

E É O QUE O PACOTE ESPECIFICA (FRONTEND §4): drawer à direita, trilha interna
`Lente › dim: valor`, e cinco partes — a frase com o impacto, a barra de
composição, o histórico do recorte, as sub-dimensões ainda não usadas (clicar
EMPILHA, descendo um nível no mesmo painel) e os itens.

UM PEDIDO SÓ, e é por isso que este arquivo prova o endpoint inteiro de uma vez:
o drawer abre com tudo ou abre mentindo. Cinco chamadas dariam cinco estados de
carregamento dentro de um painel de 600px.

O IMPACTO É A REGRA CENTRAL DO PACOTE:

    impacto(S) = 50 × Σ(sinal × peso de S) ÷ Σ(peso de TODOS os itens do mês)

O denominador é o do MÊS, nunca o do recorte — é o que faz a soma dos impactos
de todos os valores de uma dimensão fechar em `nota − 50`. Um denominador local
daria a cada pedaço o seu próprio 100%, e nada fecharia com nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.lentes import MESES_DA_EVOLUCAO, obter_recorte
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.score import peso_do_cargo, peso_do_engajamento
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

MES = date(2026, 6, 1)


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


#: DEZ MENÇÕES, DUAS UFs, DOIS PERFIS — o mínimo para que o recorte por UF tenha
#: o que decompor por dentro. O Rio é o pedaço ruim (3 negativas de 4) e São
#: Paulo o bom: é a forma do mês real, em miniatura.
LINHAS = [
    # uf, perfil, autor, sentimento
    ("RJ", "Figura pública", "@deputado", "neg"),
    ("RJ", "Cidadão", "@vizinho", "neg"),
    ("RJ", "Cidadão", "@vizinho", "neg"),
    ("RJ", "Cidadão", "@outro", "pos"),
    ("SP", "Figura pública", "@vereadora", "pos"),
    ("SP", "Cidadão", "@fulano", "pos"),
]


@pytest.fixture
def sociedade_de_junho(sessao):
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    for uf, perfil, autor, sentimento in LINHAS:
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=MES,
                sentimento=sentimento,
                uf=uf,
                perfil_autor=perfil,
                autor=autor,
                veiculo="Instagram",
                tema_texto="Abastecimento",
                unidade_texto="Águas do Rio" if uf == "RJ" else "Aegea Holding",
            )
        )
    por_sentimento: dict[str, int] = {}
    for _uf, _perfil, _autor, sentimento in LINHAS:
        por_sentimento[sentimento] = por_sentimento.get(sentimento, 0) + 1
    for sentimento, quantas in por_sentimento.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=bites.id,
                mes=MES,
                sentimento=sentimento,
                tier="",
                mencoes=quantas,
                soma_log=quantas * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=quantas * peso_do_cargo(None),
            )
        )
    sessao.flush()
    return LINHAS


def _recorte(sessao, **filtro):
    return obter_recorte(
        sessao=sessao, usuario=_QuemOlha(), codigo="sociedade", mes="2026-06", **filtro
    )


# =============================================================================
# o que o drawer mostra no topo
# =============================================================================


def test_o_recorte_diz_o_caminho_que_levou_ate_ele(sessao, sociedade_de_junho):
    """A TRILHA É O QUE IMPEDE O DRAWER DE SER UM BECO. Sem ela, quem desceu dois
    níveis não sabe de onde veio nem o que remover para subir um."""
    recorte = _recorte(sessao, uf="RJ", perfil_autor="Cidadão")

    assert [(passo.dimensao, passo.valor) for passo in recorte.trilha] == [
        ("Perfil de quem fala", "Cidadão"),
        ("UF", "RJ"),
    ]


def test_o_recorte_conta_os_itens_dele_e_os_do_mes(sessao, sociedade_de_junho):
    """OS DOIS NÚMEROS JUNTOS, e não só o do recorte: "3 itens" não diz nada;
    "3 dos 6 itens do mês" diz que isto é metade do mês."""
    recorte = _recorte(sessao, uf="RJ")

    assert recorte.itens == 4
    assert recorte.itens_no_mes == 6
    assert recorte.composicao["negativo"] == 3
    assert recorte.composicao["positivo"] == 1


def test_o_IMPACTO_usa_o_denominador_do_MES(sessao, sociedade_de_junho):
    """A REGRA CENTRAL DO PACOTE. O Rio tem 3 negativas e 1 positiva em 6 itens
    do mês: impacto = 50 × (1 − 3) ÷ 6 = −16,67 pontos."""
    recorte = _recorte(sessao, uf="RJ")

    assert round(recorte.impacto, 2) == -16.67


def test_a_soma_dos_impactos_de_uma_dimensao_FECHA_com_a_nota(sessao, sociedade_de_junho):
    """É O QUE TORNA O NÚMERO AUDITÁVEL, e é a propriedade que o pacote cobra em
    todos os níveis: a nota do mês é 50 mais a soma do que cada pedaço tira ou
    põe. Um impacto com denominador local daria a cada pedaço o seu próprio
    100%, e a tela mostraria pedaços que não somam o todo."""
    do_rio = _recorte(sessao, uf="RJ").impacto
    de_sp = _recorte(sessao, uf="SP").impacto

    #: 4 positivas e ... — a nota do mês inteiro, sem recorte nenhum.
    inteiro = _recorte(sessao)

    assert round(do_rio + de_sp, 6) == round(inteiro.impacto, 6)
    assert round(50 + do_rio + de_sp) == inteiro.nota


def test_o_recorte_vazio_nao_devolve_o_mes_inteiro(sessao, sociedade_de_junho):
    """O MESMO CUIDADO DO DOSSIÊ: um recorte sem correspondência tem de dizer
    "nenhum item", e não cair no mês como se o filtro não existisse."""
    vazio = _recorte(sessao, uf="AC")

    assert vazio.itens == 0
    assert vazio.impacto == 0
    assert vazio.ausencia


# =============================================================================
# o histórico e o que há dentro
# =============================================================================


def test_o_historico_do_recorte_tem_um_mes_por_celula(sessao, sociedade_de_junho):
    """UMA CÉLULA POR MÊS DO PERÍODO (FRONTEND §4.3): o mesmo recorte medido mês a
    mês. É o que responde "isto é de agora ou é sempre assim" — a pergunta que
    decide se o pedaço merece ação.

    OITO, E NÃO OS SEIS DO PACOTE, e a divergência é deliberada: `MESES_DA_EVOLUÇÃO`
    é oito nesta aplicação, e o gráfico de evolução da lente está na mesma tela que
    abriu o drawer. Dois históricos do mesmo mês com comprimentos diferentes, lado
    a lado, fazem quem compara os dois concluir que um deles está errado."""
    recorte = _recorte(sessao, uf="RJ")

    assert len(recorte.historico) == MESES_DA_EVOLUCAO
    deste_mes = recorte.historico[-1]
    assert deste_mes["mes"] == "2026-06"
    assert deste_mes["itens"] == 4
    #: OS MESES SEM BASE VÊM MARCADOS, e não como zero: zero se lê como "o mês
    #: foi neutro", quando o que houve foi não haver menção nenhuma.
    assert recorte.historico[0]["sem_base"] is True


def test_DENTRO_do_recorte_vem_as_dimensoes_que_AINDA_NAO_foram_usadas(sessao, sociedade_de_junho):
    """A PARTE 4 DO PACOTE, e a regra é a que faz o empilhamento ter fim: dentro
    de "UF: RJ" não se oferece UF de novo. Oferecer repetiria a mesma pergunta e
    daria uma única barra de 100%."""
    recorte = _recorte(sessao, uf="RJ")

    chaves = [bloco.recorta for bloco in recorte.dentro]
    assert "uf" not in chaves
    assert "perfil_autor" in chaves
    #: E AS LINHAS SÃO AS DE DENTRO DO RECORTE: no Rio há 3 cidadãos, não os 4
    #: do mês inteiro.
    do_perfil = next(b for b in recorte.dentro if b.recorta == "perfil_autor")
    cidadaos = next(linha for linha in do_perfil.dados if linha["rotulo"] == "Cidadão")
    assert cidadaos["negativo"] + cidadaos["positivo"] == 3


def test_os_ITENS_do_recorte_sao_os_do_recorte(sessao, sociedade_de_junho):
    """A PARTE 5: a lista que fecha a descida. Sem ela o drawer para no número e
    quem precisa agir não vê o que foi dito."""
    recorte = _recorte(sessao, uf="RJ")

    assert recorte.itens_do_recorte.tipo == "tabela"
    assert recorte.itens_do_recorte.colunas


def test_sem_recorte_o_endpoint_responde_o_MES(sessao, sociedade_de_junho):
    """O drawer dos cartões do topo ("maior detrator") abre sem dimensão
    escolhida, e o pacote prevê isso. Trilha vazia, impacto do mês inteiro."""
    inteiro = _recorte(sessao)

    assert inteiro.trilha == []
    assert inteiro.itens == 6
    assert inteiro.itens_no_mes == 6
