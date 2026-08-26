"""Configuração da aplicação, lida do ambiente."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracao(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    ambiente: str = "desenvolvimento"
    banco_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/painel_reputacional"
    banco_echo: bool = False

    #: Em desenvolvimento a autenticação usa um usuário fixo, provisionado no
    #: primeiro acesso pelo mesmo caminho JIT que o Entra ID usará em produção.
    auth_mock: bool = True
    auth_mock_email: str = "analista@aegea.com.br"
    auth_mock_nome: str = "Analista de Desenvolvimento"
    auth_mock_perfil: str = "analista"

    #: Preenchidos quando `auth_mock` for desligado.
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    entra_client_secret: str | None = None

    #: Precisa bater EXATAMENTE com o registrado no app do Entra ID. Divergência
    #: aqui não dá erro de configuração: dá `AADSTS50011` na cara do usuário,
    #: no meio do login.
    entra_redirect_uri: str = "http://localhost:8000/api/auth/callback"

    #: Base do provedor OIDC. Trocar aponta para nuvem soberana — ou, no
    #: ambiente local, para um provedor falso em contêiner.
    entra_autoridade: str = "https://login.microsoftonline.com"

    #: Para onde o navegador volta depois do login, e a base de todo redirecionamento.
    url_do_front: str = "http://localhost:5173"

    #: Assina o cookie de sessão. Trocar este valor invalida toda sessão viva —
    #: que é, aliás, o botão de emergência para derrubar todo mundo de uma vez.
    #:
    #: O padrão abaixo é público: está no Git. A conferência de subida recusa
    #: produção com ele, porque quem o conhece forja a sessão de qualquer pessoa
    #: — basta trocar o UUID e assinar de novo.
    sessao_secreta: str = "desenvolvimento-nao-use-em-producao"

    origens_permitidas: list[str] = ["http://localhost:5173"]

    #: Telemetria. Sem a connection string o aplicativo sobe igual, só sem
    #: enviar nada — é o que permite desenvolver sem recurso no Azure.
    applicationinsights_connection_string: str | None = None

    # -- limite de taxa -------------------------------------------------------
    #
    # Os números saem do uso real, não do costume. Um recorte do painel custa 25
    # requisições (`listarRecorteCompleto` pagina de 200 em 200 até 5.000), e
    # quem explora filtros faz vários recortes por minuto. Um teto de "60 por
    # minuto" quebraria a terceira mudança de filtro.
    #
    # Por IP é frouxo de propósito: atrás do NAT corporativo da Aegea, todo o
    # escritório compartilha um endereço, e apertar aqui puniria todo mundo pelo
    # excesso de um. Quem de fato limita é o balde por usuário.
    limite_por_ip_capacidade: float = 600.0
    limite_por_ip_por_segundo: float = 40.0

    limite_por_usuario_capacidade: float = 120.0
    limite_por_usuario_por_segundo: float = 8.0

    #: Quantos proxies confiáveis há na frente da aplicação. ZERO significa
    #: ignorar `X-Forwarded-For` por completo e usar o endereço da conexão — o
    #: padrão seguro, porque o cabeçalho é forjável. No App Service atrás do
    #: Front Door, 1.
    proxies_confiaveis: int = 0

    #: Desligar exige motivo. Existe para o desenvolvimento local e para o caso
    #: de a borda (Front Door / WAF) já aplicar o teto.
    limite_de_taxa_ligado: bool = True

    # -- superficie HTTP ------------------------------------------------------
    #
    # Metodos e cabecalhos explicitos, no lugar de `["*"]`. Nao e paranoia: com
    # `allow_credentials=True`, o curinga transforma qualquer origem aceita numa
    # porta para qualquer verbo e qualquer cabecalho, inclusive os que a
    # aplicacao nunca usou e que uma biblioteca futura passe a interpretar.
    metodos_permitidos: list[str] = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
    #: `X-CSRF-Token` PRECISA estar aqui.
    #:
    #: Apertar esta lista e depois criar uma proteção que usa um cabeçalho fora
    #: dela foi exatamente o que aconteceu: o navegador recusa no preflight, com
    #: `400 Disallowed CORS headers`, e a requisição nem chega à rota. Toda
    #: escrita morre — e do lado do servidor não aparece nada, porque nada
    #: chegou.
    cabecalhos_permitidos: list[str] = [
        "Content-Type",
        "Authorization",
        "X-CSRF-Token",
    ]

    #: Um megabyte. O maior corpo legitimo e o formulario de interacao — campos
    #: de texto. Nao existe `UploadFile` em rota nenhuma.
    tamanho_maximo_do_corpo: int = 1_048_576

    #: HSTS tem efeito duradouro: o navegador guarda a instrução por `max_age`
    #: inteiro e passa a recusar http naquele domínio.
    #:
    #: `None` significa "ligado em produção, desligado fora" — o padrão. Manter
    #: `False` fixo era seguro e errado: HSTS desligado em produção é o
    #: contrário do que se quer, e "depois eu ligo" nunca acontece.
    hsts_ligado_bruto: bool | None = Field(default=None, alias="HSTS_LIGADO")

    #: SEPARADO de propósito, e desligado por padrão.
    #:
    #: `includeSubDomains` é a parte perigosa do HSTS: num domínio compartilhado
    #: como `aegea.com.br`, ele obriga HTTPS em TODO subdomínio da companhia —
    #: inclusive nos que este time não conhece e que talvez ainda sirvam http.
    #: Derrubar um sistema alheio a partir daqui não seria aceitável, e desfazer
    #: leva `max_age` inteiro.
    hsts_incluir_subdominios: bool = False

    #: Um ano, o valor que as listas de preload exigem. `preload` em si nunca é
    #: enviado: entrar na lista é praticamente irreversível e é decisão da
    #: companhia, não deste serviço.
    hsts_max_age: int = 31_536_000

    #: `/docs` e `/redoc` desenham a API inteira: cada rota, cada campo, cada
    #: formato. Para um externo isso e o mapa pronto da superficie de ataque.
    #: Em producao o padrao e desligado.
    docs_publicos: bool = True

    #: Vira `cloud_RoleName` no Application Insights. É o que separa este
    #: serviço do frontend quando os dois mandam para o mesmo recurso.
    nome_do_servico: str = "painel-reputacional-api"

    @property
    def producao(self) -> bool:
        return self.ambiente == "producao"

    @property
    def hsts_ligado(self) -> bool:
        """Ligado em produção por padrão; a variável de ambiente vence."""
        if self.hsts_ligado_bruto is None:
            return self.producao
        return self.hsts_ligado_bruto


@lru_cache
def obter_configuracao() -> Configuracao:
    return Configuracao()
