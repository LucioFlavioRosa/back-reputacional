"""A fila de revisão das três abas de Cadastro compartilhado.

PEDIDO DO DONO DO PRODUTO (11/10/2026), e ele o cobrou duas vezes:

  "Dentro de cada uma das 3 abas de Cadastro compartilhado, uma aba específica
  para cadastros que precisam de serem revisados para serem consolidados na base
  de instituições, contatos, temas e representantes da Aegea. Assim o
  profissional consegue subir a planilha sem problemas e pode revisar depois, e
  inclusive pode ser trabalho de outra pessoa. Queremos dar padronização, mas com
  menor impacto."

A COLUNA EXISTIA E NINGUÉM A LIA. `pendente_de_revisao` nasceu na `0085` e
`motivo_da_revisao` na `0086`; a importação de agendas e a ingestão de menções já
marcam os cinco nascimentos. Sem este módulo o alerta existia no banco e nenhuma
tela o mostrava — que é o pior estado possível, porque a importação PAROU de
travar contando com uma revisão que não acontecia.

QUATRO TABELAS PARA TRÊS ABAS, e o mapa é exato: "Instituições e Contatos" é
`instituicao` + `interlocutor`, "Temas" é `tema`, "Representantes Aegea" é
`pessoa_aegea`. É o mesmo mapa que `tests/test_fila_de_revisao.py` já afirma.

UMA FORMA SÓ DE PENDÊNCIA para os quatro, e não quatro payloads: a aba mostra
uma lista, e o que ela precisa saber é quem, por quê, e o bastante para
distinguir dois registros parecidos. O resto já está na tela de cadastro ao
lado, que é onde a correção se faz.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_stakeholders import Instituicao, Interlocutor, PessoaAegea
from app.dominio.erros import NaoEncontrado
from app.dominio.frentes import ROTULO_DO_TIPO_DE_INSTITUICAO


@dataclass(frozen=True)
class Pendente:
    """Um cadastro que nasceu de planilha e ninguém consolidou ainda."""

    #: Texto, e não `UUID | int`: três das quatro tabelas têm chave UUID e
    #: `tema` tem chave inteira. Quem consolida devolve o mesmo texto que
    #: recebeu, e a rota reconverte — ver `consolidar`.
    id: str
    #: O `__tablename__`, que é o que a rota de consolidação recebe de volta.
    tipo: str
    nome: str
    #: POR QUE ESTE REGISTRO ESPERA REVISÃO. Nulo é "nasceu de planilha", sem
    #: mais nada a dizer — o caso comum, e o front escreve a frase genérica.
    motivo: str | None
    #: O QUE DISTINGUE ESTE DE UM REGISTRO DE NOME PARECIDO, e esta linha é a
    #: razão de a fila ser legível.
    #:
    #: O motivo mais frequente hoje é "apareceu em 2 instituições na mesma
    #: planilha" — que CRIA DOIS CADASTROS COM O MESMO NOME, de propósito. Sem a
    #: instituição ao lado, a aba mostraria "Artur Santa" duas vezes, com o
    #: mesmo motivo, e quem revisa não teria como saber qual é o do Banco XP e
    #: qual é o da XP Asset. A fila ficaria ilegível justamente no caso que a
    #: fez existir.
    contexto: str | None
    criado_em: datetime


@dataclass(frozen=True)
class AbaDaFila:
    """Uma das três abas, com o que ela tem para revisar."""

    #: O id que o front usa — `instituicoes` | `assuntos` | `porta_vozes`. São
    #: os mesmos de `PortalDoCadastroCompartilhado.tsx`, para a aba de revisão
    #: nascer dentro da aba certa sem tradução no meio.
    id: str
    rotulo: str
    pendentes: list[Pendente]


def _contexto_da_instituicao(linha: Instituicao, _nomes: dict[Any, str]) -> str | None:
    """O tipo e a praça: é o que separa um veículo de um investidor homônimo.

    É o caso que o dono do produto nomeou — "se o 'valor' for classificado como
    financeiro e em outro momento 'o valor' for registrado como veículo". Os dois
    podem estar na fila ao mesmo tempo, e o tipo é o que os distingue.
    """
    partes = [ROTULO_DO_TIPO_DE_INSTITUICAO.get(linha.tipo, linha.tipo)]
    if linha.uf:
        partes.append(linha.uf)
    return " · ".join(partes)


def _contexto_do_interlocutor(
    linha: Interlocutor, nomes: dict[Any, str]
) -> str | None:
    """A instituição, e é a linha mais importante deste módulo.

    SEM ELA A FILA É ILEGÍVEL no caso que a criou. Ver `Pendente.contexto`.

    `nomes` VEM PRONTO, e não de um `relationship`: `Interlocutor` tem
    `instituicao_id` e nenhuma relação mapeada, então um acesso por linha seria
    uma consulta por linha. `listar` carrega os nomes numa consulta só.
    """
    partes = []
    nome_da_casa = nomes.get(linha.instituicao_id)
    if nome_da_casa:
        partes.append(nome_da_casa)
    if linha.cargo:
        partes.append(linha.cargo)
    return " · ".join(partes) or None


def _contexto_do_tema(linha: Tema, _nomes: dict[Any, str]) -> str | None:
    """O nível, que é o que diz se o tema entra nos KPIs."""
    return linha.nivel or None


def _contexto_da_pessoa(linha: PessoaAegea, _nomes: dict[Any, str]) -> str | None:
    """Cargo, e se é porta-voz — a distinção que a tela de Representantes faz."""
    partes = [linha.cargo] if linha.cargo else []
    partes.append("Porta-voz" if linha.eh_porta_voz else "Equipe")
    return " · ".join(partes)


#: As quatro tabelas, cada uma com a aba a que pertence e como se descreve.
#:
#: A ORDEM DENTRO DA ABA É A DESTA TUPLA: instituição antes de interlocutor,
#: porque o interlocutor APONTA para a instituição. Quem revisa "Nikolau Muller
#: — Leto Capital" precisa que "Leto Capital" já esteja decidida; a ordem
#: inversa obriga a voltar. É o mesmo argumento que ordena as abas em
#: `PortalDoCadastroCompartilhado.tsx`.
_TABELAS: tuple[tuple[str, str, type, Any], ...] = (
    ("instituicoes", "Instituições e Contatos", Instituicao, _contexto_da_instituicao),
    ("instituicoes", "Instituições e Contatos", Interlocutor, _contexto_do_interlocutor),
    ("assuntos", "Temas", Tema, _contexto_do_tema),
    ("porta_vozes", "Representantes Aegea", PessoaAegea, _contexto_da_pessoa),
)

#: Nome da tabela → a classe, para a consolidação resolver o que recebeu da URL.
#:
#: DERIVADO DE `_TABELAS`, e não uma segunda lista escrita à mão: uma tabela
#: acrescentada à fila e esquecida aqui apareceria na listagem e recusaria a
#: consolidação — a aba mostraria um registro que não sai.
POR_TIPO: dict[str, type] = {tabela.__tablename__: tabela for _, _, tabela, _ in _TABELAS}


def listar(sessao: Session) -> list[AbaDaFila]:
    """O que cada aba tem para revisar, na ordem em que se revisa.

    `criado_em desc` E DEPOIS O NOME. Mais novo primeiro porque o pedido é
    explícito sobre a sequência — "o profissional consegue subir a planilha sem
    problemas e pode revisar depois" —, e o que ele revisa é o que ACABOU de
    subir. O nome desempata: uma importação cria tudo no mesmo instante, e sem o
    segundo critério a ordem de 304 linhas ficaria a cargo do Postgres, mudando
    entre dois carregamentos da mesma tela.
    """
    abas: dict[str, AbaDaFila] = {}
    for id_da_aba, rotulo, tabela, contexto in _TABELAS:
        aba = abas.setdefault(id_da_aba, AbaDaFila(id_da_aba, rotulo, []))
        consulta = (
            select(tabela)
            .where(tabela.pendente_de_revisao.is_(True))
            .order_by(tabela.criado_em.desc(), tabela.nome)
        )
        linhas = list(sessao.scalars(consulta))
        nomes = _nomes_das_casas(sessao, linhas)
        aba.pendentes.extend(
            Pendente(
                id=str(linha.id),
                tipo=tabela.__tablename__,
                nome=linha.nome,
                motivo=linha.motivo_da_revisao,
                contexto=contexto(linha, nomes),
                criado_em=linha.criado_em,
            )
            for linha in linhas
        )
    return list(abas.values())


def _nomes_das_casas(sessao: Session, linhas: list) -> dict[Any, str]:
    """id da instituição → nome, numa consulta só, e só quando faz diferença.

    UMA CONSULTA PARA A FILA INTEIRA, e não uma por linha: 129 interlocutores
    pendentes seriam 129 idas ao banco para montar uma lista. É o mesmo defeito
    que `indice_completo` consertou na importação, e que uma revisão pegou lá.
    """
    ids = {
        linha.instituicao_id
        for linha in linhas
        if getattr(linha, "instituicao_id", None) is not None
    }
    if not ids:
        return {}
    return dict(
        sessao.execute(
            select(Instituicao.id, Instituicao.nome).where(Instituicao.id.in_(ids))
        ).all()
    )


def consolidar(sessao: Session, *, tipo: str, id: str) -> tuple[Pendente, bool]:
    """"Conferi este, está certo" — tira o registro da fila.

    DEVOLVE SE JÁ ESTAVA FORA, e não um erro. A fila é trabalho de equipe pelo
    próprio pedido — "inclusive pode ser trabalho de outra pessoa" —, então duas
    pessoas na mesma aba é o caso NORMAL, não a exceção. O estado final é o que
    as duas queriam; recusar a segunda seria inventar um conflito onde não há
    desacordo. O front usa o booleano para dizer "outra pessoa já consolidou
    este" em vez de piscar uma confirmação falsa.

    NÃO MEXE NO CADASTRO. Consolidar é afirmar que o registro está certo como
    está; corrigi-lo é a tela de cadastro ao lado, que já existe e já sabe
    validar. Juntar as duas coisas aqui duplicaria essa validação.
    """
    tabela = POR_TIPO.get(tipo)
    if tabela is None:
        raise NaoEncontrado(
            f"'{tipo}' não é um cadastro da fila de revisão. "
            f"São {', '.join(sorted(POR_TIPO))}."
        )

    linha = _buscar(sessao, tabela, id)
    if linha is None:
        raise NaoEncontrado(f"Cadastro {id} não encontrado em {tipo}.")

    ja_estava = not linha.pendente_de_revisao
    linha.pendente_de_revisao = False
    #: O MOTIVO SAI COM A PENDÊNCIA. Ele é a pergunta que a fila fazia; mantê-lo
    #: num registro consolidado deixaria "apareceu em 2 instituições — confirme
    #: se são a mesma pessoa" grudado num cadastro sobre o qual alguém JÁ
    #: confirmou, pronto para reaparecer na próxima tela que o leia.
    linha.motivo_da_revisao = None
    sessao.flush()

    _, _, _, contexto = next(t for t in _TABELAS if t[2] is tabela)
    pendente = Pendente(
        id=str(linha.id),
        tipo=tipo,
        nome=linha.nome,
        motivo=None,
        contexto=contexto(linha, _nomes_das_casas(sessao, [linha])),
        criado_em=linha.criado_em,
    )
    return pendente, ja_estava


def _buscar(sessao: Session, tabela: type, id: str):
    """`tema` tem chave inteira e as outras três têm UUID.

    A CHAVE É CONVERTIDA AQUI, ANTES DE IR AO BANCO, e isto não é zelo: o
    Postgres recusa `'nao-sou-uuid'::UUID` com `DataError` e ABORTA A TRANSAÇÃO
    DO PEDIDO INTEIRO — 500 onde o certo é 404, e qualquer coisa que viesse
    depois na mesma sessão falharia também.

    EU TINHA ESCRITO SÓ O `int(id)`, achando que cobria os dois, e
    `test_o_id_que_nao_e_do_tipo_da_404_e_nao_500` mostrou a diferença: o inteiro
    falha em Python, na conversão; o UUID passava por `sessao.get` intacto e só
    falhava no servidor. Dois erros parecidos, dois lugares diferentes.
    """
    try:
        chave: Any = int(id) if tabela is Tema else UUID(id)
    except (ValueError, TypeError, AttributeError):
        return None
    return sessao.get(tabela, chave)
