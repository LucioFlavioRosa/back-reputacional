"""A fila do mesmo ator cadastrado duas vezes, e as duas respostas.

TRÊS COISAS MUDARAM EM 11/10/2026, pelo princípio do dono do produto — "qualquer
fonte de dados tem acesso à mesma base de instituições e interlocutores... o BTG
podemos ter acesso em rede social, em reunião de investimento ou imprensa, mas ele
continua sendo um só":

* a fila olha QUALQUER TIPO, e não só `perfil_rede` como origem;
* o HOMÔNIMO EXATO VOLTOU. O cabeçalho antigo dizia que ele era "da `0077`, que
  funde sem perguntar" — e a `0077` escreveu que a ingestão não recriaria o par. A
  Clipei recriou 22 (a `0084` fundiu), e as 4 que sobram foram feitas por GENTE no
  CRM: ALMG, ANA, BNDES e Itaú BBA. Nenhuma migration vai fundi-las, porque "quem
  decide como enquadrar é o time";
* a comparação ganhou a SEMELHANÇA, além da chave achatada — é o caso "Valor"
  contra "o Valor", que o dono do produto deu e que nenhuma das duas chaves pegava.

E SEMELHANÇA NÃO É IDENTIDADE, que é a razão de nada fundir sozinho: `Diário SM` e
`Diários M` casam na chave achatada, e `bmc.news` casa com DOIS veículos.

O QUE ESTES TESTES PROTEGEM:

* a fila mostra o par — chave achatada igual, ou semelhança acima do corte —, com
  as menções de cada lado (é o número que diz qual é a linha com história), e com
  o TIPO de quem vai sair;
* e NÃO mostra: o par que alguém já declarou distinto, o perfil ligado a uma
  pessoa do CRM, nem o nome apenas parecido de longe (o corte é medido);
* a pergunta aparece UMA vez, ancorada em quem sai, por uma ordem TOTAL — sem o
  `id` no desempate, os pares do CRM desapareciam da fila;
* a fusão move as menções, faz o sobrevivente HERDAR o que ele não tem, e RECUSA
  quando os dois discordam num campo;
* a fusão RECUSA o caminho inverso — apagar a linha com história dentro da linha
  crua —, pela mesma regra que ancora a fila;
* "são atores diferentes" tira o par da fila, nas duas ordens, e clicar duas
  vezes não é erro.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import (
    AtorDistinto,
    Instituicao,
    InstituicaoApelido,
    Interlocutor,
)
from app.casos_de_uso import atores_duplicados
from app.dominio.erros import RegraViolada
from app.dominio.texto import normalizar
from main import app
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


@pytest.fixture
def bites(sessao) -> ScoreFonte:
    return sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "bites"))


def _cadastrar(sessao, nome: str, tipo: str, **extra) -> Instituicao:
    registro = Instituicao(
        nome=nome, nome_normalizado=normalizar(nome), tipo=tipo, **extra
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _mencao(sessao, dono: Instituicao, fonte: ScoreFonte) -> None:
    sessao.add(
        Mencao(
            fonte_id=fonte.id,
            mes=date(2026, 8, 1),
            data=date(2026, 8, 3),
            sentimento="neg",
            veiculo=dono.nome,
            instituicao_id=dono.id,
        )
    )
    sessao.flush()


def _o_par_esta_na_fila(sessao, um, outro) -> bool:
    """O par apareceu na fila, de qualquer lado.

    A ORIENTAÇÃO DA PERGUNTA É REGRA SEPARADA (`_esta_do_lado_que_pergunta`), e os
    testes da ABRANGÊNCIA querem saber se o par entrou — não de qual lado. Afirmar
    o lado neles faria cair por um motivo que não é o deles, quando alguém mexesse
    na ordenação.
    """
    for pergunta in atores_duplicados.listar(sessao):
        ids = {pergunta.id} | {c.id for c in pergunta.candidatos}
        if um.id in ids and outro.id in ids:
            return True
    return False


def _interacao(sessao, dono: Instituicao, **extra) -> None:
    """Uma agenda registrada para a instituição — a origem `crm` da fila."""
    from uuid import uuid4

    from sqlalchemy import text

    from app.banco.tabelas_acesso import Usuario
    from app.banco.tabelas_interacoes import InteracaoRegistro

    sufixo = uuid4().hex[:8]
    autor = Usuario(
        entra_object_id=f"origens-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome="Autor das origens",
        acesso_irrestrito=True,
    )
    sessao.add(autor)
    sessao.flush()
    sessao.add(
        InteracaoRegistro(
            frente_id=sessao.scalar(text("select id from frente limit 1")),
            data_interacao=date(2026, 8, 4),
            instituicao_id=dono.id,
            uf="SP",
            status_id=sessao.scalar(text("select id from status limit 1")),
            pauta="conversa registrada",
            criado_por=autor.id,
            **extra,
        )
    )
    sessao.flush()


def _apelidos(sessao, chave: str) -> list[InstituicaoApelido]:
    """As linhas de apelido daquele nome. A chave da tabela é o PAR (nome,
    instituição), então um nome pode ter mais de uma — é assim que a
    ambiguidade fica registrada em vez de destruída."""
    return list(
        sessao.scalars(
            select(InstituicaoApelido).where(
                InstituicaoApelido.nome_normalizado == chave
            )
        )
    )


def _na_fila(sessao, qual) -> atores_duplicados.Duplicado | None:
    return next((d for d in atores_duplicados.listar(sessao) if d.id == qual), None)


# -- a chave da semelhança -------------------------------------------------------


def test_a_chave_junta_o_handle_e_o_nome():
    achatar = atores_duplicados.achatar_para_comparar

    assert achatar("valoreconomico") == achatar("Valor Econômico")
    assert achatar("gazeta_de_piracicaba") == achatar("Gazeta de Piracicaba")
    assert achatar("bmc.news") == achatar("BM&C News")
    #: E NÃO JUNTA O QUE É SÓ PARECIDO NO OLHO.
    assert achatar("Diário SM") != achatar("Diário de Santa Maria")


def test_a_chave_NAO_substitui_a_de_gravacao():
    #: `normalizar` carrega a unicidade do cadastro, e nela `valoreconomico` e
    #: `valor economico` são dois cadastros legítimos. Confundir as duas faria
    #: a gravação fundir sozinha o que esta fila existe para perguntar.
    assert normalizar("Valor Econômico") != atores_duplicados.achatar_para_comparar(
        "Valor Econômico"
    )


# -- a fila ----------------------------------------------------------------------


def test_a_fila_mostra_o_par_parecido_com_as_mencoes(sessao, bites):
    perfil = _cadastrar(sessao, "valorzz60", "perfil_rede", cargo="Imprensa")
    veiculo = _cadastrar(sessao, "Valor Zz60", "veiculo")
    _mencao(sessao, perfil, bites)
    for _ in range(3):
        _mencao(sessao, veiculo, bites)

    achado = _na_fila(sessao, perfil.id)

    assert achado is not None
    assert achado.mencoes == 1
    assert [(c.nome, c.mencoes) for c in achado.candidatos] == [("Valor Zz60", 3)]


def test_a_fila_MOSTRA_o_homonimo_exato(sessao):
    """O nome igual voltou a ser pergunta, e a premissa que o excluía caiu duas vezes.

    ESTE TESTE AFIRMAVA O CONTRÁRIO, com a razão de então: "nome igual por
    `nome_normalizado` é da `0077`, que funde sem perguntar. Se aparecesse aqui, a
    tela pediria decisão sobre o que já foi decidido".

    PRIMEIRA QUEDA: a `0077` escreveu que a ingestão não recriaria o par, e a
    Clipei recriou 22 — ela filtrava `tipo = 'veiculo'` e não via o perfil que a
    Bites havia criado. A `0084` fundiu os 22.

    SEGUNDA QUEDA, e é a que importa para o futuro: as 4 duplicatas que sobram
    foram feitas POR GENTE no CRM — ALMG e ANA e BNDES como `entidade`+`orgao`,
    Itaú BBA como `entidade`+`investidor`. Nenhuma migration vai fundi-las, porque
    "quem decide como enquadrar é o time que está registrando a primeira vez ou
    editando posteriormente". Fora da fila, elas não aparecem em lugar nenhum.
    """
    perfil = _cadastrar(sessao, "Exame Zz61", "perfil_rede")
    _cadastrar(sessao, "exame zz61", "veiculo")

    assert _na_fila(sessao, perfil.id) is not None


def test_a_fila_pergunta_sobre_DOIS_CADASTROS_DO_CRM(sessao):
    """O caso real que ficava invisível: `entidade` + `orgao`, feitos à mão.

    São três na base — ALMG, ANA e BNDES — mais Itaú BBA como
    `entidade`+`investidor`. A fila só olhava `perfil_rede` como origem, então
    nenhum deles aparecia; e como a ingestão não os criou, nenhuma migration os
    funde. Eram quatro perguntas que ninguém via.
    """
    uma = _cadastrar(sessao, "Agência Zz71", "entidade")
    outra = _cadastrar(sessao, "Agencia Zz71", "orgao")

    assert _o_par_esta_na_fila(sessao, uma, outra), "o par do CRM não entrou na fila"


def test_a_fila_pergunta_sobre_DOIS_VEICULOS(sessao):
    """`Neofeed` e `Neo Feed` são dois veículos — e são o mesmo ator.

    MEDIDO: são 5 pares `veiculo`+`veiculo` de chave achatada igual na base, entre
    eles `Neofeed`/`Neo Feed` e `LatinFinance`/`Latin Finance`. O comentário antigo
    dizia que "dois veículos de imprensa com nomes parecidos são outra conversa —
    essa base é curada à mão", e a medida mostra que a curadoria à mão também
    duplica.

    E O ÍNDICE ÚNICO POR NOME NÃO PEGARIA ESTES: `nome_normalizado` de "Neofeed" e
    de "Neo Feed" são diferentes. É a fila que pega.
    """
    um = _cadastrar(sessao, "NeoFeedZz72", "veiculo")
    outro = _cadastrar(sessao, "Neo Feed Zz72", "veiculo")

    assert _o_par_esta_na_fila(sessao, um, outro), "o par de veículos não entrou na fila"


def test_a_fila_pergunta_sobre_o_ARTIGO_que_muda_a_chave(sessao):
    """"Valor" contra "o Valor" — o caso que o dono do produto deu.

    NENHUMA DAS DUAS CHAVES PEGA: `normalizar` dá "valor zz73" e "o valor zz73";
    `achatar_para_comparar` dá "valorzz73" e "ovalorzz73". São chaves diferentes
    nos dois casos, e sem a SEMELHANÇA o par passa batido.

    É o que ele pediu: "ao dar flexibilidade ao usuário preciso ter mais garantias
    na comparação, já que o usuário pode mudar muita coisa que nós não prevemos".
    """
    um = _cadastrar(sessao, "Valor Zz73", "investidor")
    outro = _cadastrar(sessao, "o Valor Zz73", "veiculo")

    assert _o_par_esta_na_fila(sessao, um, outro), (
        "o artigo no começo do nome escondeu a duplicata"
    )


def test_a_fila_NAO_pergunta_sobre_nome_apenas_PARECIDO_de_longe(sessao):
    """O outro lado do corte, e é ele que mantém a fila olhável.

    MEDIDO no cadastro de 3.785 nomes ativos: corte 0,90 dá 231 pares, 0,85 dá 494
    e 0,80 dá 1.512. O argumento da `0078` vale aqui — "a fila deixa de ser fila e
    passa a ser ruído, e o ruído é o que faz ninguém olhar".

    Sem esta asserção, baixar o corte "para não perder nada" não quebraria nada
    visível, e a fila triplicaria.
    """
    um = _cadastrar(sessao, "Gazeta do Povo Zz74", "veiculo")
    outro = _cadastrar(sessao, "Gazeta de Alagoas Zz74", "veiculo")

    assert not _o_par_esta_na_fila(sessao, um, outro)


def test_a_fila_NAO_mostra_o_perfil_ligado_a_uma_pessoa(sessao):
    pessoa = Interlocutor(nome="Fulano Zz62", nome_normalizado=normalizar("Fulano Zz62"))
    sessao.add(pessoa)
    sessao.flush()
    perfil = _cadastrar(sessao, "fulanozz62", "perfil_rede", interlocutor_id=pessoa.id)
    _cadastrar(sessao, "Fulano Zz62 ", "veiculo")

    #: O sobrevivente não pode herdar a ligação (CHECK
    #: `instituicao_pessoa_so_de_perfil`), e desfazer escolha de gente não é
    #: fusão, é perda.
    assert _na_fila(sessao, perfil.id) is None

    #: CONTRAPESO: sem a ligação, o par É pergunta — o teste acima não está
    #: passando porque nada apareceria de todo jeito.
    perfil.interlocutor_id = None
    sessao.flush()
    assert _na_fila(sessao, perfil.id) is not None


def test_a_fila_NAO_repete_o_que_alguem_ja_decidiu(sessao):
    perfil = _cadastrar(sessao, "diariosmzz63", "perfil_rede")
    outro = _cadastrar(sessao, "Diários M Zz63", "veiculo")
    #: mesma chave achatada? não — este par é só para o fluxo de decisão.
    outro.nome = "Diario Sm Zz63"
    outro.nome_normalizado = normalizar("Diario Sm Zz63")
    sessao.flush()
    assert _na_fila(sessao, perfil.id) is not None

    atores_duplicados.declarar_distintos(sessao, um=perfil.id, outro=outro.id)

    assert _na_fila(sessao, perfil.id) is None


def test_o_veiculo_NAO_entra_na_fila_como_pergunta(sessao):
    #: Dois veículos de nome parecido são outra conversa: essa base é curada à
    #: mão, e o par nasce da ingestão de redes sociais. A fila pergunta sobre o
    #: perfil.
    um = _cadastrar(sessao, "jornalzz64", "veiculo")
    _cadastrar(sessao, "Jornal Zz64", "veiculo")

    assert _na_fila(sessao, um.id) is None

    #: CONTRAPESO: é o TIPO que o tira da fila, e não a semelhança fraca.
    um.tipo = "perfil_rede"
    sessao.flush()
    assert _na_fila(sessao, um.id) is not None


def test_a_mesma_pergunta_aparece_UMA_VEZ(sessao, bites):
    """Dois perfis parecidos davam DUAS linhas na fila.

    Medido na pilha: 144 linhas para ~100 perguntas, porque `AC 24 Horas →
    ac24horas` e `ac24horas → AC 24 Horas` são a mesma dúvida em dois pontos da
    lista alfabética. Responder uma resolvia as duas — mas quem abre a tela lê
    o dobro do trabalho que existe, e o contador mente.
    """
    magro = _cadastrar(sessao, "ac24horaszz72", "perfil_rede")
    gordo = _cadastrar(sessao, "AC 24 Horas Zz72", "perfil_rede")
    _mencao(sessao, gordo, bites)
    _mencao(sessao, gordo, bites)
    _mencao(sessao, magro, bites)

    fila = atores_duplicados.listar(sessao)
    deste_par = [
        d for d in fila if d.id in {magro.id, gordo.id}
    ]

    assert len(deste_par) == 1
    #: E ANCORADA EM QUEM VAI SUMIR: o lado com menos menções pergunta, a linha
    #: com história sobrevive — a mesma orientação que `fundir` exige.
    assert deste_par[0].id == magro.id
    assert [c.id for c in deste_par[0].candidatos] == [gordo.id]


def test_com_VEICULO_do_outro_lado_a_pergunta_nasce_do_perfil(sessao, bites):
    #: Aqui não há escolha de lado: só o perfil de rede entra em outro
    #: cadastro. Mesmo com MAIS menções que o veículo, é ele que pergunta.
    perfil = _cadastrar(sessao, "valorzz73", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz73", "veiculo")
    for _ in range(5):
        _mencao(sessao, perfil, bites)

    achado = _na_fila(sessao, perfil.id)

    assert achado is not None
    assert [c.id for c in achado.candidatos] == [veiculo.id]


def test_a_fila_diz_DE_ONDE_vem_cada_lado(sessao, bites):
    """As origens de cada cadastro, que é a evidência da duplicata.

    O PEDIDO DO DONO DO PRODUTO, na letra: "o valor economico pode vim de vários
    meios, pode vim do crm, pode vim de midias sociais, pode vim de mercado,
    enfim, pode ter várias fontes distintas, mas a instituição é a mesma. Então
    isso deve ficar bem claro".

    POR QUE ISSO É DADO E NÃO ENFEITE. Quem decide olhava dois nomes parecidos e
    duas contagens — e o que explica a duplicata estava de fora: um lado chegou
    pelo clipping, o outro pelo CRM. É a resposta para "por que existem dois?".

    DUAS LEITURAS DIFERENTES, e o teste cobre as duas: a menção tem lente (por
    `score_fonte`), a interação do CRM não tem — e por isso ela aparece como `crm`
    em vez de `institucional`. Dizer `institucional` confundiria "tem reunião
    registrada" com "tem menção na lente institucional".
    """
    clipei = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))

    perfil = _cadastrar(sessao, "valoreconomicozz71", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Econômico Zz71", "veiculo")
    #: O VEÍCULO VEM DE DUAS LENTES: clipping (imprensa) e Bites (sociedade).
    _mencao(sessao, veiculo, clipei)
    _mencao(sessao, veiculo, bites)

    #: E O PERFIL TEM RELACIONAMENTO REGISTRADO no CRM.
    _interacao(sessao, perfil)

    achado = _na_fila(sessao, perfil.id)

    assert achado is not None
    assert achado.origens == (atores_duplicados.ORIGEM_DO_CRM,)
    deste_lado = next(c for c in achado.candidatos if c.id == veiculo.id)
    assert deste_lado.origens == ("imprensa", "sociedade")


def test_a_agenda_ESCONDIDA_nao_vira_origem_crm(sessao):
    """A existência de relacionamento no CRM não escapa pela fila.

    ACHADO ALTA DE REVISÃO. A primeira versão marcava `crm` para QUALQUER
    `interacao_registro`, e esta listagem exige apenas a permissão do DIRETÓRIO:
    quem vê o diretório passava a inferir que a Aegea tem relacionamento com uma
    instituição mesmo quando a agenda foi tirada da vista, arquivada ou marcada
    como sensível. O docstring de `so_interacoes_visiveis` diz o porquê — o nome
    da instituição de uma agenda é "a informação que o CRM guarda com mais
    cuidado".

    OS TRÊS ESTADOS, num teste só: cada um esconde por uma razão diferente, e uma
    implementação que pegasse só o arquivamento (como cinco das seis consultas do
    Score faziam antes da regra única) passaria num teste de um estado.
    """
    escondidos = _cadastrar(sessao, "Escondidozz75", "entidade")
    _cadastrar(sessao, "Escondido Zz75", "orgao")
    _interacao(sessao, escondidos, visivel=False)
    _interacao(sessao, escondidos, sensivel=True)
    _interacao(sessao, escondidos, arquivado_em=datetime(2026, 9, 1, tzinfo=UTC))

    origens = atores_duplicados._origens_por_instituicao(sessao)

    assert origens.get(escondidos.id, ()) == ()

    #: O CONTROLE: uma agenda normal na MESMA instituição vira `crm`. Sem ele,
    #: um filtro que escondesse tudo passaria neste teste.
    _interacao(sessao, escondidos)
    assert atores_duplicados._origens_por_instituicao(sessao)[escondidos.id] == (
        atores_duplicados.ORIGEM_DO_CRM,
    )


def test_o_cadastro_SEM_registro_nenhum_nao_inventa_origem(sessao):
    """Zero registros é tupla vazia, e não uma origem chutada.

    O CONTROLE DO TESTE ACIMA: sem ele, uma implementação que devolvesse sempre
    `('imprensa',)` passaria no teste do veículo e mentiria sobre as 4 duplicatas
    do CRM (ALMG, ANA, BNDES, Itaú BBA), que têm zero menções.
    """
    um = _cadastrar(sessao, "Almgzz72", "entidade")
    outro = _cadastrar(sessao, "ALMG Zz72", "orgao")

    #: QUAL DOS DOIS PERGUNTA é a ordem total `(menções, nome, id)` — com zero
    #: menções nos dois, quem ancora depende do `id`, que é sorteado. O teste é
    #: sobre as origens, não sobre o lado: pega o que estiver na fila.
    achado = _na_fila(sessao, um.id) or _na_fila(sessao, outro.id)

    assert achado is not None
    assert achado.origens == ()
    assert all(c.origens == () for c in achado.candidatos)


# -- a fusão ---------------------------------------------------------------------


def test_a_fusao_leva_as_mencoes_e_apaga_o_perfil(sessao, bites):
    perfil = _cadastrar(sessao, "valorzz65", "perfil_rede", cargo="Imprensa")
    veiculo = _cadastrar(sessao, "Valor Zz65", "veiculo")
    _mencao(sessao, perfil, bites)
    _mencao(sessao, veiculo, bites)
    id_do_perfil, id_do_veiculo = perfil.id, veiculo.id

    atores_duplicados.fundir(
        sessao, que_sai_id=id_do_perfil, sobrevivente_id=id_do_veiculo
    )

    sobrou = sessao.scalar(
        select(func.count()).select_from(Instituicao).where(Instituicao.id == id_do_perfil)
    )
    assert sobrou == 0
    juntas = sessao.scalar(
        select(func.count()).select_from(Mencao).where(Mencao.instituicao_id == id_do_veiculo)
    )
    assert juntas == 2


def test_a_fusao_RECUSA_apagar_o_veiculo_curado(sessao):
    """O caminho inverso não é oferecido, e a recusa é do SERVIDOR.

    O veículo é a linha com categoria, subcategoria, UF e frente, e com o nome
    escrito por gente. Fundir ele dentro do handle do fornecedor perderia a
    curadoria — e quem clica numa tela de duplicados não está pedindo isso.

    A GUARDA MUDOU DE FORMA EM 11/10/2026, não de existência. Era `if perfil.tipo
    != TIPO_DE_ORIGEM`; ao abrir a fusão para todos os tipos eu a troquei por "a
    ordem da fila garante", e este teste caiu com razão: a ordem da fila é a TELA, e
    esconder o botão é conveniência — um `curl` basta.

    AGORA É A MESMA REGRA DA FILA (`_esta_do_lado_que_pergunta`), consultada pelos
    dois lugares: a fila para ancorar a pergunta, a fusão para recusar o inverso.
    """
    perfil = _cadastrar(sessao, "valorzz66", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz66", "veiculo")

    with pytest.raises(RegraViolada, match="deve sobreviver"):
        atores_duplicados.fundir(
            sessao, que_sai_id=veiculo.id, sobrevivente_id=perfil.id
        )


def test_a_fusao_ACEITA_a_escolha_de_gente_CONTRA_a_proposta(sessao, bites):
    """A guarda é a PROPOSTA da fila, e não a sentença.

    O PEDIDO DO DONO DO PRODUTO: "não basta termos uma opção de dizer se são ou não
    o mesmo, além de mostrar quais podem se juntar temos que dizer qual é o real
    para ser considerado na unificação".

    O teste acima prova que a direção inversa é recusada SEM o pedido explícito —
    é o que protege o clique errado e o `curl` distraído. Este prova que, dito de
    propósito, a escolha de quem conhece o ator vale.

    E MEDE O QUE ISSO CUSTA: o sobrevivente mantém o NOME dele. `nome` não está em
    `CAMPOS_QUE_O_SOBREVIVENTE_HERDA`, porque trocá-lo faria a fusão virar
    renomeação — então escolher o handle como o real deixa o cadastro chamado
    `valorzz70`, com as menções do veículo dentro. A tela tem de dizer isso antes
    do clique, e por isso o teste afirma o nome e não só a contagem.
    """
    perfil = _cadastrar(sessao, "valorzz70", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz70", "veiculo", uf="SP")
    for _ in range(3):
        _mencao(sessao, veiculo, bites)
    id_do_veiculo = veiculo.id

    sobrevivente = atores_duplicados.fundir(
        sessao,
        que_sai_id=id_do_veiculo,
        sobrevivente_id=perfil.id,
        contra_a_proposta=True,
    )

    #: O VEÍCULO SAIU, e as menções dele estão no perfil.
    assert sobrevivente.id == perfil.id
    assert sobrevivente.nome == "valorzz70"
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Instituicao)
            .where(Instituicao.id == id_do_veiculo)
        )
        == 0
    )
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.instituicao_id == perfil.id)
        )
        == 3
    )
    #: E A CURADORIA NÃO SE PERDE: o que o sobrevivente não tinha, ele herdou.
    assert sobrevivente.uf == "SP"


def test_a_fusao_LEVA_A_PENDENCIA_de_revisao_de_quem_sai(sessao):
    """Unir dois cadastros não responde a pergunta da conferência.

    ACHADO ALTA DE REVISÃO. A linha que sai é a pendente na maioria dos pares —
    ela nasce da subida de planilha —, e a fusão a apagava com a pendência dentro:
    o item desaparecia de "Esperando conferência" sem ninguém ter conferido nada.

    NÃO CABE EM `CAMPOS_QUE_O_SOBREVIVENTE_HERDA`, e é por isso que mora num `if`
    próprio: aquela regra é "herda o que está NULO", e `pendente_de_revisao` é
    booleano com padrão `False` — nunca seria alcançado. E pôr o campo na tupla
    faria toda fusão entre um cadastro pendente e um conferido recusar com 422.
    """
    que_sai = _cadastrar(sessao, "Pendentezz73", "perfil_rede")
    que_sai.pendente_de_revisao = True
    que_sai.motivo_da_revisao = "nasceu da planilha, ninguém conferiu"
    fica = _cadastrar(sessao, "Pendente Zz73", "veiculo")
    assert fica.pendente_de_revisao is False
    sessao.flush()

    atores_duplicados.fundir(sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id)
    sessao.flush()

    assert fica.pendente_de_revisao is True
    assert fica.motivo_da_revisao == "nasceu da planilha, ninguém conferiu"


def test_a_fusao_RECUSA_entrar_num_cadastro_DESATIVADO(sessao, bites):
    """Fundir dentro de um desativado esconderia o que está à vista.

    `ativo=false` é alguém dizendo "este cadastro sai do cadastro de agenda".
    Reativá-lo por efeito colateral de uma fusão seria decidir no lugar dessa
    pessoa, no sentido oposto; e deixá-lo desativado com as menções do outro
    dentro esconderia dado que estava aparecendo.

    A FILA NÃO ALCANÇA ESTE CASO — `listar` só olha cadastro ativo —, e é
    exatamente por isso que a guarda existe: o caminho de fora da tela.
    """
    que_sai = _cadastrar(sessao, "Ativozz74", "perfil_rede")
    _mencao(sessao, que_sai, bites)
    fica = _cadastrar(sessao, "Ativo Zz74", "veiculo")
    fica.ativo = False
    sessao.flush()

    with pytest.raises(RegraViolada, match="desativado"):
        atores_duplicados.fundir(
            sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id
        )


def test_a_fusao_RECUSA_apagar_a_linha_com_MAIS_MENCOES(sessao, bites):
    """O caso que a guarda antiga NÃO cobria, e é o ganho da regra nova.

    A guarda antiga olhava TIPO: só recusava fundir um não-perfil dentro de um
    perfil. Dois veículos passavam — e dar baixa num veículo de muitas menções
    dentro de um de poucas é a mesma perda de história, com os mesmos cliques.

    E ISTO NÃO É HIPÓTESE: medido, há 5 pares `veiculo`+`veiculo` de chave achatada
    igual na base, e a fila passou a mostrá-los.
    """
    def quantas(dono):
        return sessao.scalar(
            select(func.count()).select_from(Mencao).where(Mencao.instituicao_id == dono.id)
        )

    muitas = _cadastrar(sessao, "Neofeed Zz67", "veiculo")
    poucas = _cadastrar(sessao, "Neo Feed Zz67", "veiculo")
    for _ in range(3):
        _mencao(sessao, muitas, bites)
    _mencao(sessao, poucas, bites)
    assert quantas(muitas) == 3

    with pytest.raises(RegraViolada, match="deve sobreviver"):
        atores_duplicados.fundir(
            sessao, que_sai_id=muitas.id, sobrevivente_id=poucas.id
        )

    #: E NA DIREÇÃO CERTA FUNCIONA — senão o teste acima passaria por a fusão
    #: estar quebrada, e não pela guarda.
    atores_duplicados.fundir(sessao, que_sai_id=poucas.id, sobrevivente_id=muitas.id)
    assert quantas(muitas) == 4


def test_a_fusao_GUARDA_o_nome_que_sai_como_APELIDO(sessao):
    """O nome que some daqui continua chegando na planilha do mês que vem.

    Ver `test_reconhecer_ACHA_PELO_APELIDO_o_nome_que_a_fusao_levou`, que é o
    outro lado: aqui se grava, lá se usa. Sem os dois, a duplicata volta.
    """
    que_sai = _cadastrar(sessao, "Valor Econômico Zz76", "veiculo")
    fica = _cadastrar(sessao, "valoreconomicozz76", "perfil_rede")
    nome_que_sai = que_sai.nome_normalizado

    atores_duplicados.fundir(
        sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id, contra_a_proposta=True
    )
    sessao.flush()

    apelidos = _apelidos(sessao, nome_que_sai)
    assert len(apelidos) == 1
    assert apelidos[0].instituicao_id == fica.id
    assert apelidos[0].nome == "Valor Econômico Zz76"


def test_a_fusao_REAPONTA_os_apelidos_de_quem_sai(sessao):
    """Duas fusões encadeadas: A entra em B, e depois B entra em C.

    SEM REAPONTAR, o `on delete cascade` levaria o apelido de A junto com B — e o
    nome de A voltaria a não casar na subida seguinte, recriando a duplicata que
    JÁ tinha sido resolvida uma vez. Numa fila de 209 pares, fusão encadeada não
    é hipótese.
    """
    a = _cadastrar(sessao, "Jornal A Zz77", "veiculo")
    b = _cadastrar(sessao, "jornalazz77", "perfil_rede")
    c = _cadastrar(sessao, "jornalaz77", "perfil_rede")
    nome_de_a = a.nome_normalizado

    atores_duplicados.fundir(
        sessao, que_sai_id=a.id, sobrevivente_id=b.id, contra_a_proposta=True
    )
    atores_duplicados.fundir(
        sessao, que_sai_id=b.id, sobrevivente_id=c.id, contra_a_proposta=True
    )
    sessao.flush()

    apelidos = _apelidos(sessao, nome_de_a)
    assert apelidos, "o apelido de A foi embora com B"
    assert [a.instituicao_id for a in apelidos] == [c.id]


def test_o_apelido_AMBIGUO_e_REGISTRADO_e_nao_destruido(sessao):
    """Dois atores com o MESMO nome, fundidos em sobreviventes diferentes.

    DUAS VERSÕES ANTES DESTA, e as duas estavam erradas por motivos opostos:

    * "o mais recente vence" mandava as menções que historicamente eram do
      PRIMEIRO ator para o segundo — redirecionamento silencioso de dossiê;
    * "nome ambíguo não aponta para ninguém" apagava o apelido — e aí o nome
      saía de `nomes_da_lista`, e a reconciliação tirava as menções dele do
      Mercado em TODOS os meses fechados. Uma fusão sem relação com mercado
      mudava a série histórica.

    A CHAVE É O PAR (nome, instituição), então as duas linhas coexistem: a
    ambiguidade fica REGISTRADA. Cada leitura aplica a regra dela — ver
    `test_o_apelido_de_DUAS_linhas_nao_resolve_o_ator` e
    `test_o_apelido_AMBIGUO_continua_valendo_para_a_LISTA`.
    """
    um = _cadastrar(sessao, "Ambíguo Zz79", "entidade")
    outro = _cadastrar(sessao, "Ambíguo Zz79", "orgao")
    chave = um.nome_normalizado
    assert chave == outro.nome_normalizado
    casa_de_um = _cadastrar(sessao, "Casa Um Zz79", "entidade")
    casa_de_outro = _cadastrar(sessao, "Casa Outra Zz79", "entidade")

    atores_duplicados.fundir(
        sessao, que_sai_id=um.id, sobrevivente_id=casa_de_um.id, contra_a_proposta=True
    )
    atores_duplicados.fundir(
        sessao,
        que_sai_id=outro.id,
        sobrevivente_id=casa_de_outro.id,
        contra_a_proposta=True,
    )
    sessao.flush()

    donos = set(
        sessao.scalars(
            select(InstituicaoApelido.instituicao_id).where(
                InstituicaoApelido.nome_normalizado == chave
            )
        )
    )
    assert donos == {casa_de_um.id, casa_de_outro.id}


def test_a_MESMA_fusao_duas_vezes_nao_repete_o_apelido(sessao):
    #: A chave do par recusaria a repetição com erro de integridade; a guarda
    #: existe para a segunda fusão do mesmo par (que acontece quando alguém
    #: refaz o gesto) não virar 500.
    que_sai = _cadastrar(sessao, "Repetido Zz81", "entidade")
    fica = _cadastrar(sessao, "Casa Repetida Zz81", "entidade")
    chave = que_sai.nome_normalizado

    atores_duplicados.fundir(
        sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id, contra_a_proposta=True
    )
    sessao.flush()
    #: O MESMO NOME de novo, noutro cadastro, para o MESMO sobrevivente.
    de_novo = _cadastrar(sessao, "Repetido Zz81", "orgao")
    atores_duplicados.fundir(
        sessao, que_sai_id=de_novo.id, sobrevivente_id=fica.id, contra_a_proposta=True
    )
    sessao.flush()

    quantas = sessao.scalar(
        select(func.count())
        .select_from(InstituicaoApelido)
        .where(InstituicaoApelido.nome_normalizado == chave)
    )
    assert quantas == 1


def test_a_fusao_RECUSA_tirar_um_veiculo_da_LISTA_da_lente(sessao):
    """Fundir um veículo de lista dentro de quem não é veículo muda o índice.

    ACHADO ALTO DE REVISÃO. `nomes_da_lista` exige `tipo='veiculo'`. A fusão faz o
    sobrevivente herdar a SUBCATEGORIA, mas nunca o `tipo` — ele é identidade.
    Então o cadastro ficava com a classificação certa e o tipo errado, e saía da
    lente Mercado sem erro e sem aviso. Com a peça que faz a lista valer para o
    passado, a saída ainda apagaria as menções dele de todos os meses.
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
    veiculo = _cadastrar(
        sessao, "Valor Econômico Zz80", "veiculo", subcategoria_publico_id=alvo
    )
    perfil = _cadastrar(sessao, "valoreconomicozz80", "perfil_rede")

    with pytest.raises(RegraViolada, match="lista de veículos"):
        atores_duplicados.fundir(
            sessao,
            que_sai_id=veiculo.id,
            sobrevivente_id=perfil.id,
            contra_a_proposta=True,
        )

    #: E A OUTRA DIREÇÃO FUNCIONA — senão o teste passaria por a fusão estar
    #: quebrada, e não pela guarda.
    atores_duplicados.fundir(
        sessao, que_sai_id=perfil.id, sobrevivente_id=veiculo.id
    )
    sessao.flush()
    assert sessao.get(Instituicao, veiculo.id) is not None


