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
    MaterialDaAgenda,
    ParticipacaoAegea,
    ParticipanteDaOutraParte,
)


class ParticipacaoEntrada(BaseModel):
    pessoa_aegea_id: UUID
    papel: str = "porta_voz"
    #: Nulo = não informado. Nunca "ausente" por omissão.
    presenca: str | None = None


class ParticipanteDaOutraParteEntrada(BaseModel):
    """Alguém da outra parte — o principal inclusive, com a marca."""

    interlocutor_id: UUID
    presenca: str | None = None
    principal: bool = False


class ArquivoSaida(BaseModel):
    """O arquivo de um material, como a tela o ve.

    Sem o `caminho` no blob: quem monta a ficha nao tem o que fazer com ele, e
    dizer onde o byte mora e contar como o contenedor e organizado.
    """

    id: UUID
    nome: str
    tipo_conteudo: str
    tamanho: int


class MaterialSaida(BaseModel):
    """O material como sai. Tem `id` porque a tela precisa apagar um deles."""

    id: UUID | None = None
    momento: str
    titulo: str
    url: str | None = None
    observacao: str | None = None
    #: De qual referencia da biblioteca este material veio.
    #:
    #: Vai e VOLTA: sem o retorno, a tela reabriria a agenda sem saber quais
    #: linhas vieram da biblioteca — e desmarcar um assunto nao teria como
    #: distinguir o que ele trouxe do que a pessoa acrescentou.
    referencia_id: UUID | None = None
    #: De que assuntos o documento trata.
    temas: list[int] = Field(default_factory=list)
    #: Nulo quando o material e um LINK. Os dois caminhos convivem.
    arquivo: ArquivoSaida | None = None


