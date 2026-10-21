"""Os registros de um grupo do quadro da janela — o que abre ao clicar nele.

O PEDIDO: "se eu clicar em alguma dessas opções quero que abra um modal com os
registros do tema ou pilar, assim como fazemos nas lentes no KPI reputacional".

O QUE ESTES TESTES PROTEGEM, e é tudo a mesma coisa dita de quatro formas: a
lista TEM DE BATER com o número que está ao lado dela no quadro.

* a menção SEM DATA fica de fora, como no quadro — a rota da Base das lentes a
  traria, porque lá ela é achável pelo mês, de propósito;
* a fonte DESLIGADA na calibração fica de fora, como no quadro;
* o grupo é o ID, e não o nome: nome de N2 não é único, e pelo nome a lista
  traria o homônimo de outro pilar;
* e o total é o total, com a página sendo só uma fatia dele.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import BlocoTema, MacroTema
from app.banco.tabelas_score import Lente, Mencao, ScoreConfig, ScoreFonte
from app.casos_de_uso import impacto_na_janela
from app.dominio.erros import NaoEncontrado
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: O dia clicado e a janela padrão (15 dias): de 27/08 a 10/09.
ATE = date(2026, 9, 10)


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


@pytest.fixture
def imprensa(sessao) -> ScoreFonte:
    lente = sessao.scalar(select(Lente).where(Lente.codigo == "imprensa"))
    return sessao.scalar(
        select(ScoreFonte).where(ScoreFonte.lente_id == lente.id).order_by(ScoreFonte.ordem)
    )


def _fonte_da_lente(sessao, codigo: str) -> ScoreFonte:
    """A fonte ATIVA da lente, pelo cadastro.

    PELO CADASTRO, e não por código escrito aqui: a Institucional trocou de
    fonte (o CRM saiu, a Clipei recortada entrou) e vai trocar de novo se a
    lista mudar de dono. O `ativo` é o que separa as duas.
    """
    lente = sessao.scalar(select(Lente).where(Lente.codigo == codigo))
    assert lente is not None, f"a lente {codigo} tinha de estar cadastrada"
    fonte = sessao.scalar(
        select(ScoreFonte)
        .where(ScoreFonte.lente_id == lente.id, ScoreFonte.ativo.is_(True))
        .order_by(ScoreFonte.ordem)
    )
    assert fonte is not None, f"a lente {codigo} tinha de ter fonte ativa"
    return fonte


@pytest.fixture
def mercado(sessao) -> ScoreFonte:
    return _fonte_da_lente(sessao, "mercado")


@pytest.fixture
def institucional(sessao) -> ScoreFonte:
    return _fonte_da_lente(sessao, "institucional")


@pytest.fixture
def sociedade(sessao) -> ScoreFonte:
    """Uma lente de clipping que o modal NÃO lista — ver o teste que a usa."""
    return _fonte_da_lente(sessao, "sociedade")


@pytest.fixture
def tema(sessao) -> MacroTema:
    """Um tema estratégico novo, para não depender do cadastro de produção."""
    pilar = sessao.scalars(select(BlocoTema).order_by(BlocoTema.id)).first()
    feito = MacroTema(
        nome="Tema da janela zz1",
        codigo="zz-janela-1",
        bloco_tema_id=pilar.id,
        ordem=901,
    )
    sessao.add(feito)
    sessao.flush()
    return feito


def _mencao(sessao, fonte, tema_id, *, data, titulo="Matéria", sentimento="pos"):
    linha = Mencao(
        fonte_id=fonte.id,
        mes=date(data.year, data.month, 1) if data else date(2026, 9, 1),
        data=data,
        sentimento=sentimento,
        veiculo="Valor Econômico",
        titulo_texto=titulo,
        link="https://exemplo/" + titulo,
        tier="muito_relevante",
        macro_tema_id=tema_id,
    )
    sessao.add(linha)
    sessao.flush()
    return linha


def test_lista_as_mencoes_do_grupo_na_janela(sessao, imprensa, tema):
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Dentro A")
    _mencao(sessao, imprensa, tema.id, data=date(2026, 8, 28), titulo="Dentro B")
    #: FORA DA JANELA (a janela começa em 27/08).
    _mencao(sessao, imprensa, tema.id, data=date(2026, 8, 20), titulo="Fora")

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)

    assert lidos.total == 2
    assert [i.titulo for i in lidos.itens] == ["Dentro A", "Dentro B"]
    #: A MAIS NOVA PRIMEIRO, que é como a pessoa lê uma lista de matérias.
    assert lidos.itens[0].data == date(2026, 9, 2)
    assert lidos.itens[0].link == "https://exemplo/Dentro A"


def test_a_mencao_SEM_DATA_fica_de_fora(sessao, imprensa, tema):
    """O quadro a exclui e a conta à parte; a lista tem de excluí-la também.

    É a primeira das três razões de esta rota existir em vez de reusar a da Base
    das lentes: lá a linha sem data é achável PELO MÊS, de propósito — e aqui
    isso traria de volta exatamente o que o quadro tirou.
    """
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Com data")
    _mencao(sessao, imprensa, tema.id, data=None, titulo="Sem data")

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)

    assert lidos.total == 1
    assert [i.titulo for i in lidos.itens] == ["Com data"]


def test_a_fonte_DESLIGADA_na_calibracao_fica_de_fora(sessao, imprensa, tema):
    """A segunda razão: o impacto do quadro ignora fonte desligada."""
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Da fonte ligada")
    assert impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id).total == 1

    sessao.add(ScoreConfig(fontes_desligadas=[imprensa.codigo]))
    sessao.flush()

    assert impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id).total == 0


def test_o_grupo_e_o_ID_e_nao_o_nome(sessao, imprensa, tema):
    """A terceira razão, e a mais silenciosa das três.

    `macro_tema.nome` NÃO é único (só o `codigo` é), e o quadro agrupa por id
    desde o achado dos homônimos. Filtrando por nome, clicar em "Tarifa" traria
    a "Tarifa" de outro pilar junto — e a lista mostraria mais linhas do que a
    contagem do quadro, sem explicação na tela.
    """
    outro_pilar = sessao.scalars(select(BlocoTema).order_by(BlocoTema.id.desc())).first()
    homonimo = MacroTema(
        nome=tema.nome,
        codigo="zz-janela-2",
        bloco_tema_id=outro_pilar.id,
        ordem=902,
    )
    sessao.add(homonimo)
    sessao.flush()
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Do tema pedido")
    _mencao(sessao, imprensa, homonimo.id, data=date(2026, 9, 3), titulo="Do homônimo")

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)

    assert lidos.total == 1
    assert [i.titulo for i in lidos.itens] == ["Do tema pedido"]


def test_a_PAGINA_e_uma_fatia_do_TOTAL(sessao, imprensa, tema):
    #: Sem o total, a tela não tem como dizer "50 de 312" — e uma lista cortada
    #: sem dizer que cortou é a mesma mentira do quadro que parece o todo.
    for dia in range(1, 6):
        _mencao(sessao, imprensa, tema.id, data=date(2026, 9, dia), titulo=f"M{dia}")

    primeira = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id, tamanho=2)
    segunda = impacto_na_janela.registros(
        sessao, ate=ATE, grupo=tema.id, tamanho=2, pagina=2
    )

    assert primeira.total == 5
    assert len(primeira.itens) == 2
    assert segunda.total == 5
    #: E NÃO SE REPETEM: a ordem tem desempate por id, senão o mesmo dia podia
    #: devolver a mesma linha nas duas páginas.
    assert {i.id for i in primeira.itens}.isdisjoint({i.id for i in segunda.itens})


def test_a_mencao_COM_PILAR_E_SEM_TEMA_entra_no_n1_e_so_nele(sessao, imprensa, tema):
    """O caso dos 72.590 que a 0098 mediu, e a razão de este teste existir.

    A menção classificada no PILAR e não no TEMA é a maior população da base. No
    nível do pilar ela conta; no nível do tema ela não tem grupo, e o quadro a
    diz na linha "sem o nível pedido". Se a lista a trouxesse no n2, o modal
    mostraria mais linhas do que o número que a pessoa clicou; se a deixasse de
    fora no n1, mostraria menos.
    """
    pilar = sessao.get(BlocoTema, tema.bloco_tema_id)
    so_pilar = _mencao(sessao, imprensa, None, data=date(2026, 9, 4), titulo="Só pilar")
    so_pilar.bloco_tema_id = pilar.id
    com_tema = _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 5), titulo="Com tema")
    com_tema.bloco_tema_id = pilar.id
    sessao.flush()

    no_pilar = impacto_na_janela.registros(sessao, ate=ATE, grupo=pilar.id, nivel="n1")
    no_tema = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)

    assert {i.titulo for i in no_pilar.itens} == {"Só pilar", "Com tema"}
    assert [i.titulo for i in no_tema.itens] == ["Com tema"]


def test_o_PILAR_tambem_abre(sessao, imprensa, tema):
    #: A chave N1/N2 vale aqui como vale no quadro: o nível pedido escolhe a
    #: coluna da menção.
    pilar = sessao.get(BlocoTema, tema.bloco_tema_id)
    linha = _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Do pilar")
    linha.bloco_tema_id = pilar.id
    sessao.flush()

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=pilar.id, nivel="n1")

    assert [i.titulo for i in lidos.itens] == ["Do pilar"]


# -- as três lentes ------------------------------------------------------------


def test_o_modal_traz_AS_TRES_LENTES_e_cada_linha_diz_a_sua(
    sessao, imprensa, mercado, institucional, tema
):
    """O pedido de 20/10/2026, e a coluna que ele exige junto.

    "quero adicionar os registros de mercado e institucional também. e deve ter
    uma coluna extra no modal para identificar de qual lente vem o registro."

    A COLUNA NÃO É ENFEITE: as três lentes leem o MESMO export da Clipei (a
    Imprensa inteiro, as outras duas recortadas pela lista de veículos), então
    a mesma matéria pode aparecer duas vezes na lista. Sem dizer de onde cada
    linha veio, a repetição parece erro do sistema.
    """
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Da imprensa")
    _mencao(sessao, mercado, tema.id, data=date(2026, 9, 3), titulo="Do mercado")
    _mencao(sessao, institucional, tema.id, data=date(2026, 9, 4), titulo="Da institucional")

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)

    assert lidos.total == 3
    #: QUAL LINHA VEIO DE QUAL LENTE, e não só quantas: trocar os rótulos de
    #: lugar passaria por qualquer conferência de contagem.
    assert {(i.titulo, i.lente) for i in lidos.itens} == {
        ("Da imprensa", "imprensa"),
        ("Do mercado", "mercado"),
        ("Da institucional", "institucional"),
    }
    #: E O NOME VEM DO CADASTRO, não de um dicionário na tela: a `0061` já
    #: renomeou uma lente por migration, e um mapa no front envelheceria calado.
    nomes = {
        codigo: nome
        for codigo, nome in sessao.execute(select(Lente.codigo, Lente.nome)).all()
    }
    assert all(i.lente_nome == nomes[i.lente] for i in lidos.itens)


def test_a_lente_DE_OUTRO_FORNECEDOR_fica_de_fora(sessao, imprensa, sociedade, tema):
    """Três lentes, e não todas as cinco — a escolha tem razão medida.

    Imprensa, Mercado e Institucional leem o mesmo export da Clipei. Sociedade e
    Clientes leem OUTROS fornecedores (Bites, Approach), com outro vocabulário
    de tema: a linha deles cai no mesmo `macro_tema_id` por acaso do cadastro,
    não por falar do mesmo assunto. Listá-las aqui misturaria universos dentro
    do modal de um quadro que mede imprensa.
    """
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Da imprensa")
    _mencao(sessao, sociedade, tema.id, data=date(2026, 9, 3), titulo="Da sociedade")

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)

    assert [i.titulo for i in lidos.itens] == ["Da imprensa"]
    assert lidos.total == 1


def test_a_fonte_DESLIGADA_de_OUTRA_lente_tambem_fica_de_fora(
    sessao, imprensa, mercado, tema
):
    """A calibração continua valendo depois de a lista virar três lentes.

    O filtro de fonte desligada era conferido com uma lente só. Agora ele tem de
    valer por fonte, e não por lente: desligar a Clipei recortada do Mercado tira
    as linhas DELA e deixa as da Imprensa — que é outra fonte, ainda ligada.
    """
    _mencao(sessao, imprensa, tema.id, data=date(2026, 9, 2), titulo="Da imprensa")
    _mencao(sessao, mercado, tema.id, data=date(2026, 9, 3), titulo="Do mercado")
    assert impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id).total == 2

    sessao.add(ScoreConfig(fontes_desligadas=[mercado.codigo]))
    sessao.flush()

    lidos = impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)
    assert [i.titulo for i in lidos.itens] == ["Da imprensa"]


def test_sem_a_lente_da_IMPRENSA_cadastrada_a_leitura_RECUSA(sessao, tema):
    """A Imprensa é o chão do modal: é o quadro dela que se abre.

    SEM ELA NÃO HÁ PERGUNTA A RESPONDER, e devolver lista vazia faria a tela
    dizer "nenhum registro" para um cadastro quebrado. As outras duas podem
    faltar sem drama — a lista encurta e segue.
    """
    #: RENOMEANDO O CÓDIGO, e não apagando a lente: a `lente` é referenciada por
    #: `score_fonte`, e apagá-la mediria o `on delete` do banco em vez da regra.
    sessao.execute(
        update(Lente).where(Lente.codigo == "imprensa").values(codigo="imprensa_zz")
    )
    sessao.flush()

    with pytest.raises(NaoEncontrado):
        impacto_na_janela.registros(sessao, ate=ATE, grupo=tema.id)
