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
    quem: str | None
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
    eventos.sort(key=lambda evento: evento.quando, reverse=True)
    return eventos[:TETO]


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
        .order_by(CargaDeBase.concluida_em.desc())
        .limit(TETO)
    )
    if base is not None:
        consulta = consulta.where(CargaDeBase.base == base)
    return [
        CargaSaida(
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
        for carga, nome_da_fonte, nome_de_quem in sessao.execute(consulta)
    ]


def _das_agendas(sessao, base: str | None) -> list[CargaSaida]:
    """As agendas do CRM, da trilha que elas já tinham (`importacao`, 0008).

    SÓ AS CONFIRMADAS. Uma importação em `processando` ou
    `aguardando_conferencia` não carregou nada ainda, e uma `cancelada` não
    carregou nada nunca — listá-las faria a aba dizer que a base mudou quando
    não mudou.

    `criado_por` E NÃO quem confirmou, porque é o que a tabela guarda: a 0008
    não tem `confirmado_por`. É quem subiu o arquivo, que no fluxo de agendas é
    quase sempre a mesma pessoa que confere — mas não é garantido, e o nome do
    campo aqui não promete mais do que isso.
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
    consulta = (
        select(Importacao, Usuario.nome, func.coalesce(entraram.c.quantas, 0))
        .outerjoin(Usuario, Usuario.id == Importacao.criado_por)
        .outerjoin(entraram, entraram.c.importacao_id == Importacao.id)
        .where(Importacao.situacao == "confirmada", Importacao.confirmado_em.is_not(None))
        .order_by(Importacao.confirmado_em.desc())
        .limit(TETO)
    )
    return [
        CargaSaida(
            base="agendas",
            fonte=None,
            arquivo=importacao.arquivo_nome,
            quem=nome_de_quem,
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
        for importacao, nome_de_quem, quantas in sessao.execute(consulta)
    ]
