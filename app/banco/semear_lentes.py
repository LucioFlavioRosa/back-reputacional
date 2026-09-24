"""O conteúdo das Lentes v2 que ainda não vem de lugar nenhum.

DE ONDE SAI CADA COISA (e é isto que o "?" de cada bloco mostra na tela):

    das planilhas       evolução, composição por tier, temas, concessionárias,
                        teor das mensagens — a ingestão já grava
    do CRM              a lente institucional inteira, contada na hora
    DESTE ARQUIVO       a matriz de jornalistas, a trajetória de rating, o
                        estudo de percepção, quantas mensagens foram
                        respondidas, e todo o texto editorial

O que este semeador grava veio do **Balanço Reputacional Jan-Ago 2026** do
cliente, transcrito — não é invenção, mas também não é medição desta
ferramenta. Por isso toda linha entra com `exemplo = true`, e a tela diz isso
no "?" de cada bloco em vez de apresentar o número como se tivesse saído da
base.

DUAS LACUNAS QUE ESTE ARQUIVO TAPA, E QUE PRECISAM SER COBRADAS:

    A Clipei não manda o AUTOR da matéria. Sem isso a exposição de cada
    jornalista não pode ser calculada pelo volume, e a matriz inteira é a que a
    agência montou à mão.

    A Approach não manda se a mensagem foi RESPONDIDA. Sem isso metade do
    gráfico principal da lente Clientes não existe, e os números aqui são os do
    relatório.

IDEMPOTENTE, E SÓ SOBRE O QUE É EXEMPLO. O `delete` de cada tabela filtra por
`exemplo = true`: rodar este arquivo de novo nunca apaga cadastro de verdade —
que é o cenário em que um semeador destrói trabalho de gente.

GERADO por `scripts/gerar_semeador_de_lentes.py`? NÃO: este arquivo é editado à
mão como qualquer outro. A formatação abaixo é longa porque o conteúdo é texto
de relatório, e quebrá-lo em constantes menores só afastaria a frase do lugar
onde ela é usada.

Rodar:
    python -m app.banco.semear_lentes
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.banco.sessao import obter_fabrica_de_sessao

# `Usuario` e `Interlocutor` entram para o mapeamento resolver as chaves
# estrangeiras — este semeador roda sozinho, fora do `main`.
from app.banco.tabelas_acesso import Usuario  # noqa: F401
from app.banco.tabelas_lentes import (
    CmRespostaMes,
    CuradoriaLente,
    Encaminhamento,
    EstudoAtributo,
    EstudoPercepcao,
    EventoMercado,
    JornalistaMatriz,
)
from app.banco.tabelas_score import Lente
from app.banco.tabelas_stakeholders import Interlocutor  # noqa: F401

logger = logging.getLogger(__name__)

#: O mês em que a curadoria de exemplo é gravada. É o mês que a base cobre
#: inteiro — as quatro planilhas têm junho.
MES = date(2026, 6, 1)

ORIGEM = "Balanço Reputacional Jan-Ago 2026 (relatório do cliente), transcrito"


# -- a matriz de jornalistas ---------------------------------------------------
#
# Relevância, exposição e proximidade, de 1 a 5. A soma dá a prioridade:
# P1 13–15 · P2 10–12 · P3 7–9 · P4 abaixo de 7.

JORNALISTAS: list[tuple[str, str, int, int, int]] = [
    ("Taís Hirata e Felipe Laurence", "Valor Econômico", 5, 5, 5),
    ("Elisa Calmon", "Neofeed", 5, 5, 5),
    ("Thiago Bethônico", "Folha de S.Paulo", 5, 5, 4),
    ("Juliana Estigarribia", "Bloomberg Línea", 5, 4, 5),
    ("Thierry Ogier", "LatinFinance", 5, 4, 3),
    ("Maria Fernanda Blaser", "REDD Intelligence", 5, 5, 2),
    ("Luciano Pádua", "Exame Infra", 4, 3, 5),
    ("João Sorima", "O Globo", 4, 3, 4),
    ("Márcio Juliboni", "Veja", 4, 2, 5),
    ("Beatriz Kawai", "Agência Infra", 3, 3, 1),
]


# -- o que aconteceu no mercado ------------------------------------------------
#
# O dia só é exato onde o próprio relatório o dá (as divulgações de resultado);
# nos demais vale o mês, que é o grão do eventograma.

EVENTOS: list[tuple[str, str, str, str, str | None, str | None, str | None]] = [
    ("2026-02-15", "governanca", "Vazamento do Termo de Acordo", "pressiona", None, None, None),
    (
        "2026-03-15",
        "resultado",
        "Atraso na divulgação das demonstrações financeiras",
        "pressiona",
        None,
        None,
        None,
    ),
    ("2026-04-10", "resultado", "Demonstrações financeiras de 2025", "misto", None, None, None),
    ("2026-05-07", "resultado", "Resultado do 1T26", "misto", None, None, None),
    ("2026-05-20", "operacao", "Brazil Week, em Nova York", "sustenta", None, None, None),
    ("2026-05-25", "rating", "S&P rebaixa para B", "pressiona", "S&P", None, "B · brAA-"),
    ("2026-05-25", "rating", "Fitch rebaixa para BB-", "pressiona", "Fitch", None, "BB- · brA+"),
    ("2026-05-25", "rating", "Moody's rebaixa para Ba3", "pressiona", "Moody's", None, "Ba3"),
    ("2026-06-15", "operacao", "Edital e proposta da Copasa", "misto", None, None, None),
    ("2026-07-15", "operacao", "Aumento de capital de até R$ 2,1 bi", "sustenta", None, None, None),
    ("2026-07-20", "rating", "Fitch move para B+", "pressiona", "Fitch", "BB- · brA+", "B+ · A"),
    (
        "2026-07-25",
        "outro",
        "Estudo de percepção com investidores e analistas",
        "misto",
        None,
        None,
        None,
    ),
    ("2026-08-05", "resultado", "Resultado do 2T26", "misto", None, None, None),
    ("2026-08-12", "governanca", "Saída do CFO", "pressiona", None, None, None),
    (
        "2026-08-20",
        "rating",
        "Moody's move para B2, perspectiva negativa",
        "pressiona",
        "Moody's",
        "Ba3",
        "B2",
    ),
]

#: A perspectiva só aparece onde a agência a declarou.
PERSPECTIVA_POR_NOTA = {"B2": "negativa"}


# -- o estudo de percepção -----------------------------------------------------

ESTUDO = {
    "instituto": "Brunswick",
    "data": date(2026, 6, 30),
    "amostra": 20,
    "publico": "Investidores e analistas, entrevistas em profundidade",
    "observacao": (
        "Junho e julho de 2026. Os demais atributos entram quando o estudo completo for "
        "liberado."
    ),
}

ATRIBUTOS: list[tuple[str, float, str]] = [
    (
        "Eficiência operacional",
        4.0,
        "Capacidade de executar projetos complexos e melhorar ativos.",
    ),
    (
        "Solidez financeira",
        1.8,
        (
            "A crítica não é ao crescimento, e sim a como foi financiado e à impossibilidade "
            "de auditá-lo."
        ),
    ),
]


# -- quantas mensagens foram respondidas ---------------------------------------
#
# Janeiro a agosto. As RECEBIDAS a ingestão conta sozinha, da própria base; o que
# o banco guarda aqui é só o que a planilha não traz.

RESPOSTAS: list[int] = [383, 325, 504, 492, 607, 465, 398, 561]


# -- o texto de cada lente -----------------------------------------------------

CURADORIA: dict[str, dict] = {
    "imprensa": {
        "manchete": (
            "A cobertura segue majoritariamente favorável, mas o tom continua condicionado "
            "aos resultados financeiros: cada divulgação de balanço reabre governança e "
            "rating."
        ),
        "evolucao_titulo": (
            "Fevereiro concentra o pico negativo; junho puxa o volume para cima com pauta "
            "favorável."
        ),
        "painel_a_titulo": (
            "Nos veículos Muito Relevantes o negativo é o menor, mas o neutro quase empata "
            "com o positivo — espaço para dados mais claros."
        ),
        "painel_b_titulo": (
            "Quem priorizar: relevância, exposição e proximidade. Quanto menor a proximidade, "
            "maior a urgência de aproximação."
        ),
        "leitura": [
            (
                "As pautas neutras e positivas voltaram depois do episódio de fevereiro, e o "
                "volume de junho é o maior do semestre."
            ),
            (
                "O escrutínio não passou: governança e estrutura financeira seguem sob lupa a "
                "cada divulgação de resultado."
            ),
        ],
        "revela": [
            (
                "Crise superada, escrutínio não",
                (
                    "As pautas neutras e positivas voltaram, mas governança e estrutura "
                    "financeira seguem sob lupa a cada divulgação."
                ),
            ),
            (
                "Tier 1 lê com cautela",
                (
                    "Nos veículos mais relevantes o neutro quase empata com o positivo — "
                    "espaço para dados mais claros e didáticos."
                ),
            ),
            (
                "Relacionamento é ativo",
                (
                    "Valor, Folha e Bloomberg Línea concentram volume e retratam a Aegea como "
                    "protagonista do setor."
                ),
            ),
            (
                "Framing em transição",
                (
                    "Sair de pautas de case para a demonstração do impacto macro da "
                    "companhia."
                ),
            ),
        ],
        "encaminhamentos": [
            (
                "Retomar encontros com jornalistas e diretores de redação (P1 e P2)",
                "Comunicação + CEO",
                "contínuo",
            ),
            (
                "Novo ciclo com mídia especializada em mercado financeiro",
                "Comunicação + RI",
                "2026",
            ),
            ("Kit de dados para divulgações de resultado", "RI", "antes do 3T26"),
            ("Monitorar REDD (plataforma fechada, leitura cautelosa)", "Comunicação", "mensal"),
        ],
    },
    "mercado": {
        "manchete": (
            "O mercado reconhece o operador, mas ainda não confia no emissor: eficiência "
            "operacional recebe 4,0 e solidez financeira 1,8 — a nota mais baixa do estudo."
        ),
        "evolucao_titulo": (
            "A agenda de mercado alternou pressão e reforço: cada divulgação de resultado "
            "veio acompanhada de uma ação de rating."
        ),
        "painel_a_titulo": "Operador reconhecido, emissor de dívida ainda gera dúvidas.",
        "painel_b_titulo": "Três agências, cinco movimentos no ano — todos para baixo.",
        "leitura": [
            (
                "Nenhum analista reconstrói a Aegea consolidada a partir do material público "
                "— a complexidade é o problema-raiz e a maior alavanca sobre o custo de "
                "capital."
            ),
            (
                "O mercado quer números, não intenções: conversão de EBITDA em caixa, "
                "reconciliação proforma e guidance de CAPEX."
            ),
            (
                "O impacto está contido no mercado financeiro, por enquanto. Em crédito já "
                "sensibilizado, um segundo evento fecharia essa diferença."
            ),
        ],
        "revela": [
            (
                "Reconstruir a confiança",
                (
                    "Reconhecer o episódio com foco na resposta, não na magnitude do ajuste."
                ),
            ),
            (
                "Disclosure verificável",
                (
                    "Permitir que o investidor valide o resultado sozinho — estrutura "
                    "societária, preferenciais nas SPEs."
                ),
            ),
            (
                "RI é ativo reputacional",
                (
                    "O time é reconhecido; o C-Level tem espaço para fortalecer "
                    "relacionamentos em períodos de estresse."
                ),
            ),
            (
                "ESG depois da confiança",
                (
                    "Comunicar impacto socioambiental antes de restabelecer a confiança pode "
                    "soar como desvio de atenção."
                ),
            ),
        ],
        "encaminhamentos": [
            (
                "Guidance formal de CAPEX e conversão de EBITDA em caixa",
                "RI + Financeiro",
                "imediato",
            ),
            (
                "Doutrina de fato relevante com simetria entre credores",
                "RI + Governança",
                "curto prazo",
            ),
            ("Microfone aberto nas calls de resultado", "CEO + RI", "3T26"),
            (
                "Ampliar terceiros validadores (sell side, mídia especializada)",
                "Comunicação + RI",
                "contínuo",
            ),
        ],
    },
    "sociedade": {
        "manchete": (
            "A imagem da marca ficou praticamente dividida: no 1º semestre o positivo recuou "
            "e o negativo subiu. A pressão não é contínua — vem em picos, e a Corsan "
            "concentra volume e recorrência."
        ),
        "evolucao_titulo": (
            "O volume deve ser lido junto da composição: março e junho concentram a pressão."
        ),
        "painel_a_titulo": (
            "Patrocínio e marca empregadora sustentam a favorabilidade; serviço, obras e "
            "privatização organizam a crítica."
        ),
        "painel_b_titulo": (
            "Corsan concentra a repercussão territorial; as demais unidades têm picos "
            "pontuais."
        ),
        "leitura": [
            (
                "Janeiro foi o mês mais favorável do ano: patrocínio e marca empregadora "
                "dominaram a conversa."
            ),
            (
                "Em julho o volume recua e a crítica fica menos difusa e mais territorial — "
                "serviço, obras, cobrança e impacto ambiental."
            ),
            (
                "Para o restante do ano a tendência é de alta, puxada pelas narrativas "
                "eleitorais que atrelam a Aegea às concessionárias."
            ),
        ],
        "revela": [
            (
                "Territórios positivos",
                (
                    "Patrocínio e Marca Empregadora sustentam a favorabilidade quando a marca "
                    "se associa a pessoas e oportunidades."
                ),
            ),
            (
                "Serviço organiza a crítica",
                (
                    "Atendimento, cobrança, obras e privatização concentram a negatividade."
                ),
            ),
            (
                "Transferência de risco",
                (
                    "Corsan é a unidade mais associada à holding, inclusive negativamente."
                ),
            ),
            (
                "Antecipar picos",
                (
                    "Monitorar recorrências antes dos picos reduz a reação tardia."
                ),
            ),
        ],
        "encaminhamentos": [
            ("Mapeamento preventivo de picos por unidade", "Comunicação + SL", "quinzenal"),
            (
                "Informar antes sobre obras, cobrança e privatização",
                "Comunicação Regional",
                "contínuo",
            ),
            (
                "Protocolo de contaminação político-eleitoral",
                "Comunicação + Institucional",
                "até as eleições",
            ),
            ("Manter ativos patrocínio e marca empregadora", "Comunicação", "contínuo"),
        ],
    },
    "clientes": {
        "manchete": (
            "A pressão nos canais atingiu o máximo em maio e se recompôs a partir de junho: a "
            "reclamação perde peso e a dúvida passa a organizar a demanda."
        ),
        "evolucao_titulo": (
            "O volume cresce até maio, enquanto a proporção bruta de respostas recua."
        ),
        "painel_a_titulo": (
            "A composição muda a partir de junho: cai o negativo e o neutro passa a "
            "predominar."
        ),
        "painel_b_titulo": (
            "Reclamação ganha espaço até maio, quando passa de metade das mensagens."
        ),
        "leitura": [
            (
                "A volumetria sai de 497 em janeiro para 1.016 em maio e não volta ao patamar "
                "do começo do ano."
            ),
            (
                "A taxa bruta inclui marcações e mensagens não pertinentes. A taxa "
                "operacional considera só as mensagens acionáveis — 18% da base fica de fora, "
                "e é isso que separa exposição de demanda real."
            ),
            (
                "Separar crescimento de exposição de demanda real permite dimensionar a "
                "equipe sem transformar alcance em fila."
            ),
        ],
        "revela": [
            (
                "Pico em maio",
                (
                    "Coincidiu com o maior volume do tema Institucional — agenda de conteúdo "
                    "gera demanda nos canais."
                ),
            ),
            (
                "Falta de água é localizada",
                (
                    "Picos em março e maio: driver operacional ligado à prestação do serviço "
                    "pelas unidades."
                ),
            ),
            (
                "Águas do Rio lidera a demanda",
                "Concentra o 1º trimestre; Corsan segue estável em segundo.",
            ),
            (
                "Recomposição",
                (
                    "Com menos reclamação, dúvida e elogio ganham espaço — oportunidade de "
                    "conteúdo útil."
                ),
            ),
        ],
        "encaminhamentos": [
            (
                "Sincronizar impulsionamentos e collabs com a capacidade do CM",
                "Conteúdo + CM",
                "por campanha",
            ),
            ("Medir taxa operacional só com mensagens acionáveis", "CM", "set/26"),
            ("Fluxo quinzenal CM + SL alimentando a pauta de conteúdo", "Comunicação", "contínuo"),
            (
                "Preparar as unidades antes de agendas institucionais",
                "Comunicação Regional",
                "por agenda",
            ),
        ],
    },
    "institucional": {
        "manchete": (
            "O relacionamento institucional é o colchão da reputação: a maioria das agendas "
            "segue propositiva, com a tensão concentrada em tarifa, reequilíbrio e no "
            "processo da Copasa."
        ),
        "evolucao_titulo": "O clima das agendas se mantém propositivo ao longo do semestre.",
        "painel_a_titulo": "Onde o relacionamento sustenta e onde exige preparo.",
        "painel_b_titulo": "A agenda está concentrada em poucos interlocutores federais.",
        "leitura": [
            (
                "Reputação institucional e operacional sólidas amortecem os episódios de "
                "mercado."
            ),
            (
                "A tensão tem endereço: tarifa, reequilíbrio e Copasa concentram o clima "
                "tenso."
            ),
        ],
        "revela": [
            (
                "Colchão reputacional",
                (
                    "Reputação institucional e operacional sólidas amortecem os episódios de "
                    "mercado."
                ),
            ),
            (
                "Tensão tem endereço",
                (
                    "Tarifa e Copasa concentram o clima tenso — preparo de porta-voz e "
                    "posicionamento."
                ),
            ),
            (
                "Fechar o ciclo",
                (
                    "Registrar resultado em todas as agendas é o que transforma "
                    "relacionamento em indicador."
                ),
            ),
        ],
        "encaminhamentos": [
            (
                "Posicionamento único sobre temas sensíveis do setor",
                "Comunicação + Institucional",
                "curto prazo",
            ),
            (
                "Alinhamento de VPs e porta-vozes antes de agendas tensas",
                "Institucional",
                "por agenda",
            ),
            ("Preencher resultado de todas as agendas no CRM", "Institucional", "contínuo"),
        ],
    },
}


def _apagar_exemplos(sessao: Session) -> None:
    """Tira só o que este arquivo pôs. Cadastro de gente fica."""
    for tabela in (
        EventoMercado,
        JornalistaMatriz,
        CmRespostaMes,
        CuradoriaLente,
        Encaminhamento,
    ):
        sessao.execute(delete(tabela).where(tabela.exemplo.is_(True)))
    # O atributo cai junto com o estudo, por `on delete cascade`.
    sessao.execute(delete(EstudoPercepcao).where(EstudoPercepcao.exemplo.is_(True)))


def principal() -> None:
    sessao = obter_fabrica_de_sessao()()
    try:
        lentes = {lente.codigo: lente.id for lente in sessao.scalars(select(Lente))}
        _apagar_exemplos(sessao)

        for nome, veiculo, relevancia, exposicao, proximidade in JORNALISTAS:
            sessao.add(
                JornalistaMatriz(
                    nome=nome,
                    veiculo=veiculo,
                    relevancia=relevancia,
                    exposicao=exposicao,
                    proximidade=proximidade,
                    exemplo=True,
                )
            )

        for dia, tipo, texto, efeito, agencia, anterior, nova in EVENTOS:
            sessao.add(
                EventoMercado(
                    data=date.fromisoformat(dia),
                    tipo=tipo,
                    texto=texto,
                    efeito=efeito,
                    agencia=agencia,
                    nota_anterior=anterior,
                    nota_nova=nova,
                    perspectiva=PERSPECTIVA_POR_NOTA.get(nova or ""),
                    exemplo=True,
                )
            )

        estudo = EstudoPercepcao(**ESTUDO, exemplo=True)
        sessao.add(estudo)
        sessao.flush()
        for ordem, (atributo, nota, comentario) in enumerate(ATRIBUTOS):
            sessao.add(
                EstudoAtributo(
                    estudo_id=estudo.id,
                    atributo=atributo,
                    nota=nota,
                    comentario=comentario,
                    ordem=ordem,
                )
            )

        for indice, respondidas in enumerate(RESPOSTAS):
            sessao.add(
                CmRespostaMes(
                    mes=date(2026, indice + 1, 1),
                    respondidas=respondidas,
                    origem=ORIGEM,
                    exemplo=True,
                )
            )

        for codigo, conteudo in CURADORIA.items():
            lente_id = lentes.get(codigo)
            if lente_id is None:  # pragma: no cover - a 0048 semeia as cinco
                raise RuntimeError(f"Lente {codigo!r} não cadastrada.")
            sessao.add(
                CuradoriaLente(
                    lente_id=lente_id,
                    mes=MES,
                    # PUBLICADO de propósito: o texto veio do relatório do
                    # cliente, e deixá-lo como rascunho faria a tela cair no
                    # rascunho automático — pior que o texto real, e escondendo
                    # que ele existe. A marca `exemplo` é que conta a história.
                    status="publicado",
                    manchete=conteudo["manchete"],
                    evolucao_titulo=conteudo["evolucao_titulo"],
                    painel_a_titulo=conteudo["painel_a_titulo"],
                    painel_b_titulo=conteudo["painel_b_titulo"],
                    leitura=conteudo["leitura"],
                    revela=[
                        {"titulo": titulo, "texto": corpo}
                        for titulo, corpo in conteudo["revela"]
                    ],
                    exemplo=True,
                )
            )
            for acao, responsavel, prazo in conteudo["encaminhamentos"]:
                sessao.add(
                    Encaminhamento(
                        lente_id=lente_id,
                        mes_origem=MES,
                        acao=acao,
                        responsavel=responsavel,
                        prazo=prazo,
                        exemplo=True,
                    )
                )

        sessao.commit()
        quantos = (
            len(JORNALISTAS)
            + len(EVENTOS)
            + len(ATRIBUTOS)
            + len(RESPOSTAS)
            + sum(1 + len(c["encaminhamentos"]) for c in CURADORIA.values())
        )
        logger.info("Lentes: %s linhas de exemplo gravadas.", quantos)
        print(f"Lentes: {quantos} linhas de exemplo gravadas (todas com exemplo=true).")
    finally:
        sessao.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    principal()
