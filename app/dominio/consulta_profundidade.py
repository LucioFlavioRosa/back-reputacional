"""A Consulta em profundidade de uma lente: Pilar › Tema › Subtema › Matérias.

O FRONT JÁ TEM A TELA, e lia um JSON ilustrativo. Este módulo monta o MESMO
formato (`Dados` de `front-reputacional/.../consulta/dados/tipos.ts`) a partir
das menções reais do mês — sem banco e sem HTTP, para cada regra ser provada
com meia dúzia de menções na mão.

UMA CONTA SÓ, EM TODOS OS NÍVEIS — a regra central do pacote das lentes:

    impacto(S) = 50 × (P_S − N_S) ÷ D_mês

P e N são os pesos (tier × régua de engajamento, `peso_da_mencao`) das
positivas e negativas do pedaço; D é o total ponderado do MÊS INTEIRO da lente,
o mesmo `score_mes_fonte` de `impacto_do_recorte`. É o denominador do mês que
faz os irmãos somarem o pai e os pilares somarem `50 × NS = nota − 50`: cada
número do drill é igual ao do recorte com o filtro equivalente, e a árvore
inteira se confere contra a nota que a tela já mostra.

ONDE CADA MENÇÃO SE PENDURA (`Taxonomia.resolver`). O vínculo relacional
(`mencao.tema_id`) a ingestão passou a gravar pela Subcategoria
(`casos_de_uso.temas_da_mencao`), mas as menções já carregadas — o mock
inteiro — não o têm, e a Subcategoria que não casa com o cadastro fica sem ele.
Por isso o texto do fornecedor continua valendo como reserva. A resolução
tenta, nesta ordem, e a primeira que casar vence:

    1. tema_id de um subtema ativo         cadeia completa N3 › N2 › N1
    2. tema_texto == nome de um subtema    a Subcategoria da Clipei é o N3
    3. subtema == nome de um subtema
    4. tema_texto == nome de um tema (N2)  N3 fica "sem subtema"
    5. sem N2: o pilar pelo ATRIBUTO (sem o prefixo "7. " do export real),
       senão pelo tema_texto == pilar (a regra antiga do filtro tema_n1),
       senão "sem pilar"

Comparando sem acento, sem caixa e com espaços colapsados (`texto.normalizar`).
Só a taxonomia ATIVA entra: os temas legados inativos ("Tarifa" id 2,
"Universalização" id 1) não têm macro e não podem pendurar ninguém.

A CADEIA VENCE O ATRIBUTO quando os dois dizem pilares diferentes: o subtema é
uma classificação mais fina que o pilar escrito à mão ao lado. As divergências
são contadas (`conferencia.divergenciasDePilar`) — no export real os dois devem
concordar, e um número alto ali é o sinal de que o de-para precisa de revisão.

OS NÓS DE FECHAMENTO ("Sem pilar identificado", "Sem tema identificado", "Sem
subtema identificado") existem para a conta fechar: sem eles, uma menção sem
vínculo sumiria da árvore e os filhos deixariam de somar o pai. Só aparecem com
volume, nunca têm filhos nem nível aberto, nunca viram destaque e nunca são
citados nas frases.
"""

from __future__ import annotations

import calendar
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.dominio import frases_da_consulta as frases
from app.dominio.score import (
    FAIXAS,
    REGUA_DE_CONTAGEM,
    REGUAS_DE_TIER,
    Calibracao,
    Tier,
    peso_da_mencao,
)
from app.dominio.tema_do_mes import PONTOS_POR_NS
from app.dominio.texto import normalizar

#: Versão do contrato. O front ilustrativo é '1.0'; esta é a primeira que sai
#: do banco, e o prefixo deixa claro de onde o JSON veio.
VERSAO = "api-1"

#: As lentes que esta consulta sabe montar. As outras três não são menções da
#: Clipei (redes, canais próprios, CRM) e não têm pilar por matéria.
LENTES_DA_CONSULTA = ("imprensa", "mercado")

#: Quem desce além do Nível 1. O Mercado tem a árvore calculada igual, mas a
#: tela dele fica no Nível 1 nesta versão (decisão D2): abrir o drill é trocar
#: esta constante, sem mexer em conta nenhuma.
LENTES_COM_DRILL = frozenset({"imprensa"})

#: Seis meses, o último é o da tela — o tamanho de `serie` e da evolução.
MESES_DA_CONSULTA = 6

SEM_PILAR = "sem-pilar"
SEM_TEMA = "sem-tema"
SEM_SUBTEMA = "sem-subtema"
NOMES_DE_FECHAMENTO = {
    SEM_PILAR: "Sem pilar identificado",
    SEM_TEMA: "Sem tema identificado",
    SEM_SUBTEMA: "Sem subtema identificado",
}

NAO_INFORMADA = "Não informada"
NAO_INFORMADO = "Não informado"
OUTRAS = "Outras"
OUTRAS_UFS = "Outras UFs"
SEM_TITULO = "(sem título na planilha)"

#: Quantas linhas cada quadro mostra antes de juntar o resto em "Outras".
TOPO_DA_CONCENTRACAO = 4
TOPO_DE_VEICULOS = 5
TOPO_DE_JORNALISTAS = 4

#: A amostra de matérias do Nível 4: até 20, das quais até 4 neutras recentes —
#: para nenhuma aba (positivas, neutras, negativas) abrir vazia quando há o que
#: mostrar nela. O universo inteiro iria em dezenas de KB por subtema.
TETO_DA_AMOSTRA = 20
NEUTRAS_NA_AMOSTRA = 4

#: Profundidade a partir da qual o nó guarda as suas menções (0 raiz, 1 pilar,
#: 2 tema, 3 subtema): o Nível 2 recorta o tema e o 3/4 recortam o subtema.
NIVEL_QUE_GUARDA = 2

#: Quanto o D do agregado pode se afastar do Σw das menções só por
#: arredondamento: `score_mes_fonte.soma_log` é numeric(14,4), meia unidade da
#: 4ª casa por linha (fonte × sentimento × tier). Com folga para dezenas de
#: linhas — uma carga que não refez o agregado erra por matérias inteiras.
TOLERANCIA_DO_AGREGADO = 5e-3

#: O tier da Clipei, como a tela o escreve.
TIER_DA_TELA: dict[str, str] = {
    Tier.MUITO_RELEVANTE: "Tier 1",
    Tier.RELEVANTE: "Tier 2",
    Tier.MENOS_RELEVANTE: "Tier 3",
}
SENTIMENTO_DA_TELA = {"pos": "positivo", "neu": "neutro", "neg": "negativo"}
SINAL = {"pos": 1, "neu": 0, "neg": -1}

#: As cinco faixas da nota, com as cores do JSON do front — que ainda chama
#: `faixaDe` com elas. OS CORTES VÊM DE `dominio.score.FAIXAS`, a mesma régua do
#: índice: copiar 85/70/55/40 aqui faria a cor da tela e a faixa do número
#: discordarem no dia em que alguém mexesse num dos dois.
_CORES_DAS_FAIXAS: dict[str, tuple[str, str, str, str]] = {
    "Referência": ("referencia", "#DFFAF6", "#06574E", "#E0F7F4"),
    "Sólido": ("solido", "#DFFAF6", "#0A6B60", "#E9FBF8"),
    "Estável": ("estavel", "#E6EAFB", "#0027BD", "#EEF1F8"),
    "Atenção": ("atencao", "#FFF1DC", "#8A4E00", "#FFF5E6"),
    "Crítico": ("critico", "#FFE7E8", "#B32328", "#FFEDEE"),
}

#: "7. X", "7) X", "7 - X", "7 – X": o número do pilar com qualquer separador
#: que um export à mão costuma ter, com ou sem espaço antes dele.
_PREFIXO_NUMERICO = re.compile(r"^\s*[0-9]+\s*[.)\-–]?\s*")
_FORA_DO_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Apresentacao:
    """O que a tela mostra da lente e não vem do banco: público, cor, fonte."""

    publico: str
    cor: str
    fonte: str
    #: "da Imprensa", "do Mercado" — o artigo muda, e "da Mercado" numa frase
    #: gerada é o tipo de erro que ninguém perdoa num painel de diretoria.
    contraida: str
    #: O segundo cartão lateral: a história do mês ou os temas de maior impacto.
    cartao: str


APRESENTACAO: dict[str, Apresentacao] = {
    "imprensa": Apresentacao(
        publico="Formadores de opinião",
        cor="#17E3CB",
        fonte="Clipei, ponderado pelo tier do veículo",
        contraida="da Imprensa",
        cartao="historia",
    ),
    "mercado": Apresentacao(
        publico="Investidores e rating",
        cor="#0027BD",
        fonte="Clipei, imprensa econômica de todos os tiers",
        contraida="do Mercado",
        cartao="divergentes",
    ),
}

