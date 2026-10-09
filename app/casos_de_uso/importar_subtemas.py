"""Lê a planilha de subtemas e diz o que faria com cada linha.

NADA É GRAVADO AQUI. Este módulo lê, confronta com o banco e devolve uma
`Proposta` por linha — a confirmação é outra rota, e é de propósito: a Aegea
mantém a taxonomia numa planilha de 104 linhas, e aplicar 104 mudanças sem
mostrar quais são é pedir confiança que ninguém deveria dar a um `.xlsx` que
passou por e-mail.

O QUE A CONFERÊNCIA PRECISA RESPONDER, em uma tela: destas 104 linhas, quais
mudaram? Na manutenção mensal a resposta é "quatro", e o valor está em não
precisar ler as outras cem.

A IMPORTAÇÃO NÃO CRIA VOCABULÁRIO. Pilar, tema estratégico, LSO e risco já
existem no banco; a planilha os ESCOLHE. Valor que não casa vira linha recusada,
com a coluna e o valor nomeados. A alternativa — criar o que não existe — faria
um erro de digitação virar um pilar novo, e a taxonomia da Aegea é o que o
painel inteiro usa para agrupar.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.banco.gravar import gravar
from app.banco.tabelas_catalogo import (
    BlocoTema,
    MacroTema,
    Risco,
    Tema,
    TemaRisco,
)
from app.casos_de_uso.vinculos_de_risco import aplicar_riscos_do_tema
from app.dominio.erros import RegraViolada
from app.dominio.importacao_de_subtemas import (
    ABA_PRINCIPAL,
    FORMATO,
    Decisao,
    Divergencia,
    Proposta,
    ResumoDaAplicacao,
    SubtemaLido,
    normalizar_nome,
)
from app.dominio.vocabulario_de_temas import NIVEL_PADRAO_DA_TAXONOMIA

#: O teto de linhas que uma planilha de subtemas pode ter.
#:
#: A taxonomia tem 104 subtemas, e dobrar isso já seria uma reorganização
#: inteira. O teto existe para um arquivo errado (a planilha de agendas, com 500
#: linhas, ou um export de outro sistema) ser recusado com uma frase em vez de
#: virar 500 propostas que ninguém vai conferir.
TETO_DE_LINHAS = 400


def ler(conteudo: bytes) -> list[SubtemaLido]:
    """Converte o arquivo em linhas do domínio, ou recusa o arquivo.

    AS RECUSAS SÃO ESTRUTURAIS e vêm antes de qualquer confronto com o banco:
    arquivo que não abre, aba que não existe, cabeçalho que não é o do modelo.
    Deixar o leitor seguir com um cabeçalho diferente é como uma coluna
    renomeada vira 104 linhas recusadas em vez de uma mensagem dizendo "esta
    planilha não é o modelo".
    """
    try:
        livro = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as falha:  # openpyxl levanta de tudo para arquivo ruim
        raise RegraViolada(
            "Não consegui abrir o arquivo. Ele precisa ser o `.xlsx` do modelo — "
            "um `.xls` antigo ou um `.csv` renomeado não serve."
        ) from falha

    if ABA_PRINCIPAL not in livro.sheetnames:
        raise RegraViolada(
            f"A planilha não tem a aba {ABA_PRINCIPAL!r}. "
            f"Abas encontradas: {', '.join(livro.sheetnames) or '(nenhuma)'}. "
            "Baixe o modelo e preencha nele."
        )

    aba = livro[ABA_PRINCIPAL]
    linhas = list(aba.iter_rows(values_only=True))
    if not linhas:
        raise RegraViolada(f"A aba {ABA_PRINCIPAL!r} está vazia.")

    # O CABEÇALHO PODE NÃO ESTAR NA PRIMEIRA LINHA: o modelo escreve uma nota
    # acima dele, e quem edita no Excel às vezes acrescenta outra. Procurar o
    # cabeçalho em vez de exigi-lo na linha 1 é o que faz a planilha que a pessoa
    # já tem continuar servindo.
    inicio = _onde_esta_o_cabecalho(linhas)
    if inicio is None:
        esperado = ", ".join(c.nome for c in FORMATO)
        raise RegraViolada(
            f"Não achei o cabeçalho do modelo na aba {ABA_PRINCIPAL!r}. "
            f"As colunas precisam ser: {esperado}."
        )

    cabecalho = [_texto(v) for v in linhas[inicio]]
    posicao = {c.nome: cabecalho.index(c.nome) for c in FORMATO}

    lidas: list[SubtemaLido] = []
    for numero, bruta in enumerate(linhas[inicio + 1 :], start=inicio + 2):
        celulas = {c.nome: _texto(_na(bruta, posicao[c.nome])) for c in FORMATO}
        # LINHA EM BRANCO NÃO É ERRO: a planilha vem com linhas vazias no fim
        # porque o Excel as guarda depois de alguém apagar conteúdo.
        if not any(celulas.values()):
            continue
        if len(lidas) >= TETO_DE_LINHAS:
            raise RegraViolada(
                f"A planilha passa de {TETO_DE_LINHAS} linhas preenchidas. "
                "A taxonomia tem 104 subtemas — confira se este é o arquivo certo."
            )
        lidas.append(
            SubtemaLido(
                linha=numero,
                nome=celulas["Subtema (N3)"],
                pilar=celulas["Pilar (N1)"],
                tema_estrategico=celulas["Tema estratégico (N2)"],
                camada_lso=celulas["LSO"] or None,
                e_risco_bruto=celulas["É tema de risco?"],
                riscos=_codigos(celulas["Riscos (códigos)"]),
            )
        )

    if not lidas:
        raise RegraViolada(
            f"A aba {ABA_PRINCIPAL!r} não tem nenhuma linha preenchida abaixo do "
            "cabeçalho."
        )
    return lidas


def _onde_esta_o_cabecalho(linhas: Sequence[tuple]) -> int | None:
    """O índice da linha que tem TODAS as colunas do modelo.

    Todas, e não "a primeira que tem alguma": o modelo escreve uma nota que
    contém o nome da aba, e uma busca frouxa a confundiria com o cabeçalho.
    """
    nomes = {c.nome for c in FORMATO}
    for i, linha in enumerate(linhas[:20]):
        if nomes <= {_texto(v) for v in linha}:
            return i
    return None


def _na(linha: tuple, indice: int):
    return linha[indice] if indice < len(linha) else None


def _texto(valor) -> str:
    if valor is None:
        return ""
    # `str` E `strip`, nesta ordem: o Excel devolve número para uma célula que
    # parece texto ("01" vira 1), e `strip` sobre `int` estoura.
    return str(valor).strip()


#: O que `É tema de risco?` aceita, além de `Sim`/`Não`.
#:
#: As variações existem porque a planilha passa por várias mãos e o Excel
#: oferece caixas de seleção que gravam `TRUE`. Recusar `VERDADEIRO` por rigor
#: faria a pessoa corrigir 104 células que o sistema entende perfeitamente.
_SIM = {"sim", "s", "true", "verdadeiro", "1", "x"}
_NAO = {"nao", "n", "false", "falso", "0"}


def _interpretar_risco(valor: str) -> tuple[bool | None, bool]:
    """Devolve `(valor, reconhecido)`.

    NULO É RESPOSTA, e distinta de `Não`: `e_risco` nulo quer dizer "não
    reconciliado com a taxonomia v4", e `false` quer dizer "reconciliado, e não
    é de risco". A `0058` documenta a diferença, e perdê-la aqui apagaria uma
    informação que a planilha carrega de propósito.

    O SEGUNDO ELEMENTO separa "em branco" de "digitou algo que eu não entendo" —
    sem ele, um "Talvez" na célula viraria nulo em silêncio, e a pessoa só
    descobriria meses depois que aquele subtema nunca foi reconciliado.
    """
    if not valor.strip():
        return None, True
    normal = normalizar_nome(valor)
    sem_acento = normal.replace("ã", "a").replace("á", "a").replace("é", "e")
    if sem_acento in _SIM:
        return True, True
    if sem_acento in _NAO:
        return False, True
    return None, False


def _codigos(valor: str) -> tuple[str, ...]:
    """`"R01, R07"` -> `("R01", "R07")`, preservando a ordem e sem repetir."""
    vistos: list[str] = []
    for pedaco in valor.replace(";", ",").split(","):
        codigo = pedaco.strip().upper()
        if codigo and codigo not in vistos:
            vistos.append(codigo)
    return tuple(vistos)


def propor(sessao: Session, lidas: Iterable[SubtemaLido]) -> list[Proposta]:
    """Confronta cada linha com o banco e diz o que faria com ela."""
    pilares = {normalizar_nome(b.nome): b for b in sessao.scalars(select(BlocoTema))}
    macros = {normalizar_nome(m.nome): m for m in sessao.scalars(select(MacroTema))}
    riscos = {r.codigo.upper(): r for r in sessao.scalars(select(Risco))}
    temas = {normalizar_nome(t.nome): t for t in sessao.scalars(select(Tema))}

    # OS RISCOS DE CADA TEMA, numa consulta só. Um `select` por linha seriam 104
    # idas ao banco para uma planilha de manutenção.
    riscos_do_tema: dict[int, set[int]] = {}
    for tema_id, risco_id in sessao.execute(select(TemaRisco.tema_id, TemaRisco.risco_id)):
        riscos_do_tema.setdefault(tema_id, set()).add(risco_id)

    propostas: list[Proposta] = []
    #: Onde cada nome apareceu pela primeira vez NESTE arquivo.
    #:
    #: SEM ISTO, DUAS LINHAS COM O MESMO SUBTEMA VIRAM DOIS `NOVO`, e a gravação
    #: estoura no índice único de `tema.nome` — 500 e "erro interno" para quem
    #: subiu, em vez da frase que resolve ("a linha 37 repete a 12"). O confronto
    #: com o banco não pega o caso: `temas` é o que já existe LÁ, e as duas
    #: linhas são novas aqui.
    #:
    #: Vale também para `ALTERA` e `IGUAL`: duas linhas mandando no mesmo tema
    #: podem mandar coisas diferentes, e aplicar as duas faria a última ganhar
    #: em silêncio. A segunda é recusada, qualquer que seja a decisão dela.
    primeira_aparicao: dict[str, int] = {}

    for lida in lidas:
        proposta = _propor_uma(lida, pilares, macros, riscos, temas, riscos_do_tema)
        chave = normalizar_nome(lida.nome)
        anterior = primeira_aparicao.get(chave)
        if chave and anterior is not None:
            proposta = Proposta(
                lido=lida,
                decisao=Decisao.RECUSADA,
                divergencias=(
                    Divergencia(
                        "Subtema (N3)",
                        lida.nome,
                        f"Esta planilha já traz este subtema na linha {anterior}. "
                        "Deixe uma linha por subtema.",
                    ),
                ),
            )
        elif chave:
            primeira_aparicao[chave] = lida.linha
        propostas.append(proposta)
    return propostas


def _propor_uma(
    lida: SubtemaLido,
    pilares: Mapping[str, BlocoTema],
    macros: Mapping[str, MacroTema],
    riscos: Mapping[str, Risco],
    temas: Mapping[str, Tema],
    riscos_do_tema: Mapping[int, set[int]],
) -> Proposta:
    divergencias: list[Divergencia] = []

    if not lida.nome:
        divergencias.append(
            Divergencia("Subtema (N3)", "", "O subtema é o que esta planilha cadastra.")
        )

    pilar = pilares.get(normalizar_nome(lida.pilar))
    if lida.pilar and pilar is None:
        divergencias.append(
            Divergencia(
                "Pilar (N1)",
                lida.pilar,
                "Não é um dos pilares cadastrados. A importação não cria pilar — "
                "escolha da lista do modelo.",
            )
        )

    macro = macros.get(normalizar_nome(lida.tema_estrategico))
    if lida.tema_estrategico and macro is None:
        divergencias.append(
            Divergencia(
                "Tema estratégico (N2)",
                lida.tema_estrategico,
                "Não é um dos temas estratégicos cadastrados.",
            )
        )

    # OS DOIS ANDAM JUNTOS, e a recusa é do PAR incompleto, não da coluna vazia.
    #
    # Em branco nos dois é estado legítimo ("não reconciliado", o que 45
    # subtemas têm hoje). Preenchido nos dois é classificação. Um só preenchido
    # é meia classificação: o banco guarda apenas `macro_tema_id`, então um
    # pilar sem tema estratégico não seria gravado em lugar nenhum — a linha
    # pareceria aplicada e não teria efeito.
    if bool(lida.pilar) != bool(lida.tema_estrategico):
        faltando = "Tema estratégico (N2)" if lida.pilar else "Pilar (N1)"
        divergencias.append(
            Divergencia(
                faltando,
                "",
                "Pilar e Tema estratégico andam juntos: preencha os dois, ou "
                "deixe os dois em branco (= ainda não reconciliado).",
            )
        )

    # A HIERARQUIA TEM DE FECHAR, e este é o erro mais fácil de cometer numa
    # planilha: escolher o pilar de uma linha e o tema estratégico de outra. O
    # banco aceitaria (só `macro_tema_id` é gravado), e o painel passaria a
    # agrupar aquele subtema sob um pilar que a planilha não diz.
    if pilar is not None and macro is not None and macro.bloco_tema_id != pilar.id:
        divergencias.append(
            Divergencia(
                "Tema estratégico (N2)",
                lida.tema_estrategico,
                f"{lida.tema_estrategico!r} não pertence ao pilar {lida.pilar!r}.",
            )
        )

    e_risco, reconhecido = _interpretar_risco(lida.e_risco_bruto)
    if not reconhecido:
        divergencias.append(
            Divergencia(
                "É tema de risco?",
                lida.e_risco_bruto,
                "Use Sim, Não, ou deixe em branco (= não reconciliado).",
            )
        )

    escolhidos: list[Risco] = []
    for codigo in lida.riscos:
        risco = riscos.get(codigo)
        if risco is None:
            divergencias.append(
                Divergencia(
                    "Riscos (códigos)",
                    codigo,
                    f"{codigo!r} não é um código da matriz de risco (R01 a R32).",
                )
            )
        else:
            escolhidos.append(risco)

    if divergencias:
        return Proposta(lido=lida, decisao=Decisao.RECUSADA, divergencias=tuple(divergencias))

    depois = {
        "macro_tema_id": macro.id if macro else None,
        "camada_lso": lida.camada_lso,
        "e_risco": e_risco,
        "riscos": sorted(r.id for r in escolhidos),
    }

    existente = temas.get(normalizar_nome(lida.nome))
    if existente is None:
        return Proposta(lido=lida, decisao=Decisao.NOVO, depois=depois)

    antes = {
        "macro_tema_id": existente.macro_tema_id,
        "camada_lso": existente.camada_lso,
        "e_risco": existente.e_risco,
        "riscos": sorted(riscos_do_tema.get(existente.id, set())),
    }
    decisao = Decisao.IGUAL if antes == depois else Decisao.ALTERA
    return Proposta(
        lido=lida,
        decisao=decisao,
        tema_id=existente.id,
        antes=antes if decisao is Decisao.ALTERA else None,
        depois=depois if decisao is Decisao.ALTERA else None,
    )


def impressao_das_propostas(propostas: Iterable[Proposta]) -> str:
    """Um resumo do que a pessoa VIU na conferência, para a confirmação conferir.

    POR QUE ISTO EXISTE. Nada é gravado entre conferir e confirmar — a
    importação de subtemas não tem tabela de rascunho, de propósito (ver
    `aplicar`). O preço é que o banco pode mudar nesse intervalo: alguém edita
    um subtema pela tela de Cadastro de Assuntos enquanto a planilha está
    aberta, e a confirmação aplicaria um `ALTERA` sobre um "antes" que já não é
    o antes. A pessoa teria aprovado uma mudança e aplicado outra.

    A impressão fecha isso sem tabela: a confirmação reconfere a planilha contra
    o banco DAQUELE instante, recalcula a impressão, e recusa se ela mudou. É a
    reconferência transacional que a importação de agendas faz com estado, feita
    aqui sem estado.

    ENTRA O QUE MUDA A DECISÃO, e não a planilha inteira: a linha, o nome, o
    `tema_id`, a decisão e o par antes/depois. Reordenar a planilha sem mudar
    nada muda a impressão (a linha entra), e isso é desejado — a conferência
    mostra números de linha, e a pessoa aprovou AQUELAS linhas.

    O `tema_id` ENTROU DEPOIS, e a revisão do bloco o provou necessário com um
    cenário reproduzido contra o banco: conferiu-se um `ALTERA` do tema 159;
    antes de confirmar, aquele tema foi RENOMEADO e um outro, com o nome e os
    campos que o 159 tinha, foi criado como 160. A planilha segue falando do
    mesmo nome, e com nome normalizado a impressão batia — mas `aplicar` ia
    alterar o 160. A pessoa teria aprovado uma mudança num subtema e aplicado
    noutro. A identidade do registro é parte do que ela aprovou, não só o nome.
    """
    resumo = hashlib.sha256()
    for proposta in propostas:
        resumo.update(
            json.dumps(
                [
                    proposta.lido.linha,
                    normalizar_nome(proposta.lido.nome),
                    proposta.tema_id,
                    str(proposta.decisao),
                    proposta.antes,
                    proposta.depois,
                ],
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        )
        resumo.update(b"\x1e")  # separador, para duas linhas não se fundirem
    return resumo.hexdigest()


def aplicar(sessao: Session, propostas: Iterable[Proposta]) -> ResumoDaAplicacao:
    """Grava os `NOVO` e os `ALTERA`, e devolve a conta do que fez.

    NÃO HÁ TABELA DE RASCUNHO, e isso é escolha. A importação de agendas
    persiste cada linha em `importacao_linha` porque são até 500 linhas de 58
    colunas, com edição célula a célula e um trabalho que a pessoa interrompe e
    retoma. A de subtemas são 150 linhas de 6 colunas que ninguém edita dentro
    do sistema: a pessoa corrige a PLANILHA e sobe de novo. Duas tabelas e uma
    migration para guardar um rascunho que vive três minutos seriam a cerimônia
    que o docstring do domínio recusa — e o custo real, a reconferência, está
    resolvido por `impressao_das_propostas` mais o bloqueio de
    `_conferir_sob_bloqueio`, aqui embaixo.

    `RECUSADA` E `IGUAL` NÃO GERAM ESCRITA, e uma linha recusada não impede as
    outras. A alternativa — recusar o arquivo inteiro por uma célula errada —
    faria uma revisão de taxonomia parar por um código de risco digitado
    errado, com as outras 149 linhas certas presas atrás dele.

    O QUE A IMPORTAÇÃO NÃO TOCA, mesmo tendo a linha na mão: `tema.nivel`,
    `tema.tipo`, `tema.ativo` e `tema.area_dona_id`. Nenhum deles está na
    planilha, e em registro que já existe silêncio na planilha não é instrução
    de apagar. Em registro NOVO o nível vem de `NIVEL_PADRAO_DA_TAXONOMIA`, que
    explica a escolha.
    """
    propostas = list(propostas)
    _conferir_sob_bloqueio(sessao, propostas)

    criados = alterados = iguais = recusadas = 0

    for proposta in propostas:
        if proposta.decisao is Decisao.RECUSADA:
            recusadas += 1
            continue
        if proposta.decisao is Decisao.IGUAL:
            iguais += 1
            continue

        depois = proposta.depois or {}
        riscos = list(depois.get("riscos") or [])

        if proposta.decisao is Decisao.NOVO:
            tema = Tema(
                # O NOME VAI COMO A PLANILHA ESCREVEU, com acento e caixa.
                # `normalizar_nome` serve para COMPARAR, nunca para gravar:
                # gravar a forma normalizada criaria "tarifa social" na tela
                # onde a Aegea escreve "Tarifa social".
                nome=" ".join(proposta.lido.nome.split()),
                nivel=NIVEL_PADRAO_DA_TAXONOMIA,
                macro_tema_id=depois.get("macro_tema_id"),
                camada_lso=depois.get("camada_lso"),
                e_risco=depois.get("e_risco"),
            )
            # `gravar` E NÃO `add` + `flush`: `tema.nome` tem índice único, e a
            # comparação desta importação é por nome NORMALIZADO (caixa e espaço
            # colapsado) enquanto o índice é exato. Duas confirmações
            # simultâneas, ou um nome que já existe com outra caixa, estouram
            # `IntegrityError` — que sem isto sairia como 500 e "erro interno"
            # para quem subiu, em vez da frase que resolve.
            gravar(
                sessao,
                tema,
                novo=True,
                ao_colidir=(
                    f"A linha {proposta.lido.linha} tenta criar o subtema "
                    f"{tema.nome!r}, que já existe. Confira de novo."
                ),
            )
            aplicar_riscos_do_tema(sessao, tema.id, riscos)
            criados += 1
            continue

        # ALTERA
        tema = sessao.get(Tema, proposta.tema_id)
        if tema is None:  # pragma: no cover - some entre a conferência e aqui
            raise RegraViolada(
                f"O subtema da linha {proposta.lido.linha} foi apagado enquanto "
                "esta planilha estava em conferência. Confira de novo."
            )
        tema.macro_tema_id = depois.get("macro_tema_id")
        tema.camada_lso = depois.get("camada_lso")
        tema.e_risco = depois.get("e_risco")
        aplicar_riscos_do_tema(sessao, tema.id, riscos)
        alterados += 1

    sessao.flush()
    return ResumoDaAplicacao(
        criados=criados, alterados=alterados, iguais=iguais, recusadas=recusadas
    )


def _conferir_sob_bloqueio(sessao: Session, propostas: Sequence[Proposta]) -> None:
    """Tranca as linhas que vão mudar e confirma que o `antes` ainda é o antes.

    A IMPRESSÃO SOZINHA NÃO BASTA, e a revisão do bloco mostrou por quê: ela é
    calculada ANTES de gravar, e nada impede outra transação de entrar entre o
    cálculo e os `UPDATE`. A janela é pequena e o efeito é "o último commit
    ganha" — a edição feita pelo Cadastro de Assuntos some sem ninguém saber.

    A TRANCA É `FOR UPDATE` NAS LINHAS AFETADAS, e não um bloqueio da tabela
    inteira: revisar a taxonomia não pode impedir alguém de cadastrar um
    assunto que esta planilha não menciona. Depois de trancar, o estado é LIDO
    DE NOVO e comparado com o `antes` que a pessoa aprovou:

      - mudou antes da tranca -> a comparação falha, e a importação recusa
      - mudou depois da tranca -> impossível: o outro lado espera o nosso commit

    `tema_risco` TAMBÉM ENTRA. Trancar só `tema` deixaria passar quem mexe nos
    vínculos de risco sem tocar na linha do tema — e é exatamente o que
    `aplicar_riscos_do_tema` faz quando a lista de riscos é a única coisa que
    muda.
    """
    alvos = {
        proposta.tema_id: proposta
        for proposta in propostas
        if proposta.decisao is Decisao.ALTERA and proposta.tema_id is not None
    }
    if not alvos:
        return

    ids = sorted(alvos)
    # ORDENADOS, para duas confirmações simultâneas trancarem na mesma ordem e
    # não se abraçarem num impasse (`deadlock detected`).
    sessao.execute(select(Tema.id).where(Tema.id.in_(ids)).order_by(Tema.id).with_for_update())
    sessao.execute(
        select(TemaRisco.tema_id)
        .where(TemaRisco.tema_id.in_(ids))
        .order_by(TemaRisco.tema_id, TemaRisco.risco_id)
        .with_for_update()
    )

    agora: dict[int, set[int]] = {}
    for tema_id, risco_id in sessao.execute(
        select(TemaRisco.tema_id, TemaRisco.risco_id).where(TemaRisco.tema_id.in_(ids))
    ).all():
        agora.setdefault(tema_id, set()).add(risco_id)

    # `populate_existing` GARANTE A RELEITURA, e a garantia é o ponto.
    #
    # Sem ele, `select(Tema)` pode devolver o objeto que já está no mapa de
    # identidade — a versão lida na conferência — e a comparação abaixo
    # compararia o `antes` com ele mesmo: um guarda que não dispara. Medido em
    # ensaio direto: sessão A lê, sessão B altera e commita, A relê; sem a opção
    # vem `confianca` (o valor velho), com a opção vem `credibilidade`.
    #
    # PODE, E NÃO SEMPRE: em outros arranjos de sessão a releitura simples volta
    # fresca, e foi medido também. É justamente por depender do estado da sessão
    # que isto não fica por sorte — a opção custa nada e torna a leitura sempre
    # a do banco. `test_a_tranca_enxerga_o_valor_do_banco_e_nao_o_da_sessao`
    # fixa o mecanismo de forma determinística.
    presentes = list(
        sessao.scalars(select(Tema).where(Tema.id.in_(ids)).execution_options(populate_existing=True))
    )
    for tema in presentes:
        proposta = alvos[tema.id]
        encontrado = {
            "macro_tema_id": tema.macro_tema_id,
            "camada_lso": tema.camada_lso,
            "e_risco": tema.e_risco,
            "riscos": sorted(agora.get(tema.id, set())),
        }
        if encontrado != proposta.antes:
            raise RegraViolada(
                f"O subtema da linha {proposta.lido.linha} "
                f"({proposta.lido.nome!r}) mudou depois que você conferiu esta "
                "planilha. Confira de novo antes de aplicar."
            )

    faltando = set(ids) - {tema.id for tema in presentes}
    if faltando:
        linhas = sorted(alvos[tema_id].lido.linha for tema_id in faltando)
        raise RegraViolada(
            f"O subtema da linha {linhas[0]} foi apagado enquanto esta planilha "
            "estava em conferência. Confira de novo."
        )
