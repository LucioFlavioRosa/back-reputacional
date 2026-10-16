"""A Approach passa a ler link, texto, autor e subtema — e os apelidos de grafia.

O QUE ESTES TESTES PROTEGEM:

* as quatro colunas que o arquivo real trazia cheias e o cadastro ignorava
  (`Link` e `Conteúdo` nas duas abas, `Tags (subtema)` na SL, `Publicador` na
  CM) chegam ao banco;
* **a subida de hoje não pode piorar**: coluna de enriquecimento ausente não
  derruba o mês. "Mapeada é exigida" é o padrão, e passar a exigir `Link`
  trocaria 17.039 menções por uma recusa no dia em que a agência renomear uma
  coluna;
* `Publicador` da CM vira `autor` e NÃO `veiculo`: ninguém cria instituição no
  Cadastro compartilhado para cada pessoa que comenta num post da Aegea;
* os apelidos juntam SÓ grafias da mesma coisa — a verificação é derivada do
  próprio cadastro, não de uma lista escrita à mão aqui;
* `subtema` é o nível abaixo de `tema` no vocabulário do fornecedor. É a
  primeira fonte a mapeá-lo, e apontá-lo para outro nível agruparia as menções
  errado sem nada acusar.

AS DUAS ABAS EM TODA PLANILHA DE TESTE, de propósito: `approach_sl` e
`approach_cm` declaram o mesmo `arquivo`, então `ingerir` sobe as duas na mesma
transação. Uma planilha com uma aba só seria recusada pela fonte irmã — e é
esse acoplamento que o teste tem de exercitar, não evitar.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte
from app.casos_de_uso import ingerir_mencoes
from app.dominio.ingestao_score import CAMPOS_OBRIGATORIOS, Mapeamento, achatar
from tests.test_e2e_postgres import MIGRATIONS, URL

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


@pytest.fixture
def fontes(sessao) -> dict[str, ScoreFonte]:
    achadas = {
        fonte.codigo: fonte
        for fonte in sessao.scalars(
            select(ScoreFonte).where(ScoreFonte.codigo.in_(("approach_sl", "approach_cm")))
        )
    }
    assert set(achadas) == {"approach_sl", "approach_cm"}
    return achadas


#: O CABEÇALHO REAL da aba SL, na ordem do arquivo de 01-08/2026.
CABECALHO_SL = [
    "Mês", "Ano", "Data", "Autor", "Rede", "Cidade", "Estado", "Sentimento",
    "Concessionárias", "Publicador", "Link", "Conteúdo", "Reações",
    "Compartilham.", "Comentários", "Engajamento", "Atributo", "Tags (tema)",
    "Tags (subtema)", "Holding",
]
#: O CABEÇALHO REAL da aba CM.
CABECALHO_CM = [
    "Mês", "Ano", "Data", "Rede", "Publicador", "Link", "Conteúdo", "Sentimento",
    "Concessionárias", "TAG (motivo)", "TAG (assunto 1)", "Tags (assunto 2)",
    "Tags (assunto 3)", "Tags (assunto 4)", "Reações", "Compartilhamento",
    "Comentários", "Interações",
]
#: O NÚCLEO que a planilha é OBRIGADA a trazer. Fora dele, toda coluna mapeada
#: é enriquecimento e tem de poder faltar — ver
#: `test_toda_coluna_de_enriquecimento_pode_faltar_no_arquivo`.
NUCLEO = {"data", "sentimento", "tema", "unidade", "engajamento", "teor"}

LINHA_SL = {
    "Mês": "Janeiro", "Ano": 2026, "Data": date(2026, 8, 3), "Rede": "Instagram",
    "Sentimento": "Negativo", "Concessionárias": "Aegea - Corsan",
    "Link": "https://instagram.com/p/XYZ", "Conteúdo": "A obra parou de novo",
    "Reações": 3, "Engajamento": 7, "Tags (tema)": "2 - Aegea - Obra",
    "Tags (subtema)": "Aegea - Manutencao Operacional",
}
LINHA_CM = {
    "Mês": "Janeiro", "Ano": 2026, "Data": date(2026, 8, 4), "Rede": "instagram",
    "Publicador": "branca_medeiros15", "Link": "https://instagram.com/p/ABC/c/1",
    "Conteúdo": "Vocês deveriam ter vergonha", "Sentimento": "Negativo",
    "Concessionárias": "Águas do Rio", "TAG (motivo)": "1 , Reclamação",
    "TAG (assunto 1)": "2 , Aegea , Falta de Água", "Interações": 2,
}


def _aba(livro, nome: str, cabecalho: list[str], linhas: list[dict], faixa: bool) -> None:
    aba = livro.create_sheet(nome)
    #: A FAIXA DE ANOTAÇÃO ACIMA DO CABEÇALHO, como o arquivo real: na aba SL a
    #: agência escreve "Buzzmonitor, verificar" e "o que é?" na linha 1, e o
    #: cabeçalho fica na linha 2. `_achar_o_cabecalho` tem de atravessá-la.
    if faixa:
        aba.append([None, None, None, "Buzzmonitor, verificar"])
    aba.append(cabecalho)
    for linha in linhas:
        aba.append([linha.get(coluna) for coluna in cabecalho])


def _planilha(
    sl: list[dict],
    cm: list[dict],
    cabecalho_sl: list[str] | None = None,
    cabecalho_cm: list[str] | None = None,
) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    livro.remove(livro.active)
    _aba(livro, "SL", cabecalho_sl or CABECALHO_SL, sl, faixa=True)
    _aba(livro, "CM", cabecalho_cm or CABECALHO_CM, cm, faixa=False)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _subir(sessao, fontes, sl, cm):
    """Sobe pelas duas irmãs e devolve o resumo por código de fonte."""
    resumos = ingerir_mencoes.ingerir(sessao, fontes["approach_sl"], _planilha(sl, cm))
    por_codigo = {resumo.fonte: resumo for resumo in resumos}
    assert len(resumos) == 2, f"um arquivo, duas fontes; vieram {list(por_codigo)}"
    return por_codigo


def _gravada(sessao, fonte: ScoreFonte, mes: date) -> Mencao:
    achada = sessao.scalar(
        select(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes == mes)
    )
    assert achada is not None, f"nada gravado para {fonte.codigo} em {mes}"
    return achada


def test_o_social_listening_le_link_texto_e_subtema(sessao, fontes):
    _subir(sessao, fontes, [LINHA_SL], [LINHA_CM])

    gravada = _gravada(sessao, fontes["approach_sl"], date(2026, 8, 1))
    assert gravada.link == "https://instagram.com/p/XYZ"
    assert gravada.titulo_texto == "A obra parou de novo"
    #: SEM O PREFIXO DE TAXONOMIA: a célula vem "Aegea - Manutencao
    #: Operacional", e o `Aegea -` é marca, não assunto.
    assert gravada.subtema == "Manutencao Operacional"
    #: E o tema continua vindo do N3 do fornecedor, como antes.
    assert gravada.tema_texto == "Obra"


def test_o_community_management_le_link_texto_e_autor(sessao, fontes):
    _subir(sessao, fontes, [LINHA_SL], [LINHA_CM])

    gravada = _gravada(sessao, fontes["approach_cm"], date(2026, 8, 1))
    assert gravada.link == "https://instagram.com/p/ABC/c/1"
    assert gravada.titulo_texto == "Vocês deveriam ter vergonha"
    assert gravada.autor == "branca_medeiros15"
    assert gravada.teor == "Reclamação"


def test_o_publicador_da_cm_nao_vira_cadastro_de_quem_falou(sessao, fontes):
    """4.725 perfis de pessoas que comentaram NÃO entram no Cadastro.

    `autor` é texto; `veiculo` é "quem falou" e procura/cria instituição. Se o
    `Publicador` fosse mapeado para `veiculo`, a conferência proporia criar uma
    instituição por pessoa que comenta num post da Aegea.
    """
    arquivo = _planilha([LINHA_SL], [LINHA_CM])

    propostos = ingerir_mencoes.veiculos_da_planilha(sessao, fontes["approach_cm"], arquivo)

    assert propostos == {}, f"a CM propôs criar quem falou: {propostos}"
    _subir(sessao, fontes, [LINHA_SL], [LINHA_CM])
    assert _gravada(sessao, fontes["approach_cm"], date(2026, 8, 1)).veiculo is None


def test_toda_coluna_de_enriquecimento_pode_faltar_no_arquivo(sessao, fontes):
    """O cadastro só pode EXIGIR o núcleo. Derivado do mapeamento, não de lista.

    Sem esta garantia, acrescentar uma coluna de enriquecimento ao cadastro
    passa a poder DERRUBAR um mês que hoje sobe — o oposto do que a mudança
    existe para fazer.
    """
    for codigo, fonte in fontes.items():
        mapeamento = Mapeamento.de_json(fonte.mapeamento_colunas)
        enriquecimento = set(mapeamento.colunas) - NUCLEO
        exigidas_demais = sorted(enriquecimento - set(mapeamento.colunas_opcionais))
        assert not exigidas_demais, (
            f"{codigo} exige {exigidas_demais}, que é enriquecimento. "
            "Declare em `colunas_opcionais` (ver a 0064 e a 0091)."
        )
        #: E o núcleo continua exigido: `colunas_opcionais` não pode afrouxar
        #: o que faz a menção existir.
        assert CAMPOS_OBRIGATORIOS.isdisjoint(mapeamento.colunas_opcionais)


def test_a_planilha_sem_as_colunas_novas_sobe_igual(sessao, fontes):
    """O arquivo de ANTES desta mudança, sem Link, Conteúdo, subtema e Publicador."""
    sem_novas_sl = [c for c in CABECALHO_SL if c not in ("Link", "Conteúdo", "Tags (subtema)")]
    sem_novas_cm = [c for c in CABECALHO_CM if c not in ("Link", "Conteúdo", "Publicador")]

    resumos = ingerir_mencoes.ingerir(
        sessao,
        fontes["approach_sl"],
        _planilha([LINHA_SL], [LINHA_CM], sem_novas_sl, sem_novas_cm),
    )

    assert sorted(resumo.ingeridas for resumo in resumos) == [1, 1]
    gravada = _gravada(sessao, fontes["approach_sl"], date(2026, 8, 1))
    assert gravada.link is None and gravada.titulo_texto is None and gravada.subtema is None
    da_cm = _gravada(sessao, fontes["approach_cm"], date(2026, 8, 1))
    assert da_cm.autor is None
    #: O QUE IMPORTA: a menção entrou. O enriquecimento falta, o mês não.
    assert gravada.sentimento == "neg" and da_cm.sentimento == "neg"


#: OS SETE APELIDOS, com o CAMPO em que cada um tem de cair.
#:
#: O CAMPO IMPORTA, e esta lista nasceu sem ele: a primeira versão deste teste
#: conferia se a forma canônica aparecia na UNIÃO de `unidade_texto`,
#: `tema_texto` e `subtema` — então um apelido que convergisse a grafia no campo
#: ERRADO passava. `apelidos` é um dicionário plano aplicado aos quatro campos
#: que passam por `_rotulo`, e é exatamente esse espalhamento que o teste tem de
#: vigiar. Achado da revisão.
APELIDOS = [
    ("SL", "Concessionárias", "unidade_texto", "Águas do Para", "Águas do Pará"),
    ("SL", "Tags (tema)", "tema_texto", "Premios", "Prêmios"),
    ("SL", "Tags (subtema)", "subtema", "Gestao de Residuos", "Gestão de Resíduos"),
    ("SL", "Tags (subtema)", "subtema", "Seguranca no Trabalho", "Segurança no Trabalho"),
    ("SL", "Tags (subtema)", "subtema", "Pescando Tradicoes", "Pescando Tradições"),
    ("CM", "Concessionárias", "unidade_texto", "Águas do Para", "Águas do Pará"),
    ("CM", "TAG (assunto 1)", "tema_texto", "Reclamação de Serviços", "Reclamação de serviços"),
]


@pytest.mark.parametrize(("aba", "coluna", "campo", "torta", "canonica"), APELIDOS)
def test_o_apelido_junta_as_duas_grafias(sessao, fontes, aba, coluna, campo, torta, canonica):
    """Medido no arquivo real: a grafia sem acento virava uma segunda barra."""
    sl = dict(LINHA_SL)
    cm = dict(LINHA_CM)
    (sl if aba == "SL" else cm)[coluna] = torta

    _subir(sessao, fontes, [sl], [cm])

    fonte = fontes["approach_sl" if aba == "SL" else "approach_cm"]
    gravada = _gravada(sessao, fonte, date(2026, 8, 1))
    assert getattr(gravada, campo) == canonica, (
        f"{torta!r} devia virar {canonica!r} em `{campo}`; "
        f"gravou {getattr(gravada, campo)!r}"
    )


def test_todo_apelido_do_cadastro_esta_exercitado(fontes):
    """A lista de cima não pode ficar atrás do cadastro.

    Dois dos sete apelidos não tinham caso quando este arquivo nasceu, e foi a
    revisão que contou. Derivar a conferência do cadastro é o que impede o
    próximo apelido de entrar sem ninguém provar que ele funciona.
    """
    exercitados = {(aba, torta) for aba, _, _, torta, _ in APELIDOS}
    for codigo, fonte in fontes.items():
        aba = "SL" if codigo.endswith("_sl") else "CM"
        for de in Mapeamento.de_json(fonte.mapeamento_colunas).apelidos:
            assert (aba, de) in exercitados, (
                f"o apelido {de!r} da {codigo} não tem caso em `APELIDOS`."
            )


def test_o_apelido_so_junta_grafias_da_mesma_coisa(fontes):
    """Derivado do cadastro: `achatar(de) == achatar(para)` em todo apelido.

    Um apelido é para CONVERGIR grafia, nunca para renomear uma coisa noutra.
    `{"Boleto": "Faturamento"}` passaria calado por qualquer teste de exemplo e
    reescreveria o assunto de 1.131 linhas.
    """
    for codigo, fonte in fontes.items():
        for de, para in Mapeamento.de_json(fonte.mapeamento_colunas).apelidos.items():
            assert achatar(de) == achatar(para), (
                f"{codigo}: o apelido {de!r} -> {para!r} não é a mesma palavra; "
                "apelido converge grafia, não renomeia assunto."
            )


def test_o_subtema_e_o_nivel_abaixo_do_tema(fontes):
    """A SL é a primeira fonte a mapear `subtema`, e no nível certo."""
    colunas = Mapeamento.de_json(fontes["approach_sl"].mapeamento_colunas).colunas

    assert colunas["tema"] == "Tags (tema)"
    assert colunas["subtema"] == "Tags (subtema)"
    #: E A CM NÃO MAPEIA `subtema`: as colunas `Tags (assunto 2/3/4)` dela são
    #: um SACO DE ETIQUETAS posicional — 1.135 linhas com `replied`, 544 com
    #: `Visto` —, e não o nível abaixo do assunto.
    assert "subtema" not in Mapeamento.de_json(fontes["approach_cm"].mapeamento_colunas).colunas


#: O MAPEAMENTO DE ANTES DA 0091, por fonte. É o que a migration tinha de
#: PRESERVAR, e ela mexe no JSON inteiro com `||` e `jsonb_build_object` — um
#: `jsonb_set` no caminho errado, ou um `||` invertido, apagaria isto sem erro
#: nenhum e a subida passaria a recusar a planilha por coluna faltando.
ANTES_DA_0091 = {
    "approach_sl": {
        "aba": "SL",
        "arquivo": "approach",
        "colunas": {
            "data": "Data",
            "sentimento": "Sentimento",
            "engajamento": "Engajamento",
            "tema": "Tags (tema)",
            "unidade": "Concessionárias",
        },
    },
    "approach_cm": {
        "aba": "CM",
        "arquivo": "approach",
        "colunas": {
            "data": "Data",
            "sentimento": "Sentimento",
            "engajamento": "Interações",
            "tema": "TAG (assunto 1)",
            "unidade": "Concessionárias",
            "teor": "TAG (motivo)",
        },
    },
}
#: O prefixo de taxonomia que a 0048 cadastrou. Vale para as duas fontes.
PREFIXO_DA_0048 = "^(\\d+\\s*[,-]\\s*)?(Aegea\\s*[,-]\\s*)?"


def test_o_mapeamento_de_antes_sobrevive_a_migration(fontes):
    """A 0091 ACRESCENTA. Nada do cadastro anterior pode ter sumido."""
    for codigo, esperado in ANTES_DA_0091.items():
        mapeamento = dict(fontes[codigo].mapeamento_colunas)
        assert mapeamento["aba"] == esperado["aba"]
        assert mapeamento["arquivo"] == esperado["arquivo"]
        assert mapeamento["prefixo_a_remover"] == PREFIXO_DA_0048, (
            f"{codigo} perdeu o prefixo de taxonomia; sem ele "
            '"2 - Aegea - Falta de Água" vira assunto.'
        )
        for campo, coluna in esperado["colunas"].items():
            assert mapeamento["colunas"].get(campo) == coluna, (
                f"{codigo}: o mapeamento de `{campo}` era {coluna!r} e virou "
                f"{mapeamento['colunas'].get(campo)!r}."
            )


def test_a_0091_pode_rodar_duas_vezes(sessao, fontes):
    """Idempotente: o ambiente que reaplica uma migration não pode divergir.

    Roda DENTRO da transação do teste, que é desfeita no fim.
    """
    (arquivo,) = MIGRATIONS.glob("0091_*.sql")
    antes = {codigo: dict(fonte.mapeamento_colunas) for codigo, fonte in fontes.items()}

    sessao.execute(text(arquivo.read_text(encoding="utf-8")))
    sessao.flush()
    sessao.expire_all()

    depois = {
        fonte.codigo: dict(fonte.mapeamento_colunas)
        for fonte in sessao.scalars(
            select(ScoreFonte).where(ScoreFonte.codigo.in_(tuple(antes)))
        )
    }
    assert depois == antes
