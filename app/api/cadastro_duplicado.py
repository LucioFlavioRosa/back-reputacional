"""A fila do mesmo ator cadastrado duas vezes, e as duas respostas.

Módulo separado porque `stakeholders.py` já passa de 900 linhas e isto é um
assunto fechado: a fila, a fusão, e o "são atores diferentes". A regra mora em
`app/casos_de_uso/atores_duplicados.py`; aqui só entram o contrato HTTP e a
permissão.

PERMISSÃO DE ADMINISTRAR CADASTROS nas duas escritas, e não a de escrita comum:
fundir junta dois dossiês e apaga uma linha do catálogo — não tem volta.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioQueAdministraCadastros,
    UsuarioQueVeDiretorio,
    exigir_diretorio,
    exigir_portal_crm,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import atores_duplicados

#: PREFIXO `/api`, e os caminhos escritos por extenso: as duas escritas moram
#: em endereços diferentes de propósito. Ver `declarar_distinto`.
#:
#: AS MESMAS DUAS DEPENDÊNCIAS DO ROUTER DOS STAKEHOLDERS, e por isso aqui no
#: router e não em cada rota: a resposta nomeia atores do mapa de
#: relacionamento da Aegea — todo jornalista e veículo com quem a companhia
#: fala —, e isso vale para a fila tanto quanto para a listagem. Quem apontou
#: foi `test_toda_rota_sob_prefixo_do_crm_exige_o_portal`, que varre a
#: aplicação montada: rota nova sob `/api/instituicoes` sem o portal é rota
#: desprotegida, venha do router que vier.
rotas = APIRouter(
    prefix="/api",
    tags=["stakeholders"],
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_diretorio)],
)


class CandidatoSaida(BaseModel):
    id: UUID
    nome: str
    tipo: str
    #: QUANTAS MENÇÕES este lado carrega. É o número que diz qual dos dois é a
    #: linha com história — e, na tela, qual deve sobreviver.
    mencoes: int


class DuplicadoSaida(BaseModel):
    id: UUID
    nome: str
    cargo: str | None
    mencoes: int
    candidatos: list[CandidatoSaida]


class FusaoEntrada(BaseModel):
    #: QUEM FICA. O perfil vem na URL e é sempre quem sai: ver `fundir`.
    sobrevivente_id: UUID


class DistintosEntrada(BaseModel):
    um_id: UUID
    outro_id: UUID
    motivo: str | None = None


@rotas.get("/instituicoes/duplicados", response_model=list[DuplicadoSaida])
def listar_duplicados(
    sessao: SessaoDoPedido, usuario: UsuarioQueVeDiretorio
) -> list[atores_duplicados.Duplicado]:
    """Os perfis de rede que se parecem com outro cadastro.

    LEITURA COM A PERMISSÃO DO DIRETÓRIO, como as outras listagens de cadastro:
    a resposta nomeia atores do mapa de relacionamento da Aegea.
    """
    return atores_duplicados.listar(sessao)


@rotas.post("/instituicoes/{perfil_id}/fundir", status_code=200)
def fundir_cadastro(
    sessao: SessaoDoPedido,
    usuario: UsuarioQueAdministraCadastros,
    perfil_id: UUID,
    entrada: FusaoEntrada,
) -> dict[str, str]:
    sobrevivente = atores_duplicados.fundir(
        sessao, perfil_id=perfil_id, sobrevivente_id=entrada.sobrevivente_id
    )
    return {"id": str(sobrevivente.id), "nome": sobrevivente.nome}


@rotas.post("/atores-distintos", status_code=200)
def declarar_distinto(
    sessao: SessaoDoPedido,
    usuario: UsuarioQueAdministraCadastros,
    entrada: DistintosEntrada,
) -> dict[str, bool]:
    """"Não é o mesmo ator" — tira o par da fila, para sempre.

    FORA DE `/api/instituicoes/` de propósito. O front recarrega o catálogo
    inteiro a cada escrita numa rota de catálogo, casando por prefixo — e esta
    decisão não muda cadastro nenhum. A fusão, que muda, fica lá e dispara a
    recarga sozinha.
    """
    atores_duplicados.declarar_distintos(
        sessao,
        um=entrada.um_id,
        outro=entrada.outro_id,
        motivo=entrada.motivo,
        decidido_por=usuario.id,
    )
    return {"guardado": True}
