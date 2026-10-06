"""O dossiê de uma lente, pronto para a tela.

UM ENDPOINT, UMA TELA. A regra 2 do pacote: o front não calcula. Ele recebe a
nota, os KPIs, a série, os dois painéis e as frases já montados — e só decide
cor, ordem e tamanho.

NENHUM TEXTO ANALÍTICO É SALVO. Manchete, títulos de gráfico e a lista de
sinais saem de detectores sobre os próprios dados, a cada leitura: mudar um
dado muda a frase. Guardá-los faria a tela afirmar em setembro o que era
verdade em junho.

CADA BLOCO VIAJA COM A SUA FICHA. `Ficha` diz de onde o número veio (planilha,
CRM, cadastro, relatório transcrito), que colunas o alimentam, o que FALTA hoje
e se o conteúdo é exemplo. É o conteúdo do "?" que abre em cima de cada
gráfico.

Isso não é documentação: é parte do dado. Metade do que esta tela mostra não
sai das planilhas — a matriz de jornalistas, a trajetória de rating, o estudo
de percepção e quantas mensagens foram respondidas vêm do relatório do cliente,
transcritos. Apresentá-los com a mesma cara de uma contagem medida é o jeito
mais barato de destruir a confiança num painel: basta o leitor descobrir
sozinho, uma vez.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.dependencias import UsuarioLogado, exigir_portal_score
from app.api.score import _formula, _mes_de
from app.banco import repositorio_lentes, repositorio_score
from app.banco.sessao import SessaoDoPedido

#: A coluna em si, para pedir a contagem de um valor específico ao
#: repositório — ver `quantas_com`.
from app.banco.tabelas_score import Mencao
from app.casos_de_uso.ler_sinais_da_lente import ler_sinais, regua_dos_sinais
from app.dominio import frases_de_sinais as frases
from app.dominio.causa_da_lente import DIMENSOES_POR_LENTE, ROTULO_DA_DIMENSAO
from app.dominio.erros import NaoEncontrado
from app.dominio.lentes import (
    Conceito,
    Ficha,
    Procedencia,
    TaxaDeResposta,
    prioridade_do_jornalista,
)
from app.dominio.score import Calibracao, FiltroDeMencoes
from app.dominio.sinais_da_lente import Secao

rotas = APIRouter(
    prefix="/api/score/lentes",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido

#: Quantos meses a evolução mostra. Fixos, e não "os que têm dado": o buraco
#: faz parte da leitura — ver `repositorio_lentes.meses_ate`.
MESES_DA_EVOLUCAO = 8


# -- o que a tela recebe --------------------------------------------------------


class ConceitoSaida(BaseModel):
    termo: str
    texto: str


class FichaSaida(BaseModel):
    """A procedência de um bloco — o conteúdo do "?"."""

    origem: str
    fonte: str
    colunas: list[str] = Field(default_factory=list)
    #: O que este bloco NÃO tem hoje, dito onde a pessoa está olhando.
    lacunas: list[str] = Field(default_factory=list)
    exemplo: bool = False
    conceitos: list[ConceitoSaida] = Field(default_factory=list)


class ColunaSaida(BaseModel):
    """Uma coluna de uma tabela do dossiê.

    VEM DO SERVIDOR porque é ele que sabe o que a tabela mostra. A primeira
    versão montava as colunas na tela OLHANDO O TÍTULO do bloco — e o título
    passou a ser a frase de um detector, que muda com o dado: o schema da
    tabela trocaria sozinho no mês em que a leitura mudasse.
    """

    chave: str
    titulo: str
    alinhamento: str = "esquerda"


class BlocoSaida(BaseModel):
    """Um gráfico ou quadro, com o tipo que a tela deve desenhar."""

    tipo: str
    #: Distingue duas tabelas que se desenham igual e se leem diferente:
    #: `rating` destaca rebaixamento, `teor` destaca reclamação acima de
    #: metade. A regra de destaque é de leitura e mora na tela; QUAL regra
    #: aplicar é do servidor.
    subtipo: str | None = None
    titulo: str
    #: A frase que o gráfico prova, escrita pelos detectores a cada leitura.
    conclusao: str | None = None
    dados: list[dict] = Field(default_factory=list)
    #: Como se chamam as três faixas NESTE bloco. A lente institucional mede
    #: clima (propositivo/neutro/tenso) e as outras medem sentimento — e a tela
    #: não pode descobrir isso adivinhando pelo título.
    legenda: list[str] = Field(default_factory=list)
    #: A cor de cada faixa de `legenda`, na mesma ordem — só a lente
    #: institucional manda isto hoje, com `clima.cor_hex` (a mesma cor do
    #: Painel). Vazio quando ausente: a tela cai nos tons genéricos de
    #: positivo/neutro/negativo do próprio design system.
    cores: list[str] = Field(default_factory=list)
    #: Só nas tabelas.
    colunas: list[ColunaSaida] = Field(default_factory=list)
    #: A coluna cujo valor é o ENDEREÇO DA LINHA — a tela a usa como destino de
    #: um clique na linha, e NÃO desenha a coluna.
    #:
    #: O DONO DO PRODUTO PEDIU A LINHA, E NÃO O LINK: "não precisa ter o link no
    #: modal, mas se clicar gostaria de acessar a página". Uma coluna "Link" com
    #: "Abrir ↗" repetido trinta vezes é ruído, e rouba largura do texto da
    #: menção — que é o que se lê.
    #:
    #: VEM DO SERVIDOR pelo mesmo motivo de `recorta`: a alternativa é a tela
    #: procurar uma coluna chamada "link", que é adivinhação pelo nome — o jeito
    #: exato como a escolha do schema da tabela já quebrou uma vez (ver
    #: `ColunaSaida`).
    coluna_do_link: str | None = None
    #: A dimensão do recorte que um clique neste painel aplica — a chave do
    #: parâmetro da rota (`tema`, `empresa`, `perfil_autor`). Nula no bloco que
    #: não recorta nada (a evolução, as tabelas).
    #:
    #: VEM DO SERVIDOR porque a alternativa é a tela adivinhar a dimensão pelo
    #: TÍTULO do painel — e o título é a frase de um detector, que muda com o
    #: dado. Ver `RECORTE_DO_PAINEL`, e o comentário de `ColunaSaida`, que conta
    #: como esse mesmo atalho já quebrou uma vez.
    recorta: str | None = None
    ficha: FichaSaida


class SinalSaida(BaseModel):
    """Uma linha do bloco "Sinais do período"."""

    tipo: str
    frase: str
    #: O número que a frase prova, em destaque ao lado dela.
    evidencia: str
    #: Em que gráfico conferir — "Evolução", o nome de um painel, ou "Lente".
    #: É O QUE LIGA A FRASE À PROVA: sem isso a lista vira cinco afirmações
    #: soltas, e quem duvida de uma não sabe onde olhar.
    onde: str
    tom: str


class KpiSaida(BaseModel):
    rotulo: str
    valor: str
    detalhe: str | None = None


class FatoSaida(BaseModel):
    mes: str
    texto: str
    efeito: str


class DossieSaida(BaseModel):
    codigo: str
    nome: str
    stakeholder: str
    mes: str

    #: A nota da lente e a variação — vêm do índice, sem recálculo.
    nota: int | None
    ns: float | None
    delta: int | None
    #: `mes_anterior` (o normal) ou `sem_filtro` — com um recorte ativo, "vs.
    #: mês anterior" compararia maçã com laranja (o mês passado não tem o
    #: mesmo filtro), então o delta vira "nota filtrada vs. nota do mês
    #: inteiro", e o front troca a legenda.
    delta_versus: str = "mes_anterior"
    #: Verdadeiro quando `tier`/`veiculo`/`atributo`/`tema` veio preenchido na
    #: chamada. A tela usa isto para o selo "recorte filtrado" — esta nota NÃO
    #: é a nota oficial do mês, é só o que esse recorte mostraria.
    recorte_filtrado: bool = False
    peso: int
    estimado: bool
    ausencia: str | None
    fontes: list[str] = Field(default_factory=list)
    formula: str

    #: QUATRO, sempre — é a estrutura fixa da §1, e não uma convenção. Um
    #: quinto KPI quebraria a grade, e três deixariam um buraco onde a pessoa
    #: procura o número que ela sempre olha.
    kpis: list[KpiSaida] = Field(min_length=4, max_length=4)
    #: A nota, a variação e os KPIs saem daqui.
    ficha_do_destaque: FichaSaida
    #: A frase que abre a lente. CALCULADA dos dados a cada leitura, nunca
    #: salva: texto guardado envelhece em silêncio numa tela que a diretoria lê
    #: como se fosse deste mês.
    manchete: str | None = None
    evolucao: BlocoSaida
    #: O quadro ao lado da evolução — até três sinais da série, mais as lacunas.
    sinais_da_evolucao: list[str] = Field(default_factory=list)
    #: A rosca de volume por tier, ao lado do Top 5 veículos — ver
    #: `_volume_por_tier`/`_veiculos`. Vazios na Institucional.
    volume_por_tier: BlocoSaida
    top_veiculos: BlocoSaida
    #: O placar de clima por veículo — ver `_veiculos`. Vazio na Institucional.
    clima_por_veiculos: BlocoSaida
    #: O que está puxando a lente pra cima ou pra baixo, por atributo
    #: reputacional — ver `_drivers_e_riscos`. Vazio na Institucional.
    drivers_e_riscos: BlocoSaida
    #: Os temas (Subcategoria da Clipei) mais falados do mês — ver
    #: `_temas_mais_falados`. Vazio na Institucional.
    temas_mais_falados: BlocoSaida
    #: O drill-down até a linha: as matérias mais recentes por trás da nota —
    #: ver `_materias_recentes`. Vazio na Institucional (não vem de clipping).
    materias_recentes: BlocoSaida
    fatos: list[FatoSaida] = Field(default_factory=list)
    #: DOIS para quem alcança a lente inteira — e UM para quem não alcança o
    #: diretório. O piso desceu de 2 para 1 porque o painel que NOMEIA gente de
    #: fora (a matriz de jornalistas; os órgãos do CRM) sai do payload de quem
    #: não tem `ve_diretorio`, e o que sobra continua sendo a lente: o quadro
    #: agregado, a nota, a evolução e os KPIs.
    #:
    #: O TETO CONTINUA EM DOIS: a especificação dá dois painéis por lente, e um
    #: terceiro seria mudança de tela, não de permissão.
    paineis: list[BlocoSaida] = Field(min_length=1, max_length=2)
    #: As abas de "onde está a causa" — o mesmo mês cortado por cada dimensão
    #: que o explica, na ordem em que a lente se explica. Ver
    #: `_onde_esta_a_causa`.
    #:
    #: FORA DE `paineis` DE PROPÓSITO: aquele campo tem teto de dois porque a
    #: especificação dá dois painéis por lente, e um terceiro seria mudança de
    #: tela. Isto não é um terceiro painel — é um cartão só, com abas, e as abas
    #: não cabem num contrato que a tela lê como "painel A" e "painel B".
    #:
    #: VAZIO na lente que não vem de menção (Mercado, Institucional) e no mês
    #: em que nenhuma dimensão explica nada.
    onde_esta_a_causa: list[BlocoSaida] = Field(default_factory=list)
    #: O bloco do fim da tela: o que mudou no período, por intensidade, com as
    #: lacunas de dado no fim.
    sinais: list[SinalSaida] = Field(default_factory=list)


# -- as fichas que se repetem ---------------------------------------------------

CONCEITO_NS = Conceito(
    termo="NS (saldo de sentimento)",
    texto=(
        "(positivas − negativas) ÷ total. Vai de −1 a 1 e vira nota de 0 a 100 "
        "por (NS + 1) ÷ 2 × 100. Total zero é sem dado, e não zero."
    ),
)
CONCEITO_TIER = Conceito(
    termo="Tier do veículo",
    texto=(
        "A relevância do veículo na escala da própria clipagem: Tier 1 "
        "(imprensa nacional e econômica), Tier 2 (regionais com influência) "
        "e Tier 3 (locais e blogs de nicho)."
    ),
)
CONCEITO_ACIONAVEL = Conceito(
    termo="Mensagem acionável",
    texto=(
        "Contato de verdade, e não marcação de post nem mensagem etiquetada "
        "como não pertinente. As não acionáveis continuam contadas — o que "
        "muda é o denominador da taxa de resposta."
    ),
)

FICHA_DO_DESTAQUE = Ficha(
    origem=Procedencia.CALCULO,
    fonte="Derivado das fontes da lente pela régua em vigor",
    conceitos=(
        Conceito(
            termo="Nota da lente",
            texto=(
                "O saldo de sentimento das fontes ligadas, na escala de 0 a "
                "100. Com mais de uma fonte, as menções das duas entram na "
                "mesma conta: um denominador só, para a soma dos recortes "
                "fechar com a nota."
            ),
        ),
        Conceito(
            termo="Variação",
            texto="Contra o mesmo cálculo no mês anterior. Nula sem os dois meses.",
        ),
    ),
)

LACUNA_AUTOR = (
    "A clipagem não informa quem assina a matéria. Sem essa coluna a exposição "
    "de cada jornalista não pode ser calculada pelo volume, e a matriz inteira "
    "é preenchida à mão."
)
LACUNA_RESPOSTA = (
    "O fornecedor não informa se a mensagem foi respondida. Os números de "
    "respondidas vêm do relatório mensal, transcritos."
)
COLUNAS_DAS_MATERIAS = [
    ColunaSaida(chave="quando", titulo="Quando"),
    ColunaSaida(chave="veiculo", titulo="Veículo"),
    ColunaSaida(chave="sentimento", titulo="Classificação"),
    ColunaSaida(chave="tier", titulo="Tier"),
    ColunaSaida(chave="atributo", titulo="Atributo"),
    ColunaSaida(chave="tema", titulo="Tema"),
]

#: As colunas da MENÇÃO DE REDE, que não são as da matéria de jornal.
#:
#: O MOTIVO DA RESTRIÇÃO DO JONES (02/10/2026) ERA ESTE: a tabela de matérias
#: existia só na Imprensa porque "Veículo" e "Aegea Tier" não dizem nada de um
#: post — e mostrar colunas vazias é pior que não mostrar tabela. A Sociedade
#: passa a ter a lista porque a carga do padrão trouxe o que ela precisa (o
#: texto, o link, quem escreveu e o engajamento), com as colunas dela.
#:
#: O TEXTO VEM PRIMEIRO porque é o que se lê; o resto é o que localiza a menção.
COLUNAS_DAS_MENCOES = [
    ColunaSaida(chave="texto", titulo="Menção"),
    ColunaSaida(chave="quando", titulo="Quando"),
    ColunaSaida(chave="veiculo", titulo="Rede"),
    ColunaSaida(chave="sentimento", titulo="Classificação"),
    ColunaSaida(chave="autor", titulo="Quem falou"),
    ColunaSaida(chave="perfil", titulo="Perfil"),
    ColunaSaida(chave="engajamento", titulo="Engajamento"),
]


def _ficha_da_base(fonte: str, colunas: tuple[str, ...], conceitos=()) -> Ficha:
    return Ficha(
        origem=Procedencia.PLANILHA,
        fonte=fonte,
        colunas=colunas,
        conceitos=tuple(conceitos),
    )


def _saida_da_ficha(ficha: Ficha) -> FichaSaida:
    return FichaSaida(
        origem=str(ficha.origem),
        fonte=ficha.fonte,
        colunas=list(ficha.colunas),
        lacunas=list(ficha.lacunas),
        exemplo=ficha.exemplo,
        conceitos=[ConceitoSaida(termo=c.termo, texto=c.texto) for c in ficha.conceitos],
    )


SENTIMENTO = ["Positivo", "Neutro", "Negativo"]

#: MESMO VALOR DE `clima.cor_hex` (Turquesa Rio, Cinza 2, Vermelho Pitanga da
#: paleta da Aegea) — sentimento de mídia e clima institucional são a mesma
#: pergunta (positivo/neutro/negativo) por fontes diferentes, e não há por
#: que a mesma resposta ter duas cores. Fixo, e não lido de dicionário: ao
#: contrário de `clima`, não existe uma tabela `sentimento` para ler.
CORES_DO_SENTIMENTO = ["#17E3CB", "#8C91A4", "#FF5C60"]

#: A ORDEM pos/neu/neg dos códigos — e só a ordem. `codigo` nunca muda (ver
#: `SENTIMENTO_DO_CLIMA`); NOME e COR vêm sempre do dicionário a cada leitura,
#: por `_legenda_e_cores_do_clima`, para não repetir o defeito que fez este
#: bloco continuar dizendo "Propositivo"/"Tenso" duas renomeações depois.
CODIGOS_DO_CLIMA = ("propositivo", "neutro", "tenso")


def _legenda_e_cores_do_clima(sessao) -> tuple[list[str], list[str]]:
    """Nome e cor de cada faixa pos/neu/neg, direto do dicionário de clima."""
    dicionario = repositorio_lentes.climas_por_codigo(sessao)
    climas = [dicionario[codigo] for codigo in CODIGOS_DO_CLIMA]
    return [c.nome for c in climas], [c.cor_hex for c in climas]


#: Painel → a dimensão do recorte que um clique nele aplica.
#:
#: O DONO DO PRODUTO FOI À TELA E NÃO ACHOU COMO DESCER OS NÍVEIS, e a causa era
#: esta: o recorte funcionava pela barra de filtros, mas a barra é um SELETOR.
#: Quem olha um painel e vê um tema com 60% de negativas tenta clicar NELE.
#:
#: POR QUE VEM DO SERVIDOR: a tela recebe barras com rótulos, e ligar o clique ao
#: filtro exigiria adivinhar a dimensão pelo TÍTULO do painel — que é a frase de um
#: detector e muda com o dado. Era assim que a tabela escolhia o schema antes, e o
#: comentário de `ColunaSaida` conta como isso quebrou.
#:
#: A CHAVE É A DO PARÂMETRO da rota (`?tema=`, `?empresa=`), e não o nome da
#: coluna: é o que a tela põe na URL, e é o que faz um link reproduzir o ponto do
#: caminho.
RECORTE_DO_PAINEL: dict[str, str] = {
    "Temas × sentimento": "tema",
    "Temas × clima": "tema",
    #: O BLOCO AMPLO DOS TEMAS, logo abaixo dos painéis. Ele mostra os seis temas
    #: mais falados do mês com o sentimento de cada um, e era o único gráfico da
    #: tela em que a barra não levava a lugar nenhum — pedido do dono do produto,
    #: e o pedido seguinte dele já estava atendido: DENTRO de um tema a primeira
    #: aba é o Subtema, porque quem classifica o tema classifica o subtema (as
    #: duas colunas vêm da mesma fonte, e a medida de presença é feita já dentro
    #: do recorte).
    "Temas mais falados": "tema",
    "Concessionárias com maior repercussão": "empresa",
    "Tier do veículo × sentimento": "tier",
    "Perfil de quem fala × sentimento": "perfil_autor",
}


def _bloco(
    tipo: str,
    titulo: str,
    dados: list[dict],
    ficha: Ficha,
    conclusao: str | None,
    legenda: list[str] | None = None,
    subtipo: str | None = None,
    colunas: list[ColunaSaida] | None = None,
    cores: list[str] | None = None,
    recorta: str | None = None,
    coluna_do_link: str | None = None,
) -> BlocoSaida:
    return BlocoSaida(
        tipo=tipo,
        subtipo=subtipo,
        titulo=titulo,
        conclusao=conclusao,
        dados=dados,
        legenda=legenda or [],
        cores=cores or [],
        colunas=colunas or [],
        #: PELO TÍTULO, e é o único lugar onde o título decide algo: `_bloco` é
        #: chamado de dez pontos diferentes, e passar a dimensão em cada chamada
        #: seria dez chances de esquecer. O mapa é pequeno, fica ao lado da
        #: função, e um painel que não está nele simplesmente não recorta.
        #:
        #: DITO NA CHAMADA VENCE O MAPA, e as abas de "onde está a causa" são o
        #: caso: o título delas é o nome da dimensão, que já vem do domínio —
        #: repeti-lo no mapa seria manter a mesma lista em dois lugares.
        #:
        #: O DEDUZIDO PELO TÍTULO MORRE NO BLOCO VAZIO; o DITO na chamada, não.
        #:
        #: Achado de revisão: o mapa casa por TÍTULO, e a Institucional monta um
        #: "Temas mais falados" vazio (ela lê o CRM, não clipping) que passou a
        #: anunciar `recorta: "tema"` — contrato prometendo o que não existe.
        #:
        #: MAS A ABA VAZIA DE "ONDE ESTÁ A CAUSA" CONTINUA DIZENDO O QUE RECORTA,
        #: e é por isso que a distinção existe: ela declara a dimensão na chamada,
        #: e aquela aba É daquela dimensão mesmo num mês em que a fonte não
        #: classificou nada. Perder a chave ali faria a aba virar um quadro
        #: anônimo — e, no mês seguinte, deixaria de abrir o que abre hoje.
        recorta=recorta or (RECORTE_DO_PAINEL.get(titulo) if dados else None),
        coluna_do_link=coluna_do_link,
        ficha=_saida_da_ficha(ficha),
    )


COLUNAS_DO_RATING = [
    ColunaSaida(chave="agencia", titulo="Agência"),
    ColunaSaida(chave="data", titulo="Quando"),
    ColunaSaida(chave="de", titulo="De"),
    ColunaSaida(chave="para", titulo="Para"),
    ColunaSaida(chave="perspectiva", titulo="Perspectiva"),
]


def _colunas_do_teor(linhas: list[dict]) -> list[ColunaSaida]:
    """As colunas da tabela de teor, na ordem em que se lê.

    OS QUATRO PRIMEIROS SÃO FIXOS porque são a leitura — reclamação, dúvida,
    elogio e informação respondem "o que as pessoas queriam". Marcação e NPR
    não viram coluna: elas entram no total e na contagem de acionáveis, que é
    onde importam.
    """
    presentes = {chave for linha in linhas for chave in linha}
    principais = [
        teor for teor in ("Reclamação", "Dúvida", "Elogio", "Informação") if teor in presentes
    ]
    return [
        ColunaSaida(chave="mes", titulo="Mês"),
        *[ColunaSaida(chave=teor, titulo=teor, alinhamento="direita") for teor in principais],
        ColunaSaida(chave="sem_classificacao", titulo="Sem motivo", alinhamento="direita"),
        ColunaSaida(chave="acionaveis", titulo="Acionáveis", alinhamento="direita"),
    ]


# -- a montagem -----------------------------------------------------------------


def _nomes_das_fontes(sessao, lente_id: int) -> str:
    fontes = repositorio_lentes.fontes_da_lente(sessao, lente_id)
    return " · ".join(fonte.nome for fonte in fontes) or "sem fonte cadastrada"


def _serie_em_blocos(serie: list[dict]) -> list[dict]:
    return [
        {
            "mes": f"{linha['mes']:%Y-%m}",
            "positivo": linha["pos"],
            "neutro": linha["neu"],
            "negativo": linha["neg"],
            "total": linha["pos"] + linha["neu"] + linha["neg"],
            "sem_base": linha["sem_base"],
            # O VOLUME QUE NINGUÉM LEU viaja junto, e não é somado ao total:
            # ele não tem sentimento, e engordar o total com ele faria a
            # composição da barra mentir. A tela desenha a faixa cinza à parte.
            "sem_classificacao": linha.get("sem_classificacao", 0),
        }
        for linha in serie
    ]


def _evolucao(
    sessao,
    lente,
    alvo: date,
    meses,
    calibracao: Calibracao,
    conclusao: str | None,
    filtro: FiltroDeMencoes | None = None,
) -> BlocoSaida:
    """A série mensal. Para Mercado é a linha do tempo de eventos, não barras."""
    if lente.codigo == "mercado":
        eventos = repositorio_lentes.eventos_de_mercado(sessao, meses)
        por_mes: dict[str, list[dict]] = {f"{mes:%Y-%m}": [] for mes in meses}
        exemplo = False
        for evento in eventos:
            chave = f"{evento.data:%Y-%m}"
            if chave not in por_mes:
                continue
            exemplo = exemplo or evento.exemplo
            por_mes[chave].append({"texto": evento.texto, "efeito": evento.efeito})
        return _bloco(
            "linha_do_tempo",
            "Eventograma · mercado e rating",
            [{"mes": mes, "eventos": lista} for mes, lista in por_mes.items()],
            Ficha(
                origem=Procedencia.RELATORIO,
                fonte="Eventograma do Balanço Reputacional",
                exemplo=exemplo,
                lacunas=(
                    "A lente Mercado ainda não tem série mensal medida: o que se "
                    "mostra é a sequência de fatos, e não uma contagem.",
                ),
                conceitos=(
                    Conceito(
                        termo="Efeito do evento",
                        texto=(
                            "Como o fato age sobre a reputação: sustenta, "
                            "pressiona ou misto. É o que pinta a borda do mês."
                        ),
                    ),
                ),
            ),
            conclusao,
        )

    serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao, filtro)
    if lente.codigo == "clientes":
        recebidas = repositorio_lentes.recebidas_por_mes(sessao, lente.id, meses, calibracao)
        respondidas = repositorio_lentes.respondidas_por_mes(sessao, meses)
        exemplo = any(linha["exemplo"] for linha in respondidas.values())
        dados = [
            {
                "mes": f"{mes:%Y-%m}",
                "recebidas": recebidas.get(mes, 0),
                # Ausente, e não zero: zero diria que ninguém respondeu nada.
                "respondidas": (respondidas.get(mes) or {}).get("respondidas"),
                "sem_base": mes not in recebidas,
            }
            for mes in meses
        ]
        return _bloco(
            "barras_pareadas",
            "Mensagens recebidas e respondidas",
            dados,
            Ficha(
                origem=Procedencia.PLANILHA,
                fonte="Approach · Community Management, e o relatório mensal",
                colunas=("Data",),
                lacunas=(LACUNA_RESPOSTA,),
                exemplo=exemplo,
                conceitos=(CONCEITO_ACIONAVEL,),
            ),
            conclusao,
        )

    interna = lente.codigo == "institucional"
    legenda, cores = (
        _legenda_e_cores_do_clima(sessao) if interna else (SENTIMENTO, CORES_DO_SENTIMENTO)
    )
    # A CONCLUSÃO DESTE GRÁFICO FALA DE MATÉRIA, E NÃO DE NOTA. Antes, este
    # bloco herdava `leitura.titulo_da_evolucao` — o mesmo sinal que já é a
    # manchete do Destaque E a primeira linha de `sinais_da_evolucao` logo
    # abaixo (a frase chegava a aparecer três vezes na tela). Era sempre sobre
    # a NOTA ("a nota subiu 21 pontos... o negativo foi de 38% para 24%"), em
    # cima de um gráfico que desenha CONTAGEM de matéria — duas unidades
    # diferentes sem nada dizendo que são diferentes. Aqui embaixo a frase
    # nova descreve só o que o gráfico desenha; o sinal mais rico continua
    # visível no Destaque e no quadro de sinais, sem repetição a mais.
    if not interna:
        do_mes = next((linha for linha in serie if linha["mes"] == alvo), None)
        conclusao = (
            frases.volume_de_materias(
                do_mes["pos"], do_mes["neu"], do_mes["neg"],
                do_mes.get("sem_classificacao", 0), alvo,
            )
            if do_mes and not do_mes["sem_base"]
            else None
        )
    return _bloco(
        "barras_empilhadas",
        "Evolução das matérias" if not interna else "Clima das agendas, mês a mês",
        _serie_em_blocos(serie),
        Ficha(
            origem=Procedencia.CRM if interna else Procedencia.PLANILHA,
            fonte="CRM dos Stakeholders" if interna else _nomes_das_fontes(sessao, lente.id),
            colunas=("Data", "Clima") if interna else ("Data", "Sentimento"),
            conceitos=(CONCEITO_NS,),
        ),
        conclusao,
        legenda,
        cores=cores,
    )


def _paineis(
    sessao, lente, mes: date, meses, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> list[BlocoSaida]:
    """Os dois painéis de cada lente, na ordem da especificação."""
    # OS TÍTULOS PASSAM A VIR DOS DETECTORES, e não de texto salvo. Nulos
    # aqui, preenchidos quando `sinais_da_lente` entrar — a tela já sabe cair no
    # nome do painel quando não há conclusão.
    titulo_a = titulo_b = None

    if lente.codigo == "imprensa":
        tiers = repositorio_lentes.composicao_por_tier(sessao, lente.id, mes, calibracao, filtro)
        matriz = repositorio_lentes.matriz_de_jornalistas(
            sessao, veiculo=filtro.veiculo if filtro else None
        )
        linhas = []
        for pessoa in matriz:
            prioridade = prioridade_do_jornalista(
                pessoa.relevancia, pessoa.exposicao, pessoa.proximidade
            )
            linhas.append(
                {
                    "nome": pessoa.nome,
                    "veiculo": pessoa.veiculo,
                    "relevancia": pessoa.relevancia,
                    "exposicao": pessoa.exposicao,
                    "proximidade": pessoa.proximidade,
                    "pontos": prioridade.pontos,
                    "prioridade": prioridade.nivel,
                    "cadencia": prioridade.cadencia,
                    "exemplo": pessoa.exemplo,
                }
            )
        return [
            _bloco(
                "barras_100",
                "Tier do veículo × sentimento",
                [
                    {
                        "rotulo": _ROTULO_DO_TIER_DA_MATERIA.get(linha["tier"], linha["tier"]),
                        **{k: v for k, v in linha.items() if k != "tier"},
                    }
                    for linha in tiers
                ],
                _ficha_da_base(
                    _nomes_das_fontes(sessao, lente.id),
                    ("Aegea Tier", "Classificação"),
                    (CONCEITO_TIER,),
                ),
                titulo_a,
                SENTIMENTO,
                cores=CORES_DO_SENTIMENTO,
            ),
            _bloco(
                "matriz_prioridade",
                "Matriz de relacionamento com jornalistas",
                linhas,
                Ficha(
                    origem=Procedencia.CADASTRO,
                    fonte="Matriz do Balanço Reputacional, mantida à mão",
                    lacunas=(LACUNA_AUTOR,),
                    exemplo=any(linha["exemplo"] for linha in linhas),
                    conceitos=(
                        Conceito(
                            termo="Prioridade",
                            texto=(
                                "Relevância + exposição + proximidade, de 1 a 5 "
                                "cada. P1 13–15 (contínuo) · P2 10–12 "
                                "(semestral) · P3 7–9 (tático) · P4 abaixo de 7 "
                                "(monitoramento)."
                            ),
                        ),
                    ),
                ),
                titulo_b,
            ),
        ]

    if lente.codigo == "mercado":
        estudo, atributos = repositorio_lentes.estudo_vigente(sessao, mes)
        escala = [
            {
                "rotulo": atributo.atributo,
                "nota": float(atributo.nota),
                "detalhe": atributo.comentario,
            }
            for atributo in atributos
        ]
        eventos = [
            evento
            for evento in repositorio_lentes.eventos_de_mercado(sessao, meses)
            if evento.tipo == "rating"
        ]
        return [
            _bloco(
                "escala_1a5",
                "Percepção do mercado financeiro",
                escala,
                Ficha(
                    origem=Procedencia.RELATORIO,
                    fonte=(
                        f"{estudo.instituto}, {estudo.amostra} entrevistas"
                        if estudo
                        else "nenhum estudo cadastrado até este mês"
                    ),
                    exemplo=bool(estudo and estudo.exemplo),
                    lacunas=(() if estudo else ("Nenhum estudo de percepção cobre este mês.",)),
                ),
                titulo_a,
            ),
            _bloco(
                "tabela",
                "Trajetória de rating",
                [
                    {
                        "agencia": evento.agencia,
                        "data": f"{evento.data:%Y-%m}",
                        "de": evento.nota_anterior,
                        "para": evento.nota_nova,
                        "perspectiva": evento.perspectiva,
                        "efeito": evento.efeito,
                    }
                    for evento in eventos
                ],
                Ficha(
                    origem=Procedencia.RELATORIO,
                    fonte="Ações de rating registradas no eventograma",
                    exemplo=any(evento.exemplo for evento in eventos),
                ),
                titulo_b,
                subtipo="rating",
                colunas=COLUNAS_DO_RATING,
            ),
        ]

    if lente.codigo == "clientes":
        teor = repositorio_lentes.teor_por_mes(sessao, lente.id, meses, calibracao)
        serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao)
        linhas_do_teor = [
            {
                "mes": f"{linha['mes']:%Y-%m}",
                "total": linha["total"],
                "acionaveis": linha["acionaveis"],
                "sem_classificacao": linha["sem_classificacao"],
                **linha["teores"],
            }
            for linha in teor
        ]
        return [
            _bloco(
                "barras_100",
                "Sentimento por mês",
                [
                    {
                        "rotulo": f"{linha['mes']:%Y-%m}",
                        "positivo": linha["pos"],
                        "neutro": linha["neu"],
                        "negativo": linha["neg"],
                        "sem_base": linha["sem_base"],
                        "sem_classificacao": linha.get("sem_classificacao", 0),
                    }
                    for linha in serie
                ],
                _ficha_da_base(_nomes_das_fontes(sessao, lente.id), ("Data", "Sentimento")),
                titulo_a,
                SENTIMENTO,
                cores=CORES_DO_SENTIMENTO,
            ),
            _bloco(
                "tabela",
                "Teor das mensagens",
                linhas_do_teor,
                _ficha_da_base(
                    _nomes_das_fontes(sessao, lente.id),
                    ("TAG (motivo)",),
                    (CONCEITO_ACIONAVEL,),
                ),
                titulo_b,
                subtipo="teor",
                colunas=_colunas_do_teor(linhas_do_teor),
            ),
        ]

    # Sociedade e Institucional: temas e onde a conversa se concentra.
    #
    # A INSTITUCIONAL LÊ DE OUTRO LUGAR. A fonte dela é interna — são agendas
    # registradas, e não menções ingeridas. Rodar aqui as consultas de `mencao`
    # devolveria zero, e zero numa tela se lê como "não houve", nunca como
    # "está noutro lugar".
    interna = lente.codigo == "institucional"

    # OS DOIS PAINÉIS DESTA LENTE FICAM COMO ESTÃO, e isto é uma decisão que eu
    # TOMEI E DESFIZ no meio do caminho.
    #
    # Eu havia trocado o segundo — "Concessionárias com maior repercussão" — por
    # perfil do autor × sentimento, com o argumento de que o perfil é a dimensão
    # mais informativa que a tela não tinha. Desfiz ao conferir a ordem de
    # prioridade que o próprio pacote declara para esta lente: tema, subtema,
    # EMPRESA CITADA, rede, perfil do autor. A concessionária é a terceira e o
    # perfil a quinta — a troca entregava uma dimensão do pacote pagando com
    # outra, mais alta, e ainda tirava da tela a pergunta de negócio que a Aegea
    # faz primeiro: qual operação está apanhando.
    #
    # O PERFIL ENTROU ONDE HAVIA ESPAÇO DE VERDADE: nos indicadores da lente
    # (`Figuras públicas` e `Autor mais negativo`) e no filtro, que é o mecanismo
    # de recorte que esta tela já tem — junto de UF, subtema e autor.

    if interna:
        temas = repositorio_lentes.temas_do_crm(sessao, meses)
        unidades = repositorio_lentes.orgaos_do_crm(sessao, meses)
        legenda_do_clima, cores_do_clima = _legenda_e_cores_do_clima(sessao)
    else:
        temas = repositorio_lentes.temas_por_sentimento(sessao, lente.id, mes, calibracao, filtro)
        unidades = repositorio_lentes.unidades_da_lente(sessao, lente.id, meses, calibracao)
        legenda_do_clima, cores_do_clima = SENTIMENTO, CORES_DO_SENTIMENTO
    return [
        _bloco(
            "barras_100",
            "Temas × clima" if interna else "Temas × sentimento",
            [{"rotulo": linha.pop("tema"), **linha} for linha in temas],
            Ficha(
                origem=Procedencia.CRM if interna else Procedencia.PLANILHA,
                fonte="CRM dos Stakeholders" if interna else _nomes_das_fontes(sessao, lente.id),
                colunas=() if interna else ("Tags (tema)", "Sentimento"),
                lacunas=(
                    (
                        "Os temas vêm do vocabulário de cada fornecedor, ainda "
                        "não casado com o dicionário de assuntos do CRM.",
                    )
                    if not interna
                    else ()
                ),
            ),
            titulo_a,
            legenda_do_clima,
            cores=cores_do_clima,
        ),
        _bloco(
            "barras_horizontais",
            "Órgãos com mais interações" if interna else "Concessionárias com maior repercussão",
            [
                {
                    "rotulo": linha["unidade"],
                    "valor": linha["total"],
                    "detalhe": (
                        f"pico em {linha['pico_mes']:%Y-%m} ({linha['pico']})"
                        if linha["pico_mes"]
                        else None
                    ),
                }
                for linha in unidades
            ],
            Ficha(
                origem=Procedencia.CRM if interna else Procedencia.PLANILHA,
                fonte="CRM dos Stakeholders" if interna else _nomes_das_fontes(sessao, lente.id),
                colunas=() if interna else ("Concessionárias", "Unidades/Empresas"),
                lacunas=(
                    (
                        "A clipagem de imprensa marca a companhia inteira em toda "
                        "matéria e por isso não entra aqui.",
                    )
                    if not interna
                    else ()
                ),
            ),
            titulo_b,
        ),
    ]


def _onde_esta_a_causa(
    sessao,
    lente,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    ja_usadas: FiltroDeMencoes | None = None,
    ve_diretorio: bool = True,
) -> list[BlocoSaida]:
    """As abas do cartão "Onde está a causa": o mesmo mês, cortado por cada
    dimensão que o explica.

    É A NAVEGAÇÃO QUE FALTAVA ENTRE O NÍVEL 1 E O NÍVEL 3. A tela tinha a nota
    (nível 1), tinha a lista de itens (nível 3) e, no meio, dois painéis — tema e
    concessionária. As outras seis dimensões que o pacote prioriza só existiam no
    seletor da barra, que serve a quem JÁ SABE o que procurar. Quem abre a lente
    com a nota caída não sabe: a pergunta é "onde está a causa", e ela se responde
    trocando de aba até uma barra pular.

    CADA ABA É UM BLOCO COMO OS OUTROS — linhas com sentimento, ficha de
    procedência e a dimensão que um clique aplica. A tela que já desenha
    `barras_100` não aprende nada novo para desenhar estas.

    QUEM MANDA NA ORDEM E NO CRITÉRIO é `app/dominio/causa_da_lente`; aqui só se
    veste o resultado. Ver lá por que seis abas, e por que uma dimensão com 70%
    de nulo não é causa.

    O AUTOR NÃO É DIRETÓRIO, e a distinção é a mesma que `_nomeia_o_diretorio`
    faz: `ve_diretorio` guarda o CADASTRO de terceiros (a matriz de jornalistas,
    os órgãos do CRM), não o nome que veio dentro da menção. O indicador "Autor
    mais negativo" já publica o perfil que mais pesou, pela mesma razão.
    """
    cortes = repositorio_lentes.cortes_da_causa(
        sessao, lente.codigo, lente.id, mes, calibracao, filtro, ve_diretorio=ve_diretorio
    )
    #: DENTRO DE "UF: RJ" NÃO SE OFERECE UF DE NOVO, e é esta linha que faz o
    #: empilhamento ter fim: a dimensão já usada daria uma única barra de 100% e
    #: repetiria a pergunta que acabou de ser respondida.
    if ja_usadas is not None:
        usadas = {passo.chave for passo in _trilha_do_recorte(lente.codigo, ja_usadas)}
        cortes = [corte for corte in cortes if corte.dimensao.chave not in usadas]
    if not cortes:
        return []
    fonte = _nomes_das_fontes(sessao, lente.id)
    blocos = []
    for corte in cortes:
        #: TODO CORTE É ABA, inclusive o sem linha nenhuma: a fileira de abas é a
        #: mesma em todo mês, e a aba vazia diz que a fonte não classificou aquele
        #: campo. Decisão do dono do produto — ver `dimensoes_do_recorte`.
        dimensao, linhas, presenca, total = (
            corte.dimensao,
            corte.linhas,
            corte.presenca,
            corte.total,
        )
        faltam = total - presenca.preenchidas
        blocos.append(
            _bloco(
                "barras_100",
                dimensao.rotulo,
                linhas,
                Ficha(
                    origem=Procedencia.PLANILHA,
                    fonte=fonte,
                    colunas=(dimensao.rotulo, "Sentimento"),
                    #: QUANTO FALTA VAI ESCRITO, e é o que impede a aba de
                    #: mentir por omissão: o corte ignora nulo, então uma
                    #: dimensão presente em pouco mais da metade dos itens
                    #: desenha barras que somam 100% de um mês menor do que o
                    #: mês. Quem lê precisa saber de qual pedaço se fala.
                    #: QUANTO FALTA, SEMPRE QUE FALTA — e, quando falta TUDO, é
                    #: esta frase que explica a aba vazia. É o que transforma um
                    #: quadro em branco num fato sobre a fonte, que dá para cobrar
                    #: do fornecedor.
                    lacunas=(
                        (
                            (
                                f"A fonte não classificou {dimensao.rotulo.lower()} "
                                f"em nenhuma das {_num(total)} menções deste mês."
                            )
                            if not presenca.preenchidas
                            else (
                                f"{dimensao.rotulo} vem em {_num(presenca.preenchidas)} "
                                f"das {_num(total)} menções do mês; {_num(faltam)} não "
                                "trazem o campo."
                            ),
                        )
                        if faltam
                        else ()
                    ),
                ),
                None,
                SENTIMENTO,
                cores=CORES_DO_SENTIMENTO,
                recorta=dimensao.chave,
            )
        )
    return blocos


def _trilha_do_recorte(codigo_da_lente: str, filtro: FiltroDeMencoes) -> list[PassoDaTrilha]:
    """O caminho até este recorte, na ordem em que a lente se explica.

    A TRILHA É O QUE IMPEDE O DRAWER DE SER UM BECO: sem ela, quem desceu dois
    níveis não sabe de onde veio nem o que remover para subir um.

    A ORDEM É A DO DOMÍNIO, e não a dos cliques: a ordem dos cliques não viaja
    numa URL (`?uf=RJ&perfil_autor=Cidadão` é o mesmo conjunto de qualquer jeito),
    e uma trilha que mudasse de forma conforme o caminho tomado faria dois links
    para o mesmo recorte se lerem como recortes diferentes.
    """
    valores = {
        "tema": filtro.tema_texto,
        "subtema": filtro.subtema,
        "empresa": filtro.empresa,
        "veiculo": filtro.veiculo,
        "perfil_autor": filtro.perfil_autor,
        "autor": filtro.autor,
        "uf": filtro.uf,
        "tier": filtro.tier,
        "atributo": filtro.atributo,
    }
    #: PRIMEIRO AS DA LENTE, NA ORDEM DELA; depois TODAS as outras que o filtro
    #: aceita, na ordem do dicionário de rótulos.
    #:
    #: ACHADO DE REVISÃO: eu apensava tier e atributo à mão — as duas que me
    #: vieram à cabeça. `subtema` na Imprensa, `empresa` em qualquer lente cuja
    #: lista não a traga: aplicados pelo servidor e invisíveis na trilha. Um
    #: degrau invisível não dá para remover.
    da_lente = [d.chave for d in DIMENSOES_POR_LENTE.get(codigo_da_lente, ())]
    ordem = da_lente + [chave for chave in ROTULO_DA_DIMENSAO if chave not in da_lente]
    rotulos = {d.chave: d.rotulo for d in DIMENSOES_POR_LENTE.get(codigo_da_lente, ())}
    return [
        PassoDaTrilha(
            chave=chave,
            #: O RÓTULO DA LENTE VENCE o genérico: na Sociedade, `veiculo` se lê
            #: "Rede"; na Imprensa, "Veículo". É a mesma coluna com dois nomes, e
            #: quem lê a trilha espera o nome que viu na aba.
            dimensao=rotulos.get(chave) or ROTULO_DA_DIMENSAO[chave],
            valor=valores[chave],
        )
        for chave in ordem
        if valores.get(chave)
    ]


def _frase_do_recorte(
    lente,
    filtro: FiltroDeMencoes,
    impacto: float,
    composicao: dict[str, int],
    itens: int,
    no_mes: int,
) -> str:
    """A frase do topo do drawer — o número em palavras.

    CALCULADA A CADA LEITURA, nunca salva: texto guardado envelhece em silêncio
    numa tela que a diretoria lê como se fosse deste mês.

    DIZ OS DOIS NÚMEROS: "4 itens" não informa nada; "4 dos 6 itens do mês"
    informa que isto é metade do mês. É a diferença entre um pedaço que explica a
    nota e um que só aparece primeiro na lista.
    """
    if not itens:
        return f"Nenhum item deste recorte em {lente.nome} neste mês."
    negativas = round(composicao["negativo"] / itens * 100)
    verbo = "tira" if impacto < 0 else "põe"
    pontos = f"{abs(impacto):.1f}".replace(".", ",")
    quantos = f"{_num(itens)} de {_num(no_mes)}" if no_mes else _num(itens)
    return (
        f"Este recorte {verbo} {pontos} ponto"
        f"{'s' if abs(impacto) >= 2 else ''} da nota de {lente.nome}, "
        f"com {quantos} itens do mês e {negativas}% de negativas."
    )


def _nomeia_o_diretorio(codigo_da_lente: str, bloco: BlocoSaida) -> bool:
    """Este painel publica NOME de gente ou de instituição de fora?

    É a pergunta que separa o que `ve_diretorio` guarda do que ele não guarda, e
    ela não se responde pelo tipo do bloco: `barras_horizontais` serve tanto
    "Órgãos com mais interações" — os mesmos nomes que `GET /api/instituicoes`
    recusa a este papel — quanto "Concessionárias com maior repercussão", que é
    unidade de negócio da própria Aegea e não é cadastro de terceiro. Gatilhar
    pelo tipo esconderia da lente errada um dado que é da casa.
    """
    if bloco.tipo == "matriz_prioridade":
        return True
    return codigo_da_lente == "institucional" and bloco.tipo == "barras_horizontais"


#: As cores do tier, na mesma paleta oficial da Aegea que o resto do produto
#: usa — nunca uma cor inventada para preencher uma fatia da rosca.
_CORES_DO_TIER = {
    "muito_relevante": "#0027BD",  # Azul Mar
    "relevante": "#17E3CB",  # Turquesa Rio
    "menos_relevante": "#A11FFF",  # Roxo Açaí
}


def _volume_por_tier(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """A rosca de volume por tier — mesmo desenho de "% Interações por tier"
    do Painel (CRM), com matéria no lugar de interação.

    REAPROVEITA `composicao_por_tier`, a mesma consulta do painel "Tier do
    veículo × sentimento": a rosca só soma os três sentimentos de cada tier,
    não pede nada que aquela consulta já não traga.

    SÓ NA IMPRENSA — POR HORA (decisão do Jones, 2026-10-02), e NÃO por o dado
    do Mercado ser inválido: a migration 0048 já define Mercado como "o mesmo
    clipping da Clipei, recortado por público-alvo Investidores" — tier e
    veículo são tão reais ali quanto na Imprensa, e é por isso que o semeador
    de desenvolvimento usa a mesma função para as duas (`_imprensa_ou_mercado`
    em `semear_mencoes.py`). A restrição é só a tela: olhando os dois gráficos
    lado a lado nas lentes ainda não fazia sentido PRA ELE ver os mesmos
    veículos/tiers repetidos em Imprensa e Mercado — Sociedade/Clientes nunca
    tiveram o campo, então para elas o bloco já saía vazio de qualquer jeito.
    Se um dia o recorte por público-alvo virar outro veículo/tier na prática
    (ex.: fontes econômicas específicas), vale revisitar.
    """
    if lente.codigo != "imprensa":
        vazio_ficha = (
            Ficha(
                origem=Procedencia.CRM,
                fonte="Esta lente não vem de clipping",
                lacunas=("A lente Institucional não tem tier — ela lê o CRM.",),
            )
            if repositorio_lentes.lente_e_interna(sessao, lente.id)
            else Ficha(
                origem=Procedencia.PLANILHA,
                fonte=_nomes_das_fontes(sessao, lente.id),
                lacunas=(
                    "Por ora esta tela só mostra tier na lente Imprensa.",
                ),
            )
        )
        return _bloco("rosca", "Volume por tier", [], vazio_ficha, None)

    tiers = repositorio_lentes.composicao_por_tier(sessao, lente.id, mes, calibracao, filtro)
    return _bloco(
        "rosca",
        "Volume por tier",
        [
            {
                "chave": linha["tier"],
                "rotulo": _ROTULO_DO_TIER_DA_MATERIA.get(linha["tier"], linha["tier"]),
                "total": linha["positivo"] + linha["neutro"] + linha["negativo"],
                "cor": _CORES_DO_TIER.get(linha["tier"]),
            }
            for linha in tiers
        ],
        Ficha(
            origem=Procedencia.PLANILHA,
            fonte=_nomes_das_fontes(sessao, lente.id),
            colunas=("Aegea Tier",),
        ),
        None,
    )


def _veiculos(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> tuple[BlocoSaida, BlocoSaida]:
    """Top veículos por volume, e o placar de clima de cada um — mesmo par
    de "Top 5 instituições" + "Clima por Instituições" do Painel (CRM), por
    veículo em vez de instituição.

    UMA CONSULTA SÓ alimenta os dois blocos: top-por-volume e o saldo de
    sentimento são a mesma soma lida de dois jeitos.

    SÓ NA IMPRENSA — POR HORA: mesma ressalva de `_volume_por_tier` — é
    restrição de TELA, pedida pelo Jones, e não um juízo de que o dado do
    Mercado seja inválido (ver o motivo completo lá).
    """
    if lente.codigo != "imprensa":
        vazio_ficha = (
            Ficha(
                origem=Procedencia.CRM,
                fonte="Esta lente não vem de clipping",
                lacunas=("A lente Institucional não tem veículo — ela lê o CRM.",),
            )
            if repositorio_lentes.lente_e_interna(sessao, lente.id)
            else Ficha(
                origem=Procedencia.PLANILHA,
                fonte=_nomes_das_fontes(sessao, lente.id),
                lacunas=(
                    "Por ora esta tela só mostra veículo na lente Imprensa.",
                ),
            )
        )
        return (
            _bloco("barras_horizontais", "Top veículos", [], vazio_ficha, None),
            _bloco("divergente_por_item", "Clima por veículos", [], vazio_ficha, None),
        )

    veiculos = repositorio_lentes.veiculos_por_sentimento(sessao, lente.id, mes, calibracao, filtro)
    ficha = Ficha(
        origem=Procedencia.PLANILHA,
        fonte=_nomes_das_fontes(sessao, lente.id),
        colunas=("Veículo", "Classificação"),
    )
    top_veiculos = _bloco(
        "barras_horizontais",
        "Top veículos",
        [{"rotulo": linha["veiculo"], "valor": linha["total"]} for linha in veiculos],
        ficha,
        None,
    )
    # MESMO CÁLCULO DO PAINEL (CRM): (positivas − negativas) ÷ total × 100,
    # de −100 a 100 — não é o NS oficial do Score (que pondera por tier e vai
    # de 0 a 100). É o placar simples que a diretoria já conhece de lá.
    clima_por_veiculos = _bloco(
        "divergente_por_item",
        "Clima por veículos",
        [
            {
                "chave": linha["veiculo"],
                "rotulo": linha["veiculo"],
                "total": linha["total"],
                "score": round((linha["positivo"] - linha["negativo"]) / linha["total"] * 100),
            }
            for linha in veiculos
        ],
        ficha,
        None,
    )
    return top_veiculos, clima_por_veiculos


def _drivers_e_riscos(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """"Drivers e riscos": os atributos reputacionais que mais puxam a lente,
    em volume e sentimento — não só o saldo final que a nota resume.

    SÓ NAS LENTES DE CLIPPING, pelo mesmo motivo de `_materias_recentes`: a
    institucional não tem `atributo` nenhum, porque não vem de `mencao`.
    """
    if repositorio_lentes.lente_e_interna(sessao, lente.id):
        return _bloco(
            "barras_100",
            "Drivers e riscos",
            [],
            Ficha(
                origem=Procedencia.CRM,
                fonte="Esta lente não vem de clipping",
                lacunas=("A lente Institucional não tem atributo — ela lê o CRM.",),
            ),
            None,
            SENTIMENTO,
            cores=CORES_DO_SENTIMENTO,
        )

    atributos = repositorio_lentes.atributos_por_sentimento(
        sessao, lente.id, mes, calibracao, filtro
    )
    return _bloco(
        "barras_100",
        "Drivers e riscos",
        [{"rotulo": linha.pop("atributo"), **linha} for linha in atributos],
        Ficha(
            origem=Procedencia.PLANILHA,
            fonte=_nomes_das_fontes(sessao, lente.id),
            colunas=("Atributo", "Classificação"),
        ),
        None,
        SENTIMENTO,
        cores=CORES_DO_SENTIMENTO,
    )


def _temas_mais_falados(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """Os temas (Subcategoria da Clipei) mais falados do mês, por sentimento.

    SÓ NAS LENTES DE CLIPPING — mesma ressalva de `_drivers_e_riscos`.
    """
    if repositorio_lentes.lente_e_interna(sessao, lente.id):
        return _bloco(
            "barras_100",
            "Temas mais falados",
            [],
            Ficha(
                origem=Procedencia.CRM,
                fonte="Esta lente não vem de clipping",
                lacunas=("A lente Institucional tem seu próprio bloco de temas, lido do CRM.",),
            ),
            None,
            SENTIMENTO,
            cores=CORES_DO_SENTIMENTO,
        )

    temas = repositorio_lentes.temas_por_sentimento(sessao, lente.id, mes, calibracao, filtro)
    return _bloco(
        "barras_100",
        "Temas mais falados",
        [{"rotulo": linha.pop("tema"), **linha} for linha in temas],
        Ficha(
            origem=Procedencia.PLANILHA,
            fonte=_nomes_das_fontes(sessao, lente.id),
            colunas=("Tags (tema)", "Sentimento"),
            lacunas=(
                "Os temas vêm do vocabulário de cada fornecedor, ainda não "
                "casado com o dicionário de assuntos do CRM.",
            ),
        ),
        None,
        SENTIMENTO,
        cores=CORES_DO_SENTIMENTO,
    )


_ROTULO_DO_SENTIMENTO = {"pos": "Positivo", "neu": "Neutro", "neg": "Negativo"}
_ROTULO_DO_TIER_DA_MATERIA = {
    "muito_relevante": "Tier 1",
    "relevante": "Tier 2",
    "menos_relevante": "Tier 3",
}


#: Sem recorte: só uma amostra do mês inteiro. Com recorte (um veículo, um
#: tier...): o universo já é pequeno, então sobe para "praticamente tudo".
TETO_DE_MATERIAS = 5
TETO_DE_MATERIAS_FILTRADO = 30


def _mencoes_da_sociedade(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """As menções de rede do mês — o nível do item, nesta lente.

    SÓ AS QUE TÊM TEXTO. Uma linha sem texto nesta tabela é um endereço sem
    conteúdo: nem se lê, nem se clica. Elas continuam na nota, nos cortes e no
    engajamento — o que não fazem é ocupar a lista de leitura.
    """
    quantas = TETO_DE_MATERIAS_FILTRADO if filtro and filtro.ativo else TETO_DE_MATERIAS
    linhas = [
        {
            "texto": linha["titulo_texto"],
            "quando": f"{linha['data']:%d/%m}" if linha["data"] else None,
            "veiculo": linha["veiculo"],
            "sentimento": _ROTULO_DO_SENTIMENTO.get(
                linha["sentimento"], linha["sentimento"]
            ),
            "autor": linha["autor"],
            "perfil": linha["perfil_autor"],
            "engajamento": _num(linha["engajamento"]) if linha["engajamento"] else None,
            "link": linha["link"],
        }
        for linha in repositorio_lentes.materias_recentes(
            sessao, lente.id, mes, calibracao, filtro, quantas=quantas
        )
        if linha["titulo_texto"]
    ]
    return _bloco(
        "tabela",
        "Menções do mês",
        linhas,
        Ficha(
            origem=Procedencia.PLANILHA,
            fonte=_nomes_das_fontes(sessao, lente.id),
            colunas=("Texto", "Link", "Autor", "Perfil do autor", "Engajamento"),
            lacunas=(
                # O NÚMERO É DO PACOTE, e dizer quanto falta é o que separa
                # "não houve menção" de "o texto ainda não chegou": o
                # fornecedor manda o conteúdo de uma amostra — as negativas,
                # as de tier alto e as mais engajadas — e o resto vem na
                # primeira carga mensal completa.
                "O texto e o link vêm numa amostra das menções (as negativas, "
                "as de maior alcance e as mais engajadas). As demais entram na "
                "nota e nos cortes, mas não têm o que mostrar aqui.",
            ),
        ),
        None,
        subtipo="mencoes",
        colunas=COLUNAS_DAS_MENCOES,
        #: O ENDEREÇO SAIU DA GRADE E VIROU O DESTINO DA LINHA — ver
        #: `BlocoSaida.coluna_do_link`. O valor continua em `dados`.
        coluna_do_link="link",
    )


def _materias_recentes(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """O drill-down até a linha: as matérias mais recentes por trás da nota.

    SÓ NA IMPRENSA — POR HORA: mesma ressalva de `_volume_por_tier` — é
    restrição de TELA, pedida pelo Jones (2026-10-02), e não um juízo de que
    o dado do Mercado seja inválido. As colunas desta tabela ("Veículo",
    "Aegea Tier") são as mesmas duas que motivaram a restrição lá.

    A SOCIEDADE SAIU DESSA RESTRIÇÃO, e pela própria razão dela: o motivo era
    que as colunas de clipping não dizem nada de um post. A carga do padrão
    trouxe o que uma menção de rede precisa — o texto, o link, quem escreveu e o
    engajamento —, então ela ganha a lista com as colunas DELA
    (`_mencoes_da_sociedade`). As outras três continuam como o Jones pediu.
    """
    if lente.codigo == "sociedade":
        return _mencoes_da_sociedade(sessao, lente, mes, calibracao, filtro)

    if lente.codigo != "imprensa":
        vazio_ficha = (
            Ficha(
                origem=Procedencia.CRM,
                fonte="Esta lente não vem de clipping",
                lacunas=("A lente Institucional não tem matéria — ela lê o CRM.",),
            )
            if repositorio_lentes.lente_e_interna(sessao, lente.id)
            else Ficha(
                origem=Procedencia.PLANILHA,
                fonte=_nomes_das_fontes(sessao, lente.id),
                lacunas=("Por ora esta tela só mostra matérias na lente Imprensa.",),
            )
        )
        return _bloco(
            "tabela",
            "Últimas matérias",
            [],
            vazio_ficha,
            None,
            subtipo="materias",
            colunas=COLUNAS_DAS_MATERIAS,
        )

    # COM RECORTE ATIVO, O TETO SOBE. Cinco bastam para "o que aconteceu no
    # mês nesta lente" — mas quem clicou num veículo no placar de clima quer
    # ver AS matérias que formaram aquele saldo, não uma amostra delas. Um
    # veículo com recorte já é um universo pequeno (dezenas, não milhares),
    # então um teto mais alto continua seguro.
    quantas = TETO_DE_MATERIAS_FILTRADO if filtro and filtro.ativo else TETO_DE_MATERIAS
    linhas = [
        {
            "quando": f"{linha['data']:%d/%m}" if linha["data"] else None,
            "veiculo": linha["veiculo"],
            "sentimento": _ROTULO_DO_SENTIMENTO.get(linha["sentimento"], linha["sentimento"]),
            "tier": _ROTULO_DO_TIER_DA_MATERIA.get(linha["tier"], linha["tier"]),
            "atributo": linha["atributo"],
            "tema": linha["tema"],
        }
        for linha in repositorio_lentes.materias_recentes(
            sessao, lente.id, mes, calibracao, filtro, quantas=quantas
        )
    ]
    return _bloco(
        "tabela",
        "Últimas matérias",
        linhas,
        Ficha(
            origem=Procedencia.PLANILHA,
            fonte=_nomes_das_fontes(sessao, lente.id),
            colunas=("Data", "Veículo", "Classificação", "Aegea Tier", "Atributo", "Subcategoria"),
        ),
        None,
        subtipo="materias",
        colunas=COLUNAS_DAS_MATERIAS,
    )


def _kpis(
    sessao,
    lente,
    mes: date,
    meses,
    calibracao: Calibracao,
    medida,
    filtro: FiltroDeMencoes | None = None,
) -> list[KpiSaida]:
    """Os quatro números do destaque — e eles são DIFERENTES em cada lente.

    A §3 dá a lista de cada uma, e não é capricho: "matérias no ano" responde a
    pergunta da imprensa, e não a de clientes, que quer saber quanto do que
    chegou foi respondido. Quatro KPIs genéricos serviriam a todas e a nenhuma.

    ONDE O DADO NÃO EXISTE, O KPI DIZ "—". Inventar um número parecido para
    encher o quadrante é pior do que deixar a lacuna à vista.
    """
    alvo = repositorio_score.primeiro_dia(mes)
    serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao, filtro)
    do_mes = next((linha for linha in serie if linha["mes"] == alvo), None)
    total = sum(linha["pos"] + linha["neu"] + linha["neg"] for linha in serie)
    com_base = [linha for linha in serie if not linha["sem_base"]]

    if lente.codigo == "imprensa":
        return _kpis_da_imprensa(
            sessao, lente, meses, calibracao, serie, com_base, do_mes, total, filtro
        )
    if lente.codigo == "mercado":
        return _kpis_do_mercado(sessao, mes, meses)
    if lente.codigo == "clientes":
        return _kpis_dos_clientes(sessao, lente, alvo, meses, calibracao)
    if lente.codigo == "institucional":
        return _kpis_do_institucional(serie, do_mes, total)
    return _kpis_da_sociedade(sessao, lente, alvo, meses, calibracao, serie, do_mes, total)


def _kpis_da_imprensa(
    sessao, lente, meses, calibracao, serie, com_base, do_mes, total,
    filtro: FiltroDeMencoes | None = None,
) -> list[KpiSaida]:
    pico = max(serie, key=lambda linha: linha["neg"], default=None)
    positivas = sum(linha["pos"] for linha in serie)
    neutras = sum(linha["neu"] for linha in serie)
    veiculos_tier1 = repositorio_lentes.veiculos_tier1_do_periodo(
        sessao, lente.id, meses, calibracao, filtro
    )
    return [
        KpiSaida(
            rotulo="Matérias no período",
            valor=_num(total),
            detalhe=(
                f"média de {_num(round(total / len(com_base)))} por mês"
                if com_base
                else "nenhum mês com base"
            ),
        ),
        KpiSaida(
            rotulo="Positivas ou neutras",
            valor=_pct((positivas + neutras) / total if total else None),
            detalhe=f"{_num(positivas)} positivas",
        ),
        KpiSaida(
            rotulo="Pico negativo",
            valor=_num(pico["neg"]) if pico and pico["neg"] else "—",
            detalhe=f"{pico['mes']:%Y-%m}" if pico and pico["neg"] else "sem negativa",
        ),
        KpiSaida(
            rotulo="Veículos Tier 1",
            valor=str(veiculos_tier1),
            detalhe="cobertura do período",
        ),
    ]


def _kpis_do_mercado(sessao, mes: date, meses) -> list[KpiSaida]:
    estudo, atributos = repositorio_lentes.estudo_vigente(sessao, mes)
    rebaixamentos = [
        evento
        for evento in repositorio_lentes.eventos_de_mercado(sessao, meses)
        if evento.tipo == "rating" and evento.efeito == "pressiona"
    ]
    por_nome = {atributo.atributo.lower(): atributo for atributo in atributos}
    solidez = next((a for nome, a in por_nome.items() if "solidez" in nome), None)
    eficiencia = next((a for nome, a in por_nome.items() if "efici" in nome), None)

    return [
        KpiSaida(
            rotulo="Solidez financeira",
            valor=_nota(solidez),
            detalhe="de 5" if solidez else "sem estudo neste mês",
        ),
        KpiSaida(
            rotulo="Eficiência operacional",
            valor=_nota(eficiencia),
            detalhe="de 5" if eficiencia else "sem estudo neste mês",
        ),
        KpiSaida(
            rotulo="Rebaixamentos no período",
            valor=str(len(rebaixamentos)),
            detalhe=", ".join(
                sorted({evento.agencia for evento in rebaixamentos if evento.agencia})
            )
            or "nenhuma ação de rating",
        ),
        KpiSaida(
            rotulo="Entrevistas do estudo",
            valor=str(estudo.amostra) if estudo and estudo.amostra else "—",
            detalhe=estudo.instituto if estudo else "nenhum estudo cadastrado",
        ),
    ]


def _kpis_dos_clientes(sessao, lente, alvo: date, meses, calibracao) -> list[KpiSaida]:
    recebidas = repositorio_lentes.recebidas_por_mes(sessao, lente.id, meses, calibracao)
    respondidas = repositorio_lentes.respondidas_por_mes(sessao, meses)
    teor_do_mes = next(
        (
            linha
            for linha in repositorio_lentes.teor_por_mes(sessao, lente.id, [alvo], calibracao)
            if linha["mes"] == alvo
        ),
        {"acionaveis": 0, "teores": {}, "total": 0},
    )
    taxa = TaxaDeResposta(
        recebidas=recebidas.get(alvo, 0),
        acionaveis=teor_do_mes["acionaveis"],
        respondidas=(respondidas.get(alvo) or {}).get("respondidas"),
    )
    pico = max(recebidas.items(), key=lambda item: item[1], default=None)
    elogios = teor_do_mes["teores"].get("Elogio", 0)

    return [
        KpiSaida(
            rotulo="Recebidas no mês",
            valor=_num(taxa.recebidas),
            detalhe=(f"pico de {_num(pico[1])} em {pico[0]:%Y-%m}" if pico else "sem base"),
        ),
        KpiSaida(
            rotulo="Resposta bruta",
            valor=_pct(taxa.bruta),
            detalhe="sobre tudo o que chegou",
        ),
        KpiSaida(
            rotulo="Resposta operacional",
            valor=_pct(taxa.operacional),
            detalhe=f"sobre {_num(taxa.acionaveis)} mensagens acionáveis",
        ),
        KpiSaida(
            rotulo="Elogio",
            valor=_pct(elogios / teor_do_mes["total"] if teor_do_mes["total"] else None),
            detalhe=f"{_num(elogios)} mensagens",
        ),
    ]


def _kpis_do_institucional(serie, do_mes, total) -> list[KpiSaida]:
    no_mes = (do_mes["pos"] + do_mes["neu"] + do_mes["neg"]) if do_mes else 0
    return [
        KpiSaida(
            rotulo="Agendas no período",
            valor=_num(total),
            detalhe=f"{_num(no_mes)} no mês de referência",
        ),
        KpiSaida(
            rotulo="Clima propositivo",
            valor=_pct(do_mes["pos"] / no_mes if no_mes else None),
            detalhe=f"{_num(do_mes['pos'])} agendas" if do_mes else "sem base",
        ),
        KpiSaida(
            rotulo="Clima tenso",
            valor=_pct(do_mes["neg"] / no_mes if no_mes else None),
            detalhe=f"{_num(do_mes['neg'])} agendas" if do_mes else "sem base",
        ),
        # O "% Avançou" da §3 depende do RESULTADO da agenda, que hoje nem toda
        # interação preenche. Prometer o número sem a base seria pior do que
        # dizer que ele ainda não existe — e o encaminhamento da própria lente
        # já cobra o preenchimento.
        KpiSaida(
            rotulo="Agendas que avançaram",
            valor="—",
            detalhe="depende do resultado preenchido no CRM",
        ),
    ]


def _kpis_da_sociedade(
    sessao, lente, alvo: date, meses, calibracao, serie, do_mes, total
) -> list[KpiSaida]:
    no_mes = (do_mes["pos"] + do_mes["neu"] + do_mes["neg"]) if do_mes else 0

    autores = repositorio_lentes.autores_por_sentimento(
        sessao, lente.id, alvo, calibracao, quantos=1
    )
    #: CONTAGEM DIRETA, e não a soma de um corte: o corte por perfil devolve os
    #: seis de maior VOLUME, e com sete grafias na frente "Figura pública" cairia
    #: fora dele — o indicador mostraria zero sem nada ter acontecido. Achado de
    #: revisão; ver `quantas_com`.
    figuras = repositorio_lentes.quantas_com(
        sessao, Mencao.perfil_autor, "Figura pública", lente.id, alvo, calibracao
    )
    #: A UF MAIS NEGATIVA é a de mais menções NEGATIVAS, e não a de mais menções:
    #: o estado com mais volume costuma ser o maior, e isso não é notícia.
    #:
    #: ORDENADA PELO NEGATIVO NA PRÓPRIA CONSULTA, e aqui estava o segundo achado
    #: da mesma família: eu lia o corte por volume e escolhia o mais negativo
    #: DENTRE OS SEIS MAIORES. Seis UFs grandes e pouco negativas escondiam uma
    #: pequena inteiramente negativa — que é justamente a que interessa.
    mais_negativas = repositorio_lentes.ufs_por_sentimento(
        sessao, lente.id, alvo, calibracao, quantos=1, ordenar_pelo_negativo=True
    )
    mais_negativa = mais_negativas[0] if mais_negativas and mais_negativas[0]["negativo"] else None
    return [
        KpiSaida(
            rotulo="Menções no período",
            valor=_num(total),
            detalhe=f"{len([x for x in serie if not x['sem_base']])} meses com base",
        ),
        # -- OS TRÊS QUE O PACOTE DE PRODUÇÃO NOMEIA PARA ESTA LENTE ---------
        #
        # ELES SUBSTITUEM TRÊS, e não se somam aos quatro: o dossiê tem quatro
        # indicadores por lente, de propósito — "é o que faz as cinco lentes se
        # lerem igual", e o Pydantic recusa o quinto. Acrescentar os do pacote
        # daria sete nesta lente e quatro nas outras.
        #
        # SAÍRAM "POSITIVO NO MÊS" E "NEGATIVO NO MÊS" porque a manchete do
        # dossiê já diz isso em palavras ("o negativo foi de 45% para 53%") e o
        # gráfico de evolução o desenha mês a mês — três lugares para o mesmo
        # número, e o cartão era o que menos acrescentava.
        #
        # SAIU TAMBÉM "UNIDADE COM MAIS MENÇÕES", que continua na tela como
        # painel inteiro ("Concessionárias com maior repercussão"), com o
        # sentimento de cada uma — mais do que o cartão dizia.
        #
        # O QUE ENTROU responde "de quem" e "onde", que é a pergunta seguinte de
        # quem lê uma nota que caiu: `autor_mais_negativo`, `figuras_publicas` e
        # `uf_mais_negativa` no vocabulário do pacote.
        KpiSaida(
            rotulo="Autor mais negativo",
            valor=autores[0]["autor"] if autores else "—",
            detalhe=(
                f"{_num(autores[0]['negativo'])} menções negativas"
                if autores
                else "sem autor informado"
            ),
        ),
        KpiSaida(
            rotulo="Figuras públicas",
            # QUEM FALA, E NÃO QUANTOS CARGOS A FONTE DIGITOU: o cargo do autor
            # chega em 5 dos 14.855 itens reais e o perfil em todos. Contar pelo
            # cargo diria "5 figuras públicas" num mês com centenas delas.
            valor=_num(figuras) if figuras is not None else "—",
            # DE QUANTAS, E NÃO O PERCENTUAL: em junho de 2026 são 5 de 6.932,
            # e "0% das menções do mês" ao lado do número 5 é uma frase que
            # desinforma — quem lê conclui que o indicador está quebrado. A
            # fração bruta diz a mesma coisa sem arredondar para nada.
            detalhe=(
                f"de {_num(no_mes)} menções no mês"
                if figuras is not None and no_mes
                else "sem perfil informado"
            ),
        ),
        KpiSaida(
            rotulo="UF mais negativa",
            valor=mais_negativa["uf"] if mais_negativa else "—",
            detalhe=(
                f"{_num(mais_negativa['negativo'])} menções negativas"
                if mais_negativa
                else "sem UF informada"
            ),
        ),
    ]


def _num(valor: int | None) -> str:
    return "—" if valor is None else f"{valor:,}".replace(",", ".")


def _nota(atributo) -> str:
    return "—" if atributo is None else f"{float(atributo.nota):.1f}".replace(".", ",")


def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{round(valor * 100)}%"


def _com_conclusao(bloco: BlocoSaida, frase: str | None) -> BlocoSaida:
    """O título-conclusão do bloco, quando o detector tem algo a dizer.

    NÃO REPETE O NOME DO PRÓPRIO BLOCO. Sem sinal naquela seção, a §3 manda
    usar o nome do painel — que a tela já mostra no título logo acima. Copiá-lo
    para a conclusão desenharia a mesma frase duas vezes, uma embaixo da outra.
    """
    if not frase or frase == bloco.titulo:
        return bloco
    return bloco.model_copy(update={"conclusao": frase})


#: CAMINHO TRANSITÓRIO. A especificação pede `GET /score/lentes/{lente}`, que
#: hoje é a rota antiga da aba — a que devolve só composição, fórmula e temas. O
#: dossiê fica em `/dossie` até a tela migrar; aí a antiga sai e este endpoint
#: assume o caminho da especificação. Duas rotas com o mesmo caminho seriam
#: resolvidas por ordem de registro, que é o tipo de dependência invisível que
#: quebra num refactor e ninguém liga ao que mudou.
@rotas.get("/{codigo}/dossie")
def obter_dossie(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    #: As dimensões que o padrão Aegea trouxe (0055). Elas se empilham com as de
    #: cima: `?uf=RJ&perfil_autor=Figura+pública` é "figuras públicas no Rio", e
    #: não uma coisa ou a outra. É o nível 3 do pacote, e é o que faz um link
    #: reproduzir o ponto exato do caminho.
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
) -> DossieSaida:
    """A lente inteira: nota, KPIs, evolução, dois painéis, texto e ações.

    OS QUATRO PARÂMETROS SÃO UM RECORTE DE TELA, não a Calibração: ver
    `FiltroDeMencoes`. Ativo, ele recalcula nota, KPIs, evolução e os dois
    painéis sobre o subconjunto de menções que casa com ele — mas NUNCA entra
    no ISR nem é comparado com o mês anterior como se fosse a nota oficial.
    """
    alvo = _mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")

    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        autor=autor,
        empresa=empresa,
    )
    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_lentes.meses_ate(alvo, MESES_DA_EVOLUCAO)

    medidas = {
        medida.codigo: medida for medida in repositorio_score.medir_lentes(sessao, alvo, calibracao)
    }
    medida_sem_filtro = medidas[lente.codigo]

    if filtro.ativo:
        # A NOTA FILTRADA NÃO VEM DO LOTE DAS CINCO: `medir_lentes` só lê
        # `score_mes_fonte`, que não tem veículo/atributo/tema — ver
        # `repositorio_score.medir_uma_lente`.
        medida = repositorio_score.medir_uma_lente(sessao, lente, alvo, calibracao, filtro)
        # "VS. MÊS ANTERIOR" NÃO FAZ SENTIDO AQUI: o mês passado não tem o
        # mesmo recorte. A comparação vira "este recorte vs. o mês inteiro",
        # que é a pergunta que o filtro está mesmo respondendo.
        delta = (
            medida.score - medida_sem_filtro.score
            if medida.score is not None and medida_sem_filtro.score is not None
            else None
        )
        delta_versus = "sem_filtro"
    else:
        anteriores = {
            medida.codigo: medida
            for medida in repositorio_score.medir_lentes(
                sessao, meses[-2] if len(meses) > 1 else alvo, calibracao
            )
        }
        medida = medida_sem_filtro
        antes = anteriores.get(lente.codigo)
        delta = (
            medida.score - antes.score
            if medida.score is not None and antes and antes.score is not None
            else None
        )
        delta_versus = "mes_anterior"

    evolucao = _evolucao(sessao, lente, alvo, meses, calibracao, None, filtro)
    paineis = _paineis(sessao, lente, alvo, meses, calibracao, filtro)
    volume_por_tier = _volume_por_tier(sessao, lente, alvo, calibracao, filtro)
    top_veiculos, clima_por_veiculos = _veiculos(sessao, lente, alvo, calibracao, filtro)
    drivers = _drivers_e_riscos(sessao, lente, alvo, calibracao, filtro)
    temas_falados = _temas_mais_falados(sessao, lente, alvo, calibracao, filtro)
    materias = _materias_recentes(sessao, lente, alvo, calibracao, filtro)
    #: `ve_diretorio` CHEGA ATÉ AQUI porque uma das abas publica nome de gente de
    #: fora: na Imprensa, `autor` é o jornalista — o mesmo cadastro de terceiros
    #: que a matriz de jornalistas publica e que esta permissão guarda. Achado de
    #: revisão: a aba entregava por outra porta o que o painel esconde.
    causa = _onde_esta_a_causa(
        sessao, lente, alvo, calibracao, filtro, ve_diretorio=usuario.ve_diretorio
    )

    #: O QUE ESTE PAPEL NÃO ALCANÇA. `score_leitura` e `score_edicao` têm
    #: `acessa_score` e NÃO têm `ve_diretorio` — e levam 403 em
    #: `GET /api/instituicoes` pelo motivo escrito em `exigir_diretorio`. O
    #: dossiê entregava a eles a mesma classe de dado por outra porta.
    #:
    #: OS SINAIS VÃO JUNTO, e essa é a metade que se esquece: o detector de
    #: concentração narra o primeiro colocado do painel pelo nome, então
    #: esconder o quadro e manter a frase publicaria exatamente o que o quadro
    #: publicava, em uma linha de texto.
    escondidos = (
        set()
        if usuario.ve_diretorio
        else {
            secao
            for indice, secao in ((0, Secao.PAINEL_A), (1, Secao.PAINEL_B))
            if _nomeia_o_diretorio(lente.codigo, paineis[indice])
        }
    )
    leitura = ler_sinais(
        sessao,
        lente,
        alvo,
        meses,
        calibracao,
        limites=regua_dos_sinais(calibracao),
        nome_do_painel_a=paineis[0].titulo,
        nome_do_painel_b=paineis[1].titulo,
        secoes_a_omitir=escondidos,
        filtro=filtro,
    )
    onde = {
        Secao.EVOLUCAO: "Evolução",
        Secao.PAINEL_A: paineis[0].titulo,
        Secao.PAINEL_B: paineis[1].titulo,
        Secao.GERAL: "Lente",
    }

    return DossieSaida(
        codigo=lente.codigo,
        nome=lente.nome,
        stakeholder=lente.stakeholder,
        mes=f"{alvo:%Y-%m}",
        nota=medida.score,
        ns=round(medida.ns, 4) if medida.ns is not None else None,
        delta=delta,
        delta_versus=delta_versus,
        recorte_filtrado=filtro.ativo,
        peso=medida.peso,
        estimado=medida.estimado,
        ausencia=medida.ausencia,
        fontes=list(medida.fontes),
        formula=_formula(lente.codigo, calibracao),
        kpis=_kpis(sessao, lente, alvo, meses, calibracao, medida, filtro),
        ficha_do_destaque=_saida_da_ficha(FICHA_DO_DESTAQUE),
        manchete=leitura.manchete,
        # IMPRENSA E SOCIEDADE JÁ SAEM COM A PRÓPRIA CONCLUSÃO (sobre matéria,
        # não sobre nota) — ver o comentário em `_evolucao`. Sobrescrevê-la
        # aqui reintroduziria a mesma frase da manchete em cima do gráfico de
        # contagem. Mercado, Clientes e Institucional continuam herdando o
        # sinal mais forte do período, como sempre.
        evolucao=(
            evolucao
            if lente.codigo in ("imprensa", "sociedade")
            else _com_conclusao(evolucao, leitura.titulo_da_evolucao)
        ),
        sinais_da_evolucao=leitura.sinais_da_evolucao,
        volume_por_tier=volume_por_tier,
        top_veiculos=top_veiculos,
        clima_por_veiculos=clima_por_veiculos,
        drivers_e_riscos=drivers,
        temas_mais_falados=temas_falados,
        materias_recentes=materias,
        fatos=[
            FatoSaida(mes=f"{fato.mes:%Y-%m}", texto=fato.texto, efeito=fato.efeito)
            for fato in repositorio_score.fatos_do_periodo(sessao, meses)
        ],
        onde_esta_a_causa=causa,
        paineis=[
            _com_conclusao(bloco, titulo)
            for secao, bloco, titulo in (
                (Secao.PAINEL_A, paineis[0], leitura.titulo_do_painel_a),
                (Secao.PAINEL_B, paineis[1], leitura.titulo_do_painel_b),
            )
            if secao not in escondidos
        ],
        sinais=[
            SinalSaida(
                tipo=sinal.tipo,
                frase=sinal.frase,
                evidencia=sinal.evidencia,
                onde=onde[sinal.secao],
                tom=sinal.tom.value,
            )
            for sinal in leitura.lista
            # REDUNDANTE DE PROPÓSITO. `ler_sinais` já descartou estes sinais na
            # origem, e é lá que a correção mora. Esta linha custa nada e recusa
            # o payload caso alguém chame a leitura sem `secoes_a_omitir` — o
            # jeito exato como a manchete vazou na primeira tentativa.
            if sinal.secao not in escondidos
        ],
    )


class PassoDaTrilha(BaseModel):
    """Um degrau do caminho que levou até este recorte."""

    #: A chave do parâmetro (`uf`), para a tela saber o que remover ao subir.
    chave: str
    #: O nome da dimensão como a pessoa a leu na aba (`UF`).
    dimensao: str
    valor: str


class RecorteSaida(BaseModel):
    """O nível 3: um pedaço do mês, medido e decomposto.

    UM PEDIDO SÓ, de propósito. O drawer abre com tudo ou abre mentindo — e
    cinco chamadas dariam cinco estados de carregamento dentro de um painel de
    600px, cada um aparecendo e sumindo na frente de quem só clicou numa barra.
    """

    lente: str
    mes: str
    #: O caminho até aqui, na ordem em que a lente se explica. Vazio no recorte
    #: que é o mês inteiro (os cartões do topo abrem assim).
    trilha: list[PassoDaTrilha] = Field(default_factory=list)

    #: A nota que este pedaço teria se fosse o mês — é o número que a tela já
    #: mostrava quando o recorte era aplicado na tela inteira.
    nota: int | None
    #: Quantos pontos ele tira ou põe na nota da lente. VER `impacto_do_recorte`:
    #: o denominador é o do mês, e é isso que faz a soma dos pedaços fechar com
    #: `nota − 50`.
    impacto: float
    #: Positivo/neutro/negativo CONTADOS um a um — o que a barra desenha. Não é o
    #: ponderado da nota: a barra mostra volume, e volume se conta.
    composicao: dict[str, int]
    itens: int
    #: O total do mês, para a frase dizer "4 dos 6 itens" em vez de "4 itens".
    itens_no_mes: int
    #: A frase pronta, calculada a cada leitura — nunca salva.
    frase: str
    ausencia: str | None = None

    #: Seis células: o mesmo recorte mês a mês. Responde "isto é de agora ou é
    #: sempre assim", que é a pergunta que decide se o pedaço merece ação.
    historico: list[dict] = Field(default_factory=list)
    #: As dimensões AINDA NÃO USADAS, cortadas dentro deste recorte. Clicar numa
    #: linha empilha mais um degrau — é descer no mesmo painel.
    dentro: list[BlocoSaida] = Field(default_factory=list)
    #: A lista que fecha a descida: os itens deste recorte.
    itens_do_recorte: BlocoSaida


@rotas.get("/{codigo}/recorte")
def obter_recorte(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
) -> RecorteSaida:
    """O nível 3 do pacote: o que o drawer abre quando alguém clica num dado.

    POR QUE NÃO BASTAVA O RECORTE NA TELA INTEIRA — e esta foi a correção que o
    dono do produto pediu com estas palavras: "ao clicar em um dado temos que
    abrir um modal com o deep diving, e não como é feito hoje". Aplicar o filtro
    na tela inteira REFAZ o mês: a nota muda, os painéis se refazem, e quem
    clicou perde de vista o mês de onde saiu. É recortar, não aprofundar. O
    drawer põe o pedaço AO LADO do mês, com a trilha de volta.

    OS MESMOS PARÂMETROS DO DOSSIÊ, e isso não é repetição preguiçosa: é o que
    faz um link reproduzir o ponto exato do caminho, e o que permite a mesma
    barra de filtros e o mesmo clique levarem ao mesmo lugar.
    """
    alvo = _mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")

    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        autor=autor,
        empresa=empresa,
    )
    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_lentes.meses_ate(alvo, MESES_DA_EVOLUCAO)
    trilha = _trilha_do_recorte(lente.codigo, filtro)

    #: A LENTE QUE LÊ O CRM NÃO TEM O QUE RECORTAR, e isto foi achado de revisão.
    #: O filtro é de `mencao`; a Institucional conta interações. A resposta
    #: misturava duas contas de universos diferentes: a nota vinha de `mencao`
    #: (zero, porque não há) e a composição e o histórico vinham do CRM INTEIRO,
    #: porque `serie_da_lente` ignora o filtro na lente interna — cada número
    #: certo no seu mundo, e lado a lado se contradizendo sem nada explicando.
    #:
    #: A TRILHA FICA, para a pessoa ver o que pediu e poder desfazer.
    if filtro.ativo and repositorio_lentes.lente_e_interna(sessao, lente.id):
        return RecorteSaida(
            lente=lente.codigo,
            mes=f"{alvo:%Y-%m}",
            trilha=trilha,
            nota=None,
            impacto=0,
            composicao={"positivo": 0, "neutro": 0, "negativo": 0},
            itens=0,
            itens_no_mes=0,
            frase=(
                f"{lente.nome} não vem de menções: ela conta as agendas registradas "
                "no CRM, e este recorte não se aplica a elas."
            ),
            ausencia=(
                f"{lente.nome} lê o CRM dos Stakeholders, e o recorte da tela filtra "
                "menções de planilha. Remova o recorte para ver esta lente."
            ),
            historico=[],
            dentro=[],
            itens_do_recorte=_materias_recentes(sessao, lente, alvo, calibracao, None),
        )

    medida = repositorio_score.medir_uma_lente(sessao, lente, alvo, calibracao, filtro)
    #: MEDIDO UMA VEZ e reusado no histórico — ver `denominador_do_mes`.
    denominador = repositorio_score.denominador_do_mes(sessao, lente.id, alvo, calibracao)
    impacto = repositorio_score.impacto_do_recorte(
        sessao, lente.id, alvo, calibracao, filtro, denominador
    )

    serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao, filtro)
    do_mes = repositorio_lentes.serie_da_lente(sessao, lente.id, [alvo], calibracao, None)
    deste_mes = next((linha for linha in serie if linha["mes"] == alvo), None)
    composicao = {
        "positivo": int(deste_mes["pos"]) if deste_mes else 0,
        "neutro": int(deste_mes["neu"]) if deste_mes else 0,
        "negativo": int(deste_mes["neg"]) if deste_mes else 0,
    }
    itens = sum(composicao.values())
    no_mes = sum(int(do_mes[0][chave]) for chave in ("pos", "neu", "neg")) if do_mes else 0

    #: O HISTÓRICO É O IMPACTO MÊS A MÊS, e não a contagem: a pergunta é "este
    #: pedaço pesava o mesmo antes", e peso se mede em pontos. A contagem vai ao
    #: lado porque um impacto pequeno com muitos itens e um impacto pequeno com
    #: dois itens são situações diferentes.
    #:
    #: A NOTA DO MÊS NÃO SAI DAQUI, e eu já tentei que saísse — duas vezes achado
    #: de revisão, pela mesma razão de fundo: um segundo caminho para o mesmo
    #: número.
    #:
    #: O DONO DO PRODUTO LEU A COLUNA COMO VARIAÇÃO MÊS A MÊS, e ele leu certo o
    #: que a tela mostrava: cada número é a distância da nota daquele mês até 50,
    #: e nada dizia isso. Eu resolvi derivando a nota aqui (`50 + impacto`, que é
    #: identidade exata quando não há recorte) — e a revisão mostrou DOIS furos:
    #:
    #:   arredondamento   `impacto` já vinha com 2 casas, e `round(50 + 35.50)`
    #:                    dá 86 onde `para_score` dá 85
    #:   estimativa       `medir_uma_lente` exclui `score_estimativa` de
    #:                    propósito, então num mês estimado a lente publica nota
    #:                    e este histórico diria "sem base"
    #:
    #: A NOTA OFICIAL JÁ ESTÁ NA TELA: `PontoDaSerie.notas_das_lentes` é o número
    #: que a própria Jornada desenha, mês a mês, estimativa incluída. Medi-lo de
    #: novo aqui custaria `indice_do_mes` oito vezes (cinco lentes por chamada)
    #: para chegar, na melhor das hipóteses, ao mesmo valor. A tela junta os dois;
    #: aqui fica só o que é desta conta — o impacto.
    historico = []
    for linha in serie:
        do_mes = round(
            repositorio_score.impacto_do_recorte(
                sessao,
                lente.id,
                linha["mes"],
                calibracao,
                filtro,
                #: O DO MÊS ALVO JÁ ESTÁ NA MÃO; os outros sete se medem aqui.
                denominador if linha["mes"] == alvo else None,
            ),
            2,
        )
        historico.append(
            {
                "mes": f"{linha['mes']:%Y-%m}",
                "impacto": do_mes,
                "itens": int(linha["pos"] + linha["neu"] + linha["neg"]),
                "sem_base": bool(linha["sem_base"]),
                #: A PONTUAÇÃO DO RECORTE, mês a mês — pedido do dono do produto:
                #: "traga a pontuação, que é mais fácil de comunicar".
                #:
                #: O IMPACTO CONTINUA SENDO A CONTA CERTA para "quanto este pedaço
                #: mexe na nota da lente", e é o número grande do topo do painel.
                #: Mas numa coluna de oito meses ele não se lê: −2,1 ao lado de
                #: +1,0 diz que mexeu para baixo e para cima, e não se o pedaço
                #: está bem ou mal. A nota diz as duas coisas, na escala que todo
                #: mundo na Aegea já usa.
                #:
                #: SÓ COM RECORTE ATIVO, e a divisão é deliberada: sem recorte, o
                #: número certo é o da série que desenha a Jornada (estimativa
                #: incluída), e a tela já o tem. Derivá-lo aqui foi duas vezes
                #: achado de revisão — arredondamento duplo, e "sem base" nos
                #: meses de nota estimada.
                #:
                #: 21 ms PARA OS OITO MESES, medido: a nota de um pedaço não
                #: existe em lugar nenhum senão medindo.
                "nota": (
                    repositorio_score.medir_uma_lente(
                        sessao, lente, linha["mes"], calibracao, filtro
                    ).score
                    if filtro.ativo and not linha["sem_base"]
                    else None
                ),
            }
        )

    return RecorteSaida(
        lente=lente.codigo,
        mes=f"{alvo:%Y-%m}",
        trilha=trilha,
        nota=medida.score,
        impacto=round(impacto, 2),
        composicao=composicao,
        itens=itens,
        itens_no_mes=no_mes,
        frase=_frase_do_recorte(lente, filtro, impacto, composicao, itens, no_mes),
        #: A MESMA AUSÊNCIA DO DOSSIÊ, pela mesma razão: um recorte sem
        #: correspondência tem de DIZER isso, e não cair no mês como se o filtro
        #: não existisse.
        ausencia=medida.ausencia if not itens else None,
        historico=historico,
        dentro=_onde_esta_a_causa(
            sessao,
            lente,
            alvo,
            calibracao,
            filtro,
            ja_usadas=filtro,
            ve_diretorio=usuario.ve_diretorio,
        ),
        itens_do_recorte=_materias_recentes(sessao, lente, alvo, calibracao, filtro),
    )


class OpcoesDeFiltroSaida(BaseModel):
    tiers: list[str]
    veiculos: list[str]
    atributos: list[str]
    temas: list[str]
    #: Os cortes que o padrão Aegea trouxe (0055). VAZIOS na lente que não tem o
    #: campo — a Imprensa não manda perfil do autor —, e é assim que a tela sabe
    #: não oferecer um seletor que não escolhe nada.
    perfis: list[str] = []
    ufs: list[str] = []
    subtemas: list[str] = []
    autores: list[str] = []
    empresas: list[str] = []


@rotas.get("/{codigo}/dossie/opcoes-de-filtro")
def obter_opcoes_de_filtro(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> OpcoesDeFiltroSaida:
    """Os valores que o recorte da tela pode oferecer NESTE mês.

    NÃO É DICIONÁRIO: tier é fechado, mas veículo/atributo/tema são texto
    livre de cada fornecedor — ver `repositorio_lentes.opcoes_de_filtro`.
    """
    alvo = _mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")
    return OpcoesDeFiltroSaida(**repositorio_lentes.opcoes_de_filtro(sessao, lente.id, alvo))
