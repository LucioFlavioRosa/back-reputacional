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
from app.dominio.ingestao_score import para_sigla
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
    sessao: Session, veiculos: dict[str, dict[str, object]]
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
    existentes = {
        normalizado: str(ident)
        for normalizado, ident in sessao.execute(
            select(Instituicao.nome_normalizado, Instituicao.id).where(
                Instituicao.tipo == "veiculo",
                Instituicao.nome_normalizado.in_(list(nomes)),
            )
        ).all()
    }

    novos = [
        VeiculoNovo(
            nome=bruto,
            uf=_texto(veiculos[bruto].get("uf")),
            esfera=ESFERA_POR_ABRANGENCIA.get(
                str(veiculos[bruto].get("abrangencia") or "").strip().lower()
            ),
            mencoes=int(veiculos[bruto].get("mencoes") or 0),
        )
        for normalizado, bruto in nomes.items()
        if normalizado not in existentes
    ]
    novos.sort(key=lambda v: (-v.mencoes, v.nome))
    return Reconhecimento(cadastrados=existentes, novos=tuple(novos))


def criar(sessao: Session, novos: tuple[VeiculoNovo, ...]) -> dict[str, str]:
    """Cadastra os veículos que faltam e devolve nome normalizado -> id.

    NASCEM COMO IMPRENSA E SEM SUBCATEGORIA. A categoria é a única que o
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

    categoria = sessao.scalar(
        select(CategoriaPublico.id).where(
            CategoriaPublico.nome == CATEGORIA_DA_IMPRENSA,
            CategoriaPublico.ativo,
        )
    )
    esferas = {
        nome: ident
        for nome, ident in sessao.execute(select(Esfera.nome, Esfera.id)).all()
    }

    criados: dict[str, str] = {}
    for veiculo in novos:
        nome = " ".join(veiculo.nome.split())
        registro = Instituicao(
            nome=nome,
            nome_normalizado=normalizar(nome),
            tipo="veiculo",
            categoria_publico_id=categoria,
            esfera_id=esferas.get(veiculo.esfera or ""),
            # A SIGLA, e não o nome: `instituicao.uf` é o domínio
            # `abrangencia`, com CHECK das 29 siglas — "Santa Catarina" ali é
            # recusado pelo Postgres. É a assimetria com `mencao.uf`, que
            # guarda o nome por decisão do dono; `para_sigla` documenta as duas.
            uf=para_sigla(veiculo.uf),
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
