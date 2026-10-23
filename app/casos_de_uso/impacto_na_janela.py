"""Que temas estrategicos (N2) mais empurraram a nota numa janela de dias.

A PERGUNTA, nas palavras de quem pediu: "quero poder clicar em alguma data seja
no gráfico ou no eixo, que você pega a data e subtrai 15 dias, pega esse recorte
de data e me traga dois quadros logo abaixo do gráfico, um quadro com os 5 N1 que
mais impactaram positivamente o score e 5 N1 que mais impactaram negativamente".

ERA N1 E PASSOU A SER N2, por pedido dele depois de ver no ar: "ao inves de ser
n1 pode aparece o n2, pois o n1 esta quase tudo sendo positivo e estamos deixando
passar alguma informacao valiosa". Sao SETE N1 contra QUARENTA E UM N2 no
cadastro: num quadro de cinco linhas, sete grupos quase nao escolhem nada, e um
pilar com muita materia positiva esconde o bolsao negativo que mora dentro dele.

O SCORE É MENSAL E A JANELA TEM QUINZE DIAS, e isso não é contradição — é o que
ele esclareceu: "seria simplesmente fazer um recorte do período que tem aquele
score". A nota do mês é a nota; a janela é um recorte das menções que a compõem.
Daí o denominador ser o DO MÊS (ver `impacto_do_recorte`): é o que faz "−2,3 pt"
querer dizer "dois vírgula três pontos DA NOTA DAQUELE MÊS", e não dois vírgula
três pontos de uma régua inventada para esses quinze dias.

A JANELA ATRAVESSA A VIRADA DO MÊS, por decisão dele: clicar em 10/09 lê de 26/08
a 10/09, e a régua é a de setembro — o mês em que ele clicou. O que isso custa
está dito na tela, e o que NÃO custa é a ordem: como todos os pilares dividem
pelo mesmo denominador, o ranking dos cinco é exato de qualquer forma. O
denominador só escala o número exibido.

ERA SÓ A LENTE DE IMPRENSA ("considere nesse momento somente dados da lente de
impressa"), e desde 21/10/2026 são as TRÊS DE CLIPPING, com o impacto medido em
pontos do SCORE GERAL: "o impacto deve ser em relação à nota geral, e daí por
isso tem que pegar nesse caso tanto registros que vêm de imprensa, mercado e
institucional".

AS DUAS MUDANÇAS SÃO UMA SÓ, e é o que torna o número conferível. Antes o
impacto era em pontos da NOTA DA IMPRENSA — a tela dizia isso, em resposta a uma
pergunta que ele já tinha feito ("esse desconto de pontos de cada pilar ou tema é
em relação à pontuação total? ou só da lente?"). Agora que o número é do índice,
o universo tem de ser o do índice: medir uma lente e chamar o resultado de
"impacto no score geral" omitiria as outras duas que também o movem.

A FÓRMULA É A DO PROJETO, por pedido explícito ("esse impacto deve levar em
consideração a fórmula de pesos que definimos no projeto"): cada lente contribui
com `pontos na nota dela × fatia dela no índice`, e a fatia sai de
`pesos_exatos`, que é o mesmo `Σ score×peso / Σ peso` do ISR — com lente sem dado
saindo do numerador E do denominador. A conta é POR LENTE e somada depois: as
menções das três num denominador só apagariam que uma matéria do Mercado e uma
da Imprensa não valem o mesmo no score geral.

O QUE ESTE NÚMERO É, COM PRECISÃO — e a ressalva é correção de revisão, porque
eu havia afirmado mais do que ele entrega. Ele é a contribuição no ÍNDICE
CONTÍNUO, antes dos arredondamentos: `calcular_indice` arredonda o score de cada
lente e depois o ISR, então a soma dos impactos NÃO fecha necessariamente com a
diferença do inteiro que a tela mostra. "Quanto este tema empurrou o índice" é
verdade; "exatamente quanto o ISR exibido mudou" seria forte demais.

E ELE COBRE AS TRÊS LENTES DE CLIPPING, não o índice inteiro: Sociedade e
Clientes pesam no ISR e ficam fora desta conta, por pedido. Por isso a tela diz
QUANTO do índice a soma representa — ver `fatia_das_lentes`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco import repositorio_score
from app.banco.tabelas_score import Lente
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.score import Contagem, Tier, pesos_exatos, ponderar
from app.dominio.tema_do_mes import PONTOS_POR_NS

#: A lente desta leitura. Ver o cabeçalho do módulo.
LENTE = "imprensa"

#: AS LENTES QUE O MODAL DOS REGISTROS LISTA — pedido de 20/10/2026: "quero
#: adicionar os registros de mercado e institucional também".
#:
#: AS TRÊS DE CLIPPING, e não todas: são as que leem o export da Clipei
#: (inteiro ou recortado), então falam do mesmo universo de matéria e do mesmo
#: vocabulário de tema. Sociedade e Clientes leem OUTROS fornecedores (Bites,
#: Approach), com outro vocabulário — listá-las aqui misturaria universos no
#: mesmo modal.
#:
#: E O QUADRO MEDE AS MESMAS TRÊS desde 21/10/2026, quando o impacto virou ponto
#: do score geral — por um dia esta lista mostrou três lentes e o quadro media a
#: Imprensa, e era por isso que o cabeçalho do modal nomeava os dois números.
#: Hoje a lista é o universo da conta, e não um superconjunto dela.
LENTES_DOS_REGISTROS = ("imprensa", "mercado", "institucional")

#: Quantos dias a janela cobre, contados para trás a partir do dia clicado.
DIAS_DA_JANELA = 15

#: O NIVEL PADRAO E O TEMA, por pedido dele: o pilar estava "quase tudo sendo
#: positivo" e nao achava o problema. O pilar fica a um clique, pela chave.
NIVEL_PADRAO = repositorio_score.NIVEL_DO_TEMA
NIVEL_DO_PILAR = repositorio_score.NIVEL_DO_PILAR
NIVEL_DO_TEMA = repositorio_score.NIVEL_DO_TEMA

#: Quantos grupos cada quadro mostra.
QUANTOS_NO_QUADRO = 5


@dataclass(frozen=True, slots=True)
class ImpactoDoGrupo:
    #: A CHAVE e o id do cadastro -- o nome e rotulo. Ver TemaNaJanela.
    id: int
    #: O nome do grupo -- o pilar ou o tema, conforme o nivel pedido.
    rotulo: str
    #: O nivel de cima, como contexto: o pilar de um tema. None no nivel do
    #: pilar (ele e o topo) ou quando o cadastro nao resolve o pai.
    contexto: str | None
    #: Pontos na nota do mês: positivo empurra para cima, negativo para baixo.
    impacto: float
    mencoes: int


@dataclass(frozen=True, slots=True)
class ImpactoNaJanela:
    de: date
    ate: date
    #: O mês cuja régua e cujo denominador medem esta conta.
    mes: date
    #: A régua de engajamento vigente no mês — a tela a diz, porque ela muda o
    #: que "peso" significa.
    regua: str
    #: QUANTO POR CENTO DO ÍNDICE AS LENTES DESTA LEITURA PESARAM NO MÊS, sem
    #: arredondar e somando as que entraram. É o fator que converte o impacto
    #: para pontos do score geral, e a tela o diz: sem o número à vista, a conta
    #: não é conferível.
    #:
    #: ZERO QUANDO NENHUMA DELAS ENTROU no índice do mês. Aí não há impacto em
    #: ponto do índice para dizer, e a tela precisa dizer ISSO em vez de mostrar
    #: dois quadros vazios — é o que `mes_sem_base` sinaliza.
    fatia_das_lentes: float = 0.0
    #: AS LENTES QUE ENTRARAM NA SOMA — e não as três fixas: a lente sem dado no
    #: mês não contribui, e dizer que ela entrou faria a tela prometer um
    #: universo que a conta não cobriu.
    #:
    #: NA ORDEM PEDIDA, e antes era "na ordem do cadastro" — mudou com o filtro
    #: rápido (`_ler_lentes` devolve na ordem de `codigos`, que sem escolha é a
    #: de `LENTES_DOS_REGISTROS`). A tela imprime esta lista na linha da régua,
    #: então a ordem é visível; ninguém a lê por posição.
    lentes: tuple[str, ...] = ()
    positivos: list[ImpactoDoGrupo] = field(default_factory=list)
    negativos: list[ImpactoDoGrupo] = field(default_factory=list)
    #: Quantos temas com impacto existem de cada lado, para a tela poder dizer
    #: "3 de 3" em vez de fingir que são sempre cinco.
    total_positivos: int = 0
    total_negativos: int = 0
    #: As duas formas de uma menção ficar fora — ver `SomasNaJanela`.
    #: As mencoes da janela sem o nivel pedido.
    sem_grupo: int = 0
    #: O nivel que esta resposta descreve, ecoado como metrica na serie.
    nivel: str = NIVEL_PADRAO
    sem_data: int = 0
    #: Zero quando o mês não tem base: sem denominador não há pergunta a
    #: responder, e é diferente de "nenhum pilar impactou".
    mes_sem_base: bool = False


@dataclass
class _GrupoSomado:
    """O que um grupo acumulou ATRAVESSANDO as lentes.

    Mutável de propósito: é um acumulador de laço, não um valor que viaja.
    """

    rotulo: str
    contexto: str | None
    impacto: float = 0.0
    mencoes: int = 0


def _acumular(
    somado: dict[int, _GrupoSomado],
    somas: repositorio_score.SomasNaJanela,
    calibracao,
    regua: str,
    total_do_mes: float,
    fatia: float,
) -> None:
    """Soma a contribuição de UMA lente ao acumulado por grupo.

    A CONVERSÃO ACONTECE AQUI, dentro da lente, e é o ponto inteiro desta
    função: o grupo moveu a nota DESTA lente em `na_lente` pontos, e isso vale
    `na_lente × fatia / 100` pontos do índice, porque é com essa fatia que a
    lente pondera nele. É a mesma conta de `pontos_no_indice` em "Temas que
    pesaram" — duas contas diferentes para a mesma pergunta fariam duas telas
    discordarem.

    SOMAR ANTES DE CONVERTER SERIA O DEFEITO: as menções das três lentes num
    denominador só apagariam que uma matéria do Mercado e uma da Imprensa não
    valem o mesmo no score geral.
    """
    for id_do_grupo, por_fonte in somas.por_grupo.items():
        grupo = somas.grupos[id_do_grupo]
        #: AS FONTES DESLIGADAS NA CALIBRAÇÃO SAEM, como em toda leitura do
        #: índice: a nota não as conta, e contá-las aqui faria o impacto de um
        #: pilar incluir o que a nota ignorou.
        ligadas = [linhas for fonte, linhas in por_fonte.items() if calibracao.ligada(fonte)]
        if not ligadas:
            continue
        contagem = Contagem()
        mencoes = 0
        for linhas in ligadas:
            #: A MESMA RÉGUA DO DENOMINADOR DESTA LENTE, passada de fora: deixar
            #: `ponderar` escolher a dele mediria um pilar em menções contra um
            #: mês medido em curtidas — ver `composicao_da_lente`.
            contagem = contagem + ponderar(linhas, calibracao, regua)
            mencoes += sum(int(linha.mencoes) for linha in linhas)
        na_lente = PONTOS_POR_NS * (contagem.positivo - contagem.negativo) / total_do_mes
        acumulado = somado.setdefault(
            id_do_grupo, _GrupoSomado(rotulo=grupo.nome, contexto=grupo.contexto)
        )
        acumulado.impacto += na_lente * fatia / 100
        acumulado.mencoes += mencoes


def _regua_das_lentes(reguas: list[str]) -> str:
    """A régua que a tela diz, agora que a conta atravessa lentes.

    AS TRÊS LEEM O MESMO EXPORT DA CLIPEI, então na prática a régua é uma só e
    esta função devolve ela. Mas isso é propriedade do cadastro de hoje, não
    garantia: se uma lente passar a medir em engajamento e outra em menções,
    dizer só a primeira seria afirmar uma régua que não vale para a conta
    inteira. Aí a tela nomeia as duas, e quem lê sabe que está olhando uma soma
    de réguas diferentes.
    """
    distintas = sorted(set(reguas))
    if not distintas:
        return ""
    return " e ".join(distintas)


def _lentes_escolhidas(lentes: Sequence[str] | None) -> tuple[str, ...]:
    """As lentes pedidas, conferidas contra as três de clipping.

    VAZIO É "AS TRÊS", que é o quadro de sempre. Uma lente fora da lista é
    recusada em voz alta: devolver as três em silêncio faria a tela afirmar
    "só Mercado" sobre uma soma das três.
    """
    if not lentes:
        return tuple(LENTES_DOS_REGISTROS)
    desconhecidas = sorted(set(lentes) - set(LENTES_DOS_REGISTROS))
    if desconhecidas:
        raise RegraViolada(
            f"Lente fora do quadro: {', '.join(desconhecidas)}. "
            f"Aceitas: {', '.join(LENTES_DOS_REGISTROS)}."
        )
    return tuple(dict.fromkeys(lentes))


def _tier_escolhido(tier: str | None) -> str | None:
    """O tier pedido, conferido contra a escala da Clipei.

    POR SIMETRIA COM `nivel`, que já é conferido aqui — achado de revisão. A
    regex da rota protege quem chega por HTTP, mas estas funções são chamadas
    direto (testes, comandos, qualquer leitura futura), e `Mencao.tier == tier`
    com um valor que não existe na escala devolve ZERO EM SILÊNCIO: um quadro
    vazio tem a mesma cara de "nada impactou neste tier".

    `Tier.SEM` É RECUSADO DE PROPÓSITO: é o tier vazio das fontes que não têm
    tier (redes, canais próprios, CRM), e filtrar o quadro por ele pediria "as
    matérias de imprensa sem veículo com tier" — pergunta que a tela não faz.
    """
    if tier is None:
        return None
    aceitos = tuple(t.value for t in Tier if t is not Tier.SEM)
    if tier not in aceitos:
        raise RegraViolada(f"Tier desconhecido: {tier}. Aceitos: {', '.join(aceitos)}.")
    return tier


def _ler_lentes(
    sessao: Session, codigos: Sequence[str], escolhidas: bool
) -> list[Lente]:
    """As lentes do cadastro, na ordem pedida.

    SEM ESCOLHA, A IMPRENSA É O CHÃO e as outras duas podem faltar que a soma
    encurta — o comportamento de sempre do quadro e do modal. COM ESCOLHA, cada
    lente pedida tem de existir: "só Mercado" sem a lente Mercado no cadastro
    não pode virar um quadro vazio que parece resposta.
    """
    achadas = {
        lente.codigo: lente
        for lente in sessao.scalars(select(Lente).where(Lente.codigo.in_(codigos))).all()
    }
    exigidas = list(codigos) if escolhidas else [LENTE]
    faltando = [codigo for codigo in exigidas if codigo not in achadas]
    if faltando:
        raise NaoEncontrado(f"A lente {', '.join(faltando)} não está cadastrada.")
    return [achadas[codigo] for codigo in codigos if codigo in achadas]


def registros(
    sessao: Session,
    ate: date,
    grupo: int,
    dias: int = DIAS_DA_JANELA,
    nivel: str = NIVEL_PADRAO,
    pagina: int = 1,
    tamanho: int = 50,
    lentes: Sequence[str] | None = None,
    tier: str | None = None,
) -> repositorio_score.RegistrosDaJanela:
    """As menções que compõem UM grupo do quadro — o que abre ao clicar nele.

    O PEDIDO: "se eu clicar em alguma dessas opções quero que abra um modal com
    os registros do tema ou pilar, assim como fazemos nas lentes no KPI".

    A JANELA É CALCULADA AQUI, pelos mesmos `ate` e `dias` do quadro, e não vem
    pronta da tela: duas contas de data em dois lugares divergem na primeira vez
    que alguém mudar o tamanho da janela. A tela manda o que ela clicou (o dia e
    o grupo); quem sabe o que é uma janela é este módulo.

    O RECORTE DE DATA, GRUPO E CALIBRAÇÃO É O MESMO DO QUADRO — ver
    `registros_do_grupo_na_janela`, que explica por que a rota da Base das
    lentes não serve.

    AS TRÊS LENTES DE CLIPPING, E NÃO SÓ A IMPRENSA (pedido de 20/10/2026:
    "quero adicionar os registros de mercado e institucional também"). Cada
    linha diz de qual lente veio, porque a lente é decidida pelo VEÍCULO que
    publicou e a mesma matéria publicada por dois veículos cai em duas.

    E O QUADRO VOLTOU A MEDIR O MESMO UNIVERSO (21/10/2026): quando o impacto
    passou a ser em pontos do score geral, `ler` passou a somar as três lentes.
    Por um dia esta lista mostrou três lentes e o quadro media uma — foi por isso
    que o cabeçalho do modal passou a nomear os dois números. Agora os dois
    contam o mesmo recorte, e a igualdade que eu tinha desmontado volta a valer.
    """
    if dias < 1:
        raise RegraViolada("A janela precisa de pelo menos um dia.")
    if nivel not in repositorio_score.NIVEIS_DA_JANELA:
        raise RegraViolada(f"Nivel desconhecido: {nivel}.")

    escolhidas = _lentes_escolhidas(lentes)
    tier = _tier_escolhido(tier)
    lidas = _ler_lentes(sessao, escolhidas, bool(lentes))

    return repositorio_score.registros_do_grupo_na_janela(
        sessao,
        [lente.id for lente in lidas],
        de=ate - timedelta(days=dias - 1),
        ate=ate,
        grupo_id=grupo,
        calibracao=repositorio_score.calibracao_vigente(sessao),
        nivel=nivel,
        pagina=pagina,
        tamanho=tamanho,
        tier=tier,
    )


def ler(
    sessao: Session,
    ate: date,
    dias: int = DIAS_DA_JANELA,
    nivel: str = NIVEL_PADRAO,
    lentes: Sequence[str] | None = None,
    tier: str | None = None,
) -> ImpactoNaJanela:
    """Os temas que mais empurraram o ÍNDICE na janela que termina em `ate`.

    EM PONTOS DO SCORE GERAL, E SOMANDO AS TRÊS LENTES DE CLIPPING (pedido de
    21/10/2026): "o impacto deve ser em relação à nota geral, e daí por isso tem
    que pegar nesse caso tanto registros que vêm de imprensa, mercado e
    institucional".

    AS DUAS COISAS SÃO UMA SÓ, e é o que torna este número conferível: se o
    impacto é em ponto do índice, o universo tem de ser o do índice — medir só a
    Imprensa e chamar o resultado de "impacto no score geral" seria omitir as
    outras duas lentes que também o movem.

    A CONTA É POR LENTE E SOMADA DEPOIS, nunca com as menções das três num
    mesmo denominador: cada lente tem o denominador DELA (o volume ponderado do
    mês) e o PESO dela no índice. Uma matéria do Mercado e uma da Imprensa não
    valem o mesmo no score geral, e somá-las antes de converter apagaria
    exatamente essa diferença.

    O GRUPO É O MESMO NAS TRÊS porque a taxonomia é uma: "Tarifa" é o mesmo tema
    tenha a matéria vindo de onde vier. É isso que permite somar por grupo.

    E AGORA O QUADRO E O MODAL MEDEM O MESMO UNIVERSO: o modal dos registros já
    lista as três lentes desde 20/10/2026, e o quadro media uma. A igualdade que
    eu tinha desmontado volta a existir — ver `registros` e o cabeçalho do modal.
    """
    if dias < 1:
        raise RegraViolada("A janela precisa de pelo menos um dia.")
    if nivel not in repositorio_score.NIVEIS_DA_JANELA:
        raise RegraViolada(f"Nivel desconhecido: {nivel}.")

    #: AS LENTES ESCOLHIDAS NO FILTRO RÁPIDO (pedido de 22/10/2026: "olhar apenas
    #: notícias de Imprensa e Mercado, ou apenas Imprensa, ou apenas Mercado").
    #: Sem escolha, as três de sempre. A conta continua por lente e somada
    #: depois, cada uma com o seu denominador e o seu peso no índice.
    escolhidas = _lentes_escolhidas(lentes)
    tier = _tier_escolhido(tier)
    lentes_lidas = _ler_lentes(sessao, escolhidas, bool(lentes))

    #: INCLUSIVA NAS DUAS PONTAS, e `dias - 1` é o que faz "15 dias" serem quinze
    #: dias: de 10/09 menos 14 dá 27/08, e de 27/08 a 10/09 há exatamente quinze
    #: dias contados. `ate - 15` daria dezesseis.
    de = ate - timedelta(days=dias - 1)
    mes = repositorio_score.primeiro_dia(ate)
    calibracao = repositorio_score.calibracao_vigente(sessao)
    #: `indice_do_mes` mede as cinco lentes; `pesos_exatos` devolve a fração com
    #: que CADA UMA ponderou de fato, já descontando as que ficaram sem dado — a
    #: Imprensa pesa 30 de 85 num mês em que falta uma lente, e 30 de 100 noutro.
    #: Fixar os 30% do cadastro mentiria nos meses incompletos.
    fatias = pesos_exatos(repositorio_score.indice_do_mes(sessao, mes, calibracao))

    somado: dict[int, _GrupoSomado] = {}
    fatia_das_lentes = 0.0
    reguas: list[str] = []
    contaram: list[str] = []
    sem_grupo = 0
    sem_data = 0
    for lente in lentes_lidas:
        regua_da_lente, total_do_mes = repositorio_score.denominador_do_mes(
            sessao, lente.id, mes, calibracao
        )
        fatia = fatias.get(lente.codigo, 0.0)
        #: SEM DENOMINADOR OU FORA DO ÍNDICE, a lente não tem como contribuir em
        #: ponto do score geral — e multiplicar por zero esconderia que ela foi
        #: pulada. Ela sai da conta e da soma das fatias, que é o que a tela diz.
        #:
        #: A LENTE ESTIMADA CAI AQUI, e é LIMITE e não descuido — achado de
        #: revisão. `medir_lentes` dá score a quem tem `score_estimativa`, então
        #: ela pondera no índice (`fatia > 0`) sem ter `score_mes_fonte`
        #: (`total_do_mes == 0`). Não há como repartir o impacto dela por tema:
        #: aquele score é um NS de resumo semestral, sem nenhuma das dimensões
        #: do tema — é o que `somas_da_lente_filtradas` já diz ao deixá-la de
        #: fora de propósito. Inventar uma decomposição seria responder a
        #: pergunta errada com a aparência de ter acertado.
        #:
        #: O QUE A TELA DEVE ENTÃO: dizer quanto do índice a conta COBRE. É para
        #: isso que `fatia_das_lentes` existe e aparece na linha da régua — com
        #: 65%, quem lê sabe que não está vendo o índice inteiro decomposto.
        if not total_do_mes or not fatia:
            continue
        fatia_das_lentes += fatia
        reguas.append(regua_da_lente)
        contaram.append(lente.codigo)
        somas = repositorio_score.somas_por_nivel_na_janela(
            sessao, lente.id, de=de, ate=ate, nivel=nivel, tier=tier
        )
        sem_grupo += somas.sem_grupo
        sem_data += somas.sem_data
        _acumular(somado, somas, calibracao, regua_da_lente, total_do_mes, fatia)

    if not fatia_das_lentes:
        return ImpactoNaJanela(
            de=de,
            ate=ate,
            mes=mes,
            regua=_regua_das_lentes(reguas),
            sem_grupo=sem_grupo,
            nivel=nivel,
            sem_data=sem_data,
            mes_sem_base=True,
        )

    medidos = [
        ImpactoDoGrupo(
            id=id_do_grupo,
            rotulo=item.rotulo,
            contexto=item.contexto,
            impacto=item.impacto,
            mencoes=item.mencoes,
        )
        for id_do_grupo, item in somado.items()
        if item.impacto
    ]

    #: O DESEMPATE É PELO NOME, e é conserto de achado de revisão: a ordenação
    #: usava só o impacto, e dois temas empatados ficavam na ordem que o banco
    #: devolvesse. Com cinco linhas no quadro, o QUINTO item trocava entre duas
    #: aberturas da MESMA janela sobre o MESMO dado — e quem lê não tem como
    #: saber que a diferença é arbitrária.
    acima = sorted(
        [p for p in medidos if p.impacto > 0], key=lambda p: (-p.impacto, p.rotulo)
    )
    abaixo = sorted(
        [p for p in medidos if p.impacto < 0], key=lambda p: (p.impacto, p.rotulo)
    )

    return ImpactoNaJanela(
        de=de,
        ate=ate,
        mes=mes,
        regua=_regua_das_lentes(reguas),
        fatia_das_lentes=fatia_das_lentes,
        lentes=tuple(contaram),
        positivos=acima[:QUANTOS_NO_QUADRO],
        negativos=abaixo[:QUANTOS_NO_QUADRO],
        total_positivos=len(acima),
        total_negativos=len(abaixo),
        sem_grupo=sem_grupo,
        nivel=nivel,
        #: O ACUMULADO DAS LENTES, e não `somas.sem_data` — achado de revisão, e
        #: era defeito meu de verdade: eu somava no laço e devolvia o valor da
        #: ÚLTIMA lente que não foi pulada. Com uma menção sem data na Imprensa
        #: e nenhuma no Mercado, a tela dizia zero. O `sem_grupo` logo acima já
        #: estava certo, o que torna o deslize mais fácil de passar na leitura.
        sem_data=sem_data,
    )
