"""Duas grafias do mesmo nome não coexistem — nem em referência, nem na matriz.

O QUE ESTAVA ERRADO. `referencia` e `jornalista_matriz` tinham cada uma a SUA
regra de chave de nome, escrita em SQL dentro do índice único, e NENHUMA DAS
DUAS TIRAVA ACENTO:

    0026  referencia         (lower(btrim(titulo)))
    0049  jornalista_matriz  (lower(regexp_replace(nome,'\\s+',' ','g')),
                              coalesce(veiculo,''))

Então "Relatório Anual" e "Relatorio Anual" entravam como DUAS referências — o
começo de duas versões circulando, que é o problema que aquela tabela existe
para acabar —, e "Taís Hirata" e "Tais Hirata" como DUAS jornalistas, contra o
que o comentário da própria `0049` promete. A `0026` ainda deixava passar espaço
interno duplo, e a `0049` não normalizava `veiculo` de jeito nenhum: a mesma
pessoa em "Valor Econômico" e em "Valor Economico" abria duas linhas.

A `0097` passou as duas para o desenho que `instituicao` já usava: a COLUNA
guarda a chave, a APLICAÇÃO a escreve com `dominio/texto.normalizar`, e o índice
é sobre a coluna. Uma regra, num lugar só, em Python.

OS CASOS PELA API DE REFERÊNCIAS ficam em `test_referencias.py`, onde moram o
cliente e os assuntos — aqui ficam a matriz, o backfill e a forma dos índices.

PRECISA DE BANCO: é sobre índice único e sobre o que o backfill gravou.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_lentes import JornalistaMatriz
from app.banco.tabelas_referencias import Referencia
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
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


# ====================================================== o backfill da migration
#: O BACKFILL É A ÚNICA VEZ QUE A REGRA APARECE EM SQL, e é de uso único: a
#: `0097` usa `translate()` com os acentos do português, porque `unaccent` é
#: extensão e o CI roda com conta comum. `translate` NÃO É a mesma coisa que o
#: NFKD + ascii do `normalizar` — perde `ß`, `œ`, `ﬁ` —, então o backfill não
#: pode ficar no escuro: estes casos recalculam TODA linha com a função canônica
#: e falham se divergir em um caractere.
@pytest.mark.parametrize(
    "tabela, origem, destino",
    [
        (Referencia, "titulo", "titulo_normalizado"),
        (JornalistaMatriz, "nome", "nome_normalizado"),
    ],
)
def test_o_backfill_bate_com_a_funcao_canonica(sessao, tabela, origem, destino):
    divergentes = [
        (getattr(linha, origem), getattr(linha, destino))
        for linha in sessao.scalars(select(tabela))
        if getattr(linha, destino) != normalizar(getattr(linha, origem))
    ]
    assert not divergentes, (
        f"{tabela.__tablename__}.{destino} não é `normalizar({origem})` em "
        f"{len(divergentes)} linha(s): {divergentes[:5]}\n\n"
        "O `translate()` do backfill da `0097` não cobriu algum caractere. "
        "Quem corrigir recalcula a coluna, e não afrouxa este teste."
    )


def test_o_veiculo_da_matriz_tambem_esta_normalizado(sessao):
    """`veiculo` ENTRAVA CRU no índice antigo, e é metade da chave."""
    divergentes = [
        (linha.veiculo, linha.veiculo_normalizado)
        for linha in sessao.scalars(select(JornalistaMatriz))
        if linha.veiculo_normalizado
        != (normalizar(linha.veiculo) if linha.veiculo else None)
    ]
    assert not divergentes, divergentes[:5]


# ============================================= o índice recusa a segunda grafia
def _jornalista(**extra) -> JornalistaMatriz:
    """SEM ATRIBUIR AS COLUNAS NORMALIZADAS, de propósito: elas são derivadas
    pelo gancho no modelo, e é isso que estes casos exercitam."""
    return JornalistaMatriz(relevancia=3, exposicao=3, proximidade=3, **extra)


# ============================================== a chave é derivada, não atribuída
def test_a_chave_sai_do_nome_sozinha():
    """SEM BANCO: é o gancho do modelo, não o índice.

    POR QUE ISTO É TESTE. A primeira versão desta mudança atribuía a coluna à
    mão em cada ponto de escrita, e a suíte achou pontos que eu não conhecia —
    cada um deles uma chance de esquecer. Coluna derivada que depende de alguém
    lembrar dela não é derivada.
    """
    linha = _jornalista(nome="  Taís   Hirata  ", veiculo="Valor Econômico")
    assert linha.nome_normalizado == "tais hirata"
    assert linha.veiculo_normalizado == "valor economico"
    #: E ACOMPANHA A RENOMEAÇÃO — era a outra metade do buraco na referência.
    linha.nome = "Tais Hirata Silva"
    assert linha.nome_normalizado == "tais hirata silva"
    linha.veiculo = None
    assert linha.veiculo_normalizado is None


def test_a_chave_do_titulo_sai_do_titulo_sozinha():
    """SEM BANCO: o mesmo gancho, do outro lado."""
    linha = Referencia(titulo="  Relatório   Anual  ")
    assert linha.titulo_normalizado == "relatorio anual"
    linha.titulo = "Relatório Trimestral"
    assert linha.titulo_normalizado == "relatorio trimestral"


@pytest.mark.parametrize(
    "primeiro, segundo, por_que",
    [
        ("Taís Hirata zz1", "Tais Hirata zz1", "acento — era o caso do índice antigo"),
        ("Taís  Hirata zz2", "Taís Hirata zz2", "espaço interno duplo"),
        (" Taís Hirata zz3 ", "Taís Hirata zz3", "espaço nas pontas"),
        ("TAÍS HIRATA zz4", "taís hirata zz4", "caixa — esta a antiga já pegava"),
    ],
)
def test_a_matriz_recusa_a_segunda_grafia(sessao, primeiro, segundo, por_que):
    from sqlalchemy.exc import IntegrityError

    sessao.add(_jornalista(nome=primeiro))
    sessao.flush()
    sessao.add(_jornalista(nome=segundo))
    with pytest.raises(IntegrityError) as erro:
        sessao.flush()
    assert "jornalista_matriz_unica_normalizada" in str(erro.value), por_que


def test_a_matriz_separa_a_mesma_pessoa_em_veiculos_diferentes(sessao):
    """O VEÍCULO CONTINUA FAZENDO PARTE DA CHAVE: a mesma jornalista em dois
    veículos são duas linhas legítimas, e isso não pode ter mudado."""
    sessao.add(_jornalista(nome="Taís Hirata zz5", veiculo="Valor Econômico"))
    sessao.add(_jornalista(nome="Taís Hirata zz5", veiculo="Folha de S.Paulo"))
    sessao.flush()
    achadas = sessao.scalars(
        select(JornalistaMatriz).where(
            JornalistaMatriz.nome_normalizado == normalizar("Taís Hirata zz5")
        )
    ).all()
    assert len(achadas) == 2


def test_a_matriz_recusa_a_segunda_grafia_do_veiculo(sessao):
    """O BURACO QUE SÓ O `veiculo_normalizado` FECHA: no índice antigo o veículo
    entrava cru, então a mesma pessoa no mesmo jornal escrito de dois jeitos
    abria duas linhas."""
    from sqlalchemy.exc import IntegrityError

    sessao.add(_jornalista(nome="Taís Hirata zz6", veiculo="Valor Econômico"))
    sessao.flush()
    sessao.add(_jornalista(nome="Taís Hirata zz6", veiculo="Valor Economico"))
    with pytest.raises(IntegrityError) as erro:
        sessao.flush()
    assert "jornalista_matriz_unica_normalizada" in str(erro.value)


def test_a_matriz_deixa_a_inativa_conviver(sessao):
    """O `where ativo` SE MANTÉM: a matriz desativa em vez de apagar, e duas
    linhas inativas da mesma pessoa são histórico, não duplicata."""
    sessao.add(_jornalista(nome="Taís Hirata zz7", ativo=False))
    sessao.add(_jornalista(nome="Tais Hirata zz7", ativo=False))
    sessao.flush()


# ===================================== a regra antiga não ficou para trás no banco
@pytest.mark.parametrize(
    "indice", ["referencia_titulo_idx", "jornalista_matriz_unica"]
)
def test_o_indice_de_expressao_antigo_nao_existe_mais(sessao, indice):
    """ENQUANTO O ÍNDICE ANTIGO EXISTIR, a regra dele continua valendo em
    paralelo — e um índice único é uma regra que recusa gravação.

    O `jornalista_matriz_unica` ENTROU AQUI POR UM ERRO MEU: eu dei ao índice
    novo o mesmo nome do antigo, e `test_dois_indices_nao_disputam_o_mesmo_nome`
    me parou — `create ... if not exists` com nome já usado é no-op silencioso.
    O novo virou `jornalista_matriz_unica_normalizada`, e o antigo tem de ter
    ido embora de verdade.
    """
    assert (
        sessao.execute(text("select to_regclass(:nome)"), {"nome": indice}).scalar()
        is None
    ), f"{indice} ainda existe — a `0097` não derrubou a regra antiga"


@pytest.mark.parametrize(
    "indice, coluna",
    [
        ("referencia_titulo_normalizado_idx", "titulo_normalizado"),
        ("jornalista_matriz_unica_normalizada", "nome_normalizado"),
    ],
)
def test_o_indice_novo_e_sobre_a_coluna_e_nao_sobre_uma_expressao(
    sessao, indice, coluna
):
    """A PROVA DE QUE A REGRA SAIU DO SQL. Se o índice voltar a ser expressão, a
    chave volta a ter duas implementações — e foi assim que o defeito nasceu."""
    definicao = sessao.execute(
        text("select indexdef from pg_indexes where indexname = :nome"),
        {"nome": indice},
    ).scalar_one()
    assert coluna in definicao, definicao
    for proibido in ("lower(", "regexp_replace", "translate(", "unaccent"):
        assert proibido not in definicao, (
            f"{indice} voltou a normalizar dentro do SQL: {definicao}"
        )
