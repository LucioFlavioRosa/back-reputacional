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

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.api.dependencias import (
    UsuarioLogado,
    UsuarioQueAdministraCadastros,
    exigir_portal_score,
)
from app.banco import repositorio_score
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_score import Lente, ScoreConfig, ScoreFato, ScoreFonte, ScoreMesFonte
from app.casos_de_uso import ingerir_mencoes
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.score import (
    REGUAS_DE_ENGAJAMENTO,
    REGUAS_DE_TIER,
    Calibracao,
    Indice,
)

rotas = APIRouter(
    prefix="/api/score",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido


class LenteSaida(BaseModel):
    codigo: str
    nome: str
    peso: int
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


class CalibracaoSaida(BaseModel):
    pesos: dict[str, int]
    regua_tier: str
    regua_engajamento: str
    fontes_desligadas: list[str]
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


def _mes_de(texto: str) -> date:
    """`2026-06` vira o primeiro dia do mês."""
    try:
        ano, mes = texto.split("-")
        return date(int(ano), int(mes), 1)
    except (ValueError, TypeError) as erro:
        raise RegraViolada(
            f"Mês inválido: {texto!r}. Use o formato AAAA-MM."
        ) from erro


def _calibracao_saida(sessao, calibracao: Calibracao) -> CalibracaoSaida:
    padrao = repositorio_score.pesos_padrao(sessao)
    return CalibracaoSaida(
        pesos=calibracao.pesos,
        regua_tier=calibracao.regua_tier,
        regua_engajamento=calibracao.regua_engajamento,
        fontes_desligadas=sorted(calibracao.fontes_desligadas),
        padrao=(
            calibracao.pesos == padrao
            and calibracao.regua_tier == "aegea"
            and calibracao.regua_engajamento == "n"
            and not calibracao.fontes_desligadas
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
    anterior = repositorio_score.indice_do_mes(
        sessao, _mes_anterior(alvo), calibracao
    )

    meses = repositorio_score.meses_com_dado(sessao)
    primeiro = (
        repositorio_score.indice_do_mes(sessao, meses[0], calibracao)
        if meses else indice
    )

    scores_anteriores = {lente.codigo: lente.score for lente in anterior.lentes}
    lentes = [
        LenteSaida(
            codigo=lente.codigo,
            nome=lente.nome,
            peso=lente.peso,
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
        mes.replace(year=mes.year - 1, month=12) if mes.month == 1
        else mes.replace(month=mes.month - 1)
    )


def _fatos_do_mes(sessao, mes: date) -> list[FatoSaida]:
    registros = sessao.scalars(
        select(ScoreFato).where(ScoreFato.mes == mes).order_by(ScoreFato.criado_em)
    )
    return [
        FatoSaida(id=f.id, mes=f"{f.mes:%Y-%m}", texto=f.texto, efeito=f.efeito)
        for f in registros
    ]


@rotas.get("/serie")
def serie(sessao: Sessao, usuario: UsuarioLogado) -> list[PontoDaSerie]:
    """A evolução mensal do índice, com a régua vigente.

    TODOS OS MESES COM A MESMA RÉGUA: recalcular o passado com a calibração de
    hoje é o que torna a curva comparável. Guardar o score de cada mês com a
    régua da época faria a linha subir e descer por mudança de critério.
    """
    calibracao = repositorio_score.calibracao_vigente(sessao)
    pontos = []
    for mes in repositorio_score.meses_com_dado(sessao):
        indice = repositorio_score.indice_do_mes(sessao, mes, calibracao)
        pontos.append(
            PontoDaSerie(
                mes=indice.mes,
                isr=indice.isr,
                lentes=len(indice.lentes_no_calculo),
                tem_estimativa=any(
                    lente.estimado for lente in indice.lentes_no_calculo
                ),
            )
        )
    return pontos


class FonteSaida(BaseModel):
    codigo: str
    nome: str
    fornecedor: str
    lente: str
    interna: bool
    ativo: bool
    #: Se a calibração vigente a desligou.
    ligada: bool
    observacao: str | None
    #: Quantos meses têm dado desta fonte, e quantas menções no mês pedido.
    meses_com_dado: int
    mencoes_no_mes: int


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
        set(
            sessao.scalars(
                select(ScoreMesFonte.mes).where(ScoreMesFonte.fonte_id == fonte_id)
            )
        )
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
        (m for m in repositorio_score.medir_lentes(sessao, alvo, calibracao)
         if m.codigo == codigo),
        None,
    )
    if medida is None:  # pragma: no cover - `medir_lentes` cobre as ativas
        raise NaoEncontrado(f"Lente {codigo!r} não está ativa.")

    composicao = repositorio_score.composicao_da_lente(
        sessao, lente.id, alvo, calibracao
    )
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
                codigo=fonte.codigo, nome=fonte.nome, ns=ns_da_fonte, mencoes=mencoes,
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
            f"{base} Cada matéria vale {pesos['muito_relevante']:g} (Muito "
            f"Relevante), {pesos['relevante']:g} (Relevante) ou "
            f"{pesos['menos_relevante']:g} (Menos Relevante)."
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
            "a lente é a média simples dos NS."
        )
    return f"{base} Vem do clima das interações registradas neste painel."


class CalibracaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pesos: dict[str, int] = Field(default_factory=dict)
    regua_tier: str = "aegea"
    regua_engajamento: str = "n"
    fontes_desligadas: list[str] = Field(default_factory=list)


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
    )
    conhecidas = {fonte.codigo for fonte in repositorio_score.fontes_cadastradas(sessao)}
    desconhecidas = sorted(calibracao.fontes_desligadas - conhecidas)
    if desconhecidas:
        raise RegraViolada(
            f"Fonte não cadastrada: {', '.join(desconhecidas)}."
        )
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
            criado_por=usuario.id,
        )
    )
    sessao.flush()
    return _calibracao_saida(sessao, repositorio_score.calibracao_vigente(sessao))


