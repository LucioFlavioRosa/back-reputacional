"""Quem está pedindo — a dependência que todo endpoint protegido usa.

`auth_mock` devolve um usuário fixo pelo mesmo caminho de provisionamento do
SSO real, para desenvolver sem depender do tenant. Trocar de um para o outro
substitui a origem das claims, não a forma da dependência — e a conferência de
subida (`app/seguranca/verificacao_de_producao.py`) recusa iniciar em produção com
ele ligado.

Autenticar e autorizar são passos distintos aqui. O Entra ID responde o
primeiro; `papel`, `usuario_escopo` e o prazo respondem o segundo. Um convidado
B2B válido pode passar pela autenticação e ainda assim não entrar.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.banco.autoria import (
    marcar_autor_na_sessao,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso.provisionar_usuario import (
    carregar,
    provisionar,
)
from app.configuracao import Configuracao, obter_configuracao
from app.dominio.erros import NaoAutorizado
from app.dominio.identidade import Perfil, UsuarioAtual
from app.seguranca import sessao_assinada
from app.seguranca.cache_de_autorizacao import CacheDeAutorizacao, cache_para
from app.seguranca.limite_de_taxa import (
    ExcessoDeRequisicoes,
    RegistroDeBaldes,
    custo_da_requisicao,
)

#: `oid` sintético do usuário de desenvolvimento. Estável, para que o mesmo
#: registro seja reaproveitado entre execuções.
OID_MOCK = "mock-desenvolvimento"


#: Métodos que não alteram estado. Só os outros exigem token anti-CSRF.
#:
#: `HEAD` e `OPTIONS` entram na lista porque o navegador os dispara sozinho — o
#: preflight do CORS é um `OPTIONS`, e exigir cabeçalho nele impediria qualquer
#: requisição cross-origin de sair do lugar.
METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

CABECALHO_CSRF = "X-CSRF-Token"


def _exigir_csrf(requisicao: Request, sessao_atual: sessao_assinada.Sessao) -> None:
    """Dupla submissão: o token está no cookie E precisa vir no cabeçalho.

    O cookie é `httpOnly`, então nenhum script o lê. O front obtém o token pelo
    CORPO de `/api/eu` — e é justamente isso que um site de outra origem não
    consegue: disparar a requisição ele consegue, LER a resposta não, porque o
    CORS impede.

    Isso importa mais do que parece aqui. `SameSite=Lax` não protege contra
    outro subdomínio de `aegea.com.br`, que para o navegador é o MESMO site — e
    a Aegea tem muitos.
    """
    if requisicao.method in METODOS_SEGUROS:
        return

    enviado = requisicao.headers.get(CABECALHO_CSRF, "")
    if not enviado or not secrets.compare_digest(enviado, sessao_atual.csrf):
        raise NaoAutorizado(
            "Token de verificação ausente ou inválido. Recarregue a página.",
            # Acionável e sem revelar nada: descreve o estado do pedido, não a
            # regra de permissão.
            sobre_o_pedido=True,
        )


def _usuario_provisionado(
    requisicao: Request,
    # `SessaoDoPedido`, e não `Depends(obter_sessao)` cru: o alias carrega o
    # `scope="function"`, sem o qual um commit que falha só apareceria depois de
    # a resposta já ter saído. Ver `app/banco/sessao.py`.
    sessao: SessaoDoPedido,
    configuracao: Annotated[Configuracao, Depends(obter_configuracao)],
) -> UsuarioAtual:
    """Só identidade. A autorização vem depois, e o limite antes dela."""
    if not configuracao.auth_mock:
        return _da_sessao(requisicao, sessao, configuracao)

    usuario = provisionar(
        sessao,
        entra_object_id=OID_MOCK,
        email=configuracao.auth_mock_email,
        nome=configuracao.auth_mock_nome,
        papel_inicial=Perfil(configuracao.auth_mock_perfil),
    )

    # Carimba o autor na transação para os gatilhos de auditoria (migration 0005).
    # Fica aqui, e não nos casos de uso de escrita, porque aqui é onde a
    # identidade nasce — e um caso de uso novo que esquecesse de chamar
    # gravaria a alteração como se tivesse vindo de SQL direto.
    marcar_autor_na_sessao(sessao, usuario.id)
    return usuario


def _da_sessao(
    requisicao: Request, sessao: Session, configuracao: Configuracao
) -> UsuarioAtual:
    """O caminho de produção: cookie assinado, usuário do cache ou do banco.

    O cookie carrega apenas o id e o prazo — nunca papel nem escopo, que são do
    banco. O que muda com o cache é a FREQUÊNCIA da leitura, não a fonte: a
    autorização vale por `autorizacao_cache_segundos` antes de ser relida.

    A verificação da sessão continua a cada requisição. É só o que o banco diria
    sobre um usuário já identificado que se guarda, nunca a identidade.
    """
    try:
        atual = sessao_assinada.ler(
            requisicao.cookies.get(sessao_assinada.NOME_DO_COOKIE),
            configuracao.sessao_secreta,
        )
    except sessao_assinada.SessaoInvalida as erro:
        # Uma mensagem só para os três casos — ausente, adulterado, vencido.
        # A diferença entre eles só interessa a quem está tentando forjar.
        raise NaoAutorizado(
            "Sessão ausente ou expirada. Entre novamente.", sobre_o_pedido=True
        ) from erro

    _exigir_csrf(requisicao, atual)

    cache = cache_de_autorizacao(configuracao)
    usuario = cache.obter(atual.usuario_id)

    if usuario is None:
        # O marcador vem ANTES da leitura: se alguém revogar enquanto ela
        # acontece, `guardar` recusa o valor velho. Ver o docstring de
        # `CacheDeAutorizacao.guardar`.
        marcador = cache.marcador()
        usuario = carregar(sessao, atual.usuario_id)
        if usuario is None:
            # Sessão válida de alguém que não existe mais, ou foi desativado. O
            # cookie continua assinado corretamente; o que mudou foi o banco.
            #
            # A ausência NÃO é guardada no cache, de propósito: guardá-la faria
            # uma reativação demorar a valer, e o caso é raro demais para que
            # economizar a consulta dele valha esse preço.
            raise NaoAutorizado(
                "Sessão ausente ou expirada. Entre novamente.", sobre_o_pedido=True
            )
        cache.guardar(usuario, marcador)

    # Fora do `if`: vale para o caminho do cache também. É um `SET LOCAL` na
    # transação em curso, que os gatilhos de auditoria leem (migration 0005), e
    # o cache não o dispensa — o que ele evita é RECONSTRUIR o usuário, não
    # carimbar a transação.
    marcar_autor_na_sessao(sessao, usuario.id)
    return usuario


def obter_usuario_atual(
    requisicao: Request,
    usuario: Annotated[UsuarioAtual, Depends(_usuario_provisionado)],
    configuracao: Annotated[Configuracao, Depends(obter_configuracao)],
) -> UsuarioAtual:
    """Identidade, depois LIMITE, depois autorização. A ordem importa.

    O limite vem antes da autorização de propósito. Na ordem inversa, um
    convidado B2B autenticado e ainda sem papel podia repetir a requisição
    indefinidamente: cada uma levava um 403 — e uma ida ao banco — sem nunca
    gastar ficha. Quem ainda não foi liberado é justamente quem tem menos razão
    para receber tratamento ilimitado.
    """
    _consumir_limite(requisicao, usuario, configuracao)
    autorizado = _exigir_autorizacao_valida(usuario)

    # O tratador de erros precisa saber se quem pediu é de fora, para decidir o
    # que a mensagem pode contar. Ele não tem dependências — só a requisição.
    requisicao.state.usuario = autorizado
    return autorizado


def _exigir_autorizacao_valida(usuario: UsuarioAtual) -> UsuarioAtual:
    """Autenticado não é o mesmo que autorizado.

    As duas recusas são deliberadamente específicas: quem chega aqui já provou
    identidade no diretório, então a mensagem não revela nada que a pessoa já
    não saiba sobre si mesma — e "peça acesso à coordenação" é melhor do que
    uma tela vazia sem explicação.
    """
    if usuario.sem_autorizacao:
        raise NaoAutorizado(
            "Seu acesso ainda não foi liberado. Peça à coordenação do painel.",
            # O convidado B2B precisa saber o que fazer. A frase fala do estado
            # dele, que ele já conhece — não de como o sistema decide.
            sobre_o_pedido=True,
        )

    if usuario.acesso_vencido():
        raise NaoAutorizado(
            f"Seu acesso expirou em {usuario.acesso_expira_em:%d/%m/%Y}. "
            "Peça a renovação à coordenação do painel.",
            sobre_o_pedido=True,
        )

    return usuario


UsuarioLogado = Annotated[UsuarioAtual, Depends(obter_usuario_atual)]


#: Os baldes por pessoa, um registro por combinação de teto.
#:
#: Vivem no módulo, e não na aplicação, porque precisam sobreviver entre
#: requisições — e não no banco, porque uma escrita por requisição para contar
#: requisições seria o próprio problema que se quer evitar.
#:
#: A chave é o par de números, e não um único registro global: com um só, o
#: primeiro teto visto grudava para sempre. Recriar a aplicação no mesmo
#: processo — que é o que os testes fazem — continuaria usando o teto antigo, e
#: o teste validaria um limite diferente do que roda.
_registros: dict[tuple[float, float], RegistroDeBaldes] = {}

def cache_de_autorizacao(configuracao: Configuracao) -> CacheDeAutorizacao:
    """O cache em vigor. O registro mora em `app/seguranca/`, e não aqui, para
    que `administrar_acessos` possa invalidar sem importar de `app/api/`."""
    return cache_para(configuracao.autorizacao_cache_segundos)


def _registro_por_usuario(configuracao: Configuracao) -> RegistroDeBaldes:
    chave = (
        configuracao.limite_por_usuario_capacidade,
        configuracao.limite_por_usuario_por_segundo,
    )
    if chave not in _registros:
        _registros[chave] = RegistroDeBaldes(capacidade=chave[0], por_segundo=chave[1])
    return _registros[chave]


def _consumir_limite(
    requisicao: Request, usuario: UsuarioAtual, configuracao: Configuracao
) -> None:
    """A camada fina do limite: por pessoa, não por endereço.

    Não é middleware porque middleware executa ANTES das dependências e não
    teria como saber quem está pedindo. E é por pessoa que o limite faz sentido:
    o balde por IP não distingue duas pessoas atrás do mesmo NAT corporativo.

    O PREÇO dessa posição: quando isto roda, a identidade já foi resolvida — o
    que custou uma consulta ao banco. Uma enxurrada autenticada paga essa
    consulta por requisição antes de ser barrada. Quem protege o que vem antes
    da identidade é a camada por IP, no middleware; é por isso que as duas
    existem.
    """
    if not configuracao.limite_de_taxa_ligado:
        return

    espera = _registro_por_usuario(configuracao).consumir(
        str(usuario.id), custo_da_requisicao(requisicao)
    )
    if espera is not None:
        raise ExcessoDeRequisicoes(espera)


def exigir_escrita(usuario: UsuarioLogado) -> UsuarioAtual:
    """Barra quem só lê antes de tocar no banco."""
    if usuario.somente_leitura:
        raise NaoAutorizado(f"Perfil {_nome_do_papel(usuario)} tem acesso somente de leitura.")
    return usuario


def exigir_diretorio(usuario: UsuarioLogado) -> UsuarioAtual:
    """Os diretórios expõem o mapa de relacionamento inteiro da Aegea.

    Instituições e interlocutores são todo jornalista, gestor público e
    entidade com quem a companhia fala. Para um terceiro, isso pode valer mais
    do que os registros em si.
    """
    if usuario.papel is None or not usuario.papel.ve_diretorio:
        raise NaoAutorizado("Seu perfil não tem acesso aos cadastros de stakeholders.")
    return usuario


# NÃO existe `exigir_exportacao` aqui, e a ausência é deliberada.
#
# `papel.pode_exportar` está no banco, mas não há rota para protegê-lo: o CSV é
# montado no navegador, a partir dos registros que a listagem já entregou.
# Escrever a dependência sem rota criaria um controle que parece existir e não
# roda — pior do que controle nenhum, porque quem lesse o código concluiria que
# a exportação está barrada.
#
# Enquanto o export for do lado do cliente, quem limita o dano é o escopo (o
# usuário só baixa o que alcança) e a ocultação de `relato`/`pendencias`.
# Restringir a exportação de verdade exige movê-la para o backend.


def _nome_do_papel(usuario: UsuarioAtual) -> str:
    return usuario.papel.nome if usuario.papel else "sem papel"


UsuarioQueEscreve = Annotated[UsuarioAtual, Depends(exigir_escrita)]
UsuarioQueVeDiretorio = Annotated[UsuarioAtual, Depends(exigir_diretorio)]
