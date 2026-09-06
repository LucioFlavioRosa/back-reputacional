"""Ciclo completo contra um Postgres de verdade.

Exercita o que nenhum teste de unidade alcança: o DDL das migrations, os tipos
do Postgres (uuid, array, timestamptz), as chaves estrangeiras entre contextos
e a tradução do Recorte para SQL de fato executada pelo banco.

Precisa da pilha local no ar:

    docker compose up -d

Sem banco acessível, o módulo inteiro é pulado — a suíte continua verde numa
máquina sem Docker.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.banco.sessao import obter_sessao
from app.banco.tabelas_acesso import Usuario
from app.banco.tabelas_interacoes import (
    InteracaoAuditoria,
    InteracaoRegistro,
)
from app.banco.tabelas_stakeholders import (
    Instituicao,
    PessoaAegea,
)
from main import app

#: Os testes usam um banco PRÓPRIO, e não o de desenvolvimento.
#:
#: Compartilhar o banco faria a suíte depender de estar vazia — bastaria rodar
#: `semear_desenvolvimento` para as contagens quebrarem e os nomes colidirem no
#: índice único de instituição. O banco de teste é criado e migrado aqui.
SERVIDOR = os.environ.get(
    "BANCO_URL_TESTE",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/painel_reputacional",
)
BANCO_DE_TESTE = "painel_reputacional_teste"

MIGRATIONS = (
    Path(__file__).resolve().parents[1] / "app/banco/migrations"
)


def _preparar_banco_de_teste() -> str:
    """Cria e migra o banco de teste. Devolve a URL dele."""
    url_servidor = make_url(SERVIDOR)
    url_teste = url_servidor.set(database=BANCO_DE_TESTE)

    # O banco de teste é descartável e recriado a cada execução. Reaproveitá-lo
    # faria a suíte rodar contra o schema de uma migration anterior, e a
    # divergência apareceria como falha em teste que nada tem a ver.
    administrativo = create_engine(
        url_servidor.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with administrativo.connect() as conexao:
        conexao.execute(text(f'drop database if exists "{BANCO_DE_TESTE}" with (force)'))
        conexao.execute(text(f'create database "{BANCO_DE_TESTE}"'))
    administrativo.dispose()

    engine = create_engine(url_teste, isolation_level="AUTOCOMMIT")
    with engine.connect() as conexao:
        for arquivo in sorted(MIGRATIONS.glob("*.sql")):
            conexao.execute(text(arquivo.read_text(encoding="utf-8")))
    engine.dispose()

    return url_teste.render_as_string(hide_password=False)


try:
    URL = _preparar_banco_de_teste()
    _engine = create_engine(URL, pool_pre_ping=True)
    with _engine.connect() as conexao:
        conexao.execute(text("select 1 from frente limit 1"))
except Exception as erro:  # noqa: BLE001 - qualquer falha significa "sem banco"
    pytest.skip(
        f"Postgres indisponível em {SERVIDOR} ({type(erro).__name__}: {erro}). "
        "Suba com `docker compose up -d`.",
        allow_module_level=True,
    )


@pytest.fixture
def sessao():
    """Cada teste roda dentro de uma transação desfeita ao final."""
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
    from fastapi.testclient import TestClient

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def cliente_admin(sessao, monkeypatch):
    """O mesmo cliente, mas com perfil que administra cadastros.

    O `cliente` roda como `crm_edicao` — que EDITA agenda e NAO mexe nos
    cadastros. A separacao e o ponto: quem cadastra agenda le esses nomes o
    tempo todo, e renomear uma instituicao muda o que aparece em toda agenda
    que aponta para ela.

    `obter_configuracao` tem `lru_cache`, entao trocar a variavel de ambiente
    nao bastaria: o valor ja lido continuaria valendo.
    """
    from fastapi.testclient import TestClient

    from app.configuracao import Configuracao, obter_configuracao

    padrao = obter_configuracao()
    como_admin = Configuracao(
        **{**padrao.model_dump(), "auth_mock_perfil": "plataforma_edicao"}
    )
    monkeypatch.setattr(
        "app.api.dependencias.obter_configuracao", lambda: como_admin
    )

    app.dependency_overrides[obter_sessao] = lambda: sessao
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def semente(sessao):
    """Instituição e duas pessoas da Aegea, para as chaves estrangeiras."""
    valor = Instituicao(
        nome="Valor Econômico",
        nome_normalizado="valor economico",
        tipo="veiculo",
        uf="SP",
    )
    radames = PessoaAegea(
        nome="Radamés Casseb", nome_normalizado="radames casseb", eh_porta_voz=True
    )
    andre = PessoaAegea(
        nome="André Pires", nome_normalizado="andre pires", eh_porta_voz=True
    )
    sessao.add_all([valor, radames, andre])
    sessao.flush()
    return {"instituicao": valor, "radames": radames, "andre": andre}


def corpo(semente, **ajustes) -> dict:
    padrao = {
        "frente": "imprensa",
        "data_interacao": "2026-05-07",
        "instituicao_id": str(semente["instituicao"].id),
        "uf": "SP",
        "status": "atendido",
        "pauta": "Reajuste tarifário em concessões",
        "tier": 1,
        "clima": "tenso",
    }
    return {**padrao, **ajustes}


# -- ciclo completo ----------------------------------------------------------


def test_migrations_criaram_o_schema_esperado(sessao):
    tabelas = sessao.scalars(
        text("select table_name from information_schema.tables where table_schema='public'")
    ).all()
    assert "interacao" in tabelas
    assert "interacao_pessoa_aegea" in tabelas
    assert len(tabelas) >= 30


def test_cria_le_edita_e_arquiva(cliente, semente, sessao):
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    assert criada.status_code == 201, criada.text
    registro = criada.json()
    id_ = registro["id"]

    assert registro["frente"] == "imprensa"
    assert registro["tier"] == 1
    assert registro["criado_por"] is not None  # autoria vem do usuário logado

    lida = cliente.get(f"/api/interacoes/{id_}")
    assert lida.status_code == 200
    assert lida.json()["pauta"] == "Reajuste tarifário em concessões"

    editada = cliente.patch(f"/api/interacoes/{id_}", json={"clima": "neutro", "tier": 2})
    assert editada.status_code == 200, editada.text
    assert editada.json()["clima"] == "neutro"
    assert editada.json()["tier"] == 2

    arquivada = cliente.delete(f"/api/interacoes/{id_}")
    assert arquivada.status_code == 204
    assert cliente.get(f"/api/interacoes/{id_}").status_code == 404


def test_extensao_de_imprensa_vai_e_volta_do_banco(cliente, semente):
    resposta = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            extensao={
                "formato": "entrevista_online",
                "data_atendida": "2026-05-08",
                "data_publicacao": "2026-05-12",
                "link_materia": "https://exemplo.com/materia",
                "mensagens_chave": ["Tarifa", "Universalização"],
            },
        ),
    )
    assert resposta.status_code == 201, resposta.text

    extensao = resposta.json()["extensao"]
    assert extensao["formato"] == "entrevista_online"
    # array do Postgres preservando acento
    assert extensao["mensagens_chave"] == ["Tarifa", "Universalização"]


def test_dois_porta_vozes_no_mesmo_registro(cliente, semente):
    resposta = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            participacoes=[
                {"pessoa_aegea_id": str(semente["radames"].id), "papel": "porta_voz"},
                {"pessoa_aegea_id": str(semente["andre"].id), "papel": "porta_voz"},
            ],
        ),
    )
    assert resposta.status_code == 201, resposta.text
    assert len(resposta.json()["participacoes"]) == 2


def test_filtrar_por_porta_voz_encontra_os_dois(cliente, semente):
    cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            participacoes=[
                {"pessoa_aegea_id": str(semente["radames"].id), "papel": "porta_voz"},
                {"pessoa_aegea_id": str(semente["andre"].id), "papel": "porta_voz"},
            ],
        ),
    )
    for pessoa in ("radames", "andre"):
        listagem = cliente.get(
            "/api/interacoes", params={"portaVoz": str(semente[pessoa].id)}
        )
        assert listagem.status_code == 200, listagem.text
        # O registro conta para os dois — e sem duplicar a linha na listagem.
        assert listagem.json()["total"] == 1
        assert len(listagem.json()["itens"]) == 1


# -- o Recorte executado pelo banco ------------------------------------------


def test_filtros_do_recorte_no_postgres(cliente, semente):
    cliente.post("/api/interacoes", json=corpo(semente))
    cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            frente="governo",
            uf="DF",
            tier=3,
            status="declinado",
            data_interacao="2026-02-20",
            pauta="Audiência sobre marco regulatório",
            extensao={"natureza_orgao": "executivo"},
        ),
    )

    def total(**params) -> int:
        resposta = cliente.get("/api/interacoes", params=params)
        assert resposta.status_code == 200, resposta.text
        return resposta.json()["total"]

    assert total() == 2
    assert total(frente="imprensa") == 1
    assert total(area="governo") == 1  # apelido histórico continua valendo
    assert total(uf="SP") == 1
    assert total(tier=1) == 1
    assert total(de="2026-01-01", ate="2026-03-01") == 1
    assert total(q="tarifário") == 1
    # Ambas são do mesmo veículo: se a busca não alcançasse a instituição, o
    # resultado seria 0, porque "Valor Econômico" não aparece em nenhuma pauta.
    assert total(q="Valor Econômico") == 2


def test_status_e_grupo_sao_filtros_distintos_no_banco(cliente, semente):
    cliente.post("/api/interacoes", json=corpo(semente, status="declinado"))
    cliente.post("/api/interacoes", json=corpo(semente, status="cancelado"))

    def total(**params) -> int:
        return cliente.get("/api/interacoes", params=params).json()["total"]

    # O grupo "declinado" contém declinado e cancelado; o status, só um deles.
    assert total(grupo="declinado") == 2
    assert total(status="declinado") == 1


def test_filtro_invalido_responde_422(cliente):
    resposta = cliente.get("/api/interacoes", params={"uf": "XX"})
    assert resposta.status_code == 422
    assert "UF inválida" in resposta.json()["detalhe"]


# -- regressões apontadas na revisão -----------------------------------------


def test_trocar_entre_governo_e_parceiros_preserva_a_extensao(cliente, semente):
    criada = cliente.post(
        "/api/interacoes",
        json=corpo(
            semente,
            frente="governo",
            extensao={"natureza_orgao": "executivo", "cargo_interlocutor": "Secretário"},
        ),
    )
    id_ = criada.json()["id"]

    trocada = cliente.patch(f"/api/interacoes/{id_}", json={"frente": "parceiros"})
    assert trocada.status_code == 200, trocada.text
    assert trocada.json()["frente"] == "parceiros"
    # As três frentes institucionais compartilham a extensão: nada se perde.
    assert trocada.json()["extensao"]["cargo_interlocutor"] == "Secretário"


def test_trocar_para_frente_de_outra_extensao_e_recusado(cliente, semente):
    criada = cliente.post(
        "/api/interacoes",
        json=corpo(semente, frente="governo", extensao={"natureza_orgao": "executivo"}),
    )
    id_ = criada.json()["id"]

    resposta = cliente.patch(f"/api/interacoes/{id_}", json={"frente": "legislativo"})
    assert resposta.status_code == 422
    assert "Envie `extensao`" in resposta.json()["detalhe"]


def test_leitura_nao_escreve_no_banco(cliente, semente, sessao):
    """GET não pode sujar a sessão atualizando `ultimo_acesso_em`."""
    cliente.get("/api/interacoes")  # provisiona o usuário
    sessao.flush()

    usuario = sessao.scalars(select(Usuario)).first()
    antes = usuario.ultimo_acesso_em

    for _ in range(3):
        cliente.get("/api/interacoes")

    sessao.refresh(usuario)
    assert usuario.ultimo_acesso_em == antes


def test_auditoria_grava_uma_linha_por_campo_alterado(cliente, semente, sessao):
    """Quem grava é o gatilho (migration 0005), e o vocabulário é o do BANCO.

    A trilha registra `clima_id`, a coluna física, e o valor é o id do
    dicionário — não `clima` nem o código. É o preço de auditar no banco, e vale
    pagar: é o único ponto por onde passam tanto a aplicação quanto o `update`
    feito à mão no cliente SQL.

    Resolver id para rótulo é trabalho de quem for exibir a trilha; a auditoria
    guarda o que de fato mudou na linha.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])

    cliente.patch(
        f"/api/interacoes/{id_}",
        json={"clima": "neutro", "tier": 1, "relato": "Entrevista concedida"},
    )

    linhas = sessao.scalars(
        select(InteracaoAuditoria).where(InteracaoAuditoria.interacao_id == id_)
    ).all()
    campos = {linha.campo for linha in linhas}

    # `tier` já era 1: não mudou, não vira linha de auditoria.
    assert campos == {"clima_id", "relato"}

    relato = next(linha for linha in linhas if linha.campo == "relato")
    assert relato.valor_anterior is None
    assert relato.valor_novo == "Entrevista concedida"


