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

SÓ A LENTE DE IMPRENSA, também por pedido ("considere nesse momento somente dados
da lente de impressa"). Fixa no código em vez de parâmetro: um parâmetro que
ninguém passa é generalidade especulativa, e a lente certa aqui não é detalhe de
chamada — é o recorte que faz a pergunta ter resposta. Quando a segunda lente
chegar, ela chega com o pedido que a justifica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco import repositorio_score
from app.banco.tabelas_score import Lente
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.score import Contagem, ponderar
from app.dominio.tema_do_mes import PONTOS_POR_NS

#: A lente desta leitura. Ver o cabeçalho do módulo.
LENTE = "imprensa"

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


def registros(
    sessao: Session,
    ate: date,
    grupo: int,
    dias: int = DIAS_DA_JANELA,
    nivel: str = NIVEL_PADRAO,
    pagina: int = 1,
    tamanho: int = 50,
) -> repositorio_score.RegistrosDaJanela:
    """As menções que compõem UM grupo do quadro — o que abre ao clicar nele.

    O PEDIDO: "se eu clicar em alguma dessas opções quero que abra um modal com
    os registros do tema ou pilar, assim como fazemos nas lentes no KPI".

    A JANELA É CALCULADA AQUI, pelos mesmos `ate` e `dias` do quadro, e não vem
    pronta da tela: duas contas de data em dois lugares divergem na primeira vez
    que alguém mudar o tamanho da janela. A tela manda o que ela clicou (o dia e
    o grupo); quem sabe o que é uma janela é este módulo.

    O RECORTE É O MESMO DO QUADRO — ver `registros_do_grupo_na_janela`, que
    explica por que a rota da Base das lentes não serve.
    """
    if dias < 1:
        raise RegraViolada("A janela precisa de pelo menos um dia.")
    if nivel not in repositorio_score.NIVEIS_DA_JANELA:
        raise RegraViolada(f"Nivel desconhecido: {nivel}.")

    lente = sessao.execute(select(Lente).where(Lente.codigo == LENTE)).scalar_one_or_none()
    if lente is None:
        raise NaoEncontrado(f"A lente {LENTE} não está cadastrada.")

    return repositorio_score.registros_do_grupo_na_janela(
        sessao,
        lente.id,
        de=ate - timedelta(days=dias - 1),
        ate=ate,
        grupo_id=grupo,
        calibracao=repositorio_score.calibracao_vigente(sessao),
        nivel=nivel,
        pagina=pagina,
        tamanho=tamanho,
    )


def ler(
    sessao: Session,
    ate: date,
    dias: int = DIAS_DA_JANELA,
    nivel: str = NIVEL_PADRAO,
) -> ImpactoNaJanela:
    """Os temas (N2) que mais empurraram a nota na janela que termina em `ate`."""
    if dias < 1:
        raise RegraViolada("A janela precisa de pelo menos um dia.")

    lente = sessao.execute(select(Lente).where(Lente.codigo == LENTE)).scalar_one_or_none()
    if lente is None:
        raise NaoEncontrado(f"A lente {LENTE} não está cadastrada.")

    #: INCLUSIVA NAS DUAS PONTAS, e `dias - 1` é o que faz "15 dias" serem quinze
    #: dias: de 10/09 menos 14 dá 27/08, e de 27/08 a 10/09 há exatamente quinze
    #: dias contados. `ate - 15` daria dezesseis.
    de = ate - timedelta(days=dias - 1)
    mes = repositorio_score.primeiro_dia(ate)
    calibracao = repositorio_score.calibracao_vigente(sessao)

    regua, total_do_mes = repositorio_score.denominador_do_mes(sessao, lente.id, mes, calibracao)
    if nivel not in repositorio_score.NIVEIS_DA_JANELA:
        raise RegraViolada(f"Nivel desconhecido: {nivel}.")
    somas = repositorio_score.somas_por_nivel_na_janela(
        sessao, lente.id, de=de, ate=ate, nivel=nivel
    )

    if not total_do_mes:
        return ImpactoNaJanela(
            de=de,
            ate=ate,
            mes=mes,
            regua=regua,
            sem_grupo=somas.sem_grupo,
        nivel=nivel,
            sem_data=somas.sem_data,
            mes_sem_base=True,
        )

    medidos: list[ImpactoDoGrupo] = []
    for id_do_grupo, por_fonte in somas.por_grupo.items():
        grupo = somas.grupos[id_do_grupo]
        #: AS FONTES DESLIGADAS NA CALIBRAÇÃO SAEM, como em toda leitura do
        #: índice: a nota não as conta, e contá-las aqui faria o impacto de um
        #: pilar incluir o que a nota ignorou.
        ligadas = [
            linhas for fonte, linhas in por_fonte.items() if calibracao.ligada(fonte)
        ]
        if not ligadas:
            continue
        contagem = Contagem()
        mencoes = 0
        for linhas in ligadas:
            #: A MESMA RÉGUA DO DENOMINADOR, passada de fora: deixar `ponderar`
            #: escolher a dele mediria um pilar em menções contra um mês medido
            #: em curtidas — ver o comentário de `composicao_da_lente`.
            contagem = contagem + ponderar(linhas, calibracao, regua)
            mencoes += sum(int(linha.mencoes) for linha in linhas)
        impacto = PONTOS_POR_NS * (contagem.positivo - contagem.negativo) / total_do_mes
        if impacto:
            medidos.append(
                ImpactoDoGrupo(
                    id=grupo.id,
                    rotulo=grupo.nome,
                    contexto=grupo.contexto,
                    impacto=impacto,
                    mencoes=mencoes,
                )
            )

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
        regua=regua,
        positivos=acima[:QUANTOS_NO_QUADRO],
        negativos=abaixo[:QUANTOS_NO_QUADRO],
        total_positivos=len(acima),
        total_negativos=len(abaixo),
        sem_grupo=somas.sem_grupo,
        nivel=nivel,
        sem_data=somas.sem_data,
    )
