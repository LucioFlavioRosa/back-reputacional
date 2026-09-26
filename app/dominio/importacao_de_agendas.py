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

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field

from app.dominio.erros import RegraViolada
from app.dominio.texto import normalizar


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
        "areas_pessoa",
    }
)

#: Os únicos vocabulários que a IMPORTAÇÃO cria.
#:
#: Editável não quer dizer criável-pela-planilha. `unidades_negocio`,
#: `formatos_interacao` e `areas_pessoa` são DICIONÁRIO ADMINISTRADO: a
#: coordenação os mantém pela tela de Administração, e uma unidade de negócio
#: nova é decisão de estrutura da companhia, não um nome que se digita no meio de
#: 54 agendas. Antes eles prometiam "vou criar" na conferência e falhavam no
#: ÚLTIMO passo, depois de a pessoa já ter conferido tudo — a recusa agora é no
#: upload, dizendo o que fazer.
VOCABULARIOS_QUE_A_IMPORTACAO_CRIA: frozenset[str] = frozenset(
    {"instituicoes", "interlocutores", "pessoas_aegea", "temas"}
)

#: A coluna extra que a aba de vocabulário de instituições tem.
#:
#: A CATEGORIA, E NÃO O TIPO, e a diferença não é de gosto. É dela que o tipo
#: nasce (`TIPO_DA_CATEGORIA_DE_PUBLICO`), e é assim que a tela de cadastro cria
#: instituição — `api/stakeholders.py` diz que "a tela de cadastro nao pergunta
#: mais o tipo; ausente, ele vem da categoria de publico". Pedir o tipo direto
#: deixaria `categoria_publico_id` NULO, e é essa coluna que a taxonomia de
#: públicos do Score usa para agrupar: a instituição importada ficaria invisível
#: para uma área inteira do produto.
#:
#: E o tipo importa porque DERIVA A FRENTE da agenda — `derivar_frente` diz que
#: "o tipo já basta, sozinho, para todos os tipos menos dois". Chutá-lo daria
#: frente errada em toda agenda daquela instituição.
COLUNA_DA_CATEGORIA_DE_INSTITUICAO = "Categoria de público"

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
        # A taxonomia de públicos é FECHADA (mudá-la é migration, diz o
        # `api/dicionarios.py`) e ganha aba própria para a pessoa ver a lista
        # de onde a coluna da aba de instituições escolhe.
        "categorias_publico",
    }
)

