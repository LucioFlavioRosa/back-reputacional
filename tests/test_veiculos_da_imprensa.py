"""Ligar a menção ao veículo do cadastro, e criar o que falta.

POR QUE ESTE ARQUIVO EXISTE. O cadastro compartilhado tem 39 veículos; o export
de dois meses da Clipei traz 2.648 distintos. Criar os que faltam no upload foi
pedido do dono do produto — e ver a conta ANTES de confirmar foi a outra metade
do pedido, que é o que torna a coisa segura.

A LIÇÃO QUE A IMPORTAÇÃO DE AGENDAS JÁ ESCREVEU no próprio código: "importação
de planilha sem conferência humana cria duplicata de instituição em massa, e
desfazer isso depois é pior que digitar de novo". Aqui são 2.631 criações numa
subida. Estes testes protegem a parte que impede o desastre: `reconhecer` não
escreve, e diz quantos e quais.
"""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico, Esfera
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso.veiculos_da_imprensa import (
    CATEGORIA_DA_IMPRENSA,
    ESFERA_POR_ABRANGENCIA,
    criar,
    reconhecer,
)
from app.dominio.ingestao_score import para_sigla
from app.dominio.texto import normalizar
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


def _da_planilha(nome, uf="Santa Catarina", abrangencia="Local", mencoes=1):
    return {nome: {"uf": uf, "abrangencia": abrangencia, "mencoes": mencoes}}


# ============================================ reconhecer: separa, e NÃO escreve
def test_reconhecer_separa_o_que_existe_do_que_falta(sessao):
    ja = Instituicao(
        nome="Veículo Já Cadastrado 42",
        nome_normalizado=normalizar("Veículo Já Cadastrado 42"),
        tipo="veiculo",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(
        sessao,
        {
            **_da_planilha("Veículo Já Cadastrado 42"),
            **_da_planilha("Veículo Que Falta 42"),
        },
    )

    assert normalizar("Veículo Já Cadastrado 42") in reco.cadastrados
    assert [v.nome for v in reco.novos] == ["Veículo Que Falta 42"]
    assert reco.quantos_novos == 1


def test_reconhecer_NAO_escreve_nada(sessao):
    """A conferência é leitura. Se ela criasse, a conta que a tela mostra já
    seria o fato consumado — e o "mostre antes" do dono não existiria."""
    antes = sessao.scalar(
        select(func.count()).select_from(Instituicao).where(Instituicao.tipo == "veiculo")
    )

    reconhecer(sessao, _da_planilha("Veículo Novo Que Não Deve Nascer 42"))

    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Instituicao)
            .where(Instituicao.tipo == "veiculo")
        )
        == antes
    )


def test_reconhecer_ordena_pelos_mais_citados(sessao):
    """A tela mostra os primeiros, e 2.631 nomes não cabem numa lista. Um
    veículo com 1.453 menções merece a atenção que um com 1 não merece."""
    reco = reconhecer(
        sessao,
        {
            **_da_planilha("Pouco Citado 42", mencoes=1),
            **_da_planilha("Muito Citado 42", mencoes=1453),
            **_da_planilha("Medio 42", mencoes=50),
        },
    )

    assert [v.nome for v in reco.novos] == ["Muito Citado 42", "Medio 42", "Pouco Citado 42"]


def test_reconhecer_casa_por_nome_NORMALIZADO(sessao):
    """ACENTO E CAIXA NÃO CRIAM VEÍCULO NOVO.

    `Instituicao` tem índice único em `(nome_normalizado, tipo)`, e a Clipei
    pode mandar "VALOR ECONÔMICO" num mês e "Valor Econômico" no outro. Sem
    normalizar, o segundo mês criaria um segundo cadastro do mesmo veículo — a
    duplicata em massa que a importação de agendas documenta.
    """
    sessao.add(
        Instituicao(
            nome="Valor Econômico 42",
            nome_normalizado=normalizar("Valor Econômico 42"),
            tipo="veiculo",
        )
    )
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("  VALOR  ECONOMICO 42  "))

    assert reco.novos == (), "acento e caixa não podem criar veículo novo"


def test_reconhecer_ignora_instituicao_que_nao_e_veiculo(sessao):
    """Um ÓRGÃO com o mesmo nome não serve: o índice único é por
    `(nome_normalizado, tipo)`, e a menção aponta para veículo."""
    sessao.add(
        Instituicao(
            nome="Homônimo 42",
            nome_normalizado=normalizar("Homônimo 42"),
            tipo="orgao",
        )
    )
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Homônimo 42"))

    assert [v.nome for v in reco.novos] == ["Homônimo 42"]


def test_reconhecer_com_planilha_sem_veiculo_nenhum(sessao):
    reco = reconhecer(sessao, {})
    assert reco.novos == () and reco.cadastrados == {}


