"""Os dois vocabulários fechados de `tema`, onde o domínio pode alcançá-los.

ELES MORAVAM EM `app/api/stakeholders.py`, e o leitor da planilha de subtemas é
o primeiro consumidor fora da camada de API. Um caso de uso importando de
`app/api/` inverteria a dependência que o `app/__init__.py` deste projeto
descreve: `api/` são as rotas, `casos_de_uso/` o que elas orquestram, `dominio/`
o vocabulário — e a flecha aponta num sentido só.

`stakeholders.py` segue reexportando os dois nomes, porque três testes e as
mensagens de erro das rotas de tema os usam pelo caminho antigo.

OS DOIS EIXOS SÃO INDEPENDENTES, e isso é o que mais importa aqui:

- `nivel` é SENSIBILIDADE do assunto (sensível, estratégico, geral)
- `camada_lso` é a dimensão da licença social da taxonomia v1.3

Medido na base recriada: dos 149 temas, os 104 reconciliados com a v4 são todos
`estrategico`, e os 45 sem reconciliação se espalham por `estrategico` (24),
`sensivel` (16) e `gerais` (5). Ou seja: reconciliar um subtema com a taxonomia
nova NÃO diz nada sobre o nível dele, e a planilha de subtemas — que não tem
coluna de nível — não pode mexer nesse campo em registro que já existe.
"""

from __future__ import annotations

#: Quão sensível é o assunto. Vocabulário fechado de `tema.nivel`.
NIVEIS_DE_TEMA = ("sensivel", "estrategico", "gerais")

#: O nível com que um subtema da taxonomia estratégica nasce pela planilha.
#:
#: A planilha NÃO tem coluna de nível, então a importação precisa escolher um
#: para a linha nova. `estrategico` porque é a taxonomia estratégica que a
#: planilha descreve, e porque é o nível dos 104 subtemas já reconciliados —
#: uma linha nova nasce parecida com as vizinhas dela, não com um terceiro
#: comportamento. Em registro que JÁ EXISTE a importação não toca em `nivel`.
NIVEL_PADRAO_DA_TAXONOMIA = "estrategico"

#: A dimensão da licença social. Vocabulário fechado de `tema.camada_lso`.
CAMADAS_DE_LSO = ("legitimidade", "credibilidade", "confianca", "nao_se_aplica")