FILTRO_DE_TIER = {
    "id": "tier",
    "rotulo": "Tier",
    "opcoes": ["Todos", "Tier 1", "Tier 2", "Tier 3"],
}


# -- entradas -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MencaoDaConsulta:
    """Uma linha de `mencao`, só com o que o drill usa."""

    id: str
    mes: date
    sentimento: str
    data: date | None = None
    tier: str | None = None
    engajamento: int | None = None
    cargo: str | None = None
    tema_id: int | None = None
    tema_texto: str | None = None
    subtema: str | None = None
    atributo: str | None = None
    veiculo: str | None = None
    unidade_texto: str | None = None
    uf: str | None = None
    autor: str | None = None
    titulo_texto: str | None = None
    link: str | None = None
    id_fonte: str | None = None


@dataclass(frozen=True, slots=True)
class GrupoDaConsulta:
    """`quantas` menções de um mês ANTERIOR que pesam e se penduram igual.

    OS CINCO MESES ANTES DO DA TELA SÓ ALIMENTAM AGREGADOS — o impacto de cada nó
    na evolução, o `impactoMesAnterior`, o volume. Ler as linhas cruas deles
    (título, link, autor…) custava segundos com o volume real, para jogar quase
    tudo fora. O banco agrupa pelo que decide o vínculo e o peso, e a árvore
    soma `w × quantas`: o mesmo número, com uma fração das linhas.
    """

    mes: date
    sentimento: str
    quantas: int
    tier: str | None = None
    engajamento: int | None = None
    cargo: str | None = None
    tema_id: int | None = None
    tema_texto: str | None = None
    subtema: str | None = None
    atributo: str | None = None


@dataclass(frozen=True, slots=True)
class MesDaLente:
    """O mês da lente medido por `score_mes_fonte` — a nota oficial e o D.

    `nota` É A MESMA DA TELA (inclusive a estimativa, quando o mês não tem
    medição); `ns` e `denominador` são só da contagem, e é contra eles que a
    árvore fecha.
    """

    mes: date
    regua: str
    denominador: float
    ns: float | None
    nota: int | None


@dataclass(frozen=True, slots=True)
class LenteDaConsulta:
    codigo: str
    nome: str
    #: Fração do índice (peso da calibração ÷ Σ pesos), de 0 a 1.
    peso: float


# -- a taxonomia --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PilarDaTaxonomia:
    id: int
    codigo: str
    nome: str


@dataclass(frozen=True, slots=True)
class TemaDaTaxonomia:
    """O tema estratégico (N2, `macro_tema`)."""

    id: int
    codigo: str
    nome: str
    pilar_id: int


@dataclass(frozen=True, slots=True)
class SubtemaDaTaxonomia:
    """O subtema (N3, `tema`). `tema_id` é o `macro_tema_id` dele."""

    id: int
    nome: str
    tema_id: int


@dataclass(frozen=True, slots=True)
class Vinculo:
    """Onde a menção se pendura. Vazio no nível que não existe abaixo de um
    nó de fechamento (sem-pilar não tem tema; sem-tema não tem subtema)."""

    pilar: str
    tema: str = ""
    subtema: str = ""
    #: A cadeia (passos 1 a 4) disse um pilar e o atributo disse outro.
    divergente: bool = False

    @property
    def caminho(self) -> tuple[str, ...]:
        return tuple(parte for parte in (self.pilar, self.tema, self.subtema) if parte)


def sem_prefixo(texto: str) -> str:
    """'7. Prosperidade Compartilhada' vira 'Prosperidade Compartilhada'.

    O EXPORT REAL NUMERA O PILAR (ingerir_mencoes, linha de marcadores N1/N2/N3),
    e o mock não. Sem tirar o número, nenhum atributo real casaria com o
    cadastro — e todo o mês cairia em "sem pilar" com a conta certa e a árvore
    vazia, o pior jeito de errar porque parece funcionar.
    """
    return _PREFIXO_NUMERICO.sub("", texto)


def slug(nome: str) -> str:
    """O id do N3 no estilo do `codigo` de N1/N2: ASCII, minúsculas e '_'."""
    return _FORA_DO_SLUG.sub("_", normalizar(nome)).strip("_")


class Taxonomia:
    """Os três níveis ativos, indexados para resolver cada menção.

    SÓ A CADEIA ATIVA COMPLETA: subtema ativo com tema ativo com pilar ativo. Um
    elo inativo no meio deixaria a menção num N3 sem N2 — e a tela não tem onde
    desenhar isso.
    """

    def __init__(
        self,
        pilares: Sequence[PilarDaTaxonomia],
        temas: Sequence[TemaDaTaxonomia],
        subtemas: Sequence[SubtemaDaTaxonomia],
    ) -> None:
        self.pilares: tuple[PilarDaTaxonomia, ...] = tuple(pilares)
        pilar_por_id = {p.id: p for p in self.pilares}
        self.temas: tuple[TemaDaTaxonomia, ...] = tuple(
            t for t in temas if t.pilar_id in pilar_por_id
        )
        tema_por_id = {t.id: t for t in self.temas}
        self.subtemas: tuple[SubtemaDaTaxonomia, ...] = tuple(
            s for s in subtemas if s.tema_id in tema_por_id
        )

        self._pilar_do_tema = {t.id: pilar_por_id[t.pilar_id].codigo for t in self.temas}
        self._codigo_do_tema = {t.id: t.codigo for t in self.temas}
        self.nome_do_pilar = {p.codigo: p.nome for p in self.pilares}
        self.nome_do_tema = {t.codigo: t.nome for t in self.temas}
        self.ordem_do_tema = {t.codigo: i for i, t in enumerate(self.temas)}

        # PRIMEIRO NA ORDEM DA TAXONOMIA vence um nome repetido: `macro_tema.nome`
        # não é único (só o `codigo` é), e a escolha tem de ser estável.
        self._pilar_por_nome: dict[str, str] = {}
        for p in self.pilares:
            self._pilar_por_nome.setdefault(normalizar(p.nome), p.codigo)
        self._tema_por_nome: dict[str, TemaDaTaxonomia] = {}
        for t in self.temas:
            self._tema_por_nome.setdefault(normalizar(t.nome), t)

        # O SLUG DO N3 COLIDE quando dois nomes só diferem em acento ou
        # pontuação; o primeiro por id fica com o slug limpo e os outros levam
        # o id — estável entre leituras, que é o que o endereço precisa.
        self.slug_do_subtema: dict[int, str] = {}
        usados: set[str] = set()
        for s in sorted(self.subtemas, key=lambda s: s.id):
            base = slug(s.nome) or f"subtema_{s.id}"
            self.slug_do_subtema[s.id] = base if base not in usados else f"{base}_{s.id}"
            usados.add(self.slug_do_subtema[s.id])
        self.nome_do_subtema = {self.slug_do_subtema[s.id]: s.nome for s in self.subtemas}
        self._subtema_por_id = {s.id: s for s in self.subtemas}
        self._subtema_por_nome: dict[str, SubtemaDaTaxonomia] = {}
        for s in sorted(self.subtemas, key=lambda s: s.id):
            self._subtema_por_nome.setdefault(normalizar(s.nome), s)

    def _pilar_pelo_atributo(self, atributo: str | None) -> str | None:
        if not atributo:
            return None
        return self._pilar_por_nome.get(normalizar(sem_prefixo(atributo)))

    def resolver(
        self,
        *,
        tema_id: int | None = None,
        tema_texto: str | None = None,
        subtema: str | None = None,
        atributo: str | None = None,
    ) -> Vinculo:
        """A precedência do desenho, passo a passo — ver o cabeçalho do módulo."""
        pelo_atributo = self._pilar_pelo_atributo(atributo)

        achado: SubtemaDaTaxonomia | None = None
        if tema_id is not None:
            achado = self._subtema_por_id.get(tema_id)
        if achado is None and tema_texto:
            achado = self._subtema_por_nome.get(normalizar(tema_texto))
        if achado is None and subtema:
            achado = self._subtema_por_nome.get(normalizar(subtema))
        if achado is not None:
            pilar = self._pilar_do_tema[achado.tema_id]
            return Vinculo(
                pilar=pilar,
                tema=self._codigo_do_tema[achado.tema_id],
                subtema=self.slug_do_subtema[achado.id],
                divergente=pelo_atributo is not None and pelo_atributo != pilar,
            )

        tema = self._tema_por_nome.get(normalizar(tema_texto)) if tema_texto else None
        if tema is not None:
            pilar = self._pilar_do_tema[tema.id]
            return Vinculo(
                pilar=pilar,
                tema=tema.codigo,
                subtema=SEM_SUBTEMA,
                divergente=pelo_atributo is not None and pelo_atributo != pilar,
            )

        pilar = pelo_atributo
        if pilar is None and tema_texto:
            pilar = self._pilar_por_nome.get(normalizar(tema_texto))
        if pilar is None:
            return Vinculo(pilar=SEM_PILAR)
        return Vinculo(pilar=pilar, tema=SEM_TEMA)


