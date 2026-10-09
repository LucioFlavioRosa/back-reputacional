"""A carga inicial do pacote de produção das Lentes.

A PLANILHA É A FONTE, e não um semeador: 29.414 itens reais, uma aba por lente,
nas 40 colunas do padrão Aegea. Este arquivo trava a leitura — o que vira menção,
o que é descartado e o que acontece quando a mesma carga roda duas vezes.

POR QUE NÃO USAR O IMPORTADOR MENSAL. `casos_de_uso/ingerir_mencoes` lê UMA aba
por fonte, pelo mapeamento gravado em `score_fonte`, e é o caminho que a
coordenação vai usar todo mês com o padrão Aegea. A planilha de carga é outra
coisa: uma aba por LENTE, com as fontes misturadas na coluna `fonte`, entregue
uma vez. Forçar as duas pelo mesmo caminho faria o fluxo mensal carregar um
parâmetro que só a carga inicial usa.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.casos_de_uso.carga_do_pacote_das_lentes import (
    PACOTE,
    carregar,
    ler_aba_da_lente,
)
from tests.test_e2e_postgres import URL

#: As colunas do padrão que a aba da Sociedade preenche, na ordem da planilha.
COLUNAS = (
    "id_fonte",
    "mes",
    "data",
    "fonte",
    "lente",
    "empresa_citada",
    "uf",
    "classificacao",
    "tema",
    "subtema",
    "titulo_texto",
    "link",
    "autor",
    "cargo_autor",
    "perfil_autor",
    "engajamento",
    "peso_tier",
    "veiculo_rede",
)


_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    """O banco de teste, com a transação desfeita no fim.

    NUM SAVEPOINT, como a suíte de referências: a carga faz `flush` e o rollback
    externo é quem limpa. Sem o savepoint, um rollback interno derrubaria a
    transação do fixture e o teste seguinte herdaria o que este escreveu.
    """
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(
        bind=conexao, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def _planilha(linhas: list[dict]) -> bytes:
    """Uma planilha no formato da carga, com a aba da Sociedade."""
    pasta = Workbook()
    folha = pasta.active
    folha.title = "item_sociedade_digital"
    folha.append(list(COLUNAS))
    for linha in linhas:
        folha.append([linha.get(coluna) for coluna in COLUNAS])
    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


def _item(**campos) -> dict:
    base = {
        "id_fonte": "soc-2026-06-00001",
        "mes": "2026-06",
        "fonte": "Bites",
        "lente": "Sociedade digital",
        "classificacao": "Negativa",
        "perfil_autor": "Cidadão",
        "veiculo_rede": "Instagram",
        "peso_tier": 1,
    }
    return {**base, **campos}


def test_le_os_campos_do_padrao_e_traduz_os_nomes():
    """O PADRÃO E O ÍNDICE CHAMAM AS MESMAS COISAS POR NOMES DIFERENTES, e a
    tradução é o trabalho desta função: `classificacao` é o `sentimento` do
    índice, `veiculo_rede` é `veiculo`, `tema` é `tema_texto`, `empresa_citada` é
    `unidade_texto`, `cargo_autor` é `cargo`. Os sete campos novos entram com o
    nome do padrão, porque é o nome que a 0055 deu a eles."""
    conteudo = _planilha(
        [
            _item(
                empresa_citada="Águas do Rio",
                uf="RJ",
                tema="Saneamento básico",
                subtema="Ampliacao do Acesso",
                titulo_texto="Obra atrasada na zona norte",
                link="https://exemplo/1",
                autor="@diariodoporto",
                cargo_autor="Deputado Estadual",
                perfil_autor="Figura pública",
                engajamento=9926,
                data="2026-06-15",
            )
        ]
    )

    (lida,) = ler_aba_da_lente(conteudo, "sociedade").mencoes

    assert lida.mes == date(2026, 6, 1)
    assert lida.data == date(2026, 6, 15)
    assert lida.sentimento == "neg"
    assert lida.unidade_texto == "Águas do Rio"
    assert lida.tema_texto == "Saneamento básico"
    assert lida.veiculo == "Instagram"
    assert lida.cargo == "Deputado Estadual"
    assert lida.engajamento == 9926
    assert lida.id_fonte == "soc-2026-06-00001"
    # A SIGLA DO PACOTE CONVERGE PARA O NOME, como na ingestao mensal: sem
    # isto a base teria "RJ" do pacote e "Rio de Janeiro" da Clipei, duas
    # opcoes de filtro para o mesmo estado. Ver `para_uf` e a `0064`.
    assert lida.uf == "Rio de Janeiro"
    assert lida.subtema == "Ampliacao do Acesso"
    assert lida.perfil_autor == "Figura pública"
    assert lida.titulo_texto == "Obra atrasada na zona norte"
    assert lida.link == "https://exemplo/1"
    assert lida.peso_tier == 1


def test_o_mes_vem_da_coluna_mes_e_nao_da_data():
    """`mes` é a chave de tudo — a nota, o agregado, a substituição na recarga —
    e a planilha o traz como `2026-06`. Derivá-lo da `data` jogaria para o mês
    errado os 86% de itens que chegam SEM data."""
    conteudo = _planilha([_item(mes="2026-03", data=None)])

    (lida,) = ler_aba_da_lente(conteudo, "sociedade").mencoes

    assert lida.mes == date(2026, 3, 1)
    assert lida.data is None


def test_cada_fonte_da_aba_vira_a_fonte_do_indice():
    """A aba mistura as duas fontes na coluna `fonte`, e cada uma é uma linha de
    `score_fonte` diferente — é por fonte que o agregado e a substituição por mês
    acontecem. Trocar o nome por outro deixaria a menção órfã."""
    conteudo = _planilha(
        [_item(fonte="Bites"), _item(id_fonte="soc-2", fonte="Approach SL")]
    )

    leitura = ler_aba_da_lente(conteudo, "sociedade")

    assert sorted(leitura.por_fonte) == ["approach_sl", "bites"]


def test_a_linha_sem_classificacao_e_descartada_e_contada():
    """SEM SINAL NÃO HÁ CONTA. A linha entra na contagem de não classificadas —
    é o que permite a tela dizer "houve volume, ninguém classificou" em vez de
    "não houve nada"."""
    conteudo = _planilha([_item(classificacao=None), _item(id_fonte="soc-2")])

    leitura = ler_aba_da_lente(conteudo, "sociedade")

    assert len(leitura.mencoes) == 1
    assert leitura.descartes["sem classificação"] == 1


def test_a_lente_que_o_pacote_nao_tem_e_recusada_dizendo_as_que_tem():
    with pytest.raises(Exception) as erro:
        ler_aba_da_lente(_planilha([]), "inexistente")

    assert "sociedade" in str(erro.value)


def test_o_pacote_declara_a_aba_de_cada_lente():
    """O MAPA FICA NUM LUGAR SÓ. Cada etapa do rollout acrescenta uma linha aqui,
    e é por ela que a carga sabe qual aba ler."""
    assert PACOTE["sociedade"].aba == "item_sociedade_digital"
    assert PACOTE["sociedade"].fontes == {"Bites": "bites", "Approach SL": "approach_sl"}


# -- a carga no banco ---------------------------------------------------------


def test_a_carga_grava_as_mencoes_e_refaz_o_agregado(sessao):
    """O CAMINHO INTEIRO: planilha → menções com os campos do padrão → agregado
    de `score_mes_fonte`, que é de onde a nota sai."""
    from sqlalchemy import select

    from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte

    conteudo = _planilha(
        [
            _item(id_fonte="a", classificacao="Negativa", engajamento=100),
            _item(id_fonte="b", classificacao="Positiva", engajamento=None),
            _item(id_fonte="c", classificacao="Neutra", uf="SP"),
        ]
    )

    resumo = carregar(sessao, conteudo, "sociedade")

    assert resumo.gravadas == 3
    bites = sessao.scalars(
        select(ScoreFonte).where(ScoreFonte.codigo == "bites")
    ).one()
    gravadas = sessao.scalars(
        select(Mencao).where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 6, 1))
    ).all()
    assert len(gravadas) == 3
    assert {m.id_fonte for m in gravadas} == {"a", "b", "c"}

    agregado = sessao.scalars(
        select(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == bites.id, ScoreMesFonte.mes == date(2026, 6, 1)
        )
    ).all()
    assert sum(linha.mencoes for linha in agregado) == 3


def test_rodar_a_carga_DUAS_VEZES_nao_duplica(sessao):
    """A CARGA É REEXECUTÁVEL, e isto é o que torna seguro consertar a planilha e
    rodar de novo: cada mês presente no arquivo é apagado e regravado. Sem isso,
    a segunda execução dobraria o volume do mês e a nota continuaria plausível —
    o pior tipo de erro, porque não aparece."""
    from sqlalchemy import func, select

    from app.banco.tabelas_score import Mencao, ScoreFonte

    conteudo = _planilha([_item(id_fonte="a"), _item(id_fonte="b")])

    carregar(sessao, conteudo, "sociedade")
    carregar(sessao, conteudo, "sociedade")

    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    total = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 6, 1))
    )
    assert total == 2


def test_a_carga_NAO_mexe_no_mes_que_o_arquivo_nao_traz(sessao):
    """Um arquivo de junho não é uma afirmação sobre maio."""
    from sqlalchemy import func, select

    from app.banco.tabelas_score import Mencao, ScoreFonte

    carregar(sessao, _planilha([_item(id_fonte="maio", mes="2026-05")]), "sociedade")
    carregar(sessao, _planilha([_item(id_fonte="junho", mes="2026-06")]), "sociedade")

    bites = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "bites")).one()
    de_maio = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.fonte_id == bites.id, Mencao.mes == date(2026, 5, 1))
    )
    assert de_maio == 1


# =============================================================================
# os achados da revisão sobre a carga
# =============================================================================


def test_fonte_DESCONHECIDA_recusa_a_carga_em_vez_de_gravar_metade(sessao):
    """ACHADO MÉDIO DA REVISÃO, e o cenário dele é real: a planilha vem com
    "Approach" em vez de "Approach SL" — ou a coluna chega vazia porque o arquivo
    foi gerado por pipeline e a fórmula não tinha cache.

    O QUE ACONTECIA: as linhas da fonte desconhecida eram contadas em
    `descartes`, o resto era gravado, o comando imprimia o resumo e saía com
    sucesso. A lente ficava com metade das menções do mês e uma nota plausível —
    o pior tipo de erro, porque ninguém olha o stdout de uma carga que "passou".

    A CARGA NÃO ADIVINHA NOME DE FONTE, e também não grava pela metade: ela
    recusa dizendo qual nome não reconheceu e quantas linhas dependiam dele.
    """
    conteudo = _planilha(
        [_item(id_fonte="a", fonte="Bites"), _item(id_fonte="b", fonte="Approach")]
    )

    with pytest.raises(Exception) as erro:
        carregar(sessao, conteudo, "sociedade")

    assert "Approach" in str(erro.value)


def test_mes_ILEGIVEL_recusa_a_carga(sessao):
    """O MESMO CENÁRIO POR OUTRA PORTA: coluna `mes` preenchida por fórmula sem
    cache chega vazia, e cada linha dessas sairia como descarte silencioso.

    SEM MÊS NÃO HÁ ONDE GRAVAR — o mês é a chave da nota, do agregado e da
    substituição —, então uma planilha cujo mês não se lê é uma planilha que a
    carga não entendeu, e não uma planilha com algumas linhas a menos.
    """
    conteudo = _planilha([_item(id_fonte="a"), _item(id_fonte="b", mes=None)])

    with pytest.raises(Exception) as erro:
        carregar(sessao, conteudo, "sociedade")

    assert "mês" in str(erro.value) or "mes" in str(erro.value)


def test_a_linha_SEM_CLASSIFICACAO_continua_passando(sessao):
    """O CONTRAPESO, e a diferença entre os dois casos: sem classificação é um
    estado PREVISTO — a fonte mandou volume e não classificou, a tela desenha
    isso em cinza e a contagem vai para `mencao_nao_classificada`. Recusar a
    carga por isso jogaria fora um mês inteiro por causa de uma informação que o
    produto já sabe representar.
    """
    conteudo = _planilha(
        [_item(id_fonte="a"), _item(id_fonte="b", classificacao=None)]
    )

    resumo = carregar(sessao, conteudo, "sociedade")

    assert resumo.gravadas == 1
    assert resumo.descartes["sem classificação"] == 1
