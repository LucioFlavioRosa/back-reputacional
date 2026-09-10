"""No Postgres gerenciado do Azure, o token do Entra ID é a senha.

O QUE ISTO PROTEGE. A URL de produção tem usuário e NÃO tem senha — quem
autentica é a identidade gerenciada do contêiner. Se o ouvinte que injeta o
token deixar de ser registrado, a aplicação sobe, o `pool_pre_ping` não ajuda,
e a primeira consulta falha com "autenticação falhou" para um usuário que não
tem senha nenhuma. É o tipo de erro que faz procurar no lugar errado.

Nenhum teste aqui conecta em banco nenhum: montar a engine não abre conexão, e
o que se prova é a DECISÃO de registrar o ouvinte.
"""

from __future__ import annotations

import pytest

from app.banco import sessao as modulo
from app.configuracao import Configuracao

AZURE = (
    "postgresql+psycopg2://id-back-painel@psql-painel.postgres.database.azure.com"
    ":5432/painel_reputacional?sslmode=require"
)
LOCAL = "postgresql+psycopg2://postgres:postgres@localhost:5432/painel_reputacional"
#: Sem senha, e legítimo: `trust`, autenticação por par e `.pgpass` são a
#: forma normal de conectar num Postgres da própria máquina.
LOCAL_SEM_SENHA = "postgresql+psycopg2://postgres@localhost:5432/painel_reputacional"


def ouvintes_de_conexao(engine) -> list:
    """Os ouvintes de `do_connect` registrados na engine.

    NO DIALETO, e não na engine: `do_connect` é evento de `DialectEvents`, e
    registrá-lo pela engine — que é como se escreve — guarda o ouvinte em
    `engine.dialect.dispatch`. Procurar em `engine.dispatch` devolve lista
    vazia mesmo com o ouvinte no lugar, e o teste passaria a mentir.

    Com `getattr` e padrão porque o SQLAlchemy só materializa o atributo do
    evento quando alguém registra o primeiro ouvinte.
    """
    return list(getattr(engine.dialect.dispatch, "do_connect", ()))


@pytest.fixture
def engine_de(monkeypatch):
    """Monta a engine para uma URL, sem deixar a cache suja para o vizinho."""

    def montar(url: str):
        monkeypatch.setattr(
            modulo, "obter_configuracao", lambda: Configuracao(banco_url=url)
        )
        modulo.obter_engine.cache_clear()
        return modulo.obter_engine()

    yield montar
    modulo.obter_engine.cache_clear()


def test_url_sem_senha_ganha_o_ouvinte_do_token(engine_de):
    """Usuário sem senha só pode ser autenticação por Entra ID."""
    engine = engine_de(AZURE)

    assert engine.url.password is None
    assert ouvintes_de_conexao(engine), (
        "sem o ouvinte, a conexão vai sem senha e o Postgres recusa"
    )


def test_url_com_senha_nao_ganha_ouvinte_nenhum(engine_de):
    """Desenvolvimento e testes: a senha está na URL, e o Azure não entra nisso.

    Registrar o ouvinte aqui faria toda conexão local tentar buscar um token
    de identidade gerenciada que não existe.
    """
    engine = engine_de(LOCAL)

    assert engine.url.password is not None
    assert not ouvintes_de_conexao(engine)


def test_postgres_local_sem_senha_nao_busca_token(engine_de):
    """Ausência de senha não é, sozinha, sinal de identidade gerenciada.

    Cair aqui faria a aplicação buscar um token de identidade que não existe,
    para mandá-lo a um Postgres que não o entende — e o erro apareceria como
    "autenticação falhou", longe da causa.
    """
    engine = engine_de(LOCAL_SEM_SENHA)

    assert engine.url.password is None, "o caso só vale sem senha"
    assert not ouvintes_de_conexao(engine)