# -- contas puras -------------------------------------------------------------------


def maior_resto(valores: Sequence[float], alvo: float, casas: int = 1) -> list[float]:
    """Arredonda `valores` em `casas` de modo que somem exatamente `alvo`.

    É O MÉTODO DE HAMILTON (o mesmo de `pesos_efetivos`): cada valor vai para o
    piso, e as unidades que faltam vão para quem perdeu mais no corte. Arredondar
    cada irmão por si faria a tabela mostrar filhos que somam 0,1 a mais que o
    pai — o tipo de detalhe que alguém confere com a calculadora na reunião.

    `alvo` é o pai JÁ ARREDONDADO, e por isso a diferença para a soma dos pisos
    nunca passa do número de irmãos; o laço com resto cobre mesmo assim um alvo
    incoerente, em vez de devolver uma lista que não soma.
    """
    if not valores:
        return []
    escala = 10**casas
    # O `round(…, 9)` tira o ruído binário: 0,3 × 10 é 2,9999999999999996, e o
    # piso disso é 2.
    escalados = [round(v * escala, 9) for v in valores]
    pisos = [math.floor(x) for x in escalados]
    falta = round(alvo * escala) - sum(pisos)
    ordem = sorted(range(len(valores)), key=lambda i: (-(escalados[i] - pisos[i]), i))
    passo = 1 if falta >= 0 else -1
    if passo < 0:
        ordem.reverse()
    for k in range(abs(falta)):
        pisos[ordem[k % len(ordem)]] += passo
    return [p / escala for p in pisos]


def distribuicao(pos: int, neu: int, neg: int) -> dict[str, int]:
    """Porcentagens inteiras que somam 100; volume zero vale 0/0/0."""
    total = pos + neu + neg
    if total == 0:
        return {"pos": 0, "neu": 0, "neg": 0}
    p, u, n = maior_resto([pos / total * 100, neu / total * 100, neg / total * 100], 100, 0)
    return {"pos": int(p), "neu": int(u), "neg": int(n)}


def janela_de_sete_dias(total: Sequence[int]) -> tuple[int, int]:
    """Os 7 dias seguidos com mais matérias, base 1. Empate fica com a primeira."""
    dias = len(total)
    if dias <= 7:
        return 1, max(dias, 1)
    melhor, inicio = -1, 0
    for i in range(dias - 6):
        soma = sum(total[i : i + 7])
        if soma > melhor:
            melhor, inicio = soma, i
    return inicio + 1, inicio + 7


def por_dia(mencoes: Iterable[MencaoDaConsulta], mes: date) -> dict:
    """Matérias e negativas por dia do mês, com a semana de maior volume.

    SEM DATA, A MATÉRIA CAI NO DIA 1 do mês dela — a mesma `coalesce(data, mes)`
    do item e da base. Descartá-la faria o gráfico somar menos que o volume do
    subtema, e a tela mostra os dois lado a lado.
    """
    dias = calendar.monthrange(mes.year, mes.month)[1]
    total = [0] * dias
    negativas = [0] * dias
    for m in mencoes:
        dia = m.data.day if m.data and (m.data.year, m.data.month) == (mes.year, mes.month) else 1
        total[dia - 1] += 1
        if m.sentimento == "neg":
            negativas[dia - 1] += 1
    inicio, fim = janela_de_sete_dias(total)
    return {"total": total, "negativas": negativas, "destaque": {"inicio": inicio, "fim": fim}}


def amostra(itens: Sequence[dict]) -> list[dict]:
    """Até 20 matérias: as de maior |impacto| e as neutras mais recentes.

    AS TRÊS ABAS TÊM DE TER O QUE MOSTRAR quando o subtema tem o que mostrar: uma
    amostra só por |impacto| nunca traria uma neutra (impacto zero), e num mês
    muito negativo poderia não trazer a única positiva. Por isso a cota das
    neutras é separada, e a positiva e a negativa de maior impacto entram mesmo
    quando a fila delas foi ocupada pelo outro sinal.
    """

    def por_impacto(item: dict) -> tuple:
        return (-abs(item["impacto"]), item["impacto"] >= 0, item["data"], item["id"])

    neutras = sorted(
        (i for i in itens if i["sentimento"] == "neutro"),
        key=lambda i: (i["data"], i["id"]),
        reverse=True,
    )[:NEUTRAS_NA_AMOSTRA]
    com_sinal = sorted((i for i in itens if i["sentimento"] != "neutro"), key=por_impacto)
    cota = TETO_DA_AMOSTRA - len(neutras)
    escolhidas = com_sinal[:cota]
    for sentimento in ("positivo", "negativo"):
        if any(i["sentimento"] == sentimento for i in escolhidas):
            continue
        melhor = next((i for i in com_sinal if i["sentimento"] == sentimento), None)
        if melhor is None:
            continue
        if len(escolhidas) >= cota:
            # Sai a última do sinal que sobra — nunca a única do outro sinal.
            sobra = next(
                j
                for j in reversed(range(len(escolhidas)))
                if escolhidas[j]["sentimento"] != sentimento
            )
            escolhidas.pop(sobra)
        escolhidas.append(melhor)
    return sorted([*escolhidas, *neutras], key=por_impacto)


# -- a árvore -----------------------------------------------------------------------


@dataclass(slots=True)
class Agregado:
    volume: int = 0
    pos: int = 0
    neu: int = 0
    neg: int = 0
    #: P e N da fórmula; `peso` é o total ponderado (P + U + N).
    positivo: float = 0.0
    negativo: float = 0.0
    peso: float = 0.0
    tier1: int = 0

    def somar(self, sentimento: str, tier: str | None, w: float, quantas: int = 1) -> None:
        peso = w * quantas
        self.volume += quantas
        self.peso += peso
        if sentimento == "pos":
            self.pos += quantas
            self.positivo += peso
        elif sentimento == "neg":
            self.neg += quantas
            self.negativo += peso
        else:
            self.neu += quantas
        if tier == Tier.MUITO_RELEVANTE:
            self.tier1 += quantas

    def impacto(self, denominador: float) -> float:
        if not denominador:
            return 0.0
        return PONTOS_POR_NS * (self.positivo - self.negativo) / denominador


@dataclass(slots=True)
class No:
    agregado: Agregado = field(default_factory=Agregado)
    filhos: dict[str, No] = field(default_factory=dict)
    #: (menção, w) de tudo o que está abaixo deste nó — SÓ NO TEMA E NO SUBTEMA
    #: do mês da tela, os únicos que abrem recortes e matérias. Guardar a lista
    #: também na raiz e no pilar, e nos meses anteriores, era a maior parte do
    #: custo da montagem com o volume real, para listas que ninguém lia.
    mencoes: list[tuple[MencaoDaConsulta, float]] = field(default_factory=list)

    def somar(
        self,
        caminho: tuple[str, ...],
        mencao: MencaoDaConsulta | GrupoDaConsulta,
        w: float,
        *,
        guardar: bool,
        profundidade: int = 0,
    ) -> None:
        quantas = mencao.quantas if isinstance(mencao, GrupoDaConsulta) else 1
        self.agregado.somar(mencao.sentimento, mencao.tier, w, quantas)
        if guardar and profundidade >= NIVEL_QUE_GUARDA and isinstance(mencao, MencaoDaConsulta):
            self.mencoes.append((mencao, w))
        if caminho:
            self.filhos.setdefault(caminho[0], No()).somar(
                caminho[1:], mencao, w, guardar=guardar, profundidade=profundidade + 1
            )

    def no(self, *caminho: str) -> No | None:
        atual: No | None = self
        for parte in caminho:
            atual = atual.filhos.get(parte) if atual else None
        return atual


def montar_arvore(
    mencoes: Iterable[MencaoDaConsulta | GrupoDaConsulta],
    vinculo_de: Callable[[MencaoDaConsulta | GrupoDaConsulta], Vinculo],
    peso_de: Callable[[MencaoDaConsulta | GrupoDaConsulta], float],
    *,
    guardar: bool = True,
) -> No:
    raiz = No()
    for mencao in mencoes:
        raiz.somar(vinculo_de(mencao).caminho, mencao, peso_de(mencao), guardar=guardar)
    return raiz


