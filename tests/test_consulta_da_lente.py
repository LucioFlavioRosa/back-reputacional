"""A Consulta em profundidade contra o Postgres: a rota, o banco e a nota da tela.

O DOMÍNIO JÁ PROVA A ÁRVORE com menções na mão (`test_consulta_profundidade`).
O que só o banco prova é a COSTURA: que a leitura das menções, a do agregado
(`score_mes_fonte`) e a da taxonomia chegam ao mesmo número que o resto do
produto já mostra. Se a Consulta disser −7,7 e o recorte do dossiê disser −7,6
para o mesmo mês, a diretoria vê dois números para a mesma pergunta — e deixa de
acreditar nos dois.

POR ISSO CADA TESTE COMPARA COM UMA FUNÇÃO QUE JÁ EXISTE, e não com um número
escrito aqui: a soma dos pilares com `impacto_do_recorte` sem filtro, o pilar
com o recorte pelo atributo, a nota com `medir_lentes` (a do dossiê).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.api.consulta_profundidade import obter_consulta
from app.banco import repositorio_score
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte, ScoreMesFonte
from app.dominio.erros import NaoEncontrado
from app.dominio.score import FiltroDeMencoes, peso_do_cargo, peso_do_engajamento
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: UM MÊS LONGE DE TUDO, para nenhuma semente do banco de teste entrar na conta.
MES = date(2031, 5, 1)
TEXTO_DO_MES = "2031-05"


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


@dataclass
class _QuemOlha:
    administra_dicionarios: bool = False
    ve_diretorio: bool = True


def _gravar(sessao, fonte_codigo: str, linhas: list[dict], mes: date = MES) -> None:
    """Grava as menções E o agregado do mês, como `ingerir_mencoes` faria.

    O AGREGADO É REFEITO DAS MESMAS LINHAS, no grão (sentimento, tier) de
    `score_mes_fonte`. É a condição de fechamento da Consulta: D vem dali, e os
    numeradores vêm da menção.
    """
    fonte = sessao.scalars(select(ScoreFonte).where(ScoreFonte.codigo == fonte_codigo)).one()
    grao: Counter[tuple[str, str]] = Counter()
    for linha in linhas:
        sessao.add(Mencao(fonte_id=fonte.id, mes=mes, **linha))
        grao[(linha["sentimento"], linha.get("tier") or "")] += 1
    for (sentimento, tier), quantas in grao.items():
        sessao.add(
            ScoreMesFonte(
                fonte_id=fonte.id,
                mes=mes,
                sentimento=sentimento,
                tier=tier,
                mencoes=quantas,
                soma_log=quantas * peso_do_engajamento(None),
                soma_engajamento=0,
                soma_cargo=quantas * peso_do_cargo(None),
            )
        )
    sessao.flush()


def _linhas_da_imprensa(sessao) -> list[dict]:
    """Os três jeitos de uma menção chegar à taxonomia, e um que não chega.

    - `tema_id` gravado (a ingestão nova faz isso pela Subcategoria);
    - só a Subcategoria em `tema_texto`, de uma carga antiga;
    - só o pilar no atributo, com o prefixo do export real;
    - nada que case: o nó "Sem pilar identificado".
    """
    atendimento = sessao.scalars(
        select(Tema).where(Tema.nome == "Atendimento ao cliente", Tema.ativo.is_(True))
    ).one()
    base = {"veiculo": "Folha", "unidade_texto": "Águas do Rio", "data": date(2031, 5, 12)}
    return [
        {**base, "sentimento": "neg", "tier": "muito_relevante", "tema_id": atendimento.id,
         "tema_texto": "Atendimento ao cliente",
         "atributo": "2. Eficiência Operacional e Qualidade"},
        {**base, "sentimento": "pos", "tier": "relevante", "tema_texto": "atendimento ao cliente"},
        {**base, "sentimento": "neu", "tier": "menos_relevante",
         "tema_texto": "Atendimento ao cliente"},
        {**base, "sentimento": "neg", "tier": "relevante", "tema_texto": "Obras",
         "atributo": "1. Governança"},
        {**base, "sentimento": "pos", "tier": "menos_relevante", "tema_texto": "Obras",
         "atributo": "Governança"},
        {**base, "sentimento": "neg", "tier": "menos_relevante", "tema_texto": "Qualquer",
         "atributo": "Nada que case", "data": date(2031, 5, 20)},
    ]


def _consulta(sessao, codigo: str = "imprensa", mes: str = TEXTO_DO_MES) -> dict:
    return obter_consulta(sessao=sessao, usuario=_QuemOlha(), codigo=codigo, mes=mes)


def _lente(sessao, codigo: str) -> Lente:
    return sessao.scalars(select(Lente).where(Lente.codigo == codigo)).one()


def test_os_pilares_somam_o_impacto_do_mes_inteiro_e_50_ns(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    saida = _consulta(sessao)
    conferencia = saida["meta"]["conferencia"]

    calibracao = repositorio_score.calibracao_vigente(sessao)
    lente = _lente(sessao, "imprensa")
    do_recorte = repositorio_score.impacto_do_recorte(sessao, lente.id, MES, calibracao)
    medida = repositorio_score.medir_uma_lente(sessao, lente, MES, calibracao)

    assert conferencia["fecha"] is True
    assert conferencia["somaPilares"] == pytest.approx(do_recorte, abs=1e-4)
    assert conferencia["somaPilares"] == pytest.approx(50 * medida.ns, abs=1e-4)
    pilares = saida["lentes"][0]["pilares"]
    assert round(sum(p["impacto"] for p in pilares), 1) == round(do_recorte, 1)
    assert conferencia["semVinculo"]["pilar"] == 1
    assert pilares[-1]["id"] == "sem-pilar"


def test_o_pilar_sem_divergencia_e_o_recorte_pelo_atributo(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    pilares = {p["id"]: p for p in _consulta(sessao)["lentes"][0]["pilares"]}

    calibracao = repositorio_score.calibracao_vigente(sessao)
    lente = _lente(sessao, "imprensa")
    # As duas menções de Governança vêm SÓ pelo atributo, uma com o prefixo do
    # export real e outra sem — e o filtro pelo nome limpo alcança as duas
    # grafias (é o rótulo que a aba N1 do painel mostra e o clique manda).
    governanca = repositorio_score.impacto_do_recorte(
        sessao, lente.id, MES, calibracao, FiltroDeMencoes(atributo="Governança")
    )
    assert pilares["governanca"]["impacto"] == round(governanca, 1)
    assert pilares["governanca"]["volume"] == 2
    assert "filhos" not in pilares["governanca"]  # só "sem tema": não abre


def test_os_quatro_niveis_abrem_pela_cadeia_do_cadastro(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    lente = _consulta(sessao)["lentes"][0]
    pilar = next(p for p in lente["pilares"] if p["id"] == "eficiencia_operacional_e_qualidade")
    assert pilar["volume"] == 3
    tema = pilar["filhos"][0]
    assert tema["nome"] != "Sem tema identificado" and "nivel3" in tema
    subtema = tema["filhos"][0]
    assert subtema["id"] == "atendimento_ao_cliente"
    assert len(subtema["nivel4"]["porDia"]["total"]) == 31
    assert {i["sentimento"] for i in subtema["nivel4"]["itens"]} == {
        "positivo", "neutro", "negativo"
    }
    assert lente["drill"] is True
    assert [c["tipo"] for c in lente["cartoesLaterais"]] == ["oQueMudou", "historia"]


def test_a_nota_e_a_do_dossie(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    lente = _consulta(sessao)["lentes"][0]
    calibracao = repositorio_score.calibracao_vigente(sessao)
    do_dossie = next(
        m for m in repositorio_score.medir_lentes(sessao, MES, calibracao)
        if m.codigo == "imprensa"
    )
    assert lente["nota"] == do_dossie.score
    assert lente["serie"][-1] == do_dossie.score
    assert lente["totalPonderado"] == pytest.approx(10 + 5 + 1 + 5 + 1 + 1)


def test_o_mercado_responde_sem_drill(sessao):
    _gravar(
        sessao,
        "clipei_investidores",
        [
            {"sentimento": "pos", "tier": "muito_relevante", "veiculo": "Valor",
             "tema_texto": "Tarifa"},
            {"sentimento": "neg", "tier": "relevante", "veiculo": "Valor",
             "atributo": "3. Crescimento e Solidez Financeira"},
        ],
    )
    saida = _consulta(sessao, "mercado")
    lente = saida["lentes"][0]
    assert lente["id"] == "mercado" and lente["drill"] is False
    assert saida["meta"]["conferencia"]["fecha"] is True
    assert round(sum(p["impacto"] for p in lente["pilares"]), 1) == round(50 * (10 - 5) / 15, 1)
    assert [c["tipo"] for c in lente["cartoesLaterais"]] == ["oQueMudou", "divergentes"]


def test_lente_fora_da_consulta_e_404(sessao):
    with pytest.raises(NaoEncontrado):
        _consulta(sessao, "sociedade")
    with pytest.raises(NaoEncontrado):
        _consulta(sessao, "nao-existe")


def test_mes_sem_dado_volta_vazio_sem_erro(sessao):
    saida = _consulta(sessao, "imprensa", "2031-02")
    lente = saida["lentes"][0]
    assert saida["meta"]["vazio"] is True
    assert lente["pilares"] == [] and lente["cartoesLaterais"] == []
    assert lente["volumeTotal"] == 0 and lente["nota"] is None


def test_o_mes_anterior_agrupado_no_banco_da_o_mesmo_impacto_do_recorte(sessao):
    """Os cinco meses antes do da tela vêm de um GROUP BY, e não linha a linha:
    o pilar de abril tem de ser o mesmo que o recorte de abril pelo atributo."""
    abril = date(2031, 4, 1)
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao), mes=abril)
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    pilares = {p["id"]: p for p in _consulta(sessao)["lentes"][0]["pilares"]}

    calibracao = repositorio_score.calibracao_vigente(sessao)
    lente = _lente(sessao, "imprensa")
    governanca_em_abril = repositorio_score.impacto_do_recorte(
        sessao, lente.id, abril, calibracao, FiltroDeMencoes(atributo="Governança")
    )
    assert pilares["governanca"]["impactoMesAnterior"] == round(governanca_em_abril, 1)
    tema = next(
        t for t in pilares["eficiencia_operacional_e_qualidade"]["filhos"]
        if not t["id"].startswith("sem-")
    )
    evolucao = pilares["eficiencia_operacional_e_qualidade"]["nivel2"]["destaque"]["evolucao"]
    assert evolucao["volumes"][-2] == tema["volume"]  # o mesmo mês, agrupado
    assert evolucao["impactos"][-2] == tema["impactoMesAnterior"]


# -- pelo HTTP: a rota registrada, a permissão do portal e o 422 ----------------------


@pytest.fixture
def cliente(sessao):
    from main import app
    from tests.test_score_api import _cliente

    try:
        yield lambda perfil: _cliente(sessao, perfil)
    finally:
        app.dependency_overrides.clear()


def test_pelo_http_a_consulta_responde_comprimida_a_quem_tem_o_score(sessao, cliente):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    resposta = cliente("plataforma_edicao").get(
        f"/api/score/lentes/imprensa/consulta?mes={TEXTO_DO_MES}",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["meta"]["versao"] == "api-1"
    assert resposta.headers.get("content-encoding") == "gzip"


def test_pelo_http_quem_nao_tem_o_portal_do_score_nao_le_a_consulta(cliente):
    resposta = cliente("crm_edicao").get(
        f"/api/score/lentes/imprensa/consulta?mes={TEXTO_DO_MES}"
    )
    assert resposta.status_code == 403


@pytest.mark.parametrize("mes", ["2026-13", "abc", "0001-02", "1-1", "99999-01"])
def test_pelo_http_mes_invalido_e_422_e_nunca_500(cliente, mes):
    resposta = cliente("plataforma_edicao").get(f"/api/score/lentes/imprensa/consulta?mes={mes}")
    assert resposta.status_code == 422


def test_pelo_http_lente_fora_da_consulta_e_404(cliente):
    resposta = cliente("plataforma_edicao").get(
        f"/api/score/lentes/sociedade/consulta?mes={TEXTO_DO_MES}"
    )
    assert resposta.status_code == 404


# -- o painel de aprofundamento da Imprensa: N1 › N2 › N3 -----------------------


def _recorte(sessao, codigo: str = "imprensa", **filtro):
    from app.api.lentes import obter_recorte

    parametros = dict(
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        sentimento=None,
    )
    parametros.update(filtro)
    return obter_recorte(
        sessao=sessao, usuario=_QuemOlha(), codigo=codigo, mes=TEXTO_DO_MES, **parametros
    )


def test_o_painel_da_imprensa_desce_pela_taxonomia_n1_n2_n3(sessao):
    """Por pedido do dono do produto: as abas do painel são os 7 atributos (N1),
    os temas estratégicos (N2) e os subtemas (N3) — nessa ordem."""
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    recorte = _recorte(sessao)
    assert [bloco.titulo for bloco in recorte.dentro] == [
        "N1 Atributo Reputacional",
        "N2 Temas estratégicos",
        "N3 Subtemas",
    ]
    n1, n2, n3 = recorte.dentro
    # O ATRIBUTO SEM O PREFIXO "1. ": as duas grafias de Governança viram uma pílula.
    rotulos = {linha["rotulo"]: linha for linha in n1.dados}
    assert "Governança" in rotulos and "1. Governança" not in rotulos
    assert rotulos["Governança"]["negativo"] == 1 and rotulos["Governança"]["positivo"] == 1
    # N2 e N3 pelo vínculo com o cadastro: só a menção com tema_id entra.
    assert [linha["rotulo"] for linha in n3.dados] == ["Atendimento ao cliente"]
    assert len(n2.dados) == 1
    assert n1.recorta == "atributo" and n2.recorta == "tema_n2" and n3.recorta == "tema_n3"


def test_o_painel_do_mercado_tambem_desce_pela_taxonomia_n1_n2_n3(sessao):
    """O MERCADO ENTROU AQUI (20/10/2026, por pedido de paridade visual com a
    Imprensa): mesma Clipei, mesmas colunas, só a fonte muda
    (`clipei_investidores`) — ver `DIMENSOES_DO_APROFUNDAMENTO` em
    `causa_da_lente.py`."""
    _gravar(sessao, "clipei_investidores", _linhas_da_imprensa(sessao))
    recorte = _recorte(sessao, codigo="mercado")
    assert [bloco.titulo for bloco in recorte.dentro] == [
        "N1 Atributo Reputacional",
        "N2 Temas estratégicos",
        "N3 Subtemas",
    ]
    n1, n2, n3 = recorte.dentro
    assert n1.recorta == "atributo" and n2.recorta == "tema_n2" and n3.recorta == "tema_n3"


def test_o_painel_da_institucional_tambem_desce_pela_taxonomia_n1_n2_n3(sessao):
    """A INSTITUCIONAL ENTROU AQUI (20/10/2026, no mesmo pedido do Mercado):
    desde a 0111/0112 ela também é a Clipei, só recortada pela subcategoria
    "Institucional" em vez de "Investidores" — ver `DIMENSOES_DO_APROFUNDAMENTO`
    em `causa_da_lente.py`."""
    _gravar(sessao, "clipei_institucional", _linhas_da_imprensa(sessao))
    recorte = _recorte(sessao, codigo="institucional")
    assert [bloco.titulo for bloco in recorte.dentro] == [
        "N1 Atributo Reputacional",
        "N2 Temas estratégicos",
        "N3 Subtemas",
    ]
    n1, n2, n3 = recorte.dentro
    assert n1.recorta == "atributo" and n2.recorta == "tema_n2" and n3.recorta == "tema_n3"


def test_a_ficha_da_aba_n2_conta_exatamente_o_que_as_barras_somam(sessao):
    """A aba não pode dizer "vem em X menções" e desenhar menos que X.

    `tema_n2` chega ao pilar ATRAVESSANDO `MacroTema`, e `Tema.macro_tema_id` é
    nulável — há 45 temas órfãos em 149 no cadastro, que a reconciliação da
    `0058` deixou para trás por casar só pelo nome exato. Antes desta correção a
    presença vinha de `count(tema_id)`, que conta a menção do órfão, enquanto o
    join a excluía das barras.

    É EXATAMENTE O QUE A FICHA EXISTE PARA IMPEDIR — "quanto falta vai escrito, e
    é o que impede a aba de mentir por omissão" — e era ela mentindo.

    O TESTE AFIRMA A INVARIANTE, não um número: a presença da aba tem de bater
    com a soma das barras dela. Um número escrito aqui envelheceria com a
    semente; a invariante não.

    E A ABA N3 CONTINUA CONTANDO O ÓRFÃO, que é o certo: um subtema sem pilar
    ainda é um subtema.
    """
    from app.banco import repositorio_lentes
    from app.dominio.causa_da_lente import dimensoes_do_aprofundamento

    orfao = Tema(nome="Tema sem pilar nenhum", nivel="estrategico", macro_tema_id=None)
    sessao.add(orfao)
    sessao.flush()
    assert orfao.macro_tema_id is None, "o teste precisa de um tema SEM pilar"

    linhas = _linhas_da_imprensa(sessao)
    linhas.append({
        "veiculo": "Folha", "unidade_texto": "Águas do Rio", "data": date(2031, 5, 12),
        "sentimento": "neg", "tier": "relevante", "tema_id": orfao.id,
        "tema_texto": orfao.nome, "atributo": "1. Governança",
    })
    _gravar(sessao, "clipei", linhas)

    lente = _lente(sessao, "imprensa")
    cortes = repositorio_lentes.cortes_da_causa(
        sessao,
        "imprensa",
        lente.id,
        MES,
        repositorio_score.calibracao_vigente(sessao),
        dimensoes=dimensoes_do_aprofundamento("imprensa"),
    )
    por_chave = {corte.dimensao.chave: corte for corte in cortes}

    def soma_das_barras(corte) -> int:
        return sum(
            linha["positivo"] + linha["neutro"] + linha["negativo"] for linha in corte.linhas
        )

    n2, n3 = por_chave["tema_n2"], por_chave["tema_n3"]
    assert n2.presenca.preenchidas == soma_das_barras(n2)
    assert n3.presenca.preenchidas == soma_das_barras(n3)

    #: E O ÓRFÃO ESTÁ DE FATO NO MÊS, senão a invariante acima passaria por não
    #: haver o caso: ele aparece no N3 e não no N2.
    assert orfao.nome in [linha["rotulo"] for linha in n3.linhas]
    assert orfao.nome not in [linha["rotulo"] for linha in n2.linhas]
    assert n3.presenca.preenchidas == n2.presenca.preenchidas + 1


def test_o_filtro_do_atributo_alcanca_a_grafia_CRUA_do_export(sessao):
    """O valor com prefixo ("1. Governança") vem de link antigo e do mock.

    `ATRIBUTO_SEM_PREFIXO` fez a aba N1 agrupar pelo nome limpo, e o filtro
    passou a aceitar os dois por um `or_`. Mas o teste que exercitava a grafia
    crua foi substituído por um que usa só a limpa — e a suíte INTEIRA (2187)
    passava com o lado cru do `or_` removido, provado por mutação em 16/10/2026.

    Sem esta guarda, um link guardado nos favoritos passa a devolver vazio em
    silêncio: nenhum erro, nenhuma menção.
    """
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    lente = _lente(sessao, "imprensa")
    calibracao = repositorio_score.calibracao_vigente(sessao)

    pelo_cru = repositorio_score.impacto_do_recorte(
        sessao, lente.id, MES, calibracao, FiltroDeMencoes(atributo="1. Governança")
    )
    pelo_limpo = repositorio_score.impacto_do_recorte(
        sessao, lente.id, MES, calibracao, FiltroDeMencoes(atributo="Governança")
    )

    #: ESTA É A GUARDA: com o lado cru do `or_` removido, "1. Governança" só
    #: casaria contra o valor JÁ LIMPO, que nunca traz o prefixo — zero menções,
    #: impacto zero.
    assert pelo_cru != 0, "a grafia crua do export deixou de alcançar a menção"

    #: E OS DOIS NÃO SÃO O MESMO NÚMERO: o limpo alcança também a menção
    #: POSITIVA sem prefixo, e as duas se cancelam em parte — por isso o
    #: impacto dele é MENOR em módulo.
    #:
    #: ESTA LINHA AFIRMAVA O CONTRÁRIO ("mais menções, mais impacto") e o teste
    #: caiu na primeira execução. Mais menções não é mais impacto quando os
    #: sentimentos se opõem; a conta certa veio da medição, não da intuição.
    assert abs(pelo_limpo) < abs(pelo_cru), "o nome limpo tem de alcançar as duas grafias"


def test_um_atributo_que_COMECA_com_digito_nao_e_mutilado(sessao):
    """"5G e cobertura" tem de chegar inteiro à aba N1.

    `ATRIBUTO_SEM_PREFIXO` existe para tirar o "7. " do export real. O padrão
    era `^[0-9]+[.)-]?\\s*` — com o `?`, a pontuação era OPCIONAL, e aí o
    dígito sozinho bastava para comer o começo do valor:

        "5G e cobertura"     -> "G e cobertura"
        "2024 Resultados"    -> "Resultados"
        "2 Ruas sem asfalto" -> "Ruas sem asfalto"

    Dois atributos diferentes podiam cair na MESMA pílula da aba, e a barra
    contaria os dois como um só. Os 7 atributos do cadastro usam ". " e nenhum
    disparava o defeito — ele esperava o primeiro valor com dígito sem
    pontuação.

    O TESTE PASSA PELA ABA, e não só pela função: é a aba que agrupa, e era lá
    que a fusão apareceria.
    """
    from app.banco import repositorio_lentes
    from app.dominio.causa_da_lente import dimensoes_do_aprofundamento

    base = {"veiculo": "Folha", "unidade_texto": "Águas do Rio", "data": date(2031, 5, 12)}
    _gravar(sessao, "clipei", [
        {**base, "sentimento": "neg", "tier": "relevante", "atributo": "5G e cobertura"},
        {**base, "sentimento": "pos", "tier": "relevante", "atributo": "G e cobertura"},
        {**base, "sentimento": "neu", "tier": "relevante", "atributo": "1. Governança"},
    ])

    lente = _lente(sessao, "imprensa")
    cortes = repositorio_lentes.cortes_da_causa(
        sessao,
        "imprensa",
        lente.id,
        MES,
        repositorio_score.calibracao_vigente(sessao),
        dimensoes=dimensoes_do_aprofundamento("imprensa"),
    )
    n1 = next(corte for corte in cortes if corte.dimensao.chave == "atributo")
    rotulos = {linha["rotulo"]: linha for linha in n1.linhas}

    #: OS DOIS VALORES SÃO DISTINTOS e continuam distintos na aba. Com o `?`,
    #: "5G e cobertura" virava "G e cobertura" e os dois fundiam numa pílula com
    #: um positivo e um negativo.
    assert "5G e cobertura" in rotulos, "o dígito do começo foi comido"
    assert "G e cobertura" in rotulos
    assert rotulos["5G e cobertura"]["negativo"] == 1
    assert rotulos["5G e cobertura"]["positivo"] == 0
    assert rotulos["G e cobertura"]["positivo"] == 1

    #: E O PREFIXO DE VERDADE CONTINUA SAINDO, que é a razão de a função existir.
    assert "Governança" in rotulos and "1. Governança" not in rotulos


def test_escolher_um_atributo_tira_a_aba_n1_e_a_trilha_o_nomeia(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    recorte = _recorte(sessao, atributo="Governança")
    assert [bloco.titulo for bloco in recorte.dentro] == ["N2 Temas estratégicos", "N3 Subtemas"]
    assert recorte.trilha[0].dimensao == "N1 Atributo Reputacional"
    assert recorte.trilha[0].valor == "Governança"
    # O filtro pelo nome limpo alcança as duas grafias: as duas menções de Governança.
    assert recorte.itens == 2


def _explorador(sessao, **filtro):
    from app.api.lentes import obter_explorador

    parametros = dict(
        tier=None, veiculo=None, atributo=None, tema=None, perfil_autor=None, uf=None,
        subtema=None, autor=None, empresa=None, tema_n1=None, tema_n2=None, tema_n3=None,
        sentimento=None,
    )
    parametros.update(filtro)
    return obter_explorador(
        sessao=sessao, usuario=_QuemOlha(), codigo="imprensa", mes=TEXTO_DO_MES, **parametros
    )


def test_o_explorador_fecha_com_o_impacto_do_mes_e_o_denominador(sessao):
    """Os gráficos N1 › N2 › N3 e o mapa somam estes grupos na tela: a soma dos
    pesos tem de ser o denominador do mês, e o saldo, o impacto do mês inteiro."""
    linhas = _linhas_da_imprensa(sessao)
    for linha, uf in zip(linhas, ["RJ", "RJ", "SP", "SP", None, "MT"], strict=True):
        linha["uf"] = uf
    _gravar(sessao, "clipei", linhas)
    saida = _explorador(sessao)
    lente = _lente(sessao, "imprensa")
    calibracao = repositorio_score.calibracao_vigente(sessao)

    pesos = sum(g.peso_positivo + g.peso_neutro + g.peso_negativo for g in saida.grupos)
    assert pesos == pytest.approx(saida.denominador)
    saldo = 50 * sum(g.peso_positivo - g.peso_negativo for g in saida.grupos) / saida.denominador
    assert saldo == pytest.approx(
        repositorio_score.impacto_do_recorte(sessao, lente.id, MES, calibracao)
    )
    assert sum(g.positivo + g.neutro + g.negativo for g in saida.grupos) == len(linhas)

    # N1 SEM O PREFIXO, como no popup; N2/N3 pelo vínculo do cadastro; UF crua.
    por_n1 = Counter()
    for g in saida.grupos:
        por_n1[g.n1] += g.positivo + g.neutro + g.negativo
    assert por_n1["Governança"] == 2 and "1. Governança" not in por_n1
    com_n3 = [g for g in saida.grupos if g.n3]
    assert [g.n3 for g in com_n3] == ["Atendimento ao cliente"] and com_n3[0].n2
    assert {g.uf for g in saida.grupos} == {"RJ", "SP", "MT", None}


def test_o_explorador_devolve_a_UF_em_SIGLA_mesmo_gravada_pelo_NOME(sessao):
    """O TERMÔMETRO POR UF FICAVA VAZIO com a base reimportada (21/10/2026).

    `mencao.uf` guarda o NOME do estado desde 09/10/2026 ("Rio de Janeiro"), e o
    mapa e a lista da tela procuram a SIGLA. O explorador converte; o estado
    estrangeiro, que não tem sigla, continua com o nome do fornecedor.
    """
    linhas = _linhas_da_imprensa(sessao)
    nomes = ["Rio de Janeiro", "Rio de Janeiro", "São Paulo", "SP", "Comunidade de Madrid", None]
    for linha, uf in zip(linhas, nomes, strict=True):
        linha["uf"] = uf
    _gravar(sessao, "clipei", linhas)

    saida = _explorador(sessao)

    assert {g.uf for g in saida.grupos} == {"RJ", "SP", "Comunidade de Madrid", None}


def test_a_LINHA_DO_MAPA_e_o_clique_nela_contam_O_MESMO(sessao):
    """A LIÇÃO DA `0098`, agora na UF — e o mapa já estava exposto a ela.

    A lista do Termômetro por UF mostra a SIGLA, derivada de `mencao.uf`, que
    guarda o NOME desde 09/10/2026. O recorte compara o valor recebido com a
    coluna: mandar "SP" sobre uma coluna que diz "São Paulo" não acharia nada —
    barra cheia, modal VAZIO. É o que faltava para o clique no estado abrir o
    mesmo recorte que a linha mostra.

    AS DUAS FORMAS CONVIVEM NA MESMA UF de propósito ("São Paulo" e "SP"), que é
    o caso em que casar só uma delas conta MENOS que a linha clicada. E a
    verificação é por linha, não só na que interessa: estado estrangeiro
    ("Comunidade de Madrid", sem sigla) tem de continuar fechando pelo texto.
    """
    linhas = _linhas_da_imprensa(sessao)
    nomes = ["Rio de Janeiro", "Rio de Janeiro", "São Paulo", "SP", "Comunidade de Madrid", None]
    for linha, uf in zip(linhas, nomes, strict=True):
        linha["uf"] = uf
    _gravar(sessao, "clipei", linhas)
    lente = _lente(sessao, "imprensa")
    calibracao = repositorio_score.calibracao_vigente(sessao)

    da_linha = Counter()
    for grupo in _explorador(sessao).grupos:
        if grupo.uf:
            da_linha[grupo.uf] += grupo.positivo + grupo.neutro + grupo.negativo
    assert da_linha == Counter({"RJ": 2, "SP": 2, "Comunidade de Madrid": 1})

    for uf, quantas in da_linha.items():
        #: O MESMO `where` DA LEITURA, menos a UF: é o clique na linha.
        do_clique = sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .where(
                ScoreFonte.lente_id == lente.id,
                Mencao.mes == MES,
                *repositorio_score.so_fontes_ligadas(calibracao),
                *repositorio_score.condicoes_do_filtro(FiltroDeMencoes(uf=uf)),
            )
        )
        assert do_clique == quantas, (
            f"a linha {uf!r} conta {quantas} e o clique nela alcança {do_clique}"
        )


def test_o_recorte_por_uf_nao_pega_estado_vizinho(sessao):
    """O conjunto de formas não pode virar peneira larga.

    `para_uf` e `para_sigla` traduzem UMA UF; se alguma delas devolvesse valor
    de outro estado — ou o conjunto entrasse vazio e virasse `in_()` sem termo —
    o recorte por "SP" passaria a contar o Rio junto.
    """
    linhas = _linhas_da_imprensa(sessao)
    for linha, uf in zip(
        linhas, ["Rio de Janeiro", "SP", "SP", "SP", "SP", "SP"], strict=True
    ):
        linha["uf"] = uf
    _gravar(sessao, "clipei", linhas)
    lente = _lente(sessao, "imprensa")

    def quantas(valor: str) -> int:
        return sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .where(
                ScoreFonte.lente_id == lente.id,
                Mencao.mes == MES,
                *repositorio_score.condicoes_do_filtro(FiltroDeMencoes(uf=valor)),
            )
        )

    assert quantas("SP") == 5
    #: PELAS DUAS PONTAS: o nome acha a linha gravada em sigla, e a sigla acha a
    #: gravada pelo nome — é o que a barra de filtros da tela manda (ela oferece
    #: os valores crus da coluna) e o que o mapa manda.
    assert quantas("São Paulo") == 5
    assert quantas("Rio de Janeiro") == 1
    assert quantas("RJ") == 1


def test_o_explorador_segue_o_filtro_da_tela(sessao):
    _gravar(sessao, "clipei", _linhas_da_imprensa(sessao))
    saida = _explorador(sessao, sentimento="neg")
    assert sum(g.negativo for g in saida.grupos) == 3
    assert all(g.positivo == 0 and g.neutro == 0 for g in saida.grupos)
