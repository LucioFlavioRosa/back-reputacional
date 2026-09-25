"""A planilha do fornecedor virando menção — sem tocar em arquivo nem em banco.

Cada fornecedor manda o mesmo fato com outro nome: a Clipei chama de
`Classificação` o que a Approach chama de `Sentimento`, e escreve `POSITIVA`
onde a Bites escreve `Positivo`. O §4 do pacote exige que um fornecedor novo
entre por CADASTRO — uma linha em `score_fonte` com o `mapeamento_colunas` —, e
não por deploy. É este módulo que cumpre a promessa: ele recebe o mapeamento
gravado e as linhas já lidas, e devolve menções no vocabulário do índice.

O que ele DELIBERADAMENTE não faz: abrir o `.xlsx` (isso é o caso de uso, que
conhece openpyxl) e gravar (isso é o repositório). O que sobra aqui é a regra
que decide se uma linha vira número — e é a única parte que precisa de teste
com linha literal, não com arquivo de exemplo.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from app.dominio.score import Sentimento, Tier, peso_do_cargo, peso_do_engajamento

#: Os campos de `mencao` que uma planilha pode alimentar. Um mapeamento que
#: cite outro nome é erro de cadastro, e não coluna ignorada em silêncio.
CAMPOS = frozenset(
    {
        "data",
        "sentimento",
        "tier",
        "engajamento",
        "cargo",
        "atributo",
        "veiculo",
        "publico_alvo",
        "tema",
        "unidade",
        "teor",
        "autor",
    }
)

#: Sem estes dois não há menção: o índice é mensal e é de sentimento.
CAMPOS_OBRIGATORIOS = frozenset({"data", "sentimento"})


def _achatar(texto: object) -> str:
    """Minúsculo, sem acento e sem espaço dobrado.

    É o que permite `POSITIVA`, `Positivo` e `positiva ` caírem no mesmo lugar
    sem uma tabela de sinônimos por fornecedor.
    """
    bruto = str(texto or "").strip()
    sem_acento = "".join(
        letra
        for letra in unicodedata.normalize("NFD", bruto)
        if unicodedata.category(letra) != "Mn"
    )
    return " ".join(sem_acento.lower().split())


#: O vocabulário dos quatro fornecedores de hoje, já achatado. Um fornecedor
#: com outra palavra a declara em `mapeamento_colunas.sentimentos`.
SENTIMENTOS: dict[str, str] = {
    "positiva": Sentimento.POSITIVO,
    "positivo": Sentimento.POSITIVO,
    "neutra": Sentimento.NEUTRO,
    "neutro": Sentimento.NEUTRO,
    "negativa": Sentimento.NEGATIVO,
    "negativo": Sentimento.NEGATIVO,
}

TIERS: dict[str, str] = {
    "muito relevante": Tier.MUITO_RELEVANTE,
    "relevante": Tier.RELEVANTE,
    "menos relevante": Tier.MENOS_RELEVANTE,
}

#: O QUE CHEGA PELO CANAL MAS NÃO É GENTE PROCURANDO A COMPANHIA.
#:
#: `Marcação` é alguém citando a Aegea num post próprio; `NPR` é o que o
#: fornecedor etiqueta como não pertinente. Juntos são 18% da base de janeiro a
#: junho — e incluí-los no denominador da taxa de resposta faz o atendimento
#: parecer 22% pior do que é.
#:
#: NÃO SÃO DESCARTADOS. A menção entra, conta no volume e aparece na tela com o
#: teor escrito; o que muda é o `acionavel`, que é o recorte de quem cobra a
#: operação. Esconder 800 mensagens para melhorar um percentual seria
#: exatamente o oposto do que esta marca existe para fazer.
TEORES_NAO_ACIONAVEIS: frozenset[str] = frozenset({"marcacao", "npr", "spam"})


class Descarte(StrEnum):
    """Por que uma linha da planilha não virou menção.

    Toda linha descartada é CONTADA e devolvida: uma ingestão que engole 1.400
    linhas caladas é indistinguível de um mapeamento errado.
    """

    FORA_DO_FILTRO = "fora_do_filtro"
    SEM_DATA = "sem_data"
    SEM_SENTIMENTO = "sem_sentimento"


@dataclass(frozen=True, slots=True)
class Mapeamento:
    """Qual coluna da planilha alimenta qual campo do índice."""

    colunas: Mapping[str, str]
    aba: str | None = None
    #: QUAL EXPORT ESTA FONTE LÊ. Duas fontes com o mesmo `arquivo` leem o
    #: mesmo anexo do fornecedor — a Clipei alimenta Imprensa e, recortada,
    #: Mercado; o export da Approach traz Social Listening e Community
    #: Management em abas diferentes do mesmo `.xlsx`. Sem isto, importar por
    #: uma das fontes deixaria a irmã com o mês antigo, e as duas lentes
    #: passariam a ler versões diferentes do mesmo arquivo.
    arquivo: str | None = None
    #: Recorta a planilha ANTES de contar — é o que faz a lente Mercado sair
    #: do mesmo arquivo da Clipei, só com `Público-alvo = Investidores`.
    filtros: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Sinônimos de sentimento deste fornecedor, além dos conhecidos.
    sentimentos: Mapping[str, str] = field(default_factory=dict)
    #: O PREFIXO DE TAXONOMIA QUE O FORNECEDOR CARIMBA no rótulo. A Approach
    #: manda `2 - Aegea - Falta de Água` e `1 - Aegea - Corsan`: o número é a
    #: posição na árvore dele, e o `Aegea -` é a marca — nada disso é o assunto
    #: nem a unidade. Sem remover, "Corsan" vira quatro unidades diferentes e o
    #: gráfico de exposição não fecha.
    #:
    #: DECLARADO NO CADASTRO, e não no código, pelo mesmo motivo do resto do
    #: mapeamento: é a convenção DESTE fornecedor. Um `replace` embutido aqui
    #: serviria a Approach e mutilaria o rótulo de quem não usa prefixo.
    prefixo_a_remover: str | None = None
    #: O MESMO LUGAR COM DOIS NOMES. A Bites chama a controladora de "Aegea"; a
    #: Approach chama de "Holding". No ranking de exposição isso vira duas
    #: barras para uma unidade só, e a maior delas fica menor do que é.
    #:
    #: Vale para `unidade` e `tema` — os dois campos em que cada fornecedor usa
    #: o vocabulário da casa dele. É a versão declarada, e mínima, do trabalho
    #: de casar as listas com o dicionário do CRM: aqui se resolve a colisão que
    #: atrapalha a leitura, sem esperar a taxonomia inteira ser conciliada.
    apelidos: Mapping[str, str] = field(default_factory=dict)
    #: Os teores que NÃO contam como contato de verdade nesta fonte, já
    #: achatados. Vazio usa `TEORES_NAO_ACIONAVEIS` — o vocabulário de hoje.
    #: Declarável porque é convenção do fornecedor, como o resto do mapeamento.
    teores_nao_acionaveis: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        desconhecidos = set(self.colunas) - CAMPOS
        if desconhecidos:
            raise ValueError(
                f"mapeamento cita campo que não existe em mencao: {sorted(desconhecidos)}"
            )
        faltando = CAMPOS_OBRIGATORIOS - set(self.colunas)
        if faltando:
            raise ValueError(f"mapeamento sem os campos {sorted(faltando)}")
        # Os sinônimos entram achatados SEMPRE, seja o mapeamento montado à mão
        # ou lido do banco: a busca é pela forma achatada, e um `Favorável`
        # gravado com acento nunca casaria com o `favoravel` da procura.
        object.__setattr__(
            self,
            "sentimentos",
            {_achatar(chave): str(valor) for chave, valor in self.sentimentos.items()},
        )

    @classmethod
    def de_json(cls, dados: Mapping[str, object] | None) -> Mapeamento:
        """O que está gravado em `score_fonte.mapeamento_colunas`."""
        dados = dados or {}
        filtros = {
            coluna: tuple(valores)
            if isinstance(valores, list | tuple)
            else (str(valores),)
            for coluna, valores in dict(dados.get("filtros") or {}).items()
        }
        aba = dados.get("aba")
        arquivo = dados.get("arquivo")
        prefixo = dados.get("prefixo_a_remover")
        return cls(
            colunas=dict(dados.get("colunas") or {}),
            aba=str(aba) if aba else None,
            arquivo=str(arquivo) if arquivo else None,
            filtros=filtros,
            sentimentos=dict(dados.get("sentimentos") or {}),  # type: ignore[arg-type]
            prefixo_a_remover=str(prefixo) if prefixo else None,
            apelidos={
                str(de): str(para)
                for de, para in dict(dados.get("apelidos") or {}).items()
            },
            teores_nao_acionaveis=frozenset(
                _achatar(teor) for teor in (dados.get("teores_nao_acionaveis") or [])
            ),
        )

    @property
    def colunas_necessarias(self) -> frozenset[str]:
        """Os cabeçalhos que a planilha precisa ter — filtros inclusive."""
        return frozenset(self.colunas.values()) | frozenset(self.filtros)


@dataclass(frozen=True, slots=True)
class MencaoLida:
    """Uma linha da planilha já no vocabulário do índice."""

    mes: date
    sentimento: str
    data: date | None = None
    tier: str | None = None
    engajamento: int | None = None
    cargo: str | None = None
    atributo: str | None = None
    veiculo: str | None = None
    publico_alvo: str | None = None
    tema_texto: str | None = None
    unidade_texto: str | None = None
    teor: str | None = None
    #: Nulo quando a fonte não mapeia teor — a pergunta não se aplica, e
    #: `False` diria que a menção não é um contato de verdade.
    acionavel: bool | None = None
    autor: str | None = None


@dataclass(frozen=True, slots=True)
class SomaCrua:
    """O agregado de um mês no grão de `score_mes_fonte`."""

    mes: date
    sentimento: str
    tier: str
    mencoes: int
    soma_log: float
    soma_engajamento: int
    soma_cargo: float


#: O tier veio escrito e não é nenhum dos três da escala da Clipei. A linha
#: ENTRA — ela tem data e sentimento, e jogá-la fora por causa de uma coluna
#: acessória perderia matéria de verdade —, mas entra sem tier, valendo o peso
#: de fábrica. Contar o aviso é o que distingue três células em branco num
#: arquivo de 1.506 linhas de uma coluna inteira mapeada errado.
AVISO_DE_TIER = "tier_nao_reconhecido"


@dataclass(frozen=True, slots=True)
class Leitura:
    """O que a planilha rendeu, com os descartes na cara."""

    mencoes: tuple[MencaoLida, ...]
    descartes: Mapping[str, int]
    linhas: int
    #: O que entrou, mas merece um olhar. Ver `AVISO_DE_TIER`.
    avisos: Mapping[str, int] = field(default_factory=dict)
    #: Quantas linhas TINHAM data e não tinham sentimento, por mês. É o que
    #: permite a tela desenhar "houve volume, ninguém classificou" em vez de
    #: "não houve nada" — dois estados que a §2 separa de propósito.
    nao_classificadas: Mapping[date, int] = field(default_factory=dict)

    @property
    def meses(self) -> tuple[date, ...]:
        return tuple(sorted({mencao.mes for mencao in self.mencoes}))


def para_data(valor: object) -> date | None:
    """A data da célula, seja ela data, texto ou lixo."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texto[:19], formato).date()
        except ValueError:
            continue
    return None