def _ordem_dos_filhos(chaves: Iterable[str], ordem: Callable[[str], tuple]) -> list[str]:
    """Os identificados na ordem dada, e o nó de fechamento sempre por último."""
    return sorted(chaves, key=lambda k: (k.startswith("sem-"), ordem(k)))


def arredondar_arvore(
    raiz: No, denominador: float, pilares: Sequence[str]
) -> dict[tuple[str, ...], float]:
    """O impacto de cada nó em 1 casa, com irmãos que somam o pai.

    OS PILARES SOMAM `round(50 × NS, 1)` — o valor exato da raiz, que é o que a
    tela compara com `nota − 50`. Cada nível abaixo recebe como alvo o pai já
    arredondado, e por isso o fechamento vale em toda a descida, e não só no
    primeiro degrau.
    """
    saida: dict[tuple[str, ...], float] = {}

    def descer(no: No, prefixo: tuple[str, ...], chaves: list[str], alvo: float) -> None:
        exatos = [
            no.filhos[k].agregado.impacto(denominador) if k in no.filhos else 0.0 for k in chaves
        ]
        for chave, valor in zip(chaves, maior_resto(exatos, alvo), strict=True):
            saida[(*prefixo, chave)] = valor
            filho = no.filhos.get(chave)
            if filho is not None and filho.filhos:
                descer(filho, (*prefixo, chave), sorted(filho.filhos), valor)

    chaves = list(pilares) + sorted(k for k in raiz.filhos if k not in pilares)
    descer(raiz, (), chaves, round(raiz.agregado.impacto(denominador), 1))
    return saida


def _impacto_exato(mencoes: Iterable[tuple[MencaoDaConsulta, float]], denominador: float) -> float:
    if not denominador:
        return 0.0
    return PONTOS_POR_NS * sum(SINAL.get(m.sentimento, 0) * w for m, w in mencoes) / denominador


def _agrupar(
    mencoes: Iterable[tuple[MencaoDaConsulta, float]],
    chave: Callable[[MencaoDaConsulta], object],
) -> dict[object, list[tuple[MencaoDaConsulta, float]]]:
    grupos: dict[object, list[tuple[MencaoDaConsulta, float]]] = {}
    for m, w in mencoes:
        grupos.setdefault(chave(m), []).append((m, w))
    return grupos


def _topo_com_outras(
    grupos: dict[object, list[tuple[MencaoDaConsulta, float]]],
    denominador: float,
    alvo: float,
    rotulo_outras: str,
    linha: Callable[[object], dict],
) -> list[dict]:
    """Os 4 de maior volume e o resto junto, com impactos que somam `alvo`."""
    ordenados = sorted(
        grupos.items(),
        key=lambda kv: (-len(kv[1]), -abs(_impacto_exato(kv[1], denominador)), str(kv[0])),
    )
    topo = ordenados[:TOPO_DA_CONCENTRACAO]
    resto = [par for _, lista in ordenados[TOPO_DA_CONCENTRACAO:] for par in lista]
    linhas = [(linha(chave), lista) for chave, lista in topo]
    if resto:
        linhas.append(({"nome": rotulo_outras}, resto))
    exatos = [_impacto_exato(lista, denominador) for _, lista in linhas]
    saida = []
    for (base, lista), valor in zip(linhas, maior_resto(exatos, alvo), strict=True):
        saida.append({**base, "volume": len(lista), "impacto": valor})
    return saida


def _mais_frequente(valores: Iterable[str]) -> str:
    contagem = Counter(valores)
    return min(contagem, key=lambda v: (-contagem[v], v)) if contagem else ""


def _no_saida(
    id_: str, nome: str, agregado: Agregado, impacto: float, anterior: float | None
) -> dict:
    saida = {
        "id": id_,
        "nome": nome,
        "volume": agregado.volume,
        "sentimento": distribuicao(agregado.pos, agregado.neu, agregado.neg),
        "impacto": impacto,
    }
    if anterior is not None:
        saida["impactoMesAnterior"] = anterior
    return saida


def _destaque(filhos: Sequence[dict]) -> dict | None:
    """O de maior |impacto|, desempate por volume — o primeiro dos maiores, como
    o `reduce` do teste de invariantes do front. Nós sem-* não concorrem."""
    melhor = None
    for filho in filhos:
        if filho["id"].startswith("sem-"):
            continue
        if melhor is None:
            melhor = filho
            continue
        dif = abs(filho["impacto"]) - abs(melhor["impacto"])
        if dif > 1e-9 or (abs(dif) <= 1e-9 and filho["volume"] > melhor["volume"]):
            melhor = filho
    return melhor


def _demais_identificados(filhos: Sequence[dict], destaque: dict) -> list[float]:
    """O impacto dos irmãos IDENTIFICADOS do destaque. Os sem-* ficam fora:
    "os demais temas" não pode ser, às escondidas, "Sem tema identificado"."""
    return [
        f["impacto"] for f in filhos if f is not destaque and not f["id"].startswith("sem-")
    ]


def _unico_oposto(filhos: Sequence[dict], impacto_do_pai: float) -> dict | None:
    identificados = [f for f in filhos if not f["id"].startswith("sem-")]
    if len(identificados) < 2 or abs(impacto_do_pai) < frases.QUASE_ZERO:
        return None
    opostos = [
        f
        for f in identificados
        if abs(f["impacto"]) >= frases.QUASE_ZERO and (f["impacto"] > 0) != (impacto_do_pai > 0)
    ]
    return opostos[0] if len(opostos) == 1 else None


def _unico_do_sentido(filhos: Sequence[dict], impacto_do_pai: float) -> dict | None:
    """O único subtema positivo (ou negativo) entre dois ou mais identificados.

    O SENTIDO CONTRÁRIO AO DO PAI É PERGUNTADO PRIMEIRO: num tema que pressiona,
    "o único positivo" é a notícia; "o único negativo" só vale quando não há ela.
    """
    identificados = [f for f in filhos if not f["id"].startswith("sem-")]
    if len(identificados) < 2:
        return None
    primeiro = 1 if impacto_do_pai < 0 else -1
    for sentido in (primeiro, -primeiro):
        do_sentido = [f for f in identificados if f["impacto"] * sentido >= frases.QUASE_ZERO]
        if len(do_sentido) == 1:
            return do_sentido[0]
    return None


# -- a montagem ---------------------------------------------------------------------


@dataclass(slots=True)
class _Contexto:
    """O que toda a descida precisa saber, para não passar doze parâmetros."""

    lente: LenteDaConsulta
    apresentacao: Apresentacao
    taxonomia: Taxonomia
    calibracao: Calibracao
    mes: date
    meses: list[date]
    arvores: dict[date, No]
    arredondados: dict[date, dict[tuple[str, ...], float]]
    denominador: float
    regua: str
    ve_diretorio: bool
    drill: bool

    @property
    def mes_anterior(self) -> date:
        return self.meses[-2]

    @property
    def nome_do_mes(self) -> str:
        return frases.nome_do_mes(self.mes)

    @property
    def nome_do_mes_anterior(self) -> str:
        return frases.nome_do_mes(self.mes_anterior)

    def anterior(self, caminho: tuple[str, ...]) -> float | None:
        """O mesmo nó no mês anterior, com o D daquele mês.

        UMA REGRA SÓ PARA OS TRÊS NÍVEIS, a mesma da evolução: se o mês anterior
        teve matéria, o nó que não apareceu nele vale 0,0 — "ninguém falou disso
        em julho" é um zero, e a evolução já o mostra assim. Só um mês anterior
        SEM BASE NENHUMA deixa o campo de fora: aí não há com o que comparar.
        """
        if self.arvores[self.mes_anterior].agregado.volume == 0:
            return None
        return self.arredondados[self.mes_anterior].get(caminho, 0.0)

    def nome(self, nivel: int, chave: str) -> str:
        if chave in NOMES_DE_FECHAMENTO:
            return NOMES_DE_FECHAMENTO[chave]
        if nivel == 1:
            return self.taxonomia.nome_do_pilar[chave]
        if nivel == 2:
            return self.taxonomia.nome_do_tema[chave]
        return self.taxonomia.nome_do_subtema[chave]

    def item(self, mencao: MencaoDaConsulta, w: float) -> dict | None:
        """A matéria como a lista do Nível 4 a mostra. Sem tier, fica fora:
        a tela não tem como escrevê-la (o tipo `Tier` é fechado)."""
        tier = TIER_DA_TELA.get(mencao.tier or "")
        if tier is None:
            return None
        impacto = (
            PONTOS_POR_NS * w * SINAL.get(mencao.sentimento, 0) / self.denominador
            if self.denominador
            else 0.0
        )
        return {
            "id": mencao.id,
            "data": (mencao.data or mencao.mes).isoformat(),
            "veiculo": mencao.veiculo or NAO_INFORMADO,
            # O AUTOR É GENTE DE FORA, guardado pela mesma permissão do
            # diretório — ver `obter_dossie`. Sem ela, a coluna vem vazia.
            "jornalista": (mencao.autor or "") if self.ve_diretorio else "",
            "tier": tier,
            "sentimento": SENTIMENTO_DA_TELA.get(mencao.sentimento, "neutro"),
            "concessionaria": mencao.unidade_texto or NAO_INFORMADA,
            "uf": mencao.uf or NAO_INFORMADA,
            "titulo": mencao.titulo_texto or SEM_TITULO,
            "trecho": "",
            "url": mencao.link or None,
            "impacto": round(impacto, 2),
        }


