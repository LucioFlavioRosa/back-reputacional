"""A planilha do fornecedor entrando no índice.

O que este módulo acrescenta ao `dominio/ingestao_score.py`: abrir o `.xlsx`
(openpyxl), achar a aba, casar o cabeçalho com o mapeamento gravado e trocar o
mês inteiro no banco. A regra de o que vira menção NÃO mora aqui.

UM ARQUIVO PODE ALIMENTAR VÁRIAS FONTES, e o upload trata todas de uma vez. O
export da Clipei vira a lente Imprensa inteira e, recortado por público
investidor, a lente Mercado; o da Approach traz Social Listening e Community
Management em abas diferentes do mesmo `.xlsx`. Importar por uma fonte só
deixaria a irmã com o mês anterior, e duas lentes leriam versões diferentes do
mesmo arquivo — divergência que ninguém vê na tela, porque cada lente mostra um
número plausível. Quem diz quais fontes andam juntas é o campo `arquivo` do
mapeamento, que é cadastro.

SUBSTITUIÇÃO POR MÊS, e não acréscimo: o fornecedor reenvia o arquivo quando
corrige uma classificação, e o mesmo post somado contaria duas vezes. Cada mês
presente no arquivo é apagado e regravado; um mês que o arquivo não traz fica
intacto, porque o export de junho não é uma afirmação sobre maio.

O PREÇO É QUE UM ARQUIVO PARCIAL PODE ENCOLHER UM MÊS: um export baixado antes
fechamento substitui o mês cheio pelo pedaço, e o servidor não tem como
distinguir isso de uma reclassificação com menos linhas. O que dá é não deixar
passar calado — o resumo diz quantas menções o mês tinha antes da troca, ao lado
de quantas entraram.

O AGREGADO SE REFAZ AQUI porque a substituição deixa o banco com exatamente as
menções do arquivo para aqueles meses: as somas do arquivo JÁ SÃO as somas do
mês, e relê-las do banco seria conferir a própria escrita.

UMA CONSEQUÊNCIA A CARREGAR: `soma_log` e `soma_cargo` congelam, no instante da
ingestão, as fórmulas de `dominio/score.py` (`peso_do_engajamento` e
`peso_do_cargo`). Mudar uma delas NÃO reescreve o passado. É de propósito — o
número que a diretoria citou em julho continua sendo o que ela citou —, e o grão
para reprocessar está inteiro em `mencao`.
"""

from __future__ import annotations

import io
import re
import threading
import weakref
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.banco.tabelas_lentes import MencaoNaoClassificada
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.casos_de_uso import temas_da_mencao, unidade_da_mencao, veiculos_da_imprensa
from app.casos_de_uso.leitor_de_planilha import (
    abrir_pelo_openpyxl,
    celulas_pelo_calamine,
    como_o_openpyxl,
    sem_erro_do_excel,
)
from app.casos_de_uso.veiculos_da_imprensa import nomes_da_lista
from app.configuracao import obter_configuracao
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import (
    Descarte,
    Leitura,
    Mapeamento,
    ler_planilha,
    quem_falou,
    somar,
)

# `normalizar` É A MESMA DOS DOIS LADOS: o nome que vem da planilha e o
# `nome_normalizado` gravado em `instituicao`. É isso que faz a menção achar o
# veículo criado a partir dela — e não `normalizar` ser igual ao `achatar` da
# ingestão, que ela não é (divergem em caractere não-ASCII; ver `reconhecer`).
from app.dominio.texto import normalizar

#: Abrir uma planilha de 10 mil linhas é barato; abrir um arquivo de 200 MB
#: enviado por engano não é. O teto é pedido do dono do produto: planilhas de
#: até 80 MB.
#:
#: O `client_max_body_size` DO NGINX DO FRONT FICA ACIMA DISTO (81m), e a ordem
#: é o que importa: o nginx vem primeiro, então cortar lá troca esta mensagem —
#: que diz o tamanho aceito — por um 413 seco do proxy. Quem mudar um muda o
#: outro.
#:
#: E O TETO DE BYTES NÃO É O LIMITE REAL destas planilhas: o tempo é. O ingress
#: do Container Apps corta a requisição por volta de 240 s, e um clipping de
#: poucos MB já leva dezenas de segundos de processamento. Arquivo de 80 MB
#: passa por aqui e pode não terminar lá — ele pede importação em segundo plano.
TAMANHO_MAXIMO = 80 * 1024 * 1024

