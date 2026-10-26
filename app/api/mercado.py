"""As rotas do Painel de Inteligência de Mercado.

O GUARDA DO ROUTER CHECA DUAS COISAS — ver
`dependencias.exigir_portal_de_inteligencia_de_mercado`: o ALCANCE
(`papel.acessa_inteligencia_de_mercado`) e a PORTA
(`configuracao.mercado_lancado`). Com a bandeira desligada estas rotas recusam
para todo mundo, inclusive para quem tem o papel.

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
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioLogado,
    exigir_escrita,
    exigir_portal_de_inteligencia_de_mercado,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import (
    impacto_na_janela,
    ingerir_bonds,
    planilha_de_bonds,
    planilha_do_score,
    serie_de_mercado,
    subida_em_partes,
)

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
    #: O SCORE DE CADA LENTE no mês, por código: é o que deixa o gráfico mostrar
    #: a nota da Imprensa, do Mercado e da Institucional ao lado do índice.
    #:
    #: SAI DA MESMA MEDIÇÃO QUE O `isr`, e é por isso que não há rota nova: o
    #: índice de um mês já mede as cinco lentes para somá-las. Duas rotas fariam
    #: a mesma conta duas vezes e poderiam discordar.
    #:
    #: NULO É "NÃO MEDIDA", como no `isr`: a lente sem dado fica fora do índice,
    #: e desenhar zero diria que a reputação dela foi péssima.
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
    #: As lentes que a conta somou, e quanto elas pesaram no índice do mês.
    lentes: list[str]
    fatia_das_lentes: float
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
    #: nome é o que a pessoa lê — mandar só o código faria a tela guardar um
    #: dicionário de nomes, e o nome de uma lente mora no cadastro (`lente.nome`).
    #: É o que `repositorio_riscos` já faz, com este mesmo rótulo.
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
    nivel: Annotated[str, Query(pattern="^(n1|n2|n3)$")] = impacto_na_janela.NIVEL_PADRAO,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=200)] = 50,
    lentes: Annotated[
        str | None,
        Query(
            pattern="^(imprensa|mercado|institucional)(,(imprensa|mercado|institucional))*$",
            #: OMITIR, E NÃO MANDAR VAZIO: a regex exige ao menos uma lente, e
            #: `lentes=` é 422. A descrição diz isso porque quem a lesse ao pé
            #: da letra escreveria a chamada que a rota recusa.
            description=(
                "as lentes do quadro, separadas por vírgula. OMITIR o parâmetro é "
                "pedir as três; mandá-lo vazio é 422."
            ),
        ),
    ] = None,
    tier: Annotated[
        str | None, Query(pattern="^(muito_relevante|relevante|menos_relevante)$")
    ] = None,
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
        sessao,
        ate=ate,
        grupo=grupo,
        dias=dias,
        nivel=nivel,
        pagina=pagina,
        tamanho=tamanho,
        lentes=lentes.split(",") if lentes else None,
        tier=tier,
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
    nivel: Annotated[str, Query(pattern="^(n1|n2|n3)$")] = impacto_na_janela.NIVEL_PADRAO,
    lentes: Annotated[
        str | None,
        Query(
            pattern="^(imprensa|mercado|institucional)(,(imprensa|mercado|institucional))*$",
            #: OMITIR, E NÃO MANDAR VAZIO: a regex exige ao menos uma lente, e
            #: `lentes=` é 422. A descrição diz isso porque quem a lesse ao pé
            #: da letra escreveria a chamada que a rota recusa.
            description=(
                "as lentes do quadro, separadas por vírgula. OMITIR o parâmetro é "
                "pedir as três; mandá-lo vazio é 422."
            ),
        ),
    ] = None,
    tier: Annotated[
        str | None, Query(pattern="^(muito_relevante|relevante|menos_relevante)$")
    ] = None,
) -> ImpactoNaJanelaSaida:
    """Os temas que mais empurraram o ÍNDICE na janela — em pontos do score geral.

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
    lida = impacto_na_janela.ler(
        sessao,
        ate=ate,
        dias=dias,
        nivel=nivel,
        lentes=lentes.split(",") if lentes else None,
        tier=tier,
    )
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
        #: AS LENTES QUE A CONTA SOMOU, e a fatia delas no índice do mês. O
        #: impacto é em ponto do SCORE GERAL e soma as três de clipping, cada
        #: uma pelo peso dela; as duas coisas vêm da RESPOSTA e não de uma
        #: constante, porque a lente sem dado no mês não entrou.
        lentes=list(lida.lentes),
        fatia_das_lentes=lida.fatia_das_lentes,
        dias=dias,
    )


