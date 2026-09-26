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
    sessao.add(instituicao)
    sessao.flush()

    # O interlocutor PERTENCE à instituição da semente, e não é detalhe de
    # fixture: a recusa 4 recusa quem não pertence, então um interlocutor solto
    # aqui faria toda agenda com participante ser recusada — e o teste diria que
    # a importação está errada quando o errado seria o cenário.
    interlocutor = Interlocutor(
        nome="Ana Prado",
        nome_normalizado=normalizar("Ana Prado"),
        instituicao_id=instituicao.id,
    )
    pessoa = PessoaAegea(nome="Radamés Casseb", nome_normalizado=normalizar("Radamés Casseb"))
    sessao.add_all([interlocutor, pessoa])
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


#: Como cada "linha de aba filha" dos testes vira colunas numeradas.
#:
#: AS ABAS FILHAS DEIXARAM DE EXISTIR, mas os testes seguem dizendo "esta agenda
#: tem estes participantes" — que é a intenção, e ela não mudou. O helper faz a
#: tradução, e é por isso que dezessete testes sobreviveram à mudança de formato
#: sem precisar reescrever o que cada um quer provar.
_GRUPOS_DO_HELPER = {
    "participantes": {"Pessoa": "Interlocutor {n}", "Presença": "Presença {n}"},
    "pessoas_aegea": {
        "Pessoa": "Pessoa da Aegea {n}",
        "Papel": "Papel {n}",
        "Presença": "Presença da Aegea {n}",
    },
    "materiais": {
        "Momento": "Momento {n}",
        "Título": "Título {n}",
        "Link": "Link {n}",
        "Observação": "Observação do material {n}",
    },
}


def _com_grupos(
    agenda: dict,
    participantes: list[dict] = (),
    pessoas_aegea: list[dict] = (),
    materiais: list[dict] = (),
) -> dict:
    """A agenda com as pessoas e os materiais nas colunas numeradas dela."""
    valores = dict(agenda)
    for chave, linhas in (
        ("participantes", participantes),
        ("pessoas_aegea", pessoas_aegea),
        ("materiais", materiais),
    ):
        moldes = _GRUPOS_DO_HELPER[chave]
        for numero, linha in enumerate(linhas, start=1):
            for campo, molde in moldes.items():
                if campo in linha and linha[campo] is not None:
                    valores[molde.format(n=numero)] = linha[campo]
    return valores


def _preenchida(
    sessao,
    agendas: list[dict] = (),
    participantes: list[dict] = (),
    pessoas_aegea: list[dict] = (),
    materiais: list[dict] = (),
    declarar: dict[str, list[str]] | None = None,
) -> bytes:
    """O modelo de verdade, preenchido — o caminho que a pessoa faz.

    As pessoas e os materiais entram nas COLUNAS NUMERADAS da agenda a que
    pertencem, casada pelo `Código`. Quem não tem código vai para a primeira, que
    é o caso de quase todo teste: uma agenda só.

    `declarar` acrescenta nomes às abas de vocabulário editáveis: é a declaração
    de intenção que `classificar` distingue de digitar direto na célula.
    """
    from openpyxl import load_workbook

    conteudo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(conteudo))

    def do_codigo(linhas, codigo):
        return [
            linha
            for linha in linhas
            if linha.get("Código", codigo) == codigo or "Código" not in linha
        ]

    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for valores in agendas:
        codigo = valores.get("Código")
        completa = _com_grupos(
            valores,
            do_codigo(participantes, codigo),
            do_codigo(pessoas_aegea, codigo),
            do_codigo(materiais, codigo),
        )
        desconhecidas = set(completa) - set(cabecalho)
        assert not desconhecidas, f"coluna que não existe: {sorted(desconhecidas)}"
        folha.append([completa.get(coluna) for coluna in cabecalho])

    for chave, nomes in (declarar or {}).items():
        folha_do_vocabulario = pasta[ROTULO_DO_VOCABULARIO[chave]]
        for nome in nomes:
            # A ABA DE INSTITUIÇÕES TEM DUAS COLUNAS: nome e CATEGORIA de público.
            # É dela que o tipo nasce, e o tipo deriva a frente da agenda — a
            # importação recusa criar instituição sem categoria válida.
            if chave == "instituicoes":
                folha_do_vocabulario.append(
                    list(nome) if isinstance(nome, tuple) else [nome, "Poder Executivo"]
                )
            else:
                folha_do_vocabulario.append([nome])

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
    conteudo = _preenchida(
        sessao, agendas=[_agenda(semente, **{"Desdobra em outra interação?": "sim"})]
    )

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