#: A assinatura de um ZIP — e um `.xlsx` é um ZIP. Conferir os quatro primeiros
#: bytes recusa o `.xls` antigo, o CSV renomeado e o PDF trocado por engano
#: ANTES de entregar o conteúdo ao parser de XML, que é a parte que um arquivo
#: hostil tenta alcançar. Não substitui o `defusedxml` (declarado no
#: `pyproject.toml`, que o openpyxl usa sozinho quando presente): é a primeira
#: das duas barreiras, não a única.
ASSINATURA_ZIP = b"PK\x03\x04"


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que a ingestão fez com UMA fonte — o que a tela mostra depois."""

    fonte: str
    nome: str
    linhas: int
    ingeridas: int
    descartes: Mapping[str, int]
    meses: tuple[date, ...]
    #: Quantas menções esta fonte tinha nestes meses ANTES da substituição.
    #: É o que deixa visível um export parcial encolhendo um mês fechado.
    antes: int = 0
    avisos: Mapping[str, int] = field(default_factory=dict)
    #: QUANTOS VEÍCULOS NASCERAM NESTA SUBIDA — e é da SUBIDA, não desta fonte.
    #:
    #: Os veículos são criados UMA vez, antes das fontes irmãs, porque todas leem
    #: o mesmo arquivo. Então este número vem REPETIDO em cada resumo da lista,
    #: com o mesmo valor, e NÃO SE SOMA: a tela mostra uma vez, porque é o número
    #: que a pessoa acabou de autorizar na conferência.
    veiculos_criados: int = 0
    #: Quantas menções DESTA fonte acharam veículo no cadastro. Esta é por
    #: fonte, e somar não faz sentido por outro motivo: as irmãs recortam o
    #: mesmo arquivo, então a menção da lente Mercado também está na Imprensa.
    #:
    #: É o número que diz o quanto a ponte cobre, e o que cresce a cada subida
    #: com criação.
    mencoes_ligadas: int = 0
    #: Quantas menções DESTA fonte acharam assunto no cadastro de temas.
    #:
    #: É O NÚMERO QUE DIZ SE O FILTRO DA TAXONOMIA TEM DADO: o dossiê recorta
    #: por N1/N2/N3 pelo `tema_id`, então menção sem vínculo não aparece em
    #: recorte nenhum.
    mencoes_com_tema: int = 0


def _linhas_da_aba(
    conteudo: bytes | ArquivoLido, mapeamento: Mapeamento
) -> Iterator[Mapping[str, object]]:
    """As linhas da planilha como dicionários cabeçalho → célula.

    ABRE O ARQUIVO A CADA CHAMADA quando recebe bytes, e é por isso que quem faz
    mais de uma passada passa um `ArquivoLido`: a conferência faz quatro
    passadas, e decodificar o arquivo quatro vezes é o custo que `ArquivoLido`
    existe para eliminar.
    """
    return _lido(conteudo).linhas(mapeamento)


#: A NORMALIZAÇÃO DE CÉLULA MORA EM `leitor_de_planilha`, porque a ingestão de
#: bonds lê pelo mesmo mecanismo. O nome fica reexportado aqui porque é por ele
#: que os testes deste módulo a alcançam.
_como_o_openpyxl = como_o_openpyxl


# =============================================================================
# QUANDO VALE LER RÁPIDO E GUARDAR A LEITURA
#
# A pergunta é uma só — "a leitura desta planilha cabe na memória deste
# contêiner?" — e dela sai TUDO: o leitor rápido e o cache andam juntos em
# `ArquivoLido.linhas`, porque `_pelo_calamine` só é alcançável pelo ramo que
# guarda. Dizer "não" perde os dois de uma vez.
#
# NÃO SE RESPONDE PELO BYTE COMPRIMIDO do `.xlsx`, que é o proxy óbvio e erra
# por mais de 3x entre os dois arquivos reais: a razão entre comprimido e XML da
# aba varia de 2x a 6x. Com um número só para os dois, ou se recusa o cache a
# quem cabe — e aí a conferência decodifica o arquivo quatro vezes — ou se
# concede a quem não cabe, e o processo morre.
#
# E O BYTE COMPRIMIDO NÃO SABE DE ABAS. O arquivo da Approach tem SETE, e cada
# fonte lê uma: julgar pelo arquivo inteiro cobra de uma aba o tamanho das
# outras seis.
# =============================================================================

#: TRÊS TERMOS, PORQUE O CUSTO TEM TRÊS FONTES, e um termo só subestima por
#: duas ordens de grandeza.
#:
#: O TEXTO DE UM `.xlsx` NÃO MORA NA ABA: mora em `xl/sharedStrings.xml`, e a
#: aba guarda referências curtas. Uma planilha de poucas células com textos
#: enormes tem aba pequena, estimativa pequena e pico gigante.
#:
#: E SOMAR `sharedStrings.file_size` NÃO BASTA, que é a correção óbvia: com
#: texto REPETIDO o arquivo guarda uma cópia muito menor, mas o leitor
#: materializa uma string Python POR CÉLULA, e o custo continua.
#:
#: O QUE FECHA A CONTA É A RAZÃO `count/uniqueCount`, que o `<sst>` declara no
#: próprio cabeçalho: quantas células referenciam texto contra quantos textos
#: distintos existem. `sharedStrings × razão` é o texto como ele é
#: MATERIALIZADO.
#:
#: OS COEFICIENTES FICAM ACIMA DO AJUSTE, de propósito e com folga medida sobre
#: os arquivos reais e casos montados: SUBESTIMAR MATA O PROCESSO, e
#: superestimar só custa tempo, porque o caminho lento continua correto.

#: A célula em si: o `tuple`, o objeto Python do valor e o overhead do
#: dicionário rio abaixo, arredondado para cima.
MEMORIA_POR_CELULA = 140

#: A CÉLULA DE PREENCHIMENTO, que não traz valor nenhum.
#:
#: `iter_rows` devolve a linha INTEIRA até a última coluna que a aba declara, e
#: as colunas sem valor vêm como `None` — numa aba larga e vazia, a maioria das
#: células. Mas é sempre o MESMO `None`: o que custa é o ponteiro na tupla, não
#: um objeto por célula, e por isso o coeficiente é uma ordem de grandeza menor
#: que o da célula com valor.
#:
#: O NÚMERO TEM MARGEM DELIBERADA sobre a pior medição, na mesma régua dos
#: outros coeficientes deste bloco. E a margem é assimétrica de propósito:
#: superestimar nas lentes só derruba para o caminho lento, que continua
#: correto, mas `ingerir_bonds` NÃO TEM caminho lento, e a mesma conta recusaria
#: o arquivo na cara de quem subiu. Quem for ajustar isto para baixo precisa
#: medir os DOIS leitores: o calamine custa mais por célula que o openpyxl,
#: porque a lista de listas do `to_python()` coexiste com a lista de tuplas.
MEMORIA_POR_CELULA_VAZIA = 24

#: O TEXTO COMO CADA CÉLULA O MATERIALIZA (`sharedStrings × count/uniqueCount`).
#: O byte de XML vira caractere Python com overhead, e a deduplicação do arquivo
#: não se repete na memória.
MEMORIA_POR_TEXTO_MATERIALIZADO = 0.55

#: O TEXTO ÚNICO que o leitor guarda uma vez (o lado Rust do calamine). É o
#: termo que domina quando o texto é longo e distinto, que é justamente o caso
#: que um termo só não vê.
MEMORIA_POR_TEXTO_UNICO = 2.8

#: BYTES DE XML QUE UMA CÉLULA OCUPA, para quando a planilha não declara as
#: dimensões dela. Fica entre o que os dois arquivos reais medem, e a estimativa
#: só é usada quando é a MAIOR das duas — ver `celulas_da_maior_aba`.
XML_POR_CELULA = 35

#: QUANTO DO CONTÊINER A LEITURA DE UMA PLANILHA PODE TOMAR.
#:
#: Não é 100% porque o processo já carrega FastAPI, SQLAlchemy e o pool de
#: conexões antes de abrir arquivo nenhum, e porque `max_replicas = 2` no back
#: significa que o limite do contêiner é por réplica mas o pico pode coincidir.
#: 40% deixa o dobro de folga sobre o que a leitura pede.
FRACAO_DO_CONTEINER = 0.4

#: O ORÇAMENTO QUANDO NÃO HÁ CONTÊINER QUE SE DECLARE — máquina de quem
#: desenvolve, teste, um ambiente sem cgroup. Conservador de propósito: aqui não
#: há quem matar, e errar para baixo custa tempo, não o processo.
ORCAMENTO_SEM_CONTEINER = 192 * 1024 * 1024

#: Onde o cgroup publica o limite de memória. OS DOIS, e a ordem é só
#: preferência.
#:
#: OS DOIS AMBIENTES DIVERGEM: o Container Apps publica em **v1**
#: (`/sys/fs/cgroup/memory/memory.limit_in_bytes`), e o AKS documenta **v2**
#: como padrão desde o Kubernetes 1.25. Lendo só o v2 — o "moderno" —, o
#: orçamento cairia no padrão conservador e o ganho desta leitura desapareceria
#: EM SILÊNCIO. Ler os dois é o que faz a decisão viajar entre os ambientes sem
#: ninguém reparar.
_LIMITES_DO_CGROUP = (
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
)

#: `max` (v2) ou um número perto de 2^63 (v1) querem dizer "sem limite".
_SEM_LIMITE = 1 << 62

#: `<dimension ref="A1:W75370"/>`, que fica nos primeiros bytes do XML da aba.
#: É a planilha declarando quantas linhas e colunas ela tem.
_DIMENSAO = re.compile(rb'<dimension\s+ref="[A-Z]+\d+:([A-Z]+)(\d+)"')

#: O cabeçalho do `<sst>`: `count` são as CÉLULAS que referenciam texto,
#: `uniqueCount` os textos DISTINTOS. A razão entre os dois é o fator de
#: deduplicação, e sem ela a estimativa não vê o custo do texto repetido.
#:
#: OS DOIS ATRIBUTOS EM QUALQUER ORDEM, porque o formato não a fixa: um padrão
#: que exigisse `count` antes de `uniqueCount` falharia em silêncio — e falhar
#: aqui significa estimar baixo, que é o lado que mata o processo.
_SST_COUNT = re.compile(rb'\bcount="(\d+)"')
_SST_UNIQUE = re.compile(rb'\buniqueCount="(\d+)"')


@lru_cache(maxsize=1)
def _memoria_do_conteiner() -> int | None:
    """O limite de memória deste contêiner, ou `None` se não houver.

    `lru_cache` porque isto não muda enquanto o processo vive, e porque a
    pergunta é feita uma vez por planilha aberta.
    """
    for caminho in _LIMITES_DO_CGROUP:
        try:
            bruto = caminho.read_text().strip()
        except OSError:
            continue
        if bruto == "max":
            return None
        try:
            valor = int(bruto)
        except ValueError:
            continue
        return None if valor >= _SEM_LIMITE else valor
    return None


def orcamento_de_leitura() -> int:
    """Quantos bytes a leitura de uma planilha pode ocupar.

    DEDUZIDO DO CONTÊINER, e não fixado no código: é o que faz esta decisão
    viajar junto com o ambiente. O back roda em dois lugares com memórias
    diferentes — Container Apps com 4 GiB e o cluster do cliente com o que o
    `values.yaml` dele disser —, e um número no código serviria a um e mataria
    ou travaria o outro.

    Na prática:

        contêiner de 4 GiB   -> 1,6 GB -> ~8,5 milhões de células
        contêiner de 1 GiB   -> 410 MB -> ~2,1 milhões de células
        contêiner de 512 MiB -> 205 MB -> ~1,0 milhão de células

    O clipping da Clipei tem 1,73 milhão de células: ele cabe a partir de 1 GiB
    e NÃO cabe em 512 MiB. Isto não é defeito desta função, é o fato — e é o
    número a levar a quem opera o cluster, porque com 512 MiB a leitura segue
    pelo caminho lento por falta de memória, não por falta de código.

    A CONFIGURAÇÃO VENCE quando preenchida, para quem mediu o próprio ambiente e
    sabe mais que esta heurística.
    """
    escolhido = obter_configuracao().leitura_orcamento_de_memoria
    if escolhido > 0:
        return escolhido
    limite = _memoria_do_conteiner()
    if limite is None:
        return ORCAMENTO_SEM_CONTEINER
    return int(limite * FRACAO_DO_CONTEINER)


@dataclass(frozen=True)
class CelulasDaAba:
    """As células da maior aba, SEPARADAS pelo que cada uma custa.

    AS DUAS SÃO NECESSÁRIAS e por muito tempo houve só uma. `materializadas` é
    o que o leitor CRIA — a linha inteira até a última coluna declarada, com as
    vagas preenchidas por `None`; `ocupadas` é quantas dessas trazem valor, e é
    o único termo que paga objeto Python. Numa aba densa as duas coincidem;
    numa aba larga e vazia, a diferença entre elas é toda a conta.
    """

    materializadas: int
    ocupadas: int


def celulas_da_maior_aba(conteudo: bytes) -> CelulasDaAba | None:
    """Quantas células a maior aba traz, SEM descomprimir a planilha.

    Lê o diretório central do ZIP — que já traz o tamanho descomprimido de cada
    arquivo — e descomprime só os primeiros 4 KB da aba maior, à caça do
    `<dimension>`. São milissegundos num clipping de dezenas de MB.

    A MAIOR ABA, e não a aba que se vai ler: resolver nome de aba até o arquivo
    exigiria `xl/workbook.xml` mais os `.rels`, e o ganho seria estimar o que já
    está limitado. A maior aba é um teto para qualquer aba do arquivo — erra para
    o lado de recusar o cache, que custa tempo, nunca o processo.

    AS DUAS ESTIMATIVAS, E A MAIOR VENCE. A dimensão declarada é exata quando
    existe, mas `<dimension>` é opcional no formato e há quem escreva
    `ref="A1:A1"` numa aba de 60 MB — confiar nela sozinha concederia o cache a
    um arquivo enorme. O tamanho do XML é grosseiro, mas nunca mente sobre ordem
    de grandeza.

    A DIFERENÇA ENTRE AS DUAS É O PREENCHIMENTO: quando a dimensão declara MAIS
    do que o XML comporta, o excesso não é célula com valor, são as vagas que
    `iter_rows` devolve como `None` — e elas custam uma fração do que uma célula
    de verdade custa (ver `MEMORIA_POR_CELULA_VAZIA`).

    O MÁXIMO CONTINUA EM `materializadas`, de propósito: é ele que impede a
    dimensão que mente PARA BAIXO de conceder o cache a um arquivo enorme.
    Quando o XML vence, `ocupadas` iguala `materializadas`, o termo do
    preenchimento zera e a conta é a de sempre.

    DEVOLVE `None` quando não consegue dizer — ZIP ilegível, nenhuma aba, uma
    exceção qualquer. Quem chama trata `None` como "não cabe", porque a
    alternativa é adivinhar para cima.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            abas = [
                item
                for item in pacote.infolist()
                if item.filename.startswith("xl/worksheets/")
                and item.filename.endswith(".xml")
            ]
            if not abas:
                return None
            maior = max(abas, key=lambda item: item.file_size)
            pelo_xml = maior.file_size // XML_POR_CELULA
            with pacote.open(maior) as fluxo:
                cabeca = fluxo.read(4096)
    except Exception:  # noqa: BLE001 - ZIP corrompido, truncado ou exótico
        return None

    achado = _DIMENSAO.search(cabeca)
    if achado is None:
        #: SEM DIMENSÃO não há preenchimento a descontar: o tamanho do XML é a
        #: única conta, e tudo o que ele comporta é célula com valor.
        return CelulasDaAba(pelo_xml, pelo_xml) if pelo_xml else None
    #: `A` -> 1, `Z` -> 26, `AA` -> 27: é base 26 com dígitos de 1 a 26, não de
    #: 0 a 25. Iterar `bytes` entrega INTEIROS, e `b"A"[0]` é 65 — daí o 64.
    colunas = 0
    for letra in achado.group(1):
        colunas = colunas * 26 + (letra - 64)
    linhas = int(achado.group(2))
    materializadas = max(colunas * linhas, pelo_xml)
    #: `ocupadas` NÃO É LIMITADA PELA DIMENSÃO, e isso é a guarda: com
    #: `ref="A1:A1"` numa aba de 60 MB, limitar daria uma célula ocupada e o
    #: arquivo inteiro sairia de graça. O XML manda em quanta célula com valor
    #: existe; a dimensão manda só em quanta vaga vem junto.
    return CelulasDaAba(materializadas, pelo_xml) if materializadas else None