@rotas.delete("/calibracao", status_code=status.HTTP_201_CREATED)
def restaurar_padrao(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros
) -> CalibracaoSaida:
    """"Restaurar padrão" (§3): grava uma versão com a régua de fábrica.

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
        raise RegraViolada(
            f"Efeito inválido: {entrada.efeito!r}. Use {', '.join(EFEITOS)}."
        )
    registro = ScoreFato(
        mes=_mes_de(entrada.mes),
        texto=entrada.texto.strip(),
        efeito=entrada.efeito,
        criado_por=usuario.id,
    )
    sessao.add(registro)
    sessao.flush()
    return FatoSaida(
        id=registro.id, mes=f"{registro.mes:%Y-%m}", texto=registro.texto,
        efeito=registro.efeito,
    )


@rotas.delete("/fatos/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_fato(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, id: UUID
) -> None:
    registro = sessao.get(ScoreFato, id)
    if registro is None:
        raise NaoEncontrado("Fato não encontrado.")
    sessao.execute(delete(ScoreFato).where(ScoreFato.id == id))


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


@rotas.post("/fontes/{codigo}/planilha", status_code=status.HTTP_201_CREATED)
def importar_planilha(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    codigo: str,
    arquivo: Annotated[UploadFile, File()],
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
        ImportacaoSaida(
            fonte=resumo.fonte,
            nome=resumo.nome,
            linhas=resumo.linhas,
            ingeridas=resumo.ingeridas,
            antes=resumo.antes,
            descartes=dict(resumo.descartes),
            avisos=dict(resumo.avisos),
            meses=[f"{mes:%Y-%m}" for mes in resumo.meses],
        )
        for resumo in ingerir_mencoes.ingerir(sessao, fonte, arquivo.file.read())
    ]


class OpcoesSaida(BaseModel):
    """O que a tela de Calibração oferece — vem do servidor, não de lista fixa."""

    reguas_de_tier: list[dict]
    reguas_de_engajamento: list[str]
    lentes: list[dict]
    meses: list[str]


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
    )


def _fontes_da_lente(sessao, lente_codigo: str) -> list[ScoreFonte]:  # pragma: no cover
    return list(
        sessao.scalars(
            select(ScoreFonte)
            .join(Lente, Lente.id == ScoreFonte.lente_id)
            .where(Lente.codigo == lente_codigo)
            .order_by(ScoreFonte.ordem)
        )
    )