def test_auditoria_registra_quem_alterou(cliente, semente, sessao):
    """O gatilho não sabe quem pediu: a aplicação carimba na transação.

    Para o Postgres toda requisição chega pela mesma conta. `painel.usuario_id`
    é a ponte, definida quando a identidade é resolvida.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])
    cliente.patch(f"/api/interacoes/{id_}", json={"relato": "algo"})

    linha = sessao.scalars(
        select(InteracaoAuditoria).where(InteracaoAuditoria.interacao_id == id_)
    ).first()
    usuario = sessao.scalars(select(Usuario)).first()

    assert linha.usuario_id == usuario.id


def test_update_por_sql_direto_deixa_rastro(cliente, semente, sessao):
    """Alteração por SQL direto aparece na trilha, com autor nulo.

    É a razão de a auditoria ser escrita por GATILHO e não pela aplicação:
    trilha escrita em Python registra o que o Python faz, e um `update` rodado
    no cliente SQL — manutenção, correção de emergência, alguem com a
    credencial — passaria despercebido.

    Autor nulo com `origem` preenchida é a assinatura desse caso. Não é dado
    faltando: é sinal.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])
    sessao.flush()

    # Transação nova, sem `painel.usuario_id` — é o que um cliente SQL faz.
    sessao.execute(text("reset painel.usuario_id"))
    sessao.execute(
        text("update interacao set pauta = :nova where id = :id"),
        {"nova": "Pauta trocada por fora do sistema", "id": id_},
    )

    linhas = sessao.scalars(
        select(InteracaoAuditoria).where(
            InteracaoAuditoria.interacao_id == id_,
            InteracaoAuditoria.campo == "pauta",
        )
    ).all()

    assert len(linhas) == 1, "o update direto não foi auditado"
    assert linhas[0].usuario_id is None, "autor nulo é o sinal de alteração externa"
    assert linhas[0].valor_novo == "Pauta trocada por fora do sistema"


