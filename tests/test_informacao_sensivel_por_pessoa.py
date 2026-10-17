"""A agenda inteira pode ser sensível, e aí só quem tem a camada a alcança.

DUAS COISAS DIFERENTES, E ESTE ARQUIVO GUARDA AS DUAS:

    usuario.acesso_sensivel   a PERMISSÃO (migration 0087). Combina com
                              `papel.ve_campos_sensiveis` por E lógico — o
                              papel é o teto do cargo, a coluna é se ESTA
                              pessoa recebeu. A conta mora num lugar só,
                              `UsuarioAtual.ve_campos_sensiveis`.

    interacao.sensivel        a CLASSIFICAÇÃO (migration 0089). Quem registra
                              marca, uma agenda por vez.

O encontro das duas é um filtro de LINHA: agenda marcada não existe para quem
não tem a permissão — nem na Base, nem na ficha, nem na busca, nem no KPI.

O QUE ESTE ARQUIVO JÁ FOI, e por que a história fica escrita

Na primeira versão (0087) a informação sensível era uma lista FIXA de campos:
`relato`, `pendencias`, `posicionamento`, `encaminhamentos`, `observacoes`. O
registro aparecia para todos e esses campos vinham nulos. Havia aqui um teste
provando que a busca livre não varria campo escondido — o oráculo: sem receber
o texto, a pessoa descobriria o conteúdo por tentativa e erro, uma palavra por
vez, e ainda saberia quais registros casam. Foi achado de revisão real, e a
correção valia naquele desenho.

A lista fixa não respondia à pergunta de quem usa. "Esta reunião é delicada" é
propriedade do ENCONTRO, não do campo: há agenda cujo relato é banal e agenda
em que a simples existência do encontro é a informação sensível — e a lista de
campos não tinha como esconder a segunda. Em 0089 a restrição mudou de lugar, e
com ela o oráculo deixou de existir: não há campo escondido para deduzir,
porque a linha inteira sai.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.dominio.frentes import Frente
from app.dominio.identidade import Escopo, Papel, UsuarioAtual
from app.dominio.interacao import Interacao
from app.dominio.recorte import Recorte
from app.esquemas.interacoes import InteracaoSaida

#: Um papel que ALCANÇA o sensível — o teto aberto. É o caso dos nove semeados.
COM_TETO = Papel(
    codigo="crm_leitura",
    nome="CRM · leitura",
    ve_campos_sensiveis=True,
    ve_diretorio=True,
    pode_exportar=True,
    acessa_crm=True,
)

#: Um papel que NÃO alcança — o teto fechado. Nenhum papel semeado é assim, e o
#: caso existe porque a bandeira é editável no banco e um papel novo é um
#: `insert`.
SEM_TETO = Papel(
    codigo="crm_leitura_restrito",
    nome="CRM · leitura sem sensível",
    ve_campos_sensiveis=False,
    acessa_crm=True,
)


def pessoa(papel: Papel | None, **ajustes) -> UsuarioAtual:
    return UsuarioAtual(
        id=uuid4(),
        nome="Fulano",
        email="f@aegea.com.br",
        papel=papel,
        escopo=Escopo.total(),
        **ajustes,
    )


# -- a permissão: a conjunção das duas camadas (0087) --------------------------


def test_teto_aberto_e_camada_concedida_alcanca():
    assert pessoa(COM_TETO, acesso_sensivel=True).ve_campos_sensiveis


def test_teto_aberto_e_camada_negada_nao_alcanca():
    """O caso que a coluna de 0087 tornou representável.

    Antes dela, com papel de CRM a pessoa alcançava o sensível, e a única saída
    era criar um papel por combinação.
    """
    assert not pessoa(COM_TETO, acesso_sensivel=False).ve_campos_sensiveis


def test_camada_concedida_nao_vence_teto_fechado():
    """Conjunção, e NÃO substituição.

    Se a coluna sobrepujasse o papel, marcar a pessoa daria a ela mais do que o
    cargo permite — e quem marcasse não teria como saber que estava fazendo
    isso.
    """
    assert not pessoa(SEM_TETO, acesso_sensivel=True).ve_campos_sensiveis


def test_sem_papel_nao_alcanca_por_mais_que_esteja_marcado():
    """O padrão `True` da coluna não concede nada sozinho.

    É o que torna `default true` em 0087 seguro: quem nasce no provisionamento
    nasce sem papel, e sem papel a conjunção já é falsa.
    """
    assert not pessoa(None, acesso_sensivel=True).ve_campos_sensiveis


def test_o_padrao_de_quem_tem_papel_e_alcancar():
    assert pessoa(COM_TETO).ve_campos_sensiveis


# -- a classificação: o filtro de LINHA (0089) ---------------------------------


def sql_das_condicoes(
    *, alcanca: bool, busca: str | None = None, incluir_arquivadas: bool = False
) -> str:
    """O `where` que `condicoes()` monta, como texto, para inspecionar."""
    from app.banco.filtros_sql import condicoes

    partes = condicoes(
        Recorte(busca=busca) if busca else Recorte(),
        escopo=Escopo.total(),
        alcanca_sensivel=alcanca,
        incluir_arquivadas=incluir_arquivadas,
    )
    return " ".join(
        str(p.compile(compile_kwargs={"literal_binds": True})) for p in partes
    )


def test_quem_nao_alcanca_leva_o_filtro_de_linha():
    """A condição que tira a agenda do conjunto.

    UMA condição, e ela basta para tudo: `condicoes()` é o único tradutor de
    filtro do sistema — listagem, ficha, busca, materiais, exportações e TODAS
    as agregações de `consultas_metricas` passam por aqui.
    """
    sem = sql_das_condicoes(alcanca=False)
    assert "interacao.sensivel" in sem


def test_quem_alcanca_nao_leva_filtro_nenhum():
    """Sem a condição, e não com ela invertida.

    `sensivel = true` para quem alcança seria o erro oposto: a pessoa veria SÓ
    as agendas restritas, e as comuns desapareceriam — e a tela pareceria
    funcionar, porque ainda viria conteúdo.
    """
    assert "interacao.sensivel" not in sql_das_condicoes(alcanca=True)


def test_a_busca_varre_os_mesmos_campos_para_todo_mundo():
    """O oráculo deixou de existir, e este teste é o que registra isso.

    Enquanto a informação sensível era uma lista de campos, `relato` e
    `encaminhamentos` tinham de sair da busca de quem não os recebia. Agora
    quem não alcança a agenda não tem a LINHA no conjunto — e condicionar
    colunas só esconderia da pessoa certa o texto que ela lê na tela ao lado.
    """
    com = sql_das_condicoes(alcanca=True, busca="reajuste")
    sem = sql_das_condicoes(alcanca=False, busca="reajuste")

    for campo in ("relato", "encaminhamentos", "pauta", "expectativa"):
        assert f"interacao.{campo}" in com, f"`{campo}` saiu da busca de quem alcança"
        assert f"interacao.{campo}" in sem, f"`{campo}` saiu da busca sem precisar"

    #: E a diferença entre os dois continua sendo UMA: o filtro de linha.
    assert "interacao.sensivel" in sem
    assert "interacao.sensivel" not in com


def test_o_filtro_vale_tambem_quando_se_pede_o_arquivo():
    """Agenda arquivada E sensível continua sensível.

    `incluir_arquivadas` existe para a tela que mostra o arquivo. Se o filtro
    do sensível morasse dentro daquele `if`, pedir o arquivo abriria o acervo
    restrito — e seria o jeito mais fácil de contornar a marca.
    """
    sql = sql_das_condicoes(alcanca=False, incluir_arquivadas=True)
    assert "interacao.sensivel" in sql
    #: E o de arquivada saiu, que é o que `incluir_arquivadas` pede.
    assert "arquivado_em" not in sql


# -- o que a serialização faz, e o que já não faz ------------------------------


def nova(**ajustes) -> Interacao:
    padroes = dict(
        #: `id` explícito: o agregado só ganha o dele ao ser persistido, e o
        #: esquema de saída exige um.
        id=uuid4(),
        frente=Frente.IMPRENSA,
        data_interacao=date(2026, 5, 7),
        instituicao_id=uuid4(),
        uf="SP",
        status="confirmada",
        pauta="Reajuste tarifário em concessões",
    )
    return Interacao(**{**padroes, **ajustes})


def test_a_agenda_que_chega_chega_inteira():
    """A serialização já não mascara campo nenhum.

    Mascarar aqui, além de redundante, esconderia da pessoa certa o que ela tem
    direito de ler: a agenda que chegou até a serialização é uma que ela
    alcança.
    """
    interacao = nova(
        relato="Disse que não haveria reajuste antes de dezembro.",
        pendencias="Confirmar com o jurídico antes de responder.",
        posicionamento="Não comentar publicamente até a decisão da agência.",
        encaminhamentos="Enviar nota à diretoria até sexta.",
        observacoes="Pediu sigilo sobre a conversa.",
    )

    saida = InteracaoSaida.de_dominio(interacao)
    for campo in (
        "relato",
        "pendencias",
        "posicionamento",
        "encaminhamentos",
        "observacoes",
    ):
        assert getattr(saida, campo) is not None, f"`{campo}` foi mascarado"


def test_a_lista_de_campos_sensiveis_nao_existe_mais():
    """A ausência é a mudança, e por isso é asserção.

    Enquanto `CAMPOS_SENSIVEIS` existir, alguém vai mascarar por ela de novo —
    e aí haverá DOIS mecanismos para a mesma coisa, discordando nas bordas.
    """
    assert not hasattr(InteracaoSaida, "CAMPOS_SENSIVEIS")
    assert not hasattr(InteracaoSaida, "CAMPOS_SENSIVEIS_DA_CONSULTA")


def test_a_classificacao_sai_no_payload():
    """Quem alcança precisa VER que a agenda está marcada.

    Sem isto, quem classificou não tem como conferir que a marca pegou, e a
    tela não tem como distinguir a linha restrita na lista.
    """
    assert InteracaoSaida.de_dominio(nova()).sensivel is False
    assert InteracaoSaida.de_dominio(nova(sensivel=True)).sensivel is True


def test_a_agenda_nasce_comum():
    """Classificar é um ato; esquecer não tranca nada.

    O contrário faria quem omitisse o campo — um `curl`, um script, uma
    planilha com a coluna em branco — trancar o registro sem decidir isso.
    """
    assert nova().sensivel is False


# -- as guardas de fonte -------------------------------------------------------

#: Onde mora o código da aplicação.
APP = Path(__file__).resolve().parent.parent / "app"

#: O ÚNICO lugar onde ler a bandeira do papel direto é correto: é onde a
#: conjunção é feita. Qualquer outro é um consumidor decidindo acesso pelo teto
#: em vez do efetivo.
LEITURAS_LEGITIMAS = {"dominio/identidade.py"}


def sem_prosa(linha: str) -> str:
    """A linha sem o que é texto para gente ler.

    SEM ISTO A GUARDA ACUSA A SI MESMA: este projeto documenta decisão em
    comentário, e a decisão aqui é justamente "combina com
    `papel.ve_campos_sensiveis`" — a frase aparece em arquivos que não decidem
    acesso nenhum.
    """
    return re.sub(r"`[^`]*`", "", linha).split("#", 1)[0]


def test_ninguem_decide_acesso_pela_bandeira_do_papel():
    """A conjunção só vale se TODO mundo passar por ela.

    Um consumidor que leia `usuario.papel.ve_campos_sensiveis` recebe o TETO, e
    não o efetivo: entregaria a agenda restrita a quem teve a camada negada. E
    entregaria só naquela rota, o que é o pior formato de defeito de
    autorização — as outras continuam certas, então ninguém procura.

    O QUE ELA NÃO PEGA: casa o receptor chamado `papel`.
    `teto = usuario.papel; teto.ve_campos_sensiveis` passaria. É heurística, não
    análise — pega a forma que alguém escreveria sem pensar, que é a que chega
    sem revisão.
    """
    culpados: list[str] = []

    for caminho in sorted(APP.rglob("*.py")):
        relativo = caminho.relative_to(APP).as_posix()
        if relativo in LEITURAS_LEGITIMAS:
            continue

        fonte = caminho.read_text(encoding="utf-8")
        for numero, linha in enumerate(fonte.splitlines(), start=1):
            if re.search(r"papel\s*\.\s*ve_campos_sensiveis", sem_prosa(linha)):
                culpados.append(f"{relativo}:{numero}: {linha.strip()}")

    assert culpados == [], (
        "Estes lugares leem o teto do papel em vez do acesso efetivo. "
        "Use `usuario.ve_campos_sensiveis`:\n  " + "\n  ".join(culpados)
    )


def test_nenhuma_leitura_de_interacao_fixa_o_alcance():
    """`alcanca_sensivel` tem de vir de quem pede, nunca escrito no código.

    Um `alcanca_sensivel=True` FIXO é o caminho pelo qual a agenda restrita
    volta a aparecer para todo mundo — e passa desapercebido, porque o nome do
    argumento parece inofensivo e a linha parece configuração.

    Aconteceu de verdade na direção oposta: a leitura por id tinha
    `False` fixo, herdado de quando o argumento só decidia colunas da busca.
    Em 0089 aquele `False` trancaria a ficha da agenda sensível para TODO
    mundo, inclusive para quem a marcou.

    `filtros_sql` é isento: é ele quem DEFINE o parâmetro.
    """
    culpados: list[str] = []
    for caminho in sorted(APP.rglob("*.py")):
        if caminho.relative_to(APP).as_posix() == "banco/filtros_sql.py":
            continue
        fonte = caminho.read_text(encoding="utf-8")
        for numero, linha in enumerate(fonte.splitlines(), start=1):
            if re.search(r"alcanca_sensivel\s*=\s*(True|False)\b", sem_prosa(linha)):
                culpados.append(
                    f"{caminho.relative_to(APP).as_posix()}:{numero}: {linha.strip()}"
                )

    assert culpados == [], (
        "Valor FIXO de `alcanca_sensivel` no código da aplicação. Ele tem de "
        "vir de `usuario.ve_campos_sensiveis`:\n  " + "\n  ".join(culpados)
    )


#: Os módulos que leem `InteracaoRegistro` e NÃO precisam do filtro, com o
#: motivo de cada um. Qualquer outro tem de aplicar `condicoes()` ou citar
#: `sensivel` — ver `test_todo_modulo_que_le_interacao_decide_sobre_o_sensivel`.
LEITURAS_SEM_FILTRO = {
    #: É quem DEFINE o filtro.
    "banco/filtros_sql.py",
    #: Só o mapeamento ORM.
    "banco/tabelas_interacoes.py",
    #: Semeadores: populam o banco em desenvolvimento, não servem requisição.
    #:
    #: O CAMINHO MUDOU EM 17/10/2026 — eles saíram de `banco/` para `comandos/`,
    #: e esta lista é por caminho: os três caíram fora dela na mudança e o teste
    #: falhou, que é o comportamento certo. Uma lista de exceção de SEGURANÇA
    #: que seguisse valendo depois de o arquivo mudar de lugar seria pior do que
    #: não existir.
    "comandos/semear_desenvolvimento.py",
    "comandos/semear_enredos.py",
    "comandos/semear_taxonomia_de_temas.py",
    #: Rotinas de MANUTENÇÃO, chamadas por comando e não por rota. Preenchem
    #: campo de cadastro a partir do acervo (`Instituicao.tier`, categoria de
    #: público sugerida). Excluir a agenda sensível aqui faria um campo
    #: cadastral depender de quem pode vê-la, o que não tem sentido — o cadastro
    #: não é por pessoa. Achado de revisão, deixado de fora com o motivo.
    "banco/derivados.py",
    "banco/sugerir_categoria_de_publico.py",
    #: FUSÃO DE CADASTROS DUPLICADOS: um `update` que reaponta as agendas do
    #: perfil absorvido para o sobrevivente. Tem de tocar TODAS as linhas —
    #: filtrar deixaria as restritas apontando para um cadastro que deixou de
    #: existir, e isso não é privacidade, é corrupção de dado.
    "casos_de_uso/atores_duplicados.py",
    #: CONTAGEM QUE PROTEGE INTEGRIDADE, não contagem que informa.
    #:
    #: `mudar_a_casa` conta quantas agendas serão reapontadas ao mover um
    #: contato de instituição, e a conferência de exclusão de stakeholder conta
    #: quantas impedem o `delete`. As duas existem para a OPERAÇÃO acertar: uma
    #: conta filtrada diria "zero, pode apagar" com uma agenda restrita ainda
    #: apontando para a linha, e o `delete` falharia na chave estrangeira — ou
    #: pior, a operação mexeria em menos registros do que diz.
    #:
    #: "Quantas coisas apontam para isto" é fato estrutural; "quais reuniões
    #: aconteceram" é a informação protegida. Só a segunda a marca esconde.
    #: Hoje as duas são alcançadas só por `administra_dicionarios`, que implica
    #: a camada. Achado de revisão, mantido com o motivo.
    "casos_de_uso/mudar_a_casa.py",
}

#: O que conta como "este módulo decidiu sobre o sensível".
#:
#: `so_interacoes_visiveis` entra porque é o auxiliar COMPARTILHADO do Score: é
#: lá que o filtro mora, e quem o chama está coberto sem citar a coluna. Sem
#: este marcador, `repositorio_lentes` apareceria como culpado por estar certo.
MARCAS_DE_DECISAO = ("condicoes(", "sensivel", "so_interacoes_visiveis")


def test_todo_modulo_que_le_interacao_decide_sobre_o_sensivel():
    """A GUARDA QUE A PRIMEIRA VERSÃO DESTE ARQUIVO NÃO TINHA.

    A guarda anterior procurava `alcanca_sensivel=True/False` escrito no código
    — e só isso. Não pegava o caso que de fato vazou: a leitura que simplesmente
    OMITE o filtro, montando o próprio `where`. Foi assim que a deduplicação da
    importação, o contador de alegações e as conferências de exclusão de
    stakeholder continuaram contando agendas restritas, e foi um revisor que
    apontou — a guarda me deu confiança falsa.

    Agora a pergunta é outra: todo módulo que toca `InteracaoRegistro` ou
    aplica `condicoes()`, ou cita `sensivel` explicitamente. Citar não prova que
    está certo; prova que alguém DECIDIU. A isenção é nominal, com motivo
    escrito, e é isso que força a decisão a passar por aqui.

    `banco/__init__.py` já diz que `condicoes()` é invariante do sistema: "uma
    consulta que monte `where` por conta própria quebra a garantia de que o KPI
    conta o que a tabela lista — e quebra em silêncio". Esta é a versão
    executável dessa frase.

    O QUE ELA AINDA NÃO PEGA, e é melhor estar escrito do que descoberto:

    1. É POR MÓDULO, não por consulta. Um arquivo que aplique `condicoes()`
       numa função e conte à mão noutra passa. Foi exatamente o caso de
       `api/stakeholders.py`, e um revisor o achou — não esta guarda.
    2. Não vê quem conta por uma tabela FILHA sem tocar `interacao`. Foi o caso
       de `_consultas_por_alegacao`, que contava `interacao_alegacao` direto: a
       contagem revelava que uma consulta existe sobre aquela alegação, e o
       nome `InteracaoRegistro` não aparecia no arquivo.

    Ela é uma rede, não uma prova. Serve para a leitura NOVA não nascer
    esquecida; as duas acima pedem revisão humana.
    """
    culpados: list[str] = []

    for caminho in sorted(APP.rglob("*.py")):
        relativo = caminho.relative_to(APP).as_posix()
        if relativo in LEITURAS_SEM_FILTRO:
            continue

        fonte = caminho.read_text(encoding="utf-8")
        if "InteracaoRegistro" not in fonte:
            continue
        if any(marca in fonte for marca in MARCAS_DE_DECISAO):
            continue
        culpados.append(relativo)

    assert culpados == [], (
        "Estes módulos leem `interacao` e não dizem nada sobre o sensível. "
        "Apliquem `condicoes()`, citem `sensivel`, ou entrem em "
        "`LEITURAS_SEM_FILTRO` com o motivo:\n  " + "\n  ".join(culpados)
    )


def test_as_guardas_reconhecem_o_que_existem_para_pegar():
    """Guarda de fonte que nunca viu um positivo pode ter parado de casar."""
    assert re.search(
        r"papel\s*\.\s*ve_campos_sensiveis", "if usuario.papel.ve_campos_sensiveis:"
    )
    assert not re.search(
        r"papel\s*\.\s*ve_campos_sensiveis",
        "alcanca_sensivel=usuario.ve_campos_sensiveis,",
    )

    assert re.search(
        r"alcanca_sensivel\s*=\s*(True|False)\b", "condicoes(r, alcanca_sensivel=True)"
    )
    assert not re.search(
        r"alcanca_sensivel\s*=\s*(True|False)\b",
        "condicoes(r, alcanca_sensivel=usuario.ve_campos_sensiveis)",
    )


def test_as_guardas_estao_olhando_para_os_arquivos_de_verdade():
    arquivos = list(APP.rglob("*.py"))
    assert len(arquivos) > 50
    assert any(
        "alcanca_sensivel" in a.read_text(encoding="utf-8") for a in arquivos
    )
