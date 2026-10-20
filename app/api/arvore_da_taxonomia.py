"""A Árvore da taxonomia (Metodologia): o Cadastro de Temas em leitura.

UMA ROTA SÓ DE LEITURA, sem cache: cada abertura da página lê o cadastro como
ele está agora. Salvar no Cadastro de Temas (ou subir a planilha de subtemas)
reflete na próxima abertura, sem deploy e sem nada a invalidar.

TUDO PELOS IDS. A tela monta as duas árvores (por atributo e por risco) e a
numeração (1, 1.2) a partir de `ordem`; nome nenhum é chave, e a numeração
nunca é gravada. Item inativo não sai daqui.

SÓ O RISCO PRIMÁRIO. `tema_risco` ainda não distingue primário de secundário,
e hoje cada subtema tem no máximo um vínculo — esse é o primário. Se um dia
houver dois, sai o de menor `ordem` do risco (o primeiro da matriz), e a regra
fica num lugar só: `_risco_primario`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencias import UsuarioLogado, exigir_portal_score
from app.banco.sessao import SessaoDoPedido as Sessao
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Risco, RiskCluster, Tema, TemaRisco
from app.dominio.arvore_da_taxonomia import DIMENSOES_DE_COR

#: Mesma porta da Metodologia, que mora no Score.
rotas = APIRouter(
    prefix="/api/taxonomia", tags=["taxonomia"], dependencies=[Depends(exigir_portal_score)]
)


class ItemOrdenado(BaseModel):
    id: int
    nome: str
    ordem: int


class TemaSaida(ItemOrdenado):
    pilar_id: int


class SubtemaSaida(BaseModel):
    id: int
    nome: str
    tema_id: int
    #: Código da camada (`credibilidade`…), ou nulo quando ainda a definir.
    lso: str | None
    #: O risco primário, ou nulo: "Sem enquadramento de risco".
    risco_id: int | None


class RiscoSaida(ItemOrdenado):
    cluster_id: int
    severidade: str


class ValorDeCorSaida(BaseModel):
    codigo: str
    nome: str
    cor: str
    hachurado: bool


class DimensaoDeCorSaida(BaseModel):
    chave: str
    nome: str
    titulo: str
    explicacao: str
    alvo: str
    campo: str
    valores: list[ValorDeCorSaida]
    vazio: ValorDeCorSaida


class ArvoreSaida(BaseModel):
    pilares: list[ItemOrdenado]
    temas: list[TemaSaida]
    subtemas: list[SubtemaSaida]
    clusters: list[ItemOrdenado]
    riscos: list[RiscoSaida]
    cores: list[DimensaoDeCorSaida]


def _risco_primario(vinculos: list[int], ordem_do_risco: dict[int, tuple[int, int]]) -> int | None:
    """O primeiro risco ativo da matriz entre os vínculos do subtema."""
    ativos = [risco_id for risco_id in vinculos if risco_id in ordem_do_risco]
    return min(ativos, key=lambda risco_id: ordem_do_risco[risco_id]) if ativos else None


@rotas.get("/arvore")
def obter_arvore(sessao: Sessao, usuario: UsuarioLogado) -> ArvoreSaida:
    """Pilares, temas, subtemas, clusters e riscos ATIVOS, e as cores.

    UM SUBTEMA SÓ APARECE COM O TEMA E O PILAR ATIVOS — um subtema de tema
    desativado não teria onde ser desenhado na árvore por atributo.
    """
    pilares = sessao.scalars(
        select(BlocoTema).where(BlocoTema.ativo.is_(True)).order_by(BlocoTema.ordem, BlocoTema.id)
    ).all()
    ids_de_pilar = {pilar.id for pilar in pilares}
    temas = [
        tema
        for tema in sessao.scalars(
            select(MacroTema)
            .where(MacroTema.ativo.is_(True))
            .order_by(MacroTema.ordem, MacroTema.id)
        ).all()
        if tema.bloco_tema_id in ids_de_pilar
    ]
    ids_de_tema = {tema.id for tema in temas}

    clusters = sessao.scalars(
        select(RiskCluster)
        .where(RiskCluster.ativo.is_(True))
        .order_by(RiskCluster.ordem, RiskCluster.id)
    ).all()
    ids_de_cluster = {cluster.id for cluster in clusters}
    riscos = [
        risco
        for risco in sessao.scalars(
            select(Risco).where(Risco.ativo.is_(True)).order_by(Risco.ordem, Risco.id)
        ).all()
        if risco.risk_cluster_id in ids_de_cluster
    ]
    ordem_do_risco = {risco.id: (risco.ordem, risco.id) for risco in riscos}

    vinculos: dict[int, list[int]] = {}
    for tema_id, risco_id in sessao.execute(select(TemaRisco.tema_id, TemaRisco.risco_id)):
        vinculos.setdefault(tema_id, []).append(risco_id)

    subtemas = sessao.scalars(
        select(Tema).where(Tema.ativo.is_(True), Tema.macro_tema_id.is_not(None)).order_by(Tema.id)
    ).all()

    return ArvoreSaida(
        pilares=[ItemOrdenado(id=p.id, nome=p.nome, ordem=p.ordem) for p in pilares],
        temas=[
            TemaSaida(id=t.id, nome=t.nome, ordem=t.ordem, pilar_id=t.bloco_tema_id) for t in temas
        ],
        subtemas=[
            SubtemaSaida(
                id=s.id,
                nome=s.nome,
                tema_id=s.macro_tema_id,
                lso=s.camada_lso,
                risco_id=_risco_primario(vinculos.get(s.id, []), ordem_do_risco),
            )
            for s in subtemas
            if s.macro_tema_id in ids_de_tema
        ],
        clusters=[ItemOrdenado(id=c.id, nome=c.nome, ordem=c.ordem) for c in clusters],
        riscos=[
            RiscoSaida(
                id=r.id,
                nome=r.nome,
                ordem=r.ordem,
                cluster_id=r.risk_cluster_id,
                severidade=r.severidade,
            )
            for r in riscos
        ],
        cores=[
            DimensaoDeCorSaida(
                chave=d.chave,
                nome=d.nome,
                titulo=d.titulo,
                explicacao=d.explicacao,
                alvo=d.alvo,
                campo=d.campo,
                valores=[ValorDeCorSaida(**v.__dict__) for v in d.valores],
                vazio=ValorDeCorSaida(**d.vazio.__dict__),
            )
            for d in DIMENSOES_DE_COR
        ],
    )
