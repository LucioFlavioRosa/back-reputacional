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

from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import (
    AtorDistinto,
    Instituicao,
    InstituicaoApelido,
    Interlocutor,
    PareamentoDaFila,
    ParSemelhante,
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
    for pergunta in _fila(sessao):
        ids = {pergunta.id} | {c.id for c in pergunta.candidatos}
        if um.id in ids and outro.id in ids:
            return True
    return False


def _fila(sessao) -> list[atores_duplicados.Duplicado]:
    """A fila com o pareamento já feito, que é a ordem da produção no TEMPO.

    O PAREAMENTO É GUARDADO desde a `0118` — era o que tirava 102,7 s da
    requisição e dava 504. `listar` não recalcula de propósito: fazê-lo
    devolveria o problema. Então um teste que cria cadastro e espera encontrá-lo
    na fila tem de recalcular primeiro, exatamente como a subida faz ao criar
    veículo (`ingerir_mencoes.ingerir`).

    AQUI E NÃO DENTRO DE `listar`: se `listar` recalculasse quando a tabela está
    vazia, o primeiro acesso depois do deploy pagaria os 102,7 s e o 504 voltaria
    — justamente no pior momento.
    """
    atores_duplicados.recalcular(sessao)
    return atores_duplicados.listar(sessao)


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
    return next((d for d in _fila(sessao) if d.id == qual), None)


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

    fila = _fila(sessao)
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

    #: O PAREAMENTO PRIMEIRO, porque a ROTA não recalcula — desde a `0118` ela só
    #: lê o que está guardado, e é isso que tirou o 504 dela. Em produção quem
    #: recalcula é a subida que cria veículo.
    atores_duplicados.recalcular(sessao)

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

    #: O PAREAMENTO PRIMEIRO, porque a ROTA não recalcula — desde a `0118` ela só
    #: lê o que está guardado, e é isso que tirou o 504 dela. Em produção quem
    #: recalcula é a subida que cria veículo.
    atores_duplicados.recalcular(sessao)

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
        d for d in _fila(sessao) if d.id in {uma.id, outra.id}
    ]

    assert len(perguntas) == 1
    (pergunta,) = perguntas
    #: O TIPO É O DE QUEM SAI, e não um fixo.
    esperado = uma.tipo if pergunta.id == uma.id else outra.tipo
    assert pergunta.tipo == esperado
    assert pergunta.tipo in ("entidade", "orgao")


# -- o pareamento guardado (0118) -----------------------------------------------


def test_a_fila_LE_o_pareamento_guardado_e_nao_recalcula(sessao):
    """O que tirou o 504: a comparação saiu da requisição.

    Um cadastro criado DEPOIS do último recálculo não aparece na fila, e isso é a
    troca declarada — a alternativa era pagar 102,7 s medidos a cada abertura da
    tela, contra os ~240 s em que o ingress corta. Quem recalcula é a subida que
    cria veículo, e o comando `recalcular_duplicados`.
    """
    um = _cadastrar(sessao, "Valor Economico zzpg", "veiculo")
    outro = _cadastrar(sessao, "valoreconomico zzpg", "perfil_rede")

    #: `listar` DIRETO e não `_na_fila`: o auxiliar recalcula antes de ler, que é
    #: o que a produção faz — e usá-lo aqui prepararia justamente o estado que
    #: este teste precisa NÃO ter.
    antes = {d.id for d in atores_duplicados.listar(sessao)}
    assert um.id not in antes
    assert outro.id not in antes

    atores_duplicados.recalcular(sessao)

    depois = {d.id for d in atores_duplicados.listar(sessao)}
    assert um.id in depois or outro.id in depois


def test_recalcular_SUBSTITUI_em_vez_de_acumular(sessao):
    """Rodar duas vezes não duplica par, e o cadastro que saiu sai da tabela."""
    um = _cadastrar(sessao, "Gazeta de Piracicaba zzpg2", "veiculo")
    outro = _cadastrar(sessao, "gazetadepiracicaba zzpg2", "perfil_rede")

    primeiro = atores_duplicados.recalcular(sessao)
    segundo = atores_duplicados.recalcular(sessao)

    assert primeiro == segundo
    pares = list(
        sessao.scalars(
            select(ParSemelhante).where(
                ParSemelhante.um_id.in_({um.id, outro.id}),
            )
        )
    )
    assert len(pares) == 1, "o par foi guardado duas vezes"

    #: DESATIVADO SAI DO PAREAMENTO no próximo recálculo: a fila é só de ativos.
    outro.ativo = False
    sessao.flush()
    atores_duplicados.recalcular(sessao)

    assert _na_fila(sessao, um.id) is None