def test_toda_coluna_numerada_tem_grupo():
    """O GUARDA DA COLUNA NOVA NUMA ABA FILHA.

    As colunas numeradas alimentam uma LISTA e não um campo escalar, então o
    guarda de destino da Tarefa 2 não as alcança. Sem este teste, uma coluna nova
    — um `Interlocutor 5`, um `Cargo 1` — apareceria no modelo, a pessoa a
    preencheria, e o valor não chegaria a lugar nenhum: sem erro no Excel, sem
    erro no servidor, sem nada.
    """
    assert importar_agendas.colunas_numeradas_sem_grupo() == []


def test_nenhum_vocabulario_tem_duas_fontes():
    assert set(importar_agendas.NO_BANCO) & set(importar_agendas.NO_CODIGO) == set()


# =============================================================================
# as recusas do formulário, do lado do servidor
# =============================================================================


def test_as_seis_recusas_do_front_estao_todas_classificadas():
    """O GUARDA DA DECISÃO, e o motivo desta seção existir.

    As seis recusas vivem em TypeScript, em `impedimento.ts`, e a importação é
    Python. Duplicá-las criaria duas versões da mesma verdade. O que sobrevive à
    duplicação é este teste: ele lê a lista canônica do front e exige que cada
    recusa esteja classificada aqui. Sem ele, a sétima recusa nasce no
    TypeScript e ninguém nunca pergunta se a planilha a produz.

    É o mesmo mecanismo de `_DE_TEXTO` no `Recorte` e do `DESTINO` de
    `corpo.test.ts`: uma lista que obriga a classificar o que for novo.
    """
    import pathlib
    import re

    from app.dominio.importacao_de_agendas import FORA_DA_PLANILHA, IMPEDIMENTOS_DA_PLANILHA

    ts = pathlib.Path("../front-reputacional/src/paginas/cadastro/impedimento.test.ts")
    if not ts.exists():
        pytest.skip("o repositório do front não está ao lado deste")

    no_front = set(re.findall(r"describe\((?:'|\")(\d)\. ", ts.read_text(encoding="utf-8")))

    assert no_front == {"1", "2", "3", "4", "5", "6"}, (
        f"o front agora tem as recusas {sorted(no_front)}: uma mudou de número ou "
        "nasceu uma nova. Decida se a planilha a produz e classifique-a em "
        "IMPEDIMENTOS_DA_PLANILHA ou em FORA_DA_PLANILHA."
    )
    assert set(IMPEDIMENTOS_DA_PLANILHA) | FORA_DA_PLANILHA == no_front


def test_material_com_titulo_e_sem_link_e_recusado(sessao, semente):
    """Regra 1. Na planilha ela é MAIS estrita que no formulário: o front aceita
    arquivo OU link, e uma planilha não tem como subir arquivo — então sem link
    o material não leva a lugar nenhum."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        materiais=[{"Código": "A1", "Momento": "apoio", "Título": "Nota técnica"}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any("Link" in d.mensagem for d in proposta.divergencias)


def test_material_com_link_e_sem_titulo_e_recusado(sessao, semente):
    """Regra 2. `montarCorpo` descartaria a linha, e descartar em silêncio é
    pior que recusar: a tela diria "salvo" com um material a menos."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        materiais=[{"Código": "A1", "Momento": "apoio", "Link": "https://acervo/x"}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any("Título" in d.mensagem for d in proposta.divergencias)


