"""Leitura dos dicionários. O cadastro carrega tudo numa chamada só."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.dependencias import obter_usuario_atual
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import DICIONARIOS
from app.dominio.recorte import ABRANGENCIAS_VALIDAS, INTERNACIONAL, NACIONAL

rotas = APIRouter(
    prefix="/api",
    tags=["catalogo"],
    # Só autenticação. Os dicionários são vocabulário fechado — frentes,
    # status, climas — e sem eles nenhuma tela renderiza rótulo. Não revelam
    # nada sobre com quem a Aegea fala nem sobre o que foi conversado, então
    # ficam fora do escopo de propósito, e não por esquecimento.
    dependencies=[Depends(obter_usuario_atual)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido


#: Rótulos dos grupos de status, para a tela não ter de traduzir códigos.
#:
#: Ficam aqui, e não no banco, porque `grupo` é coluna de texto em `status`, e
#: não tabela: os três valores são estrutura do modelo — sustentam a taxa de
#: resolutividade — e não vocabulário que a coordenação administra. Um quarto
#: grupo mudaria o cálculo do painel, então é mudança de código por definição.
ROTULOS_DE_GRUPO = {
    "resolvido": "Resolvidos",
    "aberto": "Em aberto",
    "declinado": "Declinados",
}


@rotas.get("/dicionarios")
def listar_dicionarios(sessao: Sessao) -> dict[str, list[dict[str, Any]]]:
    """Todos os vocabulários do painel, só os ativos, na ordem de exibição.

    O front NÃO deve ter lista fixa de nenhum deles. Toda opção de filtro sai
    daqui, então acrescentar uma linha num dicionário do banco faz a opção
    aparecer na próxima carga da tela, sem build e sem deploy.
    """
    resposta: dict[str, list[dict[str, Any]]] = {}
    for chave, tabela in DICIONARIOS.items():
        consulta = select(tabela).where(tabela.ativo.is_(True))  # type: ignore[attr-defined]
        if hasattr(tabela, "ordem"):
            consulta = consulta.order_by(tabela.ordem)  # type: ignore[attr-defined]
        else:
            consulta = consulta.order_by(tabela.nome)  # type: ignore[attr-defined]

        resposta[chave] = [
            {
                coluna.name: getattr(linha, coluna.name)
                for coluna in tabela.__table__.columns
                if coluna.name != "ativo"
            }
            for linha in sessao.scalars(consulta)
        ]

    # Os dois abaixo NÃO são tabelas, e por isso são montados à mão. Saem por
    # aqui mesmo assim: o front precisa de uma fonte só para as opções de
    # filtro, e "vá buscar este num lugar e aquele noutro" é como uma lista
    # fixa reaparece no código da tela.

    resposta["ufs"] = [
        {"codigo": uf, "nome": ROTULOS_DE_ABRANGENCIA.get(uf, uf)}
        for uf in sorted(_abrangencias_do_banco(sessao), key=_ordem_da_uf)
    ]

    resposta["grupos_de_status"] = [
        {"codigo": codigo, "nome": ROTULOS_DE_GRUPO[codigo]}
        for codigo in ("resolvido", "aberto", "declinado")
    ]

    return resposta


#: O que o domínio `abrangencia` aceita, LIDO do Postgres.
#:
#: Ler daqui, e não da constante `ABRANGENCIAS_VALIDAS`, é o que faz o filtro
#: oferecer exatamente o que o banco aceita. Com a constante, um valor
#: acrescentado ao domínio por migration não apareceria na tela até alguém
#: lembrar de editar o Python — e o registro existiria sem ninguém conseguir
#: filtrá-lo.
#:
#: `ABRANGENCIAS_VALIDAS` continua existindo, e serve a outra coisa: o domínio
#: Python valida a ESCRITA sem ir ao banco. As duas são mantidas em acordo por
#: `tests/test_dicionarios_sao_a_fonte.py`, que falha se divergirem.
#:
#: O resultado é guardado em memória: mudar o domínio exige migration, então
#: dentro de um processo ele não muda. Sem isso, seriam 29 valores relidos a
#: cada abertura de tela.
_CONSULTA_DO_DOMINIO = text("""
    select pg_get_constraintdef(c.oid)
      from pg_constraint c
      join pg_type t on t.oid = c.contypid
     where t.typname = 'abrangencia'
""")

_abrangencias: frozenset[str] | None = None


def _abrangencias_do_banco(sessao: Session) -> frozenset[str]:
    global _abrangencias
    if _abrangencias is not None:
        return _abrangencias

    definicao = sessao.scalar(_CONSULTA_DO_DOMINIO)
    lidas = frozenset(re.findall(r"'([A-Z]{2})'::text", definicao or ""))

    # Se a leitura falhar — domínio renomeado, texto do `pg_get_constraintdef`
    # mudando entre versões do Postgres — o filtro cai para a constante em vez
    # de vir VAZIO. Uma tela sem nenhuma UF seria pior do que uma lista que
    # envelheceu, e o teste de acordo já cobre a divergência.
    #
    # Mas cai RECLAMANDO. Um fallback silencioso aqui é o pior desfecho: o
    # painel continuaria funcionando com a lista do código, e a introspecção
    # estaria quebrada há meses sem ninguém saber — que é exatamente o estado
    # do qual esta função nos tirou.
    if not lidas:
        logging.getLogger("painel_reputacional").warning(
            "Não consegui ler o domínio `abrangencia` do Postgres; as UFs do "
            "filtro vêm da constante em `app/dominio/recorte.py`. Conferir "
            "`pg_get_constraintdef` e o nome do domínio."
        )

    _abrangencias = lidas or frozenset(ABRANGENCIAS_VALIDAS)
    return _abrangencias


#: `NA` e `IN` vão para o FIM, e nesta ordem — Nacional antes de Internacional.
#:
#: Os dois não são estado, e no meio da lista alfabética passariam por sigla de
#: UF: quem procura "IN" esperando Indiana ou coisa parecida não é o problema;
#: o problema é quem rola a lista procurando "Nacional" e não olha entre "MS" e
#: "PA".
#:
#: A ordem entre eles é EXPLÍCITA, e não alfabética: por alfabeto "IN" viria
#: antes de "NA", invertendo o par que a tela sempre mostrou.
_FORA_DO_ALFABETO = {NACIONAL: 1, INTERNACIONAL: 2}


def _ordem_da_uf(uf: str) -> tuple[int, int, str]:
    fim = _FORA_DO_ALFABETO.get(uf)
    return (1, fim, "") if fim else (0, 0, uf)


ROTULOS_DE_ABRANGENCIA = {NACIONAL: "Nacional", INTERNACIONAL: "Internacional"}
