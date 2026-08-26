"""Autenticação, sessão e a superfície HTTP protegida.

    oidc.py                    o fluxo com o Entra ID (PKCE, JWKS, nonce)
    sessao_assinada.py         o cookie assinado com HMAC
    protecao_http.py           CSRF, cabeçalhos de segurança, tamanho de corpo
    limite_de_taxa.py          os dois baldes: por IP e por usuário
    verificacao_de_producao.py recusa subir com configuração insegura

A AUTORIZAÇÃO não mora aqui: papel, escopo e prazo vêm do banco e são aplicados
em `banco/filtros_sql.py` e em `dominio/politica.py`. Autenticar é dizer quem
é; autorizar é dizer o que alcança.
"""
