"""Conceder e revogar acesso.

A ESCRITA NÃO ACONTECE AQUI: acontece na função `conceder_acesso` do banco. A
aplicação não tem `grant` para alterar `papel_id`, `acesso_irrestrito`,
`acesso_sensivel` ou `usuario_escopo` — tem `execute` na função.

O QUE ISSO PROTEGE, E O QUE NÃO PROTEGE. A função NÃO é fronteira de
autorização: quem tem a connection string a chama direto, escolhendo
`quem_concede`, e concede o que quiser a quem quiser — o banco não distingue "a
aplicação agindo por um administrador" de "alguém com a credencial da
aplicação".

    PROTEGE     estado inválido (a função valida papel, prazo, frente,
                unidade), caminho futuro na aplicação que esqueça as regras, e
                a existência da trilha em `usuario_auditoria`
    NÃO PROTEGE contra quem detém a credencial do banco

**A fronteira de autorização é esta camada, em Python.** `exigir_administrador`
abaixo é o controle real; a função é integridade e trilha. Concessão por um
serviço separado, com credencial que o processo do painel não possui, é mudança
de arquitetura e está registrada em `seguranca/ARQUITETURA.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import (
    Papel as PapelRegistro,
)
from app.banco.tabelas_acesso import (
    Usuario,
    UsuarioEscopo,
)
from app.banco.tabelas_exportacoes import ExportacaoRegistro
from app.banco.tabelas_score import CargaDeBase
from app.dominio.erros import Conflito, NaoAutorizado, RegraViolada
from app.dominio.identidade import UsuarioAtual
from app.seguranca.cache_de_autorizacao import esquecer_em_todos


@dataclass(frozen=True, slots=True)
class Concessao:
    """O que se quer que a pessoa passe a alcançar."""

    papel: str | None
    acesso_irrestrito: bool = False
    #: A terceira camada: se esta pessoa alcança os campos sensíveis do CRM.
    #:
    #: FECHA POR PADRÃO, como as bandeiras de `Papel`: uma concessão montada por
    #: dentro (rotina de importação, comando de manutenção, caso de uso novo) que
    #: não tome essa decisão não deve conceder o relato por omissão. Diferente de
    #: `versao_vista`, que é obrigatório por ser token de concorrência, onde não
    #: existe padrão seguro; para bandeira de permissão existe, e é `False`.
    sensivel: bool = False
    externo: bool = False
    expira_em: date | None = None
    frentes: tuple[str, ...] = ()
    unidades: tuple[str, ...] = ()
    #: O `concedido_em` que a tela viu ao abrir o formulário.
    #:
    #: NULO NÃO É CURINGA: afirma "vi esta pessoa sem concessão nenhuma", e só
    #: passa se o banco também estiver sem — é o caso da primeira concessão, e
    #: nada além dele. Sem a versão, dois administradores editando a mesma pessoa
    #: fazem o segundo apagar o primeiro, sem conflito e sem aviso.
    #:
    #: OBRIGATÓRIO (e `kw_only` só para poder sê-lo depois de campos com padrão):
    #: omitir o campo afirmaria "vi sem concessão" sem ter olhado, e é por dentro
    #: que passam as chamadas que ninguém revisa como entrada. Assim, esquecer é
    #: `TypeError` na hora, e não sobrescrita silenciosa meses depois.
    versao_vista: datetime | None = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class LinhaDeAcesso:
    """Uma pessoa, na tela de administração."""

    id: UUID
    nome: str
    email: str
    ativo: bool
    papel: str | None
    acesso_irrestrito: bool
    #: O que está gravado na pessoa. NÃO é o acesso efetivo: o efetivo é este
    #: valor E `papel.ve_campos_sensiveis`. A tela mostra os dois, porque
    #: "marcado e sem efeito" é um estado que quem administra precisa ver.
    sensivel: bool
    externo: bool
    expira_em: date | None
    frentes: tuple[str, ...]
    unidades: tuple[str, ...]
    concedido_por: str | None
    concedido_em: str | None
    #: PRÉ-CADASTRADA E AINDA SEM ENTRAR (`0119`): tem papel, não tem vínculo com
    #: o Entra. Precisa aparecer na tela, e não é enfeite — é o que denuncia o
    #: pré-cadastro com e-mail errado, que nunca vai casar e ficaria para sempre na
    #: lista parecendo uma pessoa com acesso.
    aguardando_primeiro_acesso: bool


def exigir_administrador(usuario: UsuarioAtual) -> None:
    if usuario.papel is None or not usuario.papel.administra_acessos:
        raise NaoAutorizado("Seu perfil não administra acessos.")


def listar(sessao: Session, *, solicitante: UsuarioAtual) -> list[LinhaDeAcesso]:
    """Todas as pessoas e o que cada uma alcança."""
    exigir_administrador(solicitante)

    papeis = {p.id: p.codigo for p in sessao.scalars(select(PapelRegistro))}
    nomes = {u.id: u.nome for u in sessao.scalars(select(Usuario))}

    # Uma consulta para todo o escopo, agrupada em memória. Buscar por pessoa
    # seria N+1 numa tela que existe justamente para ver todo mundo de uma vez.
    escopos: dict[UUID, dict[str, list[str]]] = {}
    for linha in sessao.execute(
        select(UsuarioEscopo.usuario_id, UsuarioEscopo.dimensao, UsuarioEscopo.valor)
    ).all():
        escopos.setdefault(linha.usuario_id, {}).setdefault(linha.dimensao, []).append(
            linha.valor
        )

    pessoas = sessao.scalars(select(Usuario).order_by(Usuario.nome)).all()
    return [
        LinhaDeAcesso(
            id=pessoa.id,
            nome=pessoa.nome,
            email=str(pessoa.email),
            ativo=pessoa.ativo,
            papel=papeis.get(pessoa.papel_id),
            acesso_irrestrito=pessoa.acesso_irrestrito,
            sensivel=pessoa.acesso_sensivel,
            externo=pessoa.externo,
            expira_em=pessoa.acesso_expira_em,
            frentes=tuple(sorted(escopos.get(pessoa.id, {}).get("frente", []))),
            unidades=tuple(
                sorted(escopos.get(pessoa.id, {}).get("unidade_negocio", []))
            ),
            concedido_por=nomes.get(pessoa.papel_concedido_por),
            concedido_em=(
                pessoa.papel_concedido_em.isoformat()
                if pessoa.papel_concedido_em
                else None
            ),
            aguardando_primeiro_acesso=pessoa.entra_object_id is None,
        )
        for pessoa in pessoas
    ]


@dataclass(frozen=True, slots=True)
class LinhaDeIndicador:
    """Uma pessoa e o quanto ela usou a plataforma num período."""

    id: UUID
    nome: str
    email: str
    logins: int
    uploads: int
    interacoes_criadas: int
    ultimo_acesso_em: str | None


def indicadores_de_uso(
    sessao: Session, *, solicitante: UsuarioAtual, de: date, ate: date
) -> list[LinhaDeIndicador]:
    """Login, upload de base e interação criada, por pessoa, entre `de` e `ate`
    (as duas datas inclusas).

    TRÊS CONTAGENS, TRÊS TABELAS JÁ EXISTENTES — nenhuma rastreia uso por si
    só pensando nesta tela (`acesso_log` existe para investigar incidente,
    `carga_de_base` para auditar carga, `interacao.criado_por` é autoria comum
    do CRM). Juntar as três aqui é a parte nova; os dados em si já eram
    confiáveis e indexados por `usuario_id`/`criado_por`.
    """
    exigir_administrador(solicitante)

    # Limite superior EXCLUSIVO: `ate` é uma data de calendário (o último dia
    # que deve entrar inteiro), e as colunas são `timestamptz`. `< ate+1dia`
    # inclui o dia inteiro sem truncar a hora digitada.
    ate_exclusivo = ate + timedelta(days=1)

    linhas = sessao.execute(
        text(
            "select u.id, u.nome, u.email, u.ultimo_acesso_em, "
            "       coalesce(logins.qtd, 0) as logins, "
            "       coalesce(uploads.qtd, 0) as uploads, "
            "       coalesce(interacoes.qtd, 0) as interacoes_criadas "
            "  from usuario u "
            "  left join ( "
            "    select usuario_id, count(*) as qtd "
            "      from acesso_log "
            "     where resultado = 'sucesso' "
            "       and ocorrido_em >= :de and ocorrido_em < :ate "
            "     group by usuario_id "
            "  ) logins on logins.usuario_id = u.id "
            "  left join ( "
            "    select usuario_id, count(*) as qtd "
            "      from carga_de_base "
            "     where concluida_em >= :de and concluida_em < :ate "
            "     group by usuario_id "
            "  ) uploads on uploads.usuario_id = u.id "
            "  left join ( "
            "    select criado_por as usuario_id, count(*) as qtd "
            "      from interacao "
            "     where criado_em >= :de and criado_em < :ate "
            "     group by criado_por "
            "  ) interacoes on interacoes.usuario_id = u.id "
            " order by u.nome"
        ),
        {"de": de, "ate": ate_exclusivo},
    ).all()

    return [
        LinhaDeIndicador(
            id=linha.id,
            nome=linha.nome,
            email=str(linha.email),
            logins=linha.logins,
            uploads=linha.uploads,
            interacoes_criadas=linha.interacoes_criadas,
            ultimo_acesso_em=(
                linha.ultimo_acesso_em.isoformat() if linha.ultimo_acesso_em else None
            ),
        )
        for linha in linhas
    ]


@dataclass(frozen=True, slots=True)
class PessoaNoDia:
    """Quantas vezes UMA pessoa logou num dia — a quebra por trás do total."""

    nome: str
    logins: int


@dataclass(frozen=True, slots=True)
class AcessoNoDia:
    """Quantos logins bem-sucedidos aconteceram num dia, e de quem."""

    data: str
    logins: int
    #: VAZIO no detalhe por pessoa (`detalhe_de_uso`): lá o dia já está
    #: filtrado a uma pessoa só, então listar "ela mesma" de novo não
    #: acrescenta nada. Só `acessos_por_dia` (todas as pessoas) preenche isto —
    #: é o que o tooltip do gráfico geral usa para responder "quem".
    pessoas: list[PessoaNoDia]


def acessos_por_dia(
    sessao: Session, *, solicitante: UsuarioAtual, de: date, ate: date
) -> list[AcessoNoDia]:
    """Total de logins bem-sucedidos (todas as pessoas) e quem logou, por dia,
    entre `de` e `ate` (as duas inclusas). Só dias com pelo menos um login
    aparecem — a tela decide como preencher os dias sem nenhum.
    """
    exigir_administrador(solicitante)

    ate_exclusivo = ate + timedelta(days=1)
    linhas = sessao.execute(
        text(
            "select date(a.ocorrido_em) as dia, u.nome, count(*) as qtd "
            "  from acesso_log a "
            "  join usuario u on u.id = a.usuario_id "
            " where a.resultado = 'sucesso' "
            "   and a.ocorrido_em >= :de and a.ocorrido_em < :ate "
            " group by date(a.ocorrido_em), u.nome "
            " order by dia, u.nome"
        ),
        {"de": de, "ate": ate_exclusivo},
    ).all()

    por_dia: dict[str, list[PessoaNoDia]] = {}
    for linha in linhas:
        dia = linha.dia.isoformat()
        por_dia.setdefault(dia, []).append(PessoaNoDia(nome=linha.nome, logins=linha.qtd))

    return [
        AcessoNoDia(data=dia, logins=sum(p.logins for p in pessoas), pessoas=pessoas)
        for dia, pessoas in por_dia.items()
    ]


@dataclass(frozen=True, slots=True)
class CargaNoDetalhe:
    """Uma carga desta pessoa, na tela de indicadores."""

    base: str
    #: Nulo quando a carga veio sem nome a dar (ex.: ingestão por bytes).
    arquivo: str | None
    linhas: int
    concluida_em: str


@dataclass(frozen=True, slots=True)
class ExportacaoNoDetalhe:
    """Uma exportação de CSV da Base desta pessoa.

    SEM NOME DE ARQUIVO: a exportação da Base não gera arquivo no servidor —
    é montada no navegador a partir do que a listagem já devolveu. O que dá
    para mostrar é o filtro aplicado e quantas linhas ele alcançava.
    """

    filtros: dict
    total_de_registros: int
    criado_em: str


@dataclass(frozen=True, slots=True)
class DetalheDeUso:
    cargas: list[CargaNoDetalhe]
    exportacoes: list[ExportacaoNoDetalhe]
    logins_por_dia: list[AcessoNoDia]


#: Teto de linhas por lista — a mesma régua do `/acessos/{id}/historico`: uma
#: tela de detalhe por pessoa não precisa do histórico inteiro de anos, só do
#: suficiente para responder "o que essa pessoa andou fazendo".
TETO_DO_DETALHE = 200


def detalhe_de_uso(
    sessao: Session, *, solicitante: UsuarioAtual, usuario_id: UUID, de: date, ate: date
) -> DetalheDeUso:
    """As cargas e exportações de UMA pessoa, entre `de` e `ate` (inclusas).

    O DRILL-DOWN da tela de indicadores: lá aparece "3 uploads" ao lado do
    nome, e esta função é o que responde "quais, de qual base, quando".
    """
    exigir_administrador(solicitante)

    ate_exclusivo = ate + timedelta(days=1)

    cargas = sessao.scalars(
        select(CargaDeBase)
        .where(CargaDeBase.usuario_id == usuario_id)
        .where(CargaDeBase.concluida_em >= de)
        .where(CargaDeBase.concluida_em < ate_exclusivo)
        .order_by(CargaDeBase.concluida_em.desc())
        .limit(TETO_DO_DETALHE)
    ).all()

    exportacoes = sessao.scalars(
        select(ExportacaoRegistro)
        .where(ExportacaoRegistro.criado_por == usuario_id)
        .where(ExportacaoRegistro.criado_em >= de)
        .where(ExportacaoRegistro.criado_em < ate_exclusivo)
        .order_by(ExportacaoRegistro.criado_em.desc())
        .limit(TETO_DO_DETALHE)
    ).all()

    logins_por_dia = sessao.execute(
        text(
            "select date(ocorrido_em) as dia, count(*) as qtd "
            "  from acesso_log "
            " where usuario_id = :usuario_id and resultado = 'sucesso' "
            "   and ocorrido_em >= :de and ocorrido_em < :ate "
            " group by date(ocorrido_em) "
            " order by dia"
        ),
        {"usuario_id": usuario_id, "de": de, "ate": ate_exclusivo},
    ).all()

    return DetalheDeUso(
        cargas=[
            CargaNoDetalhe(
                base=c.base,
                arquivo=c.arquivo,
                linhas=c.linhas,
                concluida_em=c.concluida_em.isoformat(),
            )
            for c in cargas
        ],
        exportacoes=[
            ExportacaoNoDetalhe(
                filtros=e.filtros,
                total_de_registros=e.total_de_registros,
                criado_em=e.criado_em.isoformat(),
            )
            for e in exportacoes
        ],
        logins_por_dia=[
            AcessoNoDia(data=linha.dia.isoformat(), logins=linha.qtd, pessoas=[])
            for linha in logins_por_dia
        ],
    )


def conceder(
    sessao: Session,
    *,
    alvo: UUID,
    concessao: Concessao,
    solicitante: UsuarioAtual,
) -> None:
    """Aplica a concessão pela função do banco."""
    exigir_administrador(solicitante)

    if alvo == solicitante.id:
        # Não é paranoia: administrador que se rebaixa por engano fica sem
        # conseguir se consertar, e quem conserta é quem tem o mesmo papel — que
        # pode não existir. Pior ainda seria alguém se conceder mais do que tem.
        raise RegraViolada(
            "Ninguém altera o próprio acesso. Peça a outra pessoa da coordenação."
        )

    try:
        sessao.execute(
            text(
                "select conceder_acesso("
                ":alvo, :quem, :papel, :irrestrito, :externo, :expira, "
                ":frentes, :unidades, :versao, :sensivel)"
            ),
            {
                "alvo": alvo,
                "quem": solicitante.id,
                "papel": concessao.papel,
                "irrestrito": concessao.acesso_irrestrito,
                "externo": concessao.externo,
                "expira": concessao.expira_em,
                "frentes": list(concessao.frentes),
                "unidades": list(concessao.unidades),
                "versao": concessao.versao_vista,
                "sensivel": concessao.sensivel,
            },
        )
    except DBAPIError as erro:
        # A função levanta `raise exception` com mensagem escrita para gente:
        # "Acesso externo exige prazo", "Papel desconhecido". Traduzir para
        # `RegraViolada` faz o front mostrar o texto certo em vez de 500.
        raise RegraViolada(_mensagem_do_banco(erro)) from erro

    # A função escreveu por SQL, por fora do ORM, então o mapa de identidade da
    # sessão continua com os valores antigos: qualquer leitura seguinte NESTA
    # sessão devolveria o acesso anterior, inclusive uma que decidisse permissão.
    # Expira só o alvo — `expire_all()` descartaria o estado de objetos sem
    # relação com a concessão, e o efeito apareceria longe daqui.
    alterado = sessao.get(Usuario, alvo)
    if alterado is not None:
        sessao.expire(alterado)

    # Mesmo motivo do `expire` acima, uma camada adiante: papel e escopo ficam em
    # memória por `autorizacao_cache_segundos` (ver
    # `app/seguranca/cache_de_autorizacao.py`), e sem esta linha a concessão que
    # acabou de ser gravada só valeria quando a entrada vencesse. É o que faz a
    # revogação pela TELA valer no ato. Revogação por SQL direto no banco não
    # passa por aqui e segue limitada ao TTL.
    esquecer_em_todos(alvo)


def pre_cadastrar(
    sessao: Session,
    *,
    email: str,
    nome: str,
    concessao: Concessao,
    solicitante: UsuarioAtual,
) -> UUID:
    """Cria o PRÉ-CADASTRO e concede o acesso, antes do primeiro login.

    POR QUE EXISTE: sem isto a pessoa só passava a existir depois de ser
    RECUSADA — `provisionar` criava a linha sem papel e o callback barrava. Numa
    estreia com diretores, isso é um lote de "seu acesso ainda não foi liberado"
    antes de alguém poder agir.

    A CONCESSÃO É A MESMA, e não é detalhe: delega a `conceder`, única porta para
    as colunas de autorização (`conceder_acesso`, 0006). O pré-cadastro herda as
    conferências do banco, a auditoria e a invalidação de cache — um `insert`
    paralelo com as mesmas colunas seria uma segunda regra livre para divergir.

    NÃO CONCEDE ENTRADA, só papel. Sem o grupo do SSO não há token, e a linha
    fica parada: a `0096` segue sendo o único caminho de entrada.

    NADA É ENVIADO, e isto está escrito porque o nome "convite" — que esta função
    teve por um tempo — faz esperar o contrário. Não há e-mail, link nem
    notificação: grava-se nome, e-mail e papel, e quem avisa a pessoa é quem a
    cadastra no Entra ID. Se um dia houver aviso automático, ele é mudança nova e
    tem de aparecer aqui.
    """
    exigir_administrador(solicitante)

    #: SÓ O ÓBVIO. Conferir formato não pega o erro que importa — e-mail válido e
    #: ERRADO —, que é o que deixa o pré-cadastro sem casar para sempre. Ver a `0119`.
    if "@" not in email:
        raise RegraViolada("E-mail inválido.")

    achado = sessao.scalar(select(Usuario).where(Usuario.email == email))
    if achado is not None:
        #: DUAS MENSAGENS, porque as ações que resolvem são diferentes: conta
        #: existente se edita na lista; pré-cadastro pendente só espera o primeiro
        #: login.
        raise Conflito(
            "Esta pessoa já tem conta no painel. Edite o acesso dela na lista."
            if achado.entra_object_id is not None
            else "Esta pessoa já tem pré-cadastro e ainda não entrou."
        )

    pessoa = Usuario(entra_object_id=None, email=email, nome=nome)
    sessao.add(pessoa)
    #: A CONFERÊNCIA ACIMA NÃO BASTA, e o `except` não é zelo — achado de
    #: revisão. Entre o `select` e o `insert` não há trava: dois administradores
    #: pré-cadastrando o mesmo e-mail passavam os dois pela conferência, e o
    #: segundo levava `UniqueViolation` crua, que chega à tela como 500.
    #:
    #: O `select` FICA, e não é redundante: ele é quem produz a mensagem que
    #: distingue "já tem conta" de "já tem pré-cadastro", e essa distinção o erro
    #: do banco não carrega. Aqui só o caso raro é traduzido.
    #:
    #: SAVEPOINT porque a violação aborta a transação: sem ele, a requisição
    #: inteira já estaria perdida quando o `Conflito` chegasse ao tratador.
    try:
        with sessao.begin_nested():
            sessao.flush()
    except IntegrityError as erro:
        raise Conflito(
            "Esta pessoa acabou de ser cadastrada por outra pessoa. "
            "Recarregue a lista."
        ) from erro

    conceder(sessao, alvo=pessoa.id, concessao=concessao, solicitante=solicitante)
    return pessoa.id


def definir_situacao(
    sessao: Session,
    *,
    alvo: UUID,
    ativa: bool,
    solicitante: UsuarioAtual,
) -> None:
    """Liga e desliga uma conta. É a REMOÇÃO do produto.

    NÃO EXISTE APAGAR PESSOA, e não é omissão: dez chaves estrangeiras apontam
    para `usuario` e `interacao.criado_por` é `not null`, então o banco recusa
    apagar quem já registrou qualquer coisa — e deve, porque apagar o autor
    apagaria a autoria. Desligar preserva o histórico e tira o acesso.

    A ESCRITA É `update` DIRETO, e não pela função `conceder_acesso`: `ativo` não
    é concessão. A trilha não se perde — o gatilho `auditar_acesso_do_usuario`
    vigia `ativo` junto com `papel_id`, e o autor vem do `SET LOCAL` que toda
    requisição autenticada carimba.
    """
    exigir_administrador(solicitante)

    if alvo == solicitante.id:
        # Mesma razão de `conceder`: quem se desliga não consegue se religar, e
        # quem religa é outro administrador — que pode não existir.
        raise RegraViolada(
            "Ninguém desativa a própria conta. Peça a outra pessoa da coordenação."
        )

    registro = sessao.get(Usuario, alvo)
    if registro is None:
        raise RegraViolada("Pessoa não encontrada.")

    if registro.ativo == ativa:
        # Sem isto, dois cliques seguidos gravariam duas linhas na trilha, a
        # segunda dizendo que `ativo` mudou de `false` para `false`.
        return

    # O CADEADO, e só quando o alvo administra: ver
    # `0010_ultimo_administrador.sql`. Desativar um leitor não pode deixar a
    # plataforma sem administrador, e serializar essas operações com as outras
    # criaria recusas sem motivo.
    #
    # O ARGUMENTO SEQUENCIAL NÃO BASTA: "para desativar é preciso ser
    # administrador ativo, e ninguém desativa a própria conta, logo quem pede
    # sempre permanece" está certo em série e é inútil com duas transações ao
    # mesmo tempo — cada uma olha antes de a outra escrever, e as duas escrevem
    # em linhas diferentes, então nada as serializa. Sem o cadeado, dois
    # administradores desativando um ao outro em paralelo terminam com ZERO
    # ativos.
    alvo_administra = bool(
        registro.papel_id
        and sessao.scalar(
            select(PapelRegistro.administra_acessos).where(
                PapelRegistro.id == registro.papel_id, PapelRegistro.ativo
            )
        )
    )

    if not ativa and alvo_administra:
        # `try`, e não esperar: esperar cria deadlock. `carregar()` já carimbou
        # `ultimo_acesso_em` de quem pede, o que TRAVA a linha dele; se as duas
        # transações esperassem o cadeado, cada uma seguraria a linha que a
        # outra quer. Ver o bloco DEADLOCK em `0010_ultimo_administrador.sql`.
        if not sessao.scalar(
            text(
                "select pg_try_advisory_xact_lock("
                "chave_do_cadeado_de_administradores())"
            )
        ):
            raise RegraViolada(
                "Outra alteração de acesso está em andamento. "
                "Tente de novo em instantes."
            )
    registro.ativo = ativa
    sessao.flush()

    # DEPOIS da escrita, e sob o cadeado: se esta foi a última conta que
    # administrava, a exceção desfaz tudo. Conferir antes exigiria prever qual
    # campo importa; conferir depois pergunta direto o que se quer saber.
    if not ativa and alvo_administra:
        try:
            sessao.execute(text("select exigir_administrador_restante()"))
        except DBAPIError as erro:
            # Sem esta tradução a recusa chega como 500. A função levanta com
            # texto escrito para quem administra ler — o mesmo tratamento que
            # `conceder` já dava, e que aqui faltava.
            raise RegraViolada(_mensagem_do_banco(erro)) from erro

    # A permissão antiga não pode continuar sendo servida de memória.
    #
    # `conceder` já fazia isto, e não fazer aqui criaria a incoerência de
    # REBAIXAR alguém valer no ato e REMOVER a pessoa levar até o TTL do cache.
    esquecer_em_todos(alvo)


#: SQLSTATE de `raise exception` em PL/pgSQL.
#:
#: É o que a nossa função levanta, com texto escrito para gente ler: "Acesso
#: externo exige prazo", "Frente desconhecida: X". Qualquer OUTRO código vem do
#: Postgres, não de nós.
ERRO_LEVANTADO_PELA_FUNCAO = "P0001"


def _mensagem_do_banco(erro: DBAPIError) -> str:
    """Só repassa mensagem que a NOSSA função escreveu.

    O FILTRO É POR SQLSTATE, e não pela primeira linha do erro. Devolver a
    primeira linha de qualquer erro entregaria a forma do schema na tela:

        insert or update on table "usuario" violates foreign key constraint
        "usuario_papel_concedido_por_fkey"

    Nome de tabela e nome de constraint são informação para quem está procurando
    por onde entrar.
    """
    original = getattr(erro, "orig", None)
    codigo = getattr(original, "pgcode", None)

    if codigo == ERRO_LEVANTADO_PELA_FUNCAO:
        bruto = str(getattr(original, "diag", None) and original.diag.message_primary
                    or original)
        return bruto.strip().splitlines()[0]

    # Falha inesperada: o detalhe fica no log, pela cadeia de exceções.
    return "Não foi possível aplicar a concessão."
