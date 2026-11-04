"""A fila do mesmo ator cadastrado duas vezes, e as duas respostas.

Módulo separado porque `stakeholders.py` já passa de 900 linhas e isto é um
assunto fechado: a fila, a fusão, e o "são atores diferentes". A regra mora em
`app/casos_de_uso/atores_duplicados.py`; aqui só entram o contrato HTTP e a
permissão.

PERMISSÃO DE ADMINISTRAR CADASTROS nas duas escritas, e não a de escrita comum:
fundir junta dois dossiês e apaga uma linha do catálogo — não tem volta.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioQueAdministraCadastros,
    UsuarioQueVeDiretorio,
    exigir_diretorio,
    exigir_portal_crm,
)
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import atores_duplicados

#: PREFIXO `/api`, e os caminhos escritos por extenso: as duas escritas moram
#: em endereços diferentes de propósito. Ver `declarar_distinto`.
#:
#: AS MESMAS DUAS DEPENDÊNCIAS DO ROUTER DOS STAKEHOLDERS, e por isso aqui no
#: router e não em cada rota: a resposta nomeia atores do mapa de
#: relacionamento da Aegea — todo jornalista e veículo com quem a companhia
#: fala —, e isso vale para a fila tanto quanto para a listagem. Quem apontou
#: foi `test_toda_rota_sob_prefixo_do_crm_exige_o_portal`, que varre a
#: aplicação montada: rota nova sob `/api/instituicoes` sem o portal é rota
#: desprotegida, venha do router que vier.
rotas = APIRouter(
    prefix="/api",
    tags=["stakeholders"],
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_diretorio)],
)


class CandidatoSaida(BaseModel):
    id: UUID
    nome: str
    tipo: str
    #: QUANTAS MENÇÕES este lado carrega. É o número que diz qual dos dois é a
    #: linha com história — e, na tela, qual deve sobreviver.
    mencoes: int
    #: DE ONDE VÊM OS REGISTROS DESTE LADO: códigos de lente, e `crm`. É a
    #: evidência que explica a duplicata — um chegou pelo clipping, o outro pelo
    #: social listening, e é o mesmo ator.
    origens: list[str] = []


class DuplicadoSaida(BaseModel):
    id: UUID
    nome: str
    #: O TIPO DE QUEM VAI SAIR. A tela escrevia "Perfil de rede" fixo, e com a fila
    #: aberta a todos os tipos isso passou a ser mentira para os pares do CRM.
    tipo: str
    cargo: str | None
    mencoes: int
    candidatos: list[CandidatoSaida]
    #: Ver `CandidatoSaida.origens`.
    origens: list[str] = []


class FusaoEntrada(BaseModel):
    #: QUEM FICA. Quem SAI vem na URL — ver `fundir`.
    #:
    #: QUALQUER CADASTRO PODE SAIR, porque a fila pergunta sobre qualquer tipo.
    #: A assimetria que protege a curadoria vem da ORDEM DA FILA —
    #: `_esta_do_lado_que_pergunta` ancora a pergunta em quem deve sair — e não
    #: de um `if` de tipo no servidor.
    sobrevivente_id: UUID
    #: "O CADASTRO CERTO É ESTE", dito de propósito contra a proposta da fila.
    #:
    #: A fila propõe quem sai (o perfil cru antes do curado, depois quem tem
    #: menos menções) e o servidor recusa o inverso — é o que impede fundir a
    #: linha com história dentro da linha crua por um clique errado. Mas só quem
    #: conhece o ator sabe quando o cadastro certo é o outro, e é esta bandeira
    #: que deixa a pessoa dizer qual é o real.
    #:
    #: FALSO POR PADRÃO, e é isso que mantém a proteção: quem não disser nada
    #: continua levando 422 na direção inversa.
    contra_a_proposta: bool = False


class DistintosEntrada(BaseModel):
    um_id: UUID
    outro_id: UUID
    motivo: str | None = None


@rotas.get("/instituicoes/duplicados", response_model=list[DuplicadoSaida])
def listar_duplicados(
    sessao: SessaoDoPedido, usuario: UsuarioQueVeDiretorio
) -> list[atores_duplicados.Duplicado]:
    """Os cadastros que podem ser o mesmo ator.

    QUALQUER TIPO, e não só perfil de rede: o mesmo ator chega por rede social,
    por reunião de investimento e por imprensa, e continua sendo um só.

    LEITURA COM A PERMISSÃO DO DIRETÓRIO, como as outras listagens de cadastro:
    a resposta nomeia atores do mapa de relacionamento da Aegea.
    """
    return atores_duplicados.listar(sessao)


class EstadoDaFilaSaida(BaseModel):
    """Quando o pareamento foi refeito — e se já foi alguma vez.

    EXISTE PARA A TELA NÃO MENTIR. O pareamento é guardado (`0118`) para a fila
    não ser recalculada a cada abertura, que era a causa do 504. O preço é que a
    tabela nasce vazia, e fila vazia não se distingue de "nenhum duplicado": sem
    este estado, a tela diria "Possíveis duplicados (0)" num cadastro cheio de
    duplicatas.
    """

    #: NULO significa NUNCA CALCULADO, e a tela tem de dizer isso em vez de zero.
    calculado_em: datetime | None
    #: O CADASTRO MUDOU DEPOIS DO ÚLTIMO PAREAMENTO. Verdadeiro também quando
    #: nunca calculou.
    #:
    #: EXISTE PORQUE O RECÁLCULO NÃO ESTÁ EM TODO ESCRITOR: a subida o dispara,
    #: mas criar pela tela de cadastro, confirmar agendas ou rodar o comando de
    #: cadastro externo não. Pendurar um gancho em cada um é a lista que o próximo
    #: esquece; comparar a impressão do cadastro pega todos — e a tela diz "pode
    #: haver duplicado novo" em vez de calar.
    desatualizado: bool


@rotas.get("/instituicoes/duplicados/estado", response_model=EstadoDaFilaSaida)
def estado_da_fila(
    sessao: SessaoDoPedido, usuario: UsuarioQueVeDiretorio
) -> EstadoDaFilaSaida:
    """Se a fila já foi calculada, e quando.

    ROTA PRÓPRIA E NÃO UM CAMPO NA LISTAGEM: a listagem devolve uma lista, e
    embrulhá-la num objeto para caber mais um campo mudaria o contrato de um
    consumidor que já existe. Esta é barata — um `max` sobre a chave primária.

    ANTES DE `/duplicados` NO ARQUIVO, e isso não é acidente: `/duplicados` não
    tem parâmetro de rota, então não há captura a disputar — mas manter a mais
    específica em cima é o que evita o problema no dia em que houver.
    """
    return EstadoDaFilaSaida(
        calculado_em=atores_duplicados.calculado_em(sessao),
        desatualizado=atores_duplicados.esta_desatualizado(sessao),
    )


@rotas.post("/instituicoes/{que_sai_id}/fundir", status_code=200)
def fundir_cadastro(
    sessao: SessaoDoPedido,
    usuario: UsuarioQueAdministraCadastros,
    que_sai_id: UUID,
    entrada: FusaoEntrada,
) -> dict[str, str]:
    """Quem vem na URL SAI; quem vem no corpo fica.

    O NOME DO PARÂMETRO DE ROTA NÃO É PARTE DA URL, então renomeá-lo de `perfil_id`
    para `que_sai_id` não muda o endereço — `/api/instituicoes/<uuid>/fundir`
    continua igual, e o front não precisa de mudança. O que muda é o que o nome
    promete a quem lê.
    """
    sobrevivente = atores_duplicados.fundir(
        sessao,
        que_sai_id=que_sai_id,
        sobrevivente_id=entrada.sobrevivente_id,
        contra_a_proposta=entrada.contra_a_proposta,
    )
    return {"id": str(sobrevivente.id), "nome": sobrevivente.nome}


@rotas.post("/atores-distintos", status_code=200)
def declarar_distinto(
    sessao: SessaoDoPedido,
    usuario: UsuarioQueAdministraCadastros,
    entrada: DistintosEntrada,
) -> dict[str, bool]:
    """"Não é o mesmo ator" — tira o par da fila, para sempre.

    FORA DE `/api/instituicoes/` de propósito. O front recarrega o catálogo
    inteiro a cada escrita numa rota de catálogo, casando por prefixo — e esta
    decisão não muda cadastro nenhum. A fusão, que muda, fica lá e dispara a
    recarga sozinha.
    """
    atores_duplicados.declarar_distintos(
        sessao,
        um=entrada.um_id,
        outro=entrada.outro_id,
        motivo=entrada.motivo,
        decidido_por=usuario.id,
    )
    return {"guardado": True}
