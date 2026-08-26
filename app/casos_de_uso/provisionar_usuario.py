"""Provisionamento JIT: o usuário nasce no primeiro login.

O mesmo caminho serve para o SSO real e para o provedor mock de desenvolvimento
— muda apenas de onde vêm as claims. Nunca há cadastro manual de senha.

O provisionamento cria a IDENTIDADE e não decide AUTORIZAÇÃO. `papel_id` e
`usuario_escopo` são concedidos por alguém com `administra_acessos`, pela tela
de administração de acessos; o login apenas os lê.

Quem chega pela primeira vez nasce sem papel nenhum — autenticado e autorizado a
nada. É o comportamento correto para convidado B2B: adivinhar permissão para
quem acabou de chegar de fora é o erro que se quer evitar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
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
        # O e-mail também é único, e a busca acima foi por `entra_object_id`.
        # Se já existe alguém com este e-mail e OUTRO identificador, o `flush`
        # abaixo levantaria `UniqueViolation` — e o usuário veria um 500 opaco,
        # sem pista do que houve.
        #
        # NÃO reatribuímos o `entra_object_id` da linha existente: o `oid` é a
        # identidade estável, e trocá-lo em silêncio entregaria a conta de uma
        # pessoa a outra que apenas tenha o mesmo e-mail. Preferimos recusar e
        # dizer o motivo — a resolução é humana.
        #
        # Acontece de verdade em desenvolvimento: alternar entre `AUTH_MOCK` e
        # o SSO real cria dois `oid` para o mesmo e-mail.
        conflito = sessao.scalar(select(Usuario).where(Usuario.email == email))
        if conflito is not None:
            raise NaoAutorizado(
                "Este e-mail já está provisionado com outro identificador do "
                "provedor. Fale com quem administra acessos.",
                sobre_o_pedido=True,
            )

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
        if _passou_da_folga(registro.ultimo_acesso_em, agora):
            registro.ultimo_acesso_em = agora

    return _montar(sessao, registro)


def carregar(sessao: Session, usuario_id) -> UsuarioAtual | None:
    """Reconstrói o usuário a partir do id guardado na sessão.

    Papel e escopo são lidos do banco A CADA requisição, e não guardados no
    cookie. É o que faz uma revogação valer no próximo clique em vez de na
    próxima hora — e o que impede que uma sessão emitida ontem carregue as
    permissões de ontem.
    """
    registro = sessao.get(Usuario, usuario_id)
    if registro is None or not registro.ativo:
        return None

    agora = datetime.now(UTC)
    if _passou_da_folga(registro.ultimo_acesso_em, agora):
        registro.ultimo_acesso_em = agora

    return _montar(sessao, registro)


def _montar(sessao: Session, registro: Usuario) -> UsuarioAtual:
    return UsuarioAtual(
        id=registro.id,
        nome=registro.nome,
        email=registro.email,
        papel=_papel_de(sessao, registro.papel_id),
        escopo=_escopo_de(sessao, registro),
        externo=registro.externo,
        acesso_expira_em=registro.acesso_expira_em,
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


def _passou_da_folga(ultimo: datetime | None, agora: datetime) -> bool:
    if ultimo is None:
        return True
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=UTC)
    return agora - ultimo > FOLGA_DE_REGISTRO_DE_ACESSO
