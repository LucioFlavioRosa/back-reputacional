"""Contratos HTTP do contexto de interações.

Estes modelos existem para validar e serializar a fronteira. Eles não são o
domínio — a conversão entre os dois é explícita, para que mudar o formato da
API não mexa nas regras de negócio.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    Frente,
    Imprensa,
    Institucional,
    Interna,
    Investidores,
    Legislativo,
    extensao_esperada,
)
from app.dominio.interacao import (
    Interacao,
    ParticipacaoAegea,
)


class ParticipacaoEntrada(BaseModel):
    pessoa_aegea_id: UUID
    papel: str = "porta_voz"


class ExtensaoEntrada(BaseModel):
    """Campos específicos de frente, todos opcionais.

    Um único objeto serve às cinco extensões: o domínio recusa combinação
    incoerente (dados de imprensa numa interação de Governo, por exemplo).
    """

    model_config = ConfigDict(extra="forbid")

    # imprensa
    formato: str | None = None
    data_atendida: date | None = None
    data_publicacao: date | None = None
    link_materia: str | None = None
    mensagens_chave: list[str] = Field(default_factory=list)

    # institucional (governo, parceiros, eventos)
    natureza_orgao: str | None = None
    cargo_interlocutor: str | None = None
    nome_evento: str | None = None

    # legislativo
    casa: str | None = None
    tramitacao: str | None = None
    prioridade: str | None = None
    ementa: str | None = None

    # investidores
    tipo_investidor: str | None = None

    # interna
    natureza: str | None = None
    cumprimento: str | None = None
    complexidade: str | None = None
    prazo_dias: int | None = None
    data_retorno: date | None = None

    def para_dominio(self, frente: Frente):  # noqa: ANN201 - união das extensões
        match frente:
            case Frente.IMPRENSA:
                return Imprensa(
                    formato=self.formato,
                    data_atendida=self.data_atendida,
                    data_publicacao=self.data_publicacao,
                    link_materia=self.link_materia,
                    mensagens_chave=tuple(self.mensagens_chave),
                )
            case Frente.GOVERNO | Frente.PARCEIROS | Frente.EVENTOS:
                return Institucional(
                    natureza_orgao=self.natureza_orgao,
                    cargo_interlocutor=self.cargo_interlocutor,
                    nome_evento=self.nome_evento,
                )
            case Frente.LEGISLATIVO:
                return Legislativo(
                    casa=self.casa,
                    tramitacao=self.tramitacao,
                    prioridade=self.prioridade,
                    ementa=self.ementa,
                )
            case Frente.INVESTIDORES:
                return Investidores(
                    tipo_investidor=self.tipo_investidor, formato=self.formato
                )
            case Frente.INTERNA:
                return Interna(
                    natureza=self.natureza,
                    cumprimento=self.cumprimento,
                    complexidade=self.complexidade,
                    prazo_dias=self.prazo_dias,
                    data_retorno=self.data_retorno,
                )
        raise ValueError(f"Frente sem extensão definida: {frente}")


class InteracaoEntrada(BaseModel):
    """Corpo do POST."""

    model_config = ConfigDict(extra="forbid")

    frente: Frente
    data_interacao: date
    instituicao_id: UUID
    uf: str
    status: str
    pauta: str = Field(min_length=1)

    interlocutor_id: UUID | None = None
    unidade_negocio_id: int | None = None
    esfera_id: int | None = None
    tier: int | None = None
    stakeholder_id: int | None = None

    clima: str | None = None
    resultado: str | None = None
    iniciativa: str | None = None

    posicionamento: str | None = None
    relato: str | None = None
    encaminhamentos: str | None = None
    pendencias: str | None = None
    observacoes: str | None = None
    registro_url: str | None = None

    extensao: ExtensaoEntrada | None = None
    temas: list[int] = Field(default_factory=list)
    participacoes: list[ParticipacaoEntrada] = Field(default_factory=list)

    def para_dominio(self) -> Interacao:
        return Interacao(
            frente=self.frente,
            data_interacao=self.data_interacao,
            instituicao_id=self.instituicao_id,
            uf=self.uf.upper(),
            status=self.status,
            pauta=self.pauta.strip(),
            interlocutor_id=self.interlocutor_id,
            unidade_negocio_id=self.unidade_negocio_id,
            esfera_id=self.esfera_id,
            tier=self.tier,
            stakeholder_id=self.stakeholder_id,
            clima=self.clima,
            resultado=self.resultado,
            iniciativa=self.iniciativa,
            posicionamento=self.posicionamento,
            relato=self.relato,
            encaminhamentos=self.encaminhamentos,
            pendencias=self.pendencias,
            observacoes=self.observacoes,
            registro_url=self.registro_url,
            extensao=self.extensao.para_dominio(self.frente) if self.extensao else None,
            temas=tuple(self.temas),
            participacoes=tuple(
                ParticipacaoAegea(pessoa_aegea_id=p.pessoa_aegea_id, papel=p.papel)
                for p in self.participacoes
            ),
        )


class InteracaoEdicao(BaseModel):
    """Corpo do PATCH: só o que veio é alterado.

    `model_dump(exclude_unset=True)` distingue "não mandou o campo" de "mandou
    null para limpar" — a diferença importa em campos opcionais como `relato`.
    """

    model_config = ConfigDict(extra="forbid")

    frente: Frente | None = None
    data_interacao: date | None = None
    instituicao_id: UUID | None = None
    interlocutor_id: UUID | None = None
    unidade_negocio_id: int | None = None
    esfera_id: int | None = None
    uf: str | None = None
    tier: int | None = None
    stakeholder_id: int | None = None
    status: str | None = None
    clima: str | None = None
    resultado: str | None = None
    iniciativa: str | None = None
    pauta: str | None = None
    posicionamento: str | None = None
    relato: str | None = None
    encaminhamentos: str | None = None
    pendencias: str | None = None
    observacoes: str | None = None
    registro_url: str | None = None
    visivel: bool | None = None
    temas: list[int] | None = None
    participacoes: list[ParticipacaoEntrada] | None = None
    extensao: ExtensaoEntrada | None = None

    def alteracoes(self, frente_atual: Frente) -> dict[str, Any]:
        """Traduz o corpo em campos do agregado, só com o que foi enviado."""
        bruto = self.model_dump(exclude_unset=True)
        alteracoes: dict[str, Any] = {}

        frente = Frente(bruto["frente"]) if "frente" in bruto else frente_atual

        for campo, valor in bruto.items():
            match campo:
                case "extensao":
                    alteracoes["extensao"] = (
                        self.extensao.para_dominio(frente) if self.extensao else None
                    )
                case "temas":
                    alteracoes["temas"] = tuple(valor or ())
                case "participacoes":
                    alteracoes["participacoes"] = tuple(
                        ParticipacaoAegea(
                            pessoa_aegea_id=p["pessoa_aegea_id"], papel=p["papel"]
                        )
                        for p in (valor or ())
                    )
                case "uf":
                    alteracoes["uf"] = valor.upper() if valor else valor
                case "frente":
                    alteracoes["frente"] = frente
                case _:
                    alteracoes[campo] = valor

        # Trocar de frente sem mandar extensão só é problema quando a extensão
        # esperada muda de tipo. Governo, Parceiros e Eventos compartilham a
        # mesma (Institucional): trocar entre elas preserva natureza_orgao,
        # cargo_interlocutor e nome_evento, que continuam válidos.
        #
        # Quando o tipo muda de fato, recusamos em vez de apagar em silêncio —
        # descartar o conteúdo de um registro é decisão de quem edita, e o
        # cliente diz isso mandando `extensao: null` explicitamente.
        if "frente" in bruto and "extensao" not in bruto:
            if extensao_esperada(frente) is not extensao_esperada(frente_atual):
                raise RegraViolada(
                    f"Mudar a frente de {frente_atual.value!r} para {frente.value!r} "
                    "troca os campos específicos do registro. Envie `extensao` com os "
                    "dados da nova frente, ou `extensao: null` para descartar os da antiga."
                )

        return alteracoes


class ParticipacaoSaida(BaseModel):
    pessoa_aegea_id: UUID
    papel: str


class InteracaoSaida(BaseModel):
    """Corpo das respostas."""

    id: UUID
    frente: Frente
    data_interacao: date
    instituicao_id: UUID
    interlocutor_id: UUID | None
    unidade_negocio_id: int | None
    esfera_id: int | None
    uf: str
    tier: int | None
    stakeholder_id: int | None
    status: str
    clima: str | None
    resultado: str | None
    iniciativa: str | None
    pauta: str
    posicionamento: str | None
    relato: str | None
    encaminhamentos: str | None
    pendencias: str | None
    observacoes: str | None
    registro_url: str | None
    extensao: dict[str, Any] | None
    temas: list[int]
    participacoes: list[ParticipacaoSaida]
    fonte: str
    visivel: bool
    criado_por: UUID | None
    criado_em: datetime | None
    atualizado_em: datetime | None

    #: Campos que só saem no payload para quem tem `papel.ve_campos_sensiveis`.
    #:
    #: `relato` é a transcrição do que foi conversado; `pendencias` costuma
    #: carregar posicionamento ainda não público. Os dois são exatamente o que
    #: um terceiro não deveria levar embora — e a busca livre continua varrendo
    #: `relato`, então esconder o campo não esconde a existência do registro.
    CAMPOS_SENSIVEIS: ClassVar[tuple[str, ...]] = ("relato", "pendencias")

    @classmethod
    def de_dominio(
        cls, interacao: Interacao, *, ve_campos_sensiveis: bool = True
    ) -> InteracaoSaida:
        """Serializa o agregado, omitindo o que o papel não alcança.

        O padrão é `True` para não quebrar chamadas internas; toda rota passa o
        valor explicitamente a partir do papel de quem pediu.
        """
        from dataclasses import asdict

        saida = cls(
            id=interacao.id,
            frente=interacao.frente,
            data_interacao=interacao.data_interacao,
            instituicao_id=interacao.instituicao_id,
            interlocutor_id=interacao.interlocutor_id,
            unidade_negocio_id=interacao.unidade_negocio_id,
            esfera_id=interacao.esfera_id,
            uf=interacao.uf,
            tier=interacao.tier,
            stakeholder_id=interacao.stakeholder_id,
            status=interacao.status,
            clima=interacao.clima,
            resultado=interacao.resultado,
            iniciativa=interacao.iniciativa,
            pauta=interacao.pauta,
            posicionamento=interacao.posicionamento,
            relato=interacao.relato,
            encaminhamentos=interacao.encaminhamentos,
            pendencias=interacao.pendencias,
            observacoes=interacao.observacoes,
            registro_url=interacao.registro_url,
            extensao=asdict(interacao.extensao) if interacao.extensao else None,
            temas=list(interacao.temas),
            participacoes=[
                ParticipacaoSaida(pessoa_aegea_id=p.pessoa_aegea_id, papel=p.papel)
                for p in interacao.participacoes
            ],
            fonte=interacao.fonte,
            visivel=interacao.visivel,
            criado_por=interacao.criado_por,
            criado_em=interacao.criado_em,
            atualizado_em=interacao.atualizado_em,
        )

        if not ve_campos_sensiveis:
            # `model_copy` em vez de omitir o campo do modelo: o contrato da
            # API continua o mesmo para todo perfil, e o front não precisa
            # saber quem está olhando — só recebe nulo onde não tem direito.
            saida = saida.model_copy(
                update={campo: None for campo in cls.CAMPOS_SENSIVEIS}
            )

        return saida


class PaginaDeInteracoes(BaseModel):
    """A listagem, com o total do recorte que o painel exibe no cabeçalho."""

    itens: list[InteracaoSaida]
    total: int
    pagina: int
    tamanho: int
    paginas: int
    filtros_ativos: int
