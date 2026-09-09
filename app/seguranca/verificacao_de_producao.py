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
from collections.abc import Callable
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


#: Uma verificação: recebe a configuração e devolve o achado, ou `None` quando
#: está tudo certo. Assinatura única para as catorze — é o que permite listá-las
#: em vez de encadear catorze `if`.
Verificacao = Callable[[Configuracao], Achado | None]


# -- o que torna um controle inexistente --------------------------------------


def _autenticacao_de_mentira(c: Configuracao) -> Achado | None:
    if not c.auth_mock:
        return None
    return Achado(
        "AUTH_MOCK",
        "a autenticação de desenvolvimento devolve um usuário fixo: "
        "qualquer pessoa que alcance a URL entra como esse usuário",
        "AUTH_MOCK=false, com o SSO do Entra ID configurado",
    )


def _origem_impropria(c: Configuracao) -> Achado | None:
    problemas = [p for p in (_problema_na_origem(o) for o in c.origens_permitidas) if p]
    if not problemas:
        return None
    return Achado(
        "ORIGENS_PERMITIDAS",
        "origem imprópria na allowlist de produção: "
        + "; ".join(problemas)
        + ". Com `allow_credentials=True`, uma página servida nessa origem "
        "lê a API com a sessão de quem estiver logado",
        "deixar só os domínios https reais do painel",
    )


def _segredo_de_sessao_fraco(c: Configuracao) -> Achado | None:
    if c.sessao_secreta == Configuracao.model_fields["sessao_secreta"].default:
        return Achado(
            "SESSAO_SECRETA",
            "o segredo padrão está no Git. Quem o conhece assina o cookie de "
            "sessão de QUALQUER pessoa — basta trocar o UUID e assinar de "
            "novo. Não é adivinhar senha: é emitir a sessão",
            "um valor aleatório de pelo menos 32 bytes, guardado no Key Vault",
        )
    if len(c.sessao_secreta) < 32:
        return Achado(
            "SESSAO_SECRETA",
            f"tem {len(c.sessao_secreta)} caracteres. Segredo curto "
            "é forçável offline: quem captura um cookie assinado testa "
            "candidatos até a assinatura bater, sem tocar no servidor",
            "pelo menos 32 caracteres aleatórios",
        )
    return None


def _sso_sem_credencial(c: Configuracao) -> Achado | None:
    if c.auth_mock or (c.entra_tenant_id and c.entra_client_id and c.entra_client_secret):
        return None
    return Achado(
        "ENTRA_*",
        "SSO ligado sem tenant, client id ou secret: ninguém consegue "
        "entrar, e o erro só aparece quando a primeira pessoa tenta",
        "preencher ENTRA_TENANT_ID, ENTRA_CLIENT_ID e ENTRA_CLIENT_SECRET",
    )


def _sem_limite_de_taxa(c: Configuracao) -> Achado | None:
    if c.limite_de_taxa_ligado:
        return None
    return Achado(
        "LIMITE_DE_TAXA_LIGADO",
        "sem limite de taxa, uma única origem consome a capacidade "
        "do serviço inteiro",
        "LIMITE_DE_TAXA_LIGADO=true, ou a borda aplicando o teto",
    )


def _sql_no_log(c: Configuracao) -> Achado | None:
    if not c.banco_echo:
        return None
    return Achado(
        "BANCO_ECHO",
        "o SQLAlchemy passa a registrar cada comando SQL COM OS "
        "PARÂMETROS. O termo pesquisado em `q=` e o conteúdo de `relato` "
        "vão parar no log e na telemetria — exatamente os dados que o "
        "resto deste plano existe para proteger",
        "BANCO_ECHO=false",
    )


def _banco_sem_tls(c: Configuracao) -> Achado | None:
    tls = _problema_no_tls(c.banco_url)
    if not tls or _banco_e_local(c.banco_url):
        return None
    return Achado(
        "BANCO_URL",
        f"{tls}. O tráfego entre o App Service e o Postgres carrega "
        "`relato` e o conteúdo das interações",
        "acrescentar `?sslmode=require` — ou `verify-full`, que também "
        "confere o certificado do servidor",
    )


def _banco_na_propria_maquina(c: Configuracao) -> Achado | None:
    if not _banco_e_local(c.banco_url):
        return None
    return Achado(
        "BANCO_URL",
        "aponta para a própria máquina em produção. É o valor padrão do "
        "código: esquecer a variável no App Service não dá erro de "
        "configuração, dá erro de conexão na primeira consulta — ou, "
        "pior, conecta num Postgres local se houver um",
        "a connection string do Postgres gerenciado",
    )


def _sem_reposicao(campo: str, por_segundo: float) -> Achado | None:
    if por_segundo > 0:
        return None
    return Achado(
        f"LIMITE_POR_{campo}_POR_SEGUNDO",
        "reposição zero ou negativa: o balde nunca devolve ficha. "
        "Depois da rajada inicial, quem for barrado fica barrado "
        "para sempre — inclusive gente legítima",
        "um valor positivo; ver os padrões em `configuracao.py`",
    )


def _sem_capacidade(campo: str, capacidade: int) -> Achado | None:
    if capacidade > 0:
        return None
    return Achado(
        f"LIMITE_POR_{campo}_CAPACIDADE",
        "capacidade zero ou negativa: nenhuma requisição passa",
        "um valor positivo; ver os padrões em `configuracao.py`",
    )


