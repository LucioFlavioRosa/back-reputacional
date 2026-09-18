"""Base de demonstração derivada da planilha real de 2026.

FORMA CERTA NÃO BASTA; O CONTEÚDO TAMBÉM É A DEMONSTRAÇÃO
---------------------------------------------------------
Cadeias com losango, confluência e sete níveis, em que cada nó diz "Confluência
ampla — etapa 3" e o relato é "Reunião realizada; encaminhamentos registrados.",
desenham bonito e não ensinam nada — e um grafo que não ensina nada não mostra
valor nenhum.

O que uma base gerada por forma deixa vazio:

    encaminhamentos     0        posicionamento    0        observações   0
    outra parte         0        materiais         0        registro_url  0
    pendências          8        extensões        56

`encaminhamentos` é o campo que CARREGA a causalidade — na planilha é ele que
diz "Abcon manterá o diálogo com o parlamentar", que é a frase de onde a
próxima agenda nasce. Zero preenchimentos, zero explicação de por que uma
reunião levou à outra.

O QUE MUDA
----------
As cadeias deixam de ser formas abstratas e passam a ser os ENREDOS que
realmente aconteceram, lidos das abas da planilha `Demandas de Imprensa 2026`:
Resolução CONAMA 430, tarifa mínima nos PLs 4117 e 1845, escala 6x1, insumos
químicos, Copasa, o Acordo de Leniência, o resultado do 4T25, Saneamento Salva,
reúso e o leilão da Saneago.

As formas que a versão anterior fabricava aparecem sozinhas, porque a realidade
tem todas elas:

  - LEQUE          um Fato Relevante e doze veículos no mesmo dia
  - CADEIA PROFUNDA a 430, sete reuniões de março a maio
  - LOSANGO        dois PLs de tarifa mínima que saem juntos e se reencontram
  - CONFLUÊNCIA    imprensa e ABDIB levando juntas à audiência na ALMG
  - SALTO DE CAMADA a queda dos bonds decorre do rebaixamento E da revisão
  - DUAS RAÍZES    o acordo com o MDS em 2025 e o com o MS em 2026
  - TRAVESSIA      ABCON → comitê interno → MDIC → ABIQUIM
  - SOLTAS         a maioria, como em qualquer base real

E uma raiz DE PROPÓSITO em janeiro de 2025: fora da janela padrão do painel. É
o único jeito de ver na tela o aviso de cadeia incompleta funcionando com dado
de verdade.

NÃO É UMA IMPORTAÇÃO
--------------------
Nada aqui lê o arquivo `.xlsx`. Os enredos foram lidos por uma pessoa e escritos
como texto neste módulo. É uma fixture de demonstração; a importação de planilha
continua sendo outro assunto, e não foi implementada.

Rodar de novo NÃO duplica: a função para se já houver elo em `interacao_origem`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.banco.repositorio_interacoes import RepositorioSQL
from app.banco.tabelas_acesso import Papel, Usuario
from app.banco.tabelas_catalogo import AreaPessoa, Esfera, Tema, UnidadeNegocio
from app.banco.tabelas_catalogo import Frente as FrenteTabela
from app.banco.tabelas_interacoes import InteracaoArea, InteracaoRegistro
from app.banco.tabelas_stakeholders import (
    Instituicao,
    Interlocutor,
    PessoaAegea,
    PessoaAegeaTema,
)
from app.dominio.frentes import (
    TIPO_DE_INSTITUICAO,
    Frente,
    Imprensa,
    Institucional,
    Interna,
    Investidores,
    Legislativo,
)
from app.dominio.interacao import (
    Interacao,
    MaterialDaAgenda,
    ParticipacaoAegea,
    ParticipanteDaOutraParte,
)
from app.dominio.texto import normalizar

#: `cadastro_manual`, e nao um valor proprio.
#:
#: `fonte` e vocabulario do PRODUTO — de onde o registro veio: cadastro,
#: planilha, plataforma de RI. Inventar `sintetico` poria um termo de
#: desenvolvimento numa lista que a aplicacao valida e a tela exibe.
#:
#: E `origem_aba` NAO fica vazio. Vazio, estes registros ficariam
#: indistinguiveis de cadastro manual de verdade, e so se separariam por
#: inferencia negativa contra a amostra. O campo e marca de procedencia de
#: fixture, e nao so aba de planilha importada — a amostra de handoff usa
#: `origem_aba="amostra-handoff"` pela mesma razao.
#:
#: `origem_linha` continua nulo: nao ha linha de planilha unica por tras de
#: cada agenda — os enredos foram lidos e reescritos, nao copiados.
FONTE = "cadastro_manual"
ORIGEM = "demonstracao-enredos-2026"

#: Semente fixa: a MESMA base a cada execução. Uma base diferente a cada vez
#: tornaria impossível comparar duas capturas de tela, e é assim que estas
#: telas são discutidas.
SEMENTE = 20260907

#: O "hoje" da base. Agenda depois disto ainda não aconteceu, e por isso não
#: tem clima, resultado nem relato — só expectativa.
HOJE = date(2026, 9, 7)


# ============================================================ o elenco real
#
# Nomes de instituição saídos da planilha. `tipo` decide em que frente a
# instituição aparece (ver `TIPO_DE_INSTITUICAO`), e é por isso que a mesma
# ABCON aparece como `entidade`: quem conversa com ela é a frente de parceiros.
#
# A lista é conferida contra o que já existe: a base de handoff tem 72
# instituições, e cadastrar "Valor Econômico" de novo criaria a terceira cópia
# de um veículo que já está duplicado ali.

INSTITUICOES: tuple[tuple[str, str, str], ...] = (
    # veículos — frente de imprensa
    ("Valor Econômico", "veiculo", "NA"),
    ("O Globo", "veiculo", "RJ"),
    ("Folha de S.Paulo", "veiculo", "SP"),
    ("Broadcast/Estadão", "veiculo", "SP"),
    ("Bloomberg", "veiculo", "IN"),
    ("Bloomberg Línea", "veiculo", "IN"),
    ("Debtwire", "veiculo", "IN"),
    ("LatinFinance", "veiculo", "IN"),
    ("Redd Intelligence", "veiculo", "IN"),
    ("9Fin", "veiculo", "IN"),
    ("Veja", "veiculo", "SP"),
    ("UOL", "veiculo", "SP"),
    ("Neofeed", "veiculo", "SP"),
    ("Pipeline", "veiculo", "SP"),
    ("Capital Aberto", "veiculo", "SP"),
    ("Exame", "veiculo", "SP"),
    ("CNN Infraestrutura", "veiculo", "SP"),
    ("Gazeta do Povo", "veiculo", "PR"),
    ("O Tempo", "veiculo", "MG"),
    ("Times Brasil", "veiculo", "SP"),
    ("Midia Max", "veiculo", "MS"),
    ("O Estado (MS)", "veiculo", "MS"),
    ("Canal de Piracicaba", "veiculo", "SP"),
    ("Jornal de Holambra", "veiculo", "SP"),
    ("O Diário Piracicabano", "veiculo", "SP"),
    ("Rádio Cidade Matão", "veiculo", "SP"),
    ("Diário do Nordeste", "veiculo", "CE"),
    ("Global Water Intelligence", "veiculo", "IN"),
    ("Relatório Reservado", "veiculo", "RJ"),
    ("Revista Hydro", "veiculo", "SP"),
    ("Mergermarket", "veiculo", "IN"),
    ("Brazil Journal", "veiculo", "SP"),
    # órgãos — frente de governo
    ("ANA", "orgao", "DF"),
    ("MMA", "orgao", "DF"),
    ("MDIC", "orgao", "DF"),
    ("MDS", "orgao", "DF"),
    ("MS", "orgao", "DF"),
    ("BNDES", "orgao", "RJ"),
    ("Ministério das Cidades", "orgao", "DF"),
    ("CONAMA", "orgao", "DF"),
    # entidades — parceiros e eventos
    ("ABCON", "entidade", "DF"),
    ("ABDIB", "entidade", "SP"),
    ("ABIQUIM", "entidade", "SP"),
    ("ABREMA", "entidade", "DF"),
    ("ABioGás", "entidade", "SP"),
    ("CNI", "entidade", "DF"),
    ("BMJ", "entidade", "DF"),
    ("Instituto Trata Brasil", "entidade", "SP"),
    ("ALMG", "entidade", "MG"),
    ("Itaú BBA", "entidade", "SP"),
    ("Esfera Brasil", "entidade", "SP"),
    ("MBC", "entidade", "DF"),
    ("Eurasia Group", "entidade", "IN"),
    # proposições — frente legislativa
    ("PL 4117/2025 — Tarifa mínima", "proposicao", "NA"),
    ("PL 1845/2025 — Rateio em condomínios", "proposicao", "NA"),
    ("PEC 221/2019 — Escala 6x1", "proposicao", "NA"),
    ("PL 10108/2018 — Reúso e fontes alternativas", "proposicao", "NA"),
    ("PL 1922/2022 — Água como direito humano", "proposicao", "NA"),
    ("PLP 268/2023 — IBS e CBS no saneamento", "proposicao", "NA"),
    ("PL 124/2022 — Flexibilização tarifária", "proposicao", "NA"),
    # investidores
    ("S&P Global", "investidor", "IN"),
    ("Moody's", "investidor", "IN"),
    ("Fitch Ratings", "investidor", "IN"),
    ("Itaúsa", "investidor", "SP"),
    ("GIC", "investidor", "IN"),
    ("BTG Pactual", "investidor", "SP"),
    # áreas internas
    ("Jurídico", "area_interna", "NA"),
    ("Engenharia", "area_interna", "NA"),
    ("Novos Negócios", "area_interna", "NA"),
    ("Comunicação", "area_interna", "NA"),
    ("Regulatório", "area_interna", "NA"),
)

#: Quem está do OUTRO lado da mesa. Nome, instituição, cargo.
#:
#: SEM ELES O CRM NÃO É DE STAKEHOLDERS, é de instituições: a ficha abre com o
#: quadro "Pela outra parte" vazio, e não há a quem atribuir a conversa. São os
#: jornalistas e servidores que a planilha nomeia.
INTERLOCUTORES: tuple[tuple[str, str, str], ...] = (
    ("Taís Hirata", "Valor Econômico", "Repórter de infraestrutura"),
    ("Fabiana Lopes", "Valor Econômico", "Repórter"),
    ("Glauce Cavalcanti", "O Globo", "Repórter de economia"),
    ("Cássia Almeida", "O Globo", "Repórter de economia"),
    ("Thiago Bethônico", "Folha de S.Paulo", "Repórter"),
    ("Fabiola Gomes", "Debtwire", "Repórter de crédito"),
    ("Thierry Ogier", "LatinFinance", "Correspondente"),
    ("Rachel Gamarski", "Bloomberg", "Repórter"),
    ("Elisa Calmon", "Broadcast/Estadão", "Repórter"),
    ("Cristiane Rubim", "Veja", "Editora"),
    ("Pedro Gil", "Neofeed", "Repórter"),
    ("Vladimir Goitia", "Redd Intelligence", "Repórter"),
    ("Ana Carolina Argolo", "ANA", "Diretora-presidente interina"),
    ("Iracema Freitas", "ANA", "Superintendente adjunta de fiscalização"),
    ("Thiago Gil Barreto Barros", "ANA", "Coordenador de sustentabilidade financeira"),
    ("Priscyla Conti de Mesquita", "ANA", "Coordenadora de outorga"),
    ("Luciana Xavier Capanema", "BNDES", "Chefe de departamento de saneamento"),
    ("Camile Sahb", "MDS", "Diretora de inclusão produtiva rural e acesso à água"),
    ("Vitor Leal Santana", "MDS", "Coordenador-geral"),
    ("Cristiane Godoy", "MS", "Assessoria de comunicação"),
    ("Aloysia Caldas", "MS", "Departamento de doenças transmissíveis"),
    ("Luis Felipe Giesteira", "MDIC", "Secretário de desenvolvimento industrial"),
    ("Eduardo Santos", "MMA", "Diretor de gestão de resíduos"),
    ("Yhebert Gouveia", "ABIQUIM", "Vice-presidente de operações"),
    ("Victor Figueiredo", "BMJ", "Sócio"),
    ("Tatiane Ollé", "BMJ", "Consultora legislativa"),
    ("Lucas Redecker", "PL 1845/2025 — Rateio em condomínios", "Relator na CCJC"),
    ("Thiago de Joaldo", "PL 4117/2025 — Tarifa mínima", "Autor da matéria"),
    ("Silvano Silvério Costa", "ABDIB", "Superintendente de regulação"),
    ("Rodrigo Cordeiro", "ABCON", "Consultor de eventos"),
    # Os demais veículos e entidades. Um veículo sem repórter cadastrado abre a
    # ficha com "Pela outra parte" vazio, e a agenda fica sem a única pessoa
    # que efetivamente participou dela.
    ("Bernardo Cortez", "Mergermarket", "Repórter"),
    ("Luciano Costa", "Brazil Journal", "Repórter de infraestrutura"),
    ("Redação", "UOL", "Redação de economia"),
    ("Mariana Prado", "9Fin", "Analista de crédito"),
    ("Sofia Almeida", "Pipeline", "Repórter"),
    ("Marcos Bertoldi", "Capital Aberto", "Editor"),
    ("Renata Vilela", "Exame", "Repórter de ESG"),
    ("Paulo Menezes", "CNN Infraestrutura", "Produtor"),
    ("Helena Braga", "Gazeta do Povo", "Repórter"),
    ("Diego Martins", "O Tempo", "Repórter de economia"),
    ("Carla Ribeiro", "Times Brasil", "Âncora"),
    ("Fernanda Prates", "Midia Max", "Editora"),
    ("Rodrigo Sales", "O Estado (MS)", "Repórter"),
    ("Ana Paula Lima", "Canal de Piracicaba", "Repórter"),
    ("Sérgio Vidal", "Jornal de Holambra", "Editor"),
    ("Bianca Souto", "O Diário Piracicabano", "Repórter"),
    ("Marcelo Nunes", "Rádio Cidade Matão", "Apresentador"),
    ("Juliana Farias", "Diário do Nordeste", "Repórter"),
    ("Peter Halloran", "Global Water Intelligence", "Editor"),
    ("Tomás Vieira", "Relatório Reservado", "Editor"),
    ("Larissa Amaral", "Revista Hydro", "Editora"),
    ("Marina Duarte", "Veja", "Repórter"),
    ("Rafael Antunes", "Neofeed", "Repórter"),
    ("Beatriz Salles", "Bloomberg Línea", "Repórter"),
    ("Gustavo Ferrari", "LatinFinance", "Repórter"),
    ("Clara Monteiro", "Redd Intelligence", "Analista"),
    ("Sandra Guimarães", "Ministério das Cidades", "Diretora de saneamento"),
    ("Ricardo Vasques", "CONAMA", "Secretário-executivo"),
    ("Paula Andrade", "BNDES", "Gerente de projetos"),
    ("Nilton Prado", "ABDIB", "Coordenador de comitês"),
    ("Cecília Marques", "ABREMA", "Diretora técnica"),
    ("Tiago Belmonte", "ABioGás", "Gerente de relações governamentais"),
    ("Vera Lins", "CNI", "Gerente-executiva de infraestrutura"),
    ("Otávio Lacerda", "Instituto Trata Brasil", "Diretor-executivo"),
    ("Marta Figueira", "MBC", "Coordenadora de comitês"),
    ("Igor Bastos", "Esfera Brasil", "Diretor de conteúdo"),
    ("Elaine Tavares", "Itaú BBA", "Head de infraestrutura"),
    ("Bruno Salgado", "Eurasia Group", "Analista sênior"),
    ("Marcelo Pinto", "ALMG", "Assessor da Comissão de Defesa do Consumidor"),
    ("Denise Oliveira", "S&P Global", "Analista de crédito corporativo"),
    ("Hugo Vasconcelos", "Moody's", "Analista"),
    ("Patrícia Nogueira", "Fitch Ratings", "Diretora associada"),
    ("Alberto Fontes", "Itaúsa", "Gerente de participações"),
    ("Wei Lin Tan", "GIC", "Investment director"),
    ("Rodrigo Câmara", "BTG Pactual", "Head de research de utilities"),
    ("Consultoria legislativa", "PL 1922/2022 — Água como direito humano",
     "Assessoria da comissão"),
    ("Assessoria da relatoria", "PLP 268/2023 — IBS e CBS no saneamento",
     "Assessoria parlamentar"),
    ("Gabinete do relator", "PL 124/2022 — Flexibilização tarifária",
     "Assessoria parlamentar"),
    ("Assessoria da liderança", "PEC 221/2019 — Escala 6x1",
     "Assessoria parlamentar"),
    ("Gabinete do autor", "PL 10108/2018 — Reúso e fontes alternativas",
     "Assessoria parlamentar"),
    ("Comitê interno", "Jurídico", "Coordenação"),
    ("Comitê interno de engenharia", "Engenharia", "Coordenação"),
    ("Comitê de novos negócios", "Novos Negócios", "Coordenação"),
    ("Comitê de comunicação", "Comunicação", "Coordenação"),
    ("Núcleo regulatório", "Regulatório", "Coordenação"),
)

#: Quem representa a Aegea, e SOBRE O QUE responde.
#:
#: A última coluna é o que sustenta a regra de "fora do escopo" — agenda
#: conduzida por quem não responde por aquele assunto. O ORM já nomeava a
#: regra em `PessoaAegeaTema` e nada a preenchia: doze pessoas cadastradas,
#: zero assuntos vinculados, e a conta nunca podia ser feita.
PESSOAS_AEGEA: tuple[tuple[str, str, bool, tuple[str, ...]], ...] = (
    ("Radamés Casseb", "Diretor-presidente", True,
     ("Modelo de negócio", "Copasa", "IPO", "Reputação", "Universalização")),
    ("André Pires", "Diretor financeiro e de RI", True,
     ("Disciplina financeira", "IPO", "Tributário")),
    ("Andréa Melo", "Diretora de relações institucionais", True,
     ("Regulação", "Cenário político", "Universalização")),
    ("Letícia Novaes", "Gerente de relações governamentais", True,
     ("Tarifa", "Regulação", "Cenário político")),
    ("Édison Carlos", "Diretor de sustentabilidade", True,
     ("Inclusão sanitária", "Universalização", "Clima")),
    ("Márcia Costa", "Gerente de comunicação", True,
     ("Reputação",)),
    ("Rogério Tavares", "Diretor de relações institucionais", True,
     ("Regulação", "Tarifa", "Resíduos")),
    ("Bruna Camargo", "Analista de relações governamentais", False,
     ("Regulação", "Resíduos")),
    ("Joseane Dias", "Especialista regulatória", False,
     ("Regulação", "Reúso")),
    ("Maíra Sugawara", "Coordenadora de projetos sociais", False,
     ("Inclusão sanitária",)),
    ("Yaroslav Neto", "Diretor de resíduos", True,
     ("Resíduos", "Biometano", "Carbono")),
    ("Alexandre Perufo", "Diretor de operações", True,
     ("Reúso", "Clima")),
)


# ============================================================== os enredos


@dataclass(frozen=True)
class Passo:
    """Uma agenda de um enredo, com o texto que ela realmente teve.

    `chave` só existe dentro do enredo: é como um passo diz de qual outro
    decorre sem precisar de id, que só existe depois de gravar.
    """

    chave: str
    quando: date
    frente: Frente
    instituicao: str
    pauta: str
    origens: tuple[str, ...] = ()
    expectativa: str | None = None
    relato: str | None = None
    encaminhamentos: str | None = None
    posicionamento: str | None = None
    pendencias: str | None = None
    status: str = "confirmada"
    clima: str | None = None
    resultado: str | None = None
    tier: int = 2
    uf: str = "NA"
    esfera: str = "federal"
    unidade: str | None = None
    modalidade: str | None = "online"
    local: str | None = None
    temas: tuple[str, ...] = ()
    aegea: tuple[str, ...] = ()
    #: (nome, presença) — o PRIMEIRO é o principal.
    outra_parte: tuple[tuple[str, str], ...] = ()
    #: (momento, título, url)
    materiais: tuple[tuple[str, str, str], ...] = ()
    #: chaves da extensão da frente, já com os nomes do domínio.
    extensao: dict = field(default_factory=dict)
    declinado_por: str | None = None
    motivo_declinio: str | None = None
    registro_url: str | None = None
    observacoes: str | None = None

    def __post_init__(self) -> None:
        """`solicitado` com relato é um estado que o domínio não reconhece.

        Relato é o que diz que a reunião aconteceu — ver `jaAconteceu` no
        front. Um pedido sem resposta não produziu reunião, então escrever os
        dois juntos cria um registro que a fila de exceções cobra como "sem
        resposta há 30 dias" enquanto o texto ao lado narra o encontro.

        Aconteceu de verdade, num passo escrito à mão: o relato ali descrevia o
        PEDIDO, não a reunião. `raise`, e não `assert`, porque `python -O`
        remove asserções e uma invariante que some conforme a flag de execução
        não é invariante.
        """
        if self.status == "solicitado" and (self.relato or "").strip():
            raise ValueError(
                f"Passo {self.chave!r}: `solicitado` não pode ter relato. "
                "Relato é o que marca que a reunião aconteceu; se ela "
                "aconteceu, a situação não é `solicitado`. Se o texto descreve "
                "o pedido, ele pertence a `pauta` ou `expectativa`."
            )


ACERVO = "https://acervo.aegea.com.br/relinst"


def _leniencia(veiculo: str, dia: int, chave: str) -> Passo:
    """Um dos doze pedidos que o mesmo Fato Relevante gerou no mesmo dia.

    Escrito como função porque são doze registros que diferem só no veículo: a
    repetição literal esconderia justamente o que é igual em todos — o
    posicionamento, que é o ponto do enredo.
    """
    return Passo(
        chave=chave,
        quando=date(2026, 2, dia),
        frente=Frente.IMPRENSA,
        instituicao=veiculo,
        origens=("len-fr",),
        pauta="Acordo de Leniência / Fato Relevante",
        expectativa="Sustentar a mesma resposta em todos os veículos, sem abrir "
        "detalhe que o Fato Relevante não trouxe.",
        relato=f"{veiculo} pediu confirmação e detalhamento do Fato Relevante. "
        "Enviado o mesmo texto distribuído aos demais veículos.",
        encaminhamentos="Monitorar a publicação e registrar divergência de "
        "interpretação, se houver.",
        posicionamento="Em Fato Relevante publicado em 05/02/2026, a Companhia "
        "informou a celebração do acordo e reiterou que os fatos apurados são "
        "anteriores à atual administração.",
        status="confirmada",
        clima="neutro",
        resultado="mantido",
        tier=3,
        temas=("Reputação", "Disciplina financeira"),
        aegea=("Márcia Costa",),
        extensao={"formato": "informacoes_email", "data_atendida": date(2026, 2, dia)},
    )


ENREDOS: tuple[tuple[str, tuple[Passo, ...]], ...] = (
    # ------------------------------------------------------------------ 1
    (
        "Acordo de Leniência: um Fato Relevante, doze pedidos",
        (
            Passo(
                chave="len-fr",
                quando=date(2026, 2, 4),
                frente=Frente.IMPRENSA,
                instituicao="UOL",
                pauta="Acordo de Leniência / Fato Relevante",
                expectativa="Responder com o texto do Fato Relevante e conter a "
                "pauta antes que ela se espalhe.",
                relato="Primeiro pedido de posicionamento sobre o acordo. A "
                "resposta virou o texto-padrão usado nos onze pedidos seguintes.",
                encaminhamentos="Preparar distribuição simultânea para os demais "
                "veículos assim que o Fato Relevante for publicado.",
                posicionamento="A Companhia informou a celebração do acordo e "
                "reiterou que os fatos apurados são anteriores à atual "
                "administração.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=1,
                temas=("Reputação", "Disciplina financeira"),
                aegea=("Márcia Costa", "Radamés Casseb"),
                outra_parte=(("Redação", "presente"),),
                materiais=(
                    (
                        "apoio",
                        "Fato Relevante — Acordo de Leniência",
                        f"{ACERVO}/fato-relevante-leniencia.pdf",
                    ),
                    (
                        "produzido",
                        "Texto-padrão de posicionamento",
                        f"{ACERVO}/posicionamento-leniencia.docx",
                    ),
                ),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 2, 4),
                },
            ),
            _leniencia("Bloomberg", 12, "len-01"),
            _leniencia("Veja", 12, "len-02"),
            _leniencia("Midia Max", 12, "len-03"),
            _leniencia("O Tempo", 12, "len-04"),
            _leniencia("O Estado (MS)", 12, "len-05"),
            _leniencia("Valor Econômico", 12, "len-06"),
            _leniencia("Canal de Piracicaba", 12, "len-07"),
            _leniencia("Jornal de Holambra", 12, "len-08"),
            _leniencia("O Diário Piracicabano", 12, "len-09"),
            _leniencia("Rádio Cidade Matão", 12, "len-10"),
            _leniencia("Times Brasil", 13, "len-11"),
        ),
    ),
    # ------------------------------------------------------------------ 2
    (
        "Resultado do 4T25: do rebaixamento à queda dos bonds",
        (
            Passo(
                chave="4t-sp",
                quando=date(2026, 3, 31),
                frente=Frente.INVESTIDORES,
                instituicao="S&P Global",
                pauta="Revisão de rating corporativo",
                expectativa="Demonstrar a trajetória de desalavancagem antes da "
                "decisão do comitê.",
                relato="A agência comunicou o rebaixamento da nota, citando "
                "alavancagem acima do previsto e o adiamento da divulgação dos "
                "resultados do 4T25.",
                encaminhamentos="Preparar resposta pública e alinhar a mensagem "
                "com o time de RI antes do mercado abrir.",
                pendencias="Definir se haverá call com investidores após a "
                "publicação dos resultados.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Disciplina financeira", "IPO"),
                aegea=("André Pires",),
                modalidade="online",
                local="Videoconferência",
                extensao={"tipo_investidor": "rating", "formato": "videoconferencia"},
                materiais=(
                    (
                        "obtido",
                        "Relatório de rating — S&P",
                        f"{ACERVO}/rating-sp-2026.pdf",
                    ),
                ),
            ),
            Passo(
                chave="4t-uol",
                quando=date(2026, 4, 1),
                frente=Frente.IMPRENSA,
                instituicao="UOL",
                origens=("4t-sp",),
                pauta="Posicionamento após o rebaixamento pela S&P Global",
                expectativa="Enquadrar o rebaixamento como movimento setorial e "
                "não como deterioração isolada.",
                relato="Repórter pediu posicionamento no mesmo dia da divulgação "
                "do relatório.",
                encaminhamentos="Acompanhar se o texto publicado repete a leitura "
                "da agência sem a resposta da companhia.",
                posicionamento="A Aegea informa que mantém fundamentos "
                "operacionais sólidos, com crescimento consistente de receita e "
                "plano de investimentos preservado.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=1,
                temas=("Disciplina financeira",),
                aegea=("Márcia Costa",),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 4, 1),
                    "data_publicacao": date(2026, 4, 1),
                    "link_materia": "https://economia.uol.com.br/noticias/",
                    "mensagens_chave": ("Solidez financeira", "Plano de investimentos"),
                },
            ),
            Passo(
                chave="4t-redd",
                quando=date(2026, 4, 1),
                frente=Frente.IMPRENSA,
                instituicao="Redd Intelligence",
                origens=("4t-sp",),
                pauta="Posicionamento após o rebaixamento pela S&P Global",
                expectativa="Manter a mesma resposta dada aos demais veículos.",
                relato="Pedido de posicionamento para leitores de crédito.",
                encaminhamentos="Sem desdobramento imediato.",
                posicionamento="Companhia não quis comentar além do já divulgado.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                temas=("Disciplina financeira",),
                aegea=("Márcia Costa",),
                outra_parte=(("Vladimir Goitia", "presente"),),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 4, 1),
                },
            ),
            Passo(
                chave="4t-adiamento",
                quando=date(2026, 4, 2),
                frente=Frente.IMPRENSA,
                instituicao="Broadcast/Estadão",
                origens=("4t-sp",),
                pauta="Motivo do adiamento da publicação dos resultados do 4T25",
                expectativa="Explicar o adiamento sem antecipar o ajuste contábil "
                "em discussão.",
                relato="Repórter perguntou o motivo do adiamento e que tipo de "
                "ajuste contábil está em análise.",
                encaminhamentos="Publicar comunicado ao mercado antes que a "
                "ausência de resposta vire a própria notícia.",
                posicionamento="A Aegea informa que o adiamento decorre da "
                "conclusão de procedimentos de revisão e que a nova data será "
                "comunicada ao mercado.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Disciplina financeira", "IPO"),
                aegea=("Márcia Costa", "André Pires"),
                outra_parte=(("Elisa Calmon", "presente"),),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 4, 2),
                },
            ),
            Passo(
                chave="4t-lf",
                quando=date(2026, 4, 9),
                frente=Frente.IMPRENSA,
                instituicao="LatinFinance",
                origens=("4t-adiamento",),
                pauta="Questionamento sobre a publicação do resultado do 4T25",
                expectativa="Reforçar a data comunicada e evitar nova rodada de "
                "especulação.",
                relato="Repórter cobrou a data prometida, que venceu sem "
                "publicação.",
                encaminhamentos="Alinhar com o jurídico o texto a ser usado caso "
                "a data volte a mudar.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=2,
                temas=("Disciplina financeira",),
                aegea=("Márcia Costa",),
                outra_parte=(("Thierry Ogier", "presente"),),
                extensao={
                    "formato": "informacoes_email",
                    "data_atendida": date(2026, 4, 9),
                },
            ),
            Passo(
                chave="4t-debtwire",
                quando=date(2026, 4, 10),
                frente=Frente.IMPRENSA,
                instituicao="Debtwire",
                # DE DUAS CAMADAS: o adiamento e a cobrança da véspera. É o caso
                # que quebra um layout que assume aresta só entre camadas
                # vizinhas.
                origens=("4t-adiamento", "4t-lf"),
                pauta="Resultado do 4T25 não divulgado em 09/04",
                expectativa="Conter a leitura de que há problema contábil não "
                "revelado.",
                relato="Repórter apurou com investidores a desconfiança gerada "
                "pelos adiamentos sucessivos.",
                encaminhamentos="Antecipar a divulgação para a semana seguinte e "
                "convocar call com credores.",
                posicionamento="A Aegea informa que, em caráter excepcional, "
                "adiou a divulgação e que não há alteração em sua posição de "
                "liquidez.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Disciplina financeira", "Reputação"),
                aegea=("Márcia Costa", "André Pires"),
                outra_parte=(("Fabiola Gomes", "presente"),),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 4, 10),
                },
            ),
            Passo(
                chave="4t-valor",
                quando=date(2026, 4, 11),
                frente=Frente.IMPRENSA,
                instituicao="Valor Econômico",
                origens=("4t-debtwire",),
                pauta="Comentários sobre a revisão de resultados do 4T25",
                expectativa="Explicar a reapresentação sem reabrir o tema do "
                "endividamento.",
                relato="Reportagem cita a reapresentação dos resultados de 2024 e "
                "o aumento do endividamento.",
                encaminhamentos="Preparar material de apoio para o encontro de "
                "relacionamento já agendado com o veículo.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=1,
                temas=("Disciplina financeira",),
                aegea=("Márcia Costa",),
                outra_parte=(("Taís Hirata", "presente"),),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 4, 11),
                    "data_publicacao": date(2026, 4, 12),
                    "link_materia": "https://valor.globo.com/empresas/noticia/",
                },
            ),
            Passo(
                chave="4t-bonds",
                quando=date(2026, 4, 22),
                frente=Frente.IMPRENSA,
                instituicao="Broadcast/Estadão",
                # SALTO DE CAMADA: decorre do rebaixamento (camada 0) e da
                # revisão (camada 4).
                origens=("4t-sp", "4t-valor"),
                pauta="Queda dos bonds e rebaixamento de crédito por agências",
                expectativa="Separar o movimento de mercado da situação "
                "operacional das concessões.",
                relato="Matéria relaciona a queda dos bonds à desconfiança "
                "acumulada desde o rebaixamento.",
                encaminhamentos="Levar o tema ao encontro com investidores e "
                "preparar resposta para a revisão da Moody's, prevista para maio.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Disciplina financeira", "Reputação"),
                aegea=("Márcia Costa", "André Pires"),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 4, 22),
                },
            ),
            Passo(
                chave="4t-moodys",
                quando=date(2026, 5, 5),
                frente=Frente.IMPRENSA,
                instituicao="Folha de S.Paulo",
                origens=("4t-bonds",),
                pauta="Rebaixamento de nota pela Moody's",
                expectativa="Manter a narrativa de fundamentos preservados.",
                relato="Segunda agência a rebaixar a nota em cinco semanas.",
                encaminhamentos="Marcar entrevista com porta-voz para retomar a "
                "narrativa de capitalização.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Disciplina financeira",),
                aegea=("Márcia Costa",),
                outra_parte=(("Thiago Bethônico", "presente"),),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 5, 5),
                },
            ),
            Passo(
                chave="4t-neofeed",
                quando=date(2026, 5, 18),
                frente=Frente.IMPRENSA,
                instituicao="Neofeed",
                origens=("4t-moodys",),
                pauta="Participação em Copasa, rebaixamento e capitalização",
                expectativa="Retomar a agenda positiva pelo aporte dos acionistas.",
                relato="Entrevista com porta-voz para tratar dos três temas juntos.",
                encaminhamentos="Consolidar a mensagem de capitalização como eixo "
                "das próximas conversas com imprensa e investidores.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                temas=("Disciplina financeira", "Copasa", "IPO"),
                aegea=("André Pires",),
                outra_parte=(("Pedro Gil", "presente"),),
                extensao={
                    "formato": "entrevista_online",
                    "data_atendida": date(2026, 5, 18),
                    "mensagens_chave": (
                        "Capitalização por acionistas",
                        "Fundamentos operacionais",
                    ),
                },
            ),
        ),
    ),
    # ------------------------------------------------------------------ 3
    (
        "Resolução CONAMA 430: sete reuniões, de março a maio",
        (
            Passo(
                chave="430-gt",
                quando=date(2026, 3, 13),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                pauta="GT de revisão da Resolução CONAMA 430",
                expectativa="Obter a análise de impacto regulatório antes da "
                "consolidação do texto.",
                relato="A reunião do GT apresentou os resultados da consulta "
                "pública, mas sem análise de impacto regulatório. A ABCON não "
                "recebeu as planilhas de suporte.",
                encaminhamentos="Reunião do comitê de QSMS da ABCON na próxima "
                "semana para discutir os dados e a análise de impacto.",
                pendencias="Obter as planilhas de suporte da consulta pública.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Regulação", "Resíduos"),
                aegea=("Rogério Tavares", "Bruna Camargo"),
                modalidade="online",
                local="Teams",
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="430-qsms",
                quando=date(2026, 3, 19),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("430-gt",),
                pauta="Comitê Técnico e de QSMS — parâmetros da 430",
                expectativa="Sustentar a manutenção dos parâmetros atuais.",
                relato="O pleito de manutenção de parâmetros não foi acatado e a "
                "associação não vê espaço para que seja. Começa a análise da "
                "minuta artigo a artigo.",
                encaminhamentos="Distribuir a minuta às associadas para "
                "levantamento de impacto por operação.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Regulação",),
                aegea=("Bruna Camargo", "Joseane Dias"),
                extensao={"natureza_orgao": "associacao"},
                materiais=(
                    (
                        "obtido",
                        "Minuta da revisão da Resolução 430",
                        f"{ACERVO}/minuta-conama-430.pdf",
                    ),
                ),
            ),
            Passo(
                chave="430-interna",
                quando=date(2026, 3, 23),
                frente=Frente.INTERNA,
                instituicao="Regulatório",
                origens=("430-qsms",),
                pauta="Levantamento de impacto da 430 nas operações",
                expectativa="Ter número por operação antes da próxima reunião da "
                "ABCON.",
                relato="Engenharia, jurídico e meio ambiente levantaram o custo "
                "de adequação por unidade. O lodo não entra na resolução.",
                encaminhamentos="Consolidar a planilha de impacto e enviar à "
                "ABCON até 01/04.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=2,
                temas=("Regulação", "Resíduos"),
                aegea=("Joseane Dias", "Bruna Camargo"),
                extensao={
                    "natureza": "demanda",
                    "cumprimento": "interno",
                    "complexidade": "alta",
                    "prazo_dias": 10,
                    "data_retorno": date(2026, 4, 1),
                },
            ),
            Passo(
                chave="430-abril",
                quando=date(2026, 4, 2),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                # CONFLUÊNCIA: a reunião de março e o levantamento interno.
                origens=("430-qsms", "430-interna"),
                pauta="Comitê Técnico e de SSMA — consolidação da posição",
                expectativa="Chegar com número próprio à negociação com o MMA.",
                relato="Consolidada a posição do setor com base nos "
                "levantamentos das associadas, incluindo o da Aegea.",
                encaminhamentos="Solicitar reunião técnica com o MMA e pedir "
                "apoio da ANA na intermediação.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                temas=("Regulação",),
                aegea=("Bruna Camargo", "Joseane Dias", "Rogério Tavares"),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="430-pressao",
                quando=date(2026, 4, 10),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("430-abril",),
                pauta="Pressão política para deliberar antes das eleições",
                expectativa="Ganhar tempo para a negociação técnica.",
                relato="O tema avançou com intensificação da pressão política "
                "para deliberação antes das eleições. A ABCON passou a atuar com "
                "apoio da ANA.",
                encaminhamentos="Nova rodada de reuniões institucionais, com "
                "apoio da ANA, e reforço da estratégia de sensibilização.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=1,
                temas=("Regulação", "Cenário político"),
                aegea=("Rogério Tavares",),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="430-tecnica",
                quando=date(2026, 4, 17),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("430-pressao",),
                pauta="Negociação técnica da minuta com o MMA",
                expectativa="Flexibilizar parâmetros e preservar dispositivos "
                "específicos do saneamento.",
                relato="O tema evoluiu para fase técnica, com foco na "
                "flexibilização de parâmetros.",
                encaminhamentos="Agendar reunião direta com o MMA para maio.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                temas=("Regulação",),
                aegea=("Rogério Tavares", "Bruna Camargo"),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="430-mma",
                quando=date(2026, 5, 15),
                frente=Frente.GOVERNO,
                instituicao="MMA",
                origens=("430-tecnica",),
                pauta="Reunião técnica sobre a revisão da Resolução 430",
                expectativa="Obter compromisso de prazo de adequação escalonado.",
                relato="O ministério recebeu a proposta técnica do setor e "
                "sinalizou abertura para prazo de adequação diferenciado.",
                encaminhamentos="Enviar nota técnica com a proposta de "
                "escalonamento em quinze dias.",
                pendencias="Definir quem assina a nota técnica pelo setor.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Regulação",),
                aegea=("Rogério Tavares", "Andréa Melo"),
                outra_parte=(("Eduardo Santos", "presente"),),
                modalidade="presencial",
                local="Brasília, sede do MMA",
                extensao={
                    "natureza_orgao": "executivo",
                    "cargo_interlocutor": "Diretor de gestão de resíduos",
                },
            ),
            Passo(
                chave="430-balanco",
                quando=date(2026, 5, 29),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("430-mma",),
                pauta="Balanço da negociação da Resolução 430",
                expectativa="Fechar a posição do setor antes da câmara técnica.",
                relato="Apresentado o retorno do MMA e o desenho do prazo "
                "escalonado.",
                encaminhamentos="Acompanhar a publicação da minuta final e "
                "preparar comunicação às associadas.",
                status="confirmada",
                clima="neutro",
                resultado="avancou",
                tier=2,
                temas=("Regulação",),
                aegea=("Bruna Camargo",),
                extensao={"natureza_orgao": "associacao"},
            ),
        ),
    ),
    # ------------------------------------------------------------------ 4
    (
        "Tarifa mínima: dois projetos que se reencontram",
        (
            Passo(
                chave="tar-agenda",
                quando=date(2026, 2, 13),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                pauta="Projeto de Lei 1845/2025 — cobrança em condomínios",
                expectativa="Enquadrar o projeto como risco tarifário para o "
                "setor inteiro.",
                relato="A ABCON apresentou o projeto, que proíbe a cobrança "
                "individual de unidades em condomínios com hidrômetro único. A "
                "proposta foi avaliada como potencialmente danosa.",
                encaminhamentos="Monitoramento legislativo do projeto e "
                "interlocução com o relator na comissão competente.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=1,
                temas=("Tarifa", "Regulação"),
                aegea=("Rogério Tavares", "Letícia Novaes"),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="tar-1845",
                quando=date(2026, 3, 6),
                frente=Frente.LEGISLATIVO,
                instituicao="PL 1845/2025 — Rateio em condomínios",
                origens=("tar-agenda",),
                pauta="Agenda com o relator na CCJC",
                expectativa="Apresentar o impacto tarifário antes do parecer.",
                relato="O relator recebeu o setor e pediu dados de impacto por "
                "faixa de consumo.",
                encaminhamentos="Manter o diálogo com o parlamentar e enviar os "
                "dados solicitados.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Tarifa",),
                aegea=("Letícia Novaes",),
                outra_parte=(("Lucas Redecker", "presente"),),
                modalidade="presencial",
                local="Brasília, Câmara dos Deputados",
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "em_comissao",
                    "prioridade": "alta",
                    "ementa": "Veda a cobrança individualizada em condomínios "
                    "com medidor único.",
                },
            ),
            Passo(
                chave="tar-4117",
                quando=date(2026, 3, 25),
                frente=Frente.LEGISLATIVO,
                instituicao="PL 4117/2025 — Tarifa mínima",
                origens=("tar-agenda",),
                pauta="Reunião com o autor da matéria",
                expectativa="Construir alternativa que preserve a tarifa mínima.",
                relato="O autor recebeu a associação e sinalizou disposição para "
                "discutir texto alternativo.",
                encaminhamentos="Elaborar substitutivo e apresentar ao autor "
                "antes da designação do relator.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=1,
                uf="DF",
                temas=("Tarifa",),
                aegea=("Letícia Novaes",),
                outra_parte=(("Thiago de Joaldo", "presente"),),
                modalidade="presencial",
                local="Brasília, Câmara dos Deputados",
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "apresentada",
                    "prioridade": "alta",
                    "ementa": "Veda a cobrança de tarifa mínima na prestação dos "
                    "serviços de abastecimento e esgoto.",
                },
            ),
            Passo(
                chave="tar-risco",
                quando=date(2026, 4, 10),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                # LOSANGO: os dois projetos que saíram da mesma agenda voltam a
                # se encontrar aqui.
                origens=("tar-1845", "tar-4117"),
                pauta="Risco político após alinhamento entre autor e relator",
                expectativa="Evitar tramitação acelerada sem debate técnico.",
                relato="O tema evoluiu com agravamento do risco político: autor e "
                "relator são do mesmo estado e querem votar parecer favorável.",
                encaminhamentos="Combinar duas frentes — atuação para evitar "
                "tramitação acelerada e desenvolvimento de substitutivo alinhado "
                "às normas de referência.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Tarifa", "Cenário político"),
                aegea=("Rogério Tavares", "Letícia Novaes"),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="tar-urgencia",
                quando=date(2026, 4, 17),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("tar-risco",),
                pauta="Urgência aprovada na Câmara dos Deputados",
                expectativa="Segurar a votação até haver texto alternativo.",
                relato="Foi aprovada urgência ao projeto, o que intensificou o "
                "risco regulatório.",
                encaminhamentos="Manter a construção do substitutivo como "
                "principal frente.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Tarifa",),
                aegea=("Letícia Novaes",),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="tar-substitutivo",
                quando=date(2026, 4, 24),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("tar-urgencia",),
                pauta="Substitutivo como plano de contingência",
                expectativa="Ter texto pronto sem antecipar a discussão.",
                relato="Avaliação interna de um texto substitutivo já elaborado. "
                "Diferentemente da estratégia anterior, o texto não será "
                "apresentado enquanto o projeto não avançar.",
                encaminhamentos="Monitorar a tramitação e manter o substitutivo "
                "guardado como contingência.",
                pendencias="Validar o texto com o jurídico das associadas.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=1,
                temas=("Tarifa",),
                aegea=("Letícia Novaes", "Rogério Tavares"),
                extensao={"natureza_orgao": "associacao"},
                materiais=(
                    (
                        "produzido",
                        "Minuta de substitutivo — tarifa mínima",
                        f"{ACERVO}/substitutivo-tarifa-minima.docx",
                    ),
                ),
            ),
            Passo(
                chave="tar-art12",
                quando=date(2026, 5, 18),
                frente=Frente.LEGISLATIVO,
                instituicao="PL 4117/2025 — Tarifa mínima",
                origens=("tar-substitutivo",),
                pauta="Substitutivo incorpora o art. 12 da norma de referência",
                expectativa="Alinhar o texto legal à norma da ANA.",
                relato="O substitutivo apresentado traz para o texto o art. 12 da "
                "norma de referência da ANA, com prazo de adaptação.",
                encaminhamentos="Sugerir nomes para a relatoria na CDC.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Tarifa", "Regulação"),
                aegea=("Letícia Novaes",),
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "em_comissao",
                    "prioridade": "alta",
                },
            ),
            Passo(
                chave="tar-assessoria",
                quando=date(2026, 5, 25),
                frente=Frente.LEGISLATIVO,
                instituicao="PL 1845/2025 — Rateio em condomínios",
                origens=("tar-substitutivo",),
                pauta="Reunião com a assessoria do relator, com a CNI",
                expectativa="Somar a indústria à posição do saneamento.",
                relato="A associação se reuniu com a assessoria do relator; a CNI "
                "também esteve presente e reforçou o pleito.",
                encaminhamentos="Levar a minuta à consultoria legislativa da "
                "Câmara pela liderança.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Tarifa",),
                aegea=("Letícia Novaes",),
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "em_comissao",
                    "prioridade": "media",
                },
            ),
        ),
    ),
    # ------------------------------------------------------------------ 5
    (
        "Escala 6x1: do custo ao plenário",
        (
            Passo(
                chave="6x1-capex",
                quando=date(2026, 3, 13),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                pauta="Impacto da escala 6x1 no CAPEX",
                expectativa="Quantificar o custo antes de o tema virar votação.",
                relato="O cenário mais provável é a redução de 44 para 40 horas, "
                "com aumento de custo entre 9% e 12% na operação.",
                encaminhamentos="Levantar o impacto por associada e levar o número "
                "consolidado à CNI.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                temas=("Cenário político", "Disciplina financeira"),
                aegea=("Rogério Tavares",),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="6x1-cni",
                quando=date(2026, 3, 27),
                frente=Frente.PARCEIROS,
                instituicao="CNI",
                origens=("6x1-capex",),
                pauta="Adesão ao manifesto da indústria sobre a escala 6x1",
                expectativa="Entrar na articulação da indústria em vez de agir "
                "isolado.",
                relato="A associação aderiu ao manifesto da CNI, com abordagem "
                "moderada, buscando evitar confronto direto e postergar a "
                "discussão.",
                encaminhamentos="Manter o alinhamento institucional com a CNI "
                "sobre o tema.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=2,
                uf="DF",
                temas=("Cenário político",),
                aegea=("Andréa Melo",),
                modalidade="presencial",
                local="Brasília, sede da CNI",
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="6x1-ccjc",
                quando=date(2026, 4, 14),
                frente=Frente.LEGISLATIVO,
                instituicao="PEC 221/2019 — Escala 6x1",
                origens=("6x1-cni",),
                pauta="Em pauta na CCJC, pendente de parecer",
                expectativa="Impedir a apreciação antes do debate técnico.",
                relato="A matéria entrou em pauta na CCJC sem parecer. A "
                "associação é divergente.",
                encaminhamentos="Estruturar dados de impacto tarifário para "
                "subsidiar a interlocução com parlamentares.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                uf="DF",
                temas=("Cenário político", "Tarifa"),
                aegea=("Letícia Novaes",),
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "pronta_para_pauta",
                    "prioridade": "alta",
                },
            ),
            Passo(
                chave="6x1-tarifa",
                quando=date(2026, 4, 17),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("6x1-ccjc",),
                pauta="Estimativa de impacto de 5% na tarifa",
                expectativa="Transformar o custo operacional em argumento "
                "tarifário, que é o que sensibiliza o parlamentar.",
                relato="Consolidada a estimativa de 5% de impacto na tarifa, "
                "usada como insumo técnico.",
                encaminhamentos="Distribuir o material às associadas para uso nas "
                "agendas parlamentares.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                temas=("Tarifa", "Cenário político"),
                aegea=("Rogério Tavares", "Letícia Novaes"),
                extensao={"natureza_orgao": "associacao"},
                materiais=(
                    (
                        "produzido",
                        "Nota técnica — impacto da escala 6x1 na tarifa",
                        f"{ACERVO}/nota-tecnica-6x1.pdf",
                    ),
                ),
            ),
            Passo(
                chave="6x1-plenario",
                quando=date(2026, 4, 24),
                frente=Frente.LEGISLATIVO,
                instituicao="PEC 221/2019 — Escala 6x1",
                origens=("6x1-tarifa",),
                pauta="Aprovada na CCJ e encaminhada ao plenário",
                expectativa="Emendar o texto já que a aprovação não foi evitada.",
                relato="A aprovação na CCJ elevou o grau de risco regulatório. A "
                "atuação passa a incluir participação na construção de emendas.",
                encaminhamentos="Associadas devem contribuir com sugestões de "
                "emendas.",
                pendencias="Prazo de envio das sugestões: uma semana.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                uf="DF",
                temas=("Cenário político",),
                aegea=("Letícia Novaes",),
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "aprovada",
                    "prioridade": "alta",
                },
            ),
            Passo(
                chave="6x1-emendas",
                quando=date(2026, 5, 29),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("6x1-plenario",),
                pauta="Consolidação das emendas do setor",
                expectativa="Chegar ao plenário com texto de emenda pronto.",
                relato="Consolidadas as sugestões das associadas em três emendas.",
                encaminhamentos="Protocolar as emendas pela liderança e acompanhar "
                "a inclusão na ordem do dia.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                temas=("Cenário político",),
                aegea=("Letícia Novaes",),
                extensao={"natureza_orgao": "associacao"},
            ),
        ),
    ),
    # ------------------------------------------------------------------ 6
    (
        "Insumos químicos: do PAC à nota técnica no MDIC",
        (
            Passo(
                chave="pac-alta",
                quando=date(2026, 4, 17),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                pauta="Alta de 150% no preço do policloreto de alumínio",
                expectativa="Confirmar se a alta é generalizada ou de um "
                "fornecedor.",
                relato="Identificado aumento de cerca de 150% no preço do PAC, "
                "insumo essencial na coagulação do tratamento de água.",
                encaminhamentos="Estruturar atuação coordenada via comitê de "
                "suprimentos, com avaliação de alternativas de fornecimento.",
                status="confirmada",
                clima="tenso",
                resultado="recuou",
                tier=1,
                temas=("Disciplina financeira", "Regulação"),
                aegea=("Rogério Tavares",),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="pac-comite",
                quando=date(2026, 4, 24),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("pac-alta",),
                pauta="Comitê de suprimentos — custo e abastecimento",
                expectativa="Passar do diagnóstico à ação.",
                relato="O tema evoluiu de diagnóstico para ação estruturada, com "
                "agravamento da preocupação sobre preços e risco de escassez.",
                encaminhamentos="Reunião do comitê de suprimentos em 28 de abril "
                "para definir medidas e articulação com o governo.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=1,
                temas=("Disciplina financeira",),
                aegea=("Rogério Tavares", "Bruna Camargo"),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="pac-interno",
                quando=date(2026, 4, 28),
                frente=Frente.INTERNA,
                instituicao="Engenharia",
                origens=("pac-comite",),
                pauta="Alternativas de fornecimento de coagulante",
                expectativa="Ter alternativa técnica antes de a articulação "
                "chegar ao governo.",
                relato="Levantadas duas alternativas de coagulante com "
                "qualificação técnica e prazo de homologação.",
                encaminhamentos="Enviar o comparativo técnico à ABCON para compor "
                "a nota ao MDIC.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=2,
                temas=("Disciplina financeira",),
                aegea=("Alexandre Perufo",),
                extensao={
                    "natureza": "demanda",
                    "cumprimento": "interno",
                    "complexidade": "media",
                    "prazo_dias": 15,
                    "data_retorno": date(2026, 5, 12),
                },
            ),
            Passo(
                chave="pac-abiquim",
                quando=date(2026, 4, 29),
                frente=Frente.PARCEIROS,
                instituicao="ABIQUIM",
                origens=("pac-comite",),
                pauta="Variação de preços de resina de PVC e PEAD",
                expectativa="Entender a curva de preços pela ótica da indústria "
                "química.",
                relato="A associação da indústria química avaliou curva de "
                "recuperação de três a cinco anos para o setor.",
                encaminhamentos="Buscar posição conjunta com a ABIQUIM para levar "
                "ao MDIC.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                uf="SP",
                temas=("Disciplina financeira",),
                aegea=("Andréa Melo",),
                outra_parte=(("Yhebert Gouveia", "presente"),),
                modalidade="presencial",
                local="São Paulo, sede da ABIQUIM",
                extensao={
                    "natureza_orgao": "associacao",
                    "cargo_interlocutor": "Vice-presidente de operações",
                },
            ),
            Passo(
                chave="pac-mdic",
                quando=date(2026, 5, 15),
                frente=Frente.GOVERNO,
                instituicao="MDIC",
                # CONFLUÊNCIA: o levantamento técnico interno e a posição da
                # indústria química chegam juntos ao ministério.
                origens=("pac-interno", "pac-abiquim"),
                pauta="Nota técnica sobre insumos químicos do saneamento",
                expectativa="Obter tratamento tarifário para o coagulante "
                "importado.",
                relato="Apresentada a nota técnica com o comparativo de custos e a "
                "posição conjunta do setor e da indústria química.",
                encaminhamentos="Ministério pediu dados de volume por operação "
                "para avaliar medida específica.",
                pendencias="Consolidar volumes das associadas até 30/05.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Disciplina financeira", "Tributário"),
                aegea=("Andréa Melo", "Rogério Tavares"),
                outra_parte=(("Luis Felipe Giesteira", "presente"),),
                modalidade="presencial",
                local="Brasília, sede do MDIC",
                extensao={
                    "natureza_orgao": "executivo",
                    "cargo_interlocutor": "Secretário de desenvolvimento industrial",
                },
                materiais=(
                    (
                        "produzido",
                        "Nota técnica — insumos químicos",
                        f"{ACERVO}/nota-tecnica-insumos.pdf",
                    ),
                ),
            ),
            Passo(
                chave="pac-parceria",
                quando=date(2026, 5, 29),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                origens=("pac-mdic",),
                pauta="Parceria com a ABIQUIM para acompanhamento de preços",
                expectativa="Institucionalizar o monitoramento em vez de reagir a "
                "cada alta.",
                relato="Definida a parceria para acompanhamento conjunto da curva "
                "de preços dos insumos.",
                encaminhamentos="Formalizar o acordo e definir a periodicidade do "
                "boletim de preços.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=2,
                temas=("Disciplina financeira",),
                aegea=("Rogério Tavares",),
                extensao={"natureza_orgao": "associacao"},
            ),
        ),
    ),
    # ------------------------------------------------------------------ 7
    (
        "Copasa: de duas conversas paralelas ao leilão",
        (
            Passo(
                chave="cop-bloomberg",
                quando=date(2026, 1, 30),
                frente=Frente.IMPRENSA,
                instituicao="Bloomberg",
                pauta="Privatização da Copasa",
                expectativa="Não confirmar interesse antes do edital.",
                relato="Primeiro pedido de posicionamento sobre a privatização.",
                encaminhamentos="Manter a resposta padrão até haver edital "
                "publicado.",
                posicionamento="A Companhia monitora atentamente as novas "
                "oportunidades, avaliando licitações em todo o país.",
                status="declinado",
                declinado_por="aegea",
                motivo_declinio="Sem edital publicado, qualquer confirmação "
                "anteciparia decisão que ainda não foi tomada.",
                clima="neutro",
                resultado="mantido",
                tier=1,
                temas=("Copasa", "Leilões"),
                aegea=("Márcia Costa",),
                outra_parte=(("Rachel Gamarski", "presente"),),
                extensao={"formato": "posicionamento"},
            ),
            Passo(
                chave="cop-bmj",
                quando=date(2026, 2, 10),
                frente=Frente.PARCEIROS,
                instituicao="BMJ",
                pauta="Alinhamento institucional sobre a Copasa",
                expectativa="Mapear o cenário político em Minas antes do edital.",
                relato="A consultoria apresentou o mapa de atores na Assembleia e "
                "o calendário provável do processo.",
                encaminhamentos="Acompanhar a tramitação na ALMG e preparar "
                "posição para a audiência pública.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Copasa", "Cenário político"),
                aegea=("Andréa Melo",),
                outra_parte=(
                    ("Victor Figueiredo", "presente"),
                    ("Tatiane Ollé", "presente"),
                ),
                modalidade="presencial",
                local="Brasília, escritório da BMJ",
                extensao={"natureza_orgao": "escritorio"},
            ),
            Passo(
                chave="cop-valor-fev",
                quando=date(2026, 2, 2),
                frente=Frente.IMPRENSA,
                instituicao="Valor Econômico",
                origens=("cop-bloomberg",),
                pauta="Privatização da Copasa",
                expectativa="Manter a mesma resposta dada à Bloomberg.",
                relato="Segundo veículo a procurar em três dias.",
                encaminhamentos="Registrar que a pauta está circulando e avisar a "
                "diretoria.",
                posicionamento="A Companhia monitora atentamente as novas "
                "oportunidades.",
                status="declinado",
                declinado_por="aegea",
                motivo_declinio="Mesma razão do pedido anterior.",
                clima="neutro",
                resultado="mantido",
                tier=1,
                temas=("Copasa",),
                aegea=("Márcia Costa",),
                outra_parte=(("Taís Hirata", "presente"),),
                extensao={"formato": "entrevista_email"},
            ),
            Passo(
                chave="cop-abdib",
                quando=date(2026, 3, 17),
                frente=Frente.PARCEIROS,
                instituicao="ABDIB",
                origens=("cop-bmj",),
                pauta="Comitê de Recursos Hídricos — modelo de privatização",
                expectativa="Discutir o modelo com os demais interessados sem "
                "revelar posição.",
                relato="Apresentado o modelo de privatização da companhia mineira "
                "e o desenho do sócio de referência.",
                encaminhamentos="Levar dúvidas sobre a cláusula de não "
                "concorrência ao jurídico.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                uf="SP",
                temas=("Copasa", "Leilões", "Modelo de negócio"),
                aegea=("Rogério Tavares",),
                outra_parte=(("Silvano Silvério Costa", "presente"),),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="cop-almg",
                quando=date(2026, 4, 15),
                frente=Frente.EVENTOS,
                instituicao="ALMG",
                # CONFLUÊNCIA de duas conversas que correram em paralelo: a
                # pressão da imprensa e a preparação institucional.
                origens=("cop-valor-fev", "cop-abdib"),
                pauta="Audiência pública sobre a privatização da Copasa",
                expectativa="Acompanhar o debate sem se expor como parte.",
                relato="A Comissão de Defesa do Consumidor debateu o modelo. "
                "Houve menções à Aegea como possível interessada.",
                encaminhamentos="Preparar porta-voz para o caso de a pauta migrar "
                "para a imprensa nacional.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=1,
                uf="MG",
                esfera="estadual",
                temas=("Copasa", "Cenário político"),
                aegea=("Letícia Novaes",),
                modalidade="presencial",
                local="Belo Horizonte, ALMG",
                extensao={
                    "natureza_orgao": "legislativo",
                    "nome_evento": "Audiência pública — privatização da Copasa",
                },
                materiais=(
                    (
                        "obtido",
                        "Notas taquigráficas da audiência",
                        f"{ACERVO}/almg-audiencia-copasa.pdf",
                    ),
                ),
            ),
            Passo(
                chave="cop-valor-rel",
                quando=date(2026, 4, 27),
                frente=Frente.IMPRENSA,
                instituicao="Valor Econômico",
                origens=("cop-almg",),
                pauta="Encontro de relacionamento — Copasa entre os temas",
                expectativa="Recuperar a relação com o veículo depois de duas "
                "recusas.",
                relato="Encontro presencial com o diretor-presidente para tratar "
                "trajetória, aumento de capital e a Copasa.",
                encaminhamentos="Enviar dados de investimento por concessão como "
                "material de apoio.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                temas=("Copasa", "Modelo de negócio"),
                aegea=("Radamés Casseb", "Márcia Costa"),
                outra_parte=(("Taís Hirata", "presente"),),
                modalidade="presencial",
                local="São Paulo, sede da Aegea",
                extensao={
                    "formato": "encontro_relacionamento",
                    "data_atendida": date(2026, 4, 27),
                    "mensagens_chave": ("Modelo de negócio", "Disciplina de capital"),
                },
            ),
            Passo(
                chave="cop-bbg-rel",
                quando=date(2026, 4, 27),
                frente=Frente.IMPRENSA,
                instituicao="Bloomberg",
                origens=("cop-almg",),
                pauta="Encontro de relacionamento — Copasa entre os temas",
                expectativa="Mesma abertura dada ao Valor, para não criar "
                "exclusividade.",
                relato="Encontro presencial com o diretor-presidente.",
                encaminhamentos="Manter a cadência trimestral de encontros com os "
                "dois veículos.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                temas=("Copasa", "Modelo de negócio"),
                aegea=("Radamés Casseb",),
                outra_parte=(("Rachel Gamarski", "presente"),),
                modalidade="presencial",
                local="São Paulo, sede da Aegea",
                extensao={
                    "formato": "encontro_relacionamento",
                    "data_atendida": date(2026, 4, 27),
                },
            ),
            Passo(
                chave="cop-sabesp",
                quando=date(2026, 5, 21),
                frente=Frente.IMPRENSA,
                instituicao="O Globo",
                origens=("cop-valor-rel", "cop-bbg-rel"),
                pauta="Participação no leilão após a saída da Sabesp",
                expectativa="Não confirmar antes do credenciamento formal.",
                relato="Com a saída da concorrente, a pergunta passou a ser "
                "diária.",
                encaminhamentos="Definir com o jurídico o momento de confirmar "
                "publicamente o credenciamento.",
                status="declinado",
                declinado_por="aegea",
                motivo_declinio="Confirmação dependia do credenciamento formal, "
                "ainda não concluído.",
                clima="tenso",
                resultado="mantido",
                tier=1,
                temas=("Copasa", "Leilões"),
                aegea=("Márcia Costa",),
                outra_parte=(("Glauce Cavalcanti", "presente"),),
                extensao={"formato": "posicionamento"},
            ),
            Passo(
                chave="cop-edital",
                quando=date(2026, 5, 27),
                frente=Frente.IMPRENSA,
                instituicao="Veja",
                origens=("cop-sabesp",),
                pauta="Posicionamento sobre o adiamento do edital da Copasa",
                expectativa="Tratar o adiamento como fato do processo, não como "
                "revés.",
                relato="O adiamento do edital reabriu a especulação sobre o "
                "interesse da companhia.",
                encaminhamentos="Reavaliar a estratégia de comunicação quando o "
                "novo calendário for publicado.",
                posicionamento="A Aegea segue todas as exigências e procedimentos "
                "legais previstos nos processos licitatórios.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                temas=("Copasa", "Leilões"),
                aegea=("Márcia Costa",),
                outra_parte=(("Cristiane Rubim", "presente"),),
                extensao={
                    "formato": "posicionamento",
                    "data_atendida": date(2026, 5, 27),
                },
            ),
        ),
    ),
    # ------------------------------------------------------------------ 8
    (
        "Saneamento Salva: uma raiz em 2025",
        (
            # A RAIZ FICA FORA DA JANELA PADRÃO DO PAINEL, de propósito. É o
            # único jeito de ver na tela, com dado real, o aviso de que a cadeia
            # começou antes do que o recorte mostra.
            Passo(
                chave="ss-mds-2025",
                quando=date(2025, 1, 8),
                frente=Frente.GOVERNO,
                instituicao="MDS",
                pauta="Cerimônia de assinatura do Acordo de Cooperação",
                expectativa="Firmar o acordo que abre a agenda social da "
                "companhia com o governo federal.",
                relato="Assinado o acordo de cooperação técnica que originou as "
                "frentes de cisternas e de saúde.",
                encaminhamentos="Definir os dois primeiros programas a serem "
                "executados sob o acordo.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Inclusão sanitária", "Universalização"),
                aegea=("Andréa Melo",),
                modalidade="presencial",
                local="Brasília, sede do MDS",
                extensao={"natureza_orgao": "executivo"},
            ),
            Passo(
                chave="ss-ms",
                quando=date(2026, 4, 14),
                frente=Frente.GOVERNO,
                instituicao="MS",
                origens=("ss-mds-2025",),
                pauta="Acordo de Cooperação Aegea e Ministério da Saúde",
                expectativa="Ligar a campanha de saúde à operação de saneamento.",
                relato="O ministério apresentou o pipeline de campanhas e pediu "
                "dados de cobertura por município.",
                encaminhamentos="Ministério encaminhará o pipeline de campanhas; "
                "a companhia enviará a cobertura por município.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Inclusão sanitária",),
                aegea=("Andréa Melo", "Bruna Camargo"),
                outra_parte=(
                    ("Cristiane Godoy", "presente"),
                    ("Aloysia Caldas", "presente"),
                ),
                modalidade="presencial",
                local="Brasília, sede do Ministério da Saúde",
                extensao={
                    "natureza_orgao": "executivo",
                    "cargo_interlocutor": "Assessoria de comunicação",
                },
            ),
            Passo(
                chave="ss-marajo",
                quando=date(2026, 5, 13),
                frente=Frente.GOVERNO,
                instituicao="MDS",
                origens=("ss-mds-2025",),
                pauta="Programa Cisternas no Marajó",
                expectativa="Aperfeiçoar os sistemas sanitários das comunidades "
                "atendidas.",
                relato="O ministério informou a intenção de aperfeiçoar os "
                "sistemas sanitários e pediu proposta técnica.",
                encaminhamentos="Apresentar proposta técnica de sistema sanitário "
                "adaptado à realidade ribeirinha.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="PA",
                temas=("Inclusão sanitária", "Universalização"),
                aegea=("Andréa Melo", "Maíra Sugawara", "Édison Carlos"),
                outra_parte=(
                    ("Camile Sahb", "presente"),
                    ("Vitor Leal Santana", "presente"),
                ),
                modalidade="presencial",
                local="Brasília, sede do MDS",
                extensao={
                    "natureza_orgao": "executivo",
                    "cargo_interlocutor": "Diretoria de inclusão produtiva rural",
                },
            ),
            Passo(
                chave="ss-perenidade",
                quando=date(2026, 6, 2),
                frente=Frente.GOVERNO,
                instituicao="MDS",
                origens=("ss-marajo",),
                pauta="Perenidade e manutenção dos sistemas no Marajó",
                expectativa="Resolver quem mantém o sistema depois da entrega.",
                relato="O ministério pontuou duas preocupações: perenidade da "
                "solução e responsabilidade pela manutenção.",
                encaminhamentos="Desenhar modelo de manutenção com a prefeitura e "
                "trazer resposta na próxima reunião.",
                pendencias="Definir quem responde pela manutenção após a entrega.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=1,
                uf="PA",
                temas=("Inclusão sanitária",),
                aegea=("Bruna Camargo", "Maíra Sugawara"),
                outra_parte=(("Camile Sahb", "presente"),),
                extensao={"natureza_orgao": "executivo"},
            ),
            Passo(
                chave="ss-campanha",
                quando=date(2026, 6, 3),
                frente=Frente.GOVERNO,
                instituicao="MS",
                # CONFLUÊNCIA das duas frentes abertas pelo acordo de 2025.
                origens=("ss-ms", "ss-perenidade"),
                pauta="Saneamento Salva — pipeline de campanhas",
                expectativa="Lançar a campanha conjunta antes do período "
                "eleitoral.",
                relato="Definido o recorte das campanhas por doença de veiculação "
                "hídrica e as praças prioritárias, incluindo o Marajó.",
                encaminhamentos="Ministério enviará por e-mail o levantamento das "
                "doenças por município; a companhia responderá com o calendário "
                "de campo.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=1,
                uf="DF",
                temas=("Inclusão sanitária", "Reputação"),
                aegea=("Bruna Camargo", "Maíra Sugawara", "Márcia Costa"),
                outra_parte=(("Cristiane Godoy", "presente"),),
                extensao={"natureza_orgao": "executivo"},
                materiais=(
                    (
                        "produzido",
                        "Plano de campanhas — Saneamento Salva",
                        f"{ACERVO}/saneamento-salva-plano.pptx",
                    ),
                ),
            ),
        ),
    ),
    # ------------------------------------------------------------------ 9
    (
        "Reúso: da norma da ANA ao data center",
        (
            Passo(
                chave="reuso-norma",
                quando=date(2026, 3, 13),
                frente=Frente.PARCEIROS,
                instituicao="ABCON",
                pauta="Norma de reúso de água proposta pela ANA",
                expectativa="Evitar norma que engesse iniciativas já em operação.",
                relato="A norma proposta visa disciplinar o reúso, mas a "
                "associação argumenta que não é necessária, pois já existem "
                "iniciativas funcionando.",
                encaminhamentos="Levar o argumento à agência na celebração do Dia "
                "Mundial da Água e preparar contribuição à consulta.",
                status="confirmada",
                clima="tenso",
                resultado="mantido",
                tier=2,
                temas=("Reúso", "Regulação"),
                aegea=("Rogério Tavares", "Joseane Dias"),
                extensao={"natureza_orgao": "associacao"},
            ),
            Passo(
                chave="reuso-ana",
                quando=date(2026, 3, 24),
                frente=Frente.GOVERNO,
                instituicao="ANA",
                origens=("reuso-norma",),
                pauta="Celebração do Dia Mundial da Água",
                expectativa="Abrir canal técnico sobre a norma de reúso.",
                relato="Na celebração, a agência recebeu o pleito do setor sobre "
                "a norma de reúso e indicou o canal de contribuição.",
                encaminhamentos="Protocolar a contribuição técnica dentro do prazo "
                "da consulta.",
                status="confirmada",
                clima="propositivo",
                resultado="avancou",
                tier=2,
                uf="DF",
                temas=("Reúso", "Regulação"),
                aegea=("Andréa Melo", "Bruna Camargo"),
                outra_parte=(("Ana Carolina Argolo", "presente"),),
                modalidade="presencial",
                local="Brasília, sede da ANA",
                extensao={
                    "natureza_orgao": "executivo",
                    "cargo_interlocutor": "Diretora-presidente interina",
                    "nome_evento": "Dia Mundial da Água 2026",
                },
            ),
            Passo(
                chave="reuso-hydro",
                quando=date(2026, 4, 7),
                frente=Frente.IMPRENSA,
                instituicao="Revista Hydro",
                origens=("reuso-ana",),
                pauta="Reúso da água para indústrias e data centers",
                expectativa="Posicionar o reúso como negócio, e não como "
                "obrigação regulatória.",
                # SEM RELATO: o pedido de entrevista chegou e ainda não foi
                # respondido. O que estava escrito aqui descrevia o PEDIDO, não
                # a reunião — e relato, neste domínio, é o que diz que a reunião
                # houve. A pauta acima já conta do que se trata.
                relato=None,
                encaminhamentos="Preparar o porta-voz com os números de Itaboraí.",
                status="solicitado",
                clima=None,
                resultado=None,
                tier=3,
                unidade="Reuso Itaboraí",
                temas=("Reúso", "Modelo de negócio"),
                aegea=("Alexandre Perufo",),
                extensao={"formato": "entrevista_online"},
            ),
            Passo(
                chave="reuso-pl",
                quando=date(2026, 5, 4),
                frente=Frente.LEGISLATIVO,
                instituicao="PL 10108/2018 — Reúso e fontes alternativas",
                origens=("reuso-norma",),
                pauta="Reúso e fontes alternativas — contato com o gabinete",
                expectativa="Segurar a deliberação até haver texto acordado.",
                relato="A associação contatou o gabinete do relator, que afirmou "
                "não haver pressa para deliberar.",
                encaminhamentos="Buscar reunião com o assessor do relator para "
                "apresentar o texto do setor.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                uf="DF",
                temas=("Reúso",),
                aegea=("Letícia Novaes",),
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "em_comissao",
                    "prioridade": "media",
                    "ementa": "Dispõe sobre o reúso de água e fontes alternativas "
                    "de abastecimento.",
                },
            ),
            Passo(
                chave="reuso-acordo",
                quando=date(2026, 5, 18),
                frente=Frente.LEGISLATIVO,
                instituicao="PL 10108/2018 — Reúso e fontes alternativas",
                origens=("reuso-pl",),
                pauta="Acordo para não deliberar segue mantido",
                expectativa="Chegar às eleições sem votação.",
                relato="Longa reunião com o assessor do relator; o acordo para "
                "não deliberar agora está mantido.",
                encaminhamentos="Reavaliar em agosto, conforme o calendário da "
                "Casa.",
                status="confirmada",
                clima="propositivo",
                resultado="mantido",
                tier=2,
                uf="DF",
                temas=("Reúso",),
                aegea=("Letícia Novaes",),
                extensao={
                    "casa": "camara_deputados",
                    "tramitacao": "em_comissao",
                    "prioridade": "media",
                },
            ),
        ),
    ),
    # ----------------------------------------------------------------- 10
    (
        "Leilão da Saneago: a suspensão que virou pauta",
        (
            Passo(
                chave="san-suspensao",
                quando=date(2026, 3, 16),
                frente=Frente.IMPRENSA,
                instituicao="Broadcast/Estadão",
                pauta="Suspensão do leilão da Saneago a pedido da Aegea",
                expectativa="Explicar o pedido como zelo pelo edital, e não como "
                "obstrução.",
                relato="Repórter solicitou posicionamento sobre a suspensão do "
                "leilão pedida pela companhia.",
                encaminhamentos="Preparar material técnico com os pontos do "
                "edital questionados.",
                status="declinado",
                declinado_por="aegea",
                motivo_declinio="Matéria sub judice no momento do pedido.",
                clima="tenso",
                resultado="mantido",
                tier=1,
                uf="GO",
                esfera="estadual",
                temas=("Leilões",),
                aegea=("Márcia Costa",),
                extensao={"formato": "posicionamento"},
            ),
            Passo(
                chave="san-valor",
                quando=date(2026, 3, 18),
                frente=Frente.IMPRENSA,
                instituicao="Valor Econômico",
                origens=("san-suspensao",),
                pauta="Detalhes dos pedidos para suspender o leilão da Saneago",
                expectativa="Levar a discussão para o mérito técnico do edital.",
                relato="Entrevista com a diretoria jurídica sobre os pontos "
                "questionados.",
                encaminhamentos="Enviar a íntegra da impugnação como material de "
                "apoio.",
                status="confirmada",
                clima="neutro",
                resultado="avancou",
                tier=1,
                uf="GO",
                esfera="estadual",
                temas=("Leilões", "Regulação"),
                aegea=("Márcia Costa",),
                outra_parte=(("Taís Hirata", "presente"),),
                extensao={
                    "formato": "entrevista_online",
                    "data_atendida": date(2026, 3, 18),
                },
                materiais=(
                    (
                        "produzido",
                        "Íntegra da impugnação ao edital",
                        f"{ACERVO}/impugnacao-saneago.pdf",
                    ),
                ),
            ),
            Passo(
                chave="san-folha",
                quando=date(2026, 3, 18),
                frente=Frente.IMPRENSA,
                instituicao="Folha de S.Paulo",
                origens=("san-suspensao",),
                pauta="Detalhes dos pedidos para suspender o leilão da Saneago",
                expectativa="Mesma abertura dada ao Valor.",
                relato="Entrevista com a diretoria jurídica.",
                encaminhamentos="Acompanhar a publicação nos dois veículos no "
                "mesmo dia.",
                status="confirmada",
                clima="neutro",
                resultado="avancou",
                tier=1,
                uf="GO",
                esfera="estadual",
                temas=("Leilões",),
                aegea=("Márcia Costa",),
                outra_parte=(("Thiago Bethônico", "presente"),),
                extensao={
                    "formato": "entrevista_online",
                    "data_atendida": date(2026, 3, 18),
                },
            ),
            Passo(
                chave="san-gwi",
                quando=date(2026, 3, 23),
                frente=Frente.IMPRENSA,
                instituicao="Global Water Intelligence",
                origens=("san-valor", "san-folha"),
                pauta="Repercussão internacional do leilão da Saneago",
                expectativa="Levar a leitura técnica ao público internacional de "
                "investidores.",
                relato="Publicação internacional retomou o tema citando as duas "
                "reportagens brasileiras.",
                encaminhamentos="Registrar a repercussão no relatório mensal de "
                "imprensa.",
                status="confirmada",
                clima="neutro",
                resultado="mantido",
                tier=2,
                uf="IN",
                esfera="internacional",
                temas=("Leilões", "Reputação"),
                aegea=("Márcia Costa",),
                extensao={
                    "formato": "informacoes_email",
                    "data_atendida": date(2026, 3, 23),
                },
            ),
        ),
    ),
)


# ====================================================== as agendas soltas
#
# A MAIORIA DA BASE, como em qualquer operação real: reuniões que não abriram
# nem fecharam cadeia. O que muda em relação à versão anterior é que elas
# também têm texto — pauta da planilha, relato e encaminhamento plausíveis.
# Uma base em que só as cadeias têm conteúdo ensina a olhar só para elas.

SOLTAS_POR_FRENTE: dict[Frente, tuple[tuple[str, str, str], ...]] = {
    Frente.IMPRENSA: (
        (
            "Leilão de saneamento em Goiás",
            "Pedido de posicionamento sobre a participação no certame.",
            "Resposta enviada; acompanhar publicação.",
        ),
        (
            "Perspectivas de investimentos e expansão para 2026",
            "Jornalista pediu números do plano de investimentos do ano.",
            "Enviado o release de resultados como material de apoio.",
        ),
        (
            "Impactos de eventos climáticos extremos nas operações",
            "Entrevista para especial do Dia Mundial da Água.",
            "Publicação prevista para a semana seguinte.",
        ),
        (
            "Economia circular no saneamento",
            "Repórter enviou doze perguntas sobre reúso e resíduos.",
            "Respostas em elaboração com engenharia.",
        ),
        (
            "Modelo de atendimento ao consumidor",
            "Perguntas por e-mail sobre o processo de melhoria do atendimento.",
            "Respondido com os indicadores de satisfação do trimestre.",
        ),
        (
            "Geração de biogás a partir do tratamento de esgoto",
            "Pauta para o caderno de biocombustíveis.",
            "Agendada visita técnica à unidade.",
        ),
        (
            "Case de universalização em Manaus",
            "Editor solicitou detalhes do caso da capital amazonense.",
            "Enviado o material do case e fotos da operação.",
        ),
        (
            "Resíduos sólidos como hub de negócios no saneamento",
            "Entrevista sobre a vertical de resíduos.",
            "Acompanhar se a matéria trata da aquisição em curso.",
        ),
        (
            "Nova emissão de debêntures e bookbuilding",
            "Pedido de posicionamento sobre a operação em curso.",
            "Resposta limitada ao que consta do prospecto.",
        ),
        (
            "Metas do Marco Legal em áreas vulneráveis",
            "Entrevista por e-mail sobre inclusão sanitária.",
            "Enviados dados de cobertura por comunidade.",
        ),
        (
            "Adiamento do edital e o calendário do setor",
            "Colunista pediu leitura do calendário de leilões.",
            "Sem posicionamento adicional.",
        ),
        (
            "Prêmio Mulheres na Liderança",
            "Aspas da executiva para matéria sobre liderança feminina.",
            "Depoimento enviado e aprovado.",
        ),
    ),
    Frente.GOVERNO: (
        (
            "Pontos de lançamento de esgoto in natura — outorgas",
            "Alinhamento sobre a regularização das outorgas da unidade.",
            "Enviar o cronograma de regularização em trinta dias.",
        ),
        (
            "Cobrança de outorgas — diagnóstico e regularização",
            "Discutida a necessidade de diagnóstico dos lançamentos.",
            "Agendar reunião técnica com a superintendência.",
        ),
        (
            "Resíduos sólidos urbanos — estruturação de projetos",
            "Apresentado o pipeline de projetos de resíduos ao banco.",
            "Encaminhar estudo de viabilidade da primeira praça.",
        ),
        (
            "Superciclo de investimentos em infraestrutura",
            "Evento destacou o papel da infraestrutura no desenvolvimento.",
            "Registrar as sinalizações de crédito para o setor.",
        ),
        (
            "Avanços da regulamentação do marco legal",
            "Audiência sobre o estágio das normas de referência.",
            "Acompanhar a publicação das próximas normas.",
        ),
        (
            "Acesso a recursos públicos e condicionantes regulatórias",
            "Discussão sobre restrições de acesso por descumprimento de normas.",
            "Elaborar nota técnica sustentando a posição do setor.",
        ),
        (
            "Agenda regulatória da agência para 2026 e 2027",
            "Aberta tomada de subsídios sobre as prioridades regulatórias.",
            "Consolidar e enviar as contribuições no prazo.",
        ),
        (
            "Cofaturamento — contribuições à minuta",
            "Aprovadas as contribuições à minuta de cofaturamento.",
            "Protocolar dentro do prazo prorrogado.",
        ),
        (
            "Norma de contabilidade regulatória",
            "Preparação para reunião com a nova diretoria da agência.",
            "Alinhar posicionamento técnico antes da reunião.",
        ),
        (
            "Programa de acesso à água em comunidades rurais",
            "Ministério apresentou o desenho do programa.",
            "Avaliar aderência à área de concessão.",
        ),
    ),
    Frente.PARCEIROS: (
        (
            "Comitê de Recursos Hídricos e Saneamento Básico",
            "Reunião ordinária do comitê com a diretoria técnica.",
            "Acompanhar os temas levados à agência.",
        ),
        (
            "Comitê Legal e Tributário — reforma da tributação",
            "Apresentadas as próximas etapas da reforma tributária.",
            "Mapear impacto nas concessões e reportar ao jurídico.",
        ),
        (
            "Debêntures de infraestrutura e o papel do banco de fomento",
            "Debate sobre o cenário de financiamento da infraestrutura.",
            "Levar o tema ao comitê financeiro interno.",
        ),
        (
            "Lançamento da Agenda Legislativa do Saneamento",
            "A associação lançou a agenda legislativa do ano.",
            "Distribuir a agenda às áreas e definir prioridades.",
        ),
        (
            "Contratação de escritórios de advocacia pelo setor",
            "Apresentadas propostas dos escritórios e o modelo de rateio.",
            "Decisão adiada; retomar após a definição do rateio.",
        ),
        (
            "Sistema Nacional de Efluentes",
            "Comunicada a saída de uma associação do apoio ao sistema.",
            "Acompanhar desdobramentos regulatórios.",
        ),
        (
            "Impacto do marco regulatório nos investimentos",
            "Apresentados dados de aumento dos investimentos após o marco.",
            "Avaliar inclusão dos dados do ano na narrativa institucional.",
        ),
        (
            "Litigância predatória e o esgotamento da via administrativa",
            "Recurso especial afetado pelo tribunal superior.",
            "Reunir dados de judicialização das associadas.",
        ),
        (
            "Planejamento do comitê de QSMS",
            "Apresentado o plano de atividades do comitê.",
            "Estruturar grupo de trabalho sobre gestão de lodo.",
        ),
        (
            "Mercado de carbono no saneamento",
            "Relatado o andamento da regulamentação do mercado.",
            "Encaminhar nota técnica sobre metodologia.",
        ),
        (
            "Assembleia Geral Ordinária da associação",
            "Deliberação sobre a prestação de contas do exercício.",
            "Manter a estratégia de racionalização de custos.",
        ),
        (
            "Atualização político-econômica do trimestre",
            "Consultoria apresentou o cenário para o segundo semestre.",
            "Distribuir a leitura às diretorias.",
        ),
    ),
    Frente.EVENTOS: (
        (
            "Audiência pública sobre norma de instrumentos negociais",
            "Acompanhamento da audiência convocada pela agência.",
            "Registrar os pleitos apresentados pelo setor.",
        ),
        (
            "Encontro nacional do setor de saneamento",
            "Participação institucional no encontro anual.",
            "Avaliar patrocínio da próxima edição.",
        ),
        (
            "Seminário sobre resíduos sólidos e economia circular",
            "Painel sobre destinação e aproveitamento energético.",
            "Convidar o palestrante para o comitê interno.",
        ),
        (
            "Prêmio de mulheres na infraestrutura",
            "Reconhecimento a trajetórias femininas no setor.",
            "Divulgar internamente e nas redes.",
        ),
        (
            "Fórum de investimentos em infraestrutura",
            "Painel com investidores sobre o pipeline do setor.",
            "Registrar contatos para a agenda de RI.",
        ),
        (
            "Solenidade de posse de nova diretoria de entidade",
            "Presença institucional na posse.",
            "Agendar reunião com a nova diretoria.",
        ),
        (
            "Casa Parlamento — prioridades legislativas",
            "Encontro com lideranças sobre a pauta do semestre.",
            "Cruzar as prioridades com a agenda legislativa do setor.",
        ),
        (
            "Lançamento de boletim técnico setorial",
            "Relançamento do observatório técnico do setor.",
            "Avaliar participação no comitê editorial.",
        ),
    ),
    Frente.INVESTIDORES: (
        (
            "Reunião de acompanhamento com fundo de infraestrutura",
            "Apresentado o desempenho operacional do trimestre.",
            "Enviar o material com os indicadores por concessão.",
        ),
        (
            "Conversa com analista de research sobre alavancagem",
            "Discutida a trajetória de desalavancagem.",
            "Enviar o cronograma de amortizações.",
        ),
        (
            "Roadshow com investidores internacionais",
            "Rodada de reuniões com fundos estrangeiros.",
            "Consolidar as perguntas recorrentes para o próximo call.",
        ),
        (
            "Call de resultados do trimestre",
            "Apresentação dos resultados e sessão de perguntas.",
            "Publicar a transcrição no site de RI.",
        ),
        (
            "Revisão de perspectiva por agência de rating",
            "Agência revisou a perspectiva da nota corporativa.",
            "Preparar comunicação ao mercado.",
        ),
        (
            "Conferência de infraestrutura de banco de investimento",
            "Painel com gestores sobre o setor de saneamento.",
            "Registrar os contatos gerados no evento.",
        ),
        (
            "Aporte de capital pelos acionistas de referência",
            "Discutido o desenho do aporte e o calendário.",
            "Alinhar a comunicação com o jurídico antes do anúncio.",
        ),
        (
            "Reunião com gestora sobre debêntures incentivadas",
            "Discutida a demanda para a próxima emissão.",
            "Enviar o material de bookbuilding.",
        ),
    ),
    Frente.LEGISLATIVO: (
        (
            "Acompanhamento de parecer em comissão",
            "Matéria em pauta com parecer favorável do relator.",
            "Monitorar a votação na próxima sessão.",
        ),
        (
            "Audiência pública sobre serviços de saneamento",
            "Requerimento aprovado para audiência na comissão.",
            "Articular inclusão da associação entre os convidados.",
        ),
        (
            "Projeto sobre tarifa social para microempreendedores",
            "Parecer favorável apresentado na comissão.",
            "Levantar impacto da medida nas concessões.",
        ),
        (
            "Proposta de prazo máximo de atendimento ao público",
            "Matéria em pauta com parecer contrário.",
            "Posição convergente ao parecer.",
        ),
        (
            "Alíquota reduzida de IBS e CBS para saneamento",
            "Parecer proferido pela prejudicialidade.",
            "Posição de acordo com o parecer.",
        ),
        (
            "Flexibilização tarifária em calamidade pública",
            "Novo parecer apresentado na comissão do Senado.",
            "Tentar interlocução com o relator antes da votação.",
        ),
        (
            "Destinação mínima de recursos para saneamento rural",
            "Novo parecer em análise pela associação.",
            "Posição inicialmente neutra.",
        ),
        (
            "Prevenção de enchentes e obrigações do prestador",
            "Matéria em pauta com parecer favorável.",
            "Posição favorável ao texto.",
        ),
        (
            "Proibição da prestação direta pelo poder público",
            "Matéria distribuída à comissão de constituição e justiça.",
            "Acompanhar a designação do relator.",
        ),
        (
            "Metas para redução de perdas de água",
            "Projeto em análise na comissão de meio ambiente.",
            "Levantar dados de perdas por concessão.",
        ),
    ),
    Frente.INTERNA: (
        (
            "Levantamento de estados que aderiram ao programa federal",
            "Levantamento solicitado pela área de novos negócios.",
            "E-mail enviado com a consolidação.",
        ),
        (
            "Ficha de priorização da agenda legislativa",
            "Elaborada a ficha de priorização das matérias do ano.",
            "Publicada no repositório da diretoria.",
        ),
        (
            "Núcleo regulatório — reunião semanal",
            "Apresentados os estudos com relatórios finais.",
            "Definir os próximos estudos a contratar.",
        ),
        (
            "Alinhamento sobre a carteira de resíduos",
            "Tratados os estudos em contratação e em análise.",
            "Consolidar o cronograma dos estudos.",
        ),
        (
            "Plano Clima e metas setoriais",
            "Discutido o entendimento do setor sobre metas.",
            "Levar a posição ao comitê de sustentabilidade.",
        ),
        (
            "Kick off de estudo com consultoria externa",
            "Ajustado o recorte inicial proposto pela consultoria.",
            "Revisar o plano de trabalho em quinze dias.",
        ),
        (
            "Preparação de porta-vozes para o trimestre",
            "Treinamento de mensagens-chave com a diretoria.",
            "Atualizar o material de apoio dos porta-vozes.",
        ),
        (
            "Consolidação do relatório mensal de imprensa",
            "Fechamento do relatório do mês com a agência.",
            "Distribuir às diretorias até o dia cinco.",
        ),
    ),
}

#: Quantas soltas por frente. A proporção segue a planilha: imprensa domina o
#: volume (247 de 327 registros com stakeholder informado), governo e parceiros
#: vêm depois, e a frente interna é a menor.
QUANTAS_SOLTAS: dict[Frente, int] = {
    Frente.IMPRENSA: 58,
    Frente.GOVERNO: 22,
    Frente.PARCEIROS: 24,
    Frente.EVENTOS: 14,
    Frente.INVESTIDORES: 16,
    Frente.LEGISLATIVO: 18,
    Frente.INTERNA: 8,
}

#: A SITUAÇÃO TEM TRÊS VALORES: `solicitado`, `confirmada` (Aceito) e
#: `declinado` (Negado). Todos os três respondem ao PEDIDO, e nenhum deles diz
#: se a reunião já aconteceu.
#:
#: O "já aconteceu" está no RELATO: só se escreve o relato de uma reunião
#: que houve, e por isso este semeador preenche relato apenas nas aceitas cuja
#: data passou. Ver `jaAconteceu` no front.
#:
#: A proporção segue a planilha: imprensa recusa mais (é o volume de demanda
#: que não vira pauta); a agenda institucional é quase toda aceita.
STATUS_POR_FRENTE: dict[Frente, tuple[str, ...]] = {
    Frente.IMPRENSA: (
        "confirmada", "confirmada", "confirmada", "confirmada",
        "declinado", "declinado", "solicitado", "solicitado",
    ),
    Frente.GOVERNO: ("confirmada", "confirmada", "confirmada", "solicitado"),
    Frente.PARCEIROS: ("confirmada", "confirmada", "confirmada", "confirmada"),
    Frente.EVENTOS: ("confirmada", "confirmada", "solicitado"),
    Frente.INVESTIDORES: ("confirmada", "confirmada", "solicitado", "solicitado"),
    Frente.LEGISLATIVO: ("confirmada", "confirmada", "solicitado"),
    Frente.INTERNA: ("confirmada", "confirmada", "solicitado"),
}

#: O que a companhia respondeu. Frases da própria planilha, inclusive as
#: negativas: "não comentou" é posicionamento, e registrar isso é o que
#: permite medir depois quantas vezes a companhia optou pelo silêncio.
POSICIONAMENTOS = (
    "A Aegea não comentou.",
    "Companhia não quis comentar.",
    "A Companhia monitora atentamente as novas oportunidades, avaliando "
    "licitações em todo o país.",
    "A Aegea informa que mantém fundamentos operacionais sólidos, com "
    "crescimento consistente de receita.",
    "A Aegea segue todas as exigências e procedimentos legais previstos nos "
    "processos licitatórios.",
    "Solicitação atendida pela comunicação local.",
    "A Aegea atua com disciplina de capital e plano de investimentos "
    "preservado.",
    "Sem posicionamento adicional ao já divulgado ao mercado.",
)

#: Onde o registro da agenda ficou guardado. A planilha chama de "Registro /
#: documentação", e é quase sempre um link para o acervo da companhia.
REGISTROS = (
    ("apoio", "Material de apoio da agenda"),
    ("apoio", "Perguntas recebidas"),
    ("produzido", "Resposta enviada"),
    ("produzido", "Ata da reunião"),
    ("obtido", "Apresentação do interlocutor"),
    ("obtido", "Nota técnica recebida"),
)

FORMATOS_DE_IMPRENSA = (
    "posicionamento", "posicionamento", "posicionamento",
    "entrevista_online", "entrevista_email", "informacoes_email",
    "entrevista_presencial", "entrevista_telefone", "encontro_relacionamento",
    "depoimento",
)


#: As mensagens que a companhia tenta emplacar. Saíram da coluna
#: "Mensagens-chave" da planilha.
MENSAGENS_CHAVE = (
    "Modelo de negócio",
    "Evolução do setor",
    "Solidez financeira",
    "Universalização",
    "Disciplina de capital",
    "Redução de perdas",
    "Inclusão sanitária",
    "Investimento por concessão",
)

#: O que se QUER da agenda, por frente. É o lado previsto do registro, e é a
#: distância entre ele e o relato que o painel mede — por isso vale para toda
#: agenda, e não só para a que ainda não aconteceu.
EXPECTATIVAS: dict[Frente, str] = {
    Frente.IMPRENSA: "Responder sem ampliar a pauta, mantendo a mensagem já "
    "usada nos demais veículos.",
    Frente.GOVERNO: "Sair da reunião com um encaminhamento datado, e não com "
    "uma sinalização genérica.",
    Frente.PARCEIROS: "Alinhar a posição do setor antes de a discussão chegar "
    "ao regulador.",
    Frente.EVENTOS: "Marcar presença institucional e mapear quem mais está "
    "tratando do tema.",
    Frente.INVESTIDORES: "Sustentar a trajetória de desalavancagem com número, "
    "e não com narrativa.",
    Frente.LEGISLATIVO: "Impedir que a matéria avance sem debate técnico.",
    Frente.INTERNA: "Fechar o insumo dentro do prazo para não travar a frente "
    "que depende dele.",
}


def _expectativa(frente: Frente, pauta: str) -> str:
    """O previsto, dito na primeira pessoa de quem vai à reunião."""
    return f"{EXPECTATIVAS[frente]} Assunto: {pauta[0].lower()}{pauta[1:]}."


# =============================================================== a semeadura


def semear(sessao: Session) -> int:
    """Cria os enredos e as agendas soltas. Devolve quantas criou."""
    from app.banco.tabelas_interacoes import InteracaoOrigem

    # A EXISTÊNCIA DE LINHAGEM é a marca. A amostra de handoff tem 60 registros
    # e nenhum elo; qualquer elo aqui veio deste semeador.
    if sessao.scalar(select(func.count()).select_from(InteracaoOrigem)):
        return 0

    sorte = random.Random(SEMENTE)
    elenco = _elenco(sessao)
    autor = _autor(sessao)
    _alinhar_porta_vozes_da_amostra(sessao, elenco, sorte)
    repositorio = RepositorioSQL(sessao)
    criadas = 0

    for _nome, passos in ENREDOS:
        # Os ids só existem depois de gravar, e um passo precisa do id de outro:
        # a tradução chave → id acontece à medida que a cadeia é criada, e é por
        # isso que os passos vêm em ordem cronológica dentro do enredo.
        ids: dict[str, UUID] = {}
        for passo in passos:
            agenda = _do_passo(passo, elenco, autor, ids)
            ids[passo.chave] = repositorio.adicionar(agenda).id
            criadas += 1
        sessao.flush()

    for frente, quantas in QUANTAS_SOLTAS.items():
        for indice in range(quantas):
            agenda = _uma_solta(frente, indice, elenco, autor, sorte)
            repositorio.adicionar(agenda)
            criadas += 1
            if indice % 20 == 0:
                sessao.flush()

    sessao.flush()
    return criadas


def _alinhar_porta_vozes_da_amostra(
    sessao: Session, elenco: dict, sorte: random.Random
) -> None:
    """Faz a amostra de handoff obedecer à regra que este semeador introduz.

    A amostra atribui porta-voz por RODÍZIO — `PORTA_VOZES[indice % 6]` —, o
    que é razoável para ver o painel de exposição e não tem relação nenhuma com
    o assunto da agenda. Sob a regra de "fora do escopo", dois terços daquela
    fatia aparecem como desvio, contra um quinto das agendas que este semeador
    cria: a exceção viraria ruído por artefato de fixture, e uma exceção
    ruidosa é uma exceção que alguém desliga.

    Aqui a atribuição respeita o assunto na maioria dos casos. Os
    ~12% que restam são deliberados: uma base em que todo mundo fala do que lhe
    cabe nunca mostraria a regra funcionando.
    """
    from app.banco.tabelas_interacoes import (
        InteracaoPessoaAegea,
        InteracaoRegistro,
        InteracaoTema,
    )

    agendas = sessao.scalars(
        select(InteracaoRegistro).where(
            InteracaoRegistro.origem_aba == "amostra-handoff"
        )
    ).all()

    por_pessoa = elenco["temas_por_pessoa"]

    for agenda in agendas:
        temas = set(
            sessao.scalars(
                select(InteracaoTema.tema_id).where(
                    InteracaoTema.interacao_id == agenda.id
                )
            )
        )
        if not temas:
            continue

        vinculos = sessao.scalars(
            select(InteracaoPessoaAegea).where(
                InteracaoPessoaAegea.interacao_id == agenda.id,
                InteracaoPessoaAegea.papel == "porta_voz",
            )
        ).all()
        if not vinculos:
            continue

        ja_responde = any(por_pessoa.get(v.pessoa_aegea_id, set()) & temas for v in vinculos)
        if ja_responde or sorte.random() < 0.12:
            continue

        donas = [pid for pid, assuntos in por_pessoa.items() if assuntos & temas]
        if not donas:
            continue

        # Troca só o PRIMEIRO porta-voz: quem acompanhava continua na agenda.
        escolhida = sorte.choice(donas)
        if any(v.pessoa_aegea_id == escolhida for v in vinculos):
            continue
        vinculos[0].pessoa_aegea_id = escolhida

    sessao.flush()


def _do_passo(passo: Passo, elenco: dict, autor: UUID, ids: dict) -> Interacao:
    """Traduz um passo do enredo para o agregado do domínio."""
    instituicao = elenco["instituicoes"][passo.instituicao]

    return Interacao(
        frente=passo.frente,
        data_interacao=passo.quando,
        instituicao_id=instituicao.id,
        uf=passo.uf,
        status=passo.status,
        criado_por=autor,
        fonte=FONTE,
        origem_aba=ORIGEM,
        origens=tuple(ids[chave] for chave in passo.origens if chave in ids),
        pauta=passo.pauta,
        expectativa=passo.expectativa,
        relato=passo.relato,
        encaminhamentos=passo.encaminhamentos,
        posicionamento=passo.posicionamento,
        pendencias=passo.pendencias,
        observacoes=passo.observacoes,
        registro_url=passo.registro_url,
        clima=passo.clima,
        resultado=passo.resultado,
        tier=passo.tier,
        esfera_id=elenco["esferas"].get(passo.esfera),
        unidade_negocio_id=elenco["unidades"].get(passo.unidade or ""),
        modalidade=passo.modalidade,
        local=passo.local,
        declinado_por=passo.declinado_por,
        motivo_declinio=passo.motivo_declinio,
        temas=tuple(
            elenco["temas"][nome] for nome in passo.temas if nome in elenco["temas"]
        ),
        participacoes=tuple(
            ParticipacaoAegea(
                pessoa_aegea_id=elenco["pessoas"][nome].id,
                papel="porta_voz" if indice == 0 else "equipe",
                presenca="presente" if passo.quando <= HOJE else "previsto",
            )
            for indice, nome in enumerate(passo.aegea)
            if nome in elenco["pessoas"]
        ),
        outra_parte=tuple(
            ParticipanteDaOutraParte(
                interlocutor_id=elenco["interlocutores"][nome].id,
                presenca=presenca,
                # O PRIMEIRO É O PRINCIPAL. A lista manda, e a coluna
                # `interlocutor_id` é projeção dela — ver o repositório.
                principal=(indice == 0),
            )
            for indice, (nome, presenca) in enumerate(passo.outra_parte)
            if nome in elenco["interlocutores"]
        ),
        materiais=tuple(
            MaterialDaAgenda(momento=momento, titulo=titulo, url=url)
            for momento, titulo, url in passo.materiais
        ),
        extensao=_extensao(passo.frente, passo.extensao),
    )


def _extensao(frente: Frente, campos: dict):
    """A extensão da frente, ou nada quando o passo não informou."""
    if not campos:
        return None
    classe = {
        Frente.IMPRENSA: Imprensa,
        Frente.GOVERNO: Institucional,
        Frente.PARCEIROS: Institucional,
        Frente.EVENTOS: Institucional,
        Frente.LEGISLATIVO: Legislativo,
        Frente.INVESTIDORES: Investidores,
        Frente.INTERNA: Interna,
    }[frente]
    return classe(**campos)


def _registro(
    frente: Frente, indice: int, pauta: str, sorte: random.Random
) -> tuple[MaterialDaAgenda, ...]:
    """O documento que sobrou da agenda, em cerca de um terço delas.

    Nem toda reunião gera papel, e uma base em que TODAS geram ensina errado.
    Mas uma em que NENHUMA gera — a anterior tinha zero materiais em 235
    agendas — esconde a seção de documentos da ficha inteira.
    """
    if sorte.random() >= 0.32:
        return ()
    momento, titulo = sorte.choice(REGISTROS)
    return (
        MaterialDaAgenda(
            momento=momento,
            titulo=f"{titulo} — {pauta[:44]}",
            url=f"{ACERVO}/registro-{frente.value}-{indice:03d}.pdf",
        ),
    )


def _uma_solta(
    frente: Frente, indice: int, elenco: dict, autor: UUID, sorte: random.Random
) -> Interacao:
    """Uma agenda sem linhagem, com texto plausível da frente."""
    pauta, relato, encaminhamento = SOLTAS_POR_FRENTE[frente][
        indice % len(SOLTAS_POR_FRENTE[frente])
    ]
    tipo = TIPO_DE_INSTITUICAO[frente]
    candidatas = [i for i in elenco["instituicoes"].values() if i.tipo == tipo]
    instituicao = sorte.choice(candidatas)

    # Espalhadas pelo ano corrente, e não amontoadas: o painel mostra série
    # mensal, e nove meses com o mesmo número não se distinguem de um erro.
    temas_da_agenda = tuple(
        elenco["temas"][nome]
        for nome in sorte.sample(list(elenco["temas"]), sorte.choice([1, 2, 2, 3]))
    )
    quando = date(2026, 1, 5) + timedelta(days=sorte.randrange(0, 245))
    ja_aconteceu = quando <= HOJE
    status = sorte.choice(STATUS_POR_FRENTE[frente])
    if not ja_aconteceu:
        # Agenda no futuro ainda não teve resposta.
        status = "solicitado"

    # SEM RELATO é o que diz "ainda não aconteceu". Uma agenda aceita cuja data
    # já passou TEM relato — é ele que a torna elegível como origem de outra.
    aberta = status == "solicitado" or not ja_aconteceu

    # QUEM CONDUZ. Escolhido entre quem responde pelo assunto — quase sempre.
    #
    # Uma base em que todo mundo fala do que lhe cabe nunca mostraria a regra
    # de "fora do escopo" funcionando; uma em que ninguém fala tornaria o aviso
    # ruído. A proporção aqui é deliberada: cerca de uma em oito foge, que é a
    # ordem de grandeza que faz a exceção valer a pena olhar.
    pessoas = list(elenco["pessoas"].values())
    donas = [
        p
        for p in pessoas
        if elenco["temas_por_pessoa"].get(p.id, set()) & set(temas_da_agenda)
    ]
    fora_do_escopo = sorte.random() < 0.12
    if donas and not fora_do_escopo:
        principal = sorte.choice(donas)
    else:
        principal = sorte.choice([p for p in pessoas if p not in donas] or pessoas)
    apoio = [p for p in pessoas if p is not principal]
    dela = [principal] + sorte.sample(apoio, sorte.choice([0, 0, 1]))
    da_instituicao = [
        i for i in elenco["interlocutores"].values()
        if i.instituicao_id == instituicao.id
    ]

    return Interacao(
        frente=frente,
        data_interacao=quando,
        instituicao_id=instituicao.id,
        uf=instituicao.uf or "NA",
        status=status,
        criado_por=autor,
        fonte=FONTE,
        origem_aba=ORIGEM,
        pauta=pauta,
        expectativa=_expectativa(frente, pauta),
        relato=relato if not aberta else None,
        encaminhamentos=encaminhamento if not aberta else None,
        posicionamento=(
            sorte.choice(POSICIONAMENTOS)
            if frente is Frente.IMPRENSA and not aberta
            else None
        ),
        pendencias=(
            f"{encaminhamento[:-1]} — sem prazo definido."
            if not aberta and sorte.random() < 0.18
            else None
        ),
        clima=sorte.choice(["propositivo", "neutro", "neutro", "tenso"])
        if not aberta
        else None,
        clima_esperado=sorte.choice(["propositivo", "neutro"]) if aberta else None,
        resultado=sorte.choice(["avancou", "mantido", "mantido", "recuou"])
        if not aberta
        else None,
        tier=sorte.choice([1, 2, 2, 3, 3, 3]),
        esfera_id=elenco["esferas"]["federal"],
        modalidade=sorte.choice(["presencial", "online", "online", "hibrida"]),
        local=sorte.choice(
            ["Brasília, sede do órgão", "Teams", "São Paulo, sede da Aegea", None]
        ),
        temas=temas_da_agenda,
        participacoes=tuple(
            ParticipacaoAegea(
                pessoa_aegea_id=pessoa.id,
                papel="porta_voz" if posicao == 0 else "equipe",
                presenca="presente" if not aberta else "previsto",
            )
            for posicao, pessoa in enumerate(dela)
        ),
        outra_parte=(
            (
                ParticipanteDaOutraParte(
                    interlocutor_id=sorte.choice(da_instituicao).id,
                    presenca="presente" if not aberta else "previsto",
                    principal=True,
                ),
            )
            if da_instituicao
            else ()
        ),
        materiais=_registro(frente, indice, pauta, sorte),
        extensao=_extensao(
            frente,
            {
                "formato": sorte.choice(FORMATOS_DE_IMPRENSA),
                "data_atendida": quando if not aberta else None,
                "data_publicacao": (
                    quando + timedelta(days=sorte.randrange(1, 21))
                    if not aberta and sorte.random() < 0.55
                    else None
                ),
                "link_materia": (
                    f"https://{instituicao.nome_normalizado.split()[0]}.com.br/"
                    f"noticia/{quando.isoformat()}"
                    if not aberta and sorte.random() < 0.55
                    else None
                ),
                "mensagens_chave": tuple(
                    sorte.sample(MENSAGENS_CHAVE, sorte.choice([1, 2, 2, 3]))
                ),
            }
            if frente is Frente.IMPRENSA
            else {"natureza_orgao": "executivo"}
            if frente in (Frente.GOVERNO,)
            else {"natureza_orgao": "associacao"}
            if frente in (Frente.PARCEIROS, Frente.EVENTOS)
            else {"casa": "camara_deputados", "tramitacao": "em_comissao"}
            if frente is Frente.LEGISLATIVO
            else {"tipo_investidor": sorte.choice(["fundo", "research", "rating"])}
            if frente is Frente.INVESTIDORES
            else {
                "natureza": "demanda",
                "cumprimento": "interno",
                "complexidade": sorte.choice(["baixa", "media", "alta"]),
                "prazo_dias": sorte.choice([5, 10, 15]),
            },
        ),
    )


# ============================================================= o cadastro


def _elenco(sessao: Session) -> dict:
    """Garante instituições, pessoas e interlocutores; devolve por NOME.

    Por nome, e não por índice: um enredo diz `instituicao="ABCON"`, e é isso
    que se lê ao revisar o texto. Índice numérico esconderia uma troca.

    REAPROVEITA o que já existe. A base de handoff tem 72 instituições, e
    cadastrar "Valor Econômico" de novo criaria a terceira cópia de um veículo
    que já está duplicado ali.
    """
    # `normalizar`, e NAO `.lower()`. A diferenca sao os acentos, e o efeito
    # medido de usar `.lower()` aqui foram seis duplicatas: a amostra de
    # handoff gravou "valor economico" e a busca por "valor econômico" nao
    # achava — entao este semeador criava a segunda linha do mesmo veiculo.
    instituicoes: dict[str, Instituicao] = {}
    for nome, tipo, uf in INSTITUICOES:
        achada = sessao.scalar(
            select(Instituicao).where(
                Instituicao.nome_normalizado == normalizar(nome),
                Instituicao.tipo == tipo,
            )
        )
        if achada is None:
            achada = Instituicao(
                nome=nome, nome_normalizado=normalizar(nome), tipo=tipo, uf=uf
            )
            sessao.add(achada)
            sessao.flush()
        instituicoes[nome] = achada

    interlocutores: dict[str, Interlocutor] = {}
    for nome, casa, cargo in INTERLOCUTORES:
        achado = sessao.scalar(
            select(Interlocutor).where(
                Interlocutor.nome_normalizado == normalizar(nome)
            )
        )
        if achado is None:
            achado = Interlocutor(
                nome=nome,
                nome_normalizado=normalizar(nome),
                instituicao_id=instituicoes[casa].id,
                cargo=cargo,
            )
            sessao.add(achado)
            sessao.flush()
        interlocutores[nome] = achado

    temas_por_nome = {t.nome: t.id for t in sessao.scalars(select(Tema))}

    pessoas: dict[str, PessoaAegea] = {}
    for nome, cargo, porta_voz, assuntos in PESSOAS_AEGEA:
        achada = sessao.scalar(
            select(PessoaAegea).where(
                PessoaAegea.nome_normalizado == normalizar(nome)
            )
        )
        if achada is None:
            achada = PessoaAegea(
                nome=nome,
                nome_normalizado=normalizar(nome),
                cargo=cargo,
                eh_porta_voz=porta_voz,
            )
            sessao.add(achada)
            sessao.flush()
        elif achada.cargo is None:
            # A base de handoff cadastrou os seis porta-vozes SEM cargo. A ficha
            # mostra "Radamés Casseb" e não diz o que ele é, que é metade da
            # informação de quem representou a companhia.
            achada.cargo = cargo
        pessoas[nome] = achada
        sessao.flush()

        # OS ASSUNTOS AUTORIZADOS. Sem eles a pergunta "o especialista está
        # falando do assunto dele?" não tem como ser respondida, e a regra de
        # "fora do escopo" fica sem base para comparar.
        ja_tem = set(
            sessao.scalars(
                select(PessoaAegeaTema.tema_id).where(
                    PessoaAegeaTema.pessoa_aegea_id == achada.id
                )
            )
        )
        for assunto in assuntos:
            tema_id = temas_por_nome.get(assunto)
            if tema_id is not None and tema_id not in ja_tem:
                sessao.add(
                    PessoaAegeaTema(pessoa_aegea_id=achada.id, tema_id=tema_id)
                )

    sessao.flush()

    return {
        "instituicoes": instituicoes,
        "interlocutores": interlocutores,
        "pessoas": pessoas,
        "temas_por_pessoa": {
            pessoa.id: {
                temas_por_nome[a] for a in assuntos if a in temas_por_nome
            }
            for (nome, _cargo, _pv, assuntos), pessoa in zip(
                PESSOAS_AEGEA, pessoas.values(), strict=True
            )
        },
        "temas": {t.nome: t.id for t in sessao.scalars(select(Tema))},
        "esferas": {e.codigo: e.id for e in sessao.scalars(select(Esfera))},
        "unidades": {u.nome: u.id for u in sessao.scalars(select(UnidadeNegocio))},
    }


def _autor(sessao: Session) -> UUID:
    achado = sessao.scalar(select(Usuario.id).order_by(Usuario.email).limit(1))
    if achado:
        return achado
    papel = sessao.scalar(select(Papel.id).where(Papel.codigo == "plataforma_edicao"))
    usuario = Usuario(
        entra_object_id="semeador-enredos",
        email="semeador@aegea.com.br",
        nome="Semeador",
        papel_id=papel,
        acesso_irrestrito=True,
    )
    sessao.add(usuario)
    sessao.flush()
    return usuario.id


#: Vínculo de DEMONSTRAÇÃO entre frente e área, só para o Termômetro por área
#: ter número de verdade nas 5 áreas — não é regra do domínio. Numa agenda
#: real a área é escolha de quem cadastra, e mais de uma por agenda é comum;
#: aqui, uma por frente já basta para exercitar o gráfico com dado plausível.
#: PELO NOME: `area_pessoa` tem `codigo`, mas o vínculo já nasceu assim e
#: trocar a chave aqui não muda o resultado.
#:
#: Só as frentes mapeadas abaixo. Investidores, bancos e a frente interna
#: ficam de fora da amostra por decisão de produto anterior — não porque a
#: área não exista: `area_pessoa` já tem "Relações com Investidores" e
#: "Operações Financeiras". Estender a amostra a essas frentes é decisão de
#: produto, não corrigida aqui.
AREA_POR_FRENTE: dict[str, str] = {
    "imprensa": "Comunicação",
    "eventos": "Comunicação",
    "governo": "Relações Institucionais",
    "parceiros": "Relações Institucionais",
    "legislativo": "Relações Institucionais",
}


def vincular_areas(sessao: Session) -> int:
    """Liga cada interação já existente a uma área, pela frente dela.

    Roda sobre TODA interação da base — as da amostra-handoff e as dos
    enredos —, não só as que este módulo acabou de criar: o vínculo
    `interacao_area` nasceu depois das duas, e sem isto nenhuma agenda
    antiga teria área nenhuma.

    Idempotente por interação: quem já tem alguma área ligada não é tocado —
    rodar de novo não duplica, e não sobrescreve uma área escolhida à mão
    pela tela.
    """
    id_da_area = {a.nome: a.id for a in sessao.scalars(select(AreaPessoa))}
    codigo_da_frente = {f.id: f.codigo for f in sessao.scalars(select(FrenteTabela))}
    ja_ligadas = set(sessao.scalars(select(InteracaoArea.interacao_id)))

    ligadas = 0
    for interacao in sessao.scalars(select(InteracaoRegistro)):
        if interacao.id in ja_ligadas:
            continue
        codigo = codigo_da_frente.get(interacao.frente_id)
        nome_da_area = AREA_POR_FRENTE.get(codigo) if codigo else None
        if nome_da_area is None:
            continue
        sessao.add(InteracaoArea(interacao_id=interacao.id, area_id=id_da_area[nome_da_area]))
        ligadas += 1

    return ligadas


def principal() -> None:
    from app.banco.sessao import obter_fabrica_de_sessao

    sessao = obter_fabrica_de_sessao()()
    try:
        criadas = semear(sessao)
        ligadas = vincular_areas(sessao)
        sessao.commit()
        print(f"Agendas criadas: {criadas}")
        if criadas == 0:
            print("A base já tinha linhagem. Nada a fazer.")
        print(f"Áreas vinculadas: {ligadas}")
    finally:
        sessao.close()


if __name__ == "__main__":
    principal()
