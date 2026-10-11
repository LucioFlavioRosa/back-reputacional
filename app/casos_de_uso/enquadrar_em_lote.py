"""Dar categoria de público a várias instituições de uma vez.

POR QUE ISTO EXISTE, e o número é o argumento: subir a planilha real de Relações
com Investidores criou 499 instituições, TODAS como "Entidade", porque a planilha
não traz categoria de público. A aba de revisão as lista e sabe dizer "Está
certo" sobre UMA linha por vez.

Mas a resposta para quase todas é a MESMA — são gestoras e bancos, e a categoria
é uma só. Quatrocentas e noventa e nove idas à lista de cadastro para digitar a
mesma coisa não é revisão: é a pessoa desistindo na décima e a base ficando
meio classificada, que é pior do que não classificada, porque ninguém sabe onde
parou.

O TIPO SAI DA CATEGORIA, e é o que torna este gesto mais do que preencher um
campo: `derivar_tipo` traduz categoria em tipo, e o tipo da instituição é o que
`derivar_frente` usa para dizer de que frente é cada agenda dela. Enquadrar 499
instituições reclassifica as agendas de todas elas.

SÓ O QUE ESTÁ NA FILA, e é a trava que mantém isto seguro. Um lote que pudesse
reescrever o tipo de qualquer instituição permitiria a um clique na aba de
revisão varrer a curadoria de 3.785 cadastros feitos à mão. O que está pendente
nasceu de planilha e ninguém conferiu — é exatamente o que este gesto serve. O
resto se edita um a um, onde a tela mostra o cadastro inteiro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso.derivar_tipo import derivar_tipo
from app.dominio.erros import RegraViolada
from app.dominio.frentes import ROTULO_DO_TIPO_DE_INSTITUICAO

#: QUANTAS INSTITUIÇÕES UM LOTE ACEITA.
#:
#: 500 porque a fila real tem 499, e o limite existe para haver um: sem ele, o
#: tamanho do pedido é decidido por quem o manda. Não é proteção contra abuso —
#: a rota exige `administra_dicionarios` —, é a diferença entre uma operação
#: cujo custo se conhece e uma que pode levar o tempo que quiser.
MAXIMO_DO_LOTE = 500


@dataclass(frozen=True)
class Recusado:
    """Uma instituição do lote que não pôde ser enquadrada, e por quê.

    O LOTE NÃO É TUDO-OU-NADA, e esta é a decisão de desenho mais importante
    daqui. Com 499 linhas, uma colisão de nome faria o lote inteiro falhar e a
    pessoa não teria como saber qual das 499. Enquadrar as que dão e DIZER quais
    não deram, com o motivo de cada uma, é o que permite o gesto acontecer.
    """

    id: str
    nome: str
    motivo: str


@dataclass(frozen=True)
class Resultado:
    enquadradas: int
    consolidadas: int
    #: O tipo que a categoria escolhida implica — o que a tela mostra de volta
    #: para a pessoa saber o que acabou de acontecer.
    tipo: str
    recusadas: list[Recusado] = field(default_factory=list)


def enquadrar(
    sessao: Session,
    *,
    ids: list[UUID],
    categoria_publico_id: int,
    subcategoria_publico_id: int | None,
    consolidar: bool,
) -> Resultado:
    """Grava a categoria nas instituições pedidas e deriva o tipo de todas.

    `consolidar` É ESCOLHA DE QUEM REVISA, e não consequência automática. Dar a
    categoria resolve o motivo que a fila mostrava — "entrou sem categoria de
    público" —, mas consolidar é afirmar que o cadastro está certo, e quem
    enquadra um lote de 499 pode querer que outra pessoa confira antes. É o mesmo
    princípio da consolidação uma a uma: ela sai por ação, não por um campo que
    ficou preenchido.
    """
    if not ids:
        raise RegraViolada("Nenhuma instituição foi escolhida.")
    if len(ids) > MAXIMO_DO_LOTE:
        raise RegraViolada(
            f"Um lote aceita até {MAXIMO_DO_LOTE} instituições, e vieram {len(ids)}. "
            "Divida a seleção."
        )

    #: O TIPO É DERIVADO UMA VEZ, e não por linha: a categoria é a mesma para
    #: todo o lote, então o tipo também é. `tipo=None` faz `derivar_tipo` usar a
    #: categoria, que é precisamente o que este caso de uso quer dizer.
    novo_tipo = derivar_tipo(
        sessao,
        tipo=None,
        categoria_publico_id=categoria_publico_id,
        atual=None,
    )

    pedidas = {
        linha.id: linha
        for linha in sessao.scalars(
            select(Instituicao).where(Instituicao.id.in_(ids))
        )
    }

    #: OS NOMES JÁ OCUPADOS NO TIPO DE DESTINO, numa consulta só.
    #:
    #: A `0002` cria `unique (nome_normalizado, tipo)` e o índice NÃO é parcial em
    #: `ativo`: uma instituição desativada continua ocupando o par. Sem esta
    #: conferência, mudar o tipo de 499 linhas estoura em `IntegrityError` no
    #: flush — 500 para a pessoa, e sem dizer qual nome colidiu.
    ocupados = {
        nome
        for nome, in sessao.execute(
            select(Instituicao.nome_normalizado).where(
                Instituicao.tipo == novo_tipo,
                Instituicao.id.notin_(list(pedidas)),
            )
        )
    }

    #: E AS COLISÕES DENTRO DO PRÓPRIO LOTE: duas pendências com o mesmo nome
    #: normalizado em tipos diferentes hoje passam a querer o MESMO par. É o caso
    #: que o dono do produto nomeou — "se o 'valor' for classificado como
    #: financeiro e em outro momento 'o valor' for registrado como veículo" —, e
    #: aqui ele deixa de ser hipótese: o lote é o que os junta.
    quantas_vezes: dict[str, int] = {}
    for linha in pedidas.values():
        quantas_vezes[linha.nome_normalizado] = (
            quantas_vezes.get(linha.nome_normalizado, 0) + 1
        )

    rotulo = ROTULO_DO_TIPO_DE_INSTITUICAO.get(novo_tipo, novo_tipo)
    recusadas: list[Recusado] = []
    enquadradas = 0
    consolidadas = 0

    for ident in ids:
        linha = pedidas.get(ident)
        if linha is None:
            recusadas.append(
                Recusado(str(ident), "—", "Esta instituição não existe mais.")
            )
            continue
        if not linha.pendente_de_revisao:
            #: JÁ CONSOLIDADA: fora do alcance do lote, pelo argumento do
            #: docstring do módulo. Pode ter sido outra pessoa revisando a mesma
            #: aba — a fila é trabalho de equipe por desenho.
            recusadas.append(
                Recusado(
                    str(linha.id),
                    linha.nome,
                    "Já foi consolidada — outra pessoa pode ter revisado. "
                    "Edite-a pela lista de cadastro.",
                )
            )
            continue
        if linha.nome_normalizado in ocupados:
            recusadas.append(
                Recusado(
                    str(linha.id),
                    linha.nome,
                    f"Já existe outra instituição com este nome do tipo "
                    f"{rotulo!r} — é possível duplicata. Resolva em "
                    f"'Possíveis duplicados'.",
                )
            )
            continue
        if quantas_vezes.get(linha.nome_normalizado, 0) > 1:
            recusadas.append(
                Recusado(
                    str(linha.id),
                    linha.nome,
                    f"Duas pendências têm este mesmo nome, e as duas ficariam do "
                    f"tipo {rotulo!r} — é possível duplicata. Resolva em "
                    f"'Possíveis duplicados' antes de enquadrar.",
                )
            )
            continue

        linha.categoria_publico_id = categoria_publico_id
        linha.subcategoria_publico_id = subcategoria_publico_id
        linha.tipo = novo_tipo
        enquadradas += 1
        #: O NOME PASSA A OCUPAR O PAR, para a segunda linha do lote com o mesmo
        #: nome não passar atrás da primeira. A contagem acima já pega o caso, e
        #: isto é o cinto: as duas conferências custam nada e o erro que elas
        #: evitam é um `IntegrityError` no flush.
        ocupados.add(linha.nome_normalizado)
        if consolidar:
            linha.pendente_de_revisao = False
            linha.motivo_da_revisao = None
            consolidadas += 1

    sessao.flush()
    return Resultado(
        enquadradas=enquadradas,
        consolidadas=consolidadas,
        tipo=novo_tipo,
        recusadas=recusadas,
    )
