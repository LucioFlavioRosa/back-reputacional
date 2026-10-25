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

A regra está escrita UMA vez, aqui, e quem precisa dela pergunta. Dois lugares
perguntam hoje:

  * `repositorio_riscos.agendas_de_incidente` — se as agendas contam como
    incidente na matriz de risco (é o gargalo: os seis caminhos das agendas
    passam por ele);
  * `api.score.listar_fontes` — que fontes a aba Calibração mostra.

O QUE ESTE MÓDULO *NÃO* É, e eu escrevi o contrário aqui antes — achado da
revisão do Codex. Ele NÃO é a única guarda do sistema. Os caminhos do ÍNDICE
(`catalogo_das_lentes`, `_somas_do_crm`, `lente_e_interna`, a série da lente)
decidem pelo CADASTRO, com a sua própria forma da pergunta
(`interna and ativo`), e não consultam esta política. Centralizar aqueles seis
lugares seria mexer no cálculo do índice, e o dono do produto foi explícito:
*"não deve mudar nenhum tipo de fórmula de cálculo"*. Fica registrado como
pendência, não feito de carona.

QUEM GARANTE O ÍNDICE, ENTÃO, é o cadastro: a `0112` aposentou a fonte
(`ativo = false`) e a `0114` a desligou de qualquer lente. É estrutural, e é por
isso que ela importa tanto quanto esta constante.

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


def pode_alimentar_os_kpis(*, interna: bool) -> bool:
    """A POLÍTICA, sozinha: uma fonte desta natureza pode entrar nos KPIs?

    Para quem NÃO tem o cadastro em mão — um filtro que já sabe que está
    falando do CRM, por exemplo. Responde só o que a política decide, e não
    finge saber se aquela fonte está ativa.
    """
    return FONTE_INTERNA_ALIMENTA_OS_KPIS or not interna


def alimenta_os_kpis(*, interna: bool, ativo: bool) -> bool:
    """Esta fonte, do jeito que ela está no cadastro, entra nos KPIs?

    A POLÍTICA E O CADASTRO, juntos. `ativo` não é regra deste módulo — é o
    significado da coluna, que a `0112` documenta: fonte aposentada não conta.

    POR PALAVRA-CHAVE (`*`), porque os dois parâmetros são booleanos: na ordem
    posicional, trocá-los compila, passa a checagem de tipos e inverte a regra
    em silêncio.
    """
    return ativo and pode_alimentar_os_kpis(interna=interna)