def test_a_resposta_de_gente_tira_o_par_na_HORA_sem_recalcular(sessao):
    """É por isso que só o PAREAMENTO é guardado, e não a fila pronta.

    Se a fila fosse materializada inteira, o par respondido ficaria na tela até o
    próximo recálculo — e quem respondeu veria a mesma pergunta de novo.
    """
    um = _cadastrar(sessao, "Diario do Litoral zzpg3", "veiculo")
    outro = _cadastrar(sessao, "diariodolitoral zzpg3", "perfil_rede")
    atores_duplicados.recalcular(sessao)
    assert _o_par_esta_na_fila(sessao, um, outro)

    atores_duplicados.declarar_distintos(
        sessao, um=um.id, outro=outro.id, motivo="são dois jornais", decidido_por=None
    )

    #: `listar` DIRETO e não `_o_par_esta_na_fila`: o auxiliar recalcula antes de
    #: ler, e usá-lo aqui provaria apenas que a decisão filtra — não que ela
    #: filtra SEM recálculo, que é o ponto de guardar só o pareamento.
    pares_na_fila = {
        frozenset({d.id, c.id})
        for d in atores_duplicados.listar(sessao)
        for c in d.candidatos
    }
    assert frozenset({um.id, outro.id}) not in pares_na_fila


def test_o_cadastro_LIMPO_calculou_e_a_tela_sabe(sessao):
    """O furo que eu quase repeti, e que a `0115` existe para fechar do outro lado.

    Um cadastro sem duplicata nenhuma faz `recalcular` achar zero par e não
    inserir linha em `par_semelhante`. Se `calculado_em` saísse do `max` daquela
    tabela, seria nulo — e a tela diria "nunca calculado" tendo calculado. O
    cálculo é fato próprio, registrado mesmo com zero.
    """
    sessao.execute(delete(ParSemelhante))
    sessao.execute(delete(PareamentoDaFila))
    #: SÓ UM CADASTRO: não há com quem parear.
    _cadastrar(sessao, "Unico Sem Par zzpg7", "veiculo")
    sessao.flush()

    pares = atores_duplicados.recalcular(sessao)

    assert pares == 0
    assert sessao.scalar(select(func.count()).select_from(ParSemelhante)) == 0
    #: E MESMO ASSIM a tela sabe que calculou.
    assert atores_duplicados.calculado_em(sessao) is not None


def test_o_historico_do_pareamento_acrescenta_em_vez_de_substituir(sessao):
    """Duas execuções deixam duas linhas: "quando foi recalculado e quantos pares
    deu" é a pergunta seguinte de quem desconfia da fila."""
    sessao.execute(delete(PareamentoDaFila))
    sessao.flush()

    atores_duplicados.recalcular(sessao)
    atores_duplicados.recalcular(sessao)

    assert sessao.scalar(select(func.count()).select_from(PareamentoDaFila)) == 2


def test_calculado_em_distingue_ZERO_de_NUNCA(sessao):
    """O erro que isto evita é pior que o 504 que a mudança corrige.

    A tabela nasce vazia, então depois do deploy a tela diria "Possíveis
    duplicados (0)" num cadastro cheio de duplicatas. Nulo significa NUNCA, e a
    tela tem de dizer isso.
    """
    sessao.execute(delete(ParSemelhante))
    sessao.execute(delete(PareamentoDaFila))
    sessao.flush()
    assert atores_duplicados.calculado_em(sessao) is None

    _cadastrar(sessao, "Agencia Brasil zzpg4", "veiculo")
    _cadastrar(sessao, "agenciabrasil zzpg4", "perfil_rede")
    atores_duplicados.recalcular(sessao)

    assert atores_duplicados.calculado_em(sessao) is not None


def test_a_rota_do_estado_responde_o_mesmo(sessao, cliente):
    sessao.execute(delete(ParSemelhante))
    sessao.flush()

    assert cliente.get("/api/instituicoes/duplicados/estado").json()["calculado_em"] is None

    _cadastrar(sessao, "Portal do Sul zzpg5", "veiculo")
    _cadastrar(sessao, "portaldosul zzpg5", "perfil_rede")
    atores_duplicados.recalcular(sessao)

    resposta = cliente.get("/api/instituicoes/duplicados/estado")
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["calculado_em"] is not None


def test_fundir_apaga_o_par_por_cascade(sessao):
    """`on delete cascade`: par apontando para cadastro que já não existe seria
    linha que a leitura teria de filtrar para sempre."""
    um = _cadastrar(sessao, "Radio Campinas zzpg6", "veiculo")
    outro = _cadastrar(sessao, "radiocampinas zzpg6", "perfil_rede")
    atores_duplicados.recalcular(sessao)
    antes = sessao.scalar(
        select(func.count())
        .select_from(ParSemelhante)
        .where(ParSemelhante.um_id.in_({um.id, outro.id}))
    )
    assert antes == 1

    sessao.delete(outro)
    sessao.flush()

    depois = sessao.scalar(
        select(func.count())
        .select_from(ParSemelhante)
        .where(ParSemelhante.um_id.in_({um.id, outro.id}))
    )
    assert depois == 0


# -- a defasagem é VISÍVEL, sem gancho em cada escritor -------------------------


