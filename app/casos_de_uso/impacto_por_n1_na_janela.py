"""Que pilares (N1) mais empurraram a nota numa janela de dias.

A PERGUNTA, nas palavras de quem pediu: "quero poder clicar em alguma data seja
no gráfico ou no eixo, que você pega a data e subtrai 15 dias, pega esse recorte
de data e me traga dois quadros logo abaixo do gráfico, um quadro com os 5 N1 que
mais impactaram positivamente o score e 5 N1 que mais impactaram negativamente".

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

#: Quantos pilares cada quadro mostra.
QUANTOS_NO_QUADRO = 5


@dataclass(frozen=True, slots=True)
class ImpactoDoPilar:
    n1: str
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
    positivos: list[ImpactoDoPilar] = field(default_factory=list)
    negativos: list[ImpactoDoPilar] = field(default_factory=list)
    #: Quantos pilares com impacto existem de cada lado, para a tela poder dizer
    #: "3 de 3" em vez de fingir que são sempre cinco.
    total_positivos: int = 0
    total_negativos: int = 0
    #: As duas formas de uma menção ficar fora — ver `SomasNaJanela`.
    sem_n1: int = 0
    sem_data_no_mes: int = 0
    #: Zero quando o mês não tem base: sem denominador não há pergunta a
    #: responder, e é diferente de "nenhum pilar impactou".
    mes_sem_base: bool = False


def ler(sessao: Session, ate: date, dias: int = DIAS_DA_JANELA) -> ImpactoNaJanela:
    """Os pilares que mais empurraram a nota na janela que termina em `ate`."""
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
    somas = repositorio_score.somas_por_n1_na_janela(sessao, lente.id, de=de, ate=ate)

    if not total_do_mes:
        return ImpactoNaJanela(
            de=de,
            ate=ate,
            mes=mes,
            regua=regua,
            sem_n1=somas.sem_n1,
            sem_data_no_mes=somas.sem_data_no_mes,
            mes_sem_base=True,
        )

    medidos: list[ImpactoDoPilar] = []
    for n1, por_fonte in somas.por_n1.items():
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
            medidos.append(ImpactoDoPilar(n1=n1, impacto=impacto, mencoes=mencoes))

    acima = sorted([p for p in medidos if p.impacto > 0], key=lambda p: -p.impacto)
    abaixo = sorted([p for p in medidos if p.impacto < 0], key=lambda p: p.impacto)

    return ImpactoNaJanela(
        de=de,
        ate=ate,
        mes=mes,
        regua=regua,
        positivos=acima[:QUANTOS_NO_QUADRO],
        negativos=abaixo[:QUANTOS_NO_QUADRO],
        total_positivos=len(acima),
        total_negativos=len(abaixo),
        sem_n1=somas.sem_n1,
        sem_data_no_mes=somas.sem_data_no_mes,
    )
