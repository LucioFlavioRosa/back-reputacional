"""O formato da planilha de subtemas, descrito uma vez só.

POR QUE ESTA IMPORTAÇÃO EXISTE. A taxonomia de temas entra no banco por
migration — foi assim na `0053`, na `0058` e na `0061`. Isso é certo para a carga
inicial, e errado para a manutenção: a Aegea mantém a taxonomia numa planilha
(`20260917_Aegea_Taxonomia_Publicos_v2.xlsx` e sucessoras), e cada revisão dela
hoje exige um desenvolvedor escrevendo SQL. A planilha existe para ACELERAR o
cadastro, e sem caminho de volta ela só acelera o trabalho de quem a escreve.

O QUE SE IMPORTA É O SUBTEMA, e os níveis pendem dele. Quem cadastra uma agenda
informa só o tema — pilar, tema estratégico, LSO e risco o sistema remonta a
partir dele. Por isso esta planilha é a fonte daqueles níveis, e por isso ela
tem uma linha por subtema em vez de uma linha por combinação.

NADA AQUI É NOVO NO BANCO. Pilar (`bloco_tema`), tema estratégico
(`macro_tema`), LSO (`tema.camada_lso`) e os riscos (`risco`, `tema_risco`) já
existem. A importação não cria vocabulário: ela liga um subtema ao que já está
lá, e RECUSA o que não reconhece. É a diferença entre acelerar o cadastro e
deixar a planilha inventar taxonomia.

A FORMA SEGUE A IMPORTAÇÃO DE AGENDAS, que já está provada: baixar o modelo com
as listas do banco, preencher, subir, CONFERIR, confirmar. O que não segue é o
tamanho — uma agenda tem 59 colunas, abas aninhadas e herança entre linhas; um
subtema tem seis campos. Replicar a maquinária daquela aqui seria cerimônia.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: A aba que se preenche. Uma só, e com o nome que a planilha da Aegea usa — a
#: pessoa que baixa o modelo reconhece a aba que ela já conhece.
ABA_PRINCIPAL = "Subtemas"


@dataclass(frozen=True, slots=True)
class Coluna:
    """Uma coluna da planilha de subtemas.

    `vocabulario` é a chave do dicionário contra o qual a célula é validada, e
    `None` quando a coluna é texto livre. Diferente da importação de agendas,
    aqui NENHUM vocabulário é editável: a planilha classifica, não cadastra
    pilar nem risco.
    """

    nome: str
    #: O campo de `SubtemaLido` que esta coluna alimenta.
    campo: str
    vocabulario: str | None = None
    #: Pode ficar em branco? Vazio é resposta em dois casos, e os dois estão
    #: na fonte: a taxonomia não define LSO para 47 dos 104 subtemas, e deixa 4
    #: sem enquadramento de risco.
    obrigatoria: bool = True
    #: Texto curto no cabeçalho da coluna, para quem preenche sem o manual.
    dica: str = ""


FORMATO: tuple[Coluna, ...] = (
    Coluna(
        nome="Subtema (N3)",
        campo="nome",
        dica="O tema da reunião. É por ele que a agenda é classificada.",
    ),
    # PILAR E N2 NÃO SÃO OBRIGATÓRIOS, e isto é conserto de uma falha que só
    # apareceu ao testar contra a planilha de verdade: o importador RECUSAVA o
    # estado que a própria exportação produz.
    #
    # Os 45 subtemas que a `0058` deixou sem reconciliar têm `macro_tema_id`
    # NULO no banco, e saem da planilha com estas duas colunas em branco.
    # Exigi-las tornava o instrumento incapaz de representar a base — e eram
    # exatamente esses 45 que a planilha existe para ajudar a reconciliar.
    #
    # EM BRANCO É "NÃO RECONCILIADO", o mesmo que o nulo significa. E apagar uma
    # classificação que existia não passa calado: a conferência mostra como
    # ALTERA, com o antes e o depois — é para isso que o passo de conferência
    # existe.
    Coluna(
        nome="Pilar (N1)",
        campo="pilar",
        vocabulario="blocos_tema",
        obrigatoria=False,
        dica="Um dos 7 pilares. Em branco = ainda não reconciliado.",
    ),
    Coluna(
        nome="Tema estratégico (N2)",
        campo="tema_estrategico",
        vocabulario="macro_temas",
        obrigatoria=False,
        dica="Um dos 41, do pilar ao lado. Em branco = ainda não reconciliado.",
    ),
    Coluna(
        nome="LSO",
        campo="camada_lso",
        vocabulario="camadas_lso",
        obrigatoria=False,
        dica="Em branco é resposta: a taxonomia não define LSO para 47 dos 104.",
    ),
    Coluna(
        nome="É tema de risco?",
        campo="e_risco",
        vocabulario="sim_nao",
        obrigatoria=False,
        dica="Sim ou Não. Em branco = não reconciliado.",
    ),
    Coluna(
        nome="Riscos (códigos)",
        campo="riscos",
        vocabulario="riscos",
        obrigatoria=False,
        dica="Códigos da matriz (R01, R07), separados por vírgula. Em branco = sem enquadramento.",
    ),
)

#: Os vocabulários que o modelo oferece em aba própria, todos FECHADOS.
#:
#: `camadas_lso` e `sim_nao` não são tabela: são domínio do código
#: (`CAMADAS_DE_LSO` em `app/api/stakeholders.py`) e um par de palavras. Saem em
#: aba mesmo assim, porque uma lista suspensa que existe para metade das colunas
#: ensina que a outra metade é texto livre.
VOCABULARIOS = ("blocos_tema", "macro_temas", "camadas_lso", "sim_nao", "riscos")

#: O que `É tema de risco?` aceita, e o que cada um significa.
SIM = "Sim"
NAO = "Não"


class Decisao(StrEnum):
    """O que a conferência diz de cada linha.

    OS QUATRO ESTADOS SÃO O PRODUTO desta importação. Uma planilha de 104 linhas
    em que 100 não mudaram e 4 mudaram é o caso normal da manutenção mensal, e a
    tela só vale se ela mostrar quais são as 4 sem a pessoa ler as 104.
    """

    #: O subtema não existe no banco. Vai nascer.
    NOVO = "novo"
    #: Existe e a planilha diz o mesmo. Nada a fazer — e é a maioria.
    IGUAL = "igual"
    #: Existe e a planilha diz outra coisa. A tela mostra o antes e o depois.
    ALTERA = "altera"
    #: A linha não pode ser aplicada: vocabulário não reconhecido, pilar que não
    #: casa com o tema estratégico, código de risco inexistente.
    RECUSADA = "recusada"


@dataclass(frozen=True, slots=True)
class SubtemaLido:
    """Uma linha da planilha, já convertida e ainda não confrontada com o banco.

    OS TIPOS JÁ SÃO OS DO DOMÍNIO — `e_risco` é `bool | None` e `riscos` é uma
    tupla de códigos —, porque o leitor é o único lugar que sabe o que "Sim" e
    "R01, R07" significam. Deixar texto cru viajar daqui para a frente
    espalharia essa tradução por três camadas.
    """

    linha: int
    nome: str
    pilar: str
    tema_estrategico: str
    camada_lso: str | None
    #: O TEXTO CRU da célula, e não `bool | None`.
    #:
    #: A primeira versão convertia aqui e usava um sentinela para "a célula tem
    #: algo que não é Sim nem Não" — um `object()` viajando num campo tipado
    #: `bool | None`. Mentira de tipo, e das que o verificador não pega.
    #:
    #: Guardar o texto e interpretar na conferência é mais honesto e dá melhor
    #: mensagem: a divergência pode dizer QUAL valor a pessoa digitou.
    e_risco_bruto: str
    riscos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Divergencia:
    """Por que uma linha foi recusada, em palavras que a pessoa possa agir sobre.

    `coluna` e `valor` existem para a tela marcar a célula: "a linha 37 está
    errada" manda a pessoa procurar, e "a linha 37, coluna Pilar, valor
    'Governanca' " manda ela corrigir.
    """

    coluna: str
    valor: str
    motivo: str


@dataclass(frozen=True, slots=True)
class Proposta:
    """O que a importação faria com uma linha, e o que ela encontrou.

    `antes` só vem preenchido em `ALTERA`, e é o que permite a tela mostrar o
    que muda em vez de pedir confiança.
    """

    lido: SubtemaLido
    decisao: Decisao
    #: O `tema.id` quando o subtema já existe.
    tema_id: int | None = None
    antes: dict[str, object] | None = None
    depois: dict[str, object] | None = None
    divergencias: tuple[Divergencia, ...] = ()


def normalizar_nome(valor: str) -> str:
    """A forma de comparar nome de subtema entre a planilha e o banco.

    MINÚSCULA E ESPAÇO COLAPSADO, e nada além disso — de propósito. A `0058`
    casou a taxonomia por nome EXATO e 45 temas não casaram, o que custou a
    reconciliação que ainda está em aberto. Afrouxar aqui (ignorar acento,
    aproximar por similaridade) repetiria aquele erro na direção oposta: duas
    linhas diferentes virariam a mesma, e a importação sobrescreveria um subtema
    com o conteúdo de outro.

    Espaço colapsado porque colar de uma planilha traz espaço duplo e espaço no
    fim, e isso não é informação. Caixa porque "Tarifa" e "tarifa" são o mesmo
    assunto para quem digita.
    """
    return " ".join(valor.split()).lower()


@dataclass(frozen=True, slots=True)
class ResumoDaAplicacao:
    """O que a confirmação fez, em números que a tela repete para a pessoa.

    `recusadas` e `iguais` entram no resumo mesmo não gerando escrita: a frase
    útil depois de confirmar é "3 criados, 1 alterado, 145 sem mudança, 1
    recusado", e não "4 gravados". Sem os dois últimos a pessoa não sabe se as
    145 linhas restantes foram ignoradas por estarem certas ou por terem sido
    perdidas no caminho.
    """

    criados: int
    alterados: int
    iguais: int
    recusadas: int

    @property
    def escritas(self) -> int:
        """Quantas linhas efetivamente mexeram no banco."""
        return self.criados + self.alterados
