"""O que foi levado embora, por quem, e sobre qual recorte.

ESTE CONTEXTO NÃO GERA PDF, e a escolha é deliberada.

O documento sai da impressão do navegador sobre um layout próprio — é o que o
handoff pede, e a tela já faz. Um gerador no servidor exigiria uma dependência
nova, uma segunda implementação do mesmo layout, e fontes empacotadas no
contêiner. O que faltava não era o documento: era saber que ele existiu.

E é justamente esse o evento que `seguranca/ARQUITETURA.md` lista como ausente. Com
acesso externo, "quem exportou, qual recorte, quantas linhas" deixa de ser
curiosidade e vira a única forma de responder o que saiu do sistema depois de um
incidente.

O QUE ESTE REGISTRO É, E O QUE NÃO É

    É       trilha de responsabilização, útil entre pessoas da casa e como
            insumo de alerta ("alguém exportou a base inteira às 3h")
    NÃO É   controle. Depende de o cliente chamar a rota; um cliente
            modificado simplesmente não chama, e o registro não acontece.

Fingir o contrário seria pior do que não ter: alguém consultaria a trilha
acreditando que ela é completa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.dominio.erros import RegraViolada

#: As seções que a tela oferece. Vocabulário fechado.
#:
#: Texto livre aqui viraria seis grafias da mesma seção e nenhuma consulta
#: confiável — o mesmo motivo pelo qual `acesso_log.resultado` tem `check`.
SECOES = (
    "resumo",
    "volumetria",
    "status",
    "resultado",
    "rankings",
    "interlocutores",
    "pendencias",
    "base",
)

#: A seção que muda a natureza do documento.
#:
#: Todas as outras são números agregados; com `base`, o documento carrega linhas
#: individuais — nome de veículo, pauta, data, quem falou.
SECAO_DE_REGISTROS = "base"

#: Quantas linhas o documento de fato leva quando a seção `base` é escolhida.
#:
#: O layout impresso corta em 80 (`GerarRelatorio.tsx`), e o número precisa
#: estar AQUI porque é ele que a trilha registra.
#:
#: Registrar o tamanho do RECORTE no lugar deste anotaria um relatório sobre
#: 6.000 registros como se 6.000 linhas tivessem saído, quando saíram 80 — e o
#: alerta de volume dispararia no alvo errado. Alerta que erra é alerta que
#: alguém desliga.
#:
#: A duplicação com o front é real e conhecida. Um dia o documento vem do
#: servidor e ela some; até lá, mudar um lado sem o outro faz a trilha mentir.
LINHAS_NO_DOCUMENTO = 80

#: Como a saída deixou o sistema.
#:
#: `documento` é o relatório impresso, cortado em `LINHAS_NO_DOCUMENTO`.
#: `csv` é a exportação da tela Base — o caminho MAIS CURTO para tirar dados
#: daqui, e o que ficava sem evento nenhum: um botão, um arquivo, o recorte
#: inteiro, sem corte.
FORMATOS = ("documento", "csv")


@dataclass(frozen=True, slots=True)
class Relatorio:
    """Um documento gerado."""

    secoes: tuple[str, ...]
    #: O `Recorte` serializado, como veio da query string.
    filtros: dict
    criado_por: UUID
    #: Quantos registros o recorte alcançava no momento.
    #:
    #: É o CONTEXTO: o que a pessoa estava olhando. Não é o que saiu — para isso
    #: existe `registros_no_documento`.
    total_de_registros: int = 0
    formato: str = "documento"
    id: UUID | None = None
    criado_em: datetime | None = None
    arquivo_url: str | None = None

    def __post_init__(self) -> None:
        if not self.secoes:
            raise RegraViolada("Um relatório precisa de ao menos uma seção.")

        desconhecidas = [s for s in self.secoes if s not in SECOES]
        if desconhecidas:
            raise RegraViolada(
                f"Seção desconhecida: {', '.join(sorted(desconhecidas))}. "
                f"Use uma de {', '.join(SECOES)}."
            )

        if self.formato not in FORMATOS:
            raise RegraViolada(
                f"Formato desconhecido: {self.formato!r}. "
                f"Use um de {', '.join(FORMATOS)}."
            )

    @property
    def leva_registros(self) -> bool:
        """O documento carrega linhas individuais, e não só números agregados."""
        return SECAO_DE_REGISTROS in self.secoes

    @property
    def registros_no_documento(self) -> int:
        """Quantas linhas de fato saíram.

        É o número do alerta. `total_de_registros` diz o que a pessoa estava
        olhando; este diz o que ela levou.

        A diferença entre os formatos é o ponto: o documento impresso corta em
        `LINHAS_NO_DOCUMENTO`; o CSV **não corta**. Um export de 6.000 registros
        leva 6.000 — e é por isso que ele é o caminho mais curto para tirar
        dados daqui, e o que mais merece o alerta.
        """
        if not self.leva_registros:
            return 0
        if self.formato == "csv":
            return self.total_de_registros
        return min(self.total_de_registros, LINHAS_NO_DOCUMENTO)


@dataclass(frozen=True, slots=True)
class LinhaDoHistorico:
    """Uma geração, na tela de histórico."""

    id: UUID
    criado_em: datetime
    criado_por: str
    secoes: tuple[str, ...]
    total_de_registros: int
    leva_registros: bool
    formato: str = "documento"
    resumo_do_recorte: str = field(default="")
