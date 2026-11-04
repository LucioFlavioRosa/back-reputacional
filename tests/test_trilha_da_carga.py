"""A trilha da carga: quando cada base foi atualizada, por quem, e quanto entrou.

O QUE ESTES TESTES PROTEGEM, e por que a trilha existe:

* A CARGA DE ZERO MENÇÃO TAMBÉM DEIXA RASTRO. É o caso que torna a tabela
  necessária, e o que impede responder a pergunta com
  `max(score_mes_fonte.atualizado_em)`: quem recorta por lista e não acha
  veículo nenhum tem os meses APAGADOS e nada inserido, então aquele carimbo não
  anda e a tela diria "atualizado há 40 dias" depois de uma carga feita hoje.
* A IRMÃ QUE FICA SEM NADA não deixa rastro, e também de propósito: ela não
  apaga o mês dela, então nada mudou ali. A linha segue a escrita, não a
  tentativa — e a diferença entre as duas irmãs é se ela DECLARA lista.
* as fontes irmãs do mesmo arquivo compartilham o `lote_id`;
* quem não se identifica grava `desconhecida` — visível —, e não nada.

A IMUTABILIDADE mora em `test_papel_restrito.py`, com o papel restrito de
verdade: aqui a sessão é dona do banco e poderia tudo.
"""

from __future__ import annotations

import io
import uuid
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_catalogo import CategoriaPublico, SubcategoriaPublico
from app.banco.tabelas_score import CargaDeBase, Mencao, ScoreFonte, ScoreMesFonte
from app.banco.tabelas_stakeholders import Instituicao, ParSemelhante
from app.casos_de_uso import atores_duplicados, ingerir_mencoes, trilha_da_carga
from app.dominio.ingestao_score import Leitura, MencaoLida
from app.dominio.texto import normalizar
from tests.test_e2e_postgres import URL

_engine = create_engine(URL, pool_pre_ping=True)

_CABECALHO = ["Data", "Classificação", "Veículo", "Público-alvo"]


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
def usuario(sessao) -> Usuario:
    papel = sessao.scalars(select(Papel).where(Papel.codigo == "plataforma_edicao")).first()
    registro = Usuario(
        entra_object_id=f"oid-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@aegea.com.br",
        nome="Quem Carregou",
        papel_id=papel.id,
        acesso_irrestrito=True,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def _planilha(linhas: list[list[object]]) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "Clipping"
    aba.append(_CABECALHO)
    for linha in linhas:
        aba.append(linha)
    memoria = io.BytesIO()
    livro.save(memoria)
    return memoria.getvalue()


def _fonte(sessao, codigo: str, *, com_lista: bool, arquivo: str | None = None) -> ScoreFonte:
    """Uma fonte no grão em que o banco a guarda.

    `com_lista` faz dela uma fonte que recorta pela lista de veículos — é o que
    torna legítima a carga de zero menção. `arquivo` é o que liga fontes irmãs.
    """
    molde = sessao.scalar(select(ScoreFonte).where(ScoreFonte.codigo == "clipei"))
    assert molde is not None
    mapeamento: dict[str, object] = {
        "aba": "Clipping",
        "colunas": {
            "data": "Data",
            "sentimento": "Classificação",
            "veiculo": "Veículo",
        },
    }
    if com_lista:
        mapeamento["lista_de_veiculos"] = "imprensa_economica"
    if arquivo is not None:
        mapeamento["arquivo"] = arquivo
    nova = ScoreFonte(
        codigo=codigo,
        nome=f"Fonte {codigo}",
        fornecedor="Clipei",
        lente_id=molde.lente_id,
        ordem=99,
        mapeamento_colunas=mapeamento,
    )
    sessao.add(nova)
    sessao.flush()
    return nova


def _marcar(sessao, nome: str) -> None:
    """Cadastra o veículo já na lista que a lente Mercado recorta."""
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
    assert alvo is not None
    sessao.add(
        Instituicao(
            nome=nome,
            nome_normalizado=normalizar(nome),
            tipo="veiculo",
            subcategoria_publico_id=alvo,
        )
    )
    sessao.flush()


def _trilha(sessao, fonte: ScoreFonte) -> list[CargaDeBase]:
    return list(
        sessao.scalars(
            select(CargaDeBase)
            .where(CargaDeBase.fonte_id == fonte.id)
            .order_by(CargaDeBase.concluida_em)
        )
    )


# -- a carga normal -------------------------------------------------------------


def test_a_carga_grava_quem_quando_e_quanto(sessao, usuario):
    fonte = _fonte(sessao, "zz_trilha_1", com_lista=False)

    ingerir_mencoes.ingerir(
        sessao,
        fonte,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz1", "Geral"],
                [date(2026, 8, 4), "Negativa", "Jornal do Bairro zz1", "Geral"],
            ]
        ),
        (),
        trilha_da_carga.Procedencia(
            origem="api:planilha",
            arquivo="clipping-agosto.xlsx",
            usuario_id=usuario.id,
        ),
    )

    cargas = _trilha(sessao, fonte)
    assert len(cargas) == 1
    carga = cargas[0]
    assert carga.linhas == 2
    assert carga.meses == [date(2026, 8, 1)]
    assert carga.origem == "api:planilha"
    assert carga.arquivo == "clipping-agosto.xlsx"
    assert carga.usuario_id == usuario.id
    assert carga.concluida_em is not None


