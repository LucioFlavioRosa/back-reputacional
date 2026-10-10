"""O Score Executivo — o Índice de Saúde Reputacional, servido pronto.

O CÁLCULO É DO SERVIDOR, e a tela só exibe (regra 4 do handoff). Não é
preferência de arquitetura: o ISR é um número que a diretoria vai citar em
reunião, e ele precisa ser o mesmo para todo mundo, calculado uma vez, com a
régua que a coordenação gravou — e não recomputado em cada navegador com a
versão de código que aquele navegador carregou.

O SCORE NÃO USA O RECORTE DO PAINEL. Ele é mensal e é da organização inteira:
filtrar por frente ou por unidade produziria um "ISR da imprensa" cujo peso de
lente não significa nada. O que se escolhe aqui é o MÊS.

Permissões: ler exige o portal Score (`acessa_score`); mexer na calibração
exige administrar cadastros — é configuração da organização, e muda o número
que todos leem.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.dependencias import (
    UsuarioLogado,
    UsuarioQueAdministraCadastros,
    exigir_portal_score,
)
from app.banco import repositorio_score
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import Lente, ScoreConfig, ScoreFato, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso import ingerir_mencoes
from app.casos_de_uso.ler_sinais_da_lente import regua_dos_sinais
from app.dominio.erros import Conflito, NaoEncontrado, RegraViolada
from app.dominio.ingestao_score import rotulo_do_cargo
from app.dominio.score import (
    REGUAS_DE_ENGAJAMENTO,
    REGUAS_DE_TIER,
    Calibracao,
    Contagem,
    Indice,
    ns,
    para_score,
    pesos_efetivos,
    pesos_exatos,
)
from app.dominio.sinais_da_lente import Limites
from app.dominio.tema_do_mes import TemaDoMes, temas_que_pesaram, temas_que_pesaram_na_lente

rotas = APIRouter(
    prefix="/api/score",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido


class LenteSaida(BaseModel):
    codigo: str
    nome: str
    #: De quem é a lente — "Formadores de opinião", "Investidores e rating".
    #: A lista da Visão geral abre por ele: quem lê o índice pergunta "de quem
    #: é este 37?" antes de perguntar de que fonte ele saiu.
    stakeholder: str
    #: O peso que a calibração gravou — o que a aba Calibração ajusta.
    peso: int
    #: O QUE ESSE PESO VALEU DE FATO, em porcento, depois de a lente sem dado
    #: sair do denominador. Com as cinco lentes medidas os dois batem; com uma
    #: fora, Imprensa vale 30 de 70 — 43%, e não 30%. Mostrar só o nominal
    #: faria a tela afirmar uma participação que não aconteceu.
    peso_efetivo: int
    #: Nulo quando a lente ficou de fora — sem fonte ligada ou sem menção.
    score: int | None
    ns: float | None
    #: Contra o mês anterior. Nulo quando não há os dois meses.
    delta: int | None = None
    fontes: list[str] = Field(default_factory=list)
    estimado: bool = False
    #: Por que ficou de fora, quando ficou. A tela mostra como aviso.
    ausencia: str | None = None


class FatoSaida(BaseModel):
    id: UUID
    mes: str
    texto: str
    efeito: str


class LimiteSaida(BaseModel):
    """Um corte de detector, com o que a tela precisa para desenhar o campo."""

    chave: str
    rotulo: str
    #: O que muda quando este número muda, em uma frase.
    explicacao: str
    valor: float
    padrao: float
    #: `decimal` aceita vírgula; `inteiro` não — "3,5 meses seguidos" não
    #: significa nada, e um campo que aceita o valor convida a digitá-lo.
    formato: str
    unidade: str | None = None


class CalibracaoSaida(BaseModel):
    pesos: dict[str, int]
    regua_tier: str
    regua_engajamento: str
    fontes_desligadas: list[str]
    #: OS OITO, sempre — os ajustados e os de fábrica. Mandar só o que foi
    #: mexido faria a tela ter de conhecer os padrões, e eles passariam a viver
    #: em dois lugares.
    limites: list[LimiteSaida] = Field(default_factory=list)
    #: A fatia de cada lente no radial tem a largura do peso efetivo.
    radial_por_peso: bool = True
    #: Verdadeiro quando a régua é a de fábrica — a tela mostra o chip
    #: "calibração ajustada" quando falso.
    padrao: bool


class IndiceSaida(BaseModel):
    mes: str
    isr: int | None
    faixa: str
    leitura_da_faixa: str
    #: Contra o mês anterior e contra o primeiro mês da série (§6.1).
    delta_mes: int | None
    delta_inicio: int | None
    lentes: list[LenteSaida]
    calibracao: CalibracaoSaida
    fatos: list[FatoSaida]
    #: A leitura em palavras: qual lente sustenta, qual corrói.
    leitura: str


class FatoDoPonto(BaseModel):
    """O que explica o degrau do mês, na própria coluna dele.

    ESCRITO POR GENTE. Um mês pode ter vários: a curva de março não se explica
    só pelo atraso das demonstrações, e obrigar quem cadastra a escolher UM
    faria o segundo motivo sumir do painel.
    """

    id: UUID
    texto: str
    efeito: str


class TemaSaida(BaseModel):
    """O tema que mais pesou no índice do mês — derivado, não cadastrado.

    A OUTRA METADE DA PERGUNTA. O fato diz o que aconteceu no mundo; este diz
    por onde aquilo entrou no número, e quanto custou ou rendeu em pontos do
    índice. A conta é decomposição exata — ver `dominio/tema_do_mes`.
    """

    tema: str
    lente: str
    #: Pontos do índice, com sinal.
    pontos: float
    efeito: str
    positivas: int
    negativas: int


class MovimentoDaLente(BaseModel):
    """Quem mais se mexeu no mês — a lente, e quanto.

    É A PERGUNTA QUE VEM DEPOIS DE "por que caiu": o fato diz o que aconteceu
    no mundo, e este número diz por onde aquilo entrou no índice."""

    lente: str
    delta: int


class TemasDaLenteSaida(BaseModel):
    """O que moveu a nota de UMA lente no mês — a mesma pergunta de
    `sustentou`/`pressionou`, respondida dentro dela só.

    É A METADE DA PERGUNTA QUE A JORNADA DE UMA LENTE PRECISA: lá dentro não se
    compara lente com lente, e por isso não há `maior_movimento` equivalente —
    só "o que, dentro da Imprensa, sustentou e o que pressionou".
    """

    sustentou: TemaSaida | None = None
    pressionou: TemaSaida | None = None
    pontos_sem_tema: float = 0.0


class PontoDaSerie(BaseModel):
    mes: str
    isr: int | None
    #: QUANTAS LENTES formaram o ponto, de 5. Um mês em que só a institucional
    #: tem dado produz um ISR legítimo pela fórmula e ENGANOSO na curva — é o
    #: score de uma lente, desenhado como se fosse o da companhia. A tela usa
    #: este número para marcar o ponto como parcial.
    lentes: int
    #: Verdadeiro quando alguma lente do mês veio de estimativa, e não de
    #: medição.
    tem_estimativa: bool
    #: Contra o mês anterior da série. Nulo no primeiro ponto — que é ponto de
    #: partida, e não variação zero.
    delta: int | None = None
    #: TODOS os fatos do mês, do mais antigo para o mais novo.
    fatos: list[FatoDoPonto] = Field(default_factory=list)
    #: O que a BASE diz sobre o mês: o tema que mais segurou e o que mais
    #: puxou. Qualquer um pode faltar — um mês em que nada pesou não ganha um
    #: "tema do mês" inventado.
    sustentou: TemaSaida | None = None
    pressionou: TemaSaida | None = None
    #: Pontos do índice que nenhum tema explica — menções sem tema. Dizer
    #: isto é o que impede a coluna de afirmar mais do que sabe.
    pontos_sem_tema: float = 0.0
    maior_movimento: MovimentoDaLente | None = None
    #: A nota de cada lente medida no mês, por código. É o que permite desenhar
    #: a curva de comparação sem uma segunda chamada por lente.
    notas_das_lentes: dict[str, int] = Field(default_factory=dict)
    #: O que sustentou e o que pressionou CADA lente no mês, por código — a
    #: Jornada de uma lente lê a dela própria sem uma segunda chamada.
    temas_das_lentes: dict[str, TemasDaLenteSaida] = Field(default_factory=dict)


def _mes_de(texto: str) -> date:
    """`2026-06` vira o primeiro dia do mês.

    O ANO TEM FAIXA: `date` aceita o ano 1, mas as telas voltam meses a partir
    do pedido (`meses_ate`), e "0001-02" estourava em ValueError lá dentro, como
    500. Fora de 2000–2100 não há dado nenhum, e a resposta certa é 422.
    """
    try:
        ano, mes = texto.split("-")
        valor = date(int(ano), int(mes), 1)
    except (ValueError, TypeError) as erro:
        raise RegraViolada(f"Mês inválido: {texto!r}. Use o formato AAAA-MM.") from erro
    if not ANO_MINIMO <= valor.year <= ANO_MAXIMO:
        raise RegraViolada(
            f"Mês inválido: {texto!r}. O ano vai de {ANO_MINIMO} a {ANO_MAXIMO}."
        )
    return valor


ANO_MINIMO = 2000
ANO_MAXIMO = 2100


#: Como cada limite se apresenta na Calibração, na ordem em que se lê: dos
#: cortes da série mensal para os da composição, e por fim o tamanho da lista.
LIMITES_DOS_SINAIS: tuple[tuple[str, str, str, str, str | None], ...] = (
    (
        "pico_desvios",
        "Pico · desvios",
        "Quantos desvios-padrão acima da média um mês precisa ter para virar pico.",
        "decimal",
        "desvios",
    ),
    (
        "pico_razao_minima",
        "Pico · razão mínima",
        "E quantas vezes a média ele precisa ser — as duas condições valem juntas.",
        "decimal",
        "× a média",
    ),
    (
        "virada_pontos",
        "Virada · pontos de nota",
        "Quantos pontos a nota precisa andar de um mês para o outro.",
        "inteiro",
        "pontos",
    ),
    (
        "deslocamento_pp",
        "Deslocamento · pontos percentuais",
        "Quanto a fatia negativa precisa recuar, ou subir, para virar sinal.",
        "decimal",
        "p.p.",
    ),
    (
        "tendencia_meses",
        "Tendência · meses seguidos",
        "Quantos meses na mesma direção formam uma tendência.",
        "inteiro",
        "meses",
    ),
    (
        "concentracao_razao",
        "Concentração · razão",
        "Quantas vezes o primeiro colocado precisa valer o segundo.",
        "decimal",
        "×",
    ),
    (
        "concentracao_top3",
        "Concentração · topo",
        "Quanto do volume os três primeiros precisam somar, quando a razão não dispara.",
        "decimal",
        "%",
    ),
    (
        "max_sinais",
        "Sinais na lista",
        "Quantos sinais o bloco do fim da lente mostra. As lacunas não ocupam vaga.",
        "inteiro",
        None,
    ),
)


def _limites_saida(calibracao: Calibracao) -> list[LimiteSaida]:
    """Os oito, com o valor em vigor e o de fábrica ao lado.

    O PADRÃO VIAJA JUNTO porque é a única forma de a tela oferecer "voltar ao
    de fábrica" sem guardar uma segunda cópia dos números — que envelheceria na
    primeira vez que alguém mudasse um padrão no código.
    """
    padrao = Limites()
    # TOLERANTE NA LEITURA, estrita na gravação: um valor impossível gravado
    # por fora não pode fechar a porta da tela onde ele se conserta.
    vigente = regua_dos_sinais(calibracao)
    return [
        LimiteSaida(
            chave=chave,
            rotulo=rotulo,
            explicacao=explicacao,
            valor=getattr(vigente, chave),
            padrao=getattr(padrao, chave),
            formato=formato,
            unidade=unidade,
        )
        for chave, rotulo, explicacao, formato, unidade in LIMITES_DOS_SINAIS
    ]


def _calibracao_saida(sessao, calibracao: Calibracao) -> CalibracaoSaida:
    padrao = repositorio_score.pesos_padrao(sessao)
    return CalibracaoSaida(
        pesos=calibracao.pesos,
        regua_tier=calibracao.regua_tier,
        regua_engajamento=calibracao.regua_engajamento,
        fontes_desligadas=sorted(calibracao.fontes_desligadas),
        limites=_limites_saida(calibracao),
        radial_por_peso=calibracao.radial_por_peso,
        padrao=(
            calibracao.pesos == padrao
            and calibracao.regua_tier == "aegea"
            and calibracao.regua_engajamento == "n"
            and not calibracao.fontes_desligadas
            and not calibracao.limites
            and calibracao.radial_por_peso
        ),
    )


def _leitura(indice: Indice) -> str:
    """A frase que explica o número (§6.1).

    GERADA, E NÃO ESCRITA: ela muda com o mês e com a régua, e uma frase fixa
    envelheceria no primeiro recálculo. Diz o que sustenta e o que corrói —
    que é a pergunta que alguém faz ao ver o índice.
    """
    com_dado = indice.lentes_no_calculo
    if not com_dado:
        return "Nenhuma lente foi medida neste mês."

    melhor = max(com_dado, key=lambda lente: lente.score or 0)
    pior = min(com_dado, key=lambda lente: lente.score or 0)
    fora = indice.lentes_de_fora

    frase = (
        f"{melhor.nome} sustenta o índice, com {melhor.score}; "
        f"{pior.nome} é o que mais o pressiona, com {pior.score}."
    )
    if fora:
        nomes = ", ".join(lente.nome for lente in fora)
        frase += f" Fora do cálculo: {nomes}."
    return frase


@rotas.get("")
def obter(
    sessao: Sessao,
    usuario: UsuarioLogado,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> IndiceSaida:
    """O índice do mês, com as lentes que o formaram e o que explica a curva."""
    alvo = _mes_de(mes)
    calibracao = repositorio_score.calibracao_vigente(sessao)

    indice = repositorio_score.indice_do_mes(sessao, alvo, calibracao)
    anterior = repositorio_score.indice_do_mes(sessao, _mes_anterior(alvo), calibracao)

    meses = repositorio_score.meses_com_dado(sessao)
    primeiro = repositorio_score.indice_do_mes(sessao, meses[0], calibracao) if meses else indice

    scores_anteriores = {lente.codigo: lente.score for lente in anterior.lentes}
    efetivos = pesos_efetivos(indice)
    # O STAKEHOLDER NÃO PASSA PELO CÁLCULO, e por isso não está em
    # `LenteMedida`: é rótulo de cadastro, e não número. Buscá-lo aqui mantém o
    # domínio do índice falando só de conta.
    stakeholders = {
        lente.codigo: lente.stakeholder for lente in repositorio_score.lentes_cadastradas(sessao)
    }
    lentes = [
        LenteSaida(
            codigo=lente.codigo,
            nome=lente.nome,
            stakeholder=stakeholders[lente.codigo],
            peso=lente.peso,
            peso_efetivo=efetivos.get(lente.codigo, 0),
            score=lente.score,
            ns=round(lente.ns, 4) if lente.ns is not None else None,
            delta=_delta(lente.score, scores_anteriores.get(lente.codigo)),
            fontes=list(lente.fontes),
            estimado=lente.estimado,
            ausencia=lente.ausencia,
        )
        for lente in indice.lentes
    ]

    return IndiceSaida(
        mes=indice.mes,
        isr=indice.isr,
        faixa=indice.faixa,
        leitura_da_faixa=indice.leitura_da_faixa,
        delta_mes=_delta(indice.isr, anterior.isr),
        delta_inicio=_delta(indice.isr, primeiro.isr),
        lentes=lentes,
        calibracao=_calibracao_saida(sessao, calibracao),
        fatos=_fatos_do_mes(sessao, alvo),
        leitura=_leitura(indice),
    )


def _delta(atual: int | None, anterior: int | None) -> int | None:
    """Sem os dois meses não há variação — e zero não é a resposta."""
    if atual is None or anterior is None:
        return None
    return atual - anterior


def _mes_anterior(mes: date) -> date:
    return (
        mes.replace(year=mes.year - 1, month=12)
        if mes.month == 1
        else mes.replace(month=mes.month - 1)
    )


def _fatos_do_mes(sessao, mes: date) -> list[FatoSaida]:
    registros = sessao.scalars(
        select(ScoreFato).where(ScoreFato.mes == mes).order_by(ScoreFato.criado_em)
    )
    return [
        FatoSaida(id=f.id, mes=f"{f.mes:%Y-%m}", texto=f.texto, efeito=f.efeito) for f in registros
    ]


@rotas.get("/serie")
def serie(sessao: Sessao, usuario: UsuarioLogado) -> list[PontoDaSerie]:
    """A evolução mensal do índice, com a régua vigente.

    TODOS OS MESES COM A MESMA RÉGUA: recalcular o passado com a calibração de
    hoje é o que torna a curva comparável. Guardar o score de cada mês com a
    régua da época faria a linha subir e descer por mudança de critério.
    """
    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_score.meses_com_dado(sessao)
    # O CADASTRO ATRAVESSA A SÉRIE INTEIRA. Relê-lo a cada mês somava consultas
    # por ponto, todas com a mesma resposta — e a conta piorava a cada mês
    # ingerido, que é o que vai acontecer todo mês.
    catalogo = repositorio_score.catalogo_das_lentes(sessao)
    nomes = {lente.codigo: lente.nome for lente in catalogo}
    # UMA CONSULTA PARA O PERÍODO INTEIRO, e não uma por mês: a série já faz
    # uma medição por mês, e somar a isso uma ida ao banco por coluna faria a
    # tela mais cara a cada mês ingerido.
    # TODOS OS FATOS DE CADA MÊS, na ordem em que foram cadastrados. A coluna
    # mostra a lista inteira: escolher um faria o segundo motivo do mês sumir
    # do painel, e é justamente o segundo que costuma explicar o resto.
    fatos: dict[str, list[ScoreFato]] = {}
    for fato in repositorio_score.fatos_do_periodo(sessao, meses):
        fatos.setdefault(f"{fato.mes:%Y-%m}", []).append(fato)

    # E o que a BASE diz, ao lado do que as pessoas escreveram.
    temas = repositorio_score.pesos_por_tema(sessao, meses, calibracao)

    pontos: list[PontoDaSerie] = []
    anterior: dict[str, int] = {}
    isr_anterior: int | None = None
    for mes in meses:
        indice = repositorio_score.indice_do_mes(sessao, mes, calibracao, catalogo)
        notas = {lente.codigo: lente.score for lente in indice.lentes if lente.score is not None}
        # O PESO EXATO, E NÃO O ARREDONDADO DA TELA. `pesos_efetivos` reparte
        # inteiros que somam 100 pelo método de Hamilton, para a composição
        # exibida não dar 101. O índice, porém, pondera pela fração real — e
        # usar o inteiro aqui quebraria a exatidão que esta conta promete.
        exatos = pesos_exatos(indice)
        do_mes = temas_que_pesaram(
            temas.get(mes, []),
            exatos,
            {
                lente.codigo: (lente.ns or 0) * 50 * exatos.get(lente.codigo, 0) / 100
                for lente in indice.lentes_no_calculo
            },
        )
        # A MESMA LISTA DE PESOS, aberta por lente — sem consulta nova: é a
        # soma que `temas_que_pesaram` já fez para o índice, só que sem
        # atravessar as outras lentes. SÓ QUEM TEM NOTA entra, pelo mesmo
        # corte de `notas` acima — uma lente sem nota não tem o que explicar.
        temas_das_lentes: dict[str, TemasDaLenteSaida] = {}
        for lente in indice.lentes:
            if lente.score is None:
                continue
            por_lente = temas_que_pesaram_na_lente(
                temas.get(mes, []), lente.codigo, (lente.ns or 0) * 50
            )
            temas_das_lentes[lente.codigo] = TemasDaLenteSaida(
                sustentou=_saida_do_tema(por_lente.sustentou),
                pressionou=_saida_do_tema(por_lente.pressionou),
                pontos_sem_tema=por_lente.pontos_sem_tema,
            )
        pontos.append(
            PontoDaSerie(
                mes=indice.mes,
                isr=indice.isr,
                lentes=len(indice.lentes_no_calculo),
                tem_estimativa=any(lente.estimado for lente in indice.lentes_no_calculo),
                delta=_delta(indice.isr, isr_anterior) if pontos else None,
                fatos=[
                    FatoDoPonto(id=f.id, texto=f.texto, efeito=f.efeito)
                    for f in fatos.get(indice.mes, ())
                ],
                sustentou=_saida_do_tema(do_mes.sustentou),
                pressionou=_saida_do_tema(do_mes.pressionou),
                pontos_sem_tema=do_mes.pontos_sem_tema,
                maior_movimento=_maior_movimento(notas, anterior, nomes),
                notas_das_lentes=notas,
                temas_das_lentes=temas_das_lentes,
            )
        )
        anterior, isr_anterior = notas, indice.isr
    return pontos


def _saida_do_tema(escolhido: TemaDoMes | None) -> TemaSaida | None:
    if escolhido is None:
        return None
    return TemaSaida(
        tema=escolhido.tema,
        lente=escolhido.lente,
        pontos=escolhido.pontos,
        efeito=escolhido.efeito,
        positivas=escolhido.positivas,
        negativas=escolhido.negativas,
    )


def _maior_movimento(
    notas: dict[str, int], anteriores: dict[str, int], nomes: dict[str, str]
) -> MovimentoDaLente | None:
    """A lente que mais andou de um mês para o outro.

    SÓ CONTA QUEM TEM OS DOIS MESES. Uma lente que estreia no mês não "subiu 42
    pontos" — ela apareceu, e chamar isso de movimento faria toda primeira
    ingestão de uma fonte parecer um salto de reputação.

    O EMPATE FICA COM O CÓDIGO, em ordem alfabética: duas lentes com a mesma
    variação precisam devolver sempre a mesma resposta, senão a coluna do mês
    muda de texto entre duas leituras sem nada ter mudado.
    """
    movimentos = [
        (nota - anteriores[codigo], codigo)
        for codigo, nota in notas.items()
        if codigo in anteriores
    ]
    if not movimentos:
        return None
    delta, codigo = sorted(movimentos, key=lambda par: (-abs(par[0]), par[1]))[0]
    if not delta:
        return None
    return MovimentoDaLente(lente=nomes.get(codigo, codigo), delta=delta)


class FonteSaida(BaseModel):
    codigo: str
    nome: str
    fornecedor: str
    lente: str
    #: QUAL EXPORT ESTA FONTE LÊ — `clipei`, `approach`, `bites`.
    #:
    #: EXISTE PARA A TELA AGRUPAR, e a pergunta do dono do produto é a razão:
    #: "por que tem clipei e clipei investidores?". Porque `score_fonte` é a
    #: alimentação de uma LENTE, não um fornecedor — `clipei` alimenta Imprensa
    #: (peso 30) e `clipei_investidores` alimenta Mercado (peso 20), com o mesmo
    #: arquivo. Sem a segunda, 20% do índice fica sem alimentação.
    #:
    #: Mas ninguém SOBE pela segunda: ela é alimentada junto, e expor as duas
    #: num seletor de upload oferece uma escolha que não existe. Com este campo
    #: a tela oferece o ARQUIVO e diz quais lentes ele alimenta.
    #:
    #: Nulo na fonte que anda sozinha — é o fornecedor que entrega um arquivo só
    #: dele, e aí o próprio código serve de agrupador.
    arquivo: str | None
    interna: bool
    ativo: bool
    #: Se a calibração vigente a desligou.
    ligada: bool
    observacao: str | None
    #: Quantos meses têm dado desta fonte, e quantas menções no mês pedido.
    meses_com_dado: int
    mencoes_no_mes: int


def _arquivo_do_mapeamento(bruto: dict | None) -> str | None:
    """Qual export a fonte lê, como o cadastro o guarda.

    SÓ A CHAVE, sem validar o resto: a listagem é LEITURA, e uma fonte com
    mapeamento incompleto tem de aparecer na tela de cadastro — é justamente
    lá que alguém vai consertá-la. Validar aqui esconderia o problema atrás de
    um 500 na tela que o mostraria.
    """
    valor = (bruto or {}).get("arquivo")
    return valor if isinstance(valor, str) and valor else None


@rotas.get("/fontes")
def listar_fontes(
    sessao: Sessao,
    usuario: UsuarioLogado,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> list[FonteSaida]:
    """O registro de fontes, com cobertura e volume — a aba Calibração."""
    alvo = _mes_de(mes)
    calibracao = repositorio_score.calibracao_vigente(sessao)
    lentes = {lente.id: lente.nome for lente in repositorio_score.lentes_cadastradas(sessao)}

    cobertura: dict[int, int] = {}
    volume: dict[int, int] = {}
    for fonte_id, mes_da_linha, mencoes in sessao.execute(
        select(ScoreMesFonte.fonte_id, ScoreMesFonte.mes, ScoreMesFonte.mencoes)
    ):
        cobertura[fonte_id] = cobertura.get(fonte_id, 0) + (1 if mes_da_linha else 0)
        if mes_da_linha == alvo:
            volume[fonte_id] = volume.get(fonte_id, 0) + mencoes

    return [
        FonteSaida(
            codigo=fonte.codigo,
            nome=fonte.nome,
            fornecedor=fonte.fornecedor,
            lente=lentes.get(fonte.lente_id, "—"),
            # DIRETO DA CHAVE, e não por `Mapeamento.de_json`: o mapeamento da
            # fonte INTERNA (`crm`) é `{}` — ela não lê planilha nenhuma —, e
            # `Mapeamento` exige `data` e `sentimento`, com razão. Montá-lo só
            # para ler uma chave fazia a LISTAGEM INTEIRA estourar por causa da
            # fonte que nem tem arquivo, levando com ela a Calibração e a Base.
            arquivo=_arquivo_do_mapeamento(fonte.mapeamento_colunas),
            interna=fonte.interna,
            ativo=fonte.ativo,
            ligada=calibracao.ligada(fonte.codigo),
            observacao=fonte.observacao,
            # Meses distintos, e não linhas: cada mês tem várias linhas (uma
            # por sentimento e tier).
            meses_com_dado=_meses_distintos(sessao, fonte.id),
            mencoes_no_mes=volume.get(fonte.id, 0),
        )
        for fonte in repositorio_score.fontes_cadastradas(sessao)
    ]


def _meses_distintos(sessao, fonte_id: int) -> int:
    return len(
        set(sessao.scalars(select(ScoreMesFonte.mes).where(ScoreMesFonte.fonte_id == fonte_id)))
    )


class ComposicaoSaida(BaseModel):
    """Os três números da fórmula, JÁ PONDERADOS pela régua vigente.

    São o que a barra da aba Lentes desenha — e não a contagem crua: com a
    régua 10/5/1, as 65 matérias de veículo Muito Relevante valem 650, e é
    isso que entra na conta.
    """

    positivo: float
    neutro: float
    negativo: float


class FonteDaLenteSaida(BaseModel):
    codigo: str
    nome: str
    ns: float | None
    mencoes: int
    ligada: bool


class TemaDaLenteSaida(BaseModel):
    nome: str
    positivo: int
    negativo: int
    #: `estruturante` | `operacional` | nulo quando ninguém classificou.
    tipo: str | None


class LenteDetalheSaida(BaseModel):
    codigo: str
    nome: str
    stakeholder: str
    score: int | None
    ns: float | None
    peso: int
    estimado: bool
    ausencia: str | None
    composicao: ComposicaoSaida
    #: A fórmula aplicada, escrita — muda com a régua, então é gerada.
    formula: str
    fontes: list[FonteDaLenteSaida]
    temas: list[TemaDaLenteSaida]


@rotas.get("/lentes/{codigo}")
def obter_lente(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> LenteDetalheSaida:
    """Uma lente por dentro: a composição, a fórmula e os temas."""
    alvo = _mes_de(mes)
    calibracao = repositorio_score.calibracao_vigente(sessao)

    lente = sessao.scalar(select(Lente).where(Lente.codigo == codigo))
    if lente is None:
        raise NaoEncontrado(f"Lente {codigo!r} não existe.")

    medida = next(
        (m for m in repositorio_score.medir_lentes(sessao, alvo, calibracao) if m.codigo == codigo),
        None,
    )
    if medida is None:  # pragma: no cover - `medir_lentes` cobre as ativas
        raise NaoEncontrado(f"Lente {codigo!r} não está ativa.")

    composicao = repositorio_score.composicao_da_lente(sessao, lente.id, alvo, calibracao)
    return LenteDetalheSaida(
        codigo=lente.codigo,
        nome=lente.nome,
        stakeholder=lente.stakeholder,
        score=medida.score,
        ns=round(medida.ns, 4) if medida.ns is not None else None,
        peso=medida.peso,
        estimado=medida.estimado,
        ausencia=medida.ausencia,
        composicao=ComposicaoSaida(
            positivo=round(composicao.positivo, 2),
            neutro=round(composicao.neutro, 2),
            negativo=round(composicao.negativo, 2),
        ),
        formula=_formula(lente.codigo, calibracao),
        fontes=[
            FonteDaLenteSaida(
                codigo=fonte.codigo,
                nome=fonte.nome,
                ns=ns_da_fonte,
                mencoes=mencoes,
                ligada=calibracao.ligada(fonte.codigo),
            )
            for fonte, ns_da_fonte, mencoes in repositorio_score.fontes_da_lente(
                sessao, lente.id, alvo, calibracao
            )
        ],
        temas=[
            TemaDaLenteSaida(nome=nome, positivo=pos, negativo=neg, tipo=tipo)
            for nome, pos, neg, tipo in repositorio_score.temas_da_lente(
                sessao, lente.id, alvo, calibracao
            )
        ],
    )


#: Quantas matérias cada tier vale, em palavras, para a frase da fórmula.
def _formula(lente: str, calibracao: Calibracao) -> str:
    """A fórmula aplicada, escrita — é a explicação que a tela mostra.

    GERADA, e não fixa: ela muda com a régua, e um texto escrito à mão
    passaria a mentir no primeiro ajuste da calibração.
    """
    base = "NS = (positivas − negativas) ÷ total; score = (NS + 1) ÷ 2 × 100."
    if lente in ("imprensa", "mercado"):
        pesos = REGUAS_DE_TIER[calibracao.regua_tier]
        return (
            f"{base} Cada matéria vale {pesos['muito_relevante']:g} (Tier 1), "
            f"{pesos['relevante']:g} (Tier 2) ou {pesos['menos_relevante']:g} (Tier 3)."
        )
    if lente in ("sociedade", "clientes"):
        comoR = {
            "n": "cada menção vale 1",
            "log": "cada menção vale 1 + log₁₀(1 + engajamento)",
            "bruto": "cada menção vale o seu engajamento",
            "cargo": "cada menção vale o peso do cargo de quem postou",
        }[calibracao.regua_engajamento]
        return (
            f"{base} {comoR[0].upper() + comoR[1:]}. Com mais de uma fonte, "
            "as menções das duas entram na mesma conta — um denominador só."
        )
    return f"{base} Vem do clima das interações registradas neste painel."


class CalibracaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pesos: dict[str, int] = Field(default_factory=dict)
    regua_tier: str = "aegea"
    regua_engajamento: str = "n"
    fontes_desligadas: list[str] = Field(default_factory=list)
    #: SÓ O QUE FOI MEXIDO. Gravar os oito sempre faria toda régua parecer
    #: ajustada, e "voltar ao padrão" deixaria de ser distinguível de "gravei
    #: os mesmos números".
    limites: dict[str, float] = Field(default_factory=dict)
    radial_por_peso: bool = True


@rotas.get("/calibracao")
def obter_calibracao(sessao: Sessao, usuario: UsuarioLogado) -> CalibracaoSaida:
    return _calibracao_saida(sessao, repositorio_score.calibracao_vigente(sessao))


@rotas.put("/calibracao", status_code=status.HTTP_201_CREATED)
def gravar_calibracao(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, entrada: CalibracaoEntrada
) -> CalibracaoSaida:
    """Grava uma VERSÃO NOVA da régua, e não altera a anterior.

    Saber com que critério um número foi lido no mês passado é o que permite
    explicar por que ele mudou — e é por isso que a tabela só cresce.
    """
    # `Calibracao` valida as réguas e a faixa dos pesos antes de qualquer
    # escrita: a recusa vem do domínio, e não de um `check` no banco.
    calibracao = Calibracao(
        pesos=entrada.pesos,
        regua_tier=entrada.regua_tier,
        regua_engajamento=entrada.regua_engajamento,
        fontes_desligadas=frozenset(entrada.fontes_desligadas),
        limites=entrada.limites,
        radial_por_peso=entrada.radial_por_peso,
    )
    # RECUSA ANTES DE GRAVAR: um limite zerado não daria erro aqui, daria horas
    # depois, na tela de outra pessoa abrindo uma lente.
    Limites.a_partir_de(entrada.limites)
    conhecidas = {fonte.codigo for fonte in repositorio_score.fontes_cadastradas(sessao)}
    desconhecidas = sorted(calibracao.fontes_desligadas - conhecidas)
    if desconhecidas:
        raise RegraViolada(f"Fonte não cadastrada: {', '.join(desconhecidas)}.")
    conhecidas_lentes = set(repositorio_score.pesos_padrao(sessao))
    fora = sorted(set(entrada.pesos) - conhecidas_lentes)
    if fora:
        raise RegraViolada(f"Lente não cadastrada: {', '.join(fora)}.")

    sessao.add(
        ScoreConfig(
            pesos=entrada.pesos,
            regua_tier=entrada.regua_tier,
            regua_engajamento=entrada.regua_engajamento,
            fontes_desligadas=sorted(entrada.fontes_desligadas),
            limites=entrada.limites,
            radial_por_peso=entrada.radial_por_peso,
            criado_por=usuario.id,
        )
    )
    sessao.flush()
    return _calibracao_saida(sessao, repositorio_score.calibracao_vigente(sessao))


@rotas.delete("/calibracao", status_code=status.HTTP_201_CREATED)
def restaurar_padrao(sessao: Sessao, usuario: UsuarioQueAdministraCadastros) -> CalibracaoSaida:
    """ "Restaurar padrão" (§3): grava uma versão com a régua de fábrica.

    Não apaga o histórico — volta ao padrão gravando, que é como se desfaz
    numa tabela que só cresce.
    """
    sessao.add(
        ScoreConfig(
            pesos=repositorio_score.pesos_padrao(sessao),
            regua_tier="aegea",
            regua_engajamento="n",
            fontes_desligadas=[],
            criado_por=usuario.id,
        )
    )
    sessao.flush()
    return _calibracao_saida(sessao, repositorio_score.calibracao_vigente(sessao))


class FatoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mes: str
    texto: str = Field(min_length=3)
    efeito: str


EFEITOS = ("sustenta", "pressiona", "misto")


@rotas.post("/fatos", status_code=status.HTTP_201_CREATED)
def criar_fato(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, entrada: FatoEntrada
) -> FatoSaida:
    """O que explica a curva — "caiu em março porque saíram as DFs"."""
    if entrada.efeito not in EFEITOS:
        raise RegraViolada(f"Efeito inválido: {entrada.efeito!r}. Use {', '.join(EFEITOS)}.")
    registro = ScoreFato(
        mes=_mes_de(entrada.mes),
        texto=entrada.texto.strip(),
        efeito=entrada.efeito,
        criado_por=usuario.id,
    )
    sessao.add(registro)
    sessao.flush()
    return FatoSaida(
        id=registro.id,
        mes=f"{registro.mes:%Y-%m}",
        texto=registro.texto,
        efeito=registro.efeito,
    )


@rotas.delete("/fatos/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_fato(sessao: Sessao, usuario: UsuarioQueAdministraCadastros, id: UUID) -> None:
    registro = sessao.get(ScoreFato, id)
    if registro is None:
        raise NaoEncontrado("Fato não encontrado.")
    sessao.execute(delete(ScoreFato).where(ScoreFato.id == id))


class AtributoSaida(BaseModel):
    """Um atributo reputacional, com o saldo que ele carrega."""

    nome: str
    positivo: int
    neutro: int
    negativo: int
    #: O saldo na escala do índice, para a tela desenhar a barra divergente.
    score: int
    ns: float


class UnidadeSaida(BaseModel):
    nome: str
    negativas: int
    mencoes: int
    #: Quanto do negativo do mês inteiro está nesta unidade.
    participacao: int


class PerpetuacaoSaida(BaseModel):
    """Um tema negativo que atravessa meses."""

    tema: str
    meses: int
    primeiro_mes: str
    ultimo_mes: str
    negativas: int
    #: Em que lentes ele aparece — "imprensa e redes" é pior que só redes.
    lentes: list[str]


class RegraDaPerpetuacao(BaseModel):
    """Os números que definem "em perpetuação", ditos pelo servidor.

    A TELA PRECISA EXPLICAR A REGRA para quem lê a lista — "temas presentes em
    3 dos últimos 6 meses" —, e uma constante repetida no front envelheceria
    calada: mudaria a explicação sem mudar a lista, que é a pior forma de
    errar, porque ninguém desconfia do texto.
    """

    meses_da_janela: int
    meses_para_perpetuar: int


class DriversSaida(BaseModel):
    """A aba de Drivers e riscos: o porquê do número, e não o número.

    As três listas vêm de `mencao`, uma a uma, e não do agregado mensal — que
    já perdeu o atributo, o tema e a unidade ao somar. Sem planilha importada
    no mês, as três voltam vazias, e a tela diz por quê em vez de desenhar
    zeros.
    """

    mes: str
    atributos: list[AtributoSaida]
    unidades: list[UnidadeSaida]
    perpetuacao: list[PerpetuacaoSaida]
    regra_da_perpetuacao: RegraDaPerpetuacao
    #: Quantas menções individuais o mês tem, DE FONTES LIGADAS. Zero explica
    #: as três listas vazias — mas não diz qual dos dois motivos: pode não ter
    #: planilha importada, ou pode ter e estar toda desligada na calibração. É
    #: o que `fontes_ligadas` distingue.
    mencoes_no_mes: int
    #: Quantas fontes de planilha estão no cálculo. Zero com menção no banco
    #: significa "você desligou tudo", e não "falta importar".
    fontes_ligadas: int


@rotas.get("/drivers")
def drivers(
    sessao: Sessao,
    usuario: UsuarioLogado,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> DriversSaida:
    """O que explica o índice do mês: atributo, unidade e o que não passa."""
    alvo = _mes_de(mes)
    calibracao = repositorio_score.calibracao_vigente(sessao)

    atributos = [
        AtributoSaida(
            nome=nome,
            positivo=pos,
            neutro=neu,
            negativo=neg,
            ns=round(saldo, 4),
            score=para_score(saldo),
        )
        for nome, pos, neu, neg in repositorio_score.atributos_do_mes(sessao, alvo, calibracao)
        # `ns` devolve None quando o total é zero — o que não acontece aqui,
        # porque o agrupamento só produz linha com menção. O guarda é para o
        # dia em que a consulta mudar e o zero passar a existir: dividir por
        # zero na tela apareceria como um atributo em 50, que é mentira.
        if (saldo := ns(Contagem(positivo=pos, neutro=neu, negativo=neg))) is not None
    ]

    unidades_cruas = repositorio_score.unidades_do_mes(sessao, alvo, calibracao)
    # O TOTAL DO MÊS, e não a soma do ranking: com as oito primeiras como base,
    # a nona unidade negativa sumiria da conta e as oito somariam 100% de um
    # todo que não existe.
    total_negativo = repositorio_score.negativas_do_mes(sessao, alvo, calibracao) or 1
    unidades = [
        UnidadeSaida(
            nome=nome,
            negativas=neg,
            mencoes=total,
            participacao=round(neg / total_negativo * 100),
        )
        for nome, neg, total in unidades_cruas
    ]

    perpetuacao = [
        PerpetuacaoSaida(
            tema=tema,
            meses=meses,
            primeiro_mes=f"{primeiro:%Y-%m}",
            ultimo_mes=f"{ultimo:%Y-%m}",
            negativas=neg,
            lentes=lentes,
        )
        for tema, meses, primeiro, ultimo, neg, lentes in (
            repositorio_score.temas_em_perpetuacao(sessao, alvo, calibracao)
        )
    ]

    return DriversSaida(
        mes=f"{alvo:%Y-%m}",
        atributos=atributos,
        unidades=unidades,
        perpetuacao=perpetuacao,
        regra_da_perpetuacao=RegraDaPerpetuacao(
            meses_da_janela=repositorio_score.MESES_DA_PERPETUACAO,
            meses_para_perpetuar=repositorio_score.MESES_PARA_PERPETUAR,
        ),
        mencoes_no_mes=repositorio_score.mencoes_do_mes(sessao, alvo, calibracao),
        fontes_ligadas=sum(
            1
            for fonte in repositorio_score.fontes_cadastradas(sessao)
            if not fonte.interna and calibracao.ligada(fonte.codigo)
        ),
    )


class ImportacaoSaida(BaseModel):
    """O que a planilha rendeu numa fonte — a tela mostra isto após o upload.

    OS DESCARTES SAEM NA RESPOSTA de propósito. Uma importação que diz só
    "ingeridas 4.973" esconde que 1.426 posts vieram sem classificação de
    sentimento: quem conferir o número do mês precisa saber que o fornecedor
    mandou 7.868 linhas e que a diferença não é perda, é recusa declarada.

    `antes` é a outra metade da honestidade: quantas menções a fonte tinha
    nestes meses antes da troca. É o que deixa um export parcial, baixado antes
    do fechamento, aparecer como o que é — um mês que encolheu.
    """

    fonte: str
    nome: str
    linhas: int
    ingeridas: int
    antes: int
    descartes: dict[str, int]
    avisos: dict[str, int]
    meses: list[str]
    #: Quantos veículos nasceram no cadastro nesta subida, e quantas menções
    #: ficaram ligadas a ele. Zero nos dois é o estado de quem subiu sem
    #: autorizar criação — o padrão da rota.
    veiculos_criados: int = 0
    mencoes_ligadas: int = 0


class VeiculoNovoSaida(BaseModel):
    """Um veículo que a planilha traz e o cadastro não tem.

    A TELA MARCA TODOS e deixa desmarcar — pedido do dono do produto. Por isso
    cada um vem com a praça, o alcance e quantas menções o citam: é com esses
    três que alguém decide tirar a marca de um rádio de bairro sem precisar
    procurar o que ele é.
    """

    nome: str
    uf: str | None = None
    esfera: str | None = None
    mencoes: int
    #: O CARGO QUE O FORNECEDOR INFORMOU, já com as grafias dobradas.
    #:
    #: É ELE QUE DECIDE O PÚBLICO do perfil no cadastro — vereador entra em
    #: Poder Legislativo / Municipal, e não em Formadores de Opinião. Quem
    #: autoriza a criação de 1.108 perfis precisa ver "Iriel Sachet —
    #: Vereador": sem o cargo, a decisão é tomada sobre um nome e um número.
    cargo: str | None = None


class AssuntoNaoReconhecidoSaida(BaseModel):
    """Um assunto que a planilha traz e o cadastro de temas não reconhece."""

    #: O texto como o fornecedor o escreveu — é o que se procura na planilha.
    nome: str
    #: Quantas linhas o citam. A lista ordena por aqui.
    mencoes: int
    #: O NOME EXISTE NO CADASTRO, MAS ESTÁ DESATIVADO. São dois problemas com
    #: dois consertos: nome errado se arruma na planilha, tema desativado se
    #: arruma no cadastro — ou é a planilha que está na taxonomia antiga, e a
    #: v4 desativou 45 temas.
    desativado: bool


class ConferenciaSaida(BaseModel):
    """O que a subida FARIA, antes de gravar.

    `previsao` tem uma linha por fonte irmã, como a importação; `veiculos_novos`
    é o que nasceria no cadastro. Medido no primeiro arquivo da Clipei: 2.631
    veículos. É esse número que a pessoa vê antes de decidir.
    """

    previsao: list[ImportacaoSaida]
    veiculos_novos: list[VeiculoNovoSaida]
    #: Quantos veículos da planilha o cadastro JÁ reconhece. Com os novos, dá o
    #: total — e a razão entre os dois é o quanto a ponte cobre hoje.
    veiculos_reconhecidos: int
    #: Quantas linhas achariam assunto no cadastro de temas.
    #:
    #: POR QUE ESTE NÚMERO APARECE NA CONFERÊNCIA. O dossiê recorta por Pilar
    #: (N1), Tema estratégico (N2) e Subtema (N3) pelo vínculo da menção com o
    #: tema; sem vínculo, a linha não entra em recorte nenhum. Subir uma
    #: planilha cujo assunto não casa é subir dado que nenhum filtro alcança.
    mencoes_com_tema: int = 0
    #: Quantas vieram SEM assunto. Não é erro — a planilha da Bites de
    #: 01–09/2026 veio com 84% da coluna em branco, e o conteúdo vai ser
    #: refeito. Mas quem sobe tem de ver o tamanho disso.
    mencoes_sem_assunto: int = 0
    #: OS NOMES QUE O CADASTRO NÃO RECONHECE, por volume. É a lista que a
    #: pessoa leva para o fornecedor — ou para o cadastro, quando o tema existe
    #: e está desativado.
    assuntos_nao_reconhecidos: list[AssuntoNaoReconhecidoSaida] = []


#: A subcategoria de público que define a lente Mercado.
#:
#: PELO NOME, e não pelo id: ids são do banco de cada ambiente. O par
#: (Imprensa, "Econômica e de negócios") é o contrato que a `0061` fixou ao
#: separar Imprensa de Formadores de Opinião, e a `0066` semeou.
CATEGORIA_DA_IMPRENSA = "Imprensa"
SUBCATEGORIA_DO_MERCADO = "Econômica e de negócios"


class VeiculosDoMercadoEntrada(BaseModel):
    """A lista COMPLETA de veículos que a lente Mercado considera.

    DECLARATIVA, e não um alternador por veículo. Duas razões:

    O `PUT /api/instituicoes/{id}` existente exige o cadastro inteiro
    (`extra="forbid"`), então alternar um campo obrigaria a tela a reenviar nome,
    tipo, UF, tier e categoria — e esquecer um deles apagaria o dado sem
    ninguém notar.

    E porque é assim que a pessoa pensa: ela tem uma LISTA de veículos de
    mercado, mantida numa planilha, e quer que o sistema reflita essa lista.
    "Estes 81 são" é a frase dela; "marque o 37º" não é.
    """

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID]
    #: A LISTA QUE A TELA TINHA EM MÃO quando a pessoa começou a editar.
    #:
    #: POR QUE ELA VEM NO PEDIDO. A gravação é declarativa sobre a tabela
    #: inteira, e o catálogo que a tela lê é carregado no boot: duas pessoas
    #: editando a mesma lista se destroem em silêncio. A abre a aba de manhã, B
    #: acrescenta um veículo à tarde, A remove outro e salva — o pedido de A
    #: chega sem o id do veículo de B, e "estes são os veículos de mercado"
    #: desmarca o de B. A tela de A diz "0 entraram, 1 saíram": contagem
    #: verdadeira de uma mudança que A não pediu.
    #:
    #: OBRIGATÓRIA, e não opcional: guarda que se pode esquecer de mandar é
    #: guarda que não existe. Divergiu? 409, e a tela recarrega e mostra a
    #: lista de agora — ninguém perde trabalho sem saber.
    conhecidos: list[UUID]


class VeiculosDoMercadoSaida(BaseModel):
    marcados: int
    #: Quantos saíram da lista nesta gravação. É o número que a tela repete de
    #: volta, porque remover é a operação que a pessoa quer ver confirmada.
    desmarcados: int
    #: OS QUE NÃO ENTRARAM, pelo nome, por já terem outra classificação.
    #:
    #: EXISTE PORQUE A RECUSA ERA MUDA. O servidor não sobrescreve subcategoria
    #: escolhida à mão — está certo —, mas devolvia `{marcados: 0}` sem dizer
    #: de quem, e a tela imprimia "Nada mudou — a lista já estava assim" e
    #: limpava a edição. A pessoa achava que salvou, e a lente seguia sem o
    #: veículo. Nome, e não id: é o que ela reconhece na frase.
    recusados: list[str] = []


@rotas.put("/veiculos-de-investidores")
def definir_veiculos_de_investidores(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    entrada: VeiculosDoMercadoEntrada,
) -> VeiculosDoMercadoSaida:
    """Define quais veículos a lente Mercado considera.

    O QUE ISTO RESOLVE. A lente Mercado se separava por `Público-alvo =
    Investidores`, coluna que o fornecedor preenche: medido contra o export de
    08–09/2026, captura 80 linhas onde a lista de veículos que a Aegea mantém
    captura 323. O critério passa a ser o cadastro, e esta rota é como a lista
    se mantém — por tela, não por SQL.

    SÓ MEXE NA SUBCATEGORIA DO MERCADO. Um veículo classificado à mão como
    "Geral nacional" ou "Regional das concessões" não é tocado: tirá-lo da lista
    de mercado não pode apagar uma classificação que alguém fez. Quem sai da
    lista e tinha a subcategoria DO MERCADO fica sem subcategoria — que é o
    estado de "ainda não classificado", e é verdade.

    SÓ VEÍCULO. Um id de órgão ou de entidade é ignorado em silêncio: a lente lê
    `mencao`, que aponta para veículo, e marcar um órgão como imprensa econômica
    seria cadastro errado sem efeito nenhum.
    """
    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(CategoriaPublico, CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id)
        .where(
            CategoriaPublico.nome == CATEGORIA_DA_IMPRENSA,
            SubcategoriaPublico.nome == SUBCATEGORIA_DO_MERCADO,
        )
        #: DESEMPATE EXPLÍCITO: `categoria_publico.nome` e
        #: `subcategoria_publico.nome` não têm índice único, e hoje nenhuma tela
        #: os renomeia (as duas tabelas estão em `FECHADOS`) — mas migration
        #: renomeia, e a 0061 renomeou. Sem ordem, duas linhas com o mesmo nome
        #: fariam a rota e a ingestão escolherem subcategorias diferentes, cada
        #: uma pela ordem que o banco devolvesse.
        .order_by(SubcategoriaPublico.id)
        .limit(1)
    )
    if alvo is None:
        raise RegraViolada(
            f"A subcategoria {SUBCATEGORIA_DO_MERCADO!r} da {CATEGORIA_DA_IMPRENSA} "
            "não está cadastrada. Cadastre-a antes de definir a lista."
        )

    categoria = sessao.scalar(
        select(CategoriaPublico.id).where(CategoriaPublico.nome == CATEGORIA_DA_IMPRENSA)
    )

    pedidos = set(entrada.ids)
    #: TRAVA AS LINHAS ENVOLVIDAS ANTES DE DECIDIR, em ordem de id — a mesma
    #: disciplina da reconferência da taxonomia. Sem trava, duas gravações
    #: simultâneas leem a mesma lista e a segunda desfaz a primeira.
    envolvidos = sorted(pedidos | set(entrada.conhecidos))
    if envolvidos:
        sessao.scalars(
            select(Instituicao)
            .where(Instituicao.id.in_(envolvidos))
            .order_by(Instituicao.id)
            .with_for_update()
        ).all()

    #: A LISTA DE AGORA, depois da trava.
    atuais = {
        instituicao.id: instituicao
        for instituicao in sessao.scalars(
            select(Instituicao).where(
                Instituicao.tipo == "veiculo",
                Instituicao.subcategoria_publico_id == alvo,
            )
        )
    }
    if set(entrada.conhecidos) != set(atuais):
        raise Conflito(
            "A lista de veículos de investidores mudou desde que esta tela "
            f"carregou (agora são {len(atuais)}). Recarregue e refaça a edição — "
            "salvar por cima desfaria o que a outra pessoa acabou de fazer."
        )

    marcados = 0
    desmarcados = 0
    recusados: list[str] = []
    for instituicao in sessao.scalars(
        select(Instituicao).where(Instituicao.tipo == "veiculo")
    ):
        quer = instituicao.id in pedidos
        tem = instituicao.subcategoria_publico_id == alvo
        if quer and not tem:
            #: NÃO SOBRESCREVE outra subcategoria: ela é decisão de alguém. Mas
            #: a recusa VOLTA COM NOME — ver `VeiculosDoMercadoSaida.recusados`.
            if instituicao.subcategoria_publico_id is None:
                instituicao.subcategoria_publico_id = alvo
                #: E A CATEGORIA VAI JUNTO. A subcategoria é filha da categoria,
                #: e gravar só a filha deixa um par que a tela de cadastro
                #: recusa ("Subcategoria X não pertence à categoria Y") — quem
                #: fosse editar aquele veículo teria de mudar a classificação,
                #: e isso o tiraria da lente sem querer.
                if instituicao.categoria_publico_id is None and categoria is not None:
                    instituicao.categoria_publico_id = categoria
                marcados += 1
            else:
                recusados.append(instituicao.nome)
        elif tem and not quer:
            instituicao.subcategoria_publico_id = None
            desmarcados += 1
    sessao.flush()
    return VeiculosDoMercadoSaida(
        marcados=marcados, desmarcados=desmarcados, recusados=recusados
    )


@rotas.post("/fontes/{codigo}/conferencia")
def conferir_planilha(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    codigo: str,
    arquivo: Annotated[UploadFile, File()],
) -> ConferenciaSaida:
    """Lê o export e diz o que a subida faria. NADA É GRAVADO.

    POR QUE ELA EXISTE. O dono do produto pediu que o veículo sem cadastro nasça
    junto com a subida, e pediu que a conta apareça antes — o que é o que torna
    a coisa segura. A importação de agendas tem escrito no próprio código por
    quê: "importação de planilha sem conferência humana cria duplicata de
    instituição em massa, e desfazer isso depois é pior que digitar de novo".

    AS RECUSAS ESTRUTURAIS APARECEM AQUI, antes de a pessoa escolher nada:
    arquivo que não abre, aba que falta, coluna que o cadastro espera e não
    existe. `app/api/erros.py` as traduz para 422.
    """
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
    if fonte is None:
        raise NaoEncontrado("Fonte não encontrada.")

    previsao, reconhecimento, assuntos = ingerir_mencoes.conferir(
        sessao, fonte, arquivo.file.read()
    )
    return ConferenciaSaida(
        previsao=[_saida_da_importacao(resumo) for resumo in previsao],
        veiculos_novos=[
            VeiculoNovoSaida(
                nome=veiculo.nome,
                uf=veiculo.uf,
                esfera=veiculo.esfera,
                mencoes=veiculo.mencoes,
                #: PELO RÓTULO, e não pelo código: a tela mostra "Deputado
                #: estadual", e não `deputado_estadual`.
                cargo=rotulo_do_cargo(veiculo.cargo),
            )
            for veiculo in reconhecimento.novos
        ],
        veiculos_reconhecidos=len(reconhecimento.cadastrados),
        mencoes_com_tema=assuntos.ligadas,
        mencoes_sem_assunto=assuntos.sem_assunto,
        assuntos_nao_reconhecidos=[
            AssuntoNaoReconhecidoSaida(
                nome=item.nome, mencoes=item.mencoes, desativado=item.desativado
            )
            #: OS TRINTA MAIORES, e não a lista inteira: a Bites de 01–09/2026
            #: traz 65 valores distintos, e um fornecedor novo pode trazer
            #: centenas. Quem corrige a planilha ataca por volume, e a lista
            #: ordenada já põe o que importa no topo.
            for item in assuntos.nao_ligados[:30]
        ],
    )


@rotas.post("/fontes/{codigo}/planilha", status_code=status.HTTP_201_CREATED)
def importar_planilha(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    codigo: str,
    arquivo: Annotated[UploadFile, File()],
    veiculos_a_criar: Annotated[str | None, Form()] = None,
) -> list[ImportacaoSaida]:
    """Lê o export do fornecedor e substitui os meses que ele traz.

    DEVOLVE UMA LINHA POR FONTE porque um arquivo alimenta mais de uma: o
    export da Clipei atende Imprensa e, recortado, Mercado; o da Approach traz
    Social Listening e Community Management em abas diferentes. Ver o cabeçalho
    de `casos_de_uso/ingerir_mencoes.py`.

    MESMA PERMISSÃO DA CALIBRAÇÃO, e pelo mesmo motivo: isto muda o número que
    todo mundo lê na reunião. Ler o Score basta ter o portal; mexer no que o
    alimenta é da coordenação.
    """
    fonte = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == codigo))
    if fonte is None:
        raise NaoEncontrado("Fonte não encontrada.")

    return [
        _saida_da_importacao(resumo)
        for resumo in ingerir_mencoes.ingerir(
            sessao, fonte, arquivo.file.read(), _nomes_autorizados(veiculos_a_criar)
        )
    ]


def _nomes_autorizados(bruto: str | None) -> tuple[str, ...]:
    """Os nomes que a pessoa marcou, de UM campo com a lista em JSON.

    UM CAMPO, E NÃO UM POR NOME, e isto é conserto de um defeito que a pessoa
    encontrou na tela: a primeira versão mandava `veiculos_a_criar` repetido,
    uma vez por veículo, que é como o FastAPI lê `Form(list[str])`. Com 2.628
    veículos na primeira carga da Clipei, o parser multipart do Starlette
    recusou o pedido inteiro:

        Too many fields. Maximum number of fields is 1000

    O limite é proteção do servidor e está certo — quem estava errado era o
    formato. Afrouxá-lo trocaria um defeito desta tela por uma porta aberta em
    todas as outras.

    OS MEUS TESTES NÃO PEGARAM porque chamavam `ingerir` direto em Python, e os
    de HTTP usavam listas de dois nomes. O teste novo manda 2.000 pelo cliente
    de verdade — o número é o que importa aqui, e testar com dois provava o
    caminho e não o volume.

    JSON INVÁLIDO É ERRO DE PEDIDO, não lista vazia: aceitar em silêncio faria a
    tela dizer "2.628 cadastrados" e nada nascer.
    """
    if not bruto or not bruto.strip():
        return ()
    try:
        lido = json.loads(bruto)
    except json.JSONDecodeError as erro:
        raise RegraViolada(
            "A lista de veículos a cadastrar não chegou em formato válido. "
            "Recarregue a página e tente de novo."
        ) from erro
    if not isinstance(lido, list):
        raise RegraViolada(
            "A lista de veículos a cadastrar precisa ser uma lista de nomes."
        )
    return tuple(str(nome) for nome in lido if str(nome).strip())


def _saida_da_importacao(resumo: ingerir_mencoes.Resumo) -> ImportacaoSaida:
    """O resumo no formato da tela — de uma conferência ou de uma subida.

    O MESMO MOLDE PARA AS DUAS, de propósito: a conferência promete o que a
    subida faz, e dois moldes divergiriam no primeiro campo novo.
    """
    return ImportacaoSaida(
        fonte=resumo.fonte,
        nome=resumo.nome,
        linhas=resumo.linhas,
        ingeridas=resumo.ingeridas,
        antes=resumo.antes,
        descartes=dict(resumo.descartes),
        avisos=dict(resumo.avisos),
        meses=[f"{mes:%Y-%m}" for mes in resumo.meses],
        veiculos_criados=resumo.veiculos_criados,
        mencoes_ligadas=resumo.mencoes_ligadas,
    )


class OpcoesSaida(BaseModel):
    """O que a tela de Calibração oferece — vem do servidor, não de lista fixa."""

    reguas_de_tier: list[dict]
    reguas_de_engajamento: list[str]
    lentes: list[dict]
    meses: list[str]
    #: Em que mês abrir. NÃO é o último: o CRM põe um mês na lista a cada
    #: interação registrada, e o mais recente costuma ser um mês com uma lente
    #: só — um ISR que é o score da institucional, e quatro lentes vazias.
    mes_sugerido: str | None


@rotas.get("/opcoes")
def opcoes(sessao: Sessao, usuario: UsuarioLogado) -> OpcoesSaida:
    return OpcoesSaida(
        reguas_de_tier=[
            {"codigo": codigo, "pesos": {tier: peso for tier, peso in pesos.items()}}
            for codigo, pesos in REGUAS_DE_TIER.items()
        ],
        reguas_de_engajamento=list(REGUAS_DE_ENGAJAMENTO),
        lentes=[
            {
                "codigo": lente.codigo,
                "nome": lente.nome,
                "stakeholder": lente.stakeholder,
                "peso_padrao": lente.peso_padrao,
            }
            for lente in sessao.scalars(
                select(Lente).where(Lente.ativo.is_(True)).order_by(Lente.ordem)
            )
        ],
        meses=[f"{mes:%Y-%m}" for mes in repositorio_score.meses_com_dado(sessao)],
        mes_sugerido=(
            f"{sugerido:%Y-%m}"
            if (
                sugerido := repositorio_score.mes_mais_completo(
                    sessao, repositorio_score.calibracao_vigente(sessao)
                )
            )
            else None
        ),
    )
