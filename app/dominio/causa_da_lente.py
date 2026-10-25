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
    #: O ATRIBUTO DA CLIPEI É O N1 DA AEGEA — os 7 atributos reputacionais
    #: (Governança, Eficiência Operacional e Qualidade…), por pedido do dono do
    #: produto. A planilha real o traz com prefixo ("7. Prosperidade…").
    "atributo": "N1 Atributo Reputacional",
    "tema_n1": "Pilar (N1)",
    "tema_n2": "N2 Tema estratégico",
    "tema_n3": "N3 Subtema",
    "sentimento": "Sentimento",
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
    #: Imprensa. É a mesma pergunta que `nomeia_o_diretorio` faz dos painéis
    #: (em `casos_de_uso/leitura_das_lentes`).
    nomeia_o_diretorio: bool = False
    #: TODOS OS VALORES, sem o corte dos seis maiores. Para a taxonomia da Aegea
    #: (7 atributos, ~41 temas estratégicos, 104 subtemas): é um vocabulário
    #: FECHADO, e cortar o sétimo atributo esconderia justamente um dos sete.
    todos: bool = False


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
#: O MERCADO ESTAVA JUNTO DELA, E ERA ERRO MEU DE PREMISSA. O comentário dizia
#: "a fonte é estudo e agenda" para os dois. Para o Mercado isso é falso: ele é
#: o clipping da Clipei recortado por público-alvo Investidores (migration
#: 0048), e tem menção ingerida como a Imprensa. Medido:
#:
#:     MERCADO        327 menções    tema 327 (34 distintos)   atributo 327 (8)
#:                                   veículo 327               uf 327 (10 UFs)
#:                                   autor 0
#:     INSTITUCIONAL    0 menções
#:
#: Quatro das cinco dimensões da Imprensa estão 100% preenchidas no Mercado, e
#: nenhum corte devolveria zero.
#:
#: O `autor` entra nas três lentes de clipping, por paridade. A carga ainda
#: não traz valores nessa coluna: a aba existe por decisão de produto, e não
#: por ter dado.
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
    #: AS MESMAS DA IMPRENSA, Jornalista incluso: as três lentes de clipping
    #: são a mesma tela.
    #:
    #: `nomeia_o_diretorio=True` não é enfeite da aba: é de onde a Base das
    #: Lentes deriva se pode publicar o nome do autor para quem não tem a
    #: permissão do diretório (ver `nomeia_o_diretorio`, abaixo). A flag
    #: acompanha a dimensão `autor` em TODA lente de clipping — sem ela,
    #: aquela lente publica o nome do autor para quem não vê o diretório.
    #:
    #: E é o mesmo autor, não outro: as três são o mesmo export da Clipei pela
    #: mesma ingestão. O `autor` é o jornalista, e não o perfil que vem dentro
    #: da menção.
    #:
    #: E O TIER NÃO ENTRA, pela mesma razão que não entra na Imprensa: ele já é
    #: a rosca no alto da tela, e uma aba que repete um painel da mesma tela
    #: gasta a vez de uma que não está em nenhum lugar.
    "mercado": (
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
    #: AS MESMAS DO MERCADO, porque o export é o mesmo, recortado de outro
    #: jeito: desde a `0111` a Institucional é o clipping da Clipei recortado
    #: pela subcategoria "Institucional" do cadastro, e a `0112` tirou o CRM do
    #: índice. Jornalista incluso, com a flag, pela razão escrita no Mercado.
    "institucional": (
        Dimensao("tema", "Pilar (N1)", "tema_texto"),
        Dimensao("atributo", "Atributo", "atributo"),
        Dimensao("veiculo", "Veículo", "veiculo"),
        Dimensao("uf", "UF", "uf"),
        Dimensao("autor", "Jornalista", "autor", nomeia_o_diretorio=True),
    ),
}


