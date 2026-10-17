"""O mês que o Score pede por `AAAA-MM`, e a faixa de anos que ele aceita.

POR QUE ESTE ARQUIVO EXISTE AGORA. `mes_de` morava em `api/score.py` como
`_mes_de`, e os casos de recusa abaixo só eram exercitados por HTTP — em
`test_consulta_da_lente.py`, que precisa de Postgres no ar para chegar à rota.
A função é parse e regra, não transporte: posta no domínio, ela se prova sem
subir nada. É o que a camada existe para permitir.

OS ATALHOS E JANELAS do mesmo módulo são cobertos por `test_recorte.py`, que é
quem os usa.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.dominio.erros import RegraViolada
from app.dominio.periodo import ANO_MAXIMO, ANO_MINIMO, mes_de


def test_o_mes_vira_o_primeiro_dia_dele():
    assert mes_de("2026-06") == date(2026, 6, 1)


def test_o_mes_de_um_digito_tambem_vale():
    """`2026-6` é o que um link escrito à mão traz, e significa junho."""
    assert mes_de("2026-6") == date(2026, 6, 1)


@pytest.mark.parametrize(
    "texto",
    [
        "2026-13",
        "2026-00",
        "abc",
        "",
        "2026",
        "2026-06-15",
        #: 99999 PASSA DO ANO MÁXIMO DO PRÓPRIO `date` (9999), então morre no
        #: parse e nunca chega à faixa — a mensagem é a de formato, não a de
        #: faixa. O teste por HTTP agrupava este caso com os de faixa e conferia
        #: só o 422, então não distinguia as duas mensagens.
        "99999-01",
    ],
)
def test_o_que_nao_e_mes_e_recusado_dizendo_o_formato(texto):
    with pytest.raises(RegraViolada) as erro:
        mes_de(texto)
    assert "AAAA-MM" in str(erro.value)


@pytest.mark.parametrize("texto", ["0001-02", "1-1", "1999-12", "2101-01"])
def test_ano_fora_da_faixa_e_recusado_dizendo_a_faixa(texto):
    """A FAIXA NÃO É CAPRICHO: as telas voltam meses a partir do pedido
    (`meses_ate`), e aritmética a partir do ano 1 estourava lá dentro como 500.
    Recusar na entrada é o que transforma aquele 500 num 422 com explicação."""
    with pytest.raises(RegraViolada) as erro:
        mes_de(texto)
    assert f"de {ANO_MINIMO} a {ANO_MAXIMO}" in str(erro.value)


@pytest.mark.parametrize("ano", [ANO_MINIMO, ANO_MAXIMO])
def test_os_extremos_da_faixa_valem(ano):
    """Os dois limites são INCLUSIVOS — um `<` no lugar do `<=` recusaria um ano
    que a mensagem de erro promete aceitar."""
    assert mes_de(f"{ano}-01") == date(ano, 1, 1)
