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
    COLUNA_DE_REPETICAO,
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VALOR_DA_REPETICAO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_QUE_A_IMPORTACAO_CRIA,
    Aba,
    colunas_do_cadastro,
)
from app.dominio.texto import normalizar

#: Primeira barreira, antes de o parser de XML ver o arquivo: um `.xlsx` é um
#: zip, e todo zip começa assim. É a mesma guarda de `ingerir_mencoes`.
ASSINATURA_ZIP = b"PK\x03\x04"

#: Acima disto a tela de conferência deixa de ser conferível e a transação da
#: confirmação fica longa demais para uma requisição. Um dia de 54 agendas —
#: o caso que originou esta funcionalidade — cabe dez vezes.
TETO_DE_AGENDAS = 500



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
    # SÓ AS OBRIGATÓRIAS SÃO EXIGIDAS, e é o que faz os dois modelos coexistirem
    # sem o leitor precisar saber qual deles chegou: o simplificado tem 22 das 59
    # colunas, e exigir o cabeçalho inteiro recusaria o arquivo do próprio modelo.
    #
    # Isso também acolhe o arquivo de quem apagou as colunas que não ia usar — que
    # é o que se faz numa planilha. Recusar por coluna apagada é o pior erro
    # possível num arquivo de 500 linhas: nada aproveitado, e nada a consertar
    # linha a linha.
    faltando = [
        coluna.nome
        for coluna in aba.colunas
        if coluna.obrigatoria and coluna.nome not in lidos
    ]
    if faltando:
        raise RegraViolada(
            f"A aba {aba.nome!r} está sem a coluna "
            f"{', '.join(repr(n) for n in faltando)}, que toda agenda precisa ter. "
            "Baixe o modelo de novo e transfira o que já preencheu."
        )
    # Colunas que não conhecemos ficam de fora, e é de propósito: alguém
    # acrescenta uma coluna de rascunho para se organizar, e recusar por causa
    # dela seria proibir a pessoa de anotar na própria planilha.
    return {
        coluna.nome: lidos[coluna.nome] for coluna in aba.colunas if coluna.nome in lidos
    }


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

        # UMA COLUNA DECIDE PELA LINHA TODA, e é aí que está a economia: escrever a
        # instrução em cada uma das 37 colunas trocaria digitar 37 valores por
        # digitar 22 instruções, e não pouparia nada.
        #
        # A LINHA OPTA POR HERDAR. Quem não marcou não herda: vazio continua vazio,
        # e um esquecimento continua virando pendência em vez de dado inventado. É a
        # diferença entre isto e "vazio herda", que tiraria a possibilidade de
        # deixar um campo vazio de propósito.
        #
        # ANTES ERA O MARCADOR `idem`, escolhido dentro de qualquer lista suspensa:
        # funcionava e era indescobrível. A instrução virou coluna, e a palavra
        # `idem` numa célula voltou a ser só texto.
        marca = celulas.get(COLUNA_DE_REPETICAO)
        repete = isinstance(marca, str) and normalizar(marca) == normalizar(
            VALOR_DA_REPETICAO
        )
        if repete and not ultimo:
            raise RegraViolada(
                f"Na linha {numero} da aba {aba.nome!r} está marcado "
                f"{VALOR_DA_REPETICAO!r} em {COLUNA_DE_REPETICAO!r}, mas não há linha "
                "acima para repetir. Preencha esta linha por inteiro."
            )

        herdado: dict[str, object] = {}
        for nome, valor in celulas.items():
            # A PRÓPRIA COLUNA DE REPETIÇÃO NÃO HERDA: herdá-la faria uma linha
            # marcada contaminar todas as de baixo, e a pessoa perderia o controle
            # de onde a cadeia começa.
            if nome == COLUNA_DE_REPETICAO:
                continue
            if repete and valor is None and nome in ultimo:
                celulas[nome] = ultimo[nome]
                herdado[nome] = ultimo[nome]

        # `ultimo` guarda o valor FINAL da linha — o que a pessoa escreveu ou o que
        # esta linha herdou —, para que uma CADEIA de repetições propague o dado
        # original por todas elas.
        for nome, valor in celulas.items():
            if valor is not None and nome != COLUNA_DE_REPETICAO:
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

    # O TETO É CONFERIDO AQUI desde que o `Código` saiu: ele morava dentro da
    # função que conferia a unicidade dos códigos, e teria ido embora com ela — o
    # teste do teto foi o que pegou.
    #
    # Acima de 500 a tela de conferência deixa de ser conferível e a transação fica
    # longa demais para uma requisição. Um dia de 54 cabe dez vezes.
    agendas = por_aba.get(ABA_PRINCIPAL, [])
    if len(agendas) > TETO_DE_AGENDAS:
        raise RegraViolada(
            f"A planilha tem {len(agendas)} agendas e o limite é {TETO_DE_AGENDAS} "
            "por arquivo. Divida em dois envios."
        )
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
    # O CABEÇALHO NÃO É UM CADASTRO DECLARADO, e o nome dele vem da descrição — não
    # de uma lista escrita à mão, que envelhecia quando um rótulo mudava e fazia a
    # palavra "Instituição" virar uma instituição a criar.
    for chave in declarados:
        colunas = colunas_do_cadastro(chave)
        if len(colunas) > 1:
            declarados[chave] = declarados[chave] - {
                normalizar(coluna.nome) for coluna in colunas
            }
    # O MARCADOR SAIU DAS LISTAS junto com a própria ideia dele: a instrução de
    # repetir virou coluna. Não há mais nada a subtrair aqui.
    return declarados


