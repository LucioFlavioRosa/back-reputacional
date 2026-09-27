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

from app.banco.tabelas_catalogo import (
    AreaPessoa,
    CategoriaPublico,
    Clima,
    FormatoInteracao,
    Iniciativa,
    Resultado,
    Status,
    Tema,
    UnidadeNegocio,
)
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.casos_de_uso.ler_planilha_de_agendas import (
    LinhaBruta,
    ler,
    ler_categorias_declaradas,
    ler_declarados,
    ler_instituicoes_dos_interlocutores,
)
from app.dominio.erros import Conflito, RegraViolada
from app.dominio.frentes import TIPO_DA_CATEGORIA_DE_PUBLICO
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
    Divergencia,
    aba_de,
    classificar,
    coluna_do_campo,
)
from app.dominio.interacao import (
    ABRANGENCIAS_VALIDAS,
    MODALIDADES,
    MOMENTOS_DE_MATERIAL,
    PAPEIS,
    PRESENCAS,
)
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
}

#: Vocabulário sem tabela: a lista mora em `dominio/interacao.py`, porque mudá-la
#: é mudar a regra e não o cadastro. O valor É o código, e `normalizar` faz
#: "Híbrida" casar com `hibrida` — acento e caixa saem dos dois lados.
NO_CODIGO: dict[str, tuple[str, ...]] = {
    "modalidade": MODALIDADES,
    "presenca": PRESENCAS,
    "papel": PAPEIS,
    "momento": MOMENTOS_DE_MATERIAL,
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


def _resolver(
    valor: object,
    coluna_nome: str,
    vocabulario: str,
    campo: str,
    indice: dict[str, dict[str, object]],
    declarados: Mapping[str, frozenset[str]],
    divergencias: list[Divergencia],
    apontados: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    categorias_declaradas: Mapping[str, str] = MAPPING_VAZIO,
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
        # O TIPO DA INSTITUIÇÃO É EXIGIDO AQUI, no upload, e não na confirmação.
        # Ele deriva a frente da agenda, então sem ele a criação chutaria — e o
        # chute erra a frente de TODA agenda daquela instituição. Recusar agora põe
        # a pendência na tela junto das outras, em vez de fazer a confirmação
        # falhar depois de a pessoa já ter conferido tudo.
        categoria = (
            categorias_declaradas.get(normalizar(texto))
            if vocabulario == "instituicoes"
            else None
        )
        if vocabulario == "instituicoes" and (
            categoria is None or categoria not in indice.get("categorias_publico", {})
        ):
            divergencias.append(
                Divergencia(
                    campo=campo,
                    valor=texto,
                    mensagem=(
                        f"{coluna_nome}: {texto!r} foi declarada sem uma categoria de "
                        "público válida. Escreva a categoria na coluna ao lado, na aba "
                        "de instituições — é dela que sai o tipo, e o tipo define a "
                        "frente da agenda."
                    ),
                    trava=True,
                    coluna=coluna_nome,
                )
            )
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
                categoria_declarada=categoria,
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
        motivo = (
            f"{coluna_nome}: {texto!r} não existe no cadastro. Se é novo, "
            "escreva-o também na aba de cadastro da planilha."
        )
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
    instituicoes_dos_interlocutores: Mapping[str, str],
    divergencias: list[Divergencia],
) -> None:
    """A contradição entre o órgão declarado ao lado do nome e o da agenda.

    Declarar "Carla Nova — Câmara Municipal" e usá-la numa agenda do Valor
    Econômico é pedir duas coisas incompatíveis, e o domínio só diz isso na
    CONFIRMAÇÃO — depois da conferência inteira. Criar a pessoa em um dos dois e
    seguir seria escolher por ela, calado, num dado que nenhuma tela mostra depois.

    Sem órgão declarado não há contradição: a pessoa nasce na instituição da
    agenda, que é o comportamento de antes desta coluna existir.
    """
    declarado = instituicoes_dos_interlocutores.get(normalizar(texto))
    if not declarado or not instituicao_escrita:
        return
    if declarado == normalizar(instituicao_escrita):
        return
    divergencias.append(
        Divergencia(
            campo=campo,
            valor=texto,
            mensagem=(
                f"{coluna_nome}: você declarou {texto!r} na aba de interlocutores como "
                f"sendo de outra instituição, e esta agenda é de "
                f"{instituicao_escrita!r}. Um interlocutor fala por uma instituição "
                "só — deixe as duas iguais."
            ),
            trava=True,
            coluna=coluna_nome,
        )
    )


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

    RECUSA NO UPLOAD quem é de outro órgão. A regra 4 do domínio — o participante
    pertence à instituição da agenda — recusava isso na CONFIRMAÇÃO, depois de a
    pessoa ter conferido tudo. A suspensa dependente previne o erro no Excel, mas
    a planilha convertida para o Google Sheets pode perder a validação, e o
    arquivo pode não ter saído do nosso modelo: quem garante é aqui.

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
    divergencias.append(
        Divergencia(
            campo=campo,
            valor=texto,
            mensagem=(
                f"{coluna_nome}: {texto!r} não é de {instituicao_escrita!r}, e sim de "
                f"{' ou '.join(repr(orgao) for orgao in orgaos)}. Um interlocutor fala "
                "por uma instituição só — corrija a pessoa, a instituição da agenda, "
                "ou aponte para o cadastro certo na conferência."
            ),
            trava=True,
            coluna=coluna_nome,
        )
    )
    return _Resolucao()


def _listas_da_linha(
    linha: LinhaBruta,
    indice: dict[str, dict[str, object]],
    declarados: Mapping[str, frozenset[str]],
    apontados: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    categorias_declaradas: Mapping[str, str] = MAPPING_VAZIO,
    instituicao_id: object = None,
    instituicao_escrita: str = "",
    instituicoes_dos_interlocutores: Mapping[str, str] = MAPPING_VAZIO,
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
                        if resolucao is None:
                            _conferir_orgao_declarado(
                                str(bruto),
                                coluna_nome,
                                campo_cheio,
                                instituicao_escrita,
                                instituicoes_dos_interlocutores,
                                do_item,
                            )
                    if resolucao is None:
                        resolucao = _resolver(
                            bruto,
                            coluna_nome,
                            coluna.vocabulario,
                            campo_cheio,
                            indice,
                            declarados,
                            do_item,
                            apontados,
                            categorias_declaradas,
                        )
                    resolvido = resolucao.valor
                    if resolucao.a_criar is not None:
                        criar_do_item.append(resolucao.a_criar)
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
    return propor_de_linhas(
        sessao,
        ler(conteudo),
        ler_declarados(conteudo),
        categorias_declaradas=ler_categorias_declaradas(conteudo),
        instituicoes_dos_interlocutores=ler_instituicoes_dos_interlocutores(conteudo),
    )


def propor_de_linhas(
    sessao: Session,
    por_aba: Mapping[str, list[LinhaBruta]],
    declarados: Mapping[str, frozenset[str]],
    apontados: Mapping[tuple[str, str], object] = MAPPING_VAZIO,
    categorias_declaradas: Mapping[str, str] = MAPPING_VAZIO,
    instituicoes_dos_interlocutores: Mapping[str, str] = MAPPING_VAZIO,
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
                    bruto,
                    coluna.nome,
                    coluna.vocabulario,
                    coluna.campo,
                    indice,
                    declarados,
                    divergencias,
                    apontados,
                    categorias_declaradas,
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
            elif coluna.campo == "preve_desdobramento":
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
                listas.setdefault(coluna.campo, []).append(valor)
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
            linha,
            indice,
            declarados,
            apontados,
            categorias_declaradas,
            instituicao_id=campos.get("instituicao_id"),
            instituicao_escrita=str(linha.celulas.get(COLUNA_DA_INSTITUICAO_DA_AGENDA) or ""),
            instituicoes_dos_interlocutores=instituicoes_dos_interlocutores,
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

    return _avisar_duplicatas(sessao, propostas)


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
    apontados: dict[tuple[str, str], str] = {}
    for linha in linhas:
        if linha.decisao == "descartada":
            continue
        for bruta in linha.divergencias or []:
            acao = bruta.get("acao")
            if acao == "criar":
                vocabulario = vocabulario_do_campo(bruta["campo"])
                if vocabulario:
                    a_criar[(vocabulario, bruta["valor"])] = bruta["campo"]
            elif acao == "apontar" and bruta.get("alvo"):
                apontados[(bruta["campo"], bruta["valor"])] = bruta["alvo"]
    return a_criar, apontados


def _categorias_declaradas(linhas) -> dict[str, str]:
    """O tipo de cada instituição a criar, guardado no upload.

    VEM DA DIVERGÊNCIA e não do arquivo, porque o arquivo não é guardado. O
    upload anota o tipo declarado em `categoria_declarada` ao marcar `acao="criar"`.
    """
    tipos: dict[str, str] = {}
    for linha in linhas:
        if linha.decisao == "descartada":
            continue
        for bruta in linha.divergencias or []:
            if bruta.get("acao") == "criar" and bruta.get("categoria_declarada"):
                tipos[normalizar(bruta["valor"])] = bruta["categoria_declarada"]
    return tipos


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


def _instituicao_de_cada_interlocutor(
    linhas, indice, escolhidos: Mapping[tuple[str, str], object] = MAPPING_VAZIO
) -> dict[str, object]:
    """Interlocutor novo → a instituição da agenda em que ele aparece.

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
    """
    de_quem: dict[str, object] = {}
    ambiguos: set[str] = set()
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
                if chave in de_quem and de_quem[chave] != instituicao:
                    # A MESMA PESSOA NOVA em agendas de instituições diferentes:
                    # não há como escolher, e escolher errado a faria ser recusada
                    # em toda edição futura daquela agenda. Quem sabe é quem
                    # cadastra.
                    ambiguos.add(str(pessoa))
                de_quem[chave] = instituicao

    if ambiguos:
        raise RegraViolada(
            f"{', '.join(sorted(ambiguos))} aparece em agendas de instituições "
            "diferentes, e um interlocutor pertence a uma só. Cadastre-o pela tela "
            "de Administração e aponte para ele na conferência."
        )
    return de_quem


def _criar_cadastros(
    sessao: Session,
    a_criar,
    categorias: Mapping[str, str],
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
    for (vocabulario, valor), _campo in sorted(a_criar.items(), key=peso):
        if vocabulario != "instituicoes" and not de_quem:
            sessao.flush()
            de_quem = _instituicao_de_cada_interlocutor(linhas, _indice(sessao), escolhidos)
        if vocabulario == "instituicoes":
            # O CAMINHO CANÔNICO: a categoria vem da planilha e o TIPO NASCE DELA,
            # exatamente como `api/stakeholders.py` faz — "a tela de cadastro nao
            # pergunta mais o tipo; ausente, ele vem da categoria de publico".
            # Gravar `categoria_publico_id` é o que mantém a instituição importada
            # visível para a taxonomia de públicos do Score; sem ela, ficaria fora
            # de uma área inteira do produto.
            categoria_nome = categorias.get(normalizar(valor))
            categoria = (
                sessao.scalars(
                    select(CategoriaPublico).where(
                        CategoriaPublico.id == indice["categorias_publico"][categoria_nome]
                    )
                ).first()
                if categoria_nome in indice.get("categorias_publico", {})
                else None
            )
            if categoria is None:
                raise RegraViolada(
                    f"A instituição {valor!r} foi declarada sem uma categoria de "
                    "público válida. Escreva a categoria na coluna ao lado, na aba de "
                    "instituições — é dela que sai o tipo."
                )
            sessao.add(
                Instituicao(
                    nome=valor,
                    nome_normalizado=normalizar(valor),
                    tipo=TIPO_DA_CATEGORIA_DE_PUBLICO[categoria.codigo],
                    categoria_publico_id=categoria.id,
                    uf="NA",
                )
            )
        elif vocabulario == "interlocutores":
            sessao.add(
                Interlocutor(
                    nome=valor,
                    nome_normalizado=normalizar(valor),
                    instituicao_id=de_quem.get(normalizar(valor)),
                )
            )
        elif vocabulario == "pessoas_aegea":
            sessao.add(PessoaAegea(nome=valor, nome_normalizado=normalizar(valor)))
        elif vocabulario == "temas":
            from app.banco.tabelas_catalogo import Tema

            # `livre` e não `estrategico`: tema estratégico é vocabulário fechado
            # do modelo, e a planilha não o amplia.
            sessao.add(Tema(nome=valor, nivel="livre"))
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

    (proposta,) = propor_de_linhas(sessao, _linhas_para_reler([alvo]), {}, escolhidos)
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
        sessao, a_criar, _categorias_declaradas(linhas), _indice(sessao), linhas, escolhidos
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


