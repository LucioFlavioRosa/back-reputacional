"""Limite de taxa: balde de fichas por identidade, com o IP como rede de baixo.

CONTRA O QUE ISTO PROTEGE — e contra o que NÃO protege.

Protege de custo e de automação: varredura de endpoint caro, laço de script,
cliente com defeito repetindo em loop, e a rajada anônima que chegaria antes da
autenticação. É também o que impede que uma única origem consuma a capacidade
do serviço inteiro.

**Não protege de exfiltração.** Uma sessão legítima já baixa a base inteira do
escopo dela — `listarRecorteCompleto` pagina de 200 em 200 até 5.000 registros,
porque as análises são derivadas no cliente. Quem limita o que um usuário leva
embora é o escopo (`usuario_escopo`), não o limite de taxa. Qualquer teto
frouxo o bastante para o painel funcionar é frouxo demais para conter quem
simplesmente usa o produto.

E não protege de força bruta de senha, porque não existe senha: a autenticação é
do Entra ID.

DUAS CAMADAS, PORQUE UMA SÓ NÃO SERVE

  1. Por IP, em middleware. Roda antes de qualquer dependência, então barra a
     rajada anônima sem tocar no banco. É grosseira de propósito: atrás do NAT
     corporativo da Aegea todo mundo compartilha um endereço, e apertar aqui
     puniria o escritório inteiro pelo excesso de uma pessoa.

  2. Por usuário, em dependência. Roda depois da identidade resolvida, então
     distingue pessoas atrás do mesmo IP. É a camada que de fato limita.

CUSTO NÃO É UNIFORME

Uma busca livre custa mais que uma listagem: `ilike` com curinga à esquerda
varre índice de trigrama. Cobrar fichas proporcionais ao custo evita ter de
escolher entre um teto que estrangula a navegação normal e um que libera a
consulta cara.

O QUE ESTE MÓDULO NÃO RESOLVE SOZINHO

O estado é **da instância**. No Azure App Service com escala horizontal, N
instâncias significam N vezes o limite, e um reinício zera as contagens. Para um
teto de verdade o lugar é a borda — regra de rate limit no Azure Front Door ou
no Application Gateway WAF, que enxerga o tráfego antes de distribuí-lo. Isto
aqui é o que sobra quando a borda falha ou não existe, e é melhor do que nada
por uma razão específica: a borda não conhece o usuário, só o IP.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

#: Quantas chaves distintas o registro guarda antes de descartar as mais antigas.
#:
#: O teto existe porque o próprio limitador seria um vetor de negação de serviço
#: sem ele: quem alterna o endereço de origem faria o dicionário crescer sem
#: limite até derrubar o processo por memória.
MAXIMO_DE_CHAVES = 20_000

#: Teto do `Retry-After`, em segundos. Uma hora.
#:
#: Serve para dois casos: espera infinita (balde que não repõe) e valores tão
#: grandes que o cliente concluiria que o serviço morreu. Mandar "volte em uma
#: hora" é honesto; mandar "volte em 3 mil anos" é o mesmo que não responder.
ESPERA_MAXIMA = 3600


@dataclass(slots=True)
class Balde:
    """Balde de fichas: acumula folga em silêncio, gasta em rajada.

    Janela fixa não serve aqui. O painel faz 25 requisições seguidas para montar
    um recorte, e uma janela de 60 por minuto recusaria a terceira mudança de
    filtro. O balde absorve a rajada e cobra a média.
    """

    fichas: float
    ultimo: float


class RegistroDeBaldes:
    """Baldes por chave, com teto de tamanho e descarte do mais antigo.

    `OrderedDict` em vez de `dict`: o descarte precisa saber qual chave está
    parada há mais tempo, e mover a chave usada para o fim é O(1).
    """

    def __init__(
        self,
        *,
        capacidade: float,
        por_segundo: float,
        maximo: int = MAXIMO_DE_CHAVES,
    ) -> None:
        self.capacidade = capacidade
        self.por_segundo = por_segundo
        self.maximo = maximo
        self._baldes: OrderedDict[str, Balde] = OrderedDict()
        # Endpoints síncronos rodam no threadpool do uvicorn: sem o cadeado,
        # duas requisições simultâneas da mesma chave leriam o mesmo saldo e
        # gastariam a mesma ficha duas vezes.
        self._cadeado = threading.Lock()

    def consumir(self, chave: str, custo: float = 1.0) -> float | None:
        """Gasta `custo` fichas. Devolve `None` se coube, ou a espera em segundos.

        A espera devolvida vira `Retry-After`, para que o cliente saiba quando
        voltar em vez de tentar de novo na hora e piorar a situação.
        """
        agora = time.monotonic()

        with self._cadeado:
            balde = self._baldes.get(chave)
            if balde is None:
                balde = Balde(fichas=self.capacidade, ultimo=agora)
                self._baldes[chave] = balde
                if len(self._baldes) > self.maximo:
                    self._baldes.popitem(last=False)
            else:
                self._baldes.move_to_end(chave)
                decorrido = agora - balde.ultimo
                balde.fichas = min(
                    self.capacidade, balde.fichas + decorrido * self.por_segundo
                )
                balde.ultimo = agora

            if balde.fichas >= custo:
                balde.fichas -= custo
                return None

            faltam = custo - balde.fichas
            return faltam / self.por_segundo if self.por_segundo > 0 else float("inf")

    def esquecer(self, chave: str) -> None:
        """Devolve a chave ao estado inicial. Existe para os testes."""
        with self._cadeado:
            self._baldes.pop(chave, None)


def ip_do_cliente(requisicao: Request, *, proxies_confiaveis: int = 0) -> str:
    """O endereço de origem, contado a partir da DIREITA de `X-Forwarded-For`.

    O cabeçalho é forjável: qualquer cliente manda `X-Forwarded-For: 1.2.3.4` e
    escolhe a identidade que quiser. O que NÃO é forjável são as entradas que os
    proxies acrescentam no fim — o cliente não controla o que vem depois dele.

    Por isso a contagem é da direita para a esquerda, e o padrão é zero: sem
    proxy declarado o cabeçalho é ignorado por completo e vale o endereço da
    conexão. Ler a primeira entrada, que é o costume, daria ao atacante o poder
    de trocar de identidade a cada requisição — e de encher o registro de baldes
    de passagem.

    No Azure App Service atrás do Front Door, `proxies_confiaveis=1`.
    """
    if proxies_confiaveis > 0:
        encaminhado = requisicao.headers.get("x-forwarded-for")
        if encaminhado:
            entradas = [p.strip() for p in encaminhado.split(",") if p.strip()]
            if len(entradas) >= proxies_confiaveis:
                return _sem_porta(entradas[-proxies_confiaveis])

    return requisicao.client.host if requisicao.client else "desconhecido"


def _sem_porta(bruto: str) -> str:
    """Descarta a porta que o proxy anexa, em IPv4 e em IPv6.

    A porta muda a cada conexão. Mantê-la na chave daria um balde novo por
    requisição — ou seja, limite nenhum. Três formatos aparecem na prática:

        198.51.100.7            IPv4 puro
        198.51.100.7:52431      IPv4 com porta (App Service anexa)
        2001:db8::1             IPv6 puro, cheio de `:`
        [2001:db8::1]:52431     IPv6 com porta, entre colchetes

    A porta PRECISA sair da chave: com ela, cada conexão nova do mesmo endereço
    ganharia um balde próprio, e o limite por IP deixaria de limitar.
    """
    bruto = bruto.strip()

    if bruto.startswith("["):
        fecha = bruto.find("]")
        if fecha != -1:
            return bruto[1:fecha]
        return bruto

    # Mais de um `:` sem colchete é IPv6 puro: não há porta a remover.
    return bruto.rsplit(":", 1)[0] if bruto.count(":") == 1 else bruto


def custo_da_requisicao(requisicao: Request) -> float:
    """Busca livre custa mais: `ilike` com curinga à esquerda varre trigrama."""
    return 5.0 if requisicao.query_params.get("q") else 1.0


def resposta_de_excesso(espera: float) -> JSONResponse:
    """429 com `Retry-After`.

    A mensagem não diz qual limite foi atingido nem quanto resta: seria um
    medidor útil para calibrar um raspador logo abaixo do teto.
    """
    # `espera` pode ser infinita: um balde com reposição zero nunca devolve
    # ficha. `int(inf)` levanta `OverflowError`, e a requisição que devia
    # receber 429 virava 500 — o limitador derrubando o serviço em vez de
    # protegê-lo. A conferência de subida recusa essa configuração, mas o teto
    # aqui é defesa em profundidade: quem constrói o registro na mão não passa
    # por ela.
    segundos = ESPERA_MAXIMA if espera == float("inf") else max(1, int(espera + 0.999))
    return JSONResponse(
        status_code=429,
        content={"detalhe": "Muitas requisições. Tente novamente em instantes."},
        headers={"Retry-After": str(min(segundos, ESPERA_MAXIMA))},
    )


class LimiteDeTaxaMiddleware(BaseHTTPMiddleware):
    """Camada grosseira, por IP, antes de qualquer dependência.

    NÃO isenta rota nenhuma, `/api/saude` inclusive.

    A tentação é isentar a rota de saúde, para não arriscar que a sonda do App
    Service tome 429 e a plataforma recicle a instância. Não é necessário e
    abriria um buraco: o balde é **por IP**, e a sonda vem de um endereço da
    infraestrutura do Azure fazendo cerca de duas requisições por minuto contra
    uma capacidade de centenas — nunca encosta no teto. Uma rota isenta, por
    outro lado, é uma rota que qualquer um inunda sem gastar ficha.

    O `preflight` do CORS também não precisa de isenção: o `CORSMiddleware` fica
    por FORA deste, responde ao preflight e nunca chega aqui.
    """

    def __init__(
        self,
        app,  # noqa: ANN001
        *,
        registro: RegistroDeBaldes,
        proxies_confiaveis: int = 0,
    ) -> None:
        super().__init__(app)
        self.registro = registro
        self.proxies_confiaveis = proxies_confiaveis

    async def dispatch(self, requisicao: Request, seguir) -> Response:  # noqa: ANN001
        chave = ip_do_cliente(requisicao, proxies_confiaveis=self.proxies_confiaveis)
        espera = self.registro.consumir(chave, custo_da_requisicao(requisicao))

        if espera is None:
            return await seguir(requisicao)

        # O evento é emitido AQUI, e não pelo tratador de erro.
        #
        # Esta camada devolve a resposta direto, sem levantar exceção — e por
        # isso não passa por `app/api/erros.py`. A consulta de segurança que
        # procurava `erro == "ExcessoDeRequisicoes"` devolvia ZERO LINHA para
        # justamente o caso mais importante: a rajada anônima, antes de haver
        # identidade. Zero linha sem erro é o pior tipo de alerta errado —
        # parece que não há ataque.
        #
        # Aqui só existe o endereço; não há usuário ainda. É o que dá para
        # registrar, e é o suficiente para agrupar.
        logging.getLogger("painel_reputacional.limite").warning(
            "Limite por IP atingido: %s em %s",
            chave,
            requisicao.url.path,
            extra={
                "evento": "limite_por_ip",
                "camada": "ip",
                "endereco": chave,
                "rota": requisicao.url.path,
                "metodo": requisicao.method,
                "espera_segundos": round(min(espera, ESPERA_MAXIMA), 2),
            },
        )
        return resposta_de_excesso(espera)


class ExcessoDeRequisicoes(Exception):
    """Passou do limite. Vira 429.

    Não herda de `ErroDeDominio` de propósito: limite de taxa não é regra de
    negócio, é proteção de infraestrutura. O domínio não deveria conhecê-lo, e
    um repositório em memória num teste de unidade não tem por que esbarrar
    nisso.
    """

    def __init__(self, espera_segundos: float) -> None:
        self.espera_segundos = espera_segundos
        super().__init__("Muitas requisições. Tente novamente em instantes.")