class SubidaDeBondsSaida(BaseModel):
    """O que o cliente precisa para subir o export em pedaços.

    `subida_id` NULO SIGNIFICA "AQUI NÃO DÁ, MANDE DE UMA VEZ" — ambiente sem
    armazenamento não tem onde montar. A tela cai no caminho de sempre em vez de
    mostrar uma recusa crua: um 422 aqui seria indistinguível das outras recusas
    desta rota.

    `tamanho_da_parte` VAI MESMO ASSIM, e não condicionalmente: ele não depende
    do armazenamento, e um campo que às vezes falta obrigaria o cliente a tratar
    duas formas de resposta em vez de um campo nulo.
    """

    subida_id: UUID | None
    tamanho_da_parte: int


@rotas.post("/bonds/upload")
def abrir_subida_de_bonds(
    sessao: Sessao,
    usuario: Annotated[UsuarioLogado, Depends(exigir_escrita)],
    tarefas: BackgroundTasks,
    tamanho: Annotated[int, Form()],
    nome: Annotated[str, Form()],
) -> SubidaDeBondsSaida:
    """Abre uma subida em partes para um export grande.

    POR QUE ESTE CAMINHO EXISTE. O ingress do Container Apps encerra a
    requisição por volta de 240 s, e isso NÃO é configurável. A banda de subida
    varia em mais de uma ordem de grandeza na mesma hora, e o export de bonds é
    CUMULATIVO: cresce toda semana. Hoje ele passa numa requisição; sem este
    caminho, é questão de tempo até a tela devolver 403 sem explicação — que foi
    o que aconteceu com a planilha do Score. Mesma razão e mesma solução: ver
    `api/score.comecar_subida_em_partes`.

    NÃO SUBSTITUI A SUBIDA DE UMA VEZ. Arquivo pequeno não paga várias idas, e
    ambiente sem armazenamento não tem onde montar: ali esta rota devolve
    `subida_id` nulo e a tela usa o de sempre.
    """
    aberta = planilha_de_bonds.comecar(
        sessao, usuario_id=usuario.id, nome=nome, tamanho=tamanho
    )
    tarefas.add_task(planilha_do_score.apagar_byte, aberta.caminho_substituido)
    return SubidaDeBondsSaida(
        subida_id=aberta.id, tamanho_da_parte=subida_em_partes.TAMANHO_DA_PARTE
    )