#: `1.234.567` ou `1,234,567` — o ponto e a vírgula separando MILHAR.
_MILHAR = re.compile(r"\d{1,3}(\.\d{3})+|\d{1,3}(,\d{3})+")
#: `1,5` ou `1.5` — o mesmo sinal separando DECIMAL.
_DECIMAL = re.compile(r"\d+[.,]\d+")


def para_inteiro(valor: object) -> int | None:
    """O engajamento da célula.

    A planilha de Community Management traz 885 linhas com o TEXTO `"0"` no
    lugar do número — uma conversão ingênua as leria como nulo, e o mês perderia
    um quinto das mensagens na régua de engajamento.

    O PONTO E A VÍRGULA PRECISAM SER DISTINGUIDOS, e não apagados. Uma primeira
    versão removia os dois: `"1.234"` virava 1234, certo, mas `"1,5"` virava 15
    — um post com 1 interação entrando no mês como 15, calado. Aqui, milhar é
    milhar e decimal é decimal; o decimal é truncado, porque engajamento é
    contagem de gente e meia interação não existe.
    """
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int | float):
        return int(valor)

    texto = str(valor or "").strip()
    negativo = texto.startswith("-")
    corpo = texto.lstrip("+-").strip()
    if not corpo:
        return None

    if _MILHAR.fullmatch(corpo):
        numero = int(corpo.replace(".", "").replace(",", ""))
    elif corpo.isdigit():
        numero = int(corpo)
    elif _DECIMAL.fullmatch(corpo):
        numero = int(corpo.replace(",", ".").split(".")[0])
    else:
        # `n/d`, `—`, `sem dados`: não é número, e chutar zero seria afirmar
        # que o post não teve engajamento nenhum.
        return None

    return -numero if negativo else numero


