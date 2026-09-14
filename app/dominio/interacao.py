"""O agregado raiz: uma interação com um stakeholder.

Uma tabela-mãe, sete frentes. Os campos comuns — os que os filtros do Recorte e as
agregações usam — moram aqui; o que é exclusivo de uma frente vive na extensão
correspondente, em `frentes/`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from uuid import UUID

from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    Extensao,
    Frente,
    extensao_esperada,
)
from app.dominio.recorte import ABRANGENCIAS_VALIDAS

#: Como o registro entrou no sistema.
FONTES = ("cadastro_manual", "importacao_planilha", "plataforma_ri")

#: Papéis que uma pessoa da Aegea pode ter numa interação.
#: PRESENÇA: o previsto e o real.
#:
#: `None` é NÃO INFORMADO, e é o estado de todo registro anterior a esta onda.
#: Tratá-lo como "ausente" faria a base afirmar que ninguém compareceu a
#: reuniões que aconteceram — e a diferença entre "não sabemos" e "não" é
#: exatamente o que esta plataforma existe para reduzir.
#:
#: `ausente` é a mais valiosa das três: uma reunião em que o decisor não
#: apareceu não é a reunião que foi pedida, ainda que conste como realizada.
PRESENCAS = ("previsto", "presente", "ausente")

#: MOMENTO DO MATERIAL. `apoio` existe antes da reunião; os outros dois, depois.
MODALIDADES = ("presencial", "online", "hibrida")

MOMENTOS_DE_MATERIAL = ("apoio", "obtido", "produzido")

#: Quem declinou. A leitura estratégica é oposta nos dois casos: declinar é
#: escolha da Aegea; ser declinado é porta que se fechou.
LADOS = ("aegea", "outra_parte")

PAPEL_PORTA_VOZ = "porta_voz"
PAPEL_EQUIPE = "equipe"
PAPEIS = (PAPEL_PORTA_VOZ, PAPEL_EQUIPE)


@dataclass(frozen=True, slots=True)
class ParticipacaoAegea:
    """Quem representou a Aegea, e em que papel.

    Uma interação pode ter mais de um porta-voz: "Radamés Casseb e André Pires"
    conta para os dois no painel de exposição.
    """

    pessoa_aegea_id: UUID
    papel: str = PAPEL_PORTA_VOZ
    #: Nulo = não informado. Ver `PRESENCAS`.
    presenca: str | None = None

    def __post_init__(self) -> None:
        if self.papel not in PAPEIS:
            raise RegraViolada(
                f"Papel inválido: {self.papel!r}. Use {' ou '.join(PAPEIS)}."
            )
        _exigir_presenca_valida(self.presenca)


def _exigir_presenca_valida(presenca: str | None) -> None:
    """Nulo passa; qualquer outra coisa fora da lista, não.

    A validação mora numa função porque os dois lados da mesa a usam, e uma
    cópia em cada lugar é como as duas listas divergem.
    """
    if presenca is not None and presenca not in PRESENCAS:
        raise RegraViolada(
            f"Presença inválida: {presenca!r}. Use {', '.join(PRESENCAS)}."
        )


@dataclass(frozen=True)
class ParticipanteDaOutraParte:
    """Quem participou pelo outro lado — o principal INCLUSIVE.

    O principal entra na lista como os outros, com uma marca — e não só em
    `interacao.interlocutor_id`. Fora da lista ele não teria onde ter presença:
    justamente a pessoa mais importante da reunião seria a única de quem não se
    sabe se compareceu.
    """

    interlocutor_id: UUID
    presenca: str | None = None
    principal: bool = False

    def __post_init__(self) -> None:
        _exigir_presenca_valida(self.presenca)


@dataclass(frozen=True, slots=True)
class ArquivoDoMaterial:
    """O arquivo guardado, como o domínio o conhece.

    Só o que a tela precisa mostrar sem ir ao armazenamento: nome para
    reconhecer, tipo para o ícone, tamanho para avisar antes do download. O
    `caminho` no blob NÃO entra aqui — é detalhe de onde o byte mora, e quem
    monta a ficha não tem o que fazer com ele.
    """

    id: UUID
    nome: str
    tipo_conteudo: str
    tamanho: int


@dataclass(frozen=True, slots=True)
class MaterialDaAgenda:
    """Um documento que circula em torno da agenda.

    Sem link e sem arquivo, um material é só um título — e um título sozinho
    não leva ninguém ao documento. Os DOIS caminhos valem: link para o que já
    mora fora, arquivo para o que se sobe aqui.
    """

    momento: str
    titulo: str
    url: str | None = None
    observacao: str | None = None
    id: UUID | None = None
    #: Preenchido na LEITURA, pelo repositório. Na escrita o que conta é
    #: `arquivo_id`: a tela devolve o id que o upload lhe deu, e não o objeto.
    arquivo: ArquivoDoMaterial | None = None
    arquivo_id: UUID | None = None
    #: De qual REFERÊNCIA da biblioteca este material veio. Nulo no que a
    #: pessoa escreveu à mão. A tela o usa para marcar a linha e para saber o
    #: que devolver quando o assunto é desmarcado.
    referencia_id: UUID | None = None
    #: DE QUE ASSUNTOS O DOCUMENTO TRATA.
    #:
    #: É o que faz a busca por assunto ser a mesma nas duas procedências: a
    #: referência da biblioteca e o documento que sai da reunião se organizam
    #: pelo mesmo eixo.
    temas: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.momento not in MOMENTOS_DE_MATERIAL:
            raise RegraViolada(
                f"Momento inválido: {self.momento!r}. "
                f"Use {', '.join(MOMENTOS_DE_MATERIAL)}."
            )
        if not self.titulo.strip():
            raise RegraViolada("Material precisa de título.")
        #: A MESMA REGRA DO BANCO (`material_precisa_apontar_para_algo`), aqui
        #: para dar a mensagem. O `check` protege o dado; ele não sabe dizer
        #: qual material está pela metade nem o que fazer a respeito.
        tem_arquivo = self.arquivo_id is not None or self.arquivo is not None
        if not (self.url or "").strip() and not tem_arquivo:
            raise RegraViolada(
                f"O material {self.titulo!r} não leva a lugar nenhum: "
                "suba um arquivo ou informe um link."
            )


@dataclass
class Interacao:
    """Uma interação institucional registrada.

    O construtor valida as invariantes; a edição volta a validá-las por
    `revalidar()`. Nenhum caminho grava um registro que o domínio recusaria.
    """

    # identidade e recorte
    frente: Frente
    data_interacao: date
    instituicao_id: UUID
    uf: str
    status: str
    #: OPCIONAL, e fora da tela de cadastro: `temas` diz o assunto de forma
    #: classificada — que e o que o painel consegue somar — e `expectativa` diz
    #: o que se quer dele. A pauta seria a terceira forma de dizer a mesma
    #: coisa, e a unica que ninguem consegue agregar.
    #:
    #: Vem preenchida nos registros que nasceram da planilha, onde e a unica
    #: descricao em palavras que existe.
    pauta: str | None = None

    id: UUID | None = None
    interlocutor_id: UUID | None = None
    unidade_negocio_id: int | None = None
    esfera_id: int | None = None
    tier: int | None = None
    stakeholder_id: int | None = None

    # classificação
    clima: str | None = None
    resultado: str | None = None
    iniciativa: str | None = None

    # conteúdo
    posicionamento: str | None = None
    relato: str | None = None
    encaminhamentos: str | None = None
    pendencias: str | None = None
    observacoes: str | None = None
    registro_url: str | None = None
    #: `presencial`, `online` ou `hibrida`. Nulo = nao informado.
    modalidade: str | None = None
    #: Onde, em palavras: endereco, sala, ou o link da chamada.
    local: str | None = None

    # relações
    extensao: Extensao | None = None
    temas: tuple[int, ...] = ()
    #: DE QUAIS ÁREAS INTERNAS DA AEGEA esta interação trata — Comunicação,
    #: Relações Institucionais etc. Mesmo papel de `temas`, num vocabulário
    #: diferente: o de onde, e não o sobre o quê.
    areas: tuple[int, ...] = ()
    participacoes: tuple[ParticipacaoAegea, ...] = ()

    # -- o ciclo da agenda ----------------------------------------------------
    #
    # A interação é a agenda inteira, e não só o registro do que aconteceu: ela
    # nasce como PEDIDO, é planejada, confirmada ou declinada, realizada, e
    # desdobra em outra. Os campos abaixo guardam o lado PREVISTO — e é a
    # distância entre ele e `relato`/`clima` que mede se o que se promete
    # costuma acontecer.
    #
    # Nulo em todos: não informado. Nunca "não".
    expectativa: str | None = None
    declinado_por: str | None = None
    motivo_declinio: str | None = None
    #: Em que condições foi aceita. Ver `motivo_declinio`, que é o outro lado.
    nota_situacao: str | None = None
    #: DE QUAIS agendas esta decorre. Vazio = nasceu sozinha.
    #:
    #: Plural: com um pai so, "a agencia e a bancada levaram juntas a esta
    #: reuniao" perderia uma das duas — e e justamente o caso que o grafo
    #: existe para mostrar.
    origens: tuple[UUID, ...] = ()
    #: QUANTAS agendas decorrem desta. So leitura — quem escreve o elo e a
    #: agenda que descende.
    #:
    #: Vem do servidor, e nao contada na tela: a descendente pode estar fora do
    #: recorte carregado, e contar so o que a tela ve diria "nao faz parte de
    #: cadeia" para uma agenda que faz.
    derivadas: int = 0
    preve_desdobramento: bool | None = None
    outra_parte: tuple[ParticipanteDaOutraParte, ...] = ()
    materiais: tuple[MaterialDaAgenda, ...] = ()
    #: O clima que se ESPERAVA, na mesma escala de `clima`. É o que permite o
    #: painel comparar previsto com realizado como número, e não como leitura.
    clima_esperado: str | None = None

    # procedência e ciclo de vida
    fonte: str = "cadastro_manual"
    visivel: bool = True
    origem_aba: str | None = None
    origem_linha: int | None = None
    criado_por: UUID | None = None
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None
    arquivado_em: datetime | None = None

    def __post_init__(self) -> None:
        self.frente = Frente(self.frente)
        self.revalidar()

    # -- invariantes ---------------------------------------------------------

    def revalidar(self) -> None:
        """Garante que o agregado está íntegro. Chamado na criação e na edição."""
        # A MESMA REGRA DO `check` DO BANCO, aqui para dar a mensagem. O banco
        # protege o dado; ele nao sabe dizer que "remoto" nao existe e que o
        # valor procurado e "online".
        if self.modalidade is not None and self.modalidade not in MODALIDADES:
            raise RegraViolada(
                f"Modalidade invalida: {self.modalidade!r}. "
                f"Use {', '.join(MODALIDADES)}."
            )

        if self.uf not in ABRANGENCIAS_VALIDAS:
            raise RegraViolada(
                f"Abrangência inválida: {self.uf!r}. Use uma das 27 UFs, "
                "'NA' (nacional) ou 'IN' (internacional). O mapa do painel depende dela."
            )

        if self.tier is not None and self.tier < 1:
            raise RegraViolada(f"Tier inválido: {self.tier!r}. Use um número positivo.")
        # QUAIS números existem é decisão do BANCO, não daqui: os níveis são
        # linhas em `relevancia`, e `interacao.tier` tem chave estrangeira para
        # lá. Repetir a lista neste ponto criaria uma segunda fonte da verdade
        # que nada obriga a concordar com a primeira — foi exatamente o que
        # havia antes: QUATRO cópias da mesma lista — esta, uma em
        # `dominio/recorte.py`, um `check between 1 and 3` no schema e as opções
        # escritas à mão no filtro do front, em outro repositório.
        #
        # Um número inexistente vira violação de chave estrangeira, traduzida
        # para `RegraViolada` na borda do banco.

        if self.fonte not in FONTES:
            raise RegraViolada(
                f"Fonte inválida: {self.fonte!r}. Use {', '.join(FONTES)}."
            )

        self._validar_extensao()
        self._validar_participacoes()
        self._validar_ciclo()

    def _validar_ciclo(self) -> None:
        """As invariantes da agenda como CICLO, e não como fato isolado."""
        if self.declinado_por is not None and self.declinado_por not in LADOS:
            raise RegraViolada(
                f"Lado inválido: {self.declinado_por!r}. Use {' ou '.join(LADOS)}."
            )

        # MOTIVO SEM LADO É METADE DA INFORMAÇÃO.
        #
        # "Declinada por falta de agenda" não diz quem ficou sem agenda — e a
        # leitura muda por inteiro: se foi a Aegea, houve escolha; se foi a
        # outra parte, houve porta fechada. Guardar o motivo sem o lado produz
        # uma linha que ninguém consegue interpretar depois.
        if self.motivo_declinio and self.declinado_por is None:
            raise RegraViolada(
                "Informe quem declinou: o motivo sozinho não diz de que lado "
                "veio a recusa, e é o lado que muda a leitura."
            )

        # Uma agenda não nasce de si mesma. O banco também barra o caso
        # trivial; aqui a mensagem explica, em vez de mostrar uma violação de
        # `check` ao usuário.
        #
        # PLURAL desde a 0017: basta ela aparecer entre as origens. O ciclo
        # mais longo — A vem de B, que vem de A — não cabe aqui: exige subir o
        # grafo, e quem faz isso é o repositório.
        if self.id is not None and self.id in self.origens:
            raise RegraViolada("Uma agenda não pode ter origem em si mesma.")

        if len(set(self.origens)) != len(self.origens):
            raise RegraViolada(
                "A mesma agenda aparece duas vezes entre as origens desta."
            )

        vistos: set[UUID] = set()
        for participante in self.outra_parte:
            if participante.interlocutor_id in vistos:
                raise RegraViolada(
                    "A mesma pessoa aparece duas vezes entre os participantes "
                    "da outra parte."
                )
            vistos.add(participante.interlocutor_id)

        # O PRINCIPAL MORA NA LISTA, e não fora dela.
        #
        # Ele é um participante como os outros, com uma marca — proibi-lo aqui
        # é o que o deixaria sem presença. As duas invariantes abaixo são o que
        # mantém a marca significando alguma coisa.
        principais = [p for p in self.outra_parte if p.principal]
        if len(principais) > 1:
            raise RegraViolada(
                "Só uma pessoa da outra parte pode ser a principal."
            )

        # `interacao.interlocutor_id` continua existindo, e 67 usos dependem
        # dele. Ele e a marca na lista precisam dizer a MESMA coisa, senão o
        # filtro por pessoa e a ficha discordam sobre quem representa a outra
        # parte — e ninguém saberia qual das duas está certa.
        if principais and self.interlocutor_id is not None:
            if principais[0].interlocutor_id != self.interlocutor_id:
                raise RegraViolada(
                    "O participante marcado como principal não é o mesmo "
                    "registrado como interlocutor da agenda."
                )

    def _validar_extensao(self) -> None:
        if self.extensao is None:
            return
        esperada = extensao_esperada(self.frente)
        if not isinstance(self.extensao, esperada):
            raise RegraViolada(
                f"A frente {self.frente.value!r} espera dados de "
                f"{esperada.__name__}, e recebeu {type(self.extensao).__name__}."
            )

    def _validar_participacoes(self) -> None:
        vistos: set[tuple[UUID, str]] = set()
        for participacao in self.participacoes:
            chave = (participacao.pessoa_aegea_id, participacao.papel)
            if chave in vistos:
                raise RegraViolada(
                    "A mesma pessoa aparece duas vezes no mesmo papel nesta interação."
                )
            vistos.add(chave)

    # -- comportamento -------------------------------------------------------

    @property
    def arquivada(self) -> bool:
        return self.arquivado_em is not None

    @property
    def porta_vozes(self) -> tuple[UUID, ...]:
        """Todos os porta-vozes do registro — a base do painel de exposição."""
        return tuple(
            p.pessoa_aegea_id for p in self.participacoes if p.papel == PAPEL_PORTA_VOZ
        )

    def dias_parada(self, hoje: date | None = None) -> int:
        """Dias desde a interação. Alimenta a fila de pendências."""
        return ((hoje or date.today()) - self.data_interacao).days

    def alterar(self, **campos: object) -> None:
        """Aplica alterações e revalida o agregado inteiro.

        Um `alterar` que quebre uma invariante levanta antes de qualquer coisa
        chegar ao banco.
        """
        desconhecidos = set(campos) - {f.name for f in _campos_editaveis()}
        if desconhecidos:
            raise RegraViolada(
                f"Campo inexistente ou não editável: {', '.join(sorted(desconhecidos))}."
            )

        for nome, valor in campos.items():
            setattr(self, nome, valor)

        if "frente" in campos:
            self.frente = Frente(self.frente)

        self.revalidar()


def _campos_editaveis() -> tuple[object, ...]:
    """Tudo, menos identidade e trilha de auditoria."""
    imutaveis = {
        "id", "criado_por", "criado_em", "atualizado_em",
        "arquivado_em", "origem_aba", "origem_linha",
    }
    return tuple(f for f in fields(Interacao) if f.name not in imutaveis)
