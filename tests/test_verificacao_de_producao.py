"""A conferência de subida.

Único ponto do sistema que impede a aplicação de iniciar. Vale explicar por quê:
todo controle de segurança deste projeto depende de uma variável de ambiente
estar certa, e variável de ambiente é a parte do sistema que ninguém revisa —
sem teste, sem code review, e errando em silêncio. O serviço sobe, responde 200,
e a proteção não está lá.

Um contêiner que não inicia aparece em minutos no portal do App Service. Uma
allowlist de CORS com `localhost` dentro não aparece nunca.
"""

from __future__ import annotations

import pytest

from app.configuracao import Configuracao
from app.seguranca.verificacao_de_producao import (
    ConfiguracaoInsegura,
    conferir,
)

#: Uma produção que a conferência aceita inteira, para estragar um campo por vez.
#:
#: Precisa incluir `banco_url`: o padrão do código aponta para localhost, e a
#: conferência recusa isso em produção. Sem esta linha, todo teste desta suíte
#: falharia pelo motivo errado.
BANCO_GERENCIADO = (
    "postgresql+psycopg2://app:x@servidor.postgres.database.azure.com/painel"
    "?sslmode=require"
)


def producao(**ajustes) -> Configuracao:
    padrao = dict(
        ambiente="producao",
        auth_mock=False,
        origens_permitidas=["https://painel.aegea.com.br"],
        proxies_confiaveis=1,
        applicationinsights_connection_string="InstrumentationKey=algo",
        docs_publicos=False,
        banco_url=BANCO_GERENCIADO,
        # Segredo próprio: o padrão do código está no Git, e a conferência
        # de subida recusa produção com ele.
        sessao_secreta="x" * 48,
        # SSO ligado exige as três: sem elas ninguém entra, e o erro só
        # apareceria quando a primeira pessoa tentasse.
        entra_tenant_id="tenant",
        entra_client_id="cliente",
        entra_client_secret="segredo",
    )
    return Configuracao(**{**padrao, **ajustes})


# -- fora de produção, nada acontece -------------------------------------------


def test_desenvolvimento_nao_e_conferido():
    """Os padrões de desenvolvimento SÃO os que a conferência recusa.

    `auth_mock=True` e `localhost` na allowlist são exatamente o ambiente local.
    Conferir fora de produção tornaria impossível rodar o projeto na máquina de
    quem desenvolve.
    """
    assert conferir(Configuracao()) == []


# -- o que impede de subir -----------------------------------------------------


def test_auth_mock_em_producao_impede_a_subida():
    """O pior erro possível, e o mais fácil de cometer.

    `AUTH_MOCK=true` é o padrão do código. Basta esquecer a variável no App
    Service para que qualquer pessoa que alcance a URL entre como o usuário
    fixo de desenvolvimento — com o papel dele, sobre o escopo dele.
    """
    with pytest.raises(ConfiguracaoInsegura, match="AUTH_MOCK"):
        conferir(producao(auth_mock=True))


def test_localhost_na_allowlist_de_producao_impede_a_subida():
    """Com `allow_credentials=True`, uma origem a mais é uma porta a mais.

    Qualquer página servida em `localhost:5173` — na máquina de quem for — passa
    a poder ler esta API com a sessão de quem estiver logado no navegador.
    """
    with pytest.raises(ConfiguracaoInsegura, match="ORIGENS_PERMITIDAS"):
        conferir(producao(origens_permitidas=["https://painel.aegea.com.br", "http://localhost:5173"]))


def test_limite_de_taxa_desligado_em_producao_impede_a_subida():
    with pytest.raises(ConfiguracaoInsegura, match="LIMITE_DE_TAXA_LIGADO"):
        conferir(producao(limite_de_taxa_ligado=False))


def test_a_mensagem_diz_como_corrigir():
    """Recusar sem dizer o que fazer transforma a proteção em obstáculo.

    Quem encontra isto está com o deploy parado, provavelmente fora do
    expediente. A mensagem precisa bastar.
    """
    with pytest.raises(ConfiguracaoInsegura) as erro:
        conferir(producao(auth_mock=True))

    texto = str(erro.value)
    assert "AUTH_MOCK=false" in texto
    assert "Entra ID" in texto


