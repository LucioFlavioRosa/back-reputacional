"""As entidades, as regras e o vocabulário. Sem SQL e sem FastAPI.

O que está aqui não sabe que existe banco nem que existe HTTP, e é isso que
permite testá-lo sozinho.

`recorte.py` é a peça central: os filtros do painel como um valor único. Toda
listagem e toda agregação respondem ao MESMO recorte — é o que faz o número do
KPI bater com o da tabela.
"""
