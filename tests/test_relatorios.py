"""O registro de geração de relatório.

Este contexto NÃO gera PDF, e os testes refletem isso. O documento sai da
impressão do navegador; o que faltava era saber que ele existiu — e esse é o
evento que `seguranca/ARQUITETURA.md` lista como ausente para responder "o que saiu
daqui?" depois de um incidente.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_relatorios import (
    RelatorioRegistro,
)
from app.casos_de_uso import registrar_relatorio
from app.dominio.erros import NaoAutorizado, RegraViolada
from app.dominio.recorte import Recorte
from app.dominio.relatorio import Relatorio
from main import app
from tests.test_e2e_postgres import URL, corpo

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
def cliente(sessao):
    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    from app.banco.tabelas_stakeholders import (
        Instituicao,
        PessoaAegea,
    )

    sufixo = uuid4().hex[:6]
    valor = Instituicao(
        nome=f"Veículo {sufixo}", nome_normalizado=f"veiculo {sufixo}",
        tipo="veiculo", uf="SP",
    )
    a = PessoaAegea(nome=f"A {sufixo}", nome_normalizado=f"a {sufixo}", eh_porta_voz=True)
    b = PessoaAegea(nome=f"B {sufixo}", nome_normalizado=f"b {sufixo}", eh_porta_voz=True)
    sessao.add_all([valor, a, b])
    sessao.flush()
    return {"instituicao": valor, "radames": a, "andre": b}


# -- o vocabulário de seções ---------------------------------------------------


def test_secao_desconhecida_e_recusada():
    """Texto livre viraria seis grafias da mesma seção e nenhuma consulta útil.

    O mesmo motivo pelo qual `acesso_log.resultado` tem `check` no banco.
    """
    with pytest.raises(RegraViolada, match="desconhecida"):
        Relatorio(secoes=("inventada",), filtros={}, criado_por=uuid4())


def test_relatorio_sem_secao_e_recusado():
    with pytest.raises(RegraViolada, match="ao menos uma"):
        Relatorio(secoes=(), filtros={}, criado_por=uuid4())


def test_base_marca_o_relatorio_como_portador_de_registros():
    """`base` é a seção que muda a natureza do documento.

    Todas as outras são números agregados; com ela, o relatório é uma
    exportação com capa.
    """
    assert Relatorio(secoes=("base",), filtros={}, criado_por=uuid4()).leva_registros
    assert not Relatorio(secoes=("resumo",), filtros={}, criado_por=uuid4()).leva_registros


# -- o total é contado aqui, não recebido --------------------------------------


def test_o_total_e_contado_pelo_servidor(cliente, semente, sessao):
    """Receber o total do cliente seria aceitar que quem exporta declare quanto.

    O número existe exatamente para o caso em que essa declaração não é
    confiável.
    """
    for _ in range(3):
        assert cliente.post("/api/interacoes", json=corpo(semente)).status_code == 201

    resposta = cliente.post(
        "/api/relatorios?frente=imprensa", json={"secoes": ["base"]}
    )
    assert resposta.status_code == 201

    linhas = cliente.get("/api/interacoes?frente=imprensa").json()["total"]
    assert resposta.json()["total_de_registros"] == linhas


def test_o_total_respeita_o_recorte(cliente, semente):
    """O relatório registra o tamanho DO RECORTE, não da base."""
    cliente.post("/api/interacoes", json=corpo(semente, frente="imprensa"))
    cliente.post("/api/interacoes", json=corpo(semente, frente="governo"))

    tudo = cliente.post("/api/relatorios", json={"secoes": ["resumo"]}).json()
    so_governo = cliente.post(
        "/api/relatorios?frente=governo", json={"secoes": ["resumo"]}
    ).json()

    assert so_governo["total_de_registros"] < tudo["total_de_registros"]


def test_o_recorte_registrado_e_o_da_query_string(cliente, semente, sessao):
    """Receber os filtros no corpo abriria a porta para o relatório registrar um
    recorte e contar outro — e a trilha passaria a mentir sobre o que saiu."""
    cliente.post("/api/interacoes", json=corpo(semente))
    cliente.post("/api/relatorios?frente=imprensa&uf=SP", json={"secoes": ["resumo"]})
    sessao.flush()

    registro = sessao.scalars(
        select(RelatorioRegistro).order_by(RelatorioRegistro.criado_em.desc())
    ).first()
    assert registro.filtros == {"frente": "imprensa", "uf": "SP"}


def test_filtros_vazios_nao_enchem_a_coluna(cliente, semente, sessao):
    """Guardar `{"frente": null, "uf": null, ...}` tornaria ilegível o que de
    fato foi filtrado."""
    cliente.post("/api/relatorios", json={"secoes": ["resumo"]})
    sessao.flush()

    registro = sessao.scalars(
        select(RelatorioRegistro).order_by(RelatorioRegistro.criado_em.desc())
    ).first()
    assert registro.filtros == {}


# -- o histórico ---------------------------------------------------------------


def cria_usuario(sessao, papel_codigo: str) -> Usuario:
    papel_id = sessao.scalars(select(Papel.id).where(Papel.codigo == papel_codigo)).first()
    sufixo = uuid4().hex[:8]
    registro = Usuario(
        entra_object_id=f"oid-{sufixo}",
        email=f"{sufixo}@aegea.com.br",
        nome=f"Pessoa {sufixo}",
        papel_id=papel_id,
        acesso_irrestrito=True,
    )
    sessao.add(registro)
    sessao.flush()
    return registro


def como(sessao, registro: Usuario):
    from app.casos_de_uso.provisionar_usuario import (
        carregar,
    )

    return carregar(sessao, registro.id)


def test_historico_exige_administrar_acessos(cliente, semente, sessao):
    """A trilha diz o que cada pessoa levou embora.

    Isso é informação sobre as PESSOAS, não sobre as interações — quem lê
    precisa ter o papel de quem responde por isso.
    """
    analista = como(sessao, cria_usuario(sessao, "analista"))
    with pytest.raises(NaoAutorizado):
        registrar_relatorio.historico(sessao, solicitante=analista)


def test_historico_mostra_quem_gerou_e_quanto(cliente, semente, sessao):
    admin = cria_usuario(sessao, "coordenacao")
    cliente.post("/api/interacoes", json=corpo(semente))

    registrar_relatorio.registrar(
        sessao,
        secoes=("resumo", "base"),
        recorte=Recorte(frente="imprensa"),
        usuario=como(sessao, admin),
    )
    sessao.flush()

    linhas = registrar_relatorio.historico(sessao, solicitante=como(sessao, admin))
    primeira = linhas[0]

    assert primeira.criado_por == admin.nome
    assert primeira.leva_registros
    assert "frente=imprensa" in primeira.resumo_do_recorte


def test_recorte_sem_filtro_aparece_legivel_no_historico(cliente, semente, sessao):
    admin = cria_usuario(sessao, "coordenacao")
    registrar_relatorio.registrar(
        sessao, secoes=("resumo",), recorte=Recorte(), usuario=como(sessao, admin)
    )
    sessao.flush()

    linhas = registrar_relatorio.historico(sessao, solicitante=como(sessao, admin))
    assert linhas[0].resumo_do_recorte == "todo o histórico"


# -- o escopo vale aqui também -------------------------------------------------


def test_o_total_respeita_o_escopo_de_quem_gera(cliente, semente, sessao):
    """Sem isso, o relatório de um externo contaria a base inteira.

    A trilha registraria "5.000 linhas" para quem alcança 40 — e o alerta de
    volume dispararia no alvo errado, todo dia, até alguém desligá-lo.
    """
    from app.dominio.identidade import Escopo

    cliente.post("/api/interacoes", json=corpo(semente, frente="imprensa"))
    cliente.post("/api/interacoes", json=corpo(semente, frente="governo"))
    sessao.flush()

    admin = cria_usuario(sessao, "coordenacao")
    irrestrito = como(sessao, admin)

    # `replace`, e não reconstruir campo a campo: se `UsuarioAtual` ganhar um
    # campo obrigatório, o teste quebraria por forma e não por comportamento.
    restrito = replace(irrestrito, escopo=Escopo(frentes=frozenset({"governo"})))

    completo = registrar_relatorio.registrar(
        sessao, secoes=("resumo",), recorte=Recorte(), usuario=irrestrito
    )
    parcial = registrar_relatorio.registrar(
        sessao, secoes=("resumo",), recorte=Recorte(), usuario=restrito
    )

    assert parcial.total_de_registros < completo.total_de_registros


# -- a trilha não se reescreve -------------------------------------------------


def test_a_aplicacao_nao_altera_relatorio_gravado(sessao):
    """A migration 0009 revoga `update` e `delete` em `relatorio`.

    O `alter default privileges` da 0009 concede em massa; sem a revogação,
    quem tivesse a connection string reescreveria a trilha de exportações —
    exatamente a que diz o que saiu daqui.
    """
    concedido = sessao.execute(
        text(
            "select has_table_privilege('painel_app', 'relatorio', 'INSERT') as inserir, "
            "       has_table_privilege('painel_app', 'relatorio', 'UPDATE') as alterar, "
            "       has_table_privilege('painel_app', 'relatorio', 'DELETE') as remover"
        )
    ).one()
    assert concedido.inserir, "a aplicação precisa registrar"
    assert not concedido.alterar
    assert not concedido.remover


# -- o que saiu não é o que se estava olhando ---------------------------------


def test_o_documento_leva_no_maximo_o_teto_impresso(cliente, semente):
    """O documento registra o que SAIU, e não o tamanho do recorte.

    O layout impresso corta em `LINHAS_NO_DOCUMENTO`. Registrar o recorte
    inteiro anotaria um relatório sobre 6.000 registros como se 6.000 linhas
    tivessem saído, e o alerta de volume dispararia no alvo errado — alerta que
    erra é alerta que alguém desliga.

    O CSV é o oposto e por isso tem tratamento próprio: ele não corta.
    """
    from app.dominio.relatorio import (
        LINHAS_NO_DOCUMENTO,
        Relatorio,
    )

    grande = Relatorio(
        secoes=("base",), filtros={}, criado_por=uuid4(), total_de_registros=6000
    )
    assert grande.total_de_registros == 6000, "o contexto continua registrado"
    assert grande.registros_no_documento == LINHAS_NO_DOCUMENTO

    pequeno = Relatorio(
        secoes=("base",), filtros={}, criado_por=uuid4(), total_de_registros=12
    )
    assert pequeno.registros_no_documento == 12


def test_relatorio_so_de_numeros_nao_leva_linha_nenhuma(cliente, semente):
    from app.dominio.relatorio import Relatorio

    so_agregados = Relatorio(
        secoes=("resumo", "status"), filtros={}, criado_por=uuid4(), total_de_registros=6000
    )
    assert so_agregados.registros_no_documento == 0


def test_secoes_repetidas_nao_incham_o_registro(cliente, semente, sessao):
    """`["base"] * 500` passaria pela validação de vocabulário.

    O limite de corpo reduz o dano, mas o histórico é o que a coluna existe para
    tornar legível.
    """
    resposta = cliente.post(
        "/api/relatorios", json={"secoes": ["base", "base", "resumo", "base"]}
    )
    assert resposta.status_code == 201
    sessao.flush()

    registro = sessao.scalars(
        select(RelatorioRegistro).order_by(RelatorioRegistro.criado_em.desc())
    ).first()
    # Ordem preservada: quem escolheu "base" primeiro vê "base" primeiro.
    assert registro.secoes == ["base", "resumo"]


# -- exportação CSV: o buraco que o plano listava desde o começo ---------------


def test_exportacao_csv_e_registrada(cliente, semente, sessao):
    """"Export CSV — quem exportou, qual recorte, quantas linhas."

    Estava no plano de segurança desde o primeiro dia e continuava ausente: o
    arquivo era montado no navegador a partir da listagem já baixada, e saía sem
    evento nenhum.
    """
    cliente.post("/api/interacoes", json=corpo(semente))

    resposta = cliente.post("/api/relatorios/exportacoes?frente=imprensa")
    assert resposta.status_code == 201
    sessao.flush()

    registro = sessao.scalars(
        select(RelatorioRegistro).order_by(RelatorioRegistro.criado_em.desc())
    ).first()
    assert registro.formato == "csv"
    assert registro.filtros == {"frente": "imprensa"}


def test_o_csv_nao_corta_como_o_documento_corta():
    """A diferença que faz o CSV merecer mais atenção que o relatório.

    O documento impresso leva 80 linhas por mais amplo que seja o recorte. O CSV
    leva tudo — e é por isso que ele é o caminho mais curto para tirar dados
    daqui.
    """
    from app.dominio.relatorio import (
        LINHAS_NO_DOCUMENTO,
        Relatorio,
    )

    comum = dict(secoes=("base",), filtros={}, criado_por=uuid4(), total_de_registros=6000)

    documento = Relatorio(**comum, formato="documento")
    planilha = Relatorio(**comum, formato="csv")

    assert documento.registros_no_documento == LINHAS_NO_DOCUMENTO
    assert planilha.registros_no_documento == 6000


def test_formato_desconhecido_e_recusado():
    from app.dominio.relatorio import Relatorio

    with pytest.raises(RegraViolada, match="[Ff]ormato desconhecido"):
        Relatorio(secoes=("base",), filtros={}, criado_por=uuid4(), formato="pdf")


def test_o_banco_tambem_recusa_formato_desconhecido(sessao, semente):
    """Vocabulário fechado no `check`, e não só no Python.

    A consulta de incidente filtra por formato; duas grafias da mesma coisa
    fariam metade das exportações sumirem do resultado.
    """
    from sqlalchemy.exc import IntegrityError

    # Cria o autor: a transação do teste é desfeita ao final, então não há
    # usuário garantido no banco.
    usuario = cria_usuario(sessao, "coordenacao")
    with pytest.raises(IntegrityError), sessao.begin_nested():
        sessao.execute(
            text(
                "insert into relatorio (secoes, filtros, criado_por, formato) "
                "values ('[\"base\"]'::jsonb, '{}'::jsonb, :quem, 'planilha')"
            ),
            {"quem": usuario.id},
        )


def test_historico_distingue_os_dois_formatos(cliente, semente, sessao):
    admin = cria_usuario(sessao, "coordenacao")
    cliente.post("/api/interacoes", json=corpo(semente))

    for formato in ("documento", "csv"):
        registrar_relatorio.registrar(
            sessao,
            secoes=("base",),
            recorte=Recorte(),
            usuario=como(sessao, admin),
            formato=formato,
        )
    sessao.flush()

    linhas = registrar_relatorio.historico(sessao, solicitante=como(sessao, admin))
    formatos = {linha.formato for linha in linhas[:2]}
    assert formatos == {"documento", "csv"}