# QUATRO VERIFICAÇÕES, E NÃO DUAS COM UM LAÇO DENTRO.
#
# Foram duas por uma versão, cada uma percorrendo os dois baldes e devolvendo
# no primeiro inválido — e com isso uma configuração que zerava IP E USUÁRIO
# acusava só o IP. Quem corrigisse o que a mensagem apontou subiria de novo e
# levaria o segundo erro na cara.
#
# São quatro porque são quatro perguntas: cada balde tem reposição e
# capacidade, e cada uma quebra de um jeito. `Achado | None` é o contrato de
# todas as verificações; devolver lista aqui obrigaria as outras dez a fazer o
# mesmo para uniformizar.
def _taxa_por_ip_zerada(c: Configuracao) -> Achado | None:
    return _sem_reposicao("IP", c.limite_por_ip_por_segundo)


def _capacidade_por_ip_zerada(c: Configuracao) -> Achado | None:
    return _sem_capacidade("IP", c.limite_por_ip_capacidade)


def _taxa_por_usuario_zerada(c: Configuracao) -> Achado | None:
    return _sem_reposicao("USUARIO", c.limite_por_usuario_por_segundo)


def _capacidade_por_usuario_zerada(c: Configuracao) -> Achado | None:
    return _sem_capacidade("USUARIO", c.limite_por_usuario_capacidade)


# -- o acoplamento que erra em silêncio ---------------------------------------


def _proxy_nao_declarado(c: Configuracao) -> Achado | None:
    """O achado que motivou o módulo.

    Com Front Door na frente e `PROXIES_CONFIAVEIS=0`, o limitador enxerga o IP
    do Front Door em toda requisição: o mundo inteiro passa a dividir um balde
    só. O serviço não quebra, não loga erro, e começa a devolver 429 para gente
    legítima enquanto o atacante gasta a cota de todos.

    O contrário — `PROXIES_CONFIAVEIS=1` sem proxy nenhum — é pior: passa a
    valer o `X-Forwarded-For` que o cliente escreve, e o limite por IP deixa de
    existir.
    """
    if c.proxies_confiaveis != 0:
        return None
    return Achado(
        "PROXIES_CONFIAVEIS",
        "zero em produção. Se houver Front Door ou Application Gateway "
        "na frente, o limite por IP agrupa TODO o tráfego num balde só",
        "1 com Front Door; manter 0 apenas se a aplicação recebe conexão direta",
    )


# -- o que provavelmente não é o que se quis ----------------------------------


def _sem_hsts(c: Configuracao) -> Achado | None:
    if c.hsts_ligado:
        return None
    return Achado(
        "HSTS_LIGADO",
        "desligado em produção: o navegador aceita voltar a http",
        "HSTS_LIGADO=true depois de confirmar que o HTTPS responde",
    )


def _docs_marcados_como_publicos(c: Configuracao) -> Achado | None:
    if not c.docs_publicos:
        return None
    return Achado(
        "DOCS_PUBLICOS",
        "verdadeiro em produção. As rotas são removidas mesmo assim, "
        "porque `criar_app` também exige ambiente diferente de produção",
        "DOCS_PUBLICOS=false, para a intenção ficar explícita",
    )


def _telemetria_desligada(c: Configuracao) -> Achado | None:
    if c.applicationinsights_connection_string:
        return None
    return Achado(
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "vazia: a telemetria não sai do contêiner, e nenhum alerta de "
        "segurança dispara",
        "a connection string do recurso de Application Insights",
    )


#: AS QUE IMPEDEM A APLICAÇÃO DE SUBIR. Cada uma descreve um controle que, em
#: produção, simplesmente não existiria.
GRAVES: tuple[Verificacao, ...] = (
    _autenticacao_de_mentira,
    _origem_impropria,
    _segredo_de_sessao_fraco,
    _sso_sem_credencial,
    _sem_limite_de_taxa,
    _sql_no_log,
    _banco_sem_tls,
    _banco_na_propria_maquina,
    _taxa_por_ip_zerada,
    _capacidade_por_ip_zerada,
    _taxa_por_usuario_zerada,
    _capacidade_por_usuario_zerada,
)

#: AS QUE SÓ AVISAM. A aplicação sobe; o log registra.
AVISOS: tuple[Verificacao, ...] = (
    _proxy_nao_declarado,
    _sem_hsts,
    _docs_marcados_como_publicos,
    _telemetria_desligada,
)


def conferir(configuracao: Configuracao) -> list[Achado]:
    """Devolve os avisos; levanta se algo for grave. Só age em produção.

    ERA UMA FUNÇÃO DE 186 LINHAS com catorze `if` em sequência, e o problema
    não era o tamanho: era que a lista do que se confere só existia lendo o
    corpo inteiro. Agora ela está escrita — em `GRAVES` e `AVISOS` —, e cada
    verificação tem nome, motivo e correção no lugar dela.
    """
    if not configuracao.producao:
        return []

    graves = [a for verificar in GRAVES if (a := verificar(configuracao))]
    avisos = [a for verificar in AVISOS if (a := verificar(configuracao))]

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
