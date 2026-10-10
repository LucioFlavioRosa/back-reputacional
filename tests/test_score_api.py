"""O Score servido pela API — o contrato, e quem alcança o quê.

As fórmulas se provam em `test_score.py`, sem banco. Aqui é o resto: o índice
sai com as lentes que o formaram, a calibração é versionada e só quem
administra cadastros a muda, a lente institucional vem DAS INTERAÇÕES deste
banco, e quem não tem o portal Score não lê nada disso.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_score import Lente, Mencao, ScoreConfig, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao
from main import app
from tests.test_e2e_postgres import URL, corpo

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


def _cliente(sessao, perfil: str):
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": perfil}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    return TestClient(app)


@pytest.fixture
def cliente_do_score(sessao):
    """`plataforma_edicao`: alcança o Score E administra cadastros."""
    cliente = _cliente(sessao, "plataforma_edicao")
    try:
        yield cliente
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_score(sessao):
    """`crm_edicao`: escreve agenda e NÃO alcança o portal Score."""
    cliente = _cliente(sessao, "crm_edicao")
    try:
        yield cliente
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    valor = Instituicao(
        nome="Valor Econômico", nome_normalizado="valor economico",
        tipo="veiculo", uf="SP",
    )
    sessao.add(valor)
    sessao.flush()
    return {"instituicao": valor}


@pytest.fixture
def junho(sessao):
    """Junho com uma fonte de imprensa, no grão que o índice lê."""
    mes = date(2026, 6, 1)
    sessao.execute(delete(ScoreMesFonte).where(ScoreMesFonte.mes == mes))
    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    for tier, contagens in {
        "muito_relevante": {"pos": 65, "neu": 64, "neg": 16},
        "relevante": {"pos": 85, "neu": 43, "neg": 55},
        "menos_relevante": {"pos": 946, "neu": 80, "neg": 149},
    }.items():
        for sentimento, total in contagens.items():
            sessao.add(
                ScoreMesFonte(
                    fonte_id=clipei.id, mes=mes, sentimento=sentimento,
                    tier=tier, mencoes=total,
                )
            )
    sessao.flush()
    return mes


# -- as cinco lentes e o índice -------------------------------------------------


def test_a_migration_cadastrou_as_cinco_lentes_e_as_seis_fontes(sessao):
    lentes = sessao.scalars(select(Lente).order_by(Lente.ordem)).all()
    assert [lente.codigo for lente in lentes] == [
        "imprensa", "mercado", "sociedade", "clientes", "institucional"
    ]
    assert sum(lente.peso_padrao for lente in lentes) == 100

    fontes = sessao.scalars(select(ScoreFonte)).all()
    assert {fonte.codigo for fonte in fontes} >= {
        "clipei", "clipei_investidores", "approach_sl", "bites", "approach_cm", "crm"
    }
    # O CRM é a única fonte interna: ela se lê deste banco, não de planilha.
    assert [fonte.codigo for fonte in fontes if fonte.interna] == ["crm"]


def test_o_indice_traz_a_imprensa_em_70_com_a_regua_padrao(cliente_do_score, junho):
    """O critério de aceite do §7, pela API."""
    resposta = cliente_do_score.get("/api/score?mes=2026-06")
    assert resposta.status_code == 200, resposta.text

    corpo_ = resposta.json()
    imprensa = next(lente for lente in corpo_["lentes"] if lente["codigo"] == "imprensa")
    assert imprensa["score"] == 70
    assert imprensa["fontes"] == ["clipei"]
    assert corpo_["calibracao"]["padrao"] is True


def test_a_lente_institucional_vem_das_interacoes_deste_banco(
    cliente_do_score, sessao, semente, junho
):
    """Sem cópia: o clima das interações É a lente.

    É o que garante que corrigir um registro no CRM corrige o índice — com o
    clima duplicado numa tabela de menções, o índice mentiria até alguém
    reprocessar.
    """
    antes = cliente_do_score.get("/api/score?mes=2026-06").json()
    institucional_antes = next(
        lente for lente in antes["lentes"] if lente["codigo"] == "institucional"
    )

    for clima in ("propositivo", "propositivo", "tenso"):
        criada = cliente_do_score.post(
            "/api/interacoes",
            json={**corpo(semente), "data_interacao": "2026-06-15", "clima": clima},
        )
        assert criada.status_code == 201, criada.text

    depois = cliente_do_score.get("/api/score?mes=2026-06").json()
    institucional_depois = next(
        lente for lente in depois["lentes"] if lente["codigo"] == "institucional"
    )

    assert institucional_depois["fontes"] == ["crm"]
    assert institucional_depois["score"] != institucional_antes["score"] or (
        institucional_antes["score"] is None
    )


def test_a_leitura_diz_o_que_sustenta_e_o_que_corroi(cliente_do_score, junho):
    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    assert "sustenta o índice" in corpo_["leitura"]
    assert "pressiona" in corpo_["leitura"]


def test_a_serie_diz_quantas_lentes_formaram_cada_ponto(cliente_do_score, junho):
    """Um mês com uma lente só produz um ISR legítimo pela fórmula e enganoso
    na curva — a tela precisa poder marcar o ponto como parcial."""
    serie = cliente_do_score.get("/api/score/serie").json()
    assert serie, "junho tem dado; a série não pode vir vazia"
    assert all("lentes" in ponto for ponto in serie)
    assert all(0 <= ponto["lentes"] <= 5 for ponto in serie)


@pytest.fixture
def junho_com_temas(sessao):
    """Imprensa em junho com dois temas — um sustentando, um pressionando —,
    e `mencao`/`score_mes_fonte` na mesma soma: pela MESMA razão de
    `imprensa_de_junho` em `test_filtro_da_lente.py`, é `score_mes_fonte` quem
    dá a nota da lente, e `mencao` quem abre por tema; sem o par, ou a nota sai
    nula ou a decomposição não tem o que explicar.
    """
    mes = date(2026, 6, 1)
    sessao.execute(delete(ScoreMesFonte).where(ScoreMesFonte.mes == mes))
    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    for _ in range(2):
        sessao.add(
            Mencao(
                fonte_id=clipei.id, mes=mes, sentimento="pos",
                tier="muito_relevante", tema_texto="Tarifa justa",
            )
        )
    sessao.add(
        Mencao(
            fonte_id=clipei.id, mes=mes, sentimento="neg",
            tier="muito_relevante", tema_texto="Falha no abastecimento",
        )
    )
    sessao.add(
        ScoreMesFonte(
            fonte_id=clipei.id, mes=mes, sentimento="pos", tier="muito_relevante", mencoes=2,
        )
    )
    sessao.add(
        ScoreMesFonte(
            fonte_id=clipei.id, mes=mes, sentimento="neg", tier="muito_relevante", mencoes=1,
        )
    )
    sessao.flush()
    return mes


def test_a_serie_abre_o_que_sustentou_e_pressionou_CADA_lente(
    cliente_do_score, junho_com_temas
):
    """A Jornada de uma lente lê `temas_das_lentes[codigo]` sem chamada extra —
    é a mesma pergunta de `sustentou`/`pressionou`, respondida dentro da
    Imprensa só, e não comparada com as outras quatro."""
    serie = cliente_do_score.get("/api/score/serie").json()
    junho = next(ponto for ponto in serie if ponto["mes"] == "2026-06")

    imprensa = junho["temas_das_lentes"]["imprensa"]
    assert imprensa["sustentou"]["tema"] == "Tarifa justa"
    assert imprensa["pressionou"]["tema"] == "Falha no abastecimento"
    # As duas menções têm tema: nada sobra sem explicação.
    assert imprensa["pontos_sem_tema"] == pytest.approx(0, abs=0.2)


def test_mes_invalido_e_recusado_dizendo_o_formato(cliente_do_score):
    resposta = cliente_do_score.get("/api/score?mes=junho")
    assert resposta.status_code == 422
    assert "AAAA-MM" in resposta.json()["detalhe"]


# -- a calibração ---------------------------------------------------------------


def test_desligar_as_fontes_da_sociedade_tira_a_lente_e_redistribui(
    cliente_do_score, junho, sessao
):
    """§7: "Desligar Approach SL e Bites remove Sociedade e redistribui pesos".

    A LENTE PRECISA TER DADO para o desligamento significar alguma coisa: uma
    lente que não teve export nenhum no mês já sai do cálculo por falta de
    medição, e o teste passaria sem que a chave de desligar fizesse nada.
    """
    for codigo in ("approach_sl", "bites"):
        fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
        for sentimento, total in (("pos", 700), ("neu", 140), ("neg", 1100)):
            sessao.add(
                ScoreMesFonte(
                    fonte_id=fonte.id, mes=junho, sentimento=sentimento,
                    tier="", mencoes=total,
                )
            )
    sessao.flush()

    com_sociedade = cliente_do_score.get("/api/score?mes=2026-06").json()
    assert next(
        lente for lente in com_sociedade["lentes"] if lente["codigo"] == "sociedade"
    )["score"] is not None

    gravou = cliente_do_score.put(
        "/api/score/calibracao",
        json={"fontes_desligadas": ["approach_sl", "bites"]},
    )
    assert gravou.status_code == 201, gravou.text
    assert gravou.json()["padrao"] is False

    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    sociedade = next(lente for lente in corpo_["lentes"] if lente["codigo"] == "sociedade")
    assert sociedade["score"] is None
    assert "desligadas" in sociedade["ausencia"]
    assert "Fora do cálculo" in corpo_["leitura"]

    # O PESO REDISTRIBUÍDO APARECE. A lente fora vale 0; as que ficaram
    # dividem 100 entre si — sem isso a tela diria "Imprensa, peso 30" num mês
    # em que ela pesou 37, e a soma dos pesos na tela não fecharia.
    efetivos = {lente["codigo"]: lente["peso_efetivo"] for lente in corpo_["lentes"]}
    assert efetivos["sociedade"] == 0
    assert sum(efetivos.values()) == 100
    assert efetivos["imprensa"] > 30


def test_a_regua_de_tier_muda_o_indice_sem_tocar_no_dado(cliente_do_score, junho):
    """O agregado é o mesmo; o que muda é quanto cada tier vale."""
    com_padrao = cliente_do_score.get("/api/score?mes=2026-06").json()
    imprensa_padrao = next(
        lente for lente in com_padrao["lentes"] if lente["codigo"] == "imprensa"
    )["score"]

    cliente_do_score.put("/api/score/calibracao", json={"regua_tier": "igual"})

    sem_ponderacao = cliente_do_score.get("/api/score?mes=2026-06").json()
    imprensa_sem = next(
        lente for lente in sem_ponderacao["lentes"] if lente["codigo"] == "imprensa"
    )["score"]

    assert imprensa_sem != imprensa_padrao


def test_a_calibracao_e_versionada_e_nao_sobrescrita(cliente_do_score, sessao, junho):
    """Saber com que régua um número foi lido é o que explica por que ele
    mudou — por isso a tabela só cresce."""
    antes = len(sessao.scalars(select(ScoreConfig)).all())

    cliente_do_score.put("/api/score/calibracao", json={"regua_engajamento": "log"})
    cliente_do_score.put("/api/score/calibracao", json={"regua_engajamento": "bruto"})

    depois = len(sessao.scalars(select(ScoreConfig)).all())
    assert depois == antes + 2


def test_restaurar_o_padrao_grava_uma_versao_em_vez_de_apagar(cliente_do_score, junho):
    cliente_do_score.put("/api/score/calibracao", json={"regua_tier": "forte"})
    restaurou = cliente_do_score.delete("/api/score/calibracao")

    assert restaurou.status_code == 201, restaurou.text
    assert restaurou.json()["padrao"] is True
    assert restaurou.json()["regua_tier"] == "aegea"


def test_regua_invalida_e_recusada(cliente_do_score):
    recusa = cliente_do_score.put("/api/score/calibracao", json={"regua_tier": "chute"})
    assert recusa.status_code == 422
    assert "Régua de tier inválida" in recusa.json()["detalhe"]


def test_peso_fora_da_faixa_e_recusado(cliente_do_score):
    recusa = cliente_do_score.put(
        "/api/score/calibracao", json={"pesos": {"imprensa": 90}}
    )
    assert recusa.status_code == 422
    assert "fora da faixa" in recusa.json()["detalhe"]


def test_lente_ou_fonte_desconhecida_e_recusada(cliente_do_score):
    assert cliente_do_score.put(
        "/api/score/calibracao", json={"pesos": {"astrologia": 10}}
    ).status_code == 422
    assert cliente_do_score.put(
        "/api/score/calibracao", json={"fontes_desligadas": ["inventada"]}
    ).status_code == 422


# -- quem alcança o quê ---------------------------------------------------------


def test_quem_nao_tem_o_portal_score_nao_le_o_indice(cliente_sem_score):
    """O cartão escondido na capa não protege a rota: um `curl` basta."""
    recusa = cliente_sem_score.get("/api/score?mes=2026-06")
    assert recusa.status_code == 403
    assert "Score Executivo" in recusa.json()["detalhe"]


def test_a_calibracao_exige_administrar_cadastros(sessao, junho):
    """Ler o índice é de quem tem o portal; MEXER NA RÉGUA é da coordenação —
    ela muda o número que todo mundo lê."""
    leitura = _cliente(sessao, "score_leitura")
    try:
        assert leitura.get("/api/score?mes=2026-06").status_code == 200
        assert leitura.put(
            "/api/score/calibracao", json={"regua_tier": "forte"}
        ).status_code == 403
    finally:
        app.dependency_overrides.clear()


# -- os fatos do mês ------------------------------------------------------------


def test_o_fato_do_mes_aparece_no_indice(cliente_do_score, junho):
    """É o que transforma uma curva em explicação."""
    criado = cliente_do_score.post(
        "/api/score/fatos",
        json={"mes": "2026-06", "texto": "Atraso na divulgação das DFs", "efeito": "pressiona"},
    )
    assert criado.status_code == 201, criado.text

    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    assert [f["texto"] for f in corpo_["fatos"]] == ["Atraso na divulgação das DFs"]

    apagou = cliente_do_score.delete(f"/api/score/fatos/{criado.json()['id']}")
    assert apagou.status_code == 204


def test_efeito_invalido_e_recusado(cliente_do_score):
    recusa = cliente_do_score.post(
        "/api/score/fatos",
        json={"mes": "2026-06", "texto": "Alguma coisa", "efeito": "chute"},
    )
    assert recusa.status_code == 422
    assert "Efeito inválido" in recusa.json()["detalhe"]


# -- o registro de fontes -------------------------------------------------------


def test_as_fontes_trazem_cobertura_e_volume_do_mes(cliente_do_score, junho):
    """A aba Calibração lista: fonte, lente, cobertura de meses, volume."""
    fontes = cliente_do_score.get("/api/score/fontes?mes=2026-06").json()
    clipei = next(f for f in fontes if f["codigo"] == "clipei")

    assert clipei["lente"] == "Imprensa"
    assert clipei["meses_com_dado"] >= 1
    assert clipei["mencoes_no_mes"] == 1503
    assert clipei["ligada"] is True


def test_a_listagem_sobrevive_a_fonte_sem_planilha(cliente_do_score):
    """A fonte INTERNA tem mapeamento vazio, e a listagem tem de trazê-la.

    O QUE ISTO PEGOU: `arquivo` (qual export a fonte lê) foi acrescentado
    lendo o mapeamento por `Mapeamento.de_json`, que exige `data` e
    `sentimento` — com razão, para quem vai LER planilha. O `crm` não lê
    nenhuma: o mapeamento dele é `{}`. A listagem inteira estourava por causa
    da única fonte que não tem arquivo, e com ela caíam a Calibração e a Base.
    """
    fontes = cliente_do_score.get("/api/score/fontes?mes=2026-06").json()

    por_codigo = {f["codigo"]: f for f in fontes}
    assert por_codigo["crm"]["interna"] is True
    assert por_codigo["crm"]["arquivo"] is None
    #: E AS DUAS FONTES DA CLIPEI DIZEM O MESMO ARQUIVO — é o que permite a
    #: tela oferecer uma opção só para as duas.
    assert por_codigo["clipei"]["arquivo"] == "clipei"
    assert por_codigo["clipei_investidores"]["arquivo"] == "clipei"


def test_as_opcoes_da_calibracao_vem_do_servidor(cliente_do_score):
    """A tela não tem lista fixa de régua nem de lente: uma régua nova passa a
    ser oferecida sem build do front."""
    opcoes = cliente_do_score.get("/api/score/opcoes").json()

    assert {r["codigo"] for r in opcoes["reguas_de_tier"]} == {
        "aegea", "suave", "forte", "igual", "so_tier1"
    }
    assert set(opcoes["reguas_de_engajamento"]) == {"n", "log", "bruto", "cargo"}
    assert len(opcoes["lentes"]) == 5


# -- a ingestão da planilha do fornecedor ---------------------------------------
#
# A tradução célula → menção se prova em `test_ingestao_score.py`, sem arquivo.
# Aqui é o que só o banco responde: o mês entra, o agregado nasce das menções,
# reenviar o mesmo arquivo não dobra nada, e quem não administra não importa.


def _planilha(aba: str, cabecalho: list[str], linhas: list[list]) -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    livro = Workbook()
    pagina = livro.active
    pagina.title = aba
    pagina.append(cabecalho)
    for linha in linhas:
        pagina.append(linha)
    buffer = BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


#: O cabeçalho que o cadastro da Bites espera, inteiro. Uma linha pode vir com
#: menos células — o que falta chega como célula vazia, que é exatamente o que
#: a planilha de verdade faz.
CABECALHO_DA_BITES = [
    "Data", "Autor", "Cargo", "Sentimento", "Atributo", "Categoria", "Engajamento",
    "Unidades/Empresas",
]


def _export_da_bites(linhas: list[list]) -> bytes:
    return _planilha("Posts", CABECALHO_DA_BITES, linhas)


#: O tipo que o navegador manda para um .xlsx. Declarado uma vez, porque
#:  o escrevia inteiro e os testes novos precisam dele tambem.
_TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _subir(cliente, codigo: str, conteudo: bytes):
    return cliente.post(
        f"/api/score/fontes/{codigo}/planilha",
        files={
            "arquivo": (
                "export.xlsx",
                conteudo,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_a_planilha_vira_mencao_e_agregado(cliente_do_score, sessao):
    conteudo = _export_da_bites(
        [
            [date(2026, 6, 2), "@a", "Governador", "Positivo", "Investimento", "Obras", 100],
            [date(2026, 6, 3), "@b", "Vereador", "Negativo", "Tarifa", "Tarifa", 9],
            [date(2026, 6, 4), "@c", "", "Não informado", "", "", 5],
        ]
    )
    resposta = _subir(cliente_do_score, "bites", conteudo)
    assert resposta.status_code == 201

    # A Bites entrega um arquivo só dela: uma fonte, um resumo.
    assert len(resposta.json()) == 1
    resumo = resposta.json()[0]
    assert resumo["linhas"] == 3
    assert resumo["ingeridas"] == 2
    # O post sem classificação é recusa declarada, e sai na resposta.
    assert resumo["descartes"]["sem_sentimento"] == 1
    assert resumo["meses"] == ["2026-06"]

    bites = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))
    somas = sessao.scalars(
        select(ScoreMesFonte).where(ScoreMesFonte.fonte_id == bites.id)
    ).all()
    por_sentimento = {soma.sentimento: soma for soma in somas}
    assert por_sentimento["pos"].mencoes == 1
    assert por_sentimento["pos"].soma_engajamento == 100
    # `1 + log10(1 + 9)` = 2, e o vereador vale 2 na régua de cargo.
    assert float(por_sentimento["neg"].soma_log) == pytest.approx(2.0)
    assert float(por_sentimento["neg"].soma_cargo) == pytest.approx(2.0)
    assert float(por_sentimento["pos"].soma_cargo) == pytest.approx(5.0)


def test_reenviar_o_mesmo_arquivo_nao_dobra_o_mes(cliente_do_score, sessao):
    """O fornecedor reenvia o export quando corrige uma classificação — somar
    contaria o mesmo post duas vezes."""
    conteudo = _export_da_bites(
        [[date(2026, 6, 2), "@a", "Prefeito", "Positivo", "", "", 10]]
    )
    _subir(cliente_do_score, "bites", conteudo)
    segunda = _subir(cliente_do_score, "bites", conteudo)
    assert segunda.json()[0]["ingeridas"] == 1
    # E o resumo diz que o mês já tinha uma — é assim que um export parcial,
    # que encolheria o mês, aparece para quem subiu.
    assert segunda.json()[0]["antes"] == 1

    bites = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))
    somas = sessao.scalars(
        select(ScoreMesFonte).where(ScoreMesFonte.fonte_id == bites.id)
    ).all()
    assert [soma.mencoes for soma in somas] == [1]


def test_o_mes_que_o_arquivo_nao_traz_fica_intacto(cliente_do_score, sessao):
    """O export de junho não é uma afirmação sobre maio."""
    _subir(
        cliente_do_score,
        "bites",
        _export_da_bites([[date(2026, 5, 9), "@a", "", "Positivo", "", "", 1]]),
    )
    _subir(
        cliente_do_score,
        "bites",
        _export_da_bites([[date(2026, 6, 9), "@b", "", "Negativo", "", "", 1]]),
    )

    bites = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))
    meses = sessao.scalars(
        select(ScoreMesFonte.mes).where(ScoreMesFonte.fonte_id == bites.id)
    ).all()
    assert sorted(set(meses)) == [date(2026, 5, 1), date(2026, 6, 1)]


def _clipping(linhas: list[list]) -> bytes:
    return _planilha(
        "Clipping",
        ["Data", "Classificação", "Aegea Tier", "Atributo", "Veículo",
         "Público-alvo", "Subcategoria"],
        linhas,
    )


DUAS_MATERIAS = [
    [date(2026, 6, 1), "POSITIVA", "Muito Relevante", "Gestão",
     "Valor Econômico", "Investidores", "Resultados"],
    [date(2026, 6, 2), "NEGATIVA", "Relevante", "Tarifa",
     "Jornal Local", "População em geral", "Tarifa"],
]


#: AS MESMAS DUAS MATÉRIAS, com a coluna `Público-alvo` CONTRA o cadastro: a de
#: investidor vem de um veículo que NÃO está na lista, e a que está na lista vem
#: marcada como população em geral. É o par que separa os dois critérios.
MATERIAS_CONTRA_A_COLUNA = [
    [date(2026, 6, 1), "POSITIVA", "Muito Relevante", "Gestão",
     "Valor Econômico", "População em geral", "Resultados"],
    [date(2026, 6, 2), "NEGATIVA", "Relevante", "Tarifa",
     "Jornal Local", "Investidores", "Tarifa"],
]


def _na_lista_do_mercado(sessao, nome: str) -> None:
    """Põe o veículo na lista que a lente Mercado considera."""
    from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
    from app.dominio.texto import normalizar

    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            CategoriaPublico.nome == "Imprensa",
            SubcategoriaPublico.nome == "Econômica e de negócios",
        )
    )
    assert alvo is not None
    sessao.add(
        Instituicao(
            nome=nome,
            nome_normalizado=normalizar(nome),
            tipo="veiculo",
            subcategoria_publico_id=alvo,
        )
    )
    sessao.flush()


def test_um_arquivo_alimenta_as_duas_fontes_que_o_leem(cliente_do_score, sessao):
    """Duas lentes, um arquivo: Mercado é o clipping recortado pela LISTA.

    O UPLOAD TRATA AS DUAS. Importar por uma só deixaria a irmã com o mês
    anterior, e Imprensa e Mercado passariam a ler versões diferentes do MESMO
    arquivo — divergência que a tela não teria como mostrar, porque cada lente
    exibiria um número plausível.

    E O RECORTE É O CADASTRO, não a coluna do fornecedor. Este teste afirma a
    troca de dono com as duas em conflito: a matéria do Valor Econômico (na
    lista) vem marcada como "População em geral" e entra; a do Jornal Local
    (fora da lista) vem marcada como "Investidores" e NÃO entra. Medido contra o
    export de 08–09/2026, a diferença entre os dois critérios é de 271 linhas.
    """
    _na_lista_do_mercado(sessao, "Valor Econômico")

    resposta = _subir(cliente_do_score, "clipei", _clipping(MATERIAS_CONTRA_A_COLUNA))
    assert resposta.status_code == 201

    por_fonte = {resumo["fonte"]: resumo for resumo in resposta.json()}
    assert set(por_fonte) == {"clipei", "clipei_investidores"}
    assert por_fonte["clipei"]["ingeridas"] == 2
    assert por_fonte["clipei_investidores"]["ingeridas"] == 1
    assert (
        por_fonte["clipei_investidores"]["descartes"]["fora_da_lista_de_veiculos"] == 1
    )
    #: E A COLUNA NÃO DECIDE MAIS NADA: nenhuma linha saiu por filtro de coluna.
    assert por_fonte["clipei_investidores"]["descartes"]["fora_do_filtro"] == 0


def test_subir_pela_fonte_irma_da_no_mesmo(cliente_do_score):
    """Quem escolhe "Importar" na linha do Mercado alimenta a Imprensa também:
    o grupo é do arquivo, e não de quem clicou."""
    resposta = _subir(cliente_do_score, "clipei_investidores", _clipping(DUAS_MATERIAS))
    assert {resumo["fonte"] for resumo in resposta.json()} == {
        "clipei", "clipei_investidores"
    }


def test_o_tier_que_ninguem_reconhece_entra_como_aviso(cliente_do_score):
    """A matéria não se perde por causa de uma coluna acessória — mas uma
    coluna inteira mapeada errado precisa aparecer."""
    conteudo = _clipping(
        [
            [date(2026, 6, 1), "POSITIVA", "Tier 1", "Gestão",
             "Valor Econômico", "Investidores", "Resultados"],
        ]
    )
    por_fonte = {r["fonte"]: r for r in _subir(cliente_do_score, "clipei", conteudo).json()}
    assert por_fonte["clipei"]["ingeridas"] == 1
    assert por_fonte["clipei"]["avisos"]["tier_nao_reconhecido"] == 1


def test_a_planilha_maior_que_um_mega_passa_pelo_teto_global(cliente_do_score):
    """O teto de 1 MB protege as rotas de formulário; esta recebe arquivo.

    O export da Clipei tem 1,4 MB. Sem a rota na lista de exceções do
    `LimiteDeCorpoMiddleware`, o upload morria em 413 ANTES de a ingestão
    rodar — e a única forma de carregar era chamar o caso de uso direto.

    O CORPO AQUI NÃO É UMA PLANILHA de propósito: um `.xlsx` de verdade com
    mais de 1 MB precisaria de dezenas de milhares de linhas (o formato
    comprime bem), e o que se quer provar não é a leitura — é que o corpo
    grande CHEGA na rota.
    """
    grande = b"x" * (1536 * 1024)
    resposta = _subir(cliente_do_score, "bites", grande)

    # 413 significaria que o middleware barrou o corpo antes da rota. O que se
    # espera é 422: a rota RODOU e recusou o conteúdo por não ser um `.xlsx` —
    # que é a mensagem que diz o que fazer.
    assert resposta.status_code == 422, resposta.status_code
    assert ".xlsx" in resposta.json()["detalhe"]


def test_a_planilha_sem_as_colunas_do_cadastro_e_recusada(cliente_do_score):
    conteudo = _planilha("Posts", ["Quando", "Tom"], [[date(2026, 6, 1), "Positivo"]])
    recusa = _subir(cliente_do_score, "bites", conteudo)
    assert recusa.status_code == 422
    # A mensagem NOMEIA as colunas que faltam: "arquivo inválido" mandaria a
    # pessoa abrir o export e adivinhar.
    assert "Data" in recusa.json()["detalhe"]


def test_o_arquivo_que_nao_e_planilha_e_recusado_com_instrucao(cliente_do_score):
    recusa = _subir(cliente_do_score, "bites", b"Data;Sentimento\n2026-06-01;Positivo")
    assert recusa.status_code == 422
    assert ".xlsx" in recusa.json()["detalhe"]


def test_a_fonte_interna_nao_se_importa(cliente_do_score):
    """O CRM já está neste banco: aceitar uma planilha para ele criaria uma
    segunda versão do clima das interações."""
    conteudo = _export_da_bites([[date(2026, 6, 2), "@a", "", "Positivo", "", "", 1]])
    recusa = _subir(cliente_do_score, "crm", conteudo)
    assert recusa.status_code == 422
    assert "interna" in recusa.json()["detalhe"]


def test_quem_so_le_o_score_nao_importa_planilha(sessao):
    """Importar muda o número que todos leem — mesma régua da calibração."""
    cliente = _cliente(sessao, "plataforma_leitura")
    try:
        conteudo = _export_da_bites(
            [[date(2026, 6, 2), "@a", "", "Positivo", "", "", 1]]
        )
        assert _subir(cliente, "bites", conteudo).status_code == 403
    finally:
        app.dependency_overrides.clear()


# -- a aba de Drivers e riscos --------------------------------------------------
#
# As três leituras saem de `mencao`, uma a uma — e por isso só existem depois de
# a planilha entrar. O que se prova aqui: que elas leem o atributo, a unidade e
# a travessia de meses; que respeitam o desligamento de fonte; e que um mês sem
# menção individual diz isso, em vez de desenhar zeros.


def _post_da_bites(quando: date, sentimento: str, atributo: str, unidade: str, tema: str):
    return [quando, "@a", "", sentimento, atributo, tema, 1, unidade]


def test_os_drivers_leem_unidade_e_perpetuacao(cliente_do_score, sessao):
    """Duas das três leituras da aba, pela fonte da Sociedade digital.

    O ATRIBUTO SAIU DESTE TESTE porque saiu da Bites: a `0069` tirou a coluna
    do mapeamento dela por decisão de negócio — o N1 passa a ser derivado do
    assunto (N3) pelo cadastro, e manter o N1 que o fornecedor carimba criava
    dois N1 para a mesma menção, livres para discordar. O eixo de atributo se
    prova em `test_os_drivers_leem_o_atributo_da_clipei`.
    """
    linhas = []
    # Um tema negativo em quatro meses seguidos, sempre na Corsan.
    for mes_ in (3, 4, 5, 6):
        linhas.append(
            _post_da_bites(date(2026, mes_, 5), "Negativo", "Governança", "Corsan", "Tarifa")
        )
    # E um mês positivo noutra unidade.
    linhas.append(
        _post_da_bites(date(2026, 6, 6), "Positivo", "Prosperidade", "Prolagos", "Obras")
    )
    _subir(cliente_do_score, "bites", _export_da_bites(linhas))

    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    assert corpo_["mencoes_no_mes"] >= 2

    #: A COLUNA DE ATRIBUTO DA PLANILHA É IGNORADA, e o eixo fica sem nada da
    #: Bites: é o preço declarado da decisão, e aparece aqui para não aparecer
    #: numa reunião.
    assert "Governança" not in {a["nome"] for a in corpo_["atributos"]}

    por_unidade = {u["nome"]: u for u in corpo_["unidades"]}
    assert por_unidade["Corsan"]["negativas"] == 1
    # Prolagos não tem negativa nenhuma: não entra num ranking de pressão.
    assert "Prolagos" not in por_unidade

    perpetuados = {p["tema"]: p for p in corpo_["perpetuacao"]}
    assert perpetuados["Tarifa"]["meses"] == 4
    assert perpetuados["Tarifa"]["primeiro_mes"] == "2026-03"
    assert perpetuados["Tarifa"]["ultimo_mes"] == "2026-06"
    assert perpetuados["Tarifa"]["lentes"] == ["Sociedade digital"]


def test_os_drivers_leem_o_atributo_da_clipei(cliente_do_score, sessao):
    """O eixo de atributo, pela fonte que ainda manda a coluna.

    DEPOIS DA `0069`, A CLIPEI É A ÚNICA que alimenta `mencao.atributo` — a
    Bites deixou de mandar e as duas fontes da Approach nunca mandaram. Este
    teste é o que impede o eixo de morrer sem ninguém notar.
    """
    conteudo = _clipping(
        [
            [date(2026, 6, 1), "NEGATIVA", "Muito Relevante", "Governança",
             "Jornal Local", "População em geral", "Tarifa"],
            [date(2026, 6, 2), "POSITIVA", "Relevante", "Prosperidade",
             "Jornal Local", "População em geral", "Obras"],
        ]
    )
    _subir(cliente_do_score, "clipei", conteudo)

    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()

    por_atributo = {a["nome"]: a for a in corpo_["atributos"]}
    assert por_atributo["Governança"]["negativo"] == 1
    # NS −1 → score 0; NS +1 → score 100. É o que a barra divergente desenha.
    assert por_atributo["Governança"]["score"] == 0
    assert por_atributo["Prosperidade"]["score"] == 100


def test_o_tema_que_morreu_antes_do_mes_nao_esta_em_perpetuacao(cliente_do_score):
    """Um incêndio apagado em abril não é risco vivo em junho — listá-lo mandaria
    a comunicação atuar sobre o que já acabou."""
    linhas = [
        _post_da_bites(date(2026, mes_, 5), "Negativo", "Governança", "Corsan", "Encerrado")
        for mes_ in (2, 3, 4)
    ]
    linhas.append(
        _post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Corsan", "Vivo")
    )
    _subir(cliente_do_score, "bites", _export_da_bites(linhas))

    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    assert "Encerrado" not in {p["tema"] for p in corpo_["perpetuacao"]}


def test_um_tema_de_um_mes_so_nao_e_perpetuacao(cliente_do_score):
    _subir(
        cliente_do_score,
        "bites",
        _export_da_bites(
            [_post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Corsan", "Episódio")]
        ),
    )
    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    assert corpo_["perpetuacao"] == []
    # Mas a menção existe, e o atributo e a unidade aparecem.
    assert corpo_["mencoes_no_mes"] >= 1
    assert corpo_["unidades"]


def test_os_drivers_respeitam_a_fonte_desligada(cliente_do_score):
    """Explicar o número com o dado de uma fonte que não entrou nele é pior do
    que não explicar: quem lê o gráfico não tem como saber."""
    _subir(
        cliente_do_score,
        "bites",
        _export_da_bites(
            [_post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Corsan", "Tarifa")]
        ),
    )
    assert cliente_do_score.get("/api/score/drivers?mes=2026-06").json()["unidades"]

    cliente_do_score.put("/api/score/calibracao", json={"fontes_desligadas": ["bites"]})
    depois = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    assert depois["unidades"] == []
    assert depois["atributos"] == []
    assert depois["mencoes_no_mes"] == 0


def test_mes_sem_mencao_individual_diz_isso(cliente_do_score, junho):
    """O `junho` semeia o AGREGADO da Clipei, e não menções: o índice funciona,
    e a aba de Drivers precisa dizer que o detalhe não chegou."""
    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    assert corpo_["mencoes_no_mes"] == 0
    assert corpo_["atributos"] == []
    assert corpo_["unidades"] == []
    assert corpo_["perpetuacao"] == []


def test_quem_nao_tem_o_portal_do_score_nao_le_os_drivers(cliente_sem_score):
    assert cliente_sem_score.get("/api/score/drivers?mes=2026-06").status_code == 403


def test_o_peso_efetivo_fecha_em_cem_com_quatro_lentes(cliente_do_score, sessao, junho):
    """O caso que o arredondamento simples errava.

    Com a lente Institucional fora, as outras quatro dividem 85 pontos: 30/85,
    20/85, 20/85 e 15/85 arredondados por si dão 35 + 24 + 24 + 18 = 101 — uma
    composição impossível na tela, e o tipo de detalhe que corrói a confiança
    num número que a diretoria cita.
    """
    for codigo in ("clipei_investidores", "approach_sl", "approach_cm"):
        fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
        for sentimento, total in (("pos", 100), ("neu", 50), ("neg", 40)):
            sessao.add(
                ScoreMesFonte(
                    fonte_id=fonte.id, mes=junho, sentimento=sentimento,
                    tier="", mencoes=total,
                )
            )
    sessao.flush()

    corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
    efetivos = {lente["codigo"]: lente["peso_efetivo"] for lente in corpo_["lentes"]}
    medidas = [lente for lente in corpo_["lentes"] if lente["score"] is not None]

    assert len(medidas) == 4, "o teste precisa de quatro lentes medidas"
    assert sum(efetivos.values()) == 100
    # E a de fora continua em zero — não é "pouco peso", é nenhum.
    assert efetivos["institucional"] == 0


def test_perpetuacao_conta_so_os_meses_em_que_o_tema_foi_NEGATIVO(cliente_do_score):
    """Uma negativa em março e elogios de abril a junho não são um risco vivo.

    Contando meses de qualquer sentimento, esse tema entrava como quatro meses
    de perpetuação — e a comunicação sairia atrás de um incêndio que virou
    elogio no segundo mês.
    """
    linhas = [_post_da_bites(date(2026, 3, 5), "Negativo", "Governança", "Corsan", "Virou elogio")]
    linhas += [
        _post_da_bites(date(2026, mes_, 5), "Positivo", "Governança", "Corsan", "Virou elogio")
        for mes_ in (4, 5, 6)
    ]
    # E um contraexemplo de verdade, negativo nos quatro meses.
    linhas += [
        _post_da_bites(date(2026, mes_, 6), "Negativo", "Governança", "Corsan", "Não passa")
        for mes_ in (3, 4, 5, 6)
    ]
    _subir(cliente_do_score, "bites", _export_da_bites(linhas))

    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    temas = {p["tema"]: p for p in corpo_["perpetuacao"]}
    assert "Virou elogio" not in temas
    assert temas["Não passa"]["meses"] == 4


def test_a_lente_do_tema_perpetuado_e_onde_ele_foi_negativo(cliente_do_score):
    """Dizer que o risco está numa lente porque ela falou BEM do assunto seria
    o contrário do que a tela promete."""
    linhas = [
        _post_da_bites(date(2026, mes_, 5), "Negativo", "Governança", "Corsan", "Tarifa")
        for mes_ in (4, 5, 6)
    ]
    _subir(cliente_do_score, "bites", _export_da_bites(linhas))

    # A mesma tarifa, elogiada nos canais próprios — outra lente.
    elogios = _planilha(
        "CM",
        ["Data", "Sentimento", "Interações", "TAG (assunto 1)", "Concessionárias"],
        [[date(2026, 6, 7), "Positivo", 1, "Tarifa", "Corsan"]],
    )
    _subir(cliente_do_score, "approach_cm", elogios)

    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    tarifa = next(p for p in corpo_["perpetuacao"] if p["tema"] == "Tarifa")
    assert tarifa["lentes"] == ["Sociedade digital"]


def test_a_participacao_da_unidade_usa_o_negativo_do_mes_inteiro(cliente_do_score):
    """Com a soma do ranking como base, as unidades listadas somariam 100% de
    um todo que não existe."""
    linhas = [
        _post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Corsan", "Tarifa"),
        _post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Corsan", "Tarifa"),
        _post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Prolagos", "Tarifa"),
        _post_da_bites(date(2026, 6, 5), "Positivo", "Governança", "Prolagos", "Tarifa"),
    ]
    _subir(cliente_do_score, "bites", _export_da_bites(linhas))

    unidades = {
        u["nome"]: u
        for u in cliente_do_score.get("/api/score/drivers?mes=2026-06").json()["unidades"]
    }
    # Três negativas no mês: duas na Corsan, uma no Prolagos.
    assert unidades["Corsan"]["participacao"] == 67
    assert unidades["Prolagos"]["participacao"] == 33
    # E o total de menções da unidade sai junto: 1 de 2 no Prolagos é outra
    # situação que 1 de 200.
    assert unidades["Prolagos"]["mencoes"] == 2


def test_os_drivers_dizem_a_regra_da_perpetuacao(cliente_do_score):
    """A tela explica a lista — e o número da explicação vem de quem aplica a
    regra, não de uma constante repetida no front."""
    regra = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()[
        "regra_da_perpetuacao"
    ]
    assert regra["meses_da_janela"] >= regra["meses_para_perpetuar"] >= 2


def test_tudo_desligado_nao_e_o_mesmo_que_planilha_faltando(cliente_do_score):
    """Duas telas vazias, dois motivos: sem isso a tela manda importar uma
    planilha que já está no banco."""
    _subir(
        cliente_do_score,
        "bites",
        _export_da_bites(
            [_post_da_bites(date(2026, 6, 5), "Negativo", "Governança", "Corsan", "Tarifa")]
        ),
    )
    todas = [
        "clipei", "clipei_investidores", "approach_sl", "approach_cm", "bites",
    ]
    cliente_do_score.put("/api/score/calibracao", json={"fontes_desligadas": todas})

    corpo_ = cliente_do_score.get("/api/score/drivers?mes=2026-06").json()
    assert corpo_["mencoes_no_mes"] == 0
    assert corpo_["fontes_ligadas"] == 0


def test_todo_clima_do_banco_tem_sentimento_no_score(sessao):
    """O dicionário `clima` é fechado — e se alguém o abrir, este teste quebra.

    A lente institucional traduz clima em sentimento por um dicionário em
    código. Um clima novo no banco não derruba nada em produção: as interações
    dele apenas ficam de fora, com um aviso no log, e o índice sai menor e
    plausível. É justamente por ser plausível que precisa quebrar aqui — no
    mesmo dia em que o clima for criado, e não meses depois, quando alguém
    desconfiar do número.
    """
    from app.banco.repositorio_score import SENTIMENTO_DO_CLIMA
    from app.banco.tabelas_catalogo import Clima

    codigos = set(sessao.scalars(select(Clima.codigo).where(Clima.ativo.is_(True))))
    assert codigos <= set(SENTIMENTO_DO_CLIMA), (
        f"clima sem tradução para sentimento: {sorted(codigos - set(SENTIMENTO_DO_CLIMA))}"
    )


def test_a_tela_abre_no_mes_mais_completo_e_nao_no_ultimo(
    cliente_do_score, sessao, semente, junho
):
    """O defeito que fazia a tela parecer vazia com o banco cheio.

    O CRM é a única fonte que se alimenta sozinha: cada interação registrada põe
    um mês na lista de meses com dado, mesmo sem planilha nenhuma. As planilhas
    dos fornecedores chegam com atraso — então o mês MAIS RECENTE é quase sempre
    um mês só de CRM, com quatro lentes vazias e um ISR que é o score de uma só.
    """
    # Junho com DUAS lentes: a `junho` traz a imprensa, e aqui entra a
    # sociedade. É o que faz dele o mês mais completo — com uma lente só,
    # empatado com setembro, o desempate pelo mais recente escolheria setembro,
    # e com razão.
    approach = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "approach_sl"))
    for sentimento, total in (("pos", 700), ("neu", 140), ("neg", 1100)):
        sessao.add(
            ScoreMesFonte(
                fonte_id=approach.id, mes=junho, sentimento=sentimento,
                tier="", mencoes=total,
            )
        )
    sessao.flush()

    # Uma interação em setembro, com clima: basta isso para setembro entrar na
    # lista e, pela regra antiga, virar o mês de abertura.
    criada = cliente_do_score.post(
        "/api/interacoes",
        json={**corpo(semente), "data_interacao": "2026-09-10", "clima": "propositivo"},
    )
    assert criada.status_code == 201, criada.text

    opcoes = cliente_do_score.get("/api/score/opcoes").json()
    assert "2026-09" in opcoes["meses"], "setembro precisa estar na lista"
    assert opcoes["meses"][-1] == "2026-09", "e ser o último — é o que tornava o defeito possível"
    # Mas não é nele que a tela abre.
    assert opcoes["mes_sugerido"] == "2026-06"


def test_registro_nao_visivel_nao_move_o_indice(cliente_do_score, sessao, semente, junho):
    """`visivel = false` é o registro que alguém tirou da vista de propósito.

    `filtros_sql.condicoes` o exclui de toda leitura do CRM — é a linha
    `InteracaoRegistro.visivel.is_(True)`. As consultas do Score nasceram sem
    ela: filtram `arquivado_em is null` e nada mais. O efeito é que um registro
    retirado continua movendo o índice da companhia, e ainda pode devolver o
    nome da instituição dele no painel da institucional.

    A PROVA É A VOLTA: mede, acrescenta tensos, confirma que o índice desceu, e
    então esconde os mesmos registros. Se esconder de fato os tira da conta, o
    número volta ao que era. Comparar com um valor fixo provaria menos — passaria
    também se o cálculo tivesse parado de olhar para o CRM.
    """

    def institucional() -> int | None:
        corpo_ = cliente_do_score.get("/api/score?mes=2026-06").json()
        lente = next(le for le in corpo_["lentes"] if le["codigo"] == "institucional")
        return lente["score"]

    antes = institucional()

    ids = []
    for _ in range(3):
        criada = cliente_do_score.post(
            "/api/interacoes",
            json={**corpo(semente), "data_interacao": "2026-06-15", "clima": "tenso"},
        )
        assert criada.status_code == 201, criada.text
        ids.append(criada.json()["id"])

    com_os_tensos = institucional()
    assert com_os_tensos != antes, "os três tensos tinham de mover o índice"

    sessao.execute(
        update(InteracaoRegistro)
        .where(InteracaoRegistro.id.in_(ids))
        .values(visivel=False)
    )
    sessao.flush()

    assert institucional() == antes


def test_registro_nao_visivel_nao_nomeia_orgao_no_dossie(
    cliente_do_score, sessao, semente, junho
):
    """A outra ponta: o painel da institucional lista COM QUEM se conversou.

    Um registro retirado da vista devolvia o nome da instituição dele por aqui —
    e este é o caminho que não passa por `condicoes`.
    """
    criada = cliente_do_score.post(
        "/api/interacoes",
        json={**corpo(semente), "data_interacao": "2026-06-15", "clima": "propositivo"},
    )
    assert criada.status_code == 201, criada.text
    sessao.execute(
        update(InteracaoRegistro)
        .where(InteracaoRegistro.id == criada.json()["id"])
        .values(visivel=False)
    )
    sessao.flush()

    dossie = cliente_do_score.get("/api/score/lentes/institucional/dossie?mes=2026-06").json()
    orgaos = next(
        (p for p in dossie["paineis"] if p["titulo"] == "Órgãos com mais interações"),
        None,
    )
    assert orgaos is not None, "o papel do teste vê o diretório; o painel tem de vir"

    nomes = [linha["rotulo"] for linha in orgaos["dados"]]
    assert "Valor Econômico" not in nomes


# ======================= o volume, pelo HTTP (o que meus testes não cobriam)
#
# A pessoa encontrou na tela: "Too many fields. Maximum number of fields is
# 1000". A primeira versão mandava `veiculos_a_criar` repetido, um campo por
# veículo — e a primeira carga da Clipei tem 2.628.
#
# MEUS TESTES NÃO PEGARAM por dois motivos, e os dois valem como lição: os de
# unidade chamavam `ingerir` direto em Python, sem passar pelo multipart; e os
# de HTTP mandavam listas de DOIS nomes. O caminho estava provado, o volume não.


def test_a_lista_de_veiculos_vai_num_campo_so_e_aguenta_milhares(cliente_do_score):
    """DOIS MIL NOMES PELO CLIENTE DE VERDADE.

    O limite de 1.000 campos do parser multipart é proteção do servidor e está
    certa — quem estava errado era o formato. Este teste é sobre o NÚMERO: com
    dois nomes ele passaria em qualquer dos dois formatos, e não provaria nada.

    Os nomes são de veículos que a planilha NÃO tem: a rota os ignora, e o que
    se mede aqui é o pedido atravessar o parser.
    """
    import json

    nomes = [f"Veículo Inexistente {i}" for i in range(2000)]

    resposta = cliente_do_score.post(
        "/api/score/fontes/clipei/planilha",
        files={"arquivo": ("clipei.xlsx", _clipping(DUAS_MATERIAS), _TIPO_XLSX)},
        data={"veiculos_a_criar": json.dumps(nomes)},
    )

    assert "Too many fields" not in resposta.text
    assert resposta.status_code == 201, resposta.text


def test_lista_de_veiculos_em_formato_invalido_e_erro_de_pedido(cliente_do_score):
    """JSON QUEBRADO NÃO É LISTA VAZIA.

    Aceitar em silêncio faria a tela dizer "2.628 cadastrados" e nada nascer —
    o pior resultado possível, porque parece ter funcionado.
    """
    resposta = cliente_do_score.post(
        "/api/score/fontes/clipei/planilha",
        files={"arquivo": ("clipei.xlsx", _clipping(DUAS_MATERIAS), _TIPO_XLSX)},
        data={"veiculos_a_criar": "{isto nao e json"},
    )

    assert resposta.status_code == 422
    assert "formato válido" in resposta.text


def test_o_campo_com_a_lista_cria_de_verdade(cliente_do_score, sessao):
    """O CONTRAPESO dos dois acima: o formato novo não pode só passar pelo
    parser — ele tem de criar. Sem isto, trocar JSON por campo nenhum passaria
    nos três testes."""
    import json

    from app.dominio.texto import normalizar

    resposta = cliente_do_score.post(
        "/api/score/fontes/clipei/planilha",
        files={"arquivo": ("clipei.xlsx", _clipping(DUAS_MATERIAS), _TIPO_XLSX)},
        data={"veiculos_a_criar": json.dumps(["Jornal Local"])},
    )

    assert resposta.status_code == 201, resposta.text
    criado = sessao.scalar(
        select(Instituicao).where(
            Instituicao.nome_normalizado == normalizar("Jornal Local"),
            Instituicao.tipo == "veiculo",
        )
    )
    assert criado is not None
    assert resposta.json()[0]["veiculos_criados"] == 1
