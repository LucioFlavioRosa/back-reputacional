"""Registro de geração de relatório, e o histórico.

NÃO existe rota que devolva um PDF. O documento sai da impressão do navegador
sobre um layout próprio, que a tela já tem; o que faltava era saber que ele
existiu. Ver `dominio/relatorio.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.api.dependencias import (
    UsuarioLogado,
    obter_usuario_atual,
)
from app.api.interacoes import obter_recorte
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso import registrar_relatorio
from app.dominio.recorte import Recorte

rotas = APIRouter(
    prefix="/api/relatorios",
    tags=["relatorios"],
    dependencies=[Depends(obter_usuario_atual)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido
RecorteAtual = Annotated[Recorte, Depends(obter_recorte)]


class GeracaoEntrada(BaseModel):
    #: Só as seções. O recorte vem da query string, pela MESMA dependência que
    #: a listagem usa — receber os filtros no corpo abriria a porta para o
    #: relatório registrar um recorte e contar outro.
    secoes: list[str]


class GeracaoSaida(BaseModel):
    id: str
    criado_em: str
    total_de_registros: int
    leva_registros: bool


class HistoricoSaida(BaseModel):
    id: str
    criado_em: str
    criado_por: str
    secoes: list[str]
    total_de_registros: int
    leva_registros: bool
    formato: str
    resumo_do_recorte: str


@rotas.post("", status_code=status.HTTP_201_CREATED)
def registrar(
    sessao: Sessao,
    usuario: UsuarioLogado,
    recorte: RecorteAtual,
    entrada: GeracaoEntrada,
) -> GeracaoSaida:
    """Registra que um relatório foi gerado.

    A tela chama isto ANTES de montar a prévia. É trilha, não permissão: um
    cliente modificado simplesmente não chama, e nada é registrado. Serve para
    responsabilização entre pessoas da casa e como insumo de alerta — não como
    barreira.
    """
    relatorio = registrar_relatorio.registrar(
        sessao,
        # Deduplica preservando a ordem: `["base"] * 500` passaria pela
        # validação de vocabulário e gravaria um JSONB inchado, poluindo o
        # histórico que a coluna existe para tornar legível.
        secoes=tuple(dict.fromkeys(entrada.secoes)),
        recorte=recorte,
        usuario=usuario,
    )
    return GeracaoSaida(
        id=str(relatorio.id),
        criado_em=relatorio.criado_em.isoformat(),
        total_de_registros=relatorio.total_de_registros,
        leva_registros=relatorio.leva_registros,
    )


@rotas.post("/exportacoes", status_code=status.HTTP_201_CREATED)
def registrar_exportacao(
    sessao: Sessao, usuario: UsuarioLogado, recorte: RecorteAtual
) -> GeracaoSaida:
    """Registra uma exportação CSV da tela Base.

    Era o buraco que o plano de segurança listava desde o começo: "Export CSV —
    quem exportou, qual recorte, quantas linhas". O CSV é montado no navegador a
    partir da listagem já baixada, e saía sem evento nenhum — um botão, um
    arquivo, o recorte inteiro.

    Diferente do relatório impresso, o CSV **não corta**: leva tudo que o
    recorte alcança. É o caminho mais curto para tirar dados daqui, e o que mais
    merece o alerta.

    Vale a mesma ressalva de sempre: é trilha, não barreira. Um cliente
    modificado baixa a listagem e monta o arquivo sem chamar isto.
    """
    relatorio = registrar_relatorio.registrar(
        sessao,
        secoes=("base",),
        recorte=recorte,
        usuario=usuario,
        formato="csv",
    )
    return GeracaoSaida(
        id=str(relatorio.id),
        criado_em=relatorio.criado_em.isoformat(),
        total_de_registros=relatorio.total_de_registros,
        leva_registros=relatorio.leva_registros,
    )


@rotas.get("/historico")
def historico(
    sessao: Sessao,
    usuario: UsuarioLogado,
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[HistoricoSaida]:
    """O que foi gerado, por quem. Exige `administra_acessos`."""
    return [
        HistoricoSaida(
            id=str(linha.id),
            criado_em=linha.criado_em.isoformat(),
            criado_por=linha.criado_por,
            secoes=list(linha.secoes),
            total_de_registros=linha.total_de_registros,
            leva_registros=linha.leva_registros,
            formato=linha.formato,
            resumo_do_recorte=linha.resumo_do_recorte,
        )
        for linha in registrar_relatorio.historico(sessao, solicitante=usuario, limite=limite)
    ]
