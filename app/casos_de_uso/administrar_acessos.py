"""Conceder e revogar acesso.

A escrita não acontece aqui: acontece na função `conceder_acesso` do banco
(migration 0009). A aplicação não tem `grant` para alterar `papel_id`,
`acesso_irrestrito` ou `usuario_escopo` — tem `execute` na função.

O QUE ISSO PROTEGE, E O QUE NÃO PROTEGE

A função NÃO é fronteira de autorização. Quem tem a connection string a chama
diretamente, escolhendo `quem_concede`, e concede o que quiser a quem quiser: o
banco não distingue "a aplicação agindo por um administrador" de "alguém com a
credencial da aplicação" — as duas chegam pela mesma conta. Logo:

    PROTEGE     estado inválido (a função valida papel, prazo, frente, unidade),
                caminho futuro na aplicação que esqueça as regras, e a existência
                da trilha em `usuario_auditoria`
    NÃO PROTEGE contra quem detém a credencial do banco

**A fronteira de autorização é esta camada, em Python.** `exigir_administrador`
abaixo é o controle real; a função é integridade e trilha.

O que seria fronteira de verdade: concessão por um serviço separado, com
credencial que o processo do painel não possui. É mudança de arquitetura, está
registrada em `seguranca/ARQUITETURA.md`, e não entrou nesta onda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import (
    Papel as PapelRegistro,
)
from app.banco.tabelas_acesso import (
    Usuario,
    UsuarioEscopo,
)
from app.dominio.erros import NaoAutorizado, RegraViolada
from app.dominio.identidade import UsuarioAtual
from app.seguranca.cache_de_autorizacao import esquecer_em_todos


@dataclass(frozen=True, slots=True)
class Concessao:
    """O que se quer que a pessoa passe a alcançar."""

    papel: str | None
    acesso_irrestrito: bool = False
    externo: bool = False
    expira_em: date | None = None
    frentes: tuple[str, ...] = ()
    unidades: tuple[str, ...] = ()
    #: O `concedido_em` que a tela viu ao abrir o formulário.
    #:
    #: Nulo NÃO é curinga: afirma "vi esta pessoa sem concessão nenhuma", e só
    #: passa se o banco também estiver sem. É o caso da primeira concessão — e
    #: nada além dele. A lista traz `concedido_em` nulo para quem ainda não tem
    #: papel, e é isso que a tela devolve.
    #:
    #: Sem a versão, dois administradores editando a mesma pessoa fazem o
    #: segundo apagar o primeiro, sem conflito e sem aviso.
    #:
    #: OBRIGATÓRIO, e `kw_only` só para poder sê-lo depois de campos com padrão.
    #: Omitir o campo seria AFIRMAR "vi esta pessoa sem concessão nenhuma" sem
    #: ter olhado, e é por dentro que passam as chamadas que ninguém revisa como
    #: se fossem entrada: uma rotina de importação, um comando de manutenção, um
    #: caso de uso novo. Com o campo obrigatório, esquecer é `TypeError` na
    #: hora, e não uma sobrescrita silenciosa meses depois.
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
    externo: bool
    expira_em: date | None
    frentes: tuple[str, ...]
    unidades: tuple[str, ...]
    concedido_por: str | None
    concedido_em: str | None


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
        )
        for pessoa in pessoas
    ]


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
                ":frentes, :unidades, :versao)"
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
            },
        )
    except DBAPIError as erro:
        # A função levanta `raise exception` com mensagem escrita para gente:
        # "Acesso externo exige prazo", "Papel desconhecido". Traduzir para
        # `RegraViolada` faz o front mostrar o texto certo em vez de 500.
        raise RegraViolada(_mensagem_do_banco(erro)) from erro

    # A função escreveu por SQL, por fora do ORM. O mapa de identidade da sessão
    # continua com os valores antigos, então qualquer leitura seguinte NESTA
    # mesma sessão devolveria o acesso anterior — inclusive uma que decidisse
    # permissão.
    #
    # Expira só o alvo, e não a sessão inteira: `expire_all()` descartaria o
    # estado de objetos sem relação nenhuma com a concessão, e o efeito
    # apareceria longe daqui.
    alterado = sessao.get(Usuario, alvo)
    if alterado is not None:
        sessao.expire(alterado)

    # Pelo mesmo motivo do `expire` acima, uma camada adiante: papel e escopo
    # ficam em memória por `autorizacao_cache_segundos` (ver
    # `app/seguranca/cache_de_autorizacao.py`), e sem esta linha a concessão que
    # acabou de ser gravada só valeria quando a entrada vencesse.
    #
    # É o que faz a revogação pela TELA valer no ato — que é justamente quando
    # alguém confere se ela pegou. Revogação feita por SQL direto no banco não
    # passa por aqui e continua limitada pelo TTL; está documentado.
    esquecer_em_todos(alvo)


#: SQLSTATE de `raise exception` em PL/pgSQL.
#:
#: É o que a nossa função levanta, com texto escrito para gente ler: "Acesso
#: externo exige prazo", "Frente desconhecida: X". Qualquer OUTRO código vem do
#: Postgres, não de nós.
ERRO_LEVANTADO_PELA_FUNCAO = "P0001"


def _mensagem_do_banco(erro: DBAPIError) -> str:
    """Só repassa mensagem que a NOSSA função escreveu.

    O filtro é por SQLSTATE, e não pela primeira linha do erro. Devolver a
    primeira linha de qualquer erro entregaria a forma do schema na tela:

        insert or update on table "usuario" violates foreign key constraint
        "usuario_papel_concedido_por_fkey"

    Nome de tabela e nome de constraint são informação para quem está
    procurando por onde entrar. Filtrar por SQLSTATE é a diferença entre
    "mensagem que escrevi para o usuário" e "o que o Postgres achou de dizer".
    """
    original = getattr(erro, "orig", None)
    codigo = getattr(original, "pgcode", None)

    if codigo == ERRO_LEVANTADO_PELA_FUNCAO:
        bruto = str(getattr(original, "diag", None) and original.diag.message_primary
                    or original)
        return bruto.strip().splitlines()[0]

    # Falha inesperada: o detalhe fica no log, pela cadeia de exceções.
    return "Não foi possível aplicar a concessão."
