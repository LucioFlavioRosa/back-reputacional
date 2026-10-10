"""O rastreio de risco: a aba que lê a plataforma pela matriz de risco da Aegea.

O QUE ESTA ABA RESPONDE, e por que ela pôde existir agora: `tema_risco` liga o
tema (N3) do cadastro aos 32 riscos da matriz corporativa, e o vínculo de
`mencao.tema_id` — que até semanas atrás era nulo em 100% da base — fez TUDO o
que entra na plataforma por assunto chegar a risco. Medido em 10/10/2026: 25.248
menções da Clipei, 2.322 da Bites, 319 do recorte de investidores e 401 agendas
do CRM chegam a um risco.

DUAS ROTAS, e a divisão é a da tela: uma devolve o painel inteiro (a série do
índice, os KPIs e a matriz de 32 riscos, que a pessoa clica para filtrar), e a
outra, o "Relatório de incidentes" — paginado, porque são milhares de linhas.

O PORTAL É O DO SCORE, como nas outras rotas daqui. O índice do Score já lê o
clima das interações institucionais (ver `exigir_portal_score`), então contar
agenda de clima negativo como incidente não abre nada novo.

E A PAUTA DA REUNIÃO NÃO ENTRA NA RESPOSTA, por decisão do dono do produto, e a
razão de fundo é a que sustenta a aba inteira: ESTA TELA EXISTE PARA CRUZAR
FONTES, e só cruza o que é padronizado. Assunto e clima vêm do cadastro — mesmo
vocabulário no CRM, na Clipei, na Bites e na Approach. A pauta é texto livre que
só o CRM tem: ela não cruza com nada, e uma coluna que só uma das cinco fontes
preenche faz o relatório parecer quebrado nas outras quatro.

Somam-se as outras duas razões que ele deu: a informação "já deveria estar em
tema da reunião e clima", e a pauta é texto descritivo mais longo — num relatório
de sete colunas, um parágrafo por linha arrebenta a grade. Ela também já aparece
em todo lugar que trata da agenda, então repeti-la aqui é ruído.

A LINHA DA AGENDA DIZ data, assunto, severidade, recorrência e riscos: o
bastante para ler "houve reunião tensa sobre Tarifa social, que toca o R23". O
detalhe tem lugar próprio, que é a agenda no CRM.

E ISSO FECHA UMA PERGUNTA DE ACESSO antes de ela existir: sem texto do CRM na
resposta, não há conteúdo do CRM nesta aba, e o portal do Score basta.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencias import UsuarioDoScore
from app.banco.repositorio_riscos import (
    DIMENSOES,
    FiltroDeRisco,
    arvore_dos_temas,
    dimensoes_do_recorte,
    incidentes_de_risco,
    lentes_das_fontes,
    matriz_de_risco,
    serie_do_indice,
    total_por_severidade,
)
from app.banco.sessao import SessaoDoPedido
from app.dominio.erros import RegraViolada
from app.dominio.riscos import (
    FAIXAS_DO_INDICE,
    SEVERIDADES,
    faixa_do_indice,
    variacao,
)

rotas = APIRouter(prefix="/api/score/riscos", tags=["score"])

#: O TETO DA PÁGINA do relatório. O mesmo da Base de dados: o que passa disso é
#: exportação, não leitura de tela.
TAMANHO_MAXIMO = 500


class MesDoIndice(BaseModel):
    mes: str
    indice: int | None
    incidentes: int
    #: A soma pelos pesos de severidade — o número cru do qual o índice é a
    #: redução à escala. Vai na resposta para o número poder ser conferido.
    pesado: int
    #: QUANTOS INCIDENTES DE CADA SEVERIDADE. A barra do mês é empilhada por
    #: severidade e a dica do mês mostra os três números; do total não se deriva
    #: a divisão. Só as severidades que o mês teve.
    por_severidade: dict[str, int]
    #: OS MESMOS GRUPOS, JÁ PELO PESO: é com isto que a barra se empilha, porque
    #: a altura dela é o índice ponderado. Ver `MesDeRisco`.
    pesado_por_severidade: dict[str, int]
    faixa: str | None
    #: Dentro da janela escolhida? A série vem inteira e a tela esmaece o resto.
    na_janela: bool
    #: Quais fontes alimentaram este mês. Enquanto a base está incompleta, é o
    #: que impede o gráfico de comparar mês de uma fonte com mês de quatro.
    fontes: list[str]


class KpiDoRisco(BaseModel):
    valor: int | None
    #: O mês a que o valor se refere, `AAAA-MM`.
    mes: str | None


class RiscoDaMatriz(BaseModel):
    codigo: str
    nome: str
    severidade: str
    cluster: str
    cluster_nome: str
    incidentes: int
    #: Separados porque uma notícia e uma reunião não se leem do mesmo jeito.
    mencoes: int
    agendas: int


class PainelDeRisco(BaseModel):
    serie: list[MesDoIndice]
    #: O que vale 100 pontos: o maior `pesado` da série, e o mês dele. Sem isto,
    #: "índice 32" é número sem unidade.
    referencia: int
    mes_do_pico: str | None
    #: Os três KPIs do topo da tela.
    pico_do_periodo: KpiDoRisco
    indice_atual: KpiDoRisco
    #: A variação contra o mês anterior. A série é MENSAL: o protótipo chama de
    #: "30 dias", e a tela diz o mês comparado em vez de prometer trinta dias
    #: que a granularidade não tem.
    variacao_no_mes: KpiDoRisco
    matriz: list[RiscoDaMatriz]
    #: Quantos incidentes por severidade, na janela — o "Total de incidentes" do
    #: protótipo, que mostra três números.
    total_por_severidade: dict[str, int]
    #: Os limites inferiores das faixas, para a tela desenhar as zonas de fundo
    #: sem recalcular a convenção.
    faixas: dict[str, int]


class IncidenteNaTabela(BaseModel):
    tipo: str
    id: str
    data: date
    quem: str | None
    #: O título da matéria. Nulo na agenda — ver o cabeçalho do módulo.
    incidente: str | None
    link: str | None
    fonte: str
    #: A LENTE da fonte — a dimensão padronizada do Score.
    lente: str
    tema: str
    tier: str | None
    engajamento: float | None
    severidade: str
    recorrencia: int
    riscos: list[dict[str, str]]


class PaginaDeIncidentes(BaseModel):
    itens: list[IncidenteNaTabela]
    total: int
    pagina: int
    tamanho: int


class DimensaoDoFiltro(BaseModel):
    """Uma dimensão que o recorte atual TEM, para a tela oferecer."""

    chave: str
    rotulo: str
    #: `lista` quando os valores cabem num seletor; `busca` quando são muitos;
    #: `vazia` quando a fonte classifica o campo e este recorte não trouxe valor.
    #: A DIMENSÃO VAZIA CONTINUA NA RESPOSTA, como a aba vazia das Lentes: um
    #: filtro que aparece e desaparece a cada clique se lê como tela quebrada.
    tipo: str
    valores: list[str]
    quantos: int
    #: EM QUAIS FONTES ela tem valor. É o que permite a tela dizer "só na
    #: imprensa" em vez de deixar o filtro mudo nas outras — e é a resposta à
    #: pergunta que o dono do produto fez: padronização, com espaço para a
    #: particularidade de cada base.
    fontes: list[str]
    #: QUANTAS MENÇÕES DO RECORTE têm valor aqui. Zero com `fontes` preenchido é
    #: "a fonte classifica isto, e neste corte não há nenhum" — que a tela
    #: escreve no filtro desabilitado, em vez de omitir o filtro.
    preenchidas: int


class ClusterDeRisco(BaseModel):
    codigo: str
    nome: str
    riscos: list[dict[str, str]]


class NivelDoTemaNoFiltro(BaseModel):
    """Um nó da taxonomia de temas, com o que vem abaixo dele.

    TRÊS NÍVEIS — bloco (N1), macro tema (N2), tema (N3) —, que é como o
    cadastro guarda e como a planilha da Bites manda. É o caminho natural do
    aprofundamento: escolher N1 reduz a lista de N2, e escolher N2 reduz a de N3.
    """

    codigo: str
    nome: str
    dentro: list[NivelDoTemaNoFiltro] = []
    #: QUANTOS INCIDENTES no recorte atual, sem contar o próprio recorte de
    #: tema: é o que mostra onde está a massa antes de descer. Ver `NivelDoTema`.
    incidentes: int = 0


class OpcoesDoRisco(BaseModel):
    """O que a tela pode oferecer: o cadastro, as fontes e as dimensões.

    O CADASTRO É FIXO (8 clusters, 32 riscos) e as DIMENSÕES VARIAM com o
    recorte — praça e concessionária cruzam as fontes, tier e público-alvo só a
    imprensa tem, cargo e autor só as redes. Medido na base: oferecer tier a
    quem está olhando a Bites seria prometer um filtro que volta vazio.
    """

    clusters: list[ClusterDeRisco]
    #: AS LENTES COM INCIDENTE no recorte — a dimensão padronizada, e o filtro
    #: que o dono do produto pediu. Vêm ao lado das fontes porque as duas
    #: perguntas são diferentes: "como está a imprensa" é lente, "esta planilha
    #: está certa" é fonte.
    lentes: list[dict[str, str]]
    #: A TAXONOMIA EM TRÊS NÍVEIS, só dos temas que tocam risco. A árvore inteira
    #: do cadastro, e não só o que tem incidente: é a régua da matriz dos 32
    #: riscos, que mostra os sem incidente — e um seletor que muda de tamanho a
    #: cada clique não deixa procurar.
    temas: list[NivelDoTemaNoFiltro]
    #: As fontes que TÊM incidente no recorte, com o rótulo que a tela mostra.
    fontes: list[dict[str, str]]
    dimensoes: list[DimensaoDoFiltro]
    #: Os meses com incidente, do mais antigo ao mais novo — a janela de análise
    #: só pode oferecer o que existe.
    meses: list[str]


#: AS CHAVES DE DIMENSÃO que a rota aceita, derivadas do repositório.
#:
#: DERIVADAS, e não escritas aqui: a rota `/opcoes` oferece as dimensões a partir
#: de `DIMENSOES`, e uma segunda lista nesta ponta permitiria oferecer uma coisa
#: e aceitar outra.
CHAVES_DE_DIMENSAO = tuple(chave for chave, _rotulo, _coluna in DIMENSOES)


def _filtro(
    cluster: str | None,
    risco: str | None,
    fontes: list[str] | None,
    de: str | None,
    ate: str | None,
    busca: str | None,
    dimensao: list[str] | None = None,
    lentes: list[str] | None = None,
    severidade: str | None = None,
    bloco: str | None = None,
    macro: str | None = None,
    tema: str | None = None,
) -> FiltroDeRisco:
    """O recorte da tela, com os meses em `AAAA-MM` virando o primeiro dia.

    `dimensao` vem como `chave:valor` repetido — `?dimensao=tier:relevante`.
    UM PARÂMETRO REPETIDO, e não um por dimensão: as dimensões que existem saem
    do dado, e um parâmetro fixo por dimensão obrigaria a mexer na rota a cada
    uma nova.
    """

    def primeiro_dia(mes: str | None) -> date | None:
        if not mes:
            return None
        return date(int(mes[:4]), int(mes[5:7]), 1)

    pares: list[tuple[str, str]] = []
    for crua in dimensao or ():
        chave, _, valor = crua.partition(":")
        if chave not in CHAVES_DE_DIMENSAO:
            raise RegraViolada(
                f"Dimensão {chave!r} não existe. "
                f"Conhecidas: {', '.join(CHAVES_DE_DIMENSAO)}."
            )
        if not valor:
            raise RegraViolada(
                f"A dimensão {chave!r} veio sem valor. Use `{chave}:algum valor`."
            )
        pares.append((chave, valor))

    #: SEVERIDADE DESCONHECIDA É RECUSADA COM O NOME, como a dimensão: ela vem
    #: de um clique na fatia da barra ou no número do topo, e valor que não
    #: existe devolveria a tela vazia sem dizer por quê.
    if severidade and severidade not in SEVERIDADES:
        raise RegraViolada(
            f"Severidade {severidade!r} não existe. Conhecidas: {', '.join(SEVERIDADES)}."
        )

    return FiltroDeRisco(
        cluster=cluster,
        risco=risco,
        fontes=tuple(fontes or ()),
        lentes=tuple(lentes or ()),
        severidade=severidade or None,
        bloco=bloco or None,
        macro=macro or None,
        tema=tema or None,
        de=primeiro_dia(de),
        ate=primeiro_dia(ate),
        busca=busca,
        por_dimensao=tuple(pares),
    )


@rotas.get("", response_model=PainelDeRisco)
def painel_de_risco(
    sessao: SessaoDoPedido,
    usuario: UsuarioDoScore,
    cluster: Annotated[str | None, Query()] = None,
    risco: Annotated[str | None, Query()] = None,
    fonte: Annotated[list[str] | None, Query()] = None,
    de: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    ate: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    busca: Annotated[str | None, Query()] = None,
    dimensao: Annotated[list[str] | None, Query()] = None,
    lente: Annotated[list[str] | None, Query()] = None,
    severidade: Annotated[str | None, Query()] = None,
    #: OS TRÊS NÍVEIS DO CADASTRO DE TEMAS — N1, N2, N3. Ver `FiltroDeRisco`.
    bloco: Annotated[str | None, Query()] = None,
    macro: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
) -> PainelDeRisco:
    """A série do índice, os três KPIs e a matriz de 32 riscos."""
    filtro = _filtro(
        cluster, risco, fonte, de, ate, busca, dimensao, lente, severidade,
        bloco, macro, tema,
    )
    serie, referencia, mes_do_pico = serie_do_indice(sessao, filtro, usuario.escopo)
    matriz = matriz_de_risco(sessao, filtro, usuario.escopo)

    #: OS KPIs SAEM DA JANELA, e não da série inteira: o protótipo os chama de
    #: "Pico do período" e "Índice atual", e é o período escolhido que eles
    #: descrevem. A referência de 100 pontos, não — ela é da série.
    da_janela = [mes for mes in serie if mes.na_janela]
    pico = max(da_janela, key=lambda mes: mes.indice or 0, default=None)
    atual = da_janela[-1] if da_janela else None

    #: O TOTAL VEM DA CONTAGEM POR INCIDENTE, e não da soma da matriz: o
    #: incidente de um tema que toca um crítico e um alto entraria nos dois
    #: baldes, e os três números do topo somariam mais que o total. Achado de
    #: revisão.
    por_severidade = total_por_severidade(sessao, filtro, usuario.escopo)

    return PainelDeRisco(
        serie=[
            MesDoIndice(
                mes=mes.mes,
                indice=mes.indice,
                incidentes=mes.incidentes,
                pesado=mes.pesado,
            por_severidade=dict(mes.por_severidade),
            pesado_por_severidade=dict(mes.pesado_por_severidade),
                faixa=faixa_do_indice(mes.indice),
                na_janela=mes.na_janela,
                fontes=list(mes.fontes),
            )
            for mes in serie
        ],
        referencia=referencia,
        mes_do_pico=mes_do_pico,
        pico_do_periodo=KpiDoRisco(
            valor=pico.indice if pico else None, mes=pico.mes if pico else None
        ),
        indice_atual=KpiDoRisco(
            valor=atual.indice if atual else None, mes=atual.mes if atual else None
        ),
        variacao_no_mes=KpiDoRisco(
            valor=variacao(da_janela),
            mes=da_janela[-2].mes if len(da_janela) > 1 else None,
        ),
        matriz=[
            RiscoDaMatriz(
                codigo=linha.codigo,
                nome=linha.nome,
                severidade=linha.severidade,
                cluster=linha.cluster,
                cluster_nome=linha.cluster_nome,
                incidentes=linha.incidentes,
                mencoes=linha.mencoes,
                agendas=linha.agendas,
            )
            for linha in matriz
        ],
        total_por_severidade=por_severidade,
        faixas=dict(FAIXAS_DO_INDICE),
    )


@rotas.get("/incidentes", response_model=PaginaDeIncidentes)
def relatorio_de_incidentes(
    sessao: SessaoDoPedido,
    usuario: UsuarioDoScore,
    cluster: Annotated[str | None, Query()] = None,
    risco: Annotated[str | None, Query()] = None,
    fonte: Annotated[list[str] | None, Query()] = None,
    de: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    ate: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    busca: Annotated[str | None, Query()] = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=TAMANHO_MAXIMO)] = 50,
    dimensao: Annotated[list[str] | None, Query()] = None,
    lente: Annotated[list[str] | None, Query()] = None,
    severidade: Annotated[str | None, Query()] = None,
    #: OS TRÊS NÍVEIS DO CADASTRO DE TEMAS — N1, N2, N3. Ver `FiltroDeRisco`.
    bloco: Annotated[str | None, Query()] = None,
    macro: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
) -> PaginaDeIncidentes:
    """O "Relatório de incidentes": um incidente por linha, do mais recente.

    A JANELA VALE AQUI, ao contrário da série: a tabela é o detalhe do período
    escolhido, e trazer fora dele responderia outra pergunta.
    """
    filtro = _filtro(
        cluster, risco, fonte, de, ate, busca, dimensao, lente, severidade,
        bloco, macro, tema,
    )
    linhas, total = incidentes_de_risco(
        sessao, filtro, usuario.escopo, pagina=pagina, tamanho=tamanho
    )

    return PaginaDeIncidentes(
        itens=[
            IncidenteNaTabela(
                tipo=linha.tipo,
                id=linha.id,
                data=linha.data,
                quem=linha.quem,
                incidente=linha.incidente,
                link=linha.link,
                fonte=linha.fonte,
                lente=linha.lente,
                tema=linha.tema,
                tier=linha.tier,
                engajamento=linha.engajamento,
                severidade=linha.severidade,
                recorrencia=linha.recorrencia,
                riscos=[{"codigo": codigo, "nome": nome} for codigo, nome in linha.riscos],
            )
            for linha in linhas
        ],
        total=total,
        pagina=pagina,
        tamanho=tamanho,
    )


@rotas.get("/opcoes", response_model=OpcoesDoRisco)
def opcoes_do_risco(
    sessao: SessaoDoPedido,
    usuario: UsuarioDoScore,
    cluster: Annotated[str | None, Query()] = None,
    risco: Annotated[str | None, Query()] = None,
    fonte: Annotated[list[str] | None, Query()] = None,
    de: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    ate: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    busca: Annotated[str | None, Query()] = None,
    dimensao: Annotated[list[str] | None, Query()] = None,
    lente: Annotated[list[str] | None, Query()] = None,
    severidade: Annotated[str | None, Query()] = None,
    #: OS TRÊS NÍVEIS DO CADASTRO DE TEMAS — N1, N2, N3. Ver `FiltroDeRisco`.
    bloco: Annotated[str | None, Query()] = None,
    macro: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
) -> OpcoesDoRisco:
    """O que a tela pode oferecer como filtro, dado o recorte de agora.

    RECEBE O RECORTE de propósito: as dimensões disponíveis dependem dele. Quem
    escolhe "só a Bites" perde o filtro de tier (ela não manda tier) e ganha o
    de cargo (ela manda em 100% das linhas) — é o dado respondendo, não uma
    lista fixa por fonte.
    """
    from app.banco.tabelas_catalogo import Risco, RiskCluster
    from app.banco.tabelas_score import ScoreFonte

    filtro = _filtro(
        cluster, risco, fonte, de, ate, busca, dimensao, lente, severidade,
        bloco, macro, tema,
    )

    do_cadastro = sessao.execute(
        select(RiskCluster, Risco)
        .join(Risco, Risco.risk_cluster_id == RiskCluster.id)
        .where(RiskCluster.ativo.is_(True), Risco.ativo.is_(True))
        .order_by(RiskCluster.ordem, Risco.ordem)
    )
    clusters: dict[str, ClusterDeRisco] = {}
    for agrupador, um_risco in do_cadastro:
        atual = clusters.setdefault(
            agrupador.codigo,
            ClusterDeRisco(codigo=agrupador.codigo, nome=agrupador.nome, riscos=[]),
        )
        atual.riscos.append(
            {"codigo": um_risco.codigo, "nome": um_risco.nome, "severidade": um_risco.severidade}
        )

    #: AS FONTES COM INCIDENTE, e não o cadastro inteiro: fonte sem incidente no
    #: recorte é filtro que volta vazio.
    serie, _referencia, _pico = serie_do_indice(sessao, filtro, usuario.escopo)
    com_incidente = {codigo for mes in serie for codigo in mes.fontes}
    rotulos = dict(sessao.execute(select(ScoreFonte.codigo, ScoreFonte.nome)).all())

    #: AS LENTES SAEM DAS FONTES COM INCIDENTE, e não de uma segunda consulta: a
    #: lente de uma fonte é cadastro, e a fonte com incidente já está calculada.
    das_fontes = lentes_das_fontes(sessao)
    com_lente: dict[str, str] = {}
    for codigo in com_incidente:
        achada = das_fontes.get(codigo)
        if achada:
            com_lente[achada[0]] = achada[1]

    return OpcoesDoRisco(
        clusters=list(clusters.values()),
        temas=[
            NivelDoTemaNoFiltro(
                codigo=bloco.codigo,
                nome=bloco.nome,
                incidentes=bloco.incidentes,
                dentro=[
                    NivelDoTemaNoFiltro(
                        codigo=macro.codigo,
                        nome=macro.nome,
                        incidentes=macro.incidentes,
                        dentro=[
                            NivelDoTemaNoFiltro(
                                codigo=um.codigo,
                                nome=um.nome,
                                incidentes=um.incidentes,
                            )
                            for um in macro.dentro
                        ],
                    )
                    for macro in bloco.dentro
                ],
            )
            for bloco in arvore_dos_temas(sessao, filtro, usuario.escopo)
        ],
        lentes=[
            {"codigo": codigo, "nome": nome} for codigo, nome in sorted(com_lente.items())
        ],
        fontes=[
            {"codigo": codigo, "nome": rotulos.get(codigo, codigo)}
            for codigo in sorted(com_incidente)
        ],
        dimensoes=[
            DimensaoDoFiltro(
                chave=achada.chave,
                rotulo=achada.rotulo,
                tipo=achada.tipo,
                valores=list(achada.valores),
                quantos=achada.quantos,
                fontes=list(achada.fontes),
                preenchidas=achada.preenchidas,
            )
            for achada in dimensoes_do_recorte(
                sessao,
                filtro,
                usuario.escopo,
                #: O AUTOR NOMEIA PESSOA: só quem vê o diretório o lista.
                ve_o_diretorio=bool(usuario.papel and usuario.papel.ve_diretorio),
                #: AS FONTES JÁ CONTADAS AQUI, para a consulta não as procurar de
                #: novo — e são elas que dizem quais campos existem no recorte.
                fontes_do_recorte=com_incidente,
            )
        ],
        meses=[mes.mes for mes in serie],
    )
