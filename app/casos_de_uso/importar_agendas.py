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
from datetime import UTC, date, datetime
from types import MappingProxyType

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.gravar import gravar
from app.banco.tabelas_catalogo import (
    AreaPessoa,
    CategoriaPublico,
    Clima,
    FormatoInteracao,
    Iniciativa,
    Relevancia,
    Resultado,
    Status,
    SubcategoriaPublico,
    Tema,
    UnidadeNegocio,
)
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso.ler_planilha_de_agendas import (
    LinhaBruta,
    ler,
    ler_cadastros_declarados,
    ler_declarados,
)
from app.dominio.erros import Conflito, RegraViolada
from app.dominio.frentes import (
    ROTULO_DO_TIPO_DE_INSTITUICAO,
    TIPO_DA_CATEGORIA_DE_PUBLICO,
    TIPO_SEM_CATEGORIA,
)
from app.dominio.importacao_de_agendas import (
    ABA_PRINCIPAL,
    CHAVE_DO_CORRIGIDO,
    CHAVE_DO_HERDADO,
    COLUNA_DA_INSTITUICAO_DA_AGENDA,
    DECISOES_DE_DIVERGENCIA,
    FORMATO,
    INTERLOCUTORES_POR_AGENDA,
    MATERIAIS_POR_AGENDA,
    PESSOAS_DA_AEGEA_POR_AGENDA,
    PRIMEIRO_INTERLOCUTOR_E_PRINCIPAL,
    VOCABULARIOS_FECHADOS,
    VOCABULARIOS_QUE_A_IMPORTACAO_CRIA,
    Coluna,
    Divergencia,
    aba_de,
    acao_efetiva,
    classificar,
    coluna_do_campo,
    colunas_do_cadastro,
)
from app.dominio.interacao import (
    ABRANGENCIAS_VALIDAS,
    MODALIDADES,
    MOMENTOS_DE_MATERIAL,
    PAPEIS,
    PRESENCAS,
)
from app.dominio.recorte import INTERNACIONAL, NACIONAL, UFS
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
    # Resolve para o `id` porque é ele que vai em `instituicao.categoria_publico_id`;
    # o `codigo`, que deriva o tipo, sai de uma leitura pelo id na criação.
    "categorias_publico": _Fonte(CategoriaPublico, "id"),
    # O `id` da relevância É o número do tier — a tabela não tem sequência
    # própria de propósito, porque 1, 2 e 3 já são os códigos estáveis.
    "relevancias": _Fonte(Relevancia, "id"),
    "subcategorias_publico": _Fonte(SubcategoriaPublico, "id"),
}

#: Vocabulário sem tabela: a lista mora em `dominio/interacao.py`, porque mudá-la
#: é mudar a regra e não o cadastro. O valor É o código, e `normalizar` faz
#: "Híbrida" casar com `hibrida` — acento e caixa saem dos dois lados.
NO_CODIGO: dict[str, tuple[str, ...]] = {
    "modalidade": MODALIDADES,
    "presenca": PRESENCAS,
    "papel": PAPEIS,
    "momento": MOMENTOS_DE_MATERIAL,
    # A ABRANGÊNCIA NÃO TEM TABELA: é o domínio do banco mais os dois de fora do
    # país. Montada aqui pelo mesmo motivo que `catalogo.py` a monta à mão —
    # não há de onde ler.
    "abrangencias": (*sorted(UFS), NACIONAL, INTERNACIONAL),
}

#: As colunas numeradas que montam cada lista de `InteracaoEntrada`.
#:
#: TUDO NUMA ABA SÓ. Antes eram três abas filhas ligadas pelo `Código`; agora cada
#: pessoa e cada material é um GRUPO de colunas numeradas na própria linha da
#: agenda. O que se ganhou: a instituição do interlocutor está na mesma linha que
#: ele, então "quem pode falar por qual instituição" deixou de ser inferido.
#:
#: Cada grupo diz qual campo de `InteracaoEntrada` alimenta, com que modelo cada
#: item é montado, e o sufixo de cada coluna dele — `"Interlocutor {n}"` vira
#: `interlocutor_id`. Um teste prende cada coluna numerada de `FORMATO` a uma
#: entrada aqui, senão uma coluna nova apareceria no modelo e não chegaria a
#: lugar nenhum.
GRUPOS_NUMERADOS: dict[str, dict] = {
    "outra_parte": {
        "modelo": ParticipanteDaOutraParteEntrada,
        "quantos": INTERLOCUTORES_POR_AGENDA,
        "colunas": {"Interlocutor {n}": "interlocutor_id", "Presença {n}": "presenca"},
        "exigida": "Interlocutor {n}",
    },
    "participacoes": {
        "modelo": ParticipacaoEntrada,
        "quantos": PESSOAS_DA_AEGEA_POR_AGENDA,
        "colunas": {
            "Pessoa da Aegea {n}": "pessoa_aegea_id",
            "Papel {n}": "papel",
            "Presença da Aegea {n}": "presenca",
        },
        "exigida": "Pessoa da Aegea {n}",
    },
    "materiais": {
        "modelo": MaterialEntrada,
        "quantos": MATERIAIS_POR_AGENDA,
        "colunas": {
            "Momento {n}": "momento",
            "Título {n}": "titulo",
            "Link {n}": "url",
            "Observação do material {n}": "observacao",
        },
        # O material precisa de título E de link: a planilha não tem como subir
        # arquivo, então sem link ele não leva a lugar nenhum.
        "exigida": "Título {n}",
        "tambem_exigida": "Link {n}",
    },
}

#: Os campos que `InteracaoEntrada` exige. Sem um deles não há proposta nenhuma
#: a montar, então a divergência TRAVA.
OBRIGATORIOS = ("data_interacao", "instituicao_id", "uf")

#: Um mapeamento vazio, para default de parâmetro. Um `{}` literal como default
#: seria compartilhado entre todas as chamadas — e mutável.
MAPPING_VAZIO: Mapping[tuple[str, str], object] = MappingProxyType({})