def test_auditoria_nao_grava_duas_vezes(cliente, semente, sessao):
    """A aplicação parou de escrever quando o gatilho começou.

    Se `_registrar_diff` tivesse ficado, toda edição pela API geraria duas
    linhas por campo — e ninguém notaria olhando uma tela de histórico, só
    contando.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])
    cliente.patch(f"/api/interacoes/{id_}", json={"relato": "uma vez só"})

    linhas = sessao.scalars(
        select(InteracaoAuditoria).where(
            InteracaoAuditoria.interacao_id == id_,
            InteracaoAuditoria.campo == "relato",
        )
    ).all()
    assert len(linhas) == 1


def test_arquivar_e_auditado_pelo_gatilho(cliente, semente, sessao):
    """Soft delete é um `update` de `arquivado_em`: o gatilho pega sem caso especial."""
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])
    cliente.delete(f"/api/interacoes/{id_}")

    linhas = sessao.scalars(
        select(InteracaoAuditoria).where(
            InteracaoAuditoria.interacao_id == id_,
            InteracaoAuditoria.campo == "arquivado_em",
        )
    ).all()
    assert len(linhas) == 1
    assert linhas[0].valor_anterior is None
    assert linhas[0].valor_novo is not None


# -- papel restrito da aplicação (migration 0009) ------------------------------


def test_papel_da_aplicacao_existe_e_nao_faz_login(sessao):
    """`painel_app` é recipiente de permissão, não conta.

    A conta de login é criada pela infraestrutura, com a senha vinda do Key
    Vault, e recebe este papel. Senha em arquivo de migration entra no
    histórico do Git e não sai mais.
    """
    linha = sessao.execute(
        text("select rolcanlogin, rolsuper from pg_roles where rolname = 'painel_app'")
    ).first()
    assert linha is not None, "a migration 0009 não criou o papel"
    assert linha.rolcanlogin is False
    assert linha.rolsuper is False


def test_papel_da_aplicacao_le_e_escreve_mas_nao_apaga(sessao):
    """O teto do estrago quando a connection string vaza.

    Nenhum caso de uso remove linha — o sistema usa soft delete. Então `delete`
    só serviria para destruir, e `truncate` não é coberto por `delete`.
    """
    def pode(privilegio: str) -> bool:
        return sessao.execute(
            text("select has_table_privilege('painel_app', 'interacao', :p)"),
            {"p": privilegio},
        ).scalar()

    assert pode("SELECT")
    assert pode("INSERT")
    assert pode("UPDATE")
    assert not pode("DELETE"), "delete permitido: soft delete deixa de ser garantia"
    assert not pode("TRUNCATE")


def test_papel_da_aplicacao_nao_e_dono_de_tabela(sessao):
    """Dono pode dropar a própria tabela, tenha ou não grant.

    Conceder tudo menos DDL e depois deixar a aplicação dona seria anular a
    migration 0009 inteira sem que nenhum `grant` denunciasse.
    """
    donos = sessao.execute(
        text("select tableowner from pg_tables where schemaname = 'public'")
    ).scalars().all()
    assert "painel_app" not in donos


def test_arquivar_e_soft_delete(cliente, semente, sessao):
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])

    cliente.delete(f"/api/interacoes/{id_}")

    registro = sessao.get(InteracaoRegistro, id_)
    assert registro is not None  # continua no banco
    assert registro.arquivado_em is not None
    assert cliente.get("/api/interacoes").json()["total"] == 0


# -- garantias do próprio banco ----------------------------------------------
#
# O domínio da aplicação já valida estes casos, mas o importador e qualquer
# correção manual escrevem SQL direto. Estes testes provam que o banco também
# recusa — é a rede embaixo da rede.


def test_email_ignora_caixa(sessao):
    """CITEXT: a mesma pessoa não pode virar duas contas no provisionamento."""
    from sqlalchemy.exc import IntegrityError

    sessao.add(
        Usuario(
            entra_object_id="caixa-1",
            email="pessoa@aegea.com.br",
            nome="Pessoa",
        )
    )
    sessao.flush()

    # Savepoint: o erro aborta a transação corrente, e sem isolá-lo o rollback
    # do fixture reclamaria de operar sobre uma transação já encerrada.
    with pytest.raises(IntegrityError), sessao.begin_nested():
        sessao.add(
            Usuario(
                entra_object_id="caixa-2",
                email="Pessoa@Aegea.COM.BR",
                nome="Pessoa de novo",
            )
        )
        sessao.flush()


def test_banco_recusa_abrangencia_invalida(cliente, semente, sessao):
    """O domínio `abrangencia` guarda o campo de que o mapa depende."""
    from sqlalchemy.exc import IntegrityError

    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])

    with pytest.raises(IntegrityError, match="abrangencia"), sessao.begin_nested():
        sessao.execute(
            text("update interacao set uf = 'ZZ' where id = :id"), {"id": id_}
        )


def test_busca_encontra_nome_sem_acento(cliente, semente, sessao):
    """A busca usa a coluna normalizada: digitar sem acento acha o registro."""
    sessao.add(
        Instituicao(
            nome="Valor Econômico Brasil",
            nome_normalizado="valor economico brasil",
            tipo="orgao",
        )
    )
    sessao.flush()

    cliente.post("/api/interacoes", json=corpo(semente))

    com_acento = cliente.get("/api/interacoes", params={"q": "Econômico"})
    sem_acento = cliente.get("/api/interacoes", params={"q": "Economico"})

    assert com_acento.json()["total"] == 1
    assert sem_acento.json()["total"] == 1


# -- contrato HTTP -----------------------------------------------------------


def test_204_devolve_corpo_vazio(cliente, semente):
    """`-> None` com 204 não pode serializar `null` no corpo.

    Um 204 com corpo é malformado segundo o HTTP, e alguns clientes engasgam.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    resposta = cliente.delete(f"/api/interacoes/{criada.json()['id']}")

    assert resposta.status_code == 204
    assert resposta.content == b""


def papel_de_coordenacao():
    """O papel semeado pela migration 0003, montado em memoria.

    O override de dependencia nao passa por `provisionar`, entao precisa
    devolver um `Papel` pronto; usar coordenacao mantem o teste focado em
    contagem de chamadas e nao em permissao.
    """
    from app.dominio.identidade import Papel

    return Papel(
        codigo="plataforma_edicao",
        nome="Coordenacao",
        # `plataforma` abre os tres portais. Sem declarar aqui, a requisicao
        # parava antes de chegar a rota — `exigir_portal_crm` barra quem nao
        # abre o CRM, e o teste deixaria de contar o que se propoe a contar.
        acessa_crm=True,
        acessa_sintese=True,
        acessa_score=True,
        pode_criar=True,
        pode_editar_proprio=True,
        pode_editar_tudo=True,
        administra_dicionarios=True,
        administra_acessos=True,
        ve_campos_sensiveis=True,
        ve_diretorio=True,
        pode_exportar=True,
    )