#: O nome da aba que uma pessoa vê para cada vocabulário. Fecha uma lacuna que
#: a chave sozinha deixa: a chave (`"instituicoes"`, `"unidades_negocio"`) é o
#: identificador estável que o código usa; o rótulo (`"Instituições"`,
#: "Unidades de negócio") é o texto em português que vai na aba do `.xlsx`. Sem
#: este dicionário, a Tarefa 3 (gerador) e a Tarefa 4 (leitor) teriam cada uma
#: que inventar o nome da aba a partir da chave — e nada garantiria que
#: inventassem o MESMO nome.
#:
#: NENHUM RÓTULO PODE REPETIR O NOME DE UMA ABA DE `FORMATO` —
#: `test_nenhum_rotulo_de_vocabulario_repete_nome_de_aba_de_preenchimento`
#: prende essa regra para o dicionário inteiro. `"pessoas_aegea"` já caiu
#: nela uma vez: o rótulo óbvio seria "Pessoas da Aegea", mas esse é também o
#: nome da aba de preenchimento (a terceira de `FORMATO`, onde se lista quem
#: da Aegea esteve em cada reunião). Duas abas com o mesmo nome não cabem no
#: mesmo `.xlsx` — o Excel não aceita —, e o openpyxl resolve a colisão
#: RENOMEANDO A SEGUNDA CALADAMENTE para "Pessoas da Aegea1", sem erro nem
#: aviso. Se o gerador construísse o `DefinedName` da lista suspensa a partir
#: do rótulo pretendido em vez do nome real da aba, o intervalo apontaria
#: para "Pessoas da Aegea" — a aba de PREENCHIMENTO, cuja primeira linha é o
#: cabeçalho Código/Pessoa/Papel/Presença, não uma lista de nomes — e a
#: lista suspensa da coluna Pessoa ficaria silenciosamente errada no arquivo
#: que a pessoa baixa: sem exceção, sem aviso, só uma lista suspensa que não
#: lista pessoa nenhuma. Por isso o rótulo abaixo já vem distinto.
ROTULO_DO_VOCABULARIO: dict[str, str] = {
    "instituicoes": "Instituições",
    "interlocutores": "Interlocutores",
    "pessoas_aegea": "Pessoas da Aegea (lista)",
    "temas": "Temas",
    "unidades_negocio": "Unidades de negócio",
    "formatos_interacao": "Tipos de interação",
    "areas_pessoa": "Áreas",
    "status": "Situação",
    "climas": "Clima",
    "resultados": "Resultado",
    "iniciativas": "Iniciativa",
    "modalidade": "Modalidade",
    "presenca": "Presença",
    "categorias_publico": "Categorias de público",
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
        Coluna(nome="Área 1", campo="areas", vocabulario="areas_pessoa"),
        Coluna(nome="Área 2", campo="areas", vocabulario="areas_pessoa"),
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


#: Toda chave de `InteracaoEntrada.model_fields` classificada em um de quatro
#: destinos:
#:
#: - `"da planilha"` — uma COLUNA de `FORMATO` alimenta o campo diretamente:
#:   o valor da célula vira o valor do campo, sem cálculo no meio.
#: - `"das abas filhas"` — a pessoa também digita o valor na planilha, mas numa
#:   aba FILHA (Participantes, Pessoas da Aegea, Materiais), um item de lista
#:   por linha, e não por uma coluna só: o campo é a lista inteira remontada a
#:   partir de várias colunas daquela linha. Apagar uma linha da aba filha
#:   encolhe a lista — é dado digitado, não calculado. Por não vir de UMA
#:   coluna, `Coluna.campo` não descreve este caso (as colunas dessas abas têm
#:   `campo=""` de propósito — ver o docstring de `Coluna`), e é por isso que
#:   o teste de "da planilha" não alcança nem precisa alcançar estas chaves.
#: - `"derivado"` — o importador CALCULA o valor a partir de outro dado, sem
#:   que a pessoa o tenha digitado num campo próprio (a instituição já
#:   cadastrada, ou a linha marcada `Principal`).
#: - `"fora da v1"` — o importador não escreve o campo — ele fica no padrão do
#:   próprio esquema.
#:
#: O MESMO PADRÃO DE `_DE_TEXTO` (`app/dominio/recorte.py`) E DE `DESTINO`
#: (`corpo.test.ts`, no front): uma lista de "todo campo passa por aqui" que um
#: teste compara contra o modelo de verdade. Sem ela, um campo novo em
#: `InteracaoEntrada` simplesmente não chega pela importação — nem o Pydantic
#: reclama (o campo tem valor padrão), nem o Excel (a coluna que faltaria nunca
#: existiu) — e o silêncio dura até alguém notar, na produção, que a agenda
#: importada não carrega aquele dado.
#:
#: As chaves classificadas como `"da planilha"` são as ÚNICAS que precisam
#: bater com um `Coluna.campo` de `FORMATO` — é o que
#: `test_todo_campo_declarado_como_da_planilha_tem_coluna` prende, e só prende
#: essa categoria de propósito: as outras três não têm coluna nenhuma para
#: casar — `"das abas filhas"` porque o dado é linha, não coluna; `"derivado"`
#: porque o valor não é cópia de célula nenhuma; e `"fora da v1"` porque não
#: há célula.
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
    # permitiria que as duas informações discordassem. Note a diferença para
    # `outra_parte` logo abaixo: `Principal` é uma MARCA numa linha que já
    # existe por outro motivo, e não um dado que a pessoa digitou pensando em
    # preencher "o interlocutor principal" — por isso este é cálculo
    # (`"derivado"`), e a lista de participantes de onde ele sai não é.
    "interlocutor_id": "derivado",
    # -- das abas filhas: a pessoa digita, mas linha a linha numa aba filha ---
    #
    # `outra_parte`, `participacoes` e `materiais` vêm de uma aba filha
    # inteira (Participantes / Pessoas da Aegea / Materiais): cada linha da
    # aba filha é um item da lista, digitado pela pessoa e remontado a partir
    # de várias colunas daquela linha. Apagar uma linha em Participantes
    # encolhe `outra_parte` — não é cálculo, é transcrição; chamar isto de
    # "derivado" diria ao próximo leitor que o importador CALCULA o valor, o
    # que é falso.
    #
    # Também não é "da planilha": essa categoria é o caso de UMA coluna
    # copiando para UM campo escalar — o de `FORMATO._AGENDAS` —, e as
    # colunas destas três abas têm `campo=""` de propósito (ver o docstring
    # de `Coluna`). Não há `Coluna.campo` chamado "outra_parte" para casar, e
    # por isso `test_todo_campo_declarado_como_da_planilha_tem_coluna`
    # continua sem enxergar estas três chaves — de propósito, não por
    # omissão: elas simplesmente não pertencem à pergunta que aquele teste
    # faz.
    "outra_parte": "das abas filhas",
    "participacoes": "das abas filhas",
    "materiais": "das abas filhas",
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


#: AS SEIS RECUSAS DO FORMULÁRIO, e por que a planilha produz cada uma.
#:
#: Elas vivem em TypeScript, em `front/src/paginas/cadastro/impedimento.ts`, e a
#: importação é Python. Duplicá-las criaria duas versões da mesma verdade, das
#: quais uma envelheceria — então o que existe aqui não é a regra, é a
#: CLASSIFICAÇÃO dela, mais um teste que lê a lista canônica do front e exige
#: que nenhuma recusa fique sem classificar.
#:
#: A SPEC SUPÔS QUE SÓ DUAS DAS SEIS VALIAM AQUI, com o argumento de que as
#: outras quatro são artefato de formulário meio preenchido — a linha vazia que
#: alguém criou ao clicar "acrescentar" e abandonar. O argumento vale para um
#: formulário e não vale para uma planilha: quem preenche 54 agendas digita a
#: coluna de código inteira primeiro e os nomes depois, e copia blocos de
#: participantes de uma reunião para a seguinte. As seis são produzíveis, e por
#: cópia — que é justamente como um dia de 54 reuniões se preenche.
IMPEDIMENTOS_DA_PLANILHA: dict[str, str] = {
    "1": (
        "Material com título e sem link. Na planilha esta regra é MAIS estrita "
        "que no formulário: o front aceita arquivo OU link, e uma planilha não "
        "tem como subir arquivo — então sem link o material não leva a lugar "
        "nenhum."
    ),
    "2": (
        "Material com link e sem título. Descartar a linha em silêncio seria "
        "pior que recusar: a tela diria 'importado' com um material a menos."
    ),
    "3": (
        "Linha da outra parte sem pessoa. Quem digita a coluna de código antes "
        "dos nomes e para no meio produz exatamente isto."
    ),
    "4": (
        "Participante que não pertence à instituição da agenda. É o efeito de "
        "copiar a linha de uma agenda e trocar só a instituição, deixando os "
        "participantes da anterior."
    ),
    "5": "Linha da Aegea sem pessoa. O mesmo argumento da 3, do outro lado da mesa.",
    "6": (
        "A mesma pessoa no mesmo papel duas vezes. `(pessoa, papel)` é a chave "
        "no banco, e a repetição vem de copiar um bloco de participantes."
    ),
}

#: Vazio, e isso é uma conclusão e não um esquecimento: nenhuma das seis recusas
#: do formulário é impossível de produzir numa planilha. Se uma sétima nascer e
#: de fato não for produzível, ela entra aqui com a frase que explica por quê.
FORA_DA_PLANILHA: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class GrupoDeDivergencia:
    """Uma decisão que resolve VÁRIAS linhas — a unidade da tela de conferência.

    NÃO É TABELA. É uma vista montada ao ler `importacao_linha.divergencias`, e
    é o que faz a conferência escalar com o volume em vez de crescer junto com
    ele: "Instituição não encontrada: 'Prefeitura de Campinas' — em 12 linhas",
    uma decisão, doze linhas resolvidas. Sem o agrupamento, um dia de 54 agendas
    com o mesmo órgão desconhecido pediria 54 cliques idênticos, e ninguém
    conferiria de verdade — passaria a clicar.
    """

    campo: str
    valor: str
    #: Os números de linha do ARQUIVO que esta decisão destrava. A pessoa precisa
    #: poder ir olhá-las: contar não basta para ela decidir.
    linhas: tuple[int, ...]
    #: `True` se QUALQUER linha do grupo travava. Uma decisão que destrava
    #: algumas e não todas não pode fazer a tela dizer que está resolvido.
    trava: bool
    #: Nomes parecidos já cadastrados. Vazio quando não há nada parecido — e
    #: oferecer o menos-ruim de uma lista sem nada parecido é pior que não
    #: oferecer, porque a pessoa aponta para o errado por confiar na sugestão.
    sugestoes: tuple[str, ...] = ()


#: As decisões que uma pessoa pode tomar sobre um grupo de divergência.
#:
#: `descartar` não aparece aqui porque não é decisão SOBRE a divergência: é
#: decisão sobre a LINHA, e vive em `importacao_linha.decisao`.
DECISOES_DE_DIVERGENCIA = ("apontar", "criar")


#: Quão parecido um nome tem de ser para virar sugestão. 0.6 é o padrão do
#: `difflib`, e mexer nisto é escolher entre dois erros: mais baixo oferece
#: "Valor Econômico" para "Prefeitura de Campinas", mais alto deixa de oferecer
#: "Prefeitura Municipal de Campinas" — que é exatamente o caso que a sugestão
#: existe para resolver.
SEMELHANCA_MINIMA = 0.6

#: Quantas sugestões a tela oferece. Três cabem numa linha e ainda deixam a
#: escolha rápida; uma lista longa devolve à pessoa o trabalho de procurar.
SUGESTOES_POR_GRUPO = 3


def agrupar(
    linhas: Sequence[tuple[int, Sequence[Divergencia]]],
    conhecidos: Sequence[str] = (),
) -> list[GrupoDeDivergencia]:
    """As divergências de várias linhas, viradas em decisões.

    Agrupa por `(campo, valor)` e não por valor sozinho: "Ana Prado" que não
    existe como interlocutora e "Ana Prado" que não existe como pessoa da Aegea
    são dois problemas, com duas resoluções diferentes.

    A ORDEM É POR QUANTAS LINHAS O GRUPO SEGURA, decrescente — a pessoa resolve
    primeiro o que destrava mais — e desempata pelo valor. O desempate não é
    capricho: sem ele a ordem sairia da iteração de um dicionário, a lista se
    remexeria entre dois F5, e a pessoa perderia o lugar onde estava numa tela
    de 54 agendas.
    """
    import difflib

    por_chave: dict[tuple[str, str], list[int]] = {}
    trava_de: dict[tuple[str, str], bool] = {}

    for numero, divergencias in linhas:
        for divergencia in divergencias:
            chave = (divergencia.campo, divergencia.valor)
            por_chave.setdefault(chave, []).append(numero)
            trava_de[chave] = trava_de.get(chave, False) or divergencia.trava

    #: `normalizar` dos dois lados para a comparação, mas a SUGESTÃO devolve o
    #: nome como está cadastrado — é o que a pessoa vai reconhecer e escolher.
    por_normalizado = {normalizar(nome): nome for nome in conhecidos}

    grupos = [
        GrupoDeDivergencia(
            campo=campo,
            valor=valor,
            linhas=tuple(numeros),
            trava=trava_de[(campo, valor)],
            sugestoes=tuple(
                por_normalizado[parecido]
                for parecido in difflib.get_close_matches(
                    normalizar(valor),
                    list(por_normalizado),
                    n=SUGESTOES_POR_GRUPO,
                    cutoff=SEMELHANCA_MINIMA,
                )
            ),
        )
        for (campo, valor), numeros in por_chave.items()
    ]
    return sorted(grupos, key=lambda grupo: (-len(grupo.linhas), grupo.valor, grupo.campo))


def aba_de(nome: str) -> Aba:
    """A aba de `FORMATO` com este nome, ou `RegraViolada` se não existir."""
    for aba in FORMATO:
        if aba.nome == nome:
            return aba
    raise RegraViolada(f"Aba inválida: {nome!r}. Use uma de {[a.nome for a in FORMATO]}.")


@dataclass(frozen=True, slots=True)
class Divergencia:
    """O que a importação não conseguiu resolver sozinha, numa linha.

    IMUTÁVEL de propósito. A resolução (Tarefa 10) reescreve a lista de
    divergências de uma linha trocando os objetos, e não mutando-os: a tela
    agrupa as divergências por `(campo, valor)` e compara por valor, então uma
    divergência mutada mudaria em silêncio um agrupamento que a pessoa já está
    olhando.

    `trava` é a diferença entre as duas severidades da spec, e ela não é
    cosmética: com `trava=True` o botão de confirmar não acende. Instituição que
    não existe trava; possível duplicata só avisa, porque duas reuniões com o
    mesmo órgão no mesmo dia acontecem — e travar por isso ensinaria a pessoa a
    ignorar o aviso.
    """

    #: O campo de `InteracaoEntrada` afetado — é por ele que a tela agrupa.
    campo: str
    #: O valor como a pessoa escreveu, sem normalizar: é o que ela reconhece.
    valor: str
    #: O texto que a pessoa lê.
    mensagem: str
    trava: bool
    #: Nomes parecidos já cadastrados, para a tela oferecer. Vazio na maioria
    #: das divergências, e por isso tem default — uma tupla, nunca lista, para
    #: não haver default mutável compartilhado entre todas elas.
    sugestoes: Sequence[str] = field(default_factory=tuple)

    #: O que a pessoa DECIDIU sobre esta divergência, quando decidiu: `apontar`
    #: para um cadastro existente, ou `criar` um novo. `None` enquanto ninguém
    #: decidiu nada.
    #:
    #: A decisão fica NA divergência e não numa tabela à parte porque é dela que
    #: a confirmação precisa: ao percorrer as linhas, a instrução está ao lado do
    #: valor a que se refere, sem uma segunda consulta para casar as duas.
    acao: str | None = None
    #: O id do cadastro escolhido, quando `acao == "apontar"`.
    alvo: str | None = None
    #: A categoria de público declarada na aba, quando o cadastro a criar é uma
    #: instituição. É dela que o tipo nasce.
    #:
    #: VIAJA COM A DIVERGÊNCIA porque o ARQUIVO NÃO É GUARDADO: na confirmação é
    #: daqui que sai a categoria, e sem ela a criação voltaria a chutar o tipo.
    categoria_declarada: str | None = None


def classificar(
    valor: str,
    vocabulario: str,
    conhecidos: Mapping[str, str],
    declarados: Set[str],
) -> str:
    """O que fazer com um valor lido da planilha: `resolve`, `cria` ou `diverge`.

    A DISTINÇÃO ENTRE `conhecidos` E `declarados` É A REGRA CENTRAL DESTE
    MÓDULO, e é ela que torna defensável a decisão de produto de criar cadastro
    pela planilha. `conhecidos` é o que está no banco; `declarados` é o que a
    pessoa escreveu nas ABAS EDITÁVEIS do próprio arquivo.

    Escrever um nome novo na aba de cadastro é declaração de intenção — "quero
    que isto exista". Digitar o mesmo nome direto na célula da agenda, sem
    declará-lo, é muito mais provavelmente erro de grafia: "Prefeitura de
    Campinas" onde o cadastro tem "Prefeitura Municipal de Campinas". Tratar os
    dois igual é escolher entre dois defeitos — ou a importação cria duplicata
    em massa a cada erro de digitação, ou ela recusa o cadastro novo que é a
    razão de existir desta funcionalidade. A distinção evita os dois.

    O vocabulário FECHADO nunca cria, mesmo declarado. A aba dele vai protegida
    no modelo, mas o Google Sheets descarta a proteção ao converter o arquivo —
    então proteger a aba é conveniência do Excel, e o controle é aqui. Mudar um
    clima ou um status é mudança de regra de negócio: os KPIs e a taxa de
    resolutividade dependem daquela lista, e isso é código e migration.

    `normalizar` cuida da caixa, do acento e do espaço — inclusive do espaço não
    separável (`\xa0`) colado de uma página web, que o NFKD converte em espaço
    comum antes de o regex colapsar. Sem isso, um nome idêntico na tela não
    casaria com o cadastro e a pessoa não teria como descobrir por quê.
    """
    chave = normalizar(valor)
    # Célula vazia não é nome. Sem esta guarda, um `conhecidos` que por acidente
    # tivesse a chave vazia faria a célula em branco "casar" com um cadastro.
    if not chave:
        return "diverge"
    if chave in conhecidos:
        return "resolve"
    if vocabulario in VOCABULARIOS_FECHADOS:
        return "diverge"
    # Editável não é o mesmo que criável pela planilha: dicionário administrado
    # se cadastra na Administração, e prometer "vou criar" aqui só adiaria a
    # recusa para o último passo da conferência.
    if vocabulario not in VOCABULARIOS_QUE_A_IMPORTACAO_CRIA:
        return "diverge"
    return "cria" if chave in declarados else "diverge"
