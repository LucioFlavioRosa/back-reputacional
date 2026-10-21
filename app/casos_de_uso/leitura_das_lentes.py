"""A leitura das lentes: o Dossiê, o Recorte e os blocos que os compõem.

SAÍRAM DE `api/lentes.py` EM 17/10/2026. Eram 30 funções auxiliares e 1.344
linhas DENTRO do módulo de rota — mais da metade das 3.183 linhas que
`docs/ESTRUTURA_E_EXPANSAO.md` §7.1 mediu em auxiliares de rota no projeto
inteiro.

POR QUE ISSO IMPORTAVA. Nenhuma delas tocava o pedido HTTP: todas recebiam
`(sessao, lente, mes, calibracao, filtro)` e devolviam modelo de saída. Mas
morando em `api/`, e privadas, a única forma de perguntar "como está a Imprensa
este mês?" era fazer um pedido HTTP com sessão de navegador. O painel vai
ganhar mais automações de leitura, geração de texto por IA e uma segunda
interface — e as três querem exatamente esta leitura.

AS 14 QUE A ROTA CHAMA SÃO PÚBLICAS; as 16 que só servem a elas continuam
privadas. A diferença não é estilo: `tests/test_as_camadas_sao_respeitadas.py`
recusa que um módulo importe nome privado de outro, e com razão — `_nome` diz
"não me use de fora", e a rota agora é de fora.
"""

from __future__ import annotations

from datetime import date

from app.banco import repositorio_lentes, repositorio_score

#: A coluna em si, para pedir a contagem de um valor específico ao
#: repositório — ver `quantas_com`.
from app.banco.tabelas_score import Mencao
from app.dominio import frases_de_sinais as frases
from app.dominio.causa_da_lente import (
    DIMENSOES_DO_APROFUNDAMENTO,
    DIMENSOES_POR_LENTE,
    ROTULO_DA_DIMENSAO,
    dimensoes_do_aprofundamento,
)
from app.dominio.lentes import (
    Conceito,
    Ficha,
    Procedencia,
    TaxaDeResposta,
    prioridade_do_jornalista,
)
from app.dominio.score import Calibracao, FiltroDeMencoes
from app.esquemas.lentes import (
    BlocoSaida,
    ColunaSaida,
    ConceitoSaida,
    FichaSaida,
    KpiSaida,
    PassoDaTrilha,
)

# -- as fichas que se repetem ---------------------------------------------------

