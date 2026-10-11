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
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.dependencias import UsuarioQueAdministraCadastros, obter_usuario_atual
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.casos_de_uso import enquadrar_em_lote, fila_de_revisao
from app.dominio.erros import RegraViolada

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


class EnquadramentoEntrada(BaseModel):
    """Uma categoria de público para várias instituições da fila."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1)
    categoria_publico_id: int
    subcategoria_publico_id: int | None = None
    #: ESCOLHA DE QUEM REVISA, e não consequência automática — ver `enquadrar`.
    consolidar: bool = True


class RecusadaSaida(BaseModel):
    id: str
    nome: str
    motivo: str


class EnquadramentoSaida(BaseModel):
    enquadradas: int
    consolidadas: int
    #: O tipo que a categoria implica, para a tela dizer o que aconteceu.
    tipo: str
    recusadas: list[RecusadaSaida]


@rotas.post("/instituicoes/enquadramento", response_model=EnquadramentoSaida)
def enquadrar_instituicoes(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    entrada: EnquadramentoEntrada,
) -> EnquadramentoSaida:
    """Dá a mesma categoria de público a várias instituições da fila.

    POR QUE ESTA ROTA EXISTE: a planilha real de RI criou 178 instituições sem
    categoria (de 499 pendências na aba — o resto são contatos, que não têm esse
    campo), e a resposta para quase todas é a mesma. A consolidação uma a uma
    faria a pessoa digitar a mesma coisa 178 vezes — e desistir na décima, com a
    base meio classificada, que é pior do que não classificada porque ninguém
    sabe onde parou.

    FORA DE `/api/instituicoes` de propósito, e sob a fila: ela só alcança o que
    está pendente de revisão. E o prefixo importa para o front — o barramento
    recarrega o catálogo inteiro a cada escrita numa rota de catálogo, casando por
    prefixo, e aqui a recarga é NECESSÁRIA: o tipo da instituição muda, e com ele
    a frente de toda agenda dela. Ver a nota no cliente.
    """
    _conferir_categoria(
        sessao, entrada.categoria_publico_id, entrada.subcategoria_publico_id
    )
    resultado = enquadrar_em_lote.enquadrar(
        sessao,
        ids=entrada.ids,
        categoria_publico_id=entrada.categoria_publico_id,
        subcategoria_publico_id=entrada.subcategoria_publico_id,
        consolidar=entrada.consolidar,
    )
    return EnquadramentoSaida(
        enquadradas=resultado.enquadradas,
        consolidadas=resultado.consolidadas,
        tipo=resultado.tipo,
        recusadas=[RecusadaSaida(**vars(r)) for r in resultado.recusadas],
    )


def _conferir_categoria(
    sessao: Sessao, categoria_publico_id: int, subcategoria_publico_id: int | None
) -> None:
    """A MESMA REGRA DE `_conferir_categoria_publico` em `stakeholders.py`.

    A chave estrangeira já recusa o id que não existe, mas não o DESATIVADO, e
    nunca o cruzamento categoria × subcategoria — esse pareamento é regra de
    domínio, não algo que uma FK sozinha expresse.

    E AQUI ELA PESA MAIS DO QUE LÁ: uma subcategoria que não pertence à categoria
    seria gravada em até 500 linhas de uma vez, e desfazer isso é outro lote.
    """
    valida = sessao.scalar(
        select(CategoriaPublico.id).where(
            CategoriaPublico.id == categoria_publico_id,
            CategoriaPublico.ativo.is_(True),
        )
    )
    if valida is None:
        raise RegraViolada(
            f"Categoria de público inválida: {categoria_publico_id!r}."
        )
    if subcategoria_publico_id is None:
        return
    dona = sessao.scalar(
        select(SubcategoriaPublico.categoria_publico_id).where(
            SubcategoriaPublico.id == subcategoria_publico_id,
            SubcategoriaPublico.ativo.is_(True),
        )
    )
    if dona is None:
        raise RegraViolada(
            f"Subcategoria de público inválida: {subcategoria_publico_id!r}."
        )
    if dona != categoria_publico_id:
        raise RegraViolada(
            "A subcategoria escolhida não pertence a esta categoria de público."
        )