def test_o_nome_IGUAL_nao_vira_apelido(sessao):
    #: `ALMG` (entidade) dentro de `ALMG` (órgão) não tira nome nenhum de
    #: circulação — a linha só ocuparia a chave.
    que_sai = _cadastrar(sessao, "ALMG Zz78", "entidade")
    fica = _cadastrar(sessao, "ALMG Zz78", "orgao")
    chave = que_sai.nome_normalizado
    assert chave == fica.nome_normalizado

    atores_duplicados.fundir(
        sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id, contra_a_proposta=True
    )
    sessao.flush()

    assert _apelidos(sessao, chave) == []


def test_a_fusao_recusa_o_perfil_ligado_a_uma_pessoa(sessao):
    pessoa = Interlocutor(nome="Fulano Zz67", nome_normalizado=normalizar("Fulano Zz67"))
    sessao.add(pessoa)
    sessao.flush()
    perfil = _cadastrar(sessao, "fulanozz67", "perfil_rede", interlocutor_id=pessoa.id)
    veiculo = _cadastrar(sessao, "Fulano Zz67", "veiculo")

    with pytest.raises(RegraViolada, match="pessoa"):
        atores_duplicados.fundir(
            sessao, que_sai_id=perfil.id, sobrevivente_id=veiculo.id
        )


