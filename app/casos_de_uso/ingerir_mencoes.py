"""A planilha do fornecedor entrando no índice.

O que este módulo acrescenta ao `dominio/ingestao_score.py`: abrir o `.xlsx`
(openpyxl), achar a aba, casar o cabeçalho com o mapeamento gravado e trocar o
mês inteiro no banco. A regra de o que vira menção NÃO mora aqui.

UM ARQUIVO PODE ALIMENTAR VÁRIAS FONTES, e o upload trata todas de uma vez. O
export da Clipei vira a lente Imprensa inteira e, recortado por público
investidor, a lente Mercado; o da Approach traz Social Listening e Community
Management em abas diferentes do mesmo `.xlsx`. Importar por uma fonte só
deixaria a irmã com o mês anterior, e duas lentes passariam a ler versões
diferentes do mesmo arquivo — uma divergência que ninguém veria na tela, porque
cada lente mostraria um número plausível. Quem diz quais fontes andam juntas é
o campo `arquivo` do mapeamento, que é cadastro.

SUBSTITUIÇÃO POR MÊS, e não acréscimo. O fornecedor reenvia o arquivo quando
corrige uma classificação — e o mesmo post reenviado, somado, contaria duas
vezes. Cada mês presente no arquivo é apagado e regravado; um mês que o arquivo
não traz fica intacto, porque o export de junho não é uma afirmação sobre maio.

O PREÇO DISSO É UM ARQUIVO PARCIAL PODER ENCOLHER UM MÊS: um export baixado
antes do fechamento substitui o mês cheio pelo pedaço. Não dá para o servidor
distinguir "o fornecedor reclassificou e sobraram menos" de "baixaram cedo
demais" — os dois chegam como um arquivo com menos linhas. O que dá é NÃO
DEIXAR ISSO PASSAR CALADO: o resumo diz quantas menções o mês tinha antes de a
troca acontecer, ao lado de quantas entraram.

POR QUE O AGREGADO SE REFAZ AQUI. `score_mes_fonte` guarda as quatro somas de
que toda régua precisa. Como a substituição deixa o banco com exatamente as
menções do arquivo para aqueles meses, as somas do arquivo JÁ SÃO as somas do
mês — não há por que relê-las do banco para conferir a própria escrita.

UMA CONSEQUÊNCIA A CARREGAR: `soma_log` e `soma_cargo` congelam, no instante da
ingestão, as fórmulas de `dominio/score.py` (`peso_do_engajamento` e
`peso_do_cargo`). Mudar uma delas NÃO reescreve o passado. É de propósito — o
número que a diretoria citou em julho continua sendo o que ela citou —, e o
grão para reprocessar, se um dia for preciso, está inteiro em `mencao`.
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
#: enviado por engano não é. O maior export real medido é de 10,53 MB — o
#: clipping de janeiro a julho da Clipei, 75.369 linhas (16/10/2026; a nota
#: anterior aqui dizia 3,8 MB, de um recorte menor) —, e o teto é pedido do dono
#: do produto: planilhas de até 80 MB.
#:
#: O `client_max_body_size` DO NGINX DO FRONT FICA ACIMA DISTO (81m), e a ordem
#: é o que importa: o nginx vem primeiro, então cortar lá primeiro troca esta
#: mensagem — que diz o tamanho aceito — por um 413 seco do proxy. Já esteve
#: desalinhado: 26m de nginx contra 40 MB aqui deixava um vão de 14 MB em que o
#: arquivo era recusado sem explicação. Quem mudar um muda o outro.
#:
#: E O TETO DE BYTES NÃO É O LIMITE REAL destas planilhas: o tempo é. O ingress
#: do Container Apps corta a requisição por volta de 240 s, e o clipping de
#: 3,8 MB já levou 22,9 s de processamento. 80 MB passam por aqui e podem não
#: terminar lá. Arquivo dessa ordem pede importação em segundo plano.
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
    #: Os veículos são criados UMA vez, antes das fontes irmãs, porque as duas
    #: leem o mesmo arquivo e veriam os mesmos veículos. Então este número vem
    #: REPETIDO em cada resumo da lista, com o mesmo valor.
    #:
    #: NÃO SOME A LISTA: duas fontes irmãs com 2.628 criações cada dariam 5.256,
    #: e nasceram 2.628. A tela mostra uma vez — é o número que a pessoa acabou
    #: de autorizar na conferência, e ele tem de bater com o que ela marcou.
    veiculos_criados: int = 0
    #: Quantas menções DESTA fonte acharam veículo no cadastro. Esta é por
    #: fonte, e somar não faz sentido por outro motivo: as irmãs recortam o
    #: mesmo arquivo, então a menção da lente Mercado também está na Imprensa.
    #:
    #: É o número que diz o quanto a ponte cobre, e o que cresce a cada subida
    #: com criação: medido depois da primeira carga, 76,7%.
    mencoes_ligadas: int = 0
    #: Quantas menções DESTA fonte acharam assunto no cadastro de temas.
    #:
    #: É O NÚMERO QUE DIZ SE O FILTRO DA TAXONOMIA TEM DADO: o dossiê recorta
    #: por N1/N2/N3 pelo `tema_id`, então menção sem vínculo não aparece em
    #: recorte nenhum. Medido antes desta etapa: zero em 29.898.
    mencoes_com_tema: int = 0


def _linhas_da_aba(
    conteudo: bytes | ArquivoLido, mapeamento: Mapeamento
) -> Iterator[Mapping[str, object]]:
    """As linhas da planilha como dicionários cabeçalho → célula.

    ABRE O ARQUIVO A CADA CHAMADA quando recebe bytes, e é por isso que quem faz
    mais de uma passada passa um `ArquivoLido`: a conferência fazia quatro
    leituras do mesmo arquivo e gastava 14,3s onde hoje gasta 2,7s. Ver
    `ArquivoLido`.
    """
    return _lido(conteudo).linhas(mapeamento)


def _como_o_openpyxl(celula: object) -> object:
    """Uma célula do calamine na forma que o openpyxl entregava.

    Chamada uma vez por célula — 300 mil vezes num arquivo de 25.000 linhas —,
    e por isso é só dois testes. Mesmo assim custa uma fração do que se ganhou:
    a decodificação caiu de 2,55s para 0,27s.
    """
    if celula == "":
        return None
    if type(celula) is float and celula.is_integer():
        return int(celula)
    return celula


# =============================================================================
# QUANDO VALE LER RÁPIDO E GUARDAR A LEITURA
#
# A pergunta é uma só — "a leitura desta planilha cabe na memória deste
# contêiner?" — e dela sai TUDO: o leitor rápido e o cache andam juntos em
# `ArquivoLido.linhas`, porque `_pelo_calamine` só é alcançável pelo ramo que
# guarda. Dizer "não" perde os dois de uma vez.
#
# O QUE HAVIA ANTES, E POR QUE SAIU. A pergunta era respondida por
# `len(conteudo) <= 8 MB`: o byte COMPRIMIDO do `.xlsx`. Medido em 16/10/2026
# nos dois arquivos reais, esse proxy erra por 3,2×:
#
#     Clipei     10,53 MB comprimido  ->  66,19 MB de XML da aba   (6,3x)
#     Approach    3,27 MB comprimido  ->   6,48 MB de XML da aba   (2,0x)
#
# Com um número só para os dois, ou se recusa o cache a quem cabe, ou se
# concede a quem não cabe. Era o primeiro caso: o clipping da Clipei caía no
# caminho lento e a conferência gastava 47,5 s só decodificando — quatro
# passadas de 11,88 s —, contra 1,40 s pelo caminho rápido. É daí que vinham os
# 113 s que estouraram o gateway do cliente em 15/10/2026.
#
# E O BYTE COMPRIMIDO NÃO SABE DE ABAS. O arquivo da Approach tem SETE, e cada
# fonte lê uma: julgar pelo arquivo inteiro cobra de uma aba o tamanho das
# outras seis.
# =============================================================================

#: TRÊS TERMOS, PORQUE O CUSTO TEM TRÊS FONTES — e a primeira versão tinha um
#: só, o que subestimava por até 141×.
#:
#: O QUE A PRIMEIRA VERSÃO ERRAVA. Ela cobrava 200 B por célula e pronto. Mas o
#: TEXTO de um `.xlsx` não mora na aba: mora em `xl/sharedStrings.xml`, e a aba
#: guarda referências de ~30 B. Uma planilha de poucas células com textos
#: enormes tinha aba pequena, estimativa pequena, e pico gigante. Medido em
#: 16/10/2026 com arquivos montados à mão para isolar a forma (10.000 células):
#:
#:     texto/célula    aba      sharedStrings   estimava   custava    erro
#:           10 B     0,36 MB      0,29 MB        2,0 MB    2,1 MB    1,0x
#:          100 B     0,36 MB      1,15 MB        2,0 MB    3,6 MB    1,8x
#:            1 KB    0,36 MB      9,74 MB        2,0 MB   29,8 MB   14,7x
#:           10 KB    0,36 MB     95,57 MB        2,0 MB  287,7 MB  141,8x
#:
#: E SOMAR `sharedStrings.file_size` NÃO BASTA, que era a correção óbvia: com
#: texto REPETIDO o arquivo deduplica e aquele número vai a zero, enquanto o
#: custo continua — o calamine materializa uma string Python POR CÉLULA. No caso
#: medido: sharedStrings de 0,00 MB e pico de 19,1 MB.
#:
#: O QUE FALTAVA É A RAZÃO `count/uniqueCount`, que o `<sst>` declara no próprio
#: cabeçalho: quantas células referenciam texto contra quantos textos distintos
#: existem. `sharedStrings × razão` é o texto como ele é MATERIALIZADO. Na Clipei
#: a razão é 13,2 (11,36 MB de arquivo, 150 MB materializados); na Approach, 4,8.
#:
#: OS TRÊS COEFICIENTES, ajustados contra nove casos — os dois arquivos reais e
#: sete montados. Nenhum caso subestima; a folga vai de 1,08x a 1,45x:
#:
#:     Clipei          294 MB reais -> 357 estimados   1,21x
#:     Approach         40,5        ->  58,7           1,45x
#:     10 B              2,1        ->   2,4           1,13x
#:      1 KB            29,8        ->  34,0           1,14x
#:     10 KB           287,7       -> 321             1,12x
#:      1 KB repetido   19,1       ->  23,4           1,23x
#:    100 B x 100k      49,0       ->  52,9           1,08x
#:
#: SUBESTIMAR MATA O PROCESSO; superestimar só custa tempo, porque o caminho
#: lento continua correto. Por isso os coeficientes ficam acima do ajuste.

#: A célula em si: o `tuple`, o objeto Python do valor, o overhead do dicionário
#: rio abaixo. Sai de 123 B/célula ajustados, arredondado para cima.
MEMORIA_POR_CELULA = 140

#: A CÉLULA DE PREENCHIMENTO, que não traz valor nenhum — e que até 22/10/2026
#: era cobrada pelos mesmos 140 B da que traz.
#:
#: POR QUE ELA EXISTE. `iter_rows` devolve a linha INTEIRA até a última coluna
#: que a aba declara, e as colunas sem valor vêm como `None`. Numa aba larga e
#: vazia isso é a maioria das células — mas é sempre o MESMO `None`: o que
#: custa é o ponteiro na tupla, não um objeto por célula.
#:
#: MEDIDO em 22/10/2026 no export de bonds que o Q&A recusou (649 KB,
#: `ref="A1:BR54254"`), com `tracemalloc` sobre o que `ingerir_bonds` faz:
#:
#:     células materializadas  3.797.780      pico real      36,6 MB
#:     dessas, com valor          12.598      estimado então  507,1 MB   13,9x
#:
#: 36,6 MB / 3,8 M células são 9,7 B/célula com TUDO incluído. 12 arredonda para
#: cima, como os outros coeficientes deste bloco.
#:
#: A ASSIMETRIA ERA O ESTRAGO: superestimar nas lentes só derruba para o caminho
#: lento, que continua correto; em `ingerir_bonds` não há caminho lento, e a
#: mesma conta recusava o arquivo na cara de quem subia.
MEMORIA_POR_CELULA_VAZIA = 12

#: O TEXTO COMO CADA CÉLULA O MATERIALIZA (`sharedStrings × count/uniqueCount`).
#: 0,55 porque o byte de XML vira caractere Python com overhead, e a
#: deduplicação do arquivo não se repete na memória.
MEMORIA_POR_TEXTO_MATERIALIZADO = 0.55

#: O TEXTO ÚNICO que o leitor guarda uma vez (o lado Rust do calamine). 2,8
#: sobre o tamanho de `sharedStrings.xml` — é o termo que domina quando o texto
#: é longo e distinto, que é justamente o caso que a versão anterior não via.
MEMORIA_POR_TEXTO_UNICO = 2.8

#: BYTES DE XML QUE UMA CÉLULA OCUPA, para quando a planilha não declara as
#: dimensões dela. Medido: 38 B/célula na Clipei e 31 na Approach. 35 fica no
#: meio, e a estimativa só é usada quando é a MAIOR das duas — ver
#: `celulas_da_maior_aba`.
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
#: MEDIDO, e desmente o que esta nota dizia antes. Ela afirmava que "v2 é o que
#: AKS e Container Apps usam hoje". Em 16/10/2026 eu li dentro da réplica
#: implantada no **Container Apps**:
#:
#:     /sys/fs/cgroup/memory.max                    -> No such file or directory
#:     /sys/fs/cgroup/memory/memory.limit_in_bytes  -> 4294967296
#:
#: Ou seja: o Container Apps usa **v1**. Se este módulo lesse só o v2 — o
#: "moderno", que é o que a nota errada sugeria —, o orçamento cairia no padrão
#: conservador e o ganho desta leitura desapareceria EM SILÊNCIO exatamente no
#: ambiente para o qual ele foi medido.
#:
#: O AKS documenta v2 como padrão desde o Kubernetes 1.25, e é por isso que o
#: v2 continua primeiro. Ler os dois é o que faz a decisão viajar entre os dois
#: ambientes sem ninguém reparar.
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

    CUSTA 6,7 ms no clipping de 10,53 MB, porque lê o diretório central do ZIP —
    que já traz o tamanho descomprimido de cada arquivo — e descomprime só os
    primeiros 4 KB da aba maior, à caça do `<dimension>`.

    A MAIOR ABA, e não a aba que se vai ler: resolver nome de aba até o arquivo
    exigiria `xl/workbook.xml` mais `xl/_rels/workbook.xml.rels`, e o ganho seria
    estimar o que já está limitado. A maior aba é um teto para qualquer aba do
    arquivo — erra para o lado de recusar o cache, que custa tempo, nunca o
    processo.

    AS DUAS ESTIMATIVAS, E A MAIOR DELAS VENCE. A dimensão declarada é exata
    quando existe, mas `<dimension>` é opcional no formato e há quem escreva
    `ref="A1:A1"` numa aba de 60 MB — confiar nela sozinha concederia o cache a
    um arquivo enorme. O tamanho do XML é grosseiro mas nunca mente sobre ordem
    de grandeza. Pegar o máximo deixa o erro sempre do lado seguro:

        Clipei    dimensão 1.733.510   XML 1.983.000   ->  1.983.000  (+14%)
        Approach  dimensão   219.140   XML   194.000   ->    219.140  (exato)

    E A DIFERENÇA ENTRE AS DUAS É O PREENCHIMENTO, que é o conserto de
    22/10/2026. Quando a dimensão declara MAIS do que o XML comporta, o excesso
    não é célula com valor: são as vagas que `iter_rows` devolve como `None`
    para completar a linha. Elas existem (medi: o openpyxl preenche mesmo) e
    custam ~9 B, não os 140 de uma célula de verdade — ver
    `MEMORIA_POR_CELULA_VAZIA`.

        bonds Q&A  dimensão 3.797.780   XML   152.890
                   -> materializadas 3.797.780, ocupadas 152.890

    O MÁXIMO CONTINUA EM `materializadas`, e é de propósito: é ele que impede a
    dimensão que mente PARA BAIXO (`ref="A1:A1"` numa aba de 60 MB) de conceder
    o cache a um arquivo enorme. Quando o XML vence, `ocupadas` iguala
    `materializadas`, o termo do preenchimento zera e a conta é a de sempre —
    por isso esta mudança não mexe em nenhum arquivo que já funcionava.

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
    que a estimativa anterior não tinha. Com texto repetido o arquivo guarda uma
    cópia e o leitor materializa uma string Python por célula — medido: 0,00 MB
    de `sharedStrings` contra 19,1 MB de pico.

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

    TRÊS TERMOS, um por fonte de custo — ver os coeficientes no topo. Custa
    ~9 ms no clipping de 10,53 MB: o diretório central do ZIP mais 6 KB
    descomprimidos.

    `None` quando qualquer parte não se deixa estimar.
    """
    celulas = celulas_da_maior_aba(conteudo)
    texto = bytes_de_texto(conteudo)
    if celulas is None or texto is None:
        return None
    materializado, unico = texto
    #: QUATRO TERMOS DESDE 22/10/2026: a célula com valor e a vaga de
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

    O ORÇAMENTO É DO PROCESSO, NÃO DO ARQUIVO — e esta é a correção de um
    defeito meu que a revisão do Codex achou em 16/10/2026. A versão anterior
    comparava cada arquivo com o orçamento inteiro, então DUAS leituras
    simultâneas na mesma réplica podiam tomar duas vezes aquilo: `0,8 L` mais os
    ~88 MB que o processo já carrega. Num contêiner de 512 MiB isso são ~498 de
    537 MB; três leituras passam claramente.

    AS DUAS RÉPLICAS NÃO COMPARTILHAM MEMÓRIA, mas uma delas atende pedidos
    concorrentes, e o Uvicorn com um worker não serializa nada disto.

    A SEGUNDA LEITURA DEGRADA, NÃO FALHA: quem não cabe na folga que sobrou vai
    pelo caminho lento, de memória constante. É a mesma degradação de quem é
    grande demais — e é por isso que isto é controle de admissão e não uma trava
    que faz esperar: esperar transformaria duas importações simultâneas em uma
    fila de dois minutos, e o resultado é o mesmo arquivo lido.
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

    POR QUE EXISTE, com os números que a motivaram. Medido com 25.000 linhas (o
    tamanho do export real da Clipei), abrir e percorrer o `.xlsx` custa 5,1s —
    e a conferência fazia isso QUATRO vezes: duas na previsão (uma por fonte
    irmã), uma nos veículos e uma nos assuntos. Davam 14,3s, dos quais 0,02s
    eram banco. Reusando as células, as quatro passadas custam 0,10s.

    O CUSTO É A DECODIFICAÇÃO DO XML, não o dicionário por linha: guardar as
    células de uma passada não pesa por linha, e é o que elimina as outras três
    leituras.

    GUARDA A ABA INTEIRA, linhas do topo inclusive, e a BUSCA DO CABEÇALHO
    continua sendo de cada fonte. Não é detalhe: `_achar_o_cabecalho` procura a
    primeira linha que traz as `colunas_necessarias` DAQUELA fonte, e duas irmãs
    podem exigir conjuntos diferentes. Guardar o cabeçalho da primeira faria a
    segunda recusar uma coluna que existe numa linha mais abaixo — hoje as duas
    da Clipei exigem o mesmo, mas era armadilha montada. Achado de revisão.

    A VALIDAÇÃO DE COLUNA também é por fonte, pelo mesmo motivo: o que se reusa
    é a leitura; o que cada cadastro exige, cada uma confere.

    UMA ABA POR ARQUIVO, e o cache é por nome de aba: fonte que peça outra aba
    do mesmo arquivo abre a dela, e não recebe as linhas da vizinha. É o caso
    das duas fontes da Approach, que leem as abas `CM` e `SL` do mesmo arquivo:
    duas decodificações, cada uma da sua aba. As duas da Clipei leem `Clipping`,
    e aí a segunda sai de graça — que é onde está o ganho, porque é esse o
    arquivo de 25.000 linhas.

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
            yield from self._dicionarios(aba.iter_rows(values_only=True), mapeamento)
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
                self._lido[chave] = list(aba.iter_rows(values_only=True))
            finally:
                planilha.close()
        return self._lido[chave]

    def _pelo_calamine(self, mapeamento: Mapeamento) -> list[tuple]:
        """A aba lida pelo calamine, com as células na forma do openpyxl.

        AS TRÊS DIFERENÇAS, achadas comparando célula por célula os dois leitores
        nos dois arquivos reais, e resolvidas aqui para que nada rio abaixo
        precise saber qual leitor trouxe a célula:

        * VAZIO vem como `""`, e não `None`. `_texto` já trata os dois, mas
          `linha.get(coluna) is None` em qualquer lugar passaria a ser falso;
        * INTEIRO vem como `float`, e a coluna `ID` da Clipei é numérica:
          `id_fonte` gravaria `"12345.0"` no lugar de `"12345"`, e é por esse
          campo que se compara matéria com matéria;
        * `to_python()` PULA as linhas vazias do topo por padrão. O leitor
          procura o cabeçalho nas 20 primeiras linhas contando a partir da
          primeira: pular uma mudaria o que ele acha. `skip_empty_area=False`
          devolve a aba como ela é.
        """
        from python_calamine import CalamineWorkbook

        livro = CalamineWorkbook.from_filelike(io.BytesIO(self._conteudo))
        nomes = livro.sheet_names
        if mapeamento.aba and mapeamento.aba not in nomes:
            raise RegraViolada(
                f"A planilha não tem a aba {mapeamento.aba!r}. "
                f"Abas encontradas: {', '.join(nomes)}."
            )
        if not nomes:
            raise RegraViolada("A planilha está vazia.")
        aba = livro.get_sheet_by_name(mapeamento.aba or nomes[0])
        return [
            tuple(_como_o_openpyxl(celula) for celula in linha)
            for linha in aba.to_python(skip_empty_area=False)
        ]

    def _abrir(self, mapeamento: Mapeamento):
        """Abre o arquivo e devolve a planilha e a aba desta fonte."""
        try:
            from openpyxl import load_workbook
        except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
            raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

        # `read_only` não carrega a planilha inteira na memória de uma vez, e
        # `data_only` traz o VALOR de uma célula com fórmula — sem ele, a coluna
        # de engajamento calculada chegaria como a string "=SOMA(...)".
        try:
            planilha = load_workbook(io.BytesIO(self._conteudo), read_only=True, data_only=True)
        except Exception as erro:
            # Um `.xls` antigo, um CSV renomeado ou um upload truncado chegam
            # aqui. Sem a tradução, o openpyxl devolveria 500 e a pessoa leria
            # "erro interno" para um arquivo que ela mesma pode trocar.
            raise RegraViolada(
                "Não consegui abrir o arquivo como planilha .xlsx. "
                "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
            ) from erro

        if mapeamento.aba and mapeamento.aba in planilha.sheetnames:
            return planilha, planilha[mapeamento.aba]
        if mapeamento.aba:
            abas = ", ".join(planilha.sheetnames)
            planilha.close()
            raise RegraViolada(
                f"A planilha não tem a aba {mapeamento.aba!r}. Abas encontradas: {abas}."
            )
        return planilha, planilha[planilha.sheetnames[0]]


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
#: (`N1`, `N2`, `N3`) sobre as colunas Atributo, Categoria e Subcategoria. O
#: leitor assumia a linha 1 e recusava o arquivo inteiro com "a planilha não tem
#: as colunas que o cadastro desta fonte espera" — a mensagem certa para um
#: arquivo errado, e a errada para um arquivo CERTO com uma linha de título.
#:
#: VINTE É FOLGA, e é o mesmo número da importação de subtemas: fornecedor que
#: põe logotipo e data antes do cabeçalho cabe, e um arquivo que realmente não
#: tem as colunas ainda é recusado — com a mesma mensagem, que volta a ser
#: verdade.
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
    do agregado e a contagem do que ninguém classificou, tudo substituindo o mês.
    Uma segunda cópia desta função seria a segunda definição de "o que é um mês
    no banco".
    """
    #: A TRAVA DO ARQUIVO, E A INGESTÃO TAMBÉM A TOMA — correção de achado ALTO
    #: de revisão. A reconciliação já se serializava por ela, mas a subida não
    #: participava: a reconciliação copiava uma linha para o espelho e uma
    #: subida cuja exclusão começara antes do commit dela não via essa linha e
    #: inseria outra cópia. O resultado era duplicação no espelho e no
    #: agregado — justamente o defeito que esta mudança existe para acabar.
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
    #: os DOIS caminhos de escrita, inclusive a `carga_do_pacote_das_lentes`,
    #: que monta a `Leitura` à mão e chama esta função direto.
    #:
    #: UMA CONSULTA POR NÍVEL por gravação, e são 7 N1 + 41 N2 + 104 N3: o
    #: conjunto cabe na memória e a comparação é O(1). Perguntar ao banco por
    #: linha faria da subida de 25.597 linhas um problema de rede.
    #:
    #: A ÁRVORE INTEIRA, e não só o mapa do N3 (`por_nome`), desde a `0098`: o
    #: fornecedor traz um nível e os de cima são derivados daqui. Ver
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

    #: `insert()` EM LOTE, e nao `add_all` com objetos do ORM. Medido com 25.000
    #: linhas: 4,34s instanciando e dando flush, contra 2,11s mandando os
    #: dicionários — dos quais 1,13s eram só para criar objetos que ninguém lê
    #: de volta (esta função não devolve nada, e quem conta usa a `leitura`).
    #: O `id` continua vindo do default da coluna, aplicado pelo próprio
    #: `insert()`.
    #: ONDE O CADASTRO PÕE CADA MENÇÃO, resolvido ANTES de montar os valores.
    #:
    #: Um passo à parte porque `resolver` devolve os TRÊS níveis de uma vez, e
    #: chamá-lo três vezes dentro do dicionário resolveria a árvore três vezes
    #: por linha — 75 mil buscas a mais numa subida de 25 mil linhas, com a
    #: chance de as três discordarem se alguém mexer numa só.
    #: OS MESMOS QUATRO CAMPOS QUE A LEITURA USA (`consulta_profundidade`), e
    #: na mesma ordem de precedência — é o que torna a coluna gravada igual ao
    #: que a tela calcula ao vivo. `tema_id` não entra porque é o que estamos
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
            # bom tempo: a Clipei traz 2.648 veículos distintos e o cadastro
            # começou com 39. A cada subida com criação a cobertura sobe.
            "instituicao_id": de_cadastro.get(normalizar(mencao.veiculo or "")),
            # O ASSUNTO DO CADASTRO, quando o nome casa. Nulo é o normal
            # enquanto o fornecedor não fala o vocabulário do nível — e é o que
            # a conferência mostra antes de gravar. Com o vínculo, o dossiê
            # filtra por Pilar (N1), Tema estratégico (N2) e Subtema (N3).
            #
            # OS TRÊS GRAVADOS, e não só o N3 com o resto por `join`: o
            # fornecedor que descreve a menção só no topo (a Clipei, em 71% do
            # volume) tem N1 e não tem N3, e um `join` a partir de `tema_id`
            # nunca o alcançaria. Ver a `0098`.
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
    #: PLANILHA VAZIA NÃO VIRA `insert` VAZIO: o SQLAlchemy recusaria a lista
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

    SÃO DOIS LADOS DA MESMA PARTIÇÃO, desde que o recorte passou a ser
    EXCLUSIVO (pedido de 20/10/2026: "se o Valor Econômico é um veículo de
    imprensa de mercado, absolutamente todas as matérias dele vão para a lente
    de mercado"):

        a fonte que DECLARA uma lista  fica com os veículos dela
        a fonte irmã que não declara   fica com todo o RESTO do arquivo

    ANTES O ESPELHO FICAVA COM TUDO, e a recortada era uma cópia do subconjunto
    — a mesma matéria contava nas duas lentes. Foi o que a medição mostrou:
    uma subida com duas matérias deixava `clipei` com 2 e `clipei_investidores`
    com 1, e a do Valor Econômico estava nas duas.

    A EXCLUSÃO É DERIVADA DAS IRMÃS, e não declarada no cadastro da fonte. É a
    decisão que importa aqui: declarada, ela sairia de sincronia no dia em que
    alguém criasse um recorte novo e esquecesse de atualizar o espelho — e o
    sintoma seria a matéria voltando a contar duas vezes, em silêncio.
    Derivada, a partição é exata por construção: o que uma inclui, a outra
    exclui, pela MESMA função (`nomes_da_lista`, com os apelidos).

    `None` quando a fonte não recorta nem tem irmã que recorte — e aí
    `ler_planilha` lê tudo, como sempre leu.

    LÊ O CADASTRO UMA VEZ, e não uma consulta por linha: o export da Clipei tem
    25.597 linhas, e perguntar ao banco por cada uma faria da subida um
    problema de rede. São 2.670 veículos cadastrados; o conjunto cabe na
    memória com folga.
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
        #: ZERO NUMA IRMÃ QUE RECORTA É FATO, e não erro — e isto é conserto de
        #: um defeito que vem do commit original da ingestão.
        #:
        #: A lente Mercado é a Clipei recortada por público investidor. Um mês
        #: sem nenhuma menção de investidor é perfeitamente normal, e o erro
        #: derrubava A SUBIDA INTEIRA: as 25.457 menções de Imprensa não
        #: entravam porque o recorte ficou vazio.
        #:
        #: E o problema ia piorar: quando o critério do Mercado virar a
        #: subcategoria do veículo cadastrado, a primeira subida terá zero
        #: veículos classificados — o recorte nasce vazio por construção, e
        #: nenhuma carga da Clipei passaria.
        #:
        #: O MÊS DA IRMÃ NÃO É APAGADO quando o recorte vem vazio: sem meses na
        #: leitura, `regravar` não tem o que substituir, e o que já estava lá
        #: fica. Um recorte vazio num mês não é instrução de esquecer o mês.
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

    O PADRÃO TEM DE SER VAZIO, e isto não é timidez. A tela de Calibração já tem
    um botão "Importar planilha" por fonte, que chama esta função direto. Se o
    padrão fosse "criar tudo", quem clicasse ali criaria 2.631 instituições sem
    ter visto nada — a duplicata em massa que a importação de agendas documenta,
    por uma mudança de assinatura. Quem quer criação pede, nomeando.

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
    #: cadastro — e a planilha a traz. Sem isto, dos 2.670 veículos cadastrados
    #: só 39 tinham relevância: a ingestão criava os outros jogando fora uma
    #: coluna que estava no arquivo.
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
        #: O PRIMEIRO NÃO VAZIO, DE VERDADE — e era aqui o defeito (achado MÉDIA
        #: de revisão, 11/10/2026). O comentário antigo prometia "o primeiro não
        #: vazio" e o código fazia outra coisa: `setdefault` só age quando a CHAVE
        #: falta, ou seja na PRIMEIRA LINHA daquele veículo. O que ele guardava
        #: era o valor daquela linha, VAZIO INCLUÍDO, e um valor preenchido numa
        #: linha seguinte ia para o lixo.
        #:
        #: O CARGO É O MAIS CARO DOS QUATRO, porque é ele que decide o PÚBLICO do
        #: perfil (`CATEGORIA_POR_CARGO`): primeira linha sem cargo fazia o
        #: vereador nascer sem público — o mesmo defeito que
        #: `CATEGORIA_DE_QUEM_FALA` registra como já consertado uma vez.
        #:
        #: E O RISCO É MEDIDO, não teórico: 2.851 das 28.626 menções têm tier
        #: nulo, 10% — a chance de a primeira linha de um veículo ser uma dessas
        #: não é remota.
        #:
        #: O CONFLITO ENTRE DOIS VALORES PREENCHIDOS continua resolvido pelo
        #: primeiro, como antes. Um perfil com dois cargos na mesma planilha é
        #: dado a corrigir; o que falta é a conferência MOSTRAR o que vai ser
        #: usado, e para o tier ela ainda não mostra.
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

    PELA LEITURA, e não pela célula crua. A primeira versão desta função
    percorria as linhas da aba direto, e isso errava duas coisas de uma vez —
    as duas contra a razão de existir da conferência, que é prometer o que vai
    acontecer:

    1. NENHUM FILTRO OU DESCARTE era aplicado. A Bites traz 2.886 linhas e
       1.426 caíam por sentimento ilegível NO ARQUIVO DE 01–09/2026: a tela
       dizia "N acham o assunto" sobre 2.886, e o resumo depois de gravar
       contava sobre ~1.460. (A planilha consolidada já vem com sentimento em
       todas as linhas; o furo era de CAMINHO, não daquele arquivo.) O mesmo
       rótulo, dois números, quase o dobro de diferença. Pior em
       `clipei_investidores`, que recorta o arquivo: contava as 25.597 linhas
       do clipping inteiro.

    2. O TEXTO NÃO PASSAVA POR `_rotulo`, que tira o prefixo de taxonomia do
       fornecedor e aplica os apelidos. Nas duas fontes da Approach, cuja
       célula vem como `2 - Aegea - Falta de Água`, a conferência listaria
       TODOS os assuntos como desconhecidos e a subida ligaria todos — mandando
       a pessoa cobrar do fornecedor um problema que não existe.

    LÊ O ARQUIVO DE NOVO, como `veiculos_da_planilha`: é o preço de não ter
    tabela de rascunho, e o mesmo desenho do resto da conferência.

    E NÃO LÊ NADA quando a fonte não mapeia assunto: a fonte sem a coluna
    confere sem estourar, e é o que `test_fonte_sem_coluna_de_assunto_nao_reclama`
    exige. Foi este teste que pegou a primeira versão de `contagens_da_planilha`,
    onde a saída antecipada passou a depender das DUAS colunas — e aí a fonte
    sem assunto, mas com concessionária, lia o arquivo e recusava um `b""`.
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

    ISTO JÁ ME PEGOU: chamar `recusar_o_que_nao_entra(fonte, b"")` na abertura
    recusava TUDO, porque aquela função também confere a assinatura de ZIP — e
    `b""` nunca a tem. Catorze testes caíram de uma vez, o que foi a sorte: a
    alternativa era a abertura recusando toda planilha em produção.
    """
    if fonte.interna:
        raise RegraViolada(
            f"{fonte.nome} é fonte interna: o dado já está neste banco e não se importa."
        )
    if not fonte.ativo:
        raise RegraViolada(f"{fonte.nome} está inativa. Reative-a antes de importar.")