def bytes_de_texto(conteudo: bytes) -> tuple[int, int] | None:
    """O texto da planilha: o materializado por célula, e o único.

    DEVOLVE (materializado, único) EM BYTES DE XML, lendo o tamanho de
    `xl/sharedStrings.xml` no diretório central e os dois contadores do
    cabeçalho `<sst>`. Descomprime 2 KB.

    `count` SÃO AS CÉLULAS, `uniqueCount` OS TEXTOS, e a razão entre eles é o
    que um termo só não tem. Com texto repetido o arquivo guarda uma cópia e o
    leitor materializa uma string Python por célula: `sharedStrings` pequeno
    conviver com pico grande é o caso normal, não a exceção.

    SEM `sharedStrings` o arquivo guarda o texto INLINE na aba, e aí o tamanho
    da aba já o contou: devolve (0, 0) e o termo de célula faz o trabalho. É o
    que o openpyxl escreve, e foi por isso que o primeiro experimento não
    reproduziu o defeito.

    DEVOLVE `None` quando `sharedStrings` existe e o cabeçalho não se lê: aí não
    há como saber a razão, e estimar sem ela subestima — o lado que mata o
    processo. Quem chama trata `None` como "não cabe".
    """
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            try:
                item = pacote.getinfo("xl/sharedStrings.xml")
            except KeyError:
                return (0, 0)
            unico = item.file_size
            with pacote.open(item) as fluxo:
                cabeca = fluxo.read(2048)
    except Exception:  # noqa: BLE001 - ZIP corrompido, truncado ou exótico
        return None

    quantas = _SST_COUNT.search(cabeca)
    unicas = _SST_UNIQUE.search(cabeca)
    if quantas is None or unicas is None:
        return None
    distintas = int(unicas.group(1))
    if distintas <= 0:
        return (0, unico)
    razao = int(quantas.group(1)) / distintas
    return (int(unico * razao), unico)


def custo_da_leitura(conteudo: bytes) -> int | None:
    """Quantos bytes de memória a leitura guardada desta planilha vai pedir.

    TRÊS TERMOS, um por fonte de custo — ver os coeficientes no topo. Lê o
    diretório central do ZIP mais alguns KB descomprimidos.

    `None` quando qualquer parte não se deixa estimar.
    """
    celulas = celulas_da_maior_aba(conteudo)
    texto = bytes_de_texto(conteudo)
    if celulas is None or texto is None:
        return None
    materializado, unico = texto
    #: QUATRO TERMOS: a célula com valor e a vaga de preenchimento custam
    #: preenchimento custam coisas diferentes, e cobrá-las igual inflava uma aba
    #: larga e vazia em 14×. A subtração não fica negativa por construção
    #: (`materializadas` é o máximo das duas estimativas, e `ocupadas` é uma
    #: delas); o `max` é cinto de segurança para quem mexer naquela conta.
    vazias = max(0, celulas.materializadas - celulas.ocupadas)
    return int(
        celulas.ocupadas * MEMORIA_POR_CELULA
        + vazias * MEMORIA_POR_CELULA_VAZIA
        + materializado * MEMORIA_POR_TEXTO_MATERIALIZADO
        + unico * MEMORIA_POR_TEXTO_UNICO
    )


#: AS LEITURAS GUARDADAS QUE ESTÃO DE PÉ AGORA, e quanto cada uma reservou.
#: Ver `_reservar`.
_reserva = threading.Lock()
_reservado = 0


def reservado_agora() -> int:
    """Quantos bytes as leituras guardadas em curso já reservaram."""
    with _reserva:
        return _reservado


def _devolver(quanto: int) -> None:
    global _reservado
    with _reserva:
        _reservado -= quanto


def vale_guardar(conteudo: bytes) -> int | None:
    """O custo reservado, se a leitura guardada couber; `None` se não couber.

    O ORÇAMENTO É DO PROCESSO, NÃO DO ARQUIVO. Comparando cada arquivo com o
    orçamento inteiro, duas leituras simultâneas na mesma réplica tomariam duas
    vezes aquilo, mais o que o processo já carrega — e num contêiner pequeno
    duas passam raspando e três passam claramente.

    AS DUAS RÉPLICAS NÃO COMPARTILHAM MEMÓRIA, mas uma delas atende pedidos
    concorrentes, e o Uvicorn com um worker não serializa nada disto.

    A SEGUNDA LEITURA DEGRADA, NÃO FALHA: quem não cabe na folga que sobrou vai
    pelo caminho lento, de memória constante. É a mesma degradação de quem é
    grande demais — e é por isso que isto é controle de admissão, e não uma
    trava que faz esperar: esperar transformaria duas importações simultâneas
    numa fila de minutos, para ler o mesmo arquivo.
    """
    custo = custo_da_leitura(conteudo)
    if custo is None:
        return None
    global _reservado
    with _reserva:
        if _reservado + custo > orcamento_de_leitura():
            return None
        _reservado += custo
    return custo


class ArquivoLido:
    """A planilha aberta UMA VEZ, servindo todas as etapas da subida.

    POR QUE EXISTE: a conferência percorria o `.xlsx` QUATRO vezes — duas na
    previsão (uma por fonte irmã), uma nos veículos e uma nos assuntos —, e cada
    passada custa segundos num export real. Reusando as células, as três
    passadas seguintes saem quase de graça.

    O CUSTO É A DECODIFICAÇÃO DO XML, não o dicionário por linha: guardar as
    células de uma passada não pesa por linha, e é o que elimina as outras três
    leituras.

    GUARDA A ABA INTEIRA, linhas do topo inclusive, e A BUSCA DO CABEÇALHO
    CONTINUA SENDO DE CADA FONTE. Não é detalhe: `_achar_o_cabecalho` procura a
    primeira linha que traz as `colunas_necessarias` DAQUELA fonte, e duas irmãs
    podem exigir conjuntos diferentes — guardar o cabeçalho da primeira faria a
    segunda recusar uma coluna que existe numa linha mais abaixo. A validação de
    coluna é por fonte pelo mesmo motivo: o que se reusa é a leitura; o que cada
    cadastro exige, cada uma confere.

    UMA ABA POR ARQUIVO, e o cache é por nome de aba: fonte que peça outra aba do
    mesmo arquivo abre a dela, e não recebe as linhas da vizinha. É o caso das
    duas fontes da Approach, que leem `CM` e `SL`; as duas da Clipei leem
    `Clipping`, e aí a segunda sai de graça — que é onde está o ganho.

    O QUE NÃO CABE NA MEMÓRIA NÃO É GUARDADO, e aí também não é lido rápido —
    os dois andam juntos. Ver `vale_guardar`.
    """

    def __init__(self, conteudo: bytes) -> None:
        self._conteudo = conteudo
        #: aba resolvida -> todas as células da aba, do topo ao fim
        self._lido: dict[str, list[tuple]] = {}
        reservado = vale_guardar(conteudo)
        self._guardar = reservado is not None
        #: A RESERVA VOLTA QUANDO ESTE OBJETO MORRE, que é quando o cache morre
        #: com ele. `weakref.finalize` e não `__del__`: o segundo não roda se o
        #: objeto entrar num ciclo de referências, e aí a reserva ficaria presa
        #: para sempre — o processo passaria a recusar toda leitura guardada e
        #: ninguém entenderia por quê.
        if reservado is not None:
            self._fim = weakref.finalize(self, _devolver, reservado)

    def linhas(self, mapeamento: Mapeamento) -> Iterator[Mapping[str, object]]:
        """As linhas como dicionários cabeçalho → célula, para este mapeamento."""
        if self._guardar:
            fluxo: Iterator[tuple] = iter(self._celulas(mapeamento))
            yield from self._dicionarios(fluxo, mapeamento)
            return

        #: SEM GUARDAR: a planilha é grande, e cada etapa decodifica a sua.
        planilha, aba = self._abrir(mapeamento)
        try:
            #: A MESMA NORMALIZAÇÃO DO CAMINHO RÁPIDO, célula a célula. Os dois
            #: caminhos precisam normalizar igual, senão a MESMA planilha produz
            #: dados diferentes conforme caiba ou não na memória.
            cru = aba.iter_rows(values_only=True)
            limpas = (sem_erro_do_excel(linha) for linha in cru)
            yield from self._dicionarios(limpas, mapeamento)
        finally:
            planilha.close()

    def _dicionarios(
        self, fluxo: Iterator[tuple], mapeamento: Mapeamento
    ) -> Iterator[Mapping[str, object]]:
        """O cabeçalho desta fonte, a conferência das colunas, e as linhas."""
        cabecalho = _achar_o_cabecalho(fluxo, mapeamento)

        faltando = sorted(mapeamento.colunas_necessarias - set(cabecalho))
        if faltando:
            raise RegraViolada(
                "A planilha não tem as colunas que o cadastro desta fonte espera: "
                f"{', '.join(faltando)}."
            )

        for linha in fluxo:
            yield dict(zip(cabecalho, linha, strict=False))

    def _celulas(self, mapeamento: Mapeamento) -> list[tuple]:
        """As células da aba, decodificadas uma vez e guardadas."""
        chave = mapeamento.aba or ""
        if chave in self._lido:
            return self._lido[chave]

        try:
            self._lido[chave] = self._pelo_calamine(mapeamento)
        except RegraViolada:
            #: RECUSA DE CADASTRO passa direto: aba que falta é mensagem para a
            #: pessoa, não falha de leitor, e tentar o outro daria a mesma.
            raise
        except Exception:
            #: QUALQUER OUTRA FALHA DO CALAMINE cai no openpyxl, que leu esses
            #: arquivos por meses. Um leitor novo pode recusar um `.xlsx`
            #: estranho que o antigo aceitava, e a subida não pode morrer por
            #: causa de uma otimização.
            planilha, aba = self._abrir(mapeamento)
            try:
                #: `sem_erro_do_excel` PARA OS DOIS LEITORES CONCORDAREM: o
                #: calamine entrega célula de erro como vazio, o openpyxl como
                #: a string "#N/A". Sem isto, cair na reserva mudava o DADO —
                #: um veículo chamado "#N/A" entrava por aqui e não pelo outro.
                self._lido[chave] = [
                    sem_erro_do_excel(linha) for linha in aba.iter_rows(values_only=True)
                ]
            finally:
                planilha.close()
        return self._lido[chave]

    def _pelo_calamine(self, mapeamento: Mapeamento) -> list[tuple]:
        """A aba lida pelo calamine — ver `leitor_de_planilha`.

        O MÉTODO FICA, embora seja uma linha: é por este nome que
        `test_a_planilha_e_aberta_uma_vez` conta as decodificações, e contar
        decodificação é o que impede a conferência de voltar a ler o mesmo
        arquivo quatro vezes.
        """
        return celulas_pelo_calamine(self._conteudo, mapeamento.aba)

    def _abrir(self, mapeamento: Mapeamento):
        """Abre o arquivo e devolve a planilha e a aba desta fonte."""
        return abrir_pelo_openpyxl(self._conteudo, mapeamento.aba)