def _nivel4(ctx: _Contexto, no: No, nome: str, impacto: float) -> dict:
    mencoes = no.mencoes
    itens = [i for i in (ctx.item(m, w) for m, w in mencoes) if i is not None]
    escolhidas = amostra(itens)
    dias = por_dia((m for m, _ in mencoes), ctx.mes)
    inicio, fim = dias["destaque"]["inicio"], dias["destaque"]["fim"]
    na_janela = sum(dias["total"][inicio - 1 : fim])
    volume = no.agregado.volume

    com_sinal = sorted(
        (i for i in itens if i["sentimento"] != "neutro"),
        key=lambda i: (-abs(i["impacto"]), i["impacto"] >= 0, i["data"], i["id"]),
    )
    tier1_no_topo = 0
    for i in com_sinal:
        if i["tier"] != "Tier 1":
            break
        tier1_no_topo += 1
    # "A DE MAIOR IMPACTO" SÓ SE TEVE IMPACTO: na régua só-Tier-1, uma positiva
    # de Tier 2 vale zero, e citá-la como "a positiva de maior impacto" seria
    # afirmar um efeito que a lista ao lado mostra como 0,00.
    com_impacto = [i for i in com_sinal if i["impacto"] != 0]
    positiva = next((i for i in com_impacto if i["sentimento"] == "positivo"), None)
    negativa = next((i for i in com_impacto if i["sentimento"] == "negativo"), None)

    # UM VALOR ÚNICO PARA O TIER 1 SÓ EXISTE NA RÉGUA DE CONTAGEM: nas de
    # engajamento ou cargo cada matéria pesa diferente (e o w de uma menção sem
    # engajamento seria 0 no 'bruto'), e a frase cai no texto sem número.
    valor_tier1: float | None = None
    if ctx.regua == REGUA_DE_CONTAGEM:
        w_tier1 = peso_da_mencao(Tier.MUITO_RELEVANTE, None, None, ctx.calibracao, ctx.regua)
        valor_tier1 = PONTOS_POR_NS * w_tier1 / ctx.denominador if ctx.denominador else 0.0
    return {
        "leitura": frases.leitura_das_materias(
            pct_na_janela=round(na_janela / volume * 100) if volume else 0,
            dia_inicial=inicio,
            dia_final=fim,
            mes=ctx.nome_do_mes,
            tier1_no_topo=tier1_no_topo,
            positiva_de_maior_impacto=date.fromisoformat(positiva["data"]) if positiva else None,
        ),
        "tituloLista": frases.titulo_da_lista(
            subtema=nome,
            mes=ctx.nome_do_mes,
            volume=volume,
            negativas=no.agregado.neg,
            tier1_no_topo=tier1_no_topo,
            negativa_de_maior_impacto=date.fromisoformat(negativa["data"]) if negativa else None,
        ),
        "subtituloLista": frases.subtitulo_da_lista(
            lente_contraida=ctx.apresentacao.contraida,
            valor_tier1=valor_tier1,
            mostradas=len(escolhidas),
            volume=volume,
        ),
        "porDia": dias,
        "itens": escolhidas,
    }


def _linhas_ordenadas_no_sentido(
    grupos: dict[object, list[tuple[MencaoDaConsulta, float]]],
    denominador: float,
    sentido_negativo: bool,
    quantos: int,
) -> list[tuple[object, list[tuple[MencaoDaConsulta, float]], float]]:
    """Os grupos de maior impacto NO SENTIDO do subtema: num subtema que pressiona,
    o veículo que mais tirou vem primeiro; o que mais pôs vai para o fim."""
    linhas = [(k, lista, _impacto_exato(lista, denominador)) for k, lista in grupos.items()]
    linhas.sort(key=lambda x: (x[2] if sentido_negativo else -x[2], -len(x[1]), str(x[0])))
    return linhas[:quantos]


def _nivel3(ctx: _Contexto, caminho: tuple[str, str], tema_no: No, tema_saida: dict) -> dict:
    filhos = tema_saida["filhos"]
    destaque = _destaque(filhos)
    assert destaque is not None  # só se chama com ≥ 1 subtema identificado
    sub_no = tema_no.filhos[destaque["id"]]
    sub_imp_exato = sub_no.agregado.impacto(ctx.denominador)
    sub_imp = destaque["impacto"]
    mencoes = sub_no.mencoes
    d = ctx.denominador

    # -- tiers: os três sempre, e "Sem tier" só se houver, para a soma fechar.
    por_tier = _agrupar(mencoes, lambda m: TIER_DA_TELA.get(m.tier or ""))
    chaves_tier: list[str | None] = ["Tier 1", "Tier 2", "Tier 3"]
    if None in por_tier:
        chaves_tier.append(None)
    exatos = [_impacto_exato(por_tier.get(k, []), d) for k in chaves_tier]
    linhas_tier = []
    for k, valor in zip(chaves_tier, maior_resto(exatos, sub_imp), strict=True):
        base = {"tier": k} if k else {"nome": "Sem tier"}
        # "Sem tier" vai com `nome` e sem `tier` (o tipo Tier da tela é fechado).
        # A linha fica para os impactos somarem o subtema.
        linhas_tier.append({**base, "volume": len(por_tier.get(k, [])), "impacto": valor})
    tier1 = por_tier.get("Tier 1", [])
    tier1_volume_pct = round(len(tier1) / sub_no.agregado.volume * 100) if tier1 else None
    tier1_impacto_pct = frases.pct(_impacto_exato(tier1, d), sub_imp_exato) if tier1 else None
    pesos = REGUAS_DE_TIER[ctx.calibracao.regua_tier]

    # -- concessionárias: o par (concessionária, UF), topo 4 + Outras.
    pares = _agrupar(mencoes, lambda m: (m.unidade_texto or NAO_INFORMADA, m.uf or NAO_INFORMADA))
    linhas_conc = _topo_com_outras(
        pares,
        d,
        sub_imp,
        OUTRAS,
        lambda k: {"nome": k[0], "uf": k[1]},  # type: ignore[index]
    )

    # -- veículos: os 5 de maior impacto no sentido do subtema.
    negativo = sub_imp_exato < 0
    veiculos = _linhas_ordenadas_no_sentido(
        _agrupar(mencoes, lambda m: m.veiculo or NAO_INFORMADO), d, negativo, TOPO_DE_VEICULOS
    )
    linhas_veic = []
    for nome, lista, valor in veiculos:
        linha: dict = {"nome": nome}
        # VEÍCULO SEM TIER NENHUM FICA SEM O CAMPO (é opcional na tela), em vez
        # de ganhar um "Tier 3" que a fonte nunca disse.
        tier = _mais_frequente(TIER_DA_TELA[m.tier] for m, _ in lista if m.tier in TIER_DA_TELA)
        if tier:
            linha["tier"] = tier
        linha.update(
            volume=len(lista),
            negativas=sum(1 for m, _ in lista if m.sentimento == "neg"),
            impacto=round(valor, 1),
        )
        linhas_veic.append(linha)

    # -- jornalistas: só com autor no dado e com acesso ao diretório.
    com_autor = [(m, w) for m, w in mencoes if m.autor]
    if not ctx.ve_diretorio:
        linhas_jorn: list[dict] = []
        titulo_jorn = frases.TITULO_DOS_JORNALISTAS_RESTRITO
    else:
        jornalistas = _linhas_ordenadas_no_sentido(
            _agrupar(com_autor, lambda m: m.autor), d, negativo, TOPO_DE_JORNALISTAS
        )
        linhas_jorn = [
            {
                "nome": nome,
                "veiculo": _mais_frequente(m.veiculo for m, _ in lista if m.veiculo),
                "volume": len(lista),
                "negativas": sum(1 for m, _ in lista if m.sentimento == "neg"),
                "impacto": round(valor, 1),
            }
            for nome, lista, valor in jornalistas
        ]
        titulo_jorn = frases.titulo_dos_jornalistas(
            [(j["nome"], j["negativas"]) for j in linhas_jorn],
            sub_no.agregado.neg,
            ha_autor=bool(com_autor),
        )

    unico = _unico_do_sentido(filhos, tema_saida["impacto"])
    demais = _demais_identificados(filhos, destaque)

    return {
        "leitura": frases.leitura_do_tema(
            subtema=destaque["nome"],
            impacto_do_subtema=sub_imp,
            impacto_do_tema=tema_saida["impacto"],
            volume_do_subtema=destaque["volume"],
            mes=ctx.nome_do_mes,
            tier1_volume_pct=tier1_volume_pct,
            tier1_impacto_pct=tier1_impacto_pct,
            veiculos=[v["nome"] for v in linhas_veic if abs(v["impacto"]) >= frases.QUASE_ZERO],
            unico=(unico["nome"], unico["impacto"]) if unico else None,
            subtemas_identificados=len(demais) + 1,
        ),
        "tituloTabela": frases.titulo_da_tabela_de_filhos(
            destaque=destaque["nome"],
            impacto_do_destaque=sub_imp,
            impacto_do_pai=tema_saida["impacto"],
            demais=demais,
            filho="subtema",
            pai="tema",
            nome_do_pai=tema_saida["nome"],
        ),
        "subtituloTabela": frases.subtitulo_da_tabela_de_subtemas(
            tema_saida["nome"], ctx.apresentacao.contraida
        ),
        "destaque": {
            "subtemaId": destaque["id"],
            "titulo": frases.titulo_do_destaque_do_subtema(
                destaque["nome"],
                sub_no.agregado.volume,
                sub_no.agregado.neg,
                tier1_volume_pct,
                tier1_impacto_pct,
            ),
            "subtitulo": frases.subtitulo_do_destaque_do_subtema(
                sub_no.agregado.volume, sub_no.agregado.neg, ctx.apresentacao.contraida
            ),
            "tiers": {
                "titulo": frases.titulo_dos_tiers(
                    pesos[Tier.MUITO_RELEVANTE], pesos[Tier.MENOS_RELEVANTE]
                ),
                "linhas": linhas_tier,
            },
            "concessionarias": {
                "titulo": frases.titulo_das_concessionarias_do_subtema(
                    [
                        (k[0], k[1], len(lista), _impacto_exato(lista, d))  # type: ignore[index]
                        for k, lista in pares.items()
                    ],
                    sub_no.agregado.volume,
                    sub_imp_exato,
                    NAO_INFORMADA,
                ),
                "linhas": linhas_conc,
            },
            "veiculos": {
                "titulo": frases.titulo_dos_veiculos(
                    [(v["nome"], v["impacto"]) for v in linhas_veic], sub_imp
                ),
                "linhas": linhas_veic,
            },
            "jornalistas": {"titulo": titulo_jorn, "linhas": linhas_jorn},
        },
    }