def normalizar_cargo(valor: object) -> str | None:
    """`Deputado Estadual` → `deputado_estadual`, a chave de `PESO_DO_CARGO`."""
    achatado = _achatar(valor)
    return achatado.replace(" ", "_") if achatado else None


def _texto(valor: object) -> str | None:
    limpo = str(valor or "").strip()
    return limpo or None


def sem_prefixo(valor: str | None, prefixo: str | None) -> str | None:
    """Tira do rótulo o cabeçalho de taxonomia do fornecedor.

    Só o COMEÇO do texto, e só uma vez: o objetivo é `2 - Aegea - Falta de
    Água` virar `Falta de Água`, e não sair caçando a palavra no meio do nome.
    Um prefixo que não casa devolve o rótulo intacto.
    """
    if not valor or not prefixo:
        return valor
    try:
        limpo = re.sub(prefixo, "", valor, count=1).strip()
    except re.error:
        # Prefixo inválido é erro de cadastro, e não motivo para perder o dado:
        # o rótulo cru é pior que o limpo, e muito melhor que nenhum.
        return valor
    return limpo or valor


def _rotulo(valor: object, mapeamento: Mapeamento) -> str | None:
    """O rótulo do fornecedor já sem prefixo e sob o nome combinado."""
    limpo = sem_prefixo(_texto(valor), mapeamento.prefixo_a_remover)
    if limpo is None:
        return None
    return mapeamento.apelidos.get(limpo, limpo)