def test_RENOMEAR_deixa_a_fila_desatualizada(sessao):
    """O caso que nenhum gancho de criação pegaria.

    Renomear não cria nem apaga cadastro: `count(*)` e `max(criado_em)` ficam
    iguais. Mas renomear é exatamente o que faz dois cadastros passarem a se
    parecer — e o recálculo só está pendurado na subida que CRIA.
    """
    um = _cadastrar(sessao, "Jornal do Norte zzdef", "veiculo")
    _cadastrar(sessao, "Outra Coisa zzdef", "veiculo")
    atores_duplicados.recalcular(sessao)
    assert not atores_duplicados.esta_desatualizado(sessao)

    um.nome = "jornaldonorte zzdef"
    um.nome_normalizado = normalizar("jornaldonorte zzdef")
    sessao.flush()

    assert atores_duplicados.esta_desatualizado(sessao)


def test_CRIAR_por_qualquer_caminho_deixa_a_fila_desatualizada(sessao):
    """Criar pela tela de cadastro, por agenda ou por comando não recalcula — e a
    impressão do cadastro é o que faz a tela saber disso de qualquer forma."""
    _cadastrar(sessao, "Base Zero zzdef2", "veiculo")
    atores_duplicados.recalcular(sessao)
    assert not atores_duplicados.esta_desatualizado(sessao)

    _cadastrar(sessao, "Chegou Depois zzdef2", "veiculo")
    sessao.flush()

    assert atores_duplicados.esta_desatualizado(sessao)


def test_DESATIVAR_tambem_conta_como_defasagem(sessao):
    """A fila é só de ativos, então desativar muda o conjunto que a impressão
    cobre — e um par antigo continuaria guardado até o próximo recálculo."""
    um = _cadastrar(sessao, "Vai Sair zzdef3", "veiculo")
    _cadastrar(sessao, "Fica zzdef3", "veiculo")
    atores_duplicados.recalcular(sessao)
    assert not atores_duplicados.esta_desatualizado(sessao)

    um.ativo = False
    sessao.flush()

    assert atores_duplicados.esta_desatualizado(sessao)


def test_a_fila_NUNCA_calculada_esta_desatualizada(sessao):
    """Por definição: fila que nunca rodou está atrás do cadastro."""
    sessao.execute(delete(PareamentoDaFila))
    sessao.flush()

    assert atores_duplicados.esta_desatualizado(sessao)


def test_a_rota_do_estado_diz_a_defasagem(sessao, cliente):
    _cadastrar(sessao, "Pela Rota zzdef4", "veiculo")
    atores_duplicados.recalcular(sessao)

    assert cliente.get("/api/instituicoes/duplicados/estado").json()["desatualizado"] is False

    _cadastrar(sessao, "Chegou Depois zzdef4", "veiculo")
    sessao.flush()

    resposta = cliente.get("/api/instituicoes/duplicados/estado")
    assert resposta.json()["desatualizado"] is True
    #: E O CARIMBO CONTINUA LÁ: desatualizada não é o mesmo que nunca calculada.
    assert resposta.json()["calculado_em"] is not None


def test_FUNDIR_de_verdade_apaga_o_par(sessao):
    """Pelo caminho real, e não por `sessao.delete`: `fundir` move os dependentes
    antes de apagar a linha, e é esse caminho que a tela exercita."""
    sobrevivente = _cadastrar(sessao, "Valor Econômico zzfun", "veiculo")
    que_sai = _cadastrar(sessao, "valoreconomico zzfun", "perfil_rede")
    atores_duplicados.recalcular(sessao)
    assert sessao.scalar(select(func.count()).select_from(ParSemelhante)) >= 1

    atores_duplicados.fundir(
        sessao,
        que_sai_id=que_sai.id,
        sobrevivente_id=sobrevivente.id,
        contra_a_proposta=False,
    )

    sobrou = sessao.scalar(
        select(func.count())
        .select_from(ParSemelhante)
        .where(ParSemelhante.um_id.in_({que_sai.id, sobrevivente.id}))
    )
    assert sobrou == 0, "o par ficou apontando para cadastro que já não existe"


def test_a_impressao_NAO_depende_da_ordem_de_leitura(sessao):
    """`string_agg` sem `ORDER BY` daria hash diferente pela ordem de leitura.

    O defeito seria uma defasagem FALSA na tela — pior que não avisar, porque
    manda recalcular 102 s à toa e ensina a ignorar o aviso.

    REESCREVER A LINHA MOVE O REGISTRO no heap: `update` no Postgres grava uma
    versão nova, que passa a ser lida no fim. Se a agregação dependesse da ordem
    física, a impressão mudaria aqui — e não muda.
    """
    primeiro = _cadastrar(sessao, "Alfa zzord", "veiculo")
    _cadastrar(sessao, "Beta zzord", "veiculo")
    _cadastrar(sessao, "Gama zzord", "veiculo")
    sessao.flush()
    antes = atores_duplicados.impressao_do_cadastro(sessao)

    #: MESMO CONTEÚDO, posição nova: o `update` grava uma versão nova da linha
    #: sem alterar valor nenhum, que é exatamente o que isola a ORDEM.
    sessao.execute(
        text("update instituicao set nome = nome where id = :id"), {"id": primeiro.id}
    )
    sessao.flush()

    assert atores_duplicados.impressao_do_cadastro(sessao) == antes


