"""A revisão da taxonomia de subtemas pela planilha: modelo, leitura, conferência
e aplicação.

A PROVA CENTRAL DESTE ARQUIVO É A IDA E VOLTA: gerar o modelo com a taxonomia do
banco, ler o arquivo gerado e exigir que TODA linha volte `igual`. Ela cobre o
gerador, o leitor e a conferência de uma vez, e é o único teste que pega uma
coluna que escreve num formato e lê em outro — o tipo de defeito que teste por
unidade não alcança, porque cada lado está certo isoladamente.

O SEGUNDO GRUPO É O QUE A IDA E VOLTA NÃO PEGA: os 45 subtemas sem reconciliação.
Eles saem da planilha com Pilar e N2 em branco porque têm `macro_tema_id` nulo, e
a primeira versão do leitor os RECUSAVA — o importador rejeitava o estado que a
própria exportação produz. Há teste para os dois lados da regra que consertou
isso: em branco nos dois é estado legítimo, um só preenchido é recusa.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session

from app.api import importacao_de_subtemas as rota
from app.banco.sessao import obter_sessao
from app.banco.tabelas_catalogo import (
    AreaPessoa,
    BlocoTema,
    MacroTema,
    Risco,
    Tema,
    TemaRisco,
)
from app.casos_de_uso import modelo_de_subtemas
from app.casos_de_uso.importar_subtemas import (
    TETO_DE_LINHAS,
    _codigos,
    _interpretar_risco,
    aplicar,
    impressao_das_propostas,
    ler,
    propor,
)
from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_subtemas import (
    ABA_PRINCIPAL,
    FORMATO,
    SIM,
    VOCABULARIOS,
    Decisao,
    normalizar_nome,
)
from app.dominio.vocabulario_de_temas import NIVEL_PADRAO_DA_TAXONOMIA
from main import app
from tests.test_e2e_postgres import URL

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_engine = create_engine(URL, pool_pre_ping=True)


@pytest.fixture
def sessao():
    conexao = _engine.connect()
    transacao = conexao.begin()
    sessao = Session(bind=conexao, expire_on_commit=False)
    try:
        yield sessao
    finally:
        sessao.close()
        transacao.rollback()
        conexao.close()


def _cliente(sessao, perfil: str) -> TestClient:
    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": perfil}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    return TestClient(app)


@pytest.fixture
def cliente_admin(sessao):
    try:
        yield _cliente(sessao, "plataforma_edicao")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_sem_admin(sessao):
    """`crm_edicao` abre o portal do CRM e NÃO administra cadastros — é o
    contrapeso exato da guarda, e não um perfil sem acesso a nada, que passaria
    o teste de 403 pelo motivo errado."""
    try:
        yield _cliente(sessao, "crm_edicao")
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------- ajudantes
def _planilha(linhas, cabecalho=None, aba=ABA_PRINCIPAL, nota=None) -> bytes:
    """Um `.xlsx` mínimo com a aba de subtemas.

    `nota` escreve uma linha acima do cabeçalho, como o modelo real pode ter —
    é o caso que obriga o leitor a PROCURAR o cabeçalho em vez de assumir a
    linha 1.
    """
    from openpyxl import Workbook

    pasta = Workbook()
    pasta.remove(pasta.active)
    planilha = pasta.create_sheet(aba)
    if nota:
        planilha.append([nota])
    planilha.append(cabecalho or [coluna.nome for coluna in FORMATO])
    for linha in linhas:
        planilha.append(list(linha))
    arquivo = io.BytesIO()
    pasta.save(arquivo)
    return arquivo.getvalue()


def _celulas(conteudo: bytes, aba=ABA_PRINCIPAL) -> list[list]:
    import openpyxl

    pasta = openpyxl.load_workbook(io.BytesIO(conteudo))
    return [list(linha) for linha in pasta[aba].values]


@pytest.fixture
def taxonomia(sessao):
    """Um pilar, dois temas estratégicos dele, um de outro pilar, e dois riscos.

    O TEMA ESTRATÉGICO DE OUTRO PILAR é o que permite testar a hierarquia que
    não fecha — o erro mais fácil de cometer numa planilha, e o que o banco
    aceitaria em silêncio porque só `macro_tema_id` é gravado.
    """
    pilar = BlocoTema(codigo="BT-TESTE", nome="Pilar de Teste", ordem=99)
    outro_pilar = BlocoTema(codigo="BT-FORA", nome="Outro Pilar", ordem=98)
    sessao.add_all([pilar, outro_pilar])
    sessao.flush()
    macro = MacroTema(
        bloco_tema_id=pilar.id, codigo="MT-TESTE", nome="Macro de Teste", ordem=99
    )
    macro_de_fora = MacroTema(
        bloco_tema_id=outro_pilar.id, codigo="MT-FORA", nome="Macro de Fora", ordem=98
    )
    sessao.add_all([macro, macro_de_fora])
    sessao.flush()
    riscos = list(
        sessao.scalars(select(Risco).where(Risco.ativo).order_by(Risco.codigo).limit(2))
    )
    return {
        "pilar": pilar,
        "outro_pilar": outro_pilar,
        "macro": macro,
        "macro_de_fora": macro_de_fora,
        "riscos": riscos,
    }


def _linha(nome, t, *, pilar=None, macro=None, lso="", risco="", codigos=""):
    return [
        nome,
        t["pilar"].nome if pilar is None else pilar,
        t["macro"].nome if macro is None else macro,
        lso,
        risco,
        codigos,
    ]


# ===================================================== a leitura do arquivo
def test_arquivo_que_nao_abre_e_recusado_com_frase():
    with pytest.raises(RegraViolada):
        ler(b"isto nao e um xlsx")


def test_aba_que_falta_e_recusada():
    with pytest.raises(RegraViolada) as erro:
        ler(_planilha([], aba="Outra Coisa"))
    assert ABA_PRINCIPAL in str(erro.value)


def test_cabecalho_fora_do_modelo_e_recusado():
    with pytest.raises(RegraViolada):
        ler(_planilha([], cabecalho=["Assunto", "Grupo"]))


def test_cabecalho_e_procurado_abaixo_de_uma_nota():
    """O modelo pode trazer um aviso acima do cabeçalho; o leitor tem de achá-lo.

    Assumir a linha 1 faria o modelo com nota ser recusado — e a nota é
    exatamente o que ajuda quem preenche.
    """
    lidas = ler(_planilha([["Tarifa", "P", "M", "", "", ""]], nota="Preencha abaixo:"))
    assert [linha.nome for linha in lidas] == ["Tarifa"]


def test_linha_em_branco_no_meio_e_ignorada():
    conteudo = _planilha(
        [["Tarifa", "P", "M", "", "", ""], [None] * 6, ["Obras", "P", "M", "", "", ""]]
    )
    assert [linha.nome for linha in ler(conteudo)] == ["Tarifa", "Obras"]


def test_a_linha_lembra_de_onde_veio():
    """O número da linha é o que a conferência mostra, e tem de ser o da PLANILHA.

    Com nota e cabeçalho, o primeiro subtema está na linha 3 do arquivo. Numerar
    pela ordem de leitura diria "linha 1", e a pessoa procuraria no lugar errado.
    """
    lidas = ler(_planilha([["Tarifa", "P", "M", "", "", ""]], nota="Aviso"))
    assert lidas[0].linha == 3


def test_arquivo_acima_do_teto_e_recusado():
    linhas = [[f"Assunto {i}", "P", "M", "", "", ""] for i in range(TETO_DE_LINHAS + 1)]
    with pytest.raises(RegraViolada) as erro:
        ler(_planilha(linhas))
    assert str(TETO_DE_LINHAS) in str(erro.value)


@pytest.mark.parametrize(
    "valor, esperado, reconhecido",
    [
        ("Sim", True, True),
        ("sim", True, True),
        ("S", True, True),
        ("TRUE", True, True),
        ("VERDADEIRO", True, True),
        ("x", True, True),
        ("Não", False, True),
        ("nao", False, True),
        ("N", False, True),
        ("FALSO", False, True),
        ("", None, True),
        ("   ", None, True),
        ("Talvez", None, False),
    ],
)
def test_interpretar_risco(valor, esperado, reconhecido):
    """VAZIO É RESPOSTA e é diferente de `Não`: nulo quer dizer "não reconciliado
    com a v4", `false` quer dizer "reconciliado, e não é de risco".

    E "Talvez" NÃO vira nulo em silêncio — sem o segundo elemento, um valor
    estranho confundiria "digitou errado" com "deixou em branco de propósito", e
    a pessoa descobriria meses depois que aquele subtema nunca foi reconciliado.
    """
    assert _interpretar_risco(valor) == (esperado, reconhecido)


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("", ()),
        ("R01", ("R01",)),
        ("R01, R07", ("R01", "R07")),
        ("r01;R07", ("R01", "R07")),
        ("  R01 ,, R07  ", ("R01", "R07")),
    ],
)
def test_codigos(valor, esperado):
    assert _codigos(valor) == esperado


@pytest.mark.parametrize(
    "a, b",
    [
        ("Tarifa", "tarifa"),
        ("Tarifa  social", "Tarifa social"),
        (" Tarifa ", "Tarifa"),
    ],
)
def test_normalizar_nome_iguala(a, b):
    assert normalizar_nome(a) == normalizar_nome(b)


def test_normalizar_nome_nao_ignora_acento():
    """DE PROPÓSITO. A 0058 casou por nome exato e 45 temas não casaram; afrouxar
    aqui repetiria o erro na direção oposta — duas linhas diferentes virariam a
    mesma, e a importação sobrescreveria um subtema com o conteúdo de outro.
    """
    assert normalizar_nome("Água") != normalizar_nome("Agua")


# ========================================================== o modelo (.xlsx)
def test_o_cabecalho_do_modelo_e_exatamente_o_formato():
    """Uma célula a mais ou a menos na linha 1 é o que faz o leitor recusar o
    próprio modelo que o sistema gerou."""
    celulas = _celulas(modelo_de_subtemas.gerar({}))
    assert celulas[0] == [coluna.nome for coluna in FORMATO]


def test_o_modelo_sai_preenchido_com_as_linhas_recebidas():
    linhas = [{"Subtema (N3)": "Tarifa", "LSO": "confianca"}]
    celulas = _celulas(modelo_de_subtemas.gerar({}, linhas))
    assert celulas[1][0] == "Tarifa"
    assert celulas[1][FORMATO.index(next(c for c in FORMATO if c.campo == "camada_lso"))] == (
        "confianca"
    )


def test_vocabulario_vazio_nao_quebra_o_arquivo():
    """Uma base nova pode não ter risco cadastrado, e o modelo ainda tem de
    abrir: a aba sai presente e vazia, sem suspensa ligada a intervalo nulo —
    que o Excel rejeita na abertura."""
    conteudo = modelo_de_subtemas.gerar({chave: [] for chave in VOCABULARIOS})
    import openpyxl

    pasta = openpyxl.load_workbook(io.BytesIO(conteudo))
    for chave in VOCABULARIOS:
        assert modelo_de_subtemas.ROTULO_DA_ABA[chave] in pasta.sheetnames


def test_a_aba_de_riscos_poe_o_codigo_sozinho_na_coluna_a():
    """A COLUNA ACEITA SÓ O CÓDIGO. Juntar código e nome num texto colocaria na
    lista suspensa um valor que a conferência recusa — pior que não ter a dica,
    porque a pessoa escolheria da lista oferecida e veria a linha recusada."""
    conteudo = modelo_de_subtemas.gerar({"riscos": [("R01", "Reajuste negado")]})
    celulas = _celulas(conteudo, modelo_de_subtemas.ROTULO_DA_ABA["riscos"])
    assert celulas[1] == ["R01", "Reajuste negado"]


def test_as_abas_de_vocabulario_saem_protegidas():
    """A importação não cria pilar nem risco: ela escolhe do que existe. A
    proteção torna isso visível a quem abre o arquivo — o controle é a
    conferência, não o Excel."""
    import openpyxl

    conteudo = modelo_de_subtemas.gerar({"blocos_tema": ["Pilar"]})
    pasta = openpyxl.load_workbook(io.BytesIO(conteudo))
    assert pasta[modelo_de_subtemas.ROTULO_DA_ABA["blocos_tema"]].protection.sheet


# ================================================= a conferência contra o banco
def test_subtema_que_nao_existe_e_novo(sessao, taxonomia):
    lidas = ler(_planilha([_linha("Assunto Inexistente 42", taxonomia)]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.NOVO
    assert proposta.depois["macro_tema_id"] == taxonomia["macro"].id


def test_subtema_identico_ao_banco_e_igual(sessao, taxonomia):
    tema = Tema(
        nome="Assunto Já Cadastrado 42",
        nivel="estrategico",
        macro_tema_id=taxonomia["macro"].id,
        camada_lso="confianca",
        e_risco=True,
    )
    sessao.add(tema)
    sessao.flush()
    sessao.add(TemaRisco(tema_id=tema.id, risco_id=taxonomia["riscos"][0].id))
    sessao.flush()

    lidas = ler(
        _planilha(
            [
                _linha(
                    tema.nome,
                    taxonomia,
                    lso="confianca",
                    risco=SIM,
                    codigos=taxonomia["riscos"][0].codigo,
                )
            ]
        )
    )
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.IGUAL
    assert proposta.antes is None and proposta.depois is None


def test_mudanca_vira_altera_com_antes_e_depois(sessao, taxonomia):
    """O ANTES É O QUE PERMITE A TELA MOSTRAR O QUE MUDA em vez de pedir
    confiança num `.xlsx` que passou por e-mail."""
    tema = Tema(
        nome="Assunto Que Muda 42",
        nivel="estrategico",
        macro_tema_id=taxonomia["macro"].id,
        camada_lso="confianca",
        e_risco=False,
    )
    sessao.add(tema)
    sessao.flush()

    lidas = ler(_planilha([_linha(tema.nome, taxonomia, lso="legitimidade", risco=SIM)]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.ALTERA
    assert proposta.antes["camada_lso"] == "confianca"
    assert proposta.depois["camada_lso"] == "legitimidade"
    assert proposta.antes["e_risco"] is False
    assert proposta.depois["e_risco"] is True


def test_pilar_e_n2_em_branco_e_estado_legitimo(sessao, taxonomia):
    """OS 45 SUBTEMAS SEM RECONCILIAÇÃO. Eles têm `macro_tema_id` nulo e saem da
    planilha com as duas colunas em branco. A primeira versão do leitor os
    RECUSAVA — o importador rejeitava o estado que a própria exportação produz,
    e eram justamente esses 45 que a planilha existe para ajudar a reconciliar.
    """
    tema = Tema(nome="Assunto Sem Reconciliar 42", nivel="sensivel")
    sessao.add(tema)
    sessao.flush()

    lidas = ler(_planilha([_linha(tema.nome, taxonomia, pilar="", macro="")]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.IGUAL, proposta.divergencias


def test_pilar_sem_tema_estrategico_e_recusado(sessao, taxonomia):
    """MEIA CLASSIFICAÇÃO NÃO VAI PARA O BANCO. Só `macro_tema_id` é gravado, e
    um pilar sem tema estratégico não seria gravado em lugar nenhum — a linha
    pareceria aplicada e não teria efeito."""
    lidas = ler(_planilha([_linha("Assunto Meio Classificado 42", taxonomia, macro="")]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.RECUSADA
    assert any(d.coluna == "Tema estratégico (N2)" for d in proposta.divergencias)


def test_tema_estrategico_sem_pilar_e_recusado(sessao, taxonomia):
    lidas = ler(_planilha([_linha("Assunto Sem Pilar 42", taxonomia, pilar="")]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.RECUSADA
    assert any(d.coluna == "Pilar (N1)" for d in proposta.divergencias)


def test_hierarquia_que_nao_fecha_e_recusada(sessao, taxonomia):
    """O ERRO MAIS FÁCIL DE COMETER NUMA PLANILHA: o pilar de uma linha com o
    tema estratégico de outra. O banco aceitaria, e o painel passaria a agrupar
    aquele subtema sob um pilar que a planilha não diz."""
    lidas = ler(
        _planilha(
            [
                _linha(
                    "Assunto Torto 42", taxonomia, macro=taxonomia["macro_de_fora"].nome
                )
            ]
        )
    )
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.RECUSADA
    assert "não pertence ao pilar" in " ".join(d.motivo for d in proposta.divergencias)


def test_pilar_desconhecido_nao_cria_pilar(sessao, taxonomia):
    """A IMPORTAÇÃO NÃO CRIA VOCABULÁRIO. Criar o que não existe faria um erro de
    digitação virar um pilar novo — e a taxonomia é o que o painel inteiro usa
    para agrupar."""
    antes = sessao.scalar(select(BlocoTema.id).where(BlocoTema.nome == "Governanca"))
    lidas = ler(_planilha([_linha("Assunto 42", taxonomia, pilar="Governanca")]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.RECUSADA
    assert antes == sessao.scalar(
        select(BlocoTema.id).where(BlocoTema.nome == "Governanca")
    )


def test_codigo_de_risco_inexistente_e_recusado(sessao, taxonomia):
    lidas = ler(_planilha([_linha("Assunto 42", taxonomia, risco=SIM, codigos="R99")]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.RECUSADA
    assert any(d.valor == "R99" for d in proposta.divergencias)


def test_risco_ilegivel_nomeia_o_valor_digitado(sessao, taxonomia):
    """A divergência diz QUAL valor a pessoa digitou — era o que o sentinela
    `object()` da primeira versão não conseguia carregar."""
    lidas = ler(_planilha([_linha("Assunto 42", taxonomia, risco="Talvez")]))
    (proposta,) = propor(sessao, lidas)
    assert proposta.decisao is Decisao.RECUSADA
    assert any(d.valor == "Talvez" for d in proposta.divergencias)


def test_duas_linhas_com_o_mesmo_subtema_a_segunda_e_recusada(sessao, taxonomia):
    """SEM ISTO A GRAVAÇÃO ESTOURA NO ÍNDICE ÚNICO de `tema.nome` — 500 e "erro
    interno" para quem subiu, em vez da frase que resolve. O confronto com o
    banco não pega: as duas linhas são novas aqui."""
    lidas = ler(
        _planilha(
            [
                _linha("Assunto Repetido 42", taxonomia),
                _linha("assunto  repetido 42", taxonomia, lso="confianca"),
            ]
        )
    )
    primeira, segunda = propor(sessao, lidas)
    assert primeira.decisao is Decisao.NOVO
    assert segunda.decisao is Decisao.RECUSADA
    assert "linha 2" in " ".join(d.motivo for d in segunda.divergencias)


def test_uma_linha_recusada_nao_prende_as_outras(sessao, taxonomia):
    """Recusar o arquivo inteiro por uma célula errada faria uma revisão de
    taxonomia parar por um código digitado errado, com as outras linhas certas
    presas atrás dele."""
    lidas = ler(
        _planilha(
            [
                _linha("Assunto Bom 42", taxonomia),
                _linha("Assunto Ruim 42", taxonomia, codigos="R99"),
            ]
        )
    )
    boa, ruim = propor(sessao, lidas)
    assert (boa.decisao, ruim.decisao) == (Decisao.NOVO, Decisao.RECUSADA)


# ============================================================== a aplicação
def test_aplicar_cria_o_subtema_novo_com_os_riscos(sessao, taxonomia):
    codigos = ", ".join(r.codigo for r in taxonomia["riscos"])
    lidas = ler(
        _planilha(
            [_linha("Assunto Criado 42", taxonomia, lso="confianca", risco=SIM, codigos=codigos)]
        )
    )
    resumo = aplicar(sessao, propor(sessao, lidas))
    assert (resumo.criados, resumo.alterados, resumo.escritas) == (1, 0, 1)

    tema = sessao.scalar(select(Tema).where(Tema.nome == "Assunto Criado 42"))
    assert tema.macro_tema_id == taxonomia["macro"].id
    assert tema.camada_lso == "confianca"
    assert tema.e_risco is True
    assert tema.nivel == NIVEL_PADRAO_DA_TAXONOMIA
    assert sorted(tema.riscos) == sorted(r.id for r in taxonomia["riscos"])


def test_aplicar_grava_o_nome_como_a_planilha_escreveu(sessao, taxonomia):
    """`normalizar_nome` serve para COMPARAR, nunca para gravar: gravar a forma
    normalizada criaria "tarifa social" na tela onde a Aegea escreve "Tarifa
    social"."""
    lidas = ler(_planilha([_linha("  Tarifa Social Á 42  ", taxonomia)]))
    aplicar(sessao, propor(sessao, lidas))
    assert sessao.scalar(select(Tema).where(Tema.nome == "Tarifa Social Á 42")) is not None


