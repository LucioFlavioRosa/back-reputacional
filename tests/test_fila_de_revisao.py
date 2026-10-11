"""O cadastro que nasce de planilha espera revisão, e a fila nasce vazia.

PEDIDO DO DONO DO PRODUTO (11/10/2026):

  "Quando subirmos uma base que tenha algum ponto de conferência de cadastro, pode
  subir sem problemas. Porém, dentro de cada uma das 3 abas de Cadastro
  compartilhado, deve existir uma aba específica para cadastros que precisam ser
  revisados para serem consolidados na base de instituições/contatos, temas e
  representantes da Aegea. Assim o profissional consegue subir a planilha sem
  problemas e pode revisar depois — e inclusive pode ser trabalho de outra pessoa.
  Queremos dar padronização, mas com menor impacto."

QUATRO NASCIMENTOS PARA TRÊS ABAS, e o mapa é exato: "Instituições e Contatos" é
`instituicao` + `interlocutor`, "Temas" é `tema`, "Representantes Aegea" é
`pessoa_aegea`. São também os quatro cadastros que a importação de agendas sabe
criar (`VOCABULARIOS_QUE_A_IMPORTACAO_CRIA`), mais a instituição que a ingestão de
menções cria.

POR QUE ESTE ARQUIVO EXISTE. A marca é uma linha por nascimento, e uma linha
esquecida não quebra nada: o cadastro entra, a tela funciona, e ele simplesmente
nunca aparece na fila. Uma fila que não tem tudo é pior que fila nenhuma, porque
ensina a confiar nela.

E A SEGUNDA METADE, de 11/10/2026: a ROTA que lê a fila e o ato que tira dela.
Durante um dia a coluna existiu sem ninguém a ler — o pior estado possível,
porque a importação PAROU DE TRAVAR contando com uma revisão que não acontecia.
O dono do produto cobrou: "e pedi também por uma aba extra somente para
conferência de novos registros e não vi".
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso import importar_agendas, modelo_de_importacao
from app.casos_de_uso.veiculos_da_imprensa import criar, reconhecer
from app.dominio.texto import normalizar

#: O AJUDANTE DE ONDE ELE JÁ EXISTE, e não uma cópia: `_cliente` monta o
#: `TestClient` sobrescrevendo `obter_configuracao` por `dependency_overrides` — o
#: `Depends` já foi resolvido na importação do módulo, então `monkeypatch.setattr`
#: não alcança quem guardou a função. Uma segunda cópia disso divergiria no dia em
#: que o login mudasse.
#:
#: A FUNÇÃO E NÃO A FIXTURE: importar a fixture e usá-la como parâmetro redefine o
#: nome (F811), e este projeto não compartilha fixture entre arquivos de teste —
#: cada um monta as suas.
from main import app
from tests.test_e2e_postgres import URL
from tests.test_importacoes_api import TIPO_XLSX, _cliente

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


@pytest.fixture
def cliente_admin(sessao):
    """`plataforma_edicao` é o único perfil com `administra_dicionarios`, e é o
    que a importação exige — ver `exigir_administracao_de_cadastros`.

    O `finally` LIMPA OS OVERRIDES: `_cliente` os instala em `app`, que é global, e
    um teste que os deixasse montados contaminaria o próximo arquivo da suíte.
    """
    try:
        yield _cliente(sessao, "plataforma_edicao")
    finally:
        app.dependency_overrides.clear()


#: As quatro tabelas da fila, com o nome da aba de Cadastro compartilhado a que
#: cada uma pertence — é o que faz a falha dizer ONDE o registro deixaria de
#: aparecer.
DA_FILA = (
    (Instituicao, "Instituições e Contatos"),
    (Interlocutor, "Instituições e Contatos"),
    (Tema, "Temas"),
    (PessoaAegea, "Representantes Aegea"),
)


def test_as_quatro_tabelas_da_fila_TEM_a_coluna(sessao):
    """A fila das três abas sai destas quatro, e de nenhuma outra.

    SE UMA DELAS NÃO TIVER A COLUNA, a aba correspondente não tem o que listar — e
    a descoberta seria pela tela vazia, não por aqui.
    """
    for tabela, aba in DA_FILA:
        quantos = sessao.scalar(
            select(func.count()).select_from(tabela).where(tabela.pendente_de_revisao)
        )
        assert quantos is not None, f"{tabela.__tablename__} não tem a coluna (aba {aba})"


def test_a_fila_NASCE_VAZIA(sessao):
    """O "menor impacto" do pedido, afirmado.

    `default false` É A DECISÃO: os 3.785 cadastros de instituição, 129 de
    interlocutor, 149 de tema e 12 de pessoa da Aegea que já existem foram feitos
    por gente, ou já passaram pela conferência da ingestão. Se a coluna nascesse
    `true`, a fila abriria pedindo revisão de tudo — e uma fila que nasce cheia de
    registro antigo é ruído, que é o que faz ninguém olhar (o argumento da `0078`).
    """
    for tabela, aba in DA_FILA:
        pendentes = sessao.scalars(
            select(tabela.nome).where(tabela.pendente_de_revisao).limit(5)
        ).all()
        assert pendentes == [], f"a aba {aba} abriria com {pendentes} na fila"


def _agenda_com(sessao, **valores) -> bytes:
    """Uma planilha de agendas com uma linha, pelos nomes de coluna."""
    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    folha.append([valores.get(coluna) for coluna in cabecalho])
    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


def test_os_QUATRO_cadastros_da_importacao_de_agendas_nascem_pendentes(
    cliente_admin, sessao
):
    """Instituição, interlocutor, pessoa da Aegea e tema, de uma planilha só.

    OS QUATRO NUMA LINHA, de propósito: é o caso que o dono do produto descreveu —
    "quando temos várias reuniões em um dia o registro completo pode ser uma
    dificuldade". A linha entra com nomes que não existem em cadastro nenhum, e os
    quatro nascem.

    PASSA PELA CONFIRMAÇÃO, e isto não é detalhe: os cadastros nascem em
    `_criar_cadastros`, que só roda ali. Uma primeira versão deste teste afirmava
    `proposta.a_criar` — o que prova que a importação SE PROPÕE a criar, e nada
    sobre a marca da fila. Passaria com a marca removida dos quatro.
    """
    conteudo = _agenda_com(
        sessao,
        **{
            "Data": date(2026, 9, 25),
            "Instituição": "Órgão Novo Da Fila ZZ",
            "UF": "SP",
            "Interlocutor 1": "Pessoa Nova Da Fila ZZ",
            "Pessoa da Aegea 1": "Representante Novo Da Fila ZZ",
            "Tema 1": "Assunto Novo Da Fila ZZ",
        },
    )

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", conteudo, TIPO_XLSX)}
    ).json()
    #: NÃO BARRA: é a premissa do pedido, e sem ela o resto não acontece.
    assert criada["pendencias"] == 0, criada["grupos"]

    confirmacao = cliente_admin.post(f"/api/importacoes/{criada['id']}/confirmacao")
    assert confirmacao.status_code == 201, confirmacao.text

    #: OS QUATRO NASCERAM, E OS QUATRO ESTÃO NA FILA.
    nascidos = (
        (Instituicao, "Órgão Novo Da Fila ZZ", "Instituições e Contatos"),
        (Interlocutor, "Pessoa Nova Da Fila ZZ", "Instituições e Contatos"),
        (PessoaAegea, "Representante Novo Da Fila ZZ", "Representantes Aegea"),
        (Tema, "Assunto Novo Da Fila ZZ", "Temas"),
    )
    for tabela, nome, aba in nascidos:
        registro = sessao.scalar(select(tabela).where(tabela.nome == nome))
        assert registro is not None, f"{nome} não foi criado"
        assert registro.pendente_de_revisao is True, (
            f"{nome} nasceu fora da fila — não apareceria na aba {aba}"
        )


def test_o_veiculo_da_ingestao_NASCE_pendente(sessao):
    """A ingestão de menções também, e o motivo de ela entrar na fila importa.

    ELA JÁ TEM CONFERÊNCIA, e ainda assim entra — porque as duas perguntam coisas
    diferentes. Na conferência da ingestão a pessoa autoriza a CRIAÇÃO olhando
    nome, praça, alcance e cargo: ela diz "este veículo existe e deve entrar". O
    ENQUADRAMENTO é outra pergunta — a subcategoria é lógica editorial que nenhuma
    coluna da Clipei informa, e é dela que a lente Mercado depende. Quem autoriza
    2.631 criações numa tela não decide 2.631 enquadramentos na mesma tela.
    """
    nome = "Veículo Da Fila ZZ"
    reco = reconhecer(
        sessao, {nome: {"uf": "SP", "abrangencia": "Local", "mencoes": 3, "tier": ""}}
    )
    criar(sessao, reco.novos)
    sessao.flush()

    novo = sessao.scalar(
        select(Instituicao).where(Instituicao.nome_normalizado == normalizar(nome))
    )
    assert novo is not None, "o veículo não foi criado"
    assert novo.pendente_de_revisao is True


def test_quem_a_PESSOA_cadastra_pela_tela_NAO_entra_na_fila(sessao):
    """O outro lado da regra, e é ele que mantém a fila útil.

    O `default` da coluna é `false`, então um cadastro criado por qualquer caminho
    que não seja planilha nasce fora da fila. Sem esta asserção, alguém poderia
    trocar o default por `true` para "garantir que nada escape" — e a fila passaria
    a conter tudo que a plataforma cria, incluindo o que acabou de ser conferido
    por gente na própria tela de cadastro.
    """
    nome = "Entidade Feita A Mao ZZ"
    sessao.add(
        Instituicao(nome=nome, nome_normalizado=normalizar(nome), tipo="entidade")
    )
    sessao.flush()

    feita = sessao.scalar(
        select(Instituicao).where(Instituicao.nome_normalizado == normalizar(nome))
    )
    assert feita.pendente_de_revisao is False


# -- A ABA: a rota que lê a fila, e o ato que tira dela ------------------------


@pytest.fixture
def cliente_sem_admin(sessao):
    """`crm_edicao` abre o portal do CRM e NÃO administra cadastros.

    É o contrapeso EXATO da guarda, e não um perfil sem acesso a nada — que
    passaria com qualquer dependência, inclusive com a errada.
    """
    try:
        yield _cliente(sessao, "crm_edicao")
    finally:
        app.dependency_overrides.clear()


def test_a_rota_LISTA_as_tres_abas_sempre(cliente_admin):
    """As três, inclusive as vazias, e na ordem da tela.

    UMA ABA QUE DESAPARECE QUANDO ESTÁ LIMPA é uma aba que ninguém aprende a
    olhar: quem abre o Cadastro compartilhado precisa ver que a revisão existe e
    que não há nada pendente — não um espaço em branco indistinguível de uma
    tela que não carregou.
    """
    resposta = cliente_admin.get("/api/revisao-de-cadastros")
    assert resposta.status_code == 200, resposta.text

    abas = resposta.json()
    assert [aba["id"] for aba in abas] == ["instituicoes", "assuntos", "porta_vozes"]
    assert [aba["rotulo"] for aba in abas] == [
        "Instituições e Contatos",
        "Temas",
        "Representantes Aegea",
    ]


def test_quem_NAO_administra_cadastros_nao_le_a_fila(cliente_sem_admin):
    """Mais estrito que as listagens de cadastro, que pedem `ve_diretorio`.

    A FILA NÃO É A BASE: um registro aqui diz que a plataforma não confia naquele
    enquadramento ainda. Quem não pode consertar não ganha nada em ver a lista do
    que está por consertar — e a lista carrega o motivo, que é uma dúvida
    interna sobre o dado.
    """
    assert cliente_sem_admin.get("/api/revisao-de-cadastros").status_code == 403


def test_os_quatro_nascimentos_APARECEM_cada_um_na_sua_aba(cliente_admin, sessao):
    """O mapa de `DA_FILA`, afirmado pela ROTA e não pela coluna.

    `test_os_QUATRO_cadastros_da_importacao_de_agendas_nascem_pendentes` prova que
    a marca foi gravada. Este prova que ela CHEGA NA TELA, e na aba certa — que é
    o que o dono do produto pediu e o que faltava.
    """
    conteudo = _agenda_com(
        sessao,
        **{
            "Data": date(2026, 9, 25),
            "Instituição": "Órgão Da Aba Zz73",
            "UF": "SP",
            "Interlocutor 1": "Pessoa Da Aba Zz73",
            "Pessoa da Aegea 1": "Representante Da Aba Zz73",
            "Tema 1": "Assunto Da Aba Zz73",
        },
    )
    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("dia.xlsx", conteudo, TIPO_XLSX)}
    ).json()
    assert criada["pendencias"] == 0, criada["grupos"]
    assert (
        cliente_admin.post(f"/api/importacoes/{criada['id']}/confirmacao").status_code
        == 201
    )

    abas = {
        aba["id"]: {p["nome"]: p for p in aba["pendentes"]}
        for aba in cliente_admin.get("/api/revisao-de-cadastros").json()
    }

    esperado = (
        ("instituicoes", "Órgão Da Aba Zz73", "instituicao"),
        ("instituicoes", "Pessoa Da Aba Zz73", "interlocutor"),
        ("assuntos", "Assunto Da Aba Zz73", "tema"),
        ("porta_vozes", "Representante Da Aba Zz73", "pessoa_aegea"),
    )
    for aba, nome, tipo in esperado:
        assert nome in abas[aba], f"{nome} não apareceu na aba {aba}: {list(abas[aba])}"
        assert abas[aba][nome]["tipo"] == tipo


def test_a_fila_DIZ_a_instituicao_de_cada_pessoa_homonima(cliente_admin, sessao):
    """O caso real, e é a razão de `contexto` existir.

    A PLANILHA DE RI tem quatro nomes em duas instituições cada, e desde
    11/10/2026 cada um nasce DUAS VEZES, de propósito — a `0002` diz que "mesmo
    nome em instituições diferentes são pessoas diferentes".

    SEM A INSTITUIÇÃO AO LADO a aba mostraria "Artur Santa" duas vezes, com o
    mesmo motivo, e quem revisa não teria como saber qual é o do Banco XP e qual
    é o da XP Asset. A fila ficaria ilegível justamente no caso que a fez
    existir — e pior que ilegível: convidaria a fundir os dois.
    """
    modelo = modelo_de_importacao.gerar(importar_agendas.vocabularios(sessao))
    pasta = load_workbook(io.BytesIO(modelo))
    folha = pasta["Agendas"]
    cabecalho = [celula.value for celula in next(folha.iter_rows())]
    for casa in ("Banco Zz74 Um", "Banco Zz74 Dois"):
        folha.append(
            [
                {
                    "Data": date(2026, 9, 25),
                    "Instituição": casa,
                    "UF": "SP",
                    "Interlocutor 1": "Pessoa Em Duas Zz74",
                }.get(coluna)
                for coluna in cabecalho
            ]
        )
    saida = io.BytesIO()
    pasta.save(saida)

    criada = cliente_admin.post(
        "/api/importacoes", files={"arquivo": ("ri.xlsx", saida.getvalue(), TIPO_XLSX)}
    ).json()
    assert criada["pendencias"] == 0, criada["grupos"]
    assert (
        cliente_admin.post(f"/api/importacoes/{criada['id']}/confirmacao").status_code
        == 201
    )

    aba = next(
        a
        for a in cliente_admin.get("/api/revisao-de-cadastros").json()
        if a["id"] == "instituicoes"
    )
    as_duas = [
        p for p in aba["pendentes"] if p["nome"] == "Pessoa Em Duas Zz74"
    ]
    assert len(as_duas) == 2, as_duas

    #: AS DUAS SÃO DISTINGUÍVEIS, e é só o `contexto` que as distingue.
    assert {p["contexto"] for p in as_duas} == {"Banco Zz74 Um", "Banco Zz74 Dois"}
    #: E AS DUAS DIZEM POR QUÊ.
    for pendente in as_duas:
        assert "2 instituições" in pendente["motivo"]


def test_consolidar_TIRA_da_fila_e_APAGA_o_motivo(cliente_admin, sessao):
    """O ato de revisar, e os dois efeitos que ele tem.

    O MOTIVO SAI COM A PENDÊNCIA porque ele é a PERGUNTA que a fila fazia.
    Mantê-lo deixaria "apareceu em 2 instituições — confirme se são a mesma
    pessoa" grudado num cadastro sobre o qual alguém JÁ confirmou, pronto para
    reaparecer na próxima tela que o leia.
    """
    nome = "Entidade Consolidada Zz75"
    registro = Instituicao(
        nome=nome,
        nome_normalizado=normalizar(nome),
        tipo="entidade",
        uf="SP",
        pendente_de_revisao=True,
        motivo_da_revisao="Nasceu da planilha de teste.",
    )
    sessao.add(registro)
    sessao.flush()

    na_fila = cliente_admin.get("/api/revisao-de-cadastros").json()[0]["pendentes"]
    assert nome in [p["nome"] for p in na_fila]

    resposta = cliente_admin.post(
        f"/api/revisao-de-cadastros/instituicao/{registro.id}/consolidacao"
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ja_estava_consolidado"] is False
    assert resposta.json()["pendente"]["motivo"] is None
    #: O CONTEXTO CONTINUA, porque ele descreve o cadastro e não a pendência.
    assert resposta.json()["pendente"]["contexto"] == "Entidade · SP"

    sessao.refresh(registro)
    assert registro.pendente_de_revisao is False
    assert registro.motivo_da_revisao is None

    #: E SAIU DA LISTA.
    depois = cliente_admin.get("/api/revisao-de-cadastros").json()[0]["pendentes"]
    assert nome not in [p["nome"] for p in depois]


def test_consolidar_DUAS_VEZES_diz_que_ja_estava(cliente_admin, sessao):
    """Duas pessoas na mesma aba é o caso NORMAL, não a exceção.

    O PEDIDO É EXPLÍCITO: "inclusive pode ser trabalho de outra pessoa". Recusar
    o segundo clique seria inventar um conflito onde não há desacordo — o estado
    final é o que as duas pessoas queriam. O booleano existe para a tela dizer
    "outra pessoa já consolidou este" em vez de piscar uma confirmação falsa.
    """
    nome = "Entidade Duas Vezes Zz76"
    registro = Instituicao(
        nome=nome,
        nome_normalizado=normalizar(nome),
        tipo="entidade",
        pendente_de_revisao=True,
    )
    sessao.add(registro)
    sessao.flush()

    rota = f"/api/revisao-de-cadastros/instituicao/{registro.id}/consolidacao"
    assert cliente_admin.post(rota).json()["ja_estava_consolidado"] is False
    segunda = cliente_admin.post(rota)
    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["ja_estava_consolidado"] is True


def test_o_id_que_nao_e_do_tipo_da_404_e_nao_500(cliente_admin):
    """`sessao.get(Tema, "abc")` estoura `DataError` e aborta a transação.

    UM 500 ONDE O CERTO É 404, e o custo é maior que a resposta errada: o
    `DataError` aborta a transação do pedido INTEIRO no Postgres, então qualquer
    coisa que viesse depois na mesma sessão também falharia.

    E ESTE NÃO É UM CASO HIPOTÉTICO: o id vem da URL, e o front monta a URL com
    o id que a listagem devolveu como TEXTO — um `tema` com id inteiro e uma
    `instituicao` com UUID saem da mesma lista, pela mesma rota.
    """
    assert cliente_admin.post(
        "/api/revisao-de-cadastros/tema/nao-sou-numero/consolidacao"
    ).status_code == 404
    assert cliente_admin.post(
        "/api/revisao-de-cadastros/instituicao/nao-sou-uuid/consolidacao"
    ).status_code == 404
    #: E O TIPO QUE NÃO É DA FILA.
    assert cliente_admin.post(
        "/api/revisao-de-cadastros/mencao/1/consolidacao"
    ).status_code == 404


def test_toda_tabela_da_fila_SAI_pela_rota():
    """Âncora: as quatro que entram na fila são as quatro que a rota consolida.

    SEM ELA, uma tabela acrescentada a `_TABELAS` e esquecida em `POR_TIPO`
    apareceria na aba e recusaria a consolidação — a pessoa veria um registro
    que não sai, e descobriria pelo 404. `POR_TIPO` é derivado de `_TABELAS` por
    essa razão; este teste prende a derivação ao mapa de `DA_FILA`, que é o
    pedido do dono do produto escrito em código.
    """
    from app.casos_de_uso.fila_de_revisao import POR_TIPO

    assert set(POR_TIPO) == {tabela.__tablename__ for tabela, _ in DA_FILA}
