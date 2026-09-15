"""As extensões por frente.

Cada frente acrescenta os seus próprios campos à interação. Governo, Parceiros
e Eventos compartilham a mesma extensão porque têm exatamente os mesmos campos
extras — são cinco extensões para sete frentes.

Acrescentar um campo novo a uma frente mexe só na classe dela e na tabela
`interacao_<frente>` correspondente. Nenhuma outra frente precisa saber.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.dominio.erros import RegraViolada


class Frente(StrEnum):
    IMPRENSA = "imprensa"
    GOVERNO = "governo"
    PARCEIROS = "parceiros"
    EVENTOS = "eventos"
    INVESTIDORES = "investidores"
    LEGISLATIVO = "legislativo"
    INTERNA = "interna"
    #: "Bancos/Credores" na tela — ver `0031_frente_bancos_credores.sql`. O
    #: MEMBRO fica em português técnico (como os demais), e não como o rótulo
    #: exibido: `GOVERNO`/`LEGISLATIVO` também não viraram `ENTIDADES`/
    #: `AGENTES_PUBLICOS` quando só o `nome` do dicionário mudou.
    BANCOS_CREDORES = "bancos_credores"


@dataclass(frozen=True, slots=True)
class Extensao:
    """Base das extensões. Cada subclasse declara a que frentes serve."""

    @classmethod
    def frentes_atendidas(cls) -> frozenset[Frente]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Imprensa(Extensao):
    formato: str | None = None
    data_atendida: date | None = None
    data_publicacao: date | None = None
    link_materia: str | None = None
    mensagens_chave: tuple[str, ...] = ()

    @classmethod
    def frentes_atendidas(cls) -> frozenset[Frente]:
        return frozenset({Frente.IMPRENSA})

    def __post_init__(self) -> None:
        if (
            self.data_atendida
            and self.data_publicacao
            and self.data_publicacao < self.data_atendida
        ):
            raise RegraViolada(
                "A data de publicação é anterior à data em que a demanda foi atendida."
            )


@dataclass(frozen=True, slots=True)
class Institucional(Extensao):
    """Governo, Parceiros, Eventos e Bancos/Credores.

    BANCOS/CREDORES ENTROU AQUI, e não numa extensão própria: o cadastro (ver
    `Cadastro.tsx`, "Os campos extras por frente NÃO estão mais na tela")
    parou de expor esses campos por formulário — sobrevivem só ao reeditar um
    registro que já os tinha. Uma extensão nova, com uma tabela
    `interacao_bancos_credores` só para isso, pagaria o preço de uma tabela e
    uma migration para um campo que hoje ninguém preenche pela tela. Se um dia
    precisar de campo próprio (ex.: linha de crédito, instituição garantidora),
    é quando ganha a classe dela.
    """

    natureza_orgao: str | None = None
    cargo_interlocutor: str | None = None
    #: Só faz sentido em Eventos: o nome do evento não é a entidade promotora
    #: nem o interlocutor — confundir os três é um erro recorrente na planilha.
    nome_evento: str | None = None

    @classmethod
    def frentes_atendidas(cls) -> frozenset[Frente]:
        return frozenset(
            {Frente.GOVERNO, Frente.PARCEIROS, Frente.EVENTOS, Frente.BANCOS_CREDORES}
        )


@dataclass(frozen=True, slots=True)
class Legislativo(Extensao):
    casa: str | None = None
    tramitacao: str | None = None
    prioridade: str | None = None
    #: A coluna "TAG" da ABCON-ML: é a ementa da proposição, não uma tag.
    ementa: str | None = None

    PRIORIDADES = ("alta", "media", "baixa", "monitoramento")

    @classmethod
    def frentes_atendidas(cls) -> frozenset[Frente]:
        return frozenset({Frente.LEGISLATIVO})

    def __post_init__(self) -> None:
        if self.prioridade and self.prioridade not in self.PRIORIDADES:
            raise RegraViolada(
                f"Prioridade inválida: {self.prioridade!r}. "
                f"Use {', '.join(self.PRIORIDADES)}."
            )


@dataclass(frozen=True, slots=True)
class Investidores(Extensao):
    tipo_investidor: str | None = None
    formato: str | None = None

    @classmethod
    def frentes_atendidas(cls) -> frozenset[Frente]:
        return frozenset({Frente.INVESTIDORES})


@dataclass(frozen=True, slots=True)
class Interna(Extensao):
    natureza: str | None = None
    cumprimento: str | None = None
    complexidade: str | None = None
    prazo_dias: int | None = None
    data_retorno: date | None = None

    NATUREZAS = ("demanda", "entrega")
    CUMPRIMENTOS = ("interno", "externo", "misto")
    COMPLEXIDADES = ("baixa", "media", "alta")

    @classmethod
    def frentes_atendidas(cls) -> frozenset[Frente]:
        return frozenset({Frente.INTERNA})

    def __post_init__(self) -> None:
        for valor, validos, rotulo in (
            (self.natureza, self.NATUREZAS, "Natureza"),
            (self.cumprimento, self.CUMPRIMENTOS, "Cumprimento"),
            (self.complexidade, self.COMPLEXIDADES, "Complexidade"),
        ):
            if valor and valor not in validos:
                raise RegraViolada(
                    f"{rotulo} inválido: {valor!r}. Use {', '.join(validos)}."
                )
        if self.prazo_dias is not None and self.prazo_dias < 0:
            raise RegraViolada("O prazo em dias não pode ser negativo.")


#: Que TIPO de instituição cada frente conversa.
#:
#: É REGRA DE DOMÍNIO, e por isso mora aqui e não no semeador: uma agenda de
#: imprensa fala com veículo, uma de legislativo com proposição. Quem precisa
#: do mapa — inclusive os semeadores — importa daqui.
#:
#: `eventos` e `parceiros` compartilham `entidade`: quem promove um evento é a
#: mesma classe de instituição com quem se faz parceria.
TIPO_DE_INSTITUICAO: dict[Frente, str] = {
    Frente.IMPRENSA: "veiculo",
    Frente.GOVERNO: "orgao",
    Frente.PARCEIROS: "entidade",
    Frente.EVENTOS: "entidade",
    Frente.INVESTIDORES: "investidor",
    Frente.LEGISLATIVO: "proposicao",
    Frente.INTERNA: "area_interna",
    #: NÃO é "investidor": a relação com um banco credor é de dívida, não de
    #: mercado de capitais — misturar as duas faria o filtro de instituições
    #: de Investidores oferecer bancos de crédito, e vice-versa.
    Frente.BANCOS_CREDORES: "credor",
}

#: Os tipos que se pode cadastrar. DERIVADO do mapa acima, e nao uma segunda
#: lista: um tipo que nenhuma frente conversa seria cadastravel e invisivel —
#: a instituicao existiria e nunca apareceria em formulario nenhum.
#:
#: Um tipo que nao aparece no mapa acima nao existe para a aplicacao, por mais
#: que alguem o escreva num comentario.
TIPOS_DE_INSTITUICAO: frozenset[str] = frozenset(TIPO_DE_INSTITUICAO.values())

#: A frente determina qual extensão é aceita. Uma interação de Governo com
#: dados de imprensa é um erro de programação, não um caso de uso.
EXTENSAO_POR_FRENTE: dict[Frente, type[Extensao]] = {
    frente: classe
    for classe in (Imprensa, Institucional, Legislativo, Investidores, Interna)
    for frente in classe.frentes_atendidas()
}


def extensao_esperada(frente: Frente) -> type[Extensao]:
    return EXTENSAO_POR_FRENTE[frente]
