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
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.tabelas_score import PlanilhaRecebida, ScoreFonte
from app.casos_de_uso import ingerir_mencoes
from app.dominio.erros import Conflito, NaoEncontrado, RegraViolada

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

    planilha_id = uuid4()
    guardada = _registrar(
        sessao,
        fonte=fonte,
        usuario_id=usuario_id,
        planilha_id=planilha_id,
        nome=nome,
        tamanho=len(dados),
        caminho=blob.caminho_da_planilha(
            fonte=fonte.codigo, planilha_id=planilha_id, nome=nome
        ),
    )
    blob.guardar(
        blob.caminho_da_planilha(fonte=fonte.codigo, planilha_id=planilha_id, nome=nome),
        dados,
        TIPO_DA_PLANILHA,
    )
    return guardada


def _registrar(
    sessao: Session,
    *,
    fonte: ScoreFonte,
    usuario_id: UUID,
    planilha_id: UUID,
    nome: str,
    tamanho: int,
    caminho: str,
    completa: bool = True,
) -> Guardada:
    """A LINHA, só ela — o byte é de quem chama.

    EXTRAÍDA DE `guardar` PORQUE HÁ DOIS CAMINHOS ATÉ O BYTE e um só até a
    linha. Quem sobe de uma vez grava a linha e depois o byte; quem sobe em
    partes já tem o byte publicado quando chega aqui. A regra de substituir a
    anterior, o ponto de salvamento e o 409 da corrida são os mesmos nos dois, e
    duplicá-los seria garantir que divergissem.
    """
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

    recebida = PlanilhaRecebida(
        id=planilha_id,
        fonte_id=fonte.id,
        caminho=caminho,
        nome=nome,
        tamanho=tamanho,
        criado_por=usuario_id,
        #: `None` É O ESTADO "SUBINDO". A subida de uma vez só grava a linha
        #: depois de conferir, então ela nasce completa; a em partes nasce
        #: incompleta e `concluir` a fecha. Ver a `0094`.
        completa_em=datetime.now(UTC) if completa else None,
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

    return Guardada(id=planilha_id, caminho_substituido=substituido)


#: O PEDAÇO, e o número sai de medição, não de gosto.
#:
#: O TETO QUE MANDA é o do ingress do Container Apps: ~240 s por requisição, e
#: ele NÃO é configurável. Medido no navegador dele em 16/10/2026, pela
#: telemetria do próprio painel:
#:
#:     1,42 MB  ->    4,1 s  -> 200
#:     1,33 MB  ->   73,2 s  -> 200
#:    10,53 MB  ->  212,4 s  -> 403   (o ingress desistindo)
#:    10,53 MB  ->  212,6 s  -> 403
#:    10,53 MB  ->  227,4 s  -> 403
#:
#: A banda de subida varia de ~18 KB/s a ~350 KB/s na mesma máquina e na mesma
#: hora. A 18 KB/s, 10,53 MB precisariam de 390 s e nunca caberiam em 240.
#:
#: 1 MB DÁ ~57 s NO PIOR CASO MEDIDO, quatro vezes de margem. Pedaço maior
#: compra menos requisições e gasta a margem que justamente não existe; pedaço
#: menor multiplica idas sem comprar segurança que já está em 4x.
TAMANHO_DA_PARTE = 1 * 1024 * 1024


def _partes_maximas() -> int:
    """O máximo de partes que uma subida pode ter, derivado e não escolhido.

    EXISTE PORQUE `partes` VEM DO CLIENTE. Sem este limite,
    `partes=1_000_000_000` na conferência fazia o processo construir a lista de
    blocos ANTES de falar com o Azure — uma requisição derrubava a réplica.
    Achado da revisão do Codex em 16/10/2026.

    FUNÇÃO E NÃO CONSTANTE porque `TAMANHO_DA_PARTE` é trocado nos testes, e uma
    constante calculada no import ficaria com o valor antigo — o teto deixaria
    de valer exatamente onde se quer provar que ele vale.
    """
    return ingerir_mencoes.TAMANHO_MAXIMO // TAMANHO_DA_PARTE + 1


def comecar(
    sessao: Session, *, fonte: ScoreFonte, usuario_id: UUID, nome: str, tamanho: int
) -> Guardada:
    """Abre uma subida em partes: GRAVA A LINHA e devolve o identificador.

    A LINHA NASCE AQUI, e esta é a correção de quatro defeitos de uma vez —
    todos achados pela revisão do Codex em 16/10/2026, quando esta função não
    tocava no banco e o estado da subida era só o caminho no Blob:

      1. O IDENTIFICADOR VALIA COMO SENHA AO PORTADOR. Sem linha, `receber_parte`
         não tinha o que consultar para saber de quem era a subida — então
         aceitava parte de qualquer sessão, e quem conhecesse o uuid de outra
         pessoa registrava a planilha dela no próprio nome.

      2. O TETO DECLARADO NÃO LIMITAVA. Declarar 1 MB e enviar oitenta partes de
         1 MB montava 80 MB. Agora o declarado fica GRAVADO, e é contra ele que
         cada parte é conferida.

      3. O BYTE FICAVA ÓRFÃO. A linha vinha depois do arquivo, e o commit da
         sessão roda DEPOIS de a rota retornar (`banco/sessao.py`): um commit
         que falhasse desfazia a linha e deixava o arquivo publicado. Com a
         linha nascendo antes, o pior caso é uma linha INCOMPLETA apontando para
         o byte — que é o que permite achá-lo.

      4. Nada limitava quantas subidas uma pessoa abria. O índice único de
         (fonte, criado_por) passa a significar "uma subida em voo por fonte e
         por pessoa".

    SUBSTITUI A ANTERIOR, como a conferência de uma vez só faz: abrir subida nova
    descarta a planilha pendente daquela pessoa naquela fonte, byte inclusive.
    Quem chama põe `caminho_substituido` numa tarefa de fundo.

    O NOME VEM AGORA, e não no fim: ele é coluna `not null`, e a linha existe
    desde já. Pedi-lo no último passo obrigaria um valor de mentira no meio.

    O IDENTIFICADOR É DO SERVIDOR, e não do cliente: ele entra no caminho do
    armazenamento, e caminho montado com valor que o cliente escolhe é como se
    escreve em pasta alheia.
    """
    if not blob.ligado():
        #: Sem armazenamento não há onde montar. A tela cai no envio de uma vez
        #: só, que é o caminho que sempre existiu.
        raise RegraViolada(
            "Este ambiente não guarda arquivos, então a planilha precisa subir "
            "de uma vez. Se ela for grande demais para isso, fale com quem "
            "administra."
        )
    if tamanho <= 0:
        raise RegraViolada("Diga o tamanho da planilha para começar a subida.")
    if tamanho > ingerir_mencoes.TAMANHO_MAXIMO:
        raise RegraViolada(
            f"A planilha passa de {ingerir_mencoes.TAMANHO_MAXIMO // (1024 * 1024)} MB."
        )
    planilha_id = uuid4()
    return _registrar(
        sessao,
        fonte=fonte,
        usuario_id=usuario_id,
        planilha_id=planilha_id,
        nome=nome,
        tamanho=tamanho,
        caminho=blob.caminho_da_planilha_em_partes(
            fonte=fonte.codigo, planilha_id=planilha_id
        ),
        #: SUBINDO: é a ausência de `completa_em` que diz isso, e é ela que faz
        #: `recuperar` recusar confirmar uma planilha que ainda chega.
        completa=False,
    )


def _subida_em_voo(
    sessao: Session, *, planilha_id: UUID, fonte: ScoreFonte, usuario_id: UUID
) -> PlanilhaRecebida:
    """A subida que aquela pessoa abriu naquela fonte, ou recusa.

    AS QUATRO CONDIÇÕES SÃO A SEGURANÇA DESTE CAMINHO, e cada uma recusa uma
    coisa diferente:

      * existir — `PUT` com uuid nunca aberto gastava armazenamento sem criar
        estado nenhum;
      * `criado_por` — é O defeito que a revisão achou. Sem isto o uuid valia
        como senha ao portador: conhecê-lo bastava para mandar parte na subida
        de outra pessoa e registrar a planilha dela no próprio nome;
      * `fonte_id` — a planilha da Clipei não se monta pela rota da Approach;
      * ESTAR SUBINDO — mandar parte para uma planilha já conferida
        sobrescreveria, pelo `commit_block_list`, um arquivo que alguém está
        prestes a confirmar.

    A MESMA MENSAGEM NOS QUATRO CASOS, de propósito: distinguir "não é sua" de
    "não existe" conta a quem tem o id se ele acertou o número de outra pessoa.
    """
    recebida = sessao.scalar(
        select(PlanilhaRecebida).where(
            PlanilhaRecebida.id == planilha_id,
            PlanilhaRecebida.fonte_id == fonte.id,
            PlanilhaRecebida.criado_por == usuario_id,
            PlanilhaRecebida.completa_em.is_(None),
        )
    )
    if recebida is None:
        raise NaoEncontrado(
            "Esta subida não está em andamento. Comece a subida de novo."
        )
    return recebida


def receber_parte(
    sessao: Session,
    *,
    fonte: ScoreFonte,
    planilha_id: UUID,
    usuario_id: UUID,
    indice: int,
    dados: bytes,
) -> None:
    """Guarda uma parte da subida DAQUELA PESSOA. Não publica nada.

    CONSULTA O BANCO ANTES DE ESCREVER, e é essa a correção: antes não havia o
    que consultar e a rota aceitava parte de qualquer sessão para qualquer uuid.
    Ver `_subida_em_voo`.

    OS DOIS TETOS SÃO O QUE SOBROU DO ABUSO. A rota da parte é isenta do limite
    genérico de corpo — tem de ser, senão a primeira parte seria recusada — e o
    servidor lê a parte inteira na memória. Sem estes dois, uma sessão autorizada
    mandava partes de qualquer tamanho e acumulava além do teto:

      * cada parte cabe em `TAMANHO_DA_PARTE`;
      * o índice cabe no que o TAMANHO DECLARADO comporta.

    Juntos eles limitam o arquivo montado a pouco mais do que foi declarado — e o
    declarado já foi conferido contra os 80 MB na abertura. A conferência final
    ainda mede os bytes de verdade, que é o que de fato autoriza.

    A PARTE VAZIA É RECUSADA: o Blob aceita bloco de zero byte, e um deles no
    meio da lista produz um `.xlsx` truncado que só falha na leitura, longe da
    causa.
    """
    subida = _subida_em_voo(
        sessao, planilha_id=planilha_id, fonte=fonte, usuario_id=usuario_id
    )
    esperadas = _partes_esperadas(subida.tamanho)
    if not dados:
        raise RegraViolada("A parte chegou vazia. Mande os bytes dela.")
    if indice < 0 or indice >= esperadas:
        raise RegraViolada(
            "Esta parte está fora do tamanho que a subida declarou. "
            "Comece a subida de novo."
        )
    #: PARTE CHEIA, EXCETO A ÚLTIMA — e esta regra é o que faz a aritmética do
    #: teto fechar. Com ela, o arquivo montado não passa de
    #: `partes_esperadas * TAMANHO_DA_PARTE`, que é o declarado arredondado para
    #: cima; sem ela, partes menores permitiriam mais partes que o esperado e o
    #: total voltaria a ser ilimitado.
    #:
    #: O SERVIDOR DITA O TAMANHO na abertura, então o cliente não tem o que
    #: adivinhar. A recusa diz o número para quem estiver escrevendo outro
    #: cliente.
    ultima = indice == esperadas - 1
    if len(dados) > TAMANHO_DA_PARTE or (not ultima and len(dados) != TAMANHO_DA_PARTE):
        raise RegraViolada(
            f"Cada parte tem {TAMANHO_DA_PARTE} bytes, menos a última. "
            "Comece a subida de novo."
        )
    blob.guardar_parte(subida.caminho, indice, dados)


def _partes_esperadas(tamanho_declarado: int) -> int:
    """Quantas partes um arquivo daquele tamanho tem, para o teto do índice."""
    return -(-tamanho_declarado // TAMANHO_DA_PARTE)


def montar(
    sessao: Session,
    *,
    fonte: ScoreFonte,
    planilha_id: UUID,
    usuario_id: UUID,
    partes: int,
) -> tuple[PlanilhaRecebida, bytes]:
    """Junta as partes da subida daquela pessoa e devolve a linha e os bytes.

    DEVOLVE OS BYTES em vez de só publicar porque quem chama precisa deles para
    conferir — e lê-los de volta do armazenamento é o que garante que o que vai
    ser conferido é exatamente o que ficou gravado, e não o que o servidor
    pensava ter montado.

    `partes` VEM DO CLIENTE, e por isso tem dois tetos: `PARTES_MAXIMAS`, que é
    derivado do teto da planilha, e o que o tamanho DECLARADO desta subida
    comporta. Sem eles, `partes=1_000_000_000` construía a lista de blocos na
    memória antes de qualquer chamada ao Azure.

    PARTE FALTANDO VIRA RECUSA COM NOME, e não erro de leitura: o serviço recusa
    a lista inteira quando um bloco não está lá, e sem esta tradução a pessoa
    leria "não consegui abrir o arquivo como planilha" — que manda procurar
    defeito no arquivo dela.
    """
    subida = _subida_em_voo(
        sessao, planilha_id=planilha_id, fonte=fonte, usuario_id=usuario_id
    )
    if partes <= 0:
        raise RegraViolada("Diga quantas partes a planilha tem.")
    if partes > _partes_maximas() or partes > _partes_esperadas(subida.tamanho):
        raise RegraViolada(
            "Esta contagem de partes não corresponde ao tamanho que a subida "
            "declarou. Comece a subida de novo."
        )
    try:
        blob.juntar_partes(subida.caminho, partes, TIPO_DA_PLANILHA)
    except Exception as erro:  # noqa: BLE001 - bloco ausente, expirado ou id errado
        raise RegraViolada(
            "Faltou alguma parte da planilha. Comece a subida de novo."
        ) from erro
    return subida, blob.ler(subida.caminho)


def concluir(subida: PlanilhaRecebida, *, tamanho: int) -> None:
    """Marca a subida como completa, com o tamanho REAL do arquivo montado.

    O DECLARADO ERA AFIRMAÇÃO DO CLIENTE e serviu para dimensionar os tetos; o
    que fica gravado é o que o arquivo tem. Guardar o declarado faria a tela
    dizer um número que ninguém mediu.

    DEPOIS DE CONFERIR, nunca antes: enquanto `completa_em` é nulo, `recuperar`
    recusa confirmar — e é isso que impede confirmar uma planilha que a
    conferência acabou de recusar.
    """
    subida.tamanho = tamanho
    subida.completa_em = datetime.now(UTC)


def descartar_montagem(*, fonte: ScoreFonte, planilha_id: UUID) -> None:
    """Apaga o arquivo montado de uma subida que foi recusada. Engole a falha.

    ENGOLE PORQUE O ERRO ORIGINAL É O QUE IMPORTA: relançar daqui esconderia a
    recusa da conferência — que é o que a pessoa precisa ler — por uma falha de
    limpeza, que é problema nosso.

    E O BYTE NÃO SE PERDE DE VISTA quando isto falha, que é a diferença em
    relação à versão anterior: a linha da subida existe desde a abertura e
    continua apontando para o caminho. Antes, falhar aqui deixava um arquivo que
    nenhuma linha citava — e o id era aleatório, então nem procurá-lo era
    possível. Uma varredura por idade (ainda não existe) acha pelo `criado_em`.
    """
    try:
        blob.apagar(
            blob.caminho_da_planilha_em_partes(fonte=fonte.codigo, planilha_id=planilha_id)
        )
    except Exception:  # noqa: BLE001
        _log.warning(
            "Byte de subida recusada ficou no contêiner: fonte %s, id %s. "
            "A linha de planilha_recebida ainda o cita.",
            fonte.codigo,
            planilha_id,
        )


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
            #: A QUARTA CONDIÇÃO, e ela entrou com a subida em partes: confirmar
            #: uma planilha que AINDA SOBE leria um arquivo que não existe —
            #: `commit_block_list` não rodou — ou, se rodou e a conferência
            #: falhou depois, um arquivo que a conferência recusou.
            #:
            #: A MESMA MENSAGEM dos outros três casos, e o conselho serve:
            #: conferir de novo é o que resolve, porque a conferência é o passo
            #: que marca a subida como completa.
            PlanilhaRecebida.completa_em.is_not(None),
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
