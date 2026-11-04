"""Ligar a menção ao veículo do cadastro compartilhado, e criar o que falta.

POR QUE ISTO EXISTE. A menção guardava o veículo como texto do fornecedor
(`mencao.veiculo`) e nada mais. O cadastro compartilhado já modela veículo —
`instituicao` com `tipo='veiculo'`, categoria de público, subcategoria
editorial e esfera —, e as duas metades não se falavam: o export traz milhares
de veículos distintos e o cadastro começou com algumas dezenas.

O EFEITO DISSO NA LENTE MERCADO. Separada por `Público-alvo = Investidores`,
ela captura um conjunto muito menor e DIFERENTE da lista de veículos do mercado
financeiro que a Aegea mantém. Com o vínculo, o critério passa a ser a
subcategoria "Econômica e de negócios" do cadastro, e a lista se mantém pela
tela de Cadastro de Instituições em vez de por SQL.

CRIAR NO UPLOAD, MAS NÃO EM SILÊNCIO. O veículo sem cadastro nasce junto com a
subida, por pedido do dono do produto, e a conta aparece ANTES de confirmar —
é isso que torna a coisa segura, porque uma subida faz nascer milhares de
cadastros. A importação de agendas tem a razão escrita no próprio código:
"importação de planilha sem conferência humana cria duplicata de instituição em
massa, e desfazer isso depois é pior que digitar de novo".

O QUE O FORNECEDOR SABE, E O QUE ELE NÃO SABE. Do export vêm o nome, a praça
(`Estado do Veículo`) e o alcance (`Abrangência`, que casa com `esfera`). O que
ele NÃO diz é a lógica editorial: nenhuma coluna da Clipei informa que a
InfoMoney é imprensa econômica. Então o veículo nasce com `subcategoria` NULA, e
essa classificação continua sendo juízo humano — o que é certo, porque é dela
que a lente Mercado depende.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Text, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, Esfera, SubcategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao, InstituicaoApelido
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import (
    TIERS,
    achatar,
    normalizar_cargo,
    para_sigla,
    rotulo_do_cargo,
)
from app.dominio.score import RELEVANCIA_DO_TIER
from app.dominio.texto import achatar_para_comparar, normalizar

#: A categoria de público com que um veículo da imprensa nasce.
#:
#: PELO NOME e não pelo id: ids são do banco de cada ambiente, e um `12` escrito
#: aqui apontaria para outra categoria na base do cliente. O nome é o contrato
#: que a `0061` fixou ao separar Imprensa de Formadores de Opinião.
CATEGORIA_DA_IMPRENSA = "Imprensa"

#: O QUE CADA LISTA DE VEÍCULOS É, no cadastro compartilhado.
#:
#: O MOTOR SÓ CONHECE O NOME (`LISTAS_DE_VEICULOS`, em `dominio/ingestao_score`);
#: a tradução para o par (categoria, subcategoria) mora aqui, que é a camada com
#: banco. Pelo PAR, e não pelo nome da subcategoria sozinho:
#: `subcategoria_publico` repete nome entre categorias de propósito ("federal"
#: aparece em três), então a chave real é sempre (categoria, subcategoria).
LISTAS_DE_VEICULOS: dict[str, tuple[str, str]] = {
    "imprensa_economica": (CATEGORIA_DA_IMPRENSA, "Econômica e de negócios"),
    #: A LENTE INSTITUCIONAL RECORTA PELO MESMO MECANISMO: o filtro dela é
    #: Imprensa > Institucional, como o do Mercado.
    "imprensa_institucional": (CATEGORIA_DA_IMPRENSA, "Institucional"),
}

#: A CATEGORIA DE PÚBLICO COM QUE CADA TIPO NASCE.
#:
#: O motor só conhece os tipos (`CADASTROS_DE_QUEM_FALA`, em
#: `dominio/ingestao_score`); a categoria mora aqui, que é a camada com banco —
#: o mesmo desenho das listas de veículos.
#:
#: PERFIL DE REDE É FORMADOR DE OPINIÃO, e não imprensa. A categoria já existia
#: no cadastro e estava VAZIA: as categorias de público preveem formador de
#: opinião e sociedade civil desde a `0036`, e só a Imprensa tinha gente. Um
#: perfil de rede dentro da Imprensa poderia um dia entrar na lista de imprensa
#: econômica da lente Mercado — e "deolhoemesteio" não é veículo de investidor.
CATEGORIA_DE_QUEM_FALA: dict[str, str] = {
    "veiculo": CATEGORIA_DA_IMPRENSA,
    "perfil_rede": "Formadores de Opinião",
}

#: O PÚBLICO DE QUEM FALA, PELO CARGO QUE A PLANILHA INFORMA.
#:
#: SEM ISTO O CARGO É JOGADO FORA no cadastro: a coluna `Cargo` alimenta a régua
#: de peso e o gráfico de quem fala, mas o perfil nasce sem ela — e é ela que
#: diz se o ator é poder público, imprensa ou sociedade. Sem o mapa, todo perfil
#: nasce como "Formador de Opinião", e um vereador aparece classificado como
#: formador de opinião quando o cadastro TEM o vocabulário certo (a taxonomia de
#: públicos prevê Poder Legislativo com Federal, Estadual e Municipal desde a
#: `0036`).
#:
#: SÓ O QUE SE PODE DEFENDER ESTÁ AQUI. `político` pode ser executivo ou
#: legislativo; `partido`, `empresa` e `órgão público` não têm par óbvio na
#: taxonomia; `outros`, `alemao` e `perfil de twitter` não são cargo. Esses ficam
#: SEM categoria — que é a verdade ("ainda não classificado") e um estado que o
#: cadastro já conhece. Chutar classificaria milhares de perfis anônimos como
#: formadores de opinião.
#:
#: A chave é o cargo JÁ CANONIZADO (`normalizar_cargo`), então `Vereadora` e
#: `Verador` caem no mesmo lugar.
CATEGORIA_POR_CARGO: dict[str, tuple[str, str | None]] = {
    "presidente": ("Poder Executivo", "Federal"),
    "ministro": ("Poder Executivo", "Federal"),
    "governador": ("Poder Executivo", "Estadual"),
    "prefeito": ("Poder Executivo", "Municipal"),
    #: A PREFEITURA é o órgão, e o perfil dela fala pelo executivo municipal.
    "prefeitura": ("Poder Executivo", "Municipal"),
    "senador": ("Poder Legislativo", "Federal"),
    "deputado_federal": ("Poder Legislativo", "Federal"),
    "deputado_estadual": ("Poder Legislativo", "Estadual"),
    "vereador": ("Poder Legislativo", "Municipal"),
    #: IMPRENSA SEM SUBCATEGORIA: a lógica editorial (econômica, geral,
    #: regional) é juízo humano, e é dela que a lente Mercado depende.
    "imprensa": (CATEGORIA_DA_IMPRENSA, None),
    "comunicador": ("Formadores de Opinião", None),
    "sindicato": ("Entidades Setoriais e Representativas", "Institutos e Associações"),
    "internauta": ("Sociedade Civil e Comunidade", "Comunidade e lideranças locais"),
}

#: `Abrangência` da Clipei -> `esfera` do cadastro.
#:
#: O FORNECEDOR DIZ O ALCANCE e o cadastro tem o campo: Local, Regional,
#: Nacional e Internacional são quatro dos seis valores de `esfera`. "Local" vai
#: para Municipal, que é o nome que a Aegea usa para a mesma ideia.
#:
#: Os dois que sobram (`Estadual`, `Federal`) não têm equivalente no export, e
#: não se inventa: veículo sem abrangência declarada nasce sem esfera.
ESFERA_POR_ABRANGENCIA = {
    "local": "Municipal",
    "regional": "Regional",
    "nacional": "Nacional",
    "internacional": "Internacional",
}


@dataclass(frozen=True, slots=True)
class Parecido:
    """Um cadastro que JÁ EXISTE e que este nome novo pode ser.

    PELA CHAVE ACHATADA — espaço e pontuação fora —, que é a mesma comparação da
    fila de duplicados. `Neofeed` e `Neo Feed` coincidem; `cnnbrasil` e `CNN
    Brasil` também.

    PARA QUEM AUTORIZA A CRIAÇÃO LER ANTES DE AUTORIZAR. A conferência da ingestão
    marca todos e deixa desmarcar; sem isto, quem desmarca um rádio de bairro não
    tem como ver que "Neo Feed" é o "Neofeed" que já está no cadastro — e a
    autorização cria a duplicata que a fila depois pergunta.
    """

    id: str
    nome: str
    tipo: str


@dataclass(frozen=True, slots=True)
class VeiculoNovo:
    """Um veículo que a planilha traz e o cadastro não tem.

    É o que a conferência mostra antes de criar — com a praça e o alcance que
    vieram do fornecedor, para quem confere reconhecer o que vai entrar.
    """

    nome: str
    uf: str | None = None
    esfera: str | None = None
    #: Quantas menções da planilha apontam para ele. É por aqui que a tela
    #: ordena: um veículo com 1.453 menções merece mais atenção que um com 1.
    mencoes: int = 0
    #: O CARGO QUE O FORNECEDOR INFORMOU, já canonizado — `vereador`,
    #: `deputado_estadual`, `imprensa`. É o que decide o público do perfil (ver
    #: `CATEGORIA_POR_CARGO`) e o que a conferência mostra, para quem autoriza
    #: a criação ver "Iriel Sachet — Vereador" em vez de só o nome.
    cargo: str | None = None
    #: OS CADASTROS QUE ESTE NOME PODE SER — vazio quando não parece com nenhum.
    #:
    #: NÃO IMPEDE A CRIAÇÃO, informa quem a autoriza. A decisão é de gente: a
    #: semelhança não prova identidade, e `Diário SM` contra `Diários M` é o
    #: contraexemplo que o módulo da fila já registra.
    parecidos: tuple[Parecido, ...] = ()
    #: A RELEVÂNCIA com que ele nasce — 1, 2 ou 3, o `relevancia.id`.
    #:
    #: JÁ TRADUZIDO da escala do fornecedor ("muito relevante") para a do
    #: cadastro ("Tier 1"), por `RELEVANCIA_DO_TIER`. Nulo quando a fonte não
    #: tem tier: rede social e canal próprio não têm, e inventar um afirmaria
    #: sobre o veículo o que o fornecedor não disse.
    tier: int | None = None


@dataclass(frozen=True, slots=True)
class Reconhecimento:
    """O que a planilha diz de veículo, confrontado com o cadastro."""

    #: nome normalizado -> id da instituição, para os que JÁ existem.
    cadastrados: dict[str, str] = field(default_factory=dict)
    #: os que faltam, do mais citado para o menos.
    novos: tuple[VeiculoNovo, ...] = ()

    @property
    def quantos_novos(self) -> int:
        return len(self.novos)


def reconhecer(
    sessao: Session,
    veiculos: dict[str, dict[str, object]],
    tipo: str = "veiculo",
) -> Reconhecimento:
    """Separa o que o cadastro já tem do que falta. NÃO ESCREVE NADA.

    `veiculos` é nome cru -> `{"uf": ..., "abrangencia": ..., "mencoes": n}`,
    como o leitor da planilha o monta.

    NORMALIZA PELA MESMA FUNÇÃO DO CADASTRO (`dominio.texto.normalizar`), e é
    isso que faz "Valor Econômico" casar com o "Valor Econômico" já cadastrado:
    acento, caixa, espaço duplo e o `|` que a Clipei usa entre veículo e cidade.

    ELA NÃO É IGUAL AO `achatar` DA INGESTÃO, e a segurança não vem de serem
    iguais — vem de os DOIS LADOS desta comparação usarem `normalizar`.
    Divergem em caractere não-ASCII: `normalizar` faz `NFKD` e corta o que não é
    ASCII (medido: `normalizar("Jornal 📈")` dá `"jornal"`), enquanto `achatar`
    o preserva. Um veículo cujo nome seja só não-ASCII normaliza para vazio e
    nunca casa — fato aceito, e a razão de a lista descartar nome vazio.
    """
    nomes = {normalizar(nome): nome for nome in veiculos}
    if not nomes:
        return Reconhecimento()

    #: UMA CONSULTA, e não uma por veículo: são milhares de nomes por export, e
    #: milhares de idas ao banco levariam minutos.
    #:
    #: EM QUALQUER TIPO, por decisão do dono do produto: UM CADASTRO SÓ, vindo do
    #: Cadastro compartilhado. Filtrando por tipo, o mesmo ator existe duas e três
    #: vezes — como veículo na lista do Mercado e como perfil de rede sem
    #: classificação —, as menções não somam, e nenhuma tela junta.
    #:
    #: O CANAL NÃO SE PERDE AO UNIFICAR: quem diz "foi em rede social" é a FONTE
    #: da menção — `bites` alimenta a Sociedade digital, `clipei` a Imprensa. A
    #: instituição responde QUEM falou; a fonte responde ONDE.
    achados: dict[str, tuple[str, bool]] = {}
    for normalizado, ident, de_outro_tipo in sessao.execute(
        select(
            Instituicao.nome_normalizado,
            Instituicao.id,
            (Instituicao.tipo != tipo).label("de_outro_tipo"),
        ).where(
            Instituicao.nome_normalizado.in_(list(nomes)),
            #: EM QUALQUER TIPO, PARA QUALQUER FONTE — regra do dono do produto:
            #: "qualquer fonte de dados tem acesso à mesma base de instituições e
            #: interlocutores, não interessa se é no CRM, redes sociais ou
            #: imprensa. O BTG podemos ter acesso em rede social, em reunião de
            #: investimento ou imprensa, mas ele continua sendo um só".
            #:
            #: FILTRANDO PELO TIPO DA FONTE, o mesmo ator fica partido em dois
            #: cadastros: um `investidor` invisível para a Clipei e um `veiculo`
            #: criado pela ingestão, com as agendas num registro e as menções no
            #: outro, e nenhuma tela juntando. Uma fonte que busca em qualquer
            #: tipo e outra que não busca recriam o par a cada subida.
            #:
            #: QUEM ENQUADRA É O TIME, não esta busca: o tipo, a categoria e a
            #: subcategoria são de quem cadastra, e esta função nunca os muda num
            #: cadastro que já existe.
            #:
            #: O HOMÔNIMO MUDOU DE DONO, não desapareceu: decidir aqui que nome
            #: igual com tipo diferente é outro ator é o que produzia os pares. O
            #: que falta é a conferência MOSTRAR "este nome já existe como perfil
            #: de rede; é o mesmo ator?" — a regra do dono do produto para
            #: suspeita de duplicação é mostrar para a pessoa decidir.
        )
    ).all():
        #: O DO TIPO DA FONTE VENCE quando o nome existe nos dois: enquanto os
        #: 94 duplicados não forem fundidos, a Clipei continua achando o
        #: veículo dela e a Bites o perfil dela — ninguém troca de ator no meio
        #: do caminho. Fundidos, sobra um e a preferência não decide nada.
        atual = achados.get(normalizado)
        if atual is None or (atual[1] and not de_outro_tipo):
            achados[normalizado] = (str(ident), bool(de_outro_tipo))
    existentes = {chave: ident for chave, (ident, _) in achados.items()}

    #: E DEPOIS O APELIDO, para os nomes que a busca exata não achou.
    #:
    #: POR QUE EXISTE (migration `0102`): quando dois cadastros se fundem, o nome
    #: de quem sai some do banco — e o fornecedor continua mandando aquele nome
    #: todo mês. Sem esta consulta ele vira "veículo novo" e NASCE DE NOVO,
    #: recriando a duplicata que alguém acabou de resolver.
    #:
    #: DEPOIS, E NUNCA ANTES: `instituicao.nome_normalizado` não é única (ALMG
    #: existe como entidade e como órgão), e um apelido que respondesse primeiro
    #: trocaria o ator de um cadastro VIVO pelo de uma fusão antiga. O apelido só
    #: fala sobre nome que não existe mais.

    #: E SÓ O APELIDO DE UMA LINHA RESOLVE. A chave da tabela é o par (nome,
    #: instituição), e o mesmo nome pode ter sido de dois cadastros fundidos em
    #: sobreviventes diferentes: escolher um deles mandaria as menções de um ator
    #: para o dossiê do outro. Mesma regra da concessionária — nunca adivinhar
    #: quando há mais de uma candidata. O nome ambíguo segue para a CONFERÊNCIA.
    sem_cadastro = [chave for chave in nomes if chave not in existentes]
    if sem_cadastro:
        for chave, ident, quantos in sessao.execute(
            select(
                InstituicaoApelido.nome_normalizado,
                func.min(InstituicaoApelido.instituicao_id.cast(Text)),
                func.count(),
            )
            .where(InstituicaoApelido.nome_normalizado.in_(sem_cadastro))
            .group_by(InstituicaoApelido.nome_normalizado)
        ).all():
            if quantos == 1:
                existentes[chave] = str(ident)

    #: O CADASTRO ATIVO INTEIRO, PELA CHAVE ACHATADA — uma consulta, e um
    #: dicionário consultado em O(1) por nome novo.
    #:
    #: SÓ SE HOUVER NOME NOVO: num arquivo em que tudo já está cadastrado, esta
    #: consulta não responderia nada. São 3.785 linhas de três colunas.
    faltando = [bruto for normalizado, bruto in nomes.items() if normalizado not in existentes]
    por_achatado: dict[str, list[Parecido]] = {}
    if faltando:
        for ident, nome_do_cadastro, tipo_do_cadastro in sessao.execute(
            select(Instituicao.id, Instituicao.nome, Instituicao.tipo).where(
                Instituicao.ativo.is_(True)
            )
        ).all():
            chave = achatar_para_comparar(nome_do_cadastro or "")
            if chave:
                por_achatado.setdefault(chave, []).append(
                    Parecido(
                        id=str(ident), nome=nome_do_cadastro, tipo=str(tipo_do_cadastro)
                    )
                )

    novos = [
        VeiculoNovo(
            nome=bruto,
            #: QUEM ESTE NOME PODE SER. Medido antes de existir: com `NeofeedZZ` no
            #: cadastro e `Neo feed ZZ` na planilha, a ingestão criava o segundo —
            #: porque a busca acima usa `normalizar`, que preserva o espaço.
            parecidos=tuple(por_achatado.get(achatar_para_comparar(bruto), ())),
            uf=_texto(veiculos[bruto].get("uf")),
            esfera=ESFERA_POR_ABRANGENCIA.get(
                str(veiculos[bruto].get("abrangencia") or "").strip().lower()
            ),
            mencoes=int(veiculos[bruto].get("mencoes") or 0),
            cargo=normalizar_cargo(veiculos[bruto].get("cargo")),
            #: PELAS MESMAS DUAS FUNÇÕES DA GRAVAÇÃO DA MENÇÃO — `achatar` e
            #: `TIERS`. É o que faz "Muito Relevante", "muito relevante " e
            #: "MUITO RELEVANTE" caírem na mesma chave, e o que garante que o
            #: cadastro e a menção não discordem sobre o mesmo texto.
            tier=RELEVANCIA_DO_TIER.get(
                TIERS.get(achatar(veiculos[bruto].get("tier")), "") or ""
            ),
        )
        for normalizado, bruto in nomes.items()
        if normalizado not in existentes
    ]
    novos.sort(key=lambda v: (-v.mencoes, v.nome))
    return Reconhecimento(cadastrados=existentes, novos=tuple(novos))


def criar(
    sessao: Session, novos: tuple[VeiculoNovo, ...], tipo: str = "veiculo"
) -> dict[str, str]:
    """Cadastra quem falou e ainda não estava no cadastro. Normalizado -> id.

    `tipo` VEM DA FONTE (`Mapeamento.quem_fala`): `veiculo` para um clipping
    de imprensa, `perfil_rede` para social listening. O padrão mantém as
    quatro fontes antigas exatamente como estavam.

    NASCEM NA CATEGORIA DO TIPO E SEM SUBCATEGORIA. A categoria é a única que o
    fornecedor permite afirmar — é um export de clipping de imprensa, e todo
    veículo dele é imprensa. A subcategoria é lógica EDITORIAL (econômica,
    geral nacional, regional das concessões, municipal), e nenhuma coluna da
    Clipei a informa: inventá-la aqui faria a lente Mercado se separar por um
    palpite nosso em vez de por uma decisão da Aegea.

    NASCEM ATIVOS, e isso é consequência de serem veículos reais que acabaram de
    publicar sobre a companhia. Desativar é gesto de quem administra o cadastro.
    """
    if not novos:
        return {}

    #: TODAS AS CATEGORIAS E SUBCATEGORIAS DE UMA VEZ, porque o público de
    #: cada perfil sai do cargo dele: uma consulta por perfil faria 1.108 idas
    #: ao banco numa subida.
    categorias = {
        nome: ident
        for nome, ident in sessao.execute(
            select(CategoriaPublico.nome, CategoriaPublico.id).where(
                CategoriaPublico.ativo
            )
        )
    }
    subcategorias = {
        (categoria, sub): ident
        for categoria, sub, ident in sessao.execute(
            select(CategoriaPublico.nome, SubcategoriaPublico.nome, SubcategoriaPublico.id)
            .join(
                CategoriaPublico,
                CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
            )
        )
    }
    categoria = categorias.get(CATEGORIA_DE_QUEM_FALA[tipo])
    esferas = {
        nome: ident
        for nome, ident in sessao.execute(select(Esfera.nome, Esfera.id)).all()
    }

    criados: dict[str, str] = {}
    for veiculo in novos:
        nome = " ".join(veiculo.nome.split())
        #: O PÚBLICO SAI DO CARGO quando quem fala é um perfil e o cargo é
        #: conhecido: o vereador entra em Poder Legislativo / Municipal, e não
        #: em Formadores de Opinião. Cargo desconhecido ou ausente deixa o
        #: perfil SEM categoria — "ainda não classificado", que é a verdade.
        publico, subpublico = categoria, None
        #: O FATO, e não o efeito dele no banco: "a fonte mandou um cargo que
        #: sabemos traduzir". Ver `_motivo_da_revisao` — a frase que vai para a
        #: fila depende disto, e NÃO de `publico is None`.
        cargo_reconhecido = False
        if tipo == "perfil_rede":
            par = CATEGORIA_POR_CARGO.get(veiculo.cargo or "")
            cargo_reconhecido = par is not None
            if par is None:
                publico = None
            else:
                publico = categorias.get(par[0])
                subpublico = (
                    subcategorias.get((par[0], par[1])) if par[1] else None
                )

        registro = Instituicao(
            nome=nome,
            nome_normalizado=normalizar(nome),
            tipo=tipo,
            categoria_publico_id=publico,
            subcategoria_publico_id=subpublico,
            esfera_id=esferas.get(veiculo.esfera or ""),
            # A SIGLA, e não o nome: `instituicao.uf` é o domínio
            # `abrangencia`, com CHECK das 29 siglas — "Santa Catarina" ali é
            # recusado pelo Postgres. É a assimetria com `mencao.uf`, que
            # guarda o nome por decisão do dono; `para_sigla` documenta as duas.
            uf=para_sigla(veiculo.uf),
            #: O CARGO VAI PARA O CADASTRO, pelo rótulo: é o que faz a tela
            #: dizer "Stela Farias — Deputado estadual" em vez de só o público.
            #: Nulo em veículo, onde a coluna não existe.
            cargo=rotulo_do_cargo(veiculo.cargo) if tipo == "perfil_rede" else None,
            #: A RELEVÂNCIA QUE A PLANILHA DISSE. Sem isto o cadastro automático
            #: nasce sem relevância, jogando fora uma coluna que o arquivo traz.
            tier=veiculo.tier,
            #: NASCE PENDENTE DE REVISÃO, como todo cadastro que vem de planilha.
            #:
            #: MESMO TENDO PASSADO PELA CONFERÊNCIA DA INGESTÃO, e a diferença é
            #: o que cada uma pergunta: ali a pessoa autoriza a CRIAÇÃO olhando
            #: nome, praça, alcance e cargo — ela diz "este veículo existe e deve
            #: entrar". O ENQUADRAMENTO é outra pergunta: a subcategoria é lógica
            #: editorial que nenhuma coluna da Clipei informa, e é dela que a
            #: lente Mercado depende. Quem autoriza milhares de criações numa
            #: tela não decide milhares de enquadramentos na mesma tela.
            #:
            pendente_de_revisao=True,
            #: E A MARCA DIZ QUAL ENQUADRAMENTO FALTA: este é o produtor de maior
            #: volume da fila, e a frase genérica a deixaria inútil.
            motivo_da_revisao=_motivo_da_revisao(tipo, cargo_reconhecido),
        )
        sessao.add(registro)
        criados[normalizar(nome)] = registro
    sessao.flush()
    return {chave: str(registro.id) for chave, registro in criados.items()}


#: POR QUE O CADASTRO DA INGESTÃO ESPERA REVISÃO — e são três perguntas
#: diferentes, não uma.
#:
#: NÃO É O MESMO MOTIVO DA IMPORTAÇÃO DE AGENDAS. Lá falta a CATEGORIA, e o tipo
#: cai em `entidade`. Aqui ela é derivada: `CATEGORIA_DE_QUEM_FALA` dá "Imprensa"
#: ao veículo, e o cargo dá a do perfil quando a taxonomia o reconhece. O que
#: falta é outra coisa em cada caso — usar a mesma frase mandaria a pessoa
#: procurar um campo que já está preenchido.


def _motivo_da_revisao(tipo: str, cargo_reconhecido: bool) -> str:
    """Três casos, três frases.

    VEÍCULO: a categoria é Imprensa e a SUBCATEGORIA falta. Ela é lógica
    editorial que nenhuma coluna da Clipei informa — e é dela que a lente
    Mercado depende: a lista do Mercado é `tipo='veiculo'` com categoria
    Imprensa e subcategoria "Econômica e de negócios". Sem a subcategoria, o
    veículo fica fora da lente.

    PERFIL COM CARGO RECONHECIDO: o enquadramento saiu do cargo que o fornecedor
    mandou, e o fornecedor erra — cargo ausente, UF de outro estado. O
    enquadramento existe e ainda assim merece um olhar.

    PERFIL SEM CARGO RECONHECIDO: não há categoria nenhuma, porque o cargo não
    estava em `CATEGORIA_POR_CARGO`. É o caso em que a fila tem mais a ganhar.

    `cargo_reconhecido` E NÃO O `id` DA CATEGORIA. Decidir por `publico is None`
    decide pelo EFEITO no banco, e o fato que gera a frase é outro: "a fonte
    mandou um cargo que sabemos traduzir". Os dois coincidem hoje e podem
    descolar — uma categoria da taxonomia desativada, ou um cargo reconhecido
    apontando para categoria ausente, fariam um perfil COM cargo receber "sem
    cargo reconhecido".

    E O ESTRAGO SERIA PERMANENTE: esta frase é GRAVADA na linha. Um `id` nulo
    passageiro vira uma instrução errada que fica no banco pedindo à pessoa um
    campo que ela já preencheu — e a fila que mente é a fila que ninguém usa.
    """
    if tipo == "veiculo":
        return (
            "Entrou pela ingestão de menções com a categoria Imprensa, mas sem "
            "subcategoria — ela é lógica editorial que a fonte não informa, e é "
            "dela que a lente Mercado depende."
        )
    if not cargo_reconhecido:
        return (
            "Entrou pela ingestão de menções sem cargo reconhecido, então ficou "
            "sem categoria de público. Diga o cargo para o perfil entrar na "
            "taxonomia."
        )
    return (
        "Entrou pela ingestão de menções, e o enquadramento saiu do cargo que a "
        "fonte informou — confira se o cargo e a praça estão certos."
    )


def nomes_da_lista(sessao: Session, lista: str) -> frozenset[str]:
    """Os nomes NORMALIZADOS dos veículos que estão na lista pedida.

    NORMALIZADOS porque é assim que nome de veículo se compara em todo o
    sistema: `instituicao` tem índice único em `(nome_normalizado, tipo)`, e o
    texto que o fornecedor manda vem com acento, caixa e espaço variando.
    Comparar por `nome` cru marca "Valor Econômico" e "VALOR ECONOMICO" como
    veículos diferentes.

    LISTA VAZIA É RESPOSTA LEGÍTIMA, e não erro: numa base onde ninguém
    classificou veículo nenhum, a lente Mercado recorta para zero. É o estado da
    primeira subida, e `_ingerir_uma` já sabe que recorte vazio numa fonte irmã é
    fato, não falha.

    VEÍCULO DESATIVADO NÃO ESTÁ NA LISTA. `ativo=false` é o gesto de quem
    administra o cadastro dizendo "este não é um veículo corrente", e manter as
    menções dele contando numa lente faria a desativação significar duas coisas
    diferentes em dois lugares. `fontes_do_mesmo_arquivo` já filtra `ativo` pelo
    mesmo motivo. A aba o mostra com a marca "inativo — não conta na lente", para
    a consequência não ser silenciosa.
    """
    par = LISTAS_DE_VEICULOS.get(lista)
    if par is None:
        #: Nome que o motor aceitou e esta camada não conhece: as duas listas
        #: saíram de sincronia, e seguir devolveria "nenhum veículo" — um
        #: recorte vazio que ninguém saberia explicar.
        raise RegraViolada(
            f"a lista de veículos {lista!r} não tem tradução para o cadastro. "
            f"Conhecidas: {sorted(LISTAS_DE_VEICULOS)}."
        )
    categoria, subcategoria = par
    nomes = sessao.scalars(
        select(Instituicao.nome_normalizado)
        .join(
            SubcategoriaPublico,
            SubcategoriaPublico.id == Instituicao.subcategoria_publico_id,
        )
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            Instituicao.tipo == "veiculo",
            Instituicao.ativo.is_(True),
            CategoriaPublico.nome == categoria,
            SubcategoriaPublico.nome == subcategoria,
        )
        #: SEM `limit`, de propósito: aqui se quer a UNIÃO de todos os veículos
        #: que casam, e não uma subcategoria escolhida. Se um dia houver duas
        #: linhas com o mesmo par de nomes, o recorte inclui as duas — o que é
        #: mais seguro do que escolher uma e perder metade da lista.
    )
    da_lista = {nome for nome in nomes if nome}

    #: E OS APELIDOS DELES (`0102`).
    #:
    #: A LISTA É UM CONJUNTO DE NOMES, e o recorte casa o TEXTO da linha do
    #: fornecedor contra ele. Quando dois cadastros se fundem, o nome de quem sai
    #: deixa de existir em `instituicao` — então, sem esta união, toda fusão que
    #: levasse o nome de um veículo listado tirava as menções dele da lente
    #: Mercado, em silêncio e para trás. O apelido guarda esse nome apontando
    #: para o cadastro que ficou.
    #:
    #: E NÃO É SÓ A FUSÃO QUE TROCA DE TIPO: mesmo fundindo veículo em veículo, o
    #: texto que o clipping manda todo mês é o de quem SAIU.
    apelidos = sessao.scalars(
        select(InstituicaoApelido.nome_normalizado)
        .join(Instituicao, Instituicao.id == InstituicaoApelido.instituicao_id)
        .join(
            SubcategoriaPublico,
            SubcategoriaPublico.id == Instituicao.subcategoria_publico_id,
        )
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            Instituicao.tipo == "veiculo",
            Instituicao.ativo.is_(True),
            CategoriaPublico.nome == categoria,
            SubcategoriaPublico.nome == subcategoria,
        )
    )
    return frozenset(da_lista | {nome for nome in apelidos if nome})


def _texto(valor: object) -> str | None:
    texto = str(valor or "").strip()
    return texto or None
