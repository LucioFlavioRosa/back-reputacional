"""Quem está do outro lado, e quem representa a Aegea."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.banco.sessao import Tabela


class Instituicao(Tabela):
    __tablename__ = "instituicao"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    #: Sem acento e em minúsculas, normalizado por `app/dominio/texto.py` —
    #: junta "Radamés" e "Radames". É esta coluna que carrega a unicidade e o
    #: índice de trigrama; `nome` fica intacto para exibição.
    nome_normalizado: Mapped[str] = mapped_column(Text)
    #: veiculo | orgao | entidade | investidor | proposicao | area_interna
    #:
    #: A lista vale como `TIPOS_DE_INSTITUICAO` no dominio, derivada do mapa
    #: frente -> tipo — e nao escrita a mao aqui.
    tipo: Mapped[str] = mapped_column(Text)
    #: O nome POR EXTENSO. `nome` guarda a forma curta — "ABCON", "ANA" —, que
    #: e como se fala e como a lista fica legivel; quem nao convive com a sigla
    #: nao sabe o que escolheu. Nulo no que veio da planilha.
    nome_completo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: O CARGO QUE O FORNECEDOR INFORMOU, pelo rótulo — "Deputado estadual".
    #: Só em `tipo='perfil_rede'`, e o CHECK da `0076` garante.
    #:
    #: É O QUE A PESSOA RECONHECE NA TELA: o público diz a que poder o ator
    #: pertence ("Poder Legislativo"); o cargo diz quem ele é.
    #:
    #: NÃO É A MESMA AFIRMAÇÃO QUE `interlocutor.cargo`: lá é a verdade do CRM
    #: sobre a PESSOA, aqui é a evidência do fornecedor sobre o PERFIL — e um
    #: perfil pode existir sem pessoa nenhuma, que é o estado dos 1.108.
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A PESSOA DE QUEM ESTE PERFIL É — só em `tipo='perfil_rede'`, e o CHECK
    #: da `0073` garante. É o que liga o que `stelafariasrs` postou ao que a
    #: deputada Stela Farias fez nas agendas do CRM.
    #:
    #: A CHAVE FICA NO PERFIL porque a cardinalidade é essa: um perfil é de no
    #: máximo uma pessoa, e uma pessoa tem vários perfis (54 dos 1.173 autores
    #: da Bites aparecem em mais de uma rede).
    #:
    #: NÃO CONFUNDIR COM `interlocutor.instituicao_id`, que diz DE QUEM a
    #: pessoa fala — para a deputada, a Assembleia.
    interlocutor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("interlocutor.id", ondelete="SET NULL"),
        nullable=True,
    )
    esfera_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("esfera.id"), nullable=True
    )
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: Relevância da INSTITUIÇÃO — Tier 1 a 4, do mesmo dicionário `relevancia`
    #: que a agenda usa. Não confundir com `interacao.tier`, que é a relevância
    #: daquele encontro: a Folha é Tier 1 sempre, e uma nota de rodapé com a
    #: Folha pode ser Tier 3.
    #:
    #: Nulo nas cadastradas antes da coluna existir (0023). O formulário exige
    #: o campo nas novas.
    tier: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("relevancia.id"), nullable=True
    )
    #: A nova taxonomia de públicos (10 categorias) — ver
    #: `0036_categoria_de_publico.sql`. Nula em quem ainda não foi
    #: reclassificado (todo o diretório, na entrada em vigor do campo).
    categoria_publico_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("categoria_publico.id"), nullable=True
    )
    #: A subdivisão dentro da categoria (Federal/Estadual/Municipal...). Nula
    #: sempre que a categoria for "sem_quebra", e nula também em quem ainda
    #: não foi reclassificado.
    subcategoria_publico_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("subcategoria_publico.id"), nullable=True
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    #: ESTE CADASTRO NASCEU DE PLANILHA E NINGUÉM O CONSOLIDOU AINDA.
    #:
    #: A FILA DE REVISÃO das três abas de Cadastro compartilhado sai daqui —
    #: pedido do dono do produto (11/10/2026): "o profissional consegue subir a
    #: planilha sem problemas e pode revisar depois, e inclusive pode ser trabalho
    #: de outra pessoa. Queremos dar padronização, mas com menor impacto".
    #:
    #: NÃO SE DERIVA DA INCOMPLETUDE, e eu tentei: das 99 instituições que
    #: aparecem em agendas, só 58 têm categoria de público. A ausência é o estado
    #: NORMAL do CRM, e a fila nasceria com 250 das 544 agendas dentro — ruído, e
    #: ruído é o que faz ninguém olhar. O que distingue é a PROCEDÊNCIA.
    #:
    #: E NÃO É `ativo`: o que nasce de planilha está EM circulação — a menção
    #: aponta para ele, a agenda existe —, só falta alguém conferir o
    #: enquadramento. `ativo=false` esconderia o dado que acabou de entrar.
    #:
    #: SAI POR AÇÃO DE QUEM REVISA. "Consolidar" é uma decisão, não um campo que
    #: ficou preenchido: ligar a saída a um campo faria a fila esvaziar sozinha com
    #: um preenchimento parcial, e ninguém teria dito nada.
    pendente_de_revisao: Mapped[bool] = mapped_column(Boolean, default=False)
    #: POR QUE ESTE CADASTRO ESPERA REVISÃO. Nulo é "nasceu de planilha", sem mais
    #: nada a dizer — o caso comum.
    #:
    #: A ABA LISTA O REGISTRO PELO BOOLEANO, e quem abre a aba precisa saber POR
    #: QUÊ. "Apareceu em duas instituições na mesma planilha" é a informação que
    #: torna a revisão possível em vez de um convite a adivinhar.
    #:
    #: TEXTO E NÃO CÓDIGO: um enum obrigaria a prever os motivos, e o motivo é uma
    #: frase para gente ler. É a mesma escolha de `ator_distinto.motivo`, pela mesma
    #: razão — "é conhecimento sobre o mundo, não estado de interface".
    motivo_da_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Interlocutor(Tabela):
    __tablename__ = "interlocutor"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text)
    instituicao_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("instituicao.id"), nullable=True
    )
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A área DENTRO DA INSTITUIÇÃO dele (ex.: "Research" num banco) — texto
    #: livre, não o dicionário `area_pessoa` (que é a área da Aegea). Ver
    #: migrations/0054.
    area: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Como se chega na pessoa. Marcar agenda comeca por escrever para alguem, e
    #: este endereco vivia fora do sistema.
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Os links/handles de redes sociais do contato, se ele tiver — texto
    #: livre, zero ou mais, sem identificar a rede nem validar formato. Uma
    #: lista, e não cinco campos fixos: ver migrations/0055.
    redes_sociais: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    tipo: Mapped[str | None] = mapped_column(Text, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    #: ESTE CADASTRO NASCEU DE PLANILHA E NINGUÉM O CONSOLIDOU AINDA.
    #:
    #: A FILA DE REVISÃO das três abas de Cadastro compartilhado sai daqui —
    #: pedido do dono do produto (11/10/2026): "o profissional consegue subir a
    #: planilha sem problemas e pode revisar depois, e inclusive pode ser trabalho
    #: de outra pessoa. Queremos dar padronização, mas com menor impacto".
    #:
    #: NÃO SE DERIVA DA INCOMPLETUDE, e eu tentei: das 99 instituições que
    #: aparecem em agendas, só 58 têm categoria de público. A ausência é o estado
    #: NORMAL do CRM, e a fila nasceria com 250 das 544 agendas dentro — ruído, e
    #: ruído é o que faz ninguém olhar. O que distingue é a PROCEDÊNCIA.
    #:
    #: E NÃO É `ativo`: o que nasce de planilha está EM circulação — a menção
    #: aponta para ele, a agenda existe —, só falta alguém conferir o
    #: enquadramento. `ativo=false` esconderia o dado que acabou de entrar.
    #:
    #: SAI POR AÇÃO DE QUEM REVISA. "Consolidar" é uma decisão, não um campo que
    #: ficou preenchido: ligar a saída a um campo faria a fila esvaziar sozinha com
    #: um preenchimento parcial, e ninguém teria dito nada.
    pendente_de_revisao: Mapped[bool] = mapped_column(Boolean, default=False)
    #: POR QUE ESTE CADASTRO ESPERA REVISÃO. Nulo é "nasceu de planilha", sem mais
    #: nada a dizer — o caso comum.
    #:
    #: A ABA LISTA O REGISTRO PELO BOOLEANO, e quem abre a aba precisa saber POR
    #: QUÊ. "Apareceu em duas instituições na mesma planilha" é a informação que
    #: torna a revisão possível em vez de um convite a adivinhar.
    #:
    #: TEXTO E NÃO CÓDIGO: um enum obrigaria a prever os motivos, e o motivo é uma
    #: frase para gente ler. É a mesma escolha de `ator_distinto.motivo`, pela mesma
    #: razão — "é conhecimento sobre o mundo, não estado de interface".
    motivo_da_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InterlocutorTema(Tabela):
    __tablename__ = "interlocutor_tema"

    interlocutor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("interlocutor.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )


class PessoaAegea(Tabela):
    """Uma pessoa da Aegea é a mesma pessoa quer apareça como porta-voz numa
    demanda de imprensa, quer apareça na equipe de uma agenda de governo. O
    papel fica na relação com a interação, não na pessoa."""

    __tablename__ = "pessoa_aegea"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(Text)
    nome_normalizado: Mapped[str] = mapped_column(Text, unique=True)
    cargo: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Como se aciona a pessoa da casa para articular a agenda. Antes disto o
    #: endereco vivia no catalogo corporativo, fora daqui, e sem garantia de
    #: ser o certo.
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Aparece no diretório de porta-vozes e no painel de exposição.
    eh_porta_voz: Mapped[bool] = mapped_column(Boolean, default=False)
    #: De onde esta pessoa fala — Comunicação, Relações Institucionais etc.
    #: Nula em quem foi cadastrado antes de a coluna existir (0029).
    area_id: Mapped[int | None] = mapped_column(
        SmallInteger, ForeignKey("area_pessoa.id"), nullable=True
    )
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    #: ESTE CADASTRO NASCEU DE PLANILHA E NINGUÉM O CONSOLIDOU AINDA.
    #:
    #: A FILA DE REVISÃO das três abas de Cadastro compartilhado sai daqui —
    #: pedido do dono do produto (11/10/2026): "o profissional consegue subir a
    #: planilha sem problemas e pode revisar depois, e inclusive pode ser trabalho
    #: de outra pessoa. Queremos dar padronização, mas com menor impacto".
    #:
    #: NÃO SE DERIVA DA INCOMPLETUDE, e eu tentei: das 99 instituições que
    #: aparecem em agendas, só 58 têm categoria de público. A ausência é o estado
    #: NORMAL do CRM, e a fila nasceria com 250 das 544 agendas dentro — ruído, e
    #: ruído é o que faz ninguém olhar. O que distingue é a PROCEDÊNCIA.
    #:
    #: E NÃO É `ativo`: o que nasce de planilha está EM circulação — a menção
    #: aponta para ele, a agenda existe —, só falta alguém conferir o
    #: enquadramento. `ativo=false` esconderia o dado que acabou de entrar.
    #:
    #: SAI POR AÇÃO DE QUEM REVISA. "Consolidar" é uma decisão, não um campo que
    #: ficou preenchido: ligar a saída a um campo faria a fila esvaziar sozinha com
    #: um preenchimento parcial, e ninguém teria dito nada.
    pendente_de_revisao: Mapped[bool] = mapped_column(Boolean, default=False)
    #: POR QUE ESTE CADASTRO ESPERA REVISÃO. Nulo é "nasceu de planilha", sem mais
    #: nada a dizer — o caso comum.
    #:
    #: A ABA LISTA O REGISTRO PELO BOOLEANO, e quem abre a aba precisa saber POR
    #: QUÊ. "Apareceu em duas instituições na mesma planilha" é a informação que
    #: torna a revisão possível em vez de um convite a adivinhar.
    #:
    #: TEXTO E NÃO CÓDIGO: um enum obrigaria a prever os motivos, e o motivo é uma
    #: frase para gente ler. É a mesma escolha de `ator_distinto.motivo`, pela mesma
    #: razão — "é conhecimento sobre o mundo, não estado de interface".
    motivo_da_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    #: SOBRE O QUE ESTA PESSOA PODE FALAR.
    #:
    #: `selectin` carrega os vinculos de TODA a lista em uma consulta a mais —
    #: nao uma por pessoa. A objecao a N+1 registrada em `temas_do_porta_voz`
    #: vale para carregamento preguicoso, nao para carregamento em lote.
    #:
    #: So leitura: quem escreve e `_aplicar_temas_da_pessoa`, na API. Ter os
    #: dois lados gravaveis seria a mesma relacao com duas donas.
    vinculos_de_tema: Mapped[list[PessoaAegeaTema]] = relationship(
        "PessoaAegeaTema", viewonly=True, lazy="selectin"
    )

    @property
    def temas(self) -> list[int]:
        """Os ids dos assuntos autorizados, como a tela os quer.

        Propriedade e nao relacao: quem le quer o id do assunto, e nao a linha
        de ligacao. O esquema de saida mapeia por nome, entao le daqui.
        """
        return sorted(vinculo.tema_id for vinculo in self.vinculos_de_tema)


class PessoaAegeaTema(Tabela):
    """Temas autorizados. Sustenta a regra de "fora do escopo": registro cujo
    tema não está na lista do porta-voz que o conduziu."""

    __tablename__ = "pessoa_aegea_tema"

    pessoa_aegea_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pessoa_aegea.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tema_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tema.id"), primary_key=True
    )


class InstituicaoApelido(Tabela):
    """Um nome que já foi de um cadastro e hoje aponta para o que o absorveu.

    POR QUE EXISTE (migration `0102`). A ingestão casa menção com cadastro por
    `nome_normalizado` EXATO (`veiculos_da_imprensa.reconhecer`). Quando dois
    cadastros se fundem, o nome de quem sai some do banco — e o fornecedor
    continua mandando aquele nome todo mês. Sem apelido, ele deixa de casar,
    vira "veículo novo" e NASCE DE NOVO: a duplicata que alguém acabou de
    resolver volta, e as menções do mês vão para o cadastro recém-criado.

    O MESMO DESENHO DE `UnidadeNegocioApelido`, que resolveu isto para a
    concessionária. Dois jeitos diferentes de dizer "este nome também é aquele
    cadastro" seriam dois lugares para divergir.

    A BUSCA EXATA VENCE O APELIDO, e a ordem importa: `instituicao`
    `nome_normalizado` NÃO é única (ALMG existe como entidade e como órgão), e um
    apelido que respondesse antes trocaria o ator de um cadastro vivo.

    A CHAVE É O PAR (nome, instituição), e não o nome sozinho: o MESMO nome pode
    ter sido de dois cadastros, fundidos em sobreviventes diferentes. Guardando
    o par, a ambiguidade fica REGISTRADA em vez de destruída, e cada leitura
    aplica a regra dela — `reconhecer` só resolve o nome de UMA linha (nunca
    adivinha o ator), `nomes_da_lista` aceita o nome se QUALQUER linha aponta
    para um veículo da lista (o texto era, e continua sendo, de um listado).
    """

    __tablename__ = "instituicao_apelido"

    #: O nome já normalizado — o MESMO com que `reconhecer` procura. Chave
    #: diferente da busca seria um apelido que nunca casa.
    nome_normalizado: Mapped[str] = mapped_column(Text, primary_key=True)
    #: A grafia como ela existia no cadastro que saiu, para a tela dizer o que
    #: foi absorvido em vez de devolver a chave achatada.
    nome: Mapped[str] = mapped_column(Text)
    instituicao_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instituicao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AtorDistinto(Tabela):
    """O par que alguém olhou e declarou atores diferentes.

    Tira o par da fila de duplicados — sem isto, a fila nunca chega a zero — e
    guarda conhecimento sobre o mundo: `Diário SM` e `Diários M` casam por
    semelhança e podem não ser o mesmo jornal. Ver migration `0078`.

    SEM LADO: o par é guardado sempre na mesma ordem (`esquerda < direita`,
    pelo uuid), e é a chave primária que recusa a repetição — a aplicação não
    procura nas duas direções, ela ordena antes de gravar.
    """

    __tablename__ = "ator_distinto"

    esquerda: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instituicao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    direita: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("instituicao.id", ondelete="CASCADE"),
        primary_key=True,
    )
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    decidido_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    decidido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