def test_o_carimbo_e_o_FIM_e_nao_o_inicio_da_transacao(sessao):
    """`now()` ficaria congelado no começo da transação.

    No Postgres, `now()` é `transaction_timestamp()`: duas leituras com dois
    segundos entre elas devolvem o mesmo valor. A ingestão mede 62 s, então uma
    coluna chamada `concluida_em` com `default now()` registraria o COMEÇO da
    carga. A `0115` usa `clock_timestamp()`, e é isto que esta comparação cobra:
    com `now()` os dois valores seriam IGUAIS, e a asserção falha.
    """
    fonte = _fonte(sessao, "zz_trilha_8", com_lista=False)
    comeco_da_transacao = sessao.execute(text("select now()")).scalar()

    ingerir_mencoes.ingerir(
        sessao,
        fonte,
        _planilha([[date(2026, 8, 3), "Positiva", "Valor Econômico zz8", "Geral"]]),
        (),
        trilha_da_carga.Procedencia(origem="api:planilha"),
    )

    assert _trilha(sessao, fonte)[0].concluida_em > comeco_da_transacao


def test_cada_carga_acrescenta_uma_linha(sessao):
    """Resubir o mês não sobrescreve o rastro da carga anterior."""
    fonte = _fonte(sessao, "zz_trilha_2", com_lista=False)
    planilha = _planilha([[date(2026, 8, 3), "Positiva", "Valor Econômico zz2", "Geral"]])

    for _ in range(2):
        ingerir_mencoes.ingerir(
            sessao, fonte, planilha, (), trilha_da_carga.Procedencia(origem="api:planilha")
        )

    assert len(_trilha(sessao, fonte)) == 2


# -- o caso que torna a tabela necessária ---------------------------------------


def test_a_carga_de_recorte_VAZIO_tambem_grava(sessao):
    """O furo que derrubaria `max(score_mes_fonte.atualizado_em)`.

    Uma fonte que recorta por lista e não acha veículo nenhum é caso LEGÍTIMO: o
    mês é substituído por zero. `regravar` apaga o agregado e não insere nada,
    então nenhum carimbo de `score_mes_fonte` ou de `mencao` anda — e sem esta
    linha a carga de hoje seria invisível.
    """
    fonte = _fonte(sessao, "zz_trilha_3", com_lista=True)

    ingerir_mencoes.ingerir(
        sessao,
        fonte,
        #: NENHUM destes veículos está na lista.
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Jornal do Bairro zz3", "Geral"],
                [date(2026, 8, 4), "Negativa", "Boletim do Centro zz3", "Geral"],
            ]
        ),
        (),
        trilha_da_carga.Procedencia(origem="api:planilha", arquivo="vazio.xlsx"),
    )

    cargas = _trilha(sessao, fonte)
    assert len(cargas) == 1, "a carga de zero menção não deixou rastro"
    assert cargas[0].linhas == 0
    assert cargas[0].meses == [date(2026, 8, 1)]

    #: E A PROVA DE QUE O CAMINHO ANTIGO SERIA CEGO: o agregado do mês não tem
    #: linha nenhuma, então `max(atualizado_em)` não teria como andar.
    agregado = sessao.scalars(
        select(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes == date(2026, 8, 1)
        )
    ).all()
    assert agregado == []