def test_aplicar_troca_os_riscos_do_subtema_que_muda(sessao, taxonomia):
    tema = Tema(
        nome="Assunto Com Riscos 42", nivel="estrategico", macro_tema_id=taxonomia["macro"].id
    )
    sessao.add(tema)
    sessao.flush()
    sessao.add(TemaRisco(tema_id=tema.id, risco_id=taxonomia["riscos"][0].id))
    sessao.flush()

    lidas = ler(
        _planilha([_linha(tema.nome, taxonomia, codigos=taxonomia["riscos"][1].codigo)])
    )
    resumo = aplicar(sessao, propor(sessao, lidas))
    assert (resumo.criados, resumo.alterados) == (0, 1)
    sessao.expire(tema)
    assert tema.riscos == [taxonomia["riscos"][1].id]


def test_aplicar_nao_toca_no_que_a_planilha_nao_tem(sessao, taxonomia):
    """`nivel`, `tipo`, `ativo` e `area_dona_id` não estão na planilha, e em
    registro que já existe silêncio na planilha não é instrução de apagar.

    OS QUATRO SÃO VERIFICADOS. A primeira versão prometia os quatro no docstring
    e só media três — `area_dona_id` ficava de fora, e a revisão do bloco pegou.
    Era lacuna de teste e não defeito, mas um teste que promete mais do que mede
    é pior que um teste que não existe: ele faz alguém confiar.

    Medido na base: dos 45 subtemas sem reconciliação, 16 são `sensivel` e 5
    `gerais` — reconciliar um deles com a taxonomia nova não diz nada sobre o
    nível dele."""
    area = sessao.scalars(select(AreaPessoa).limit(1)).first()
    assert area is not None, "o banco de teste não tem área cadastrada"
    tema = Tema(
        nome="Assunto Sensivel 42",
        nivel="sensivel",
        tipo="estruturante",
        ativo=False,
        area_dona_id=area.id,
    )
    sessao.add(tema)
    sessao.flush()

    lidas = ler(_planilha([_linha(tema.nome, taxonomia)]))
    aplicar(sessao, propor(sessao, lidas))
    sessao.expire(tema)
    assert (tema.nivel, tema.tipo, tema.ativo) == ("sensivel", "estruturante", False)
    assert tema.area_dona_id == area.id
    assert tema.macro_tema_id == taxonomia["macro"].id