def test_a_fusao_recusa_o_cadastro_com_ele_mesmo(sessao):
    perfil = _cadastrar(sessao, "valorzz68", "perfil_rede")

    with pytest.raises(RegraViolada, match="ele mesmo"):
        atores_duplicados.fundir(
            sessao, que_sai_id=perfil.id, sobrevivente_id=perfil.id
        )


def test_a_fusao_LEVA_AS_PESSOAS_do_perfil(sessao):
    #: Sem isto a exclusão bate na chave estrangeira e a fusão morre no meio,
    #: com a menção já movida.
    perfil = _cadastrar(sessao, "grupozz69", "perfil_rede")
    veiculo = _cadastrar(sessao, "Grupo Zz69", "veiculo")
    pessoa = Interlocutor(
        nome="Fulana Zz69",
        nome_normalizado=normalizar("Fulana Zz69"),
        instituicao_id=perfil.id,
    )
    sessao.add(pessoa)
    sessao.flush()

    atores_duplicados.fundir(sessao, que_sai_id=perfil.id, sobrevivente_id=veiculo.id)

    sessao.expire_all()
    assert sessao.scalar(
        select(Interlocutor.instituicao_id).where(Interlocutor.id == pessoa.id)
    ) == veiculo.id


# -- "são atores diferentes" -----------------------------------------------------


