"""A linha da planilha vira uma proposta de interação, ou vira divergência.

A IMPORTAÇÃO NÃO ESCREVE EM `interacao`. Ela monta um `InteracaoEntrada` — o
mesmo corpo que o `POST /api/interacoes` recebe da tela — e a confirmação
(Tarefa 11) o manda pelo mesmo caminho. É o que garante que uma agenda importada
nasça com as mesmas regras, as mesmas derivações e as mesmas recusas de uma
agenda digitada: se a importação escrevesse direto, cada regra nova do
formulário teria de ser reimplementada aqui, e as duas versões divergiriam.

ONDE CADA VOCABULÁRIO MORA é a única coisa que este módulo sabe e o domínio não.
`app/dominio/importacao_de_agendas.py` descreve QUAIS vocabulários a planilha
tem e como suas abas se chamam — isso é sobre o arquivo. De qual tabela cada um
sai, e se o campo da interação guarda o `id` da linha ou o `codigo` estável, é
sobre como o BANCO guarda, e por isso é aqui. `NO_BANCO` e `NO_CODIGO` são essa
tabela, e um teste prende as duas listas à do domínio.

O NOME QUE A PESSOA VÊ NÃO É O QUE O BANCO GUARDA, e isso não é detalhe: o clima
de código `propositivo` tem rótulo "Positivo". A aba de vocabulário lista o
rótulo, porque é o que a pessoa reconhece; `InteracaoEntrada.clima` recebe o
código, porque é o que a criação espera. Mandar o rótulo adiante daria 422 num
campo que a pessoa preencheu certo.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import (
    AreaPessoa,
    Clima,
    FormatoInteracao,
    Iniciativa,
    Resultado,
    Status,
    Tema,
    UnidadeNegocio,
)
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso.ler_planilha_de_agendas import (
    ABA_PRINCIPAL,
    COLUNA_DO_CODIGO,
    LinhaBruta,
    ler,
    ler_declarados,
)
from app.dominio.importacao_de_agendas import (
    FORMATO,
    VOCABULARIOS_FECHADOS,
    Divergencia,
    aba_de,
    classificar,
)
from app.dominio.interacao import (
    ABRANGENCIAS_VALIDAS,
    MODALIDADES,
    MOMENTOS_DE_MATERIAL,
    PAPEIS,
    PRESENCAS,
)
from app.dominio.texto import normalizar
from app.esquemas.interacoes import (
    InteracaoEntrada,
    MaterialEntrada,
    ParticipacaoEntrada,
    ParticipanteDaOutraParteEntrada,
)


@dataclass(frozen=True, slots=True)
class _Fonte:
    """De onde um vocabulário sai e o que dele entra na interação."""

    tabela: type
    #: `id` quando o campo da interação é `..._id` ou lista de ids; `codigo`
    #: quando ele guarda o código estável do dicionário (`clima`, `status`…).
    resolve_para: str


#: Vocabulário → tabela. As três primeiras são CADASTRO (a importação pode criar
#: linha nova nelas); as outras são dicionário administrado ou fechado.
NO_BANCO: dict[str, _Fonte] = {
    "instituicoes": _Fonte(Instituicao, "id"),
    "interlocutores": _Fonte(Interlocutor, "id"),
    "pessoas_aegea": _Fonte(PessoaAegea, "id"),
    "temas": _Fonte(Tema, "id"),
    "unidades_negocio": _Fonte(UnidadeNegocio, "id"),
    "formatos_interacao": _Fonte(FormatoInteracao, "id"),
    "areas_pessoa": _Fonte(AreaPessoa, "id"),
    "status": _Fonte(Status, "codigo"),
    "climas": _Fonte(Clima, "codigo"),
    "resultados": _Fonte(Resultado, "codigo"),
    "iniciativas": _Fonte(Iniciativa, "codigo"),
}

#: Vocabulário sem tabela: a lista mora em `dominio/interacao.py`, porque mudá-la
#: é mudar a regra e não o cadastro. O valor É o código, e `normalizar` faz
#: "Híbrida" casar com `hibrida` — acento e caixa saem dos dois lados.
NO_CODIGO: dict[str, tuple[str, ...]] = {
    "modalidade": MODALIDADES,
    "presenca": PRESENCAS,
    "papel": PAPEIS,
    "momento": MOMENTOS_DE_MATERIAL,
}

#: Coluna da aba filha → campo da entrada correspondente. As colunas das abas
#: filhas têm `campo=""` em `FORMATO` de propósito: elas não alimentam um campo
#: da interação, e sim um item de lista. O mapeamento é aqui, e um teste prende
#: cada coluna a uma entrada desta tabela.
CAMPOS_DAS_ABAS_FILHAS: dict[str, dict[str, str]] = {
    "Participantes": {
        "Pessoa": "interlocutor_id",
        "Presença": "presenca",
        "Principal": "principal",
    },
    "Pessoas da Aegea": {"Pessoa": "pessoa_aegea_id", "Papel": "papel", "Presença": "presenca"},
    "Materiais": {
        "Momento": "momento",
        "Título": "titulo",
        "Link": "url",
        "Observação": "observacao",
    },
}

#: Em qual campo de `InteracaoEntrada` a lista de cada aba filha entra, e com
#: qual modelo cada linha dela é montada.
LISTAS_DAS_ABAS_FILHAS: dict[str, tuple[str, type]] = {
    "Participantes": ("outra_parte", ParticipanteDaOutraParteEntrada),
    "Pessoas da Aegea": ("participacoes", ParticipacaoEntrada),
    "Materiais": ("materiais", MaterialEntrada),
}

#: As colunas sem as quais a linha da aba filha não tem sentido — as recusas 1,
#: 2, 3 e 5 de `IMPEDIMENTOS_DA_PLANILHA`.
#:
#: MATERIAIS EXIGE O LINK, e aqui a planilha é mais estrita que o formulário de
#: propósito: o front aceita arquivo OU link porque tem upload, e uma planilha
#: não tem. Um material sem link nem arquivo não leva a lugar nenhum, e deixá-lo
#: passar gravaria um título que aponta para nada.
COLUNAS_EXIGIDAS_DAS_FILHAS: dict[str, tuple[str, ...]] = {
    "Participantes": ("Pessoa",),
    "Pessoas da Aegea": ("Pessoa",),
    "Materiais": ("Título", "Link"),
}

#: Os campos que `InteracaoEntrada` exige. Sem um deles não há proposta nenhuma
#: a montar, então a divergência TRAVA.
OBRIGATORIOS = ("data_interacao", "instituicao_id", "uf")

#: O campo sob o qual a possível duplicata aparece na conferência.
#:
#: NOME PRÓPRIO, e não `data_interacao`: o agrupamento junta por `(campo, valor)`,
#: e usar `data_interacao` misturaria "não consegui ler esta data" com "já existe
#: agenda nesse dia" — dois problemas com resoluções completamente diferentes na
#: mesma linha da tela.
CAMPO_DA_DUPLICATA = "duplicata"

#: Vocabulário de duas palavras que não tem tabela nem lista no domínio.
_SIM = frozenset({"sim", "s", "true", "verdadeiro", "1"})
_NAO = frozenset({"nao", "n", "false", "falso", "0"})


@dataclass(frozen=True, slots=True)
class Proposta:
    """O que a importação entendeu de UMA linha da aba Agendas.

    `entrada` é `None` quando alguma divergência trava: sem os campos que
    `InteracaoEntrada` exige não há objeto válido a montar, e montá-lo pela
    metade só adiaria o erro para a confirmação.
    """

    linha: LinhaBruta
    entrada: InteracaoEntrada | None
    divergencias: list[Divergencia] = field(default_factory=list)


def _indice(sessao: Session) -> dict[str, dict[str, object]]:
    """Vocabulário → (nome normalizado → o valor que entra na interação).

    UMA CONSULTA POR VOCABULÁRIO, e não uma por linha. É o que faz 500 agendas
    custarem o mesmo que 3: sem isto, cada linha iria ao banco buscar a sua
    instituição, e o teste de invariância de custo é o que prende essa promessa.
    """
    indice: dict[str, dict[str, object]] = {}
    for chave, fonte in NO_BANCO.items():
        coluna = getattr(fonte.tabela, fonte.resolve_para)
        # `nome_normalizado` já existe nas tabelas de cadastro e é indexado —
        # usá-lo evita normalizar em Python o que o banco já tem pronto.
        tem_normalizado = hasattr(fonte.tabela, "nome_normalizado")
        alvo = fonte.tabela.nome_normalizado if tem_normalizado else fonte.tabela.nome
        indice[chave] = {
            (nome if tem_normalizado else normalizar(nome)): valor
            for nome, valor in sessao.execute(select(alvo, coluna)).all()
            if nome
        }
    for chave, codigos in NO_CODIGO.items():
        indice[chave] = {normalizar(codigo): codigo for codigo in codigos}
    return indice


def vocabularios(sessao: Session) -> dict[str, list[str]]:
    """Os nomes que a pessoa LÊ, por vocabulário — o que o modelo `.xlsx` lista.

    Separado de `_indice` porque são duas perguntas: o modelo mostra o rótulo, a
    proposta resolve para o id ou o código. Juntá-los faria a aba de vocabulário
    listar `propositivo` onde a pessoa espera "Positivo".
    """
    listas: dict[str, list[str]] = {}
    for chave, fonte in NO_BANCO.items():
        nomes = sessao.scalars(select(fonte.tabela.nome).order_by(fonte.tabela.nome)).all()
        listas[chave] = [nome for nome in nomes if nome]
    for chave, codigos in NO_CODIGO.items():
        listas[chave] = list(codigos)
    return listas


def _booleano(valor: object) -> bool | None | str:
    """`sim`/`não` viram booleano; qualquer outra coisa volta como está.

    Devolver o valor cru em vez de `None` é o que permite virar divergência: um
    "talvez" digitado na coluna não pode desaparecer em silêncio.
    """
    if valor is None:
        return None
    chave = normalizar(str(valor))
    if chave in _SIM:
        return True
    if chave in _NAO:
        return False
    return str(valor)


def _resolver(
    valor: object,
    coluna_nome: str,
    vocabulario: str,
    campo: str,
    indice: dict[str, dict[str, object]],
    declarados: Mapping[str, frozenset[str]],
    divergencias: list[Divergencia],
) -> object | None:
    """O valor resolvido, ou `None` com a divergência anotada."""
    if valor is None:
        return None
    texto = str(valor)
    conhecidos = indice.get(vocabulario, {})
    veredito = classificar(texto, vocabulario, conhecidos, declarados.get(vocabulario, frozenset()))

    if veredito == "resolve":
        return conhecidos[normalizar(texto)]

    if veredito == "cria":
        # Declarado na aba editável: não é pendência da pessoa, é trabalho da
        # confirmação. Aparece na conferência como "vou criar", sem travar.
        divergencias.append(
            Divergencia(
                campo=campo,
                valor=texto,
                mensagem=f"{coluna_nome}: vou cadastrar {texto!r}, que você declarou na aba.",
                trava=False,
            )
        )
        return None

    fechado = vocabulario in VOCABULARIOS_FECHADOS
    motivo = (
        f"{coluna_nome}: {texto!r} não está na lista, e esta lista não aceita valor novo."
        if fechado
        else f"{coluna_nome}: {texto!r} não existe no cadastro. Se é novo, "
        f"escreva-o também na aba de cadastro."
    )
    divergencias.append(Divergencia(campo=campo, valor=texto, mensagem=motivo, trava=True))
    return None


def _filhas_por_codigo(
    por_aba: Mapping[str, list[LinhaBruta]],
    indice: dict[str, dict[str, object]],
    declarados: Mapping[str, frozenset[str]],
) -> dict[str, dict[str, list]]:
    """Código da agenda → {campo da lista: [itens]}, com as divergências dentro.

    AGRUPA UMA VEZ, e não uma busca por agenda: com 54 agendas e 200
    participantes, varrer a aba filha por agenda seria varrê-la 54 vezes.
    """
    agrupado: dict[str, dict[str, list]] = {}
    pendencias: dict[str, list[Divergencia]] = {}

    for nome_da_aba, (campo_da_lista, modelo) in LISTAS_DAS_ABAS_FILHAS.items():
        mapeamento = CAMPOS_DAS_ABAS_FILHAS[nome_da_aba]
        colunas = {coluna.nome: coluna for coluna in aba_de(nome_da_aba).colunas}

        for linha in por_aba[nome_da_aba]:
            codigo = str(linha.celulas[COLUNA_DO_CODIGO])
            divergencias: list[Divergencia] = []
            valores: dict[str, object] = {}

            for coluna_nome, campo in mapeamento.items():
                bruto = linha.celulas.get(coluna_nome)
                coluna = colunas[coluna_nome]
                if coluna.vocabulario:
                    resolvido = _resolver(
                        bruto,
                        coluna_nome,
                        coluna.vocabulario,
                        f"{campo_da_lista}.{campo}",
                        indice,
                        declarados,
                        divergencias,
                    )
                elif campo == "principal":
                    resolvido = _booleano(bruto) or False
                else:
                    resolvido = bruto
                if resolvido is not None:
                    valores[campo] = resolvido

            for exigida in COLUNAS_EXIGIDAS_DAS_FILHAS[nome_da_aba]:
                if linha.celulas.get(exigida) is None:
                    divergencias.append(
                        Divergencia(
                            campo=campo_da_lista,
                            valor=codigo,
                            mensagem=(
                                f"Linha {linha.numero} da aba {nome_da_aba!r}: "
                                f"falta {exigida}."
                            ),
                            trava=True,
                        )
                    )

            destino = agrupado.setdefault(codigo, {})
            pendencias.setdefault(codigo, []).extend(divergencias)
            if divergencias:
                # A linha filha com pendência não entra na lista: montar o modelo
                # sem o id obrigatório estouraria a validação do Pydantic, e a
                # pendência já está registrada para a pessoa resolver.
                continue
            try:
                destino.setdefault(campo_da_lista, []).append(modelo(**valores))
            except Exception as erro:  # noqa: BLE001 - vira pendência, não 500
                pendencias[codigo].append(
                    Divergencia(
                        campo=campo_da_lista,
                        valor=str(valores),
                        mensagem=f"Linha {linha.numero} da aba {nome_da_aba!r}: {erro}",
                        trava=True,
                    )
                )

    for codigo, divergencias in pendencias.items():
        agrupado.setdefault(codigo, {})["__divergencias__"] = divergencias
    return agrupado


def _quem_representa(sessao: Session) -> dict[object, frozenset]:
    """Instituição → os interlocutores que podem falar por ela.

    UMA CONSULTA, e não uma por agenda: com 54 agendas, perguntar "quem
    representa esta instituição?" por linha seria 54 idas ao banco, e o teste de
    invariância de custo pegaria na hora.
    """
    por_instituicao: dict[object, set] = {}
    linhas = sessao.execute(
        select(Interlocutor.instituicao_id, Interlocutor.id).where(
            Interlocutor.instituicao_id.is_not(None)
        )
    ).all()
    for instituicao_id, interlocutor_id in linhas:
        por_instituicao.setdefault(instituicao_id, set()).add(interlocutor_id)
    return {chave: frozenset(valores) for chave, valores in por_instituicao.items()}


def _ja_existem(sessao: Session, pares: set[tuple]) -> set[tuple]:
    """Quais (instituição, data) já têm agenda no sistema.

    UMA CONSULTA para o arquivo inteiro, e não uma por agenda. Filtra pelos dois
    conjuntos e cruza em Python: com no máximo 500 linhas, o `in_` de duas
    colunas é barato, e o teste de invariância de custo não deixaria passar uma
    consulta por linha.

    Ignora o que foi arquivado: uma agenda arquivada não é a mesma reunião
    acontecendo de novo, e avisar sobre ela ensinaria a ignorar o aviso.
    """
    if not pares:
        return set()
    instituicoes = {instituicao for instituicao, _ in pares}
    datas = {data for _, data in pares}
    linhas = sessao.execute(
        select(InteracaoRegistro.instituicao_id, InteracaoRegistro.data_interacao).where(
            InteracaoRegistro.instituicao_id.in_(instituicoes),
            InteracaoRegistro.data_interacao.in_(datas),
            InteracaoRegistro.arquivado_em.is_(None),
        )
    ).all()
    return {(instituicao, data) for instituicao, data in linhas} & pares


def impedimentos(entrada: InteracaoEntrada, podem_representar: frozenset) -> list[Divergencia]:
    """As recusas 4 e 6 — as que só se veem com a proposta inteira montada.

    As outras quatro (1, 2, 3, 5) são "falta esta coluna" e vivem em
    `COLUNAS_EXIGIDAS_DAS_FILHAS`, onde a mensagem pode citar a linha e a aba.
    Aqui ficam as duas que dependem de comparar um item com OUTRO dado: o
    participante com a instituição da agenda, e um participante com os demais.
    """
    achados: list[Divergencia] = []

    for posicao, participante in enumerate(entrada.outra_parte, start=1):
        if participante.interlocutor_id not in podem_representar:
            achados.append(
                Divergencia(
                    campo="outra_parte",
                    valor=str(participante.interlocutor_id),
                    mensagem=(
                        f"Pela outra parte, a pessoa da linha {posicao} não pertence "
                        "à instituição desta agenda."
                    ),
                    trava=True,
                )
            )

    # `(pessoa, papel)` é a chave no banco. A mesma pessoa em papéis DIFERENTES
    # continua válida, e barrá-la aqui seria a importação inventando uma regra
    # que o resto do sistema não tem.
    vistos: set[tuple] = set()
    for participacao in entrada.participacoes:
        chave = (participacao.pessoa_aegea_id, participacao.papel)
        if chave in vistos:
            achados.append(
                Divergencia(
                    campo="participacoes",
                    valor=str(participacao.pessoa_aegea_id),
                    mensagem=(
                        "Pela Aegea, esta pessoa já está na lista neste mesmo papel."
                    ),
                    trava=True,
                )
            )
        vistos.add(chave)

    return achados


def propor(sessao: Session, conteudo: bytes) -> list[Proposta]:
    """Uma proposta por linha da aba Agendas, com o que não resolveu anotado."""
    por_aba = ler(conteudo)
    declarados = ler_declarados(conteudo)
    indice = _indice(sessao)
    filhas = _filhas_por_codigo(por_aba, indice, declarados)
    representantes = _quem_representa(sessao)

    colunas_de_agenda = aba_de(ABA_PRINCIPAL).colunas
    propostas: list[Proposta] = []

    for linha in por_aba[ABA_PRINCIPAL]:
        divergencias: list[Divergencia] = []
        campos: dict[str, object] = {}
        listas: dict[str, list[object]] = {}

        for coluna in colunas_de_agenda:
            if not coluna.campo:
                continue
            bruto = linha.celulas.get(coluna.nome)
            e_lista = coluna.campo in ("temas", "areas")

            if coluna.vocabulario:
                valor = _resolver(
                    bruto,
                    coluna.nome,
                    coluna.vocabulario,
                    coluna.campo,
                    indice,
                    declarados,
                    divergencias,
                )
            elif coluna.campo == "data_interacao":
                valor = bruto if isinstance(bruto, date) else None
                if bruto is not None and valor is None:
                    divergencias.append(
                        Divergencia(
                            campo="data_interacao",
                            valor=str(bruto),
                            mensagem=f"Data: não consegui ler {str(bruto)!r}. "
                            "Use 25/09/2026 ou 2026-09-25.",
                            trava=True,
                        )
                    )
            elif coluna.campo == "preve_desdobramento":
                convertido = _booleano(bruto)
                if isinstance(convertido, str):
                    divergencias.append(
                        Divergencia(
                            campo=coluna.campo,
                            valor=convertido,
                            mensagem=f"{coluna.nome}: responda sim ou não, não {convertido!r}.",
                            trava=True,
                        )
                    )
                    valor = None
                else:
                    valor = convertido
            elif coluna.campo == "uf":
                valor = str(bruto).upper() if bruto is not None else None
                if valor is not None and valor not in ABRANGENCIAS_VALIDAS:
                    divergencias.append(
                        Divergencia(
                            campo="uf",
                            valor=str(bruto),
                            mensagem=f"UF: {str(bruto)!r} não é sigla de estado. "
                            "Use uma das 27, ou NA/IN.",
                            trava=True,
                        )
                    )
                    valor = None
            else:
                valor = bruto

            if valor is None:
                continue
            if e_lista:
                listas.setdefault(coluna.campo, []).append(valor)
            else:
                campos[coluna.campo] = valor

        campos.update(listas)

        codigo = str(linha.celulas[COLUNA_DO_CODIGO])
        da_agenda = filhas.get(codigo, {})
        divergencias.extend(da_agenda.get("__divergencias__", []))
        for campo_da_lista, itens in da_agenda.items():
            if campo_da_lista != "__divergencias__":
                campos[campo_da_lista] = itens

        faltando = [campo for campo in OBRIGATORIOS if campo not in campos]
        for campo in faltando:
            # Só anuncia o que ainda não tem divergência própria: uma instituição
            # que não existe já foi explicada acima, e repetir a mesma pendência
            # com outras palavras faria a pessoa procurar dois problemas.
            if not any(d.campo == campo for d in divergencias):
                divergencias.append(
                    Divergencia(
                        campo=campo,
                        valor="",
                        mensagem=f"Falta {campo.replace('_', ' ')}, que toda agenda precisa ter.",
                        trava=True,
                    )
                )

        entrada = None
        if not any(d.trava for d in divergencias):
            try:
                entrada = InteracaoEntrada(**campos)
            except Exception as erro:  # noqa: BLE001 - vira pendência, não 500
                divergencias.append(
                    Divergencia(
                        campo="",
                        valor="",
                        mensagem=f"Linha {linha.numero}: {erro}",
                        trava=True,
                    )
                )

        if entrada is not None:
            # As recusas 4 e 6 só se veem agora, com a proposta montada: elas
            # comparam um participante com a instituição da agenda e com os
            # outros participantes.
            do_formulario = impedimentos(
                entrada, representantes.get(entrada.instituicao_id, frozenset())
            )
            if do_formulario:
                divergencias.extend(do_formulario)
                entrada = None

        propostas.append(Proposta(linha=linha, entrada=entrada, divergencias=divergencias))

    return _avisar_duplicatas(sessao, propostas)


def _avisar_duplicatas(sessao: Session, propostas: list[Proposta]) -> list[Proposta]:
    """Marca as agendas que já parecem existir — AVISO, nunca travamento.

    Duas reuniões com o mesmo órgão no mesmo dia acontecem, e travar por isso
    ensinaria a pessoa a ignorar o aviso. É justamente o aviso que a protege do
    caso que importa: ela subiu o mesmo arquivo duas vezes.

    Conta também a repetição DENTRO do arquivo, não só contra o banco: subir uma
    planilha onde a mesma agenda foi colada duas vezes é o mesmo erro visto de
    outro ângulo.
    """
    pares = {
        (proposta.entrada.instituicao_id, proposta.entrada.data_interacao)
        for proposta in propostas
        if proposta.entrada is not None
    }
    no_banco = _ja_existem(sessao, pares)

    vistos: set[tuple] = set()
    for proposta in propostas:
        if proposta.entrada is None:
            continue
        par = (proposta.entrada.instituicao_id, proposta.entrada.data_interacao)
        if par in no_banco or par in vistos:
            proposta.divergencias.append(
                Divergencia(
                    campo=CAMPO_DA_DUPLICATA,
                    valor=proposta.entrada.data_interacao.isoformat(),
                    mensagem=(
                        "Já existe agenda com esta instituição nesta data. Se são "
                        "duas reuniões de verdade, pode confirmar."
                    ),
                    trava=False,
                )
            )
        vistos.add(par)
    return propostas


def vocabulario_do_campo(campo: str) -> str | None:
    """O vocabulário de onde as sugestões de um campo saem.

    A tela precisa oferecer "nomes parecidos" para uma instituição que não
    existe, e os nomes parecidos vêm do vocabulário daquela coluna. O `campo` de
    uma coluna de aba filha vem prefixado (`outra_parte.interlocutor_id`), e é
    por isso que este mapa é montado dos dois lados.
    """
    return _VOCABULARIO_DO_CAMPO.get(campo)


_VOCABULARIO_DO_CAMPO: dict[str, str] = {
    **{
        coluna.campo: coluna.vocabulario
        for aba in FORMATO
        if aba.nome == ABA_PRINCIPAL
        for coluna in aba.colunas
        if coluna.campo and coluna.vocabulario
    },
    **{
        f"{LISTAS_DAS_ABAS_FILHAS[nome][0]}.{campo}": coluna.vocabulario
        for nome, mapeamento in CAMPOS_DAS_ABAS_FILHAS.items()
        for coluna in aba_de(nome).colunas
        for campo in [mapeamento.get(coluna.nome)]
        if campo and coluna.vocabulario
    },
}


def colunas_de_aba_filha_sem_campo() -> Sequence[str]:
    """As colunas de aba filha que ninguém mapeou para um campo.

    PÚBLICA porque é um teste que a usa, e não o código de produção: a guarda
    vive em `tests/test_importar_agendas.py`. Um `assert` de módulo pareceria
    mais forte e seria mais fraco — `python -O` o removeria, e violá-lo
    derrubaria a aplicação inteira na importação em vez de deixar um teste
    vermelho para quem acrescentou a coluna.
    """
    faltando = []
    for nome_da_aba, mapeamento in CAMPOS_DAS_ABAS_FILHAS.items():
        for coluna in aba_de(nome_da_aba).colunas:
            if coluna.nome != COLUNA_DO_CODIGO and coluna.nome not in mapeamento:
                faltando.append(f"{nome_da_aba}.{coluna.nome}")
    return faltando
