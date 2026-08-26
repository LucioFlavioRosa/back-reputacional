"""O cache de autorização: o que ele economiza e o que ele não pode cegar.

Papel e escopo passaram a valer por um tempo em memória, em vez de serem lidos
a cada requisição. A troca é deliberada — leitura é constante, mudança de
permissão é rara —, mas ela tem um preço, e este arquivo é onde o preço fica
medido em vez de suposto.

O caminho HTTP completo está em `test_acesso_http.py`. Aqui é a unidade.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.dominio.identidade import Escopo, Papel, UsuarioAtual
from app.seguranca.cache_de_autorizacao import (
    _TETO_DE_ENTRADAS,
    CacheDeAutorizacao,
    _Entrada,
    cache_para,
    esquecer_em_todos,
    limpar_todos,
)


def _usuario(*, expira_em: date | None = None) -> UsuarioAtual:
    # `date`, e NÃO `datetime`: é o que a coluna `acesso_expira_em` guarda e o
    # que o ORM devolve. Fabricar `datetime` aqui — que passa no type checker,
    # porque `datetime` herda de `date` — faria os testes exercitarem um tipo
    # que a produção nunca produz.
    return UsuarioAtual(
        id=uuid4(),
        nome="Pessoa",
        email="pessoa@aegea.com.br",
        papel=Papel(
            codigo="coordenacao",
            nome="Coordenação",
            pode_criar=True,
            pode_editar_proprio=True,
            pode_editar_tudo=True,
            administra_dicionarios=True,
            administra_acessos=True,
            ve_campos_sensiveis=True,
            ve_diretorio=True,
            pode_exportar=True,
        ),
        escopo=Escopo.total(),
        externo=False,
        acesso_expira_em=expira_em,
    )


# -- o que ele economiza -------------------------------------------------------


def test_guarda_e_devolve_dentro_da_janela():
    cache = CacheDeAutorizacao(ttl_segundos=60)
    usuario = _usuario()
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is usuario


def test_quem_nunca_foi_guardado_da_none():
    cache = CacheDeAutorizacao(ttl_segundos=60)
    assert cache.obter(uuid4()) is None


def test_a_entrada_vence():
    cache = CacheDeAutorizacao(ttl_segundos=0.05)
    usuario = _usuario()
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is not None
    time.sleep(0.08)
    assert cache.obter(usuario.id) is None


def test_ttl_zero_desliga():
    """A saída para quem não aceitar a janela: nada é guardado."""
    cache = CacheDeAutorizacao(ttl_segundos=0)
    usuario = _usuario()
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is None
    assert not cache.ligado


# -- o que ele NÃO pode cegar --------------------------------------------------


def test_usuario_com_prazo_e_guardado_sem_estourar():
    """O tipo real do prazo é `date`, e o cache tem de aguentá-lo.

    Este teste existe por um defeito de verdade: a primeira versão fazia
    `prazo.tzinfo`, que só existe em `datetime`. Com o `date` que o banco
    devolve, levantava `AttributeError` — ou seja, 500 na primeira requisição de
    TODO convidado externo, que é justamente quem é obrigado a ter prazo.

    Passou despercebido porque o teste fabricava `datetime`, que herda de
    `date` e tem `tzinfo`.
    """
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario(expira_em=date.today() + timedelta(days=1))
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is not None


def test_o_prazo_vale_o_dia_inteiro():
    """Vencer HOJE não é vencido: `acesso_vencido()` só reprova quando a data
    UTC PASSOU do prazo. O cache tem de concordar, senão o último dia de acesso
    de quem é de fora some — e some em silêncio."""
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario(expira_em=date.today())
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is not None
    assert not usuario.acesso_vencido()


def test_acesso_ja_vencido_nao_vira_entrada():
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario(expira_em=date.today() - timedelta(days=1))
    assert usuario.acesso_vencido()
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is None


def test_o_prazo_encurta_a_janela_quando_e_menor_que_o_ttl():
    """A garantia, medida em vez de afirmada: com o prazo vencendo no fim deste
    dia UTC e um TTL de trinta dias, a entrada tem de morrer com o dia."""
    cache = CacheDeAutorizacao(ttl_segundos=30 * 24 * 3600)
    usuario = _usuario(expira_em=date.today())

    sobra_do_dia = (
        datetime.combine(
            date.today() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        )
        - datetime.now(UTC)
    ).total_seconds()

    vale_ate = cache._ate_quando(usuario)
    assert vale_ate is not None
    assert vale_ate - time.monotonic() <= sobra_do_dia + 1


def test_datetime_no_lugar_do_date_tambem_funciona():
    """Defensivo: `datetime` herda de `date`, então o type checker aceita um no
    lugar do outro. Se uma carga ou um teste trouxer `datetime`, o cache não
    pode estourar."""
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario(expira_em=datetime.now(UTC) + timedelta(days=1))
    cache.guardar(usuario)
    assert cache.obter(usuario.id) is not None


def test_esquecer_tira_no_ato():
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario()
    cache.guardar(usuario)
    cache.esquecer(usuario.id)
    assert cache.obter(usuario.id) is None


def test_esquecer_quem_nao_esta_guardado_nao_levanta():
    CacheDeAutorizacao(ttl_segundos=300).esquecer(uuid4())


# -- o registro do processo ----------------------------------------------------


def test_o_mesmo_ttl_devolve_o_mesmo_cache():
    """Se rendesse um cache novo, cada requisição começaria vazia e o cache não
    economizaria nada — falhando em silêncio, que é o pior modo."""
    assert cache_para(123.0) is cache_para(123.0)


def test_ttl_diferente_rende_cache_diferente():
    assert cache_para(11.0) is not cache_para(12.0)


def test_esquecer_em_todos_alcanca_todos_os_ttl():
    """Quem revoga não sabe qual configuração está em vigor, e não deveria
    precisar saber: a pergunta é "ninguém mais pode servir a permissão antiga
    desta pessoa"."""
    limpar_todos()
    usuario = _usuario()
    for ttl in (31.0, 32.0, 33.0):
        cache_para(ttl).guardar(usuario)

    esquecer_em_todos(usuario.id)

    for ttl in (31.0, 32.0, 33.0):
        assert cache_para(ttl).obter(usuario.id) is None


