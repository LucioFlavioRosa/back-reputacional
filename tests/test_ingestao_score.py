"""A planilha do fornecedor virando menção.

A regra se prova com LINHA LITERAL, e não com arquivo de exemplo: o que
interessa é o que cada célula faz — `POSITIVA` e `Positivo` caindo no mesmo
lugar, `"0"` em texto sendo zero e não nada, `Não informado` sendo recusa
declarada e não neutro. Um `.xlsx` de fixture provaria o openpyxl.

Os números de referência são os dos quatro exports de junho/2026, conferidos
contra o protótipo (`docs/handoff/Score Executivo Aegea.dc.html`).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.dominio.ingestao_score import (
    AVISO_DE_TIER,
    Descarte,
    Mapeamento,
    MencaoLida,
    ler_linha,
    ler_planilha,
    normalizar_cargo,
    para_data,
    para_inteiro,
    para_uf,
    sem_prefixo,
    somar,
)

CLIPEI = Mapeamento(
    aba="Clipping",
    colunas={
        "data": "Data",
        "sentimento": "Classificação",
        "tier": "Aegea Tier",
        "veiculo": "Veículo",
        "publico_alvo": "Público-alvo",
        "tema": "Subcategoria",
    },
)

MERCADO = Mapeamento(
    aba="Clipping",
    colunas=dict(CLIPEI.colunas),
    filtros={"Público-alvo": ("Investidores",)},
)

BITES = Mapeamento(
    aba="Posts",
    colunas={
        "data": "Data",
        "sentimento": "Sentimento",
        "engajamento": "Engajamento",
        "cargo": "Cargo",
    },
)

CM = Mapeamento(
    aba="CM",
    colunas={"data": "Data", "sentimento": "Sentimento", "engajamento": "Interações"},
)


# -- o mapeamento é cadastro, e cadastro errado grita ------------------------


def test_mapeamento_recusa_campo_que_nao_existe():
    with pytest.raises(ValueError, match="não existe em mencao"):
        Mapeamento(colunas={"data": "Data", "sentimento": "S", "curtidas": "C"})


def test_mapeamento_exige_data_e_sentimento():
    with pytest.raises(ValueError, match="sem os campos"):
        Mapeamento(colunas={"data": "Data"})


def test_mapeamento_de_json_le_o_que_a_fonte_tem_gravado():
    mapeamento = Mapeamento.de_json(
        {
            "aba": "Clipping",
            "colunas": {"data": "Data", "sentimento": "Classificação"},
            "filtros": {"Público-alvo": ["Investidores"]},
        }
    )
    assert mapeamento.aba == "Clipping"
    assert mapeamento.filtros == {"Público-alvo": ("Investidores",)}
    #: O filtro conta como coluna necessária: sem ela, o recorte seria mudo.
    assert mapeamento.colunas_necessarias == {"Data", "Classificação", "Público-alvo"}


# -- o vocabulário de cada fornecedor ----------------------------------------


@pytest.mark.parametrize(
    ("escrito", "esperado"),
    [
        ("POSITIVA", "pos"),  # Clipei
        ("Positivo", "pos"),  # Approach e Bites
        ("Neutra", "neu"),
        ("neutro ", "neu"),
        ("NEGATIVA", "neg"),
        ("Negativo", "neg"),
    ],
)
def test_o_mesmo_sentimento_com_o_nome_de_cada_fornecedor(escrito, esperado):
    linha = {"Data": date(2026, 6, 10), "Sentimento": escrito, "Engajamento": 0}
    lido = ler_linha(linha, BITES)
    assert isinstance(lido, MencaoLida)
    assert lido.sentimento == esperado


def test_sem_classificacao_a_linha_nao_vira_neutro():
    """A Bites manda 1.426 posts com `Não informado` — entrar como neutro
    inventaria uma opinião que o fornecedor não emitiu."""
    linha = {"Data": date(2026, 6, 10), "Sentimento": "Não informado"}
    assert ler_linha(linha, BITES) is Descarte.SEM_SENTIMENTO


def test_sentimento_do_fornecedor_novo_entra_por_cadastro():
    mapeamento = Mapeamento(
        colunas={"data": "Data", "sentimento": "Tom"},
        sentimentos={"favorável": "pos"},
    )
    lido = ler_linha({"Data": date(2026, 6, 1), "Tom": "Favorável"}, mapeamento)
    assert isinstance(lido, MencaoLida)
    assert lido.sentimento == "pos"


def test_tier_da_clipei():
    linha = {
        "Data": date(2026, 6, 3),
        "Classificação": "POSITIVA",
        "Aegea Tier": "Muito Relevante",
        "Veículo": "Valor Econômico",
        "Público-alvo": "Investidores",
        "Subcategoria": "Resultados",
    }
    lido = ler_linha(linha, CLIPEI)
    assert isinstance(lido, MencaoLida)
    assert lido.tier == "muito_relevante"
    assert lido.veiculo == "Valor Econômico"
    assert lido.tema_texto == "Resultados"
    #: O mês é o primeiro dia, sempre — o índice é mensal.
    assert lido.mes == date(2026, 6, 1)
    assert lido.data == date(2026, 6, 3)


def test_fonte_sem_tier_fica_sem_tier_e_nao_com_um_inventado():
    lido = ler_linha({"Data": date(2026, 6, 1), "Sentimento": "Positivo"}, BITES)
    assert isinstance(lido, MencaoLida)
    assert lido.tier is None


# -- o recorte que faz a lente Mercado sair do arquivo da Imprensa -----------


def test_o_filtro_recorta_antes_de_contar():
    dentro = {
        "Data": date(2026, 6, 3),
        "Classificação": "POSITIVA",
        "Público-alvo": "Investidores",
    }
    fora = {**dentro, "Público-alvo": "População em geral"}
    assert isinstance(ler_linha(dentro, MERCADO), MencaoLida)
    assert ler_linha(fora, MERCADO) is Descarte.FORA_DO_FILTRO
    #: A mesma linha, sem o recorte, conta para Imprensa.
    assert isinstance(ler_linha(fora, CLIPEI), MencaoLida)


# -- as células que chegam torcidas ------------------------------------------


@pytest.mark.parametrize(
    ("celula", "esperado"),
    [
        (datetime(2026, 6, 10, 14, 30), date(2026, 6, 10)),
        (date(2026, 6, 10), date(2026, 6, 10)),
        ("2026-06-10", date(2026, 6, 10)),
        ("10/06/2026", date(2026, 6, 10)),
        ("", None),
        (None, None),
        ("junho", None),
    ],
)
def test_a_data_seja_qual_for_o_formato_da_celula(celula, esperado):
    assert para_data(celula) == esperado


def test_linha_sem_data_nao_entra_em_mes_nenhum():
    linha = {"Data": None, "Sentimento": "Positivo"}
    assert ler_linha(linha, BITES) is Descarte.SEM_DATA


@pytest.mark.parametrize(
    ("celula", "esperado"),
    [
        (0, 0),
        # A aba de Community Management traz 885 linhas com o TEXTO "0".
        ("0", 0),
        (1234, 1234),
        (12.7, 12),
        # Milhar, à brasileira e à americana.
        ("1.234", 1234),
        ("1,234", 1234),
        ("12.345.678", 12345678),
        # DECIMAL, e não milhar: apagar a vírgula faria 1 virar 15.
        ("1,5", 1),
        ("1.5", 1),
        ("-42", -42),
        ("", None),
        (None, None),
        ("n/d", None),
    ],
)
def test_o_engajamento_escrito_como_texto(celula, esperado):
    assert para_inteiro(celula) == esperado


def test_o_mapeamento_diz_qual_export_a_fonte_le():
    """Duas fontes com o mesmo `arquivo` leem o mesmo anexo do fornecedor."""
    imprensa = Mapeamento.de_json(
        {"aba": "Clipping", "arquivo": "clipei",
         "colunas": {"data": "Data", "sentimento": "Classificação"}}
    )
    mercado = Mapeamento.de_json(
        {"aba": "Clipping", "arquivo": "clipei",
         "filtros": {"Público-alvo": ["Investidores"]},
         "colunas": {"data": "Data", "sentimento": "Classificação"}}
    )
    assert imprensa.arquivo == mercado.arquivo == "clipei"


def test_o_tier_que_ninguem_reconhece_vira_aviso_e_nao_descarte():
    """A matéria tem data e sentimento: jogá-la fora por causa de uma coluna
    acessória perderia notícia de verdade. Mas uma coluna inteira mapeada
    errado não pode passar calada."""
    linhas = [
        {"Data": date(2026, 6, 1), "Classificação": "POSITIVA", "Aegea Tier": "Tier 1"},
        {"Data": date(2026, 6, 2), "Classificação": "POSITIVA", "Aegea Tier": ""},
        {"Data": date(2026, 6, 3), "Classificação": "POSITIVA",
         "Aegea Tier": "Muito Relevante"},
    ]
    leitura = ler_planilha(linhas, CLIPEI)

    assert len(leitura.mencoes) == 3
    # Só o texto que ninguém reconhece conta: a célula em branco é uma fonte
    # sem tier, que é legítimo.
    assert leitura.avisos[AVISO_DE_TIER] == 1


def test_zero_em_texto_nao_vira_linha_sem_engajamento():
    lido = ler_linha(
        {"Data": date(2026, 6, 1), "Sentimento": "Negativo", "Interações": "0"}, CM
    )
    assert isinstance(lido, MencaoLida)
    assert lido.engajamento == 0


def test_cargo_vira_a_chave_da_regua():
    assert normalizar_cargo("Deputado Estadual") == "deputado_estadual"
    assert normalizar_cargo("  GOVERNADOR ") == "governador"
    assert normalizar_cargo("") is None


# -- o vocabulário de cada fornecedor, reconciliado no cadastro ---------------

#: O que a Approach cadastra: `2 - Aegea - Falta de Água` e `1 - Aegea - Corsan`
#: — o número é a posição na árvore dela e o `Aegea -` é a marca.
PREFIXO_DA_APPROACH = r"^(\d+\s*-\s*)?(Aegea\s*-\s*)?"


@pytest.mark.parametrize(
    ("escrito", "esperado"),
    [
        ("2 - Aegea - Falta de Água", "Falta de Água"),
        ("1 - Aegea - Corsan", "Corsan"),
        ("Aegea - Corsan", "Corsan"),
        ("2 - Reclamação de Serviços", "Reclamação de Serviços"),
        # Quem não usa prefixo passa intacto.
        ("Corsan", "Corsan"),
        ("Águas do Rio", "Águas do Rio"),
    ],
)
def test_o_prefixo_de_taxonomia_sai_do_rotulo(escrito, esperado):
    assert sem_prefixo(escrito, PREFIXO_DA_APPROACH) == esperado


def test_prefixo_invalido_devolve_o_rotulo_inteiro():
    """Erro de cadastro não pode custar o dado: rótulo cru é pior que limpo, e
    muito melhor que nenhum."""
    assert sem_prefixo("Corsan", "([") == "Corsan"


def test_o_prefixo_nao_come_o_rotulo_inteiro():
    """Se o que sobra é vazio, fica o original — uma unidade sem nome sumiria
    do ranking de exposição sem ninguém notar."""
    assert sem_prefixo("Aegea - ", PREFIXO_DA_APPROACH) == "Aegea - "


def test_o_apelido_junta_o_mesmo_lugar_com_dois_nomes():
    """A Bites chama de `Aegea` o que a Approach chama de `Holding`. Sem o
    apelido, a controladora vira duas barras e a maior fica menor do que é."""
    mapeamento = Mapeamento(
        colunas={"data": "Data", "sentimento": "Sentimento", "unidade": "Unidades/Empresas"},
        apelidos={"Aegea": "Holding"},
    )
    lido = ler_linha(
        {"Data": date(2026, 6, 1), "Sentimento": "Positivo", "Unidades/Empresas": "Aegea"},
        mapeamento,
    )
    assert isinstance(lido, MencaoLida)
    assert lido.unidade_texto == "Holding"


def test_a_unidade_entra_com_o_prefixo_ja_removido():
    mapeamento = Mapeamento(
        colunas={
            "data": "Data",
            "sentimento": "Sentimento",
            "unidade": "Concessionárias",
            "tema": "Tags (tema)",
        },
        prefixo_a_remover=PREFIXO_DA_APPROACH,
    )
    lido = ler_linha(
        {
            "Data": date(2026, 6, 1),
            "Sentimento": "Negativo",
            "Concessionárias": "1 - Aegea - Corsan",
            "Tags (tema)": "2 - Aegea - Falta de Água",
        },
        mapeamento,
    )
    assert isinstance(lido, MencaoLida)
    assert lido.unidade_texto == "Corsan"
    #: O mesmo cadastro limpa os dois campos de taxonomia do fornecedor.
    assert lido.tema_texto == "Falta de Água"


# -- a planilha inteira, com os descartes na cara ----------------------------


def test_a_leitura_conta_o_que_ficou_de_fora():
    linhas = [
        {"Data": date(2026, 6, 1), "Sentimento": "Positivo", "Engajamento": 10},
        {"Data": date(2026, 6, 2), "Sentimento": "Não informado"},
        {"Data": None, "Sentimento": "Negativo"},
        {"Data": date(2026, 5, 30), "Sentimento": "Negativo", "Engajamento": 0},
    ]
    leitura = ler_planilha(linhas, BITES)

    assert leitura.linhas == 4
    assert len(leitura.mencoes) == 2
    assert leitura.descartes["sem_sentimento"] == 1
    assert leitura.descartes["sem_data"] == 1
    #: Dois meses no mesmo arquivo — a substituição precisa dos dois.
    assert leitura.meses == (date(2026, 5, 1), date(2026, 6, 1))


# -- as quatro somas que toda régua consome ----------------------------------


def test_somar_produz_o_grao_de_score_mes_fonte():
    mencoes = [
        MencaoLida(mes=date(2026, 6, 1), sentimento="pos", tier="relevante"),
        MencaoLida(mes=date(2026, 6, 1), sentimento="pos", tier="relevante"),
        MencaoLida(mes=date(2026, 6, 1), sentimento="neg", tier="relevante"),
    ]
    somas = somar(mencoes)
    assert [(s.sentimento, s.tier, s.mencoes) for s in somas] == [
        ("neg", "relevante", 1),
        ("pos", "relevante", 2),
    ]


def test_a_soma_do_log_usa_a_mesma_regua_do_indice():
    """`1 + log10(1 + e)`: 9 interações valem 2, e 99 valem 3."""
    mencoes = [
        MencaoLida(mes=date(2026, 6, 1), sentimento="pos", engajamento=9),
        MencaoLida(mes=date(2026, 6, 1), sentimento="pos", engajamento=99),
    ]
    soma = somar(mencoes)[0]
    assert soma.soma_log == pytest.approx(5.0)
    assert soma.soma_engajamento == 108


def test_a_soma_do_cargo_pesa_a_voz_de_quem_postou():
    """Um governador vale 5; quem não tem cargo conhecido vale 1."""
    mencoes = [
        MencaoLida(mes=date(2026, 6, 1), sentimento="neg", cargo="governador"),
        MencaoLida(mes=date(2026, 6, 1), sentimento="neg", cargo="vereador"),
        MencaoLida(mes=date(2026, 6, 1), sentimento="neg", cargo=None),
    ]
    assert somar(mencoes)[0].soma_cargo == pytest.approx(8.0)


def test_mencao_sem_engajamento_ainda_conta_um_na_regua_log():
    """Imprensa não tem engajamento — na régua `log` cada matéria vale 1, e o
    mês não pode sumir por isso."""
    somas = somar([MencaoLida(mes=date(2026, 6, 1), sentimento="pos")])
    assert somas[0].soma_log == pytest.approx(1.0)
    assert somas[0].mencoes == 1


# =========================================== os campos que ninguém lia (0063)
#
# `CAMPOS` aceitava seis campos do "padrão Aegea" no mapeamento, `MencaoLida`
# tinha o atributo, `mencao` tinha a coluna e `ingerir_mencoes` passava o valor
# adiante — e `ler_linha` nunca os preenchia. Medido no banco antes do conserto:
# `link`, `id_fonte`, `titulo_texto` e `uf` ZERADOS nas cinco fontes, 4.392
# menções. E `app/api/lentes.py` já pedia `coluna_do_link="link"` para o dossiê.
#
# O silêncio era o problema: nenhum erro, nenhum aviso, nenhum teste.

#: O mapeamento da Clipei DEPOIS da 0063 — as cinco colunas que ela sempre
#: mandou e o cadastro ignorava.
CLIPEI_COMPLETO = Mapeamento(
    aba="Clipping",
    colunas={
        "data": "Data",
        "sentimento": "Classificação",
        "tier": "Aegea Tier",
        "veiculo": "Veículo",
        "publico_alvo": "Público-alvo",
        "tema": "Subcategoria",
        "atributo": "Atributo",
        "id_fonte": "ID",
        "link": "Arquivo/Link",
        "titulo_texto": "Título",
        "uf": "Estado do Veículo",
        "unidade": "Empresa",
    },
)

#: Uma linha como a Clipei a manda, com os nomes de coluna dela.
LINHA_DA_CLIPEI = {
    "Data": datetime(2026, 8, 1),
    "Classificação": "POSITIVA",
    "Aegea Tier": "Menos Relevante",
    "Veículo": "Rádio Betel 87.9 FM | São Francisco do Sul",
    "Público-alvo": "Opinião Pública",
    "Subcategoria": "Universalização e metas de cobertura",
    "Atributo": "7. Prosperidade Compartilhada",
    "ID": "1733052",
    "Arquivo/Link": "https://painel.clipei.com.br/anexo-email/1733052-4-34",
    "Título": "Águas de São Francisco do Sul reforça importância do investimento",
    "Estado do Veículo": "Santa Catarina",
    "Empresa": "Águas de São Francisco do Sul",
}


def test_os_cinco_campos_novos_chegam_quando_mapeados():
    lido = ler_linha(LINHA_DA_CLIPEI, CLIPEI_COMPLETO)

    assert isinstance(lido, MencaoLida)
    assert lido.id_fonte == "1733052"
    assert lido.link == "https://painel.clipei.com.br/anexo-email/1733052-4-34"
    assert lido.titulo_texto.startswith("Águas de São Francisco do Sul reforça")
    # O NOME, e nao a sigla: ver `para_uf` e a `0064`.
    assert lido.uf == "Santa Catarina"
    assert lido.unidade_texto == "Águas de São Francisco do Sul"


def test_fonte_que_NAO_mapeia_os_campos_segue_sem_eles():
    """O CONTRAPESO, e ele é o que protege as outras fontes.

    A Bites e a Approach não mandam essas colunas. Se `ler_linha` passasse a
    exigi-las, ou a inventar valor, a carga delas quebraria ou ganharia dado
    falso. `opcional` devolve nulo para campo que o cadastro não cita — e este
    teste é o que impede alguém de "melhorar" isso com um valor padrão.
    """
    sem_os_campos = Mapeamento(
        colunas={"data": "Data", "sentimento": "Classificação"}
    )

    lido = ler_linha(LINHA_DA_CLIPEI, sem_os_campos)

    assert isinstance(lido, MencaoLida)
    assert lido.id_fonte is None
    assert lido.link is None
    assert lido.titulo_texto is None
    assert lido.uf is None
    assert lido.unidade_texto is None


@pytest.mark.parametrize(
    "escrito, esperado",
    [
        # O NOME É A FORMA CANÔNICA. Decisão do dono (09/10/2026), e a `0064`
        # alargou `mencao.uf` de `char(2)` para `text` para o nome caber.
        ("Santa Catarina", "Santa Catarina"),
        # Caixa e espaço convergem, senão "SÃO PAULO" e "São Paulo" virariam
        # duas opções de filtro do mesmo estado.
        ("são paulo", "São Paulo"),
        ("SÃO PAULO", "São Paulo"),
        ("  Mato Grosso do Sul  ", "Mato Grosso do Sul"),
        # A SIGLA CONVERGE PARA O NOME: fornecedor que manda `SC` grava o mesmo
        # valor de quem manda "Santa Catarina". Mesma razão de `apelidos`.
        ("SC", "Santa Catarina"),
        ("sc", "Santa Catarina"),
        ("DF", "Distrito Federal"),
        # O QUE NÃO É ESTADO BRASILEIRO FICA COMO VEIO, e é o ganho de guardar
        # nome em vez de sigla: a versão anterior achatava isto em `IN`, e
        # "Comunidade de Madrid" diz mais do que "internacional".
        ("Comunidade de Madrid", "Comunidade de Madrid"),
        # Vazio é nulo, e é DIFERENTE de "não se aplica": nulo é "o fornecedor
        # não disse" — afirmação que só quem cadastra pode fazer.
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_para_uf(escrito, esperado):
    assert para_uf(escrito) == esperado


def test_a_coluna_opcional_que_falta_NAO_para_a_subida():
    """"Pode ter casos sem link" — decisao do dono (09/10/2026).

    Mapear uma coluna a tornava exigida, e isso e certo para `Data` e
    `Classificacao`. Para enriquecimento e duro demais: 25 mil mencoes paradas
    porque o fornecedor renomeou a coluna do link.
    """
    mapeamento = Mapeamento(
        colunas={
            "data": "Data",
            "sentimento": "Classificação",
            "link": "Arquivo/Link",
            "id_fonte": "ID",
        },
        colunas_opcionais=frozenset({"link", "id_fonte"}),
    )

    assert mapeamento.colunas_necessarias == frozenset({"Data", "Classificação"})


def test_data_e_sentimento_NAO_podem_ser_declarados_opcionais():
    """O CONTRAPESO: sem isto, o cadastro teria um jeito de gravar mencao sem mes.

    `colunas_necessarias` reexige os dois mesmo quando declarados — e nao e
    cerimonia: e a unica coisa que impede um JSON de cadastro de desligar a
    regra que `__post_init__` protege na criacao.
    """
    mapeamento = Mapeamento(
        colunas={"data": "Data", "sentimento": "Classificação"},
        colunas_opcionais=frozenset({"data", "sentimento"}),
    )

    assert mapeamento.colunas_necessarias == frozenset({"Data", "Classificação"})


def test_sem_declarar_opcionais_a_exigencia_segue_como_era():
    """As outras fontes nao podem ter afrouxado por tabela."""
    assert CLIPEI_COMPLETO.colunas_opcionais == frozenset()
    assert "Arquivo/Link" in CLIPEI_COMPLETO.colunas_necessarias


def test_o_cadastro_le_colunas_opcionais_do_json():
    mapeamento = Mapeamento.de_json(
        {
            "colunas": {"data": "Data", "sentimento": "S", "link": "L"},
            "colunas_opcionais": ["link"],
        }
    )

    assert mapeamento.colunas_opcionais == frozenset({"link"})
    assert mapeamento.colunas_necessarias == frozenset({"Data", "S"})


def test_o_id_do_fornecedor_e_a_chave_que_impede_a_mesma_mencao_duas_vezes():
    """POR QUE O `id_fonte` É O MAIS IMPORTANTE DOS CINCO.

    O índice `mencao_do_fornecedor_uma_vez` existe desde a `0055` com
    `where id_fonte is not null` — então, sem o campo preenchido, ele nunca
    protegeu nada. Duas cargas do mesmo mês criavam duplicata, e só a
    regravação por mês escondia isso.

    Medido no arquivo de 08–09/2026: 25.597 IDs distintos em 25.597 linhas.
    """
    lido = ler_linha(LINHA_DA_CLIPEI, CLIPEI_COMPLETO)

    assert isinstance(lido, MencaoLida)
    assert lido.id_fonte, "sem id_fonte o índice único do banco fica desligado"