def test_a_impressao_muda_SO_com_nome_ou_conjunto(sessao):
    """O contrapeso: se ela não mudasse com o que importa, não serviria."""
    um = _cadastrar(sessao, "Delta zzord2", "veiculo")
    sessao.flush()
    antes = atores_duplicados.impressao_do_cadastro(sessao)

    um.nome_normalizado = normalizar("delta renomeado zzord2")
    sessao.flush()

    assert atores_duplicados.impressao_do_cadastro(sessao) != antes


def test_FUNDIR_nao_deixa_a_fila_desatualizada(sessao):
    """A RESPOSTA DE GENTE NÃO PODE ACUSAR DEFASAGEM.

    O defeito que isto prende, achado ao consumir a rota do estado no front: a
    fusão APAGA uma linha de `instituicao`, então a impressão do cadastro muda e
    `esta_desatualizado` virava verdadeiro — por causa do próprio clique de quem
    está lendo a fila. Com 209 pares a decidir, o aviso "pode haver duplicado
    novo" ficaria aceso para sempre depois do primeiro, e aviso sempre aceso é
    aviso que se aprende a ignorar.

    E O CARIMBO NÃO É MENTIRA: semelhança é par a par, tirar um nome não faz dois
    outros passarem a se parecer, e os pares do removido saíram na cascata. O que
    sobrou guardado continua correto.
    """
    sobrevivente = _cadastrar(sessao, "Valor Econômico zzrev", "veiculo")
    que_sai = _cadastrar(sessao, "valoreconomico zzrev", "perfil_rede")
    atores_duplicados.recalcular(sessao)
    assert not atores_duplicados.esta_desatualizado(sessao)

    atores_duplicados.fundir(
        sessao,
        que_sai_id=que_sai.id,
        sobrevivente_id=sobrevivente.id,
        contra_a_proposta=False,
    )

    assert not atores_duplicados.esta_desatualizado(sessao)
    #: E A CONTAGEM CARIMBADA É A DE VERDADE, e não a de antes da fusão: o par
    #: respondido saiu, e uma linha dizendo o número velho faria o histórico do
    #: pareamento mentir sobre o que estava guardado.
    assert sessao.scalar(
        select(PareamentoDaFila.pares).order_by(
            PareamentoDaFila.calculado_em.desc(), PareamentoDaFila.id.desc()
        )
    ) == sessao.scalar(select(func.count()).select_from(ParSemelhante))


def test_REVALIDAR_nao_inventa_pareamento_que_nunca_houve(sessao):
    """O carimbo não pode nascer de uma remoção.

    É a mesma mentira que `pareamento_da_fila` existe para impedir, pela porta de
    trás: apagar cadastro não é calcular fila, e uma linha dizendo "pareado, zero
    pares" faria a tela afirmar que a fila está em dia num banco em que ela nunca
    rodou — exatamente o que o comando de backfill da `0118` existe para evitar.
    """
    sobrevivente = _cadastrar(sessao, "Fica zzrev2", "veiculo")
    que_sai = _cadastrar(sessao, "fica zzrev2", "perfil_rede")
    sessao.execute(delete(PareamentoDaFila))
    sessao.flush()

    atores_duplicados.fundir(
        sessao,
        que_sai_id=que_sai.id,
        sobrevivente_id=sobrevivente.id,
        contra_a_proposta=False,
    )

    assert atores_duplicados.calculado_em(sessao) is None
    assert atores_duplicados.esta_desatualizado(sessao)


def test_APAGAR_cadastro_pela_rota_nao_deixa_a_fila_desatualizada(cliente, sessao):
    """A OUTRA REMOÇÃO. `DELETE /api/instituicoes/{id}` apaga a linha que entrou
    por engano, e sem o carimbo ela acenderia o aviso do mesmo jeito que a fusão.

    PELA ROTA, e não por `revalidar` direto: é o caminho que a tela exercita, e é
    nele que o chamador pode esquecer de carimbar.
    """
    _cadastrar(sessao, "Erro de Cadastro zzrev4", "veiculo")
    sobra = _cadastrar(sessao, "errodecadastro zzrev4", "perfil_rede")
    atores_duplicados.recalcular(sessao)
    assert not atores_duplicados.esta_desatualizado(sessao)

    assert cliente.delete(f"/api/instituicoes/{sobra.id}").status_code == 204

    assert not atores_duplicados.esta_desatualizado(sessao)


def _carimbar_um_pareamento(sessao) -> None:
    """Uma linha em `pareamento_da_fila` SEM passar por `recalcular`.

    POR QUE NÃO `recalcular` AQUI: ele pega `pg_advisory_xact_lock`, que vive até o
    fim da transação — e a transação do teste não acaba durante o teste. Um
    cadeado de outra conexão então esperaria para sempre. Medido: a suíte travou
    em `SELECT pg_advisory_lock(8118)` com a sessão do teste `idle in transaction`.
    """
    sessao.add(
        PareamentoDaFila(
            pares=0, impressao=atores_duplicados.impressao_do_cadastro(sessao)
        )
    )
    sessao.flush()


