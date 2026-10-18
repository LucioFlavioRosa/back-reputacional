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

import re
from pathlib import Path

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
MIGRACAO = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "banco"
    / "migrations"
    / "0097_duas_grafias_do_mesmo_nome_nao_coexistem.sql"
)

#: O CORPUS. Cada entrada está aqui porque exercita uma parte diferente da regra,
#: e a primeira é a que de fato quebrou: o travessão colado de um documento.
CORPUS = [
    ("Posicionamento — Metas", "O TRAVESSÃO: era ele. 67 dos 87 valores reais"),
    ("Relatório  Anual", "acento mais espaço interno duplo"),
    ("  Taís Hirata  ", "espaço nas pontas"),
    ("Valor Econômico", "espaço NÃO SEPARÁVEL, que o NFKD vira espaço"),
    ("Release do 2º trimestre", "`º`, cuja decomposição é a LETRA `o`"),
    ("1ª Via do contrato", "`ª`, idem"),
    ("Área de 12,5 m²", "`²`, cuja decomposição é o DÍGITO 2"),
    ("Tarifa ½ cheia", "`½`, que decompõe em MAIS DE UM caractere"),
    ("Nota “técnica” — v2", "aspas curvas, que as duas regras descartam"),
    ("Temp. 20°C", "`°`, descartado pelas duas"),
    ("Lucro ± 3% em €", "símbolos que as duas descartam"),
    ("Straße", "`ß`, que NÃO decompõe — as duas descartam"),
    ("Œuvre", "`Œ`, idem"),
    ("Dvořák", "`ř`, acento de fora do português"),
    ("Marca™ registrada", "`™`, que o `replace` trata porque viraria `TM`"),
    ("Banco № 1", "`№`, idem — viraria `No`"),
    ("ﬁm do ciclo", "a ligadura `ﬁ`, que viraria `fi`"),
    ("Ação & Reação: o caso", "pontuação ASCII, que sobrevive às duas"),
    ("© 2026 Aegea", "`©`, descartado"),
]


#: A expressão inteira, do `lower(btrim(` até o fecho do colapso de espaço.
_EXPRESSAO = re.compile(r"lower\(btrim\(.*?'\\s\+', ' ', 'g'\)\)\)", re.S)


def _corpo() -> str:
    """O SQL que executa, sem o cabeçalho de comentário."""
    sql = MIGRACAO.read_text(encoding="utf-8")
    return sql[sql.index("\nbegin;") :]


def _expressoes_do_backfill() -> list[str]:
    """As expressões que a `0097` EMBARCA, recortadas do próprio arquivo.

    POR QUE RECORTAR, E NÃO COPIAR PARA O TESTE. A primeira versão deste teste
    comparava as COLUNAS do banco de teste com `normalizar` — e o banco de teste
    nasce vazio, então ele percorria ZERO linhas e passava por vácuo. Era
    justamente o teste que devia ter pegado o travessão, e não pegou nada.
    """
    #: SÓ O CORPO, a partir do `begin;`. O cabeçalho CITA a regra antiga
    #: (`lower(btrim(titulo))`) para explicar o defeito, e o recorte pegava
    #: aquela citação como se fosse a expressão — levando o teste a comparar
    #: comentário com `normalizar`.
    return _EXPRESSAO.findall(_corpo())


def test_as_tres_expressoes_do_backfill_sao_a_mesma_regra():
    """A MIGRATION ESCREVE A MESMA REGRA TRÊS VEZES — `titulo`, `nome`,
    `veiculo`. Este PR inteiro é sobre cópia que diverge, então conferir só uma
    delas seria supor que as outras duas acompanharam: a suposição que criou o
    defeito. Aqui as três têm de ser o MESMO texto, trocado só o nome da coluna.
    """
    achadas = _expressoes_do_backfill()
    assert len(achadas) == 3, f"esperava 3 expressões, achei {len(achadas)}"
    sem_coluna = {
        re.sub(r"\b(titulo|nome|veiculo)\b", "COLUNA", e, count=1) for e in achadas
    }
    assert len(sem_coluna) == 1, (
        "as três cópias da regra do backfill DIVERGIRAM entre si:\n"
        + "\n\n".join(sorted(sem_coluna))
    )


def _como_parametro() -> str:
    """A expressão com a coluna trocada por um parâmetro, para rodar solta.

    As três são o mesmo texto — `test_as_tres_expressoes_do_backfill_sao_a_mesma_regra`
    exige isso —, então exercitar uma exercita as três.
    """
    primeira = _expressoes_do_backfill()[0]
    return re.sub(r"\b(titulo|nome|veiculo)\b", ":valor", primeira, count=1)


@pytest.mark.parametrize("valor, por_que", CORPUS, ids=[c[0][:22] for c in CORPUS])
def test_a_expressao_do_backfill_bate_com_a_funcao_canonica(sessao, valor, por_que):
    """A REGRA EM SQL E A REGRA EM PYTHON TÊM DE DAR A MESMA CHAVE.

    Se não derem, uma referência que veio do backfill deixa de colidir com uma
    criada pela tela — o defeito que a `0097` existe para consertar, feito pela
    própria `0097`. Foi exatamente o que aconteceu na primeira versão dela.
    """
    do_sql = sessao.execute(
        text(f"select {_como_parametro()}"), {"valor": valor}
    ).scalar_one()
    assert do_sql == normalizar(valor), por_que


