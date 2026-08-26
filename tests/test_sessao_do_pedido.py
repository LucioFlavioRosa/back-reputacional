"""O contrato de `SessaoDoPedido`: commit que falha não vira resposta de sucesso.

`obter_sessao` faz `commit()` DEPOIS do `yield` — é código de saída de uma
dependência. E o momento em que o código de saída roda depende do `scope`:

    "request" (padrão)   depois de a resposta ir para o cliente
    "function"           depois de os dados serem gerados, ANTES de enviar

Com o padrão, um commit que falha — violação de constraint adiada, deadlock,
conexão perdida — acontece quando o cliente já recebeu `201 Created` com o corpo
do registro. A API afirma que gravou, e não gravou. Não há erro na tela, não há
retry, e o registro simplesmente não existe.

Estes dois testes andam juntos de propósito: um prova que o alias funciona, o
outro prova que ele é NECESSÁRIO.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.banco.sessao import SessaoDoPedido, obter_sessao


class _FalhaNoCommit(RuntimeError):
    """O que o psycopg2 levantaria num commit recusado pelo banco."""


def _sessao_que_falha_no_commit() -> Iterator[object]:
    """Entrega a sessão normalmente e explode ao fechar, como um commit ruim."""
    yield object()
    raise _FalhaNoCommit("o banco recusou o commit")


def test_falha_no_commit_chega_ao_cliente():
    """Com `SessaoDoPedido`, o cliente vê o erro em vez de um 201 mentiroso."""
    app = FastAPI()

    @app.post("/escrever", status_code=201)
    def escrever(sessao: SessaoDoPedido) -> dict[str, bool]:
        return {"gravado": True}

    app.dependency_overrides[obter_sessao] = _sessao_que_falha_no_commit
    resposta = TestClient(app, raise_server_exceptions=False).post("/escrever")

    assert resposta.status_code == 500, (
        "o commit falhou e o cliente recebeu sucesso — é o defeito que o "
        "`scope='function'` de `SessaoDoPedido` existe para impedir"
    )


def test_o_escopo_padrao_deixaria_passar():
    """A razão de o alias existir, escrita como teste.

    Se um dia alguém declarar `Annotated[Session, Depends(obter_sessao)]` direto
    numa rota nova — sem o alias —, é ISTO que acontece: 201 com corpo de
    sucesso, e nada gravado.

    Este teste falha no dia em que o FastAPI mudar o comportamento do escopo
    padrão. Nesse dia, `SessaoDoPedido` pode deixar de precisar do parâmetro — e
    esta suíte é o lugar onde isso vai aparecer.
    """
    app = FastAPI()

    @app.post("/escrever", status_code=201)
    def escrever(sessao: Annotated[object, Depends(obter_sessao)]) -> dict[str, bool]:
        return {"gravado": True}

    app.dependency_overrides[obter_sessao] = _sessao_que_falha_no_commit
    resposta = TestClient(app, raise_server_exceptions=False).post("/escrever")

    assert resposta.status_code == 201
    assert resposta.json() == {"gravado": True}


def test_toda_rota_usa_o_alias():
    """Nenhuma rota declara a sessão por fora de `SessaoDoPedido`.

    É a garantia que sobrevive a um contexto novo: sem ela, bastaria alguém
    escrever `Depends(obter_sessao)` num `rotas.py` recém-criado para reabrir o
    buraco — e nada quebraria de forma visível.
    """
    import ast
    from pathlib import Path

    def _nome_chamado(no: ast.expr) -> str:
        """`Depends`, `fastapi.Depends` e `x.y.Depends` viram todos `Depends`.

        Sem isto a varredura só enxerga a forma importada diretamente, e um
        `fastapi.Depends(obter_sessao)` passaria — que é justamente como alguém
        escreveria sem pensar.
        """
        if isinstance(no, ast.Name):
            return no.id
        if isinstance(no, ast.Attribute):
            return no.attr
        return ""

    raiz = Path(__file__).resolve().parents[1] / "app"
    infratores: list[str] = []

    for arquivo in raiz.rglob("*.py"):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))

        # Um `import ... as` renomeia a função, e a varredura por nome perderia
        # o rastro. Coletar os apelidos é o que fecha essa porta.
        apelidos = {"obter_sessao"}
        for no in ast.walk(arvore):
            if isinstance(no, ast.ImportFrom):
                for alias in no.names:
                    if alias.name == "obter_sessao" and alias.asname:
                        apelidos.add(alias.asname)

        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            if _nome_chamado(no.func) != "Depends":
                continue
            if not no.args:
                continue
            if _nome_chamado(no.args[0]) not in apelidos:
                continue
            if not any(palavra.arg == "scope" for palavra in no.keywords):
                infratores.append(f"{arquivo.name}:{no.lineno}")

    assert not infratores, (
        "use `SessaoDoPedido` (de `app/banco/sessao.py`) em vez de "
        f"`Depends(obter_sessao)` sem escopo: {infratores}"
    )