def test_a_impressao_descreve_o_cadastro_DE_QUE_OS_PARES_SAIRAM(sessao, monkeypatch):
    """O FURO GRAVE que a revisão achou, e o único cuja mentira é silenciosa.

    A impressão era tirada no FIM de `recalcular`, depois dos 102,7 s de cálculo.
    Um nome editado durante o cálculo entrava na impressão e NÃO nos pares — e aí
    `esta_desatualizado` respondia "em dia" sobre um pareamento que não conhecia
    aquele nome. Falso "em dia" é pior que defasagem falsa: não há aviso nenhum
    para desconfiar.

    O ESCRITOR CONCORRENTE É SIMULADO pelo `_vizinhos`, que é onde os 102 s são
    gastos: renomear ali é renomear "durante o cálculo". Não é duas transações de
    verdade — é a ORDEM que está sob teste, e a ordem é a mesma.
    """
    um = _cadastrar(sessao, "Durante o Calculo zzimp", "veiculo")
    _cadastrar(sessao, "Outra Coisa zzimp", "veiculo")

    de_verdade = atores_duplicados._vizinhos

    def renomeando_no_meio(cadastros):
        resultado = de_verdade(cadastros)
        um.nome_normalizado = normalizar("renomeado no meio zzimp")
        sessao.flush()
        return resultado

    monkeypatch.setattr(atores_duplicados, "_vizinhos", renomeando_no_meio)
    atores_duplicados.recalcular(sessao)

    #: A IMPRESSÃO GUARDADA É A DE ANTES DO RENOME, porque é dela que os pares
    #: saíram — então a tela sabe que o pareamento está atrás do cadastro.
    assert atores_duplicados.esta_desatualizado(sessao)


def _instrucoes_de(sessao, fazer) -> list[str]:
    """O SQL que `fazer` manda ao banco, em ordem."""
    instrucoes: list[str] = []

    def capturar(conexao, cursor, instrucao, parametros, contexto, varias):
        instrucoes.append(instrucao)

    event.listen(sessao.bind, "before_cursor_execute", capturar)
    try:
        fazer()
    finally:
        event.remove(sessao.bind, "before_cursor_execute", capturar)
    return instrucoes


def test_a_impressao_SAI_DA_MESMA_INSTRUCAO_QUE_LE_AS_LINHAS(sessao):
    """A JANELA RESIDUAL FECHADA, e ela ainda caía do lado perigoso.

    Tirar a impressão logo DEPOIS da leitura encurtou a janela dos 102,7 s para o
    intervalo entre duas instruções vizinhas, mas não mudou o lado do erro: sob
    `read committed` cada instrução pega o seu instantâneo, então um escritor que
    commitasse entre as duas entrava na impressão e não nos pares. A impressão
    guardada passava a bater com a de agora, `esta_desatualizado` respondia "em
    dia", e os pares não conheciam aquele nome — o falso "em dia" outra vez, só
    mais estreito.

    UMA INSTRUÇÃO NÃO TEM "ENTRE": linhas e impressão saem do mesmo instantâneo, e
    não há intervalo onde caber um commit. Por isso o teste conta INSTRUÇÕES, e não
    efeito: o efeito dependeria de acertar a janela no relógio.
    """
    _cadastrar(sessao, "Mesmo Instantaneo zzimp2", "veiculo")
    _cadastrar(sessao, "mesmoinstantaneo zzimp2", "perfil_rede")

    instrucoes = _instrucoes_de(sessao, lambda: atores_duplicados.recalcular(sessao))

    leituras = [
        i for i in instrucoes if "instituicao" in i.lower() and "select" in i.lower()
    ]
    assert len(leituras) == 1, (
        "a impressão voltou a sair numa instrução própria, e com ela a janela:\n"
        + "\n---\n".join(leituras)
    )
    assert "md5" in leituras[0].lower(), (
        "a única leitura de `instituicao` não traz a impressão: "
        "ela deve ser coluna da MESMA instrução"
    )


def test_a_impressao_GUARDADA_e_a_QUE_A_FUNCAO_PUBLICA_CALCULA(sessao):
    """A IMPRESSÃO EMBUTIDA CONTINUA SENDO A MESMA, e o erro aqui seria silencioso.

    Virar coluna de outra consulta é a chance de a impressão passar a descrever
    outra coisa — a linha da vez em vez do cadastro, se a subconsulta algum dia
    correlacionar. Não levantaria erro: gravaria hash diferente do que
    `esta_desatualizado` compara, e a tela acusaria defasagem a cada leitura.

    O QUE ESTE TESTE NÃO FAZ, e eu afirmei que fazia: ele não discrimina o
    `correlate(None)`. MEDIDO — o SQL sai igual com e sem, porque o SQLAlchemy só
    correlaciona se sobrar algum `from` na subconsulta. O teste prende a
    IGUALDADE, que é a invariante que importa, e é ela que pegaria a correlação se
    uma segunda tabela a destravasse.
    """
    _cadastrar(sessao, "Correlacao zzimp3", "veiculo")
    _cadastrar(sessao, "correlacao zzimp3", "perfil_rede")
    _cadastrar(sessao, "Terceiro Nome zzimp3", "veiculo")

    atores_duplicados.recalcular(sessao)

    guardada = sessao.scalar(
        select(PareamentoDaFila.impressao).order_by(PareamentoDaFila.id.desc())
    )
    assert guardada == atores_duplicados.impressao_do_cadastro(sessao)
    assert not atores_duplicados.esta_desatualizado(sessao)


