"""A aplicação. As pastas são CAMADAS; os arquivos, contextos de negócio.

    api/          as rotas HTTP — um arquivo por contexto
    esquemas/     o que entra e o que sai da API (Pydantic)
    dominio/      entidades, invariantes e vocabulário. Sem SQL, sem FastAPI
    casos_de_uso/ o que a aplicação FAZ, nomeado com o verbo do negócio
    banco/        ORM, consultas, sessão e migrations
    seguranca/    OIDC, cookie de sessão, CSRF, limite de taxa, cabeçalhos

    configuracao.py    variáveis de ambiente, com os padrões
    observabilidade.py log estruturado e telemetria

A dependência corre em um sentido só: `api` conhece `casos_de_uso`, que conhece
`dominio`. `dominio` não conhece ninguém — é o que permite testá-lo sem banco e
sem HTTP.
"""
