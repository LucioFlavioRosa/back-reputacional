"""A credencial da aplicação no Azure, sem segredo nenhum.

TRÊS COISAS PEDEM CREDENCIAL — o Postgres, o Blob e a troca do código do SSO —
e as três usam a MESMA identidade gerenciada do contêiner. Concentrá-la aqui é
o que impede três formas diferentes de provar quem somos, cada uma com o seu
jeito de expirar.

NADA DISTO VALE EM DESENVOLVIMENTO. Localmente o Postgres tem senha na URL, o
Azurite tem cadeia de conexão e o SSO está desligado: quem chama estas funções
são os caminhos que só existem quando o ambiente NÃO tem segredo para oferecer.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

#: O escopo do token que o Postgres Flexible Server aceita NO LUGAR DA SENHA.
ESCOPO_POSTGRES = "https://ossrdbms-aad.database.windows.net/.default"

#: O escopo do token que prova, ao Entra ID, que somos o cliente do App
#: Registration — a credencial federada aponta para esta identidade.
ESCOPO_TROCA_DE_TOKEN = "api://AzureADTokenExchange/.default"

#: Cinco minutos de folga antes do vencimento. Um token que vence no caminho
#: entre pedir e usar falha como "senha errada", que é o erro mais difícil de
#: ler quando não há senha nenhuma.
FOLGA_ANTES_DE_VENCER = 300


@lru_cache
def credencial():
    """A identidade do contêiner, ou o `az login` de quem desenvolve.

    DUAS CREDENCIAIS, E O AMBIENTE DECIDE.

    `AZURE_CLIENT_ID` sozinho NÃO significa identidade gerenciada: ele também
    nomeia o cliente de um service principal, ao lado de `AZURE_TENANT_ID` e de
    um segredo ou certificado — que é como um CI se autentica. Tratar os dois
    casos como um só quebraria o CI, mandando-o pedir um token de identidade
    que ele não tem. Por isso a condição olha o CONJUNTO.

    COM IDENTIDADE GERENCIADA, `ManagedIdentityCredential` — determinística. O
    `DefaultAzureCredential` percorre uma CADEIA: variáveis de ambiente, depois
    identidade gerenciada, depois a credencial do `az`, e assim por diante. Em
    produção isso custa três coisas: latência a cada tentativa que falha antes
    da certa; diagnóstico ruim, porque a falha vem no fim da cadeia e não diz
    qual elo era o certo; e o risco de autenticar como OUTRA identidade, se
    alguma variável de ambiente sobrar no lugar errado.

    FORA DELE, `DefaultAzureCredential` — que é justamente o que faz o `az
    login` de quem desenvolve valer sem configuração nenhuma.

    Ver a orientação da Microsoft em "Passwordless connections for Azure
    services": credencial determinística em produção, cadeia só no
    desenvolvimento.
    """
    identidade = os.environ.get("AZURE_CLIENT_ID")
    if identidade and not _e_service_principal():
        return ManagedIdentityCredential(client_id=identidade)
    return DefaultAzureCredential()


def _e_service_principal() -> bool:
    """O ambiente descreve um service principal, e não uma identidade do host.

    É o que o `EnvironmentCredential` consome, e a cadeia do
    `DefaultAzureCredential` o encontra primeiro — que é o comportamento certo
    para um CI.
    """
    return bool(
        os.environ.get("AZURE_TENANT_ID")
        and (
            os.environ.get("AZURE_CLIENT_SECRET")
            or os.environ.get("AZURE_CLIENT_CERTIFICATE_PATH")
        )
    )


class _TokenComPrazo:
    """Um token por escopo, renovado antes de vencer.

    GUARDAR IMPORTA: pedir token a cada conexão põe uma chamada de rede no
    caminho de toda requisição. O SDK já tem cache próprio, e esta camada
    existe para a folga ser explícita e para o teste conseguir olhar.
    """

    def __init__(self, escopo: str) -> None:
        self._escopo = escopo
        self._valor = ""
        self._expira_em = 0.0

    def __call__(self) -> str:
        if time.time() > self._expira_em - FOLGA_ANTES_DE_VENCER:
            self._valor, self._expira_em = self._buscar()
        return self._valor

    def _buscar(self) -> tuple[str, float]:
        """Pede o token, e traduz a recusa.

        O ERRO DO SDK NÃO DIZ O QUE FAZER. Ele fala de credencial e de cadeia,
        e chega a quem opera dentro de um "autenticação falhou" do Postgres ou
        de um 500 do upload — longe da causa, que é sempre a mesma: a
        identidade do contêiner não está configurada ou não tem permissão.

        Levanta o mesmo tipo, para nada acima precisar saber deste módulo.
        """
        try:
            token = credencial().get_token(self._escopo)
        except ClientAuthenticationError as erro:
            identidade = os.environ.get("AZURE_CLIENT_ID") or "(nenhuma)"
            raise ClientAuthenticationError(
                f"Não foi possível obter token para {self._escopo}. "
                f"AZURE_CLIENT_ID={identidade}. Confira, nesta ordem: a "
                f"identidade atribuída ao contêiner, a permissão dela neste "
                f"recurso, o escopo acima, e a saída para o endpoint de "
                f"identidade. Causa: {erro}"
            ) from erro
        return token.token, float(token.expires_on)


token_para_postgres = _TokenComPrazo(ESCOPO_POSTGRES)
token_para_troca = _TokenComPrazo(ESCOPO_TROCA_DE_TOKEN)
