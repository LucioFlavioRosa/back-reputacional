"""Bytes de um `.xlsx` viram linhas brutas, ou o arquivo é recusado inteiro.

O QUE ESTE MÓDULO NÃO FAZ. Ele não resolve nome contra cadastro, não decide o
que é divergência e não monta interação nenhuma — isso é da Tarefa 5 em diante.
Aqui só se responde "consigo entender a estrutura deste arquivo?", e o valor de
cada célula sai como a pessoa digitou.

A FRONTEIRA ENTRE RECUSAR O ARQUIVO E MARCAR A LINHA é a regra de desenho deste
módulo, e ela não é arbitrária:

  - recusa o ARQUIVO o que não tem conserto linha a linha — uma aba que não
    existe, um cabeçalho que não bate, dois códigos iguais, um participante
    apontando para agenda nenhuma. Nesses casos ninguém sabe o que a pessoa
    quis dizer, e propor 54 agendas a partir de um palpite seria pedir
    conferência de uma coisa que ela não preencheu.

  - deixa passar CRU o que é de uma linha só — uma data que não dá para ler,
    um nome que não existe no cadastro. Derrubar o arquivo por isso puniria as
    53 agendas certas pelo erro de uma, e é exatamente o que a tela de
    conferência existe para resolver.

É o `LinhaBruta` que carrega `numero`, e ele é o número da linha NO ARQUIVO,
contando o cabeçalho. É o que a `importacao_linha.linha_origem` grava e o que
deixa a pessoa voltar à planilha e conferir o que digitou.
"""

import io
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_agendas import (
    ABA_PRINCIPAL,
    FORMATO,
    MARCADOR_DE_REPETICAO,
    ROTULO_DO_VOCABULARIO,
    SEGUNDA_COLUNA_DO_VOCABULARIO,
    VOCABULARIOS_EDITAVEIS,
    Aba,
)
from app.dominio.texto import normalizar

#: Primeira barreira, antes de o parser de XML ver o arquivo: um `.xlsx` é um
#: zip, e todo zip começa assim. É a mesma guarda de `ingerir_mencoes`.
ASSINATURA_ZIP = b"PK\x03\x04"

#: Acima disto a tela de conferência deixa de ser conferível e a transação da
#: confirmação fica longa demais para uma requisição. Um dia de 54 agendas —
#: o caso que originou esta funcionalidade — cabe dez vezes.
TETO_DE_AGENDAS = 500

#: A aba que manda: é dela que saem os códigos que as outras três referenciam.
# `ABA_PRINCIPAL` vem do domínio (ver o import acima): é fato do formato, não
# decisão do leitor. Reexportado aqui porque este módulo era a origem dele e há
# quem o importe por este caminho.

#: A coluna que liga as abas. Vive em todas as quatro.
COLUNA_DO_CODIGO = "Código"

#: O prefixo do código que o SERVIDOR gera para uma agenda sem código.
#:
#: O CÓDIGO NÃO É IDENTIDADE DA AGENDA — é só o vínculo com as abas filhas, e a
#: linha já se identifica por `linha_origem`. Quem tem 54 reuniões para registrar
#: não deve preencher uma coluna que não serve para nada nas linhas sem
#: participante nem material.
#:
#: Ele existe de qualquer forma porque o agrupamento das filhas trabalha por
#: código, e um `None` no meio disso viraria um caso especial em cada passo.
PREFIXO_DO_CODIGO_GERADO = "linha "


def codigo_da_linha(numero: int) -> str:
    """O código que o servidor dá a uma agenda que não tem um.

    CITA A LINHA para a pessoa reconhecer de qual agenda ele fala quando ele
    aparecer numa mensagem — "linha 7" ela encontra na planilha; um uuid, não.
    """
    return f"{PREFIXO_DO_CODIGO_GERADO}{numero}"


