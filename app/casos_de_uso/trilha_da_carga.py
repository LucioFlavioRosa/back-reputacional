"""Quem carregou o quê, quando, e quanto entrou. Espelha a `0115` e a `0116`.

POR QUE A TRILHA EXISTE. "Quando esta base foi atualizada, e por quem" não tinha
resposta: o "quando" parecia estar nos carimbos das próprias tabelas e não está
— a ingestão APAGA e reinsere, então uma carga legítima de zero linha não move
carimbo nenhum —, e o "quem" era apagado junto com a planilha recebida, nas três
bases que sobem por arquivo.

ESCRITA PELA APLICAÇÃO, e não por gatilho como as trilhas da `0005`. Um gatilho
vê linhas mudando; não sabe de que arquivo vieram, quem mandou, nem que fontes
irmãs o mesmo arquivo alimentou — e não distingue carga de reconciliação.

É O QUE OBRIGA O `revoke` EXPLÍCITO. A rede automática de
`test_nenhuma_trilha_e_gravavel_pela_aplicacao` varre tabelas `*_auditoria` e
exige que `painel_app` não tenha `insert`; aqui o `insert` é o ponto. Por isso o
nome fica fora do sufixo e a imutabilidade vem do `revoke update, delete` da
`0115`, cobrado por teste próprio.

O QUE A TRILHA NÃO COBRE: só a CARGA. Reconciliação da lista de veículos, edição
de jornalista e fusão de atores alteram menção por fora da ingestão. Por isso a
tela diz "última carga", e não "última atualização".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.banco.tabelas_score import CargaDeBase

#: As bases que sobem por arquivo e registram carga aqui. LISTA FECHADA TAMBÉM
#: NO BANCO (`check carga_de_base_base_conhecida`, na `0116`), ao contrário de
#: `ORIGENS`: base é discriminador — a aba decide o que mostrar por ela, e um
#: typo deixaria a carga invisível. Base nova é migration, e precisa ser.
#:
#: AS AGENDAS DO CRM NÃO ESTÃO AQUI porque `importacao` já sobrevive à
#: confirmação com `criado_por`, `criado_em` e `confirmado_em`. Copiá-las para
#: esta tabela criaria uma segunda verdade sobre o mesmo fato; a aba lê as duas.
BASES = (
    #: As fontes de menção. É a única base com `fonte_id` — ver o `check` da `0116`.
    "score",
    #: As cotações dos papéis.
    "bonds",
    #: A taxonomia de subtemas.
    "subtemas",
)

#: As origens que existem hoje, para quem lê a aba saber o que esperar. NÃO É
#: LISTA FECHADA: a `0115` não tem `check`, de propósito — chamador novo não deve
#: precisar de migration.
ORIGENS = (
    "api:planilha",
    "api:bonds",
    "api:subtemas",
    "carga_do_pacote",
    #: Chamador que não se identificou — ver `Procedencia.origem`.
    "desconhecida",
)


@dataclass(frozen=True, slots=True)
class Procedencia:
    """De onde veio a carga, viajando do topo até a trilha.

    UM PARÂMETRO E NÃO QUATRO: `origem`, `arquivo` e `usuario_id` atravessam a
    cadeia juntos, e `lote_id` nasce aqui — um por objeto, logo um por arquivo,
    que é exatamente o que liga as linhas das fontes irmãs. Quem constrói uma
    `Procedencia` por fonte quebra esse laço.

    `origem` TEM PADRÃO, e o padrão não é inofensivo de propósito: um chamador
    futuro que esqueça de se identificar grava `desconhecida` e aparece assim na
    aba, em vez de não gravar linha nenhuma. Carga sem rastro é pior que carga
    com rastro anônimo — a primeira é invisível, a segunda se denuncia.

    `usuario_id` é nulo no comando de linha, e NÃO vem de
    `current_setting('painel.usuario_id')` como as trilhas de gatilho da `0005`:
    um `default` de coluna não pode embrulhar o cast numa exceção como aquelas
    funções fazem, e um valor malformado abortaria a ingestão inteira em vez de
    só perder o autor.
    """

    origem: str = "desconhecida"
    #: Nulo onde o chamador não tem nome a dar.
    arquivo: str | None = None
    usuario_id: uuid.UUID | None = None
    lote_id: uuid.UUID = field(default_factory=uuid.uuid4)


def registrar(
    sessao: Session,
    *,
    base: str,
    linhas: int,
    procedencia: Procedencia | None = None,
    fonte_id: int | None = None,
    meses: Iterable[date] = (),
) -> None:
    """Grava a linha da carga. Chamada DENTRO da transação que gravou os dados.

    NA MESMA TRANSAÇÃO, e é o que torna a linha confiável nas duas direções: uma
    carga que estoura faz `rollback` e não deixa rastro de algo que não
    aconteceu, e uma carga que commita não pode deixar de ter rastro. É também
    por isso que não há coluna de situação — a existência da linha é o sucesso, e
    tentativa/falha é observabilidade, não linhagem.

    `linhas` ZERO É VÁLIDO e é o caso que torna a tabela necessária: a ingestão
    apaga o período e pode não inserir nada, e aí nenhum carimbo das tabelas de
    dado anda.
    """
    procedencia = procedencia or Procedencia()
    sessao.add(
        CargaDeBase(
            base=base,
            fonte_id=fonte_id,
            arquivo=procedencia.arquivo,
            usuario_id=procedencia.usuario_id,
            origem=procedencia.origem,
            lote_id=procedencia.lote_id,
            linhas=linhas,
            meses=sorted(set(meses)),
        )
    )