def _lido(conteudo: bytes | ArquivoLido) -> ArquivoLido:
    """Aceita os bytes ou o arquivo já aberto.

    As funções públicas recebem bytes — é o que a rota tem na mão, e é o que os
    testes passam. Quem orquestra (`conferir`, `ingerir`) abre uma vez e passa o
    `ArquivoLido` adiante, e aí as etapas internas não reabrem nada.
    """
    return conteudo if isinstance(conteudo, ArquivoLido) else ArquivoLido(conteudo)


#: Quantas linhas do topo o leitor examina procurando o cabeçalho.
#:
#: O EXPORT DA CLIPEI TEM UMA LINHA ACIMA DO CABEÇALHO: três marcadores de nível
#: (`N1`, `N2`, `N3`) sobre as colunas Atributo, Categoria e Subcategoria.
#: Assumir a linha 1 recusa o arquivo inteiro com "a planilha não tem as colunas
#: que o cadastro desta fonte espera" — a mensagem certa para um arquivo errado,
#: e a errada para um arquivo CERTO com uma linha de título.
#:
#: VINTE É FOLGA, o mesmo número da importação de subtemas: fornecedor que põe
#: logotipo e data antes do cabeçalho cabe, e um arquivo que realmente não tem
#: as colunas ainda é recusado.
LINHAS_ATE_O_CABECALHO = 20


def _achar_o_cabecalho(
    linhas: Iterator[tuple], mapeamento: Mapeamento
) -> list[str]:
    """A primeira linha do topo que traz as colunas que o cadastro espera.

    CONSOME O ITERADOR ATÉ O CABEÇALHO, e é o que faz o `for` seguinte começar
    nos DADOS: o chamador continua lendo do mesmo iterador, e se este devolvesse
    o cabeçalho sem consumi-lo a primeira linha de dado seria o próprio
    cabeçalho.

    RECONHECE PELAS COLUNAS NECESSÁRIAS, e não por "a linha tem muitas células":
    uma linha de título com cinco células passaria no segundo critério. Aqui ela
    só passa se trouxer o que o cadastro desta fonte precisa.
    """
    procuradas = mapeamento.colunas_necessarias
    candidata: list[str] | None = None
    for numero, linha in enumerate(linhas, start=1):
        nomes = [str(celula).strip() if celula is not None else "" for celula in linha]
        if candidata is None:
            candidata = nomes  # a primeira linha, para a mensagem de erro
        if procuradas <= set(nomes):
            return nomes
        if numero >= LINHAS_ATE_O_CABECALHO:
            break
    if candidata is None:
        raise RegraViolada("A planilha está vazia.")
    #: DEVOLVE A PRIMEIRA LINHA quando não achou: quem confere as colunas é o
    #: chamador, e a mensagem dele nomeia o que falta. Levantar aqui duplicaria
    #: a regra em dois lugares — e esta função não sabe o nome da fonte.
    return candidata


def _quanto_havia(sessao: Session, fonte: ScoreFonte, meses: list[date]) -> int:
    total = sessao.scalar(
        select(func.count())
        .select_from(Mencao)
        .where(Mencao.fonte_id == fonte.id, Mencao.mes.in_(meses))
    )
    return int(total or 0)


