"""Leitura dos cadastros de stakeholders.

A listagem de interações devolve chaves estrangeiras, não nomes. Quem monta a
tela resolve os nomes com estes três diretórios, carregados uma vez — são
poucas centenas de linhas e mudam raramente.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencias import (
    UsuarioQueAdministraCadastros,
    UsuarioQueVeDiretorio,
    exigir_diretorio,
    exigir_portal_crm,
)
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import (
    AreaPessoa,
    CategoriaPublico,
    Relevancia,
    SubcategoriaPublico,
    Tema,
)
from app.banco.tabelas_stakeholders import (
    Instituicao,
    Interlocutor,
    PessoaAegea,
    PessoaAegeaTema,
)
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.frentes import TIPO_DA_CATEGORIA_DE_PUBLICO, TIPOS_DE_INSTITUICAO

rotas = APIRouter(
    prefix="/api",
    tags=["stakeholders"],
    # `exigir_diretorio`, e não só autenticação: estas três rotas devolvem o
    # mapa de relacionamento inteiro da Aegea — todo jornalista, gestor público
    # e entidade com quem a companhia fala. Para um terceiro isso pode valer
    # mais do que os registros. Não passam por `condicoes()`, então a barreira
    # é o papel.
    # DUAS dependências, e as duas importam.
    #
    # O portal diz em qual módulo se entra; `ve_diretorio` diz se, dentro dele,
    # a pessoa alcança o mapa de relacionamento — que é todo jornalista, gestor
    # e entidade com quem a Aegea fala. Um perfil do CRM sem `ve_diretorio`
    # continua barrado, como antes.
    dependencies=[Depends(exigir_portal_crm), Depends(exigir_diretorio)],
)

#: Vem da plataforma para carregar o `scope="function"` junto — ver
#: `app/banco/sessao.py`. Redeclarar aqui perderia isso em silêncio.
Sessao = SessaoDoPedido


class InstituicaoSaida(BaseModel):
    id: UUID
    nome: str
    tipo: str
    nome_completo: str | None
    esfera_id: int | None
    uf: str | None
    #: Tier 1 a 4. Nulo nas cadastradas antes de a coluna existir.
    tier: int | None
    #: A taxonomia de publicos (10 categorias) e sua subdivisao. Nulos em quem
    #: ainda nao foi reclassificado — ver `0036_categoria_de_publico.sql`.
    categoria_publico_id: int | None
    subcategoria_publico_id: int | None
    ativo: bool


class InterlocutorSaida(BaseModel):
    id: UUID
    nome: str
    instituicao_id: UUID | None
    cargo: str | None
    email: str | None
    tipo: str | None
    ativo: bool


class PessoaAegeaSaida(BaseModel):
    id: UUID
    nome: str
    cargo: str | None
    email: str | None
    eh_porta_voz: bool
    #: DE ONDE esta pessoa fala. Nulo em quem foi cadastrado antes de a coluna
    #: existir, ou em quem é equipe (o campo só faz sentido para porta-voz).
    area_id: int | None
    ativo: bool
    #: SOBRE O QUE ESTA PESSOA PODE FALAR.
    #:
    #: Entrou aqui porque a regra de "fora do escopo" — agenda conduzida por
    #: quem nao responde por aquele assunto — se faz na tela, cruzando estes
    #: ids com os temas da interacao. Sem eles na listagem, a conta exigiria
    #: uma requisicao por pessoa.
    temas: list[int] = Field(default_factory=list)


@rotas.get("/instituicoes", response_model=list[InstituicaoSaida])
def listar_instituicoes(
    sessao: Sessao,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[Instituicao]:
    consulta = select(Instituicao).order_by(Instituicao.nome)
    if not incluir_inativos:
        consulta = consulta.where(Instituicao.ativo.is_(True))
    return list(sessao.scalars(consulta))


@rotas.get("/interlocutores", response_model=list[InterlocutorSaida])
def listar_interlocutores(
    sessao: Sessao,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[Interlocutor]:
    """Quem fala pelas instituicoes.

    DISPONIVEL = a pessoa esta ativa E a instituicao dela esta ativa. Desativar
    a instituicao nao reescreve o `ativo` de cada pessoa — e o que permite
    reativa-la depois sem "religar" quem foi desligada individualmente —, mas
    a listagem padrao, que alimenta quem oferece escolha, aplica os dois
    niveis. `incluir_inativos` devolve tudo, para a administracao.
    """
    consulta = select(Interlocutor).order_by(Interlocutor.nome)
    if not incluir_inativos:
        # `outerjoin`: `instituicao_id` e anulavel, e uma pessoa sem
        # instituicao nao tem instituicao desativada — continua disponivel.
        consulta = (
            consulta.outerjoin(Instituicao, Instituicao.id == Interlocutor.instituicao_id)
            .where(Interlocutor.ativo.is_(True))
            .where(or_(Instituicao.id.is_(None), Instituicao.ativo.is_(True)))
        )
    return list(sessao.scalars(consulta))


@rotas.get("/pessoas-aegea", response_model=list[PessoaAegeaSaida])
def listar_pessoas_aegea(
    sessao: Sessao,
    somente_porta_vozes: Annotated[bool, Query()] = False,
    incluir_inativos: Annotated[bool, Query()] = False,
) -> list[PessoaAegea]:
    """Porta-vozes e equipe. O diretório de porta-vozes filtra por
    `somente_porta_vozes`; o cadastro de interação precisa dos dois."""
    consulta = select(PessoaAegea).order_by(PessoaAegea.nome)
    if somente_porta_vozes:
        consulta = consulta.where(PessoaAegea.eh_porta_voz.is_(True))
    if not incluir_inativos:
        consulta = consulta.where(PessoaAegea.ativo.is_(True))
    return list(sessao.scalars(consulta))


# -- administracao dos cadastros ----------------------------------------------
#
# OS CADASTROS SE EDITAM PELA TELA porque duas decisoes do formulario dependem
# deles: a frente escolhida filtra as instituicoes pelo TIPO, e a instituicao
# escolhida filtra quem pode representar a outra parte. Sem um lugar para
# cadastrar, essas duas listas so teriam o que a planilha trouxe — e uma agenda
# com um orgao novo nao teria como ser registrada.
#
# ESCREVER EXIGE `administra_dicionarios`, e nao `escrita`: quem cadastra agenda
# LE estes nomes o tempo todo e nao deve reescreve-los. Renomear uma instituicao
# muda o que aparece em toda agenda que aponta para ela.


class InstituicaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1)
    #: `veiculo`, `orgao`, `entidade`, `investidor`, `proposicao`,
    #: `area_interna`, `credor`. E o que liga a instituicao a uma FRENTE — ver
    #: `TIPO_DE_INSTITUICAO` no dominio.
    #:
    #: OPCIONAL: a tela de cadastro nao pergunta mais o tipo. Ausente, ele vem
    #: da categoria de publico (`TIPO_DA_CATEGORIA_DE_PUBLICO`) — e sem
    #: categoria tambem, a criacao e recusada, porque uma instituicao sem tipo
    #: nao aparece em formulario nenhum. Na edicao, ausente, o tipo gravado
    #: fica como esta.
    tipo: str | None = None
    #: O nome POR EXTENSO. Quem escolhe "ABCON" no formulario de agenda
    #: precisa saber que instituicao e essa, e a sigla nao diz.
    nome_completo: str | None = None
    esfera_id: int | None = None
    uf: str | None = None
    #: A RELEVANCIA da instituicao: 1 a 4. Opcional AQUI e obrigatoria na tela,
    #: e a diferenca e proposital — as 98 instituicoes que existiam antes da
    #: coluna nao tem tier, e um PUT que exigisse o campo impediria de corrigir
    #: o nome de qualquer uma delas sem antes classifica-la.
    tier: int | None = None
    #: A NOVA TAXONOMIA DE PUBLICOS. Opcional pelo mesmo motivo do `tier`: as
    #: instituicoes que existiam antes desta coluna nao tem categoria, e um PUT
    #: que a exigisse impediria de corrigir qualquer uma delas sem antes
    #: classifica-la.
    categoria_publico_id: int | None = None
    #: So faz sentido junto de `categoria_publico_id`, e so quando a categoria
    #: tem `padrao_de_quebra != sem_quebra` — ver `_conferir_categoria_publico`.
    subcategoria_publico_id: int | None = None
    ativo: bool = True


class InterlocutorEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1)
    #: DE QUEM esta pessoa fala. E o que faz ela aparecer — ou nao — na lista
    #: "Pela outra parte" de uma agenda.
    instituicao_id: UUID | None = None
    cargo: str | None = None
    #: Como se chega na pessoa para marcar a agenda.
    email: str | None = None
    tipo: str | None = None
    ativo: bool = True


def _gravar(sessao, registro, *, ao_colidir: str, novo: bool = False):
    """Grava, e traduz colisao de indice unico em mensagem de gente.

    ESTA FUNCAO EXISTE POR UMA ORDEM QUE E FACIL DE ERRAR, e que eu errei: o
    `add` precisa ficar DENTRO do savepoint. Um `flush` que falha marca a
    SESSAO INTEIRA para rollback, e o savepoint so a protege se a insercao
    inteira estiver dentro dele. Com o `add` de fora, o comando seguinte
    estoura `PendingRollbackError` — um erro sem relacao aparente com o que a
    pessoa fez.

    Estava copiada em SEIS rotas. Uma regra que so vale se escrita numa ordem
    especifica, repetida seis vezes, e seis chances de a proxima edicao
    inverte-la em uma so.

    `ao_colidir` e a mensagem que a pessoa le. O banco diria "duplicate key
    value violates unique constraint", que nao ajuda ninguem a decidir o que
    fazer.
    """
    try:
        with sessao.begin_nested():
            if novo:
                sessao.add(registro)
            sessao.flush()
    except IntegrityError as erro:
        raise RegraViolada(ao_colidir) from erro
    return registro


def _normalizar(nome: str) -> str:
    """A forma comparavel do nome, como a planilha ja gravava.

    O indice unico e `(nome_normalizado, tipo)`: sem normalizar aqui, "Folha de
    S.Paulo" e "FOLHA DE S.PAULO" entrariam como duas instituicoes, e a segunda
    agenda apontaria para a duplicata sem ninguem notar.
    """
    return unicodedata.normalize("NFKD", nome.strip().lower()).encode(
        "ascii", "ignore"
    ).decode()


@rotas.post(
    "/instituicoes", response_model=InstituicaoSaida, status_code=status.HTTP_201_CREATED
)
def criar_instituicao(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, entrada: InstituicaoEntrada
) -> Instituicao:
    _conferir_tier(sessao, entrada.tier)
    _conferir_categoria_publico(
        sessao, entrada.categoria_publico_id, entrada.subcategoria_publico_id
    )
    tipo = _tipo_efetivo(sessao, entrada, atual=None)
    registro = Instituicao(
        nome=entrada.nome.strip(),
        nome_normalizado=_normalizar(entrada.nome),
        tipo=tipo,
        nome_completo=entrada.nome_completo,
        categoria_publico_id=entrada.categoria_publico_id,
        subcategoria_publico_id=entrada.subcategoria_publico_id,
        esfera_id=entrada.esfera_id,
        uf=entrada.uf,
        tier=entrada.tier,
        ativo=entrada.ativo,
    )
    _gravar(
        sessao,
        registro,
        novo=True,
        ao_colidir=(
            f"Ja existe uma instituicao chamada {entrada.nome!r} do tipo {tipo!r}."
        ),
    )

    return registro


def _tipo_efetivo(sessao: Sessao, entrada: InstituicaoEntrada, *, atual: str | None) -> str:
    """O tipo que vai ficar gravado: o informado, ou o que a categoria implica.

    A ORDEM E ESTA: quem manda `tipo` esta dizendo o que quer, e a categoria
    nao passa por cima — e o que permite corrigir, na edicao, um banco credor
    que a taxonomia nao distingue de um investidor. Sem `tipo`, a categoria
    decide; sem os dois, na edicao o tipo gravado fica, e na criacao nao ha de
    onde tirar um — recusar aqui e melhor do que gravar uma instituicao que
    nunca aparece em formulario nenhum.
    """
    if entrada.tipo is not None:
        if entrada.tipo not in TIPOS_DE_INSTITUICAO:
            raise RegraViolada(
                f"Tipo invalido: {entrada.tipo!r}. "
                f"Use {', '.join(sorted(TIPOS_DE_INSTITUICAO))}."
            )
        return entrada.tipo
    if entrada.categoria_publico_id is not None:
        # `_conferir_categoria_publico` ja garantiu que ela existe e esta ativa.
        categoria = sessao.get(CategoriaPublico, entrada.categoria_publico_id)
        tipo = TIPO_DA_CATEGORIA_DE_PUBLICO.get(categoria.codigo) if categoria else None
        if tipo is not None:
            return tipo
    if atual is not None:
        return atual
    raise RegraViolada(
        "Informe a categoria de publico: e dela que sai o tipo da instituicao, "
        "e sem tipo ela nao apareceria em formulario nenhum."
    )


def _conferir_tier(sessao: Sessao, tier: int | None) -> None:
    """Recusa tier que nao existe, ou que foi desativado.

    A chave estrangeira ja recusaria o inexistente — com um `IntegrityError`
    que sai como 500, uma mensagem que nao diz o que fazer. E ela NAO recusa o
    desativado: o dicionario continua tendo a linha. Conferir aqui e o que faz
    a API responder a mesma coisa que a tela oferece.
    """
    if tier is None:
        return
    valido = sessao.scalar(
        select(Relevancia.id).where(Relevancia.id == tier, Relevancia.ativo.is_(True))
    )
    if valido is None:
        disponiveis = sessao.scalars(
            select(Relevancia.id).where(Relevancia.ativo.is_(True)).order_by(Relevancia.ordem)
        ).all()
        raise RegraViolada(
            f"Relevancia invalida: {tier!r}. Use "
            f"{', '.join(str(i) for i in disponiveis)}."
        )


def _conferir_categoria_publico(
    sessao: Sessao,
    categoria_publico_id: int | None,
    subcategoria_publico_id: int | None,
) -> None:
    """Recusa categoria/subcategoria inexistente ou desativada, e recusa uma
    subcategoria que nao pertence a categoria informada.

    Mesmo raciocinio de `_conferir_tier`: a chave estrangeira ja recusa o id
    que nao existe, mas nao o desativado, e nunca o cruzamento
    categoria x subcategoria — esse pareamento e regra de dominio, nao algo
    que uma FK sozinha expresse.
    """
    if categoria_publico_id is not None:
        valida = sessao.scalar(
            select(CategoriaPublico.id).where(
                CategoriaPublico.id == categoria_publico_id,
                CategoriaPublico.ativo.is_(True),
            )
        )
        if valida is None:
            raise RegraViolada(f"Categoria de publico invalida: {categoria_publico_id!r}.")

    if subcategoria_publico_id is None:
        return
    categoria_dona = sessao.scalar(
        select(SubcategoriaPublico.categoria_publico_id).where(
            SubcategoriaPublico.id == subcategoria_publico_id,
            SubcategoriaPublico.ativo.is_(True),
        )
    )
    if categoria_dona is None:
        raise RegraViolada(f"Subcategoria de publico invalida: {subcategoria_publico_id!r}.")
    if categoria_dona != categoria_publico_id:
        raise RegraViolada(
            f"Subcategoria {subcategoria_publico_id!r} nao pertence a categoria "
            f"{categoria_publico_id!r}."
        )


@rotas.put("/instituicoes/{id}", response_model=InstituicaoSaida)
def editar_instituicao(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    entrada: InstituicaoEntrada,
) -> Instituicao:
    registro = sessao.get(Instituicao, id)
    if registro is None:
        raise NaoEncontrado("Instituicao nao encontrada.")
    _conferir_tier(sessao, entrada.tier)
    _conferir_categoria_publico(
        sessao, entrada.categoria_publico_id, entrada.subcategoria_publico_id
    )
    registro.nome = entrada.nome.strip()
    registro.nome_normalizado = _normalizar(entrada.nome)
    registro.tipo = _tipo_efetivo(sessao, entrada, atual=registro.tipo)
    registro.nome_completo = entrada.nome_completo
    registro.tier = entrada.tier
    registro.categoria_publico_id = entrada.categoria_publico_id
    registro.subcategoria_publico_id = entrada.subcategoria_publico_id
    registro.esfera_id = entrada.esfera_id
    registro.uf = entrada.uf
    registro.ativo = entrada.ativo
    _gravar(
        sessao,
        registro,
        ao_colidir=(
            f"Ja existe outra instituicao chamada {entrada.nome!r} do tipo "
            f"{registro.tipo!r}."
        ),
    )
    return registro


@rotas.delete("/instituicoes/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_instituicao(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, id: UUID
) -> None:
    """Apaga a instituicao que entrou por engano. Recusa a que ja tem agenda.

    A MESMA REGRA DE `remover_interlocutor`, um nivel acima: uma instituicao
    cadastrada errada e lixo, e apagar e o certo; uma que ja esteve numa
    reuniao e um FATO, e o registro daquela reuniao ficaria sem a outra parte.
    Para essa existe `ativo = false` (Desativar, na mesma linha da tela): sai
    de quem oferece escolha e fica onde e historico.

    AS PESSOAS DELA SAEM JUNTO — quem foi cadastrado "pela ANA" nao tem para
    quem falar se a ANA some. Mas so se nenhuma delas esteve numa agenda: a
    presenca de uma pessoa numa reuniao e historico tanto quanto a da
    instituicao, e uma pessoa da ANA pode ter participado de uma agenda
    registrada em nome de outra instituicao.

    O banco recusaria de qualquer jeito, pela chave estrangeira — com uma
    mensagem de constraint que nao diz o que fazer. Aqui a recusa conta as
    agendas e aponta o gesto certo.
    """
    from app.banco.tabelas_interacoes import InteracaoInterlocutor, InteracaoRegistro
    from app.banco.tabelas_stakeholders import InterlocutorTema

    registro = sessao.get(Instituicao, id)
    if registro is None:
        raise NaoEncontrado("Instituicao nao encontrada.")

    pessoas = select(Interlocutor.id).where(Interlocutor.instituicao_id == id)
    # As agendas da instituicao, mais as agendas de qualquer pessoa dela — pelas
    # duas formas de estar numa agenda (ver `remover_interlocutor`). `union`
    # para a mesma agenda, alcancada por mais de um caminho, contar uma vez.
    agendas = (
        select(InteracaoRegistro.id)
        .where(InteracaoRegistro.instituicao_id == id)
        .union(
            select(InteracaoRegistro.id).where(
                InteracaoRegistro.interlocutor_id.in_(pessoas)
            ),
            select(InteracaoInterlocutor.interacao_id).where(
                InteracaoInterlocutor.interlocutor_id.in_(pessoas)
            ),
        )
    )
    em_agendas = sessao.scalar(select(func.count()).select_from(agendas.subquery())) or 0
    if em_agendas:
        raise RegraViolada(
            f"{registro.nome} aparece em {em_agendas} "
            f"{'agenda' if em_agendas == 1 else 'agendas'} e nao pode ser "
            "apagada: o registro delas ficaria sem a outra parte. Use "
            "Desativar — ela sai das listas e o historico fica."
        )

    sessao.execute(
        delete(InterlocutorTema).where(InterlocutorTema.interlocutor_id.in_(pessoas))
    )
    sessao.execute(delete(Interlocutor).where(Interlocutor.instituicao_id == id))
    sessao.delete(registro)
    sessao.flush()


@rotas.post(
    "/interlocutores",
    response_model=InterlocutorSaida,
    status_code=status.HTTP_201_CREATED,
)
def criar_interlocutor(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, entrada: InterlocutorEntrada
) -> Interlocutor:
    registro = Interlocutor(
        nome=entrada.nome.strip(),
        nome_normalizado=_normalizar(entrada.nome),
        instituicao_id=entrada.instituicao_id,
        cargo=entrada.cargo,
        email=entrada.email,
        tipo=entrada.tipo,
        ativo=entrada.ativo,
    )
    # PELO `_gravar`, como as outras rotas de cadastro: sem ele, a duplicata
    # sai como 500. O indice unico e `(nome_normalizado, instituicao_id)` — a
    # mesma pessoa duas vezes na mesma instituicao.
    #
    # Criar o helper e deixar duas chamadas de fora e o mesmo defeito que ele
    # existe para evitar, so que mais dificil de ver.
    return _gravar(
        sessao,
        registro,
        novo=True,
        ao_colidir=f"{entrada.nome!r} ja esta cadastrada nesta instituicao.",
    )


@rotas.put("/interlocutores/{id}", response_model=InterlocutorSaida)
def editar_interlocutor(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    entrada: InterlocutorEntrada,
) -> Interlocutor:
    registro = sessao.get(Interlocutor, id)
    if registro is None:
        raise NaoEncontrado("Pessoa nao encontrada.")
    registro.nome = entrada.nome.strip()
    registro.nome_normalizado = _normalizar(entrada.nome)
    registro.instituicao_id = entrada.instituicao_id
    registro.cargo = entrada.cargo
    registro.email = entrada.email
    registro.tipo = entrada.tipo
    registro.ativo = entrada.ativo
    return _gravar(
        sessao,
        registro,
        ao_colidir=(
            f"Ja existe outra pessoa chamada {entrada.nome!r} nesta instituicao."
        ),
    )


@rotas.delete("/interlocutores/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_interlocutor(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, id: UUID
) -> None:
    """Apaga quem entrou por engano. Recusa quem ja esteve numa agenda.

    APAGAR E DESLIGAR SAO COISAS DIFERENTES, e a diferenca e o historico.

    Uma pessoa cadastrada com o nome errado, ou na instituicao errada, e lixo:
    apagar e o certo. Uma pessoa que participou de uma reuniao e um FATO — e
    apaga-la deixaria aquela agenda sem o nome de quem esteve na sala, que e
    justamente o que este painel existe para guardar.

    O banco ja recusaria, pela chave estrangeira. Mas a mensagem seria de
    violacao de constraint, e quem lesse nao saberia o que fazer. Aqui a recusa
    diz quantas agendas dependem dela e qual e o gesto certo.
    """
    from app.banco.tabelas_interacoes import InteracaoInterlocutor, InteracaoRegistro
    from app.banco.tabelas_stakeholders import InterlocutorTema

    registro = sessao.get(Interlocutor, id)
    if registro is None:
        raise NaoEncontrado("Pessoa nao encontrada.")

    # AS DUAS FORMAS DE ESTAR NUMA AGENDA, contadas UMA vez.
    #
    # A pessoa aparece na lista (`interacao_interlocutor`) e, quando e a
    # principal, tambem na coluna (`interacao.interlocutor_id`). Sao duas
    # representacoes do MESMO fato — e somar as duas contagens dizia "participa
    # de 2 agendas" para uma reuniao so. A mensagem existe para orientar; um
    # numero inflado a torna suspeita.
    #
    # `union` (e nao `union all`) sobre os IDs resolve: a mesma agenda vinda
    # pelos dois caminhos vira uma linha.
    agendas = select(InteracaoInterlocutor.interacao_id).where(
        InteracaoInterlocutor.interlocutor_id == id
    ).union(
        select(InteracaoRegistro.id).where(InteracaoRegistro.interlocutor_id == id)
    )
    em_agendas = sessao.scalar(
        select(func.count()).select_from(agendas.subquery())
    ) or 0

    if em_agendas:
        raise RegraViolada(
            f"{registro.nome} participa de {em_agendas} "
            f"{'agenda' if em_agendas == 1 else 'agendas'} e nao pode ser "
            "apagada: o registro delas ficaria sem o nome de quem esteve na "
            "sala. Use Desligar — ela sai das listas e o historico fica."
        )

    # O vinculo com temas e ligacao pura, sem valor de historico: sai junto.
    sessao.execute(
        delete(InterlocutorTema).where(InterlocutorTema.interlocutor_id == id)
    )
    sessao.delete(registro)
    sessao.flush()


# -- porta-vozes da Aegea ------------------------------------------------------
#
# `pessoa_aegea` ja existia, e o docstring de `PessoaAegeaTema` ja dizia para
# que serve: sustentar a regra de "fora do escopo" — registro cujo tema nao esta
# na lista do porta-voz que o conduziu. O conceito estava modelado e nao havia
# como edita-lo: os temas de cada porta-voz vinham da planilha e ficavam.


class PessoaAegeaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1)
    cargo: str | None = None
    email: str | None = None
    #: `false` para quem participa de agendas sem falar pela companhia. Ver
    #: `PAPEIS`: porta-voz conta no painel de exposicao, equipe nao.
    eh_porta_voz: bool = True
    #: DE ONDE esta pessoa fala — id de `area`. Opcional: nem toda pessoa
    #: cadastrada tem área classificada.
    area_id: int | None = None
    ativo: bool = True
    #: SOBRE O QUE esta pessoa pode falar. A lista inteira substitui a anterior,
    #: que e o mesmo contrato das outras listas do produto.
    temas: list[int] = Field(default_factory=list)


def _aplicar_temas_da_pessoa(sessao, pessoa_id: UUID, temas: list[int]) -> None:
    """Substitui a lista inteira, casando por (pessoa, tema).

    Nao apaga e recria tudo: os vinculos que permanecem ficam intocados, e a
    trilha nao registra uma saida e uma entrada para um tema que nunca mudou.
    """
    atuais = {
        v.tema_id: v
        for v in sessao.scalars(
            select(PessoaAegeaTema).where(PessoaAegeaTema.pessoa_aegea_id == pessoa_id)
        )
    }
    desejados = set(temas)

    for tema_id, vinculo in atuais.items():
        if tema_id not in desejados:
            sessao.delete(vinculo)
    for tema_id in desejados - set(atuais):
        sessao.add(PessoaAegeaTema(pessoa_aegea_id=pessoa_id, tema_id=tema_id))
    sessao.flush()


def _conferir_area(sessao: Sessao, area_id: int | None) -> None:
    """Recusa área que não existe, ou que foi desativada.

    Mesmo papel de `_conferir_tier`: a chave estrangeira já recusaria o
    inexistente, com um `IntegrityError` que sai como 500. Conferir aqui é o
    que faz a API responder a mesma coisa que a tela oferece.
    """
    if area_id is None:
        return
    valida = sessao.scalar(
        select(AreaPessoa.id).where(AreaPessoa.id == area_id, AreaPessoa.ativo.is_(True))
    )
    if valida is None:
        disponiveis = sessao.scalars(
            select(AreaPessoa.id).where(AreaPessoa.ativo.is_(True)).order_by(AreaPessoa.nome)
        ).all()
        raise RegraViolada(
            f"Area invalida: {area_id!r}. Use "
            f"{', '.join(str(i) for i in disponiveis)}."
        )


@rotas.post(
    "/pessoas-aegea",
    response_model=PessoaAegeaSaida,
    status_code=status.HTTP_201_CREATED,
)
def criar_pessoa_aegea(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, entrada: PessoaAegeaEntrada
) -> PessoaAegea:
    _conferir_area(sessao, entrada.area_id)
    registro = PessoaAegea(
        nome=entrada.nome.strip(),
        nome_normalizado=_normalizar(entrada.nome),
        cargo=entrada.cargo,
        email=entrada.email,
        eh_porta_voz=entrada.eh_porta_voz,
        area_id=entrada.area_id,
        ativo=entrada.ativo,
    )
    _gravar(
        sessao,
        registro,
        novo=True,
        ao_colidir=f"Ja existe uma pessoa chamada {entrada.nome!r} na Aegea.",
    )

    _aplicar_temas_da_pessoa(sessao, registro.id, entrada.temas)
    return registro


@rotas.put("/pessoas-aegea/{id}", response_model=PessoaAegeaSaida)
def editar_pessoa_aegea(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: UUID,
    entrada: PessoaAegeaEntrada,
) -> PessoaAegea:
    registro = sessao.get(PessoaAegea, id)
    if registro is None:
        raise NaoEncontrado("Pessoa nao encontrada.")
    _conferir_area(sessao, entrada.area_id)
    registro.nome = entrada.nome.strip()
    registro.nome_normalizado = _normalizar(entrada.nome)
    registro.cargo = entrada.cargo
    registro.email = entrada.email
    registro.eh_porta_voz = entrada.eh_porta_voz
    registro.area_id = entrada.area_id
    registro.ativo = entrada.ativo
    _gravar(
        sessao,
        registro,
        ao_colidir=f"Ja existe outra pessoa chamada {entrada.nome!r} na Aegea.",
    )

    _aplicar_temas_da_pessoa(sessao, registro.id, entrada.temas)
    return registro


@rotas.get("/pessoas-aegea/{id}/temas")
def temas_do_porta_voz(
    sessao: Sessao, usuario: UsuarioQueVeDiretorio, id: UUID
) -> list[int]:
    """Sobre o que esta pessoa pode falar.

    Fora de `PessoaAegeaSaida` de proposito: a listagem de pessoas alimenta o
    formulario de agenda, que nao usa os temas, e carrega-los ali seria uma
    consulta por pessoa em toda abertura de tela.
    """
    return list(
        sessao.scalars(
            select(PessoaAegeaTema.tema_id).where(
                PessoaAegeaTema.pessoa_aegea_id == id
            )
        )
    )


# -- assuntos ------------------------------------------------------------------


class TemaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1)
    #: `estrategico` ou `livre`. O primeiro e agenda da companhia; o segundo, o
    #: que aparece sem ter sido planejado. A distincao ja existia no dicionario.
    nivel: str = "gerais"
    ativo: bool = True


class TemaSaida(BaseModel):
    id: int
    nome: str
    nivel: str
    ativo: bool


#: OS TRÊS NÍVEIS, na ordem do mais restrito ao mais aberto.
#:
#: `sensivel` é o que exige alinhamento antes de alguém falar; `estrategico` é
#: agenda da companhia; `gerais` é o que aparece sem ter sido planejado.
#:
#: `gerais` se chamava `livre` até a 0022. A migração trocou o código junto com
#: o rótulo: rótulo novo sobre código velho vira duas escritas da mesma coisa.
NIVEIS_DE_TEMA = ("sensivel", "estrategico", "gerais")


@rotas.get("/temas", response_model=list[TemaSaida])
def listar_temas(sessao: Sessao, usuario: UsuarioQueVeDiretorio) -> list[Tema]:
    """A lista COMPLETA, inclusive os inativos.

    `/api/dicionarios` devolve so os ativos, porque e o que alimenta filtro e
    formulario. Quem administra precisa ver o que desativou — senao o assunto
    some da tela e reaparece como "ja existe" na proxima tentativa de criar.
    """
    return list(sessao.scalars(select(Tema).order_by(Tema.nome)))


@rotas.post("/temas", response_model=TemaSaida, status_code=status.HTTP_201_CREATED)
def criar_tema(
    sessao: Sessao, usuario: UsuarioQueAdministraCadastros, entrada: TemaEntrada
) -> Tema:
    if entrada.nivel not in NIVEIS_DE_TEMA:
        raise RegraViolada(
            f"Nivel invalido: {entrada.nivel!r}. Use {' ou '.join(NIVEIS_DE_TEMA)}."
        )
    registro = Tema(nome=entrada.nome.strip(), nivel=entrada.nivel, ativo=entrada.ativo)
    return _gravar(
        sessao,
        registro,
        novo=True,
        ao_colidir=f"Ja existe um assunto chamado {entrada.nome!r}.",
    )


@rotas.put("/temas/{id}", response_model=TemaSaida)
def editar_tema(
    sessao: Sessao,
    usuario: UsuarioQueAdministraCadastros,
    id: int,
    entrada: TemaEntrada,
) -> Tema:
    registro = sessao.get(Tema, id)
    if registro is None:
        raise NaoEncontrado("Assunto nao encontrado.")
    if entrada.nivel not in NIVEIS_DE_TEMA:
        raise RegraViolada(
            f"Nivel invalido: {entrada.nivel!r}. Use {' ou '.join(NIVEIS_DE_TEMA)}."
        )
    registro.nome = entrada.nome.strip()
    registro.nivel = entrada.nivel
    registro.ativo = entrada.ativo
    return _gravar(
        sessao,
        registro,
        ao_colidir=f"Ja existe outro assunto chamado {entrada.nome!r}.",
    )