def test_autenticacao_resolve_uma_vez_por_requisicao(cliente, semente, sessao):
    """A auth está no router E em `UsuarioQueEscreve` nas rotas de escrita.

    O FastAPI cacheia dependências por requisição, então as duas referências
    à mesma função devem resolvê-la uma vez só. Sem o cache, cada escrita
    provisionaria o usuário duas vezes.
    """
    from app.api.dependencias import (
        obter_usuario_atual,
    )

    chamadas = 0
    original = app.dependency_overrides.get(obter_usuario_atual)

    def contando(sessao_injetada=None, configuracao=None):  # noqa: ANN001
        nonlocal chamadas
        chamadas += 1
        from app.dominio.identidade import Escopo, UsuarioAtual

        usuario = sessao.scalars(select(Usuario)).first()
        return UsuarioAtual(
            id=usuario.id,
            nome=usuario.nome,
            email=str(usuario.email),
            papel=papel_de_coordenacao(),
            escopo=Escopo.total(),
        )

    # Garante que existe um usuário para o override devolver.
    cliente.get("/api/interacoes")
    sessao.flush()

    app.dependency_overrides[obter_usuario_atual] = contando
    try:
        resposta = cliente.post("/api/interacoes", json=corpo(semente))
    finally:
        if original is None:
            app.dependency_overrides.pop(obter_usuario_atual, None)
        else:
            app.dependency_overrides[obter_usuario_atual] = original

    assert resposta.status_code == 201, resposta.text
    assert chamadas == 1, f"a dependência resolveu {chamadas} vezes"


def test_registro_invisivel_nao_e_legivel_por_id(cliente, semente, sessao):
    """A ficha precisa recusar o que a listagem esconde.

    `condicoes()` filtra `visivel is true`; se a busca por id não fizer o mesmo,
    um registro escondido da Base continua legível por quem souber o id.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])

    assert cliente.get(f"/api/interacoes/{id_}").status_code == 200

    sessao.execute(
        text("update interacao set visivel = false where id = :id"), {"id": id_}
    )
    sessao.flush()

    assert cliente.get("/api/interacoes").json()["total"] == 0
    assert cliente.get(f"/api/interacoes/{id_}").status_code == 404


def test_dicionarios_vem_carregados(cliente):
    resposta = cliente.get("/api/dicionarios")
    assert resposta.status_code == 200

    dicionarios = resposta.json()
    assert len(dicionarios["frentes"]) == 7
    assert len(dicionarios["unidades_negocio"]) == 29
    assert {f["codigo"] for f in dicionarios["resultados"]} == {
        "avancou", "mantido", "recuou", "sem_definicao"
    }


def test_a_agenda_e_criada_sem_pauta(cliente, semente):
    """Pela API, e nao so no dominio. Ver `test_a_agenda_vale_sem_pauta`.

    Este teste exigia 422 e passou a exigir 201: a obrigatoriedade saiu do
    banco (0013), do dominio e do esquema, e se qualquer uma das tres tivesse
    ficado para tras a criacao continuaria sendo recusada aqui.
    """
    corpo_sem_pauta = corpo(semente)
    corpo_sem_pauta.pop("pauta", None)

    resposta = cliente.post("/api/interacoes", json=corpo_sem_pauta)
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["pauta"] is None


def test_uf_invalida_e_recusada(cliente, semente):
    resposta = cliente.post("/api/interacoes", json=corpo(semente, uf="ZZ"))
    assert resposta.status_code == 422


def test_status_inexistente_no_catalogo_e_recusado(cliente, semente):
    resposta = cliente.post("/api/interacoes", json=corpo(semente, status="inventado"))
    assert resposta.status_code == 422
    assert "desconhecido" in resposta.json()["detalhe"].lower()


def test_data_futura_e_aceita(cliente, semente):
    """Agenda marcada é registro legítimo — não existe trava de data futura."""
    resposta = cliente.post(
        "/api/interacoes",
        json=corpo(semente, data_interacao="2027-01-15", status="agendado"),
    )
    assert resposta.status_code == 201


# -- autorização: papel, escopo e prazo ---------------------------------------
#
# A autorização mora no banco, e não em claim de grupo. O que estes testes
# cobrem é justamente o que teste de unidade não alcança: o `check` do prazo e o
# escopo virando `where` de verdade.


def como(cliente, papel, escopo=None):
    """Troca o usuário da requisição seguinte.

    O override devolve um `UsuarioAtual` pronto porque o caminho normal
    (`provisionar`) leria papel e escopo do banco — aqui o interesse é o que
    acontece *depois* da resolução.
    """
    from app.api.dependencias import obter_usuario_atual
    from app.dominio.identidade import Escopo, UsuarioAtual

    def override():
        return UsuarioAtual(
            id=uuid.uuid4(),
            nome="Convidado",
            email="convidado@agencia.com.br",
            papel=papel,
            escopo=escopo or Escopo.total(),
        )

    app.dependency_overrides[obter_usuario_atual] = override
    return cliente


def papel_externo():
    """Convidado de fora: entra no CRM e não vê quase nada lá dentro.

    `acessa_crm=True` porque o que estes testes exercitam é a POBREZA de
    permissão dentro do módulo — sem campo sensível, sem diretório. Portal é a
    outra dimensão, e sem ele a requisição pararia antes, num 403 de módulo, e
    o teste deixaria de exercitar o que se propõe.
    """
    from app.dominio.identidade import Papel

    return Papel(codigo="externo_crm", nome="Externo", acessa_crm=True)


def test_migration_semeou_os_oito_papeis(sessao):
    """Um par por portal: quem lê e quem edita."""
    codigos = set(sessao.scalars(text("select codigo from papel")).all())
    assert codigos == {
        "plataforma_leitura",
        "plataforma_edicao",
        "crm_leitura",
        "crm_edicao",
        "sintese_leitura",
        "sintese_edicao",
        "score_leitura",
        "score_edicao",
    }


def test_banco_recusa_externo_sem_prazo(sessao):
    """O esquecimento de revogar precisa virar expiração, não acesso eterno.

    Contrato de agência acaba e ninguém apaga a linha. Sem o `check`, o acesso
    sobrevive ao contrato — e é isso que a restrição impede na origem, mesmo
    que a concessão venha por SQL direto e não pela aplicação.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), sessao.begin_nested():
        sessao.add(
            Usuario(
                entra_object_id="agencia-sem-prazo",
                email="agencia@externa.com.br",
                nome="Agência",
                externo=True,
                acesso_expira_em=None,
            )
        )
        sessao.flush()


def test_externo_com_prazo_e_aceito(sessao):
    sessao.add(
        Usuario(
            entra_object_id="agencia-com-prazo",
            email="agencia2@externa.com.br",
            nome="Agência",
            externo=True,
            acesso_expira_em=date(2026, 12, 31),
        )
    )
    sessao.flush()


def test_escopo_restringe_a_listagem(cliente, semente, sessao):
    from app.dominio.identidade import Escopo

    criada = cliente.post("/api/interacoes", json=corpo(semente))
    assert criada.status_code == 201
    sessao.flush()

    # Quem alcança `imprensa` vê o registro.
    de_imprensa = como(cliente, papel_externo(), Escopo(frentes=frozenset({"imprensa"})))
    assert de_imprensa.get("/api/interacoes").json()["total"] == 1

    # Quem só alcança `governo` não vê nada — o filtro não veio da query string.
    de_governo = como(cliente, papel_externo(), Escopo(frentes=frozenset({"governo"})))
    assert de_governo.get("/api/interacoes").json()["total"] == 0