CONCEITO_NS = Conceito(
    termo="NS (saldo de sentimento)",
    texto=(
        "(propositivas − reativas) ÷ total. Vai de −1 a 1 e vira nota de 0 a 100 "
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


def saida_da_ficha(ficha: Ficha) -> FichaSaida:
    return FichaSaida(
        origem=str(ficha.origem),
        fonte=ficha.fonte,
        colunas=list(ficha.colunas),
        lacunas=list(ficha.lacunas),
        exemplo=ficha.exemplo,
        conceitos=[ConceitoSaida(termo=c.termo, texto=c.texto) for c in ficha.conceitos],
    )


SENTIMENTO = ["Propositivo", "Neutro", "Reativo"]


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
    "Temas × termômetro": "tema",
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
        ficha=saida_da_ficha(ficha),
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
    """De onde veio o dado deste bloco — o rodapé de procedência da ficha.

    A FONTE INTERNA APOSENTADA SAI DA FRASE, e as de planilha ficam. É a mesma
    assimetria de `lente_e_interna`, pela mesma razão: o histórico de uma fonte
    de planilha aposentada continua gravado em `score_mes_fonte` e continua
    dentro do número, então nomeá-la é dizer a verdade; a interna é recontada a
    cada leitura, e aposentada ela não contribui com nada. Depois da `0108`, a
    ficha da Institucional dizia "CRM dos Stakeholders · Clipei · imprensa
    institucional" sobre um dado em que o CRM não tem parte nenhuma.
    """
    fontes = [
        fonte
        for fonte in repositorio_lentes.fontes_da_lente(sessao, lente_id)
        if fonte.ativo or not fonte.interna
    ]
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


def evolucao(
    sessao,
    lente,
    alvo: date,
    meses,
    calibracao: Calibracao,
    conclusao: str | None,
    filtro: FiltroDeMencoes | None = None,
) -> BlocoSaida:
    """A série mensal de matérias, por sentimento.

    O MERCADO CAI AQUI, e antes ele saía por cima com o eventograma. Era a mesma
    premissa que o barrava nos blocos de veículo: tratá-lo como lente sem menção
    ingerida. Ele tem — 216 menções em agosto e 111 em setembro, e a Imprensa
    cobre exatamente os mesmos dois meses.

    O EVENTOGRAMA SAIU DA TELA, por decisão do dono do produto (11/10/2026).
    Ele era a Evolução desta lente; virou um bloco à parte quando a série
    entrou, e depois foi retirado.

    O QUE SAIU COM ELE, porque alguém vai perguntar: dos 15 eventos, os 5 de
    rating seguem no painel "Trajetória de rating" (mesma tabela, filtrada por
    tipo); os outros 10 não aparecem mais em lugar nenhum, e com eles sai a
    cobertura de fevereiro a julho — esta série começa em agosto. A tabela
    `evento_mercado` continua no banco, intacta.
    """
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

    #: PELO CADASTRO, E NÃO PELO CÓDIGO DA LENTE — achado de revisão. "Clima em
    #: vez de sentimento" é consequência de a lente se ler do CRM, e quem sabe
    #: disso é `lente_e_interna`. Com o código escrito aqui, a Institucional
    #: continuaria com a legenda de clima depois da `0108`, que a fez ler
    #: menções: a legenda diria "Proativo/Reativo" sobre barras de matérias.
    interna = repositorio_lentes.lente_e_interna(sessao, lente.id)
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
        "Evolução das matérias" if not interna else "Termômetro das agendas, mês a mês",
        _serie_em_blocos(serie),
        Ficha(
            origem=Procedencia.CRM if interna else Procedencia.PLANILHA,
            fonte="CRM dos Stakeholders" if interna else _nomes_das_fontes(sessao, lente.id),
            colunas=("Data", "Termômetro") if interna else ("Data", "Sentimento"),
            conceitos=(CONCEITO_NS,),
        ),
        conclusao,
        legenda,
        cores=cores,
    )


def paineis(
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
                    #: "do Balanço Reputacional" por extenso: o eventograma
                    #: deixou de ser um bloco da tela (11/10/2026), e dizer só
                    #: "no eventograma" mandaria a pessoa procurar um gráfico
                    #: que não existe mais. A fonte é o documento.
                    fonte="Ações de rating do eventograma do Balanço Reputacional",
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
    # A LENTE INTERNA LÊ DE OUTRO LUGAR. A fonte dela são agendas registradas, e
    # não menções ingeridas. Rodar aqui as consultas de `mencao` devolveria zero,
    # e zero numa tela se lê como "não houve", nunca como "está noutro lugar".
    #
    # PELO CADASTRO, E NÃO PELO CÓDIGO: a Institucional deixou de ser interna na
    # `0108`. Com o código escrito aqui, ela ficaria com os painéis do CRM sobre
    # uma nota que passou a vir de matérias.
    interna = repositorio_lentes.lente_e_interna(sessao, lente.id)

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
            "Temas × termômetro" if interna else "Temas × sentimento",
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


def onde_esta_a_causa(
    sessao,
    lente,
    mes: date,
    calibracao: Calibracao,
    filtro: FiltroDeMencoes | None = None,
    ja_usadas: FiltroDeMencoes | None = None,
    ve_diretorio: bool = True,
    aprofundamento: bool = False,
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

    O AUTOR NÃO É DIRETÓRIO, e a distinção é a mesma que `nomeia_o_diretorio`
    faz: `ve_diretorio` guarda o CADASTRO de terceiros (a matriz de jornalistas,
    os órgãos do CRM), não o nome que veio dentro da menção. O indicador "Autor
    mais negativo" já publica o perfil que mais pesou, pela mesma razão.
    """
    cortes = repositorio_lentes.cortes_da_causa(
        sessao,
        lente.codigo,
        lente.id,
        mes,
        calibracao,
        filtro,
        ve_diretorio=ve_diretorio,
        #: NO PAINEL DE APROFUNDAMENTO, as abas próprias da lente (na Imprensa,
        #: N1 › N2 › N3); no cartão da Síntese, as de sempre.
        dimensoes=(
            dimensoes_do_aprofundamento(lente.codigo, ve_diretorio) if aprofundamento else None
        ),
    )
    #: DENTRO DE "UF: RJ" NÃO SE OFERECE UF DE NOVO, e é esta linha que faz o
    #: empilhamento ter fim: a dimensão já usada daria uma única barra de 100% e
    #: repetiria a pergunta que acabou de ser respondida.
    if ja_usadas is not None:
        usadas = {passo.chave for passo in trilha_do_recorte(lente.codigo, ja_usadas)}
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


def trilha_do_recorte(codigo_da_lente: str, filtro: FiltroDeMencoes) -> list[PassoDaTrilha]:
    """O caminho até este recorte, na ordem em que a lente se explica.

    A TRILHA É O QUE IMPEDE O DRAWER DE SER UM BECO: sem ela, quem desceu dois
    níveis não sabe de onde veio nem o que remover para subir um.

    A ORDEM É A DO DOMÍNIO, e não a dos cliques: a ordem dos cliques não viaja
    numa URL (`?uf=RJ&perfil_autor=Cidadão` é o mesmo conjunto de qualquer jeito),
    e uma trilha que mudasse de forma conforme o caminho tomado faria dois links
    para o mesmo recorte se lerem como recortes diferentes.
    """
    valores = {
        "tema_n1": filtro.tema_n1,
        "tema_n2": filtro.tema_n2,
        "tema_n3": filtro.tema_n3,
        "tema": filtro.tema_texto,
        "subtema": filtro.subtema,
        "empresa": filtro.empresa,
        "veiculo": filtro.veiculo,
        "perfil_autor": filtro.perfil_autor,
        "autor": filtro.autor,
        "uf": filtro.uf,
        "tier": filtro.tier,
        "atributo": filtro.atributo,
        "sentimento": filtro.sentimento,
    }
    #: PRIMEIRO AS DA LENTE, NA ORDEM DELA; depois TODAS as outras que o filtro
    #: aceita, na ordem do dicionário de rótulos.
    #:
    #: ACHADO DE REVISÃO: eu apensava tier e atributo à mão — as duas que me
    #: vieram à cabeça. `subtema` na Imprensa, `empresa` em qualquer lente cuja
    #: lista não a traga: aplicados pelo servidor e invisíveis na trilha. Um
    #: degrau invisível não dá para remover.
    #: A TAXONOMIA PRIMEIRO, quando a lente desce por ela (N1 › N2 › N3): é a
    #: sequência que o painel de aprofundamento oferece, e a trilha se lê igual.
    proprias = DIMENSOES_DO_APROFUNDAMENTO.get(codigo_da_lente, ())
    do_cartao = DIMENSOES_POR_LENTE.get(codigo_da_lente, ())
    da_lente = list(dict.fromkeys(d.chave for d in (*proprias, *do_cartao)))
    ordem = da_lente + [chave for chave in ROTULO_DA_DIMENSAO if chave not in da_lente]
    rotulos = {d.chave: d.rotulo for d in (*do_cartao, *proprias)}
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


def frase_do_recorte(
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
        f"com {quantos} itens do mês e {negativas}% de reativas."
    )


def nomeia_o_diretorio(lente_e_interna: bool, bloco: BlocoSaida) -> bool:
    """Este painel publica NOME de gente ou de instituição de fora?

    É a pergunta que separa o que `ve_diretorio` guarda do que ele não guarda, e
    ela não se responde pelo tipo do bloco: `barras_horizontais` serve tanto
    "Órgãos com mais interações" — os mesmos nomes que `GET /api/instituicoes`
    recusa a este papel — quanto "Concessionárias com maior repercussão", que é
    unidade de negócio da própria Aegea e não é cadastro de terceiro. Gatilhar
    pelo tipo esconderia da lente errada um dado que é da casa.

    E NÃO SE RESPONDE PELO CÓDIGO DA LENTE — achado de revisão. A pergunta era
    "é a Institucional?", porque ali o bloco horizontal era o de órgãos. Depois
    da `0108` o bloco horizontal DELA é "Concessionárias com maior
    repercussão", que é dado da casa: quem não vê o diretório perdia um painel
    por uma regra de privacidade que não tinha mais o que proteger. Quem
    responde é a procedência — o painel de órgãos só existe na lente interna.
    """
    if bloco.tipo == "matriz_prioridade":
        return True
    return lente_e_interna and bloco.tipo == "barras_horizontais"


#: As cores do tier, na mesma paleta oficial da Aegea que o resto do produto
#: usa — nunca uma cor inventada para preencher uma fatia da rosca.
_CORES_DO_TIER = {
    "muito_relevante": "#0027BD",  # Azul Mar
    "relevante": "#17E3CB",  # Turquesa Rio
    "menos_relevante": "#A11FFF",  # Roxo Açaí
}


#: AS LENTES QUE TÊM VEÍCULO E TIER DE VERDADE — e portanto os três blocos de
#: veículo do dossiê: a rosca de volume por tier, o par top/termômetro por
#: veículo, e a lista de últimas matérias.
#:
#: ERA SÓ A IMPRENSA, e a restrição era de TELA: o Jones (2026-10-02) não quis
#: ver "os mesmos veículos e tiers repetidos em Imprensa e Mercado". A decisão
#: ficou escrita com a condição de revisão junto — "se um dia o recorte por
#: público-alvo virar outro veículo/tier na prática (ex.: fontes econômicas
#: específicas), vale revisitar".
#:
#: A CONDIÇÃO SE CUMPRIU, e é medida, não impressão. Na base de hoje:
#:
#:   ZERO dos 10 maiores veículos do Mercado estão no top 10 da Imprensa
#:   Valor Econômico  — 1º no Mercado,   95º na Imprensa
#:   Expert XP        — 3º no Mercado,  333º na Imprensa
#:   InfoMoney        — 5º no Mercado,  419º na Imprensa
#:   Acionista        — 10º no Mercado, 634º na Imprensa
#:
#:   o top da Imprensa é rádio local (Rádio Betel 87.9 FM, 1.451 menções);
#:   o do Mercado é imprensa econômica, inteiro
#:
#:   e o tier quase se inverte: 46,2% muito_relevante no Mercado contra 10,7%
#:   na Imprensa, que tem 72,7% em menos_relevante
#:
#: Ou seja: os dois gráficos lado a lado não repetem nada. Era o recorte por
#: público-alvo Investidores (migration 0048) virando fonte econômica de fato.
#:
#: SOCIEDADE E CLIENTES FICAM FORA, e por razões DIFERENTES — vale dizer qual,
#: porque eu já errei essa frase duas vezes:
#:
#:   Clientes não tem menção nenhuma. Nada a mostrar.
#:
#:   Sociedade TEM `veiculo` (2.582 menções, 1.103 valores) e ZERO tier. Mas o
#:   que ela guarda ali é perfil e rede — "deolhoemesteio", "Stela Farias" —,
#:   não veículo de imprensa. Ranquear isso como "Top veículos", ao lado de
#:   tier, diria algo errado sobre o dado. Ver `_lacuna_do_veiculo`, que é o que
#:   explica isso para quem está na tela.
#:
#: A Institucional fica fora por vir do CRM, e isso é conferido à parte
#: (`lente_e_interna`), porque a mensagem é outra.
LENTES_COM_VEICULO_E_TIER = ("imprensa", "mercado")


def _lacuna_do_veiculo(codigo: str) -> str:
    """Por que ESTA lente não tem o ranking de veículos — e a frase tem de ser
    verdadeira sobre ela, não genérica.

    ACHADO DE REVISÃO, e o erro foi meu duas vezes: a frase original era "por
    ora esta tela só mostra veículo na lente Imprensa", que virou mentira no dia
    em que o Mercado entrou. Troquei por "esta lente não traz veículo na carga",
    e essa é FALSA para a Sociedade: medido, ela traz 2.582 menções com veículo,
    em 1.103 valores distintos.

    O QUE A SOCIEDADE TRAZ NÃO É VEÍCULO DE IMPRENSA: é perfil ou rede —
    "deolhoemesteio", "casadevovodede", nomes de pessoas. O campo é o mesmo, o
    conceito não, e `DIMENSOES_POR_LENTE` já a chama de "Rede". Ranquear isso
    como "Top veículos", ao lado de tier, diria algo errado sobre o dado.
    """
    if codigo == "sociedade":
        return (
            "Nesta lente o campo do veículo guarda o perfil ou a rede, não um "
            "veículo de imprensa — ele aparece como Rede, em Onde está a causa."
        )
    return "Esta lente não traz veículo na carga."


def volume_por_tier(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """A rosca de volume por tier — mesmo desenho de "% Interações por tier"
    do Painel (CRM), com matéria no lugar de interação.

    REAPROVEITA `composicao_por_tier`, a mesma consulta do painel "Tier do
    veículo × sentimento": a rosca só soma os três sentimentos de cada tier,
    não pede nada que aquela consulta já não traga.

    IMPRENSA E MERCADO — ver `LENTES_COM_VEICULO_E_TIER`, onde está a medida que
    trouxe o Mercado para cá. Em resumo: os dois gráficos lado a lado não
    repetem nada, porque nenhum dos 10 maiores veículos do Mercado está no top
    10 da Imprensa.
    """
    if lente.codigo not in LENTES_COM_VEICULO_E_TIER:
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
                #: A LACUNA DIZ O MOTIVO, e não "por ora": esta lente não tem o
                #: campo, e isso não muda com o tempo. A frase antiga ("só
                #: mostra tier na lente Imprensa") virou mentira no dia em que
                #: o Mercado entrou — e ninguém a teria revisado.
                lacunas=("Esta lente não traz tier do veículo na carga.",),
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
                #: O SENTIMENTO DE CADA TIER, para a coluna empilhada do card
                #: (quantidade, não 100%) — já vinha na consulta.
                "positivo": linha["positivo"],
                "neutro": linha["neutro"],
                "negativo": linha["negativo"],
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


def veiculos(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> tuple[BlocoSaida, BlocoSaida]:
    """Top veículos por volume, e o placar de clima de cada um — mesmo par
    de "Top 5 instituições" + "Clima por Instituições" do Painel (CRM), por
    veículo em vez de instituição.

    UMA CONSULTA SÓ alimenta os dois blocos: top-por-volume e o saldo de
    sentimento são a mesma soma lida de dois jeitos.

    IMPRENSA E MERCADO — ver `LENTES_COM_VEICULO_E_TIER`.
    """
    if lente.codigo not in LENTES_COM_VEICULO_E_TIER:
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
                lacunas=(_lacuna_do_veiculo(lente.codigo),),
            )
        )
        return (
            _bloco("barras_horizontais", "Top veículos", [], vazio_ficha, None),
            _bloco("divergente_por_item", "Termômetro por veículos", [], vazio_ficha, None),
        )

    veiculos = repositorio_lentes.veiculos_por_sentimento(
        sessao, lente.id, mes, calibracao, filtro, quantos=QUANTOS_VEICULOS_NO_TOPO
    )
    ficha = Ficha(
        origem=Procedencia.PLANILHA,
        fonte=_nomes_das_fontes(sessao, lente.id),
        colunas=("Veículo", "Classificação"),
    )
    top_veiculos = _bloco(
        "barras_horizontais",
        "Top veículos",
        [
            {
                "rotulo": linha["veiculo"],
                "valor": linha["total"],
                "positivo": linha["positivo"],
                "neutro": linha["neutro"],
                "negativo": linha["negativo"],
            }
            for linha in veiculos
        ],
        ficha,
        None,
    )
    no_termometro = veiculos[:QUANTOS_VEICULOS_NO_TERMOMETRO]
    # MESMO CÁLCULO DO PAINEL (CRM): (positivas − negativas) ÷ total × 100,
    # de −100 a 100 — não é o NS oficial do Score (que pondera por tier e vai
    # de 0 a 100). É o placar simples que a diretoria já conhece de lá.
    clima_por_veiculos = _bloco(
        "divergente_por_item",
        "Termômetro por veículos",
        [
            {
                "chave": linha["veiculo"],
                "rotulo": linha["veiculo"],
                "total": linha["total"],
                "score": round((linha["positivo"] - linha["negativo"]) / linha["total"] * 100),
            }
            for linha in no_termometro
        ],
        ficha,
        None,
    )
    return top_veiculos, clima_por_veiculos


QUANTOS_VEICULOS_TIER1 = 10


def veiculos_tier1(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida | None:
    """Os 10 veículos TIER 1 com mais matérias no mês, com positivo, neutro e
    negativo de cada um — em QUANTIDADE, não 100% (por pedido). Mora embaixo do
    painel "Tier do veículo × sentimento": ele diz como o Tier 1 foi no total,
    este diz quais veículos do Tier 1 formaram isso.

    SÓ ONDE HÁ TIER (`LENTES_COM_VEICULO_E_TIER`); nas outras, nulo.
    """
    if lente.codigo not in LENTES_COM_VEICULO_E_TIER:
        return None
    veiculos = repositorio_lentes.veiculos_por_sentimento(
        sessao,
        lente.id,
        mes,
        calibracao,
        filtro,
        quantos=QUANTOS_VEICULOS_TIER1,
        so_do_tier="muito_relevante",
    )
    return _bloco(
        "barras_horizontais",
        "Top 10 veículos Tier 1",
        [
            {
                "rotulo": linha["veiculo"],
                "valor": linha["total"],
                "positivo": linha["positivo"],
                "neutro": linha["neutro"],
                "negativo": linha["negativo"],
            }
            for linha in veiculos
        ],
        Ficha(
            origem=Procedencia.PLANILHA,
            fonte=_nomes_das_fontes(sessao, lente.id),
            colunas=("Veículo", "Aegea Tier", "Classificação"),
        ),
        None,
    )


def drivers_e_riscos(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """"Drivers e riscos": os atributos reputacionais que mais puxam a lente,
    em volume e sentimento — não só o saldo final que a nota resume.

    SÓ NAS LENTES DE CLIPPING, pelo mesmo motivo de `materias_recentes`: a
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


def temas_mais_falados(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """Os temas (Subcategoria da Clipei) mais falados do mês, por sentimento.

    SÓ NAS LENTES DE CLIPPING — mesma ressalva de `drivers_e_riscos`.
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


_ROTULO_DO_SENTIMENTO = {"pos": "Propositivo", "neu": "Neutro", "neg": "Reativo"}


_ROTULO_DO_TIER_DA_MATERIA = {
    "muito_relevante": "Tier 1",
    "relevante": "Tier 2",
    "menos_relevante": "Tier 3",
}


#: Sem recorte: só uma amostra do mês inteiro. Com recorte (um veículo, um
#: tier...): o universo já é pequeno, então sobe para "praticamente tudo".
TETO_DE_MATERIAS = 5


TETO_DE_MATERIAS_FILTRADO = 30
#: "ÚLTIMAS MATÉRIAS" DA IMPRENSA E DO MERCADO MOSTRAM 15, por pedido: o card
#: rola, e cada linha abre o detalhe da matéria num popup.
TETO_DAS_ULTIMAS_MATERIAS = 15
#: TOP 10 VEÍCULOS no card de tier, por pedido; e o TERMÔMETRO AO LADO também
#: passou a 10 (21/10/2026), para os dois cards terem o mesmo tamanho.
QUANTOS_VEICULOS_NO_TOPO = 10
QUANTOS_VEICULOS_NO_TERMOMETRO = 10


def _mencoes_da_sociedade(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """As menções de rede do mês — o nível do item, nesta lente.

    TODAS ENTRAM NA LISTA, inclusive as sem texto e as sem link. Decisão do dono
    do produto, 13/10/2026, com estas palavras: *"embora não tenha link, só não
    vamos conseguir acessar a página, mas a informação deve estar lá"*.

    ANTES ERAM SÓ AS QUE TINHAM TEXTO, e o motivo de então era real: 86% dos
    itens chegavam sem texto, e cinco linhas de metadado seriam uma lista sem
    nada a ler. A PREMISSA MUDOU — na consolidada da Bites de jan-set/2026,
    2.833 das 2.842 linhas têm texto (99,7%) —, e o que antes era uma lista
    vazia de conteúdo virou a lista vazia de tudo: filtrar por texto escondia a
    menção inteira, com data, autor, perfil, sentimento e engajamento.

    O QUE SEGURA A LEITURA NO TOPO é a ordenação, não a exclusão:
    `repositorio_lentes.materias_recentes` já põe quem tem texto primeiro e, entre
    eles, o maior engajamento. As de metadado ficam abaixo.

    E A LINHA SEM LINK FICA INERTE, não quebrada: o front só dá `onClick` e cursor
    quando o endereço é `http`/`https` (`PecasDoDossie.tsx`) — a mesma conferência
    de esquema que o conserto do `urlSegura` fixou.
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
            #: ZERO É UM NÚMERO, e era virado em nulo pelo `if` truthy —
            #: achado da mesma revisão, na linha de baixo do que ela apontou.
            #: Numa menção de rede, engajamento zero diz "ninguém reagiu";
            #: célula vazia diz "não se sabe". São coisas diferentes, e a
            #: segunda é a que a planilha significa quando não traz a coluna.
            "engajamento": _num(linha["engajamento"])
            if linha["engajamento"] is not None
            else None,
            "link": linha["link"],
        }
        for linha in repositorio_lentes.materias_recentes(
            sessao, lente.id, mes, calibracao, filtro, quantas=quantas
        )
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
                #
                # A FRASE MUDOU COM A REGRA: dizia que as demais "não têm o que
                # mostrar aqui", e isso deixou de ser verdade quando elas
                # passaram a entrar na lista.
                #
                # E NÃO PROMETE CAMPO, achado de revisão contra a primeira
                # versão desta frase: ela dizia "com data, autor e engajamento",
                # e os três são nulos possíveis no modelo. Prometer o que o dado
                # pode não ter é o mesmo erro, do outro lado.
                "O texto e o link vêm numa amostra das menções (as reativas, "
                "as de maior alcance e as mais engajadas). As demais aparecem "
                "nesta lista com os metadados que vieram — classificação, "
                "perfil, autor e engajamento quando houver — e não abrem a "
                "página de origem.",
            ),
        ),
        None,
        subtipo="mencoes",
        colunas=COLUNAS_DAS_MENCOES,
        #: O ENDEREÇO SAIU DA GRADE E VIROU O DESTINO DA LINHA — ver
        #: `BlocoSaida.coluna_do_link`. O valor continua em `dados`.
        coluna_do_link="link",
    )