def _subtemas(ctx: _Contexto, caminho: tuple[str, str], tema_no: No) -> list[dict]:
    saida = []
    nomes = ctx.taxonomia.nome_do_subtema
    for chave in _ordem_dos_filhos(tema_no.filhos, lambda k: (normalizar(nomes.get(k, k)),)):
        no = tema_no.filhos[chave]
        cam = (*caminho, chave)
        nome = ctx.nome(3, chave)
        impacto = ctx.arredondados[ctx.mes][cam]
        sub = _no_saida(chave, nome, no.agregado, impacto, ctx.anterior(cam))
        if chave != SEM_SUBTEMA and no.agregado.volume > 0:
            sub["contagens"] = {
                "pos": no.agregado.pos,
                "neu": no.agregado.neu,
                "neg": no.agregado.neg,
            }
            sub["tier1"] = no.agregado.tier1
            sub["nivel4"] = _nivel4(ctx, no, nome, impacto)
        saida.append(sub)
    return saida


def _evolucao(ctx: _Contexto, caminho: tuple[str, str], nome: str) -> dict:
    impactos = [ctx.arredondados[m].get(caminho, 0.0) for m in ctx.meses]
    volumes = []
    for m in ctx.meses:
        no = ctx.arvores[m].no(*caminho)
        volumes.append(no.agregado.volume if no else 0)
    return {
        "titulo": frases.titulo_da_evolucao(nome, impactos, volumes, ctx.nome_do_mes_anterior),
        "subtitulo": frases.subtitulo_da_evolucao(
            ctx.apresentacao.contraida, ctx.nome_do_mes, volumes
        ),
        "meses": [frases.mes_curto(m) for m in ctx.meses],
        "impactos": impactos,
        "volumes": volumes,
    }


def _nivel2(ctx: _Contexto, pilar: str, pilar_no: No, pilar_saida: dict) -> dict:
    filhos = pilar_saida["filhos"]
    destaque = _destaque(filhos)
    assert destaque is not None  # só se chama com ≥ 1 tema identificado
    caminho = (pilar, destaque["id"])
    tema_no = pilar_no.filhos[destaque["id"]]
    d = ctx.denominador
    tema_imp = destaque["impacto"]

    por_conc = _agrupar(tema_no.mencoes, lambda m: m.unidade_texto or NAO_INFORMADA)
    por_uf = _agrupar(tema_no.mencoes, lambda m: m.uf or NAO_INFORMADA)
    concessionarias = _topo_com_outras(por_conc, d, tema_imp, OUTRAS, lambda k: {"nome": k})
    ufs = _topo_com_outras(por_uf, d, tema_imp, OUTRAS_UFS, lambda k: {"nome": k})
    linhas_conc = [(str(k), len(v), _impacto_exato(v, d)) for k, v in por_conc.items()]

    informadas = sorted(
        (x for x in linhas_conc if x[0] != NAO_INFORMADA), key=lambda x: (-x[1], x[0])
    )
    concentracao = None
    if informadas and tema_no.agregado.volume:
        concentracao = (informadas[0][0], round(informadas[0][1] / tema_no.agregado.volume * 100))
    unico = _unico_oposto(filhos, pilar_saida["impacto"])
    demais = _demais_identificados(filhos, destaque)

    return {
        "leitura": frases.leitura_do_pilar(
            pilar=pilar_saida["nome"],
            impacto=pilar_saida["impacto"],
            lente_contraida=ctx.apresentacao.contraida,
            mes=ctx.nome_do_mes,
            mes_anterior=ctx.nome_do_mes_anterior,
            impacto_anterior=pilar_saida.get("impactoMesAnterior"),
            destaque=(destaque["nome"], tema_imp),
            concentracao=concentracao,
            unico_oposto=unico["nome"] if unico else None,
            temas_identificados=len(demais) + 1,
        ),
        "tituloTabela": frases.titulo_da_tabela_de_filhos(
            destaque=destaque["nome"],
            impacto_do_destaque=tema_imp,
            impacto_do_pai=pilar_saida["impacto"],
            demais=demais,
            filho="tema",
            pai="pilar",
            nome_do_pai=pilar_saida["nome"],
        ),
        "subtituloTabela": frases.subtitulo_da_tabela_de_temas(
            pilar_saida["nome"],
            ctx.apresentacao.contraida,
            tem_sem_tema=any(f["id"] == SEM_TEMA for f in filhos),
        ),
        "destaque": {
            "temaId": destaque["id"],
            "evolucao": _evolucao(ctx, caminho, destaque["nome"]),
            "concentracao": {
                "titulo": frases.titulo_da_concentracao(
                    linhas_conc, tema_no.agregado.volume, tema_no.agregado.impacto(d), NAO_INFORMADA
                ),
                "subtitulo": frases.subtitulo_da_concentracao(
                    uf_toda_nula=all(m.uf is None or m.uf == "" for m, _ in tema_no.mencoes)
                ),
                "concessionarias": concessionarias,
                "ufs": ufs,
            },
        },
    }


def _temas(ctx: _Contexto, pilar: str, pilar_no: No) -> list[dict]:
    saida = []
    ordem = ctx.taxonomia.ordem_do_tema
    for chave in _ordem_dos_filhos(pilar_no.filhos, lambda k: (ordem.get(k, 0),)):
        no = pilar_no.filhos[chave]
        cam = (pilar, chave)
        tema = _no_saida(
            chave,
            ctx.nome(2, chave),
            no.agregado,
            ctx.arredondados[ctx.mes][cam],
            ctx.anterior(cam),
        )
        if ctx.drill and chave != SEM_TEMA and any(k != SEM_SUBTEMA for k in no.filhos):
            tema["filhos"] = _subtemas(ctx, cam, no)
            tema["nivel3"] = _nivel3(ctx, cam, no, tema)
        saida.append(tema)
    return saida


