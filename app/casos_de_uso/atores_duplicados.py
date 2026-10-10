"""O mesmo ator cadastrado duas vezes — a fila, e a fusão.

A DECISÃO DE NEGÓCIO. "O Valor Econômico é uma empresa grande que está na base
de imprensa; caso tenhamos Valor Econômico no CRM, empresa e rede social, vamos
consultar o mesmo perfil?" — "deveria ser um único cadastro que vem de Cadastro
compartilhado".

TRÊS CAMADAS, e cada uma faz o que a anterior não pode:

1. A INGESTÃO não cria mais o par: `veiculos_da_imprensa.reconhecer` procura em
   qualquer tipo quando quem fala é perfil de rede.
2. A `0077` fundiu os 30 HOMÔNIMOS EXATOS que a versão antiga gravou — nome
   igual por `nome_normalizado` não pede julgamento.
3. ESTE MÓDULO cuida dos que sobraram: ~66 pares que só casam depois de tirar
   pontuação e espaço. Ali a semelhança NÃO prova identidade — `Diário SM` e
   `Diários M` casam assim, e `bmc.news` casa com DOIS veículos —, então quem
   decide é gente, e o que a pessoa decidir fica guardado.

A CHAVE DA COMPARAÇÃO é `nome_normalizado` sem nada que não seja letra ou
dígito: o fornecedor de redes escreve o handle (`valoreconomico`, `bmc.news`,
`gazeta_de_piracicaba`) e o clipping escreve o nome (`Valor Econômico`). É uma
regra de BUSCA, para montar a fila de perguntas — nunca de gravação.

O QUE ESTE MÓDULO NÃO FAZ: fundir sozinho. Juntar dois dossiês não tem volta.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_score import Mencao
from app.banco.tabelas_stakeholders import AtorDistinto, Instituicao, Interlocutor
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.texto import normalizar

_SO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")

#: O TIPO QUE A FILA OLHA. O par nasce da ingestão de redes sociais: é o perfil
#: que chega com o handle do fornecedor e vira cadastro novo. Dois veículos de
#: imprensa com nomes parecidos são outra conversa — essa base é curada à mão.
TIPO_DE_ORIGEM = "perfil_rede"


def achatar_para_comparar(nome: str) -> str:
    """A chave de SEMELHANÇA: `Valor Econômico` e `valoreconomico` coincidem.

    Não é `normalizar`, e a diferença é o ponto: `normalizar` é a chave de
    GRAVAÇÃO, que carrega a unicidade do cadastro, e nela `valoreconomico` e
    `valor economico` são dois cadastros legítimos. Aqui o espaço e a pontuação
    saem para a pergunta ser feita, e a resposta é de gente.
    """
    return _SO_ALFANUMERICO.sub("", normalizar(nome))


@dataclass(frozen=True)
class Candidato:
    """Um cadastro que PODE ser o mesmo ator do perfil."""

    id: uuid.UUID
    nome: str
    tipo: str
    mencoes: int


@dataclass(frozen=True)
class Duplicado:
    """Um perfil de rede e os cadastros com que ele se parece."""

    id: uuid.UUID
    nome: str
    cargo: str | None
    mencoes: int
    candidatos: tuple[Candidato, ...]


def _mencoes_por_instituicao(sessao: Session) -> dict[uuid.UUID, int]:
    linhas = sessao.execute(
        select(Mencao.instituicao_id, func.count())
        .where(Mencao.instituicao_id.is_not(None))
        .group_by(Mencao.instituicao_id)
    )
    return {instituicao: quantas for instituicao, quantas in linhas}


def listar(sessao: Session) -> list[Duplicado]:
    """A fila de perguntas: perfis que se parecem com outro cadastro.

    FORA DA FILA, e cada exclusão por um motivo diferente:

    * o HOMÔNIMO EXATO, que a `0077` já fundiu e que a ingestão não recria —
      se aparecer um, é regressão, e a `0077` roda de novo;
    * o par que alguém JÁ DECIDIU que é outro ator (`ator_distinto`) — sem
      isso a fila nunca chega a zero;
    * o perfil LIGADO A UMA PESSOA do CRM, porque o sobrevivente não pode
      herdar a ligação (CHECK `instituicao_pessoa_so_de_perfil`) e desfazer
      escolha humana não é fusão, é perda.

    EM MEMÓRIA, e não em SQL: a chave de semelhança é a mesma função que a
    ingestão usa, e reescrevê-la em `regexp_replace` seria a terceira cópia da
    mesma regra — o jeito conhecido de divergir em silêncio. O cadastro todo
    são ~3.800 linhas de duas colunas.
    """
    #: O CADASTRO ATIVO INTEIRO. Quem fica de fora da fila fica de fora no
    #: laço abaixo, onde a razão de cada exclusão está escrita.
    cadastros = list(
        sessao.scalars(select(Instituicao).where(Instituicao.ativo.is_(True)))
    )
    por_chave: dict[str, list[Instituicao]] = {}
    for cadastro in cadastros:
        por_chave.setdefault(achatar_para_comparar(cadastro.nome), []).append(cadastro)

    decididos = {
        (par.esquerda, par.direita) for par in sessao.scalars(select(AtorDistinto))
    }
    mencoes = _mencoes_por_instituicao(sessao)

    fila: list[Duplicado] = []
    for grupo in por_chave.values():
        if len(grupo) < 2:
            continue
        for perfil in grupo:
            if perfil.tipo != TIPO_DE_ORIGEM or perfil.interlocutor_id is not None:
                continue
            candidatos = tuple(
                Candidato(
                    id=outro.id,
                    nome=outro.nome,
                    tipo=outro.tipo,
                    mencoes=mencoes.get(outro.id, 0),
                )
                for outro in grupo
                if outro.id != perfil.id
                #: O HOMÔNIMO EXATO não é pergunta: é a `0077`.
                and outro.nome_normalizado != perfil.nome_normalizado
                and ordenar_o_par(perfil.id, outro.id) not in decididos
                and _esta_do_lado_que_pergunta(perfil, outro, mencoes)
            )
            if candidatos:
                fila.append(
                    Duplicado(
                        id=perfil.id,
                        nome=perfil.nome,
                        cargo=perfil.cargo,
                        mencoes=mencoes.get(perfil.id, 0),
                        candidatos=tuple(
                            sorted(candidatos, key=lambda c: -c.mencoes)
                        ),
                    )
                )
    return sorted(fila, key=lambda d: d.nome.lower())


def _esta_do_lado_que_pergunta(
    perfil: Instituicao, outro: Instituicao, mencoes: dict[uuid.UUID, int]
) -> bool:
    """A pergunta aparece UMA VEZ, e ancorada em quem vai sumir.

    Quando os dois lados são perfil de rede, os dois cabem no papel de "quem
    pergunta" — e a fila trazia a mesma dúvida duas vezes, em dois pontos da
    lista alfabética (`AC 24 Horas → ac24horas` e `ac24horas → AC 24 Horas`).
    Responder uma resolve as duas, mas quem abre a tela lê o dobro do trabalho
    que existe, e o contador mente: 144 linhas para ~100 perguntas.

    A ORIENTAÇÃO É A DA FUSÃO: âncora é quem vai sumir, e quem vai sumir é o
    lado com MENOS menções — a linha com história sobrevive. Empate desempata
    pelo nome, para a escolha não trocar de lado entre duas aberturas da tela.

    Com um cadastro de outro tipo do outro lado não há escolha: só o perfil de
    rede entra em outro cadastro, e a pergunta nasce dele.
    """
    if outro.tipo != TIPO_DE_ORIGEM:
        return True
    return (mencoes.get(perfil.id, 0), perfil.nome) < (
        mencoes.get(outro.id, 0),
        outro.nome,
    )


def ordenar_o_par(um: uuid.UUID, outro: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """O par sem lado, sempre na mesma ordem.

    Dizer que A é diferente de B é dizer que B é diferente de A. Guardado
    ordenado, é a chave primária que recusa a repetição — a aplicação não
    procura nas duas direções. Ver migration `0078`.
    """
    return (um, outro) if str(um) < str(outro) else (outro, um)


def _buscar(sessao: Session, qual: uuid.UUID) -> Instituicao:
    registro = sessao.get(Instituicao, qual)
    if registro is None:
        raise NaoEncontrado("Cadastro nao encontrado.")
    return registro


def fundir(
    sessao: Session, *, perfil_id: uuid.UUID, sobrevivente_id: uuid.UUID
) -> Instituicao:
    """O perfil de rede entra no cadastro que fica, com as menções dele.

    QUEM SOBREVIVE É ESCOLHA DE QUEM CHAMA, e na tela é o veículo: ele é a
    linha curada, com categoria, subcategoria, UF e frente, e o nome dele é o
    escrito por gente ("UOL") contra o handle do fornecedor ("Uol"). Mas quem
    some é sempre o PERFIL, e é por isso que o parâmetro tem nome: fundir um
    veículo com 86 menções dentro de um perfil com 2 seria perder a curadoria,
    e é um gesto que esta função não oferece.

    O QUE SE PERDE, dito em voz alta: o `cargo` do perfil, porque o CHECK
    `instituicao_cargo_so_de_perfil` existe de propósito — um jornal não tem
    cargo, e o tipo `veiculo` já afirma o que "Imprensa" dizia.
    """
    if perfil_id == sobrevivente_id:
        raise RegraViolada("Um cadastro nao funde com ele mesmo.")

    perfil = _buscar(sessao, perfil_id)
    sobrevivente = _buscar(sessao, sobrevivente_id)

    if perfil.tipo != TIPO_DE_ORIGEM:
        raise RegraViolada(
            "So o perfil de rede entra em outro cadastro. Para o contrario, "
            "funda o perfil no cadastro que fica."
        )
    if perfil.interlocutor_id is not None:
        raise RegraViolada(
            "Este perfil esta ligado a uma pessoa do CRM. Desfaca a ligacao "
            "antes de fundir, ou funda no cadastro da pessoa."
        )

    #: AS MENÇÕES PASSAM: o dossiê do ator fica num só lugar.
    sessao.execute(
        Mencao.__table__.update()
        .where(Mencao.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    #: E O QUE MAIS APONTA PARA INSTITUIÇÃO — sem isto a exclusão bate na chave
    #: estrangeira e a fusão morre no meio.
    sessao.execute(
        Interlocutor.__table__.update()
        .where(Interlocutor.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    sessao.execute(
        InteracaoRegistro.__table__.update()
        .where(InteracaoRegistro.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    sessao.delete(perfil)
    sessao.flush()
    return sobrevivente


def declarar_distintos(
    sessao: Session,
    *,
    um: uuid.UUID,
    outro: uuid.UUID,
    motivo: str | None = None,
    decidido_por: uuid.UUID | None = None,
) -> AtorDistinto:
    """"São atores diferentes" — tira o par da fila e guarda o que se soube."""
    if um == outro:
        raise RegraViolada("Um cadastro nao e distinto de si mesmo.")
    _buscar(sessao, um)
    _buscar(sessao, outro)

    esquerda, direita = ordenar_o_par(um, outro)
    ja = sessao.get(AtorDistinto, (esquerda, direita))
    if ja is not None:
        #: IDEMPOTENTE: clicar duas vezes não é erro, e o motivo mais novo vale.
        if motivo is not None:
            ja.motivo = motivo
        return ja

    par = AtorDistinto(
        esquerda=esquerda, direita=direita, motivo=motivo, decidido_por=decidido_por
    )
    sessao.add(par)
    sessao.flush()
    return par