def test_o_cadastro_VAZIO_tambem_fica_com_impressao(sessao):
    """SEM LINHA NENHUMA A INSTRUÇÃO NÃO DEVOLVE LINHA, e a impressão viria vazia.

    O cadastro vazio é o caso em que a impressão não pode sair da leitura das
    linhas — não há linha de onde tirá-la. Ela é a constante que
    `_consulta_da_impressao` já usa no `coalesce`, e usar a MESMA constante é o que
    impede o cadastro vazio de parecer defasado para sempre.
    """
    sessao.execute(delete(Mencao))
    sessao.execute(delete(Interlocutor))
    sessao.execute(delete(Instituicao))
    sessao.flush()

    assert atores_duplicados.recalcular(sessao) == 0
    assert not atores_duplicados.esta_desatualizado(sessao)


def test_REVALIDAR_dispensa_o_carimbo_com_RECALCULO_em_voo(sessao):
    """ACHADO DE REVISÃO: contar `par_semelhante` no meio da substituição dela
    gravaria no histórico um número de pares que nunca foi verdade.

    O CADEADO EXCLUSIVO DE OUTRA CONEXÃO simula o recálculo em voo — de sessão, e
    não `xact`, para sobreviver fora de transação.
    """
    sobrevivente = _cadastrar(sessao, "Em Voo zzrev5", "veiculo")
    que_sai = _cadastrar(sessao, "emvoo zzrev5", "perfil_rede")
    _carimbar_um_pareamento(sessao)
    antes = sessao.scalar(select(func.count()).select_from(PareamentoDaFila))

    outra = _engine.connect()
    try:
        outra.execute(
            select(func.pg_advisory_lock(atores_duplicados.ESPACO_DA_TRAVA_DO_PAREAMENTO))
        )
        outra.commit()

        atores_duplicados.fundir(
            sessao,
            que_sai_id=que_sai.id,
            sobrevivente_id=sobrevivente.id,
            contra_a_proposta=False,
        )

        #: NENHUMA LINHA NOVA: o carimbo foi dispensado, e não gravou contagem
        #: tirada de uma tabela que estava sendo substituída.
        assert sessao.scalar(select(func.count()).select_from(PareamentoDaFila)) == antes
    finally:
        outra.execute(
            select(
                func.pg_advisory_unlock(atores_duplicados.ESPACO_DA_TRAVA_DO_PAREAMENTO)
            )
        )
        outra.commit()
        outra.close()


def test_REVALIDAR_carimba_mesmo_com_OUTRA_revalidacao_em_voo(sessao):
    """O CONTRAPESO, e sem ele o conserto viraria o defeito.

    Com cadeado EXCLUSIVO a segunda fusão simultânea não carimbaria — e o aviso
    falso que `revalidar` existe para apagar voltaria pela porta de trás, agora só
    para quem clica junto com outra pessoa. O CADEADO COMPARTILHADO DE OUTRA
    CONEXÃO é a outra revalidação em voo.

    O QUE ESTE TESTE PROVA, E SÓ ISSO: que o cadeado compartilhado não barra o
    carimbo. Ele NÃO exercita duas transações escrevendo — a ordem de
    `calculado_em` contra a ordem de commit, e qual linha vence na inversão,
    seguem afirmadas no docstring de `revalidar` e não prendidas aqui. Provar
    aquilo pede duas sessões que COMMITAM, e o resíduo delas cairia nos outros
    testes desta execução.
    """
    sobrevivente = _cadastrar(sessao, "Junto zzrev6", "veiculo")
    que_sai = _cadastrar(sessao, "junto zzrev6", "perfil_rede")
    _carimbar_um_pareamento(sessao)
    antes = sessao.scalar(select(func.count()).select_from(PareamentoDaFila))

    outra = _engine.connect()
    try:
        outra.execute(
            select(
                func.pg_advisory_lock_shared(
                    atores_duplicados.ESPACO_DA_TRAVA_DO_PAREAMENTO
                )
            )
        )
        outra.commit()

        atores_duplicados.fundir(
            sessao,
            que_sai_id=que_sai.id,
            sobrevivente_id=sobrevivente.id,
            contra_a_proposta=False,
        )

        assert (
            sessao.scalar(select(func.count()).select_from(PareamentoDaFila))
            == antes + 1
        )
        assert not atores_duplicados.esta_desatualizado(sessao)
    finally:
        outra.execute(
            select(
                func.pg_advisory_unlock_shared(
                    atores_duplicados.ESPACO_DA_TRAVA_DO_PAREAMENTO
                )
            )
        )
        outra.commit()
        outra.close()


