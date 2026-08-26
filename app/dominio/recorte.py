"""O Recorte — os filtros do painel como um value object único.

Esta é a peça central do sistema. Todo bloco de agregação e toda listagem
respondem ao MESMO conjunto de filtros; se cada endpoint montasse o seu próprio
`where`, o número do KPI deixaria de bater com o da tabela na primeira
divergência.

São 16 campos. A gaveta de filtros da tela expõe 13 deles; `porta_voz`,
`pessoa` e `grupo_status` existem hoje só na query string da API — ver
`obter_recorte` em `app/api/interacoes.py`.

Por isso o Recorte é um objeto só, imutável, construído uma vez na fronteira
HTTP e passado adiante. A tradução dele para SQL mora em um único lugar:
`app/banco/filtros_sql.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from uuid import UUID

from app.dominio.erros import RegraViolada
from app.dominio.periodo import AtalhoDePeriodo, Periodo

UFS = frozenset(
    {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
        "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
        "SP", "SE", "TO",
    }
)

#: Além das 27 UFs, o campo aceita dois valores que o mapa trata à parte.
NACIONAL = "NA"
INTERNACIONAL = "IN"
ABRANGENCIAS_VALIDAS = UFS | {NACIONAL, INTERNACIONAL}

#: Grupos de status usados na taxa de resolutividade.
#:
#: `status` e `grupo_status` são campos separados de propósito: "declinado" é ao
#: mesmo tempo o código de um status e o nome de um grupo — que também contém
#: "cancelado". Num campo só, filtrar por "declinado" seria ambíguo e o número
#: da tela de Status não bateria com o da Base.
GRUPOS_DE_STATUS = frozenset({"resolvido", "aberto", "declinado"})


@dataclass(frozen=True, slots=True)
class Recorte:
    """O conjunto de filtros que define o que está sendo analisado.

    Todo campo é opcional: um Recorte vazio significa "a base inteira".
    """

    periodo: Periodo = field(default_factory=Periodo)
    frente: str | None = None
    unidade: str | None = None
    uf: str | None = None
    esfera: str | None = None
    tier: int | None = None
    clima: str | None = None
    resultado: str | None = None
    status: str | None = None
    grupo_status: str | None = None
    entidade: str | None = None
    subtipo: str | None = None
    porta_voz: UUID | None = None
    pessoa: UUID | None = None
    tags: tuple[str, ...] = ()
    busca: str | None = None

    def __post_init__(self) -> None:
        if self.uf and self.uf not in ABRANGENCIAS_VALIDAS:
            raise RegraViolada(
                f"UF inválida: {self.uf!r}. Use uma das 27 siglas, "
                f"{NACIONAL!r} (nacional) ou {INTERNACIONAL!r} (internacional)."
            )
        if self.tier is not None and self.tier < 1:
            raise RegraViolada(f"Tier inválido: {self.tier!r}. Use um número positivo.")
        # QUAIS níveis existem é decisão do banco — são linhas em `relevancia`.
        #
        # Filtrar por um nível inexistente devolve zero registros, e está certo:
        # é a mesma resposta de filtrar por um que existe e ninguém usou. Recusar
        # o pedido exigiria consultar o banco DAQUI, e este módulo não tem acesso
        # a ele de propósito — o `Recorte` é objeto de valor puro.
        #
        # Esta era a QUARTA cópia da lista de níveis: havia esta, uma em
        # `dominio/interacao.py`, um `check between 1 and 3` no schema e as
        # opções escritas à mão no filtro do front. Nada obrigava as quatro a
        # concordar, e nenhuma delas dizia por que o Tier 4 não entrava.
        if self.grupo_status and self.grupo_status not in GRUPOS_DE_STATUS:
            validos = ", ".join(sorted(GRUPOS_DE_STATUS))
            raise RegraViolada(
                f"Grupo de status inválido: {self.grupo_status!r}. Use {validos}."
            )

    @property
    def vazio(self) -> bool:
        """Verdadeiro quando nenhum filtro está aplicado."""
        return self == Recorte()

    @property
    def quantidade_de_filtros(self) -> int:
        """Quantos filtros estão ativos — vira o contador do botão "Filtros"."""
        ativos = sum(
            1
            for valor in (
                self.frente, self.unidade, self.uf, self.esfera, self.tier,
                self.clima, self.resultado, self.status, self.grupo_status,
                self.entidade, self.subtipo, self.porta_voz, self.pessoa, self.busca,
            )
            if valor is not None
        )
        if not self.periodo.aberto:
            ativos += 1
        if self.tags:
            ativos += 1
        return ativos

    def com(self, **alteracoes: object) -> Recorte:
        """Devolve um novo Recorte com os campos alterados.

        Usado pelas telas que empilham filtros: clicar numa barra do gráfico
        acrescenta uma frente ao recorte corrente sem destruir o resto.
        """
        return replace(self, **alteracoes)  # type: ignore[arg-type]

    def alternar_tag(self, tag: str) -> Recorte:
        """Liga ou desliga uma tag. Clicar de novo no mesmo item remove o filtro."""
        atuais = set(self.tags)
        atuais.symmetric_difference_update({tag})
        return replace(self, tags=tuple(sorted(atuais)))

    @classmethod
    def construir(
        cls,
        *,
        periodo: str | None = None,
        de: date | None = None,
        ate: date | None = None,
        hoje: date | None = None,
        **filtros: object,
    ) -> Recorte:
        """Monta um Recorte resolvendo o atalho de período.

        `de`/`ate` explícitos têm precedência sobre o atalho, como manda o
        contrato da API.
        """
        if de or ate:
            intervalo = Periodo(de=de, ate=ate)
        elif periodo:
            try:
                atalho = AtalhoDePeriodo(periodo)
            except ValueError as erro:
                validos = ", ".join(a.value for a in AtalhoDePeriodo)
                raise RegraViolada(
                    f"Período inválido: {periodo!r}. Use {validos}, ou de/ate explícitos."
                ) from erro
            intervalo = Periodo.do_atalho(atalho, hoje=hoje)
        else:
            intervalo = Periodo()

        tags = filtros.pop("tags", ()) or ()
        if isinstance(tags, str):
            tags = tuple(t.strip() for t in tags.split(",") if t.strip())

        # Ordenadas para que dois Recortes com as mesmas tags sejam iguais,
        # independentemente da ordem em que o usuário clicou nelas.
        return cls(periodo=intervalo, tags=tuple(sorted(tags)), **filtros)  # type: ignore[arg-type]
