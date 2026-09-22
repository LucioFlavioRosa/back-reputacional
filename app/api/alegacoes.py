"""As alegações que circulam no mercado — o que as perguntas dão como fato.

POR QUE É ROTA PRÓPRIA, E NÃO UM DICIONÁRIO
-------------------------------------------
Um dicionário é vocabulário fechado que alguém administra antes de usar. Uma
alegação NASCE DO REGISTRO: ela aparece quando chega o e-mail, e quem a
cadastra é quem está registrando a consulta — não a coordenação, depois. Por
isso tem rota própria, com `POST` liberado a quem escreve interação.

Depois disso ela vira um objeto administrado: a área apura, muda o status e
amarra o posicionamento que responde. Esse lado exige `administra_cadastros`,
como referência e instituição.

NÃO HÁ `DELETE`. A alegação é o histórico do que circulou; apagá-la
reescreveria a leitura de um período que já foi lido — inclusive a contagem
que a tela usou para afirmar que algo estava circulando. Sai de circulação
com `ativo=false`, como instituição e contato.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencias import (
    UsuarioLogado,
    UsuarioQueAdministraCadastros,
    UsuarioQueEscreve,
    exigir_portal_crm,
)
from app.banco.gravar import gravar
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_alegacoes import Alegacao, AlegacaoTema
from app.banco.tabelas_catalogo import Apuracao
from app.banco.tabelas_interacoes import InteracaoAlegacao
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.texto import normalizar

rotas = APIRouter(
    prefix="/api/alegacoes",
    tags=["alegacoes"],
    dependencies=[Depends(exigir_portal_crm)],
)

Sessao = SessaoDoPedido

#: Com o que uma alegação nasce quando ninguém disse o contrário: ninguém
#: apurou nada ainda, e dizer "sem fundamento" por omissão seria afirmar o que
#: não se verificou.
APURACAO_INICIAL = "em_apuracao"


class AlegacaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A premissa em uma frase, na voz de quem alega.
    texto: str = Field(min_length=8)
    temas: list[int] = Field(default_factory=list)
    #: Nulo na criação = `em_apuracao`.
    apuracao_id: int | None = None
    #: O posicionamento da biblioteca que responde a esta alegação.
    referencia_id: UUID | None = None
    nota: str | None = None
    ativo: bool = True


class AlegacaoSaida(BaseModel):
    id: UUID
    texto: str
    temas: list[int]
    apuracao_id: int
    referencia_id: UUID | None
    nota: str | None
    ativo: bool
    criado_em: datetime | None
    #: EM QUANTAS CONSULTAS esta alegação já apareceu — a contagem inteira, e
    #: não a do recorte: a tela usa para ordenar a administração, e quem
    #: precisa da leitura por período conta as consultas do recorte.
    consultas: int


def _apuracao_inicial(sessao: Session) -> int:
    id_ = sessao.scalar(select(Apuracao.id).where(Apuracao.codigo == APURACAO_INICIAL))
    if id_ is None:  # pragma: no cover - a 0046 semeia os quatro
        raise RegraViolada("O dicionário de apuração está vazio.")
    return id_


def _saida(
    registro: Alegacao,
    temas: dict[UUID, list[int]],
    consultas: dict[UUID, int],
) -> AlegacaoSaida:
    return AlegacaoSaida(
        id=registro.id,
        texto=registro.texto,
        temas=sorted(temas.get(registro.id, [])),
        apuracao_id=registro.apuracao_id,
        referencia_id=registro.referencia_id,
        nota=registro.nota,
        ativo=registro.ativo,
        criado_em=registro.criado_em,
        consultas=consultas.get(registro.id, 0),
    )


def _temas_por_alegacao(sessao: Session) -> dict[UUID, list[int]]:
    """Os vínculos de todas as alegações de uma vez — a lista inteira cabe em
    uma consulta, e por linha seria N+1 numa tela que mostra dezenas."""
    por_alegacao: dict[UUID, list[int]] = {}
    for alegacao_id, tema_id in sessao.execute(
        select(AlegacaoTema.alegacao_id, AlegacaoTema.tema_id)
    ):
        por_alegacao.setdefault(alegacao_id, []).append(tema_id)
    return por_alegacao


def _consultas_por_alegacao(sessao: Session) -> dict[UUID, int]:
    return {
        alegacao_id: total
        for alegacao_id, total in sessao.execute(
            select(InteracaoAlegacao.alegacao_id, func.count())
            .group_by(InteracaoAlegacao.alegacao_id)
        )
    }


def _casar_temas(sessao: Session, registro: Alegacao, desejados: list[int]) -> None:
    """Mantém quem continua, acrescenta quem entrou, apaga quem saiu."""
    atuais = {
        vinculo.tema_id: vinculo
        for vinculo in sessao.scalars(
            select(AlegacaoTema).where(AlegacaoTema.alegacao_id == registro.id)
        )
    }
    for tema_id, vinculo in atuais.items():
        if tema_id not in desejados:
            sessao.delete(vinculo)
    for tema_id in desejados:
        if tema_id not in atuais:
            sessao.add(AlegacaoTema(alegacao_id=registro.id, tema_id=tema_id))


@rotas.get("")
def listar(
    sessao: Sessao,
    usuario: UsuarioLogado,
    incluir_inativas: Annotated[
        bool,
        Query(description="1 traz também as que saíram de circulação"),
    ] = False,
) -> list[AlegacaoSaida]:
    """As alegações, da mais recente para a mais antiga.

    INATIVAS TAMBÉM, quando pedido: sem elas a alegação desativada some da
    administração e volta como "já existe" na próxima tentativa de cadastrar a
    mesma frase — o índice único é sobre o texto normalizado, e não sobre o
    texto que a pessoa vê.
    """
    consulta = select(Alegacao).order_by(Alegacao.criado_em.desc())
    if not incluir_inativas:
        consulta = consulta.where(Alegacao.ativo.is_(True))

    temas = _temas_por_alegacao(sessao)
    consultas = _consultas_por_alegacao(sessao)
    return [_saida(registro, temas, consultas) for registro in sessao.scalars(consulta)]


@rotas.post("", status_code=status.HTTP_201_CREATED)
def criar(
    sessao: Sessao, usuario: UsuarioQueEscreve, entrada: AlegacaoEntrada
) -> AlegacaoSaida:
    """Quem registra a consulta cadastra a alegação que ela trouxe.

    O índice único é sobre o TEXTO NORMALIZADO: a mesma frase com outra
    acentuação é a mesma alegação, e deixá-la entrar duas vezes partiria em
    duas a contagem que a tela existe para fazer.
    """
    texto = entrada.texto.strip()
    registro = Alegacao(
        id=uuid.uuid4(),
        texto=texto,
        texto_normalizado=normalizar(texto),
        apuracao_id=entrada.apuracao_id or _apuracao_inicial(sessao),
        referencia_id=entrada.referencia_id,
        nota=entrada.nota,
        ativo=entrada.ativo,
        criado_por=usuario.id,
    )
    gravar(
        sessao,
        registro,
        ao_colidir="Esta alegação já está cadastrada.",
        novo=True,
    )
    _casar_temas(sessao, registro, entrada.temas)
    sessao.flush()
    return _saida(
        registro, {registro.id: entrada.temas}, _consultas_por_alegacao(sessao)
    )


@rotas.put("/{id}")
def editar(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    entrada: AlegacaoEntrada,
) -> AlegacaoSaida:
    """Apurar é trabalho da área: muda o status, amarra o posicionamento que
    responde e escreve o que se verificou."""
    registro = sessao.get(Alegacao, id)
    if registro is None:
        raise NaoEncontrado("Alegação não encontrada.")

    texto = entrada.texto.strip()
    registro.texto = texto
    registro.texto_normalizado = normalizar(texto)
    if entrada.apuracao_id is not None:
        registro.apuracao_id = entrada.apuracao_id
    registro.referencia_id = entrada.referencia_id
    registro.nota = entrada.nota
    registro.ativo = entrada.ativo
    registro.atualizado_em = datetime.now(UTC)

    gravar(sessao, registro, ao_colidir="Esta alegação já está cadastrada.")
    _casar_temas(sessao, registro, entrada.temas)
    sessao.flush()
    return _saida(
        registro, {registro.id: entrada.temas}, _consultas_por_alegacao(sessao)
    )