def regravar(
    sessao: Session,
    fonte: ScoreFonte,
    leitura: Leitura,
    veiculos: Mapping[str, str] | None = None,
) -> None:
    """Troca os meses que o arquivo traz — menções, agregado e não classificadas.

    `veiculos` é nome normalizado -> id de `instituicao`, e chega vazio em dois
    casos normais: fonte sem veículo (as de rede social não têm) e subida em que
    ninguém autorizou criação. Vazio liga nada, e a menção fica com
    `instituicao_id` nulo — o estado normal enquanto o cadastro não cobre o
    fornecedor.

    PÚBLICA PORQUE SÃO DOIS CHAMADORES: o importador mensal (aqui) e a carga
    inicial do pacote (`carga_do_pacote_das_lentes`). As duas leem planilhas de
    formatos diferentes e precisam da MESMA gravação — menções, as quatro somas
    do agregado e a contagem do que ninguém classificou, tudo substituindo o
    mês. Uma segunda cópia desta função seria a segunda definição de "o que é um
    mês no banco".
    """
    #: A TRAVA DO ARQUIVO, E A INGESTÃO TAMBÉM A TOMA. Com a reconciliação
    #: sozinha na trava, ela copiava uma linha para o espelho e uma subida cuja
    #: exclusão começara antes do commit dela não via essa linha e inseria outra
    #: cópia — duplicação no espelho e no agregado.
    #:
    #: A MESMA CHAVE das duas: o id do espelho do arquivo. Fonte sem irmã que
    #: recorte trava por si mesma, e arquivos diferentes não se esperam.
    travar_o_arquivo(sessao, fonte)

    mapeamento = _mapeamento_de(fonte)
    if mapeamento.lista_de_veiculos and not leitura.recortada_por_lista:
        #: A GUARDA MORA AQUI, e não só em `ler_planilha`, porque é AQUI que a
        #: escrita acontece. `carga_do_pacote_das_lentes` monta a `Leitura` à
        #: mão e chama esta função direto: no dia em que a imprensa entrar
        #: naquele pacote, a fonte do Mercado seria gravada com o clipping
        #: inteiro — a lente contaria 25.457 menções em vez de 327, e nada
        #: daria sinal. Quem grava numa fonte que recorta por lista tem de ter
        #: recortado.
        raise RegraViolada(
            f"{fonte.nome} recorta pela lista {mapeamento.lista_de_veiculos!r} e "
            "a leitura recebida não foi recortada."
        )

    de_cadastro = dict(veiculos or {})
    #: O MAPA DOS ASSUNTOS SAI DAQUI, e não de um parâmetro como o dos veículos.
    #: A diferença é que ele não depende de autorização: veículo que falta NASCE
    #: na subida, e por isso quem decide é a tela; assunto não nasce — o cadastro
    #: é a autoridade. Montar o mapa dentro da gravação faz o vínculo valer para
    #: os DOIS caminhos de escrita, inclusive a `carga_do_pacote_das_lentes`, que
    #: monta a `Leitura` à mão e chama esta função direto.
    #:
    #: UMA CONSULTA POR NÍVEL por gravação: a taxonomia inteira cabe na memória e
    #: a comparação é O(1). Perguntar ao banco por linha faria de uma subida de
    #: dezenas de milhares de linhas um problema de rede.
    #:
    #: A ÁRVORE INTEIRA, e não só o mapa do N3 (`por_nome`): o fornecedor traz um
    #: nível e os de cima são derivados daqui. Ver
    #: `dominio/niveis_de_taxonomia.py`.
    arvore_de_temas = temas_da_mencao.arvore(sessao)
    #: E A CONCESSIONÁRIA, pelo mesmo motivo e no mesmo momento: 29 unidades e
    #: os apelidos declarados cabem em memória, e a busca vira `dict.get`. Ver
    #: `casos_de_uso/unidade_da_mencao.py` para a medição e para por que ela
    #: NUNCA adivinha bloco.
    cadastro_de_unidades = unidade_da_mencao.cadastro(sessao)
    #: OS MESES DO ARQUIVO para quem recorta por lista — ver
    #: `Leitura.meses_a_substituir`. Apagar por `meses` deixaria o mês sem
    #: veículo da lista com o que o critério anterior gravou.
    meses = list(leitura.meses_a_substituir(mapeamento))
    sessao.execute(
        delete(MencaoNaoClassificada).where(
            MencaoNaoClassificada.fonte_id == fonte.id,
            MencaoNaoClassificada.mes.in_(meses),
        )
    )
    sessao.execute(
        delete(Mencao).where(Mencao.fonte_id == fonte.id, Mencao.mes.in_(meses))
    )
    sessao.execute(
        delete(ScoreMesFonte).where(
            ScoreMesFonte.fonte_id == fonte.id, ScoreMesFonte.mes.in_(meses)
        )
    )

    #: ONDE O CADASTRO PÕE CADA MENÇÃO, resolvido ANTES de montar os valores.
    #:
    #: Um passo à parte porque `resolver` devolve os TRÊS níveis de uma vez, e
    #: chamá-lo três vezes dentro do dicionário resolveria a árvore três vezes
    #: por linha — com a chance de as três discordarem se alguém mexer numa só.

    #: OS MESMOS QUATRO CAMPOS QUE A LEITURA USA (`consulta_profundidade`), e na
    #: mesma ordem de precedência — é o que torna a coluna gravada igual ao que a
    #: tela calcula ao vivo. `tema_id` não entra porque é o que estamos
    #: resolvendo: na subida mensal ninguém conferiu nível nenhum ainda.
    niveis_por_linha = [
        arvore_de_temas.resolver(
            tema_texto=mencao.tema_texto,
            subtema=mencao.subtema,
            atributo=mencao.atributo,
        )
        for mencao in leitura.mencoes
    ]
    valores = [
        {
            "fonte_id": fonte.id,
            "mes": mencao.mes,
            "data": mencao.data,
            "sentimento": mencao.sentimento,
            "tier": mencao.tier,
            "engajamento": mencao.engajamento,
            "cargo": mencao.cargo,
            "atributo": mencao.atributo,
            "veiculo": mencao.veiculo,
            "publico_alvo": mencao.publico_alvo,
            # O VEÍCULO DO CADASTRO, quando ele existe. Nulo é o normal por um
            # bom tempo: o fornecedor traz milhares de veículos distintos, e a
            # cobertura sobe a cada subida com criação.
            "instituicao_id": de_cadastro.get(normalizar(mencao.veiculo or "")),
            # O ASSUNTO DO CADASTRO, quando o nome casa. Nulo é o normal
            # enquanto o fornecedor não fala o vocabulário do nível — e é o que
            # a conferência mostra antes de gravar.
            #
            # OS TRÊS NÍVEIS GRAVADOS, e não só o N3 com o resto por `join`: o
            # fornecedor que descreve a menção só no topo tem N1 e não tem N3, e
            # um `join` a partir de `tema_id` nunca o alcançaria. Ver a `0098`.
            "bloco_tema_id": niveis.n1_id,
            "macro_tema_id": niveis.n2_id,
            "tema_id": niveis.n3_id,
            "tema_texto": mencao.tema_texto,
            "unidade_texto": mencao.unidade_texto,
            # A CONCESSIONÁRIA DO CADASTRO, quando o nome casa ou há apelido
            # declarado. É o que faz as duas grafias da Corsan — "Corsan" e
            # "Companhia Riograndense de Saneamento (Corsan)" — virarem uma
            # linha só no gráfico e no recorte, em vez de duas.
            #
            # NULO QUANDO O CADASTRO NÃO RESOLVE, inclusive quando ele tem mais
            # de uma candidata ("Águas do Pará" e os quatro blocos). A
            # conferência mostra os dois casos antes de gravar, com as opções ao
            # lado — escolher um bloco aqui inventaria o dado. Ver a `0099`.
            "unidade_negocio_id": cadastro_de_unidades.resolver(mencao.unidade_texto),
            "teor": mencao.teor,
            "acionavel": mencao.acionavel,
            "autor": mencao.autor,
            # -- os campos do padrão Aegea (0055) ---------------------------
            # Nulos vindos de fonte que não os manda, e é assim que as
            # planilhas antigas continuam entrando sem mudança.
            "id_fonte": mencao.id_fonte,
            "uf": mencao.uf,
            "subtema": mencao.subtema,
            "perfil_autor": mencao.perfil_autor,
            "titulo_texto": mencao.titulo_texto,
            "link": mencao.link,
            "peso_tier": mencao.peso_tier,
        }
        #: `zip` com `strict=True`: as duas listas saem da MESMA `leitura.mencoes`
        #: e têm de ter o mesmo tamanho. Se um dia alguém filtrar uma e não a
        #: outra, isto estoura aqui em vez de deslocar os níveis em uma linha e
        #: gravar 25 mil menções com o pilar da vizinha.
        for mencao, niveis in zip(leitura.mencoes, niveis_por_linha, strict=True)
    ]
    #: `insert()` EM LOTE, e não `add_all` com objetos do ORM: instanciar
    #: dezenas de milhares de objetos que ninguém lê de volta custa o dobro do
    #: tempo de mandar os dicionários. Esta função não devolve nada, e quem conta
    #: usa a `leitura`. O `id` continua vindo do default da coluna, aplicado pelo
    #: próprio `insert()`.
    #:
    #: E PLANILHA VAZIA NÃO VIRA `insert` VAZIO: o SQLAlchemy recusaria a lista
    #: sem linhas, e mês sem menção é caso legítimo — é o que acontece quando o
    #: recorte por lista não acha veículo nenhum.
    if valores:
        sessao.execute(insert(Mencao), valores)
    sessao.add_all(
        ScoreMesFonte(
            fonte_id=fonte.id,
            mes=soma.mes,
            sentimento=soma.sentimento,
            tier=soma.tier,
            mencoes=soma.mencoes,
            soma_log=soma.soma_log,
            soma_engajamento=soma.soma_engajamento,
            soma_cargo=soma.soma_cargo,
        )
        for soma in somar(leitura.mencoes)
    )
    # O QUE CHEGOU E NINGUÉM LEU, por mês. Sem isto a tela não distingue "mês
    # sem base" de "mês com volume que o fornecedor não classificou" — e os
    # dois viram a mesma barra vazia.
    sessao.add_all(
        MencaoNaoClassificada(fonte_id=fonte.id, mes=mes, total=total)
        for mes, total in leitura.nao_classificadas.items()
        if total and mes in meses
    )
    sessao.flush()


def _mapeamento_de(fonte: ScoreFonte) -> Mapeamento:
    try:
        return Mapeamento.de_json(fonte.mapeamento_colunas)
    except ValueError as erro:
        # O mapeamento é cadastro, não entrada de usuário: um mapeamento
        # quebrado é problema de configuração da fonte, e a mensagem precisa
        # dizer isso, senão quem subiu o arquivo procura o defeito no arquivo.
        raise RegraViolada(
            f"O mapeamento de colunas de {fonte.nome} está inválido: {erro}"
        ) from erro


def _recorte_por_lista(
    sessao: Session, fonte: ScoreFonte, mapeamento: Mapeamento
) -> Callable[[str | None], bool] | None:
    """O predicado que diz se a linha pertence a ESTA fonte.

    SÃO DOIS LADOS DA MESMA PARTIÇÃO, porque o recorte é EXCLUSIVO — se o Valor
    Econômico é veículo de imprensa de mercado, todas as matérias dele vão para a
    lente de mercado:

        a fonte que DECLARA uma lista  fica com os veículos dela
        a fonte irmã que não declara   fica com todo o RESTO do arquivo

    Sem exclusividade, o espelho fica com tudo e a recortada é uma cópia do
    subconjunto: a mesma matéria conta nas duas lentes.

    A EXCLUSÃO É DERIVADA DAS IRMÃS, e não declarada no cadastro da fonte. É a
    decisão que importa aqui: declarada, ela sairia de sincronia no dia em que
    alguém criasse um recorte novo e esquecesse de atualizar o espelho, e o
    sintoma seria a matéria voltando a contar duas vezes, em silêncio. Derivada,
    a partição é exata por construção: o que uma inclui, a outra exclui, pela
    MESMA função (`nomes_da_lista`, com os apelidos).

    `None` quando a fonte não recorta nem tem irmã que recorte — e aí
    `ler_planilha` lê tudo.

    LÊ O CADASTRO UMA VEZ, e não uma consulta por linha: com dezenas de milhares
    de linhas no export, perguntar ao banco por cada uma faria da subida um
    problema de rede. O conjunto de veículos cadastrados cabe na memória com
    folga.
    """
    if mapeamento.lista_de_veiculos:
        permitidos = nomes_da_lista(sessao, mapeamento.lista_de_veiculos)

        def na_lista(veiculo: str | None) -> bool:
            #: SEM VEÍCULO NÃO ENTRA: não há como afirmar que a linha é de um
            #: veículo de mercado, e supor que é inventaria menção na lente.
            if not veiculo:
                return False
            return normalizar(veiculo) in permitidos

        return na_lista

    recortadas = [
        irma
        for irma in fontes_do_mesmo_arquivo(sessao, fonte)
        if irma.id != fonte.id and (irma.mapeamento_colunas or {}).get("lista_de_veiculos")
    ]
    if not recortadas:
        return None

    das_irmas: set[str] = set()
    for irma in recortadas:
        das_irmas |= nomes_da_lista(
            sessao, str((irma.mapeamento_colunas or {})["lista_de_veiculos"])
        )
    if not das_irmas:
        return None

    def fora_das_listas(veiculo: str | None) -> bool:
        #: SEM VEÍCULO FICA AQUI: a linha sem veículo não pertence a lista
        #: nenhuma (nenhuma recortada a aceita — ver `na_lista`), e tirá-la
        #: daqui também a faria sumir do sistema.
        if not veiculo:
            return True
        return normalizar(veiculo) not in das_irmas

    return fora_das_listas