#: Marca um nome que casa com MAIS DE UM cadastro.
#:
#: A unicidade de `instituicao` é `(nome_normalizado, tipo)` e a de
#: `interlocutor` é `(nome_normalizado, instituicao_id)` — a migration 0002 diz
#: por quê: "Águas do Rio" existe como `area_interna` e pode existir como
#: `orgao`, e duas "Ana Prado" em instituições diferentes é situação comum. Um
#: índice nome→id ACHATA as duas e a planilha passa a apontar silenciosamente
#: para a errada. Travar é o único comportamento honesto: só quem preencheu sabe
#: de qual delas falava.
AMBIGUO = object()

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

    `entrada` é `None` em DOIS casos diferentes, e distingui-los é o ponto:

      - **travada**: alguma divergência trava. A pessoa precisa decidir algo
        antes de isto virar agenda.
      - **esperando criação**: `a_criar` não está vazio. Nada falta à pessoa —
        ela já declarou o cadastro novo na aba editável —, só não existe ainda o
        id para montar o `InteracaoEntrada`. Quem cria é a confirmação.

    Tratar os dois como a mesma coisa era o defeito que a revisão achou: um nome
    escrito corretamente na aba de cadastro fazia a linha travar, o oposto do que
    a spec manda.
    """

    linha: LinhaBruta
    entrada: InteracaoEntrada | None
    divergencias: list[Divergencia] = field(default_factory=list)
    #: `(vocabulário, nome)` de cada cadastro que a confirmação precisa criar.
    #: Guardado como DADO e não só dentro do texto de uma divergência: a
    #: confirmação precisa do valor, não da frase que o descreve.
    a_criar: tuple[tuple[str, str], ...] = ()
    #: Os grupos de colunas que não deu para montar porque esperam um cadastro.
    #: Guardam o que a pessoa preencheu — descartá-los levaria a presença e o papel
    #: com eles, e ela não preencheu aquilo para nada.
    filhas_pendentes: tuple[Mapping[str, object], ...] = ()

    @property
    def travada(self) -> bool:
        return any(divergencia.trava for divergencia in self.divergencias)

    @property
    def esperando_criacao(self) -> bool:
        return not self.travada and bool(self.a_criar)


def _so_ativos(consulta, tabela):
    """A consulta filtrada por `ativo`, quando a tabela tem a coluna.

    AS APIS NORMAIS JÁ FILTRAM — `api/stakeholders.py` e `api/catalogo.py` — e a
    importação não filtrava: uma linha limpa podia confirmar apontando para uma
    instituição desativada, ressuscitando na Base um cadastro que alguém tirou de
    circulação de propósito.
    """
    coluna = getattr(tabela, "ativo", None)
    return consulta if coluna is None else consulta.where(coluna.is_(True))


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
        por_nome: dict[str, object] = {}
        for nome, valor in sessao.execute(_so_ativos(select(alvo, coluna), fonte.tabela)).all():
            if not nome:
                continue
            campo = nome if tem_normalizado else normalizar(nome)
            # O SEGUNDO com o mesmo nome não sobrescreve o primeiro: marca os
            # dois como ambíguos. Sobrescrever é o que fazia a planilha apontar
            # para a instituição errada sem nada avisar.
            por_nome[campo] = AMBIGUO if campo in por_nome else valor
        indice[chave] = por_nome
    for chave, codigos in NO_CODIGO.items():
        indice[chave] = {normalizar(codigo): codigo for codigo in codigos}
    # O ÍNDICE QUE DESFAZ O HOMÔNIMO. "Assessoria da liderança" é cargo, não nome
    # próprio, e existe em vários órgãos — o banco permite, porque `interlocutor` é
    # único por `(nome_normalizado, instituicao_id)`. Pelo nome sozinho a
    # importação travava pedindo que a pessoa escolhesse qual; com a instituição da
    # linha não há o que escolher.
    indice[CHAVE_POR_INSTITUICAO] = _interlocutores_por_instituicao(sessao)
    indice[CHAVE_ORGAOS_DO_NOME] = _orgaos_de_cada_interlocutor(sessao)
    return indice


#: Chave do índice auxiliar: `(instituicao_id, nome normalizado) -> interlocutor_id`.
CHAVE_POR_INSTITUICAO = "interlocutores_por_instituicao"


def _interlocutores_por_instituicao(sessao: Session) -> dict[tuple[str, str], object]:
    """`(id da instituição, nome normalizado)` → id do interlocutor.

    Dois interlocutores com o mesmo nome NA MESMA instituição não existem — o
    banco tem índice único para isso —, então esta chave nunca é ambígua.
    """
    from app.banco.tabelas_stakeholders import Interlocutor

    linhas = sessao.execute(
        _so_ativos(
            select(Interlocutor.instituicao_id, Interlocutor.nome, Interlocutor.id),
            Interlocutor,
        )
    ).all()
    return {
        (str(instituicao_id), normalizar(nome)): pessoa_id
        for instituicao_id, nome, pessoa_id in linhas
        if instituicao_id and nome
    }


#: Chave do índice auxiliar: `nome normalizado do interlocutor -> nomes dos órgãos`.
CHAVE_ORGAOS_DO_NOME = "orgaos_do_interlocutor"


def _orgaos_de_cada_interlocutor(sessao: Session) -> dict[str, tuple[str, ...]]:
    """Nome normalizado → os nomes das instituições em que aquele nome existe.

    SÓ PARA A MENSAGEM, e a mensagem é o ponto: "Ana Prado não é da Câmara
    Municipal" manda a pessoa procurar; "Ana Prado é do Valor Econômico" a deixa
    consertar sem sair da tela. Todo o custo é uma consulta a mais no upload.
    """
    from app.banco.tabelas_stakeholders import Instituicao, Interlocutor

    linhas = sessao.execute(
        _so_ativos(
            select(Interlocutor.nome, Instituicao.nome).join(
                Instituicao, Interlocutor.instituicao_id == Instituicao.id
            ),
            Interlocutor,
        )
    ).all()
    de_quem: dict[str, set[str]] = {}
    for pessoa, orgao in linhas:
        if pessoa and orgao:
            de_quem.setdefault(normalizar(pessoa), set()).add(orgao)
    return {nome: tuple(sorted(orgaos)) for nome, orgaos in de_quem.items()}


def indice_completo(sessao: Session) -> dict[str, dict[str, object]]:
    """O índice de TODOS os vocabulários, numa leitura só.

    PARA QUEM PRECISA DELE VÁRIAS VEZES NA MESMA RESPOSTA. `_indice` custa uma
    consulta por vocabulário, e `indice_do_vocabulario` o reconstrói INTEIRO a
    cada chamada. A resposta da conferência pergunta duas coisas por grupo — qual
    é o alvo deste nome, e este valor é ambíguo —, então perguntá-las pelo atalho
    de um vocabulário custa o índice inteiro por grupo.

    MEDIDO (11/10/2026): a resposta custava 19 consultas, iguais para 3 e para 30
    grupos. Uma pergunta a mais por grupo a levou para 67 e 499. Com 500 valores
    distintos pendentes seriam milhares de consultas numa leitura de tela.
    """
    return _indice(sessao)


def indice_do_vocabulario(sessao: Session, vocabulario: str) -> dict[str, object]:
    """Nome normalizado → valor que entra na interação, para UM vocabulário.

    A API a usa para dar à sugestão o `alvo` que `apontar` aceita. Passa pelo
    `_indice` inteiro de propósito: é a MESMA resolução que a proposta usa, com o
    mesmo filtro de `ativo` e a mesma marca de ambiguidade — uma segunda leitura
    com regra própria é como as duas verdades nascem.
    """
    return _indice(sessao).get(vocabulario, {})


def vocabularios(sessao: Session) -> dict[str, list[str]]:
    """Os nomes que a pessoa LÊ, por vocabulário — o que o modelo `.xlsx` lista.

    Separado de `_indice` porque são duas perguntas: o modelo mostra o rótulo, a
    proposta resolve para o id ou o código. Juntá-los faria a aba de vocabulário
    listar `propositivo` onde a pessoa espera "Positivo".
    """
    listas: dict[str, list[str]] = {}
    for chave, fonte in NO_BANCO.items():
        # SÓ OS ATIVOS, como as telas de cadastro e de catálogo já fazem. Oferecer
        # um cadastro aposentado na lista suspensa seria convidar a pessoa a
        # escolher exatamente o que a importação vai recusar.
        nomes = sessao.scalars(
            _so_ativos(select(fonte.tabela.nome), fonte.tabela).order_by(fonte.tabela.nome)
        ).all()
        listas[chave] = [nome for nome in nomes if nome]
    for chave, codigos in NO_CODIGO.items():
        listas[chave] = list(codigos)
    return listas


def interlocutores_com_instituicao(sessao: Session) -> list[tuple[str, str]]:
    """(nome do interlocutor, nome da instituição dele) — os pares que a aba lista.

    A RELAÇÃO QUE O FRONT TEM, servida à planilha. `interlocutoresDaInstituicao`,
    em `src/dominio/frentes.ts`, reduz a lista do formulário ao `instituicao_id`
    escolhido; a planilha só consegue fazer o mesmo se souber de quem é cada um.

    SÓ OS ATIVOS, dos dois lados: oferecer alguém de uma instituição desativada
    seria convidar a escolher o que a importação recusa — e é a mesma regra que a
    tela usa, que checa a pessoa E o órgão.

    Sem instituição a pessoa não entra: ela não tem como aparecer numa suspensa
    dependente, e o cadastro solto é defeito de base, não caso a suportar aqui.
    """
    from app.banco.tabelas_stakeholders import Instituicao, Interlocutor

    linhas = sessao.execute(
        _so_ativos(
            select(Interlocutor.nome, Instituicao.nome).join(
                Instituicao, Interlocutor.instituicao_id == Instituicao.id
            ),
            Interlocutor,
        )
        .where(Instituicao.ativo.is_(True))
        .order_by(Instituicao.nome, Interlocutor.nome)
    ).all()
    return [(pessoa, orgao) for pessoa, orgao in linhas if pessoa and orgao]


def pares_de_vocabulario(sessao: Session) -> dict[str, list[tuple[str, str]]]:
    """Os vocabulários que saem em PARES — o valor e o dono dele.

    É O QUE FAZ A SUSPENSA DEPENDENTE FUNCIONAR, e são dois: o interlocutor com a
    instituição dele, e a subcategoria de público com a categoria dona. A aba sai com o
    valor na coluna A e o dono na B, agrupada por dono, e a fórmula recorta o bloco.

    UM SÓ LUGAR PARA OS DOIS, porque é um mecanismo só: o dia em que houver um terceiro
    par, ele entra aqui e a planilha o trata sem nenhuma linha nova no gerador.
    """
    from app.banco.tabelas_catalogo import CategoriaPublico as _Categoria
    from app.banco.tabelas_catalogo import SubcategoriaPublico as _Subcategoria

    subcategorias = sessao.execute(
        select(_Subcategoria.nome, _Categoria.nome)
        .join(_Categoria, _Categoria.id == _Subcategoria.categoria_publico_id)
        .where(_Subcategoria.ativo.is_(True), _Categoria.ativo.is_(True))
        .order_by(_Categoria.nome, _Subcategoria.ordem)
    ).all()
    return {
        "interlocutores": interlocutores_com_instituicao(sessao),
        "subcategorias_publico": [(sub, cat) for sub, cat in subcategorias if sub and cat],
    }


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


@dataclass(frozen=True, slots=True)
class _Resolucao:
    """O que saiu de uma célula: o valor, ou o cadastro que falta criar.

    DUAS SAÍDAS E NÃO UMA. Devolver só `None` para "não resolvi" misturava
    "não sei o que é isto" com "isto ainda vai ser criado" — e era essa mistura
    que fazia um cadastro declarado travar a linha.
    """

    valor: object | None = None
    #: `(vocabulário, nome)` quando a confirmação precisa criar este cadastro.
    a_criar: tuple[str, str] | None = None
    #: ESTE ITEM DA LISTA NÃO ENTRA NA AGENDA, e o aviso já explica por quê.
    #:
    #: NASCEU DO "AVISE MAS NÃO TRAVE" (11/10/2026). Um interlocutor que é de
    #: OUTRA instituição não pode ser ligado a esta agenda — a regra 4 do domínio
    #: diz que o participante pertence à instituição da agenda, e `impedimentos` a
    #: reconfere com a proposta montada. Avisar sem omitir empurraria a recusa
    #: para a confirmação, depois de a conferência ter dito que estava pronto.
    #:
    #: E NÃO DÁ PARA OMITIR DEIXANDO O CAMPO VAZIO:
    #: `ParticipanteDaOutraParteEntrada.interlocutor_id` é obrigatório, então
    #: construir o item sem ele estoura o pydantic — e o `except` daquele laço
    #: transforma o estouro em divergência que TRAVA. A trava voltaria pela porta
    #: de trás, com uma mensagem pior.
    omitir_o_item: bool = False


def _subcategoria_da_categoria_por_id(
    sessao: Session, categoria_id: object, nome: str
) -> int | None:
    """O id da subcategoria daquele nome, dentro da categoria daquele id.

    SEPARADA DA QUE RECEBE O OBJETO porque a conferência do upload tem o ID (vindo do
    índice) e a criação tem o objeto (vindo do banco). Uma função só teria de aceitar os
    dois, e "aceita qualquer coisa" é como o argumento errado passa sem ninguém notar.
    """
    from app.banco.tabelas_catalogo import SubcategoriaPublico

    procurado = normalizar(nome)
    candidatas = sessao.scalars(
        select(SubcategoriaPublico).where(
            SubcategoriaPublico.categoria_publico_id == categoria_id,
            SubcategoriaPublico.ativo.is_(True),
        )
    ).all()
    for candidata in candidatas:
        if normalizar(candidata.nome) == procurado:
            return candidata.id
    return None


def _conferir_o_declarado(
    sessao: Session,
    vocabulario: str,
    nome: str,
    declarado: Mapping[str, object],
    indice: Mapping,
    declarados: Mapping[str, frozenset[str]],
    coluna_nome: str,
    campo: str,
    divergencias: list[Divergencia],
) -> bool:
    """Confere as colunas da ABA DE CADASTRO, e devolve se está tudo bem.

    ERA O BURACO QUE A REVISÃO ACHOU, e ele tinha três sintomas: a abrangência escrita
    como "Minas Gerais" estourava a confirmação por violar o domínio da coluna no banco;
    o tier `999` falhava por chave estrangeira; e a subcategoria de outra categoria era
    DESCARTADA em silêncio, com o cadastro nascendo sem ela.

    A RAIZ ERA A MESMA: as células da AGENDA passavam por `_resolver`, e as da aba de
    CADASTRO não passavam por nada. Um vocabulário fechado tem de ser conferido onde
    todos os outros são — no upload, junto das outras pendências, com a coluna e o valor
    na mensagem.

    POR QUE NO UPLOAD E NÃO NA CONFIRMAÇÃO: é a diferença entre a pessoa consertar uma
    célula junto das outras e receber erro interno depois de ter conferido 500 linhas e
    clicado em subir.
    """
    tudo_bem = True
    for coluna in colunas_do_cadastro(vocabulario):
        bruto = declarado.get(coluna.campo)
        if bruto is None or str(bruto).strip() == "":
            continue
        texto = str(bruto).strip()

        if coluna.campo == "eh_porta_voz":
            # A MESMA REGRA DA COLUNA DE SIM/NÃO DA AGENDA: "talvez" lá é pendência, e
            # aqui virava `False` em silêncio.
            if _booleano(texto) not in (True, False):
                divergencias.append(
                    Divergencia(
                        campo=campo,
                        valor=nome,
                        mensagem=(
                            f"Na aba de cadastro, {coluna.nome!r} de {nome!r} está "
                            f"{texto!r}: responda sim ou não."
                        ),
                        coluna=coluna_nome,
                        trava=True,
                    )
                )
                tudo_bem = False
            continue

        if coluna.campo == "subcategoria_publico_id":
            # DENTRO DA CATEGORIA DECLARADA, porque o nome só é único ali. Incompatível
            # é pendência e não descarte: o valor não pertence à categoria escolhida, e
            # só a pessoa sabe qual dos dois está errado.
            categoria_nome = normalizar(str(declarado.get("categoria_publico_id") or ""))
            categoria_id = indice.get("categorias_publico", {}).get(categoria_nome)
            if categoria_id is None or categoria_id is AMBIGUO:
                continue
            if _subcategoria_da_categoria_por_id(sessao, categoria_id, texto) is None:
                divergencias.append(
                    Divergencia(
                        campo=campo,
                        valor=nome,
                        mensagem=(
                            f"Na aba de cadastro, {texto!r} não é uma subcategoria de "
                            f"{declarado.get('categoria_publico_id')!r}. Escolha uma da "
                            "lista, que se reduz pela categoria da linha."
                        ),
                        coluna=coluna_nome,
                        trava=True,
                    )
                )
                tudo_bem = False
            continue

        if not coluna.vocabulario or coluna.campo == "categoria_publico_id":
            # Texto livre não tem o que conferir, e a categoria já tem a recusa dela.
            continue

        # O QUE OUTRA ABA DECLAROU TAMBÉM VALE, e este era um defeito meu que dois
        # testes antigos pegaram: a pessoa cria a instituição na aba Instituições e o
        # interlocutor dela na aba Interlocutores, no MESMO arquivo. O nome ainda não
        # está no banco — vai nascer na mesma transação —, e conferir só contra o banco
        # transformava o uso normal das duas abas em pendência.
        #
        # MAS SÓ PARA O QUE A IMPORTAÇÃO REALMENTE CRIA, e este era o achado da revisão
        # seguinte: `areas_pessoa` tem aba e lista suspensa, mas é dicionário
        # administrado na plataforma — a importação não cria área nenhuma. Aceitar a
        # área "declarada" fazia a conferência dizer que estava tudo certo e a criação
        # omitir o campo, porque ela só grava `area_id` do que achou no banco. A pessoa
        # preenchia a área e o cadastro nascia sem ela, sem nada reclamar.
        declarados_que_valem = (
            declarados.get(coluna.vocabulario, frozenset())
            if coluna.vocabulario in VOCABULARIOS_QUE_A_IMPORTACAO_CRIA
            else frozenset()
        )
        conhecido = indice.get(coluna.vocabulario, {}).get(normalizar(texto))
        if conhecido is None and normalizar(texto) not in declarados_que_valem:
            divergencias.append(
                Divergencia(
                    campo=campo,
                    valor=nome,
                    mensagem=(
                        f"Na aba de cadastro, {coluna.nome!r} de {nome!r} está {texto!r}, "
                        f"que não existe na lista. Escolha um valor da suspensa."
                    ),
                    coluna=coluna_nome,
                    trava=True,
                )
            )
            tudo_bem = False
        elif conhecido is AMBIGUO:
            # DECLAROU ALGO QUE NÃO RESOLVE, e isto é diferente de não declarar —
            # achado ALTA de revisão (11/10/2026). O nome ambíguo ESTÁ no índice,
            # então a checagem acima o aceitava; depois, `_instituicao_declarada`
            # devolvia `None` para a sentinela, e `None` quer dizer "use a
            # instituição da agenda". Resultado: ela declarava um órgão e o
            # cadastro nascia em OUTRO, em silêncio — o mesmo chute calado que a
            # preferência pela aba acabou de fechar, reaberto por outra porta.
            #
            # A FRASE DÁ AS DUAS SAÍDAS REAIS, e nenhuma delas é "escreva o nome
            # certo": os dois cadastros têm o MESMO nome, então não há o que
            # corrigir na célula. Ou ela deixa a coluna em branco — e aí a
            # instituição da agenda passa a valer, legitimamente, porque ela não
            # declarou nada —, ou cadastra a pessoa pela Administração e aponta
            # para ela na conferência.
            divergencias.append(
                Divergencia(
                    campo=campo,
                    valor=nome,
                    mensagem=(
                        f"Na aba de cadastro, {coluna.nome!r} de {nome!r} está "
                        f"{texto!r}, e existe mais de um cadastro com esse nome — não "
                        "tenho como saber qual. Deixe a coluna em branco para usar a "
                        "instituição desta agenda, ou cadastre a pessoa pela tela de "
                        "Administração e aponte para ela aqui."
                    ),
                    coluna=coluna_nome,
                    trava=True,
                )
            )
            tudo_bem = False
    return tudo_bem


def _resolver(
    sessao: Session | None,
    valor: object,
    coluna_nome: str,
    vocabulario: str,
    campo: str,
    indice: dict[str, dict[str, object]],
    declarados: Mapping[str, frozenset[str]],
    divergencias: list[Divergencia],
    apontados: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    cadastros_declarados: Mapping[str, Mapping[str, Mapping[str, object]]] = MAPPING_VAZIO,
) -> _Resolucao:
    """O valor resolvido, o cadastro a criar, ou a divergência anotada."""
    if valor is None:
        return _Resolucao()
    texto = str(valor)
    # A DECISÃO DA PESSOA VEM PRIMEIRO. Ela já disse, na conferência, que
    # "Prefeitura de Campinas" é aquele cadastro — e o nome continua não
    # existindo no banco, então sem isto a confirmação o recusaria de novo e
    # jogaria fora a decisão que ela tomou.
    escolhido = apontados.get((campo, texto))
    if escolhido is not None:
        return _Resolucao(valor=escolhido)
    conhecidos = indice.get(vocabulario, {})
    veredito = classificar(texto, vocabulario, conhecidos, declarados.get(vocabulario, frozenset()))

    if veredito == "resolve":
        achado = conhecidos[normalizar(texto)]
        if achado is AMBIGUO:
            divergencias.append(
                Divergencia(
                    campo=campo,
                    valor=texto,
                    mensagem=(
                        f"{coluna_nome}: existe mais de um cadastro com o nome "
                        f"{texto!r}. Escolha qual na conferência."
                    ),
                    trava=True,
                    coluna=coluna_nome,
                )
            )
            return _Resolucao()
        return _Resolucao(valor=achado)

    if veredito == "cria":
        # A CATEGORIA DA INSTITUIÇÃO É CONFERIDA AQUI, no upload, e não na
        # confirmação — e desde 11/10/2026 ela AVISA em vez de recusar.
        #
        # ESTE COMENTÁRIO DIZIA "O TIPO DA INSTITUIÇÃO É EXIGIDO AQUI… recusar agora
        # põe a pendência na tela junto das outras", e era verdade até a decisão do
        # dono do produto: "pode registrar como entidade e marcar para revisar".
        # Nada é exigido aqui; `entidade` é o tipo de quem nasce sem categoria, e a
        # frente deixa de ser chutada porque `entidade` é o único tipo fora de
        # `FRENTE_UNICA_DO_TIPO`. Achado de revisão: comentário errado custa o mesmo
        # que código errado, só demora mais a doer — foi uma frase desatualizada
        # neste arquivo que me fez escrever `nivel="livre"` e estourar o banco.
        #
        # O LUGAR CONTINUA SENDO O UPLOAD, e por uma razão que não mudou: a
        # conferência é onde a pessoa vê o que vai acontecer. Um aviso que só
        # aparecesse na confirmação chegaria depois de ela já ter conferido tudo.
        # O QUE A PESSOA ESCREVEU NAS OUTRAS COLUNAS daquela aba, para a criação ter
        # com que nascer. Era só a categoria de público; passou a ser tudo, porque as
        # abas ganharam os campos do formulário da plataforma — e um campo que não
        # viaja até aqui é um campo que ela preencheu e que o cadastro nasce sem.
        declarado = dict(
            (cadastros_declarados.get(vocabulario) or {}).get(normalizar(texto)) or {}
        )
        categoria = declarado.get("categoria_publico_id")
        if vocabulario == "instituicoes" and (
            categoria is None
            or normalizar(str(categoria)) not in indice.get("categorias_publico", {})
        ):
            # AVISA E DEIXA NASCER — era `trava=True` até 11/10/2026.
            #
            # A INCOERÊNCIA QUE ISTO CONSERTA (achado de revisão): um nome que
            # NÃO está na aba passou a entrar sem categoria, e um nome que ESTÁ
            # na aba sem categoria válida continuava travando. Quem usou a aba
            # levava a trava que quem não usou deixou de levar — o oposto do que
            # se quer, e contra o "todos os campos são opcionais" do pedido.
            #
            # UM CAMINHO SÓ PARA NASCER INCOMPLETO, qualquer que seja o jeito
            # como o nome chegou. É o padrão de cadastro que o dono do produto
            # pediu, com os parâmetros de cada caso vindo do que a aba trouxer.
            #
            # A FRASE DIZ O QUE SE PERDE porque ela escreveu algo ali e merece
            # saber por que não valeu.
            divergencias.append(
                Divergencia(
                    campo=campo,
                    valor=texto,
                    mensagem=(
                        f"{coluna_nome}: vou cadastrar {texto!r} sem categoria de "
                        "público — o que está na coluna ao lado não é uma categoria "
                        "da lista. Sem ela a instituição fica fora da taxonomia de "
                        "públicos do Score, e a frente da agenda sai genérica. "
                        "Complete o cadastro na plataforma depois."
                    ),
                    trava=False,
                    coluna=coluna_nome,
                    acao_padrao="criar",
                    #: O RESTO DO QUE ELA ESCREVEU VIAJA, e sem isto o cadastro
                    #: nasceria sem a abrangência e a relevância que ela
                    #: preencheu — perder duas colunas por causa de uma terceira.
                    declarado=declarado or None,
                )
            )
            return _Resolucao(a_criar=(vocabulario, texto))
        # O QUE ELA DECLAROU NAS OUTRAS COLUNAS é conferido ANTES da promessa: um
        # valor fora da lista ali estouraria a confirmação, e a conferência teria dito
        # que estava tudo pronto.
        if sessao is not None and not _conferir_o_declarado(
            sessao,
            vocabulario,
            texto,
            declarado,
            indice,
            declarados,
            coluna_nome,
            campo,
            divergencias,
        ):
            return _Resolucao()

        # Declarado na aba editável: não é pendência da pessoa, é trabalho da
        # confirmação. Aparece na conferência como "vou criar", sem travar — e o
        # valor volta em `a_criar` para a confirmação ter o que criar.
        divergencias.append(
            Divergencia(
                campo=campo,
                valor=texto,
                mensagem=f"{coluna_nome}: vou cadastrar {texto!r}, que você declarou na aba.",
                trava=False,
                coluna=coluna_nome,
                declarado=declarado or None,
                # MARCA A AÇÃO já aqui, e não só quando a pessoa decide na tela:
                # é assim que a confirmação encontra o que criar sem depender do
                # arquivo original, que não fica guardado. Declarar na aba e
                # escolher "criar" na conferência passam a ter a MESMA forma.
                acao="criar",
            )
        )
        return _Resolucao(a_criar=(vocabulario, texto))

    # TRÊS CASOS, TRÊS MENSAGENS, porque a saída de cada um é diferente e mandar
    # a pessoa pelo caminho errado é pior que não dizer nada.
    if vocabulario in VOCABULARIOS_FECHADOS:
        motivo = (
            f"{coluna_nome}: {texto!r} não está na lista, e esta lista não aceita "
            "valor novo — mudá-la é mudança de regra. Escolha um dos valores."
        )
    elif vocabulario not in VOCABULARIOS_QUE_A_IMPORTACAO_CRIA:
        # Dicionário administrado: escrever na aba NÃO resolve, e dizer que
        # resolve mandaria a pessoa tentar duas vezes a mesma coisa.
        motivo = (
            f"{coluna_nome}: {texto!r} não existe. Este cadastro é mantido pela "
            "tela de Administração — cadastre-o lá e aponte para ele aqui."
        )
    else:
        # NÃO TRAVA MAIS, e esta é a mudança pedida pelo dono do produto
        # (11/10/2026): "o ponto principal é não barrar o registro".
        #
        # O QUE ERA: a importação já sabia criar os quatro cadastros desta lista,
        # mas só se a pessoa escrevesse o nome TAMBÉM na aba de cadastro. A trava
        # não era "falta dado" — era "falta dado em dois lugares". Com várias
        # reuniões num dia, preencher duas abas para cada nome novo é o que faz o
        # registro não acontecer.
        #
        # É O MODELO DA CLIPEI/BITES, que ele citou: lá a menção entra mesmo
        # quando o veículo não está no cadastro, com o texto cru preservado, e o
        # vínculo se faz depois — "o estado normal enquanto o cadastro não cobre
        # o fornecedor".
        #
        # O CADASTRO NASCE COM O QUE HOUVER e fica incompleto até alguém
        # completá-lo na plataforma. A divergência continua aparecendo na
        # conferência, agora como AVISO e não como impedimento.
        divergencias.append(
            Divergencia(
                campo=campo,
                valor=texto,
                mensagem=(
                    f"{coluna_nome}: vou cadastrar {texto!r}, que não existe ainda. "
                    "Ele nasce só com o nome — complete o cadastro na plataforma "
                    "depois, ou aponte aqui para um que já exista."
                ),
                trava=False,
                coluna=coluna_nome,
                # SEM `acao`, e esta é a diferença que mantém a oferta de apontar.
                #
                # O caso "declarada na aba", logo acima, marca `acao="criar"`
                # porque ali a pessoa PEDIU o cadastro — a decisão está tomada, e
                # `linhas_com` ignora divergência decidida justamente para um
                # segundo clique não sobrescrever o que ela escolheu.
                #
                # AQUI ELA SÓ DIGITOU UM NOME na coluna da agenda. Criar é o
                # PADRÃO, não a escolha dela — então a divergência fica aberta, e
                # a conferência continua podendo oferecer "aponte para 'Prefeitura
                # Municipal de Campinas', que já existe". É essa oferta que
                # impede a duplicata, e medida ela importa: 3.809 instituições
                # para 3.781 nomes distintos, com 28 duplicatas já no banco.
                #
                # E NÃO TRAVA NADA: `a_criar` põe a linha em "esperando criação",
                # que é trabalho da confirmação, não pendência da pessoa.
                #
                # `acao_padrao` É O QUE FAZ A CONFIRMAÇÃO FUNCIONAR sem clique:
                # `acao` vazia mantém a oferta de apontar, e isto diz à
                # confirmação o que fazer quando ninguém aponta. Sem este campo o
                # fluxo inteiro dava 409 — achado de revisão, com teste.
                acao_padrao="criar",
            )
        )
        return _Resolucao(a_criar=(vocabulario, texto))

    divergencias.append(
        Divergencia(
            campo=campo, valor=texto, mensagem=motivo, coluna=coluna_nome, trava=True
        )
    )
    return _Resolucao()


def _conferir_orgao_declarado(
    texto: str,
    coluna_nome: str,
    campo: str,
    instituicao_escrita: str,
    cadastros_declarados: Mapping[str, Mapping[str, Mapping[str, object]]],
    divergencias: list[Divergencia],
) -> bool:
    """A contradição entre o órgão declarado ao lado do nome e o da agenda.

    Declarar "Carla Nova — Câmara Municipal" e usá-la numa agenda do Valor
    Econômico é pedir duas coisas incompatíveis, e o domínio só diz isso na
    CONFIRMAÇÃO — depois da conferência inteira. Criar a pessoa em um dos dois e
    seguir seria escolher por ela, calado, num dado que nenhuma tela mostra depois.

    Sem órgão declarado não há contradição: a pessoa nasce na instituição da
    agenda, que é o comportamento de antes desta coluna existir.

    DEVOLVE "ESTE ITEM NÃO ENTRA" — era `None` até 11/10/2026, quando o aviso
    deixou de travar. Quem decide omitir é o laço das listas, e ele só pode
    decidir se souber: o vínculo com esta agenda é o que a regra 4 não aceita, e
    `impedimentos` o recusaria na confirmação.
    """
    do_interlocutor = (cadastros_declarados.get("interlocutores") or {}).get(
        normalizar(texto)
    ) or {}
    declarado = do_interlocutor.get("instituicao_id")
    if not declarado or not instituicao_escrita:
        return False
    if normalizar(str(declarado)) == normalizar(instituicao_escrita):
        return False
    # AVISA E DEIXA A AGENDA ENTRAR, pelo mesmo motivo do caso acima e com a
    # mesma consequência: o cadastro declarado NASCE, com a instituição que ela
    # declarou — porque escrever na aba é dizer "quero que isto exista" —, mas o
    # vínculo com ESTA agenda não se faz.
    divergencias.append(
        Divergencia(
            campo=campo,
            valor=texto,
            mensagem=(
                f"{coluna_nome}: você declarou {texto!r} na aba de interlocutores como "
                f"sendo de outra instituição, e esta agenda é de "
                f"{instituicao_escrita!r}. Um interlocutor fala por uma instituição "
                "só, então a agenda entra SEM esta pessoa. Deixe as duas iguais, ou "
                "aponte para o cadastro certo na conferência."
            ),
            trava=False,
            coluna=coluna_nome,
        )
    )
    return True


def _interlocutor_da_instituicao(
    texto: str,
    coluna_nome: str,
    campo: str,
    indice: dict,
    instituicao_id: object,
    instituicao_escrita: str,
    divergencias: list[Divergencia],
) -> _Resolucao | None:
    """O interlocutor daquela instituição, a recusa, ou `None` para seguir adiante.

    A RELAÇÃO QUE O FRONT TEM, do lado do servidor.
    `interlocutoresDaInstituicao` reduz a lista do formulário ao órgão escolhido;
    aqui a mesma informação faz duas coisas que a lista solta não fazia:

    DESFAZ O HOMÔNIMO. "Assessoria da liderança" é cargo, não nome próprio, e
    existe em vários órgãos — o banco permite, porque `interlocutor` é único por
    `(nome_normalizado, instituicao_id)`. Pelo nome sozinho a importação travava
    pedindo à pessoa que escolhesse qual; com o órgão da linha não há o que
    escolher, e a pendência desaparece.

    DEIXA DE FORA quem é de outro órgão — e AVISA, sem travar (11/10/2026). A
    regra 4 do domínio — o participante pertence à instituição da agenda —
    recusava isso na CONFIRMAÇÃO, depois de a pessoa ter conferido tudo. A
    suspensa dependente previne o erro no Excel, mas a planilha convertida para o
    Google Sheets pode perder a validação, e o arquivo pode não ter saído do nosso
    modelo: quem garante é aqui.

    ATÉ 11/10/2026 ISSO TRAVAVA A IMPORTAÇÃO INTEIRA, e o dono do produto pediu o
    contrário: "sempre aponte a inconsistência mas não trave". Agora a agenda
    entra sem a pessoa, com o aviso na linha — e apontar o cadastro certo na
    conferência a traz de volta num clique.

    `None` significa "não sei, siga pelo caminho normal" — sem órgão na linha, ou
    com um nome que não existe em cadastro nenhum, que é o caminho de quem declara
    alguém novo.
    """
    if instituicao_id is None or instituicao_id is AMBIGUO:
        return None
    chave = normalizar(texto)
    achado = indice.get(CHAVE_POR_INSTITUICAO, {}).get((str(instituicao_id), chave))
    if achado is not None:
        return _Resolucao(valor=achado)
    orgaos = indice.get(CHAVE_ORGAOS_DO_NOME, {}).get(chave, ())
    if not orgaos:
        # O nome não existe em cadastro nenhum: é criação, e quem trata disso é
        # `_resolver` com a declaração da aba.
        return None
    # AVISA E DEIXA A AGENDA ENTRAR — era `trava=True` até 11/10/2026, a pedido
    # do dono do produto: "sempre aponte a inconsistência mas não trave".
    #
    # SEM A PESSOA, E ISSO ESTÁ NA FRASE. O vínculo é o que não pode acontecer: a
    # regra 4 do domínio não aceita participante de outra instituição, e
    # `impedimentos` a reconfere. O que se perde é a presença daquele grupo, e
    # ela não significa nada sem a pessoa a que se refere.
    #
    # E A SAÍDA CONTINUA A UM CLIQUE: a divergência fica aberta, então apontar
    # para o cadastro certo na conferência faz a pessoa entrar — `apontados` é
    # consultado ANTES desta checagem, justamente para a decisão dela valer.
    divergencias.append(
        Divergencia(
            campo=campo,
            valor=texto,
            mensagem=(
                f"{coluna_nome}: {texto!r} não é de {instituicao_escrita!r}, e sim de "
                f"{' ou '.join(repr(orgao) for orgao in orgaos)}. Um interlocutor fala "
                "por uma instituição só, então a agenda entra SEM esta pessoa. "
                "Corrija a instituição da agenda, ou aponte para o cadastro certo "
                "na conferência."
            ),
            trava=False,
            coluna=coluna_nome,
        )
    )
    return _Resolucao(omitir_o_item=True)


def _listas_da_linha(
    sessao: Session,
    linha: LinhaBruta,
    indice: dict[str, dict[str, object]],
    declarados: Mapping[str, frozenset[str]],
    apontados: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    cadastros_declarados: Mapping[str, Mapping[str, Mapping[str, object]]] = MAPPING_VAZIO,
    instituicao_id: object = None,
    instituicao_escrita: str = "",
) -> tuple[dict[str, list], list[Divergencia], list[tuple[str, str]], list[Mapping]]:
    """As pessoas e os materiais de UMA linha, montados das colunas numeradas.

    TUDO NUMA ABA SÓ. Antes cada pessoa era uma linha numa aba filha, ligada pelo
    `Código`; agora é um grupo de colunas na própria linha da agenda. O vínculo
    deixou de existir, e com ele a classe inteira de erro que ele produzia — código
    órfão, código repetido, participante na agenda errada.

    Devolve quatro coisas: as listas montadas por campo, as divergências, os
    cadastros a criar, e os itens que ESPERAM um cadastro com o que já se sabe
    deles. O item que espera não pode ser descartado: ele leva a presença e o papel
    com ele, e a pessoa não preencheu aquilo para nada.

    O GRUPO VAZIO É IGNORADO em silêncio, e é o caso comum: a agenda tem dois
    interlocutores e a planilha tem espaço para quatro. Acusar "falta o
    Interlocutor 3" em toda linha afogaria a conferência em pendências inventadas.
    """
    colunas = {coluna.nome: coluna for coluna in aba_de(ABA_PRINCIPAL).colunas}
    listas: dict[str, list] = {}
    divergencias: list[Divergencia] = []
    a_criar: list[tuple[str, str]] = []
    esperando: list[Mapping] = []

    for campo_da_lista, grupo in GRUPOS_NUMERADOS.items():
        for numero in range(1, grupo["quantos"] + 1):
            do_grupo: dict[str, object] = {}
            do_item: list[Divergencia] = []
            criar_do_item: list[tuple[str, str]] = []
            algo_preenchido = False
            #: Alguma célula deste item disse "este item não entra na agenda".
            omitir_o_item = False

            for molde, campo in grupo["colunas"].items():
                coluna_nome = molde.format(n=numero)
                bruto = linha.celulas.get(coluna_nome)
                if bruto is not None:
                    algo_preenchido = True
                coluna = colunas[coluna_nome]
                if coluna.vocabulario:
                    campo_cheio = f"{campo_da_lista}.{campo}"
                    resolucao = None
                    if coluna.vocabulario == "interlocutores" and bruto is not None:
                        # A DECISÃO DA PESSOA AINDA VEM PRIMEIRO: se ela apontou um
                        # cadastro para este nome na conferência, é aquele, e nem a
                        # instituição da linha desfaz isso.
                        if apontados.get((campo_cheio, str(bruto))) is None:
                            resolucao = _interlocutor_da_instituicao(
                                str(bruto),
                                coluna_nome,
                                campo_cheio,
                                indice,
                                instituicao_id,
                                instituicao_escrita,
                                do_item,
                            )
                        if resolucao is None and _conferir_orgao_declarado(
                            str(bruto),
                            coluna_nome,
                            campo_cheio,
                            instituicao_escrita,
                            cadastros_declarados,
                            do_item,
                        ):
                            omitir_o_item = True
                    if resolucao is None:
                        resolucao = _resolver(
                            sessao,
                            bruto,
                            coluna_nome,
                            coluna.vocabulario,
                            campo_cheio,
                            indice,
                            declarados,
                            do_item,
                            apontados,
                            cadastros_declarados,
                        )
                    resolvido = resolucao.valor
                    if resolucao.a_criar is not None:
                        criar_do_item.append(resolucao.a_criar)
                    if resolucao.omitir_o_item:
                        omitir_o_item = True
                else:
                    resolvido = bruto
                if resolvido is not None:
                    do_grupo[campo] = resolvido

            if not algo_preenchido:
                # O grupo em branco é espaço sobrando, não omissão.
                continue

            for chave in ("exigida", "tambem_exigida"):
                molde = grupo.get(chave)
                if not molde:
                    continue
                coluna_nome = molde.format(n=numero)
                if linha.celulas.get(coluna_nome) is None:
                    do_item.append(
                        Divergencia(
                            campo=campo_da_lista,
                            valor=coluna_nome,
                            mensagem=f"Falta {coluna_nome}, e o grupo {numero} tem dado.",
                            coluna=coluna_nome,
                            trava=True,
                        )
                    )

            divergencias.extend(do_item)
            a_criar.extend(criar_do_item)

            if any(divergencia.trava for divergencia in do_item):
                continue
            # O ITEM QUE NÃO PODE SE LIGAR A ESTA AGENDA fica fora, e o aviso que
            # já entrou em `divergencias` diz por quê. ANTES do `esperando` e
            # antes do modelo: o modelo exige o vínculo e estouraria, e o
            # `except` lá embaixo transformaria o estouro em trava.
            if omitir_o_item:
                continue
            if criar_do_item:
                esperando.append(
                    {
                        "campo_da_lista": campo_da_lista,
                        "linha_origem": linha.numero,
                        "valores": do_grupo,
                        "aguardando": tuple(criar_do_item),
                    }
                )
                continue

            # O PRIMEIRO INTERLOCUTOR É O PRINCIPAL. Com abas filhas havia uma
            # coluna para marcá-lo; em colunas numeradas, listar a pessoa mais
            # importante primeiro é mais fácil de preencher do que dizer "qual
            # número é o principal".
            if campo_da_lista == "outra_parte" and PRIMEIRO_INTERLOCUTOR_E_PRINCIPAL:
                do_grupo["principal"] = numero == 1

            try:
                listas.setdefault(campo_da_lista, []).append(grupo["modelo"](**do_grupo))
            except Exception as erro:  # noqa: BLE001 - vira pendência, não 500
                divergencias.append(
                    Divergencia(
                        campo=campo_da_lista,
                        valor=str(do_grupo),
                        mensagem=f"Grupo {numero} de {campo_da_lista}: {erro}",
                        # SEM COLUNA, e é de propósito: este `except` não sabe qual
                        # campo o modelo reprovou. Anotar aqui a última coluna que o
                        # laço viu faria a grade pintar de vermelho uma célula
                        # CORRETA — mandando a pessoa consertar o que está certo
                        # enquanto o problema real fica sem marca nenhuma. Sem
                        # coluna, o erro aparece na mensagem da linha, que é onde ele
                        # pertence: o mesmo tratamento que as recusas de comparação
                        # entre itens já recebem, em `impedimentos`.
                        trava=True,
                    )
                )

    return listas, divergencias, a_criar, esperando


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
    """Uma proposta por linha da aba Agendas, a partir do arquivo."""
    propostas, _, _ = propor_com_as_declaracoes(sessao, conteudo)
    return propostas


def propor_com_as_declaracoes(
    sessao: Session, conteudo: bytes
) -> tuple[list[Proposta], dict[str, frozenset[str]], dict[str, dict[str, dict[str, object]]]]:
    """As propostas E o que a pessoa declarou nas abas de cadastro.

    QUEM SOBE PRECISA DAS DUAS COISAS: as propostas para gravar as linhas, e as
    declarações para GUARDAR — o arquivo não é preservado, e sem isso uma declaração que
    nenhuma linha usou desaparece no fim do upload (ver `ABA_DAS_DECLARACOES`).

    DEVOLVE EM VEZ DE DEIXAR RELER. `propor` já abre o arquivo três vezes — a estrutura,
    os nomes declarados, os campos declarados —, e pedir a quem chama que releia daria
    uma quarta e uma quinta leitura do mesmo bytes para um dado que acabou de ser lido.
    """
    linhas = ler(conteudo)
    nomes = ler_declarados(conteudo)
    campos = ler_cadastros_declarados(conteudo)
    return (
        propor_de_linhas(sessao, linhas, nomes, cadastros_declarados=campos),
        nomes,
        campos,
    )


def propor_de_linhas(
    sessao: Session,
    por_aba: Mapping[str, list[LinhaBruta]],
    declarados: Mapping[str, frozenset[str]],
    apontados: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    cadastros_declarados: Mapping[str, Mapping[str, Mapping[str, object]]] = MAPPING_VAZIO,
) -> list[Proposta]:
    """O mesmo, a partir de linhas JÁ LIDAS.

    SEPARADO DE `propor` porque a confirmação não tem o arquivo. Ela reconstrói
    as linhas de `importacao_linha.dados_brutos` e passa por aqui de novo, contra
    o banco COMO ELE ESTÁ NAQUELE MOMENTO — que é o que a spec quer dizer por
    "a resolução é refeita na confirmação". Ter duas portas para a mesma máquina
    é o que impede a confirmação de reimplementar a resolução e divergir dela.
    """
    indice = _indice(sessao)
    representantes = _quem_representa(sessao)

    colunas_de_agenda = aba_de(ABA_PRINCIPAL).colunas
    propostas: list[Proposta] = []

    for linha in por_aba[ABA_PRINCIPAL]:
        divergencias: list[Divergencia] = []
        campos: dict[str, object] = {}
        listas: dict[str, list[object]] = {}
        a_criar: list[tuple[str, str]] = []

        for coluna in colunas_de_agenda:
            if not coluna.campo:
                continue
            if coluna.campo in GRUPOS_NUMERADOS:
                # Coluna de grupo numerado: quem a lê é `_listas_da_linha`, que
                # sabe a qual item ela pertence. Aqui ela seria resolvida como se
                # fosse campo de valor único da agenda.
                continue
            bruto = linha.celulas.get(coluna.nome)
            e_lista = coluna.campo in ("temas", "areas")

            if coluna.vocabulario:
                resolucao = _resolver(
                    sessao,
                    bruto,
                    coluna.nome,
                    coluna.vocabulario,
                    coluna.campo,
                    indice,
                    declarados,
                    divergencias,
                    apontados,
            cadastros_declarados,
                )
                valor = resolucao.valor
                if resolucao.a_criar is not None:
                    a_criar.append(resolucao.a_criar)
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
                            coluna=coluna.nome,
                        )
                    )
            elif coluna.campo in ("preve_desdobramento", "sensivel"):
                convertido = _booleano(bruto)
                if isinstance(convertido, str):
                    divergencias.append(
                        Divergencia(
                            campo=coluna.campo,
                            valor=convertido,
                            mensagem=f"{coluna.nome}: responda sim ou não, não {convertido!r}.",
                            trava=True,
                            coluna=coluna.nome,
                        )
                    )
                    valor = None
                else:
                    valor = convertido
                #: VAZIO É "NÃO" PARA `sensivel`, e não nulo.
                #:
                #: A coluna é `not null` no banco, e o agregado tem `False` por
                #: padrão — mas aqui o valor segue para um `dict` de alterações,
                #: e `None` ali afirmaria "sem classificação" num campo que não
                #: aceita. Planilha de 500 linhas com a coluna em branco tem de
                #: produzir 500 agendas comuns, não 500 erros.
                if coluna.campo == "sensivel" and valor is None:
                    valor = False
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
                            coluna=coluna.nome,
                        )
                    )
                    valor = None
            else:
                valor = bruto

            if valor is None:
                continue
            if e_lista:
                ja_na_lista = listas.setdefault(coluna.campo, [])
                if valor in ja_na_lista:
                    escrito = _texto_da_celula(bruto)
                    de_onde = _primeira_coluna_com(
                        linha, colunas_de_agenda, coluna.campo, bruto
                    )
                    # O MESMO TEMA DUAS VEZES NA MESMA AGENDA É UMA SÓ.
                    #
                    # `interacao_tema` tem chave primária `(interacao, tema)` e o
                    # repositório monta a lista com `set`, então a repetição JÁ
                    # era absorvida — em silêncio. Com três colunas de tema isso
                    # quase não acontecia; com 18 passou a ser o erro de
                    # preenchimento mais fácil de cometer, e silêncio aqui faria
                    # a pessoa conferir 18 células para descobrir por que a
                    # agenda tem 6 temas e ela preencheu 8.
                    #
                    # NÃO TRAVA, de propósito. Repetir um tema é escorregão de
                    # preenchimento, não dado errado: a agenda resultante está
                    # correta, e travar uma linha de um arquivo de 500 por isso
                    # ensinaria a ignorar o aviso — o mesmo raciocínio que
                    # `_avisar_duplicatas` usa para a agenda repetida.
                    divergencias.append(
                        Divergencia(
                            campo=coluna.campo,
                            valor=escrito,
                            mensagem=(
                                f"{coluna.nome}: {escrito!r} já está em {de_onde}. "
                                "Cada assunto conta uma vez — esta coluna foi ignorada."
                            ),
                            trava=False,
                            coluna=coluna.nome,
                        )
                    )
                    continue
                ja_na_lista.append(valor)
            else:
                campos[coluna.campo] = valor

        campos.update(listas)

        # AS PESSOAS E OS MATERIAIS SAEM DA PRÓPRIA LINHA, das colunas
        # numeradas. Antes vinham de abas filhas ligadas pelo `Código`, e o
        # vínculo era a parte que mais confundia quem preenchia.
        # A INSTITUIÇÃO DA LINHA JÁ ESTÁ RESOLVIDA aqui: o laço das colunas
        # simples rodou antes, e é dele que sai `campos["instituicao_id"]`. É essa
        # ordem que permite ao interlocutor ser resolvido DENTRO do órgão da agenda,
        # como o formulário do front faz.
        listas_da_linha, das_listas, criar_das_listas, esperando_tuplas = _listas_da_linha(
            sessao,
            linha,
            indice,
            declarados,
            apontados,
            cadastros_declarados=cadastros_declarados,
            instituicao_id=campos.get("instituicao_id"),
            instituicao_escrita=str(linha.celulas.get(COLUNA_DA_INSTITUICAO_DA_AGENDA) or ""),
        )
        divergencias.extend(das_listas)
        a_criar.extend(criar_das_listas)
        esperando = tuple(esperando_tuplas)
        campos.update(listas_da_linha)

        # `a_criar` sem repetição, preservando a ordem em que apareceu: a mesma
        # instituição declarada em duas colunas é UM cadastro a criar.
        pendentes_de_cadastro = tuple(dict.fromkeys(a_criar))
        aguardando_por_campo = {
            divergencia.campo
            for divergencia in divergencias
            if not divergencia.trava and divergencia.campo != CAMPO_DA_DUPLICATA
        }

        faltando = [campo for campo in OBRIGATORIOS if campo not in campos]
        for campo in faltando:
            # Só anuncia o que ainda não tem divergência própria: uma instituição
            # que não existe já foi explicada acima, e repetir a mesma pendência
            # com outras palavras faria a pessoa procurar dois problemas. Um campo
            # que ESPERA CADASTRO também não é "falta": ele já tem a sua linha na
            # conferência dizendo que vai ser criado.
            if campo in aguardando_por_campo:
                continue
            if not any(d.campo == campo for d in divergencias):
                divergencias.append(
                    Divergencia(
                        campo=campo,
                        valor="",
                        mensagem=(
                            f"Falta {coluna_do_campo(campo) or campo.replace('_', ' ')}"
                            ", que toda agenda precisa ter."
                        ),
                        coluna=coluna_do_campo(campo),
                        trava=True,
                    )
                )

        entrada = None
        travada = any(d.trava for d in divergencias)
        # NÃO TENTA MONTAR quando algo espera cadastro: faltaria o id obrigatório,
        # o Pydantic estouraria, e o erro genérico entraria como divergência que
        # TRAVA — transformando um cadastro corretamente declarado em pendência.
        # Era o primeiro defeito que a revisão do Codex achou.
        if not travada and not pendentes_de_cadastro and not esperando:
            try:
                entrada = InteracaoEntrada(**campos)
            except Exception as erro:  # noqa: BLE001 - vira pendência, não 500
                divergencias.append(
                    Divergencia(
                        campo="",
                        valor="",
                        mensagem=f"Linha {linha.numero}: {erro}",
                        # SEM COLUNA, pelo mesmo motivo do `except` dos grupos: o
                        # erro é da agenda inteira, e `coluna.nome` aqui seria a
                        # última coluna do laço — uma célula qualquer.
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

        propostas.append(
            Proposta(
                linha=linha,
                entrada=entrada,
                divergencias=divergencias,
                a_criar=pendentes_de_cadastro,
                filhas_pendentes=esperando,
            )
        )

    return _avisar_as_duas_grafias(
        _avisar_a_pessoa_em_duas_instituicoes(_avisar_duplicatas(sessao, propostas))
    )


def _avisar_as_duas_grafias(propostas: list[Proposta]) -> list[Proposta]:
    """Avisa que um nome novo vem escrito de duas formas — SEM travar.

    POR QUE ISTO EXISTE. A criação deduplica pelo nome NORMALIZADO e fica com a
    primeira grafia do arquivo, o que conserta um 422 real: "já existe uma pessoa
    chamada 'Renan Tiburcio' nesta instituição", numa planilha que trazia "Renan
    Tiburcio" e "Renan Tibúrcio" e numa base onde ela não existia.

    MAS A DEDUPLICAÇÃO É SILENCIOSA, e aí está o problema que este aviso resolve: o
    cadastro nasce com uma das grafias e ninguém fica sabendo que havia outra. A
    conferência existe para prometer o que vai acontecer, e "vou cadastrar como
    'Renan Tiburcio', não 'Renan Tibúrcio'" é uma escolha que a pessoa tem direito
    de ver — e de corrigir na planilha, se a errada for a que ficou.

    MEDIDO NO ARQUIVO REAL: três nomes de 318, os três na mesma instituição,
    diferindo só no acento — Barbara Halberstadt, Nathalia Maximo e Renan Tiburcio.

    SÓ O QUE VAI NASCER, pela mesma razão do aviso das duas instituições: para quem
    já está no cadastro, a resolução por linha já casa as duas grafias — é para
    isso que `nome_normalizado` existe.
    """
    #: (vocabulário, nome normalizado) -> as grafias que o arquivo trouxe, na
    #: ordem de aparição.
    #:
    #: O VOCABULÁRIO ENTRA NA CHAVE porque a deduplicação que este aviso explica
    #: é por `(vocabulario, normalizar(valor))` — duas tabelas diferentes não
    #: colidem entre si. Achado de revisão do Codex: agrupando só pelo nome, um
    #: tema e uma instituição com o mesmo texto normalizado viravam "duas
    #: grafias", e a conferência prometia uma deduplicação que não vai acontecer.
    #: Aviso falso numa tela de aviso é o que ensina a ignorá-la.
    grafias: dict[tuple[str, str], list[str]] = {}
    a_criar: set[tuple[str, str]] = set()
    for proposta in propostas:
        for vocabulario, nome in proposta.a_criar:
            if vocabulario in VOCABULARIOS_QUE_A_IMPORTACAO_CRIA:
                a_criar.add((vocabulario, normalizar(nome)))
        for coluna in aba_de(ABA_PRINCIPAL).colunas:
            if not coluna.vocabulario:
                continue
            bruto = proposta.linha.celulas.get(coluna.nome)
            if not bruto:
                continue
            formas = grafias.setdefault(
                (coluna.vocabulario, normalizar(str(bruto))), []
            )
            if str(bruto) not in formas:
                formas.append(str(bruto))

    de_duas = {
        chave: formas
        for chave, formas in grafias.items()
        if chave in a_criar and len(formas) > 1
    }
    if not de_duas:
        return propostas

    for proposta in propostas:
        for coluna in aba_de(ABA_PRINCIPAL).colunas:
            if not coluna.vocabulario:
                continue
            bruto = proposta.linha.celulas.get(coluna.nome)
            formas = (
                de_duas.get((coluna.vocabulario, normalizar(str(bruto))))
                if bruto
                else None
            )
            if not formas:
                continue
            proposta.divergencias.append(
                Divergencia(
                    campo=coluna.campo or coluna.nome,
                    valor=str(bruto),
                    mensagem=(
                        f"{coluna.nome}: este nome vem escrito de "
                        f"{len(formas)} formas nesta planilha "
                        f"({', '.join(repr(f) for f in formas)}). Vou cadastrar uma "
                        f"só, como {formas[0]!r} — a primeira que aparece. Se a "
                        "grafia certa for outra, corrija na planilha antes de subir."
                    ),
                    trava=False,
                    coluna=coluna.nome,
                )
            )
    return propostas


def _avisar_a_pessoa_em_duas_instituicoes(
    propostas: list[Proposta],
) -> list[Proposta]:
    """Avisa que um nome novo aparece em instituições diferentes — SEM travar.

    POR QUE NO UPLOAD E NÃO SÓ NA ABA DE REVISÃO. O alerta na aba de cadastro é o
    pedido do dono do produto, e ele acontece DEPOIS da confirmação. A conferência
    também tem de dizer, antes: ela existe para prometer o que vai acontecer, e
    "vou criar dois cadastros para esta pessoa" é exatamente o que ninguém quer
    descobrir depois.

    ERA UMA RECUSA ATÉ 11/10/2026, levantada na confirmação. Medido na planilha
    real de relações com investidores: 304 linhas, 321 pessoas, e QUATRO em duas
    instituições cada — 300 agendas barradas por 4 nomes. "A mensagem está correta,
    mas não era para impedir subir: era transformar isso em um alerta para revisão
    na aba correspondente de cadastro."

    SÓ O NOME NOVO, e é o que mantém o aviso útil: quem já está no cadastro tem
    uma instituição decidida, e a resolução por linha (`_interlocutor_da_instituicao`)
    já trata o caso dele — com o aviso de que a agenda entra sem a pessoa.

    PELO QUE A LINHA ESCREVEU, e não pelo id resolvido: nesta altura o cadastro
    ainda não existe, então o que há é o texto da célula. É a mesma informação que
    `_instituicao_de_cada_interlocutor` vai usar na confirmação.
    """
    moldes = [
        molde
        for molde, campo in GRUPOS_NUMERADOS["outra_parte"]["colunas"].items()
        if campo == "interlocutor_id"
    ]
    #: nome normalizado -> os nomes de instituição escritos nas linhas dele.
    onde_aparece: dict[str, set[str]] = {}
    a_criar: set[str] = set()
    for proposta in propostas:
        instituicao = proposta.linha.celulas.get("Instituição")
        if not instituicao:
            continue
        for vocabulario, nome in proposta.a_criar:
            if vocabulario == "interlocutores":
                a_criar.add(normalizar(nome))
        for molde in moldes:
            for numero in range(1, INTERLOCUTORES_POR_AGENDA + 1):
                pessoa = proposta.linha.celulas.get(molde.format(n=numero))
                if pessoa:
                    onde_aparece.setdefault(normalizar(str(pessoa)), set()).add(
                        " ".join(str(instituicao).split())
                    )

    em_duas = {
        chave: sorted(instituicoes)
        for chave, instituicoes in onde_aparece.items()
        if chave in a_criar and len(instituicoes) > 1
    }
    if not em_duas:
        return propostas

    for proposta in propostas:
        for molde in moldes:
            for numero in range(1, INTERLOCUTORES_POR_AGENDA + 1):
                coluna = molde.format(n=numero)
                pessoa = proposta.linha.celulas.get(coluna)
                instituicoes = em_duas.get(normalizar(str(pessoa))) if pessoa else None
                if not instituicoes:
                    continue
                proposta.divergencias.append(
                    Divergencia(
                        campo="outra_parte.interlocutor_id",
                        valor=str(pessoa),
                        mensagem=(
                            f"{coluna}: {str(pessoa)!r} aparece em "
                            f"{len(instituicoes)} instituições nesta planilha "
                            f"({', '.join(instituicoes)}). Um interlocutor pertence "
                            "a uma só, então vai nascer um cadastro por "
                            "instituição — os dois ficam marcados para revisão em "
                            "Instituições e Contatos."
                        ),
                        trava=False,
                        coluna=coluna,
                    )
                )
    return propostas


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


def resolver(
    sessao: Session,
    importacao_id,
    *,
    campo: str,
    valor: str,
    decisao: str,
    alvo: str | None = None,
) -> int:
    """Aplica UMA decisão a TODAS as linhas que aquele valor segurava.

    Devolve quantas linhas foram alcançadas. Zero é recusa e não sucesso
    silencioso: um 200 com nada feito faria a tela mostrar "resolvido" para uma
    decisão que não encontrou linha nenhuma, e a pessoa seguiria adiante achando
    que tratou o problema.

    O QUE ACONTECE COM A PROPOSTA. Nada, aqui. A decisão é gravada ao lado do
    valor a que se refere, e é a confirmação (Tarefa 11) que reconstrói as
    entradas — porque ela precisa reconferir tudo contra o banco de qualquer
    forma, já que o cadastro pode ter mudado entre subir e confirmar. Reescrever
    a proposta agora criaria uma segunda verdade para a confirmação desconfiar.
    """
    from app.banco import repositorio_importacao

    if decisao == "descartar":
        pass
    elif decisao not in DECISOES_DE_DIVERGENCIA:
        raise RegraViolada(
            f"Decisão inválida: {decisao!r}. Use "
            f"{', '.join(DECISOES_DE_DIVERGENCIA)} ou 'descartar'."
        )
    elif decisao == "criar":
        # A RESOLUÇÃO NÃO PODE CONTORNAR A REGRA DO UPLOAD. `classificar` recusa
        # valor novo em vocabulário fechado porque mudar a lista de modalidades
        # ou de climas é mudança de REGRA — os KPIs dependem dela —, e isso é
        # código e migration. Sem esta guarda, a tela de conferência oferecia
        # uma porta lateral para a mesma coisa.
        if not pode_criar(campo):
            vocabulario = vocabulario_do_campo(campo)
            if vocabulario in VOCABULARIOS_FECHADOS:
                motivo = (
                    "esta lista é fechada, e mudá-la é mudança de regra, não de "
                    "cadastro"
                )
            elif vocabulario is None:
                # Campo sem vocabulário — uma data ilegível, uma UF inválida.
                # "Criar" não significa nada ali, e aceitar apagaria a pendência
                # para ela voltar como conflito na confirmação.
                motivo = (
                    "este campo não tem cadastro: o valor precisa ser corrigido na "
                    "planilha, ou as linhas descartadas"
                )
            else:
                motivo = (
                    "este cadastro é mantido pela tela de Administração, e não pela "
                    "importação"
                )
            raise RegraViolada(
                f"{valor!r} não pode ser cadastrado por aqui: {motivo}. Aponte para "
                "um valor existente ou descarte as linhas."
            )
        # E NEM O NOME QUE JÁ EXISTE DUAS VEZES. Criar aqui seria a TERCEIRA
        # duplicata do mesmo nome, pela porta que a conferência abre — e a
        # conferência existe para evitar exatamente isso. A tela já não oferece o
        # botão (`pode_criar`), e isto é o controle: esconder o botão é
        # conveniência, e um `curl` basta.
        if e_ambiguo(sessao, campo, valor):
            raise RegraViolada(
                f"{valor!r} já existe em mais de um cadastro: criar faria um terceiro "
                "com o mesmo nome. Escolha qual deles é, ou descarte as linhas."
            )
    elif decisao == "apontar":
        if not alvo:
            raise RegraViolada("Para apontar é preciso dizer para qual cadastro.")
        if not _cadastro_existe(sessao, campo, alvo):
            raise RegraViolada(
                f"O cadastro {alvo!r} não existe. Recarregue a conferência: ele "
                "pode ter sido apagado desde que a tela abriu."
            )

    alcancadas = repositorio_importacao.linhas_com(
        sessao, importacao_id, campo=campo, valor=valor
    )
    if not alcancadas:
        raise RegraViolada(
            f"Nenhuma linha desta importação está pendente por {valor!r} em "
            f"{campo!r}. A conferência pode estar desatualizada — recarregue."
        )

    for linha in alcancadas:
        if decisao == "descartar":
            linha.decisao = "descartada"
            continue
        linha.decisao = "corrigida"
        # Reatribui a lista inteira: o SQLAlchemy não observa mutação DENTRO de
        # um JSONB, e alterar o dicionário no lugar não marcaria a linha como
        # suja — a decisão da pessoa desapareceria no fim da requisição.
        linha.divergencias = [
            (
                {**bruta, "trava": False, "acao": decisao, "alvo": alvo}
                if bruta.get("campo") == campo and bruta.get("valor") == valor
                else bruta
            )
            for bruta in (linha.divergencias or [])
        ]
    sessao.flush()
    return len(alcancadas)


def _cadastro_existe(sessao: Session, campo: str, alvo: str) -> bool:
    """O alvo de um `apontar` existe mesmo?

    Sem esta guarda a decisão gravaria um id que a confirmação não encontra, e o
    erro apareceria lá — longe de quem escolheu, depois de a pessoa já ter
    conferido tudo.

    ATENDE OS DOIS TIPOS DE VOCABULÁRIO. Antes só olhava `NO_BANCO`, e uma
    Modalidade escrita errada não tinha saída: apontar para `presencial` era
    recusado como inexistente, e criar é proibido porque a lista é fechada — a
    pessoa ficava presa numa pendência sem resolução possível.
    """
    vocabulario = vocabulario_do_campo(campo)
    if vocabulario is None:
        return False
    if vocabulario in NO_CODIGO:
        # O alvo É o código. Não há tabela a consultar.
        return alvo in NO_CODIGO[vocabulario]
    fonte = NO_BANCO.get(vocabulario)
    if fonte is None:
        return False
    coluna = getattr(fonte.tabela, fonte.resolve_para)
    convertido = _no_tipo_da_coluna(coluna, alvo)
    if convertido is None:
        # Texto que não cabe no tipo da coluna: `"abc"` num campo UUID ia direto
        # ao Postgres e voltava como erro de banco — 500 e "erro interno" para
        # quem só mandou algo inesperado num campo da API.
        return False
    return (
        sessao.scalar(
            _so_ativos(select(coluna).where(coluna == convertido), fonte.tabela)
        )
        is not None
    )


def _no_tipo_da_coluna(coluna, alvo: str):
    """`alvo` convertido para o tipo da coluna, ou `None` se não couber."""
    import uuid as _uuid

    from sqlalchemy import Integer, SmallInteger
    from sqlalchemy.dialects.postgresql import UUID as _PG_UUID

    tipo = coluna.type
    try:
        if isinstance(tipo, _PG_UUID):
            return _uuid.UUID(str(alvo))
        if isinstance(tipo, (Integer, SmallInteger)):
            return int(alvo)
    except (ValueError, AttributeError, TypeError):
        return None
    return alvo


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que a confirmação fez."""

    criadas: int
    cadastros: int