def test_aplicar_ignora_recusada_e_igual(sessao, taxonomia):
    lidas = ler(_planilha([_linha("Assunto Ruim 42", taxonomia, codigos="R99")]))
    resumo = aplicar(sessao, propor(sessao, lidas))
    assert (resumo.criados, resumo.alterados, resumo.recusadas) == (0, 0, 1)
    assert sessao.scalar(select(Tema).where(Tema.nome == "Assunto Ruim 42")) is None


# ====================================================== a impressão digital
def test_a_impressao_e_estavel_para_a_mesma_conferencia(sessao, taxonomia):
    lidas = ler(_planilha([_linha("Assunto 42", taxonomia)]))
    assert impressao_das_propostas(propor(sessao, lidas)) == impressao_das_propostas(
        propor(sessao, lidas)
    )


def test_a_impressao_muda_quando_o_banco_muda_embaixo(sessao, taxonomia):
    """O CASO QUE ELA EXISTE PARA PEGAR: alguém edita o subtema pelo Cadastro de
    Assuntos enquanto a planilha está em conferência. Sem isto, a confirmação
    aplicaria um `ALTERA` sobre um "antes" que já não é o antes — a pessoa teria
    aprovado uma mudança e aplicado outra."""
    tema = Tema(nome="Assunto Mexido 42", nivel="estrategico", camada_lso="confianca")
    sessao.add(tema)
    sessao.flush()
    lidas = ler(_planilha([_linha(tema.nome, taxonomia, lso="legitimidade")]))
    antes = impressao_das_propostas(propor(sessao, lidas))

    tema.camada_lso = "credibilidade"
    sessao.flush()
    assert impressao_das_propostas(propor(sessao, lidas)) != antes


