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
from app.banco.tabelas_stakeholders import Instituicao, InstituicaoApelido
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


def test_reconhecer_ACHA_PELO_APELIDO_o_nome_que_a_fusao_levou(sessao):
    """A duplicata não volta na subida seguinte.

    O DEFEITO, achado na revisão da fusão com escolha de direção: a ingestão casa
    por `nome_normalizado` EXATO. Quando dois cadastros se fundem, o nome de quem
    sai some do banco — e o fornecedor continua mandando aquele nome todo mês.
    Sem apelido ele vira "veículo novo" e NASCE DE NOVO, com as menções do mês
    dentro: a duplicata que alguém acabou de resolver volta.

    O TESTE É A SUBIDA DO MÊS SEGUINTE: o cadastro se chama `handlezz10`, a
    planilha manda "Veículo Fundido Zz10" — o nome que a fusão levou —, e o
    reconhecimento tem de devolver o cadastro que ficou, e não um novo.
    """
    ficou = Instituicao(
        nome="handlezz10",
        nome_normalizado=normalizar("handlezz10"),
        tipo="perfil_rede",
    )
    sessao.add(ficou)
    sessao.flush()
    sessao.add(
        InstituicaoApelido(
            nome_normalizado=normalizar("Veículo Fundido Zz10"),
            nome="Veículo Fundido Zz10",
            instituicao_id=ficou.id,
        )
    )
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Veículo Fundido Zz10"))

    assert reco.novos == ()
    assert reco.cadastrados == {normalizar("Veículo Fundido Zz10"): str(ficou.id)}


def test_sem_o_apelido_o_MESMO_nome_voltaria_a_nascer(sessao):
    """O controle do teste acima, e a medida do defeito que ele fecha.

    Sem esta asserção, um `reconhecer` que achasse o cadastro por outro caminho
    qualquer faria o teste do apelido passar sem o apelido existir — e eu não
    saberia se a linha nova serve para alguma coisa.
    """
    ficou = Instituicao(
        nome="handlezz11",
        nome_normalizado=normalizar("handlezz11"),
        tipo="perfil_rede",
    )
    sessao.add(ficou)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Veículo Fundido Zz11"))

    assert [v.nome for v in reco.novos] == ["Veículo Fundido Zz11"]


def test_o_APELIDO_de_um_veiculo_da_lista_CONTINUA_na_lista(sessao):
    """A fusão não pode tirar o veículo da lente Mercado.

    ACHADO ALTO DE REVISÃO, e é mais largo do que parecia: a lista é um conjunto
    de NOMES, e o recorte casa o TEXTO da linha do fornecedor contra ele. Quando
    dois cadastros se fundem, o nome de quem sai deixa de existir em
    `instituicao` — então QUALQUER fusão que levasse o nome de um veículo listado
    tirava as menções dele da lente, em silêncio. Não é só a fusão que troca de
    tipo: mesmo veículo em veículo, o texto que o clipping manda todo mês é o de
    quem SAIU.
    """
    from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico

    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            CategoriaPublico.nome == "Imprensa",
            SubcategoriaPublico.nome == "Econômica e de negócios",
        )
    )
    ficou = Instituicao(
        nome="Valor Econômico SP zz13",
        nome_normalizado=normalizar("Valor Econômico SP zz13"),
        tipo="veiculo",
        subcategoria_publico_id=alvo,
    )
    sessao.add(ficou)
    sessao.flush()
    sessao.add(
        InstituicaoApelido(
            nome_normalizado=normalizar("Valor Econômico zz13"),
            nome="Valor Econômico zz13",
            instituicao_id=ficou.id,
        )
    )
    sessao.flush()

    from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista

    lista = nomes_da_lista(sessao, "imprensa_economica")

    assert normalizar("Valor Econômico SP zz13") in lista
    #: O NOME QUE A FUSÃO LEVOU continua recortando para a lente.
    assert normalizar("Valor Econômico zz13") in lista


def test_o_apelido_de_quem_NAO_esta_na_lista_fica_de_fora(sessao):
    #: O controle: o apelido entra na lista PELO cadastro para onde ele aponta, e
    #: não por ser apelido. Sem isto, um apelido qualquer alargaria a lente.
    from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista

    solto = Instituicao(
        nome="Jornal Solto zz14",
        nome_normalizado=normalizar("Jornal Solto zz14"),
        tipo="veiculo",
    )
    sessao.add(solto)
    sessao.flush()
    sessao.add(
        InstituicaoApelido(
            nome_normalizado=normalizar("Jornalzinho zz14"),
            nome="Jornalzinho zz14",
            instituicao_id=solto.id,
        )
    )
    sessao.flush()

    assert normalizar("Jornalzinho zz14") not in nomes_da_lista(
        sessao, "imprensa_economica"
    )


