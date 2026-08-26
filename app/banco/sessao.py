"""Conexão com o Postgres e a base declarativa do SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.configuracao import obter_configuracao


class Tabela(DeclarativeBase):
    """Base de todas as tabelas. As definições moram na `infraestrutura` de
    cada contexto — este módulo só oferece o ponto de ancoragem comum."""


@lru_cache
def obter_engine() -> Engine:
    configuracao = obter_configuracao()
    return create_engine(
        configuracao.banco_url,
        echo=configuracao.banco_echo,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def obter_fabrica_de_sessao() -> sessionmaker[Session]:
    return sessionmaker(bind=obter_engine(), expire_on_commit=False, future=True)


def obter_sessao() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição.

    Commit no caminho feliz, rollback em qualquer exceção — inclusive nos erros
    de domínio, que sobem até o handler da plataforma.
    """
    sessao = obter_fabrica_de_sessao()()
    try:
        yield sessao
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


#: A sessão, como toda rota deve declará-la.
#:
#: `scope="function"` é o ponto, e NÃO é detalhe de estilo.
#:
#: No escopo padrão (`"request"`), o código de saída de uma dependência com
#: `yield` roda DEPOIS de a resposta ir para o cliente. O `commit()` acima é
#: código de saída — então um commit que falha (violação de constraint adiada,
#: deadlock, conexão perdida) acontece quando o cliente já recebeu `201 Created`
#: com o corpo do registro. A API diria que gravou, e não gravou.
#:
#: Com `"function"`, a saída roda depois de os dados da resposta serem gerados e
#: ANTES de ela ser enviada: a falha vira 500, que é a verdade.
#:
#: Está aqui, e não em cada `rotas.py`, porque é o tipo de parâmetro que um
#: contexto novo esqueceria — e o esquecimento não quebra nada visivelmente.
SessaoDoPedido = Annotated[Session, Depends(obter_sessao, scope="function")]
