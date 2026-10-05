"""Por quais cortes se pergunta "onde está a causa" — e quando um corte explica.

O DONO DO PRODUTO FOI À TELA E NÃO ACHOU COMO DESCER OS NÍVEIS. O recorte
funcionava: a barra de filtros aplica, o servidor recalcula, a nota muda. Mas a
barra é um SELETOR — ela serve a quem JÁ SABE o que quer ver. Quem abre a lente
com a nota caída não sabe; a pergunta é "onde está a causa", e a tela só a
respondia por duas dimensões (tema e concessionária), enquanto o pacote declara
oito para a Sociedade digital.

AS ABAS SÃO A RESPOSTA DO PACOTE (FRONTEND §3: "abas das dimensões úteis"). É uma
pergunta só, feita por vários cortes: trocar de aba é a navegação que faltava
entre o nível 1 (a nota) e o nível 3 (o item).

AQUI MORA O QUE É DECISÃO, e não consulta: a ordem em que se pergunta, e quando
um corte merece aba. O SQL fica no repositório, que é quem conhece as colunas.
"""

from __future__ import annotations

from dataclasses import dataclass

#: QUANTAS ABAS CABEM. O pacote pede "máx. 6 visíveis + mais"; seis é o número a
#: partir do qual a fileira de abas deixa de ser escolha e passa a ser lista —
#: e uma lista de cortes é exatamente a barra de filtros que já existe.
ABAS = 6

#: NULO DEMAIS PARA SER CAUSA. Uma dimensão que a fonte quase não classificou não
#: explica o mês: explica a si mesma. Com 70% de nulo, a maior barra do painel
#: seria "sem classificação" — e quem lê conclui que a lente está quebrada, não
#: que o fornecedor não mandou o campo.
#:
#: QUANTO FALTA CONTINUA VISÍVEL, na lacuna da ficha de cada aba: o corte sai da
#: fileira de abas, não do conhecimento de quem lê.
NULO_DEMAIS = 0.6


@dataclass(frozen=True)
class Dimensao:
    """Um corte pelo qual se pergunta onde está a causa.

    `chave` É O PARÂMETRO DA ROTA (`?uf=RJ`), e não o nome da coluna: é o que a
    tela põe na URL quando alguém clica na barra, e é o que faz um link
    reproduzir o ponto exato do caminho.
    """

    chave: str
    rotulo: str
    #: O atributo de `Mencao` que guarda o valor. Texto, e não a coluna em si,
    #: porque o domínio não importa o ORM — o repositório resolve.
    campo: str
    #: ESTA ABA PUBLICA NOME DE GENTE DE FORA? ACHADO DE REVISÃO, e ele é sobre a
    #: mesma coluna significar coisas diferentes em duas lentes: na Imprensa,
    #: `autor` é o JORNALISTA — o mesmo cadastro de terceiros que a matriz de
    #: jornalistas publica e que `ve_diretorio` guarda; na Sociedade é o perfil de
    #: rede que veio DENTRO da menção, que o indicador "Autor mais negativo" já
    #: mostra a todo mundo.
    #:
    #: POR DIMENSÃO E POR LENTE, portanto, e não pelo nome da coluna: gatilhar
    #: pelo nome esconderia da Sociedade um dado que é dela, ou publicaria o da
    #: Imprensa. É a mesma pergunta que `_nomeia_o_diretorio` faz dos painéis.
    nomeia_o_diretorio: bool = False


@dataclass(frozen=True)
class Presenca:
    """Quanto uma dimensão aparece no mês: quantas menções a trazem, e em
    quantos valores distintos."""

    preenchidas: int
    distintas: int


#: A ORDEM DE CADA LENTE — é a ordem em que a lente se EXPLICA, e por isso é
#: declarada aqui e não ordenada por volume. Em junho de 2026 a aba de autor
#: tem mais linhas que a de tema; ainda assim ninguém abre a lente querendo
#: saber quem falou antes de saber do que se falou.
#:
#: A DA SOCIEDADE É A DO PACOTE, na letra: tema, subtema, empresa citada, rede,
#: perfil do autor, autor, fonte, UF. Falta `fonte` — ela não é um corte do
#: assunto, é de procedência, e vive na ficha de cada bloco.
#:
#: TIER NÃO ENTRA NA IMPRENSA porque ele já é o painel A da lente: uma aba que
#: repete um painel da mesma tela gasta a vez de uma que não está em nenhum.
#:
#: MERCADO E INSTITUCIONAL NÃO ESTÃO AQUI, e é a mesma razão que esvazia os
#: painéis delas: a fonte é estudo e agenda, não menção ingerida. Rodar os
#: cortes devolveria zero, e zero numa tela se lê como "não houve".
DIMENSOES_POR_LENTE: dict[str, tuple[Dimensao, ...]] = {
    "sociedade": (
        Dimensao("tema", "Tema", "tema_texto"),
        Dimensao("subtema", "Subtema", "subtema"),
        Dimensao("empresa", "Concessionária", "unidade_texto"),
        Dimensao("veiculo", "Rede", "veiculo"),
        Dimensao("perfil_autor", "Perfil de quem fala", "perfil_autor"),
        Dimensao("autor", "Autor", "autor"),
        Dimensao("uf", "UF", "uf"),
    ),
    "imprensa": (
        Dimensao("tema", "Tema", "tema_texto"),
        Dimensao("atributo", "Atributo", "atributo"),
        Dimensao("veiculo", "Veículo", "veiculo"),
        Dimensao("uf", "UF", "uf"),
        Dimensao("autor", "Jornalista", "autor", nomeia_o_diretorio=True),
    ),
    "clientes": (
        Dimensao("tema", "Tema", "tema_texto"),
        Dimensao("subtema", "Subtema", "subtema"),
        Dimensao("empresa", "Concessionária", "unidade_texto"),
        Dimensao("uf", "UF", "uf"),
    ),
}


def explica(presenca: Presenca, total: int) -> bool:
    """Esta dimensão explica o mês, ou só a si mesma?

    DOIS VALORES, NO MÍNIMO: com um só, a barra ocupa a largura inteira e diz
    "100% de tudo é isto" — informação zero, e uma aba gasta.

    E NULO ABAIXO DE `NULO_DEMAIS`: ver o comentário da constante.
    """
    if total <= 0:
        return False
    return presenca.distintas >= 2 and presenca.preenchidas > total * (1 - NULO_DEMAIS)


def dimensoes_que_explicam(
    codigo_da_lente: str,
    presencas: dict[str, Presenca],
    total: int,
    ve_diretorio: bool = True,
) -> list[Dimensao]:
    """As abas desta lente, na ordem dela, até o teto de `ABAS`.

    `ve_diretorio` TIRA A ABA, E NÃO A LENTE: quem não alcança o cadastro de
    terceiros perde a aba que nomeia jornalista e fica com todas as outras. O
    contrário — esconder o cartão inteiro — pagaria a tela toda por uma coluna.
    """
    candidatas = DIMENSOES_POR_LENTE.get(codigo_da_lente, ())
    return [
        dimensao
        for dimensao in candidatas
        if explica(presencas.get(dimensao.chave, Presenca(0, 0)), total)
        and (ve_diretorio or not dimensao.nomeia_o_diretorio)
    ][:ABAS]