#: AS ABAS DO APROFUNDAMENTO — o painel que abre ao clicar num dado (a coluna da
#: Evolução, uma barra de tema) —, quando a lente pede abas próprias ali.
#:
#: NA IMPRENSA, A TAXONOMIA DA AEGEA, na ordem em que ela desce, por pedido do
#: dono do produto: N1 (os 7 atributos reputacionais, da coluna Atributo da
#: Clipei), N2 (os temas estratégicos) e N3 (os subtemas). N2 e N3 saem do
#: vínculo da menção com o cadastro (`tema_id`, gravado na ingestão desde o
#: `temas_da_mencao`): é o mesmo caminho que o filtro `tema_n2`/`tema_n3` usa, e
#: por isso o clique numa coluna recorta exatamente o que a coluna contou.
#:
#: O CARTÃO "ONDE ESTÁ A CAUSA" DA SÍNTESE CONTINUA com as abas de
#: `DIMENSOES_POR_LENTE`: o pedido foi para o painel, não para o cartão.
#:
#: O MERCADO ENTROU AQUI (20/10/2026, por pedido de paridade visual com a
#: Imprensa): é a mesma Clipei, com atributo e tema_id gravados pela MESMA
#: ingestão (`temas_da_mencao`) — ver a medição em `DIMENSOES_POR_LENTE`
#: acima (atributo 100% preenchido no Mercado).
#:
#: A INSTITUCIONAL ENTROU LOGO DEPOIS, no mesmo dia: a nota acima ("lê o CRM,
#: tem zero menções") morreu com a `0111`/`0112` — ela também é a Clipei,
#: recortada pela subcategoria "Institucional" em vez de "Investidores", pela
#: MESMA fonte `clipei_institucional` que espelha a `clipei` por inteiro (ver
#: `test_a_fonte_institucional_ESPELHA_a_clipei`). Atributo e tema_id vêm da
#: mesma ingestão do Mercado; não há razão para a Institucional ficar de fora
#: de uma tela que as outras duas lentes de clipping já têm.
DIMENSOES_DO_APROFUNDAMENTO: dict[str, tuple[Dimensao, ...]] = {
    "imprensa": (
        Dimensao("atributo", "N1 Atributo Reputacional", "atributo", todos=True),
        Dimensao("tema_n2", "N2 Temas estratégicos", "tema_id", todos=True),
        Dimensao("tema_n3", "N3 Subtemas", "tema_id", todos=True),
    ),
    "mercado": (
        Dimensao("atributo", "N1 Atributo Reputacional", "atributo", todos=True),
        Dimensao("tema_n2", "N2 Temas estratégicos", "tema_id", todos=True),
        Dimensao("tema_n3", "N3 Subtemas", "tema_id", todos=True),
    ),
    "institucional": (
        Dimensao("atributo", "N1 Atributo Reputacional", "atributo", todos=True),
        Dimensao("tema_n2", "N2 Temas estratégicos", "tema_id", todos=True),
        Dimensao("tema_n3", "N3 Subtemas", "tema_id", todos=True),
    ),
}


def dimensoes_do_aprofundamento(
    codigo_da_lente: str, ve_diretorio: bool = True
) -> list[Dimensao]:
    """As abas do painel de aprofundamento: as próprias da lente, quando ela as
    declara, e senão as mesmas do cartão "Onde está a causa"."""
    proprias = DIMENSOES_DO_APROFUNDAMENTO.get(codigo_da_lente)
    if proprias is None:
        return dimensoes_do_recorte(codigo_da_lente, ve_diretorio)
    return [d for d in proprias if ve_diretorio or not d.nomeia_o_diretorio]


def nomeia_o_diretorio(codigo_da_lente: str) -> bool:
    """Esta lente publica nome de gente de fora que o CADASTRO guarda?

    A PERGUNTA É A MESMA EM DOIS LUGARES, e a resposta tem de ser uma. Além do
    cartão "Onde está a causa" (que tira a aba), a Base das Lentes esconde a
    coluna `autor` e não oferece o filtro dela — e essa segunda regra estava
    escrita como `codigo == "imprensa"`, repetida em três pontos de
    `app/api/base_das_lentes.py`.

    DUAS CÓPIAS DE UMA REGRA DE ACESSO DIVERGEM NA PRIMEIRA MUDANÇA: marcar uma
    lente nova com `nomeia_o_diretorio=True` tiraria a aba do cartão e deixaria
    a coluna e o filtro da Base publicando o nome, sem erro nenhum. Derivar da
    declaração é o que fecha esse vão.

    O CRITÉRIO É A ORIGEM DO DADO, não o nome da coluna (ver `Dimensao`): na
    Imprensa, `autor` é o jornalista do cadastro de terceiros; na Sociedade
    digital e em Clientes é o perfil que veio DENTRO da menção — o `Publicador`
    que o fornecedor manda na própria linha, que o indicador "Autor mais
    negativo" já mostra a todo mundo. Por isso respondem `True` as
    três lentes de clipping, e por isso o `Publicador` da Approach entra
    aberto.
    """
    return any(
        dimensao.nomeia_o_diretorio
        for dimensao in DIMENSOES_POR_LENTE.get(codigo_da_lente, ())
    )


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
