"""Ligar a menção à concessionária do cadastro central.

POR QUE ISTO EXISTE. A menção guarda a concessionária como texto do fornecedor
(`mencao.unidade_texto`) e nada mais, enquanto a agenda do CRM
(`interacao.unidade_negocio_id`) usa o cadastro em todas as linhas — e o alcance
de cada pessoa é concedido POR NOME DE UNIDADE
(`filtros_sql.condicoes_de_escopo`). São as duas metades da mesma companhia sem
uma chave em comum.

E O TEXTO CRU JÁ CUSTA NA TELA DE HOJE. A dimensão "Concessionária" das lentes
agrupa por `unidade_texto`, e a mesma empresa chega em grafias diferentes
("Corsan" e "Companhia Riograndense de Saneamento (Corsan)"): duas barras no
gráfico e dois valores no filtro, e recortar por uma perde a outra.

O CADASTRO É A AUTORIDADE: aqui não se cria unidade. É a mesma regra de
`temas_da_mencao`, e pelo mesmo motivo — concessionária é a estrutura societária
da companhia, não fato do mundo que o fornecedor possa inventar. A diferença
para o veículo (`veiculos_da_imprensa`), onde o que falta nasce no upload, é
deliberada.

NUNCA SE ADIVINHA, E É ISSO QUE DEFINE O DESENHO. Há nome que o fornecedor manda
e corresponde a mais de uma linha do cadastro — "Águas do Rio" vale por duas
unidades, "Águas do Pará" por quatro blocos. Nenhum deles liga. Escolher um
bloco por ordem, por volume ou por qualquer outro critério seria inventar um
dado que a planilha não tem, e ele sairia depois num relatório por
concessionária como se fosse informação. A conferência mostra esses casos com as
opções do cadastro ao lado, e quem decide é gente: ou o fornecedor passa a
mandar o bloco, ou alguém declara o apelido.

O APELIDO É DADO, E NÃO CÓDIGO (`unidade_negocio_apelido`, migration `0099`). A
grafia longa não cabe como unidade nova — duplicaria a empresa no cadastro que o
CRM usa — e também não cabe no `apelidos` do `mapeamento_colunas`, que é POR
FONTE (o mesmo nome chega por duas fontes) e que REESCREVE `unidade_texto`,
apagando a palavra do fornecedor. Aqui o texto do fornecedor continua do lado e
o apelido só resolve a chave — o mesmo par que `instituicao_id`/`veiculo` e que
os três níveis da taxonomia já formam.

CASA POR `normalizar`, a chave de gravação do cadastro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.tabelas_catalogo import UnidadeNegocio, UnidadeNegocioApelido
from app.dominio.texto import normalizar

#: O SUFIXO QUE DISTINGUE IRMÃS DENTRO DA MESMA FAMÍLIA: `— Bloco C` e ` 4`.
#:
#: SERVE SÓ PARA A MENSAGEM, NUNCA PARA RESOLVER. Ele existe para a conferência
#: poder dizer "o cadastro tem quatro blocos, diga qual" em vez de "não
#: reconhecido" — que mandaria a pessoa procurar na planilha um nome que está
#: certo. Uma heurística que só melhora um texto não pode escolher um valor
#: errado; se um dia ela passar a resolver, esta frase deixa de valer.
#:
#: Até 19/10/2026 o cadastro tinha 3 famílias de verdade (Águas do Rio,
#: Ambiental Ceará, Águas do Pará, 8 das 29 unidades) — a consolidação daquele
#: dia (migration `0104`, por pedido) uniu cada uma numa linha só, e o
#: cadastro de produção ficou sem nenhuma família. A heurística continua de
#: pé para a PRÓXIMA vez que o cadastro ganhar nomes que colidam assim —
#: `tests/test_unidade_da_mencao.py` testa o mecanismo com um par fictício
#: (`duas_irmas`), não mais com um caso real.
_SUFIXO_DA_IRMA = re.compile(r"\s*(?:[—–-]\s*Bloco\s+\S+|\d+)\s*$", re.IGNORECASE)


def familia(nome: str) -> str:
    """A chave da família de uma unidade: `Águas do Pará — Bloco C` -> a do Pará."""
    return normalizar(_SUFIXO_DA_IRMA.sub("", nome))


@dataclass(frozen=True, slots=True)
class UnidadeNaoLigada:
    """Uma concessionária que a planilha traz e o cadastro não resolve."""

    #: O texto como o fornecedor o escreveu — é o que a pessoa vai procurar na
    #: planilha para corrigir, ou levar ao fornecedor.
    nome: str
    #: Quantas linhas do arquivo a citam. A lista ordena por aqui: o nome que
    #: aparece 15.019 vezes importa mais que o que aparece uma.
    mencoes: int
    #: AS UNIDADES DO CADASTRO QUE ESTE NOME PODE SER, quando são mais de uma.
    #: Vazio quer dizer "o cadastro não tem nada parecido", e são dois problemas
    #: com dois consertos: a lista cheia se resolve mandando o fornecedor
    #: informar o bloco (ou declarando um apelido), a lista vazia se resolve
    #: cadastrando a unidade — ou aceitando que aquela operação não é da Aegea.
    opcoes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Reconhecimento:
    """O que a subida FARIA com as concessionárias do arquivo, antes de gravar."""

    #: Quantas linhas achariam unidade no cadastro.
    ligadas: int
    #: Quantas linhas vieram sem concessionária nenhuma. Hoje são 37 em 104.670.
    sem_unidade: int
    nao_ligados: tuple[UnidadeNaoLigada, ...] = field(default_factory=tuple)

    @property
    def nao_ligadas(self) -> int:
        """Quantas linhas citam concessionária que o cadastro não resolve."""
        return sum(item.mencoes for item in self.nao_ligados)


@dataclass(frozen=True, slots=True)
class Cadastro:
    """As unidades ativas e os apelidos declarados, carregados de uma vez.

    DUAS CONSULTAS POR GRAVAÇÃO, e não uma por linha: são 29 unidades e 5
    apelidos, e o conjunto inteiro cabe em memória. É o mesmo motivo de
    `temas_da_mencao.Arvore` existir.

    SÓ AS ATIVAS, como lá: ligar a menção a uma unidade desativada a faria
    aparecer num recorte que a tela não oferece. Medido hoje: as 29 estão ativas,
    então o critério não tira nada — ele existe para quando tirar.
    """

    #: chave do nome (ou do apelido) → id da unidade.
    por_chave: dict[str, int] = field(default_factory=dict)
    #: chave da família → os NOMES das unidades dela, em ordem. Só para a
    #: mensagem da conferência; `resolver` não a consulta.
    familias: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def resolver(self, unidade_texto: object) -> int | None:
        """O id da concessionária, ou nulo. NUNCA ADIVINHA.

        UM PASSO SÓ, de propósito. A precedência de `temas_da_mencao` existe
        porque o fornecedor manda três níveis diferentes do mesmo assunto; aqui
        ele manda um nome de empresa, e ou o cadastro o conhece ou não. Um
        segundo passo por semelhança seria exatamente a adivinhação que a
        família acima se recusa a fazer — e `Águas de São Francisco` (132
        menções) coincidiria com `Águas de São Francisco do Sul` (7.528), que é
        outra operação, em outro estado.
        """
        if not unidade_texto:
            return None
        return self.por_chave.get(normalizar(str(unidade_texto)))


def cadastro(sessao: Session) -> Cadastro:
    """O cadastro ativo mais os apelidos declarados, em duas consultas.

    O APELIDO NÃO SUBSTITUI O NOME, ele se soma: as duas chaves caem no mesmo
    `por_chave`, e um apelido que repetisse um nome do cadastro seria um erro de
    dado — `tests/test_unidade_da_mencao.py` prende isso, porque é o cadastro que
    pode mudar, não este código.
    """
    nomes = sessao.execute(
        select(UnidadeNegocio.id, UnidadeNegocio.nome).where(
            UnidadeNegocio.ativo.is_(True)
        )
    ).all()

    familias: dict[str, list[str]] = {}
    for _, nome in nomes:
        familias.setdefault(familia(nome), []).append(nome)

    por_chave = {normalizar(nome): ident for ident, nome in nomes}
    for chave, ident in sessao.execute(
        select(
            UnidadeNegocioApelido.nome_normalizado,
            UnidadeNegocioApelido.unidade_negocio_id,
        )
    ):
        por_chave.setdefault(chave, ident)

    return Cadastro(
        por_chave=por_chave,
        #: SÓ AS FAMÍLIAS COM IRMÃ, porque é a pluralidade que a conferência
        #: precisa anunciar. Unidade sozinha na família não é opção a escolher.
        familias={
            chave: tuple(sorted(membros))
            for chave, membros in familias.items()
            if len(membros) > 1
        },
    )


def reconhecer(sessao: Session, unidades: dict[str, int]) -> Reconhecimento:
    """O que o cadastro resolve das concessionárias do arquivo. NÃO GRAVA NADA.

    `unidades` é texto cru do fornecedor → quantas linhas o citam, e é o mesmo
    contrato de `temas_da_mencao.reconhecer`: a conferência precisa do número
    ANTES de alguém confirmar.
    """
    resolvedor = cadastro(sessao)

    ligadas = 0
    sem_unidade = unidades.get("", 0)
    nao_ligados: list[UnidadeNaoLigada] = []
    for texto, quantas in unidades.items():
        if not texto.strip():
            continue
        if resolvedor.resolver(texto) is not None:
            ligadas += quantas
            continue
        nao_ligados.append(
            UnidadeNaoLigada(
                nome=texto,
                mencoes=quantas,
                opcoes=resolvedor.familias.get(familia(texto), ()),
            )
        )
    #: PELO VOLUME, e empate pelo nome para a lista não dançar entre duas
    #: aberturas — o mesmo critério dos assuntos.
    nao_ligados.sort(key=lambda item: (-item.mencoes, item.nome))
    return Reconhecimento(
        ligadas=ligadas,
        sem_unidade=sem_unidade,
        nao_ligados=tuple(nao_ligados),
    )
