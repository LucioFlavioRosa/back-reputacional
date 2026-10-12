"""A mudança de casa de um contato: o contrato HTTP.

MÓDULO PRÓPRIO porque `stakeholders.py` já passa de 900 linhas e isto é um
assunto fechado — a mesma razão de `cadastro_duplicado.py` existir. A regra mora
em `app/casos_de_uso/mudar_a_casa.py`.

SOB `/api/interlocutores`, que está em `PREFIXOS_DO_CRM`: a resposta nomeia duas
instituições do mapa de relacionamento da Aegea, e a âncora
`test_toda_rota_sob_prefixo_do_crm_exige_o_portal` varre a aplicação montada
cobrando o portal de qualquer rota sob esse prefixo — venha do router que vier.

`administra_dicionarios`, e não a escrita comum: mover um contato muda a quem ele
pertence, e nesse modelo a instituição é parte da identidade dele.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.dependencias import (
    UsuarioQueAdministraCadastros,
    exigir_diretorio,
    exigir_portal_crm,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import mudar_a_casa

rotas = APIRouter(
    prefix="/api",
    tags=["stakeholders"],
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_diretorio)],
)


class MudancaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Para onde o contato passa a falar.
    instituicao_id: UUID


class MudancaSaida(BaseModel):
    id: str
    nome: str
    #: A casa de onde saiu; nulo em quem não tinha nenhuma.
    de: str | None
    para: str
    #: QUANTAS AGENDAS FICAM NA CASA ANTIGA — a frase que distingue "mudou de
    #: casa" de "eu errei a instituição no cadastro". Zero quando não havia casa
    #: de origem: não há de onde ficar nada.
    agendas_que_ficam: int
    #: SE O CONTATO SAIU DA FILA DE REVISÃO com esta mudança.
    #:
    #: Mover É a resposta à pergunta que a fila fazia — "confirme se são a mesma
    #: pessoa, se ela mudou de casa, ou se são homônimas" —, então ela se
    #: encerra aqui em vez de voltar amanhã com a resposta já dada no dado.
    consolidou: bool


@rotas.post("/interlocutores/{id}/mudanca-de-casa", response_model=MudancaSaida)
def mudar_de_casa(
    sessao: SessaoDoPedido,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    entrada: MudancaEntrada,
) -> MudancaSaida:
    """Passa o contato para outra instituição, e diz quantas agendas ficam atrás.

    ENDEREÇO PRÓPRIO, e não `PUT /api/interlocutores/{id}` com outra
    `instituicao_id`. Aquele caminho existe e funciona — é por ele que a tela de
    cadastro grava a ficha —, e é exatamente por isso que este também existe: no
    PUT a instituição vai no meio de oito campos, com o mesmo peso de corrigir um
    e-mail, e a `0002` diz que "mesmo nome em instituições diferentes são pessoas
    diferentes". Trocar a casa é afirmar que a pessoa é a mesma de outro lugar.

    Um endereço com nome é o que permite a tela pedir confirmação, contar o que
    fica atrás, e recusar com a mensagem certa quando o nome já existe no
    destino. `PUT` não tem como dizer nada disso.
    """
    mudanca = mudar_a_casa.mudar(
        sessao, interlocutor_id=id, instituicao_id=entrada.instituicao_id
    )
    return MudancaSaida(**vars(mudanca))
