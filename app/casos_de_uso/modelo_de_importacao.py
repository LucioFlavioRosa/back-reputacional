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
#: cabeçalho. Bate exatamente com o teto de 500 agendas por arquivo (ver
#: Restrições globais) — DE PROPÓSITO, não por acaso: convidar a pessoa a
#: preencher a linha 600 quando o servidor vai recusar o arquivo inteiro por
#: passar de 500 é pior do que não ter lista suspensa nenhuma ali, porque ela
#: falsamente sugere que a linha é válida.
_LINHAS_DE_AGENDAS = 500

#: A coluna que recebe a data da agenda. Pelo NOME e não pelo índice: a ordem das
#: colunas segue a sequência dos campos do formulário e já mudou uma vez.
COLUNA_DA_DATA = "Data"

#: Tipo de coluna → largura no Excel, em CARACTERES (a unidade do openpyxl).
#:
#: A MESMA NECESSIDADE QUE A GRADE TEM, no outro lugar onde a pessoa encontra a
#: planilha: o arquivo saía com todas as colunas do mesmo tamanho, o Relato tão
#: estreito quanto a UF — e é no Relato que ela digita um parágrafo.
#:
#: O TIPO VEM DA MESMA DESCRIÇÃO que a tela usa (`tipo_da_coluna`). Uma tabela de
#: larguras por NOME de coluna, escrita aqui, envelheceria na primeira coluna nova e
#: divergiria da tela no dia em que uma das duas mudasse.
#:
#: Os números não são os da tela convertidos: o Excel mede em caracteres da fonte
#: padrão, e a tela em pixels. São duas unidades para a mesma intenção — "cabe uma
#: sigla", "cabe um nome de órgão", "cabe um parágrafo sem esconder o resto".
LARGURA_NO_EXCEL: dict[str, float] = {
    "marca": 22,  # o cabeçalho "Repetir a linha de cima" é mais largo que o valor
    "data": 12,
    "sigla": 6,
    "lista": 28,
    "prosa": 48,
    "texto": 18,
}

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


#: A coluna que o gerador RESERVA e nunca escreve, em cada aba que sai em pares.
#:
#: É COM ELA QUE A SUSPENSA FICA VAZIA. Uma lista suspensa não aceita intervalo de
#: altura zero, então "nenhuma opção" se faz apontando para uma célula em branco — e
#: essa célula precisa ser garantidamente branca, senão a suspensa passaria a oferecer
#: aquele valor em toda linha sem dono escolhido. Um teste confere que ela está vazia.
COLUNA_DE_RESERVA = "H"


def _ultima_linha_preenchida(coluna: str, primeira: int) -> str:
    """A fórmula que devolve o NÚMERO da última linha com conteúdo numa coluna.

    ERA `COUNTA`, E ISSO ESTAVA ERRADO — a revisão achou, e é o defeito original por
    outro caminho. `COUNTA` diz QUANTAS linhas têm conteúdo, não QUAL é a última: quem
    acrescenta instituições deixando uma linha vazia entre elas faz a conta ficar menor
    que o número da última linha, e o intervalo termina antes dela. As instituições
    abaixo do buraco desaparecem da suspensa, sem aviso — exatamente o desfecho que o
    intervalo dinâmico existia para impedir.

    DOIS BRAÇOS PORQUE HÁ DOIS TIPOS DE VALOR. `MATCH` com um valor maior que qualquer
    texto (`REPT("z",255)`) devolve a posição da última célula de TEXTO; com um número
    maior que qualquer número, a da última célula NUMÉRICA. A Relevância sai como número,
    então um braço só deixaria a lista dela com um item.

    `IFERROR` EM CADA BRAÇO porque a coluna pode não ter nenhum valor daquele tipo — o
    braço que não acha nada vira zero em vez de derrubar a expressão inteira —, e
    `MAX(..., primeira)` é o caso da base nova, sem valor nenhum: o intervalo tem de
    existir mesmo apontando para célula vazia, senão o Excel recusa o arquivo ao ABRIR.

    `COUNTA` CONTINUA NO `MAX`, COMO PISO, e isto responde a uma ressalva da revisão:
    `MATCH` sem o terceiro argumento usa o modo aproximado, que a documentação da
    Microsoft e do LibreOffice descreve para intervalo ORDENADO. O truque funciona em
    coluna desordenada porque o valor procurado é maior que qualquer texto (ou qualquer
    número) e a busca nunca tem para onde descer — mas é garantia de implementação, não
    de documentação, e o arquivo abre no Excel de outra pessoa.
    
    ENTÃO NÃO SE APOSTA NUM SÓ. `MAX` de todos os braços nunca fica abaixo do melhor
    deles, e nenhum deles pode passar da última linha preenchida — `COUNTA` conta
    células com conteúdo e `MATCH` devolve a posição de uma célula que existe. O pior
    caso de cada braço é o comportamento do outro: com um buraco no meio, `MATCH`
    cobre o que `COUNTA` perde; se `MATCH` falhar por qualquer motivo, a lista volta a
    ser o que era antes desta correção, e não uma lista vazia.
    """
    return (
        f"MAX(COUNTA({coluna}),"
        f'IFERROR(MATCH(REPT("z",255),{coluna}),0),'
        f"IFERROR(MATCH(9.99999999999999E+307,{coluna}),0),{primeira})"
    )


