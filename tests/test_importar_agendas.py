"""A linha da planilha vira proposta de interação — ou vira divergência.

OS TESTES PREENCHEM O MODELO DE VERDADE. Em vez de montar um `.xlsx` à mão com
o cabeçalho que este arquivo acha que existe, eles chamam
`modelo_de_importacao.gerar()`, abrem o resultado e escrevem nas linhas — que é
exatamente o que a pessoa faz. Isso amarra as duas metades da promessa do
módulo de domínio: um arquivo que o gerador produz e o leitor não entende
quebra AQUI, e não nas mãos de quem preencheu 54 agendas.
"""

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import (
    AreaPessoa,
    Clima,
    FormatoInteracao,
    Status,
    Tema,
    UnidadeNegocio,
)
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso import importar_agendas, modelo_de_importacao
from app.dominio.importacao_de_agendas import ROTULO_DO_VOCABULARIO
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    """Uma sessão que se desfaz no fim — nada deste arquivo sobra no banco."""
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


@pytest.fixture
def semente(sessao):
    """Os cadastros que as agendas dos testes referenciam.

    Os DICIONÁRIOS vêm semeados no banco de teste e são lidos, não criados: são
    vocabulário fechado ou administrado, e inventar linha nova neles aqui
    testaria um estado que a aplicação não produz.
    """
    instituicao = Instituicao(
        nome="Valor Econômico",
        nome_normalizado=normalizar("Valor Econômico"),
        tipo="veiculo",
        uf="SP",
    )
    interlocutor = Interlocutor(nome="Ana Prado", nome_normalizado=normalizar("Ana Prado"))
    pessoa = PessoaAegea(nome="Radamés Casseb", nome_normalizado=normalizar("Radamés Casseb"))
    sessao.add_all([instituicao, interlocutor, pessoa])
    sessao.flush()

    def primeiro(tabela):
        linha = sessao.scalars(select(tabela).limit(1)).first()
        assert linha is not None, f"o banco de teste está sem {tabela.__name__} semeado"
        return linha

    return {
        "instituicao": instituicao,
        "interlocutor": interlocutor,
        "pessoa": pessoa,
        "formato": primeiro(FormatoInteracao),
        "unidade": primeiro(UnidadeNegocio),
        "tema": primeiro(Tema),
        "area": primeiro(AreaPessoa),
        "status": primeiro(Status),
        "clima": primeiro(Clima),
    }


def _preenchida(
    sessao,
    agendas: list[dict] = (),
    participantes: list[dict] = (),
    pessoas_aegea: list[dict] = (),
    materiais: list[dict] = (),
    declarar: dict[str, list[str]] | None = None,
) -> bytes:
    """O modelo de verdade, preenchido — o caminho que a pessoa faz.

    `declarar` acrescenta nomes às abas de vocabulário editáveis: é a declaração
    de intenção que `classificar` distingue de digitar direto na célula.
    """
    from openpyxl import load_workbook

    conteudo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(conteudo))

    por_aba = {
        "Agendas": agendas,
        "Participantes": participantes,
        "Pessoas da Aegea": pessoas_aegea,
        "Materiais": materiais,
    }
    for nome, linhas in por_aba.items():
        folha = pasta[nome]
        cabecalho = [celula.value for celula in next(folha.iter_rows())]
        for valores in linhas:
            desconhecidas = set(valores) - set(cabecalho)
            assert not desconhecidas, f"coluna que não existe em {nome!r}: {sorted(desconhecidas)}"
            folha.append([valores.get(coluna) for coluna in cabecalho])

    for chave, nomes in (declarar or {}).items():
        folha = pasta[ROTULO_DO_VOCABULARIO[chave]]
        for nome in nomes:
            folha.append([nome])

    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


def _agenda(semente, **mudancas) -> dict:
    """Uma agenda que resolve inteira: os três campos que `InteracaoEntrada` exige."""
    base = {
        "Código": "A1",
        "Data": date(2026, 9, 25),
        "Instituição": semente["instituicao"].nome,
        "UF": "SP",
    }
    return {**base, **mudancas}


# =============================================================================
# o vocabulário lido do banco
# =============================================================================


def test_todo_vocabulario_da_planilha_sabe_de_onde_vem(sessao):
    """O GUARDA DA TABELA DE FONTES.

    O domínio descreve QUAIS vocabulários a planilha tem; este módulo sabe de
    qual tabela cada um sai. Sem este teste, um vocabulário novo no domínio
    geraria aba e lista suspensa no modelo e não resolveria contra nada —
    divergência em toda linha que o usasse, sem nada explicar por quê.
    """
    from app.dominio.importacao_de_agendas import VOCABULARIOS_EDITAVEIS, VOCABULARIOS_FECHADOS

    descritos = VOCABULARIOS_EDITAVEIS | VOCABULARIOS_FECHADOS
    mapeados = set(importar_agendas.NO_BANCO) | set(importar_agendas.NO_CODIGO)

    assert descritos == mapeados


