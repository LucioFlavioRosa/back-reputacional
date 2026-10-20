"""As três rotas das lentes. A LEITURA não mora mais aqui.

ESTE ARQUIVO TINHA 2.403 LINHAS, e 1.344 delas eram 30 funções auxiliares
privadas — mais da metade das 3.183 linhas que `docs/ESTRUTURA_E_EXPANSAO.md`
§7.1 mediu em auxiliares de rota no projeto inteiro. Em 17/10/2026 elas saíram:

    casos_de_uso/leitura_das_lentes.py   a leitura (30 funções)
    esquemas/lentes.py                   os modelos de resposta (11 classes)
    este arquivo                         as 3 rotas, e só

O MOTIVO NÃO FOI TAMANHO. Nenhuma daquelas funções tocava o pedido HTTP: todas
recebiam `(sessao, lente, mes, calibracao, filtro)` e devolviam modelo de
saída. Mas, privadas e dentro de `api/`, a única forma de perguntar "como está
a Imprensa este mês?" era fazer um pedido com sessão de navegador. O painel vai
ganhar mais automações de leitura, geração de texto por IA e uma segunda
interface, e as três querem exatamente esta leitura.

O QUE FICOU: receber o pedido, resolver `mes`/`filtro`, decidir o que o papel de
quem pede PODE ver, chamar a leitura e devolver. Nada mais.

UM ENDPOINT, UMA TELA. A regra 2 do pacote: o front não calcula. Ele recebe a
nota, os KPIs, a série, os dois painéis e as frases já montados — e só decide
cor, ordem e tamanho.

NENHUM TEXTO ANALÍTICO É SALVO. Manchete, títulos de gráfico e a lista de
sinais saem de detectores sobre os próprios dados, a cada leitura: mudar um
dado muda a frase. Guardá-los faria a tela afirmar em setembro o que era
verdade em junho.

CADA BLOCO VIAJA COM A SUA FICHA. `Ficha` diz de onde o número veio (planilha,
CRM, cadastro, relatório transcrito), que colunas o alimentam, o que FALTA hoje
e se o conteúdo é exemplo. É o conteúdo do "?" que abre em cima de cada
gráfico.

Isso não é documentação: é parte do dado. Metade do que esta tela mostra não
sai das planilhas — a matriz de jornalistas, a trajetória de rating, o estudo
de percepção e quantas mensagens foram respondidas vêm do relatório do cliente,
transcritos. Apresentá-los com a mesma cara de uma contagem medida é o jeito
mais barato de destruir a confiança num painel: basta o leitor descobrir
sozinho, uma vez.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencias import UsuarioLogado, exigir_portal_score
from app.banco import repositorio_lentes, repositorio_score
from app.banco.sessao import SessaoDoPedido
from app.casos_de_uso.leitura_das_lentes import (
    com_conclusao,
    drivers_e_riscos,
    evolucao,
    frase_do_recorte,
    kpis,
    materias_recentes,
    nomeia_o_diretorio,
    onde_esta_a_causa,
    paineis,
    saida_da_ficha,
    temas_mais_falados,
    trilha_do_recorte,
    veiculos,
    veiculos_tier1,
    volume_por_tier,
)
from app.casos_de_uso.ler_sinais_da_lente import ler_sinais, regua_dos_sinais
from app.dominio.erros import NaoEncontrado
from app.dominio.lentes import (
    Conceito,
    Ficha,
    Procedencia,
)
from app.dominio.periodo import mes_de
from app.dominio.score import FiltroDeMencoes, formula_aplicada
from app.dominio.sinais_da_lente import Secao
from app.esquemas.lentes import (
    DossieSaida,
    ExploradorSaida,
    FatoSaida,
    GrupoDoExploradorSaida,
    OpcoesDeFiltroSaida,
    RecorteSaida,
    SinalSaida,
)

rotas = APIRouter(
    prefix="/api/score/lentes",
    tags=["score"],
    dependencies=[Depends(exigir_portal_score)],
)

Sessao = SessaoDoPedido

#: Quantos meses a evolução mostra. Fixos, e não "os que têm dado": o buraco
#: faz parte da leitura — ver `repositorio_lentes.meses_ate`.
MESES_DA_EVOLUCAO = 8

FICHA_DO_DESTAQUE = Ficha(
    origem=Procedencia.CALCULO,
    fonte="Derivado das fontes da lente pela régua em vigor",
    conceitos=(
        Conceito(
            termo="Nota da lente",
            texto=(
                "O saldo de sentimento das fontes ligadas, na escala de 0 a "
                "100. Com mais de uma fonte, as menções das duas entram na "
                "mesma conta: um denominador só, para a soma dos recortes "
                "fechar com a nota."
            ),
        ),
        Conceito(
            termo="Variação",
            texto="Contra o mesmo cálculo no mês anterior. Nula sem os dois meses.",
        ),
    ),
)

#: CAMINHO TRANSITÓRIO. A especificação pede `GET /score/lentes/{lente}`, que
#: hoje é a rota antiga da aba — a que devolve só composição, fórmula e temas. O
#: dossiê fica em `/dossie` até a tela migrar; aí a antiga sai e este endpoint
#: assume o caminho da especificação. Duas rotas com o mesmo caminho seriam
#: resolvidas por ordem de registro, que é o tipo de dependência invisível que
#: quebra num refactor e ninguém liga ao que mudou.
@rotas.get("/{codigo}/dossie")
def obter_dossie(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    #: As dimensões que o padrão Aegea trouxe (0055). Elas se empilham com as de
    #: cima: `?uf=RJ&perfil_autor=Figura+pública` é "figuras públicas no Rio", e
    #: não uma coisa ou a outra. É o nível 3 do pacote, e é o que faz um link
    #: reproduzir o ponto exato do caminho.
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
    tema_n1: Annotated[str | None, Query(description="pilar (N1) da taxonomia, pelo nome")] = None,
    tema_n2: Annotated[str | None, Query(description="tema estratégico (N2), pelo nome")] = None,
    tema_n3: Annotated[str | None, Query(description="tema (N3) do cadastro, pelo nome")] = None,
    sentimento: Annotated[str | None, Query(description="pos, neu ou neg")] = None,
) -> DossieSaida:
    """A lente inteira: nota, KPIs, evolução, dois painéis, texto e ações.

    OS QUATRO PARÂMETROS SÃO UM RECORTE DE TELA, não a Calibração: ver
    `FiltroDeMencoes`. Ativo, ele recalcula nota, KPIs, evolução e os dois
    painéis sobre o subconjunto de menções que casa com ele — mas NUNCA entra
    no ISR nem é comparado com o mês anterior como se fosse a nota oficial.
    """
    alvo = mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")

    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        autor=autor,
        empresa=empresa,
        tema_n1=tema_n1,
        tema_n2=tema_n2,
        tema_n3=tema_n3,
        sentimento=sentimento,
    )
    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_lentes.meses_ate(alvo, MESES_DA_EVOLUCAO)

    medidas = {
        medida.codigo: medida for medida in repositorio_score.medir_lentes(sessao, alvo, calibracao)
    }
    medida_sem_filtro = medidas[lente.codigo]

    if filtro.ativo:
        # A NOTA FILTRADA NÃO VEM DO LOTE DAS CINCO: `medir_lentes` só lê
        # `score_mes_fonte`, que não tem veículo/atributo/tema — ver
        # `repositorio_score.medir_uma_lente`.
        medida = repositorio_score.medir_uma_lente(sessao, lente, alvo, calibracao, filtro)
        # "VS. MÊS ANTERIOR" NÃO FAZ SENTIDO AQUI: o mês passado não tem o
        # mesmo recorte. A comparação vira "este recorte vs. o mês inteiro",
        # que é a pergunta que o filtro está mesmo respondendo.
        delta = (
            medida.score - medida_sem_filtro.score
            if medida.score is not None and medida_sem_filtro.score is not None
            else None
        )
        delta_versus = "sem_filtro"
    else:
        anteriores = {
            medida.codigo: medida
            for medida in repositorio_score.medir_lentes(
                sessao, meses[-2] if len(meses) > 1 else alvo, calibracao
            )
        }
        medida = medida_sem_filtro
        antes = anteriores.get(lente.codigo)
        delta = (
            medida.score - antes.score
            if medida.score is not None and antes and antes.score is not None
            else None
        )
        delta_versus = "mes_anterior"

    #: OS LOCAIS NÃO PODEM TER O NOME DA FUNÇÃO. Eles tinham, enquanto as
    #: funções eram `_evolucao`/`_paineis`/`_volume_por_tier` neste mesmo
    #: arquivo. Quando a leitura saiu para `casos_de_uso/leitura_das_lentes` as
    #: funções perderam o `_`, e `evolucao = evolucao(...)` passou a sombrear o
    #: import — `UnboundLocalError` na primeira chamada. O `ruff` pegou os três
    #: antes de qualquer teste rodar (F823).
    bloco_da_evolucao = evolucao(sessao, lente, alvo, meses, calibracao, None, filtro)
    blocos_dos_paineis = paineis(sessao, lente, alvo, meses, calibracao, filtro)
    bloco_do_volume = volume_por_tier(sessao, lente, alvo, calibracao, filtro)
    top_veiculos, clima_por_veiculos = veiculos(sessao, lente, alvo, calibracao, filtro)
    tier1 = veiculos_tier1(sessao, lente, alvo, calibracao, filtro)
    drivers = drivers_e_riscos(sessao, lente, alvo, calibracao, filtro)
    temas_falados = temas_mais_falados(sessao, lente, alvo, calibracao, filtro)
    materias = materias_recentes(sessao, lente, alvo, calibracao, filtro)
    #: `ve_diretorio` CHEGA ATÉ AQUI porque uma das abas publica nome de gente de
    #: fora: na Imprensa, `autor` é o jornalista — o mesmo cadastro de terceiros
    #: que a matriz de jornalistas publica e que esta permissão guarda. Achado de
    #: revisão: a aba entregava por outra porta o que o painel esconde.
    causa = onde_esta_a_causa(
        sessao, lente, alvo, calibracao, filtro, ve_diretorio=usuario.ve_diretorio
    )

    #: O QUE ESTE PAPEL NÃO ALCANÇA. `score_leitura` e `score_edicao` têm
    #: `acessa_score` e NÃO têm `ve_diretorio` — e levam 403 em
    #: `GET /api/instituicoes` pelo motivo escrito em `exigir_diretorio`. O
    #: dossiê entregava a eles a mesma classe de dado por outra porta.
    #:
    #: OS SINAIS VÃO JUNTO, e essa é a metade que se esquece: o detector de
    #: concentração narra o primeiro colocado do painel pelo nome, então
    #: esconder o quadro e manter a frase publicaria exatamente o que o quadro
    #: publicava, em uma linha de texto.
    escondidos = (
        set()
        if usuario.ve_diretorio
        else {
            secao
            for indice, secao in ((0, Secao.PAINEL_A), (1, Secao.PAINEL_B))
            if nomeia_o_diretorio(
                repositorio_lentes.lente_e_interna(sessao, lente.id),
                blocos_dos_paineis[indice],
            )
        }
    )
    leitura = ler_sinais(
        sessao,
        lente,
        alvo,
        meses,
        calibracao,
        limites=regua_dos_sinais(calibracao),
        nome_do_painel_a=blocos_dos_paineis[0].titulo,
        nome_do_painel_b=blocos_dos_paineis[1].titulo,
        secoes_a_omitir=escondidos,
        filtro=filtro,
    )
    onde = {
        Secao.EVOLUCAO: "Evolução",
        Secao.PAINEL_A: blocos_dos_paineis[0].titulo,
        Secao.PAINEL_B: blocos_dos_paineis[1].titulo,
        Secao.GERAL: "Lente",
    }

    return DossieSaida(
        codigo=lente.codigo,
        nome=lente.nome,
        stakeholder=lente.stakeholder,
        mes=f"{alvo:%Y-%m}",
        nota=medida.score,
        ns=round(medida.ns, 4) if medida.ns is not None else None,
        delta=delta,
        delta_versus=delta_versus,
        recorte_filtrado=filtro.ativo,
        peso=medida.peso,
        estimado=medida.estimado,
        ausencia=medida.ausencia,
        fontes=list(medida.fontes),
        formula=formula_aplicada(lente.codigo, calibracao),
        kpis=kpis(sessao, lente, alvo, meses, calibracao, medida, filtro),
        ficha_do_destaque=saida_da_ficha(FICHA_DO_DESTAQUE),
        manchete=leitura.manchete,
        # QUEM DESENHA CONTAGEM SAI COM A PRÓPRIA CONCLUSÃO (sobre matéria, não
        # sobre nota) — ver o comentário em `evolucao`. Sobrescrevê-la aqui
        # reintroduziria a mesma frase da manchete em cima de um gráfico de
        # contagem: duas unidades diferentes sem nada dizendo que são
        # diferentes.
        #
        # O MERCADO ENTROU NESTA LISTA junto com o gráfico. Ele herdava a frase
        # da nota porque desenhava o eventograma, onde não havia contagem com
        # que a frase pudesse se confundir. Agora desenha a mesma série da
        # Imprensa — e deixá-lo herdando a frase da nota traria de volta,
        # exatamente nele, o defeito que esta lista existe para evitar.
        #
        # Clientes e Institucional continuam herdando o sinal do período:
        # Clientes desenha recebidas × respondidas e a Institucional desenha
        # clima de agenda, e para nenhuma das duas a frase de volume de matéria
        # faria sentido.
        evolucao=(
            bloco_da_evolucao
            if lente.codigo in ("imprensa", "sociedade", "mercado")
            else com_conclusao(bloco_da_evolucao, leitura.titulo_da_evolucao)
        ),
        sinais_da_evolucao=leitura.sinais_da_evolucao,
        volume_por_tier=bloco_do_volume,
        top_veiculos=top_veiculos,
        clima_por_veiculos=clima_por_veiculos,
        veiculos_tier1=tier1,
        drivers_e_riscos=drivers,
        temas_mais_falados=temas_falados,
        materias_recentes=materias,
        fatos=[
            FatoSaida(mes=f"{fato.mes:%Y-%m}", texto=fato.texto, efeito=fato.efeito)
            for fato in repositorio_score.fatos_do_periodo(sessao, meses)
        ],
        onde_esta_a_causa=causa,
        paineis=[
            com_conclusao(bloco, titulo)
            for secao, bloco, titulo in (
                (Secao.PAINEL_A, blocos_dos_paineis[0], leitura.titulo_do_painel_a),
                (Secao.PAINEL_B, blocos_dos_paineis[1], leitura.titulo_do_painel_b),
            )
            if secao not in escondidos
        ],
        sinais=[
            SinalSaida(
                tipo=sinal.tipo,
                frase=sinal.frase,
                evidencia=sinal.evidencia,
                onde=onde[sinal.secao],
                tom=sinal.tom.value,
            )
            for sinal in leitura.lista
            # REDUNDANTE DE PROPÓSITO. `ler_sinais` já descartou estes sinais na
            # origem, e é lá que a correção mora. Esta linha custa nada e recusa
            # o payload caso alguém chame a leitura sem `secoes_a_omitir` — o
            # jeito exato como a manchete vazou na primeira tentativa.
            if sinal.secao not in escondidos
        ],
    )

@rotas.get("/{codigo}/recorte")
def obter_recorte(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
    tema_n1: Annotated[str | None, Query(description="pilar (N1) da taxonomia, pelo nome")] = None,
    tema_n2: Annotated[str | None, Query(description="tema estratégico (N2), pelo nome")] = None,
    tema_n3: Annotated[str | None, Query(description="tema (N3) do cadastro, pelo nome")] = None,
    sentimento: Annotated[str | None, Query(description="pos, neu ou neg")] = None,
) -> RecorteSaida:
    """O nível 3 do pacote: o que o drawer abre quando alguém clica num dado.

    POR QUE NÃO BASTAVA O RECORTE NA TELA INTEIRA — e esta foi a correção que o
    dono do produto pediu com estas palavras: "ao clicar em um dado temos que
    abrir um modal com o deep diving, e não como é feito hoje". Aplicar o filtro
    na tela inteira REFAZ o mês: a nota muda, os painéis se refazem, e quem
    clicou perde de vista o mês de onde saiu. É recortar, não aprofundar. O
    drawer põe o pedaço AO LADO do mês, com a trilha de volta.

    OS MESMOS PARÂMETROS DO DOSSIÊ, e isso não é repetição preguiçosa: é o que
    faz um link reproduzir o ponto exato do caminho, e o que permite a mesma
    barra de filtros e o mesmo clique levarem ao mesmo lugar.
    """
    alvo = mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")

    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        autor=autor,
        empresa=empresa,
        tema_n1=tema_n1,
        tema_n2=tema_n2,
        tema_n3=tema_n3,
        sentimento=sentimento,
    )
    calibracao = repositorio_score.calibracao_vigente(sessao)
    meses = repositorio_lentes.meses_ate(alvo, MESES_DA_EVOLUCAO)
    trilha = trilha_do_recorte(lente.codigo, filtro)

    #: A LENTE QUE LÊ O CRM NÃO TEM O QUE RECORTAR, e isto foi achado de revisão.
    #: O filtro é de `mencao`; a Institucional conta interações. A resposta
    #: misturava duas contas de universos diferentes: a nota vinha de `mencao`
    #: (zero, porque não há) e a composição e o histórico vinham do CRM INTEIRO,
    #: porque `serie_da_lente` ignora o filtro na lente interna — cada número
    #: certo no seu mundo, e lado a lado se contradizendo sem nada explicando.
    #:
    #: A TRILHA FICA, para a pessoa ver o que pediu e poder desfazer.
    if filtro.ativo and repositorio_lentes.lente_e_interna(sessao, lente.id):
        return RecorteSaida(
            lente=lente.codigo,
            mes=f"{alvo:%Y-%m}",
            trilha=trilha,
            nota=None,
            impacto=0,
            composicao={"positivo": 0, "neutro": 0, "negativo": 0},
            itens=0,
            itens_no_mes=0,
            frase=(
                f"{lente.nome} não vem de menções: ela conta as agendas registradas "
                "no CRM, e este recorte não se aplica a elas."
            ),
            ausencia=(
                f"{lente.nome} lê o CRM dos Stakeholders, e o recorte da tela filtra "
                "menções de planilha. Remova o recorte para ver esta lente."
            ),
            historico=[],
            dentro=[],
            itens_do_recorte=materias_recentes(sessao, lente, alvo, calibracao, None),
        )

    medida = repositorio_score.medir_uma_lente(sessao, lente, alvo, calibracao, filtro)
    #: MEDIDO UMA VEZ e reusado no histórico — ver `denominador_do_mes`.
    denominador = repositorio_score.denominador_do_mes(sessao, lente.id, alvo, calibracao)
    impacto = repositorio_score.impacto_do_recorte(
        sessao, lente.id, alvo, calibracao, filtro, denominador
    )

    serie = repositorio_lentes.serie_da_lente(sessao, lente.id, meses, calibracao, filtro)
    do_mes = repositorio_lentes.serie_da_lente(sessao, lente.id, [alvo], calibracao, None)
    deste_mes = next((linha for linha in serie if linha["mes"] == alvo), None)
    composicao = {
        "positivo": int(deste_mes["pos"]) if deste_mes else 0,
        "neutro": int(deste_mes["neu"]) if deste_mes else 0,
        "negativo": int(deste_mes["neg"]) if deste_mes else 0,
    }
    itens = sum(composicao.values())
    no_mes = sum(int(do_mes[0][chave]) for chave in ("pos", "neu", "neg")) if do_mes else 0

    #: O HISTÓRICO É O IMPACTO MÊS A MÊS, e não a contagem: a pergunta é "este
    #: pedaço pesava o mesmo antes", e peso se mede em pontos. A contagem vai ao
    #: lado porque um impacto pequeno com muitos itens e um impacto pequeno com
    #: dois itens são situações diferentes.
    #:
    #: A NOTA DO MÊS NÃO SAI DAQUI, e eu já tentei que saísse — duas vezes achado
    #: de revisão, pela mesma razão de fundo: um segundo caminho para o mesmo
    #: número.
    #:
    #: O DONO DO PRODUTO LEU A COLUNA COMO VARIAÇÃO MÊS A MÊS, e ele leu certo o
    #: que a tela mostrava: cada número é a distância da nota daquele mês até 50,
    #: e nada dizia isso. Eu resolvi derivando a nota aqui (`50 + impacto`, que é
    #: identidade exata quando não há recorte) — e a revisão mostrou DOIS furos:
    #:
    #:   arredondamento   `impacto` já vinha com 2 casas, e `round(50 + 35.50)`
    #:                    dá 86 onde `para_score` dá 85
    #:   estimativa       `medir_uma_lente` exclui `score_estimativa` de
    #:                    propósito, então num mês estimado a lente publica nota
    #:                    e este histórico diria "sem base"
    #:
    #: A NOTA OFICIAL JÁ ESTÁ NA TELA: `PontoDaSerie.notas_das_lentes` é o número
    #: que a própria Jornada desenha, mês a mês, estimativa incluída. Medi-lo de
    #: novo aqui custaria `indice_do_mes` oito vezes (cinco lentes por chamada)
    #: para chegar, na melhor das hipóteses, ao mesmo valor. A tela junta os dois;
    #: aqui fica só o que é desta conta — o impacto.
    historico = []
    for linha in serie:
        do_mes = round(
            repositorio_score.impacto_do_recorte(
                sessao,
                lente.id,
                linha["mes"],
                calibracao,
                filtro,
                #: O DO MÊS ALVO JÁ ESTÁ NA MÃO; os outros sete se medem aqui.
                denominador if linha["mes"] == alvo else None,
            ),
            2,
        )
        historico.append(
            {
                "mes": f"{linha['mes']:%Y-%m}",
                "impacto": do_mes,
                "itens": int(linha["pos"] + linha["neu"] + linha["neg"]),
                "sem_base": bool(linha["sem_base"]),
                #: A PONTUAÇÃO DO RECORTE, mês a mês — pedido do dono do produto:
                #: "traga a pontuação, que é mais fácil de comunicar".
                #:
                #: O IMPACTO CONTINUA SENDO A CONTA CERTA para "quanto este pedaço
                #: mexe na nota da lente", e é o número grande do topo do painel.
                #: Mas numa coluna de oito meses ele não se lê: −2,1 ao lado de
                #: +1,0 diz que mexeu para baixo e para cima, e não se o pedaço
                #: está bem ou mal. A nota diz as duas coisas, na escala que todo
                #: mundo na Aegea já usa.
                #:
                #: SÓ COM RECORTE ATIVO, e a divisão é deliberada: sem recorte, o
                #: número certo é o da série que desenha a Jornada (estimativa
                #: incluída), e a tela já o tem. Derivá-lo aqui foi duas vezes
                #: achado de revisão — arredondamento duplo, e "sem base" nos
                #: meses de nota estimada.
                #:
                #: 21 ms PARA OS OITO MESES, medido: a nota de um pedaço não
                #: existe em lugar nenhum senão medindo.
                #: O MÊS ALVO JÁ FOI MEDIDO para o topo do painel — achado de
                #: revisão: ele lia as somas filtradas três vezes (a medida, o
                #: impacto e esta nota). Os outros sete se medem aqui.
                "nota": (
                    medida.score
                    if linha["mes"] == alvo
                    else repositorio_score.medir_uma_lente(
                        sessao, lente, linha["mes"], calibracao, filtro
                    ).score
                )
                if filtro.ativo and not linha["sem_base"]
                else None,
            }
        )

    return RecorteSaida(
        lente=lente.codigo,
        mes=f"{alvo:%Y-%m}",
        trilha=trilha,
        nota=medida.score,
        impacto=round(impacto, 2),
        composicao=composicao,
        itens=itens,
        itens_no_mes=no_mes,
        frase=frase_do_recorte(lente, filtro, impacto, composicao, itens, no_mes),
        #: A MESMA AUSÊNCIA DO DOSSIÊ, pela mesma razão: um recorte sem
        #: correspondência tem de DIZER isso, e não cair no mês como se o filtro
        #: não existisse.
        ausencia=medida.ausencia if not itens else None,
        historico=historico,
        dentro=onde_esta_a_causa(
            sessao,
            lente,
            alvo,
            calibracao,
            filtro,
            ja_usadas=filtro,
            ve_diretorio=usuario.ve_diretorio,
            aprofundamento=True,
        ),
        itens_do_recorte=materias_recentes(sessao, lente, alvo, calibracao, filtro),
    )

@rotas.get("/{codigo}/dossie/opcoes-de-filtro")
def obter_opcoes_de_filtro(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
) -> OpcoesDeFiltroSaida:
    """Os valores que o recorte da tela pode oferecer NESTE mês.

    NÃO É DICIONÁRIO: tier é fechado, mas veículo/atributo/tema são texto
    livre de cada fornecedor — ver `repositorio_lentes.opcoes_de_filtro`.
    """
    alvo = mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")
    return OpcoesDeFiltroSaida(**repositorio_lentes.opcoes_de_filtro(sessao, lente.id, alvo))


@rotas.get("/{codigo}/explorador")
def obter_explorador(
    sessao: Sessao,
    usuario: UsuarioLogado,
    codigo: str,
    mes: Annotated[str, Query(description="AAAA-MM")],
    tier: Annotated[str | None, Query()] = None,
    veiculo: Annotated[str | None, Query()] = None,
    atributo: Annotated[str | None, Query()] = None,
    tema: Annotated[str | None, Query()] = None,
    perfil_autor: Annotated[str | None, Query()] = None,
    uf: Annotated[str | None, Query()] = None,
    subtema: Annotated[str | None, Query()] = None,
    autor: Annotated[str | None, Query()] = None,
    empresa: Annotated[str | None, Query()] = None,
    tema_n1: Annotated[str | None, Query(description="pilar (N1) da taxonomia, pelo nome")] = None,
    tema_n2: Annotated[str | None, Query(description="tema estratégico (N2), pelo nome")] = None,
    tema_n3: Annotated[str | None, Query(description="tema (N3) do cadastro, pelo nome")] = None,
    sentimento: Annotated[str | None, Query(description="pos, neu ou neg")] = None,
) -> ExploradorSaida:
    """Os gráficos N1 › N2 › N3 e o mapa por UF da Síntese executiva.

    UM PEDIDO POR MÊS E RECORTE DA TELA, e o filtro cruzado (clicar num N1
    refaz N2, N3 e o mapa) acontece no navegador, somando os grupos — ver
    `grupos_do_explorador`. Os mesmos parâmetros do dossiê: a barra de filtros
    do topo vale aqui também.

    A LENTE QUE LÊ O CRM NÃO TEM MENÇÃO, e volta vazia (sem erro): a tela só
    pede para as lentes de clipping.
    """
    alvo = mes_de(mes)
    lente = repositorio_lentes.lente_por_codigo(sessao, codigo)
    if lente is None:
        raise NaoEncontrado("Lente não encontrada.")
    if repositorio_lentes.lente_e_interna(sessao, lente.id):
        return ExploradorSaida(lente=lente.codigo, mes=f"{alvo:%Y-%m}", denominador=0, grupos=[])

    filtro = FiltroDeMencoes(
        tier=tier,
        veiculo=veiculo,
        atributo=atributo,
        tema_texto=tema,
        perfil_autor=perfil_autor,
        uf=uf,
        subtema=subtema,
        autor=autor,
        empresa=empresa,
        tema_n1=tema_n1,
        tema_n2=tema_n2,
        tema_n3=tema_n3,
        sentimento=sentimento,
    )
    calibracao = repositorio_score.calibracao_vigente(sessao)
    regua, denominador = repositorio_score.denominador_do_mes(sessao, lente.id, alvo, calibracao)
    grupos = repositorio_lentes.grupos_do_explorador(
        sessao, lente.id, alvo, calibracao, regua, filtro
    )
    return ExploradorSaida(
        lente=lente.codigo,
        mes=f"{alvo:%Y-%m}",
        denominador=denominador,
        grupos=[GrupoDoExploradorSaida(**grupo) for grupo in grupos],
    )