# ============================================ criar: o que o fornecedor sabe
def test_criar_nasce_como_imprensa_e_SEM_subcategoria(sessao):
    """A CATEGORIA É A ÚNICA QUE O FORNECEDOR PERMITE AFIRMAR.

    É um export de clipping de imprensa: todo veículo dele é imprensa. A
    subcategoria é lógica EDITORIAL (econômica, geral nacional, regional das
    concessões, municipal) e nenhuma coluna da Clipei a informa — e é justamente
    dela que a lente Mercado depende. Inventá-la aqui faria a lente se separar
    por um palpite nosso em vez de uma decisão da Aegea.
    """
    reco = reconhecer(sessao, _da_planilha("Veículo Nascendo 42"))
    criar(sessao, reco.novos)

    novo = sessao.scalar(
        select(Instituicao).where(Instituicao.nome == "Veículo Nascendo 42")
    )
    imprensa = sessao.scalar(
        select(CategoriaPublico.id).where(CategoriaPublico.nome == CATEGORIA_DA_IMPRENSA)
    )
    assert novo.tipo == "veiculo"
    assert novo.categoria_publico_id == imprensa
    assert novo.subcategoria_publico_id is None, "a lógica editorial é juízo humano"
    assert novo.ativo is True


def test_criar_grava_a_UF_EM_SIGLA_e_nao_o_nome(sessao):
    """`instituicao.uf` é o domínio `abrangencia`, com CHECK das 29 siglas.

    "Santa Catarina" ali é RECUSADO pelo Postgres — e é a assimetria com
    `mencao.uf`, que guarda o nome por decisão do dono. Sem `para_sigla`, a
    criação estouraria no banco em vez de gravar.
    """
    reco = reconhecer(sessao, _da_planilha("Veículo Com UF 42", uf="Santa Catarina"))
    criar(sessao, reco.novos)

    novo = sessao.scalar(select(Instituicao).where(Instituicao.nome == "Veículo Com UF 42"))
    assert novo.uf == "SC"
    assert para_sigla("Santa Catarina") == "SC"


def test_criar_deixa_a_UF_nula_quando_nao_e_estado_brasileiro(sessao):
    """O CHECK recusaria, e nulo é verdade: "sem praça definida".

    `mencao.uf` guarda "Comunidade de Madrid" porque é texto livre e a
    informação é útil. Aqui não cabe, e perder o cadastro inteiro por causa da
    praça seria trocar o veículo por nada.
    """
    reco = reconhecer(
        sessao, _da_planilha("Veículo De Fora 42", uf="Comunidade de Madrid")
    )
    criar(sessao, reco.novos)

    novo = sessao.scalar(select(Instituicao).where(Instituicao.nome == "Veículo De Fora 42"))
    assert novo.uf is None


@pytest.mark.parametrize(
    "abrangencia, esfera_esperada",
    [
        # O FORNECEDOR DIZ O ALCANCE e o cadastro tem o campo. "Local" vira
        # Municipal, que é o nome que a Aegea usa para a mesma ideia.
        ("Local", "Municipal"),
        ("Regional", "Regional"),
        ("Nacional", "Nacional"),
        ("Internacional", "Internacional"),
        # Vazio NÃO INVENTA esfera: 598 dos 2.631 veículos do export vêm sem
        # abrangência, e chutar "Municipal" neles classificaria por conveniência.
        ("", None),
        ("Outra Coisa", None),
    ],
)
def test_criar_deriva_a_esfera_da_abrangencia(sessao, abrangencia, esfera_esperada):
    nome = f"Veículo Esfera {abrangencia or 'vazia'} 42"
    reco = reconhecer(sessao, _da_planilha(nome, abrangencia=abrangencia))
    criar(sessao, reco.novos)

    novo = sessao.scalar(select(Instituicao).where(Instituicao.nome == nome))
    if esfera_esperada is None:
        assert novo.esfera_id is None
    else:
        esperado = sessao.scalar(select(Esfera.id).where(Esfera.nome == esfera_esperada))
        assert novo.esfera_id == esperado


def test_as_esferas_que_o_mapa_cita_existem_no_cadastro(sessao):
    """A ÂNCORA. `ESFERA_POR_ABRANGENCIA` escreve nomes de esfera à mão; se
    alguém renomear uma esfera no cadastro, a derivação para de funcionar em
    silêncio — veículo nasceria sem esfera e ninguém notaria."""
    cadastradas = {n for n in sessao.scalars(select(Esfera.nome))}
    assert set(ESFERA_POR_ABRANGENCIA.values()) <= cadastradas


def test_a_categoria_da_imprensa_existe_e_esta_ativa(sessao):
    """Mesma âncora, para a categoria: a `0061` separou Imprensa de Formadores
    de Opinião e desativou a antiga. Se a ativa mudar de nome, `criar` passaria
    a gravar categoria nula."""
    ativa = sessao.scalar(
        select(CategoriaPublico.id).where(
            CategoriaPublico.nome == CATEGORIA_DA_IMPRENSA, CategoriaPublico.ativo
        )
    )
    assert ativa is not None


def test_criar_sem_nada_a_criar_nao_toca_no_banco(sessao):
    assert criar(sessao, ()) == {}
