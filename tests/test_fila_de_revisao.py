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
