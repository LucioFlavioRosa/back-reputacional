"""O recorte da tela (tier/veículo/atributo/tema) no dossiê da lente.

POR QUE UM ARQUIVO À PARTE, e não dentro de `test_lentes_v2.py`: aquele banco
de teste nasce vazio de `mencao` — os testes existentes provam a FORMA do
dossiê (quatro KPIs, dois painéis, fichas) sem precisar de dado real. Provar
que o filtro realmente muda a nota exige inserir `mencao` de verdade, com
tier/veículo/atributo/tema variados, e isso merece seu próprio cenário.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.lentes import obter_dossie, obter_opcoes_de_filtro, obter_recorte
from app.banco.tabelas_catalogo import Tema
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


@pytest.fixture
def imprensa_de_junho(sessao):
    """Seis matérias de Clipei em junho/2026: duas de cada tier, metade do
    veículo A (atributo "Qualidade") e metade do B (atributo "Preço"), com
    sentimento oposto entre os dois grupos — para o filtro ter o que separar.

    TAMBÉM grava `score_mes_fonte` com a MESMA soma — não é redundância, é o
    que faz o caminho SEM filtro (que só lê o agregado, nunca `mencao`) ter
    nota: sem isto, a nota viria `None` ("sem menção classificada") mesmo
    com seis menções no banco, porque é assim que a ingestão de verdade
    preenche aquela tabela, e este teste não roda ingestão nenhuma.
    """
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    linhas = [
        # tier, veiculo, atributo, tema_texto, sentimento
        ("muito_relevante", "Veículo A", "Qualidade", "Tarifa", "pos"),
        ("muito_relevante", "Veículo A", "Qualidade", "Tarifa", "pos"),
        ("relevante", "Veículo B", "Preço", "Obras", "neg"),
        ("relevante", "Veículo B", "Preço", "Obras", "neg"),
        ("menos_relevante", "Veículo A", "Qualidade", "Tarifa", "neu"),
        ("menos_relevante", "Veículo B", "Preço", "Obras", "neu"),
    ]
    for tier, veiculo, atributo, tema_texto, sentimento in linhas:
        sessao.add(
            Mencao(
                fonte_id=clipei.id,
                mes=MES,
                sentimento=sentimento,
                tier=tier,
                veiculo=veiculo,
                atributo=atributo,
                tema_texto=tema_texto,
            )
        )

    por_grupo: dict[tuple[str, str], int] = {}
    for tier, _veiculo, _atributo, _tema, sentimento in linhas:
        por_grupo[(sentimento, tier)] = por_grupo.get((sentimento, tier), 0) + 1
    for (sentimento, tier), mencoes in por_grupo.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=clipei.id,
                mes=MES,
                sentimento=sentimento,
                tier=tier,
                mencoes=mencoes,
                soma_log=mencoes * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=mencoes * peso_do_cargo(None),
            )
        )

    sessao.flush()
    return linhas


def _dossie(sessao, **filtro):
    return obter_dossie(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes="2026-06", **filtro
    )


def test_sem_filtro_usa_todas_as_mencoes_e_nao_se_marca_como_recorte(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    assert dossie.recorte_filtrado is False
    assert dossie.delta_versus == "mes_anterior"
    # Pesos do tier (régua "aegea"): 10/5/1. positivo=2*10=20, negativo=2*5=10,
    # neutro=2*1=2 -> NS = (20-10)/32 = 0,3125 -> score = round(65,625) = 66.
    assert dossie.nota == 66


def test_evolucao_fala_de_materia_e_nao_repete_a_manchete_da_nota(sessao, imprensa_de_junho):
    """A conclusão do gráfico de Evolução precisa bater com o que ele desenha
    (contagem de matéria) — e não repetir a manchete do Destaque, que fala da
    nota. 2 positivas, 2 neutras, 2 negativas: 33% cada."""
    dossie = _dossie(sessao)

    assert dossie.evolucao.titulo == "Evolução das matérias"
    assert dossie.evolucao.conclusao == (
        "6 matérias em junho: 33% positivas, 33% neutras, 33% negativas."
    )
    assert dossie.evolucao.conclusao != dossie.manchete


def test_filtrar_por_tier_muda_a_nota_e_marca_o_recorte(sessao, imprensa_de_junho):
    """Só o tier muito_relevante: as duas matérias positivas do Veículo A."""
    dossie = _dossie(sessao, tier="muito_relevante")

    assert dossie.recorte_filtrado is True
    assert dossie.delta_versus == "sem_filtro"
    # 2 positivas, 0 neutras, 0 negativas -> NS = 1 -> score = 100.
    assert dossie.nota == 100
    # vs. a nota sem filtro (66): delta = 100 - 66 = 34.
    assert dossie.delta == 34


def test_filtrar_por_veiculo_muda_a_nota_tambem(sessao, imprensa_de_junho):
    """Só o Veículo B: negativo=2*5=10 (tier relevante), neutro=1*1=1 (tier
    menos_relevante) -> NS = (0-10)/11 ≈ -0,909 -> score = round(4,545) = 5."""
    dossie = _dossie(sessao, veiculo="Veículo B")

    assert dossie.recorte_filtrado is True
    assert dossie.nota == 5


def test_filtrar_por_atributo_e_tema_restringe_igual_a_veiculo(sessao, imprensa_de_junho):
    """"Qualidade" e "Tarifa" são sinônimos de Veículo A neste cenário:
    positivo=2*10=20 (tier muito_relevante), neutro=1*1=1 (tier
    menos_relevante) -> NS = 20/21 ≈ 0,952 -> score = round(97,619) = 98."""
    por_atributo = _dossie(sessao, atributo="Qualidade")
    por_tema = _dossie(sessao, tema="Tarifa")

    assert por_atributo.nota == por_tema.nota == 98


def test_painel_a_so_mostra_o_tier_filtrado(sessao, imprensa_de_junho):
    dossie = _dossie(sessao, tier="relevante")

    (painel_a,) = (p for p in dossie.paineis if p.tipo == "barras_100")
    rotulos = {linha["rotulo"] for linha in painel_a.dados}
    assert rotulos == {"Tier 2"}


def test_filtro_de_veiculo_nao_afeta_tier_nem_atributo(sessao, imprensa_de_junho):
    """Os quatro filtros são independentes: pedir só `veiculo` não implica
    nenhuma restrição de tier/atributo/tema."""
    dossie = _dossie(sessao, veiculo="Veículo A")

    (painel_a,) = (p for p in dossie.paineis if p.tipo == "barras_100")
    rotulos = {linha["rotulo"] for linha in painel_a.dados}
    # Veículo A tem matérias em DOIS tiers (muito_relevante e menos_relevante).
    assert rotulos == {"Tier 1", "Tier 3"}


def test_opcoes_de_filtro_lista_so_o_que_existe_no_mes(sessao, imprensa_de_junho):
    opcoes = obter_opcoes_de_filtro(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes="2026-06"
    )

    assert set(opcoes.tiers) == {"muito_relevante", "relevante", "menos_relevante"}
    assert set(opcoes.veiculos) == {"Veículo A", "Veículo B"}
    assert set(opcoes.atributos) == {"Qualidade", "Preço"}
    assert set(opcoes.temas) == {"Tarifa", "Obras"}


def test_opcoes_de_filtro_vazias_fora_do_mes_semeado(sessao, imprensa_de_junho):
    opcoes = obter_opcoes_de_filtro(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes="2026-01"
    )

    assert opcoes.tiers == opcoes.veiculos == opcoes.atributos == opcoes.temas == []


# -- o drill-down: últimas matérias ----------------------------------------------


def test_materias_recentes_aparece_com_teto_de_cinco(sessao, imprensa_de_junho):
    """Seis menções semeadas, teto de cinco — o recorte pedido para o
    exercício não é "todas", é uma amostra pequena."""
    dossie = _dossie(sessao)

    bloco = dossie.materias_recentes
    assert bloco.tipo == "tabela"
    assert bloco.subtipo == "materias"
    assert len(bloco.dados) == 5
    # Nenhuma das seis menções do fixture tem `data` — a ordenação cai para
    # `criado_em`, mas o que este teste trava é só o teto, não a ordem exata.
    assert {linha["veiculo"] for linha in bloco.dados} <= {"Veículo A", "Veículo B"}


def test_materias_recentes_respeita_o_mesmo_filtro_da_tela(sessao, imprensa_de_junho):
    """Filtrar por tier muito_relevante deixa só as duas matérias daquele
    tier — o mesmo recorte que já muda a nota e o painel A."""
    dossie = _dossie(sessao, tier="muito_relevante")

    linhas = dossie.materias_recentes.dados
    assert len(linhas) == 2
    assert {linha["tier"] for linha in linhas} == {"Tier 1"}
    assert {linha["veiculo"] for linha in linhas} == {"Veículo A"}


def test_materias_recentes_vazia_na_institucional(sessao):
    """A lente Institucional lê o CRM, não `mencao` — não há matéria lá."""
    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="institucional", mes="2026-06")

    assert dossie.materias_recentes.dados == []
    assert dossie.materias_recentes.ficha.lacunas


# -- drivers e riscos, e temas mais falados --------------------------------------


def test_drivers_e_riscos_agrega_por_atributo(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    bloco = dossie.drivers_e_riscos
    assert bloco.tipo == "barras_100"
    por_rotulo = {linha["rotulo"]: linha for linha in bloco.dados}
    assert por_rotulo["Qualidade"] == {
        "rotulo": "Qualidade", "positivo": 2, "neutro": 1, "negativo": 0,
    }
    assert por_rotulo["Preço"] == {"rotulo": "Preço", "positivo": 0, "neutro": 1, "negativo": 2}


def test_drivers_e_riscos_mostra_os_SETE_pilares_mesmo_com_volume_desigual(sessao):
    """Atributo é vocabulário FECHADO — 7 pilares reputacionais, e não um
    ranking de cauda longa como tema ou veículo. Perder um pilar por ele ter
    menos matéria no mês (o `quantos=6` de antes) esconderia justamente o
    pilar menos falado, que é às vezes o próprio problema."""
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    pilares = [
        "Governança", "Eficiência Operacional e Qualidade", "Crescimento e Solidez Financeira",
        "Responsabilidade Social", "Responsabilidade Ambiental", "Prosperidade Compartilhada",
        "Inovação e Tecnologia",
    ]
    # O ÚLTIMO TEM UMA MATÉRIA SÓ — é o que um teto de 6 cortaria primeiro.
    for posicao, atributo in enumerate(pilares):
        for _ in range(len(pilares) - posicao):
            sessao.add(
                Mencao(
                    fonte_id=clipei.id, mes=MES, sentimento="neu",
                    tier="muito_relevante", atributo=atributo,
                )
            )
    sessao.flush()

    dossie = _dossie(sessao)

    assert {linha["rotulo"] for linha in dossie.drivers_e_riscos.dados} == set(pilares)


def test_temas_mais_falados_agrega_por_tema(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    por_rotulo = {linha["rotulo"]: linha for linha in dossie.temas_mais_falados.dados}
    assert por_rotulo["Tarifa"] == {"rotulo": "Tarifa", "positivo": 2, "neutro": 1, "negativo": 0}
    assert por_rotulo["Obras"] == {"rotulo": "Obras", "positivo": 0, "neutro": 1, "negativo": 2}


def test_drivers_e_temas_respeitam_o_filtro(sessao, imprensa_de_junho):
    """Filtrar por Veículo A deixa só "Qualidade"/"Tarifa" nos dois blocos."""
    dossie = _dossie(sessao, veiculo="Veículo A")

    assert [linha["rotulo"] for linha in dossie.drivers_e_riscos.dados] == ["Qualidade"]
    assert [linha["rotulo"] for linha in dossie.temas_mais_falados.dados] == ["Tarifa"]


def test_drivers_e_temas_vazios_na_institucional(sessao):
    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="institucional", mes="2026-06")

    assert dossie.drivers_e_riscos.dados == []
    assert dossie.drivers_e_riscos.ficha.lacunas
    assert dossie.temas_mais_falados.dados == []
    assert dossie.temas_mais_falados.ficha.lacunas


# -- volume por tier, e top/clima dos veículos ------------------------------------


def test_volume_por_tier_e_uma_rosca_com_os_tres_tiers(sessao, imprensa_de_junho):
    dossie = _dossie(sessao)

    bloco = dossie.volume_por_tier
    assert bloco.tipo == "rosca"
    por_chave = {linha["chave"]: linha["total"] for linha in bloco.dados}
    assert por_chave == {"muito_relevante": 2, "relevante": 2, "menos_relevante": 2}


def test_top_veiculos_ordena_por_volume(sessao, imprensa_de_junho):
    """Os dois veículos têm 3 menções cada — empate desfeito por nome."""
    dossie = _dossie(sessao)

    assert dossie.top_veiculos.tipo == "barras_horizontais"
    assert [linha["rotulo"] for linha in dossie.top_veiculos.dados] == [
        "Veículo A", "Veículo B",
    ]
    assert {linha["valor"] for linha in dossie.top_veiculos.dados} == {3}


def test_veiculos_tier1_conta_so_quem_tem_materia_muito_relevante(sessao, imprensa_de_junho):
    """Veículo A tem duas matérias muito_relevante; Veículo B só tem relevante
    e menos_relevante — a conta de Tier 1 é dele só."""
    dossie = _dossie(sessao)
    kpi = next(k for k in dossie.kpis if k.rotulo == "Veículos Tier 1")
    assert kpi.valor == "1"


def test_veiculos_tier1_respeita_o_mesmo_filtro_da_tela(sessao, imprensa_de_junho):
    """Filtrar por Veículo B — que não tem matéria Tier 1 nenhuma — zera a
    conta: o KPI lê o MESMO recorte que o resto do dossiê, e não a base
    inteira por baixo dele."""
    dossie = _dossie(sessao, veiculo="Veículo B")
    kpi = next(k for k in dossie.kpis if k.rotulo == "Veículos Tier 1")
    assert kpi.valor == "0"


def test_clima_por_veiculos_e_o_saldo_simples_nao_o_ns_ponderado(sessao, imprensa_de_junho):
    """(positivas − negativas) ÷ total × 100 — SEM peso de tier, diferente da
    nota oficial da lente. Veículo A: 2 pos, 1 neu, 0 neg -> +67. Veículo B:
    0 pos, 1 neu, 2 neg -> -67."""
    dossie = _dossie(sessao)

    por_chave = {linha["chave"]: linha["score"] for linha in dossie.clima_por_veiculos.dados}
    assert por_chave == {"Veículo A": 67, "Veículo B": -67}


def test_volume_e_veiculos_vazios_na_institucional(sessao):
    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="institucional", mes="2026-06")

    assert dossie.volume_por_tier.dados == []
    assert dossie.volume_por_tier.ficha.lacunas
    assert dossie.top_veiculos.dados == []
    assert dossie.clima_por_veiculos.dados == []
    assert dossie.clima_por_veiculos.ficha.lacunas


def test_volume_e_veiculos_vazios_no_mercado_MESMO_com_tier_e_veiculo_no_dado(sessao):
    """Restrição de TELA, por hora (pedido do Jones, 2026-10-02) — e não por
    o Mercado não ter tier/veículo de verdade: a migration 0048 define
    `clipei_investidores` como o MESMO clipping da Clipei, recortado por
    público-alvo. Este teste planta `mencao` com tier/veículo reais nessa
    fonte e confere que os quatro blocos saem vazios assim mesmo — provando
    que a restrição é da tela, e não "faltou dado"."""
    clipei_investidores = sessao.scalars(
        select(ScoreFonte).where(ScoreFonte.codigo == "clipei_investidores")
    ).one()
    sessao.add(
        Mencao(
            fonte_id=clipei_investidores.id, mes=MES, sentimento="pos",
            tier="muito_relevante", veiculo="Valor Econômico",
        )
    )
    sessao.flush()

    dossie = obter_dossie(sessao=sessao, usuario=_QuemOlha(), codigo="mercado", mes="2026-06")

    assert dossie.volume_por_tier.dados == []
    assert dossie.top_veiculos.dados == []
    assert dossie.clima_por_veiculos.dados == []
    assert dossie.materias_recentes.dados == []


def test_materias_recentes_sobe_o_teto_quando_ha_recorte(sessao):
    """Clicar num veículo do placar de clima precisa mostrar TODAS as
    matérias por trás daquele saldo, não só uma amostra de 5 — ver
    `TETO_DE_MATERIAS_FILTRADO`."""
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    for _ in range(7):
        sessao.add(
            Mencao(fonte_id=clipei.id, mes=MES, sentimento="pos", veiculo="Veículo Único")
        )
    sessao.flush()

    sem_filtro = _dossie(sessao)
    assert len(sem_filtro.materias_recentes.dados) == 5

    com_filtro = _dossie(sessao, veiculo="Veículo Único")
    assert len(com_filtro.materias_recentes.dados) == 7


# =============================================================================
# o recorte pelas dimensões do padrão Aegea
# =============================================================================
#
# EU ABRI UMA PORTA QUE NÃO LEVAVA A LUGAR NENHUM: o endpoint de opções passou a
# oferecer perfil do autor, UF, subtema e autor, e `FiltroDeMencoes` só conhecia
# tier, veículo, atributo e tema. A tela ofereceria a escolha e o servidor
# devolveria o mês inteiro, sem recorte e sem erro — a pior forma de não
# funcionar, porque parece ter funcionado.
#
# O RECORTE TEM DE CHEGAR À NOTA, e não só à lista: é o que o pacote chama de
# nível 3, e é a pergunta "quanto este pedaço pesa no número". Um filtro que
# muda a lista e não muda a nota responde outra coisa.


@pytest.fixture
def sociedade_de_junho(sessao):
    """Menções de rede em junho, variadas nas dimensões que a carga trouxe.

    O AGREGADO VAI JUNTO, pela mesma razão do fixture da imprensa: o caminho SEM
    filtro lê `score_mes_fonte`, e sem ele a nota viria nula mesmo com menções no
    banco.
    """
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    #: A GRAFIA CURTA das duas concessionárias, para a linha caber: o nome
    #: completo não muda nada do que estes testes provam.
    rio, holding = "Águas do Rio", "Aegea Holding"
    agua, obra = "Falta de água", "Obra atrasada"
    linhas = [
        # perfil, uf, tema, subtema, autor, sentimento, empresa
        ("Figura pública", "RJ", "Abastecimento", agua, "@deputado", "neg", rio),
        ("Figura pública", "SP", "Obras", obra, "@vereadora", "pos", holding),
        ("Cidadão", "RJ", "Abastecimento", agua, "@vizinho", "neg", rio),
        ("Cidadão", "RJ", "Abastecimento", agua, "@vizinho", "pos", holding),
        ("Cidadão", "SP", "Obras", obra, "@outro", "pos", holding),
        ("Cidadão", "SP", "Obras", obra, "@outro", "pos", holding),
    ]
    for perfil, uf, tema, subtema, autor, sentimento, empresa in linhas:
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=MES,
                sentimento=sentimento,
                perfil_autor=perfil,
                uf=uf,
                #: O TEMA É A PRIMEIRA DIMENSÃO PRIORITÁRIA DO PACOTE nesta
                #: lente, e o fixture nascera sem ele. Dois temas, cada um com o
                #: seu subtema: é o que faz a aba de tema ter o que mostrar e a
                #: descida tema → subtema significar algo.
                tema_texto=tema,
                subtema=subtema,
                autor=autor,
                veiculo="Instagram",
                unidade_texto=empresa,
            )
        )

    por_sentimento: dict[str, int] = {}
    for _perfil, _uf, _tema, _subtema, _autor, sentimento, _empresa in linhas:
        por_sentimento[sentimento] = por_sentimento.get(sentimento, 0) + 1
    for sentimento, mencoes in por_sentimento.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=bites.id,
                mes=MES,
                sentimento=sentimento,
                tier="",
                mencoes=mencoes,
                soma_log=mencoes * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=mencoes * peso_do_cargo(None),
            )
        )
    sessao.flush()
    return linhas


def _da_sociedade(sessao, **filtro):
    return obter_dossie(
        sessao=sessao, usuario=_QuemOlha(), codigo="sociedade", mes="2026-06", **filtro
    )


def test_o_recorte_por_PERFIL_muda_a_nota_da_lente(sessao, sociedade_de_junho):
    """Quatro positivas e duas negativas no mês dão nota 67. O recorte das duas
    figuras públicas — uma negativa e uma positiva — dá 50."""
    inteiro = _da_sociedade(sessao)
    recortado = _da_sociedade(sessao, perfil_autor="Figura pública")

    assert inteiro.nota == 67
    assert inteiro.recorte_filtrado is False
    assert recortado.nota == 50
    assert recortado.recorte_filtrado is True


def test_o_recorte_por_UF_por_SUBTEMA_e_por_AUTOR_tambem_recorta(sessao, sociedade_de_junho):
    #: RJ: duas negativas e uma positiva -> 33. "Obra atrasada": três positivas
    #: -> 100. "@vizinho": uma de cada -> 50.
    assert _da_sociedade(sessao, uf="RJ").nota == 33
    assert _da_sociedade(sessao, subtema="Obra atrasada").nota == 100
    assert _da_sociedade(sessao, autor="@vizinho").nota == 50


def test_DOIS_recortes_ao_mesmo_tempo_se_acumulam(sessao, sociedade_de_junho):
    """É o empilhamento que o pacote pede no nível 3: escolher uma UF e, DENTRO
    dela, um perfil. Os dois valem juntos, e não o último."""
    so_uf = _da_sociedade(sessao, uf="RJ")
    uf_e_perfil = _da_sociedade(sessao, uf="RJ", perfil_autor="Figura pública")

    assert so_uf.nota == 33
    #: Em RJ, a única figura pública é a negativa: nota 0.
    assert uf_e_perfil.nota == 0


def test_o_recorte_que_nao_casa_com_nada_NAO_devolve_o_mes_inteiro(sessao, sociedade_de_junho):
    """O QUE ESTE TESTE PROTEGE é o modo de falhar silencioso: um filtro que o
    servidor não conhece é ignorado, e a tela mostra o mês inteiro como se fosse
    o recorte. Zero menções é uma resposta; o mês todo é uma mentira."""
    vazio = _da_sociedade(sessao, uf="AC")

    assert vazio.nota is None
    assert vazio.ausencia is not None


# =============================================================================
# a navegação pelos três níveis: clicar num painel recorta a tela
# =============================================================================
#
# O DONO DO PRODUTO FOI À TELA E NÃO ACHOU COMO DESCER OS NÍVEIS. O recorte
# funcionava — a barra de filtros aplica, o servidor recalcula, a nota muda —, mas
# a barra é um SELETOR: quem olha um painel e vê "Saneamento básico" com 60% de
# negativas tenta clicar NELE, não procurar o mesmo nome num campo suspenso.
#
# NA IMPRENSA ISSO JÁ EXISTIA: a rosca de tier e o ranking de veículos são
# clicáveis e recortam a tela inteira. Os painéis das outras lentes não eram, e o
# que faltava para serem é o servidor DIZER qual dimensão cada painel representa
# — sem isso a tela recebe barras com rótulos e não sabe que filtro aplicar.
#
# E A EMPRESA CITADA NÃO ESTAVA NO RECORTE: o painel de concessionárias é a
# terceira dimensão prioritária do pacote, e clicar nele não tinha para onde ir.


def test_cada_painel_DIZ_a_dimensao_que_ele_recorta(sessao, sociedade_de_junho):
    """É o que permite a tela ligar um clique a um filtro sem adivinhar pelo
    título do painel — e o título é a frase de um detector, que muda com o dado."""
    dossie = _da_sociedade(sessao)

    por_titulo = {painel.titulo: painel.recorta for painel in dossie.paineis}
    assert por_titulo["Temas × sentimento"] == "tema"
    assert por_titulo["Concessionárias com maior repercussão"] == "empresa"


def test_o_recorte_por_EMPRESA_muda_a_nota(sessao, sociedade_de_junho):
    """A empresa citada é a terceira dimensão prioritária do pacote, e era a
    única dos dois painéis da lente sem lugar no filtro: clicar na barra de uma
    concessionária não tinha para onde ir."""
    de_uma = _da_sociedade(sessao, empresa="Águas do Rio")

    assert de_uma.recorte_filtrado is True
    #: As duas menções de Águas do Rio no fixture são negativas.
    assert de_uma.nota == 0


def test_a_empresa_entra_nas_opcoes_de_filtro(sessao, sociedade_de_junho):
    opcoes = obter_opcoes_de_filtro(
        sessao=sessao, usuario=_QuemOlha(), codigo="sociedade", mes="2026-06"
    )

    assert "Águas do Rio" in opcoes.empresas


def test_o_painel_da_IMPRENSA_tambem_diz_o_que_recorta(sessao, imprensa_de_junho):
    """O contrapeso, e ele corrige uma premissa minha: a Imprensa NÃO tem painel
    de temas — os dois dela são o tier do veículo e a matriz de jornalistas.

    O TIER RECORTA, a matriz não: ela é uma matriz de prioridade de pessoas, com
    duas coordenadas e sem uma dimensão de menção para filtrar. Painel que não
    recorta nada diz `None`, e a tela não o torna clicável — o que é melhor que
    um clique que não faz nada.
    """
    dossie = _dossie(sessao)

    por_titulo = {painel.titulo: painel.recorta for painel in dossie.paineis}
    assert por_titulo["Tier do veículo × sentimento"] == "tier"
    assert por_titulo["Matriz de relacionamento com jornalistas"] is None


# =============================================================================
# "Onde está a causa": uma aba por dimensão útil
# =============================================================================
#
# OS DOIS PAINÉIS NÃO BASTAM, e isto foi medido: o pacote declara oito dimensões
# prioritárias para a Sociedade digital — tema, subtema, empresa citada, rede,
# perfil do autor, autor, fonte e UF — e a tela desenhava duas. As outras seis só
# existiam no seletor da barra, que é onde se ESCOLHE um recorte, não onde se
# DESCOBRE qual deles explica o mês.
#
# O PACOTE PEDE ABAS (FRONTEND §3): "abas das dimensões úteis (máx. 6 visíveis +
# mais)". É a mesma pergunta — "onde está a causa" — feita por vários cortes, e
# trocar de aba é a navegação que faltava.
#
# TUDO NO MESMO PEDIDO, e isto foi medido antes de decidir: as seis consultas
# levam 109 ms juntas no mês mais cheio (6.932 menções). Um endpoint por aba
# custaria um estado de carregamento por clique e um segundo caminho de dados
# para a mesma conta.
#
# "ÚTIL" É O CRITÉRIO DO PACOTE: pelo menos dois valores distintos não nulos, e
# nulos abaixo de 60%. Uma dimensão em que quase ninguém classificou não é uma
# causa: é uma lacuna de dado, e a ficha do bloco é quem conta isso.


def test_a_causa_vem_com_uma_aba_por_dimensao_util(sessao, sociedade_de_junho):
    dossie = _da_sociedade(sessao)

    chaves = [bloco.recorta for bloco in dossie.onde_esta_a_causa]
    #: A ORDEM É A DO PACOTE para esta lente: o assunto primeiro, depois quem
    #: fala, depois onde.
    assert chaves[0] == "tema"
    assert "subtema" in chaves
    assert "perfil_autor" in chaves
    assert "uf" in chaves
    assert "autor" in chaves


def test_a_dimensao_de_UM_VALOR_SO_nao_e_aba(sessao, sociedade_de_junho):
    """Uma dimensão com um valor só não explica nada: a barra ocuparia a largura
    inteira e diria "100% de tudo é isto". No fixture, a rede é só Instagram."""
    dossie = _da_sociedade(sessao)

    assert "veiculo" not in [bloco.recorta for bloco in dossie.onde_esta_a_causa]


def test_a_dimensao_com_MUITO_NULO_nao_e_aba(sessao):
    """O critério do pacote: nulos abaixo de 60%. Uma dimensão que a fonte quase
    não classificou não é causa, é lacuna — e a tela que a mostra como causa diz
    que "a maior parte do mês é Sem classificação", o que não ajuda ninguém."""
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    for i in range(10):
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=MES,
                sentimento="neg",
                perfil_autor="Cidadão" if i < 4 else None,
                tema_texto="Saneamento",
                uf="RJ" if i % 2 else "SP",
            )
        )
    sessao.add(
        ScoreMesFonte(
            fonte_id=bites.id, mes=MES, sentimento="neg", tier="", mencoes=10,
            soma_log=10 * peso_do_engajamento(None), soma_engajamento=0,
            soma_cargo=10 * peso_do_cargo(None),
        )
    )
    sessao.flush()

    dossie = _da_sociedade(sessao)

    #: Perfil em 4 de 10 — 60% de nulo — fica fora. A UF, em todas, entra.
    chaves = [bloco.recorta for bloco in dossie.onde_esta_a_causa]
    assert "perfil_autor" not in chaves
    assert "uf" in chaves


def test_cada_aba_traz_as_linhas_e_o_que_ela_recorta(sessao, sociedade_de_junho):
    """A aba é um bloco como os outros: linhas com sentimento, ficha de
    procedência e a dimensão que um clique aplica."""
    dossie = _da_sociedade(sessao)
    da_uf = next(b for b in dossie.onde_esta_a_causa if b.recorta == "uf")

    assert da_uf.tipo == "barras_100"
    assert {linha["rotulo"] for linha in da_uf.dados} == {"RJ", "SP"}
    assert da_uf.ficha.origem
    #: RJ tem duas negativas e uma positiva no fixture.
    do_rio = next(linha for linha in da_uf.dados if linha["rotulo"] == "RJ")
    assert do_rio["negativo"] == 2
    assert do_rio["positivo"] == 1


def test_a_causa_respeita_o_recorte_ativo(sessao, sociedade_de_junho):
    """DENTRO DO RECORTE, e é isto que faz o terceiro nível existir: com uma UF
    escolhida, as abas passam a mostrar o que explica AQUELA UF — é descer um
    nível, e não olhar o mês inteiro de outro jeito."""
    inteiro = _da_sociedade(sessao)
    no_rio = _da_sociedade(sessao, uf="RJ")

    do_perfil_inteiro = next(b for b in inteiro.onde_esta_a_causa if b.recorta == "perfil_autor")
    do_perfil_no_rio = next(b for b in no_rio.onde_esta_a_causa if b.recorta == "perfil_autor")

    #: No mês há duas figuras públicas; no Rio, uma só.
    das_figuras_inteiro = next(
        linha for linha in do_perfil_inteiro.dados if linha["rotulo"] == "Figura pública"
    )
    das_figuras_no_rio = next(
        linha for linha in do_perfil_no_rio.dados if linha["rotulo"] == "Figura pública"
    )
    assert das_figuras_inteiro["negativo"] + das_figuras_inteiro["positivo"] == 2
    assert das_figuras_no_rio["negativo"] + das_figuras_no_rio["positivo"] == 1


# =============================================================================
# os achados da revisão desta etapa
# =============================================================================


def test_a_aba_de_tema_usa_o_MESMO_rotulo_do_painel(sessao):
    """ACHADO DE REVISÃO (alta). O painel "Temas × sentimento" agrupa por
    `coalesce(Tema.nome, Mencao.tema_texto)` — o nome do dicionário do CRM vence
    a grafia do fornecedor. A aba de tema agrupava por `Mencao.tema_texto` cru.

    O ESTRAGO ERA DUPLO, e os dois lados aparecem na mesma tela: painel e aba
    mostrariam rótulos diferentes para o mesmo mês, e clicar no rótulo
    normalizado do painel mandaria `?tema=Saneamento básico` para um dado cuja
    grafia é "SAN BASICO" — nenhuma menção encontrada, num clique numa barra
    visível."""
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    do_dicionario = sessao.scalars(select(Tema).limit(1)).one()
    for sentimento in ("neg", "neg", "pos"):
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=MES,
                sentimento=sentimento,
                #: A GRAFIA DO FORNECEDOR, com o tema do dicionário ao lado.
                tema_texto="SAN BASICO",
                tema_id=do_dicionario.id,
                uf="RJ",
                perfil_autor="Cidadão",
            )
        )
    sessao.add(
        Mencao(
            fonte_id=bites.id,
            mes=MES,
            sentimento="pos",
            tema_texto="Outro assunto",
            uf="SP",
            perfil_autor="Cidadão",
        )
    )
    sessao.add(
        ScoreMesFonte(
            fonte_id=bites.id, mes=MES, sentimento="neg", tier="", mencoes=2,
            soma_log=2 * peso_do_engajamento(None), soma_engajamento=0,
            soma_cargo=2 * peso_do_cargo(None),
        )
    )
    sessao.add(
        ScoreMesFonte(
            fonte_id=bites.id, mes=MES, sentimento="pos", tier="", mencoes=2,
            soma_log=2 * peso_do_engajamento(None), soma_engajamento=0,
            soma_cargo=2 * peso_do_cargo(None),
        )
    )
    sessao.flush()

    dossie = _da_sociedade(sessao)
    da_aba = next(bloco for bloco in dossie.onde_esta_a_causa if bloco.recorta == "tema")
    do_painel = next(painel for painel in dossie.paineis if painel.recorta == "tema")

    rotulos_da_aba = {linha["rotulo"] for linha in da_aba.dados}
    rotulos_do_painel = {linha["rotulo"] for linha in do_painel.dados}
    assert rotulos_da_aba == rotulos_do_painel
    assert do_dicionario.nome in rotulos_da_aba


def test_o_recorte_por_tema_ACHA_o_que_o_rotulo_normalizado_nomeia(sessao):
    """A outra metade do mesmo achado: o filtro comparava só `tema_texto`, então
    o rótulo que a tela mostra (o do dicionário) não encontrava as menções cuja
    grafia crua é outra. Um clique que devolve "nenhuma menção" numa barra que
    acabou de mostrar três é o pior resultado possível."""
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    do_dicionario = sessao.scalars(select(Tema).limit(1)).one()
    for sentimento in ("neg", "neg"):
        sessao.add(
            Mencao(
                fonte_id=bites.id, mes=MES, sentimento=sentimento,
                tema_texto="SAN BASICO", tema_id=do_dicionario.id,
            )
        )
    sessao.add(
        ScoreMesFonte(
            fonte_id=bites.id, mes=MES, sentimento="neg", tier="", mencoes=2,
            soma_log=2 * peso_do_engajamento(None), soma_engajamento=0,
            soma_cargo=2 * peso_do_cargo(None),
        )
    )
    sessao.flush()

    pelo_nome_do_dicionario = _da_sociedade(sessao, tema=do_dicionario.nome)

    assert pelo_nome_do_dicionario.recorte_filtrado is True
    #: Duas negativas: a nota do recorte é zero, e NÃO a ausência.
    assert pelo_nome_do_dicionario.nota == 0
    assert pelo_nome_do_dicionario.ausencia is None


def test_a_aba_de_JORNALISTA_respeita_ve_diretorio(sessao, imprensa_de_junho):
    """ACHADO DE REVISÃO (alta). A matriz de jornalistas e os sinais que nomeiam
    jornalista saem do payload de quem não tem `ve_diretorio` — e a aba "Jornalista"
    da Imprensa publicava os mesmos nomes por outra porta.

    E A DA SOCIEDADE CONTINUA: lá o autor é o perfil de rede que veio DENTRO da
    menção, não cadastro de terceiro — é o mesmo dado que o indicador "Autor mais
    negativo" já publica. A distinção é a que `_nomeia_o_diretorio` faz, e ela é
    por lente, não por nome de coluna."""
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    clipei = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    #: A IMPRENSA PRECISA DE AUTOR NA MAIORIA DAS MENÇÕES para a aba existir: o
    #: critério do pacote exige nulo abaixo de 60%, e o fixture da imprensa traz
    #: seis matérias sem autor. Oito com autor passam das seis sem.
    for nome in ("Repórter A",) * 5 + ("Repórter B",) * 3:
        sessao.add(
            Mencao(
                fonte_id=clipei.id, mes=MES, sentimento="neg", autor=nome,
                tier="relevante", veiculo="Veículo A", atributo="Qualidade",
                tema_texto="Tarifa",
            )
        )
    sessao.flush()

    de_quem_ve = obter_dossie(
        sessao=sessao, usuario=_QuemOlha(ve_diretorio=True), codigo="imprensa", mes="2026-06"
    )
    de_quem_nao_ve = obter_dossie(
        sessao=sessao, usuario=_QuemOlha(ve_diretorio=False), codigo="imprensa", mes="2026-06"
    )

    assert "autor" in [bloco.recorta for bloco in de_quem_ve.onde_esta_a_causa]
    assert "autor" not in [bloco.recorta for bloco in de_quem_nao_ve.onde_esta_a_causa]
    #: E AS OUTRAS ABAS FICAM: esconder a lente inteira para proteger um nome
    #: seria pagar com a tela toda por uma coluna.
    assert "tema" in [bloco.recorta for bloco in de_quem_nao_ve.onde_esta_a_causa]
    _ = bites


def test_a_dimensao_ESPERADA_que_nao_explica_vira_AVISO(sessao):
    """O PACOTE PEDE ISTO (FRONTEND §40), e o caso é real, não hipotético: o tema
    é a PRIMEIRA dimensão prioritária da Sociedade digital e chega em 1.959 dos
    6.932 itens de junho — uma das duas fontes não classifica assunto.

    SEM O AVISO, a tela mostra um cartão "onde está a causa" SEM aba de tema logo
    acima de um painel "Temas × sentimento". Quem lê conclui que a tela está
    quebrada. A frase transforma um buraco inexplicável em um fato sobre a
    fonte — e esse fato é acionável: dá para cobrar do fornecedor."""
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    for i in range(10):
        sessao.add(
            Mencao(
                fonte_id=bites.id,
                mes=MES,
                sentimento="neg" if i % 2 else "pos",
                #: O tema em 2 de 10 — a proporção da planilha real, arredondada.
                tema_texto=("Abastecimento" if i == 0 else "Obras") if i < 2 else None,
                uf="RJ" if i % 2 else "SP",
                perfil_autor="Cidadão",
            )
        )
    for sentimento, quantas in (("neg", 5), ("pos", 5)):
        sessao.add(
            ScoreMesFonte(
                fonte_id=bites.id, mes=MES, sentimento=sentimento, tier="", mencoes=quantas,
                soma_log=quantas * peso_do_engajamento(None), soma_engajamento=0,
                soma_cargo=quantas * peso_do_cargo(None),
            )
        )
    sessao.flush()

    dossie = _da_sociedade(sessao)

    assert "tema" not in [bloco.recorta for bloco in dossie.onde_esta_a_causa]
    #: E A TELA SABE DIZER POR QUÊ, com o número na frase.
    do_tema = next(frase for frase in dossie.lacunas_da_causa if frase.startswith("Tema"))
    assert "2 de 10" in do_tema

    #: O VALOR ÚNICO TEM FRASE PRÓPRIA: o perfil está em todas as menções, mas com
    #: um valor só — não é falta de classificação, é dimensão que não separa nada.
    do_perfil = next(
        frase for frase in dossie.lacunas_da_causa if frase.startswith("Perfil de quem fala")
    )
    assert "um valor só" in do_perfil


def test_a_tabela_de_mencoes_DIZ_qual_coluna_e_o_endereco_da_linha(sessao, sociedade_de_junho):
    """O DONO DO PRODUTO PEDIU A LINHA, E NÃO O LINK: "não precisa ter o link no
    modal, mas se clicar gostaria de acessar a página".

    UMA COLUNA "LINK" COM "ABRIR ↗" EM CADA LINHA É RUÍDO: a coluna existe só
    para repetir, trinta vezes, a mesma palavra — e rouba largura do texto da
    menção, que é o que se lê. O endereço continua vindo no dado; o que muda é
    que ele passa a ser o DESTINO DA LINHA, e não uma célula.

    QUEM DECIDE É O SERVIDOR, pelo mesmo motivo de `recorta`: a alternativa é a
    tela procurar uma coluna chamada "link" — adivinhação pelo nome, que é
    exatamente como a escolha do schema da tabela já quebrou uma vez."""
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    sessao.add(
        Mencao(
            fonte_id=bites.id,
            mes=MES,
            sentimento="neg",
            titulo_texto="Falta de água no bairro",
            link="https://exemplo.com/post/1",
            uf="RJ",
        )
    )
    sessao.flush()

    dossie = _da_sociedade(sessao)
    tabela = dossie.materias_recentes

    assert tabela.coluna_do_link == "link"
    #: A COLUNA SAI DA TELA, mas o endereço CONTINUA NO DADO — é ele que a linha
    #: usa para levar à página.
    assert "link" not in [coluna.chave for coluna in tabela.colunas]
    assert tabela.dados[0]["link"] == "https://exemplo.com/post/1"


def test_a_tabela_que_nao_tem_endereco_nao_promete_nenhum(sessao, imprensa_de_junho):
    """A tabela de matérias da Imprensa não traz link — e uma linha que parece
    clicável e não leva a lugar nenhum custa mais do que uma que não parece."""
    dossie = _dossie(sessao)

    assert dossie.materias_recentes.coluna_do_link is None


def test_o_bloco_dos_TEMAS_MAIS_FALADOS_recorta_por_tema(sessao, sociedade_de_junho):
    """PEDIDO DO DONO DO PRODUTO: "Temas mais falados seria ter um modal aqui tb".
    Era o único gráfico da tela em que a barra não levava a lugar nenhum."""
    dossie = _da_sociedade(sessao)

    assert dossie.temas_mais_falados.recorta == "tema"


def test_DENTRO_de_um_tema_a_primeira_aba_e_o_SUBTEMA(sessao, sociedade_de_junho):
    """A OUTRA METADE DO PEDIDO: "e uma aba com os sub temas".

    ELA JÁ FUNCIONAVA, e vale dizer por quê, porque o motivo é frágil se ninguém
    o escrever: o subtema chega em 28% das menções do mês e por isso NÃO é aba do
    mês — mas a presença de cada dimensão é medida DENTRO do recorte ativo, e
    quem classifica o tema classifica o subtema (as duas colunas vêm da mesma
    fonte). Dentro de um tema, o subtema está em quase tudo, e entra."""
    #: DOIS SUBTEMAS DENTRO DO TEMA, porque um valor só não explica nada e é
    #: corretamente excluído — o fixture nasceu com "Falta de água" nas três
    #: menções de Abastecimento. No dado real são vários por tema.
    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    sessao.add(
        Mencao(
            fonte_id=bites.id,
            mes=MES,
            sentimento="neg",
            tema_texto="Abastecimento",
            subtema="Água turva",
            uf="RJ",
            perfil_autor="Cidadão",
        )
    )
    sessao.flush()

    no_tema = _da_sociedade(sessao, tema="Abastecimento")
    dentro = obter_recorte(
        sessao=sessao, usuario=_QuemOlha(), codigo="sociedade", mes="2026-06", tema="Abastecimento"
    )

    assert no_tema.recorte_filtrado is True
    assert [bloco.recorta for bloco in dentro.dentro][0] == "subtema"
    #: E AS LINHAS SÃO AS DE DENTRO DO TEMA: os dois subtemas dele, não os do mês.
    do_subtema = dentro.dentro[0]
    assert {linha["rotulo"] for linha in do_subtema.dados} == {"Falta de água", "Água turva"}
    #: E O TEMA NÃO SE REPETE dentro de si mesmo.
    assert "tema" not in [bloco.recorta for bloco in dentro.dentro]
