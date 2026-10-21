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
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.casos_de_uso import impacto_na_janela
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

    O PILAR VEM DO TEMA, SOZINHO, e isto é conserto de uma infidelidade do
    auxiliar: a produção grava os DOIS níveis quando resolve o tema (o resolvedor
    devolve `Niveis(n1_id=…, n2_id=…)` e a ingestão escreve os dois), e este
    auxiliar escrevia só o tema. Com isso, toda menção dos testes era invisível
    no nível do PILAR — e o teste da chave falhou exatamente nisso, apontando o
    dedo para a fixture em vez de para o código.

    DERIVAR AQUI, em vez de pedir os dois a cada chamada, é o que garante que o
    próximo teste também seja fiel sem ninguém se lembrar da regra.
    """
    pai = None
    if n2 is not None:
        pai = sessao.scalars(select(MacroTema).where(MacroTema.id == n2)).one().bloco_tema_id
    sessao.add(
        Mencao(
            fonte_id=clipei.id,
            mes=mes,
            data=dia,
            sentimento=sentimento,
            tier=tier,
            macro_tema_id=n2,
            bloco_tema_id=pai,
        )
    )
    sessao.flush()


# -- a janela ------------------------------------------------------------------


def test_a_janela_tem_os_dias_pedidos_nas_DUAS_pontas(sessao, clipei):
    """`ate - 15` daria DEZESSEIS dias. Quinze dias contados, de 06/05 a 20/05."""
    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.ate == CLICADO
    assert lida.de == date(2026, 5, 6)
    assert (lida.ate - lida.de).days == 14  # 15 dias CONTADOS


def test_a_janela_de_um_dia_e_o_proprio_dia(sessao, clipei):
    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=1)

    assert lida.de == CLICADO
    assert lida.ate == CLICADO


def test_janela_de_zero_dia_e_recusada(sessao, clipei):
    with pytest.raises(RegraViolada):
        impacto_na_janela.ler(sessao, ate=CLICADO, dias=0)


def test_o_mes_da_regua_e_o_do_dia_CLICADO(sessao, clipei):
    """A janela pode atravessar a virada; a régua é a do mês em que ele clicou.

    Decisão dele, registrada: "15 dias de verdade, com o mês do clique como
    régua". O que isso custa está dito na tela; o que não custa é a ordem — todos
    os temas dividem pelo mesmo denominador.
    """
    lida = impacto_na_janela.ler(sessao, ate=date(2026, 5, 3), dias=15)

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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    total_do_mes = mes_com_base
    assert lida.positivos, "o tema da janela tem de aparecer"
    assert lida.positivos[0].rotulo == governanca
    assert lida.positivos[0].impacto == pytest.approx(50 * 1 / total_do_mes)
    #: E NÃO 50: é o que um denominador local daria.
    assert lida.positivos[0].impacto < 50


def test_a_mencao_FORA_da_janela_nao_entra_no_numerador(sessao, clipei, temas, mes_com_base):
    governanca = next(iter(temas))
    #: um dia antes do começo da janela de 15 dias que termina em 20/05
    _mencao(sessao, clipei, sentimento="neg", n2=temas[governanca], dia=date(2026, 5, 5))

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.negativos == []


def test_positivo_e_negativo_vao_para_quadros_SEPARADOS(sessao, clipei, temas, mes_com_base):
    nomes = list(temas)
    _mencao(sessao, clipei, sentimento="pos", n2=temas[nomes[0]], dia=CLICADO)
    _mencao(sessao, clipei, sentimento="neg", n2=temas[nomes[1]], dia=CLICADO)

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert [p.rotulo for p in lida.positivos] == [nomes[0]]
    assert [p.rotulo for p in lida.negativos] == [nomes[1]]
    assert lida.positivos[0].impacto > 0
    assert lida.negativos[0].impacto < 0


def test_o_neutro_nao_impacta_e_nao_aparece_em_quadro_nenhum(sessao, clipei, temas, mes_com_base):
    """A fórmula é `positivo − negativo`: o neutro entra no DENOMINADOR do mês e
    não no numerador de lado nenhum. Um pilar só de neutras não impactou nada, e
    listá-lo com `0,0 pt` ocuparia uma das cinco linhas com um não-fato."""
    nomes = list(temas)
    _mencao(sessao, clipei, sentimento="neu", n2=temas[nomes[0]], dia=CLICADO)

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert len(lida.negativos) == 5
    assert lida.total_negativos == 6
    #: o de seis menções é o mais negativo, e o de uma ficou fora
    assert lida.negativos[0].rotulo == nomes[5]
    assert [p.rotulo for p in lida.negativos] == list(reversed(nomes[1:]))
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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.sem_grupo == 1
    assert [p.rotulo for p in lida.negativos] == [governanca]


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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=90)

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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert [p.rotulo for p in lida.positivos] == [do_mesmo_pai[0].nome]
    assert [p.rotulo for p in lida.negativos] == [do_mesmo_pai[1].nome]
    #: O PILAR É O MESMO NOS DOIS, e vem preenchido.
    assert lida.positivos[0].contexto is not None
    assert lida.positivos[0].contexto == lida.negativos[0].contexto


def test_dois_temas_de_MESMO_NOME_sob_pais_diferentes_NAO_se_fundem(
    sessao, clipei, mes_com_base
):
    """ACHADO DE REVISÃO: o agrupamento era pelo NOME do tema.

    Hoje o cadastro tem 41 temas e 41 nomes distintos, então nada colide — mas
    `macro_tema.nome` NÃO É ÚNICO no schema (só `codigo` é). A unicidade era um
    fato do dado, não uma garantia, e o dia em que alguém cadastrasse "Tarifa"
    sob dois pilares os dois impactos se somariam numa linha só, com o pai do
    último que passasse na consulta.

    A CHAVE PASSOU A SER O `id`, que é o que a tabela garante. O nome continua
    sendo o rótulo, e dois temas homônimos aparecem como duas linhas — que é o
    que eles são.
    """
    pais = sessao.scalars(select(BlocoTema).order_by(BlocoTema.id)).all()[:2]
    assert len(pais) == 2, "o cadastro precisa de dois N1"
    homonimos = []
    for indice, pai in enumerate(pais):
        tema = MacroTema(
            nome="Tema Homônimo de Teste",
            bloco_tema_id=pai.id,
            codigo=f"homonimo-de-teste-{indice}",
            ordem=90 + indice,
        )
        sessao.add(tema)
        homonimos.append(tema)
    sessao.flush()

    #: um NEGATIVO em cada, com volumes diferentes para a ordem ser previsível
    _mencao(sessao, clipei, sentimento="neg", n2=homonimos[0].id, dia=CLICADO)
    for _ in range(2):
        _mencao(sessao, clipei, sentimento="neg", n2=homonimos[1].id, dia=CLICADO)

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    homonimos_na_saida = [p for p in lida.negativos if p.rotulo == "Tema Homônimo de Teste"]
    #: DUAS LINHAS, e não uma somada.
    assert len(homonimos_na_saida) == 2
    assert {p.mencoes for p in homonimos_na_saida} == {1, 2}
    #: E CADA UMA COM O SEU PAI, que é a informação que a fusão destruía.
    assert {p.contexto for p in homonimos_na_saida} == {pais[0].nome, pais[1].nome}
    #: AS CHAVES SÃO DISTINTAS, para a tela poder desenhar as duas.
    assert homonimos_na_saida[0].id != homonimos_na_saida[1].id


def test_a_mencao_com_N1_E_SEM_N2_e_o_caso_REAL_que_fica_de_fora(
    sessao, clipei, temas, mes_com_base
):
    """O CASO QUE A TROCA DE N1 PARA N2 CRIOU, e que o teste de antes não via.

    O resolvedor tem seis caminhos, e o da Clipei — pelo `atributo` — devolve
    `Niveis(n1_id=achado)`: N1 preenchido, N2 e N3 NULOS. A migration 0098 mede
    72.590 menções da Clipei nesse estado, e a Clipei é a única fonte da lente
    de imprensa.

    O TESTE ANTERIOR ZERAVA OS DOIS NÍVEIS, e por isso não reproduzia nada: ele
    provava que menção sem taxonomia alguma fica fora, que é um caso raro. O
    caso real — e volumoso — é ter pilar e não ter tema, e é ele que precisa
    aparecer no contador que a tela mostra.
    """
    pai = sessao.scalars(select(BlocoTema).order_by(BlocoTema.id)).first()
    com_tema = next(iter(temas))
    _mencao(sessao, clipei, sentimento="neg", n2=temas[com_tema], dia=CLICADO)
    #: a menção da Clipei resolvida pelo `atributo`: N1 sim, N2 não
    sessao.add(
        Mencao(
            fonte_id=clipei.id,
            mes=MES,
            data=CLICADO,
            sentimento="neg",
            bloco_tema_id=pai.id,
            macro_tema_id=None,
        )
    )
    sessao.flush()

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert lida.sem_grupo == 1
    assert [p.rotulo for p in lida.negativos] == [com_tema]


def test_o_EMPATE_nao_muda_de_ordem_entre_chamadas(sessao, clipei, temas, mes_com_base):
    """ACHADO DE REVISÃO: a ordenação usava só o impacto.

    Dois temas com o mesmo impacto ficavam na ordem que o banco devolvesse — e
    com cinco linhas no quadro, o QUINTO item podia trocar entre duas aberturas
    da mesma janela, sobre o mesmo dado. Quem está lendo não tem como saber que
    a diferença é arbitrária.
    """
    nomes = sorted(temas)[:3]
    for nome in nomes:
        _mencao(sessao, clipei, sentimento="neg", n2=temas[nome], dia=CLICADO)

    primeira = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)
    segunda = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

    assert [p.rotulo for p in primeira.negativos] == [p.rotulo for p in segunda.negativos]
    #: EMPATADOS, A ORDEM É A DO NOME — previsível e explicável.
    assert [p.rotulo for p in primeira.negativos] == nomes


def test_O_PILAR_ALCANCA_O_QUE_O_TEMA_NAO_ALCANCA(sessao, clipei, temas, mes_com_base):
    """A RAZÃO DE A CHAVE EXISTIR, no mesmo dado e numa asserção só.

    A menção resolvida pelo `atributo` (o caminho da Clipei) tem PILAR e não tem
    TEMA — e a migration 0098 mede 72.590 nesse estado. No nível do tema ela cai
    no `sem_grupo`; no nível do pilar ela é uma linha do quadro.

    É ISSO QUE NENHUM DOS DOIS NÍVEIS RESOLVE SOZINHO: escolher o tema esconde
    essa menção, escolher o pilar junta tudo num grupo grosso. A chave deixa a
    pessoa ver as duas leituras do MESMO recorte — e o contraste entre os dois
    `sem_grupo` é a medida honesta do que cada nível custa.
    """
    pai = sessao.scalars(select(BlocoTema).order_by(BlocoTema.id)).first()
    com_tema = next(iter(temas))
    #: uma COM tema (e portanto com pilar, derivado), e uma só com pilar
    _mencao(sessao, clipei, sentimento="neg", n2=temas[com_tema], dia=CLICADO)
    sessao.add(
        Mencao(
            fonte_id=clipei.id,
            mes=MES,
            data=CLICADO,
            sentimento="neg",
            bloco_tema_id=pai.id,
            macro_tema_id=None,
        )
    )
    sessao.flush()

    no_tema = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel="n2")
    no_pilar = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel="n1")

    #: NO TEMA: uma linha, e a outra menção fora da conta.
    assert [p.rotulo for p in no_tema.negativos] == [com_tema]
    assert no_tema.sem_grupo == 1
    assert no_tema.nivel == "n2"

    #: NO PILAR: a menção que estava fora entra, e NADA fica de fora.
    assert no_pilar.sem_grupo == 0
    assert no_pilar.nivel == "n1"
    assert pai.nome in [p.rotulo for p in no_pilar.negativos]

    #: E O PILAR NÃO TEM CONTEXTO, porque ele é o topo da árvore.
    assert all(p.contexto is None for p in no_pilar.negativos)
    #: o tema, sim.
    assert no_tema.negativos[0].contexto is not None


def test_o_RECORTE_do_modal_e_o_do_quadro_na_lente_DA_IMPRENSA(
    sessao, clipei, temas, mes_com_base
):
    """O recorte de data, grupo e calibração, medido contra a fonte do número.

    O QUADRO conta somando `linha.mencoes` por fonte ligada, aqui dentro; O MODAL
    conta `count(*)` no repositório, com os mesmos predicados. Os dois números
    ficam LADO A LADO na tela — a contagem na linha, o total no cabeçalho do que
    ela abre — e divergir no RECORTE é afirmar duas contagens do mesmo conjunto
    sem dizer qual vale. Foi o defeito da 0098: a barra do N2 contava 29.701 e o
    clique alcançava 30.932.

    A IGUALDADE DOS NÚMEROS CAIU EM 20/10/2026, e de propósito: o modal passou a
    listar as TRÊS lentes de clipping e o quadro continua medindo a Imprensa. O
    que este teste ainda prova — e é o que importava nele — é que, OLHANDO SÓ A
    IMPRENSA, os dois lados recortam igual. Ver
    `test_o_quadro_NAO_MUDA_quando_as_outras_lentes_entram`, que mede o resto.

    NOS DOIS NÍVEIS, COM A MENÇÃO SÓ-PILAR NO MEIO, que é o caso volumoso (72.590
    na Clipei) e o único em que os dois lados leem colunas diferentes: o quadro
    agrupa pelo nível pedido, e o modal filtra pela coluna dele.

    ESTE TESTE MORA AQUI, e não junto dos outros do modal, porque o quadro só
    existe com `mes_com_base`: sem a base o mês devolve listas vazias, e o teste
    passaria comparando dois nadas — a armadilha que esta fixture documenta.
    """
    pai = sessao.scalars(select(BlocoTema).order_by(BlocoTema.id)).first()
    com_tema = next(iter(temas))
    #: DUAS COM TEMA (e com pilar, derivado) e DUAS SÓ COM PILAR.
    for _ in range(2):
        _mencao(sessao, clipei, sentimento="neg", n2=temas[com_tema], dia=CLICADO)
        sessao.add(
            Mencao(
                fonte_id=clipei.id,
                mes=MES,
                data=CLICADO,
                sentimento="neg",
                bloco_tema_id=pai.id,
                macro_tema_id=None,
            )
        )
    #: E O QUE OS DOIS LADOS TÊM DE EXCLUIR: a de antes da janela e a sem data.
    _mencao(sessao, clipei, sentimento="neg", n2=temas[com_tema], dia=date(2026, 5, 1))
    _mencao(sessao, clipei, sentimento="neg", n2=temas[com_tema], dia=None)
    sessao.flush()

    for nivel, grupo_id in (("n1", pai.id), ("n2", temas[com_tema])):
        quadro = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel=nivel)
        no_quadro = [
            g for g in (*quadro.positivos, *quadro.negativos) if g.id == grupo_id
        ]
        assert no_quadro, f"o grupo pedido não apareceu no quadro do {nivel}"
        no_modal = impacto_na_janela.registros(
            sessao, ate=CLICADO, grupo=grupo_id, nivel=nivel
        )
        assert no_modal.total == no_quadro[0].mencoes, nivel
        assert len(no_modal.itens) == no_modal.total

    #: E OS DOIS NÍVEIS NÃO CONTAM O MESMO, que é o que prova que a menção
    #: só-pilar entrou num e não no outro — sem isto, dois zeros também passariam.
    assert impacto_na_janela.registros(
        sessao, ate=CLICADO, grupo=pai.id, nivel="n1"
    ).total == 4
    assert impacto_na_janela.registros(
        sessao, ate=CLICADO, grupo=temas[com_tema], nivel="n2"
    ).total == 2


def test_o_quadro_NAO_MUDA_quando_as_outras_lentes_entram(
    sessao, clipei, temas, mes_com_base
):
    """O outro lado da igualdade que caiu: o quadro continua medindo a Imprensa.

    O MODAL PASSOU A LISTAR TRÊS LENTES, e o risco imediato é o número do quadro
    ir atrás — bastaria o impacto ler as menções sem filtrar a lente para o
    gráfico começar a somar matéria recortada e a nota do mês mudar sozinha. Este
    teste mede exatamente isso: as mesmas menções, com e sem as outras duas
    lentes presentes no banco.

    A LISTA CRESCE, O QUADRO NÃO. É a divergência que a tela precisa explicar, e
    é por isso que o cabeçalho do modal deixou de repetir o número da linha.
    """
    com_tema = next(iter(temas))
    _mencao(sessao, clipei, sentimento="neg", n2=temas[com_tema], dia=CLICADO)

    antes = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel="n2")
    no_quadro_antes = [g for g in antes.negativos if g.id == temas[com_tema]]
    assert no_quadro_antes, "o grupo pedido não apareceu no quadro"

    #: AS OUTRAS DUAS LENTES, no mesmo dia e no mesmo tema — o pior caso para o
    #: quadro: tudo igual menos a fonte.
    for codigo in ("mercado", "institucional"):
        lente = sessao.scalars(select(Lente).where(Lente.codigo == codigo)).one()
        fonte = sessao.scalars(
            select(ScoreFonte)
            .where(ScoreFonte.lente_id == lente.id, ScoreFonte.ativo.is_(True))
            .order_by(ScoreFonte.ordem)
        ).first()
        assert fonte is not None, f"a lente {codigo} tinha de ter fonte ativa"
        _mencao(sessao, fonte, sentimento="neg", n2=temas[com_tema], dia=CLICADO)

    depois = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel="n2")
    no_quadro_depois = [g for g in depois.negativos if g.id == temas[com_tema]]

    #: O QUADRO, IDÊNTICO: contagem e impacto.
    assert no_quadro_depois[0].mencoes == no_quadro_antes[0].mencoes == 1
    assert no_quadro_depois[0].impacto == no_quadro_antes[0].impacto
    #: E A LISTA, COM AS TRÊS.
    no_modal = impacto_na_janela.registros(
        sessao, ate=CLICADO, grupo=temas[com_tema], nivel="n2"
    )
    assert no_modal.total == 3
    assert {i.lente for i in no_modal.itens} == {"imprensa", "mercado", "institucional"}


def test_o_nivel_DESCONHECIDO_e_recusado(sessao, clipei):
    """Um nível que não existe devolveria a janela do padrão em silêncio, e a
    tela afirmaria estar mostrando o que pediu."""
    with pytest.raises(RegraViolada):
        impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel="n4")


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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

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

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15)

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
    lida = impacto_na_janela.ler(sessao, ate=date(2026, 5, 3), dias=15)

    assert lida.de == date(2026, 4, 19)
    assert lida.sem_data == 2


def test_o_SUBTEMA_N3_agrupa_pelo_tema_da_mencao_com_o_N2_de_contexto(
    sessao, clipei, mes_com_base
):
    """O PEDIDO DE 21/10/2026: a aba Bonds e reputação lê os quadros no N3.

    O GRUPO É `mencao.tema_id`, e o CONTEXTO é o tema estratégico (N2) do
    cadastro do subtema — o mesmo molde do N2, que leva o pilar. A menção sem
    N3 (só com N2, o caso comum de hoje) fica fora da conta e é contada.
    E O MODAL dos registros conta o MESMO grupo pela MESMA coluna.
    """
    subtema = sessao.scalars(
        select(Tema).where(Tema.macro_tema_id.is_not(None)).order_by(Tema.id)
    ).first()
    assert subtema is not None, "o banco de teste não tem subtema com N2"
    pai = sessao.scalars(select(MacroTema).where(MacroTema.id == subtema.macro_tema_id)).one()
    for _ in range(2):
        sessao.add(
            Mencao(
                fonte_id=clipei.id,
                mes=MES,
                data=CLICADO,
                sentimento="neg",
                tema_id=subtema.id,
                macro_tema_id=pai.id,
                bloco_tema_id=pai.bloco_tema_id,
            )
        )
    #: só com N2, sem N3
    _mencao(sessao, clipei, sentimento="neg", n2=pai.id, dia=CLICADO)
    sessao.flush()

    lida = impacto_na_janela.ler(sessao, ate=CLICADO, dias=15, nivel="n3")

    assert lida.nivel == "n3"
    assert [g.rotulo for g in lida.negativos] == [subtema.nome]
    assert lida.negativos[0].contexto == pai.nome
    assert lida.negativos[0].mencoes == 2
    assert lida.sem_grupo == 1
    assert impacto_na_janela.registros(
        sessao, ate=CLICADO, grupo=subtema.id, nivel="n3"
    ).total == 2
