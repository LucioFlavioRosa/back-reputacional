"""Mover um contato para outra instituição — a mudança de casa.

POR QUE ISTO NÃO É EDITAR UM CAMPO, e é a razão de ter caso de uso próprio: a
`0002` cria `unique (nome_normalizado, instituicao_id)` com o comentário "mesmo
nome em instituições diferentes são pessoas diferentes". A instituição não é um
atributo do contato: é parte da IDENTIDADE dele neste modelo.

Então trocá-la num `<select>` ao lado do cargo seria oferecer, com o mesmo peso
de corrigir um e-mail, uma afirmação de outra natureza — "esta pessoa é a mesma
que eu tinha registrado em outra casa". O modal da fila de revisão
deliberadamente NÃO oferece o campo, e aponta para cá.

O QUE O DONO DO PRODUTO PEDIU: "siga com mover contato". E o caso real existe —
Nikolau Muller apareceu em JGP Gestão e Leto Capital na mesma planilha de RI, e a
leitura mais provável é que ele mudou de casa.

== O HISTÓRICO NÃO SE MEXE, e foi o que eu fui conferir antes de escrever ==

`interacao.instituicao_id` é coluna PRÓPRIA da agenda, separada de
`interacao.interlocutor_id` e de `interacao_interlocutor`. Mover o contato NÃO
reescreve a casa de nenhuma agenda passada: a reunião continua registrada como
tendo sido com a JGP, porque era.

E ISSO É O CERTO. Uma pessoa que trocou de emprego participou daquelas reuniões
pela casa antiga; reescrever isso apagaria o fato. O que a mudança diz é "de hoje
em diante, ela fala pela Leto" — e as agendas antigas são a prova de que a
mudança aconteceu.

A CONTAGEM VOLTA NA RESPOSTA por isso: quem confirma a mudança precisa saber
quantas agendas ficam na casa antiga, porque é essa frase que distingue "mudou de
casa" de "eu errei a instituição no cadastro".
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.banco.tabelas_interacoes import InteracaoInterlocutor, InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor
from app.dominio.erros import NaoEncontrado, RegraViolada


@dataclass(frozen=True)
class Mudanca:
    """O que aconteceu, para a tela poder contar a história de volta."""

    id: str
    nome: str
    #: A casa de onde saiu. Nulo quando o contato não tinha nenhuma — o que
    #: acontece com quem a planilha criou sem instituição na linha.
    de: str | None
    para: str
    #: QUANTAS AGENDAS FICAM NA CASA ANTIGA. É a frase que distingue "mudou de
    #: casa" de "eu errei a instituição no cadastro": com zero agendas, a
    #: segunda leitura é a provável.
    agendas_que_ficam: int


def mudar(
    sessao: Session, *, interlocutor_id: UUID, instituicao_id: UUID
) -> Mudanca:
    """Passa o contato para outra instituição, e diz o que ficou atrás."""
    #: `with_for_update`: a mesma disciplina do lote, e pela mesma razão. Duas
    #: pessoas movendo o mesmo contato para casas diferentes, lendo antes de
    #: qualquer commit, teriam as duas respondido 200 — e a última gravação
    #: venceria em silêncio.
    contato = sessao.scalars(
        select(Interlocutor).where(Interlocutor.id == interlocutor_id).with_for_update()
    ).first()
    if contato is None:
        raise NaoEncontrado("Contato não encontrado.")

    destino = sessao.get(Instituicao, instituicao_id)
    if destino is None:
        raise NaoEncontrado("Instituição de destino não encontrada.")
    if not destino.ativo:
        #: RECUSA EXPLÍCITA, e não a FK: o banco aceitaria, e o contato ficaria
        #: numa casa desativada — invisível na listagem padrão, que filtra os
        #: dois níveis. Mover para lá é esconder a pessoa sem dizer isso.
        raise RegraViolada(
            f"{destino.nome!r} está desativada. Reative-a pela Administração "
            "antes de mover alguém para lá."
        )
    if contato.instituicao_id == destino.id:
        raise RegraViolada(f"{contato.nome!r} já fala por {destino.nome!r}.")

    #: O MESMO NOME JÁ NA CASA DE DESTINO.
    #:
    #: O índice único da `0002` é `(nome_normalizado, instituicao_id)` e NÃO é
    #: parcial em `ativo`: um contato desativado continua ocupando o par. Sem
    #: esta conferência o `flush` estoura em `IntegrityError` — 500 para quem
    #: clicou, e sem dizer que já existe alguém com aquele nome lá.
    #:
    #: E A RECUSA APONTA PARA A FILA DE DUPLICADOS, porque é a pergunta certa:
    #: se há um "Nikolau Muller" na Leto e outro na JGP, mover um para cima do
    #: outro não é mudança de casa, é fusão — e fundir é decisão de quem conhece
    #: as duas linhas.
    ja_esta_la = sessao.scalars(
        select(Interlocutor).where(
            Interlocutor.nome_normalizado == contato.nome_normalizado,
            Interlocutor.instituicao_id == destino.id,
            Interlocutor.id != contato.id,
        )
    ).first()
    if ja_esta_la is not None:
        raise RegraViolada(
            f"Já existe um contato chamado {ja_esta_la.nome!r} em "
            f"{destino.nome!r} — pode estar desativado. Se for a mesma pessoa, "
            "a resposta é fundir os dois em 'Possíveis duplicados', e não mover "
            "um para cima do outro."
        )

    de_onde = (
        sessao.get(Instituicao, contato.instituicao_id)
        if contato.instituicao_id
        else None
    )

    #: AS AGENDAS QUE FICAM, contadas nos DOIS lugares onde um contato participa:
    #: `interacao.interlocutor_id` guarda o principal (67 usos em filtros e
    #: relatórios dependem dele) e `interacao_interlocutor` guarda os demais.
    #: Contar só o primeiro diria "zero agendas" para quem participou de trinta
    #: como acompanhante.
    agendas = (
        sessao.scalar(
            select(InteracaoRegistro.id.distinct().label("id"))
            .outerjoin(
                InteracaoInterlocutor,
                InteracaoInterlocutor.interacao_id == InteracaoRegistro.id,
            )
            .where(
                or_(
                    InteracaoRegistro.interlocutor_id == contato.id,
                    InteracaoInterlocutor.interlocutor_id == contato.id,
                )
            )
            .with_only_columns(_contar_distintas())
        )
        or 0
    )

    contato.instituicao_id = destino.id
    sessao.flush()

    return Mudanca(
        id=str(contato.id),
        nome=contato.nome,
        de=de_onde.nome if de_onde else None,
        para=destino.nome,
        agendas_que_ficam=int(agendas),
    )


def _contar_distintas():
    """`count(distinct interacao.id)`, isolado porque o `outerjoin` multiplica.

    Uma agenda com três participantes vira três linhas no join, e um `count(*)`
    diria três agendas onde há uma.
    """
    from sqlalchemy import distinct, func

    return func.count(distinct(InteracaoRegistro.id))