def test_REVALIDAR_nao_esconde_defasagem_de_verdade(sessao):
    """O contrapeso: o carimbo vale para a remoção, e só para ela.

    Sem este teste, `revalidar` poderia ser chamada de um caminho que CRIA ou
    RENOMEIA e silenciar o aviso que a tela precisa dar.
    """
    sobrevivente = _cadastrar(sessao, "Sobrevive zzrev3", "veiculo")
    que_sai = _cadastrar(sessao, "sobrevive zzrev3", "perfil_rede")
    atores_duplicados.recalcular(sessao)
    atores_duplicados.fundir(
        sessao,
        que_sai_id=que_sai.id,
        sobrevivente_id=sobrevivente.id,
        contra_a_proposta=False,
    )
    assert not atores_duplicados.esta_desatualizado(sessao)

    sobrevivente.nome_normalizado = normalizar("sobrevive renomeado zzrev3")
    sessao.flush()

    assert atores_duplicados.esta_desatualizado(sessao)


#: A ROTA DO BOTÃO, em constante porque quatro testes a citam: um erro de
#: digitação em um deles passaria como 404, e o teste falharia dizendo a coisa
#: errada.
#:
#: FORA DE `/api/instituicoes/` de propósito — ver `refazer_o_pareamento`. O
#: endereço faz parte do contrato aqui: sob aquele prefixo, o front recarregaria
#: o catálogo inteiro a cada clique.
ROTA_DO_PAREAMENTO = "/api/pareamento-de-duplicados"


@contextmanager
def _cliente_como(sessao, perfil: str, **ajustes):
    """Um cliente HTTP com o papel pedido, e a configuração que o teste quiser.

    A fixture `cliente` fixa `plataforma_edicao`, que é quem administra. O teste
    da recusa precisa de OUTRO papel e o do teto de outro número — parâmetro em
    vez de uma fixture por combinação.
    """
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como = Configuracao(
        **{
            **padrao.model_dump(),
            "auth_mock": True,
            "auth_mock_perfil": perfil,
            **ajustes,
        }
    )
    #: DEVOLVE O QUE ENCONTROU, em vez de zerar: limpar tudo apagaria as
    #: sobrescritas de quem chamou — a fixture `cliente`, por exemplo — e um teste
    #: que aninhasse os dois sairia daqui com a aplicação ligada no banco de
    #: verdade. Achado de revisão; nenhum teste aninha hoje.
    anteriores = dict(app.dependency_overrides)
    app.dependency_overrides[obter_sessao] = lambda: sessao
    app.dependency_overrides[obter_configuracao] = lambda: como
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(anteriores)


def test_a_rota_do_pareamento_NAO_FICA_sob_instituicoes():
    """O ENDEREÇO É CONTRATO, e não gosto.

    O front trata toda escrita sob `/api/instituicoes` como mudança de catálogo e
    recarrega o catálogo INTEIRO — por prefixo com fronteira, em
    `dominio/sincronizacao.ts`, cuja regra é "a escrita muda o catálogo?". O
    pareamento escreve `par_semelhante` e `pareamento_da_fila`, e nada que o
    catálogo sirva: sob aquele prefixo, cada clique custaria uma recarga do
    painel para não mudar nada nele. É a mesma razão que deixou
    `/api/atores-distintos` fora de lá.

    MOVER A ROTA PARA LÁ NÃO QUEBRARIA MAIS NADA nesta suíte — o back não conhece
    a lista do front. Este teste é o único que reclamaria.

    `_rotas_montadas` E NÃO `app.routes`: o primeiro nível traz cinco rotas de
    serviço e NENHUMA de negócio, então a busca passaria sem achar nada — que é o
    aviso escrito no próprio helper, e foi o erro que eu cometi aqui antes de
    procurá-lo.
    """
    from fastapi.routing import APIRoute

    from tests.test_portal_no_backend import _rotas_montadas

    caminhos = {
        rota.path for rota in _rotas_montadas(app) if isinstance(rota, APIRoute)
    }
    #: AS DUAS ASSERÇÕES, e a segunda não é zelo: sozinha, a primeira passaria
    #: com a rota APAGADA.
    assert ROTA_DO_PAREAMENTO in caminhos
    assert not ROTA_DO_PAREAMENTO.startswith("/api/instituicoes")


def test_a_ROTA_DO_PAREAMENTO_enche_a_fila_que_nasceu_vazia(cliente, sessao):
    """O botão da tela, e o conserto de um beco sem saída.

    A `0118` cria `par_semelhante` vazia, e a tela avisa "ainda não foi pareada:
    peça ao administrador para rodar o pareamento". Até esta rota existir o
    administrador TAMBÉM não tinha caminho — o recado não tinha destino.
    """
    sessao.execute(delete(ParSemelhante))
    sessao.execute(delete(PareamentoDaFila))
    sessao.flush()
    _cadastrar(sessao, "Portal do Norte zzbot1", "veiculo")
    _cadastrar(sessao, "portaldonorte zzbot1", "perfil_rede")
    sessao.flush()

    assert cliente.get("/api/instituicoes/duplicados/estado").json()["calculado_em"] is None

    resposta = cliente.post(ROTA_DO_PAREAMENTO)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["pares"] >= 1
    #: E A LEITURA ALCANÇA O QUE A CONTAGEM AFIRMA. A contagem sozinha poderia
    #: sair de um `insert` que a fila não enxerga — foi o defeito da `0098`, em
    #: que a barra contava 29.701 e o clique achava 30.932.
    assert cliente.get("/api/instituicoes/duplicados/estado").json()["calculado_em"] is not None
    assert cliente.get("/api/instituicoes/duplicados").json() != []


