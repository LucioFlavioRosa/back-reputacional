"""Os documentos que saíram das reuniões — os que moram no nosso armazenamento.

DUAS PROCEDÊNCIAS, DUAS TELAS. A biblioteca (`/api/referencias`) é o acervo
oficial da companhia — o que a Aegea leva PARA a reunião, e que tem versão.
Isto aqui é o que
VOLTA dela — a ata que a outra parte entregou, o material que a equipe produziu
depois — e mora no Blob, porque nasceu aqui.

Só o que tem ARQUIVO. Material por link já é alcançável pelo link; o que
justifica uma tela própria é o acervo que só existe dentro do painel e que, sem
uma listagem, só se encontra abrindo a agenda que o gerou — e é preciso saber
qual foi.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencias import UsuarioLogado, exigir_portal_crm
from app.api.interacoes import obter_recorte
from app.banco.filtros_sql import condicoes
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_catalogo import Frente, Status
from app.banco.tabelas_interacoes import Arquivo, InteracaoRegistro, Material
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.recorte import Recorte

rotas = APIRouter(
    prefix="/api/materiais",
    tags=["materiais"],
    dependencies=[Depends(exigir_portal_crm)],
)

Sessao = SessaoDoPedido
RecorteAtual = Annotated[Recorte, Depends(obter_recorte)]


class MaterialDaBase(BaseModel):
    id: UUID
    #: `apoio` (antes da reunião), `obtido` ou `produzido` (depois).
    momento: str
    titulo: str
    resumo: str | None
    #: A agenda de onde ele saiu — é por ela que se chega ao contexto.
    interacao_id: UUID
    data_interacao: date
    frente: str
    instituicao: str | None
    #: Do arquivo no Blob.
    arquivo_id: UUID
    arquivo_nome: str
    arquivo_tipo: str
    arquivo_tamanho: int
    #: DE QUE ASSUNTOS O DOCUMENTO TRATA — os mesmos ids do dicionario `temas`.
    #:
    #: E o que permite procurar por assunto aqui como se procura na biblioteca:
    #: "o que existe sobre tarifa" passa a ter a mesma resposta nas duas abas.
    temas: list[int]
    criado_em: datetime
    criado_por: str | None


@rotas.get("", response_model=list[MaterialDaBase])
def listar(
    sessao: Sessao,
    usuario: UsuarioLogado,
    recorte: RecorteAtual,
    limite: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[MaterialDaBase]:
    """Os documentos com arquivo das agendas ALCANÇADAS PELO RECORTE.

    O recorte vale aqui como vale na listagem de agendas: esta tela mora dentro
    da Base, e o cabeçalho da Base diz o recorte em vigor. Uma aba que ignorasse
    os filtros mostraria documentos de agendas que a tela ao lado não lista — e
    quem visse os dois números não teria como reconciliá-los.

    O ESCOPO TAMBÉM, pelas mesmas `condicoes` da listagem. Um documento é tão
    sensível quanto a agenda que o gerou: deixá-lo escapar aqui contornaria a
    restrição de frente que a listagem respeita.
    """
    consulta = (
        select(Material, InteracaoRegistro, Frente.codigo, Instituicao.nome, Usuario.nome, Arquivo)
        .join(InteracaoRegistro, InteracaoRegistro.id == Material.interacao_id)
        .join(Frente, Frente.id == InteracaoRegistro.frente_id)
        .join(Status, Status.id == InteracaoRegistro.status_id)
        .join(Arquivo, Arquivo.id == Material.arquivo_id)
        .outerjoin(Instituicao, Instituicao.id == InteracaoRegistro.instituicao_id)
        .outerjoin(Usuario, Usuario.id == Material.criado_por)
        .where(
            Material.arquivo_id.is_not(None),
            *condicoes(
                recorte,
                escopo=usuario.escopo,
                busca_em_campos_sensiveis=usuario.ve_campos_sensiveis,
            ),
        )
        .order_by(Material.criado_em.desc())
        .limit(limite)
    )

    return [
        MaterialDaBase(
            id=material.id,
            momento=material.momento,
            titulo=material.titulo,
            resumo=material.observacao,
            interacao_id=interacao.id,
            data_interacao=interacao.data_interacao,
            frente=frente,
            instituicao=instituicao,
            arquivo_id=arquivo.id,
            arquivo_nome=arquivo.nome,
            arquivo_tipo=arquivo.tipo_conteudo,
            arquivo_tamanho=arquivo.tamanho,
            temas=sorted(vinculo.tema_id for vinculo in material.temas),
            criado_em=material.criado_em,
            criado_por=autor,
        )
        for material, interacao, frente, instituicao, autor, arquivo in sessao.execute(
            consulta
        ).all()
    ]
