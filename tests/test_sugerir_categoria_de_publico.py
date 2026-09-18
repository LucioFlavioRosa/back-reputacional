"""A heurística de `sugerir_categoria_de_publico` — só a função pura `sugerir`.

Não cobre a leitura do banco (`gerar_sugestoes`/`_natureza_orgao_mais_recente_
por_instituicao`): aquilo é E/S, e o valor de testar aqui está na REGRA, que é
o que alguém vai ajustar antes de rodar o script de verdade contra a base
inteira.

`sugerir` devolve `(categoria, confianca_categoria, subcategoria,
confianca_subcategoria)` — DUAS confianças, não uma: `tipo='veiculo'` acerta a
categoria sem ambiguidade, mas não diz nada sobre a subcategoria, e as duas
coisas não podem sair misturadas numa confiança só.
"""

from __future__ import annotations

from app.banco.sugerir_categoria_de_publico import sugerir


def test_area_interna_fica_sem_sugestao():
    assert sugerir("area_interna", None, "Comunicação") == (None, "baixa", None, "baixa")


def test_palavra_chave_de_regulador_vence_o_tipo():
    # `tipo='orgao'` sozinho não diria "Reguladores" — só o nome diz. A
    # subcategoria (Federal) veio da MESMA palavra-chave, então também é alta.
    assert sugerir("orgao", "executivo", "Agência Nacional de Águas") == (
        "Reguladores", "alta", "Federal", "alta",
    )


def test_palavra_chave_de_controle_e_fiscalizacao():
    assert sugerir("orgao", None, "Tribunal de Contas do Estado") == (
        "Controle e Fiscalização", "alta", "Controle e auditoria", "alta",
    )
    assert sugerir("orgao", None, "Ministério Público Federal") == (
        "Controle e Fiscalização", "alta", "Ministério Público", "alta",
    )


def test_palavra_chave_de_entidade_setorial_sugere_a_subcategoria_tambem():
    # "Entidades Setoriais e Representativas" deixou de ser sem_quebra
    # (0037_ajusta_taxonomia_de_publicos.sql) — a palavra-chave que já
    # identificava a categoria agora identifica a subcategoria junto.
    assert sugerir("orgao", "associacao", "Sindicato dos Trabalhadores") == (
        "Entidades Setoriais e Representativas", "alta",
        "Institutos e Associações", "alta",
    )
    assert sugerir("entidade", None, "CNI") == (
        "Entidades Setoriais e Representativas", "alta",
        "Institutos e Associações", "alta",
    )


def test_esfera_por_palavra_chave_mais_natureza_orgao_decide_a_categoria():
    # "Câmara Municipal" só diz a ESFERA — falta natureza_orgao para saber se
    # é Executivo ou Legislativo. Com natureza_orgao presente, as duas saem
    # com confiança alta.
    assert sugerir("orgao", "legislativo", "Câmara Municipal de Piracicaba") == (
        "Poder Legislativo", "alta", "Municipal", "alta",
    )
    assert sugerir("orgao", "executivo", "Prefeitura de Franca") == (
        "Poder Executivo", "alta", "Municipal", "alta",
    )


def test_esfera_reconhecida_sem_natureza_orgao_nao_arrisca_so_a_categoria():
    # A ESFERA continua confiável (veio de palavra-chave) mesmo quando falta
    # natureza_orgao para saber se é Executivo ou Legislativo — só a
    # categoria fica em aberto.
    assert sugerir("orgao", None, "Prefeitura de Franca") == (
        None, "baixa", "Municipal", "alta",
    )


def test_judiciario_e_seguro_mesmo_sem_palavra_chave():
    # Sem esfera para adivinhar, e "sem_quebra": a subcategoria vazia é a
    # resposta CERTA, não um "não sei" — por isso também alta.
    assert sugerir("orgao", "judiciario", "TJSP") == ("Poder Judiciário", "alta", None, "alta")


def test_rating_por_palavra_chave_no_nome_do_investidor():
    assert sugerir("investidor", None, "S&P Global") == (
        "Mercado Financeiro e de Capitais", "alta", "Rating", "alta",
    )


def test_investidor_sem_palavra_chave_de_rating_cai_no_palpite_generico():
    # A CATEGORIA é certa pelo tipo (alta); a subcategoria (dívida x rating)
    # é um chute sem a palavra-chave (baixa) — as duas não podem se misturar.
    assert sugerir("investidor", None, "Itaú BBA") == (
        "Mercado Financeiro e de Capitais", "alta",
        "Dívida, crédito, equity e acionistas", "baixa",
    )


def test_credor_e_seguro_por_tipo_sozinho():
    # Um credor/banco É, por definição, do lado da dívida — as duas
    # confianças são altas.
    assert sugerir("credor", None, "Banco do Brasil") == (
        "Mercado Financeiro e de Capitais", "alta",
        "Dívida, crédito, equity e acionistas", "alta",
    )


def test_veiculo_vira_imprensa_com_categoria_certa_mas_subcategoria_incerta():
    # ESTE É O CASO QUE MOTIVOU AS DUAS CONFIANÇAS: `tipo='veiculo'` acerta a
    # categoria sem ambiguidade nenhuma (alta) — nenhum sinal na base diz qual
    # das 4 linhas editoriais é essa (baixa). As duas juntas numa confiança só
    # faria a categoria (certa) parecer tão duvidosa quanto a subcategoria
    # (um chute).
    assert sugerir("veiculo", None, "Valor Econômico") == (
        "Imprensa e Formadores de Opinião", "alta", None, "baixa",
    )


def test_sem_palavra_chave_e_sem_natureza_orgao_nao_ha_palpite():
    assert sugerir("orgao", None, "Sigla Desconhecida") == (None, "baixa", None, "baixa")
