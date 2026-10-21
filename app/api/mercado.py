"""As rotas do Painel de Inteligência de Mercado.

PRIMEIRO MÓDULO DO TERCEIRO PORTAL. O cartão dele existe na capa desde o início,
com `view: null` e `pronto: false`; estas são as primeiras rotas que ele serve.

O GUARDA DO ROUTER CHECA DUAS COISAS — ver
`dependencias.exigir_portal_de_inteligencia_de_mercado`: o ALCANCE
(`papel.acessa_inteligencia_de_mercado`) e a PORTA
(`configuracao.mercado_lancado`). Enquanto a bandeira estiver desligada estas
rotas recusam para todo mundo, inclusive para quem tem o papel — que é o estado
em que elas nascem, e o que permite mesclar o back antes de a tela existir.

ARQUIVO PRÓPRIO, e não uma seção de `score.py`: o preço de um bond não é menção,
não tem lente e não entra em régua de calibração. O que os dois domínios
compartilham é a TELA, que lê as duas rotas e cruza no cliente — e é no cliente
que o cruzamento pertence, porque a granularidade é diferente (o bond é diário, o
índice é mensal).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioLogado,
    exigir_escrita,
    exigir_portal_de_inteligencia_de_mercado,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import impacto_na_janela, ingerir_bonds, serie_de_mercado

rotas = APIRouter(
    prefix="/api/mercado",
    tags=["mercado"],
    dependencies=[Depends(exigir_portal_de_inteligencia_de_mercado)],
)

Sessao = SessaoDoPedido


class PapelSaida(BaseModel):
    ticker: str
    descricao: str | None
    emissor: str
    e_aegea: bool


class PontoDoBondSaida(BaseModel):
    data: date
    valor: Decimal


class SerieDoBondSaida(BaseModel):
    ticker: str
    pontos: list[PontoDoBondSaida]


class PontoDoIndiceSaida(BaseModel):
    #: `mes`, e NÃO `data` — o nome do campo é o que diz à tela que a medida é
    #: mensal enquanto a do bond é diária. Chamar os dois de `data` faria a tela
    #: interpolar uma linha diária que não existe.
    mes: date
    isr: int | None
    #: O SCORE DE CADA LENTE no mês, por código. Pedido de 20/10/2026: o gráfico
    #: passa a poder mostrar a nota da Imprensa, do Mercado e da Institucional
    #: ao lado do índice.
    #:
    #: SAI DA MESMA MEDIÇÃO QUE O `isr`, e é por isso que não há rota nova: o
    #: índice de um mês já mede as cinco lentes para somá-las. Duas rotas
    #: fariam a mesma conta duas vezes e poderiam discordar.
    #:
    #: NULO É "NÃO MEDIDA", como no `isr`: a lente sem dado fica fora do
    #: índice, e desenhar zero diria que a reputação dela foi péssima.
    lentes: dict[str, int | None] = {}


class SerieDeMercadoSaida(BaseModel):
    """As DUAS séries e o catálogo, numa resposta.

    O ÍNDICE VEM DAQUI, e não de `/api/score/serie`, por uma razão de permissão:
    aquela rota está atrás de `exigir_portal_score`, e quem tem só
    `acessa_inteligencia_de_mercado` recebe 403 dela. A linha do eixo direito
    sairia vazia por autorização e se leria como "o score não tem número neste
    período" — o pior formato de erro de autorização é o que parece dado.

    O NÚMERO É O MESMO do painel de KPIs: `serie_de_mercado` chama as mesmas
    `calibracao_vigente`, `catalogo_das_lentes` e `indice_do_mes` que a rota do
    Score usa. Uma segunda implementação divergiria no dia em que a régua
    mudasse, e a divergência apareceria como "um painel discorda do outro".
    """

    papeis: list[PapelSaida]
    bonds: list[SerieDoBondSaida]
    indice: list[PontoDoIndiceSaida]
    metrica: str


class ConferenciaDeBondsSaida(BaseModel):
    """O que a subida FARIA. Nenhum campo é agregado dos outros.

    `a_inserir` e `a_atualizar` somados dão as cotações de papéis CADASTRADOS, e
    não `cotacoes_no_arquivo` — a diferença é o que o arquivo traz de ticker que
    o cadastro não tem. Mandar só o total obrigaria a tela a inferir isso por
    subtração, e uma conta na tela é uma segunda fonte de verdade.
    """

    primeira_data: date | None
    ultima_data: date | None
    cotacoes_no_arquivo: int
    a_inserir: int
    a_atualizar: int
    por_ticker: dict[str, int]
    tickers_desconhecidos: list[str]
    tickers_sem_valor: list[str]
    rotulos_ignorados: list[tuple[str, str]]
    pares_repetidos: list[tuple[str, str]]
    linha_que_encerrou: int | None


class ImportacaoDeBondsSaida(BaseModel):
    inseridas: int
    atualizadas: int
    papeis_completados: int


@rotas.get("/bonds/serie")
def serie_dos_bonds(
    sessao: Sessao,
    usuario: UsuarioLogado,
    tickers: Annotated[str | None, Query()] = None,
    de: Annotated[date | None, Query()] = None,
    ate: Annotated[date | None, Query()] = None,
    metrica: Annotated[str, Query()] = serie_de_mercado.PRECO,
) -> SerieDeMercadoSaida:
    """A cotação dos papéis escolhidos e o índice mensal, no mesmo período.

    `tickers` É UMA LISTA SEPARADA POR VÍRGULA, e não repetição do parâmetro:
    é como o front já monta os filtros das outras telas, e a URL fica legível no
    painel de rede quando alguém for diagnosticar.

    VAZIO SIGNIFICA "OS DA AEGEA". Trinta e uma linhas num gráfico não se lê, e
    a tela abre na companhia — quem quer par pede par. Ticker que não existe no
    cadastro é ignorado em silêncio: não é erro do sistema, a série dele
    simplesmente não existe, e a legenda mostra o que voltou.

    SEM `de`/`ate` DEVOLVE A SÉRIE INTEIRA. O seletor de período da tela (1M, 3M,
    6M) é quem recorta, e um padrão de "últimos N dias" aqui faria a regra do
    recorte viver em dois lugares.
    """
    escolhidos = (
        [t.strip() for t in tickers.split(",") if t.strip()] if tickers else None
    )
    lida = serie_de_mercado.ler(
        sessao, tickers=escolhidos, de=de, ate=ate, metrica=metrica
    )
    return SerieDeMercadoSaida(
        papeis=[PapelSaida(**vars(p)) for p in lida.papeis],
        bonds=[
            SerieDoBondSaida(
                ticker=s.ticker,
                pontos=[PontoDoBondSaida(**vars(p)) for p in s.pontos],
            )
            for s in lida.bonds
        ],
        #: CAMPO A CAMPO, e não `**vars`: o ponto do índice ganhou `lentes`, e
        #: um dia ganha outro campo. `**vars` publica o que for acrescentado
        #: no caso de uso sem ninguém decidir publicar — foi assim que uma
        #: coluna de controle vazou para a tela em `api/catalogo`.
        indice=[
            PontoDoIndiceSaida(mes=p.mes, isr=p.isr, lentes=p.lentes) for p in lida.indice
        ],
        metrica=lida.metrica,
    )


class GrupoNaJanelaSaida(BaseModel):
    #: A CHAVE do cadastro. A tela desenha a lista por ela, e nao pelo nome:
    #: dois temas homonimos sob pilares diferentes sao duas linhas.
    id: int
    rotulo: str
    contexto: str | None
    impacto: float
    mencoes: int


class ImpactoNaJanelaSaida(BaseModel):
    de: date
    ate: date
    mes: date
    regua: str
    positivos: list[GrupoNaJanelaSaida]
    negativos: list[GrupoNaJanelaSaida]
    total_positivos: int
    total_negativos: int
    sem_grupo: int
    nivel: str
    sem_data: int
    mes_sem_base: bool
    lente: str
    dias: int


def _grupo(p: impacto_na_janela.ImpactoDoGrupo) -> GrupoNaJanelaSaida:
    """Um tema, campo por campo — ver o comentário em `impacto_por_n2`."""
    return GrupoNaJanelaSaida(
        id=p.id,
        rotulo=p.rotulo,
        contexto=p.contexto,
        impacto=p.impacto,
        mencoes=p.mencoes,
    )


class RegistroDaJanelaSaida(BaseModel):
    id: str
    data: date
    veiculo: str | None
    titulo: str | None
    link: str | None
    sentimento: str
    tier: str | None
    #: DE QUAL LENTE VEM ESTE REGISTRO. O código serve à tela (cor, ordem) e o
    #: nome é o que a pessoa lê — mandar só o código faria a tela ter um
    #: dicionário de nomes que envelhece sozinho no dia em que uma lente for
    #: renomeada por migration, como a `0061` renomeou.
    lente: str
    lente_nome: str


class RegistrosDaJanelaSaida(BaseModel):
    itens: list[RegistroDaJanelaSaida]
    total: int
    pagina: int
    tamanho: int


@rotas.get("/impacto-na-janela/registros")
def registros_da_janela(
    sessao: Sessao,
    usuario: UsuarioLogado,
    ate: Annotated[date, Query()],
    grupo: Annotated[int, Query(description="o id do pilar ou do tema do quadro")],
    dias: Annotated[int, Query(ge=1, le=90)] = impacto_na_janela.DIAS_DA_JANELA,
    nivel: Annotated[str, Query(pattern="^(n1|n2)$")] = impacto_na_janela.NIVEL_PADRAO,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RegistrosDaJanelaSaida:
    """As menções que compõem um grupo do quadro — o que abre ao clicar nele.

    O PEDIDO: "se eu clicar em alguma dessas opções quero que abra um modal com
    os registros do tema ou pilar, assim como fazemos nas lentes no KPI".

    `grupo` É O ID, e não o nome: nome de tema estratégico NÃO é único no
    cadastro, e o quadro agrupa por id desde o achado dos homônimos. Pelo nome,
    clicar em "Tarifa" traria junto a "Tarifa" de outro pilar — e a lista
    discordaria da contagem que está ao lado dela, na mesma tela.

    POR QUE NÃO A ROTA DA BASE DAS LENTES, que já lista menção por período e por
    tema: ela casa a data por `coalesce(data, mes)` e não tira as fontes
    desligadas. As duas diferenças são deliberadas lá e erradas aqui — ver
    `registros_do_grupo_na_janela`.

    MESMOS PARÂMETROS DA JANELA (`ate`, `dias`, `nivel`), e não um par de datas:
    quem sabe o que é uma janela de quinze dias é o caso de uso, e duas contas
    de data em dois lugares divergem na primeira mudança.
    """
    lidos = impacto_na_janela.registros(
        sessao, ate=ate, grupo=grupo, dias=dias, nivel=nivel, pagina=pagina, tamanho=tamanho
    )
    #: CAMPO A CAMPO, e não `**vars(r)`: as dataclasses do repositório têm
    #: `slots=True` e não têm `__dict__` — `vars()` levanta `TypeError`, e foi
    #: assim que esta mesma tela devolveu 500 em produção.
    return RegistrosDaJanelaSaida(
        itens=[
            RegistroDaJanelaSaida(
                id=r.id,
                data=r.data,
                veiculo=r.veiculo,
                titulo=r.titulo,
                link=r.link,
                sentimento=r.sentimento,
                tier=r.tier,
                lente=r.lente,
                lente_nome=r.lente_nome,
            )
            for r in lidos.itens
        ],
        total=lidos.total,
        pagina=lidos.pagina,
        tamanho=lidos.tamanho,
    )


@rotas.get("/impacto-na-janela")
def impacto_na_janela_(
    sessao: Sessao,
    usuario: UsuarioLogado,
    ate: Annotated[date, Query()],
    dias: Annotated[int, Query(ge=1, le=90)] = impacto_na_janela.DIAS_DA_JANELA,
    nivel: Annotated[str, Query(pattern="^(n1|n2)$")] = impacto_na_janela.NIVEL_PADRAO,
) -> ImpactoNaJanelaSaida:
    """Os temas estratégicos (N2) que mais empurraram a nota da imprensa na janela.

    NESTE ROTEADOR, E NÃO NO DO SCORE, por causa do guarda: a pergunta nasce no
    Painel de Inteligência de Mercado e quem pode fazê-la é quem tem o portal —
    `exigir_portal_de_inteligencia_de_mercado`, que já cerca este `APIRouter`
    inteiro. Pendurá-la no `score.py` a abriria para quem tem o Score e não tem
    este painel.

    `ate` É OBRIGATÓRIO de propósito: ele é o dia que a pessoa clicou no gráfico,
    e um padrão aqui ("hoje", "o último dia com dado") faria a tela mostrar uma
    janela que ninguém pediu quando o parâmetro se perdesse no caminho.

    `dias` TEM TETO porque a janela existe para ser um recorte: noventa dias já
    são três meses, e o denominador é de UM mês só — ver o cabeçalho do caso de
    uso. O teto não é performance, é a conta parar de querer dizer o que diz.

    A LENTE E A JANELA VOLTAM NA RESPOSTA, como `metrica` volta na série: é o que
    permite a tela afirmar "imprensa, 27/08 a 10/09" com o dado que desenhou, e
    não com o que ela pediu — os dois divergem enquanto a resposta não chega.
    """
    lida = impacto_na_janela.ler(sessao, ate=ate, dias=dias, nivel=nivel)
    return ImpactoNaJanelaSaida(
        de=lida.de,
        ate=lida.ate,
        mes=lida.mes,
        regua=lida.regua,
        #: CAMPO POR CAMPO, e não `**vars(p)`: `ImpactoDoPilar` é
        #: `@dataclass(frozen=True, slots=True)`, e dataclass com slots NÃO TEM
        #: `__dict__` — `vars()` levanta `TypeError` ali mesmo. Foi 500 no
        #: ambiente: clicar numa data SEM dado devolvia 200 (a compreensão de
        #: lista não roda com lista vazia) e clicar numa data COM dado — o caso
        #: que a funcionalidade existe para atender — devolvia "Erro interno".
        #:
        #: AS OUTRAS SAÍDAS DESTE MÓDULO usam `**vars(...)` e funcionam porque as
        #: dataclasses delas não declaram `slots`. A divergência estava nas duas
        #: minhas, e escrever os campos aqui é o que tira a saída da dependência
        #: de um detalhe da declaração da dataclass.
        positivos=[_grupo(p) for p in lida.positivos],
        negativos=[_grupo(p) for p in lida.negativos],
        total_positivos=lida.total_positivos,
        total_negativos=lida.total_negativos,
        sem_grupo=lida.sem_grupo,
        nivel=lida.nivel,
        sem_data=lida.sem_data,
        mes_sem_base=lida.mes_sem_base,
        lente=impacto_na_janela.LENTE,
        dias=dias,
    )


@rotas.post("/bonds/conferencia")
def conferir_bonds(
    sessao: Sessao,
    usuario: Annotated[UsuarioLogado, Depends(exigir_escrita)],
    arquivo: Annotated[UploadFile, File()],
) -> ConferenciaDeBondsSaida:
    """Lê o export e diz o que a subida faria. NÃO escreve nada.

    EXIGE ESCRITA mesmo sem escrever, e de propósito: quem só lê não tem o que
    fazer com uma prévia de importação, e deixar a rota aberta a ele revelaria
    o conteúdo de um arquivo que ele não vai poder subir.

    AS RECUSAS ESTRUTURAIS SAEM DAQUI, antes de a pessoa decidir nada: arquivo
    que não é `.xlsx`, arquivo grande demais, planilha sem aba. `app/api/erros.py`
    as traduz para 422.
    """
    return ConferenciaDeBondsSaida(
        **vars(ingerir_bonds.conferir(sessao, arquivo.file.read()))
    )


@rotas.post("/bonds/importar")
def importar_bonds(
    sessao: Sessao,
    usuario: Annotated[UsuarioLogado, Depends(exigir_escrita)],
    arquivo: Annotated[UploadFile, File()],
) -> ImportacaoDeBondsSaida:
    """Grava as cotações, por `upsert` na chave `(bond_ticker, data)`.

    RECEBE O ARQUIVO DE NOVO, e não um identificador do que a conferência
    guardou. A montagem por partes de `planilha_do_score` é por fonte do Score e
    generalizá-la para outro domínio é bloco próprio; enquanto o arquivo tem 1,05
    MB — abaixo do limite de 1,2 MB que faz o front fatiar — reenviar os bytes é
    o que a tela já faria de qualquer forma.

    SUBIR O MESMO ARQUIVO DUAS VEZES É INOFENSIVO, e isso é propriedade da chave
    composta, não gentileza desta rota: a segunda subida atualiza as mesmas
    linhas com os mesmos valores. É o que torna a rotina semanal segura mesmo
    quando alguém não lembra se já subiu.
    """
    resultado = ingerir_bonds.gravar(sessao, arquivo.file.read())
    sessao.commit()
    return ImportacaoDeBondsSaida(**vars(resultado))
