"""A Base de dados das lentes: as menções como chegaram da fonte, para consulta.

O DOSSIÊ RESUME, A BASE MOSTRA. O dossiê de cada lente devolve a nota, os
painéis e cinco matérias de amostra; quem quer saber "o que aconteceu" precisa
ver as linhas de verdade — todas, filtráveis por qualquer campo, com o texto e o
link quando a fonte os mandou. É o equivalente, para as planilhas dos
fornecedores, da Base do CRM para as agendas.

TODAS AS FONTES, INCLUSIVE AS DESLIGADAS NA CALIBRAÇÃO. A calibração decide o
que entra na NOTA; a Base é a fonte crua. Esconder aqui o que a régua desligou
faria a pessoa procurar uma matéria que existe e não achar — a coluna "Fonte"
diz de onde cada linha veio, e a tela avisa quais estão fora do cálculo.

O JORNALISTA SÓ PARA QUEM VÊ O DIRETÓRIO. Na Imprensa, `autor` é cadastro de
terceiros — a mesma regra que o dossiê aplica (`ve_diretorio`). Sem a
permissão, a coluna vem vazia e a opção de filtro não é oferecida.

QUEM DECIDE ISSO É `causa_da_lente.nomeia_o_diretorio`, e não um `codigo ==
"imprensa"` escrito aqui: a mesma pergunta já governava as abas do cartão "Onde
está a causa", e duas cópias de uma regra de acesso divergem na primeira
mudança. O critério é a ORIGEM do dado — cadastro de terceiros (o jornalista)
contra o perfil que veio dentro da menção (o `Publicador` da Approach, o autor
da Bites), que é aberto nas duas lentes de rede.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.api.dependencias import UsuarioLogado, UsuarioQueEscreve, exigir_portal_score
from app.banco import repositorio_lentes, repositorio_score
from app.banco.repositorio_score import CONCESSIONARIA
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema, UnidadeNegocio
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import Interlocutor
from app.dominio.causa_da_lente import nomeia_o_diretorio
from app.dominio.erros import NaoAutorizado, NaoEncontrado, RegraViolada
from app.dominio.score import FiltroDeMencoes
from app.dominio.texto import normalizar

rotas = APIRouter(
    prefix="/api/score/base",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido

#: As lentes que têm menção. Mercado também — o recorte de imprensa econômica.
#:
#: A INSTITUCIONAL ENTROU na `0111`, que a pôs a recortar a Imprensa pela
#: subcategoria "Institucional", e na `0112`, que tirou o CRM do índice. A Base
#: é onde se confere menção a menção o que uma lente conta, e deixá-la de fora
#: seria esconder justamente as linhas que passaram a formar a nota dela.
LENTES_DA_BASE = ("imprensa", "mercado", "sociedade", "clientes", "institucional")

#: O que se pode ordenar, e por qual coluna.
ORDENAVEIS = {
    "data": Mencao.data,
    "veiculo": Mencao.veiculo,
    "sentimento": Mencao.sentimento,
    "tier": Mencao.tier,
    "engajamento": Mencao.engajamento,
    "uf": Mencao.uf,
    "autor": Mencao.autor,
    #: PELO NOME QUE A COLUNA MOSTRA, e não pelo texto cru: a lista exibe
    #: `CONCESSIONARIA` desde a `0099`, e ordenar pela outra faria "Companhia
    #: Riograndense de Saneamento (Corsan)" cair no C enquanto a tela mostra
    #: "Corsan". A junção que ela exige está na consulta de `listar_mencoes`.
    "empresa": CONCESSIONARIA,
}

TAMANHO_MAXIMO = 500


class MencaoDaBase(BaseModel):
    id: str
    data: date | None
    mes: str
    fonte: str
    fonte_no_calculo: bool
    veiculo: str | None
    #: O VEÍCULO NO CADASTRO COMPARTILHADO, pelo id — não pelo nome, que pode
    #: divergir do `veiculo` acima (o texto cru da fonte). É o que permite a
    #: tela oferecer só os jornalistas cadastrados NESTA instituição (edição do
    #: autor, ver `editar_jornalista` abaixo). Nulo quando a menção não bateu
    #: com nenhum veículo do cadastro — e aí não há o que oferecer.
    instituicao_id: str | None
    tier: str | None
    sentimento: str | None
    atributo: str | None
    #: O tema COMO O FORNECEDOR O ESCREVEU. O do cadastro vem em `tema_n3`.
    tema: str | None
    #: A taxonomia do CRM, quando a menção está ligada a um tema do cadastro.
    tema_n1: str | None
    tema_n2: str | None
    tema_n3: str | None
    subtema: str | None
    empresa: str | None
    uf: str | None
    autor: str | None
    perfil_autor: str | None
    engajamento: float | None
    publico_alvo: str | None
    titulo: str | None
    link: str | None


class PaginaDaBase(BaseModel):
    itens: list[MencaoDaBase]
    total: int
    pagina: int
    tamanho: int


class OpcoesDaBase(BaseModel):
    fontes: list[str]
    sentimentos: list[str]
    tiers: list[str]
    veiculos: list[str]
    atributos: list[str]
    temas: list[str]
    temas_n1: list[str]
    temas_n2: list[str]
    temas_n3: list[str]
    subtemas: list[str]
    empresas: list[str]
    ufs: list[str]
    autores: list[str]
    perfis: list[str]


class EdicaoDoJornalista(BaseModel):
    #: `None` desvincula — a matéria some da lista de "jornalista escolhido" e
    #: volta a precisar de uma escolha.
    interlocutor_id: UUID | None


class JornalistaDaMencao(BaseModel):
    autor: str | None


def _lente(sessao, codigo: str):
    if codigo not in LENTES_DA_BASE:
        raise NaoEncontrado("Esta lente não tem base de menções.")
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")
    return lente


def _onde(lente_id: int, de: date | None, ate: date | None) -> list:
    """O recorte que vale para a lista e para as opções: a lente e o período."""
    if de and ate and de > ate:
        raise RegraViolada("O início do período é depois do fim.")
    condicoes = [ScoreFonte.lente_id == lente_id]
    #: PELA DATA DA MENÇÃO, e pelo mês quando ela não veio: uma linha sem data
    #: continua achável pelo período do mês a que pertence.
    data_efetiva = func.coalesce(Mencao.data, Mencao.mes)
    if de:
        condicoes.append(data_efetiva >= de)
    if ate:
        condicoes.append(data_efetiva <= ate)
    return condicoes


def _busca(q: str) -> object:
    """A busca livre: qualquer pedaço, sem acento, em todo campo de texto.

    INCLUI O NOME DO CADASTRO, e não só o texto do fornecedor. A coluna
    "Concessionária" mostra `CONCESSIONARIA` desde a `0099` — o nome do
    cadastro, com o texto do fornecedor como reserva —, e uma busca que varra só
    `unidade_texto` devolve zero para quem lê "Holding / corporativo" na tela e
    digita exatamente isso, porque o gravado é "Aegea Saneamento e Participações
    S/A". É o pior tipo de busca vazia, porque nada na tela indica que a palavra
    certa era outra — e a razão social da Corsan contém "Corsan", então o caso
    que todo mundo testa esconde o defeito.

    OS DOIS, e não um no lugar do outro: quem procura pela razão social está
    lendo a planilha que tem na mão, e não pode perder o resultado. `like` sobre
    um `or_` de colunas só ganha linha.

    EXIGE `outerjoin(UnidadeNegocio, ...)` em QUEM USA — nas DUAS consultas, a
    da lista e a do `total`. Elas são montadas separadamente, e uma junção só na
    primeira faria a paginação discordar do que a lista mostra.
    """
    termo = f"%{normalizar(q)}%"
    campos = (
        Mencao.titulo_texto,
        Mencao.veiculo,
        Mencao.autor,
        Mencao.tema_texto,
        Mencao.subtema,
        Mencao.unidade_texto,
        UnidadeNegocio.nome,
        Mencao.atributo,
        Mencao.uf,
        Tema.nome,
    )
    return or_(*(_sem_acento(campo).like(termo) for campo in campos))


#: AS MAIÚSCULAS ACENTUADAS TAMBÉM: num banco com collation "C", `lower()` não
#: converte "Á" — então o acento sai ANTES, e o `lower` só vê ASCII.
_COM_ACENTO = "áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ"
_SEM_ACENTO = "aaaaaeeeeiiiiooooouuuucnAAAAAEEEEIIIIOOOOOUUUUCN"


def _sem_acento(coluna):
    """A coluna em minúscula e sem acento, no banco — o par de `normalizar` do
    termo. `translate`, e não a extensão `unaccent`, que o schema não instala."""
    return func.lower(func.translate(coluna, _COM_ACENTO, _SEM_ACENTO))


@rotas.get("/{codigo}/mencoes")
def listar_mencoes(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    de: Annotated[date | None, Query()] = None,
    ate: Annotated[date | None, Query()] = None,
    q: Annotated[str | None, Query(description="busca livre em todo campo de texto")] = None,
    fonte: Annotated[str | None, Query()] = None,
    sentimento: Annotated[str | None, Query()] = None,
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
    tema_n1: Annotated[str | None, Query()] = None,
    tema_n2: Annotated[str | None, Query()] = None,
    tema_n3: Annotated[str | None, Query()] = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=TAMANHO_MAXIMO)] = 50,
    ordenacao: Annotated[str, Query(description="campo, com '-' para descendente")] = "-data",
) -> PaginaDaBase:
    """As menções da lente no período, filtradas, paginadas e ordenadas."""
    lente = _lente(sessao, codigo)
    calibracao = repositorio_score.calibracao_vigente(sessao)
    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        #: O JORNALISTA não filtra quem não o vê — senão a contagem o revelaria.
        autor=autor if (usuario.ve_diretorio or not nomeia_o_diretorio(codigo)) else None,
        empresa=empresa,
        tema_n1=tema_n1,
        tema_n2=tema_n2,
        tema_n3=tema_n3,
    )
    onde = [*_onde(lente.id, de, ate), *repositorio_score.condicoes_do_filtro(filtro)]
    if fonte:
        onde.append(ScoreFonte.nome == fonte)
    if sentimento:
        onde.append(Mencao.sentimento == sentimento)
    if q and q.strip():
        onde.append(_busca(q))

    base = (
        select(Mencao.id)
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        #: A MESMA JUNÇÃO DA LISTA, porque `condicoes_do_filtro` e `_busca`
        #: alcançam `UnidadeNegocio.nome`. Esta consulta existe só para contar,
        #: e é montada à parte da que exibe — então a junção precisa ser
        #: repetida aqui, ou o `total` do rodapé discorda das linhas.
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .where(*onde)
    )
    total = sessao.scalar(select(func.count()).select_from(base.subquery())) or 0

    campo = ordenacao.lstrip("-")
    if campo not in ORDENAVEIS:
        raise RegraViolada(f"Ordenação inválida: {ordenacao!r}. Use {', '.join(ORDENAVEIS)}.")
    coluna = ORDENAVEIS[campo]
    ordem = coluna.desc().nulls_last() if ordenacao.startswith("-") else coluna.asc().nulls_last()

    #: O PILAR E O TEMA ESTRATÉGICO GRAVADOS NA PRÓPRIA MENÇÃO (`0098`), em
    #: ALIAS próprio: `BlocoTema` e `MacroTema` já entram nesta consulta pela
    #: CADEIA (`Tema -> MacroTema -> BlocoTema`), e reusar o mesmo nome para uma
    #: segunda junção faria as duas virarem a mesma — a linha ligada só pelo
    #: pilar sumiria do `join` da cadeia e levaria a menção com ela.
    PilarDaMencao = aliased(BlocoTema)
    TemaEstrategicoDaMencao = aliased(MacroTema)

    consulta = (
        select(
            Mencao,
            ScoreFonte.nome,
            ScoreFonte.codigo,
            Mencao.tema_texto,
            Tema.nome,
            MacroTema.nome,
            BlocoTema.nome,
            PilarDaMencao.nome,
            TemaEstrategicoDaMencao.nome,
            CONCESSIONARIA,
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .outerjoin(MacroTema, MacroTema.id == Tema.macro_tema_id)
        .outerjoin(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
        #: A CONCESSIONÁRIA DO CADASTRO (`0099`). `outerjoin` porque
        #: `Mencao.unidade_negocio_id` é anulável e `Mencao.unidade_texto` é a
        #: reserva: a menção sem unidade resolvida continua na lista.
        .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
        .outerjoin(PilarDaMencao, PilarDaMencao.id == Mencao.bloco_tema_id)
        .outerjoin(
            TemaEstrategicoDaMencao,
            TemaEstrategicoDaMencao.id == Mencao.macro_tema_id,
        )
        .where(*onde)
        .order_by(ordem, Mencao.criado_em.desc(), Mencao.id)
        .offset((pagina - 1) * tamanho)
        .limit(tamanho)
    )
    desligadas = set(calibracao.fontes_desligadas or ())
    esconde_autor = nomeia_o_diretorio(codigo) and not usuario.ve_diretorio
    itens = [
        MencaoDaBase(
            id=str(m.id),
            data=m.data,
            mes=f"{m.mes:%Y-%m}",
            fonte=nome_da_fonte,
            fonte_no_calculo=codigo_da_fonte not in desligadas,
            veiculo=m.veiculo,
            instituicao_id=str(m.instituicao_id) if m.instituicao_id else None,
            tier=m.tier,
            sentimento=m.sentimento,
            atributo=m.atributo,
            tema=tema_mostrado,
            #: O PILAR DA LINHA, em três tentativas e nesta ordem:
            #:
            #:   1. o derivado do tema do cadastro (`tema_id -> N2 -> N1`)
            #:   2. o GRAVADO na menção pela `0098` (`mencao.bloco_tema_id`)
            #:   3. o tema que o fornecedor escreveu
            #:
            #: O DERIVADO PRIMEIRO, de propósito: onde ele existe, a coluna
            #: continua mostrando exatamente o que mostrava. O passo 2 só
            #: preenche o que estava caindo no passo 3.
            #:
            #: O PASSO 3 É UM RÓTULO ERRADO quando existe N1 derivado ou
            #: gravado:
            #: `tema_texto` ali é a `Subcategoria` do fornecedor — um ASSUNTO
            #: —, e a coluna que o exibe se chama "Pilar (N1)", então a pessoa
            #: lê "Falta de água" como se fosse um dos 7 pilares. Com a `0098` o
            #: pilar de verdade existe, e é ele que aparece.
            #:
            #: O passo 3 fica para a linha sem nível nenhum: ali a coluna mostra
            #: o que o fornecedor disse, que é mais útil que vazio.
            tema_n1=n1 or n1_da_mencao or m.tema_texto,
            tema_n2=n2 or n2_da_mencao,
            tema_n3=n3,
            subtema=m.subtema,
            #: A CONCESSIONÁRIA COMO O CADASTRO A CHAMA, com o texto do
            #: fornecedor como reserva — a mesma expressão por que a lista
            #: ordena e por que o seletor agrupa. Ver `CONCESSIONARIA`.
            empresa=concessionaria,
            uf=m.uf,
            autor=None if esconde_autor else m.autor,
            perfil_autor=m.perfil_autor,
            engajamento=float(m.engajamento) if m.engajamento is not None else None,
            publico_alvo=m.publico_alvo,
            titulo=m.titulo_texto,
            link=m.link,
        )
        for (
            m,
            nome_da_fonte,
            codigo_da_fonte,
            tema_mostrado,
            n3,
            n2,
            n1,
            n1_da_mencao,
            n2_da_mencao,
            concessionaria,
        ) in sessao.execute(consulta)
    ]
    return PaginaDaBase(itens=itens, total=total, pagina=pagina, tamanho=tamanho)


@rotas.get("/{codigo}/mencoes/opcoes")
def opcoes_da_base(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    de: Annotated[date | None, Query()] = None,
    ate: Annotated[date | None, Query()] = None,
) -> OpcoesDaBase:
    """Os valores de cada campo que aparecem nas menções da lente no período."""
    lente = _lente(sessao, codigo)
    onde = _onde(lente.id, de, ate)

    def distintos(coluna, limite: int | None = None) -> list[str]:
        consulta = (
            select(coluna, func.count().label("n"))
            .select_from(Mencao)
            .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
            .outerjoin(Tema, Tema.id == Mencao.tema_id)
            .outerjoin(MacroTema, MacroTema.id == Tema.macro_tema_id)
            .outerjoin(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
            #: PARA `CONCESSIONARIA` PODER SER UMA DAS COLUNAS. Sai barato (29
            #: linhas, chave indexada) e evita uma segunda função só para ela —
            #: o que importa é a lista agrupar pela MESMA expressão que a
            #: coluna da tabela mostra e que o filtro recorta.
            .outerjoin(UnidadeNegocio, UnidadeNegocio.id == Mencao.unidade_negocio_id)
            .where(*onde, coluna.is_not(None))
            .group_by(coluna)
        )
        #: AS LISTAS LONGAS (autor, veículo) VÊM POR VOLUME e cortadas — a
        #: pergunta de quem abre o seletor é "quem mais aparece".
        consulta = (
            consulta.order_by(func.count().desc(), coluna).limit(limite)
            if limite
            else consulta.order_by(coluna)
        )
        return [str(valor) for valor, _ in sessao.execute(consulta) if valor]

    esconde_autor = nomeia_o_diretorio(codigo) and not usuario.ve_diretorio
    return OpcoesDaBase(
        fontes=distintos(ScoreFonte.nome),
        sentimentos=distintos(Mencao.sentimento),
        tiers=distintos(Mencao.tier),
        veiculos=distintos(Mencao.veiculo, 200),
        atributos=distintos(Mencao.atributo),
        temas=distintos(Mencao.tema_texto),
        #: PILAR E TEMA ESTRATÉGICO: a taxonomia inteira, sempre — são filtros
        #: rápidos fixos (ver `repositorio_lentes.taxonomia_n1_n2`).
        **repositorio_lentes.taxonomia_n1_n2(sessao, distintos(Mencao.tema_texto)),
        temas_n3=distintos(Tema.nome),
        subtemas=distintos(Mencao.subtema),
        empresas=distintos(CONCESSIONARIA, 100),
        ufs=distintos(Mencao.uf),
        autores=[] if esconde_autor else distintos(Mencao.autor, 100),
        perfis=distintos(Mencao.perfil_autor),
    )


@rotas.patch("/mencoes/{id}/jornalista")
def editar_jornalista(
    sessao: Sessao,
    usuario: UsuarioQueEscreve,
    id: UUID,
    edicao: EdicaoDoJornalista,
) -> JornalistaDaMencao:
    """Vincula — ou desvincula — o jornalista da menção a um interlocutor do
    cadastro compartilhado.

    SÓ QUEM VÊ O DIRETÓRIO EDITA, a mesma regra que esconde a coluna e o filtro
    na leitura (`nomeia_o_diretorio` por trás de `ve_diretorio`). Sem isto, a
    edição vazaria por outra porta o nome que a leitura nega.

    O SERVIDOR CONFERE O VÍNCULO, e não confia no que a tela mandou: um
    interlocutor só entra se pertencer À MESMA INSTITUIÇÃO da matéria — a regra
    de produto ("só jornalista cadastrado no veículo") só vale de verdade
    cercada aqui; só na tela, um cliente direto da API a ignoraria.

    `autor` CONTINUA TEXTO LIVRE NO BANCO: a escolha veio de uma lista fechada
    (o interlocutor existe e pertence à instituição certa), mas o que fica
    gravado é o nome dele, não um vínculo. Mudar o cadastro do interlocutor
    depois não atualiza matérias já vinculadas — o mesmo compromisso que o
    resto da Base já faz com dado de fonte externa.
    """
    if not usuario.ve_diretorio:
        raise NaoAutorizado("Seu perfil não tem acesso aos cadastros de stakeholders.")
    if usuario.papel is None or not usuario.papel.pode_editar_tudo:
        nome = usuario.papel.nome if usuario.papel else "sem papel"
        raise NaoAutorizado(f"Perfil {nome} não edita a Base do Score.")

    mencao = sessao.get(Mencao, id)
    if mencao is None:
        raise NaoEncontrado("Menção não encontrada.")

    if edicao.interlocutor_id is None:
        mencao.autor = None
    else:
        interlocutor = sessao.get(Interlocutor, edicao.interlocutor_id)
        if interlocutor is None:
            raise NaoEncontrado("Interlocutor não encontrado.")
        if mencao.instituicao_id is None or interlocutor.instituicao_id != mencao.instituicao_id:
            raise RegraViolada(
                "Este interlocutor não está cadastrado na instituição desta matéria."
            )
        mencao.autor = interlocutor.nome

    sessao.flush()
    return JornalistaDaMencao(autor=mencao.autor)
