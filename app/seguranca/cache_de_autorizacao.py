"""Papel e escopo em memória por um tempo, em vez de lidos a cada requisição.

POR QUE EXISTE

Reconstruir a autorização custa 3 comandos no banco — ou 4 quando o escopo é
por linha em vez de irrestrito. Medido, com sessão nova, que é o que toda
requisição tem:

    SELECT usuario ...          busca por chave
    UPDATE usuario SET ultimo_acesso_em = ...
    SELECT papel ...            busca por chave
    SELECT usuario_escopo ...   só quando o acesso não é irrestrito

Nenhum é caro sozinho. Dois pontos fazem o conjunto pesar: o segundo é uma
ESCRITA, com o custo de WAL e de versão de linha que toda escrita tem; e o
volume, porque o painel deriva as análises no cliente e pagina de 200 em 200 até
5.000 registros — UMA tela dispara dezenas de requisições, todas reconstruindo
exatamente a mesma permissão.

O `UPDATE` já tinha folga própria de 5 minutos (`FOLGA_DE_REGISTRO_DE_ACESSO`),
então a frequência dele não muda com o cache. O que cai são as leituras.

O QUE SE PAGA POR ISSO

Uma janela. Uma revogação passa a valer em até `ttl` segundos, e não no clique
seguinte. Isso é decisão consciente, tomada porque mudança de permissão neste
painel é rara — concessão e revogação passam por coordenação, não por
autoatendimento — enquanto a leitura acontece o tempo todo.

TRÊS COISAS QUE O CACHE NÃO PODE CEGAR, E NÃO CEGA

1. **O vencimento do acesso.** Uma entrada nunca vive além de
   `acesso_expira_em`. Sem isso, um acesso que vence às 14h00 valeria até
   14h05, e o prazo deixaria de ser prazo. Ver `_ate_quando`.

2. **A revogação feita pela própria aplicação.** `conceder()` chama
   `esquecer()`, então quem administra vê o efeito no ato — que é justamente
   quando alguém confere se a revogação pegou.

3. **A sessão.** O cookie continua sendo lido, verificado e datado a cada
   requisição. O que se guarda aqui é o que o banco diria sobre um usuário JÁ
   identificado, nunca a identidade em si.

O QUE ELE CEGA, E PRECISA SER SABIDO

Uma alteração feita FORA da aplicação — `update usuario set ativo = false` no
banco, ou `update papel set ativo = false` para revogação em massa — só vale
quando a entrada expira. E o estado é DA INSTÂNCIA: com N instâncias no App
Service, cada uma tem o seu cache e a revogação chega em momentos diferentes,
todos dentro do mesmo teto de `ttl`. Para janela menor, diminua `ttl`; para
janela nenhuma, `AUTORIZACAO_CACHE_SEGUNDOS=0` desliga.

POR QUE TEM TRAVA E O LIMITADOR DE TAXA NÃO TEM

O limitador roda em middleware `async`, na thread do laço de eventos, então
suas operações nunca se intercalam. Este cache é lido de dependência SÍNCRONA,
e as rotas deste projeto são `def` — o FastAPI as executa num threadpool, com
paralelismo real. `dict` é seguro sob o GIL para uma operação só, mas
"ler, decidir e apagar" são três.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.dominio.identidade import UsuarioAtual


#: Teto de entradas por cache.
#:
#: Não é dimensionamento — é rede de segurança. A base de usuários do painel são
#: funcionários da Aegea mais convidados B2B, na casa das centenas; este número
#: nunca deveria ser alcançado. Existe para o mapa não crescer sem fim se essa
#: premissa mudar, e porque encostar nele degrada para "sem cache", que é o
#: comportamento anterior e correto — não para uma falha.
_TETO_DE_ENTRADAS = 10_000


@dataclass(frozen=True, slots=True)
class _Entrada:
    usuario: UsuarioAtual
    #: Relógio monotônico, e não data-hora: mudança de fuso, ajuste de NTP ou
    #: horário de verão não podem esticar a validade de uma permissão.
    vale_ate: float


class CacheDeAutorizacao:
    """Guarda o resultado de `carregar()` por um tempo, por usuário."""

    def __init__(self, ttl_segundos: float) -> None:
        self._ttl = max(0.0, ttl_segundos)
        self._entradas: dict[UUID, _Entrada] = {}
        self._trava = threading.Lock()
        #: Conta invalidações. Ver `marcador()` e `guardar()`.
        self._invalidacoes = 0

    @property
    def ligado(self) -> bool:
        return self._ttl > 0

    def obter(self, usuario_id: UUID) -> UsuarioAtual | None:
        """O usuário guardado, ou `None` se não há ou se venceu."""
        if not self.ligado:
            return None

        agora = time.monotonic()
        with self._trava:
            entrada = self._entradas.get(usuario_id)
            if entrada is None:
                return None
            if entrada.vale_ate <= agora:
                # Sai agora, e não numa varredura futura: assim o mapa não
                # guarda permissão vencida à espera de alguém passar por ela.
                del self._entradas[usuario_id]
                return None
            return entrada.usuario

    def marcador(self) -> int:
        """Instantâneo do estado de invalidação, para passar a `guardar()`.

        Quem vai ler o banco pega o marcador ANTES da leitura. Ver `guardar()`
        para o que isso resolve.
        """
        with self._trava:
            return self._invalidacoes

    def guardar(self, usuario: UsuarioAtual, marcador: int | None = None) -> None:
        """Guarda o que foi lido do banco, se ainda valer.

        O `marcador` fecha uma corrida que anula a promessa de que revogar pela
        tela vale no ato:

            requisição A  erra o cache e começa a ler do banco
            admin         revoga, e a revogação chama `esquecer()`
            requisição A  termina a leitura e guarda o que leu — o valor VELHO

        Sem o marcador, a permissão revogada ressuscitaria e valeria por mais um
        TTL inteiro, justamente na instância onde alguém acabou de revogar.

        A comparação é do contador INTEIRO, e não por usuário: qualquer
        invalidação ocorrida durante a leitura recusa a gravação. É mais amplo
        do que o estritamente necessário, e de propósito — invalidação é rara
        (mudança de permissão), guardar de menos só custa uma releitura, e
        guardar de mais custa autorização errada. Diante da dúvida, erra-se
        para o lado de reler.
        """
        if not self.ligado:
            return

        vale_ate = self._ate_quando(usuario)
        if vale_ate is None:
            return

        with self._trava:
            if marcador is not None and marcador != self._invalidacoes:
                return
            if len(self._entradas) >= _TETO_DE_ENTRADAS:
                self._podar_vencidas()
                if len(self._entradas) >= _TETO_DE_ENTRADAS:
                    # Deixa de cachear em vez de crescer sem fim. O pior que
                    # acontece é voltar ao comportamento de reler sempre — o
                    # cache nunca é necessário para a resposta estar correta.
                    return
            self._entradas[usuario.id] = _Entrada(usuario=usuario, vale_ate=vale_ate)

    def esquecer(self, usuario_id: UUID) -> None:
        """Descarta o que se sabia deste usuário. Chamado por quem ESCREVE."""
        with self._trava:
            self._invalidacoes += 1
            self._entradas.pop(usuario_id, None)

    def _podar_vencidas(self) -> None:
        """Tira as entradas já vencidas. Chamada com a trava em mãos.

        Só roda ao encostar no teto. Uma varredura periódica exigiria uma
        thread, e uma thread exigiria desligá-la no encerramento — complexidade
        que este cache não justifica: toda entrada vencida é descartada de
        graça na próxima leitura da mesma chave.
        """
        agora = time.monotonic()
        vencidas = [k for k, e in self._entradas.items() if e.vale_ate <= agora]
        for k in vencidas:
            del self._entradas[k]

    def limpar(self) -> None:
        with self._trava:
            self._entradas.clear()
            self._invalidacoes += 1

    def _ate_quando(self, usuario: UsuarioAtual) -> float | None:
        """O menor entre o `ttl` e o que sobra do prazo de acesso.

        Devolve `None` quando não sobra nada — acesso já vencido não vira
        entrada, porque guardá-lo por um instante que seja é guardar uma
        permissão que o banco já não daria.
        """
        teto = time.monotonic() + self._ttl
        if usuario.acesso_expira_em is None:
            return teto

        falta = (_vence_em(usuario.acesso_expira_em) - datetime.now(UTC)).total_seconds()
        if falta <= 0:
            return None
        return min(teto, time.monotonic() + falta)


def _vence_em(prazo: date) -> datetime:
    """O instante em que um prazo deixa de valer.

    `acesso_expira_em` é um DIA de calendário (coluna `date`), não um instante,
    e `UsuarioAtual.acesso_vencido()` o lê como "vencido quando hoje em UTC
    passou dele". O acesso vale, portanto, o dia inteiro: expira à meia-noite
    UTC do dia SEGUINTE, e é isso que esta função devolve.

    Tratar o prazo como instante — que é o que uma leitura apressada faz — daria
    meia-noite do PRÓPRIO dia e cortaria o último dia de acesso inteiro. As duas
    contas divergem em 24 horas, e a diferença aparece só no último dia de quem
    é de fora, que é exatamente quando ninguém está olhando.
    """
    dia = prazo.date() if isinstance(prazo, datetime) else prazo
    return datetime.combine(dia + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


#: Os caches vivos do processo, um por TTL configurado.
#:
#: Indexado pelo TTL, e não um só global, pelo mesmo motivo que os baldes do
#: limitador de taxa: recriar a aplicação no mesmo processo — que é o que os
#: testes fazem — precisa render um cache novo quando o TTL muda, senão o teste
#: mede a janela antiga.
_registro: dict[float, CacheDeAutorizacao] = {}
_trava_do_registro = threading.Lock()


def cache_para(ttl_segundos: float) -> CacheDeAutorizacao:
    with _trava_do_registro:
        if ttl_segundos not in _registro:
            _registro[ttl_segundos] = CacheDeAutorizacao(ttl_segundos)
        return _registro[ttl_segundos]


def esquecer_em_todos(usuario_id: UUID) -> None:
    """Descarta este usuário de TODO cache do processo.

    Quem altera autorização chama isto e não precisa saber qual configuração
    está em vigor: a pergunta que importa é "ninguém mais pode estar servindo a
    permissão antiga desta pessoa", e a resposta não depende do TTL.
    """
    with _trava_do_registro:
        caches = list(_registro.values())
    for cache in caches:
        cache.esquecer(usuario_id)


def limpar_todos() -> None:
    """Só para teste: devolve o processo ao estado de quem nunca cacheou nada."""
    with _trava_do_registro:
        caches = list(_registro.values())
    for cache in caches:
        cache.limpar()
