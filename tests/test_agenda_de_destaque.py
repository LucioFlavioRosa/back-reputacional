"""A agenda de destaque — a marca editorial, e como se acha ela depois (0090).

É A OUTRA BANDEIRA BOOLEANA DE `interacao`, e a razão deste arquivo existir
separado do `test_informacao_sensivel_por_pessoa` é que as duas são opostas no
que importa:

    `sensivel`  é ALCANCE. Entra em `filtros_sql.condicoes()` sempre, sem
                ninguém pedir, e tira a linha da Base, do KPI e da busca de
                quem não tem a camada. Marcar exige permissão.

    `destaque`  é RECORTE PEDIDO. Fica inerte até a tela filtrar por ela, não
                esconde nada de ninguém, e quem pode editar pode marcar.

Misturá-las num arquivo só convidaria a copiar a guarda de uma para a outra —
e uma marca editorial que vira permissão por acidente é exatamente o defeito
que ninguém procura, porque a tela continua funcionando.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.dominio.frentes import Frente
from app.dominio.identidade import Escopo
from app.dominio.interacao import Interacao
from app.dominio.recorte import Recorte
from app.esquemas.interacoes import InteracaoSaida

# -- o filtro: três estados, e o do meio é o que se erra -----------------------


def sql_das_condicoes(**recorte) -> str:
    """O `where` que `condicoes()` monta, como texto, para inspecionar."""
    from app.banco.filtros_sql import condicoes

    partes = condicoes(
        Recorte(**recorte),
        escopo=Escopo.total(),
        #: Irrelevante aqui, e passado explícito porque é obrigatório: este
        #: arquivo é sobre a outra bandeira.
        alcanca_sensivel=True,
    )
    return " ".join(
        str(p.compile(compile_kwargs={"literal_binds": True})) for p in partes
    )


def test_sem_pedido_a_marca_nao_filtra_nada():
    """O padrão é a base inteira, com destaques e comuns juntos.

    É a diferença de fundo em relação a `sensivel`: aquela condição entra sem
    ninguém pedir. Esta só entra quando alguém pede, e por isso a Base não
    muda para quem nunca abriu o filtro.
    """
    assert "interacao.destaque" not in sql_das_condicoes()


def test_so_as_de_destaque():
    assert "interacao.destaque IS true" in sql_das_condicoes(destaque=True)


def test_so_as_que_NAO_sao_de_destaque():
    """O ESTADO DO MEIO, e o único jeito de errar este filtro.

    `destaque=False` é pedido legítimo — "as agendas que ninguém apontou" — e
    `if recorte.destaque:` o trataria como "sem filtro": a tela pediria um
    subconjunto estreito e receberia a BASE INTEIRA, sem erro, sem log e com
    número de KPI batendo com a tabela, porque as duas metades estariam
    igualmente erradas.

    É por isso que `filtros_sql` testa `is not None`, e é por isso que este
    teste existe: ele é o que falha se alguém "simplificar" a condição.
    """
    assert "interacao.destaque IS false" in sql_das_condicoes(destaque=False)


def test_o_contador_de_filtros_conta_os_dois_lados():
    """O contador do botão "Filtros" conta `is not None`, não truthiness.

    Mesma armadilha do SQL, do outro lado da tela: com truthiness, filtrar
    por "as que não são de destaque" mostraria "0 filtros ativos" sobre uma
    lista recortada, e a pessoa leria o subconjunto achando que vê tudo.
    """
    assert Recorte().quantidade_de_filtros == 0
    assert Recorte(destaque=True).quantidade_de_filtros == 1
    assert Recorte(destaque=False).quantidade_de_filtros == 1


def test_a_marca_nao_e_alcance():
    """Nenhum caminho do Recorte liga a marca sozinho.

    Um `destaque=True` que entrasse por padrão esconderia as agendas comuns de
    todo mundo — e a tela pareceria funcionar, porque ainda viria conteúdo.
    """
    assert Recorte().destaque is None
    assert Recorte.construir().destaque is None


# -- o agregado e o que sai no payload -----------------------------------------


def nova(**ajustes) -> Interacao:
    padroes = dict(
        id=uuid4(),
        frente=Frente.IMPRENSA,
        data_interacao=date(2026, 5, 7),
        instituicao_id=uuid4(),
        uf="SP",
        status="confirmada",
        pauta="Audiência pública sobre o contrato",
    )
    return Interacao(**{**padroes, **ajustes})


def test_a_agenda_nasce_comum():
    """`False` por padrão: apontar uma agenda é um ato, não o estado inicial."""
    assert nova().destaque is False


def test_a_marca_sai_no_payload():
    """A tela precisa dela para marcar a linha e para mostrar que o gesto pegou."""
    assert InteracaoSaida.de_dominio(nova(destaque=True)).destaque is True
    assert InteracaoSaida.de_dominio(nova()).destaque is False


def test_a_marca_e_editavel():
    """`alterar` aceita o campo — é o que o `PATCH` usa.

    Se `destaque` entrasse na lista de imutáveis de `_campos_editaveis`, a
    edição levantaria "campo inexistente ou não editável" e a tela mostraria
    erro ao salvar uma agenda que ela mesma deixou marcar.
    """
    agenda = nova()
    agenda.alterar(destaque=True)
    assert agenda.destaque is True


# -- a planilha ----------------------------------------------------------------


def test_a_coluna_existe_nos_DOIS_modelos():
    """Oferecê-la num modelo e não no outro faria a MESMA agenda poder ou não
    ser apontada dependendo do arquivo que a pessoa baixou."""
    from app.dominio.importacao_de_agendas import MODELOS

    assert "Agenda de destaque?" in MODELOS["completo"]
    assert "Agenda de destaque?" in MODELOS["simplificado"]


def test_a_coluna_fica_na_secao_5_logo_depois_do_local():
    """A ordem da planilha é a ordem do formulário, e o dono pôs a marca na
    seção 5 — quem preenche conhece a tela, e procurar coluna é o custo."""
    from app.dominio.importacao_de_agendas import MODELOS

    for modelo in ("completo", "simplificado"):
        colunas = list(MODELOS[modelo])
        assert colunas[colunas.index("Local") + 1] == "Agenda de destaque?", modelo


def test_a_marca_tem_procedencia_declarada():
    """`DESTINO_DO_CAMPO` é o que a tela de conferência usa para dizer de onde
    cada valor veio. Campo sem entrada ali aparece sem explicação."""
    from app.dominio.importacao_de_agendas import DESTINO_DO_CAMPO

    assert DESTINO_DO_CAMPO["destaque"] == "da planilha"