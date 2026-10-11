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


def _da_planilha(nome, uf="Santa Catarina", abrangencia="Local", mencoes=1, tier=""):
    return {
        nome: {"uf": uf, "abrangencia": abrangencia, "mencoes": mencoes, "tier": tier}
    }


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


# ============================================ a relevância que a planilha informa
@pytest.mark.parametrize(
    ("da_clipei", "relevancia"),
    [
        ("Muito Relevante", 1),
        ("muito relevante", 1),
        ("MUITO RELEVANTE ", 1),
        ("Relevante", 2),
        ("Menos Relevante", 3),
    ],
)
def test_criar_grava_a_RELEVANCIA_que_a_planilha_informa(sessao, da_clipei, relevancia):
    """A escala da Clipei tem três nomes; o cadastro tem três números.

    PEDIDO DO DONO DO PRODUTO (11/10/2026): "na tabela da clipei tem uma coluna de
    tier, e no cadastro de instituições que são cadastradas automaticamente a
    informação de tier falta — esse campo se chama relevância". Ele faltava mesmo:
    medido, 39 dos 2.670 veículos cadastrados tinham relevância. A ingestão criava
    os outros 2.631 jogando fora uma coluna que estava no arquivo.

    A MEDIDA QUE AUTORIZA COPIAR. A coluna é por MATÉRIA, não por veículo — nada
    garantiria que o mesmo veículo viesse sempre com o mesmo tier. Medido: 2.640
    dos 2.641 veículos com menção têm UM único tier distinto em todas as suas
    matérias. Só um divergiu. Na prática o tier da Clipei é propriedade do
    veículo, e é isso que faz disto uma leitura e não um chute.

    AS VARIAÇÕES DE CAIXA E ESPAÇO ESTÃO AQUI porque a tradução usa as MESMAS
    duas funções da gravação da menção (`achatar` e `TIERS`). Se alguém trocar por
    uma comparação direta, o cadastro e a menção passam a discordar sobre o mesmo
    texto — e a discordância aparece numa tela, não aqui.
    """
    reco = reconhecer(sessao, _da_planilha(f"Veículo Com Tier {relevancia} 42", tier=da_clipei))
    criar(sessao, reco.novos)

    novo = sessao.scalar(
        select(Instituicao).where(Instituicao.nome == f"Veículo Com Tier {relevancia} 42")
    )
    assert novo.tier == relevancia


def test_criar_deixa_a_relevancia_NULA_quando_a_fonte_nao_tem_tier(sessao):
    """Rede social e canal próprio não têm tier, e inventar um seria afirmar.

    As fontes da Bites e da Approach não mapeiam coluna de tier nenhuma — só as
    duas da Clipei mapeiam, para "Aegea Tier". O perfil nasce sem relevância, que
    é a verdade sobre ele.
    """
    reco = reconhecer(sessao, _da_planilha("Veículo Sem Tier 42"))
    criar(sessao, reco.novos)

    novo = sessao.scalar(select(Instituicao).where(Instituicao.nome == "Veículo Sem Tier 42"))
    assert novo.tier is None


def test_criar_deixa_a_relevancia_NULA_quando_o_tier_nao_e_da_escala(sessao):
    """Texto fora da escala não vira palpite.

    "Tier 1" escrito na coluna, ou um valor novo que o fornecedor inventar, não
    está em `TIERS` — e cair no nível errado é pior que não ter nível, porque a
    régua de peso do Score usa o tier.
    """
    reco = reconhecer(sessao, _da_planilha("Veículo Com Tier Estranho 42", tier="prioritário"))
    criar(sessao, reco.novos)

    novo = sessao.scalar(
        select(Instituicao).where(Instituicao.nome == "Veículo Com Tier Estranho 42")
    )
    assert novo.tier is None


def test_a_relevancia_de_cada_tier_da_clipei_EXISTE_no_cadastro(sessao):
    """O mapa aponta para `relevancia.id`, e os três têm de estar lá e ativos.

    POR QUE ISTO É TESTE: o número do mapa vai direto para uma chave estrangeira.
    Se alguém desativar o Tier 2 — como a `0082` desativou o Tier 4 —, a criação
    passaria a gravar um tier que a tela de cadastro não oferece mais, e a tela de
    stakeholders recusaria ao editar. O T4 saiu de circulação justamente porque a
    escala da Clipei não o tem; os três que ela tem precisam continuar.
    """
    from app.banco.tabelas_catalogo import Relevancia
    from app.dominio.score import RELEVANCIA_DO_TIER

    ativos = set(
        sessao.scalars(select(Relevancia.id).where(Relevancia.ativo.is_(True))).all()
    )
    faltando = sorted(set(RELEVANCIA_DO_TIER.values()) - ativos)
    assert not faltando, f"a Clipei mapeia para relevância inativa ou inexistente: {faltando}"


def test_o_mapa_cobre_TODA_a_escala_da_clipei():
    """Os três valores que a planilha pode trazer têm correspondência.

    `TIERS` é o vocabulário que a gravação da menção aceita; `RELEVANCIA_DO_TIER`
    é a tradução para o cadastro. Um valor em `TIERS` sem número aqui faria o
    veículo nascer sem relevância em silêncio — a coluna preenchida, o cadastro
    vazio, e nada reclamando. É a mesma forma do defeito que a área declarada e
    não gravada produziu na importação de agendas.
    """
    from app.dominio.ingestao_score import TIERS
    from app.dominio.score import RELEVANCIA_DO_TIER

    sem_numero = sorted(set(TIERS.values()) - set(RELEVANCIA_DO_TIER))
    assert not sem_numero, f"a escala da Clipei tem valor sem relevância: {sem_numero}"


