"""O mesmo ator cadastrado duas vezes — a fila, e a fusão.

A DECISÃO DE NEGÓCIO. "O Valor Econômico é uma empresa grande que está na base
de imprensa; caso tenhamos Valor Econômico no CRM, empresa e rede social, vamos
consultar o mesmo perfil?" — "deveria ser um único cadastro que vem de Cadastro
compartilhado".

TRÊS CAMADAS, e cada uma faz o que a anterior não pode:

1. A INGESTÃO não cria o par: `veiculos_da_imprensa.reconhecer` procura em
   qualquer tipo quando quem fala é perfil de rede.
2. A `0077` fundiu os HOMÔNIMOS EXATOS que a versão antiga gravou — nome igual
   por `nome_normalizado` não pede julgamento.
3. ESTE MÓDULO cuida dos que só casam depois de tirar pontuação e espaço. Ali a
   semelhança NÃO prova identidade — `Diário SM` e `Diários M` casam assim, e
   `bmc.news` casa com DOIS veículos —, então quem decide é gente, e o que a
   pessoa decidir fica guardado.

A CHAVE DA COMPARAÇÃO é `nome_normalizado` sem nada que não seja letra ou
dígito: o fornecedor de redes escreve o handle (`valoreconomico`, `bmc.news`) e
o clipping escreve o nome (`Valor Econômico`). É regra de BUSCA, para montar a
fila de perguntas — nunca de gravação.

O QUE ESTE MÓDULO NÃO FAZ: fundir sozinho. Juntar dois dossiês não tem volta.
"""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.repositorio_score import so_interacoes_visiveis
from app.banco.tabelas_interacoes import InteracaoRegistro
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte
from app.banco.tabelas_stakeholders import (
    AtorDistinto,
    Instituicao,
    InstituicaoApelido,
    Interlocutor,
)
from app.casos_de_uso.veiculos_da_imprensa import LISTAS_DE_VEICULOS, nomes_da_lista
from app.dominio.erros import NaoEncontrado, RegraViolada
from app.dominio.texto import (
    SEMELHANCA_MINIMA,
    achatar_para_comparar,
)

#: O TIPO QUE SÓ ENTRA EM OUTRO CADASTRO, e não mais "o tipo que a fila olha".
#:
#: A FILA PASSOU A OLHAR TODOS (11/10/2026), pelo princípio do dono do produto:
#: "qualquer fonte tem acesso à mesma base... o BTG continua sendo um só". Este
#: tipo ficou por uma razão estreita e real: só um `perfil_rede` pode estar ligado
#: a uma pessoa do CRM (CHECK `instituicao_pessoa_so_de_perfil`), e é essa ligação
#: que tira um cadastro da fila.
TIPO_DE_ORIGEM = "perfil_rede"

#: A CHAVE DE SEMELHANÇA E O CORTE VÊM DO DOMÍNIO (`dominio/texto.py`), e não
#: moram aqui: a INGESTÃO precisa deles para não CRIAR o par, e esta fila para
#: PERGUNTAR sobre ele. Eram duas cópias, e o comentário deste módulo já avisava
#: contra "a terceira cópia da mesma regra" — medido: a ingestão buscava por
#: `normalizar`, que preserva o espaço, e criava `Neo Feed` ao lado de `Neofeed`.
#:
#: `achatar_para_comparar` e `SEMELHANCA_MINIMA` seguem alcançáveis por este módulo
#: (`atores_duplicados.achatar_para_comparar`), porque o import os põe no espaço de
#: nomes dele — os testes e a API continuam lendo daqui.


#: O QUE O SOBREVIVENTE HERDA de quem sai, quando ele não tem.
#:
#: SEM ISTO A FUSÃO PERDE CAMPO: ela move as chaves estrangeiras e apaga a
#: linha, então um `investidor` com `tier` e categoria de público sai levando os
#: dois. E num par de nome idêntico e zero menções a perda é por SORTEIO, porque
#: quem sai é decidido pelo UUID.
#:
#: `cargo` NÃO ESTÁ AQUI, e é o único campo de CLASSIFICAÇÃO de fora: o CHECK
#: `instituicao_cargo_so_de_perfil` não deixa um veículo ter cargo, então
#: herdá-lo estouraria o banco. A perda dele está dita no docstring.
#:
#: `nome` E `tipo` TAMBÉM NÃO: são a identidade do sobrevivente, e trocá-los
#: faria a fusão virar renomeação — outro gesto, com outras consequências.
CAMPOS_QUE_O_SOBREVIVENTE_HERDA = (
    "nome_completo",
    "esfera_id",
    "uf",
    "tier",
    "categoria_publico_id",
    "subcategoria_publico_id",
)