def test_o_vocabulario_traz_o_nome_que_a_pessoa_LE(sessao, semente):
    """A aba de vocabulário lista `nome`, não `codigo`: "Positivo", não
    "propositivo". É o nome que a pessoa reconhece."""
    lido = importar_agendas.vocabularios(sessao)

    assert semente["clima"].nome in lido["climas"]


# =============================================================================
# o caminho que resolve
# =============================================================================


def test_a_agenda_limpa_vira_uma_entrada_valida(sessao, semente):
    conteudo = _preenchida(sessao, agendas=[_agenda(semente)])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.divergencias == []
    assert proposta.entrada is not None
    assert proposta.entrada.instituicao_id == semente["instituicao"].id


def test_o_rotulo_do_dicionario_resolve_para_o_CODIGO_gravado(sessao, semente):
    """A pessoa escolhe "Positivo" na lista e o banco guarda `propositivo`.
    Mandar o rótulo adiante daria 422 na criação, e o 422 falaria de um campo
    que a pessoa preencheu certo."""
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, **{"Clima": semente["clima"].nome})])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.divergencias == []
    assert proposta.entrada.clima == semente["clima"].codigo


def test_o_rotulo_do_dicionario_resolve_para_o_ID_quando_o_campo_e_id(sessao, semente):
    conteudo = _preenchida(
        sessao, agendas=[_agenda(semente, **{"Tipo de interação": semente["formato"].nome})]
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada.formato_interacao_id == semente["formato"].id


def test_as_colunas_numeradas_de_tema_viram_UMA_lista(sessao, semente):
    """Tema 1, Tema 2 e Tema 3 são três colunas e um campo só."""
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, **{"Tema 1": semente["tema"].nome})])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada.temas == [semente["tema"].id]


def test_a_coluna_vazia_nao_entra_na_lista(sessao, semente):
    """Tema 2 e Tema 3 em branco não podem virar dois `None` na lista."""
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, **{"Tema 1": semente["tema"].nome})])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert len(proposta.entrada.temas) == 1


def test_o_vocabulario_de_CODIGO_resolve_pelo_proprio_codigo(sessao, semente):
    """`modalidade` não tem tabela: a lista mora em `dominio/interacao.py`. E
    normalizar faz "Híbrida" casar com o código `hibrida`, acento e tudo."""
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, **{"Modalidade": "Híbrida"})])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.divergencias == []
    assert proposta.entrada.modalidade == "hibrida"


def test_sim_e_nao_viram_booleano(sessao, semente):
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, **{"Prevê desdobramento": "sim"})])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada.preve_desdobramento is True


# =============================================================================
# as abas filhas
# =============================================================================


def test_o_participante_da_outra_parte_entra_na_proposta(sessao, semente):
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        participantes=[
            {"Código": "A1", "Pessoa": semente["interlocutor"].nome, "Principal": "sim"}
        ],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert len(proposta.entrada.outra_parte) == 1
    assert proposta.entrada.outra_parte[0].interlocutor_id == semente["interlocutor"].id
    assert proposta.entrada.outra_parte[0].principal is True


