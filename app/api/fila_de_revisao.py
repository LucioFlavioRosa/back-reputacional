"""A fila de revisão do Cadastro compartilhado: o que ler, e como tirar da fila.

A REGRA MORA EM `app/casos_de_uso/fila_de_revisao.py`; aqui só o contrato HTTP e
a permissão.

FORA DOS PREFIXOS DO CRM, de propósito. O Cadastro compartilhado está fora do
portal do CRM — "as três são dado mestre, não cadastro de agenda", diz
`PortalDoCadastroCompartilhado.tsx` —, e `exigir_portal_crm` aqui barraria quem
administra o cadastro sem abrir o CRM. `PREFIXOS_DO_CRM` em
`tests/test_portal_no_backend.py` é a lista de quem precisa do portal, e
`/api/revisao-de-cadastros` não está nela nem deve estar.

`administra_dicionarios` NAS DUAS, inclusive na leitura, e é mais estrito que as
listagens de cadastro — que pedem `ve_diretorio`. A fila não é "a base": é
trabalho pendente, e um registro aqui diz que a plataforma NÃO confia naquele
enquadramento ainda. Quem não pode consertar não ganha nada em ver a lista do que
está por consertar.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencias import UsuarioQueAdministraCadastros, obter_usuario_atual
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import fila_de_revisao

rotas = APIRouter(
    prefix="/api/revisao-de-cadastros",
    tags=["cadastro"],
    dependencies=[Depends(obter_usuario_atual)],
)

Sessao = SessaoDoPedido


class PendenteSaida(BaseModel):
    id: str
    tipo: str
    nome: str
    motivo: str | None
    contexto: str | None
    criado_em: datetime


class AbaSaida(BaseModel):
    """Uma das três abas de Cadastro compartilhado, com a sua fila.

    AS TRÊS SEMPRE, inclusive as vazias. A tela precisa saber que a aba existe e
    está limpa — uma aba que desaparece quando não tem pendência é uma aba que
    ninguém aprende a olhar.
    """

    id: str
    rotulo: str
    pendentes: list[PendenteSaida]


class ConsolidacaoSaida(BaseModel):
    pendente: PendenteSaida
    #: SE OUTRA PESSOA JÁ TINHA CONSOLIDADO ESTE. Ver `fila_de_revisao.consolidar`:
    #: a fila é trabalho de equipe pelo próprio pedido, então o segundo clique é
    #: o caso normal e não um erro.
    ja_estava_consolidado: bool


@rotas.get("", response_model=list[AbaSaida])
def listar_a_fila(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros
) -> list[fila_de_revisao.AbaDaFila]:
    """O que cada aba de Cadastro compartilhado tem para revisar."""
    return fila_de_revisao.listar(sessao)


@rotas.post("/{tipo}/{id}/consolidacao", response_model=ConsolidacaoSaida)
def consolidar(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, tipo: str, id: str
) -> ConsolidacaoSaida:
    """"Conferi este cadastro, está certo" — e ele sai da fila.

    `POST` NUM SUB-RECURSO, e não `PATCH` no cadastro: consolidar não edita o
    cadastro, afirma algo sobre ele. O `PATCH` ficaria a um campo de distância de
    "deixe eu só corrigir o nome aqui também", e a correção tem rota própria, com
    a validação que ela já sabe fazer.

    O ID VEM COMO TEXTO porque `tema` tem chave inteira e as outras três têm
    UUID. Converter aqui, com `int` no path, daria 422 para os UUIDs; converter
    lá, onde a tabela é conhecida, dá 404 — que é a resposta certa para "este
    cadastro não existe".
    """
    pendente, ja_estava = fila_de_revisao.consolidar(sessao, tipo=tipo, id=id)
    return ConsolidacaoSaida(
        pendente=PendenteSaida(**vars(pendente)), ja_estava_consolidado=ja_estava
    )
