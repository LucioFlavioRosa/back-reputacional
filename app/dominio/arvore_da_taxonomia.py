"""As dimensões de cor da Árvore da taxonomia (Metodologia).

A ÁRVORE EM SI NÃO MORA AQUI: pilar, tema, subtema, cluster e risco vêm do
Cadastro de Temas, pelos ids, a cada leitura (`app/api/arvore_da_taxonomia.py`).
Aqui fica só o que o cadastro ainda NÃO guarda: o rótulo, a cor e a ordem de
cada valor das duas classificações que pintam o subtema.

- SEVERIDADE é do RISCO PRIMÁRIO (`risco.severidade`), nunca de um campo
  repetido no subtema: o subtema herda a do risco a que aponta.
- LSO é do próprio subtema (`tema.camada_lso`), e pode ficar vazio — 47 dos 104
  não têm LSO definido, e isso é resposta, não falha.

UM LUGAR SÓ, e o front não tem cópia: a tela recebe estas listas prontas pela
rota e desenha legenda, filtro e cor a partir delas. Uma classificação nova
entra aqui (e numa coluna do cadastro) e aparece na página sem mudar a tela.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValorDeCor:
    codigo: str
    nome: str
    cor: str
    #: Desenho hachurado em vez de cor cheia — para o "ainda a definir".
    hachurado: bool = False


@dataclass(frozen=True)
class DimensaoDeCor:
    #: A chave da URL e da tela (`sev`, `lso`).
    chave: str
    #: O nome no seletor "Cor do subtema".
    nome: str
    #: O título da faixa de distribuição.
    titulo: str
    #: A frase do rodapé que explica a cor.
    explicacao: str
    #: `risco`: o valor sai do risco primário do subtema; `subtema`: do próprio.
    alvo: str
    #: O campo de onde o valor sai, no risco ou no subtema da rota.
    campo: str
    valores: tuple[ValorDeCor, ...]
    #: O balde de quem não tem valor (subtema sem risco, LSO vazio).
    vazio: ValorDeCor


SEVERIDADE = DimensaoDeCor(
    chave="sev",
    nome="Severidade",
    titulo="Severidade do risco primário",
    explicacao="Cor do subtema: severidade do risco primário, onde o dano se materializa.",
    alvo="risco",
    campo="severidade",
    valores=(
        ValorDeCor("critico", "Crítico", "#FF5C60"),
        ValorDeCor("alto", "Alto", "#FE952B"),
        ValorDeCor("moderado", "Moderado", "#F8DC00"),
    ),
    vazio=ValorDeCor("sem_risco", "Sem risco", "#C4C8D6"),
)

LSO = DimensaoDeCor(
    chave="lso",
    nome="LSO",
    titulo="Licença Social para Operar",
    explicacao=("Cor do subtema: nível de Licença Social para Operar. Hachurado: ainda a definir."),
    alvo="subtema",
    campo="lso",
    valores=(
        ValorDeCor("confianca", "Confiança", "#0027BD"),
        ValorDeCor("credibilidade", "Credibilidade", "#17E3CB"),
        ValorDeCor("legitimidade", "Legitimidade", "#9DEEE7"),
        ValorDeCor("nao_se_aplica", "Não se aplica", "#C4C8D6"),
    ),
    vazio=ValorDeCor("a_definir", "A definir", "#E2E5F0", hachurado=True),
)

#: A ordem do seletor "Cor do subtema"; a primeira é a de abertura da página.
DIMENSOES_DE_COR: tuple[DimensaoDeCor, ...] = (SEVERIDADE, LSO)