def test_a_pessoa_da_aegea_entra_na_proposta(sessao, semente):
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        pessoas_aegea=[{"Código": "A1", "Pessoa": semente["pessoa"].nome, "Papel": "porta_voz"}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert len(proposta.entrada.participacoes) == 1
    assert proposta.entrada.participacoes[0].pessoa_aegea_id == semente["pessoa"].id


def test_o_material_entra_na_proposta(sessao, semente):
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        materiais=[
            {
                "Código": "A1",
                "Momento": "apoio",
                "Título": "Nota técnica",
                "Link": "https://acervo/nota",
            }
        ],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert len(proposta.entrada.materiais) == 1
    assert proposta.entrada.materiais[0].titulo == "Nota técnica"


def test_a_linha_filha_vai_para_a_AGENDA_do_codigo_dela(sessao, semente):
    """Com duas agendas, o participante não pode cair na errada."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente, **{"Código": "A1"}), _agenda(semente, **{"Código": "A2"})],
        participantes=[{"Código": "A2", "Pessoa": semente["interlocutor"].nome}],
    )

    primeira, segunda = importar_agendas.propor(sessao, conteudo)

    assert primeira.entrada.outra_parte == []
    assert len(segunda.entrada.outra_parte) == 1


# =============================================================================
# as divergências
# =============================================================================


def test_a_data_ausente_e_divergencia_que_trava(sessao, semente):
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, Data=None)])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(d.trava for d in proposta.divergencias)


def test_a_data_ilegivel_e_divergencia_que_trava(sessao, semente):
    """O leitor deixou passar crua de propósito; é aqui que ela vira pendência."""
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, Data="25 de setembro")])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(d.campo == "data_interacao" and d.trava for d in proposta.divergencias)


def test_a_uf_ausente_trava_porque_InteracaoEntrada_a_exige(sessao, semente):
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, UF=None)])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(d.campo == "uf" for d in proposta.divergencias)


def test_a_instituicao_desconhecida_trava(sessao, semente):
    conteudo = _preenchida(
        sessao, agendas=[_agenda(semente, **{"Instituição": "Prefeitura de Campinas"})]
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(d.campo == "instituicao_id" and d.trava for d in proposta.divergencias)


def test_a_instituicao_DECLARADA_na_aba_nao_trava_e_espera_criacao(sessao, semente):
    """A REGRA CENTRAL vista de fora: declarar na aba editável é pedir cadastro.
    A proposta ainda não tem id — quem cria é a confirmação (Tarefa 11) — mas
    isto não é pendência que a pessoa precise resolver."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente, **{"Instituição": "Prefeitura de Campinas"})],
        declarar={"instituicoes": ["Prefeitura de Campinas"]},
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    a_criar = [d for d in proposta.divergencias if d.campo == "instituicao_id"]
    assert a_criar, "o cadastro a criar precisa aparecer na conferência"
    assert not any(d.trava for d in a_criar)


def test_valor_fora_de_vocabulario_FECHADO_trava(sessao, semente):
    """Um clima que não existe iria a 422 na criação. Travar aqui é o que faz a
    pessoa descobrir na conferência, e não depois de confirmar."""
    conteudo = _preenchida(sessao, agendas=[_agenda(semente, **{"Clima": "Eufórico"})])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(d.campo == "clima" and d.trava for d in proposta.divergencias)


def test_a_mesma_instituicao_desconhecida_em_doze_linhas_e_UMA_divergencia(sessao, semente):
    """É o que faz a conferência escalar: uma decisão, doze linhas."""
    agendas = [
        _agenda(semente, **{"Código": f"A{i}", "Instituição": "Prefeitura de Campinas"})
        for i in range(12)
    ]

    propostas = importar_agendas.propor(sessao, _preenchida(sessao, agendas=agendas))
    valores = {d.valor for p in propostas for d in p.divergencias if d.campo == "instituicao_id"}

    assert valores == {"Prefeitura de Campinas"}


def test_uma_agenda_torta_nao_derruba_as_outras(sessao, semente):
    """O argumento da fronteira do leitor, provado do lado de cá."""
    conteudo = _preenchida(
        sessao,
        agendas=[
            _agenda(semente, **{"Código": "A1"}),
            _agenda(semente, **{"Código": "A2"}, Data=None),
            _agenda(semente, **{"Código": "A3"}),
        ],
    )

    propostas = importar_agendas.propor(sessao, conteudo)

    assert [p.entrada is not None for p in propostas] == [True, False, True]


# =============================================================================
# o custo
# =============================================================================


def _consultas_para_propor(sessao, conteudo: bytes) -> int:
    """Conta as consultas de um `propor`, no molde de
    `tests/test_leitura_sem_consulta_por_linha.py`. Aquele arquivo tem a mesma
    contagem presa a um helper privado, e repetir seis linhas é melhor que
    exportar o interno de outro teste."""
    from sqlalchemy import event

    contagem = 0

    def contar(*_):
        nonlocal contagem
        contagem += 1

    conexao = sessao.connection()
    event.listen(conexao, "before_cursor_execute", contar)
    try:
        importar_agendas.propor(sessao, conteudo)
    finally:
        event.remove(conexao, "before_cursor_execute", contar)
    return contagem


def test_o_custo_nao_cresce_com_o_numero_de_agendas(sessao, semente):
    """500 agendas não podem virar 500 buscas de instituição.

    A GARANTIA É POR INVARIÂNCIA, e não por um teto absoluto: um teto passa a
    ser escolhido para caber no que o código faz hoje, e sobe calado quando
    alguém acrescenta uma consulta. Comparar 3 com 30 não tem como subir
    calado — a única forma de o número mudar entre os dois é alguém ter voltado
    a consultar por linha. É o mesmo argumento, e o mesmo formato, de
    `test_o_numero_de_consultas_nao_cresce_com_as_linhas`.
    """

    def arquivo(quantas: int) -> bytes:
        return _preenchida(
            sessao, agendas=[_agenda(semente, **{"Código": f"A{i}"}) for i in range(quantas)]
        )

    tres, trinta = arquivo(3), arquivo(30)

    com_tres = _consultas_para_propor(sessao, tres)
    assert com_tres > 0, "o contador não está escutando a conexão da sessão"

    com_trinta = _consultas_para_propor(sessao, trinta)

    assert com_trinta == com_tres, (
        f"propor 30 agendas custou {com_trinta} consultas e propor 3 custou "
        f"{com_tres}: alguma coisa voltou a consultar por linha"
    )


def test_toda_coluna_de_aba_filha_tem_campo():
    """O GUARDA DA COLUNA NOVA NUMA ABA FILHA.

    As colunas das abas filhas têm `campo=""` em `FORMATO`, porque não alimentam
    um campo da interação e sim um item de lista — então o guarda de destino da
    Tarefa 2 não as alcança. Sem este teste, uma coluna nova em Participantes
    apareceria no modelo, a pessoa a preencheria, e o valor não chegaria a lugar
    nenhum: sem erro no Excel, sem erro no servidor, sem nada.
    """
    assert importar_agendas.colunas_de_aba_filha_sem_campo() == []


def test_nenhum_vocabulario_tem_duas_fontes():
    assert set(importar_agendas.NO_BANCO) & set(importar_agendas.NO_CODIGO) == set()