def test_o_par_distinto_e_guardado_SEM_LADO(sessao):
    um = _cadastrar(sessao, "diariozz70", "perfil_rede")
    outro = _cadastrar(sessao, "Diário Zz70", "veiculo")

    atores_duplicados.declarar_distintos(sessao, um=outro.id, outro=um.id)

    #: Gravado na ordem canônica, e a chave primária recusa a repetição.
    esquerda, direita = atores_duplicados.ordenar_o_par(um.id, outro.id)
    assert sessao.get(AtorDistinto, (esquerda, direita)) is not None


def test_declarar_DUAS_VEZES_nao_e_erro(sessao):
    um = _cadastrar(sessao, "diariozz71", "perfil_rede")
    outro = _cadastrar(sessao, "Diário Zz71", "veiculo")

    atores_duplicados.declarar_distintos(sessao, um=um.id, outro=outro.id)
    atores_duplicados.declarar_distintos(
        sessao, um=outro.id, outro=um.id, motivo="jornais diferentes"
    )

    quantos = sessao.scalar(select(func.count()).select_from(AtorDistinto))
    assert quantos == 1
    esquerda, direita = atores_duplicados.ordenar_o_par(um.id, outro.id)
    assert sessao.get(AtorDistinto, (esquerda, direita)).motivo == "jornais diferentes"