#: A ORIGEM DE UM CADASTRO QUE NÃO É MENÇÃO: o relacionamento registrado no CRM.
#:
#: As outras origens são códigos de LENTE (`imprensa`, `mercado`, `sociedade`,
#: `clientes`, `institucional`), que saem de `mencao -> score_fonte -> lente`. A
#: interação do CRM mora em `interacao_registro` e não em `mencao`, então ela não
#: tem lente para dizer — e dizer `institucional` aqui misturaria "tem interação
#: registrada" com "tem menção na lente institucional", que são coisas diferentes
#: para quem decide se os dois cadastros são o mesmo ator.
ORIGEM_DO_CRM = "crm"


@dataclass(frozen=True)
class Candidato:
    """Um cadastro que PODE ser o mesmo ator do perfil."""

    id: uuid.UUID
    nome: str
    tipo: str
    mencoes: int
    #: DE ONDE VÊM OS REGISTROS DESTE CADASTRO — ver `_origens_por_instituicao`.
    origens: tuple[str, ...] = ()


@dataclass(frozen=True)
class Duplicado:
    """Um cadastro que vai SAIR, e os cadastros com que ele se parece."""

    id: uuid.UUID
    nome: str
    #: O TIPO DE QUEM VAI SAIR. Sem ele a tela escreve um tipo fixo, e num par
    #: entidade+órgão ela diz que vai apagar um perfil de rede — quem decide lê o
    #: tipo errado do registro que desaparece.
    tipo: str
    cargo: str | None
    mencoes: int
    candidatos: tuple[Candidato, ...]
    #: DE ONDE VÊM OS REGISTROS DESTE CADASTRO — ver `_origens_por_instituicao`.
    origens: tuple[str, ...] = ()


def _mencoes_por_instituicao(sessao: Session) -> dict[uuid.UUID, int]:
    linhas = sessao.execute(
        select(Mencao.instituicao_id, func.count())
        .where(Mencao.instituicao_id.is_not(None))
        .group_by(Mencao.instituicao_id)
    )
    return {instituicao: quantas for instituicao, quantas in linhas}


def _origens_por_instituicao(sessao: Session) -> dict[uuid.UUID, tuple[str, ...]]:
    """De onde vêm os registros de cada cadastro: as lentes, e o CRM.

    O PEDIDO DO DONO DO PRODUTO, na letra: "o Valor Econômico pode vir de vários
    meios, pode vir do crm, pode vir de mídias sociais, pode vir de mercado,
    enfim, pode ter várias fontes distintas, mas a instituição é a mesma. Então
    isso deve ficar bem claro".

    POR QUE NA FILA. Quem decide se dois cadastros são o mesmo ator está olhando
    dois nomes parecidos e duas contagens. Falta o que EXPLICA a duplicata: um
    lado chegou pelo clipping e o outro pelo social listening. Com as origens na
    linha, a pergunta "são o mesmo?" passa a ter a evidência ao lado dela.

    DUAS LEITURAS, e não uma: a menção tem lente (por `score_fonte`) e a
    interação do CRM não tem — ver `ORIGEM_DO_CRM`. Juntá-las num `union` daria
    uma coluna que mente sobre o que mediu.

    O CUSTO É RUÍDO AQUI: a fila compara os nomes par a par em memória, e
    `ratio()` é caro. Dois agregados sobre índice não mudam essa ordem de
    grandeza.
    """
    origens: dict[uuid.UUID, set[str]] = {}

    das_mencoes = sessao.execute(
        select(Mencao.instituicao_id, Lente.codigo)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .where(Mencao.instituicao_id.is_not(None))
        .distinct()
    )
    for instituicao, lente in das_mencoes:
        origens.setdefault(instituicao, set()).add(lente)

    #: SÓ AS INTERAÇÕES QUE PODEM SER LIDAS, e isto é conserto de achado ALTA de
    #: revisão. A primeira versão marcava `crm` para QUALQUER `interacao_registro`,
    #: e esta listagem exige apenas `UsuarioQueVeDiretorio`: quem vê o diretório
    #: passava a inferir que a Aegea tem relacionamento com uma instituição mesmo
    #: quando a agenda foi tirada da vista, arquivada ou marcada como sensível.
    #:
    #: `so_interacoes_visiveis` É A REGRA DA CASA para isso, e o docstring dela diz
    #: por quê: o nome da instituição de uma agenda é "a informação que o CRM
    #: guarda com mais cuidado". Reescrever o filtro aqui seria a sétima cópia.
    do_crm = sessao.execute(
        select(InteracaoRegistro.instituicao_id)
        .where(
            InteracaoRegistro.instituicao_id.is_not(None),
            *so_interacoes_visiveis(),
        )
        .distinct()
    )
    for (instituicao,) in do_crm:
        origens.setdefault(instituicao, set()).add(ORIGEM_DO_CRM)

    #: ORDENADAS, para a linha da tela não trocar de ordem entre duas aberturas —
    #: a mesma razão do desempate por nome em `listar`.
    return {quem: tuple(sorted(quais)) for quem, quais in origens.items()}