def test_a_impressao_muda_quando_as_linhas_trocam_de_lugar(sessao, taxonomia):
    """A conferência mostra NÚMEROS DE LINHA, e a pessoa aprovou aquelas linhas.
    Reordenar sem mudar conteúdo muda a impressão, e isso é desejado."""
    a = _linha("Assunto A 42", taxonomia)
    b = _linha("Assunto B 42", taxonomia)
    uma = impressao_das_propostas(propor(sessao, ler(_planilha([a, b]))))
    outra = impressao_das_propostas(propor(sessao, ler(_planilha([b, a]))))
    assert uma != outra


# ============================================================ a ida e volta
def test_ida_e_volta_do_modelo_nao_muda_nada(sessao):
    """A PROVA CENTRAL. Gerar o modelo com a taxonomia do banco e ler o arquivo
    gerado tem de dar `igual` em toda linha.

    Cobre gerador, leitor e conferência de uma vez, e é o único teste que pega
    uma coluna que escreve num formato e lê em outro — cada lado está certo
    isoladamente, e só a volta mostra o desencontro.
    """
    conteudo = modelo_de_subtemas.gerar(
        rota._vocabularios(sessao), rota._linhas_atuais(sessao)
    )
    propostas = propor(sessao, ler(conteudo))
    assert propostas, "o banco de teste não tem subtema nenhum"
    fora_do_igual = [
        (p.lido.linha, p.lido.nome, str(p.decisao), [d.motivo for d in p.divergencias])
        for p in propostas
        if p.decisao is not Decisao.IGUAL
    ]
    assert fora_do_igual == []


