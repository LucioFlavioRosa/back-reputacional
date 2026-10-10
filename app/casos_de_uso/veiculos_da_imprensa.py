"""Ligar a menção ao veículo do cadastro compartilhado, e criar o que falta.

POR QUE ISTO EXISTE. A menção guardava o veículo como texto do fornecedor
(`mencao.veiculo`) e nada mais. O cadastro compartilhado já modela veículo —
`instituicao` com `tipo='veiculo'`, categoria de público, subcategoria editorial
e esfera —, e as duas metades não se falavam: 39 veículos cadastrados, 2.648
distintos no export de dois meses da Clipei.

O EFEITO DISSO NA LENTE MERCADO. Ela se separa hoje por
`Público-alvo = Investidores`, o que captura 80 linhas quando a lista de
veículos do mercado financeiro que a Aegea mantém captura 323 — e as duas listas
discordam em 267 das 335 linhas envolvidas. Com o vínculo, o critério passa a
ser a subcategoria "Econômica e de negócios" do cadastro, e a lista se mantém
pela tela de Cadastro de Instituições em vez de por SQL.

CRIAR NO UPLOAD, MAS NÃO EM SILÊNCIO. O dono do produto pediu que o veículo sem
cadastro nasça junto com a subida. Pediu também — e isto é o que torna a coisa
segura — que a conta apareça ANTES de confirmar. É a mesma lição que a
importação de agendas aprendeu e escreveu no próprio código: "importação de
planilha sem conferência humana cria duplicata de instituição em massa, e
desfazer isso depois é pior que digitar de novo". Aqui são ~2.600 criações numa
subida; ver o número antes é a diferença entre decidir e descobrir.

O QUE O FORNECEDOR SABE, E O QUE ELE NÃO SABE. Do export vêm o nome, a praça
(`Estado do Veículo`) e o alcance (`Abrangência`, que casa com `esfera`). O que
ele NÃO diz é a lógica editorial: nenhuma coluna da Clipei informa que a
InfoMoney é imprensa econômica. Então o veículo nasce com `subcategoria` NULA, e
essa classificação continua sendo juízo humano — o que é certo, porque é dela
que a lente Mercado depende.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, Esfera, SubcategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import (
    normalizar_cargo,
    para_sigla,
    rotulo_do_cargo,
)
from app.dominio.texto import normalizar

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
#: POR QUE ISTO EXISTE. A primeira carga criou os 1.108 perfis todos como
#: "Formadores de Opinião", e quem abriu o cadastro viu o vereador Iriel Sachet
#: classificado como formador de opinião — errado, e o cadastro TEM o
#: vocabulário certo: a taxonomia de públicos prevê Poder Legislativo com
#: Federal, Estadual e Municipal desde a `0036`.
#:
#: O CARGO VINHA SENDO JOGADO FORA no cadastro. A coluna `Cargo` da Bites
#: alimentava a régua de peso e o gráfico de quem fala, mas o perfil nascia sem
#: ela — e é ela que diz se o ator é poder público, imprensa ou sociedade.
#:
#: SÓ O QUE SE PODE DEFENDER ESTÁ AQUI. `político` (19 menções) pode ser
#: executivo ou legislativo; `partido`, `empresa` e `órgão público` não têm par
#: óbvio na taxonomia; `outros`, `alemao` e `perfil de twitter` não são cargo.
#: Esses ficam SEM categoria — que é a verdade ("ainda não classificado"), e é
#: um estado que o cadastro já conhece. Chutar classificaria 2.249 perfis
#: anônimos como formadores de opinião, que é o defeito que isto conserta.
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

    #: UMA CONSULTA, e não uma por veículo: são 2.648 nomes no export de dois
    #: meses da Clipei, e 2.648 idas ao banco levariam minutos.
    #:
    #: EM QUALQUER TIPO, e é decisão do dono do produto: UM CADASTRO SÓ, vindo
    #: do Cadastro compartilhado.
    #:
    #: O QUE ISTO CONSERTA, medido nesta base: "Valor Econômico" existia TRÊS
    #: vezes — como veículo (86 menções, na lista do Mercado) e como dois
    #: perfis de rede (2 e 11 menções, sem classificação nenhuma). Treze
    #: menções do Valor não somavam com as 86, e nenhuma tela juntava. São 94
    #: atores com cadastro duplicado entre imprensa e rede.
    #:
    #: O CANAL NÃO SE PERDE AO UNIFICAR, e era essa a minha objeção: quem diz
    #: "foi em rede social" é a FONTE da menção — `bites` alimenta a lente
    #: Sociedade digital, `clipei` a Imprensa. A instituição responde QUEM
    #: falou; a fonte responde ONDE.
    achados: dict[str, tuple[str, bool]] = {}
    for normalizado, ident, de_outro_tipo in sessao.execute(
        select(
            Instituicao.nome_normalizado,
            Instituicao.id,
            (Instituicao.tipo != tipo).label("de_outro_tipo"),
        ).where(
            Instituicao.nome_normalizado.in_(list(nomes)),
            #: EM QUALQUER TIPO SÓ QUANDO QUEM FALA É UM PERFIL. O `Veículo` do
            #: clipping é SEMPRE um meio de imprensa: um nome igual ao de um
            #: órgão ali é HOMÔNIMO, e não o mesmo ator — apontar a matéria do
            #: jornal para a prefeitura seria atribuição errada. O perfil de
            #: rede é o contrário: o Instagram do Valor Econômico É o Valor.
            *([] if tipo == "perfil_rede" else [Instituicao.tipo == tipo]),
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

    novos = [
        VeiculoNovo(
            nome=bruto,
            uf=_texto(veiculos[bruto].get("uf")),
            esfera=ESFERA_POR_ABRANGENCIA.get(
                str(veiculos[bruto].get("abrangencia") or "").strip().lower()
            ),
            mencoes=int(veiculos[bruto].get("mencoes") or 0),
            cargo=normalizar_cargo(veiculos[bruto].get("cargo")),
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
        if tipo == "perfil_rede":
            par = CATEGORIA_POR_CARGO.get(veiculo.cargo or "")
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
        )
        sessao.add(registro)
        criados[normalizar(nome)] = registro
    sessao.flush()
    return {chave: str(registro.id) for chave, registro in criados.items()}


def nomes_da_lista(sessao: Session, lista: str) -> frozenset[str]:
    """Os nomes NORMALIZADOS dos veículos que estão na lista pedida.

    NORMALIZADOS porque é assim que nome de veículo se compara em todo o
    sistema: `instituicao` tem índice único em `(nome_normalizado, tipo)`, e o
    texto que o fornecedor manda vem com acento, caixa e espaço variando. A
    comparação por `nome` cru marcaria "Valor Econômico" e "VALOR ECONOMICO"
    como veículos diferentes — foi exatamente o que aconteceu na primeira
    versão da `0066`, que casou 78 de 81 por usar `lower()`.

    LISTA VAZIA É RESPOSTA LEGÍTIMA, e não erro: numa base onde ninguém
    classificou veículo nenhum, a lente Mercado recorta para zero. É o estado
    da primeira subida, e `_ingerir_uma` já sabe que recorte vazio numa fonte
    irmã é fato, não falha.

    VEÍCULO DESATIVADO NÃO ESTÁ NA LISTA. `ativo=false` é o gesto de quem
    administra o cadastro dizendo "este não é um veículo corrente", e manter as
    menções dele contando numa lente faria a desativação significar duas coisas
    diferentes em dois lugares. `fontes_do_mesmo_arquivo` já filtra `ativo` pelo
    mesmo motivo. A aba o mostra com a marca "inativo — não conta na lente",
    para a consequência não ser silenciosa.
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
    return frozenset(nome for nome in nomes if nome)


def _texto(valor: object) -> str | None:
    texto = str(valor or "").strip()
    return texto or None