def _vizinhos(cadastros: list[Instituicao]) -> dict[uuid.UUID, list[Instituicao]]:
    """Cada cadastro e os outros que PODEM ser o mesmo ator.

    DUAS CAMADAS, e a segunda é o pedido do dono do produto:

    1. CHAVE ACHATADA IGUAL — `cnnbrasil` e `CNN Brasil`, `Neofeed` e `Neo Feed`.
    2. CHAVE PARECIDA, acima de `SEMELHANCA_MINIMA` — o caso "Valor" contra "o
       Valor", que a camada 1 não vê porque "valor" e "ovalor" são chaves
       diferentes.

    O PRÉ-FILTRO POR TAMANHO não é otimização gratuita: são milhares de nomes,
    logo milhões de pares, e `ratio()` é caro. Duas chaves cujo tamanho difere
    mais de 30% não alcançam 0,90 — a razão é limitada por `2*min/(a+b)` —, então
    descartá-las antes não muda nenhuma resposta. `real_quick_ratio` e
    `quick_ratio` são os mesmos atalhos que `difflib.get_close_matches` usa por
    dentro.
    """
    chaves = [(c, achatar_para_comparar(c.nome)) for c in cadastros]
    perto: dict[uuid.UUID, list[Instituicao]] = {c.id: [] for c in cadastros}

    #: `autojunk=False`: o heurístico de "caractere popular" do `difflib` foi feito
    #: para arquivos de código, e em textos curtos ele descarta letra comum e muda
    #: a razão sem motivo. Os nomes aqui têm 3 a 40 caracteres.
    medida = difflib.SequenceMatcher(autojunk=False)
    for i, (um, chave_um) in enumerate(chaves):
        if not chave_um:
            #: Nome que normaliza para vazio — acontece com nome só de emoji. Sem
            #: chave não há com que comparar, e comparar vazio com vazio casaria
            #: todos eles entre si.
            continue
        medida.set_seq2(chave_um)
        for outro, chave_outro in chaves[i + 1 :]:
            if not chave_outro:
                continue
            if chave_um == chave_outro:
                perto[um.id].append(outro)
                perto[outro.id].append(um)
                continue
            maior = max(len(chave_um), len(chave_outro))
            if abs(len(chave_um) - len(chave_outro)) > maior * 0.3:
                continue
            medida.set_seq1(chave_outro)
            if (
                medida.real_quick_ratio() < SEMELHANCA_MINIMA
                or medida.quick_ratio() < SEMELHANCA_MINIMA
                or medida.ratio() < SEMELHANCA_MINIMA
            ):
                continue
            perto[um.id].append(outro)
            perto[outro.id].append(um)
    return perto


