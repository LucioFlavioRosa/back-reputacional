"""Entrada por e-mail e senha, ao lado do SSO.

POR QUE EXISTE, já que há Entra ID

Nem todo mundo que precisa do painel está no diretório da Aegea. Convidado de
agência, consultor com contrato curto, alguém de uma investida que ainda não foi
integrada — para essas pessoas, provisionar no Entra ID é um processo que não
acompanha o prazo do trabalho.

O HASH É CALCULADO EM PYTHON, E A SENHA NUNCA CHEGA AO POSTGRES

A primeira versão comparava no banco, com `senha_hash = crypt($1, senha_hash)`
do pgcrypto, e o comentário aqui afirmava que isso era mais seguro — a senha não
passaria por variável da aplicação.

Estava errado, e a demonstração foi direta: com a consulta em execução,
`pg_stat_activity` mostra `crypt('a-senha-em-claro', ...)`. Ou seja, a senha
fica visível para quem consegue ler a atividade do banco, e pode parar em log
conforme `log_statement`, `log_min_duration_statement` ou a coleta de consulta
lenta do provedor. Mandar a senha para o servidor de banco AUMENTA a superfície
em vez de reduzir: são mais um processo, mais um log e mais um conjunto de
pessoas com acesso.

Agora o Postgres só vê o hash derivado. A senha em claro existe dentro deste
processo, pelo tempo de uma chamada, e não sai dele.

POR QUE `hashlib.scrypt`, E NÃO BCRYPT

É biblioteca padrão — nenhuma dependência nova para uma função de segurança, o
que importa porque dependência a menos é superfície a menos. E scrypt é
memory-hard: além de tempo, cada tentativa custa memória, o que encarece o
ataque com GPU muito mais do que bcrypt.

O QUE ESTE MÓDULO NÃO FAZ, e é deliberado

Não cria conta, não redefine senha e não manda e-mail. Quem define a senha de
alguém é quem administra a plataforma, e hoje isso é `definir_senha` chamada à
mão. Um fluxo de "esqueci minha senha" é superfície conhecida — enumeração de
e-mail, token de redefinição vazando por log de proxy — e não se acrescenta de
passagem.

O QUE PROTEGE A ENTRADA

  1. **A resposta é a MESMA** para e-mail inexistente, senha errada e conta
     desativada. Distinguir entregaria a lista de quem tem acesso ao painel — e
     o painel guarda com quem a Aegea conversa.

  2. **O tempo também é o mesmo.** Sem usuário, um hash de isca é derivado
     assim mesmo. Sem isso, a diferença entre 1ms e 100ms diria "este e-mail
     existe" com precisão suficiente para varrer um diretório.

  3. **A comparação é de tempo constante** (`hmac.compare_digest`). Comparar
     com `==` vaza, por tempo, quantos bytes iniciais bateram.

  4. **Toda tentativa vira linha em `acesso_log`**, com o resultado — inclusive
     as recusas. Ver `registrar_e_confirmar` na rota: gravar sem confirmar faz
     a recusa sumir junto com a transação desfeita.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

#: Parâmetros do scrypt.
#:
#: `n = 2**14` custa cerca de 16 MB e uns poucos centésimos de segundo por
#: tentativa — desprezível para quem entra uma vez, caro para quem tenta um
#: dicionário. Subir `n` é a alavanca a revisar com o tempo; ele fica GRAVADO em
#: cada hash, então aumentar não invalida as senhas já cadastradas.
_N = 2**14
_R = 8
_P = 1
_TAMANHO_DO_SAL = 16
_TAMANHO_DA_CHAVE = 32

#: Prefixo do formato. Existe para o hash dizer o que é: no dia em que scrypt
#: for trocado, um `senha_hash` que não comece com isto é reconhecido como
#: formato antigo em vez de virar recusa silenciosa.
_FORMATO = "scrypt"

#: Mínimo de caracteres. Não há regra de complexidade de propósito: exigir
#: símbolo e maiúscula produz senha previsível e anotada em papel. Comprimento
#: é o que de fato custa a quem tenta adivinhar.
TAMANHO_MINIMO_DA_SENHA = 12


@dataclass(frozen=True, slots=True)
class Autenticado:
    """O bastante para emitir a sessão. Nunca carrega o hash."""

    usuario_id: str
    email: str
    nome: str


def gerar_hash(senha: str, *, n: int = _N) -> str:
    """`scrypt$n$r$p$sal$chave`, tudo em base64 sem preenchimento.

    Os parâmetros vão JUNTO do hash, e não numa constante: assim aumentar o
    custo amanhã não invalida o que já está gravado — cada senha é verificada
    com os parâmetros que a produziram.
    """
    sal = secrets.token_bytes(_TAMANHO_DO_SAL)
    chave = hashlib.scrypt(
        senha.encode("utf-8"), salt=sal, n=n, r=_R, p=_P, dklen=_TAMANHO_DA_CHAVE
    )
    return "$".join(
        [_FORMATO, str(n), str(_R), str(_P), _b64(sal), _b64(chave)]
    )


def conferir(senha: str, guardado: str) -> bool:
    """Se a senha produz o hash guardado. Nunca levanta."""
    try:
        formato, n, r, p, sal, chave = guardado.split("$")
        if formato != _FORMATO:
            return False
        derivada = hashlib.scrypt(
            senha.encode("utf-8"),
            salt=_de_b64(sal),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_de_b64(chave)),
        )
    except (ValueError, TypeError, MemoryError):
        # Hash corrompido, formato desconhecido, parâmetros absurdos. Recusa —
        # e NÃO deixa a exceção subir: uma senha errada não pode virar 500, que
        # informaria ao atacante que aquele registro é especial.
        return False

    # Tempo constante: `==` compara byte a byte e para no primeiro que difere,
    # o que revela por tempo quantos bateram.
    return hmac.compare_digest(derivada, _de_b64(chave))


def autenticar(sessao: Session, *, email: str, senha: str) -> Autenticado | None:
    """A pessoa, se e-mail e senha conferirem. `None` em qualquer outro caso.

    UM retorno para todas as recusas, de propósito: quem chama não consegue
    distinguir os casos nem por engano, então a rota não tem como vazar a
    diferença numa mensagem.
    """
    linha = sessao.execute(
        text("""
            select id::text as id, email, nome, senha_hash, ativo
              from usuario
             where email = :email
        """),
        {"email": email},
    ).first()

    # Sem usuário, sem senha cadastrada ou conta desativada: confere a isca e
    # devolve nada. O scrypt roda IGUAL nos quatro caminhos — é o que iguala o
    # tempo de resposta e impede descobrir quais e-mails existem.
    guardado = linha.senha_hash if linha and linha.senha_hash else _isca()
    confere = conferir(senha, guardado)

    if not linha or not linha.senha_hash or not linha.ativo or not confere:
        return None

    return Autenticado(usuario_id=linha.id, email=linha.email, nome=linha.nome)


def definir_senha(sessao: Session, *, email: str, senha: str, n: int = _N) -> None:
    """Grava a senha de alguém que já existe.

    NÃO é rota, e não deve virar uma sem que se decida antes quem pode chamá-la
    e como o valor chega:

        python -m app.banco.definir_senha fulano@aegea.com.br

    `n` menor serve aos testes: derivar dezenas de hashes com o custo de
    produção faria a suíte levar minutos, e o que se exercita é a lógica.
    """
    if len(senha) < TAMANHO_MINIMO_DA_SENHA:
        raise ValueError(
            f"Senha curta demais: use ao menos {TAMANHO_MINIMO_DA_SENHA} caracteres."
        )

    atingidos = sessao.execute(
        text("update usuario set senha_hash = :hash where email = :email"),
        {"hash": gerar_hash(senha, n=n), "email": email},
    ).rowcount

    if atingidos == 0:
        raise ValueError(f"Não há usuário com o e-mail {email!r}.")


def _b64(bruto: bytes) -> str:
    return base64.b64encode(bruto).decode("ascii").rstrip("=")


def _de_b64(texto: str) -> bytes:
    return base64.b64decode(texto + "=" * (-len(texto) % 4))


#: O hash de isca, derivado UMA vez por processo.
#:
#: Precisa ter os mesmos parâmetros dos hashes reais — é o custo que iguala o
#: tempo, e um custo diferente denunciaria a ausência do usuário.
_ISCA: str | None = None


def _isca() -> str:
    global _ISCA
    if _ISCA is None:
        _ISCA = gerar_hash(secrets.token_urlsafe(32))
    return _ISCA
