"""De onde os KPIs Reputacionais se medem — NESTE MOMENTO.

A DECISÃO É DE PRODUTO E TEM DATA. Dono do produto, 24/10/2026, nestas
palavras: *"nada deve vir do CRM; as lentes de imprensa, mercado e
institucional são exclusivamente de fontes externas de veículos de imprensa
nesse momento"* e *"os dados de agendas do CRM devem ficar somente no CRM; os
KPIs Reputacionais são focados nesse momento em bases da Clipei, Bites e
Approach. Esse isolamento nesse momento deve ser claro."*

POR QUE UM MÓDULO COM UMA PERGUNTA SÓ, e não um `if` em cada leitura — pedido
dele, na mesma conversa: *"essa guarda nesse momento deve ser bem modular e
clara no código, pois isso pode mudar no futuro, então preciso que o código
seja bem estruturado para que mudanças não gerem muito retrabalho e códigos
mortos que poluem."*

A regra está escrita UMA vez, aqui. Quem precisa dela pergunta; ninguém a
reimplementa. Três lugares perguntam hoje:

  * `repositorio_riscos.FiltroDeRisco.tem_crm` — se as agendas contam como
    incidente na matriz de risco;
  * `api.score.listar_fontes` — que fontes a aba Calibração mostra;
  * a migration `0114`, que desliga a fonte interna da lente no cadastro, para
    que o isolamento não dependa só de código.

E NADA FOI APAGADO, que é a outra metade do pedido. A máquina que lê agendas
continua inteira e continua correta — ela é dirigida por DADO
(`score_fonte.interna`), não por código espalhado. Com a resposta em `False`
ela simplesmente não é alcançada; com `True` ela volta a ser, sem ninguém
reescrever nada. É por isso que a política é uma pergunta sobre a NATUREZA da
fonte, e não uma lista de códigos ("crm"): lista de códigos envelhece e deixa
ramo morto atrás de si.

COMO SE DESFAZ, quando o produto quiser somar as interações do CRM de volta
(está escrito como "próximas ondas" em `descricao_das_lentes`, no front):

  1. `FONTE_INTERNA_ALIMENTA_OS_KPIS = True`, aqui;
  2. `update score_fonte set lente_id = (select id from lente where codigo =
     'institucional'), ativo = true where codigo = 'crm';`

Duas linhas, e nenhum arquivo a mais.
"""

from __future__ import annotations

#: FONTE INTERNA ALIMENTA OS KPIs REPUTACIONAIS? Não, neste momento.
#:
#: "Interna" é a fonte que não lê planilha de fornecedor: ela é recontada do
#: próprio banco a cada leitura. Hoje existe exatamente uma, o CRM dos
#: Stakeholders (`score_fonte.interna = true`), e é dela que saem as agendas.
#:
#: A PERGUNTA É SOBRE A NATUREZA DA FONTE, de propósito, e não sobre o código
#: dela. Se amanhã nascer uma segunda fonte interna, ela já entra na regra sem
#: ninguém se lembrar de acrescentá-la a uma lista.
FONTE_INTERNA_ALIMENTA_OS_KPIS = False


def alimenta_os_kpis(*, interna: bool, ativo: bool) -> bool:
    """Esta fonte entra na conta dos KPIs Reputacionais?

    `ativo` é condição em qualquer cenário: fonte aposentada não conta, e isso
    não é a política deste módulo — é o significado da coluna, que a `0112`
    documenta.

    POR PALAVRA-CHAVE (`*`), porque os dois parâmetros são booleanos: na ordem
    posicional, trocá-los compila, passa a suíte de tipos e inverte a regra em
    silêncio.
    """
    return ativo and (FONTE_INTERNA_ALIMENTA_OS_KPIS or not interna)
