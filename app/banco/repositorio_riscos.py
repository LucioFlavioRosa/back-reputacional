"""O rastreio de risco lido do banco: a série, a matriz e os incidentes.

O CAMINHO É UM SÓ, e é o que torna esta tela possível: `tema_risco` liga o tema
(N3) do cadastro aos riscos da matriz corporativa, e TUDO o que entra na
plataforma por assunto chega a risco pelo mesmo vínculo. Medido em 10/10/2026:

    clipei ................. 25.248 de 25.457 menções chegam a um risco
    bites ...................  2.322 de  2.842
    clipei_investidores .....    319 de    327
    CRM (agendas) ...........    401 de    544, por `interacao_tema`
    approach ................ zero hoje; entra sozinha quando a fonte subir

NÃO HÁ LÓGICA POR FORNECEDOR aqui, e isso é desenho: a fonte é uma dimensão de
filtro, não um caminho de código. Fonte nova que mapeie `tema` aparece nesta
tela sem uma linha a mais.

AS DUAS FAMÍLIAS DE INCIDENTE, que não se somam por acidente: menção negativa
(`mencao.sentimento = 'neg'`) e agenda de clima negativo (`clima.codigo =
'tenso'`). São contadas separadas e somadas no fim, porque uma menção e uma
reunião não são a mesma coisa — e a tela diz qual é qual.

E O CRM PRECISA DA MESMA REGRA DE VISIBILIDADE do resto da plataforma:
`interacao.visivel` e não arquivada. Uma tela de risco que mostre agenda
arquivada contaria como incidente o que alguém retirou do registro.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy import Select, Text, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.banco.filtros_sql import condicoes_de_escopo
from app.banco.tabelas_catalogo import (
    BlocoTema,
    Clima,
    MacroTema,
    Risco,
    RiskCluster,
    Tema,
    TemaRisco,
)
from app.banco.tabelas_interacoes import InteracaoRegistro, InteracaoTema
from app.banco.tabelas_score import Lente, Mencao, ScoreFonte
from app.dominio.identidade import Escopo
from app.dominio.riscos import (
    PESO_DA_SEVERIDADE,
    SEVERIDADES,
    MesDeRisco,
    com_o_indice,
    peso_da_severidade,
)

#: O SENTIMENTO QUE FAZ UM INCIDENTE, na grafia que o banco guarda (ver o CHECK
#: `mencao_sentimento_check`: `pos` | `neu` | `neg`).
SENTIMENTO_DO_INCIDENTE = "neg"

#: O CLIMA QUE FAZ UM INCIDENTE no CRM. `tenso` é o código; o rótulo que a tela
#: mostra é "Negativo" (ver a tabela `clima`), e é por isso que se compara pelo
#: CÓDIGO: o rótulo é editável pela coordenação.
CLIMA_DO_INCIDENTE = "tenso"

#: O CÓDIGO DA FONTE DO CRM, que é a origem das agendas.
FONTE_DO_CRM = "crm"

#: E A LENTE DELA, no cadastro: o CRM é a lente institucional. Está aqui porque
#: o recorte por lente também tem de poder deixar as agendas de fora.
LENTE_DO_CRM = "institucional"


@dataclass(frozen=True, slots=True)
class FiltroDeRisco:
    """O recorte da tela. Tudo opcional: sem nada, é a base inteira.

    `cluster` e `risco` vêm dos CÓDIGOS do cadastro (`risk_cluster.codigo`,
    `risco.codigo`) e não dos ids: é o que o endereço da tela carrega, e id
    numérico no link quebra quando a base do cliente tem outros.
    """

    cluster: str | None = None
    risco: str | None = None
    #: Códigos de `score_fonte` — e `crm` entre eles, que é a fonte das agendas.
    fontes: tuple[str, ...] = ()
    #: Códigos de `lente`, a dimensão PADRONIZADA do Score.
    #:
    #: LENTE NÃO É FONTE, e por isso são dois filtros: a Clipei alimenta DUAS
    #: lentes (imprensa e mercado, pelo público investidores) e a Bites e a
    #: Approach dividem a sociedade digital. Quem pergunta "como está a imprensa"
    #: não está perguntando por um fornecedor, e quem desconfia de uma planilha
    #: não está perguntando por uma lente. Medido no cadastro: 6 fontes, 5
    #: lentes, e o CRM é a institucional.
    lentes: tuple[str, ...] = ()
    #: `critico` | `alto` | `moderado` — a PIOR severidade do incidente.
    #:
    #: PELA PIOR, e não "toca um risco desta severidade": é a mesma régua que
    #: empilha a barra do mês, preenche a coluna da tabela e soma os três números
    #: do topo. Filtrar por "toca" faria o incidente cujo pior é crítico
    #: aparecer também em "alto", e os três números deixariam de somar o total —
    #: exatamente o defeito que a revisão apontou no caminho contrário.
    severidade: str | None = None
    #: OS TRÊS NÍVEIS DO CADASTRO DE TEMAS: `bloco_tema` (N1) > `macro_tema`
    #: (N2) > `tema` (N3). Pelos códigos do cadastro, e o N3 pelo nome, que é o
    #: que ele tem de único.
    #:
    #: ELES CRUZAM TODAS AS FONTES, e é por isso que estão aqui e não entre as
    #: `DIMENSOES`: a premissa da aba é que tudo chega a risco pelo tema do
    #: cadastro, então o tema é a única dimensão que nenhuma fonte deixa de ter.
    #: Medido em 10/10/2026: 7 blocos, 41 macro temas, 104 temas, 100 com risco.
    #:
    #: E SÃO O CAMINHO NATURAL DO APROFUNDAMENTO — N1 > N2 > N3 > incidente —,
    #: que é o que o dono do produto pediu: sair do macro e chegar ao registro.
    bloco: str | None = None
    macro: str | None = None
    tema: str | None = None
    #: A janela da série, pelo PRIMEIRO DIA do mês, inclusiva nas duas pontas.
    de: date | None = None
    ate: date | None = None
    #: Busca livre no texto do incidente, no veículo e no nome do assunto.
    busca: str | None = None
    #: O RECORTE POR DIMENSÃO, pelas chaves de `DIMENSOES`: `{"tier": "relevante"}`.
    #:
    #: UM DICIONÁRIO, e não seis campos: as dimensões que existem saem do DADO
    #: (ver `dimensoes_do_recorte`), e seis campos fixos aqui obrigariam a mexer
    #: nesta classe a cada dimensão nova — exatamente a rigidez que a tela
    #: deixou de ter. Chave que não está em `DIMENSOES` é recusada na rota.
    #:
    #: ACHADO DE REVISÃO: a rota `/opcoes` oferecia as dimensões e NENHUMA rota
    #: as aceitava. A tela ia desenhar filtros que não fazem nada.
    por_dimensao: tuple[tuple[str, str], ...] = ()

    @property
    def dimensoes(self) -> dict[str, str]:
        """O recorte por dimensão como mapa — a tupla é só para o `frozen`."""
        return dict(self.por_dimensao)

    def sem_a_janela(self) -> FiltroDeRisco:
        """O mesmo recorte sem o corte de meses.

        A SÉRIE INTEIRA É O QUE DEFINE A REFERÊNCIA de 100 pontos. Se a janela
        entrasse no cálculo, o índice de um mesmo mês mudaria conforme o período
        que a pessoa escolhesse na tela — e o número deixaria de querer dizer
        algo sobre o mês.
        """
        return FiltroDeRisco(
            cluster=self.cluster,
            risco=self.risco,
            fontes=self.fontes,
            lentes=self.lentes,
            severidade=self.severidade,
            bloco=self.bloco,
            macro=self.macro,
            tema=self.tema,
            busca=self.busca,
            por_dimensao=self.por_dimensao,
        )

    @property
    def tem_crm(self) -> bool:
        """O CRM entra quando nem a fonte nem a lente o deixam de fora.

        A LENTE TAMBÉM O EXCLUI, e esquecer isso seria o pior tipo de erro nesta
        tela: quem escolhe "Imprensa" receberia as reuniões do CRM no meio das
        notícias, e o total não corresponderia a nada que se possa conferir.
        """
        if self.fontes and FONTE_DO_CRM not in self.fontes:
            return False
        return not self.lentes or LENTE_DO_CRM in self.lentes


def _riscos_do_filtro(sessao: Session, filtro: FiltroDeRisco) -> list[int] | None:
    """Os ids de risco que o recorte alcança, ou `None` para "todos".

    `None` E NÃO A LISTA INTEIRA: sem recorte, a consulta não precisa de um `IN`
    com 32 ids — e, mais importante, "todos os riscos" e "os 32 que existem hoje"
    deixam de ser a mesma coisa no dia em que alguém cadastrar o 33º.
    """
    if not filtro.cluster and not filtro.risco:
        return None

    consulta = select(Risco.id).join(RiskCluster, RiskCluster.id == Risco.risk_cluster_id)
    if filtro.cluster:
        consulta = consulta.where(RiskCluster.codigo == filtro.cluster)
    if filtro.risco:
        consulta = consulta.where(Risco.codigo == filtro.risco)
    return list(sessao.scalars(consulta))


def _primeiro_dia_do_mes_seguinte(mes: date) -> date:
    """O dia seguinte ao fim do mês — o limite aberto da janela.

    EM PYTHON, e não com aritmética de intervalo no SQL: a conta é a mesma, o
    teste não precisa de banco, e a consulta fica legível.
    """
    return date(mes.year + (mes.month == 12), (mes.month % 12) + 1, 1)


def mencoes_de_incidente(filtro: FiltroDeRisco, riscos: list[int] | None) -> Select:
    """As menções que contam como incidente, já cruzadas com risco.

    `join` em `TemaRisco` e não `outerjoin`: menção cujo tema não toca risco não
    é incidente desta tela.

    UMA LINHA POR PAR (menção, risco), e não por menção: um tema pode tocar dois
    riscos, e a matriz conta o incidente em cada um deles — é o que "o incidente
    toca estes dois riscos" significa. Quem quer "quantas menções" conta
    `distinct` sobre `mencao_id`, e é o que a série faz.
    """
    consulta = (
        select(
            Mencao.id.label("mencao_id"),
            Mencao.mes.label("mes"),
            Mencao.data.label("data"),
            Mencao.veiculo.label("veiculo"),
            Mencao.tier.label("tier"),
            Mencao.engajamento.label("engajamento"),
            Mencao.titulo_texto.label("titulo"),
            Mencao.link.label("link"),
            #: AS DIMENSÕES DO RECORTE saem daqui — ver `dimensoes_do_recorte`.
            #: Cada fonte preenche as suas: tier e público-alvo na imprensa,
            #: cargo e autor nas redes, praça e concessionária nas duas.
            Mencao.uf.label("uf"),
            Mencao.unidade_texto.label("unidade_texto"),
            Mencao.publico_alvo.label("publico_alvo"),
            Mencao.cargo.label("cargo"),
            Mencao.autor.label("autor"),
            Tema.nome.label("tema"),
            Risco.id.label("risco_id"),
            Risco.codigo.label("risco"),
            Risco.nome.label("risco_nome"),
            Risco.severidade.label("severidade"),
            ScoreFonte.codigo.label("fonte"),
            ScoreFonte.nome.label("fonte_nome"),
            #: A LENTE VEM JUNTO: é a dimensão padronizada, e a tabela a mostra
            #: ao lado da fonte — "Imprensa · Clipei" diz mais do que cada uma.
            Lente.codigo.label("lente"),
            Lente.nome.label("lente_nome"),
        )
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .join(Lente, Lente.id == ScoreFonte.lente_id)
        .join(Tema, Tema.id == Mencao.tema_id)
        .join(TemaRisco, TemaRisco.tema_id == Mencao.tema_id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        .where(
            Mencao.sentimento == SENTIMENTO_DO_INCIDENTE,
            Risco.ativo.is_(True),
            Tema.ativo.is_(True),
        )
    )
    if riscos is not None:
        consulta = consulta.where(Risco.id.in_(riscos))
    if filtro.fontes:
        consulta = consulta.where(ScoreFonte.codigo.in_(filtro.fontes))
    if filtro.lentes:
        consulta = consulta.where(Lente.codigo.in_(filtro.lentes))
    if filtro.severidade:
        consulta = consulta.where(
            Mencao.id.in_(_mencoes_cuja_pior_e(filtro.severidade, riscos, filtro))
        )
    consulta = _so_os_temas_do_recorte(consulta, filtro, Mencao.tema_id)
    if filtro.de:
        consulta = consulta.where(Mencao.mes >= filtro.de)
    if filtro.ate:
        consulta = consulta.where(Mencao.mes <= filtro.ate)
    if filtro.busca:
        procurado = f"%{filtro.busca.strip()}%"
        consulta = consulta.where(
            or_(
                Mencao.titulo_texto.ilike(procurado),
                Mencao.veiculo.ilike(procurado),
                Tema.nome.ilike(procurado),
            )
        )
    #: O RECORTE POR DIMENSÃO. Pelas mesmas colunas que `dimensoes_do_recorte`
    #: oferece — uma cópia da lista aqui seria a chance de oferecer uma coisa e
    #: filtrar outra. Achado de revisão.
    for chave, valor in filtro.dimensoes.items():
        coluna = _COLUNA_DA_DIMENSAO.get(chave)
        if coluna is not None:
            consulta = consulta.where(getattr(Mencao, coluna) == valor)
    return consulta


def agendas_de_incidente(
    filtro: FiltroDeRisco, riscos: list[int] | None, escopo: Escopo
) -> Select | None:
    """As agendas do CRM que contam como incidente, ou `None` se o CRM está fora.

    `interacao` NÃO TEM SENTIMENTO: tem `clima`, que é o Termômetro da tela do
    CRM. Clima negativo é o equivalente da menção negativa, e é a única leitura
    de "incidente" que o CRM oferece sem inventar campo.

    O ESCOPO DO USUÁRIO É OBRIGATÓRIO, e é por isso que ele é parâmetro e não
    campo opcional do filtro: achado de revisão. O CRM restringe por frente e
    por unidade de negócio (`usuario_escopo`), e uma tela de risco sem isso
    contaria como incidente a agenda que a listagem do CRM esconde daquele
    usuário — a mesma agenda, visível num lugar e não no outro. Guarda que se
    pode esquecer de passar é guarda que não existe.
    """
    if not filtro.tem_crm:
        return None
    #: DIMENSÃO DE MENÇÃO EXCLUI A AGENDA. Quem filtra por tier ou por cargo está
    #: perguntando sobre imprensa ou sobre redes; a agenda não tem esses campos,
    #: e devolvê-la junto faria o recorte parecer não ter funcionado. Achado de
    #: revisão: campos de uma fonte só precisam dizer que a ausência é
    #: estrutural.
    if filtro.dimensoes:
        return None

    consulta = (
        select(
            InteracaoRegistro.id.label("interacao_id"),
            func.date_trunc("month", InteracaoRegistro.data_interacao).label("mes"),
            InteracaoRegistro.data_interacao.label("data"),
            Tema.nome.label("tema"),
            Risco.id.label("risco_id"),
            Risco.codigo.label("risco"),
            Risco.nome.label("risco_nome"),
            Risco.severidade.label("severidade"),
        )
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .join(InteracaoTema, InteracaoTema.interacao_id == InteracaoRegistro.id)
        .join(Tema, Tema.id == InteracaoTema.tema_id)
        .join(TemaRisco, TemaRisco.tema_id == InteracaoTema.tema_id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        .where(
            Clima.codigo == CLIMA_DO_INCIDENTE,
            #: A MESMA REGRA DE VISIBILIDADE do resto da plataforma: visível,
            #: não arquivada, e dentro do alcance do usuário.
            InteracaoRegistro.visivel.is_(True),
            InteracaoRegistro.arquivado_em.is_(None),
            *condicoes_de_escopo(escopo),
            Risco.ativo.is_(True),
            Tema.ativo.is_(True),
        )
    )
    if riscos is not None:
        consulta = consulta.where(Risco.id.in_(riscos))
    if filtro.severidade:
        consulta = consulta.where(
            InteracaoRegistro.id.in_(_agendas_cuja_pior_e(filtro.severidade, riscos, filtro))
        )
    consulta = _so_os_temas_do_recorte(consulta, filtro, InteracaoTema.tema_id)
    if filtro.de:
        consulta = consulta.where(InteracaoRegistro.data_interacao >= filtro.de)
    if filtro.ate:
        #: `ate` É O PRIMEIRO DIA do último mês da janela (a série é mensal), e a
        #: agenda tem dia: o limite é o primeiro dia do mês seguinte, aberto.
        consulta = consulta.where(
            InteracaoRegistro.data_interacao < _primeiro_dia_do_mes_seguinte(filtro.ate)
        )
    if filtro.busca:
        #: SÓ NO ASSUNTO, e não na pauta: a pauta não vai na resposta (ver
        #: `Incidente.incidente`), e procurar num texto que não se mostra
        #: devolveria linha sem a pessoa entender por que ela casou.
        consulta = consulta.where(Tema.nome.ilike(f"%{filtro.busca.strip()}%"))
    return consulta


def _temas_do_nivel(filtro: FiltroDeRisco) -> Select | None:
    """Os ids dos temas que casam com o recorte de N1 e N2, ou `None` sem ele.

    POR SUBCONSULTA DE `tema_id`, e não por `join` nas consultas base: a coluna
    `tema.macro_tema_id` é anulável, e um `join` interno faria o tema sem macro
    desaparecer da aba inteira — em silêncio, porque a tela não teria como saber
    que a linha existia. Medido hoje os 104 temas ativos têm macro, mas o
    cadastro aceita um sem, e é exatamente o caso que ninguém testaria.
    """
    if not (filtro.bloco or filtro.macro):
        return None
    consulta = (
        select(Tema.id)
        .join(MacroTema, MacroTema.id == Tema.macro_tema_id)
        .join(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
    )
    if filtro.bloco:
        consulta = consulta.where(BlocoTema.codigo == filtro.bloco)
    if filtro.macro:
        consulta = consulta.where(MacroTema.codigo == filtro.macro)
    return consulta


def _mencoes_cuja_pior_e(
    severidade: str, riscos: list[int] | None, filtro: FiltroDeRisco
) -> Select:
    """As menções cuja PIOR severidade, DENTRO DO RECORTE, é esta.

    DENTRO DO RECORTE, e não sobre todos os riscos do cadastro — e isto é
    correção de achado de revisão. A primeira versão media a pior severidade
    GLOBAL do fato, com o argumento de que "a severidade é propriedade do fato,
    não do recorte". O argumento é defensável, mas CRIAVA UMA SEGUNDA DEFINIÇÃO:
    a coluna da tabela, a pilha da barra, o índice e os três números do topo
    todos medem `max(peso)` DEPOIS do recorte por risco.

    O QUE ISSO CAUSAVA: com o risco X (alto) escolhido, um incidente que também
    toca um risco crítico aparecia no topo como `alto` (certo, porque dentro do
    recorte só o X conta) e o filtro `severidade=alto` NÃO o traía — ele caía em
    `severidade=critico`, e lá era exibido como `alto`. Clicar no "14" e receber
    outra quantidade de linhas.

    POR QUE O RECORTE GANHOU: o índice também é recorte-escopo. Medir a
    severidade globalmente faria um recorte de um risco alto pesar 3 pontos por
    incidente e mostrar um balde `crítico` num recorte que não tem risco crítico
    nenhum — que se lê como tela quebrada. Dentro do recorte, as cinco contas
    dão o mesmo número por construção, e a coluna responde "a pior severidade
    entre os riscos que você está olhando" — com a coluna "Riscos relacionados"
    ao lado mostrando os demais.
    """
    consulta = (
        select(Mencao.id)
        .join(Tema, Tema.id == Mencao.tema_id)
        .join(TemaRisco, TemaRisco.tema_id == Mencao.tema_id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        .where(
            Mencao.sentimento == SENTIMENTO_DO_INCIDENTE,
            Risco.ativo.is_(True),
            Tema.ativo.is_(True),
        )
        .group_by(Mencao.id)
        .having(func.max(_peso_em_sql()) == peso_da_severidade(severidade))
    )
    if riscos is not None:
        consulta = consulta.where(Risco.id.in_(riscos))
    #: O RECORTE DE TEMA TAMBÉM, pela mesma razão do de risco. Na menção ele não
    #: muda resultado — uma menção tem UM tema, então os riscos que ela toca são
    #: os mesmos com ou sem o recorte de N1/N2/N3 —, e está aqui para a regra ser
    #: uma só nos dois lugares: na agenda ele muda, e muda muito.
    return _so_os_temas_do_recorte(consulta, filtro, Mencao.tema_id)


def _so_os_temas_do_recorte(consulta: Select, filtro: FiltroDeRisco, coluna) -> Select:
    """As mesmas restrições de tema que a consulta principal aplica.

    EXTRAÍDO PARA UM LUGAR SÓ porque é a terceira cópia das mesmas três linhas, e
    a divergência entre elas foi exatamente o achado de revisão: a subconsulta da
    pior severidade não aplicava o recorte de tema, e a consulta principal sim.
    """
    if filtro.tema:
        consulta = consulta.where(Tema.nome == filtro.tema)
    do_nivel = _temas_do_nivel(filtro)
    if do_nivel is not None:
        consulta = consulta.where(coluna.in_(do_nivel))
    return consulta


def _agendas_cuja_pior_e(
    severidade: str, riscos: list[int] | None, filtro: FiltroDeRisco
) -> Select:
    """O mesmo, para as agendas de clima tenso.

    E AQUI O RECORTE DE TEMA É DECISIVO, ao contrário da menção: `interacao_tema`
    é N:N, e uma agenda pode tratar de vários assuntos. Sem o recorte, uma agenda
    com o tema A (alto, dentro do recorte) e o tema B (crítico, fora dele)
    aparecia no topo como `alto` e sumia ao clicar em `alto` — a pior severidade
    era medida sobre os dois temas, e o resto da tela sobre um. Achado de
    revisão.

    SEM O ESCOPO DO USUÁRIO AQUI de propósito: esta subconsulta só responde
    "qual é a pior severidade desta agenda", e a consulta que a usa já aplica a
    visibilidade e o escopo. Repeti-los aqui não mudaria o resultado e daria
    duas respostas para a mesma pergunta de permissão.
    """
    consulta = (
        select(InteracaoRegistro.id)
        .join(Clima, Clima.id == InteracaoRegistro.clima_id)
        .join(InteracaoTema, InteracaoTema.interacao_id == InteracaoRegistro.id)
        .join(Tema, Tema.id == InteracaoTema.tema_id)
        .join(TemaRisco, TemaRisco.tema_id == InteracaoTema.tema_id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        .where(
            Clima.codigo == CLIMA_DO_INCIDENTE,
            Risco.ativo.is_(True),
            Tema.ativo.is_(True),
        )
        .group_by(InteracaoRegistro.id)
        .having(func.max(_peso_em_sql()) == peso_da_severidade(severidade))
    )
    if riscos is not None:
        consulta = consulta.where(Risco.id.in_(riscos))
    return _so_os_temas_do_recorte(consulta, filtro, InteracaoTema.tema_id)


def _na_janela(chave: str, filtro: FiltroDeRisco) -> bool:
    """O mês `AAAA-MM` está dentro da janela escolhida na tela?

    MARCA, e não corta: ver `MesDeRisco.na_janela`. Sem janela, todo mês está
    dentro — o padrão da tela é a série inteira.
    """
    primeiro_dia = date(int(chave[:4]), int(chave[5:7]), 1)
    if filtro.de and primeiro_dia < filtro.de:
        return False
    return not (filtro.ate and primeiro_dia > filtro.ate)


def _peso_em_sql():
    """O peso da severidade como expressão SQL, GERADO do mapa do domínio.

    Em SQL porque a conta é por incidente: o peso de um incidente é o MAIOR
    entre os riscos que ele toca, e isso é um `max()` por incidente — não dá
    para somar em Python depois de agrupar por severidade sem contar o mesmo
    fato duas vezes (foi o defeito que o teste dos dois riscos pegou).

    GERADO, e não escrito à mão: duas cópias da mesma tabela de pesos é a
    receita conhecida de divergir em silêncio. Uma severidade nova no domínio
    aparece aqui no mesmo instante.
    """
    from sqlalchemy import case, literal

    return case(
        *[
            (Risco.severidade == severidade, literal(peso))
            for severidade, peso in PESO_DA_SEVERIDADE.items()
        ],
        #: SEVERIDADE DESCONHECIDA PESA ZERO, como no domínio: o incidente
        #: aparece na matriz e não move o índice. Ver `peso_da_severidade`.
        else_=literal(0),
    )


def serie_do_indice(
    sessao: Session, filtro: FiltroDeRisco, escopo: Escopo
) -> tuple[list[MesDeRisco], int, str | None]:
    """A série mensal do índice, com a referência que vale 100 e o mês dela.

    CADA INCIDENTE CONTA UMA VEZ, com a PIOR severidade que ele toca. Um tema
    pode tocar dois riscos: contar por severidade inflaria o índice de quem tem
    tema mais conectado, e pesar pelo menor esconderia a gravidade.

    DOIS GRUPOS DE CONSULTA, somados em Python: as menções e as agendas. Um
    `union` em SQL exigiria colunas iguais nas duas pontas (a menção tem veículo
    e tier; a agenda, pauta), e o volume aqui é de uma linha por mês.

    A JANELA FICA DE FORA do cálculo: ver `FiltroDeRisco.sem_a_janela`.
    """
    riscos = _riscos_do_filtro(sessao, filtro)
    inteiro = filtro.sem_a_janela()
    incidentes_do_mes: dict[str, int] = {}
    pesado_do_mes: dict[str, int] = {}
    fontes_do_mes: dict[str, set[str]] = {}
    severidade_do_mes: dict[str, dict[str, int]] = {}

    def somar(mes: date, peso: int, incidentes: int) -> None:
        """Soma um grupo (mês, pior severidade) nos três acumuladores.

        AGRUPADO POR PESO, e não só por mês: a barra do mês é empilhada por
        severidade e a dica mostra os três números. Do total não se deriva a
        divisão — 6 pontos são dois críticos, três altos ou seis moderados.
        """
        chave = mes.strftime("%Y-%m")
        incidentes_do_mes[chave] = incidentes_do_mes.get(chave, 0) + incidentes
        pesado_do_mes[chave] = pesado_do_mes.get(chave, 0) + peso * incidentes
        nome = _severidade_do_peso(peso, None)
        do_mes = severidade_do_mes.setdefault(chave, {})
        do_mes[nome] = do_mes.get(nome, 0) + incidentes

    #: AS MENÇÕES: o pior peso por menção, e depois a soma por mês.
    #:
    #: AS FONTES SAEM NA MESMA AGREGAÇÃO (`array_agg distinct`), e não numa
    #: segunda consulta: achado de revisão — a versão anterior repetia o mesmo
    #: join sobre 28 mil menções só para saber quais fontes alimentaram o mês.
    por_mencao = (
        mencoes_de_incidente(inteiro, riscos)
        .with_only_columns(
            Mencao.mes.label("mes"),
            Mencao.id.label("incidente"),
            func.max(_peso_em_sql()).label("pior"),
            func.min(ScoreFonte.codigo).label("fonte"),
        )
        .group_by(Mencao.mes, Mencao.id)
        .subquery()
    )
    for mes, peso, incidentes, fontes in sessao.execute(
        select(
            por_mencao.c.mes,
            por_mencao.c.pior,
            func.count(),
            func.array_agg(func.distinct(por_mencao.c.fonte)),
        ).group_by(por_mencao.c.mes, por_mencao.c.pior)
    ):
        somar(mes, peso, incidentes)
        fontes_do_mes.setdefault(mes.strftime("%Y-%m"), set()).update(fontes or ())

    #: AS AGENDAS, pela mesma regra.
    das_agendas = agendas_de_incidente(inteiro, riscos, escopo)
    if das_agendas is not None:
        por_agenda = (
            das_agendas.with_only_columns(
                func.date_trunc("month", InteracaoRegistro.data_interacao).label("mes"),
                InteracaoRegistro.id.label("incidente"),
                func.max(_peso_em_sql()).label("pior"),
            )
            .group_by(
                func.date_trunc("month", InteracaoRegistro.data_interacao),
                InteracaoRegistro.id,
            )
            .subquery()
        )
        for mes, peso, incidentes in sessao.execute(
            select(
                por_agenda.c.mes,
                por_agenda.c.pior,
                func.count(),
            ).group_by(por_agenda.c.mes, por_agenda.c.pior)
        ):
            somar(mes, peso, incidentes)
            fontes_do_mes.setdefault(mes.strftime("%Y-%m"), set()).add(FONTE_DO_CRM)

    meses = [
        MesDeRisco(
            mes=chave,
            incidentes=incidentes_do_mes[chave],
            pesado=pesado_do_mes.get(chave, 0),
            na_janela=_na_janela(chave, filtro),
            fontes=tuple(sorted(fontes_do_mes.get(chave, ()))),
            #: NA ORDEM DA GRAVIDADE, e só as que o mês teve: a pilha da barra
            #: sai igual em todos os meses, e a dica não lista zero.
            por_severidade=tuple(
                (nome, severidade_do_mes.get(chave, {})[nome])
                for nome in SEVERIDADES
                if severidade_do_mes.get(chave, {}).get(nome)
            ),
            #: E O PESO DE CADA UMA, que é com o que a barra se empilha.
            pesado_por_severidade=tuple(
                (nome, severidade_do_mes.get(chave, {})[nome] * peso_da_severidade(nome))
                for nome in SEVERIDADES
                if severidade_do_mes.get(chave, {}).get(nome)
            ),
        )
        for chave in sorted(incidentes_do_mes)
    ]
    return com_o_indice(meses)


@dataclass(frozen=True, slots=True)
class RiscoNaMatriz:
    """Uma célula da matriz: o risco, a severidade dele e o que o atingiu."""

    codigo: str
    nome: str
    severidade: str
    cluster: str
    cluster_nome: str
    #: Menções negativas, agendas de clima negativo, e a soma.
    mencoes: int
    agendas: int

    @property
    def incidentes(self) -> int:
        return self.mencoes + self.agendas


def matriz_de_risco(
    sessao: Session, filtro: FiltroDeRisco, escopo: Escopo
) -> list[RiscoNaMatriz]:
    """Os 32 riscos do cadastro, com os incidentes de cada um na janela.

    TODOS OS RISCOS, e não só os atingidos: "sem incidente" é a informação mais
    útil da matriz — risco que ninguém citou negativamente no período. Uma
    consulta que só trouxesse os atingidos deixaria a tela sem o silêncio, que é
    metade do que ela tem para dizer.

    O RECORTE DE CLUSTER E RISCO NÃO SE APLICA AQUI: a matriz é o que se clica
    para abrir o aprofundamento, e esconder os outros riscos tiraria o caminho
    de volta. TODO O RESTO SE APLICA — janela, fontes, lente, severidade, os três
    níveis do tema, as dimensões e a busca.

    POR `replace`, E NÃO RECONSTRUINDO A MÃO: a versão anterior listava quatro
    campos, e os cinco filtros que entraram depois (lente, severidade, bloco,
    macro, tema, dimensões) ficaram de fora em silêncio — a tela recortava e a
    matriz continuava contando a base inteira. Achado de revisão. Com `replace`,
    o campo novo entra sozinho e só sai quem for nomeado aqui.
    """
    sem_recorte_de_risco = replace(filtro, cluster=None, risco=None)

    das_mencoes = mencoes_de_incidente(sem_recorte_de_risco, None).subquery()
    por_risco: dict[int, dict[str, int]] = {}
    for risco_id, quantas in sessao.execute(
        select(das_mencoes.c.risco_id, func.count(func.distinct(das_mencoes.c.mencao_id)))
        .group_by(das_mencoes.c.risco_id)
    ):
        por_risco.setdefault(risco_id, {})["mencoes"] = quantas

    das_agendas = agendas_de_incidente(sem_recorte_de_risco, None, escopo)
    if das_agendas is not None:
        agendas = das_agendas.subquery()
        for risco_id, quantas in sessao.execute(
            select(agendas.c.risco_id, func.count(func.distinct(agendas.c.interacao_id)))
            .group_by(agendas.c.risco_id)
        ):
            por_risco.setdefault(risco_id, {})["agendas"] = quantas

    do_cadastro = sessao.execute(
        select(Risco, RiskCluster)
        .join(RiskCluster, RiskCluster.id == Risco.risk_cluster_id)
        .where(Risco.ativo.is_(True), RiskCluster.ativo.is_(True))
        .order_by(RiskCluster.ordem, Risco.ordem)
    )
    return [
        RiscoNaMatriz(
            codigo=risco.codigo,
            nome=risco.nome,
            severidade=risco.severidade,
            cluster=cluster.codigo,
            cluster_nome=cluster.nome,
            mencoes=por_risco.get(risco.id, {}).get("mencoes", 0),
            agendas=por_risco.get(risco.id, {}).get("agendas", 0),
        )
        for risco, cluster in do_cadastro
    ]


@dataclass(frozen=True, slots=True)
class Incidente:
    """Uma linha do "Relatório de incidentes"."""

    #: `mencao` ou `agenda` — a tela diz qual é qual, porque uma notícia e uma
    #: reunião não se leem do mesmo jeito.
    tipo: str
    id: str
    data: date
    #: Quem publicou (menção) ou com quem foi a conversa (agenda).
    quem: str | None
    #: O TÍTULO DA MATÉRIA, e nulo na agenda: o assunto e o clima já dizem o
    #: que a reunião foi, e a pauta é registro do CRM — decisão do dono do
    #: produto. Quem precisa do detalhe abre a agenda no CRM, onde ela mora.
    incidente: str | None
    link: str | None
    fonte: str
    #: A LENTE da fonte — a dimensão padronizada. A tabela escreve "Imprensa ·
    #: Clipei": a lente diz de que ângulo se está vendo, a fonte diz de quem
    #: veio o dado, e quem confere uma planilha precisa da segunda.
    lente: str
    #: OS NOMES DE CADASTRO DOS DOIS, porque é o que a tela escreve.
    #:
    #: O CÓDIGO É CHAVE, NÃO RÓTULO: a tabela mostrava "sociedade · bites" onde o
    #: resto do produto escreve "Sociedade digital" — e "sociedade" não é nem o
    #: nome da lente. Vêm do servidor e não de um mapa no navegador: a consulta
    #: já seleciona os dois, e um mapa no front seria uma segunda cópia do
    #: cadastro, que envelheceria na primeira lente renomeada.
    lente_nome: str
    fonte_nome: str
    tema: str
    #: O ALCANCE vai CRU, nas duas formas que as fontes mandam: o tier da
    #: imprensa e o engajamento das redes. Traduzir aqui obrigaria a inventar
    #: uma escala comum entre "muito relevante" e "1.243 interações".
    tier: str | None
    engajamento: float | None
    #: A PIOR severidade entre os riscos tocados — a mesma regra do índice.
    severidade: str
    #: EM QUANTOS MESES este assunto já teve incidente. É o que separa o fato
    #: isolado do problema crônico.
    recorrencia: int
    #: TODOS os riscos do tema, e não só o que filtrou a tela.
    riscos: tuple[tuple[str, str], ...]


def _recorrencia_por_tema(
    sessao: Session, filtro: FiltroDeRisco, escopo: Escopo, temas: Collection[str]
) -> dict[str, int]:
    """Em quantos meses cada assunto teve incidente, na série inteira.

    NA SÉRIE INTEIRA, e não na janela: "este assunto já voltou sete vezes" é um
    fato sobre o assunto, não sobre o período que a pessoa está olhando.

    CONTADO NO BANCO, e só dos assuntos QUE ESTÃO NA PÁGINA. Antes esta função
    trazia o par (tema, mês) de TODOS os incidentes da série — 28 mil menções em
    linhas Python — para montar um dicionário do qual a tabela usava cinquenta
    entradas, a cada pedido e a cada virada de página. Achado de revisão.
    """
    if not temas:
        return {}

    inteiro = filtro.sem_a_janela()
    das_mencoes = mencoes_de_incidente(inteiro, None).subquery()
    partes = [
        select(das_mencoes.c.tema.label("tema"), das_mencoes.c.mes.label("mes")).where(
            das_mencoes.c.tema.in_(temas)
        )
    ]

    das_agendas = agendas_de_incidente(inteiro, None, escopo)
    if das_agendas is not None:
        agendas = das_agendas.subquery()
        partes.append(
            select(agendas.c.tema.label("tema"), agendas.c.mes.label("mes")).where(
                agendas.c.tema.in_(temas)
            )
        )

    #: AS DUAS FAMÍLIAS NA MESMA CONTAGEM: o assunto que voltou uma vez na
    #: imprensa e uma vez numa reunião voltou em dois meses, não em um de cada.
    juntas = union_all(*partes).subquery()
    return dict(
        sessao.execute(
            select(juntas.c.tema, func.count(func.distinct(juntas.c.mes))).group_by(
                juntas.c.tema
            )
        ).all()
    )


def _riscos_por_tema(sessao: Session) -> dict[str, tuple[tuple[str, str], ...]]:
    """Os riscos de cada tema, pelo nome do tema.

    UMA CONSULTA para a tabela inteira, e não uma por linha: são 100 vínculos no
    cadastro, e a página tem 50 incidentes.
    """
    por_tema: dict[str, list[tuple[str, str]]] = {}
    for tema, codigo, nome in sessao.execute(
        select(Tema.nome, Risco.codigo, Risco.nome)
        .join(TemaRisco, TemaRisco.tema_id == Tema.id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        .where(Risco.ativo.is_(True), Tema.ativo.is_(True))
        .order_by(Risco.ordem)
    ):
        por_tema.setdefault(tema, []).append((codigo, nome))
    return {tema: tuple(riscos) for tema, riscos in por_tema.items()}


def incidentes_de_risco(
    sessao: Session,
    filtro: FiltroDeRisco,
    escopo: Escopo,
    *,
    pagina: int = 1,
    tamanho: int = 50,
) -> tuple[list[Incidente], int]:
    """A página do relatório, e o total de incidentes do recorte.

    DOIS GRUPOS unidos em Python e ordenados por data, porque as duas pontas não
    têm as mesmas colunas — menção tem veículo e tier; agenda tem pauta. O
    volume da página é 50 linhas; o `total` sai de duas contagens.

    A JANELA VALE AQUI, ao contrário da série: a tabela é o detalhe do período
    que a pessoa escolheu, e mostrar fora dele seria responder outra pergunta.
    """
    riscos = _riscos_do_filtro(sessao, filtro)
    riscos_do_tema = _riscos_por_tema(sessao)

    #: O PIOR PESO POR INCIDENTE, para a severidade da linha ser a mesma do
    #: índice. Em SQL, como na série.
    de_mencoes = (
        mencoes_de_incidente(filtro, riscos)
        .with_only_columns(
            Mencao.id.label("id"),
            Mencao.data.label("data"),
            Mencao.veiculo.label("quem"),
            Mencao.titulo_texto.label("incidente"),
            Mencao.link.label("link"),
            Mencao.tier.label("tier"),
            Mencao.engajamento.label("engajamento"),
            ScoreFonte.codigo.label("fonte"),
            ScoreFonte.nome.label("fonte_nome"),
            Lente.codigo.label("lente"),
            Lente.nome.label("lente_nome"),
            Tema.nome.label("tema"),
            func.max(_peso_em_sql()).label("pior"),
            func.min(Risco.severidade).label("qualquer_severidade"),
        )
        .group_by(
            Mencao.id,
            Mencao.data,
            Mencao.veiculo,
            Mencao.titulo_texto,
            Mencao.link,
            Mencao.tier,
            Mencao.engajamento,
            ScoreFonte.codigo,
            ScoreFonte.nome,
            Lente.codigo,
            Lente.nome,
            Tema.nome,
        )
        .subquery()
    )
    total = sessao.scalar(select(func.count()).select_from(de_mencoes)) or 0

    linhas: list[Incidente] = []
    for linha in sessao.execute(
        select(de_mencoes)
        .order_by(de_mencoes.c.data.desc(), de_mencoes.c.id.desc())
        .limit(tamanho * pagina)
    ):
        linhas.append(
            Incidente(
                tipo="mencao",
                id=str(linha.id),
                data=linha.data,
                quem=linha.quem,
                incidente=linha.incidente,
                link=linha.link,
                fonte=linha.fonte,
                fonte_nome=linha.fonte_nome,
                lente=linha.lente,
                lente_nome=linha.lente_nome,
                tema=linha.tema,
                tier=linha.tier,
                engajamento=linha.engajamento,
                severidade=_severidade_do_peso(linha.pior, linha.qualquer_severidade),
                #: PREENCHIDA DEPOIS DO CORTE DA PÁGINA, para a contagem no
                #: banco pedir só os assuntos que a tela vai mostrar.
                recorrencia=0,
                riscos=riscos_do_tema.get(linha.tema, ()),
            )
        )

    das_agendas = agendas_de_incidente(filtro, riscos, escopo)
    if das_agendas is not None:
        #: O NOME DA FONTE E DA LENTE DO CRM, do cadastro: ele é uma `score_fonte`
        #: como as outras (`interna = true`), e escrever "crm" na tela seria o
        #: mesmo erro de mostrar código onde o produto mostra nome.
        do_cadastro = lentes_das_fontes(sessao).get(FONTE_DO_CRM)
        nomes_do_crm = (
            (nomes_das_fontes(sessao).get(FONTE_DO_CRM) or FONTE_DO_CRM),
            (do_cadastro[1] if do_cadastro else LENTE_DO_CRM),
        )
        de_agendas = (
            das_agendas.with_only_columns(
                InteracaoRegistro.id.label("id"),
                InteracaoRegistro.data_interacao.label("data"),
                Tema.nome.label("tema"),
                func.max(_peso_em_sql()).label("pior"),
                func.min(Risco.severidade).label("qualquer_severidade"),
            )
            .group_by(
                InteracaoRegistro.id,
                InteracaoRegistro.data_interacao,
                Tema.nome,
            )
            .subquery()
        )
        total += sessao.scalar(select(func.count()).select_from(de_agendas)) or 0
        for linha in sessao.execute(
            select(de_agendas)
            .order_by(de_agendas.c.data.desc(), de_agendas.c.id.desc())
            .limit(tamanho * pagina)
        ):
            linhas.append(
                Incidente(
                    tipo="agenda",
                    id=str(linha.id),
                    data=linha.data,
                    #: A AGENDA NÃO TEM VEÍCULO: quem está do outro lado é a
                    #: instituição, e a tela do CRM é que a mostra. Aqui a
                    #: coluna fica vazia em vez de repetir a pauta.
                    quem=None,
                    #: SEM TEXTO LIVRE: o assunto e o clima descrevem a reunião.
                    incidente=None,
                    link=None,
                    fonte=FONTE_DO_CRM,
                    #: O NOME DO CRM E DA LENTE DELE vêm do cadastro, como os
                    #: das menções — ver `lentes_das_fontes`.
                    fonte_nome=nomes_do_crm[0],
                    lente=LENTE_DO_CRM,
                    lente_nome=nomes_do_crm[1],
                    tema=linha.tema,
                    tier=None,
                    engajamento=None,
                    severidade=_severidade_do_peso(linha.pior, linha.qualquer_severidade),
                    #: PREENCHIDA DEPOIS DO CORTE DA PÁGINA, para a contagem no
                #: banco pedir só os assuntos que a tela vai mostrar.
                recorrencia=0,
                    riscos=riscos_do_tema.get(linha.tema, ()),
                )
            )

    #: ORDENADAS JUNTAS e cortadas na página: as duas famílias se intercalam por
    #: data, senão a tabela mostraria todas as menções antes de qualquer agenda.
    #:
    #: COM DESEMPATE PELO ID, e não só por data: dezenas de incidentes caem no
    #: mesmo dia, e sem critério estável a ordem entre eles podia mudar de uma
    #: chamada para a outra — a mesma linha aparecendo na página 1 e na 2, ou em
    #: nenhuma. Achado de revisão.
    linhas.sort(key=lambda incidente: (incidente.data, incidente.tipo, incidente.id))
    linhas.reverse()
    comeco = (pagina - 1) * tamanho
    da_pagina = linhas[comeco : comeco + tamanho]

    #: A RECORRÊNCIA SÓ DOS ASSUNTOS DESTA PÁGINA, e por isso depois do corte:
    #: são no máximo cinquenta assuntos, contados no banco. Ver
    #: `_recorrencia_por_tema`.
    recorrencia = _recorrencia_por_tema(
        sessao, filtro, escopo, {incidente.tema for incidente in da_pagina}
    )
    return [
        replace(incidente, recorrencia=recorrencia.get(incidente.tema, 1))
        for incidente in da_pagina
    ], total


def _severidade_do_peso(peso: int | None, qualquer: str | None) -> str:
    """O nome da severidade que corresponde ao pior peso do incidente.

    O SQL devolve o PESO (para somar), e a tela mostra o NOME.

    PELA ORDEM DE GRAVIDADE, e não pela ordem do dicionário: se dois níveis
    tivessem o mesmo peso, varrer o mapa devolveria o primeiro inserido — uma
    linha só `alto` podia aparecer como `critico`. Percorrendo `SEVERIDADES`, do
    pior para o menos grave, o empate resolve a favor do mais grave, que é o
    único lado em que errar não esconde problema. Achado de revisão.

    E PESO ZERO NÃO É "MODERADO": é severidade que o cadastro tem e o mapa de
    pesos não conhece. Aí o nome vem do banco (`qualquer`), e só na falta dos
    dois é que sobra o menos grave — com o aviso de que isso é o fim da linha, e
    não uma informação.
    """
    if peso:
        for nome in SEVERIDADES:
            if PESO_DA_SEVERIDADE.get(nome) == peso:
                return nome
    return qualquer or SEVERIDADES[-1]


#: AS DIMENSÕES CANDIDATAS, e de qual coluna cada uma sai.
#:
#: As duas primeiras CRUZAM as fontes (toda fonte manda praça e unidade); as
#: outras são particularidades — tier e público-alvo existem na imprensa, cargo
#: e autor nas redes. Ver `dimensoes_do_recorte`.
DIMENSOES: tuple[tuple[str, str, str], ...] = (
    ("uf", "Praça", "uf"),
    ("unidade", "Concessionária", "unidade_texto"),
    ("tier", "Relevância do veículo", "tier"),
    ("publico_alvo", "Público-alvo", "publico_alvo"),
    ("cargo", "Cargo de quem fala", "cargo"),
    ("autor", "Autor", "autor"),
)

#: A CHAVE -> COLUNA, derivado de `DIMENSOES`: é o que garante que o filtro
#: recorta pela MESMA coluna que a opção ofereceu.
_COLUNA_DA_DIMENSAO: dict[str, str] = {chave: coluna for chave, _rotulo, coluna in DIMENSOES}

#: AS DIMENSÕES QUE NOMEIAM PESSOA, e que só quem vê o diretório pode listar.
#:
#: A Base das Lentes já esconde o autor da imprensa de quem não tem
#: `ve_diretorio` — é o cadastro de terceiros, o mesmo que a matriz de
#: jornalistas protege. Oferecer o autor como FILTRO publicaria a lista inteira
#: de nomes num seletor. Achado de revisão.
DIMENSOES_QUE_NOMEIAM_PESSOA: frozenset[str] = frozenset({"autor"})

#: ACIMA DE QUANTOS VALORES uma dimensão deixa de ser lista e passa a ser busca.
#:
#: 40 porque `uf` tem 27 e `unidade` 56: a praça cabe num seletor, a
#: concessionária já não — e `autor`, com 1.157 valores na Bites, seria um
#: seletor que ninguém percorre. A tela decide pelo `tipo` que vem na resposta.
VALORES_QUE_CABEM_NUM_SELETOR = 40


@dataclass(frozen=True, slots=True)
class DimensaoDoRecorte:
    """Uma dimensão que o recorte atual tem — com o que oferecer nela."""

    chave: str
    rotulo: str
    #: `lista` quando os valores cabem num seletor; `busca` quando são muitos;
    #: `vazia` quando a fonte TEM o campo e este recorte não trouxe valor —
    #: ver `dimensoes_do_recorte`.
    tipo: str
    valores: tuple[str, ...]
    quantos: int
    #: AS FONTES DO RECORTE QUE PREENCHEM ESTE CAMPO. É um fato sobre a fonte, e
    #: não sobre o recorte: é o que permite a tela escrever "só na imprensa" em
    #: vez de deixar o filtro mudo nas outras.
    fontes: tuple[str, ...]
    #: QUANTAS MENÇÕES DO RECORTE têm valor aqui. Zero com `fontes` preenchido
    #: significa "a fonte classifica este campo, e neste corte não há nenhum" —
    #: que é diferente de a fonte não ter o campo.
    preenchidas: int


def dimensoes_do_recorte(
    sessao: Session,
    filtro: FiltroDeRisco,
    escopo: Escopo,
    *,
    ve_o_diretorio: bool,
    fontes_do_recorte: Collection[str],
) -> list[DimensaoDoRecorte]:
    """As dimensões com valor no recorte, para a tela oferecer só o que existe.

    PADRONIZAÇÃO COM ESPAÇO PARA A PARTICULARIDADE, que é o pedido do dono do
    produto: praça e concessionária cruzam todas as fontes; tier e público-alvo
    só a imprensa tem; cargo e autor, só as redes. Oferecer tier a quem está
    olhando a Bites é prometer um filtro que volta vazio; esconder cargo de quem
    está na Bites é tirar o melhor filtro que ela tem.

    É O DADO QUE RESPONDE, e não uma lista fixa por fonte: dimensão aparece
    quando tem valor no recorte. Fonte nova que mande cargo entra sozinha.

    SÓ DAS MENÇÕES. As agendas do CRM têm as suas próprias dimensões (frente,
    esfera, unidade), e o filtro delas é a tela do CRM — esta aba as conta por
    risco, não as recorta por dentro. Quando isso virar pedido, entra aqui com a
    mesma régua.

    E A DIMENSÃO QUE A FONTE TEM NÃO DESAPARECE QUANDO O RECORTE A ESVAZIA: ela
    vem como `vazia`, com as fontes que a classificam e zero preenchidas. É a
    MESMA REGRA DA FILEIRA DE ABAS DAS LENTES, decidida pelo dono do produto em
    05/10/2026 — "uma fileira de filtros que muda a cada clique se lê como tela
    quebrada", e o filtro vazio diz algo acionável: a fonte não classificou
    aquilo neste corte. O que sai de vez é só a dimensão que NENHUMA fonte do
    recorte preenche, porque aí a ausência é da fonte, não do corte. Achado de
    revisão: a resposta tinha de deixar a tela distinguir as duas coisas.
    """
    candidatas = [
        (chave, rotulo, coluna)
        for chave, rotulo, coluna in DIMENSOES
        #: O AUTOR NOMEIA PESSOA, e listá-lo num seletor publicaria o cadastro de
        #: terceiros que `ve_diretorio` protege — a Base das Lentes já esconde o
        #: autor da imprensa de quem não o tem. Achado de revisão.
        if ve_o_diretorio or chave not in DIMENSOES_QUE_NOMEIAM_PESSOA
    ]
    if not candidatas:
        return []

    riscos = _riscos_do_filtro(sessao, filtro)
    das_mencoes = mencoes_de_incidente(filtro, riscos).subquery()

    #: (1) OS VALORES DO RECORTE, NUMA CONSULTA SÓ. Antes eram seis, uma por
    #: dimensão, cada uma agrupando a subconsulta inteira de incidentes. Aqui as
    #: seis colunas viram linhas (`chave`, `valor`) e o banco agrupa uma vez.
    #: Achado de revisão.
    empilhadas = union_all(
        *[
            select(
                literal(chave).label("chave"),
                cast(das_mencoes.c[coluna], Text).label("valor"),
                das_mencoes.c.mencao_id.label("mencao_id"),
            ).where(das_mencoes.c[coluna].is_not(None))
            for chave, _rotulo, coluna in candidatas
        ]
    ).subquery()
    valores_de: dict[str, list[str]] = {}
    preenchidas_em: dict[str, int] = {}
    for chave, valor, quantas in sessao.execute(
        select(
            empilhadas.c.chave,
            empilhadas.c.valor,
            #: DISTINTAS PELA MENÇÃO, porque a subconsulta tem uma linha por par
            #: (menção, risco) e o tema que toca dois riscos contaria duas vezes.
            func.count(func.distinct(empilhadas.c.mencao_id)),
        )
        .group_by(empilhadas.c.chave, empilhadas.c.valor)
        .order_by(empilhadas.c.chave, empilhadas.c.valor)
    ):
        valores_de.setdefault(chave, []).append(str(valor))
        preenchidas_em[chave] = preenchidas_em.get(chave, 0) + quantas

    #: (2) QUAIS FONTES CLASSIFICAM CADA CAMPO — a pergunta estrutural, e por
    #: isso medida na fonte inteira e não no recorte: `tier` vem em 25.448 das
    #: 25.457 menções da Clipei e em ZERO das 2.842 da Bites, e é isso que
    #: separa "a Bites não classifica relevância" de "não houve relevante aqui".
    de_cada_fonte = sessao.execute(
        select(
            ScoreFonte.codigo,
            *[
                func.count(getattr(Mencao, coluna)).label(chave)
                for chave, _rotulo, coluna in candidatas
            ],
        )
        .select_from(Mencao)
        .join(ScoreFonte, ScoreFonte.id == Mencao.fonte_id)
        .where(ScoreFonte.codigo.in_(list(fontes_do_recorte)))
        .group_by(ScoreFonte.codigo)
    ).all()
    classificam: dict[str, set[str]] = {}
    for linha in de_cada_fonte:
        for chave, _rotulo, _coluna in candidatas:
            if getattr(linha, chave):
                classificam.setdefault(chave, set()).add(linha.codigo)

    achadas: list[DimensaoDoRecorte] = []
    for chave, rotulo, _coluna in candidatas:
        fontes = classificam.get(chave, set())
        if not fontes:
            #: NENHUMA FONTE DO RECORTE CLASSIFICA ISTO: a ausência é da fonte, e
            #: o filtro não teria o que oferecer nem depois de trocar o período.
            continue
        valores = valores_de.get(chave, [])
        cabe = len(valores) <= VALORES_QUE_CABEM_NUM_SELETOR
        achadas.append(
            DimensaoDoRecorte(
                chave=chave,
                rotulo=rotulo,
                tipo="vazia" if not valores else ("lista" if cabe else "busca"),
                #: OS VALORES SÓ QUANDO CABEM: mandar 1.157 autores para a tela
                #: desenhar um seletor que ninguém percorre é peso sem uso.
                valores=tuple(valores) if cabe else (),
                quantos=len(valores),
                fontes=tuple(sorted(fontes)),
                preenchidas=preenchidas_em.get(chave, 0),
            )
        )
    return achadas


#: O NOME DO NÓ DE QUEM NÃO FOI CLASSIFICADO na taxonomia de três níveis.
#:
#: Ele existe porque a soma dos nós tem de fechar com o total da tabela: tema
#: ativo que toca risco e não tem macro tema continua produzindo incidente, e
#: deixá-lo fora da árvore faria a conta não bater sem dizer onde. O nó vem com
#: código vazio, e a tela não o oferece como filtro.
SEM_CLASSIFICACAO = "Sem classificação na taxonomia"


@dataclass(frozen=True, slots=True)
class NivelDoTema:
    """Um nó da árvore de temas: código, nome, o que vem abaixo e o que tem."""

    codigo: str
    nome: str
    dentro: tuple[NivelDoTema, ...] = ()
    #: QUANTOS INCIDENTES ESTE NÓ TEM NO RECORTE ATUAL.
    #:
    #: SEM ISSO O APROFUNDAMENTO É CEGO: escolher N1 seria chutar. A contagem
    #: mostra onde está a massa, que é o que faz descer um nível valer a pena —
    #: é o mesmo papel das barras do "dentro deste recorte" das Lentes.
    #:
    #: ZERO É INFORMAÇÃO e o nó fica: é a régua da matriz dos 32 riscos, que
    #: mostra os sem incidente. Um seletor que muda de tamanho a cada clique não
    #: deixa procurar.
    incidentes: int = 0


def _incidentes_por_tema(
    sessao: Session, filtro: FiltroDeRisco, escopo: Escopo
) -> dict[str, int]:
    """Quantos incidentes cada tema (N3) tem no recorte, pelo nome do tema.

    POR INCIDENTE, e não por par (incidente, risco): o tema que toca dois riscos
    contaria duas vezes, e a soma dos nós não fecharia com o total da tabela.
    """
    riscos = _riscos_do_filtro(sessao, filtro)
    contagem: dict[str, int] = {}

    das_mencoes = (
        mencoes_de_incidente(filtro, riscos)
        .with_only_columns(Mencao.id.label("incidente"), Tema.nome.label("tema"))
        .group_by(Mencao.id, Tema.nome)
        .subquery()
    )
    for tema, quantos in sessao.execute(
        select(das_mencoes.c.tema, func.count()).group_by(das_mencoes.c.tema)
    ):
        contagem[tema] = contagem.get(tema, 0) + quantos

    das_agendas = agendas_de_incidente(filtro, riscos, escopo)
    if das_agendas is not None:
        por_agenda = (
            das_agendas.with_only_columns(
                InteracaoRegistro.id.label("incidente"), Tema.nome.label("tema")
            )
            .group_by(InteracaoRegistro.id, Tema.nome)
            .subquery()
        )
        for tema, quantos in sessao.execute(
            select(por_agenda.c.tema, func.count()).group_by(por_agenda.c.tema)
        ):
            contagem[tema] = contagem.get(tema, 0) + quantos
    return contagem


def arvore_dos_temas(
    sessao: Session, filtro: FiltroDeRisco, escopo: Escopo
) -> list[NivelDoTema]:
    """A taxonomia em três níveis, SÓ dos temas que tocam algum risco.

    SÓ OS QUE TOCAM RISCO porque esta aba é sobre risco: oferecer um tema que
    não chega a risco nenhum é oferecer um filtro que volta vazio sempre, e não
    por causa do recorte.

    A ÁRVORE INTEIRA DO CADASTRO, e não só o que tem incidente no recorte: é a
    mesma régua da matriz dos 32 riscos, que mostra os sem incidente — "não
    houve" é informação, e um seletor que muda de tamanho a cada clique não
    deixa procurar. Ver `dimensoes_do_recorte` para o outro lado da regra, que
    vale para as dimensões que só algumas fontes preenchem.
    """
    linhas = sessao.execute(
        select(
            BlocoTema.codigo,
            BlocoTema.nome,
            MacroTema.codigo,
            MacroTema.nome,
            Tema.nome,
        )
        .select_from(Tema)
        .join(TemaRisco, TemaRisco.tema_id == Tema.id)
        .join(Risco, Risco.id == TemaRisco.risco_id)
        #: `outerjoin` E NÃO `join`: `tema.macro_tema_id` é anulável, e o join
        #: interno fazia o tema sem macro DESAPARECER da árvore — ele continuava
        #: na tabela e nos incidentes, e a soma dos nós deixava de fechar com o
        #: total. Achado de revisão. Hoje os 104 temas ativos têm macro, mas o
        #: cadastro aceita um sem, e é o caso que ninguém olharia.
        .outerjoin(MacroTema, MacroTema.id == Tema.macro_tema_id)
        .outerjoin(BlocoTema, BlocoTema.id == MacroTema.bloco_tema_id)
        .where(
            Tema.ativo.is_(True),
            Risco.ativo.is_(True),
            or_(BlocoTema.id.is_(None), BlocoTema.ativo.is_(True)),
            or_(MacroTema.id.is_(None), MacroTema.ativo.is_(True)),
        )
        #: SEM `distinct` NO SQL: a ordem é por `ordem` do bloco e do macro, que
        #: não estão na projeção, e o Postgres recusa as duas coisas juntas. O
        #: tema que toca dois riscos vem duas vezes e o laço abaixo o
        #: desduplica — a verificação que ele já precisava ter.
        .order_by(BlocoTema.ordem, MacroTema.ordem, Tema.nome)
    ).all()

    #: A CONTAGEM DO RECORTE, SEM O NÍVEL JÁ ESCOLHIDO: com N1 escolhido, os
    #: outros N1 apareceriam com zero e a pessoa concluiria que não há nada lá —
    #: quando o que há é um filtro ligado. A árvore responde "onde está a massa",
    #: e essa pergunta é sobre o recorte MENOS o próprio nível do tema.
    sem_o_tema = replace(filtro, bloco=None, macro=None, tema=None)
    por_tema = _incidentes_por_tema(sessao, sem_o_tema, escopo)

    blocos: dict[str, tuple[str, dict[str, tuple[str, list[str]]]]] = {}
    for bloco, bloco_nome, macro, macro_nome, tema in linhas:
        #: O NÃO CLASSIFICADO VIRA UM NÓ, com código vazio: ele aparece com a
        #: contagem (é o que diz a alguém que falta classificar aquele tema) e a
        #: tela não o oferece como filtro, porque não há o que filtrar. O que
        #: não pode é ele sumir — aí o total da tabela não fecha com a árvore.
        chave_do_bloco = bloco or ""
        chave_do_macro = macro or ""
        _nome, macros = blocos.setdefault(
            chave_do_bloco, (bloco_nome or SEM_CLASSIFICACAO, {})
        )
        _macro_nome, temas = macros.setdefault(
            chave_do_macro, (macro_nome or SEM_CLASSIFICACAO, [])
        )
        if tema not in temas:
            temas.append(tema)

    arvore: list[NivelDoTema] = []
    for bloco, (bloco_nome, macros) in blocos.items():
        dentro: list[NivelDoTema] = []
        for macro, (macro_nome, temas) in macros.items():
            folhas = tuple(
                NivelDoTema(codigo=tema, nome=tema, incidentes=por_tema.get(tema, 0))
                for tema in temas
            )
            dentro.append(
                NivelDoTema(
                    codigo=macro,
                    nome=macro_nome,
                    dentro=folhas,
                    #: O PAI SOMA OS FILHOS, e não uma contagem própria: dois
                    #: números para o mesmo conjunto divergiriam na primeira
                    #: diferença de arredondamento ou de `join`.
                    incidentes=sum(folha.incidentes for folha in folhas),
                )
            )
        arvore.append(
            NivelDoTema(
                codigo=bloco,
                nome=bloco_nome,
                dentro=tuple(dentro),
                incidentes=sum(um.incidentes for um in dentro),
            )
        )
    return arvore


def nomes_das_fontes(sessao: Session) -> dict[str, str]:
    """O nome de cadastro de cada fonte, pelo código.

    A TELA ESCREVE NOME, e o código é chave. Vale para o CRM como para as
    outras: ele é uma `score_fonte` com `interna = true`, e "crm" na coluna da
    tabela seria o mesmo erro de mostrar `sociedade` onde o cadastro diz
    "Sociedade digital".
    """
    return dict(sessao.execute(select(ScoreFonte.codigo, ScoreFonte.nome)).all())


def lentes_das_fontes(sessao: Session) -> dict[str, tuple[str, str]]:
    """De que lente é cada fonte: `{"clipei": ("imprensa", "Imprensa")}`.

    UM MAPA EM VEZ DE UM `join` na rota: a rota já sabe quais FONTES trouxeram
    incidente (sai da série), e a lente de uma fonte é cadastro que não muda com
    o recorte. Medido no cadastro: 6 fontes, 5 lentes — a Clipei alimenta
    imprensa e mercado, a Bites e a Approach dividem a sociedade digital.
    """
    return {
        codigo: (lente, nome)
        for codigo, lente, nome in sessao.execute(
            select(ScoreFonte.codigo, Lente.codigo, Lente.nome)
            .join(Lente, Lente.id == ScoreFonte.lente_id)
            .order_by(Lente.ordem)
        )
    }


def total_por_severidade(
    sessao: Session, filtro: FiltroDeRisco, escopo: Escopo
) -> dict[str, int]:
    """Quantos incidentes por severidade na janela — o "Total de incidentes".

    POR INCIDENTE, E PELA PIOR SEVERIDADE, como o índice e como a linha da
    tabela. Somar a matriz por risco daria outro número: o incidente de um tema
    que toca um crítico e um alto entraria nos dois baldes, e os três números do
    topo somariam mais que o total de incidentes. Achado de revisão.
    """
    riscos = _riscos_do_filtro(sessao, filtro)
    contagem = dict.fromkeys(SEVERIDADES, 0)

    def somar(linhas) -> None:
        for peso, quantos in linhas:
            nome = _severidade_do_peso(peso, None)
            contagem[nome] = contagem.get(nome, 0) + quantos

    por_mencao = (
        mencoes_de_incidente(filtro, riscos)
        .with_only_columns(
            Mencao.id.label("incidente"), func.max(_peso_em_sql()).label("pior")
        )
        .group_by(Mencao.id)
        .subquery()
    )
    somar(
        sessao.execute(
            select(por_mencao.c.pior, func.count()).group_by(por_mencao.c.pior)
        )
    )

    das_agendas = agendas_de_incidente(filtro, riscos, escopo)
    if das_agendas is not None:
        por_agenda = (
            das_agendas.with_only_columns(
                InteracaoRegistro.id.label("incidente"),
                func.max(_peso_em_sql()).label("pior"),
            )
            .group_by(InteracaoRegistro.id)
            .subquery()
        )
        somar(
            sessao.execute(
                select(por_agenda.c.pior, func.count()).group_by(por_agenda.c.pior)
            )
        )
    return contagem
