"""A subida em partes do export de bonds: a linha, o dono e a montagem.

POR QUE ESTA TELA PRECISA DISSO. O ingress do Container Apps encerra a
requisição por volta de 240 s, e isso NÃO é configurável. Medido na mesma
máquina e na mesma hora, com a banda variando bastante: 1,42 MB subiram em 4 s
e deram 200; 10,53 MB passaram de 212 s e levaram 403, o ingress desistindo.

O export é CUMULATIVO e cresce toda semana, e a tela manda o arquivo DUAS
VEZES, porque confere e depois importa.

O QUE ESTE MÓDULO NÃO FAZ: as regras do pedaço. Tamanho da parte, índice,
contagem e seus tetos estão em `subida_em_partes`, que não sabe de bonds. Aqui
mora o que é desta tela: a linha, o dono, o caminho no armazenamento e o que
fazer com o arquivo montado.

A LÓGICA DE SEGURANÇA É A DA PLANILHA DO SCORE, com uma condição menos: lá o
`where` casa também `fonte_id`, porque cada subida é de uma fonte do Score; aqui
o export é um só. Ver `_em_voo`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.tabelas_mercado import PlanilhaDeBondsRecebida
from app.casos_de_uso import subida_em_partes
from app.casos_de_uso.ingerir_mencoes import TAMANHO_MAXIMO
from app.dominio.erros import NaoEncontrado, RegraViolada

TIPO_DA_PLANILHA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class Aberta:
    """O que a abertura devolve para a tela.

    `id` NULO SIGNIFICA "AQUI NÃO DÁ, MANDE DE UMA VEZ" — ambiente sem
    armazenamento não tem onde montar. É a mesma convenção da planilha do Score,
    e existe porque recusar com 422 não funciona: o cliente não distingue essa
    recusa das outras desta rota e mostra a mensagem crua.
    """

    id: UUID | None
    caminho_substituido: str | None = None


def comecar(
    sessao: Session, *, usuario_id: UUID, nome: str, tamanho: int
) -> Aberta:
    """Abre uma subida em partes: GRAVA A LINHA e devolve o identificador.

    A LINHA NASCE ANTES DO BYTE, e é ela que dá dono à subida. Sem linha, o
    identificador valeria como senha ao portador. E o byte nunca fica órfão: uma
    falha em qualquer ponto, inclusive no commit (que roda DEPOIS de a rota
    retornar), deixa uma linha incompleta apontando para o arquivo, que é o que
    permite achá-lo.

    O TAMANHO DECLARADO FICA GRAVADO, e é contra ele que cada parte é conferida:
    sem isso, declarar 1 MB e mandar oitenta partes de 1 MB montaria 80 MB.

    SUBSTITUI A PENDENTE daquela pessoa, byte inclusive — é o que o índice único
    de `criado_por` exige, e o que a tela já espera. Quem chama põe
    `caminho_substituido` numa tarefa de fundo.

    O IDENTIFICADOR É DO SERVIDOR, e não do cliente: ele entra no caminho do
    armazenamento, e caminho montado com valor que o cliente escolhe é como se
    escreve em pasta alheia.
    """
    if tamanho <= 0:
        raise RegraViolada("Diga o tamanho do arquivo que vai subir.")
    if tamanho > TAMANHO_MAXIMO:
        raise RegraViolada("A planilha de bonds passa do tamanho que se aceita ler.")
    if not blob.ligado():
        return Aberta(id=None)

    anterior = sessao.scalar(
        select(PlanilhaDeBondsRecebida).where(
            PlanilhaDeBondsRecebida.criado_por == usuario_id
        )
    )
    substituido = None
    if anterior is not None:
        substituido = anterior.caminho
        sessao.delete(anterior)
        sessao.flush()

    subida_id = uuid4()
    sessao.add(
        PlanilhaDeBondsRecebida(
            id=subida_id,
            caminho=blob.caminho_dos_bonds_em_partes(subida_id=subida_id),
            nome=nome,
            tamanho=tamanho,
            criado_por=usuario_id,
        )
    )
    sessao.flush()
    return Aberta(id=subida_id, caminho_substituido=substituido)


def _em_voo(
    sessao: Session, *, subida_id: UUID, usuario_id: UUID
) -> PlanilhaDeBondsRecebida:
    """A subida que aquela pessoa abriu, ou recusa.

    AS TRÊS CONDIÇÕES SÃO A SEGURANÇA DESTE CAMINHO, e cada uma recusa uma
    coisa diferente:

      * existir — `PUT` com uuid nunca aberto gastaria armazenamento sem criar
        estado nenhum;
      * `criado_por` — sem isto o uuid vale como senha ao portador: conhecê-lo
        basta para mandar parte na subida de outra pessoa;
      * ESTAR SUBINDO — mandar parte para uma planilha já montada
        sobrescreveria, pelo `commit_block_list`, um arquivo que alguém está
        prestes a importar.

    A MESMA MENSAGEM NOS TRÊS CASOS, de propósito: distinguir "não é sua" de
    "não existe" conta a quem tem o id se ele acertou o número de outra pessoa.
    """
    subida = sessao.scalar(
        select(PlanilhaDeBondsRecebida).where(
            PlanilhaDeBondsRecebida.id == subida_id,
            PlanilhaDeBondsRecebida.criado_por == usuario_id,
            PlanilhaDeBondsRecebida.completa_em.is_(None),
        )
    )
    if subida is None:
        raise NaoEncontrado(
            "Esta subida não está em andamento. Comece a subida de novo."
        )
    return subida


def receber_parte(
    sessao: Session, *, subida_id: UUID, usuario_id: UUID, indice: int, dados: bytes
) -> None:
    """Guarda uma parte da subida DAQUELA PESSOA. Não publica nada.

    CONSULTA O BANCO ANTES DE ESCREVER, e nesta ordem: `_em_voo` primeiro, as
    regras do pedaço depois. Invertido, um uuid de outra pessoa receberia "a
    parte chegou vazia" em vez de "não está em andamento" — e isso já conta a
    quem tem o número que ele existe.
    """
    subida = _em_voo(sessao, subida_id=subida_id, usuario_id=usuario_id)
    subida_em_partes.conferir_a_parte(
        indice=indice, dados=dados, tamanho_declarado=subida.tamanho
    )
    blob.guardar_parte(subida.caminho, indice, dados)


def montar(
    sessao: Session, *, subida_id: UUID, usuario_id: UUID, partes: int
) -> tuple[PlanilhaDeBondsRecebida, bytes]:
    """Junta as partes da subida daquela pessoa e devolve a linha e os bytes.

    DEVOLVE OS BYTES em vez de só publicar porque quem chama precisa deles para
    conferir, e lê-los de volta do armazenamento garante que o conferido é o que
    ficou gravado, não o que o servidor pensava ter montado.

    PARTE FALTANDO VIRA RECUSA COM NOME, e não erro de leitura: sem esta
    tradução a pessoa leria "não consegui abrir o arquivo como planilha", que
    manda procurar defeito no arquivo dela.
    """
    subida = _em_voo(sessao, subida_id=subida_id, usuario_id=usuario_id)
    subida_em_partes.conferir_a_contagem(
        partes=partes, tamanho_declarado=subida.tamanho, teto_do_arquivo=TAMANHO_MAXIMO
    )
    try:
        blob.juntar_partes(subida.caminho, partes, TIPO_DA_PLANILHA)
    except Exception as erro:  # noqa: BLE001 - bloco ausente, expirado ou id errado
        raise RegraViolada(
            "Faltou alguma parte da planilha. Comece a subida de novo."
        ) from erro
    return subida, blob.ler(subida.caminho)


def concluir(subida: PlanilhaDeBondsRecebida, *, tamanho: int) -> None:
    """Marca a subida como completa, com o tamanho REAL do arquivo montado.

    O declarado é afirmação do cliente e serve para dimensionar os tetos; o que
    fica gravado é o que o arquivo tem.
    """
    subida.tamanho = tamanho
    subida.completa_em = datetime.now().astimezone()


def recuperar(
    sessao: Session, *, subida_id: UUID, usuario_id: UUID
) -> tuple[PlanilhaDeBondsRecebida, bytes]:
    """A planilha já montada daquela pessoa, para a importação.

    SÓ QUEM CONFERIU IMPORTA, e é a mesma razão de `criado_por` existir: sem a
    condição do dono, conhecer o id bastaria para importar o arquivo de outra
    pessoa com a própria sessão.

    AINDA SUBINDO É RECUSA, e não leitura: o arquivo não existe até
    `juntar_partes`, e ler um que está pela metade daria "não consegui abrir a
    planilha" para quem não fez nada errado.
    """
    subida = sessao.scalar(
        select(PlanilhaDeBondsRecebida).where(
            PlanilhaDeBondsRecebida.id == subida_id,
            PlanilhaDeBondsRecebida.criado_por == usuario_id,
        )
    )
    if subida is None or subida.subindo:
        raise NaoEncontrado(
            "Não encontrei esta planilha. Confira o arquivo de novo."
        )
    return subida, blob.ler(subida.caminho)


def descartar(sessao: Session, *, subida_id: UUID, usuario_id: UUID) -> str | None:
    """Apaga a linha MONTADA e devolve o caminho do byte, para quem chama apagá-lo.

    DEVOLVE O CAMINHO em vez de apagar aqui: apagar byte é ida à rede, e ela não
    pertence à transação — quem chama põe numa tarefa de fundo, como a abertura
    faz com o substituído.

    SÓ A JÁ MONTADA. Pela rota não há como chegar aqui com uma subida em voo,
    porque `recuperar` roda antes e a recusa; mas esta é função pública de caso
    de uso, e sem a guarda ela apagaria a subida que outra aba da mesma pessoa
    está no meio de enviar. Guarda que depende da ordem das chamadas é guarda
    que o próximo refator desfaz.
    """
    subida = sessao.scalar(
        select(PlanilhaDeBondsRecebida).where(
            PlanilhaDeBondsRecebida.id == subida_id,
            PlanilhaDeBondsRecebida.criado_por == usuario_id,
            PlanilhaDeBondsRecebida.completa_em.is_not(None),
        )
    )
    if subida is None:
        return None
    caminho = subida.caminho
    sessao.delete(subida)
    return caminho
