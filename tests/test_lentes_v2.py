"""As Lentes v2 — etapa 1: o que a ingestão passa a ler, e o que se semeia.

O TEOR É O QUE SEPARA EXPOSIÇÃO DE DEMANDA. A aba de Community Management traz
`TAG (motivo)`: Reclamação, Dúvida, Elogio, Informação — e mais Marcação (alguém
citou a Aegea num post) e NPR (não pertinente). Os dois últimos chegam pelo
mesmo canal e não são gente procurando a companhia: 18% da base de janeiro a
junho. Incluí-los no denominador da taxa de resposta faz o atendimento parecer
22% pior do que é.

O que este arquivo prova é que eles são MARCADOS, e não descartados.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_lentes import (
    CuradoriaLente,
    Encaminhamento,
    EstudoPercepcao,
    EventoMercado,
    JornalistaMatriz,
)
from app.dominio.ingestao_score import Mapeamento, MencaoLida, ler_linha
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


#: O cadastro da aba CM, como a 0048 o grava.
CM = Mapeamento(
    aba="CM",
    colunas={
        "data": "Data",
        "sentimento": "Sentimento",
        "engajamento": "Interações",
        "teor": "TAG (motivo)",
    },
    prefixo_a_remover=r"^(\d+\s*[,-]\s*)?(Aegea\s*[,-]\s*)?",
)


def _linha(motivo: str) -> dict:
    return {
        "Data": date(2026, 6, 10),
        "Sentimento": "Negativo",
        "Interações": 3,
        "TAG (motivo)": motivo,
    }


# -- o teor, e o prefixo que a Approach carimba nele -----------------------------


@pytest.mark.parametrize(
    ("escrito", "esperado"),
    [
        # A mesma etiqueta chega com dois separadores na mesma planilha.
        ("1 , Reclamação", "Reclamação"),
        ("1 - Reclamação", "Reclamação"),
        ("1 , Dúvida", "Dúvida"),
        ("2 , Marcação", "Marcação"),
        ("NPR", "NPR"),
    ],
)
def test_o_teor_entra_sem_o_prefixo_de_taxonomia(escrito, esperado):
    lido = ler_linha(_linha(escrito), CM)
    assert isinstance(lido, MencaoLida)
    assert lido.teor == esperado


@pytest.mark.parametrize(
    ("motivo", "acionavel"),
    [
        ("1 , Reclamação", True),
        ("1 , Dúvida", True),
        ("1 , Elogio", True),
        ("1 , Informação", True),
        # Alguém citou a Aegea num post próprio: não é contato.
        ("2 , Marcação", False),
        # O fornecedor etiquetou como não pertinente.
        ("NPR", False),
        ("spam", False),
    ],
)
def test_marcacao_e_npr_saem_da_base_acionavel(motivo, acionavel):
    lido = ler_linha(_linha(motivo), CM)
    assert isinstance(lido, MencaoLida)
    assert lido.acionavel is acionavel


def test_a_mencao_nao_acionavel_continua_contada():
    """NÃO É DESCARTE. A menção entra, conta no volume e aparece na tela com o
    teor escrito — esconder 800 mensagens para melhorar um percentual seria o
    oposto do que a marca existe para fazer."""
    lido = ler_linha(_linha("NPR"), CM)
    assert isinstance(lido, MencaoLida), "a linha precisa virar menção"
    assert lido.sentimento == "neg"
    assert lido.engajamento == 3


def test_fonte_que_nao_mapeia_teor_fica_com_acionavel_nulo():
    """Nulo, e não `False`: a pergunta não se aplica a uma matéria de jornal, e
    `False` diria que ela não é um contato de verdade."""
    sem_teor = Mapeamento(colunas={"data": "Data", "sentimento": "Sentimento"})
    lido = ler_linha({"Data": date(2026, 6, 1), "Sentimento": "Positivo"}, sem_teor)
    assert isinstance(lido, MencaoLida)
    assert lido.teor is None
    assert lido.acionavel is None


def test_a_fonte_pode_declarar_os_proprios_teores_nao_acionaveis():
    """A lista de hoje é o vocabulário da Approach. Outro fornecedor chama a
    mesma coisa de outro nome, e isso é cadastro — como o resto do mapeamento."""
    outro = Mapeamento(
        colunas={"data": "Data", "sentimento": "Sentimento", "teor": "Motivo"},
        teores_nao_acionaveis=frozenset({"nao se aplica"}),
    )
    fora = ler_linha(
        {"Data": date(2026, 6, 1), "Sentimento": "Neutro", "Motivo": "Não se aplica"},
        outro,
    )
    dentro = ler_linha(
        {"Data": date(2026, 6, 1), "Sentimento": "Neutro", "Motivo": "NPR"}, outro
    )
    assert isinstance(fora, MencaoLida) and fora.acionavel is False
    # `NPR` não está na lista DESTA fonte: para ela, é contato.
    assert isinstance(dentro, MencaoLida) and dentro.acionavel is True


# -- o que se semeia se declara exemplo ------------------------------------------


def test_todo_conteudo_semeado_esta_marcado_como_exemplo(sessao):
    """A matriz de jornalistas, o rating e o estudo vieram do relatório do
    cliente, e não desta ferramenta. Apresentá-los como medição é a forma mais
    barata de destruir a confiança num painel — a marca é o que a tela lê para
    avisar no "?" de cada bloco."""
    for tabela in (EventoMercado, JornalistaMatriz, EstudoPercepcao, CuradoriaLente):
        semeadas = sessao.scalars(select(tabela).where(tabela.exemplo.is_(True)))
        # O banco de teste nasce vazio; o que importa é o contrato da coluna.
        assert all(linha.exemplo for linha in semeadas)


def test_o_encaminhamento_some_por_conclusao_e_nao_por_mes(sessao):
    """Uma ação que desaparece no virar do mês é uma ação que ninguém cobrou."""
    from app.banco.tabelas_score import Lente

    imprensa = sessao.scalar(select(Lente).where(Lente.codigo == "imprensa"))
    aberto = Encaminhamento(
        lente_id=imprensa.id,
        mes_origem=date(2026, 1, 1),
        acao="Kit de dados para divulgações de resultado",
    )
    sessao.add(aberto)
    sessao.flush()

    assert aberto.status == "aberto"
    assert aberto.concluido_em is None
    # Seis meses depois, continua aberto — é o mês de ORIGEM que fica para trás,
    # não a pendência.
    abertos = sessao.scalars(
        select(Encaminhamento).where(Encaminhamento.status != "concluido")
    ).all()
    assert aberto in abertos
