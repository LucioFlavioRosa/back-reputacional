"""As frases que os detectores produzem, num lugar só.

POR QUE ISOLAR O TEXTO. Um detector responde "isto aconteceu"; a frase responde
"como se diz isso em português". São dois trabalhos que mudam por motivos
diferentes: o limite de um pico muda quando a coordenação recalibra, e a frase
muda quando alguém acha que "recuou" soa melhor que "caiu". Misturados, toda
revisão de texto vira risco de mexer na regra.

É também o que a §6 do pacote pede — e o que permitirá traduzir a tela sem
caçar aspas dentro de condicionais.

TRÊS REGRAS DE IDIOMA valem para tudo aqui, e nenhuma é decorativa:

    mês por extenso, minúsculo      "junho", e não "jun" nem "Junho" no meio
                                    da frase — número de mês numa frase de
                                    diretoria é ruído
    número em pt-BR                 1.529, e não 1,529 nem 1529
    plural conferido                "2 agências voltaram" e "1 agência voltou";
                                    "1 meses" denuncia que ninguém leu a tela
"""

from __future__ import annotations

from datetime import date

#: Por extenso e minúsculo: as frases inserem o mês no meio de uma oração.
MES_POR_EXTENSO: tuple[str, ...] = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def mes_de(quando: date) -> str:
    return MES_POR_EXTENSO[quando.month - 1]


def maiuscula(texto: str) -> str:
    """Primeira letra maiúscula, sem tocar no resto — `capitalize` derruba o
    resto da frase e transformaria "Copasa / ALMG" em "Copasa / almg"."""
    return texto[:1].upper() + texto[1:]


def inteiro(valor: float) -> str:
    """1529 → "1.529". O separador de milhar é o ponto."""
    return f"{round(valor):,}".replace(",", ".")


def decimal(valor: float, casas: int = 1) -> str:
    """2.2 → "2,2". Uma casa por padrão, e sempre a mesma quantidade: "4" numa
    escala de 1 a 5 lê-se como inteiro arredondado, e "4,0" como medida."""
    return f"{valor:.{casas}f}".replace(".", ",")


def porcento(fracao: float) -> str:
    """0.234 → "23%". Sem casa decimal: a precisão que a fatia tem é essa."""
    return f"{round(fracao * 100)}%"


def plural(quantidade: int, singular: str, plural_: str) -> str:
    return singular if abs(quantidade) == 1 else plural_


def lista(itens: list[str]) -> str:
    """["a", "b", "c"] → "a, b e c". Com um item, o item."""
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


# -- os modelos de frase --------------------------------------------------------
#
# Um por detector, na ordem do §5 do pacote. O nome diz o detector; o corpo é a
# única coisa que muda quando alguém quer outro jeito de dizer.


def pico(quando: date, volume: int, unidade: str, razao: float) -> str:
    return (
        f"{maiuscula(mes_de(quando))} teve o maior volume do período "
        f"({inteiro(volume)} {unidade}), {decimal(razao)}× a média mensal."
    )


def virada(delta: int, quando: date, antes: float, depois: float) -> str:
    """A nota andou — ou o saldo trocou de lado sem a nota andar.

    O SEGUNDO CASO EXISTE E NÃO É RARO: a nota é o saldo reescalado e
    arredondado, e um saldo que cruza o zero por pouco pode cair no mesmo
    inteiro dos dois lados. "A nota caiu 0 ponto" seria a frase, e ela é
    absurda — o que aconteceu ali foi a troca de lado, e é isso que se diz.
    """
    if not delta:
        return (
            f"O saldo virou para o negativo em {mes_de(quando)}: o negativo foi de "
            f"{porcento(antes)} para {porcento(depois)}."
            if depois > antes
            else f"O saldo virou para o positivo em {mes_de(quando)}: o negativo "
            f"foi de {porcento(antes)} para {porcento(depois)}."
        )
    verbo = "subiu" if delta > 0 else "caiu"
    return (
        f"A nota {verbo} {abs(delta)} {plural(abs(delta), 'ponto', 'pontos')} em "
        f"{mes_de(quando)}: o negativo foi de {porcento(antes)} para {porcento(depois)}."
    )


def alta_do_negativo(antes: float, quando_antes: date, depois: float, quando: date) -> str:
    return (
        f"O negativo subiu de {porcento(antes)} em {mes_de(quando_antes)} para "
        f"{porcento(depois)} em {mes_de(quando)}."
    )


def tendencia(caindo: bool, fatias: list[float]) -> str:
    verbo = "cai" if caindo else "sobe"
    return (
        f"O negativo {verbo} há {len(fatias)} meses seguidos: "
        + " → ".join(porcento(fatia) for fatia in fatias)
        + "."
    )


def deslocamento(pico_fatia: float, quando_pico: date, ultima: float, quando: date) -> str:
    return (
        f"O negativo recuou de {porcento(pico_fatia)} em {mes_de(quando_pico)} para "
        f"{porcento(ultima)} em {mes_de(quando)}."
    )