def _decisoes(linhas) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """O que foi decidido: `(vocabulário, valor) -> criar` e `(campo, valor) -> alvo`."""
    a_criar: dict[tuple[str, str], str] = {}
    #: `(vocabulário, nome NORMALIZADO)` do que já entrou em `a_criar` — é a chave
    #: que o banco usa para a unicidade, e sem ela duas grafias do mesmo nome
    #: viravam duas criações que colidiam.
    ja_vai_nascer: set[tuple[str, str]] = set()
    apontados: dict[tuple[str, str], str] = {}
    for linha in linhas:
        if linha.decisao == "descartada":
            continue
        for bruta in linha.divergencias or []:
            #: UMA FUNÇÃO SÓ RESPONDE "o que vai acontecer" — ver `acao_efetiva`.
            #: Eram quatro lugares lendo `acao` cru, e a revisão achou dois deles
            #: errados depois do conserto do terceiro.
            acao = acao_efetiva(bruta)
            if acao == "criar":
                vocabulario = vocabulario_do_campo(bruta["campo"])
                if vocabulario:
                    #: UMA CRIAÇÃO POR NOME NORMALIZADO, com a PRIMEIRA grafia do
                    #: arquivo como nome.
                    #:
                    #: O 422 QUE ISTO CONSERTA, de uma subida real: "já existe uma
                    #: pessoa chamada 'Renan Tiburcio' nesta instituição" — e ela
                    #: não existia no banco. A colisão era dentro da própria
                    #: planilha, que trazia "Renan Tiburcio" e "Renan Tibúrcio".
                    #: Medido: de 318 nomes, TRÊS vinham com duas grafias, as três
                    #: na mesma instituição, diferindo só no acento.
                    #:
                    #: DUAS ENTRADAS VIRAVAM DUAS CRIAÇÕES, e elas colidem no
                    #: índice único `(nome_normalizado, instituicao_id)`.
                    #:
                    #: E `normalizar` EXISTE PARA ISSO: o docstring dela diz que
                    #: "`nome_normalizado` existe para a importação deduplicar
                    #: 'Radamés' e 'Radames' antes de criar as chaves
                    #: estrangeiras". A deduplicação falhava porque a chave deste
                    #: dicionário era o texto cru.
                    #:
                    #: A PRIMEIRA GRAFIA FICA, e a escolha é por ser estável e
                    #: explicável: ela não depende de a planilha estar ordenada, e
                    #: duas confirmações do mesmo arquivo dão o mesmo cadastro. A
                    #: conferência avisa que havia duas — ver
                    #: `_avisar_as_duas_grafias`.
                    #:
                    #: E O NOME CRU CONTINUA SENDO O VALOR DA CHAVE, para
                    #: `_criar_cadastros` e `_reconferir` receberem um nome de
                    #: verdade e não a forma normalizada.
                    chave = normalizar(str(bruta["valor"]))
                    if (vocabulario, chave) not in ja_vai_nascer:
                        ja_vai_nascer.add((vocabulario, chave))
                        a_criar[(vocabulario, bruta["valor"])] = bruta["campo"]
            elif acao == "apontar" and bruta.get("alvo"):
                apontados[(bruta["campo"], bruta["valor"])] = bruta["alvo"]
    return a_criar, apontados