def test_participante_da_outra_parte_sem_pessoa_e_recusado(sessao, semente):
    """Regra 3. A planilha PRODUZ isto: a pessoa preenche a presença e esquece o
    nome, ou apaga o nome e deixa o resto. O grupo tem dado, então o vazio é
    omissão e não espaço sobrando."""
    conteudo = _preenchida(
        sessao, agendas=[_agenda(semente)], participantes=[{"Código": "A1", "Presença": "presente"}]
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any("Interlocutor 1" in d.mensagem for d in proposta.divergencias)


def test_participante_que_nao_pertence_a_instituicao_e_recusado(sessao, semente):
    """Regra 4. A planilha produz isto com facilidade: a pessoa copia a linha de
    uma agenda e troca só a instituição, deixando os participantes da anterior."""
    outra = Instituicao(
        nome="Prefeitura de Campos",
        nome_normalizado=normalizar("Prefeitura de Campos"),
        tipo="orgao",
        uf="RJ",
    )
    sessao.add(outra)
    sessao.flush()
    de_outra = Interlocutor(
        nome="Bruno Lima", nome_normalizado=normalizar("Bruno Lima"), instituicao_id=outra.id
    )
    sessao.add(de_outra)
    sessao.flush()

    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        participantes=[{"Código": "A1", "Pessoa": de_outra.nome}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    # A RECUSA MUDOU DE LUGAR: ela era da validação da entrada, no fim, e agora
    # acontece na RESOLUÇÃO da coluna, porque a resolução passou a saber de qual
    # instituição é cada interlocutor. O ganho está na mensagem: ela diz de quem a
    # pessoa é, e consertar não exige procurar em outra tela.
    assert any(
        "Prefeitura de Campos" in d.mensagem and d.trava for d in proposta.divergencias
    ), [d.mensagem for d in proposta.divergencias]


def test_participante_da_propria_instituicao_passa(sessao, semente):
    """O contrapeso da regra 4, e ele importa: sem ele, "recusa todo mundo"
    passaria por implementação correta."""
    semente["interlocutor"].instituicao_id = semente["instituicao"].id
    sessao.flush()

    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        participantes=[{"Código": "A1", "Pessoa": semente["interlocutor"].nome}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.divergencias == []


def test_pessoa_da_aegea_sem_pessoa_e_recusada(sessao, semente):
    """Regra 5, o mesmo argumento da 3 do outro lado da mesa."""
    conteudo = _preenchida(
        sessao, agendas=[_agenda(semente)], pessoas_aegea=[{"Código": "A1", "Papel": "porta_voz"}]
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any("Pessoa" in d.mensagem for d in proposta.divergencias)


def test_a_mesma_pessoa_no_mesmo_papel_e_recusada(sessao, semente):
    """Regra 6. `(pessoa, papel)` é a chave no banco, e a planilha produz a
    repetição por cópia — que é como um dia de 54 reuniões se preenche."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        pessoas_aegea=[
            {"Código": "A1", "Pessoa": semente["pessoa"].nome, "Papel": "porta_voz"},
            {"Código": "A1", "Pessoa": semente["pessoa"].nome, "Papel": "porta_voz"},
        ],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any("já está" in d.mensagem for d in proposta.divergencias)


def test_a_mesma_pessoa_em_papeis_DIFERENTES_passa(sessao, semente):
    """O contrapeso da regra 6: `(pessoa, papel)` é a chave, então a mesma
    pessoa em dois papéis é válida. Barrar aqui o que o banco aceita seria a
    importação inventando uma regra própria."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        pessoas_aegea=[
            {"Código": "A1", "Pessoa": semente["pessoa"].nome, "Papel": "porta_voz"},
            {"Código": "A1", "Pessoa": semente["pessoa"].nome, "Papel": "equipe"},
        ],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.divergencias == []
    assert len(proposta.entrada.participacoes) == 2


# =============================================================================
# os defeitos que a revisão do Codex achou
# =============================================================================

def test_instituicao_declarada_nao_trava_NENHUMA_divergencia(sessao, semente):
    """O DEFEITO 1 DA REVISÃO, e o que meu teste anterior deixou passar.

    `test_a_instituicao_DECLARADA_na_aba_nao_trava_e_espera_criacao` filtrava só
    as divergências com `campo == "instituicao_id"`. A que o Pydantic gerava tinha
    `campo == ""`, ficava fora do filtro, e o teste dava verde com a linha
    travada. Este olha TODAS — que é o que a promessa "declarar não é pendência"
    de fato significa.
    """
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente, **{"Instituição": "Prefeitura de Campinas"})],
        declarar={"instituicoes": ["Prefeitura de Campinas"]},
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    travam = [d for d in proposta.divergencias if d.trava]
    assert travam == [], [d.mensagem for d in travam]

def test_a_proposta_diz_O_QUE_vai_criar(sessao, semente):
    """Sem isto, a confirmação não tem como saber o que criar: o valor só existe
    dentro da mensagem de uma divergência, em texto."""
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente, **{"Instituição": "Prefeitura de Campinas"})],
        declarar={"instituicoes": ["Prefeitura de Campinas"]},
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert ("instituicoes", "Prefeitura de Campinas") in proposta.a_criar