def ler_linha(
    linha: Mapping[str, object], mapeamento: Mapeamento
) -> MencaoLida | Descarte:
    """Uma linha da planilha, ou o motivo de ela não contar."""
    for coluna, aceitos in mapeamento.filtros.items():
        if _achatar(linha.get(coluna)) not in {_achatar(aceito) for aceito in aceitos}:
            return Descarte.FORA_DO_FILTRO

    colunas = mapeamento.colunas
    data = para_data(linha.get(colunas["data"]))
    if data is None:
        return Descarte.SEM_DATA

    achatado = _achatar(linha.get(colunas["sentimento"]))
    sentimento = mapeamento.sentimentos.get(achatado) or SENTIMENTOS.get(achatado)
    if sentimento is None:
        # A Bites traz 1.426 posts com `Não informado`: são posts reais que o
        # fornecedor não classificou, e entrar como neutro inventaria opinião.
        return Descarte.SEM_SENTIMENTO

    def opcional(campo: str) -> object:
        coluna = colunas.get(campo)
        return linha.get(coluna) if coluna else None

    teor = _rotulo(opcional("teor"), mapeamento)
    nao_acionaveis = mapeamento.teores_nao_acionaveis or TEORES_NAO_ACIONAVEIS

    return MencaoLida(
        mes=data.replace(day=1),
        data=data,
        sentimento=sentimento,
        tier=TIERS.get(_achatar(opcional("tier"))),
        engajamento=para_inteiro(opcional("engajamento")),
        cargo=normalizar_cargo(opcional("cargo")),
        atributo=_texto(opcional("atributo")),
        veiculo=_texto(opcional("veiculo")),
        publico_alvo=_texto(opcional("publico_alvo")),
        tema_texto=_rotulo(opcional("tema"), mapeamento),
        unidade_texto=_rotulo(opcional("unidade"), mapeamento),
        teor=teor,
        acionavel=None if teor is None else _achatar(teor) not in nao_acionaveis,
        autor=_texto(opcional("autor")),
    )