#: Formatos de data que uma planilha de verdade entrega quando a célula é
#: TEXTO em vez de data: o brasileiro que a pessoa digita e o ISO que todo
#: export de sistema produz. A ordem importa — "03/04/2026" é 3 de abril aqui.
FORMATOS_DE_DATA = ("%d/%m/%Y", "%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class LinhaBruta:
    """Uma linha da planilha, sem interpretação além de aparar espaço e data."""

    aba: str
    #: O número da linha NO ARQUIVO. A primeira linha de dados é a 2.
    numero: int
    celulas: Mapping[str, object]
    #: O que veio da linha de cima por `idem`, coluna → valor.
    #:
    #: EXISTE PARA A CONFERÊNCIA MOSTRAR. A herança é a única parte desta
    #: funcionalidade cujo resultado é invisível antes de as agendas nascerem: a
    #: célula continua visualmente vazia na planilha. Sem isto, a pessoa
    #: confirmaria 54 agendas confiando na memória do que havia acima.
    herdado: Mapping[str, object] = field(default_factory=dict)


def _texto(valor: object) -> object:
    """Apara o espaço invisível antes de qualquer comparação.

    `str.strip()` sem argumento tira também o espaço não separável (`\xa0`) que
    vem de copiar de uma página web — e é preciso tirá-lo AQUI, porque ele faz
    um nome que existe no cadastro não casar, e a pessoa não vê diferença
    nenhuma na tela para entender por quê.
    """
    if not isinstance(valor, str):
        return valor
    aparado = valor.strip()
    return aparado or None


def data_de_celula(valor: object) -> object:
    """Devolve `date` quando consegue; o valor cru quando não.

    Deixar passar cru é deliberado: data ilegível é divergência de UMA linha,
    e quem decide isso é a Tarefa 5.
    """
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if not isinstance(valor, str):
        return valor
    for formato in FORMATOS_DE_DATA:
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            continue
    return valor


def _abrir(conteudo: bytes):
    """O arquivo aberto, ou `RegraViolada` com mensagem que a pessoa resolve."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
        raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

    nao_e_xlsx = RegraViolada(
        "O arquivo não é uma planilha .xlsx. "
        "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
    )
    if not conteudo.startswith(ASSINATURA_ZIP):
        raise nao_e_xlsx
    try:
        # `data_only` traz o VALOR de uma célula com fórmula: sem ele, uma data
        # montada com `=HOJE()` chegaria como a string "=HOJE()".
        return load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as erro:
        # Um `.docx`, um zip renomeado ou um upload truncado passam a assinatura
        # e morrem aqui. Sem a tradução, a pessoa leria "erro interno" para um
        # arquivo que ela mesma pode trocar.
        raise nao_e_xlsx from erro


def _indices(aba: Aba, cabecalho: tuple) -> dict[str, int]:
    """Coluna → posição, casando por NOME.

    POR NOME E NÃO POR POSIÇÃO. Quem lê por posição recusa o arquivo de quem
    arrastou uma coluna no Excel — ou pior, lê o valor da coluna vizinha como
    se fosse o certo, e a agenda entra com o dado trocado e sem erro nenhum.
    """
    lidos = {
        _texto(valor): posicao
        for posicao, valor in enumerate(cabecalho)
        if isinstance(valor, str) and _texto(valor)
    }
    faltando = [coluna.nome for coluna in aba.colunas if coluna.nome not in lidos]
    if faltando:
        raise RegraViolada(
            f"A aba {aba.nome!r} está sem a coluna {', '.join(repr(n) for n in faltando)}. "
            "Baixe o modelo de novo e transfira o que já preencheu — o cabeçalho "
            "precisa ser o mesmo."
        )
    # Colunas que não conhecemos ficam de fora, e é de propósito: alguém
    # acrescenta uma coluna de rascunho para se organizar, e recusar por causa
    # dela seria proibir a pessoa de anotar na própria planilha.
    return {coluna.nome: lidos[coluna.nome] for coluna in aba.colunas}


def _linhas_da_aba(aba: Aba, folha) -> list[LinhaBruta]:
    linhas = folha.iter_rows(values_only=True)
    try:
        cabecalho = next(linhas)
    except StopIteration:
        raise RegraViolada(f"A aba {aba.nome!r} está vazia, sem nem o cabeçalho.") from None

    indices = _indices(aba, cabecalho)
    e_data = {coluna.nome for coluna in aba.colunas if coluna.campo == "data_interacao"}

    #: O último valor DE VERDADE de cada coluna — o que `idem` repete. Guarda o
    #: valor original e nunca o marcador, senão uma cadeia de `idem` repetiria a
    #: palavra em vez do dado.
    ultimo: dict[str, object] = {}

    lidas: list[LinhaBruta] = []
    for numero, valores in enumerate(linhas, start=2):
        celulas = {
            nome: _texto(valores[posicao]) if posicao < len(valores) else None
            for nome, posicao in indices.items()
        }
        # A LINHA VAZIA É CONFERIDA ANTES DA HERANÇA. É o rastro de um
        # preenchimento abandonado ou de um Ctrl+V, e propô-la daria uma
        # divergência por coluna. Se a herança rodasse primeiro, esse rastro
        # viraria uma CÓPIA da agenda de cima — agendas que ninguém digitou.
        if all(valor is None for valor in celulas.values()):
            continue

        # UM `idem` VALE PARA A LINHA TODA, e é isso que faz o marcador economizar
        # trabalho: escrevê-lo em cada uma das 27 colunas trocaria digitar 27
        # valores por digitar 27 marcadores, e não pouparia nada.
        #
        # A linha OPTA por herdar, uma de cada vez. Quem não escreveu `idem` não
        # herda nada — vazio continua vazio, e um esquecimento continua virando
        # pendência em vez de dado inventado. É a diferença entre isto e "vazio
        # herda", que tiraria a possibilidade de deixar um campo vazio de propósito.
        repete = any(
            isinstance(valor, str) and normalizar(valor) == MARCADOR_DE_REPETICAO
            for valor in celulas.values()
        )

        herdado: dict[str, object] = {}
        for nome, valor in celulas.items():
            marcado = isinstance(valor, str) and normalizar(valor) == MARCADOR_DE_REPETICAO

            if marcado and nome not in ultimo:
                raise RegraViolada(
                    f"Na linha {numero} da aba {aba.nome!r}, a coluna {nome!r} "
                    f"tem {MARCADOR_DE_REPETICAO!r} mas não há linha acima com "
                    "valor para repetir. Escreva o valor nesta linha."
                )

            # O CÓDIGO DA AGENDA NUNCA HERDA por tabela — duas agendas com o mesmo
            # código fariam o arquivo ser recusado por código repetido, e a herança
            # derrubaria o arquivo que ela existe para facilitar. Na aba Agendas o
            # código IDENTIFICA a linha; nas filhas ele REFERENCIA outra, e lá
            # herdar é justamente o que serve — dez participantes da mesma reunião.
            if nome == COLUNA_DO_CODIGO and aba.nome == ABA_PRINCIPAL and not marcado:
                continue

            if marcado or (repete and valor is None and nome in ultimo):
                celulas[nome] = ultimo[nome]
                herdado[nome] = ultimo[nome]

        # `ultimo` guarda o valor FINAL da linha, para uma cadeia de `idem` repetir
        # o dado original e nunca o marcador.
        for nome, valor in celulas.items():
            if valor is not None:
                ultimo[nome] = valor

        for nome in e_data:
            celulas[nome] = data_de_celula(celulas[nome])
        for nome in e_data:
            if nome in herdado:
                herdado[nome] = celulas[nome]
        lidas.append(
            LinhaBruta(
                aba=aba.nome, numero=numero, celulas=celulas, herdado=herdado
            )
        )
    return lidas


def _codigos_das_agendas(linhas: list[LinhaBruta]) -> set[str]:
    """Os códigos da aba Agendas, recusando o que não dá para referenciar."""
    if len(linhas) > TETO_DE_AGENDAS:
        raise RegraViolada(
            f"A planilha tem {len(linhas)} agendas e o limite é {TETO_DE_AGENDAS} "
            "por arquivo. Divida em dois envios."
        )

    vistos: set[str] = set()
    for linha in linhas:
        codigo = linha.celulas.get(COLUNA_DO_CODIGO)
        if codigo is None:
            # SEM CÓDIGO, O SERVIDOR PÕE UM. A coluna só serve para ligar as abas
            # filhas, e uma agenda que não tem filha não tem o que ligar — exigir
            # o preenchimento seria trabalho manual sem função, em cada uma das 54
            # linhas de um dia cheio.
            codigo = codigo_da_linha(linha.numero)
            linha.celulas[COLUNA_DO_CODIGO] = codigo  # type: ignore[index]
        codigo = str(codigo)
        if codigo.startswith(PREFIXO_DO_CODIGO_GERADO) and codigo != codigo_da_linha(
            linha.numero
        ):
            # Escrever à mão o que o servidor geraria para OUTRA linha faria o
            # código deixar de ser único, e a filha ligaria na agenda errada. Só
            # quem escreveu sabe o que quis dizer.
            raise RegraViolada(
                f"O Código {codigo!r} é reservado: o servidor usa {PREFIXO_DO_CODIGO_GERADO!r} "
                "seguido do número da linha para as agendas que deixam a coluna em "
                "branco. Escolha outro código."
            )
        if codigo in vistos:
            raise RegraViolada(
                f"O Código {codigo!r} aparece em duas agendas. Com o código "
                "repetido não há como saber a qual delas cada participante "
                "pertence."
            )
        vistos.add(codigo)
    return vistos


def ler(conteudo: bytes) -> dict[str, list[LinhaBruta]]:
    """As linhas de cada aba, ou `RegraViolada` se a estrutura não se sustenta."""
    pasta = _abrir(conteudo)

    faltando = [aba.nome for aba in FORMATO if aba.nome not in pasta.sheetnames]
    if faltando:
        raise RegraViolada(
            f"A planilha está sem a aba {', '.join(repr(n) for n in faltando)}. "
            f"Abas encontradas: {', '.join(pasta.sheetnames)}. "
            "Baixe o modelo de novo — as quatro abas precisam estar lá."
        )

    por_aba = {aba.nome: _linhas_da_aba(aba, pasta[aba.nome]) for aba in FORMATO}

    # UMA ABA SÓ: não há mais vínculo a conferir. As pessoas e os materiais vivem
    # em colunas numeradas da própria linha, e com isso desapareceu a classe
    # inteira de erro que o vínculo produzia — código órfão, código repetido,
    # participante na agenda errada. O código segue sendo checado por ser único,
    # porque ele ainda identifica a linha nas mensagens.
    _codigos_das_agendas(por_aba[ABA_PRINCIPAL])

    return por_aba


def ler_declarados(conteudo: bytes) -> dict[str, frozenset[str]]:
    """Os nomes que a pessoa ESCREVEU nas abas de vocabulário editáveis.

    É a metade da regra central da classificação que não vem do banco: escrever
    um nome novo na aba de cadastro é declaração de intenção — "quero que isto
    exista" —, e é o que separa cadastro novo de erro de grafia digitado direto
    na célula da agenda. Ver `classificar`, no domínio.

    ABRE O ARQUIVO UMA SEGUNDA VEZ, de propósito, em vez de `ler` passar a
    devolver as duas coisas. `ler` tem contrato e testes próprios em torno das
    quatro abas de preenchimento, e alargá-lo para carregar vocabulário
    misturaria duas perguntas diferentes — "a estrutura se sustenta?" e "o que a
    pessoa quer cadastrar?". O custo é um `load_workbook` a mais sobre bytes que
    já estão na memória, para um arquivo de no máximo 500 agendas.

    SÓ AS EDITÁVEIS. Ler as fechadas não mudaria nada — `classificar` recusa
    valor novo nelas de qualquer jeito — e carregá-las sugeriria que declarar um
    clima novo significa algo, quando não significa.

    Uma aba de vocabulário que não existe vale como vazia, e não como recusa: o
    arquivo de quem apagou a aba que não ia usar continua tendo agendas
    perfeitamente resolvíveis contra o banco, e o efeito de tolerar é o seguro —
    o nome novo vira divergência para a pessoa resolver na tela, em vez de
    cadastro criado sem ela ter declarado nada.
    """
    pasta = _abrir(conteudo)
    declarados: dict[str, frozenset[str]] = {}
    for chave in VOCABULARIOS_EDITAVEIS:
        rotulo = ROTULO_DO_VOCABULARIO[chave]
        if rotulo not in pasta.sheetnames:
            declarados[chave] = frozenset()
            continue
        nomes = set()
        for (valor,) in pasta[rotulo].iter_rows(min_col=1, max_col=1, values_only=True):
            aparado = _texto(valor)
            if isinstance(aparado, str):
                nomes.add(normalizar(aparado))
        declarados[chave] = frozenset(nomes)
    # AS ABAS DE DUAS COLUNAS TÊM CABEÇALHO, e a palavra do cabeçalho não é um
    # cadastro declarado. Sem isto, "Instituição" entraria como instituição a
    # criar. Vale para as duas abas — instituições e interlocutores —, e vem do
    # mapa do domínio em vez de uma linha escrita à mão por aba: a terceira aba de
    # duas colunas já nasceria coberta.
    for chave, segunda in SEGUNDA_COLUNA_DO_VOCABULARIO.items():
        if chave in declarados:
            declarados[chave] = declarados[chave] - {
                normalizar(segunda),
                *(normalizar(cabecalho) for cabecalho in _CABECALHOS_POSSIVEIS[chave]),
            }
    # O MARCADOR ESTÁ NA LISTA de todas as abas de vocabulário, para poder ser
    # escolhido na suspensa — mas ele é instrução, não cadastro. Sem esta
    # subtração, `idem` viraria uma instituição a criar.
    return {
        chave: nomes - {MARCADOR_DE_REPETICAO}
        for chave, nomes in declarados.items()
    }


#: Os nomes que podem estar no cabeçalho da coluna A de cada aba de duas colunas.
#: O rótulo mudou uma vez ("Instituições" → "Instituição") e pode mudar de novo; um
#: cabeçalho não reconhecido vira cadastro a criar, que é o tipo de defeito que
#: aparece como "por que ele quer criar uma instituição chamada Instituição?".
_CABECALHOS_POSSIVEIS: dict[str, tuple[str, ...]] = {
    "instituicoes": ("Instituição", "Instituições"),
    "interlocutores": ("Interlocutor", "Interlocutores"),
}


def _segunda_coluna(conteudo: bytes, chave: str) -> dict[str, str]:
    """Nome normalizado da coluna A → valor normalizado da coluna B.

    UMA LEITURA, DUAS CHAMADORAS: a categoria de público da instituição e a
    instituição do interlocutor são a mesma pergunta feita a abas diferentes. Duas
    cópias divergiriam no dia em que uma delas aprendesse a aparar algo novo.
    """
    pasta = _abrir(conteudo)
    rotulo = ROTULO_DO_VOCABULARIO[chave]
    if rotulo not in pasta.sheetnames:
        return {}
    cabecalhos = {normalizar(nome) for nome in _CABECALHOS_POSSIVEIS.get(chave, ())}
    valores: dict[str, str] = {}
    for nome, ao_lado in pasta[rotulo].iter_rows(min_col=1, max_col=2, values_only=True):
        aparado = _texto(nome)
        if not isinstance(aparado, str):
            continue
        primeira = normalizar(aparado)
        if primeira in cabecalhos:
            continue
        aparado_ao_lado = _texto(ao_lado)
        if isinstance(aparado_ao_lado, str):
            valores[primeira] = normalizar(aparado_ao_lado)
    return valores


def ler_instituicoes_dos_interlocutores(conteudo: bytes) -> dict[str, str]:
    """Nome normalizado do interlocutor → a instituição escrita ao lado dele.

    A COLUNA B DA ABA DE INTERLOCUTORES, que é a relação que o front tem. Quem
    declara alguém novo escolhe o órgão na suspensa ao lado do nome, e é isso que
    permite recusar no UPLOAD a contradição entre o órgão declarado e o da agenda —
    em vez de deixá-la estourar na confirmação, depois da conferência inteira.

    Devolve o nome da instituição, não o id: quem resolve nome para cadastro é a
    proposta, com o mesmo `classificar` de todo o resto. Resolver aqui seria uma
    segunda resolução, com regra própria.
    """
    return _segunda_coluna(conteudo, "interlocutores")


def ler_categorias_declaradas(conteudo: bytes) -> dict[str, str]:
    """Nome normalizado → categoria de público, da coluna B da aba de instituições.

    É DELA QUE O TIPO NASCE, e o tipo deriva a frente da agenda. Quem declara o
    cadastro declara a categoria, como a tela de cadastro também exige.
    """
    return _segunda_coluna(conteudo, "instituicoes")
