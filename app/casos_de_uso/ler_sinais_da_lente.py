"""Qual detector lê qual gráfico, em cada lente — o mapeamento da §5.6.

ESTE É O ÚNICO LUGAR QUE SABE AS DUAS COISAS: de onde o dado vem (o
repositório) e o que se lê dele (os detectores). Os detectores não conhecem
banco e não sabem o que é uma lente; o repositório não sabe o que é um sinal. A
tradução entre os dois mora aqui, e é por isso que ela cabe numa função por
lente.

POR QUE NÃO ESTÁ NO ENDPOINT. Porque o endpoint já tem trabalho: montar quinze
campos de payload, decidir fichas, escolher legendas. Enfiar aqui dentro o
mapeamento faria as duas responsabilidades crescerem juntas — e a primeira
pergunta de quem for calibrar um limite ("de onde sai o pico da imprensa?")
exigiria ler o endpoint inteiro para achar a resposta.

TODA LENTE DEVOLVE UMA `Leitura`, mesmo sem nenhum sinal: a tela sempre tem uma
manchete, um título de evolução e um quadro lateral para preencher, e devolver
nada obrigaria cada um desses lugares a inventar o próprio texto de vazio.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date

from app.banco import repositorio_lentes
from app.dominio.erros import RegraViolada
from app.dominio.score import Calibracao
from app.dominio.sinais_da_lente import (
    AcaoDeRating,
    Evento,
    Item,
    Jornalista,
    Leitura,
    Limites,
    Ponto,
    Secao,
    Sinal,
    detectar_na_matriz,
    detectar_na_recuperacao,
    detectar_na_serie,
    detectar_no_estudo,
    detectar_no_percentual,
    detectar_no_ranking,
    detectar_no_rating,
    detectar_no_volume,
    detectar_nos_eventos,
    detectar_nos_itens,
    escolher,
    sinal_de_proxy,
)

#: O teor cujo peso a lente de Clientes acompanha mês a mês.
TEOR_ACOMPANHADO = "Reclamação"

registrador = logging.getLogger(__name__)


def regua_dos_sinais(calibracao: Calibracao) -> Limites:
    """Os limites gravados — ou os de fábrica, quando os gravados não servem.

    O ENDPOINT DA CALIBRAÇÃO JÁ RECUSA valor inválido antes de gravar, e é lá
    que a pessoa precisa ver o erro. Mas `score_config` é uma tabela como outra
    qualquer: um `insert` na mão, um script de migração de ambiente ou um job
    podem pôr lá dentro uma chave em camelCase ou um zero.

    SE A LEITURA TAMBÉM ESTOURASSE, esse engano derrubaria a Calibração e as
    cinco lentes para todo mundo, com 500 — e ninguém conseguiria abrir a tela
    onde se conserta a régua. Cair no padrão de fábrica mantém o painel de pé; o
    log é o que impede a degradação de passar despercebida.
    """
    try:
        return Limites.a_partir_de(calibracao.limites)
    except RegraViolada as erro:
        registrador.error("Limites inválidos em score_config; usando o padrão de fábrica: %s", erro)
        return Limites()


def ler_sinais(
    sessao,
    lente,
    mes: date,
    meses: Sequence[date],
    calibracao: Calibracao,
    *,
    limites: Limites,
    nome_do_painel_a: str,
    nome_do_painel_b: str,
) -> Leitura:
    """O que está acontecendo nesta lente, já escolhido para cada lugar da tela."""
    detectores = {
        "imprensa": _da_imprensa,
        "mercado": _do_mercado,
        "clientes": _dos_clientes,
        "institucional": _do_institucional,
    }
    de = detectores.get(lente.codigo, _da_sociedade)
    return escolher(
        de(sessao, lente, mes, meses, calibracao, limites),
        limites=limites,
        nome_do_painel_a=nome_do_painel_a,
        nome_do_painel_b=nome_do_painel_b,
    )


# -- o que cada lente lê ---------------------------------------------------------


def _da_imprensa(sessao, lente, mes, meses, calibracao, limites) -> list[Sinal]:
    return [
        *detectar_na_serie(
            _serie(sessao, lente, meses, calibracao),
            unidade="matérias",
            secao=Secao.EVOLUCAO,
            limites=limites,
        ),
        *detectar_nos_itens(
            _tiers(sessao, lente, mes, calibracao),
            secao=Secao.PAINEL_A,
            rotulo_do_negativo="Tier",
        ),
        *detectar_na_matriz(
            [
                Jornalista(
                    nome=pessoa.nome,
                    veiculo=pessoa.veiculo,
                    relevancia=pessoa.relevancia,
                    exposicao=pessoa.exposicao,
                    proximidade=pessoa.proximidade,
                )
                for pessoa in repositorio_lentes.matriz_de_jornalistas(sessao)
            ],
            secao=Secao.PAINEL_B,
        ),
    ]


def _do_mercado(sessao, lente, mes, meses, calibracao, limites) -> list[Sinal]:
    """A única lente sem série de sentimento — e a única que precisa dizer isso.

    O EVENTOGRAMA OCUPA O LUGAR DA EVOLUÇÃO. Não é uma contagem mensal, é uma
    sequência de fatos; rodar nela os detectores de série produziria variação
    de nota a partir de números que ninguém mediu.
    """
    eventos = repositorio_lentes.eventos_de_mercado(sessao, meses)
    _, atributos = repositorio_lentes.estudo_vigente(sessao, mes)
    return [
        *detectar_nos_eventos(
            [
                Evento(quando=evento.data, texto=evento.texto, efeito=evento.efeito)
                for evento in eventos
            ],
            secao=Secao.EVOLUCAO,
        ),
        *detectar_no_estudo(
            [(atributo.atributo, float(atributo.nota)) for atributo in atributos],
            secao=Secao.PAINEL_A,
        ),
        *detectar_no_rating(
            [
                AcaoDeRating(
                    agencia=evento.agencia,
                    quando=evento.data,
                    efeito=evento.efeito,
                    perspectiva=evento.perspectiva,
                )
                for evento in eventos
                if evento.tipo == "rating" and evento.agencia
            ],
            secao=Secao.PAINEL_B,
        ),
        sinal_de_proxy(),
    ]


def _dos_clientes(sessao, lente, mes, meses, calibracao, limites) -> list[Sinal]:
    """A evolução conta MENSAGENS, não sentimento — daí o pico e a recuperação.

    O SENTIMENTO DESCE PARA O PAINEL A, e sem pico: o pico de volume já foi dito
    na evolução, e repeti-lo gastaria uma das cinco vagas com a mesma notícia.
    """
    recebidas = repositorio_lentes.recebidas_por_mes(sessao, lente.id, meses, calibracao)
    respondidas = repositorio_lentes.respondidas_por_mes(sessao, meses)
    taxa = [
        (
            quando,
            (respondidas[quando]["respondidas"] / recebidas[quando])
            if quando in respondidas and recebidas.get(quando)
            else None,
        )
        for quando in meses
    ]
    return [
        *detectar_no_volume(
            [(quando, recebidas.get(quando)) for quando in meses],
            unidade="mensagens",
            secao=Secao.EVOLUCAO,
            limites=limites,
        ),
        *detectar_na_recuperacao(taxa, secao=Secao.EVOLUCAO, limites=limites),
        *detectar_na_serie(
            _serie(sessao, lente, meses, calibracao),
            unidade="mensagens",
            secao=Secao.PAINEL_A,
            limites=limites,
            com_pico=False,
        ),
        *detectar_no_percentual(
            _peso_do_teor(sessao, lente, meses, calibracao),
            nome=TEOR_ACOMPANHADO,
            secao=Secao.PAINEL_B,
            limites=limites,
        ),
    ]


def _do_institucional(sessao, lente, mes, meses, calibracao, limites) -> list[Sinal]:
    """Lê do CRM, e não das menções: a fonte desta lente é interna."""
    return [
        *detectar_na_serie(
            _serie(sessao, lente, meses, calibracao),
            unidade="agendas",
            secao=Secao.EVOLUCAO,
            limites=limites,
        ),
        *detectar_nos_itens(
            _itens(repositorio_lentes.temas_do_crm(sessao, meses), "tema"),
            secao=Secao.PAINEL_A,
        ),
        *detectar_no_ranking(
            _ranking(repositorio_lentes.orgaos_do_crm(sessao, meses)),
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="o segundo órgão",
            unidade="agendas",
            limites=limites,
        ),
    ]


def _da_sociedade(sessao, lente, mes, meses, calibracao, limites) -> list[Sinal]:
    return [
        *detectar_na_serie(
            _serie(sessao, lente, meses, calibracao),
            unidade="menções",
            secao=Secao.EVOLUCAO,
            limites=limites,
        ),
        # CONTAGEM, E NÃO PERCENTUAL — e isto diverge da §5.6 de propósito. A
        # especificação diz "5.2 sobre temas (%)" porque no protótipo os temas
        # da Approach vêm já normalizados, linha a linha. A NOSSA base guarda
        # menção a menção, e `temas_por_sentimento` devolve contagens: com elas
        # existe um "geral" com que comparar, e some-lo é a leitura que a frase
        # promete. Passar `percentual=True` aqui jogaria fora esse número por
        # fidelidade a uma forma de dado que não é a nossa.
        *detectar_nos_itens(
            _itens(
                repositorio_lentes.temas_por_sentimento(sessao, lente.id, mes, calibracao),
                "tema",
            ),
            secao=Secao.PAINEL_A,
        ),
        *detectar_no_ranking(
            _ranking(repositorio_lentes.unidades_da_lente(sessao, lente.id, meses, calibracao)),
            secao=Secao.PAINEL_B,
            ordinal_do_segundo="a segunda unidade",
            unidade="menções",
            limites=limites,
        ),
    ]


# -- as traduções que se repetem -------------------------------------------------


def _serie(sessao, lente, meses, calibracao) -> list[Ponto]:
    return [
        Ponto(
            mes=linha["mes"],
            pos=linha["pos"],
            neu=linha["neu"],
            neg=linha["neg"],
            sem_classificacao=linha.get("sem_classificacao", 0),
            sem_base=linha["sem_base"],
        )
        for linha in repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao)
    ]


def _tiers(sessao, lente, mes, calibracao) -> list[Item]:
    nomes = {
        "muito_relevante": "Muito Relevante",
        "relevante": "Relevante",
        "menos_relevante": "Menos Relevante",
    }
    return [
        Item(
            rotulo=nomes.get(linha["tier"], linha["tier"]),
            pos=linha["positivo"],
            neu=linha["neutro"],
            neg=linha["negativo"],
        )
        for linha in repositorio_lentes.composicao_por_tier(sessao, lente.id, mes, calibracao)
    ]


def _itens(linhas: list[dict], chave: str) -> list[Item]:
    return [
        Item(
            rotulo=linha[chave],
            pos=linha["positivo"],
            neu=linha["neutro"],
            neg=linha["negativo"],
        )
        for linha in linhas
    ]


def _ranking(linhas: list[dict]) -> list[tuple[str, float]]:
    return [(linha["unidade"], linha["total"]) for linha in linhas]


def _peso_do_teor(sessao, lente, meses, calibracao) -> list[tuple[date, float | None]]:
    """Quanto do que era contato de verdade foi reclamação, mês a mês.

    O DENOMINADOR SÃO OS ACIONÁVEIS, e não o total: marcação de post e NPR
    chegam pelo mesmo canal e não são gente procurando a companhia. Dividir por
    tudo faria o peso da reclamação parecer menor nos meses em que a marca foi
    mais citada — que é exatamente quando ela sobe.
    """
    return [
        (
            linha["mes"],
            (linha["teores"].get(TEOR_ACOMPANHADO, 0) / linha["acionaveis"] * 100)
            if linha["acionaveis"]
            else None,
        )
        for linha in repositorio_lentes.teor_por_mes(sessao, lente.id, meses, calibracao)
    ]