def test_esperar_criacao_e_diferente_de_estar_travada(sessao, semente):
    """As duas dão `entrada is None`, e a tela precisa distingui-las: uma pede
    decisão da pessoa, a outra só espera a confirmação."""
    esperando = _preenchida(
        sessao,
        agendas=[_agenda(semente, **{"Instituição": "Prefeitura de Campinas"})],
        declarar={"instituicoes": ["Prefeitura de Campinas"]},
    )
    travada = _preenchida(
        sessao, agendas=[_agenda(semente, **{"Instituição": "Prefeitura de Campos"})]
    )

    (a,) = importar_agendas.propor(sessao, esperando)
    (b,) = importar_agendas.propor(sessao, travada)

    assert a.entrada is None and a.a_criar and not any(d.trava for d in a.divergencias)
    assert b.entrada is None and not b.a_criar and any(d.trava for d in b.divergencias)

def test_linha_filha_com_cadastro_declarado_NAO_perde_os_outros_campos(sessao, semente):
    """O DEFEITO 2: a linha inteira era descartada, levando Presença e Principal.

    O interlocutor novo ainda não tem id — quem o cria é a confirmação —, mas o
    resto do que a pessoa preencheu não pode desaparecer no caminho.
    """
    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        participantes=[
            {"Código": "A1", "Pessoa": "Bruno Novo", "Presença": "presente", "Principal": "sim"}
        ],
        declarar={"interlocutores": ["Bruno Novo"]},
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert not any(d.trava for d in proposta.divergencias)
    assert ("interlocutores", "Bruno Novo") in proposta.a_criar
    pendentes = [p for p in proposta.filhas_pendentes if p["campo_da_lista"] == "outra_parte"]
    assert pendentes, proposta.filhas_pendentes
    assert pendentes[0]["valores"]["presenca"] == "presente"
    # `principal` NÃO está aqui: ele deixou de ser um valor preenchido e passou a
    # ser implícito pela posição — o `Interlocutor 1` é o principal. O item que
    # espera cadastro guarda o que a PESSOA escreveu, e ela não escreve isso.

def test_nome_ambiguo_no_cadastro_TRAVA_em_vez_de_escolher_sozinho(sessao, semente):
    """O DEFEITO 4. A unicidade de `instituicao` é (nome_normalizado, tipo) — a
    migration 0002 diz por quê: "Águas do Rio" existe como area_interna e pode
    existir como orgao. Um dicionário nome→id achata as duas e a planilha aponta
    silenciosamente para a errada. Travar é o único comportamento honesto: só a
    pessoa sabe de qual delas ela falava."""
    gemea = Instituicao(
        nome=semente["instituicao"].nome,
        nome_normalizado=semente["instituicao"].nome_normalizado,
        tipo="orgao",
        uf="SP",
    )
    sessao.add(gemea)
    sessao.flush()

    conteudo = _preenchida(sessao, agendas=[_agenda(semente)])

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is None
    assert any(
        d.campo == "instituicao_id" and d.trava and "mais de um" in d.mensagem
        for d in proposta.divergencias
    ), [d.mensagem for d in proposta.divergencias]

