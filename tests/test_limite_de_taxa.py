"""Limite de taxa.

O que estes testes protegem, além do óbvio: os dois modos de errar um limitador.
Ou ele é apertado demais e quebra o uso normal — e aí alguém o afrouxa até virar
enfeite — ou é frouxo o bastante para não incomodar ninguém, inclusive quem se
quer barrar.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.configuracao import Configuracao
from app.seguranca.limite_de_taxa import (
    LimiteDeTaxaMiddleware,
    RegistroDeBaldes,
    custo_da_requisicao,
    ip_do_cliente,
)

# -- o balde ------------------------------------------------------------------


def test_rajada_cabe_ate_a_capacidade():
    registro = RegistroDeBaldes(capacidade=3, por_segundo=1)
    assert registro.consumir("a") is None
    assert registro.consumir("a") is None
    assert registro.consumir("a") is None
    assert registro.consumir("a") is not None


def test_chaves_nao_se_atrapalham():
    registro = RegistroDeBaldes(capacidade=1, por_segundo=1)
    assert registro.consumir("a") is None
    assert registro.consumir("b") is None, "o balde de 'b' não é o de 'a'"
    assert registro.consumir("a") is not None


def test_repoe_com_o_tempo(monkeypatch):
    relogio = {"agora": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: relogio["agora"])

    registro = RegistroDeBaldes(capacidade=2, por_segundo=2)
    registro.consumir("a")
    registro.consumir("a")
    assert registro.consumir("a") is not None

    relogio["agora"] += 0.5  # 0,5 s a 2/s = 1 ficha
    assert registro.consumir("a") is None
    assert registro.consumir("a") is not None


def test_nao_acumula_acima_da_capacidade(monkeypatch):
    """Uma hora parado não compra uma hora de rajada.

    Sem o teto, quem ficasse ocioso acumularia crédito indefinidamente e
    descarregaria tudo de uma vez — que é exatamente o pico que o limite existe
    para evitar.
    """
    relogio = {"agora": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: relogio["agora"])

    registro = RegistroDeBaldes(capacidade=3, por_segundo=1)
    registro.consumir("a")
    relogio["agora"] += 3600

    for _ in range(3):
        assert registro.consumir("a") is None
    assert registro.consumir("a") is not None


def test_espera_devolvida_e_o_tempo_ate_a_proxima_ficha(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    registro = RegistroDeBaldes(capacidade=1, por_segundo=2)
    registro.consumir("a")
    espera = registro.consumir("a")
    assert espera == pytest.approx(0.5)


def test_registro_nao_cresce_sem_limite():
    """O limitador não pode ser o próprio vetor de negação de serviço.

    Sem teto de tamanho, quem alterna o endereço de origem faz o dicionário
    crescer até derrubar o processo por memória — e cada chave nova nasce com o
    balde cheio, então nem sequer é barrado no caminho.
    """
    registro = RegistroDeBaldes(capacidade=1, por_segundo=1, maximo=10)
    for i in range(100):
        registro.consumir(f"ip-{i}")
    assert len(registro._baldes) == 10


# -- de quem é a requisição ---------------------------------------------------


class _RequisicaoFalsa:
    def __init__(self, cabecalhos=None, cliente="203.0.113.9", consulta=None):
        self.headers = cabecalhos or {}
        self.client = type("C", (), {"host": cliente})()
        self.query_params = consulta or {}


def test_cabecalho_forjado_e_ignorado_sem_proxy_declarado():
    """O padrão precisa ser desconfiar.

    `X-Forwarded-For` é texto que o cliente escolhe. Se o limitador acreditar
    nele sem proxy declarado, o atacante troca de identidade a cada requisição e
    o limite deixa de existir — pior, cada valor novo vira uma chave nova no
    registro.
    """
    requisicao = _RequisicaoFalsa(cabecalhos={"x-forwarded-for": "1.2.3.4"})
    assert ip_do_cliente(requisicao, proxies_confiaveis=0) == "203.0.113.9"


def test_com_um_proxy_vale_a_entrada_da_direita():
    """A da esquerda é a que o cliente escreveu; a da direita, a que o proxy pôs.

    Ler a primeira entrada é o costume — e é o erro: ela está sob controle de
    quem se quer identificar.
    """
    requisicao = _RequisicaoFalsa(
        cabecalhos={"x-forwarded-for": "1.2.3.4, 198.51.100.7"}
    )
    assert ip_do_cliente(requisicao, proxies_confiaveis=1) == "198.51.100.7"


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("198.51.100.7", "198.51.100.7"),
        ("198.51.100.7:52431", "198.51.100.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("[2001:db8::1]:52431", "2001:db8::1"),
    ],
)
def test_porta_e_descartada_em_ipv4_e_ipv6(bruto, esperado):
    """A porta muda a cada conexão: mantê-la na chave é não ter limite.

    São quatro formas, e o IPv6 entre colchetes é a que engana — contar os `:`
    não distingue `2001:db8::1` de `[2001:db8::1]:52431`. Se a porta ficar na
    chave, cada requisição de um cliente IPv6 ganha um balde novo e cheio, e a
    camada por IP deixa de existir para ele.
    """
    requisicao = _RequisicaoFalsa(cabecalhos={"x-forwarded-for": bruto})
    assert ip_do_cliente(requisicao, proxies_confiaveis=1) == esperado


def test_ipv6_com_porta_nao_gera_chave_nova_a_cada_conexao():
    """A consequência do bug anterior, medida.

    Sem a normalização, três conexões do MESMO cliente viravam três chaves — e
    três baldes cheios.
    """
    registro = RegistroDeBaldes(capacidade=1, por_segundo=0.01)
    for porta in (52431, 52432, 52433):
        requisicao = _RequisicaoFalsa(
            cabecalhos={"x-forwarded-for": f"[2001:db8::1]:{porta}"}
        )
        chave = ip_do_cliente(requisicao, proxies_confiaveis=1)
        registro.consumir(chave)

    assert len(registro._baldes) == 1, "a porta voltou para a chave"


def test_busca_livre_custa_mais():
    """`ilike` com curinga à esquerda varre trigrama; listar não."""
    assert custo_da_requisicao(_RequisicaoFalsa(consulta={"q": "tarifa"})) == 5.0
    assert custo_da_requisicao(_RequisicaoFalsa(consulta={"frente": "imprensa"})) == 1.0


# -- o teto padrão não pode quebrar o painel ----------------------------------

#: Quanto custa UM recorte: `listarRecorteCompleto` pagina de 200 em 200 até o
#: teto de derivação de 5.000. Está em `frontend/src/compartilhado/api/cliente.ts`.
REQUISICOES_POR_RECORTE = 25


def test_teto_padrao_aguenta_o_uso_normal_do_painel():
    """O modo mais comum de um limitador falhar é quebrando quem é legítimo.

    Quando isso acontece, alguém afrouxa o número até parar de incomodar — e o
    limite vira enfeite. Então o padrão precisa caber com folga em quem apenas
    usa o produto.
    """
    padrao = Configuracao()
    registro = RegistroDeBaldes(
        capacidade=padrao.limite_por_usuario_capacidade,
        por_segundo=padrao.limite_por_usuario_por_segundo,
    )

    # Quatro recortes seguidos, sem pausa: mexer no filtro quatro vezes.
    for _ in range(REQUISICOES_POR_RECORTE * 4):
        assert registro.consumir("pessoa") is None, "o painel normal foi barrado"


def test_teto_padrao_ainda_barra_repeticao_indefinida():
    """Folga não é ausência de teto: em algum ponto a rajada acaba."""
    padrao = Configuracao()
    registro = RegistroDeBaldes(
        capacidade=padrao.limite_por_usuario_capacidade,
        por_segundo=padrao.limite_por_usuario_por_segundo,
    )
    recusas = sum(1 for _ in range(1000) if registro.consumir("raspador") is not None)
    assert recusas > 0


# -- na aplicação -------------------------------------------------------------


def _app_com_limite(capacidade: float) -> FastAPI:
    """Monta a pilha na MESMA ordem de `main.py`: CORS por fora do limite."""
    app = FastAPI()
    app.add_middleware(
        LimiteDeTaxaMiddleware,
        registro=RegistroDeBaldes(capacidade=capacidade, por_segundo=0.01),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/saude")
    def saude() -> dict[str, str]:
        return {"situacao": "ok"}

    @app.get("/api/coisa")
    def coisa() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_excesso_responde_429_com_retry_after():
    cliente = TestClient(_app_com_limite(capacidade=2))
    assert cliente.get("/api/coisa").status_code == 200
    assert cliente.get("/api/coisa").status_code == 200

    recusada = cliente.get("/api/coisa")
    assert recusada.status_code == 429
    # Sem `Retry-After` o cliente tenta de novo na hora, e o limite vira
    # amplificador em vez de freio.
    assert int(recusada.headers["Retry-After"]) >= 1


def test_429_carrega_cabecalho_cors():
    """A recusa precisa ser legível pelo navegador.

    Se o CORS não estiver por fora do limitador, o 429 chega sem cabeçalho e o
    front vê erro opaco de rede — o usuário recebe "falha ao carregar" em vez de
    "muitas requisições", e ninguém descobre o motivo.
    """
    cliente = TestClient(_app_com_limite(capacidade=1))
    origem = {"Origin": "http://localhost:5173"}

    cliente.get("/api/coisa", headers=origem)
    recusada = cliente.get("/api/coisa", headers=origem)

    assert recusada.status_code == 429
    assert recusada.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_saude_nao_e_isenta():
    """A isenção que existia aqui era um buraco, não uma proteção.

    O raciocínio original: o App Service sonda `/api/saude` de poucos em poucos
    segundos, e um 429 faria a plataforma concluir que o serviço caiu. O medo
    era infundado — o balde é POR IP, e a sonda vem de um endereço da
    infraestrutura do Azure. O efeito colateral era real: qualquer um inundava
    aquela rota sem gastar uma ficha.
    """
    cliente = TestClient(_app_com_limite(capacidade=2))
    assert cliente.get("/api/saude").status_code == 200
    assert cliente.get("/api/saude").status_code == 200
    assert cliente.get("/api/saude").status_code == 429, "a isenção voltou"


def test_sonda_de_saude_nunca_encosta_no_teto_padrao(monkeypatch):
    """E o medo que motivou a isenção? Medido, em vez de suposto.

    A sonda do App Service bate a cada poucos segundos. Uma hora inteira dela,
    contra o teto padrão por IP, não chega perto — porque a reposição cobre a
    frequência muitas vezes.
    """
    relogio = {"agora": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: relogio["agora"])

    padrao = Configuracao()
    registro = RegistroDeBaldes(
        capacidade=padrao.limite_por_ip_capacidade,
        por_segundo=padrao.limite_por_ip_por_segundo,
    )

    # Uma hora sondando de 5 em 5 segundos, que é mais agressivo que o padrão
    # do App Service.
    for _ in range(720):
        assert registro.consumir("sonda-do-azure") is None
        relogio["agora"] += 5


def test_excesso_na_dependencia_tambem_vira_429():
    """O middleware e a dependência são caminhos DIFERENTES até o 429.

    O middleware devolve a resposta; a dependência levanta `ExcessoDeRequisicoes`
    e depende do tratador registrado em `app/api/erros.py`. Testar só o
    primeiro deixaria o segundo devolvendo 500 sem ninguém notar.
    """
    from app.api.erros import registrar_tratadores
    from app.seguranca.limite_de_taxa import ExcessoDeRequisicoes

    app = FastAPI()
    registrar_tratadores(app)

    @app.get("/api/coisa")
    def coisa() -> dict[str, bool]:
        raise ExcessoDeRequisicoes(espera_segundos=2.4)

    resposta = TestClient(app, raise_server_exceptions=False).get("/api/coisa")
    assert resposta.status_code == 429
    assert resposta.headers["Retry-After"] == "3", "arredonda para cima"
    # A mensagem não diz qual teto foi atingido nem quanto resta: seria um
    # medidor para calibrar um raspador logo abaixo do limite.
    assert "Muitas requisições" in resposta.json()["detalhe"]