def _pilares(ctx: _Contexto) -> list[dict]:
    raiz = ctx.arvores[ctx.mes]
    chaves = [p.codigo for p in ctx.taxonomia.pilares]
    if SEM_PILAR in raiz.filhos:
        chaves.append(SEM_PILAR)
    saida = []
    for chave in chaves:
        no = raiz.filhos.get(chave) or No()
        pilar = _no_saida(
            chave,
            ctx.nome(1, chave),
            no.agregado,
            ctx.arredondados[ctx.mes][(chave,)],
            ctx.anterior((chave,)),
        )
        if chave != SEM_PILAR and any(k != SEM_TEMA for k in no.filhos):
            pilar["filhos"] = _temas(ctx, chave, no)
            # SEM DRILL, A TELA FICA NO NÍVEL 1: os temas vão (o cartão dos
            # temas de maior impacto os lê), os níveis abertos não — eram a
            # maior parte do payload do Mercado para nada. Ligar o drill em
            # LENTES_COM_DRILL volta a abri-los sem mexer em conta nenhuma.
            if ctx.drill:
                pilar["nivel2"] = _nivel2(ctx, chave, no, pilar)
        saida.append(pilar)
    return saida


def _o_que_mudou(ctx: _Contexto, pilares: list[dict], nota: int | None, antes: int | None) -> dict:
    linhas = sorted(
        (
            {"rotulo": p["nome"], "valor": round(p["impacto"] - p["impactoMesAnterior"], 1)}
            for p in pilares
            if "impactoMesAnterior" in p
        ),
        key=lambda x: x["valor"],
    )
    pilar_da_nota = None
    tema_da_nota = None
    candidatos = [p for p in pilares if "impactoMesAnterior" in p and p["id"] != SEM_PILAR]
    if candidatos:
        maior = max(candidatos, key=lambda p: abs(p["impacto"] - p["impactoMesAnterior"]))
        pilar_da_nota = (maior["nome"], maior["impactoMesAnterior"], maior["impacto"])
        agora = ctx.arredondados[ctx.mes]
        antes_ = ctx.arredondados[ctx.mes_anterior]
        temas = {
            k[1]
            for k in (*agora, *antes_)
            if len(k) == 2 and k[0] == maior["id"] and not k[1].startswith("sem-")
        }
        if temas:

            def delta(t: str) -> float:
                return agora.get((maior["id"], t), 0.0) - antes_.get((maior["id"], t), 0.0)

            tema = max(
                sorted(temas, key=lambda t: ctx.taxonomia.ordem_do_tema.get(t, 0)),
                key=lambda t: abs(delta(t)),
            )
            tema_da_nota = (ctx.taxonomia.nome_do_tema[tema], round(delta(tema), 1))
    sem_base = not linhas
    return {
        "tipo": "oQueMudou",
        "rotulo": frases.rotulo_do_que_mudou(ctx.nome_do_mes_anterior),
        "titulo": frases.titulo_do_que_mudou(ctx.nome_do_mes_anterior),
        # SEM BASE NO MÊS ANTERIOR, "de" repete a nota de agora: zero linhas e
        # de = para é a única forma de o cartão não afirmar uma variação.
        "de": nota if sem_base or antes is None else antes,
        "para": nota,
        "linhas": linhas,
        "nota": frases.nota_do_que_mudou(
            mes_anterior=ctx.nome_do_mes_anterior,
            pilar=None if sem_base else pilar_da_nota,
            tema=tema_da_nota,
        ),
    }


def _historia(ctx: _Contexto, pilares: list[dict], drill: bool) -> dict | None:
    """O subtema navegável de maior |impacto| — só existe se a tela consegue
    levar até ele (pilar com filhos numa lente com drill)."""
    if not drill:
        return None
    candidatos = [
        (p, t, s)
        for p in pilares
        for t in p.get("filhos", [])
        if "nivel3" in t
        for s in t.get("filhos", [])
        if "nivel4" in s and s["nivel4"]["itens"]
    ]
    if not candidatos:
        return None
    p, t, s = max(candidatos, key=lambda c: (abs(c[2]["impacto"]), c[2]["volume"]))
    n4 = s["nivel4"]
    inicio, fim = n4["porDia"]["destaque"]["inicio"], n4["porDia"]["destaque"]["fim"]
    na_janela = sum(n4["porDia"]["total"][inicio - 1 : fim])
    item = n4["itens"][0]  # a amostra já sai na ordem de |impacto|
    # O DIA DA MATÉRIA ÚNICA vem do porDia, que põe a sem data no dia 1 — o
    # mesmo dia que o gráfico ao lado mostra.
    dias_com_materia = [i + 1 for i, n in enumerate(n4["porDia"]["total"]) if n]
    publicada_em = (
        date(ctx.mes.year, ctx.mes.month, dias_com_materia[0])
        if s["volume"] == 1 and dias_com_materia
        else None
    )
    return {
        "tipo": "historia",
        "rotulo": "A história do mês",
        "titulo": s["nome"],
        "texto": frases.texto_da_historia(
            volume=s["volume"],
            mes=ctx.nome_do_mes,
            pct_na_janela=round(na_janela / s["volume"] * 100) if s["volume"] else 0,
            dia_inicial=inicio,
            dia_final=fim,
            impacto=s["impacto"],
            publicada_em=publicada_em,
        ),
        "metricas": [
            {"valor": str(s["volume"]), "rotulo": "matéria" if s["volume"] == 1 else "matérias"},
            {"valor": str(s.get("tier1", 0)), "rotulo": "no Tier 1"},
            {
                "valor": frases.numero(s["impacto"]),
                "rotulo": "pontos na nota"
                if frases.pontos(s["impacto"]) == "pontos"
                else "ponto na nota",
                "negativo": s["impacto"] < 0,
            },
        ],
        "itemId": item["id"],
        "destino": {
            "lente": ctx.lente.codigo,
            "pilar": p["id"],
            "tema": t["id"],
            "subtema": s["id"],
        },
    }


def _divergentes(ctx: _Contexto, pilares: list[dict]) -> dict | None:
    """Os temas de maior |impacto| da lente — o cartão do Mercado."""
    # O TEMA DE 0,0 NÃO É "DE MAIOR IMPACTO": numa lente pequena ele entraria
    # no topo 5 só por existir, e a lista pareceria dizer que ele pesou.
    temas = [
        t
        for p in pilares
        for t in p.get("filhos", [])
        if not t["id"].startswith("sem-") and abs(t["impacto"]) >= frases.QUASE_ZERO
    ]
    if not temas:
        return None
    topo = sorted(temas, key=lambda t: (-abs(t["impacto"]), -t["volume"]))[:5]
    linhas = [{"rotulo": t["nome"], "valor": t["impacto"]} for t in topo]
    # O TOTAL É DOS MESMOS TEMAS QUE CONCORREM À LISTA — identificados e com
    # impacto —, e a frase o chama assim. Somar os sem-tema e deixar de fora os
    # pilares sem tema dava um "ganho da lente" que não era o da lente.
    sinal_negativo = topo[0]["impacto"] < 0
    total_do_sinal = sum(t["impacto"] for t in temas if (t["impacto"] < 0) == sinal_negativo)
    return {
        "tipo": "divergentes",
        "rotulo": f"Temas {ctx.apresentacao.contraida}",
        "titulo": frases.titulo_dos_divergentes(
            [(x["rotulo"], x["valor"]) for x in linhas], total_do_sinal
        ),
        "subtitulo": f"Impacto na nota {ctx.apresentacao.contraida}, em pontos.",
        "linhas": linhas,
    }


def faixas_da_tela() -> list[dict]:
    """As cinco faixas, com os cortes do índice e as cores da tela."""
    saida = []
    teto = 100
    for minimo, rotulo, _leitura in FAIXAS:
        id_, fundo, texto, fundo_grafico = _CORES_DAS_FAIXAS[rotulo]
        saida.append(
            {
                "id": id_,
                "rotulo": rotulo,
                "min": minimo,
                "max": teto,
                "fundo": fundo,
                "texto": texto,
                "fundoGrafico": fundo_grafico,
            }
        )
        teto = minimo - 1
    return saida


def peso_dos_tiers(calibracao: Calibracao) -> dict[str, float]:
    """`pesoTier` da tela — a régua vigente, nunca 10/5/1 fixos."""
    regua = REGUAS_DE_TIER[calibracao.regua_tier]
    return {TIER_DA_TELA[tier]: regua[tier] for tier in TIER_DA_TELA}