def _declarados_por_nome(linhas) -> dict[str, dict[str, object]]:
    """Nome normalizado → os campos que a pessoa escreveu na aba de cadastro.

    VEM DA DIVERGÊNCIA E NÃO DO ARQUIVO, porque o arquivo não é guardado: o upload
    anota em `declarado` tudo o que ela preencheu ao marcar `acao="criar"`, e a
    confirmação lê daqui. Era só a categoria de público; passou a ser todos os campos
    quando as abas ganharam os do formulário da plataforma.
    """
    campos: dict[str, dict[str, object]] = {}
    for linha in linhas:
        if linha.decisao == "descartada":
            continue
        for bruta in linha.divergencias or []:
            #: PELA AÇÃO EFETIVA, e aqui estava o defeito: este filtro exigia
            #: `acao == "criar"`, e a criação por PADRÃO não passava. A
            #: instituição nascia — e sem a abrangência e a relevância que a
            #: pessoa escreveu na aba. Perda silenciosa, que é pior que a trava
            #: que isto substituiu, porque a trava ela VÊ. Achado de revisão.
            if acao_efetiva(bruta) != "criar":
                continue
            declarado = _o_declarado_da_divergencia(bruta)
            if declarado:
                campos[normalizar(bruta["valor"])] = declarado
    return campos