def _ingerir_uma(
    sessao: Session,
    fonte: ScoreFonte,
    conteudo: bytes | ArquivoLido,
    veiculos: Mapping[str, str] | None = None,
    criados: int = 0,
    e_recorte: bool = False,
) -> Resumo:
    """Lê a planilha pelo mapeamento desta fonte e substitui os meses dela.

    `e_recorte` diz que esta fonte é uma IRMÃ que recorta o arquivo de outra, e
    não a fonte pela qual a pessoa subiu. A diferença está no vazio — ver abaixo.
    """
    mapeamento = _mapeamento_de(fonte)
    leitura = ler_planilha(
        _linhas_da_aba(conteudo, mapeamento),
        mapeamento,
        _recorte_por_lista(sessao, fonte, mapeamento),
    )
    #: RECORTAR POR LISTA JÁ FAZ DA FONTE UM RECORTE, mesmo que tenha sido ela
    #: a escolhida na tela: um mês em que nenhum veículo da lista foi mencionado
    #: é um mês de zero menções de Mercado, e não um arquivo que não serve.
    #: Sem isto, subir pela própria fonte do Mercado derrubaria a subida inteira
    #: no mês fraco — e, na primeira subida de uma base sem veículo
    #: classificado, em todos eles.
    #:
    #: MAS SÓ O RECORTE PODE EXPLICAR O VAZIO. O que o recorte não explica é
    #: arquivo ILEGÍVEL: aba e cabeçalho certos, datas que o parser não lê ou
    #: vocabulário de sentimento que o mapeamento não conhece. Aí nenhuma linha
    #: chegou a ser candidata, e aceitar em silêncio é a falha para a qual esta
    #: guarda foi escrita — subir pela fonte do Mercado a desligava inteira.
    legiveis = len(leitura.mencoes) + leitura.descartes.get(
        Descarte.FORA_DA_LISTA_DE_VEICULOS.value, 0
    )
    pode_vir_vazia = e_recorte or (
        bool(mapeamento.lista_de_veiculos) and legiveis > 0
    )
    if not leitura.mencoes and not pode_vir_vazia:
        #: ZERO NA FONTE PELA QUAL SE SUBIU É ERRO: o arquivo não serve, e
        #: aceitar em silêncio apagaria o mês trocando-o por nada.
        raise RegraViolada(
            f"Nenhuma linha da planilha virou menção em {fonte.nome}. "
            f"Lidas {leitura.linhas}; descartes: {dict(leitura.descartes)}."
        )
    if not leitura.mencoes and mapeamento.lista_de_veiculos:
        #: ZERO NUMA FONTE QUE RECORTA POR LISTA SUBSTITUI O MÊS. "Nenhum
        #: veículo meu foi mencionado em setembro" é um zero da Aegea, medido
        #: pela régua da Aegea — e setembro tem de ficar zerado, não com o que a
        #: régua antiga gravou. Sem isto, resubir o arquivo para aplicar o
        #: critério novo deixava o mês fraco no critério velho, e a série do
        #: Mercado passava a misturar os dois sem nada em tela.
        #:
        #: Segue para `regravar`, que apaga os meses DO ARQUIVO e grava zero
        #: menções.
        antes_do_vazio = _quanto_havia(
            sessao, fonte, list(leitura.meses_a_substituir(mapeamento))
        )
        regravar(sessao, fonte, leitura, veiculos)
        return Resumo(
            fonte=fonte.codigo,
            nome=fonte.nome,
            linhas=leitura.linhas,
            ingeridas=0,
            descartes=leitura.descartes,
            meses=leitura.meses_a_substituir(mapeamento),
            antes=antes_do_vazio,
            avisos={motivo: total for motivo, total in leitura.avisos.items() if total},
            veiculos_criados=criados,
        )

    if not leitura.mencoes:
        #: ZERO NUMA IRMÃ QUE RECORTA É FATO, e não erro.
        #:
        #: A lente Mercado é a Clipei recortada por público investidor, e um mês
        #: sem nenhuma menção de investidor é normal. Tratar como erro derruba A
        #: SUBIDA INTEIRA: as menções de Imprensa não entram porque o recorte da
        #: irmã ficou vazio. Com o critério do Mercado vindo da subcategoria do
        #: veículo cadastrado, a primeira subida tem zero veículos classificados
        #: — o recorte nasce vazio por construção.
        #:
        #: O MÊS DA IRMÃ NÃO É APAGADO quando o recorte vem vazio: sem meses na
        #: leitura, `regravar` não tem o que substituir, e o que já estava lá
        #: fica. Recorte vazio num mês não é instrução de esquecer o mês.
        return Resumo(
            fonte=fonte.codigo,
            nome=fonte.nome,
            linhas=leitura.linhas,
            ingeridas=0,
            descartes=leitura.descartes,
            meses=leitura.meses,
            antes=_quanto_havia(sessao, fonte, list(leitura.meses)),
            avisos={motivo: total for motivo, total in leitura.avisos.items() if total},
            veiculos_criados=criados,
        )

    #: PELOS MESES QUE VÃO SER SUBSTITUÍDOS, que para quem recorta por lista
    #: são os do arquivo: é esse o número que a tela compara para dizer "este
    #: mês tinha 300 e vai encolher".
    meses_substituidos = list(leitura.meses_a_substituir(mapeamento))
    antes = _quanto_havia(sessao, fonte, meses_substituidos)
    regravar(sessao, fonte, leitura, veiculos)
    #: UMA VEZ, e nao por mencao: a contagem abaixo percorre 25 mil linhas, e
    #: uma consulta dentro do laco faria 25 mil idas ao banco.
    temas = temas_da_mencao.por_nome(sessao)
    de_cadastro = dict(veiculos or {})
    return Resumo(
        fonte=fonte.codigo,
        nome=fonte.nome,
        linhas=leitura.linhas,
        ingeridas=len(leitura.mencoes),
        descartes=leitura.descartes,
        meses=tuple(meses_substituidos),
        antes=antes,
        avisos={motivo: total for motivo, total in leitura.avisos.items() if total},
        veiculos_criados=criados,
        # CONTA AS MENÇÕES QUE ACHARAM VEÍCULO, e não as que têm veículo: é o
        # número que diz o quanto a ponte para o cadastro cobre, e é ele que
        # cresce a cada subida com criação.
        mencoes_ligadas=sum(
            1
            for mencao in leitura.mencoes
            if normalizar(mencao.veiculo or "") in de_cadastro
        ),
        # PELA MESMA RÉGUA DA GRAVAÇÃO, e não por uma contagem própria: o
        # número que a tela mostra tem de ser o que o banco recebeu.
        mencoes_com_tema=sum(
            1
            for mencao in leitura.mencoes
            if normalizar(mencao.tema_texto or "") in temas
        ),
    )


#: O "namespace" da trava do arquivo (`pg_advisory_xact_lock` recebe dois
#: inteiros). O MESMO NÚMERO que `reconciliar_lista_de_veiculos` usa, de
#: propósito: as duas operações precisam se esperar, e travas em espaços
#: diferentes não se veem. Está declarado aqui porque é aqui que a ingestão
#: mora, e importá-lo de lá criaria ciclo.
ESPACO_DA_TRAVA_DO_ARQUIVO = 10_267


def travar_o_arquivo(sessao: Session, fonte: ScoreFonte) -> None:
    """Serializa quem escreve os meses deste arquivo — subida e reconciliação.

    A CHAVE É O ESPELHO (a irmã que não recorta), que é a identidade do
    arquivo; sem irmã que recorte, a fonte trava por si mesma. Arquivos
    diferentes não se esperam.

    `xact`: morre com a transação, e nada fica preso se o processo cair.
    """
    irmas = fontes_do_mesmo_arquivo(sessao, fonte)
    espelhos = [
        irma for irma in irmas if not (irma.mapeamento_colunas or {}).get("lista_de_veiculos")
    ]
    chave = espelhos[0].id if espelhos else fonte.id
    sessao.execute(select(func.pg_advisory_xact_lock(ESPACO_DA_TRAVA_DO_ARQUIVO, chave)))


def fontes_do_mesmo_arquivo(sessao: Session, fonte: ScoreFonte) -> list[ScoreFonte]:
    """As fontes que leem o export que esta fonte lê — ela inclusive.

    Sem `arquivo` no mapeamento, a fonte anda sozinha: é o caso de um
    fornecedor que entrega um arquivo só dele.
    """
    grupo = _mapeamento_de(fonte).arquivo
    if not grupo:
        return [fonte]

    irmas = sessao.scalars(
        select(ScoreFonte)
        .where(
            ScoreFonte.ativo.is_(True),
            ScoreFonte.interna.is_(False),
            ScoreFonte.mapeamento_colunas["arquivo"].astext == grupo,
        )
        .order_by(ScoreFonte.ordem)
    ).all()
    # A fonte pedida entra mesmo que o filtro não a alcance (inativa, por
    # exemplo, ela já foi recusada antes): quem subiu escolheu esta.
    return list(irmas) if fonte in irmas else [fonte, *irmas]