def test_o_veiculo_nulo_continua_nulo(sessao):
    """O RAMO QUE O CORPUS NÃO ALCANÇA: `veiculo` é anulável, e o backfill o
    trata num `case when veiculo is null`. Chave de `null` tem de ser `null`, e
    não string vazia — senão duas pessoas sem veículo colidiriam entre si."""
    sql = MIGRACAO.read_text(encoding="utf-8")
    assert "when veiculo is null then null" in sql, (
        "o ramo nulo saiu do backfill: `veiculo` é anulável e chave de nulo tem "
        "de ser nula, senão duas pessoas sem veículo colidem entre si"
    )
    valor = sessao.execute(
        text(f"select case when :valor is null then null else {_como_parametro()} end"),
        {"valor": None},
    ).scalar_one()
    assert valor is None


def _classe_da_guarda() -> str:
    sql = MIGRACAO.read_text(encoding="utf-8")
    assert "raise exception" in sql, "a guarda saiu da migration"
    inicio = sql.index("where titulo ~ '") + len("where titulo ~ '")
    return sql[inicio : sql.index("'", inicio)]


def _a_guarda_recusa(sessao, caractere: str) -> bool:
    """A GUARDA RODANDO NO POSTGRES, e não no `re` do Python.

    POR QUE ISTO IMPORTA. A primeira versão deste teste compilava a classe com o
    `re` do Python — mas quem a executa é o Postgres, e as duas engenhas não
    precisam concordar sobre `\\uXXXX` dentro de classe de caractere. O teste
    podia estar provando a coisa errada: verde aqui, guarda cega no banco.
    """
    return bool(
        sessao.execute(
            text("select :valor ~ :classe"),
            {"valor": caractere, "classe": _classe_da_guarda()},
        ).scalar_one()
    )


#: AS TRÊS CATEGORIAS DE CARACTERE NÃO-ASCII, e a guarda tem de separar as três.
#: Errar para qualquer lado custa: recusar à toa trava um deploy, deixar passar
#: grava chave errada — que é o defeito que esta migration existe para consertar.
TRATADOS = "ºª²½№™ﬁçã "
DESCARTADOS_PELAS_DUAS = "—°€©ßœ“±"
DIVERGENTES_SEM_TRATAMENTO = "①Ａ㍱ǅẛͺℂ"


@pytest.mark.parametrize("caractere", list(DIVERGENTES_SEM_TRATAMENTO))
def test_a_guarda_recusa_o_que_o_sql_nao_sabe_normalizar(sessao, caractere):
    """O SQL NÃO TEM NFKD. Para `①`, `Ａ`, `㍱` e companhia, o `normalizar`
    produz ASCII (`1`, `A`, `hpa`) e o SQL só saberia descartar — chave
    diferente, e a referência migrada deixaria de colidir com a criada na tela.

    Para esses a `0097` PARA, com a linha na mensagem, em vez de adivinhar. A
    faixa de recusa foi DERIVADA varrendo os 1.114.112 codepoints: são 1.982 que
    divergiriam, e nenhum escapa.
    """
    assert _a_guarda_recusa(sessao, caractere), (
        f"U+{ord(caractere):04X} divergiria e a guarda deixou passar"
    )


@pytest.mark.parametrize("caractere", list(TRATADOS + DESCARTADOS_PELAS_DUAS))
def test_a_guarda_nao_recusa_a_toa(sessao, caractere):
    """O OUTRO LADO, e ele custa igual: estes a regra sabe tratar — por
    `replace`, por `translate`, ou porque as duas regras os descartam. Recusar
    um deles trava um deploy por nada."""
    assert not _a_guarda_recusa(sessao, caractere), (
        f"U+{ord(caractere):04X} a guarda recusou, e não precisava"
    )


def test_a_guarda_diz_qual_coluna(sessao):
    """A MENSAGEM TEM DE MANDAR A PESSOA PARA A COLUNA CERTA.

    A primeira versão juntava `nome` e `veiculo` num `or` e imprimia sempre o
    `nome`: recusava certo, e mandava olhar a coluna errada. São três
    conferências, uma por coluna, cada uma com o seu nome na mensagem.
    """
    sql = MIGRACAO.read_text(encoding="utf-8")
    for coluna in ("referencia.titulo", "jornalista_matriz.nome", "jornalista_matriz.veiculo"):
        assert coluna in sql, f"a guarda não nomeia {coluna}"
    assert sql.count("raise exception") == 3


#: NÃO HÁ TESTE AQUI sobre a coluna já gravada no banco. Ele existia, e saiu:
#: `test_referencias.test_a_chave_do_titulo_e_a_canonica` já faz o caminho
#: inteiro pela API e lê a coluna de volta, com o usuário e o assunto que a
#: tabela exige. Um terceiro teste sobre o mesmo fato custaria uma fixture de
#: usuário para não afirmar nada novo.


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
