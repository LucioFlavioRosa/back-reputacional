"""As frases da Consulta em profundidade — só com os números da própria resposta.

A TELA NÃO ESCREVE TEXTO ANALÍTICO, e a base ilustrativa escrevia: "quase tudo
por um rompimento de adutora na Zona Norte". Com o dado real não há quem saiba
o evento, a causa ou o lugar — a menção da Clipei traz tier, sentimento, pilar,
subcategoria e veículo, e nada mais. Uma frase que inventasse o porquê seria a
pior mentira possível num painel: plausível, citável e impossível de conferir.

POR ISSO CADA FUNÇÃO RECEBE NÚMEROS E NOMES PRONTOS e só os põe em ordem. Toda
afirmação aqui se confere na própria resposta (o impacto de um pilar, a fatia de
um tema, o dia em que a matéria saiu), e quando a condição de uma frase não vale
cai-se num título NEUTRO, que descreve o bloco sem concluir nada.

AS CONVENÇÕES SÃO AS DO DESENHO aprovado:

    números         pt-BR, vírgula decimal e o sinal de menos tipográfico (U+2212)
    'ponto'         quando |x| < 2; 'pontos' a partir de 2 — "1,4 ponto"
    verbo           pelo sinal, com a preposição que ele pede: "tirou X pontos
                    DA nota", "pôs X pontos NA nota"; |x| < 0,05 é "não mexeu
                    na nota"
    porcentagem     só quando a parte e o todo têm o mesmo sinal e |todo| ≥ 0,1;
                    senão a frase que a usaria não é dita
    nós sem-*       ("Sem pilar identificado" etc.) nunca são citados — quem
                    chama não os passa

PURO DE PROPÓSITO: sem banco, sem data de hoje, sem configuração. É o que deixa
cada caso (plural, sinal, fallback) ser testado com dois números na mão.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

MENOS = "−"

#: Abaixo disto o impacto "não mexeu na nota": com uma casa, é o que aparece
#: como 0,0 na tabela.
QUASE_ZERO = 0.05

#: O todo mínimo para uma porcentagem fazer sentido. Abaixo disto "responde por
#: 300% da perda" é verdade aritmética e bobagem de leitura.
TODO_MINIMO_PARA_PCT = 0.1

NOMES_DOS_MESES = (
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


# -- formatação -----------------------------------------------------------------


def numero(valor: float, casas: int = 1) -> str:
    """`-7.4` vira `−7,4`. O zero nunca leva sinal (nada de `−0,0`)."""
    arredondado = round(valor, casas)
    if arredondado == 0:
        arredondado = 0.0
    texto = f"{abs(arredondado):.{casas}f}".replace(".", ",")
    return f"{MENOS}{texto}" if arredondado < 0 else texto


def com_sinal(valor: float, casas: int = 1) -> str:
    """Como `numero`, com `+` explícito no positivo — para impacto na tabela."""
    texto = numero(valor, casas)
    return texto if texto.startswith(MENOS) or round(valor, casas) == 0 else f"+{texto}"


def pontos(valor: float) -> str:
    """'ponto' abaixo de 2 em módulo, 'pontos' a partir de 2."""
    return "ponto" if abs(round(valor, 1)) < 2 else "pontos"


def plural(quantos: int, singular: str, no_plural: str) -> str:
    return f"{quantos} {singular if quantos == 1 else no_plural}"


def pct(parte: float, todo: float) -> int | None:
    """A fatia inteira de `parte` em `todo`, ou None quando não se deve dizer.

    MESMO SINAL E TODO RELEVANTE, senão a frase mente: um tema de −1,0 num pilar
    de +0,2 "responderia por −500% do ganho".

    NUNCA MAIS QUE 100%. Com irmãos de sinais opostos a parte pode passar do
    todo (um tema de −5,7 num pilar de −3,7, porque outro devolveu +2,0), e
    "responde por 154% da perda" é conta certa e leitura errada: quem lê entende
    fatia. Esse caso tem a sua própria frase ("sozinho custa mais que os demais
    somados"); aqui a fatia simplesmente não é dita.
    """
    if abs(todo) < TODO_MINIMO_PARA_PCT or parte == 0 or (parte > 0) != (todo > 0):
        return None
    fatia = round(parte / todo * 100)
    return fatia if fatia <= 100 else None


def data_curta(dia: date) -> str:
    return f"{dia:%d/%m}"


def nome_do_mes(mes: date) -> str:
    return NOMES_DOS_MESES[mes.month - 1]


def rotulo_do_mes(mes: date) -> str:
    """`Agosto de 2026` — o rótulo do cabeçalho do drill."""
    return f"{nome_do_mes(mes).capitalize()} de {mes.year}"


def mes_curto(mes: date) -> str:
    """`ago/26` — o eixo da evolução."""
    return f"{nome_do_mes(mes)[:3]}/{mes:%y}"


def _efeito_na_nota(valor: float, lente_contraida: str = "", *, no_plural: bool = False) -> str:
    """'tirou 1,4 ponto da nota da Imprensa' / 'pôs 2,0 pontos na nota do Mercado'.

    A PREPOSIÇÃO SEGUE O VERBO: tira-se ponto DA nota e põe-se ponto NA nota.
    "Pôs 2,0 pontos da nota" estava no desenho, e nenhum leitor de português o
    aceitaria num painel.
    """
    if valor < 0:
        verbo, prep = ("tiraram" if no_plural else "tirou"), "da"
    else:
        verbo, prep = ("puseram" if no_plural else "pôs"), "na"
    nota = f"{prep} nota {lente_contraida}".rstrip()
    return f"{verbo} {numero(abs(valor))} {pontos(valor)} {nota}"


def _perda_ou_ganho(valor: float) -> str:
    return "da perda" if valor < 0 else "do ganho"


# -- Nível 1: a tabela de pilares --------------------------------------------------


def titulo_da_tabela_de_pilares(
    pilares: Sequence[tuple[str, float]], lente_contraida: str, mes: str
) -> str:
    """O título que conclui a tabela de pilares, pelos casos do desenho.

    `pilares`: (nome, impacto) só dos pilares da taxonomia — o nó sem-pilar não
    entra. A ORDEM DOS CASOS vai do mais específico ao mais genérico: o par que
    concentra a pressão (b) só é dito quando há pelo menos três pilares negativos
    — com dois, "os dois maiores somam ≥ 60%" é sempre verdade e não informa nada.
    """
    negativos = sorted((p for p in pilares if p[1] <= -QUASE_ZERO), key=lambda p: p[1])
    positivos = sorted((p for p in pilares if p[1] >= QUASE_ZERO), key=lambda p: -p[1])
    perda = sum(v for _, v in negativos)
    ganho = sum(v for _, v in positivos)

    if len(negativos) >= 3 and positivos:
        dois = negativos[0][1] + negativos[1][1]
        if dois / perda >= 0.6:
            return (
                f"{negativos[0][0]} e {negativos[1][0]} tiram {numero(abs(dois))} "
                f"{pontos(dois)}; o que sustenta devolve {numero(ganho)}"
            )
    if negativos and positivos:
        return (
            f"{negativos[0][0]} é o que mais pressiona ({numero(negativos[0][1])}); "
            f"{positivos[0][0]} é o que mais sustenta ({com_sinal(positivos[0][1])})"
        )
    # UM PILAR SÓ NÃO É "TODOS", e "responde por 100%" dele é aritmética
    # trivial: com um único pilar com impacto, a frase diz exatamente isso.
    if len(negativos) == 1 and not positivos:
        return (
            f"{negativos[0][0]} é o único pilar que pressiona a nota "
            f"({numero(negativos[0][1])})"
        )
    if len(positivos) == 1 and not negativos:
        return (
            f"{positivos[0][0]} é o único pilar que sustenta a nota "
            f"({com_sinal(positivos[0][1])})"
        )
    if negativos:
        fatia = pct(negativos[0][1], perda)
        if fatia is not None:
            return (
                f"Todos os pilares com impacto pressionam a nota; {negativos[0][0]} "
                f"responde por {fatia}% da perda"
            )
    if positivos:
        fatia = pct(positivos[0][1], ganho)
        if fatia is not None:
            return (
                f"Todos os pilares com impacto sustentam a nota; {positivos[0][0]} "
                f"responde por {fatia}% do ganho"
            )
    return f"Pilares {lente_contraida} em {mes}"


def subtitulo_da_tabela_de_pilares(
    lente_contraida: str, mes: str, *, drill: bool, tem_sem_pilar: bool
) -> str:
    texto = (
        f"Quanto cada pilar empurrou a nota {lente_contraida} acima ou abaixo do neutro "
        f"(50) em {mes}. Volume em matérias; impacto ponderado pelo tier do veículo."
    )
    if drill:
        texto += " Clique num pilar para abrir os temas."
    if tem_sem_pilar:
        texto += " Matérias sem pilar identificado ficam numa linha à parte, para a conta fechar."
    return texto


# -- Nível 2: o pilar aberto -------------------------------------------------------


def leitura_do_pilar(
    *,
    pilar: str,
    impacto: float,
    lente_contraida: str,
    mes: str,
    mes_anterior: str,
    impacto_anterior: float | None,
    destaque: tuple[str, float] | None,
    concentracao: tuple[str, int] | None,
    unico_oposto: str | None,
    temas_identificados: int = 2,
) -> str:
    """O parágrafo do Nível 2, frase a frase, cada uma só quando vale.

    `concentracao`: (concessionária, % das matérias do tema em destaque) — só é
    dita a partir de 50%. `unico_oposto`: o único tema com sinal contrário ao do
    pilar, quando há exatamente um. `temas_identificados`: com um só, a fatia
    dele não é dita — "responde por 100%" de um tema único não informa nada.
    """
    if abs(impacto) < QUASE_ZERO:
        frases = [f"{pilar} não mexeu na nota {lente_contraida} em {mes}."]
    else:
        frases = [f"{pilar} {_efeito_na_nota(impacto, lente_contraida)} em {mes}."]
    if impacto_anterior is not None:
        frases.append(f"Em {mes_anterior} o impacto foi {numero(impacto_anterior)}.")
    if destaque is not None:
        fatia = pct(destaque[1], impacto) if temas_identificados >= 2 else None
        if fatia is not None:
            frases.append(f"{destaque[0]} responde por {fatia}% {_perda_ou_ganho(impacto)}.")
        if concentracao is not None and concentracao[1] >= 50:
            frases.append(
                f"{destaque[0]} se concentra em {concentracao[0]} "
                f"({concentracao[1]}% das matérias)."
            )
    if unico_oposto is not None and abs(impacto) >= QUASE_ZERO:
        verbo = "sustenta" if impacto < 0 else "pressiona"
        frases.append(f"{unico_oposto} é o único tema que {verbo}.")
    return " ".join(frases)


def titulo_da_tabela_de_filhos(
    *,
    destaque: str,
    impacto_do_destaque: float,
    impacto_do_pai: float,
    demais: Sequence[float],
    filho: str,
    pai: str,
    nome_do_pai: str,
) -> str:
    """O título da tabela do Nível 2 (temas) e do Nível 3 (subtemas).

    `filho`/`pai`: 'tema'/'pilar' ou 'subtema'/'tema'. `demais`: o impacto dos
    OUTROS filhos IDENTIFICADOS — os nós sem-* não entram, senão "os demais
    temas" seria, às escondidas, a linha "Sem tema identificado".

    COM UM SÓ IDENTIFICADO o título é neutro: "responde por 100%" de um filho
    único é verdade sem informação. "Mais que os demais somados" só se diz
    quando os demais vão NO MESMO SENTIDO: se eles devolvem pontos, "custa mais
    que os demais" compara uma perda com um ganho.
    """
    d, p = impacto_do_destaque, impacto_do_pai
    plural_do_filho = f"{filho}s"
    neutro = f"{plural_do_filho.capitalize()} de {nome_do_pai}"
    if not demais or abs(d) < QUASE_ZERO or abs(p) < QUASE_ZERO:
        return neutro
    if (d > 0) == (p > 0):
        mesmo_sentido = all(v * d >= 0 for v in demais)
        if mesmo_sentido and abs(d) > abs(sum(demais)):
            verbo = "custa" if d < 0 else "soma"
            # SEM "SOZINHO" CONCORDANDO COM O NOME: "Qualidade da água sozinho"
            # erra o gênero. Concorda com "o tema", que é sempre masculino.
            return (
                f"Sozinho, o {filho} {destaque} {verbo} {numero(abs(d))} {pontos(d)}, "
                f"mais que os demais {plural_do_filho} do {pai} somados"
            )
        fatia = pct(d, p)
        if fatia is not None:
            return f"{destaque} responde por {fatia}% {_perda_ou_ganho(p)} do {pai}"
        return neutro
    return (
        f"{destaque} é o {filho} de maior impacto ({com_sinal(d)}), na direção contrária à do {pai}"
    )


def subtitulo_da_tabela_de_temas(pilar: str, lente_contraida: str, *, tem_sem_tema: bool) -> str:
    texto = (
        f"Temas estratégicos de {pilar}, com o impacto de cada um na nota {lente_contraida}. "
        "O tema em destaque abre a evolução e a concentração logo abaixo. Clique num tema "
        "para descer aos subtemas."
    )
    if tem_sem_tema:
        texto += " Matérias sem tema identificado ficam numa linha à parte."
    return texto


def titulo_da_evolucao(
    tema: str, impactos: Sequence[float], volumes: Sequence[int], mes_anterior: str
) -> str:
    """O título do gráfico de evolução do tema em destaque (6 meses)."""
    vazios = sum(1 for v in volumes if v == 0)
    if vazios >= 4:
        return f"Evolução de {tema} nos últimos {len(impactos)} meses"
    atual = impactos[-1]
    # ESTRITO CONTRA OS MESES ANTERIORES: empatar com eles (uma série plana, por
    # exemplo) não é "chegar ao pior nível" — é ficar onde estava.
    antes = impactos[:-1]
    if antes and atual < 0 and atual < min(antes):
        return f"{tema} chegou ao pior nível dos últimos {len(impactos)} meses ({numero(atual)})"
    if antes and atual > 0 and atual > max(antes):
        return (
            f"{tema} teve o melhor resultado dos últimos {len(impactos)} meses ({com_sinal(atual)})"
        )
    delta = round(atual - impactos[-2], 1) if len(impactos) >= 2 else 0.0
    if abs(delta) >= 0.1:
        verbo = "piorou" if delta < 0 else "melhorou"
        return f"{tema} {verbo} {numero(abs(delta))} {pontos(delta)} em relação a {mes_anterior}"
    return f"{tema} ficou estável em relação a {mes_anterior}"


def subtitulo_da_evolucao(lente_contraida: str, mes: str, volumes: Sequence[int]) -> str:
    texto = (
        f"Impacto na nota {lente_contraida}, em pontos, e matérias por mês; cada mês é "
        "medido contra o total do próprio mês."
    )
    atual = volumes[-1] if volumes else 0
    if atual > 0 and all(atual > v for v in volumes[:-1]):
        texto += f" O volume de {mes} é o maior do período."
    return texto


def titulo_da_concentracao(
    linhas: Sequence[tuple[str, int, float]],
    volume: int,
    impacto: float,
    nao_informada: str,
) -> str:
    """O título do quadro de concessionárias do tema em destaque.

    `linhas`: (nome, volume, impacto) de TODAS as concessionárias do tema, antes
    do corte em quatro — "distribuídas entre n" conta todas.
    """
    informadas = sorted(
        (linha for linha in linhas if linha[0] != nao_informada), key=lambda x: (-x[1], x[0])
    )
    if not informadas or volume <= 0:
        return "A fonte não informou a concessionária destas matérias"
    nome, vol, imp = informadas[0]
    fatia = round(vol / volume * 100)
    if fatia >= 50:
        texto = f"{nome} concentra {fatia}% das matérias"
        do_impacto = pct(imp, impacto)
        if do_impacto is not None:
            texto += f" e {do_impacto}% do impacto"
        return texto
    if len(informadas) == 1:
        return f"{nome} é a única concessionária informada ({fatia}% das matérias)"
    return (
        f"Matérias distribuídas entre {len(informadas)} concessionárias; {nome} lidera com {fatia}%"
    )


def subtitulo_da_concentracao(*, uf_toda_nula: bool) -> str:
    texto = "Matérias e impacto na nota, em pontos."
    if uf_toda_nula:
        texto += " A fonte não informou a UF neste mês."
    return texto


# -- Nível 3: o tema aberto --------------------------------------------------------


def leitura_do_tema(
    *,
    subtema: str,
    impacto_do_subtema: float,
    impacto_do_tema: float,
    volume_do_subtema: int,
    mes: str,
    tier1_volume_pct: int | None,
    tier1_impacto_pct: int | None,
    veiculos: Sequence[str],
    unico: tuple[str, float] | None,
    subtemas_identificados: int = 2,
) -> str:
    frases: list[str] = []
    # Subtema único: a fatia seria sempre "100% do tema", e não é dita.
    fatia = pct(impacto_do_subtema, impacto_do_tema) if subtemas_identificados >= 2 else None
    if fatia is not None:
        frases.append(
            f"{subtema} responde por {fatia}% {_perda_ou_ganho(impacto_do_tema)} do tema."
        )
    if tier1_volume_pct is not None and tier1_impacto_pct is not None:
        frases.append(
            f"O Tier 1 é {tier1_volume_pct}% das matérias do subtema e {tier1_impacto_pct}% "
            "do impacto."
        )
    if len(veiculos) >= 2:
        frases.append(f"{veiculos[0]} e {veiculos[1]} são os veículos de maior impacto.")
    if unico is not None:
        sentido = "negativo" if unico[1] < 0 else "positivo"
        frases.append(f"{unico[0]} é o único subtema {sentido}.")
    if not frases:
        frases.append(
            f"{subtema} teve {plural(volume_do_subtema, 'matéria', 'matérias')} em {mes}."
        )
    return " ".join(frases)


def subtitulo_da_tabela_de_subtemas(tema: str, lente_contraida: str) -> str:
    return (
        f"Subtemas de {tema}, com o impacto de cada um na nota {lente_contraida}. O subtema "
        "em destaque abre os recortes abaixo. Clique num subtema para ver as matérias."
    )


def titulo_do_destaque_do_subtema(
    subtema: str,
    volume: int,
    negativas: int,
    tier1_volume_pct: int | None,
    tier1_impacto_pct: int | None,
) -> str:
    if (
        tier1_volume_pct is not None
        and tier1_impacto_pct is not None
        and tier1_impacto_pct >= 50
        and tier1_impacto_pct > tier1_volume_pct
    ):
        return (
            f"A grande imprensa pesou mais: Tier 1 é {tier1_volume_pct}% das matérias e "
            f"{tier1_impacto_pct}% do impacto"
        )
    return (
        f"{subtema}: {plural(volume, 'matéria', 'matérias')}, "
        f"{plural(negativas, 'negativa', 'negativas')}"
    )


def subtitulo_do_destaque_do_subtema(volume: int, negativas: int, lente_contraida: str) -> str:
    return (
        f"{plural(volume, 'matéria', 'matérias')}, {plural(negativas, 'negativa', 'negativas')}. "
        f"Impacto em pontos na nota {lente_contraida}."
    )


def titulo_dos_tiers(peso_tier1: float, peso_tier3: float) -> str:
    """Quanto uma matéria de Tier 1 vale contra uma de Tier 3, na régua vigente."""
    if peso_tier3 == 0:
        return "Nesta calibração só o Tier 1 conta na nota"
    razao = peso_tier1 / peso_tier3
    if razao == 1:
        return "Nesta calibração os três tiers pesam igual"
    vezes = f"{razao:.0f}" if razao == int(razao) else numero(razao)
    return f"Cada matéria de Tier 1 pesa {vezes} vezes uma de Tier 3"


def titulo_das_concessionarias_do_subtema(
    linhas: Sequence[tuple[str, str, int, float]],
    volume: int,
    impacto: float,
    nao_informada: str,
) -> str:
    """`linhas`: (concessionária, UF, volume, impacto) de todos os pares.

    A UF VAI ENTRE PARÊNTESES, e não com preposição: a Clipei manda o estado por
    extenso, e "no {UF}" daria "no Bahia". Parêntese não tem gênero.
    """
    informadas = sorted(
        (linha for linha in linhas if linha[0] != nao_informada), key=lambda x: (-x[2], x[0])
    )
    if not informadas or volume <= 0:
        return "A fonte não informou a concessionária destas matérias"
    nome, uf, vol, imp = informadas[0]
    onde = f"{nome} ({uf})" if uf and uf != nao_informada else nome
    fatia = round(vol / volume * 100)
    if fatia >= 50:
        texto = f"{onde} concentra {fatia}% das matérias"
        do_impacto = pct(imp, impacto)
        if do_impacto is not None:
            texto += f" e {do_impacto}% do impacto"
        return texto
    distintas = len({linha[0] for linha in informadas})
    return f"{distintas} concessionárias no subtema; {nome} lidera com {fatia}%"


def titulo_dos_veiculos(linhas: Sequence[tuple[str, float]], impacto_do_subtema: float) -> str:
    """`linhas`: (veículo, impacto), já na ordem do quadro."""
    if len(linhas) >= 2:
        soma = linhas[0][1] + linhas[1][1]
        mesmo_sentido = all(
            (v < 0) == (impacto_do_subtema < 0) and abs(v) >= QUASE_ZERO for _, v in linhas[:2]
        )
        fatia = pct(soma, impacto_do_subtema)
        if mesmo_sentido and fatia is not None:
            return (
                f"{linhas[0][0]} e {linhas[1][0]} somam {numero(abs(soma))} {pontos(soma)}, "
                f"{fatia}% do subtema"
            )
    return "Veículos de maior impacto no subtema"


def titulo_dos_jornalistas(
    linhas: Sequence[tuple[str, int]], negativas_do_subtema: int, *, ha_autor: bool
) -> str:
    """`linhas`: (jornalista, negativas). Sem autor no dado, o título só diz isso."""
    if not ha_autor:
        return "A fonte não informa o jornalista destas matérias"
    com_negativa = [n for _, n in linhas if n > 0]
    if negativas_do_subtema > 0 and com_negativa:
        k = len(com_negativa)
        assinaturas = "Uma assinatura responde" if k == 1 else f"{k} assinaturas respondem"
        return (
            f"{assinaturas} por {sum(com_negativa)} das {negativas_do_subtema} matérias negativas"
        )
    return "Jornalistas de maior impacto no subtema"


TITULO_DOS_JORNALISTAS_RESTRITO = "Os jornalistas ficam visíveis para quem tem acesso ao diretório"


# -- Nível 4: as matérias ----------------------------------------------------------


def leitura_das_materias(
    *,
    pct_na_janela: int,
    dia_inicial: int,
    dia_final: int,
    mes: str,
    tier1_no_topo: int,
    positiva_de_maior_impacto: date | None,
) -> str:
    frases = [f"{pct_na_janela}% das matérias saíram entre {dia_inicial} e {dia_final} de {mes}."]
    if tier1_no_topo >= 3:
        frases.append(f"As {tier1_no_topo} de maior impacto são de grande imprensa (Tier 1).")
    if positiva_de_maior_impacto is not None:
        frases.append(
            f"A positiva de maior impacto saiu em {data_curta(positiva_de_maior_impacto)}."
        )
    return " ".join(frases)


def titulo_da_lista(
    *,
    subtema: str,
    mes: str,
    volume: int,
    negativas: int,
    tier1_no_topo: int,
    negativa_de_maior_impacto: date | None,
) -> str:
    if tier1_no_topo >= 3:
        return f"As {tier1_no_topo} matérias de maior impacto são de grande imprensa (Tier 1)"
    if negativas > 0 and negativa_de_maior_impacto is not None:
        return (
            f"{negativas} de {plural(volume, 'matéria', 'matérias')} "
            f"{'é negativa' if negativas == 1 else 'são negativas'}; a de maior impacto saiu "
            f"em {data_curta(negativa_de_maior_impacto)}"
        )
    return f"Matérias de {subtema} em {mes}"


def subtitulo_da_lista(
    *, lente_contraida: str, valor_tier1: float | None, mostradas: int, volume: int
) -> str:
    """O valor de uma matéria de Tier 1 na nota — derivado exato, 50 × T1 ÷ D.

    `valor_tier1` None: a régua do mês pesa também o engajamento (ou o cargo), e
    cada matéria de Tier 1 vale um número diferente. Afirmar um valor único aí
    seria citar um número que nenhuma matéria da lista tem.
    """
    if valor_tier1 is None:
        texto = (
            f"Impacto de cada matéria na nota {lente_contraida}, em pontos, ponderado pelo "
            "tier do veículo e pelo engajamento."
        )
    else:
        u = numero(abs(valor_tier1), 2)
        texto = (
            f"Impacto de cada matéria na nota {lente_contraida}, em pontos: Tier 1 vale "
            f"{MENOS}{u} quando negativa e +{u} quando positiva."
        )
    if mostradas < volume:
        texto += f" A lista mostra as {mostradas} de maior impacto de {volume}."
    return texto


# -- cartões laterais --------------------------------------------------------------


def rotulo_do_que_mudou(mes_anterior: str) -> str:
    return f"O que mudou desde {mes_anterior}"


def titulo_do_que_mudou(mes_anterior: str) -> str:
    return f"Variação do impacto por pilar desde {mes_anterior}"


def nota_do_que_mudou(
    *,
    mes_anterior: str,
    pilar: tuple[str, float, float] | None,
    tema: tuple[str, float] | None,
) -> str:
    """`pilar`: (nome, impacto anterior, atual) do pilar que mais variou;
    `tema`: (nome, Δ) do tema que mais variou dentro dele."""
    if pilar is None:
        return f"Sem base em {mes_anterior} para comparar."
    nome, antes, agora = pilar
    if abs(agora - antes) < QUASE_ZERO:
        return f"Nenhum pilar mudou de impacto desde {mes_anterior}."
    texto = f"{nome} foi de {numero(antes)} para {numero(agora)} pt"
    if tema is not None and abs(tema[1]) >= QUASE_ZERO:
        texto += f"; no pilar, o tema que mais variou foi {tema[0]} ({com_sinal(tema[1])})"
    return texto + "."


def texto_da_historia(
    *,
    volume: int,
    mes: str,
    pct_na_janela: int,
    dia_inicial: int,
    dia_final: int,
    impacto: float,
    publicada_em: date | None = None,
) -> str:
    """O texto do cartão "A história do mês".

    UMA MATÉRIA SÓ PEDE O SINGULAR e dispensa a janela: "100% delas entre 13 e
    19" de uma matéria é porcentagem sobre nada. `publicada_em` é o dia dela;
    sem ele, a frase diz só o mês.
    """
    if volume == 1:
        efeito = "não mexeu na nota" if abs(impacto) < QUASE_ZERO else _efeito_na_nota(impacto)
        quando = f", publicada em {data_curta(publicada_em)}," if publicada_em else ""
        return f"1 matéria em {mes}{quando} {efeito}."
    if abs(impacto) < QUASE_ZERO:
        efeito = "e não mexeram na nota"
    else:
        efeito = _efeito_na_nota(impacto, no_plural=True)
    return (
        f"{plural(volume, 'matéria', 'matérias')} em {mes}, {pct_na_janela}% delas entre "
        f"{dia_inicial} e {dia_final}, {efeito}."
    )


def titulo_dos_divergentes(linhas: Sequence[tuple[str, float]], total_do_sinal: float) -> str:
    """`linhas`: (tema, impacto) por |impacto| decrescente; `total_do_sinal`: a soma
    dos impactos dos TEMAS IDENTIFICADOS com o sinal dos dois primeiros.

    "DOS TEMAS IDENTIFICADOS", E NÃO "DA LENTE": o ganho da lente inclui o que
    ficou sem tema (e os pilares sem tema nenhum), e um total que somasse uma
    coisa com o nome de outra seria o número que alguém confere e não acha.
    """
    if len(linhas) >= 2:
        a, b = linhas[0][1], linhas[1][1]
        if (a < 0) == (b < 0) and abs(a) >= QUASE_ZERO and abs(b) >= QUASE_ZERO:
            soma = a + b
            if abs(total_do_sinal) >= abs(soma) and abs(total_do_sinal) >= TODO_MINIMO_PARA_PCT:
                tipo = "de perda" if soma < 0 else "de ganho"
                return (
                    f"{linhas[0][0]} e {linhas[1][0]} somam {numero(abs(soma))} dos "
                    f"{numero(abs(total_do_sinal))} {pontos(total_do_sinal)} {tipo} "
                    "dos temas identificados"
                )
    return "Temas de maior impacto no Mercado"