def test_limpar_todos_esvazia():
    usuario = _usuario()
    cache_para(41.0).guardar(usuario)
    limpar_todos()
    assert cache_para(41.0).obter(usuario.id) is None


# -- a corrida entre ler do banco e revogar ------------------------------------


def test_revogar_durante_a_leitura_recusa_o_valor_velho():
    """A corrida que anulava "revogar pela tela vale no ato".

        requisição A  erra o cache e começa a ler do banco
        admin         revoga, e a revogação chama `esquecer()`
        requisição A  termina a leitura e guarda o que leu — o valor VELHO

    Sem o marcador, a permissão revogada ressuscitava e valia por mais um TTL
    inteiro — na instância onde alguém acabou de revogar, que é onde a pessoa
    vai conferir se a revogação pegou.
    """
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario()

    marcador = cache.marcador()  # A pega o marcador e vai ao banco
    cache.esquecer(usuario.id)  # o admin revoga no meio
    cache.guardar(usuario, marcador)  # A volta com o valor velho

    assert cache.obter(usuario.id) is None


def test_sem_revogacao_no_meio_o_valor_e_guardado():
    """O contrapeso do teste acima: o marcador não pode recusar o caso normal,
    senão o cache não cacheia nada e a economia é zero — em silêncio."""
    cache = CacheDeAutorizacao(ttl_segundos=300)
    usuario = _usuario()

    marcador = cache.marcador()
    cache.guardar(usuario, marcador)

    assert cache.obter(usuario.id) is not None


def test_revogar_outra_pessoa_tambem_recusa_a_gravacao_em_curso():
    """Documenta que o marcador é GLOBAL, e não por usuário.

    É mais amplo que o estritamente necessário, e de propósito: invalidação é
    rara, recusar de mais custa uma releitura, recusar de menos custa
    autorização errada.
    """
    cache = CacheDeAutorizacao(ttl_segundos=300)
    alguem = _usuario()

    marcador = cache.marcador()
    cache.esquecer(uuid4())  # outra pessoa qualquer
    cache.guardar(alguem, marcador)

    assert cache.obter(alguem.id) is None


# -- o teto ---------------------------------------------------------------------


def test_o_teto_degrada_para_sem_cache_em_vez_de_crescer():
    """Encostar no teto não pode falhar: o cache nunca é necessário para a
    resposta estar correta, então a degradação é "reler sempre"."""
    cache = CacheDeAutorizacao(ttl_segundos=300)
    cache._entradas = {uuid4(): _Entrada(usuario=_usuario(), vale_ate=1e18)
                       for _ in range(_TETO_DE_ENTRADAS)}

    excedente = _usuario()
    cache.guardar(excedente)

    assert cache.obter(excedente.id) is None
    assert len(cache._entradas) == _TETO_DE_ENTRADAS


def test_o_teto_poda_as_vencidas_antes_de_desistir():
    cache = CacheDeAutorizacao(ttl_segundos=300)
    cache._entradas = {uuid4(): _Entrada(usuario=_usuario(), vale_ate=0.0)
                       for _ in range(_TETO_DE_ENTRADAS)}

    novo = _usuario()
    cache.guardar(novo)

    assert cache.obter(novo.id) is not None
    assert len(cache._entradas) == 1