def montar_consulta(
    *,
    lente: LenteDaConsulta,
    mes: date,
    meses: Sequence[date],
    mencoes: Sequence[MencaoDaConsulta],
    medidas: dict[date, MesDaLente],
    taxonomia: Taxonomia,
    calibracao: Calibracao,
    ve_diretorio: bool = True,
    grupos: Sequence[GrupoDaConsulta] = (),
) -> dict:
    """A resposta inteira, no formato `Dados` do front, com UMA lente.

    `meses`: os 6 meses que terminam em `mes`. `mencoes`: as menções da lente
    (de fonte ligada) — as do mês da tela linha a linha; as dos meses anteriores
    podem vir assim também ou, como a rota faz, já agrupadas em `grupos`, que
    somam igual. `medidas`: o D e a nota oficial de cada mês, de
    `score_mes_fonte`.

    PILARES DE VOLUME ZERO. Havendo ao menos uma menção da lente no mês, os 7
    pilares ativos entram SEMPRE, na ordem da taxonomia — o de volume zero com
    impacto zero e sentimento 0/0/0, porque "ninguém falou de Inovação" é uma
    leitura, e a tabela que some com a linha a esconde. SEM NENHUMA MENÇÃO no mês
    a lista vem vazia (e `meta.vazio`), e o front mostra o estado vazio em vez de
    sete linhas de zeros que pareceriam um mês neutro.
    """
    meses = list(meses)
    apresentacao = APRESENTACAO[lente.codigo]
    drill = lente.codigo in LENTES_COM_DRILL

    vinculos: dict[tuple, Vinculo] = {}

    def vinculo_de(m: MencaoDaConsulta | GrupoDaConsulta) -> Vinculo:
        chave = (m.tema_id, m.tema_texto, m.subtema, m.atributo)
        if chave not in vinculos:
            vinculos[chave] = taxonomia.resolver(
                tema_id=m.tema_id, tema_texto=m.tema_texto, subtema=m.subtema, atributo=m.atributo
            )
        return vinculos[chave]

    por_mes: dict[date, list[MencaoDaConsulta]] = {m: [] for m in meses}
    for mencao in mencoes:
        if mencao.mes in por_mes:
            por_mes[mencao.mes].append(mencao)
    grupos_por_mes: dict[date, list[GrupoDaConsulta]] = {m: [] for m in meses}
    for grupo in grupos:
        if grupo.mes in grupos_por_mes and grupo.mes != mes:
            grupos_por_mes[grupo.mes].append(grupo)

    codigos = [p.codigo for p in taxonomia.pilares]
    arvores: dict[date, No] = {}
    arredondados: dict[date, dict[tuple[str, ...], float]] = {}
    for m in meses:
        medida = medidas.get(m)
        regua = medida.regua if medida else REGUA_DE_CONTAGEM
        denominador = medida.denominador if medida else 0.0

        def peso_de(x: MencaoDaConsulta | GrupoDaConsulta, regua: str = regua) -> float:
            return peso_da_mencao(x.tier, x.cargo, x.engajamento, calibracao, regua)

        arvores[m] = montar_arvore(
            [*por_mes[m], *grupos_por_mes[m]], vinculo_de, peso_de, guardar=m == mes
        )
        arredondados[m] = arredondar_arvore(arvores[m], denominador, codigos)

    medida = medidas.get(mes)
    denominador = medida.denominador if medida else 0.0
    nota = medida.nota if medida else None
    antes = medidas[meses[-2]].nota if meses[-2] in medidas else None
    raiz = arvores[mes]
    vazio = raiz.agregado.volume == 0

    ctx = _Contexto(
        lente=lente,
        apresentacao=apresentacao,
        taxonomia=taxonomia,
        calibracao=calibracao,
        mes=mes,
        meses=meses,
        arvores=arvores,
        arredondados=arredondados,
        denominador=denominador,
        regua=medida.regua if medida else REGUA_DE_CONTAGEM,
        ve_diretorio=ve_diretorio,
        drill=drill,
    )

    pilares = [] if vazio else _pilares(ctx)
    cartoes: list[dict] = []
    if not vazio:
        cartoes.append(_o_que_mudou(ctx, pilares, nota, antes))
        extra = (
            _historia(ctx, pilares, drill)
            if apresentacao.cartao == "historia"
            else _divergentes(ctx, pilares)
        )
        if extra is not None:
            cartoes.append(extra)

    soma_exata = raiz.agregado.impacto(denominador)
    ns50 = PONTOS_POR_NS * medida.ns if medida and medida.ns is not None else None
    sem_vinculo = {"pilar": 0, "tema": 0, "subtema": 0}
    divergencias = 0
    for mencao in por_mes[mes]:
        v = vinculo_de(mencao)
        divergencias += v.divergente
        if v.pilar == SEM_PILAR:
            sem_vinculo["pilar"] += 1
        elif v.tema == SEM_TEMA:
            sem_vinculo["tema"] += 1
        elif v.subtema == SEM_SUBTEMA:
            sem_vinculo["subtema"] += 1
    # FECHA quando as duas tabelas contam o mesmo mês: o Σw das menções é o D do
    # agregado, e então a soma dos pilares é 50 × NS por construção. Uma carga
    # direta em `mencao` sem refazer `score_mes_fonte` quebra isso, e é aqui que
    # aparece. A TOLERÂNCIA É A DO ARREDONDAMENTO DO AGREGADO (4 casas por
    # linha de `score_mes_fonte`, ver TOLERANCIA_DO_AGREGADO) e a que ela
    # propaga para 50 × NS; uma comparação exata acusaria falha na régua 'log'
    # com todos os números da tela batendo.
    tolerancia_ns = 2 * PONTOS_POR_NS * TOLERANCIA_DO_AGREGADO / denominador if denominador else 0
    fecha = (
        not vazio
        and ns50 is not None
        and abs(raiz.agregado.peso - denominador) <= TOLERANCIA_DO_AGREGADO + 1e-9 * denominador
        and abs(soma_exata - ns50) <= tolerancia_ns + 1e-6
    )
    data_corte = max(((x.data or x.mes) for x in por_mes[mes]), default=None)
    pilares_da_frase = [(p["nome"], p["impacto"]) for p in pilares if p["id"] != SEM_PILAR]

    return {
        "meta": {
            "versao": VERSAO,
            "mesReferencia": f"{mes:%Y-%m}",
            "rotuloMes": frases.rotulo_do_mes(mes),
            "mesAnterior": frases.nome_do_mes(meses[-2]),
            "dataCorte": data_corte.isoformat() if data_corte else "",
            # O SELO "Dados ilustrativos" SOME com aviso vazio: o número é o do
            # banco. `origem` diz se o mês é carga real (tem o ID do fornecedor)
            # ou o semeador de desenvolvimento, que não tem marcador próprio.
            "aviso": "",
            "meses": [frases.mes_curto(m) for m in meses],
            "vazio": vazio,
            "origem": "carga" if any(x.id_fonte for x in por_mes[mes]) else "exemplo",
            "conferencia": {
                "somaPilares": round(soma_exata, 4),
                "ns50": round(ns50, 4) if ns50 is not None else None,
                "nota": nota,
                "denominadorMencao": round(raiz.agregado.peso, 4),
                "denominadorAgregado": round(denominador, 4),
                "fecha": fecha,
                "divergenciasDePilar": divergencias,
                "semVinculo": sem_vinculo,
            },
        },
        "faixas": faixas_da_tela(),
        "pesoTier": peso_dos_tiers(calibracao),
        "lentes": [
            {
                "id": lente.codigo,
                "nome": lente.nome,
                "publico": apresentacao.publico,
                "cor": apresentacao.cor,
                "peso": round(lente.peso, 4),
                "nota": nota,
                "serie": [medidas[m].nota if m in medidas else None for m in meses],
                "fonte": apresentacao.fonte,
                "unidade": "matérias",
                "volumeTotal": raiz.agregado.volume,
                "totalPonderado": round(denominador, 4),
                "drill": drill,
                "filtroProprio": FILTRO_DE_TIER,
                "kpis": [],
                "leitura": "",
                "tabelaPilares": {
                    "titulo": frases.titulo_da_tabela_de_pilares(
                        pilares_da_frase, apresentacao.contraida, ctx.nome_do_mes
                    ),
                    "subtitulo": frases.subtitulo_da_tabela_de_pilares(
                        apresentacao.contraida,
                        ctx.nome_do_mes,
                        drill=drill,
                        tem_sem_pilar=any(p["id"] == SEM_PILAR for p in pilares),
                    ),
                },
                "pilares": pilares,
                "cartoesLaterais": cartoes,
            }
        ],
    }
