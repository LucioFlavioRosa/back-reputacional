"""O CORS precisa liberar todo verbo que alguma rota realmente usa.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
`metodos_permitidos` não tinha `PUT`, e `PUT /api/acessos/{id}` — a concessão
de acesso, a única rota `PUT` do produto — estava morta no navegador. O
preflight voltava `400 Disallowed CORS method`, a requisição nunca chegava à
rota, e a tela dizia "Não foi possível falar com o servidor. Verifique se o
backend está no ar" — apontando para a API estar fora, quando ela estava de pé
respondendo todo o resto.

NENHUM TESTE PEGOU, e a razão importa: o `TestClient` do FastAPI chama a
aplicação direto, sem preflight. Preflight é comportamento de NAVEGADOR. Uma
suíte inteira de testes de HTTP pode passar com o CORS quebrado, porque ela
nunca faz a pergunta que o navegador faz.

A DEFESA NÃO É UMA LISTA
------------------------
Escrever `assert "PUT" in metodos_permitidos` consertaria hoje e falharia de
novo na primeira rota que usasse um verbo novo — seria repetir a lista à mão,
que é exatamente o erro original.

Estes testes DERIVAM a resposta do próprio app: percorrem as rotas
registradas, juntam os verbos que elas declaram e exigem que a configuração os
cubra. Um verbo novo numa rota nova acusa sozinho.

O QUE ELES **NÃO** ALCANÇAM
---------------------------
`HEAD` é excluído da varredura (ver `_verbos_realmente_usados`), e portanto uma
rota `HEAD` NÃO acusa aqui. Hoje isso não esconde nada: nenhuma rota declara
`HEAD` explicitamente, e `HEAD` é método CORS-safelisted — o navegador não pede
preflight para ele. Mas a isenção é do MÉTODO, não da requisição: um `HEAD` com
cabeçalho fora da lista segura pediria preflight, e este teste ficaria calado.
Se algum dia existir rota `HEAD` de propósito, reveja a exclusão.
"""

from starlette.routing import Route

from app.configuracao import Configuracao


def _verbos_realmente_usados() -> set[str]:
    """Todo verbo declarado por alguma rota do app.

    `HEAD` e `OPTIONS` entram sozinhos pelo Starlette em qualquer rota `GET` —
    ninguém os escreveu, e exigi-los na configuração faria o teste falhar por
    um verbo que nenhuma rota do produto usa de fato. Ficam de fora para que a
    falha, quando vier, aponte para uma rota real.

    A ressalva está na docstring do módulo: a isenção de preflight vale para o
    MÉTODO, e um `HEAD` com cabeçalho fora da lista segura escaparia daqui.
    """
    from main import app

    verbos: set[str] = set()
    for rota in app.routes:
        if isinstance(rota, Route) and rota.methods:
            verbos |= {m for m in rota.methods if m not in {"HEAD", "OPTIONS"}}
    return verbos


def test_cors_libera_todo_verbo_que_alguma_rota_usa() -> None:
    permitidos = set(Configuracao().metodos_permitidos)
    faltando = _verbos_realmente_usados() - permitidos

    assert not faltando, (
        f"Rotas usam {sorted(faltando)}, e o CORS não libera. "
        "No navegador o preflight devolve 400 e a chamada nem chega à rota — "
        "a tela acusa 'servidor fora do ar' com a API de pé. "
        "Acrescente o verbo a `metodos_permitidos` em app/configuracao.py."
    )


def test_o_put_da_concessao_esta_coberto() -> None:
    """A rota que quebrou, nomeada.

    O teste acima é a rede geral; este fixa o caso concreto, para que quem
    apertar a lista no futuro veja qual funcionalidade some.
    """
    assert "PUT" in Configuracao().metodos_permitidos, (
        "Sem PUT, `PUT /api/acessos/{id}` fica inalcançável pelo navegador e "
        "ninguém consegue conceder nem alterar acesso de ninguém."
    )


def test_o_cabecalho_do_csrf_continua_liberado() -> None:
    """O mesmo erro, do lado dos cabeçalhos — já aconteceu uma vez.

    Toda escrita manda `X-CSRF-Token`. Fora da lista, o preflight recusa e
    TODAS as escritas morrem de uma vez, com o mesmo sintoma enganoso.
    """
    assert "X-CSRF-Token" in Configuracao().cabecalhos_permitidos