def ler_planilha(
    linhas: Iterable[Mapping[str, object]], mapeamento: Mapeamento
) -> Leitura:
    """A planilha inteira, com a contagem do que ficou de fora."""
    mencoes: list[MencaoLida] = []
    descartes: dict[str, int] = {motivo.value: 0 for motivo in Descarte}
    avisos: dict[str, int] = {AVISO_DE_TIER: 0}
    nao_classificadas: dict[date, int] = {}
    coluna_do_tier = mapeamento.colunas.get("tier")
    total = 0
    for linha in linhas:
        total += 1
        lido = ler_linha(linha, mapeamento)
        if isinstance(lido, Descarte):
            descartes[lido.value] += 1
            # A linha sem sentimento MAS COM DATA é volume que existiu e
            # ninguém leu: ela não vira menção, e some da contagem — mas o mês
            # dela precisa saber que ela passou por ali.
            if lido is Descarte.SEM_SENTIMENTO:
                data = para_data(linha.get(mapeamento.colunas["data"]))
                if data is not None:
                    mes = data.replace(day=1)
                    nao_classificadas[mes] = nao_classificadas.get(mes, 0) + 1
            continue
        mencoes.append(lido)
        # A fonte mapeia tier, a célula tem texto, e o texto não é nenhum dos
        # três valores da escala: alguém trocou a coluna, ou o fornecedor mudou
        # o vocabulário.
        if coluna_do_tier and lido.tier is None and _achatar(linha.get(coluna_do_tier)):
            avisos[AVISO_DE_TIER] += 1
    return Leitura(
        mencoes=tuple(mencoes),
        descartes=descartes,
        linhas=total,
        avisos=avisos,
        nao_classificadas=nao_classificadas,
    )


def somar(mencoes: Iterable[MencaoLida]) -> list[SomaCrua]:
    """As quatro somas de que toda régua precisa, no grão mês×sentimento×tier.

    As somas saem daqui, e não de um `sum()` em SQL, porque os pesos são os de
    `dominio/score.py`: reescrever o `log10` e a tabela de cargos dentro de um
    `case` seria a segunda definição da régua, livre para divergir da primeira
    no dia em que alguém ajustar uma das duas.
    """
    acumulado: dict[tuple[date, str, str], list[float]] = {}
    for mencao in mencoes:
        chave = (mencao.mes, mencao.sentimento, mencao.tier or "")
        soma = acumulado.setdefault(chave, [0, 0.0, 0, 0.0])
        soma[0] += 1
        soma[1] += peso_do_engajamento(mencao.engajamento)
        soma[2] += max(0, mencao.engajamento or 0)
        soma[3] += peso_do_cargo(mencao.cargo)
    return [
        SomaCrua(
            mes=mes,
            sentimento=sentimento,
            tier=tier,
            mencoes=int(valores[0]),
            soma_log=round(valores[1], 4),
            soma_engajamento=int(valores[2]),
            soma_cargo=round(valores[3], 4),
        )
        for (mes, sentimento, tier), valores in sorted(acumulado.items())
    ]
