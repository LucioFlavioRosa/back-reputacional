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
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.banco.tabelas_lentes import MencaoNaoClassificada
from app.banco.tabelas_score import Mencao, ScoreFonte, ScoreMesFonte
from app.casos_de_uso import veiculos_da_imprensa
from app.dominio.erros import RegraViolada
from app.dominio.ingestao_score import Leitura, Mapeamento, ler_planilha, somar

# `normalizar` É A MESMA DO CADASTRO, e isso foi verificado: ela e o
# `achatar` da ingestão dão o mesmo resultado nos casos reais. Duas
# normalizações diferentes fariam a menção não achar o veículo que acabou
# de ser criado a partir dela.
from app.dominio.texto import normalizar

#: Abrir uma planilha de 10 mil linhas é barato; abrir um arquivo de 200 MB
#: enviado por engano não é. O maior dos quatro exports de hoje tem 1,4 MB.
TAMANHO_MAXIMO = 40 * 1024 * 1024

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


def _linhas_da_aba(
    conteudo: bytes, mapeamento: Mapeamento
) -> Iterator[Mapping[str, object]]:
    """As linhas da planilha como dicionários cabeçalho → célula."""
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as erro:  # pragma: no cover - dependência declarada
        raise RegraViolada("Leitura de planilha indisponível neste servidor.") from erro

    # `read_only` não carrega a planilha inteira na memória, e `data_only` traz
    # o VALOR de uma célula com fórmula — sem ele, a coluna de engajamento
    # calculada chegaria como a string "=SOMA(...)".
    try:
        planilha = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as erro:
        # Um `.xls` antigo, um CSV renomeado ou um upload truncado chegam aqui.
        # Sem a tradução, o openpyxl devolveria 500 e a pessoa leria "erro
        # interno" para um arquivo que ela mesma pode trocar.
        raise RegraViolada(
            "Não consegui abrir o arquivo como planilha .xlsx. "
            "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
        ) from erro
    try:
        if mapeamento.aba and mapeamento.aba in planilha.sheetnames:
            aba = planilha[mapeamento.aba]
        elif mapeamento.aba:
            raise RegraViolada(
                f"A planilha não tem a aba {mapeamento.aba!r}. "
                f"Abas encontradas: {', '.join(planilha.sheetnames)}."
            )
        else:
            aba = planilha[planilha.sheetnames[0]]

        linhas = aba.iter_rows(values_only=True)
        cabecalho = _achar_o_cabecalho(linhas, mapeamento)

        faltando = sorted(mapeamento.colunas_necessarias - set(cabecalho))
        if faltando:
            raise RegraViolada(
                "A planilha não tem as colunas que o cadastro desta fonte espera: "
                f"{', '.join(faltando)}."
            )

        for linha in linhas:
            yield dict(zip(cabecalho, linha, strict=False))
    finally:
        planilha.close()


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
    de_cadastro = dict(veiculos or {})
    meses = list(leitura.meses)
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

    sessao.add_all(
        Mencao(
            fonte_id=fonte.id,
            mes=mencao.mes,
            data=mencao.data,
            sentimento=mencao.sentimento,
            tier=mencao.tier,
            engajamento=mencao.engajamento,
            cargo=mencao.cargo,
            atributo=mencao.atributo,
            veiculo=mencao.veiculo,
            publico_alvo=mencao.publico_alvo,
            # O VEÍCULO DO CADASTRO, quando ele existe. Nulo é o normal por um
            # bom tempo: a Clipei traz 2.648 veículos distintos e o cadastro
            # começou com 39. A cada subida com criação a cobertura sobe.
            instituicao_id=de_cadastro.get(normalizar(mencao.veiculo or "")),
            tema_texto=mencao.tema_texto,
            unidade_texto=mencao.unidade_texto,
            teor=mencao.teor,
            acionavel=mencao.acionavel,
            autor=mencao.autor,
            # -- os campos do padrão Aegea (0055) ---------------------------
            # Nulos vindos de fonte que não os manda, e é assim que as
            # planilhas antigas continuam entrando sem mudança.
            id_fonte=mencao.id_fonte,
            uf=mencao.uf,
            subtema=mencao.subtema,
            perfil_autor=mencao.perfil_autor,
            titulo_texto=mencao.titulo_texto,
            link=mencao.link,
            peso_tier=mencao.peso_tier,
        )
        for mencao in leitura.mencoes
    )
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