class MaterialEntrada(BaseModel):
    """Um documento da agenda.

    `url` e `arquivo_id` sao ambos opcionais AQUI, e o dominio exige um dos
    dois. A validacao fica la para a mensagem sair em portugues dizendo o que
    fazer — "suba um arquivo ou informe um link" —, e nao como erro de campo
    obrigatorio que nao explica a alternativa.
    """

    #: O arquivo ja subido, pelo `POST .../materiais/arquivo`. A tela devolve o
    #: id que o upload lhe deu; o byte ja esta no blob quando esta rota corre.
    arquivo_id: UUID | None = None

    #: O `id` DE VOLTA, e sem ele o resto não funciona.
    #:
    #: O repositório casa material por `id` para não trocar a identidade de
    #: todos a cada salvamento. Isso só vale se o cliente devolver o `id` que
    #: recebeu — e este campo não existia. O Pydantic descartava o campo em
    #: SILÊNCIO (o `extra="forbid"` de `InteracaoEdicao` não alcança modelo
    #: aninhado), então toda edição chegava sem `id` e recriava tudo. Medido
    #: por HTTP: o `id` voltava diferente do enviado.
    #:
    #: Mandar o `id` de um material de OUTRA interação não sequestra nada: o
    #: casamento só olha os materiais daquele registro, e um `id` desconhecido
    #: cai no ramo de criação.
    id: UUID | None = None

    momento: str
    titulo: str
    url: str | None = None
    observacao: str | None = None
    #: De qual referencia da biblioteca este material veio.
    #:
    #: Vai e VOLTA: sem o retorno, reabrir a agenda perderia quais linhas vieram
    #: da biblioteca — e desmarcar um assunto nao teria como distinguir o que
    #: ele trouxe do que a pessoa acrescentou.
    referencia_id: UUID | None = None
    #: De que assuntos o documento trata. Vazio no que ninguem classificou.
    temas: list[int] = Field(default_factory=list)


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
            case Frente.GOVERNO | Frente.PARCEIROS | Frente.EVENTOS | Frente.BANCOS_CREDORES:
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
    #: O ESTADO EM QUE UMA AGENDA COMECA, e o backend e o dono dele.
    #:
    #: Exigi-lo na criacao contradiria o proprio desenho — a agenda nasce com o
    #: que a IDENTIFICA — e obrigaria cada cliente a saber qual e o estado
    #: inicial. Um `POST` so com frente, data, instituicao e uf tem de passar.
    #:
    #: `solicitado` e nao `agendado`: dizer "agendado" afirma que existe data
    #: marcada com a outra parte, e no instante da criacao ninguem confirmou
    #: isso. A distancia entre pedir e conseguir marcar e metade do que este
    #: painel mede.
    status: str = "solicitado"
    #: Sem `min_length`: a agenda nasce com o que a IDENTIFICA, e o assunto em
    #: palavras nao e exigido — `temas` e `expectativa` ocupam o lugar.
    pauta: str | None = None

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

    # -- o ciclo da agenda ----------------------------------------------------
    expectativa: str | None = None
    clima_esperado: str | None = None
    declinado_por: str | None = None
    motivo_declinio: str | None = None
    nota_situacao: str | None = None
    origens: list[UUID] = Field(default_factory=list)
    preve_desdobramento: bool | None = None
    outra_parte: list[ParticipanteDaOutraParteEntrada] = Field(default_factory=list)
    materiais: list[MaterialEntrada] = Field(default_factory=list)
    pendencias: str | None = None
    observacoes: str | None = None
    registro_url: str | None = None
    modalidade: str | None = None
    local: str | None = None

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
            pauta=self.pauta.strip() if self.pauta else None,
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
            modalidade=self.modalidade,
            local=self.local,
            extensao=self.extensao.para_dominio(self.frente) if self.extensao else None,
            temas=tuple(self.temas),
            participacoes=tuple(
                ParticipacaoAegea(
                    pessoa_aegea_id=p.pessoa_aegea_id,
                    papel=p.papel,
                    presenca=p.presenca,
                )
                for p in self.participacoes
            ),
            expectativa=self.expectativa,
            clima_esperado=self.clima_esperado,
            declinado_por=self.declinado_por,
            motivo_declinio=self.motivo_declinio,
            nota_situacao=self.nota_situacao,
            origens=tuple(self.origens),
            preve_desdobramento=self.preve_desdobramento,
            outra_parte=tuple(
                ParticipanteDaOutraParte(
                    interlocutor_id=p.interlocutor_id,
                    presenca=p.presenca,
                    principal=p.principal,
                )
                for p in self.outra_parte
            ),
            materiais=tuple(
                MaterialDaAgenda(
                    momento=m.momento,
                    titulo=m.titulo,
                    url=m.url,
                    arquivo_id=m.arquivo_id,
                    observacao=m.observacao,
                    referencia_id=m.referencia_id,
                    temas=tuple(m.temas),
                )
                for m in self.materiais
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
    modalidade: str | None = None
    local: str | None = None
    visivel: bool | None = None
    temas: list[int] | None = None
    participacoes: list[ParticipacaoEntrada] | None = None
    extensao: ExtensaoEntrada | None = None

    # -- o ciclo da agenda ----------------------------------------------------
    #
    # TODOS EDITÁVEIS, e não só preenchíveis na criação. `model_config` é
    # `extra="forbid"`: um campo que exista no `POST` e falte aqui devolve 422
    # na edição, e o formulário não tem como saber por quê.
    expectativa: str | None = None
    clima_esperado: str | None = None
    declinado_por: str | None = None
    motivo_declinio: str | None = None
    nota_situacao: str | None = None
    origens: list[UUID] = Field(default_factory=list)
    preve_desdobramento: bool | None = None
    outra_parte: list[ParticipanteDaOutraParteEntrada] | None = None
    materiais: list[MaterialEntrada] | None = None

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
                            pessoa_aegea_id=p["pessoa_aegea_id"],
                            papel=p["papel"],
                            # Faltava, e o PATCH apagava a presença de quem
                            # representou a Aegea a cada edição.
                            presenca=p.get("presenca"),
                        )
                        for p in (valor or ())
                    )
                case "outra_parte":
                    alteracoes["outra_parte"] = tuple(
                        ParticipanteDaOutraParte(
                            interlocutor_id=p["interlocutor_id"],
                            presenca=p.get("presenca"),
                            principal=p.get("principal", False),
                        )
                        for p in (valor or ())
                    )
                case "materiais":
                    alteracoes["materiais"] = tuple(
                        MaterialDaAgenda(
                            momento=m["momento"],
                            titulo=m["titulo"],
                            url=m.get("url"),
                            arquivo_id=m.get("arquivo_id"),
                            observacao=m.get("observacao"),
                            id=m.get("id"),
                            referencia_id=m.get("referencia_id"),
                            temas=tuple(m.get("temas") or ()),
                        )
                        for m in (valor or ())
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
    #: Faltava. O campo existia no banco e no domínio, e morria aqui: quem
    #: lesse a ficha nunca saberia se o porta-voz compareceu.
    presenca: str | None = None


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
    pauta: str | None = None
    posicionamento: str | None
    relato: str | None
    encaminhamentos: str | None
    pendencias: str | None
    observacoes: str | None
    registro_url: str | None
    #: `presencial` | `online` | `hibrida`. Nulo = nao informado.
    modalidade: str | None = None
    local: str | None = None
    extensao: dict[str, Any] | None
    temas: list[int]
    participacoes: list[ParticipacaoSaida]

    # -- o ciclo da agenda ----------------------------------------------------
    expectativa: str | None = None
    clima_esperado: str | None = None
    declinado_por: str | None = None
    motivo_declinio: str | None = None
    nota_situacao: str | None = None
    origens: list[UUID] = Field(default_factory=list)
    #: Quantas agendas decorrem desta. SO SAIDA: o lado inverso nao se
    #: escreve — quem grava o elo e a agenda que descende.
    derivadas: int = 0
    preve_desdobramento: bool | None = None
    outra_parte: list[ParticipanteDaOutraParteEntrada] = Field(default_factory=list)
    materiais: list[MaterialSaida] = Field(default_factory=list)

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
            modalidade=interacao.modalidade,
            local=interacao.local,
            expectativa=interacao.expectativa,
            clima_esperado=interacao.clima_esperado,
            declinado_por=interacao.declinado_por,
            motivo_declinio=interacao.motivo_declinio,
            nota_situacao=interacao.nota_situacao,
            origens=list(interacao.origens),
            derivadas=interacao.derivadas,
            preve_desdobramento=interacao.preve_desdobramento,
            outra_parte=[
                ParticipanteDaOutraParteEntrada(
                    interlocutor_id=p.interlocutor_id,
                    presenca=p.presenca,
                    principal=p.principal,
                )
                for p in interacao.outra_parte
            ],
            materiais=[
                MaterialSaida(
                    id=m.id,
                    momento=m.momento,
                    titulo=m.titulo,
                    url=m.url,
                    observacao=m.observacao,
                    referencia_id=m.referencia_id,
                    temas=list(m.temas),
                    # PREENCHIDO, e nao so declarado. Ver o commit da presenca
                    # do porta-voz: campo declarado aqui e nao passado no
                    # construtor sai `None` para sempre, com 200 na resposta.
                    arquivo=(
                        ArquivoSaida(
                            id=m.arquivo.id,
                            nome=m.arquivo.nome,
                            tipo_conteudo=m.arquivo.tipo_conteudo,
                            tamanho=m.arquivo.tamanho,
                        )
                        if m.arquivo is not None
                        else None
                    ),
                )
                for m in interacao.materiais
            ],
            extensao=asdict(interacao.extensao) if interacao.extensao else None,
            temas=list(interacao.temas),
            participacoes=[
                ParticipacaoSaida(
                    pessoa_aegea_id=p.pessoa_aegea_id,
                    papel=p.papel,
                    # DECLARAR O CAMPO NÃO É PREENCHÊ-LO. `presenca` foi
                    # acrescentada a `ParticipacaoSaida` com um comentário
                    # dizendo que ela "morria aqui" — e continuou morrendo,
                    # porque o construtor não a passava e o valor-padrão é
                    # `None`. O banco gravava, o domínio carregava, e a API
                    # respondia nulo: um PATCH com `presenca` devolvia 200 e a
                    # tela concluía que o servidor tinha ignorado o gesto.
                    #
                    # Medido pela API, não por leitura: só o round-trip
                    # completo separou "não grava" de "não devolve".
                    presenca=p.presenca,
                )
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