def _o_declarado_da_divergencia(bruta: Mapping[str, object]) -> dict[str, object]:
    """O que foi declarado, lendo o campo novo OU o antigo.

    IMPORTAÇÕES CRIADAS ANTES de `categoria_declarada` virar `declarado` estão no banco
    com o campo velho, e a conferência delas continua aberta. Sem ler os dois, a
    confirmação recusa a instituição como "sem categoria" — uma importação que a pessoa
    já conferiu inteira deixa de poder ser confirmada, e sem nenhuma pista do motivo.

    A leitura do campo velho fica NUM LUGAR SÓ, e é o que permite apagá-la quando não
    houver mais nenhuma importação antiga aberta.
    """
    novo = bruta.get("declarado")
    if novo:
        return dict(novo)
    antigo = bruta.get("categoria_declarada")
    return {"categoria_publico_id": antigo} if antigo else {}


def _reconferir(sessao: Session, a_criar, apontados) -> None:
    """A RECONFERÊNCIA — o passo mais delicado da funcionalidade.

    A proposta foi calculada no upload. Entre ele e a confirmação, alguém pode ter
    cadastrado aquela instituição pela tela de Administração, ou desativado uma
    que a planilha usava. Confirmar cego criaria a duplicata que a conferência
    existia para evitar — e duplicata de instituição é o defeito mais caro aqui,
    porque contamina toda leitura que agrupa por órgão.

    Levanta `Conflito` (409) e não `RegraViolada` (422) de propósito: o que a
    pessoa mandou estava certo quando ela olhou. Pedir que ela procure um erro no
    próprio preenchimento seria mandá-la atrás de algo que não existe.
    """
    indice = _indice(sessao)
    for vocabulario, valor in a_criar:
        if normalizar(valor) in indice.get(vocabulario, {}):
            raise Conflito(
                f"{valor!r} já foi cadastrado desde que você subiu a planilha. "
                "Recarregue a conferência: agora é só apontar para o cadastro que "
                "existe, em vez de criar um segundo."
            )
    for (campo, valor), alvo in apontados.items():
        if not _cadastro_existe(sessao, campo, alvo):
            raise Conflito(
                f"O cadastro que você escolheu para {valor!r} não existe mais. "
                "Recarregue a conferência e escolha de novo."
            )


#: "Ela declarou uma instituição, e eu não consigo dizer qual é."
#:
#: TRÊS ESTADOS, E NÃO DOIS, e foi um achado ALTA de revisão. "Não declarou" e
#: "declarou algo que não resolve" davam o mesmo `None`, e `None` autorizava usar
#: a instituição da agenda — então a segunda virava o chute calado que a
#: preferência pela aba existe para fechar.
#:
#: SÓ O PRIMEIRO AUTORIZA O PADRÃO. Quem não declarou nada aceita a inferência de
#: vizinhança de coluna; quem declarou e teve a declaração desfeita por uma
#: mudança no cadastro, não.
NAO_RESOLVE = object()


def _instituicao_declarada(declarado: Mapping[str, object] | None, indice) -> object | None:
    """A instituição que a aba declarou para esta pessoa, resolvida para id.

    `None` quando não há declaração — e só isso autoriza cair na instituição da
    agenda.

    `NAO_RESOLVE` quando ela declarou algo e o cadastro não responde: o nome não
    existe, ou é AMBÍGUO. Devolver a sentinela `AMBIGUO` em si não serve, porque
    ela viraria chave estrangeira e estouraria no `flush` com "can't adapt type
    'object'" — o achado Alto que `escolhidos` já consertou uma vez.
    """
    nome = (declarado or {}).get("instituicao_id")
    if not nome:
        return None
    achada = indice.get("instituicoes", {}).get(normalizar(str(nome)))
    return NAO_RESOLVE if achada is None or achada is AMBIGUO else achada