def ler_cadastros_declarados(conteudo: bytes) -> dict[str, dict[str, dict[str, object]]]:
    """Por aba de cadastro: nome normalizado → o que a pessoa escreveu nas outras colunas.

    O PENTE FINO DO DONO DO PRODUTO. As abas de cadastro passaram a ter os campos do
    formulário da plataforma — a abrangência e a relevância da instituição, o cargo e o
    e-mail do interlocutor —, e nada disso servia para nada se o leitor continuasse
    olhando só a coluna B.

    LÊ PELA DESCRIÇÃO, coluna por coluna, e é o que faz uma coluna nova passar a ser
    lida sem nenhuma linha nova aqui. O cabeçalho é reconhecido pelo próprio nome
    descrito, e não por uma lista de nomes possíveis escrita à mão — que era o que
    envelhecia quando um rótulo mudava, e fazia a palavra do cabeçalho virar um cadastro
    a criar.

    O VALOR SAI CRU e não normalizado: o cargo e o e-mail vão para o banco como a pessoa
    escreveu. Quem precisa comparar — a categoria, a instituição — normaliza na hora.
    """
    pasta = _abrir(conteudo)
    declarados: dict[str, dict[str, dict[str, object]]] = {}
    for chave in VOCABULARIOS_QUE_A_IMPORTACAO_CRIA:
        rotulo = ROTULO_DO_VOCABULARIO[chave]
        colunas = colunas_do_cadastro(chave)
        if rotulo not in pasta.sheetnames or len(colunas) < 2:
            declarados[chave] = {}
            continue
        cabecalho = normalizar(colunas[0].nome)
        por_nome: dict[str, dict[str, object]] = {}
        for linha in pasta[rotulo].iter_rows(
            min_col=1, max_col=len(colunas), values_only=True
        ):
            nome = _texto(linha[0])
            if not isinstance(nome, str) or normalizar(nome) == cabecalho:
                continue
            campos: dict[str, object] = {}
            for coluna, bruto in zip(colunas[1:], linha[1:], strict=False):
                valor = _texto(bruto)
                if valor is not None and valor != "":
                    campos[coluna.campo] = valor
            por_nome[normalizar(nome)] = campos
        declarados[chave] = por_nome
    return declarados