def test_a_ida_e_volta_nao_grava_nada(sessao):
    """Se a volta é toda `igual`, `aplicar` não pode escrever — é o contrapeso do
    teste acima: ele prova a leitura, este prova que a decisão vira ação nenhuma.
    """
    conteudo = modelo_de_subtemas.gerar(
        rota._vocabularios(sessao), rota._linhas_atuais(sessao)
    )
    resumo = aplicar(sessao, propor(sessao, ler(conteudo)))
    assert resumo.escritas == 0


def test_as_linhas_atuais_incluem_os_nao_reconciliados(sessao, taxonomia):
    """Omitir quem não tem pilar esconderia a fila de reconciliação — e é essa
    fila que a planilha existe para ajudar a vencer."""
    tema = Tema(nome="Assunto Orfao 42", nivel="gerais")
    sessao.add(tema)
    sessao.flush()
    linhas = {linha["Subtema (N3)"]: linha for linha in rota._linhas_atuais(sessao)}
    assert linhas["Assunto Orfao 42"]["Pilar (N1)"] == ""
    assert linhas["Assunto Orfao 42"]["Tema estratégico (N2)"] == ""


def test_e_risco_nulo_sai_em_branco_e_nao_como_nao(sessao):
    """Em branco quer dizer "não reconciliado com a v4"; `Não` quer dizer
    "reconciliado, e não é de risco". Escrever `Não` no lugar de vazio apagaria
    a diferença na ida — e a volta gravaria `false` em 45 subtemas."""
    tema = Tema(nome="Assunto Sem Risco Definido 42", nivel="estrategico", e_risco=None)
    sessao.add(tema)
    sessao.flush()
    linhas = {linha["Subtema (N3)"]: linha for linha in rota._linhas_atuais(sessao)}
    assert linhas["Assunto Sem Risco Definido 42"]["É tema de risco?"] == ""


def test_o_modelo_oferece_so_vocabulario_ativo(sessao):
    """O modelo é para ESCOLHER, e oferecer um pilar aposentado convidaria a
    pessoa a classificar um subtema sob ele. É o oposto da leitura, onde o
    inativo entra porque um subtema pode já estar ligado a um."""
    aposentado = BlocoTema(
        codigo="BT-VELHO", nome="Pilar Aposentado 42", ordem=97, ativo=False
    )
    sessao.add(aposentado)
    sessao.flush()
    assert "Pilar Aposentado 42" not in rota._vocabularios(sessao)["blocos_tema"]


# ================================================================== as rotas
def test_quem_nao_administra_cadastros_nao_alcanca_nenhuma_rota(cliente_sem_admin):
    """ESCONDER O BOTÃO É CONVENIÊNCIA, NUNCA CONTROLE: um `curl` basta. A guarda
    é a dependência do router, e esta âncora é o que garante que uma rota nova
    sob este prefixo nasça protegida."""
    assert cliente_sem_admin.get("/api/taxonomia/subtemas/modelo").status_code == 403
    resposta = cliente_sem_admin.post(
        "/api/taxonomia/subtemas/conferencia",
        files={"arquivo": ("x.xlsx", b"nada", TIPO_XLSX)},
    )
    assert resposta.status_code == 403


def test_todas_as_rotas_do_prefixo_estao_protegidas():
    """A ÂNCORA ESTRUTURAL. O teste acima cobre as rotas de hoje; esta cobre a
    próxima, que ninguém vai lembrar de acrescentar ao teste acima."""
    nomes = {
        dependencia.dependency.__name__
        for dependencia in rota.rotas.dependencies
        if dependencia.dependency is not None
    }
    assert nomes == {"exigir_portal_crm", "exigir_administracao_de_cadastros"}
    caminhos = [r.path for r in rota.rotas.routes]
    assert all(c.startswith("/api/taxonomia/subtemas") for c in caminhos), caminhos


def test_as_rotas_de_subtemas_sao_ATENDIDAS_por_elas(cliente_admin):
    """A ARMADILHA QUE ESTE ARQUIVO JÁ PEGOU UMA VEZ, e agora pela via certa.

    O prefixo era `/api/importacoes/subtemas`, e a importação de agendas tem
    `POST /api/importacoes/{importacao_id}/confirmacao`: o parâmetro casa com o
    literal `subtemas`, e a confirmação caía na rota de agendas, devolvendo 422
    de "uuid inválido". Passava em todo teste de unidade — só a chamada HTTP
    mostrava.

    A PRIMEIRA VERSÃO DESTE TESTE ANDAVA PELA ÁRVORE DE ROTAS, comparando
    `rota.matches(...)` e lendo `rota.path` de cada item de `app.routes`. Ela
    passava aqui e QUEBROU NO CI: o lock pina `fastapi==0.141.1`, e nessa versão
    `include_router` deixa um `_IncludedRouter` em `app.routes` — um invólucro
    que tem `matches` e NÃO tem `path`. `AttributeError`, nos dois testes.

    O erro de fundo não foi o atributo: foi eu testar roteamento por dentro de
    estrutura privada do framework. Agora o teste pergunta o que a pessoa
    percebe — QUEM ATENDEU —, e a resposta vem no corpo do 422: o meu
    manipulador reclama do CORPO que falta; o de agendas reclamaria de um
    `importacao_id` que não é uuid. Isso não depende de versão nenhuma.
    """
    for caminho in (
        "/api/taxonomia/subtemas/conferencia",
        "/api/taxonomia/subtemas/confirmacao",
    ):
        resposta = cliente_admin.post(caminho)
        assert resposta.status_code == 422, (caminho, resposta.text)
        locais = [".".join(str(parte) for parte in d["loc"]) for d in resposta.json()["detail"]]
        # QUEM ATENDEU FOI O MEU: ele pede `arquivo` no corpo.
        assert any("arquivo" in local for local in locais), (caminho, locais)
        # E NÃO O DE AGENDAS: ele pediria um uuid no caminho.
        assert all("importacao_id" not in local for local in locais), (caminho, locais)


def test_o_prefixo_ANTIGO_ainda_cairia_na_importacao_de_agendas(cliente_admin):
    """O CONTRAPESO. Um guarda que ninguém viu falhar não prova nada.

    Este bate no caminho que o prefixo antigo produzia e mostra que ele É
    atendido pela rota de agendas — a armadilha segue viva na aplicação de
    hoje, e é só o prefixo próprio que nos tira dela. Sem este teste, o de cima
    passaria por estar medindo a coisa errada (por exemplo, se o 422 do corpo
    viesse de qualquer rota).
    """
    resposta = cliente_admin.post("/api/importacoes/subtemas/confirmacao")

    assert resposta.status_code == 422
    tipos = [d.get("type") for d in resposta.json()["detail"]]
    locais = [".".join(str(parte) for parte in d["loc"]) for d in resposta.json()["detail"]]
    assert "uuid_parsing" in tipos, resposta.text
    assert any("importacao_id" in local for local in locais), locais


