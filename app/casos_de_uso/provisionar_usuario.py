"""Provisionamento no login: a identidade nasce ou se liga aqui.

O mesmo caminho serve para o SSO real e para o provedor mock de desenvolvimento
— muda apenas de onde vêm as claims. Nunca há cadastro manual de senha.

O provisionamento cria a IDENTIDADE e não decide AUTORIZAÇÃO. `papel_id` e
`usuario_escopo` são concedidos por alguém com `administra_acessos`, pela tela
de administração de acessos; o login apenas os lê.

SÃO DOIS CAMINHOS DESDE A `0119`, e o docstring dizia só o primeiro:

* QUEM CHEGA SEM PRÉ-CADASTRO nasce aqui, sem papel nenhum — autenticado e
  autorizado a nada. É o comportamento correto para convidado B2B: adivinhar
  permissão para quem acabou de chegar de fora é o erro que se quer evitar.
* QUEM FOI PRÉ-CADASTRADO já existe, com papel, e este login só LIGA o `oid`
  àquela linha. Era o beco sem saída que a `0119` fecha: antes dela, a pessoa
  tinha de ser recusada uma vez para passar a existir.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import (
    Papel as PapelRegistro,
)
from app.banco.tabelas_acesso import (
    Usuario,
    UsuarioEscopo,
)
from app.dominio.erros import NaoAutorizado
from app.dominio.identidade import Escopo, Papel, Perfil, UsuarioAtual

#: De quanto em quanto tempo `ultimo_acesso_em` é atualizado.
#:
#: Sem essa folga, toda requisição — inclusive as de leitura — sujaria a sessão
#: e faria um UPDATE, transformando cada GET do painel numa escrita no banco.
#:
#: Este campo é conveniência de tela ("visto por último"), e não trilha: a folga
#: o torna impreciso de propósito. Quem responde "quem entrou, quando e de onde"
#: é `acesso_log`, escrita a cada tentativa por `aplicacao/registrar_acesso.py`.
FOLGA_DE_REGISTRO_DE_ACESSO = timedelta(minutes=5)


def provisionar(
    sessao: Session,
    *,
    entra_object_id: str,
    email: str,
    nome: str,
    papel_inicial: Perfil | None = None,
) -> UsuarioAtual:
    """Encontra o usuário pelo `oid` do diretório, ou o cria.

    Nome e e-mail são reescritos quando divergem das claims: para identidade, a
    fonte da verdade continua sendo o Entra ID.

    `papel_inicial` só age na **criação**, e existe para o provedor mock de
    desenvolvimento — sem ele, subir o ambiente local daria uma tela vazia. No
    SSO real ele fica nulo e a concessão é um ato explícito de alguém.
    """
    registro = sessao.scalar(
        select(Usuario).where(Usuario.entra_object_id == entra_object_id)
    )
    agora = datetime.now(UTC)

    if registro is None:
        # O e-mail também é único, e a busca acima foi por `entra_object_id`: sem
        # tratar a colisão, o `flush` abaixo levantaria `UniqueViolation` e a
        # pessoa veria um 500 opaco. As duas respostas possíveis estão em
        # `_vincular_pre_cadastro`.
        registro = _vincular_pre_cadastro(
            sessao, entra_object_id=entra_object_id, email=email
        )

    if registro is None:
        registro = Usuario(
            entra_object_id=entra_object_id,
            email=email,
            nome=nome,
            ultimo_acesso_em=agora,
        )
        if papel_inicial is not None:
            registro.papel_id = _id_do_papel(sessao, papel_inicial)
            registro.acesso_irrestrito = True
            registro.papel_concedido_em = agora
        sessao.add(registro)
        sessao.flush()
    else:
        # Só escreve o que mudou — do contrário toda leitura vira UPDATE.
        if registro.email != email:
            registro.email = email
        if registro.nome != nome:
            registro.nome = nome
        # CONTA DESATIVADA NÃO CARIMBA ÚLTIMO ACESSO. O login dela vai ser
        # recusado logo adiante, mas este ponto vem antes da decisão, e sem a
        # guarda o "último acesso" de quem acabou de ser REMOVIDO passava a ser
        # agora: na tela de acessos ela apareceria como quem entrou há um
        # instante, sugerindo que a remoção não pegou. Tentativa não é acesso, e
        # `acesso_log` grava a recusa com motivo, hora e IP.
        #
        # Para quem está apenas SEM PAPEL o carimbo continua: essa pessoa é
        # legítima, está esperando concessão, e "tentou entrar" é o que faz quem
        # administra saber que há alguém à espera.
        if registro.ativo and _passou_da_folga(registro.ultimo_acesso_em, agora):
            registro.ultimo_acesso_em = agora

    return _montar(sessao, registro)


def carregar(sessao: Session, usuario_id) -> UsuarioAtual | None:
    """Reconstrói o usuário a partir do id guardado na sessão.

    Papel e escopo vêm do banco, e não do cookie — é o que impede que uma sessão
    emitida ontem carregue as permissões de ontem.

    Esta função é o caminho CARO, e a dependência que a chama consulta antes o
    cache de autorização (`app/seguranca/cache_de_autorizacao.py`). Quem mexer
    aqui deve saber que o retorno fica em memória por
    `autorizacao_cache_segundos`: um campo novo acrescentado a `UsuarioAtual`
    herda essa janela sem pedir licença.
    """
    registro = sessao.get(Usuario, usuario_id)
    if registro is None or not registro.ativo:
        return None

    agora = datetime.now(UTC)
    #: PRÉ-CADASTRO NÃO CARIMBA ACESSO (`0119`), e o `check` do banco pegou isto:
    #: quem nunca foi vinculada nunca entrou, e carimbar aqui a mostraria na tela
    #: de acessos como usuária ativa — apagando o "nunca entrou" que é o único
    #: sinal de um convite com e-mail errado. Mesma regra da conta desativada em
    #: `provisionar`: carregar não é entrar.
    if registro.entra_object_id is not None and _passou_da_folga(
        registro.ultimo_acesso_em, agora
    ):
        registro.ultimo_acesso_em = agora

    return _montar(sessao, registro)


def _montar(sessao: Session, registro: Usuario) -> UsuarioAtual:
    return UsuarioAtual(
        id=registro.id,
        nome=registro.nome,
        email=registro.email,
        papel=_papel_de(sessao, registro.papel_id),
        escopo=_escopo_de(sessao, registro),
        acesso_sensivel=registro.acesso_sensivel,
        externo=registro.externo,
        acesso_expira_em=registro.acesso_expira_em,
        ativo=registro.ativo,
    )


def _id_do_papel(sessao: Session, codigo: Perfil) -> int | None:
    return sessao.scalar(select(PapelRegistro.id).where(PapelRegistro.codigo == codigo.value))


def _papel_de(sessao: Session, papel_id: int | None) -> Papel | None:
    if papel_id is None:
        return None
    registro = sessao.get(PapelRegistro, papel_id)
    # Papel desativado é o mesmo que papel nenhum: a revogação em massa é
    # `update papel set ativo = false`, e ela precisa surtir efeito no login
    # seguinte sem tocar em cada usuário.
    if registro is None or not registro.ativo:
        return None
    return Papel(
        codigo=registro.codigo,
        nome=registro.nome,
        pode_criar=registro.pode_criar,
        pode_editar_proprio=registro.pode_editar_proprio,
        pode_editar_tudo=registro.pode_editar_tudo,
        administra_dicionarios=registro.administra_dicionarios,
        administra_acessos=registro.administra_acessos,
        ve_campos_sensiveis=registro.ve_campos_sensiveis,
        ve_diretorio=registro.ve_diretorio,
        pode_exportar=registro.pode_exportar,
        acessa_crm=registro.acessa_crm,
        acessa_inteligencia_de_mercado=registro.acessa_inteligencia_de_mercado,
        acessa_score=registro.acessa_score,
    )


def _escopo_de(sessao: Session, registro: Usuario) -> Escopo:
    if registro.acesso_irrestrito:
        return Escopo.total()

    linhas = sessao.execute(
        select(UsuarioEscopo.dimensao, UsuarioEscopo.valor).where(
            UsuarioEscopo.usuario_id == registro.id
        )
    ).all()

    return Escopo(
        irrestrito=False,
        frentes=frozenset(v for d, v in linhas if d == "frente"),
        unidades=frozenset(v for d, v in linhas if d == "unidade_negocio"),
    )


def _vincular_pre_cadastro(
    sessao: Session, *, entra_object_id: str, email: str
) -> Usuario | None:
    """O pré-cadastro deste e-mail, já vinculado a este `oid` — ou nada.

    DUAS RESPOSTAS MUITO DIFERENTES para "o e-mail já existe", e quem decide é o
    `oid` da linha achada:

    * SEM `oid` é PRÉ-CADASTRO (`0119`): alguém concedeu o papel antes de a
      pessoa entrar, e este login é o vínculo. Devolve a MESMA linha — linha
      nova perderia o papel e o rastro de quem o concedeu.
    * COM `oid` é outra identidade para o mesmo e-mail, e aí recusa. Trocá-lo em
      silêncio entregaria a conta de uma pessoa a outra que apenas tenha o mesmo
      e-mail; acontece de verdade em desenvolvimento, alternando entre
      `AUTH_MOCK` e o SSO real. A resolução é humana.

    QUEM CASA É O E-MAIL QUE O TOKEN AFIRMA, e nunca algo digitado no login. O
    `oidc.validar` o tira de `preferred_username`, `email` ou `upn` de um
    `id_token` com assinatura, emissor, audiência, `nonce` e `tid` conferidos —
    então vale o que o TENANT afirma, e token de outro diretório é recusado
    antes de chegar aqui.

    NÃO É "E-MAIL VERIFICADO" no sentido do `email_verified` do OIDC, e a
    diferença importa: `preferred_username` é o nome de entrada que a
    administração do Entra controla. O risco que sobra é dela — UPN de alguém que
    saiu, reatribuído a outra pessoa, vincularia um pré-cadastro feito para a
    primeira. É o mesmo risco que o e-mail já carrega para qualquer usuário desde
    a `0003`, e não se fecha daqui.

    E DIGITADO ERRADO NO PRÉ-CADASTRO, não casa: a pessoa ganha linha nova sem
    papel e é recusada como antes, e o pré-cadastro fica na tela como "nunca
    entrou".
    """
    #: PELA FUNÇÃO, E NÃO POR ATRIBUIÇÃO — achado de revisão, e era defeito que
    #: só apareceria em produção: a `0009` não dá `update` em `entra_object_id` à
    #: aplicação, então escrevê-lo aqui daria `permission denied for column`
    #: no primeiro login de todo pré-cadastrado. O banco de teste roda como
    #: superusuário e não pegaria.
    #:
    #: E A FUNÇÃO VINCULA SÓ O QUE AINDA NÃO TEM `oid`, num `update` só: dois
    #: logins concorrentes contra o mesmo pré-cadastro não se sobrescrevem. Ver a
    #: `0119`.
    vinculado = sessao.scalar(
        text("select vincular_pre_cadastro(cast(:email as citext), :oid)"),
        {"email": email, "oid": entra_object_id},
    )
    if vinculado is not None:
        registro = sessao.get(Usuario, vinculado)
        #: A FUNÇÃO ESCREVEU POR SQL, por fora do ORM. Sem expirar, a sessão
        #: devolveria a linha com `entra_object_id` ainda nulo — e o carimbo de
        #: último acesso logo adiante bateria no `check` da `0119`.
        sessao.expire(registro)
        return registro

    #: NULO NÃO DIZ QUAL DOS DOIS CASOS É: não havia linha com este e-mail, ou
    #: havia uma JÁ vinculada. A consulta separa, e é aqui que a recusa antiga
    #: continua intacta.
    achado = sessao.scalar(select(Usuario).where(Usuario.email == email))
    if achado is not None:
        raise NaoAutorizado(
            "Este e-mail já está provisionado com outro identificador do "
            "provedor. Fale com quem administra acessos.",
            sobre_o_pedido=True,
        )
    return None


def _passou_da_folga(ultimo: datetime | None, agora: datetime) -> bool:
    if ultimo is None:
        return True
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=UTC)
    return agora - ultimo > FOLGA_DE_REGISTRO_DE_ACESSO
