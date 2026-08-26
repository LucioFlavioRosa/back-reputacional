"""Trilha de login: quem entrou, quando, de onde, e quem tentou e não entrou.

Toda tentativa vira uma linha em `acesso_log` (migration 0003), com ou sem
sucesso. É a resposta para "quem entrou no sistema?" — a pergunta que aparece
depois de um incidente, quando já não dá para reconstruir.

A MESMA informação também vai para a telemetria, e a duplicação é deliberada:
alerta não se escreve em SQL. `acesso_log` responde com precisão a quem for
procurar; o Application Insights é onde a regra "cinco negativas da mesma conta
em dez minutos" roda sozinha e avisa alguém.

A tentativa NEGADA é a linha mais valiosa das duas. Login bem-sucedido é
rotina; sequência de negados é sinal — conta desativada tentando de novo,
convidado sem papel insistindo, ou alguém testando e-mails.
"""

from __future__ import annotations

import ipaddress
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.banco.tabelas_acesso import AcessoLog
from app.observabilidade import obter_logger

logger = obter_logger("acesso")

#: Vocabulário fechado do campo `resultado`, espelhando o `check` da migration
#: 0003. Texto livre aqui viraria seis grafias da mesma coisa e nenhuma consulta
#: confiável — e o banco recusa qualquer valor fora desta lista.
#:
#: A distinção entre as negativas não é preciosismo: depois de um incidente,
#: "houve 40 logins negados" não diz nada. `negado_sem_papel` em rajada é
#: convidado insistindo, ou alguém cujo acesso foi revogado e que ainda não
#: sabe; `negado_no_provedor` é o único que pode indicar credencial forjada.
CONCEDIDO = "sucesso"
NEGADO_SEM_PAPEL = "negado_sem_papel"
NEGADO_VENCIDO = "negado_vencido"
NEGADO_NO_PROVEDOR = "negado_no_provedor"
NEGADO_INATIVO = "negado_inativo"


def registrar_e_confirmar(
    sessao: Session,
    *,
    resultado: str,
    usuario_id: UUID | None = None,
    email_tentado: str | None = None,
    ip: str | None = None,
) -> None:
    """Grava a linha E CONFIRMA, porque quem chama vai levantar em seguida.

    Sem o commit explícito, toda recusa de login some. `obter_sessao` desfaz a
    transação em qualquer exceção — inclusive nos erros de domínio, que é
    exatamente o que a rota levanta ao negar. A linha era gravada e descartada
    milissegundos depois.

    E a recusa é a linha que mais importa: login bem-sucedido é rotina;
    sequência de negados é sinal.
    """
    # Sessão PRÓPRIA, e não a da requisição.
    #
    # Confirmar a sessão do caso de uso levaria junto qualquer mutação pendente
    # que estivesse ali — a auditoria passaria a decidir o destino de dados que
    # não são dela. Uma transação separada grava só isto, e grava mesmo que a
    # transação principal seja desfeita logo em seguida (que é o caso: quem
    # chama vai levantar).
    # O bind vem de QUEM CHAMA, e não da configuração global. São o mesmo banco,
    # mas por caminhos diferentes: derivar daqui mantém a auditoria na base em
    # que a requisição está trabalhando — inclusive nos testes, que usam uma
    # base descartável própria. Ler a configuração faria a linha ir parar no
    # banco de desenvolvimento durante o teste, e ninguém notaria.
    from sqlalchemy.orm import Session as SessaoNova

    with SessaoNova(bind=sessao.get_bind().engine) as propria:
        registrar(
            propria,
            resultado=resultado,
            usuario_id=usuario_id,
            email_tentado=email_tentado,
            ip=ip,
        )
        propria.commit()


def registrar(
    sessao: Session,
    *,
    resultado: str,
    usuario_id: UUID | None = None,
    email_tentado: str | None = None,
    ip: str | None = None,
) -> None:
    """Grava uma linha de acesso.

    `usuario_id` fica nulo quando a falha aconteceu antes de saber quem é —
    token inválido, por exemplo. Nesse caso `email_tentado` é tudo o que há, e
    às vezes nem isso.
    """
    sessao.add(
        AcessoLog(
            usuario_id=usuario_id,
            email_tentado=email_tentado,
            ip=_endereco_valido(ip),
            resultado=resultado,
        )
    )

    # A MESMA informação também vai para a telemetria, e a duplicação é
    # deliberada.
    #
    # `acesso_log` é a trilha oficial: fica no banco, junto do resto, e responde
    # "quem entrou?" com precisão. Mas alerta não se escreve em SQL — o
    # Application Insights é onde a regra "cinco negativas da mesma conta em dez
    # minutos" roda sozinha e avisa alguém. Uma consulta no banco só encontra
    # quem for procurar.
    negado = resultado != CONCEDIDO
    logger.log(
        # Negativa é `warning` para separá-la do ruído de login bem-sucedido,
        # que é rotina e enche o log.
        logging.WARNING if negado else logging.INFO,
        "Login %s para %s",
        resultado,
        email_tentado or usuario_id or "desconhecido",
        extra={
            "evento": "login",
            "resultado": resultado,
            "negado": negado,
            "usuario_id": str(usuario_id) if usuario_id else "",
            "email_tentado": email_tentado or "",
            "ip": _endereco_valido(ip) or "",
        },
    )


def _endereco_valido(ip: str | None) -> str | None:
    """A coluna é `inet`: texto que não seja endereço faz o insert explodir.

    E `ip_do_cliente` devolve `"desconhecido"` quando a conexão não expõe o
    cliente — situação real atrás de certos proxies. Como esta gravação virou
    transação própria e acontece no caminho de RECUSA, o erro transformaria uma
    negativa de login num 500: a pessoa veria "erro interno" em vez de "seu
    acesso não foi liberado", e a trilha continuaria sem a linha.

    Endereço ilegível vira nulo. Perder o endereço é ruim; perder o registro
    inteiro é pior.
    """
    if not ip:
        return None
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None
    return ip
