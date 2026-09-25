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
from app.dominio.importacao_de_agendas import (
    FORMATO,
    ROTULO_DO_VOCABULARIO,
    VOCABULARIOS_EDITAVEIS,
    VOCABULARIOS_FECHADOS,
)

#: Linhas de dados que cada lista suspensa cobre, além do cabeçalho. O teto de
#: 500 agendas por arquivo (ver Restrições globais) é o limite da aba
#: Agendas; as abas filhas (Participantes, Pessoas da Aegea, Materiais) têm
#: várias linhas por agenda — várias pessoas ou materiais numa mesma reunião
#: —, então o mesmo teto aplicado a elas sufocaria uma agenda com muitos
#: participantes. Um único valor generoso, usado nas quatro abas, evita
#: calcular um teto por aba sem deixar nenhuma delas curta.
_LINHAS_DE_DADOS = 2000


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
        for valor in valores:
            planilha.append([valor])

        ultima_linha = len(valores)
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
        intervalo = f"'{rotulo}'!$A$1:$A${max(ultima_linha, 1)}"
        pasta.defined_names[chave] = DefinedName(chave, attr_text=intervalo)

    # -- listas suspensas: uma DataValidation por coluna com vocabulário ------
    for aba in FORMATO:
        planilha = pasta[aba.nome]
        for indice, coluna in enumerate(aba.colunas, start=1):
            if coluna.vocabulario is None:
                continue
            letra = get_column_letter(indice)
            validacao = DataValidation(
                type="list",
                formula1=f"={coluna.vocabulario}",
                allow_blank=True,
            )
            planilha.add_data_validation(validacao)
            validacao.add(f"{letra}2:{letra}{_LINHAS_DE_DADOS + 1}")

    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()
