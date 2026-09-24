"""As regras do dossiê de cada lente — sem banco e sem HTTP.

O que mora aqui é o que se confere na mão: a prioridade de um jornalista a
partir de três notas e as duas taxas de resposta.

AS FRASES DA TELA NÃO MORAM AQUI. Elas são calculadas por detectores, em
`dominio/sinais_da_lente.py` — este arquivo guarda as regras de negócio que os
detectores leem, e não o texto que eles produzem.

O ÍNDICE NÃO MORA AQUI. Nota, NS e ponderação continuam em `dominio/score.py`:
a lente é uma LEITURA do índice, e duplicar a fórmula criaria duas verdades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Procedencia(StrEnum):
    """De onde veio o número. É o que o "?" de cada bloco mostra primeiro.

    A distinção que importa não é técnica, é de confiança: `PLANILHA` e `CRM`
    são medição; `RELATORIO` é transcrição de um documento que alguém escreveu;
    `CADASTRO` é alguém desta casa digitando. Apresentar os três com a mesma
    cara é o que faz um painel perder credibilidade de uma vez, quando o leitor
    descobre sozinho que um número era estimativa.
    """

    PLANILHA = "planilha"
    CRM = "crm"
    RELATORIO = "relatorio"
    CADASTRO = "cadastro"
    #: Derivado dos anteriores — a nota da lente, os percentuais.
    CALCULO = "calculo"


@dataclass(frozen=True, slots=True)
class Conceito:
    """Um termo do bloco, explicado. Vai no "?"."""

    termo: str
    texto: str


@dataclass(frozen=True, slots=True)
class Ficha:
    """A procedência de um bloco, inteira.

    `lacunas` é o campo que esta ficha existe para carregar: o que o bloco NÃO
    tem hoje, dito com todas as letras, no lugar onde a pessoa está olhando o
    número. Uma lacuna escrita no README não protege ninguém.
    """

    origem: Procedencia
    fonte: str
    colunas: tuple[str, ...] = ()
    lacunas: tuple[str, ...] = ()
    #: O conteúdo é ilustrativo, e não medição desta ferramenta.
    exemplo: bool = False
    conceitos: tuple[Conceito, ...] = ()


# -- a matriz de jornalistas ----------------------------------------------------

#: Os cortes do §3.1. A soma das três notas de 1 a 5 dá de 3 a 15.
FAIXAS_DE_PRIORIDADE: tuple[tuple[int, int, str], ...] = (
    (13, 1, "relacionamento contínuo"),
    (10, 2, "contato semestral"),
    (7, 3, "tático"),
    (0, 4, "monitoramento"),
)


@dataclass(frozen=True, slots=True)
class Prioridade:
    pontos: int
    nivel: int
    cadencia: str


def prioridade_do_jornalista(
    relevancia: int, exposicao: int, proximidade: int
) -> Prioridade:
    """Quem priorizar, a partir das três notas.

    AS TRÊS PESAM IGUAL, e é deliberado: um jornalista muito relevante e muito
    exposto de quem estamos longe soma o mesmo que um próximo de peso médio — e
    a tela existe justamente para mostrar que o primeiro é o urgente. Ponderar
    relevância acima das outras faria a matriz repetir o ranking de veículos,
    que já existe em outro lugar.
    """
    for nota in (relevancia, exposicao, proximidade):
        if not 1 <= nota <= 5:
            raise ValueError(f"Nota fora da escala de 1 a 5: {nota}.")
    pontos = relevancia + exposicao + proximidade
    for minimo, nivel, cadencia in FAIXAS_DE_PRIORIDADE:
        if pontos >= minimo:
            return Prioridade(pontos=pontos, nivel=nivel, cadencia=cadencia)
    raise AssertionError("faixa 0 cobre todo o resto")  # pragma: no cover


# -- as duas taxas de resposta --------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaxaDeResposta:
    """Quanto do que chegou foi respondido, das duas formas.

    A BRUTA sobre tudo, a OPERACIONAL só sobre o que é contato de verdade. A
    diferença entre elas não é detalhe de cálculo: é a diferença entre cobrar a
    equipe por um número que inclui marcação de post e cobrá-la pelo trabalho
    que existia para fazer.
    """

    recebidas: int
    acionaveis: int
    respondidas: int | None

    @property
    def bruta(self) -> float | None:
        if self.respondidas is None or not self.recebidas:
            return None
        return self.respondidas / self.recebidas

    @property
    def operacional(self) -> float | None:
        """Nula quando a fonte não classifica teor — e não igual à bruta.

        Devolver a bruta com outro nome faria a tela mostrar duas taxas iguais
        e sugerir que a distinção foi feita, quando não foi.
        """
        if self.respondidas is None or not self.acionaveis:
            return None
        # Pode passar de 1: responderam também o que não era acionável. É
        # informação, não erro — e cortar em 1 esconderia justamente o esforço
        # gasto fora da fila.
        return self.respondidas / self.acionaveis


# -- o que a tela precisa saber de cada bloco -----------------------------------


@dataclass(frozen=True, slots=True)
class Bloco:
    """Um gráfico ou quadro do dossiê, com a ficha de procedência junto.

    A FICHA VIAJA COM O DADO, e não numa tabela à parte de documentação: é o
    que garante que os dois não se separem. Um bloco que muda de fonte e leva a
    explicação antiga é pior do que um bloco sem explicação nenhuma.
    """

    tipo: str
    titulo: str
    dados: object
    ficha: Ficha
    legenda: tuple[str, ...] = ()
    #: O título-conclusão escrito pela curadoria, quando existe.
    conclusao: str | None = None
    campos: dict = field(default_factory=dict)