def listar(sessao: Session) -> list[Duplicado]:
    """A fila de perguntas: cadastros que podem ser o mesmo ator.

    QUALQUER TIPO. A fila nasceu da ingestão de redes e olhava só `perfil_rede`
    como origem; o princípio do dono do produto é "uma base só — qualquer fonte
    tem acesso à mesma base de instituições e interlocutores". Por tipo, os pares
    veículo+veículo, entidade+órgão e entidade+investidor ficavam fora.

    E O HOMÔNIMO EXATO TAMBÉM ENTRA. Deixá-lo fora supõe que só migration cria
    duplicata exata, e não é verdade: a ingestão as recria, e gente as cria no
    CRM — e nenhuma migration vai fundi-las, porque "quem decide como enquadrar é
    o time".

    FORA DA FILA, e cada exclusão por um motivo diferente:

    * o par que alguém JÁ DECIDIU que é outro ator (`ator_distinto`) — sem isso a
      fila nunca chega a zero;
    * o perfil LIGADO A UMA PESSOA do CRM, porque o sobrevivente não pode herdar
      a ligação (CHECK `instituicao_pessoa_so_de_perfil`) e desfazer escolha
      humana não é fusão, é perda.

    EM MEMÓRIA, e não em SQL: a chave de semelhança é a mesma função que a
    ingestão usa, e reescrevê-la em `regexp_replace` seria a terceira cópia da
    mesma regra — o jeito conhecido de divergir em silêncio. O cadastro todo são
    alguns milhares de linhas de duas colunas.
    """
    #: O CADASTRO ATIVO INTEIRO. Quem fica de fora da fila fica de fora no
    #: laço abaixo, onde a razão de cada exclusão está escrita.
    cadastros = list(
        sessao.scalars(select(Instituicao).where(Instituicao.ativo.is_(True)))
    )
    perto = _vizinhos(cadastros)

    decididos = {
        (par.esquerda, par.direita) for par in sessao.scalars(select(AtorDistinto))
    }
    mencoes = _mencoes_por_instituicao(sessao)
    origens = _origens_por_instituicao(sessao)

    fila: list[Duplicado] = []
    for perfil in cadastros:
        #: SÓ O PERFIL LIGADO A UMA PESSOA DO CRM fica fora, e o tipo aparece aqui
        #: por isso: a ligação só existe em `perfil_rede` (CHECK
        #: `instituicao_pessoa_so_de_perfil`), e o sobrevivente não pode herdá-la.
        if perfil.tipo == TIPO_DE_ORIGEM and perfil.interlocutor_id is not None:
            continue
        candidatos = tuple(
            Candidato(
                id=outro.id,
                nome=outro.nome,
                tipo=outro.tipo,
                mencoes=mencoes.get(outro.id, 0),
                origens=origens.get(outro.id, ()),
            )
            for outro in perto[perfil.id]
            if ordenar_o_par(perfil.id, outro.id) not in decididos
            and _esta_do_lado_que_pergunta(perfil, outro, mencoes)
        )
        if candidatos:
            fila.append(
                Duplicado(
                    id=perfil.id,
                    nome=perfil.nome,
                    tipo=perfil.tipo,
                    cargo=perfil.cargo,
                    mencoes=mencoes.get(perfil.id, 0),
                    candidatos=tuple(sorted(candidatos, key=lambda c: -c.mencoes)),
                    origens=origens.get(perfil.id, ()),
                )
            )
    return sorted(fila, key=lambda d: d.nome.lower())


def _esta_do_lado_que_pergunta(
    perfil: Instituicao, outro: Instituicao, mencoes: dict[uuid.UUID, int]
) -> bool:
    """A pergunta aparece UMA VEZ, e ancorada em quem vai sumir.

    Quando os dois lados são perfil de rede, os dois cabem no papel de "quem
    pergunta" — e a fila traz a mesma dúvida duas vezes, em dois pontos da lista
    alfabética. Responder uma resolve as duas, mas quem abre a tela lê o dobro do
    trabalho que existe, e o contador mente.

    QUATRO DEGRAUS, nesta ordem:

    1. O PERFIL DE REDE SOME ANTES de um cadastro curado. A `0077` já tinha
       gravado a razão: "quem sobrevive é o veículo, e não o perfil: ele é a
       linha curada, com categoria, subcategoria, UF e frente". Sem este degrau,
       num par de zero menções o desempate pelo nome manda a pergunta para o
       VEÍCULO.
    2. DEPOIS, QUEM TEM MENOS MENÇÕES — a linha com história sobrevive.
    3. DEPOIS O NOME, para a escolha não trocar de lado entre duas aberturas da
       tela.
    4. E O `id`, QUE FECHA A ORDEM.

    O QUARTO DEGRAU NÃO É ZELO. Com o desempate em `(menções, nome)`, dois
    cadastros não-`perfil_rede` com as mesmas menções e o MESMO nome textual
    calculam `x < x` = False DOS DOIS LADOS: ninguém pergunta, e o par sai da
    fila em silêncio. Era o caso das duplicatas de nome idêntico e zero menções
    criadas no CRM — invisíveis numa fila que dizia duzentas perguntas.

    O `id` É ÚNICO POR CONSTRUÇÃO, então `(menções, nome, id)` é ordem TOTAL:
    para qualquer par distinto, exatamente um lado pergunta. É o que faz a
    pergunta aparecer UMA vez — nem zero, nem duas.
    """
    de_rede = perfil.tipo == TIPO_DE_ORIGEM
    outro_de_rede = outro.tipo == TIPO_DE_ORIGEM
    if de_rede != outro_de_rede:
        return de_rede
    return (mencoes.get(perfil.id, 0), perfil.nome, str(perfil.id)) < (
        mencoes.get(outro.id, 0),
        outro.nome,
        str(outro.id),
    )


