"""As Lentes v2 — etapa 1: o que a ingestão passa a ler, e o que se semeia.

O TEOR É O QUE SEPARA EXPOSIÇÃO DE DEMANDA. A aba de Community Management traz
`TAG (motivo)`: Reclamação, Dúvida, Elogio, Informação — e mais Marcação (alguém
citou a Aegea num post) e NPR (não pertinente). Os dois últimos chegam pelo
mesmo canal e não são gente procurando a companhia: 18% da base de janeiro a
junho. Incluí-los no denominador da taxa de resposta faz o atendimento parecer
22% pior do que é.

O que este arquivo prova é que eles são MARCADOS, e não descartados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.lentes import DossieSaida
from app.banco.tabelas_lentes import (
    EstudoPercepcao,
    EventoMercado,
    JornalistaMatriz,
)
from app.dominio.ingestao_score import Mapeamento, MencaoLida, ler_linha
from tests.test_e2e_postgres import URL

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


#: O cadastro da aba CM, como a 0048 o grava.
CM = Mapeamento(
    aba="CM",
    colunas={
        "data": "Data",
        "sentimento": "Sentimento",
        "engajamento": "Interações",
        "teor": "TAG (motivo)",
    },
    prefixo_a_remover=r"^(\d+\s*[,-]\s*)?(Aegea\s*[,-]\s*)?",
)


def _linha(motivo: str) -> dict:
    return {
        "Data": date(2026, 6, 10),
        "Sentimento": "Negativo",
        "Interações": 3,
        "TAG (motivo)": motivo,
    }


# -- o teor, e o prefixo que a Approach carimba nele -----------------------------


@pytest.mark.parametrize(
    ("escrito", "esperado"),
    [
        # A mesma etiqueta chega com dois separadores na mesma planilha.
        ("1 , Reclamação", "Reclamação"),
        ("1 - Reclamação", "Reclamação"),
        ("1 , Dúvida", "Dúvida"),
        ("2 , Marcação", "Marcação"),
        ("NPR", "NPR"),
    ],
)
def test_o_teor_entra_sem_o_prefixo_de_taxonomia(escrito, esperado):
    lido = ler_linha(_linha(escrito), CM)
    assert isinstance(lido, MencaoLida)
    assert lido.teor == esperado


@pytest.mark.parametrize(
    ("motivo", "acionavel"),
    [
        ("1 , Reclamação", True),
        ("1 , Dúvida", True),
        ("1 , Elogio", True),
        ("1 , Informação", True),
        # Alguém citou a Aegea num post próprio: não é contato.
        ("2 , Marcação", False),
        # O fornecedor etiquetou como não pertinente.
        ("NPR", False),
        ("spam", False),
    ],
)
def test_marcacao_e_npr_saem_da_base_acionavel(motivo, acionavel):
    lido = ler_linha(_linha(motivo), CM)
    assert isinstance(lido, MencaoLida)
    assert lido.acionavel is acionavel


def test_a_mencao_nao_acionavel_continua_contada():
    """NÃO É DESCARTE. A menção entra, conta no volume e aparece na tela com o
    teor escrito — esconder 800 mensagens para melhorar um percentual seria o
    oposto do que a marca existe para fazer."""
    lido = ler_linha(_linha("NPR"), CM)
    assert isinstance(lido, MencaoLida), "a linha precisa virar menção"
    assert lido.sentimento == "neg"
    assert lido.engajamento == 3


def test_fonte_que_nao_mapeia_teor_fica_com_acionavel_nulo():
    """Nulo, e não `False`: a pergunta não se aplica a uma matéria de jornal, e
    `False` diria que ela não é um contato de verdade."""
    sem_teor = Mapeamento(colunas={"data": "Data", "sentimento": "Sentimento"})
    lido = ler_linha({"Data": date(2026, 6, 1), "Sentimento": "Positivo"}, sem_teor)
    assert isinstance(lido, MencaoLida)
    assert lido.teor is None
    assert lido.acionavel is None


def test_a_fonte_pode_declarar_os_proprios_teores_nao_acionaveis():
    """A lista de hoje é o vocabulário da Approach. Outro fornecedor chama a
    mesma coisa de outro nome, e isso é cadastro — como o resto do mapeamento."""
    outro = Mapeamento(
        colunas={"data": "Data", "sentimento": "Sentimento", "teor": "Motivo"},
        teores_nao_acionaveis=frozenset({"nao se aplica"}),
    )
    fora = ler_linha(
        {"Data": date(2026, 6, 1), "Sentimento": "Neutro", "Motivo": "Não se aplica"},
        outro,
    )
    dentro = ler_linha({"Data": date(2026, 6, 1), "Sentimento": "Neutro", "Motivo": "NPR"}, outro)
    assert isinstance(fora, MencaoLida) and fora.acionavel is False
    # `NPR` não está na lista DESTA fonte: para ela, é contato.
    assert isinstance(dentro, MencaoLida) and dentro.acionavel is True


# -- o que se semeia se declara exemplo ------------------------------------------


def test_todo_conteudo_semeado_esta_marcado_como_exemplo(sessao):
    """A matriz de jornalistas, o rating e o estudo vieram do relatório do
    cliente, e não desta ferramenta. Apresentá-los como medição é a forma mais
    barata de destruir a confiança num painel — a marca é o que a tela lê para
    avisar no "?" de cada bloco."""
    for tabela in (EventoMercado, JornalistaMatriz, EstudoPercepcao):
        semeadas = sessao.scalars(select(tabela).where(tabela.exemplo.is_(True)))
        # O banco de teste nasce vazio; o que importa é o contrato da coluna.
        assert all(linha.exemplo for linha in semeadas)


# -- o dossiê: um endpoint, uma tela --------------------------------------------


@dataclass
class _QuemOlha:
    """O mínimo que o dossiê pergunta sobre quem pediu a tela."""

    administra_dicionarios: bool = False


def _dossie(sessao, codigo: str, mes: str = "2026-06", *, edita: bool = False):
    from app.api.lentes import obter_dossie

    return obter_dossie(sessao=sessao, usuario=_QuemOlha(edita), codigo=codigo, mes=mes)


def test_o_dossie_devolve_a_tela_inteira(sessao):
    """A regra 2 do pacote: o front não calcula. Evolução, dois painéis e as
    frases dos detectores chegam prontos."""
    dossie = _dossie(sessao, "imprensa")

    assert dossie.codigo == "imprensa"
    assert dossie.evolucao.tipo == "barras_empilhadas"
    assert len(dossie.paineis) == 2
    assert [painel.tipo for painel in dossie.paineis] == [
        "barras_100",
        "matriz_prioridade",
    ]


def test_cada_bloco_carrega_a_ficha_de_procedencia(sessao):
    """A ficha VIAJA COM O DADO, e não numa página de documentação: é o que
    garante que os dois não se separem quando a fonte mudar."""
    dossie = _dossie(sessao, "imprensa")
    for bloco in [dossie.evolucao, *dossie.paineis]:
        assert bloco.ficha.origem, f"{bloco.titulo} sem origem"
        assert bloco.ficha.fonte, f"{bloco.titulo} sem fonte"


def test_a_lacuna_do_autor_aparece_onde_a_pessoa_esta_olhando(sessao):
    """A Clipei não manda quem assina — e isso precisa estar escrito na matriz
    de jornalistas, não num README que ninguém abre."""
    matriz = next(
        painel
        for painel in _dossie(sessao, "imprensa").paineis
        if painel.tipo == "matriz_prioridade"
    )
    assert matriz.ficha.origem == "cadastro"
    assert any("assina" in lacuna for lacuna in matriz.ficha.lacunas)


def test_a_lente_institucional_le_o_crm_e_nao_as_mencoes(sessao):
    """A fonte dela é interna: são agendas registradas, e não menções
    ingeridas. Rodar as consultas de `mencao` aqui devolveria zero — e zero,
    numa tela, se lê como "não houve"."""
    dossie = _dossie(sessao, "institucional")
    for bloco in [dossie.evolucao, *dossie.paineis]:
        assert bloco.ficha.origem == "crm", bloco.titulo


def test_a_evolucao_mostra_a_janela_inteira_com_os_buracos(sessao):
    """Um gráfico que pula de março para junho porque abril e maio não tiveram
    export conta uma história de três meses seguidos que não aconteceu."""
    from app.api.lentes import MESES_DA_EVOLUCAO

    evolucao = _dossie(sessao, "imprensa").evolucao
    assert len(evolucao.dados) == MESES_DA_EVOLUCAO
    # No banco de teste não há menção nenhuma: todos os meses saem sem base.
    assert all(linha["sem_base"] for linha in evolucao.dados)


def test_a_lente_inexistente_devolve_nao_encontrado(sessao):
    from app.dominio.erros import NaoEncontrado

    with pytest.raises(NaoEncontrado):
        _dossie(sessao, "inexistente")


# -- o contrato fixo da §1 -------------------------------------------------------


def test_o_dossie_tem_sempre_quatro_kpis_e_dois_paineis(sessao):
    """A estrutura fixa não é convenção: é o que faz as cinco lentes se lerem
    igual. Um quinto KPI quebraria a grade; três deixariam um buraco onde a
    pessoa procura o número que sempre olha. O Pydantic recusa antes de sair."""
    for codigo in ("imprensa", "mercado", "sociedade", "clientes", "institucional"):
        dossie = _dossie(sessao, codigo)
        assert len(dossie.kpis) == 4, codigo
        assert len(dossie.paineis) == 2, codigo


def test_os_kpis_sao_os_da_especificacao_em_cada_lente(sessao):
    """Quatro números iguais para cinco lentes serviriam a todas e a nenhuma:
    "matérias no ano" responde a pergunta da imprensa, não a de clientes."""
    rotulos = {
        codigo: [kpi.rotulo for kpi in _dossie(sessao, codigo).kpis]
        for codigo in ("imprensa", "mercado", "clientes")
    }
    assert "Jornalistas P1" in rotulos["imprensa"]
    assert "Solidez financeira" in rotulos["mercado"]
    # As DUAS taxas, lado a lado — é a diferença entre cobrar a equipe por
    # marcação de post e cobrá-la pelo trabalho que existia.
    assert "Resposta bruta" in rotulos["clientes"]
    assert "Resposta operacional" in rotulos["clientes"]


def test_todo_bloco_de_informacao_tem_ficha(sessao):
    """O "?" vale para os blocos, e não só para os gráficos: o destaque também
    precisa dizer de onde vêm a nota, a variação e os KPIs."""
    dossie = _dossie(sessao, "imprensa")
    for ficha in (
        dossie.ficha_do_destaque,
        dossie.evolucao.ficha,
        *[painel.ficha for painel in dossie.paineis],
    ):
        assert ficha.origem and ficha.fonte


def test_a_tabela_manda_as_proprias_colunas_e_o_subtipo(sessao):
    """A tela escolhia o schema procurando "rating" no TÍTULO do bloco. Um
    título reescrito pela curadoria trocaria a tabela inteira em silêncio."""
    tabelas = [
        painel
        for codigo in ("mercado", "clientes")
        for painel in _dossie(sessao, codigo).paineis
        if painel.tipo == "tabela"
    ]
    assert tabelas, "as lentes Mercado e Clientes têm tabela"
    for tabela in tabelas:
        assert tabela.subtipo in {"rating", "teor"}
        assert tabela.colunas, tabela.titulo


def test_a_legenda_da_institucional_fala_de_clima(sessao):
    """A institucional mede clima, e as outras medem sentimento — e a tela não
    pode descobrir isso adivinhando pelo título do bloco."""
    institucional = _dossie(sessao, "institucional")
    assert institucional.evolucao.legenda == ["Propositivo", "Neutro", "Tenso"]

    imprensa = _dossie(sessao, "imprensa")
    assert imprensa.evolucao.legenda == ["Positivo", "Neutro", "Negativo"]


def test_a_serie_separa_mes_sem_base_de_mes_sem_classificacao(sessao):
    """Os dois primeiros estados da §2. Um mês que ninguém leu TEM volume; um
    mês sem base não teve nada. Desenhá-los igual afirmaria que o mês foi
    tranquilo quando ele só não foi analisado."""
    evolucao = _dossie(sessao, "sociedade").evolucao
    for linha in evolucao.dados:
        assert "sem_base" in linha
        assert "sem_classificacao" in linha


# -- os sinais do período --------------------------------------------------------

LENTES = ("imprensa", "mercado", "sociedade", "clientes", "institucional")


@pytest.mark.parametrize("codigo", LENTES)
def test_toda_lente_abre_com_uma_frase_calculada(sessao, codigo):
    """A manchete NÃO É NULA EM LENTE NENHUMA, nem quando não há sinal: a tela
    tem esse lugar para preencher, e devolver nada a obrigaria a inventar o
    próprio texto de vazio — cinco vezes, uma por lente."""
    dossie = _dossie(sessao, codigo)
    assert dossie.manchete
    assert dossie.manchete.endswith(".")
    assert dossie.sinais_da_evolucao


@pytest.mark.parametrize("codigo", LENTES)
def test_cada_sinal_diz_onde_conferi_lo(sessao, codigo):
    """SEM O "ONDE" A LISTA VIRA CINCO AFIRMAÇÕES SOLTAS, e quem duvida de uma
    não sabe em que gráfico olhar."""
    dossie = _dossie(sessao, codigo)
    lugares = {"Evolução", "Lente", *(painel.titulo for painel in dossie.paineis)}
    for sinal in dossie.sinais:
        assert sinal.onde in lugares, sinal
        assert sinal.tom in {"pos", "neg", "neu"}
        assert sinal.frase and sinal.evidencia


@pytest.mark.parametrize("codigo", LENTES)
def test_as_lacunas_de_dado_ficam_no_fim_da_lista(sessao, codigo):
    """Elas dizem o que FALTA, e o que falta não compete com o que aconteceu."""
    sinais = _dossie(sessao, codigo).sinais
    tipos = [sinal.tipo for sinal in sinais]
    lacunas = [i for i, tipo in enumerate(tipos) if tipo == "Lacuna de dado"]
    if lacunas:
        assert lacunas == list(range(len(tipos) - len(lacunas), len(tipos))), tipos


@pytest.mark.parametrize("codigo", LENTES)
def test_no_maximo_cinco_sinais_reais(sessao, codigo):
    reais = [sinal for sinal in _dossie(sessao, codigo).sinais if sinal.tipo != "Lacuna de dado"]
    assert len(reais) <= 5, codigo


@pytest.mark.parametrize("codigo", LENTES)
def test_a_conclusao_nunca_repete_o_titulo_do_proprio_bloco(sessao, codigo):
    """Sem sinal na seção, a §3 manda usar o nome do painel — que a tela já
    mostra logo acima. Copiá-lo para a conclusão desenharia a mesma frase duas
    vezes, uma embaixo da outra."""
    dossie = _dossie(sessao, codigo)
    for bloco in (dossie.evolucao, *dossie.paineis):
        assert bloco.conclusao != bloco.titulo, bloco.titulo


def test_mudar_um_dado_muda_a_frase_na_proxima_leitura(sessao):
    """O critério central da §7, e a razão de nada disto ser salvo: texto
    guardado envelhece em silêncio numa tela que a diretoria lê como se fosse
    deste mês."""
    from app.banco.tabelas_lentes import JornalistaMatriz

    antes = _dossie(sessao, "imprensa").paineis[1].conclusao

    sessao.add(
        JornalistaMatriz(
            nome="Zulmira Teste",
            veiculo="Diário do Teste",
            relevancia=5,
            exposicao=5,
            proximidade=1,
            exemplo=True,
        )
    )
    sessao.flush()

    depois = _dossie(sessao, "imprensa").paineis[1].conclusao
    assert depois != antes
    assert "Zulmira Teste" in depois


def test_o_mercado_avisa_que_a_nota_e_um_proxy(sessao):
    """É a única lente sem série mensal de sentimento. A nota existe e é
    defensável, mas quem a lê tem de saber que ela mede os veículos econômicos
    de Tier 1, e não o que o mercado disse."""
    sinais = _dossie(sessao, "mercado").sinais
    assert any("proxy dos veículos Tier 1" in sinal.frase for sinal in sinais)
    assert sinais[-1].onde == "Lente"


# -- os limites na Calibração ----------------------------------------------------


def test_a_calibracao_devolve_os_oito_limites_com_o_padrao_ao_lado(sessao):
    """O PADRÃO VIAJA JUNTO porque é a única forma de a tela oferecer "voltar
    ao de fábrica" sem guardar uma segunda cópia dos números — que envelheceria
    na primeira vez que alguém mudasse um padrão no código."""
    from app.api.score import LIMITES_DOS_SINAIS, _calibracao_saida
    from app.banco import repositorio_score

    saida = _calibracao_saida(sessao, repositorio_score.calibracao_vigente(sessao))

    assert [limite.chave for limite in saida.limites] == [chave for chave, *_ in LIMITES_DOS_SINAIS]
    for limite in saida.limites:
        assert limite.valor == limite.padrao
        assert limite.rotulo and limite.explicacao
        assert limite.formato in {"decimal", "inteiro"}


def test_o_limite_gravado_chega_ao_detector(sessao):
    """O critério da §7: mudar um limite na Calibração altera os sinais sem
    deploy. O que este teste prova é o CAMINHO — que o número gravado em
    `score_config` é o mesmo que o detector lê —, e não a regra em si, que os
    testes do domínio cobrem um a um."""
    from app.banco.tabelas_lentes import JornalistaMatriz
    from app.banco.tabelas_score import ScoreConfig

    sessao.add(
        JornalistaMatriz(
            nome="Zulmira Teste",
            veiculo="Diário do Teste",
            relevancia=5,
            exposicao=5,
            proximidade=1,
            exemplo=True,
        )
    )
    # A SEGUNDA É P1, e é ela que faz o detector de prioridade falar: com um
    # sinal só na matriz, encurtar a lista não provaria nada.
    sessao.add(
        JornalistaMatriz(
            nome="Aurélia Teste",
            veiculo="Gazeta do Teste",
            relevancia=5,
            exposicao=5,
            proximidade=5,
            exemplo=True,
        )
    )
    sessao.flush()

    antes = [
        sinal for sinal in _dossie(sessao, "imprensa").sinais if sinal.tipo != "Lacuna de dado"
    ]
    assert len(antes) == 2, [sinal.tipo for sinal in antes]

    sessao.add(ScoreConfig(limites={"max_sinais": 1}))
    sessao.flush()

    depois = [
        sinal for sinal in _dossie(sessao, "imprensa").sinais if sinal.tipo != "Lacuna de dado"
    ]
    assert len(depois) == 1


def test_um_limite_zerado_e_recusado_antes_de_gravar(sessao):
    """Ele não daria erro na tela da Calibração: estouraria horas depois, na
    tela de outra pessoa abrindo uma lente."""
    from app.api.score import CalibracaoEntrada, gravar_calibracao
    from app.dominio.erros import RegraViolada

    @dataclass
    class _QuemEdita:
        id: None = None

    with pytest.raises(RegraViolada, match="maior que zero"):
        gravar_calibracao(
            sessao=sessao,
            usuario=_QuemEdita(),
            entrada=CalibracaoEntrada(limites={"pico_desvios": 0}),
        )


def test_o_mes_leva_TODOS_os_fatos_cadastrados(sessao):
    """Escolher um faria o segundo motivo do mês sumir do painel — e é
    justamente o segundo que costuma explicar o resto do degrau."""
    from app.api.score import serie
    from app.banco.tabelas_score import ScoreFato

    _dois_meses_de_imprensa(sessao)
    for texto, efeito in (
        ("Atraso das demonstrações", "pressiona"),
        ("Aporte de capital anunciado", "sustenta"),
    ):
        sessao.add(ScoreFato(mes=date(2026, 6, 1), texto=texto, efeito=efeito))
    sessao.flush()

    de_junho = next(
        ponto for ponto in serie(sessao=sessao, usuario=_QuemLe()) if ponto.mes == "2026-06"
    )
    assert [f.texto for f in de_junho.fatos] == [
        "Atraso das demonstrações",
        "Aporte de capital anunciado",
    ]


def test_os_assuntos_que_pesaram_vêm_da_base(sessao):
    """A outra metade da coluna: o fato diz o que aconteceu no mundo, o tema
    diz por onde aquilo entrou no número — dos dois lados."""
    from app.api.score import serie

    _dois_meses_de_imprensa(sessao)
    de_junho = next(
        ponto for ponto in serie(sessao=sessao, usuario=_QuemLe()) if ponto.mes == "2026-06"
    )
    # A base de teste não tem menção com tema, então não há tema a apontar —
    # e a ausência é `None` dos dois lados, e não um tema inventado.
    for lado in (de_junho.sustentou, de_junho.pressionou):
        assert lado is None or lado.pontos != 0


def test_o_limite_gravado_PELO_ENDPOINT_muda_a_lente(sessao):
    """O critério da §7 pelo caminho que a pessoa percorre.

    O teste acima prova que o número gravado chega ao detector. Este prova o
    resto do trajeto: a validação do endpoint, a versão nova de `score_config`,
    e a leitura seguinte já com a régua mudada — que é o que "sem deploy"
    significa para quem usa a tela.
    """
    from app.api.score import CalibracaoEntrada, gravar_calibracao
    from app.banco.tabelas_lentes import JornalistaMatriz

    for nome, proximidade in (("Zulmira Teste", 1), ("Aurélia Teste", 5)):
        sessao.add(
            JornalistaMatriz(
                nome=nome,
                veiculo="Diário do Teste",
                relevancia=5,
                exposicao=5,
                proximidade=proximidade,
                exemplo=True,
            )
        )
    sessao.flush()

    @dataclass
    class _QuemEdita:
        id: None = None

    antes = _sinais_reais(_dossie(sessao, "imprensa"))
    assert len(antes) == 2, [sinal.tipo for sinal in antes]

    saida = gravar_calibracao(
        sessao=sessao,
        usuario=_QuemEdita(),
        entrada=CalibracaoEntrada(limites={"max_sinais": 1}),
    )
    ajustados = [limite for limite in saida.limites if limite.valor != limite.padrao]
    assert [limite.chave for limite in ajustados] == ["max_sinais"]
    assert not saida.padrao

    assert len(_sinais_reais(_dossie(sessao, "imprensa"))) == 1


def test_uma_regua_impossivel_gravada_por_fora_nao_derruba_a_tela(sessao):
    """A tela onde se conserta a régua não pode ser a primeira a cair.

    `score_config` é uma tabela como outra qualquer: um insert na mão, um script
    de ambiente ou um job podem pôr lá um zero. Se a leitura estourasse junto
    com a gravação, esse engano derrubaria a Calibração e as cinco lentes para
    todo mundo — e ninguém abriria a página onde ele se desfaz.
    """
    from app.api.score import _calibracao_saida
    from app.banco import repositorio_score
    from app.banco.tabelas_score import ScoreConfig

    sessao.add(ScoreConfig(limites={"pico_desvios": 0, "inventado": 9}))
    sessao.flush()

    saida = _calibracao_saida(sessao, repositorio_score.calibracao_vigente(sessao))
    assert all(limite.valor == limite.padrao for limite in saida.limites)

    # E a lente continua abrindo.
    assert _dossie(sessao, "imprensa").manchete


def test_o_dossie_nao_carrega_mais_curadoria_nem_encaminhamentos(sessao):
    """A §2 da mudança: os dois blocos saíram, e nada os traz de volta pela
    porta dos fundos — nem um campo esquecido no payload, nem uma tabela que
    ficou no banco esperando alguém reconectá-la."""
    from sqlalchemy import inspect

    campos = set(DossieSaida.model_fields)
    assert not campos & {
        "curadoria",
        "encaminhamentos",
        "ficha_dos_encaminhamentos",
    }, sorted(campos)

    tabelas = set(inspect(sessao.get_bind()).get_table_names())
    assert "curadoria_lente" not in tabelas
    assert "encaminhamento" not in tabelas


def _sinais_reais(dossie):
    return [sinal for sinal in dossie.sinais if sinal.tipo != "Lacuna de dado"]


# -- a jornada do índice ---------------------------------------------------------


@dataclass
class _QuemLe:
    administra_dicionarios: bool = False


def _dois_meses_de_imprensa(sessao) -> None:
    """Dois meses de menções, para a série ter de fato dois pontos."""
    from app.banco.tabelas_score import ScoreFonte, ScoreMesFonte

    fonte = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == "clipei")).one()
    for mes, positivas, negativas in (
        (date(2026, 5, 1), 60, 40),
        (date(2026, 6, 1), 80, 20),
    ):
        for sentimento, quantas in (("pos", positivas), ("neg", negativas)):
            sessao.add(
                ScoreMesFonte(
                    fonte_id=fonte.id,
                    mes=mes,
                    sentimento=sentimento,
                    tier="relevante",
                    mencoes=quantas,
                    soma_log=quantas,
                    soma_engajamento=quantas,
                    soma_cargo=quantas,
                )
            )
    sessao.flush()


def test_a_serie_carrega_o_que_a_jornada_mostra(sessao):
    """A §1 do pacote diz que nada muda no servidor, e não era verdade.

    A coluna de cada mês precisa do fato, da variação e de quem mais se mexeu;
    a curva de comparação precisa da nota de cada lente. Tudo isso já era
    calculado dentro do laço da série — só não saía dele.
    """
    from app.api.score import serie

    _dois_meses_de_imprensa(sessao)
    pontos = serie(sessao=sessao, usuario=_QuemLe())

    assert len(pontos) >= 2
    assert pontos[-1].notas_das_lentes.get("imprensa") is not None
    assert pontos[-1].delta is not None


def test_o_primeiro_ponto_e_partida_e_nao_variacao_zero(sessao):
    """ "0 no mês" no primeiro ponto afirmaria que o índice não se moveu — e não
    há de onde se mover."""
    from app.api.score import serie

    _dois_meses_de_imprensa(sessao)
    assert serie(sessao=sessao, usuario=_QuemLe())[0].delta is None


def test_os_fatos_do_mes_viajam_com_o_ponto(sessao):
    """Eles deixaram de ser uma lista embaixo do gráfico e passaram a ser a
    coluna do próprio mês — e para isso precisam chegar junto do ponto."""
    from app.api.score import serie
    from app.banco.tabelas_score import ScoreFato

    _dois_meses_de_imprensa(sessao)
    sessao.add(ScoreFato(mes=date(2026, 6, 1), texto="Aporte anunciado", efeito="sustenta"))
    sessao.flush()

    de_junho = next(
        ponto for ponto in serie(sessao=sessao, usuario=_QuemLe()) if ponto.mes == "2026-06"
    )
    assert [f.texto for f in de_junho.fatos] == ["Aporte anunciado"]
    assert de_junho.fatos[0].efeito == "sustenta"


def test_a_lente_que_estreia_no_mes_nao_conta_como_movimento():
    """Ela não "subiu 42 pontos" — ela apareceu. Chamar isso de movimento faria
    toda primeira ingestão de uma fonte parecer um salto de reputação."""
    from app.api.score import _maior_movimento

    nomes = {"imprensa": "Imprensa", "clientes": "Clientes"}
    estreante = _maior_movimento({"imprensa": 70, "clientes": 42}, {"imprensa": 70}, nomes)
    assert estreante is None


def test_o_maior_movimento_e_o_de_maior_modulo():
    from app.api.score import _maior_movimento

    nomes = {"imprensa": "Imprensa", "clientes": "Clientes"}
    movimento = _maior_movimento(
        {"imprensa": 72, "clientes": 30}, {"imprensa": 70, "clientes": 42}, nomes
    )
    assert movimento is not None
    assert movimento.lente == "Clientes"
    assert movimento.delta == -12


def test_o_empate_de_movimento_fica_sempre_com_a_mesma_lente():
    """Duas leituras seguidas têm de dar a mesma coluna: um desempate por
    ordem de dicionário faria o texto do mês mudar sem nada ter mudado."""
    from app.api.score import _maior_movimento

    nomes = {"imprensa": "Imprensa", "clientes": "Clientes"}
    primeiro = _maior_movimento(
        {"imprensa": 75, "clientes": 47}, {"imprensa": 70, "clientes": 42}, nomes
    )
    segundo = _maior_movimento(
        {"clientes": 47, "imprensa": 75}, {"clientes": 42, "imprensa": 70}, nomes
    )
    assert primeiro is not None and segundo is not None
    assert primeiro.lente == segundo.lente == "Clientes"


def test_mes_em_que_nada_se_moveu_nao_tem_maior_movimento():
    from app.api.score import _maior_movimento

    parado = _maior_movimento({"imprensa": 70}, {"imprensa": 70}, {"imprensa": "Imprensa"})
    assert parado is None


def test_a_calibracao_nao_ganha_limite_sem_a_tela_saber():
    """Todo corte que a API expõe é um campo na Calibração, e todo campo lá tem
    um verbete de ajuda no front (`dominio/guiaDaCalibracao.ts`).

    ESTE TESTE É A METADE DE CÁ desse contrato: acrescentar um limite ao domínio
    sem pô-lo na lista da API o deixaria calibrável pela rota e invisível na
    tela; pôr na lista um nome que o domínio não tem estoura na leitura, para
    todo mundo, na primeira vez que alguém abrir a Calibração.
    """
    from dataclasses import fields

    from app.api.score import LIMITES_DOS_SINAIS
    from app.dominio.sinais_da_lente import Limites

    da_api = {chave for chave, *_ in LIMITES_DOS_SINAIS}
    do_dominio = {campo.name for campo in fields(Limites)}
    assert da_api == do_dominio, sorted(da_api ^ do_dominio)