def _ingerir_uma(
    sessao: Session,
    fonte: ScoreFonte,
    conteudo: bytes,
    veiculos: Mapping[str, str] | None = None,
    criados: int = 0,
    e_recorte: bool = False,
) -> Resumo:
    """Lê a planilha pelo mapeamento desta fonte e substitui os meses dela.

    `e_recorte` diz que esta fonte é uma IRMÃ que recorta o arquivo de outra, e
    não a fonte pela qual a pessoa subiu. A diferença está no vazio — ver abaixo.
    """
    mapeamento = _mapeamento_de(fonte)
    leitura = ler_planilha(_linhas_da_aba(conteudo, mapeamento), mapeamento)
    if not leitura.mencoes and not e_recorte:
        #: ZERO NA FONTE PELA QUAL SE SUBIU É ERRO: o arquivo não serve, e
        #: aceitar em silêncio apagaria o mês trocando-o por nada.
        raise RegraViolada(
            f"Nenhuma linha da planilha virou menção em {fonte.nome}. "
            f"Lidas {leitura.linhas}; descartes: {dict(leitura.descartes)}."
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

    antes = _quanto_havia(sessao, fonte, list(leitura.meses))
    regravar(sessao, fonte, leitura, veiculos)
    de_cadastro = dict(veiculos or {})
    return Resumo(
        fonte=fonte.codigo,
        nome=fonte.nome,
        linhas=leitura.linhas,
        ingeridas=len(leitura.mencoes),
        descartes=leitura.descartes,
        meses=leitura.meses,
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
    )


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
    if fonte.interna:
        raise RegraViolada(
            f"{fonte.nome} é fonte interna: o dado já está neste banco e não se importa."
        )
    if not fonte.ativo:
        raise RegraViolada(f"{fonte.nome} está inativa. Reative-a antes de importar.")
    if len(conteudo) > TAMANHO_MAXIMO:
        raise RegraViolada("A planilha passa de 40 MB.")
    if not conteudo.startswith(ASSINATURA_ZIP):
        raise RegraViolada(
            "O arquivo não é uma planilha .xlsx. "
            "Se ele veio em .xls ou .csv, salve como .xlsx e envie de novo."
        )

    # OS VEÍCULOS NASCEM UMA VEZ, antes das fontes irmãs: as duas leem o mesmo
    # arquivo e veriam os mesmos veículos. Criar por fonte faria a segunda achar
    # tudo já cadastrado — inofensivo — e contaria a criação duas vezes no
    # resumo, o que faria a tela mentir o número que a pessoa autorizou.
    reconhecimento = veiculos_da_imprensa.reconhecer(
        sessao, veiculos_da_planilha(sessao, fonte, conteudo)
    )
    autorizados = {normalizar(nome) for nome in veiculos_a_criar}
    a_criar = tuple(
        novo for novo in reconhecimento.novos if normalizar(novo.nome) in autorizados
    )
    criados = veiculos_da_imprensa.criar(sessao, a_criar)
    de_cadastro = {**reconhecimento.cadastrados, **criados}

    return [
        _ingerir_uma(
            sessao,
            irma,
            conteudo,
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
    sessao: Session, fonte: ScoreFonte, conteudo: bytes
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
    achados: dict[str, dict[str, object]] = {}
    for linha in _linhas_da_aba(conteudo, mapeamento):
        nome = str(linha.get(coluna_do_veiculo) or "").strip()
        if not nome:
            continue
        registro = achados.setdefault(
            nome,
            {
                "uf": str(linha.get(coluna_do_estado) or "").strip()
                if coluna_do_estado
                else "",
                "abrangencia": str(linha.get(COLUNA_DA_ABRANGENCIA) or "").strip(),
                "mencoes": 0,
            },
        )
        registro["mencoes"] = int(registro["mencoes"]) + 1
    return achados


def conferir(
    sessao: Session, fonte: ScoreFonte, conteudo: bytes
) -> tuple[list[Resumo], veiculos_da_imprensa.Reconhecimento]:
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
    previsao = [
        _prever_uma(sessao, irma, conteudo)
        for irma in fontes_do_mesmo_arquivo(sessao, fonte)
    ]
    return previsao, veiculos_da_imprensa.reconhecer(
        sessao, veiculos_da_planilha(sessao, fonte, conteudo)
    )


def _prever_uma(sessao: Session, fonte: ScoreFonte, conteudo: bytes) -> Resumo:
    """O resumo de uma fonte sem gravar — o mesmo cálculo de `_ingerir_uma`."""
    mapeamento = _mapeamento_de(fonte)
    leitura = ler_planilha(_linhas_da_aba(conteudo, mapeamento), mapeamento)
    return Resumo(
        fonte=fonte.codigo,
        nome=fonte.nome,
        linhas=leitura.linhas,
        ingeridas=len(leitura.mencoes),
        antes=_quanto_havia(sessao, fonte, list(leitura.meses)),
        descartes=leitura.descartes,
        avisos={motivo: total for motivo, total in leitura.avisos.items() if total},
        meses=tuple(leitura.meses),
    )
