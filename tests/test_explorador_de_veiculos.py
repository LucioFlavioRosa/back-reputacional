"""O Explorador de veículos contra o Postgres: o agrupamento e a rota.

O MOLDE É O EXPLORADOR DE TAXONOMIA (`test_consulta_da_lente.py`), e a
invariante é a mesma: a soma dos pesos de todas as linhas tem de ser o
denominador do mês. É isso que faz o impacto de cada barra da tela fechar com a
nota — se não fechar, a diretoria vê dois números para a mesma pergunta.

O QUE SÓ O BANCO PROVA é o agrupamento: que uma linha sai por par
`(tier, veículo)`, que o peso cai no lado do sentimento, e que `cargo` e
`engajamento` entram no `group_by` sem vazar para a resposta.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco import repositorio_lentes, repositorio_score
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.erros import NaoEncontrado
from app.dominio.score import peso_da_mencao, peso_do_cargo, peso_do_engajamento
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: UM MÊS LONGE DE TUDO, para nenhuma semente do banco de teste entrar na conta.
MES = date(2031, 5, 1)
TEXTO_DO_MES = "2031-05"

#: OS PARÂMETROS DE FILTRO DA ROTA, todos nulos — a rota os recebe um por um, e
#: repetir treze `None` em cada teste esconderia qual deles o teste muda.
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


def _gravar(sessao, fonte_codigo: str, linhas: list[dict], mes: date = MES) -> None:
    """Grava as menções E o agregado do mês, como `ingerir_mencoes` faria.

    O AGREGADO É REFEITO DAS MESMAS LINHAS, no grão (sentimento, tier) de
    `score_mes_fonte`: é dali que sai o denominador, e sem ele a invariante
    desta suíte não teria com o que fechar.
    """
    fonte = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == fonte_codigo)).one()
    grao: Counter[tuple[str, str]] = Counter()
    for linha in linhas:
        sessao.add(Mencao(fonte_id=fonte.id, mes=mes, **linha))
        grao[(linha["sentimento"], linha.get("tier") or "")] += 1
    for (sentimento, tier), quantas in grao.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=fonte.id,
                mes=mes,
                sentimento=sentimento,
                tier=tier,
                mencoes=quantas,
                soma_log=quantas * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=quantas * peso_do_cargo(None),
            )
        )
    sessao.flush()


def _linhas_da_imprensa(sessao) -> list[dict]:
    """Seis menções da Imprensa, uma por tier e sentimento úteis aqui."""
    atendimento = sessao.scalars(
        select(Tema).where(Tema.nome == "Atendimento ao cliente", Tema.ativo.is_(True))
    ).one()
    base = {"veiculo": "Folha", "unidade_texto": "Águas do Rio", "data": date(2031, 5, 12)}
    return [
        {**base, "sentimento": "neg", "tier": "muito_relevante", "tema_id": atendimento.id,
         "tema_texto": "Atendimento ao cliente",
         "atributo": "2. Eficiência Operacional e Qualidade"},
        {**base, "sentimento": "pos", "tier": "relevante", "tema_texto": "atendimento ao cliente"},
        {**base, "sentimento": "neu", "tier": "menos_relevante",
         "tema_texto": "Atendimento ao cliente"},
        {**base, "sentimento": "neg", "tier": "relevante", "tema_texto": "Obras",
         "atributo": "1. Governança"},
        {**base, "sentimento": "pos", "tier": "menos_relevante", "tema_texto": "Obras",
         "atributo": "Governança"},
        {**base, "sentimento": "neg", "tier": "menos_relevante", "tema_texto": "Qualquer",
         "atributo": "Nada que case", "data": date(2031, 5, 20)},
    ]


def _lente(sessao, codigo: str) -> Lente:
    return sessao.scalars(select(Lente).where(Lente.codigo == codigo)).one()


def _grupos(sessao, lente_codigo: str = "imprensa", **filtro):
    """Os grupos do mês, com o que o teste precisa para conferir o peso: o
    denominador, a calibração e a régua que a rota usou."""
    lente = _lente(sessao, lente_codigo)
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, denominador = repositorio_score.denominador_do_mes(sessao, lente.id, MES, calibracao)
    grupos = repositorio_lentes.grupos_de_veiculos(
        sessao, lente.id, MES, calibracao, regua, filtro.get("filtro")
    )
    return grupos, denominador, calibracao, regua


def test_os_grupos_saem_por_tier_e_veiculo_com_o_peso_no_lado_certo(sessao):
    """Uma linha por (tier, veículo), com a contagem e o peso no lado do
    sentimento. É o que a tela soma para desenhar os três painéis."""
    linhas = _linhas_da_imprensa(sessao)
    veiculos = ["Folha", "Folha", "Valor", "Valor", "Estadão", "Estadão"]
    for linha, veiculo in zip(linhas, veiculos, strict=True):
        linha["veiculo"] = veiculo
    _gravar(sessao, "clipei", linhas)

    grupos, denominador, calibracao, regua = _grupos(sessao)

    #: AS SEIS MENÇÕES INTEIRAS, sem perder nem duplicar nenhuma.
    assert sum(g["positivo"] + g["neutro"] + g["negativo"] for g in grupos) == 6
    #: A SOMA DOS PESOS É O DENOMINADOR DO MÊS — é isto que faz o impacto de
    #: cada barra fechar com a nota, a mesma invariante do explorador de
    #: taxonomia.
    assert sum(
        g["peso_positivo"] + g["peso_neutro"] + g["peso_negativo"] for g in grupos
    ) == pytest.approx(denominador)

    #: UMA LINHA POR PAR, e "Folha" chega em DOIS tiers: a soma por veículo é
    #: trabalho da tela, e a rota não a antecipa — somar aqui tiraria da tela a
    #: possibilidade de estreitar por tier.
    pares = {(g["tier"], g["veiculo"]) for g in grupos}
    assert ("muito_relevante", "Folha") in pares
    assert ("relevante", "Folha") in pares
    #: E É UMA LINHA POR PAR DE VERDADE: sem esta igualdade, a asserção de
    #: cima passa com a linha DUPLICADA — um `set` não conta repetição.
    #: Achado da revisão do Codex (23/10/2026).
    assert len(grupos) == len(pares)

    #: O PESO DE CADA LINHA É O DE `peso_da_mencao` COM O TIER DELA, na régua
    #: do mês. Sem comparar contra a função, a soma total fecharia com o
    #: denominador mesmo se o tier não chegasse ao cálculo (todas as linhas com
    #: o mesmo peso somam igual) — e é o tier que diferencia Tier 1 de Tier 3.
    for grupo in grupos:
        esperado = peso_da_mencao(grupo["tier"], None, None, calibracao, regua) * (
            grupo["positivo"] + grupo["neutro"] + grupo["negativo"]
        )
        soma = grupo["peso_positivo"] + grupo["peso_neutro"] + grupo["peso_negativo"]
        assert soma == pytest.approx(esperado), f"peso errado em {grupo['tier']}"

    #: A CONTRAPROVA de que a régua separa os tiers: se os pesos fossem iguais,
    #: o laço acima passaria com qualquer coluna no lugar do tier.
    peso_t1 = peso_da_mencao("muito_relevante", None, None, calibracao, regua)
    peso_t3 = peso_da_mencao("menos_relevante", None, None, calibracao, regua)
    assert peso_t1 != peso_t3

    #: O PESO CAI NO LADO DO SENTIMENTO: a primeira linha é negativa.
    folha_t1 = next(
        g for g in grupos if g["tier"] == "muito_relevante" and g["veiculo"] == "Folha"
    )
    assert folha_t1["negativo"] == 1 and folha_t1["positivo"] == 0
    assert folha_t1["peso_negativo"] > 0
    assert folha_t1["peso_positivo"] == 0

    #: CARGO E ENGAJAMENTO NÃO SAEM: entram no group_by só porque
    #: `peso_da_mencao` precisa deles.
    assert set(grupos[0]) == {
        "tier", "veiculo", "positivo", "neutro", "negativo",
        "peso_positivo", "peso_neutro", "peso_negativo",
    }


def test_mencao_sem_tier_ou_sem_veiculo_nao_derruba_a_consulta(sessao):
    """Nulo é dado, não erro: a menção entra com o campo vazio, e a tela a
    deixa fora da barra DAQUELE eixo sem a tirar do outro."""
    linhas = _linhas_da_imprensa(sessao)
    linhas[0]["tier"] = None
    linhas[1]["veiculo"] = None
    _gravar(sessao, "clipei", linhas)

    grupos, _, _, _ = _grupos(sessao)

    assert sum(g["positivo"] + g["neutro"] + g["negativo"] for g in grupos) == 6
    assert any(g["tier"] is None for g in grupos)
    assert any(g["veiculo"] is None for g in grupos)


def _explorador_de_veiculos(sessao, codigo: str = "imprensa", **filtro):
    from app.api.lentes import obter_explorador_de_veiculos

    parametros = dict(SEM_FILTRO)
    parametros.update(filtro)
    return obter_explorador_de_veiculos(
        sessao=sessao, usuario=_QuemOlha(), codigo=codigo, mes=TEXTO_DO_MES, **parametros
    )


def test_a_rota_devolve_os_grupos_e_o_denominador(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))

    saida = _explorador_de_veiculos(sessao)

    assert saida.lente == "imprensa"
    assert saida.mes == TEXTO_DO_MES
    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == 6
    #: A INVARIANTE DO MOLDE: a soma dos pesos é o denominador do mês.
    pesos = sum(g.peso_positivo + g.peso_neutro + g.peso_negativo for g in saida.grupos)
    assert pesos == pytest.approx(saida.denominador)
    assert {g.veiculo for g in saida.grupos} == {"Folha"}


def test_a_rota_segue_o_filtro_da_tela(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))

    saida = _explorador_de_veiculos(sessao, sentimento="neg")

    assert sum(g.negativo for g in saida.grupos) == 3
    assert all(g.positivo == 0 and g.neutro == 0 for g in saida.grupos)


def test_a_lente_que_le_o_crm_responde_vazia_sem_erro(sessao):
    """A tela só pede para as lentes de clipping; a interna volta vazia, e não
    em erro — é o mesmo contrato do explorador de taxonomia."""
    saida = _explorador_de_veiculos(sessao, codigo="institucional")

    assert saida.grupos == [] and saida.denominador == 0


def test_a_lente_que_nao_existe_da_404(sessao):
    with pytest.raises(NaoEncontrado):
        _explorador_de_veiculos(sessao, codigo="nao-existe")


def test_o_mercado_responde_como_a_imprensa(sessao):
    """A PARIDADE MERCADO/IMPRENSA PERDEU A GUARDA NO BACK em 23/10/2026, e esta
    é ela de volta — achado da revisão do Codex.

    O teste que a prendia (`test_o_mercado_tem_os_quatro_blocos_de_veiculo_como_a
    _imprensa`) saiu com os quatro blocos do dossiê, e a rota nova não herdou
    guarda nenhuma: ela não consulta `LENTES_COM_VEICULO_E_TIER`, responde para
    qualquer lente que não seja interna. Isso é de propósito — mas "de propósito"
    sem teste é a mesma coisa que por acidente.

    O FRONT GUARDA O OUTRO LADO (`LENTES_COM_BLOCOS_DE_VEICULO`, com os testes de
    tela cobrindo as duas lentes). Faltava este: que o SERVIDOR entrega dado para
    o Mercado, e não só para a Imprensa.
    """
    fonte = sessao.scalars(
        select(ScoreFonte).where(ScoreFonte.codigo == "clipei_investidores")
    ).one()
    lente_do_mercado = _lente(sessao, "mercado")
    assert fonte.lente_id == lente_do_mercado.id, "a fonte do Mercado mudou de lente"

    linhas = _linhas_da_imprensa(sessao)
    for linha, veiculo in zip(linhas, ["Valor", "Valor", "Expert XP"] * 2, strict=True):
        linha["veiculo"] = veiculo
    _gravar(sessao, "clipei_investidores", linhas)

    saida = _explorador_de_veiculos(sessao, codigo="mercado")

    assert saida.lente == "mercado"
    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == 6
    assert {g.veiculo for g in saida.grupos} == {"Valor", "Expert XP"}
    #: E A INVARIANTE DO DENOMINADOR VALE AQUI TAMBÉM: a nota do Mercado tem a
    #: régua dela, e o impacto das barras tem de fechar com ela.
    pesos = sum(g.peso_positivo + g.peso_neutro + g.peso_negativo for g in saida.grupos)
    assert pesos == pytest.approx(saida.denominador)
