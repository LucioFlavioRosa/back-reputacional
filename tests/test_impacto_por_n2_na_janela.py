"""Os temas estrategicos (N2) que mais empurraram a nota numa janela de dias.

O QUE ESTE ARQUIVO PROTEGE:

1. que a janela tenha os dias PEDIDOS e nas duas pontas — `ate - 15` daria
   dezesseis dias, e um erro de um dia aqui muda silenciosamente quais menções
   entram na conta;
2. que o DENOMINADOR seja o do mês, não o da janela. É o que faz "−2,3 pt" querer
   dizer pontos DA NOTA DAQUELE MÊS; um denominador local daria a cada janela o
   seu próprio 100%, cada pilar pareceria enorme e nenhum comporia o todo;
3. que a conta seja a MESMA da nota oficial — mesma régua, mesmas fórmulas de
   peso, mesmas fontes ligadas. Uma conta própria aqui faria esta tela discordar
   da tela do Score sem nada explicando;
4. que o que fica FORA seja contado e dito: menção sem N1 e menção sem `data`.
   São as duas formas de uma menção existir, pesar no índice e não aparecer aqui;
5. que a ordem seja por impacto e que o quadro curto diga o tamanho real.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.banco import repositorio_score
from app.banco.tabelas_catalogo import MacroTema
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.casos_de_uso import impacto_por_n2_na_janela
from app.dominio.erros import RegraViolada
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: O dia clicado nos testes, e o mês dele.
CLICADO = date(2026, 5, 20)
MES = date(2026, 5, 1)


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


@pytest.fixture
def clipei(sessao: Session) -> ScoreFonte:
    """A fonte da lente de imprensa — ela tem uma só."""
    return sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()


@pytest.fixture
def temas(sessao: Session) -> dict[str, int]:
    """Os TEMAS ESTRATÉGICOS (N2) do cadastro, por nome.

    ERA O N1, e a troca foi pedida depois de ver no ar: sete pilares num quadro
    de cinco linhas quase não escolhem nada, e um pilar com muita matéria
    positiva esconde o bolsão negativo que mora dentro dele. São 41 N2.
    """
    return {m.nome: m.id for m in sessao.scalars(select(MacroTema)).all()}


#: O denominador do mês, em menções. Ver `mes_com_base`.
BASE_DO_MES = 10


@pytest.fixture
def mes_com_base(sessao: Session, clipei: ScoreFonte) -> float:
    """O DENOMINADOR do mês, semeado onde a produção o grava.

    ISTO ME ENSINOU COMO O SISTEMA É, e o teste falhou primeiro por ignorá-lo: o
    denominador sai de `score_mes_fonte` — o agregado que a ingestão grava —, e
    não de `mencao`. O numerador desta leitura sai de `mencao`, porque aquele
    agregado não tem grão de dia nem de pilar.

    OS DOIS LADOS VÊM DE ORIGENS DIFERENTES, e isso NÃO é defeito meu: é
    exatamente a relação que `impacto_do_recorte` já usa há tempo (numerador por
    `somas_da_lente_filtradas`, sobre `mencao`; denominador por
    `denominador_do_mes`, sobre o agregado). A ingestão grava os dois no mesmo
    passo, então em produção eles descrevem o mesmo conjunto.

    SEM ESTA FIXTURE O MÊS NÃO TEM BASE, `ler` devolve listas vazias com
    `mes_sem_base`, e um teste que afirme "o pilar X não aparece" passa VAZIO —
    por nada ter aparecido. Foi o que aconteceu com
    `test_a_mencao_FORA_da_janela_nao_entra_no_numerador` na primeira execução.
    """
    sessao.add(
        ScoreMesFonte(
            fonte_id=clipei.id,
            mes=MES,
            sentimento="pos",
            tier="",
            mencoes=BASE_DO_MES,
            soma_log=BASE_DO_MES,
            soma_engajamento=0,
            soma_cargo=0,
        )
    )
    sessao.flush()
    _, total = repositorio_score.denominador_do_mes(
        sessao, clipei.lente_id, MES, repositorio_score.calibracao_vigente(sessao)
    )
    assert total == BASE_DO_MES, f"a régua do banco de teste mudou a base: {total}"
    return total


def _mencao(
    sessao: Session,
    clipei: ScoreFonte,
    *,
    sentimento: str,
    n2: int | None,
    dia: date | None,
    mes: date = MES,
    tier: str | None = None,
):
    """Uma menção da imprensa, no grão que a conta do índice lê.

    SEM ENGAJAMENTO E SEM TIER por padrão: é o caso da régua de contagem, em que
    cada menção vale 1 — o cenário em que a conta à mão dos testes fecha sem
    depender da régua do banco de teste.
    """
    sessao.add(
        Mencao(
            fonte_id=clipei.id,
            mes=mes,
            data=dia,
            sentimento=sentimento,
            tier=tier,
            macro_tema_id=n2,
        )
    )
    sessao.flush()


# -- a janela ------------------------------------------------------------------


def test_a_janela_tem_os_dias_pedidos_nas_DUAS_pontas(sessao, clipei):
    """`ate - 15` daria DEZESSEIS dias. Quinze dias contados, de 06/05 a 20/05."""
    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.ate == CLICADO
    assert lida.de == date(2026, 5, 6)
    assert (lida.ate - lida.de).days == 14  # 15 dias CONTADOS


def test_a_janela_de_um_dia_e_o_proprio_dia(sessao, clipei):
    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=1)

    assert lida.de == CLICADO
    assert lida.ate == CLICADO


def test_janela_de_zero_dia_e_recusada(sessao, clipei):
    with pytest.raises(RegraViolada):
        impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=0)


def test_o_mes_da_regua_e_o_do_dia_CLICADO(sessao, clipei):
    """A janela pode atravessar a virada; a régua é a do mês em que ele clicou.

    Decisão dele, registrada: "15 dias de verdade, com o mês do clique como
    régua". O que isso custa está dito na tela; o que não custa é a ordem — todos
    os temas dividem pelo mesmo denominador.
    """
    lida = impacto_por_n2_na_janela.ler(sessao, ate=date(2026, 5, 3), dias=15)

    assert lida.de == date(2026, 4, 19)  # atravessa a virada
    assert lida.mes == date(2026, 5, 1)  # e a régua é de MAIO


# -- a conta -------------------------------------------------------------------


def test_o_impacto_usa_o_denominador_do_MES_e_nao_o_da_janela(
    sessao, clipei, temas, mes_com_base
):
    """A asserção central do arquivo, com a conta à mão.

    Cenário: na janela, UMA menção positiva de um pilar. No mês, dez menções
    positivas no total (a da janela e nove fora dela).

    Com o denominador do MÊS: impacto = 50 × (1 − 0) ÷ 10 = 5,0 pontos.
    Com um denominador da JANELA: 50 × 1 ÷ 1 = 50 pontos — a menção única
    pareceria mover a nota em cinquenta pontos.
    """
    governanca = next(iter(temas))
    _mencao(sessao, clipei, sentimento="pos", n2=temas[governanca], dia=CLICADO)
    for _ in range(9):
        _mencao(
            sessao, clipei, sentimento="pos", n2=temas[governanca], dia=date(2026, 5, 1)
        )

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    total_do_mes = mes_com_base
    assert lida.positivos, "o tema da janela tem de aparecer"
    assert lida.positivos[0].n2 == governanca
    assert lida.positivos[0].impacto == pytest.approx(50 * 1 / total_do_mes)
    #: E NÃO 50: é o que um denominador local daria.
    assert lida.positivos[0].impacto < 50


def test_a_mencao_FORA_da_janela_nao_entra_no_numerador(sessao, clipei, temas, mes_com_base):
    governanca = next(iter(temas))
    #: um dia antes do começo da janela de 15 dias que termina em 20/05
    _mencao(sessao, clipei, sentimento="neg", n2=temas[governanca], dia=date(2026, 5, 5))

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.negativos == []


def test_positivo_e_negativo_vao_para_quadros_SEPARADOS(sessao, clipei, temas, mes_com_base):
    nomes = list(temas)
    _mencao(sessao, clipei, sentimento="pos", n2=temas[nomes[0]], dia=CLICADO)
    _mencao(sessao, clipei, sentimento="neg", n2=temas[nomes[1]], dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert [p.n2 for p in lida.positivos] == [nomes[0]]
    assert [p.n2 for p in lida.negativos] == [nomes[1]]
    assert lida.positivos[0].impacto > 0
    assert lida.negativos[0].impacto < 0


def test_o_neutro_nao_impacta_e_nao_aparece_em_quadro_nenhum(sessao, clipei, temas, mes_com_base):
    """A fórmula é `positivo − negativo`: o neutro entra no DENOMINADOR do mês e
    não no numerador de lado nenhum. Um pilar só de neutras não impactou nada, e
    listá-lo com `0,0 pt` ocuparia uma das cinco linhas com um não-fato."""
    nomes = list(temas)
    _mencao(sessao, clipei, sentimento="neu", n2=temas[nomes[0]], dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.positivos == []
    assert lida.negativos == []


def test_a_ordem_e_por_IMPACTO_e_os_quadros_cortam_em_cinco(sessao, clipei, temas, mes_com_base):
    """Seis temas negativos, com volumes diferentes: o quadro mostra os cinco
    maiores em módulo, na ordem, e diz que existem seis."""
    nomes = list(temas)[:6]
    assert len(nomes) == 6, "o cadastro precisa de seis N2 para este teste"
    for quantas, nome in enumerate(nomes, start=1):
        for _ in range(quantas):
            _mencao(sessao, clipei, sentimento="neg", n2=temas[nome], dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert len(lida.negativos) == 5
    assert lida.total_negativos == 6
    #: o de seis menções é o mais negativo, e o de uma ficou fora
    assert lida.negativos[0].n2 == nomes[5]
    assert [p.n2 for p in lida.negativos] == list(reversed(nomes[1:]))
    assert all(
        lida.negativos[i].impacto <= lida.negativos[i + 1].impacto for i in range(4)
    )


def test_o_quadro_diz_o_tamanho_real_quando_tem_menos_de_cinco(
    sessao, clipei, temas, mes_com_base
):
    """Decisão dele: "mostra os que houver e diz o total"."""
    nomes = list(temas)
    for nome in nomes[:2]:
        _mencao(sessao, clipei, sentimento="pos", n2=temas[nome], dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert len(lida.positivos) == 2
    assert lida.total_positivos == 2


# -- o que fica de fora, e é dito ----------------------------------------------


def test_a_mencao_SEM_N1_e_contada_e_nao_entra_em_pilar_nenhum(
    sessao, clipei, temas, mes_com_base
):
    """Ela existe e pesa no índice, mas não pertence a pilar nenhum — somá-la a
    um seria inventar vínculo, e omiti-la faria a soma dos temas não fechar com
    o impacto do período."""
    governanca = next(iter(temas))
    _mencao(sessao, clipei, sentimento="neg", n2=temas[governanca], dia=CLICADO)
    _mencao(sessao, clipei, sentimento="neg", n2=None, dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.sem_n2 == 1
    assert [p.n2 for p in lida.negativos] == [governanca]


def test_a_janela_LONGA_nao_perde_os_meses_do_MEIO(sessao, clipei, temas, mes_com_base):
    """ACHADO DE REVISÃO, e era perda silenciosa de dado.

    A consulta filtrava `Mencao.mes.in_({primeiro_dia(de), primeiro_dia(ate)})` —
    as duas PONTAS. Numa janela de noventa dias que vai de 20/02 a 20/05, isso
    são fevereiro e maio: março e abril inteiros eram descartados, e o impacto
    dos temas saía menor sem nada na tela dizendo que faltou metade da janela.

    A ROTA ACEITA `dias` ATÉ 90, então o caminho era alcançável de fato — não é
    cenário de laboratório.
    """
    governanca = next(iter(temas))
    #: uma menção em CADA mês que a janela de 90 dias atravessa
    for dia in (date(2026, 2, 25), date(2026, 3, 10), date(2026, 4, 10), date(2026, 5, 10)):
        _mencao(
            sessao,
            clipei,
            sentimento="neg",
            n2=temas[governanca],
            dia=dia,
            mes=date(dia.year, dia.month, 1),
        )

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=90)

    assert lida.de == date(2026, 2, 20)
    assert lida.negativos, "o tema da janela tem de aparecer"
    #: AS QUATRO MENÇÕES ENTRAM. Com as pontas só, seriam duas.
    assert lida.negativos[0].mencoes == 4


def test_dois_temas_do_MESMO_pilar_aparecem_em_lados_OPOSTOS(sessao, clipei, mes_com_base):
    """A RAZÃO DA TROCA DE N1 PARA N2, nas palavras dele: "o n1 esta quase tudo
    sendo positivo e estamos deixando passar alguma informação valiosa".

    O cenário exato: dois temas do MESMO pilar, um positivo e um negativo. No N1
    os dois se somavam numa linha só, o positivo vencia, e o pilar inteiro
    aparecia no quadro de cima — o bolsão negativo ficava invisível. No N2 cada
    um vai para o seu lado.

    O PILAR VAI COMO CONTEXTO em cada linha, e é o mesmo nos dois: é o que
    permite ler "estes dois temas são do mesmo pilar, e um derruba".
    """
    irmaos = sessao.scalars(
        select(MacroTema).order_by(MacroTema.bloco_tema_id, MacroTema.id)
    ).all()
    pai = irmaos[0].bloco_tema_id
    do_mesmo_pai = [m for m in irmaos if m.bloco_tema_id == pai][:2]
    assert len(do_mesmo_pai) == 2, "o cadastro precisa de dois N2 sob o mesmo N1"

    #: o positivo com MAIS volume, que é o que o N1 deixava vencer
    for _ in range(3):
        _mencao(sessao, clipei, sentimento="pos", n2=do_mesmo_pai[0].id, dia=CLICADO)
    _mencao(sessao, clipei, sentimento="neg", n2=do_mesmo_pai[1].id, dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert [p.n2 for p in lida.positivos] == [do_mesmo_pai[0].nome]
    assert [p.n2 for p in lida.negativos] == [do_mesmo_pai[1].nome]
    #: O PILAR É O MESMO NOS DOIS, e vem preenchido.
    assert lida.positivos[0].n1 is not None
    assert lida.positivos[0].n1 == lida.negativos[0].n1


def test_o_mes_SEM_BASE_diz_isso_em_vez_de_dizer_zero(sessao, clipei, temas):
    """SEM A FIXTURE `mes_com_base`, de propósito: é o mês que não tem
    denominador.

    "NENHUM PILAR IMPACTOU" E "NÃO HÁ COMO MEDIR" SÃO COISAS DIFERENTES, e os
    dois quadros vazios parecem iguais. Sem denominador não há pergunta a
    responder — e a menção da janela existe, o que torna "nada aqui" uma
    afirmação falsa. É o estado que `impacto_do_recorte` já trata devolvendo
    zero; aqui ele precisa de nome, porque a tela tem de dizer outra frase.
    """
    governanca = next(iter(temas))
    _mencao(sessao, clipei, sentimento="neg", n2=temas[governanca], dia=CLICADO)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.mes_sem_base is True
    assert lida.positivos == []
    assert lida.negativos == []
    #: E A JANELA CONTINUA DITA, para a tela não precisar adivinhar o que pediu.
    assert lida.de == date(2026, 5, 6)
    assert lida.ate == CLICADO


def test_a_mencao_SEM_DATA_fica_fora_da_janela_e_e_contada(sessao, clipei, temas, mes_com_base):
    """`mencao.data` é opcional: a menção pertence ao MÊS e não a um dia, então
    janela nenhuma a alcança. Sem este número, a janela parece ter lido tudo."""
    governanca = next(iter(temas))
    _mencao(sessao, clipei, sentimento="neg", n2=temas[governanca], dia=None)

    lida = impacto_por_n2_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.sem_data >= 1
    assert lida.negativos == []


def test_o_sem_data_conta_TODOS_os_meses_da_janela(sessao, clipei, temas, mes_com_base):
    """ACHADO DE REVISÃO: o número contava só o mês da ponta.

    Numa janela que atravessa a virada, as menções sem data do mês ANTERIOR
    também ficam fora dela — e eram invisíveis. A frase na tela diz "menções do
    mês sem data", e com a janela atravessando há dois meses: contar um só fazia
    o número mentir por omissão, que é o defeito que este campo existe para
    evitar.
    """
    _mencao(sessao, clipei, sentimento="neg", n2=None, dia=None, mes=date(2026, 4, 1))
    _mencao(sessao, clipei, sentimento="neg", n2=None, dia=None, mes=date(2026, 5, 1))

    #: janela que atravessa a virada: de 19/04 a 03/05
    lida = impacto_por_n2_na_janela.ler(sessao, ate=date(2026, 5, 3), dias=15)

    assert lida.de == date(2026, 4, 19)
    assert lida.sem_data == 2
