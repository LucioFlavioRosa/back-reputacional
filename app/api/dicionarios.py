"""Administração dos dicionários — o que a coordenação pode mexer sem migration.

`GET /api/dicionarios` (em `catalogo.py`) serve as TELAS: só os ativos, sem
dizer o que é editável. Esta rota serve a ADMINISTRAÇÃO: tudo, inclusive o
que foi desativado, e para cada vocabulário se ele se edita aqui ou não — e
por quê.

DOIS GRUPOS, e a fronteira é de propósito:

- ABERTOS — vocabulário que a coordenação administra: unidades de negócio,
  formatos de interação, formatos de imprensa/investidores, tipos de
  investidor, esferas, casas, tramitações, áreas. Acrescentar, renomear,
  desativar e reativar; nunca apagar (há agenda apontando).
- FECHADOS — estrutura do modelo: frentes (o back deriva por elas), status e
  seus grupos (a taxa de resolutividade), clima e resultado (os KPIs),
  relevância (o número é o próprio tier), iniciativa, e a taxonomia de
  públicos (o tipo da instituição nasce dela). Mudar um valor aqui é mudança
  de regra, então é código e migration — a tela mostra, e diz isso.

`natureza_orgao` e `stakeholder` aparecem como aposentados: continuam no
banco porque o acervo os tem, mas nenhuma tela os pede. `temas` tem aba
própria e não repete aqui. `test_dicionarios_administracao` garante que todo
dicionário do registro está em exatamente um desses grupos.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.dependencias import (
    UsuarioQueAdministraCadastros,
    obter_usuario_atual,
)
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import (
    DICIONARIOS,
    AreaPessoa,
    Casa,
    Esfera,
    Formato,
    FormatoInteracao,
    TipoInvestidor,
    Tramitacao,
    UnidadeNegocio,
)
from app.dominio.erros import NaoEncontrado, RegraViolada

rotas = APIRouter(
    prefix="/api/dicionarios",
    tags=["dicionarios"],
    dependencies=[Depends(obter_usuario_atual)],
)

Sessao = SessaoDoPedido

#: Os abertos: nome público → tabela. A ORDEM é a da tela.
ABERTOS: dict[str, type] = {
    "unidades_negocio": UnidadeNegocio,
    "formatos_interacao": FormatoInteracao,
    "formatos": Formato,
    "tipos_investidor": TipoInvestidor,
    "esferas": Esfera,
    "casas": Casa,
    "tramitacoes": Tramitacao,
    "areas_pessoa": AreaPessoa,
}

#: Os fechados, com o motivo que a tela mostra no lugar do botão.
FECHADOS: dict[str, str] = {
    "frentes": (
        "A frente é derivada pelo servidor a partir do tipo da instituição; "
        "mudar a lista é mudar a regra."
    ),
    "status": (
        "Os status sustentam a taxa de resolutividade pelos grupos "
        "resolvido/aberto/declinado."
    ),
    "climas": "O clima alimenta os KPIs e as cores do Painel.",
    "resultados": "O desfecho alimenta os KPIs de resultado.",
    "relevancias": "O número do tier é o próprio código, gravado em cada agenda.",
    "iniciativas": "Vocabulário fixo do modelo.",
    "categorias_publico": (
        "A taxonomia de públicos define o tipo da instituição e a área dona; "
        "mudar é migration."
    ),
    "subcategorias_publico": "Subdivisão da taxonomia de públicos; mudar é migration.",
}

#: Administrados em OUTRA aba da Administração: não repetem aqui.
OUTRA_ABA: dict[str, str] = {
    "temas": "Aba Temas",
}

#: Aposentados: ficam visíveis para o acervo fazer sentido, sem botão.
APOSENTADOS: dict[str, str] = {
    "naturezas_orgao": "Substituído pela categoria de público da instituição (0036).",
    "stakeholders": "Substituído pela categoria de público da instituição (0036).",
}

ROTULOS: dict[str, str] = {
    "unidades_negocio": "Unidades de negócio",
    "formatos_interacao": "Formatos de interação",
    "formatos": "Formatos (imprensa e investidores)",
    "tipos_investidor": "Tipos de investidor",
    "esferas": "Esferas",
    "casas": "Casas legislativas",
    "tramitacoes": "Tramitações",
    "areas_pessoa": "Áreas da Aegea",
    "frentes": "Frentes",
    "status": "Situações",
    "climas": "Climas",
    "resultados": "Desfechos",
    "relevancias": "Relevância (tiers)",
    "iniciativas": "Iniciativas",
    "categorias_publico": "Categorias de público",
    "subcategorias_publico": "Subcategorias de público",
    "naturezas_orgao": "Natureza do órgão (aposentado)",
    "stakeholders": "Stakeholder (aposentado)",
}


def _linhas(sessao, tabela) -> list[dict[str, Any]]:
    consulta = select(tabela)
    if hasattr(tabela, "ordem"):
        consulta = consulta.order_by(tabela.ordem)
    else:
        consulta = consulta.order_by(tabela.nome)
    return [
        {coluna.name: getattr(linha, coluna.name) for coluna in tabela.__table__.columns}
        for linha in sessao.scalars(consulta)
    ]


@rotas.get("/administracao")
def listar_para_administracao(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros
) -> list[dict[str, Any]]:
    """Todos os vocabulários, inclusive inativos, cada um dizendo se se edita aqui."""
    resposta: list[dict[str, Any]] = []
    for nome, tabela in ABERTOS.items():
        resposta.append(
            {"nome": nome, "rotulo": ROTULOS[nome], "editavel": True, "motivo": None,
             "itens": _linhas(sessao, tabela)}
        )
    for grupo in (FECHADOS, APOSENTADOS):
        for nome, motivo in grupo.items():
            resposta.append(
                {"nome": nome, "rotulo": ROTULOS[nome], "editavel": False, "motivo": motivo,
                 "itens": _linhas(sessao, DICIONARIOS[nome])}
            )
    return resposta


class ItemEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1)
    ativo: bool = True


class ItemSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str | None = None
    nome: str
    ordem: int
    ativo: bool


def _tabela_aberta(nome: str) -> type:
    tabela = ABERTOS.get(nome)
    if tabela is None:
        if nome in FECHADOS or nome in APOSENTADOS:
            raise RegraViolada(
                f"O dicionário {nome!r} não se edita pela tela: "
                f"{(FECHADOS | APOSENTADOS)[nome]}"
            )
        raise NaoEncontrado(f"Dicionário {nome!r} não existe.")
    return tabela


def _codigo(nome: str) -> str:
    """`codigo` estável a partir do nome: sem acento, minúsculo, `_` no lugar
    do resto. É o que o front e o SQL usam para se referir ao valor."""
    base = unicodedata.normalize("NFKD", nome.strip().lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")


@rotas.post("/{nome}", response_model=ItemSaida, status_code=status.HTTP_201_CREATED)
def acrescentar(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, nome: str, entrada: ItemEntrada
):
    tabela = _tabela_aberta(nome)
    valor = entrada.nome.strip()
    if sessao.scalar(select(tabela).where(func.lower(tabela.nome) == valor.lower())) is not None:
        raise RegraViolada(f"Já existe {valor!r} em {ROTULOS[nome]}.")
    campos: dict[str, Any] = {
        "nome": valor,
        "ativo": entrada.ativo,
        "ordem": (sessao.scalar(select(func.max(tabela.ordem))) or 0) + 1,
    }
    if hasattr(tabela, "codigo"):
        codigo = _codigo(valor)
        if sessao.scalar(select(tabela).where(tabela.codigo == codigo)) is not None:
            raise RegraViolada(f"Já existe um valor com o código {codigo!r} em {ROTULOS[nome]}.")
        campos["codigo"] = codigo
    # Formato tem escopo (imprensa/investidores); o acrescentado pela tela vale
    # para os dois, que é o que `geral` significa.
    if tabela is Formato:
        campos["escopo"] = "geral"
    registro = tabela(**campos)
    sessao.add(registro)
    sessao.flush()
    return registro


@rotas.put("/{nome}/{id}", response_model=ItemSaida)
def editar(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    nome: str,
    id: int,
    entrada: ItemEntrada,
):
    """Renomeia, desativa ou reativa. O `codigo` NÃO muda: é ele que as
    agendas e o front guardam — renomear é mudar o rótulo, não a identidade."""
    tabela = _tabela_aberta(nome)
    registro = sessao.get(tabela, id)
    if registro is None:
        raise NaoEncontrado(f"Valor {id} não encontrado em {ROTULOS[nome]}.")
    valor = entrada.nome.strip()
    outro = sessao.scalar(
        select(tabela).where(func.lower(tabela.nome) == valor.lower(), tabela.id != id)
    )
    if outro is not None:
        raise RegraViolada(f"Já existe {valor!r} em {ROTULOS[nome]}.")
    registro.nome = valor
    registro.ativo = entrada.ativo
    sessao.flush()
    return registro
