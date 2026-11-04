"""As configurações da plataforma inteira — o que não é de área nenhuma.

Espelha o `PortalDaPlataforma` do front, que até hoje tinha uma aba só
(Gerenciamento de perfis). A segunda é esta: quando cada base foi carregada, e
por quem.

POR QUE AQUI E NÃO NO SCORE. A pergunta atravessa as áreas — menções, bonds,
subtemas e agendas do CRM — e quem a faz é quem administra a plataforma, não
quem opera uma lente. Pendurá-la em `/api/score` faria a aba depender do portal
do Score para mostrar bonds.

O GUARDA É O MESMO DO GERENCIAMENTO DE PERFIS, e no corpo da rota como lá:
`administrar_acessos.exigir_administrador`. Ver `acesso.py`, que faz igual em
`listar_papeis` e `historico` — a permissão de acessos não tem dependência
própria em `dependencias.py`, e inventar uma só para esta rota criaria dois
jeitos de exigir a mesma coisa.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.api.dependencias import UsuarioLogado
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_importacao import Importacao, ImportacaoLinha
from app.banco.tabelas_score import CargaDeBase, ScoreFonte
from app.casos_de_uso import administrar_acessos

rotas = APIRouter(prefix="/api/plataforma", tags=["plataforma"])

Sessao = SessaoDoPedido

#: O teto de linhas que a aba traz. Não há paginação porque não há volume: a
#: carga é um ato humano semanal ou mensal, e 200 eventos cobrem mais de um ano
#: das quatro bases juntas. Paginar antes de haver o que paginar seria complicar
#: a tela por uma suposição.
TETO = 200


class CargaSaida(BaseModel):
    """Um evento de carga, de qualquer base."""

    #: `score`, `bonds`, `subtemas` ou `agendas`. Ver `trilha_da_carga.BASES` —
    #: `agendas` não está lá porque não vem da mesma tabela; ver `_das_agendas`.
    base: str
    #: O nome da fonte, SÓ no Score: é a única base que tem fonte. A tela compõe
    #: o rótulo a partir de `base` e deste campo.
    fonte: str | None
    arquivo: str | None
    #: O nome de quem carregou. NULO É INFORMAÇÃO, não dado faltando: significa
    #: carga feita fora da tela — comando de linha, ou SQL direto. Ver `origem`.
    #:
    #: NAS AGENDAS É QUEM CONFIRMOU (`importacao.confirmado_por`, da `0117`), que
    #: é a pessoa cujo ato fez o dado entrar — e é a mesma a quem `quando` se
    #: refere. Nas confirmadas ANTES da `0117` a coluna é nula e cai em
    #: `criado_por`, que é quem enviou o arquivo; `quem_enviou_o_arquivo` diz
    #: quando isso aconteceu, para a tela não afirmar mais do que sabe.
    quem: str | None
    #: VERDADEIRO quando `quem` é o remetente do arquivo e não quem confirmou —
    #: só nas agendas confirmadas antes da `0117`. A tela usa isto para dizer
    #: "enviado por" em vez de "carregado por", em vez de errar o verbo.
    quem_enviou_o_arquivo: bool = False
    #: A rota ou o comando que carregou. Ver `trilha_da_carga.ORIGENS`.
    origem: str | None
    #: Quantas linhas entraram. ZERO É RESULTADO VÁLIDO: recorte que não achou
    #: veículo nenhum, planilha de bonds só com papel fora do cadastro,
    #: taxonomia reconfirmada sem mudança. É por isso que a trilha existe — os
    #: carimbos das tabelas de dado não andam nesses casos.
    linhas: int
    #: Os meses cobertos. Vazio onde a base não é mensal.
    meses: list[date]
    quando: datetime
    #: Liga as fontes irmãs do mesmo arquivo. Nulo nas agendas, que não têm.
    #:
    #: EXPOSTO PORQUE A TELA AGRUPA POR ELE: uma subida da Clipei alimenta
    #: Imprensa e Mercado e rende duas linhas, e sem o lote a aba mostraria duas
    #: cargas onde houve uma. Não é identificador de recurso — nenhuma rota o
    #: aceita de volta.
    lote_id: UUID | None


@rotas.get("/cargas")
def listar_cargas(
    sessao: Sessao,
    usuario: UsuarioLogado,
    base: Annotated[str | None, Query(description="Filtra por uma base")] = None,
) -> list[CargaSaida]:
    """A última carga de cada base, e as anteriores — a aba da plataforma.

    DUAS FONTES DE VERDADE, de propósito. `carga_de_base` (0115/0116) guarda as
    bases que sobem por arquivo; as agendas do CRM já tinham a sua em
    `importacao`, com `criado_por` e `confirmado_em`, e copiá-las para a tabela
    nova criaria uma segunda verdade sobre o mesmo fato. A união é aqui.

    DIZ "CARGA" E NÃO "ATUALIZAÇÃO", e a diferença é real: a reconciliação da
    lista de veículos, a edição de jornalista e a fusão de atores alteram menção
    por fora da ingestão e não aparecem aqui. Chamar isto de última atualização
    faria a tela afirmar o que a trilha não sabe.
    """
    administrar_acessos.exigir_administrador(usuario)

    eventos = _da_trilha(sessao, base) + _das_agendas(sessao, base)
    #: ORDENADO AQUI, e não no banco: são duas consultas de tabelas diferentes, e
    #: ordenar em SQL exigiria uma `union` que amarraria as duas formas — a hora
    #: de uma é `concluida_em`, a da outra `confirmado_em`.
    #:
    #: O CORTE É CORRETO apesar de serem duas consultas: cada uma traz os `TETO`
    #: mais recentes da sua tabela, e um evento que esteja entre os `TETO` mais
    #: recentes do TOTAL está necessariamente entre os `TETO` da sua própria
    #: tabela — logo o corte final devolve exatamente os `TETO` globais.
    eventos.sort(key=lambda evento: evento.quando, reverse=True)
    eventos = eventos[:TETO]
    return eventos + _irmas_que_o_corte_separou(sessao, eventos)


def _irmas_que_o_corte_separou(sessao, eventos: list[CargaSaida]) -> list[CargaSaida]:
    """As irmãs de lote que ficaram do lado de fora do corte.

    O DEFEITO QUE ISTO CONSERTA. A tela agrupa por `lote_id` para mostrar uma
    subida da Clipei como UMA carga em vez de duas. Se as duas irmãs caírem em
    lados opostos do corte, o grupo chega com uma fonte só e uma soma parcial —
    e a tela não teria como saber, então mostraria um número menor como se fosse
    o total. Numa trilha que existe para ser confiável, esse é o pior tipo de
    erro: silencioso e plausível.

    DEVOLVER UM LOTE INCOMPLETO É PIOR QUE DEVOLVER MAIS QUE `TETO` LINHAS. O
    excedente é no máximo o número de fontes irmãs do arquivo mais largo — hoje
    duas — por lote na fronteira, e a alternativa seria a soma mentir.
    """
    lotes = {evento.lote_id for evento in eventos if evento.lote_id is not None}
    if not lotes:
        return []
    ja_vieram = {
        (evento.lote_id, evento.fonte) for evento in eventos if evento.lote_id is not None
    }
    consulta = (
        select(CargaDeBase, ScoreFonte.nome, Usuario.nome)
        .outerjoin(ScoreFonte, ScoreFonte.id == CargaDeBase.fonte_id)
        .outerjoin(Usuario, Usuario.id == CargaDeBase.usuario_id)
        .where(CargaDeBase.lote_id.in_(lotes))
        .order_by(CargaDeBase.concluida_em.desc(), CargaDeBase.id.desc())
    )
    return [
        _da_linha(carga, nome_da_fonte, nome_de_quem)
        for carga, nome_da_fonte, nome_de_quem in sessao.execute(consulta)
        if (carga.lote_id, nome_da_fonte) not in ja_vieram
    ]


#: As bases que a aba conhece, NA ORDEM EM QUE A TELA AS MOSTRA.
#:
#: `agendas` ENTRA AQUI e não em `trilha_da_carga.BASES`: aquela lista é das
#: bases que escrevem em `carga_de_base`, e as agendas têm trilha própria. Esta é
#: a lista do que a ABA cobre, e são as duas coisas que a tela precisa saber.
BASES_DA_ABA = ("score", "bonds", "subtemas", "agendas")


class ResumoDaBaseSaida(BaseModel):
    """O estado de uma base, para a tela poder dizer "sem registro"."""

    base: str
    #: Quantas cargas a base já teve, SEM TETO: é a contagem de verdade.
    cargas: int
    #: A mais recente. Nula quando `cargas` é zero.
    ultima_em: datetime | None


@rotas.get("/cargas/resumo")
def resumir_cargas(sessao: Sessao, usuario: UsuarioLogado) -> list[ResumoDaBaseSaida]:
    """Quantas cargas cada base já teve, e quando foi a última.

    POR QUE ISTO EXISTE SEPARADO DA LISTAGEM, e é conserto de um defeito real: a
    listagem é histórico com teto, e a tela estava inferindo "esta base nunca foi
    carregada" de "esta base não apareceu nas últimas 200 cargas". Uma base com
    cargas só antigas, empurradas para fora do teto por 200 eventos mais recentes
    de outra, apareceria como nunca carregada — uma afirmação falsa, e justamente
    sobre o caso em que alguém precisa agir.

    SEM TETO AQUI porque é agregado: quatro linhas, uma por base, qualquer que
    seja o volume. E a resposta traz TODAS as bases, inclusive as com zero — é o
    que permite à tela avisar em vez de ficar calada.
    """
    administrar_acessos.exigir_administrador(usuario)

    da_trilha = {
        base: (quantas, ultima)
        for base, quantas, ultima in sessao.execute(
            select(
                CargaDeBase.base,
                func.count(),
                func.max(CargaDeBase.concluida_em),
            ).group_by(CargaDeBase.base)
        )
    }
    das_agendas = sessao.execute(
        select(func.count(), func.max(Importacao.confirmado_em)).where(
            Importacao.situacao == "confirmada", Importacao.confirmado_em.is_not(None)
        )
    ).one()
    da_trilha["agendas"] = (das_agendas[0], das_agendas[1])

    return [
        ResumoDaBaseSaida(
            base=base,
            cargas=da_trilha.get(base, (0, None))[0],
            ultima_em=da_trilha.get(base, (0, None))[1],
        )
        for base in BASES_DA_ABA
    ]


def _da_trilha(sessao, base: str | None) -> list[CargaSaida]:
    """As bases que sobem por arquivo: Score, bonds e subtemas."""
    if base == "agendas":
        return []
    consulta = (
        select(CargaDeBase, ScoreFonte.nome, Usuario.nome)
        #: `outerjoin` NOS DOIS: fonte só existe no Score, e usuário é nulo em
        #: carga feita por comando. Um `join` comum esconderia justamente as
        #: linhas que mais interessam numa trilha.
        .outerjoin(ScoreFonte, ScoreFonte.id == CargaDeBase.fonte_id)
        .outerjoin(Usuario, Usuario.id == CargaDeBase.usuario_id)
        #: `id` DESEMPATA para a ordem ser ESTÁVEL, não cronológica: `id` é uuid4
        #: e num empate exato a escolha é arbitrária. O que isto evita é a aba
        #: trocar de ordem entre dois carregamentos do mesmo dado, que parece
        #: corrupção e não é.
        .order_by(CargaDeBase.concluida_em.desc(), CargaDeBase.id.desc())
        .limit(TETO)
    )
    if base is not None:
        consulta = consulta.where(CargaDeBase.base == base)
    return [
        _da_linha(carga, nome_da_fonte, nome_de_quem)
        for carga, nome_da_fonte, nome_de_quem in sessao.execute(consulta)
    ]


def _da_linha(carga: CargaDeBase, nome_da_fonte: str | None, nome_de_quem: str | None):
    """Uma linha de `carga_de_base` no formato da saída.

    EXTRAÍDA PORQUE SÃO DOIS CHAMADORES: a listagem e o remendo dos lotes que o
    corte separou. Duas cópias seriam a forma de uma delas esquecer um campo.
    """
    return CargaSaida(
        base=carga.base,
        fonte=nome_da_fonte,
        arquivo=carga.arquivo,
        quem=nome_de_quem,
        origem=carga.origem,
        linhas=carga.linhas,
        meses=carga.meses,
        quando=carga.concluida_em,
        lote_id=carga.lote_id,
    )


def _das_agendas(sessao, base: str | None) -> list[CargaSaida]:
    """As agendas do CRM, da trilha que elas já tinham (`importacao`, 0008).

    SÓ AS CONFIRMADAS. Uma importação em `processando` ou
    `aguardando_conferencia` não carregou nada ainda, e uma `cancelada` não
    carregou nada nunca — listá-las faria a aba dizer que a base mudou quando
    não mudou.

    QUEM CONFIRMOU, da `0117`. Antes dela a tabela só guardava quem SUBIU, e
    `importar_agendas.confirmar` não exige que seja a mesma pessoa — então a
    linha mostrava a hora de quem confirmou com o nome de quem enviou. Nas
    confirmadas antes da `0117` a coluna é nula e a leitura cai em `criado_por`,
    marcando `quem_enviou_o_arquivo` para a tela trocar o verbo.
    """
    if base is not None and base != "agendas":
        return []
    #: QUANTAS LINHAS VIRARAM INTERAÇÃO, que é o que "entrou" significa aqui: a
    #: importação guarda as linhas descartadas junto com as aceitas, e contar
    #: todas faria uma planilha majoritariamente recusada parecer uma carga
    #: grande.
    entraram = (
        select(
            ImportacaoLinha.importacao_id,
            func.count().label("quantas"),
        )
        .where(ImportacaoLinha.interacao_id.is_not(None))
        .group_by(ImportacaoLinha.importacao_id)
        .subquery()
    )
    #: QUEM CONFIRMOU, com queda para quem enviou. São dois `outerjoin` na MESMA
    #: tabela, então o segundo precisa de apelido — sem ele o SQL casaria os dois
    #: na primeira junção e o nome viria sempre de `confirmado_por`, inclusive
    #: quando ela é nula.
    quem_confirmou = aliased(Usuario)
    quem_enviou = aliased(Usuario)
    consulta = (
        select(
            Importacao,
            quem_confirmou.nome,
            quem_enviou.nome,
            func.coalesce(entraram.c.quantas, 0),
        )
        .outerjoin(quem_confirmou, quem_confirmou.id == Importacao.confirmado_por)
        .outerjoin(quem_enviou, quem_enviou.id == Importacao.criado_por)
        .outerjoin(entraram, entraram.c.importacao_id == Importacao.id)
        .where(Importacao.situacao == "confirmada", Importacao.confirmado_em.is_not(None))
        #: `id` DESEMPATA, pela mesma razão da outra consulta.
        .order_by(Importacao.confirmado_em.desc(), Importacao.id.desc())
        .limit(TETO)
    )
    return [
        CargaSaida(
            base="agendas",
            fonte=None,
            arquivo=importacao.arquivo_nome,
            #: `is not None` E NÃO `or`: nome vazio é dado ruim, mas é dado — cair
            #: no remetente por causa dele trocaria o nome E o verbo, dizendo
            #: "enviado por" sobre uma importação que tem quem confirmou.
            quem=nome_confirmou if nome_confirmou is not None else nome_enviou,
            #: O VERBO MUDA quando o nome é do remetente: só nas confirmadas
            #: antes da `0117`, que não têm `confirmado_por`.
            quem_enviou_o_arquivo=nome_confirmou is None and nome_enviou is not None,
            #: A IMPORTAÇÃO DE AGENDAS SÓ ACONTECE PELA TELA, então a origem é
            #: constante — não há um campo equivalente na 0008 para ler.
            origem="api:agendas",
            linhas=quantas,
            #: A agenda é datada por reunião, não por mês de referência: não há
            #: período a declarar.
            meses=[],
            quando=importacao.confirmado_em,
            lote_id=None,
        )
        for importacao, nome_confirmou, nome_enviou, quantas in sessao.execute(consulta)
    ]
