"""Conexão com o Postgres e a base declarativa do SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.configuracao import obter_configuracao


class Tabela(DeclarativeBase):
    """Base de todas as tabelas. As definições moram na `infraestrutura` de
    cada contexto — este módulo só oferece o ponto de ancoragem comum."""


#: O sufixo dos servidores gerenciados do Azure. É o que separa "sem senha
#: porque a identidade autentica" de "sem senha porque o Postgres local não
#: pede uma".
HOSPEDEIRO_DO_AZURE = ".postgres.database.azure.com"


def _e_postgres_do_azure(url) -> bool:
    """Autentica por Entra ID: usuário, sem senha, num servidor do Azure."""
    return bool(
        url.username
        and url.password is None
        and (url.host or "").lower().endswith(HOSPEDEIRO_DO_AZURE)
    )


@lru_cache
def obter_engine() -> Engine:
    configuracao = obter_configuracao()
    engine = create_engine(
        configuracao.banco_url,
        echo=configuracao.banco_echo,
        pool_pre_ping=True,
        future=True,
    )

    # NO POSTGRES DO AZURE, SEM SENHA NA URL, O TOKEN É A SENHA.
    #
    # A identidade do contêiner entra como usuário e o token do Entra ID entra
    # como senha. Ele vale cerca de uma hora, então não pode ir fixo na URL:
    # quem o busca é este ouvinte, no momento de abrir cada conexão.
    #
    # `pool_pre_ping` é o que faz o resto funcionar: uma conexão que já está no
    # pool continua válida depois de o token vencer, porque o token só é
    # conferido no LOGIN. Quem pega token novo é a conexão nova.
    #
    # O HOSPEDEIRO ENTRA NA CONDIÇÃO, e não só a ausência de senha. Uma URL
    # local sem senha é legítima e comum — `trust`, autenticação por par,
    # `.pgpass` — e cair aqui faria a aplicação buscar um token de identidade
    # gerenciada que não existe, para mandá-lo a um Postgres que não o entende.
    # O erro apareceria como "autenticação falhou", longe da causa.
    if _e_postgres_do_azure(engine.url):
        from app.seguranca.identidade_azure import token_para_postgres

        @event.listens_for(engine, "do_connect")
        def _token_no_lugar_da_senha(dialeto, registro, args, parametros):  # noqa: ANN001
            parametros["password"] = token_para_postgres()

    return engine


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
