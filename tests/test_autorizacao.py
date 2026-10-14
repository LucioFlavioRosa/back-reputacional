"""Autorização: papel, escopo e prazo.

O Entra ID responde "quem é você"; o banco responde "o que você pode". Estes são
os testes de unidade dessa separação. O que precisa de SQL de verdade — o `check`
do prazo, o escopo virando `where` — vive em `test_e2e_postgres`.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.banco.filtros_sql import condicoes
from app.dominio.erros import NaoAutorizado
from app.dominio.frentes import Frente
from app.dominio.identidade import Escopo, Papel, UsuarioAtual
from app.dominio.interacao import Consulta, Interacao
from app.dominio.politica import (
    exigir_permissao_de_edicao,
    pode_editar,
)
from app.dominio.recorte import Recorte
from app.esquemas.interacoes import InteracaoSaida


def nova(**ajustes) -> Interacao:
    padroes = dict(
        frente=Frente.IMPRENSA,
        data_interacao=date(2026, 5, 7),
        instituicao_id=uuid4(),
        uf="SP",
        status="confirmada",
        pauta="Reajuste tarifário em concessões",
    )
    return Interacao(**{**padroes, **ajustes})


def pessoa(papel: Papel | None, escopo: Escopo | None = None, **ajustes) -> UsuarioAtual:
    return UsuarioAtual(
        id=ajustes.pop("id", uuid4()),
        nome="Fulano",
        email="f@aegea.com.br",
        papel=papel,
        escopo=escopo or Escopo.total(),
        **ajustes,
    )


EXTERNO = Papel(codigo="score_leitura", nome="Externo")
COORDENACAO = Papel(
    codigo="plataforma_edicao",
    nome="Coordenação",
    pode_criar=True,
    pode_editar_tudo=True,
    ve_campos_sensiveis=True,
    ve_diretorio=True,
    pode_exportar=True,
)


# -- o escopo é obrigatório por construção ------------------------------------


def test_condicoes_sem_escopo_nao_compila():
    """A garantia mais importante deste desenho não é um `if` — é a assinatura.

    Enquanto `escopo` for argumento obrigatório, esquecê-lo em qualquer consulta
    nova é `TypeError` no primeiro teste que a exercitar. Se algum dia alguém
    lhe der um valor padrão, este teste cai e a leitura sem restrição volta a
    ser possível em silêncio.
    """
    with pytest.raises(TypeError):
        condicoes(Recorte())

    # O MESMO VALE PARA `alcanca_sensivel`, e desde 0089 vale mais: ele deixou
    # de decidir só quais colunas a busca varre e passou a decidir quais LINHAS
    # existem. Sem ele obrigatório, uma consulta nova nasceria enxergando as
    # agendas sensíveis de todo mundo — e nada quebraria para avisar.
    with pytest.raises(TypeError):
        condicoes(Recorte(), escopo=Escopo.total())


def test_escopo_irrestrito_nao_acrescenta_condicao():
    apenas_estado = condicoes(
        Recorte(), escopo=Escopo.total(), alcanca_sensivel=True
    )
    # `arquivado_em is null` e `visivel is true` — o filtro por estado, que
    # nunca dependeu de quem pede.
    assert len(apenas_estado) == 2


def test_escopo_restrito_sem_concessao_nao_alcanca_nada():
    """Falha fechada: o convidado recém-provisionado não enxerga a base.

    A alternativa natural — "sem linha significa sem restrição" — daria acesso
    total a quem ainda não recebeu concessão nenhuma, que é exatamente o caso
    que motivou este plano.
    """
    escopo = Escopo(irrestrito=False)
    assert escopo.nao_alcanca_nada

    onde = condicoes(Recorte(), escopo=escopo, alcanca_sensivel=False)
    assert str(onde[0]) == "false"


def test_escopo_por_frente_entra_como_condicao():
    onde = condicoes(
        Recorte(),
        escopo=Escopo(frentes=frozenset({"imprensa"})),
        alcanca_sensivel=True,
    )
    sql = " ".join(str(c) for c in onde)
    assert "frente_id IN" in sql


def test_escopo_nao_e_afrouxado_pelo_recorte():
    """O usuário refina o que já lhe é permitido; jamais amplia.

    Pedir `frente=governo` com escopo de `imprensa` não troca uma condição pela
    outra — as duas entram, e o resultado é vazio. Aqui se conta apenas que as
    duas condições existem; que a interseção seja de fato vazia está provado
    contra o Postgres em `test_recorte_nao_amplia_o_escopo`.
    """
    onde = condicoes(
        Recorte(frente="governo"),
        escopo=Escopo(frentes=frozenset({"imprensa"})),
        alcanca_sensivel=True,
    )
    do_recorte = [c for c in onde if "frente_id =" in str(c)]
    do_escopo = [c for c in onde if "frente_id IN" in str(c)]
    assert do_recorte and do_escopo, "uma das duas condições sumiu"


def test_a_agenda_sensivel_sai_do_conjunto_de_quem_nao_a_alcanca():
    """O filtro é de LINHA, e é por isso que ele vale para tudo.

    ESTE TESTE MUDOU DE SENTIDO em 0089, e o anterior está citado aqui porque
    a troca é a parte que importa. Ele se chamava
    `test_busca_nao_varre_relato_sem_permissao` e provava o contrário desta
    asserção: que `relato` saía da busca para quem não tinha a camada. Fazia
    sentido quando a informação sensível era uma lista de CAMPOS — o registro
    aparecia para todos, alguns campos vinham nulos, e deixá-los pesquisáveis
    seria um oráculo.

    Agora quem classifica é quem registra, uma agenda por vez, e o efeito é
    sobre a linha: a agenda marcada não está no conjunto. Sem campo escondido
    não há o que deduzir, e condicionar colunas da busca só esconderia da pessoa
    certa o texto que ela lê na tela ao lado.
    """
    com_direito = condicoes(
        Recorte(busca="off the record"),
        escopo=Escopo.total(),
        alcanca_sensivel=True,
    )
    sql_com = " ".join(str(c) for c in com_direito)
    #: Quem alcança não leva filtro de linha nenhum...
    assert "interacao.sensivel" not in sql_com
    #: ...e busca nos mesmos campos de sempre.
    assert "interacao.relato" in sql_com

    sem_direito = condicoes(
        Recorte(busca="off the record"),
        escopo=Escopo.total(),
        alcanca_sensivel=False,
    )
    sql_sem = " ".join(str(c) for c in sem_direito)
    #: A LINHA É QUE SAI. É esta condição que tira a agenda da Base, da ficha,
    #: do KPI e da busca de uma vez — e por isso ela basta.
    assert "interacao.sensivel" in sql_sem
    #: A busca varre os MESMOS campos: o que a pessoa alcança, alcança inteiro.
    assert "interacao.relato" in sql_sem
    assert "interacao.pauta" in sql_sem


# -- prazo de concessão --------------------------------------------------------


def test_sem_prazo_nao_vence():
    assert not pessoa(COORDENACAO).acesso_vencido(hoje=date(2030, 1, 1))


def test_vence_no_dia_seguinte_e_nao_no_proprio_dia():
    """O último dia ainda é válido: o prazo é `até`, não `antes de`."""
    externo = pessoa(EXTERNO, externo=True, acesso_expira_em=date(2026, 12, 31))
    assert not externo.acesso_vencido(hoje=date(2026, 12, 31))
    assert externo.acesso_vencido(hoje=date(2027, 1, 1))


# -- papel ---------------------------------------------------------------------


def test_sem_papel_nao_edita_nada():
    """O estado normal do convidado B2B no primeiro login."""
    convidado = pessoa(None)
    assert convidado.sem_autorizacao
    assert not pode_editar(convidado, nova())


def test_externo_e_somente_leitura():
    externo = pessoa(EXTERNO)
    assert externo.somente_leitura
    with pytest.raises(NaoAutorizado, match="somente de leitura"):
        exigir_permissao_de_edicao(externo, nova())


def test_a_agenda_que_chega_chega_inteira():
    """A SERIALIZAÇÃO JÁ NÃO MASCARA NADA, e isso é a mudança de 0089.

    Aqui havia dois testes — `test_papel_sem_campos_sensiveis_recebe_nulo` e
    `test_a_consulta_recebida_perde_o_que_identifica_e_guarda_o_que_opera` — que
    provavam o mascaramento: `relato`, `pendencias`, `remetente`, `teor` e
    `motivo` voltando nulos para quem não tinha a camada.

    O mascaramento saiu porque a restrição mudou de lugar: quem não alcança a
    agenda não recebe a agenda (`filtros_sql.condicoes`, filtro de LINHA). A
    que chega até a serialização é uma que a pessoa alcança, e mascarar campos
    nela esconderia dela o que tem direito de ler.

    Este teste é o inverso dos dois antigos, e existe para que a volta do
    mascaramento seja uma escolha e não um acidente: `de_dominio` nem aceita
    mais a bandeira.
    """
    interacao = nova(
        # `id` explícito: o agregado só ganha o dele ao ser persistido, e o
        # esquema de saída exige um.
        id=uuid4(),
        relato="Off the record com o repórter",
        pendencias="Aguarda jurídico",
        consulta=Consulta(
            canal_id=1,
            remetente="analista@banco.com",
            teor="Como tratam a hipótese de não renegociação?",
            motivo="Quer justificar revisão de spread.",
            prazo_resposta=date(2026, 6, 30),
        ),
    )

    saida = InteracaoSaida.de_dominio(interacao)
    assert saida.relato == "Off the record com o repórter"
    assert saida.pendencias == "Aguarda jurídico"
    assert saida.consulta is not None
    assert saida.consulta.remetente == "analista@banco.com"
    assert saida.consulta.teor is not None
    assert saida.consulta.motivo is not None

    #: E A ASSINATURA NÃO ACEITA MAIS A BANDEIRA. É o que impede uma rota de
    #: continuar passando a bandeira antiga e mascarar em silêncio.
    #:
    #: O nome do argumento vai por `**` de propósito: escrito por extenso, ele
    #: seria apanhado pelo mesmo tipo de troca em massa que me apagou esta
    #: asserção uma vez — o script procurava `, <nome>=False)` para limpar as
    #: chamadas reais e limpou também a que existe para provar que elas doem.
    with pytest.raises(TypeError):
        InteracaoSaida.de_dominio(interacao, **{"ve_campos_sensiveis": False})


def test_a_classificacao_da_agenda_sai_no_payload():
    """Quem alcança precisa VER que a agenda está marcada.

    Sem isto, quem classificou não tem como conferir que a marca pegou — e a
    tela não tem como distinguir a linha restrita na lista.
    """
    assert InteracaoSaida.de_dominio(nova(id=uuid4())).sensivel is False
    assert InteracaoSaida.de_dominio(nova(id=uuid4(), sensivel=True)).sensivel is True


def test_limite_vem_antes_da_autorizacao():
    """Quem ainda não foi liberado não pode repetir de graça.

    Na ordem inversa — autorizar primeiro, limitar depois — um convidado B2B
    autenticado e sem papel repetiria a requisição indefinidamente: cada uma
    devolvia 403 e custava uma consulta ao banco, sem nunca gastar ficha. É
    justamente quem ainda não tem permissão que tem menos razão para receber
    tratamento ilimitado.
    """
    from app.api import dependencias
    from app.configuracao import Configuracao
    from app.dominio.erros import NaoAutorizado
    from app.seguranca.limite_de_taxa import ExcessoDeRequisicoes

    convidado = pessoa(None)  # autenticado no diretório, sem papel concedido
    apertado = Configuracao(
        limite_por_usuario_capacidade=2, limite_por_usuario_por_segundo=0.001
    )
    requisicao = type("R", (), {"query_params": {}})()

    # As primeiras passam pelo limite e morrem na autorização, como deve ser.
    for _ in range(2):
        with pytest.raises(NaoAutorizado):
            dependencias.obter_usuario_atual(requisicao, convidado, apertado)

    # A terceira nem chega lá: o balde acabou.
    with pytest.raises(ExcessoDeRequisicoes):
        dependencias.obter_usuario_atual(requisicao, convidado, apertado)


def test_registro_de_baldes_acompanha_a_configuracao():
    """Um registro global grudaria no primeiro teto visto.

    Recriar a aplicação no mesmo processo — que é o que os testes fazem —
    continuaria usando o teto antigo, e o teste validaria um limite diferente do
    que roda.
    """
    from app.api.dependencias import (
        _registro_por_usuario,
    )
    from app.configuracao import Configuracao

    estreito = _registro_por_usuario(Configuracao(limite_por_usuario_capacidade=1))
    largo = _registro_por_usuario(Configuracao(limite_por_usuario_capacidade=999))

    assert estreito.capacidade == 1
    assert largo.capacidade == 999
    assert estreito is not largo