@rotas.put(
    "/bonds/upload/{subida_id}/parte/{indice}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def subir_parte_dos_bonds(
    sessao: Sessao,
    usuario: Annotated[UsuarioLogado, Depends(exigir_escrita)],
    subida_id: UUID,
    indice: int,
    parte: Annotated[UploadFile, File()],
) -> None:
    """Recebe uma parte. Não publica nada.

    `PUT` E NÃO `POST` porque a operação é idempotente por índice: reenviar a
    parte 3 substitui a parte 3, e é isso que permite ao cliente repetir a que
    falhou sem recomeçar a subida.

    A PARTE NÃO EXISTE PARA NINGUÉM até a montagem — são blocos não commitados
    no armazenamento. Uma subida abandonada não deixa arquivo pela metade para
    alguém ler, e o serviço descarta os blocos em sete dias.

    E A SUBIDA TEM DONO: `receber_parte` consulta a linha por (id, dono, ainda
    subindo) antes de escrever. Sem isso, conhecer o uuid de outra pessoa
    bastaria para mandar parte na subida dela.
    """
    planilha_de_bonds.receber_parte(
        sessao,
        subida_id=subida_id,
        usuario_id=usuario.id,
        indice=indice,
        dados=parte.file.read(),
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

    RECEBE O ARQUIVO DE NOVO, e é o caminho do arquivo PEQUENO. Para o grande
    existe `/bonds/upload/{subida_id}/importar`, que lê o que a conferência já
    montou em vez de pedir os bytes outra vez — ver aquela rota.

    SUBIR O MESMO ARQUIVO DUAS VEZES É INOFENSIVO, e isso é propriedade da chave
    composta, não gentileza desta rota: a segunda subida atualiza as mesmas
    linhas com os mesmos valores. É o que torna a rotina semanal segura mesmo
    quando alguém não lembra se já subiu.
    """
    resultado = ingerir_bonds.gravar(sessao, arquivo.file.read())
    sessao.commit()
    return ImportacaoDeBondsSaida(**vars(resultado))


@rotas.post("/bonds/upload/{subida_id}/conferencia")
def conferir_bonds_em_partes(
    sessao: Sessao,
    usuario: Annotated[UsuarioLogado, Depends(exigir_escrita)],
    subida_id: UUID,
    partes: Annotated[int, Form()],
) -> ConferenciaDeBondsSaida:
    """Junta as partes e confere o arquivo montado. NÃO grava cotação nenhuma.

    MONTA E LÊ DE VOLTA DO ARMAZENAMENTO, e não confere o que o servidor pensa
    ter montado: é a leitura do que ficou gravado que garante que a prévia
    mostrada é a do arquivo que a importação vai usar.

    A SUBIDA FICA MARCADA COMO COMPLETA com o tamanho REAL. O declarado era
    afirmação do cliente e serviu para dimensionar os tetos das partes.
    """
    subida, bytes_da_planilha = planilha_de_bonds.montar(
        sessao, subida_id=subida_id, usuario_id=usuario.id, partes=partes
    )
    conferencia = ingerir_bonds.conferir(sessao, bytes_da_planilha)
    planilha_de_bonds.concluir(subida, tamanho=len(bytes_da_planilha))
    return ConferenciaDeBondsSaida(**vars(conferencia))


@rotas.post("/bonds/upload/{subida_id}/importar")
def importar_bonds_em_partes(
    sessao: Sessao,
    usuario: Annotated[UsuarioLogado, Depends(exigir_escrita)],
    tarefas: BackgroundTasks,
    subida_id: UUID,
) -> ImportacaoDeBondsSaida:
    """Grava as cotações do arquivo que a conferência já montou.

    SEM REENVIAR OS BYTES, que é o ponto de toda a subida em partes: o arquivo
    já está no armazenamento e esta rota o lê de lá. Mandá-lo de novo faria o
    export INTEIRO passar duas vezes pelo ingress — uma para conferir e outra
    para importar —, e cada passagem teria de caber nos 240 s.

    RELÊ E RECONFERE: a importação não confia no que a conferência calculou. Ela
    lê a planilha de novo e compara com o cadastro do instante em que roda, que
    é o que torna seguro haver minutos entre uma tela e outra.

    O BYTE SAI DEPOIS DE GRAVADO, e numa tarefa de fundo: apagar é ida à rede e
    não pertence à transação. Se a tarefa não rodar, sobra um byte sem linha —
    que é o lado barato de errar.
    """
    subida, bytes_da_planilha = planilha_de_bonds.recuperar(
        sessao, subida_id=subida_id, usuario_id=usuario.id
    )
    resultado = ingerir_bonds.gravar(sessao, bytes_da_planilha)
    caminho = planilha_de_bonds.descartar(
        sessao, subida_id=subida_id, usuario_id=usuario.id
    )
    sessao.commit()
    tarefas.add_task(planilha_do_score.apagar_byte, caminho)
    return ImportacaoDeBondsSaida(**vars(resultado))
