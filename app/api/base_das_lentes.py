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
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.api.dependencias import UsuarioLogado, exigir_portal_score
from app.banco import repositorio_lentes, repositorio_score
from app.banco.sessao import SessaoDoPedido
from app.banco.tabelas_catalogo import BlocoTema, MacroTema, Tema
from app.banco.tabelas_score import Mencao, ScoreFonte
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.score import FiltroDeMencoes
from app.dominio.texto import normalizar

rotas = APIRouter(
    prefix="/api/score/base",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido

#: As lentes que têm menção. Mercado também — o recorte de imprensa econômica.
#: Institucional não: ela lê o CRM, que tem a Base dele.
LENTES_DA_BASE = ("imprensa", "mercado", "sociedade", "clientes")

#: O que se pode ordenar, e por qual coluna.
ORDENAVEIS = {
    "data": Mencao.data,
    "veiculo": Mencao.veiculo,
    "sentimento": Mencao.sentimento,
    "tier": Mencao.tier,
    "engajamento": Mencao.engajamento,
    "uf": Mencao.uf,
    "autor": Mencao.autor,
    "empresa": Mencao.unidade_texto,
}

TAMANHO_MAXIMO = 500


class MencaoDaBase(BaseModel):
    id: str
    data: date | None
    mes: str
    fonte: str
    fonte_no_calculo: bool
    veiculo: str | None
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
    """A busca livre: qualquer pedaço, sem acento, em todo campo de texto."""
    termo = f"%{normalizar(q)}%"
    campos = (
        Mencao.titulo_texto,
        Mencao.veiculo,
        Mencao.autor,
        Mencao.tema_texto,
        Mencao.subtema,
        Mencao.unidade_texto,
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
        autor=autor if (usuario.ve_diretorio or codigo != "imprensa") else None,
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
        .where(*onde)
    )
    total = sessao.scalar(select(func.count()).select_from(base.subquery())) or 0

    campo = ordenacao.lstrip("-")
    if campo not in ORDENAVEIS:
        raise RegraViolada(f"Ordenação inválida: {ordenacao!r}. Use {', '.join(ORDENAVEIS)}.")
    coluna = ORDENAVEIS[campo]
    ordem = coluna.desc().nulls_last() if ordenacao.startswith("-") else coluna.asc().nulls_last()

    consulta = (
        select(
            Mencao,
            ScoreFonte.nome,
            ScoreFonte.codigo,
            Mencao.tema_texto,
            Tema.nome,
            MacroTema.nome,
            BlocoTema.nome,
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .outerjoin(Tema, Tema.id == Mencao.tema_id)
        .outerjoin(MacroTema, MacroTema.id == Tema.macro_tema_id)
        .outerjoin(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
        .where(*onde)
        .order_by(ordem, Mencao.criado_em.desc(), Mencao.id)
        .offset((pagina - 1) * tamanho)
        .limit(tamanho)
    )
    desligadas = set(calibracao.fontes_desligadas or ())
    esconde_autor = codigo == "imprensa" and not usuario.ve_diretorio
    itens = [
        MencaoDaBase(
            id=str(m.id),
            data=m.data,
            mes=f"{m.mes:%Y-%m}",
            fonte=nome_da_fonte,
            fonte_no_calculo=codigo_da_fonte not in desligadas,
            veiculo=m.veiculo,
            tier=m.tier,
            sentimento=m.sentimento,
            atributo=m.atributo,
            tema=tema_mostrado,
            #: O PILAR DA LINHA: o do tema do cadastro, ou — o mais comum hoje —
            #: o tema que o fornecedor escreveu, que é o N1.
            tema_n1=n1 or m.tema_texto,
            tema_n2=n2,
            tema_n3=n3,
            subtema=m.subtema,
            empresa=m.unidade_texto,
            uf=m.uf,
            autor=None if esconde_autor else m.autor,
            perfil_autor=m.perfil_autor,
            engajamento=float(m.engajamento) if m.engajamento is not None else None,
            publico_alvo=m.publico_alvo,
            titulo=m.titulo_texto,
            link=m.link,
        )
        for m, nome_da_fonte, codigo_da_fonte, tema_mostrado, n3, n2, n1 in sessao.execute(consulta)
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

    esconde_autor = codigo == "imprensa" and not usuario.ve_diretorio
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
        empresas=distintos(Mencao.unidade_texto, 100),
        ufs=distintos(Mencao.uf),
        autores=[] if esconde_autor else distintos(Mencao.autor, 100),
        perfis=distintos(Mencao.perfil_autor),
    )
