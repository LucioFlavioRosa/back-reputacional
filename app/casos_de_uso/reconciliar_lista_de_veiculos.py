"""A lista de veículos vale para os meses JÁ ingeridos, e não só para o próximo.

O PEDIDO, nas palavras do dono do produto: "se eu dizer que uma instituição
pertence a categoria de público como imprensa e esfera econômica e de negócios,
todos seus registros devem ser movidos para a lente de mercado, atualizando
tudo".

COMO ERA. A lente Mercado recorta na INGESTÃO: `clipei_investidores` lê o mesmo
arquivo e a mesma aba que `clipei`, guardando só as linhas cujo veículo está na
lista (`0066`/`0067`). A `0067` escreveu a consequência em voz alta: "nada muda
nos meses já gravados — o novo critério vale a partir da PRÓXIMA subida de cada
mês". Classificar o Valor Econômico hoje não o fazia entrar em agosto; era
preciso resubir agosto.

POR QUE DÁ PARA FAZER SEM O ARQUIVO. As duas fontes leem o MESMO arquivo e a
MESMA aba, e a única diferença entre elas é a lista. Então a fonte de imprensa já
tem, no banco, todas as linhas que a fonte de mercado deveria ter — e reconciliar
é copiar de uma para a outra. O arquivo original não é necessário, e isso importa
porque ele não fica guardado.

O RECORTE AQUI É O MESMO DA INGESTÃO, e isto é a parte que mais pode dar errado.
`ler_planilha` decide por `normalizar(veiculo) in nomes_da_lista` — o TEXTO da
linha, não o `instituicao_id`. Reconciliar por `instituicao_id` seria um segundo
critério: mais bonito, e livre para divergir do primeiro no dia seguinte. Aqui o
caminho é: normalizar em PYTHON os textos distintos do espelho, cruzar com a
lista, e filtrar no SQL por igualdade de texto. Nunca `normalizar` em SQL — a
`0097` reimplementou essa função em SQL e divergiu em 67 de 87 valores.

OS DOIS SENTIDOS, por decisão do dono do produto (19/10/2026): classificar faz
entrar, e DESclassificar faz sair. "A lente é sempre o espelho do cadastro" é uma
regra só, e explicável; o preço é que a nota de um mês pode CAIR por causa de uma
correção de cadastro, e é por isso que a prévia existe.

O QUE ESTA RECONCILIAÇÃO NÃO RECOMPÕE: `mencao_nao_classificada`, a contagem de
"chegou e ninguém classificou". Ela conta linhas que tinham data e não tinham
sentimento — linhas que NUNCA viraram menção, e que portanto não estão no banco
para serem copiadas. Ela fica com o valor da última subida. Afeta só o aviso
"houve volume, ninguém classificou"; não afeta a nota, porque a nota sai de
`score_mes_fonte`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.casos_de_uso.ingerir_mencoes import fontes_do_mesmo_arquivo
from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import Mapeamento, MencaoLida, somar
from app.dominio.texto import normalizar

#: A única lista que existe hoje. Ver `ingestao_score.LISTAS_DE_VEICULOS`.
LISTA_PADRAO = "imprensa_economica"

#: O "namespace" da trava de aplicação (`pg_advisory_xact_lock` recebe dois
#: inteiros). Um número desta casa, para a trava desta operação não colidir com
#: outra que alguém venha a pôr no mesmo banco.
_ESPACO_DA_TRAVA = 10_267


@dataclass(frozen=True, slots=True)
class MudancaDoVeiculo:
    """Um veículo que passa a contar na lente, ou que deixa de contar."""

    nome: str
    mencoes: int


@dataclass(frozen=True, slots=True)
class MudancaDoMes:
    mes: date
    #: Quantas menções a fonte recortada tem HOJE neste mês.
    antes: int
    #: Quantas ela terá quando a lista de agora valer para ele.
    depois: int
    #: SE O MÊS PRECISA SER REESCRITO, e NÃO é `antes != depois`.
    #:
    #: Era uma propriedade derivada das contagens, e isso tinha um buraco: num
    #: mês em que um veículo de 3 menções sai da lista e outro de 3 entra, o
    #: total não muda e o mês ficava intacto — com as menções do veículo que já
    #: não pertence à lente. A comparação verdadeira é entre os CONJUNTOS de
    #: veículos, e quem a faz é `_por_mes_e_veiculo`.
    mudou: bool


@dataclass(frozen=True, slots=True)
class Reconciliacao:
    """O que muda — ou o que mudou — quando a lista passa a valer para trás."""

    #: O código da fonte que recorta (a da lente Mercado).
    fonte: str
    #: O código da fonte de onde as linhas vêm (a que lê o arquivo inteiro).
    espelho: str
    lista: str
    meses: tuple[MudancaDoMes, ...] = ()
    #: Os veículos que passam a contar, e os que deixam de contar. É a resposta
    #: para "o que eu ganho e o que eu perco ao salvar esta classificação".
    entram: tuple[MudancaDoVeiculo, ...] = ()
    saem: tuple[MudancaDoVeiculo, ...] = ()
    #: Falso na prévia, verdadeiro depois de escrever.
    aplicada: bool = False

    @property
    def meses_que_mudam(self) -> tuple[MudancaDoMes, ...]:
        return tuple(mes for mes in self.meses if mes.mudou)


def fontes_que_recortam(sessao: Session, lista: str = LISTA_PADRAO) -> list[ScoreFonte]:
    """As fontes cujo recorte é esta lista — hoje, uma só.

    DESCOBERTAS E NÃO ESCRITAS: `clipei_investidores` é o código de hoje, e um
    código escrito aqui apontaria para o nada numa base onde a fonte tenha outro
    — o cadastro de fontes é dado, não código.

    A UNIDADE DE TRABALHO É A FONTE, e não a lista: cada fonte que recorta tem o
    PRÓPRIO espelho (a irmã que lê o mesmo arquivo). Duas fontes com a mesma
    lista não são um erro — são duas reconciliações, e quem chama percorre.

    O FILTRO É NO JSONB, e não `Mapeamento.de_json` sobre todas as fontes. Isto
    é conserto de um defeito que o teste da configuração REAL pegou: nem toda
    fonte tem mapeamento de planilha — a do CRM é interna e o `de_json` dela
    estoura com "mapeamento sem os campos ['data', 'sentimento']". Interpretar o
    mapeamento de todo mundo para achar uma fonte fazia a descoberta morrer por
    causa de uma fonte que não tem nada a ver com o assunto. É a mesma técnica de
    `fontes_do_mesmo_arquivo`, que filtra por `arquivo` no JSONB.
    """
    return list(
        sessao.scalars(
            select(ScoreFonte)
            .where(ScoreFonte.mapeamento_colunas["lista_de_veiculos"].astext == lista)
            .order_by(ScoreFonte.ordem)
        )
    )


def espelho_de(sessao: Session, fonte: ScoreFonte) -> ScoreFonte:
    """A irmã que lê o MESMO arquivo e NÃO recorta — a origem das linhas.

    `fontes_do_mesmo_arquivo` já é quem responde "quem lê este export", e é a
    mesma função que a ingestão usa para substituir o mês nas duas fontes de uma
    subida só. Perguntar por outro caminho abriria a chance de a reconciliação
    copiar de uma fonte que a subida não considera irmã.
    """
    #: A CHAVE CRUA, e não `Mapeamento.de_json`, pela mesma razão de
    #: `fontes_que_recortam`: interpretar o mapeamento de uma irmã só para
    #: perguntar se ela recorta faz a descoberta morrer por um campo que não tem
    #: nada a ver. `de_json` trata vazio como ausente, e a verdade aqui é a
    #: mesma.
    irmas = [
        irma
        for irma in fontes_do_mesmo_arquivo(sessao, fonte)
        if irma.id != fonte.id
        and not (irma.mapeamento_colunas or {}).get("lista_de_veiculos")
    ]
    if len(irmas) != 1:
        #: Sem espelho não há de onde copiar, e com dois não há como escolher —
        #: e os dois casos são cadastro de fonte mal configurado, não dado.
        raise RegraViolada(
            f"A fonte {fonte.codigo!r} precisa de exatamente uma fonte irmã que "
            f"leia o mesmo arquivo sem recortar; achei {len(irmas)}."
        )
    return irmas[0]


def _textos_no_universo(
    sessao: Session,
    espelho: ScoreFonte,
    fonte: ScoreFonte,
    permitidos: frozenset[str],
) -> set[str]:
    """Os textos de veículo das DUAS fontes que a lista alcança.

    `normalizar` RODA EM PYTHON, sobre os textos DISTINTOS — são alguns milhares
    contra as ~104 mil menções —, e o SQL depois compara texto com texto. É o que
    permite usar a MESMA função da ingestão sem reescrevê-la em `regexp_replace`:
    a `0097` fez isso e divergiu em 67 de 87 valores.

    AS DUAS, porque o recorte é exclusivo: o veículo que já se mudou para a
    recortada não aparece mais no espelho, e olhar só para lá o faria sumir do
    alvo — o que apagaria as menções dele na reconciliação seguinte.
    """
    distintos = sessao.scalars(
        select(Mencao.veiculo)
        .where(
            Mencao.fonte_id.in_([espelho.id, fonte.id]),
            Mencao.veiculo.is_not(None),
        )
        .distinct()
    ).all()
    return {texto for texto in distintos if normalizar(texto) in permitidos}


def _do_universo(
    sessao: Session, espelho: ScoreFonte, fonte: ScoreFonte, alvo: set[str]
) -> dict[date, dict[str | None, int]]:
    """`{mês: {veículo: quantas}}` do que a recortada DEVE ter.

    SOMA AS DUAS FONTES, sem contar duas vezes: para um veículo do alvo, as
    linhas estão OU no espelho (ainda não se mudaram) OU na recortada (já se
    mudaram). Durante a transição do recorte exclusivo elas podem estar nos
    dois — a cópia antiga no espelho e a cópia nova na recortada —, e aí o que
    vale é a da RECORTADA: ela é o destino, e contar as duas inventaria menção.
    """
    da_recortada = _por_mes_e_veiculo(sessao, fonte, alvo)
    do_espelho = _por_mes_e_veiculo(sessao, espelho, alvo)

    juntos: dict[date, dict[str | None, int]] = {
        mes: dict(veiculos) for mes, veiculos in da_recortada.items()
    }
    for mes, veiculos in do_espelho.items():
        no_mes = juntos.setdefault(mes, {})
        for veiculo, quantas in veiculos.items():
            #: SÓ SE A RECORTADA AINDA NÃO TEM ESTE VEÍCULO NESTE MÊS. Com ela
            #: tendo, as linhas do espelho são a cópia velha que a transição
            #: vai apagar — somá-las dobraria o veículo na lente.
            if veiculo not in no_mes:
                no_mes[veiculo] = quantas
    return juntos


def _por_mes_e_veiculo(
    sessao: Session, fonte: ScoreFonte, textos: set[str] | None = None
) -> dict[date, dict[str | None, int]]:
    """`{mês: {veículo: quantas}}` — o grão em que a comparação é honesta.

    POR VEÍCULO E NÃO SÓ POR MÊS, e isto é conserto de um defeito que a primeira
    versão tinha: eu decidia quais meses reescrever comparando a CONTAGEM do mês.
    Num mês em que um veículo de 3 menções sai da lista e outro de 3 entra, o
    total não muda — e o mês ficava intacto, com as menções do veículo que já não
    pertence à lente. Nada daria sinal.

    `None` É UMA CHAVE LEGÍTIMA aqui: a fonte recortada pode ter menções SEM
    veículo, gravadas pelo critério anterior (antes da `0067` o recorte era a
    coluna `Público-alvo`, que não exigia veículo). O alvo nunca as tem, então o
    mês em que elas existem difere e é reescrito — que é o certo.
    """
    consulta = (
        select(Mencao.mes, Mencao.veiculo, func.count())
        .where(Mencao.fonte_id == fonte.id)
        .group_by(Mencao.mes, Mencao.veiculo)
    )
    if textos is not None:
        if not textos:
            return {}
        consulta = consulta.where(Mencao.veiculo.in_(list(textos)))
    mapa: dict[date, dict[str | None, int]] = {}
    for mes, veiculo, quantas in sessao.execute(consulta):
        mapa.setdefault(mes, {})[veiculo] = quantas
    return mapa


def _somado(por_mes: dict[date, dict[str | None, int]]) -> dict[str, int]:
    """O total por veículo, somando os meses.

    `None` FICA DE FORA: linha sem veículo não é um veículo que entra ou sai da
    lista, e mostrá-la no quadro de "passam a contar" seria inventar um nome.
    """
    total: dict[str, int] = {}
    for veiculos in por_mes.values():
        for veiculo, quantas in veiculos.items():
            if veiculo is not None:
                total[veiculo] = total.get(veiculo, 0) + quantas
    return total


def _medir(
    sessao: Session, fonte: ScoreFonte
) -> tuple[ScoreFonte, set[str], Reconciliacao]:
    """O diagnóstico, sem escrever nada. A prévia e o aplicar partem dele.

    O UNIVERSO É A SOMA DAS DUAS FONTES, e não só o espelho — mudança de
    20/10/2026, quando o recorte passou a ser EXCLUSIVO. Antes o espelho tinha
    o arquivo inteiro e a recortada era uma cópia filtrada dele; agora as duas
    PARTICIONAM o arquivo, então a linha que a recortada precisa pode já estar
    nela, e a que ela precisa devolver só existe nela.

    Medir só pelo espelho deixaria de enxergar as linhas que já se mudaram — e
    a prévia diria "nada a fazer" num mês inteiro que mudou de lugar.
    """
    lista = Mapeamento.de_json(fonte.mapeamento_colunas).lista_de_veiculos
    if not lista:
        raise RegraViolada(
            f"A fonte {fonte.codigo!r} não recorta por lista de veículos: não há "
            "o que reconciliar."
        )
    espelho = espelho_de(sessao, fonte)
    permitidos = nomes_da_lista(sessao, lista)
    alvo = _textos_no_universo(sessao, espelho, fonte, permitidos)

    hoje = _por_mes_e_veiculo(sessao, fonte)
    depois = _do_universo(sessao, espelho, fonte, alvo)
    hoje_por_veiculo = _somado(hoje)
    alvo_por_veiculo = _somado(depois)

    entram = tuple(
        MudancaDoVeiculo(nome=nome, mencoes=quantas)
        for nome, quantas in sorted(
            ((n, q) for n, q in alvo_por_veiculo.items() if n not in hoje_por_veiculo),
            key=lambda par: (-par[1], par[0]),
        )
    )
    saem = tuple(
        MudancaDoVeiculo(nome=nome, mencoes=quantas)
        for nome, quantas in sorted(
            ((n, q) for n, q in hoje_por_veiculo.items() if n not in alvo_por_veiculo),
            key=lambda par: (-par[1], par[0]),
        )
    )

    #: A UNIÃO DOS DOIS, e não só os meses do espelho: um mês que hoje tem
    #: menções na lente e deixa de ter (porque o único veículo dele saiu da
    #: lista) é exatamente o caso que o sentido inverso precisa alcançar. Pelos
    #: meses do espelho ele não apareceria, e ficaria com o recorte velho.
    meses = tuple(
        MudancaDoMes(
            mes=mes,
            antes=sum(hoje.get(mes, {}).values()),
            depois=sum(depois.get(mes, {}).values()),
            #: A COMPARAÇÃO É DOS CONJUNTOS, e não dos totais — ver
            #: `_por_mes_e_veiculo`.
            mudou=hoje.get(mes, {}) != depois.get(mes, {}),
        )
        for mes in sorted(set(hoje) | set(depois))
    )

    return (
        espelho,
        alvo,
        Reconciliacao(
            fonte=fonte.codigo,
            espelho=espelho.codigo,
            lista=lista,
            meses=meses,
            entram=entram,
            saem=saem,
        ),
    )


def previa(sessao: Session, fonte: ScoreFonte) -> Reconciliacao:
    """O que mudaria. NÃO escreve.

    A PRÉVIA EXISTE PORQUE A CONTA É A DA DIRETORIA. Aplicar reescreve o
    `score_mes_fonte` de meses fechados, e o índice daqueles meses muda — o
    número que já foi citado em reunião. "Mostre antes" é a mesma regra que a
    conferência da subida de planilha segue, e pela mesma razão.
    """
    _, _, medida = _medir(sessao, fonte)
    return medida


def _devolver_ao_espelho(
    sessao: Session,
    fonte: ScoreFonte,
    espelho: ScoreFonte,
    mes: date,
    alvo: set[str],
    copiaveis: list[str],
) -> None:
    """As menções da recortada cujo veículo saiu da lista voltam ao espelho.

    O SENTIDO INVERSO DO RECORTE EXCLUSIVO. Enquanto o espelho guardava o
    arquivo inteiro, sair da lista era só apagar a cópia — o original nunca
    tinha saído de lá. Com a partição, a linha existe num lugar só: apagá-la
    sem devolver apagaria a matéria do sistema.

    E NÃO DEVOLVE O QUE JÁ ESTÁ LÁ: um mês ainda não migrado tem a linha nos
    dois lados, e copiar de volta criaria a terceira. A conferência é por
    (mês, veículo), que é o grão em que a cópia foi feita.
    """
    de_volta = [
        texto
        for texto in sessao.scalars(
            select(Mencao.veiculo)
            .where(
                Mencao.fonte_id == fonte.id,
                Mencao.mes == mes,
                Mencao.veiculo.is_not(None),
            )
            .distinct()
        ).all()
        if texto not in alvo
    ]
    if not de_volta:
        return

    #: OS QUE O ESPELHO JÁ TEM NESTE MÊS ficam de fora da devolução.
    ja_no_espelho = set(
        sessao.scalars(
            select(Mencao.veiculo)
            .where(
                Mencao.fonte_id == espelho.id,
                Mencao.mes == mes,
                Mencao.veiculo.in_(de_volta),
            )
            .distinct()
        ).all()
    )
    faltando = [texto for texto in de_volta if texto not in ja_no_espelho]
    if not faltando:
        return

    origem = select(
        func.gen_random_uuid(),
        espelho.id,
        *[Mencao.__table__.c[nome] for nome in copiaveis],
    ).where(
        Mencao.fonte_id == fonte.id,
        Mencao.mes == mes,
        Mencao.veiculo.in_(faltando),
    )
    sessao.execute(insert(Mencao).from_select(["id", "fonte_id", *copiaveis], origem))


def _regravar_o_agregado(sessao: Session, fonte: ScoreFonte, mes: date) -> None:
    """Refaz `score_mes_fonte` do mês a partir das menções que a fonte tem agora.

    O AGREGADO SAI DE `somar`, a MESMA função que a ingestão usa — não há uma
    segunda definição de "o que é um mês no banco". Reescrevê-la em SQL seria a
    segunda régua, livre para divergir da primeira.
    """
    sessao.execute(
        delete(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes == mes
        )
    )
    linhas = sessao.execute(
        select(
            Mencao.mes,
            Mencao.sentimento,
            Mencao.tier,
            Mencao.engajamento,
            Mencao.cargo,
        ).where(Mencao.fonte_id == fonte.id, Mencao.mes == mes)
    ).all()
    sessao.add_all(
        ScoreMesFonte(
            fonte_id=fonte.id,
            mes=soma.mes,
            sentimento=soma.sentimento,
            tier=soma.tier,
            mencoes=soma.mencoes,
            soma_log=soma.soma_log,
            soma_engajamento=soma.soma_engajamento,
            soma_cargo=soma.soma_cargo,
        )
        for soma in somar(
            MencaoLida(
                mes=linha.mes,
                sentimento=linha.sentimento,
                tier=linha.tier,
                engajamento=linha.engajamento,
                cargo=linha.cargo,
            )
            for linha in linhas
        )
    )


def aplicar(sessao: Session, fonte: ScoreFonte) -> Reconciliacao:
    """Faz a lista de agora valer para todos os meses já ingeridos.

    SUBSTITUI O MÊS INTEIRO em vez de inserir e apagar linha a linha, e é o mesmo
    gesto de `regravar`: o mês da fonte recortada passa a ser exatamente o
    recorte do mês do espelho. Casar linha a linha exigiria uma chave natural que
    nem todas as menções têm (`id_fonte` só é mapeado desde a `0063`), e um
    casamento errado duplicaria menção na nota.

    O AGREGADO SAI DE `somar`, a MESMA função que a ingestão usa. Ela precisa de
    mês, sentimento, tier, engajamento e cargo, e os cinco estão em `mencao` —
    então não há uma segunda definição de "o que é um mês no banco". Reescrevê-la
    em SQL seria a segunda régua, livre para divergir da primeira.

    A RESPOSTA DESCREVE O ESTADO DEPOIS, e isto é conserto de achado ALTO de
    revisão. A primeira versão devolvia a medida de ANTES, com `mudou=True` nos
    meses que ela acabara de reescrever: a tela, que pergunta "ainda há desvio?",
    continuava mostrando o aviso e o botão depois de aplicar com sucesso. O que
    FOI feito está em `entram`/`saem`, que vêm da medida de antes — é a única
    coisa que só a medida de antes sabe.

    UM POR VEZ, POR TRAVA DE BANCO. Duas aplicações simultâneas (duas abas, ou um
    clique que escape do botão desabilitado) apagavam e inseriam o mesmo mês ao
    mesmo tempo, e a segunda morria com `IntegrityError` na chave primária de
    `score_mes_fonte` — 500 na cara de quem clicou. O banco final ficava certo,
    porque a perdedora desfazia tudo; o erro é que a segunda pessoa via um erro
    para uma operação que simplesmente já tinha sido feita. Com a trava, ela
    espera, remede, e não acha mês para mudar.
    """
    #: A TRAVA É POR FONTE e morre com a transação (`xact`): duas
    #: reconciliações de fontes diferentes não se esperam, e nada fica preso se
    #: o processo cair. A chave é o id da fonte num espaço próprio — o primeiro
    #: argumento é o "namespace", para não colidir com outra trava desta casa.
    sessao.execute(select(func.pg_advisory_xact_lock(_ESPACO_DA_TRAVA, fonte.id)))

    espelho, alvo, medida = _medir(sessao, fonte)

    mudam = [mudanca.mes for mudanca in medida.meses if mudanca.mudou]
    if not mudam:
        return Reconciliacao(
            fonte=medida.fonte,
            espelho=medida.espelho,
            lista=medida.lista,
            meses=medida.meses,
            entram=medida.entram,
            saem=medida.saem,
            aplicada=True,
        )

    #: AS COLUNAS SAEM DO METADATA, e não de uma lista escrita aqui: uma coluna
    #: nova em `mencao` entraria na cópia sozinha. Escrita à mão, ela seria
    #: perdida em silêncio nas menções copiadas — e só nelas.
    copiaveis = [
        coluna.name
        for coluna in Mencao.__table__.columns
        if coluna.name not in ("id", "fonte_id")
    ]

    for mes in mudam:
        #: O QUE VOLTA PARA O ESPELHO, E ISTO É O SENTIDO INVERSO DO RECORTE
        #: EXCLUSIVO (pedido de 20/10/2026: "se voltar a ser imprensa o
        #: histórico deve ser movido também de volta").
        #:
        #: ANTES DE APAGAR A RECORTADA, porque é dela que estas linhas saem: o
        #: veículo que deixou a lista tem as menções dele AQUI, e em lugar
        #: nenhum mais. Apagar primeiro e copiar depois perderia o histórico
        #: dele — o `delete` abaixo não distingue quem fica de quem volta.
        _devolver_ao_espelho(sessao, fonte, espelho, mes, alvo, copiaveis)

        sessao.execute(
            delete(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes == mes)
        )
        sessao.execute(
            delete(ScoreMesFonte).where(
                ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes == mes
            )
        )
        if alvo:
            origem = select(
                #: `gen_random_uuid()` no banco porque o padrão de `Mencao.id` é
                #: do Python, e `insert ... select` nunca o chamaria: as linhas
                #: sairiam sem id.
                func.gen_random_uuid(),
                fonte.id,
                *[Mencao.__table__.c[nome] for nome in copiaveis],
            ).where(
                Mencao.fonte_id == espelho.id,
                Mencao.mes == mes,
                Mencao.veiculo.in_(list(alvo)),
            )
            sessao.execute(
                insert(Mencao).from_select(["id", "fonte_id", *copiaveis], origem)
            )
            #: E SAEM DO ESPELHO: o recorte é EXCLUSIVO. Era aqui que a lente
            #: Imprensa continuava contando o Valor Econômico depois de ele
            #: virar veículo de Mercado — a cópia ia para o recorte e o
            #: original ficava, e as duas lentes contavam a mesma matéria.
            sessao.execute(
                delete(Mencao).where(
                    Mencao.fonte_id == espelho.id,
                    Mencao.mes == mes,
                    Mencao.veiculo.in_(list(alvo)),
                )
            )

        _regravar_o_agregado(sessao, fonte, mes)
        #: O AGREGADO DO ESPELHO TAMBÉM, e é ele que carrega a nota: a Imprensa
        #: só deixa de contar o veículo quando `score_mes_fonte` for refeito.
        #: Mexer em `mencao` e esquecer o agregado deixaria a lista certa e a
        #: NOTA errada — e é a nota que a diretoria cita.
        _regravar_o_agregado(sessao, espelho, mes)

    sessao.flush()
    #: REMEDE DEPOIS DE ESCREVER: `meses` passa a descrever o estado de AGORA, e
    #: nenhum mês volta com `mudou=True` — era isso que fazia a tela continuar
    #: avisando que há desvio logo depois de aplicar com sucesso.
    #:
    #: `entram`/`saem` CONTINUAM SENDO OS DE ANTES, e é de propósito: eles são a
    #: única coisa que só a medida anterior sabe dizer — o que ESTA aplicação
    #: moveu. Depois de escrever, não há mais ninguém entrando nem saindo.
    _, _, agora = _medir(sessao, fonte)
    return Reconciliacao(
        fonte=medida.fonte,
        espelho=medida.espelho,
        lista=medida.lista,
        meses=agora.meses,
        entram=medida.entram,
        saem=medida.saem,
        aplicada=True,
    )
