"""O rastreio de risco: o que é um incidente, e como ele vira índice.

O QUE ESTA TELA RESPONDE. A matriz de risco corporativo da Aegea tem 32 riscos
em 8 clusters, com severidade atribuída pela própria companhia. O cadastro de
assuntos liga cada tema (N3) aos riscos que ele toca — 100 dos 104 temas ativos.
Juntando as duas coisas, tudo o que entra na plataforma por assunto passa a
poder ser lido por RISCO, que é a língua em que a diretoria decide.

UM INCIDENTE É UM FATO NEGATIVO SOBRE UM ASSUNTO QUE TOCA RISCO — decisão do
dono do produto, 10/10/2026. Nas fontes de menção é a menção de sentimento
negativo; no CRM é a agenda de clima negativo (`clima.codigo = 'tenso'`), que é
o equivalente que existe ali — `interacao` não tem coluna de sentimento, tem
clima. Medido na base: 84 agendas de clima negativo tocam tema com risco.

POR QUE NÃO É TODA MENÇÃO. "Sem incidente" é a informação mais útil da matriz:
risco que ninguém citou negativamente no período. Contando toda menção, a frase
viraria "risco que ninguém citou", e um risco muito falado de forma positiva
apareceria como o mais quente da tela.

O ÍNDICE PESA A SEVERIDADE. Dez reclamações sobre um risco moderado não valem o
mesmo que dez sobre um crítico — e a matriz da Aegea já decidiu quais são
quais. O índice é a soma dos incidentes do mês com o peso da severidade,
reduzida à escala de 0 a 100 pelo pico da série.

E ESSA ESCALA TEM UMA PROPRIEDADE QUE PRECISA ESTAR ESCRITA: 100 é o pior mês
JÁ MEDIDO. Enquanto nenhum mês superar o pico, a série não se move; no dia em
que um mês pior entrar, a série inteira se reescala para baixo — o passado
"melhora" sem nada ter mudado nele. É o preço de não ter uma referência fixa
cadastrada, e a saída, se incomodar, é fixar a referência no cadastro em vez de
recalculá-la. A resposta da API devolve a referência e o mês dela justamente
para a tela poder dizer o que 100 significa.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

#: QUANTO CADA SEVERIDADE PESA no índice.
#:
#: Três níveis porque são os três da matriz da Aegea, e a proporção é a mais
#: simples que preserva a ordem: um crítico vale três moderados. Qualquer escala
#: aqui é convenção — o que não é convenção é a ORDEM, que vem do cadastro.
#:
#: NÃO DERIVADO: a severidade é atribuída pela companhia em `risco.severidade`,
#: não calculada a partir do volume. Ver `migrations/0059`.
PESO_DA_SEVERIDADE: dict[str, int] = {
    "critico": 3,
    "alto": 2,
    "moderado": 1,
}

#: A ORDEM DE LEITURA das severidades — do pior para o menos grave. A tela
#: empilha e colore por ela, e um `sorted()` alfabético poria "alto" antes de
#: "critico".
SEVERIDADES: tuple[str, ...] = ("critico", "alto", "moderado")

#: AS FAIXAS DA ESCALA, que o protótipo desenha como zonas de fundo.
#:
#: Em pontos do índice, do limite INFERIOR de cada faixa. Dois terços e um terço
#: da escala: a divisão que não finge precisão que não existe. Elas não mudam o
#: cálculo — são leitura, e por isso moram aqui, perto do que as produz.
FAIXAS_DO_INDICE: tuple[tuple[str, int], ...] = (
    ("critico", 67),
    ("alto", 34),
    ("moderado", 0),
)


def peso_da_severidade(severidade: str | None) -> int:
    """O peso de uma severidade, e 0 para o que o cadastro não conhece.

    ZERO, E NÃO UM: severidade que a plataforma não reconhece não pode entrar no
    índice com o peso do menos grave — isso inventaria gravidade a partir de um
    valor que ninguém cadastrou. Ela aparece na matriz (o incidente existe) e
    não move o índice, que é o estado honesto de "não sei quanto isso pesa".
    """
    return PESO_DA_SEVERIDADE.get((severidade or "").strip().lower(), 0)


def faixa_do_indice(indice: int | None) -> str | None:
    """Em que faixa um valor do índice cai — `critico`, `alto` ou `moderado`."""
    if indice is None:
        return None
    for nome, piso in FAIXAS_DO_INDICE:
        if indice >= piso:
            return nome
    return "moderado"


@dataclass(frozen=True, slots=True)
class MesDeRisco:
    """Um mês da série do índice, com o que o compõe.

    `pesado` é a soma dos incidentes pelo peso da severidade — o número cru, do
    qual o índice é a redução à escala. Vai na resposta porque é o que permite
    recalcular ou conferir o índice sem refazer a consulta.
    """

    mes: str
    incidentes: int
    pesado: int
    indice: int | None = None
    #: ESTE MÊS ESTÁ NA JANELA que a pessoa escolheu na tela?
    #:
    #: A SÉRIE VEM INTEIRA e a janela MARCA, em vez de cortar — é o que o
    #: protótipo desenha: "barras esmaecidas ficam fora da janela selecionada".
    #: Cortar deixaria o gráfico sem o contexto de onde o período escolhido cai
    #: na história, que é metade do que uma série temporal tem para dizer.
    #:
    #: Achado de revisão: a janela saía do cálculo da referência (certo) e
    #: também dos meses devolvidos (errado, e silencioso — a tela mostrava a
    #: série inteira sem saber que parte dela estava fora do pedido).
    na_janela: bool = True
    #: AS FONTES QUE ALIMENTARAM ESTE MÊS, pelos códigos do cadastro.
    #:
    #: Está aqui porque sem isso o gráfico mente por omissão ENQUANTO A BASE
    #: ESTÁ INCOMPLETA: medido em 10/10/2026, o índice de jan a jul fica entre 0
    #: e 9 e agosto e setembro em 75 e 100 — e a razão não é o risco ter
    #: explodido, é que jan a jul só têm Bites e a Clipei (25 mil menções)
    #: começa em agosto.
    #:
    #: É ESTADO DE TRANSIÇÃO, e não defeito do índice: o dono do produto vai
    #: subir as bases de todos os meses. Por isso o campo é um AVISO e não uma
    #: correção — nada aqui tenta compensar a fonte que falta, o que inventaria
    #: incidente que ninguém mediu. Quando todo mês tiver todas as fontes, ele
    #: passa a dizer sempre a mesma coisa e sai da tela sozinho.
    fontes: tuple[str, ...] = ()
    #: QUANTOS INCIDENTES DE CADA SEVERIDADE, na ordem da gravidade.
    #:
    #: A BARRA DO MÊS É EMPILHADA por severidade, e a dica do mês mostra os três
    #: números — é o bloco principal da tela. O total sozinho não permitiria
    #: desenhar nem um nem outro, e derivar a divisão do `pesado` seria
    #: impossível: 6 pontos são dois críticos, três altos ou seis moderados.
    #:
    #: UMA TUPLA DE PARES e não um dicionário, para a ordem ser a da gravidade e
    #: não a de inserção da consulta — a pilha da barra tem de sair igual em
    #: todos os meses.
    por_severidade: tuple[tuple[str, int], ...] = ()
    #: QUANTOS PONTOS DE CADA SEVERIDADE — a contagem já pelo peso.
    #:
    #: A ALTURA DA BARRA É O ÍNDICE, que é ponderado: dividi-la pela CONTAGEM
    #: faria um mês de um crítico e três moderados aparecer 25/75 quando o peso
    #: é 50/50, e as fatias não somariam a altura. A tela precisa das duas
    #: coisas — o peso para empilhar, a contagem para a dica dizer "2
    #: incidentes" —, e mandar o peso daqui evita uma segunda cópia da régua no
    #: navegador, que divergiria no primeiro ajuste de calibração.
    pesado_por_severidade: tuple[tuple[str, int], ...] = ()


def com_o_indice(meses: list[MesDeRisco]) -> tuple[list[MesDeRisco], int, str | None]:
    """A série com o índice calculado, mais a referência e o mês dela.

    A REFERÊNCIA É O MAIOR `pesado` DA SÉRIE, e ela vale 100. Devolvida junto
    porque a tela precisa dizer o que 100 significa — sem isso, "índice 32" é um
    número sem unidade.

    SÉRIE SEM INCIDENTE NENHUM devolve índice zero em todos os meses, e não uma
    divisão por zero: mês sem incidente é informação, não falha.
    """
    referencia = max((mes.pesado for mes in meses), default=0)
    if referencia <= 0:
        return ([replace(mes, indice=0) for mes in meses], 0, None)

    do_pico = next(mes.mes for mes in meses if mes.pesado == referencia)
    return (
        [
            #: POR `replace`, E NÃO RECONSTRUINDO POR POSIÇÃO: a construção
            #: posicional calava quando o mês ganhava um campo novo — o campo
            #: voltava ao padrão, e nada reclamava. Foi o que aconteceu ao
            #: acrescentar `por_severidade`.
            replace(
                mes,
                #: ARREDONDAMENTO PARA O INTEIRO MAIS PRÓXIMO: a escala é de
                #: leitura, e um índice com casa decimal sugere uma precisão que
                #: a contagem de incidentes não tem.
                indice=round(100 * mes.pesado / referencia),
            )
            for mes in meses
        ],
        referencia,
        do_pico,
    )


def variacao(serie: list[MesDeRisco], meses_atras: int = 1) -> int | None:
    """A diferença do índice do último mês contra o de `meses_atras` antes.

    O protótipo chama de "Variação em 30 dias" e a série é MENSAL: a comparação
    é com o mês anterior, e o rótulo da tela diz a data do mês comparado em vez
    de prometer trinta dias que a granularidade não tem.

    Devolve `None` quando não há mês anterior — primeira medição não tem
    variação, e zero diria que ficou estável.
    """
    if len(serie) <= meses_atras:
        return None
    atual = serie[-1].indice
    antes = serie[-1 - meses_atras].indice
    if atual is None or antes is None:
        return None
    return atual - antes