def test_interlocutor_homonimo_RESOLVE_pela_instituicao_da_linha(sessao, semente):
    """A AMBIGUIDADE DEIXOU DE SER PENDÊNCIA quando a linha diz o órgão.

    Duas "Ana Prado" de instituições diferentes é comum, não exótico, e
    `interlocutor` é único por `(nome_normalizado, instituicao_id)` — o banco
    permite. Antes desta mudança a importação travava a linha pedindo que a pessoa
    escolhesse qual das duas; mas a linha JÁ DIZ o órgão da agenda, e é a mesma
    informação que o formulário do front usa para reduzir a lista. Não havia o que
    perguntar.

    O guarda da ambiguidade continua onde ainda é preciso: ver
    `test_o_homonimo_ainda_e_ambiguo_quando_a_instituicao_nao_resolve`."""
    outra = Instituicao(
        nome="Prefeitura de Campos",
        nome_normalizado=normalizar("Prefeitura de Campos"),
        tipo="orgao",
        uf="RJ",
    )
    sessao.add(outra)
    sessao.flush()
    sessao.add(
        Interlocutor(
            nome=semente["interlocutor"].nome,
            nome_normalizado=semente["interlocutor"].nome_normalizado,
            instituicao_id=outra.id,
        )
    )
    sessao.flush()

    conteudo = _preenchida(
        sessao,
        agendas=[_agenda(semente)],
        participantes=[{"Código": "A1", "Pessoa": semente["interlocutor"].nome}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert proposta.entrada is not None, [d.mensagem for d in proposta.divergencias]
    # A Ana Prado DA INSTITUIÇÃO DA AGENDA, e não a homônima da Prefeitura.
    (participante,) = proposta.entrada.outra_parte
    assert participante.interlocutor_id == semente["interlocutor"].id


def test_o_homonimo_ainda_e_ambiguo_quando_a_instituicao_nao_resolve(sessao, semente):
    """O CONTRAPESO, e sem ele a mudança acima seria perigosa.

    Se a instituição da linha não resolve — nome que não existe no cadastro —, a
    importação não tem como desfazer o homônimo, e escolher uma das duas pessoas
    seria chutar em silêncio num vínculo que nenhuma tela mostra depois. Aí a
    ambiguidade volta a ser pendência, que é o comportamento correto."""
    outra = Instituicao(
        nome="Prefeitura de Campos",
        nome_normalizado=normalizar("Prefeitura de Campos"),
        tipo="orgao",
        uf="RJ",
    )
    sessao.add(outra)
    sessao.flush()
    sessao.add(
        Interlocutor(
            nome=semente["interlocutor"].nome,
            nome_normalizado=semente["interlocutor"].nome_normalizado,
            instituicao_id=outra.id,
        )
    )
    sessao.flush()

    agenda = _agenda(semente)
    agenda["Instituição"] = "Órgão que ninguém cadastrou"
    conteudo = _preenchida(
        sessao,
        agendas=[agenda],
        participantes=[{"Código": "A1", "Pessoa": semente["interlocutor"].nome}],
    )

    (proposta,) = importar_agendas.propor(sessao, conteudo)

    assert any("mais de um" in d.mensagem and d.trava for d in proposta.divergencias), [
        d.mensagem for d in proposta.divergencias
    ]


def test_nenhuma_coluna_de_GRUPO_entra_no_mapa_de_campo_unico():
    """O DEFEITO QUE A ABA ÚNICA TROUXE, e ele passou por todos os outros testes.

    `Interlocutor 1` virou coluna da aba de agendas, e o laço das colunas
    simples a resolvia uma SEGUNDA vez — sob `campo="outra_parte"`, que não é um
    campo de valor único mas uma lista. A chave crua `outra_parte` entrava no mapa
    campo → vocabulário com o vocabulário da última coluna numerada que o laço
    via (`presenca`), e `_decisoes` a consultava para descobrir o que criar.

    O efeito: um interlocutor novo e declarado ia para `a_criar` duas vezes, a
    segunda como se fosse um cadastro de `presenca` — e a confirmação recusava
    com "não sei criar um cadastro em 'presenca'", depois de a pessoa ter
    conferido tudo. O upload dizia que estava tudo certo."""
    from app.casos_de_uso.importar_agendas import _VOCABULARIO_DO_CAMPO, GRUPOS_NUMERADOS

    cruas = [campo for campo in _VOCABULARIO_DO_CAMPO if campo in GRUPOS_NUMERADOS]

    assert cruas == []
    # E o mapa prefixado continua lá — a guarda não pode passar por o mapa estar vazio.
    assert _VOCABULARIO_DO_CAMPO["outra_parte.interlocutor_id"] == "interlocutores"
    assert _VOCABULARIO_DO_CAMPO["outra_parte.presenca"] == "presenca"