def _suspensa_dependente(vocabulario: str, celula_do_dono: str) -> str:
    """A fonte de uma suspensa que se reduz pelo valor de OUTRA célula da mesma linha.

    UMA FÓRMULA PARA OS DOIS CASOS, e eram dois quase iguais: o interlocutor que se
    reduz pela instituição da agenda, e a subcategoria que se reduz pela categoria de
    público da linha do cadastro. Duas cópias divergiriam no dia em que uma delas
    aprendesse algo — e a que não aprendeu é sempre a que ninguém está olhando.

    COMO FUNCIONA: a aba do vocabulário sai com o valor na coluna A e o DONO na coluna
    B, agrupada por dono. `COUNTIF` diz quantos são daquele dono, `MATCH` acha a primeira
    linha dele, e `OFFSET` recorta o bloco.

    SEM DONO OU SEM NINGUÉM, A LISTA FICA VAZIA — e isto era um defeito meu, que o dono
    do produto achou usando: ela caía na LISTA INTEIRA. Ele criou uma instituição, não
    atrelou interlocutor nenhum, foi lançar a agenda e viu todos os interlocutores da
    base.

    MEU ARGUMENTO ERA QUE UMA SUSPENSA VAZIA PARECERIA DEFEITO, e estava errado — o
    próprio servidor prova: escolher alguém de outro órgão é justamente o que ele RECUSA,
    porque um interlocutor fala por uma instituição só. A rede convidava ao erro que o
    passo seguinte rejeita, e na hora em que a pessoa tem 54 linhas para preencher.

    VAZIA DIZ A VERDADE — "este órgão ainda não tem ninguém" — e é o que o front já faz
    (`interlocutoresDaInstituicao` devolve lista vazia). Digitar continua permitido,
    porque a coluna não trava: é assim que se declara alguém novo.
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

    A RELAÇÃO QUE O FRONT TEM. `interlocutoresDaInstituicao` filtra a lista pelo
    `instituicao_id` escolhido; aqui o equivalente é recortar o bloco daquele órgão na
    aba de interlocutores, que sai agrupada por instituição justamente para isto.
    """
    if coluna.vocabulario != "interlocutores":
        return coluna.vocabulario
    return _suspensa_dependente(
        "interlocutores",
        f"${_letra_de_coluna(colunas, COLUNA_DA_INSTITUICAO_DA_AGENDA)}2",
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
    pares: Mapping[str, Sequence[tuple[str, str]]] | None = None,
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
    # AS COLUNAS SAEM DO RECORTE ESCOLHIDO. `colunas_do_modelo` recusa um nome de
    # modelo que não existe, então um erro de digitação aqui não gera arquivo torto.
    # OS PARES SÃO "VALOR + DONO", e hoje são dois: o interlocutor com a instituição
    # dele, e a subcategoria de público com a categoria dona. É o que faz a suspensa
    # dependente funcionar — ela procura o dono na coluna B da aba do vocabulário.
    os_pares = dict(pares or {})
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
        # AS COLUNAS VÊM DA DESCRIÇÃO, e são as do formulário da plataforma.
        #
        # ERAM UMA LISTA DE NOMES: só instituição e interlocutor tinham uma segunda
        # coluna. Uma aba de cadastro com menos campos que o formulário cria cadastro
        # pela metade, e quem completa depois é alguém que não estava na reunião. O que
        # o formulário NÃO pergunta continua fora: a esfera e o tipo da instituição são
        # derivados, e pedi-los abriria a chance de a planilha contradizer a derivação.
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
        # A LISTA É SÓ O VOCABULÁRIO. O marcador `idem` ocupava a última linha de
        # TODAS estas abas, onde nunca foi um valor daquele vocabulário: quem abria
        # a suspensa de Clima via uma instrução de preenchimento entre os climas. A
        # instrução virou a coluna `Repetir a linha de cima`.
        if chave in VOCABULARIOS_FECHADOS:
            planilha.protection.sheet = True

        # UMA SUSPENSA POR COLUNA QUE TEM VOCABULÁRIO, como na aba de agendas. Era aqui
        # que faltava o pente: os campos novos entrariam como texto livre, e o erro de
        # grafia viraria cadastro errado em vez de pendência.
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

        # O INTERVALO ACOMPANHA O CONTEÚDO, e era aqui o defeito que o dono do
        # produto achou ao usar: ele acrescentou instituições na aba e elas não
        # apareceram na suspensa da agenda.
        #
        # ERA UM INTERVALO FIXO — os valores do banco mais UMA linha em branco, o
        # "convite a cadastrar". Quem acrescentava duas via a primeira na lista e a
        # segunda não, sem aviso nenhum. E o desfecho era o pior possível: ela
        # digitava o nome na agenda, a suspensa não o tinha, e a linha virava
        # pendência de um cadastro que ela mesma acabara de declarar.
        #
        # `OFFSET` COM ALTURA DE `COUNTA` resolve porque a altura é calculada pelo
        # Excel na hora de abrir a lista — é quantas linhas têm conteúdo AGORA, e não
        # quantas tinham quando o arquivo foi gerado. Não há mais linha de convite: a
        # pessoa escreve onde quiser abaixo do último valor.
        #
        # `MAX(..., 1)` porque uma base nova pode não ter nenhum valor, e um intervalo
        # de altura ZERO é inválido — o Excel recusaria o arquivo inteiro ao abrir, que
        # é o pior momento possível para um erro.
        #
        # A LARGURA TAMBÉM AQUI, e era o pedido do dono do produto: o ajuste valia
        # só para `Agendas`, e as dezenove abas de cadastro saíam com a coluna padrão
        # do Excel — "Nome completo" do tamanho de "Relevância", com o nome do órgão
        # cortado ao meio na única aba onde ele é escrito.
        #
        # NA DIMENSÃO DA COLUNA, pelo mesmo motivo da aba de agendas: largura por
        # célula materializaria as 2000 linhas da suspensa e o `Ctrl+End` de quem abre
        # a aba iria para o fim do nada.
        for posicao, coluna in enumerate(colunas, start=1):
            planilha.column_dimensions[get_column_letter(posicao)].width = (
                LARGURA_NO_EXCEL[tipo_da_coluna_de_cadastro(coluna)]
            )

        primeira = 2 if tem_cabecalho else 1
        # `INDEX` E NÃO `OFFSET`, e a diferença importa: `OFFSET` é uma função VOLÁTIL, e
        # função volátil em validação de dados é o caso onde o Excel se recusa a resolver
        # em algumas versões. `INDEX` devolve uma referência sem ser volátil, e a
        # expressão inteira é um INTERVALO — `$A$2:INDEX(...)` —, que é a forma que a
        # validação de dados lê com menos ressalvas.
        #
        # O FIM É A ÚLTIMA LINHA PREENCHIDA (ver `_ultima_linha_preenchida`), e não
        # a CONTAGEM de linhas preenchidas: com uma linha vazia no meio da coluna, a
        # contagem fica menor que o número da última linha e os valores abaixo do
        # buraco caem fora da suspensa.
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

    # -- o tema repetido fica VERMELHO enquanto a pessoa preenche -------------
    #
    # O PEDIDO ERA OUTRO, e vale dizer por que ele não dá: "ao escolher um tema,
    # tirá-lo das outras colunas". O Excel não permite — uma célula aceita UMA
    # validação, e uma lista não sabe excluir o que as células vizinhas usaram.
    # As alternativas que existiriam são piores que o problema: trocar a lista
    # por uma fórmula `COUNTIF` perderia a suspensa com os 149 assuntos (e
    # digitá-los à mão é o erro que a suspensa existe para impedir), e uma
    # suspensa filtrada por linha exigiria uma área auxiliar com uma fórmula
    # `FILTER` por linha — 500 linhas vezes 18 colunas de fórmula num arquivo
    # que precisa abrir no Excel de quem recebe por e-mail.
    #
    # O QUE DÁ, E RESOLVE O MESMO PROBLEMA: formatação condicional. A célula
    # repetida fica vermelha NA HORA, a suspensa continua inteira, e quem
    # preenche vê o erro antes de subir o arquivo. A trava de verdade é a
    # conferência, que retira a repetição e avisa em qual coluna o assunto já
    # estava — ver `importar_agendas`.
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