def test_varios_problemas_saem_de_uma_vez():
    """Recusar um por vez faria o deploy falhar três vezes seguidas."""
    with pytest.raises(ConfiguracaoInsegura) as erro:
        conferir(
            producao(
                auth_mock=True,
                origens_permitidas=["http://localhost:5173"],
                limite_de_taxa_ligado=False,
            )
        )

    texto = str(erro.value)
    assert "AUTH_MOCK" in texto
    assert "ORIGENS_PERMITIDAS" in texto
    assert "LIMITE_DE_TAXA_LIGADO" in texto


# -- o que apenas avisa --------------------------------------------------------


def test_producao_correta_nao_gera_aviso():
    assert conferir(producao()) == []


def test_proxies_confiaveis_zero_apenas_avisa():
    """O acoplamento que erra em silêncio, e por isso não pode recusar.

    Com Front Door na frente e `PROXIES_CONFIAVEIS=0`, o limitador enxerga o IP
    do Front Door em toda requisição e o mundo inteiro divide um balde só — o
    serviço passa a devolver 429 para gente legítima. Mas zero é o valor CERTO
    quando a aplicação recebe conexão direta, e o código não tem como saber qual
    é o caso. Avisar é o máximo que dá para fazer com honestidade.
    """
    avisos = conferir(producao(proxies_confiaveis=0))
    assert [a.campo for a in avisos] == ["PROXIES_CONFIAVEIS"]


def test_hsts_desligado_em_producao_apenas_avisa():
    avisos = conferir(producao(HSTS_LIGADO=False))
    assert any(a.campo == "HSTS_LIGADO" for a in avisos)


def test_telemetria_vazia_apenas_avisa():
    """Sem telemetria nenhum alerta de segurança dispara — mas o painel funciona.

    Recusar aqui impediria de subir um ambiente de homologação sem recurso de
    Application Insights, o que é legítimo.
    """
    avisos = conferir(producao(applicationinsights_connection_string=None))
    assert any(a.campo == "APPLICATIONINSIGHTS_CONNECTION_STRING" for a in avisos)


# -- HSTS ----------------------------------------------------------------------


def test_hsts_liga_sozinho_em_producao():
    """Manter `False` fixo era seguro e errado.

    HSTS desligado em produção é o contrário do que se quer, e "depois eu ligo"
    não acontece. O padrão passou a seguir o ambiente; a variável ainda vence.
    """
    assert Configuracao().hsts_ligado is False
    assert Configuracao(ambiente="producao").hsts_ligado is True
    assert Configuracao(ambiente="producao", HSTS_LIGADO=False).hsts_ligado is False


def test_include_subdomains_nao_liga_junto():
    """A metade perigosa do HSTS fica de fora até alguém pedir.

    Num domínio compartilhado como `aegea.com.br`, `includeSubDomains` obriga
    HTTPS em TODO subdomínio da companhia — inclusive nos que este time não
    conhece e que talvez ainda sirvam http. Derrubar sistema alheio a partir
    daqui não seria aceitável, e desfazer leva `max_age` inteiro.
    """
    assert Configuracao(ambiente="producao").hsts_incluir_subdominios is False


# -- origens: parsear, não procurar substring ----------------------------------


@pytest.mark.parametrize(
    "origem",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",       # loopback IPv6 — escapava da substring
        "http://0.0.0.0:5173",     # escapava
        "http://192.168.1.5:5173", # rede privada — escapava
        "http://painel.aegea.com.br",  # http puro com allow_credentials
        "https://10.0.0.4",
        "https://[::1]",
    ],
)
def test_origem_impropria_impede_a_subida(origem):
    """A origem é analisada, e não procurada por substring.

    Procurar `"localhost"` no texto deixa passar metade destes casos. O mais
    perigoso é `http://painel.aegea.com.br`: domínio legítimo, esquema errado —
    e com `allow_credentials=True` a sessão passa a trafegar a partir de página
    servida em claro.
    """
    with pytest.raises(ConfiguracaoInsegura, match="ORIGENS_PERMITIDAS"):
        conferir(producao(origens_permitidas=[origem]))


