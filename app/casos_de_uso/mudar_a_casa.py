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

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
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
    #:
    #: NA CASA ANTIGA, E NÃO "do contato" — achado de revisão com severidade
    #: MÉDIA. A primeira versão contava TODAS as agendas da pessoa, inclusive as
    #: de uma terceira instituição e as da própria casa de destino: o número
    #: inflava a frase da confirmação, que é a única razão de ele existir. Uma
    #: tela que conta errado numa confirmação é pior que uma que não conta.
    #:
    #: SEM CASA ANTIGA É ZERO, por definição: não há casa de onde ficar nada.
    agendas_que_ficam: int
    #: SE O CONTATO SAIU DA FILA DE REVISÃO com esta mudança.
    #:
    #: Achado de revisão, e é um erro de raciocínio meu: eu havia decidido não
    #: mexer na pendência porque "uma mudança deliberada é uma decisão, não uma
    #: dúvida". O outro lado é o que importa — "não precisa marcar dúvida nova;
    #: precisa ENCERRAR a dúvida antiga". O motivo da fila diz literalmente
    #: "confirme se são a mesma pessoa, se ela mudou de casa, ou se são
    #: homônimas": mover É a resposta, e deixar na fila faz a pergunta voltar.
    consolidou: bool


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

    #: O DESTINO TAMBÉM É TRAVADO, e nesta ordem — contato, depois instituição.
    #:
    #: Achado de revisão (BAIXA): sem o lock, uma edição concorrente podia
    #: DESATIVAR a casa depois da conferência e antes do commit, deixando o
    #: contato numa instituição inativa — exatamente o que a recusa abaixo
    #: existe para impedir.
    #:
    #: A ORDEM FIXA é o que evita deadlock: todo caminho deste caso de uso trava
    #: o contato primeiro e a casa depois, então duas chamadas simultâneas
    #: esperam, nunca se cruzam.
    destino = sessao.scalars(
        select(Instituicao).where(Instituicao.id == instituicao_id).with_for_update()
    ).first()
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

    #: AS AGENDAS QUE FICAM NA CASA ANTIGA.
    #:
    #: SEM `outerjoin`, e isto também veio da revisão: a primeira versão juntava
    #: `interacao_interlocutor` e precisava de `count(distinct)` porque o join
    #: MULTIPLICA — uma agenda de três participantes virava três linhas. Com a
    #: participação como subconsulta, cada agenda é uma linha e o `count(*)` é o
    #: número; e o filtro da casa antiga cabe sem acrobacia.
    #:
    #: OS DOIS LUGARES ONDE UM CONTATO PARTICIPA continuam cobertos:
    #: `interacao.interlocutor_id` guarda o principal (67 usos em filtros e
    #: relatórios dependem dele) e `interacao_interlocutor` guarda os demais.
    #: Contar só o primeiro diria "zero agendas" para quem participou de trinta
    #: como acompanhante.
    agendas = 0
    if de_onde is not None:
        agendas = (
            sessao.scalar(
                select(func.count())
                .select_from(InteracaoRegistro)
                .where(
                    InteracaoRegistro.instituicao_id == de_onde.id,
                    or_(
                        InteracaoRegistro.interlocutor_id == contato.id,
                        InteracaoRegistro.id.in_(
                            select(InteracaoInterlocutor.interacao_id).where(
                                InteracaoInterlocutor.interlocutor_id == contato.id
                            )
                        ),
                    ),
                )
            )
            or 0
        )

    #: A PENDÊNCIA SE ENCERRA AQUI, e não vira dúvida nova.
    #:
    #: O motivo que a fila mostrava — "apareceu em N instituições na mesma
    #: planilha, confirme se são a mesma pessoa, se ela mudou de casa, ou se são
    #: homônimas" — foi RESPONDIDO por este gesto. Deixá-lo na fila faria a
    #: pergunta voltar amanhã, com a resposta já dada no dado.
    consolidou = contato.pendente_de_revisao

    #: A MUTAÇÃO FICA DENTRO DO SAVEPOINT, e não antes dele.
    #:
    #: ACHADO DE REVISÃO COM SEVERIDADE MÉDIA, e é sobre o meu conserto anterior:
    #: eu havia posto as três atribuições ANTES de chamar `gravar`, e
    #: `Session.begin_nested()` FAZ FLUSH DO QUE ESTÁ PENDENTE AO ENTRAR no
    #: bloco. O `UPDATE` saía, portanto, antes de o SAVEPOINT existir.
    #:
    #: O QUE ISSO CUSTAVA: a colisão continuava virando `RegraViolada`, porque o
    #: `try` do `gravar` envolve a entrada no bloco — mas a sessão ficava marcada
    #: para rollback, e qualquer leitura depois dali estouraria
    #: `PendingRollbackError`. O savepoint não estava isolando nada; só parecia.
    #:
    #: É EXATAMENTE A LIÇÃO QUE `app/banco/gravar.py` REGISTRA em voz alta — "o
    #: `add` precisa ficar DENTRO do savepoint" — e eu a li, citei no comentário,
    #: e não a apliquei: `gravar` só consegue cumprir a promessa para quem lhe
    #: entrega um objeto NOVO, porque aí o `add` é dele. Num `UPDATE` de objeto já
    #: sujo, ele não tem como pegar a mutação.
    #:
    #: ENTÃO É O SAVEPOINT EXPLÍCITO, a mesma forma de `enquadrar_em_lote`.
    try:
        with sessao.begin_nested():
            contato.instituicao_id = destino.id
            contato.pendente_de_revisao = False
            contato.motivo_da_revisao = None
            sessao.flush()
    except IntegrityError as erro:
        #: A CORRIDA QUE ISTO PEGA: duas sessões movendo contatos de MESMO
        #: `nome_normalizado` para a MESMA casa passam as duas pela conferência
        #: acima, antes de qualquer commit, e uma perde no índice único da `0002`.
        #: A conferência continua valendo — é dela que sai a mensagem que diz o
        #: que fazer —, mas a última palavra é do índice.
        raise RegraViolada(
            f"Já existe um contato chamado {contato.nome!r} em "
            f"{destino.nome!r} — alguém pode ter movido ou cadastrado outro "
            "agora mesmo. Se for a mesma pessoa, a resposta é fundir os dois em "
            "'Possíveis duplicados'."
        ) from erro

    return Mudanca(
        id=str(contato.id),
        nome=contato.nome,
        de=de_onde.nome if de_onde else None,
        para=destino.nome,
        agendas_que_ficam=int(agendas),
        consolidou=consolidou,
    )
