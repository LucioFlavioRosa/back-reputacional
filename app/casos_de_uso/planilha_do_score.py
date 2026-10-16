"""A planilha do Score entre a conferência e a confirmação.

POR QUE ESTE MÓDULO EXISTE. Importar uma planilha são dois pedidos: um que
confere e não grava nada, outro que grava. Até aqui os dois pediam o ARQUIVO —
a mesma pessoa mandava os mesmos bytes duas vezes. Medido em 15/10/2026 com o
clipping real da Clipei (10,53 MB, 75.369 linhas): 21 MB de tráfego e duas
travessias completas de ingress, nginx e API, para um trabalho que precisa dos
bytes uma vez.

E a segunda travessia é a pior, porque é a que grava: ela sobe o arquivo de
novo ANTES de começar, dentro do mesmo relógio de gateway que já estourou uma
vez — o 504 de 15/10/2026 no cluster do cliente, com 113 s de processamento
contra um teto de 60 s.

GUARDA O BYTE, NUNCA A CONCLUSÃO
--------------------------------
A importação de subtemas registra, com razão, que mandar o arquivo de novo "não
é desperdício: o servidor relê e reconfere contra o banco daquele instante", e
que guardar as propostas exigiria uma tabela de rascunho que aquele desenho
dispensa.

O argumento continua valendo inteiro, e este módulo não o contraria: a
confirmação segue relendo a planilha do zero e reconferindo veículo por veículo
e tema por tema contra o cadastro do instante em que ela roda. Nada do que a
conferência calculou é guardado aqui — nem previsão, nem veículo novo, nem
contagem. O que se dispensa é o UPLOAD.

A diferença, em uma frase: uma tabela de rascunho guarda o que o servidor
CONCLUIU e corre o risco de concluir diferente depois; esta guarda o que a
pessoa ENVIOU, que não muda.

UMA POR FONTE E POR PESSOA
--------------------------
Conferir de novo substitui a anterior, byte inclusive. Sem isso, cada
conferência abandonada deixaria dezenas de MB para sempre no contêiner — e
abandonar conferência é o caso NORMAL, não o excepcional: é o que acontece toda
vez que alguém olha a previsão e decide não subir.

A unicidade está declarada no índice da `0092`, e não só aqui: o código pode
esquecer de apagar a anterior; o banco não.

SEM ARMAZENAMENTO, TUDO ISTO SOME EM SILÊNCIO
---------------------------------------------
`blob_ligado` pode ser falso — o painel inteiro funciona assim, com material por
link. Então `guardar` devolve `None` em vez de explodir, a conferência responde
sem `planilha_id`, e a tela manda o arquivo de novo exatamente como antes. Esta
funcionalidade é uma economia, nunca uma dependência: o dia em que ela virar
pré-requisito é o dia em que uma conta de armazenamento mal configurada passa a
impedir a importação, que é um preço que ninguém aceitou pagar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.tabelas_score import PlanilhaRecebida, ScoreFonte
from app.dominio.erros import Conflito, NaoEncontrado

#: O que um `.xlsx` é para o Storage. A planilha NÃO passa por
#: `blob.exigir_tipo_aceito`: aquela lista guarda material de agenda, cujo teto
#: é 25 MB, e esta planilha vale até os 80 MB de `ingerir_mencoes`. Misturar as
#: duas réguas faria um arquivo legítimo ser recusado por um limite de outro
#: produto.
TIPO_DA_PLANILHA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Guardada:
    """O que a conferência guardou, e o que sobrou para apagar depois.

    `caminho_substituido` é o byte da conferência ANTERIOR desta mesma pessoa
    nesta mesma fonte. Ele não pode ser apagado junto com a linha: se a
    transação voltar atrás, a linha ressuscita apontando para o vazio. Vai para
    uma tarefa de fundo, depois do commit — a mesma ordem de
    `registrar_interacao.apagar_bytes_orfaos`.
    """

    id: UUID | None
    caminho_substituido: str | None


def guardar(
    sessao: Session, *, fonte: ScoreFonte, usuario_id: UUID, nome: str, dados: bytes
) -> Guardada:
    """Guarda a planilha conferida para a confirmação reusar.

    LINHA ANTES, BYTE DEPOIS, como em `registrar_interacao`: se o upload falhar,
    a transação volta atrás e a linha some junto. O contrário deixaria byte
    pago e invisível, sem ninguém que o conheça.

    DEVOLVE `id` NULO quando o armazenamento está desligado — ver o cabeçalho.
    """
    if not blob.ligado():
        return Guardada(id=None, caminho_substituido=None)

    anterior = sessao.scalar(
        select(PlanilhaRecebida).where(
            PlanilhaRecebida.fonte_id == fonte.id,
            PlanilhaRecebida.criado_por == usuario_id,
        )
    )
    substituido = anterior.caminho if anterior is not None else None
    if anterior is not None:
        sessao.execute(delete(PlanilhaRecebida).where(PlanilhaRecebida.id == anterior.id))
        #: O `flush` é obrigatório, e não higiene: sem ele o `insert` abaixo
        #: esbarra no índice único antes de o `delete` chegar ao banco.
        sessao.flush()

    planilha_id = uuid4()
    recebida = PlanilhaRecebida(
        id=planilha_id,
        fonte_id=fonte.id,
        caminho=blob.caminho_da_planilha(
            fonte=fonte.codigo, planilha_id=planilha_id, nome=nome
        ),
        nome=nome,
        tamanho=len(dados),
        criado_por=usuario_id,
    )
    try:
        #: PONTO DE SALVAMENTO, e não um `try` seco: uma violação de restrição
        #: envenena a transação inteira no psycopg, e sem o aninhamento o
        #: `rollback` levaria junto tudo o que a conferência já tinha feito.
        with sessao.begin_nested():
            sessao.add(recebida)
            sessao.flush()
    except IntegrityError as erro:
        #: DUAS CONFERÊNCIAS AO MESMO TEMPO, da mesma pessoa na mesma fonte: as
        #: duas passam pelo `select` acima, as duas apagam a anterior, e o
        #: índice único deixa só uma entrar. A corrida é real — o Codex a
        #: reproduziu no Postgres em 16/10/2026 — e é rara e inofensiva em
        #: dado: nada foi gravado errado, uma das duas só precisa repetir.
        #:
        #: 409, E NÃO 500: 500 diz "o servidor quebrou" e manda procurar
        #: defeito; 409 diz o que houve e o que fazer. Travar a linha antes não
        #: resolveria o caso que importa — na PRIMEIRA conferência não há linha
        #: anterior para travar.
        raise Conflito(
            "Outra conferência desta planilha está em andamento. Tente de novo."
        ) from erro

    blob.guardar(recebida.caminho, dados, TIPO_DA_PLANILHA)
    return Guardada(id=planilha_id, caminho_substituido=substituido)


def recuperar(
    sessao: Session, *, planilha_id: UUID, fonte: ScoreFonte, usuario_id: UUID
) -> bytes:
    """Os bytes que aquela pessoa conferiu para aquela fonte.

    AS TRÊS CONFERÊNCIAS SÃO A SEGURANÇA DESTA ROTA, e cada uma recusa uma
    coisa diferente:

      * `criado_por` — só quem conferiu confirma. Sem isso, conhecer um uuid
        bastaria para outra pessoa da coordenação gravar um arquivo que ela
        nunca viu, no mês de todo mundo;
      * `fonte_id` — a planilha da Clipei não entra pela rota da Approach. O
        mapeamento é por fonte, e o arquivo errado não daria erro: daria
        recusa de coluna, ou pior, leitura torta;
      * existir — a linha pode ter sido substituída por uma conferência mais
        nova enquanto a tela estava aberta, e aí o id na mão da tela é passado.

    As três devolvem a MESMA mensagem de propósito: distinguir "não é sua" de
    "não existe" conta a quem tem o id se ele acertou o número de outra pessoa.
    """
    recebida = sessao.scalar(
        select(PlanilhaRecebida).where(
            PlanilhaRecebida.id == planilha_id,
            PlanilhaRecebida.fonte_id == fonte.id,
            PlanilhaRecebida.criado_por == usuario_id,
        )
    )
    if recebida is None:
        raise NaoEncontrado(
            "Esta planilha não está mais guardada. Confira o arquivo de novo."
        )
    try:
        return blob.ler(recebida.caminho)
    except blob.ArmazenamentoDesligado as erro:
        #: O BLOB CAIU ENTRE OS DOIS PEDIDOS. A linha existe e o byte não está
        #: alcançável — para quem está na tela, é indistinguível de a planilha
        #: ter sumido, e é essa a mensagem útil: conferir de novo resolve,
        #: porque com o armazenamento desligado a conferência devolve
        #: `planilha_id` nulo e a tela volta a mandar o arquivo.
        #:
        #: 503 SERIA PIOR AQUI. "O armazenamento não está configurado" é
        #: verdade sobre o servidor e inútil para quem queria subir uma
        #: planilha: não diz o que fazer, e o que fazer existe. Achado da
        #: revisão do Codex em 16/10/2026.
        raise NaoEncontrado(
            "Esta planilha não está mais guardada. Confira o arquivo de novo."
        ) from erro


def descartar(sessao: Session, *, planilha_id: UUID) -> str | None:
    """Tira a linha depois que a importação gravou. Devolve o byte a apagar.

    O BYTE NÃO SAI AQUI, pela mesma razão de `Guardada.caminho_substituido`:
    apagar dentro da transação significa que um rollback devolve a linha
    apontando para o nada. Quem chama põe o caminho numa tarefa de fundo.
    """
    recebida = sessao.get(PlanilhaRecebida, planilha_id)
    if recebida is None:
        return None
    caminho = recebida.caminho
    sessao.execute(delete(PlanilhaRecebida).where(PlanilhaRecebida.id == planilha_id))
    return caminho


def id_da_pendente(sessao: Session, *, fonte: ScoreFonte, usuario_id: UUID) -> UUID | None:
    """Qual planilha daquela pessoa está pendente naquela fonte AGORA.

    POR QUE EXISTE, em uma frase: a importação PELO ARQUIVO também precisa
    limpar, e ela não tem identificador nenhum para citar — então ela pergunta
    qual é, ANTES de ingerir, e depois descarta por id como o outro ramo.

    O CAMINHO QUE VAZAVA. Quem manda `arquivo` na confirmação cai no ramo que
    não conhece `planilha_id`, e esse ramo não descartava nada: a importação
    terminava com sucesso e a linha mais o byte ficavam guardados — até a pessoa
    conferir aquela fonte de novo, o que pode nunca acontecer. Mandar o arquivo
    é caminho legítimo e permanente (a Calibração importa sem conferir, e a tela
    recai no arquivo sempre que não tem a conferência em mão).

    E POR QUE ESTA FUNÇÃO SÓ PERGUNTA, EM VEZ DE APAGAR. A primeira versão
    apagava por (fonte, dono) no fim da importação, e isso tinha uma corrida que
    PERDE TRABALHO — achado da revisão do Codex em 16/10/2026:

        1. a pessoa tem a planilha V1 pendente;
        2. começa a importar por arquivo (62 s de ingestão, medidos);
        3. no meio disso, outra conferência dela na mesma fonte grava V2;
        4. a importação apaga "a pendência" — e leva V2.

    V2 era a que ela ainda queria confirmar. Perguntar ANTES e apagar POR ID
    fecha isso: se a troca aconteceu, o descarte não acha V1 e não toca em V2 —
    o mesmo desfecho inofensivo que o ramo do identificador já tinha, e pela
    mesma razão. Era incoerente proteger um ramo e não o outro.

    DESCARTAR CONTINUA SENDO O CERTO para a pendência que existia antes: quem
    importou aquela fonte por arquivo tornou obsoleta a conferência dela — a
    previsão foi calculada contra um banco que já não existe.

    POR DONO E POR FONTE na consulta, que é a granularidade do índice único da
    `0092`: acha no máximo uma linha, e nunca a de outra pessoa nem de outra
    fonte.
    """
    return sessao.scalar(
        select(PlanilhaRecebida.id).where(
            PlanilhaRecebida.fonte_id == fonte.id,
            PlanilhaRecebida.criado_por == usuario_id,
        )
    )


def apagar_byte(caminho: str | None) -> None:
    """Apaga o byte de uma planilha que já não tem linha. DEPOIS do commit.

    Engole a falha, como `registrar_interacao.apagar_bytes_orfaos`: o dado já
    está consistente, e o que resta é um arquivo que ninguém alcança. Devolver
    500 para quem acabou de importar com sucesso seria mentir sobre o que
    aconteceu.
    """
    if not caminho:
        return
    try:
        blob.apagar(caminho)
    except Exception:  # noqa: BLE001
        _log.warning(
            "Byte órfão de planilha não apagado: %s. A linha já saiu do banco; "
            "o arquivo continua ocupando espaço no contêiner.",
            caminho,
        )