def test_a_irma_SEM_LISTA_que_fica_sem_nada_nao_grava(sessao):
    """Nada mudou naquela fonte, então a última carga dela não deve andar.

    A PARTIÇÃO É EXCLUSIVA (ver `_recorte_por_lista`): quem declara a lista fica
    com os veículos dela, e a irmã que não declara fica com TODO O RESTO. Num
    arquivo em que todo veículo está na lista, o resto é vazio — e aí
    `_ingerir_uma` retorna antes de `regravar`, porque mês vazio numa irmã não é
    instrução de esquecer o mês dela. Sem escrita, não há carga a registrar.

    NÃO CONFUNDIR COM A IRMÃ QUE DECLARA LISTA: aquela, vindo vazia, SUBSTITUI o
    mês por zero — a base mudou, e `test_a_carga_de_recorte_VAZIO_tambem_grava`
    cobre o rastro dela.
    """
    _marcar(sessao, "Valor Econômico zz4")
    _marcar(sessao, "InfoMoney zz4")
    com_lista = _fonte(sessao, "zz_trilha_4a", com_lista=True, arquivo="zz_pacote_4")
    sem_lista = _fonte(sessao, "zz_trilha_4b", com_lista=False, arquivo="zz_pacote_4")

    #: O MÊS DA IRMÃ JÁ TEM DADO, e a afirmação é que ele SOBREVIVE. Gravado por
    #: `add` e não por `regravar`, que deixaria rastro e falsearia o teste.
    sessao.add(
        Mencao(
            fonte_id=sem_lista.id,
            mes=date(2026, 8, 1),
            data=date(2026, 8, 1),
            sentimento="pos",
            veiculo="Carga anterior zz4",
        )
    )
    sessao.flush()

    ingerir_mencoes.ingerir(
        sessao,
        com_lista,
        #: TODOS na lista: não sobra resto para a irmã.
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz4", "Geral"],
                [date(2026, 8, 4), "Negativa", "InfoMoney zz4", "Geral"],
            ]
        ),
        (),
        trilha_da_carga.Procedencia(origem="api:planilha"),
    )

    assert len(_trilha(sessao, com_lista)) == 1
    assert _trilha(sessao, com_lista)[0].linhas == 2
    assert _trilha(sessao, sem_lista) == []
    #: E O DADO DELA CONTINUA LÁ: a trilha vazia não é só ausência de linha, é a
    #: afirmação de que nada foi apagado naquela fonte.
    sobreviveu = sessao.scalars(
        select(Mencao).where(
            Mencao.fonte_id == sem_lista.id, Mencao.mes == date(2026, 8, 1)
        )
    ).all()
    assert len(sobreviveu) == 1
    assert sobreviveu[0].veiculo == "Carga anterior zz4"


# -- o laço entre fontes irmãs --------------------------------------------------


def test_as_fontes_irmas_compartilham_o_lote(sessao):
    """Uma subida é uma subida, mesmo alimentando duas lentes.

    O export da Clipei vira Imprensa e, recortado, Mercado. Sem o `lote_id`
    comum, a aba mostraria duas cargas onde houve uma.
    """
    _marcar(sessao, "Valor Econômico zz5")
    principal = _fonte(sessao, "zz_trilha_5a", com_lista=False, arquivo="zz_pacote_5")
    irma = _fonte(sessao, "zz_trilha_5b", com_lista=True, arquivo="zz_pacote_5")

    ingerir_mencoes.ingerir(
        sessao,
        principal,
        _planilha(
            [
                [date(2026, 8, 3), "Positiva", "Valor Econômico zz5", "Geral"],
                [date(2026, 8, 4), "Negativa", "Jornal do Bairro zz5", "Geral"],
            ]
        ),
        (),
        trilha_da_carga.Procedencia(origem="api:planilha", arquivo="clipping.xlsx"),
    )

    da_principal = _trilha(sessao, principal)
    da_irma = _trilha(sessao, irma)
    assert len(da_principal) == 1
    assert len(da_irma) == 1
    assert da_principal[0].lote_id == da_irma[0].lote_id
    #: UMA MENÇÃO CADA, e a soma é o arquivo inteiro: a partição é exclusiva —
    #: a irmã fica com os veículos da lista, a principal com o resto. Se um dia
    #: a soma passar das linhas do arquivo, a matéria voltou a contar duas vezes.
    assert da_principal[0].linhas == 1
    assert da_irma[0].linhas == 1
    assert da_principal[0].linhas + da_irma[0].linhas == 2


