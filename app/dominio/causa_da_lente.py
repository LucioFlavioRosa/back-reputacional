"""Por quais cortes se pergunta "onde está a causa".

O DONO DO PRODUTO FOI À TELA E NÃO ACHOU COMO DESCER OS NÍVEIS. O recorte
funcionava: a barra de filtros aplica, o servidor recalcula, a nota muda. Mas a
barra é um SELETOR — ela serve a quem JÁ SABE o que quer ver. Quem abre a lente
com a nota caída não sabe; a pergunta é "onde está a causa", e a tela só a
respondia por duas dimensões (tema e concessionária), enquanto o pacote declara
oito para a Sociedade digital.

AS ABAS SÃO A RESPOSTA DO PACOTE (FRONTEND §3). É uma pergunta só, feita por
vários cortes: trocar de aba é a navegação que faltava entre o nível 1 (a nota) e
o nível 3 (o item).

AQUI MORA O QUE É DECISÃO, e não consulta: QUAIS cortes a lente oferece e em que
ordem se pergunta. O SQL fica no repositório, que é quem conhece as colunas.
"""

from __future__ import annotations

from dataclasses import dataclass

#: O NOME DE CADA DIMENSÃO DO RECORTE, inclusive as que não são aba de lente
#: nenhuma.
#:
#: ACHADO DE REVISÃO: a trilha do aprofundamento percorria só a lista da lente, com
#: tier e atributo apensados à mão — as duas que eu tinha em mente quando escrevi.
#: `subtema` numa lente de clipping, ou `empresa` na Imprensa, eram aplicados pelo
#: servidor e NÃO apareciam na trilha: um degrau invisível, que não dá para
#: remover. Pior que não aceitar o recorte.
#:
#: A CHAVE É A DO PARÂMETRO DA ROTA. Toda dimensão que `FiltroDeMencoes` aceita
#: tem de estar aqui, e é isto que o teste da trilha trava.
ROTULO_DA_DIMENSAO: dict[str, str] = {
    #: O TEMA DO FORNECEDOR É O PILAR (N1) — definição do dono do produto. O
    #: subtema do fornecedor é o N3, e fica "(fornecedor)" até o de-para entrar.
    "tema": "Pilar (N1)",
    "subtema": "Subtema (fornecedor)",
    "empresa": "Concessionária",
    "veiculo": "Veículo",
    "perfil_autor": "Perfil de quem fala",
    "autor": "Autor",
    "uf": "UF",
    "tier": "Tier",
    "atributo": "Atributo",
    "tema_n1": "Pilar (N1)",
    "tema_n2": "Tema estratégico (N2)",
    "tema_n3": "Subtema (N3)",
}


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
        Dimensao("tema", "Pilar (N1)", "tema_texto"),
        Dimensao("subtema", "Subtema (fornecedor)", "subtema"),
        Dimensao("empresa", "Concessionária", "unidade_texto"),
        Dimensao("veiculo", "Rede", "veiculo"),
        Dimensao("perfil_autor", "Perfil de quem fala", "perfil_autor"),
        Dimensao("autor", "Autor", "autor"),
        Dimensao("uf", "UF", "uf"),
    ),
    "imprensa": (
        Dimensao("tema", "Pilar (N1)", "tema_texto"),
        Dimensao("atributo", "Atributo", "atributo"),
        Dimensao("veiculo", "Veículo", "veiculo"),
        Dimensao("uf", "UF", "uf"),
        Dimensao("autor", "Jornalista", "autor", nomeia_o_diretorio=True),
    ),
    "clientes": (
        Dimensao("tema", "Pilar (N1)", "tema_texto"),
        Dimensao("subtema", "Subtema (fornecedor)", "subtema"),
        Dimensao("empresa", "Concessionária", "unidade_texto"),
        Dimensao("uf", "UF", "uf"),
    ),
}


#: AS MESMAS ABAS EM TODO MÊS, E A QUE NÃO TEM DADO FICA VAZIA — decisão do dono
#: do produto (05/10/2026), e ela SUBSTITUI as "dimensões úteis" do pacote
#: (FRONTEND §3), que mediam quanto cada dimensão explicava o mês e escondiam a
#: que explicava pouco.
#:
#: O QUE O CRITÉRIO DO PACOTE CUSTAVA, no dado real: até maio/2026 só a Approach
#: entregava, e o tema vinha em 97% a 100% dos itens; em junho a Bites entra com
#: 4.973 posts sem tema, o tema cai para 28% do mês e a aba SUMIA. O dono do
#: produto abriu junho pelo ponto da Jornada e reparou na hora — "não tenho a
#: opção de tema como aparece nos demais meses".
#:
#: UMA FILEIRA DE ABAS QUE MUDA DE MÊS PARA MÊS SE LÊ COMO TELA QUEBRADA, e o
#: preço de mostrar a aba vazia é menor: ela diz que a fonte não classificou
#: aquele campo naquele mês — um fato sobre a fonte, e acionável, porque dá para
#: cobrar do fornecedor.
#:
#: QUANTO FALTA CONTINUA DITO na ficha de cada aba ("Tema vem em 1.959 das 6.932
#: menções do mês"), que é onde a informação não concorre com a navegação.
#:
#: E VALE PARA TODAS AS LENTES, e para os dois lugares onde as abas aparecem: o
#: cartão da tela e o painel de aprofundamento.
def dimensoes_do_recorte(codigo_da_lente: str, ve_diretorio: bool = True) -> list[Dimensao]:
    """Os cortes que esta lente oferece, na ordem em que ela se explica.

    `ve_diretorio` TIRA A ABA, E NÃO A LENTE: quem não alcança o cadastro de
    terceiros perde a aba que nomeia jornalista e fica com todas as outras. O
    contrário — esconder o cartão inteiro — pagaria a tela toda por uma coluna.
    """
    return [
        dimensao
        for dimensao in DIMENSOES_POR_LENTE.get(codigo_da_lente, ())
        if ve_diretorio or not dimensao.nomeia_o_diretorio
    ]