# -- as rotas --------------------------------------------------------------------


@pytest.fixture
def cliente(sessao):
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{**padrao.model_dump(), "auth_mock": True, "auth_mock_perfil": "plataforma_edicao"}
    )
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    feito = TestClient(app)
    try:
        yield feito
    finally:
        app.dependency_overrides.clear()


def test_a_rota_lista_a_fila(cliente, sessao, bites):
    perfil = _cadastrar(sessao, "valorzz80", "perfil_rede", cargo="Imprensa")
    veiculo = _cadastrar(sessao, "Valor Zz80", "veiculo")
    _mencao(sessao, veiculo, bites)

    resposta = cliente.get("/api/instituicoes/duplicados")

    assert resposta.status_code == 200, resposta.text
    achado = next(d for d in resposta.json() if d["id"] == str(perfil.id))
    assert achado["cargo"] == "Imprensa"
    assert achado["candidatos"][0]["nome"] == "Valor Zz80"
    assert achado["candidatos"][0]["mencoes"] == 1


def test_a_rota_funde(cliente, sessao, bites):
    perfil = _cadastrar(sessao, "valorzz81", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz81", "veiculo")
    _mencao(sessao, perfil, bites)

    resposta = cliente.post(
        f"/api/instituicoes/{perfil.id}/fundir",
        json={"sobrevivente_id": str(veiculo.id)},
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["nome"] == "Valor Zz81"
    sessao.expire_all()
    assert (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.instituicao_id == veiculo.id)
        )
        == 1
    )