def test_o_apelido_de_DUAS_linhas_nao_resolve_o_ator(sessao):
    """Nome ambíguo não vira menção no dossiê de ninguém.

    A chave da tabela é o par (nome, instituição), então o MESMO nome pode ter
    duas linhas — duas fusões de dois atores homônimos. Escolher uma delas
    mandaria as menções de um ator para o dossiê do outro. A regra é a da
    concessionária: nunca adivinhar com mais de uma candidata. O nome segue para
    a conferência, que é onde gente decide.
    """
    uma = Instituicao(
        nome="Casa Uma zz15", nome_normalizado=normalizar("Casa Uma zz15"), tipo="entidade"
    )
    outra = Instituicao(
        nome="Casa Outra zz15",
        nome_normalizado=normalizar("Casa Outra zz15"),
        tipo="entidade",
    )
    sessao.add_all([uma, outra])
    sessao.flush()
    chave = normalizar("Homônimo zz15")
    sessao.add_all(
        [
            InstituicaoApelido(
                nome_normalizado=chave, nome="Homônimo zz15", instituicao_id=uma.id
            ),
            InstituicaoApelido(
                nome_normalizado=chave, nome="Homônimo zz15", instituicao_id=outra.id
            ),
        ]
    )
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Homônimo zz15"))

    assert reco.cadastrados == {}
    assert [v.nome for v in reco.novos] == ["Homônimo zz15"]


def test_o_apelido_AMBIGUO_continua_valendo_para_a_LISTA(sessao):
    """A lente não perde o veículo por causa de uma fusão alheia.

    É a outra metade do teste acima, e a razão de a ambiguidade ser REGISTRADA
    em vez de apagada: a pergunta da lente não é "de quem é esta menção", é
    "este texto é de um veículo da lista". Se UMA das linhas aponta para um
    veículo listado, a resposta é sim — e as menções históricas continuam no
    Mercado.

    A versão que apagava o apelido ambíguo fazia uma fusão sem relação com
    mercado mudar a série de meses fechados.
    """
    from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
    from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista

    alvo = sessao.scalar(
        select(SubcategoriaPublico.id)
        .join(
            CategoriaPublico,
            CategoriaPublico.id == SubcategoriaPublico.categoria_publico_id,
        )
        .where(
            CategoriaPublico.nome == "Imprensa",
            SubcategoriaPublico.nome == "Econômica e de negócios",
        )
    )
    listado = Instituicao(
        nome="Veículo Listado zz16",
        nome_normalizado=normalizar("Veículo Listado zz16"),
        tipo="veiculo",
        subcategoria_publico_id=alvo,
    )
    qualquer = Instituicao(
        nome="Entidade Qualquer zz16",
        nome_normalizado=normalizar("Entidade Qualquer zz16"),
        tipo="entidade",
    )
    sessao.add_all([listado, qualquer])
    sessao.flush()
    chave = normalizar("Homônimo zz16")
    sessao.add_all(
        [
            InstituicaoApelido(
                nome_normalizado=chave, nome="Homônimo zz16", instituicao_id=listado.id
            ),
            InstituicaoApelido(
                nome_normalizado=chave, nome="Homônimo zz16", instituicao_id=qualquer.id
            ),
        ]
    )
    sessao.flush()

    assert chave in nomes_da_lista(sessao, "imprensa_economica")


def test_o_apelido_NAO_vence_um_cadastro_vivo_de_mesmo_nome(sessao):
    """A ordem é cadastro exato primeiro, apelido depois.

    `instituicao.nome_normalizado` NÃO é única — ALMG existe como entidade e como
    órgão. Um apelido que respondesse antes da busca exata trocaria o ator de um
    cadastro VIVO pelo de uma fusão antiga, e o pior é que ninguém veria: a
    menção simplesmente iria para o dossiê errado.
    """
    vivo = Instituicao(
        nome="Ambíguo Zz12",
        nome_normalizado=normalizar("Ambíguo Zz12"),
        tipo="veiculo",
    )
    outro = Instituicao(
        nome="outrozz12", nome_normalizado=normalizar("outrozz12"), tipo="perfil_rede"
    )
    sessao.add_all([vivo, outro])
    sessao.flush()
    #: Um apelido com o MESMO nome do cadastro vivo, apontando para outro lugar.
    sessao.add(
        InstituicaoApelido(
            nome_normalizado=normalizar("Ambíguo Zz12"),
            nome="Ambíguo Zz12",
            instituicao_id=outro.id,
        )
    )
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Ambíguo Zz12"))

    assert reco.cadastrados == {normalizar("Ambíguo Zz12"): str(vivo.id)}


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