def _instituicao_de_cada_interlocutor(
    linhas,
    indice,
    escolhidos: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    declarados: Mapping[str, Mapping[str, object]] = MAPPING_VAZIO,
    a_nascer: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Interlocutor novo → a instituição a que ele pertence.

    COM TUDO NUMA ABA, a resposta é vizinha de coluna: o interlocutor e a
    instituição estão na MESMA linha. Antes isto atravessava duas abas ligadas
    pelo `Código`, e era a parte mais frágil da inferência.

    SEM ISTO o interlocutor nasceria solto, e a recusa 4 — participante tem de
    pertencer à instituição da agenda — o rejeitaria NA CONFIRMAÇÃO: o upload
    diria "vou criar", a pessoa conferiria tudo, e o último passo devolveria
    conflito por uma pessoa que ela mesma declarou.

    `escolhidos` VEM PRIMEIRO, e é o achado Alto da revisão. Quando duas
    instituições têm o mesmo nome normalizado, o índice cru devolve `AMBIGUO` —
    um sentinela, não um id — e era ele que ia para a chave estrangeira do
    interlocutor novo, estourando no `flush` com "can't adapt type 'object'". A
    pessoa tinha escolhido qual instituição era, na conferência; a decisão estava
    gravada e só não era consultada aqui.

    E O QUE ELA DECLAROU NA ABA VEM ANTES DA INSTITUIÇÃO DA AGENDA (11/10/2026).
    Declarar "Carla Nova — Câmara Municipal" e usá-la numa agenda do Valor
    Econômico era RECUSADO, e o motivo escrito era este: "criar a pessoa em um dos
    dois órgãos e esperar que dê certo é o tipo de chute que erra calado". Tirada a
    trava, o chute aconteceu — medido: ela nascia na instituição da agenda,
    contrariando em silêncio o que a pessoa escreveu.

    A ORDEM É A DO RESTO DO MÓDULO: decisão explícita antes de inferência. A aba é
    declaração ("quero que exista assim"); a instituição da agenda é vizinhança de
    coluna, que acerta quando ninguém disse nada e erra quando alguém disse.

    E O ESCRITOR CONTINUA SENDO UM SÓ: `_JA_RESOLVIDOS` mantém `instituicao_id`
    fora do que a criação grava a partir do declarado, justamente para as duas
    verdades não discordarem. Quem aprende a declaração é este caminho.

    `a_nascer` É O CONJUNTO DOS QUE VÃO SER CRIADOS, e sem ele a trava voltava
    pela confirmação — achado ALTA de revisão. A varredura lê as células CRUAS da
    linha, não os itens que `_listas_da_linha` manteve: o interlocutor de outra
    instituição, corretamente OMITIDO da agenda, continuava entrando na checagem
    de "a mesma pessoa em agendas de instituições diferentes" e levantava
    `RegraViolada` na confirmação. A tela dizia "a agenda entra sem Ana" e o
    servidor recusava tudo.

    E É O PRÓPRIO PROPÓSITO DA FUNÇÃO: ela responde por interlocutor NOVO. Quem já
    existe no cadastro já tem instituição, e quem foi omitido não vai nascer —
    `de_quem` é lido num lugar só, na criação, exatamente para isso.
    """
    #: NOME -> AS INSTITUIÇÕES EM QUE ELE APARECE, no plural desde 11/10/2026.
    #:
    #: ERA NOME -> UMA INSTITUIÇÃO, e a trava nascia daí: duas instituições para o
    #: mesmo nome não caBIAM na estrutura, então a função levantava `RegraViolada`
    #: — a saída honesta de quem não podia representar o caso.
    #:
    #: E O BANCO SEMPRE REPRESENTOU: a `0002` cria
    #: `unique (nome_normalizado, instituicao_id)` com o comentário "Mesmo nome em
    #: instituições diferentes são pessoas diferentes". Dois cadastros é o que o
    #: modelo prevê; faltava a criação saber fazer dois.
    de_quem: dict[str, list[object]] = {}
    #: Quem declarou instituição que o cadastro não responde mais. Ver `NAO_RESOLVE`.
    nao_resolvidos: set[str] = set()
    moldes = [
        molde
        for molde in GRUPOS_NUMERADOS["outra_parte"]["colunas"]
        if GRUPOS_NUMERADOS["outra_parte"]["colunas"][molde] == "interlocutor_id"
    ]

    for linha in linhas:
        if linha.decisao == "descartada":
            continue
        brutos = linha.dados_brutos or {}
        nome_da_instituicao = brutos.get("Instituição")
        if not nome_da_instituicao:
            continue
        # A DECISÃO DA PESSOA ANTES DO ÍNDICE: `("instituicao_id", nome)` é a
        # mesma chave que a resolução usa, então o nome ambíguo que ela desfez na
        # conferência já vem resolvido aqui.
        instituicao = escolhidos.get(("instituicao_id", str(nome_da_instituicao)))
        if instituicao is None:
            instituicao = indice.get("instituicoes", {}).get(
                normalizar(str(nome_da_instituicao))
            )
        if instituicao is None or instituicao is AMBIGUO:
            # AMBÍGUO SEM DECISÃO não vira chute: a linha está travada e a
            # confirmação já a recusa antes de chegar aqui. O que esta guarda
            # impede é o sentinela virar chave estrangeira se algum caminho
            # futuro chegar sem a decisão.
            continue
        for molde in moldes:
            for numero in range(1, INTERLOCUTORES_POR_AGENDA + 1):
                pessoa = brutos.get(molde.format(n=numero))
                if not pessoa:
                    continue
                chave = normalizar(str(pessoa))
                #: SÓ QUEM VAI NASCER. Ver `a_nascer` no docstring: incluir quem
                #: já existe, ou quem foi omitido da agenda, fazia a checagem
                #: recusar a importação inteira por uma pessoa que ninguém ia
                #: criar.
                if chave not in a_nascer:
                    continue
                #: A ABA ANTES DA AGENDA: o que ela declarou é explícito, a
                #: instituição da linha é inferência.
                da_aba = _instituicao_declarada(declarados.get(chave), indice)
                if da_aba is NAO_RESOLVE:  # noqa: SIM114
                    # O CADASTRO MUDOU ENTRE SUBIR E CONFIRMAR, e este é o
                    # contrato que a confirmação já tem escrito: "quando algo
                    # mudou, a resposta é 409 e não 422 — o que a pessoa mandou
                    # estava certo quando ela olhou".
                    #
                    # O CASO: "Câmara Municipal" era única no upload, e alguém
                    # cadastrou uma segunda pela Administração no meio do
                    # caminho. Cair na instituição da agenda aqui faria a pessoa
                    # NASCER no órgão errado — e, por ter nascido no órgão da
                    # agenda, ela ainda seria vinculada a ela. Achado ALTA de
                    # revisão.
                    nao_resolvidos.add(str(pessoa))
                    continue
                onde = instituicao if da_aba is None else da_aba
                # A MESMA PESSOA NOVA EM AGENDAS DE INSTITUIÇÕES DIFERENTES VIRA
                # DOIS CADASTROS, um por instituição — e não uma recusa.
                #
                # ERA `RegraViolada` ATÉ 11/10/2026, e o dono do produto corrigiu
                # depois de subir a planilha real: "a mensagem está correta, mas
                # não era para impedir subir: era transformar isso em um alerta
                # para revisão na aba correspondente de cadastro". Medido no
                # arquivo dele: 300 agendas barradas por 4 nomes.
                #
                # DOIS CADASTROS É O QUE O MODELO PREVÊ: a `0002` diz "mesmo nome
                # em instituições diferentes são pessoas diferentes", e a
                # unicidade é `(nome_normalizado, instituicao_id)`.
                #
                # E A ORDEM É A DO ARQUIVO, para a lista não remexer entre duas
                # confirmações: quem aparece primeiro nasce primeiro.
                destinos = de_quem.setdefault(chave, [])
                if onde not in destinos:
                    destinos.append(onde)

    if nao_resolvidos:
        # `Conflito` E NÃO `RegraViolada`: o 409 diz "mudou desde que você
        # olhou", e é a resposta honesta — a planilha estava certa, e a
        # conferência também. Reconferir devolve a pendência com a frase que
        # explica o que fazer.
        raise Conflito(
            f"A instituição declarada para {', '.join(sorted(nao_resolvidos))} "
            "deixou de ser identificável no cadastro desde que você conferiu — ela "
            "não existe mais, ou passou a ter homônimo. Confira de novo e escolha."
        )
    return de_quem


#: Os campos que a criação NÃO grava a partir do declarado, porque já são resolvidos
#: por outro caminho — e gravá-los duas vezes deixaria as duas verdades discordarem.
_JA_RESOLVIDOS = frozenset({"nome", "categoria_publico_id", "instituicao_id"})

#: Os campos que guardam `id` de vocabulário: o que a pessoa escreve é o NOME, e o que
#: a coluna aceita é o id.
#:
#: A SUBCATEGORIA NÃO ESTÁ AQUI, e é por um motivo de desenho: o nome dela só é único
#: DENTRO da categoria — "Federal" existe em Poder Executivo, Poder Legislativo e
#: Reguladores. Resolvê-la pelo nome sozinho a marcaria como ambígua e o cadastro
#: nasceria sem ela. Ver `_subcategoria_da_categoria`.
_CAMPOS_DE_ID = {"area_id": "areas_pessoa"}

#: O que "sim" quer dizer numa coluna de sim/não.
_AFIRMATIVOS = frozenset({"sim", "s", "x", "true", "1", "porta voz", "porta-voz"})


def _campos_do_cadastro(
    vocabulario: str, declarado: Mapping[str, object], indice: Mapping
) -> dict[str, object]:
    """O que a pessoa escreveu, traduzido para o que as colunas do banco aceitam.

    LÊ A DESCRIÇÃO DAS COLUNAS, e é o que faz um campo novo chegar ao banco sem
    nenhuma linha nova aqui: acrescentar a coluna em `COLUNAS_DO_CADASTRO` basta.
    Uma lista de campos escrita aqui divergiria da planilha no primeiro campo novo — e
    o sintoma seria o pior possível: a pessoa preenche, não dá erro, e o cadastro nasce
    sem aquilo.

    TRÊS TRADUÇÕES, e cada uma é uma diferença real entre o que se escreve e o que a
    coluna guarda: o NOME de uma subcategoria vira o id dela; "sim" vira booleano; e o
    tier, que é número, vira número.
    """
    campos: dict[str, object] = {}
    for coluna in colunas_do_cadastro(vocabulario):
        if coluna.campo in _JA_RESOLVIDOS or coluna.campo == "subcategoria_publico_id":
            continue
        bruto = declarado.get(coluna.campo)
        if bruto is None or str(bruto).strip() == "":
            continue
        texto = str(bruto).strip()
        if coluna.campo in _CAMPOS_DE_ID:
            achado = indice.get(_CAMPOS_DE_ID[coluna.campo], {}).get(normalizar(texto))
            if achado is not None and achado is not AMBIGUO:
                campos[coluna.campo] = achado
        elif coluna.campo == "eh_porta_voz":
            campos[coluna.campo] = normalizar(texto) in _AFIRMATIVOS
        elif coluna.campo == "tier":
            # O id da relevância É o número do tier, e é o que a coluna guarda.
            achado = indice.get("relevancias", {}).get(normalizar(texto))
            if achado is not None and achado is not AMBIGUO:
                campos[coluna.campo] = achado
            elif texto.isdigit():
                campos[coluna.campo] = int(texto)
        else:
            campos[coluna.campo] = texto
    return campos


def _subcategoria_da_categoria(sessao: Session, categoria, nome: object) -> int | None:
    """O id da subcategoria daquele NOME, dentro daquela categoria.

    DENTRO DA CATEGORIA, e não pelo nome solto: "Federal" existe em Poder Executivo, em
    Poder Legislativo e em Reguladores — a unicidade real é `(categoria, código)`, como
    a própria migration diz. Pelo nome sozinho, as três seriam ambíguas entre si e o
    cadastro nasceria sem subcategoria nenhuma.

    É O MESMO PADRÃO do interlocutor resolvido dentro da instituição da agenda, e pela
    mesma razão: quando o nome não decide, quem decide é o dono.
    """
    if not nome:
        return None
    return _subcategoria_da_categoria_por_id(sessao, categoria.id, str(nome))


#: POR QUE ESTA INSTITUIÇÃO ESPERA REVISÃO: ela entrou sem categoria de público.
#:
#: DECISÃO DO DONO DO PRODUTO (11/10/2026), depois de ver a fila real: "pode
#: registrar como entidade e marcar para revisar". O comportamento era esse; o que
#: faltava era a marca DIZER o que há para fazer.
#:
#: E A DIFERENÇA É O QUE SE VÊ NA ABA. Medido com a planilha real de RI: 499 das
#: 502 pendências caem na aba "Instituições e Contatos", e 178 delas são
#: INSTITUIÇÕES — todas nasceram assim: `3R Investimentos`, `AF Invest`, `ARX`,
#: numa planilha de Relações com Investidores, todas como "Entidade". (Esta linha
#: dizia "499 das 502 pendências SÃO instituições", e estava errada: 499 é o total
#: da aba, que junta duas tabelas.) Sem este texto, a aba mostra 499 linhas
#: repetindo a frase genérica
#: "entrou por planilha e ninguém conferiu", que não diz O QUE conferir. Com ele,
#: cada linha nomeia o campo que falta e o efeito de ele faltar.
#:
#: `entidade` CONTINUA SENDO O TIPO CERTO, e o motivo explica por quê em vez de
#: pedir desculpa: é o único tipo fora de `FRENTE_UNICA_DO_TIPO`, então ele não
#: finge decidir a frente da agenda. Qualquer outro cravaria uma frente errada em
#: toda agenda desta instituição.
MOTIVO_SEM_CATEGORIA = (
    "Entrou pela planilha sem categoria de público, então o tipo ficou "
    "'Entidade' — o único que não crava uma frente. Diga a categoria para a "
    "instituição entrar na taxonomia de públicos do Score."
)


def _criar_cadastros(
    sessao: Session,
    a_criar,
    declarados: Mapping[str, Mapping[str, object]],
    indice: Mapping,
    linhas,
    escolhidos: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
) -> int:
    """Cria os cadastros declarados, no MESMO commit das agendas.

    É por isso que nada nasce no upload: se nascesse, cancelar a conferência
    deixaria instituições criadas sem nenhuma agenda a que servissem — e cancelar
    é caminho normal, não falha.
    """
    from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea

    # A ORDEM IMPORTA: o interlocutor precisa do id da instituição da agenda dele,
    # e essa instituição pode estar sendo criada agora. Instituições primeiro, um
    # `flush`, e só então o resto — com o índice relido para ver as novas.
    def peso(entrada) -> int:
        return 0 if entrada[0][0] == "instituicoes" else 1

    criados = 0
    de_quem: dict[str, object] = {}
    #: UMA FLAG, E NÃO `not de_quem`: a varredura pode devolver vazio por motivo
    #: legítimo — um arquivo que cria só um tema não tem interlocutor novo —, e
    #: `not de_quem` a repetiria a cada cadastro, com um `_indice` inteiro em
    #: cada repetição.
    varrido = False
    #: SÓ OS INTERLOCUTORES QUE VÃO NASCER. Ver `_instituicao_de_cada_interlocutor`:
    #: a varredura lê as células cruas, e sem este recorte ela respondia também por
    #: quem já existe e por quem foi omitido da agenda.
    a_nascer = frozenset(
        normalizar(nome) for vocabulario, nome in a_criar if vocabulario == "interlocutores"
    )
    for (vocabulario, valor), _campo in sorted(a_criar.items(), key=peso):
        if vocabulario != "instituicoes" and not varrido:
            sessao.flush()
            varrido = True
            de_quem = _instituicao_de_cada_interlocutor(
                linhas, _indice(sessao), escolhidos, declarados, a_nascer
            )
        if vocabulario == "instituicoes":
            # O CAMINHO CANÔNICO: a categoria vem da planilha e o TIPO NASCE DELA,
            # exatamente como `api/stakeholders.py` faz — "a tela de cadastro nao
            # pergunta mais o tipo; ausente, ele vem da categoria de publico".
            # Gravar `categoria_publico_id` é o que mantém a instituição importada
            # visível para a taxonomia de públicos do Score; sem ela, ficaria fora
            # de uma área inteira do produto.
            do_cadastro = dict(declarados.get(normalizar(valor)) or {})
            categoria_nome = normalizar(str(do_cadastro.get("categoria_publico_id") or ""))
            categoria = (
                sessao.scalars(
                    select(CategoriaPublico).where(
                        CategoriaPublico.id == indice["categorias_publico"][categoria_nome]
                    )
                ).first()
                if categoria_nome in indice.get("categorias_publico", {})
                else None
            )
            # SEM CATEGORIA, NASCE INCOMPLETA — e não recusada. Era um
            # `RegraViolada` aqui, e isso barrava a linha inteira por uma coluna
            # da OUTRA aba. Mudança pedida pelo dono do produto (11/10/2026).
            #
            # O QUE SE PERDE, e está dito em voz alta porque é real: a categoria
            # de público é o que torna a instituição visível para a taxonomia de
            # públicos do Score, e é dela que sai o `tipo`. Sem ela, esta
            # instituição fica fora dessa taxonomia até alguém completá-la.
            #
            # `entidade` É O TIPO HONESTO para "ainda não se sabe": é o único que
            # não está em `FRENTE_UNICA_DO_TIPO`, então ele não finge decidir a
            # frente — `derivar_frente` cai no formato da interação e, sem ele,
            # em `PARCEIROS`. Qualquer outro tipo cravaria uma frente errada em
            # toda agenda desta instituição, que é pior que uma frente genérica.
            #
            # E NÃO É ESTADO NOVO NO BANCO: 205 das 3.809 instituições já estão
            # sem categoria hoje. O alerta na agenda é o que torna isso visível.
            tipo = (
                TIPO_DA_CATEGORIA_DE_PUBLICO[categoria.codigo]
                if categoria is not None
                else TIPO_SEM_CATEGORIA
            )
            # A ABRANGÊNCIA VEM DA PLANILHA e não é a UF da agenda: o dono do
            # produto foi explícito, são coisas diferentes. Uma reunião em Brasília
            # com um órgão de Minas tem UF da agenda `DF` e abrangência do órgão
            # `MG`. Antes disto a instituição nascia com `NA` fixo, e alguém
            # precisava completar na Administração depois — e "depois" é quando
            # ninguém lembra.
            # PELO `gravar`, e não `sessao.add` pelado: sem ele, declarar um
            # nome+tipo que já existe DESATIVADO sai como 500 — o índice
            # único (nome_normalizado, tipo) da 0002 não é parcial em
            # `ativo`, e `_indice`/`_so_ativos` só enxergam o que está ativo,
            # então a divergência nunca aparece antes do `INSERT` bater na
            # colisão. Mesmo defeito que `api/stakeholders.py` já evita nas
            # mesmas três tabelas.
            gravar(
                sessao,
                Instituicao(
                    nome=valor,
                    nome_normalizado=normalizar(valor),
                    tipo=tipo,
                    categoria_publico_id=categoria.id if categoria is not None else None,
                    subcategoria_publico_id=(
                        _subcategoria_da_categoria(
                            sessao, categoria, do_cadastro.get("subcategoria_publico_id")
                        )
                        if categoria is not None
                        else None
                    ),
                    **_campos_do_cadastro("instituicoes", do_cadastro, indice),
                    #: NASCE PENDENTE DE REVISÃO — ver a coluna em
                    #: `tabelas_stakeholders`. A planilha entra sem barreira, e o
                    #: enquadramento fica para quem revisa: "o profissional
                    #: consegue subir a planilha sem problemas e pode revisar
                    #: depois, e inclusive pode ser trabalho de outra pessoa".
                    pendente_de_revisao=True,
                    motivo_da_revisao=(
                        MOTIVO_SEM_CATEGORIA if categoria is None else None
                    ),
                ),
                novo=True,
                ao_colidir=(
                    f"Já existe uma instituição chamada {valor!r} deste mesmo "
                    "tipo — pode estar desativada. Reative-a pela Administração "
                    "em vez de declarar de novo na planilha."
                ),
            )
        elif vocabulario == "interlocutores":
            do_cadastro = dict(declarados.get(normalizar(valor)) or {})
            #: UM CADASTRO POR INSTITUIÇÃO EM QUE O NOME APARECE.
            #:
            #: ERA UM SÓ, e duas instituições para o mesmo nome levantavam
            #: `RegraViolada` na confirmação — 300 agendas da planilha real de RI
            #: barradas por 4 nomes. O dono do produto corrigiu a regra:
            #: "transformar isso em um alerta para revisão na aba correspondente de
            #: cadastro".
            #:
            #: E É O QUE O MODELO PREVÊ: a `0002` diz "mesmo nome em instituições
            #: diferentes são pessoas diferentes", com unicidade em
            #: `(nome_normalizado, instituicao_id)`. Dois cadastros não colidem.
            #:
            #: A LISTA VAZIA CRIA UM SEM INSTITUIÇÃO, que é o comportamento de
            #: antes para o nome que apareceu sem instituição na linha.
            destinos = de_quem.get(normalizar(valor)) or [None]
            #: O MOTIVO, SÓ QUANDO HÁ MAIS DE UM, e é o alerta que a aba mostra:
            #: sem ele a pessoa abre a fila e vê dois cadastros iguais sem saber
            #: por que estão lá.
            motivo = (
                f"Apareceu em {len(destinos)} instituições na mesma planilha — "
                "confirme se são a mesma pessoa, se ela mudou de casa, ou se são "
                "homônimas."
                if len(destinos) > 1
                else None
            )
            for destino in destinos:
                gravar(
                    sessao,
                    Interlocutor(
                        nome=valor,
                        nome_normalizado=normalizar(valor),
                        # A INSTITUIÇÃO CONTINUA VINDO DA INFERÊNCIA e não do
                        # declarado: ela já resolve o nome para o id, respeitando a
                        # decisão que a pessoa tomou na conferência quando o nome
                        # era ambíguo.
                        instituicao_id=destino,
                        **_campos_do_cadastro("interlocutores", do_cadastro, indice),
                        pendente_de_revisao=True,
                        motivo_da_revisao=motivo,
                    ),
                    novo=True,
                    ao_colidir=(
                        f"Já existe uma pessoa chamada {valor!r} nesta instituição — "
                        "pode estar desativada. Reative-a pela Administração em vez de "
                        "declarar de novo na planilha."
                    ),
                )
                criados += 1
            #: `continue`: ESTA É A ÚNICA RAMIFICAÇÃO QUE CRIA MAIS DE UMA LINHA.
            #:
            #: O `criados += 1` no fim do laço conta UMA criação por nome, e era
            #: verdade até 11/10/2026, quando um nome em duas instituições passou a
            #: nascer duas vezes. Achado de revisão do Codex: a confirmação da
            #: planilha real de RI respondeu `cadastros: 505` tendo inserido 509 —
            #: os 4 nomes em duas casas contavam 4 em vez de 8.
            #:
            #: E ESSE NÚMERO É O QUE A PESSOA LÊ na tela depois de subir a planilha.
            #: Um resumo que subconta é pior que resumo nenhum: ele convida a
            #: conferir o que já está certo.
            continue
        elif vocabulario == "pessoas_aegea":
            do_cadastro = dict(declarados.get(normalizar(valor)) or {})
            gravar(
                sessao,
                PessoaAegea(
                    nome=valor,
                    nome_normalizado=normalizar(valor),
                    **_campos_do_cadastro("pessoas_aegea", do_cadastro, indice),
                    pendente_de_revisao=True,
                ),
                novo=True,
                ao_colidir=(
                    f"Já existe uma pessoa da Aegea chamada {valor!r} — pode "
                    "estar desativada. Reative-a pela Administração em vez de "
                    "declarar de novo na planilha."
                ),
            )
        elif vocabulario == "temas":
            from app.banco.tabelas_catalogo import Tema

            # `livre` e não `estrategico`: tema estratégico é vocabulário fechado
            # do modelo, e a planilha não o amplia.
            gravar(
                sessao,
                #: `gerais`, E NAO `livre`: `livre` não é um nível. A
                #: constraint `tema_nivel_check` e `NIVEIS_DE_TEMA` aceitam
                #: `sensivel`, `estrategico` e `gerais` — confirmar uma
                #: importação com tema novo devolvia CheckViolation, 500.
                #:
                #: NUNCA APARECEU porque era preciso declarar o tema na aba para
                #: chegar aqui, e nenhum teste fazia isso de ponta a ponta. O
                #: caminho ficou alcançável quando a importação parou de exigir a
                #: aba (11/10/2026) — a mudança não criou o defeito, tirou-o do
                #: esconderijo.
                #:
                #: E `gerais` É O NEUTRO: `estrategico` é vocabulário fechado do
                #: modelo (os KPIs dependem dele, e a planilha não o amplia), e
                #: `sensivel` seria uma afirmação sobre o tema que a planilha não
                #: tem como fazer.
                Tema(nome=valor, nivel="gerais", pendente_de_revisao=True),
                novo=True,
                ao_colidir=(
                    f"Já existe um tema chamado {valor!r} — pode estar "
                    "desativado. Reative-o pela Administração em vez de "
                    "declarar de novo na planilha."
                ),
            )
        else:  # pragma: no cover - `classificar` já não deixa chegar aqui
            raise RegraViolada(
                f"Não sei criar um cadastro em {vocabulario!r} pela importação. "
                "Cadastre-o pela tela de Administração e aponte para ele."
            )
        criados += 1
    if criados:
        sessao.flush()
    return criados


def _linhas_para_reler(linhas) -> dict[str, list[LinhaBruta]]:
    """As linhas gravadas, de volta ao formato que a resolução entende.

    A CONFIRMAÇÃO NÃO TEM O ARQUIVO — ele não é guardado. Tem `dados_brutos`, que
    é exatamente o que o leitor produziu, e é dele que a resolução roda de novo.
    A data volta a `date` porque o JSONB a guardou como texto ISO.
    """
    from app.casos_de_uso.ler_planilha_de_agendas import data_de_celula

    por_aba: dict[str, list[LinhaBruta]] = {aba.nome: [] for aba in FORMATO}
    # PELO NÚMERO DA LINHA NO ARQUIVO, e não mais por um `Código` que a pessoa
    # inventava: é o mesmo número que a conferência mostra e por onde ela volta à
    # planilha para conferir. O `Código` existia para ligar as abas filhas, que já
    # não existem.
    descartados: set[int] = {
        linha.linha_origem
        for linha in linhas
        if linha.aba == ABA_PRINCIPAL and linha.decisao == "descartada"
    }
    for linha in linhas:
        if linha.aba not in por_aba:
            continue
        celulas = dict(linha.dados_brutos or {})
        if linha.linha_origem in descartados:
            continue
        for aba in FORMATO:
            if aba.nome != linha.aba:
                continue
            for coluna in aba.colunas:
                if coluna.campo == "data_interacao" and coluna.nome in celulas:
                    celulas[coluna.nome] = data_de_celula(celulas[coluna.nome])
        por_aba[linha.aba].append(
            LinhaBruta(aba=linha.aba, numero=linha.linha_origem, celulas=celulas)
        )
    return por_aba


def corrigir_linha(
    sessao: Session,
    importacao_id,
    linha_id: int,
    celulas: Mapping[str, object] = MAPPING_VAZIO,
    descartada: bool | None = None,
) -> None:
    """Preenche células de UMA linha e repropõe só ela.

    O QUE ISTO RESOLVE. A conferência sabia resolver o valor ERRADO — "este órgão
    não existe, aponte ou crie" — e não sabia resolver o valor AUSENTE. A linha sem
    data gerava um grupo sem valor nenhum: nada para apontar, nada para criar. As
    saídas eram corrigir a planilha e subir tudo de novo, ou descartar a linha.

    A REPROPOSIÇÃO É A MESMA MÁQUINA, `propor_de_linhas` — a mesma que o upload e a
    confirmação usam. Uma segunda implementação aqui divergiria das outras duas no
    primeiro campo que ganhasse regra nova, e a linha corrigida passaria a valer por
    critério diferente do das vizinhas.

    A CÉLULA CORRIGIDA FICA MARCADA, e é a contrapartida honesta de editar aqui: o
    registro passa a divergir da planilha que a pessoa guardou. Sem a marca, ela
    abriria o arquivo meses depois para entender uma agenda e encontraria a célula
    vazia — sem nada explicando de onde veio o valor.
    """
    from app.banco import repositorio_importacao

    importacao = repositorio_importacao.obter(sessao, importacao_id)
    if importacao.situacao != "aguardando_conferencia":
        raise RegraViolada(
            f"Esta importação está {importacao.situacao!r}: as linhas dela já não "
            "podem ser editadas. Depois de confirmada, a linha virou agenda, e é a "
            "agenda que se edita."
        )

    if descartada is not None and celulas:
        # AS DUAS COISAS JUNTAS SÃO CONTRADITÓRIAS: preencher uma célula de uma linha
        # que não vai entrar. Escolher uma das duas em silêncio deixaria a pessoa com
        # a impressão de ter feito as duas.
        raise RegraViolada(
            "Ou preencha células desta linha, ou exclua a linha — não as duas coisas "
            "na mesma ação."
        )

    conhecidas = {coluna.nome for coluna in aba_de(ABA_PRINCIPAL).colunas}
    desconhecidas = sorted(set(celulas) - conhecidas)
    if desconhecidas:
        # SEM ISTO A GRAVAÇÃO SERIA MUDA: a chave errada entraria em
        # `dados_brutos`, ninguém a leria, e a pessoa veria a pendência continuar
        # depois de clicar em salvar, sem nenhuma pista do motivo.
        raise RegraViolada(
            f"A planilha não tem a coluna {', '.join(repr(c) for c in desconhecidas)}."
        )

    linhas = repositorio_importacao.linhas_de(sessao, importacao_id)
    alvo = next((linha for linha in linhas if linha.id == linha_id), None)
    if alvo is None or alvo.aba != ABA_PRINCIPAL:
        raise RegraViolada("Esta linha não é desta importação.")

    if descartada is not None:
        # EXCLUIR É REVERSÍVEL ATÉ A CONFIRMAÇÃO, e precisa ser: excluir por engano
        # numa tela de 54 linhas é fácil, e a planilha não é o caminho de volta —
        # o arquivo não fica guardado. A linha continua na grade, marcada.
        alvo.decisao = "descartada" if descartada else "pendente"
        sessao.flush()
        # SÓ A RESTAURADA É REPROPOSTA. A excluída não tem o que propor — e a
        # releitura a PULA de propósito, o que fazia esta chamada estourar em
        # "not enough values to unpack" quando eu tentei repropor as duas.
        #
        # A proposta antiga dela fica gravada e não faz mal: `confirmar`,
        # `_grupos` e a contagem de pendências todos ignoram linha descartada, e
        # guardá-la é o que permite restaurar sem reler o arquivo — que não existe
        # mais.
        if not descartada:
            _repropor_uma(sessao, importacao_id, alvo)
        return

    brutos = dict(alvo.dados_brutos or {})
    corrigido = dict(brutos.get(CHAVE_DO_CORRIGIDO) or {})
    herdado = dict(brutos.get(CHAVE_DO_HERDADO) or {})
    for coluna, valor in celulas.items():
        brutos[coluna] = valor
        corrigido[coluna] = valor
        # A CÉLULA EDITADA DEIXA DE SER HERDADA: a pessoa acabou de dizer o que vale
        # ali, e continuar mostrando "herdado da linha de cima" contaria uma
        # história que deixou de ser verdade.
        herdado.pop(coluna, None)
    brutos[CHAVE_DO_CORRIGIDO] = corrigido
    brutos[CHAVE_DO_HERDADO] = herdado
    alvo.dados_brutos = brutos
    sessao.flush()

    _repropor_uma(sessao, importacao_id, alvo)


def _declaracoes_da_importacao(
    sessao: Session, importacao_id, linhas
) -> tuple[dict[str, frozenset[str]], dict[str, dict[str, dict[str, object]]]]:
    """O que a pessoa declarou no arquivo, para repropor uma linha depois do upload.

    DUAS FONTES, E A ORDEM IMPORTA. A primeira é a linha reservada que o upload gravou
    (`ABA_DAS_DECLARACOES`): ela tem a declaração INTEIRA, inclusive a que nenhuma linha
    usou — foi o achado da revisão, e o caso era a pessoa declarar um órgão, não usá-lo
    em nenhuma linha, e passar a usá-lo corrigindo uma célula na conferência.

    A SEGUNDA É AS DIVERGÊNCIAS GRAVADAS, e ela existe para as importações ANTIGAS: as
    que foram criadas antes de a linha reservada existir continuam abertas para
    conferência, e para elas a reconstrução parcial é tudo o que há. Some quando não
    houver mais nenhuma conferência antiga aberta.

    UNIÃO E NÃO ESCOLHA: as duas descrevem o mesmo arquivo, e o que a linha reservada
    tem a mais é justamente o que a reconstrução não alcança. Onde as duas têm o mesmo
    nome, a gravada manda — ela é o que a pessoa escreveu, não o que foi inferido.
    """
    from app.banco import repositorio_importacao

    nomes, campos = repositorio_importacao.declaracoes_de(sessao, importacao_id)
    nomes_reconstruidos, campos_reconstruidos = _declaracoes_gravadas(linhas)

    juntos_nomes = {
        chave: nomes.get(chave, frozenset()) | nomes_reconstruidos.get(chave, frozenset())
        for chave in set(nomes) | set(nomes_reconstruidos)
    }
    juntos_campos: dict[str, dict[str, dict[str, object]]] = {}
    for chave in set(campos) | set(campos_reconstruidos):
        juntos_campos[chave] = {
            **dict(campos_reconstruidos.get(chave, {})),
            **dict(campos.get(chave, {})),
        }
    return juntos_nomes, juntos_campos


def _declaracoes_gravadas(
    linhas,
) -> tuple[dict[str, frozenset[str]], dict[str, dict[str, dict[str, object]]]]:
    """O que foi declarado nas abas, reconstruído das divergências gravadas.

    O ARQUIVO NÃO É GUARDADO, então tudo o que sobra da declaração é o que o upload
    anotou na divergência: o nome, o vocabulário (pelo campo) e os outros campos da aba.
    Isto devolve as duas formas que a resolução espera — o conjunto de nomes declarados,
    que `classificar` usa, e o mapa de campos por nome, que a criação usa.
    """
    nomes: dict[str, set[str]] = {}
    campos: dict[str, dict[str, dict[str, object]]] = {}
    for linha in linhas:
        if linha.decisao == "descartada":
            continue
        for bruta in linha.divergencias or []:
            #: Mesma razão de `_declarados_por_nome`: o que vale é a ação
            #: efetiva, não só a que a pessoa clicou.
            if acao_efetiva(bruta) != "criar":
                continue
            vocabulario = vocabulario_do_campo(bruta.get("campo") or "")
            if not vocabulario:
                continue
            chave = normalizar(bruta["valor"])
            nomes.setdefault(vocabulario, set()).add(chave)
            declarado = _o_declarado_da_divergencia(bruta)
            if declarado:
                campos.setdefault(vocabulario, {})[chave] = declarado
    return {chave: frozenset(valores) for chave, valores in nomes.items()}, campos


def _repropor_uma(sessao: Session, importacao_id, alvo) -> None:
    """Recalcula a proposta de UMA linha e regrava proposta e divergências.

    SÓ ELA, e não a importação inteira: repropor tudo apagaria as decisões que a
    pessoa já tomou nas outras linhas — o `acao="criar"` que veio da declaração na
    aba, e cada `apontar` que ela escolheu.
    """
    from app.banco import repositorio_importacao

    linhas = repositorio_importacao.linhas_de(sessao, importacao_id)
    _, apontados = _decisoes(linhas)
    escolhidos: dict[tuple[str, str], object] = {}
    for (campo, valor), destino in apontados.items():
        vocabulario = vocabulario_do_campo(campo)
        fonte = NO_BANCO.get(vocabulario or "")
        if fonte is None:
            escolhidos[(campo, valor)] = destino
        else:
            coluna = getattr(fonte.tabela, fonte.resolve_para)
            escolhidos[(campo, valor)] = _no_tipo_da_coluna(coluna, destino)

    # A DECLARAÇÃO VEM DA PRÓPRIA DIVERGÊNCIA GRAVADA, e era o achado crítico da
    # revisão: a pessoa declarava a instituição, o upload prometia criá-la, ela corrigia
    # QUALQUER célula daquela linha na grade — e a promessa desaparecia, virando pendência
    # travada.
    #
    # A CAUSA: a reproposição não tem o arquivo, então não tinha como saber o que foi
    # declarado. Mas tem a divergência, que já carrega a declaração inteira — era só ler
    # de lá. O mesmo vale para os NOMES declarados, que `classificar` usa para separar
    # "quero cadastrar isto" de "errei a grafia".
    declarados, cadastros = _declaracoes_da_importacao(sessao, importacao_id, linhas)
    (proposta,) = propor_de_linhas(
        sessao,
        _linhas_para_reler([alvo]),
        declarados,
        escolhidos,
        cadastros_declarados=cadastros,
    )
    repositorio_importacao.gravar_proposta(sessao, alvo, proposta)


def confirmar(sessao: Session, importacao_id, usuario) -> Resumo:
    """Cria os cadastros e as agendas — tudo, ou nada.

    UMA TRANSAÇÃO SÓ, e o commit acontece no teardown da dependência da rota (ver
    `app/banco/sessao.py`). Não há `sessao.commit()` aqui de propósito: um commit
    no meio criaria o estado que esta função existe para impedir, o de instituições
    criadas e agendas não.
    """
    from app.banco import repositorio_importacao
    from app.banco.repositorio_interacoes import RepositorioSQL
    from app.casos_de_uso import registrar_interacao
    from app.casos_de_uso.consulta_recebida import validar_consulta
    from app.casos_de_uso.derivar_esfera import derivar_esfera
    from app.casos_de_uso.derivar_frente import derivar_frente

    importacao = repositorio_importacao.obter(sessao, importacao_id)
    if importacao.situacao != "aguardando_conferencia":
        raise RegraViolada(
            f"Esta importação está {importacao.situacao!r} e não pode ser "
            "confirmada. Só uma importação aguardando conferência pode."
        )

    linhas = repositorio_importacao.linhas_de(sessao, importacao_id)
    presas = [
        linha
        for linha in linhas
        if linha.aba == ABA_PRINCIPAL
        and linha.decisao != "descartada"
        and any(bruta.get("trava") for bruta in (linha.divergencias or []))
    ]
    if presas:
        raise RegraViolada(
            f"{len(presas)} linha(s) ainda seguram a confirmação. Resolva as "
            "pendências da conferência antes de confirmar."
        )

    a_criar, apontados = _decisoes(linhas)
    _reconferir(sessao, a_criar, apontados)

    # Os apontamentos convertidos para o tipo da coluna, uma vez: a resolução os
    # consulta por linha, e converter lá dentro repetiria o trabalho.
    #
    # ANTES DE CRIAR OS CADASTROS, e não depois: a criação do interlocutor novo
    # precisa saber de qual instituição ele é, e quando o nome da instituição é
    # ambíguo é SÓ a decisão da pessoa que responde isso. Calcular depois foi o
    # achado Alto da revisão — ver `_instituicao_de_cada_interlocutor`.
    escolhidos: dict[tuple[str, str], object] = {}
    for (campo, valor), alvo in apontados.items():
        vocabulario = vocabulario_do_campo(campo)
        fonte = NO_BANCO.get(vocabulario or "")
        if fonte is None:
            escolhidos[(campo, valor)] = alvo
        else:
            coluna = getattr(fonte.tabela, fonte.resolve_para)
            escolhidos[(campo, valor)] = _no_tipo_da_coluna(coluna, alvo)

    cadastros = _criar_cadastros(
        sessao, a_criar, _declarados_por_nome(linhas), _indice(sessao), linhas, escolhidos
    )

    # A RESOLUÇÃO RODA DE NOVO, contra o banco com os cadastros já criados. É a
    # mesma máquina do upload — `propor_de_linhas` —, e não uma segunda
    # implementação que poderia divergir dela.
    propostas = propor_de_linhas(
        sessao, _linhas_para_reler(linhas), {}, escolhidos
    )

    por_linha_de_origem = {
        linha.linha_origem: linha for linha in linhas if linha.aba == ABA_PRINCIPAL
    }
    repositorio = RepositorioSQL(sessao)
    criadas = 0
    for proposta in propostas:
        if proposta.entrada is None:
            raise Conflito(
                f"A linha {proposta.linha.numero} deixou de ser resolvível desde a "
                "conferência: "
                + "; ".join(d.mensagem for d in proposta.divergencias if d.trava)
            )
        entrada = proposta.entrada
        frente = entrada.frente or derivar_frente(
            sessao,
            instituicao_id=entrada.instituicao_id,
            formato_interacao_id=entrada.formato_interacao_id,
        )
        esfera_id = entrada.esfera_id or derivar_esfera(
            sessao, instituicao_id=entrada.instituicao_id
        )
        interacao = entrada.para_dominio(frente=frente, esfera_id=esfera_id)
        # A PROCEDÊNCIA, e é o que permite responder "de onde veio este registro"
        # e reprocessar quando a regra de leitura mudar.
        interacao.fonte = "importacao_planilha"
        interacao.origem_aba = proposta.linha.aba
        interacao.origem_linha = proposta.linha.numero
        validar_consulta(sessao, interacao)
        criada = registrar_interacao.registrar(
            repositorio, interacao=interacao, usuario=usuario
        )
        gravada = por_linha_de_origem.get(proposta.linha.numero)
        if gravada is not None:
            gravada.interacao_id = criada.id
            gravada.decisao = "aceita" if gravada.decisao == "pendente" else gravada.decisao
        criadas += 1

    importacao.situacao = "confirmada"
    importacao.confirmado_em = datetime.now(UTC)
    sessao.flush()
    return Resumo(criadas=criadas, cadastros=cadastros)


def cancelar(sessao: Session, importacao_id) -> None:
    """Desiste da importação, sem apagar o que a pessoa preencheu.

    O bruto fica: ela pode querer entender o que deu errado, e é a única cópia
    daquilo no sistema. E nenhum cadastro precisa ser desfeito, porque nenhum foi
    criado — é o que `_criar_cadastros` deixa dito.
    """
    from app.banco import repositorio_importacao

    importacao = repositorio_importacao.obter(sessao, importacao_id)
    if importacao.situacao == "confirmada":
        raise RegraViolada("Esta importação já foi confirmada e não pode ser cancelada.")
    importacao.situacao = "cancelada"
    sessao.flush()


def pode_criar(campo: str) -> bool:
    """A importação sabe criar cadastro para este campo?

    A TELA PERGUNTA ISTO para não oferecer um botão que o servidor recusa. Antes
    ela mostrava "Cadastrar como novo" em todo grupo, e um dicionário administrado
    saía da pendência como `criar` para falhar só na confirmação — depois de a
    pessoa ter conferido tudo.
    """
    vocabulario = vocabulario_do_campo(campo)
    return vocabulario in VOCABULARIOS_QUE_A_IMPORTACAO_CRIA


def candidatos_do_nome(sessao: Session, campo: str, nome: str) -> list[tuple[str, str]]:
    """`(alvo, rótulo)` de cada cadastro ATIVO com este nome — para o nome ambíguo.

    O QUE ISTO CONSERTA. `AMBIGUO` marca o nome que casa com mais de um cadastro,
    e a divergência dele manda "escolha qual na conferência". A conferência não
    tinha como oferecer a escolha: `agrupar` compara TEXTO e achata os dois
    cadastros num item só, e `_alvo_de` devolvia `str(AMBIGUO)` — o repr da
    sentinela — como se fosse id. O botão existia e mandava lixo.

    ENTÃO A ESCOLHA VEM DAQUI, de quem conhece a tabela: um item por cadastro, com
    o id de verdade e um rótulo que os distingue. Sem isto a única saída da pessoa
    era descartar a linha ou renomear na planilha.

    SÓ OS ATIVOS, pela mesma razão que `_indice` filtra: oferecer um cadastro
    aposentado é convidar a apontar para o que a confirmação recusa.

    DOIS VOCABULÁRIOS, e não todos, porque rótulo que não distingue é pior que
    nenhum — devolveria dois botões idênticos outra vez:

    * `instituicoes` se distingue pelo TIPO. Medido: 28 nomes duplicados, sendo
      22 do par `perfil_rede` + `veiculo`.
    * `interlocutores` se distingue pela INSTITUIÇÃO, que é a unicidade da tabela
      (`nome_normalizado`, `instituicao_id`). Medido: hoje não existe nenhum
      homônimo — 129 interlocutores, nenhum nome repetido. O caminho fica porque
      o banco o permite, e `_orgaos_de_cada_interlocutor` já existe para a
      mensagem desse mesmo caso.

    Para os outros vocabulários, devolve vazio: dois temas ativos com o mesmo nome
    são defeito de base, e não há atributo que a pessoa reconheça para escolher
    entre eles.
    """
    vocabulario = vocabulario_do_campo(campo)
    chave = normalizar(nome)
    if vocabulario == "instituicoes":
        linhas = sessao.execute(
            _so_ativos(
                select(Instituicao.id, Instituicao.nome, Instituicao.tipo).where(
                    Instituicao.nome_normalizado == chave
                ),
                Instituicao,
            )
        ).all()
        return [
            (str(ident), f"{nome_do_cadastro} ({_rotulo_do_tipo(tipo)})")
            for ident, nome_do_cadastro, tipo in linhas
        ]
    if vocabulario == "interlocutores":
        linhas = sessao.execute(
            _so_ativos(
                select(Interlocutor.id, Interlocutor.nome, Instituicao.nome)
                .join(Instituicao, Interlocutor.instituicao_id == Instituicao.id)
                .where(Interlocutor.nome_normalizado == chave),
                Interlocutor,
            ).where(Instituicao.ativo.is_(True))
        ).all()
        return [
            (str(ident), f"{pessoa} ({orgao})") for ident, pessoa, orgao in linhas
        ]
    return []


def e_ambiguo(
    sessao: Session,
    campo: str,
    valor: str,
    indice: dict[str, dict[str, object]] | None = None,
) -> bool:
    """Este valor casa com MAIS DE UM cadastro?

    QUEM PERGUNTA, E POR QUÊ. A conferência oferece "Cadastrar como novo" em todo
    grupo de campo que a importação sabe criar. Num nome AMBÍGUO isso é um atalho
    explícito para a TERCEIRA duplicata do mesmo nome — achado de revisão
    (11/10/2026) —, e é o contrário do que o dono do produto pediu: "caso tenha
    suspeita de duplicação em qualquer campo, mostrar para o usuário decidir". A
    decisão coerente ali é escolher um dos dois que já existem.

    SÓ A AMBIGUIDADE, e não "o nome existe no índice". A diferença importa: o
    interlocutor que existe sob OUTRA instituição também está no índice, e ali
    criar é legítimo — duas "Ana Prado" em instituições diferentes são dois
    cadastros legítimos, e a `0002` diz isso com todas as letras.
    """
    vocabulario = vocabulario_do_campo(campo)
    if vocabulario is None:
        return False
    #: O ÍNDICE DE QUEM CHAMA, QUANDO ELE TEM UM. Quem pergunta uma vez só —
    #: `resolver`, numa decisão da pessoa — não precisa calculá-lo antes; quem
    #: pergunta por grupo precisa, e medido: reconstruí-lo por grupo levou a
    #: resposta da conferência de 19 consultas fixas para 499 em 30 grupos.
    conhecidos = (
        indice_do_vocabulario(sessao, vocabulario)
        if indice is None
        else indice.get(vocabulario, {})
    )
    return conhecidos.get(normalizar(valor)) is AMBIGUO


def _rotulo_do_tipo(tipo: str) -> str:
    """O nome que a pessoa lê, ou o código cru se alguém criou um tipo sem rótulo.

    NÃO ESTOURA por falta de rótulo: a escolha entre dois cadastros é mais
    importante que a beleza do rótulo, e um 500 aqui tiraria da pessoa a única
    saída da ambiguidade. O teste que prende "todo tipo tem rótulo" é quem avisa.
    """
    return ROTULO_DO_TIPO_DE_INSTITUICAO.get(tipo, tipo)


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
        if coluna.campo and coluna.vocabulario and coluna.campo not in GRUPOS_NUMERADOS
    },
    # Os campos das listas vêm prefixados — `outra_parte.interlocutor_id` — e o
    # vocabulário deles sai da PRIMEIRA coluna de cada grupo numerado: os quatro
    # `Interlocutor {n}` apontam para o mesmo vocabulário, então basta uma.
    **{
        f"{campo_da_lista}.{campo}": vocabulario
        for campo_da_lista, grupo in GRUPOS_NUMERADOS.items()
        for molde, campo in grupo["colunas"].items()
        for vocabulario in [
            {
                coluna.nome: coluna.vocabulario
                for coluna in aba_de(ABA_PRINCIPAL).colunas
            }.get(molde.format(n=1))
        ]
        if vocabulario
    },
}


def colunas_numeradas_sem_grupo() -> Sequence[str]:
    """As colunas numeradas de `FORMATO` que nenhum grupo mapeia.

    PÚBLICA porque é um teste que a usa. Sem ela, uma coluna numerada nova
    apareceria no modelo, a pessoa a preencheria, e o valor não chegaria a lugar
    nenhum: sem erro no Excel, sem erro no servidor, sem nada.
    """
    mapeadas = {
        molde.format(n=numero)
        for grupo in GRUPOS_NUMERADOS.values()
        for molde in grupo["colunas"]
        for numero in range(1, grupo["quantos"] + 1)
    }
    numeradas = {
        coluna.nome
        for coluna in aba_de(ABA_PRINCIPAL).colunas
        if coluna.campo in GRUPOS_NUMERADOS
    }
    return sorted(numeradas - mapeadas)




def _texto_da_celula(bruto: object) -> str:
    """O que a pessoa escreveu na célula, para a mensagem citar de volta.

    Sem normalizar e sem resolver para id: a divergência tem de dizer o valor que
    ela reconhece na planilha, não o que o sistema entendeu dele.
    """
    return "" if bruto is None else str(bruto).strip()


def _primeira_coluna_com(
    linha: object, colunas: Sequence[Coluna], campo: str, bruto: object
) -> str:
    """Qual coluna do mesmo campo já trouxe este valor.

    "O tema está repetido" manda procurar entre 18 colunas; "já está em Tema 3"
    manda apagar uma célula. É a mesma régua das outras divergências deste
    módulo, que nomeiam a coluna e o valor.
    """
    procurado = _texto_da_celula(bruto).casefold()
    for coluna in colunas:
        if coluna.campo != campo:
            continue
        if _texto_da_celula(linha.celulas.get(coluna.nome)).casefold() == procurado:
            return coluna.nome
    return "outra coluna"  # pragma: no cover - o valor veio de uma delas