def test_registro_fora_do_escopo_nao_e_legivel_por_id(cliente, semente, sessao):
    """IDOR: `obter` usava `sessao.get()` e pulava o filtro inteiro.

    Era o caminho de leitura sem restrição nenhuma — quem descobrisse um id
    lia o registro, estivesse ele no seu alcance ou não. A resposta é 404, e
    não 403, porque 403 confirmaria a existência do registro.
    """
    from app.dominio.identidade import Escopo

    id_ = cliente.post("/api/interacoes", json=corpo(semente)).json()["id"]
    sessao.flush()

    fora = como(cliente, papel_externo(), Escopo(frentes=frozenset({"governo"})))
    assert fora.get(f"/api/interacoes/{id_}").status_code == 404

    dentro = como(cliente, papel_externo(), Escopo(frentes=frozenset({"imprensa"})))
    assert dentro.get(f"/api/interacoes/{id_}").status_code == 200


def test_convidado_sem_concessao_nao_ve_nada(cliente, semente, sessao):
    """Falha fechada: restrito e sem linha de escopo é zero, não tudo."""
    from app.dominio.identidade import Escopo

    cliente.post("/api/interacoes", json=corpo(semente))
    sessao.flush()

    recem_chegado = como(cliente, papel_externo(), Escopo(irrestrito=False))
    assert recem_chegado.get("/api/interacoes").json()["total"] == 0


def test_externo_nao_recebe_campos_sensiveis(cliente, semente, sessao):
    from app.dominio.identidade import Escopo

    id_ = cliente.post(
        "/api/interacoes",
        json=corpo(semente, relato="Off the record", pendencias="Aguarda jurídico"),
    ).json()["id"]
    sessao.flush()

    externo = como(cliente, papel_externo(), Escopo(frentes=frozenset({"imprensa"})))
    ficha = externo.get(f"/api/interacoes/{id_}").json()
    assert ficha["relato"] is None
    assert ficha["pendencias"] is None
    assert ficha["pauta"]  # o registro continua visível


def test_diretorio_exige_papel(cliente, semente):
    """Instituições e interlocutores são o mapa de relacionamento da Aegea.

    Não passam por `condicoes()` — a barreira precisa ser o papel.
    """
    externo = como(cliente, papel_externo())
    assert externo.get("/api/instituicoes").status_code == 403

    from app.dominio.identidade import Papel

    com_direito = como(
        cliente, Papel(codigo="crm_edicao", nome="Analista", ve_diretorio=True, acessa_crm=True)
    )
    assert com_direito.get("/api/instituicoes").status_code == 200


def test_recorte_nao_amplia_o_escopo(cliente, semente, sessao):
    """Pedir uma frente fora do alcance devolve vazio, não a frente pedida.

    O escopo entra depois do filtro do usuário e nunca no lugar dele — a query
    string não tem como afrouxar o que a concessão restringiu.
    """
    from app.dominio.identidade import Escopo

    cliente.post("/api/interacoes", json=corpo(semente))
    sessao.flush()

    preso_em_governo = como(
        cliente, papel_externo(), Escopo(frentes=frozenset({"governo"}))
    )
    resposta = preso_em_governo.get("/api/interacoes?frente=imprensa")
    assert resposta.json()["total"] == 0


def test_busca_livre_nao_delata_relato_escondido(cliente, semente, sessao):
    """O oráculo: sem o campo no payload, mas com ele no `where`.

    O externo recebe `relato: null` e mesmo assim descobriria o conteúdo por
    tentativa — bastaria observar se o registro aparece no resultado da busca.
    """
    from app.dominio.identidade import Escopo, Papel

    cliente.post(
        "/api/interacoes",
        json=corpo(semente, relato="conversa sobre desligamento do diretor"),
    )
    sessao.flush()

    escopo_valido = Escopo(frentes=frozenset({"imprensa"}))

    # A palavra existe SOMENTE em `relato`.
    externo = como(cliente, papel_externo(), escopo_valido)
    assert externo.get("/api/interacoes?q=desligamento").json()["total"] == 0

    # Quem tem direito ao campo continua encontrando por ele.
    interno = como(
        cliente,
        Papel(codigo="crm_edicao", nome="Analista", ve_campos_sensiveis=True, acessa_crm=True),
        escopo_valido,
    )
    assert interno.get("/api/interacoes?q=desligamento").json()["total"] == 1


def test_troca_de_porta_voz_e_auditada(cliente, semente, sessao):
    """O gatilho precisa cobrir as tabelas FILHAS, e não só `interacao`.

    Porta-voz está em `interacao_pessoa_aegea`. Trocar quem falou pela empresa —
    exatamente o tipo de alteração que interessa auditar — não deixava rastro.
    """
    criada = cliente.post(
        "/api/interacoes",
        json=corpo(semente, participacoes=[
            {"pessoa_aegea_id": str(semente["radames"].id), "papel": "porta_voz"}
        ]),
    )
    id_ = uuid.UUID(criada.json()["id"])

    cliente.patch(
        f"/api/interacoes/{id_}",
        json={"participacoes": [
            {"pessoa_aegea_id": str(semente["andre"].id), "papel": "porta_voz"}
        ]},
    )

    linhas = sessao.scalars(
        select(InteracaoAuditoria).where(
            InteracaoAuditoria.interacao_id == id_,
            InteracaoAuditoria.campo == "participacao",
        )
    ).all()

    saiu = [linha for linha in linhas if linha.valor_anterior and not linha.valor_novo]
    entrou = [linha for linha in linhas if linha.valor_novo and not linha.valor_anterior]
    assert saiu and entrou, "a troca de porta-voz não foi auditada"
    assert str(semente["andre"].id) in entrou[-1].valor_novo


def test_troca_de_tema_e_auditada(cliente, semente, sessao):
    criada = cliente.post("/api/interacoes", json=corpo(semente, temas=[1]))
    id_ = uuid.UUID(criada.json()["id"])
    cliente.patch(f"/api/interacoes/{id_}", json={"temas": [2]})

    campos = sessao.scalars(
        select(InteracaoAuditoria.campo).where(InteracaoAuditoria.interacao_id == id_)
    ).all()
    assert "tema" in campos


def test_extensao_da_frente_e_auditada(cliente, semente, sessao):
    """`mensagens_chave` mora em `interacao_imprensa`, não em `interacao`."""
    criada = cliente.post(
        "/api/interacoes",
        json=corpo(semente, extensao={"formato": "entrevista_online"}),
    )
    id_ = uuid.UUID(criada.json()["id"])

    cliente.patch(
        f"/api/interacoes/{id_}",
        json={"extensao": {"formato": "entrevista_online", "mensagens_chave": ["tarifa justa"]}},
    )

    campos = sessao.scalars(
        select(InteracaoAuditoria.campo).where(InteracaoAuditoria.interacao_id == id_)
    ).all()
    assert any(c.startswith("interacao_imprensa.") for c in campos), campos


