"""A Consulta em profundidade de uma lente, pronta para a tela do drill.

O FRONT JÁ TEM A TELA (Lente › Pilar › Tema › Subtema › Matérias) e lia um JSON
ilustrativo. Este endpoint devolve O MESMO FORMATO (`Dados` de
`front-reputacional/src/paginas/score/consulta/dados/tipos.ts`, em camelCase),
com UMA lente em `lentes` — a da aba aberta. Assim `resolverCaminho` e os quatro
níveis funcionam sem mudar de forma; a tela só troca de onde lê.

MÓDULO PRÓPRIO, E NÃO MAIS UMA ROTA EM `lentes.py`: aquele arquivo é o dossiê
(2.000+ linhas de blocos, fichas e sinais) e esta resposta não compartilha nada
com ele além do prefixo. O prefixo é o mesmo de propósito: a consulta É da lente,
e `/api/score/lentes/{codigo}/consulta` fica ao lado de `/dossie` e `/recorte`.

A ROTA SÓ LÊ E ENTREGA. Toda conta e toda frase moram em
`dominio.consulta_profundidade` e `dominio.frases_da_consulta`, puros — é lá que
os testes provam o fechamento, o arredondamento e cada frase.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencias import UsuarioLogado, exigir_portal_score
from app.api.score import _mes_de
from app.banco import repositorio_lentes, repositorio_score
from app.banco.sessao import SessaoDoPedido
from app.dominio.consulta_profundidade import (
    LENTES_DA_CONSULTA,
    MESES_DA_CONSULTA,
    LenteDaConsulta,
    montar_consulta,
)
from app.dominio.erros import NaoEncontrado

rotas = APIRouter(
    prefix="/api/score/lentes",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido


@rotas.get("/{codigo}/consulta")
def obter_consulta(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> dict:
    """A árvore do mês: pilares, temas, subtemas e uma amostra das matérias.

    SÓ IMPRENSA E MERCADO. As outras lentes não são matérias da Clipei com pilar
    por linha — redes, canais próprios e o CRM —, e responder com uma árvore
    vazia faria a tela parecer quebrada em vez de dizer que a pergunta não se
    aplica. Por isso é 404, como lente inexistente.

    UM NÚMERO FIXO DE LEITURAS, qualquer que seja o tamanho da árvore: as linhas
    do mês da tela, os grupos dos cinco meses anteriores (já somados no banco),
    três da taxonomia e três do agregado — nada aqui consulta o banco por nó.
    """
    alvo = _mes_de(mes)
    if codigo not in LENTES_DA_CONSULTA:
        raise NaoEncontrado("A consulta em profundidade existe só para Imprensa e Mercado.")
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")

    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_lentes.meses_ate(alvo, MESES_DA_CONSULTA)
    medidas = repositorio_score.meses_da_lente(sessao, lente, meses, calibracao)
    mencoes = repositorio_score.mencoes_da_consulta(sessao, lente.id, alvo, calibracao)
    grupos = repositorio_score.grupos_da_consulta(
        sessao,
        lente.id,
        [m for m in meses if m != alvo],
        calibracao,
        {m: medida.regua for m, medida in medidas.items()},
    )
    taxonomia = repositorio_lentes.taxonomia_ativa(sessao)

    # O PESO É A FRAÇÃO DO ÍNDICE, de 0 a 1, como no JSON da tela: o peso da
    # calibração sobre a soma de todos. Uma lente sem dado no mês continua
    # dividindo o bolo aqui — a redistribuição do ISR é do índice, não da lente.
    soma_dos_pesos = sum(calibracao.pesos.values())
    peso = calibracao.peso(lente.codigo, lente.peso_padrao)
    return montar_consulta(
        lente=LenteDaConsulta(
            codigo=lente.codigo,
            nome=lente.nome,
            peso=peso / soma_dos_pesos if soma_dos_pesos else 0.0,
        ),
        mes=alvo,
        meses=meses,
        mencoes=mencoes,
        grupos=grupos,
        medidas=medidas,
        taxonomia=taxonomia,
        calibracao=calibracao,
        ve_diretorio=usuario.ve_diretorio,
    )