def ordenar_o_par(um: uuid.UUID, outro: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """O par sem lado, sempre na mesma ordem.

    Dizer que A é diferente de B é dizer que B é diferente de A. Guardado
    ordenado, é a chave primária que recusa a repetição — a aplicação não
    procura nas duas direções. Ver migration `0078`.
    """
    return (um, outro) if str(um) < str(outro) else (outro, um)


def _buscar(sessao: Session, qual: uuid.UUID) -> Instituicao:
    registro = sessao.get(Instituicao, qual)
    if registro is None:
        raise NaoEncontrado("Cadastro nao encontrado.")
    return registro


def fundir(
    sessao: Session,
    *,
    que_sai_id: uuid.UUID,
    sobrevivente_id: uuid.UUID,
    contra_a_proposta: bool = False,
) -> Instituicao:
    """Um cadastro entra no outro, com as menções dele.

    QUEM SOBREVIVE É ESCOLHA DE QUEM CHAMA, e a fila propõe: a regra de
    `_esta_do_lado_que_pergunta` ancora a pergunta em quem deve sair — o perfil
    de rede antes de um cadastro curado, depois quem tem menos menções.

    `contra_a_proposta` É A ESCOLHA DE GENTE, e é o pedido do dono do produto:
    "além de mostrar quais podem se juntar temos que dizer qual é o real para ser
    considerado na unificação".

    POR QUE UM PARÂMETRO E NÃO TIRAR A GUARDA. A proposta da fila está certa
    quase sempre — é ela que impede fundir a linha com história dentro da linha
    crua — e protege o `curl` distraído, que continua levando 422. O que ela não
    pode fazer é ter a última palavra: só quem conhece o ator sabe que o cadastro
    certo é o do CRM, e não o que acumulou menções. A guarda é o PADRÃO, e não
    proibição.

    O QUE A ESCOLHA CONTRÁRIA CUSTA, e a tela tem de dizer: o sobrevivente mantém
    o NOME dele — `nome` e `tipo` não estão em
    `CAMPOS_QUE_O_SOBREVIVENTE_HERDA`, porque trocá-los faria a fusão virar
    renomeação. Escolher o handle `valoreconomico` como o real deixa o cadastro
    chamado `valoreconomico`, com as menções do Valor Econômico dentro. A
    curadoria em si NÃO se perde: categoria, subcategoria, tier, esfera e UF são
    herdados quando o sobrevivente não os tem.

    QUALQUER TIPO SAI. Exigindo `perfil_rede` de quem sai, a fila mostra pares
    `veiculo`+`veiculo` e `entidade`+`orgao` cuja única resposta aceita pelo
    servidor é "são distintos" — uma pergunta cuja resposta certa é recusada, que
    é pior que não perguntar. A assimetria que isso protegia — fundir um veículo
    com muitas menções dentro de um perfil com duas seria perder a curadoria —
    continua garantida pela ORDEM DA FILA, e não por um `if` de tipo.

    O SOBREVIVENTE HERDA O QUE ELE NÃO TEM (`CAMPOS_QUE_O_SOBREVIVENTE_HERDA`), e
    o CONFLITO RECUSA com 422 dizendo quais campos divergem. Sem isso as chaves
    estrangeiras passam e a linha é apagada com a categoria de público e o tier
    dela dentro.

    O QUE SE PERDE, dito em voz alta:

    * o `cargo` de quem sai — o CHECK `instituicao_cargo_so_de_perfil` existe de
      propósito, e um jornal não tem cargo;
      o nome NÃO sai de circulação: QUANDO ELE DIFERE do nome do sobrevivente,
      vira APELIDO do cadastro que fica (`instituicao_apelido`, migration
      `0102`), e é por isso que a ingestão continua reconhecendo o texto que o
      fornecedor manda todo mês. Sem o apelido, o veículo nasceria de novo na
      subida seguinte;
    * `criado_em`, que é a data da linha que sai e não diz nada sobre a que fica.

    A PENDÊNCIA DE REVISÃO PASSA PARA O SOBREVIVENTE que ainda não está
    pendente, com o motivo de quem sai. Se ele JÁ está pendente, o motivo dele
    fica — são duas pendências e uma frase só. Ver abaixo.
    """
    if que_sai_id == sobrevivente_id:
        raise RegraViolada("Um cadastro nao funde com ele mesmo.")

    perfil = _buscar(sessao, que_sai_id)
    sobrevivente = _buscar(sessao, sobrevivente_id)

    #: A DIREÇÃO É CONFERIDA PELA MESMA REGRA DA FILA, e não por um `if` de tipo.
    #:
    #: O QUE ESTA GUARDA IMPEDE: fundir a linha curada dentro da linha crua. O
    #: veículo é a linha com categoria, subcategoria, UF e frente, e com o nome
    #: escrito por gente; fundi-lo dentro do handle do fornecedor perderia a
    #: curadoria, e quem clica numa tela de duplicados não está pedindo isso.
    #:
    #: E A GUARDA PRECISA EXISTIR NO SERVIDOR: a ordem da fila é a TELA, e
    #: esconder o botão é conveniência — um `curl` basta.
    #:
    #: UMA FUNÇÃO DECIDE A ORDENAÇÃO e os dois lugares a consultam — a fila para
    #: ancorar a pergunta, a fusão para recusar o inverso. Não há como
    #: divergirem. E a escolha de gente passa por cima dela: a guarda é a
    #: proposta, não a sentença. Ver o docstring.
    if not contra_a_proposta and _esta_do_lado_que_pergunta(
        sobrevivente, perfil, _mencoes_por_instituicao(sessao)
    ):
        raise RegraViolada(
            f"{sobrevivente.nome!r} é a linha que deve sobreviver a "
            f"{perfil.nome!r} — tem mais menções, ou é o cadastro curado. Funda na "
            "outra direção: quem sai vai na URL. Se o cadastro certo é mesmo "
            f"{sobrevivente.nome!r}, diga isso de propósito com "
            "`contra_a_proposta`."
        )
    if perfil.interlocutor_id is not None:
        raise RegraViolada(
            "Este perfil esta ligado a uma pessoa do CRM. Desfaca a ligacao "
            "antes de fundir, ou funda no cadastro da pessoa."
        )

    #: FUNDIR DENTRO DE UM CADASTRO DESATIVADO ESCONDERIA O DADO ATIVO, e por isso
    #: recusa em vez de herdar: `ativo=false` é alguém dizendo "este cadastro sai
    #: do cadastro de agenda", e reativá-lo por efeito colateral de uma fusão é
    #: decidir no lugar dessa pessoa — no sentido oposto.
    #:
    #: A FILA NÃO ALCANÇA ESTE CASO: `listar` só olha cadastro ativo, então os dois
    #: lados de toda pergunta estão ativos. Esta guarda é para o caminho de fora da
    #: tela, que é o mesmo motivo por que a guarda de direção vive aqui e não no
    #: botão — um `curl` basta.
    if not sobrevivente.ativo:
        raise RegraViolada(
            f"{sobrevivente.nome!r} está desativado, e fundir dentro dele "
            "esconderia as menções que estão à vista. Reative o cadastro que "
            "fica, ou funda na outra direção."
        )

    #: O CONFLITO RECUSA ANTES DE QUALQUER ESCRITA, e com os nomes dos campos.
    #:
    #: Dois valores diferentes preenchidos são duas afirmações de GENTE sobre o
    #: mesmo ator — uma diz que é Tier 1, a outra que é Tier 3. Escolher uma em
    #: silêncio é o chute calado que esta semana cobrou três vezes; e escolher a do
    #: sobrevivente só porque ele é o sobrevivente seria escolher por sorteio nos
    #: pares de zero menções, onde quem sai é decidido pelo UUID.
    divergentes = [
        campo
        for campo in CAMPOS_QUE_O_SOBREVIVENTE_HERDA
        if getattr(perfil, campo) is not None
        and getattr(sobrevivente, campo) is not None
        and getattr(perfil, campo) != getattr(sobrevivente, campo)
    ]
    if divergentes:
        raise RegraViolada(
            f"{perfil.nome!r} e {sobrevivente.nome!r} discordam em "
            f"{', '.join(divergentes)}. Alguém preencheu os dois, e fundir "
            "escolheria um sem dizer: acerte o cadastro que fica e funda depois."
        )

    #: E O SOBREVIVENTE HERDA O QUE ELE NÃO TEM. Sem conflito não há escolha a
    #: fazer, e deixar o campo cair junto com a linha seria perder trabalho de
    #: alguém por nada.
    for campo in CAMPOS_QUE_O_SOBREVIVENTE_HERDA:
        if getattr(sobrevivente, campo) is None:
            setattr(sobrevivente, campo, getattr(perfil, campo))

    #: A PENDÊNCIA DE REVISÃO VIAJA, e ela não cabia na regra acima porque não é
    #: campo nulo: `pendente_de_revisao` é booleano com padrão `False`, então
    #: "herda o que não tem" nunca a alcançaria. Pôr `ativo` e esta na tupla faria
    #: toda fusão entre um cadastro pendente e um conferido RECUSAR com 422 — e
    #: quase todo cadastro nascido de planilha nasce pendente.
    #:
    #: O QUE ISTO FECHA (achado ALTA de revisão): a linha que sai era a pendente na
    #: maioria dos pares — ela nasce da subida —, e a fusão a apagava com a
    #: pendência dentro. O item desaparecia de "Esperando conferência" sem ninguém
    #: ter conferido nada: a fusão respondia, em silêncio, uma pergunta que ela não
    #: responde. Unir dois cadastros não diz que o resultado está conferido.
    if perfil.pendente_de_revisao and not sobrevivente.pendente_de_revisao:
        sobrevivente.pendente_de_revisao = True
        sobrevivente.motivo_da_revisao = (
            sobrevivente.motivo_da_revisao or perfil.motivo_da_revisao
        )

    #: FUNDIR UM VEÍCULO DE LISTA DENTRO DE QUEM NÃO É VEÍCULO RECUSA, e isto é
    #: conserto de achado ALTO de revisão.
    #:
    #: A LENTE MERCADO RECORTA POR `nomes_da_lista`, que exige `tipo='veiculo'`.
    #: A fusão faz o sobrevivente HERDAR a subcategoria, mas nunca o `tipo` — ele
    #: é identidade. Então fundir o Valor Econômico (veículo, classificado)
    #: dentro de um perfil de rede deixava o cadastro com a classificação certa e
    #: o tipo errado: ele saía da lente, sem erro e sem aviso. Com a peça que faz
    #: a lista valer para o passado, essa saída ainda apagaria as menções dele de
    #: todos os meses — uma mudança no índice que ninguém pediu.
    #:
    #: RECUSA, E NÃO CONSERTO AUTOMÁTICO. Trocar o `tipo` do sobrevivente seria
    #: decidir que ele virou veículo, e os CHECKs do banco (`cargo` e pessoa só em
    #: perfil) podem recusar isso no meio da fusão. A outra direção resolve o caso
    #: real — quem quer unificar o Valor Econômico quer o veículo de pé — e a
    #: mensagem a aponta.
    if perfil.tipo == "veiculo" and sobrevivente.tipo != "veiculo":
        em_lista = [
            nome
            for nome in LISTAS_DE_VEICULOS
            if perfil.nome_normalizado in nomes_da_lista(sessao, nome)
        ]
        if em_lista:
            raise RegraViolada(
                f"{perfil.nome!r} está na lista de veículos "
                f"{', '.join(sorted(em_lista))}, que alimenta uma lente, e "
                f"{sobrevivente.nome!r} não é veículo — fundir assim tiraria as "
                "menções dele da lente, inclusive nos meses já fechados. Funda na "
                "outra direção, mantendo o veículo."
            )

    #: E O NOME DE QUEM SAI VIRA APELIDO DO QUE FICA (migration `0102`).
    #:
    #: SEM ISTO A DUPLICATA VOLTA. A ingestão casa por `nome_normalizado` exato
    #: (`veiculos_da_imprensa.reconhecer`), e o nome que some daqui continua
    #: chegando na planilha do mês seguinte: deixaria de casar, viraria "veículo
    #: novo" e nasceria de novo, com as menções do mês dentro.
    #:
    #: OS APELIDOS DE QUEM SAI VÊM JUNTO, e não é zelo: sem reapontar, o
    #: `on delete cascade` os levaria embora, e um nome que já tinha sido
    #: absorvido uma vez voltaria a não casar na subida seguinte. Duas fusões
    #: encadeadas (A→B, depois B→C) são o caso normal numa fila grande.
    sessao.execute(
        InstituicaoApelido.__table__.update()
        .where(InstituicaoApelido.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    #: NOME IGUAL NÃO VIRA APELIDO: `ALMG` (entidade) dentro de `ALMG` (órgão)
    #: não tira nome nenhum de circulação, e a linha só ocuparia a chave.
    if perfil.nome_normalizado != sobrevivente.nome_normalizado:
        #: A AMBIGUIDADE É REGISTRADA, E NÃO RESOLVIDA NEM DESTRUÍDA.
        #:
        #: O CASO: dois cadastros VIVOS podem ter o mesmo `nome_normalizado`
        #: (ALMG é entidade e órgão), e cada um pode ser fundido num sobrevivente
        #: DIFERENTE. A primeira versão fazia "o mais recente vence", e as
        #: menções que eram do primeiro ator passavam todas para o segundo. A
        #: segunda APAGAVA o apelido — e aí o nome saía de `nomes_da_lista`, e a
        #: reconciliação tirava as menções dele do Mercado em todos os meses
        #: fechados: uma fusão sem relação com mercado mudava a série histórica.
        #:
        #: AGORA A CHAVE É O PAR, então as duas linhas coexistem e cada leitura
        #: aplica a regra dela: `reconhecer` só resolve nome de UMA linha,
        #: `nomes_da_lista` aceita o nome se QUALQUER linha for de um listado.
        #:
        #: SEM REPETIR: a mesma fusão rodada duas vezes não acrescenta linha.
        ja = sessao.scalar(
            select(InstituicaoApelido).where(
                InstituicaoApelido.nome_normalizado == perfil.nome_normalizado,
                InstituicaoApelido.instituicao_id == sobrevivente.id,
            )
        )
        if ja is None:
            sessao.add(
                InstituicaoApelido(
                    nome_normalizado=perfil.nome_normalizado,
                    nome=perfil.nome,
                    instituicao_id=sobrevivente.id,
                )
            )

    #: AS MENÇÕES PASSAM: o dossiê do ator fica num só lugar.
    sessao.execute(
        Mencao.__table__.update()
        .where(Mencao.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    #: E O QUE MAIS APONTA PARA INSTITUIÇÃO — sem isto a exclusão bate na chave
    #: estrangeira e a fusão morre no meio.
    sessao.execute(
        Interlocutor.__table__.update()
        .where(Interlocutor.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    sessao.execute(
        InteracaoRegistro.__table__.update()
        .where(InteracaoRegistro.instituicao_id == perfil.id)
        .values(instituicao_id=sobrevivente.id)
    )
    sessao.delete(perfil)
    sessao.flush()
    return sobrevivente


def declarar_distintos(
    sessao: Session,
    *,
    um: uuid.UUID,
    outro: uuid.UUID,
    motivo: str | None = None,
    decidido_por: uuid.UUID | None = None,
) -> AtorDistinto:
    """"São atores diferentes" — tira o par da fila e guarda o que se soube."""
    if um == outro:
        raise RegraViolada("Um cadastro nao e distinto de si mesmo.")
    _buscar(sessao, um)
    _buscar(sessao, outro)

    esquerda, direita = ordenar_o_par(um, outro)
    ja = sessao.get(AtorDistinto, (esquerda, direita))
    if ja is not None:
        #: IDEMPOTENTE: clicar duas vezes não é erro, e o motivo mais novo vale.
        if motivo is not None:
            ja.motivo = motivo
        return ja

    par = AtorDistinto(
        esquerda=esquerda, direita=direita, motivo=motivo, decidido_por=decidido_por
    )
    sessao.add(par)
    sessao.flush()
    return par
