"""De onde os KPIs Reputacionais se medem.

Hoje, só de fontes externas: Clipei, Bites e Approach. As agendas do CRM ficam
no CRM. É decisão de produto e pode mudar, e é por isso que a regra está escrita
aqui, num lugar só, em vez de espalhada em `if`.

Quem pergunta: `repositorio_riscos.agendas_de_incidente` (a agenda conta como
incidente?) e `api.score.listar_fontes` (que fontes a Calibração mostra).

Esta política não é a única guarda. Os caminhos do índice decidem pelo cadastro
(`interna and ativo`) e não consultam este módulo: quem mantém o CRM fora do
índice é a `0112` (`ativo = false`) e a `0114` (`lente_id = null`).

Nada foi apagado. A máquina que lê agendas é dirigida por dado
(`score_fonte.interna`), então com a resposta em `False` ela não é alcançada, e
com `True` volta a ser.

Para somar o CRM de novo, os dois passos juntos:

  1. `FONTE_INTERNA_ALIMENTA_OS_KPIS = True`, aqui;
  2. `update score_fonte set lente_id = (select id from lente where codigo =
     'institucional'), ativo = true where codigo = 'crm';`
"""

from __future__ import annotations

#: Fonte interna é a que não lê planilha de fornecedor: é recontada do banco a
#: cada leitura. Hoje existe uma, o CRM dos Stakeholders. A pergunta é sobre a
#: NATUREZA da fonte, não sobre o código dela, para uma segunda fonte interna
#: entrar na regra sem lista para alguém manter.
FONTE_INTERNA_ALIMENTA_OS_KPIS = False


def pode_alimentar_os_kpis(*, interna: bool) -> bool:
    """A política sozinha: uma fonte desta natureza pode entrar nos KPIs?

    Para quem não tem o cadastro em mão e por isso não sabe se a fonte está
    ativa.
    """
    return FONTE_INTERNA_ALIMENTA_OS_KPIS or not interna


def alimenta_os_kpis(*, interna: bool, ativo: bool) -> bool:
    """Esta fonte, como está no cadastro, entra nos KPIs?

    `ativo` é o significado da coluna — fonte aposentada não conta —, e não
    regra deste módulo.

    Por palavra-chave porque os dois parâmetros são booleanos: na ordem
    posicional, trocá-los compila e inverte a regra em silêncio.
    """
    return ativo and pode_alimentar_os_kpis(interna=interna)
