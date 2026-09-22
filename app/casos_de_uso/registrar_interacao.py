"""Caso de uso: registrar uma nova interação."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.repositorio_interacoes import RepositorioSQL
from app.banco.tabelas_interacoes import Arquivo, Material
from app.banco.tabelas_stakeholders import Instituicao
from app.dominio.erros import NaoEncontrado
from app.dominio.identidade import UsuarioAtual
from app.dominio.interacao import Interacao
from app.dominio.repositorio import (
    RepositorioDeInteracoes,
)


def registrar(
    repositorio: RepositorioDeInteracoes,
    *,
    interacao: Interacao,
    usuario: UsuarioAtual,
) -> Interacao:
    """Grava a interação em nome de quem está logado.

    Qualquer perfil que chegue até aqui já passou por `exigir_escrita`; a
    autoria é definida aqui e não vem do cliente, para que ninguém registre em
    nome de outra pessoa.
    """
    interacao.criado_por = usuario.id
    interacao.revalidar()
    return repositorio.adicionar(interacao)


def _caminho_do_anexo(
    sessao: Session, interacao: Interacao, *, momento: str, arquivo_id: UUID, nome: str
) -> str:
    """A ÁRVORE DEPENDE DO QUE A INTERAÇÃO É.

    Material de agenda mora na pasta da agenda, porque quem o procura chega
    pelo registro e já tem o link. O anexo de uma consulta recebida é
    procurado pelo contêiner — por mês, por quem mandou —, e por isso ganha
    árvore própria. Ver `blob.caminho_da_consulta`.
    """
    if interacao.consulta is None:
        return blob.caminho_do_arquivo(
            interacao_id=interacao.id,
            momento=momento,
            arquivo_id=arquivo_id,
            nome=nome,
        )

    instituicao = sessao.scalar(
        select(Instituicao.nome).where(Instituicao.id == interacao.instituicao_id)
    )
    return blob.caminho_da_consulta(
        data=interacao.data_interacao,
        # Sem nome de instituição o caminho ainda precisa existir: o byte não
        # pode ficar sem casa porque um cadastro sumiu.
        instituicao=instituicao or "sem-instituicao",
        consulta_id=interacao.id,
        arquivo_id=arquivo_id,
        nome=nome,
    )


def guardar_arquivo(
    repositorio: RepositorioSQL,
    sessao: Session,
    *,
    interacao: Interacao,
    momento: str,
    nome: str,
    tipo_conteudo: str,
    dados: bytes,
    usuario: UsuarioAtual,
) -> Arquivo:
    """Grava a linha e sobe o byte, nesta ordem.

    A LINHA PRIMEIRO, E O BYTE DEPOIS. É o inverso do que a intuição sugere,
    e é o único jeito de o pior caso ser recuperável.

    Byte antes, linha depois: se a gravação falhar, o byte fica no contêiner
    sem ninguém que o conheça — invisível e pago para sempre.

    Linha antes, byte depois: se o upload falhar, a transação volta atrás e a
    linha some junto. Nada sobra.

    O `id` da linha entra no caminho do blob, então ele precisa existir antes
    de o byte subir — o que faz a ordem certa ser também a única possível.
    """
    arquivo = Arquivo(
        # Caminho ainda vazio: ele depende do `id`, que o `flush` atribui.
        caminho="",
        nome=nome,
        tipo_conteudo=tipo_conteudo,
        tamanho=len(dados),
        criado_por=usuario.id,
    )
    sessao.add(arquivo)
    sessao.flush()

    arquivo.caminho = _caminho_do_anexo(
        sessao, interacao, momento=momento, arquivo_id=arquivo.id, nome=nome
    )
    sessao.flush()

    blob.guardar(arquivo.caminho, dados, tipo_conteudo)
    return arquivo


def arquivo_da_interacao(
    repositorio: RepositorioSQL, *, interacao_id: UUID, arquivo_id: UUID
) -> Arquivo:
    """O arquivo, se ele for MESMO desta agenda.

    Conferir o vínculo é o que impede que conhecer dois uuids baste para baixar
    o anexo de uma agenda que a pessoa não pode ver: o escopo já foi checado
    contra `interacao_id`, e sem esta verificação o `arquivo_id` escaparia dele.
    """
    arquivo = repositorio.sessao.scalars(
        select(Arquivo)
        .join(Material, Material.arquivo_id == Arquivo.id)
        .where(Arquivo.id == arquivo_id, Material.interacao_id == interacao_id)
    ).first()
    if arquivo is None:
        raise NaoEncontrado("Arquivo não encontrado nesta agenda.")
    return arquivo


def apagar_bytes_orfaos(repositorio: RepositorioSQL) -> None:
    """Apaga do blob o que perdeu a linha. Chamada DEPOIS do commit.

    Falha aqui não desfaz nada: o dado já está consistente, e o que resta é um
    byte que ninguém alcança. Por isso engole o erro em vez de propagá-lo —
    devolver 500 para quem acabou de salvar com sucesso seria mentir sobre o
    que aconteceu.
    """
    for caminho in repositorio.caminhos_orfaos():
        try:
            blob.apagar(caminho)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Byte órfão não apagado: %s. A linha já saiu do banco; "
                "o arquivo continua ocupando espaço no contêiner.",
                caminho,
            )
