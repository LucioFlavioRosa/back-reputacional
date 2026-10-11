"""Dar categoria de público a várias instituições de uma vez.

POR QUE ISTO EXISTE, e o número é o argumento: subir a planilha real de Relações
com Investidores encheu a aba "Instituições e Contatos" com 499 pendências, e
178 delas são INSTITUIÇÕES — todas como "Entidade", porque a planilha não traz
categoria de público. (As outras 321 são os contatos, que não têm esse campo.) A
aba de revisão as lista e sabe dizer "Está certo" sobre UMA linha por vez.

O NÚMERO ESTAVA ERRADO AQUI e eu o corrigi: eu havia escrito "499 instituições",
e 499 era o total da ABA, que junta duas tabelas. Medido na pilha depois de
subir o arquivo real: 178 instituições, e o lote enquadrou as 178 numa chamada,
sem nenhuma recusa, derivando o tipo `investidor`.

Mas a resposta para quase todas é a MESMA — são gestoras e bancos, e a categoria
é uma só. Cento e setenta e oito idas à lista de cadastro para digitar a mesma
coisa não é revisão: é a pessoa desistindo na décima e a base ficando meio
classificada, que é pior do que não classificada, porque ninguém sabe onde
parou.

O TIPO SAI DA CATEGORIA, e é o que torna este gesto mais do que preencher um
campo: `derivar_tipo` traduz categoria em tipo, e o tipo da instituição é o que
`derivar_frente` usa para dizer de que frente é cada agenda dela. Enquadrar as
178 reclassifica as agendas de todas elas — e no caso real a mudança é de
"Entidade" para "Investidor", numa planilha de Relações com Investidores.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import CategoriaPublico
from app.banco.tabelas_stakeholders import Instituicao
from app.casos_de_uso.derivar_tipo import derivar_tipo
from app.dominio.erros import RegraViolada
from app.dominio.frentes import (
    ROTULO_DO_TIPO_DE_INSTITUICAO,
    TIPO_DA_CATEGORIA_DE_PUBLICO,
)

#: QUANTAS INSTITUIÇÕES UM LOTE ACEITA.
#:
#: 500 com folga sobre as 178 que a fila real tem, e o limite existe para haver
#: um: sem ele, o
#: tamanho do pedido é decidido por quem o manda. Não é proteção contra abuso —
#: a rota exige `administra_dicionarios` —, é a diferença entre uma operação
#: cujo custo se conhece e uma que pode levar o tempo que quiser.
MAXIMO_DO_LOTE = 500


def _categorias_com_tipo(sessao: Session) -> set[int]:
    """Os ids das categorias ATIVAS que definem um tipo de instituição.

    LIDO DO BANCO cruzando com `TIPO_DA_CATEGORIA_DE_PUBLICO`, e não da constante
    sozinha: o mapa é por CÓDIGO e o pedido vem por id, então alguém tem de
    traduzir. Fazer isso aqui é o que permite a recusa dizer "esta categoria não
    define tipo" em vez de deixar `derivar_tipo` dizer "informe a categoria de
    público" — que é verdade no cadastro um a um e mentira num lote onde a
    categoria FOI informada. Achado de revisão.
    """
    codigos = {
        codigo for codigo, tipo in TIPO_DA_CATEGORIA_DE_PUBLICO.items() if tipo
    }
    return {
        ident
        for ident, in sessao.execute(
            select(CategoriaPublico.id).where(
                CategoriaPublico.codigo.in_(codigos),
                CategoriaPublico.ativo.is_(True),
            )
        )
    }


@dataclass(frozen=True)
class Recusado:
    """Uma instituição do lote que não pôde ser enquadrada, e por quê.

    O LOTE NÃO É TUDO-OU-NADA, e esta é a decisão de desenho mais importante
    daqui. Com 178 linhas, uma colisão de nome faria o lote inteiro falhar e a
    pessoa não teria como saber qual das 178. Enquadrar as que dão e DIZER quais
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
    enquadra um lote de 178 pode querer que outra pessoa confira antes. É o mesmo
    princípio da consolidação uma a uma: ela sai por ação, não por um campo que
    ficou preenchido.
    """
    if not ids:
        raise RegraViolada("Nenhuma instituição foi escolhida.")
    #: SEM REPETIDOS, preservando a ordem do pedido.
    #:
    #: A ORDEM IMPORTA porque é a ordem em que as recusas voltam, e a tela as lê
    #: de cima para baixo. E a deduplicação SUBSTITUI um "cinto" que eu havia
    #: posto no laço — achado de revisão: ele "sugeria uma proteção que não
    #: resolve concorrência", e o id repetido era o único caso que ele cobria.
    ids = list(dict.fromkeys(ids))
    if len(ids) > MAXIMO_DO_LOTE:
        raise RegraViolada(
            f"Um lote aceita até {MAXIMO_DO_LOTE} instituições, e vieram {len(ids)}. "
            "Divida a seleção."
        )

    #: O TIPO É DERIVADO UMA VEZ, e não por linha: a categoria é a mesma para
    #: todo o lote, então o tipo também é. `tipo=None` faz `derivar_tipo` usar a
    #: categoria, que é precisamente o que este caso de uso quer dizer.
    #:
    #: A CATEGORIA SEM TIPO É CONFERIDA ANTES, e não deixada para `derivar_tipo`:
    #: ela levantaria "Informe a categoria de público", que é verdade no cadastro
    #: um a um — onde a categoria pode vir vazia — e MENTIRA aqui, onde ela foi
    #: informada e o que falta é ela mapear para um tipo. Quem lê "informe a
    #: categoria" depois de ter escolhido uma procura o erro no lugar errado.
    if categoria_publico_id not in _categorias_com_tipo(sessao):
        raise RegraViolada(
            "Esta categoria de público não define tipo de instituição, e o lote "
            "existe para dar o tipo. Escolha outra."
        )
    novo_tipo = derivar_tipo(
        sessao,
        tipo=None,
        categoria_publico_id=categoria_publico_id,
        atual=None,
    )

    #: `with_for_update`: AS LINHAS DO LOTE FICAM TRAVADAS ATÉ O COMMIT.
    #:
    #: ACHADO DE REVISÃO COM SEVERIDADE ALTA, e era um lost update de verdade: o
    #: lote lia as linhas, testava `pendente_de_revisao` EM MEMÓRIA e só gravava
    #: no flush. Dois lotes sobre ids que se cruzam passavam os dois pelo teste
    #: antes de qualquer commit, e o segundo reescrevia categoria, subcategoria e
    #: TIPO de uma linha que o primeiro já havia consolidado.
    #:
    #: ISSO QUEBRAVA A TRAVA "só o que está na fila", que é a razão de a rota
    #: viver sob a fila de revisão — e quebrava em SILÊNCIO, porque as duas
    #: requisições respondiam 200.
    #:
    #: E A FILA É TRABALHO DE EQUIPE POR DESENHO ("inclusive pode ser trabalho de
    #: outra pessoa"), então dois lotes ao mesmo tempo é o caso normal, não a
    #: exceção. O lock serializa os dois: o segundo espera, lê a linha já
    #: consolidada, e recusa — que é o que ele deve fazer.
    #:
    #: `order_by(Instituicao.id)` ANTES DO LOCK, e isso é o conserto de um segundo
    #: achado de revisão: travar várias linhas sem ordem definida deixa o Postgres
    #: escolher, e dois lotes com conjuntos CRUZADOS podem travar subconjuntos em
    #: ordens diferentes — deadlock, que chega como 500 para quem clicou.
    #:
    #: E A DISCIPLINA JÁ EXISTIA NO REPOSITÓRIO, com o comentário dizendo o
    #: porquê: `api/score.py` trava "em ordem de id — a mesma disciplina da
    #: reconferência da taxonomia". Eu escrevi um `with_for_update` novo sem
    #: olhar o que já estava ali.
    #:
    #: A ORDEM DO LOCK NÃO É A ORDEM DAS RECUSAS: o laço continua percorrendo
    #: `ids`, que é a ordem do pedido, e é essa que a tela lê de cima para baixo.
    pedidas = {
        linha.id: linha
        for linha in sessao.scalars(
            select(Instituicao)
            .where(Instituicao.id.in_(ids))
            .order_by(Instituicao.id)
            .with_for_update()
        )
    }

    #: OS NOMES JÁ OCUPADOS NO TIPO DE DESTINO, numa consulta só.
    #:
    #: A `0002` cria `unique (nome_normalizado, tipo)` e o índice NÃO é parcial em
    #: `ativo`: uma instituição desativada continua ocupando o par. Sem esta
    #: conferência, mudar o tipo de 178 linhas estoura em `IntegrityError` no
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
        if linha.tipo == "perfil_rede" and novo_tipo != "perfil_rede":
            #: TODO PERFIL DE REDE, e não só o que tem cargo ou pessoa.
            #:
            #: DOIS ACHADOS DE REVISÃO COM SEVERIDADE ALTA, no mesmo lugar, e o
            #: segundo foi o meu conserto pela METADE: eu recusei o perfil que
            #: carrega `cargo` ou `interlocutor_id` — porque o banco tem CHECK de
            #: que os dois só existem em `tipo = 'perfil_rede'` (migrations `0073`
            #: e `0076`) — e deixei PASSAR o perfil que não tem nenhum dos dois.
            #:
            #: MEDIDO removendo a recusa e o savepoint: 500 com `CheckViolation:
            #: instituicao_cargo_so_de_perfil`. Uma linha derrubava as 178.
            #:
            #: MAS O PERFIL SEM CARGO É O CASO MAIS POBRE, não o mais inofensivo:
            #: `veiculos_da_imprensa._motivo_da_revisao` diz em voz alta que ele
            #: entrou "sem cargo reconhecido, então ficou sem categoria de
            #: público. Diga o CARGO para o perfil entrar na taxonomia". A
            #: pendência dele pede o cargo, não um tipo novo — e são os 1.108
            #: perfis que a primeira carga da Bites criou.
            #:
            #: CONVERTÊ-LO EM `orgao` APAGARIA O FATO de que ele é um perfil de
            #: rede: o vínculo com a pessoa do CRM deixaria de ser possível, e a
            #: fila de duplicados perderia o par perfil × veículo que ela existe
            #: para perguntar. Em silêncio, num lote de 178.
            #:
            #: RECUSAR, E NÃO LIMPAR NADA. É a mesma recusa que o cadastro um a um
            #: já faz (`_conferir_campos_de_perfil`), "para a mensagem falar de
            #: cadastro em vez de constraint".
            recusadas.append(
                Recusado(
                    str(linha.id),
                    linha.nome,
                    "É um perfil de rede, e o lote daria a ele um tipo de "
                    "instituição. O que falta num perfil é o CARGO, que é de onde "
                    "sai a categoria dele — informe-o pela lista de cadastro.",
                )
            )
            continue

        #: UM SAVEPOINT POR LINHA, e é a rede que torna verdadeira a promessa de
        #: "não estoura em IntegrityError".
        #:
        #: ACHADO DE REVISÃO (MÉDIA): as conferências acima são feitas ANTES do
        #: flush, e entre uma e outro cabe outra transação ocupando o mesmo par
        #: `(nome_normalizado, tipo)`. Elas continuam valendo — é delas que sai a
        #: mensagem que diz O QUE fazer —, mas a última palavra é do índice.
        #:
        #: E A MEDIÇÃO MOSTROU QUE OS DOIS CONSERTOS SÃO COMPLEMENTARES: sem a
        #: recusa do perfil mas COM o savepoint, o lote não caía e a recusa dizia
        #: "já existe outra instituição com este nome" — razão errada para a linha
        #: certa. O savepoint evita o estrago; a conferência diz a verdade.
        #:
        #: A MUTAÇÃO FICA DENTRO DO SAVEPOINT, e a ordem é fácil de errar: é a
        #: lição que `app/banco/gravar.py` registra em voz alta. Um flush que falha
        #: marca a SESSÃO INTEIRA para rollback, e o savepoint só a protege se a
        #: escrita estiver dentro dele — com ela de fora, o próximo comando estoura
        #: `PendingRollbackError`, um erro sem relação aparente com o que a pessoa
        #: fez.
        try:
            with sessao.begin_nested():
                linha.categoria_publico_id = categoria_publico_id
                linha.subcategoria_publico_id = subcategoria_publico_id
                linha.tipo = novo_tipo
                if consolidar:
                    linha.pendente_de_revisao = False
                    linha.motivo_da_revisao = None
                sessao.flush()
        except IntegrityError:
            recusadas.append(
                Recusado(
                    str(ident),
                    linha.nome,
                    f"O banco recusou: já existe outra instituição com este nome "
                    f"do tipo {rotulo!r}. É possível duplicata — resolva em "
                    f"'Possíveis duplicados'.",
                )
            )
            continue

        enquadradas += 1
        if consolidar:
            consolidadas += 1

    return Resultado(
        enquadradas=enquadradas,
        consolidadas=consolidadas,
        tipo=novo_tipo,
        recusadas=recusadas,
    )