def test_reconhecer_ACHA_qualquer_tipo_porque_a_base_e_UMA_SO(sessao):
    """Um ÓRGÃO com o mesmo nome É o mesmo ator, e a regra mudou em 11/10/2026.

    ESTE TESTE AFIRMAVA O CONTRÁRIO, e estava certo pela regra de então: "um órgão
    com o mesmo nome não serve: o índice único é por `(nome_normalizado, tipo)`, e
    a menção aponta para veículo". O dono do produto trocou a regra:

        "qualquer fonte de dados tem acesso à mesma base de instituições e
        interlocutores, não interessa se é no CRM, redes sociais ou imprensa. O
        BTG por exemplo podemos ter acesso em rede social, em reunião de
        investimento ou imprensa, mas ele continua sendo um só, se comunicando e
        relacionando em diferentes níveis."

    E O CUSTO DA REGRA ANTIGA ESTÁ MEDIDO: 24 atores ficaram partidos em dois
    cadastros. BTG Pactual e Fitch Ratings como `investidor` + `veiculo` — 23
    agendas num registro, 6 menções no outro —, e 22 pares `perfil_rede` +
    `veiculo`, com 310 menções de um lado e 37 do outro.
    """
    ja = Instituicao(
        nome="Homônimo 42",
        nome_normalizado=normalizar("Homônimo 42"),
        tipo="orgao",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Homônimo 42"))

    assert reco.novos == (), [v.nome for v in reco.novos]
    assert reco.cadastrados[normalizar("Homônimo 42")] == str(ja.id)


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


def test_a_ingestao_NAO_MUDA_o_enquadramento_de_quem_ja_existe(sessao):
    """"Quem decide como enquadrar é o time que está registrando a primeira vez ou
    editando posteriormente."

    É A OUTRA METADE DA REGRA NOVA, e sem ela a primeira é perigosa: a busca
    passou a achar o cadastro em QUALQUER tipo, então ela agora encontra o órgão, a
    entidade, o investidor. Se a ingestão aproveitasse para "corrigir" o tipo ou a
    categoria do que achou, uma subida de clipping reclassificaria o cadastro que
    alguém montou à mão — e a frente de toda agenda daquela instituição mudaria
    junto, porque `derivar_frente` sai do tipo.

    POR ISSO ESTE TESTE PERCORRE OS TIPOS: ele afirma, para cada um, que o cadastro
    sai da ingestão exatamente como entrou.
    """
    from app.banco.tabelas_catalogo import CategoriaPublico

    imprensa = sessao.scalar(
        select(CategoriaPublico.id).where(CategoriaPublico.nome == CATEGORIA_DA_IMPRENSA)
    )
    for tipo in ("orgao", "proposicao", "entidade", "area_interna", "investidor"):
        nome = f"Enquadrado Como {tipo} 42"
        ja = Instituicao(
            nome=nome,
            nome_normalizado=normalizar(nome),
            tipo=tipo,
            #: Uma categoria PROPOSITALMENTE diferente da que a ingestão daria a um
            #: veículo: se ela sobrescrevesse, o teste veria.
            categoria_publico_id=None,
        )
        sessao.add(ja)
        sessao.flush()

        reco = reconhecer(sessao, _da_planilha(nome))
        criar(sessao, reco.novos)
        sessao.flush()
        sessao.refresh(ja)

        assert ja.tipo == tipo, f"a ingestão mudou o tipo de {nome}"
        assert ja.categoria_publico_id != imprensa, (
            f"a ingestão classificou {nome} como imprensa"
        )
        #: E NÃO NASCEU UM SEGUNDO: é a regra nova agindo, e a razão de ela existir.
        quantos = sessao.scalar(
            select(func.count(Instituicao.id)).where(
                Instituicao.nome_normalizado == normalizar(nome)
            )
        )
        assert quantos == 1, f"{nome} ficou com {quantos} cadastros"


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


# ============================ o parecido: quem autoriza vê antes de autorizar
def test_reconhecer_APONTA_o_parecido_que_difere_SO_NO_ESPACO(sessao):
    """`Neofeed` e `Neo Feed` — o caso que o dono do produto deu.

    MEDIDO ANTES DE EXISTIR: com `NeofeedZZ` no cadastro e `Neo feed ZZ` na
    planilha, `reconhecer` devolvia `novos=['Neo feed ZZ']` e `criar` gravava o
    SEGUNDO cadastro. A causa é a assimetria entre as duas chaves: a busca usa
    `normalizar`, que PRESERVA o espaço, e a fila de duplicados compara por
    `achatar_para_comparar`, que o tira. A ingestão fabricava exatamente os pares
    que a fila depois perguntava — 5 `veiculo`+`veiculo` e 59
    `perfil_rede`+`veiculo` na base.

    O NOME CONTINUA NOVO, e isto é deliberado: a semelhança não prova identidade,
    e quem decide é gente. O que muda é que a conferência agora DIZ de quem ele se
    parece, para a autorização não ser tomada sobre um nome e um número.
    """
    ja = Instituicao(
        nome="NeofeedZz81",
        nome_normalizado=normalizar("NeofeedZz81"),
        tipo="veiculo",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Neo feed Zz81"))

    (novo,) = reco.novos
    assert novo.nome == "Neo feed Zz81"
    assert [(p.nome, p.tipo) for p in novo.parecidos] == [("NeofeedZz81", "veiculo")]


def test_reconhecer_APONTA_o_parecido_de_OUTRO_TIPO(sessao):
    """O handle da rede contra o nome do clipping, que é o caso dos 59 pares.

    `cnnbrasil` (perfil de rede) e `CNN Brasil` (veículo) são o mesmo ator, e a
    chave achatada os une. Sem o aviso, a Clipei cria o veículo ao lado do perfil
    que a Bites já tinha criado — foi assim que os 22 pares que a `0084` fundiu
    nasceram depois de a `0077` já tê-los fundido uma vez.

    E O NOME CONTINUA NOVO, de propósito. Uma primeira versão deste teste afirmava
    que ele seria RECONHECIDO — ou seja, ligado ao perfil automaticamente pela
    chave achatada. Isso é precisamente o que esta mudança NÃO faz: a semelhança
    não prova identidade, `bmc.news` coincide com DOIS veículos, e ligar sozinho
    faria a máquina decidir o que o próprio módulo da fila diz que só gente decide.

    O QUE MUDA É A INFORMAÇÃO na hora de autorizar. Quem olha a conferência vê
    "CNN Brasil Zz82 — parece com cnnbrasilzz82 (perfil de rede)" e decide: ou
    desmarca e vai fundir pela fila, ou autoriza porque sabe que são dois atores.
    """
    ja = Instituicao(
        nome="cnnbrasilzz82",
        nome_normalizado=normalizar("cnnbrasilzz82"),
        tipo="perfil_rede",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("CNN Brasil Zz82"))

    (novo,) = reco.novos
    assert novo.nome == "CNN Brasil Zz82"
    #: O PARECIDO ATRAVESSA O TIPO: é o caso dos 59 pares `perfil_rede`+`veiculo`.
    assert [(p.nome, p.tipo) for p in novo.parecidos] == [
        ("cnnbrasilzz82", "perfil_rede")
    ]


def test_reconhecer_NAO_aponta_parecido_quando_nao_ha(sessao):
    """Vazio é resposta, e não lista com o menos-ruim.

    Oferecer o menos parecido de uma lista sem nada parecido é pior que não
    oferecer, porque quem autoriza confia na sugestão — é o mesmo argumento que
    `GrupoDeDivergencia.sugestoes` já carrega na importação de agendas.
    """
    reco = reconhecer(sessao, _da_planilha("Veículo Sem Parecido Zz83"))

    (novo,) = reco.novos
    assert novo.parecidos == ()


def test_o_parecido_NAO_impede_a_criacao(sessao):
    """Ele informa; a decisão continua sendo de quem autoriza.

    A SEMELHANÇA NÃO PROVA IDENTIDADE, e o módulo da fila registra o
    contraexemplo: `Diário SM` e `Diários M` coincidem na chave achatada e podem
    ser dois veículos. Bloquear a criação faria a máquina decidir o que o próprio
    código diz que só gente decide.
    """
    ja = Instituicao(
        nome="DiarioSmZz84",
        nome_normalizado=normalizar("DiarioSmZz84"),
        tipo="veiculo",
    )
    sessao.add(ja)
    sessao.flush()

    reco = reconhecer(sessao, _da_planilha("Diario Sm Zz84"))
    criar(sessao, reco.novos)
    sessao.flush()

    quantos = sessao.scalar(
        select(func.count()).select_from(Instituicao).where(
            Instituicao.nome.in_(("DiarioSmZz84", "Diario Sm Zz84"))
        )
    )
    assert quantos == 2, "a criação autorizada tem de acontecer"