def materias_recentes(
    sessao, lente, mes: date, calibracao: Calibracao, filtro: FiltroDeMencoes | None = None
) -> BlocoSaida:
    """O drill-down até a linha: as matérias mais recentes por trás da nota.

    IMPRENSA E MERCADO — ver `LENTES_COM_VEICULO_E_TIER`. As colunas desta
    tabela ("Veículo", "Aegea Tier") são as mesmas duas que a medida de lá
    justifica.

    A SOCIEDADE TEM LISTA PRÓPRIA, e por razão diferente: as colunas de clipping
    não dizem nada de um post, mas a carga do padrão trouxe o que uma menção de
    rede precisa — o texto, o link, quem escreveu e o engajamento. Ela ganha a
    lista com as colunas DELA (`_mencoes_da_sociedade`). Clientes e
    Institucional seguem sem lista, por não terem o campo.
    """
    if lente.codigo == "sociedade":
        return _mencoes_da_sociedade(sessao, lente, mes, calibracao, filtro)

    if lente.codigo not in LENTES_COM_VEICULO_E_TIER:
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
                #: A Sociedade NÃO chega aqui (tem lista própria, logo
                #: acima); quem chega é Clientes, que não vem de clipping.
                lacunas=("Esta lente não traz matéria de clipping na carga.",),
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
    quantas = (
        TETO_DE_MATERIAS_FILTRADO if filtro and filtro.ativo else TETO_DAS_ULTIMAS_MATERIAS
    )
    linhas = [
        {
            "quando": f"{linha['data']:%d/%m}" if linha["data"] else None,
            "veiculo": linha["veiculo"],
            "sentimento": _ROTULO_DO_SENTIMENTO.get(linha["sentimento"], linha["sentimento"]),
            "tier": _ROTULO_DO_TIER_DA_MATERIA.get(linha["tier"], linha["tier"]),
            "atributo": linha["atributo"],
            "tema": linha["tema"],
            #: O ENDEREÇO VAI NA LINHA, NÃO NA GRADE — mesma escolha da
            #: Sociedade: `coluna_do_link` abaixo faz a linha inteira virar o
            #: destino, e `link` não está em `COLUNAS_DAS_MATERIAS`, então não
            #: aparece como coluna. Pedido do dono do produto: "não precisa
            #: trazer o link na página, apenas que o registro seja clicável".
            #:
            #: A CONSULTA JÁ TRAZIA O CAMPO para todas as lentes (é a mesma
            #: `materias_recentes` que serve a Sociedade); só esta montagem o
            #: descartava.
            "link": linha["link"],
            #: O DETALHE DO POPUP, por pedido — fora da grade (não estão em
            #: `COLUNAS_DAS_MATERIAS`), só no `dados` que a tela abre ao clicar.
            "data": f"{linha['data']:%Y-%m-%d}" if linha["data"] else None,
            "texto": linha["titulo_texto"],
            "autor": linha["autor"],
            "uf": linha["uf"],
            "engajamento": _num(linha["engajamento"])
            if linha["engajamento"] is not None
            else None,
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
        #: CLICAR NA LINHA ABRE A MATÉRIA, como na Sociedade. Medido: 100% das
        #: menções têm link nas três lentes, então nenhuma linha fica sem
        #: destino.
        coluna_do_link="link",
    )


def kpis(
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

    #: OS KPIs DO CRM SÃO ESCOLHIDOS PELO CADASTRO — achado de revisão. Eles
    #: dizem "Agendas no período" e "Termômetro propositivo/tenso", que é a
    #: semântica da fonte interna; depois da `0108` a Institucional mede
    #: matérias, e manter a escolha pelo código da lente poria rótulo de agenda
    #: sobre contagem de clipping. A pergunta certa é de onde o número vem.
    if repositorio_lentes.lente_e_interna(sessao, lente.id):
        return _kpis_do_institucional(serie, do_mes, total)
    if lente.codigo in ("imprensa", "institucional"):
        #: A INSTITUCIONAL USA OS KPIs DA IMPRENSA, que é o que ela passou a
        #: ser: clipping recortado, medido em matérias e tiers.
        return _kpis_da_imprensa(
            sessao, lente, meses, calibracao, serie, com_base, do_mes, total, filtro
        )
    if lente.codigo == "mercado":
        return _kpis_do_mercado(sessao, mes, meses)
    if lente.codigo == "clientes":
        return _kpis_dos_clientes(sessao, lente, alvo, meses, calibracao)
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
            rotulo="Propositivas ou neutras",
            valor=_pct((positivas + neutras) / total if total else None),
            detalhe=f"{_num(positivas)} propositivas",
        ),
        KpiSaida(
            rotulo="Pico reativo",
            valor=_num(pico["neg"]) if pico and pico["neg"] else "—",
            detalhe=f"{pico['mes']:%Y-%m}" if pico and pico["neg"] else "sem reativa",
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
            rotulo="Termômetro propositivo",
            valor=_pct(do_mes["pos"] / no_mes if no_mes else None),
            detalhe=f"{_num(do_mes['pos'])} agendas" if do_mes else "sem base",
        ),
        KpiSaida(
            rotulo="Termômetro tenso",
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
            rotulo="Autor mais reativo",
            valor=autores[0]["autor"] if autores else "—",
            detalhe=(
                f"{_num(autores[0]['negativo'])} menções reativas"
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
            rotulo="UF mais reativa",
            valor=mais_negativa["uf"] if mais_negativa else "—",
            detalhe=(
                f"{_num(mais_negativa['negativo'])} menções reativas"
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


def com_conclusao(bloco: BlocoSaida, frase: str | None) -> BlocoSaida:
    """O título-conclusão do bloco, quando o detector tem algo a dizer.

    NÃO REPETE O NOME DO PRÓPRIO BLOCO. Sem sinal naquela seção, a §3 manda
    usar o nome do painel — que a tela já mostra no título logo acima. Copiá-lo
    para a conclusão desenharia a mesma frase duas vezes, uma embaixo da outra.
    """
    if not frase or frase == bloco.titulo:
        return bloco
    return bloco.model_copy(update={"conclusao": frase})
