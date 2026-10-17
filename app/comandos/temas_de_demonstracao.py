"""Tradução dos 17 nomes de tema "de fundação" (`0001_fundacao.sql`) usados
pelos semeadores de desenvolvimento, para os subtemas ATIVOS da taxonomia v4
(`0058_taxonomia_de_temas_v4.sql`).

POR QUE EXISTE. Os semeadores (`semear_desenvolvimento`, `semear_enredos`,
`semear_referencias`) citam tema por nome em dado escrito à mão — tags de
`amostra_de_desenvolvimento.json`, os `temas=(...)` dos enredos, o `ACERVO`.
A 0058 desativou os 17 "de fundação" (`ativo=false`, `macro_tema_id=null`) e
carregou 104 subtemas novos no lugar. Sem tradução, cada semeador ou liga a um
tema aposentado (sem Pilar/Tema estratégico — invisível nos gráficos por N1/N2
novos) ou, onde já filtra por `ativo`, não acha nome nenhum e a interação
nasce sem tema.

UM CATÁLOGO SÓ, não uma cópia por semeador: assim a próxima reestruturação de
taxonomia edita um lugar, não três.

NÃO É 1 PARA 1: é dado de demonstração, não a taxonomia real. Dois nomes
antigos podem mirar o mesmo subtema novo sem problema nenhum — o que importa
aqui é a interação nascer com ALGUM subtema ativo, para exercitar Pilar/Tema
estratégico/LSO/risco, não reproduzir uma correspondência de negócio.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Tema

TEMA_ANTIGO_PARA_V4: dict[str, str] = {
    "Biometano": "Aproveitamento de subprodutos",
    "Carbono": "Emissão gases efeito estufa",
    "Clima": "Eventos Climáticos",
    "IPO": "IPO e acesso ao mercado de ações",
    "Leilões": "Novos Negócios e Leilões",
    "Modelo de negócio": "Modelo Operacional Aegea",
    "Regulação": "Fiscalização regulatória",
    "Resíduos": "Coleta de resíduos / Tratamento e Destinação",
    "Reúso": "Reúso de água",
    "Tarifa": "Estrutura e composição tarifária",
    "Universalização": "Universalização e metas de cobertura",
    "Disciplina financeira": "Custos e eficiência",
    "Cenário político": "Políticas públicas e setoriais",
    "Copasa": "Modelo Operacional Aegea",
    "Reputação": "Debate público versus privado",
    "Tributário": "Resultados financeiros e operacionais",
    "Inclusão sanitária": "Universalização e metas de cobertura",
}


def id_de_tema_por_nome_antigo(sessao: Session) -> dict[str, int]:
    """Nome ANTIGO (o que o dado de demonstração cita) -> id do subtema ATIVO
    equivalente na v4.

    Um antigo cujo destino não existe mais (renomeado ou removido numa
    taxonomia futura) simplesmente some daqui, em vez de apontar para um id
    errado — quem chama já lida com "nome não encontrado" (`.get()`, ou um
    `raise` explícito, conforme o semeador).
    """
    id_por_nome_novo = {
        t.nome: t.id for t in sessao.scalars(select(Tema).where(Tema.ativo))
    }
    return {
        antigo: id_por_nome_novo[novo]
        for antigo, novo in TEMA_ANTIGO_PARA_V4.items()
        if novo in id_por_nome_novo
    }
