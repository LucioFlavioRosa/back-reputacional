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
from collections.abc import Mapping

from app.dominio.erros import RegraViolada
from app.dominio.frentes import TIPOS_DE_INSTITUICAO
from app.dominio.importacao_de_agendas import (
    COLUNA_DO_TIPO_DE_INSTITUICAO,
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
)

#: Linhas de dados que a lista suspensa da aba AGENDAS cobre, além do
#: cabeçalho. Bate exatamente com o teto de 500 agendas por arquivo (ver
#: Restrições globais) — DE PROPÓSITO, não por acaso: convidar a pessoa a
#: preencher a linha 600 quando o servidor vai recusar o arquivo inteiro por
#: passar de 500 é pior do que não ter lista suspensa nenhuma ali, porque ela
#: falsamente sugere que a linha é válida.
_LINHAS_DE_AGENDAS = 500

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
    return {"instituicoes": "Instituição"}.get(chave, ROTULO_DO_VOCABULARIO[chave])


def gerar(vocabularios: Mapping[str, list[str]]) -> bytes:
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
    for aba in FORMATO:
        planilha = pasta.create_sheet(aba.nome)
        planilha.append([coluna.nome for coluna in aba.colunas])
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
            planilha["A1"].comment = Comment(
                "Máximo de 500 agendas por arquivo.", "Painel Reputacional"
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
        e_de_instituicao = chave == "instituicoes"
        if e_de_instituicao:
            planilha.append([rotulo_singular(chave), COLUNA_DO_TIPO_DE_INSTITUICAO])
        for valor in valores:
            planilha.append([valor])

        ultima_linha = len(valores) + (1 if e_de_instituicao else 0)
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
        primeira = 2 if e_de_instituicao else 1
        intervalo = f"'{rotulo}'!$A${primeira}:$A${max(ultima_linha, primeira)}"
        pasta.defined_names[chave] = DefinedName(chave, attr_text=intervalo)

    # -- a lista de tipos, na coluna B da aba de instituições -----------------
    #
    # Sem ela a pessoa digita "orgão" com acento ou "veículo" e a importação
    # recusa um tipo que ela acha que escreveu certo.
    from openpyxl.worksheet.datavalidation import DataValidation as _DV

    aba_das_instituicoes = pasta[ROTULO_DO_VOCABULARIO["instituicoes"]]
    tipos = _DV(
        type="list",
        formula1='"' + ",".join(sorted(TIPOS_DE_INSTITUICAO)) + '"',
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Tipo inválido",
        error="Escolha um dos tipos da lista.",
    )
    aba_das_instituicoes.add_data_validation(tipos)
    tipos.add(f"B2:B{_LINHAS_DE_ABAS_FILHAS}")

    # -- listas suspensas: uma DataValidation por coluna com vocabulário ------
    for aba in FORMATO:
        planilha = pasta[aba.nome]
        teto = _LINHAS_DE_AGENDAS if aba.nome == "Agendas" else _LINHAS_DE_ABAS_FILHAS
        for indice, coluna in enumerate(aba.colunas, start=1):
            if coluna.vocabulario is None:
                continue
            letra = get_column_letter(indice)
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
                formula1=f"={coluna.vocabulario}",
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

    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()
