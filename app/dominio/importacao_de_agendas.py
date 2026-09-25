"""O formato da planilha de agendas — a descrição que o gerador e o leitor leem.

UMA DESCRIÇÃO, DOIS CONSUMIDORES. O `.xlsx` que a pessoa baixa e preenche é
gerado a partir de `FORMATO` (Tarefa 3), e o arquivo preenchido é lido de volta
contra o mesmo `FORMATO` (Tarefa 4). Se o formato morasse duas vezes — uma
lista de colunas no gerador, outra no leitor —, uma coluna nova entraria numa
e não na outra, e a pessoa preencheria uma coluna que ninguém lê, sem erro
nenhum: nem o Excel reclamaria (a aba existe, a célula está lá), nem o servidor
(ele simplesmente nunca olha aquela coluna). Em `tests/test_importacao_de_
agendas.py`, `test_toda_coluna_com_vocabulario_aponta_para_um_grupo_conhecido`
prende a metade dessa promessa que um teste consegue prender sozinho: a outra
metade — gerador e leitor lendo o MESMO `FORMATO` — está na própria
arquitetura do módulo, que não expõe nenhum jeito de descrevê-lo duas vezes.

Este módulo é DOMÍNIO PURO: nada aqui toca banco ou `openpyxl`. `FORMATO` é
dado estático, e `aba_de` é busca em memória. Isso é o que permite testá-lo sem
fixture de Postgres e sem escrever um `.xlsx` de verdade.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dominio.erros import RegraViolada


@dataclass(frozen=True, slots=True)
class Coluna:
    """Uma coluna de uma aba de preenchimento.

    `campo` é o nome do campo em `InteracaoEntrada` que esta coluna alimenta —
    vazio quando a coluna não vira campo da interação (é o caso de `Código`,
    que só liga as abas entre si, e das colunas das abas filhas, que viram
    participante/pessoa/material, não campo da agenda). A Tarefa 2 usa este
    campo para provar que todo campo de `InteracaoEntrada` tem destino
    declarado.

    `vocabulario` é a chave em `VOCABULARIOS_EDITAVEIS` ou
    `VOCABULARIOS_FECHADOS` contra a qual o valor da célula é validado —
    `None` quando a coluna é texto livre, sem lista suspensa.
    """

    nome: str
    campo: str
    vocabulario: str | None = None
    obrigatoria: bool = False


@dataclass(frozen=True, slots=True)
class Aba:
    """Uma aba de preenchimento, com uma linha por registro."""

    nome: str
    colunas: tuple[Coluna, ...]


#: Vocabulários que a planilha deixa a pessoa ampliar: escrever um nome novo
#: nesta aba é declaração de intenção — "cadastre isto" — e a Tarefa 5 usa essa
#: distinção para decidir entre criar e divergir.
VOCABULARIOS_EDITAVEIS: frozenset[str] = frozenset(
    {
        "instituicoes",
        "interlocutores",
        "pessoas_aegea",
        "temas",
        "unidades_negocio",
        "formatos_interacao",
        "areas",
    }
)

#: Vocabulários fechados: mudar um valor aqui é mudança de regra de negócio
#: (os KPIs e a taxa de resolutividade dependem deles), então é código e
#: migration — nunca uma linha na planilha. O servidor recusa valor novo
#: nestes MESMO QUE a aba correspondente chegue desprotegida: proteger a aba é
#: conveniência do Excel, não o controle (ver `classificar`, Tarefa 5).
#:
#: AS CHAVES SÃO AS DE `api/dicionarios.py › FECHADOS`, e por isso as quatro
#: primeiras não são o singular óbvio: `status`, `climas`, `resultados` e
#: `iniciativas` resolvem contra TABELA no banco (a Tarefa 6 as lê de lá por
#: esta chave — duas grafias para o mesmo conceito quebraria essa busca). As
#: quatro últimas — `modalidade`, `presenca`, `papel`, `momento` — não têm
#: entrada em `api/dicionarios.py`: são vocabulário fixo definido em código,
#: sem tabela própria, e por isso ficam no singular que o resto deste módulo
#: usa. `ROTULO_DO_VOCABULARIO` é quem apresenta as oito com o mesmo nome de
#: aba visível, singular, independente de qual das duas famílias cada uma é.
VOCABULARIOS_FECHADOS: frozenset[str] = frozenset(
    {
        "status",
        "climas",
        "resultados",
        "iniciativas",
        "modalidade",
        "presenca",
        "papel",
        "momento",
    }
)

#: O nome da aba que uma pessoa vê para cada vocabulário. Fecha uma lacuna que
#: a chave sozinha deixa: a chave (`"instituicoes"`, `"pessoas_aegea"`) é o
#: identificador estável que o código usa; o rótulo (`"Instituições"`,
#: "Pessoas da Aegea") é o texto em português que vai na aba do `.xlsx`. Sem
#: este dicionário, a Tarefa 3 (gerador) e a Tarefa 4 (leitor) teriam cada uma
#: que inventar o nome da aba a partir da chave — e nada garantiria que
#: inventassem o MESMO nome.
ROTULO_DO_VOCABULARIO: dict[str, str] = {
    "instituicoes": "Instituições",
    "interlocutores": "Interlocutores",
    "pessoas_aegea": "Pessoas da Aegea",
    "temas": "Temas",
    "unidades_negocio": "Unidades de negócio",
    "formatos_interacao": "Tipos de interação",
    "areas": "Áreas",
    "status": "Situação",
    "climas": "Clima",
    "resultados": "Resultado",
    "iniciativas": "Iniciativa",
    "modalidade": "Modalidade",
    "presenca": "Presença",
    "papel": "Papel",
    "momento": "Momento",
}

_AGENDAS = Aba(
    nome="Agendas",
    colunas=(
        # `Código` é inventado por quem preenche (A1, A2…) e repetido nas abas
        # filhas — é o único conceito novo que a planilha introduz, e por isso
        # vem primeiro: quem preenche precisa vê-lo antes de tudo.
        Coluna(nome="Código", campo=""),
        Coluna(nome="Data", campo="data_interacao", obrigatoria=True),
        # Instituição em branco não identifica agenda nenhuma — é o mínimo que
        # a distingue de outra, junto com a Data.
        Coluna(
            nome="Instituição", campo="instituicao_id", vocabulario="instituicoes", obrigatoria=True
        ),
        Coluna(
            nome="Tipo de interação", campo="formato_interacao_id", vocabulario="formatos_interacao"
        ),
        # UF não é vocabulário de aba: são as 27 siglas fixas mais NA/IN que
        # `app/dominio/recorte.py › ABRANGENCIAS_VALIDAS` já enumera — criar
        # uma aba de vocabulário para uma lista que não muda seria mais um
        # lugar para ela divergir da de `recorte.py`.
        Coluna(nome="UF", campo="uf"),
        Coluna(
            nome="Unidade de negócio", campo="unidade_negocio_id", vocabulario="unidades_negocio"
        ),
        Coluna(nome="Modalidade", campo="modalidade", vocabulario="modalidade"),
        Coluna(nome="Local", campo="local"),
        Coluna(nome="Situação", campo="status", vocabulario="status"),
        Coluna(nome="Iniciativa", campo="iniciativa", vocabulario="iniciativas"),
        Coluna(nome="Nota da situação", campo="nota_situacao"),
        Coluna(nome="Declinado por", campo="declinado_por"),
        Coluna(nome="Motivo do declínio", campo="motivo_declinio"),
        Coluna(nome="Clima esperado", campo="clima_esperado", vocabulario="climas"),
        Coluna(nome="Expectativa", campo="expectativa"),
        Coluna(nome="Prevê desdobramento", campo="preve_desdobramento"),
        Coluna(nome="Clima", campo="clima", vocabulario="climas"),
        Coluna(nome="Resultado", campo="resultado", vocabulario="resultados"),
        Coluna(nome="Relato", campo="relato"),
        Coluna(nome="Repercussão e encaminhamentos", campo="encaminhamentos"),
        Coluna(nome="Pendências", campo="pendencias"),
        Coluna(nome="Observações", campo="observacoes"),
        # Temas e áreas são COLUNAS, não abas: são poucos por agenda, e uma
        # aba própria custaria duas abas a mais para um vocabulário que cabe
        # em três/duas colunas com lista suspensa. O teto é arbitrário e
        # ampliável — ver a seção "Abas de preenchimento" da spec.
        Coluna(nome="Tema 1", campo="temas", vocabulario="temas"),
        Coluna(nome="Tema 2", campo="temas", vocabulario="temas"),
        Coluna(nome="Tema 3", campo="temas", vocabulario="temas"),
        Coluna(nome="Área 1", campo="areas", vocabulario="areas"),
        Coluna(nome="Área 2", campo="areas", vocabulario="areas"),
    ),
)

_PARTICIPANTES = Aba(
    nome="Participantes",
    colunas=(
        Coluna(nome="Código", campo=""),
        # `Pessoa` aqui é o interlocutor — pessoa da OUTRA parte —, e por isso
        # aponta para o vocabulário `interlocutores`, não `pessoas_aegea`.
        Coluna(nome="Pessoa", campo="", vocabulario="interlocutores"),
        Coluna(nome="Presença", campo="", vocabulario="presenca"),
        # O interlocutor PRINCIPAL não é coluna da Agenda: é quem estiver
        # marcado aqui. Uma coluna separada em Agendas permitiria que as duas
        # informações discordassem — ver "O que não entra na planilha".
        Coluna(nome="Principal", campo=""),
    ),
)

_PESSOAS_DA_AEGEA = Aba(
    nome="Pessoas da Aegea",
    colunas=(
        Coluna(nome="Código", campo=""),
        Coluna(nome="Pessoa", campo="", vocabulario="pessoas_aegea"),
        Coluna(nome="Papel", campo="", vocabulario="papel"),
        Coluna(nome="Presença", campo="", vocabulario="presenca"),
    ),
)

_MATERIAIS = Aba(
    nome="Materiais",
    colunas=(
        Coluna(nome="Código", campo=""),
        Coluna(nome="Momento", campo="", vocabulario="momento"),
        Coluna(nome="Título", campo=""),
        Coluna(nome="Link", campo=""),
        Coluna(nome="Observação", campo=""),
    ),
)

#: As quatro abas de preenchimento, na ordem em que a pessoa as encontra no
#: arquivo: a agenda primeiro (dona do `Código`), depois as três abas filhas
#: que se ligam a ela por ele.
FORMATO: tuple[Aba, ...] = (_AGENDAS, _PARTICIPANTES, _PESSOAS_DA_AEGEA, _MATERIAIS)


#: Toda chave de `InteracaoEntrada.model_fields` classificada em um de três
#: destinos: `"da planilha"` (uma coluna de `FORMATO` alimenta o campo),
#: `"derivado"` (o importador calcula o valor a partir de outros dados já
#: importados ou já cadastrados) ou `"fora da v1"` (o importador não escreve
#: o campo — ele fica no padrão do próprio esquema).
#:
#: O MESMO PADRÃO DE `_DE_TEXTO` (`app/dominio/recorte.py`) E DE `DESTINO`
#: (`corpo.test.ts`, no front): uma lista de "todo campo passa por aqui" que um
#: teste compara contra o modelo de verdade. Sem ela, um campo novo em
#: `InteracaoEntrada` simplesmente não chega pela importação — nem o Pydantic
#: reclama (o campo tem valor padrão), nem o Excel (a coluna que faltaria nunca
#: existiu) — e o silêncio dura até alguém notar, na produção, que a agenda
#: importada não carrega aquele dado.
#:
#: As chaves classificadas como `"da planilha"` são as únicas que
#: precisam bater com um `Coluna.campo` de `FORMATO` — é o que
#: `test_todo_campo_declarado_como_da_planilha_tem_coluna` prende. As outras
#: duas categorias não têm coluna nenhuma para casar: `"derivado"` porque o
#: valor não é cópia de célula, e `"fora da v1"` porque não há célula.
DESTINO_DO_CAMPO: dict[str, str] = {
    # -- da planilha: uma coluna de `FORMATO` copia direto para o campo -------
    "data_interacao": "da planilha",
    "instituicao_id": "da planilha",
    "uf": "da planilha",
    "status": "da planilha",
    "formato_interacao_id": "da planilha",
    "unidade_negocio_id": "da planilha",
    "modalidade": "da planilha",
    "local": "da planilha",
    "iniciativa": "da planilha",
    "nota_situacao": "da planilha",
    "declinado_por": "da planilha",
    "motivo_declinio": "da planilha",
    "clima_esperado": "da planilha",
    "expectativa": "da planilha",
    "preve_desdobramento": "da planilha",
    "clima": "da planilha",
    "resultado": "da planilha",
    "relato": "da planilha",
    "encaminhamentos": "da planilha",
    "pendencias": "da planilha",
    "observacoes": "da planilha",
    "temas": "da planilha",
    "areas": "da planilha",
    # -- derivado: o importador calcula, não copia de uma célula -------------
    #
    # Frente, Esfera e Tier vêm da INSTITUIÇÃO, não de coluna — pô-los na
    # planilha abriria a chance de a agenda contradizer o cadastro do órgão,
    # que é exatamente o que derivar deles resolve (ver "O que não entra na
    # planilha" na spec, e o item 3 de 24/09).
    "frente": "derivado",
    "esfera_id": "derivado",
    "tier": "derivado",
    # O interlocutor principal não é coluna própria: é quem estiver marcado
    # `Principal` na aba Participantes. Uma coluna separada em Agendas
    # permitiria que as duas informações discordassem.
    "interlocutor_id": "derivado",
    # `outra_parte`, `participacoes` e `materiais` vêm de uma aba filha
    # inteira (Participantes / Pessoas da Aegea / Materiais), não de UMA
    # coluna: cada linha da aba filha vira um item da lista, remontado a
    # partir de várias colunas daquela linha. `Coluna.campo` descreve o caso
    # "uma coluna copia para um campo escalar" — que é o de `FORMATO._AGENDAS`
    # — e por isso as colunas dessas três abas têm `campo=""` (ver o docstring
    # de `Coluna`). Chamar estes três de "da planilha" prometeria uma coluna
    # que não existe com este nome, e é justamente essa promessa vazia que
    # `test_todo_campo_declarado_como_da_planilha_tem_coluna` recusa.
    "outra_parte": "derivado",
    "participacoes": "derivado",
    "materiais": "derivado",
    # -- fora da v1: o importador não escreve o campo -------------------------
    #
    # Os campos por frente (link da matéria, casa, tramitação, tipo de
    # investidor) formam um registro variante; numa planilha plana virariam
    # vinte colunas com dezoito sempre vazias. A agenda importada sem eles é
    # válida — `extensao` é anulável — e quem precisar completa na ficha.
    "extensao": "fora da v1",
    # A "Consulta recebida" é outro tipo de registro (canal, remetente, teor,
    # prazo e resposta próprios — os campos de `ConsultaEntrada`), e
    # `validar_consulta` recusa o bloco fora do tipo certo. A planilha recusa
    # esse tipo de interação inteiro, com mensagem dizendo para registrá-lo
    # pela tela — então nem o bloco nem o que ele carrega chega pela
    # importação.
    "consulta": "fora da v1",
    # Só faz sentido dentro de uma Consulta recebida — sem ela, não há de onde
    # vir.
    "alegacoes": "fora da v1",
    # Nenhuma coluna da aba Agendas leva a pauta em palavras — o assunto da
    # reunião é o que `temas` (colunas Tema 1–3) já cobre na planilha.
    "pauta": "fora da v1",
    # Aposentado (ver `api/dicionarios.py`, item "stakeholders": substituído
    # pela categoria de público da instituição na migration 0036). Um campo
    # em extinção não ganha coluna nova.
    "stakeholder_id": "fora da v1",
    "posicionamento": "fora da v1",
    "registro_url": "fora da v1",
    # Aponta para interações ANTERIORES já existentes no sistema — algo que só
    # faz sentido escolher entre registros que já têm id, e uma planilha de
    # agendas novas não tem como referenciar isso.
    "origens": "fora da v1",
}


def aba_de(nome: str) -> Aba:
    """A aba de `FORMATO` com este nome, ou `RegraViolada` se não existir."""
    for aba in FORMATO:
        if aba.nome == nome:
            return aba
    raise RegraViolada(f"Aba inválida: {nome!r}. Use uma de {[a.nome for a in FORMATO]}.")
