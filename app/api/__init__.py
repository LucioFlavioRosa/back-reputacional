"""As rotas HTTP, uma por contexto de negócio.

Aqui não mora regra: cada rota traduz HTTP para um caso de uso e devolve o
resultado. Validação de entrada fica em `esquemas/`, decisão fica em
`dominio/`.

`dependencias.py` tem o que toda rota protegida usa — quem está pedindo, e se
pode. `erros.py` traduz exceção de domínio em resposta HTTP.
"""
