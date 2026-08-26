"""Entrada e saída do sistema: o fluxo OIDC e a sessão.

Quatro rotas, e três delas são públicas por necessidade — quem ainda não entrou
não tem sessão para provar nada:

    GET  /api/auth/login      começa o fluxo, redireciona ao Entra ID
    GET  /api/auth/callback   recebe o `code`, valida, cria a sessão
    POST /api/auth/logout     apaga a sessão
    GET  /api/eu              quem sou eu, o que posso, e o token anti-CSRF

`/api/eu` é a única protegida — e é a peça que fecha o CSRF: o token vive no
cookie `httpOnly`, que nenhum script lê, e chega ao front pelo CORPO desta
resposta. Um site de outra origem consegue disparar a requisição, mas não
consegue LER a resposta: o CORS impede. Sem ler, não há token; sem token, o
`POST` forjado é recusado.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, text

from app.api.dependencias import UsuarioLogado
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import (
    administrar_acessos,
    autenticar_por_senha,
    registrar_acesso,
)
from app.casos_de_uso.provisionar_usuario import carregar, provisionar
from app.configuracao import Configuracao, obter_configuracao
from app.dominio.erros import NaoAutorizado
from app.dominio.identidade import UsuarioAtual
from app.observabilidade import obter_logger
from app.seguranca import sessao_assinada
from app.seguranca.limite_de_taxa import (
    ExcessoDeRequisicoes,
    RegistroDeBaldes,
    ip_do_cliente,
)
from app.seguranca.oidc import (
    ClienteEntraId,
    FalhaNoLogin,
    novo_desafio,
)

logger = obter_logger("acesso")

rotas = APIRouter(prefix="/api", tags=["acesso"])

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido
Config = Annotated[Configuracao, Depends(obter_configuracao)]

#: Cookie de curta duração que atravessa o redirecionamento ao Entra ID.
#:
#: Guarda `state`, `nonce`, o verificador PKCE e para onde voltar. Vai no
#: navegador, e não em memória do servidor, porque memória de servidor não
#: sobrevive a duas instâncias atrás de um balanceador — o usuário começaria o
#: login numa e voltaria na outra.
COOKIE_DO_PEDIDO = "painel_pedido"
VALIDADE_DO_PEDIDO = 600  # dez minutos: tempo de digitar senha e fazer MFA

#: Um cliente por combinação de credenciais, e não um global só.
#:
#: Com um global, o primeiro tenant visto grudaria para sempre: rotacionar o
#: segredo sem reiniciar o processo continuaria usando o antigo, e o login
#: falharia sem que a configuração mostrasse nada de errado.
_clientes: dict[tuple[str, str, str, str], ClienteEntraId] = {}


def cliente_entra(configuracao: Configuracao) -> ClienteEntraId:
    """Uma instância por credencial, para reaproveitar o cache de chaves."""
    if not (
        configuracao.entra_tenant_id
        and configuracao.entra_client_id
        and configuracao.entra_client_secret
    ):
        raise NaoAutorizado("SSO do Entra ID não configurado.")

    chave = (
        configuracao.entra_tenant_id,
        configuracao.entra_client_id,
        configuracao.entra_client_secret,
        configuracao.entra_autoridade,
    )
    if chave not in _clientes:
        _clientes[chave] = ClienteEntraId(
            tenant_id=chave[0],
            client_id=chave[1],
            client_secret=chave[2],
            autoridade=chave[3],
        )
    return _clientes[chave]


def destino_seguro(pedido: str | None, configuracao: Configuracao) -> str:
    """Para onde mandar o navegador depois do login.

    Recusa qualquer coisa que não seja um caminho relativo desta aplicação.
    Sem isto, `/api/auth/login?redirect=https://sitedoatacante` transformaria o
    domínio do painel em trampolim: o link parece da Aegea, a pessoa faz o
    login de verdade, e é despejada em outro lugar — e o atacante ainda ganha o
    referrer.
    """
    if not pedido:
        return configuracao.url_do_front

    partes = urlsplit(pedido)
    #: `//outro.site` é caminho relativo de protocolo: o navegador o trata como
    #: absoluto, e checar só `startswith("/")` deixaria passar.
    if partes.scheme or partes.netloc or pedido.startswith("//"):
        logger.warning("Redirecionamento externo recusado", extra={"destino": pedido})
        return configuracao.url_do_front

    return configuracao.url_do_front.rstrip("/") + "/" + pedido.lstrip("/")


# -- entrada -------------------------------------------------------------------


@rotas.get("/auth/login")
def login(
    requisicao: Request,
    configuracao: Config,
    redirect: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Começa o fluxo. Redireciona para a tela da Microsoft."""
    if not configuracao.sso_ligado:
        # 503, e não 404: a rota EXISTE e vai voltar. 404 diria "isto nunca
        # existiu", e quem estivesse depurando procuraria o erro no lugar
        # errado. `Retry-After` fica de fora porque não há data prometida.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O acesso pelo SSO da Microsoft ainda não está liberado.",
        )

    desafio = novo_desafio()
    estado = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    destino = cliente_entra(configuracao).url_de_autorizacao(
        redirect_uri=configuracao.entra_redirect_uri,
        estado=estado,
        desafio=desafio.desafio,
        nonce=nonce,
    )

    resposta = RedirectResponse(destino, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _gravar_cookie(
        resposta,
        configuracao,
        nome=COOKIE_DO_PEDIDO,
        valor=sessao_assinada.assinar(
            sessao_assinada.Sessao(
                # O pedido não tem usuário ainda; o campo carrega o `state`.
                usuario_id=_uuid_falso(),
                expira_em=_agora() + VALIDADE_DO_PEDIDO,
                # `redirect` é o ÚLTIMO campo e vem da query string do usuário.
                # `split("|", 3)` na leitura para de dividir depois do terceiro
                # separador, então um `|` no redirect fica dentro dele em vez de
                # embaralhar os anteriores. Os três primeiros são `token_urlsafe`,
                # que nunca contém `|`.
                csrf=f"{estado}|{nonce}|{desafio.verificador}|{redirect or ''}",
                tipo=sessao_assinada.TIPO_PEDIDO,
            ),
            configuracao.sessao_secreta,
        ),
        duracao=VALIDADE_DO_PEDIDO,
        # `Lax` e não `Strict`: o retorno do Entra ID é uma navegação de topo
        # vinda de outro site, e `Strict` faria o navegador NÃO mandar o cookie
        # justamente na volta — o login falharia sempre.
        samesite="lax",
    )
    return resposta


@rotas.get("/auth/callback")
def callback(
    requisicao: Request,
    sessao: Sessao,
    configuracao: Config,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    """Recebe o `code`, valida tudo e cria a sessão."""
    if not configuracao.sso_ligado:
        # Mesmo motivo do `/auth/login`: com o SSO desligado ninguém deveria
        # chegar aqui, e quem chegar recebe a mesma resposta em vez de um 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O acesso pelo SSO da Microsoft ainda não está liberado.",
        )

    ip = ip_do_cliente(requisicao, proxies_confiaveis=configuracao.proxies_confiaveis)

    try:
        pedido = sessao_assinada.ler(
            requisicao.cookies.get(COOKIE_DO_PEDIDO),
            configuracao.sessao_secreta,
            tipo=sessao_assinada.TIPO_PEDIDO,
        )
    except sessao_assinada.SessaoInvalida as erro:
        # Este caminho não registrava. Cookie de pedido ausente, vencido,
        # adulterado ou de outro tipo é justamente o que uma rajada de callbacks
        # forjados produz — e é o sinal que a trilha existe para mostrar.
        registrar_acesso.registrar_e_confirmar(
            sessao, resultado=registrar_acesso.NEGADO_NO_PROVEDOR, ip=ip
        )
        raise NaoAutorizado("Pedido de login expirado. Tente entrar de novo.") from erro

    estado, nonce, verificador, redirect = pedido.csrf.split("|", 3)

    if error:
        registrar_acesso.registrar_e_confirmar(
            sessao, resultado=registrar_acesso.NEGADO_NO_PROVEDOR, ip=ip
        )
        raise NaoAutorizado("O Entra ID recusou o login.")

    if not code or not state or not secrets.compare_digest(state, estado):
        # `state` divergente é a assinatura de um CSRF no próprio login: alguém
        # tentando fazer a vítima entrar na conta do atacante.
        registrar_acesso.registrar_e_confirmar(
            sessao, resultado=registrar_acesso.NEGADO_NO_PROVEDOR, ip=ip
        )
        raise NaoAutorizado("Pedido de login inválido.")

    cliente = cliente_entra(configuracao)
    try:
        id_token = cliente.trocar_codigo(
            codigo=code,
            redirect_uri=configuracao.entra_redirect_uri,
            verificador=verificador,
        )
        identidade = cliente.validar(id_token, nonce=nonce)
    except FalhaNoLogin as erro:
        # O motivo vai para o log, não para a tela: ele descreve o que falhou na
        # validação, e isso ajuda quem está tentando forjar um token.
        logger.warning("Login recusado: %s", erro, extra={"ip": ip})
        registrar_acesso.registrar_e_confirmar(
            sessao, resultado=registrar_acesso.NEGADO_NO_PROVEDOR, ip=ip
        )
        raise NaoAutorizado("Não foi possível concluir o login.") from erro

    usuario = provisionar(
        sessao,
        entra_object_id=identidade.entra_object_id,
        email=identidade.email,
        nome=identidade.nome,
    )

    # Confirma o provisionamento ANTES de decidir. A pessoa existe no diretório
    # e acabou de ser criada aqui; se a recusa desfizesse isso, quem administra
    # acessos não teria a quem conceder — teria de esperar a pessoa tentar de
    # novo, e a tentativa seria negada de novo.
    sessao.commit()

    negativa = _motivo_da_recusa(usuario)
    if negativa:
        registrar_acesso.registrar_e_confirmar(
            sessao,
            resultado=negativa,
            usuario_id=usuario.id,
            email_tentado=identidade.email,
            ip=ip,
        )
        # A pessoa é quem diz ser; só não tem acesso liberado. A mensagem pode
        # ser específica: não revela nada que ela já não saiba sobre si.
        raise NaoAutorizado(_texto_da_recusa(usuario))

    registrar_acesso.registrar(
        sessao,
        resultado=registrar_acesso.CONCEDIDO,
        usuario_id=usuario.id,
        email_tentado=identidade.email,
        ip=ip,
    )

    resposta = RedirectResponse(
        destino_seguro(redirect or None, configuracao),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _gravar_cookie(
        resposta,
        configuracao,
        nome=sessao_assinada.NOME_DO_COOKIE,
        valor=sessao_assinada.assinar(
            sessao_assinada.nova_sessao(usuario.id), configuracao.sessao_secreta
        ),
        duracao=sessao_assinada.DURACAO_PADRAO,
    )
    resposta.delete_cookie(COOKIE_DO_PEDIDO, path="/")
    return resposta


class EntradaPorSenha(BaseModel):
    """O que a tela de login manda."""

    email: str
    senha: str


#: Tentativas por CONTA, e não por IP.
#:
#: O middleware por IP já cobre esta rota, e não basta: quem tem uma botnet
#: tenta a mesma conta de mil endereços, e cada um deles fica muito abaixo do
#: teto. O teto por e-mail é o que transforma "mil IPs, mil tentativas" em "mil
#: IPs, dez tentativas".
#:
#: 10 fichas e uma nova a cada 30s: erro de digitação não incomoda ninguém, e
#: quem varre dicionário para na décima.
#:
#: A memória é DA INSTÂNCIA, como a do limitador de taxa: com N instâncias o
#: teto efetivo é N vezes maior. É o mesmo compromisso documentado em
#: `app/seguranca/limite_de_taxa.py`, e a saída é a mesma — um contador
#: compartilhado, no dia em que a escala pedir.
_TENTATIVAS_POR_CONTA = RegistroDeBaldes(capacidade=10, por_segundo=1 / 30)


@rotas.post("/auth/senha", status_code=status.HTTP_204_NO_CONTENT)
def entrar_por_senha(
    requisicao: Request,
    resposta: Response,
    sessao: Sessao,
    configuracao: Config,
    corpo: EntradaPorSenha,
) -> Response:
    """Entrada por e-mail e senha, para quem não está no Entra ID.

    Emite EXATAMENTE a mesma sessão que o retorno do SSO: mesmo cookie, mesma
    assinatura, mesma duração. Daqui para a frente o resto da aplicação não
    sabe — nem precisa saber — por qual porta a pessoa entrou. Fosse um segundo
    tipo de sessão, cada verificação teria de tratar os dois, e é assim que uma
    delas passa a tratar só um.

    A resposta é 204 e o cookie vai no cabeçalho. Nada do usuário volta no
    corpo: quem precisa disso chama `/api/eu` em seguida, que é a rota que já
    existe para essa pergunta.
    """
    ip = ip_do_cliente(requisicao, proxies_confiaveis=configuracao.proxies_confiaveis)
    # Normalizado antes de virar chave do balde: `Fulano@Aegea.com.br` e
    # `fulano@aegea.com.br` são a mesma conta (a coluna é `citext`), e sem
    # normalizar seriam dois baldes — dobrando o teto para quem alterna a caixa.
    email = corpo.email.strip()
    chave = email.casefold()

    espera = _TENTATIVAS_POR_CONTA.consumir(chave)
    if espera is not None:
        # A MESMA mensagem das outras recusas seria melhor para não revelar que
        # a conta existe — mas 429 já revela por si, e esconder o motivo faria a
        # pessoa legítima tentar de novo achando que errou a senha. O que se
        # protege aqui é a conta, e quem está do outro lado já sabe que a
        # atacou.
        raise ExcessoDeRequisicoes(espera)

    autenticado = autenticar_por_senha.autenticar(sessao, email=email, senha=corpo.senha)

    if autenticado is None:
        # `NEGADO_NO_PROVEDOR` porque foi a credencial que não conferiu, e não o
        # papel: a pessoa não chegou a ser identificada. É o mesmo resultado que
        # o SSO registra quando o token não vale.
        # `registrar_e_confirmar`, e NÃO `registrar`: quem chama levanta em
        # seguida, e `obter_sessao` desfaz a transação em qualquer exceção. Com
        # `registrar`, a linha era gravada e descartada milissegundos depois —
        # toda recusa de login sumia da trilha, que é justamente a linha que
        # mais importa numa investigação.
        registrar_acesso.registrar_e_confirmar(
            sessao,
            resultado=registrar_acesso.NEGADO_NO_PROVEDOR,
            usuario_id=None,
            email_tentado=email,
            ip=ip,
        )
        # UMA mensagem para todos os casos — e-mail inexistente, senha errada,
        # conta desativada. Distinguir entregaria a lista de quem tem acesso ao
        # painel, e o painel guarda com quem a Aegea conversa.
        raise NaoAutorizado("E-mail ou senha não conferem.", sobre_o_pedido=True)

    usuario = carregar(sessao, autenticado.usuario_id)
    if usuario is None:
        # A credencial conferiu mas o usuário sumiu entre uma consulta e outra —
        # desativado no meio do caminho, ou apagado. Trata-se como recusa de
        # credencial: não há a quem dizer nada de específico.
        registrar_acesso.registrar_e_confirmar(
            sessao,
            resultado=registrar_acesso.NEGADO_INATIVO,
            usuario_id=autenticado.usuario_id,
            email_tentado=email,
            ip=ip,
        )
        raise NaoAutorizado("E-mail ou senha não conferem.", sobre_o_pedido=True)

    # `_motivo_da_recusa`, o mesmo que o SSO usa: distingue "sem papel" de
    # "prazo vencido". Fixar `NEGADO_SEM_PAPEL` para os dois faria a trilha
    # dizer que ninguém nunca teve acesso expirado.
    negativa = _motivo_da_recusa(usuario)
    if negativa is not None:
        registrar_acesso.registrar_e_confirmar(
            sessao,
            resultado=negativa,
            usuario_id=usuario.id,
            email_tentado=email,
            ip=ip,
        )
        # Aqui a mensagem PODE ser específica: a credencial já provou quem é a
        # pessoa, então dizer "seu acesso não foi liberado" não conta nada que
        # ela não saiba sobre si mesma — e é acionável.
        raise NaoAutorizado(_texto_da_recusa(usuario), sobre_o_pedido=True)

    # Entrou: o balde da conta volta ao cheio. Sem isto, nove erros de digitação
    # ao longo do dia deixariam a pessoa a uma tentativa do bloqueio mesmo tendo
    # acertado nove vezes no meio.
    _TENTATIVAS_POR_CONTA.esquecer(chave)

    registrar_acesso.registrar(
        sessao,
        resultado=registrar_acesso.CONCEDIDO,
        usuario_id=usuario.id,
        email_tentado=email,
        ip=ip,
    )

    _gravar_cookie(
        resposta,
        configuracao,
        nome=sessao_assinada.NOME_DO_COOKIE,
        valor=sessao_assinada.assinar(
            sessao_assinada.nova_sessao(usuario.id), configuracao.sessao_secreta
        ),
        duracao=sessao_assinada.DURACAO_PADRAO,
    )
    resposta.status_code = status.HTTP_204_NO_CONTENT
    return resposta


@rotas.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(requisicao: Request, configuracao: Config) -> Response:
    """Apaga a sessão.

    Não desloga do Entra ID de propósito: a pessoa costuma usar a mesma conta em
    outros sistemas da casa, e derrubar todos eles ao sair daqui seria uma
    surpresa desagradável.

    Confere o token anti-CSRF quando há sessão, e responde 204 quando não há.
    Sair é idempotente: quem já está fora não precisa de erro para descobrir
    isso. Mas um `logout` forjado por outro site é chateação real — a pessoa é
    derrubada no meio do trabalho sem entender por quê.
    """
    from app.api.dependencias import _exigir_csrf

    try:
        atual = sessao_assinada.ler(
            requisicao.cookies.get(sessao_assinada.NOME_DO_COOKIE),
            configuracao.sessao_secreta,
        )
    except sessao_assinada.SessaoInvalida:
        atual = None

    if atual is not None and not configuracao.auth_mock:
        _exigir_csrf(requisicao, atual)

    resposta = Response(status_code=status.HTTP_204_NO_CONTENT)
    resposta.delete_cookie(
        sessao_assinada.NOME_DO_COOKIE,
        path="/",
        secure=configuracao.producao,
        httponly=True,
        samesite="lax",
    )
    return resposta


# -- quem sou eu ---------------------------------------------------------------


class PapelSaida(BaseModel):
    codigo: str
    nome: str
    pode_criar: bool
    pode_editar_proprio: bool
    pode_editar_tudo: bool
    administra_dicionarios: bool
    administra_acessos: bool
    ve_campos_sensiveis: bool
    ve_diretorio: bool
    pode_exportar: bool

    #: Quais portais este papel abre. A capa usa para decidir o que oferecer.
    #:
    #: Vai no `/api/eu` e não numa rota própria: a tela precisa dos três junto
    #: com o resto do papel, e buscá-los à parte criaria um instante em que a
    #: pessoa está identificada mas a capa ainda não sabe o que mostrar.
    acessa_crm: bool
    acessa_sintese: bool
    acessa_score: bool


class EuSaida(BaseModel):
    id: str
    nome: str
    email: str
    papel: PapelSaida | None
    externo: bool
    acesso_expira_em: str | None
    #: O front guarda e devolve em `X-CSRF-Token` a cada escrita.
    csrf_token: str


@rotas.get("/eu")
def eu(
    requisicao: Request,
    configuracao: Config,
    usuario: UsuarioLogado,
) -> EuSaida:
    """Quem está logado, o que pode, e o token anti-CSRF."""
    try:
        atual = sessao_assinada.ler(
            requisicao.cookies.get(sessao_assinada.NOME_DO_COOKIE),
            configuracao.sessao_secreta,
        )
        token = atual.csrf
    except sessao_assinada.SessaoInvalida:
        # Modo mock: não há cookie, e não há CSRF a proteger porque não há
        # sessão de verdade. String vazia é honesto; um token inventado daria a
        # impressão de proteção que não existe.
        token = ""

    return EuSaida(
        id=str(usuario.id),
        nome=usuario.nome,
        email=usuario.email,
        # `asdict` e não `vars`: `Papel` usa `slots=True`, e objeto com slots
        # não tem `__dict__` — `vars` levantaria `TypeError`.
        papel=PapelSaida(**asdict(usuario.papel)) if usuario.papel else None,
        externo=usuario.externo,
        acesso_expira_em=(
            usuario.acesso_expira_em.isoformat() if usuario.acesso_expira_em else None
        ),
        csrf_token=token,
    )


# -- apoio ---------------------------------------------------------------------


def _motivo_da_recusa(usuario: UsuarioAtual) -> str | None:
    if usuario.sem_autorizacao:
        return registrar_acesso.NEGADO_SEM_PAPEL
    if usuario.acesso_vencido():
        return registrar_acesso.NEGADO_VENCIDO
    return None


def _texto_da_recusa(usuario: UsuarioAtual) -> str:
    if usuario.sem_autorizacao:
        return "Seu acesso ainda não foi liberado. Peça à coordenação do painel."
    return (
        f"Seu acesso expirou em {usuario.acesso_expira_em:%d/%m/%Y}. "
        "Peça a renovação à coordenação do painel."
    )


def _gravar_cookie(
    resposta: Response,
    configuracao: Configuracao,
    *,
    nome: str,
    valor: str,
    duracao: int,
    # `Literal`, e não `str`: o Starlette aceita exatamente estes três valores.
    # Com `str`, um `"Lax"` capitalizado ou um erro de digitação viraria um
    # atributo de cookie inválido — e o navegador simplesmente ignora atributo
    # que não entende, sem erro nenhum. O modo de falha seria uma sessão sem a
    # proteção que se acreditava ter.
    samesite: Literal["lax", "strict", "none"] = "lax",
) -> None:
    resposta.set_cookie(
        nome,
        valor,
        max_age=duracao,
        path="/",
        # `httpOnly` é o que impede um XSS de ler a sessão. Sem ele, todo o
        # resto do plano depende de nunca haver um XSS.
        httponly=True,
        # `Secure` só em produção: em desenvolvimento não há TLS, e o navegador
        # descartaria o cookie silenciosamente — o login pareceria funcionar e
        # nada ficaria logado.
        secure=configuracao.producao,
        samesite=samesite,
    )


def _agora() -> int:
    import time

    return int(time.time())


def _uuid_falso():
    """O cookie de pedido reaproveita a estrutura da sessão e não tem usuário."""
    from uuid import UUID

    return UUID(int=0)


# -- administração de acessos --------------------------------------------------
#
# A escrita não acontece na aplicação: acontece na função `conceder_acesso` do
# banco (migration 0006). `painel_app` não tem `grant` nas colunas de
# autorização — só para executar a função, que valida e deixa rastro.


class AcessoSaida(BaseModel):
    id: str
    nome: str
    email: str
    ativo: bool
    papel: str | None
    acesso_irrestrito: bool
    externo: bool
    expira_em: str | None
    frentes: list[str]
    unidades: list[str]
    concedido_por: str | None
    concedido_em: str | None


class ConcessaoEntrada(BaseModel):
    #: Nulo revoga: a pessoa continua existindo e passa a não alcançar nada.
    #: É o oposto de apagar — o histórico dela permanece atribuído.
    papel: str | None = None
    acesso_irrestrito: bool = False
    externo: bool = False
    expira_em: date | None = None
    frentes: list[str] = []
    unidades: list[str] = []
    #: O `concedido_em` que a tela recebeu ao carregar a lista.
    #:
    #: A tela manda de volta o que viu; se o banco tiver outra versão, a
    #: concessão é recusada em vez de sobrescrever a alteração de outra pessoa.
    #:
    #: Nulo é um valor como outro qualquer aqui — quer dizer "sem concessão" —,
    #: e é conferido do mesmo jeito.
    #:
    #: SEM `= None`, e isso é deliberado: o campo é OBRIGATÓRIO. Nulo continua
    #: sendo um valor válido, mas precisa ser escrito.
    #:
    #: Enquanto havia default, um cliente que simplesmente não conhecesse o
    #: campo — um script, um `curl` de manutenção, uma integração futura —
    #: sobrescrevia concessão alheia sem nunca ter tomado a decisão de
    #: sobrescrever. Exigir o campo transforma "não sei" em erro 422 em vez de
    #: numa afirmação silenciosa sobre o estado do banco.
    versao_vista: datetime | None


class PapelDisponivel(BaseModel):
    codigo: str
    nome: str
    administra_acessos: bool
    ve_campos_sensiveis: bool
    ve_diretorio: bool


@rotas.get("/acessos")
def listar_acessos(sessao: Sessao, usuario: UsuarioLogado) -> list[AcessoSaida]:
    """Quem existe e o que cada um alcança."""
    return [
        AcessoSaida(
            id=str(linha.id),
            nome=linha.nome,
            email=linha.email,
            ativo=linha.ativo,
            papel=linha.papel,
            acesso_irrestrito=linha.acesso_irrestrito,
            externo=linha.externo,
            expira_em=linha.expira_em.isoformat() if linha.expira_em else None,
            frentes=list(linha.frentes),
            unidades=list(linha.unidades),
            concedido_por=linha.concedido_por,
            concedido_em=linha.concedido_em,
        )
        for linha in administrar_acessos.listar(sessao, solicitante=usuario)
    ]


@rotas.get("/acessos/papeis")
def listar_papeis(sessao: Sessao, usuario: UsuarioLogado) -> list[PapelDisponivel]:
    """Os papéis que podem ser concedidos.

    Sai da tabela, e não de uma lista no código: acrescentar um papel passa a
    ser uma linha no banco, e a tela o mostra sem deploy.
    """
    administrar_acessos.exigir_administrador(usuario)
    from app.banco.tabelas_acesso import (
        Papel as PapelRegistro,
    )

    papeis = sessao.scalars(
        select(PapelRegistro).where(PapelRegistro.ativo).order_by(PapelRegistro.id)
    ).all()
    return [
        PapelDisponivel(
            codigo=p.codigo,
            nome=p.nome,
            administra_acessos=p.administra_acessos,
            ve_campos_sensiveis=p.ve_campos_sensiveis,
            ve_diretorio=p.ve_diretorio,
        )
        for p in papeis
    ]


@rotas.put("/acessos/{id}", status_code=status.HTTP_204_NO_CONTENT)
def conceder(
    sessao: Sessao, usuario: UsuarioLogado, id: UUID, entrada: ConcessaoEntrada
) -> Response:
    """Substitui o acesso da pessoa pelo que foi pedido.

    `PUT` e não `PATCH`: a concessão é o estado completo do que alguém alcança.
    Aplicar diferença abriria a porta para "acrescentei uma frente e esqueci que
    ele já tinha acesso irrestrito" — e o erro só apareceria depois.
    """
    administrar_acessos.conceder(
        sessao,
        alvo=id,
        concessao=administrar_acessos.Concessao(
            papel=entrada.papel,
            acesso_irrestrito=entrada.acesso_irrestrito,
            externo=entrada.externo,
            expira_em=entrada.expira_em,
            frentes=tuple(entrada.frentes),
            unidades=tuple(entrada.unidades),
            versao_vista=entrada.versao_vista,
        ),
        solicitante=usuario,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class TrilhaDeAcesso(BaseModel):
    ocorrido_em: str
    campo: str
    valor_anterior: str | None
    valor_novo: str | None
    concedido_por: str | None
    origem: str | None


@rotas.get("/acessos/{id}/historico")
def historico(sessao: Sessao, usuario: UsuarioLogado, id: UUID) -> list[TrilhaDeAcesso]:
    """O que já foi concedido a esta pessoa, e por quem.

    Existe para responder a pergunta que motivou a tabela: depois de um
    incidente, quem liberou este acesso? `origem` nula é impossível — o gatilho
    sempre grava `session_user`; `concedido_por` nulo significa alteração fora
    da aplicação.
    """
    administrar_acessos.exigir_administrador(usuario)

    linhas = sessao.execute(
        text(
            "select a.ocorrido_em, a.campo, a.valor_anterior, a.valor_novo, "
            "       a.origem, u.nome as autor "
            "  from usuario_auditoria a "
            "  left join usuario u on u.id = a.concedido_por "
            " where a.usuario_id = :id "
            " order by a.ocorrido_em desc limit 200"
        ),
        {"id": id},
    ).all()

    return [
        TrilhaDeAcesso(
            ocorrido_em=linha.ocorrido_em.isoformat(),
            campo=linha.campo,
            valor_anterior=linha.valor_anterior,
            valor_novo=linha.valor_novo,
            concedido_por=linha.autor,
            origem=linha.origem,
        )
        for linha in linhas
    ]
