"""O recorte por pilar (N1) e por tema estratégico (N2) usa a chave da `0098`.

O QUE ESTAVA ERRADO. O filtro por pilar entrava por duas condições: o texto que
o fornecedor escreveu (`tema_texto` igual ao nome do pilar) ou o pilar DERIVADO
de `tema_id`. Nenhuma das duas alcança a menção cujo único sinal de N1 é o
`atributo` — e são 71% da base da Clipei.

Medido na base local (104.670 menções) antes de mudar:

    pilar                                 alcançava  ->  alcança
    Eficiência Operacional e Qualidade       12.386      60.114
    Prosperidade Compartilhada                3.614      13.281
    Governança                                5.537      10.336
    Responsabilidade Social                   5.548       8.687
    Crescimento e Solidez Financeira          1.131       6.763
    Responsabilidade Ambiental                  839       2.888
    Inovação e Tecnologia                       646         646
    TOTAL                                    29.701     102.715

Filtrar por "Eficiência Operacional e Qualidade" devolvia 12.386 de 60.114 —
quatro de cada cinco escondidos, com a conta certa na tela.

O QUE ESTE ARQUIVO PROTEGE:

1. que o conjunto novo seja SUPERCONJUNTO do antigo — a mudança pode ganhar
   linhas, nunca perder. É o teste que torna "mantém tudo funcionando"
   verificável em vez de prometido;
2. que o recorte alcance a menção ligada SÓ por pilar (`bloco_tema_id` sem
   `tema_id`), que é o caso que não existia antes da `0098`;
3. que os dois níveis empilhem com `and`, como no CRM — escolher o pilar e
   dentro dele o tema estratégico estreita, não alarga.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.banco.repositorio_score import condicoes_do_filtro
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.dominio.score import FiltroDeMencoes
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

MES = date(2026, 1, 1)


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
def arvore(sessao: Session):
    """Um pilar com um tema estratégico e um subtema, do cadastro de verdade.

    DO CADASTRO, e não criado aqui: é o cadastro que decide quem é pai de quem,
    e uma árvore montada no teste concordaria consigo mesma.
    """
    linha = sessao.execute(
        select(BlocoTema.id, BlocoTema.nome, MacroTema.id, MacroTema.nome, Tema.id)
        .join(MacroTema, MacroTema.bloco_tema_id == BlocoTema.id)
        .join(Tema, Tema.macro_tema_id == MacroTema.id)
        .where(
            BlocoTema.ativo.is_(True),
            MacroTema.ativo.is_(True),
            Tema.ativo.is_(True),
        )
        .order_by(BlocoTema.id, MacroTema.id, Tema.id)
        .limit(1)
    ).first()
    assert linha is not None, "o cadastro não tem uma cadeia N1>N2>N3 ativa"
    return linha


@pytest.fixture
def fonte(sessao: Session) -> int:
    ident = sessao.scalar(select(ScoreFonte.id).order_by(ScoreFonte.id).limit(1))
    assert ident is not None, "nenhuma fonte cadastrada"
    return ident


def _mencao(sessao: Session, fonte_id: int, **campos) -> uuid.UUID:
    """Uma menção com o mínimo para existir, mais o que o caso pede."""
    ident = uuid.uuid4()
    sessao.add(
        Mencao(
            id=ident,
            fonte_id=fonte_id,
            mes=MES,
            data=MES,
            sentimento="neg",
            **campos,
        )
    )
    sessao.flush()
    return ident


def _acha(sessao: Session, filtro: FiltroDeMencoes, ident: uuid.UUID) -> bool:
    """A menção `ident` passa pelo recorte?"""
    return (
        sessao.scalar(
            select(func.count())
            .select_from(Mencao)
            .where(Mencao.id == ident, *condicoes_do_filtro(filtro))
        )
        == 1
    )


# -- 2. o caso que a 0098 criou ------------------------------------------------


def test_o_recorte_acha_a_mencao_ligada_so_pelo_pilar(sessao, fonte, arvore) -> None:
    """`bloco_tema_id` preenchido, `tema_id` nulo — 71% da base da Clipei.

    É O CASO QUE NÃO PASSAVA. Sem `tema_id` não há de onde derivar o pilar, e o
    `tema_texto` dela é um assunto que o cadastro não reconhece, não o nome de um
    pilar — então as duas condições antigas falhavam as duas.
    """
    n1_id, n1_nome, _n2_id, _n2_nome, _n3_id = arvore
    ident = _mencao(
        sessao,
        fonte,
        bloco_tema_id=n1_id,
        tema_texto="Assunto que o cadastro não tem",
        atributo="2. Qualquer coisa",
    )
    assert _acha(sessao, FiltroDeMencoes(tema_n1=n1_nome), ident)


def test_o_recorte_acha_a_mencao_ligada_so_pelo_tema_estrategico(
    sessao, fonte, arvore
) -> None:
    """`macro_tema_id` preenchido, `tema_id` nulo — o fornecedor que fala N2."""
    _n1_id, _n1_nome, n2_id, n2_nome, _n3_id = arvore
    ident = _mencao(sessao, fonte, macro_tema_id=n2_id, tema_texto="Outro assunto")
    assert _acha(sessao, FiltroDeMencoes(tema_n2=n2_nome), ident)


def test_o_pilar_errado_nao_acha(sessao, fonte, arvore) -> None:
    """A condição nova não é um `or` frouxo que deixa tudo passar."""
    n1_id, _n1_nome, _n2_id, _n2_nome, _n3_id = arvore
    outro = sessao.scalar(
        select(BlocoTema.nome)
        .where(BlocoTema.ativo.is_(True), BlocoTema.id != n1_id)
        .order_by(BlocoTema.id)
        .limit(1)
    )
    assert outro, "o cadastro só tem um pilar; o teste não provaria nada"
    ident = _mencao(sessao, fonte, bloco_tema_id=n1_id)
    assert not _acha(sessao, FiltroDeMencoes(tema_n1=outro), ident)


# -- 1. superconjunto: nada que achava hoje deixa de ser achado ----------------


def test_o_recorte_por_pilar_ainda_acha_pelo_caminho_antigo(
    sessao, fonte, arvore
) -> None:
    """Os DOIS caminhos antigos continuam valendo, com `bloco_tema_id` NULO.

    É a verificação de superconjunto na forma que importa: a menção gravada
    ANTES da `0098` tem as duas colunas novas nulas, e tem de continuar entrando
    pelo caminho que a achava. Se alguém "simplificar" a condição trocando o
    `or` por só a coluna nova, estes dois casos falham.
    """
    n1_id, n1_nome, _n2_id, _n2_nome, n3_id = arvore

    #: (a) pelo `tema_texto` igual ao nome do pilar.
    pelo_texto = _mencao(sessao, fonte, tema_texto=n1_nome)
    assert _acha(sessao, FiltroDeMencoes(tema_n1=n1_nome), pelo_texto)

    #: (b) pelo pilar DERIVADO de `tema_id`, sem as colunas novas.
    pelo_tema_id = _mencao(sessao, fonte, tema_id=n3_id)
    assert _acha(sessao, FiltroDeMencoes(tema_n1=n1_nome), pelo_tema_id)
    assert sessao.scalar(
        select(Mencao.bloco_tema_id).where(Mencao.id == pelo_tema_id)
    ) is None, "o caso (b) precisa ter a coluna nova NULA para provar o que prova"


def test_o_recorte_por_n2_ainda_acha_pelo_tema_id(sessao, fonte, arvore) -> None:
    """Idem para o N2: `macro_tema_id` nulo, `tema_id` preenchido."""
    _n1_id, _n1_nome, _n2_id, n2_nome, n3_id = arvore
    ident = _mencao(sessao, fonte, tema_id=n3_id)
    assert _acha(sessao, FiltroDeMencoes(tema_n2=n2_nome), ident)


# -- 3. os níveis empilham -----------------------------------------------------


def test_pilar_e_tema_estrategico_empilham_com_and(sessao, fonte, arvore) -> None:
    """Escolher os dois ESTREITA. Um `or` entre níveis alargaria o recorte.

    A menção tem o pilar certo e NÃO tem o tema estratégico pedido, então o
    recorte combinado não pode achá-la.
    """
    n1_id, n1_nome, n2_id, _n2_nome, _n3_id = arvore
    outro_n2 = sessao.scalar(
        select(MacroTema.nome)
        .where(MacroTema.ativo.is_(True), MacroTema.id != n2_id)
        .order_by(MacroTema.id)
        .limit(1)
    )
    assert outro_n2, "o cadastro só tem um tema estratégico"

    ident = _mencao(sessao, fonte, bloco_tema_id=n1_id)
    assert _acha(sessao, FiltroDeMencoes(tema_n1=n1_nome), ident), (
        "o recorte pelo pilar sozinho deveria achá-la"
    )
    assert not _acha(
        sessao, FiltroDeMencoes(tema_n1=n1_nome, tema_n2=outro_n2), ident
    ), "pilar certo + tema estratégico errado não pode achar: os níveis empilham"


# -- a condição não mudou de forma --------------------------------------------


def test_o_recorte_por_pilar_e_superconjunto_do_antigo(sessao, fonte, arvore) -> None:
    """Varre as combinações de colunas e exige: achava antes => acha agora.

    SOBRE AS OITO COMBINAÇÕES de (`bloco_tema_id`, `tema_id`, `tema_texto`), que
    é o espaço inteiro do que a condição olha. Para cada uma, calcula se o
    recorte ANTIGO a achava — a regra antiga está escrita aqui, em Python, de
    propósito: é o registro do que existia, e se a condição nova deixar de ser
    superconjunto o teste diz exatamente em qual combinação.
    """
    n1_id, n1_nome, _n2_id, _n2_nome, n3_id = arvore
    combinacoes = [
        {},
        {"bloco_tema_id": n1_id},
        {"tema_id": n3_id},
        {"tema_texto": n1_nome},
        {"bloco_tema_id": n1_id, "tema_id": n3_id},
        {"bloco_tema_id": n1_id, "tema_texto": n1_nome},
        {"tema_id": n3_id, "tema_texto": n1_nome},
        {"bloco_tema_id": n1_id, "tema_id": n3_id, "tema_texto": n1_nome},
    ]
    perdidas = []
    for campos in combinacoes:
        ident = _mencao(sessao, fonte, **campos)
        #: A REGRA ANTIGA, escrita à mão: `tema_texto == nome` OU o pilar
        #: derivado de `tema_id`. Não olhava `bloco_tema_id`, que nem existia.
        achava_antes = campos.get("tema_texto") == n1_nome or (
            campos.get("tema_id") == n3_id
        )
        acha_agora = _acha(sessao, FiltroDeMencoes(tema_n1=n1_nome), ident)
        if achava_antes and not acha_agora:
            perdidas.append(campos)

    assert not perdidas, (
        "o recorte novo PERDEU menções que o antigo achava: "
        f"{perdidas}. A condição tem de ser superconjunto."
    )