def ingerir(
    sessao: Session,
    fonte: ScoreFonte,
    conteudo: bytes,
    veiculos_a_criar: Sequence[str] = (),
) -> list[Resumo]:
    """Lê o export e substitui os meses dele em TODAS as fontes que o leem.

    `veiculos_a_criar` são os nomes que a pessoa AUTORIZOU na conferência, e o
    padrão é vazio — nenhuma criação.

    O PADRÃO TEM DE SER VAZIO, e isto não é timidez: a tela de Calibração tem um
    botão "Importar planilha" por fonte, que chama esta função direto. Com o
    padrão em "criar tudo", quem clicasse ali criaria milhares de instituições
    sem ter visto nada — a duplicata em massa que a importação de agendas
    documenta, por uma mudança de assinatura. Quem quer criação pede, nomeando.

    OS NOMES SÃO CONFERIDOS CONTRA A PLANILHA antes de virar cadastro: um nome
    que a pessoa manda e o arquivo não tem é ignorado, não criado. Sem isso, a
    rota seria um jeito de cadastrar instituição arbitrária por um campo de
    formulário.
    """
    recusar_o_que_nao_entra(fonte, conteudo)

    # OS VEÍCULOS NASCEM UMA VEZ, antes das fontes irmãs: as duas leem o mesmo
    # arquivo e veriam os mesmos veículos. Criar por fonte faria a segunda achar
    # tudo já cadastrado — inofensivo — e contaria a criação duas vezes no
    # resumo, o que faria a tela mentir o número que a pessoa autorizou.
    #: COM QUE TIPO QUEM FALA NASCE, dito pela fonte: `veiculo` no clipping de
    #: imprensa, `perfil_rede` no social listening. Procurar e criar sempre em
    #: `veiculo` faria "deolhoemesteio" virar veículo de imprensa — e um dia
    #: candidato à lista de imprensa econômica da lente Mercado.
    quem_fala = _mapeamento_de(fonte).quem_fala
    #: ABERTA UMA VEZ, como na conferência: a subida fazia três leituras do
    #: mesmo arquivo (os veículos, e uma gravação por irmã). Ver `ArquivoLido`.
    arquivo = _lido(conteudo)
    reconhecimento = veiculos_da_imprensa.reconhecer(
        sessao, veiculos_da_planilha(sessao, fonte, arquivo), quem_fala
    )
    autorizados = {normalizar(nome) for nome in veiculos_a_criar}
    a_criar = tuple(
        novo for novo in reconhecimento.novos if normalizar(novo.nome) in autorizados
    )
    criados = veiculos_da_imprensa.criar(sessao, a_criar, quem_fala)
    de_cadastro = {**reconhecimento.cadastrados, **criados}

    return [
        _ingerir_uma(
            sessao,
            irma,
            arquivo,
            de_cadastro,
            len(criados),
            e_recorte=irma.id != fonte.id,
        )
        for irma in fontes_do_mesmo_arquivo(sessao, fonte)
    ]


#: A coluna do alcance do veiculo, no nome que a Clipei usa.
#:
#: LIDA PELO NOME, e e a excecao do modulo: `Abrangencia` nao tem campo em
#: `mencao`, entao nao ha o que mapear em `score_fonte`. Fonte que a chame de
#: outra coisa simplesmente nao a traz, e o veiculo nasce sem esfera — o que e
#: melhor que nao nascer.
COLUNA_DA_ABRANGENCIA = "Abrangência"


def veiculos_da_planilha(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes | ArquivoLido
) -> dict[str, dict[str, object]]:
    """Nome do veículo -> praça, alcance e quantas menções o citam.

    LÊ PELO MAPEAMENTO DA FONTE, e não por nome de coluna fixo: a Clipei chama
    de `Veículo`, e o dia em que outro fornecedor mandar veículo a coluna dele
    vai ter outro nome. Fonte que não mapeia `veiculo` devolve vazio, e isso é
    correto — a Approach e a Bites são redes sociais, não têm veículo.

    `Estado do Veículo` e `Abrangência` SÃO LIDOS PELO NOME DA COLUNA, e é a
    exceção: eles não têm campo em `mencao` (a abrangência não tem; o estado vai
    para `uf`), então não há o que mapear. Ficam declarados aqui, com o nome que
    a Clipei usa, e uma fonte que os chame de outra coisa simplesmente não os
    traz — o veículo nasce sem praça, que é melhor que não nascer.
    """
    mapeamento = _mapeamento_de(fonte)
    coluna_do_veiculo = mapeamento.colunas.get("veiculo")
    if not coluna_do_veiculo:
        return {}

    coluna_do_estado = mapeamento.colunas.get("uf")
    #: O CARGO VEM JUNTO, porque é ele que decide o público do perfil no
    #: cadastro — vereador é Poder Legislativo / Municipal, e não formador de
    #: opinião. Sem isto, o cargo alimentava a régua e o gráfico, e o cadastro
    #: nascia sem ele.
    coluna_do_cargo = mapeamento.colunas.get("cargo")
    #: O TIER VEM JUNTO, porque é a relevância com que o veículo nasce no
    #: cadastro — e a planilha a traz. Sem isto a ingestão cria o veículo jogando
    #: fora uma coluna que estava no arquivo.
    #:
    #: PELO MAPEAMENTO, como o resto: na Clipei a coluna se chama "Aegea Tier", e
    #: as fontes de rede social não mapeiam `tier` nenhum — o perfil nasce sem
    #: relevância, que é a verdade.
    coluna_do_tier = mapeamento.colunas.get("tier")
    achados: dict[str, dict[str, object]] = {}
    for linha in _linhas_da_aba(conteudo, mapeamento):
        #: PELA MESMA FUNÇÃO DA GRAVAÇÃO. A célula crua traria `@casadevovodede`
        #: e `casadevovodede` como dois perfis — a tela listaria dois para
        #: cadastrar, e o cadastro ganharia duas linhas para um perfil.
        nome = quem_falou(linha.get(coluna_do_veiculo), mapeamento)
        if not nome:
            continue
        registro = achados.setdefault(
            nome, {"uf": "", "abrangencia": "", "cargo": "", "tier": "", "mencoes": 0}
        )
        #: O PRIMEIRO NÃO VAZIO, DE VERDADE. `setdefault` não serve aqui: ele só
        #: age quando a CHAVE falta, ou seja na primeira linha daquele veículo, e
        #: guarda o valor daquela linha — vazio incluído —, mandando para o lixo
        #: um valor preenchido numa linha seguinte.
        #:
        #: O CARGO É O MAIS CARO DOS QUATRO, porque é ele que decide o PÚBLICO do
        #: perfil (`CATEGORIA_POR_CARGO`): primeira linha sem cargo faz o
        #: vereador nascer sem público. E o risco não é teórico — cerca de 10%
        #: das menções têm tier nulo, então a primeira linha de um veículo ser
        #: uma dessas não é remoto.
        #:
        #: O CONFLITO ENTRE DOIS VALORES PREENCHIDOS fica com o primeiro. Um
        #: perfil com dois cargos na mesma planilha é dado a corrigir; o que
        #: falta é a conferência MOSTRAR o que vai ser usado, e para o tier ela
        #: ainda não mostra.
        for chave, valor in (
            ("uf", linha.get(coluna_do_estado) if coluna_do_estado else None),
            ("abrangencia", linha.get(COLUNA_DA_ABRANGENCIA)),
            ("cargo", linha.get(coluna_do_cargo) if coluna_do_cargo else None),
            ("tier", linha.get(coluna_do_tier) if coluna_do_tier else None),
        ):
            if not registro[chave]:
                registro[chave] = str(valor or "").strip()
        registro["mencoes"] = int(registro["mencoes"]) + 1
    return achados


def assuntos_da_planilha(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes | ArquivoLido
) -> dict[str, int]:
    """Assunto → quantas linhas o citam, CONTADO COMO A SUBIDA CONTA.

    PELA LEITURA, e não pela célula crua, porque percorrer a aba direto erra
    duas coisas — as duas contra a razão de existir da conferência, que é
    prometer o que vai acontecer:

    1. NENHUM FILTRO OU DESCARTE seria aplicado. Linha que cai por sentimento
       ilegível entraria na conta, e a tela diria "N acham o assunto" sobre um
       total que o resumo depois de gravar não reproduz. Pior na fonte que
       RECORTA o arquivo, que contaria o clipping inteiro.
    2. O TEXTO NÃO PASSARIA POR `_rotulo`, que tira o prefixo de taxonomia do
       fornecedor e aplica os apelidos. Nas duas fontes da Approach, cuja célula
       vem como `2 - Aegea - Falta de Água`, a conferência listaria todos os
       assuntos como desconhecidos e mandaria a pessoa cobrar do fornecedor um
       problema que não existe.

    LÊ O ARQUIVO DE NOVO, como `veiculos_da_planilha`: é o preço de não ter
    tabela de rascunho, e o mesmo desenho do resto da conferência.

    E NÃO LÊ NADA quando a fonte não mapeia assunto — a saída antecipada depende
    da coluna DESTA pergunta, e não de um conjunto delas: a fonte sem assunto,
    mas com concessionária, leria o arquivo e recusaria um `b""`.
    """
    if not _mapeamento_de(fonte).colunas.get("tema"):
        return {}
    return contagens_da_planilha(sessao, fonte, conteudo)[0]


def unidades_da_planilha(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes | ArquivoLido
) -> dict[str, int]:
    """Concessionária → quantas linhas a citam, CONTADA COMO A SUBIDA CONTA.

    PELA LEITURA, pelas mesmas duas razões que `assuntos_da_planilha` explica:
    sem ela a conferência contaria linhas que o filtro descarta, e o texto não
    passaria por `_rotulo` — que aplica os apelidos POR FONTE (a `bites` dobra
    "Aegea" em "Holding" ali). Conferir por um caminho e gravar por outro é
    prometer uma coisa e fazer outra.

    E NÃO LÊ NADA quando a fonte não mapeia concessionária — a `crm` é uma
    delas —, pelo mesmo motivo que vale para os assuntos.
    """
    if not _mapeamento_de(fonte).colunas.get("unidade"):
        return {}
    return contagens_da_planilha(sessao, fonte, conteudo)[1]