# ======================================= o mesmo ator, cadastrado de outro tipo
def test_reconhecer_ACHA_o_investidor_de_mesmo_nome_em_vez_de_duplicar(sessao):
    """O banco que publica relatório é o banco com quem a companhia se reúne.

    O DEFEITO QUE ISTO FECHA, medido em 11/10/2026: a busca filtrava pelo tipo da
    fonte, então um cadastro `investidor` era invisível para a Clipei. O nome
    virava novo e a ingestão criava um SEGUNDO cadastro como `veiculo` — e a
    companhia ficava partida em dois registros:

        BTG Pactual   investidor  12 agendas,  0 menções
        BTG Pactual   veiculo      0 agendas,  4 menções

    Nenhuma tela junta os dois. Quem abre o BTG vê as reuniões sem as menções, ou
    as menções sem as reuniões, dependendo de qual dos dois abriu. O mesmo com
    Fitch Ratings: 11 agendas de um lado, 2 menções do outro.
    """
    ja = Instituicao(
        nome="Banco Que Fala 42",
        nome_normalizado=normalizar("Banco Que Fala 42"),
        tipo="investidor",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Banco Que Fala 42"))

    assert reco.novos == (), [v.nome for v in reco.novos]
    assert reco.cadastrados[normalizar("Banco Que Fala 42")] == str(ja.id)


def test_reconhecer_acha_o_credor_de_mesmo_nome(sessao):
    """`credor` entra pela mesma razão do investidor: é o mesmo ator.

    Dois tipos e não um porque a taxonomia os separa — "duas coisas a taxonomia
    não distingue: um banco credor de um investidor (os dois moram em Mercado
    Financeiro e de Capitais)", diz `TIPO_DA_CATEGORIA_DE_PUBLICO`. Quem fala na
    imprensa pode estar cadastrado em qualquer um dos dois.
    """
    ja = Instituicao(
        nome="Credor Que Fala 42",
        nome_normalizado=normalizar("Credor Que Fala 42"),
        tipo="credor",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Credor Que Fala 42"))

    assert reco.novos == ()
    assert reco.cadastrados[normalizar("Credor Que Fala 42")] == str(ja.id)


def test_o_VEICULO_ainda_ganha_quando_os_dois_existem(sessao):
    """A preferência pelo tipo da fonte não mudou, e é ela que mantém o passado.

    POR QUE ISTO IMPORTA: enquanto BTG Pactual existir como `investidor` E como
    `veiculo`, a Clipei tem de continuar achando o veículo dela — senão as menções
    novas iriam para um cadastro e as antigas ficariam no outro, e a lente passaria
    a contar o mesmo ator duas vezes. Alargar a busca sem esta preferência
    trocaria uma divisão por outra, pior.
    """
    investidor = Instituicao(
        nome="Dois Cadastros 42",
        nome_normalizado=normalizar("Dois Cadastros 42"),
        tipo="investidor",
    )
    veiculo = Instituicao(
        nome="Dois Cadastros 42",
        nome_normalizado=normalizar("Dois Cadastros 42"),
        tipo="veiculo",
    )
    sessao.add_all([investidor, veiculo])
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Dois Cadastros 42"))

    assert reco.cadastrados[normalizar("Dois Cadastros 42")] == str(veiculo.id)


def test_o_ORGAO_de_mesmo_nome_continua_sendo_HOMONIMO(sessao):
    """A metade que a correção não pode levar embora.

    Um nome de jornal igual ao de uma prefeitura é homônimo, e apontar a matéria
    para o órgão seria atribuição errada. `orgao`, `proposicao`, `entidade` e
    `area_interna` seguem fora de `TIPOS_DO_MESMO_ATOR` por isso — e sem este
    teste, alargar a lista "só um pouco mais" não quebraria nada visível.
    """
    for tipo in ("orgao", "proposicao", "entidade", "area_interna"):
        nome = f"Homônimo De {tipo} 42"
        sessao.add(
            Instituicao(nome=nome, nome_normalizado=normalizar(nome), tipo=tipo)
        )
    sessao.flush()

    for tipo in ("orgao", "proposicao", "entidade", "area_interna"):
        nome = f"Homônimo De {tipo} 42"
        reco = reconhecer(sessao, _da_planilha(nome))
        assert [v.nome for v in reco.novos] == [nome], f"{tipo} deixou de ser homônimo"


def test_o_perfil_de_rede_continua_achando_em_QUALQUER_tipo(sessao):
    """A Bites não mudou, e a medida diz que ela já cruzava os tipos.

    Medido: das menções da Bites, 2.529 estão em `perfil_rede` e 53 em cadastros
    `veiculo` — o vínculo entre tipos sempre funcionou ali, porque o Instagram do
    Valor Econômico É o Valor. `TIPOS_DO_MESMO_ATOR` não entra nesse caminho.
    """
    ja = Instituicao(
        nome="Orgão Com Perfil 42",
        nome_normalizado=normalizar("Orgão Com Perfil 42"),
        tipo="orgao",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Orgão Com Perfil 42"), "perfil_rede")

    assert reco.novos == ()
    assert reco.cadastrados[normalizar("Orgão Com Perfil 42")] == str(ja.id)
