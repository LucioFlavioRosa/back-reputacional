"""O ciclo da agenda sobrevive à ida e volta pelo banco.

POR QUE ESTE ARQUIVO EXISTE
---------------------------
A interação deixou de ser o registro de um fato consumado e passou a ser uma
agenda com ciclo: pedida, planejada, confirmada ou declinada, realizada, e
desdobrada em outra.

Isso acrescentou campos em quatro camadas — DDL, ORM, domínio e esquemas — e
uma camada que esqueça um campo não quebra nada: ela simplesmente PERDE o dado,
em silêncio, no `PATCH`. A pessoa escreve a expectativa, salva, recarrega, e o
campo está vazio. Nada nos logs.

Cada teste aqui grava e RELÊ. É a única forma de provar que as quatro camadas
concordam.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.banco.repositorio_interacoes import RepositorioSQL
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor
from app.dominio.erros import RegraViolada
from app.dominio.frentes import Frente
from app.dominio.identidade import Escopo
from app.dominio.interacao import (
    Interacao,
    MaterialDaAgenda,
    ParticipanteDaOutraParte,
)
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

#: Estes testes provam a PERSISTÊNCIA do ciclo, não o recorte por escopo — que
#: tem arquivo próprio. Um escopo restrito aqui faria a leitura devolver nada e
#: o teste falhar por um motivo que não é o dele.
IRRESTRITO = Escopo(irrestrito=True)


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
def autor(sessao):
    """Um usuário criado aqui, e não uma conta semeada.

    O banco de teste é recriado do zero e não tem as contas de
    desenvolvimento; procurar por e-mail devolvia `None`, e `criado_por`
    (obrigatório em `interacao`) estourava na inserção.
    """
    from app.banco.tabelas_acesso import Papel, Usuario

    sufixo = uuid4().hex[:8]
    # COM PAPEL DE EDICAO, e nao so `acesso_irrestrito`.
    #
    # `acesso_irrestrito` diz QUAIS registros a pessoa alcanca; o papel diz o
    # que ela FAZ neles. Sem papel, `exigir_permissao_de_edicao` recusa — e os
    # testes que passam pelo caso de uso morriam em `NaoAutorizado` antes de
    # chegar ao que queriam medir.
    papel = sessao.scalar(
        select(Papel.id).where(Papel.codigo == "plataforma_edicao")
    )
    registro = Usuario(
        entra_object_id=f"ciclo-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome="Autor do ciclo",
        papel_id=papel,
        acesso_irrestrito=True,
    )
    sessao.add(registro)
    sessao.flush()
    return registro.id


@pytest.fixture
def instituicao(sessao):
    sufixo = uuid4().hex[:8]
    registro = Instituicao(
        nome=f"Agência {sufixo}",
        nome_normalizado=f"agencia {sufixo}",
        tipo="orgao",
        uf="SP",
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _pessoa_da_outra_parte(sessao, instituicao) -> Interlocutor:
    registro = Interlocutor(
        nome=f"Pessoa {uuid4().hex[:6]}",
        nome_normalizado=f"pessoa {uuid4().hex[:6]}",
        instituicao_id=instituicao.id,
        tipo="gestor_publico",
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _agenda(instituicao, autor, **ajustes) -> Interacao:
    base = dict(
        frente=Frente.GOVERNO,
        data_interacao=date(2026, 3, 10),
        instituicao_id=instituicao.id,
        uf="SP",
        status="agendado",
        pauta="Reajuste tarifário do contrato de Piracicaba",
        criado_por=autor,
    )
    base.update(ajustes)
    return Interacao(**base)


def test_o_previsto_e_o_real_voltam_do_banco(sessao, instituicao, autor):
    """O campo que a plataforma existe para criar: expectativa ao lado do relato.

    Lado a lado, a distância entre o que se esperava e o que houve é legível
    sem consulta nenhuma — que é a medida de eficiência, e não a contagem de
    reuniões.
    """
    repositorio = RepositorioSQL(sessao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            expectativa="Sair com o cronograma do reajuste acordado",
            preve_desdobramento=True,
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.expectativa == "Sair com o cronograma do reajuste acordado"
    assert lida.preve_desdobramento is True


def test_nao_informado_continua_nao_informado(sessao, instituicao, autor):
    """Nulo NÃO pode virar `False` no caminho de volta.

    Os 60 registros que vieram da planilha não responderam nada disto. Se a
    leitura os trouxesse como "não prevê desdobramento", a base afirmaria uma
    decisão que ninguém tomou — e o painel contaria essas agendas como
    encerradas.
    """
    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(_agenda(instituicao, autor))
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.preve_desdobramento is None, "nulo virou decisão"
    assert lida.expectativa is None
    assert lida.declinado_por is None


def test_participantes_da_outra_parte_e_a_presenca(sessao, instituicao, autor):
    """Quem se esperava, quem foi, e quem faltou.

    `ausente` é o dado mais valioso dos três: uma reunião em que o decisor não
    apareceu não é a reunião que foi pedida, ainda que conste como realizada.
    """
    repositorio = RepositorioSQL(sessao)
    veio = _pessoa_da_outra_parte(sessao, instituicao)
    faltou = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=veio.id, presenca="presente"),
                ParticipanteDaOutraParte(
                    interlocutor_id=faltou.id, presenca="ausente"
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    por_pessoa = {p.interlocutor_id: p.presenca for p in lida.outra_parte}
    assert por_pessoa == {veio.id: "presente", faltou.id: "ausente"}


def test_mudar_a_presenca_nao_derruba_e_recria_o_vinculo(sessao, instituicao, autor):
    """Depois da reunião, `previsto` vira `presente` — e isso é UM fato.

    Se a atualização removesse e reinserisse a linha, a trilha registraria uma
    saída e uma entrada: dois eventos para uma confirmação de presença, e a
    ficha diria que a pessoa foi retirada da agenda e recolocada.
    """
    repositorio = RepositorioSQL(sessao)
    pessoa = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=pessoa.id, presenca="previsto"
                ),
            ),
        )
    )
    sessao.flush()
    antes = sessao.scalar(
        text(
            "select count(*) from interacao_auditoria "
            "where interacao_id = :i and campo like '%interlocutor%'"
        ),
        {"i": salva.id},
    )

    from dataclasses import replace

    repositorio.atualizar(
        replace(
            repositorio.obter(salva.id, escopo=IRRESTRITO),
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=pessoa.id, presenca="presente"
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.outra_parte[0].presenca == "presente"

    depois = sessao.scalar(
        text(
            "select count(*) from interacao_auditoria "
            "where interacao_id = :i and campo like '%interlocutor%'"
        ),
        {"i": salva.id},
    )
    assert depois == antes, (
        "confirmar presença gerou evento de vínculo: a ficha vai dizer que a "
        "pessoa saiu e voltou da agenda"
    )


def test_materiais_dos_tres_momentos(sessao, instituicao, autor):
    """Apoio existe antes da reunião; obtido e produzido, depois."""
    repositorio = RepositorioSQL(sessao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(
                    momento="apoio",
                    titulo="Nota técnica do reajuste",
                    url="https://sharepoint/nota.pdf",
                ),
                MaterialDaAgenda(
                    momento="produzido",
                    titulo="Ata da reunião",
                    url="https://sharepoint/ata.docx",
                    observacao="Assinada pelas duas partes",
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert {(m.momento, m.titulo) for m in lida.materiais} == {
        ("apoio", "Nota técnica do reajuste"),
        ("produzido", "Ata da reunião"),
    }
    assert all(m.id is not None for m in lida.materiais), (
        "sem id a tela não consegue apagar um material"
    )


def test_uma_agenda_desdobra_da_outra(sessao, instituicao, autor):
    """O encadeamento é o que transforma reuniões soltas em agenda estratégica.

    Sem ele, a terceira conversa com o mesmo órgão parece a primeira.
    """
    repositorio = RepositorioSQL(sessao)

    primeira = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="Primeira conversa sobre o reajuste")
    )
    sessao.flush()

    segunda = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            pauta="Retomada do reajuste",
            data_interacao=date(2026, 5, 4),
            origens=(primeira.id,),
        )
    )
    sessao.flush()

    assert repositorio.obter(segunda.id, escopo=IRRESTRITO).origens == (primeira.id,)


def test_declinio_guarda_o_lado_e_o_motivo(sessao, instituicao, autor):
    """Declinada PELA Aegea é escolha; declinada pela outra parte é porta fechada.

    Somar as duas num número só apaga a diferença — e é a diferença que diz se
    estamos sendo ativos o bastante.
    """
    repositorio = RepositorioSQL(sessao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            status="declinado",
            declinado_por="outra_parte",
            motivo_declinio="Agenda do diretor sem espaço no trimestre",
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.declinado_por == "outra_parte"
    assert "trimestre" in lida.motivo_declinio


def test_limpar_um_campo_do_ciclo_realmente_limpa(sessao, instituicao, autor):
    """Apagar uma expectativa escrita por engano tem de funcionar.

    Os campos acima destes no repositório usam `if is not None` — omitir
    preserva. Os do ciclo são copiados direto, justamente para que mandar nulo
    LIMPE. Se alguém uniformizar isso por simetria, este teste cai.
    """
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(
        _agenda(instituicao, autor, expectativa="texto errado")
    )
    sessao.flush()

    repositorio.atualizar(replace(repositorio.obter(salva.id, escopo=IRRESTRITO), expectativa=None))
    sessao.flush()

    assert repositorio.obter(salva.id, escopo=IRRESTRITO).expectativa is None


def test_so_um_participante_e_o_principal(sessao, instituicao, autor):
    """A marca de principal precisa significar alguma coisa.

    Dois principais na mesma agenda deixariam a ficha sem resposta para "quem
    representa a outra parte" — e o banco tem indice unico parcial para o mesmo
    fim. O dominio recusa antes, com mensagem que explica.
    """
    a = _pessoa_da_outra_parte(sessao, instituicao)
    b = _pessoa_da_outra_parte(sessao, instituicao)

    with pytest.raises(RegraViolada) as erro:
        _agenda(
            instituicao,
            autor,
            interlocutor_id=a.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=a.id, principal=True),
                ParticipanteDaOutraParte(interlocutor_id=b.id, principal=True),
            ),
        )

    assert "principal" in str(erro.value)


def test_a_marca_e_a_coluna_precisam_concordar(sessao, instituicao, autor):
    """`interacao.interlocutor_id` e a marca na lista dizem a MESMA coisa.

    As duas existem porque 67 usos dependem da coluna. Duas fontes que se
    contradizem sao piores que uma: o filtro por pessoa e a ficha responderiam
    coisas diferentes sobre quem representa a outra parte, e ninguem saberia
    qual esta certa.
    """
    principal = _pessoa_da_outra_parte(sessao, instituicao)
    outro = _pessoa_da_outra_parte(sessao, instituicao)

    with pytest.raises(RegraViolada) as erro:
        _agenda(
            instituicao,
            autor,
            interlocutor_id=principal.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=outro.id, principal=True),
            ),
        )

    assert "principal" in str(erro.value)


def test_o_principal_tem_presenca_como_qualquer_um(sessao, instituicao, autor):
    """O buraco que a revisao externa apontou.

    Antes, o principal morava so em `interlocutor_id` e nao tinha onde ter
    presenca — justamente a pessoa mais importante da reuniao era a unica sem.
    """
    repositorio = RepositorioSQL(sessao)
    pessoa = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=pessoa.id,
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=pessoa.id, presenca="ausente", principal=True
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.outra_parte[0].principal is True
    assert lida.outra_parte[0].presenca == "ausente"
    # E a coluna continua apontando para ele.
    assert lida.interlocutor_id == pessoa.id


def test_a_presenca_de_quem_representou_a_aegea_sobrevive(sessao, instituicao, autor):
    """O campo existia no banco e morria no repositorio.

    A chave da participacao e (pessoa, papel); a presenca e ATRIBUTO dela. Posta
    na chave, o porta-voz sairia e voltaria da lista quando `previsto` virasse
    `presente`.

    ATE O ESQUEMA DE SAIDA, e nao so ate o repositorio.

    Este teste parava em `lida.participacoes[0].presenca` e passava — enquanto
    a API respondia `null`. Sao CINCO camadas, nao quatro: DDL, ORM, dominio,
    esquema de ENTRADA e esquema de SAIDA. `InteracaoSaida.de_dominio` montava
    `ParticipacaoSaida` sem passar `presenca`, e o valor-padrao do campo e
    `None` — declarar nao e preencher.

    O efeito para quem usa: o `PATCH` respondia 200, o banco guardava, e a tela
    recarregava com o campo vazio. Indistinguivel de "o servidor ignorou".

    Medido pela API, e nao por leitura: so o round-trip completo separa "nao
    grava" de "nao devolve".
    """
    from app.banco.tabelas_stakeholders import PessoaAegea
    from app.dominio.interacao import ParticipacaoAegea

    porta_voz = PessoaAegea(
        nome=f"Porta-voz {uuid4().hex[:6]}",
        nome_normalizado=f"porta-voz {uuid4().hex[:6]}",
        eh_porta_voz=True,
    )
    sessao.add(porta_voz)
    sessao.flush()

    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            participacoes=(
                ParticipacaoAegea(
                    pessoa_aegea_id=porta_voz.id,
                    papel="porta_voz",
                    presenca="presente",
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.participacoes[0].presenca == "presente"

    # A PORTA QUE O NAVEGADOR USA.
    from app.esquemas.interacoes import InteracaoSaida

    saida = InteracaoSaida.de_dominio(lida, ve_campos_sensiveis=True)
    assert saida.participacoes[0].presenca == "presente"
    assert saida.participacoes[0].papel == "porta_voz"


def test_o_clima_esperado_e_comparavel_com_o_real(sessao, instituicao, autor):
    """Os dois na MESMA escala, que e o que permite compara-los como numero.

    Texto livre nao se soma, nao vira serie, e nao responde "o clima veio pior
    do que se esperava" sem alguem ler agenda por agenda.
    """
    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(
        _agenda(instituicao, autor, clima_esperado="propositivo", clima="tenso")
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.clima_esperado == "propositivo"
    assert lida.clima == "tenso"


def test_o_id_do_material_nao_muda_ao_salvar_de_novo(sessao, instituicao, autor):
    """A saida devolve `id` para a tela poder apagar UM material.

    Se ele mudasse a cada salvamento nao identificaria nada — e um `PATCH` de
    `relato` trocaria os `id`s de todos os materiais da agenda, quebrando a tela
    aberta de quem estivesse editando.
    """
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(
                    momento="apoio", titulo="Nota", url="https://x/nota.pdf"
                ),
            ),
        )
    )
    sessao.flush()

    antes = repositorio.obter(salva.id, escopo=IRRESTRITO)
    id_original = antes.materiais[0].id

    repositorio.atualizar(replace(antes, relato="qualquer outra coisa"))
    sessao.flush()

    depois = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert depois.materiais[0].id == id_original, (
        "o id do material mudou num PATCH que nem tocou nos materiais"
    )


def test_material_novo_entra_e_o_que_saiu_some(sessao, instituicao, autor):
    """Casar por `id` nao pode impedir acrescentar nem remover."""
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(momento="apoio", titulo="Fica", url="https://x/1"),
                MaterialDaAgenda(momento="apoio", titulo="Sai", url="https://x/2"),
            ),
        )
    )
    sessao.flush()

    antes = repositorio.obter(salva.id, escopo=IRRESTRITO)
    fica = next(m for m in antes.materiais if m.titulo == "Fica")

    repositorio.atualizar(
        replace(
            antes,
            materiais=(
                fica,
                MaterialDaAgenda(
                    momento="produzido", titulo="Ata", url="https://x/ata"
                ),
            ),
        )
    )
    sessao.flush()

    depois = repositorio.obter(salva.id, escopo=IRRESTRITO)
    titulos = {m.titulo for m in depois.materiais}
    assert titulos == {"Fica", "Ata"}
    assert next(m for m in depois.materiais if m.titulo == "Fica").id == fica.id


# -- os dois impedimentos da segunda revisao ----------------------------------


def test_o_id_do_material_atravessa_o_esquema_de_entrada(sessao, instituicao, autor):
    """O conserto de identidade era INERTE, e este teste e o que o prova.

    O repositorio casa material por `id`, mas `MaterialEntrada` nao declarava o
    campo — e o Pydantic o descartava em silencio, porque `extra="forbid"` de
    `InteracaoEdicao` nao alcanca modelo aninhado. Toda edicao chegava sem `id`
    e recriava tudo. A camada de baixo estava certa e nunca era exercitada.

    Testar so o repositorio nao pegava: e preciso passar pelo ESQUEMA.
    """
    from app.esquemas.interacoes import InteracaoEdicao

    corpo = InteracaoEdicao.model_validate(
        {
            "materiais": [
                {
                    "id": "11111111-2222-3333-4444-555555555555",
                    "momento": "apoio",
                    "titulo": "Nota",
                    "url": "https://x/n.pdf",
                }
            ]
        }
    )
    materiais = corpo.alteracoes(Frente.GOVERNO)["materiais"]
    assert str(materiais[0].id) == "11111111-2222-3333-4444-555555555555", (
        "o esquema descartou o id e o casamento por identidade fica inutil"
    )


def test_remover_o_principal_e_mandar_a_lista_sem_ele(sessao, instituicao, autor):
    """A REMOÇÃO, por um caminho só — e sem ressurreição.

    A versão anterior rederivava o principal a partir da coluna quando a lista
    vinha sem marca. Tirar o principal da lista o trazia de volta: uma remoção
    que o sistema desfazia calado. E `interlocutor_id: null` sozinho também não
    limpava, porque a marca antiga vencia — não havia caminho nenhum.

    Agora a lista manda. Mandá-la sem principal É a remoção.
    """
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    principal = _pessoa_da_outra_parte(sessao, instituicao)
    outro = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=principal.id,
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=principal.id, principal=True
                ),
            ),
        )
    )
    sessao.flush()

    # A COLUNA CONTINUA PREENCHIDA DE PROPÓSITO.
    #
    # É o que a tela faz: ela edita a lista de participantes, não a coluna. Se
    # o teste limpasse `interlocutor_id` à mão, exercitaria um caminho que
    # ninguém percorre — e passaria mesmo com o conserto desfeito, porque a
    # gravação incondicional da coluna já teria feito o trabalho.
    repositorio.atualizar(
        replace(
            repositorio.obter(salva.id, escopo=IRRESTRITO),
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=outro.id, presenca="presente"
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id is None, "a coluna não acompanhou a remoção"
    assert not any(p.principal for p in lida.outra_parte)
    assert {p.interlocutor_id for p in lida.outra_parte} == {outro.id}, (
        "o principal removido ressuscitou"
    )


def test_a_marca_manda_e_a_coluna_segue(sessao, instituicao, autor):
    """Trocar o principal pela lista move a coluna junto."""
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    antes = _pessoa_da_outra_parte(sessao, instituicao)
    depois = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=antes.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=antes.id, principal=True),
            ),
        )
    )
    sessao.flush()

    repositorio.atualizar(
        replace(
            repositorio.obter(salva.id, escopo=IRRESTRITO),
            interlocutor_id=depois.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=antes.id),
                ParticipanteDaOutraParte(
                    interlocutor_id=depois.id, principal=True
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id == depois.id
    marcados = [p.interlocutor_id for p in lida.outra_parte if p.principal]
    assert marcados == [depois.id]


def test_informar_so_a_coluna_continua_funcionando(sessao, instituicao, autor):
    """LISTA VAZIA é "não estou cuidando disto", e não "não há ninguém".

    É o formato do `POST` de hoje, dos testes antigos e da importação de
    planilha: informam `interlocutor_id` e nada mais. Se a lista vazia limpasse
    a coluna, todo esse caminho perderia o interlocutor em silêncio.
    """
    repositorio = RepositorioSQL(sessao)
    pessoa = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(instituicao, autor, interlocutor_id=pessoa.id)
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id == pessoa.id
    assert [p.interlocutor_id for p in lida.outra_parte] == [pessoa.id], (
        "o interlocutor da agenda ficou de fora da própria lista"
    )
    assert lida.outra_parte[0].principal is True


def test_agenda_sem_interlocutor_nao_guarda_marca_orfa(sessao, instituicao, autor):
    """A marca não pode sobreviver a um estado anterior.

    ESTE TESTE NÃO DISCRIMINAVA. A versão anterior criava a agenda já sem
    interlocutor, e aí não havia marca alguma para sobrar — esvaziar o ramo que
    limpa as marcas não o fazia falhar. Agora ele PARTE de uma agenda com
    principal marcado e depois o remove, que é o único caso em que o ramo
    importa.
    """
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    pessoa = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=pessoa.id,
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=pessoa.id, presenca="previsto", principal=True
                ),
            ),
        )
    )
    sessao.flush()
    assert repositorio.obter(salva.id, escopo=IRRESTRITO).outra_parte[0].principal

    # A pessoa continua na agenda; só deixa de representar a outra parte.
    # Sem limpar a coluna à mão: é a lista que manda.
    repositorio.atualizar(
        replace(
            repositorio.obter(salva.id, escopo=IRRESTRITO),
            outra_parte=(
                ParticipanteDaOutraParte(
                    interlocutor_id=pessoa.id, presenca="previsto"
                ),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id is None
    assert not any(p.principal for p in lida.outra_parte), (
        "a marca sobreviveu ao estado anterior"
    )
    assert len(lida.outra_parte) == 1, "a pessoa sumiu junto com a marca"


# -- quem manda depende do que o PATCH enviou ---------------------------------
#
# Os dois testes abaixo cobrem as DUAS metades de uma decisao que nao esta no
# agregado: lista vazia e lista vazia, tenha sido enviada ou omitida. So a
# requisicao sabe a diferenca, e `_reconciliar_o_principal` e onde ela para.


def _editar(sessao, salva, corpo: dict, autor):
    """Edita PELO CASO DE USO, com o corpo do PATCH de verdade.

    Chamar `_reconciliar_o_principal` direto testava a funcao e nao a LIGACAO:
    a prova negativa — tirar a chamada do fluxo — nao derrubava o teste. Foi a
    terceira vez nesta onda que escrevi um teste assim, e a licao e sempre a
    mesma: entrar pelo mesmo lugar por onde a requisicao entra.
    """
    from app.casos_de_uso.editar_interacao import editar
    from app.esquemas.interacoes import InteracaoEdicao

    return editar(
        RepositorioSQL(sessao),
        sessao,
        id=salva.id,
        alteracoes=InteracaoEdicao.model_validate(corpo).alteracoes(salva.frente),
        usuario=_como_usuario(sessao, autor),
    )


def _como_usuario(sessao, autor_id):
    from app.casos_de_uso.provisionar_usuario import carregar

    return carregar(sessao, autor_id)


def test_patch_com_lista_vazia_remove_todo_mundo(sessao, instituicao, autor):
    """Tirar TODOS os participantes nao pode ressuscitar o principal.

    Era o buraco que sobrou depois de tres rodadas de revisao: a lista vazia
    caia no ramo de compatibilidade — o mesmo que serve ao POST que informa so
    a coluna — e o principal voltava a partir dela. A pessoa tirava todo mundo,
    salvava, e ele estava la.
    """
    repositorio = RepositorioSQL(sessao)
    pessoa = _pessoa_da_outra_parte(sessao, instituicao)
    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=pessoa.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=pessoa.id, principal=True),
            ),
        )
    )
    sessao.flush()

    _editar(sessao, salva, {"outra_parte": []}, autor)
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.outra_parte == (), "alguem sobrou depois de tirar todos"
    assert lida.interlocutor_id is None, (
        "a coluna sobreviveu a remocao e ressuscitou o principal"
    )


def test_patch_so_com_interlocutor_move_a_marca(sessao, instituicao, autor):
    """A REGRESSAO que eu causei, e que a tela de hoje sofreria.

    O formulario atual edita o interlocutor num campo so e nao conhece a lista
    de participantes. Com a lista sempre mandando, esse PATCH virava no-op
    silencioso: 200 na resposta e nada alterado. Medido por HTTP antes do
    conserto — a resposta voltava com `interlocutor_id: null`.
    """
    repositorio = RepositorioSQL(sessao)
    antes = _pessoa_da_outra_parte(sessao, instituicao)
    depois = _pessoa_da_outra_parte(sessao, instituicao)
    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=antes.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=antes.id, principal=True),
            ),
        )
    )
    sessao.flush()

    _editar(sessao, salva, {"interlocutor_id": str(depois.id)}, autor)
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id == depois.id, "o PATCH nao mudou nada"
    marcados = [p.interlocutor_id for p in lida.outra_parte if p.principal]
    assert marcados == [depois.id], "a marca nao acompanhou a coluna"
    assert antes.id in {p.interlocutor_id for p in lida.outra_parte}, (
        "quem deixou de ser principal sumiu da agenda"
    )


def test_trocar_o_principal_para_quem_ja_esta_na_lista(sessao, instituicao, autor):
    """Dava 500: dois principais marcados durante o flush.

    O indice unico parcial e conferido a cada comando, e nao no fim da
    transacao — indice parcial nao pode ser `deferrable`. Promover B sem
    rebaixar A antes deixa os dois marcados por um instante, e o banco recusa
    com `duplicate key`.

    E o caminho mais natural que existe: a pessoa que ja estava na reuniao
    passa a representar a outra parte.
    """
    repositorio = RepositorioSQL(sessao)
    a = _pessoa_da_outra_parte(sessao, instituicao)
    b = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=a.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=a.id, principal=True),
                ParticipanteDaOutraParte(interlocutor_id=b.id),
            ),
        )
    )
    sessao.flush()

    _editar(sessao, salva, {"interlocutor_id": str(b.id)}, autor)
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id == b.id
    marcados = [p.interlocutor_id for p in lida.outra_parte if p.principal]
    assert marcados == [b.id], "a marca nao trocou de dono"
    assert {p.interlocutor_id for p in lida.outra_parte} == {a.id, b.id}, (
        "alguem sumiu da agenda na troca"
    )


def test_patch_com_lista_e_coluna_juntas(sessao, instituicao, autor):
    """O outro 500: mandar os dois, com a lista promovendo outra pessoa.

    A lista manda — e a coluna enviada e ignorada em favor dela. O que nao pode
    e estourar no banco por ordem de escrita.
    """
    repositorio = RepositorioSQL(sessao)
    a = _pessoa_da_outra_parte(sessao, instituicao)
    b = _pessoa_da_outra_parte(sessao, instituicao)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            interlocutor_id=a.id,
            outra_parte=(
                ParticipanteDaOutraParte(interlocutor_id=a.id, principal=True),
            ),
        )
    )
    sessao.flush()

    _editar(
        sessao,
        salva,
        {
            "interlocutor_id": str(a.id),
            "outra_parte": [{"interlocutor_id": str(b.id), "principal": True}],
        },
        autor,
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.interlocutor_id == b.id, "a lista tinha de mandar"
    assert [p.interlocutor_id for p in lida.outra_parte if p.principal] == [b.id]


def test_duas_edicoes_simultaneas_nao_estouram_no_indice(instituicao_comitada):
    """Duas pessoas editando a MESMA agenda ao mesmo tempo.

    Cada uma lia o estado antigo, decidia quem e o principal, e as duas
    gravavam: o indice unico parcial recusava a segunda com `duplicate key` e a
    tela recebia 500 — sem ninguem ter feito nada errado.

    Rebaixar antes de promover ordena DENTRO de uma sessao; nao serializa duas.
    Quem serializa e o `for update` de `obter(..., para_edicao=True)`: a segunda
    espera e le o estado NOVO em vez de decidir sobre um retrato vencido.

    O QUE ESTE TESTE PROVA, E O QUE NAO
    -----------------------------------
    Ele prova o DESFECHO: as duas edicoes concluem, nenhuma estoura, e sobra UM
    principal. E guarda de regressao util.

    Ele NAO e prova negativa. Verificado: tirando o `para_edicao=True` de
    `editar_interacao`, este teste continua passando — nem a barreira entre
    leitura e escrita nem a sincronizacao de partida produzem, neste arranjo, o
    entrelacamento que faz duas transacoes gravarem principais diferentes.

    Quem reproduziu o 500 foi a revisao externa, com duas requisicoes HTTP
    simultaneas. Registrar a limitacao importa: e a terceira vez nesta frente
    que escrevo um teste de concorrencia que se acredita discriminante e nao e,
    e um teste assim compra confianca que nao existe.
    """
    import threading

    from app.casos_de_uso.editar_interacao import editar
    from app.esquemas.interacoes import InteracaoEdicao

    agenda, a, b, autor_id, limpar = instituicao_comitada
    resultados: list[str] = []

    # A BARREIRA FICA ENTRE A LEITURA E A ESCRITA, e é isso que faz o teste
    # discriminar. Posta antes de `editar()`, ela só garante que as duas
    # threads COMEÇAM juntas — e uma pode terminar inteira antes de a outra
    # ler, caso em que não há concorrência nenhuma para medir. Foi assim que a
    # primeira versão deste teste passou até SEM o `for update`.
    #
    # `timeout` curto e `BrokenBarrierError` engolido de propósito: COM a trava,
    # a segunda thread fica presa dentro de `obter()` e nunca chega aqui. A
    # barreira estourar é o sinal de que a serialização funcionou, e não uma
    # falha.
    entre_ler_e_escrever = threading.Barrier(2, timeout=3)
    # Sem sincronizar a PARTIDA, a primeira thread terminava inteira — commit
    # inclusive — antes de a segunda sequer ler. Aí não há concorrência para
    # medir, e o teste passava dos dois jeitos.
    partida = threading.Barrier(2, timeout=10)

    class RepositorioQueEspera(RepositorioSQL):
        def atualizar(self, interacao):
            try:
                entre_ler_e_escrever.wait()
            except threading.BrokenBarrierError:
                pass
            return super().atualizar(interacao)

    def trocar(para):
        engine = create_engine(URL, pool_pre_ping=True)
        try:
            with Session(bind=engine) as propria:
                partida.wait()
                editar(
                    RepositorioQueEspera(propria),
                    propria,
                    id=agenda,
                    alteracoes=InteracaoEdicao.model_validate(
                        {"interlocutor_id": str(para)}
                    ).alteracoes(Frente.GOVERNO),
                    usuario=_como_usuario(propria, autor_id),
                )
                propria.commit()
                resultados.append("aplicou")
        except Exception as erro:  # noqa: BLE001
            resultados.append(f"{type(erro).__name__}: {str(erro)[:70]}")
        finally:
            engine.dispose()

    fios = [
        threading.Thread(target=trocar, args=(a,)),
        threading.Thread(target=trocar, args=(b,)),
    ]
    try:
        for f in fios:
            f.start()
        for f in fios:
            f.join(timeout=40)
            assert not f.is_alive(), "travou"

        quebrou = [r for r in resultados if "Violation" in r or "Integrity" in r]
        assert not quebrou, f"o indice estourou numa edicao concorrente: {quebrou}"
        assert resultados.count("aplicou") == 2, resultados

        engine = create_engine(URL, pool_pre_ping=True)
        with engine.begin() as conexao:
            marcados = conexao.execute(
                text(
                    "select count(*) from interacao_interlocutor "
                    "where interacao_id = :i and principal"
                ),
                {"i": agenda},
            ).scalar()
        engine.dispose()
        assert marcados == 1, f"sobraram {marcados} principais"
    finally:
        limpar()


@pytest.fixture
def instituicao_comitada():
    """Uma agenda COMITADA, para transacoes concorrentes a enxergarem.

    A marca nasce aqui: este modulo nao tem a fixture `marca` — ela mora em
    `test_desativar_conta.py`, e o pytest nao compartilha fixture entre
    modulos.
    """
    marca = uuid4().hex[:8]
    from app.banco.tabelas_acesso import Papel, Usuario
    from app.banco.tabelas_stakeholders import Instituicao, Interlocutor

    engine = create_engine(URL, pool_pre_ping=True)
    with Session(bind=engine) as preparo:
        papel = preparo.scalar(
            select(Papel.id).where(Papel.codigo == "plataforma_edicao")
        )
        autor = Usuario(
            entra_object_id=f"conc-{marca}",
            email=f"conc.{marca}@aegea.com.br",
            nome="Autor concorrente",
            papel_id=papel,
            acesso_irrestrito=True,
        )
        inst = Instituicao(
            nome=f"Orgao {marca}",
            nome_normalizado=f"orgao {marca}",
            tipo="orgao",
            uf="SP",
        )
        preparo.add_all([autor, inst])
        preparo.flush()
        pessoas = [
            Interlocutor(
                nome=f"P{n} {marca}",
                nome_normalizado=f"p{n} {marca}",
                instituicao_id=inst.id,
                tipo="gestor_publico",
            )
            for n in (1, 2)
        ]
        preparo.add_all(pessoas)
        preparo.flush()
        salva = RepositorioSQL(preparo).adicionar(
            Interacao(
                frente=Frente.GOVERNO,
                data_interacao=date(2026, 3, 10),
                instituicao_id=inst.id,
                uf="SP",
                status="agendado",
                pauta=f"concorrencia {marca}",
                criado_por=autor.id,
            )
        )
        preparo.commit()
        dados = (salva.id, pessoas[0].id, pessoas[1].id, autor.id)

    def limpar():
        with Session(bind=engine) as fim:
            alvo = {"m": f"%{marca}%"}
            for tabela in (
                "interacao_interlocutor",
                "material",
                "interacao_auditoria",
            ):
                fim.execute(
                    text(
                        f"delete from {tabela} where interacao_id in "
                        "(select id from interacao where pauta like :m)"
                    ),
                    alvo,
                )
            fim.execute(text("delete from interacao where pauta like :m"), alvo)
            fim.execute(text("delete from interlocutor where nome like :m"), alvo)
            fim.execute(text("delete from instituicao where nome like :m"), alvo)
            fim.execute(text("delete from usuario where email like :m"), alvo)
            fim.commit()
        engine.dispose()

    yield (*dados, limpar)


def test_agenda_sem_linha_de_participante_ainda_mostra_o_principal(
    sessao, instituicao, autor
):
    """Dados que entraram POR FORA do repositorio.

    O `backfill` da migration alcancou as interacoes que existiam naquele
    momento. O semeador de desenvolvimento, a importacao de planilha e qualquer
    `insert` de manutencao gravam `interlocutor_id` sem criar a linha de
    participante — e a ficha diria "nenhum participante" para uma agenda que
    tem interlocutor havia meses.

    Medido num banco recriado do zero: 60 interacoes semeadas, ZERO linhas em
    `interacao_interlocutor`. O backfill nao renasce a cada carga nova; a
    sintese na leitura, sim.
    """
    from sqlalchemy import text as sql

    repositorio = RepositorioSQL(sessao)
    pessoa = _pessoa_da_outra_parte(sessao, instituicao)
    salva = repositorio.adicionar(
        _agenda(instituicao, autor, interlocutor_id=pessoa.id)
    )
    sessao.flush()

    # Apaga a linha por fora, como se o registro tivesse vindo da planilha.
    sessao.execute(
        sql("delete from interacao_interlocutor where interacao_id = :i"),
        {"i": salva.id},
    )
    sessao.flush()
    sessao.expire_all()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert [p.interlocutor_id for p in lida.outra_parte] == [pessoa.id], (
        "a agenda ficou sem participante apesar de ter interlocutor"
    )
    assert lida.outra_parte[0].principal is True
    assert lida.outra_parte[0].presenca is None, (
        "inventou presenca de quem ninguem perguntou"
    )


def test_desdobramento_nao_pode_fechar_ciclo(sessao, instituicao, autor):
    """`A -> B -> A` passava, e fecha um anel.

    O banco barra `A -> A` com um `check` e o dominio da a mensagem, mas os
    dois olham UMA aresta. Com duas, qualquer leitura que suba a cadeia — "de
    onde veio esta agenda?" — roda para sempre, e a ficha que mostrar o
    historico trava.

    Enquanto nao havia como escolher a origem pela tela, o risco era teorico.
    Com o campo na tela, virou um clique. Medido pela API antes do conserto:
    os dois PATCH voltaram sucesso.
    """
    from dataclasses import replace

    repositorio = RepositorioSQL(sessao)
    primeira = repositorio.adicionar(_agenda(instituicao, autor, pauta="A"))
    sessao.flush()
    segunda = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="B", origens=(primeira.id,))
    )
    sessao.flush()

    with pytest.raises(RegraViolada) as erro:
        repositorio.atualizar(
            replace(
                repositorio.obter(primeira.id, escopo=IRRESTRITO),
                origens=(segunda.id,),
            )
        )

    assert "ciclo" in str(erro.value)


def test_cadeia_longa_de_desdobramento_continua_valendo(sessao, instituicao, autor):
    """A guarda nao pode barrar encadeamento legitimo.

    Tres agendas em fila e o caso NORMAL — e o que transforma reunioes soltas
    em agenda com historico. So o retorno ao inicio e proibido.
    """
    repositorio = RepositorioSQL(sessao)
    a = repositorio.adicionar(_agenda(instituicao, autor, pauta="A"))
    sessao.flush()
    b = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="B", origens=(a.id,))
    )
    sessao.flush()
    c = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="C", origens=(b.id,))
    )
    sessao.flush()

    assert repositorio.obter(c.id, escopo=IRRESTRITO).origens == (b.id,)


# -- o arquivo do material -----------------------------------------------------
#
# A 0011 criou `material.arquivo_id` inerte; a 0012 abriu a frente. O que segue
# cobre a costura entre banco, dominio e esquema de SAIDA — as cinco camadas,
# que este arquivo passou a vida chamando de quatro.


def test_material_sem_link_e_sem_arquivo_e_recusado(sessao, instituicao, autor):
    """A regra existia e NAO tinha teste.

    Descobri isso mudando a mensagem dela: a suite inteira passou. O `check`
    `material_precisa_apontar_para_algo` protege o dado no banco, mas quem diz
    qual material esta pela metade — e o que fazer — e o dominio.
    """
    from app.dominio.interacao import MaterialDaAgenda

    with pytest.raises(RegraViolada, match="suba um arquivo ou informe um link"):
        MaterialDaAgenda(momento="apoio", titulo="Parecer")


def test_material_pode_apontar_so_para_um_arquivo(sessao, instituicao, autor):
    """Os dois caminhos valem, e um deles basta."""
    from app.dominio.interacao import MaterialDaAgenda

    material = MaterialDaAgenda(momento="apoio", titulo="Parecer", arquivo_id=uuid4())

    assert material.url is None


def _arquivo(sessao, autor, nome="Nota.pdf"):
    from app.banco.tabelas_interacoes import Arquivo

    registro = Arquivo(
        caminho=f"interacoes/teste/{uuid4()}-{nome}",
        nome=nome,
        tipo_conteudo="application/pdf",
        tamanho=1234,
        # `autor` E O ID, e nao o objeto — a fixture devolve `registro.id`.
        criado_por=autor,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def test_o_arquivo_do_material_chega_ate_a_tela(sessao, instituicao, autor):
    """Ate o ESQUEMA DE SAIDA, e nao so ate o repositorio.

    E a licao do commit da presenca do porta-voz, aplicada antes de custar:
    `ParticipacaoSaida` DECLARAVA `presenca` e o construtor nao a passava, e o
    campo saiu nulo por tres revisoes, com 200 na resposta. Aqui o teste cruza a
    ultima camada de proposito.
    """
    from app.dominio.interacao import MaterialDaAgenda
    from app.esquemas.interacoes import InteracaoSaida

    repositorio = RepositorioSQL(sessao)
    arquivo = _arquivo(sessao, autor, "Nota tecnica ANA.pdf")

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(momento="apoio", titulo="Nota", arquivo_id=arquivo.id),
            ),
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.materiais[0].arquivo is not None
    assert lida.materiais[0].arquivo.nome == "Nota tecnica ANA.pdf"

    saida = InteracaoSaida.de_dominio(lida, ve_campos_sensiveis=True)
    assert saida.materiais[0].arquivo is not None
    assert saida.materiais[0].arquivo.nome == "Nota tecnica ANA.pdf"
    assert saida.materiais[0].arquivo.tamanho == 1234


def test_tirar_o_material_marca_o_byte_para_apagar(sessao, instituicao, autor):
    """A linha sai na transacao; o BYTE sai depois do commit.

    Sem isto, remover um material pela tela deixava a linha de `arquivo` e o
    byte no blob para sempre — o painel pagando armazenamento por documento que
    ninguem alcanca mais.

    O repositorio nao fala com o blob de proposito: ele vive dentro da
    transacao, e apagar byte ali e o jeito de destruir arquivo que um rollback
    vai fazer falta.
    """
    from app.dominio.interacao import MaterialDaAgenda

    repositorio = RepositorioSQL(sessao)
    arquivo = _arquivo(sessao, autor)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(momento="apoio", titulo="Sai", arquivo_id=arquivo.id),
            ),
        )
    )
    sessao.flush()
    # O upload nao deixa nada para apagar: ninguem perdeu arquivo ainda.
    assert repositorio.caminhos_orfaos() == []

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    lida.alterar(materiais=())
    repositorio.atualizar(lida)
    sessao.flush()

    assert repositorio.caminhos_orfaos() == [arquivo.caminho]


def test_trocar_o_arquivo_marca_o_ANTIGO_para_apagar(sessao, instituicao, autor):
    """Trocar o documento e apagar um e guardar outro.

    O material continua o mesmo — mesmo `id`, mesmo titulo — e so o arquivo
    muda. Sem olhar para o que ele apontava ANTES, o byte antigo ficaria orfao
    exatamente como na remocao, e de um jeito mais dificil de notar: a tela
    mostra o arquivo novo, e nada denuncia o velho.
    """
    from app.dominio.interacao import MaterialDaAgenda

    repositorio = RepositorioSQL(sessao)
    velho = _arquivo(sessao, autor, "v1.pdf")
    novo = _arquivo(sessao, autor, "v2.pdf")

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(momento="apoio", titulo="Ata", arquivo_id=velho.id),
            ),
        )
    )
    sessao.flush()
    repositorio.caminhos_orfaos()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    lida.alterar(
        materiais=(
            MaterialDaAgenda(
                id=lida.materiais[0].id,
                momento="apoio",
                titulo="Ata",
                arquivo_id=novo.id,
            ),
        )
    )
    repositorio.atualizar(lida)
    sessao.flush()

    assert repositorio.caminhos_orfaos() == [velho.caminho]


def test_o_material_que_fica_nao_perde_o_arquivo(sessao, instituicao, autor):
    """A prova negativa dos dois testes acima.

    Sem ela, um `_aplicar_materiais` que marcasse TODO arquivo como orfao
    passaria nos dois — e apagaria, no primeiro salvamento de qualquer campo, o
    anexo de todos os materiais da agenda.
    """
    from app.dominio.interacao import MaterialDaAgenda

    repositorio = RepositorioSQL(sessao)
    arquivo = _arquivo(sessao, autor)

    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            materiais=(
                MaterialDaAgenda(momento="apoio", titulo="Fica", arquivo_id=arquivo.id),
            ),
        )
    )
    sessao.flush()
    repositorio.caminhos_orfaos()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    lida.alterar(relato="Reuniao aconteceu")
    repositorio.atualizar(lida)
    sessao.flush()

    assert repositorio.caminhos_orfaos() == []
    lida_de_novo = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida_de_novo.materiais[0].arquivo_id == arquivo.id


# -- onde a agenda acontece ----------------------------------------------------


def test_onde_a_agenda_acontece_sobrevive_ate_a_tela(sessao, instituicao, autor):
    """As CINCO camadas, e nao quatro. Ver o teste da presenca do porta-voz.

    `modalidade` e coluna PROPRIA, e nao deducao do texto do local: ela se
    agrega — "quantas foram presenciais neste trimestre?" — e o endereco nao.
    """
    from app.esquemas.interacoes import InteracaoSaida

    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(
        _agenda(
            instituicao,
            autor,
            modalidade="hibrida",
            local="Ministerio das Cidades, bloco A, 5o andar",
        )
    )
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.modalidade == "hibrida"
    assert lida.local.startswith("Ministerio")

    saida = InteracaoSaida.de_dominio(lida, ve_campos_sensiveis=True)
    assert saida.modalidade == "hibrida"
    assert saida.local.startswith("Ministerio")


def test_hibrida_existe_porque_acontece(sessao, instituicao, autor):
    """Parte da mesa na sala e parte na chamada.

    Forcar a escolha entre presencial e online faria a base afirmar algo falso
    — e e justamente nessas que a presenca de quem faltou fica ambigua.
    """
    from app.dominio.interacao import MODALIDADES

    assert set(MODALIDADES) == {"presencial", "online", "hibrida"}


def test_modalidade_inventada_e_recusada_com_mensagem(sessao, instituicao, autor):
    """O `check` do banco protege o dado; o dominio diz o que usar.

    "remoto" e o erro provavel, e a mensagem precisa dizer que o valor e
    "online" — senao a pessoa tenta "virtual", depois "a distancia".
    """
    with pytest.raises(RegraViolada, match="online"):
        _agenda(instituicao, autor, modalidade="remoto")


def test_nao_informado_continua_nao_informado_tambem_aqui(sessao, instituicao, autor):
    """Supor presencial inventaria historia nos 60 registros da planilha."""
    repositorio = RepositorioSQL(sessao)
    salva = repositorio.adicionar(_agenda(instituicao, autor))
    sessao.flush()

    lida = repositorio.obter(salva.id, escopo=IRRESTRITO)
    assert lida.modalidade is None
    assert lida.local is None


# -- a linhagem e um GRAFO, e nao uma arvore -----------------------------------
#
# O caso que motivou a 0017: duas reunioes — uma com a agencia reguladora e
# outra com a bancada — levaram JUNTAS a uma terceira, que abriu duas frentes
# com bancos de fomento. Com um pai so, a terceira aponta para UMA das duas, e a
# outra some do encadeamento.


def test_duas_agendas_levam_juntas_a_uma_terceira(sessao, instituicao, autor):
    """O caso que a coluna unica nao conseguia representar."""
    repositorio = RepositorioSQL(sessao)

    agencia = repositorio.adicionar(_agenda(instituicao, autor, pauta="Com a agencia"))
    bancada = repositorio.adicionar(_agenda(instituicao, autor, pauta="Com a bancada"))
    sessao.flush()

    terceira = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="Decorrente das duas",
                origens=(agencia.id, bancada.id))
    )
    sessao.flush()

    lida = repositorio.obter(terceira.id, escopo=IRRESTRITO)
    assert set(lida.origens) == {agencia.id, bancada.id}


def test_uma_agenda_abre_varias_frentes(sessao, instituicao, autor):
    """O outro sentido: uma reuniao gera duas.

    A coluna unica ja permitia isto — o que ela nao permitia era o inverso. O
    teste existe para o modelo novo nao perder o que o antigo fazia.
    """
    repositorio = RepositorioSQL(sessao)
    raiz = repositorio.adicionar(_agenda(instituicao, autor, pauta="A que abriu"))
    sessao.flush()

    for banco in ("BNDES", "Caixa"):
        repositorio.adicionar(
            _agenda(instituicao, autor, pauta=f"Com o {banco}", origens=(raiz.id,))
        )
    sessao.flush()

    from app.banco.tabelas_interacoes import InteracaoOrigem

    filhas = sessao.scalars(
        select(InteracaoOrigem.interacao_id).where(InteracaoOrigem.origem_id == raiz.id)
    ).all()
    assert len(filhas) == 2


def test_o_ciclo_e_barrado_por_QUALQUER_ramo(sessao, instituicao, autor):
    """Com varios pais, o caminho se ramifica — e o ciclo pode fechar por
    qualquer ramo.

    Checar so o primeiro deixaria passar o resto. E um anel trava a leitura do
    grafo, que e exatamente a tela que esta linhagem existe para alimentar.
    """
    repositorio = RepositorioSQL(sessao)
    a = repositorio.adicionar(_agenda(instituicao, autor, pauta="A"))
    sessao.flush()
    b = repositorio.adicionar(_agenda(instituicao, autor, pauta="B", origens=(a.id,)))
    solta = repositorio.adicionar(_agenda(instituicao, autor, pauta="Solta"))
    sessao.flush()

    # `a` passaria a descender de `b`, que descende de `a`. A origem inocente
    # (`solta`) vem PRIMEIRO na lista, para provar que a guarda nao para nela.
    lida = repositorio.obter(a.id, escopo=IRRESTRITO)
    lida.alterar(origens=(solta.id, b.id))

    with pytest.raises(RegraViolada, match="ciclo"):
        repositorio.atualizar(lida)


def test_losango_nao_e_ciclo(sessao, instituicao, autor):
    """A prova negativa, e o caso que uma guarda ingenua recusaria.

    X leva a A e a B, e as duas levam a C. `C` alcanca `X` por DOIS caminhos —
    e isso e um grafo legitimo, nao um anel. Uma travessia com `union all`
    visitaria X duas vezes; com `union`, uma.
    """
    repositorio = RepositorioSQL(sessao)
    x = repositorio.adicionar(_agenda(instituicao, autor, pauta="X"))
    sessao.flush()
    a = repositorio.adicionar(_agenda(instituicao, autor, pauta="A", origens=(x.id,)))
    b = repositorio.adicionar(_agenda(instituicao, autor, pauta="B", origens=(x.id,)))
    sessao.flush()

    c = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="C", origens=(a.id, b.id))
    )
    sessao.flush()

    assert set(repositorio.obter(c.id, escopo=IRRESTRITO).origens) == {a.id, b.id}


def test_a_mesma_origem_duas_vezes_e_recusada(sessao, instituicao, autor):
    """Duplicata na lista viraria duas setas iguais no grafo."""
    repositorio = RepositorioSQL(sessao)
    raiz = repositorio.adicionar(_agenda(instituicao, autor, pauta="Raiz"))
    sessao.flush()

    with pytest.raises(RegraViolada, match="duas vezes"):
        _agenda(instituicao, autor, pauta="Filha", origens=(raiz.id, raiz.id))


def test_agenda_arquivada_some_da_linhagem_dos_dois_lados(sessao, instituicao, autor):
    """Arquivar a origem tira a seta do grafo — nos DOIS sentidos.

    O `delete` da API e SOFT: `arquivado_em` recebe data e o registro sai das
    consultas, mas a LINHA fica. Logo o `on delete cascade` da 0017 nunca
    dispara pelo fluxo real, e o elo sobrevive a origem.

    Sem este filtro o efeito medido era: a descendente continuava dizendo que
    decorre de uma agenda cujo `GET` responde 404, e a Base marcava "levou a 1"
    para uma cadeia que ninguem consegue abrir — o desenho apontando para um no
    que a tela nao mostra.
    """
    from datetime import UTC, datetime

    repositorio = RepositorioSQL(sessao)
    origem = repositorio.adicionar(_agenda(instituicao, autor, pauta="A que veio antes"))
    sessao.flush()
    filha = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="A que decorreu", origens=(origem.id,))
    )
    sessao.flush()

    assert repositorio.obter(filha.id, escopo=IRRESTRITO).origens == (origem.id,)
    assert repositorio.obter(origem.id, escopo=IRRESTRITO).derivadas == 1

    lida = repositorio.obter(origem.id, escopo=IRRESTRITO)
    lida.arquivado_em = datetime.now(UTC)
    repositorio.atualizar(lida)
    sessao.flush()
    sessao.expire_all()

    # A filha deixa de apontar para quem ninguem consegue abrir...
    assert repositorio.obter(filha.id, escopo=IRRESTRITO).origens == ()
    # ...e o ELO continua no banco, porque soft delete nao apaga nada.
    from app.banco.tabelas_interacoes import InteracaoOrigem

    assert sessao.scalar(
        select(func.count()).select_from(InteracaoOrigem)
    ) == 1


def test_arquivar_a_descendente_nao_deixa_a_origem_dizendo_que_levou_a_algo(
    sessao, instituicao, autor
):
    """O outro lado da mesma moeda.

    Se so o lado das origens filtrasse, a Base marcaria a origem como parte de
    uma cadeia — e o modal abriria mostrando ela sozinha, sem explicar por que.
    """
    from datetime import UTC, datetime

    repositorio = RepositorioSQL(sessao)
    origem = repositorio.adicionar(_agenda(instituicao, autor, pauta="Raiz"))
    sessao.flush()
    filha = repositorio.adicionar(
        _agenda(instituicao, autor, pauta="Decorrente", origens=(origem.id,))
    )
    sessao.flush()

    lida = repositorio.obter(filha.id, escopo=IRRESTRITO)
    lida.arquivado_em = datetime.now(UTC)
    repositorio.atualizar(lida)
    sessao.flush()
    sessao.expire_all()

    assert repositorio.obter(origem.id, escopo=IRRESTRITO).derivadas == 0


def test_a_linhagem_da_pagina_nao_custa_uma_consulta_por_linha(
    sessao, instituicao, autor
):
    """A REGRA CERTA PODE CUSTAR CARO EM SILENCIO.

    Uma versao desta leitura filtrava as arquivadas no proprio join, com
    `secondary`. O resultado ficava correto e o custo multiplicava sem aviso:
    400 consultas numa pagina de 200 registros. A causa e que `selectin` nao
    carrega em lote relacao AUTORREFERENTE, e com `secondary` os dois lados sao
    a mesma tabela — o SQLAlchemy cai para carregamento por objeto e nao diz
    nada.

    Este teste conta consultas. E a unica forma de a regressao aparecer antes
    de alguem abrir a Base com a base cheia.
    """
    from sqlalchemy import event

    from app.dominio.recorte import Recorte

    repositorio = RepositorioSQL(sessao)
    raiz = repositorio.adicionar(_agenda(instituicao, autor, pauta="A raiz"))
    sessao.flush()
    for n in range(12):
        repositorio.adicionar(
            _agenda(instituicao, autor, pauta=f"Decorrente {n}", origens=(raiz.id,))
        )
    sessao.flush()
    sessao.expire_all()

    consultas: list[str] = []

    def anotar(conn, cursor, instrucao, parametros, contexto, muitos):
        if "interacao_origem" in instrucao:
            consultas.append(instrucao)

    event.listen(sessao.get_bind(), "before_cursor_execute", anotar)
    try:
        pagina = repositorio.listar(
            Recorte(), escopo=IRRESTRITO, busca_em_campos_sensiveis=True, tamanho=50
        )
    finally:
        event.remove(sessao.get_bind(), "before_cursor_execute", anotar)

    assert len(pagina.itens) >= 13
    # DUAS pelas relacoes (um lado cada) e UMA para saber quais estao
    # arquivadas. Nunca proporcional ao tamanho da pagina.
    assert len(consultas) <= 4, (
        f"{len(consultas)} consultas em `interacao_origem` para "
        f"{len(pagina.itens)} registros — voltou a ser uma por linha."
    )
