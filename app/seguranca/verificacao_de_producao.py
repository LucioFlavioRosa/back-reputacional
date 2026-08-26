"""Conferência da configuração ao subir em produção.

Todo controle de segurança deste projeto depende de uma variável de ambiente
estar certa. Variável de ambiente é a parte do sistema que ninguém revisa: não
tem teste, não tem code review, e erra em silêncio — o serviço sobe, responde
200, e a proteção simplesmente não está lá.

Esta é a única parte do código que **recusa subir**. A escolha é deliberada: em
App Service, um contêiner que não inicia aparece em minutos no portal e no
alerta; uma allowlist de CORS com `localhost` dentro não aparece nunca.

A régua entre recusar e avisar:

    RECUSA   a configuração torna um controle inexistente ou inverte seu efeito
    AVISA    a configuração é defensável, mas provavelmente não é o que se quis
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.configuracao import Configuracao
from app.observabilidade import obter_logger

logger = obter_logger("configuracao")


def _banco_e_local(url: str) -> bool:
    """Reconhece a connection string padrão do desenvolvimento."""
    return any(marca in url for marca in ("@localhost", "@127.0.0.1", "@db:", "@[::1]"))


#: Modos de `sslmode` que ACEITAM conexão em texto claro.
#:
#: A distinção importa: `prefer` é o padrão do libpq e parece seguro pelo nome —
#: ele tenta TLS e, se o servidor recusar, **continua em claro sem avisar**.
#: `allow` é pior: tenta em claro primeiro. Nos dois casos, quem estiver no
#: caminho da rede só precisa recusar o TLS uma vez.
SSLMODE_INSEGURO = frozenset({"disable", "allow", "prefer"})


def _problema_no_tls(url: str) -> str | None:
    """Por que esta connection string não garante TLS."""
    partes = urlsplit(url)
    parametros = parse_qs(partes.query)
    modo = (parametros.get("sslmode") or [""])[0].strip().lower()

    if not modo:
        return (
            "sem `sslmode`: o libpq usa `prefer`, que tenta TLS e cai para "
            "texto claro sem avisar se o servidor recusar"
        )
    if modo in SSLMODE_INSEGURO:
        return f"`sslmode={modo}` aceita conexão em texto claro"
    return None


class ConfiguracaoInsegura(RuntimeError):
    """A aplicação recusa subir em produção com esta configuração."""


def _problema_na_origem(origem: str) -> str | None:
    """Por que esta origem não deveria estar numa allowlist de produção.

    A origem é ANALISADA, e não procurada por substring. Procurar `"localhost"`
    no texto erraria dos dois lados: deixaria passar `http://[::1]`,
    `http://0.0.0.0` e `http://192.168.1.5`, e recusaria
    `https://localhost.aegea.com.br`, que é um domínio legítimo.

    A regra é sobre duas propriedades:

        1. o esquema precisa ser https — com `allow_credentials=True`, uma
           origem http significa sessão trafegando a partir de página em claro;
        2. o host não pode ser desta máquina nem de rede interna.

    Domínio comum passa sem julgamento: não há como o código saber se
    `https://qualquercoisa.com.br` é legítimo, e fingir que sabe daria falso
    positivo em deploy legítimo.
    """
    partes = urlsplit(origem)

    if partes.scheme != "https":
        return f"{origem!r} não usa https"

    host = (partes.hostname or "").lower()

    if not host:
        return f"{origem!r} não tem host"

    if host == "localhost" or host.endswith(".localhost"):
        return f"{origem!r} aponta para a própria máquina"

    try:
        endereco = ipaddress.ip_address(host)
    except ValueError:
        # Nome de domínio. Nada a objetar daqui.
        return None

    if (
        endereco.is_loopback
        or endereco.is_private
        or endereco.is_link_local
        or endereco.is_unspecified
    ):
        return f"{origem!r} é endereço de rede interna"

    return None


@dataclass(frozen=True, slots=True)
class Achado:
    campo: str
    problema: str
    correcao: str


def conferir(configuracao: Configuracao) -> list[Achado]:
    """Devolve os avisos; levanta se algo for grave. Só age em produção."""
    if not configuracao.producao:
        return []

    graves: list[Achado] = []
    avisos: list[Achado] = []

    # -- o que torna um controle inexistente ----------------------------------

    if configuracao.auth_mock:
        graves.append(
            Achado(
                "AUTH_MOCK",
                "a autenticação de desenvolvimento devolve um usuário fixo: "
                "qualquer pessoa que alcance a URL entra como esse usuário",
                "AUTH_MOCK=false, com o SSO do Entra ID configurado",
            )
        )

    problemas = [
        p
        for p in (_problema_na_origem(o) for o in configuracao.origens_permitidas)
        if p
    ]
    if problemas:
        graves.append(
            Achado(
                "ORIGENS_PERMITIDAS",
                "origem imprópria na allowlist de produção: "
                + "; ".join(problemas)
                + ". Com `allow_credentials=True`, uma página servida nessa origem "
                "lê a API com a sessão de quem estiver logado",
                "deixar só os domínios https reais do painel",
            )
        )

    if configuracao.sessao_secreta == Configuracao.model_fields["sessao_secreta"].default:
        graves.append(
            Achado(
                "SESSAO_SECRETA",
                "o segredo padrão está no Git. Quem o conhece assina o cookie de "
                "sessão de QUALQUER pessoa — basta trocar o UUID e assinar de "
                "novo. Não é adivinhar senha: é emitir a sessão",
                "um valor aleatório de pelo menos 32 bytes, guardado no Key Vault",
            )
        )
    elif len(configuracao.sessao_secreta) < 32:
        graves.append(
            Achado(
                "SESSAO_SECRETA",
                f"tem {len(configuracao.sessao_secreta)} caracteres. Segredo curto "
                "é forçável offline: quem captura um cookie assinado testa "
                "candidatos até a assinatura bater, sem tocar no servidor",
                "pelo menos 32 caracteres aleatórios",
            )
        )

    if not configuracao.auth_mock and not (
        configuracao.entra_tenant_id
        and configuracao.entra_client_id
        and configuracao.entra_client_secret
    ):
        graves.append(
            Achado(
                "ENTRA_*",
                "SSO ligado sem tenant, client id ou secret: ninguém consegue "
                "entrar, e o erro só aparece quando a primeira pessoa tenta",
                "preencher ENTRA_TENANT_ID, ENTRA_CLIENT_ID e ENTRA_CLIENT_SECRET",
            )
        )

    if not configuracao.limite_de_taxa_ligado:
        graves.append(
            Achado(
                "LIMITE_DE_TAXA_LIGADO",
                "sem limite de taxa, uma única origem consome a capacidade "
                "do serviço inteiro",
                "LIMITE_DE_TAXA_LIGADO=true, ou a borda aplicando o teto",
            )
        )

    if configuracao.banco_echo:
        graves.append(
            Achado(
                "BANCO_ECHO",
                "o SQLAlchemy passa a registrar cada comando SQL COM OS "
                "PARÂMETROS. O termo pesquisado em `q=` e o conteúdo de `relato` "
                "vão parar no log e na telemetria — exatamente os dados que o "
                "resto deste plano existe para proteger",
                "BANCO_ECHO=false",
            )
        )

    tls = _problema_no_tls(configuracao.banco_url)
    if tls and not _banco_e_local(configuracao.banco_url):
        graves.append(
            Achado(
                "BANCO_URL",
                f"{tls}. O tráfego entre o App Service e o Postgres carrega "
                "`relato` e o conteúdo das interações",
                "acrescentar `?sslmode=require` — ou `verify-full`, que também "
                "confere o certificado do servidor",
            )
        )

    if _banco_e_local(configuracao.banco_url):
        graves.append(
            Achado(
                "BANCO_URL",
                "aponta para a própria máquina em produção. É o valor padrão do "
                "código: esquecer a variável no App Service não dá erro de "
                "configuração, dá erro de conexão na primeira consulta — ou, "
                "pior, conecta num Postgres local se houver um",
                "a connection string do Postgres gerenciado",
            )
        )

    # Limite ligado não é limite existente: os números precisam limitar.
    for campo, capacidade, taxa in (
        ("IP", configuracao.limite_por_ip_capacidade, configuracao.limite_por_ip_por_segundo),
        (
            "USUARIO",
            configuracao.limite_por_usuario_capacidade,
            configuracao.limite_por_usuario_por_segundo,
        ),
    ):
        if taxa <= 0:
            graves.append(
                Achado(
                    f"LIMITE_POR_{campo}_POR_SEGUNDO",
                    "reposição zero ou negativa: o balde nunca devolve ficha. "
                    "Depois da rajada inicial, quem for barrado fica barrado "
                    "para sempre — inclusive gente legítima",
                    "um valor positivo; ver os padrões em `configuracao.py`",
                )
            )
        if capacidade <= 0:
            graves.append(
                Achado(
                    f"LIMITE_POR_{campo}_CAPACIDADE",
                    "capacidade zero ou negativa: nenhuma requisição passa",
                    "um valor positivo; ver os padrões em `configuracao.py`",
                )
            )

    # -- o acoplamento que erra em silêncio -----------------------------------
    #
    # Este é o achado que motivou o módulo. Com Front Door na frente e
    # `PROXIES_CONFIAVEIS=0`, o limitador enxerga o IP do Front Door em toda
    # requisição: o mundo inteiro passa a dividir um balde só. O serviço não
    # quebra, não loga erro, e começa a devolver 429 para gente legítima
    # enquanto o atacante gasta a cota de todos.
    #
    # O contrário — `PROXIES_CONFIAVEIS=1` sem proxy nenhum — é pior: passa a
    # valer o `X-Forwarded-For` que o cliente escreve, e o limite por IP deixa
    # de existir.
    if configuracao.proxies_confiaveis == 0:
        avisos.append(
            Achado(
                "PROXIES_CONFIAVEIS",
                "zero em produção. Se houver Front Door ou Application Gateway "
                "na frente, o limite por IP agrupa TODO o tráfego num balde só",
                "1 com Front Door; manter 0 apenas se a aplicação recebe conexão direta",
            )
        )

    # -- o que provavelmente não é o que se quis ------------------------------

    if not configuracao.hsts_ligado:
        avisos.append(
            Achado(
                "HSTS_LIGADO",
                "desligado em produção: o navegador aceita voltar a http",
                "HSTS_LIGADO=true depois de confirmar que o HTTPS responde",
            )
        )

    if configuracao.docs_publicos:
        avisos.append(
            Achado(
                "DOCS_PUBLICOS",
                "verdadeiro em produção. As rotas são removidas mesmo assim, "
                "porque `criar_app` também exige ambiente diferente de produção",
                "DOCS_PUBLICOS=false, para a intenção ficar explícita",
            )
        )

    if not configuracao.applicationinsights_connection_string:
        avisos.append(
            Achado(
                "APPLICATIONINSIGHTS_CONNECTION_STRING",
                "vazia: a telemetria não sai do contêiner, e nenhum alerta de "
                "segurança dispara",
                "a connection string do recurso de Application Insights",
            )
        )

    for achado in avisos:
        logger.warning(
            "Configuração de produção: %s — %s. Correção: %s",
            achado.campo,
            achado.problema,
            achado.correcao,
            extra={"campo": achado.campo, "severidade": "aviso"},
        )

    if graves:
        for achado in graves:
            logger.critical(
                "Configuração insegura: %s — %s",
                achado.campo,
                achado.problema,
                extra={"campo": achado.campo, "severidade": "grave"},
            )
        raise ConfiguracaoInsegura(
            "A aplicação recusa subir em produção:\n"
            + "\n".join(f"  {a.campo}: {a.problema}\n    -> {a.correcao}" for a in graves)
        )

    return avisos