def contagens_da_planilha(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes | ArquivoLido
) -> tuple[dict[str, int], dict[str, int]]:
    """Os assuntos E as concessionárias do arquivo, NUMA LEITURA SÓ.

    AS DUAS JUNTAS PORQUE SAEM DA MESMA `Leitura`, e separá-las custaria uma
    decodificação a mais do arquivo inteiro. Isso importa acima do orçamento de
    memória (`orcamento_de_leitura`): ali `ArquivoLido` não guarda nada e cada
    chamada decodifica de novo, então uma função a mais seria 25% a mais de
    tempo na conferência do arquivo grande — justamente o caso em que ela já é
    lenta. `tests/test_a_planilha_e_aberta_uma_vez.py` prende a conta.

    NÃO É UM AGREGADO DE CONVENIÊNCIA: as duas contagens têm o mesmo contrato
    (texto cru do fornecedor → linhas que o citam, vazio como chave para "veio
    sem"), percorrem a mesma lista e são consumidas lado a lado por `conferir`.
    """
    mapeamento = _mapeamento_de(fonte)
    tem_tema = bool(mapeamento.colunas.get("tema"))
    tem_unidade = bool(mapeamento.colunas.get("unidade"))
    if not tem_tema and not tem_unidade:
        return {}, {}

    leitura = ler_planilha(
        _linhas_da_aba(conteudo, mapeamento),
        mapeamento,
        _recorte_por_lista(sessao, fonte, mapeamento),
    )
    assuntos: dict[str, int] = {}
    unidades: dict[str, int] = {}
    for mencao in leitura.mencoes:
        #: VAZIO É CHAVE VAZIA, e é o que `reconhecer` conta como "veio sem".
        if tem_tema:
            texto = mencao.tema_texto or ""
            assuntos[texto] = assuntos.get(texto, 0) + 1
        if tem_unidade:
            unidade = mencao.unidade_texto or ""
            unidades[unidade] = unidades.get(unidade, 0) + 1
    return assuntos, unidades


def recusar_a_fonte(fonte: ScoreFonte) -> None:
    """As recusas que dependem SÓ DO CADASTRO, sem olhar byte nenhum.

    SEPARADAS PORQUE A SUBIDA EM PARTES PRECISA DELAS ANTES DOS BYTES. Quando a
    planilha sobe em pedaços, a abertura da subida acontece quando nada chegou
    ainda — e descobrir "esta fonte é interna" na décima primeira parte é fazer
    a pessoa pagar o upload inteiro para ouvir não.

    E NÃO DÁ PARA CHAMAR `recusar_o_que_nao_entra(fonte, b"")` na abertura:
    aquela função também confere a assinatura de ZIP, que `b""` nunca tem, e
    recusaria toda planilha.
    """
    if fonte.interna:
        raise RegraViolada(
            f"{fonte.nome} é fonte interna: o dado já está neste banco e não se importa."
        )
    if not fonte.ativo:
        raise RegraViolada(f"{fonte.nome} está inativa. Reative-a antes de importar.")


def recusar_o_que_nao_entra(fonte: ScoreFonte, conteudo: bytes) -> None:
    """As recusas que valem ANTES de abrir a planilha, para os dois caminhos.

    SÃO AS MESMAS QUATRO, NA MESMA ORDEM, nos dois caminhos, e é esse o ponto:
    conferir com um conjunto de recusas e gravar com outro faz a conferência
    mentir sobre o que a subida faria, que é a única coisa que ela existe para
    dizer.

    Só em `ingerir`, dava para conferir uma fonte interna, uma fonte inativa, um
    `.pdf` renomeado e um arquivo acima do teto, e descobrir na hora de gravar —
    depois de a pessoa ter escolhido os veículos. E ficou caro quando a
    conferência passou a GUARDAR o arquivo
    (`casos_de_uso/planilha_do_score`): a planilha acima do teto era armazenada,
    ganhava `planilha_id`, e se a pessoa desistisse o byte ficava.
    """
    recusar_a_fonte(fonte)
    if len(conteudo) > TAMANHO_MAXIMO:
        #: O NÚMERO SAI DA CONSTANTE, e não do texto: a mensagem escrita à mão
        #: envelhece em silêncio e manda a pessoa cortar a planilha por nada
        #: (mesmo jeito de `app/armazenamento/blob.py`).
        raise RegraViolada(
            f"A planilha passa de {TAMANHO_MAXIMO // (1024 * 1024)} MB."
        )
    if not conteudo.startswith(ASSINATURA_ZIP):
        raise RegraViolada(
            "O arquivo não é uma planilha .xlsx. "
            "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
        )


def conferir(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes
) -> tuple[
    list[Resumo],
    veiculos_da_imprensa.Reconhecimento,
    temas_da_mencao.Reconhecimento,
    unidade_da_mencao.Reconhecimento,
]:
    """O que a subida FARIA, sem gravar nada.

    POR QUE ELA EXISTE. O veículo sem cadastro nasce junto com a subida, por
    pedido do dono do produto, e a conta aparece ANTES — é isso que torna a
    coisa segura, porque uma subida só pode fazer nascer milhares de veículos. A
    importação de agendas tem a razão escrita no próprio código: "importação de
    planilha sem conferência humana cria duplicata de instituição em massa, e
    desfazer isso depois é pior que digitar de novo".

    A LEITURA É A MESMA DA SUBIDA, de propósito: as recusas estruturais (arquivo
    que não abre, aba que falta, coluna que o cadastro espera e não existe)
    aparecem aqui, antes de a pessoa escolher nada. Conferir com um leitor
    diferente do que grava seria conferir outra coisa.

    NÃO ESCREVE, e há teste para isso. `_ingerir_uma` grava; esta só lê.
    """
    #: AS MESMAS RECUSAS DA SUBIDA, e aqui elas chegam antes de o arquivo ser
    #: guardado. Ver `recusar_o_que_nao_entra`.
    recusar_o_que_nao_entra(fonte, conteudo)
    #: ABERTA UMA VEZ, e as quatro etapas abaixo reusam a leitura: duas na
    #: previsão (uma por irmã), uma nos veículos e uma nos assuntos. Ver
    #: `ArquivoLido`.
    arquivo = _lido(conteudo)
    previsao = [
        _prever_uma(sessao, irma, arquivo)
        for irma in fontes_do_mesmo_arquivo(sessao, fonte)
    ]
    #: AS DUAS CONTAGENS NUMA LEITURA SÓ. Chamar `assuntos_da_planilha` e
    #: `unidades_da_planilha` lado a lado daria o mesmo resultado e uma
    #: decodificação a mais do arquivo — ver `contagens_da_planilha`.
    assuntos, unidades = contagens_da_planilha(sessao, fonte, arquivo)
    #: OS ASSUNTOS TAMBÉM SÃO CONFERIDOS ANTES, e pelo mesmo motivo dos
    #: veículos: o critério do dossiê por N1/N2/N3 sai do vínculo com o
    #: cadastro, e menção sem vínculo não entra em recorte nenhum. Ver o nome
    #: que não casou ANTES de gravar é a diferença entre corrigir a planilha e
    #: descobrir o buraco depois, no gráfico vazio.
    return (
        previsao,
        veiculos_da_imprensa.reconhecer(
            sessao,
            veiculos_da_planilha(sessao, fonte, arquivo),
            _mapeamento_de(fonte).quem_fala,
        ),
        temas_da_mencao.reconhecer(sessao, assuntos),
        #: E AS CONCESSIONÁRIAS, pelo mesmo motivo dos assuntos — com uma
        #: diferença que vale dizer: o nome que não resolve aqui não é
        #: necessariamente um nome ERRADO. "Águas do Pará" está escrito certo e
        #: mesmo assim não liga, porque o cadastro tem quatro blocos e a
        #: planilha não diz qual. A lista traz as opções ao lado justamente
        #: para a pessoa distinguir "corrija a planilha" de "diga o bloco".
        unidade_da_mencao.reconhecer(sessao, unidades),
    )


def _prever_uma(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes | ArquivoLido
) -> Resumo:
    """O resumo de uma fonte sem gravar — o mesmo cálculo de `_ingerir_uma`."""
    mapeamento = _mapeamento_de(fonte)
    #: A CONFERÊNCIA RECORTA IGUAL À SUBIDA. Se a previsão lesse o arquivo sem
    #: a lista, a tela prometeria 25.457 menções de Mercado e o banco gravaria
    #: 323 — e a conferência existe justamente para prometer o que vai
    #: acontecer.
    leitura = ler_planilha(
        _linhas_da_aba(conteudo, mapeamento),
        mapeamento,
        _recorte_por_lista(sessao, fonte, mapeamento),
    )
    return Resumo(
        fonte=fonte.codigo,
        nome=fonte.nome,
        linhas=leitura.linhas,
        ingeridas=len(leitura.mencoes),
        #: PELOS MESES QUE A SUBIDA SUBSTITUIRIA, e não pelos que renderiam
        #: menção: é o que faz a conferência prometer o que vai acontecer
        #: quando o recorte por lista zera um mês.
        antes=_quanto_havia(sessao, fonte, list(leitura.meses_a_substituir(mapeamento))),
        descartes=leitura.descartes,
        avisos={motivo: total for motivo, total in leitura.avisos.items() if total},
        meses=leitura.meses_a_substituir(mapeamento),
    )
