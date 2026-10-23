"""Os modelos de resposta das lentes — o contrato que a tela e qualquer outra
interface recebem.

SAÍRAM DE `api/lentes.py` EM 17/10/2026, junto com a leitura que os monta. O
motivo é a fronteira: `app/esquemas/` existe para "o que entra e o que sai" da
API, e manter o contrato dentro do módulo de ROTA fazia a única forma de
conhecer a resposta do Dossiê ser abrir a rota que a serve.

QUEM OS MONTA É `casos_de_uso/leitura_das_lentes`, e isso é o que permite uma
segunda interface (um bot, um job, um gerador de texto por IA) pedir o mesmo
dado sem passar por HTTP.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConceitoSaida(BaseModel):
    termo: str
    texto: str


class FichaSaida(BaseModel):
    """A procedência de um bloco — o conteúdo do "?"."""

    origem: str
    fonte: str
    colunas: list[str] = Field(default_factory=list)
    #: O que este bloco NÃO tem hoje, dito onde a pessoa está olhando.
    lacunas: list[str] = Field(default_factory=list)
    exemplo: bool = False
    conceitos: list[ConceitoSaida] = Field(default_factory=list)


class ColunaSaida(BaseModel):
    """Uma coluna de uma tabela do dossiê.

    VEM DO SERVIDOR porque é ele que sabe o que a tabela mostra. A primeira
    versão montava as colunas na tela OLHANDO O TÍTULO do bloco — e o título
    passou a ser a frase de um detector, que muda com o dado: o schema da
    tabela trocaria sozinho no mês em que a leitura mudasse.
    """

    chave: str
    titulo: str
    alinhamento: str = "esquerda"


class BlocoSaida(BaseModel):
    """Um gráfico ou quadro, com o tipo que a tela deve desenhar."""

    tipo: str
    #: Distingue duas tabelas que se desenham igual e se leem diferente:
    #: `rating` destaca rebaixamento, `teor` destaca reclamação acima de
    #: metade. A regra de destaque é de leitura e mora na tela; QUAL regra
    #: aplicar é do servidor.
    subtipo: str | None = None
    titulo: str
    #: A frase que o gráfico prova, escrita pelos detectores a cada leitura.
    conclusao: str | None = None
    dados: list[dict] = Field(default_factory=list)
    #: Como se chamam as três faixas NESTE bloco. A lente institucional mede
    #: clima (propositivo/neutro/tenso) e as outras medem sentimento — e a tela
    #: não pode descobrir isso adivinhando pelo título.
    legenda: list[str] = Field(default_factory=list)
    #: A cor de cada faixa de `legenda`, na mesma ordem — só a lente
    #: institucional manda isto hoje, com `clima.cor_hex` (a mesma cor do
    #: Painel). Vazio quando ausente: a tela cai nos tons genéricos de
    #: positivo/neutro/negativo do próprio design system.
    cores: list[str] = Field(default_factory=list)
    #: Só nas tabelas.
    colunas: list[ColunaSaida] = Field(default_factory=list)
    #: A coluna cujo valor é o ENDEREÇO DA LINHA — a tela a usa como destino de
    #: um clique na linha, e NÃO desenha a coluna.
    #:
    #: O DONO DO PRODUTO PEDIU A LINHA, E NÃO O LINK: "não precisa ter o link no
    #: modal, mas se clicar gostaria de acessar a página". Uma coluna "Link" com
    #: "Abrir ↗" repetido trinta vezes é ruído, e rouba largura do texto da
    #: menção — que é o que se lê.
    #:
    #: VEM DO SERVIDOR pelo mesmo motivo de `recorta`: a alternativa é a tela
    #: procurar uma coluna chamada "link", que é adivinhação pelo nome — o jeito
    #: exato como a escolha do schema da tabela já quebrou uma vez (ver
    #: `ColunaSaida`).
    coluna_do_link: str | None = None
    #: A dimensão do recorte que um clique neste painel aplica — a chave do
    #: parâmetro da rota (`tema`, `empresa`, `perfil_autor`). Nula no bloco que
    #: não recorta nada (a evolução, as tabelas).
    #:
    #: VEM DO SERVIDOR porque a alternativa é a tela adivinhar a dimensão pelo
    #: TÍTULO do painel — e o título é a frase de um detector, que muda com o
    #: dado. Ver `RECORTE_DO_PAINEL`, e o comentário de `ColunaSaida`, que conta
    #: como esse mesmo atalho já quebrou uma vez.
    recorta: str | None = None
    ficha: FichaSaida


class SinalSaida(BaseModel):
    """Uma linha do bloco "Sinais do período"."""

    tipo: str
    frase: str
    #: O número que a frase prova, em destaque ao lado dela.
    evidencia: str
    #: Em que gráfico conferir — "Evolução", o nome de um painel, ou "Lente".
    #: É O QUE LIGA A FRASE À PROVA: sem isso a lista vira cinco afirmações
    #: soltas, e quem duvida de uma não sabe onde olhar.
    onde: str
    tom: str


class KpiSaida(BaseModel):
    rotulo: str
    valor: str
    detalhe: str | None = None


class FatoSaida(BaseModel):
    mes: str
    texto: str
    efeito: str


class DossieSaida(BaseModel):
    codigo: str
    nome: str
    stakeholder: str
    mes: str

    #: A nota da lente e a variação — vêm do índice, sem recálculo.
    nota: int | None
    ns: float | None
    delta: int | None
    #: `mes_anterior` (o normal) ou `sem_filtro` — com um recorte ativo, "vs.
    #: mês anterior" compararia maçã com laranja (o mês passado não tem o
    #: mesmo filtro), então o delta vira "nota filtrada vs. nota do mês
    #: inteiro", e o front troca a legenda.
    delta_versus: str = "mes_anterior"
    #: Verdadeiro quando `tier`/`veiculo`/`atributo`/`tema` veio preenchido na
    #: chamada. A tela usa isto para o selo "recorte filtrado" — esta nota NÃO
    #: é a nota oficial do mês, é só o que esse recorte mostraria.
    recorte_filtrado: bool = False
    peso: int
    estimado: bool
    ausencia: str | None
    fontes: list[str] = Field(default_factory=list)
    formula: str

    #: QUATRO, sempre — é a estrutura fixa da §1, e não uma convenção. Um
    #: quinto KPI quebraria a grade, e três deixariam um buraco onde a pessoa
    #: procura o número que ela sempre olha.
    kpis: list[KpiSaida] = Field(min_length=4, max_length=4)
    #: A nota, a variação e os KPIs saem daqui.
    ficha_do_destaque: FichaSaida
    #: A frase que abre a lente. CALCULADA dos dados a cada leitura, nunca
    #: salva: texto guardado envelhece em silêncio numa tela que a diretoria lê
    #: como se fosse deste mês.
    manchete: str | None = None
    evolucao: BlocoSaida
    #: O quadro ao lado da evolução — até três sinais da série, mais as lacunas.
    sinais_da_evolucao: list[str] = Field(default_factory=list)
    #: A DIMENSÃO DE VEÍCULO SAIU DAQUI em 23/10/2026. Eram quatro blocos —
    #: `volume_por_tier` (a rosca), `top_veiculos`, `clima_por_veiculos` e
    #: `veiculos_tier1` — que a tela deixou de ler quando os três cartões
    #: independentes deram lugar ao Explorador de veículos, que soma no
    #: navegador a partir de `GET /{codigo}/explorador-de-veiculos`.
    #:
    #: FICARAM SENDO CALCULADOS PARA NINGUÉM por algumas horas, e sair é mais
    #: honesto que ficar: bloco que o servidor monta em todo dossiê e ninguém
    #: desenha é custo por volume e uma promessa falsa no contrato da rota.
    #:
    #: SAIU TAMBÉM, por consequência: `veiculos_por_sentimento` no repositório
    #: (sem outro consumidor) e a divergência de arredondamento que havia entre
    #: o `round` do Python daqui e o `Math.round` do navegador — ela desaparece
    #: porque o cálculo duplicado deixa de existir.
    #:
    #: O KPI "Veículos Tier 1" CONTINUA: ele vem de
    #: `veiculos_tier1_do_periodo`, que é outra função, com nome parecido.
    #: O que está puxando a lente pra cima ou pra baixo, por atributo
    #: reputacional — ver `drivers_e_riscos`. Vazio na Institucional.
    drivers_e_riscos: BlocoSaida
    #: Os temas (Subcategoria da Clipei) mais falados do mês — ver
    #: `temas_mais_falados`. Vazio na Institucional.
    temas_mais_falados: BlocoSaida
    #: O BLOCO "ÚLTIMAS MATÉRIAS" SAIU DAQUI em 23/10/2026. Ele listava as
    #: matérias por trás da nota no corpo do dossiê; agora quem as mostra é o
    #: MODAL de aprofundamento, no recorte do veículo que a pessoa clicou no
    #: Termômetro — o princípio que o produto já seguia nos outros cliques:
    #: "ao clicar em um dado temos que abrir um modal com o deep diving".
    #:
    #: A FUNÇÃO `materias_recentes` CONTINUA, e é a mesma: ela alimenta
    #: `itens_do_recorte` na rota do recorte, que é o que o modal desenha.
    #: Saiu o campo do dossiê, não a leitura.
    fatos: list[FatoSaida] = Field(default_factory=list)
    #: DOIS para quem alcança a lente inteira — e UM para quem não alcança o
    #: diretório. O piso desceu de 2 para 1 porque o painel que NOMEIA gente de
    #: fora (a matriz de jornalistas; os órgãos do CRM) sai do payload de quem
    #: não tem `ve_diretorio`, e o que sobra continua sendo a lente: o quadro
    #: agregado, a nota, a evolução e os KPIs.
    #:
    #: O TETO CONTINUA EM DOIS: a especificação dá dois painéis por lente, e um
    #: terceiro seria mudança de tela, não de permissão.
    paineis: list[BlocoSaida] = Field(min_length=1, max_length=2)
    #: As abas de "onde está a causa" — o mesmo mês cortado por cada dimensão
    #: que o explica, na ordem em que a lente se explica. Ver
    #: `onde_esta_a_causa`.
    #:
    #: FORA DE `paineis` DE PROPÓSITO: aquele campo tem teto de dois porque a
    #: especificação dá dois painéis por lente, e um terceiro seria mudança de
    #: tela. Isto não é um terceiro painel — é um cartão só, com abas, e as abas
    #: não cabem num contrato que a tela lê como "painel A" e "painel B".
    #:
    #: VAZIO na Institucional, que não vem de menção (tem zero), e no mês em que
    #: nenhuma dimensão explica nada. O MERCADO SAIU DESTA FRASE: ele é clipping
    #: com menção ingerida, e traz quatro abas — ver `DIMENSOES_POR_LENTE`.
    onde_esta_a_causa: list[BlocoSaida] = Field(default_factory=list)
    #: O bloco do fim da tela: o que mudou no período, por intensidade, com as
    #: lacunas de dado no fim.
    sinais: list[SinalSaida] = Field(default_factory=list)


class PassoDaTrilha(BaseModel):
    """Um degrau do caminho que levou até este recorte."""

    #: A chave do parâmetro (`uf`), para a tela saber o que remover ao subir.
    chave: str
    #: O nome da dimensão como a pessoa a leu na aba (`UF`).
    dimensao: str
    valor: str


class RecorteSaida(BaseModel):
    """O nível 3: um pedaço do mês, medido e decomposto.

    UM PEDIDO SÓ, de propósito. O drawer abre com tudo ou abre mentindo — e
    cinco chamadas dariam cinco estados de carregamento dentro de um painel de
    600px, cada um aparecendo e sumindo na frente de quem só clicou numa barra.
    """

    lente: str
    mes: str
    #: O caminho até aqui, na ordem em que a lente se explica. Vazio no recorte
    #: que é o mês inteiro (os cartões do topo abrem assim).
    trilha: list[PassoDaTrilha] = Field(default_factory=list)

    #: A nota que este pedaço teria se fosse o mês — é o número que a tela já
    #: mostrava quando o recorte era aplicado na tela inteira.
    nota: int | None
    #: Quantos pontos ele tira ou põe na nota da lente. VER `impacto_do_recorte`:
    #: o denominador é o do mês, e é isso que faz a soma dos pedaços fechar com
    #: `nota − 50`.
    impacto: float
    #: Positivo/neutro/negativo CONTADOS um a um — o que a barra desenha. Não é o
    #: ponderado da nota: a barra mostra volume, e volume se conta.
    composicao: dict[str, int]
    itens: int
    #: O total do mês, para a frase dizer "4 dos 6 itens" em vez de "4 itens".
    itens_no_mes: int
    #: A frase pronta, calculada a cada leitura — nunca salva.
    frase: str
    ausencia: str | None = None

    #: Seis células: o mesmo recorte mês a mês. Responde "isto é de agora ou é
    #: sempre assim", que é a pergunta que decide se o pedaço merece ação.
    historico: list[dict] = Field(default_factory=list)
    #: As dimensões AINDA NÃO USADAS, cortadas dentro deste recorte. Clicar numa
    #: linha empilha mais um degrau — é descer no mesmo painel.
    dentro: list[BlocoSaida] = Field(default_factory=list)
    #: A lista que fecha a descida: os itens deste recorte.
    itens_do_recorte: BlocoSaida


class OpcoesDeFiltroSaida(BaseModel):
    tiers: list[str]
    veiculos: list[str]
    atributos: list[str]
    temas: list[str]
    #: Os sentimentos (pos/neu/neg) que aparecem no mês — filtro rápido da Imprensa.
    sentimentos: list[str] = []
    #: Os cortes que o padrão Aegea trouxe (0055). VAZIOS na lente que não tem o
    #: campo — a Imprensa não manda perfil do autor —, e é assim que a tela sabe
    #: não oferecer um seletor que não escolhe nada.
    perfis: list[str] = []
    ufs: list[str] = []
    subtemas: list[str] = []
    autores: list[str] = []
    empresas: list[str] = []
    #: A taxonomia de temas do CRM (N1, N2, N3), pelos nomes que as menções
    #: ligadas a ela alcançam no mês. Vazias sem menção ligada.
    temas_n1: list[str] = []
    temas_n2: list[str] = []
    temas_n3: list[str] = []


class GrupoDoExploradorSaida(BaseModel):
    """Um pedaço do mês: N1, N2, N3 e UF, com contagem e peso por sentimento.

    Nulo onde a menção não traz o campo — a tela deixa de fora da barra
    daquele nível, mas a menção continua valendo nos outros.
    """

    n1: str | None
    n2: str | None
    n3: str | None
    uf: str | None
    positivo: int
    neutro: int
    negativo: int
    peso_positivo: float
    peso_neutro: float
    peso_negativo: float


class ExploradorSaida(BaseModel):
    """Os grupos do mês e o denominador da nota — a tela soma o resto.

    `impacto(S) = 50 × (Σ peso_positivo − Σ peso_negativo) ÷ denominador`, a
    mesma regra de `impacto_do_recorte`; e a nota de uma UF sai dos pesos dela.
    """

    lente: str
    mes: str
    denominador: float
    grupos: list[GrupoDoExploradorSaida]


class GrupoDeVeiculoSaida(BaseModel):
    """Um pedaço do mês: tier e veículo, com contagem e peso por sentimento.

    Nulo onde a menção não traz o campo — a tela deixa de fora da barra daquele
    EIXO, e a menção continua valendo no outro.

    UMA LINHA POR PAR, e não por veículo: o mesmo veículo pode ter matéria em
    mais de um tier, e somar aqui tiraria da tela a possibilidade de estreitar
    por tier.
    """

    tier: str | None
    veiculo: str | None
    positivo: int
    neutro: int
    negativo: int
    peso_positivo: float
    peso_neutro: float
    peso_negativo: float


class ExploradorDeVeiculosSaida(BaseModel):
    """Os grupos do mês e o denominador da nota — a tela soma o resto.

    Mesma regra de impacto de `ExploradorSaida`:
    `impacto(S) = 50 × (Σ peso_positivo − Σ peso_negativo) ÷ denominador`.
    """

    lente: str
    mes: str
    denominador: float
    grupos: list[GrupoDeVeiculoSaida]