def test_o_pareamento_EXIGE_QUEM_ADMINISTRA_cadastros(sessao):
    """A permissão de `fundir`, e não a de ver a fila.

    Ver a fila é leitura do diretório. Refazer o pareamento é trabalho que todo
    mundo sente enquanto roda, e substitui a lista que outra pessoa pode estar
    respondendo.

    A MENSAGEM ENTRA NA ASSERÇÃO porque três dependências deste router recusam
    com 403: sem ela o teste passaria se `crm_edicao` fosse barrado pelo portal
    ou pelo diretório, e passaria pelo motivo errado.
    """
    with _cliente_como(sessao, "crm_edicao") as cliente:
        resposta = cliente.post(ROTA_DO_PAREAMENTO)

    assert resposta.status_code == 403, resposta.text
    assert "administra os cadastros" in resposta.json()["detalhe"]


def test_o_pareamento_RECUSA_acima_do_teto_SEM_COMECAR(sessao, monkeypatch):
    """O teto existe para o 504 não ser o aviso.

    A conta é n²: 9,6 s medidos em 3.800 cadastros, 22,4 s medidos no ambiente
    em ~5.800, e os 240 s de `proxy_read_timeout` do nginx seriam alcançados
    perto de 19.000. O cadastro cresce em LOTE — `veiculos_da_imprensa.criar`
    registra 2.631 criações numa tela só —, então não é questão de se chega lá.

    RECUSAR ANTES DE COMEÇAR é o ponto inteiro: recusa depois da moagem já gastou
    o que a recusa existe para poupar, e quem apertou esperou do mesmo jeito.

    E "NÃO COMEÇOU" SE PROVA PELA FUNÇÃO, não pela tabela — achado de revisão. A
    versão anterior deste teste conferia `pareamento_da_fila` vazia, o que
    passaria também se a moagem tivesse rodado e falhado antes de gravar. Quem
    responde "foi chamada?" é a própria `recalcular`.
    """
    _cadastrar(sessao, "Acima do Teto zzbot2", "veiculo")
    sessao.flush()

    def nao_deveria_moer(_sessao):
        raise AssertionError("a rota chamou `recalcular` apesar do teto")

    monkeypatch.setattr(atores_duplicados, "recalcular", nao_deveria_moer)

    with _cliente_como(sessao, "plataforma_edicao", teto_do_pareamento=0) as cliente:
        resposta = cliente.post(ROTA_DO_PAREAMENTO)

    assert resposta.status_code == 409, resposta.text
    #: A MENSAGEM ENTRA NA ASSERÇÃO porque a rota tem DOIS 409 — este e o de "já
    #: está rodando". Sem ela, o teste passaria pela recusa errada.
    assert "acima do teto" in resposta.json()["detalhe"]


def test_o_pareamento_RECUSA_se_JA_ESTA_RODANDO_em_vez_de_esperar(sessao):
    """Duas moagens ao mesmo tempo não se enfileiram: a segunda é recusada.

    POR QUE IMPORTA. A rota é síncrona, então ela segura uma thread do threadpool
    e uma conexão do pool enquanto mói — 22,4 s medidos no ambiente.
    `recalcular` espera no cadeado de propósito, e esperar AQUI multiplicaria
    thread e conexão presas por chamada. O limite de taxa é middleware de 600 por
    IP, então ele não é essa guarda.

    O `statement_timeout` NÃO É DECORAÇÃO, é o controle negativo: sem a guarda
    esta rota BLOQUEIA no cadeado da outra conexão, e a suíte travaria em vez de
    falhar — já aconteceu neste arquivo, ver `_carimbar_um_pareamento`. Com o
    tempo limite, a ausência da guarda aparece como erro.
    """
    outra = _engine.connect()
    try:
        outra.execute(
            select(func.pg_advisory_lock(atores_duplicados.ESPACO_DA_TRAVA_DO_PAREAMENTO))
        )
        sessao.execute(text("set local statement_timeout = '3s'"))

        with _cliente_como(sessao, "plataforma_edicao") as cliente:
            resposta = cliente.post(ROTA_DO_PAREAMENTO)

        assert resposta.status_code == 409, resposta.text
        assert "já está sendo refeito" in resposta.json()["detalhe"]
    finally:
        outra.execute(
            select(func.pg_advisory_unlock(atores_duplicados.ESPACO_DA_TRAVA_DO_PAREAMENTO))
        )
        outra.close()
