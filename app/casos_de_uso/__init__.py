"""O que a aplicação faz, um arquivo por operação.

Os nomes são o verbo do negócio: `registrar_interacao`, `conceder` acesso,
`consultar_interacoes`. Quem procura "onde isso acontece?" acha pelo nome.

É aqui que a transação é orquestrada: o caso de uso monta a entidade, pede ao
domínio que valide, e manda o repositório gravar.
"""