def test_a_rota_RECUSA_o_caminho_inverso(cliente, sessao):
    perfil = _cadastrar(sessao, "valorzz82", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz82", "veiculo")

    resposta = cliente.post(
        f"/api/instituicoes/{veiculo.id}/fundir",
        json={"sobrevivente_id": str(perfil.id)},
    )

    #: A recusa fala de cadastro, e diz o gesto certo.
    assert resposta.status_code == 422, resposta.text
    assert "deve sobreviver" in resposta.text
    assert "quem sai vai na URL" in resposta.text


def test_a_rota_ACEITA_o_caminho_inverso_quando_dito_de_proposito(cliente, sessao, bites):
    """O mesmo pedido do teste acima, com a escolha explícita — e 200.

    É O PEDIDO DO DONO DO PRODUTO ("temos que dizer qual é o real"), e o par de
    testes é o contrato inteiro: sem o campo, 422; com o campo, funde. Só um dos
    dois seria metade da regra.
    """
    perfil = _cadastrar(sessao, "valorzz84", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz84", "veiculo")
    _mencao(sessao, veiculo, bites)

    resposta = cliente.post(
        f"/api/instituicoes/{veiculo.id}/fundir",
        json={"sobrevivente_id": str(perfil.id), "contra_a_proposta": True},
    )

    assert resposta.status_code == 200, resposta.text
    #: O NOME QUE FICA É O DO SOBREVIVENTE, e é o que a tela precisa avisar antes
    #: do clique: escolher o handle como o real deixa o cadastro com o nome dele.
    assert resposta.json()["nome"] == "valorzz84"


def test_a_rota_diz_as_ORIGENS_de_cada_lado(cliente, sessao, bites):
    #: O dado novo chega à tela: sem ele, a linha mostra dois nomes parecidos e
    #: nenhuma pista de por que existem dois cadastros.
    perfil = _cadastrar(sessao, "valorzz85", "perfil_rede")
    veiculo = _cadastrar(sessao, "Valor Zz85", "veiculo")
    _mencao(sessao, veiculo, bites)

    resposta = cliente.get("/api/instituicoes/duplicados")

    assert resposta.status_code == 200, resposta.text
    achado = next(d for d in resposta.json() if d["id"] == str(perfil.id))
    assert achado["origens"] == []
    deste_lado = next(c for c in achado["candidatos"] if c["id"] == str(veiculo.id))
    assert deste_lado["origens"] == ["sociedade"]


def test_a_rota_guarda_o_par_distinto(cliente, sessao):
    perfil = _cadastrar(sessao, "diariozz83", "perfil_rede")
    outro = _cadastrar(sessao, "Diário Zz83", "veiculo")

    resposta = cliente.post(
        "/api/atores-distintos",
        json={
            "um_id": str(perfil.id),
            "outro_id": str(outro.id),
            "motivo": "jornais diferentes",
        },
    )

    assert resposta.status_code == 200, resposta.text
    esquerda, direita = atores_duplicados.ordenar_o_par(perfil.id, outro.id)
    sessao.expire_all()
    guardado = sessao.get(AtorDistinto, (esquerda, direita))
    assert guardado.motivo == "jornais diferentes"
    #: E QUEM DECIDIU fica registrado: a fusão não tem volta, e o par recusado
    #: barra fusão automática futura.
    assert guardado.decidido_por is not None


# ====================== a fusão não joga fora o cadastro de quem sai
def test_a_fusao_FAZ_O_SOBREVIVENTE_HERDAR_o_que_ele_nao_tem(sessao):
    """O cadastro de quem sai não vai para o lixo com a linha.

    O DEFEITO QUE ISTO FECHA (achado ALTA de revisão): `fundir` movia as chaves
    estrangeiras e apagava a linha. Era tolerável enquanto quem saía era o perfil
    cru do social listening — o único campo perdido era o `cargo`, que o CHECK nem
    deixa o veículo ter. Com a fusão aberta a qualquer tipo, sai um `investidor`
    com `tier` e categoria de público, e esses campos sumiam.

    E NOS PARES DO CRM A PERDA SERIA POR SORTEIO: `ALMG` (entidade) e `ALMG`
    (orgao) têm zero menções e o mesmo nome, então quem sai é decidido pelo UUID.
    Perder a categoria de público por sorteio é inaceitável — é ela que torna a
    instituição visível para a taxonomia do Score.
    """
    que_sai = _cadastrar(sessao, "Herdeiro Zz91", "perfil_rede")
    que_sai.uf = "RS"
    que_sai.tier = 2
    fica = _cadastrar(sessao, "Herdeiro Zz91 ", "veiculo")
    assert fica.uf is None and fica.tier is None
    sessao.flush()

    atores_duplicados.fundir(sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id)
    sessao.flush()

    assert fica.uf == "RS"
    assert fica.tier == 2


def test_a_fusao_RECUSA_quando_os_dois_discordam(sessao):
    """Dois valores preenchidos e diferentes são duas afirmações de gente.

    ESCOLHER UMA EM SILÊNCIO é o chute calado que esta semana cobrou três vezes. E
    escolher a do sobrevivente só porque ele é o sobrevivente seria escolher por
    sorteio nos pares de zero menções, onde quem sai é decidido pelo UUID.

    A RECUSA DIZ QUAIS CAMPOS DIVERGEM, senão "não deu" manda a pessoa procurar.
    """
    que_sai = _cadastrar(sessao, "Discordante Zz92", "perfil_rede")
    que_sai.tier = 1
    fica = _cadastrar(sessao, "Discordante Zz92 ", "veiculo")
    fica.tier = 3
    sessao.flush()

    with pytest.raises(RegraViolada, match="tier"):
        atores_duplicados.fundir(
            sessao, que_sai_id=que_sai.id, sobrevivente_id=fica.id
        )

    #: E NADA FOI ESCRITO: a recusa vem antes de qualquer `update`.
    assert fica.tier == 3
    assert sessao.get(Instituicao, que_sai.id) is not None


def test_a_fila_DIZ_O_TIPO_de_quem_vai_sair(sessao):
    """Sem isto a tela mentia, e mentia no campo que mais importa.

    A tela escrevia "Perfil de rede" fixo para o lado que sai — correto enquanto a
    fila só olhava `perfil_rede`. Com a fila aberta a todos, `ALMG` (entidade) +
    `ALMG` (orgao) fazia a tela dizer que ia apagar um perfil de rede, e quem
    decide lia o tipo errado do registro que desaparece.
    """
    uma = _cadastrar(sessao, "Tipada Zz93", "entidade")
    outra = _cadastrar(sessao, "Tipada Zz93 ", "orgao")

    perguntas = [
        d for d in atores_duplicados.listar(sessao) if d.id in {uma.id, outra.id}
    ]

    assert len(perguntas) == 1
    (pergunta,) = perguntas
    #: O TIPO É O DE QUEM SAI, e não um fixo.
    esperado = uma.tipo if pergunta.id == uma.id else outra.tipo
    assert pergunta.tipo == esperado
    assert pergunta.tipo in ("entidade", "orgao")
