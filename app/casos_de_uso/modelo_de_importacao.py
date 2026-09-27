"""O `.xlsx` que a pessoa baixa para cadastrar agendas em massa.

O FORMATO MORA UMA VEZ SÓ, em `app/dominio/importacao_de_agendas.py`. Este
módulo não descreve nenhuma coluna nem nenhuma aba — ele PERCORRE `FORMATO` e
escreve o que encontra. A Tarefa 4 (o leitor do arquivo preenchido) é a
segunda consumidora da mesma descrição; se as colunas estivessem retiptadas
aqui, uma coluna nova entraria numa cópia e não na outra, e ninguém
perceberia até a planilha chegar cheia com uma coluna que o leitor ignora.

`vocabularios` CHEGA PRONTO. Este caso de uso não abre sessão de banco — quem
consulta `instituicoes`, `interlocutores` etc. é a rota (Tarefa 8). Isso
mantém `gerar` testável com um dicionário Python comum, sem fixture de
Postgres.

DUAS FAMÍLIAS DE ABA DE VOCABULÁRIO. As de `VOCABULARIOS_EDITAVEIS` recebem
uma linha em branco depois do último valor — é o convite mecânico a "escreva
aqui para cadastrar" que a spec pede. As de `VOCABULARIOS_FECHADOS` saem
protegidas (`ws.protection.sheet = True`): mudar clima ou situação é mudança
de regra de negócio (os KPIs dependem delas), não dado de cadastro, e a
proteção torna essa diferença visível na aba, não só documentada em código —
embora, como o comentário de `VOCABULARIOS_FECHADOS` no domínio lembra, o
servidor recuse valor novo nesses vocabulários MESMO que alguém desproteja a
aba manualmente. A proteção aqui é conveniência do Excel, não o controle.

UM VOCABULÁRIO VAZIO NÃO PODE QUEBRAR O ARQUIVO: uma base nova não tem
nenhuma instituição cadastrada, e o modelo ainda precisa abrir e oferecer a
lista suspensa (vazia, mas presente) para a primeira pessoa cadastrar a
primeira.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence

from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_agendas import (
    ABA_PRINCIPAL,
    COLUNA_DA_INSTITUICAO_DA_AGENDA,
    COLUNA_DE_REPETICAO,
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    SEGUNDA_COLUNA_DO_VOCABULARIO,
    VALOR_DA_REPETICAO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
    colunas_do_modelo,
)

#: Linhas de dados que a lista suspensa da aba AGENDAS cobre, além do
#: cabeçalho. Bate exatamente com o teto de 500 agendas por arquivo (ver
#: Restrições globais) — DE PROPÓSITO, não por acaso: convidar a pessoa a
#: preencher a linha 600 quando o servidor vai recusar o arquivo inteiro por
#: passar de 500 é pior do que não ter lista suspensa nenhuma ali, porque ela
#: falsamente sugere que a linha é válida.
_LINHAS_DE_AGENDAS = 500

#: A coluna que recebe a data da agenda. Pelo NOME e não pelo índice: a ordem das
#: colunas segue a sequência dos campos do formulário e já mudou uma vez.
COLUNA_DA_DATA = "Data"

#: O formato da célula, em código do Excel. É o formato brasileiro porque é o que
#: a pessoa digita, e é ele que faz o Excel ler `25/09/2026` como 25 de setembro —
#: numa célula "Geral" a mesma digitação pode virar texto, ou ser lida no formato
#: americano e cair em outro dia.
FORMATO_DA_DATA_NA_TELA = "DD/MM/YYYY"

#: O piso da validação de data. Ele NÃO julga a agenda: existe só para dar ao
#: Excel um critério de data a comparar, porque a validação de data pede um
#: operador. Sem teto de propósito — agenda prevista é caso normal (`status` tem
#: "previsto"), e um teto recusaria dado legítimo, que é pior que não travar.
PISO_DA_DATA = "DATE(2000,1,1)"


#: Linhas de dados que a lista suspensa das abas FILHAS cobre (Participantes,
#: Pessoas da Aegea, Materiais). Estas NÃO têm o teto de Agendas: uma agenda
#: pode ter vários participantes ou vários materiais, então o mesmo limite de
#: 500 aplicado a elas sufocaria uma única agenda com muita gente — por isso
#: usam um valor único generoso, em vez do teto que rege a aba-mãe.
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


def _fonte_da_lista(coluna, colunas: Sequence, quantos_interlocutores: int) -> str:
    """A fonte da lista suspensa de uma coluna: o nome definido, ou a fórmula
    dependente das colunas de interlocutor.

    A RELAÇÃO QUE O FRONT TEM. `interlocutoresDaInstituicao` filtra a lista pelo
    `instituicao_id` da instituição escolhida; aqui o equivalente é um `OFFSET` no
    bloco daquele órgão dentro da aba de interlocutores, que sai AGRUPADA por
    instituição justamente para isto.

    O `IF(ISNA(MATCH(...)))` é a rede, e ela é necessária: órgão NOVO, digitado na
    célula e declarado na aba, é caminho normal desta funcionalidade — e um
    `MATCH` que não acha devolveria erro, deixando a célula sem suspensa nenhuma.
    Nesse caso a lista volta a ser a de todos os interlocutores, que é o
    comportamento de antes desta mudança. Degradar para o que já funcionava é
    diferente de quebrar.

    Cabe nos 255 caracteres que o Excel aceita em `formula1` — com o rótulo da aba
    e a coluna da instituição, fica em torno de 180.
    """
    if coluna.vocabulario != "interlocutores":
        return f"={coluna.vocabulario}"
    rotulo = ROTULO_DO_VOCABULARIO["interlocutores"]
    folha = f"'{rotulo}'" if " " in rotulo else rotulo
    # A última linha do bloco de dados: o cabeçalho, os pares, o marcador e a
    # linha em branco do convite a cadastrar.
    ultima = quantos_interlocutores + 3
    instituicao = f"${_letra_de_coluna(colunas, COLUNA_DA_INSTITUICAO_DA_AGENDA)}2"
    orgaos = f"{folha}!$B$2:$B${ultima}"
    procura = f"MATCH({instituicao},{orgaos},0)"
    return (
        f"=IF(ISNA({procura}),interlocutores,"
        f"OFFSET({folha}!$A$2,{procura}-1,0,COUNTIF({orgaos},{instituicao}),1))"
    )


def _letra_de_coluna(colunas: Sequence, nome: str) -> str:
    """A letra da coluna `nome` DENTRO DAQUELE RECORTE.

    RECEBE AS COLUNAS E NÃO A ABA porque a letra depende do modelo: a Instituição é
    a sexta no completo e a sexta no simplificado, mas o Clima é a vigésima quinta
    num e a décima sétima no outro. Uma letra calculada sobre a descrição inteira
    validaria a coluna errada no simplificado — em silêncio, que é o pior defeito
    possível numa planilha.

    PÚBLICA porque a fórmula da suspensa dependente precisa dela, e um teste
    confere que é a coluna certa nos dois modelos.
    """
    from openpyxl.utils import get_column_letter

    for indice, coluna in enumerate(colunas, start=1):
        if coluna.nome == nome:
            return get_column_letter(indice)
    raise RegraViolada(f"Este modelo não tem a coluna {nome!r}.")


def gerar(
    vocabularios: Mapping[str, list[str]],
    interlocutores: Sequence[tuple[str, str]] = (),
    modelo: str = "completo",
) -> bytes:
    """O `.xlsx` de cadastro: as quatro abas de preenchimento, vazias, mais
    uma aba por vocabulário com a lista suspensa já ligada à coluna certa.

    `vocabularios` é chave (a mesma de `VOCABULARIOS_EDITAVEIS` /
    `VOCABULARIOS_FECHADOS`) → lista de valores válidos hoje. Uma chave
    ausente do dicionário conta como lista vazia — o mesmo tratamento que uma
    lista vazia explícita recebe.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        from openpyxl.utils import get_column_letter
        from openpyxl.workbook.defined_name import DefinedName
        from openpyxl.worksheet.datavalidation import DataValidation
    except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
        raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

    pasta = Workbook()
    pasta.remove(pasta.active)  # a Workbook nasce com uma aba "Sheet" que ninguém pediu

    # -- abas de preenchimento: só o cabeçalho, quem preenche escreve o resto -
    # AS COLUNAS SAEM DO RECORTE ESCOLHIDO. `colunas_do_modelo` recusa um nome de
    # modelo que não existe, então um erro de digitação aqui não gera arquivo torto.
    colunas_da_agenda = colunas_do_modelo(modelo)
    for aba in FORMATO:
        planilha = pasta.create_sheet(aba.nome)
        planilha.append([coluna.nome for coluna in colunas_da_agenda])
        if aba.nome == "Agendas":
            # O teto de 500 agendas por arquivo não aparece em NENHUMA tela
            # até o upload recusar o arquivo inteiro na linha 501, sem dizer
            # por quê. A nota avisa ANTES de a pessoa passar do limite — mas
            # vai de COMENTÁRIO na célula do cabeçalho "Código", não de uma
            # célula extra na linha 1: a Tarefa 4 lê essa MESMA linha contra
            # `FORMATO` para casar cabeçalho com coluna, e uma 26ª célula
            # numa linha de 25 nomes é exatamente a divergência que o
            # docstring do domínio existe para evitar — o comentário fica
            # visível a quem abre a aba (marcador vermelho, texto ao passar o
            # mouse) e invisível a quem lê valor de célula.
            # UM COMENTÁRIO, DOIS FATOS, na primeira célula onde a pessoa passa
            # o mouse. O do Código vem antes porque é a dúvida imediata de quem
            # abre o arquivo: a coluna fica em branco na maioria das linhas, e sem
            # explicação quem preenche não sabe se esqueceu alguma coisa.
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
    # A ORDEM segue a da spec — editáveis primeiro, fechadas depois — e cada
    # grupo em ordem alfabética para que o arquivo gerado seja determinístico
    # (útil para conferir a mesma saída duas vezes, e para o teste que abre o
    # arquivo não depender de uma ordem de iteração de frozenset, que o
    # Python não garante).
    for chave in sorted(VOCABULARIOS_EDITAVEIS) + sorted(VOCABULARIOS_FECHADOS):
        valores = vocabularios.get(chave, [])
        rotulo = ROTULO_DO_VOCABULARIO[chave]
        # Nenhum rótulo repete o nome de uma aba de `FORMATO` — o domínio
        # garante isso (`test_nenhum_rotulo_de_vocabulario_repete_nome_de_
        # aba_de_preenchimento`), então `create_sheet` aqui nunca colide com
        # uma aba de preenchimento já criada, e o nome que a pessoa vê é
        # exatamente `rotulo`, sem desvio.
        planilha = pasta.create_sheet(rotulo)
        # A ABA DE INSTITUIÇÕES TEM CABEÇALHO E DUAS COLUNAS, e é a única. O tipo
        # deriva a frente da agenda, então criar uma instituição sem ele obrigaria
        # o servidor a chutar — e o chute erra a frente de toda agenda daquela
        # instituição. As outras abas seguem sendo uma lista de nomes, porque nada
        # mais é preciso para criar um interlocutor ou um tema.
        segunda_coluna = SEGUNDA_COLUNA_DO_VOCABULARIO.get(chave)
        if segunda_coluna:
            planilha.append([rotulo_singular(chave), segunda_coluna])
        if chave == "interlocutores":
            # AGRUPADOS E CONTÍGUOS POR INSTITUIÇÃO, e não é estética: a suspensa
            # dependente é um `OFFSET` a partir da primeira linha do órgão, com
            # altura igual à contagem dele. Linhas do mesmo órgão separadas fariam
            # a suspensa daquele órgão mostrar as pessoas do vizinho.
            for nome, instituicao in sorted(
                interlocutores, key=lambda par: (par[1] or "", par[0])
            ):
                planilha.append([nome, instituicao])
        else:
            for valor in valores:
                planilha.append([valor])
        # A LISTA É SÓ O VOCABULÁRIO. O marcador `idem` ocupava a última linha de
        # TODAS estas abas, onde nunca foi um valor daquele vocabulário: quem abria
        # a suspensa de Clima via uma instrução de preenchimento entre os climas. A
        # instrução virou a coluna `Repetir a linha de cima`.
        quantos = len(interlocutores) if chave == "interlocutores" else len(valores)
        ultima_linha = quantos + (1 if segunda_coluna else 0)
        if chave in VOCABULARIOS_FECHADOS:
            planilha.protection.sheet = True
        else:
            # A linha em branco depois do último valor é o convite a
            # cadastrar: escrever aqui é a declaração de intenção que a spec
            # distingue de digitar direto na célula da agenda.
            ultima_linha += 1

        # Uma base nova pode não ter NENHUM valor ainda (zero instituições
        # cadastradas). `max(..., 1)` garante que o intervalo sempre cubra ao
        # menos a linha 1 — vazia, mas um `DefinedName` sem nenhuma célula
        # dentro do intervalo é o que de fato quebraria o arquivo.
        primeira = 2 if segunda_coluna else 1
        intervalo = f"'{rotulo}'!$A${primeira}:$A${max(ultima_linha, primeira)}"
        pasta.defined_names[chave] = DefinedName(chave, attr_text=intervalo)

    # -- a lista de tipos, na coluna B da aba de instituições -----------------
    #
    # Sem ela a pessoa digita "orgão" com acento ou "veículo" e a importação
    # recusa um tipo que ela acha que escreveu certo.
    from openpyxl.worksheet.datavalidation import DataValidation as _DV

    aba_das_instituicoes = pasta[ROTULO_DO_VOCABULARIO["instituicoes"]]
    categorias = _DV(
        # APONTA PARA A ABA da taxonomia, e não para uma lista escrita aqui: são
        # dez nomes longos, e uma lista literal na fórmula estoura o limite de 255
        # caracteres que o Excel impõe a `formula1`.
        type="list",
        formula1="=categorias_publico",
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Categoria inválida",
        error="Escolha uma das categorias da lista.",
    )
    aba_das_instituicoes.add_data_validation(categorias)
    categorias.add(f"B2:B{_LINHAS_DE_ABAS_FILHAS}")

    # -- a suspensa de instituições na coluna B da aba de interlocutores ------
    #
    # Quem cadastra alguém novo escreve o nome na coluna A e ESCOLHE o órgão na B.
    # Digitar o órgão à mão erraria a grafia — e um órgão que não casa com o
    # cadastro deixa a pessoa nascendo solta, que é exatamente o que esta coluna
    # existe para impedir. Sem `showErrorMessage`, como toda coluna de vocabulário
    # editável: o órgão novo, declarado na aba de instituições, também vale aqui.
    aba_dos_interlocutores = pasta[ROTULO_DO_VOCABULARIO["interlocutores"]]
    de_quem = _DV(type="list", formula1="=instituicoes", allow_blank=True)
    aba_dos_interlocutores.add_data_validation(de_quem)
    de_quem.add(f"B2:B{_LINHAS_DE_ABAS_FILHAS}")

    # -- listas suspensas: uma DataValidation por coluna com vocabulário ------
    for aba in FORMATO:
        planilha = pasta[aba.nome]
        teto = _LINHAS_DE_AGENDAS
        for indice, coluna in enumerate(colunas_da_agenda, start=1):
            letra = get_column_letter(indice)
            if coluna.nome == COLUNA_DE_REPETICAO:
                # UMA SUSPENSA DE UM VALOR SÓ, escrita na própria fórmula: é mais
                # rápida de preencher que um sim/não, e não deixa dúvida sobre o
                # que significa a célula vazia.
                #
                # NÃO TRAVA, como as outras colunas editáveis: travar transformaria
                # um engano de digitação nesta coluna em arquivo recusado, quando o
                # leitor simplesmente ignora o que não reconhece.
                repetir = DataValidation(
                    type="list", formula1=f'"{VALOR_DA_REPETICAO}"', allow_blank=True
                )
                planilha.add_data_validation(repetir)
                repetir.add(f"{letra}2:{letra}{teto + 1}")
                continue
            if coluna.vocabulario is None:
                continue
            fechado = coluna.vocabulario in VOCABULARIOS_FECHADOS
            # A ASSIMETRIA ABAIXO É DE PROPÓSITO — as duas metades existem
            # por motivos opostos, e trocar uma pela outra quebra algo:
            #
            # FECHADO trava de verdade (`showErrorMessage=True`). Sem isto, o
            # openpyxl desenha a seta mas `DataValidation.showErrorMessage`
            # nasce `False` — o Excel aceita QUALQUER valor digitado por
            # cima, e a lista suspensa vira decoração, não restrição. É "a
            # restrição que temos no front" que o cliente pediu, e a spec é
            # explícita: um valor novo num vocabulário fechado é mudança de
            # regra de negócio, não dado de cadastro — não pode entrar
            # digitando na célula.
            #
            # EDITÁVEL fica como está, sem `showErrorMessage` — e isto
            # também é de propósito, não a metade que "esqueceram" de trocar.
            # Digitar um nome novo na coluna e casar com uma linha nova na
            # aba editável É o caminho desenhado para cadastrar: é o que a
            # Tarefa 5 classifica como confirmação de criação, por ter sido
            # DECLARADO na aba certa. Travar aqui mataria a própria função
            # que a importação em massa existe para servir.
            validacao = DataValidation(
                type="list",
                formula1=_fonte_da_lista(coluna, colunas_da_agenda, len(interlocutores)),
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
    # AS DUAS METADES SÃO NECESSÁRIAS, e cada uma resolve um problema diferente:
    #
    # A VALIDAÇÃO recusa na hora o que não é data — `25/09/26`, `set/25`,
    # `25.09.2026`, `amanhã`. Sem ela nada é recusado no Excel: tudo isso chega
    # ao servidor como texto, e a conferência acusa "data ilegível" numa linha
    # que a pessoa jurava ter preenchido, depois de ela já ter feito as 54.
    #
    # O FORMATO DA CÉLULA é o que faz o Excel INTERPRETAR a digitação como data
    # brasileira. Numa célula "Geral", `25/09/2026` pode virar texto — e então a
    # validação recusaria o que estava certo, que é o pior dos mundos: a pessoa
    # digita a data correta e o arquivo diz que não é data.
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

    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()