def lacuna_de_dado(sem_sentimento: list[date], sem_base: list[date]) -> str:
    partes = []
    if sem_sentimento:
        nomes = lista([mes_de(quando) for quando in sem_sentimento])
        partes.append(f"Sentimento de {nomes} ainda não integrado.")
    if sem_base:
        nomes = lista([mes_de(quando) for quando in sem_base])
        partes.append(f"{maiuscula(nomes)} sem base.")
    return " ".join(partes)


def tema_dominante(item: str, fatia: float, geral: float | None) -> str:
    sufixo = f" (geral {porcento(geral)})." if geral is not None else "."
    return f"{item} concentra o maior negativo: {porcento(fatia)}{sufixo}"


def sustenta(item: str, fatia: float) -> str:
    return f"{item} é o mais favorável: {porcento(fatia)} positivo."


def concentracao_por_razao(
    primeiro: str, razao: float, segundo: str, ordinal_do_segundo: str
) -> str:
    """`ordinal_do_segundo` chega pronto: "a segunda unidade", "o segundo órgão".

    ADIVINHAR O GÊNERO PELA ÚLTIMA LETRA acerta "unidade" e erra "empresa" —
    e um artigo errado numa frase de diretoria é o tipo de detalhe que faz
    duvidar do número ao lado dele. Quem chama sabe o gênero; o modelo não.
    """
    return f"{primeiro} tem {decimal(razao)}× o volume de {segundo}, {ordinal_do_segundo}."


def concentracao_do_topo(itens: list[str], fatia: float, unidade: str) -> str:
    verbo = plural(len(itens), "concentra", "concentram")
    return f"{lista(itens)} {verbo} {porcento(fatia)} das {unidade}."


def deslocamento_percentual(
    nome: str, maior: float, quando_maior: date, ultimo: float, quando: date, e_minimo: bool
) -> str:
    fecho = ", o menor peso do período." if e_minimo else "."
    return (
        f"{nome} caiu de {porcento(maior)} em {mes_de(quando_maior)} para "
        f"{porcento(ultimo)} em {mes_de(quando)}{fecho}"
    )


def lacuna_de_relacionamento(
    nome: str, veiculo: str | None, relevancia: int, exposicao: int, proximidade: int
) -> str:
    onde = f" ({veiculo})" if veiculo else ""
    return (
        f"{nome}{onde} tem relevância {relevancia} e exposição {exposicao}, mas "
        f"proximidade {proximidade} — a maior distância da matriz."
    )


def prioridade_um(quantos: int) -> str:
    verbo = plural(quantos, "está", "estão")
    return (
        f"{quantos} {plural(quantos, 'jornalista', 'jornalistas')} {verbo} em "
        "prioridade 1 (relacionamento contínuo)."
    )


def pressao(meses_sob_pressao: list[date], meses_com_evento: int) -> str:
    nomes = lista([mes_de(quando) for quando in meses_sob_pressao])
    return (
        f"A pressão predominou em {len(meses_sob_pressao)} de {meses_com_evento} "
        f"{plural(meses_com_evento, 'mês', 'meses')} com eventos ({nomes})."
    )


def concentracao_de_eventos(quando: date, textos: list[str]) -> str:
    return (
        f"{maiuscula(mes_de(quando))} concentra {len(textos)} eventos de pressão: {lista(textos)}."
    )


def contraste(pior: str, nota_pior: float, melhor: str, nota_melhor: float) -> str:
    return (
        f"{pior} ({decimal(nota_pior)}) fica {decimal(nota_melhor - nota_pior)} pontos "
        f"abaixo de {melhor[:1].lower() + melhor[1:]} ({decimal(nota_melhor)}) — o maior "
        "contraste do estudo."
    )


def rating(quantas: int, desde: date, com_perspectiva_negativa: list[str]) -> str:
    verbo = plural(quantas, "voltou", "voltaram")
    frase = (
        f"{quantas} {plural(quantas, 'agência', 'agências')} {verbo} a rebaixar "
        f"depois de {mes_de(desde)}"
    )
    if com_perspectiva_negativa:
        return f"{frase}; {lista(com_perspectiva_negativa)} com perspectiva negativa."
    return f"{frase}."


def proxy_sem_serie() -> str:
    return (
        "Mercado sem série mensal de sentimento: a nota é um proxy dos veículos Tier 1 econômicos."
    )


def recuperacao(taxa: float, quando: date, minima: float, quando_minima: date) -> str:
    return (
        f"A taxa bruta de resposta voltou a {porcento(taxa)} em {mes_de(quando)}, "
        f"após mínima de {porcento(minima)} em {mes_de(quando_minima)}."
    )


SEM_SINAL = "Sem variação relevante no período pelas regras atuais."
SEM_SINAL_NA_SERIE = "Série mensal sem variação relevante pelas regras atuais."
SEM_SINAL_NA_LISTA = "Nenhum sinal acima dos limites configurados."
