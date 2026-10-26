"""O `.xlsx` que a pessoa baixa para cadastrar agendas em massa.

O FORMATO MORA EM `app/dominio/importacao_de_agendas.py`. Este módulo não
descreve coluna nem aba: percorre `FORMATO` e escreve o que encontra. O leitor
do arquivo preenchido lê a mesma descrição, e uma coluna retiptada aqui
entraria numa cópia só.

`vocabularios` chega pronto — quem consulta o banco é a rota —, e chave ausente
vale como lista vazia: base nova precisa gerar arquivo que abra, com a suspensa
presente e vazia.

As abas de `VOCABULARIOS_FECHADOS` saem protegidas (`protection.sheet`). É
conveniência do Excel, não o controle: o servidor recusa valor novo nesses
vocabulários mesmo que alguém desproteja a aba.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence

from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_agendas import (
    ABA_PRINCIPAL,
    CAMPO_DOS_TEMAS,
    COLUNA_DA_INSTITUICAO_DA_AGENDA,
    COLUNA_DE_REPETICAO,
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VALOR_DA_REPETICAO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
    colunas_do_cadastro,
    colunas_do_modelo,
    tipo_da_coluna,
    tipo_da_coluna_de_cadastro,
)

#: Linhas de dados que a lista suspensa da aba AGENDAS cobre, além do
#: cabeçalho. Bate com o teto de 500 agendas por arquivo de propósito: oferecer
#: suspensa na linha 600, que o servidor vai recusar, sugere que a linha é
#: válida.
_LINHAS_DE_AGENDAS = 500

#: A coluna que recebe a data da agenda. Pelo NOME e não pelo índice: a ordem das
#: colunas segue a sequência dos campos do formulário e já mudou uma vez.
COLUNA_DA_DATA = "Data"

#: Tipo de coluna → largura no Excel, em CARACTERES (a unidade do openpyxl).
#: O tipo sai da mesma descrição que a tela usa (`tipo_da_coluna`), para que
#: coluna nova não precise entrar numa tabela por nome. Os números não são os da
#: tela convertidos: o Excel mede em caracteres, e a tela em pixels.
LARGURA_NO_EXCEL: dict[str, float] = {
    "marca": 22,  # o cabeçalho "Repetir a linha de cima" é mais largo que o valor
    "data": 12,
    "sigla": 6,
    "lista": 28,
    "prosa": 48,
    "texto": 18,
}

#: O formato da célula, em código do Excel. É ele que faz o Excel ler
#: `25/09/2026` como 25 de setembro: numa célula "Geral" a mesma digitação pode
#: virar texto, ou ser lida no formato americano e cair em outro dia.
FORMATO_DA_DATA_NA_TELA = "DD/MM/YYYY"

#: O piso da validação de data. Ele NÃO julga a agenda: existe só para dar ao
#: Excel um critério de data a comparar, porque a validação de data pede um
#: operador. Sem teto de propósito — agenda prevista é caso normal (`status` tem
#: "previsto"), e um teto recusaria dado legítimo, que é pior que não travar.
PISO_DA_DATA = "DATE(2000,1,1)"


#: Linhas de dados que a suspensa das abas FILHAS cobre. Não seguem o teto de
#: Agendas: uma agenda sozinha pode ter muita gente ou muito material, e o
#: mesmo limite de 500 a sufocaria.
_LINHAS_DE_ABAS_FILHAS = 2000


def rotulo_singular(chave: str) -> str:
    """O nome da COLUNA na aba de vocabulário, quando ela tem cabeçalho.

    "Instituições" nomeia a aba; "Instituição" nomeia a coluna. A diferença
    importa porque o cabeçalho fica ao lado de "Tipo", e um plural ali leria como
    se a célula aceitasse várias.
    """
    return {"instituicoes": "Instituição", "interlocutores": "Interlocutor"}.get(
        chave, ROTULO_DO_VOCABULARIO[chave]
    )


#: A coluna que o gerador RESERVA e nunca escreve, em cada aba que sai em pares.
#: É com ela que a suspensa fica vazia: uma lista não aceita intervalo de altura
#: zero, então "nenhuma opção" se faz apontando para uma célula garantidamente
#: branca. Um teste confere que ela está vazia.
COLUNA_DE_RESERVA = "H"


def _ultima_linha_preenchida(coluna: str, primeira: int) -> str:
    """A fórmula que devolve o NÚMERO da última linha com conteúdo numa coluna.

    NÃO É A CONTAGEM de linhas preenchidas: com uma linha vazia no meio, a
    contagem fica menor que o número da última linha, e os valores abaixo do
    buraco caem fora da suspensa.

    DOIS BRAÇOS DE `MATCH`, um por tipo de valor: `REPT("z",255)` acha a última
    célula de TEXTO, e um número grande a última NUMÉRICA — a Relevância sai
    como número, e um braço só deixaria a lista dela com um item. `IFERROR`
    cobre a coluna sem valor daquele tipo, e `MAX(..., primeira)` cobre a base
    vazia: intervalo de altura zero faz o Excel recusar o arquivo ao ABRIR.

    `COUNTA` FICA NO `MAX`, COMO PISO, porque `MATCH` sem o terceiro argumento
    usa o modo aproximado, que a documentação descreve para intervalo ORDENADO.
    Aqui funciona porque o valor procurado é maior que qualquer texto (ou
    número) e a busca nunca tem para onde descer, mas isso é garantia de
    implementação. Nenhum dos três MEDIDORES passa da última linha preenchida,
    então o maior deles nunca aponta para além dela. O piso `primeira` é a
    exceção deliberada: na coluna vazia ele devolve a primeira linha de dados,
    que é a célula em branco que o intervalo precisa ter para existir.
    """
    return (
        f"MAX(COUNTA({coluna}),"
        f'IFERROR(MATCH(REPT("z",255),{coluna}),0),'
        f"IFERROR(MATCH(9.99999999999999E+307,{coluna}),0),{primeira})"
    )


def _suspensa_dependente(vocabulario: str, celula_do_dono: str) -> str:
    """A fonte de uma suspensa que se reduz pelo valor de OUTRA célula da mesma linha.

    UMA FÓRMULA PARA OS DOIS CASOS: o interlocutor que se reduz pela instituição
    da agenda, e a subcategoria que se reduz pela categoria de público da linha
    do cadastro.

    COMO FUNCIONA: a aba do vocabulário sai com o valor na coluna A e o DONO na
    coluna B, agrupada por dono. `COUNTIF` diz quantos são daquele dono, `MATCH`
    acha a primeira linha dele, e `OFFSET` recorta o bloco.

    SEM DONO, OU COM DONO SEM NINGUÉM, A LISTA FICA VAZIA — e não a lista
    inteira. O servidor recusa interlocutor de outra instituição, porque um
    interlocutor fala por uma instituição só; oferecer a base toda convidaria ao
    erro que o passo seguinte rejeita. Vazia diz "este órgão ainda não tem
    ninguém", como o front já faz. Digitar continua permitido, porque a coluna
    não trava: é assim que se declara alguém novo.
    """
    rotulo = ROTULO_DO_VOCABULARIO[vocabulario]
    folha = f"'{rotulo}'" if " " in rotulo else rotulo
    donos = f"{folha}!$B$2:$B${_LINHAS_DE_ABAS_FILHAS}"
    quantos = f"COUNTIF({donos},{celula_do_dono})"
    # `COUNTIF=0` E NÃO `ISNA(MATCH)`: a mesma pergunta, e esta cobre de uma vez o dono
    # vazio e o dono sem ninguém — que é o caso que estava errado.
    return (
        f"IF({quantos}=0,{folha}!${COLUNA_DE_RESERVA}$1,"
        f"OFFSET({folha}!$A$2,MATCH({celula_do_dono},{donos},0)-1,0,{quantos},1))"
    )


def _fonte_da_lista(coluna, colunas: Sequence) -> str:
    """A fonte da suspensa de uma coluna da AGENDA: o nome do vocabulário, ou a
    fórmula que se reduz pela instituição da linha.

    É a relação que o front tem em `interlocutoresDaInstituicao`. A aba de
    interlocutores sai agrupada por instituição justamente para permitir o
    recorte.
    """
    if coluna.vocabulario != "interlocutores":
        return coluna.vocabulario
    return _suspensa_dependente(
        "interlocutores",
        f"${_letra_de_coluna(colunas, COLUNA_DA_INSTITUICAO_DA_AGENDA)}2",
    )


def _letra_de_coluna(colunas: Sequence, nome: str) -> str:
    """A letra da coluna `nome` DENTRO DAQUELE RECORTE.

    RECEBE AS COLUNAS E NÃO A ABA porque a letra depende do modelo: o Clima é a
    vigésima quinta coluna no completo e a décima sétima no simplificado. Uma
    letra calculada sobre a descrição inteira validaria a coluna errada no
    simplificado, em silêncio. Um teste confere a coluna nos dois modelos.
    """
    from openpyxl.utils import get_column_letter

    for indice, coluna in enumerate(colunas, start=1):
        if coluna.nome == nome:
            return get_column_letter(indice)
    raise RegraViolada(f"Este modelo não tem a coluna {nome!r}.")


def gerar(
    vocabularios: Mapping[str, list[str]],
    pares: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    modelo: str = "completo",
) -> bytes:
    """O `.xlsx` de cadastro: as quatro abas de preenchimento, vazias, mais uma
    aba por vocabulário com a lista suspensa já ligada à coluna certa.

    `vocabularios` é chave (a de `VOCABULARIOS_EDITAVEIS` /
    `VOCABULARIOS_FECHADOS`) → valores válidos hoje. Chave ausente vale como
    lista vazia.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        from openpyxl.formatting.rule import FormulaRule
        from openpyxl.styles import PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.workbook.defined_name import DefinedName
        from openpyxl.worksheet.datavalidation import DataValidation
    except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
        raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

    pasta = Workbook()
    pasta.remove(pasta.active)  # a Workbook nasce com uma aba "Sheet" que ninguém pediu

    # -- abas de preenchimento: só o cabeçalho, quem preenche escreve o resto -
    # As colunas saem do recorte escolhido, e `colunas_do_modelo` recusa nome de
    # modelo que não existe. Os pares são "valor + dono" — o interlocutor com a
    # instituição, a subcategoria com a categoria —, e é deles que a suspensa
    # dependente vive: ela procura o dono na coluna B da aba do vocabulário.
    os_pares = dict(pares or {})
    colunas_da_agenda = colunas_do_modelo(modelo)
    for aba in FORMATO:
        planilha = pasta.create_sheet(aba.nome)
        planilha.append([coluna.nome for coluna in colunas_da_agenda])
        if aba.nome == "Agendas":
            # O teto de 500 agendas não aparece em tela nenhuma até o upload
            # recusar o arquivo na linha 501. O aviso vai de COMENTÁRIO na
            # célula do cabeçalho, e não de célula extra na linha 1: o leitor
            # casa essa mesma linha contra `FORMATO`, e uma 26ª célula numa
            # linha de 25 nomes seria divergência de cabeçalho.
            planilha["A1"].comment = Comment(
                "Deixe em branco quando a agenda não tiver participante nem "
                "material: o servidor põe um código sozinho."
                "\n\n"
                "Escreva um código (A1, A2...) quando ela tiver: é ele que liga "
                "esta linha às abas Participantes, Pessoas da Aegea e Materiais, "
                "e o servidor não tem como adivinhar qual pessoa esteve em qual "
                "reunião."
                "\n\n"
                "Máximo de 500 agendas por arquivo.",
                "Painel Reputacional",
            )

    # -- abas de vocabulário: uma lista em coluna A, com DefinedName ----------
    #
    # A ORDEM — editáveis primeiro, fechadas depois, cada grupo em ordem
    # alfabética — deixa o arquivo determinístico: iteração de frozenset não tem
    # ordem garantida, e o teste que abre o arquivo depende disso.
    for chave in sorted(VOCABULARIOS_EDITAVEIS) + sorted(VOCABULARIOS_FECHADOS):
        valores = vocabularios.get(chave, [])
        rotulo = ROTULO_DO_VOCABULARIO[chave]
        # Nenhum rótulo repete nome de aba de `FORMATO` (o domínio tem teste
        # para isso), então `create_sheet` não colide e o nome que a pessoa vê é
        # exatamente `rotulo`.
        planilha = pasta.create_sheet(rotulo)
        # AS COLUNAS VÊM DA DESCRIÇÃO, e são as do formulário da plataforma —
        # uma aba de cadastro com menos campos cria cadastro pela metade. O que
        # o formulário NÃO pergunta continua fora: esfera e tipo da instituição
        # são derivados, e pedi-los deixaria a planilha contradizer a derivação.
        colunas = colunas_do_cadastro(chave)
        tem_cabecalho = len(colunas) > 1
        if tem_cabecalho:
            planilha.append([coluna.nome for coluna in colunas])
        if chave in os_pares:
            # AGRUPADOS E CONTÍGUOS POR DONO, e não é estética: a suspensa dependente
            # recorta o bloco daquele dono. Linhas do mesmo dono separadas fariam a
            # suspensa mostrar os valores do vizinho.
            for valor, dono in sorted(
                os_pares[chave], key=lambda par: (par[1] or "", par[0])
            ):
                planilha.append([valor, dono])
        else:
            for valor in valores:
                planilha.append([valor])
        if chave in VOCABULARIOS_FECHADOS:
            planilha.protection.sheet = True

        # UMA SUSPENSA POR COLUNA QUE TEM VOCABULÁRIO, como na aba de agendas:
        # sem ela o campo entra como texto livre, e o erro de grafia vira
        # cadastro errado em vez de pendência.
        for posicao, coluna in enumerate(colunas, start=1):
            if not coluna.vocabulario:
                continue
            letra_do_cadastro = get_column_letter(posicao)
            dono = (
                f"${get_column_letter(
                    [outra.nome for outra in colunas].index(coluna.depende_de) + 1
                )}2"
                if coluna.depende_de
                else ""
            )
            suspensa = DataValidation(
                type="list",
                formula1=(
                    _suspensa_dependente(coluna.vocabulario, dono)
                    if dono
                    else coluna.vocabulario
                ),
                allow_blank=True,
            )
            planilha.add_data_validation(suspensa)
            suspensa.add(
                f"{letra_do_cadastro}2:{letra_do_cadastro}{_LINHAS_DE_ABAS_FILHAS}"
            )

        # A LARGURA NA DIMENSÃO DA COLUNA, como na aba de agendas: por célula
        # ela materializaria as 2000 linhas da suspensa, e o `Ctrl+End` de quem
        # abre a aba iria para o fim do nada.
        for posicao, coluna in enumerate(colunas, start=1):
            planilha.column_dimensions[get_column_letter(posicao)].width = (
                LARGURA_NO_EXCEL[tipo_da_coluna_de_cadastro(coluna)]
            )

        primeira = 2 if tem_cabecalho else 1
        # `INDEX` E NÃO `OFFSET`: `OFFSET` é volátil, e função volátil em
        # validação de dados é onde o Excel se recusa a resolver em algumas
        # versões. A expressão inteira é um INTERVALO — `$A$2:INDEX(...)` —, a
        # forma que a validação lê com menos ressalvas.
        #
        # O INTERVALO ACOMPANHA O CONTEÚDO, calculado pelo Excel ao abrir a
        # lista: quem acrescenta um valor na aba o vê na suspensa da agenda. O
        # fim é a ÚLTIMA LINHA PREENCHIDA (ver `_ultima_linha_preenchida`), e
        # não a contagem de linhas preenchidas.
        coluna_inteira = f"'{rotulo}'!$A:$A"
        pasta.defined_names[chave] = DefinedName(
            chave,
            attr_text=(
                f"'{rotulo}'!$A${primeira}:INDEX({coluna_inteira},"
                f"{_ultima_linha_preenchida(coluna_inteira, primeira)})"
            ),
        )



    # -- listas suspensas: uma DataValidation por coluna com vocabulário ------
    for aba in FORMATO:
        planilha = pasta[aba.nome]
        teto = _LINHAS_DE_AGENDAS
        for indice, coluna in enumerate(colunas_da_agenda, start=1):
            letra = get_column_letter(indice)
            if coluna.nome == COLUNA_DE_REPETICAO:
                # UMA SUSPENSA DE UM VALOR SÓ, escrita na própria fórmula:
                # mais rápida de preencher que um sim/não, e sem dúvida sobre o
                # que significa a célula vazia. NÃO TRAVA: engano de digitação
                # aqui viraria arquivo recusado, e o leitor ignora o que não
                # reconhece.
                repetir = DataValidation(
                    type="list", formula1=f'"{VALOR_DA_REPETICAO}"', allow_blank=True
                )
                planilha.add_data_validation(repetir)
                repetir.add(f"{letra}2:{letra}{teto + 1}")
                continue
            if coluna.vocabulario is None:
                continue
            fechado = coluna.vocabulario in VOCABULARIOS_FECHADOS
            # A ASSIMETRIA ABAIXO É DE PROPÓSITO:
            #
            # FECHADO trava de verdade (`showErrorMessage=True`). Sem isso o
            # openpyxl desenha a seta mas o Excel aceita qualquer valor digitado
            # por cima, e a suspensa vira decoração. Valor novo em vocabulário
            # fechado é mudança de regra de negócio, feita em código.
            #
            # EDITÁVEL fica sem `showErrorMessage`: digitar um nome novo na
            # coluna e casar com uma linha nova na aba editável É o caminho
            # desenhado para cadastrar, e travar aqui mataria a função que a
            # importação em massa existe para servir.
            validacao = DataValidation(
                type="list",
                formula1=_fonte_da_lista(coluna, colunas_da_agenda),
                allow_blank=True,
                showErrorMessage=fechado,
                errorTitle="Valor fora da lista" if fechado else None,
                error=(
                    f'"{ROTULO_DO_VOCABULARIO[coluna.vocabulario]}" é um vocabulário '
                    "fechado: escolha um valor da lista. Um valor novo aqui é mudança "
                    "de regra de negócio, feita em código — não pela planilha."
                    if fechado
                    else None
                ),
            )
            planilha.add_data_validation(validacao)
            validacao.add(f"{letra}2:{letra}{teto + 1}")

    # -- a coluna Data: travada como data, e formatada como data --------------
    #
    # A VALIDAÇÃO recusa na hora o que não é data (`25/09/26`, `set/25`,
    # `amanhã`). Sem ela isso chega ao servidor como texto, e a conferência
    # acusa "data ilegível" depois de a pessoa ter preenchido o arquivo inteiro.
    #
    # O FORMATO DA CÉLULA é o que faz o Excel INTERPRETAR a digitação como data
    # brasileira. Numa célula "Geral" ela pode virar texto, e então a validação
    # recusaria justamente o que estava certo.
    agendas = pasta[ABA_PRINCIPAL]
    indice_da_data = next(
        (
            indice
            for indice, coluna in enumerate(colunas_da_agenda, start=1)
            if coluna.nome == COLUNA_DA_DATA
        ),
        None,
    )
    if indice_da_data is not None:
        letra_da_data = get_column_letter(indice_da_data)
        faixa_da_data = f"{letra_da_data}2:{letra_da_data}{_LINHAS_DE_AGENDAS + 1}"
        data_valida = DataValidation(
            type="date",
            operator="greaterThanOrEqual",
            formula1=PISO_DA_DATA,
            # EM BRANCO CONTINUA PASSANDO: a linha vazia é o normal no meio de um
            # arquivo, e o `idem` herda a data da linha de cima. Travar o branco
            # aqui brigaria com as duas coisas.
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Data inválida",
            error=(
                "Escreva a data no formato dd/mm/aaaa — por exemplo 25/09/2026. "
                "O texto não vale: a agenda é ordenada e filtrada por data, e o "
                "que não é data não chega ao painel."
            ),
        )
        agendas.add_data_validation(data_valida)
        data_valida.add(faixa_da_data)
        # NA DIMENSÃO DA COLUNA, e não célula por célula: escrever o formato em
        # `A2..A501` CRIA as 500 células, o arquivo passa a ter 501 linhas usadas
        # e o `Ctrl+End` de quem abre o modelo vai para o fim do nada.
        agendas.column_dimensions[letra_da_data].number_format = FORMATO_DA_DATA_NA_TELA

    # -- o tema repetido fica VERMELHO enquanto a pessoa preenche -------------
    #
    # TIRAR O TEMA ESCOLHIDO DAS OUTRAS COLUNAS não dá: uma célula aceita uma
    # validação só, e uma lista não sabe excluir o que as vizinhas usaram. As
    # saídas seriam piores — `COUNTIF` perderia a suspensa com os assuntos, e
    # uma suspensa filtrada por linha pediria 500 × 18 fórmulas auxiliares num
    # arquivo que precisa abrir no Excel de quem recebe por e-mail.
    #
    # A formatação condicional avisa na hora e mantém a suspensa inteira. A
    # trava de verdade é a conferência, que retira a repetição e diz em qual
    # coluna o assunto já estava — ver `importar_agendas`.
    indices_de_tema = [
        indice
        for indice, coluna in enumerate(colunas_da_agenda, start=1)
        if coluna.campo == CAMPO_DOS_TEMAS
    ]
    if len(indices_de_tema) > 1:
        primeira = get_column_letter(min(indices_de_tema))
        ultima = get_column_letter(max(indices_de_tema))
        faixa = f"{primeira}2:{ultima}{_LINHAS_DE_AGENDAS + 1}"
        # `$` NAS COLUNAS E NÃO NA LINHA: o intervalo contado tem de ser o das
        # colunas de tema DAQUELA linha. Fixar a linha compararia tudo com a 2.
        agendas.conditional_formatting.add(
            faixa,
            FormulaRule(
                formula=[f'AND({primeira}2<>"",COUNTIF(${primeira}2:${ultima}2,{primeira}2)>1)'],
                fill=PatternFill(start_color="FFF4C7C3", end_color="FFF4C7C3", fill_type="solid"),
                stopIfTrue=False,
            ),
        )

    # -- a largura de cada coluna, pelo tipo do dado --------------------------
    #
    # SEGUE O RECORTE e não a posição: no simplificado a coluna 17 é o Clima e no
    # completo é o Relato, e uma largura por posição daria o tamanho do parágrafo
    # para a lista suspensa.
    for indice, coluna in enumerate(colunas_da_agenda, start=1):
        agendas.column_dimensions[get_column_letter(indice)].width = LARGURA_NO_EXCEL[
            tipo_da_coluna(coluna)
        ]

    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()
