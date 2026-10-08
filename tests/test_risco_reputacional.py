"""O eixo de risco do `Risk tracking map`, e o enquadramento de cada subtema.

DE ONDE VEM. A planilha de taxonomia (set/2026) tem três abas. Duas já estavam
no banco antes desta mudança: a `Taxonomia de temas` é a taxonomia v4 que a
`0058` carregou — 7 pilares em `bloco_tema`, 41 temas estratégicos em
`macro_tema`, 104 subtemas nos 104 `tema` ativos. A terceira, o
`Risk tracking map`, entrou na `0060`.

O QUE ESTES TESTES PROTEGEM, e nenhum deles é hipotético:

  o mapa é funcional      32 riscos distintos, cada um com UM cluster e UMA
                          severidade. É isso que permite a tela preencher três
                          campos com uma escolha. Se um risco ganhar dois
                          clusters, o preenchimento automático passa a mentir e
                          ninguém descobre pela tela.

  `risco_id` != `e_risco` são dois eixos, de fontes diferentes, que divergem em
                          21 dos 104 subtemas. Juntá-los num só seria perder a
                          classificação v3 — e é tentador, porque na maioria
                          eles concordam.

  nulo é resposta         4 subtemas vêm da planilha com "Sem enquadramento". A
                          Aegea olhou e decidiu que não há risco a rastrear ali;
                          um `not null` com default transformaria essa decisão
                          em dado inventado.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.catalogo import listar_dicionarios
from tests.test_e2e_postgres import URL

_engine = create_engine(URL)

#: As três severidades da aba, e nada mais. Escala, não texto livre.
SEVERIDADES = {"moderado", "alto", "critico"}


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def test_a_aba_inteira_entrou(sessao):
    """32 riscos em 8 clusters — o tamanho da aba `Risk tracking map`."""
    riscos = sessao.execute(text("select count(*) from risco_reputacional")).scalar_one()
    clusters = sessao.execute(
        text("select count(distinct cluster) from risco_reputacional")
    ).scalar_one()
    assert riscos == 32
    assert clusters == 8


def test_cada_risco_determina_um_cluster_e_uma_severidade(sessao):
    """A invariante que o preenchimento automático da tela usa.

    Escolher o risco preenche cluster e severidade. Isso só é verdade porque o
    nome do risco é único — e é esta asserção que avisa se deixar de ser.
    """
    ambiguos = sessao.execute(
        text("""
            select nome, count(*)
              from risco_reputacional
             group by nome having count(*) > 1
        """)
    ).all()
    assert not ambiguos, f"risco com mais de uma linha: {ambiguos}"


def test_severidade_fora_da_escala_e_recusada_pelo_banco(sessao):
    """O `check` do banco, e não só a validação do Python.

    "Médio" digitado ao lado de "Moderado" partiria qualquer contagem em duas, e
    quem insere pode ser uma migration ou um script — que não passam pela API.
    """
    with pytest.raises(Exception) as falha:
        sessao.execute(
            text("""
                insert into risco_reputacional (cluster, nome, severidade)
                values ('Riscos Operacionais', 'Risco de mentira', 'Medio')
            """)
        )
    assert "risco_severidade_valida" in str(falha.value)


def test_cluster_fora_dos_oito_e_recusado_pelo_banco(sessao):
    """O cluster é coluna e não tabela — este `check` é o que faz o papel da FK.

    Sem ele, um "Riscos Operacionais " com espaço no fim viraria um nono cluster
    e apareceria como opção nova no formulário.
    """
    with pytest.raises(Exception) as falha:
        sessao.execute(
            text("""
                insert into risco_reputacional (cluster, nome, severidade)
                values ('Cluster inventado', 'Outro risco de mentira', 'alto')
            """)
        )
    assert "risco_cluster_valido" in str(falha.value)


def test_cem_subtemas_enquadrados_e_quatro_sem(sessao):
    """O que a planilha diz, linha por linha: 100 com risco, 4 "Sem enquadramento"."""
    com = sessao.execute(
        text("select count(*) from tema where ativo and risco_id is not null")
    ).scalar_one()
    sem = sessao.execute(
        text("select count(*) from tema where ativo and risco_id is null")
    ).scalar_one()
    assert (com, sem) == (100, 4)


def test_os_quatro_sem_enquadramento_sao_os_da_planilha(sessao):
    """Nomeados, porque "quatro" sozinho passaria com os quatro errados."""
    nomes = {
        n
        for (n,) in sessao.execute(
            text("select nome from tema where ativo and risco_id is null")
        )
    }
    assert nomes == {
        "Estrutura de governança / Conselho e comitês",
        "Modelo Operacional Aegea",
        "Benefícios do saneamento (saúde, educação, imóveis, socioeconômico)",
        "Drenagem urbana e águas pluviais",
    }


def test_risco_e_e_risco_sao_eixos_DIFERENTES(sessao):
    """E têm de continuar sendo.

    `e_risco` é a binária Risco/Outros da taxonomia v3 (Peers/Comms); `risco_id`
    é o enquadramento do `Risk tracking map`. Eles concordam em 83 dos 104 e
    divergem em 21. Este teste existe para que ninguém "arrume" a divergência
    derivando um do outro: a reconciliação é decisão do dono do produto, e
    derivá-la em código apagaria a classificação v3 sem ninguém pedir.
    """
    divergem = sessao.execute(
        text("""
            select count(*) from tema
             where ativo
               and coalesce(e_risco, false) <> (risco_id is not null)
        """)
    ).scalar_one()
    assert divergem == 21, (
        "os dois eixos divergem em 21 subtemas; se este número mudou, alguém "
        "mexeu num dos dois — confira qual antes de ajustar o teste"
    )


def test_apagar_um_risco_usado_e_barrado(sessao):
    """`on delete restrict`: o enquadramento ficaria sem sentido.

    Aposentar um risco é `ativo = false`, não `delete` — é a mesma regra dos
    outros dicionários do painel.
    """
    usado = sessao.execute(
        text("select risco_id from tema where risco_id is not null limit 1")
    ).scalar_one()
    with pytest.raises(Exception) as falha:
        sessao.execute(
            text("delete from risco_reputacional where id = :i"), {"i": usado}
        )
    assert "tema" in str(falha.value).lower()


def test_os_riscos_saem_nos_dicionarios_para_a_tela_ter_as_opcoes(sessao):
    """A tela não pode ter lista fixa de risco nem de cluster.

    É a mesma regra dos outros vocabulários: acrescentar uma linha no banco faz
    a opção aparecer na próxima carga, sem build e sem deploy.
    """
    riscos = listar_dicionarios(sessao)["riscos_reputacionais"]

    assert len(riscos) == 32
    assert {r["severidade"] for r in riscos} <= SEVERIDADES
    assert len({r["cluster"] for r in riscos}) == 8
    # Cada item carrega os três campos que a tela mostra, para o front resolver
    # cluster e severidade a partir do risco escolhido sem uma segunda chamada.
    for r in riscos:
        assert {"id", "nome", "cluster", "severidade"} <= set(r)
        assert "ativo" not in r


def test_risco_desativado_sai_das_opcoes(sessao):
    """Mesma regra dos outros dicionários: desativar tira do formulário e o
    histórico de quem já aponta para ele continua intacto.
    """
    # UM RISCO QUE ALGUM TEMA USA, e não qualquer um: o que está sob teste é o
    # enquadramento sobreviver ao aposentamento, e um risco sem tema não mediria
    # isso.
    alvo = sessao.execute(
        text("select risco_id from tema where risco_id is not null limit 1")
    ).scalar_one()
    antes = sessao.execute(
        text("select count(*) from tema where risco_id = :i"), {"i": alvo}
    ).scalar_one()
    assert antes >= 1

    sessao.execute(
        text("update risco_reputacional set ativo = false where id = :i"), {"i": alvo}
    )
    sessao.flush()

    dicionarios = listar_dicionarios(sessao)
    ativos = {r["id"] for r in dicionarios["riscos_reputacionais"]}
    inativos = {r["id"] for r in dicionarios["riscos_inativos"]}

    assert alvo not in ativos, "aposentado não pode ser oferecido no formulário"
    # E APARECE NA OUTRA LISTA, que é o que permite a edição resolver cluster e
    # severidade de um enquadramento antigo. Sem isto a tela abriria o seletor
    # vazio para o assunto preso ao risco aposentado — e salvar dali apagaria o
    # enquadramento. Achado de revisão de 08/10/2026, a mesma forma de
    # `temas_inativos`.
    assert alvo in inativos
    assert not (ativos & inativos), "um risco não pode estar nas duas listas"
    for r in dicionarios["riscos_inativos"]:
        assert {"id", "nome", "cluster", "severidade"} <= set(r)
        assert "ativo" not in r

    # O ENQUADRAMENTO NÃO SE MEXE: aposentar o risco não desclassifica o que já
    # foi classificado com ele.
    depois = sessao.execute(
        text("select count(*) from tema where risco_id = :i"), {"i": alvo}
    ).scalar_one()
    assert depois == antes
