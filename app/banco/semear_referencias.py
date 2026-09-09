"""A biblioteca de referências, povoada como a de verdade seria.

QUATRO POR ASSUNTO, NO MÍNIMO, e os seis tipos representados. Uma biblioteca de
demonstração com duas linhas não mostra o problema que ela resolve: o valor
aparece quando alguém marca "Tarifa" numa agenda e recebe cinco documentos, e
precisa decidir quais levar.

AS DATAS SÃO ESPALHADAS DE PROPÓSITO. Parte do acervo está fresco (agosto e
setembro de 2026) e parte envelheceu — a mais antiga é de agosto de 2025, e há
quatro notas técnicas do fim daquele ano. Uma base em que tudo foi atualizado
ontem esconde justamente o que a coluna `atualizado_em` existe para mostrar.

REFERÊNCIA SERVE A MAIS DE UM ASSUNTO, e várias aqui servem: o Q&A de tarifa
social fala de tarifa E de inclusão sanitária; o inventário de GEE fala de
carbono E de clima. É assim no acervo real, e é o que faz uma agenda sobre dois
assuntos receber material dos dois.

Idempotente por TÍTULO: rodar duas vezes não duplica.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.armazenamento import blob
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_catalogo import Tema
from app.banco.tabelas_interacoes import Arquivo
from app.banco.tabelas_referencias import (
    Referencia,
    ReferenciaTema,
    ReferenciaVersao,
)

#: (título, tipo, resumo, assuntos, última atualização do arquivo)
#:
#: O PRIMEIRO ASSUNTO É O PRINCIPAL: é ele que define a pasta no blob. Os
#: demais entram em `referencia_tema`, para a busca e para o preparo de agenda.
#:
#: O tipo diz O QUE O DOCUMENTO É; os assuntos, do que ele trata. É por tipo que
#: se procura antes de uma reunião — "onde está o Q&A" vem antes de "qual era o
#: nome do arquivo".
ACERVO: list[tuple[str, str, str, tuple[str, ...], date]] = [
    # -- Universalização --------------------------------------------------
    (
        "Posicionamento — Metas de universalização até 2033",
        "posicionamento",
        "O que a Aegea afirma publicamente sobre prazos, cobertura e o que "
        "depende de terceiros para as metas do Marco serem cumpridas.",
        ("Universalização",),
        date(2026, 8, 26),
    ),
    (
        "Q&A — Prazos de universalização nos contratos vigentes",
        "qa",
        "As dez perguntas que a imprensa faz sobre atraso de obra, e a resposta "
        "que separa o que é obrigação da concessionária do que é do poder "
        "concedente.",
        ("Universalização", "Regulação"),
        date(2026, 9, 2),
    ),
    (
        "Dados — Cobertura de água e esgoto por concessão",
        "dados",
        "População atendida, ligações e índice de tratamento, concessão a "
        "concessão. É a fonte dos números que entram em entrevista.",
        ("Universalização", "Inclusão sanitária"),
        date(2026, 9, 5),
    ),
    (
        "Apresentação — Universalização: onde estamos",
        "apresentacao",
        "O deck institucional de 18 slides usado em audiência pública e em "
        "reunião com prefeitura.",
        ("Universalização", "Modelo de negócio"),
        date(2026, 7, 14),
    ),
    # -- Tarifa -----------------------------------------------------------
    (
        "Nota técnica — Metodologia do reajuste anual",
        "nota_tecnica",
        "Como o índice contratual é calculado, o que ele repassa e o que não "
        "repassa. Para responder à acusação de reajuste acima da inflação.",
        ("Tarifa", "Regulação"),
        date(2026, 8, 12),
    ),
    (
        "Dados — Tarifa média por concessão e comparativo setorial",
        "dados",
        "A tarifa da Aegea ao lado da média nacional e das estaduais, por metro "
        "cúbico e por faixa de consumo.",
        ("Tarifa",),
        date(2026, 9, 1),
    ),
    (
        "Q&A — Tarifa social: quem tem direito e como pedir",
        "qa",
        "Critérios de enquadramento, desconto praticado e o caminho para "
        "solicitar. A pergunta mais frequente em rádio e em audiência.",
        ("Tarifa", "Inclusão sanitária"),
        date(2026, 6, 30),
    ),
    # -- IPO --------------------------------------------------------------
    (
        "Posicionamento — Estrutura acionária e planos de mercado de capitais",
        "posicionamento",
        "O que se pode e o que não se pode dizer sobre abertura de capital. "
        "Inclui a frase única autorizada quando a pergunta vier de imprensa.",
        ("IPO", "Disciplina financeira"),
        date(2026, 8, 20),
    ),
    (
        "Release — Resultados do 2º trimestre de 2026",
        "release",
        "O comunicado divulgado ao mercado, com receita, EBITDA e investimento "
        "no período.",
        ("IPO", "Disciplina financeira"),
        date(2026, 8, 14),
    ),
    (
        "Q&A — Perguntas frequentes de investidores",
        "qa",
        "As dúvidas recorrentes de fundos e bancos sobre alavancagem, pipeline "
        "de leilões e governança.",
        ("IPO",),
        date(2026, 7, 29),
    ),
    (
        "Apresentação — Aegea Day 2026",
        "apresentacao",
        "O deck do encontro anual com analistas e investidores.",
        ("IPO", "Modelo de negócio"),
        date(2026, 5, 22),
    ),
    # -- Regulação --------------------------------------------------------
    (
        "Posicionamento — Normas de referência da ANA",
        "posicionamento",
        "Como a Aegea se posiciona sobre a padronização regulatória e sobre a "
        "convivência entre a ANA e as agências estaduais.",
        ("Regulação",),
        date(2026, 8, 7),
    ),
    (
        "Nota técnica — Efeito das normas de referência nos contratos vigentes",
        "nota_tecnica",
        "O que muda, o que não muda e onde há insegurança jurídica nos "
        "contratos assinados antes das normas.",
        ("Regulação", "Modelo de negócio"),
        date(2025, 11, 18),
    ),
    (
        "Q&A — Quem regula o quê: ANA, agências estaduais e municipais",
        "qa",
        "A divisão de competências explicada em linguagem de entrevista, sem "
        "jargão regulatório.",
        ("Regulação", "Cenário político"),
        date(2026, 4, 3),
    ),
    (
        "Dados — Contratos por agência reguladora",
        "dados",
        "Quantos contratos a Aegea tem sob cada agência, com o ciclo de revisão "
        "tarifária de cada uma.",
        ("Regulação", "Tarifa"),
        date(2026, 9, 4),
    ),
    # -- Leilões ----------------------------------------------------------
    (
        "Posicionamento — Critérios de participação em leilões",
        "posicionamento",
        "O que a Aegea diz sobre disciplina de capital ao disputar um ativo, e "
        "por que não participa de todos.",
        ("Leilões", "Disciplina financeira"),
        date(2026, 8, 29),
    ),
    (
        "Release — Resultado do leilão do bloco de saneamento",
        "release",
        "O comunicado padrão de arremate: valor, prazo da concessão e "
        "investimento previsto.",
        ("Leilões",),
        date(2026, 6, 11),
    ),
    (
        "Dados — Histórico de leilões do setor e ágios praticados",
        "dados",
        "Todos os leilões de saneamento desde 2020, com vencedor, ágio e "
        "investimento contratado.",
        ("Leilões", "Modelo de negócio"),
        date(2026, 7, 8),
    ),
    (
        "Q&A — Como um ativo é avaliado antes do leilão",
        "qa",
        "A resposta para \"por que a Aegea pagou tanto\" e para \"por que a "
        "Aegea não participou\".",
        ("Leilões",),
        date(2026, 3, 19),
    ),
    # -- Copasa -----------------------------------------------------------
    (
        "Posicionamento — Interesse em Minas Gerais",
        "posicionamento",
        "A posição institucional sobre o mercado mineiro. Assunto sensível: "
        "nada além do texto aprovado.",
        ("Copasa", "Cenário político"),
        date(2026, 9, 3),
    ),
    (
        "Q&A — Copasa: o que responder e o que não responder",
        "qa",
        "As perguntas que chegam por imprensa e por investidor, com a fronteira "
        "explícita do que não se comenta.",
        ("Copasa",),
        date(2026, 9, 3),
    ),
    (
        "Nota técnica — Marco regulatório do saneamento em Minas Gerais",
        "nota_tecnica",
        "Estrutura institucional, agência reguladora e histórico das discussões "
        "de desestatização no estado.",
        ("Copasa", "Regulação"),
        date(2026, 2, 27),
    ),
    (
        "Dados — Indicadores do saneamento em Minas Gerais",
        "dados",
        "Cobertura, perdas e investimento por município mineiro, do SNIS.",
        ("Copasa", "Universalização"),
        date(2026, 5, 9),
    ),
    # -- Resíduos ---------------------------------------------------------
    (
        "Posicionamento — Resíduos sólidos como frente de negócio",
        "posicionamento",
        "Por que a Aegea entrou em resíduos e como isso conversa com a operação "
        "de saneamento.",
        ("Resíduos", "Modelo de negócio"),
        date(2026, 7, 22),
    ),
    (
        "Apresentação — Portfólio de resíduos sólidos",
        "apresentacao",
        "Aterros, transbordo e coleta: o que a Aegea opera e onde.",
        ("Resíduos",),
        date(2026, 6, 5),
    ),
    (
        "Q&A — Aterro sanitário: licenciamento, vizinhança e odor",
        "qa",
        "As perguntas que aparecem em audiência pública de licenciamento, e as "
        "respostas técnicas em linguagem de rádio.",
        ("Resíduos", "Reputação"),
        date(2026, 8, 1),
    ),
    (
        "Dados — Volume tratado e destinação final",
        "dados",
        "Toneladas por unidade, com taxa de recuperação e destinação.",
        ("Resíduos", "Carbono"),
        date(2026, 9, 5),
    ),
    # -- Biometano --------------------------------------------------------
    (
        "Posicionamento — Biometano a partir do tratamento de esgoto",
        "posicionamento",
        "A tese: o esgoto tratado vira energia, e isso muda a conta ambiental e "
        "a econômica da estação.",
        ("Biometano", "Carbono"),
        date(2026, 8, 18),
    ),
    (
        "Nota técnica — Rota tecnológica e viabilidade do biogás",
        "nota_tecnica",
        "Purificação, injeção na rede e o que o projeto exige de escala para "
        "fechar a conta.",
        ("Biometano",),
        date(2025, 9, 30),
    ),
    (
        "Release — Nova planta de biometano",
        "release",
        "O comunicado de inauguração, com capacidade instalada e destinação do "
        "gás produzido.",
        ("Biometano", "Reputação"),
        date(2026, 4, 16),
    ),
    (
        "Q&A — Biogás e biometano: dúvidas frequentes",
        "qa",
        "A diferença entre os dois, segurança da operação e para onde vai o "
        "produto.",
        ("Biometano", "Clima"),
        date(2026, 7, 3),
    ),
    # -- Reúso ------------------------------------------------------------
    (
        "Posicionamento — Água de reúso para indústria e data centers",
        "posicionamento",
        "O reúso como negócio, e não como obrigação regulatória. É a moldura "
        "que o porta-voz deve usar.",
        ("Reúso", "Modelo de negócio"),
        date(2026, 8, 25),
    ),
    (
        "Nota técnica — Padrões de qualidade da água de reúso",
        "nota_tecnica",
        "Classes de reúso, parâmetros exigidos e o que cada uso industrial "
        "aceita.",
        ("Reúso", "Regulação"),
        date(2026, 1, 23),
    ),
    (
        "Dados — Capacidade instalada de reúso",
        "dados",
        "Vazão disponível por unidade e contratos industriais em vigor.",
        ("Reúso",),
        date(2026, 8, 30),
    ),
    (
        "Q&A — Reúso: segurança sanitária e aceitação pública",
        "qa",
        "A pergunta que sempre vem — \"é a mesma água?\" — respondida sem "
        "jargão.",
        ("Reúso", "Reputação"),
        date(2026, 5, 28),
    ),
    # -- Carbono ----------------------------------------------------------
    (
        "Posicionamento — Estratégia de carbono da companhia",
        "posicionamento",
        "Metas, escopo e prazo. O que a Aegea assume publicamente e o que "
        "ainda está em estudo.",
        ("Carbono",),
        date(2026, 6, 19),
    ),
    (
        "Nota técnica — Inventário de emissões: metodologia",
        "nota_tecnica",
        "Fronteiras do inventário, fatores de emissão e como os escopos 1, 2 e "
        "3 são calculados.",
        ("Carbono", "Clima"),
        date(2025, 12, 10),
    ),
    (
        "Dados — Emissões por escopo e por unidade",
        "dados",
        "A série do inventário, ano a ano, com a variação explicada.",
        ("Carbono",),
        date(2026, 8, 8),
    ),
    (
        "Q&A — Créditos de carbono e metas climáticas",
        "qa",
        "O que a companhia compensa, o que reduz e por que a distinção importa "
        "na resposta.",
        ("Carbono", "Clima"),
        date(2026, 7, 17),
    ),
    # -- Clima ------------------------------------------------------------
    (
        "Posicionamento — Adaptação climática na operação",
        "posicionamento",
        "Como a companhia trata seca, cheia e evento extremo nos planos de "
        "investimento.",
        ("Clima",),
        date(2026, 8, 21),
    ),
    (
        "Nota técnica — Plano de contingência para eventos extremos",
        "nota_tecnica",
        "Gatilhos, escalonamento e comunicação durante estiagem severa ou "
        "enchente.",
        ("Clima", "Reputação"),
        date(2026, 3, 6),
    ),
    (
        "Apresentação — Resiliência hídrica",
        "apresentacao",
        "O deck usado com governo e com investidor sobre segurança hídrica das "
        "operações.",
        ("Clima", "Cenário político"),
        date(2026, 2, 12),
    ),
    (
        "Q&A — Estiagem, racionamento e abastecimento",
        "qa",
        "O que dizer quando o reservatório baixa, e a diferença entre "
        "desabastecimento e racionamento.",
        ("Clima", "Universalização"),
        date(2026, 9, 1),
    ),
    # -- Inclusão sanitária -----------------------------------------------
    (
        "Posicionamento — Atendimento em áreas de urbanização precária",
        "posicionamento",
        "Como a companhia leva rede a comunidade sem endereço formal, e o que "
        "isso exige do poder público.",
        ("Inclusão sanitária",),
        date(2026, 7, 25),
    ),
    (
        "Dados — Ligações em comunidades e áreas de interesse social",
        "dados",
        "Ligações executadas por ano, por concessão, com população beneficiada.",
        ("Inclusão sanitária", "Universalização"),
        date(2026, 9, 5),
    ),
    (
        "Apresentação — Programa de inclusão sanitária",
        "apresentacao",
        "O deck do programa, usado com prefeitura e com organização social.",
        ("Inclusão sanitária", "Reputação"),
        date(2026, 4, 30),
    ),
    (
        "Q&A — Inadimplência, corte e responsabilidade social",
        "qa",
        "A pergunta difícil sobre corte de água em família de baixa renda, e a "
        "resposta que a companhia sustenta.",
        ("Inclusão sanitária", "Tarifa"),
        date(2026, 6, 2),
    ),
    # -- Modelo de negócio ------------------------------------------------
    (
        "Posicionamento — Concessão, PPP e subconcessão",
        "posicionamento",
        "Os três modelos em que a Aegea opera, com o que cada um transfere de "
        "risco ao privado.",
        ("Modelo de negócio",),
        date(2026, 8, 5),
    ),
    (
        "Apresentação — Como a Aegea opera",
        "apresentacao",
        "O deck institucional: presença, número de municípios e estrutura "
        "societária.",
        ("Modelo de negócio", "Reputação"),
        date(2026, 8, 28),
    ),
    (
        "Nota técnica — Estrutura contratual e matriz de risco",
        "nota_tecnica",
        "Quem responde pelo quê nos contratos, e onde o risco fica com o poder "
        "concedente.",
        ("Modelo de negócio", "Regulação"),
        date(2025, 10, 8),
    ),
    (
        "Q&A — Privatização, concessão e o que muda para o usuário",
        "qa",
        "A confusão mais comum em entrevista, desfeita em três frases.",
        ("Modelo de negócio", "Cenário político"),
        date(2026, 5, 14),
    ),
    # -- Disciplina financeira --------------------------------------------
    (
        "Posicionamento — Política de alavancagem e disciplina de capital",
        "posicionamento",
        "Os limites que a companhia se impõe, e como isso responde à pergunta "
        "sobre endividamento.",
        ("Disciplina financeira",),
        date(2026, 8, 13),
    ),
    (
        "Release — Rating reafirmado pela agência",
        "release",
        "O comunicado de manutenção da nota, com a justificativa da agência.",
        ("Disciplina financeira", "IPO"),
        date(2026, 7, 10),
    ),
    (
        "Dados — Indicadores financeiros consolidados",
        "dados",
        "Alavancagem, cobertura de juros e capex por trimestre.",
        ("Disciplina financeira",),
        date(2026, 8, 14),
    ),
    (
        "Q&A — Capex, funding e capacidade de investimento",
        "qa",
        "De onde vem o dinheiro das obras — a pergunta de investidor e a de "
        "prefeito, respondidas de formas diferentes.",
        ("Disciplina financeira", "Universalização"),
        date(2026, 6, 26),
    ),
    # -- Cenário político -------------------------------------------------
    (
        "Nota técnica — Agenda legislativa do saneamento",
        "nota_tecnica",
        "Projetos em tramitação que afetam o setor, com estágio e relator.",
        ("Cenário político",),
        date(2026, 9, 4),
    ),
    (
        "Q&A — Comunicação em ano eleitoral",
        "qa",
        "O que a companhia pode dizer, com quem pode aparecer e o que não faz "
        "em período eleitoral.",
        ("Cenário político", "Reputação"),
        date(2026, 2, 5),
    ),
    (
        "Apresentação — Mapa de stakeholders públicos",
        "apresentacao",
        "Quem decide o quê nos três níveis, e por onde passa cada pauta.",
        ("Cenário político",),
        date(2026, 6, 12),
    ),
    (
        "Posicionamento — Relacionamento institucional e conduta",
        "posicionamento",
        "Os limites do relacionamento com agente público, e a regra de registro "
        "de toda agenda.",
        ("Cenário político", "Reputação"),
        date(2026, 1, 15),
    ),
    # -- Tributário -------------------------------------------------------
    (
        "Nota técnica — Reforma tributária e efeitos no saneamento",
        "nota_tecnica",
        "O que muda com IBS e CBS para contratos de longo prazo, e o pleito "
        "setorial em curso.",
        ("Tributário", "Cenário político"),
        date(2026, 8, 22),
    ),
    (
        "Q&A — IBS e CBS nos contratos de concessão",
        "qa",
        "Como responder à pergunta \"a tarifa vai subir por causa da reforma\".",
        ("Tributário", "Tarifa"),
        date(2026, 7, 31),
    ),
    (
        "Dados — Carga tributária por concessão",
        "dados",
        "Tributos sobre receita, por contrato, com a comparação setorial.",
        ("Tributário",),
        date(2026, 5, 6),
    ),
    (
        "Posicionamento — Tratamento tributário do saneamento",
        "posicionamento",
        "Por que o setor pleiteia tratamento específico, em uma página.",
        ("Tributário", "Modelo de negócio"),
        date(2025, 8, 20),
    ),
    # -- Reputação --------------------------------------------------------
    (
        "Posicionamento — Princípios de comunicação da Aegea",
        "posicionamento",
        "As regras que valem para toda porta-voz: quem fala, sobre o quê e com "
        "que aprovação.",
        ("Reputação",),
        date(2026, 9, 5),
    ),
    (
        "Q&A — Protocolo de crise",
        "qa",
        "Os primeiros 60 minutos: quem aciona quem, o que se diz e o que não se "
        "diz antes de apurar.",
        ("Reputação",),
        date(2026, 8, 19),
    ),
    (
        "Dados — Pesquisa de imagem e reputação",
        "dados",
        "A onda mais recente do estudo de percepção, por público e por região.",
        ("Reputação", "Cenário político"),
        date(2026, 6, 24),
    ),
    (
        "Apresentação — Painel Reputacional: como usar",
        "apresentacao",
        "O passo a passo da plataforma para quem registra agenda e para quem lê "
        "os indicadores.",
        ("Reputação", "Modelo de negócio"),
        date(2026, 9, 7),
    ),
]


def _autor(sessao: Session) -> UUID:
    """O usuário que consta como quem cadastrou.

    O primeiro por e-mail, quando há gente na base — é o que faz a biblioteca
    semeada parecer cadastrada por alguém, e não brotada do nada.
    """
    achado = sessao.scalar(select(Usuario.id).order_by(Usuario.email).limit(1))
    if achado:
        return achado
    papel = sessao.scalar(select(Papel.id).where(Papel.codigo == "plataforma_edicao"))
    usuario = Usuario(
        entra_object_id="semeador-referencias",
        email="semeador@aegea.com.br",
        nome="Semeador",
        papel_id=papel,
        acesso_irrestrito=True,
    )
    sessao.add(usuario)
    sessao.flush()
    return usuario.id


def _primeira_versao(sessao, registro, *, assunto: str, atualizado_em, autor) -> None:
    """Um PDF mínimo, de verdade, no blob — e a v1 apontando para ele.

    O ARQUIVO PRECISA EXISTIR. A biblioteca guarda arquivo, e não link:
    semear uma referência sem byte criaria justamente o que ela não aceita —
    um título que não leva a lugar nenhum.

    O conteúdo é um PDF de uma página dizendo o próprio título. Não é o
    documento real — ninguém tem o acervo da Aegea aqui —, e é honesto sobre
    isso: quem abrir vê que é demonstração.
    """
    corpo = (
        f"%PDF-1.7\n% {registro.titulo}\n"
        "1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    ).encode()

    linha = Arquivo(
        caminho="",
        nome=f"{blob._sem_acento_nem_surpresa(registro.titulo).lower()}.pdf",
        tipo_conteudo="application/pdf",
        tamanho=len(corpo),
        criado_por=autor,
    )
    sessao.add(linha)
    sessao.flush()

    linha.caminho = blob.caminho_da_referencia(
        assunto=assunto,
        tipo=registro.tipo,
        titulo=registro.titulo,
        numero=1,
        arquivo_id=linha.id,
        nome=linha.nome,
    )
    blob.guardar(linha.caminho, corpo, linha.tipo_conteudo)

    registro.versoes.append(
        ReferenciaVersao(
            numero=1,
            arquivo_id=linha.id,
            atualizado_em=atualizado_em,
            criado_por=autor,
        )
    )
    sessao.flush()


def semear(sessao: Session) -> dict[str, int]:
    """Grava o acervo. Idempotente por título.

    O título é a chave porque é ele que tem índice único no banco: repetir a
    rodada não pode criar uma segunda "Q&A — Tarifa social", que é exatamente a
    duplicata que a biblioteca existe para impedir.
    """
    autor = _autor(sessao)
    id_do_tema = {t.nome: t.id for t in sessao.scalars(select(Tema))}

    ja_existem = {
        titulo.strip().lower()
        for titulo in sessao.scalars(select(Referencia.titulo)).all()
    }

    criadas = 0
    for titulo, tipo, resumo, assuntos, atualizado in ACERVO:
        if titulo.strip().lower() in ja_existem:
            continue

        desconhecidos = [nome for nome in assuntos if nome not in id_do_tema]
        if desconhecidos:
            # `raise`, e não seguir em silêncio: uma referência sem assunto não
            # é achada por ninguém, e um erro de digitação aqui produziria
            # exatamente isso — sem sintoma nenhum até alguém procurar.
            raise RuntimeError(
                f"Referência {titulo!r} aponta para assunto inexistente: "
                f"{', '.join(desconhecidos)}."
            )

        registro = Referencia(
            titulo=titulo,
            tipo=tipo,
            resumo=resumo,
            # O PRIMEIRO ASSUNTO DA TUPLA É O PRINCIPAL — o que define a pasta.
            tema_principal_id=id_do_tema[assuntos[0]],
            criado_por=autor,
        )
        registro.vinculos.extend(
            ReferenciaTema(tema_id=id_do_tema[nome]) for nome in assuntos
        )
        sessao.add(registro)
        sessao.flush()

        _primeira_versao(
            sessao,
            registro,
            assunto=assuntos[0],
            atualizado_em=atualizado,
            autor=autor,
        )
        criadas += 1

    sessao.flush()
    return {"criadas": criadas, "no_acervo": len(ACERVO)}


def principal() -> None:
    from app.banco.sessao import obter_fabrica_de_sessao

    fabrica = obter_fabrica_de_sessao()
    with fabrica() as sessao:
        resultado = semear(sessao)
        sessao.commit()
    print(f"Biblioteca: {resultado['criadas']} criadas de {resultado['no_acervo']}.")


if __name__ == "__main__":
    principal()