def test_auditoria_registra_a_conta_de_banco(cliente, semente, sessao):
    """`origem` é a defesa contra o autor forjado.

    `painel.usuario_id` é escrito por quem estiver na conexão: quem tem a
    connection string carimba o id de outra pessoa e a alteração fica registrada
    como se fosse dela. Não dá para impedir — dá para gravar ao lado algo que a
    conexão não escolhe, que é a conta com que se autenticou no banco.
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])
    cliente.patch(f"/api/interacoes/{id_}", json={"relato": "algo"})

    linha = sessao.scalars(
        select(InteracaoAuditoria).where(InteracaoAuditoria.interacao_id == id_)
    ).first()
    assert linha.origem, "a conta de banco não foi registrada"


def test_autor_carimbado_e_forjavel_e_a_origem_denuncia(cliente, semente, sessao):
    """O limite honesto deste desenho, fixado em teste.

    Quem escreve na conexão escolhe `painel.usuario_id`. Este teste NÃO afirma
    que a forja é impossível — afirma que ela é possível, e que `origem`
    continua contando com qual conta a alteração entrou. É o que separa
    "atribuição" de "prova de autoria".
    """
    criada = cliente.post("/api/interacoes", json=corpo(semente))
    id_ = uuid.UUID(criada.json()["id"])
    sessao.flush()

    vitima = sessao.scalars(select(Usuario)).first()
    sessao.execute(
        text("select set_config('painel.usuario_id', :quem, true)"),
        {"quem": str(vitima.id)},
    )
    sessao.execute(
        text("update interacao set pauta = 'forjado' where id = :id"), {"id": id_}
    )

    linha = sessao.scalars(
        select(InteracaoAuditoria).where(
            InteracaoAuditoria.interacao_id == id_,
            InteracaoAuditoria.campo == "pauta",
        )
    ).first()

    assert linha.usuario_id == vitima.id, "a forja funcionou, como esperado"
    assert linha.origem is not None, "mas a conta de banco fica registrada"


def test_a_agenda_nasce_solicitada_sem_ninguem_mandar_status(cliente, semente):
    """O ESTADO INICIAL E DO BACKEND, e nao de cada cliente.

    `status` era obrigatorio na criacao, o que contradizia o pedido — a agenda
    deve nascer com o que a IDENTIFICA — e obrigava cada cliente a saber qual e
    o primeiro estado. Medido pela API: `POST` sem status voltava 422
    `Field required`.

    `solicitado`, e nao `agendado`: "agendado" afirma que existe data marcada
    com a outra parte, e no instante da criacao ninguem confirmou isso.
    """
    corpo_minimo = corpo(semente)
    for campo in ("status", "pauta"):
        corpo_minimo.pop(campo, None)

    resposta = cliente.post("/api/interacoes", json=corpo_minimo)

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["status"] == "solicitado"
    assert resposta.json()["pauta"] is None


def test_o_status_enviado_vence_o_padrao(cliente, semente):
    """A prova negativa: o padrao nao pode atropelar quem informou.

    Sem ela, um `status = "solicitado"` escrito no lugar errado passaria neste
    arquivo inteiro — e toda agenda gravada viraria solicitada.
    """
    resposta = cliente.post("/api/interacoes", json=corpo(semente, status="realizado"))

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["status"] == "realizado"


# -- administracao dos cadastros ----------------------------------------------
#
# Instituicoes e interlocutores so entravam pela planilha. Passaram a ser
# editaveis porque o formulario de agenda depende dos dois: a frente filtra as
# instituicoes pelo TIPO, e a instituicao filtra quem pode representar a outra
# parte. Sem cadastro, uma agenda com orgao novo nao teria como ser registrada.


def test_cadastrar_instituicao_e_ela_aparece_no_diretorio(cliente_admin, semente):
    """Criar e ler pela mesma API, e nao so gravar.

    O diretorio e o que alimenta o formulario. Uma instituicao que entra no
    banco e nao aparece na listagem nao serve para nada — foi assim que a
    presenca do porta-voz se perdeu por tres revisoes.
    """
    resposta = cliente_admin.post(
        "/api/instituicoes",
        json={"nome": "Agencia Nacional de Aguas", "tipo": "orgao", "uf": "NA"},
    )

    assert resposta.status_code == 201, resposta.text
    criada = resposta.json()
    assert criada["tipo"] == "orgao"

    listagem = cliente_admin.get("/api/instituicoes").json()
    assert any(i["id"] == criada["id"] for i in listagem)


def test_o_nome_e_normalizado_para_a_duplicata_nao_passar(cliente_admin, semente):
    """O indice unico e `(nome_normalizado, tipo)`.

    Sem normalizar na rota, "Folha de S.Paulo" e "FOLHA DE S.PAULO" entrariam
    como duas instituicoes, e a segunda agenda apontaria para a duplicata sem
    ninguem notar — dois registros da mesma casa, e nenhuma contagem certa.
    """
    cliente_admin.post("/api/instituicoes", json={"nome": "Folha de S.Paulo", "tipo": "veiculo"})

    repetida = cliente_admin.post(
        "/api/instituicoes", json={"nome": "  FOLHA DE S.PAULO  ", "tipo": "veiculo"}
    )

    assert repetida.status_code == 422
    assert "Ja existe" in repetida.json()["detalhe"]


def test_o_mesmo_nome_em_tipos_diferentes_e_permitido(cliente_admin, semente):
    """A prova negativa da normalizacao.

    Uma barragem pode ser `orgao` e uma proposicao sobre ela pode ter o mesmo
    nome. O indice e por `(nome, tipo)`, e barrar so pelo nome recusaria
    cadastro legitimo.
    """
    primeira = cliente_admin.post("/api/instituicoes", json={"nome": "Sabesp", "tipo": "orgao"})
    segunda = cliente_admin.post("/api/instituicoes", json={"nome": "Sabesp", "tipo": "entidade"})

    assert primeira.status_code == 201, primeira.text
    assert segunda.status_code == 201, segunda.text


def test_tipo_fora_do_mapa_de_frentes_e_recusado(cliente_admin, semente):
    """Um tipo que nenhuma frente conversa seria invisivel.

    A instituicao existiria no banco e nunca apareceria em formulario nenhum,
    porque o campo so oferece o tipo da frente escolhida. Recusar na porta e
    melhor do que criar um cadastro inalcancavel.
    """
    resposta = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Escritorio X", "tipo": "escritorio"}
    )

    assert resposta.status_code == 422
    assert "Tipo invalido" in resposta.json()["detalhe"]


def test_editar_instituicao_muda_o_que_o_diretorio_devolve(cliente_admin, semente):
    criada = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Agencia X", "tipo": "orgao"}
    ).json()

    resposta = cliente_admin.put(
        f"/api/instituicoes/{criada['id']}",
        json={"nome": "Agencia Reguladora X", "tipo": "orgao", "ativo": False},
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["nome"] == "Agencia Reguladora X"
    assert resposta.json()["ativo"] is False


def test_cadastrar_pessoa_ligada_a_instituicao(cliente_admin, semente):
    """E o vinculo que decide quem aparece em "Pela outra parte".

    Sem `instituicao_id`, a pessoa fica fora de toda lista da tela: o
    formulario so oferece quem pertence a instituicao escolhida.
    """
    instituicao = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Ministerio Y", "tipo": "orgao"}
    ).json()

    resposta = cliente_admin.post(
        "/api/interlocutores",
        json={
            "nome": "Maria Souza",
            "instituicao_id": instituicao["id"],
            "cargo": "Secretaria de Saneamento",
        },
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["instituicao_id"] == instituicao["id"]

    listagem = cliente_admin.get("/api/interlocutores").json()
    assert any(p["id"] == resposta.json()["id"] for p in listagem)


def test_mudar_a_pessoa_de_instituicao(cliente_admin, semente):
    """Alguem troca de emprego, e a agenda antiga nao pode perder o nome.

    O vinculo muda para frente; as agendas ja gravadas continuam apontando para
    a pessoa, e a tela as mantem na lista mesmo fora da instituicao atual.
    """
    origem = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao A", "tipo": "orgao"}
    ).json()
    destino = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao B", "tipo": "orgao"}
    ).json()
    pessoa = cliente_admin.post(
        "/api/interlocutores", json={"nome": "Joao Lima", "instituicao_id": origem["id"]}
    ).json()

    resposta = cliente_admin.put(
        f"/api/interlocutores/{pessoa['id']}",
        json={"nome": "Joao Lima", "instituicao_id": destino["id"]},
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["instituicao_id"] == destino["id"]


def test_instituicao_inexistente_devolve_404_e_nao_500(cliente_admin, semente):
    resposta = cliente_admin.put(
        "/api/instituicoes/00000000-0000-0000-0000-000000000000",
        json={"nome": "Nao existe", "tipo": "orgao"},
    )

    assert resposta.status_code == 404


def test_campo_desconhecido_e_recusado(cliente_admin, semente):
    """`extra="forbid"`: um campo com nome errado seria descartado em silencio.

    A tela mandaria `instituicao` em vez de `instituicao_id`, receberia 201, e a
    pessoa entraria sem vinculo — invisivel em toda lista do formulario.
    """
    resposta = cliente_admin.post(
        "/api/interlocutores", json={"nome": "Ana", "instituicao": "algum-id"}
    )

    assert resposta.status_code == 422


def test_quem_edita_agenda_nao_administra_cadastros(cliente, semente):
    """A separacao de papeis, medida.

    `crm_edicao` cria e edita agenda o dia inteiro, e nao pode renomear uma
    instituicao — isso mudaria o que aparece em TODA agenda que aponta para
    ela, e na Base de todo mundo.
    """
    resposta = cliente.post(
        "/api/instituicoes", json={"nome": "Nao deveria entrar", "tipo": "orgao"}
    )

    assert resposta.status_code == 403
    assert "administra" in resposta.json()["detalhe"]


def test_a_sessao_sobrevive_a_duplicata_recusada(sessao, semente):
    """O motivo do `begin_nested` na rota, provado na camada em que ele age.

    Um `IntegrityError` deixa a transacao envenenada: sem isolar o `flush` num
    savepoint, o proximo comando falha com "transaction is aborted" — um erro
    sem relacao aparente com o que a pessoa fez.

    NAO da para medir isso por duas requisicoes: neste arquivo a sessao e
    COMPARTILHADA entre elas, e o rollback da requisicao que devolveu 422 mata
    a transacao do proprio fixture. O teste mediria o arranjo, e nao o codigo.
    """

    from app.api.stakeholders import InstituicaoEntrada, criar_instituicao
    from app.dominio.erros import RegraViolada

    criar_instituicao(
        sessao, None, InstituicaoEntrada(nome="Estadao", tipo="veiculo")
    )

    with pytest.raises(RegraViolada):
        criar_instituicao(
            sessao, None, InstituicaoEntrada(nome="ESTADAO", tipo="veiculo")
        )

    # A prova: a sessao continua aceitando comando depois da recusa.
    depois = criar_instituicao(
        sessao, None, InstituicaoEntrada(nome="O Globo", tipo="veiculo")
    )
    assert depois.id is not None


def test_cadastrar_instituicao_com_o_primeiro_representante(cliente_admin, semente):
    """As duas coisas numa requisicao so.

    Uma instituicao sem ninguem nao serve para nada: o formulario de agenda so
    oferece pessoas depois que a instituicao e escolhida, e a lista sairia
    vazia. Pedir dois gestos para uma decisao so era o caminho para metade das
    instituicoes ficarem sem representante.
    """
    resposta = cliente_admin.post(
        "/api/instituicoes",
        json={
            "nome": "ABCON",
            "nome_completo": "Associacao Brasileira das Concessionarias Privadas",
            "tipo": "entidade",
            "representante": {
                "nome": "Percy Soares",
                "email": "percy@abcon.example",
                "cargo": "Diretor executivo",
            },
        },
    )

    assert resposta.status_code == 201, resposta.text
    criada = resposta.json()
    assert criada["nome_completo"].startswith("Associacao")

    pessoas = [
        p
        for p in cliente_admin.get("/api/interlocutores").json()
        if p["instituicao_id"] == criada["id"]
    ]
    assert len(pessoas) == 1
    assert pessoas[0]["email"] == "percy@abcon.example"
    assert pessoas[0]["cargo"] == "Diretor executivo"


def test_a_instituicao_nao_entra_sozinha_se_o_representante_falhar(
    cliente_admin, semente
):
    """As duas escritas caem ou passam JUNTAS.

    Em duas requisicoes, uma falha na segunda deixaria a instituicao criada e
    sem representante — e a tela teria de explicar um estado meio-feito que
    ninguem pediu. Aqui o `flush` do representante estoura antes do commit, e
    nada entra.
    """
    resposta = cliente_admin.post(
        "/api/instituicoes",
        json={
            "nome": "Instituicao Fantasma",
            "tipo": "orgao",
            # `nome` vazio: `min_length=1` recusa antes de qualquer escrita.
            "representante": {"nome": ""},
        },
    )

    assert resposta.status_code == 422
    achadas = [
        i
        for i in cliente_admin.get("/api/instituicoes").json()
        if i["nome"] == "Instituicao Fantasma"
    ]
    assert achadas == [], "a instituicao entrou sem o representante"


def test_o_representante_e_opcional(cliente_admin, semente):
    """A prova negativa: exigir representante travaria o cadastro.

    Nem toda instituicao tem contato conhecido no dia em que entra na base.
    """
    resposta = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao Sem Contato", "tipo": "orgao"}
    )

    assert resposta.status_code == 201, resposta.text


def test_editar_instituicao_nao_cria_pessoa(cliente_admin, semente):
    """`representante` e ignorado na edicao, e isso e deliberado.

    Aceita-lo criaria uma pessoa nova a cada salvamento de nome — e o cadastro
    encheria de duplicatas sem ninguem entender de onde vieram.
    """
    criada = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao Z", "tipo": "orgao"}
    ).json()

    cliente_admin.put(
        f"/api/instituicoes/{criada['id']}",
        json={
            "nome": "Orgao Z",
            "tipo": "orgao",
            "representante": {"nome": "Nao deve ser criado"},
        },
    )

    pessoas = [
        p
        for p in cliente_admin.get("/api/interlocutores").json()
        if p["instituicao_id"] == criada["id"]
    ]
    assert pessoas == []


# -- apagar e desligar sao coisas diferentes -----------------------------------


def test_apagar_pessoa_que_entrou_por_engano(cliente_admin, semente):
    """Nome errado, instituicao errada: e lixo, e apagar e o certo."""
    instituicao = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao W", "tipo": "orgao"}
    ).json()
    pessoa = cliente_admin.post(
        "/api/interlocutores",
        json={"nome": "Nome Digitado Errado", "instituicao_id": instituicao["id"]},
    ).json()

    resposta = cliente_admin.delete(f"/api/interlocutores/{pessoa['id']}")

    assert resposta.status_code == 204, resposta.text
    restantes = [
        p for p in cliente_admin.get("/api/interlocutores").json() if p["id"] == pessoa["id"]
    ]
    assert restantes == []


def test_nao_apaga_quem_ja_esteve_numa_agenda(cliente_admin, semente):
    """Apagar deixaria a agenda sem o nome de quem esteve na sala.

    E o que este painel existe para guardar. O banco recusaria pela chave
    estrangeira, mas com mensagem de constraint — e quem lesse nao saberia o
    que fazer. A recusa aqui diz quantas agendas dependem e qual e o gesto.
    """
    instituicao = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao V", "tipo": "orgao"}
    ).json()
    pessoa = cliente_admin.post(
        "/api/interlocutores",
        json={"nome": "Esteve na reuniao", "instituicao_id": instituicao["id"]},
    ).json()

    agenda = corpo(semente)
    agenda["instituicao_id"] = instituicao["id"]
    agenda["outra_parte"] = [{"interlocutor_id": pessoa["id"], "principal": True}]
    criada = cliente_admin.post("/api/interacoes", json=agenda)
    assert criada.status_code == 201, criada.text

    resposta = cliente_admin.delete(f"/api/interlocutores/{pessoa['id']}")

    assert resposta.status_code == 422
    detalhe = resposta.json()["detalhe"]
    assert "1 agenda" in detalhe
    #: E diz o que fazer, e nao so o que nao da.
    assert "Desligar" in detalhe


def test_desligar_e_o_caminho_para_quem_tem_historico(cliente_admin, semente):
    """A prova positiva do teste acima: sai das listas, o historico fica."""
    instituicao = cliente_admin.post(
        "/api/instituicoes", json={"nome": "Orgao U", "tipo": "orgao"}
    ).json()
    pessoa = cliente_admin.post(
        "/api/interlocutores",
        json={"nome": "Ja participou", "instituicao_id": instituicao["id"]},
    ).json()

    resposta = cliente_admin.put(
        f"/api/interlocutores/{pessoa['id']}",
        json={
            "nome": "Ja participou",
            "instituicao_id": instituicao["id"],
            "ativo": False,
        },
    )

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ativo"] is False


# -- porta-vozes e os assuntos que eles falam ----------------------------------


def test_porta_voz_com_os_assuntos_que_pode_falar(cliente_admin, semente):
    """A regra de "fora do escopo" ja estava modelada e nao era editavel.

    `PessoaAegeaTema` existe desde o comeco, com o docstring dizendo para que
    serve: registro cujo tema nao esta na lista do porta-voz que o conduziu. Os
    temas vinham da planilha e ficavam.
    """
    temas = cliente_admin.get("/api/temas").json()
    escolhidos = [t["id"] for t in temas[:2]]

    resposta = cliente_admin.post(
        "/api/pessoas-aegea",
        json={
            "nome": f"Porta-voz {uuid4().hex[:6]}",
            "cargo": "Diretor de Relacoes Institucionais",
            "email": "radames@aegea.example",
            "temas": escolhidos,
        },
    )

    assert resposta.status_code == 201, resposta.text
    criada = resposta.json()
    assert criada["email"] == "radames@aegea.example"

    de_volta = cliente_admin.get(f"/api/pessoas-aegea/{criada['id']}/temas").json()
    assert sorted(de_volta) == sorted(escolhidos)


def test_a_lista_de_assuntos_substitui_a_anterior(cliente_admin, semente):
    """A lista inteira manda, como nas demais listas do produto.

    E o `_aplicar_temas_da_pessoa` casa por (pessoa, tema): o que permanece nao
    sai e volta, e a trilha nao registra movimento para um tema que nao mudou.
    """
    temas = [t["id"] for t in cliente_admin.get("/api/temas").json()[:3]]
    nome_unico = f"Porta-voz {uuid4().hex[:6]}"
    pessoa = cliente_admin.post(
        "/api/pessoas-aegea", json={"nome": nome_unico, "temas": temas[:2]}
    ).json()

    cliente_admin.put(
        f"/api/pessoas-aegea/{pessoa['id']}",
        json={"nome": nome_unico, "temas": temas[1:]},
    )

    de_volta = cliente_admin.get(f"/api/pessoas-aegea/{pessoa['id']}/temas").json()
    assert sorted(de_volta) == sorted(temas[1:])


def test_porta_voz_sem_assunto_e_permitido(cliente_admin, semente):
    """Exigir assunto travaria o cadastro de quem ainda nao teve a lista
    definida — e uma pessoa sem tema so significa que nada foi autorizado."""
    resposta = cliente_admin.post("/api/pessoas-aegea", json={"nome": "Sem temas"})

    assert resposta.status_code == 201, resposta.text
    assert cliente_admin.get(f"/api/pessoas-aegea/{resposta.json()['id']}/temas").json() == []


# -- assuntos ------------------------------------------------------------------


def test_cadastrar_assunto(cliente_admin, semente):
    resposta = cliente_admin.post(
        "/api/temas", json={"nome": "Reajuste tarifario 2027", "nivel": "estrategico"}
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["nivel"] == "estrategico"


def test_nivel_inventado_e_recusado(cliente_admin, semente):
    resposta = cliente_admin.post(
        "/api/temas", json={"nome": "Qualquer", "nivel": "importante"}
    )

    assert resposta.status_code == 422
    assert "estrategico" in resposta.json()["detalhe"]


def test_a_listagem_de_assuntos_mostra_os_inativos(cliente_admin, semente):
    """`/api/dicionarios` devolve so os ativos, porque alimenta filtro e
    formulario. Quem administra precisa ver o que desativou — senao o assunto
    some da tela e reaparece como "ja existe" na proxima tentativa de criar.
    """
    criado = cliente_admin.post(
        "/api/temas", json={"nome": "Assunto encerrado"}
    ).json()
    cliente_admin.put(
        f"/api/temas/{criado['id']}", json={"nome": "Assunto encerrado", "ativo": False}
    )

    listagem = cliente_admin.get("/api/temas").json()
    achado = next(t for t in listagem if t["id"] == criado["id"])
    assert achado["ativo"] is False


def test_quem_edita_agenda_nao_cadastra_assunto(cliente, semente):
    """A mesma separacao de papeis das instituicoes."""
    resposta = cliente.post("/api/temas", json={"nome": "Nao deveria entrar"})

    assert resposta.status_code == 403


def test_pessoa_repetida_na_mesma_instituicao_e_recusada_com_mensagem(
    cliente_admin, semente
):
    """Medido pela API: a segunda dava 500, e nao erro de dominio.

    As rotas de interlocutor tinham ficado FORA do `_gravar` — o helper que
    existe justamente para traduzir colisao de indice unico em mensagem de
    gente. Criar o helper e deixar duas chamadas de fora e o mesmo defeito que
    ele evita, so que mais dificil de ver.
    """
    instituicao = cliente_admin.post(
        "/api/instituicoes", json={"nome": f"Orgao {uuid4().hex[:6]}", "tipo": "orgao"}
    ).json()

    primeira = cliente_admin.post(
        "/api/interlocutores",
        json={"nome": "Ana Prado", "instituicao_id": instituicao["id"]},
    )
    repetida = cliente_admin.post(
        "/api/interlocutores",
        json={"nome": "  ANA PRADO  ", "instituicao_id": instituicao["id"]},
    )

    assert primeira.status_code == 201, primeira.text
    assert repetida.status_code == 422, repetida.text
    assert "ja esta cadastrada" in repetida.json()["detalhe"]


def test_a_mesma_pessoa_em_instituicoes_diferentes_e_permitida(cliente_admin, semente):
    """A prova negativa: o indice e `(nome, instituicao)`, e nao so o nome.

    Homonimos existem, e a mesma pessoa pode representar duas entidades.
    Barrar pelo nome sozinho recusaria cadastro legitimo.
    """
    a = cliente_admin.post(
        "/api/instituicoes", json={"nome": f"Orgao {uuid4().hex[:6]}", "tipo": "orgao"}
    ).json()
    b = cliente_admin.post(
        "/api/instituicoes", json={"nome": f"Orgao {uuid4().hex[:6]}", "tipo": "orgao"}
    ).json()

    for instituicao in (a, b):
        resposta = cliente_admin.post(
            "/api/interlocutores",
            json={"nome": "Carlos Nunes", "instituicao_id": instituicao["id"]},
        )
        assert resposta.status_code == 201, resposta.text
