"""O dossiê de uma lente, pronto para a tela.

UM ENDPOINT, UMA TELA. A regra 2 do pacote: o front não calcula. Ele recebe a
nota, os KPIs, a série, os dois painéis, o texto e os encaminhamentos já
montados — e só decide cor, ordem e tamanho.

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
from app.dominio.erros import NaoEncontrado
from app.dominio.lentes import (
    Conceito,
    Ficha,
    Numeros,
    Procedencia,
    TaxaDeResposta,
    prioridade_do_jornalista,
    rascunho_automatico,
)
from app.dominio.score import Calibracao

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


class BlocoSaida(BaseModel):
    """Um gráfico ou quadro, com o tipo que a tela deve desenhar."""

    tipo: str
    titulo: str
    #: O título-conclusão da curadoria — a frase que o gráfico prova.
    conclusao: str | None = None
    dados: list[dict] = Field(default_factory=list)
    #: Como se chamam as três faixas NESTE bloco. A lente institucional mede
    #: clima (propositivo/neutro/tenso) e as outras medem sentimento — e a tela
    #: não pode descobrir isso adivinhando pelo título.
    legenda: list[str] = Field(default_factory=list)
    ficha: FichaSaida


class KpiSaida(BaseModel):
    rotulo: str
    valor: str
    detalhe: str | None = None


class FatoSaida(BaseModel):
    mes: str
    texto: str
    efeito: str


class EncaminhamentoSaida(BaseModel):
    id: str
    acao: str
    responsavel: str | None
    prazo: str | None
    status: str
    mes_origem: str
    exemplo: bool


class CuradoriaSaida(BaseModel):
    """O texto da lente, e de quem ele é.

    `automatica` é o que impede a frase gerada de ser citada como leitura
    editorial: a tela mostra o selo, e quem lê sabe que ninguém escreveu aquilo.
    """

    manchete: str | None
    leitura: list[str] = Field(default_factory=list)
    revela: list[dict] = Field(default_factory=list)
    status: str
    automatica: bool
    exemplo: bool


class DossieSaida(BaseModel):
    codigo: str
    nome: str
    stakeholder: str
    mes: str

    #: A nota da lente e a variação — vêm do índice, sem recálculo.
    nota: int | None
    ns: float | None
    delta: int | None
    peso: int
    estimado: bool
    ausencia: str | None
    fontes: list[str] = Field(default_factory=list)
    formula: str

    kpis: list[KpiSaida] = Field(default_factory=list)
    evolucao: BlocoSaida
    fatos: list[FatoSaida] = Field(default_factory=list)
    paineis: list[BlocoSaida] = Field(default_factory=list)
    curadoria: CuradoriaSaida
    encaminhamentos: list[EncaminhamentoSaida] = Field(default_factory=list)


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
        "A relevância do veículo na escala da própria clipagem: Muito "
        "Relevante (imprensa nacional e econômica), Relevante (regionais com "
        "influência) e Menos Relevante (locais e blogs de nicho)."
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
        conceitos=[
            ConceitoSaida(termo=c.termo, texto=c.texto) for c in ficha.conceitos
        ],
    )


SENTIMENTO = ["Positivo", "Neutro", "Negativo"]
CLIMA = ["Propositivo", "Neutro", "Tenso"]


def _bloco(
    tipo: str,
    titulo: str,
    dados: list[dict],
    ficha: Ficha,
    conclusao: str | None,
    legenda: list[str] | None = None,
) -> BlocoSaida:
    return BlocoSaida(
        tipo=tipo,
        titulo=titulo,
        conclusao=conclusao,
        dados=dados,
        legenda=legenda or [],
        ficha=_saida_da_ficha(ficha),
    )


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
        }
        for linha in serie
    ]


def _evolucao(
    sessao, lente, meses, calibracao: Calibracao, conclusao: str | None
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

    serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao)
    if lente.codigo == "clientes":
        recebidas = repositorio_lentes.recebidas_por_mes(
            sessao, lente.id, meses, calibracao
        )
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
    return _bloco(
        "barras_empilhadas",
        "Evolução mensal" if not interna else "Clima das agendas, mês a mês",
        _serie_em_blocos(serie),
        Ficha(
            origem=Procedencia.CRM if interna else Procedencia.PLANILHA,
            fonte="CRM dos Stakeholders" if interna else _nomes_das_fontes(sessao, lente.id),
            colunas=("Data", "Clima") if interna else ("Data", "Sentimento"),
            conceitos=(CONCEITO_NS,),
        ),
        conclusao,
        CLIMA if interna else SENTIMENTO,
    )


def _paineis(
    sessao, lente, mes: date, meses, calibracao: Calibracao, curadoria
) -> list[BlocoSaida]:
    """Os dois painéis de cada lente, na ordem da especificação."""
    titulo_a = getattr(curadoria, "painel_a_titulo", None)
    titulo_b = getattr(curadoria, "painel_b_titulo", None)

    if lente.codigo == "imprensa":
        tiers = repositorio_lentes.composicao_por_tier(sessao, lente.id, mes, calibracao)
        matriz = repositorio_lentes.matriz_de_jornalistas(sessao)
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
                        "rotulo": {
                            "muito_relevante": "Muito Relevante",
                            "relevante": "Relevante",
                            "menos_relevante": "Menos Relevante",
                        }.get(linha["tier"], linha["tier"]),
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
                    lacunas=(
                        ()
                        if estudo
                        else ("Nenhum estudo de percepção cobre este mês.",)
                    ),
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
            ),
        ]

    if lente.codigo == "clientes":
        teor = repositorio_lentes.teor_por_mes(sessao, lente.id, meses, calibracao)
        serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao)
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
                    }
                    for linha in serie
                ],
                _ficha_da_base(
                    _nomes_das_fontes(sessao, lente.id), ("Data", "Sentimento")
                ),
                titulo_a,
                SENTIMENTO,
            ),
            _bloco(
                "tabela",
                "Teor das mensagens",
                [
                    {
                        "mes": f"{linha['mes']:%Y-%m}",
                        "total": linha["total"],
                        "acionaveis": linha["acionaveis"],
                        **linha["teores"],
                    }
                    for linha in teor
                ],
                _ficha_da_base(
                    _nomes_das_fontes(sessao, lente.id),
                    ("TAG (motivo)",),
                    (CONCEITO_ACIONAVEL,),
                ),
                titulo_b,
            ),
        ]

    # Sociedade e Institucional: temas e onde a conversa se concentra.
    #
    # A INSTITUCIONAL LÊ DE OUTRO LUGAR. A fonte dela é interna — são agendas
    # registradas, e não menções ingeridas. Rodar aqui as consultas de `mencao`
    # devolveria zero, e zero numa tela se lê como "não houve", nunca como
    # "está noutro lugar".
    interna = lente.codigo == "institucional"
    if interna:
        temas = repositorio_lentes.temas_do_crm(sessao, meses)
        unidades = repositorio_lentes.orgaos_do_crm(sessao, meses)
    else:
        temas = repositorio_lentes.temas_por_sentimento(
            sessao, lente.id, mes, calibracao
        )
        unidades = repositorio_lentes.unidades_da_lente(
            sessao, lente.id, meses, calibracao
        )
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
            CLIMA if interna else SENTIMENTO,
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


def _kpis(
    sessao, lente, mes: date, meses, calibracao: Calibracao, medida
) -> list[KpiSaida]:
    """Os quatro números do destaque — e eles são DIFERENTES em cada lente.

    A §3 dá a lista de cada uma, e não é capricho: "matérias no ano" responde a
    pergunta da imprensa, e não a de clientes, que quer saber quanto do que
    chegou foi respondido. Quatro KPIs genéricos serviriam a todas e a nenhuma.

    ONDE O DADO NÃO EXISTE, O KPI DIZ "—". Inventar um número parecido para
    encher o quadrante é pior do que deixar a lacuna à vista.
    """
    alvo = repositorio_score.primeiro_dia(mes)
    serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao)
    do_mes = next((linha for linha in serie if linha["mes"] == alvo), None)
    total = sum(linha["pos"] + linha["neu"] + linha["neg"] for linha in serie)
    com_base = [linha for linha in serie if not linha["sem_base"]]

    if lente.codigo == "imprensa":
        return _kpis_da_imprensa(sessao, serie, com_base, do_mes, total)
    if lente.codigo == "mercado":
        return _kpis_do_mercado(sessao, mes, meses)
    if lente.codigo == "clientes":
        return _kpis_dos_clientes(sessao, lente, alvo, meses, calibracao)
    if lente.codigo == "institucional":
        return _kpis_do_institucional(serie, do_mes, total)
    return _kpis_da_sociedade(sessao, lente, alvo, meses, calibracao, serie, do_mes, total)


def _kpis_da_imprensa(sessao, serie, com_base, do_mes, total) -> list[KpiSaida]:
    pico = max(serie, key=lambda linha: linha["neg"], default=None)
    positivas = sum(linha["pos"] for linha in serie)
    neutras = sum(linha["neu"] for linha in serie)
    p1 = [
        pessoa
        for pessoa in repositorio_lentes.matriz_de_jornalistas(sessao)
        if prioridade_do_jornalista(
            pessoa.relevancia, pessoa.exposicao, pessoa.proximidade
        ).nivel
        == 1
    ]
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
            rotulo="Jornalistas P1",
            valor=str(len(p1)),
            detalhe="relacionamento contínuo",
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
            for linha in repositorio_lentes.teor_por_mes(
                sessao, lente.id, [alvo], calibracao
            )
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
            detalhe=(
                f"pico de {_num(pico[1])} em {pico[0]:%Y-%m}" if pico else "sem base"
            ),
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
    unidades = repositorio_lentes.unidades_da_lente(sessao, lente.id, meses, calibracao)
    no_mes = (do_mes["pos"] + do_mes["neu"] + do_mes["neg"]) if do_mes else 0
    return [
        KpiSaida(
            rotulo="Menções no período",
            valor=_num(total),
            detalhe=f"{len([x for x in serie if not x['sem_base']])} meses com base",
        ),
        KpiSaida(
            rotulo="Positivo no mês",
            valor=_pct(do_mes["pos"] / no_mes if no_mes else None),
            detalhe=f"{_num(do_mes['pos'])} menções" if do_mes else "sem base",
        ),
        KpiSaida(
            rotulo="Negativo no mês",
            valor=_pct(do_mes["neg"] / no_mes if no_mes else None),
            detalhe=f"{_num(do_mes['neg'])} menções" if do_mes else "sem base",
        ),
        KpiSaida(
            rotulo="Unidade com mais menções",
            valor=unidades[0]["unidade"] if unidades else "—",
            detalhe=_num(unidades[0]["total"]) if unidades else "sem unidade informada",
        ),
    ]


def _num(valor: int | None) -> str:
    return "—" if valor is None else f"{valor:,}".replace(",", ".")


def _nota(atributo) -> str:
    return "—" if atributo is None else f"{float(atributo.nota):.1f}".replace(".", ",")


def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{round(valor * 100)}%"


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
) -> DossieSaida:
    """A lente inteira: nota, KPIs, evolução, dois painéis, texto e ações."""
    alvo = _mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")

    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_lentes.meses_ate(alvo, MESES_DA_EVOLUCAO)

    medidas = {
        medida.codigo: medida
        for medida in repositorio_score.medir_lentes(sessao, alvo, calibracao)
    }
    anteriores = {
        medida.codigo: medida
        for medida in repositorio_score.medir_lentes(
            sessao, meses[-2] if len(meses) > 1 else alvo, calibracao
        )
    }
    medida = medidas[lente.codigo]
    antes = anteriores.get(lente.codigo)
    delta = (
        medida.score - antes.score
        if medida.score is not None and antes and antes.score is not None
        else None
    )

    # QUEM EDITA VÊ O RASCUNHO; quem só lê, o publicado. É a §7 — publicar
    # existe para separar "estou escrevendo" de "pode citar".
    curadoria = repositorio_lentes.curadoria_vigente(
        sessao, lente.id, alvo, ve_rascunho=usuario.administra_dicionarios
    )
    temas = repositorio_lentes.temas_por_sentimento(
        sessao, lente.id, alvo, calibracao, quantos=1
    )
    if curadoria is None:
        rascunho = rascunho_automatico(
            Numeros(
                nome=lente.nome,
                nota=medida.score,
                delta=delta,
                tema_dominante=temas[0]["tema"] if temas else None,
            )
        )
        saida_da_curadoria = CuradoriaSaida(
            manchete=rascunho.manchete,
            leitura=list(rascunho.leitura),
            revela=[],
            status="rascunho",
            automatica=True,
            exemplo=False,
        )
    else:
        saida_da_curadoria = CuradoriaSaida(
            manchete=curadoria.manchete,
            leitura=list(curadoria.leitura or []),
            revela=list(curadoria.revela or []),
            status=curadoria.status,
            automatica=False,
            exemplo=curadoria.exemplo,
        )

    return DossieSaida(
        codigo=lente.codigo,
        nome=lente.nome,
        stakeholder=lente.stakeholder,
        mes=f"{alvo:%Y-%m}",
        nota=medida.score,
        ns=round(medida.ns, 4) if medida.ns is not None else None,
        delta=delta,
        peso=medida.peso,
        estimado=medida.estimado,
        ausencia=medida.ausencia,
        fontes=list(medida.fontes),
        formula=_formula(lente.codigo, calibracao),
        kpis=_kpis(sessao, lente, alvo, meses, calibracao, medida),
        evolucao=_evolucao(
            sessao,
            lente,
            meses,
            calibracao,
            getattr(curadoria, "evolucao_titulo", None),
        ),
        fatos=[
            FatoSaida(mes=f"{fato.mes:%Y-%m}", texto=fato.texto, efeito=fato.efeito)
            for fato in repositorio_score.fatos_do_periodo(sessao, meses)
        ],
        paineis=_paineis(sessao, lente, alvo, meses, calibracao, curadoria),
        curadoria=saida_da_curadoria,
        encaminhamentos=[
            EncaminhamentoSaida(
                id=str(item.id),
                acao=item.acao,
                responsavel=item.responsavel,
                prazo=item.prazo,
                status=item.status,
                mes_origem=f"{item.mes_origem:%Y-%m}",
                exemplo=item.exemplo,
            )
            for item in repositorio_lentes.encaminhamentos_da_lente(
                sessao, lente.id, alvo
            )
        ],
    )