def test_todos_os_caminhos_deste_roteador_ficam_sob_o_prefixo():
    """A CONFERÊNCIA ESTRUTURAL QUE SOBREVIVE A VERSÃO.

    `rotas.routes` são as rotas DO ROTEADOR, antes de ele ser incluído na
    aplicação — ali ainda são `APIRoute` com `path`, em qualquer versão. É a
    aplicação montada que embrulha tudo em `_IncludedRouter`, e era lá que a
    primeira versão deste teste ia procurar.
    """
    caminhos = [r.path for r in rota.rotas.routes]
    assert caminhos, "o roteador não tem rota nenhuma"
    assert all(c.startswith("/api/taxonomia/subtemas") for c in caminhos), caminhos


def test_baixar_o_modelo_devolve_xlsx_com_nome(cliente_admin):
    resposta = cliente_admin.get("/api/taxonomia/subtemas/modelo")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == TIPO_XLSX
    assert "taxonomia-de-subtemas.xlsx" in resposta.headers["content-disposition"]
    assert _celulas(resposta.content)[0] == [coluna.nome for coluna in FORMATO]


def test_conferencia_responde_os_totais_e_a_impressao(cliente_admin, taxonomia):
    conteudo = _planilha([_linha("Assunto Da Rota 42", taxonomia)])
    resposta = cliente_admin.post(
        "/api/taxonomia/subtemas/conferencia",
        files={"arquivo": ("subtemas.xlsx", conteudo, TIPO_XLSX)},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["totais"]["novo"] == 1
    assert set(corpo["totais"]) == {d.value for d in Decisao}
    assert corpo["impressao"]
    assert corpo["propostas"][0]["nome"] == "Assunto Da Rota 42"


def test_conferencia_nao_grava_nada(cliente_admin, sessao, taxonomia):
    conteudo = _planilha([_linha("Assunto Nao Gravado 42", taxonomia)])
    cliente_admin.post(
        "/api/taxonomia/subtemas/conferencia",
        files={"arquivo": ("subtemas.xlsx", conteudo, TIPO_XLSX)},
    )
    assert sessao.scalar(select(Tema).where(Tema.nome == "Assunto Nao Gravado 42")) is None


def test_arquivo_invalido_na_conferencia_da_422_e_nao_500(cliente_admin):
    """Um `.xls` renomeado daria 500, e a pessoa leria "erro interno" para um
    arquivo que ela pode trocar."""
    resposta = cliente_admin.post(
        "/api/taxonomia/subtemas/conferencia",
        files={"arquivo": ("x.xlsx", b"isto nao e um xlsx", TIPO_XLSX)},
    )
    assert resposta.status_code == 422


def test_confirmacao_aplica_o_que_foi_conferido(cliente_admin, sessao, taxonomia):
    conteudo = _planilha([_linha("Assunto Confirmado 42", taxonomia, lso="confianca")])
    conferencia = cliente_admin.post(
        "/api/taxonomia/subtemas/conferencia",
        files={"arquivo": ("subtemas.xlsx", conteudo, TIPO_XLSX)},
    ).json()

    resposta = cliente_admin.post(
        "/api/taxonomia/subtemas/confirmacao",
        files={"arquivo": ("subtemas.xlsx", conteudo, TIPO_XLSX)},
        data={"impressao": conferencia["impressao"]},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["criados"] == 1
    tema = sessao.scalar(select(Tema).where(Tema.nome == "Assunto Confirmado 42"))
    assert tema is not None and tema.camada_lso == "confianca"


def test_confirmacao_com_impressao_velha_e_recusada(cliente_admin, taxonomia):
    """A RECONFERÊNCIA. A pessoa aprovou um resultado; se o cadastro mudou
    debaixo dela, aplicar aquele resultado gravaria outra coisa."""
    conteudo = _planilha([_linha("Assunto Qualquer 42", taxonomia)])
    resposta = cliente_admin.post(
        "/api/taxonomia/subtemas/confirmacao",
        files={"arquivo": ("subtemas.xlsx", conteudo, TIPO_XLSX)},
        data={"impressao": "impressao que nao e a de agora"},
    )
    assert resposta.status_code == 422
    assert "Confira de novo" in resposta.text


# ======================================= a identidade do registro, e a tranca
def test_a_impressao_muda_quando_o_nome_passa_a_apontar_outro_registro(
    sessao, taxonomia
):
    """O CENÁRIO QUE A REVISÃO DO BLOCO REPRODUZIU, e que a impressão sem
    `tema_id` não pegava.

    Confere-se um `ALTERA` do tema A. Antes de confirmar, A é RENOMEADO e um
    tema B nasce com o nome e os campos que A tinha. A planilha segue falando do
    mesmo NOME, e com nome normalizado a impressão batia — mas a aplicação ia
    alterar B. A pessoa teria aprovado uma mudança num subtema e aplicado noutro.
    """
    a = Tema(nome="Assunto Trocado 42", nivel="estrategico", camada_lso="confianca")
    sessao.add(a)
    sessao.flush()

    conteudo = _planilha([_linha("Assunto Trocado 42", taxonomia, lso="legitimidade")])
    conferida = propor(sessao, ler(conteudo))
    assert conferida[0].decisao is Decisao.ALTERA
    assert conferida[0].tema_id == a.id
    impressao_conferida = impressao_das_propostas(conferida)

    a.nome = "Assunto Trocado 42 (antigo)"
    sessao.flush()
    b = Tema(nome="Assunto Trocado 42", nivel="estrategico", camada_lso="confianca")
    sessao.add(b)
    sessao.flush()

    agora = propor(sessao, ler(conteudo))
    assert agora[0].tema_id == b.id, "o nome passou a apontar outro registro"
    assert impressao_das_propostas(agora) != impressao_conferida


def test_aplicar_recusa_quando_o_subtema_mudou_sob_a_proposta(sessao, taxonomia):
    """A TRANCA, e a janela que a impressão sozinha não fecha.

    A impressão é recalculada na confirmação ANTES de gravar; entre o cálculo e
    os `UPDATE` nada impedia outra transação de entrar, e o efeito era "o último
    commit ganha" — a edição feita pelo Cadastro de Assuntos somia sem ninguém
    saber. Este teste monta a proposta, muda o tema por baixo dela e exige que
    `aplicar` recuse em vez de sobrescrever.

    O QUE ELE **NÃO** PROVA, e a revisão do bloco apanhou: a mudança é feita na
    MESMA sessão, então o mapa de identidade já carrega o valor novo e o teste
    passaria mesmo sem o `populate_existing` da releitura. Ele prova a
    comparação, não a releitura. Quem prova a releitura é
    `test_aplicar_recusa_mudanca_commitada_em_outra_sessao`, com duas conexões
    de verdade — e esse falha se o `populate_existing` sair.
    """
    tema = Tema(
        nome="Assunto Mexido Por Baixo 42", nivel="estrategico", camada_lso="confianca"
    )
    sessao.add(tema)
    sessao.flush()

    propostas = propor(
        sessao, ler(_planilha([_linha(tema.nome, taxonomia, lso="legitimidade")]))
    )
    assert propostas[0].decisao is Decisao.ALTERA

    tema.camada_lso = "credibilidade"  # alguém editou pelo Cadastro de Assuntos
    sessao.flush()

    with pytest.raises(RegraViolada) as erro:
        aplicar(sessao, propostas)
    assert "Confira de novo" in str(erro.value)
    sessao.expire(tema)
    assert tema.camada_lso == "credibilidade", "a edição alheia foi preservada"


def test_aplicar_recusa_quando_os_riscos_mudaram_sob_a_proposta(sessao, taxonomia):
    """`tema_risco` TAMBÉM ENTRA NA TRANCA. Trancar só `tema` deixaria passar
    quem mexe nos vínculos de risco sem tocar na linha do tema — e é o que
    `aplicar_riscos_do_tema` faz quando a lista de riscos é a única mudança.

    MESMA RESSALVA do teste acima: a mudança é na mesma sessão, e a releitura dos
    vínculos é consulta própria — então este também passaria sem
    `populate_existing`. Ele prova que os riscos entram na comparação.
    """
    tema = Tema(nome="Assunto Com Risco Mexido 42", nivel="estrategico")
    sessao.add(tema)
    sessao.flush()

    propostas = propor(
        sessao,
        ler(
            _planilha(
                [_linha(tema.nome, taxonomia, codigos=taxonomia["riscos"][0].codigo)]
            )
        ),
    )
    assert propostas[0].decisao is Decisao.ALTERA
    assert propostas[0].antes["riscos"] == []

    sessao.add(TemaRisco(tema_id=tema.id, risco_id=taxonomia["riscos"][1].id))
    sessao.flush()

    with pytest.raises(RegraViolada):
        aplicar(sessao, propostas)


def test_aplicar_segue_normal_quando_nada_mudou(sessao, taxonomia):
    """O CONTRAPESO DOS DOIS ACIMA: a tranca não pode recusar o caminho feliz.

    Sem este teste, um `antes` montado com chave diferente da do confronto faria
    toda confirmação recusar — e os dois testes de recusa passariam.
    """
    tema = Tema(
        nome="Assunto Que Nao Mexeu 42", nivel="estrategico", camada_lso="confianca"
    )
    sessao.add(tema)
    sessao.flush()

    propostas = propor(
        sessao, ler(_planilha([_linha(tema.nome, taxonomia, lso="legitimidade")]))
    )
    resumo = aplicar(sessao, propostas)
    assert resumo.alterados == 1
    sessao.expire(tema)
    assert tema.camada_lso == "legitimidade"


def test_aplicar_recusa_quando_o_subtema_foi_apagado(sessao, taxonomia):
    tema = Tema(nome="Assunto Apagado 42", nivel="estrategico")
    sessao.add(tema)
    sessao.flush()
    propostas = propor(
        sessao, ler(_planilha([_linha(tema.nome, taxonomia, lso="confianca")]))
    )
    assert propostas[0].decisao is Decisao.ALTERA

    sessao.delete(tema)
    sessao.flush()

    with pytest.raises(RegraViolada) as erro:
        aplicar(sessao, propostas)
    assert "apagado" in str(erro.value)


def test_novo_que_colide_no_indice_unico_da_frase_e_nao_500(sessao, taxonomia):
    """A COMPARAÇÃO É POR NOME NORMALIZADO; O ÍNDICE É EXATO.

    `normalizar_nome` colapsa caixa e espaço, então a conferência pode decidir
    `NOVO` para um nome que o índice único de `tema.nome` considera diferente de
    um já existente — e a gravação estoura. Com `gravar`, a pessoa lê o que
    aconteceu em vez de "erro interno".

    ESTE TESTE PROVA A TRADUÇÃO DO ERRO, não a corrida: ele forja a `Proposta`
    porque `propor` nunca devolveria `NOVO` para um nome que já existe. A corrida
    de verdade está em `test_duas_confirmacoes_simultaneas_a_segunda_recusa`.
    """
    sessao.add(Tema(nome="Assunto Com Caixa 42", nivel="estrategico"))
    sessao.flush()

    propostas = propor(sessao, ler(_planilha([_linha("Assunto Com Caixa 42", taxonomia)])))
    assert propostas[0].decisao is Decisao.ALTERA  # casa por nome normalizado

    # Agora o caso que o índice separa e o normalizador junta é impossível de
    # montar por `propor` — então se prova pela via direta: um `NOVO` cujo nome
    # já existe no banco com a MESMA grafia é o que a corrida entre duas
    # confirmações produz.
    from app.dominio.importacao_de_subtemas import Proposta

    forjada = Proposta(
        lido=propostas[0].lido,
        decisao=Decisao.NOVO,
        depois={"macro_tema_id": None, "camada_lso": None, "e_risco": None, "riscos": []},
    )
    with pytest.raises(RegraViolada) as erro:
        aplicar(sessao, [forjada])
    assert "já existe" in str(erro.value)


# ================================================= com DUAS sessões de verdade
#
# OS TESTES ACIMA MEXEM NA MESMA SESSÃO, e a revisão do bloco mostrou o que isso
# lhes custa: o mapa de identidade já carrega o valor novo, então eles passariam
# mesmo sem a releitura sob a tranca. Eles provam a COMPARAÇÃO; estes dois
# provam a RELEITURA e a CORRIDA, que é o que a tranca existe para resolver.
#
# O PREÇO É COMMITAR DE VERDADE. A fixture `sessao` desfaz tudo no fim, e
# transação desfeita nunca é vista por outra conexão — exatamente o que estes
# testes precisam que seja vista. Então eles commitam, e limpam pelo prefixo do
# nome no `finally`.

#: O prefixo dos temas que estes testes criam, para a limpeza achá-los.
#:
#: PELO NOME e não pelos ids coletados: se o teste morre no meio, os ids ficam
#: na variável local do teste morto e o tema fica no banco de alguém.
PREFIXO_DA_CORRIDA = "ZZ corrida "


@pytest.fixture
def duas_sessoes():
    """Duas sessões independentes, e a limpeza do que elas commitarem."""
    a = Session(_engine, expire_on_commit=False)
    b = Session(_engine, expire_on_commit=False)
    try:
        yield a, b
    finally:
        a.rollback()
        b.rollback()
        a.close()
        b.close()
        with Session(_engine) as limpeza:
            alvos = list(
                limpeza.scalars(
                    select(Tema.id).where(Tema.nome.like(f"{PREFIXO_DA_CORRIDA}%"))
                )
            )
            if alvos:
                limpeza.execute(delete(TemaRisco).where(TemaRisco.tema_id.in_(alvos)))
                limpeza.execute(delete(Tema).where(Tema.id.in_(alvos)))
                limpeza.commit()


@pytest.fixture
def hierarquia_commitada():
    """Um (pilar, tema estratégico) que JÁ está commitado no banco.

    A fixture `taxonomia` cria o par dentro da transação que será desfeita, e
    outra conexão não o veria — a planilha sairia recusada por "pilar não
    cadastrado" e o teste passaria pelo motivo errado.
    """
    with Session(_engine) as leitura:
        linha = leitura.execute(
            select(BlocoTema.nome, MacroTema.nome)
            .join(MacroTema, MacroTema.bloco_tema_id == BlocoTema.id)
            .where(BlocoTema.ativo, MacroTema.ativo)
            .order_by(MacroTema.id)
            .limit(1)
        ).first()
    assert linha is not None, "o banco de teste não tem hierarquia de temas"
    return {"pilar": linha[0], "macro": linha[1]}


def _planilha_de_um(nome: str, hierarquia, lso: str = "", risco: str = "", codigos: str = ""):
    return _planilha(
        [[nome, hierarquia["pilar"], hierarquia["macro"], lso, risco, codigos]]
    )


def test_aplicar_recusa_mudanca_commitada_em_outra_sessao(
    duas_sessoes, hierarquia_commitada
):
    """O TESTE QUE A REVISÃO PEDIU: a recusa atravessando um COMMIT de verdade.

    A confere; B altera e COMMITA; A aplica, e tem de recusar em vez de gravar
    em cima da edição de B. Os testes de mesma sessão não cobrem isto — lá o
    valor novo já está no mapa de identidade de quem compara.

    O QUE ELE AINDA NÃO FIXA, e eu medi antes de escrever isto: tirar o
    `populate_existing` da releitura NÃO faz este teste falhar. Neste arranjo de
    sessão a releitura simples volta fresca; noutro, volta velha. Quem fixa o
    mecanismo é `test_a_tranca_enxerga_o_valor_do_banco_e_nao_o_da_sessao`.
    """
    a, b = duas_sessoes
    nome = f"{PREFIXO_DA_CORRIDA}altera"

    a.add(Tema(nome=nome, nivel="estrategico", camada_lso="confianca"))
    a.commit()

    planilha = _planilha_de_um(nome, hierarquia_commitada, lso="legitimidade")
    propostas = propor(a, ler(planilha))
    assert propostas[0].decisao is Decisao.ALTERA, propostas[0].divergencias

    alheio = b.scalar(select(Tema).where(Tema.nome == nome))
    alheio.camada_lso = "credibilidade"
    b.commit()

    with pytest.raises(RegraViolada) as erro:
        aplicar(a, propostas)
    assert "Confira de novo" in str(erro.value)

    a.rollback()
    with Session(_engine) as conferencia:
        guardado = conferencia.scalar(select(Tema).where(Tema.nome == nome))
        assert guardado.camada_lso == "credibilidade", "a edição de B foi preservada"


def test_duas_confirmacoes_simultaneas_a_segunda_recusa(
    duas_sessoes, hierarquia_commitada
):
    """A CORRIDA DE VERDADE no `NOVO`, que o teste do `IntegrityError` forjava.

    As duas sessões leem a MESMA planilha com um subtema que não existe, e as
    duas decidem `NOVO` — é o que acontece quando duas pessoas confirmam a mesma
    revisão. A primeira grava; a segunda tem de ler uma frase, não um 500.
    """
    a, b = duas_sessoes
    nome = f"{PREFIXO_DA_CORRIDA}novo"
    planilha = _planilha_de_um(nome, hierarquia_commitada)

    de_a = propor(a, ler(planilha))
    de_b = propor(b, ler(planilha))
    assert de_a[0].decisao is Decisao.NOVO
    assert de_b[0].decisao is Decisao.NOVO, "B precisa ter decidido NOVO ANTES de A gravar"

    assert aplicar(a, de_a).criados == 1
    a.commit()

    with pytest.raises(RegraViolada) as erro:
        aplicar(b, de_b)
    assert "já existe" in str(erro.value)
    b.rollback()

    with Session(_engine) as conferencia:
        quantos = conferencia.scalar(
            select(func.count()).select_from(Tema).where(Tema.nome == nome)
        )
        assert quantos == 1, "a corrida não pode deixar dois subtemas com o mesmo nome"


def test_a_tranca_enxerga_o_valor_do_banco_e_nao_o_da_sessao(sessao, taxonomia):
    """O TESTE QUE FIXA O `populate_existing`, e o único que falha sem ele.

    Os de duas sessões provam a recusa atravessando um commit, mas não pinam a
    releitura: medido, eles passam com a opção removida, porque naquele arranjo
    a leitura simples já volta fresca. Isso é o oposto de uma garantia — depende
    do estado da sessão.

    AQUI A DEFASAGEM É FABRICADA, de propósito e por um caminho determinístico:
    um `UPDATE` do Core com `synchronize_session=False` muda a LINHA e deixa o
    objeto do mapa de identidade intacto. É exatamente a situação que a opção
    existe para resolver, e a asserção do meio prova que a defasagem é real
    antes de exigir que a tranca a enxergue.
    """
    tema = Tema(nome="Assunto Defasado 42", nivel="estrategico", camada_lso="confianca")
    sessao.add(tema)
    sessao.flush()

    propostas = propor(
        sessao, ler(_planilha([_linha(tema.nome, taxonomia, lso="legitimidade")]))
    )
    assert propostas[0].decisao is Decisao.ALTERA
    assert propostas[0].antes["camada_lso"] == "confianca"

    sessao.execute(
        update(Tema)
        .where(Tema.id == tema.id)
        .values(camada_lso="credibilidade")
        .execution_options(synchronize_session=False)
    )
    # A DEFASAGEM É REAL: a linha diz uma coisa, o objeto da sessão diz outra.
    # Sem esta asserção o teste poderia passar por o `UPDATE` não ter pegado.
    assert tema.camada_lso == "confianca", "a sessão tinha de estar defasada aqui"
    assert (
        sessao.execute(select(Tema.camada_lso).where(Tema.id == tema.id)).scalar_one()
        == "credibilidade"
    )

    with pytest.raises(RegraViolada) as erro:
        aplicar(sessao, propostas)
    assert "Confira de novo" in str(erro.value)
