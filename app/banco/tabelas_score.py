"""O Score Executivo, no banco. Espelha `migrations/0048`.

O índice mensal tem quatro coisas guardadas e uma calculada:

    lente               as cinco famílias de stakeholder — fechado
    score_fonte         de onde vem o sentimento de cada lente — extensível
    mencao              o grão fino: uma linha por matéria, post ou mensagem
    score_mes_fonte     as somas mensais, no grão que toda régua consome
    score_estimativa    o NS suposto, onde não houve medição
    score_config        a régua em vigor, versionada
    score_fato          o que explica a curva, escrito por gente
    planilha_recebida   o arquivo esperando entre conferir e confirmar (0092)

O score em si não mora aqui: é calculado na leitura, por `app/dominio/score.py`,
porque a régua que o produz é configurável — ver o cabeçalho da 0048.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.banco.sessao import Tabela


class Lente(Tabela):
    """Uma das cinco famílias de stakeholder que o ISR pondera."""

    __tablename__ = "lente"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    stakeholder: Mapped[str] = mapped_column(Text)
    #: O peso de fábrica; a calibração vigente pode sobrepor.
    peso_padrao: Mapped[int] = mapped_column(SmallInteger)
    ordem: Mapped[int] = mapped_column(SmallInteger)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class ScoreFonte(Tabela):
    """Um fornecedor de sentimento. Novo fornecedor é linha, não deploy."""

    __tablename__ = "score_fonte"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    fornecedor: Mapped[str] = mapped_column(Text)
    #: Nulo é "fonte que não alimenta lente nenhuma" (`0114`): o caso da
    #: fonte interna. As leituras alcançam esta coluna por igualdade, `in_` e
    #: `join`, e nulo fica de fora das três — o isolamento é estrutural.
    #: Ver `app/dominio/fontes_do_score.py`.
    lente_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("lente.id"), nullable=True
    )
    tipo_arquivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Qual coluna da planilha alimenta qual campo de `mencao`.
    mapeamento_colunas: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Fonte interna não se ingere — o dado já está neste banco (hoje, o CRM).
    interna: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ordem: Mapped[int] = mapped_column(SmallInteger, default=0)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)


class Mencao(Tabela):
    """Uma matéria, post ou mensagem, já no vocabulário do índice."""

    __tablename__ = "mencao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fonte_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("score_fonte.id"))
    #: O primeiro dia do mês, sempre.
    mes: Mapped[date] = mapped_column(Date)
    data: Mapped[date | None] = mapped_column(Date, nullable=True)
    sentimento: Mapped[str] = mapped_column(Text)
    tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    engajamento: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    unidade_negocio_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("unidade_negocio.id"), nullable=True
    )
    #: OS TRÊS NÍVEIS DA TAXONOMIA DO CADASTRO: `bloco_tema` (N1) >
    #: `macro_tema` (N2) > `tema` (N3). Ver `0098`.
    #:
    #: POR QUE TRÊS COLUNAS E NÃO SÓ O N3. Com `tema_id` sozinho, o N2 e o N1
    #: eram alcançados por `join` a partir dele — o que serve à menção que TEM
    #: N3 e deixa sem nível nenhum a que o fornecedor só descreveu no topo —
    #: que então não aparecia em recorte por pilar algum.
    #:
    #: SÃO CHAVE, E O TEXTO DO FORNECEDOR CONTINUA DO LADO. `tema_texto`,
    #: `subtema` e `atributo` guardam a palavra exata da planilha, porque é
    #: contra ela que a carga é auditável; estas três dizem onde o CADASTRO
    #: colocou a menção. É o mesmo par que `instituicao_id`/`veiculo` forma.
    #:
    #: NUNCA SE DESCE: um N1 não preenche o N2 nem o N3. A regra inteira está em
    #: `app/dominio/niveis_de_taxonomia.py`.
    bloco_tema_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("bloco_tema.id"), nullable=True
    )
    macro_tema_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("macro_tema.id"), nullable=True
    )
    tema_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tema.id"), nullable=True)
    #: O VEÍCULO NO CADASTRO COMPARTILHADO — `instituicao` com `tipo='veiculo'`.
    #: A terceira ponte para o cadastro, e a última a existir (`0065`).
    #:
    #: É ELA QUE DÁ O CRITÉRIO DA LENTE MERCADO. A subcategoria de público do
    #: veículo ("Econômica e de negócios", sob Imprensa, cuja `padrao_de_quebra`
    #: é `logica_editorial`) substitui o filtro por `Público-alvo =
    #: Investidores`, que alcançava uma fração do que a lista de veículos do
    #: mercado financeiro alcança.
    #:
    #: `ondelete="SET NULL"`: apagar um veículo do cadastro não pode apagar a
    #: menção — ela é fato do mês, e o vínculo é enriquecimento.
    instituicao_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instituicao.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: O assunto no vocabulário do FORNECEDOR, que não é o do CRM.
    tema_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A concessionária como o fornecedor a nomeia — idem.
    unidade_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    atributo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O teor da mensagem no vocabulário do fornecedor — Reclamação, Dúvida,
    #: Elogio, Informação, Marcação, NPR (0049).
    teor: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Se é um contato de verdade. Marcação e NPR chegam pelo mesmo canal e não
    #: são gente procurando a companhia — mas continuam contadas.
    acionavel: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Quem assina a matéria. Nulo em tudo hoje: a Clipei não manda a coluna.
    autor: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- os campos do padrão Aegea que a Sociedade digital usa (0055) ---------
    #
    # O PACOTE DE PRODUÇÃO DAS LENTES define uma planilha única de 40 colunas por
    # item, igual para as cinco lentes. Onze delas moram acima com o nome que o
    # índice usa — `sentimento` é `classificacao` no padrão, `veiculo` é
    # `veiculo_rede`, `tema_texto` é `tema`, `unidade_texto` é `empresa_citada`,
    # `cargo` é `cargo_autor`. As colunas das outras lentes entram na migration
    # da etapa daquela lente, com dado dentro.

    #: O id do item no sistema do fornecedor. É a chave natural da carga: com
    #: ela, reimportar o mesmo mês atualiza em vez de duplicar.
    id_fonte: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A UF do autor ou do assunto — um dos cortes que o pacote pede, e base do
    #: KPI `uf_mais_negativa`.
    uf: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O segundo nível do assunto, abaixo de `tema_texto`: é o corte que explica
    #: POR QUE um tema pesa.
    subtema: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Quem fala: Cidadão, Figura pública, Imprensa, Perfil institucional. É o
    #: que separa "mil cidadãos reclamando" de "um deputado reclamando" — duas
    #: coisas com o mesmo sinal e consequências diferentes.
    perfil_autor: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O texto da menção e o endereço dela. Vêm só numa amostra (as negativas,
    #: as de tier alto e as mais engajadas); o pacote diz que isso é esperado, e
    #: a tela tem de saber viver com a ausência.
    titulo_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O peso que o PADRÃO dá ao item, como o fornecedor o enviou: 1 na
    #: Sociedade, 10/5/1 pelo tier do veículo na Imprensa. É DADO, e não régua —
    #: a nota sai da calibração vigente (`dominio/score.py`), que é o que a tela
    #: de Calibração deixa mudar. Guardado para a ficha do item poder explicar o
    #: próprio peso e para a carga ser auditável contra o que a fonte afirmou.
    peso_tier: Mapped[float] = mapped_column(Numeric(4, 1), default=1)
    veiculo: Mapped[str | None] = mapped_column(Text, nullable=True)
    publico_alvo: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreMesFonte(Tabela):
    """As somas de um mês, no grão (fonte, sentimento, tier).

    É daqui que toda régua de ponderação tira o número — ver
    `dominio/score.py::ponderar`.
    """

    __tablename__ = "score_mes_fonte"

    fonte_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("score_fonte.id"), primary_key=True
    )
    mes: Mapped[date] = mapped_column(Date, primary_key=True)
    sentimento: Mapped[str] = mapped_column(Text, primary_key=True)
    #: Vazio, e não nulo, quando a fonte não tem tier: é chave primária.
    tier: Mapped[str] = mapped_column(Text, primary_key=True, default="")

    mencoes: Mapped[int] = mapped_column(Integer, default=0)
    soma_log: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    soma_engajamento: Mapped[int] = mapped_column(BigInteger, default=0)
    soma_cargo: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    atualizado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreEstimativa(Tabela):
    """O NS suposto de uma lente num mês sem export, com a origem escrita."""

    __tablename__ = "score_estimativa"

    lente_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("lente.id"), primary_key=True)
    mes: Mapped[date] = mapped_column(Date, primary_key=True)
    ns: Mapped[float] = mapped_column(Numeric(4, 3))
    #: De onde veio o número — uma estimativa sem procedência é um palpite.
    origem: Mapped[str] = mapped_column(Text)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreConfig(Tabela):
    """A calibração. Versionada: a linha mais recente é a vigente."""

    __tablename__ = "score_config"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Cresce sozinho e não empata — `criado_em` é o instante da transação, e
    #: duas versões gravadas juntas teriam o mesmo carimbo.
    versao: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    pesos: Mapped[dict] = mapped_column(JSONB, default=dict)
    regua_tier: Mapped[str] = mapped_column(Text, default="aegea")
    regua_engajamento: Mapped[str] = mapped_column(Text, default="n")
    fontes_desligadas: Mapped[list] = mapped_column(JSONB, default=list)
    #: Cortes dos detectores de sinal. CHAVE AUSENTE É O PADRÃO DO CÓDIGO, e
    #: não zero: uma régua gravada antes da 0050 não conhece limite nenhum, e
    #: zero produziria divisão por zero em todo detector que normaliza pelo
    #: próprio corte.
    limites: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Largura da fatia no gráfico radial: o peso efetivo, ou fatias iguais.
    radial_por_peso: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class ScoreFato(Tabela):
    """O que explica a curva do mês — texto de gente, não derivação."""

    __tablename__ = "score_fato"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mes: Mapped[date] = mapped_column(Date)
    texto: Mapped[str] = mapped_column(Text)
    #: `sustenta` | `pressiona` | `misto`
    efeito: Mapped[str] = mapped_column(Text)
    criado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())


class PlanilhaRecebida(Tabela):
    """A planilha que já subiu e espera a confirmação. Espelha a `0092`.

    GUARDA O BYTE, NUNCA A CONCLUSÃO: nada do que a conferência calculou está
    aqui. A confirmação relê a planilha inteira e reconfere contra o cadastro
    do instante em que ela roda — o que esta linha dispensa é o UPLOAD, e só.
    """

    __tablename__ = "planilha_recebida"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fonte_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("score_fonte.id"))
    #: Onde o byte mora. Quem monta a árvore é `blob.caminho_da_planilha`.
    caminho: Mapped[str] = mapped_column(Text)
    #: O nome que a pessoa escolheu, para a tela dizer o que ela vai confirmar.
    nome: Mapped[str] = mapped_column(Text)
    tamanho: Mapped[int] = mapped_column(Integer)
    #: CONTROLE DE ACESSO, não auditoria: só quem conferiu confirma. Por isso
    #: NOT NULL — uma linha sem dono não teria como ser recusada.
    criado_por: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id")
    )
    criado_em: Mapped[datetime] = mapped_column(server_default=func.now())
    #: NULO ENQUANTO A PLANILHA SOBE EM PARTES. Ver a `0094`.
    #:
    #: É O QUE DÁ DONO À SUBIDA: com a linha gravada desde a abertura, "de quem
    #: é esta subida" deixa de ser pergunta sem resposta — e a resposta é a
    #: verificação. Sem ela o `planilha_id` valia como senha ao portador.
    #:
    #: E É O QUE IMPEDE BYTE ÓRFÃO: a linha nasce antes do arquivo, então uma
    #: conferência que falhe em qualquer ponto — inclusive no commit, que roda
    #: depois de a rota retornar — deixa uma linha INCOMPLETA apontando para o
    #: byte, em vez de um arquivo que ninguém sabe que existe.
    #:
    #: TIMESTAMP E NÃO BOOLEANO: diz também QUANDO terminou, que é o que uma
    #: varredura por idade vai precisar para separar subida abandonada de
    #: planilha conferida e esquecida.
    completa_em: Mapped[datetime | None] = mapped_column(nullable=True)

    @property
    def subindo(self) -> bool:
        """A planilha ainda está chegando em partes?

        PROPRIEDADE E NÃO COMPARAÇÃO SOLTA: `completa_em is None` espalhado por
        quatro lugares é a forma de um deles divergir. E a leitura de
        `recuperar` depende disto — confirmar uma planilha que ainda sobe leria
        um arquivo que não existe, ou pior, um pela metade.
        """
        return self.completa_em is None