def test_o_token_entra_como_senha(engine_de, monkeypatch):
    """O ouvinte escreve em `password`, e é isso que o driver manda."""
    monkeypatch.setattr(
        "app.seguranca.identidade_azure.token_para_postgres",
        lambda: "token-do-entra",
    )
    engine = engine_de(AZURE)

    parametros: dict = {}
    for ouvinte in ouvintes_de_conexao(engine):
        ouvinte(None, None, (), parametros)

    assert parametros["password"] == "token-do-entra"


# -- qual credencial, e por quê ------------------------------------------------


def test_no_conteiner_a_credencial_e_deterministica(monkeypatch):
    """`DefaultAzureCredential` é para desenvolvimento, e não para produção.

    Ele percorre uma CADEIA — variáveis de ambiente, identidade gerenciada,
    credencial do `az`. Em produção isso custa latência a cada elo que falha
    antes do certo, esconde a causa da falha no fim da cadeia, e abre a porta
    para autenticar como outra identidade se sobrar variável de ambiente.
    """
    from azure.identity import ManagedIdentityCredential

    from app.seguranca import identidade_azure

    monkeypatch.setenv("AZURE_CLIENT_ID", "id-da-identidade-do-conteiner")
    identidade_azure.credencial.cache_clear()
    try:
        assert isinstance(identidade_azure.credencial(), ManagedIdentityCredential)
    finally:
        identidade_azure.credencial.cache_clear()


def test_fora_do_conteiner_vale_o_az_login(monkeypatch):
    """Sem a variável que a plataforma injeta, quem desenvolve entra pelo `az`."""
    from azure.identity import DefaultAzureCredential

    from app.seguranca import identidade_azure

    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    identidade_azure.credencial.cache_clear()
    try:
        assert isinstance(identidade_azure.credencial(), DefaultAzureCredential)
    finally:
        identidade_azure.credencial.cache_clear()


def test_service_principal_no_ambiente_nao_vira_identidade_gerenciada(monkeypatch):
    """`AZURE_CLIENT_ID` sozinho não significa identidade gerenciada.

    Ele também nomeia o cliente de um service principal, ao lado do tenant e de
    um segredo — que é como um CI se autentica. Confundir os dois manda o CI
    pedir um token de identidade que ele não tem, e a falha aparece como
    credencial indisponível.
    """
    from azure.identity import DefaultAzureCredential

    from app.seguranca import identidade_azure

    monkeypatch.setenv("AZURE_CLIENT_ID", "cliente-do-service-principal")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "segredo-do-ci")
    identidade_azure.credencial.cache_clear()
    try:
        assert isinstance(identidade_azure.credencial(), DefaultAzureCredential)
    finally:
        identidade_azure.credencial.cache_clear()


def test_recusa_do_token_diz_o_que_conferir(monkeypatch):
    """O erro do SDK fala de cadeia de credencial; quem opera precisa de outra coisa.

    Ele chega embrulhado num "autenticação falhou" do Postgres ou num 500 do
    upload — longe da causa, que é sempre a mesma: a identidade do contêiner
    não está atribuída, ou não tem a permissão daquele recurso.
    """
    from azure.core.exceptions import ClientAuthenticationError

    from app.seguranca import identidade_azure

    class CredencialQueRecusa:
        def get_token(self, escopo):
            raise ClientAuthenticationError("ManagedIdentityCredential: sem resposta")

    monkeypatch.setenv("AZURE_CLIENT_ID", "id-que-nao-existe")
    monkeypatch.setattr(identidade_azure, "credencial", CredencialQueRecusa)

    with pytest.raises(ClientAuthenticationError) as erro:
        identidade_azure._TokenComPrazo(identidade_azure.ESCOPO_POSTGRES)()

    mensagem = str(erro.value)
    assert "AZURE_CLIENT_ID=id-que-nao-existe" in mensagem
    assert "identidade" in mensagem and "permissão" in mensagem
    assert "escopo" in mensagem, "nem toda recusa é permissão"
    assert identidade_azure.ESCOPO_POSTGRES in mensagem