def recusar_o_que_nao_entra(fonte: ScoreFonte, conteudo: bytes) -> None:
    """As recusas que valem ANTES de abrir a planilha, para os dois caminhos.

    POR QUE ISTO VIROU FUNÇÃO. Estas quatro moravam só em `ingerir`, e a
    conferência não fazia nenhuma delas: dava para conferir uma fonte interna,
    uma fonte inativa, um `.pdf` renomeado e um arquivo de 200 MB — e só
    descobrir na hora de gravar, depois de a pessoa ter escolhido os veículos.

    Ficou caro quando a conferência passou a GUARDAR o arquivo
    (`casos_de_uso/planilha_do_score`): uma planilha acima do teto era
    armazenada, ganhava `planilha_id`, e só era recusada na confirmação — e se
    a pessoa desistisse ali, o byte ficava. Achado da revisão do Codex em
    16/10/2026.

    SÃO AS MESMAS QUATRO, na mesma ordem, e é esse o ponto: conferir com um
    conjunto de recusas e gravar com outro faz a conferência mentir sobre o que
    a subida faria, que é a única coisa que ela existe para dizer.
    """
    recusar_a_fonte(fonte)
    if len(conteudo) > TAMANHO_MAXIMO:
        #: O NÚMERO SAI DA CONSTANTE, e não do texto: a mensagem dizia
        #: "40 MB" enquanto `TAMANHO_MAXIMO` já era 80 — quem recebesse a
        #: recusa cortaria a planilha pela metade por nada. Derivar é o que
        #: impede a mensagem de envelhecer de novo (mesmo jeito de
        #: `app/armazenamento/blob.py`).
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

    POR QUE ELA EXISTE. O dono do produto pediu que o veículo sem cadastro nasça
    junto com a subida, e pediu que a conta apareça ANTES — o que é o que torna
    a coisa segura. Medido contra o export de 08–09/2026: 2.631 veículos
    nasceriam numa subida só. A importação de agendas tem escrito no próprio
    código por que isso precisa de conferência: "importação de planilha sem
    conferência humana cria duplicata de instituição em massa, e desfazer isso
    depois é pior que digitar de novo".

    A LEITURA É A MESMA DA SUBIDA, de propósito: as recusas estruturais (arquivo
    que não abre, aba que falta, coluna que o cadastro espera e não existe)
    aparecem aqui, antes de a pessoa escolher nada. Conferir com um leitor
    diferente do que grava seria conferir outra coisa.

    NÃO ESCREVE, e há teste para isso. `_ingerir_uma` grava; esta só lê.
    """
    #: AS MESMAS RECUSAS DA SUBIDA, e aqui elas chegam antes de o arquivo ser
    #: guardado. Ver `recusar_o_que_nao_entra`.
    recusar_o_que_nao_entra(fonte, conteudo)
    #: ABERTA UMA VEZ, e as quatro etapas abaixo reusam a leitura. Medido com
    #: 25.000 linhas: eram 14,3s em quatro decodificações do mesmo arquivo —
    #: duas na previsão (uma por irmã), uma nos veículos, uma nos assuntos —
    #: contra 0,02s de banco. Ver `ArquivoLido`.
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
