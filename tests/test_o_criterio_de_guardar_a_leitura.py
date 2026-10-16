"""O que decide entre a leitura rápida e a leitura lenta de uma planilha.

POR QUE ESTA SUÍTE EXISTE. A decisão era `len(conteudo) <= 8 MB` — o byte
COMPRIMIDO do `.xlsx` — e esse proxy erra por 3,2× entre os dois arquivos reais
do projeto (medido em 16/10/2026):

    Clipei     10,53 MB comprimido  ->  66,19 MB de XML da aba   (6,3x)
    Approach    3,27 MB comprimido  ->   6,48 MB de XML da aba   (2,0x)

Com um número só para os dois, ou se recusa o cache a quem cabe ou se concede a
quem não cabe. Era o primeiro: o clipping da Clipei caía no caminho lento e
pagava 47,5 s de decodificação na conferência, contra 1,40 s pelo rápido.

O QUE SE AFIRMA AQUI é o critério, não a velocidade: medir tempo em suíte é
flaky e mede a máquina. O ganho está medido no PR; estes testes provam que a
decisão olha célula e orçamento, e que ela erra para o lado seguro.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.casos_de_uso import ingerir_mencoes


@pytest.fixture(autouse=True)
def sem_cache_do_cgroup():
    """`_memoria_do_conteiner` é `lru_cache` — sem limpar, um teste contamina o
    seguinte com a resposta do anterior."""
    ingerir_mencoes._memoria_do_conteiner.cache_clear()
    yield
    ingerir_mencoes._memoria_do_conteiner.cache_clear()


@pytest.fixture(autouse=True)
def sem_reserva_pendente():
    """A reserva é estado de MÓDULO, e um teste que a deixe suja reprova o
    seguinte com "não cabe" — falha que parece regressão e não é."""
    yield
    with ingerir_mencoes._reserva:
        ingerir_mencoes._reservado = 0


def _zip_com_abas(abas: dict[str, bytes]) -> bytes:
    """Um ZIP com as abas pedidas, e NADA MAIS.

    `celulas_da_maior_aba` lê o diretório central e os primeiros 4 KB da aba
    maior — nunca abre a planilha. Então o arquivo não precisa ser um `.xlsx`
    válido, e montá-lo à mão é o que permite escrever a aba que se quer testar,
    inclusive uma que MENTE sobre o próprio tamanho.
    """
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as pacote:
        for nome, conteudo in abas.items():
            pacote.writestr(f"xl/worksheets/{nome}", conteudo)
    return saida.getvalue()


def _aba(dimensao: str | None, recheio: int = 0) -> bytes:
    """Uma aba com a dimensão declarada (ou sem) e `recheio` bytes de corpo."""
    cabeca = b'<?xml version="1.0"?><worksheet>'
    if dimensao is not None:
        cabeca += f'<dimension ref="{dimensao}"/>'.encode()
    return cabeca + b"<sheetData>" + (b"<c/>" * (recheio // 4)) + b"</sheetData></worksheet>"


# -- a dimensão declarada ----------------------------------------------------


def test_a_dimensao_declarada_da_a_contagem_de_celulas():
    """`<dimension ref="A1:T100">` são 20 colunas por 100 linhas."""
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:T100")})

    assert ingerir_mencoes.celulas_da_maior_aba(conteudo) == 20 * 100


def test_coluna_de_duas_letras_e_base_26_com_digitos_de_1_a_26():
    """`AA` é 27, não 26 nem 28.

    Era onde um fora-por-um passaria calado: `A`=1 e `Z`=26, então `AA` é
    26 + 1. Com `A`=0 daria 26, e a estimativa sairia 3,7% baixa — pouco para
    reparar e sempre para o lado errado.
    """
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:AA100")})

    assert ingerir_mencoes.celulas_da_maior_aba(conteudo) == 27 * 100


# -- e quando ela falta, ou mente --------------------------------------------


def test_sem_dimensao_a_estimativa_vem_do_tamanho_do_xml():
    """`<dimension>` é OPCIONAL no formato; faltando, sobra o tamanho."""
    conteudo = _zip_com_abas({"sheet1.xml": _aba(None, recheio=70_000)})

    celulas = ingerir_mencoes.celulas_da_maior_aba(conteudo)

    assert celulas is not None
    assert celulas == pytest.approx(70_000 // ingerir_mencoes.XML_POR_CELULA, rel=0.1)


def test_uma_dimensao_que_mente_para_BAIXO_nao_engana():
    """A guarda que mais importa, e a razão de as duas estimativas coexistirem.

    Há quem escreva `ref="A1:A1"` numa aba de dezenas de MB. Confiando só na
    dimensão, o critério concederia a leitura guardada a um arquivo enorme — que
    é exatamente o jeito de derrubar o processo. O tamanho do XML é grosseiro
    mas nunca mente sobre ordem de grandeza, e a MAIOR das duas estimativas
    vence.
    """
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:A1", recheio=2_000_000)})

    celulas = ingerir_mencoes.celulas_da_maior_aba(conteudo)

    assert celulas is not None
    assert celulas > 10_000, "a dimensão mentirosa venceu o tamanho do XML"


def test_bytes_que_nao_sao_zip_nao_sabem_dizer():
    """E `None` é tratado como "não cabe" — adivinhar seria adivinhar para cima."""
    assert ingerir_mencoes.celulas_da_maior_aba(b"nao sou um zip") is None
    assert ingerir_mencoes.custo_da_leitura(b"nao sou um zip") is None
    assert ingerir_mencoes.vale_guardar(b"nao sou um zip") is None


def test_zip_sem_aba_nenhuma_nao_sabe_dizer():
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as pacote:
        pacote.writestr("xl/workbook.xml", b"<workbook/>")

    assert ingerir_mencoes.celulas_da_maior_aba(saida.getvalue()) is None


# -- a maior aba, não a soma -------------------------------------------------


def test_o_criterio_olha_a_MAIOR_aba_e_nao_a_soma():
    """O arquivo da Approach tem SETE abas e cada fonte lê UMA.

    Somar cobraria de uma aba o tamanho das outras seis, e recusaria o cache a
    quem cabe. A maior aba é teto para qualquer aba do arquivo.

    AS ABAS SÃO DIFERENTES E SEM DIMENSÃO, e isso é o teste e não detalhe. Uma
    primeira versão usava três abas IDÊNTICAS com `<dimension>` declarada — e o
    harness de mutação mostrou que ela não distinguia nada: com a dimensão
    vencendo, somar os tamanhos não muda a resposta, então o teste passava com o
    código somando. Sem dimensão, quem decide é o tamanho, que é justamente o
    que se quer comparar: 70 KB para a maior contra 120 KB somadas.
    """
    conteudo = _zip_com_abas({
        "sheet1.xml": _aba(None, recheio=70_000),
        "sheet2.xml": _aba(None, recheio=30_000),
        "sheet3.xml": _aba(None, recheio=20_000),
    })

    celulas = ingerir_mencoes.celulas_da_maior_aba(conteudo)

    assert celulas is not None
    pela_maior = 70_000 // ingerir_mencoes.XML_POR_CELULA
    assert celulas == pytest.approx(pela_maior, rel=0.1)
    pela_soma = 120_000 // ingerir_mencoes.XML_POR_CELULA
    assert celulas < pela_soma * 0.8, "cobrou da aba o tamanho das vizinhas"


# -- o orçamento vem do contêiner --------------------------------------------


def test_o_orcamento_sai_do_limite_do_cgroup(monkeypatch, tmp_path):
    """É o que faz a decisão viajar com o ambiente em vez de morar no código.

    O back roda em dois lugares com memórias diferentes — Container Apps com
    4 GiB e o cluster do cliente com o que o `values.yaml` dele disser. Um
    número fixo serviria a um e travaria ou mataria o outro.
    """
    limite = tmp_path / "memory.max"
    limite.write_text(str(512 * 1024 * 1024))
    monkeypatch.setattr(ingerir_mencoes, "_LIMITES_DO_CGROUP", (limite,))

    assert ingerir_mencoes.orcamento_de_leitura() == int(
        512 * 1024 * 1024 * ingerir_mencoes.FRACAO_DO_CONTEINER
    )


def test_cgroup_v1_tambem_e_lido(monkeypatch, tmp_path):
    """v2 é o que AKS e Container Apps usam; v1 ainda aparece no Docker Desktop.

    Ler só um deixaria metade dos ambientes caindo no padrão conservador sem
    ninguém notar — porque o padrão FUNCIONA, só devagar.
    """
    v2 = tmp_path / "memory.max"  # não existe
    v1 = tmp_path / "limit_in_bytes"
    v1.write_text(str(1024 * 1024 * 1024))
    monkeypatch.setattr(ingerir_mencoes, "_LIMITES_DO_CGROUP", (v2, v1))

    assert ingerir_mencoes.orcamento_de_leitura() == int(
        1024 * 1024 * 1024 * ingerir_mencoes.FRACAO_DO_CONTEINER
    )


@pytest.mark.parametrize(
    "bruto", ["max", str(1 << 63), "9223372036854771712", "isto nao e numero"]
)
def test_sem_limite_de_verdade_vale_o_padrao_conservador(monkeypatch, tmp_path, bruto):
    """`max` no v2 e um número perto de 2^63 no v1 querem dizer "sem limite".

    Tomar 40% de 2^63 daria um orçamento infinito, e aí NADA cairia no caminho
    lento — a proteção existiria no código e não no comportamento.
    """
    limite = tmp_path / "memory.max"
    limite.write_text(bruto)
    monkeypatch.setattr(ingerir_mencoes, "_LIMITES_DO_CGROUP", (limite,))

    assert ingerir_mencoes.orcamento_de_leitura() == (
        ingerir_mencoes.ORCAMENTO_SEM_CONTEINER
    )


def test_a_configuracao_vence_a_deducao(monkeypatch, tmp_path):
    """Para quem mediu o próprio ambiente e sabe mais que a heurística."""
    limite = tmp_path / "memory.max"
    limite.write_text(str(512 * 1024 * 1024))
    monkeypatch.setattr(ingerir_mencoes, "_LIMITES_DO_CGROUP", (limite,))

    configuracao = ingerir_mencoes.obter_configuracao()
    monkeypatch.setattr(configuracao, "leitura_orcamento_de_memoria", 7_777)

    assert ingerir_mencoes.orcamento_de_leitura() == 7_777


# -- e a decisão inteira -----------------------------------------------------


def test_o_BYTE_COMPRIMIDO_nao_participa_mais_da_decisao(monkeypatch):
    """O coração do PR, afirmado como decisão e não como velocidade.

    A mesma aba — 2.000 células, que é o custo real — decide diferente só
    porque o orçamento mudou. E o `.xlsx` em volta pode ter qualquer tamanho:
    o que antes bastava para recusar o cache agora não é consultado.
    """
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:T100")})
    custo = ingerir_mencoes.custo_da_leitura(conteudo)
    assert custo is not None

    monkeypatch.setattr(ingerir_mencoes, "orcamento_de_leitura", lambda: custo)
    assert ingerir_mencoes.vale_guardar(conteudo) == custo

    monkeypatch.setattr(ingerir_mencoes, "orcamento_de_leitura", lambda: custo - 1)
    assert ingerir_mencoes.vale_guardar(conteudo) is None


# -- o texto, que mora fora da aba ------------------------------------------


def _zip_com_texto(aba: bytes, quantas: int, unicas: int, bytes_do_sst: int) -> bytes:
    """Um ZIP com `sharedStrings.xml` do tamanho e dos contadores pedidos.

    O CABEÇALHO É O QUE IMPORTA aqui: `bytes_de_texto` lê o tamanho do arquivo
    no diretório central e os dois contadores nos primeiros 2 KB. O corpo é
    recheio.
    """
    cabeca = f'<?xml version="1.0"?><sst count="{quantas}" uniqueCount="{unicas}">'.encode()
    corpo = b"<si><t>x</t></si>" * max(0, (bytes_do_sst - len(cabeca)) // 17)
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as pacote:
        pacote.writestr("xl/worksheets/sheet1.xml", aba)
        pacote.writestr("xl/sharedStrings.xml", cabeca + corpo + b"</sst>")
    return saida.getvalue()


def test_sem_sharedStrings_o_texto_nao_cobra_nada():
    """O arquivo guarda o texto INLINE na aba, e o tamanho dela já o contou.

    É o que o openpyxl escreve — e foi por isso que o primeiro experimento não
    reproduziu o defeito do texto: ele gerava arquivos sem `sharedStrings`.
    """
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:T100")})

    assert ingerir_mencoes.bytes_de_texto(conteudo) == (0, 0)


def test_o_texto_materializado_usa_a_razao_count_por_unique():
    """A razão é o que a estimativa anterior não tinha.

    1.000 células apontando para 10 textos: o arquivo guarda 10 e o leitor
    materializa 1.000 — fator 100.
    """
    conteudo = _zip_com_texto(_aba("A1:A1000"), quantas=1000, unicas=10, bytes_do_sst=50_000)

    materializado, unico = ingerir_mencoes.bytes_de_texto(conteudo)

    assert unico == pytest.approx(50_000, rel=0.2)
    assert materializado == pytest.approx(unico * 100, rel=0.2)


def test_TEXTO_REPETIDO_cobra_mesmo_com_sharedStrings_minusculo():
    """O caso que derrubou a correção óbvia, e a razão de existirem dois termos.

    Somar `sharedStrings.file_size` — que foi a correção proposta na revisão —
    não pega isto: com um texto só para todas as células o arquivo é minúsculo
    e o custo continua, porque o calamine materializa uma string Python POR
    CÉLULA. Medido: 0,00 MB de `sharedStrings` contra 19,1 MB de pico.
    """
    #: POUCAS CÉLULAS E MUITO TEXTO, que é a forma do defeito: com a aba grande
    #: o termo de célula domina e a diferença fica em 1,8x — o teste passaria
    #: mas não provaria nada. Aqui o texto é o assunto.
    #:
    #: Mesma aba, mesmo `sharedStrings`; só a RAZÃO muda.
    sem_repeticao = _zip_com_texto(
        _aba("A1:A1000"), quantas=1_000, unicas=1_000, bytes_do_sst=100_000
    )
    com_repeticao = _zip_com_texto(
        _aba("A1:A1000"), quantas=1_000, unicas=1, bytes_do_sst=100_000
    )

    barato = ingerir_mencoes.custo_da_leitura(sem_repeticao)
    caro = ingerir_mencoes.custo_da_leitura(com_repeticao)

    assert barato is not None and caro is not None
    #: 1.000 células contra 1 texto é fator 1.000 no termo materializado. Afirmo
    #: 20x para não prender o coeficiente exato, que é calibragem e pode mudar.
    assert caro > barato * 20, "a repetição não foi cobrada; o `file_size` sozinho enganou"


def test_sharedStrings_sem_cabecalho_legivel_nao_sabe_dizer():
    """Sem a razão não há como estimar, e estimar sem ela SUBESTIMA.

    `None` manda a leitura para o caminho lento, que é o lado seguro.
    """
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as pacote:
        pacote.writestr("xl/worksheets/sheet1.xml", _aba("A1:T100"))
        pacote.writestr("xl/sharedStrings.xml", b"<sst>sem contadores</sst>")

    assert ingerir_mencoes.bytes_de_texto(saida.getvalue()) is None
    assert ingerir_mencoes.custo_da_leitura(saida.getvalue()) is None


def test_o_custo_do_texto_longo_nao_e_mais_invisivel():
    """A regressão que isto prende, com os números medidos.

    Aba de 0,36 MB e `sharedStrings` de 95,57 MB custavam 287,7 MB de verdade e
    eram estimados em 2,0 MB — erro de 141,8×. Só o termo de célula não vê isso.
    """
    aba = _aba("A1:E2000")  # 10.000 células, aba pequena
    so_celulas = _zip_com_abas({"sheet1.xml": aba})
    com_texto = _zip_com_texto(aba, quantas=10_000, unicas=10_000, bytes_do_sst=95_000_000)

    sem = ingerir_mencoes.custo_da_leitura(so_celulas)
    com = ingerir_mencoes.custo_da_leitura(com_texto)

    assert sem is not None and com is not None
    #: A ORDEM DE GRANDEZA é o que se afirma: o texto tem de dominar.
    assert com > sem * 50


# -- o orçamento é do processo, não do arquivo -------------------------------


def test_duas_leituras_grandes_nao_tomam_duas_vezes_o_orcamento(monkeypatch):
    """O defeito que a revisão achou: o critério era por ARQUIVO.

    Duas leituras simultâneas na mesma réplica passavam as duas pelo mesmo
    orçamento inteiro — `0,8 L` mais os ~88 MB já residentes. Num contêiner de
    512 MiB são ~498 de 537 MB, e três passam claramente.

    A SEGUNDA DEGRADA, não falha: vai pelo caminho lento, de memória constante.
    """
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:T100")})
    custo = ingerir_mencoes.custo_da_leitura(conteudo)
    assert custo is not None

    #: Orçamento para UMA leitura e meia: a segunda não cabe.
    monkeypatch.setattr(ingerir_mencoes, "orcamento_de_leitura", lambda: int(custo * 1.5))

    primeira = ingerir_mencoes.ArquivoLido(conteudo)
    assert primeira._guardar is True
    assert ingerir_mencoes.reservado_agora() == custo

    segunda = ingerir_mencoes.ArquivoLido(conteudo)
    assert segunda._guardar is False, "a segunda leitura tomou orçamento que não havia"
    assert ingerir_mencoes.reservado_agora() == custo, "reservou sem conceder"

    #: E A TERCEIRA CABE DEPOIS DE A PRIMEIRA MORRER, que é o que torna isto
    #: admissão e não um teto permanente.
    del primeira
    import gc

    gc.collect()
    assert ingerir_mencoes.reservado_agora() == 0

    terceira = ingerir_mencoes.ArquivoLido(conteudo)
    assert terceira._guardar is True


def test_o_caminho_lento_nao_reserva_nada(monkeypatch):
    """Quem vai pelo openpyxl tem memória constante e não disputa orçamento."""
    conteudo = _zip_com_abas({"sheet1.xml": _aba("A1:T100")})
    monkeypatch.setattr(ingerir_mencoes, "orcamento_de_leitura", lambda: 1)

    arquivo = ingerir_mencoes.ArquivoLido(conteudo)

    assert arquivo._guardar is False
    assert ingerir_mencoes.reservado_agora() == 0


def test_o_clipping_da_clipei_cabe_a_partir_de_1_GiB_e_nao_cabe_em_512_MiB():
    """O número que vai para quem opera o cluster, fixado como teste.

    O clipping real tem 75.370 linhas por 23 colunas — 1,73 milhão de células —,
    mas o que o critério USA é 1.982.938, porque a estimativa pelo XML é a maior
    das duas e é ela que vence. É esse o número a afirmar aqui: afirmar a
    contagem exata daria 13% de folga que o código não tem, e o teste passaria
    enquanto a recomendação ao cliente estaria errada.

    MEDIDO DE VERDADE em 16/10/2026, nos três tamanhos:

        512 MiB  ->  caminho lento, 64,79 s, pico 128 MB, sobrevive
          1 GiB  ->  caminho rápido, 1,98 s, pico 383 MB
          2 GiB  ->  caminho rápido, 3,11 s, pico 382 MB

    Com 512 MiB a leitura segue pelo caminho lento por falta de MEMÓRIA, não de
    código — e é por isso que o `aks/values.yaml` do cliente precisa subir para o
    ganho aparecer no cluster dele.
    """
    custo = 1_982_938 * ingerir_mencoes.MEMORIA_POR_CELULA

    def de(mib: int) -> int:
        return int(mib * 1024 * 1024 * ingerir_mencoes.FRACAO_DO_CONTEINER)

    assert custo > de(512), "cabe em 512 MiB — o aviso ao cliente está errado"
    assert custo <= de(1024), "não cabe em 1 GiB — a recomendação está errada"