def test_dominio_com_localhost_no_nome_nao_e_falso_positivo():
    """O outro lado do erro: `https://localhost.aegea.com.br` é domínio comum.

    Recusar por conter a palavra impediria um deploy legítimo — e obrigaria a
    próxima pessoa a desligar a conferência inteira para subir.
    """
    assert conferir(producao(origens_permitidas=["https://localhost.aegea.com.br"])) == []


# -- banco ---------------------------------------------------------------------


def test_banco_echo_em_producao_impede_a_subida():
    """`echo` registra cada SQL COM OS PARÂMETROS.

    O termo pesquisado em `q=` e o conteúdo de `relato` iriam para o log e para
    a telemetria — exatamente os dados que o resto deste plano protege.
    """
    with pytest.raises(ConfiguracaoInsegura, match="BANCO_ECHO"):
        conferir(producao(banco_echo=True))


def test_banco_apontando_para_a_propria_maquina_impede_a_subida():
    """É o valor PADRÃO do código, o que torna o esquecimento provável.

    Esquecer `BANCO_URL` no App Service não dá erro de configuração: dá erro de
    conexão na primeira consulta — ou, pior, conecta num Postgres local se
    houver um no contêiner.
    """
    padrao_do_codigo = Configuracao().banco_url
    with pytest.raises(ConfiguracaoInsegura, match="BANCO_URL"):
        conferir(producao(banco_url=padrao_do_codigo))


# -- os números do limite precisam limitar -------------------------------------


def test_reposicao_zero_impede_a_subida():
    """Limite ligado não é limite existente.

    Com reposição zero o balde nunca devolve ficha: depois da rajada inicial,
    quem for barrado fica barrado para sempre — inclusive gente legítima. E a
    espera calculada vira infinita, o que fazia o 429 virar 500.
    """
    with pytest.raises(ConfiguracaoInsegura, match="LIMITE_POR_IP_POR_SEGUNDO"):
        conferir(producao(limite_por_ip_por_segundo=0))


def test_capacidade_zero_impede_a_subida():
    with pytest.raises(ConfiguracaoInsegura, match="LIMITE_POR_USUARIO_CAPACIDADE"):
        conferir(producao(limite_por_usuario_capacidade=0))


@pytest.mark.parametrize("modo", ["", "?sslmode=prefer", "?sslmode=allow", "?sslmode=disable"])
def test_tls_frouxo_no_banco_impede_a_subida(modo):
    """`prefer` é a armadilha: parece seguro e não é.

    É o padrão do libpq quando ninguém define nada. Ele tenta TLS e, se o
    servidor recusar, **continua em texto claro sem avisar** — então quem
    estiver no caminho da rede só precisa recusar o TLS uma vez. `allow` é pior:
    tenta em claro primeiro.

    O tráfego entre o App Service e o Postgres carrega `relato` e o conteúdo das
    interações.
    """
    with pytest.raises(ConfiguracaoInsegura, match="BANCO_URL"):
        conferir(producao(banco_url=BANCO_GERENCIADO.replace("?sslmode=require", modo)))


@pytest.mark.parametrize("modo", ["require", "verify-ca", "verify-full"])
def test_tls_exigido_e_aceito(modo):
    assert conferir(producao(banco_url=BANCO_GERENCIADO.replace("require", modo))) == []


# -- o caminho REAL: variável de ambiente --------------------------------------


def test_configuracao_e_lida_do_ambiente_de_verdade(monkeypatch):
    """Os outros testes montam a configuração por argumento; produção não.

    Se alguém trocar um alias ou o `model_config`, `Configuracao(ambiente=...)`
    continua verde enquanto `AMBIENTE=producao` no App Service deixa de ser
    lido — e a conferência inteira passa a não rodar, em silêncio.
    """
    for variavel, valor in {
        "AMBIENTE": "producao",
        "AUTH_MOCK": "false",
        "PROXIES_CONFIAVEIS": "1",
        "HSTS_LIGADO": "false",
        "BANCO_ECHO": "true",
    }.items():
        monkeypatch.setenv(variavel, valor)

    lida = Configuracao()
    assert lida.producao
    assert lida.auth_mock is False
    assert lida.proxies_confiaveis == 1
    assert lida.hsts_ligado is False
    assert lida.banco_echo is True