def test_cargas_diferentes_nao_compartilham_o_lote(sessao):
    fonte = _fonte(sessao, "zz_trilha_6", com_lista=False)
    planilha = _planilha([[date(2026, 8, 3), "Positiva", "Valor Econômico zz6", "Geral"]])

    for _ in range(2):
        ingerir_mencoes.ingerir(
            sessao, fonte, planilha, (), trilha_da_carga.Procedencia(origem="api:planilha")
        )

    lotes = {carga.lote_id for carga in _trilha(sessao, fonte)}
    assert len(lotes) == 2


# -- quem não se identifica -----------------------------------------------------


def test_quem_nao_se_identifica_grava_desconhecida(sessao):
    """Carga sem rastro é pior que carga com rastro anônimo.

    A primeira é invisível; a segunda é um defeito que se denuncia na aba. É por
    isso que `Procedencia.origem` tem padrão em vez de ser obrigatória.
    """
    fonte = _fonte(sessao, "zz_trilha_7", com_lista=False)

    ingerir_mencoes.regravar(
        sessao,
        fonte,
        Leitura(
            mencoes=(
                MencaoLida(
                    mes=date(2026, 8, 1),
                    data=date(2026, 8, 3),
                    sentimento="pos",
                    veiculo="Valor Econômico zz7",
                ),
            ),
            descartes={},
            linhas=1,
        ),
    )

    cargas = _trilha(sessao, fonte)
    assert len(cargas) == 1
    assert cargas[0].origem == "desconhecida"
    assert cargas[0].origem in trilha_da_carga.ORIGENS
    assert cargas[0].usuario_id is None
    assert isinstance(cargas[0].lote_id, uuid.UUID)


# -- a subida refaz o pareamento dos duplicados (0118) --------------------------


def test_a_subida_que_CRIA_veiculo_refaz_o_pareamento(sessao):
    """O gancho que tirou o 504 da tela de duplicados.

    A comparação par a par saiu da requisição e passou a rodar ao fim da subida,
    que é quando o cadastro de fato cresce — `veiculos_da_imprensa.criar` registra
    2.631 criações numa tela só.
    """
    sessao.execute(delete(ParSemelhante))
    sessao.flush()
    fonte = _fonte(sessao, "zz_pareia_1", com_lista=False)
    #: DOIS NOMES QUE SE PARECEM, e o segundo é o handle do primeiro — o par que a
    #: fila existe para achar.
    planilha = _planilha(
        [
            [date(2026, 8, 3), "Positiva", "Jornal da Serra zzpar", "Geral"],
            [date(2026, 8, 4), "Positiva", "jornaldaserra zzpar", "Geral"],
        ]
    )

    ingerir_mencoes.ingerir(
        sessao,
        fonte,
        planilha,
        #: AUTORIZA A CRIAÇÃO: sem isto a subida não cria cadastro, e o
        #: pareamento não tem por que mudar.
        ("Jornal da Serra zzpar", "jornaldaserra zzpar"),
        trilha_da_carga.Procedencia(origem="api:planilha"),
    )

    assert atores_duplicados.calculado_em(sessao) is not None
    pares = sessao.scalar(select(func.count()).select_from(ParSemelhante))
    assert pares >= 1, "a subida criou veículo e não refez o pareamento"


def test_a_subida_que_NAO_CRIA_nada_nao_refaz_o_pareamento(sessao):
    """O pareamento depende dos NOMES do cadastro, não das menções.

    Recalcular à toa somaria 43 s medidos a cada planilha — é a diferença entre
    pagar quando o mundo muda e pagar sempre.
    """
    sessao.execute(delete(ParSemelhante))
    sessao.flush()
    fonte = _fonte(sessao, "zz_pareia_2", com_lista=False)

    ingerir_mencoes.ingerir(
        sessao,
        fonte,
        _planilha([[date(2026, 8, 3), "Positiva", "Veiculo Qualquer zzpar2", "Geral"]]),
        #: NINGUÉM AUTORIZOU CRIAÇÃO: o padrão é vazio.
        (),
        trilha_da_carga.Procedencia(origem="api:planilha"),
    )

    assert atores_duplicados.calculado_em(sessao) is None
